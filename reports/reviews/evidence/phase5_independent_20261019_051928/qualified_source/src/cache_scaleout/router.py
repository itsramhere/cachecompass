"""Bounded cache-aside foreground reads with per-owner/key shared fills."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import time
from typing import Any, Callable
from .issuance import issuing

from .contracts import (
    BucketState, CacheValue, DataSource, Key, OperationOutcome, RequestRecord,
    ResourceLimits, RetryPolicy, RouteCapture, WorkClass,
)


TRANSIENT_ERRORS = (TimeoutError, OSError, ConnectionError)


@dataclass(slots=True)
class OperationLedger:
    records: list[dict[str, Any]] = field(default_factory=list)
    _sequence: int = 0
    capacity: int = 1024

    def issue(self, *, request_id: str, operation: str, source: DataSource,
              owner: str, deadline_ns: int, retry_ordinal: int) -> str:
        if len(self.records) >= self.capacity:
            raise BufferError('bounded foreground operation history exhausted')
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
    closing: bool = False


class CacheAsideRouter:
    def __init__(self, *, run_id: str, ownership: Any, caches: dict[str, Any], database: Any,
                 demand_tracker: Any, metrics: Any, limits: ResourceLimits,
                 cache_retry: RetryPolicy, db_retry: RetryPolicy,
                 fill_write_retry: RetryPolicy, cleanup_timeout_seconds: float,
                 residency: Any = None,
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
        self.ledger = OperationLedger(capacity=limits.max_pending_metric_records)
        self._inflight = 0
        self.maximum_inflight = 0
        self._fills: dict[tuple[str, Key], _FillEntry] = {}
        self._fill_lock = asyncio.Lock()
        self._generation = 0
        self.maximum_coalesced_keys = 0
        self.residency = residency
        self._pending_records: dict[str, RequestRecord] = {}
        self._cleanup_failed = False
        self._record_lock = asyncio.Lock()

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
        cache_count = self.ledger.count(request_id, "cache_read")
        db_count = self.ledger.count(owner_id, "database_read") if coalesced_to is None else 0
        if not cache_count and not db_count and coalesced_to is None:
            source, work_class = DataSource.NONE, None
        if source is DataSource.DATABASE and not db_count and coalesced_to is None:
            source = (DataSource.NEW_CACHE if route.state is BucketState.NEW else DataSource.OLD_CACHE
                      ) if cache_count else DataSource.NONE
            work_class = WorkClass.FOREGROUND_CACHE if cache_count else None
        return RequestRecord(
            1, self.run_id, request_id, scheduled_ns, submitted_ns, completed_ns,
            timeout_seconds, outcome, route, source, work_class,
            self.ledger.count(request_id, "cache_read"),
            self.ledger.count(owner_id, "database_read") if coalesced_to is None else 0,
            coalesced_to, reason, key,
            self.ledger.count(owner_id, "cache_write") if coalesced_to is None else 0,
        )

    async def _emit(self, record: RequestRecord) -> None:
        # A creator can terminate before its shared fill finishes issuing retries.
        # Preserve the terminal timestamp, but reconcile counts only after draining.
        self._pending_records[record.request_id] = record
        await self.finalize_requests()

    async def finalize_requests(self) -> None:
        async with self._record_lock:
            await self._finalize_requests_locked()

    async def _finalize_requests_locked(self) -> None:
        active_origins = {entry.origin_request_id for entry in self._fills.values()
                          if not entry.task.done()}
        for request_id, record in tuple(self._pending_records.items()):
            if request_id in active_origins:
                continue
            db_count = self.ledger.count(request_id, "database_read")
            writes = self.ledger.count(request_id, "cache_write")
            record = replace(record, database_attempts=db_count, cache_write_attempts=writes,
                             work_class=(WorkClass.FOREGROUND_DATABASE if db_count else record.work_class))
            deadline = self.clock_ns() + int(self.cleanup_timeout_seconds * 1e9)
            await self.metrics.emit_request(record, deadline_ns=deadline)
            del self._pending_records[request_id]

    async def _operation(self, request_id: str, operation: str, source: DataSource,
                         owner: str, deadline: int, attempt: int, awaitable: Any) -> Any:
        if self.clock_ns() >= deadline:
            awaitable.close()
            raise TimeoutError("operation deadline expired before issue")
        operation_id = None
        def issue():
            nonlocal operation_id
            if self.clock_ns() >= deadline:
                raise TimeoutError('deadline expired during connection acquisition')
            if operation_id is not None:
                raise RuntimeError('duplicate client issuance')
            operation_id = self.ledger.issue(request_id=request_id, operation=operation,
                source=source, owner=owner, deadline_ns=deadline, retry_ordinal=attempt)
            self.ledger.records[-1]['reserved_bytes'] = self.limits.max_buffered_payload_bytes + 1024
        outcome = OperationOutcome.FAILED
        actual = None
        try:
            target = self.database if operation == 'database_read' else self.caches[owner]
            if not getattr(target, 'reports_issuance', False):
                issue()  # Cooperative test adapters issue at entry.
            with issuing(issue):
                async with asyncio.timeout((deadline - self.clock_ns()) / 1e9):
                    result = await awaitable
            value = getattr(result, 'value', result)
            if isinstance(value, CacheValue):
                if len(value.payload) > self.limits.max_buffered_payload_bytes:
                    raise ValueError("foreground payload exceeds configured byte bound")
                if operation_id is not None:
                    next(row for row in reversed(self.ledger.records)
                         if row['operation_id'] == operation_id)['payload_bytes'] = len(value.payload)
            outcome = OperationOutcome.COMPLETED
            return result
        except asyncio.CancelledError:
            outcome = OperationOutcome.CANCELLED
            raise
        except TimeoutError:
            outcome = OperationOutcome.TIMED_OUT
            raise
        finally:
            if operation_id is not None:
                self.ledger.finish(operation_id, outcome=outcome, actual_bytes=actual)
            elif hasattr(awaitable, 'close'):
                awaitable.close()

    async def read(self, *, request_id: str, key: Key, scheduled_arrival_ns: int,
                   timeout_seconds: float, object_bytes: int) -> ReadResponse:
        submitted = self.clock_ns()
        route = self.ownership.capture(key)
        deadline = scheduled_arrival_ns + int(timeout_seconds * 1e9)
        if self._cleanup_failed:
            raise RuntimeError("router stopped after unconfirmed fill cleanup")
        self.demand_tracker.observe(key, route.bucket, object_bytes, at_ns=submitted)
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
                try:
                    attempt_deadline = min(deadline, self.clock_ns() + int(
                        self.cache_retry.attempt_timeout_seconds * 1e9))
                    cache_result = await self._operation(request_id, "cache_read", cache_source,
                        str(route.owner), attempt_deadline, attempt, cache.read(key, source=cache_source,
                                                    deadline_ns=min(deadline, self.clock_ns() + int(
                                                        self.cache_retry.attempt_timeout_seconds * 1e9))))
                    cache_error = None
                    break
                except TRANSIENT_ERRORS as error:
                    cache_error = error
                    if attempt < self.cache_retry.max_attempts:
                        await self._backoff(self.cache_retry.backoff_seconds[attempt - 1], deadline)
            if cache_error is not None:
                raise cache_error
            if self.residency is not None and route.state is BucketState.NEW:
                from .contracts import ResidencyState
                if cache_result.value is None:
                    invalidated_ns=self.clock_ns()
                    self.residency.invalidate(key, state=ResidencyState.EVICTED,
                                              observed_at_ns=invalidated_ns)
                    next(row for row in reversed(self.ledger.records) if row['request_id']==request_id and row['operation']=='cache_read')['residency_invalidated_ns']=invalidated_ns
            if cache_result is not None and cache_result.value is not None:
                now = self.clock_ns()
                if now <= deadline and (cache_result.value.absolute_expiry_ns is None or now < cache_result.value.absolute_expiry_ns):
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
            if (result.value is None or completed > deadline
                    or (result.value.absolute_expiry_ns is not None
                        and completed >= result.value.absolute_expiry_ns)):
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
            if request_id in self._pending_records:
                raise  # Failed durable emission invalidates measurement.
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
            await self.finalize_requests()

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
            if entry is not None and entry.closing:
                raise RuntimeError("shared_fill_cleanup_in_progress")
            if entry is not None and not entry.task.done():
                entry.waiters += 1
                return entry, True
            if entry is not None:
                self._fills.pop(identity)
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
                    entry.closing = True
                    entry.task.cancel()
        if cancel:
            try:
                async with asyncio.timeout(self.cleanup_timeout_seconds):
                    await asyncio.shield(entry.task)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                if not entry.task.done():
                    self._cleanup_failed = True
                    raise RuntimeError("shared fill cleanup deadline exceeded; issuance stopped")
        async with self._fill_lock:
            if identity is not None and self._fills.get(identity) is entry and entry.waiters == 0 and entry.task.done():
                self._fills.pop(identity, None)

    async def _fill(self, origin_id: str, key: Key, route: RouteCapture,
                    deadline_ns: int) -> _FillResult:
        value: CacheValue | None = None
        try:
            error: BaseException | None = None
            for attempt in range(1, self.db_retry.max_attempts + 1):
                try:
                    attempt_deadline = min(deadline_ns, self.clock_ns() + int(
                        self.db_retry.attempt_timeout_seconds * 1e9))
                    value = await self._operation(origin_id, "database_read", DataSource.DATABASE,
                        str(route.owner), attempt_deadline, attempt,
                        self.database.read_foreground(key, deadline_ns=attempt_deadline))
                    error = None
                    break
                except TRANSIENT_ERRORS as caught:
                    error = caught
                    if attempt < self.db_retry.max_attempts:
                        await self._backoff(self.db_retry.backoff_seconds[attempt - 1], deadline_ns)
            if error is not None or value is None:
                return _FillResult(None, error or RuntimeError("database returned no value"))
            if value.absolute_expiry_ns is not None and self.clock_ns() >= value.absolute_expiry_ns:
                return _FillResult(None, TimeoutError("authoritative value expired"))
            cache = self.caches[str(route.owner)]
            for attempt in range(1, self.fill_write_retry.max_attempts + 1):
                try:
                    attempt_deadline = min(deadline_ns, self.clock_ns() + int(
                        self.fill_write_retry.attempt_timeout_seconds * 1e9))
                    await self._operation(origin_id, "cache_write",
                        DataSource.NEW_CACHE if route.state is BucketState.NEW else DataSource.OLD_CACHE,
                        str(route.owner), attempt_deadline, attempt,
                        cache.write(key, value, deadline_ns=attempt_deadline))
                    break
                except TRANSIENT_ERRORS as caught:
                    if attempt < self.fill_write_retry.max_attempts:
                        delay = self.fill_write_retry.backoff_seconds[attempt - 1]
                        if self.clock_ns() + int(delay * 1e9) >= deadline_ns:
                            break
                        await self._backoff(delay, deadline_ns)
                except Exception:
                    # A non-transient cache-fill error is not a failed
                    # authoritative read and must not start another retry tree.
                    break
            return _FillResult(value, None)
        except asyncio.CancelledError:
            return _FillResult(None, asyncio.CancelledError())
        except BaseException as error:
            return _FillResult(None, error)
