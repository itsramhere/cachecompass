"""Phase 2 data contracts for the single-router scale-out experiment.

This module deliberately contains no network or request-path implementation.  It
defines the values that later phases must exchange and validates chronology,
boundedness, ownership capture, retry charging, and causal observations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
import math
from typing import Any, NewType

BucketId = NewType("BucketId", int)
RoutingEpoch = NewType("RoutingEpoch", int)
NodeId = NewType("NodeId", str)
Key = NewType("Key", str)


def _positive(value: float, name: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _nonnegative(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


class BucketState(str, Enum):
    OLD = "old"
    COPYING = "copying"
    ELIGIBLE = "eligible"
    NEW = "new"


class DataSource(str, Enum):
    OLD_CACHE = "old_cache"
    NEW_CACHE = "new_cache"
    DONOR_CACHE = "donor_cache"
    DATABASE = "database"
    NONE = "none"


class WorkClass(str, Enum):
    FOREGROUND_CACHE = "foreground_cache"
    FOREGROUND_DATABASE = "foreground_database"
    UNRELATED_FOREGROUND_DATABASE = "unrelated_foreground_database"
    DONOR_READ = "donor_read"
    DESTINATION_WRITE = "destination_write"
    DISCRETIONARY_DATABASE_WARMUP = "discretionary_database_warmup"


class OperationOutcome(str, Enum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUSED = "refused"
    UNSUBMITTED = "unsubmitted"


class ResidencyState(str, Enum):
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    EVICTED = "evicted"
    EXPIRED = "expired"


class PressureState(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    STALE = "stale"
    UNKNOWN = "unknown"


class EventPhase(str, Enum):
    PREPARATION = "preparation"
    PRE_EVENT = "pre_event"
    HANDOVER = "handover"
    POST_HANDOVER = "post_handover"
    TERMINAL = "terminal"


class EventKind(str, Enum):
    ARRIVAL_SCHEDULED = "arrival_scheduled"
    REQUEST_SUBMITTED = "request_submitted"
    REQUEST_COMPLETED = "request_completed"
    REQUEST_FAILED = "request_failed"
    POLICY_ACTION = "policy_action"
    BUCKET_TRANSITION = "bucket_transition"
    MIGRATION_ATTEMPT = "migration_attempt"
    OBSERVATION = "observation"
    ACCOUNTING = "accounting"
    HANDOVER_TERMINAL = "handover_terminal"


_NEXT_STATE = {
    BucketState.OLD: BucketState.COPYING,
    BucketState.COPYING: BucketState.ELIGIBLE,
    BucketState.ELIGIBLE: BucketState.NEW,
}


def validate_bucket_transition(before: BucketState, after: BucketState) -> None:
    """Enforce irreversible OLD -> COPYING -> ELIGIBLE -> NEW transitions."""
    if _NEXT_STATE.get(before) != after:
        raise ValueError(f"invalid bucket transition: {before.value} -> {after.value}")


@dataclass(frozen=True, slots=True)
class RouteCapture:
    """The atomic routing decision captured once by a submitted request."""

    epoch: RoutingEpoch
    bucket: BucketId
    owner: NodeId
    state: BucketState

    def __post_init__(self) -> None:
        if self.epoch < 0 or self.bucket < 0 or not self.owner:
            raise ValueError("route capture requires nonnegative IDs and an owner")


@dataclass(frozen=True, slots=True)
class CacheValue:
    payload: bytes
    absolute_expiry_ns: int | None
    version: str | None = None

    def remaining_ttl_ns(self, now_ns: int) -> int | None:
        if self.absolute_expiry_ns is None:
            return None
        return max(0, self.absolute_expiry_ns - now_ns)


@dataclass(frozen=True, slots=True)
class CacheReadResult:
    source: DataSource
    value: CacheValue | None
    observed_at_ns: int
    latency_ns: int

    def __post_init__(self) -> None:
        if self.source not in {DataSource.OLD_CACHE, DataSource.NEW_CACHE, DataSource.DONOR_CACHE}:
            raise ValueError("cache read source must identify a cache")
        if self.observed_at_ns < 0 or self.latency_ns < 0:
            raise ValueError("cache read timing must be nonnegative")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    attempt_timeout_seconds: float
    backoff_seconds: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be finite and at least one")
        _positive(self.attempt_timeout_seconds, "attempt_timeout_seconds")
        if len(self.backoff_seconds) != self.max_attempts - 1:
            raise ValueError("one finite backoff is required between each attempt")
        for delay in self.backoff_seconds:
            _nonnegative(delay, "backoff")


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    foreground_db_connections: int
    background_db_connections: int
    foreground_cache_connections_per_node: int
    background_cache_connections_per_node: int
    migration_workers: int
    max_inflight_requests: int
    max_coalesced_keys: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value < 1:
                raise ValueError(f"{name} must be at least one")


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    start_ns: int
    end_ns: int
    observed_at_ns: int
    max_age_ns: int

    def __post_init__(self) -> None:
        if not (0 <= self.start_ns < self.end_ns <= self.observed_at_ns):
            raise ValueError("observation window must be closed and causal")
        if self.max_age_ns < 0:
            raise ValueError("max_age_ns must be nonnegative")

    @property
    def age_ns(self) -> int:
        return self.observed_at_ns - self.end_ns

    @property
    def stale(self) -> bool:
        return self.age_ns > self.max_age_ns


@dataclass(frozen=True, slots=True)
class KeyDemand:
    key: Key
    bucket: BucketId
    request_count: int
    object_bytes: int
    last_seen_ns: int

    def __post_init__(self) -> None:
        if not self.key or self.bucket < 0 or self.request_count < 1 or self.object_bytes < 1 or self.last_seen_ns < 0:
            raise ValueError("invalid key-demand entry")


@dataclass(frozen=True, slots=True)
class DemandSnapshot:
    window: ObservationWindow
    entries: tuple[KeyDemand, ...]
    max_keys_per_bucket: int
    overflow_request_count_by_bucket: dict[BucketId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_keys_per_bucket < 1:
            raise ValueError("max_keys_per_bucket must be at least one")
        seen: set[Key] = set()
        counts: dict[BucketId, int] = {}
        for entry in self.entries:
            if entry.last_seen_ns > self.window.end_ns:
                raise ValueError("demand snapshot contains future information")
            if entry.key in seen:
                raise ValueError("demand snapshot keys must be unique")
            seen.add(entry.key)
            counts[entry.bucket] = counts.get(entry.bucket, 0) + 1
            if counts[entry.bucket] > self.max_keys_per_bucket:
                raise ValueError("bounded per-bucket demand metadata exceeded")
        if any(bucket < 0 or count < 0 for bucket, count in self.overflow_request_count_by_bucket.items()):
            raise ValueError("overflow accounting must be nonnegative")


@dataclass(frozen=True, slots=True)
class ResidencyEvidence:
    key: Key
    destination: NodeId
    state: ResidencyState
    observed_at_ns: int
    valid_until_ns: int | None

    def is_warm(self, *, as_of_ns: int, max_observation_age_ns: int) -> bool:
        if self.state is not ResidencyState.CONFIRMED:
            return False
        if as_of_ns < self.observed_at_ns or as_of_ns - self.observed_at_ns > max_observation_age_ns:
            return False
        return self.valid_until_ns is None or as_of_ns < self.valid_until_ns


@dataclass(frozen=True, slots=True)
class CoverageEstimate:
    known_keys: int
    confirmed_warm_keys: int
    observed_requests: int
    confirmed_warm_requests: int
    unknown_requests: int

    def __post_init__(self) -> None:
        values = asdict(self)
        if any(value < 0 for value in values.values()):
            raise ValueError("coverage counts must be nonnegative")
        if self.confirmed_warm_keys > self.known_keys:
            raise ValueError("warm keys cannot exceed known keys")
        if self.confirmed_warm_requests > self.observed_requests:
            raise ValueError("warm demand cannot exceed observed demand")

    @property
    def key_count_coverage(self) -> float:
        return self.confirmed_warm_keys / self.known_keys if self.known_keys else 0.0

    @property
    def warmed_request_coverage(self) -> float:
        denominator = self.observed_requests + self.unknown_requests
        return self.confirmed_warm_requests / denominator if denominator else 0.0


def estimate_coverage(
    demand: DemandSnapshot,
    residency: dict[Key, ResidencyEvidence],
    *,
    bucket: BucketId,
    as_of_ns: int,
    max_residency_age_ns: int,
) -> CoverageEstimate:
    relevant = [entry for entry in demand.entries if entry.bucket == bucket]
    warm = [entry for entry in relevant if entry.key in residency and residency[entry.key].is_warm(
        as_of_ns=as_of_ns, max_observation_age_ns=max_residency_age_ns)]
    return CoverageEstimate(
        known_keys=len(relevant),
        confirmed_warm_keys=len(warm),
        observed_requests=sum(entry.request_count for entry in relevant),
        confirmed_warm_requests=sum(entry.request_count for entry in warm),
        unknown_requests=demand.overflow_request_count_by_bucket.get(bucket, 0),
    )


@dataclass(frozen=True, slots=True)
class ComponentPressure:
    state: PressureState
    observed_at_ns: int
    reason: str

    def __post_init__(self) -> None:
        if self.observed_at_ns < 0 or not self.reason:
            raise ValueError("pressure requires timing and reason")


@dataclass(frozen=True, slots=True)
class ControllerObservation:
    observed_at_ns: int
    demand: DemandSnapshot
    foreground_db_rate_upper: float
    db_pressure: ComponentPressure
    donor_pressure: ComponentPressure
    destination_pressure: ComponentPressure
    bucket_coverage: dict[BucketId, CoverageEstimate]

    def __post_init__(self) -> None:
        if self.demand.window.observed_at_ns != self.observed_at_ns:
            raise ValueError("controller observation must use one causal as-of time")
        _nonnegative(self.foreground_db_rate_upper, "foreground_db_rate_upper")
        if any(p.observed_at_ns > self.observed_at_ns for p in
               (self.db_pressure, self.donor_pressure, self.destination_pressure)):
            raise ValueError("controller observation contains a future pressure sample")


@dataclass(frozen=True, slots=True)
class TransferBudget:
    donor_operations: int
    donor_bytes: int
    background_db_operations: int
    destination_write_operations: int
    valid_for_ns: int

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise ValueError("budgets must be nonnegative")
        if self.valid_for_ns < 1:
            raise ValueError("budget validity must be finite")


@dataclass(frozen=True, slots=True)
class ControllerAction:
    decided_at_ns: int
    budget: TransferBudget
    admit_buckets: tuple[BucketId, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.decided_at_ns < 0 or len(set(self.admit_buckets)) != len(self.admit_buckets):
            raise ValueError("invalid controller action")
        if not self.reason_codes:
            raise ValueError("every action, including no-progress, needs a reason")


@dataclass(frozen=True, slots=True)
class MigrationTask:
    task_id: str
    key: Key
    bucket: BucketId
    source_owner: NodeId
    destination_owner: NodeId
    source: DataSource
    work_class: WorkClass
    timeout_seconds: float
    retry: RetryPolicy
    original_absolute_expiry_ns: int | None

    def __post_init__(self) -> None:
        if not self.task_id or not self.source_owner or not self.destination_owner:
            raise ValueError("migration action requires explicit owners")
        if self.source not in {DataSource.DONOR_CACHE, DataSource.DATABASE}:
            raise ValueError("migration source must be donor cache or database")
        expected = (WorkClass.DONOR_READ if self.source is DataSource.DONOR_CACHE
                    else WorkClass.DISCRETIONARY_DATABASE_WARMUP)
        if self.work_class is not expected:
            raise ValueError("migration source and accounting class disagree")
        _positive(self.timeout_seconds, "timeout_seconds")


@dataclass(frozen=True, slots=True)
class MigrationAttemptRecord:
    schema_version: int
    run_id: str
    task_id: str
    attempt: int
    source: DataSource
    source_owner: NodeId
    destination_owner: NodeId
    timeout_seconds: float
    work_class: WorkClass
    outcome: OperationOutcome
    issued_operations: int
    issued_bytes: int
    started_ns: int
    completed_ns: int
    reason: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.run_id or not self.task_id or not self.reason:
            raise ValueError("invalid migration record identity")
        if self.attempt < 1 or self.issued_operations != 1 or self.issued_bytes < 0:
            raise ValueError("every issued retry is charged as an operation")
        if not (0 <= self.started_ns <= self.completed_ns):
            raise ValueError("invalid migration chronology")
        _positive(self.timeout_seconds, "timeout_seconds")


@dataclass(frozen=True, slots=True)
class RequestRecord:
    schema_version: int
    run_id: str
    request_id: str
    scheduled_arrival_ns: int
    submitted_ns: int | None
    completed_ns: int | None
    timeout_seconds: float
    outcome: OperationOutcome
    route: RouteCapture | None
    source: DataSource
    work_class: WorkClass | None
    cache_attempts: int
    database_attempts: int
    coalesced_to_request_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.run_id or not self.request_id or not self.reason:
            raise ValueError("invalid request identity")
        if self.scheduled_arrival_ns < 0 or self.cache_attempts < 0 or self.database_attempts < 0:
            raise ValueError("invalid request accounting")
        _positive(self.timeout_seconds, "timeout_seconds")
        if self.outcome is OperationOutcome.UNSUBMITTED:
            if self.submitted_ns is not None or self.completed_ns is not None or self.route is not None:
                raise ValueError("unsubmitted requests cannot have submission, completion, or captured routing")
            if self.source is not DataSource.NONE or self.work_class is not None:
                raise ValueError("unsubmitted requests must explicitly have no source/accounting class")
            return
        if self.submitted_ns is None or self.route is None:
            raise ValueError("every submitted request captures an epoch and owner")
        if self.submitted_ns < self.scheduled_arrival_ns:
            raise ValueError("submission cannot precede scheduled arrival")
        if self.completed_ns is not None and self.completed_ns < self.submitted_ns:
            raise ValueError("completion cannot precede submission")
        if self.source is DataSource.NONE and self.outcome is OperationOutcome.COMPLETED:
            raise ValueError("completed request needs an explicit data source")
        if self.database_attempts and self.work_class is not WorkClass.FOREGROUND_DATABASE:
            raise ValueError("foreground database work must be charged explicitly")
        if self.outcome in {OperationOutcome.COMPLETED, OperationOutcome.TIMED_OUT,
                            OperationOutcome.FAILED, OperationOutcome.CANCELLED,
                            OperationOutcome.REFUSED} and self.completed_ns is None:
            raise ValueError("terminal request outcome needs a completion/accounting time")

    @property
    def end_to_end_latency_ns(self) -> int | None:
        return None if self.completed_ns is None else self.completed_ns - self.scheduled_arrival_ns


@dataclass(frozen=True, slots=True)
class EventRecord:
    schema_version: int
    run_id: str
    utc_timestamp: str
    monotonic_elapsed_ns: int
    phase: EventPhase
    routing_epoch: RoutingEpoch
    kind: EventKind
    bucket: BucketId | None
    policy_action: str | None
    observed_pressure: dict[str, str]
    reason: str
    accounting: dict[str, int]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.run_id or not self.reason:
            raise ValueError("invalid event identity")
        parsed = datetime.fromisoformat(self.utc_timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("event timestamp must be UTC and include its offset")
        if self.monotonic_elapsed_ns < 0 or self.routing_epoch < 0:
            raise ValueError("event timing and epoch must be nonnegative")
        if any(value < 0 for value in self.accounting.values()):
            raise ValueError("event accounting must be nonnegative")


def json_record(value: Any) -> dict[str, Any]:
    """Convert a contract dataclass into a JSON-compatible dictionary."""
    def convert(item: Any) -> Any:
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, bytes):
            raise TypeError("raw payload bytes are not permitted in metric records")
        if isinstance(item, dict):
            return {str(convert(key)): convert(val) for key, val in item.items()}
        if isinstance(item, (tuple, list)):
            return [convert(part) for part in item]
        return item
    return convert(asdict(value))
