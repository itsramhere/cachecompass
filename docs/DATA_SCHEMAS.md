# Event and action schemas

The Python dataclasses in `cache_scaleout.contracts` are the normative Phase 2 machine contracts. Persistent event/request/migration records serialize with `schema_version: 1`; internal observations/actions are embedded in versioned event detail. Enums serialize to lowercase string values. Ordering/duration uses monotonic nanoseconds from a persisted run origin; UTC timestamps include offset zero. Raw payloads and nonfinite values are rejected by `json_record`. The [normative execution rules](PHASE2_EXECUTION_CONTRACT.md) define required detail fields and cross-record validation. There are no historical scientific request/migration records to migrate; original Phase 2 source is retained by the independent review.

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
| `observed_pressure` | string-to-string object | Per-component state labels; ages/reference are in `detail` |
| `reason` | nonempty string | Stable reason code or human-readable reason; no-progress requires one |
| `accounting` | string-to-integer object | Nonnegative operations/bytes/tokens affected by the event |
| `detail` | JSON object | Structured action, observation, transition, operation, or task-terminal detail as applicable; immutable snapshot |

Arrival scheduling and actual submission are separate event kinds. A policy action logs the exact observation window/as-of reference, requested budgets, admissions, rejected candidates, current and incremental foreground estimates, and reasons in linked detail fields/artifacts. A transition logs old/new state and publication epoch. Terminal events name success, policy failure, invalid measurement, or infrastructure failure.

## Per-request record

One `RequestRecord` exists for every offered primary application request, including a load-generator non-submission. Required fields are:

| Field | Type | Rule |
| --- | --- | --- |
| `schema_version`, `run_id`, `request_id` | integer/string/string | Version 1; run-local request ID unique |
| `key` | string | Dataset key identity; permits independent offered-schedule and coalescing reconciliation |
| `scheduled_arrival_ns` | integer | Created before dispatch; latency origin |
| `submitted_ns` | integer/null | Null only for `unsubmitted`; cannot precede scheduled arrival |
| `completed_ns` | integer/null | Required for every submitted terminal outcome; cannot precede submission |
| `timeout_seconds` | finite positive number | Identical foreground rule across policies |
| `outcome` | enum | `completed`, `timed_out`, `failed`, `cancelled`, `refused`, or `unsubmitted` |
| `route` | object/null | Submitted requests require captured `epoch`, `bucket`, `owner`, and `state`; null only when unsubmitted |
| `source` | enum | `old_cache`, `new_cache`, `database`, or explicit `none`; no foreground donor fallback |
| `work_class` | enum/null | Summary: foreground DB if owned attempts exist, otherwise foreground cache; null for no issued work |
| `cache_attempts`, `cache_write_attempts`, `database_attempts` | integers | Own issued cache reads, foreground fills, and DB reads, including retries/timeouts |
| `coalesced_to_request_id` | string/null | Leader ID for a follower; each follower still has its own record/latency |
| `reason` | nonempty string | Terminal result or accounting reason |

End-to-end latency is `completed_ns - scheduled_arrival_ns`; a success after the absolute deadline is invalid. Offered IDs must match the independently persisted schedule and terminal records, not merely the observed record count. Generator drops/non-submissions are `unsubmitted`; system inflight-limit drops are `refused` with a captured route and no I/O. Timeout/error/cancellation remain violations. Followers name the originating request, retain their own cache reads/latency, and own zero DB/fill attempts; the origin's final record includes shared work even if issued after its own terminal outcome. Per-operation events reconcile work independently of response time. No foreground donor source is permitted, and cache-hit source must match captured state.

## Migration task and attempt record

Every `MigrationTask` specifies task/key/bucket, explicit client/target owners, source, work class, timeout, retry policy, original expiry, absolute `deadline_ns`, and optional `parent_task_id`. Source/class pairs are `donor_cache/donor_read`, `database/discretionary_database_warmup`, or `new_cache/destination_write`. A write's source owner identifies the destination client, equals destination_owner, and requires a parent source-read task. Its payload provenance is retained through that parent. Each issued attempt has run/task identity, ordinal, owners, source/class, timeout, terminal outcome, `issued_operations: 1`, nullable actual `issued_bytes`, charged `reserved_bytes`, start/terminal times, and reason. Unknown bytes are null. Attempt ordinal is <= the linked task's finite retry maximum; event operation identity is the unique `(run_id, task_id, attempt)` tuple.

Retries produce new charged attempts. Donor miss/expiry/exhaustion may create a linked DB-fallback task only if policy/grant permits; destination writes have separate linked task/attempt records and accounting events referring to the same operation, not duplicate charges. Read and write stages have finite independent retry limits under one key-pass deadline. Nonissued work uses task-terminal detail with zero issued-operation charge.

