# Decision records

## DECISION-0013: Repeat the complete Phase 4 matrix after independent accounting and deadline corrections

Time: 2026-10-19T03:54:00Z
Phase: 4 independent review
Context: Submitted calibration lacked common probes/isolated cache pools and a latency-stability criterion, while analysis hard-coded capacity. The first corrected independent matrix then reproduced an expired-acquisition orphan in the DB adapter under overload; diagnostic trace and deterministic regression establish the cause. Original results cannot certify corrected claims.
Options considered: reuse favorable runs; relabel client issuance stops as database capacity; correct the common paths and repeat the complete prespecified comparison.
Decision: Preserve every original/first-review artifact, fix the demonstrated race and accounting/validation defects, and replace all calibration/control/immediate/headroom runs with fresh linked `p4final_*` IDs under the unchanged rates, SQL CPU work, quotas, retry counts, latency target and fixed windows. Record same-query probe demand separately. Capacity remains conditional on the query/host/pool configuration and measured overhead; run/pair uncertainty is exploratory with three repetitions.
Reason: The fixes affect issued work, workload and observation timing. Full reruns avoid selecting only successful measurements. The frozen review protocol and amendment precede replacement confirmation; no later policy is implemented.
Effect on correctness, comparability, or claims: Original `C_safe=24` and gate are withdrawn. A final gate requires raw-valid capacity, headroom and attributed positive/negative characterization. Driver failure is not DB capacity; conservative reservations are not measured traffic. If essential evidence is still absent, Phase 4 remains unmet.
Verification: `submitted_negatives.json`, `expired_acquisition_before.json`, `expiry_corrected.json`; final source and actual-client/rerun records under `reports/reviews/evidence/phase4_20261019_independent/`. Final 107-check live suite and all 16 replacement runs pass raw validation; two regenerated analyses match bytes/CSV/raw/SVG coordinates. The independent review passes Phase 4 for the attributable 24.6–38.4 ms paired penalty with explicit conditional capacity and uncertainty limits. Services are down; stop before Phase 5.

## DECISION-0012: Use a real PostgreSQL CPU-bound query mix and freeze a small Phase 4 confirmation matrix

Time: 2026-10-19T02:50:00Z
Phase: 4
Context: The 1,200-round actual-query pilot showed cold misses but no material DB pressure even at 192 rps. The 20,000-round PostgreSQL query variant had p95 near 60 ms at 12/24 rps and exceeded 200 ms at 36 rps.
Options considered: retain a non-constraining query mix; add fixed client/server sleeps; increase deterministic SQL CPU work under the existing one-CPU PostgreSQL quota.
Decision: Use the measured 20,000-round SQL query mix, retain the 100 ms provisional target, confirm DB rates 12/24/36 and matched immediate/control expansion runs at 36 rps, three independent repetitions each.
Reason: It creates actual DB work and a finite capacity knee without disguising a sleep as database pressure. The matrix is small enough for repeated physical resets.
Effect on correctness, comparability, or claims: Findings apply only to this PostgreSQL query mix, container quota, local host and 100 ms provisional threshold. No Phase 5 policy or improvement claim follows.
Verification: `docs/PHASE4_CONFIRMATION_PROTOCOL.md`; raw pilots under `runs/p4cal_pilot_cpu20k_*` and `runs/p4exp_pilot_*`.

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
Verification: scripts/validate_phase0.py passed nine checks; reports/source_state.json agrees with executed doctor/health source checksum a657f503705b75d360cf31f8ef0d3aa38f20b31051ad0fa003f00223ca4ee005.

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
Verification: Final 39 tests pass (exit 0, 0.005 s), reports/reviews/evidence/phase2_20261018_1821/tests_publication.json, linked to the retained 25-test negative run (exit 1, failures=15). Final 69-file SHA256: fc85008dd9b76d6d3e7d3c3d1ef5359264a11604631b6699a7e505e9733bdd41. Earlier 38-test passes/captures remain intermediate evidence. Full audit: reports/reviews/phase_02_independent_20261018_1821.md.

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

## DECISION-0011: Complete Phase 3 runtime obligations without changing policy foreground semantics

