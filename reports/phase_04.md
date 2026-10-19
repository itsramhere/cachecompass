# Phase 04: Capacity calibration and immediate-expansion characterization

Updated: 2026-10-19T04:06:30Z
Status: complete
Gate: PASS after independent corrections, Phase 4 only

## Required outcome

Measure the actual constrained-query client/DB path, verify non-DB headroom, and establish an attributable reproducible expansion penalty or investigated negative characterization. No Phase 5 policy or controller improvement is part of this phase.

## Delivered and verified

The [independent review](reviews/phase_04_independent_20261019_0354.md) supersedes the original owner report, archived byte-for-byte at `reports/reviews/evidence/phase4_20261019_independent/original/phase_04.md`. It corrected common-probe accounting, separate observer pools, workload parameters, warm latency stability, fixed observation timing, raw validation/statistical analysis, evidence preservation and an expired-acquisition query orphan. All original and first-review measurements remain retained and are excluded from corrected confirmation.

Executed canonical source: `cda5257b9974cd72e8e99a5ab0a94dca462e02a241d505a056e93902589c03fa`, 88 inputs. Final README/Git attributes are publication-only changes with unchanged runtime/config/test/analysis bytes; `publication_source.json` and publication audit identify that delta. Config: `configs/phase4_review.yaml`; frozen rules: `docs/PHASE4_REVIEW_PROTOCOL.md`.

## Validation and results

| Check | Exact entry / evidence | Result |
| --- | --- | --- |
| Complete actual-client regression | `PAPER2_INTEGRATION=1`, `.venv/Scripts/python.exe -B -m unittest discover -s tests -p test_*.py -v`; `final_full_live_suite.json` | 107 tests, exit 0; 17 actual-client and 17 Phase 4 cases |
| Repeated actual-query calibration | `run_final_matrix.py`; `p4final_cal{12,24,36}_{1,2,3}_20261019` | 9 raw-valid runs, 12 s each; all offers retained, overload does not stop issuance |
| Matched expansion/control | `p4final_{control,immediate}_{1,2,3}_20261019` | 6 raw-valid physically reset runs; full initial states, relative schedules, settings and transition observer work match |
| Non-DB path profile | `p4final_headroom144_20261019` | 1,152/1,152 completed, zero violations/foreground DB work, at 4× intended application rate |
| Raw audit and preservation | `raw_final_audit.json` | 16/16 valid, 5,472 offers accounted; 535 historical files and 85 archived submitted inputs unchanged |
| Regenerate figures/tables twice | `finish_analysis.py`; `final_regeneration_verification.json` | Byte-identical analysis outputs, no CSV/raw or SVG coordinate/label mismatch |
| Query-local buffering diagnostic | `final_buffer_probe.json` | Actual 20,000-row CPU expression executes; shared hits 3, reads/temp IO 0 |

All command records are under `reports/reviews/evidence/phase4_20261019_independent/`; they retain argv, output, exit code, UTC, duration and source. The original negative checks fail as expected on archived inputs and pass against corrected inputs; failed tools/replays and their corrections are retained too.

At 24 foreground attempts/s with common probes enabled, all three runs issued/completed every offer, successful scheduled p95 was 45.1–62.0 ms, and all-offer violations were zero. This is a conditional empirical foreground rate, not physical peak capacity or an uncharged total C_safe. The 12-rps runs have 3/2/0 violations, and 36-rps runs have 356/352/329 violations with client pool queueing and some dispatch interference; all remain disclosed. See the review for budget-unit conversion and uncertainty limits.

Immediate cutover issued 26 additional foreground DB attempts in each fixed [3,5) transition window and increased paired p95 by 31.3/38.4/24.6 ms. Mean paired increase: 31.4 ms; range 24.6–38.4; exploratory df=2 t95 interval 14.2–48.7 ms, three independent pairs. Every transition has 58 destination read attempts and 27 cold misses, with coalescing explaining the smaller DB count. Controls have no cold misses/foreground DB work. The added miss-to-DB path explains the measured penalty; expansion itself does not saturate the DB. No controller-improvement or robust target-violation reduction is established.

## Issues, decisions and limitations

[ISSUE-0023](issues/ISSUE-0023.md), [ISSUE-0024](issues/ISSUE-0024.md), [ISSUE-0025](issues/ISSUE-0025.md) and DECISION-0013 document original evidence, diagnosis, fixes, reruns and exclusions. The actual deadline race required replacement of the entire first independent matrix, including favorable runs. No invalid evidence is reused under corrected claims.

Single-host/router, immutable small buffered dataset, CPU-heavy synthetic equal-cost query, coarse monotonic ticks, short horizons and n=3 repetitions limit generalization. Two overloaded calibration runs exceed the dispatch eligibility limit and do not establish physical DB capacity. PING/INFO/probe work, timer/cache throttling and one lost whole-run observation opportunity are disclosed; primary transition probe counts match exactly. Conservative reservations are not measured wire bytes. Literature full-text access ISSUE-0004 remains accepted.

## Gate and handoff

PASS for the bounded Phase 4 characterization: positive reproducible miss-path penalty, actual-client capacity operating point, measured headroom and investigated boundary interference. [Handoff](HANDOFF_PHASE4.md) gives runnable entry points and the exact stopping boundary. Services are down. Stop before Phase 5; no later policies, improvement claims, publication or commit/push were performed.
