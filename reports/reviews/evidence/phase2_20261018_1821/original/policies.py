"""Executable policy contracts and pure admission arithmetic for Phase 2."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from .contracts import BucketId


class PolicyRole(str, Enum):
    EXPERIMENTAL_CONTROL = "experimental_control"
    CANDIDATE_POLICY = "candidate_policy"


class WarmupControl(str, Enum):
    NONE = "none"
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class TrafficControl(str, Enum):
    IMMEDIATE = "immediate"
    AFTER_MIGRATION = "after_migration"
    FIXED_GRADUAL = "fixed_gradual"
    ADAPTIVE = "adaptive"


@dataclass(frozen=True, slots=True)
class PolicyDefinition:
    name: str
    role: PolicyRole
    warmup_control: WarmupControl
    traffic_control: TrafficControl
    donor_first: bool
    demand_ordering: str
    admission_rule: str
    terminal_rule: str

    def __post_init__(self) -> None:
        if not all((self.name, self.demand_ordering, self.admission_rule, self.terminal_rule)):
            raise ValueError("policy definition is incomplete")


def policy_catalog() -> dict[str, PolicyDefinition]:
    """Return the seven required, explicitly classified policy contracts."""
    shared_terminal = ("all affected buckets are NEW and intended traffic is observed for the "
                       "configured stability interval; otherwise fail at the finite deadline")
    definitions = (
        PolicyDefinition(
            "immediate_cutover", PolicyRole.EXPERIMENTAL_CONTROL,
            WarmupControl.NONE, TrafficControl.IMMEDIATE, False, "none",
            "at expansion trigger atomically admit every affected bucket in one epoch",
            shared_terminal),
        PolicyDefinition(
            "migration_before_cutover", PolicyRole.EXPERIMENTAL_CONTROL,
            WarmupControl.FIXED, TrafficControl.AFTER_MIGRATION, True, "configured shared ordering",
            "admit all affected buckets only after the finite migration pass terminates",
            shared_terminal),
        PolicyDefinition(
            "adaptive_budget_migration_before_cutover", PolicyRole.EXPERIMENTAL_CONTROL,
            WarmupControl.ADAPTIVE, TrafficControl.AFTER_MIGRATION, True, "configured shared ordering",
            "adapt migration budgets causally; admit all only after the finite pass terminates",
            shared_terminal),
        PolicyDefinition(
            "fixed_gradual_handover", PolicyRole.EXPERIMENTAL_CONTROL,
            WarmupControl.FIXED, TrafficControl.FIXED_GRADUAL, True, "configured shared ordering",
            "use pilot-selected fixed budgets and fixed bucket admissions per interval",
            shared_terminal),
        PolicyDefinition(
            "warmup_only_adaptation", PolicyRole.EXPERIMENTAL_CONTROL,
            WarmupControl.ADAPTIVE, TrafficControl.FIXED_GRADUAL, True, "configured shared ordering",
            "adapt transfer/prefetch budgets; use the same fixed traffic schedule",
            shared_terminal),
        PolicyDefinition(
            "traffic_only_adaptation", PolicyRole.EXPERIMENTAL_CONTROL,
            WarmupControl.FIXED, TrafficControl.ADAPTIVE, True, "configured shared ordering",
            "keep warming fixed; causally admit only when incremental misses fit allowance",
            shared_terminal),
        PolicyDefinition(
            "joint_control", PolicyRole.CANDIDATE_POLICY,
            WarmupControl.ADAPTIVE, TrafficControl.ADAPTIVE, True, "configured shared ordering",
            "jointly charge planned DB warming and incremental misses to one remaining allowance",
            shared_terminal),
    )
    return {definition.name: definition for definition in definitions}


def incremental_foreground_db_rate(
    candidate_request_rate_upper: float,
    warmed_request_coverage_lower: float,
    unobserved_miss_reserve_rate: float,
) -> float:
    """Estimate only *new* misses from a proposed admission.

    Existing foreground DB demand is deliberately absent: callers add this result
    once to their already-inclusive foreground upper bound.
    """
    for value, name in ((candidate_request_rate_upper, "candidate_request_rate_upper"),
                        (unobserved_miss_reserve_rate, "unobserved_miss_reserve_rate")):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if not math.isfinite(warmed_request_coverage_lower) or not 0 <= warmed_request_coverage_lower <= 1:
        raise ValueError("coverage lower bound must be in [0, 1]")
    return candidate_request_rate_upper * (1 - warmed_request_coverage_lower) + unobserved_miss_reserve_rate


def remaining_db_allowance(
    safe_rate: float,
    safety_reserve_rate: float,
    foreground_db_rate_upper: float,
    planned_background_db_rate: float,
) -> float:
    """Compute allowance after charging current foreground demand and planned warming once."""
    for value in (safe_rate, safety_reserve_rate, foreground_db_rate_upper, planned_background_db_rate):
        if not math.isfinite(value) or value < 0:
            raise ValueError("rate inputs must be finite and nonnegative")
    return max(0.0, safe_rate - safety_reserve_rate - foreground_db_rate_upper - planned_background_db_rate)


def admit_in_order(
    candidates: tuple[tuple[BucketId, float], ...],
    *,
    allowance: float,
    max_admissions: int,
) -> tuple[BucketId, ...]:
    """Sequentially charge proposed incremental load; never reuse the same allowance."""
    if not math.isfinite(allowance) or allowance < 0 or max_admissions < 0:
        raise ValueError("invalid admission bound")
    admitted: list[BucketId] = []
    used = 0.0
    for bucket, incremental_rate in candidates:
        if not math.isfinite(incremental_rate) or incremental_rate < 0:
            raise ValueError("incremental candidate rate must be finite and nonnegative")
        if len(admitted) >= max_admissions:
            break
        if used + incremental_rate <= allowance:
            admitted.append(bucket)
            used += incremental_rate
    return tuple(admitted)
