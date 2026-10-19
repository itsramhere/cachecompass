# ISSUE-0033: Outer command recorder interrupted the finite matrix

Opened: 2026-10-19T05:48:00Z
Phase: 5 independent review
Status: verified
Severity: medium
Affected component: review orchestration, not policy runtime
Affected source: canonical 4e0941ac925840fe6e52b14d89163be562a11d944e8bee84887dabcde756a899
Affected evidence: p5ind_20261019_m1; matrix_command.json

## Expected versus observed

The 23-case protocol allows up to 35 minutes and individual 90-second children.
The generic scripts/record_command.py silently supplies a 180-second overall
watchdog. Calling the full matrix through it killed its parent after eight
complete, validated and disposed cases. The ninth child tune3A finished/sealed
its measurement after parent termination; parent exit/shutdown capture is absent.
No policy defect or resource-constrained outcome is inferred from that timeout.

## Original evidence and diagnosis

reports/reviews/evidence/phase5_independent_20261019_051928/matrix_command.json
retains argv, timestamps and TimeoutExpired. Existing eight command records and
progress/registration files are unchanged. Read the recorder source to identify
the hard-coded 180-second limit. Label-verified explicit cleanup then removed
only disposable paper2-research services and volumes; exact commands and empty
container listing are in interrupted_matrix_shutdown.json.

## Resolution and finite amendment

The review's orchestration_amendment.md precedes continuation. Retain/revalidate
the eight complete cases; exclude tune3A from tuning despite its completed raw
status because its lifecycle command record is incomplete; execute one linked
tune3A_r1 and the fourteen never-started cells. Maximum 24 total measurements,
23 eligible. No new tuning points or changed criteria. No runtime/config/analysis
source mutation. continue_matrix.py is an explicit captured copy of the matrix
logic plus resumption, hashed in continuation_driver_sha256.json. It refuses
existing continuation outputs, validates source/shutdown before reusing cases,
and uses the unchanged 90-second per-case cycle. Outer capture now allows 2100 s.

## Verification and impact

Continuation pending in p5ind_20261019_m1_continuation1. All original records and
the interrupted measurement remain immutable; source identity remains frozen.
This is an orchestration failure, not a negative performance result. Direct
reproduction uses scripts/phase5_matrix.py, not the short generic recorder.
Closure requires complete raw/matched verification, source identity and shutdown.

## Independent closure — 2026-10-19T06:13:08.042266+00:00

Verified for the bounded Phase5 gate by final158-test live suite (23 actual-client
cases), complete24-case p5ind_20261019_m3 matrix, six matched fresh smokes and
independent raw audit. Exact source: ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823.
Evidence: reports/reviews/evidence/phase5_independent_20261019_051928/live_lower_final.json and
final_raw_preservation_audit_corrected.json; reports/evidence/phase5/p5ind_20261019_m3/.
All earlier records/failures remain unchanged; the original v2 never launched.
Current environment execution succeeds and all disposable cycles stop. No
Phase6 implementation, commit, push or performance-superiority inference.
