# ISSUE-0006: Phase 2 records accept contradictory accounting and invalid limits

Opened: 2026-10-18T18:21:00Z
Last updated: 2026-10-18T18:58:00Z
Phase: 2 / independent review
Status: verified
Severity: high
Affected component: schemas / accounting / policy contracts
Affected source/config: submitted source b8e0d79837dddba4b11c176f7bd7610bcab772e83c0563b40e327cef6daff09d
Affected runs/artifacts: Phase 2 specification gate claim only; no scientific runs

## Expected behavior

Records reject unsubmitted issued work, forbidden foreground donor sources, follower-owned DB attempts, self-coalescing, cache source/route mismatch and late success. Resource/retry counts are finite integers; issued migration sources match their accounting classes. Candidate IDs are unique.

## Observed behavior and original evidence

The original 13 tests pass, but the focused negative suite exposes 15 failing assertions across 12 new tests (including four invalid-limit subtests). Exact commands, interpreter, output, UTC and source fingerprints: `../reviews/evidence/phase2_20261018_1821/tests_baseline.json` and `tests_regressions_before.json`. Original changed files are in that directory's `original/`. Environment: historical `../environment.json`; existing CPython 3.12.10 via approved native boundary; no services required.

## Minimal reproduction

Run the retained regression tests against the retained original contracts/interfaces/policies. Examples: an UNSUBMITTED record with four cache attempts, a completed DONOR_CACHE foreground record, or `ResourceLimits(nan,1,...)` constructs without error. Reproduction outcome: reproduced; suite exit 1, 25 tests, failures=15.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T18:21Z | Positive-only checks miss contradictory records | Rerun existing suite, add negative semantic cases | 13 pass; new negative suite fails | Constructor validation is incomplete, not a runtime failure |
| 2 / 2026-10-18T18:35Z | Enforcing class/source/chronology/count relations closes those paths | Scoped contract and admission validation changes | Verification pending | No live behavior inferred |

## Root cause

Annotations were treated as validation, several early returns bypassed accounting checks, and issued-migration records did not enforce task source/class relations.

## Resolution

Strengthen contracts.py and policies.py, expose foreground write counts, reject duplicate/invalid candidate IDs, and specify unique operation-ledger reconciliation and delayed shared-fill accounting. DB estimates now include retry amplification and pending admissions across ticks.

## Verification

Final corrected suite: exit 0; 39 tests in 0.005 s, tests_complete.json linked to tests_regressions_before.json in the review evidence directory. Includes original negatives, terminal outcomes, retry amplification, displaced old-owner credit, cross-tick pending reserve and explicit observation-DB charge. Corrected source: fc85008dd9b76d6d3e7d3c3d1ef5359264a11604631b6699a7e505e9733bdd41 (69 files). Earlier 38-test evidence is retained.

## Experimental impact

No experiment/figure invalidated. Historical 13-test success remains authentic but does not support the original complete gate claim.

## Remaining risk or blocker

Constructors cannot prove cross-record uniqueness, live retry charging or async cleanup; Phase 3 must implement and verify them.

## Closure

Verified at contract scope by the retained final suite and semantic audit on 2026-10-18 UTC; see ../reviews/phase_02_independent_20261018_1821.md. No live-system claim.
