# Research implementation plan: safe cache expansion with limited database headroom

## 1. Purpose and execution contract

This document is a handoff to an AI implementation agent. It specifies a research prototype, its evaluation, and the evidence needed to write a defensible paper.

**Original topic:** Preventing cache expansion from temporarily slowing down an application.

**Original research question:** How should a new cache server receive data and traffic when database spare capacity is limited?

**Working research question:** Can joint adaptation of cache warm-up and traffic handover reduce latency-target violations during cache scale-out, compared with strong migration and handover baselines, when database and donor-cache headroom change?

**Working title:** Backend-Budget-Aware Cache Scale-Out through Adaptive Warm-Up and Traffic Handover.

The title and proposed contribution are provisional. Implementation success does not establish novelty, improvement, or publication readiness.

### Instructions to the implementing agent

1. Read this entire document and `AGENT_REPORTING_TEMPLATES.md` before starting. Read any applicable `AGENTS.md` instructions in the implementation workspace.
2. Inspect existing files and preserve unrelated work. The existing literature-review Markdown is background material; do not overwrite it. It mixes cache domains and is not the literature foundation for this project.
3. Execute phases in dependency order. Independent work inside a phase may proceed concurrently when it does not conflict. Do not create multiple agents unless the user or applicable workspace instructions authorize delegation.
4. Passing a phase gate permits progression without requesting routine user approval. Pause dependent work only for missing authority, an essential unavailable resource, a material scope change, or an unresolved failure that invalidates the next phase.
5. Treat configuration values below as initial proposals. Record changes with reasons; freeze evaluation settings before the main experiments.
6. Never invent commands that have run, observations, references, improvements, or successful tests. Distinguish planned, implemented, executed, and verified work.
7. Use the reporting protocol in the companion file throughout the project. Every material error must have a traceable issue record, including its debugging attempts and resolution evidence.
8. Build a local research system. These instructions do not authorize production changes, paid infrastructure, external publication, or installation requiring additional permissions.
9. Deliver runnable code, exact configurations, raw evidence, analysis, and a manuscript or evidence-backed findings report. A promising simulator alone is an intermediate result.

## 2. Scope, assumptions, and non-goals

### Required first implementation

- Application-managed cache-aside reads with deterministic key ownership.
- Two existing independent cache servers and one new cache server.
- One authoritative database.
- One router/proxy that owns the routing configuration and runs the experimental controller.
- One open-loop load generator and one optional database-background-load generator.
- One expansion event per experimental run.
- Immutable data for the initial correctness and primary policy implementation.
- Bounded cache memory with a fixed eviction policy across comparisons.
- CPU execution. No GPU, model training, or reinforcement learning is required.

Use independent cache instances rather than native cluster resharding in the first implementation. The router controls the transition so that the experimental policies are explicit and comparable. Document that this architecture differs from products that migrate keys during native resharding.

Start with Python, an asynchronous Redis client, a pooled PostgreSQL client, and Docker Compose on Linux or Windows with a suitable Linux-container environment. Verify support and pin actual versions during Phase 0. If profiling demonstrates that the Python router is the bottleneck, optimize the measured bottleneck or move its request path to Go; log the evidence and decision first.

### Deferred work

- Deciding when to provision another server: the experiment triggers expansion externally.
- Cloud VM boot and deployment time: the new cache is provisioned, healthy, and empty before the measured expansion event.
- Multiple simultaneous additions, scale-in, multi-region operation, or production deployment.
- General Byzantine failures, distributed consensus, or universal zero-degradation guarantees.
- Mutable-data correctness beyond a bounded extension explicitly evaluated in Phase 8.

Do not present deferred work as implemented. In particular, a read-only experiment cannot support a claim of safe migration under arbitrary concurrent writes.

## 3. Design constraints and research model

### Resources to protect

Track database request load and latency, donor-cache latency and transfer load, destination-cache latency and memory, and router/load-generator resource usage. Low database CPU usage alone is not proof of spare capacity.

Define `C_safe` as a calibrated sustainable database read rate for a specific query mix and latency target. Define `F` as all foreground database reads, including background application traffic that is unrelated to cache expansion. Define `W` as discretionary background warm-up reads from the database.

The initial equal-cost-read model is:

```text
F + W <= C_safe - safety_reserve
```

For a proposed traffic transition, the controller should use a conservative estimate:

```text
upper_foreground_estimate
  + upper_incremental_misses_from_candidate_transition
  + planned_background_DB_reads
  <= C_safe - safety_reserve
```

Do not count transferred traffic's previous database reads twice. Do not treat cache-to-cache transfer as free: it consumes donor CPU, network, and destination write capacity. If requests have unequal database costs, a read-count budget may be inadequate; restrict the primary claim to the measured query mix or add cost-weighted evaluation.

