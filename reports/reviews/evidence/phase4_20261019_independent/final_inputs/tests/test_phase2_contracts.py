from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cache_scaleout.contracts import (
    BucketId, BucketState, ComponentPressure, ControllerObservation, DataSource,
    DemandSnapshot, Key, KeyDemand, NodeId, ObservationWindow, OperationOutcome,
    PressureState, RequestRecord, ResidencyEvidence, ResidencyState, RetryPolicy,
    RouteCapture, RoutingEpoch, WorkClass, estimate_coverage,
    validate_bucket_transition,
)
from cache_scaleout.policies import (
    PolicyRole, admit_in_order, incremental_foreground_db_rate, policy_catalog,
    remaining_db_allowance,
)
from cache_scaleout.interfaces import (
    CacheClient, Controller, DatabaseClient, KeyDemandTracker, MetricsSink,
    MigrationScheduler, OwnershipMap,
)


class Phase2ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = ObservationWindow(start_ns=100, end_ns=200, observed_at_ns=210, max_age_ns=20)

    def test_bucket_transitions_are_irreversible_and_sequential(self) -> None:
        validate_bucket_transition(BucketState.OLD, BucketState.COPYING)
        validate_bucket_transition(BucketState.COPYING, BucketState.ELIGIBLE)
        validate_bucket_transition(BucketState.ELIGIBLE, BucketState.NEW)
        with self.assertRaises(ValueError):
            validate_bucket_transition(BucketState.OLD, BucketState.NEW)
        with self.assertRaises(ValueError):
            validate_bucket_transition(BucketState.NEW, BucketState.ELIGIBLE)

    def test_observation_window_rejects_future_information(self) -> None:
        with self.assertRaises(ValueError):
            ObservationWindow(start_ns=100, end_ns=220, observed_at_ns=210, max_age_ns=20)
        self.assertFalse(self.window.stale)
        stale = ObservationWindow(start_ns=100, end_ns=200, observed_at_ns=221, max_age_ns=20)
        self.assertTrue(stale.stale)

    def test_demand_snapshot_is_bounded_per_bucket_and_causal(self) -> None:
        first = KeyDemand(Key("a"), BucketId(1), 2, 10, 180)
        second = KeyDemand(Key("b"), BucketId(1), 1, 10, 190)
        with self.assertRaises(ValueError):
            DemandSnapshot(self.window, (first, second), max_keys_per_bucket=1, max_total_keys=2, max_buckets=2)
        future = KeyDemand(Key("future"), BucketId(1), 1, 10, 201)
        with self.assertRaises(ValueError):
            DemandSnapshot(self.window, (future,), max_keys_per_bucket=2, max_total_keys=2, max_buckets=2)

    def test_unknown_expired_evicted_and_stale_residency_are_not_warm(self) -> None:
        base = dict(key=Key("a"), destination=NodeId("new"), observed_at_ns=190, valid_until_ns=None)
        for state in (ResidencyState.UNKNOWN, ResidencyState.EXPIRED, ResidencyState.EVICTED):
            evidence = ResidencyEvidence(state=state, **base)
            self.assertFalse(evidence.is_warm(as_of_ns=200, max_observation_age_ns=20))
        expired = ResidencyEvidence(state=ResidencyState.CONFIRMED, **{**base, "valid_until_ns": 200})
        self.assertFalse(expired.is_warm(as_of_ns=200, max_observation_age_ns=20))
        stale = ResidencyEvidence(state=ResidencyState.CONFIRMED, **base)
        self.assertFalse(stale.is_warm(as_of_ns=211, max_observation_age_ns=20))

    def test_request_weighted_coverage_differs_from_key_coverage(self) -> None:
        demand = DemandSnapshot(
            self.window,
            (KeyDemand(Key("hot"), BucketId(1), 99, 100, 190),
             KeyDemand(Key("cold"), BucketId(1), 1, 100, 190)),
            max_keys_per_bucket=2,
            max_total_keys=2, max_buckets=2,
            overflow_request_count_by_bucket={BucketId(1): 10},
        )
        resident = {Key("hot"): ResidencyEvidence(Key("hot"), NodeId("new"),
                                                   ResidencyState.CONFIRMED, 195, None)}
        coverage = estimate_coverage(demand, resident, bucket=BucketId(1), as_of_ns=210,
                                     max_residency_age_ns=20,
                                     registered_keys=(Key("hot"), Key("cold")), destination=NodeId("new"))
        self.assertEqual(coverage.key_count_coverage, 0.5)
        self.assertAlmostEqual(coverage.warmed_request_coverage, 0.9)

    def test_cutover_does_not_change_captured_inflight_owner(self) -> None:
        route = RouteCapture(RoutingEpoch(7), BucketId(1), NodeId("old-1"), BucketState.ELIGIBLE)
        record = RequestRecord(1, "run", "req", 100, 110, 150, 1.0,
                               OperationOutcome.COMPLETED, route, DataSource.OLD_CACHE,
                               WorkClass.FOREGROUND_CACHE, 1, 0, None, "cache hit", Key("a"))
        self.assertEqual(record.route.owner, NodeId("old-1"))
        self.assertEqual(record.route.epoch, RoutingEpoch(7))

    def test_unsubmitted_request_is_explicitly_accounted_without_a_route(self) -> None:
        record = RequestRecord(1, "run", "req", 100, None, None, 1.0,
                               OperationOutcome.UNSUBMITTED, None, DataSource.NONE,
                               None, 0, 0, None, "load generator dispatch failure", Key("a"))
        self.assertIsNone(record.end_to_end_latency_ns)
        with self.assertRaises(ValueError):
            RequestRecord(1, "run", "bad", 100, 101, None, 1.0,
                          OperationOutcome.UNSUBMITTED, None, DataSource.NONE,
                          None, 0, 0, None, "invalid", Key("a"))

    def test_db_attempts_require_foreground_db_accounting(self) -> None:
        route = RouteCapture(RoutingEpoch(1), BucketId(1), NodeId("old-1"), BucketState.OLD)
        with self.assertRaises(ValueError):
            RequestRecord(1, "run", "req", 100, 100, 120, 1.0,
                          OperationOutcome.COMPLETED, route, DataSource.DATABASE,
                          WorkClass.FOREGROUND_CACHE, 1, 1, None, "wrong accounting", Key("a"))

    def test_retry_policy_is_finite(self) -> None:
        RetryPolicy(max_attempts=3, attempt_timeout_seconds=0.5, backoff_seconds=(0.1, 0.2))
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=3, attempt_timeout_seconds=0.5, backoff_seconds=(0.1,))

    def test_controller_observation_rejects_future_pressure(self) -> None:
        demand = DemandSnapshot(self.window, (), max_keys_per_bucket=1, max_total_keys=1, max_buckets=2)
        safe = ComponentPressure(PressureState.SAFE, 205, "below threshold")
        future = ComponentPressure(PressureState.SAFE, 211, "future")
        with self.assertRaises(ValueError):
            ControllerObservation(210, demand, 5.0, safe, future, safe, {}, {}, 0, {}, {}, 0, 205, 20, NodeId("new"), {}, 1)

    def test_existing_foreground_demand_is_charged_once(self) -> None:
        incremental = incremental_foreground_db_rate(20.0, 0.75, 1.0)
        self.assertEqual(incremental, 6.0)
        allowance = remaining_db_allowance(100.0, 10.0, 70.0, 4.0)
        self.assertEqual(allowance, 16.0)
        self.assertEqual(admit_in_order(((BucketId(1), incremental), (BucketId(2), 11.0)),
                                        allowance=allowance, max_admissions=2), (BucketId(1),))

    def test_policy_catalog_has_required_controls_and_one_candidate(self) -> None:
        catalog = policy_catalog()
        self.assertEqual(set(catalog), {
            "immediate_cutover", "migration_before_cutover",
            "adaptive_budget_migration_before_cutover", "fixed_gradual_handover",
            "warmup_only_adaptation", "traffic_only_adaptation", "joint_control",
        })
        candidates = [policy for policy in catalog.values() if policy.role is PolicyRole.CANDIDATE_POLICY]
        self.assertEqual([policy.name for policy in candidates], ["joint_control"])

    def test_required_typed_interfaces_are_importable_protocols(self) -> None:
        required = (OwnershipMap, CacheClient, DatabaseClient, KeyDemandTracker,
                    MigrationScheduler, Controller, MetricsSink)
        self.assertTrue(all(getattr(interface, "_is_protocol", False) for interface in required))


if __name__ == "__main__":
    unittest.main()
