# Phase 05: Implement strong baselines

Started: 2026-10-19 UTC. Verified: 2026-10-19T06:13:08.042266+00:00.
Status: complete. **Gate PASS after independent corrections. Stop before Phase6.**

## Required outcome and delivered work

All six required controls execute through the same actual cache-aside path,
pools/retries/expiry/cleanup/observations/limits. Immediate has no migration;
fixed and adaptive-budget migration controls use one finite pass and atomic
final cutover; fixed gradual, warmup-only and traffic-only differ only in their
documented control dimensions. No joint candidate is implemented.

Runtime fixes cover complete/fresh pressure provenance, contiguous known
estimators, truthful staged installation, generation-safe tokens/retries,
linearized token clocks, fixed sampling horizon and explicit failure records.
Raw analysis replays actual operations, grants, bursts, bytes, payload/residency,
route/admission/terminal outcomes and common configuration. Fair shared A/B
selection preserves fixed components. Source and all findings/severity/file
references: [phase_05_independent_20261019_051928.md](reviews/phase_05_independent_20261019_051928.md).

Measured source `ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823` (107 inputs); publication source `d74ef2e7b58c2e002fdb007fae796befd47e4dbd0256722c6e4989ad7854fd9e`.
Only `analysis/phase5_validation.py` changes after measurement, to classify
failed probe prefixes correctly; all runtime/configuration/tuning/measurement
inputs are unchanged. Both identities and archives are in `reports/reviews/evidence/phase5_independent_20261019_051928/`.


## Validation

| Check | Exact record | Outcome |
| --- | --- | --- |
| Live regression | `reports/reviews/evidence/phase5_independent_20261019_051928/live_lower_final.json` |158 pass,23 actual-client cases, no skips, source unchanged |
| Corrected mixed operating point | `reports/evidence/phase5/p5ind_20261019_m3/mixed8_2_validation.json`, `mixed6_4_validation.json` | Both pass; conditional total12 including2/s probes, reserve2 |
| Fair pilot and fresh smoke | `reports/evidence/phase5/p5ind_20261019_m3/selections.json`, `matched_smoke.json`, `complete.json` |12 equally allocated pilot cases; common B; all6 fresh matched controls complete |
| Feasible/constrained cases | Four `boundary_*` cases in complete.json | Both migration controls cut over123 explicit cold keys; deadline/nonprogress remain policy_failure |
| Independent final replay | `reports/reviews/evidence/phase5_independent_20261019_051928/final_raw_preservation_audit_corrected.json` |24 qualified runs,7,684 offers,886 DB attempts,480 DB probes,2,880 cache probes |
| Resealed and failed-bundle checks | `schema6_final_resealed_checks.json`, `failed_probe_corrected.json` |16+3 checks pass; fabricated/missing successful work still rejects |
| Actual failed probes | `live_probe_failure.json` | Real PING timeout/zero-issued DB wait produce UNKNOWN; separate diagnostic, services down |
| Reader-only regression | `post_analysis_regressions.json` |135 executed pass,23 live skips; no changed runtime |

Exact matrix command is recorded in lower_replacement_command.json and the
review. Every child records argv/output/source/config/reset/final shutdown.

## Errors, deviations and retained outcomes

ISSUE-0029–0032 correct pressure, action/grant/retry, horizon, validator and tuning
faults demonstrated by14 original assertion failures and2 selection failures.
ISSUE-0033 records the outer180s watchdog and incomplete child; ISSUE-0034 records
the token-clock defect caught by raw replay and its advancing-clock negative.
ISSUE-0035 retains the valid16/s operating-point rejection (52.376628ms dispatch
>50ms); a single registered lower12 choice passes unchanged criteria. ISSUE-0036
corrects failed-probe reader classification after measurement with unchanged
runtime/results. All originals, intermediate sources and failures remain.
The full owner and first-review comparisons are superseded, not selectively reused.

DECISION-0017/0018/0019 and docs/PHASE5_INDEPENDENT_PROTOCOL.md define finite
replacement, unchanged tuning ranges, common-profile selection and lower operating
point before their runs. No assertions/tolerances are weakened. An audit harness
sum-order mismatch is retained and corrected without changing selection.
No later final evaluation or superiority claim is inferred. Capacity remains
query/pool/probe/host specific; Phase4 proved no DB saturation. Unknown wire bytes
remain null. Immutable single-host/no-expiry comparison limits remain.

## Gate and handoff

PASS for bounded Phase5 only. [Independent review](reviews/phase_05_independent_20261019_051928.md)
and [handoff](HANDOFF_PHASE5.md) carry source identity, reproduction, preservation,
remaining accepted limitations and the stop boundary. No Phase6, commit or push.