The budget is an admission heuristic, not a formal guarantee. Delayed measurements, query-cost changes, and bursts can invalidate it. Measure those limitations.

### Routing and bucket state

- Use a stable, explicitly seeded hash, such as SHA-256-derived rendezvous hashing. Do not use Python's process-randomized `hash()` for ownership.
- Assign keys to a fixed number of virtual buckets; begin with 256 or 1,024 and record the chosen value.
- Compute old and final owners for each bucket. Only buckets whose final owner is the new node participate in the handover.
- Keep routing ownership separate from migration progress. A bucket may contain copied data while still serving foreground requests on its old owner.
- Publish routing changes atomically in the single router. Record a monotonically increasing routing epoch.
- Maintain a simple state progression: `OLD -> COPYING -> ELIGIBLE -> NEW`. `COPYING` and `ELIGIBLE` still use the old foreground owner. `NEW` uses the new owner.
- Admission of a bucket is irreversible during the first read-only experiment. Under unsafe conditions pause future admissions; do not add an untested rollback mechanism.
- A request captures one routing epoch and foreground owner. It may complete using that captured owner while the next request uses the new epoch.
- Track estimated warmed request coverage separately from key-count coverage. A bucket containing many cold, unpopular keys can still be useful; a bucket missing one hot key can still cause substantial load.

A bucket cutover controls a fraction of the affected keyspace, not an exactly uniform fraction of requests. Log both ownership fraction and observed traffic share. Increase bucket granularity if a single bucket causes unsafe steps.

### Cache semantics

- On a miss, perform one authoritative database read and populate the current foreground owner.
- Use per-key request coalescing for concurrent misses in every policy. Document that coalescing is centralized and does not imply a multi-router solution.
- Hold fixed the cache memory, eviction policy, TTL semantics, database pool limits, and foreground timeout across compared policies.
- The primary comparison does not use foreground fallback to old caches after bucket cutover. Background warm-up may read donor caches. If foreground peer fallback is studied later, enable it consistently across applicable baselines and measure donor traffic.
- During migration, copy only keys that belong to the new node under the final ownership map. Keep old copies subject to the same bounded-memory and expiration rules; do not give a policy free unbounded replicas.
- Do not extend an item's original expiration deadline when copying it. The primary immutable-data experiment may use no expiry, but TTL behavior must have separate correctness tests.
- A failed donor read may lead to a database warm-up read only when the warm-up budget permits it. Foreground database reads must not silently disappear when warm-up is paused.

### Target repository structure

Create this structure as the implementation develops; this is not a claim that it currently exists:

```text
configs/                 versioned workload, policy, and experiment settings
src/cache_scaleout/      router, ownership, cache/DB clients, telemetry, policies
tests/                   invariants, controller logic, and service integration
infra/                   local container definitions and startup checks
scripts/                 experiment entry points and environment capture
analysis/                raw-data validation, statistics, and plotting
docs/                    scope, literature, architecture, methodology, findings
reports/                 phase reports, decisions, issues, and current status
runs/<run_id>/           immutable experiment inputs, events, results, and logs
paper/                   manuscript, bibliography, and claim-evidence map
```

Use Git revisions if a repository exists or is established within the authorized workflow. Otherwise record source/configuration checksums. Do not require a commit or a clean worktree to start; record the exact source state used.

## 4. Phase-by-phase execution

### Phase 0 - Inspect the environment and establish the execution record

**Objective:** Make the work reproducible and determine what can run on the available machine.

**Instructions:**

1. Inspect files, workspace instructions, available disk/RAM/CPU, Python, Git, container tooling, and whether Linux containers can run. On Windows, distinguish native PowerShell from WSL paths and processes.
2. Verify software compatibility from official documentation and pin supported versions. Do not silently install system software, enable virtualization, or purchase resources.
3. Create `docs/SCOPE.md`, `reports/STATUS.md`, `reports/DECISIONS.md`, and `reports/ISSUE_INDEX.md` using the companion templates.
4. Record the workload architecture, read-only initial scope, latency-target definition, and deferred work.
5. Create the project skeleton and dependency lockfile. Provide one documented bootstrap path and one clean shutdown path.
6. Start minimal cache and database services and run connection/read/write health checks using disposable test data in the research namespace.
7. Capture an environment manifest: OS, runtime and package versions, container image digests, resource limits, hardware, and relevant settings. Do not dump secrets or the complete environment.

**Deliverables:** Scope document, environment manifest, pinned dependencies, startup instructions, initial status report.

**Gate:** The chosen runtime works and all required local services pass health checks. If containers are unavailable, a simulator and literature work may continue, but actual-system validation remains pending; do not mark the full environment phase complete.

