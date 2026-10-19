# Phase 5 independent handoff

Verified: 2026-10-19T06:13:08.042266+00:00. **Phase5 PASS after corrections. Stop before Phase6.**

All work and uncommitted changes are saved in `/workspace/cachecompass`, Git
`a659f237c1f2940d83b714814e0bbf458f009c5d` plus dirty files. The Windows path is
not mounted. A chat attached to this same persistent filesystem can read these
files; it must inspect git status and these reports, rather than assume chat
memory or a separate checkout contains the work. No commit or push was made.

Measured source `ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823` (107 inputs); publication source `d74ef2e7b58c2e002fdb007fae796befd47e4dbd0256722c6e4989ad7854fd9e`.
Only `analysis/phase5_validation.py` changes after measurement, to classify
failed probe prefixes correctly; all runtime/configuration/tuning/measurement
inputs are unchanged. Both identities and archives are in `reports/reviews/evidence/phase5_independent_20261019_051928/`.


Review authority: [phase_05_independent_20261019_051928.md](reviews/phase_05_independent_20261019_051928.md).
Report: [phase_05.md](phase_05.md). Protocol: [PHASE5_INDEPENDENT_PROTOCOL.md](../docs/PHASE5_INDEPENDENT_PROTOCOL.md).
Evidence: `reports/reviews/evidence/phase5_independent_20261019_051928/` and `reports/evidence/phase5/p5ind_20261019_m3/`; raw data `runs/p5ind_20261019_m3_*`.

## What is verified

Six controls: immediate, fixed migration-before-cutover, adaptive-budget migration-
before-cutover, fixed gradual, warmup-only and traffic-only. Same router/pools,
retries/cleanup/observations, budgets/bytes and finite tasks. No joint candidate.
158 frozen-source tests pass including23 actual-client cases. Twelve fair pilot
cases select common B before six fresh matched smokes. All24 qualified runs
reconcile7,684 offers; both zero-budget migration controls cut over explicit cold
keys, while deadline/nonprogress are valid failures. A separate actual failed-
probe diagnostic plus16 resealed-record and3 bundle checks pass. Reader-only
post-measurement regression has135 passes and23 live skips.

The common conditional DB total is12/s, including2/s probes, with reserve2/s.
Both8+2 and6+4 real-query splits pass unchanged p95/dispatch/payload rules. The
16/s point failed max dispatch and remains visible; no saturation, general
capacity/safety, optimal tuning, controller-improvement or superiority claim.

## Reproduce on the existing Linux environment

Use the existing `.venv`, pinned images in infra/images.env and fresh IDs. The
wrapper verifies disposable labels, recreates only paper2-research and shuts it
down. Run a small functional case (numeric budget alone is not capacity evidence):

```bash
.venv/bin/python scripts/phase5_cycle.py --run-id p5-functional-fresh --record reports/evidence/phase5/p5-functional-fresh.json -- --policy adaptive_budget_migration_before_cutover --setting B --seed 606 --total-db-rate 12
.venv/bin/python analysis/phase5_validation.py --runs p5-functional-fresh --output reports/evidence/phase5/p5-functional-fresh-validation.json
.venv/bin/python scripts/phase5_cycle.py --run-id p5-tests-fresh --record reports/evidence/phase5/p5-tests-fresh.json --tests
```

A standalone numeric-rate case may be raw-valid but review_eligible=false until
applicable mixed evidence exists. A complete new qualified reproduction performs
both mixed checks itself and embeds their source/configuration applicability:

```bash
.venv/bin/python -B scripts/phase5_matrix.py --prefix p5-matrix-fresh --total-db-rate 12
```

Do not wrap the full matrix in the generic180-second recorder; each case has90s
watchdog and finally disposal, total bounded35min. Exact successful2100s capture
is run_lower_replacement.py in review evidence. Reproduce retained raw validation:

```bash
.venv/bin/python analysis/phase5_validation.py --runs p5ind_20261019_m3_smoke0 p5ind_20261019_m3_smoke1 p5ind_20261019_m3_smoke2 p5ind_20261019_m3_smoke3 p5ind_20261019_m3_smoke4 p5ind_20261019_m3_smoke5 --matched --output reports/evidence/phase5/revalidate-fresh.json
```

The final verification script accepts a fresh --output path; its report records
all24 cases, selection, byte/retry reconciliation, source/archive identity and
preservation. Historical output IDs refuse overwrite. No figures/effect estimates
are required at this implementation gate; all smoke/tuning data remain visible.

## Failures, preservation and next boundary

Original owner source100 inputs and old living reports are archived. The owner
matrix, first-review12 cases,16/s negative and all original failures remain
unchanged; evidence_register.json explains replacements and classifications.
ISSUE-0029–0034 and0036 are verified; ISSUE-0035 operating variability and0004
literature access remain accepted limitations. No rewrite of historical data.

Services are shut down. Scope remains one Linux host/router, immutable fitting
512×1KiB dataset,20000-round buffered SQL, one expansion, short runs and a two-
profile provisional search. TTL/expiry tests are separate; no mutable/multi-router,
production, measured wire-throughput or universal safety claim. The next concrete
action is to review the signed-off artifact; Phase6 requires a separate task.
