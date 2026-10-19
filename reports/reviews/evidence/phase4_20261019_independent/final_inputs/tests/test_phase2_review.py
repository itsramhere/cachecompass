"""Regression checks for defects found in the independent Phase 2 audit."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cache_scaleout import contracts as c
from cache_scaleout import interfaces as i
from cache_scaleout.policies import admit_in_order, incremental_foreground_db_rate, remaining_db_allowance


class ReviewContractTests(unittest.TestCase):
    def request(self, **changes):
        values = dict(schema_version=1, run_id="r", request_id="q", scheduled_arrival_ns=10,
                      submitted_ns=11, completed_ns=20, timeout_seconds=1,
                      outcome=c.OperationOutcome.COMPLETED,
                      route=c.RouteCapture(0, 0, "old", c.BucketState.OLD),
                      source=c.DataSource.OLD_CACHE, work_class=c.WorkClass.FOREGROUND_CACHE,
                      cache_attempts=1, database_attempts=0, coalesced_to_request_id=None, reason="hit", key="a")
        return c.RequestRecord(**(values | changes))

    def test_unsubmitted_cannot_claim_issued_work(self):
        with self.assertRaises(ValueError):
            self.request(outcome=c.OperationOutcome.UNSUBMITTED, route=None,
                         submitted_ns=None, completed_ns=None, source=c.DataSource.NONE,
                         work_class=None, cache_attempts=4)

    def test_foreground_peer_fallback_is_rejected(self):
        with self.assertRaises(ValueError):
            self.request(source=c.DataSource.DONOR_CACHE)

    def test_follower_cannot_double_count_leader_db_work(self):
        with self.assertRaises(ValueError):
            self.request(source=c.DataSource.DATABASE, work_class=c.WorkClass.FOREGROUND_DATABASE,
                         database_attempts=1, coalesced_to_request_id="leader")

    def test_coalesced_request_cannot_reference_itself(self):
        with self.assertRaises(ValueError):
            self.request(coalesced_to_request_id="q")

    def test_cache_source_matches_captured_owner_state(self):
        with self.assertRaises(ValueError):
            self.request(source=c.DataSource.NEW_CACHE)

    def test_completed_request_cannot_exceed_absolute_deadline(self):
        with self.assertRaises(ValueError):
            self.request(completed_ns=1_000_000_011)

    def test_resource_counts_reject_nan_fraction_and_boolean(self):
        for value in (float("nan"), float("inf"), 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.ResourceLimits(value, 1, 1, 1, 1, 1, 1, 1, 1, 1)

    def test_retry_count_must_be_integer(self):
        with self.assertRaises(ValueError):
            c.RetryPolicy(1.0, 1.0)

    def test_action_rejects_negative_buckets_and_empty_reasons(self):
        budget = c.TransferBudget(1, 1, 1, 1, 1, 1)
        with self.assertRaises(ValueError):
            c.ControllerAction(1, budget, (-1,), ("",), 0, 1)

    def test_admission_rejects_duplicate_candidates(self):
        with self.assertRaises(ValueError):
            admit_in_order(((1, 1.0), (1, 1.0)), allowance=3, max_admissions=2)

    def test_migration_attempt_rejects_wrong_source_accounting(self):
        with self.assertRaises(ValueError):
            c.MigrationAttemptRecord(1, "r", "t", 1, c.DataSource.OLD_CACHE, "old", "new", 1,
                                     c.WorkClass.FOREGROUND_DATABASE, c.OperationOutcome.COMPLETED,
                                     1, 0, 1, 2, "bad")

    def test_interfaces_can_publish_atomic_batch_and_apply_budget(self):
        self.assertTrue(callable(getattr(i.OwnershipMap, "publish", None)))
        self.assertTrue(callable(getattr(i.MigrationScheduler, "apply_action", None)))

    def demand(self, overflow=None):
        return c.DemandSnapshot(c.ObservationWindow(100, 200, 210, 20),
                                (c.KeyDemand("a", 1, 8, 10, 190),), 3, 3, 2,
                                overflow or {})

    def coverage(self, residency, **changes):
        values = dict(bucket=1, as_of_ns=210, max_residency_age_ns=20,
                      registered_keys=("a", "b", "unobserved"), destination="new")
        return c.estimate_coverage(self.demand(), residency, **(values | changes))

    def test_coverage_uses_whole_registry_and_overflow(self):
        evidence = c.ResidencyEvidence("a", "new", c.ResidencyState.CONFIRMED, 200, None)
        coverage = self.coverage({"a": evidence})
        self.assertEqual(coverage.key_count_coverage, 1 / 3)
        self.assertEqual(coverage.warmed_request_coverage, 1)
        overflow = c.estimate_coverage(self.demand({1: 8}), {"a": evidence}, bucket=1,
                                     as_of_ns=210, max_residency_age_ns=20,
                                     registered_keys=("a", "b"), destination="new")
        self.assertEqual(overflow.warmed_request_coverage, 0.5)

    def test_wrong_key_or_destination_cannot_count_as_warm(self):
        for key, destination in (("b", "new"), ("a", "old")):
            evidence = c.ResidencyEvidence(key, destination, c.ResidencyState.CONFIRMED, 200, None)
            self.assertEqual(self.coverage({"a": evidence}).confirmed_warm_requests, 0)

    def test_stale_and_noncausal_demand_cannot_confirm_coverage(self):
        evidence = c.ResidencyEvidence("a", "new", c.ResidencyState.CONFIRMED, 220, None)
        self.assertEqual(self.coverage({"a": evidence}, as_of_ns=221).confirmed_warm_requests, 0)
        with self.assertRaises(ValueError):
            self.coverage({}, as_of_ns=199)
        with self.assertRaises(ValueError):
            self.coverage({}, registered_keys=("b",))

    def test_snapshot_maps_are_copied_and_immutable(self):
        original = {1: 2}
        snapshot = self.demand(original)
        original[1] = 900
        self.assertEqual(snapshot.overflow_request_count_by_bucket[1], 2)
        with self.assertRaises(TypeError):
            snapshot.overflow_request_count_by_bucket[1] = 3

    def test_total_bucket_and_window_demand_bounds(self):
        snapshot = self.demand()
        for changes in (dict(max_total_keys=0), dict(max_buckets=1),
                        dict(overflow_request_count_by_bucket={2: 1}),
                        dict(entries=(c.KeyDemand("a", 1, 1, 1, 99),)),
                        dict(entries=(c.KeyDemand("a", 1, 1, 1, 200),))):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(snapshot, **changes)

    def observation(self, **changes):
        safe = c.ComponentPressure(c.PressureState.SAFE, 205, "safe")
        coverage = c.CoverageEstimate(3, 0, 8, 0, 0, 210, "new", 100, 200)
        values = dict(observed_at_ns=210, demand=self.demand(), foreground_db_rate_upper=70,
                      db_pressure=safe, donor_pressure=safe, destination_pressure=safe,
                      bucket_coverage={1: coverage}, bucket_states={1: c.BucketState.ELIGIBLE},
                      routing_epoch=2, candidate_request_rate_upper={1: 10}, uncertain_miss_reserve_rate={1: 1},
                      pending_admission_db_rate_upper=5, foreground_db_observed_at_ns=205,
                      max_signal_age_ns=20, destination_owner="new", old_owner_db_rate_lower={1: 2},
                      observation_db_rate_upper=1)
        return c.ControllerObservation(**(values | changes))

    def test_old_safe_samples_become_stale_automatically(self):
        self.assertTrue(self.observation().admissions_safe)
        self.assertFalse(self.observation().admissions_safe_at(231))
        with self.assertRaises(ValueError):
            self.observation().admissions_safe_at(209)
        old = c.ComponentPressure(c.PressureState.SAFE, 100, "old safe")
        self.assertFalse(self.observation(donor_pressure=old).admissions_safe)
        self.assertFalse(self.observation(foreground_db_observed_at_ns=100).admissions_safe)
        unknown = c.ComponentPressure(c.PressureState.UNKNOWN, 205, "no data")
        self.assertFalse(self.observation(destination_pressure=unknown).admissions_safe)

    def test_observation_rejects_inconsistent_bucket_maps(self):
        with self.assertRaises(ValueError):
            self.observation(candidate_request_rate_upper={})
        with self.assertRaises(TypeError):
            self.observation().bucket_states[1] = c.BucketState.NEW
        coverage = self.observation().bucket_coverage[1]
        for changes in (dict(destination="old"), dict(as_of_ns=209), dict(observed_requests=9)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.observation(bucket_coverage={1: replace(coverage, **changes)})

    def test_retry_amplification_and_cross_tick_reserve_consume_allowance(self):
        rate = incremental_foreground_db_rate(20, 0.75, 1, max_foreground_attempts=2)
        self.assertEqual(rate, 12)
        self.assertEqual(incremental_foreground_db_rate(20, 0.75, 1, max_foreground_attempts=2,
                                                       old_owner_db_rate_lower=2), 10)
        self.assertEqual(incremental_foreground_db_rate(20, 0.75, 1, max_foreground_attempts=2,
                                                       old_owner_db_rate_lower=15), 0)
        allowance = remaining_db_allowance(100, 10, 70, 4, pending_admission_db_rate_upper=8)
        self.assertEqual(allowance, 8)
        self.assertEqual(admit_in_order(((1, rate), (2, 4)), allowance=allowance, max_admissions=2), (2,))

    def test_pressure_sampling_has_explicit_interfaces_and_db_charge(self):
        self.assertTrue(callable(getattr(i.CacheClient, "sample_pressure", None)))
        self.assertTrue(callable(getattr(i.DatabaseClient, "sample_pressure", None)))
        self.assertEqual(c.WorkClass.OBSERVATION_DATABASE.value, "observation_database")
        self.assertEqual(remaining_db_allowance(100, 10, 70, 4, pending_admission_db_rate_upper=8,
                                               observation_db_rate_upper=3), 5)
        with self.assertRaises(ValueError):
            self.observation(observation_db_rate_upper=float("nan"))

    def test_invalid_candidates_are_checked_even_after_admission_cap(self):
        with self.assertRaises(ValueError):
            admit_in_order(((1, 0), (2, float("nan"))), allowance=1, max_admissions=0)

    def test_all_terminal_request_outcomes_remain_representable(self):
        records = [self.request(request_id=outcome.value, outcome=outcome)
                   for outcome in (c.OperationOutcome.COMPLETED, c.OperationOutcome.TIMED_OUT,
                                   c.OperationOutcome.FAILED, c.OperationOutcome.CANCELLED)]
        records.append(self.request(request_id="refused", outcome=c.OperationOutcome.REFUSED,
                                    cache_attempts=0, source=c.DataSource.NONE, work_class=None))
        records.append(self.request(request_id="unsubmitted", outcome=c.OperationOutcome.UNSUBMITTED,
                                    submitted_ns=None, completed_ns=None, route=None, cache_attempts=0,
                                    source=c.DataSource.NONE, work_class=None))
        self.assertEqual(len({r.request_id for r in records}), 6)
        follower = self.request(request_id="follower", source=c.DataSource.DATABASE,
                                coalesced_to_request_id="q")
        self.assertEqual(follower.database_attempts, 0)

    def test_destination_writes_and_unknown_bytes_are_explicit(self):
        retry = c.RetryPolicy(2, 0.5, (0.1,))
        task = c.MigrationTask("write", "a", 1, "new", "new", c.DataSource.NEW_CACHE,
                               c.WorkClass.DESTINATION_WRITE, 1, retry, None, 1000, "read")
        self.assertEqual(task.parent_task_id, "read")
        attempt = c.MigrationAttemptRecord(1, "r", "write", 2, c.DataSource.NEW_CACHE, "new", "new",
                                          1, c.WorkClass.DESTINATION_WRITE, c.OperationOutcome.TIMED_OUT,
                                          1, None, 100, 200, "unknown bytes", 1024)
        self.assertIsNone(c.json_record(attempt)["issued_bytes"])
        with self.assertRaises(ValueError):
            replace(attempt, issued_bytes=1025)
        with self.assertRaises(ValueError):
            replace(attempt, outcome=c.OperationOutcome.UNSUBMITTED)
        with self.assertRaises(ValueError):
            replace(task, source=c.DataSource.OLD_CACHE)
        with self.assertRaises(ValueError):
            replace(task, parent_task_id=None)

    def test_atomic_advance_can_express_immediate_policy(self):
        advance = c.BucketAdvance(1, c.BucketState.OLD,
                                  (c.BucketState.COPYING, c.BucketState.ELIGIBLE, c.BucketState.NEW))
        self.assertEqual(advance.path[-1], c.BucketState.NEW)
        with self.assertRaises(ValueError):
            c.BucketAdvance(1, c.BucketState.OLD, (c.BucketState.NEW,))

    def test_budget_action_and_event_serialization_keep_units_and_details(self):
        budget = c.TransferBudget(2, 1024, 1, 2, 100, 2048)
        action = c.ControllerAction(210, budget, (1,), ("admit",), 2, 210)
        self.assertEqual(c.json_record(action)["budget"]["destination_write_bytes"], 2048)
        with self.assertRaises(ValueError):
            replace(action, observation_as_of_ns=211)
        detail = {"observation": {"as_of": 210}}
        event = c.EventRecord(1, "r", "2026-10-18T18:00:00Z", 210, c.EventPhase.HANDOVER,
                              2, c.EventKind.POLICY_ACTION, 1, "joint_control", {}, "admit", {}, detail)
        detail["observation"]["as_of"] = 999
        self.assertEqual(c.json_record(event)["detail"]["observation"]["as_of"], 210)
        with self.assertRaises(TypeError):
            event.detail["observation"]["as_of"] = 999
        with self.assertRaises(ValueError):
            c.json_record(replace(event, detail={"bad": float("nan")}))
        with self.assertRaises(TypeError):
            c.json_record(replace(event, detail={"payload": b"secret"}))


if __name__ == "__main__":
    unittest.main()