Time: 2026-10-18T22:08:25.778452+00:00
Phase: 3 independent review/correction
Context: Ten negative runtime failures, actual TTL extension and failed-cancel cleanup reproduction contradicted the submitted PASS. Prior contract/owner tests were insufficient.
Options considered: accept happy-path evidence; defer lifecycle/resource/accounting choices to policies; enforce the reviewed obligations now and preserve every failure.
Decision: shared post-connection issuance, bounded cancel/drain/discard and quarantine, deferred creator accounting, generation-renewed reservations, independent empty-start tokens/encoded grants, separate pools and priority observations, fixed independent offers/horizon/stability, complete raw validation and physical resets. Add an original-expiry envelope/write receipt; identify the two existing fixed diagnostic deletes separately and forbid them in comparative/calibration workloads. Exclude ignored outputs/local state from canonical source identity while retaining historical definitions.
Reason: These changes close observed mechanism/provenance defects rather than tune comparative policies. See ISSUE-0017 through ISSUE-0020 and normative clarification.
Effect on correctness, comparability, or claims: All policies retain the same foreground source/owner/deadline/retry/coalescing rules and shared resource/metadata costs. Cache encoding gains 12 bytes; callers consume conservative write receipts. Full wire bytes remain unknown where not measured. No new capacity, safety, performance or novelty claim. Phases 4 onward remain unstarted.
Verification: 90 final checks including 17 actual-client cases, 39 repeated-run audits, exact-source accounted policy failure, preserved historical/source bytes; independent review `reports/reviews/phase_03_independent_20261019.md`. Final SHA256 8454ae425d5546a546d59e1b7b2258b4ec1c844eebb35e2609f7a4ab98e15c19.

## DECISION-0014: Complete six Phase 5 controls through shared mechanisms

Time: 2026-10-19 UTC
Phase: 5
Context: User authorizes Phase 5 only; the original five-control plan omits the
adaptive-budget migration comparator required by corrected Phase 2/H1/H4.
Decision: implement all six experimental controls; reject joint_control in the
Phase 5 factory. Use the same router, physical pools, retries, observations,
expiry, scheduler, empty-start tokens, finite passes, byte limits and cleanup.
Reason: isolates documented warming/admission controls without privileged
ordering or a separate foreground path. No full ElMem reproduction is claimed.
Verification: focused checks, full actual-client suite, bounded matrix and raw
validation under reports/evidence/phase5/. No commit or push is authorized.

## DECISION-0015: Supplemental cloud-host mixed-pool operating check and finite pilot

Time: 2026-10-19 UTC
Phase: 5
Context: Available checkout initially ended at Phase 3. Fast-forwarded configured
origin to user-named a659f237c1f2940d83b714814e0bbf458f009c5d, preserving both
unrelated cloud run directories. Windows local path is not mounted here.
Decision: retain the actual 20,000-round SQL mix, image digests/quotas and 4/1
DB pools on Linux Python 3.12.14. The two predeclared 8+2 and 12+2 mixed-pool
checks both pass including the fixed 2/s probes. Select total 16 attempts/s
and subtract 2/s reserve plus probes, foreground and planned warming/pending.
Reason: Phase 4's 24 foreground/s is not an uncharged total DB allowance and
its Windows host does not certify this pool mix on this cloud host.
Effect: conditional functional smoke configuration only, no peak capacity,
saturation or improvement claim. Two settings per control, then fresh seed606
comparisons; unsuccessful settings remain. Final evaluation freezing is Phase7.
Verification: mixed_validation_v1.json, mixed_selection.json; protocol registered
before runs. Ordinary sandbox network failed and automatic review once failed
with model-capacity error; the identical reviewed fetch then succeeded.

## DECISION-0016: Preserve positive-coverage validity through decision time

