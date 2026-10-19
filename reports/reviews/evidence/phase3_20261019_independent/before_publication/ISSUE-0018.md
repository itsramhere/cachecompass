# ISSUE-0018: Migration faults strand workers and stale reservations mint grant credit

Opened: 2026-10-18T21:14:07Z
Last updated: 2026-10-18T22:08:25.778452+00:00
Phase: 3 independent review
Status: verified
Severity: high
Affected component: migration scheduler / resource enforcement
Affected source/config: submitted Phase 3 SHA256 69b5d9776b9291a335c279265fa7cba882c60a771f276bc0fd777c728486aaa2
Affected runs/artifacts: submitted Phase 3 gate and smoke claims; historical evidence retained

## Expected behavior

Faults and cancellation drain finite workers; no expired/stale reservation can issue or credit a new grant; empty-start rate/burst tokens bound work independently of interval maxima.

## Observed behavior and original evidence

Wrong-payload workers strand queue.join; cancellation leaves donor IO active; releasing an old reservation credits a replacement zero grant; destination IO issues after expiry. The submitted runtime has no token enforcer and charges payload length as encoded bytes.

Original runtime is archived under [original](../reviews/evidence/phase3_20261019_independent/original/). The corrected [negative harness record](../reviews/evidence/phase3_20261019_independent/negatives_before_corrected_harness.json) ran ten tests, exit 1, ten failures. The first harness record retains two test-author mistakes and is not the corrected reproduction. Existing 53 service-free tests were insufficient proof of these paths.

## Minimal reproduction

Run `.venv/Scripts/python.exe -B -m unittest tests.test_phase3_independent -v` against the archived submitted runtime. For adapters, start pinned disposable services and set `PAPER2_INTEGRATION=1`, then execute `tests.test_phase3_integration`. Exact commands, timestamps, outputs and source fingerprints are in the independent evidence directory. Reproduction outcome: reproduced as described; static omissions are identified separately from executed failures.

## Root cause and resolution

Independent tasks were not joined on failure; reservations lacked generations/expiry checks. Use a structured bounded worker/producer group, finite drain, generation-specific reservations, post-permit issuance and refunds only for unissued work. Add five empty-start token dimensions, payload+1024 encoded ceilings, explicit queue maxima, source/write links and every cancellation/failure attempt. Flush telemetry outside worker/payload slots and wait paused grants only within original deadlines.

## Debugging and verification

`pair1_validation.json` passes actual rate/burst, byte/grant, pool/queue/buffer and drain audits. `grant_epoch_typo_failure.json` preserves a review-introduced wrong field name; `grant_wait_corrected.json` passes its correction. Final source checks are pending. All named records are under `reports/reviews/evidence/phase3_20261019_independent/`. The issue's final closure will link exact-source reruns. Original failures remain retained.

## Experimental impact and remaining scope

The submitted gate claim is superseded; prior smoke runs remain historical diagnostics and do not certify corrected behavior. No scientific performance result or Phase 4 calibration exists. Single-router immutable reads and single-host process-lifetime expiry remain the supported architecture. SQL/full driver-encoded bytes are null when unknown. Exact allocator/LRU equivalence, calibrated thresholds and performance remain later measurements. See DECISION-0011 and the normative execution-contract clarification; later policies must share the corrected mechanisms.

## Final verification and closure

Verified 2026-10-18T22:08:25.778452+00:00. Final exact source `0a66132a905c16db8765bc463d2697e31343b18ecb8e761155841ac443014212` passed `tests_complete.json` (90 checks including 17 actual-client), `complete_cycle.json` / `complete_pair_validation.json` (39 checks, two recreated-cache expansions) and `expected_failure_complete.json` (all offers/issued work retained on policy failure). All records live under `reports/reviews/evidence/phase3_20261019_independent/`. The late failed-cancel reproduction is retained in `cancel_unresponsive_before.json`, with `cancel_unresponsive_corrected.json` and the complete suite verifying bounded drain/discard and replacement. Source/encoding/interface/accounting corrections and limits are recorded in the independent review and DECISION-0011. Earlier pending-verification paragraphs above are historical milestones, superseded by this closure.
