# Issue index

| Issue | Phase | Status | Impact | Record |
| --- | --- | --- | --- | --- |
| ISSUE-0001 | 0 | verified | Approved execution path verified; sandbox restrictions remain an environment constraint | [Record](issues/ISSUE-0001.md) |
| ISSUE-0002 | 0 | verified | Existing Docker Desktop started; real service health and shutdown passed | [Record](issues/ISSUE-0002.md) |
| ISSUE-0003 | 0 | verified | File-based Python invocation fixed bootstrap quoting; rerun and fingerprint passed | [Record](issues/ISSUE-0003.md) |
| ISSUE-0004 | 1 | accepted_limitation | AdaptCache citation verified; full-text access 403 limits exhaustive novelty assessment | [Record](issues/ISSUE-0004.md) |
| ISSUE-0005 | 2 | verified | Restricted sandbox blocked venv base resolution; unchanged suite passed via existing approved CPython 3.12 | [Record](issues/ISSUE-0005.md) |
| ISSUE-0006 | 2 review | verified | Contradictory accounting, invalid limits and retry-aware allowance corrected; negative failures and linked 39-test rerun retained | [Record](issues/ISSUE-0006.md) |
| ISSUE-0007 | 2 review | verified | Atomic batch/grant interfaces, immutable bounded observations and destination/window-specific coverage corrected | [Record](issues/ISSUE-0007.md) |
| ISSUE-0008 | 2 review | verified | Exact policy/pass/cleanup/reset/stability rules specified; runtime verification remains Phase 3 | [Record](issues/ISSUE-0008.md) |

No open Phase 0 blocker. Failed bootstrap.log/bootstrap-error.txt and original inspection are retained; successful bootstrap-rerun.json, doctor-001.json and phase0-health-001 explicitly provide their corrective verification. Duplicate-run-guard.json has expected exit 1 and is a successful preservation check, not an incident or scientific failed run.

Phase 1 has no dependency blocker for characterization. ISSUE-0004 remains an accepted access limitation, not a fixed defect. No performance experiment has run; failed HTTP access and successful alternate metadata diagnostics are retained together. The existing reviewer finding R1 concerned the earlier absent Phase 1 submission; the implementation handoff at reports/phase_01.md supplies the requested deliverables for renewed review without changing that historical review.

Phase 2 has no open gate blocker. ISSUE-0005 preserves the failed sandbox launcher invocation and the unchanged successful suite through the established approved native Python 3.12 boundary. No services or scientific runs were started; no results were invalidated.

The independent Phase 2 review supersedes the original assessment after correcting ISSUE-0006 through ISSUE-0008. Original source, initial pass, negative failures, linked reruns and preservation results are under reports/reviews/evidence/phase2_20261018_1821/. Historical Phase 1 reviewer F04/F05 tooling/reporting concerns are not recertified by this Phase 2 gate; no claim is made that every literature retrieval failure path is repaired. ISSUE-0004 remains an accepted access limitation.

