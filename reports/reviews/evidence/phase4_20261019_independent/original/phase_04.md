# Phase 04: Calibrate capacity and reproduce the expansion penalty

Started: 2026-10-19T02:43:00Z
Updated/completed: 2026-10-19T03:08:00Z
Status: complete

## Required outcome

Calibrate actual PostgreSQL capacity for the measured query mix and reproduce immediate-cache-expansion cold misses, additional DB work, and a latency penalty without implementing Phase 5 controls or Phase 6 adaptation.

## Delivered

- `src/cache_scaleout/phase4.py` and `configs/phase4_calibration.yaml`: actual-client calibration and immediate-cutover harness. It records offered/submitted/issued/completed stages, raw schedules, request records, operations, observations, state and resource summaries.
- `scripts/phase4_run.ps1`: physically recreates the labelled disposable project before every measurement and shuts it down afterwards.
- `analysis/phase4_analysis.py`: validates raw terminal accounting and regenerates CSV, SVG figures and the machine-readable calibration record.
- `docs/PHASE4_CONFIRMATION_PROTOCOL.md` and `docs/PHASE4_METHODOLOGY.md`: frozen confirmation protocol and measurement boundaries.
- `reports/analysis/phase4_confirmation_final/`: raw-data validation, calibration curve, `calibration_record.json`, expansion table and figures.

## Findings

For the 512x1 KiB immutable dataset, 20,000-round PostgreSQL query mix, one-CPU/512 MiB PostgreSQL container, four foreground DB connections, and the provisional 100 ms target, the confirmed DB curve was:

| Offered DB rps | Runs | p95 range (ms) | All-offer violations | Interpretation |
| ---: | ---: | ---: | ---: | --- |
| 12 | 3 | 55.8--56.7 | 1 / 144 | below knee but one scheduling/tail violation |
| 24 | 3 | 48.1--52.3 | 0 / 288 | selected `C_safe` |
| 36 | 3 | 79.1--511.8 | 260 / 432 | unstable knee; two overloaded replications, one benign replication retained |

`C_safe=24` reads/s is conservative only by the stated rule: highest repeated rate with all offers submitted/issued, p95 below 100 ms and no violations in all three runs. It must not be applied to other query costs, host contention, pool settings, object sizes, Redis limits, or deployments.

Matched 36-rps control/immediate transition windows had p95 pairs of 30.4 -> 55.9 ms, 28.3 -> 56.7 ms, and 27.2 -> 50.2 ms (deltas +25.5, +28.4, +23.1 ms). Each control issued zero foreground DB reads; each immediate condition issued 25 in the 2-second transition window after atomic remapping to the empty destination. New-cache reads were 31/31/32; one immediate run had one of 72 transition offers exceed 100 ms. The 5--8.5 second post-event window retained 29 DB attempts and p95 44.4--51.0 ms because on-demand cache filling continued. This is an attributable expansion penalty, not evidence of an improvement.

The matched cached controls submitted/completed every offer and had 27.2--30.4 ms transition p95 with no DB work. Redis used roughly 1.6 MiB on each old instance under the 32 MiB limit and reported zero evictions. The PostgreSQL buffer probe reported a 606,208-byte relation, 734 heap hits and zero heap reads after 96 same-mix reads. Therefore this is a CPU/query and scheduling characterization; low DB CPU alone was not used to infer spare capacity, and the result does not establish disk-IO behavior.

## Validation

| Check | Exact command/config/run ID | Outcome | Evidence |
| --- | --- | --- | --- |
| Raw confirmation validation/analysis | `python -B analysis/phase4_analysis.py --runs <15 confirmation IDs> --output reports/analysis/phase4_confirmation_final` | 15/15 valid; all offered IDs reconciled | `reports/analysis/phase4_confirmation_final/validation.json` |
| DB confirmation curve | `scripts/phase4_run.ps1 -Mode calibrate -RunId p4cal_confirm_r{12,24,36}_{1,2,3} -Rate <rate>` | 9 completed independent runs | `runs/p4cal_confirm_*` |
| Matched expansion confirmation | `scripts/phase4_run.ps1 -Mode immediate -RunId p4exp_confirm_{control,immediate}_{1,2,3} -Rate 36 -Condition <condition>` | 6 completed physically reset runs | `runs/p4exp_confirm_*` |
| Actual-client regression after SQL compatibility fix | `PAPER2_INTEGRATION=1 python -B -m unittest tests.test_phase3_integration -v` | exit 0; 17 checks | `reports/evidence/phase4/actual_client_integration_rerun.json` |
| Full local regression | `python -B -m unittest discover -s tests -p 'test_*.py' -v` | exit 0; 73 passed, 17 integration tests skipped because services were intentionally down | retained command output in Phase 4 handoff |
| PostgreSQL/Redis residency probe | `python -B scripts/phase4_buffer_probe.py` under fresh services | relation 606,208 bytes; 734 hits / 0 reads; Redis empty before preparation | `reports/evidence/phase4/buffer_probe.json` |

## Errors encountered and debugging

| Issue | Symptom | Root cause/status | Fix or remaining action | Verification |
| --- | --- | --- | --- | --- |
| [ISSUE-0021](issues/ISSUE-0021.md) | early pilot schedules stale; first immediate run crashed | origin before provenance work and Zipf scalar/list bug; verified | origin moved after preparation; corrected CDF | corrected pilots and confirmation runs |
| [ISSUE-0022](issues/ISSUE-0022.md) | Phase 3 actual-client default query returned no row | zero-length SQL series erased cross-join row; verified | `GREATEST(rounds,1)` compatibility path | 17 actual-client tests passed on linked rerun |

## Decisions and deviations

DECISION-0012 selected measured SQL CPU work rather than fabricated sleeps and froze the 3x3 calibration plus 3-pair expansion matrix before confirmation. Early 1,200-round pilots, the pre-origin pilots, and failed first immediate run remain under `runs/` and are excluded from confirmation analysis. No retry replaced them.

## Gate assessment

Pass. The baseline penalty is measurable and attributable: empty-destination remapping creates cold misses and 25 extra foreground DB reads per transition window, with all three paired transition p95 values 23--28 ms worse than controls. The effect is below the provisional 100 ms target in most expansion offers, so Phase 4 supports characterization of a transient degradation, not a claim that a future controller improves the target-violation rate. The high 36-rps run-to-run variation is a material limit.

## Next phase handoff

Phase 5 may implement only the documented strong baseline suite behind the same Phase 4 foreground path. Reuse `C_safe=24` only within its stated applicability and retain 36-rps as the overload boundary. Do not alter the frozen Phase 4 confirmation evidence. Services are shut down; start with `scripts/phase4_run.ps1` or `scripts/start.ps1` as appropriate.
