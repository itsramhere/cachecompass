# Project status

Updated: 2026-10-19T03:10:00Z
Active phase: 4 - calibrate capacity and reproduce the expansion penalty
Phase status: complete
Source state: Git `186c3ddb4daf36c2a8dbe7884a82dfb929381ba1`; current canonical aggregate SHA256 `55245c36c0ac5ae716f53c5e7a18f2e48f8ed74dc34955d5d3a85c6b0319761c`; Phase 4 dirty-state/source fingerprints in `reports/evidence/phase4/source_final.json`
Dirty state: modified/untracked Phase 4 implementation, configuration, documentation, analysis and retained run evidence; exact porcelain state is captured in every Phase 4 `runs/*/manifest.json`
Environment: native Windows CPython 3.12.10; pinned disposable Redis 7.4/PostgreSQL 17; one-CPU PostgreSQL and 32 MiB Redis limits; services shut down

## Outcome so far

Phase 4 completed an actual-client capacity characterization and a minimal immediate-cutover baseline. `C_safe=24` actual reads/s is supported only for the documented 20,000-round PostgreSQL query mix and resource configuration. Atomic remapping to a healthy, physically empty cache produced cold new-cache misses, 25 additional foreground DB attempts in every two-second transition window, and a 23--28 ms paired p95 increase. This does not establish a future policy improvement.

## Current evidence

- `reports/analysis/phase4_confirmation_final/calibration_record.json`: machine-readable curve, rate rule, applicability and paired transition deltas.
- `runs/p4cal_confirm_*`: nine independent DB calibration runs; 24 rps is stable under the frozen rule while 36 rps is variable/overloaded in two runs.
- `runs/p4exp_confirm_*`: three matched controls and three immediate cutovers, each with fresh physical services and complete terminal accounting.
- `reports/evidence/phase4/actual_client_integration_rerun.json`: exit 0, 17 actual-client checks after the linked SQL compatibility fix.
- `reports/evidence/phase4/buffer_probe.json`: 606,208-byte relation and 734 heap hits/zero reads after same-mix queries.

## Open issues and impact

ISSUE-0021 and ISSUE-0022 are verified; their failed pilot/check records are retained. ISSUE-0004 remains the accepted literature-access limitation. No Phase 4 gate blocker remains.

## Next actions

1. Stop at the requested Phase 4 boundary. Any future Phase 5 baseline implementation must retain the common foreground semantics and Phase 4 evidence.

## Remaining scope and limitations

Immutable data, one router/host and independent Redis instances only. The database relation is memory-resident and the 36-rps knee is highly variable. The 100 ms threshold is provisional. Full wire-byte accounting, disk-IO behavior, mutable data, multiple routers, Phase 5 controls, Phase 6 adaptation and all performance-improvement claims remain unimplemented.
