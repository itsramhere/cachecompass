"""Adversarial runtime checks added by the independent Phase 3 review."""
import asyncio
from dataclasses import replace
import time
import unittest

from tests import test_phase3_behavior as fixtures
from tests.test_phase3_behavior import FakeCache, FakeDatabase, ownership_and_item, retry
from cache_scaleout.contracts import CacheValue, ControllerAction, TransferBudget, OperationOutcome
from cache_scaleout.migration import GrantEnforcer
from cache_scaleout.migration import TokenBuckets
from cache_scaleout.telemetry import reconcile_offers
from cache_scaleout.contracts import json_record
from cache_scaleout.load import dispatch_offers
from cache_scaleout.observations import BoundedDemandTracker, ResidencyTracker
from cache_scaleout.contracts import ResidencyState
from cache_scaleout.telemetry import JsonlMetricsSink
from pathlib import Path
from cache_scaleout.phase3 import validate_phase3_run
from cache_scaleout.adapters import _Concurrency
from cache_scaleout.issuance import issuing


class IndependentRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_observers_reserve_next_background_connection_opportunity(self):
        limiter = _Concurrency(1)
        order = []
        async def acquire(name, priority):
            with issuing(lambda:None, priority=priority):
                async with limiter:
                    order.append(name)
        async with limiter:
            ordinary = asyncio.create_task(acquire('migration',False))
            await asyncio.sleep(.01)
            observer = asyncio.create_task(acquire('observation',True))
            await asyncio.sleep(.01)
        await asyncio.gather(ordinary,observer)
        self.assertEqual(order,['observation','migration'])
        self.assertEqual(limiter.maximum,1)
    def setup_router(self):
        _, _, item = ownership_and_item()
        db = FakeDatabase({item.key: item.cache_value()})
        values = fixtures.RouterBehaviorTests().make_router(db)
        return item, db, values

    async def test_cache_cancellation_finishes_issued_ledger(self):
        item, db, (_, own, _, caches, sink, router) = self.setup_router()
        cache = caches[str(own.capture(item.key).owner)]
        cache.read_release.clear()
        task = asyncio.create_task(router.read(request_id='cancel-cache', key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(), timeout_seconds=1, object_bytes=item.object_bytes))
        await cache.read_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(router.ledger.records[0]['outcome'], 'cancelled')

    async def test_creator_deadline_bounds_fill_with_later_follower(self):
        item, db, (_, _, _, _, sink, router) = self.setup_router()
        db.release.clear()
        now = time.monotonic_ns()
        leader = asyncio.create_task(router.read(request_id='creator', key=item.key,
            scheduled_arrival_ns=now, timeout_seconds=.03, object_bytes=item.object_bytes))
        await db.started.wait()
        follower = asyncio.create_task(router.read(request_id='later', key=item.key,
            scheduled_arrival_ns=now, timeout_seconds=.3, object_bytes=item.object_bytes))
        await asyncio.sleep(.07)
        finished_at_creator_deadline = follower.done()
        db.release.set()
        await asyncio.gather(leader, follower, return_exceptions=True)
        self.assertTrue(finished_at_creator_deadline)
        self.assertEqual(router.coalesced_key_count, 0)

    async def test_refusal_still_records_submitted_demand(self):
        item, db, (_, own, _, _, _, router) = self.setup_router()
        router._inflight = router.limits.max_inflight_requests
        now = time.monotonic_ns()
        response = await router.read(request_id='refused', key=item.key,
            scheduled_arrival_ns=now, timeout_seconds=1, object_bytes=item.object_bytes)
        self.assertEqual(response.record.outcome, OperationOutcome.REFUSED)
        self.assertEqual(sum(v[0] for entries in router.demand_tracker._slots.values()
                             for v in entries.values()), 1)

    async def test_write_retry_backoff_failure_keeps_valid_database_value(self):
        item, db, (_, own, _, caches, _, router) = self.setup_router()
        cache = caches[str(own.capture(item.key).owner)]
        cache.write_failures.append(OSError('write failed'))
        router.fill_write_retry = replace(retry(2), backoff_seconds=(1.,))
        response = await router.read(request_id='write-failure', key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(), timeout_seconds=.2, object_bytes=item.object_bytes)
        self.assertEqual(response.record.outcome, OperationOutcome.COMPLETED)
        self.assertEqual(response.value.payload, item.payload)

    async def test_cancelled_creator_retains_later_retry_and_write_counts(self):
        item, db, (_, _, _, _, sink, router) = self.setup_router()
        db.release.clear()
        db.foreground_failures.append(OSError('retry'))
        router.db_retry = retry(2)
        now = time.monotonic_ns()
        leader = asyncio.create_task(router.read(request_id='origin', key=item.key,
            scheduled_arrival_ns=now, timeout_seconds=1, object_bytes=item.object_bytes))
        await db.started.wait()
        follower = asyncio.create_task(router.read(request_id='follower', key=item.key,
            scheduled_arrival_ns=now, timeout_seconds=1, object_bytes=item.object_bytes))
        await asyncio.sleep(.01)
        leader.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await leader
        self.assertFalse(any(row.request_id == 'origin' for row in sink.requests))
        db.release.set()
        self.assertEqual((await follower).value.payload, item.payload)
        origin = next(row for row in sink.requests if row.request_id == 'origin')
        self.assertEqual(origin.database_attempts, 2)
        self.assertEqual(origin.cache_write_attempts, 1)
        self.assertEqual(origin.outcome, OperationOutcome.CANCELLED)
        self.assertTrue(all(row['outcome'] for row in router.ledger.records))

    async def test_failed_timed_out_refused_and_unsubmitted_offers_reconcile(self):
        item, db, (dataset, own, _, caches, sink, router) = self.setup_router()
        rows = []
        for request_id, error in [('failed', OSError('failure')), ('timed-out', TimeoutError('timeout'))]:
            caches[str(own.capture(item.key).owner)].read_failures.append(error)
            now = time.monotonic_ns()
            rows.append({'request_id':request_id, 'key':item.key, 'scheduled_arrival_ns':now})
            await router.read(request_id=request_id, key=item.key, scheduled_arrival_ns=now,
                              timeout_seconds=.2, object_bytes=item.object_bytes)
        router._inflight = router.limits.max_inflight_requests
        now = time.monotonic_ns()
        rows.append({'request_id':'refused', 'key':item.key, 'scheduled_arrival_ns':now})
        await router.read(request_id='refused', key=item.key, scheduled_arrival_ns=now,
                          timeout_seconds=.2, object_bytes=item.object_bytes)
        router._inflight = 0
        future = ({'request_id':'unsubmitted', 'key':item.key,
                   'scheduled_arrival_ns':time.monotonic_ns()+40_000_000},)
        arrivals = []
        async def arrival(offer):
            arrivals.append(offer['request_id'])
        task = asyncio.create_task(dispatch_offers(schedule=future, router=router,
            items=dataset.by_key(), on_arrival=arrival, metrics=sink,
            timeout_seconds=.2, metric_timeout_seconds=.2))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        result = reconcile_offers(tuple(rows)+future, [json_record(row) for row in sink.requests])
        self.assertTrue(result.complete, result.reasons)
        self.assertEqual({row.outcome.value for row in sink.requests},
                          {'failed','timed_out','refused','unsubmitted'})
        self.assertEqual(arrivals, ['unsubmitted'])

    async def test_closing_generation_cannot_accept_a_new_waiter(self):
        _, _, item = ownership_and_item()
        cleanup = asyncio.Event()
        cancelling = asyncio.Event()
        class DelayedCleanup(FakeDatabase):
            async def read_foreground(self, key, *, deadline_ns):
                if self.foreground_calls == 0:
                    self.foreground_calls += 1
                    self.started.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelling.set()
                        await cleanup.wait()
                        raise
                return await super().read_foreground(key, deadline_ns=deadline_ns)
        db = DelayedCleanup({item.key:item.cache_value()})
        _, _, _, _, sink, router = fixtures.RouterBehaviorTests().make_router(db)
        old = asyncio.create_task(router.read(request_id='old-generation', key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(), timeout_seconds=1., object_bytes=item.object_bytes))
        await db.started.wait()
        old.cancel()
        await cancelling.wait()
        blocked = await router.read(request_id='during-cleanup', key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(), timeout_seconds=1., object_bytes=item.object_bytes)
        self.assertEqual(blocked.record.outcome, OperationOutcome.FAILED)
        self.assertIsNone(blocked.record.coalesced_to_request_id)
        cleanup.set()
        with self.assertRaises(asyncio.CancelledError):
            await old
        fresh = await router.read(request_id='new-generation', key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(), timeout_seconds=1., object_bytes=item.object_bytes)
        self.assertEqual(fresh.value.payload, item.payload)
        self.assertEqual(router.coalesced_key_count, 0)


