# ISSUE-0036: Validator demanded operations that a failed probe never issued

Opened/verified: 2026-10-19T06:13:08.042266+00:00
Phase: 5 independent review
Status: verified
Severity: high for failure classification
Affected component: analysis/phase5_validation.py:26,56
Affected measured source: ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823
Publication reader source: d74ef2e7b58c2e002fdb007fae796befd47e4dbd0256722c6e4989ad7854fd9e

The flat per-round DB1/cache2 count rejected a legitimate UNKNOWN bundle when a
PING timed out before INFO, or a DB permit wait expired before any query issued.
Two fresh raw counterexamples fail before correction, while the missing-INFO
successful-bundle negative correctly rejects (failed_probe_before.json).

Replace flat counts with exact per-round deadlines, issued-prefix chronology,
explicit raw failure provenance and UNKNOWN state. Successful bundles still
require every PING/INFO/query with completed outcomes; missing successful work
still rejects. No invented unissued charge, relaxed limit or tolerance. All
three checks pass in failed_probe_corrected.json. Sixteen final resealed-record
checks pass; the service-free135 executed regressions pass (23 live skips).

A separate actual-client diagnostic obtains a real issued PING timeout using an
explicit120ms disposable-only CLIENT PAUSE, and a zero-issued DB timeout under
its held background permit. Both return UNKNOWN with the exact legal issued
prefix. Raw actual operations/admin command and verified shutdown are in
live_probe_failure.json; no comparison receives that diagnostic privilege.

This is a reader-only post-matrix correction. All24 qualified measurement
bundles succeeded and their results/selection are unchanged. Every runtime,
configuration, protocol, test and other analysis input remains byte-identical
to the measured archive; only this reader file differs. Thus revalidate all24
records and adversarial cases, rather than repeat unchanged physical executions.
The publication identity/delta is explicit; no later source is claimed measured.

Final audit first found an unrelated audit-harness exact floating sum mismatch
(21.515604776000004 versus21.515604776) because sorted JSON policy order differed
from registered run order. Preserve final_audit_command.json/its script/output;
the corrected independent harness uses run order, retaining exact assertions
and unchanged profile B. final_audit_corrected_command.json passes every check.
