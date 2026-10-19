# Testable hypotheses

These hypotheses are planned, not experimental findings. The study characterizes an application-managed, immutable-data, two-to-three independent-cache expansion with one PostgreSQL backend and one router. [Prior-work comparison](LITERATURE_MATRIX.md) and [candidate contribution](CANDIDATE_CONTRIBUTION.md) delimit the claims. No policy or performance runner exists yet.

All outcomes are measured from the externally triggered expansion, including warming and migration before any cutover. Use an identical open-loop offered schedule and dataset per paired seed, equivalent initial old-cache state, bounded memory/eviction/TTL, shared foreground timeouts, coalescing and connection limits. Rejected, late, failed and unfinished requests remain in offered-request accounting. Future accesses cannot inform online demand or admission estimates.

Let V be the fraction of all offered requests in a fixed observation horizon that fail or miss the provisional end-to-end latency target (currently 100 ms, measured from scheduled arrival). Also report latency excess, per-window violations, goodput, DB foreground/background operations including retries, donor bytes/load, routing traffic share and full-handover time T. Unfinished handovers are deadline failures, not discarded observations. Compare V together with T and completion probability; permanent non-progress cannot count as protection.

Phase 4 must calibrate safe DB/query-mix capacity and rule out router/load-generator bottlenecks. Pilot data selects tuning grids, finite handover deadline, horizon, repeat count and practical-effect margins; freeze them before main runs. Results use paired run-level differences and uncertainty, not individual requests as independent replicates. A confidence interval spanning the support boundary is inconclusive; directional opposition can refute a hypothesis. Frozen settings and exclusions remain prerequisites, not completed Phase 1 work.

## H1: joint adaptation under changing headroom

Prediction: when unrelated foreground DB demand changes during expansion, adapting both discretionary DB warmup and incremental bucket admission reduces V against well-tuned fixed schedules, while meeting the same finite handover deadline without an unacceptable completion-time penalty. Also compare against the nearest R02-inspired migration-before-cutover control, including a version with adaptive migration budgets.

Manipulation: keep offered application load and initial state paired; vary external DB interference (steady spare capacity, shrinking headroom, bursts, recovery). Resource changes must be real measured DB work/quotas, with the same interference timeline across policies. A read-count budget is restricted to the calibrated query mix; varying query cost is a sensitivity test.

Refutation: fixed or adaptive migration-before-cutover meets the deadline with equivalent/lower V within frozen practical margins, or joint adaptation helps only by postponing completion beyond the common deadline. No assertion of advantage when complete reassigned resident data fits, donors have ample headroom and membership can change after copying. If the available experiment never exhibits a real expansion penalty, efficacy testing is uninformative and Phase 4 must say so.

## H2: causal demand weighting saves transfer work

Prediction: under stable skew and limited migration opportunity, weighting candidate keys by past estimated demand per byte lowers transferred bytes for a matched achieved warmed request coverage and completion target, relative to FIFO/hash order and recency order. This is a workload-dependent effect, not novelty of hot-key migration.

Manipulation: same budgets, donors, registry, eligibility rules, target and horizon; change only transfer ranking. Compare strong recency selection as well as FIFO. Evaluate uniform, stable skew, hot-set shifts and mixed object sizes; report estimator/metadata overhead and DB reads alongside bytes.

Refutation: demand weighting uses equivalent/more bytes to reach matched coverage, or apparent savings result from leaving more affected requests cold, more DB work, or missing the completion target. Uniform demand and sudden shifts should reduce or reverse the benefit. Coverage is computed from past requests and confirmed residency; future-trace coverage may appear only in explicitly offline analysis. Demand weighting being no better than recency is a valid negative result.

## H3: delayed observations and donor pressure bound usefulness

Prediction: observation delay, stale demand estimates and donor congestion erode any H1 advantage; conservative pausing should reduce additional discretionary work but can miss a finite completion deadline. Joint control has a limited useful operating region.

Manipulation: vary observation age/noise, donor competing reads or quotas, and destination pressure independently where possible, under paired application/interference schedules. Include zero estimated DB headroom, coarse buckets, underestimated miss cost, TTL expiry and eviction sensitivities. Log action reasons and issued work rather than infer behavior from aggregate CPU.

Refutation: advantages remain within the frozen equivalence margins throughout the prespecified delay/pressure range, so the predicted loss is not observed; alternatively even fresh signals/available donor capacity yield no advantage, undermining the claimed useful region. Do not generalize beyond the tested range. A budget overrun with stale inputs refutes any guarantee claim; the budget remains an admission heuristic.

## H4: coupling matters beyond independent adaptation

Prediction: with shared observations and equal tuning effort, jointly evaluating proposed bucket-induced misses and warming against one remaining DB allowance improves the V/T trade-off over warmup-only and traffic-only adaptation. Demand selection alone cannot be credited for coupling.

Manipulation: ablate only the specified adaptive decision while keeping demand priority, signal windows, safety reserve, maximum budgets and foreground semantics fixed. Include adaptive-budget migration-before-cutover to separate fine-grained admission from throttling.

Refutation: either isolated adaptive policy or adaptive migration-before-cutover matches/dominates joint control within frozen margins, or improvement disappears after equal tuning/metadata overhead. If a contribution survives only one selected workload, report that scope explicitly. All baseline tuning and negative outcomes must be retained.

The initial executable policy definitions, estimators and accounting contracts are a Phase 2 dependency; this document supplies hypotheses and decision criteria without fabricating calibrated rates or completed evaluations.
