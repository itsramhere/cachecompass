# Phase 01 independent review — completed submission

**Latest assessment (2026-10-09T18:48:34Z / 10 October local time): F01, F02's original HTTP-failure case, and F03 are verified fixed. F04 (metadata parsing) and F05 (revision/handoff accounting) remain open. See the fix-verification addendum below. The original review and reproductions remain historical evidence.**

Started: 2026-10-09T18:18:38Z
Completed: 2026-10-09T18:31:35Z
Review status: complete
Substantive Phase 1 gate: **PASS for the declared reproduction-inspired characterization study**
Disposition: two medium-severity tooling defects and one low-severity citation defect remain for the implementation agent. Fix the failure-recording paths before relying on them for further retrievals. The findings do not invalidate the twelve successful PDF archives or block Phase 2 architecture work.

Reviewed source/configuration: SHA256 e06fb76ab140eb8e071b3484afd0941b7a961db4161b92cc7a4bce073262c2bd, 49 files, matching [source_state_phase1.json](../source_state_phase1.json).
Fix owner: implementation agent. No debugging ownership was transferred; no implementation fixes were applied.

## Scope and evidence

Both planning documents were read completely in the initial review: [RESEARCH_IMPLEMENTATION_PLAN.md](../../RESEARCH_IMPLEMENTATION_PLAN.md), all 548 lines, and [AGENT_REPORTING_TEMPLATES.md](../../AGENT_REPORTING_TEMPLATES.md), all 248 lines. Their hashes remain unchanged and were checked again by the Phase 1 audit. This renewed review applies their Phase 1 requirements, experimental constraints, and failure-preservation rules. No applicable ancestor/workspace AGENTS.md was found.

The completed matrix, bibliography/BibTeX, hypotheses, contribution statement, search/reading records, phase handoff, status, decisions, ISSUE-0004, and retrieval/audit tools were inspected. The earlier absent-deliverables review is preserved verbatim as [previous_review.md](evidence/phase_01/completed_submission/previous_review.md). Its R1 delivery gap is resolved by the completed submission.

Independent primary-text checks used archived page-indexed texts of all twelve papers, focusing on sections supporting the matrix. The five mandatory sources were also opened through primary URLs; the Twitter PDF browser open failed, while its USENIX landing page and archived full text were available. Selected sections rather than every page/result were independently reviewed. Targeted live searches supplemented the submitted search record; no exhaustive novelty review is claimed.

Diagnostics, hashes, and tracebacks: [checks.json](evidence/phase_01/completed_submission/checks.json). Browser outcomes, including errors: [browser_checks.json](evidence/phase_01/completed_submission/browser_checks.json).

## Confirmed defects

### F01 — Medium: PDF retrieval errors crash the error recorder and prevent linked retries

Affected code: [scripts/literature_sources.py](../../scripts/literature_sources.py), line 58 inside retrieve().

Expected: a failed download produces a per-source failure record, an aggregate manifest, and nonzero exit status while retaining preceding successes. The manifest supplies the parent for the documented --retry-of workflow.

Observed: the handler calls type(error).__name(). The attribute is misspelled and incorrectly invoked; the intended value is type(error).__name__. A mocked HTTP 403 produces:

    HTTPError: HTTP Error 403: Forbidden
    AttributeError: type object 'HTTPError' has no attribute '__name'

The secondary exception escapes the worker and executor.map before the aggregate manifest write. The source directory remains empty; retrieval.json and manifest.json are absent. A normal linked retry is impossible because its required parent manifest does not exist.

Reproduction: [mock_debug.py](evidence/phase_01/completed_submission/mock_debug.py) executes the submitted fetch script unchanged via runpy, supplies a single-source reviewer configuration, and substitutes only urllib.request.urlopen with a deterministic HTTP 403. No live request, service, workload, or PDF download runs. [mock_debug.json](evidence/phase_01/completed_submission/mock_debug.json) preserves both exceptions; mock_pdf_failure_debug/ retains the incomplete output.

