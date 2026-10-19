# Required reporting and debugging protocol

Use these templates when implementing `RESEARCH_IMPLEMENTATION_PLAN.md`.

## 1. Evidence and status rules

- Use UTC timestamps in persistent records. For durations use monotonic elapsed time.
- Distinguish `planned`, `implemented`, `executed`, and `verified`. Code existing on disk is not proof that it ran correctly.
- A phase status is `not_started`, `in_progress`, `blocked`, or `complete`. Name the missing prerequisite when blocked. A reporting label does not invoke any product goal-status API.
- An issue status is `open`, `investigating`, `blocked`, `fixed_unverified`, `verified`, or `accepted_limitation`. An accepted limitation is not a solved defect.
- Report expected versus actual behavior, reproduction steps, observed outputs/exit codes, and affected artifacts. Redact secrets; retain useful error messages and tracebacks.
- Name failures honestly. An external tool returning no usable result is not successful verification. A process that starts is not necessarily healthy.
- Never claim that every test passed when only a subset ran. List the relevant check scope and unexecuted checks with reasons.
- Never replace a failed experiment with an unlinked successful retry.

## 2. Current status: `reports/STATUS.md`

```markdown
# Project status

Updated: <UTC timestamp>
Active phase: <number and name>
Phase status: <status>
Source state: <Git revision plus dirty-state fingerprint, or source checksums>
Environment: <manifest path>

## Outcome so far

<What is implemented and what has actually been verified.>

## Current evidence

- <Check or run ID>: <outcome>; evidence: <path>.

## Open issues and impact

- <ISSUE-ID>: <symptom>; blocks <specific deliverable/claim>; record <path>.

## Next actions

1. <Concrete action and expected evidence.>

## Remaining scope and limitations

<What is not implemented, tested, or supported.>
```

Update this at phase boundaries, after consequential failures/fixes, and before handing off to another agent.

## 3. Phase completion report: `reports/phase_<NN>.md`

```markdown
# Phase <NN>: <name>

Started: <UTC timestamp>
Updated/completed: <UTC timestamp>
Status: <status>

## Required outcome

<Phase objective and gate.>

## Delivered

- <File/component>: <purpose and implementation boundary>.

## Validation

| Check | Exact command/config/run ID | Outcome | Evidence |
| --- | --- | --- | --- |
| <check> | <command or ID> | <exit code and observed result> | <path> |

## Errors encountered and debugging

| Issue | Symptom | Root cause/status | Fix or remaining action | Verification |
| --- | --- | --- | --- | --- |
| <ID/link> | <symptom> | <evidence-backed cause or unknown> | <action> | <check/link> |

## Decisions and deviations

<Reasoned changes from the plan, with decision IDs and effects on claims.>

## Gate assessment

<Pass/fail, evidence, and exact missing items.>

## Next phase handoff

<Dependencies, runnable entry points, open issues, and first next action.>
```

Do not declare a phase complete if a required gate is unmet. A baseline legitimately failing under pressure can still be a valid measurement; an implementation defect cannot.

## 4. Issue record: `reports/issues/ISSUE-<NNNN>.md`

Open this record for correctness defects, experiment-invalidating measurement errors, persistent infrastructure failures, or repeated unexpected behavior. Minor typo fixes do not need a full incident record.

```markdown
# ISSUE-<NNNN>: <specific symptom>

Opened: <UTC timestamp>
Last updated: <UTC timestamp>
Phase: <number/name>
Status: <issue status>
Severity: <critical/high/medium/low>
Affected component: <router/cache/DB/controller/load generator/analysis/tooling>
Affected source/config: <fingerprints>
Affected runs/artifacts: <IDs/paths or none>

## Expected behavior

<Precise expectation, invariant, or measurement rule.>

## Observed behavior

<Actual behavior, frequency, scope, and first observed time.>

## Original evidence

- Command or run: <exact, safely redacted command/config/run ID>.
- Exit code: <code, or not available and why>.
- Log/traceback: <path and useful excerpt>.
- Environment: <manifest path and relevant versions/resource settings>.

## Minimal reproduction

1. <Preparation using isolated research data.>
2. <Action.>
3. <Observed failure.>

Reproduction outcome: <reproduced / intermittent / not yet reproduced>.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action or change | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / <UTC> | <testable explanation> | <command/check/diff> | <actual result and evidence link> | <supported/rejected/inconclusive and why> |

## Root cause

<Causal explanation supported by observations. If unknown, say unknown;
do not label the last changed setting as the root cause automatically.>

## Resolution

<Exact changes, touched files, why the changes address the cause,
and source revision/checksums. Explain changed semantics or trade-offs.>

## Verification

| Check | Command/config/run ID | Observed result | Evidence |
| --- | --- | --- | --- |
| Original reproduction | <reference> | <result> | <path> |
| Relevant invariant/integration check | <reference> | <result> | <path> |
| Affected experiment rerun, if needed | <reference> | <result> | <path> |

## Experimental impact

<Which earlier runs/figures/claims are invalidated; which were rerun;
which comparisons remain usable; manifest links.>

## Remaining risk or blocker

<Unverified paths, resource/authority needs, or explicit unsupported cases.>

## Closure

<Verified timestamp and evidence, or reason it remains open/limited.>
```