### Phase 1 - Rebuild the literature base and state testable hypotheses

**Objective:** Establish what the proposed study adds and what strong comparisons are required.

**Instructions:**

1. Read the relevant sections of these primary sources, not only their abstracts:
   - Scaling Memcache at Facebook: https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf
   - ElMem: https://www3.cs.stonybrook.edu/~anshul/icdcs18_elmem.pdf
   - Bonfire: https://www.usenix.org/conference/fast13/technical-sessions/presentation/zhang
   - Cache warm-up characterization: https://www.usenix.org/conference/hotcloud20/presentation/zhang-lei
   - Twitter cache workloads: https://www.usenix.org/conference/osdi20/presentation/yang
2. Search for newer work on elastic caching, migration throttling, warm-up, traffic handover, backend overload protection, and load-aware cache routing. Search the joint mechanism, not just the proposed title.
3. Build `docs/LITERATURE_MATRIX.md`. For each source record bibliographic details, architecture, data source, transfer policy, traffic policy, treatment of backend/donor limits, workload, findings, and limitations with section/page references.
4. Distinguish direct scale-out work from adjacent storage-cache research. Record unverified or inaccessible papers explicitly.
5. Write `docs/HYPOTHESES.md` with falsifiable hypotheses. Initial candidates:
   - Joint control reduces transient latency violations compared with separate fixed schedules under changing headroom.
   - Demand-weighted migration reduces unnecessary transferred bytes under skewed access.
   - Delayed signals or donor bottlenecks define conditions where the controller loses its advantage.
6. State what would refute each hypothesis. Include cases where migration-before-cutover is already adequate.
7. State the candidate novelty narrowly. Do not claim that database-aware scaling, hot-key copying, feedback throttling, or warm-before-cutover is new by itself.

**Deliverables:** Literature matrix, bibliography with verified links, hypotheses, candidate-contribution statement.

**Gate:** The nearest prior approach is identified and at least one testable difference is documented. If essentially identical joint control already exists, continue with a transparent reproduction/characterization study within the existing scope and flag the novelty limitation. Request direction only if a materially different topic or contribution is needed.

### Phase 2 - Specify interfaces, invariants, and experimental policies

**Objective:** Remove design ambiguity before building the request path.

**Instructions:**

1. Write `docs/ARCHITECTURE.md` with component ownership, the request path, migration path, observation path, and bucket transitions.
2. Define typed interfaces for the ownership map, cache client, database client, key-demand tracker, migration scheduler, controller, and metrics sink.
3. Specify policy inputs and outputs. A policy sees only past/current observations and controls transfer budgets and eligible bucket admissions. It cannot inspect future trace accesses.
4. Specify the key registry and demand tracker. Track observed keys by bucket with bounded metadata. Begin with exact counters over a bounded window; document memory/CPU cost before adopting sketches.
5. Define how copied-key readiness becomes invalid after expiration or observed eviction. Unknown residency must not automatically count as warm.
6. Define single-router request coalescing, connection limits, timeouts, and cancellation cleanup. All foreground timing includes waiting for coalesced reads and DB connections.
7. Specify event schemas: `run_id`, UTC timestamp, monotonic elapsed time, phase, routing epoch, bucket, policy action, observed pressure, and reason. Per-request records also contain scheduled arrival, actual submission, completion/timeout, latency, owner, and hit/miss source.
8. Define finite migration retries with backoff. Count retry work against budgets. Foreground retries must be identical across policies and included in request latency.
9. Define reset semantics. Each run gets an isolated cache namespace or isolated disposable instances and equivalent initial warming. Never issue broad flushes against an unverified shared service.
10. Document all invariants, including stable ownership, bounded concurrency, no unauthorized DB prefetch, no data loss, no expiry extension, and truthful request accounting.

**Deliverables:** Architecture and interfaces, event/data schemas, invariant checklist, baseline specifications.

**Gate:** Every request and migration action has an explicit data source, owner, timeout, and accounting rule. Policy definitions are implementable without guessing.

### Phase 3 - Implement and verify the minimal system

**Objective:** Build a correct system before tuning performance.

**Instructions:**

1. Implement dataset creation, stable key/bucket mapping, two-cache initial membership, and three-cache final membership.
2. Implement the asynchronous request path, cache-aside reads, bounded DB connection pool, and per-key miss coalescing.
3. Implement an isolated new-cache instance, selective donor copying, bounded workers, and a background DB warm-up limiter.
4. Implement bucket-state transitions and atomic routing-epoch publication.
5. Implement telemetry and a deterministic small-run configuration. Capture action reasons, not just resource counters.
6. Test meaningful failure modes: simultaneous misses, a cutover during an in-flight read, donor timeout, DB timeout, cancellation, expired copied data, and destination memory pressure.
7. Verify returned payloads against expected dataset values. Do not rely on hit-rate counters as a correctness check.
8. Test repeated execution and reset: two runs using the same seed must begin from equivalent cache states without reusing warmed data from the preceding run.
9. Add service integration tests for the actual Redis/PostgreSQL clients. Simulator-only checks cannot certify integration correctness.

