# ISSUE-0009: Final-waiter cancellation misclassified issued DB work

Opened: 2026-10-18T20:29:25Z
Last updated: 2026-10-18T20:38:16Z
Phase: 3 / minimal system
Status: verified
Severity: high
Affected component: router / telemetry accounting
Affected source/config: initial Phase 3 implementation; final fingerprint pending
Affected runs/artifacts: fake-client behavioral test only; no scientific run

## Expected behavior

When the final waiter cancels after its shared fill issued a foreground DB attempt, the leader terminal record must retain that DB attempt and classify the request as `foreground_database`. The fill must be cancelled and its permit released.

## Observed behavior

The DB attempt was issued, but cancellation constructed the leader record with `foreground_cache`. `RequestRecord` correctly rejected the contradiction before telemetry emission.

## Original evidence

- Command or run: `.venv\Scripts\python.exe -B -m unittest tests.test_phase3_behavior -v` through `scripts/record_command.py`.
- Exit code: 1; 12 tests ran, 11 passed and one errored.
- Log/traceback: `reports/evidence/phase3/behavior-tests-001.json`; `ValueError: foreground database work must be charged explicitly`.
- Environment: retained Phase 0 environment; fake clients, no services.

## Minimal reproduction

1. Start one cache miss whose fake DB read blocks.
2. Cancel the only waiter after the DB attempt is issued.
3. Observe terminal-record construction fail before cleanup assertions execute.

Reproduction outcome: reproduced deterministically once in the retained suite.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-19T20:00Z | The cancellation branch ignores leader-owned DB attempts | Compare ledger state and cancellation record construction with the timeout branch | Ledger has one DB attempt; branch hard-coded `foreground_cache` | Supported; classification defect is local to cancellation record construction |

## Root cause

The cancellation branch selected work class only from the last source and did not check whether this request was the shared-fill origin with an issued DB attempt.

## Resolution

Classify a cancelled shared-fill leader as `foreground_database` when its operation ledger contains an issued DB read. Followers and cache-only cancellations remain `foreground_cache`.

## Verification

The linked original reproduction rerun passed all 12 tests (`behavior-tests-002.json`). The expanded final fake-client suite passed all 14 tests (`behavior-tests-003.json`), including final-waiter cancellation, DB cancellation, zero active fake connections and empty coalescing state.

## Experimental impact

No service or scientific run exists. The failed fake-client run is retained and will be linked to the corrected rerun.

## Remaining risk or blocker

No known cancellation-accounting defect remains. Multi-router coalescing is outside scope.

## Closure

Verified 2026-10-18T20:38:16Z by the linked behavioral rerun and final expanded suite.
