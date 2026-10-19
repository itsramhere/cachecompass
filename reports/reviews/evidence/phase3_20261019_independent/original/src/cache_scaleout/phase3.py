"""Deterministic functional Phase 3 run and artifact validation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import time
import traceback
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
from .observations import BoundedDemandTracker, ResidencyTracker
from .router import CacheAsideRouter
from .telemetry import JsonlMetricsSink, reconcile_offers


def load_phase3_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Phase 3 config schema_version 1 required")
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
    if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in run_id):
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
                max_connections=config["resources"]["foreground_cache_connections_per_node"]
                                + config["resources"]["background_cache_connections_per_node"],
                socket_timeout_seconds=cache_config["socket_timeout_seconds"],
                pressure_limits=pressure)
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
        database_service = await database.service_summary(deadline_ns=deadline)
        if database_service["database"] != db_config["dbname"] or database_service["user"] != db_config["user"]:
            raise RuntimeError("refusing dataset preparation on an unverified database")
        await database.prepare_dataset(dataset.items, deadline_ns=deadline)
        database_summary = await database.verify_dataset(deadline_ns=deadline)
        if database_summary["count"] != len(dataset.items):
            raise RuntimeError("authoritative dataset count mismatch")
        for item in dataset.items:
            owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
            await caches[owner].write(item.key, item.cache_value(), deadline_ns=deadline)
        logical_caches = {node: await caches[node].namespace_summary(deadline_ns=deadline)
                          for node in routing["final_nodes"]}
        if logical_caches[routing["destination"]]:
            raise RuntimeError("destination cache is not empty at initial-state capture")
        expected_counts = {node: 0 for node in routing["old_nodes"]}
        for item in dataset.items:
            expected_counts[str(ownership.old_owner(ownership.bucket_for_key(item.key)))] += 1
        if any(len(logical_caches[node]) != count for node, count in expected_counts.items()):
            raise RuntimeError("complete old-cache initial state mismatch")
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
            max_buckets=routing["virtual_buckets"], max_age_ns=config["observations"]["max_age_ns"])
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
            cleanup_timeout_seconds=config["timing"]["cleanup_timeout_seconds"])
        schedule_items = affected_items[:config["workload"]["post_cutover_requests"]]
        miss_item = affected_items[0]
        schedule = tuple(
            [{"request_id": "pre-miss-0", "key": str(miss_item.key), "relative_arrival_ns": 0},
             {"request_id": "pre-miss-1", "key": str(miss_item.key), "relative_arrival_ns": 0}]
            + [{"request_id": f"post-{index:03d}", "key": str(item.key),
                "relative_arrival_ns": (index + 1) * 1_000_000}
               for index, item in enumerate(schedule_items)])
        write_json(run_dir / "offered_schedule.json", {"requests": schedule,
                   "checksum": hashlib.sha256(json.dumps(schedule, sort_keys=True,
                                                           separators=(",", ":")).encode()).hexdigest()})
        for offer in schedule:
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.PRE_EVENT,
                                        epoch=int(ownership.snapshot.epoch), kind=EventKind.ARRIVAL_SCHEDULED,
                                        reason="independent_offered_schedule",
                                        detail=offer), config["timing"]["metric_timeout_seconds"])
        # Force one real cache-aside fill after the complete initial state is captured.
        miss_owner = str(ownership.old_owner(ownership.bucket_for_key(miss_item.key)))
        await caches[miss_owner].delete(miss_item.key, deadline_ns=deadline)
        scheduled_ns = time.monotonic_ns()
        miss_responses = await asyncio.gather(*(
            router.read(request_id=f"pre-miss-{index}", key=miss_item.key,
                        scheduled_arrival_ns=scheduled_ns,
                        timeout_seconds=config["timing"]["foreground_timeout_seconds"],
                        object_bytes=miss_item.object_bytes)
            for index in range(2)))
        if any(response.value is None or response.value.payload != miss_item.payload for response in miss_responses):
            raise RuntimeError("authoritative simultaneous miss payload verification failed")
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
        await caches[fallback_owner].delete(fallback_item.key, deadline_ns=deadline)
        migration = BoundedMigrationScheduler(
            run_id=run_id, ownership=ownership,
            donor_caches={node: caches[node] for node in routing["old_nodes"]},
            destination_cache=caches[routing["destination"]], database=database,
            metrics=metrics, residency=residency,
            worker_limit=config["resources"]["migration_workers"],
            queue_limit=config["resources"]["max_pending_migration_tasks"],
            max_buffered_payload_bytes=config["resources"]["max_buffered_payload_bytes"],
            donor_retry=_retry(config, "donor_read"), db_retry=_retry(config, "warmup_database"),
            write_retry=_retry(config, "destination_write"),
            attempt_timeout_seconds=config["timing"]["migration_attempt_timeout_seconds"])
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
        migration_results = await migration.migrate(affected_items, deadline_ns=deadline)
        if any(result.disposition != "warmed" for result in migration_results):
            raise RuntimeError("minimal migration pass did not warm every affected key")
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
        post_responses = []
        for index, item in enumerate(schedule_items):
            scheduled = time.monotonic_ns()
            response = await router.read(
                request_id=f"post-{index:03d}", key=item.key, scheduled_arrival_ns=scheduled,
                timeout_seconds=config["timing"]["foreground_timeout_seconds"],
                object_bytes=item.object_bytes)
            post_responses.append(response)
        if any(response.value is None for response in post_responses):
            raise RuntimeError("post-cutover request failed")
        for response, item in zip(post_responses, schedule_items, strict=True):
            if response.value.payload != item.payload or response.record.route.owner != routing["destination"]:
                raise RuntimeError("post-cutover payload/owner mismatch")
        # One fixed observation round. It is recorded separately from foreground/warm-up DB work.
        cache_pressure = {node: await client.sample_pressure(deadline_ns=deadline)
                          for node, client in caches.items()}
        db_pressure = await database.sample_pressure(dataset.items[0].key, deadline_ns=deadline)
        await _emit(metrics, _event(
            run_id, origin_ns, phase=EventPhase.POST_HANDOVER, epoch=int(ownership.snapshot.epoch),
            kind=EventKind.OBSERVATION, reason="fixed_common_pressure_round",
            accounting={"observation_database_operations": 1,
                        "observation_cache_operations": len(caches) * 2},
            detail={"database": db_pressure.reason,
                    "caches": {node: sample.reason for node, sample in cache_pressure.items()}}),
            config["timing"]["metric_timeout_seconds"])
        # Persist every foreground issued operation as one accounting event.
        for operation in router.ledger.records:
            await _emit(metrics, _event(
                run_id, origin_ns, phase=EventPhase.TERMINAL, epoch=int(ownership.snapshot.epoch),
                kind=EventKind.ACCOUNTING, reason="foreground_operation",
                accounting={"issued_operations": 1}, detail=operation),
                config["timing"]["metric_timeout_seconds"])
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
                          "destination_keys": len(final_cache)},
            "foreground": {"maximum_inflight": router.maximum_inflight,
                           "maximum_coalesced_keys": router.maximum_coalesced_keys,
                           "database_attempts": foreground_db_attempts,
                           "operation_count": len(router.ledger.records)},
            "pools": {"database": database.pool_summary(),
                      "caches": {node: {"maximum_concurrency": client.maximum_concurrency,
                                        "cancelled_operations": client.cancelled_operations}
                                 for node, client in caches.items()}},
            "pressure": {"database": db_pressure.state.value,
                         "caches": {node: sample.state.value for node, sample in cache_pressure.items()},
                         "settings_provisional": True},
            "accounting": {"offered": reconciliation.offered,
                           "submitted": reconciliation.submitted,
                           "unsubmitted": reconciliation.unsubmitted,
                           "terminal": reconciliation.terminal,
                           "complete": reconciliation.complete,
                           "reasons": list(reconciliation.reasons),
                           "foreground_db_attempts": foreground_db_attempts,
                           "background_db_attempts": background_db_attempts,
                           "observation_db_attempts": 1,
                           "donor_attempts": donor_attempts,
                           "destination_write_attempts": destination_attempts,
                           "no_unbudgeted_db_prefetch": True,
                           "foreground_donor_fallback_attempts": 0},
        }
        write_json(run_dir / "results.json", artifacts)
        status, exit_code = "completed", 0
    except BaseException as error:
        password = "" if database is None else os.environ.get(config["services"]["database"]["password_env"], "")
        trace = traceback.format_exc()
        message = str(error)
        if password:
            trace = trace.replace(password, "[REDACTED]")
            message = message.replace(password, "[REDACTED]")
        (run_dir / "error.log").write_text(trace, encoding="utf-8")
        error_record = {"type": type(error).__name__, "message": message}
    finally:
        try:
            await metrics.close(deadline_ns=time.monotonic_ns() + int(config["timing"]["flush_timeout_seconds"] * 1e9))
        except BaseException as close_error:
            if error_record is None:
                error_record = {"type": type(close_error).__name__, "message": str(close_error)}
                status, exit_code = "invalid_measurement", 1
        for client in caches.values():
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
    return {"valid": all(checks.values()), "checks": checks,
            "run": run_dir.name, "compare_run": None if compare_dir is None else compare_dir.name}
