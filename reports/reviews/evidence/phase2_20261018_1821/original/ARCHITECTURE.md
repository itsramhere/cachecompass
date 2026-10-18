# Phase 2 architecture and contract boundary

Status: specified and contract-checked; the Phase 3 request path and service implementations do not exist yet. All capacities, pressure thresholds, deadlines, observation widths, latency targets, pool sizes, and rate limits are configuration inputs that remain provisional until calibration and protocol freeze. This design supports a characterization study; it makes no novelty or performance claim.

## Scope and topology

One asynchronous Python router is the only routing writer and the only experiment controller. It serves immutable application reads through two independent old Redis instances, one healthy empty destination Redis instance, and one authoritative PostgreSQL database. An open-loop load generator offers requests; an optional independent generator creates unrelated foreground database demand. Redis instances have equal bounded memory, eviction, and TTL semantics. This is application-managed cache-aside routing, not native Redis cluster resharding.

The router uses a stable, seeded SHA-256-derived mapping from keys to a configured finite set of virtual buckets. The old two-node and final three-node membership maps are immutable within a run. Only buckets whose final owner is the new node participate in migration or handover. Values are immutable in the primary study; writes and multiple routers are outside this phase.

| Component | Sole responsibilities | Must not do |
| --- | --- | --- |
| Open-loop generator | Create every offered-request ID and scheduled monotonic arrival; record submission or an explicit non-submission | Reduce the offered schedule in response to latency or omit delayed/dropped offers |
| Router/request coordinator | Capture one routing epoch and owner; execute cache-aside foreground reads; coalesce same-key misses; enforce foreground timeout | Re-read ownership mid-request, use future trace data, or hide queue/coalescing time |
| Ownership map | Stable key/bucket maps, per-bucket state, atomic monotonic epoch publication | Infer readiness or perform I/O |
| Demand tracker/key registry | Exact bounded recent counts for registered keys and overflow accounting | Admit future accesses, silently discard overflow, or assert residency |
| Residency tracker | Maintain positive destination evidence and invalidate it after expiry, observed eviction/miss, or staleness | Treat copied, scheduled, or unknown keys as resident indefinitely |
| Migration scheduler | Issue budgeted donor reads, optional budgeted DB warm-up reads, and destination writes with bounded workers/retries | Consume foreground pool permits or retry without charging work |
| Controller/policy | Consume one causal observation; select budgets and eligible bucket admissions; explain no-progress | Issue I/O directly or inspect future workload events |
| Observation collector | Close windows; report request, DB, donor, destination, pool, and resource measurements with age | Merge discretionary DB work into foreground demand |
| Metrics sink | Append validated event, request, migration, and accounting records with backpressure | Drop records silently or rewrite prior evidence |
| Run coordinator | Create an isolated namespace/instances, reproduce the initial state, enforce deadline, flush/validate artifacts | Broad-flush an unverified service or reuse preceding-run warming |

The typed boundary is implemented in [contracts.py](../src/cache_scaleout/contracts.py), [interfaces.py](../src/cache_scaleout/interfaces.py), and [policies.py](../src/cache_scaleout/policies.py). These modules contain no network request path.

## Ownership, routing epochs, and bucket transitions

Each affected bucket follows exactly:

```text
OLD  --migration pass begins-->  COPYING  --readiness evaluated-->  ELIGIBLE
ELIGIBLE  --policy admits atomically-->  NEW
```

`OLD`, `COPYING`, and `ELIGIBLE` route foreground reads to the old owner. `COPYING` means bounded migration may be active. `ELIGIBLE` means the policy has enough evidence to consider admission; it does not promise full residency or force admission. `NEW` routes later requests to the destination. Transitions are sequential and irreversible in the immutable-data experiment. Unsafe pressure pauses future work or admissions; it does not roll a `NEW` bucket back.

The ownership map publishes all transitions in one controller action as one immutable snapshot with epoch `e + 1`. Before any cache I/O, a submitted request atomically captures `(epoch, bucket, state, foreground owner)`. Every attempt for that request uses the captured owner. Thus a request that captured the old owner may finish there after another task publishes `NEW`; the next request can capture the new epoch. Coalescing is keyed by `(captured owner, key)`, preventing old-owner and new-owner requests across a cutover from sharing a fill that targets the wrong cache.

Only the single router writes routing state, so no distributed consensus claim follows. The stable old/final maps, mapping seed, bucket count, and affected-bucket list are persisted with each run.

## Foreground read path contract

End-to-end time begins at scheduled arrival, before submission delay. The load generator creates an arrival event even if dispatch later fails.

