# ISSUE-0008: Cleanup, adaptive controls and reset leave comparison-changing choices unspecified

Opened: 2026-10-18T18:21:00Z
Last updated: 2026-10-18T18:58:00Z
Phase: 2 / independent review
Status: verified
Severity: high
Affected component: policy methodology / cleanup / reset
Affected source/config: submitted source b8e0d79837dddba4b11c176f7bd7610bcab772e83c0563b40e327cef6daff09d
Affected runs/artifacts: Phase 2 gate only; no scientific runs

## Expected behavior

Implementers need parameter values later, but must not invent ramp/classifier/source-exhaustion rules, creator-cancellation ownership, byte reservation semantics, traffic stability or fair physical initial state.

## Observed behavior and original evidence

POLICIES.md named configurable hysteresis/ramp/uncertainty rules without algorithms; ARCHITECTURE.md left issued final-waiter cleanup and creator deadlines ambiguous, allowed shared-cache namespaces and sampled equivalence, and did not specify stability samples or overlapping budget grants. Original files are retained at `../reviews/evidence/phase2_20261018_1821/original/`. This is a manual specification finding, not a failed runtime experiment; no process exit code applies.

## Minimal reproduction

Attempt to implement fixed/isolated/joint policies from the submission: choosing ramp functions, skipped schedule handling, retry stages, final-waiter cancellation, and sample acceptance requires new behavioral decisions. A new namespace on the same Redis process still competes with old keys under maxmemory/allkeys-lru.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T18:21Z | Missing numerical tuning is being conflated with missing algorithms | Read policies, invariants and lifecycle rules against Phase 2 gate | Several algorithms/dispositions absent | Gate initially unmet |
| 2 / 2026-10-18T18:35Z | One normative supplement can specify behavior without a runtime | Write PHASE2_EXECUTION_CONTRACT.md and align existing documents | Exact formulas/procedures specified; semantic audit pending | Scoped Phase 2 correction |

## Root cause

Earlier documents described intended protection at a high level but deferred behavioral rules alongside legitimate calibration values.

## Resolution

Specify exact adaptive/fixed/pass rules, retry-aware cross-tick reserve, issued-operation cleanup/connection discard, finite attempt stages, conservative byte reservations, full offered-schedule reconciliation, recreated disposable caches and complete initial summaries, fixed measurement horizon and per-subwindow traffic stability. Record consequential choices in DECISION-0009.

## Verification

Manual requirement audit: ../reviews/phase_02_independent_20261018_1821.md. Final local suite: exit 0; 39 tests in 0.005 s, tests_complete.json in its evidence directory. Exact rules: docs/PHASE2_EXECUTION_CONTRACT.md; SHA256 fc85008dd9b76d6d3e7d3c3d1ef5359264a11604631b6699a7e505e9733bdd41. Documentation inspection is not runtime validation.

Final semantic follow-up: UNKNOWN pressure with zero initial migration grants requires a separate observation source; otherwise an idle destination/DB has no specified path to fresh safety evidence. This is a specification finding, not an observed runtime deadlock. Added identical bounded PING/INFO/DB sampling for all policies, independent fixed observation grants, attainable sample minima, finite no-overlap rounds and explicit DB overhead allowance. The 39th test checks those interfaces and arithmetic; actual sampling/classification remains future behavior.

## Experimental impact

No experiment invalidated or rerun. Historical Phase 2 gate claim is superseded by the new independent review.

## Remaining risk or blocker

Parameter calibration, client cancellation semantics, actual reset equivalence and policies' useful operating region remain future evidence requirements.

## Closure

Verified as a specification correction on 2026-10-18 UTC. No unresolved algorithm/lifecycle/reset choice blocks Phase 3, whose behavioral and real-client gates remain required.