class IndependentMigrationTests(unittest.IsolatedAsyncioTestCase):
    def setup_scheduler(self):
        _, own, item = ownership_and_item()
        donor = FakeCache(str(own.capture(item.key).owner), {item.key: item.cache_value()})
        db = FakeDatabase({item.key: item.cache_value()})
        destination = FakeCache('new')
        helper = fixtures.MigrationBehaviorTests()
        _, sink, scheduler = helper.make_scheduler(donor=donor, destination=destination,
                                                    database=db, items=(item,), worker_limit=1)
        helper.install(scheduler, donor_ops=4, db_ops=2, destination_ops=4)
        return item, donor, db, destination, sink, scheduler

    async def test_worker_fault_propagates_and_does_not_hang_queue(self):
        item, donor, db, dest, sink, scheduler = self.setup_scheduler()
        donor.values[item.key] = CacheValue(b'wrong', None)
        try:
            await asyncio.wait_for(scheduler.migrate((item,),
                deadline_ns=time.monotonic_ns()+500_000_000), .2)
        except ValueError:
            pass
        except TimeoutError:
            self.fail('worker failure stranded queue.join')
        else:
            self.fail('wrong payload accepted')

    async def test_caller_cancellation_drains_workers_and_charges_attempt(self):
        item, donor, db, dest, sink, scheduler = self.setup_scheduler()
        donor.read_release.clear()
        task = asyncio.create_task(scheduler.migrate((item,),
            deadline_ns=time.monotonic_ns()+2_000_000_000))
        await donor.read_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        active = donor.active
        donor.read_release.set()
        await asyncio.sleep(.01)
        self.assertEqual(active, 0, 'cancelled pass left source IO running')
        self.assertEqual(sink.migrations[0].outcome, OperationOutcome.CANCELLED)

    async def test_replaced_reservation_cannot_refund_new_grant(self):
        grants = GrantEnforcer()
        now = time.monotonic_ns()
        grants.apply_action(ControllerAction(now, TransferBudget(1,128,1,1,1_000_000_000,128), (), ('a',),0,now))
        reservation = await grants.reserve_destination(64)
        grants.apply_action(ControllerAction(now+1, TransferBudget(0,0,0,0,1_000_000_000,0), (), ('b',),0,now+1))
        reservation.release()
        self.assertEqual(grants.remaining_destination_operations, 0)
        self.assertEqual(grants.remaining_destination_bytes, 0)

    async def test_expired_grant_cannot_issue_destination(self):
        grants = GrantEnforcer()
        now = time.monotonic_ns()
        grants.apply_action(ControllerAction(now, TransferBudget(1,128,1,1,1_000_000,128), (), ('a',),0,now))
        reservation = await grants.reserve_destination(64)
        from cache_scaleout.load import sleep_until_ns
        await sleep_until_ns(now+5_000_000)
        with self.assertRaises((TimeoutError, RuntimeError)):
            await grants.issue_destination(reservation)

    async def test_registry_expiry_caps_donor_value_and_residency(self):
        item, donor, db, dest, sink, scheduler = self.setup_scheduler()
        expiry = time.monotonic_ns()+500_000_000
        item = replace(item, absolute_expiry_ns=expiry)
        donor.values[item.key] = CacheValue(item.payload, expiry+1_000_000_000, item.version)
        result = await scheduler.migrate((item,), deadline_ns=time.monotonic_ns()+1_000_000_000)
        self.assertEqual(result[0].disposition, 'warmed')
        self.assertEqual(dest.values[item.key].absolute_expiry_ns, expiry)
        self.assertEqual(scheduler.residency.snapshot()[item.key].valid_until_ns, expiry)

    async def test_waiting_source_renews_destination_with_replacement_grant(self):
        for destination_operations in (0,1):
            with self.subTest(destination_operations=destination_operations):
                item, donor, db, dest, sink, scheduler = self.setup_scheduler()
                from cache_scaleout.load import sleep_until_ns
                await sleep_until_ns(scheduler.grants.last_decided_at_ns+1_000_000)
                helper = fixtures.MigrationBehaviorTests()
                helper.install(scheduler,donor_ops=0,db_ops=0,destination_ops=1)
                task = asyncio.create_task(scheduler.migrate((item,),
                    deadline_ns=time.monotonic_ns()+200_000_000,allow_db_fallback=False))
                await asyncio.sleep(.03)
                self.assertEqual(donor.read_calls,0)
                self.assertEqual(scheduler.grants.remaining_destination_operations,0)
                helper.install(scheduler,donor_ops=1,db_ops=0,destination_ops=destination_operations)
                result = await task
                self.assertEqual(donor.read_calls,destination_operations)
                self.assertEqual(dest.write_calls,destination_operations)
                self.assertEqual(scheduler.grants.charged['donor_operations'],destination_operations)
                self.assertEqual(result[0].disposition,'warmed' if destination_operations else 'not_warmed')
                self.assertEqual(scheduler.grants.remaining_destination_operations,0)


