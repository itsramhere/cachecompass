# Phase 01: Rebuild the literature base and state testable hypotheses

Started: 2026-10-09T17:29:30Z (earliest retained retrieval timestamp; resumed status/issue reading and search preceded it)
Updated/completed: 2026-10-09T17:51:49Z
Status: complete

## Required outcome

Read relevant primary sections of all five mandatory works, search newer joint mechanisms, deliver matrix/bibliography and falsifiable hypotheses. Gate: identify nearest prior approach and a testable difference; transparently continue characterization when joint control overlaps prior work.

## Delivered

- [Matrix](../docs/LITERATURE_MATRIX.md): bibliographic identity, direct/adjacent classification, architecture/data/transfer/traffic/resource/workload/findings/limits with section and one-based PDF-page references.
- [Bibliography](../docs/BIBLIOGRAPHY.md), [BibTeX](../paper/references.bib): 12 full-text identities and one metadata-only citation, verified primary links; G01 engineering guidance separately labeled.
- [Hypotheses](../docs/HYPOTHESES.md): four predictions and refutations, including finite completion, strong baselines and adequate migration-before-cutover cases. No uncalibrated rate is presented as measured.
- [Candidate contribution](../docs/CANDIDATE_CONTRIBUTION.md): R02 nearest verified direct approach; same-scope characterization without first-joint-controller claim.
- [Search record](../docs/LITERATURE_SEARCH.md), [reading registry](../configs/literature_review.json), [manual notes](evidence/phase1/reading_notes.md), [unverified late discoveries](evidence/phase1/search-followups.md).
- Non-overwriting retrieval/extraction, separate locked PDF tool, provenance validator and exact-command recorder. PDF/text/failed responses retained under reports/literature/.
- Updated status, decisions and issue ledger. Original review, plans, runtime lock and Phase 0 evidence preserved. Historical independent reviewer report unchanged; R1 delivery gap addressed by this submission, pending renewed independent review.

Source identity: no parent Git HEAD; **SHA256 2a59c57b79a69b033bce8e1862d01a738a4ab8e828846fd3130cd7c685bd18e1**, 49 source/config files; [source manifest](source_state_phase1.json). Canonical JSON file-list hashing excludes reports/runs/venv/tools; raw literature/evidence hashes are retained separately. Historical Phase 0 checksum remains a657f503705b75d360cf31f8ef0d3aa38f20b31751ad0fa003f00223ca4ee005.

| Configuration | SHA256 | Purpose |
| --- | --- | --- |
| configs/literature_sources.json | 55d5d5e25321ee014a9f926344a647b0c444e3d394e3d5179492c9b26d0a56c7 | Nine primary PDFs, including mandatory five |
| configs/literature_followups.json | e148067b690db115b049c8e7ba7f0e61a06394698d55a0b085341226ef8623d3 | Three supplemental primary PDFs |
| configs/literature_review.json | dfe1010cfe61a0da02f138e0cf0802100f05ae82e519c377e1261362bc98482e | Identity, manual reading, comparison/gate assessment |
| requirements-literature.lock | 8e6e1c88241be68968b9397962cc77afc59f78bbed882eddf72e729ccc761dc7 | Isolated pypdf 6.1.1 wheel lock |

## Validation

Commands below were executed from the workspace root with native Windows CPython 3.12.10. Exact argv/stdout/stderr/UTC/duration records are linked where recorded; retrieval manifests independently record per-source HTTP/timing/hashes.

