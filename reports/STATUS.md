# Project status

Updated: 2026-10-19T04:06:30Z
Active phase: 4 — calibrate capacity and characterize immediate expansion
Phase status: complete
Gate: PASS after independent corrections, for Phase 4 only; stopped before Phase 5
Executed source: Git `186c3ddb4daf36c2a8dbe7884a82dfb929381ba1` plus dirty canonical SHA256 `cda5257b9974cd72e8e99a5ab0a94dca462e02a241d505a056e93902589c03fa` (88 inputs), `reports/reviews/evidence/phase4_20261019_independent/final_confirmation_source.json`
Publication source: `reports/reviews/evidence/phase4_20261019_independent/publication_source.json`; only README/byte-preservation attributes change after measurement; runtime/config/test/analysis bytes are unchanged
Environment: native Windows CPython 3.12.10, pinned Redis 7.4/PostgreSQL 17, verified 0.5-CPU Redis/1-CPU DB container limits; disposable services shut down

## Outcome so far

The independent review supersedes the implementation-owner PASS and the first independent matrix. Corrected common probes/pools, configurable workload, stable warm windows, fixed observation horizon, raw fail-closed analysis and an actual DB deadline/orphan race. All affected calibration and expansion/control measurements were replaced with linked fresh IDs, not selectively reused.

All 107 tests passed (including 17 actual-client and 17 focused Phase 4 cases); all 16 replacement runs passed raw validation, accounting for 5,472 offers. Immediate expansion added 26 foreground DB attempts per transition window and increased p95 in all three pairs: 24.6–38.4 ms, mean 31.4 ms, exploratory normal-model t95 interval 14.2–48.7 ms, n=3 independent pairs. This is an attributable cache-miss path penalty, not demonstrated DB saturation during expansion or a controller improvement.

The conditional foreground operating point is 24 attempts/s with common observation demand separately recorded. All three 24-rps runs issued/completed all offers with zero target violations; 12-rps tail violations and 36-rps overload/client dispatch interference remain disclosed. Do not substitute the foreground value for the execution contract's total C_safe without charging observers and revalidating the actual query/pool split. The 144-rps cached profile demonstrates combined router/generator/cache/telemetry headroom at four times the tested application load.

## Current evidence

- [Independent review](reviews/phase_04_independent_20261019_0354.md): findings, corrections, exact checks, run-level uncertainty, gate and limits.
- [Handoff](HANDOFF_PHASE4.md): startup/reproduction/analysis boundaries.
- `reports/analysis/phase4_independent_final_20261019/`: raw-derived curve, matched tables, figures and all 16 validation verdicts.
- `reports/reviews/evidence/phase4_20261019_independent/final_full_live_suite.json`: exact frozen-source 107-test pass.
- `raw_final_audit.json`: issue-time work, pool/CPU/throttling, headroom, reset/payload/accounting and preservation audit.
- `final_regeneration_verification.json`: two byte-identical regenerations; no CSV/raw or SVG coordinate mismatch.
- `evidence_register_final.json`: original labels retained alongside explicit exclusion/replacement classifications, 71 run directories and exact-command index.
- `final_buffer_probe.json`: actual same-query 20,000-round EXPLAIN, three shared hits and zero reads; no disk-IO claim.

## Issues and impact

ISSUE-0023 through ISSUE-0025 are verified by the complete replacement matrix and regressions. Original failures and first-review failures remain retained with replacement chains. ISSUE-0004 is still the accepted literature-access limitation. Short horizons, n=3 deterministic-workload repetitions, shared-host/coarse-clock interference, artificial CPU-heavy buffered query and unknown wire bytes limit scope; they do not establish production or later-policy guarantees.

## Handoff boundary

Stop before Phase 5. No later baseline suite/controller, mutable-data extension, improvement claim, publication or Git commit/push was performed. Future work must preserve the corrected common request/pool/probe/timeout/issuance semantics and separately justify any capacity-budget conversion or new query mix. Use fresh run/output IDs; never overwrite the retained evidence.
