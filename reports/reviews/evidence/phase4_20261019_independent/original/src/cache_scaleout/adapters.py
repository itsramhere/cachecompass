"""Actual bounded Redis and PostgreSQL adapters used by Phase 3."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import time
import struct
import math
from typing import Any, Awaitable

from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from redis.asyncio.connection import ConnectionPool
from redis.backoff import NoBackoff
from redis.retry import Retry
from psycopg.errors import QueryCanceled
from psycopg import OperationalError as PostgresOperationalError
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from .issuance import notify_issued, issuing, observation_priority

from .contracts import (
    CacheReadResult, CacheValue, ComponentPressure, DataSource, Key, NodeId,
    PressureState, CacheWriteReceipt,
)


def _remaining_seconds(deadline_ns: int) -> float:
    remaining = (deadline_ns - time.monotonic_ns()) / 1e9
    if remaining <= 0:
        raise TimeoutError("absolute operation deadline expired")
    return remaining


async def _bounded(deadline_ns: int, operation: Awaitable[Any]) -> Any:
    try:
        remaining = _remaining_seconds(deadline_ns)
    except BaseException:
        if hasattr(operation, 'close'):
            operation.close()
        raise
    try:
        async with asyncio.timeout(remaining):
            return await operation
    except asyncio.TimeoutError as error:
        raise TimeoutError("operation exceeded absolute deadline") from error


@dataclass(frozen=True, slots=True)
class PressureLimits:
    latency_upper_ms: float
    memory_upper_fraction: float = 0.95

    def __post_init__(self) -> None:
        if (not math.isfinite(self.latency_upper_ms) or self.latency_upper_ms <= 0
                or not 0 < self.memory_upper_fraction <= 1):
            raise ValueError("positive provisional pressure limits required")


class _Concurrency:
    def __init__(self, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("connection limit must be a positive integer")
        self._condition = asyncio.Condition()
        self._priority_waiters = 0
        self.limit = limit
        self.active = 0
        self.maximum = 0
        self.waiting = 0

    async def __aenter__(self) -> "_Concurrency":
        priority = observation_priority()
        async with self._condition:
            if priority:
                self._priority_waiters += 1
            self.waiting += 1
            try:
                await self._condition.wait_for(lambda:self.active < self.limit
                    and (priority or self._priority_waiters == 0))
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            finally:
                self.waiting -= 1
                if priority:
                    self._priority_waiters -= 1
                    self._condition.notify_all()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        async with self._condition:
            self.active -= 1
            self._condition.notify_all()


class _IssuingRedisPool(ConnectionPool):
    async def get_connection(self, *args, **kwargs):
        connection = await super().get_connection(*args, **kwargs)
        try:
            notify_issued()
        except BaseException:
            await self.release(connection)
            raise
        return connection


class RedisCacheAdapter:
    """A namespaced Redis client with atomic payload/PTTL reads and a bounded pool."""
    reports_issuance = True

    def __init__(self, *, node_id: NodeId, host: str, port: int, namespace: str,
                 max_connections: int, socket_timeout_seconds: float,
                 pressure_limits: PressureLimits, is_destination: bool = False) -> None:
        if not node_id or not namespace:
            raise ValueError("cache identity and namespace are required")
        if len(namespace.encode()) > 256:
            raise ValueError('namespace exceeds encoded key reservation')
        self._node_id = node_id
        self.namespace = namespace
        self.pressure_limits = pressure_limits
        self._pool = _IssuingRedisPool(host=host, port=port, max_connections=max_connections,
                                    socket_connect_timeout=socket_timeout_seconds,
                                    socket_timeout=socket_timeout_seconds,
                                    decode_responses=False, retry=Retry(NoBackoff(), 0))
        self._client = Redis(connection_pool=self._pool, single_connection_client=False)
        self._limit = _Concurrency(max_connections)
        self.cancelled_operations = 0
        self.probe_records: list[dict[str, Any]] = []
        self.real_operations: dict[str, dict[str, Any]] = {}
        self.pressure_peers = [self]
        self.evicted_keys = 0
        self.cache_role = DataSource.NEW_CACHE if is_destination else DataSource.OLD_CACHE
        self.probe_capacity = 1024
        self.last_pressure_detail = {}

    @property
    def node_id(self) -> NodeId:
        return self._node_id

    @property
    def maximum_concurrency(self) -> int:
        return self._limit.maximum

    def _key(self, key: Key) -> str:
        if len(str(key).encode()) > 256:
            raise ValueError('key exceeds encoded key reservation')
        return f"{self.namespace}:{key}"

    @staticmethod
    def _encode(value: CacheValue) -> bytes:
        return b'P2V1' + struct.pack('>q', -1 if value.absolute_expiry_ns is None
                                   else value.absolute_expiry_ns) + value.payload

    @staticmethod
    def _decode(payload: bytes) -> tuple[bytes, int | None]:
        if payload[:4] != b'P2V1' or len(payload) < 12:
            raise ValueError('cache value lacks immutable expiry envelope')
        expiry = struct.unpack('>q', payload[4:12])[0]
        return payload[12:], None if expiry == -1 else expiry

    async def _run(self, deadline_ns: int, operation: Awaitable[Any], kind: str = 'diagnostic') -> Any:
        started = False
        begin_ns = time.monotonic_ns()
        outcome = 'failed'
        try:
            async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                async with self._limit:
                    started = True
                    result = await _bounded(deadline_ns, operation)
                    outcome = 'completed'
                    return result
        except RedisTimeoutError as error:
            raise TimeoutError('Redis socket/connect attempt timed out') from error
        except RedisConnectionError as error:
            raise ConnectionError('Redis connection attempt failed') from error
        except asyncio.CancelledError:
            self.cancelled_operations += 1
            raise
        finally:
            if kind in {'read', 'write'}:
                self.real_operations[kind] = {'latency_ms': (time.monotonic_ns()-begin_ns)/1e6,
                    'observed_at_ns': time.monotonic_ns(), 'outcome': outcome}
            if not started and hasattr(operation, 'close'):
                operation.close()

    async def read(self, key: Key, *, source: DataSource, deadline_ns: int) -> CacheReadResult:
        if source not in {DataSource.OLD_CACHE, DataSource.NEW_CACHE, DataSource.DONOR_CACHE}:
            raise ValueError("cache source required")
        observed = time.monotonic_ns()
        pipeline = self._client.pipeline(transaction=True)
        pipeline.get(self._key(key))
        pipeline.pttl(self._key(key))
        payload, pttl_ms = await self._run(deadline_ns, pipeline.execute(), 'read')
        finished = time.monotonic_ns()
        if payload is None:
            value = None
        else:
            payload, original_expiry = self._decode(bytes(payload))
            # PTTL is observed at the server after the local timestamp. Subtract
            # the full local round trip so transport delay cannot extend expiry.
            expiry = (None if pttl_ms == -1 else
                      observed + max(0, int(pttl_ms)) * 1_000_000 - (finished - observed))
            if original_expiry is not None:
                expiry = original_expiry if expiry is None else min(expiry, original_expiry)
            value = CacheValue(bytes(payload), expiry)
            if expiry is not None and expiry <= finished:
                value = None
        return CacheReadResult(source, value, observed, finished - observed)

    async def write(self, key: Key, value: CacheValue, *, deadline_ns: int) -> CacheWriteReceipt:
        now = time.monotonic_ns()
        remaining = value.remaining_ttl_ns(now)
        evidence_expiry = value.absolute_expiry_ns
        if remaining == 0:
            raise TimeoutError("value expired before destination write")
        if remaining is None:
            operation = self._client.set(self._key(key), self._encode(value))
        else:
            ttl_ms = remaining // 1_000_000
            if ttl_ms < 1:
                raise TimeoutError("remaining TTL rounds down to zero")
            # Sample wall time before monotonic time: scheduling between samples
            # can shorten but cannot extend the original monotonic deadline.
            wall_now = time.time_ns()
            remaining = value.remaining_ttl_ns(time.monotonic_ns())
            if remaining is None or remaining < 1_000_000:
                raise TimeoutError("value expired while preparing Redis write")
            # Windows CPython 3.12 monotonic ticks can be coarse. Subtract both
            # clock resolutions so clock quantization cannot mint physical TTL.
            uncertainty = math.ceil((time.get_clock_info('monotonic').resolution
                                     + time.get_clock_info('time').resolution) * 1e9)
            if remaining <= uncertainty + 1_000_000:
                raise TimeoutError('TTL too short for conservative clock conversion')
            wall_expiry_ms = (wall_now + remaining - uncertainty) // 1_000_000
            evidence_expiry = max(0, value.absolute_expiry_ns-2*uncertainty-1_000_000)
            operation = self._client.set(self._key(key), self._encode(value), pxat=wall_expiry_ms)
        if not await self._run(deadline_ns, operation, 'write'):
            raise OSError("Redis write was not acknowledged")
        if evidence_expiry is not None and time.monotonic_ns() >= evidence_expiry:
            raise TimeoutError('acknowledged write no longer supplies positive residency evidence')
        return CacheWriteReceipt(evidence_expiry)

    async def delete(self, key: Key, *, deadline_ns: int) -> int:
        return int(await self._run(deadline_ns, self._client.delete(self._key(key))))

    async def sample_pressure(self, *, deadline_ns: int) -> ComponentPressure:
        started = time.monotonic_ns()
        async def probe(name, operation):
            row = {'operation_id': f'observation-cache-{self.node_id}-{len(self.probe_records)+1}',
                   'task_id': f'observer:{self.node_id}', 'source': self.cache_role.value,
                   'work_class': 'observation_cache', 'operation': name,
                   'target_owner': self.node_id, 'issued_ns': time.monotonic_ns(),
                   'absolute_deadline_ns': deadline_ns, 'reserved_bytes': 65536,
                   'actual_bytes': None, 'outcome': 'failed', 'retry_ordinal': 1}
            def issued():
                if len(self.probe_records) >= self.probe_capacity:
                    raise BufferError('bounded cache probe history exhausted')
                if time.monotonic_ns() >= deadline_ns:
                    raise TimeoutError('probe expired while acquiring cache connection')
                row['issued_ns'] = time.monotonic_ns()
                self.probe_records.append(row)
            try:
                with issuing(issued, priority=True):
                    result = await self._run(deadline_ns, operation)
                row['outcome'] = 'completed'
                return result
            except TimeoutError:
                row['outcome'] = 'timed_out'
                raise
            except asyncio.CancelledError:
                row['outcome'] = 'cancelled'
                raise
            finally:
                row['terminal_ns'] = time.monotonic_ns()
        try:
            ping_started = time.monotonic_ns()
            ping = await probe('ping', self._client.ping())
            ping_ms = (time.monotonic_ns() - ping_started) / 1e6
            info = await probe('info', self._client.info('all'))
        except Exception as error:
            self.last_pressure_detail = {'failed_at_ns':time.monotonic_ns(), 'error':type(error).__name__}
            return ComponentPressure(PressureState.UNKNOWN, time.monotonic_ns(),
                                     f'probe_failed:{type(error).__name__}')
        ended = time.monotonic_ns()
        latency_ms = (ended - started) / 1e6
        maximum = int(info.get("maxmemory", 0))
        occupied = int(info.get("used_memory", 0))
        fraction = occupied / maximum if maximum else 1.0
        previous_evictions = self.evicted_keys
        self.evicted_keys = int(info.get('evicted_keys', 0))
        real_unsafe = any(row['outcome'] != 'completed' or row['latency_ms'] > self.pressure_limits.latency_upper_ms
                          for peer in self.pressure_peers for row in peer.real_operations.values())
        unsafe = (ping is not True or ping_ms > self.pressure_limits.latency_upper_ms
                  or fraction > self.pressure_limits.memory_upper_fraction or real_unsafe
                  or self.evicted_keys > previous_evictions)
        self.last_pressure_detail = {'ping_ms':ping_ms, 'bundle_ms':latency_ms,
            'used_memory':occupied, 'maxmemory':maximum, 'evicted_keys':self.evicted_keys,
            'real_classes':{str(index):dict(peer.real_operations) for index,peer in enumerate(self.pressure_peers)},
            'active':sum(peer._limit.active for peer in self.pressure_peers),
            'waiting':sum(peer._limit.waiting for peer in self.pressure_peers)}
        reason = (f"ping_ms={ping_ms:.3f};bundle_ms={latency_ms:.3f};memory_fraction={fraction:.6f};"
                  f"evicted_keys={int(info.get('evicted_keys', 0))};"
                  f"run_id={info.get('run_id', '')}")
        return ComponentPressure(PressureState.UNSAFE if unsafe else PressureState.SAFE,
                                 ended, reason)

    async def service_summary(self, *, deadline_ns: int) -> dict[str, Any]:
        async with self._limit:
            server = await _bounded(deadline_ns, self._client.info("server"))
            memory = await _bounded(deadline_ns, self._client.info("memory"))
            stats = await _bounded(deadline_ns, self._client.info("stats"))
            policy = await _bounded(deadline_ns, self._client.config_get("maxmemory-policy"))
            key_count = await _bounded(deadline_ns, self._client.dbsize())
        return {
            "node_id": self.node_id,
            "server_run_id": server["run_id"],
            "redis_version": server["redis_version"],
            "maxmemory": int(memory["maxmemory"]),
            "maxmemory_policy": policy.get("maxmemory-policy"),
            "used_memory": int(memory["used_memory"]),
            "evicted_keys": int(stats.get("evicted_keys", 0)),
            "physical_key_count": key_count,
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
                    payload, original_expiry = self._decode(bytes(payload))
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
    reports_issuance = True

    def __init__(self, *, connection_kwargs: dict[str, Any], foreground_max_size: int,
                 background_max_size: int, pool_timeout_seconds: float,
                 statement_timeout_ms: int, pressure_latency_upper_ms: float,
                 cleanup_timeout_seconds: float = 1., query_cpu_rounds: int = 0) -> None:
        if foreground_max_size < 1 or background_max_size < 1:
            raise ValueError("separate positive DB pool bounds required")
        self._kwargs = dict(connection_kwargs)
        self._timeout = pool_timeout_seconds
        self._statement_timeout_ms = statement_timeout_ms
        self._pressure_latency_upper_ms = pressure_latency_upper_ms
        if type(query_cpu_rounds) is not int or query_cpu_rounds < 0:
            raise ValueError('query_cpu_rounds must be a nonnegative integer')
        self.query_cpu_rounds = query_cpu_rounds
        self.foreground_pool = AsyncConnectionPool("", kwargs=self._kwargs, min_size=0,
                                                   max_size=foreground_max_size,
                                                   timeout=pool_timeout_seconds, open=False)
        self.background_pool = AsyncConnectionPool("", kwargs=self._kwargs, min_size=0,
                                                   max_size=background_max_size,
                                                   timeout=pool_timeout_seconds, open=False)
        self._foreground_limit = _Concurrency(foreground_max_size)
        self._background_limit = _Concurrency(background_max_size)
        self.cancelled_operations = 0
        self.probe_records: list[dict[str, Any]] = []
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.discarded_connections = 0
        self._stopped = False
        self.probe_capacity = 1024
        self.last_pressure_detail = {}
        self.real_operations = {}
        self._quarantined = []

    async def open(self) -> None:
        await self.foreground_pool.open(wait=True, timeout=self._timeout)
        await self.background_pool.open(wait=True, timeout=self._timeout)

    async def close(self) -> None:
        if self._quarantined:
            tasks = {entry[2] for entry in self._quarantined}
            done, pending = await asyncio.wait(tasks,timeout=self.cleanup_timeout_seconds)
            await asyncio.gather(*done,return_exceptions=True)
            if pending:
                raise RuntimeError('database cleanup remains quarantined; issuance stopped')
        await self.foreground_pool.close()
        await self.background_pool.close()

    async def _read(self, pool: AsyncConnectionPool, limiter: _Concurrency,
                    key: Key, deadline_ns: int) -> CacheValue:
        begin_ns = time.monotonic_ns()
        observed_probe = observation_priority()
        outcome = 'failed'
        if self._stopped:
            raise RuntimeError('DB issuance stopped after cleanup failure')
        async def query(connection):
            async with connection.transaction():
                await connection.execute(f"SET LOCAL statement_timeout = {int(self._statement_timeout_ms)}")
                # The Phase 4 mix keeps the indexed authoritative lookup and,
                # when configured, adds deterministic CPU work inside PostgreSQL.
                # This is deliberately database work, not a client sleep.
                row = await (await connection.execute(
                    "SELECT d.payload, d.version, d.absolute_expiry_ns "
                    "FROM phase3_dataset AS d CROSS JOIN LATERAL "
                    "(SELECT sum(length(md5(g::text || d.key))) AS work "
                    " FROM generate_series(1, GREATEST(%s, 1)) AS g) AS cpu "
                    "WHERE d.key = %s AND cpu.work >= 0",
                    (self.query_cpu_rounds, str(key)))).fetchone()
                if row is None:
                    raise KeyError(str(key))
                return CacheValue(bytes(row[0]), row[2], row[1])

        async def discard(connection, task):
            # Ask the server to stop with a finite handshake before cancelling
            # the coroutine. Closing a socket while Selector is watching it can
            # invalidate the Windows loop. Drain first, then discard the socket.
            cleanup_end = time.monotonic() + self.cleanup_timeout_seconds
            try:
                async with asyncio.timeout(self.cleanup_timeout_seconds/4):
                    await connection.cancel_safe(timeout=self.cleanup_timeout_seconds / 4)
            except Exception:
                pass
            done, _ = await asyncio.wait({task}, timeout=max(0, min(
                self.cleanup_timeout_seconds/4,cleanup_end-time.monotonic())))
            if not done:
                task.cancel()
                await asyncio.sleep(0)
                # Unregister the original socket before hard close. Otherwise
                # Windows Selector can retain an invalid descriptor while the
                # driver's cancellation handshake is still being drained.
                try:
                    descriptor = connection.pgconn.socket
                    loop = asyncio.get_running_loop()
                    loop.remove_reader(descriptor)
                    loop.remove_writer(descriptor)
                except (OSError, ValueError, PostgresOperationalError):
                    pass
                await connection.close()
                task.cancel()
                done, _ = await asyncio.wait({task},timeout=max(0,cleanup_end-time.monotonic()))
                if not done:
                    self._stopped = True
                    raise RuntimeError('database cleanup deadline exceeded; issuance stopped')
            await asyncio.gather(task, return_exceptions=True)
            await connection.close()
            self.discarded_connections += 1
        try:
            async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                async with limiter:
                    if self._stopped:
                        raise RuntimeError('DB issuance stopped after cleanup failure')
                    connection = await pool.getconn(timeout=_remaining_seconds(deadline_ns))
                    task = None
                    try:
                        notify_issued()
                        task = asyncio.create_task(query(connection), name='postgres-read')
                        try:
                            done, _ = await asyncio.wait({task}, timeout=_remaining_seconds(deadline_ns))
                            if not done:
                                await discard(connection, task)
                                raise TimeoutError('database query deadline exceeded')
                            result = task.result()
                            outcome = 'completed'
                            return result
                        except asyncio.CancelledError:
                            await discard(connection, task)
                            raise
                    finally:
                        if task is None or task.done():
                            await pool.putconn(connection)
                        else:
                            # Never enter a pool context's rollback path while
                            # an uncertain query owns the connection lock.
                            self._stopped = True
                            self._quarantined.append((pool,connection,task))
        except (asyncio.TimeoutError, QueryCanceled) as error:
            outcome = 'timed_out'
            raise TimeoutError("database read exceeded absolute/statement deadline") from error
        except PostgresOperationalError as error:
            raise ConnectionError('PostgreSQL connection attempt failed') from error
        except asyncio.CancelledError:
            outcome = 'cancelled'
            self.cancelled_operations += 1
            raise
        finally:
            if not observed_probe:
                self.real_operations['foreground' if pool is self.foreground_pool else 'warmup'] = {
                    'outcome':outcome, 'latency_ms':(time.monotonic_ns()-begin_ns)/1e6,
                    'observed_at_ns':time.monotonic_ns()}

    async def read_foreground(self, key: Key, *, deadline_ns: int) -> CacheValue:
        return await self._read(self.foreground_pool, self._foreground_limit, key, deadline_ns)

    async def read_for_warmup(self, key: Key, *, deadline_ns: int) -> CacheValue:
        return await self._read(self.background_pool, self._background_limit, key, deadline_ns)

    async def sample_pressure(self, key: Key, *, deadline_ns: int) -> ComponentPressure:
        started = time.monotonic_ns()
        row = {'operation_id': f'observation-db-{len(self.probe_records)+1}',
               'task_id': 'observer:database', 'source': 'database',
               'work_class': 'observation_database', 'operation': 'same_query_probe',
               'target_owner': 'database', 'issued_ns': started,
               'absolute_deadline_ns': deadline_ns, 'reserved_bytes': 65536,
               'actual_bytes': None, 'outcome': 'failed', 'retry_ordinal': 1}
        def issued():
            if len(self.probe_records) >= self.probe_capacity:
                raise BufferError('bounded DB probe history exhausted')
            if time.monotonic_ns() >= deadline_ns:
                raise TimeoutError('probe expired while acquiring DB connection')
            row['issued_ns'] = time.monotonic_ns()
            self.probe_records.append(row)
        try:
            with issuing(issued, priority=True):
                await self.read_for_warmup(key, deadline_ns=deadline_ns)
        except Exception as error:
            row['outcome'] = 'timed_out' if isinstance(error, TimeoutError) else 'failed'
            self.last_pressure_detail = {'failed_at_ns':time.monotonic_ns(), 'error':type(error).__name__}
            return ComponentPressure(PressureState.UNKNOWN, time.monotonic_ns(),
                                     f"probe_failed:{type(error).__name__}")
        except asyncio.CancelledError:
            row['outcome'] = 'cancelled'
            raise
        finally:
            row['terminal_ns'] = time.monotonic_ns()
        row['outcome'] = 'completed'
        ended = time.monotonic_ns()
        latency_ms = (ended - started) / 1e6
        real_unsafe = any(value['outcome'] != 'completed' or value['latency_ms'] > self._pressure_latency_upper_ms
                          for value in self.real_operations.values())
        state = (PressureState.UNSAFE if latency_ms > self._pressure_latency_upper_ms or real_unsafe
                 else PressureState.SAFE)
        self.last_pressure_detail = {'probe_ms':latency_ms, 'real_classes':dict(self.real_operations),
            'foreground_waiting':self._foreground_limit.waiting, 'background_waiting':self._background_limit.waiting,
            'pools':self.pool_summary()}
        return ComponentPressure(state, ended, f"same_query_probe_ms={latency_ms:.3f}")

    async def prepare_dataset(self, items: tuple[Any, ...], *, deadline_ns: int) -> None:
        async with self._background_limit:
            async with asyncio.timeout(_remaining_seconds(deadline_ns)):
                async with self.background_pool.connection() as connection:
                    async with connection.transaction():
                        await connection.execute(f"SET LOCAL statement_timeout = {int(self._statement_timeout_ms)}")
                        identity = await (await connection.execute(
                            "SELECT current_database(), current_user")).fetchone()
                        if tuple(identity) != ('paper2_research', 'paper2_research'):
                            raise ValueError('refusing preparation outside disposable research database')
                        existing = await (await connection.execute(
                            "SELECT obj_description(to_regclass('public.phase3_dataset'), 'pg_class'), "
                            "to_regclass('public.phase3_dataset') IS NOT NULL")).fetchone()
                        if existing[1] and existing[0] != 'paper2 phase3 disposable dataset v1':
                            raise ValueError('refusing to overwrite unrecognized dataset table')
                        await connection.execute("DROP TABLE IF EXISTS phase3_dataset")
                        await connection.execute(
                            "CREATE TABLE phase3_dataset (key text PRIMARY KEY, payload bytea NOT NULL, "
                            "version text NOT NULL, absolute_expiry_ns bigint NULL)")
                        await connection.execute("COMMENT ON TABLE phase3_dataset IS 'paper2 phase3 disposable dataset v1'")
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
                        "SELECT key, payload, version, absolute_expiry_ns FROM phase3_dataset ORDER BY key")).fetchall()
                    canonical = []
                    for key,payload,version,expiry in rows:
                        digest = hashlib.sha256(bytes(payload)).hexdigest()
                        if digest != version:
                            raise ValueError('actual database payload/version mismatch')
                        canonical.append({'key':key,'payload_sha256':digest,'bytes':len(payload),
                                          'absolute_expiry_ns':expiry})
                    import json
                    actual_checksum = hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    identity = "\n".join(f"{row[0]}:{row[2]}" for row in rows).encode()
                    return {"count": len(rows),
                            "identity_sha256": hashlib.sha256(identity).hexdigest(),
                            'actual_payload_checksum':actual_checksum}

    def pool_summary(self) -> dict[str, Any]:
        return {
            "foreground": {**self.foreground_pool.get_stats(),
                           "observed_max_concurrency": self._foreground_limit.maximum},
            "background": {**self.background_pool.get_stats(),
                           "observed_max_concurrency": self._background_limit.maximum},
            "cancelled_operations": self.cancelled_operations,
            "discarded_connections": self.discarded_connections,
        }
