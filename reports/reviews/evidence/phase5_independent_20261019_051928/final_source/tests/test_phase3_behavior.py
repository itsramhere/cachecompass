from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cache_scaleout.contracts import (
    BucketAdvance, BucketState, CacheReadResult, CacheValue, ControllerAction,
    DataSource, OperationOutcome, ResourceLimits, RetryPolicy, RoutingEpoch,
    TransferBudget,
    CacheWriteReceipt,
)
from cache_scaleout.dataset import StableOwnershipMap, create_dataset
from cache_scaleout.migration import BoundedMigrationScheduler
from cache_scaleout.observations import BoundedDemandTracker, ResidencyTracker
from cache_scaleout.router import CacheAsideRouter
from cache_scaleout.telemetry import InMemoryMetricsSink, reconcile_offers


class FakeCache:
    def __init__(self, node_id: str, values=None):
        self.node_id = node_id
        self.values = dict(values or {})
        self.read_calls = 0
        self.write_calls = 0
        self.read_started = asyncio.Event()
        self.read_release = asyncio.Event()
        self.read_release.set()
        self.read_failures: list[BaseException] = []
        self.write_failures: list[BaseException] = []
        self.active = 0
        self.maximum = 0

    async def read(self, key, *, source, deadline_ns):
        self.read_calls += 1
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        self.read_started.set()
        try:
            await self.read_release.wait()
            if self.read_failures:
                raise self.read_failures.pop(0)
            now = time.monotonic_ns()
            return CacheReadResult(source, self.values.get(key), now, 1)
        finally:
            self.active -= 1

    async def write(self, key, value, *, deadline_ns):
        self.write_calls += 1
        if self.write_failures:
            raise self.write_failures.pop(0)
        self.values[key] = value
        return CacheWriteReceipt(value.absolute_expiry_ns)


class FakeDatabase:
    def __init__(self, values):
        self.values = dict(values)
        self.foreground_calls = 0
        self.warmup_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.foreground_failures: list[BaseException] = []
        self.warmup_failures: list[BaseException] = []
        self.active = 0
        self.maximum = 0
        self.cancelled = 0

    async def _read(self, key, *, foreground):
        if foreground:
            self.foreground_calls += 1
            failures = self.foreground_failures
        else:
            self.warmup_calls += 1
            failures = self.warmup_failures
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        self.started.set()
        try:
            await self.release.wait()
            if failures:
                raise failures.pop(0)
            return self.values[key]
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1

    async def read_foreground(self, key, *, deadline_ns):
        return await self._read(key, foreground=True)

    async def read_for_warmup(self, key, *, deadline_ns):
        return await self._read(key, foreground=False)


def ownership_and_item():
    dataset = create_dataset(seed=7, key_count=64, value_bytes=64)
    ownership = StableOwnershipMap(mapping_seed=2026, bucket_count=16,
                                   old_nodes=("old-1", "old-2"),
                                   final_nodes=("old-1", "old-2", "new"), destination="new")
    item = next(item for item in dataset.items
                if ownership.bucket_for_key(item.key) in ownership.affected_buckets)
    return dataset, ownership, item


def demand_tracker(ownership, dataset):
    tracker = BoundedDemandTracker(subwindow_ns=1_000_000_000, retained_subwindows=4,
                                   max_total_keys=128, max_keys_per_bucket=128,
                                   max_buckets=ownership.bucket_count, max_age_ns=5_000_000_000)
    grouped = ownership.keys_by_bucket(dataset)
    tracker.register({bucket: {item.key: item.object_bytes for item in items}
                      for bucket, items in grouped.items()})
    return tracker


def limits():
    return ResourceLimits(2, 1, 2, 1, 2, 8, 4, 32, 256, 1024)


def retry(attempts=1):
    return RetryPolicy(attempts, 0.2, tuple(0 for _ in range(attempts - 1)))


class RouterBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def make_router(self, db, old1=None, old2=None, new=None):
        dataset, ownership, item = ownership_and_item()
        caches = {"old-1": old1 or FakeCache("old-1"),
                  "old-2": old2 or FakeCache("old-2"),
                  "new": new or FakeCache("new")}
        sink = InMemoryMetricsSink()
        router = CacheAsideRouter(run_id="fake", ownership=ownership, caches=caches,
                                  database=db, demand_tracker=demand_tracker(ownership, dataset),
                                  metrics=sink, limits=limits(), cache_retry=retry(), db_retry=retry(),
                                  fill_write_retry=retry(), cleanup_timeout_seconds=0.2)
        return dataset, ownership, item, caches, sink, router

    async def test_simultaneous_misses_share_one_authoritative_fill(self):
        dataset, ownership, item = ownership_and_item()
        db = FakeDatabase({item.key: item.cache_value()})
        db.release.clear()
        _, _, item, caches, sink, router = self.make_router(db)
        now = time.monotonic_ns()
        first = asyncio.create_task(router.read(request_id="one", key=item.key,
                                                scheduled_arrival_ns=now,
                                                timeout_seconds=1, object_bytes=item.object_bytes))
        await db.started.wait()
        second = asyncio.create_task(router.read(request_id="two", key=item.key,
                                                 scheduled_arrival_ns=now,
                                                 timeout_seconds=1, object_bytes=item.object_bytes))
        await asyncio.sleep(0)
        db.release.set()
        responses = await asyncio.gather(first, second)
        self.assertEqual([response.value.payload for response in responses], [item.payload, item.payload])
        self.assertEqual(db.foreground_calls, 1)
        self.assertEqual(sum(cache.write_calls for cache in caches.values()), 1)
        followers = [record for record in sink.requests if record.coalesced_to_request_id]
        self.assertEqual(len(followers), 1)
        self.assertEqual(followers[0].database_attempts, 0)

    async def test_inflight_cutover_retains_captured_old_owner(self):
        dataset, ownership, item = ownership_and_item()
        old_owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
        old_cache = FakeCache(old_owner, {item.key: item.cache_value()})
        old_cache.read_release.clear()
        db = FakeDatabase({item.key: item.cache_value()})
        caches = {"old-1": FakeCache("old-1"), "old-2": FakeCache("old-2"), "new": FakeCache("new")}
        caches[old_owner] = old_cache
        sink = InMemoryMetricsSink()
        router = CacheAsideRouter(run_id="cutover", ownership=ownership, caches=caches, database=db,
                                  demand_tracker=demand_tracker(ownership, dataset), metrics=sink,
                                  limits=limits(), cache_retry=retry(), db_retry=retry(),
                                  fill_write_retry=retry(), cleanup_timeout_seconds=0.2)
        now = time.monotonic_ns()
        request = asyncio.create_task(router.read(request_id="inflight", key=item.key,
                                                  scheduled_arrival_ns=now, timeout_seconds=1,
                                                  object_bytes=item.object_bytes))
        await old_cache.read_started.wait()
        bucket = ownership.bucket_for_key(item.key)
        ownership.publish((BucketAdvance(bucket, BucketState.OLD,
                                         (BucketState.COPYING, BucketState.ELIGIBLE, BucketState.NEW)),),
                          expected_epoch=RoutingEpoch(0))
        old_cache.read_release.set()
        response = await request
        self.assertEqual(response.value.payload, item.payload)
        self.assertEqual(response.record.route.owner, old_owner)
        self.assertEqual(response.record.route.epoch, 0)
        self.assertEqual(db.foreground_calls, 0)

    async def test_waiter_cancellation_is_independent(self):
        _, _, item = ownership_and_item()
        db = FakeDatabase({item.key: item.cache_value()})
        db.release.clear()
        _, _, item, _, sink, router = self.make_router(db)
        now = time.monotonic_ns()
        leader = asyncio.create_task(router.read(request_id="leader", key=item.key,
                                                 scheduled_arrival_ns=now, timeout_seconds=1,
                                                 object_bytes=item.object_bytes))
        await db.started.wait()
        follower = asyncio.create_task(router.read(request_id="follower", key=item.key,
                                                   scheduled_arrival_ns=now, timeout_seconds=1,
                                                   object_bytes=item.object_bytes))
        await asyncio.sleep(0)
        follower.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await follower
        self.assertEqual(db.cancelled, 0)
        db.release.set()
        response = await leader
        self.assertEqual(response.value.payload, item.payload)
        cancelled = next(record for record in sink.requests if record.request_id == "follower")
        self.assertEqual(cancelled.outcome, OperationOutcome.CANCELLED)
        self.assertEqual(db.foreground_calls, 1)

    async def test_final_waiter_cancels_fill_and_releases_cleanup(self):
        _, _, item = ownership_and_item()
        db = FakeDatabase({item.key: item.cache_value()})
        db.release.clear()
        _, _, item, _, sink, router = self.make_router(db)
        now = time.monotonic_ns()
        request = asyncio.create_task(router.read(request_id="only", key=item.key,
                                                  scheduled_arrival_ns=now, timeout_seconds=1,
                                                  object_bytes=item.object_bytes))
        await db.started.wait()
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.assertEqual(db.cancelled, 1)
        self.assertEqual(db.active, 0)
        self.assertEqual(router.coalesced_key_count, 0)
        self.assertEqual(sink.requests[0].outcome, OperationOutcome.CANCELLED)

    async def test_database_timeout_is_terminal_and_charged(self):
        _, _, item = ownership_and_item()
        db = FakeDatabase({item.key: item.cache_value()})
        db.foreground_failures.append(TimeoutError("forced"))
        _, _, item, _, _, router = self.make_router(db)
        now = time.monotonic_ns()
        response = await router.read(request_id="timeout", key=item.key,
                                     scheduled_arrival_ns=now, timeout_seconds=1,
                                     object_bytes=item.object_bytes)
        self.assertEqual(response.record.outcome, OperationOutcome.TIMED_OUT)
        self.assertEqual(response.record.database_attempts, 1)
        self.assertEqual(router.ledger.records[-1]["outcome"], "timed_out")