| Check | Exact command/config/run ID | Outcome | Evidence |
| --- | --- | --- | --- |
| Primary retrieval | `.\.venv\Scripts\python.exe scripts/literature_sources.py fetch --config configs/literature_sources.json --output reports/literature/phase1-fetch-001` | Exit 0; nine PDFs extracted | reports/literature/phase1-fetch-001/manifest.json and per-source directories |
| Supplemental retrieval | `.\.venv\Scripts\python.exe scripts/literature_sources.py fetch --config configs/literature_followups.json --output reports/literature/phase1-fetch-002` | Exit 0; three PDFs extracted | reports/literature/phase1-fetch-002/manifest.json and per-source directories |
| Locked tool install | `.\.venv\Scripts\python.exe -m pip install --upgrade --no-index --find-links reports/tools/wheels --require-hashes --no-deps --target reports/tools/python -r requirements-literature.lock` | Exit 0; pypdf 6.1.1 | reports/evidence/phase1/tool-install-001.json |
| Primary integrity | `.\.venv\Scripts\python.exe scripts/literature_sources.py verify --config configs/literature_sources.json --output reports/literature/phase1-fetch-001` | Exit 0; 48 checks passed | reports/literature/phase1-fetch-001/verification.json; evidence/phase1/verify-fetch-001.json |
| Supplemental integrity | `.\.venv\Scripts\python.exe scripts/literature_sources.py verify --config configs/literature_followups.json --output reports/literature/phase1-fetch-002` | Exit 0; 18 checks passed | reports/literature/phase1-fetch-002/verification.json; evidence/phase1/verify-fetch-002.json |
| Gate/provenance audit | `.\.venv\Scripts\python.exe scripts/validate_phase1.py --config configs/literature_review.json --source-manifest reports/source_state_phase1.json --output reports/verification-phase1.json` | Exit 0; 133 checks passed | reports/verification-phase1.json; evidence/phase1/validate-001.json |
| Source capture | `.\.venv\Scripts\python.exe scripts/capture_source.py --output reports/source_state_phase1.json` | Exit 0; checksum above matches audit | reports/source_state_phase1.json; evidence/phase1/fingerprint-001.json |
| Historical Phase 0 integrity | `.\.venv\Scripts\python.exe scripts/validate_phase0.py --run runs/phase0-health-001 --output reports/evidence/phase1/phase0-retained-validation.json` | Exit 0; nine checks passed | evidence/phase1/phase0-retained-check-001.json and phase0-retained-validation.json |
| Final handoff audit | `.\.venv\Scripts\python.exe scripts/validate_phase1.py --config configs/literature_review.json --source-manifest reports/source_state_phase1.json --output reports/verification-phase1-handoff.json --handoff` | Exit 0; 135 checks passed | reports/verification-phase1-handoff.json; evidence/phase1/handoff-audit-001.json |
| Access/provenance followup | `.\.venv\Scripts\python.exe scripts/literature_web_checks.py --output reports/literature/phase1-web-001` | Exit 1; publisher 403; Crossref/provenance and pinned guide succeed separately | reports/literature/phase1-web-001/manifest.json and original responses |

Audit scope: hashes, provenance, configuration identity, mandatory reading records, local links, and presence of manually assessed nearest-work/refutation/overlap evidence. It does not independently certify interpretation, exhaustive novelty or performance. No scientific workload/calibration/policy evaluation or new live service check ran.

## Errors encountered and debugging

| Issue | Symptom | Root cause/status | Fix or remaining action | Verification |
| --- | --- | --- | --- | --- |
| [ISSUE-0004](issues/ISSUE-0004.md) | AdaptCache publisher full text HTTP 403; alternate browser/author-list route unavailable | Remote rejection observed; underlying server policy unknown; accepted_limitation | Preserve response; verify citation only through Crossref; leave all mechanism fields unverified | Retained native/browser failure plus alternate metadata; audit checks preservation and limited status |

Some browser opens for primary URLs returned internal errors; native retrieval succeeded for every configured PDF. No successful browser verification is invented. No scientific experiment failed or was invalidated. Metadata success is not a recovered full-text rerun. Future failed PDF retrievals use new IDs with --retry-of the retained original manifest.

## Decisions and deviations

DECISION-0004 chooses transparent reproduction-inspired characterization because general joint mechanisms overlap prior guidance; nearest verified direct comparison remains R02. Original architecture/scope retained. Strong controls include adaptive-budget migration-before-cutover and isolated-action adaptations. Negative/adequate-simple-control outcomes remain reportable. DECISION-0005 isolates hash-locked literature tooling and immutable provenance from runtime dependencies.

