# Local cache scale-out research

Phases 0 through 3 establish the local service environment, verified literature foundation, corrected architecture/contracts, and a verified minimal scale-out system. Phase 3 implements deterministic data and ownership, actual bounded Redis/PostgreSQL adapters, cache-aside reads with per-key shared fills, bounded selective migration, causal observations, append-only telemetry, and a deterministic repeated small run. Comparative policies, capacity calibration, performance experiments, and measured-gain claims remain later-phase work. Read [current status](reports/STATUS.md), [Phase 3 handoff](reports/phase_03.md), [Phase 2 execution contract](docs/PHASE2_EXECUTION_CONTRACT.md), [architecture](docs/ARCHITECTURE.md), [schemas](docs/DATA_SCHEMAS.md), [invariants](docs/INVARIANTS.md), and [issue index](reports/ISSUE_INDEX.md) before resuming.

Supported bootstrap: native Windows PowerShell 5.1, existing CPython 3.12.10 amd64 and Docker Desktop with a running Linux engine. Use the Windows workspace path below; this path and .venv are not WSL processes. Compatibility rationale and official sources are in [docs/ENVIRONMENT_COMPATIBILITY.md](docs/ENVIRONMENT_COMPATIBILITY.md).

```powershell
Set-Location -LiteralPath 'C:\Users\ramst\Documents\antigravity\paper2'
& .\scripts\bootstrap.ps1
& .\scripts\start.ps1
& .\scripts\doctor.ps1 -Output reports/environment-review.json
& .\scripts\health.ps1 -RunId phase0-health-review
& .\.venv\Scripts\python.exe scripts/validate_phase0.py --run runs/phase0-health-review --output reports/verification-review.json
& .\scripts\shutdown.ps1
```

The commands use the retained [requirements.lock](requirements.lock) and [infra/images.env](infra/images.env). If Python is installed elsewhere, pass `-Python 'C:\path\to\python.exe'` to bootstrap. No activation or execution-policy change is needed. If local PowerShell policy prohibits scripts, report that prerequisite rather than changing it silently. Bootstrap installs only into .venv; it does not install Python, Docker or system packages. Network access is needed for missing locked wheels/images. Docker Desktop can be started using its installed CLI `docker desktop start`; engine installation, license acceptance and virtualization settings are outside this bootstrap.

The existing image lock must be retained. Only on an initial workspace without that lock, run `& .\scripts\lock_images.ps1` once to resolve official Redis 7.4/PostgreSQL 17 tags, record the decision and retain the resulting digest file. The reviewed environment already includes the lock. Compose binds only loopback ports 16379/16380/16381 and 15432, creates services under project paper2-research, sets per-cache Redis maxmemory=32 MiB with allkeys-lru, container quotas of 0.5 CPU/128 MiB per cache and 1 CPU/512 MiB for PostgreSQL. These are startup settings, not calibrated capacities.

Startup uses a public disposable local DB credential if PAPER2_DB_PASSWORD is unset. For an alternative credential set that variable before start/health/shutdown and keep it out of logs. The scripts do not collect secrets or full environment/container configuration. Health writes unique expiring Redis keys and a PostgreSQL temporary table, verifies exact values, deletes them and verifies cleanup. It does not flush caches or mutate a pre-existing application dataset. Shutdown removes only this Compose project's disposable containers and volumes; Docker Desktop remains available for other work.

Each health run creates `runs/<run-id>/` with effective config, source fingerprint, UTC/monotonic timing, events, check results, exit code and checksums. Existing IDs are refused. Choose a new run ID on every execution; use `-RetryOf original-id` to link a rerun to a retained failure. Doctor and validation output paths also refuse overwriting existing evidence. If a check fails, preserve its directory and open/update an issue before rerunning. The environment config is [configs/environment.json](configs/environment.json); [infra/compose.yaml](infra/compose.yaml) defines actual service quotas.