class IndependentAccountingTests(unittest.TestCase):
    def test_telemetry_queue_cannot_be_configured_unbounded(self):
        for value in (0, -1, True):
            with self.assertRaises(ValueError):
                JsonlMetricsSink(Path('unused'), capacity=value)

    def test_incomplete_artifacts_produce_a_failed_validation_record(self):
        result = validate_phase3_run(Path('runs/does-not-exist-independent-check'))
        self.assertFalse(result['valid'])
        self.assertIn('error', result)
    def test_demand_origin_complete_windows_and_overflow_bucket_bound(self):
        tracker = BoundedDemandTracker(subwindow_ns=10, retained_subwindows=2,
            max_total_keys=2, max_keys_per_bucket=2, max_buckets=2, max_age_ns=20, origin_ns=3)
        tracker.register({0:{'a':64}})
        tracker.observe('a', 0, 64, at_ns=4)
        with self.assertRaises(ValueError):
            tracker.snapshot(start_ns=3, end_ns=13, observed_at_ns=23)
        self.assertEqual(tracker.snapshot(start_ns=3,end_ns=23,observed_at_ns=23).entries[0].request_count, 1)
        with self.assertRaises(ValueError):
            tracker.observe('unknown', 10_000, 1, at_ns=24)
        tracker.observe('a',0,64,at_ns=104)
        self.assertLessEqual(len(tracker._slots), 2)
        self.assertNotIn(3, tracker._slots)

    def test_tokens_start_empty_refill_and_clamp_without_minting(self):
        now = [0]
        tokens = TokenBuckets({'ops':2., 'bytes':100.}, {'ops':2, 'bytes':80}, clock=lambda:now[0])
        self.assertEqual(tokens.tokens, {'ops':0.,'bytes':0.})
        now[0] = 500_000_000
        tokens.refill()
        self.assertEqual(tokens.tokens, {'ops':1.,'bytes':50.})
        now[0] = 5_000_000_000
        tokens.refill()
        self.assertEqual(tokens.tokens, {'ops':2,'bytes':80})

    def test_reconciliation_rejects_wrong_key_and_schedule(self):
        offer = ({'request_id':'a', 'key':'expected', 'scheduled_arrival_ns':10},)
        request = [{'request_id':'a', 'key':'wrong', 'scheduled_arrival_ns':20,
                    'submitted_ns':21,'outcome':'completed'}]
        self.assertFalse(reconcile_offers(offer, request).complete)

    def test_reconciliation_rejects_nonterminal_outcome(self):
        self.assertFalse(reconcile_offers(({'request_id':'a'},),
            [{'request_id':'a','submitted_ns':1,'outcome':'running'}]).complete)
