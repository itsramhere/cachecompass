# Phase 00: Inspect the environment and establish the execution record

Started: 2026-10-09T12:53:31Z (first retained native-shell timestamp; preceding read-only inspection time not captured)
Updated/completed: 2026-10-09T15:40:19Z (final handoff audit)
Status: complete

## Required outcome

Establish a reproducible local execution environment and research record. Gate: the chosen Python runtime works and every required cache/database service passes actual connection/read/write health checks. Container health alone is insufficient.

## Delivered

- docs/SCOPE.md: planned single-router cache-aside architecture, immutable initial scope, latency/completion definitions, provisional target and deferred work.
- docs/ENVIRONMENT_COMPATIBILITY.md: official documentation verification, selected runtime/client/platform boundaries.
- reports/STATUS.md, DECISIONS.md, ISSUE_INDEX.md and issues/: reporting templates applied, failures/debugging/verification retained.
- src/cache_scaleout/: doctor and asynchronous health CLI only. No request router, controller, workload or policy implementation yet.
- configs/environment.json and infra/compose.yaml: isolated loopback-only three-cache/PostgreSQL testbed; explicit pool/timeouts/resource quotas.
- requirements.lock and infra/images.env: seven exact hashed CPython 3.12 Windows wheels and immutable Linux/amd64 image digests.
- scripts/: bootstrap, one startup/shutdown path, image locking, source capture, health, environment capture, artifact validation and exact command recording.
- README.md and repository skeleton: supported PowerShell commands and evidence boundaries. tests/, analysis/ and paper/ are placeholders; no unit-test or manuscript deliverable claimed.
- reports/environment.json: Windows hardware, Python/package versions, Linux engine allocation, container images/digests/limits. No secrets or complete environment captured.
- runs/phase0-health-001/: effective config, source snapshot, manifest, events, four client check results and checksums.

## Validation

Commands were executed from `C:\Users\ramst\Documents\antigravity\paper2` with the existing native Windows runtime. The exact command arrays, timestamps, stdout/stderr and exit codes are in named JSON records. The record wrapper calls the PowerShell entry points shown below.

| Check | Exact command/config/run ID | Outcome | Evidence |
| --- | --- | --- | --- |
| Required input/instruction inspection | Full RESEARCH_IMPLEMENTATION_PLAN.md and AGENT_REPORTING_TEMPLATES.md; workspace/ancestor AGENTS.md search | Both full documents read; no applicable AGENTS.md or existing reports found; original literature review preserved | reports/evidence/phase0/initial-inspection.txt; original-file checksums in reports/source_state.json |
| Runtime/bootstrap | `powershell.exe -NoProfile -File scripts/bootstrap.ps1` | Original exit 1 at quoting boundary; corrected rerun exit 0, CPython 3.12.10 and all imports verified | reports/evidence/phase0/bootstrap.log; bootstrap-error.txt; bootstrap-rerun.json |
| Image resolution | `powershell.exe -File scripts/lock_images.ps1` | Exit 0; official Redis 7.4/PostgreSQL 17 resolved to immutable digests | reports/evidence/phase0/image-lock.log; infra/images.env |
| Service startup | `powershell.exe -NoProfile -File scripts/start.ps1` | Exit 0; three Redis containers and PostgreSQL healthy | reports/evidence/phase0/start-001.json |
| Environment/runtime/quotas | `powershell.exe -NoProfile -File scripts/doctor.ps1 -Output reports/environment.json` | Exit 0; runtime, Linux engine, required containers/digests verified; hardware and quotas recorded | reports/environment.json; reports/evidence/phase0/doctor-001.json |
| Actual async client connection/read/write/cleanup | `powershell.exe -NoProfile -File scripts/health.ps1 -RunId phase0-health-001`; configs/environment.json | Completed, exit 0; Redis 7.4.11 x3, independent run IDs; PostgreSQL 17.11; exact payloads and disposable cleanup verified | runs/phase0-health-001/results.json, events.jsonl, manifest.json; reports/evidence/phase0/health-001.json |
| Artifact/source integrity | `.venv\Scripts\python.exe scripts/validate_phase0.py --run runs/phase0-health-001 --output reports/verification-phase0.json` | Exit 0; nine Phase 0 integrity/health checks passed | reports/verification-phase0.json; reports/evidence/phase0/validate-001.json |
| Existing run ID preservation | Repeat `health.ps1 -RunId phase0-health-001` | Expected exit 1/FileExistsError before service work; original artifacts preserved | reports/evidence/phase0/duplicate-run-guard.json |
| Evidence after refused duplicate | `.venv\Scripts\python.exe scripts/validate_phase0.py --run runs/phase0-health-001 --output reports/verification-after-duplicate.json` | Exit 0; same nine integrity checks passed | reports/verification-after-duplicate.json; reports/evidence/phase0/validate-after-duplicate.json |
| Clean shutdown | `powershell.exe -NoProfile -File scripts/shutdown.ps1` | Exit 0; project containers, project network and disposable volumes removed; no project containers remain | reports/evidence/phase0/shutdown-001.json |
| Final source state | `powershell.exe -NoProfile -File scripts/fingerprint.ps1 -Output reports/source_state.json` | Exit 0; final aggregate equals source recorded by doctor and health | reports/source_state.json; reports/evidence/phase0/fingerprint-001.json |

Source identity (parent Git repository has no HEAD): **SHA256 a657f503705b75d360cf31f8ef0d3aa38f20b31751ad0fa003f00223ca4ee005**. Hash definition and individual file digests are in reports/source_state.json. Mutable reports/runs, virtualenv, wheel downloads, bytecode and secrets are excluded; original plan/templates/background review are included. Final source equals the executed health source.

