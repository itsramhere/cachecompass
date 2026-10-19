# Implementable experimental policy specifications

All policy names and classifications match `cache_scaleout.policies.policy_catalog()`. Six policies are **experimental controls**. `joint_control` is the **candidate policy**. “Adaptive” does not itself imply a candidate contribution. No policy has been run, tuned, or shown to improve performance.

The [normative execution rules](PHASE2_EXECUTION_CONTRACT.md) fix the algorithms, configuration domains, finite stage/source-missing behavior, pressure classification, budget ramping and stability/reset semantics. Numerical parameters remain configurable; the algorithm itself is specified there.

## Shared inputs, ordering, and outputs

At each control interval policies read only causal ControllerObservation data: bounded past demand, fresh/aged residency, current bucket states/epoch, foreground DB attempts including unrelated traffic, discretionary and common-sampler DB work separately, and pressure summaries. They receive versioned configuration and the finite registry, never future accesses. Every policy uses the same bounded pressure sampler while idle or paused; sampler work is accounted and its DB rate subtracted from allowance. A key-residency probe remains disabled.

Every policy produces `ControllerAction`: finite-validity donor operation/byte, destination-write, and discretionary DB-operation budgets; an ordered set of eligible bucket admissions; and reason codes. The scheduler expands this only into `MigrationTask` records with explicit source, owners, timeout, retry, expiry, and accounting class. A no-work action is still emitted.

Unless the key-ordering ablation is active, every warming policy uses the same configured deterministic order. The primary demand order is descending closed-window requests saved per registered object byte, followed by most recent past access and stable `(bucket, key)` ties. FIFO/hash and recency are separate declared ablations. Shared metadata overhead is measured for every policy, including controls that do not consume demand estimates.

Eligibility is separate from admission. A finite migration pass captures the affected registry at expansion. A bucket becomes `COPYING` when its pass starts and `ELIGIBLE` after every captured task has a terminal disposition under the policy's source-missing rule. Unknown or failed keys remain non-warm. `ELIGIBLE` does not mean complete residency.

Every policy uses the same finite handover deadline and success/stability rule from [ARCHITECTURE.md](ARCHITECTURE.md). It also shares foreground semantics, memory/TTL/eviction, connection and worker maxima, finite retry behavior, source availability, initial state, and tuning effort. Pilot-selected rates and thresholds are configuration, not constants in this specification.

## Experimental controls

### `immediate_cutover`

Purpose: diagnose the cold-remapping penalty.

- At the expansion trigger, publish all affected `OLD -> COPYING -> ELIGIBLE -> NEW` transitions as one atomic epoch action; the intermediate states are explicit transition records with no migration work between them.
- Donor and discretionary DB warm-up budgets are zero. Foreground cache-aside demand populates the new owner.
- All post-trigger requests capture the new owner; in-flight pre-trigger requests finish against their old captured owner.
- It succeeds after the shared traffic-stability rule or fails at the common deadline.

This is a diagnostic control, not a serious contribution baseline by itself.

### `migration_before_cutover`

Purpose: strong fixed ElMem-inspired warm-before-membership control, without claiming an exact reproduction.

- At expansion, move every affected bucket to `COPYING` and run one finite donor-first pass using fixed pilot-selected token rates and bounded workers.
- A donor miss may use a DB warm-up read only under the fixed discretionary DB rate. Source-missing/exhausted tasks terminate as `not_warmed`; they do not retry forever.
- When the entire pass terminates, mark all affected buckets `ELIGIBLE`, then atomically admit all of them in one epoch. No admission occurs earlier.
- Pressure is observed/logged but does not change fixed rates; hard safety failures/timeouts still terminate work according to shared resource contracts.

The migration interval counts toward handover time. Full key-count migration is not assumed if eviction, expiry, missing donor data, bounded capacity, or deadline intervenes.

### `adaptive_budget_migration_before_cutover`

Purpose: isolate adaptive migration throttling from incremental/adaptive traffic handover.

- Uses the same finite pass, donor-first source rule, ordering, and all-at-once admission as `migration_before_cutover`.
- On fresh safe observations, adjusts donor and discretionary DB budgets within configured ceilings using the same increase/decrease/hysteresis rules as `joint_control`.
- Unsafe/stale/unknown DB observations set DB warm-up to zero. Unsafe/stale/unknown donor/destination observations reduce or pause corresponding transfer work.
- It never admits a partial bucket set. When the pass terminates, it admits all affected buckets regardless of observed warmed coverage, subject only to the finite deadline and explicit policy rule.

This control tests whether adaptive transfer alone is adequate.

### `fixed_gradual_handover`

Purpose: matched fixed joint schedule.

- Runs fixed donor and optional DB warm-up budgets chosen on pilot conditions.
- At each configured fixed schedule tick, considers the next `ELIGIBLE` buckets in stable configured order and admits up to the fixed bucket count, without adapting to observed pressure/coverage.
- If a scheduled bucket is not yet `ELIGIBLE`, the action logs `fixed_schedule_waiting_for_eligibility`; later buckets do not leapfrog unless the frozen configuration explicitly permits it for every compared run.
- Schedule origin, interval, per-tick count, and rates are frozen before evaluation.

