# ISSUE-0014: Redis sampling exceeds its own bounded connection pool

Opened: 2026-10-18T20:35:25Z
Last updated: 2026-10-18T20:37:04Z
Phase: 3 / actual-client integration
Status: verified
Severity: high
Affected component: Redis adapter / pressure sampling
Affected source/config: initial `RedisCacheAdapter`; integration pool size 2
Affected runs/artifacts: actual-client integration run only

## Expected behavior

Pressure and service-identity sampling must stay within the adapter's configured connection limit.

## Observed behavior

`service_summary` launched four Redis commands concurrently through a two-connection pool. Redis correctly raised `ConnectionError: Too many connections`.

## Original evidence

- Command or run: third actual-client integration suite.
- Exit code: 1; two PostgreSQL cases passed, one Redis case failed, one Redis case errored.
- Log/traceback: `reports/evidence/phase3/integration-tests-003.json`.
- Environment: three healthy pinned Redis 7.4 instances; redis-py 6.4.0.

## Minimal reproduction

1. Configure a Redis pool with two connections.
2. Call the original `service_summary`, which uses `asyncio.gather` for four commands.
3. Observe immediate pool exhaustion.

Reproduction outcome: reproduced against the actual cache adapter.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T20:41Z | Redis unavailable | Compare other Redis test and service health | TTL test reached Redis; service instances healthy | Rejected |
| 2 / 2026-10-18T20:41Z | Internal fan-out bypasses the adapter's operation limiter | Compare gather width four with pool size two | Error is `Too many connections` at pool acquisition | Supported |

## Root cause

One logical bounded sample created four concurrent physical commands while holding only one adapter-level permit.

## Resolution

Issue PING/INFO/config commands sequentially under one bounded sample permit and one absolute deadline. Sampling semantics and recorded fields are unchanged.

## Verification

`integration-tests-004.json` passed actual cache pressure/identity sampling. Both end-to-end runs sampled all three caches within the configured pool bounds; results report maximum per-cache concurrency at or below two.

## Experimental impact

No scientific run exists. The failed live integration record remains retained.

## Remaining risk or blocker

Pressure thresholds remain explicitly provisional until calibration.

## Closure

Verified 2026-10-18T20:37:04Z by actual-client and repeated small-run evidence.