Newer work includes 2024 migration, 2025 elasticity/HCI and 2026 shared-cache control. AdaptCache access and two late-discovered abstract-only sources remain explicit limitations/followups; they are not verified mechanism entries. No topic change or calibration decision was needed.

## Gate assessment

**PASS for Phase 1.** Required primary sections read beyond abstracts, newer mechanisms searched/read, matrix/bibliography delivered, H1–H4 supply refutations. Nearest fully read direct work: ElMem. Testable difference: coupling incremental bucket admission with DB warmup under changing foreground DB allowance and donor pressure versus strong migration-before-cutover and isolated controls (H1/H4). G01 overlaps the broad mechanism, so novelty is unsupported and characterization is chosen as the plan permits. No essential prerequisite blocks Phase 2 design.

This is the implementation owner's gate assessment; the independent reviewer has not reviewed this completed revision.

## Next phase handoff

Stop after Phase 1 for this request; Phase 2 is not started. On the next authorized phase request, read reports/STATUS.md, issue index and all issue records. Specify architecture/interfaces, causal observations, expiry/residency readiness, migration/admission accounting and implementable strong baselines. Runtime services remain in their Phase 0 shutdown state; literature verification requires no containers. Read-only architecture and provisional 100 ms target remain; calibrated rates and frozen performance settings belong to later phases.

Reviewer reproduction commands (fresh IDs, native PowerShell, after README bootstrap):

```powershell
Set-Location -LiteralPath 'C:\Users\ramst\Documents\antigravity\paper2'
& .\.venv\Scripts\python.exe -m pip download --only-binary=:all: --no-deps --require-hashes -r requirements-literature.lock --dest reports/tools/wheels
& .\.venv\Scripts\python.exe -m pip install --upgrade --no-index --find-links reports/tools/wheels --require-hashes --no-deps --target reports/tools/python -r requirements-literature.lock
& .\.venv\Scripts\python.exe scripts/literature_sources.py fetch --config configs/literature_sources.json --output reports/literature/phase1-fetch-review
& .\.venv\Scripts\python.exe scripts/literature_sources.py verify --config configs/literature_sources.json --output reports/literature/phase1-fetch-review
& .\.venv\Scripts\python.exe scripts/literature_sources.py fetch --config configs/literature_followups.json --output reports/literature/phase1-followups-review
& .\.venv\Scripts\python.exe scripts/literature_sources.py verify --config configs/literature_followups.json --output reports/literature/phase1-followups-review
& .\.venv\Scripts\python.exe scripts/literature_web_checks.py --output reports/literature/phase1-web-review
& .\.venv\Scripts\python.exe scripts/validate_phase1.py --config configs/literature_review.json --source-manifest reports/source_state_phase1.json --output reports/verification-phase1-review.json --handoff
```

The final audit checks canonical retained literature evidence, even when new retrievals exist under reports/. Live content can change; compare new hashes to original manifests. Commands refuse existing output IDs. Preserve failed retrievals and link retries with --retry-of reports/literature/<failed-id>/manifest.json. Command records use scripts/record_command.py --output <new-record.json> -- <argv>, with optional --retry-of <original-record.json>. Search reproduction uses the four explicit queries retained at reports/evidence/phase1/search-reproduction-001.json; rankings/availability may change. Actual independent source interpretation remains a reviewer task.

Retained evidence seal: reports/phase1-evidence-checksums.json. Exact reproduction of its integrity check (new output required):

```powershell
& .\.venv\Scripts\python.exe reports/evidence/phase1/seal_evidence.py verify --manifest reports/phase1-evidence-checksums.json --output reports/phase1-evidence-review.json
```

The executed seal/verification records are reports/evidence/phase1/seal-001.json, reports/evidence/phase1/seal-verify-001.json and reports/phase1-evidence-verification.json. Source/config identity remains separate from the evidence seal.

