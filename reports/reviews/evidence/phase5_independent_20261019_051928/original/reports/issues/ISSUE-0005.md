# ISSUE-0005: Retained virtual environment cannot start its Python 3.12 base interpreter

Opened: 2026-10-18T18:03:12Z
Last updated: 2026-10-18T18:06:41Z
Phase: 2 / contract verification
Status: verified
Severity: medium
Affected component: tooling
Affected source/config: Phase 2 source before final fingerprint; retained `.venv/pyvenv.cfg`
Affected runs/artifacts: contract test invocation only; no scientific runs

## Expected behavior

The documented `.venv\Scripts\python.exe` starts CPython 3.12 and runs the Phase 2 standard-library contract tests.

## Observed behavior

The launcher exited 1 before test discovery and reported that its retained Python 3.12 base executable was unavailable. No test executed.

## Original evidence

- Command: `& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v`.
- Exit code: 1.
- Log: `reports/evidence/phase2/test-001.json`.
- Environment: retained Phase 0 Windows virtual environment; services not started.

## Minimal reproduction

1. From the workspace root invoke the exact command above.
2. Observe the launcher error before Python imports or test discovery.

Reproduction outcome: reproduced once; repeated unchanged retries were not attempted.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T18:03:12Z | The launcher remains but the base interpreter moved or is inaccessible | Inspect launcher and retained Python 3.12/3.13 paths plus PATH commands in the sandbox | Launcher exists; installed paths return access denied; no Python command on sandbox PATH | Test source has not failed. Use the established native-execution permission boundary to determine an available interpreter. |
| 2 / 2026-10-18T18:05Z | The Phase 0 interpreter is installed but inaccessible across the restricted sandbox boundary | Invoke that exact Python 3.12 executable through approved native execution and run the unchanged suite | Exit 0; 12 tests ran and passed | Supported interpreter and test source are healthy; the failure is the known restricted execution boundary, not missing Python or contract code. |

## Root cause

The restricted sandbox can execute the workspace-local launcher but denies access when that launcher resolves its base executable under the per-user installation directory. Approved native execution of the exact recorded base interpreter succeeds. This is the same permission boundary characterized by ISSUE-0001, now affecting the retained venv launcher.

## Resolution

Used the existing Phase 0 CPython 3.12.10 directly through the approved native execution boundary. The environment was not rebuilt and no software was installed. Retained both the failed launcher record and successful unchanged-suite record.

## Verification

| Check | Command/config/run ID | Observed result | Evidence |
| --- | --- | --- | --- |
| Original sandbox launcher | `.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v` | Exit 1 before discovery | `reports/evidence/phase2/test-001.json` |
| Same suite, existing supported base interpreter | `Python312\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v` | Exit 0; 12 tests passed | `reports/evidence/phase2/test-002.json` |

## Experimental impact

No scientific runs or performance evidence exist. Only the first Phase 2 test invocation is affected.

## Remaining risk or blocker

Workspace-local launcher execution remains restricted in this agent sandbox. Normal documented user execution was not rechecked, and real clients were intentionally not needed for Phase 2. Python 3.12 remains the supported runtime.

## Closure

Verified 2026-10-18T18:06:41Z. The unchanged contract suite passed on the existing supported interpreter; this closes the Phase 2 verification blocker without claiming the sandbox restriction was removed.