Root cause: confirmed secondary exception in the error handler, followed by unhandled thread-pool propagation. This is independent of publisher availability and affects the general exception path.

Proposed implementation fix: record type(error).__name__; preserve HTTP status and a bounded error-response body where available; make ordinary source failures return records so the aggregate manifest is finalized. Verify with a failed source, a successful source in the same batch, and a linked retry using fresh IDs. Preserve the original failure evidence.

Impact: successful archives remain valid. Future failed-fetch provenance/retries are unreliable until repaired. **Confirmed, open; fix not applied.**

### F02 — Medium: pinned-guide download failure bypasses web failure recording

Affected code: [scripts/literature_web_checks.py](../../scripts/literature_web_checks.py), lines 45–57, especially the raw-content request at line 51.

Expected: every attempted retrieval receives an outcome record and the final manifest survives partial failure.

Observed: the pinned raw-content download lies outside the exception handling used for preceding requests. A mocked HTTP 503 at this download raises an uncaught HTTPError. Three earlier response files remain, but manifest.json and the guide failure response are not saved; earlier outcomes lose their completed status/timing/hash manifest.

Reproduction: the guide-failure case in [final_checks.py](evidence/phase_01/completed_submission/final_checks.py) executes the submitted web script unchanged, makes preceding mocked HTTP requests succeed, and fails only the raw guide URL. The guide_failure_reproduction field in checks.json records the traceback and retained files. mock_guide_failure_recorded/ contains the incomplete output. This is an injected failure-path test, not a claim that GitHub failed in the implementation run.

Root cause: confirmed unguarded follow-up request before the sole manifest write.

Proposed fix: guard pinned retrieval as a separate request with its own failure/status/body/hash record, and finalize the manifest after ordinary request or metadata-parsing failures. Verify the isolated failure and a successful pinned download with fresh IDs.

Impact: the submitted phase1-web-001 manifest is intact. Partial-failure robustness is incomplete. **Confirmed, open; fix not applied.**

### F03 — Low: AdaptCache citation omits its verified subtitle

Affected artifacts: [references.bib](../../paper/references.bib), line 111; [BIBLIOGRAPHY.md](../../docs/BIBLIOGRAPHY.md), R13; [literature_review.json](../../configs/literature_review.json), R13 title.

Retained and independently retrieved Crossref metadata contain title AdaptCache plus subtitle Adaptive Data Partitioning and Migration for Distributed Object Caches. The bibliography/registry retain only the short title. Authors/year/DOI and inaccessible-full-text status remain consistent.

Proposed fix: assemble the complete title from title/subtitle in the citation and registry and include subtitle handling in identity verification. Evidence: [live metadata](evidence/phase_01/completed_submission/adaptcache_metadata.response) and live_adaptcache_metadata in checks.json. This is citation incompleteness, not a misidentified mechanism. **Confirmed, open; fix not applied.**

## Literature correctness and Phase 1 gate

| Requirement | Independent assessment |
| --- | --- |
| Five mandatory primary sources | Relevant sections beyond abstracts are retained and central interpretations checked; met |
| Matrix and bibliography | Direct/adjacent sources and verified/unresolved boundaries distinguished; met subject to F03 |
| Newer mechanism search | Retained queries cover joint warming/handover, budget/overload, migration throttling, load-aware routing and newer elasticity; met for a targeted search |
| Nearest approach and testable difference | ElMem is a defensible nearest fully read direct comparison; H1/H4 compare incremental admission and discretionary DB warming against migration-before-cutover/isolated controls; met |
| Falsifiable hypotheses | H1–H4 state manipulations/refutations, admit simple-control adequacy, and require finite progress/matched resources; met |
| Narrow contribution | Characterization chosen; first-controller, universal-guarantee and measured-local-advantage claims explicitly withheld; met |

Primary-text checks support the central distinctions:

