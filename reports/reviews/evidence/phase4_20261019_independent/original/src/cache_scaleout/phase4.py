"""Phase 4 calibration and immediate-cutover experiment.

This module intentionally implements one baseline only: old caches are warmed,
the destination is physically empty, and every affected bucket moves atomically
at a fixed time with no donor copy, DB warm-up, delete, or diagnostic miss.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

import yaml

from .adapters import PostgresDatabaseAdapter, PressureLimits, RedisCacheAdapter
from .contracts import BucketAdvance, BucketState, DataSource, EventKind, EventPhase, EventRecord, ResourceLimits, RetryPolicy, RoutingEpoch, json_record
from .dataset import StableOwnershipMap, create_dataset
from .evidence import ROOT, source_fingerprint, utc_now, write_json
from .issuance import issuing
from .load import sleep_until_ns
from .observations import BoundedDemandTracker
from .router import CacheAsideRouter
from .sampling import PressureSampler
from .telemetry import JsonlMetricsSink, reconcile_offers


def load_phase4_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict) or config.get('schema_version') != 1 or config.get('provisional') is not True:
        raise ValueError('Phase 4 config schema_version 1 and provisional=true required')
    if config['dataset']['keys'] < 128 or config['routing']['virtual_buckets'] < 32:
        raise ValueError('Phase 4 requires a workload beyond the Phase 3 smoke scale')
    if not (0 < config['workload']['affected_share'] <= 1 and config['workload']['zipf_exponent'] > 0):
        raise ValueError('valid workload skew and affected share required')
    if config['resources']['max_pending_metric_records'] < 1000:
        raise ValueError('bounded telemetry capacity too small for this declared run')
    return config


def _retry(config: dict[str, Any], name: str) -> RetryPolicy:
    item = config['retries'][name]
    return RetryPolicy(item['max_attempts'], item['attempt_timeout_seconds'], tuple(item['backoff_seconds']))


def _git_state() -> dict[str, Any]:
    def call(args: list[str]) -> str:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else 'unavailable:' + result.stderr.strip()
    return {'revision': call(['git','rev-parse','HEAD']), 'status_porcelain': call(['git','status','--short']),
            'describe': call(['git','log','-1','--oneline'])}


def _event(run_id: str, origin_ns: int, phase: EventPhase, epoch: int, kind: EventKind,
           reason: str, detail: dict[str, Any] | None = None) -> EventRecord:
    return EventRecord(1, run_id, utc_now(), time.monotonic_ns() - origin_ns, phase, RoutingEpoch(epoch),
                       kind, None, 'phase4_immediate' if kind is EventKind.POLICY_ACTION else None,
                       {}, reason, {}, detail or {})


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = int(position), min(len(ordered) - 1, int(position) + 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _window_summary(records: list[dict[str, Any]], begin_ns: int, end_ns: int, target_ms: float) -> dict[str, Any]:
    rows = [row for row in records if begin_ns <= row['scheduled_arrival_ns'] < end_ns]
    successful = [((row['completed_ns'] - row['scheduled_arrival_ns']) / 1e6) for row in rows
                  if row['outcome'] == 'completed' and row.get('completed_ns') is not None]
    violations = sum(row['outcome'] != 'completed' or row.get('completed_ns') is None or
                     ((row['completed_ns'] - row['scheduled_arrival_ns']) / 1e6) > target_ms for row in rows)
    return {'offered': len(rows), 'submitted': sum(row.get('submitted_ns') is not None for row in rows),
            'completed': sum(row['outcome'] == 'completed' for row in rows),
            'successful_p50_ms': _percentile(successful, .50), 'successful_p95_ms': _percentile(successful, .95),
            'successful_p99_ms': _percentile(successful, .99), 'all_offer_latency_violations': violations,
            'all_offer_violation_fraction': (violations / len(rows)) if rows else None,
            'database_attempts': sum(row.get('database_attempts', 0) for row in rows),
            'new_cache_reads': sum(row.get('source') == 'new_cache' for row in rows),
            'old_cache_reads': sum(row.get('source') == 'old_cache' for row in rows)}


def _zipf_keys(items: list[Any], count: int, seed: int) -> list[Any]:
    # Deterministic inverse-CDF approximation; no future trace information.
    total = sum(1.0 / ((index + 1) ** 1.15) for index in range(len(items)))
    cumulative: list[float] = []
    result: list[Any] = []
    running = 0.0
    for index in range(len(items)):
        running += (1.0 / ((index + 1) ** 1.15)) / total
        cumulative.append(running)
    state = seed & 0x7fffffff
    for _ in range(count):
        state = (1103515245 * state + 12345) & 0x7fffffff
        value = state / 0x80000000
        for index, edge in enumerate(cumulative):
            if value <= edge:
                result.append(items[index])
                break
    return result


async def _open_environment(config: dict[str, Any], run_id: str, *, require_empty: bool) -> tuple[Any, Any, Any, Any, Any, dict[str, Any]]:
    dataset = create_dataset(seed=config['dataset']['seed'], key_count=config['dataset']['keys'], value_bytes=config['dataset']['value_bytes'])
    routing = config['routing']
    ownership = StableOwnershipMap(mapping_seed=routing['mapping_seed'], bucket_count=routing['virtual_buckets'],
                                  old_nodes=tuple(routing['old_nodes']), final_nodes=tuple(routing['final_nodes']), destination=routing['destination'])
    cache_config, db_config = config['services']['cache'], config['services']['database']
    pressure = PressureLimits(1000.0, .99)
    caches = {node: RedisCacheAdapter(node_id=node, host=cache_config['host'], port=port, namespace='phase4:' + run_id,
              max_connections=config['resources']['foreground_cache_connections_per_node'], socket_timeout_seconds=cache_config['socket_timeout_seconds'],
              pressure_limits=pressure, is_destination=node == routing['destination'])
              for node, port in zip(routing['final_nodes'], cache_config['ports'], strict=True)}
    password = os.environ.get(db_config['password_env'], 'paper2-disposable-local-only')
    database = PostgresDatabaseAdapter(connection_kwargs={'host':db_config['host'],'port':db_config['port'],'dbname':db_config['dbname'],
        'user':db_config['user'],'password':password,'connect_timeout':db_config['pool_timeout_seconds']},
        foreground_max_size=config['resources']['foreground_db_connections'], background_max_size=config['resources']['background_db_connections'],
        pool_timeout_seconds=db_config['pool_timeout_seconds'], statement_timeout_ms=db_config['statement_timeout_ms'], pressure_latency_upper_ms=1000.0,
        query_cpu_rounds=db_config['query_cpu_rounds'])
    await database.open()
    deadline = time.monotonic_ns() + 30_000_000_000
    services = {node: await client.service_summary(deadline_ns=deadline) for node, client in caches.items()}
    if len({entry['server_run_id'] for entry in services.values()}) != 3:
        raise RuntimeError('cache endpoints are not independent')
    if require_empty and any(entry['physical_key_count'] or entry['evicted_keys'] for entry in services.values()):
        raise RuntimeError('physical caches are not empty; recreate disposable services before this run')
    if any(entry['maxmemory'] != cache_config['maxmemory_bytes'] or entry['maxmemory_policy'] != cache_config['eviction_policy'] for entry in services.values()):
        raise RuntimeError('cache resource configuration mismatch')
    await database.prepare_dataset(dataset.items, deadline_ns=deadline)
    for item in dataset.items:
        bucket = ownership.bucket_for_key(item.key)
        await caches[str(ownership.old_owner(bucket))].write(item.key, item.cache_value(), deadline_ns=deadline)
    initial = {node: await client.namespace_summary(deadline_ns=deadline) for node,client in caches.items()}
    destination = str(routing['destination'])
    if initial[destination]:
        raise RuntimeError('destination must begin healthy and physically/logically empty')
    return dataset, ownership, caches, database, services, initial


async def _close(caches: dict[str, Any], database: Any) -> None:
    for cache in caches.values():
        await cache.close()
    await database.close()


async def run_calibration(config: dict[str, Any], config_path: Path, run_id: str, rate: float) -> int:
    run_dir = ROOT / 'runs' / run_id
    if run_dir.exists(): raise ValueError('run ID already exists')
    run_dir.mkdir(parents=True)
    started = None
    dataset = ownership = caches = database = None
    try:
        dataset, ownership, caches, database, services, initial = await _open_environment(config, run_id, require_empty=True)
        write_json(run_dir/'effective_config.json', config); write_json(run_dir/'source.json', source_fingerprint())
        write_json(run_dir/'manifest.json', {'run_id':run_id,'kind':'calibration','started_utc':utc_now(),'rate':rate,'git':_git_state(),
            'config_path':str(config_path),'source_fingerprint':source_fingerprint()['aggregate_sha256'],'initial_service_state':services})
        # Dataset creation, provenance capture and cache population are all
        # preparation, not open-loop measurement.
        started = time.monotonic_ns()
        items = list(dataset.items)
        duration, first = config['timing']['calibration_seconds'], config['timing']['first_arrival_seconds']
        count = int(rate * duration)
        schedule = [{'request_id':f'cal-{i:05d}','key':str(items[i % len(items)].key),
                     'scheduled_arrival_ns':started + int((first + i/rate)*1e9)} for i in range(count)]
        write_json(run_dir/'offered_schedule.json', {'origin_ns':started,'requests':schedule})
        records: list[dict[str, Any]] = []
        async def one(offer: dict[str, Any]) -> None:
            await sleep_until_ns(offer['scheduled_arrival_ns']); submitted=time.monotonic_ns(); issued=None; outcome='completed'; completed=None
            def mark():
                nonlocal issued
                issued=time.monotonic_ns()
            try:
                with issuing(mark):
                    await database.read_foreground(offer['key'], deadline_ns=offer['scheduled_arrival_ns'] + int(config['timing']['request_timeout_seconds']*1e9))
            except TimeoutError: outcome='timed_out'
            except Exception as error: outcome='failed'; error_name=type(error).__name__
            completed=time.monotonic_ns()
            records.append({**offer,'submitted_ns':submitted,'issued_ns':issued,'completed_ns':completed,'outcome':outcome,
                            **({'error':error_name} if outcome=='failed' else {})})
        tasks=[asyncio.create_task(one(offer)) for offer in schedule]
        await asyncio.gather(*tasks)
        records.sort(key=lambda row: row['request_id'])
        (run_dir/'requests.jsonl').write_text(''.join(json.dumps(row,sort_keys=True)+'\n' for row in records),encoding='utf-8')
        target=config['timing']['latency_target_ms']; summary=_window_summary(records, started, started+int((first+duration)*1e9), target)
        summary.update({'rate':rate,'issued':sum(row['issued_ns'] is not None for row in records),'duration_seconds':duration,
                        'db_pool':database.pool_summary(),'cache_services':{node:await c.service_summary(deadline_ns=time.monotonic_ns()+5_000_000_000) for node,c in caches.items()}})
        write_json(run_dir/'result.json',summary); write_json(run_dir/'status.json',{'status':'completed','ended_utc':utc_now()}); return 0
    except Exception as error:
        write_json(run_dir/'status.json',{'status':'infrastructure_failure','ended_utc':utc_now(),'error':repr(error)}); raise
    finally:
        if caches is not None: await _close(caches,database)


async def run_immediate(config: dict[str, Any], config_path: Path, run_id: str, offered_rate: float, condition: str) -> int:
    if condition not in {'control','immediate'}: raise ValueError('condition must be control or immediate')
    run_dir = ROOT/'runs'/run_id
    if run_dir.exists(): raise ValueError('run ID already exists')
    metrics=JsonlMetricsSink(run_dir,capacity=config['resources']['max_pending_metric_records']); await metrics.start()
    started=None; dataset=ownership=caches=database=sampler=None
    try:
        dataset, ownership, caches, database, services, initial = await _open_environment(config,run_id,require_empty=True)
        write_json(run_dir/'effective_config.json',config); write_json(run_dir/'source.json',source_fingerprint())
        write_json(run_dir/'manifest.json',{'run_id':run_id,'kind':'immediate_cutover','condition':condition,'started_utc':utc_now(),'offered_rate':offered_rate,
            'git':_git_state(),'config_path':str(config_path),'source_fingerprint':source_fingerprint()['aggregate_sha256'],
            'initial_service_state':services,'initial_logical_state':initial,'phase3_diagnostics_enabled':False})
        by_key=dataset.by_key(); grouped=ownership.keys_by_bucket(dataset)
        # Reproducible warm prefix: all old-resident keys are written, then the
        # fixed prefix is read from Redis and must have zero misses and evictions.
        prefix=[dataset.items[i % len(dataset.items)] for i in range(config['workload']['warm_prefix_requests'])]
        prefix_misses=0
        deadline=time.monotonic_ns()+10_000_000_000
        for item in prefix:
            owner=str(ownership.old_owner(ownership.bucket_for_key(item.key)))
            if (await caches[owner].read(item.key,source=DataSource.OLD_CACHE,deadline_ns=deadline)).value is None: prefix_misses += 1
        if prefix_misses > config['workload']['warm_prefix_max_misses']: raise RuntimeError('old-cache warm stability criterion failed')
        # The reproducible old-cache prefix is outside the expansion interval.
        started=time.monotonic_ns()
        tracker=BoundedDemandTracker(subwindow_ns=1_000_000_000,retained_subwindows=16,max_total_keys=config['dataset']['keys'],
            max_keys_per_bucket=config['dataset']['keys'],max_buckets=config['routing']['virtual_buckets'],max_age_ns=20_000_000_000,origin_ns=started)
        tracker.register({bucket:{item.key:item.object_bytes for item in rows} for bucket,rows in grouped.items()})
        limits=ResourceLimits(**config['resources'])
        router=CacheAsideRouter(run_id=run_id,ownership=ownership,caches=caches,database=database,demand_tracker=tracker,metrics=metrics,limits=limits,
            cache_retry=_retry(config,'foreground_cache'),db_retry=_retry(config,'foreground_database'),fill_write_retry=_retry(config,'foreground_fill_write'),
            cleanup_timeout_seconds=config['timing']['cleanup_timeout_seconds'])
        async def observe(row):
            await metrics.emit_event(_event(run_id,started,EventPhase.HANDOVER,int(ownership.snapshot.epoch),EventKind.OBSERVATION,'common_phase4_sample',row),deadline_ns=time.monotonic_ns()+1_000_000_000)
        sampler=PressureSampler(caches=caches,database=database,key=dataset.items[0].key,interval_seconds=config['timing']['observation_interval_seconds'],timeout_seconds=config['timing']['observation_timeout_seconds'],on_round=observe,maximum_rounds=32)
        await sampler.start()
        duration=config['timing']['expansion_seconds']; first=config['timing']['first_arrival_seconds']; count=int(offered_rate*duration)
        affected=[item for bucket in ownership.affected_buckets for item in grouped[bucket]]; unaffected=[item for item in dataset.items if ownership.bucket_for_key(item.key) not in ownership.affected_buckets]
        selected=[]
        affected_zipf=_zipf_keys(affected,max(1,int(count*config['workload']['affected_share'])),config['dataset']['seed'])
        unaffected_zipf=_zipf_keys(unaffected,max(1,count-len(affected_zipf)),config['dataset']['seed']+1)
        for index in range(count): selected.append(affected_zipf[index%len(affected_zipf)] if index % 5 else unaffected_zipf[index%len(unaffected_zipf)])
        schedule=[{'request_id':f'app-{i:05d}','key':str(item.key),'scheduled_arrival_ns':started+int((first+i/offered_rate)*1e9)} for i,item in enumerate(selected)]
        write_json(run_dir/'offered_schedule.json',{'origin_ns':started,'requests':schedule,'schedule_sha256':hashlib.sha256(json.dumps(schedule,sort_keys=True).encode()).hexdigest()})
        async def arrive(offer):
            await metrics.emit_event(_event(run_id,started,EventPhase.PRE_EVENT if time.monotonic_ns()<started+int(config['timing']['expansion_at_seconds']*1e9) else EventPhase.POST_HANDOVER,int(ownership.snapshot.epoch),EventKind.ARRIVAL_SCHEDULED,'open_loop_offer',offer),deadline_ns=time.monotonic_ns()+1_000_000_000)
        async def dispatch():
            tasks=[]
            for offer in schedule:
                await sleep_until_ns(offer['scheduled_arrival_ns']); await arrive(offer); item=by_key[offer['key']]
                tasks.append(asyncio.create_task(router.read(request_id=offer['request_id'],key=item.key,scheduled_arrival_ns=offer['scheduled_arrival_ns'],timeout_seconds=config['timing']['request_timeout_seconds'],object_bytes=item.object_bytes)))
            await asyncio.gather(*tasks); await router.finalize_requests()
        async def cutover():
            if condition == 'control': return
            at=started+int(config['timing']['expansion_at_seconds']*1e9); await sleep_until_ns(at)
            advances=tuple(BucketAdvance(bucket,BucketState.OLD,(BucketState.COPYING,BucketState.ELIGIBLE,BucketState.NEW)) for bucket in ownership.affected_buckets)
            epoch=ownership.publish(advances,expected_epoch=ownership.snapshot.epoch)
            await metrics.emit_event(_event(run_id,started,EventPhase.HANDOVER,int(epoch),EventKind.BUCKET_TRANSITION,'atomic_immediate_cutover',{'affected_buckets':len(advances),'destination_pre_warmed':False}),deadline_ns=time.monotonic_ns()+1_000_000_000)
        await asyncio.gather(dispatch(),cutover())
        await sampler.close(); await asyncio.sleep(.05)
        await metrics.close(deadline_ns=time.monotonic_ns()+5_000_000_000)
        requests=[json.loads(line) for line in (run_dir/'requests.jsonl').read_text(encoding='utf-8').splitlines() if line]
        recon=reconcile_offers(tuple(schedule),requests)
        if not recon.complete: raise RuntimeError('offer reconciliation failed: '+','.join(recon.reasons))
        target=config['timing']['latency_target_ms']; cut=started+int(config['timing']['expansion_at_seconds']*1e9); end=started+int((first+duration)*1e9)
        result={'condition':condition,'offered_rate':offered_rate,'warm_prefix':{'requests':len(prefix),'misses':prefix_misses,'criterion':'zero direct Redis misses; no evictions before experiment'},
                'pre_event':_window_summary(requests,started,cut,target),'transition':_window_summary(requests,cut,cut+2_000_000_000,target),'post_event':_window_summary(requests,cut+2_000_000_000,end,target),
                'reconciliation':json_record(recon),'router':{'maximum_inflight':router.maximum_inflight,'maximum_coalesced_keys':router.maximum_coalesced_keys,'operations':router.ledger.records},
                'observations':sampler.rounds,'database_pool':database.pool_summary(),'cache_final':{node:await cache.service_summary(deadline_ns=time.monotonic_ns()+5_000_000_000) for node,cache in caches.items()},
                'routing':ownership.summary()}
        write_json(run_dir/'result.json',result); write_json(run_dir/'status.json',{'status':'completed','ended_utc':utc_now()}); return 0
    except Exception as error:
        try: await metrics.close(deadline_ns=time.monotonic_ns()+1_000_000_000)
        except Exception: pass
        write_json(run_dir/'status.json',{'status':'infrastructure_failure','ended_utc':utc_now(),'error':repr(error)}); raise
    finally:
        if sampler is not None: await sampler.close()
        if caches is not None: await _close(caches,database)
