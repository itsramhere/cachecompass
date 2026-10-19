# ISSUE-0016: Direct Phase 3 validation omitted repository PYTHONPATH

Opened: 2026-10-18T20:37:18Z
Last updated: 2026-10-18T20:38:28Z
Phase: 3 / artifact validation
Status: verified
Severity: low
Affected component: command invocation / documentation
Affected source/config: no source defect; source-layout package is not installed into the retained venv
Affected runs/artifacts: standalone validation replay only; completed runs remain valid

## Expected behavior

The Phase 3 validation CLI imports the source-layout package and validates the second retained run.

## Observed behavior

The direct invocation omitted the documented `PYTHONPATH=src` setup and exited before argument parsing with `No module named cache_scaleout`.

## Original evidence

- Command or run: direct `.venv\Scripts\python.exe -B -m cache_scaleout phase3-validate ...`.
- Exit code: 1.
- Log: `reports/evidence/phase3/validate-second-001.json`.
- Environment: services stopped; no service access required.

## Minimal reproduction

Invoke the source-layout module from the retained venv without installing the package or setting `PYTHONPATH`.

Reproduction outcome: reproduced once.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T20:44Z | Validation logic failed | Inspect stderr and compare with `phase3_cycle.ps1` | Failure precedes import; cycle explicitly sets `PYTHONPATH` | Rejected; invocation defect |

## Root cause

The standalone command did not include the repository source directory on Python's import path.

## Resolution

Set `PYTHONPATH` to the workspace `src` directory, as the documented direct CLI workflow and Phase 3 cycle script do, then rerun with an explicit retry link.

## Verification

`validate-second-002.json` is explicitly linked to the failed invocation and exits 0. The strengthened replay `validate-second-003.json` also exits 0 with checksum, fingerprint, arrival and terminal reconciliation checks.

## Experimental impact

No run, raw record or comparison was changed. The already-completed cycle validation remains successful.

## Remaining risk or blocker

README must keep the direct-shell environment setup visible.

## Closure

Verified 2026-10-18T20:38:28Z. README and the cycle script include the required source-path setup.
