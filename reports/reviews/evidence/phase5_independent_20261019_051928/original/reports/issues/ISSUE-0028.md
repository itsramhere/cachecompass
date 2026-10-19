# ISSUE-0028: Automatic execution review unavailable for corrected matrix

Opened: 2026-10-19 UTC
Phase: 5
Status: blocked
Severity: high (required live evidence unavailable)
Component: external automatic permission approval service
Affected operation: .venv/bin/python scripts/phase5_matrix.py --prefix p5matrix_v2_20261019 --retry-prefix p5matrix_v1_20261019

Expected: the bounded, label-verified disposable matrix executes with reviewed
network/Docker access, as the full live suites and initial matrix did.
Observed: automatic review returned “Selected model is at capacity” and did not
execute the action. An identical retry remained in review and then returned
“The automatic permission approval review did not finish before its deadline.”
The tool permits one retry after timeout; that identical retry is pending.
These responses expressly do not determine the operation unsafe. No permissions
or network restriction is bypassed. Initial matrix and full suites had already
verified shutdown; no corrected matrix directory existed at the last check.

Impact: all six policies and 134 final tests are delivered, but the corrected
actual-client comparison gate cannot pass until the complete linked replacement
runs and validates. No success is invented. Exact action/reasons are also in
reports/evidence/phase5/approval_capacity.json.

Resolution: await/retry via the supported review path, or request explicit user
network permission if review remains unavailable. Preserve original failed
review responses and report the blocker explicitly if unresolved.

## Final observed permission state

The permitted identical retry also returned automatic-review deadline timeout.
The supported request_permissions call requested network access for the bound
cloud environment, with the concrete 20-case disposable matrix as its reason.
It returned {"permissions":{"network":null,"file_system":null},"scope":"turn"}.
No additional permission was granted. The corrected matrix has no run directory
and remains unexecuted. Repeating unchanged failed approvals is stopped. All
independent implementation, exact-source archival, historical preservation,
whitespace checks and reporting are complete. No services started under these
failed reviews; last executed cycles verified shutdown.
