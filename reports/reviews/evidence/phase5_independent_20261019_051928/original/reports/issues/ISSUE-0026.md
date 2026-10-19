# ISSUE-0026: Linux physical Redis TTL exceeds the immutable deadline

Opened: 2026-10-19 UTC
Phase: 5
Status: verified
Severity: high
Affected component: Redis expiry conversion inherited from Phase 3
Affected source: a659f23 plus initial Phase 5 work; source_before in final rerun
Affected evidence: reports/evidence/phase5/full_live_tests_v1.json

Expected: physical TTL never extends the registry's original monotonic expiry.
Observed: 1 failure in 124 checks, including 17 actual-client checks. The unchanged
12-iteration expiry check observed 712392145597 > 712391587530 ns, an excess
of 558067 ns. Services shut down after the failed suite. No tuning/comparison
run had executed. Supplemental mixed checks used no expiry and remain usable.

Reproduction: scripts/phase5_cycle.py --run-id p5live_tests_v1_20261019
--record reports/evidence/phase5/full_live_tests_v1.json --tests.
The retained child traceback is the original evidence; the wrapper exits 1.

Cause: the existing uncertainty allowance accounts for Python clock resolutions,
which are nanosecond-scale on Linux, but not Redis's millisecond-granularity
cached wall clock/PTTL. The original expiry envelope still protected application
returns; physical residency nevertheless violated the stricter contract.

Correction: include 1 ms Redis clock uncertainty in the shared write conversion,
subtract it before flooring PXAT, and propagate the tighter residency receipt.
No foreground/policy-specific path or test tolerance changed. A deterministic
high-resolution clock regression verifies the guard; the original live loop and
complete suite must pass before closure. This conservatively shortens TTLs.

Other retained initial harness failure: tests_initial.json reused a key across
separate scheduler passes and incorrectly expected its lifetime attempt total to
reset. tests_corrected.json creates a new scheduler for the zero-budget case;
17/17 focused checks passed. No runtime defect or experiment was hidden by that
harness correction.

Experimental impact: no-expiry mixed-pool checks unaffected; original failed
full suite retained. Final exact-source full live rerun and comparison matrix
will be linked here. No historical Phase 3/4 evidence is rewritten or recertified
for the new host by this correction.

## Final verification

full_live_tests_v2.json: 125/125 checks pass including the unchanged twelve-loop
physical TTL check and all17 actual-client cases. full_live_tests_final.json:
134/134 pass, same exact final source before/after, all17 actual-client cases,
no skips, verified shutdown. The deterministic high-resolution clock guard also
passes. Final source SHA256 is 796910788bedc489fc047e656ebc5b3115926d899bc28df4c1b740644784613e.
The unrelated execution-review outage does not invalidate these executed checks.
