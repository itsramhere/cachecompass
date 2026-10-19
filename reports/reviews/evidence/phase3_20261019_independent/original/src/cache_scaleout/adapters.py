"""Actual bounded Redis and PostgreSQL adapters used by Phase 3."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import time
from typing import Any, Awaitable

from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool

from .contracts import (
    CacheReadResult, CacheValue, ComponentPressure, DataSource, Key, NodeId,
    PressureState,
)


def _remaining_seconds(deadline_ns: int) -> float:
    remaining = (deadline_ns - time.monotonic_ns()) / 1e9
    if remaining <= 0:
        raise TimeoutError("absolute operation deadline expired")
    return remaining


async def _bounded(deadline_ns: int, operation: Awaitable[Any]) -> Any:
    try:
        async with asyncio.timeout(_remaining_seconds(deadline_ns)):
            return await operation
    except asyncio.TimeoutError as error:
        raise TimeoutError("operation exceeded absolute deadline") from error


@dataclass(frozen=True, slots=True)
class PressureLimits:
    latency_upper_ms: float
    memory_upper_fraction: float = 0.95

    def __post_init__(self) -> None:
        if self.latency_upper_ms <= 0 or not 0 < self.memory_upper_fraction <= 1:
            raise ValueError("positive provisional pressure limits required")


class _Concurrency:
    def __init__(self, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("connection limit must be a positive integer")
        self._semaphore = asyncio.Semaphore(limit)
        self.limit = limit
        self.active = 0
        self.maximum = 0

    async def __aenter__(self) -> "_Concurrency":
        await self._semaphore.acquire()
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.active -= 1
        self._semaphore.release()


class RedisCacheAdapter:
    """A namespaced Redis client with atomic payload/PTTL reads and a bounded pool."""

    def __init__(self, *, node_id: NodeId, host: str, port: int, namespace: str,
                 max_connections: int, socket_timeout_seconds: float,
                 pressure_limits: PressureLimits) -> None:
        if not node_id or not namespace:
            raise ValueError("cache identity and namespace are required")
        self._node_id = node_id
        self.namespace = namespace
        self.pressure_limits = pressure_limits
        self._pool = ConnectionPool(host=host, port=port, max_connections=max_connections,
                                    socket_connect_timeout=socket_timeout_seconds,
                                    socket_timeout=socket_timeout_seconds,
                                    decode_responses=False)
        self._client = Redis(connection_pool=self._pool, single_connection_client=False)
        self._limit = _Concurrency(max_connections)
        self.cancelled_operations = 0

    @property
    def node_id(self) -> NodeId:
        return self._node_id

    @property
    def maximum_concurrency(self) -> int:
        return self._limit.maximum

    def _key(self, key: Key) -> str:
        return f"{self.namespace}:{key}"

    async def _run(self, deadline_ns: int, operation: Awaitable[Any]) -> Any:
        async with self._limit:
            try:
                return await _bounded(deadline_ns, operation)
            except asyncio.CancelledError:
                self.cancelled_operations += 1
                raise

    async def read(self, key: Key, *, source: DataSource, deadline_ns: int) -> CacheReadResult:
        if source not in {DataSource.OLD_CACHE, DataSource.NEW_CACHE, DataSource.DONOR_CACHE}:
            raise ValueError("cache source required")
        observed = time.monotonic_ns()
        pipeline = self._client.pipeline(transaction=True)
        pipeline.get(self._key(key))
        pipeline.pttl(self._key(key))
        payload, pttl_ms = await self._run(deadline_ns, pipeline.execute())
        finished = time.monotonic_ns()
        if payload is None:
            value = None
        else:
            # PTTL is observed at the server after the local timestamp. Subtract
            # the full local round trip so transport delay cannot extend expiry.
            expiry = (None if pttl_ms == -1 else
                      observed + max(0, int(pttl_ms)) * 1_000_000 - (finished - observed))
            value = CacheValue(bytes(payload), expiry)
            if expiry is not None and expiry <= finished:
                value = None
        return CacheReadResult(source, value, observed, finished - observed)

    async def write(self, key: Key, value: CacheValue, *, deadline_ns: int) -> None:
        now = time.monotonic_ns()
        remaining = value.remaining_ttl_ns(now)
        if remaining == 0:
            raise TimeoutError("value expired before destination write")
        if remaining is None:
            operation = self._client.set(self._key(key), value.payload)
        else:
            ttl_ms = remaining // 1_000_000
            if ttl_ms < 1:
                raise TimeoutError("remaining TTL rounds down to zero")
            wall_expiry_ms = (time.time_ns() + remaining) // 1_000_000
            operation = self._client.set(self._key(key), value.payload, pxat=wall_expiry_ms)
        if not await self._run(deadline_ns, operation):
            raise OSError("Redis write was not acknowledged")

    async def delete(self, key: Key, *, deadline_ns: int) -> int:
        return int(await self._run(deadline_ns, self._client.delete(self._key(key))))

    async def sample_pressure(self, *, deadline_ns: int) -> ComponentPressure:
        started = time.monotonic_ns()
        async with self._limit:
            ping = await _bounded(deadline_ns, self._client.ping())
            memory = await _bounded(deadline_ns, self._client.info("memory"))
            stats = await _bounded(deadline_ns, self._client.info("stats"))
            server = await _bounded(deadline_ns, self._client.info("server"))
        ended = time.monotonic_ns()
        latency_ms = (ended - started) / 1e6
        maximum = int(memory.get("maxmemory", 0))
        occupied = int(memory.get("used_memory", 0))
        fraction = occupied / maximum if maximum else 1.0
        unsafe = (ping is not True or latency_ms > self.pressure_limits.latency_upper_ms
                  or fraction > self.pressure_limits.memory_upper_fraction)
        reason = (f"ping_ms={latency_ms:.3f};memory_fraction={fraction:.6f};"
                  f"evicted_keys={int(stats.get('evicted_keys', 0))};"
                  f"run_id={server.get('run_id', '')}")
        return ComponentPressure(PressureState.UNSAFE if unsafe else PressureState.SAFE,
                                 ended, reason)

    async def service_summary(self, *, deadline_ns: int) -> dict[str, Any]:
        async with self._limit:
            server = await _bounded(deadline_ns, self._client.info("server"))
            memory = await _bounded(deadline_ns, self._client.info("memory"))
            stats = await _bounded(deadline_ns, self._client.info("stats"))
            policy = await _bounded(deadline_ns, self._client.config_get("maxmemory-policy"))
        return {
            "node_id": self.node_id,
            "server_run_id": server["run_id"],
            "redis_version": server["redis_version"],
            "maxmemory": int(memory["maxmemory"]),
            "maxmemory_policy": policy.get("maxmemory-policy"),
            "used_memory": int(memory["used_memory"]),
            "evicted_keys": int(stats.get("evicted_keys", 0)),
        }

    async def namespace_summary(self, *, deadline_ns: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: int = 0
        pattern = f"{self.namespace}:*"
        while True:
            cursor, keys = await self._run(deadline_ns,
                                           self._client.scan(cursor=cursor, match=pattern, count=100))
            for raw_key in sorted(keys):
                pipeline = self._client.pipeline(transaction=True)
                pipeline.get(raw_key)
                pipeline.pttl(raw_key)
                payload, ttl_ms = await self._run(deadline_ns, pipeline.execute())
                if payload is not None:
                    decoded = raw_key.decode("utf-8")
                    rows.append({"key": decoded[len(self.namespace) + 1:],
                                 "payload_hex": bytes(payload).hex(),
                                 "ttl_ms": None if ttl_ms == -1 else int(ttl_ms)})
            if int(cursor) == 0:
                break
        rows.sort(key=lambda row: row["key"])
        return rows

    async def close(self) -> None:
        await self._client.aclose(close_connection_pool=True)


class PostgresDatabaseAdapter:
    """Separate bounded foreground/background PostgreSQL pools."""

    def __init__(self, *, connection_kwargs: dict[str, Any], foreground_max_size: int,
                 background_max_size: int, pool_timeout_seconds: float,
                 statement_timeout_ms: int, pressure_latency_upper_ms: float) -> None:
        if foreground_max_size < 1 or background_max_size < 1:
            raise ValueError("separate positive DB pool bounds required")
        self._kwargs = dict(connection_kwargs)
        self._timeout = pool_timeout_seconds
        self._statement_timeout_ms = statement_timeout_ms
        self._pressure_latency_upper_ms = pressure_latency_upper_ms
        self.foreground_pool = AsyncConnectionPool("", kwargs=self._kwargs, min_size=0,
                                                   max_size=foreground_max_size,
                                                   timeout=pool_timeout_seconds, open=False)
        self.background_pool = AsyncConnectionPool("", kwargs=self._kwargs, min_size=0,
                                                   max_size=background_max_size,
                                                   timeout=pool_timeout_seconds, open=False)
        self._foreground_limit = _Concurrency(foreground_max_size)
        self._background_limit = _Concurrency(background_max_size)
        self.cancelled_operations = 0

    async def open(self) -> None:
        await self.foreground_pool.open(wait=True, timeout=self._timeout)
        await self.background_pool.open(wait=True, timeout=self._timeout)

    async def close(self) -> None:
        await self.foreground_pool.close()
        await self.background_pool.close()

    async def _read(self, pool: AsyncConnectionPool, limiter: _Concurrency,
                    key: Key, deadline_ns: int) -> CacheValue:
        async with limiter:
            try:
                async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                    async with pool.connection() as connection:
                        async with connection.transaction():
                            await connection.execute(f"SET LOCAL statement_timeout = {int(self._statement_timeout_ms)}")
                            row = await (await connection.execute(
                                "SELECT payload, version, absolute_expiry_ns FROM phase3_dataset WHERE key = %s",
                                (str(key),))).fetchone()
                            if row is None:
                                raise KeyError(str(key))
                            return CacheValue(bytes(row[0]), row[2], row[1])
            except asyncio.TimeoutError as error:
                raise TimeoutError("database read exceeded absolute deadline") from error
            except asyncio.CancelledError:
                self.cancelled_operations += 1
                raise

    async def read_foreground(self, key: Key, *, deadline_ns: int) -> CacheValue:
        return await self._read(self.foreground_pool, self._foreground_limit, key, deadline_ns)

    async def read_for_warmup(self, key: Key, *, deadline_ns: int) -> CacheValue:
        return await self._read(self.background_pool, self._background_limit, key, deadline_ns)

    async def sample_pressure(self, key: Key, *, deadline_ns: int) -> ComponentPressure:
        started = time.monotonic_ns()
        try:
            await self.read_for_warmup(key, deadline_ns=deadline_ns)
        except Exception as error:
            return ComponentPressure(PressureState.UNKNOWN, time.monotonic_ns(),
                                     f"probe_failed:{type(error).__name__}")
        ended = time.monotonic_ns()
        latency_ms = (ended - started) / 1e6
        state = (PressureState.UNSAFE if latency_ms > self._pressure_latency_upper_ms
                 else PressureState.SAFE)
        return ComponentPressure(state, ended, f"same_query_probe_ms={latency_ms:.3f}")

    async def prepare_dataset(self, items: tuple[Any, ...], *, deadline_ns: int) -> None:
        async with self._background_limit:
            async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                async with self.background_pool.connection() as connection:
                    async with connection.transaction():
                        await connection.execute(f"SET LOCAL statement_timeout = {int(self._statement_timeout_ms)}")
                        await connection.execute("DROP TABLE IF EXISTS phase3_dataset")
                        await connection.execute(
                            "CREATE TABLE phase3_dataset (key text PRIMARY KEY, payload bytea NOT NULL, "
                            "version text NOT NULL, absolute_expiry_ns bigint NULL)")
                        async with connection.cursor() as cursor:
                            await cursor.executemany(
                                "INSERT INTO phase3_dataset (key,payload,version,absolute_expiry_ns) VALUES (%s,%s,%s,%s)",
                                [(str(item.key), item.payload, item.version, item.absolute_expiry_ns)
                                 for item in items])

    async def service_summary(self, *, deadline_ns: int) -> dict[str, Any]:
        async with self._background_limit:
            async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                async with self.background_pool.connection() as connection:
                    row = await (await connection.execute(
                        "SELECT current_database(), current_user, version()")).fetchone()
                    return {"database": row[0], "user": row[1], "version": row[2]}

    async def verify_dataset(self, *, deadline_ns: int) -> dict[str, Any]:
        async with self._background_limit:
            async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                async with self.background_pool.connection() as connection:
                    rows = await (await connection.execute(
                        "SELECT key, version FROM phase3_dataset ORDER BY key")).fetchall()
                    identity = "\n".join(f"{row[0]}:{row[1]}" for row in rows).encode()
                    return {"count": len(rows),
                            "identity_sha256": hashlib.sha256(identity).hexdigest()}

    def pool_summary(self) -> dict[str, Any]:
        return {
            "foreground": {**self.foreground_pool.get_stats(),
                           "observed_max_concurrency": self._foreground_limit.maximum},
            "background": {**self.background_pool.get_stats(),
                           "observed_max_concurrency": self._background_limit.maximum},
            "cancelled_operations": self.cancelled_operations,
        }