For direct CLI use after bootstrap:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& .\.venv\Scripts\python.exe -m cache_scaleout doctor --config configs/environment.json --output reports/environment-cli-review.json
# Set PAPER2_DB_PASSWORD to the same credential used by start.ps1 before direct health.
& .\.venv\Scripts\python.exe -m cache_scaleout health --config configs/environment.json --run-id phase0-health-cli-review
```

Doctor and health remain available. Phase 3 adds `phase3-run` and `phase3-validate` for functional verification. They are deliberately separate from the future calibrated experiment `run/matrix/analyze` interface. `scripts/validate_phase0.py` still validates only retained environment health evidence.

For an auditable command record, use `& .\.venv\Scripts\python.exe scripts/record_phase0.py --step health --run-id phase0-health-audit --record reports/evidence/phase0/health-audit.json`. This runs the same PowerShell entry point and records the exact invocation, UTC times, duration, stdout, stderr and exit code. Named steps also cover bootstrap/start/doctor/validate/fingerprint/shutdown; use a new record path each time. Validate requires `--output` and the health run ID.

Reviewer evidence: [reports/phase_00.md](reports/phase_00.md), [reports/environment.json](reports/environment.json), [reports/source_state.json](reports/source_state.json), and `reports/evidence/phase0/`. The parent Git repository has no HEAD, so SHA256 source/config fingerprints identify the reviewed state. Scope and provisional latency definitions are in [docs/SCOPE.md](docs/SCOPE.md). Evaluation is incomplete; there are no measured scale-out improvements or uncertainty estimates yet. Failed checks, issue IDs and linked reruns are recorded in the phase report.

Phase 1 supplies the [literature matrix](docs/LITERATURE_MATRIX.md), [verified bibliography](docs/BIBLIOGRAPHY.md), [hypotheses](docs/HYPOTHESES.md), [candidate contribution](docs/CANDIDATE_CONTRIBUTION.md) and [search provenance](docs/LITERATURE_SEARCH.md). ElMem is the nearest fully read direct research comparison; substantial prior overlap supports a characterization study. AdaptCache full text remains inaccessible (ISSUE-0004). No scientific performance experiment has run.

Phase 2 supplies typed contracts in `src/cache_scaleout/contracts.py`, protocols in `interfaces.py`, and the seven-policy catalog plus pure admission arithmetic in `policies.py`. The independent review corrected invalid record acceptance, atomic batch/budget interfaces, bounded immutable observations and coverage provenance, retry-aware new-minus-old DB estimates and pending reserves, destination byte limits, cleanup and reset rules. The [normative execution contract](docs/PHASE2_EXECUTION_CONTRACT.md) specifies exact algorithms and required parameter domains. Six policies are controls; only `joint_control` is the candidate. Numerical settings remain provisional until calibration. These are specifications and pure helpers, not implemented policy loops.

Phase 3 implements the functional mechanisms in `dataset.py`, `adapters.py`, `router.py`, `migration.py`, `observations.py`, `telemetry.py`, and `phase3.py`. The smoke orchestrator uses one fixed donor-first pass and atomic handover solely to verify mechanism behavior; it is not a Phase 5 baseline or the Phase 6 joint controller. The 48-key/16-bucket settings, pressure thresholds, deadlines and grants in [configs/phase3_smoke.yaml](configs/phase3_smoke.yaml) are explicitly provisional.

Run the complete two-run functional cycle from native PowerShell. It recreates the verified disposable cache/database project before each run, compares complete logical initial states and distinct Redis process IDs, validates both runs, and removes the research services in `finally`:

```powershell
Set-Location -LiteralPath 'C:\Users\ramst\Documents\antigravity\paper2'
& .\scripts\phase3_cycle.ps1 `
  -FirstRunId phase3-review-a `
  -SecondRunId phase3-review-b `
  -ValidationOutput reports/evidence/phase3/reset-comparison-review.json
```

Run the fake-client behavioral suite without services:

```powershell
& .\.venv\Scripts\python.exe -B -m unittest tests.test_phase3_behavior tests.test_phase3_independent -v
```

Run actual-client integration against already-started verified disposable services:

```powershell
& .\scripts\start.ps1
$env:PAPER2_INTEGRATION = '1'
& .\.venv\Scripts\python.exe -B -m unittest tests.test_phase3_integration -v
& .\scripts\shutdown.ps1
```

For a standalone retained-run validation, expose the source-layout package explicitly:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& .\.venv\Scripts\python.exe -B -m cache_scaleout phase3-validate `
  --run runs/phase3-publication-a-20261019 `
  --compare-run runs/phase3-publication-b-20261019 `
  --output reports/evidence/phase3/reset-comparison-review-2.json
```

The submitted Phase 3 evidence remains under `reports/evidence/phase3/` and the original smoke run directories. Its gate claim is superseded by the [independent runtime review](reports/reviews/phase_03_independent_20261019.md). Corrective commands, original source, failures and fresh results are under `reports/reviews/evidence/phase3_20261019_independent/`; the final pair is `runs/phase3-publication-{a,b}-20261019/`. Validation derives counts, token/burst/byte/pool bounds, payload hashes, task parents and drain state from individual records, and compares complete logical initial states plus distinct physical Redis processes. Historical booleans or contract-test passes do not certify runtime behavior.

The functional run dispatches persisted absolute offers independently of responses and samples pressure throughout a fixed horizon. Cache foreground and background pools are distinct. Redis values carry an original-expiry header; old formats require fresh disposable resets. Full encoded wire bytes are null where the drivers do not expose them; conservative encoded-byte reservations are enforced separately. `phase3-run` refuses physically nonempty caches and unrecognized database tables. Use the reset-cycle entry point for a fresh run; it label-checks the disposable project before recreation. These are provisional correctness settings, with no calibrated capacity or performance-gain claim.