For intermittent faults, define the repeated reproduction and verification procedure. If the fault did not recur once, report that observation without declaring it eliminated.

## 5. Debugging workflow

1. **Capture:** Preserve the original error, affected source state, configuration, logs, and raw results before changing anything.
2. **Classify:** Separate environment/permission problems, code correctness, overload behavior, and invalid measurements. Expected overload is a policy outcome unless another defect caused it.
3. **Reproduce:** Reduce the workload while retaining the failure. Report when reduction removes the symptom.
4. **Hypothesize:** State a causal hypothesis and a check that could reject it.
5. **Inspect:** Examine the relevant layer: routing epoch, per-key state, cache residency/expiry, DB connection waits, worker budgets, arrival timestamps, or analysis inputs.
6. **Change:** Make a scoped fix. Avoid unrelated rewrites and unexplained batches of configuration changes.
7. **Verify:** Rerun the original reproduction and the meaningful regression/integration check. For measurement defects, rerun affected policies under the same corrected conditions.
8. **Account:** Mark invalid runs and regenerate dependent figures/claims. Keep the old artifacts with their status.
9. **Report:** Explain symptom, cause, fix, verification, and remaining limits. Link the issue from the phase report and index.

After three unchanged repetitions of the same failure, do not continue identical retries. Use a different diagnostic, isolate a missing prerequisite, or report the blocker. Progress on independent tasks where possible.

If permissions or approvals prevent an action, preserve the actual rejection reason and requested action. Ask only for the necessary authority; do not circumvent the restriction or invent successful execution.

## 6. User-facing error/fix update

Use plain language and keep the message concise. The detailed issue file carries the full history.

```text
Observed: <specific failure and its effect>.
Investigated: <diagnostic and the observation that distinguished causes>.
Cause: <supported cause, or still unknown>.
Changed: <scoped fix, or next diagnostic if unresolved>.
Verified: <actual check/run and result, or not yet verified>.
Impact: <affected experiments and remaining work>.
Record: <issue file link>.
```

Do not present this template with fabricated sample numbers. Every completed field must reflect observed work.

## 7. Decision record: `reports/DECISIONS.md`

For each consequential design/methodology change append:

```markdown
## DECISION-<NNNN>: <title>

Time: <UTC>
Phase: <number>
Context: <observed constraint or evidence>
Options considered: <meaningful alternatives>
Decision: <chosen action>
Reason: <evidence and trade-off>
Effect on correctness, comparability, or claims: <explicit impact>
Verification: <check or pending work>
```

Record changes to workload selection, controller thresholds, baseline tuning, resource limits, statistical rules, or scope. Routine implementation details need not become lengthy decision entries.

## 8. Run status and rerun rules

| Run status | Meaning | Handling |
| --- | --- | --- |
| `completed` | Measurement valid; declared observation completed | Include according to the frozen protocol |
| `policy_failure` | Valid measurement of overload, timeout, non-progress, or deadline failure | Include as an outcome; do not discard |
| `invalid_measurement` | Accounting, configuration, or instrumentation defect | Preserve and exclude with reason; rerun affected comparisons |
| `infrastructure_failure` | Required service/environment failed independently of policy | Preserve, diagnose, and retry with a linked new ID |

A process exit code alone does not decide scientific validity. Link the reason, issue, and retry in the run manifest. If policy behavior caused a service crash, classify it as a policy/system outcome unless evidence shows a separate defect.

## 9. Final agent handoff

The final message and artifact README must state:

- What was implemented and the supported architecture.
- Which phases/gates completed and which did not.
- How to start services, reproduce one small run, validate artifacts, and regenerate results.
- What was actually tested, with evidence locations and source/config fingerprints.
- Main findings with measured uncertainty, or that evaluation remains incomplete.
- Significant issues, how they were debugged/fixed, and remaining open issues.
- Whether any earlier results were invalidated and replaced by linked reruns.
- Limitations and the next concrete action.

Do not use phrases such as "fully tested," "production ready," or "novel" without evidence that supports that exact claim. A complete handoff may report a negative research result; it may not conceal unfinished validation.
