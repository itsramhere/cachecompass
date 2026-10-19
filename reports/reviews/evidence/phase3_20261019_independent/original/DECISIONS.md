# Decision records

## DECISION-0001: Use the existing native Windows runtime with Linux Docker services

Time: 2026-10-09T13:00:00Z
Phase: 0
Context: Approved inspection found CPython 3.12.10, Docker Desktop and WSL2. Ubuntu has Python 3.12.3 and Redis but Docker integration is unavailable; native Docker CLI exists.
Options considered: Native PowerShell/Python plus Desktop Linux engine; configure WSL integration; install another runtime/toolchain.
Decision: Native PowerShell and project-local Windows CPython 3.12.10 virtualenv; use existing Desktop Linux engine without changing WSL integration.
Reason: Uses installed supported components and avoids system installation/settings changes. Explicit installation paths handle the sandbox PATH/access differences.
Effect on correctness, comparability, or claims: CPython Windows amd64 lock only; Linux containers provide services. Single-machine shared-resource limitations remain. No alternate platform certification.
Verification: bootstrap-rerun.json and doctor-001.json exit 0; phase0-health-001 completed with four verified real-client checks. Full paths in reports/phase_00.md.

## DECISION-0002: Pin exact wheels and image digests; use checksums for source identity

Time: 2026-10-09T13:10:00Z
Phase: 0
Context: Parent Git repository is unborn; Python packages and Docker tags otherwise permit moving inputs.
Options considered: Create a nested repository/commit; pin version tags alone; retain source fingerprints plus wheel hashes and image digests.
Decision: Source/config SHA256 manifest, seven hash-locked Windows wheels, and immutable official Redis 7.4/PostgreSQL 17 image digests. Record resolved package/server versions.
Reason: Identifies the actual local state without altering the unrelated parent repository. Pool package has its own release cycle; lock its resolved version separately.
Effect on correctness, comparability, or claims: Fingerprints exclude mutable reports/runs/venv/wheels/secrets and explicitly define canonical input serialization. Health artifacts contain their execution source snapshot. No novelty/performance claim.
Verification: scripts/validate_phase0.py passed nine checks; reports/source_state.json agrees with executed doctor/health source checksum a657f503705b75d360cf31f8ef0d3aa38f20b31751ad0fa003f00223ca4ee005.

## DECISION-0003: Use disposable startup quotas and preserve uncalibrated workload values

Time: 2026-10-09T13:10:00Z
Phase: 0
Context: Machine has roughly 15.2 GiB visible RAM and six physical cores. The plan requires bounded caches and resource accounting but capacity calibration is Phase 4.
Options considered: Unlimited containers; provisional bounded quotas; claim safe rates before calibration.
Decision: Three Redis servers with 32 MiB maxmemory/allkeys-lru and 128 MiB/0.5 CPU container quotas each; PostgreSQL 512 MiB/1 CPU. Health client pool max sizes are 4/cache and 2/DB. Do not create a purported runnable performance workload with invented safe rates.
Reason: Small health environment fits available resources and records enforceable limits. Foreground/warm-up pool partitioning belongs to later request-path design.
Effect on correctness, comparability, or claims: Quotas may change with documented Phase 4 calibration. No evidence yet of sustainable rates, limited headroom or expansion penalty. Provisional 100 ms target is not frozen.
Verification: reports/environment.json records enforced CPU/memory limits; phase0-health-001/results.json verifies 32 MiB Redis maxmemory/allkeys-lru for all three servers. Performance calibration remains pending.

## DECISION-0004: Characterize existing mechanisms with strong matched comparisons

Time: 2026-10-09T17:43:00Z
Phase: 1
Context: Relevant primary sections establish R02 as nearest verified direct approach; R06/R07/R12 show coordinated migration or control; verified G01 engineering guidance substantially overlaps the proposed joint mechanism. R13 full text is inaccessible.
Options considered: Claim a new combination; change research topic; retain scope as transparent reproduction-inspired characterization.
Decision: Same-scope characterization, with explicit testable incremental-admission/DB-warmup coupling versus R02-inspired migration-before-cutover, adaptive-budget migration-before-cutover and isolated-action controls. No first-controller claim.
Reason: Matches the plan's fallback when essentially identical joint mechanisms are found. Failure boundaries and adequacy of simple migration-before-cutover remain useful falsifiable results.
Effect on correctness, comparability, or claims: No paper's reported gain is this project's gain. Architecture differences are explicit; no claim to reproduce full Memcached/switch/HCI implementations. Phase 2 must implement fair resource/metadata/timeout/finite-completion comparisons. AdaptCache access limits novelty conclusions.
Verification: docs/LITERATURE_MATRIX.md, docs/CANDIDATE_CONTRIBUTION.md and H1/H4 in docs/HYPOTHESES.md; primary PDF and pinned guide provenance retained.