class MigrationBehaviorTests(unittest.IsolatedAsyncioTestCase):
    def make_scheduler(self, *, donor, destination, database, items, worker_limit=2):
        dataset, ownership, _ = ownership_and_item()
        affected_keys = tuple(item.key for item in dataset.items
                              if ownership.bucket_for_key(item.key) in ownership.affected_buckets)
        residency = ResidencyTracker(destination="new", registered_keys=affected_keys)
        sink = InMemoryMetricsSink(4096)
        scheduler = BoundedMigrationScheduler(
            run_id="migration", ownership=ownership,
            donor_caches={"old-1": donor if donor.node_id == "old-1" else FakeCache("old-1"),
                          "old-2": donor if donor.node_id == "old-2" else FakeCache("old-2")},
            destination_cache=destination, database=database, metrics=sink, residency=residency,
            worker_limit=worker_limit, queue_limit=16, max_buffered_payload_bytes=256,
            donor_retry=retry(2), db_retry=retry(2), write_retry=retry(2),
            attempt_timeout_seconds=0.2)
        return ownership, sink, scheduler

    def install(self, scheduler, *, donor_ops, db_ops, destination_ops, byte_budget=4096):
        now = time.monotonic_ns()
        action = ControllerAction(now, TransferBudget(donor_ops, byte_budget, db_ops,
                                                       destination_ops, 5_000_000_000, byte_budget),
                                  (), ("phase3_fixed_smoke_grant",),
                                  RoutingEpoch(0), now)
        scheduler.apply_action(action)

    async def test_retry_charging_and_selective_donor_copy(self):
        dataset, ownership, item = ownership_and_item()
        donor_owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
        donor = FakeCache(donor_owner, {item.key: item.cache_value()})
        donor.read_failures.append(TimeoutError("forced donor timeout"))
        destination = FakeCache("new")
        database = FakeDatabase({item.key: item.cache_value()})
        _, sink, scheduler = self.make_scheduler(donor=donor, destination=destination,
                                                 database=database, items=(item,))
        self.install(scheduler, donor_ops=2, db_ops=0, destination_ops=1)
        results = await scheduler.migrate((item,), deadline_ns=time.monotonic_ns() + 2_000_000_000)
        self.assertEqual(results[0].disposition, "warmed")
        self.assertEqual(results[0].source, "donor_cache")
        self.assertEqual(donor.read_calls, 2)
        self.assertEqual(scheduler.grants.charged["donor_operations"], 2)
        self.assertEqual(len(sink.migrations), 3)
        self.assertEqual(destination.values[item.key].payload, item.payload)

    async def test_expired_data_is_not_copied(self):
        dataset, ownership, item = ownership_and_item()
        donor_owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
        expired = CacheValue(item.payload, time.monotonic_ns() - 1, item.version)
        donor = FakeCache(donor_owner, {item.key: expired})
        destination = FakeCache("new")
        database = FakeDatabase({item.key: item.cache_value()})
        _, _, scheduler = self.make_scheduler(donor=donor, destination=destination,
                                              database=database, items=(item,))
        self.install(scheduler, donor_ops=1, db_ops=0, destination_ops=1)
        results = await scheduler.migrate((item,), deadline_ns=time.monotonic_ns() + 2_000_000_000,
                                          allow_db_fallback=False)
        self.assertEqual(results[0].reason, "expired_before_destination_write")
        self.assertEqual(destination.write_calls, 0)

    async def test_destination_pressure_zero_grant_prevents_source_io(self):
        dataset, ownership, item = ownership_and_item()
        donor_owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
        donor = FakeCache(donor_owner, {item.key: item.cache_value()})
        destination = FakeCache("new")
        database = FakeDatabase({item.key: item.cache_value()})
        _, _, scheduler = self.make_scheduler(donor=donor, destination=destination,
                                              database=database, items=(item,))
        self.install(scheduler, donor_ops=2, db_ops=2, destination_ops=0)
        results = await scheduler.migrate((item,), deadline_ns=time.monotonic_ns() + 1_000_000_000)
        self.assertEqual(results[0].reason, "destination_grant_exhausted_or_pressure_paused")
        self.assertEqual(donor.read_calls, 0)
        self.assertEqual(database.warmup_calls, 0)

    async def test_db_budget_exhaustion_issues_no_unbudgeted_prefetch(self):
        dataset, ownership, _ = ownership_and_item()
        items = tuple(item for item in dataset.items
                      if ownership.bucket_for_key(item.key) in ownership.affected_buckets)[:2]
        donor_owner = str(ownership.old_owner(ownership.bucket_for_key(items[0].key)))
        donor = FakeCache(donor_owner)
        # Ensure both items use one explicit donor fake regardless of owner.
        destination = FakeCache("new")
        database = FakeDatabase({item.key: item.cache_value() for item in items})
        _, _, scheduler = self.make_scheduler(donor=donor, destination=destination,
                                              database=database, items=items, worker_limit=1)
        scheduler.donor_caches = {"old-1": donor, "old-2": donor}
        self.install(scheduler, donor_ops=2, db_ops=1, destination_ops=2)
        results = await scheduler.migrate(items, deadline_ns=time.monotonic_ns() + 2_000_000_000)
        self.assertEqual(database.warmup_calls, 1)
        self.assertEqual(scheduler.grants.charged["background_db_operations"], 1)
        self.assertEqual(sum(result.disposition == "warmed" for result in results), 1)
        self.assertLessEqual(scheduler.maximum_workers, 1)

    async def test_destination_limit_prevents_extra_donor_read(self):
        dataset, ownership, _ = ownership_and_item()
        items = tuple(item for item in dataset.items
                      if ownership.bucket_for_key(item.key) in ownership.affected_buckets)[:2]
        donor = FakeCache("old-1", {item.key: item.cache_value() for item in items})
        destination = FakeCache("new")
        database = FakeDatabase({item.key: item.cache_value() for item in items})
        _, _, scheduler = self.make_scheduler(donor=donor, destination=destination,
                                              database=database, items=items, worker_limit=2)
        scheduler.donor_caches = {"old-1": donor, "old-2": donor}
        self.install(scheduler, donor_ops=2, db_ops=0, destination_ops=1)
        results = await scheduler.migrate(items, deadline_ns=time.monotonic_ns() + 2_000_000_000)
        self.assertEqual(donor.read_calls, 1)
        self.assertEqual(destination.write_calls, 1)
        self.assertEqual(sum(result.disposition == "warmed" for result in results), 1)


