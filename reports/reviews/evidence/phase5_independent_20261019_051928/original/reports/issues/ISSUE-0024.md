# ISSUE-0024: Phase 4 validator accepts changed evidence and analysis hard-codes capacity

Opened: 2026-10-19T03:30:00Z
Last updated: 2026-10-19T04:08:01Z
Phase: 4 independent review
Status: verified
Severity: high
Affected component: Phase 4 raw validation, statistical inference and reporting
Affected source/config: submitted canonical SHA256 `55245c36c0ac5ae716f53c5e7a18f2e48f8ed74dc34955d5d3a85c6b0319761c`
Affected runs/artifacts: both `reports/analysis/phase4_confirmation*` and submitted Phase 4 gate/capacity interpretations

## Expected and observed

Inference must be derived from validated raw offers, outcomes, operations and repeated runs. The original validator accepted changed keys/scheduled times, nonterminal outcomes, duplicate offers, missing calibration probes and altered p95 summaries. It read aggregate results for all figures, included invalid entries, exited zero with invalid runs, assumed four-second runs and wrote C_safe=24 even for unrelated/missing inputs. Pairing depended on three literal original IDs. The report stated run ranges but no run-level uncertainty for its attribution claim.

## Reproduction, cause and fix

`submitted_negatives.json` contains six failing validator counterexamples and two workload errors against archived source; `corrected_negatives.json` verifies the linked nine-check correction, and `focused_expanded.json` verifies 15 checks including corrected-format missing-operation/probe-terminal/ownership/payload cases. Replace trust in summaries with schedule identity, terminal/chronology/leader accounting, raw operation/probe, initial-map/payload, horizon, warm-stability, source and artifact verification; recompute all metrics. Invalid/malformed/legacy evidence fails closed and exits nonzero. Capacity is selected from eligible same-source independent repetitions or remains null. Explicit pair IDs enable fresh runs; compare complete initial contents, source/config, normalized schedules and distinct Redis process identities. Report run/pair mean/range and exploratory df=2 t intervals without pooled-request replication.

## Verification and impact

Full live suite: `reports/reviews/evidence/phase4_20261019_independent/full_live_suite.json`, exit 0, 105 checks. Corrected raw regeneration and paired uncertainty await the frozen matrix. Original aggregates remain byte-preserved but cannot certify corrected claims. A positive penalty is not required; missing essential evidence leaves Phase 4 unmet. No controller-improvement inference is authorized.

## Final closure

Verified 2026-10-19T04:08:01Z. Final 107-check live suite passes. `raw_final_audit.json` validates all 16 replacement runs; `final_regeneration_verification.json` verifies two byte-identical outputs, CSV/raw values and SVG coordinates/labels. Paired run-level mean/range and exploratory n=3 t interval are regenerated, not inferred from pooled requests. `selected_c_safe_foreground_rps=24` is derived from the registered rule and explicitly distinguished from total budget/physical capacity; 12-rps tails and 36-rps dispatch/pool interference remain visible. `final_buffer_probe.json` verifies the same-query EXPLAIN buffer evidence. The buffer CLI now requires fresh explicit output/run IDs rather than overwriting original probe evidence; cumulative pg_statio is not over-attributed. Archived-source replays reproduce the original six failures/two errors and the acquisition race; the first expiry replay's import mistake and correction remain retained. Original/first-review exclusions and exact replacements are in `evidence_register_final.json`. Final gate/limits are in the independent review; no controller claim follows.
