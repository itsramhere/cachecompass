# Project status

Updated: 2026-10-18T20:43:41Z
Active phase: 3 - Implement and verify the minimal system
Phase status: complete
Source state: Git HEAD 2674d5f plus working-tree Phase 3 changes; canonical SHA256 69b5d9776b9291a335c279265fa7cba882c60a771f276bc0fd777c728486aaa2 (80 source/config files), `reports/evidence/phase3/source-final-002.json`
Environment: `reports/environment.json` (historical Phase 0 manifest); pinned disposable services were recreated for each final run and are stopped

## Outcome so far

Phase 3 gate PASS. The repository now has deterministic immutable data and stable old/final ownership, atomic routing snapshots, bounded actual Redis/PostgreSQL adapters, cache-aside foreground reads with per-owner/key shared fills, selective donor copying with budgeted DB fallback, bounded observations/residency, append-only telemetry, independent offered-request reconciliation, and deterministic two-run physical reset verification.

The final pair `phase3-smoke-final2-a-20261018` and `phase3-smoke-final2-b-20261018` each completed expansion from two old caches to the destination using exact source SHA256 69b5d977... and config SHA256 068cf0c0.... All 9 offered requests per run were terminally accounted and returned authoritative payloads. Issued foreground, donor, DB-warmup, observation and destination attempts are separate and reconcile to grants. All nine bucket-transition events reconcile across routing epochs 1/2/3. No foreground donor fallback or unbudgeted DB prefetch occurred.

This remains a functional smoke system. No capacity calibration, immediate-cutover penalty measurement, comparative policy implementation, performance experiment or improvement claim has been performed.

## Current evidence

- Final fake-client behavior: exit 0; 14 tests passed; `reports/evidence/phase3/behavior-tests-003.json`.
- Actual clients: exit 0; four Redis/PostgreSQL tests passed, including TTL, bounded pools, DB timeout/cancellation and connection reuse; `reports/evidence/phase3/integration-tests-004.json`.
- Final repeated cycle: exit 0; both exact-source runs completed and services were removed; `reports/evidence/phase3/cycle-003.json`.
- Strengthened reset/artifact audit: valid; 18 checks pass, including transition telemetry, complete logical initial-state equality and disjoint Redis run IDs; `reports/evidence/phase3/reset-comparison-final-002.json`.
- Final service-free regression: exit 0; 57 discovered, 53 passed and four live tests explicitly skipped; `reports/evidence/phase3/full-tests-002.json`. The four skipped cases passed separately with services.
- Full Phase 3 evidence and failures: `reports/phase_03.md`, `reports/evidence/phase3/`, and `runs/phase3-smoke-final2-{a,b}-20261018/`.

## Open issues and impact

- ISSUE-0004 remains `accepted_limitation`: AdaptCache full text is inaccessible, limiting exhaustive novelty claims. It does not block functional implementation.
- No Phase 3 correctness or infrastructure issue is open. ISSUE-0009 through ISSUE-0016 are verified with linked evidence. Failed runs remain retained and no scientific result was invalidated.

## Next actions

1. Stop here unless Phase 4 is authorized.
2. In Phase 4, calibrate PostgreSQL latency versus the actual query mix and select a conservative `C_safe`; keep smoke settings separate.
3. Reproduce and attribute the immediate-cutover expansion penalty before implementing Phase 5 baselines or making performance claims.

## Remaining scope and limitations

Phases 4-10 are not started. Comparative policy loops and the joint controller remain specifications only. The implementation is immutable-data, single-router, single-host and uses independent Redis instances rather than native cluster resharding. Pressure thresholds, rates, grants, timeouts, object counts, bucket count and latency target remain provisional. The two small runs demonstrate functional correctness and repeatable reset, not capacity, safety under arbitrary bursts, multi-router coordination, mutable-data correctness, performance improvement, novelty or production readiness.
