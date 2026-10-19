# ISSUE-0031: Measurement horizon and failure classification

Opened: 2026-10-19T05:19:29.727720+00:00
Phase: 5 independent review
Status: verified
Severity: high
Affected submitted source: 796910788bedc489fc047e656ebc5b3115926d899bc28df4c1b740644784613e at Git a659f237c1f2940d83b714814e0bbf458f009c5d plus uncommitted owner work.
Scope: Sampler shutdown follows request drain; all service failures labeled invalid_measurement; phase5.py

## Original evidence and reproduction

reports/reviews/evidence/phase5_independent_20261019_051928/submitted_negatives.json records the exact command,
stdout/stderr, exit1 and fourteen assertion failures without harness errors.
The newly authored harness is archived as submitted_negative_harness.py;
all 100 submitted inputs and living reports/issues are archived under original/.
No original evidence is overwritten. All old tuning/comparison cases require
fresh review-qualified replacements; the unavailable v2 matrix never ran.

## Expected behavior

Follow docs/PHASE2_EXECUTION_CONTRACT.md exactly: common source/pools/limits,
causal fresh observations, finite generation-safe grants, issued-only retry
accounting, truthful actions/outcomes and independently validated matched runs.
Invalid or missing signals cannot be safety; aggregate flags are not evidence.

## Debugging

Read actual code and retained raw records. Reproduced targeted negative behavior
before correction. Specific fixes, original rerun and raw/live verification will
be appended after execution. No performance-ranking criterion is introduced.

## Experimental impact

Preserve every existing run and failure. Existing raw accounting success is not
certification of algorithms or capacity. Corrected Phase5 evidence must include
all six controls with common physical resets/schedules and a finite protocol
registered before new tuning. No Phase6 implementation or superiority claim.

## Resolution implemented; verification in progress

The sampler has its own fixed horizon and independent stop task, so response
drain cannot extend observation generation. Service connection failures are
infrastructure_failure; instrumentation/runtime faults remain invalid_measurement.
Partial failure accounting is retained, and legitimate handover timeout/nonprogress
remains policy_failure with the full offered horizon.

Original negatives and both pre/post commands remain in the review evidence.
The frozen 157-test actual-client suite passes (23 live cases, no skips).
Final closure requires the complete registered corrected matrix and preservation
audit; it is not inferred from the test suite alone.

## Independent closure — 2026-10-19T06:13:08.042266+00:00

Verified for the bounded Phase5 gate by final158-test live suite (23 actual-client
cases), complete24-case p5ind_20261019_m3 matrix, six matched fresh smokes and
independent raw audit. Exact source: ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823.
Evidence: reports/reviews/evidence/phase5_independent_20261019_051928/live_lower_final.json and
final_raw_preservation_audit_corrected.json; reports/evidence/phase5/p5ind_20261019_m3/.
All earlier records/failures remain unchanged; the original v2 never launched.
Current environment execution succeeds and all disposable cycles stop. No
Phase6 implementation, commit, push or performance-superiority inference.
