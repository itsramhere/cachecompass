# Phase 03: Implement and verify the minimal system

Started: 2026-10-18T20:23:36Z
Updated/completed: 2026-10-18T20:43:41Z
Status: complete

## Required outcome

Build a correct minimal request/migration system from the corrected Phase 2 execution contract. The gate requires working request and migration paths, meaningful fake-client behavior tests, actual Redis/PostgreSQL integration, a deterministic expansion run, complete offered-request accounting, no unexpected or unbudgeted DB reads, bounded resources, and repeated equivalent runs after physical cache recreation.

## Delivered

- `src/cache_scaleout/dataset.py`: deterministic immutable payload generation, stable SHA-256 bucket/rendezvous ownership, immutable old/final maps, affected-bucket registry, route capture, and atomic expected-epoch batch publication.
- `src/cache_scaleout/adapters.py`: async namespaced Redis and separate bounded foreground/background PostgreSQL pools; atomic Redis GET/PTTL, conservative absolute expiry, bounded pressure sampling, dataset preparation and service identity checks.
- `src/cache_scaleout/router.py`: cache-aside reads, one captured route per request, no old-peer fallback, per `(owner,key)` shared fills, independent waiter deadlines/cancellation, creator-owned attempt accounting, final-waiter cleanup, finite retries and bounded in-flight/coalescing state.
- `src/cache_scaleout/migration.py`: affected-key-only donor-first copying, optional budgeted DB fallback, separate donor/destination/DB grants, conservative destination reservations, bounded queue/workers/payloads, finite per-stage retries, expiry rejection and residency confirmation.
- `src/cache_scaleout/observations.py`: bounded exact subwindow demand and overflow accounting plus bounded destination-specific residency evidence.
- `src/cache_scaleout/telemetry.py`: bounded append-only JSONL sink and independent offered-schedule reconciliation.
- `src/cache_scaleout/phase3.py`, `configs/phase3_smoke.yaml`, and `scripts/phase3_cycle.ps1`: deterministic functional orchestration, strengthened offline artifact validation, physical Compose recreation between equivalent runs, and guaranteed shutdown.
- `tests/test_phase3_behavior.py`: 14 fake-client tests covering deterministic maps/atomic rejection, shared misses, in-flight cutover, cancellation/cleanup, DB timeout, donor retry, expiry, destination pressure/limits, DB budget exhaustion, grant replacement, bounded demand and reconciliation failures.
- `tests/test_phase3_integration.py`: four actual-client cases for Redis TTL/payload semantics, separate bounded DB pools, actual blocked-query timeout/cancellation/connection reuse, pressure sampling and three independent cache identities.

Final reviewable source identity: SHA256 **69b5d9776b9291a335c279265fa7cba882c60a771f276bc0fd777c728486aaa2**, 80 source/config files; `reports/evidence/phase3/source-final-002.json`. Both final small runs embed this exact source identity. Smoke config SHA256: **068cf0c022ac553541794e236d50bc42050b58dee44da43c727c97defeb9fd28**.

## Validation

| Check | Exact command/config/run ID | Outcome | Evidence |
| --- | --- | --- | --- |
| Pre-change historical suite | `.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_*.py -v` | Exit 0; 39 Phase 2 tests passed | `evidence/phase3/baseline-tests-001.json` |
| Initial fake-client behavior | `.venv\Scripts\python.exe -B -m unittest tests.test_phase3_behavior -v` | Exit 1; 12 tests, 11 passed, final-waiter accounting error retained | `evidence/phase3/behavior-tests-001.json`; ISSUE-0009 |
| Linked cancellation fix | Same command, explicit retry link | Exit 0; 12 passed | `evidence/phase3/behavior-tests-002.json` |
| Final expanded behavior suite | Same command after ownership/grant cases | Exit 0; 14 passed in 0.267 s | `evidence/phase3/behavior-tests-003.json` |
| First service start | Documented `scripts/start.ps1` through recorder | Exit 1; Docker Linux engine stopped; no services/run created | `evidence/phase3/start-001.json`; ISSUE-0010 |
| Linked service-start retry | Same startup after existing Docker Desktop start | Exit 0; three Redis and PostgreSQL healthy | `evidence/phase3/start-002.json` |
| Initial actual-client suite | `PAPER2_INTEGRATION=1`; integration unittest | Exit 1; four Proactor-loop setup errors retained | `evidence/phase3/integration-tests-001.json`; ISSUE-0012 |
| Adapter debugging reruns | Same suite, linked | Exit 1 for cursor defect, then exit 1 for Redis pool/TTL defects | `integration-tests-002.json`, `integration-tests-003.json`; ISSUE-0013/0014/0015 |
| Final actual-client suite | Same suite, linked to `integration-tests-003.json` | Exit 0; four actual Redis/PostgreSQL tests passed in 1.450 s | `evidence/phase3/integration-tests-004.json` |
| Final two-run cycle | `scripts/phase3_cycle.ps1 -FirstRunId phase3-smoke-final2-a-20261018 -SecondRunId phase3-smoke-final2-b-20261018 -ValidationOutput reports/evidence/phase3/reset-comparison-final-002.json` | Exit 0; both runs completed from recreated services; final shutdown verified | `evidence/phase3/cycle-003.json`; the two run directories |
| Reset/artifact comparison | Invoked inside final cycle | Valid; 18 checks pass, including all transition events, full logical initial state equality and disjoint Redis run IDs | `evidence/phase3/reset-comparison-final-002.json` |
| Final service-free regression suite | `.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_*.py -v` | Exit 0; 57 discovered, 53 passed and four integration cases explicitly skipped because services were stopped | `evidence/phase3/full-tests-002.json`; actual four passed separately above |
| Final source capture | `.venv\Scripts\python.exe -B scripts/capture_source.py --output reports/evidence/phase3/source-final-002.json` | Exit 0; 80 files, SHA256 above | `evidence/phase3/source-capture-002-command.json` |