Final handoff audit at 2026-10-09T15:40:19Z independently checked all 35 listed files using PowerShell Get-FileHash, found zero mismatches, confirmed doctor/health/final source agreement, verified retained health/integrity/shutdown outcomes, and rechecked the unchanged background review. Results: reports/verification-final-handoff.json. No implementation source changed after live integration.

Exact configuration SHA256 values:

- configs/environment.json: `71a5f35aebe10011546923cf652c6cac85092cdd2c64620869a92dd670275aef`.
- infra/compose.yaml: `76b0a829b55a808d1d0dd048864c53d8dddd4f7d5971fc05acaccb69a17fe885`.
- infra/images.env: `951eaeb84aa16cde86016b4f2e5231f5720d37b184b878e5b022abdb0abc39d7`.
- requirements.lock: `24ede01d0da9d29454f12a627ee61a74446df9b744a04742e480c8edd7b374a0`.

Service versions and resources: Redis 7.4.11 with 32 MiB maxmemory/allkeys-lru; 128 MiB and 0.5 CPU quota per container. PostgreSQL 17.11 with 512 MiB/1 CPU quota, 128 MiB shared memory; health DB pool maximum 2. Engine Linux/amd64, Docker server 29.8.0, 12 logical processors and 7,920,103,424 bytes reported engine RAM. Host: Windows 11 Home, Ryzen 7 7445HS (6 cores/12 threads), 15,973,788 KiB visible RAM. Dynamic free memory/disk and actual image IDs/digests are retained in the manifest; these are environment observations rather than calibrated performance limits.

## Errors encountered and debugging

| Issue | Symptom | Root cause/status | Fix or remaining action | Verification |
| --- | --- | --- | --- | --- |
| [ISSUE-0001](issues/ISSUE-0001.md) | Sandbox PATH/installation access/CIM/WSL inspection failed | Permission boundary; verified authorized workflow | Approved inspection and existing native runtime, project-local venv; permission boundary still applies | bootstrap-rerun.json; environment.json; phase0-health-001 |
| [ISSUE-0002](issues/ISSUE-0002.md) | Docker Linux server pipe absent; WSL shim unavailable | Existing Desktop engine stopped; verified | Start installed Docker Desktop, use native CLI; no WSL settings changed | start-001.json; doctor-001.json; phase0-health-001; shutdown-001.json |
| [ISSUE-0003](issues/ISSUE-0003.md) | Bootstrap installed dependencies then Python SyntaxError | PowerShell 5.1 inline argument quoting; verified | File-based Python entry points for bootstrap and fingerprint | Failed bootstrap retained; linked bootstrap-rerun.json; fingerprint-001.json; live health |

An exploratory `Get-Date -AsUTC` failed because that parameter is unavailable in PowerShell 5.1; `[DateTime]::UtcNow.ToString('o')` was used subsequently. It changed no artifact or measurement. All persisted machine-produced timestamps use UTC and durations use monotonic clocks.

No scientific expansion experiment has been run, failed, discarded or replaced. Failed infrastructure/bootstrap evidence remains available and links to its successful corrective checks. The refused duplicate is an expected preservation check; no retry overwrote a run.

## Decisions and deviations

DECISION-0001 uses existing Windows CPython plus Desktop Linux containers instead of changing Ubuntu integration. DECISION-0002 pins wheels/images and fingerprints source without altering the unrelated unborn parent repository. DECISION-0003 adopts explicitly provisional startup quotas and leaves performance workloads/calibration-required values unimplemented. These stay within Phase 0 and do not alter the research question.

Official compatibility references and limitations are in docs/ENVIRONMENT_COMPATIBILITY.md. Selector event-loop policy is explicitly used for Psycopg on Windows. A separate clean machine/Linux Python environment was not validated; reproducibility here covers the retained Windows environment and actual Linux services.

## Gate assessment

**PASS.** CPython works, all three independent caches plus the authoritative database passed connection/read/write and exact payload/cleanup checks. Environment versions/digests/limits and source/config identity are retained. Bootstrap, startup and shutdown were actually executed; artifact integrity is verified. No open correctness/infrastructure error blocks Phase 0.

The gate was verified while services were running; they were cleanly removed afterward. Re-run startup before further service checks. Docker Desktop remains running. No router, migration/controller correctness, request accounting, capacity calibration, expansion penalty or performance improvement is inferred from this gate.

## Next phase handoff

Only Phase 0 was requested and executed. Phase 1 is not_started. On resume read reports/STATUS.md and existing issue records first, then perform Phase 1 primary-source literature reconstruction and testable hypotheses. Local services need not run for that literature task.

Reviewer reproduction from native PowerShell (choose new IDs/output paths if already present):

```powershell
Set-Location -LiteralPath 'C:\Users\ramst\Documents\antigravity\paper2'
& .\scripts\bootstrap.ps1
& .\scripts\start.ps1
& .\scripts\doctor.ps1 -Output reports/environment-review.json
& .\scripts\health.ps1 -RunId phase0-health-review
& .\.venv\Scripts\python.exe scripts/validate_phase0.py --run runs/phase0-health-review --output reports/verification-review.json
& .\scripts\shutdown.ps1
```

Locked configuration: configs/environment.json, infra/compose.yaml, infra/images.env, requirements.lock. The above recreates one **service health run**, not a scale-out experiment. Later prepare/run/matrix/analyze commands and figures are pending their implementation phases. Exact executed audit-wrapper commands can be reconstructed from reports/evidence/phase0/*.json; README documents that wrapper. All unresolved project scope and environmental constraints are stated in reports/STATUS.md.
