"""Phase 4 calibration and immediate-cutover experiment.

This module intentionally implements one baseline only: old caches are warmed,
the destination is physically empty, and every affected bucket moves atomically
at a fixed time with no donor copy, DB warm-up, delete, or diagnostic miss.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
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
    if 'warm_stability' not in config:
        raise ValueError('explicit latency/hit warm_stability required; use configs/phase4_review.yaml')
    for name in ('calibration_seconds','expansion_seconds','observation_interval_seconds','request_timeout_seconds'):
        if not math.isfinite(config['timing'][name]) or config['timing'][name] <= 0:
            raise ValueError('finite positive timing required')
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


def _zipf_keys(items: list[Any], count: int, seed: int, exponent: float = 1.15) -> list[Any]:
    # Deterministic inverse-CDF approximation; no future trace information.
    if not items or not math.isfinite(exponent) or exponent <= 0:
        raise ValueError('nonempty population and finite positive exponent required')
    total = sum(1.0 / ((index + 1) ** exponent) for index in range(len(items)))
    cumulative: list[float] = []
    result: list[Any] = []
    running = 0.0
    for index in range(len(items)):
        running += (1.0 / ((index + 1) ** exponent)) / total
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


def select_workload(affected, unaffected, count, share, exponent, seed):
    """Exact rounded affected count, independently sampled within each stratum."""
    if not 0 < share <= 1 or count < 1:
        raise ValueError('positive count and affected share required')
    n = round(count * share)
    a = iter(_zipf_keys(affected, n, seed, exponent))
    b = iter(_zipf_keys(unaffected, count - n, seed + 1, exponent)) if count > n else iter(())
    return [next(a) if (i+1)*n//count > i*n//count else next(b) for i in range(count)]


class ReviewMetrics(JsonlMetricsSink):
    """Measure durable writer queue and producer wait without changing its bounds."""
    def __init__(self, directory, *, capacity):
        super().__init__(directory, capacity=capacity)
        self.maximum_queue = 0
        self.maximum_emit_ms = 0.0

    async def _emit(self, kind, record, deadline_ns):
        begin = time.perf_counter_ns()
        await super()._emit(kind, record, deadline_ns)
        self.maximum_queue = max(self.maximum_queue, self.queue.qsize())
        self.maximum_emit_ms = max(self.maximum_emit_ms, (time.perf_counter_ns()-begin)/1e6)


async def _headroom(stop, records):
    """QPC lag/CPU is supplemental; absolute runtime timestamps remain monotonic."""
    while not stop.is_set():
        begin = time.perf_counter_ns()
        try:
            await asyncio.wait_for(stop.wait(), .05)
        except TimeoutError:
            records.append(max(0, (time.perf_counter_ns()-begin)/1e6-50))


async def _stop_sampler_at(sampler, horizon_ns):
    await sleep_until_ns(horizon_ns)
    await sampler.close()


async def _prepare_measurement(config, dataset, ownership, caches, database):
    # Explicit connection/query preparation, outside the offered workload.
    await asyncio.gather(*(database.read_foreground(item.key, deadline_ns=time.monotonic_ns()+10_000_000_000)
                           for item in dataset.items[:config['resources']['foreground_db_connections']]))
    warm = config['warm_stability']
    windows = []
    for _ in range(warm['windows']):
        origin = time.monotonic_ns()
        async def one(index):
            await sleep_until_ns(origin + int(index/warm['rate']*1e9))
            item = dataset.items[index % len(dataset.items)]
            owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
            begin = time.perf_counter_ns()
            result = await caches[owner].read(item.key, source=DataSource.OLD_CACHE,
                deadline_ns=time.monotonic_ns()+1_000_000_000)
            return {'key':str(item.key), 'hit':result.value is not None,
                    'payload_ok':result.value is not None and result.value.payload == item.payload,
                    'latency_ms':(time.perf_counter_ns()-begin)/1e6}
        rows = await asyncio.gather(*(one(i) for i in range(round(warm['rate']*warm['seconds']))))
        await sleep_until_ns(origin+int(warm['seconds']*1e9))
        windows.append({'requests':rows, 'p95_ms':_percentile([r['latency_ms'] for r in rows], .95)})
    p95 = [r['p95_ms'] for r in windows]
    valid = (all(r['hit'] and r['payload_ok'] for w in windows for r in w['requests'])
             and max(p95) <= warm['maximum_p95_ms']
             and max(p95)-min(p95) <= warm['maximum_p95_spread_ms'])
    if not valid:
        raise RuntimeError('prespecified hit/latency warm stability failed: '+repr(p95))
    verified_database=await database.verify_dataset(deadline_ns=time.monotonic_ns()+5_000_000_000)
    if verified_database['count']!=len(dataset.items) or verified_database['actual_payload_checksum']!=dataset.checksum:
        raise ValueError('complete authoritative dataset mismatch')
    services={n:await c.service_summary(deadline_ns=time.monotonic_ns()+5_000_000_000) for n,c in caches.items()}
    if any(s['evicted_keys'] for s in services.values()) or services[config['routing']['destination']]['physical_key_count']:
        raise ValueError('pre-event reset/eviction/destination mismatch')
    return {'windows':windows, 'valid':valid, 'criterion':warm,'cache_services':services,'database_verification':verified_database,
            'foreground_db_preparation_reads':config['resources']['foreground_db_connections']}


def _measurement_accounting(caches, database):
    return {'database_probes':database.probe_records,
            'cache_probes':{node:cache._phase4_observer.probe_records for node,cache in caches.items()},
            'competing_application_db_reads':0, 'discretionary_db_warmup_reads':0,
            'donor_copy_reads':0, 'diagnostic_forced_misses':0,
            'wire_bytes_measured':False}


async def _resource_snapshot():
    executable=os.environ.get('PAPER2_DOCKER')
    if not executable:
        raise RuntimeError('use phase4_run.ps1: measured container resource counters required')
    async def one(service):
        def collect():
            result=subprocess.run([executable,'exec','paper2-research-'+service+'-1','cat','/sys/fs/cgroup/cpu.stat'],
                capture_output=True,text=True,timeout=5,check=True)
            observed=time.monotonic_ns()
            limits=subprocess.run([executable,'inspect','--format','{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}} {{.Config.Image}}','paper2-research-'+service+'-1'],
                capture_output=True,text=True,timeout=5,check=True).stdout.strip().split()
            return {'observed_ns':observed, 'cpu_stat':{k:int(v) for k,v in (line.split() for line in result.stdout.splitlines())},
                    'nano_cpus':int(limits[0]),'memory_limit_bytes':int(limits[1]),'image':limits[2]}
        return service,await asyncio.to_thread(collect)
    return dict(await asyncio.gather(*(one(s) for s in ('database','cache-old-1','cache-old-2','cache-new'))))


def _seal_run(directory):
    write_json(directory/'checksums.json', {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir()) if p.is_file() and p.name != 'checksums.json'})


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
    for node, port in zip(routing['final_nodes'], cache_config['ports'], strict=True):
        observer = RedisCacheAdapter(node_id=node, host=cache_config['host'], port=port, namespace='phase4:' + run_id,
            max_connections=config['resources']['background_cache_connections_per_node'],
            socket_timeout_seconds=cache_config['socket_timeout_seconds'], pressure_limits=pressure,
            is_destination=node == routing['destination'])
        caches[node]._phase4_observer = observer
        observer.pressure_peers = [observer, caches[node]]
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
    expected = {node:{} for node in caches}
    for item in dataset.items:
        owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
        expected[owner][str(item.key)] = {'payload_sha256':hashlib.sha256(item.payload).hexdigest(),
            'payload_bytes':item.object_bytes, 'absolute_expiry_ns':item.absolute_expiry_ns}
    # namespace_summary includes exact payload hashes and expiry for every key.
    for node, entries in initial.items():
        if {row['key'] for row in entries} != set(expected[node]):
            raise RuntimeError('complete initial key population mismatch')
        for row in entries:
            if hashlib.sha256(bytes.fromhex(row['payload_hex'])).hexdigest() != expected[node][row['key']]['payload_sha256'] or row['ttl_ms'] is not None:
                raise RuntimeError('initial payload mismatch')
    destination = str(routing['destination'])
    if initial[destination]:
        raise RuntimeError('destination must begin healthy and physically/logically empty')
    return dataset, ownership, caches, database, services, initial


async def _close(caches: dict[str, Any], database: Any) -> None:
    for cache in caches.values():
        if hasattr(cache, '_phase4_observer'):
            await cache._phase4_observer.close()
        await cache.close()
    await database.close()


async def run_calibration(config: dict[str, Any], config_path: Path, run_id: str, rate: float) -> int:
    run_dir = ROOT / 'runs' / run_id
    if run_dir.exists(): raise ValueError('run ID already exists')
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError('finite positive rate required')
    if config['retries']['foreground_database']['max_attempts'] != 1:
        raise ValueError('direct DB calibration requires the common one-attempt query mix')
    metrics = ReviewMetrics(run_dir, capacity=config['resources']['max_pending_metric_records'])
    await metrics.start()
    started = None
    dataset = ownership = caches = database = sampler = None
    stop = asyncio.Event(); lag=[]; heartbeat=None
    try:
        dataset, ownership, caches, database, services, initial = await _open_environment(config, run_id, require_empty=True)
        warm = await _prepare_measurement(config, dataset, ownership, caches, database)
        write_json(run_dir/'warm_stability.json', warm)
        write_json(run_dir/'effective_config.json', config); write_json(run_dir/'source.json', source_fingerprint())
        write_json(run_dir/'manifest.json', {'schema_version':2,'run_id':run_id,'kind':'calibration','started_utc':utc_now(),'rate':rate,'git':_git_state(),
            'config_path':str(config_path),'source_fingerprint':source_fingerprint()['aggregate_sha256'],'initial_service_state':services,
            'initial_logical_state':initial,'replacement_of':config.get('evidence_replacements',{}),
            'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),'retry_of':os.environ.get('PAPER2_RETRY_OF')})
        # Dataset creation, provenance capture and cache population are all
        # preparation, not open-loop measurement.
        resources_before=await _resource_snapshot()
        started = time.monotonic_ns()
        cpu_start=time.process_time(); perf_start=time.perf_counter()
        heartbeat=asyncio.create_task(_headroom(stop,lag))
        async def observe(row):
            await metrics.emit_event(_event(run_id,started,EventPhase.PRE_EVENT,0,EventKind.OBSERVATION,'common_phase4_sample',row),deadline_ns=time.monotonic_ns()+1_000_000_000)
        sampler=PressureSampler(caches={n:c._phase4_observer for n,c in caches.items()},database=database,
            key=dataset.items[0].key,interval_seconds=config['timing']['observation_interval_seconds'],
            timeout_seconds=config['timing']['observation_timeout_seconds'],on_round=observe,maximum_rounds=128)
        await sampler.start()
        items = list(dataset.items)
        duration, first = config['timing']['calibration_seconds'], config['timing']['first_arrival_seconds']
        count = int(rate * duration)
        schedule = [{'request_id':f'cal-{i:05d}','key':str(items[i % len(items)].key),
                     'scheduled_arrival_ns':started + int((first + i/rate)*1e9)} for i in range(count)]
        write_json(run_dir/'offered_schedule.json', {'origin_ns':started,'requests':schedule})
        records: list[dict[str, Any]] = []
        async def one(offer: dict[str, Any]) -> None:
            await sleep_until_ns(offer['scheduled_arrival_ns'])
            await metrics.emit_event(_event(run_id,started,EventPhase.PRE_EVENT,0,EventKind.ARRIVAL_SCHEDULED,'open_loop_offer',offer),deadline_ns=time.monotonic_ns()+1_000_000_000)
            submitted=time.monotonic_ns(); issued=None; outcome='completed'; completed=None; payload_hash=None
            def mark():
                nonlocal issued
                if time.monotonic_ns()>=offer['scheduled_arrival_ns']+int(config['timing']['request_timeout_seconds']*1e9):
                    raise TimeoutError('calibration deadline expired before query issuance')
                issued=time.monotonic_ns()
            try:
                with issuing(mark):
                    value=await database.read_foreground(offer['key'], deadline_ns=offer['scheduled_arrival_ns'] + int(config['timing']['request_timeout_seconds']*1e9))
                    payload_hash=hashlib.sha256(value.payload).hexdigest()
                    if value.payload != dataset.by_key()[offer['key']].payload:
                        raise ValueError('authoritative payload mismatch')
            except TimeoutError: outcome='timed_out'
            except Exception as error: outcome='failed'; error_name=type(error).__name__+':'+str(error)
            completed=time.monotonic_ns()
            row={**offer,'submitted_ns':submitted,'issued_ns':issued,'completed_ns':completed,'outcome':outcome,
                 'payload_sha256':payload_hash,'database_attempts':int(issued is not None), **({'error':error_name} if outcome=='failed' else {})}
            records.append(row)
            # Persist each terminal independently; a later failure must not erase it.
            with (run_dir/'requests.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(json.dumps(row,sort_keys=True)+'\n')
        tasks=[asyncio.create_task(one(offer)) for offer in schedule]
        await asyncio.gather(*tasks,_stop_sampler_at(sampler,started+int((first+duration)*1e9)))
        await sleep_until_ns(started+int((first+duration)*1e9))
        await sampler.close(); stop.set(); await heartbeat
        await metrics.close(deadline_ns=time.monotonic_ns()+5_000_000_000)
        resources_after=await _resource_snapshot()
        records.sort(key=lambda row: row['request_id'])
        target=config['timing']['latency_target_ms']; summary=_window_summary(records, started, started+int((first+duration)*1e9), target)
        summary.update({'rate':rate,'issued':sum(row['issued_ns'] is not None for row in records),'duration_seconds':duration,
                        'db_pool':database.pool_summary(),'accounting':_measurement_accounting(caches,database),
                        'container_resources':{'before':resources_before,'after':resources_after},
                        'headroom':{'process_cpu_seconds':time.process_time()-cpu_start,'wall_seconds':time.perf_counter()-perf_start,
                            'event_loop_lag_ms':lag,'maximum_metric_queue':metrics.maximum_queue,'maximum_metric_emit_ms':metrics.maximum_emit_ms},
                        'cache_services':{node:await c.service_summary(deadline_ns=time.monotonic_ns()+5_000_000_000) for node,c in caches.items()}})
        status='infrastructure_failure' if database.pool_summary()['issuance_stopped'] else 'completed'
        write_json(run_dir/'result.json',summary); write_json(run_dir/'status.json',{'status':status,'ended_utc':utc_now()}); _seal_run(run_dir); return int(status!='completed')
    except Exception as error:
        write_json(run_dir/'status.json',{'status':'infrastructure_failure','ended_utc':utc_now(),'error':repr(error)}); raise
    finally:
        stop.set()
        if heartbeat is not None: await heartbeat
        if sampler is not None: await sampler.close()
        if caches is not None: await _close(caches,database)


async def run_immediate(config: dict[str, Any], config_path: Path, run_id: str, offered_rate: float, condition: str) -> int:
    if condition not in {'control','immediate'}: raise ValueError('condition must be control or immediate')
    run_dir = ROOT/'runs'/run_id
    if run_dir.exists(): raise ValueError('run ID already exists')
    if not math.isfinite(offered_rate) or offered_rate <= 0: raise ValueError('finite positive rate required')
    metrics=ReviewMetrics(run_dir,capacity=config['resources']['max_pending_metric_records']); await metrics.start()
    started=None; dataset=ownership=caches=database=sampler=None
    stop=asyncio.Event(); lag=[]; heartbeat=None; payload_checks=[]; transition=None
    try:
        dataset, ownership, caches, database, services, initial = await _open_environment(config,run_id,require_empty=True)
        warm=await _prepare_measurement(config,dataset,ownership,caches,database)
        write_json(run_dir/'warm_stability.json',warm)
        write_json(run_dir/'effective_config.json',config); write_json(run_dir/'source.json',source_fingerprint())
        write_json(run_dir/'manifest.json',{'schema_version':2,'run_id':run_id,'kind':'immediate_cutover','condition':condition,'started_utc':utc_now(),'offered_rate':offered_rate,
            'git':_git_state(),'config_path':str(config_path),'source_fingerprint':source_fingerprint()['aggregate_sha256'],
            'initial_service_state':services,'initial_logical_state':initial,'phase3_diagnostics_enabled':False,
            'replacement_of':config.get('evidence_replacements',{}),'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),
            'pair_id':os.environ.get('PAPER2_PAIR_ID'),'retry_of':os.environ.get('PAPER2_RETRY_OF')})
        by_key=dataset.by_key(); grouped=ownership.keys_by_bucket(dataset)
        # Reproducible warm prefix: all old-resident keys are written, then the
        # fixed prefix is read from Redis and must have zero misses and evictions.
        # The reproducible old-cache prefix is outside the expansion interval.
        resources_before=await _resource_snapshot()
        started=time.monotonic_ns()
        cpu_start=time.process_time(); perf_start=time.perf_counter()
        heartbeat=asyncio.create_task(_headroom(stop,lag))
        tracker=BoundedDemandTracker(subwindow_ns=1_000_000_000,retained_subwindows=16,max_total_keys=config['dataset']['keys'],
            max_keys_per_bucket=config['dataset']['keys'],max_buckets=config['routing']['virtual_buckets'],max_age_ns=20_000_000_000,origin_ns=started)
        tracker.register({bucket:{item.key:item.object_bytes for item in rows} for bucket,rows in grouped.items()})
        limits=ResourceLimits(**config['resources'])
        router=CacheAsideRouter(run_id=run_id,ownership=ownership,caches=caches,database=database,demand_tracker=tracker,metrics=metrics,limits=limits,
            cache_retry=_retry(config,'foreground_cache'),db_retry=_retry(config,'foreground_database'),fill_write_retry=_retry(config,'foreground_fill_write'),
            cleanup_timeout_seconds=config['timing']['cleanup_timeout_seconds'])
        async def observe(row):
            await metrics.emit_event(_event(run_id,started,EventPhase.HANDOVER,int(ownership.snapshot.epoch),EventKind.OBSERVATION,'common_phase4_sample',row),deadline_ns=time.monotonic_ns()+1_000_000_000)
        sampler=PressureSampler(caches={n:c._phase4_observer for n,c in caches.items()},database=database,key=dataset.items[0].key,interval_seconds=config['timing']['observation_interval_seconds'],timeout_seconds=config['timing']['observation_timeout_seconds'],on_round=observe,maximum_rounds=128)
        await sampler.start()
        duration=config['timing']['expansion_seconds']; first=config['timing']['first_arrival_seconds']; count=int(offered_rate*duration)
        affected=[item for bucket in ownership.affected_buckets for item in grouped[bucket]]; unaffected=[item for item in dataset.items if ownership.bucket_for_key(item.key) not in ownership.affected_buckets]
        selected=select_workload(affected,unaffected,count,config['workload']['affected_share'],config['workload']['zipf_exponent'],config['dataset']['seed'])
        schedule=[{'request_id':f'app-{i:05d}','key':str(item.key),'scheduled_arrival_ns':started+int((first+i/offered_rate)*1e9)} for i,item in enumerate(selected)]
        write_json(run_dir/'offered_schedule.json',{'origin_ns':started,'requests':schedule,'schedule_sha256':hashlib.sha256(json.dumps(schedule,sort_keys=True).encode()).hexdigest()})
        async def arrive(offer):
            await metrics.emit_event(_event(run_id,started,EventPhase.PRE_EVENT if time.monotonic_ns()<started+int(config['timing']['expansion_at_seconds']*1e9) else EventPhase.POST_HANDOVER,int(ownership.snapshot.epoch),EventKind.ARRIVAL_SCHEDULED,'open_loop_offer',offer),deadline_ns=time.monotonic_ns()+1_000_000_000)
        async def read_one(offer):
            item=by_key[offer['key']]
            qpc_begin=time.perf_counter_ns()
            response=await router.read(request_id=offer['request_id'],key=item.key,scheduled_arrival_ns=offer['scheduled_arrival_ns'],timeout_seconds=config['timing']['request_timeout_seconds'],object_bytes=item.object_bytes)
            payload_checks.append({'request_id':offer['request_id'],'payload_sha256':hashlib.sha256(response.value.payload).hexdigest() if response.value else None,
                'expected_sha256':hashlib.sha256(item.payload).hexdigest(),'service_ms_qpc':(time.perf_counter_ns()-qpc_begin)/1e6})
        async def dispatch():
            tasks=[]
            for offer in schedule:
                await sleep_until_ns(offer['scheduled_arrival_ns']); await arrive(offer); item=by_key[offer['key']]
                tasks.append(asyncio.create_task(read_one(offer)))
            await asyncio.gather(*tasks); await router.finalize_requests()
        async def cutover():
            nonlocal transition
            if condition == 'control': return
            at=started+int(config['timing']['expansion_at_seconds']*1e9); await sleep_until_ns(at)
            advances=tuple(BucketAdvance(bucket,BucketState.OLD,(BucketState.COPYING,BucketState.ELIGIBLE,BucketState.NEW)) for bucket in ownership.affected_buckets)
            epoch=ownership.publish(advances,expected_epoch=ownership.snapshot.epoch)
            transition={'requested_ns':at,'published_ns':time.monotonic_ns(),'expected_epoch':0,'epoch':int(epoch),
                'affected_buckets':[int(a.bucket) for a in advances], 'path':['copying','eligible','new'],'destination_pre_warmed':False}
            await metrics.emit_event(_event(run_id,started,EventPhase.HANDOVER,int(epoch),EventKind.BUCKET_TRANSITION,'atomic_immediate_cutover',transition),deadline_ns=time.monotonic_ns()+1_000_000_000)
        await asyncio.gather(dispatch(),cutover(),_stop_sampler_at(sampler,started+int((first+duration)*1e9)))
        await sleep_until_ns(started+int((first+duration)*1e9))
        await sampler.close(); stop.set(); await heartbeat
        await metrics.close(deadline_ns=time.monotonic_ns()+5_000_000_000)
        resources_after=await _resource_snapshot()
        requests=[json.loads(line) for line in (run_dir/'requests.jsonl').read_text(encoding='utf-8').splitlines() if line]
        recon=reconcile_offers(tuple(schedule),requests)
        if not recon.complete: raise RuntimeError('offer reconciliation failed: '+','.join(recon.reasons))
        target=config['timing']['latency_target_ms']; cut=started+int(config['timing']['expansion_at_seconds']*1e9); end=started+int((first+duration)*1e9)
        result={'condition':condition,'offered_rate':offered_rate,'warm_stability':warm,'transition_record':transition,
                'pre_event':_window_summary(requests,started,cut,target),'transition':_window_summary(requests,cut,cut+2_000_000_000,target),'post_event':_window_summary(requests,cut+2_000_000_000,end,target),
                'reconciliation':json_record(recon),'router':{'maximum_inflight':router.maximum_inflight,'maximum_coalesced_keys':router.maximum_coalesced_keys,'operations':router.ledger.records},
                'observations':sampler.rounds,'accounting':_measurement_accounting(caches,database),'payload_checks':payload_checks,
                'container_resources':{'before':resources_before,'after':resources_after},
                'headroom':{'process_cpu_seconds':time.process_time()-cpu_start,'wall_seconds':time.perf_counter()-perf_start,
                    'event_loop_lag_ms':lag,'maximum_metric_queue':metrics.maximum_queue,'maximum_metric_emit_ms':metrics.maximum_emit_ms},
                'database_pool':database.pool_summary(),'cache_final':{node:await cache.service_summary(deadline_ns=time.monotonic_ns()+5_000_000_000) for node,cache in caches.items()},
                'routing':ownership.summary()}
        status='infrastructure_failure' if database.pool_summary()['issuance_stopped'] else 'completed'
        write_json(run_dir/'result.json',result); write_json(run_dir/'status.json',{'status':status,'ended_utc':utc_now()}); _seal_run(run_dir); return int(status!='completed')
    except Exception as error:
        try: await metrics.close(deadline_ns=time.monotonic_ns()+1_000_000_000)
        except Exception: pass
        write_json(run_dir/'status.json',{'status':'infrastructure_failure','ended_utc':utc_now(),'error':repr(error)}); raise
    finally:
        stop.set()
        if heartbeat is not None: await heartbeat
        if sampler is not None: await sampler.close()
        if caches is not None: await _close(caches,database)
