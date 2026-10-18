# Local cache scale-out research

Phases 0 through 2 establish the local service environment, verified literature foundation, and implementation-ready architecture/contracts. The network request path, service clients for scale-out, dataset preparation, workload runner, and experiments remain later-phase work. Read [current status](reports/STATUS.md), [Phase 2 handoff](reports/phase_02.md), [architecture](docs/ARCHITECTURE.md), [policy specifications](docs/POLICIES.md), [schemas](docs/DATA_SCHEMAS.md), [invariants](docs/INVARIANTS.md), and [issue index](reports/ISSUE_INDEX.md) before resuming.

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

Only doctor/health are executable CLI operations now. Phase 2 adds typed Python contracts and pure policy/accounting checks, not a runnable router. The plan's prepare/run/matrix/validate/analyze experiment commands and result regeneration become available in their designated later phases. `scripts/validate_phase0.py` validates the retained service health evidence. It is not the future scientific run validator.

For an auditable command record, use `& .\.venv\Scripts\python.exe scripts/record_phase0.py --step health --run-id phase0-health-audit --record reports/evidence/phase0/health-audit.json`. This runs the same PowerShell entry point and records the exact invocation, UTC times, duration, stdout, stderr and exit code. Named steps also cover bootstrap/start/doctor/validate/fingerprint/shutdown; use a new record path each time. Validate requires `--output` and the health run ID.

Reviewer evidence: [reports/phase_00.md](reports/phase_00.md), [reports/environment.json](reports/environment.json), [reports/source_state.json](reports/source_state.json), and `reports/evidence/phase0/`. The parent Git repository has no HEAD, so SHA256 source/config fingerprints identify the reviewed state. Scope and provisional latency definitions are in [docs/SCOPE.md](docs/SCOPE.md). Evaluation is incomplete; there are no measured scale-out improvements or uncertainty estimates yet. Failed checks, issue IDs and linked reruns are recorded in the phase report.

Phase 1 supplies the [literature matrix](docs/LITERATURE_MATRIX.md), [verified bibliography](docs/BIBLIOGRAPHY.md), [hypotheses](docs/HYPOTHESES.md), [candidate contribution](docs/CANDIDATE_CONTRIBUTION.md) and [search provenance](docs/LITERATURE_SEARCH.md). ElMem is the nearest fully read direct research comparison; substantial prior overlap supports a characterization study. AdaptCache full text remains inaccessible (ISSUE-0004). No scientific performance experiment has run.

Phase 2 supplies typed contracts in `src/cache_scaleout/contracts.py`, protocols in `interfaces.py`, and the explicitly classified seven-policy catalog plus pure DB-admission arithmetic in `policies.py`. It resolves routing capture, causal bounded observations, residency/coverage, resource separation, finite retries, event/request accounting, isolated resets, and handover termination. Six policies are experimental controls; only `joint_control` is the candidate policy. Numeric thresholds, capacities, deadlines, pool sizes, and latency targets remain provisional until calibration.

The focused Phase 2 checks require no services or third-party imports:

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
```

In the implementation agent's restricted sandbox the local launcher could not resolve its per-user base interpreter (ISSUE-0005); the unchanged suite was therefore executed with the existing recorded CPython 3.12.10 through the approved native boundary and all 12 tests passed. Normal user environments should use the documented `.venv` command. Evidence and the exact alternate command are retained in `reports/evidence/phase2/` and [Phase 2 report](reports/phase_02.md). Containers were not started for Phase 2.

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
