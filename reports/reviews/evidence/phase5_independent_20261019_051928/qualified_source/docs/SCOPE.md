# Research scope

Working title: Backend-Budget-Aware Cache Scale-Out through Adaptive Warm-Up and Traffic Handover.

## Question and architecture

Study whether joint adaptation of warm-up and traffic handover reduces transient latency-target violations relative to strong migration/handover baselines when backend and donor headroom change. The candidate contribution and novelty remain unverified until Phase 1 and evaluation.

The planned system has one Python asynchronous router/controller, two existing independent Redis cache servers, one provisioned healthy empty Redis destination, one authoritative PostgreSQL database, an open-loop generator, and optional unrelated database traffic. One expansion event occurs per run. The router will implement application-managed cache-aside reads with seeded SHA-256-derived bucket ownership (initial proposal: 256 buckets, mapping seed 2026), rather than native Redis cluster resharding. Ownership and migration progress remain separate; bucket transitions are OLD -> COPYING -> ELIGIBLE -> NEW, with irreversible admission in the initial experiment.

Initial workload data are immutable. Every policy will use bounded cache memory, allkeys-lru eviction, no TTL for the primary comparison, identical foreground timeouts and DB connection quotas, centralized per-key miss coalescing, and no foreground donor fallback after cutover. TTL preservation needs separate correctness checks in Phase 3. Background donor copies and DB prefetch consume separate budgets; neither is free. Discretionary DB warming must not monopolize foreground connections. These are design requirements, not implemented request-path behavior in Phase 0.

## Latency and completion definitions

Provisional application target: 100 ms, with a provisional 2,000 ms foreground timeout. Both must be justified using Phase 4 calibration and frozen in Phase 7. End-to-end latency starts at the scheduled open-loop arrival and includes dispatch delay, coalescing waits, DB connection waits, cache/database work, and retries through completion or timeout. Record scheduled arrival, actual submission and completion separately. Successful-request percentiles must be labeled and accompanied by timeout/error/drop accounting.

Latency violation rate = primary application requests exceeding the target, timing out, failing, or being dropped / all offered primary application requests. Unrelated DB traffic is measured separately and is not added to this denominator. Load-generator non-submissions are accounting events and may invalidate measurement; system refusals are outcomes.

Handover time starts at expansion trigger and ends when every affected bucket has final ownership and intended observed traffic satisfies the declared stability interval. Initial proposals are a 180 s deadline and 15 s traffic stability interval. Warming before cutover is inside this time. Infeasible/no-progress outcomes remain visible. C_safe, offered load, realized headroom, pressure thresholds, and any controller advantage remain uncalibrated.

## Phase 0 implementation boundary

Implemented now: native Windows PowerShell setup/shutdown, digest-locked Linux Docker services, Python dependency locking, doctor/environment evidence, and disposable client read/write/cleanup checks. The environment health configuration is configs/environment.json. It is not an experimental workload configuration. CPU/memory limits in infra/compose.yaml are startup proposals; they do not establish a DB bottleneck or safe capacity.

## Deferred and unsupported work

Provisioning decisions and VM boot time; simultaneous additions, scale-in, multi-region and production deployment; Byzantine failures and distributed consensus; arbitrary concurrent writes; multi-router coordination; GPU/ML/RL. Phase 8 may add a bounded single-router mutable-data extension with coordinated writes/invalidation after primary correctness. Direct DB writers remain unsupported without explicit implementation.

No correctness or performance claim follows from service health. A single machine has shared-resource interference; Phase 4 must profile and attribute bottlenecks. The original literature-review Markdown is preserved as background and is not the literature foundation. No publishing, paid resources, system software installation, or virtualization changes are included.