class ObservationAndTelemetryTests(unittest.TestCase):
    def test_dataset_mapping_and_atomic_snapshot_are_deterministic(self):
        first_dataset, first_map, item = ownership_and_item()
        second_dataset, second_map, _ = ownership_and_item()
        self.assertEqual(first_dataset.checksum, second_dataset.checksum)
        self.assertEqual(first_map.summary(), second_map.summary())
        self.assertEqual(item.payload, first_dataset.by_key()[item.key].payload)
        affected = first_map.affected_buckets
        before = first_map.snapshot
        valid = BucketAdvance(affected[0], BucketState.OLD, (BucketState.COPYING,))
        invalid = BucketAdvance(affected[1], BucketState.OLD, (BucketState.COPYING,))
        # Change one bucket first, then prove a later mixed batch is rejected wholly.
        first_map.publish((valid,), expected_epoch=before.epoch)
        snapshot = first_map.snapshot
        with self.assertRaises(ValueError):
            first_map.publish((BucketAdvance(affected[0], BucketState.OLD,
                                             (BucketState.COPYING,)), invalid),
                              expected_epoch=snapshot.epoch)
        self.assertIs(first_map.snapshot, snapshot)

    def test_grants_replace_unissued_credit_and_reject_duplicate_decisions(self):
        dataset, ownership, item = ownership_and_item()
        donor_owner = str(ownership.old_owner(ownership.bucket_for_key(item.key)))
        donor = FakeCache(donor_owner, {item.key: item.cache_value()})
        destination = FakeCache("new")
        database = FakeDatabase({item.key: item.cache_value()})
        residency = ResidencyTracker(destination="new", registered_keys=(item.key,))
        scheduler = BoundedMigrationScheduler(
            run_id="grant", ownership=ownership,
            donor_caches={"old-1": donor, "old-2": donor}, destination_cache=destination,
            database=database, metrics=InMemoryMetricsSink(), residency=residency,
            worker_limit=1, queue_limit=1, max_buffered_payload_bytes=128,
            donor_retry=retry(), db_retry=retry(), write_retry=retry(),
            attempt_timeout_seconds=0.2)
        now = time.monotonic_ns()
        first = ControllerAction(now, TransferBudget(10, 1000, 10, 10, 1_000_000_000, 1000),
                                 (), ("first",), 0, now)
        scheduler.apply_action(first)
        replacement = ControllerAction(now + 1, TransferBudget(2, 200, 1, 2, 1_000_000_000, 200),
                                       (), ("replace",), 0, now + 1)
        scheduler.apply_action(replacement)
        self.assertEqual(scheduler.grants.remaining_donor_operations, 2)
        with self.assertRaises(ValueError):
            scheduler.apply_action(replacement)

    def test_demand_memory_is_bounded_and_half_open(self):
        dataset, ownership, item = ownership_and_item()
        tracker = demand_tracker(ownership, dataset)
        tracker.observe(item.key, ownership.bucket_for_key(item.key), item.object_bytes,
                        at_ns=1_500_000_000)
        tracker.observe("unknown", ownership.bucket_for_key(item.key), 1,
                        at_ns=1_999_999_999)
        snapshot = tracker.snapshot(start_ns=0, end_ns=4_000_000_000,
                                    observed_at_ns=4_000_000_000)
        self.assertEqual(snapshot.entries[0].request_count, 1)
        self.assertEqual(sum(snapshot.overflow_request_count_by_bucket.values()), 1)

    def test_independent_schedule_reconciliation_detects_omission(self):
        schedule = ({"request_id": "a"}, {"request_id": "b"})
        complete = reconcile_offers(schedule, [
            {"request_id": "a", "submitted_ns": 1, "outcome": "completed"},
            {"request_id": "b", "submitted_ns": None, "outcome": "unsubmitted"},
        ])
        self.assertTrue(complete.complete)
        omitted = reconcile_offers(schedule, [
            {"request_id": "a", "submitted_ns": 1, "outcome": "completed"},
        ])
        self.assertFalse(omitted.complete)
        self.assertIn("offered_terminal_set_mismatch", omitted.reasons)


if __name__ == "__main__":
    unittest.main()
