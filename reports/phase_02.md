# Phase 02: Specify interfaces, invariants, and experimental policies

Started: 2026-10-18T17:50:00Z
Updated/completed: 2026-10-18T18:10:01Z
Status: complete

## Required outcome

Remove design ambiguity before request-path implementation. Gate: every request and migration action has an explicit source, owner, timeout, and accounting rule; policy definitions are implementable without guessing.

## Delivered

- [Architecture](../docs/ARCHITECTURE.md): component ownership, foreground/migration/observation flows, routing epochs, captured in-flight ownership, `OLD -> COPYING -> ELIGIBLE -> NEW`, bounded causal demand, conservative residency/coverage, resource isolation, reset equivalence, and finite outcomes.
- [Data schemas](../docs/DATA_SCHEMAS.md): versioned event, request, migration task/attempt, observation/action fields and reconciliation rules from scheduled arrival through terminal accounting.
- [Invariant checklist](../docs/INVARIANTS.md): specified correctness, bounds, causality, fairness, accounting, reset, and completion obligations. These are contract-level, not live-system certifications.
- [Policy specifications](../docs/POLICIES.md): all seven required policies. Six are experimental controls; joint control is the candidate policy.
- [Typed contracts](../src/cache_scaleout/contracts.py), [interfaces](../src/cache_scaleout/interfaces.py), and [pure policy contracts](../src/cache_scaleout/policies.py).
- [Focused checks](../tests/test_phase2_contracts.py): 13 contract tests; no services, containers, performance runs, or Phase 3 request path.
- Decisions 0006-0008, ISSUE-0005 failure/resolution, updated README/status/index, and non-overwriting source fingerprints.

Final source identity: parent repository has no project HEAD; **SHA256 b8e0d79837dddba4b11c176f7bd7610bcab772e83c0563b40e327cef6daff09d**, 67 source/config files; [final manifest](source_state_phase2_final.json). Earlier Phase 0/1 and intermediate Phase 2 manifests remain preserved. Reports/runs/venv/wheels/bytecode/secrets are excluded by the established definition.

## Validation

| Check | Exact command/config/run ID | Outcome | Evidence |
| --- | --- | --- | --- |
| Initial suite invocation | `& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v` | Exit 1 before discovery; launcher could not access recorded base interpreter | evidence/phase2/test-001.json; [ISSUE-0005](issues/ISSUE-0005.md) |
| Final Phase 2 contracts | `& 'C:\Users\ramst\AppData\Local\Programs\Python\Python312\python.exe' -B -m unittest discover -s tests -p 'test_*.py' -v` | Exit 0; 13 tests ran and passed in 0.002 s | evidence/phase2/test-003.json |
| Intermediate source capture | `& 'C:\Users\ramst\AppData\Local\Programs\Python\Python312\python.exe' -B scripts/capture_source.py --output reports/source_state_phase2.json` | Exit 0; intermediate fingerprint retained | evidence/phase2/fingerprint-001.json |
| Final source capture | `& 'C:\Users\ramst\AppData\Local\Programs\Python\Python312\python.exe' -B scripts/capture_source.py --output reports/source_state_phase2_final.json` | Exit 0; 67 files, SHA256 b8e0d798... | evidence/phase2/fingerprint-002.json; source_state_phase2_final.json |
| Static handoff audit | PowerShell existence/JSON/catalog/interface/source-manifest audit (exact scope retained in evidence) | Exit 0; 12 files, six JSON records, seven policies, seven protocols, 67 source files | evidence/phase2/handoff-audit-001.json |

Test scope: sequential transitions; causal/stale windows; bounded demand; invalid residency states; key versus warmed-request coverage; in-flight route capture; non-submission and DB-attempt accounting; finite retries; no foreground DB double-counting; required policy names/classification; and all required protocol imports. It did not verify async cancellation, pools, Redis/PostgreSQL clients, reset execution, telemetry persistence, token buckets, or performance.

## Errors encountered and debugging

| Issue | Symptom | Root cause/status | Fix or remaining action | Verification |
| --- | --- | --- | --- | --- |
| [ISSUE-0005](issues/ISSUE-0005.md) | Workspace `.venv` launcher exited before test discovery | Restricted sandbox could reach launcher but not its per-user Python base; verified tooling limitation | Retained failure; used the same existing CPython 3.12.10 through approved native execution; no install/rebuild | Unchanged suite passed 12 tests, then final expanded suite passed 13; test-002/test-003 |

No scientific run failed or was invalidated. Containers remained stopped. The workaround does not imply the sandbox restriction disappeared.

## Decisions and deviations

