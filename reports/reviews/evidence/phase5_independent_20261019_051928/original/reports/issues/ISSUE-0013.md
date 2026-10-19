# ISSUE-0013: PostgreSQL dataset preparation calls executemany on connection

Opened: 2026-10-18T20:35:05Z
Last updated: 2026-10-18T20:36:17Z
Phase: 3 / actual-client integration
Status: verified
Severity: high
Affected component: PostgreSQL adapter / dataset preparation
Affected source/config: `src/cache_scaleout/adapters.py` before correction; Phase 3 smoke config
Affected runs/artifacts: actual-client integration setup; no scientific run

## Expected behavior

Dataset preparation atomically creates the disposable Phase 3 table and inserts every deterministic row through psycopg 3's async API.

## Observed behavior

After the event-loop fix reached PostgreSQL, all four test setups failed with `AttributeError: 'AsyncConnection' object has no attribute 'executemany'`.

## Original evidence

- Command or run: linked actual-client suite rerun.
- Exit code: 1; four tests, four setup errors.
- Log/traceback: `reports/evidence/phase3/integration-tests-002.json`, linked to the prior harness failure.
- Environment: healthy pinned PostgreSQL 17 container; psycopg 3.2.10 / pool 3.3.3.

## Minimal reproduction

1. Open a psycopg 3 async connection and transaction.
2. Call `connection.executemany(...)`.
3. Observe the missing method before rows are inserted.

Reproduction outcome: deterministic in every setup.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T20:38Z | SQL or table definition failed | Inspect the first adapter frame | Failure occurs on method lookup before SQL execution | Rejected |
| 2 / 2026-10-18T20:38Z | Batch API belongs to cursor | Compare existing `connection.execute` use with psycopg async cursor API | Async cursor exposes `executemany` | Supported |

## Root cause

The adapter used the cursor batch method on `AsyncConnection`.

## Resolution

Create an async cursor inside the existing bounded transaction and await `cursor.executemany`. Transaction, deadline and pool limits are unchanged.

## Verification

`integration-tests-004.json` passed all four actual-client tests; both small runs then prepared and verified all 48 authoritative rows.

## Experimental impact

No scientific or end-to-end run was created. The failed integration evidence is retained.

## Remaining risk or blocker

None known for the Phase 3 dataset preparation path.

## Closure

Verified 2026-10-18T20:37:04Z by integration and both end-to-end runs.
