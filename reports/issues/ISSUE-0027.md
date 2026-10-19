# ISSUE-0027: Old-grant timeout incorrectly terminates a key under a live replacement

Opened: 2026-10-19 UTC
Phase: 5
Status: verified
Severity: high
Component: common migration source/destination token wait renewal
Affected source: all initial p5matrix_v1_20261019 warming runs

Expected: unissued work renews its reservation under the latest grant, preserving
the original finite task deadline. Expiring an old interval must not terminate
a key while its replacement permits progress. No new budget or issued refunds.

Observed: each initial warming smoke has one `not_warmed` key, zero issued
attempts, reason task_or_grant_deadline_expired, despite otherwise completing
122 of 123 copies. Audit inspection of `_source_slot`/`_destination_slot` found
they checked only current grant validity after token timeout. A replacement
could already be valid, causing the old timeout to escape instead of renewal.

Evidence: `reports/evidence/phase5/grant_boundary_before.json`, exit 1, both
source and destination deterministic checks raise the erroneous TimeoutError.
The negative injects replacement during the original acquire and leaves a live
500 ms key deadline; the second acquire would succeed. Original matrix raw
records, selections and smokes remain unmodified.

Correction: capture the generation used by each token wait. On timeout, renew
when that generation was replaced OR the grant expired, provided the ORIGINAL
key deadline remains. No issued-token refunds, new passes or deadline extension.
Both source and destination paths share the same correction.

Experimental impact: exclude the entire v1 matrix as superseded implementation
evidence. Repeat the identical bounded grid/fresh smoke/boundaries with v2 IDs
and linked retry_of, under registered protocol Amendment 1. Mixed-pool checks
never exercise migration grants and remain applicable. No superiority claim
was made or required. Raw v1 accounting validation remains distinct from
algorithmic validity; a validator PASS did not certify the renewal algorithm.

Verification pending: grant_boundary_corrected.json, complete final live suite,
all replacement raw validations, no premature unissued terminal in feasible
replacement warming cases, and actual constrained/deadline terminal accounting.

## Corrected deterministic/live suite evidence

Both renewal negatives pass in grant_boundary_corrected.json. The final full
live suite passes 134 checks including17 actual-client tests under unchanged
source796910788bedc489fc047e656ebc5b3115926d899bc28df4c1b740644784613e.
Actual corrected policy matrix verification remains blocked by ISSUE-0028; do
not close this issue or certify the Phase5 gate from these checks alone.

## Independent closure — 2026-10-19T06:13:08.042266+00:00

Verified for the bounded Phase5 gate by final158-test live suite (23 actual-client
cases), complete24-case p5ind_20261019_m3 matrix, six matched fresh smokes and
independent raw audit. Exact source: ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823.
Evidence: reports/reviews/evidence/phase5_independent_20261019_051928/live_lower_final.json and
final_raw_preservation_audit_corrected.json; reports/evidence/phase5/p5ind_20261019_m3/.
All earlier records/failures remain unchanged; the original v2 never launched.
Current environment execution succeeds and all disposable cycles stop. No
Phase6 implementation, commit, push or performance-superiority inference.
