# ISSUE-0011: Command recorder cannot print UTF-8 Docker output on Windows console

Opened: 2026-10-18T20:32:43Z
Last updated: 2026-10-18T20:38:42Z
Phase: 3 / evidence tooling
Status: verified
Severity: medium
Affected component: evidence tooling
Affected source/config: `scripts/record_command.py` before Phase 3 correction
Affected runs/artifacts: `reports/evidence/phase3/docker-desktop-start-001.json`; underlying command succeeded

## Expected behavior

The recorder persists exact command results, prints captured output, and exits with the recorded child exit code for arbitrary UTF-8 tool output.

## Observed behavior

Docker Desktop returned exit code 0 and a checkmark-prefixed status. The JSON record was written correctly, then the wrapper raised `UnicodeEncodeError` while printing the checkmark through the Windows CP1252 text stream.

## Original evidence

- Command or run: existing Docker CLI `desktop start` through `scripts/record_command.py`.
- Exit code: wrapper 1 after child exit 0.
- Log/traceback: interactive traceback retained in session; child result is `reports/evidence/phase3/docker-desktop-start-001.json` with exit code 0 and exact UTF-8 stdout.
- Environment: native Windows PowerShell and CPython 3.12.10.

## Minimal reproduction

1. Run the recorder around a child that emits U+2713 to stdout.
2. Let the recorder call `print()` through the CP1252 console stream.
3. Observe `UnicodeEncodeError` after the JSON evidence is safely written.

Reproduction outcome: reproduced once with Docker Desktop output.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 2026-10-18T20:33Z | Child failed | Inspect the already-written JSON and query Docker engine | Child exit 0; engine reports `linux`; only wrapper traceback failed | Rejected |
| 2 / 2026-10-18T20:33Z | Console text encoding cannot represent the checkmark | Compare stored Unicode stdout with CP1252 traceback | Failure names U+2713 and CP1252 | Supported |

## Root cause

The recorder used text `print()` through the process console encoding after correctly decoding child output as UTF-8.

## Resolution

Write captured stdout/stderr as UTF-8 bytes through the streams' binary buffers. JSON capture and child exit propagation remain unchanged.

## Verification

`utf8-recorder-001.json` records exit 0 and the wrapper emitted U+2713 successfully. `start-002.json` and every later command record also completed without recorder failure.

## Experimental impact

No scientific run was affected. The Docker start succeeded and its exact child result is retained; it is not represented as a failed Docker action.

## Remaining risk or blocker

None known for UTF-8 child output.

## Closure

Verified 2026-10-18T20:38:42Z with an explicit non-ASCII output reproduction.
