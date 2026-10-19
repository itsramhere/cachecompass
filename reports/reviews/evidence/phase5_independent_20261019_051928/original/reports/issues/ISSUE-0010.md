# ISSUE-0010: Docker Linux engine stopped at Phase 3 service startup

Opened: 2026-10-18T20:32:07Z
Last updated: 2026-10-18T20:37:04Z
Phase: 3 / actual-client integration
Status: verified
Severity: high
Affected component: infrastructure / Redis / PostgreSQL
Affected source/config: Phase 3 implementation before final fingerprint; pinned `infra/images.env`
Affected runs/artifacts: service startup only; no experiment run created

## Expected behavior

The documented isolated Compose project starts three Redis instances and PostgreSQL for actual-client verification.

## Observed behavior

`scripts/start.ps1` could not connect to `dockerDesktopLinuxEngine` because the named pipe did not exist and correctly refused to continue.

## Original evidence

- Command or run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1` through `scripts/record_command.py`.
- Exit code: 1.
- Log/traceback: `reports/evidence/phase3/start-001.json`.
- Environment: existing Docker Desktop installation and pinned Phase 0 Compose configuration.

## Minimal reproduction

1. Leave Docker Desktop's Linux engine stopped.
2. Run the documented startup script.
3. Observe the missing engine pipe and guarded failure before Compose mutation.

Reproduction outcome: reproduced once; no unchanged retry attempted.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-19T20:05Z | Existing Docker Desktop is stopped, matching ISSUE-0002 | Inspect retained startup stderr | Missing `dockerDesktopLinuxEngine` pipe; startup guard fired | Start the existing Desktop, then retry the same script with an explicit link |

## Root cause

Docker Desktop's existing Linux engine was stopped. Its CLI start command returned zero, after which `docker info` reported `linux` and the same service startup succeeded.

## Resolution

Start the existing installed Docker Desktop using its documented CLI; do not install software or change engine settings.

## Verification

`docker-desktop-start-001.json` records the child command exit 0. `start-002.json` is linked to the failed startup and records all four services healthy. `integration-tests-004.json` passed actual clients. `cycle-001.json` recreated and removed the verified Compose project twice and ended with no research containers.

## Experimental impact

No run directory or measurement was created. The failed startup record remains retained.

## Remaining risk or blocker

Future runs still require Docker Desktop to be running; the scripts continue to refuse unavailable or non-Linux engines.

## Closure

Verified 2026-10-18T20:37:04Z. Services were healthy for integration and two runs, then cleanly removed.
