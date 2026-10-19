"""Selective, bounded donor copying and explicitly budgeted DB warming."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import time
import math
from typing import Any

from .contracts import (
    ControllerAction, DataSource, MigrationAttemptRecord, OperationOutcome,
    RetryPolicy, WorkClass,
)
from .dataset import DatasetItem
from .issuance import issuing


TRANSIENT_ERRORS = (TimeoutError, OSError, ConnectionError)


class UnissuedRetry(TimeoutError):
    """A provisional client wait did not issue; retain its retry ordinal."""


@dataclass(slots=True)
class _DestinationReservation:
    enforcer: "GrantEnforcer"
    reserved_bytes: int
    issued: bool = False
    generation: int = 0
    source_token_event: int | None = None
    write_token_event: int | None = None

    def issue(self) -> None:
        self.issued = True

    def release(self) -> None:
        if not self.issued and self.generation == self.enforcer.last_decided_at_ns:
            self.enforcer.remaining_destination_operations += 1
            self.enforcer.remaining_destination_bytes += self.reserved_bytes
            self.enforcer.changed.set()
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
    changed: asyncio.Event = field(default_factory=asyncio.Event)

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
        self.changed.set()

    def _valid(self) -> bool:
        return (self.action is not None and self.action.decided_at_ns <= time.monotonic_ns()
                < self.valid_until_ns)

    async def reserve_destination(self, size: int) -> _DestinationReservation | None:
        async with self._lock:
            if (not self._valid() or self.remaining_destination_operations < 1
                    or self.remaining_destination_bytes < size):
                return None
            self.remaining_destination_operations -= 1
            self.remaining_destination_bytes -= size
            return _DestinationReservation(self, size, generation=self.last_decided_at_ns)

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
            if not self._valid() or reservation.generation != self.last_decided_at_ns:
                raise TimeoutError("destination reservation expired or was replaced")
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

    def release_unissued(self, work_class, size, generation):
        dimensions = {WorkClass.DONOR_READ: ('donor_operations','donor_bytes'),
                      WorkClass.DISCRETIONARY_DATABASE_WARMUP: ('background_db_operations',),
                      WorkClass.DESTINATION_WRITE: ('destination_write_operations','destination_write_bytes')}[work_class]
        names = {'destination_write_operations':'remaining_destination_operations',
                 'destination_write_bytes':'remaining_destination_bytes'}
        for dimension in dimensions:
            amount = size if dimension.endswith('bytes') else 1
            self.charged[dimension] -= amount
            if generation == self.last_decided_at_ns:
                attr = names.get(dimension, 'remaining_'+dimension)
                setattr(self, attr, getattr(self, attr)+amount)
        self.changed.set()


@dataclass(frozen=True, slots=True)
class MigrationResult:
    key: str
    bucket: int
    disposition: str
    source: str | None
    attempts: int
    reason: str
    terminal_ns: int = 0


class TokenBuckets:
    """Five independent monotonic token dimensions, empty on expansion."""
    def __init__(self, rates: dict[str, float], bursts: dict[str, int], clock=time.monotonic_ns, max_events=16384):
        self.clock = clock
        self.rates = dict(rates)
        self.bursts = dict(bursts)
        if self.rates.keys() != self.bursts.keys() or any(
                isinstance(rate, bool) or not math.isfinite(rate) or rate < 0 for rate in self.rates.values()):
            raise ValueError("finite matching rate/burst dimensions required")
        if any(type(value) is not int or value < 1 for value in bursts.values()):
            raise ValueError("positive integer bursts required")
        self.tokens = {name: 0.0 for name in rates}
        self.updated = clock()
        self.max_events=max_events
        self.events=[]
        self._event('init',at_ns=self.updated,rates=self.rates.copy(),bursts=self.bursts.copy())

    def _event(self,kind,*,at_ns=None,**detail):
        if len(self.events)>=self.max_events:raise BufferError('bounded token history exhausted')
        identifier=len(self.events)
        self.events.append({'event_id':identifier,'kind':kind,'at_ns':self.clock() if at_ns is None else at_ns,**detail})
        return identifier

    def set_rates(self,rates):
        self.refill()
        self.rates=dict(rates)
        for d,value in rates.items():
            if value==0:self.tokens[d]=0.
        self._event('rates',at_ns=self.updated,rates=self.rates.copy())

    def return_unissued(self,amounts,*,event_id,permitted):
        self.refill()
        if permitted:
            for d,amount in amounts.items():
                if self.rates[d]>0:self.tokens[d]=min(self.bursts[d],self.tokens[d]+amount)
        self._event('refund' if permitted else 'forfeit',at_ns=self.updated,amounts=amounts.copy(),acquire_event_id=event_id)

    def refill(self):
        now = self.clock()
        elapsed = max(0, now - self.updated) / 1e9
        for name, rate in self.rates.items():
            self.tokens[name] = min(self.bursts[name], self.tokens[name] + elapsed * rate)
        self.updated = now

    async def acquire(self, amounts: dict[str, int], deadline_ns: int):
        if any(amount > self.bursts[name] for name, amount in amounts.items()):
            raise ValueError("encoded operation exceeds token burst")
        while True:
            self.refill()
            if self.clock() >= deadline_ns:
                raise TimeoutError("token/task/grant deadline expired")
            if all(self.tokens[name] >= amount for name, amount in amounts.items()):
                event=self._event('acquire',at_ns=self.updated,amounts=amounts.copy())
                for name, amount in amounts.items():
                    self.tokens[name] -= amount
                return event
            delay = max((amount - self.tokens[name]) / self.rates[name]
                        if self.rates[name] else float('inf') for name, amount in amounts.items())
            remaining = (deadline_ns - self.clock()) / 1e9
            if delay >= remaining:
                await asyncio.sleep(max(0, remaining))
                raise TimeoutError("tokens unavailable within task/grant deadline")
            await asyncio.sleep(max(0.0001, delay))


class BoundedMigrationScheduler:
    def __init__(self, *, run_id: str, ownership: Any, donor_caches: dict[str, Any],
                 destination_cache: Any, database: Any, metrics: Any, residency: Any,
                 worker_limit: int, queue_limit: int, max_buffered_payload_bytes: int,
                 donor_retry: RetryPolicy, db_retry: RetryPolicy, write_retry: RetryPolicy,
                 attempt_timeout_seconds: float, rates: dict[str, float] | None = None,
                 bursts: dict[str, int] | None = None, cleanup_timeout_seconds: float = 1.,
                 max_operation_records: int = 4096) -> None:
        if any(type(value) is not int or value < 1
               for value in (worker_limit, queue_limit, max_buffered_payload_bytes, max_operation_records)):
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
        dimensions = ("donor_operations", "donor_bytes", "background_db_operations",
                      "destination_write_operations", "destination_write_bytes")
        self.tokens = TokenBuckets(rates or {name: 1_000_000. for name in dimensions},
                                  bursts or {name: 65536 for name in dimensions},max_events=max_operation_records*8)
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self._running = False
        self.maximum_queue_depth = 0
        self._stopped = False
        self.operation_records: list[dict[str, Any]] = []
        self._attempt_records: list[MigrationAttemptRecord] = []
        self.max_operation_records = max_operation_records

    def apply_action(self, action: ControllerAction) -> None:
        if action.expected_routing_epoch != self.ownership.snapshot.epoch:
            raise ValueError('migration action routing epoch changed')
        if self.grants.action is None:
            self.tokens.updated = time.monotonic_ns()
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
                      allow_db_fallback: bool = True, order_key=None, on_result=None) -> tuple[MigrationResult, ...]:
        if self._running or self._stopped:
            raise RuntimeError("migration pass already active or stopped after cleanup failure")
        if len({item.key for item in items}) != len(items):
            raise ValueError("duplicate migration key")
        for item in items:
            bucket = self.ownership.bucket_for_key(item.key)
            if bucket not in self.ownership.affected_buckets:
                raise ValueError("migration may schedule only expansion-affected keys")
            if self.ownership.final_owner(bucket) != self.destination_cache.node_id:
                raise ValueError("migration destination disagrees with final map")
        queue: asyncio.Queue[DatasetItem | None] = asyncio.Queue(self.queue_limit)
        results: list[MigrationResult] = []
        unissued = {item.key: item for item in items}

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    if order_key is not None:
                        item = min(unissued.values(), key=order_key)
                    unissued.pop(item.key)
                    self._active_workers += 1
                    self.maximum_workers = max(self.maximum_workers, self._active_workers)
                    try:
                        result = await self._migrate_one(item, deadline_ns, allow_db_fallback)
                        results.append(result)
                        if on_result is not None:
                            on_result(result)
                    finally:
                        self._active_workers -= 1
                finally:
                    queue.task_done()

        async def feed():
            for item in items:
                await queue.put(item)
                self.maximum_queue_depth = max(self.maximum_queue_depth, queue.qsize())
            for _ in range(self.worker_limit):
                await queue.put(None)

        self._running = True
        try:
            async with asyncio.timeout(max(0, (deadline_ns-time.monotonic_ns())/1e9) + self.cleanup_timeout_seconds):
                try:
                    async with asyncio.TaskGroup() as group:
                        group.create_task(feed(), name="migration-producer")
                        for index in range(self.worker_limit):
                            group.create_task(worker(), name=f"migration-worker-{index}")
                except ExceptionGroup as errors:
                    raise errors.exceptions[0]
        finally:
            self._running = False
            # Durable telemetry waits outside the worker/payload critical section.
            pending, self._attempt_records = self._attempt_records, []
            for record in pending:
                await self.metrics.emit_migration(record, deadline_ns=time.monotonic_ns()+1_000_000_000)
        results.sort(key=lambda result: result.key)
        return tuple(results)

    async def _record(self, *, task_id: str, attempt: int, source: DataSource,
                      source_owner: str, destination_owner: str, work_class: WorkClass,
                      outcome: OperationOutcome, issued_bytes: int | None,
                      reserved_bytes: int, started_ns: int, reason: str, timeout_seconds: float) -> None:
        record = MigrationAttemptRecord(
            1, self.run_id, task_id, attempt, source, source_owner, destination_owner,
            timeout_seconds, work_class, outcome, 1, issued_bytes,
            started_ns, time.monotonic_ns(), reason, reserved_bytes)
        self._attempt_records.append(record)

    async def _attempt(self, *, item, stage, attempt, source, source_owner, work_class,
                       reserved_bytes, deadline_ns, operation, parent_task_id=None, token_event_id=None, value_payload=None, timeout_seconds=None):
        self._attempt_sequence += 1
        started = time.monotonic_ns()
        row = {"operation_id": f"migration-{self._attempt_sequence:08d}",
               "key": item.key, "bucket": self.ownership.bucket_for_key(item.key),
               "task_id": f"{stage}:{self.ownership.bucket_for_key(item.key)}:{item.key}",
               "parent_task_id": parent_task_id,
               "operation": stage, "source": source.value, "target_owner": source_owner,
               "work_class": work_class.value, "absolute_deadline_ns": deadline_ns,
               "issued_ns": started, "terminal_ns": None, "outcome": None,
               "reserved_bytes": reserved_bytes, "actual_bytes": None,
               "retry_ordinal": attempt,"token_event_id":token_event_id,
               "timeout_seconds":timeout_seconds or self.attempt_timeout_seconds}
        if value_payload is not None:
            import hashlib
            row['payload_sha256']=hashlib.sha256(value_payload).hexdigest()
            row['payload_bytes']=len(value_payload)
        generation = self.grants.last_decided_at_ns
        row["grant_generation_ns"] = generation
        issued = False
        def issue():
            nonlocal issued
            if len(self.operation_records) >= self.max_operation_records:
                raise BufferError('bounded migration operation history exhausted')
            if (time.monotonic_ns() >= deadline_ns or not self.grants._valid()
                    or generation != self.grants.last_decided_at_ns):
                raise TimeoutError('grant/task expired while acquiring connection')
            if issued:
                raise RuntimeError('duplicate migration issuance')
            issued = True
            row['issued_ns'] = time.monotonic_ns()
            self.operation_records.append(row)
        outcome = OperationOutcome.FAILED
        try:
            client = (self.database if source is DataSource.DATABASE else
                      self.destination_cache if source is DataSource.NEW_CACHE else self.donor_caches[source_owner])
            if not getattr(client, 'reports_issuance', False):
                issue()
            with issuing(issue):
                async with asyncio.timeout(max(0, (deadline_ns-started)/1e9)):
                    result = await operation
            value = getattr(result, 'value', result)
            payload = getattr(value, 'payload', b'')
            if len(payload) > item.object_bytes:
                raise ValueError("source payload exceeds registry bound")
            # Conservative RESP application exchange count (pipeline framing is
            # covered by the fixed protocol envelope); SQL bytes are unknown.
            # Drivers do not expose complete encoded exchanges. Unknown is null;
            # do not fabricate actual protocol bytes from payload length.
            actual = None
            if actual is not None and actual > reserved_bytes:
                raise ValueError("encoded response exceeds reservation")
            row['actual_bytes'] = actual
            observed_payload=value_payload if value_payload is not None else getattr(value,'payload',None)
            import hashlib
            row['payload_sha256']=hashlib.sha256(observed_payload).hexdigest() if observed_payload is not None else None
            row['payload_bytes']=len(observed_payload) if observed_payload is not None else None
            if hasattr(result,'valid_until_ns'):row['residency_valid_until_ns']=result.valid_until_ns
            outcome = OperationOutcome.COMPLETED
            return result
        except asyncio.CancelledError:
            outcome = OperationOutcome.CANCELLED
            raise
        except TimeoutError as error:
            outcome = OperationOutcome.TIMED_OUT
            if not issued:raise UnissuedRetry(str(error)) from error
            raise
        finally:
            row.update(outcome=outcome.value, terminal_ns=time.monotonic_ns())
            if issued:
                await self._record(task_id=row['task_id'], attempt=attempt, source=source,
                    source_owner=source_owner, destination_owner=str(self.destination_cache.node_id),
                    work_class=work_class, outcome=outcome, issued_bytes=row['actual_bytes'],
                    reserved_bytes=reserved_bytes, started_ns=row['issued_ns'], reason=stage,timeout_seconds=row['timeout_seconds'])
            else:
                if hasattr(operation, 'close'):
                    operation.close()
                self.grants.release_unissued(work_class, reserved_bytes, generation)
                dimensions = {WorkClass.DONOR_READ: ('donor_operations','donor_bytes'),
                              WorkClass.DISCRETIONARY_DATABASE_WARMUP: ('background_db_operations',),
                              WorkClass.DESTINATION_WRITE: ('destination_write_operations','destination_write_bytes')}[work_class]
                amounts={d:reserved_bytes if d.endswith('bytes') else 1 for d in dimensions}
                self.tokens.return_unissued(amounts,event_id=token_event_id,
                    permitted=generation==self.grants.last_decided_at_ns and self.grants._valid())

    async def _migrate_one(self, item: DatasetItem, deadline_ns: int,
                           allow_db_fallback: bool) -> MigrationResult:
        bucket = self.ownership.bucket_for_key(item.key)
        donor_owner = str(self.ownership.old_owner(bucket))
        destination_owner = str(self.destination_cache.node_id)
        size = item.object_bytes
        # The immutable registry bounds payload; the envelope covers namespaced
        # RESP keys, commands, framing and small replies. SQL actual bytes remain
        # unknown rather than being misreported as payload length.
        encoded_bound = size + 1024
        attempts = 0
        value = None
        source_name = None
        source_missing = False
        reservation = None
        acquired = False
        def terminal(reason):
            count = sum(row['key'] == item.key for row in self.operation_records)
            return MigrationResult(item.key, bucket, "not_warmed", source_name, count, reason,time.monotonic_ns())
        try:
            await self._buffer_acquire(size, deadline_ns)
            acquired = True
            reservation = await self._wait_grant(self.grants.reserve_destination, encoded_bound, deadline_ns)
            if reservation is None:
                return terminal("destination_grant_exhausted_or_pressure_paused")
            # Source IO requires both a payload slot and a destination reservation.
            for stage, client, policy, source, owner, work_class in (
                ("donor", self.donor_caches[donor_owner], self.donor_retry,
                 DataSource.DONOR_CACHE, donor_owner, WorkClass.DONOR_READ),
                ("database", self.database, self.db_retry, DataSource.DATABASE,
                 "database", WorkClass.DISCRETIONARY_DATABASE_WARMUP)):
                if value is not None or (stage == "database" and not allow_db_fallback):
                    break
                attempt=1
                while attempt<=policy.max_attempts and time.monotonic_ns()<deadline_ns:
                    reservation, issued = await self._source_slot(reservation, encoded_bound, stage, deadline_ns)
                    if not issued:
                        break
                    attempts += 1
                    attempt_deadline = min(deadline_ns, time.monotonic_ns() + int(
                        policy.attempt_timeout_seconds * 1e9))
                    operation = (client.read(item.key, source=source, deadline_ns=attempt_deadline)
                                 if stage == "donor" else client.read_for_warmup(
                                     item.key, deadline_ns=attempt_deadline))
                    try:
                        result = await self._attempt(item=item, stage=stage, attempt=attempt,
                            source=source, source_owner=owner, work_class=work_class,
                            reserved_bytes=encoded_bound, deadline_ns=attempt_deadline,
                            operation=operation,token_event_id=reservation.source_token_event,timeout_seconds=policy.attempt_timeout_seconds)
                        value = result.value if stage == "donor" else result
                        if stage == "donor" and value is None:
                            source_missing = True
                        if value is not None:
                            source_name = "donor_cache" if stage == "donor" else "database"
                        break
                    except UnissuedRetry:
                        continue
                    except TRANSIENT_ERRORS:
                        if attempt < policy.max_attempts:
                            await self._sleep_backoff(policy.backoff_seconds[attempt-1], deadline_ns)
                        attempt+=1
            if value is None:
                return terminal("donor_missing_db_fallback_disabled" if source_missing and not allow_db_fallback
                                else "donor_missing_db_budget_or_deadline" if source_missing
                                else "source_exhausted_or_db_budget_unavailable")
            if value.payload != item.payload:
                raise ValueError(f"authoritative payload mismatch for {item.key}")
            # Registry expiry caps both donor and authoritative values, even if a
            # service unexpectedly retained the object with an extended TTL.
            expiries = [expiry for expiry in (value.absolute_expiry_ns, item.absolute_expiry_ns)
                        if expiry is not None]
            if expiries:
                from dataclasses import replace
                value = replace(value, absolute_expiry_ns=min(expiries))
            if value.absolute_expiry_ns is not None and time.monotonic_ns() >= value.absolute_expiry_ns:
                self.residency.invalidate(item.key, state=self.residency_state_expired,
                                          observed_at_ns=time.monotonic_ns())
                return terminal("expired_before_destination_write")
            attempt=1
            while attempt<=self.write_retry.max_attempts and time.monotonic_ns()<deadline_ns:
                if attempt > 1:
                    reservation = await self._wait_grant(self.grants.reserve_destination, encoded_bound, deadline_ns)
                if reservation is None:
                    return terminal("destination_retry_grant_exhausted")
                reservation = await self._destination_slot(reservation, encoded_bound, deadline_ns)
                if reservation is None:
                    return terminal('destination_grant_unavailable_until_deadline')
                attempts += 1
                attempt_deadline = min(deadline_ns, time.monotonic_ns() + int(
                    self.write_retry.attempt_timeout_seconds * 1e9))
                try:
                    receipt = await self._attempt(item=item, stage="write", attempt=attempt,
                        source=DataSource.NEW_CACHE, source_owner=destination_owner,
                        work_class=WorkClass.DESTINATION_WRITE, reserved_bytes=encoded_bound,
                        deadline_ns=attempt_deadline,
                        operation=self.destination_cache.write(item.key, value, deadline_ns=attempt_deadline),
                        parent_task_id=f"{'donor' if source_name == 'donor_cache' else 'database'}:{bucket}:{item.key}",
                        token_event_id=reservation.write_token_event,value_payload=value.payload,timeout_seconds=self.write_retry.attempt_timeout_seconds)
                    confirmed=time.monotonic_ns()
                    self.residency.confirm(item.key, observed_at_ns=confirmed,valid_until_ns=receipt.valid_until_ns)
                    next(r for r in reversed(self.operation_records) if r['key']==item.key and r['operation']=='write' and r['outcome']=='completed')['residency_confirmed_ns']=confirmed
                    return MigrationResult(item.key, bucket, "warmed", source_name,sum(row["key"]==item.key for row in self.operation_records), "written",time.monotonic_ns())
                except UnissuedRetry:
                    continue
                except TRANSIENT_ERRORS:
                    if attempt < self.write_retry.max_attempts:
                        await self._sleep_backoff(self.write_retry.backoff_seconds[attempt-1], deadline_ns)
                    attempt+=1
            return terminal("destination_write_retries_exhausted")
        except TimeoutError:
            return terminal("task_or_grant_deadline_expired")
        finally:
            if reservation is not None:
                reservation.release()
            if acquired:
                await self._buffer_release(size)

    @property
    def residency_state_expired(self):
        from .contracts import ResidencyState
        return ResidencyState.EXPIRED

    def _return_tokens(self, dimensions, *, generation, event_id):
        self.tokens.return_unissued(dimensions,event_id=event_id,
            permitted=generation==self.grants.last_decided_at_ns and self.grants._valid())

    async def _renew_destination(self, reservation, size, deadline_ns):
        if reservation is not None:
            reservation.release()
        fresh = await self._wait_grant(self.grants.reserve_destination,size,deadline_ns)
        if fresh is None or reservation is None:
            return fresh
        # Keep the caller's cleanup handle stable across grant replacements.
        # No await occurs while transferring ownership of the new reservation.
        reservation.generation = fresh.generation
        reservation.reserved_bytes = fresh.reserved_bytes
        reservation.issued = False
        fresh.issued = True
        return reservation

    async def _source_slot(self, reservation, size, stage, deadline_ns):
        dimensions = ({'donor_operations':1,'donor_bytes':size} if stage == 'donor'
                      else {'background_db_operations':1})
        while time.monotonic_ns() < deadline_ns:
            self.grants.changed.clear()
            if (reservation is None or reservation.issued or reservation.generation != self.grants.last_decided_at_ns
                    or not self.grants._valid()):
                reservation = await self._renew_destination(reservation,size,deadline_ns)
                if reservation is None:
                    return None, False
            waiting_generation = self.grants.last_decided_at_ns
            try:
                token_event=await self.tokens.acquire(dimensions,min(deadline_ns,self.grants.valid_until_ns))
            except TimeoutError:
                if time.monotonic_ns() < deadline_ns and (waiting_generation != self.grants.last_decided_at_ns or not self.grants._valid()):
                    continue
                raise
            if reservation.generation != self.grants.last_decided_at_ns:
                self._return_tokens(dimensions,generation=waiting_generation,event_id=token_event)
                continue
            issued = (await self.grants.issue_donor(size) if stage == 'donor'
                      else await self.grants.issue_database())
            if issued:
                reservation.source_token_event=token_event
                return reservation, True
            self._return_tokens(dimensions,generation=waiting_generation,event_id=token_event)
            try:
                async with asyncio.timeout(max(0,(deadline_ns-time.monotonic_ns())/1e9)):
                    await self.grants.changed.wait()
            except TimeoutError:
                break
        return reservation, False

    async def _destination_slot(self, reservation, size, deadline_ns):
        dimensions = {'destination_write_operations':1,'destination_write_bytes':size}
        while time.monotonic_ns() < deadline_ns:
            if (reservation is None or reservation.issued or reservation.generation != self.grants.last_decided_at_ns
                    or not self.grants._valid()):
                reservation = await self._renew_destination(reservation,size,deadline_ns)
                if reservation is None:
                    return None
            waiting_generation = self.grants.last_decided_at_ns
            try:
                token_event=await self.tokens.acquire(dimensions,min(deadline_ns,self.grants.valid_until_ns))
            except TimeoutError:
                if time.monotonic_ns() < deadline_ns and (waiting_generation != self.grants.last_decided_at_ns or not self.grants._valid()):
                    continue
                raise
            if reservation.generation != self.grants.last_decided_at_ns:
                self._return_tokens(dimensions,generation=waiting_generation,event_id=token_event)
                continue
            try:
                await self.grants.issue_destination(reservation)
                reservation.write_token_event=token_event
                return reservation
            except TimeoutError:
                self._return_tokens(dimensions,generation=waiting_generation,event_id=token_event)
        return None

    async def _wait_grant(self, method, size, deadline_ns):
        while time.monotonic_ns() < deadline_ns:
            self.grants.changed.clear()
            result = await method() if size is None else await method(size)
            if result:
                return result
            remaining = (deadline_ns-time.monotonic_ns())/1e9
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    await self.grants.changed.wait()
            except TimeoutError:
                break
        return None

    async def _sleep_backoff(self, seconds: float, deadline_ns: int) -> None:
        if time.monotonic_ns() + int(seconds * 1e9) >= deadline_ns:
            raise TimeoutError("migration backoff exceeds task deadline")
        await asyncio.sleep(seconds)
