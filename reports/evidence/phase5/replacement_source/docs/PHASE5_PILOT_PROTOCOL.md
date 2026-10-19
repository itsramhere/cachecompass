# Phase 5 bounded implementation pilot protocol v1

Registered before any Phase 5 service run. Provisional implementation tuning only;
Phase 7 will freeze evaluation. Six controls; no joint controller. No ranking
criterion is required for the implementation gate.

Starting Git: a659f237c1f2940d83b714814e0bbf458f009c5d, fast-forwarded from
186c3dd. Source/config identities are captured for every command/run.
The cloud host uses Linux Python 3.12.14 rather than the calibrated Windows
Python 3.12.10. Preserve the original 20,000-round SQL mix and quotas. Therefore
a supplemental mixed-pool characterization is mandatory before adaptive tuning.

## Finite mixed-pool applicability check

At most two settings, 8 foreground + 2 warmup attempts/s, then 12 + 2 attempts/s,
8 seconds each, same 0.5-s fixed one-query probes (upper 2/s plus any still-issued
probe). Independent 4/1 foreground/background pools, pinned one-CPU DB.
All issued retries/probes count. Select the largest total nominal attempted rate
with complete payload/offer/operation reconciliation, no timeout, p95 <=100 ms
for BOTH real classes, max dispatch lag <=50 ms. If neither passes, retain both,
stop adaptive configuration, document blocked gate; no automatic larger grid.
Selected total includes fixed probes; reserve 2 attempts/s. This is a short,
conditional operating setting, not capacity or saturation certification.

## Tuning matrix and selection

Two settings per policy (12 runs), same pilot dataset/trace seed 505. Immediate
has no tunable controls and is repeated under both common settings for matched
sampling effort. Parameter A: donor/destination 64 ops/s, encoded bytes/s equal
ops/s*(1024+1024), discretionary DB 2 attempts/s, fixed interval 0.5 s/count 4,
admission cap 4. Parameter B: 128 ops/s with matching byte rates, DB 4/s,
fixed interval 1 s/count 8, cap 8. Fixed origin is expansion+0.5 s in both.
Adaptive ceilings match the corresponding fixed rates; initial rates zero,
additive increment is half the ceiling per fresh safe window; k=2, donor unsafe
multiplier 0.5. Same bursts: 2 operations and two encoded objects; DB 1.
Same pressure thresholds, sample ages, margins and retry counts in both.
This bounded two-point grid tunes rate/step combinations, not every independent
parameter or optimality. No favorable ranking is required.

Selection per policy, before fresh comparison: exclude only invalid/infrastructure
runs (retained with reasons); prefer completed over legitimate deadline failure,
then fewer all-offer violations, then shorter full handover time, then A.
If both settings miss the deadline retain A and both failures. No extra search.

## Fresh smoke and boundaries

After selection, six fresh comparison runs with dataset/trace seed 606, identical
relative offers, physical resets, initial contents, pools, metadata and FIFO/hash
ordering. Every warming policy uses the SAME seeded hash ordering function;
demand/recency modes are separate ablations, not policy privileges. Execute one
zero-budget finite-pass case and one short-deadline gradual case. Deterministic
checks cover changing pressure, unknown/stale evidence, retries/cancellation,
expiry, generation replacement and estimator arithmetic independently.

Every comparison horizon is 10 seconds, expansion at 2 seconds, task lifetime
4 seconds, deadline expansion+6 seconds, two actual-traffic stability windows of
0.5 seconds with >=2 affected submissions each. Background stops by deadline;
foreground, observations and offered traffic run to the fixed horizon. All
copying time is included. Explicit not_warmed keys do not block finite pass
termination. Legitimate failures remain outcomes.

Maximum 22 service runs: 2 mixed checks +12 tuning+6 fresh+2 boundaries.
About 15–25 seconds preparation/reset plus 10 seconds measurement per run,
roughly 10–15 minutes plus tests. Each child has a 90-second watchdog; total
matrix bounds 33 minutes. Never overwrite an ID. Failed infrastructure may
have at most one linked rerun after a diagnosed correction, outside this base
22-run bound, explicitly registered before rerunning. Services stop in finally.

## Evidence and exclusions

Persist exact commands/source/config, all offers, issued operations including
retries/probes, payload hashes, full initial state, distinct Redis process IDs,
pressure raw classes, actions with observation/coverage/allowance/pending values,
per-key terminal dispositions, stability windows, pool/resource counters and
artifact checksums. Raw validation recomputes invariants; summaries alone are
insufficient. Fixed soft-pressure controls may overload; no hidden deletes or
Phase 3 forced-miss diagnostics. Initial old population follows one common
fixed seeded availability rule, never policy-specific missing keys. Baseline
smokes prove behavior only, with no superiority or confidence claim.

## Amendment 1 — complete replacement after grant-renewal defect

Registered after the initial matrix, before any replacement runs. The initial
matrix's warming smokes each left one key unissued after an old-grant timeout
while a replacement was live. Two deterministic negatives reproduce the source
and destination renewal defects (ISSUE-0027). Preserve all initial settings,
selections, outcomes and raw accounting, but exclude that entire matrix from
final comparison evidence. Execute exactly the same 12 tuning +6 fresh+2 boundary
runs once under corrected stable runtime, `p5matrix_v2_20261019`, each `retry_of`
its corresponding v1 ID. No new grid points or favorable-ranking criterion.
The no-expiry mixed-pool checks are unaffected (they do not use migration grants)
and are not repeated. New maximum total measurement runs is 42; estimated extra
10–15 minutes, bounded extra 30 minutes at 90 s per child. Any further essential
correctness defect requires a new explicit recorded finite amendment, never
unbounded reruns. Final source and final full live checks are captured before
launch; no runtime modification during the replacement matrix.
