# ISSUE-0004: AdaptCache full text inaccessible from publisher

Opened: 2026-10-09T17:35:55Z
Last updated: 2026-10-09T17:43:00Z
Phase: 1 / literature reconstruction
Status: accepted_limitation
Severity: low
Affected component: literature tooling and novelty assessment
Affected source/config: configs/literature_review.json, R13; reports/source_state_phase1.json identifies final source
Affected runs/artifacts: reports/literature/phase1-web-001; no scientific runs

## Expected behavior

Read direct prior cache elasticity work from accessible primary full text before verifying its mechanisms. Metadata or a related-work mention cannot substitute.

## Observed behavior

Publisher URL returned HTTP 403 at 2026-10-09T17:35:55Z through urllib; browser publisher access also reported 403. Browser access to a candidate author publication-list URL failed. Author-page search did not find an accessible AdaptCache PDF. Crossref returned publisher-deposited citation metadata with HTTP 200.

## Original evidence

- Command: `.\.venv\Scripts\python.exe scripts/literature_web_checks.py --output reports/literature/phase1-web-001`.
- Exit code: 1; two metadata/provenance checks and pinned guide retrieval succeeded, publisher full text failed.
- Log/response: [manifest](../literature/phase1-web-001/manifest.json), [original HTTP response](../literature/phase1-web-001/adaptcache-publisher.response). Message: `HTTP Error 403: Forbidden`.
- Browser diagnostic: [retained followup](../evidence/phase1/adaptcache-browser-diagnostic.json); browser does not expose a process exit code.
- Environment: reports/environment.json; native CPython 3.12.10, public HTTPS request; no service experiment or credentials involved.

## Minimal reproduction

1. Bootstrap the documented native Python environment.
2. Execute the command above using a new evidence directory, e.g. `phase1-web-review`.
3. Inspect publisher HTTP result separately from Crossref metadata. Availability may change.

Reproduction outcome: independent browser and native urllib access both returned publisher 403 in this session.

## Debugging attempts

| Attempt/time | Hypothesis | Diagnostic action | Observation | Conclusion |
| --- | --- | --- | --- | --- |
| 1 / 17:35:55Z | Direct native HTTPS can retrieve the paper | Publisher URL through urllib | 403; response retained | Direct access unavailable; cause not established. |
| 2 / 17:35:56Z | Identity can be verified even without full text | Crossref DOI lookup | 200; correct title/authors/venue/year/DOI/pages | Citation verified only; not a successful full-text retry. |
| 3 / 17:36Z | Browser or author-hosted path offers full text | Publisher browser access; author-list access/search | 403 diagnostics; no accessible paper located | Availability limitation remains. Stop repeated publisher retries. |

## Root cause

Remote access rejection is observed; whether bot protection, subscription access or another server policy caused it is unknown. Do not label a paywall or local Python defect without evidence.

## Resolution

Retain R13 with verified identity and every mechanism field unverified. Adopt same-scope characterization rather than an exhaustive novelty claim. R02 and newer accessible sources supply the required nearest verified comparison. No access boundary was bypassed and no paid access obtained.

## Verification

| Check | Command/config/run ID | Observed result | Evidence |
| --- | --- | --- | --- |
| Original reproduction | phase1-web-001 publisher | HTTP 403, command exit 1 | manifest.json / response |
| Alternate metadata diagnostic | phase1-web-001 Crossref | HTTP 200; title AdaptCache, Asad/Kemme, Middleware 2016 | adaptcache-metadata.response |
| Reporting integrity | scripts/validate_phase1.py, configs/literature_review.json | Final result retained separately; checks unresolved status and preserved 403 | reports/verification-phase1.json |

## Experimental impact

No experiment/figure invalidated or rerun. Original failed access is preserved. Successful citation lookup is explicitly linked in the same manifest and not represented as recovered full text. All 12 PDF retrievals succeeded; no failed PDF run was replaced.

## Remaining risk or blocker

Exhaustive novelty/nearest-work assessment cannot exclude overlap with AdaptCache. Full-text followup before manuscript novelty claims remains necessary. It does not block the Phase 1 characterization gate or Phase 2 design against verified R02. No materially different research scope is needed.

## Closure

Accepted limitation at 2026-10-09T17:43:00Z. Citation verified, access not repaired. Reopen if lawful primary full text becomes available.
