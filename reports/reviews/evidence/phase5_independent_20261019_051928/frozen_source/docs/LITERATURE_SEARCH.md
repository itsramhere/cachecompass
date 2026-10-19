# Search and reading provenance

Search date/cutoff: 2026-10-09 UTC. Search the mechanisms and their conjunction, including older citations of direct work. Five mandatory sources and seven additional primary PDFs were retrieved and relevant sections read. The [registry](../configs/literature_review.json) records actual reading coverage; raw [first](../reports/literature/phase1-fetch-001/manifest.json) and [supplemental](../reports/literature/phase1-fetch-002/manifest.json) manifests retain resolved URLs, timestamps, page counts and SHA256 values. Retrieval is not itself a literature gate.

Executed searches covered elastic Memcached/ElMem followups, cache migration throttling, warmup with limited database headroom, migration combined with traffic handover, backend overload, load-aware routing, and 2025/2026 elastic caching. Retained browser responses: [round 05](../reports/evidence/phase1/search-round-05.json), [citation followups](../reports/evidence/phase1/phase1_search_citations.json), [late screening](../reports/evidence/phase1/phase1_search_final.json). Earlier interactive search results are not independently archived; the retained search session below reruns explicit queries across every required category. Search rankings can change; these archives define this review's coverage.

Primary sources used for mechanisms are conference-hosted PDFs and author/coauthor-hosted full papers. Publisher-deposited metadata verifies AdaptCache's citation only. Blogs/search snippets and secondary indexes were used for discovery, not to verify research mechanisms. Bibliographic page ranges are recorded only when the source/citation supports them; the Holpaca preprint is identified as such.

| Screening disposition | Sources / reason |
| --- | --- |
| Direct mandatory | Facebook cold-cluster operations and ElMem elasticity. |
| Mandatory adjacent evidence | Bonfire storage warming; warmup convergence study; Twitter workload characterization. |
| Included newer comparison/context | NetMigrate 2024, ELICA 2025, Linear Elastic Caching 2025, Holpaca 2026; Pegasus load-aware routing and Metastable Failures backend risk. |
| Backward follow-up | Saving Cash by Using Less Cache verifies the original gradual peer-fallback policy directly. |
| Mechanism overlap, separate evidential status | G01 engineering guide, immutable July 2026 commit; unreviewed, with no verified performance results. |
| Unresolved | AdaptCache: publisher HTTP 403 and no accessible author full text found. Full mechanism fields unverified; ISSUE-0004. |
| Excluded from primary comparison | LLM KV/GPU cache migration, mobile edge content handover, CPU caches, web rendering and unrelated cache scheduling: different data, resources or correctness contract. Native Redis/managed-service resharding guidance is architectural context, not the independent-instance controller. |

This is a targeted search, not a systematic exhaustive review, a patent search or a novelty proof. No claim that no identical published controller exists follows from it. Recheck unresolved/direct newer work before manuscript claims. Preserve the original background review; none of its cross-domain citations substitutes for the verified foundation.

Tooling: isolated pypdf 6.1.1 under reports/tools/python; runtime experiment requirements remain unchanged. Retrieval IDs and verification files refuse overwrite. Failed HTTP responses are preserved in phase1-web-001; a metadata lookup is an alternate diagnostic, not a successful full-text rerun. For later PDF retries use a new output directory and --retry-of the failed manifest. No scientific experiment was attempted in this phase.
