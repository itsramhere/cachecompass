"""Phase 2 data contracts for the single-router scale-out experiment.

This module deliberately contains no network or request-path implementation.  It
defines the values that later phases must exchange and validates chronology,
boundedness, ownership capture, retry charging, and causal observations.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Any, NewType
from types import MappingProxyType

BucketId = NewType("BucketId", int)
RoutingEpoch = NewType("RoutingEpoch", int)
NodeId = NewType("NodeId", str)
Key = NewType("Key", str)


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")


def _nonnegative(value: float, name: str) -> None:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")


def _integer(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _freeze(instance: Any, *names: str) -> None:
    def freeze(value: Any) -> Any:
        if isinstance(value, Mapping):
            return MappingProxyType({key: freeze(part) for key, part in value.items()})
        if isinstance(value, (tuple, list)):
            return tuple(freeze(part) for part in value)
        return value
    for name in names:
        object.__setattr__(instance, name, freeze(getattr(instance, name)))


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
    OBSERVATION_CACHE = "observation_cache"
    OBSERVATION_DATABASE = "observation_database"
    FUNCTIONAL_DIAGNOSTIC_CACHE = "functional_diagnostic_cache"


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
    if not isinstance(before, BucketState) or not isinstance(after, BucketState):
        raise ValueError("bucket transitions require state enums")
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
        _integer(self.epoch, "epoch")
        _integer(self.bucket, "bucket")
        if not self.owner or not isinstance(self.state, BucketState):
            raise ValueError("route capture requires nonnegative IDs and an owner")


@dataclass(frozen=True, slots=True)
class BucketAdvance:
    bucket: BucketId
    expected: BucketState
    path: tuple[BucketState, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", tuple(self.path))
        _integer(self.bucket, "bucket")
        if not self.path:
            raise ValueError("empty transition path")
        before = self.expected
        for after in self.path:
            validate_bucket_transition(before, after)
            before = after


@dataclass(frozen=True, slots=True)
class CacheValue:
    payload: bytes
    absolute_expiry_ns: int | None
    version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, bytes):
            raise ValueError("cache payload must be bytes")
        if self.absolute_expiry_ns is not None:
            _integer(self.absolute_expiry_ns, "absolute_expiry_ns")

    def remaining_ttl_ns(self, now_ns: int) -> int | None:
        if self.absolute_expiry_ns is None:
            return None
        return max(0, self.absolute_expiry_ns - now_ns)


@dataclass(frozen=True, slots=True)
class CacheWriteReceipt:
    """Conservative expiry for positive residency evidence after acknowledged IO."""
    valid_until_ns: int | None

    def __post_init__(self) -> None:
        if self.valid_until_ns is not None:
            _integer(self.valid_until_ns, 'valid_until_ns')


@dataclass(frozen=True, slots=True)
class CacheReadResult:
    source: DataSource
    value: CacheValue | None
    observed_at_ns: int
    latency_ns: int

    def __post_init__(self) -> None:
        if self.source not in {DataSource.OLD_CACHE, DataSource.NEW_CACHE, DataSource.DONOR_CACHE}:
            raise ValueError("cache read source must identify a cache")
        _integer(self.observed_at_ns, "observed_at_ns")
        _integer(self.latency_ns, "latency_ns")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    attempt_timeout_seconds: float
    backoff_seconds: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "backoff_seconds", tuple(self.backoff_seconds))
        _integer(self.max_attempts, "max_attempts", 1)
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
    max_pending_migration_tasks: int
    max_pending_metric_records: int
    max_buffered_payload_bytes: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _integer(value, name, 1)


@dataclass(frozen=True, slots=True)
class ObservationWindow:
    start_ns: int
    end_ns: int
    observed_at_ns: int
    max_age_ns: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _integer(value, name)
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
        for name in ("bucket", "last_seen_ns", "request_count", "object_bytes"):
            _integer(getattr(self, name), name, 1 if name in {"request_count", "object_bytes"} else 0)
        if not self.key or self.bucket < 0 or self.request_count < 1 or self.object_bytes < 1 or self.last_seen_ns < 0:
            raise ValueError("invalid key-demand entry")


@dataclass(frozen=True, slots=True)
class DemandSnapshot:
    window: ObservationWindow
    entries: tuple[KeyDemand, ...]
    max_keys_per_bucket: int
    max_total_keys: int
    max_buckets: int
    overflow_request_count_by_bucket: Mapping[BucketId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        for name in ("max_keys_per_bucket", "max_total_keys", "max_buckets"):
            _integer(getattr(self, name), name, 1)
        if len(self.entries) > self.max_total_keys:
            raise ValueError("total demand bound exceeded")
        seen: set[Key] = set()
        counts: dict[BucketId, int] = {}
        for entry in self.entries:
            if not self.window.start_ns <= entry.last_seen_ns < self.window.end_ns:
                raise ValueError("demand entry lies outside the half-open observation window")
            if entry.bucket >= self.max_buckets:
                raise ValueError("demand bucket exceeds configured bound")
            if entry.key in seen:
                raise ValueError("demand snapshot keys must be unique")
            seen.add(entry.key)
            counts[entry.bucket] = counts.get(entry.bucket, 0) + 1
            if counts[entry.bucket] > self.max_keys_per_bucket:
                raise ValueError("bounded per-bucket demand metadata exceeded")
        for bucket, count in self.overflow_request_count_by_bucket.items():
            _integer(bucket, "overflow bucket")
            _integer(count, "overflow count")
            if bucket >= self.max_buckets:
                raise ValueError("overflow bucket exceeds configured bound")
        _freeze(self, "overflow_request_count_by_bucket")


@dataclass(frozen=True, slots=True)
class ResidencyEvidence:
    key: Key
    destination: NodeId
    state: ResidencyState
    observed_at_ns: int
    valid_until_ns: int | None

    def __post_init__(self) -> None:
        _integer(self.observed_at_ns, "observed_at_ns")
        if not self.key or not self.destination or not isinstance(self.state, ResidencyState):
            raise ValueError("invalid residency identity/state")
        if self.valid_until_ns is not None:
            _integer(self.valid_until_ns, "valid_until_ns")

    def is_warm(self, *, as_of_ns: int, max_observation_age_ns: int) -> bool:
        _integer(as_of_ns, "as_of_ns")
        _integer(max_observation_age_ns, "max_observation_age_ns")
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
    as_of_ns: int
    destination: NodeId
    window_start_ns: int
    window_end_ns: int

    def __post_init__(self) -> None:
        for name in ("known_keys", "confirmed_warm_keys", "observed_requests", "confirmed_warm_requests",
                     "unknown_requests", "as_of_ns", "window_start_ns", "window_end_ns"):
            _integer(getattr(self, name), name)
        if not self.destination or not self.window_start_ns < self.window_end_ns <= self.as_of_ns:
            raise ValueError("coverage requires destination and causal window provenance")
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
    residency: Mapping[Key, ResidencyEvidence],
    *,
    bucket: BucketId,
    as_of_ns: int,
    max_residency_age_ns: int,
    registered_keys: tuple[Key, ...],
    destination: NodeId,
) -> CoverageEstimate:
    _integer(as_of_ns, "as_of_ns")
    _integer(max_residency_age_ns, "max_residency_age_ns")
    _integer(bucket, "bucket")
    if bucket >= demand.max_buckets or len(registered_keys) > demand.max_keys_per_bucket:
        raise ValueError("coverage registry exceeds configured bucket bound")
    if as_of_ns < demand.window.observed_at_ns:
        raise ValueError("coverage cannot precede its demand snapshot")
    if not destination or len(set(registered_keys)) != len(registered_keys) or any(not k for k in registered_keys):
        raise ValueError("coverage requires a unique bucket registry and destination")
    relevant = [entry for entry in demand.entries if entry.bucket == bucket]
    if not {entry.key for entry in relevant} <= set(registered_keys):
        raise ValueError("demand keys disagree with the bucket registry")
    stale = as_of_ns - demand.window.end_ns > demand.window.max_age_ns
    warm_keys = {key for key in registered_keys if not stale and key in residency
                 and residency[key].key == key and residency[key].destination == destination
                 and residency[key].is_warm(as_of_ns=as_of_ns, max_observation_age_ns=max_residency_age_ns)}
    warm = [entry for entry in relevant if entry.key in warm_keys]
    return CoverageEstimate(
        known_keys=len(registered_keys),
        confirmed_warm_keys=len(warm_keys),
        observed_requests=sum(entry.request_count for entry in relevant),
        confirmed_warm_requests=sum(entry.request_count for entry in warm),
        unknown_requests=demand.overflow_request_count_by_bucket.get(bucket, 0),
        as_of_ns=as_of_ns, destination=destination,
        window_start_ns=demand.window.start_ns, window_end_ns=demand.window.end_ns,
    )


@dataclass(frozen=True, slots=True)
class ComponentPressure:
    state: PressureState
    observed_at_ns: int
    reason: str

    def __post_init__(self) -> None:
        _integer(self.observed_at_ns, "observed_at_ns")
        if not self.reason or not isinstance(self.state, PressureState):
            raise ValueError("pressure requires timing and reason")

    def effective_state(self, *, as_of_ns: int, max_age_ns: int) -> PressureState:
        _integer(as_of_ns, "as_of_ns")
        _integer(max_age_ns, "max_age_ns")
        if self.observed_at_ns > as_of_ns:
            raise ValueError("future pressure sample")
        return PressureState.STALE if as_of_ns - self.observed_at_ns > max_age_ns else self.state


@dataclass(frozen=True, slots=True)
class ControllerObservation:
    observed_at_ns: int
    demand: DemandSnapshot
    foreground_db_rate_upper: float
    db_pressure: ComponentPressure
    donor_pressure: ComponentPressure
    destination_pressure: ComponentPressure
    bucket_coverage: Mapping[BucketId, CoverageEstimate]
    bucket_states: Mapping[BucketId, BucketState]
    routing_epoch: RoutingEpoch
    candidate_request_rate_upper: Mapping[BucketId, float]
    uncertain_miss_reserve_rate: Mapping[BucketId, float]
    pending_admission_db_rate_upper: float
    foreground_db_observed_at_ns: int
    max_signal_age_ns: int
    destination_owner: NodeId
    old_owner_db_rate_lower: Mapping[BucketId, float]
    observation_db_rate_upper: float
    coverage_valid_until_ns: Mapping[BucketId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("observed_at_ns", "routing_epoch", "foreground_db_observed_at_ns", "max_signal_age_ns"):
            _integer(getattr(self, name), name)
        if self.foreground_db_observed_at_ns > self.observed_at_ns:
            raise ValueError("future foreground DB estimate")
        if self.demand.window.observed_at_ns != self.observed_at_ns:
            raise ValueError("controller observation must use one causal as-of time")
        _nonnegative(self.foreground_db_rate_upper, "foreground_db_rate_upper")
        _nonnegative(self.observation_db_rate_upper, "observation_db_rate_upper")
        if any(p.observed_at_ns > self.observed_at_ns for p in
               (self.db_pressure, self.donor_pressure, self.destination_pressure)):
            raise ValueError("controller observation contains a future pressure sample")
        _nonnegative(self.pending_admission_db_rate_upper, "pending_admission_db_rate_upper")
        for bucket, state in self.bucket_states.items():
            _integer(bucket, "bucket")
            if bucket >= self.demand.max_buckets or not isinstance(state, BucketState):
                raise ValueError("invalid bucket state")
        if not self.destination_owner:
            raise ValueError("observation requires destination identity")
        for name in ("bucket_coverage", "candidate_request_rate_upper", "uncertain_miss_reserve_rate", "old_owner_db_rate_lower"):
            if set(getattr(self, name)) != set(self.bucket_states):
                raise ValueError("per-bucket observation fields must describe the same snapshot")
        for rate in (*self.candidate_request_rate_upper.values(), *self.uncertain_miss_reserve_rate.values(),
                     *self.old_owner_db_rate_lower.values()):
            _nonnegative(rate, "candidate rate/reserve")
        for bucket, coverage in self.bucket_coverage.items():
            if (coverage.as_of_ns != self.observed_at_ns or coverage.destination != self.destination_owner
                or coverage.window_start_ns != self.demand.window.start_ns
                or coverage.window_end_ns != self.demand.window.end_ns
                or coverage.known_keys > self.demand.max_keys_per_bucket
                or coverage.observed_requests != sum(e.request_count for e in self.demand.entries if e.bucket == bucket)
                or coverage.unknown_requests != self.demand.overflow_request_count_by_bucket.get(bucket, 0)):
                raise ValueError("coverage provenance/counts disagree with observation")
        if sum(self.old_owner_db_rate_lower.values()) > self.foreground_db_rate_upper:
            raise ValueError("displaced old-owner lower rates cannot exceed existing foreground demand")
        if self.coverage_valid_until_ns and set(self.coverage_valid_until_ns) != set(self.bucket_states):
            raise ValueError("coverage validity must describe every affected bucket")
        for bound in self.coverage_valid_until_ns.values():
            _integer(bound,"coverage validity")
        _freeze(self, "bucket_coverage", "bucket_states", "candidate_request_rate_upper",
                "uncertain_miss_reserve_rate", "old_owner_db_rate_lower", "coverage_valid_until_ns")

    @property
    def admissions_safe(self) -> bool:
        return self.admissions_safe_at(self.observed_at_ns)

    def admissions_safe_at(self, decided_at_ns: int) -> bool:
        _integer(decided_at_ns, "decided_at_ns")
        if decided_at_ns < self.observed_at_ns:
            raise ValueError("decision precedes its observation")
        return (decided_at_ns - self.demand.window.end_ns <= self.demand.window.max_age_ns
                and decided_at_ns - self.foreground_db_observed_at_ns <= self.max_signal_age_ns
                and all(p.effective_state(as_of_ns=decided_at_ns, max_age_ns=self.max_signal_age_ns)
                        is PressureState.SAFE for p in
                        (self.db_pressure, self.donor_pressure, self.destination_pressure)))


@dataclass(frozen=True, slots=True)
class TransferBudget:
    donor_operations: int
    donor_bytes: int
    background_db_operations: int
    destination_write_operations: int
    valid_for_ns: int
    destination_write_bytes: int

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _integer(value, name)
        if self.valid_for_ns < 1:
            raise ValueError("budget validity must be finite")


@dataclass(frozen=True, slots=True)
class ControllerAction:
    decided_at_ns: int
    budget: TransferBudget
    admit_buckets: tuple[BucketId, ...]
    reason_codes: tuple[str, ...]
    expected_routing_epoch: RoutingEpoch
    observation_as_of_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "admit_buckets", tuple(self.admit_buckets))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        for name in ("decided_at_ns", "expected_routing_epoch", "observation_as_of_ns"):
            _integer(getattr(self, name), name)
        for bucket in self.admit_buckets:
            _integer(bucket, "admission bucket")
        if self.observation_as_of_ns > self.decided_at_ns or len(set(self.admit_buckets)) != len(self.admit_buckets):
            raise ValueError("invalid controller action")
        if not self.reason_codes or any(not reason.strip() for reason in self.reason_codes):
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
    deadline_ns: int
    parent_task_id: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id or not self.source_owner or not self.destination_owner:
            raise ValueError("migration action requires explicit owners")
        if not self.key:
            raise ValueError("migration requires key identity")
        _integer(self.bucket, "bucket")
        _integer(self.deadline_ns, "deadline_ns", 1)
        if self.original_absolute_expiry_ns is not None:
            _integer(self.original_absolute_expiry_ns, "original_absolute_expiry_ns")
        expected = {DataSource.DONOR_CACHE: WorkClass.DONOR_READ,
                    DataSource.DATABASE: WorkClass.DISCRETIONARY_DATABASE_WARMUP,
                    DataSource.NEW_CACHE: WorkClass.DESTINATION_WRITE}.get(self.source)
        if expected is None or self.work_class is not expected:
            raise ValueError("migration source and accounting class disagree")
        if self.source is DataSource.NEW_CACHE and (not self.parent_task_id or self.source_owner != self.destination_owner):
            raise ValueError("destination writes require a parent source task and destination client identity")
        if self.parent_task_id == self.task_id:
            raise ValueError("migration task cannot depend on itself")
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
    issued_bytes: int | None
    started_ns: int
    completed_ns: int
    reason: str
    reserved_bytes: int = 0

    def __post_init__(self) -> None:
        _integer(self.schema_version, "schema_version", 1)
        if self.schema_version != 1 or not self.run_id or not self.task_id or not self.reason:
            raise ValueError("invalid migration record identity")
        for name in ("attempt", "issued_operations", "started_ns", "completed_ns", "reserved_bytes"):
            _integer(getattr(self, name), name, 1 if name in {"attempt", "issued_operations"} else 0)
        if self.issued_bytes is not None:
            _integer(self.issued_bytes, "issued_bytes")
        if self.issued_operations != 1:
            raise ValueError("every issued retry is charged as an operation")
        if not (0 <= self.started_ns <= self.completed_ns):
            raise ValueError("invalid migration chronology")
        _positive(self.timeout_seconds, "timeout_seconds")
        expected = {DataSource.DONOR_CACHE: WorkClass.DONOR_READ,
                    DataSource.DATABASE: WorkClass.DISCRETIONARY_DATABASE_WARMUP,
                    DataSource.NEW_CACHE: WorkClass.DESTINATION_WRITE}.get(self.source)
        if expected is None or self.work_class is not expected or not self.source_owner or not self.destination_owner:
            raise ValueError("invalid migration source/owner/accounting")
        if self.source is DataSource.NEW_CACHE and self.source_owner != self.destination_owner:
            raise ValueError("destination write client must be the destination owner")
        if self.outcome not in {OperationOutcome.COMPLETED, OperationOutcome.FAILED,
                                OperationOutcome.TIMED_OUT, OperationOutcome.CANCELLED}:
            raise ValueError("unissued work is not an issued migration attempt")
        if self.issued_bytes is not None and self.issued_bytes > self.reserved_bytes:
            raise ValueError("issued bytes exceed reserved bound")


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
    key: Key
    cache_write_attempts: int = 0

    def __post_init__(self) -> None:
        _integer(self.schema_version, "schema_version", 1)
        if self.schema_version != 1 or not self.run_id or not self.request_id or not self.reason or not self.key:
            raise ValueError("invalid request identity")
        for name in ("scheduled_arrival_ns", "cache_attempts", "database_attempts", "cache_write_attempts"):
            _integer(getattr(self, name), name)
        if not isinstance(self.outcome, OperationOutcome):
            raise ValueError("invalid request outcome")
        _positive(self.timeout_seconds, "timeout_seconds")
        if self.outcome is OperationOutcome.UNSUBMITTED:
            if self.submitted_ns is not None or self.completed_ns is not None or self.route is not None:
                raise ValueError("unsubmitted requests cannot have submission, completion, or captured routing")
            if self.source is not DataSource.NONE or self.work_class is not None:
                raise ValueError("unsubmitted requests must explicitly have no source/accounting class")
            if self.cache_attempts or self.database_attempts or self.cache_write_attempts or self.coalesced_to_request_id is not None:
                raise ValueError("unsubmitted requests cannot have issued/coalesced work")
            return
        if self.submitted_ns is None or self.route is None:
            raise ValueError("every submitted request captures an epoch and owner")
        if self.submitted_ns < self.scheduled_arrival_ns:
            raise ValueError("submission cannot precede scheduled arrival")
        _integer(self.submitted_ns, "submitted_ns")
        if self.completed_ns is not None:
            _integer(self.completed_ns, "completed_ns")
        if self.completed_ns is not None and self.completed_ns < self.submitted_ns:
            raise ValueError("completion cannot precede submission")
        if self.source is DataSource.NONE and self.outcome is OperationOutcome.COMPLETED:
            raise ValueError("completed request needs an explicit data source")
        if self.source not in {DataSource.OLD_CACHE, DataSource.NEW_CACHE, DataSource.DATABASE, DataSource.NONE}:
            raise ValueError("foreground donor fallback is forbidden")
        if self.source in {DataSource.OLD_CACHE, DataSource.NEW_CACHE}:
            expected = DataSource.NEW_CACHE if self.route.state is BucketState.NEW else DataSource.OLD_CACHE
            if self.source is not expected or not self.cache_attempts:
                raise ValueError("cache source disagrees with captured owner or attempts")
            if self.outcome is OperationOutcome.COMPLETED and (self.database_attempts or self.coalesced_to_request_id or self.cache_write_attempts):
                raise ValueError("a DB fill cannot be reported as a cache-hit success")
        if self.work_class not in {None, WorkClass.FOREGROUND_CACHE, WorkClass.FOREGROUND_DATABASE}:
            raise ValueError("invalid foreground work class")
        if (self.cache_attempts or self.cache_write_attempts) and self.work_class is None:
            raise ValueError("issued cache work requires accounting class")
        if self.coalesced_to_request_id is not None:
            if not self.coalesced_to_request_id or self.coalesced_to_request_id == self.request_id or self.database_attempts or self.cache_write_attempts:
                raise ValueError("followers cannot own DB work or reference themselves")
        if self.source is DataSource.DATABASE and not (self.database_attempts or self.coalesced_to_request_id):
            raise ValueError("database result requires an issued or linked shared read")
        if self.database_attempts and self.work_class is not WorkClass.FOREGROUND_DATABASE:
            raise ValueError("foreground database work must be charged explicitly")
        if self.work_class is WorkClass.FOREGROUND_DATABASE and not self.database_attempts:
            raise ValueError("foreground DB summary requires owned DB attempts")
        if self.source is DataSource.NONE and (self.cache_attempts or self.database_attempts or self.cache_write_attempts):
            raise ValueError("issued work cannot have no attempted source")
        if self.outcome is OperationOutcome.REFUSED and (self.source is not DataSource.NONE or self.coalesced_to_request_id):
            raise ValueError("inflight-limit refusals issue no source work")
        if self.outcome in {OperationOutcome.COMPLETED, OperationOutcome.TIMED_OUT,
                            OperationOutcome.FAILED, OperationOutcome.CANCELLED,
                            OperationOutcome.REFUSED} and self.completed_ns is None:
            raise ValueError("terminal request outcome needs a completion/accounting time")
        if self.outcome is OperationOutcome.COMPLETED and self.completed_ns > self.scheduled_arrival_ns + self.timeout_seconds * 1e9:
            raise ValueError("success cannot occur after the absolute foreground deadline")

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
    observed_pressure: Mapping[str, str]
    reason: str
    accounting: Mapping[str, int]
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _integer(self.schema_version, "schema_version", 1)
        if self.schema_version != 1 or not self.run_id or not self.reason:
            raise ValueError("invalid event identity")
        parsed = datetime.fromisoformat(self.utc_timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError("event timestamp must be UTC and include its offset")
        _integer(self.monotonic_elapsed_ns, "monotonic_elapsed_ns")
        _integer(self.routing_epoch, "routing_epoch")
        if self.bucket is not None:
            _integer(self.bucket, "bucket")
        for name, value in self.accounting.items():
            _integer(value, name)
        _freeze(self, "observed_pressure", "accounting", "detail")
        if not isinstance(self.phase, EventPhase) or not isinstance(self.kind, EventKind):
            raise ValueError("invalid event phase/kind")


def json_record(value: Any) -> dict[str, Any]:
    """Convert a contract dataclass into a JSON-compatible dictionary."""
    def convert(item: Any) -> Any:
        if is_dataclass(item):
            return {part.name: convert(getattr(item, part.name)) for part in fields(item)}
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, bytes):
            raise TypeError("raw payload bytes are not permitted in metric records")
        if isinstance(item, Mapping):
            return {str(convert(key)): convert(val) for key, val in item.items()}
        if isinstance(item, (tuple, list)):
            return [convert(part) for part in item]
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("nonfinite telemetry value")
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        raise TypeError("unsupported metric value")
    return convert(value)