Phase 4 adds a calibrated actual-client immediate-cutover characterization. The query mix, capacity boundary, confirmation protocol, raw evidence and limitations are in [reports/phase_04.md](reports/phase_04.md), [docs/PHASE4_METHODOLOGY.md](docs/PHASE4_METHODOLOGY.md), and [docs/PHASE4_CONFIRMATION_PROTOCOL.md](docs/PHASE4_CONFIRMATION_PROTOCOL.md). The result is a baseline penalty, not a controller result: empty-destination remapping caused additional DB reads and a repeatable p95 increase against matched cached controls. No Phase 5 baseline suite or Phase 6 controller is implemented.

Reproduce one physically reset Phase 4 run and regenerate the retained confirmation analysis:

```powershell
Set-Location -LiteralPath 'C:\Users\ramst\Documents\antigravity\paper2'
& .\scripts\phase4_run.ps1 -Mode immediate -RunId phase4-review-immediate -Rate 36 -Condition immediate
& .\.venv\Scripts\python.exe -B analysis\phase4_analysis.py `
  --runs p4cal_confirm_r12_1 p4cal_confirm_r12_2 p4cal_confirm_r12_3 p4cal_confirm_r24_1 p4cal_confirm_r24_2 p4cal_confirm_r24_3 p4cal_confirm_r36_1 p4cal_confirm_r36_2 p4cal_confirm_r36_3 p4exp_confirm_control_1 p4exp_confirm_immediate_1 p4exp_confirm_control_2 p4exp_confirm_immediate_2 p4exp_confirm_control_3 p4exp_confirm_immediate_3 `
  --output reports/analysis/phase4_review
```

The analysis refuses an existing output directory. Each run persists the schedule, terminal requests, raw operation ledger, observations, source/config fingerprint and fresh-service initial state. The PowerShell wrapper always shuts down the disposable project after the run.

The focused Phase 2 checks require no services or third-party imports:

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
```

In the implementation agent's restricted sandbox the local launcher could not resolve its per-user base interpreter (ISSUE-0005); the original suite passed 13 tests through the approved existing CPython 3.12.10 boundary. The [independent Phase 2 review](reports/reviews/phase_02_independent_20261018_1821.md) records the expanded 39-test corrected suite, reproduced negative failures, linked reruns and final source identity under `reports/reviews/evidence/phase2_20261018_1821/`. Normal user environments should use the `.venv` command. [Phase 2 report](reports/phase_02.md) retains the original handoff and appends the corrected assessment. No services or performance experiments were run for this review. Phase 3 still requires behavioral and real-client integration verification.

To reproduce the literature retrieval/extraction from the workspace root after the native bootstrap, use fresh evidence IDs. This requires public network access but no running containers. The extraction dependency is separate from the runtime lock:

```powershell
& .\.venv\Scripts\python.exe -m pip download --only-binary=:all: --no-deps --require-hashes -r requirements-literature.lock --dest reports/tools/wheels
& .\.venv\Scripts\python.exe -m pip install --upgrade --no-index --find-links reports/tools/wheels --require-hashes --no-deps --target reports/tools/python -r requirements-literature.lock
& .\.venv\Scripts\python.exe scripts/literature_sources.py fetch --config configs/literature_sources.json --output reports/literature/phase1-fetch-review
& .\.venv\Scripts\python.exe scripts/literature_sources.py verify --config configs/literature_sources.json --output reports/literature/phase1-fetch-review
& .\.venv\Scripts\python.exe scripts/literature_sources.py fetch --config configs/literature_followups.json --output reports/literature/phase1-followups-review
& .\.venv\Scripts\python.exe scripts/literature_sources.py verify --config configs/literature_followups.json --output reports/literature/phase1-followups-review
& .\.venv\Scripts\python.exe scripts/literature_web_checks.py --output reports/literature/phase1-web-review
& .\.venv\Scripts\python.exe scripts/validate_phase1.py --config configs/literature_review.json --source-manifest reports/source_state_phase1.json --output reports/verification-phase1-review.json --handoff
```

The final audit validates the retained canonical Phase 1 evidence and source state, even when new retrievals have been added under reports/. Live PDFs can change; compare their new hashes to the original manifests. The web check exits 1 if any requested source is unavailable; inspect per-source records rather than treating partial success as full recovery. Verification outputs refuse overwrite. For a failed PDF fetch, preserve it and rerun with a new ID and `--retry-of reports/literature/<failed-id>/manifest.json`.

Use `scripts/record_command.py --output <new-record.json> -- <command and arguments>` for exact argv/stdout/stderr/UTC/duration/exit-code capture. It supports `--retry-of <original-record.json>`. Manual source reading and interpretation must still be performed; extraction and the audit do not certify semantic claims. Evidence and reproduction commands are in [reports/phase_01.md](reports/phase_01.md); final source identity is [reports/source_state_phase1.json](reports/source_state_phase1.json). The historical independent review [reports/reviews/phase_01.md](reports/reviews/phase_01.md) assessed the earlier absent submission; it has been preserved for renewed reviewer assessment.
