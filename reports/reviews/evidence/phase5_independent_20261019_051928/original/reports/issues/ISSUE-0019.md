# ISSUE-0019: Shared cache pools, incomplete sampling and coarse clocks violate runtime contracts

Opened: 2026-10-18T21:14:07Z
Last updated: 2026-10-18T22:08:25.778452+00:00
Phase: 3 independent review
Status: verified
Severity: high
Affected component: Redis/PostgreSQL adapters / observation / expiry
Affected source/config: submitted Phase 3 SHA256 69b5d9776b9291a335c279265fa7cba882c60a771f276bc0fd777c728486aaa2
Affected runs/artifacts: submitted Phase 3 gate and smoke claims; historical evidence retained

## Expected behavior

Separate foreground/background permits; bounded pool waits and cleanup; no implicit retries; preserved original expiry; charged fixed PING/INFO/DB rounds while idle or paused.

## Observed behavior and original evidence

The submission combines foreground/background cache quotas, issues PING plus three INFO calls while charging two operations, and samples only after handover. expanded_live_checks.json reproduces an 8 ms donor expiry extension despite the earlier TTL fix (seven of eight cases passed).

Original runtime is archived under [original](../reviews/evidence/phase3_20261019_independent/original/). The corrected [negative harness record](../reviews/evidence/phase3_20261019_independent/negatives_before_corrected_harness.json) ran ten tests, exit 1, ten failures. The first harness record retains two test-author mistakes and is not the corrected reproduction. Existing 53 service-free tests were insufficient proof of these paths.

## Minimal reproduction

Run `.venv/Scripts/python.exe -B -m unittest tests.test_phase3_independent -v` against the archived submitted runtime. For adapters, start pinned disposable services and set `PAPER2_INTEGRATION=1`, then execute `tests.test_phase3_integration`. Exact commands, timestamps, outputs and source fingerprints are in the independent evidence directory. Reproduction outcome: reproduced as described; static omissions are identified separately from executed failures.

## Root cause and resolution

Add separate pools and permit deadlines, zero Redis retries, finite PostgreSQL cancel/drain/discard, and periodic no-overlap sampling independent of migration grants. Store original monotonic expiry in a 12-byte envelope; cap reconstructed expiry, subtract clock-resolution uncertainty, and refuse unsafe short TTL writes. Eviction and observed misses invalidate destination residency. Bound overflow buckets and align complete demand windows to run origin.

## Debugging and verification

`integration_intermediate.json` preserves a review-introduced Windows Selector socket-close failure; `integration_cleanup_corrected.json` verifies drain before discard. `expanded_live_ttl_corrected.json` and `live_races_expanded.json` pass TTL, actual shared-fill deadline, replacement backend PID, idle sampling and pool separation checks. Final expanded checks remain pending. All named records are under `reports/reviews/evidence/phase3_20261019_independent/`. The issue's final closure will link exact-source reruns. Original failures remain retained.

## Experimental impact and remaining scope

The submitted gate claim is superseded; prior smoke runs remain historical diagnostics and do not certify corrected behavior. No scientific performance result or Phase 4 calibration exists. Single-router immutable reads and single-host process-lifetime expiry remain the supported architecture. SQL/full driver-encoded bytes are null when unknown. Exact allocator/LRU equivalence, calibrated thresholds and performance remain later measurements. See DECISION-0011 and the normative execution-contract clarification; later policies must share the corrected mechanisms.

## Final verification and closure

Verified 2026-10-18T22:08:25.778452+00:00. Final exact source `8454ae425d5546a546d59e1b7b2258b4ec1c844eebb35e2609f7a4ab98e15c19` passed `tests_publication.json` (90 checks including 17 actual-client), `publication_cycle.json` / `publication_pair_validation.json` (39 checks, two recreated-cache expansions) and `expected_failure_publication.json` (all offers/issued work retained on policy failure). All records live under `reports/reviews/evidence/phase3_20261019_independent/`. The late failed-cancel reproduction is retained in `cancel_unresponsive_before.json`, with `cancel_unresponsive_corrected.json` and the complete suite verifying bounded drain/discard and replacement. Source/encoding/interface/accounting corrections and limits are recorded in the independent review and DECISION-0011. Earlier pending-verification paragraphs above are historical milestones, superseded by this closure.
