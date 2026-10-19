# ISSUE-0003: PowerShell 5.1 strips quotes in Python inline runtime check

Opened: 2026-10-09T13:50:00Z (record created after inspecting original failed bootstrap)
Last updated: 2026-10-09T15:35:00Z
Phase: 0 / environment bootstrap
Status: verified
Severity: medium
Affected component: tooling
Affected source/config: bootstrap-before-fix.ps1 and fingerprint-before-fix.ps1 retained under reports/evidence/phase0; wheel lock unchanged
Affected runs/artifacts: bootstrap.log (failed); no scientific runs

## Expected behavior

Bootstrap installs locked wheels and then verifies imports, exiting zero only when both succeed.

## Observed behavior

Wheel installation succeeded; Python inline check failed with SyntaxError, exit 1. Python received `print(Runtime` instead of the intended quoted string. Bootstrap correctly propagated the failure.

## Original evidence

- Command or run: `& .\scripts\bootstrap.ps1` with native Windows PowerShell 5.1.
- Exit code: 1.
- Log/traceback: reports/evidence/phase0/bootstrap.log; supplemental native-output transcription reports/evidence/phase0/bootstrap-error.txt; `SyntaxError: '(' was never closed`.
- Environment: Python 3.12.10, PowerShell 5.1.26100.9444; installed locked wheels.

## Minimal reproduction

1. In native PowerShell 5.1 from the workspace root invoke `.venv\Scripts\python.exe -c` with the exact inline argument retained in bootstrap-before-fix.ps1 (the retained script's relative common.ps1 path must resolve to scripts/common.ps1).
2. Python sees the double quotes removed from the inline code string.
3. Observe SyntaxError after successful dependency installation.

Reproduction outcome: reproduced in original bootstrap. Source before fix retained; no repeated identical retry.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-09T13:50Z | Legacy native argument marshalling alters inline quoted Python | Inspect Python error and Invoke-Checked's displayed original arguments | Original string contains quotes but error shows unquoted `Runtime` | Quoting boundary causes failure; package installation is not the cause |
| 2 / 2026-10-09T14:54:46Z | Python file entry point avoids string marshalling | Replace inline snippets with scripts/check_runtime.py and scripts/capture_source.py; rerun same bootstrap | All imports verified; bootstrap exit 0 | Fix verified; fingerprint uses the same file-based approach |

## Root cause

Windows PowerShell 5.1 legacy native argument marshalling removes double quotes within the Python -c argument; Python then parses an incomplete expression.

## Resolution

Invoke Python file entry points rather than inline code. Bootstrap/fingerprint wrappers pass paths and simple arguments only. Preserve dependency and image locks; no runtime semantics changed. Pre-fix source retained for reviewer inspection.

## Verification

| Check | Command/config/run ID | Observed result | Evidence |
| --- | --- | --- | --- |
| Original reproduction | `powershell.exe -NoProfile -File scripts/bootstrap.ps1` | exit 0; all four required imports verified | reports/evidence/phase0/bootstrap-rerun.json |
| Same quoting boundary | `powershell.exe -NoProfile -File scripts/fingerprint.ps1 -Output reports/source_state.json` | exit 0; aggregate checksum matches executed health/doctor | reports/evidence/phase0/fingerprint-001.json |
| Relevant invariant/integration check | phase0-health-001 | completed/exit 0; actual Redis/PostgreSQL payload readback and cleanup | runs/phase0-health-001/results.json |

## Experimental impact

No scale-out measurements existed. Failed bootstrap transcript and pre-fix source retained; reports/evidence/phase0/bootstrap-rerun.json is its explicitly linked successful rerun. No failed experiment overwritten. Dependency lock unchanged.

## Remaining risk or blocker

Do not reintroduce quoted Python -c snippets in native PowerShell 5.1 wrappers. Native file-based invocation and actual integration verified.

## Closure

Verified by bootstrap rerun (2026-10-09T14:54:51Z), live integration (2026-10-09T15:33:52Z), and retained fingerprint check. Fixed source aggregate SHA256 a657f503705b75d360cf31f8ef0d3aa38f20b31751ad0fa003f00223ca4ee005.