This supplies the “fixed gradual handover” baseline and includes all warming time.

### `warmup_only_adaptation`

Purpose: isolate adaptive warm-up/transfer budgets.

- Uses exactly the adaptive donor/DB/destination budget logic, signal freshness, hysteresis, and ceilings of `joint_control`.
- Traffic follows the same fixed admission schedule and bucket order as `fixed_gradual_handover`, even if the adaptive coverage estimate would choose otherwise.
- An unsafe signal may pause background work but does not alter a scheduled admission once its bucket is `ELIGIBLE`; the resulting outcome remains measurable.
- A schedule tick blocked by ineligibility is recorded and does not create catch-up bursts beyond the frozen fixed rule.

Comparing this with fixed gradual and joint control attributes effects to warming adaptation versus coupling.

### `traffic_only_adaptation`

Purpose: isolate adaptive admissions.

- Uses the identical fixed migration/prefetch token rates and ordering as `fixed_gradual_handover`.
- At each tick, stale/unknown/unsafe DB, donor, destination, demand or foreground-rate evidence pauses new admissions. Apply the same consecutive-safe-window rule as joint control. Otherwise compute allowance after foreground demand, pending admissions and the fixed planned DB attempt rate.
- For each eligible candidate in ascending bucket order, compute its retry-aware miss bound from past request rate, lower warmed coverage, and uncertainty. Charge pending admissions from earlier ticks until represented in a fresh foreground window. Admit sequentially while cumulative load fits allowance and the cap; skip candidates that do not fit.
- Donor pressure cannot adapt the fixed donor rate, but unsafe/stale/unknown donor signals pause adaptive admissions. Shared hard limits still apply.

This tests traffic adaptation without adaptive warming.

## Candidate policy

### `joint_control`

Purpose: characterize joint causal control of background data arrival and incremental traffic ownership.

For every interval:

1. Reject future-dated observations. Classify DB, donor, and destination samples by pressure and age. Pause admissions unless all signals and demand/foreground estimates are fresh/safe for the configured consecutive windows.
2. Set DB warming to zero and pause admissions if DB evidence is unsafe/stale/unknown. Otherwise compute `remaining = C_safe - reserve - foreground_db_rate_upper - pending_admission_db_rate_upper - observation_db_rate_upper`; ramp DB warming after consecutive safe windows within allowance/ceiling.
3. Independently reduce/pause donor and destination budgets on their unsafe/stale/unknown evidence; increase them gradually after their safe-window rule. Units remain donor operations/bytes and destination writes/bytes, never an arbitrary combined rate.
4. Schedule donor-first tasks in the shared causal demand-per-byte order. Permit DB fallback only with a discretionary token. Charge every issued retry.
5. Recompute fresh residency-derived key and warmed-request coverage. `UNKNOWN`, expired, evicted, and stale evidence contributes zero.
6. Subtract the full planned discretionary DB attempt rate and pending-admission reserve once. For each `ELIGIBLE` bucket in ascending bucket order, add only the positive difference between retry-aware new-owner misses (including cold uncertainty) and the conservative old-owner lower rate already represented in foreground demand. Unknown old-owner estimates earn zero credit. Accumulate charges within allowance and cap.
7. Atomically publish all selected admissions as one next routing epoch. Emit exact observations, budgets, estimates, actions, rejected candidates, and no-progress reasons.

The normative supplement specifies additive ramping, multiplicative unsafe donor reduction, immediate zeroing on stale/unknown signals, exact-window/rolling-max estimators, and safe-window counting. Parameters, ceilings and admission caps are calibrated/tuned later and frozen before evaluation. Permanent freezing is not success: the common deadline yields `handover_timeout` with non-progress evidence.

## Fairness matrix

| Policy | Warm-up budget | Traffic admission | Role |
| --- | --- | --- | --- |
| Immediate cutover | none | all immediately | Experimental control |
| Migration before cutover | fixed | all after finite pass | Experimental control |
| Adaptive-budget migration before cutover | adaptive | all after finite pass | Experimental control |
| Fixed gradual handover | fixed | fixed schedule | Experimental control |
| Warmup-only adaptation | adaptive | fixed schedule | Experimental control |
| Traffic-only adaptation | fixed | adaptive allowance | Experimental control |
| Joint control | adaptive | adaptive shared allowance | Candidate policy |

Demand ordering is held constant across this matrix. FIFO/hash and recency comparisons change only ordering. Baselines receive separate pilot tuning under the same budget and information constraints; a simple policy that matches or dominates joint control is a valid characterization result.

## Required configuration before execution

An experiment cannot instantiate these policies until configuration supplies: fixed/adaptive donor and DB ceilings/bursts; worker/pool maxima; observation/subwindow widths and maximum ages; exact registry bounds; safe-window/hysteresis/ramp rules; calibrated `C_safe`, reserve, and pressure thresholds; coverage uncertainty rule; fixed schedule and admission cap; source-missing disposition; retry/timeout rules; deadline and traffic-stability sample rule. Phase 2 intentionally assigns no calibrated values.