## DECISION-0005: Keep literature extraction tools separate and evidence immutable

Time: 2026-10-09T17:43:00Z
Phase: 1
Context: Twelve primary PDFs need verifiable page indexes; runtime dependency lock and historical experiment inputs must remain stable.
Options considered: Add PDF libraries to runtime lock; rely only on online snippets; isolate a hash-locked extraction tool and archive full primary reading evidence.
Decision: pypdf 6.1.1 installed only under reports/tools/python, separately pinned in requirements-literature.lock. Store PDF/text hashes, effective configs, UTC/durations, failed responses and named verification outputs; never overwrite a retrieval ID.
Reason: Reproduces review inputs without adding a research runtime dependency. Relevant-section reading remains a manual assessment distinct from extraction validation.
Effect on correctness, comparability, or claims: Retrieval/structural checks cannot prove semantic interpretation or novelty. Search coverage is targeted; future availability/rankings may change. No runtime experiments or Phase 0 services were altered.
Verification: reports/evidence/phase1/tool-install-001.json, retrieval manifests, their verification.json files and reports/verification-phase1.json.

## DECISION-0006: Use bounded exact demand windows and conservative positive residency evidence

Time: 2026-10-18T18:07:00Z
Phase: 2
Context: Admission needs causal demand-weighted readiness, but an unbounded key history or future trace oracle would bias policies; destination eviction/expiry may invalidate completed copies.
Options considered: Unbounded exact history; approximate sketches immediately; bounded exact counters over a registered finite dataset and fixed window ring.
Decision: Begin with a configuration-bounded key registry and exact counters in fixed retained subwindows, with explicit overflow that invalidates exact-coverage claims. Count a key warm only after fresh positive destination evidence; expiry, observed miss/eviction, reset, or staleness invalidates it. Report key-count and past-request-weighted coverage separately.
Reason: This gives deterministic causal semantics and measurable metadata/CPU cost before introducing approximation. Conservative unknown residency prevents completed tasks from being mistaken for usable cache content.
Effect on correctness, comparability, or claims: Every policy receives the same bounded metadata and no future accesses. Overflow and stale evidence lower readiness or invalidate exact claims. Memory is proportional to configured registry/active-window bounds and must be measured later; no scale/performance claim follows.
Verification: `tests/test_phase2_contracts.py` covers future rejection, per-bucket bounds, overflow-weighted coverage, and unknown/expired/evicted/stale residency; test-002 exit 0.

## DECISION-0007: Separate foreground and discretionary resources and charge every issued retry

Time: 2026-10-18T18:07:00Z
Phase: 2
Context: Warm-up could otherwise monopolize DB/cache connections, cancellation could mint budget, and aggregate DB counts could double-count existing misses.
Options considered: One shared pool/rate; priority queue over one pool; distinct bounded foreground/background pools and token ledgers.
Decision: Use separate bounded foreground DB/cache and background DB/donor/destination quotas, bounded workers/coalescing, finite attempt timeouts/retries, and operation/byte charges for every issued attempt including failure, timeout, cancellation, and retry. Existing foreground DB demand includes unrelated application demand; candidate admission adds only estimated incremental misses.
Reason: Resource isolation makes comparisons implementable and prevents discretionary work from suppressing required foreground reads. Separate units retain bottleneck meaning and exact retry accounting.
Effect on correctness, comparability, or claims: All compared policies share maxima and foreground semantics. Budget remains a calibrated heuristic rather than a safety guarantee; delayed signals and unequal query costs remain limitations.
Verification: Typed `ResourceLimits`, `RetryPolicy`, task/attempt/request records, admission arithmetic, and focused tests; real cancellation/pool behavior remains Phase 3.

## DECISION-0008: Classify six controls and require finite completion for every policy

Time: 2026-10-18T18:07:00Z
Phase: 2
Context: Phase 1 found substantial prior overlap and requires strong migration-before-cutover and isolated-action comparisons. Pausing forever could appear to protect latency while failing expansion.
Options considered: Treat every adaptive variant as a candidate; compare only immediate cutover; explicitly classify controls and use one common completion/deadline rule.
Decision: Immediate cutover, migration-before-cutover, adaptive-budget migration-before-cutover, fixed gradual handover, warmup-only adaptation, and traffic-only adaptation are experimental controls. `joint_control` is the sole candidate policy. All include pre-cutover work in handover time and must reach all `NEW` plus observed stable intended traffic before a common finite deadline or report failure.
Reason: This supports the characterization position and separates coupling from adaptive migration or admission alone. A simple control matching joint control remains a valid result.
Effect on correctness, comparability, or claims: No novelty or gain is asserted. Policy rates, thresholds, schedules, deadlines, and tuning remain provisional until calibration/pilot freeze.
Verification: `policy_catalog()` and `docs/POLICIES.md`; catalog-classification test passed in test-002.

