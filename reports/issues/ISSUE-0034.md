# ISSUE-0034: Token events used a later clock than their balance changes

Opened: 2026-10-19T05:53:00Z
Phase: 5 independent review
Status: verified
Severity: high
Affected component: migration.TokenBuckets runtime and measurement
Affected source: first-review 4e0941ac925840fe6e52b14d89163be562a11d944e8bee84887dabcde756a899
Affected cases: complete first-review p5ind_20261019_m1 matrix excluded

## Expected and observed

Token acquisition, return and rate-change records must identify the same
monotonic balance-change boundary used by enforcement. Independent replay of
warmup_only_adaptation tune4A found destination deficits -5.273550848 and
-2.629566464 reserved bytes, equivalently -0.002574976 and -0.001283968 operation
credit. Its process/status said completed; the independent validator rejected it
and stopped the matrix. Aggregate completion was not accepted as proof.

## Original evidence and reproduction

Continuation command, failed validation, raw tune4A, and token_replay_diagnostic.json
are preserved under reports/reviews/evidence/phase5_independent_20261019_051928/
and reports/evidence/phase5/p5ind_20261019_m1_continuation1/. No original bytes
changed. The diagnostic gives exact event IDs/times/dimensions and deficits.
A fresh advancing-clock unit counterexample (test_phase5_token_clock.py) fails
before correction: 0.2 token balance versus 0.1 from the recorded rate start.
Exact command/output: token_clock_before.json; harness archived separately.

## Root cause and resolution

refill() sampled a clock and updated balances, while _event() sampled a later
clock. A new rate could accrue using the earlier updated timestamp although
its event declared a later start. Acquire/return logs similarly shifted their
linearization point, producing burst replay disagreement. This is a runtime/
measurement defect, not legitimate constrained policy behavior.

Use the same sampled balance timestamp for init, rate, acquisition and return
events. Event IDs, operation links, empty-start accounting and burst limits are
unchanged. The clock regression now passes (token_clock_corrected.json). No
replay tolerance, resource bound or assertion is weakened. Additional raw replay
also checks the known-estimator flag and old-owner lower credit from actual
issued foreground work, rather than trusting observation fields.

## Experimental impact and verification

The protocol's finite replacement amendment precedes new runs. Archive final
107 inputs and repeat all two mixed checks, 12 tuning, six fresh smokes and four
boundaries under one stable corrected runtime. Keep all 12 earlier review cases
(including the interrupted lifecycle case) and failures; do not reuse favorable
cells or their capacity evidence. Maximum 24 replacement cases, 36 review
measurements total. Final live suite passes 158 tests, 23 actual-client cases,
no skips; final_source.json and live_final.json identify the exact runtime.
Closure awaits the full p5ind_20261019_m2 matrix, raw/adversarial/preservation
checks and disposal. No Phase6 implementation or performance-improvement claim.

## Independent closure — 2026-10-19T06:13:08.042266+00:00

Verified for the bounded Phase5 gate by final158-test live suite (23 actual-client
cases), complete24-case p5ind_20261019_m3 matrix, six matched fresh smokes and
independent raw audit. Exact source: ea3f004a19f79d96b4361e523ab969a5ad13f65faa87348d057b02cbce234823.
Evidence: reports/reviews/evidence/phase5_independent_20261019_051928/live_lower_final.json and
final_raw_preservation_audit_corrected.json; reports/evidence/phase5/p5ind_20261019_m3/.
All earlier records/failures remain unchanged; the original v2 never launched.
Current environment execution succeeds and all disposable cycles stop. No
Phase6 implementation, commit, push or performance-superiority inference.
