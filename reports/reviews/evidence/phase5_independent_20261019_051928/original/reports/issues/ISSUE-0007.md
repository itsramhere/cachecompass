# ISSUE-0007: Phase 2 interfaces and coverage cannot express their stated guarantees

Opened: 2026-10-18T18:21:00Z
Last updated: 2026-10-18T18:58:00Z
Phase: 2 / independent review
Status: verified
Severity: high
Affected component: ownership / controller / scheduler / demand
Affected source/config: submitted source b8e0d79837dddba4b11c176f7bd7610bcab772e83c0563b40e327cef6daff09d
Affected runs/artifacts: Phase 2 gate only; no scientific runs

## Expected behavior

Interfaces express one atomic ownership batch, budget installation, bounded metadata, causal immutable observations, destination-specific residency and distinct whole-registry key/request coverage.

## Observed behavior and original evidence

OwnershipMap offered only per-bucket transition; scheduler had no action/budget input; observation omitted bucket state/rate/epoch; destination-byte grant was absent. Coverage ignored evidence key/destination and counted only recently requested keys. Frozen dataclasses exposed mutable dicts. Static inspection references are preserved in `../reviews/evidence/phase2_20261018_1821/original/`; the absent-interface assertion fails in tests_regressions_before.json (exit 1). Original source manifest: source_before.json. The existing 13-test suite passed because it checked importability and positive examples.

## Minimal reproduction

Inspect OwnershipMap/MigrationScheduler signatures; provide confirmed evidence for a different destination under the same key; count an inactive registered key. The original contract cannot publish/apply a batch/grant or distinguish those coverage cases.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T18:21Z | Protocols disagree with architecture | Compare actual methods/fields with architecture and coverage function | Missing inputs and mismatched key denominator confirmed | Specification/code defect |
| 2 / 2026-10-18T18:35Z | Explicit batch/grant/context and immutable bounded maps resolve mismatch | Add BucketAdvance, publish/apply_action, observation inputs, registry/destination coverage validation | Corrected verification pending | Runtime remains unimplemented |

## Root cause

Presence/import tests substituted for checking whether protocol inputs represent the documented operations and evidence context.

## Resolution

Update contracts.py/interfaces.py and schema/architecture docs; make bounds explicit, snapshot maps immutable, require causal coverage context, and add destination-write bytes. Specify atomic rejection, empty-batch behavior and grant replacement.

## Verification

Final suite: exit 0; 39 tests in 0.005 s, ../reviews/evidence/phase2_20261018_1821/tests_complete.json. Checks include atomic transition/budget interfaces, residency identity, whole registry/overflow coverage, immutable snapshots, decision-time age, coverage provenance/counts, and fixed pressure sampling interfaces with charged DB work. Final 69-file SHA256: fc85008dd9b76d6d3e7d3c3d1ef5359264a11604631b6699a7e505e9733bdd41.

## Experimental impact

No performance evidence exists. Historical reports retained; previous complete gate assessment is superseded.

## Remaining risk or blocker

Actual snapshot publication, bounded tracker cost, eviction evidence and scheduler enforcement require Phase 3 behavior/integration tests.

## Closure

Verified at contract/specification scope on 2026-10-18 UTC; final review records manual coverage and exact limitations. No atomic publication or scheduler runtime was executed.
