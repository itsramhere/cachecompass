"""Deterministic functional Phase 3 run and artifact validation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
import math
from typing import Any

import yaml

from .adapters import PostgresDatabaseAdapter, PressureLimits, RedisCacheAdapter
from .contracts import (
    BucketAdvance, BucketState, ControllerAction, EventKind, EventPhase,
    EventRecord, ResourceLimits, RetryPolicy, RoutingEpoch, TransferBudget,
    json_record,
)
from .dataset import StableOwnershipMap, create_dataset
from .evidence import ROOT, source_fingerprint, utc_now, write_json
from .migration import BoundedMigrationScheduler
from .sampling import PressureSampler
from .load import dispatch_offers, sleep_until_ns
from .issuance import issuing
from .observations import BoundedDemandTracker, ResidencyTracker
from .router import CacheAsideRouter
from .telemetry import JsonlMetricsSink, reconcile_offers


class PolicyFailure(RuntimeError):
    """A finite functional pass or stability interval did not complete."""


def load_phase3_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Phase 3 config schema_version 1 required")
    if config.get('provisional') is not True:
        raise ValueError('Phase 3 accepts provisional functional configurations only')
    _limits(config)
    for name in ('foreground_cache', 'foreground_database', 'foreground_fill_write',
                 'donor_read', 'warmup_database', 'destination_write'):
        _retry(config, name)
    for name, value in config['timing'].items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('positive finite timing required: '+name)
    for name in ('migration_rates', 'migration_bursts'):
        if set(config[name]) != {'donor_operations', 'donor_bytes', 'background_db_operations',
                                'destination_write_operations', 'destination_write_bytes'}:
            raise ValueError('complete rate/burst dimensions required')
        for value in config[name].values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('finite nonnegative rates required')
            if name == 'migration_bursts' and (type(value) is not int or value < 1):
                raise ValueError('positive integer bursts required')
    maximum = config['dataset']['value_bytes'] + 1024
    if any(config['migration_bursts'][name] < maximum for name in ('donor_bytes', 'destination_write_bytes')):
        raise ValueError('byte burst cannot accommodate maximum encoded operation')
    if config['dataset']['value_bytes'] > config['resources']['max_buffered_payload_bytes']:
        raise ValueError('object exceeds payload memory bound')
    if config['dataset']['keys'] > config['observations']['max_total_keys']:
        raise ValueError('dataset exceeds bounded registry')
    dataset = create_dataset(seed=config['dataset']['seed'], key_count=config['dataset']['keys'],
                             value_bytes=config['dataset']['value_bytes'])
    mapping = config['routing']
    ownership = StableOwnershipMap(mapping_seed=mapping['mapping_seed'], bucket_count=mapping['virtual_buckets'],
        old_nodes=tuple(mapping['old_nodes']),final_nodes=tuple(mapping['final_nodes']),destination=mapping['destination'])
    observation = config['observations']
    tracker = BoundedDemandTracker(subwindow_ns=observation['subwindow_ns'],
        retained_subwindows=observation['retained_subwindows'], max_total_keys=observation['max_total_keys'],
        max_keys_per_bucket=observation['max_keys_per_bucket'], max_buckets=mapping['virtual_buckets'],
        max_age_ns=observation['max_age_ns'])
    tracker.register({bucket:{item.key:item.object_bytes for item in items}
                      for bucket,items in ownership.keys_by_bucket(dataset).items()})
    timing = config['timing']
    required_timing = ('observation_interval_seconds', 'observation_timeout_seconds',
        'expansion_at_seconds', 'task_lifetime_seconds', 'handover_deadline_seconds',
        'measurement_horizon_seconds', 'stability_start_seconds', 'stability_subwindow_seconds',
        'stability_subwindows', 'stability_min_requests')
    for name in required_timing:
        if name not in timing:
            raise ValueError('missing timing: '+name)
    for name in ('stability_subwindows','stability_min_requests'):
        if type(timing[name]) is not int or timing[name] < 1:
            raise ValueError('positive integer stability bounds required')
    offers = config['workload']['post_cutover_requests']
    if type(offers) is not int or offers < timing['stability_subwindows']*timing['stability_min_requests']:
        raise ValueError('functional schedule cannot satisfy stability sample minimum')
    if timing['measurement_horizon_seconds'] < timing['handover_deadline_seconds'] + timing['cleanup_timeout_seconds']:
        raise ValueError('measurement horizon omits deadline/drain allowance')
    if (type(observation['maximum_rounds']) is not int or observation['maximum_rounds'] <
            math.ceil(timing['measurement_horizon_seconds']/timing['observation_interval_seconds'])+2):
        raise ValueError('bounded observation history cannot cover the fixed horizon')
    if observation['probe_byte_ceiling'] != 65536:
        raise ValueError('functional probe byte ceiling must match the bounded adapters')
    if config['services']['cache']['host'] != '127.0.0.1' or config['services']['database']['host'] != '127.0.0.1':
        raise ValueError('Phase 3 supports verified local disposable services only')
    return config


def _retry(config: dict[str, Any], name: str) -> RetryPolicy:
    value = config["retries"][name]
    return RetryPolicy(value["max_attempts"], value["attempt_timeout_seconds"],
                       tuple(value.get("backoff_seconds", ())))


def _limits(config: dict[str, Any]) -> ResourceLimits:
    return ResourceLimits(**config["resources"])


def _event(run_id: str, origin_ns: int, *, phase: EventPhase, epoch: int,
           kind: EventKind, reason: str, bucket: int | None = None,
           accounting: dict[str, int] | None = None,
           detail: dict[str, Any] | None = None) -> EventRecord:
    return EventRecord(1, run_id, utc_now(), time.monotonic_ns() - origin_ns, phase,
                       RoutingEpoch(epoch), kind, bucket, "phase3_minimal" if kind is EventKind.POLICY_ACTION else None,
                       {}, reason, accounting or {}, detail or {})


async def _emit(metrics: JsonlMetricsSink, record: EventRecord, timeout_seconds: float) -> None:
    await metrics.emit_event(record, deadline_ns=time.monotonic_ns() + int(timeout_seconds * 1e9))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def run_phase3(config: dict[str, Any], config_path: Path, run_id: str,
                     retry_of: str | None = None) -> int:
    if not run_id or len(run_id) > 80 or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in run_id):
        raise ValueError("safe nonempty run ID required")
    if retry_of and not (ROOT / "runs" / retry_of / "manifest.json").is_file():
        raise ValueError("retry_of must reference a retained run manifest")
    run_dir = ROOT / "runs" / run_id
    metrics = JsonlMetricsSink(run_dir, capacity=config["resources"]["max_pending_metric_records"])
    await metrics.start()
    started_utc = utc_now()
    origin_ns = time.monotonic_ns()
    status = "infrastructure_failure"
    exit_code = 1
    error_record = None
    caches: dict[str, RedisCacheAdapter] = {}
    background_caches = {}
    sampler = None
    generator = None
    router = None
    migration = None
    ownership = None
    emitted_operation_ids = set()
    diagnostic_operations = []
    database: PostgresDatabaseAdapter | None = None
    artifacts: dict[str, Any] = {}
    try:
        write_json(run_dir / "effective_config.json", config)
        write_json(run_dir / "source.json", source_fingerprint())
        dataset_config = config["dataset"]
        dataset = create_dataset(seed=dataset_config["seed"], key_count=dataset_config["keys"],
                                 value_bytes=dataset_config["value_bytes"])
        routing = config["routing"]
        ownership = StableOwnershipMap(
            mapping_seed=routing["mapping_seed"], bucket_count=routing["virtual_buckets"],
            old_nodes=tuple(routing["old_nodes"]), final_nodes=tuple(routing["final_nodes"]),
            destination=routing["destination"])
        grouped = ownership.keys_by_bucket(dataset)
        affected_items = tuple(item for bucket in ownership.affected_buckets for item in grouped[bucket])
        if not affected_items:
            raise ValueError("small run needs affected keys")
        cache_config = config["services"]["cache"]
        namespace = f"phase3:{run_id}"
        node_ports = dict(zip(routing["final_nodes"], cache_config["ports"], strict=True))
        pressure = PressureLimits(config["provisional_pressure"]["cache_latency_upper_ms"],
                                  config["provisional_pressure"]["memory_upper_fraction"])
        for node, port in node_ports.items():
            caches[node] = RedisCacheAdapter(
                node_id=node, host=cache_config["host"], port=port, namespace=namespace,
                max_connections=config["resources"]["foreground_cache_connections_per_node"],
                socket_timeout_seconds=cache_config["socket_timeout_seconds"],
                pressure_limits=pressure, is_destination=node == routing['destination'])
        for node, port in node_ports.items():
            background_caches[node] = RedisCacheAdapter(
                node_id=node, host=cache_config["host"], port=port, namespace=namespace,
                max_connections=config["resources"]["background_cache_connections_per_node"],
                socket_timeout_seconds=cache_config["socket_timeout_seconds"], pressure_limits=pressure,
                is_destination=node == routing['destination'])
            background_caches[node].pressure_peers = [background_caches[node], caches[node]]
        db_config = config["services"]["database"]
        password = os.environ.get(db_config["password_env"], "paper2-disposable-local-only")
        database = PostgresDatabaseAdapter(
            connection_kwargs={"host": db_config["host"], "port": db_config["port"],
                               "dbname": db_config["dbname"], "user": db_config["user"],
                               "password": password, "connect_timeout": db_config["pool_timeout_seconds"]},
            foreground_max_size=config["resources"]["foreground_db_connections"],
            background_max_size=config["resources"]["background_db_connections"],
            pool_timeout_seconds=db_config["pool_timeout_seconds"],
            statement_timeout_ms=db_config["statement_timeout_ms"],
            pressure_latency_upper_ms=config["provisional_pressure"]["db_latency_upper_ms"])
        await database.open()
        deadline = time.monotonic_ns() + int(config["timing"]["run_timeout_seconds"] * 1e9)
        cache_services = {node: await client.service_summary(deadline_ns=deadline)
                          for node, client in caches.items()}
        if len({summary["server_run_id"] for summary in cache_services.values()}) != 3:
            raise RuntimeError("cache endpoints are not independent Redis instances")
        for summary in cache_services.values():
            if (summary["maxmemory"] != cache_config["maxmemory_bytes"]
                    or summary["maxmemory_policy"] != cache_config["eviction_policy"]):
                raise RuntimeError("Redis memory/eviction configuration mismatch")
            if summary['physical_key_count']:
                raise ValueError('physical cache not empty; recreate disposable instances before a run')
        database_service = await database.service_summary(deadline_ns=deadline)
        if database_service["database"] != db_config["dbname"] or database_service["user"] != db_config["user"]:
            raise RuntimeError("refusing dataset preparation on an unverified database")
        await database.prepare_dataset(dataset.items, deadline_ns=deadline)
        database_summary = await database.verify_dataset(deadline_ns=deadline)
        if (database_summary["count"] != len(dataset.items)
                or database_summary['actual_payload_checksum'] != dataset.checksum):
            raise RuntimeError("authoritative dataset count mismatch")
        for item in dataset.items:
            owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
            await caches[owner].write(item.key, item.cache_value(), deadline_ns=deadline)
        logical_caches = {node: await caches[node].namespace_summary(deadline_ns=deadline)
                          for node in routing["final_nodes"]}
        expected_initial = {node:[] for node in routing['final_nodes']}
        for item in dataset.items:
            expected_initial[str(ownership.old_owner(ownership.bucket_for_key(item.key)))].append(
                {'key':item.key,'payload_hex':item.payload.hex(),'ttl_ms':None})
        if logical_caches != expected_initial:
            raise ValueError('actual complete initial payload state differs from deterministic dataset')
        if logical_caches[routing["destination"]]:
            raise RuntimeError("destination cache is not empty at initial-state capture")
        expected_counts = {node: 0 for node in routing["old_nodes"]}
        for item in dataset.items:
            expected_counts[str(ownership.old_owner(ownership.bucket_for_key(item.key)))] += 1
        if any(len(logical_caches[node]) != count for node, count in expected_counts.items()):
            raise RuntimeError("complete old-cache initial state mismatch")
        cache_services = {node: await client.service_summary(deadline_ns=deadline)
                          for node, client in caches.items()}
        if any(summary['physical_key_count'] != expected_counts.get(node, 0)
               or summary['evicted_keys'] != 0 for node, summary in cache_services.items()):
            raise ValueError('physical initial state contains foreign or evicted keys')
        initial_state = {
            "logical_state": {
                "dataset_checksum": dataset.checksum,
                "mapping": ownership.summary(),
                "caches": logical_caches,
            },
            "service_state": {"caches": cache_services, "database": database_service},
        }
        write_json(run_dir / "initial_state.json", initial_state)
        tracker = BoundedDemandTracker(
            subwindow_ns=config["observations"]["subwindow_ns"],
            retained_subwindows=config["observations"]["retained_subwindows"],
            max_total_keys=config["observations"]["max_total_keys"],
            max_keys_per_bucket=config["observations"]["max_keys_per_bucket"],
            max_buckets=routing["virtual_buckets"], max_age_ns=config["observations"]["max_age_ns"],
            origin_ns=origin_ns)
        tracker.register({bucket: {item.key: item.object_bytes for item in items}
                          for bucket, items in grouped.items()})
        residency = ResidencyTracker(destination=routing["destination"],
                                     registered_keys=tuple(item.key for item in affected_items))
        router = CacheAsideRouter(
            run_id=run_id, ownership=ownership, caches=caches, database=database,
            demand_tracker=tracker, metrics=metrics, limits=_limits(config),
            cache_retry=_retry(config, "foreground_cache"),
            db_retry=_retry(config, "foreground_database"),
            fill_write_retry=_retry(config, "foreground_fill_write"),
            cleanup_timeout_seconds=config["timing"]["cleanup_timeout_seconds"], residency=residency)
        timing = config["timing"]
        workload_origin_ns = time.monotonic_ns()
        miss_item = affected_items[0]
        post_count = config["workload"]["post_cutover_requests"]
        schedule_items = tuple(affected_items[index % len(affected_items)] for index in range(post_count))
        relative_offers = [
            {"request_id": "pre-miss-0", "key": str(miss_item.key), "relative_arrival_ns": 50_000_000},
            {"request_id": "pre-miss-1", "key": str(miss_item.key), "relative_arrival_ns": 50_000_000}]
        relative_offers += [{"request_id": f"post-{index:03d}", "key": str(item.key),
            "relative_arrival_ns": int(timing["stability_start_seconds"]*1e9) + index*25_000_000}
            for index, item in enumerate(schedule_items)]
        schedule = tuple({**offer, "scheduled_arrival_ns": workload_origin_ns+offer["relative_arrival_ns"]}
                         for offer in relative_offers)
        write_json(run_dir / "offered_schedule.json", {"origin_ns": workload_origin_ns, "requests": schedule,
                   "checksum": hashlib.sha256(json.dumps(schedule, sort_keys=True,
                                                           separators=(",", ":")).encode()).hexdigest()})
        async def arrival(offer):
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.HANDOVER,
                epoch=int(ownership.snapshot.epoch), kind=EventKind.ARRIVAL_SCHEDULED,
                reason="independent_offered_schedule", detail=offer), timing["metric_timeout_seconds"])
        async def observation(row):
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.HANDOVER,
                epoch=int(ownership.snapshot.epoch), kind=EventKind.OBSERVATION,
                reason="fixed_common_pressure_round", detail=row), timing["metric_timeout_seconds"])
        async def force_miss(client, item, reason):
            row = {'operation_id':f'functional-diagnostic-{len(diagnostic_operations)+1}',
                   'task_id':reason, 'operation':'delete', 'source':'old_cache',
                   'target_owner':client.node_id, 'work_class':'functional_diagnostic_cache',
                   'absolute_deadline_ns':deadline, 'reserved_bytes':1024, 'actual_bytes':None,
                   'retry_ordinal':1, 'outcome':'failed'}
            def issue():
                row['issued_ns'] = time.monotonic_ns()
                diagnostic_operations.append(row)
            try:
                with issuing(issue):
                    await client.delete(item.key, deadline_ns=deadline)
                row['outcome'] = 'completed'
            except asyncio.CancelledError:
                row['outcome'] = 'cancelled'
                raise
            except TimeoutError:
                row['outcome'] = 'timed_out'
                raise
            finally:
                row['terminal_ns'] = time.monotonic_ns()
        sampler = PressureSampler(caches=background_caches, database=database, key=dataset.items[0].key,
            interval_seconds=timing["observation_interval_seconds"],
            timeout_seconds=timing["observation_timeout_seconds"], on_round=observation, residency=residency,
            maximum_rounds=config['observations']['maximum_rounds'])
        miss_owner = str(ownership.old_owner(ownership.bucket_for_key(miss_item.key)))
        await force_miss(background_caches[miss_owner], miss_item, 'force_foreground_miss')
        await sampler.start()
        generator = asyncio.create_task(dispatch_offers(schedule=schedule, router=router,
            items=dataset.by_key(), on_arrival=arrival, metrics=metrics,
            timeout_seconds=timing["foreground_timeout_seconds"],
            metric_timeout_seconds=timing["metric_timeout_seconds"]), name="independent-generator")
        await sleep_until_ns(workload_origin_ns+int(timing["expansion_at_seconds"]*1e9))
        expansion_ns = time.monotonic_ns()
        await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.HANDOVER,
                                    epoch=int(ownership.snapshot.epoch), kind=EventKind.POLICY_ACTION,
                                    reason="begin_selective_copy",
                                    detail={"affected_buckets": list(ownership.affected_buckets)}),
                    config["timing"]["metric_timeout_seconds"])
        advances = tuple(BucketAdvance(bucket, BucketState.OLD, (BucketState.COPYING,))
                         for bucket in ownership.affected_buckets)
        publication_epoch = ownership.publish(advances, expected_epoch=ownership.snapshot.epoch)
        for advance in advances:
            await _emit(metrics, _event(
                run_id, origin_ns, phase=EventPhase.HANDOVER, epoch=int(publication_epoch),
                kind=EventKind.BUCKET_TRANSITION, reason="migration_pass_started",
                bucket=int(advance.bucket),
                detail={"expected": advance.expected.value,
                        "path": [state.value for state in advance.path],
                        "publication_epoch": int(publication_epoch)}),
                config["timing"]["metric_timeout_seconds"])
        # Force exactly one donor miss so optional DB warming is exercised and charged.
        fallback_item = affected_items[-1]
        fallback_owner = str(ownership.old_owner(ownership.bucket_for_key(fallback_item.key)))
        await force_miss(background_caches[fallback_owner], fallback_item, 'force_migration_donor_miss')
        migration = BoundedMigrationScheduler(
            run_id=run_id, ownership=ownership,
            donor_caches={node: background_caches[node] for node in routing["old_nodes"]},
            destination_cache=background_caches[routing["destination"]], database=database,
            metrics=metrics, residency=residency,
            worker_limit=config["resources"]["migration_workers"],
            queue_limit=config["resources"]["max_pending_migration_tasks"],
            max_buffered_payload_bytes=config["resources"]["max_buffered_payload_bytes"],
            donor_retry=_retry(config, "donor_read"), db_retry=_retry(config, "warmup_database"),
            write_retry=_retry(config, "destination_write"),
            attempt_timeout_seconds=config["timing"]["migration_attempt_timeout_seconds"],
            rates=config["migration_rates"], bursts=config["migration_bursts"],
            max_operation_records=config['resources']['max_pending_metric_records'],
            cleanup_timeout_seconds=timing["cleanup_timeout_seconds"])
        grant_config = config["migration_grant"]
        now = time.monotonic_ns()
        action = ControllerAction(
            now, TransferBudget(grant_config["donor_operations"], grant_config["donor_bytes"],
                                grant_config["background_db_operations"],
                                grant_config["destination_write_operations"],
                                int(grant_config["valid_for_seconds"] * 1e9),
                                grant_config["destination_write_bytes"]),
            (), ("fixed_phase3_functional_grant",), ownership.snapshot.epoch, now)
        migration.apply_action(action)
        await _emit(metrics, _event(
            run_id, origin_ns, phase=EventPhase.HANDOVER, epoch=int(ownership.snapshot.epoch),
            kind=EventKind.POLICY_ACTION, reason="fixed_phase3_functional_grant",
            detail={"action": json_record(action), "settings_provisional": True}),
            config["timing"]["metric_timeout_seconds"])
        migration_results = await migration.migrate(affected_items, deadline_ns=min(
            expansion_ns+int(timing["task_lifetime_seconds"]*1e9),
            workload_origin_ns+int(timing["handover_deadline_seconds"]*1e9)))
        write_json(run_dir / 'migration_tasks.json', [
            {'key':result.key, 'bucket':result.bucket, 'disposition':result.disposition,
             'source':result.source, 'attempts':result.attempts, 'reason':result.reason}
            for result in migration_results])
        if any(result.disposition != "warmed" for result in migration_results):
            raise PolicyFailure("minimal migration pass did not warm every affected key")
        eligible_advances = tuple(BucketAdvance(bucket, BucketState.COPYING, (BucketState.ELIGIBLE,))
                                  for bucket in ownership.affected_buckets)
        publication_epoch = ownership.publish(eligible_advances, expected_epoch=ownership.snapshot.epoch)
        for advance in eligible_advances:
            await _emit(metrics, _event(
                run_id, origin_ns, phase=EventPhase.HANDOVER, epoch=int(publication_epoch),
                kind=EventKind.BUCKET_TRANSITION, reason="finite_pass_terminal",
                bucket=int(advance.bucket),
                detail={"expected": advance.expected.value,
                        "path": [state.value for state in advance.path],
                        "publication_epoch": int(publication_epoch)}),
                config["timing"]["metric_timeout_seconds"])
        new_advances = tuple(BucketAdvance(bucket, BucketState.ELIGIBLE, (BucketState.NEW,))
                             for bucket in ownership.affected_buckets)
        publication_epoch = ownership.publish(new_advances, expected_epoch=ownership.snapshot.epoch)
        for advance in new_advances:
            await _emit(metrics, _event(
                run_id, origin_ns, phase=EventPhase.HANDOVER, epoch=int(publication_epoch),
                kind=EventKind.BUCKET_TRANSITION, reason="foreground_ownership_admitted",
                bucket=int(advance.bucket),
                detail={"expected": advance.expected.value,
                        "path": [state.value for state in advance.path],
                        "publication_epoch": int(publication_epoch)}),
                config["timing"]["metric_timeout_seconds"])
        final_publication_ns = time.monotonic_ns()
        responses = await generator
        generator = None
        await sleep_until_ns(workload_origin_ns+int(timing["measurement_horizon_seconds"]*1e9))
        await sampler.close()
        await router.finalize_requests()
        for response in responses:
            expected = dataset.by_key()[response.record.key]
            if response.value is None or response.value.payload != expected.payload:
                raise ValueError("foreground authoritative payload check failed")
        write_json(run_dir / 'payload_checks.json', [
            {'request_id': response.record.request_id, 'key': response.record.key,
             'observed_sha256': hashlib.sha256(response.value.payload).hexdigest(),
             'expected_sha256': dataset.by_key()[response.record.key].version}
            for response in responses])
        miss_responses, post_responses = responses[:2], responses[2:]
        width = int(timing["stability_subwindow_seconds"]*1e9)
        stability_origin = workload_origin_ns+int(timing["stability_start_seconds"]*1e9)
        stability = []
        for index in range(timing["stability_subwindows"]):
            start_ns = stability_origin+index*width
            rows = [response.record for response in post_responses
                    if start_ns <= response.record.submitted_ns < start_ns+width]
            if (start_ns < final_publication_ns or len(rows) < timing["stability_min_requests"]
                    or any(row.route.owner != routing["destination"] or row.route.epoch != publication_epoch
                           for row in rows)):
                raise PolicyFailure("traffic_stability_inconclusive_or_wrong_owner")
            stability.append({"start_ns": start_ns, "end_ns": start_ns+width,
                              "submitted_affected": len(rows), "destination_share": 1.0,
                              "completed": sum(row.outcome.value == "completed" for row in rows)})
        if stability[-1]["end_ns"] > workload_origin_ns+int(timing["handover_deadline_seconds"]*1e9):
            raise PolicyFailure("handover_deadline_exceeded")
        write_json(run_dir / "stability.json", {"windows": stability,
                   "final_publication_ns": final_publication_ns, "measurement_ended_ns": time.monotonic_ns()})
        probe_records = [row for cache in background_caches.values() for row in cache.probe_records]
        probe_records += database.probe_records
        for operation in migration.operation_records + probe_records + diagnostic_operations:
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.TERMINAL,
                epoch=int(ownership.snapshot.epoch), kind=EventKind.ACCOUNTING,
                reason="issued_operation", accounting={"issued_operations": 1}, detail=operation),
                timing["metric_timeout_seconds"])
            emitted_operation_ids.add(operation['operation_id'])
        cache_pressure = {node: rows['state'] for node, rows in sampler.rounds[-1]['samples'].items()
                          if node != 'database'}
        db_pressure = sampler.rounds[-1]['samples']['database']['state']
        # Persist every foreground issued operation as one accounting event.
        for operation in router.ledger.records:
            await _emit(metrics, _event(
                run_id, origin_ns, phase=EventPhase.TERMINAL, epoch=int(ownership.snapshot.epoch),
                kind=EventKind.ACCOUNTING, reason="foreground_operation",
                accounting={"issued_operations": 1}, detail=operation),
                config["timing"]["metric_timeout_seconds"])
            emitted_operation_ids.add(operation['operation_id'])
        await metrics.flush(deadline_ns=time.monotonic_ns() + int(config["timing"]["flush_timeout_seconds"] * 1e9))
        request_rows = _read_jsonl(run_dir / "requests.jsonl")
        reconciliation = reconcile_offers(schedule, request_rows)
        foreground_db_attempts = sum(record["operation"] == "database_read" for record in router.ledger.records)
        migration_rows = _read_jsonl(run_dir / "migrations.jsonl")
        background_db_attempts = sum(row["work_class"] == "discretionary_database_warmup"
                                     for row in migration_rows)
        donor_attempts = sum(row["work_class"] == "donor_read" for row in migration_rows)
        destination_attempts = sum(row["work_class"] == "destination_write" for row in migration_rows)
        if not reconciliation.complete:
            raise RuntimeError(f"offered-request reconciliation failed: {reconciliation.reasons}")
        if background_db_attempts != migration.grants.charged["background_db_operations"]:
            raise RuntimeError("background DB attempts do not reconcile to installed grant charges")
        if donor_attempts != migration.grants.charged["donor_operations"]:
            raise RuntimeError("donor attempts do not reconcile to installed grant charges")
        if destination_attempts != migration.grants.charged["destination_write_operations"]:
            raise RuntimeError("destination attempts do not reconcile to installed grant charges")
        if background_db_attempts != 1:
            raise RuntimeError("expected exactly one budgeted donor-miss DB warm-up")
        final_cache = await caches[routing["destination"]].namespace_summary(deadline_ns=deadline)
        write_json(run_dir / 'final_cache_state.json', final_cache)
        artifacts = {
            "dataset": {"count": len(dataset.items), "checksum": dataset.checksum,
                        "database": database_summary},
            "routing": {**ownership.summary(), "final_epoch": int(ownership.snapshot.epoch),
                        "final_states": {str(k): v.value for k, v in ownership.snapshot.states.items()}},
            "payload_verification": {"foreground": len(miss_responses) + len(post_responses),
                                     "all_authoritative": True},
            "migration": {"items": len(migration_results),
                          "sources": {"donor_cache": sum(r.source == "donor_cache" for r in migration_results),
                                      "database": sum(r.source == "database" for r in migration_results)},
                          "grants": migration.grants.summary(),
                          "maximum_workers": migration.maximum_workers,
                          "maximum_buffered_bytes": migration.maximum_buffered_bytes,
                          "maximum_queue_depth": migration.maximum_queue_depth,
                          "remaining_workers": migration._active_workers,
                          "remaining_buffered_bytes": migration._buffered_bytes,
                          "destination_keys": len(final_cache)},
            "foreground": {"maximum_inflight": router.maximum_inflight,
                           "maximum_coalesced_keys": router.maximum_coalesced_keys,
                           "remaining_fills": router.coalesced_key_count,
                           "database_attempts": foreground_db_attempts,
                           "operation_count": len(router.ledger.records)},
            "pools": {"database": database.pool_summary(),
                      "caches": {node: {"foreground_maximum_concurrency": caches[node].maximum_concurrency,
                                        "background_maximum_concurrency": background_caches[node].maximum_concurrency,
                                        "maximum_concurrency": caches[node].maximum_concurrency+background_caches[node].maximum_concurrency}
                                 for node in caches}},
            "pressure": {"database": db_pressure, "rounds": len(sampler.rounds),
                         "caches": cache_pressure,
                         "settings_provisional": True},
            "accounting": {"offered": reconciliation.offered,
                           "submitted": reconciliation.submitted,
                           "unsubmitted": reconciliation.unsubmitted,
                           "terminal": reconciliation.terminal,
                           "complete": reconciliation.complete,
                           "reasons": list(reconciliation.reasons),
                           "foreground_db_attempts": foreground_db_attempts,
                           "background_db_attempts": background_db_attempts,
                           "observation_db_attempts": len(database.probe_records),
                           "observation_cache_attempts": sum(len(c.probe_records) for c in background_caches.values()),
                           "functional_diagnostic_cache_attempts": len(diagnostic_operations),
                           "donor_attempts": donor_attempts,
                           "destination_write_attempts": destination_attempts,
                           "no_unbudgeted_db_prefetch": True,
                           "foreground_donor_fallback_attempts": 0},
        }
        write_json(run_dir / "results.json", artifacts)
        status, exit_code = "completed", 0
    except BaseException as error:
        if isinstance(error, PolicyFailure):
            status = 'policy_failure'
        if isinstance(error, (ValueError, AssertionError, BufferError)):
            status = "invalid_measurement"
        password = "" if database is None else os.environ.get(config["services"]["database"]["password_env"], "")
        trace = traceback.format_exc()
        message = str(error)
        if password:
            trace = trace.replace(password, "[REDACTED]")
            message = message.replace(password, "[REDACTED]")
        (run_dir / "error.log").write_text(trace, encoding="utf-8")
        error_record = {"type": type(error).__name__, "message": message}
    finally:
        if generator is not None:
            if status == 'policy_failure':
                await asyncio.gather(generator, return_exceptions=True)
                if 'workload_origin_ns' in locals():
                    await sleep_until_ns(workload_origin_ns+int(config['timing']['measurement_horizon_seconds']*1e9))
            else:
                generator.cancel()
                await asyncio.gather(generator, return_exceptions=True)
        if sampler is not None:
            try:
                await sampler.close()
            except Exception as sampler_error:
                status, exit_code = "invalid_measurement", 1
                error_record = error_record or {"type": type(sampler_error).__name__, "message": str(sampler_error)}
        # Failure paths retain the same issued ledger as success paths. Counts
        # must not disappear because execution exited before aggregate results.
        remaining_operations = ([] if router is None else router.ledger.records[:])
        remaining_operations += diagnostic_operations
        if migration is not None:
            remaining_operations += migration.operation_records
        for client in background_caches.values():
            remaining_operations += client.probe_records
        if database is not None:
            remaining_operations += database.probe_records
        try:
            for operation in remaining_operations:
                if operation['operation_id'] in emitted_operation_ids:
                    continue
                await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.TERMINAL,
                    epoch=0 if ownership is None else int(ownership.snapshot.epoch),
                    kind=EventKind.ACCOUNTING, reason='issued_operation_final_drain',
                    accounting={'issued_operations':1}, detail=operation),
                    config['timing']['metric_timeout_seconds'])
                emitted_operation_ids.add(operation['operation_id'])
        except Exception as accounting_error:
            status, exit_code = 'invalid_measurement', 1
            error_record = error_record or {'type':type(accounting_error).__name__, 'message':str(accounting_error)}
        try:
            await metrics.close(deadline_ns=time.monotonic_ns() + int(config["timing"]["flush_timeout_seconds"] * 1e9))
        except BaseException as close_error:
            if error_record is None:
                error_record = {"type": type(close_error).__name__, "message": str(close_error)}
                status, exit_code = "invalid_measurement", 1
        if status != 'completed' and (run_dir / 'offered_schedule.json').is_file():
            failed_schedule = json.loads((run_dir / 'offered_schedule.json').read_text())['requests']
            failed_reconciliation = reconcile_offers(tuple(failed_schedule), _read_jsonl(run_dir / 'requests.jsonl'))
            write_json(run_dir / 'failure_accounting.json', {
                'offered': failed_reconciliation.offered, 'submitted': failed_reconciliation.submitted,
                'unsubmitted': failed_reconciliation.unsubmitted, 'terminal': failed_reconciliation.terminal,
                'complete': failed_reconciliation.complete, 'reasons': failed_reconciliation.reasons,
                'issued_operations': len(remaining_operations), 'issued_events': len(emitted_operation_ids),
                'all_issued_terminal': all(row.get('outcome') is not None for row in remaining_operations)})
        for client in (*caches.values(), *background_caches.values()):
            try:
                await client.close()
            except Exception:
                pass
        if database is not None:
            try:
                await database.close()
            except Exception:
                pass
        manifest = {
            "run_id": run_id, "kind": "phase3_minimal_scaleout", "status": status,
            "retry_of": retry_of, "started_utc": started_utc, "ended_utc": utc_now(),
            "elapsed_seconds": (time.monotonic_ns() - origin_ns) / 1e9, "exit_code": exit_code,
            "config_path": config_path.relative_to(ROOT).as_posix(),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "source_sha256": json.loads((run_dir / "source.json").read_text())["aggregate_sha256"],
            "error": error_record,
            "boundary": "Functional Phase 3 verification only; no calibration or performance comparison.",
        }
        write_json(run_dir / "manifest.json", manifest)
        checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(run_dir.iterdir()) if path.is_file() and path.name != "checksums.json"}
        write_json(run_dir / "checksums.json", checksums)
    print(json.dumps({"run_id": run_id, "status": status, "exit_code": exit_code,
                      "evidence": str(run_dir), "error": error_record}, sort_keys=True))
    return exit_code


def validate_phase3_run(run_dir: Path, compare_dir: Path | None = None) -> dict[str, Any]:
    try:
        result = _validate_phase3_run(run_dir, compare_dir)
        if compare_dir is not None:
            other = _validate_phase3_run(compare_dir)
            result['checks']['comparison_run_independently_valid'] = other['valid']
            result['valid'] = all(result['checks'].values())
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {'valid':False, 'run':run_dir.name, 'checks':{'required_artifacts_parse_and_reconcile':False},
                'error':f'{type(error).__name__}: {error}'}


def _validate_phase3_run(run_dir: Path, compare_dir: Path | None = None) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    schedule = json.loads((run_dir / "offered_schedule.json").read_text(encoding="utf-8"))["requests"]
    requests = _read_jsonl(run_dir / "requests.jsonl")
    events = _read_jsonl(run_dir / "events.jsonl")
    reconciliation = reconcile_offers(tuple(schedule), requests)
    checksum_manifest = json.loads((run_dir / "checksums.json").read_text(encoding="utf-8"))
    checks["append_only_checksums"] = all(
        (run_dir / name).is_file()
        and hashlib.sha256((run_dir / name).read_bytes()).hexdigest() == digest
        for name, digest in checksum_manifest.items())
    source = json.loads((run_dir / "source.json").read_text(encoding="utf-8"))
    checks["source_fingerprint"] = manifest["source_sha256"] == source["aggregate_sha256"]
    config_path = ROOT / manifest["config_path"]
    checks["config_fingerprint"] = (
        config_path.is_file() and manifest["config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest())
    schedule_document = json.loads((run_dir / "offered_schedule.json").read_text(encoding="utf-8"))
    checks["offered_schedule_checksum"] = schedule_document["checksum"] == hashlib.sha256(
        json.dumps(tuple(schedule), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    offered_ids = [item["request_id"] for item in schedule]
    arrival_ids = [event["detail"]["request_id"] for event in events
                   if event["kind"] == "arrival_scheduled"]
    terminal_ids = [request["request_id"] for request in requests]
    checks["schedule_arrival_terminal_equality"] = (
        len(offered_ids) == len(set(offered_ids)) == len(arrival_ids) == len(set(arrival_ids))
        == len(terminal_ids) == len(set(terminal_ids))
        and set(offered_ids) == set(arrival_ids) == set(terminal_ids))
    transitions = [event for event in events if event["kind"] == "bucket_transition"]
    affected_count = len(results["routing"]["affected_buckets"])
    checks["routing_transition_telemetry"] = (
        len(transitions) == affected_count * 3
        and sorted({event["routing_epoch"] for event in transitions}) == [1, 2, 3]
        and all(event["detail"].get("publication_epoch") == event["routing_epoch"]
                and len(event["detail"].get("path", [])) == 1 for event in transitions))
    checks["run_completed"] = manifest["status"] == "completed" and manifest["exit_code"] == 0
    checks["offered_request_reconciliation"] = reconciliation.complete
    checks["payloads_authoritative"] = results["payload_verification"]["all_authoritative"]
    checks["all_affected_buckets_new"] = all(
        state == "new" for state in results["routing"]["final_states"].values())
    checks["no_unbudgeted_db_prefetch"] = results["accounting"]["no_unbudgeted_db_prefetch"]
    checks["no_foreground_donor_fallback"] = results["accounting"]["foreground_donor_fallback_attempts"] == 0
    effective_config = json.loads((run_dir / "effective_config.json").read_text(encoding="utf-8"))
    checks["bounded_workers"] = (results["migration"]["maximum_workers"] <=
                                  effective_config["resources"]["migration_workers"])
    checks["issued_attempts_reconcile"] = (
        results["accounting"]["background_db_attempts"] ==
        results["migration"]["grants"]["charged"]["background_db_operations"]
        and results["accounting"]["donor_attempts"] ==
        results["migration"]["grants"]["charged"]["donor_operations"]
        and results["accounting"]["destination_write_attempts"] ==
        results["migration"]["grants"]["charged"]["destination_write_operations"])
    operations = [event['detail'] for event in events if event['kind'] == 'accounting'
                  and 'operation_id' in event['detail']]
    migrations = _read_jsonl(run_dir / 'migrations.jsonl')
    checks['unique_terminal_operation_ids'] = (
        len({row['operation_id'] for row in operations}) == len(operations)
        and all(row.get('outcome') in {'completed','failed','timed_out','cancelled'}
                and row['issued_ns'] <= row['terminal_ns']
                and row['issued_ns'] <= row['absolute_deadline_ns'] for row in operations))
    foreground = [row for row in operations if row['work_class'].startswith('foreground_')]
    checks['request_owned_attempt_counts'] = all(
        request[field] == sum(row.get('request_id') == request['request_id'] and row['operation'] == operation
                              for row in foreground)
        for request in requests for field, operation in
        (('cache_attempts','cache_read'), ('database_attempts','database_read'), ('cache_write_attempts','cache_write')))
    migration_ops = [row for row in operations if row['work_class'] in
                     {'donor_read','discretionary_database_warmup','destination_write'}]
    checks['migration_attempt_operation_bijection'] = (
        len(migration_ops) == len(migrations)
        and {(row['task_id'], row['retry_ordinal'], row['outcome']) for row in migration_ops}
            == {(row['task_id'], row['attempt'], row['outcome']) for row in migrations})
    read_tasks = {row['task_id'] for row in migration_ops if row['operation'] in {'donor','database'}}
    checks['destination_parent_read_links'] = all(row.get('parent_task_id') in read_tasks
        for row in migration_ops if row['operation'] == 'write')
    charged = results['migration']['grants']['charged']
    checks['encoded_byte_charges'] = all(
        sum(row['reserved_bytes'] for row in migration_ops if row['work_class'] == work_class) == charged[field]
        for work_class, field in [('donor_read','donor_bytes'),('destination_write','destination_write_bytes')])
    grant = effective_config['migration_grant']
    checks['absolute_grant_limits'] = all(charged[name] <= grant[name] for name in charged)
    start = results['migration']['grants']['last_decided_at_ns']
    rate_checks = []
    for dimension, work_class, byte_dimension in [
            ('donor_operations','donor_read',False), ('donor_bytes','donor_read',True),
            ('background_db_operations','discretionary_database_warmup',False),
            ('destination_write_operations','destination_write',False),
            ('destination_write_bytes','destination_write',True)]:
        selected = sorted((row for row in migration_ops if row['work_class'] == work_class), key=lambda row:row['issued_ns'])
        rate, burst = effective_config['migration_rates'][dimension], effective_config['migration_bursts'][dimension]
        consumed = 0
        for index, row in enumerate(selected):
            consumed += row['reserved_bytes'] if byte_dimension else 1
            rate_checks.append(consumed <= rate*(row['issued_ns']-start)/1e9 + 1e-6)
            for previous in range(index+1):
                amount = sum(part['reserved_bytes'] if byte_dimension else 1 for part in selected[previous:index+1])
                rate_checks.append(amount <= burst + rate*(row['issued_ns']-selected[previous]['issued_ns'])/1e9 + 1e-6)
    checks['actual_token_rate_and_burst_envelopes'] = all(rate_checks)
    checks['observation_attempt_charges'] = all(
        sum(row['work_class'] == work_class for row in operations) == results['accounting'][field]
        for work_class, field in [('observation_cache','observation_cache_attempts'),
                                  ('observation_database','observation_db_attempts'),
                                  ('functional_diagnostic_cache','functional_diagnostic_cache_attempts')])
    resources = effective_config['resources']
    checks['physical_pool_partition_bounds'] = (
        all(row['foreground_maximum_concurrency'] <= resources['foreground_cache_connections_per_node']
            and row['background_maximum_concurrency'] <= resources['background_cache_connections_per_node']
            for row in results['pools']['caches'].values())
        and results['pools']['database']['foreground']['observed_max_concurrency'] <= resources['foreground_db_connections']
        and results['pools']['database']['background']['observed_max_concurrency'] <= resources['background_db_connections'])
    checks['queue_memory_and_drain_bounds'] = (
        results['migration']['maximum_queue_depth'] <= resources['max_pending_migration_tasks']
        and results['migration']['maximum_buffered_bytes'] <= resources['max_buffered_payload_bytes']
        and results['foreground']['maximum_inflight'] <= resources['max_inflight_requests']
        and results['foreground']['maximum_coalesced_keys'] <= resources['max_coalesced_keys']
        and results['foreground']['remaining_fills'] == results['migration']['remaining_workers']
            == results['migration']['remaining_buffered_bytes'] == 0)
    expected_dataset = create_dataset(seed=effective_config['dataset']['seed'],
        key_count=effective_config['dataset']['keys'], value_bytes=effective_config['dataset']['value_bytes'])
    payload_checks = json.loads((run_dir / 'payload_checks.json').read_text())
    checks['raw_returned_payload_hashes'] = (len(payload_checks) == len(requests)
        and {row['request_id'] for row in payload_checks} == set(terminal_ids)
        and all(row['observed_sha256'] == row['expected_sha256'] == expected_dataset.by_key()[row['key']].version
                for row in payload_checks))
    mapping = effective_config['routing']
    expected_map = StableOwnershipMap(mapping_seed=mapping['mapping_seed'], bucket_count=mapping['virtual_buckets'],
        old_nodes=tuple(mapping['old_nodes']), final_nodes=tuple(mapping['final_nodes']),destination=mapping['destination'])
    checks['request_chronology_and_captured_mapping'] = all(
        row['scheduled_arrival_ns'] <= row['submitted_ns'] <= row['completed_ns']
        and (row['outcome'] != 'completed' or row['completed_ns'] <= row['scheduled_arrival_ns']+row['timeout_seconds']*1e9)
        and row['route']['bucket'] == expected_map.bucket_for_key(row['key'])
        and row['route']['owner'] == (expected_map.final_owner(row['route']['bucket'])
             if row['route']['state'] == 'new' else expected_map.old_owner(row['route']['bucket']))
        for row in requests if row['submitted_ns'] is not None)
    final_cache = json.loads((run_dir / 'final_cache_state.json').read_text())
    checks['actual_destination_payloads'] = (len(final_cache) == results['migration']['items']
        and all(bytes.fromhex(row['payload_hex']) == expected_dataset.by_key()[row['key']].payload
                for row in final_cache))
    checks['actual_database_payload_checksum'] = (
        results['dataset']['database']['actual_payload_checksum'] == expected_dataset.checksum)
    initial = json.loads((run_dir / 'initial_state.json').read_text())
    checks['physical_initial_state_empty_of_foreign_keys'] = all(
        service['physical_key_count'] == len(initial['logical_state']['caches'][node])
        and service['evicted_keys'] == 0 for node, service in initial['service_state']['caches'].items())
    required = {'manifest.json','results.json','effective_config.json','source.json','offered_schedule.json',
                'events.jsonl','requests.jsonl','migrations.jsonl','initial_state.json','stability.json',
                'payload_checks.json','final_cache_state.json','migration_tasks.json'}
    checks['required_checksummed_artifacts'] = required <= set(checksum_manifest)
    canonical = json.dumps(source['files'], sort_keys=True, separators=(',',':')).encode()
    checks['canonical_source_manifest'] = hashlib.sha256(canonical).hexdigest() == source['aggregate_sha256']
    stability = json.loads((run_dir / 'stability.json').read_text())
    checks['fixed_horizon_and_traffic_stability'] = (
        len(stability['windows']) == effective_config['timing']['stability_subwindows']
        and all(row['submitted_affected'] >= effective_config['timing']['stability_min_requests']
                and row['destination_share'] == 1. for row in stability['windows'])
        and stability['measurement_ended_ns'] >= schedule_document['origin_ns'] + int(
            effective_config['timing']['measurement_horizon_seconds']*1e9))
    checks['raw_stability_subwindows'] = all(
        window['submitted_affected'] == sum(window['start_ns'] <= row['submitted_ns'] < window['end_ns']
            and row['route']['owner'] == mapping['destination'] and row['route']['epoch'] >= results['routing']['final_epoch']
            for row in requests if row['submitted_ns'] is not None)
        for window in stability['windows'])
    if compare_dir is not None:
        other_manifest = json.loads((compare_dir / "manifest.json").read_text(encoding="utf-8"))
        first_state = json.loads((run_dir / "initial_state.json").read_text(encoding="utf-8"))
        other_state = json.loads((compare_dir / "initial_state.json").read_text(encoding="utf-8"))
        checks["same_config"] = manifest["config_sha256"] == other_manifest["config_sha256"]
        checks["same_executed_source"] = manifest["source_sha256"] == other_manifest["source_sha256"]
        checks["complete_initial_state_equivalence"] = first_state["logical_state"] == other_state["logical_state"]
        first_ids = {value["server_run_id"] for value in first_state["service_state"]["caches"].values()}
        other_ids = {value["server_run_id"] for value in other_state["service_state"]["caches"].values()}
        checks["physical_cache_instances_recreated"] = first_ids.isdisjoint(other_ids)
        other_schedule = json.loads((compare_dir/'offered_schedule.json').read_text())['requests']
        normalized = lambda rows:[(row['request_id'],row['key'],row['relative_arrival_ns']) for row in rows]
        checks['same_relative_offered_schedule'] = normalized(schedule) == normalized(other_schedule)
    return {"valid": all(checks.values()), "checks": checks,
            "run": run_dir.name, "compare_run": None if compare_dir is None else compare_dir.name}