Each final small run prepared 48 authoritative 128-byte values across 16 stable buckets. Three buckets and seven keys moved to the destination. Each run offered and terminally recorded 9/9 requests, verified every returned payload, issued one coalesced foreground DB read, six successful donor values plus one donor miss, exactly one installed-grant DB warm-up, and seven destination writes. Attempt records reconcile exactly to charged grants. Observed maxima were two foreground requests, one shared-fill key, two migration workers, 256 buffered payload bytes, foreground DB pool concurrency one of two, background DB concurrency one of one, and cache concurrency at most two of three configured connections.

The final comparison also verifies append-only checksums, config/source fingerprints, offered-schedule checksum, equality of schedule/arrival/terminal ID sets, nine per-bucket transition records across routing epochs 1/2/3, all affected buckets at `NEW`, authoritative payloads, no unbudgeted DB prefetch, no foreground donor fallback, identical complete logical initial cache state, and distinct Redis server run IDs between runs. Services were removed after each final cycle.

## Errors encountered and debugging

| Issue | Symptom | Root cause/status | Fix or remaining action | Verification |
| --- | --- | --- | --- | --- |
| [ISSUE-0009](issues/ISSUE-0009.md) | Cancelled fill leader record contradicted its DB attempt | Cancellation branch ignored leader-owned DB work; verified | Classify issued leader DB work as foreground DB | Linked 12-test rerun and final 14-test suite pass |
| [ISSUE-0010](issues/ISSUE-0010.md) | Docker engine pipe absent | Existing Docker Desktop was stopped; verified recurrence | Start existing Desktop, retain failed start, link retry | Healthy start, integration, two cycles and shutdown |
| [ISSUE-0011](issues/ISSUE-0011.md) | Recorder crashed printing Docker checkmark after child success | Windows CP1252 stream could not encode U+2713; verified | Emit captured output as UTF-8 bytes | Explicit U+2713 command exits 0 |
| [ISSUE-0012](issues/ISSUE-0012.md) | Psycopg rejected all isolated test loops | Direct unittest lacked Selector policy; verified | Install Windows Selector policy before test loops | Final actual-client suite passes |
| [ISSUE-0013](issues/ISSUE-0013.md) | Dataset batch insertion method missing | psycopg async `executemany` is a cursor method; verified | Use async cursor inside transaction | Integration and four small runs prepare 48 rows |
| [ISSUE-0014](issues/ISSUE-0014.md) | Redis sampling exhausted a two-connection pool | One sample fanned out four concurrent commands; verified | Serialize commands under one bounded sample permit | Actual sampling and repeated runs pass |
| [ISSUE-0015](issues/ISSUE-0015.md) | Redis TTL reconstruction extended expiry by 12 ms | Relative TTL/transit conversion was nonconservative; verified | Use `PXAT`, millisecond floor and subtract read round trip | Actual donor and destination expiry assertions pass |
| [ISSUE-0016](issues/ISSUE-0016.md) | Standalone validator could not import package | Direct command omitted documented `PYTHONPATH=src`; verified | Use documented source-layout environment | Linked and strengthened validation replays pass |

No performance/scientific result was invalidated because no Phase 4+ run exists. Every failed command/test record remains alongside its linked correction.

## Decisions and deviations

DECISION-0010 keeps orchestration at the Phase 3 functional boundary: one fixed donor-first finite pass, one forced donor miss for a budgeted DB fallback, two atomic state publications after copying, and one fixed common pressure round. It does not implement the comparative policy catalog or adaptive controller. Physical cache processes are recreated between paired runs because namespaces cannot reset LRU/allocator history.

The smoke dataset, bucket count, pool sizes, retry limits, grants, pressure thresholds and deadlines are provisional functional-test values. They were not capacity calibrated, tuned for advantage or used for a performance comparison.

## Gate assessment

**PASS for Phase 3.** Working foreground and migration paths executed against fake and actual clients. Required race, cancellation, timeout, retry, TTL, pressure, budget and accounting behavior is covered. The actual-client suite verifies Redis/PostgreSQL semantics and cleanup. The final deterministic pair uses the exact final source/config fingerprints, completes expansion, reconciles all offers and issued attempts, stays within configured bounds, verifies authoritative payloads, and proves physical cache recreation plus complete logical initial-state equivalence.

This gate supports functional correctness for the immutable, single-router, single-host architecture. It does not establish calibrated capacity, an expansion penalty, policy superiority, latency improvement, production readiness or novelty.

## Next phase handoff

Stop at the Phase 3 boundary. Phase 4 may begin by calibrating the actual query mix and identifying a conservative `C_safe`, then reproducing or honestly failing to reproduce the immediate-cutover penalty. Reuse the verified adapters, router, ledgers, reset cycle and artifact validator. Do not reuse the provisional smoke thresholds/rates as calibrated values. ISSUE-0004 remains the accepted literature-access limitation; no Phase 3 correctness blocker is open.
