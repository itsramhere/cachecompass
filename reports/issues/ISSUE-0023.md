# ISSUE-0023: Phase 4 query/probe/pool/workload accounting does not support the submitted capacity comparison

Opened: 2026-10-19T03:30:00Z
Last updated: 2026-10-19T04:08:01Z
Phase: 4 independent review
Status: verified
Severity: high
Affected component: Phase 4 harness, initial stability, telemetry and workload
Affected source/config: submitted canonical SHA256 `55245c36c0ac5ae716f53c5e7a18f2e48f8ed74dc34955d5d3a85c6b0319761c`
Affected runs/artifacts: all `p4cal_*`, `p4exp_*` under the submitted protocol; original analyses/claims are superseded, not erased

## Expected and observed

Capacity calibration and expansion must execute the same bounded observation/query overhead, preserve complete individual accounting, use separate declared foreground/background pools, and implement the configured workload. Instead calibration had no common probes; expansion sampled Redis through foreground pools and discarded individual probe ledgers. The workload fixed an 80% branch and hard-coded Zipf 1.15 while accepting other values. The sequential zero-miss warm prefix did not measure latency stability. Measurement ended when responses finished rather than at the fixed horizon. Raw original schedules do reconcile, so omission of application offers is not the observed defect.

## Original evidence and reproduction

Byte-identical submitted inputs are archived at `reports/reviews/evidence/phase4_20261019_independent/original/` with `submitted_identity.json`. `submitted_raw_audit.json` audits every original pilot and confirmation, including missing artifacts in the failed pilot. `submitted_negatives.json` executes the archived code/analysis: 9 checks, six assertion failures and two workload errors; one denominator test passes. This records exact argv/outputs/status. Static missing-pool/probe paths are distinguished from those executed counterexamples.

## Debugging and resolution

The pilot at 24 DB rps with common probes and longer observations completed with zero target violations. The corrected immediate pilot returned every correct payload and reconciled all offers, 52 foreground DB attempts and 18 observation attempts. These are pilots, not confirmations. Use exact rounded stratum counts and configured Zipf exponent; distinct physical cache observer pools; all individual probe/foreground operations; full initial and authoritative payload verification; prespecified hit/latency warm windows; fixed horizon; process/QPC/metric-queue and cgroup/actual-limit measurements. Direct calibration uses the common one-attempt DB query semantics and separately prepares four connections. The batch changes are necessary because calibration, initial stability and overhead must be corrected together before any comparison can be reused.

## Verification and experimental impact

`preconfirmation_suite.json`: 15 focused checks pass. `full_live_suite.json`: 105 tests, including 17 live actual-client tests, exit 0. Every submitted confirmation is excluded from corrected inference, even where the default exponent happened to equal the hard-coded value. Fresh `p4review_cal{12,24,36}_{1,2,3}_20261019` and `p4review_{control,immediate}_{1,2,3}_20261019` explicitly link original IDs. `run_matrix.py` freezes order/rates and retains every outcome. Final measurement verification pending. No later policy or original data is modified.

## Remaining limits

Single host, coarse monotonic ticks, artificial CPU-heavy buffered query, duration-limited calibration and three independent deterministic-workload repetitions. Conservative byte reservations are not actual wire bytes. A corrected implementation alone does not establish a passing scientific gate.

## Final closure

Verified 2026-10-19T04:08:01Z. The entire first independent matrix was subsequently superseded after ISSUE-0025; no favorable run was reused. Exact-source `cda5257b9974cd72e8e99a5ab0a94dca462e02a241d505a056e93902589c03fa` passed 107 checks, including 17 actual-client and 17 Phase 4 cases. All 16 `p4final_*` runs pass `raw_final_audit.json` and final analysis, with all 5,472 offers/terminal identities and foreground/probe work reconciled. Each primary transition has four DB probes and eight cache probe commands/node in both conditions; one whole-run observation difference is disclosed. Corrected query-mix/stability/accounting confirmation replaces the original and first-review measurements through explicit `retry_of` chains and `evidence_register_final.json`. Two table/figure regenerations match bytes and raw values. Evidence directory: `reports/reviews/evidence/phase4_20261019_independent/`. Earlier pending paragraphs are retained milestones, superseded by this closure and the independent final review.
