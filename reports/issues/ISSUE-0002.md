# ISSUE-0002: Docker Linux engine unavailable at first inspection

Opened: 2026-10-09T13:00:00Z
Last updated: 2026-10-09T15:35:00Z
Phase: 0 / environment
Status: verified
Severity: high
Affected component: tooling / cache / DB
Affected source/config: configs/environment.json SHA256 71a5f35aebe10011546923cf652c6cac85092cdd2c64620869a92dd670275aef; infra/compose.yaml SHA256 76b0a829b55a808d1d0dd048864c53d8dddd4f7d5971fc05acaccb69a17fe885
Affected runs/artifacts: initial inspection only; no scientific runs

## Expected behavior

Existing Docker Desktop provides a Linux engine for three Redis instances and PostgreSQL.

## Observed behavior

Native Docker CLI exists but server named pipe is absent. Ubuntu's docker shim reports WSL integration unavailable.

## Original evidence

- Command or run: native installed `docker.exe version`; `wsl -d Ubuntu -- sh -lc 'docker version'`.
- Exit code: shell combined commands ended 0; Docker command reported failure; structured doctor will retain per-check code.
- Log/traceback: reports/evidence/phase0/initial-inspection.txt; `dockerDesktopLinuxEngine: The system cannot find the file specified`.
- Environment: Docker client 29.8.0, Compose v5.5.1, desktop plugin v0.4.4, WSL2.

## Minimal reproduction

1. Invoke native Docker CLI in context desktop-linux.
2. Run `version`.
3. Observe unavailable server pipe.

Reproduction outcome: reproduced at first inspection.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-09T13:00Z | CLI exists but Desktop engine is stopped | Check WSL distribution state, native Docker version and context | docker-desktop stopped; pipe absent; desktop-linux selected | Starting existing Desktop is the next bounded diagnostic |
| 2 / see retained command timestamps | Starting existing Desktop restores engine access | Installed `docker.exe desktop start`, then start.ps1 and doctor | Desktop start returned 0; Compose healthy; doctor Linux engine verified (29.8.0) | Stopped engine explains unavailable pipe; WSL integration was unnecessary |

## Root cause

Docker Desktop's Linux engine was stopped. Starting the existing Desktop made the server available and all four containers healthy without installing software or changing WSL integration/virtualization settings.

## Resolution

Started the existing installed Docker Desktop using `C:\Users\ramst\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe desktop start` (observed exit 0). Used native Windows CLI and pinned isolated Compose services. Successful infrastructure checks explicitly supersede the retained initial inspection, which remains on disk.

## Verification

| Check | Command/config/run ID | Observed result | Evidence |
| --- | --- | --- | --- |
| Original reproduction | native `docker version` | unavailable server | reports/evidence/phase0/initial-inspection.txt |
| Original reproduction after engine start | doctor: native `docker version` and `docker info` | exit 0; Linux engine 29.8.0 | reports/environment.json checks; reports/evidence/phase0/doctor-001.json |
| Relevant invariant/integration check | phase0-health-001 | completed/exit 0; three independent Redis servers plus PostgreSQL read/write/cleanup verified | runs/phase0-health-001/ |
| Cleanup | `powershell.exe -NoProfile -File scripts/shutdown.ps1` | exit 0; no research containers remain | reports/evidence/phase0/shutdown-001.json |

## Experimental impact

Initial infrastructure inspection failed before experiments. No scientific evidence invalidated. The successful start/doctor/health records are the linked corrective checks; no failed health run existed to replace.

## Remaining risk or blocker

Engine must be running on future startup. Research services are stopped at handoff, intentionally; Docker Desktop remains running. Future unavailable-engine errors must retain new evidence.

## Closure

Verified 2026-10-09T15:34:18Z after actual client health and isolated shutdown; source checksum a657f503705b75d360cf31f8ef0d3aa38f20b31751ad0fa003f00223ca4ee005.