**Deliverables:** Working request/migration path, invariant tests, service integration results, small end-to-end run.

**Gate:** Correctness tests pass; every offered request is accounted for; unexpected DB reads and unbounded workers are absent; runs reset cleanly. Open correctness bugs block performance claims.

### Phase 4 - Calibrate capacity and reproduce the expansion penalty

**Objective:** Demonstrate that the chosen testbed actually exhibits the problem.

**Instructions:**

1. Measure the DB latency-versus-load curve for the actual query mix using open-loop arrivals. Identify a conservative `C_safe` below the latency knee and record confidence/variation over repeated measurements.
2. Separately profile router, cache, and load-generator capacity. They must have sufficient headroom for the intended DB-bottleneck experiment.
3. Apply documented CPU/memory limits or controlled competing DB work to create limited headroom. Label resource constraints and artificial background workloads. Fixed sleeps may support simulator checks but must not be the only evidence for real-database behavior.
4. Warm the old caches with a reproducible prefix until their hit rate and request latency are stable by a documented criterion. Use equivalent initial contents for every policy.
5. Add the healthy empty node at a fixed event time and switch affected buckets immediately. Record pre-event, transition, and post-event metrics.
6. Confirm increased cold misses, DB pressure, and latency degradation. Identify whether misses, migration, or some other bottleneck explains the change.
7. Choose dataset size, object sizes, request skew, cache memory, and load based on this calibration. Do not assume nominal Redis memory equals payload capacity.
8. If the penalty is absent, inspect key remapping, initial residency, database buffering, TTLs, load-generator throughput, and measurement boundaries. Report the result honestly; do not manufacture slowdown through an unfair baseline.

**Deliverables:** Calibration curves, `C_safe` settings, reproducible immediate-handover penalty, diagnostic explanation.

**Gate:** The baseline penalty is measurable and attributable to cache expansion, or a documented negative characterization explains its absence. A negative result blocks claims of improvement on this testbed but does not justify inventing evidence.

### Phase 5 - Implement strong baselines

**Objective:** Establish that any improvement comes from the proposed coordination.

Implement these policies behind the same interfaces and request path:

1. **Immediate:** Cut over all affected buckets immediately; populate on demand.
2. **Fixed joint schedule:** Rate-limited warming and fixed incremental bucket handover, with rates selected on separate pilot conditions.
3. **Migration then cutover:** Copy available reassigned donor data at a bounded rate, use a documented bounded policy for source-missing keys, then cut over. This is an ElMem-inspired baseline, not a claim of an exact ElMem reproduction.
4. **Adaptive warming only:** Adapt transfer/prefetch budgets, but keep traffic handover on the fixed schedule.
5. **Adaptive handover only:** Adapt bucket admission while keeping transfer/prefetch rates fixed.
6. **Joint adaptive:** Implemented in Phase 6.

Use demand prioritization consistently when isolating the effect of joint control. Compare FIFO versus demand-weighted key ordering as a separate ablation rather than giving only the joint policy better key selection.

**Additional instructions:**

- Tune baseline parameters on pilot workloads rather than deliberately choosing weak rates.
- Give every policy the same memory, connection limits, source data availability, timeouts, and initial cache state.
- Where observation/demand tracking is shared, include its overhead and explain that choice. A policy's additional computation must remain visible.
- Include warm-up delays in expansion completion time; migration-before-cutover does not get to hide its migration interval.
- Do not call a simplified baseline a full paper reproduction. Specify every material difference from the published approach.

**Deliverables:** Baseline code, parameter specifications, tuning record, reproducible comparison smoke runs.

**Gate:** The five baseline policies execute correctly and differ only in their documented controls; the sixth, joint policy is delivered in Phase 6. Failures caused by a baseline's legitimate resource constraints remain results; failures caused by implementation bugs must be fixed before comparison.

### Phase 6 - Implement the joint adaptive controller

**Objective:** Coordinate data arrival and traffic ownership with observable resource limits.

**Instructions:**

