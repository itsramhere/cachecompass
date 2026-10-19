"""Selective, bounded donor copying and explicitly budgeted DB warming."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any

from .contracts import (
    ControllerAction, DataSource, MigrationAttemptRecord, OperationOutcome,
    RetryPolicy, WorkClass,
)
from .dataset import DatasetItem


TRANSIENT_ERRORS = (TimeoutError, OSError, ConnectionError)


@dataclass(slots=True)
class _DestinationReservation:
    enforcer: "GrantEnforcer"
    reserved_bytes: int
    issued: bool = False

    def issue(self) -> None:
        self.issued = True

    def release(self) -> None:
        if not self.issued:
            self.enforcer.remaining_destination_operations += 1
            self.enforcer.remaining_destination_bytes += self.reserved_bytes
            self.issued = True


@dataclass(slots=True)
class GrantEnforcer:
    """Absolute interval grants; replacement never adds to unused credit."""

    action: ControllerAction | None = None
    last_decided_at_ns: int = -1
    valid_until_ns: int = 0
    remaining_donor_operations: int = 0
    remaining_donor_bytes: int = 0
    remaining_background_db_operations: int = 0
    remaining_destination_operations: int = 0
    remaining_destination_bytes: int = 0
    charged: dict[str, int] = field(default_factory=lambda: {
        "donor_operations": 0, "donor_bytes": 0, "background_db_operations": 0,
        "destination_write_operations": 0, "destination_write_bytes": 0,
    })
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def apply_action(self, action: ControllerAction) -> None:
        if action.decided_at_ns <= self.last_decided_at_ns:
            raise ValueError("duplicate or older migration grant")
        self.action = action
        self.last_decided_at_ns = action.decided_at_ns
        self.valid_until_ns = action.decided_at_ns + action.budget.valid_for_ns
        self.remaining_donor_operations = action.budget.donor_operations
        self.remaining_donor_bytes = action.budget.donor_bytes
        self.remaining_background_db_operations = action.budget.background_db_operations
        self.remaining_destination_operations = action.budget.destination_write_operations
        self.remaining_destination_bytes = action.budget.destination_write_bytes

    def _valid(self) -> bool:
        return self.action is not None and time.monotonic_ns() < self.valid_until_ns

    async def reserve_destination(self, size: int) -> _DestinationReservation | None:
        async with self._lock:
            if (not self._valid() or self.remaining_destination_operations < 1
                    or self.remaining_destination_bytes < size):
                return None
            self.remaining_destination_operations -= 1
            self.remaining_destination_bytes -= size
            return _DestinationReservation(self, size)

    async def issue_donor(self, size: int) -> bool:
        async with self._lock:
            if (not self._valid() or self.remaining_donor_operations < 1
                    or self.remaining_donor_bytes < size):
                return False
            self.remaining_donor_operations -= 1
            self.remaining_donor_bytes -= size
            self.charged["donor_operations"] += 1
            self.charged["donor_bytes"] += size
            return True

    async def issue_database(self) -> bool:
        async with self._lock:
            if not self._valid() or self.remaining_background_db_operations < 1:
                return False
            self.remaining_background_db_operations -= 1
            self.charged["background_db_operations"] += 1
            return True

    async def issue_destination(self, reservation: _DestinationReservation) -> None:
        async with self._lock:
            if reservation.issued:
                raise RuntimeError("destination reservation already issued/released")
            reservation.issue()
            self.charged["destination_write_operations"] += 1
            self.charged["destination_write_bytes"] += reservation.reserved_bytes

    def summary(self) -> dict[str, Any]:
        return {
            "last_decided_at_ns": self.last_decided_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "remaining": {
                "donor_operations": self.remaining_donor_operations,
                "donor_bytes": self.remaining_donor_bytes,
                "background_db_operations": self.remaining_background_db_operations,
                "destination_write_operations": self.remaining_destination_operations,
                "destination_write_bytes": self.remaining_destination_bytes,
            },
            "charged": dict(self.charged),
        }


@dataclass(frozen=True, slots=True)
class MigrationResult:
    key: str
    bucket: int
    disposition: str
    source: str | None
    attempts: int
    reason: str


class BoundedMigrationScheduler:
    def __init__(self, *, run_id: str, ownership: Any, donor_caches: dict[str, Any],
                 destination_cache: Any, database: Any, metrics: Any, residency: Any,
                 worker_limit: int, queue_limit: int, max_buffered_payload_bytes: int,
                 donor_retry: RetryPolicy, db_retry: RetryPolicy, write_retry: RetryPolicy,
                 attempt_timeout_seconds: float) -> None:
        if min(worker_limit, queue_limit, max_buffered_payload_bytes) < 1:
            raise ValueError("positive migration bounds required")
        self.run_id = run_id
        self.ownership = ownership
        self.donor_caches = donor_caches
        self.destination_cache = destination_cache
        self.database = database
        self.metrics = metrics
        self.residency = residency
        self.worker_limit = worker_limit
        self.queue_limit = queue_limit
        self.max_buffered_payload_bytes = max_buffered_payload_bytes
        self.donor_retry = donor_retry
        self.db_retry = db_retry
        self.write_retry = write_retry
        self.attempt_timeout_seconds = attempt_timeout_seconds
        self.grants = GrantEnforcer()
        self.maximum_workers = 0
        self._active_workers = 0
        self._buffered_bytes = 0
        self.maximum_buffered_bytes = 0
        self._buffer_condition = asyncio.Condition()
        self._attempt_sequence = 0

    def apply_action(self, action: ControllerAction) -> None:
        self.grants.apply_action(action)

    async def _buffer_acquire(self, size: int, deadline_ns: int) -> None:
        if size > self.max_buffered_payload_bytes:
            raise ValueError("payload exceeds configured migration buffer")
        async with self._buffer_condition:
            while self._buffered_bytes + size > self.max_buffered_payload_bytes:
                remaining = (deadline_ns - time.monotonic_ns()) / 1e9
                if remaining <= 0:
                    raise TimeoutError("migration payload wait expired")
                async with asyncio.timeout(remaining):
                    await self._buffer_condition.wait()
            self._buffered_bytes += size
            self.maximum_buffered_bytes = max(self.maximum_buffered_bytes, self._buffered_bytes)

    async def _buffer_release(self, size: int) -> None:
        async with self._buffer_condition:
            self._buffered_bytes -= size
            self._buffer_condition.notify_all()

    async def migrate(self, items: tuple[DatasetItem, ...], *, deadline_ns: int,
                      allow_db_fallback: bool = True) -> tuple[MigrationResult, ...]:
        for item in items:
            bucket = self.ownership.bucket_for_key(item.key)
            if bucket not in self.ownership.affected_buckets:
                raise ValueError("migration may schedule only expansion-affected keys")
            if self.ownership.final_owner(bucket) != self.destination_cache.node_id:
                raise ValueError("migration destination disagrees with final map")
        queue: asyncio.Queue[DatasetItem | None] = asyncio.Queue(self.queue_limit)
        results: list[MigrationResult] = []

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    self._active_workers += 1
                    self.maximum_workers = max(self.maximum_workers, self._active_workers)
                    try:
                        results.append(await self._migrate_one(item, deadline_ns, allow_db_fallback))
                    finally:
                        self._active_workers -= 1
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker(), name=f"migration-worker-{index}")
                   for index in range(self.worker_limit)]
        for item in items:
            await queue.put(item)
        for _ in workers:
            await queue.put(None)
        await queue.join()
        await asyncio.gather(*workers)
        results.sort(key=lambda result: result.key)
        return tuple(results)

    async def _record(self, *, task_id: str, attempt: int, source: DataSource,
                      source_owner: str, destination_owner: str, work_class: WorkClass,
                      outcome: OperationOutcome, issued_bytes: int | None,
                      reserved_bytes: int, started_ns: int, reason: str) -> None:
        record = MigrationAttemptRecord(
            1, self.run_id, task_id, attempt, source, source_owner, destination_owner,
            self.attempt_timeout_seconds, work_class, outcome, 1, issued_bytes,
            started_ns, time.monotonic_ns(), reason, reserved_bytes)
        await self.metrics.emit_migration(record, deadline_ns=time.monotonic_ns() + 1_000_000_000)

    async def _migrate_one(self, item: DatasetItem, deadline_ns: int,
                           allow_db_fallback: bool) -> MigrationResult:
        bucket = self.ownership.bucket_for_key(item.key)
        donor_owner = str(self.ownership.old_owner(bucket))
        destination_owner = str(self.destination_cache.node_id)
        size = item.object_bytes
        reservation = await self.grants.reserve_destination(size)
        if reservation is None:
            return MigrationResult(item.key, bucket, "not_warmed", None, 0,
                                   "destination_grant_exhausted_or_pressure_paused")
        attempts = 0
        value = None
        source_name: str | None = None
        await self._buffer_acquire(size, deadline_ns)
        try:
            donor = self.donor_caches[donor_owner]
            for attempt in range(1, self.donor_retry.max_attempts + 1):
                if not await self.grants.issue_donor(size):
                    break
                attempts += 1
                started = time.monotonic_ns()
                task_id = f"donor:{bucket}:{item.key}"
                try:
                    result = await donor.read(item.key, source=DataSource.DONOR_CACHE,
                                              deadline_ns=min(deadline_ns, started + int(
                                                  self.attempt_timeout_seconds * 1e9)))
                    await self._record(task_id=task_id, attempt=attempt, source=DataSource.DONOR_CACHE,
                                       source_owner=donor_owner, destination_owner=destination_owner,
                                       work_class=WorkClass.DONOR_READ, outcome=OperationOutcome.COMPLETED,
                                       issued_bytes=(0 if result.value is None else len(result.value.payload)),
                                       reserved_bytes=size, started_ns=started,
                                       reason="donor_miss" if result.value is None else "donor_hit")
                    if result.value is not None:
                        value = result.value
                        source_name = "donor_cache"
                    break
                except TRANSIENT_ERRORS as error:
                    await self._record(task_id=task_id, attempt=attempt, source=DataSource.DONOR_CACHE,
                                       source_owner=donor_owner, destination_owner=destination_owner,
                                       work_class=WorkClass.DONOR_READ,
                                       outcome=(OperationOutcome.TIMED_OUT if isinstance(error, TimeoutError)
                                                else OperationOutcome.FAILED),
                                       issued_bytes=None, reserved_bytes=size, started_ns=started,
                                       reason=type(error).__name__)
                    if attempt < self.donor_retry.max_attempts:
                        await self._sleep_backoff(self.donor_retry.backoff_seconds[attempt - 1], deadline_ns)
            if value is None and allow_db_fallback:
                for attempt in range(1, self.db_retry.max_attempts + 1):
                    if not await self.grants.issue_database():
                        break
                    attempts += 1
                    started = time.monotonic_ns()
                    task_id = f"database:{bucket}:{item.key}"
                    try:
                        value = await self.database.read_for_warmup(
                            item.key, deadline_ns=min(deadline_ns, started + int(
                                self.attempt_timeout_seconds * 1e9)))
                        await self._record(task_id=task_id, attempt=attempt, source=DataSource.DATABASE,
                                           source_owner="database", destination_owner=destination_owner,
                                           work_class=WorkClass.DISCRETIONARY_DATABASE_WARMUP,
                                           outcome=OperationOutcome.COMPLETED,
                                           issued_bytes=len(value.payload), reserved_bytes=size,
                                           started_ns=started, reason="database_warmup_hit")
                        source_name = "database"
                        break
                    except TRANSIENT_ERRORS as error:
                        value = None
                        await self._record(task_id=task_id, attempt=attempt, source=DataSource.DATABASE,
                                           source_owner="database", destination_owner=destination_owner,
                                           work_class=WorkClass.DISCRETIONARY_DATABASE_WARMUP,
                                           outcome=(OperationOutcome.TIMED_OUT if isinstance(error, TimeoutError)
                                                    else OperationOutcome.FAILED),
                                           issued_bytes=None, reserved_bytes=size, started_ns=started,
                                           reason=type(error).__name__)
                        if attempt < self.db_retry.max_attempts:
                            await self._sleep_backoff(self.db_retry.backoff_seconds[attempt - 1], deadline_ns)
            if value is None:
                reservation.release()
                return MigrationResult(item.key, bucket, "not_warmed", source_name, attempts,
                                       "source_exhausted_or_db_budget_unavailable")
            if value.payload != item.payload:
                reservation.release()
                raise ValueError(f"authoritative payload mismatch for {item.key}")
            if value.absolute_expiry_ns is not None and time.monotonic_ns() >= value.absolute_expiry_ns:
                reservation.release()
                self.residency.invalidate(item.key, state=self.residency_state_expired,
                                          observed_at_ns=time.monotonic_ns())
                return MigrationResult(item.key, bucket, "not_warmed", source_name, attempts,
                                       "expired_before_destination_write")
            for attempt in range(1, self.write_retry.max_attempts + 1):
                current = reservation if attempt == 1 else await self.grants.reserve_destination(size)
                if current is None:
                    return MigrationResult(item.key, bucket, "not_warmed", source_name, attempts,
                                           "destination_retry_grant_exhausted")
                await self.grants.issue_destination(current)
                attempts += 1
                started = time.monotonic_ns()
                task_id = f"write:{bucket}:{item.key}"
                try:
                    await self.destination_cache.write(
                        item.key, value, deadline_ns=min(deadline_ns, started + int(
                            self.attempt_timeout_seconds * 1e9)))
                    await self._record(task_id=task_id, attempt=attempt, source=DataSource.NEW_CACHE,
                                       source_owner=destination_owner, destination_owner=destination_owner,
                                       work_class=WorkClass.DESTINATION_WRITE,
                                       outcome=OperationOutcome.COMPLETED, issued_bytes=size,
                                       reserved_bytes=size, started_ns=started, reason="destination_write")
                    self.residency.confirm(item.key, observed_at_ns=time.monotonic_ns(),
                                           valid_until_ns=value.absolute_expiry_ns)
                    return MigrationResult(item.key, bucket, "warmed", source_name, attempts, "written")
                except TRANSIENT_ERRORS as error:
                    await self._record(task_id=task_id, attempt=attempt, source=DataSource.NEW_CACHE,
                                       source_owner=destination_owner, destination_owner=destination_owner,
                                       work_class=WorkClass.DESTINATION_WRITE,
                                       outcome=(OperationOutcome.TIMED_OUT if isinstance(error, TimeoutError)
                                                else OperationOutcome.FAILED), issued_bytes=None,
                                       reserved_bytes=size, started_ns=started, reason=type(error).__name__)
                    if attempt < self.write_retry.max_attempts:
                        await self._sleep_backoff(self.write_retry.backoff_seconds[attempt - 1], deadline_ns)
            return MigrationResult(item.key, bucket, "not_warmed", source_name, attempts,
                                   "destination_write_retries_exhausted")
        finally:
            await self._buffer_release(size)

    @property
    def residency_state_expired(self):
        from .contracts import ResidencyState
        return ResidencyState.EXPIRED

    async def _sleep_backoff(self, seconds: float, deadline_ns: int) -> None:
        if time.monotonic_ns() + int(seconds * 1e9) >= deadline_ns:
            raise TimeoutError("migration backoff exceeds task deadline")
        await asyncio.sleep(seconds)
