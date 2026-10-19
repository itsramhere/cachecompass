# Phase 2 invariant checklist

These are implementation requirements for Phase 3 and validation requirements for later runs. Checked items are specified and represented by Phase 2 contracts; they do not claim live-system verification.

The [normative execution rules](PHASE2_EXECUTION_CONTRACT.md) resolve exact algorithms and cross-record/lifecycle obligations. Constructors validate local records; required behavior such as atomic publication and permit cleanup remains unimplemented.

## Ownership and correctness

- [x] Stable seeded mapping; Python process-randomized `hash()` is forbidden.
- [x] Old/final maps are immutable per run; only affected buckets migrate.
- [x] `OLD -> COPYING -> ELIGIBLE -> NEW` is sequential and irreversible.
- [x] `OLD`, `COPYING`, and `ELIGIBLE` retain old foreground ownership.
- [x] One atomic monotonic routing epoch is published per transition action.
- [x] A submitted request captures one epoch/bucket/owner and retains it through completion.
- [x] The primary immutable read returns DB-authoritative bytes on a miss; hit counters alone cannot certify correctness.
- [x] Copies preserve absolute expiry and never extend TTL.
- [x] `NEW` foreground reads do not fall back to an old cache in the primary comparison.

## Bounds, failures, and cancellation

- [x] Foreground cache, foreground DB, background donor/destination, and background DB pools have explicit finite limits.
- [x] Migration workers, in-flight requests, and coalescing entries are bounded.
- [x] Every operation has a finite request/attempt timeout and every retry policy has finite attempts/backoff.
- [x] Issued failed/timed-out/cancelled/retry work is charged; cancellation creates no token credit.
- [x] Permits and coalescing entries are released in terminal cleanup paths.
- [x] Followers have individual deadlines/accounting; follower cancellation does not incorrectly cancel shared work.
- [x] Discretionary warming never occupies the foreground DB quota or suppresses required foreground DB reads.

## Causality, demand, and readiness

- [x] Policy inputs end no later than their decision time and include observation age.
- [x] Future trace arrivals are inaccessible to policy/demand interfaces.
- [x] Dataset/key registry, keys per bucket, retained windows, and active metadata are bounded.
- [x] Exact tracked counts and explicit overflow replace silent sampling/sketching.
- [x] Key-count coverage and past-demand-weighted warmed coverage are separate metrics.
- [x] Only fresh confirmed destination evidence counts as warm.
- [x] Unknown, evicted, expired, or stale residency contributes zero warmed coverage.
- [x] Existing foreground DB demand includes unrelated application DB traffic and excludes discretionary warm-up.
- [x] Proposed bucket load uses a retry-aware new-owner miss bound, without adding old-owner attempts again; pending admission reserves prevent repeated allowance use before telemetry catches up. Conservative overlap is explicitly logged.
- [x] Stale/unknown safety signals pause affected discretionary work/admission.
- [x] A common bounded pressure sampler supplies idle/paused signals without assuming absence is safety; its cache/DB operation classes and DB allowance charge are explicit and identical across policies.

## Fair comparison and accounting

- [x] Policies share cache memory/eviction/TTL, request timeout, coalescing, connection/worker ceilings, retry semantics, metadata, initial state, and configured key ordering unless explicitly ablated.
- [x] Every request/migration action names source, owner(s), timeout, and work/accounting class.
- [x] Scheduled arrival, submission, terminal time/outcome, captured owner/epoch, source, attempts, and coalescing are explicit.
- [x] Every offered request receives one record; errors, timeouts, refusals, cancellations, and non-submissions remain visible.
- [x] Donor reads, destination writes, discretionary DB reads, foreground DB reads, retries, and bytes have separate counters.
- [x] Metrics loss or reconciliation failure invalidates measurement rather than improving a policy result.

## Reset and termination

- [x] Comparative runs recreate verified disposable cache instances and namespaces; namespace-only shared-cache resets are functional diagnostics. Broad unverified flush is forbidden.
- [x] Paired policies use the same dataset/mapping/offered schedule/initial warming manifest.
- [x] Destination begins empty and no preceding-run warming is reused.
- [x] Initial state uses full sorted key/value/TTL summaries, identical warming order and counters within declared TTL tolerance; sampled summaries do not certify primary-comparison equivalence.
- [x] Handover time includes pre-cutover warming/migration.
- [x] Success requires every affected bucket `NEW` plus observed intended traffic for a finite stability interval.
- [x] Idle traffic is inconclusive evidence; it cannot satisfy stability by absence.
- [x] A finite deadline produces explicit success, handover timeout/policy failure, invalid measurement, or infrastructure failure with outstanding work accounted.

Phase 3 must add behavioral tests and real-client integration evidence before these become verified implementation invariants.
