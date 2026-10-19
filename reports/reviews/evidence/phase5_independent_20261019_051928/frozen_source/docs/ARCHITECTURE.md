# Phase 2 architecture and contract boundary

Status: this is the Phase 2 specification; shared runtime mechanisms now exist in Phase 3 and are assessed by the independent review under `reports/reviews/phase_03_independent_20261019.md`. Comparative policy loops remain later work. All capacities, pressure thresholds, deadlines, observation widths, latency targets, pool sizes, and rate limits remain provisional until calibration and protocol freeze. This design supports a characterization study; it makes no novelty or performance claim.

The [normative execution rules](PHASE2_EXECUTION_CONTRACT.md) define exact policy updates, configuration domains, grant replacement, retry/pending-admission accounting, cleanup, reset and stability behavior. They resolve the independent review findings and take precedence over shorthand here.

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

The coalescing table has a configured maximum number of keys. A separate fill task retains its creator's deadline and accounting ID; all waiters, including the creator, detach independently. The final waiter cancels even issued work; issued operations remain charged. Permits return only after confirmed completion or connection discard, within a finite cleanup deadline. Entry removal checks task generation in `finally`. See the normative rules for follower failures, late accounting, and uncertain driver cancellation.

Foreground retries, if enabled, use one identical finite `RetryPolicy` for every experimental policy. Attempts share the request deadline, use finite per-attempt timeouts/backoffs, and are included in request latency and operation counters. A cache miss does not consume a migration budget. A foreground DB read continues even when discretionary warm-up is paused.

## Migration and warm-up path

Only affected keys may be scheduled. Every `MigrationTask` names its key/bucket, explicit source, source owner, destination owner, original absolute expiry, timeout, retry contract, and work class.

The deterministic source order is donor first, then optional database warm-up. A donor read consumes one donor-operation token, a conservative encoded-byte reservation, a background-cache connection, and a worker attempt; actual bytes are recorded separately. A donor hit can create a separate destination-write task, charged to destination operations/bytes. A donor miss/expiry or exhausted donor stage can fall back to DB only with policy authorization, a discretionary token and a dedicated background-DB connection. It never borrows foreground quota.

Tokens and conservative encoded-byte reservations are acquired before issuance. Every issued attempt, including timeouts, failed reads/writes, and retries, consumes operation and reserved-byte budget; actual bytes are also recorded (null when unknown). Issued budget is never refunded. Task deadlines include queue/token waits and backoff. Finite donor, DB-fallback, and destination-write stages end in success or an explicit not-warmed disposition; they never restart an exhausted stage. Completion of a finite pass means every captured key has a terminal disposition, not that every key is resident.

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

`foreground_db_rate_upper` includes primary and unrelated application DB attempts. It excludes discretionary warming and common pressure-sampler reads. Sampler demand has its own `observation_db_rate_upper` allowance term and operation class; the same bounded sampling runs for every policy even when migration is paused, allowing fresh idle-destination/DB signals. For proposed bucket `b`:

```text
new_owner_upper_b = max_foreground_DB_attempts * (
                request_rate_upper_b * (1 - warmed_request_coverage_lower_b)
                + unobserved_or_uncertain_miss_reserve_b)
incremental_b = max(0, new_owner_upper_b - old_owner_db_rate_lower_b)

remaining = max(0, C_safe - safety_reserve
                   - foreground_db_rate_upper
                   - pending_admission_db_rate_upper
                   - planned_background_DB_rate
                   - observation_db_rate_upper)
```

All rates count issued attempts, including retries. Old-owner attempts are already in the foreground estimate: only the positive new-minus-old increment is added. Credit only a conservative same-window old-bucket lower estimate; stale/unknown old demand gets zero credit, with conservative overlap logged. Never subtract unrelated demand or grant negative-increment credit. Candidates accumulate charges within a tick, and a pending-admission reserve prevents spending the same allowance again until a wholly post-cutover observation includes their work. This is a calibrated-query-mix heuristic, not a safety proof.

## Residency and two coverage measures

Key-count coverage uses the complete registered bucket key set, including keys with no recent requests. Warmed request coverage is `past demand for confirmed-warm keys / (represented past demand + overflow/unknown demand)`. Evidence must match both key identity and destination. They answer different questions and are always logged separately.

Positive destination residency evidence arises only from a completed destination write or foreground destination hit. A scheduled/read donor item is insufficient. Evidence contains key/destination identity, observation time and absolute expiry; expiry, observed miss/eviction, reset or age invalidates it. Optional eviction notifications never prove residency by their absence. Probes are disabled in the primary contract; any extension requires a separately charged destination-read grant for all policies. UNKNOWN, expired, evicted and stale evidence contributes zero warmed demand. Coverage retains unknown demand in its denominator and carries matching window/destination provenance.

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

Every comparative run recreates the verified disposable research cache instances and uses a fresh namespace. Namespace-only isolation is restricted to functional diagnostics because it shares physical eviction/memory state. Reset verifies Compose project/service identity first; it never issues a broad flush to an unverified/shared service.

Dataset generation, mapping seed, offered schedule, and initial-warming seed are paired across policies. Preparation writes authoritative values/checksums, starts with an empty destination, and warms old owners from a persisted deterministic key list under identical TTL rules. The primary comparison requires complete sorted-key/value/TTL summaries, memory/eviction counters, mapping checksum, and the same warming/stability criterion. Sampled checksums cannot certify exact equivalence. A mismatch requires recreation, not selective rewarming. TTL-time tolerance is declared; no preceding-run warming is reused.

## Finite handover outcomes

The handover clock begins at the external expansion trigger, so migration before cutover is included. Success requires all affected buckets in `NEW` and intended foreground traffic observed on the destination for the configured stability interval. Idle/bursty intervals with insufficient affected requests are `traffic_stability_inconclusive`, not invented confirmation; the run continues until evidence or deadline.

At the finite deadline, incomplete handover terminates as `handover_timeout` with outstanding work and no-progress reasons. Under the specified primary source-missing rule, exhausted/expired migration stages terminate `not_warmed`; a completed finite pass may cut over cold keys. Outstanding work cannot defer the common deadline. Infrastructure/measurement faults remain distinct from policy failures. Thresholds, deadline, stability minima and latency target remain provisional until Phases 4 and 7.

## Phase boundary

Phase 2 delivers contracts and pure checks only. It does not implement network clients, request coalescing, token buckets, the router loop, migration workers, experiment execution, or performance measurement. Service containers remain stopped. Phase 3 must implement these interfaces and verify races, timeouts, cancellation, expiry, resource bounds, reset equivalence, and real Redis/PostgreSQL integration.
