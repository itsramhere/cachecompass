# ISSUE-0025: DB acquisition at an expired deadline creates an orphan query and stops issuance

Opened: 2026-10-19T03:43:00Z
Last updated: 2026-10-19T04:08:01Z
Phase: 4 independent review
Status: verified
Severity: high
Affected component: PostgreSQL adapter, calibration validity/status
Affected source/config: first independent matrix source `e452b05bc7b494575c89ff7094b9fe02138f01562f4534909c564c079a2c521f`; `configs/phase4_review.yaml`
Affected runs/artifacts: all first independent `p4review_*` confirmations are superseded by the complete `p4final_*` matrix; high-load run failures remain retained

## Expected and observed

An expired connection acquisition must issue no query, return the idle connection and release its permit. Once query work exists, expiration must enter bounded cancellation/cleanup and retain its accounting. Instead the three first independent 36-rps runs created work after an expired acquisition edge, quarantined it and stopped later issuance. They retained all 432 terminal offers but issued only 110, 322 and 382 foreground attempts, with 321, 44 and 10 RuntimeError failures respectively. Their prior completed labels were incorrect and are superseded by the review's exclusion map, without rewriting original bytes.

## Reproduction and debugging

1. Frozen matrix independently exposed the stop in all three high-load runs; lower-load and paired runs were retained separately.
2. `cleanup_diagnostic.json`: fresh instrumented 36-rps diagnostic issued/completed all 432 reads and did not reproduce the stop, while retaining 269 target violations. This is disclosed intermittent behavior, not elimination of the failure.
3. `cleanup_diagnostic48.json`: separate 48-rps diagnostic produced `cleanup_diagnostic_errors_r48.json`. Its first stopped exception points exactly to `_remaining_seconds(deadline_ns)` after creation of the query task; quarantined count is 1. This changes the diagnostic load, not the confirmation workload or acceptance criteria.
4. `expired_acquisition_before.json`: deterministic acquisition-edge regression reproduces the incorrect issuance stop with no services; exit 1, one assertion failure. No adverse process or host scheduling is required for the counterexample.

## Root cause and resolution

The adapter checked remaining time for pool acquisition, created a query task, and only then called the raising remaining-time helper for `asyncio.wait`. A coarse-tick expiry between those steps skipped discard/cleanup; the quarantine guard correctly refused unsafe permit reuse. Add a remaining-time check on the acquired idle connection before issuance/task creation. After a task exists, a nonpositive remaining duration enters a zero-time wait and bounded discard rather than raising outside cleanup. Keep all deadlines, query work, pools, resource quotas and safety refusal intact. Calibration independently checks issue deadlines and records exception messages. Pool summaries expose issuance stop/quarantine; the harness labels those infrastructure_failure and analysis rejects them as capacity evidence. Sampling is now stopped by its independent fixed horizon even if foreground drain continues.

## Verification and experimental impact

`expiry_corrected.json`: 17 focused checks pass, including the original deterministic race and explicit runtime-failure rejection. Complete actual-client regression and the entire repeated capacity/paired/headroom matrix are rerunning as `p4final_*`; every final run links its `p4review_*` predecessor. Because request issuance and observation timing changed, none of the first independent matrix is reused as corrected confirmation. Its valid-looking lower points and positive pairs remain historical diagnostics only. No selective replacement of only the failed condition.

## Remaining risk

Actual high-load confirmation is pending. Cancellation safety is not inferred from the deterministic fake alone. If actual cleanup still cannot be confirmed, preserve the infrastructure failure and leave the dependent capacity gate unmet. No Phase 5 policy or improvement is implemented.

## Final closure

Verified 2026-10-19T04:08:01Z. The final 107-check suite includes 17 actual-client tests and the deterministic expiry race. The entire affected matrix was repeated at the same rates/workload/quotas/deadlines as fresh `p4final_*` runs, all 16 raw-valid under source `cda5257b9974cd72e8e99a5ab0a94dca462e02a241d505a056e93902589c03fa`. None stopped issuance or retained quarantined work. At 36 rps, issued foreground attempts are 370/416/430; unissued timeouts 62/16/2 remain explicit expected overload, not hidden successful reads. Issued timeouts and cleanup/discards remain charged. DB CPU approaches its quota and pool waits persist, so the fix does not manufacture extra capacity or erase overload. Source, terminal accounting and exact outcomes are retained in `final_full_live_suite.json`, per-run manifests/results, `raw_final_audit.json` and the final analysis. Original first-review failures remain excluded with corrected classification overlays. Fresh archived replay `replay_expiry_corrected.json` reproduces the original failing race; it does not load the fixed adapter. Earlier pending paragraphs are historical milestones. No later-phase behavior was added.