## Controller observation and action

`ControllerObservation` includes as-of time, bounded immutable demand, foreground DB attempt estimate/time, signal age limit, pressure states/times, destination identity, routing epoch, current bucket states, per-bucket upper request rates/cold reserves/coverage and `old_owner_db_rate_lower`, plus pending-admission DB reserve. Bucket maps describe the same affected set within configured bounds. Old-owner lower rates represent displaced attempts already in foreground demand and cannot sum above that foreground estimate. `CoverageEstimate` carries destination, as-of and demand-window provenance; counts match that snapshot. Key coverage uses the complete registry. Demand includes total-key, per-bucket and bucket-count bounds. Pressure freshness is computed at actual decision time through `admissions_safe_at`.

`ControllerAction` includes decision time, required expected routing epoch and observation as-of reference, donor-operation/byte, discretionary-DB-operation and destination-write-operation/byte grants, finite validity, ordered unique admissions and nonempty reasons. Grants replace unissued work and expire; they do not replenish by repeated evaluation. `BucketAdvance` represents one bucket's expected state and sequential path for atomic `OwnershipMap.publish`. A zero-work action must explain why. The scheduler receives actions through `apply_action` and cannot infer missing task source/owner/deadline/class.

## Reconciliation rules

Validation in later phases must establish:

1. independent offered-schedule IDs = arrival-event IDs = terminal request IDs, with uniqueness; scheduled = submitted + unsubmitted;
2. submitted = completed + timed out + failed + cancelled + refused;
3. chronological fields and route captures are valid; every submitted request has one captured owner/epoch;
4. global DB attempts equal foreground leaders' DB attempts + unrelated foreground + discretionary warming + OBSERVATION_DATABASE sampler attempts, each category separate and each operation ID counted once;
5. every issued migration retry/write has one charged operation ID, valid linked task/parent and ordinal; provisional permits return, issued tokens remain spent, and uncertain connections are discarded before pool reuse;
6. every bucket transition is sequential, epoch-monotonic, and traceable to one policy action;
7. every terminal run reconciles pending requests/tasks and metrics-sink flush status.

Schema or reconciliation failure makes the run `invalid_measurement`; it is not a policy failure and is retained with an issue link.

Pressure-sampling supplement: ControllerObservation also requires finite nonnegative `observation_db_rate_upper`. OBSERVATION_CACHE and OBSERVATION_DATABASE are separate WorkClass values in accounting events; sampler tasks use deterministic observer IDs and never emit request or migration-attempt records. Each policy gets the same fixed finite sampling grants/pools/deadlines, including when idle or paused. The DB allowance charges the observation rate once. Cache sampling returns pressure, never positive key-residency evidence. See the normative rules for PING/INFO and same-query-mix DB sampling.

Phase 3 independent-review clarification: cache writes return `CacheWriteReceipt.valid_until_ns` for conservative residency confirmation after TTL conversion. Operation `actual_bytes` is null when the full protocol exchange is unknown; separately labeled `payload_bytes` is not protocol traffic. Actual issuance is recorded after client connection acquisition. The two fixed cache-delete fault injections in the functional scaffold are separately recorded as `functional_diagnostic_cache` and are forbidden as hidden work in later policy/calibration comparisons. Initial warming and post-horizon artifact inspection are outside offered workload time. The canonical source manifest now excludes ignored `test_out`, local agent/build/cache state and credential files; historical manifests retain their original definition and hashes.

Phase 5 observations add `coverage_valid_until_ns` per affected bucket. It is
the earliest expiry or maximum-evidence-age deadline among positively credited
resident keys. At decision time, reaching that deadline removes all positive
coverage credit for the bucket until a new observation recomputes it. Legacy
observations without that field earn positive coverage only at their as-of
instant. This prevents a value expiring between observation and publication
from authorizing a stale admission estimate.

Phase 5 independent evidence schema 6 adds an explicit foreground-estimator
known flag; per-component sample times; fixed sampler cutoff; token
init/rate/acquire/refund/forfeit events linked to actual operations; actual
payload hashes and write receipts; per-key terminal timestamps; and publication
and residency-invalidation/reset timestamps. Token and interval-grant accounting
are separate and both must reconcile. Unissued waits do not consume retry
ordinals. Capacity records identify two validated mixed-pool splits and their
runtime/configuration scope; a bare numeric rate is functional-only evidence.
Legacy records remain immutable and cannot prove schema-6 review eligibility.
