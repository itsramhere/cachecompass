# Phase 05: Implement strong baselines

Started: 2026-10-19 UTC
Status: blocked — corrected replacement matrix lacks execution permission

## Required outcome

Six experimental controls execute behind shared interfaces, matching corrected
Phase 2 contracts and H1/H4. Stop before Phase 6; no joint controller, commit,
push or policy-superiority claim.

## Delivered

- `src/cache_scaleout/baselines.py`: pure staged decisions and atomic expected-epoch
  action/grant installation for immediate, fixed gradual, fixed migration-before-
  cutover, warmup-only adaptation, traffic-only adaptation, and adaptive-budget
  migration-before-cutover. Fixed ticks lose missed opportunities, never
  leapfrog, and require eligibility. Adaptive budget/admission logic uses fresh
  windows, pressure hysteresis, retry-aware positive new-minus-old demand,
  uncertainty and pending reserves. Explicit factory rejection of joint_control.
- `policy_observations.py`: causal bounded closed demand and foreground/old-owner
  rates, conservative resident coverage and observation-to-decision expiry bounds,
  probe/real/resource pressure classification. The common sampler continues while
  paused and every issued probe/retry is charged.
- `phase5.py`: actual-client execution through the existing router, separate
  foreground/background pools, original expiry, migration scheduler, cleanup and
  telemetry. No Phase 3 forced misses/deletes. Per-key terminal dispositions,
  action/observation logs, common finite deadline and fixed 10-second horizon.
- Common scheduler extensions supply the same dynamic key ordering and terminal
  callback for every warming policy. No additional passes; finite donor-first
  optional DB fallback, explicit cold outcomes, five empty-start token dimensions,
  encoded-byte grants and generation-safe replacement. Open demand slot is bounded.
- `scripts/phase5_cycle.py`: identity-checked disposable service reset and finally
  shutdown, exact argv/output/source-before/source-after/exit status. `phase5_matrix.py`:
  two-point fair tuning grid, durable selection before fresh seed606 smoke, linked
  retries. `configs/phase5_pilot.yaml` and `docs/PHASE5_PILOT_PROTOCOL.md`: provisional
  parameters, finite counts/runtime/selection rules registered before execution.
- `analysis/phase5_validation.py` and `phase5_audit.py`: raw offered/terminal/payload,
  operation/grant/byte/pool/route/epoch/stability checks and paired-state/schedule
  audit. Negative tests reject resealed fabricated payloads/summaries/epochs and
  premature token issuance. Accounting validation is separate from algorithmic
  verification; original v1 accounting passed despite the renewal defect.

## Provenance and preserved state

The requested Windows directory is not mounted in this cloud session. Work is
in `/workspace/cachecompass`, the configured repository. It initially contained
Phase 3 revision `186c3ddb4daf36c2a8dbe7884a82dfb929381ba1`. Read-only remote checks
confirmed user-named Phase 4 commit; fetched and fast-forwarded to
`a659f237c1f2940d83b714814e0bbf458f009c5d` without creating a commit. Both unrelated
untracked cloud run directories remain untouched. Initial checkout fingerprint
`33ec4f14a17cf290153be0db26b01621f358bf7e0a83bbb42bb4beada7e82bdb`;
post-Phase4 fingerprint `6eff273d12011eeef4571bc10bcc2baa7b73e47d417301cca82937a549f8abd6`.
`provenance.json`, `input_inventory.json` and `source_initial.json` are under
`reports/evidence/phase5/`. The historical Git-blob audit verifies 1,657 files
unchanged in retained runs/reviews/evidence/analysis. No old failure was rewritten.

## Validation and exact commands

Every cycle command record contains child argv, stdout/stderr, monotonic elapsed
seconds, UTC times, physical reset commands, final shutdown and source identity.
Canonical inputs exclude changing reports/runs. Commands below run from project
root using the pre-existing `.venv/bin/python` on Linux.

