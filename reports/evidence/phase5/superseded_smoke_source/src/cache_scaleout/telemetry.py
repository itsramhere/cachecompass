"""Bounded append-only telemetry and offered-request reconciliation."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any

from .contracts import EventRecord, MigrationAttemptRecord, RequestRecord, json_record


async def _within(deadline_ns: int, awaitable: Any) -> Any:
    remaining = (deadline_ns - time.monotonic_ns()) / 1e9
    if remaining <= 0:
        raise TimeoutError("telemetry deadline expired")
    async with asyncio.timeout(remaining):
        return await awaitable


class InMemoryMetricsSink:
    def __init__(self, capacity: int = 1024) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("positive telemetry capacity required")
        self.capacity = capacity
        self.events: list[EventRecord] = []
        self.requests: list[RequestRecord] = []
        self.migrations: list[MigrationAttemptRecord] = []

    def _append(self, target: list[Any], record: Any) -> None:
        if len(self.events) + len(self.requests) + len(self.migrations) >= self.capacity:
            raise BufferError("bounded telemetry capacity exceeded")
        target.append(record)

    async def emit_event(self, record: EventRecord, *, deadline_ns: int) -> None:
        if time.monotonic_ns() >= deadline_ns:
            raise TimeoutError("telemetry deadline expired")
        self._append(self.events, record)

    async def emit_request(self, record: RequestRecord, *, deadline_ns: int) -> None:
        if time.monotonic_ns() >= deadline_ns:
            raise TimeoutError("telemetry deadline expired")
        self._append(self.requests, record)

    async def emit_migration(self, record: MigrationAttemptRecord, *, deadline_ns: int) -> None:
        if time.monotonic_ns() >= deadline_ns:
            raise TimeoutError("telemetry deadline expired")
        self._append(self.migrations, record)

    async def flush(self, *, deadline_ns: int) -> None:
        if time.monotonic_ns() >= deadline_ns:
            raise TimeoutError("telemetry flush deadline expired")


class JsonlMetricsSink:
    """One bounded queue and writer; files are created exclusively per run."""

    def __init__(self, directory: Path, *, capacity: int) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError('positive bounded telemetry queue capacity required')
        self.directory = directory
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue(capacity)
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
        self.counts = {"event": 0, "request": 0, "migration": 0}

    async def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=False)
        for name in self.counts:
            (self.directory / f"{name}s.jsonl").touch(exist_ok=False)
        self._task = asyncio.create_task(self._writer(), name="phase3-telemetry-writer")

    async def _writer(self) -> None:
        handles = {name: (self.directory / f"{name}s.jsonl").open("a", encoding="utf-8")
                   for name in self.counts}
        try:
            while True:
                item = await self.queue.get()
                try:
                    if item is None:
                        return
                    kind, record = item
                    handles[kind].write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                    handles[kind].flush()
                    self.counts[kind] += 1
                finally:
                    self.queue.task_done()
        except BaseException as error:
            self._failure = error
            raise
        finally:
            for handle in handles.values():
                handle.close()

    async def _emit(self, kind: str, record: Any, deadline_ns: int) -> None:
        if self._failure:
            raise RuntimeError("telemetry writer failed") from self._failure
        await _within(deadline_ns, self.queue.put((kind, json_record(record))))

    async def emit_event(self, record: EventRecord, *, deadline_ns: int) -> None:
        await self._emit("event", record, deadline_ns)

    async def emit_request(self, record: RequestRecord, *, deadline_ns: int) -> None:
        await self._emit("request", record, deadline_ns)

    async def emit_migration(self, record: MigrationAttemptRecord, *, deadline_ns: int) -> None:
        await self._emit("migration", record, deadline_ns)

    async def flush(self, *, deadline_ns: int) -> None:
        await _within(deadline_ns, self.queue.join())
        if self._failure:
            raise RuntimeError("telemetry writer failed") from self._failure

    async def close(self, *, deadline_ns: int) -> None:
        await self.flush(deadline_ns=deadline_ns)
        await _within(deadline_ns, self.queue.put(None))
        assert self._task is not None
        await _within(deadline_ns, self._task)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    offered: int
    submitted: int
    unsubmitted: int
    terminal: int
    complete: bool
    reasons: tuple[str, ...]


def reconcile_offers(schedule: tuple[dict[str, Any], ...], requests: list[dict[str, Any]]) -> Reconciliation:
    offered_ids = [str(item["request_id"]) for item in schedule]
    terminal_ids = [str(item["request_id"]) for item in requests]
    reasons: list[str] = []
    if len(set(offered_ids)) != len(offered_ids):
        reasons.append("duplicate_offered_id")
    if len(set(terminal_ids)) != len(terminal_ids):
        reasons.append("duplicate_terminal_id")
    if set(offered_ids) != set(terminal_ids):
        reasons.append("offered_terminal_set_mismatch")
    offers = {str(item['request_id']): item for item in schedule}
    records = {str(item['request_id']): item for item in requests}
    terminal_outcomes = {'completed', 'failed', 'timed_out', 'cancelled', 'refused', 'unsubmitted'}
    for request_id, record in records.items():
        if record.get('outcome') not in terminal_outcomes:
            reasons.append('nonterminal_outcome')
        offer = offers.get(request_id, {})
        for field in ('key', 'scheduled_arrival_ns'):
            if field in offer and record.get(field) != offer[field]:
                reasons.append('offered_' + field + '_mismatch')
        if (record.get('outcome') == 'unsubmitted') != (record.get('submitted_ns') is None):
            reasons.append('submission_outcome_mismatch')
        origin_id = record.get('coalesced_to_request_id')
        if origin_id is not None:
            origin = records.get(origin_id)
            if (origin is None or origin.get('key') != record.get('key')
                    or origin.get('route', {}).get('owner') != record.get('route', {}).get('owner')
                    or origin.get('coalesced_to_request_id') is not None
                    or record.get('database_attempts', 0) or record.get('cache_write_attempts', 0)):
                reasons.append('invalid_shared_fill_origin')
    unsubmitted = sum(item.get("outcome") == "unsubmitted" for item in requests)
    submitted = sum(item.get("submitted_ns") is not None for item in requests)
    if len(schedule) != submitted + unsubmitted:
        reasons.append("scheduled_submission_reconciliation_failed")
    return Reconciliation(len(schedule), submitted, unsubmitted, len(requests), not reasons, tuple(reasons))