## DECISION-0009: Resolve Phase 2 behavioral choices before implementing runtime

Time: 2026-10-18T18:40:00Z
Phase: 2 / independent review and correction
Context: The submitted 13-test suite passed, but 12 new negative tests exposed 15 assertion failures. Semantic inspection also found missing batch/grant interfaces, destination-specific coverage, retry/cross-tick allowance and lifecycle/reset/control rules. See ISSUE-0006 through ISSUE-0008.
Options considered: Pass high-level intent to Phase 3; build runtime to discover the missing rules; finish the contracts and exact algorithms while leaving numerical tuning to calibration.
Decision: Add docs/PHASE2_EXECUTION_CONTRACT.md as normative behavioral detail and align architecture/schemas/policies. Use atomic expected-epoch batches; replacing finite grants with conservative byte reservations; positive retry-aware new-minus-old DB load plus pending reserve; immutable bounded observation/coverage provenance; exact pressure/ramp/pass/schedule rules; shielded shared fills with creator deadlines and bounded connection-discard cleanup; independent offered schedules; fresh disposable caches and full initial summaries; fixed measurement horizons and per-subwindow stability evidence.
Reason: These choices affect correctness, comparability and policy outcomes. Namespace isolation does not reset physical cache memory/eviction history. Old-owner lower credit avoids adding displaced misses twice; unknown data earns zero credit.
Effect on correctness, comparability, or claims: Six controls retain matched foreground/resource/metadata/ordering rules, with their declared differences in admission/soft-pressure adaptation. Source-missing keys can finish a finite pass cold, explicitly accounted. Strict deadlines can cause valid policy failures. Numerical capacities, margins, sample minima, ramps and thresholds remain uncalibrated. No runtime protection or improvement is certified.
Verification: Final 39 tests pass (exit 0, 0.005 s), reports/reviews/evidence/phase2_20261018_1821/tests_complete.json, linked to the retained 25-test negative run (exit 1, failures=15). Final 69-file SHA256: fc85008dd9b76d6d3e7d3c3d1ef5359264a11604631b6699a7e505e9733bdd41. Earlier 38-test passes/captures remain intermediate evidence. Full audit: reports/reviews/phase_02_independent_20261018_1821.md.

Supplement, 2026-10-18T18:58Z: The pressure classifier needs a signal producer while caches/DB are idle and migration paused. Specify a common finite PING/INFO/same-query DB sampler, identical across all policies, using bounded background pools and independent fixed observation grants. It cannot assert residency. OBSERVATION_DATABASE is charged separately in allowance and global DB reconciliation. No samples or runtime were generated; only interfaces, accounting arithmetic and algorithm obligations were verified. This closes a startup specification gap without presuming UNKNOWN is SAFE.

## DECISION-0010: Keep Phase 3 orchestration functional and physically recreate caches for repeatability evidence

Time: 2026-10-18T20:37:04Z
Phase: 3
Context: Phase 3 must exercise expansion and verify mechanisms without implementing or tuning the Phase 5/6 comparative policies. Namespace-only cache reset cannot establish equivalent physical Redis state under bounded memory/LRU.
Options considered: implement a preliminary comparative controller; run two namespaces on reused Redis processes; use one fixed donor-first pass and recreate the verified disposable Compose project for each equivalent run.
Decision: Use one deterministic fixed functional pass with explicit finite grants, one forced donor miss for budgeted DB warming, atomic `OLD -> COPYING -> ELIGIBLE -> NEW` publication, and a fixed observation round. The two-run entry point removes and recreates only the verified `paper2-research` project before each run, then compares complete logical initial states and disjoint Redis run IDs.
Reason: This verifies the Phase 3 request/migration/accounting/reset mechanisms while respecting the phase boundary. Physical recreation avoids allocator/LRU history reuse that a namespace cannot remove.
Effect on correctness, comparability, or claims: The Phase 3 gate can assess functional correctness and repeatability. All smoke rates, thresholds, grants, key counts and deadlines remain provisional. The run is not evidence about policy performance, calibrated headroom, or measured gains.
Verification: `reports/evidence/phase3/cycle-003.json` exit 0; both final exact-source runs completed. `reset-comparison-final-002.json` passes transition, complete-state, distinct-instance, checksum, fingerprint and accounting checks.