1. On submission, capture one route and calculate one absolute foreground deadline from the scheduled arrival plus the configured request timeout. Record actual submission separately.
2. Acquire a foreground cache permit from the captured owner's bounded pool within the remaining deadline, then read only that owner. `NEW` has no foreground fallback to old nodes in the primary study.
3. A hit returns the immutable value. A miss joins or creates a coalescing entry keyed by `(owner, key)`. Followers wait within their own deadlines and retain their own end-to-end latency/accounting records.
4. The leader acquires a permit from the dedicated bounded foreground DB pool and performs the authoritative read within the same request deadline. Every issued DB attempt is `foreground_database` work. It populates the request's captured owner without extending the value's absolute expiry and resolves followers.
5. Completion, timeout, failure, cancellation, refusal, or non-submission is terminal and recorded. Queue, coalescing, pool, cache, DB, retry, and dispatch waits are inside latency.

The coalescing table has a configured maximum number of keys. If no entry can be created before the deadline, the request receives an explicit terminal result; it never starts an unbounded task. A cancelled follower detaches without cancelling shared work needed by other waiters. Cancelling the final waiter cancels an unissued leader task; already issued I/O remains charged. Leader completion or failure resolves all followers and removes the entry in `finally`. Semaphore/pool permits also return in `finally` on success, error, timeout, and cancellation.

Foreground retries, if enabled, use one identical finite `RetryPolicy` for every experimental policy. Attempts share the request deadline, use finite per-attempt timeouts/backoffs, and are included in request latency and operation counters. A cache miss does not consume a migration budget. A foreground DB read continues even when discretionary warm-up is paused.

## Migration and warm-up path

Only affected keys may be scheduled. Every `MigrationTask` names its key/bucket, explicit source, source owner, destination owner, original absolute expiry, timeout, retry contract, and work class.

The deterministic source order is donor first, then optional database warm-up. A donor read consumes one donor-operation token, its actual transferred/request bytes, one bounded background-cache connection, and one worker attempt. A donor hit may cause a destination write, which separately consumes destination-operation/byte capacity. A donor miss or timeout may fall back to the database only when the policy permits DB warm-up and a discretionary-DB token plus a dedicated background-DB connection are available. It never borrows from foreground quota.

Tokens are acquired before issuance. Every issued attempt, including timeouts, failed reads/writes, and retries, consumes operation budget; actual request/response bytes are charged when known. Budget is not refunded on cancellation. Waiting for a token uses no work token but remains observable. Retry count and backoff are finite. A task becomes terminal after success, source-missing disposition, cancellation, or exhausting attempts. Completion of a finite pass means every task in the captured finite registry has a terminal disposition, not that every key is resident.

On copy, the destination receives the source's absolute expiry. If the remaining TTL is nonpositive before write, the item is `expired` and is not written. No operation refreshes TTL. Old replicas remain under their normal bounded memory and expiry rules.

Migration uses separate workers and connection pools from foreground work. Donor and destination limits are separate from DB warm-up limits because their units and bottlenecks differ. All limits are common across compared policies unless that limit is the declared manipulated control.

## Bounded causal demand and observation model

The run configuration declares the complete immutable dataset key bound, maximum registered keys overall/per bucket, subwindow width, number of retained subwindows, and maximum observation age. Dataset preparation deterministically registers keys and object sizes. Exceeding the registry bound is an invalid configuration. Unknown offered keys are recorded as overflow and invalidate exact-coverage claims; they are never silently inserted beyond the bound.

For every submitted request, the tracker increments an exact integer counter in the current monotonic-time subwindow and updates last-seen time. The tracker holds a fixed ring of `ceil(observation_window / subwindow_width)` slots for every registered key that was observed within the retained horizon. Empty/stale entries are reclaimed deterministically, while registry identity/size remains bounded. A snapshot closes at `window_end <= observed_at`; later arrivals cannot modify it. It contains exact counts for represented keys plus explicit overflow counts. Initial implementation cost is:

- metadata: `O(registered keys + active keys * retained subwindows + buckets)`;
- update: `O(1)` per request;
- expiry/rotation: `O(keys in the replaced slot)`;
- snapshot: `O(active keys in the requested bucket/window)`.

The actual byte/CPU cost must be measured before adopting a sketch. A sketch is not part of Phase 2 and cannot silently replace these semantics. Policy ranking uses only closed-window request counts and registered object bytes, e.g. causal requests-saved per byte. Ties use stable `(bucket, key)` order. A trace reader may schedule future arrivals, but the policy-facing demand tracker cannot access them.