1. Start with a simple periodic feedback controller. Make observation interval, smoothing window, safety reserve, pressure thresholds, rate bounds, and admission step configurable.
2. Maintain separate budgets for background DB reads and donor-copy bytes/operations. Do not combine their units into one arbitrary rate.
3. Estimate foreground DB demand conservatively from recent observations, including unrelated foreground/background application queries. Exclude discretionary warm-up reads from that estimate and account for them separately.
4. Build a conservative estimate of extra misses for candidate bucket admissions using observed request demand and estimated resident coverage. Add an uncertainty reserve for cold/unobserved keys.
5. Order migration candidates by estimated requests saved per transferred byte. In the equal-cost-query primary experiment, frequency divided by object bytes is an initial heuristic. Keep popularity estimates causal and bounded.
6. Prefer donor data when available and donor capacity permits. Use DB prefetch only inside its discretionary budget. The first implementation may use one deterministic donor per key; do not build complex replica selection prematurely.
7. If DB or donor pressure crosses its documented threshold, stop discretionary DB warming as appropriate, reduce donor-copy rate, and pause new bucket admissions. Existing foreground traffic continues and all waiting is measured.
8. When safe, increase the appropriate budgets gradually and admit eligible buckets only when the estimated additional DB demand fits the remaining allowance. Include hysteresis or consecutive-safe-window requirements to avoid oscillation.
9. Do not admit a bucket solely because all observed warm-up tasks completed. Readiness is about expected foreground misses, and cache contents may have expired or been evicted.
10. Keep control actions bounded and record their explanation. Log `why no progress` when warming or admission is paused.
11. Define a finite expansion deadline and success criterion: all affected ownership reaches the new node and actual intended traffic is observed for a stability interval. Log idle/bursty periods where traffic-share measurements are inconclusive.
12. If the deadline is exceeded, mark the run `handover_timeout`; do not report a permanently frozen controller as successful overload prevention.
13. Evaluate controller overhead and sensitivity to stale telemetry. Do not add ML until simple control has been measured and a specific shortcoming established.

**Deliverables:** Controller implementation, pseudocode matching the code, action logs, controller-logic tests, integration runs.

**Gate:** The controller respects configured worker/budget bounds, changes both controls when justified, and completes feasible controlled cases. It detects and reports non-progress or infeasible cases without hiding failures. No improvement claim is required to pass this implementation gate.

### Phase 7 - Pilot experiments and freeze the methodology

**Objective:** Validate the measurements and set a manageable experiment plan before seeing final results.

**Instructions:**

1. Pilot steady traffic, a request burst, changing popular keys, limited donor transfer bandwidth, and reduced DB headroom. Keep pilot data separate from final evaluation.
2. Inspect raw request traces against aggregates. Check scheduled arrivals, actual dispatch, errors, timeouts, cache-hit classifications, migration reads, and offered versus completed rates.
3. Use open-loop offered load independent of response time. If dispatch falls behind or the load generator drops requests, record it and invalidate capacity claims for that run. Do not let a slow client silently reduce offered load and improve measured latency.
4. Include the entire transition in the measurement window. Only initial old-cache preparation is outside the primary expansion interval.
5. Check that donor saturation, router overhead, destination memory, or the machine's shared resources are not misidentified as database effects.
6. Define a small primary matrix. An initial proposal is three positive DB-headroom targets crossed with three conditions: stationary demand, shifting popularity, and constrained donor transfer. Add zero-headroom/burst cases as separate boundary tests.
7. Use headroom targets such as 5%, 10%, and 20% of calibrated safe capacity only if the testbed can realize them. Record actual measured headroom, not merely nominal configuration.
8. Include at least five independent repeated runs per primary cell as an initial plan; increase replication if pilot variability makes the conclusions unstable. Randomize policy order and pair workloads/seeds where appropriate.
9. Estimate runtime before launch. Nine cells, six policies, and five repetitions produce 270 runs before boundary tests and trace validation. Reduce the declared matrix transparently if the available compute budget cannot support it; do not prune inconvenient outcomes after evaluation.
10. Choose public trace segments of manageable size, preserve temporal/key relationships, and document every transformation. Do not download a whole massive corpus unnecessarily. Prefer complete time windows over random request sampling.
11. Freeze workload configurations, seeds, metrics, analysis rules, baseline tuning, invalid-run rules, deadlines, and claim criteria in `docs/EVALUATION_PROTOCOL.md`. Save source and configuration fingerprints.

**Deliverables:** Pilot report, sanity-check evidence, frozen protocol, experiment matrix, estimated runtime.

**Gate:** The harness accounts for offered traffic and all failures; resource attribution is credible; final workloads were not selected based on final policy outcomes.

### Phase 8 - Execute the main evaluation and bounded correctness extension

**Objective:** Produce complete, reproducible evidence without selective reporting.

**Instructions:**

