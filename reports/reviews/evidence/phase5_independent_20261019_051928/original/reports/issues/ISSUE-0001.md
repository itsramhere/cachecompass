# ISSUE-0001: Sandbox prevents discovery of existing runtime and hardware

Opened: 2026-10-09T12:50:00Z
Last updated: 2026-10-09T15:35:00Z
Phase: 0 / environment
Status: verified
Severity: medium
Affected component: tooling
Affected source/config: original plan SHA256 54b41573f7f705c16a15994aba50b7190b7532b0a5e8cf094ca68567b5ae53cc
Affected runs/artifacts: environment inspection only; no experiments

## Expected behavior

Discover existing hardware and runtime/container prerequisites without changing system installation.

## Observed behavior

Native sandbox PATH has no Python/Docker; CIM and WSL return access denied. Explicit per-user executable lookup also fails inside sandbox.

## Original evidence

- Command or run: `Get-CimInstance Win32_OperatingSystem`; `python --version`; `docker version`; `wsl --list --verbose`.
- Exit code: individual PowerShell errors were nonterminating; no trustworthy combined per-check exit code.
- Log/traceback: reports/evidence/phase0/initial-inspection.txt; HRESULT 0x80041003 and WSL E_ACCESSDENIED.
- Environment: native PowerShell Desktop 5.1; reports/environment.json.

## Minimal reproduction

1. Use native sandbox PowerShell in the workspace.
2. Run the original inspection commands.
3. Observe missing commands and denied CIM/WSL access.

Reproduction outcome: reproduced with explicit installed executable paths inside sandbox.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-09T12:50Z | Software may truly be absent | Inspect standard installation paths and WSL outside sandbox with approval | Python312/Python313 and per-user DockerDesktop found; Ubuntu/docker-desktop WSL2 registered | Missing PATH was insufficient evidence of absence |
| 2 / 2026-10-09T12:55Z | Direct executable paths suffice inside sandbox | Invoke native installed Python paths | Paths not recognized; Docker directory access denied | Execution permission boundary remains |
| 3 / 2026-10-09T13:00Z | Approved native execution can use installed runtime | Create local venv and invoke installed Python outside sandbox | Python 3.12.10; virtual environment created | Supported path found; integration pending |

## Root cause

Sandbox restricts access to per-user installation directories, WSL service, and CIM. Approved outside-sandbox inspection and execution see the installations.

## Resolution

Use existing Python 3.12.10 with project-local .venv and native PowerShell scripts. Request escalation for actions requiring those installed executables; no system installation changes.

## Verification

| Check | Command/config/run ID | Observed result | Evidence |
| --- | --- | --- | --- |
| Runtime | installed Python `--version` | Python 3.12.10 | reports/evidence/phase0/initial-inspection.txt |
| Runtime imports | `powershell.exe -NoProfile -File scripts/bootstrap.ps1` | exit 0; Python 3.12.10 and all required client imports | reports/evidence/phase0/bootstrap-rerun.json |
| Relevant invariant/integration check | doctor and phase0-health-001 | exit 0; hardware/runtime captured and four real client checks passed | reports/environment.json; runs/phase0-health-001/results.json |

## Experimental impact

No scientific runs existed; no comparisons invalidated.

## Remaining risk or blocker

Future runtime/container commands need appropriate execution permissions.

## Closure

Workaround verified by retained bootstrap, doctor and service health on 2026-10-09T15:33:52Z. This verifies the authorized execution workflow; sandbox restrictions themselves were not removed. Source state: a657f503705b75d360cf31f8ef0d3aa38f20b31751ad0fa003f00223ca4ee005.

