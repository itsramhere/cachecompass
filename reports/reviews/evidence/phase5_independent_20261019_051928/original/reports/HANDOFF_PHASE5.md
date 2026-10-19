# Phase 5 handoff

Updated: 2026-10-19 UTC
Gate: BLOCKED — corrected actual-client replacement matrix has not executed. Stop before Phase 6.

The six requested experimental controls are implemented through the same
foreground router and reviewed Redis/PostgreSQL clients, physical pools,
observations, expiry, migration scheduler, limits and cleanup. No joint controller
is implemented. The corrected Phase2 adaptive-budget migration control is
included in addition to the original five baselines. Immutable, one-router,
one-host two-to-three independent Redis expansion only.

Work occurred in the available `/workspace/cachecompass` cloud checkout, not the
unmounted Windows directory. Git was fast-forwarded from 186c3dd to user-named
`a659f237c1f2940d83b714814e0bbf458f009c5d`. No new commit or push; both unrelated
cloud run directories remain. Historical audit: 1,657 retained files unchanged.

Exact final tested/replacement canonical SHA256:
`796910788bedc489fc047e656ebc5b3115926d899bc28df4c1b740644784613e`.
Manifest: `reports/evidence/phase5/source_replacement.json`. All 100 inputs are
archived byte-for-byte under `reports/evidence/phase5/replacement_source/`.
The superseded smoke's 97 inputs are reconstructed only when their bytes match
its original per-file hashes, under `superseded_smoke_source/`; this is explicitly
a hash-verified reconstruction, not an assertion of capture before the defect.

The final full live suite passed **134 tests in 9.925 s**, including **17 actual-
client cases**, no skips, identical source before/after and verified service
shutdown (`full_live_tests_final.json`). The initial full suite exposed a real
Redis physical-expiry violation on this Linux host; ISSUE-0026 adds the shared
millisecond uncertainty guard. Two further deterministic negatives exposed an
old-grant/new-grant timeout race, corrected by generation-aware renewal within
the original key deadline (ISSUE-0027). All original failures remain retained.

Both mixed-pool supplemental checks pass raw validation. Conditional setting:
**16 total issued DB attempts/s**, including **2/s fixed probes** and a further
**2/s reserve**. All actual foreground/warmup payloads match. This is not physical
DB peak capacity or an uncharged 16/s foreground allowance. Actual retries
consume the same grants; no improvement or saturation claim is supported.

## Reproduce and validate on Linux

Use a never-used ID/output path. The existing `.venv` and pinned Docker images
must be available. `phase5_cycle.py` verifies disposable project labels before
recreating services and stops them in `finally`.

```bash
.venv/bin/python scripts/phase5_cycle.py --run-id p5-fresh-copy --record reports/evidence/phase5/fresh-copy-command.json -- --policy migration_before_cutover --setting B --seed 606 --total-db-rate 16
.venv/bin/python analysis/phase5_validation.py --runs p5-fresh-copy --output reports/evidence/phase5/fresh-copy-validation.json
.venv/bin/python scripts/phase5_cycle.py --run-id p5-fresh-tests --record reports/evidence/phase5/fresh-tests-command.json --tests
```

For complete reproduction, first read `docs/PHASE5_PILOT_PROTOCOL.md`. The bounded
protocol selects A/B independently per control on seed505, durably saves the
selection, and uses fresh seed606 for comparison. It also records a zero-budget
finite-pass case and a short-deadline failure. Final evaluation freezing is Phase7.

```bash
.venv/bin/python scripts/phase5_matrix.py --prefix p5-new-matrix
```

The original matrix `p5matrix_v1_20261019` has complete raw accounting and all
six fresh smokes completed, but its comparisons are **superseded** because
ISSUE-0027 prematurely left a key cold in each warming smoke. A raw validator
PASS is not algorithmic certification. The registered Amendment1 repeats all
20 cases once, identical grid/conditions, linked IDs:

```bash
.venv/bin/python scripts/phase5_matrix.py --prefix p5matrix_v2_20261019 --retry-prefix p5matrix_v1_20261019
```

Automatic execution review returned model-capacity failure and then timed out
before this corrected matrix launched; the permitted identical retry also timed out.
The supported explicit network permission request then returned `network:null`, granting no additional permission. `approval_capacity.json` records the exact action and returned reasons. No
blocked command is presented as executed. This is the current Phase5 gate blocker.

## Interpretation and remaining limits

Every policy uses the same causal metadata and FIFO/hash ordering, query mix,
initial state, offered schedule, physical reset, resource ceilings and observation
horizon. Demand/recency ordering are separate ablations. Immediate issues no
migration/warmup work. Copying intervals count in full handover time; finite pass
termination does not imply every key resident. Legitimate deadline/constrained
outcomes remain measurements; the horizon does not end on success/failure.

These are implementation smokes, not policy superiority evidence. The Phase4
penalty is attributable to the additional miss/DB path, not demonstrated DB
saturation. Linux runtime, a short synthetic workload, a two-point provisional
grid and one fresh comparison per control cannot establish general safe rates,
reliability, optimal tuning or production behavior. SQL/full wire bytes remain
unknown; encoded reservations are not measured bandwidth. TTL is tested
separately from the no-expiry comparisons. Literature access ISSUE-0004 remains.

Full report: `reports/phase_05.md`; current status/decisions/issues and exact raw
commands/evidence remain in their usual paths. After the corrected matrix passes
raw audits and shutdown, update the gate and stop before Phase6. Do not commit
or push without a separate request.