1. Implement a manifest-driven experiment runner. Each row identifies policy, workload, seed, resource constraints, source/config fingerprints, and status.
2. For each run: validate services, reset isolated cache state, prepare equivalent old-cache contents, start telemetry, trigger expansion, execute the fixed observation period, and persist raw results.
3. Capture a manifest, effective configuration, event log, request log, metrics, process/resource observations, exit codes, and checksums under `runs/<run_id>/`.
4. Separate statuses: `completed`, `policy_failure`, `invalid_measurement`, and `infrastructure_failure`. A policy timeout or overload is not automatically an invalid measurement.
5. Never overwrite a failed run with its retry. Give the retry a new ID and link it to the original issue and run.
6. If a code bug affects multiple runs, identify every affected run. Retain them marked invalid and rerun the affected comparison set using the fixed revision, not just the joint policy.
7. Run representative trace-based checks after the synthetic matrix. A rescaled trace validates the documented transformed workload, not the original production deployment.
8. Add a bounded mutable-data extension only after the primary system is stable: all writes pass through the single router; update the DB and invalidate affected old/new cache copies under a documented per-key coordination protocol. Serialize migration against writes for the initial correctness implementation.
9. Test a copy racing with an update, a cache miss racing with invalidation, expiry during migration, and cutover during an update. Verify versions/values against DB truth. Explain the coordination overhead and that direct DB writers/multiple routers are unsupported unless explicitly implemented.
10. If the extension cannot be completed, deliver the read-only study with that boundary stated. Do not hide an unresolved consistency bug or broaden the claim.

**Deliverables:** Complete run manifest, raw artifacts, main comparisons, boundary cases, trace checks, mutable-data evidence or explicit limitation.

**Gate:** Every declared experiment has a traceable outcome; invalid/retried runs are preserved; no open bug invalidates the results retained for analysis.

### Phase 9 - Analyze findings and test the proposed contribution

**Objective:** Determine what the evidence supports, including negative results.

**Instructions:**

1. Validate schemas, timestamps, count reconciliation, source revisions, and measurement boundaries before computing improvements.
2. Report transient p95/p99 latency with the observation window and sample count stated. Label successful-request percentiles explicitly; timeouts are censored outcomes, not fast responses.
3. Report latency-target violations over all offered requests, including timeouts, errors, and drops according to the frozen definition. Keep infrastructure-invalid runs separate with reasons.
4. Report handover completion time, success/deadline failures, peak DB pressure, donor impact, transfer bytes, foreground recomputation, and controller overhead.
5. Compare latency protection and expansion speed together. Present a Pareto/trade-off plot or matched-deadline comparison so freezing traffic cannot appear optimal.
6. Compute run-level confidence intervals and paired policy differences where workloads/seeds are paired. Do not treat millions of correlated requests as millions of independent experimental replications.
7. Perform the declared ablations: fixed versus adaptive warm-up, fixed versus adaptive admission, and FIFO versus demand-weighted ordering under otherwise equal controls.
8. Inspect failure regimes: low/no headroom, small/uniform objects, changing popular keys, delayed telemetry, and donor saturation. Explain when migration-before-cutover is already competitive.
9. Create reproducible plots for a representative transition: application latency, foreground/background DB reads, warm-up budgets, donor load, bucket ownership, and actual traffic share over time. State the selection rule for representative runs.
10. Build `docs/FINDINGS.md` and a claim-evidence table. Each claim links to run IDs, configuration, analysis output, uncertainty, and limitations.
11. If joint control does not improve the trade-off, report that result. A sound workload characterization or reproduction may remain useful; do not rewrite hypotheses as if they predicted the outcome.

**Deliverables:** Analysis scripts, figures/tables, confidence intervals, ablations, failure analysis, claim-evidence map.

**Gate:** Every numerical statement is regenerated from retained raw artifacts. Conclusions are no broader than the evaluated architecture, resource regimes, and workloads.

### Phase 10 - Write and audit the paper; hand off the artifact

**Objective:** Produce a reviewable research package, not just a code demonstration.

**Instructions:**

1. Write a manuscript covering the concrete problem, closest related work, assumptions, control policy, implementation, experimental design, results, and limitations.
2. Explain why data-source choice and traffic handover must be coordinated. Clearly distinguish established components from the candidate contribution.
3. Include sufficient calibration and transient plots to substantiate the limited-headroom premise.
4. State whether the work is a novel method, extension, reproduction, or characterization. Do not imply acceptance by a venue.
5. Verify all bibliography entries against primary sources. Do not carry unrelated LLM KV-cache claims from the original Markdown into this paper.
6. Match pseudocode to final code and all numbers to the claim-evidence map. Correctness limitations, policy failures, transformed trace semantics, and single-machine constraints must be visible.
7. Regenerate one small reproduction run and its figures using only the documented commands and pinned inputs. If possible use a separate environment; otherwise state the clean-environment validation limitation.
8. Run the project's meaningful required checks and inspect their exit codes. Do not repeatedly broaden testing after relevant checks pass unless a new change or unresolved concern warrants it.
9. Update `reports/STATUS.md` and the issue index. List open issues, their impact, and exact next steps. Mark fixed issues verified only when their resolution evidence exists.
10. Deliver startup/run/analyze instructions, code/config fingerprints, artifact locations, manuscript, results summary, and limitations. Do not publish, submit, or incur costs without authorization.

