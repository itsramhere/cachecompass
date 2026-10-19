from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import time
import unittest
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cache_scaleout.adapters import PostgresDatabaseAdapter, PressureLimits, RedisCacheAdapter
from cache_scaleout.contracts import CacheValue, DataSource
from cache_scaleout.dataset import create_dataset
from cache_scaleout.phase3 import load_phase3_config
from cache_scaleout.sampling import PressureSampler
from cache_scaleout.router import CacheAsideRouter
from cache_scaleout.dataset import StableOwnershipMap
from cache_scaleout.observations import BoundedDemandTracker
from cache_scaleout.telemetry import InMemoryMetricsSink
from cache_scaleout.contracts import ResourceLimits, RetryPolicy, OperationOutcome
from cache_scaleout.issuance import issuing
from cache_scaleout.migration import BoundedMigrationScheduler
from cache_scaleout.observations import ResidencyTracker
from cache_scaleout.contracts import ControllerAction, TransferBudget
from cache_scaleout.contracts import BucketAdvance, BucketState


CONFIG = load_phase3_config(Path(__file__).resolve().parents[1] / "configs" / "phase3_smoke.yaml")


@unittest.skipUnless(os.environ.get("PAPER2_INTEGRATION") == "1",
                     "set PAPER2_INTEGRATION=1 for verified disposable services")
class ActualClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cache_config = CONFIG["services"]["cache"]
        self.namespace = f"phase3-integration:{uuid.uuid4().hex}"
        self.caches = [RedisCacheAdapter(
            node_id=node, host=cache_config["host"], port=port, namespace=self.namespace,
            max_connections=2, socket_timeout_seconds=cache_config["socket_timeout_seconds"],
            pressure_limits=PressureLimits(500, 0.999))
            for node, port in zip(CONFIG["routing"]["final_nodes"], cache_config["ports"], strict=True)]
        db_config = CONFIG["services"]["database"]
        self.database = PostgresDatabaseAdapter(
            connection_kwargs={"host": db_config["host"], "port": db_config["port"],
                               "dbname": db_config["dbname"], "user": db_config["user"],
                               "password": os.environ.get(db_config["password_env"],
                                                          "paper2-disposable-local-only"),
                               "connect_timeout": 2},
            foreground_max_size=1, background_max_size=1, pool_timeout_seconds=2,
            statement_timeout_ms=1000, pressure_latency_upper_ms=500)
        await self.database.open()
        identity = await self.database.service_summary(deadline_ns=time.monotonic_ns() + 2_000_000_000)
        self.assertEqual(identity["database"], "paper2_research")
        self.dataset = create_dataset(seed=101, key_count=4, value_bytes=64)
        await self.database.prepare_dataset(self.dataset.items,
                                            deadline_ns=time.monotonic_ns() + 2_000_000_000)

    async def asyncTearDown(self):
        for cache in self.caches:
            await cache.close()
        await self.database.close()

    async def test_redis_atomic_payload_ttl_copy_never_extends_expiry(self):
        item = self.dataset.items[0]
        original_expiry = time.monotonic_ns() + 1_500_000_000
        value = CacheValue(item.payload, original_expiry, item.version)
        deadline = time.monotonic_ns() + 2_000_000_000
        await self.caches[0].write(item.key, value, deadline_ns=deadline)
        before_pttl = time.monotonic_ns()
        physical_pttl = await self.caches[0]._client.pttl(self.caches[0]._key(item.key))
        self.assertLessEqual(before_pttl+physical_pttl*1_000_000, original_expiry)
        donor = await self.caches[0].read(item.key, source=DataSource.DONOR_CACHE, deadline_ns=deadline)
        self.assertEqual(donor.value.payload, item.payload)
        self.assertLessEqual(donor.value.absolute_expiry_ns, original_expiry)
        await asyncio.sleep(0.05)
        await self.caches[2].write(item.key, donor.value, deadline_ns=deadline)
        copied = await self.caches[2].read(item.key, source=DataSource.NEW_CACHE, deadline_ns=deadline)
        self.assertEqual(copied.value.payload, item.payload)
        self.assertLessEqual(copied.value.absolute_expiry_ns, donor.value.absolute_expiry_ns)

    async def test_postgres_pools_are_separate_bounded_and_payloads_authoritative(self):
        deadline = time.monotonic_ns() + 2_000_000_000
        foreground = await asyncio.gather(*(
            self.database.read_foreground(item.key, deadline_ns=deadline)
            for item in self.dataset.items))
        warmup = await asyncio.gather(*(
            self.database.read_for_warmup(item.key, deadline_ns=deadline)
            for item in self.dataset.items))
        self.assertEqual([value.payload for value in foreground],
                         [item.payload for item in self.dataset.items])
        self.assertEqual([value.payload for value in warmup],
                         [item.payload for item in self.dataset.items])
        pools = self.database.pool_summary()
        self.assertLessEqual(pools["foreground"]["observed_max_concurrency"], 1)
        self.assertLessEqual(pools["background"]["observed_max_concurrency"], 1)

    async def test_cancelled_and_timed_out_query_connection_is_reusable(self):
        item = self.dataset.items[0]
        async with self.database.foreground_pool.connection() as connection:
            original_pid = (await (await connection.execute('SELECT pg_backend_pid()')).fetchone())[0]
        started = time.monotonic()
        async with self.database.background_pool.connection() as blocker:
            async with blocker.transaction():
                await blocker.execute("LOCK TABLE phase3_dataset IN ACCESS EXCLUSIVE MODE")
                cancelled = asyncio.create_task(self.database.read_foreground(
                    item.key, deadline_ns=time.monotonic_ns() + 2_000_000_000))
                await asyncio.sleep(0.05)
                cancelled.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await cancelled
                with self.assertRaises(TimeoutError):
                    await self.database.read_foreground(
                        item.key, deadline_ns=time.monotonic_ns() + 50_000_000)
        value = await self.database.read_foreground(
            item.key, deadline_ns=time.monotonic_ns() + 2_000_000_000)
        self.assertEqual(value.payload, item.payload)
        self.assertEqual(self.database.cancelled_operations, 1)
        self.assertLess(time.monotonic()-started, 1.0)
        async with self.database.foreground_pool.connection() as connection:
            replacement_pid = (await (await connection.execute('SELECT pg_backend_pid()')).fetchone())[0]
        self.assertNotEqual(original_pid, replacement_pid)

    async def test_actual_pressure_sampling_and_instance_identity(self):
        deadline = time.monotonic_ns() + 2_000_000_000
        summaries = [await cache.service_summary(deadline_ns=deadline) for cache in self.caches]
        self.assertEqual(len({summary["server_run_id"] for summary in summaries}), 3)
        cache_sample = await self.caches[2].sample_pressure(deadline_ns=deadline)
        db_sample = await self.database.sample_pressure(self.dataset.items[0].key, deadline_ns=deadline)
        self.assertIn("ping_ms=", cache_sample.reason)
        self.assertIn("same_query_probe_ms=", db_sample.reason)

    async def test_pool_waits_obey_absolute_deadlines_without_issuing(self):
        item = self.dataset.items[0]
        issues = []
        async with self.caches[0]._limit:
            # The second cache permit is occupied as well.
            async with self.caches[0]._limit:
                started = time.monotonic()
                with issuing(lambda:issues.append('cache')):
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(self.caches[0].read(item.key,
                            source=DataSource.OLD_CACHE, deadline_ns=time.monotonic_ns()+30_000_000), .2)
                self.assertLess(time.monotonic()-started, .2)
        async with self.database._foreground_limit:
            with issuing(lambda:issues.append('database')):
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(self.database.read_foreground(item.key,
                        deadline_ns=time.monotonic_ns()+30_000_000), .2)
        async with self.database.foreground_pool.connection():
            with issuing(lambda:issues.append('database-pool')):
                with self.assertRaises(TimeoutError):
                    await self.database.read_foreground(item.key, deadline_ns=time.monotonic_ns()+30_000_000)
        self.assertEqual(issues, [])
        self.assertEqual((await self.database.read_foreground(item.key,
            deadline_ns=time.monotonic_ns()+1_000_000_000)).payload, item.payload)

    async def test_redis_timed_out_protocol_is_discarded_before_reuse(self):
        cache = self.caches[0]
        item = self.dataset.items[0]
        await cache.write(item.key, item.cache_value(), deadline_ns=time.monotonic_ns()+1_000_000_000)
        await cache._client.execute_command('CLIENT', 'PAUSE', 150, 'ALL')
        with self.assertRaises(TimeoutError):
            await cache.read(item.key, source=DataSource.OLD_CACHE,
                             deadline_ns=time.monotonic_ns()+30_000_000)
        result = await cache.read(item.key, source=DataSource.OLD_CACHE,
                                 deadline_ns=time.monotonic_ns()+1_000_000_000)
        self.assertEqual(result.value.payload, item.payload)
        self.assertLessEqual(cache.maximum_concurrency, 2)
        await cache._client.execute_command('CLIENT', 'PAUSE', 150, 'ALL')
        cancelled = asyncio.create_task(cache.read(item.key, source=DataSource.OLD_CACHE,
            deadline_ns=time.monotonic_ns()+1_000_000_000))
        await asyncio.sleep(.02)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        result = await cache.read(item.key, source=DataSource.OLD_CACHE,
                                 deadline_ns=time.monotonic_ns()+1_000_000_000)
        self.assertEqual(result.value.payload, item.payload)

    async def test_idle_sampler_continues_with_no_migration_grants(self):
        rows = []
        async def capture(row):
            rows.append(row)
        sampler = PressureSampler(caches={cache.node_id:cache for cache in self.caches},
            database=self.database, key=self.dataset.items[0].key,
            interval_seconds=.05, timeout_seconds=.5, on_round=capture)
        await sampler.start()
        await asyncio.sleep(.18)
        await sampler.close()
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(len(self.database.probe_records), len(rows))
        for cache in self.caches:
            self.assertEqual(len(cache.probe_records), 2*len(rows))
            self.assertTrue(all(row['outcome'] == 'completed' for row in cache.probe_records))
        self.assertTrue(all(first['ended_ns'] <= second['started_ns']
                            for first, second in zip(rows, rows[1:])))

    async def test_background_pool_saturation_leaves_foreground_available(self):
        item = self.dataset.items[0]
        async with self.database._background_limit:
            value = await self.database.read_foreground(item.key,
                deadline_ns=time.monotonic_ns()+500_000_000)
            self.assertEqual(value.payload, item.payload)

    async def test_foreground_and_background_redis_pools_are_separate(self):
        cache_config = CONFIG['services']['cache']
        background = RedisCacheAdapter(node_id=self.caches[0].node_id,
            host=cache_config['host'], port=cache_config['ports'][0], namespace=self.namespace,
            max_connections=1, socket_timeout_seconds=1., pressure_limits=PressureLimits(500))
        try:
            item = self.dataset.items[0]
            await self.caches[0].write(item.key, item.cache_value(), deadline_ns=time.monotonic_ns()+1_000_000_000)
            async with background._limit:
                result = await self.caches[0].read(item.key, source=DataSource.OLD_CACHE,
                    deadline_ns=time.monotonic_ns()+300_000_000)
                self.assertEqual(result.value.payload, item.payload)
            self.assertIsNot(background._pool, self.caches[0]._pool)
        finally:
            await background.close()

    async def test_actual_shared_fill_creator_deadline_bounds_later_follower(self):
        ownership = StableOwnershipMap(mapping_seed=2026, bucket_count=16,
            old_nodes=('old-1','old-2'), final_nodes=('old-1','old-2','new'), destination='new')
        tracker = BoundedDemandTracker(subwindow_ns=1_000_000_000, retained_subwindows=4,
            max_total_keys=64, max_keys_per_bucket=64, max_buckets=16, max_age_ns=5_000_000_000)
        tracker.register({bucket:{item.key:item.object_bytes for item in items}
                          for bucket, items in ownership.keys_by_bucket(self.dataset).items()})
        sink = InMemoryMetricsSink()
        policy = RetryPolicy(1, .5, ())
        router = CacheAsideRouter(run_id='actual-race', ownership=ownership,
            caches={cache.node_id:cache for cache in self.caches}, database=self.database,
            demand_tracker=tracker, metrics=sink, limits=ResourceLimits(**CONFIG['resources']),
            cache_retry=policy, db_retry=policy, fill_write_retry=policy, cleanup_timeout_seconds=1.)
        item = self.dataset.items[0]
        async with self.database.background_pool.connection() as blocker:
            async with blocker.transaction():
                await blocker.execute('LOCK TABLE phase3_dataset IN ACCESS EXCLUSIVE MODE')
                now = time.monotonic_ns()
                leader = asyncio.create_task(router.read(request_id='creator', key=item.key,
                    scheduled_arrival_ns=now, timeout_seconds=.15, object_bytes=item.object_bytes))
                await asyncio.sleep(.04)
                follower = asyncio.create_task(router.read(request_id='later', key=item.key,
                    scheduled_arrival_ns=now, timeout_seconds=.8, object_bytes=item.object_bytes))
                results = await asyncio.wait_for(asyncio.gather(leader, follower), .65)
        self.assertTrue(all(result.record.outcome == OperationOutcome.TIMED_OUT for result in results))
        self.assertEqual(router.coalesced_key_count, 0)
        self.assertEqual(len(sink.requests), 2)
        self.assertEqual(sum(row.database_attempts for row in sink.requests), 1)
        self.assertTrue(all(row['outcome'] is not None for row in router.ledger.records))

    async def test_prepare_refuses_unrecognized_table_without_overwrite(self):
        async with self.database.background_pool.connection() as connection:
            await connection.execute('ALTER TABLE phase3_dataset RENAME TO phase3_dataset_saved')
            await connection.execute('CREATE TABLE phase3_dataset (sentinel text)')
            await connection.execute("INSERT INTO phase3_dataset VALUES ('retain-me')")
        try:
            with self.assertRaisesRegex(ValueError, 'unrecognized'):
                await self.database.prepare_dataset(self.dataset.items,
                    deadline_ns=time.monotonic_ns()+1_000_000_000)
            async with self.database.background_pool.connection() as connection:
                row = await (await connection.execute('SELECT sentinel FROM phase3_dataset')).fetchone()
                self.assertEqual(row[0], 'retain-me')
        finally:
            async with self.database.background_pool.connection() as connection:
                await connection.execute('DROP TABLE phase3_dataset')
                await connection.execute('ALTER TABLE phase3_dataset_saved RENAME TO phase3_dataset')

    async def test_unissued_migration_pool_wait_refunds_only_provisional_budget(self):
        own = StableOwnershipMap(mapping_seed=2026, bucket_count=16,
            old_nodes=('old-1','old-2'), final_nodes=('old-1','old-2','new'), destination='new')
        item = next(item for item in self.dataset.items if own.bucket_for_key(item.key) in own.affected_buckets)
        caches = {cache.node_id:cache for cache in self.caches}
        donor = caches[str(own.capture(item.key).owner)]
        policy = RetryPolicy(1, .03, ())
        scheduler = BoundedMigrationScheduler(run_id='actual-wait', ownership=own,
            donor_caches=caches, destination_cache=caches['new'], database=self.database,
            metrics=InMemoryMetricsSink(), residency=ResidencyTracker(destination='new',registered_keys=(item.key,)),
            worker_limit=1, queue_limit=1, max_buffered_payload_bytes=128,
            donor_retry=policy, db_retry=policy, write_retry=policy, attempt_timeout_seconds=.03)
        now = time.monotonic_ns()
        scheduler.apply_action(ControllerAction(now,TransferBudget(1,4096,0,1,1_000_000_000,4096),
                                                (),('test',),0,now))
        async with donor._limit:
            async with donor._limit:
                result = await scheduler.migrate((item,), deadline_ns=time.monotonic_ns()+200_000_000,
                                                   allow_db_fallback=False)
        self.assertEqual(result[0].attempts, 0)
        self.assertEqual(scheduler.operation_records, [])
        self.assertTrue(all(value == 0 for value in scheduler.grants.charged.values()))
        self.assertEqual(scheduler.grants.remaining_destination_operations, 1)

    async def test_expiry_cap_repeats_across_coarse_clock_ticks(self):
        item = self.dataset.items[0]
        for _ in range(12):
            expiry = time.monotonic_ns()+1_500_000_000
            deadline = time.monotonic_ns()+2_000_000_000
            receipt = await self.caches[0].write(item.key, CacheValue(item.payload,expiry), deadline_ns=deadline)
            before = time.monotonic_ns()
            physical_ttl = await self.caches[0]._client.pttl(self.caches[0]._key(item.key))
            self.assertLessEqual(before+physical_ttl*1_000_000, expiry)
            self.assertLessEqual(receipt.valid_until_ns, before+physical_ttl*1_000_000)
            value = (await self.caches[0].read(item.key, source=DataSource.DONOR_CACHE,deadline_ns=deadline)).value
            self.assertIsNotNone(value)
            self.assertLessEqual(value.absolute_expiry_ns, expiry)
            await self.caches[2].write(item.key,value,deadline_ns=deadline)
            copied = (await self.caches[2].read(item.key,source=DataSource.NEW_CACHE,deadline_ns=deadline)).value
            self.assertLessEqual(copied.absolute_expiry_ns,value.absolute_expiry_ns)
            await asyncio.sleep(.01)

    async def test_destination_memory_pressure_is_observed_from_actual_info(self):
        destination = self.caches[2]
        destination.pressure_limits = PressureLimits(500, 0.000001)
        sample = await destination.sample_pressure(deadline_ns=time.monotonic_ns()+1_000_000_000)
        self.assertEqual(sample.state.value, 'unsafe')
        self.assertIn('memory_fraction=', sample.reason)
        self.assertEqual(len(destination.probe_records), 2)

    async def test_actual_cutover_during_cache_read_retains_captured_owner(self):
        own = StableOwnershipMap(mapping_seed=2026, bucket_count=16,
            old_nodes=('old-1','old-2'), final_nodes=('old-1','old-2','new'), destination='new')
        item = next(item for item in self.dataset.items if own.bucket_for_key(item.key) in own.affected_buckets)
        tracker = BoundedDemandTracker(subwindow_ns=1_000_000_000,retained_subwindows=4,
            max_total_keys=64,max_keys_per_bucket=64,max_buckets=16,max_age_ns=5_000_000_000)
        tracker.register({bucket:{value.key:value.object_bytes for value in values}
                          for bucket,values in own.keys_by_bucket(self.dataset).items()})
        caches = {cache.node_id:cache for cache in self.caches}
        policy = RetryPolicy(1,.5,())
        router = CacheAsideRouter(run_id='actual-cutover',ownership=own,caches=caches,database=self.database,
            demand_tracker=tracker,metrics=InMemoryMetricsSink(),limits=ResourceLimits(**CONFIG['resources']),
            cache_retry=policy,db_retry=policy,fill_write_retry=policy,cleanup_timeout_seconds=1.)
        old_owner = own.capture(item.key).owner
        donor = caches[old_owner]
        await donor.write(item.key,item.cache_value(),deadline_ns=time.monotonic_ns()+1_000_000_000)
        await donor._client.execute_command('CLIENT','PAUSE',150,'ALL')
        old_request = asyncio.create_task(router.read(request_id='before-cutover',key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(),timeout_seconds=1.,object_bytes=item.object_bytes))
        await asyncio.sleep(.03)
        self.assertEqual(donor._limit.active,1)
        own.publish(tuple(BucketAdvance(bucket,BucketState.OLD,
            (BucketState.COPYING,BucketState.ELIGIBLE,BucketState.NEW)) for bucket in own.affected_buckets),
            expected_epoch=own.snapshot.epoch)
        new_response = await router.read(request_id='after-cutover',key=item.key,
            scheduled_arrival_ns=time.monotonic_ns(),timeout_seconds=1.,object_bytes=item.object_bytes)
        old_response = await old_request
        self.assertEqual(old_response.record.route.owner,old_owner)
        self.assertEqual(old_response.record.route.epoch,0)
        self.assertEqual(new_response.record.route.owner,'new')
        self.assertEqual(new_response.record.route.epoch,1)
        self.assertEqual(old_response.value.payload,item.payload)
        self.assertEqual(new_response.value.payload,item.payload)
        self.assertTrue(all(row['target_owner'] == old_owner for row in router.ledger.records
                            if row['request_id'] == 'before-cutover'))

    async def test_actual_redis_socket_timeout_retries_are_finite_and_charged(self):
        own = StableOwnershipMap(mapping_seed=2026,bucket_count=16,old_nodes=('old-1','old-2'),
            final_nodes=('old-1','old-2','new'),destination='new')
        item = self.dataset.items[0]
        owner = own.capture(item.key).owner
        caches = {cache.node_id:cache for cache in self.caches}
        normal = caches[owner]
        settings = CONFIG['services']['cache']
        port = settings['ports'][CONFIG['routing']['final_nodes'].index(owner)]
        short = RedisCacheAdapter(node_id=owner,host=settings['host'],port=port,namespace=self.namespace,
            max_connections=1,socket_timeout_seconds=.2,pressure_limits=PressureLimits(500))
        try:
            await normal.write(item.key,item.cache_value(),deadline_ns=time.monotonic_ns()+1_000_000_000)
            await short._client.ping()  # Connection establishment is outside the injected read failure.
            caches[owner] = short
            tracker = BoundedDemandTracker(subwindow_ns=1_000_000_000,retained_subwindows=4,
                max_total_keys=64,max_keys_per_bucket=64,max_buckets=16,max_age_ns=5_000_000_000)
            tracker.register({own.bucket_for_key(item.key):{item.key:item.object_bytes}})
            retry = RetryPolicy(2,1.,(.6,))
            router = CacheAsideRouter(run_id='actual-retry',ownership=own,caches=caches,database=self.database,
                demand_tracker=tracker,metrics=InMemoryMetricsSink(),limits=ResourceLimits(**CONFIG['resources']),
                cache_retry=retry,db_retry=RetryPolicy(1,.5,()),fill_write_retry=RetryPolicy(1,.5,()),
                cleanup_timeout_seconds=1.)
            await normal._client.execute_command('CLIENT','PAUSE',500,'ALL')
            result = await router.read(request_id='retry',key=item.key,scheduled_arrival_ns=time.monotonic_ns(),
                                       timeout_seconds=2.5,object_bytes=item.object_bytes)
            self.assertEqual(result.value.payload,item.payload)
            self.assertEqual(result.record.cache_attempts,2)
            self.assertEqual(result.record.database_attempts,0)
            self.assertEqual([row['outcome'] for row in router.ledger.records],['timed_out','completed'])
        finally:
            await short.close()

    async def test_unresponsive_cancel_handshake_discards_within_cleanup_bound(self):
        self.database.cleanup_timeout_seconds = .1
        async with self.database.foreground_pool.connection() as connection:
            original_pid = connection.info.backend_pid
            async def lost_cancel(*, timeout):
                return None  # Fault injection: cancel handshake never reaches PostgreSQL.
            connection.cancel_safe = lost_cancel
        async with self.database.background_pool.connection() as blocker:
            async with blocker.transaction():
                await blocker.execute('LOCK TABLE phase3_dataset IN ACCESS EXCLUSIVE MODE')
                started = time.monotonic()
                with self.assertRaises((TimeoutError,RuntimeError)):
                    await self.database.read_foreground(self.dataset.items[0].key,
                        deadline_ns=time.monotonic_ns()+30_000_000)
                self.assertLess(time.monotonic()-started,.35)
        value = await self.database.read_foreground(self.dataset.items[0].key,
            deadline_ns=time.monotonic_ns()+1_000_000_000)
        self.assertEqual(value.payload,self.dataset.items[0].payload)
        async with self.database.foreground_pool.connection() as connection:
            self.assertNotEqual(connection.info.backend_pid,original_pid)


if __name__ == "__main__":
    unittest.main()