DECISION-0006 chooses bounded exact demand windows and conservative positive residency evidence. DECISION-0007 separates foreground/background pools and ledgers, charges every issued retry, and prevents double-counting current foreground DB work. DECISION-0008 classifies six controls and one candidate with a common finite completion/deadline rule.

No capacity, threshold, schedule, deadline, pool size, or latency target was calibrated or frozen. Required inputs and algorithms are symbolic until later phases. No novelty/performance claim was added; ISSUE-0004 remains an accepted limitation.

## Gate assessment

**PASS for Phase 2.** A submitted foreground request captures source owner/epoch, uses a finite timeout, and records each issued source/attempt/outcome; an unsubmitted offer explicitly records no route/source and remains accounted. Each migration task names source, source/destination owners, timeout/retry/expiry and work class; each issued retry is charged. Policy inputs are causal/bounded, readiness is conservative, resources are separated/bounded, existing DB demand is charged once, reset and terminal criteria are explicit, and each required policy has deterministic rules and classification.

This establishes implementable specifications and tested pure contracts. It does not establish Phase 3 runtime invariants, actual resource protection, a measured penalty, performance advantage, or novelty.

## Next phase handoff

Stop at the Phase 2 boundary. Phase 3 should implement stable ownership, then bounded request/coalescing behavior, migration/token enforcement, and append-only records. Test simultaneous misses, in-flight cutover, donor/DB timeout, cancellation, TTL expiry, eviction/destination pressure, retry charging, reset equivalence, and real Redis/PostgreSQL integration. Keep performance settings provisional until calibration.

## Independent correction and verified final state — 2026-10-18 UTC

The preceding implementation handoff is historical and retained. Its PASS assessment is superseded by the [independent review](reviews/phase_02_independent_20261018_1821.md). The original 13 tests passed again, but new negative checks exposed 15 assertion failures across 12 tests, and semantic inspection found essential specification gaps. The gate initially required correction.

Fixed ISSUE-0006 through ISSUE-0008 in contracts/interfaces/policy helpers and aligned architecture/schemas/policies/invariants. Added [normative execution rules](../docs/PHASE2_EXECUTION_CONTRACT.md): atomic expected-epoch batch publication, explicit grant installation and destination bytes, bounded immutable causal observations and coverage provenance, retry-aware positive new-minus-old DB increments plus pending reserve, exact control/pass/source rules, shielded creator-deadline coalescing with bounded connection discard, independent offered schedule reconciliation, fresh-instance/full-summary reset, and per-subwindow stability under a common finite deadline/horizon. DECISION-0009 records these choices. No numerical calibration or runtime implementation was substituted for specification work.

| Validation | Exact command arguments after existing CPython 3.12.10 `-B reports/reviews/evidence/phase2_20261018_1821/review_driver.py` | Actual result / evidence |
| --- | --- | --- |
| Reproduced submitted suite | `suite --label baseline` | Exit 0; 13 tests; tests_baseline.json |
| Negative reproduction | `suite --label regressions_before` | Exit 1; 25 tests, failures=15; tests_regressions_before.json retained |
| Final corrected suite | `suite --label complete --retry-of reports/reviews/evidence/phase2_20261018_1821/tests_regressions_before.json` | Exit 0; 39 tests in 0.005 s; tests_complete.json links failure; earlier 38-test passes retained |
| Fresh source | `capture --label complete` | Exit 0; 69 files; source_complete.json |
| Preservation and artifact audit | `preservation --label complete`; `audit --label complete` (separate invocations) | Exit 0 each; preservation_complete.json and audit_complete.json |

Corrected final source: **fc85008dd9b76d6d3e7d3c3d1ef5359264a11604631b6699a7e505e9733bdd41**, [fresh manifest](reviews/evidence/phase2_20261018_1821/source_complete.json). All new evidence is under reports/reviews/evidence/phase2_20261018_1821/. Previous reports/manifests/evidence remain historical; no scientific runs existed to invalidate or replace. The final semantic pass also specifies common bounded pressure sampling while idle/paused, separate observation work classes and a DB allowance charge, avoiding an unspecified bootstrap from UNKNOWN signals. Its interfaces/arithmetic are checked; no sampler runtime was implemented.

Final gate: **PASS for Phase 2 contracts/specifications after correction.** No essential unresolved Phase 2 defect blocks Phase 3 implementation. Local validation and manual cross-contract review do not prove future runtime correctness, live service health, real reset equivalence, budget protection or performance. Phase 3 remains unimplemented; its race/cancellation/TTL/accounting/reset and actual-client gates must be executed later. ISSUE-0004 and the native-boundary limitation persist. Historical Phase 1 tooling/reporting concerns were not recertified by this review.
