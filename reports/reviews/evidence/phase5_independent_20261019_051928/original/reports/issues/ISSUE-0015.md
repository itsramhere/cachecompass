# ISSUE-0015: Redis TTL conversion can extend the original expiry deadline

Opened: 2026-10-18T20:35:25Z
Last updated: 2026-10-18T20:36:17Z
Phase: 3 / actual-client integration
Status: verified
Severity: critical
Affected component: Redis adapter / TTL correctness
Affected source/config: initial `RedisCacheAdapter`; immutable TTL integration case
Affected runs/artifacts: actual-client integration run only; no scientific run

## Expected behavior

Writing and copying a value must never extend its original absolute expiry deadline.

## Observed behavior

The donor read reconstructed an absolute monotonic expiry 12 ms later than the original test deadline. The initial relative PTTL write and pre-read timestamp allowed network/command latency to appear as extra lifetime.

## Original evidence

- Command or run: third actual-client integration suite.
- Exit code: 1; TTL assertion failed against actual Redis.
- Log/traceback: `reports/evidence/phase3/integration-tests-003.json`; observed expiry `1759590000000` greater than original `1759578000000`.
- Environment: pinned Redis 7.4 and redis-py 6.4.0.

## Minimal reproduction

1. Create a cache value with a monotonic deadline 1.5 seconds ahead.
2. Write using a relative PTTL calculated before network issue.
3. Atomically read payload/PTTL and reconstruct from a pre-command timestamp.
4. Observe a reconstructed deadline later than the original by transport time.

Reproduction outcome: reproduced on actual Redis.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T20:41Z | Millisecond rounding alone explains the error | Compare error magnitude with the 1 ms floor | Extension is about 12 ms | Rejected |
| 2 / 2026-10-18T20:41Z | Relative expiry anchors after local calculation and read reconstruction ignores transit | Compare write/read timing boundaries | Extension matches local command latency | Supported |

## Root cause

The adapter converted a monotonic absolute deadline to a relative Redis TTL before transport and reconstructed it without subtracting the local round trip.

## Resolution

Write with Redis `PXAT` using the current wall/monotonic offset and millisecond floor. On atomic GET/PTTL, subtract the full local read round trip from the pre-read timestamp plus returned PTTL. Both choices are conservative and may shorten lifetime slightly.

## Verification

`integration-tests-004.json` passed the actual-Redis test: donor payload matched, donor expiry did not exceed the registry deadline, and destination copy expiry did not exceed the donor expiry.

## Experimental impact

No scientific or small run exists. Any evidence from the failed TTL case is invalid for TTL correctness and retained as failure evidence only.

## Remaining risk or blocker

Wall/monotonic conversion is verified only on the single-host short-run architecture. It deliberately rounds down and may expire data slightly early.

## Closure

Verified 2026-10-18T20:36:17Z against actual Redis.