**Deliverables:** Manuscript, bibliography, reproducible artifact README, final phase report, completed claim-evidence map, issue ledger.

**Gate:** A reader can reproduce a small experiment, verify the central figures, and understand exactly what was and was not demonstrated.

## 5. Experiment records and metric definitions

Every experiment configuration must explicitly specify:

- Dataset generator or trace source, transformations, seed, key count, object sizes, and query mix.
- Cache count before/after expansion, actual memory limits, eviction policy, TTL behavior, and bucket mapping seed/count.
- Offered load, burst/change schedule, unrelated DB workload, measured headroom, resource quotas, and transfer limits.
- Initial warming protocol, event time, observation horizon, handover deadline, and stability interval.
- Foreground timeout, DB/cache connection limits, retry/coalescing policy, telemetry interval, and controller settings.
- Policy name/version, source fingerprint, config checksum, start/end times, and run validity/status.

Define primary metrics before evaluation:

```text
latency_violation_rate = offered requests that exceed the target,
                        time out, fail, or are dropped / all offered requests

handover_time = time from expansion trigger to complete final ownership
               and the documented observed-traffic stability criterion

background_DB_reads = database reads performed solely for discretionary warm-up

foreground_DB_reads = authoritative reads needed by application traffic,
                      including unrelated application workload
```

For the primary latency metric, `all offered requests` means all requests in the primary application workload. Measure unrelated DB-background traffic separately; do not silently add it to or remove it from the primary latency denominator.

An unsubmitted request caused by a broken load generator is an accounting event and may invalidate the run; a request refused by a studied system policy is a system outcome. State which is which. Record scheduled and actual arrival so request delay is not hidden.

The CLI is to be implemented and documented by the agent, not assumed to exist now. Provide equivalent entry points for environment checks, dataset preparation, one run, a matrix, artifact validation, and analysis. Do not include fabricated successful command output in the README.

## 6. Debugging and progression rules

Use `AGENT_REPORTING_TEMPLATES.md` as the required format. In particular:

1. Open an issue record for each material error before losing its original evidence.
2. Reproduce on the smallest meaningful workload and identify which layer failed.
3. Record a hypothesis, diagnostic action, result, and conclusion for each attempt. A list of edits without observations is not a debugging report.
4. Change one causal variable at a time when practical. If a batch edit is necessary, explain why.
5. Verify both the original reproduction and the appropriate integration/behavioral check after the fix.
6. Name affected runs and invalidate them when warranted. Never silently reuse evidence produced by broken code.
7. Bound retries. After three repetitions of the same unchanged failure, change the investigation strategy or report the precise blocker; do not loop indefinitely.
8. Proceed with independent authorized work while a dependency is unavailable. Do not mark dependent phases complete or imply the issue is solved.
9. Report progress at meaningful checkpoints and at least every 60 seconds during interactive work. The user's final handoff must be self-contained.

## 7. Completion checklist

- [ ] Scope and nearest prior work are documented.
- [ ] The expansion penalty is reproduced or its absence is explained honestly.
- [ ] All policies share fair request semantics and resource limits.
- [ ] The joint controller and its uncertainty assumptions are explicit.
- [ ] Correctness, request accounting, and capacity calibration are verified.
- [ ] Raw transient measurements and failed runs are retained.
- [ ] Completion time is evaluated alongside latency protection.
- [ ] Results, ablations, uncertainty, and adverse regimes are reported.
- [ ] Every paper claim is linked to evidence.
- [ ] A small documented reproduction succeeds.
- [ ] Issue records describe reproduction, debugging, fixes, and verification.
- [ ] Remaining limitations and unfinished work are clearly identified.

Passing this checklist makes the project reviewable. It does not prove novelty, guarantee publication, or establish production readiness.

## Appendix A - Initial configuration and target execution interface

The following is an illustrative starting configuration, not a benchmark result or a ready-to-run file. The agent must implement schema validation, replace calibration-required nulls before performance evaluation, and persist the effective configuration for every run. Initial values may be changed during calibration with a decision record.

