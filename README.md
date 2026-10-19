# Backend-Budget-Aware Cache Scale-Out Research

This repository is a reproducible research prototype for expanding a cache tier while controlling the extra load that migration and newly routed traffic place on an authoritative database. It studies a single asynchronous Python router managing Redis caches in front of PostgreSQL. The controller can warm data from an existing cache or the database, then move traffic to a new cache while respecting bounded work budgets and observed backend headroom.

The project has completed Phase 6, including an independent review of the joint controller and its retained corrections. Phase 7, the final comparative evaluation, has not started. The implementation and functional evidence are available; this repository does not yet establish that the proposed controller improves performance over the baselines.

## What is implemented

- An asynchronous cache-aside router with deterministic key-to-bucket ownership, request miss coalescing, bounded connection pools, and Redis/PostgreSQL adapters.
- Bounded migration and cache warm-up with separate donor, destination-write, and discretionary database budgets.
- Six fixed or single-signal control policies and a joint adaptive controller, implemented on shared execution mechanisms.
- Causal observations, destination-residency tracking, append-only run records, and validators that replay raw evidence.
- Windows PowerShell setup and lifecycle scripts for a disposable local Redis/PostgreSQL environment managed by Docker Compose.

The system models immutable data on one router and one host. It is a research harness, not a production cache service or a general Redis cluster manager.

## Current results and limits

The Phase 6 independent review passed after fixes. Its final live suite passed 189 tests, including 24 actual-client cases, and 14 fresh bounded cases passed raw validation. The feasible joint-controller smoke completed; explicit zero-capacity, stale-observation, nonprogress, and deadline cases remain visible as failures. These are implementation and functional checks, not a comparative performance result.

The capacity check is conditional on the tested Windows host, Docker setup, equal-cost query mix, connection pools, probes, and short run horizon. It is not a database saturation measurement, a universal safe rate, or a production guarantee. The experiment uses one client/router, immutable fitting data, and limited repetitions; it makes no superiority, efficacy, or novelty claim. See the [current status](reports/STATUS.md), [independent Phase 6 review](reports/reviews/phase_06_independent_20261019_0901.md), [Phase 6 handoff](reports/HANDOFF_PHASE6.md), and [research scope](docs/SCOPE.md).

## Requirements

The supported bootstrap path is:

- Windows with native Windows PowerShell 5.1
- CPython 3.12 on 64-bit Windows (the reviewed environment used 3.12.10)
- Docker Desktop with its Linux engine available
- Network access when locked Python wheels or container images need to be downloaded

The repository retains a hash-pinned Windows dependency lock and digest-pinned container images. Linux bootstrap and other Python versions are not certified by the current environment review. See [environment compatibility](docs/ENVIRONMENT_COMPATIBILITY.md) for the version choices and rationale.

## Setup and service lifecycle

Run these commands in PowerShell from the repository root. Bootstrap creates `.venv` and installs the locked Python dependencies; it does not install Python or Docker.

```powershell
Set-Location -LiteralPath 'C:\Users\ramst\Documents\antigravity\paper2'
& .\scripts\bootstrap.ps1
& .\scripts\start.ps1
& .\scripts\doctor.ps1 -Output reports/environment-local.json
& .\scripts\health.ps1 -RunId health-local
& .\scripts\shutdown.ps1
```

Use a new run ID and output path for each execution; evidence outputs refuse to overwrite existing files. `start.ps1` and `shutdown.ps1` operate on this project's disposable Compose services. The default local database credential is intended for that disposable setup; set `PAPER2_DB_PASSWORD` before service and direct CLI use if you choose another password, and keep it out of logs.

## Run and validate Phase 6

The bounded driver runs its actual-client suite in `tests` mode. This starts the required disposable services and shuts them down when the cycle finishes:

```powershell
& .\.venv\Scripts\python.exe -B scripts/phase6_checks.py `
  --prefix phase6-tests-local --mode tests
```

To reproduce the mixed-pool checks and bounded policy cases, use a fresh prefix. This takes longer and runs multiple disposable service cycles:

```powershell
& .\.venv\Scripts\python.exe -B scripts/phase6_checks.py `
  --prefix phase6-cases-local --mode cases --total-db-rate 10
```

The case driver records source, configuration, commands, raw runs, and validation under `reports/evidence/phase6/` and `runs/`. To independently replay its case results, pass the generated smoke run IDs to the validator, for example:

```powershell
& .\.venv\Scripts\python.exe -B analysis/phase6_validation.py `
  --runs phase6-cases-local_smoke0 phase6-cases-local_smoke1 `
          phase6-cases-local_smoke2 phase6-cases-local_smoke3 `
          phase6-cases-local_smoke4 phase6-cases-local_smoke5 `
          phase6-cases-local_smoke6 `
  --output reports/analysis/phase6-local.json
```

The independent validation output must use a path that does not already exist. For the exact reviewed run IDs, commands, and limitations, follow the [Phase 6 protocol](docs/PHASE6_PROTOCOL.md) and [handoff](reports/HANDOFF_PHASE6.md). The committed evidence is the authority for the completed review; reproduction creates new evidence and does not replace it.

## Run tests

Run the full suite from PowerShell. Actual Redis/PostgreSQL integration cases require the disposable services and are enabled by the cycle driver; running unittest directly without services may skip those cases.

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
```

For the reviewed no-skip live suite, use `scripts/phase6_checks.py --mode tests` as shown above.

## Repository guide

| Path | Contents |
| --- | --- |
| `src/cache_scaleout/` | Router, policies, joint controller, adapters, migration, observations, telemetry, and phase runners |
| `configs/` | Environment and phase-specific experiment configurations |
| `infra/` | Docker Compose services and immutable image references |
| `scripts/` | Bootstrap, service lifecycle, experiment cycles, checks, and evidence utilities |
| `analysis/` | Raw evidence validators and audit tools |
| `tests/` | Contract, behavioral, integration, and independent review tests |
| `docs/` | Scope, architecture, invariants, data formats, protocols, and literature methods |
| `reports/` | Phase reports, review records, issues, decisions, and retained evidence |
| `runs/` | Per-run raw output and append-only records |

Useful starting points are [architecture](docs/ARCHITECTURE.md), [invariants](docs/INVARIANTS.md), [data schemas](docs/DATA_SCHEMAS.md), [policies](docs/POLICIES.md), and the [literature matrix](docs/LITERATURE_MATRIX.md).

## Configuration and evidence

The disposable service environment is defined in `configs/environment.json` and `infra/compose.yaml`. Phase 6 behavior is configured in `configs/phase6_v1.yaml`; its rules and run boundaries are documented in `docs/PHASE6_PROTOCOL.md`. Experiment outputs use fresh IDs and retain the source/config identity, commands, results, and validation records needed for review. Preserve failed runs and link reruns rather than editing old evidence in place.

## Contributing

Changes to experiment behavior can affect the meaning of existing results. Keep policy changes, configuration changes, and evidence validation aligned with the documented protocols. Record new runs under fresh IDs, retain failures, and update the relevant report or handoff so reviewers can trace the source and outcome. See [candidate contribution](docs/CANDIDATE_CONTRIBUTION.md) and [reporting templates](AGENT_REPORTING_TEMPLATES.md) for research-specific guidance.

## License

No license is currently specified in this repository. Contact the maintainers before reusing or redistributing the code.