- **ElMem**, PDF 4–5/7: DB-rate-aware sizing, copying reassigned resident data before membership publication, hot-subset selection when capacity is insufficient, and multi-fetch/ardb evaluation. A strong copy-before-cutover comparison is warranted; the local baseline remains an inspired implementation. [Primary paper](https://www3.cs.stonybrook.edu/~anshul/icdcs18_elmem.pdf).
- **Facebook**, PDF 4/7, and **Saving Cash**, PDF 5: lease-based refill protection and/or foreground warm-peer reads. The matrix correctly identifies the changed semantics when peer fallback is absent. [Facebook paper](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf), [Saving Cash](https://www.usenix.org/system/files/conference/hotcloud12/hotcloud12-final73.pdf).
- **Bonfire**, PDF 4–5/8–9: recency-guided preload and backend-load accounting are adjacent evidence. Its timing-ignoring synchronous replay and preload-before-foreground setup do not establish online DB admission safety. **When is the Cache Warm?**, PDF 2–5: future-interval convergence comparison cannot become an online readiness oracle. [Bonfire](https://www.usenix.org/system/files/conference/fast13/fast13-final118_0.pdf), [warm-up characterization](https://www.usenix.org/system/files/hotcloud20_paper_zhang-lei.pdf).
- **Twitter**, PDF 4–5/7–8/13: storage/computation/transient uses and changing TTL/skew/size/write patterns support the explicit workload restrictions and sensitivity checks, without certifying a local dataset. [Primary publication](https://www.usenix.org/conference/osdi20/presentation/yang).
- **R06–R12 spot checks**: NetMigrate 8–9 supports migration/query CPU trade-offs; ELICA 7–8 distinguishes gradual/aggressive migration and initiation limits; Pegasus 6 covers weighted routing/replication; metastability 13 requires sustained refill failure; linear elastic caching 4–5 concerns page retention/cost; Holpaca 7–8 concerns memory allocation and defers distributed deployment. The matrix preserves these distinctions. Archived source paths are in the [reading registry](../../configs/literature_review.json).

G01's pinned raw content independently matches the retained SHA256; GitHub metadata dates the declared revision to 2026-07-21T07:02:49Z, before the cutoff. The broad coordination overlap is accurately disclosed. Provenance/content overlap does not establish authorship beyond the account, peer review, efficacy, or exhaustive priority. [Pinned engineering guidance](https://github.com/babushkai/system-design-patterns/blob/a6e583a999cbe9f8b82e688365a58bdd2f4d5687/04-caching/04-cache-stampede.md).

## Fairness, accounting, and conclusions

**Experimental fairness and application-request accounting are specified but not yet verified.** No scale-out policies or scientific measurements exist in this submission. The hypotheses require shared open-loop arrivals/initial state, memory/TTL/coalescing/timeouts/pools, causal observations, equal tuning, retries/background-work accounting, and migration included in handover time.

H1/H4 include migration-before-cutover and adaptive-budget migration-before-cutover plus isolated-control ablations. H2 holds budgets/eligibility/metadata constant while varying ordering, including a strong recency control. Comparisons must not quietly give the joint policy extra demand information. Foreground peer fallback requires a separately matched extension, as acknowledged.

The offered-request definition includes failed/late/rejected/unfinished outcomes and latency from scheduled arrival. Phase 2 must specify mutually exclusive terminal outcomes, dispatch/drop handling, deadlines, and foreground/background DB accounting. Component health records and HTTP retrieval counts are not offered application requests. The 135-check literature audit verifies integrity/presence; it does not demonstrate scientific validity or overload protection.

No local advantage, calibrated safe capacity, expansion penalty, uncertainty estimate, or novelty result is established. The 100 ms target and practical margins remain provisional. The report states these boundaries correctly, and does not borrow papers' gains as local measurements. No experiment/figure is invalidated.

## Reproduction and diagnostic record

| Hypothesis / action | Observation | Conclusion / proposed action |
| --- | --- | --- |
| ISSUE-0004 might no longer reproduce: one native request to the same ACM URL | HTTP 403 at 18:25:30Z; original response retained | Publisher failure reproduced; underlying access policy remains unknown |
| Citation accessible separately: native Crossref lookup | HTTP 200, matching identity and available subtitle | Metadata succeeds; exact paper full text remains unrecovered; supports F03 |
| PDF fetch should record ordinary failure: isolated mocked HTTP 403 | Secondary AttributeError, empty source directory, missing records/manifest | F01 confirmed; implementation fix required |
| Web manifest should survive pinned-content failure: mocked raw HTTP 503 after preceding successes | Uncaught HTTPError, three responses but no manifest | F02 confirmed; implementation fix required |
| Source/evidence may have changed: independent fingerprints and sealed-file hashing | All 49 source/config and 85 sealed evidence files match; aggregates valid | Submitted successful archives remain intact |
| Literature audit might not reproduce: execute handoff audit and seal verifier with reviewer outputs | All 135 audit checks and 85 seal checks pass | Integrity results reproduce; semantics assessed separately |
| Historical Phase 0 evidence may have changed | All nine retained-run validator checks pass | Historical integrity remains valid; live service health not rerun |

Reexecuted commands from the workspace root:

    & .\.venv\Scripts\python.exe -B scripts/validate_phase1.py --config configs/literature_review.json --source-manifest reports/source_state_phase1.json --output reports/reviews/evidence/phase_01/completed_submission/validator_recorded.json --handoff
    & .\.venv\Scripts\python.exe -B reports/evidence/phase1/seal_evidence.py verify --manifest reports/phase1-evidence-checksums.json --output reports/reviews/evidence/phase_01/completed_submission/seal_recorded.json
    & .\.venv\Scripts\python.exe -B scripts/validate_phase0.py --run runs/phase0-health-001 --output reports/reviews/evidence/phase_01/completed_submission/phase0_validator.json

These paths now exist and refuse overwrite. Failure probes also require fresh directories. Original implementation outputs/seals were preserved. The final collector completed with exit 0; injected failures remain nonzero outcomes with tracebacks.

The first reviewer collector expected a failed-PDF record and exposed F01 when it was absent. A subsequent reviewer-only 1 MiB GitHub response cap caused JSON parsing failure; that truncated response was retained and replaced by a small commit-list diagnostic. The latter is a reviewer probe error, not an implementation finding. Both are documented in checks.json; no failure was silently overwritten.

## Suspected defects, limitations, and suggestions

No additional suspected implementation defect is supported. Outstanding coverage questions are not classified as confirmed defects.

- **AdaptCache follow-up:** an independently discovered [Omar Asad thesis, January 2021](https://escholarship.mcgill.ca/downloads/47429g24b?locale=en), is publicly accessible through McGill; its contents include the AdaptCache framework and object partitioning/migration chapters. It is useful primary follow-up, not recovery of the exact 2016 paper. The implementation agent should screen relevant chapters, record their version relationship, and update the access limitation without asserting unsupported equivalence. Publisher 403 remains reproducible.
- **Coverage metrics:** freeze a common request population/window and independent residency observations for H2, so ranking policies cannot change their apparent coverage by changing what is observed. Keep future-trace scoring offline.
- **Methodology:** later phases must freeze practical margins, replication, finite deadlines, statuses/exclusions, paired interference schedules, and uncertainty rules. These are future dependencies, not Phase 1 defects.
- **Fix verification:** the implementation agent should open issue records for F01/F02, apply scoped fixes, retain original reproductions, and verify failed/successful/linked-retry paths. Successful papers need not be refetched solely to repair failure recording.

## Preservation and handoff

Source inspection preceded reversible diagnostics. All writes are confined to reviewer reports/evidence; implementation source, configuration, plans, status/decision/issue ledgers, original literature and experiment artifacts were untouched. Final hashes confirm all 49 source/config files and 85 sealed implementation evidence files remain unchanged.

Process inspection showed Docker/PostgreSQL and no visible Python experiment process; it does not establish exclusive use or identify container workloads. Checks remained lightweight: hashing, literature validation, bounded public HTTP requests and isolated mocked failures. No services were started/stopped, dependencies installed, or capacity/cache-warming/workload/performance experiments run.

The implementation agent retains ownership of fixes and literature follow-up. Phase 2 design may proceed in the declared characterization scope. This review accepts the substantive Phase 1 gate and does not certify later system correctness, accounting, fair execution, or performance conclusions.

## Fix-verification addendum — 10 October 2026 local time

Independent checks captured at 2026-10-09T18:48:34.868567Z. The original findings above describe the earlier revision; this addendum supplies their current disposition. Both planning documents retain their previously reviewed hashes, as independently checked by the current audit. Source inspection preceded fresh, offline diagnostics. No implementation files or issue/status ledgers were edited.

Current inspected source/configuration: **59 files**, SHA256 **971148f793851b47368b2cacf8b0f935f0eef48e7def6d1a9e01d2ab18a15d26**. This is a reviewer observation, not a replacement for the implementation agent's historical source capture. Six existing files changed and ten diagnostic files were added relative to the original 49-file capture; the complete list and hashes are retained in [fix checks](evidence/phase_01/fix_verification_20261009/checks.json).

### Original findings: independently verified fixes

| Finding | Diagnostic action and observation | Current disposition |
| --- | --- | --- |
| F01: PDF error recorder | Run the actual fetch script with one mocked HTTP 403 and one successful, text-bearing synthetic PDF. Exit 1 without a secondary exception; both per-source records and aggregate manifest exist. The failed record retains HTTP 403, `HTTPError`, bounded response body and timing; the successful record retains extraction/hash evidence. Retry both sources successfully into a fresh directory linked to the failed manifest. Retry verification passes all 14 checks; original batch hashes remain unchanged. | **Verified fixed** for the reported ordinary HTTP-error path, mixed batch and linked retry. |
| F02: pinned-guide HTTP failure | Run the actual web script with three successful preceding responses and a mocked raw-download HTTP 503. Exit 1 without an uncaught exception; four requests are accounted for, including failed status, HTTP 503, exact response body, matching hashes, commit provenance and timing. The all-success counterpart exits 0 and records four responses correctly. | **Original defect verified fixed.** Broader metadata-failure finalization remains incomplete; see F04. |
| F03: incomplete AdaptCache citation | Compare registry, Markdown bibliography and BibTeX with the complete title assembled from retained Crossref title/subtitle. All three match. The amended validator explicitly checks the subtitle, and that identity check passes. | **Verified fixed.** Full-text access remains an accepted limitation; this citation fix does not recover the paper. |

These probes use fully mocked HTTP responses, fresh output IDs and a one-page PDF with text. They establish local control-flow and artifact accounting, not publisher availability or system performance. [Reviewer probe source](evidence/phase_01/fix_verification_20261009/review_fixes.py) and [checks/commands/tracebacks](evidence/phase_01/fix_verification_20261009/checks.json) retain the exact inputs and outcomes. Replay into a new evidence directory because outputs intentionally cannot be overwritten. Parent/retry artifacts are under `pdf_mixed/` and `pdf_retry/`; web outcomes are under `web_503/`, `web_success/` and `web_invalid_metadata/` in the same evidence directory.

### F04 — Medium, confirmed and open: malformed commit metadata still prevents the web manifest

Hypothesis: only the pinned network request was guarded, so parsing the preceding HTTP-success response can still bypass final accounting.

Action: return a complete mocked HTTP 200 response containing `not JSON` for the commit endpoint, after two valid preceding responses. This probe does not truncate a valid response and is distinct from the earlier reviewer-only response-cap error.

Observation: `json.loads(data)` at `scripts/literature_web_checks.py:46` raises uncaught `JSONDecodeError`. Three response files are retained, but `manifest.json` is absent. No pinned request was issued. The original F02 proposal explicitly called for finalization after metadata-parsing failures as well as request failures; the HTTP-specific fix leaves this adjacent path unhandled.

Proposed implementation fix: guard JSON parsing and expected commit fields, retain the exact raw response, record a metadata-validation failure separately from HTTP retrieval success, and finalize the aggregate manifest. Do not count an unissued pinned request as issued. Verify malformed JSON, missing required fields and an empty commit result alongside the existing success/503 cases. Only malformed JSON is reproduced here; other schema cases are proposed diagnostic coverage, not additional confirmed failures. Evidence: `web_invalid_metadata` traceback and retained files in [checks.json](evidence/phase_01/fix_verification_20261009/checks.json).

### F05 — Medium, confirmed and open: revised source has no matching implementation handoff

Hypothesis: scoped fixes changed the source, but the implementation capture, validation and reporting were not refreshed with a linked revision.

Action: run `validate_phase1.py --handoff` against the advertised `reports/source_state_phase1.json`, writing a fresh reviewer result; independently compare all current file hashes and rehash the original evidence seal. Inspect the phase/status/issue ledgers and the added implementation diagnostics.

Observation: **134/135 checks pass; `final_source_matches_manifest` fails**, producing exit 1. The advertised source capture still contains 49 files and the old aggregate hash, whereas the current source contains 59. The old 135-check success remains valid historical evidence but does not validate this revised source. The implementation's retained `validator_recorded_test.json` likewise has `passed: false` and the fingerprint mismatch. Status and phase records still describe the older handoff; the issue index contains only ISSUE-0001 through ISSUE-0004, without F01/F02 fix history. Reporting-template instructions require updates after consequential fixes and issue records for correctness defects; the original review also requested these records.

Proposed implementation fix: preserve the old capture/audits/seal, add a fresh source capture for the intended revised handoff, rerun the audit against that capture, and link the revised evidence from the phase/status records and issue index. Decide explicitly whether the root-level `test_config.json`, `test_out/`, `verify_f01.py` and `verify_f02.py` are retained diagnostics or source deliverables; they currently participate in the fingerprint. Preserve their evidence if reorganizing them. Document the F01/F02 resolutions and F04's remaining limitation; do not imply all failure-recording paths are verified.

This mismatch does **not** show corruption of successful literature archives. All **85 original sealed evidence files match**, the seal aggregate is valid, and all previous completed-submission reviewer evidence is unchanged. Evidence: [current audit](evidence/phase_01/fix_verification_20261009/validator.json) and preservation/source sections in [checks.json](evidence/phase_01/fix_verification_20261009/checks.json).

### Diagnostic evidence quality, suggestions and limits

The added `verify_f01.py` monkeypatches `urlopen` in its own process, then launches the fetcher as a subprocess; that patch does not transfer to the child. Its retained failure is an actual HTTP **404**, not the intended mocked **403**. It demonstrates ordinary error recording but does not reproduce the claimed injected case. `verify_f02.py` contains comments and imports without a regression probe. These are confirmed limitations of the supplied verification evidence; the independent in-process probes above provide the missing targeted verification. Suggested improvement: retain executable assertions with the same mocked process boundary as the code under test and preserve exact exit codes/results.

No new suspected defect is asserted. Empty/missing commit metadata checks and future request-population/fairness safeguards remain suggestions until evaluated. No performance experiments or numerical performance conclusions were added; the prior substantive Phase 1 acceptance for characterization stands, subject to the citation/access boundaries already recorded.

During this follow-up, no visible Python/benchmark process was found in the lightweight process check; this is not proof of exclusive machine use. Diagnostics remained offline and small regardless: one synthetic page, mocked requests, hashing and the structural literature audit. No services were started/stopped and no resource-intensive workload ran. The inspected source remained unchanged throughout the reviewer checks. The implementation agent retains ownership of F04/F05 and reporting corrections.
