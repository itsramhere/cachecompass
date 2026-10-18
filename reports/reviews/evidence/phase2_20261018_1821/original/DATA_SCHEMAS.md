# Event and action schemas

The Python dataclasses in `cache_scaleout.contracts` are the normative Phase 2 machine contracts. Records serialize as JSON objects with `schema_version: 1`; enums serialize to their lowercase string values. Time used for ordering/duration is monotonic nanoseconds from a persisted run origin. UTC timestamps are for cross-artifact correlation and must include an offset. Raw values/payloads are excluded from telemetry.

## Common event record

`EventRecord` is append-only JSONL with these required fields:

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version` | integer | Exactly `1` |
| `run_id` | nonempty string | Matches immutable run manifest |
| `utc_timestamp` | RFC 3339 string | UTC offset required |
| `monotonic_elapsed_ns` | integer | Nonnegative; measured from run origin |
| `phase` | enum | `preparation`, `pre_event`, `handover`, `post_handover`, `terminal` |
| `routing_epoch` | integer | Nonnegative captured/current epoch, as applicable |
| `kind` | enum | scheduled arrival, submission, completion/failure, observation, policy action, transition, migration attempt, accounting, or handover terminal |
| `bucket` | integer/null | Explicit affected bucket when applicable |
| `policy_action` | string/null | Action/catalog name when applicable |
| `observed_pressure` | object | Per-component state plus observation age/reference |
| `reason` | nonempty string | Stable reason code or human-readable reason; no-progress requires one |
| `accounting` | string-to-integer object | Nonnegative operations/bytes/tokens affected by the event |

Arrival scheduling and actual submission are separate event kinds. A policy action logs the exact observation window/as-of reference, requested budgets, admissions, rejected candidates, current and incremental foreground estimates, and reasons in linked detail fields/artifacts. A transition logs old/new state and publication epoch. Terminal events name success, policy failure, invalid measurement, or infrastructure failure.

## Per-request record

One `RequestRecord` exists for every offered primary application request, including a load-generator non-submission. Required fields are:

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version`, `run_id`, `request_id` | integer/string/string | Version 1; run-local request ID unique |
| `scheduled_arrival_ns` | integer | Created before dispatch; latency origin |
| `submitted_ns` | integer/null | Null only for `unsubmitted`; cannot precede scheduled arrival |
| `completed_ns` | integer/null | Required for every submitted terminal outcome; cannot precede submission |
| `timeout_seconds` | finite positive number | Identical foreground rule across policies |
| `outcome` | enum | `completed`, `timed_out`, `failed`, `cancelled`, `refused`, or `unsubmitted` |
| `route` | object/null | Submitted requests require captured `epoch`, `bucket`, `owner`, and `state`; null only when unsubmitted |
| `source` | enum | `old_cache`, `new_cache`, `database`, or explicit `none`; no foreground donor fallback |
| `work_class` | enum/null | Explicit foreground cache/DB charge; null only before any submitted work |
| `cache_attempts`, `database_attempts` | integers | Every issued attempt, including retries/timeouts |
| `coalesced_to_request_id` | string/null | Leader ID for a follower; each follower still has its own record/latency |
| `reason` | nonempty string | Terminal result or accounting reason |

End-to-end latency is `completed_ns - scheduled_arrival_ns`. The offered denominator is the number of request records, not only submissions or completions. `unsubmitted` records identify generator failure and may invalidate capacity claims. `refused` is a measured system outcome. Timeout/error/cancellation remain latency violations under the frozen metric rule. A coalesced leader's DB attempt is counted once globally; follower records name the leader and do not invent their own DB attempts.

## Migration task and attempt record

Every `MigrationTask` specifies `task_id`, key, bucket, `source_owner`, `destination_owner`, source (`donor_cache` or `database`), matching work class, finite timeout, finite retry policy, and original absolute expiry. Each issued attempt produces `MigrationAttemptRecord` with run/task identity, one-based attempt, both owners, source, timeout, work class, terminal attempt outcome, `issued_operations: 1`, actual issued bytes when known, start/completion times, and reason.

Retries produce new attempt records and consume new operation/byte tokens. A donor miss record is followed by a database attempt only if the policy authorizes it and a discretionary budget was acquired. Destination writes receive their own accounting events. Scheduled but never issued work consumes no operation token and must have a cancellation/non-issuance event at shutdown.

## Controller observation and action

`ControllerObservation` contains one `observed_at_ns`, a closed bounded `DemandSnapshot`, `foreground_db_rate_upper`, timestamped DB/donor/destination pressure states, and per-bucket `CoverageEstimate`. The demand window ends no later than the as-of time; pressure timestamps cannot be later. Age/staleness is explicit.

`ControllerAction` contains decision time, separate donor-operation/byte, discretionary-DB-operation, and destination-write budgets with a finite validity interval; an ordered unique tuple of bucket admissions; and one or more reason codes. A zero-work action is valid and must explain why. The scheduler cannot infer a missing source, owner, timeout, or accounting class from global state.

## Reconciliation rules

Validation in later phases must establish:

1. offered IDs = terminal request records; scheduled = submitted + unsubmitted;
2. submitted = completed + timed out + failed + cancelled + refused;
3. chronological fields and route captures are valid; every submitted request has one captured owner/epoch;
4. global DB attempts equal foreground leaders' DB attempts plus unrelated foreground DB attempts plus discretionary warm-up attempts, with each category reported separately;
5. every issued migration retry has one charged attempt record and all acquired tokens/permits are released or terminally accounted;
6. every bucket transition is sequential, epoch-monotonic, and traceable to one policy action;
7. every terminal run reconciles pending requests/tasks and metrics-sink flush status.

Schema or reconciliation failure makes the run `invalid_measurement`; it is not a policy failure and is retained with an issue link.
