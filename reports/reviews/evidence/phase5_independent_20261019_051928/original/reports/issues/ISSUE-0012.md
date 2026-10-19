# ISSUE-0012: Live integration tests create unsupported Windows Proactor loop

Opened: 2026-10-18T20:34:04Z
Last updated: 2026-10-18T20:36:17Z
Phase: 3 / actual-client integration
Status: verified
Severity: high
Affected component: integration test harness / PostgreSQL client
Affected source/config: initial `tests/test_phase3_integration.py`; services healthy
Affected runs/artifacts: integration test run only; no scientific run

## Expected behavior

Actual Redis/PostgreSQL client tests use the supported Windows Selector event loop and reach the disposable services.

## Observed behavior

All four cases failed in async setup. Psycopg pool workers reported that async psycopg cannot use the Proactor event loop; setup then timed out waiting for a connection.

## Original evidence

- Command or run: `PAPER2_INTEGRATION=1 .venv\Scripts\python.exe -B -m unittest tests.test_phase3_integration -v` through the command recorder.
- Exit code: 1; four tests, four setup errors.
- Log/traceback: `reports/evidence/phase3/integration-tests-001.json`.
- Environment: healthy disposable Compose services from `start-002.json`; CPython 3.12.10 on Windows.

## Minimal reproduction

1. Let `IsolatedAsyncioTestCase` create the Windows default Proactor loop.
2. Open `AsyncConnectionPool`.
3. Observe psycopg reject the loop before a service query is issued.

Reproduction outcome: deterministic in every test setup.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T20:36Z | Services or credentials failed | Inspect pool worker errors and earlier healthy Compose start | Error explicitly names Proactor; no auth/service error | Rejected |
| 2 / 2026-10-18T20:36Z | Test harness omitted the established Selector policy | Compare with `cache_scaleout.__main__` and Phase 0 health setup | CLI installs Selector policy; test module did not | Supported |

## Root cause

The direct unittest entry point bypassed `cache_scaleout.__main__`, so it never installed `WindowsSelectorEventLoopPolicy` before isolated async loops were created.

## Resolution

Install the Selector policy at integration-test module import on Windows. No adapter or service behavior changed.

## Verification

The linked chain progresses through adapter findings and ends at `integration-tests-004.json`: exit 0, all four actual-client cases passed on the Selector loop.

## Experimental impact

No scientific or small-system run exists. The failed harness run is retained and must not be reported as an actual-client behavior failure.

## Remaining risk or blocker

Direct Windows async entry points must continue to install the Selector policy, as the CLI and integration test do.

## Closure

Verified 2026-10-18T20:36:17Z by the actual-client suite.