```yaml
experiment:
  name: local_scaleout
  workload_seed: 42
  mapping_seed: 2026
  initial_cache_nodes: 2
  new_cache_nodes: 1
  virtual_buckets: 256
  immutable_data: true
  pre_event_observation_seconds: 30
  handover_deadline_seconds: 180
  post_handover_observation_seconds: 60
  traffic_stability_seconds: 15

dataset:
  keys: 100000
  value_bytes: 1024
  ttl_seconds: null  # No expiry in the initial primary experiment.

cache:
  memory_limit_mib_per_node: 32
  eviction_policy: allkeys-lru
  foreground_old_peer_fallback: false
  coalesce_misses: true

workload:
  distribution: zipf
  zipf_exponent: 1.1
  offered_rate_rps: null  # REQUIRED: determined during calibration.
  latency_target_ms: 100  # Provisional target; justify before protocol freeze.
  request_timeout_ms: 2000
  arrivals: open_loop
  background_db_rate_rps: null  # REQUIRED: realized headroom target.

controller:
  observation_interval_ms: 1000
  observation_window_seconds: 10
  consecutive_safe_windows: 3
  safe_db_rate_rps: null  # REQUIRED: calibrated C_safe.
  safety_reserve_fraction: 0.10
  max_bucket_admissions_per_interval: 1
  max_donor_copy_bytes_per_second: 4194304
  max_migration_workers: 4
  max_background_db_workers: 2
  db_latency_pressure_threshold_ms: null  # REQUIRED: from calibration.
  donor_latency_pressure_threshold_ms: null  # REQUIRED: from calibration.
```

This configuration does not guarantee the old caches are overloaded or the database is constrained. Phase 4 must establish both the realized workload and the cause of the transient penalty. Configure foreground and warm-up connection quotas so discretionary warming cannot occupy the entire DB pool. Record any queueing introduced by those quotas.

### Initial control algorithm to implement and then evaluate

```text
every control interval:
    read causal observations and their age
    calculate a conservative foreground DB demand estimate F_upper
    db_allowance = max(0, C_safe - reserve - F_upper)

    if DB signals are unsafe or too stale:
        set discretionary DB warm-up budget to zero
        pause new bucket admissions
    else:
        cap discretionary DB warm-up by db_allowance
        increase budget gradually only after consecutive safe observations

    if donor signals are unsafe or too stale:
        decrease donor-copy budget; pause if necessary
    else:
        increase donor-copy budget gradually within its configured ceiling

    select useful donor-copy/warm-up candidates within those budgets
    update resident-coverage estimates using completed copies and expirations

    for eligible bucket in documented priority order:
        estimate incremental foreground misses caused by admitting this bucket
        admit only if the full planned DB budget still fits the safe allowance
        count the proposed new load before considering the next bucket
        stop after the configured admission-step limit

    publish any ownership change atomically
    log budgets, observations, actions, non-progress reasons, and routing epoch
```

Implement rate enforcement using token buckets plus bounded concurrency, with an explicitly bounded burst allowance. Workers must wait for budget before issuing a background request. Account for the operations/bytes actually issued, including retries and donor misses. Cancellation and timeout must return worker/concurrency permits without creating unlimited budget credit.

Use deterministic fake-clock tests for budget accounting, stale signals, oscillation prevention, and admission decisions. Real-service tests then establish integration behavior. Do not tune the implementation to make fake-clock tests the only evidence of resource protection.

### Target CLI contract

Implement and document equivalent commands below. These are future interface requirements; they have not been executed in this planning task.

```text
python -m cache_scaleout doctor --output reports/environment.json
python -m cache_scaleout prepare --config configs/smoke.yaml
python -m cache_scaleout run --config configs/smoke.yaml --run-id smoke-001
python -m cache_scaleout validate --run runs/smoke-001
python -m cache_scaleout matrix --manifest configs/main_matrix.csv
python -m cache_scaleout analyze --manifest reports/main_manifest.csv --output analysis/results
```

- `doctor` checks prerequisites without silently installing them and exits nonzero for missing required resources.
- `prepare` creates disposable research data and verifies its checksum; it refuses to overwrite an unrecognized existing dataset.
- `run` refuses an existing run ID, saves the effective config, and reports infrastructure/measurement failures distinctly from valid policy outcomes.
- `validate` reconciles request counts, chronology, budgets, configuration, and artifact completeness; it writes a validation report with failed checks.
- `matrix` supports resuming unfinished entries without overwriting existing evidence and preserves linked retries.
- `analyze` reads validated artifacts, reports exclusions explicitly, and writes figures plus the claim-evidence table.

Document setup commands separately for the actual supported shell. Do not assume Bash commands work in PowerShell or that Windows paths work inside containers.

## Appendix B - Planning effort

For a student working part-time, an initial 15-week allocation is: Phases 0-1 about two weeks; Phases 2-3 about three; Phases 4-5 about two; Phases 6-7 about three; Phases 8-9 about three; and Phase 10 about two. This is an estimate. AI coordination can shorten coding work, but calibration, repeated experiments, and novelty assessment still need evidence and may change the schedule.
