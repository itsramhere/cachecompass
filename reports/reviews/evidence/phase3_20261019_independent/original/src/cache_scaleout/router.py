"""Bounded cache-aside foreground reads with per-owner/key shared fills."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Callable

from .contracts import (
    BucketState, CacheValue, DataSource, Key, OperationOutcome, RequestRecord,
    ResourceLimits, RetryPolicy, RouteCapture, WorkClass,
)


TRANSIENT_ERRORS = (TimeoutError, OSError, ConnectionError)


@dataclass(slots=True)
class OperationLedger:
    records: list[dict[str, Any]] = field(default_factory=list)
    _sequence: int = 0

    def issue(self, *, request_id: str, operation: str, source: DataSource,
              owner: str, deadline_ns: int, retry_ordinal: int) -> str:
        self._sequence += 1
        operation_id = f"fg-{self._sequence:08d}"
        self.records.append({
            "operation_id": operation_id, "request_id": request_id,
            "operation": operation, "source": source.value, "target_owner": owner,
            "work_class": (WorkClass.FOREGROUND_DATABASE.value
                           if source is DataSource.DATABASE else WorkClass.FOREGROUND_CACHE.value),
            "absolute_deadline_ns": deadline_ns, "issued_ns": time.monotonic_ns(),
            "terminal_ns": None, "outcome": None, "reserved_bytes": 0,
            "actual_bytes": None, "retry_ordinal": retry_ordinal,
        })
        return operation_id

    def finish(self, operation_id: str, *, outcome: OperationOutcome,
               actual_bytes: int | None = None) -> None:
        for record in reversed(self.records):
            if record["operation_id"] == operation_id:
                record["terminal_ns"] = time.monotonic_ns()
                record["outcome"] = outcome.value
                record["actual_bytes"] = actual_bytes
                return
        raise RuntimeError("unknown operation ID")

    def count(self, request_id: str, operation: str) -> int:
        return sum(record["request_id"] == request_id and record["operation"] == operation
                   for record in self.records)


@dataclass(frozen=True, slots=True)
class ReadResponse:
    value: CacheValue | None
    record: RequestRecord


@dataclass(slots=True)
class _FillResult:
    value: CacheValue | None
    error: BaseException | None


@dataclass(slots=True)
class _FillEntry:
    task: asyncio.Task[_FillResult]
    origin_request_id: str
    generation: int
    waiters: int


class CacheAsideRouter:
    def __init__(self, *, run_id: str, ownership: Any, caches: dict[str, Any], database: Any,
                 demand_tracker: Any, metrics: Any, limits: ResourceLimits,
                 cache_retry: RetryPolicy, db_retry: RetryPolicy,
                 fill_write_retry: RetryPolicy, cleanup_timeout_seconds: float,
                 clock_ns: Callable[[], int] = time.monotonic_ns) -> None:
        self.run_id = run_id
        self.ownership = ownership
        self.caches = caches
        self.database = database
        self.demand_tracker = demand_tracker
        self.metrics = metrics
        self.limits = limits
        self.cache_retry = cache_retry
        self.db_retry = db_retry
        self.fill_write_retry = fill_write_retry
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.clock_ns = clock_ns
        self.ledger = OperationLedger()
        self._inflight = 0
        self.maximum_inflight = 0
        self._fills: dict[tuple[str, Key], _FillEntry] = {}
        self._fill_lock = asyncio.Lock()
        self._generation = 0
        self.maximum_coalesced_keys = 0

    @property
    def coalesced_key_count(self) -> int:
        return len(self._fills)

    def _terminal_record(self, *, request_id: str, key: Key, scheduled_ns: int,
                         submitted_ns: int | None, completed_ns: int | None,
                         timeout_seconds: float, outcome: OperationOutcome,
                         route: RouteCapture | None, source: DataSource,
                         work_class: WorkClass | None, coalesced_to: str | None,
                         reason: str, origin_id: str | None = None) -> RequestRecord:
        owner_id = origin_id or request_id
        return RequestRecord(
            1, self.run_id, request_id, scheduled_ns, submitted_ns, completed_ns,
            timeout_seconds, outcome, route, source, work_class,
            self.ledger.count(request_id, "cache_read"),
            self.ledger.count(owner_id, "database_read") if coalesced_to is None else 0,
            coalesced_to, reason, key,
            self.ledger.count(owner_id, "cache_write") if coalesced_to is None else 0,
        )

    async def _emit(self, record: RequestRecord) -> None:
        deadline = self.clock_ns() + int(self.cleanup_timeout_seconds * 1e9)
        await self.metrics.emit_request(record, deadline_ns=deadline)

    async def read(self, *, request_id: str, key: Key, scheduled_arrival_ns: int,
                   timeout_seconds: float, object_bytes: int) -> ReadResponse:
        submitted = self.clock_ns()
        route = self.ownership.capture(key)
        deadline = scheduled_arrival_ns + int(timeout_seconds * 1e9)
        if self._inflight >= self.limits.max_inflight_requests:
            record = self._terminal_record(
                request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                submitted_ns=submitted, completed_ns=self.clock_ns(), timeout_seconds=timeout_seconds,
                outcome=OperationOutcome.REFUSED, route=route, source=DataSource.NONE,
                work_class=None, coalesced_to=None, reason="foreground_inflight_limit")
            await self._emit(record)
            return ReadResponse(None, record)
        self._inflight += 1
        self.maximum_inflight = max(self.maximum_inflight, self._inflight)
        self.demand_tracker.observe(key, route.bucket, object_bytes, at_ns=submitted)
        entry: _FillEntry | None = None
        follower = False
        last_source = DataSource.NONE
        try:
            if submitted >= deadline:
                record = self._terminal_record(
                    request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                    submitted_ns=submitted, completed_ns=submitted, timeout_seconds=timeout_seconds,
                    outcome=OperationOutcome.TIMED_OUT, route=route, source=DataSource.NONE,
                    work_class=None, coalesced_to=None, reason="deadline_expired_before_io")
                await self._emit(record)
                return ReadResponse(None, record)
            cache_source = DataSource.NEW_CACHE if route.state is BucketState.NEW else DataSource.OLD_CACHE
            last_source = cache_source
            cache = self.caches[str(route.owner)]
            cache_result = None
            cache_error: BaseException | None = None
            for attempt in range(1, self.cache_retry.max_attempts + 1):
                operation_id = self.ledger.issue(request_id=request_id, operation="cache_read",
                                                 source=cache_source, owner=str(route.owner),
                                                 deadline_ns=deadline, retry_ordinal=attempt)
                try:
                    cache_result = await cache.read(key, source=cache_source,
                                                    deadline_ns=min(deadline, self.clock_ns() + int(
                                                        self.cache_retry.attempt_timeout_seconds * 1e9)))
                    self.ledger.finish(operation_id, outcome=OperationOutcome.COMPLETED,
                                       actual_bytes=(None if cache_result.value is None
                                                     else len(cache_result.value.payload)))
                    cache_error = None
                    break
                except TRANSIENT_ERRORS as error:
                    cache_error = error
                    self.ledger.finish(operation_id, outcome=(OperationOutcome.TIMED_OUT
                                                              if isinstance(error, TimeoutError)
                                                              else OperationOutcome.FAILED))
                    if attempt < self.cache_retry.max_attempts:
                        await self._backoff(self.cache_retry.backoff_seconds[attempt - 1], deadline)
            if cache_error is not None:
                raise cache_error
            if cache_result is not None and cache_result.value is not None:
                now = self.clock_ns()
                if cache_result.value.absolute_expiry_ns is None or now < cache_result.value.absolute_expiry_ns:
                    record = self._terminal_record(
                        request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                        submitted_ns=submitted, completed_ns=now, timeout_seconds=timeout_seconds,
                        outcome=OperationOutcome.COMPLETED, route=route, source=cache_source,
                        work_class=WorkClass.FOREGROUND_CACHE, coalesced_to=None, reason="cache_hit")
                    await self._emit(record)
                    return ReadResponse(cache_result.value, record)
            entry, follower = await self._join_or_create_fill(request_id, key, route, deadline)
            last_source = DataSource.DATABASE if not follower else cache_source
            remaining = (deadline - self.clock_ns()) / 1e9
            if remaining <= 0:
                raise TimeoutError("request deadline expired before shared fill")
            try:
                async with asyncio.timeout(remaining):
                    result = await asyncio.shield(entry.task)
            except asyncio.TimeoutError as error:
                raise TimeoutError("request deadline expired while waiting for shared fill") from error
            if result.error is not None:
                raise result.error
            completed = self.clock_ns()
            if result.value is None or completed > deadline:
                raise TimeoutError("shared fill completed too late")
            record = self._terminal_record(
                request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                submitted_ns=submitted, completed_ns=completed, timeout_seconds=timeout_seconds,
                outcome=OperationOutcome.COMPLETED, route=route, source=DataSource.DATABASE,
                work_class=(WorkClass.FOREGROUND_CACHE if follower else WorkClass.FOREGROUND_DATABASE),
                coalesced_to=(entry.origin_request_id if follower else None), reason="database_fill",
                origin_id=entry.origin_request_id)
            await self._emit(record)
            return ReadResponse(result.value, record)
        except asyncio.CancelledError:
            completed = self.clock_ns()
            owns_db = (entry is not None and not follower
                       and self.ledger.count(request_id, "database_read") > 0)
            record = self._terminal_record(
                request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                submitted_ns=submitted, completed_ns=completed, timeout_seconds=timeout_seconds,
                outcome=OperationOutcome.CANCELLED, route=route, source=last_source,
                work_class=(WorkClass.FOREGROUND_DATABASE if owns_db else
                            (None if last_source is DataSource.NONE else WorkClass.FOREGROUND_CACHE)),
                coalesced_to=(entry.origin_request_id if entry is not None and follower else None),
                reason="caller_cancelled", origin_id=(entry.origin_request_id if entry else None))
            await self._emit(record)
            raise
        except TimeoutError:
            completed = self.clock_ns()
            db_owned = entry is not None and not follower
            record = self._terminal_record(
                request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                submitted_ns=submitted, completed_ns=completed, timeout_seconds=timeout_seconds,
                outcome=OperationOutcome.TIMED_OUT, route=route,
                source=(DataSource.DATABASE if db_owned else last_source),
                work_class=(WorkClass.FOREGROUND_DATABASE if db_owned and
                            self.ledger.count(request_id, "database_read") else WorkClass.FOREGROUND_CACHE),
                coalesced_to=(entry.origin_request_id if entry is not None and follower else None),
                reason="foreground_timeout", origin_id=(entry.origin_request_id if entry else None))
            await self._emit(record)
            return ReadResponse(None, record)
        except BaseException as error:
            completed = self.clock_ns()
            db_owned = entry is not None and not follower
            source = DataSource.DATABASE if db_owned and self.ledger.count(request_id, "database_read") else last_source
            work_class = (WorkClass.FOREGROUND_DATABASE if source is DataSource.DATABASE
                          else (None if source is DataSource.NONE else WorkClass.FOREGROUND_CACHE))
            record = self._terminal_record(
                request_id=request_id, key=key, scheduled_ns=scheduled_arrival_ns,
                submitted_ns=submitted, completed_ns=completed, timeout_seconds=timeout_seconds,
                outcome=OperationOutcome.FAILED, route=route, source=source, work_class=work_class,
                coalesced_to=(entry.origin_request_id if entry is not None and follower else None),
                reason=f"foreground_error:{type(error).__name__}",
                origin_id=(entry.origin_request_id if entry else None))
            await self._emit(record)
            return ReadResponse(None, record)
        finally:
            if entry is not None:
                await self._detach(entry)
            self._inflight -= 1

    async def _backoff(self, seconds: float, deadline_ns: int) -> None:
        remaining = (deadline_ns - self.clock_ns()) / 1e9
        if remaining <= 0 or seconds > remaining:
            raise TimeoutError("retry backoff exceeds operation deadline")
        await asyncio.sleep(seconds)

    async def _join_or_create_fill(self, request_id: str, key: Key,
                                   route: RouteCapture, deadline_ns: int) -> tuple[_FillEntry, bool]:
        identity = (str(route.owner), key)
        async with self._fill_lock:
            entry = self._fills.get(identity)
            if entry is not None:
                entry.waiters += 1
                return entry, True
            if len(self._fills) >= self.limits.max_coalesced_keys:
                raise RuntimeError("coalescing_table_limit")
            self._generation += 1
            task = asyncio.create_task(self._fill(request_id, key, route, deadline_ns),
                                       name=f"fill:{route.owner}:{key}:{self._generation}")
            entry = _FillEntry(task, request_id, self._generation, 1)
            self._fills[identity] = entry
            self.maximum_coalesced_keys = max(self.maximum_coalesced_keys, len(self._fills))
            return entry, False

    async def _detach(self, entry: _FillEntry) -> None:
        cancel = False
        identity: tuple[str, Key] | None = None
        async with self._fill_lock:
            for candidate, current in self._fills.items():
                if current is entry:
                    identity = candidate
                    break
            if identity is None:
                return
            entry.waiters -= 1
            if entry.waiters == 0:
                cancel = not entry.task.done()
                if cancel:
                    entry.task.cancel()
        if cancel:
            try:
                async with asyncio.timeout(self.cleanup_timeout_seconds):
                    await asyncio.shield(entry.task)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        async with self._fill_lock:
            if identity is not None and self._fills.get(identity) is entry and entry.waiters == 0:
                self._fills.pop(identity, None)

    async def _fill(self, origin_id: str, key: Key, route: RouteCapture,
                    deadline_ns: int) -> _FillResult:
        value: CacheValue | None = None
        try:
            error: BaseException | None = None
            for attempt in range(1, self.db_retry.max_attempts + 1):
                operation_id = self.ledger.issue(request_id=origin_id, operation="database_read",
                                                 source=DataSource.DATABASE, owner=str(route.owner),
                                                 deadline_ns=deadline_ns, retry_ordinal=attempt)
                try:
                    attempt_deadline = min(deadline_ns, self.clock_ns() + int(
                        self.db_retry.attempt_timeout_seconds * 1e9))
                    value = await self.database.read_foreground(key, deadline_ns=attempt_deadline)
                    self.ledger.finish(operation_id, outcome=OperationOutcome.COMPLETED,
                                       actual_bytes=len(value.payload))
                    error = None
                    break
                except TRANSIENT_ERRORS as caught:
                    error = caught
                    self.ledger.finish(operation_id, outcome=(OperationOutcome.TIMED_OUT
                                                              if isinstance(caught, TimeoutError)
                                                              else OperationOutcome.FAILED))
                    if attempt < self.db_retry.max_attempts:
                        await self._backoff(self.db_retry.backoff_seconds[attempt - 1], deadline_ns)
            if error is not None or value is None:
                return _FillResult(None, error or RuntimeError("database returned no value"))
            if value.absolute_expiry_ns is not None and self.clock_ns() >= value.absolute_expiry_ns:
                return _FillResult(None, TimeoutError("authoritative value expired"))
            cache = self.caches[str(route.owner)]
            for attempt in range(1, self.fill_write_retry.max_attempts + 1):
                operation_id = self.ledger.issue(request_id=origin_id, operation="cache_write",
                                                 source=(DataSource.NEW_CACHE if route.state is BucketState.NEW
                                                         else DataSource.OLD_CACHE),
                                                 owner=str(route.owner), deadline_ns=deadline_ns,
                                                 retry_ordinal=attempt)
                try:
                    attempt_deadline = min(deadline_ns, self.clock_ns() + int(
                        self.fill_write_retry.attempt_timeout_seconds * 1e9))
                    await cache.write(key, value, deadline_ns=attempt_deadline)
                    self.ledger.finish(operation_id, outcome=OperationOutcome.COMPLETED,
                                       actual_bytes=len(value.payload))
                    break
                except TRANSIENT_ERRORS as caught:
                    self.ledger.finish(operation_id, outcome=(OperationOutcome.TIMED_OUT
                                                              if isinstance(caught, TimeoutError)
                                                              else OperationOutcome.FAILED))
                    if attempt < self.fill_write_retry.max_attempts:
                        await self._backoff(self.fill_write_retry.backoff_seconds[attempt - 1], deadline_ns)
            return _FillResult(value, None)
        except asyncio.CancelledError:
            return _FillResult(None, asyncio.CancelledError())
        except BaseException as error:
            return _FillResult(None, error)