Every controller tick receives one `ControllerObservation` with a single monotonic as-of time. Each DB/donor/destination pressure sample carries its measurement time and age. Data after the as-of time is rejected. A signal older than its configured age is `stale`, and missing data is `unknown`; adaptive policies then set affected discretionary work to zero and pause admissions rather than treat absence as safety.

`foreground_db_rate_upper` includes all measured authoritative reads caused by primary application requests plus unrelated application/background traffic already reaching the DB. It excludes discretionary warm-up reads, which have their own counters. For proposed bucket `b`:

```text
incremental_b = request_rate_upper_b * (1 - warmed_request_coverage_lower_b)
                + unobserved_or_uncertain_miss_reserve_b

remaining = max(0, C_safe - safety_reserve
                   - foreground_db_rate_upper
                   - planned_background_DB_rate)
```

Only `incremental_b` is charged for a proposed transition. The bucket's already-observed DB misses are already inside `foreground_db_rate_upper` and are not added again. Multiple candidate buckets are evaluated sequentially, accumulating admitted incremental load before the next decision. This is a conservative admission heuristic for the calibrated equal-cost query mix, not a safety proof.

## Residency and two coverage measures

Key-count coverage is `confirmed-warm known keys / known keys`. Warmed request coverage is `past demand for confirmed-warm keys / (represented past demand + overflow/unknown demand)`. They answer different questions and are always logged separately.

Positive destination residency evidence arises only from a completed destination write or a foreground destination hit. A scheduled/read donor item is not enough. Evidence contains observation time and absolute expiry. It becomes non-warm after expiry, an observed destination miss/eviction, an explicit flush/reset event, or when older than the configured residency-observation age. Redis eviction notifications are optional evidence; their absence never proves residency. Sampling/probing may refresh evidence but consumes explicitly budgeted destination operations. `UNKNOWN`, `EVICTED`, `EXPIRED`, and stale `CONFIRMED` all contribute zero warmed demand. Unrepresented/overflow demand stays in the denominator or uncertainty reserve.

A bucket may enter `ELIGIBLE` through the specific policy's finite migration/readiness rule, but adaptive admission still uses warmed request coverage and uncertainty. Key-count completion alone cannot establish safe admission.

## Observation, action, and accounting flow

```text
append-only request/migration records
                 |
                 v
closed causal windows + signal ages --> Controller.decide(observation)
                                            |
                 reasoned budgets + ordered admissions
                                            |
       bounded migration scheduler + atomic ownership publisher
                                            |
                    append-only action/accounting events
```

The metrics sink applies bounded backpressure. If it cannot durably account for an offered request or issued action, the run becomes `invalid_measurement`; telemetry loss is never converted into a successful policy outcome. [DATA_SCHEMAS.md](DATA_SCHEMAS.md) defines records and reconciliation.

## Isolated reset and equivalent starting state

Every run uses either disposable service instances or a unique, validated namespace containing the run ID. Reset code first verifies the Compose project/service identity or namespace ownership marker. It may delete only that exact research namespace; it never issues a broad flush to an unverified/shared service.

Dataset generation, mapping seed, offered schedule, and initial-warming seed are paired across policies. Preparation writes authoritative values/checksums, starts with an empty destination namespace, and warms old owners from a persisted deterministic key list under identical TTL rules. The run records per-node sorted-key/value/TTL summaries (or deterministic sampled checksums when full enumeration is too expensive), memory/eviction counters, mapping checksum, and warming completion criterion. A run starts only when these match the paired-state manifest within the declared TTL-time tolerance. No namespace from a preceding run is reused.

## Finite handover outcomes

The handover clock begins at the external expansion trigger, so migration before cutover is included. Success requires all affected buckets in `NEW` and intended foreground traffic observed on the destination for the configured stability interval. Idle/bursty intervals with insufficient affected requests are `traffic_stability_inconclusive`, not invented confirmation; the run continues until evidence or deadline.

At the finite deadline, any incomplete state terminates as `handover_timeout` with outstanding buckets/tasks and the last no-progress reasons. Exhausted migration tasks may either block all-at-once policies or remain cold under a policy's declared bounded source-missing rule; the chosen disposition is recorded. Infrastructure/measurement faults are distinct from valid policy failures. Thresholds, deadline, stability sample minimum, and latency target remain provisional until Phases 4 and 7.

## Phase boundary

Phase 2 delivers contracts and pure checks only. It does not implement network clients, request coalescing, token buckets, the router loop, migration workers, experiment execution, or performance measurement. Service containers remain stopped. Phase 3 must implement these interfaces and verify races, timeouts, cancellation, expiry, resource bounds, reset equivalence, and real Redis/PostgreSQL integration.
