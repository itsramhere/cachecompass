# Project status

Updated: 2026-10-19 UTC
Active phase: 5 — implement strong baselines
Phase status: blocked
Gate: NOT MET — corrected actual-client comparison matrix cannot launch
Source revision: a659f237c1f2940d83b714814e0bbf458f009c5d plus dirty canonical SHA256
796910788bedc489fc047e656ebc5b3115926d899bc28df4c1b740644784613e (100 inputs)
Environment: managed Linux Python 3.12.14, recorded installed package versions,
pinned Redis/PostgreSQL digests, identical quotas and foreground/background pools

## Delivered and verified

Six experimental controls implemented: immediate_cutover, fixed_gradual_handover,
migration_before_cutover, warmup_only_adaptation, traffic_only_adaptation,
adaptive_budget_migration_before_cutover. Shared router/adapters/pools/observer,
finite passes, tokens/bytes/grants, cleanup and accounting; no joint controller.

Final full live suite: 134 tests pass in 9.925 seconds, all 17 actual-client cases,
no skips; exact source unchanged before/after, services shut down. Both mixed
pool checks pass raw validation and select conditional total16 DB attempts/s,
including fixed2/s probes and a further2/s reserve. No saturation/improvement
or general safe-capacity claim. All 100 final tested inputs archived exactly.
Historical audit: 1,657 evidence/run/review/analysis files unchanged.

## Failure and replacement record

Initial complete 20-run tuning/fresh smoke/boundary matrix is retained but
excluded from final comparison evidence. Its raw accounting passes; later
semantic audit and two deterministic negatives expose premature old-grant
expiry under a live replacement (ISSUE-0027). The correction passes both
negatives and the final full live suite. A separate physical TTL defect on
this Linux host (ISSUE-0026) is verified fixed by original live expiry checks.

The registered identical 20-run replacement p5matrix_v2_20261019 did NOT launch.
Automatic execution review failed for model capacity, then timed out twice.
Supported explicit network permission request returned no grant (network:null).
No refusal was bypassed and no unexecuted run is claimed as executed. Last
completed cycles verified shutdown; no corrected-matrix service was started.
ISSUE-0028 blocks the gate. See reports/phase_05.md and HANDOFF_PHASE5.md.

## Next action and limits

With execution permission available, run the already prepared command:
.venv/bin/python scripts/phase5_matrix.py --prefix p5matrix_v2_20261019 --retry-prefix p5matrix_v1_20261019
It repeats the same finite grid, saves selection before fresh comparisons,
validates all raw records and stops disposable services. Do not add tuning
points or require favorable performance rankings. Then reassess Phase5.

Windows directory unavailable; all work is in /workspace/cachecompass after
fast-forwarding configured origin to user-named Phase4 commit. Both unrelated
cloud run directories preserved. No new commit or push. Stop before Phase6.
Final evaluation freezing remains Phase7. Immutable/single-host/single-router,
short synthetic workload and no-expiry comparison limits remain; TTL separately
tested. Unknown wire bytes remain null. ISSUE-0004 literature access persists.
