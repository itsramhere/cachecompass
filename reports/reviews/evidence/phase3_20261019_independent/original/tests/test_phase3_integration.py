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

    async def test_actual_pressure_sampling_and_instance_identity(self):
        deadline = time.monotonic_ns() + 2_000_000_000
        summaries = [await cache.service_summary(deadline_ns=deadline) for cache in self.caches]
        self.assertEqual(len({summary["server_run_id"] for summary in summaries}), 3)
        cache_sample = await self.caches[2].sample_pressure(deadline_ns=deadline)
        db_sample = await self.database.sample_pressure(self.dataset.items[0].key, deadline_ns=deadline)
        self.assertIn("ping_ms=", cache_sample.reason)
        self.assertIn("same_query_probe_ms=", db_sample.reason)


if __name__ == "__main__":
    unittest.main()
