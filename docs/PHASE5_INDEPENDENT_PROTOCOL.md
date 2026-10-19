# Phase 5 independent correction protocol — 2026-10-19

Registered before corrected live tests, mixed checks or tuning. This supersedes
the owner pilot's replacement plan for review eligibility; historical records
and all failures remain unchanged. Starting review source and negative tests:
reports/reviews/evidence/phase5_independent_20261019_051928/.

Run exactly two supplemental mixed checks (12 foreground +2 warm-up/s, then
10+4/s), each with 8 seconds of real offers, the same 4/1 DB pools, 20,000-round
query, 1024-byte objects, one-CPU DB, and fixed 2/s DB observations. Both must
have full raw reconciliation, correct payloads, no failures, p95 <=100 ms for
each real class and maximum dispatch delay <=50 ms. Only then use the nominal
total 16 attempts/s, inclusive of observations, with 2/s reserve. Stop if either
fails; no expanded search. This tests the previously missing 4/s warming ceiling.
It is a conditional short-run operating setting, not DB saturation, universal
capacity, or a safety guarantee. Observations are charged once in total issue
counts and once as their own allowance term; real classes exclude probes.

Keep the owner's A/B ranges, 512 keys, FIFO/hash ordering, timing, retries,
burst limits, pressure thresholds, and common workload. Every control gets
exactly two tuning cases with seed 505, including two immediate repetitions.
Select one common A/B profile for the six fresh comparisons: minimize the
aggregate tuple (number of policy failures, sum of all-offer latency violations,
sum of full handover times with an 8-second penalty for noncompletion, A tie).
The immediate repetitions are excluded from this score because they have no
settings. If all five warming controls fail under both profiles, use A.
Record individual preferences as diagnostics only. This fixes the owner's
independent selection confound: warmup-only must retain the fixed control's
handover schedule, and traffic-only must retain its warming rates. It also fixes
the code's failure to apply its stated A fallback when both settings fail.
This two-point common profile is provisional, not an optimality claim.

The corrected classifier also retains in-flight work across slots and exposes
active counts. Register explicit active-count hysteresis before these runs:
DB lower/upper 3/4, cache 8/9, derived from the common bounded pools. Existing
latency, queue, memory, rate and age thresholds are unchanged. These thresholds
classify observed pressure; they do not certify spare capacity.

Persist selection before six fresh matched smoke cases with seed 606. Reconcile
all offers, operations, token acquisitions/returns, grants, admissions, payload
provenance, residency, terminal key outcomes and actual-traffic stability.
All cases use physical service resets and the same initial contents. Run three
additional boundaries: zero warming budgets with finite cold outcomes; a short
handover deadline; and adaptive handover with admission cap zero (non-progress).
Policy failures are valid outcomes; invalid measurement/infrastructure stops
the matrix for diagnosis. Every observation loop stops at the common horizon.

Maximum 23 measurement cases: 2 mixed +12 tuning +6 smoke +3 boundaries. Each
child has a 90-second watchdog; expected 10–15 minutes, upper bound 35 minutes.
Full service-free and actual-client suites run first. Six live control tests
also exercise source misses and budgeted DB fallback; these are functional
checks, not calibration or comparison measurements. No runtime/source changes
during the matrix. Any further correctness defect requires a finite amendment
before rerunning affected cases. Never overwrite evidence or weaken assertions.
Services are label-verified and shut down with disposable volumes in finally.
No Phase 6 implementation, superiority claim, commit or push is in scope.

## Finite replacement after token-clock replay failure

The first review matrix stopped on tune4A: token-event replay found destination
deficits of 5.273550848 and 2.629566464 reserved bytes (ISSUE-0034). A fresh
deterministic advancing-clock negative reproduces credit before the recorded
rate start. Preserve all first-review records and sources, including the outer
recorder timeout and incomplete-lifecycle tune3A described in ISSUE-0033.
Token balance changes and event timestamps now share one clock boundary. Do not
increase replay tolerance or reuse these cases as corrected evidence.

Before replacement, repeat the full actual-client suite and archive the new
source. Execute a complete new frozen matrix: the same two mixed checks, twelve
tuning and six fresh smokes with unchanged ranges/selection/constraints, plus
the three registered boundaries and one zero-budget adaptive migration boundary.
The extra boundary directly tests cold-key atomic cutover in both migration
controls; it is not a tuning setting. Maximum 24 replacement measurements,
36 total review measurements (12 retained first-review cases, including the
orchestration-interrupted case). No further search. Each case keeps its 90-second
watchdog; the outer command capture allows 2100 seconds. Source/runtime remains
unchanged during replacement; use fresh IDs linked to available old cells.


## Lower operating point after a retained dispatch failure

The corrected-source replacement m2 stopped at its first mixed check. All 112
real queries and 20 DB probes reconciled and payloads matched; foreground p95
60.165 ms and warming p95 51.832 ms passed, but maximum foreground dispatch
52.376628 ms exceeded the frozen 50 ms limit. This is a rejected operating case,
not DB saturation or an implementation failure. Do not relax its assertion,
repeat the same point until favorable, or exclude the negative from reporting.

Before any new tuning, permit one finite lower common operating choice only:
total12 including 2/s probes, with the unchanged 2/s reserve. Test splits 8+2
and 6+4 real queries/s under the same fixed observer, query, resources and strict
eligibility criteria. Both must pass; otherwise stop with gate unmet. Lower
load is a conservative new parameter, not a claimed causal remedy for host
scheduling jitter. No larger grid or automatic retry is allowed.

If both pass, execute the same 12 tuning, six fresh smoke and four boundary
cases once under this common12 rate, unchanged A/B ranges, scoring, workload
and all other constraints. Capture a new frozen source and full live suite.
Maximum24 further measurements; 37 review cases including the13 preserved
first-review/m2 cases. No earlier matrix is promoted to corrected inference.
The script accepts explicit --total-db-rate 12 or16; default12 reproduces this
registered lower attempt. The validator derives the required two pool splits
from the recorded total and observation charge, never infers universal capacity.
