# Phase 4 independent handoff

Updated: 2026-10-19T04:06:30Z. Phase 4 passes after corrections; stop before Phase 5.

The artifact supports immutable cache-aside reads through one router, two old Redis processes and one healthy empty destination, with actual pooled PostgreSQL queries. It implements only immediate ownership cutover and a matched no-expansion control for Phase 4. The [independent review](reviews/phase_04_independent_20261019_0354.md) is the findings/gate authority; [status](STATUS.md), [phase report](phase_04.md) and [frozen protocol](../docs/PHASE4_REVIEW_PROTOCOL.md) agree. No later baseline/controller or improvement claim is delivered.

Measured source SHA256 `cda5257b9974cd72e8e99a5ab0a94dca462e02a241d505a056e93902589c03fa`; `reviews/evidence/phase4_20261019_independent/final_confirmation_source.json` lists all 88 inputs and per-file hashes. Final README/byte-preservation attributes are separately captured by `publication_source.json`; implementation/config/test/analysis bytes remain identical to measured inputs. The user/owner's unrelated dirty changes were preserved. No Git commit/push was requested or performed.

The complete frozen-source suite passed 107 tests, including 17 actual-client checks. Sixteen fresh runs validate all 5,472 offers. Three matched pairs show p95 increases 24.6–38.4 ms (mean 31.4; exploratory t95 interval 14.2–48.7, n=3), with 26 extra foreground DB attempts per transition. The conditional 24-foreground-attempt/s calibration point includes separately recorded fixed probe overhead; do not use it as physical DB peak capacity or an uncharged total budget. The 12-rps tails, 36-rps pool/dispatch interference, short horizons and shared-host timers limit inference. No policy-improvement inference follows.

## Reproduce with fresh IDs

From `C:\Users\ramst\Documents\antigravity\paper2`, using the existing documented virtual environment and pinned Docker images:

```powershell
& .\scripts\phase4_run.ps1 -Mode immediate -RunId phase4-handoff-fresh-immediate -Rate 36 -Condition immediate
```

The wrapper label-checks and recreates only `paper2-research`, uses `configs/phase4_review.yaml`, and shuts down afterward. Pick a never-used ID. Use `-Mode calibrate -Rate 24` for a fresh 12-second capacity point. For a new matched pair, run control and immediate with the same `-PairId`, distinct IDs, and identical config/rate; the wrapper recreates services for each. Never rewarm only one condition or reuse physical cache state.

For actual-client tests:

```powershell
& .\scripts\start.ps1
$env:PAPER2_INTEGRATION = '1'
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
& .\scripts\shutdown.ps1
```

Services are currently down. Service-free runs skip actual-client cases; do not call those a live verification. Starting services alone does not reproduce a benchmark.

## Validate and regenerate

The README contains the complete 16-ID `analysis/phase4_analysis.py --runs ... --output <new directory>` command. `reviews/evidence/phase4_20261019_independent/final_analysis.json` records the exact command already executed. The script validates raw data, refuses an existing output directory, fails nonzero for invalid evidence, and selects capacity from eligible repetitions or returns null. Authoritative output is `reports/analysis/phase4_independent_final_20261019/`. Two regenerations are byte-identical and their CSV/SVG values were checked against raw rows/coordinates in `final_regeneration_verification.json`.

`raw_final_audit.json` separately computes actual issue-time DB/probe work, cache misses, QPC service timings, quotas/CPU/throttling, pool wait, sink/loop overhead and preservation. `final_buffer_probe.json` retains a query-local actual EXPLAIN ANALYZE BUFFERS. A new buffer probe requires fresh services and explicit `--run-id`/`--output`; existing outputs are refused. Cumulative pg_statio counts include preparation and asynchronous refresh and are not query-local IO measurements. Encoded byte reservations are not measured wire traffic; unknown actual bytes remain null.

## Failures, fixes and next boundary

ISSUE-0023/0024 corrected missing probe/pool/workload/stability/raw-inference obligations. ISSUE-0025 corrected query creation after expired acquisition, proven by an actual overload traceback and deterministic failing regression. Full replacement calibration/control/immediate/headroom runs link `p4final_* -> p4review_* -> original p4cal/p4exp IDs`. `evidence_register_final.json` overlays exclusions and corrected classifications without rewriting originals. The raw audit verified 535 historical files and 85 submitted archived source inputs unchanged. Original and first-review failures, unsuccessful diagnostic reproductions, tool/import mistakes and successful corrections remain disclosed.

The next boundary is a new user-authorized task. Any later policy work must retain common foreground/observer/pool/deadline/issuance semantics, charge observation within the DB budget and validate its actual mixed foreground/warm-up pool behavior. Different query costs, memory pressure, disk behavior, mutable data, multi-router operation and longer-run guarantees remain untested. Do not claim improvement from this baseline penalty alone.