| Check | Exact command or record | Outcome |
| --- | --- | --- |
| Initial Phase 5 focus | `scripts/record_command.py --output reports/evidence/phase5/tests_initial.json -- .venv/bin/python -B -m unittest discover -s tests -p test_phase5_baselines.py -v` | Retained harness expectation failure (key reused across passes); linked corrected 17-check pass |
| Original complete live suite | `scripts/phase5_cycle.py --run-id p5live_tests_v1_20261019 --record reports/evidence/phase5/full_live_tests_v1.json --tests` | 124 checks; one inherited physical-expiry failure, ISSUE-0026 |
| Corrected expiry live suite | `scripts/phase5_cycle.py --run-id p5live_tests_v2_20261019 --record reports/evidence/phase5/full_live_tests_v2.json --retry-of p5live_tests_v1_20261019 --tests` | 125 pass including 17 actual-client cases; same source before/after |
| Mixed-pool applicability | `scripts/phase5_cycle.py --run-id p5mix8_v1_20261019 --record reports/evidence/phase5/mixed8_v1.json -- --mixed-foreground 8 --stage supplemental --seed 505`, then corresponding `p5mix12_v1_20261019` / rate12 | Both raw-valid; all 80/112 actual foreground+warmup offers complete with correct payloads; fixed DB probes separately charged |
| Supplemental selection | `analysis/phase5_validation.py --runs p5mix8_v1_20261019 p5mix12_v1_20261019 --output reports/evidence/phase5/mixed_validation_v1.json` | Exit0. Select total16 attempts/s, including fixed2/s probes; further reserve2/s. No peak-capacity claim |
| Initial matrix | `scripts/phase5_matrix.py --prefix p5matrix_v1_20261019` | 20 raw-accounted runs, superseded algorithmic comparison evidence under ISSUE-0027; all settings and selections retained |
| Renewal negatives/correction | `scripts/record_command.py --output <record> -- .venv/bin/python -B -m unittest discover -s tests -p test_phase5_grant_renewal.py -v` | `grant_boundary_before.json`: 2 errors; `grant_boundary_corrected.json`: both pass |
| Final exact-source complete live suite | `scripts/phase5_cycle.py --run-id p5live_tests_final_20261019 --record reports/evidence/phase5/full_live_tests_final.json --retry-of p5live_tests_v2_20261019 --tests` | Exit0, 134 checks in 9.925 s, including all17 actual-client cases, no skips; services stopped; identical source before/after |
| Replacement matrix | `scripts/phase5_matrix.py --prefix p5matrix_v2_20261019 --retry-prefix p5matrix_v1_20261019` | NOT EXECUTED: automatic review capacity failure, two review timeouts; explicit network request returned no grant (ISSUE-0028) |

Final tested/replacement source: **796910788bedc489fc047e656ebc5b3115926d899bc28df4c1b740644784613e**;
`source_replacement.json` lists every input hash. No runtime mutation is permitted
during the replacement matrix. The earlier coverage-validity refinement took
place before adaptive-admission tuning/fresh smokes; v1 manifests retain actual
identities rather than claiming its registration hash was a freeze. The full v1
matrix is excluded regardless after the later renewal finding.

## Errors, corrections and experimental impact

- ISSUE-0026: real Redis physical expiry exceeded original monotonic deadline
  by 558067 ns on high-resolution Linux clocks. Add Redis millisecond uncertainty
  to the shared PXAT conversion and conservative residency receipt; unchanged
  repeated TTL tests and deterministic high-resolution regression pass.
- ISSUE-0027: token wait against an old interval threw after a replacement was
  already live; source/destination generation capture now renews within the
  original task lifetime. Both deterministic negatives pass after correction.
  Repeat the identical complete matrix, not only favorable or failed cells.
- Minor retained tooling failures: initial zero-budget test reused a pass and
  expected lifetime counters to reset; corrected harness creates a new scheduler.
  System Python lacked project package metadata; use existing project `.venv`.
  Standard sandbox networking failed; reviewed additional-network fetch worked.
  Automatic approval review twice could not run optional Docker-info capture
  because its model was at capacity. Local versions and actual per-run cgroup/
  quota/image snapshots supply the necessary environment evidence. No denied
  action was bypassed; no unexecuted command is claimed as successful.

## Decisions, limits and gate

DECISION-0014/0015/0016 align the sixth comparator, cloud-host applicability,
finite fair tuning and conservative coverage validity. The protocol's registered
Amendment1 permits exactly one full 20-run replacement, maximum42 measurement
runs total including supplements and superseded matrix. No extra tuning points.

Smoke outcomes establish implementation behavior only. The Phase4 measured
penalty remains the additional miss/DB path, not demonstrated saturation. Total16
is a short conditional mixed-pool setting, not an uncharged foreground budget,
statistical capacity bound or guarantee. All comparison data is immutable,
single-router, single-host and no-expiry; TTL correctness is separately tested.
Encoded reservations are not measured physical wire bytes. One fresh run per
control, a two-point grid and deterministic synthetic workload cannot establish
policy superiority or universal completion. Final evaluation freezing remains
Phase7. Linux execution does not re-certify historical Windows measurements.

**Gate NOT MET / blocked.** Corrected actual-client comparison evidence is still required. The automatic approval service failed for model capacity and timed out twice; the supported explicit permission request returned network:null. The corrected replacement matrix never launched. Previous cycles verified shutdown; no disposable services were started by the rejected commands. Exact-source and whitespace checks pass; no commit/push. Next handoff is
`reports/HANDOFF_PHASE5.md`. Stop before Phase6.