Time: 2026-10-19 UTC
Phase: 5
Context: A coverage snapshot can be fresh while a credited key expires between
collection and publication. Complete closed demand windows also need a bounded
open slot that cannot evict their oldest closed data during collection.
Decision: reserve one extra open subwindow, preserve immutable closed snapshots,
and include the earliest credited expiry/evidence-age deadline per bucket in
ControllerObservation. Remove coverage credit after that deadline at decision.
Reason: avoids admitting on expired positive evidence without uncharged probes.
Effect: conservative, possibly excessive estimated load; not a safety guarantee.
The refinement happened during development tuning before traffic_only_adaptation
ran. Earlier immediate/fixed/all-at-once settings do not consume coverage for
admission; all fresh comparison smokes load the corrected shared implementation.
Per-run source manifests remain the exact authority; registration identity is
not misrepresented as a frozen evaluation identity. No extra tuning points.
Verification: coverage_expiry_checks.json, final complete live suite, and
matched fresh smoke source identities. No Phase 6 implementation.


## DECISION-0017: Independent corrected common-profile matrix

Time: 2026-10-19 UTC
Phase: 5 independent review
Context: Fourteen reproduced semantic/accounting failures and two reproduced
selection failures invalidate reuse of owner comparisons. Independent A/B
selection could give warmup-only a different fixed handover schedule and
traffic-only different fixed warming rates. The owner mixed checks omit 4/s W.
Options considered: retain individual profile selection and accept confounding;
choose a common A/B profile after equal pilot effort; expand tuning substantially.
Decision: preregister docs/PHASE5_INDEPENDENT_PROTOCOL.md; perform exactly two
mixed splits, 12 equally allocated tuning cases, one shared aggregate-profile
selection, six fresh seed606 comparisons, and three explicit failure boundaries.
Keep the original two-point ranges. Add pool-derived active-count hysteresis;
retain all other thresholds. No search extension or favorable ranking criterion.
Reason: isolates the required behavioral differences under common constraints
without pretending a two-point grid establishes optimal settings.
Effect: all older runs and the blocked v2 command remain preserved, but none
certifies the corrected runtime. Capacity is conditional total-attempt accounting,
not saturation or universal safety. No Phase6 code or later evaluation claim.
Verification: initial selection negatives tuning_before.json; corrected full
157-test live suite live_frozen.json; matrix p5ind_20261019_m1 in progress.

## DECISION-0018: Replace all first-review cases after token-clock defect

Time: 2026-10-19 UTC
Phase: 5 independent review
Context: Independent replay stopped warmup-only tune4A despite process completion;
recorded deficits and a fresh deterministic negative establish inconsistent token
balance/event clocks. The earlier 157-test source and first-review matrix are
superseded, including favorable cells. The outer 180-second recorder timeout is
separately recorded as ISSUE-0033, not a policy failure.
Decision: use one balance-change clock for token events, retain replay tolerance,
archive the old runtime and add the advancing-clock regression. Repeat the full
matrix on stable corrected source, with one extra adaptive zero-budget boundary
to test cold atomic cutover for both migration controls.
Effect: no Phase6 work, no relaxed limits, no favorable-case reuse. New full suite
has158 checks including23 actual-client cases. Protocol amendments bound all
additional measurements. Verification: token_clock_before/corrected.json,
token_replay_diagnostic.json, live_lower_final.json and final matrix raw audits.

## DECISION-0019: Retain failed16 operating point; test one lower common12 point

Time: 2026-10-19 UTC
Phase: 5 independent review
Context: Corrected-source mixed12+2 with fixed2/s probes has full raw/payload
reconciliation and p95s within100ms, but max dispatch52.376628ms exceeds50ms.
The matrix stopped before tuning. This is a rejected operating setting, not DB
saturation; PostgreSQL averaged about0.38 core with no added throttling count.
Options considered: relax dispatch assertion; retry16 until favorable; stop
without corrected comparisons; preregister one conservative lower common point.
Decision: preserve the negative and unchanged criteria, then check total12 with
8+2 and6+4 real queries plus2/s probes. Both must pass before the same fair
A/B tuning and fresh smokes proceed. No other point or automatic retry allowed.
Reason: the plan permits empirical operating parameters; lowering is a new
conditional choice, not a claimed fix for unexplained host scheduling jitter.
Effect: all controls receive identical total12/reserve2 and the same profile
selection rule. The failed16 result remains visible, accepted limitation
ISSUE-0035. No general capacity/safety or controller improvement claim.
Verification: both final lower mixed cases pass raw validation and criteria;
full p5ind_20261019_m3 matrix executing under archived stable source.
