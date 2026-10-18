# Relevant-section reading assessment

Recorded: 2026-10-09T17:48:00Z
Assessment type: manual primary-text reading, separate from automated extraction/integrity checks.
Coverage: exact one-based PDF pages and sections in configs/literature_review.json. Mandatory R01–R05 and additional R06–R12 were read beyond abstracts; G01 relevant sections were read from pinned text. R13 identity only verified. Individual papers were not claimed to be read cover-to-cover.

Key distinctions checked against text:

- R02 §III-D4, PDF 5: scale-out copies reassigned available key/value pairs when new capacity fits; hot-subset selection is conditional. Do not treat all ElMem scale-out as partial hot-key prefetch. §III-B, PDF 4 supplies backend-rate-aware sizing; §V-A, PDF 7 uses ardb/RocksDB and multiple fetches per web request. Baseline is inspired, not an identical local reproduction.
- R01 §4.3, PDF 7 and R11 §4.2, PDF 5: warm/old peer reads occur on the foreground miss path. That protection cannot be silently credited to this project's no-peer-fallback primary comparison.
- R03 §4/§6, PDF 5/8/9 and R04 §3, PDF 2–3: convergence comparisons can inspect future intervals; useful offline definitions cannot be deployed as causal online readiness observations. Bonfire's synchronous replay is not original-timed open-loop overload evidence.
- R05 §3/§4/§7, PDF 4–5/7–8/13: workloads include storage, computation and transient caches, diverse skew and TTLs. Restricted immutable cache-aside workloads are a deliberate boundary.
- R06 §4.4/§6.1, PDF 8–9: migration/routing and source CPU allocation already interact; this is authoritative KV migration with hardware switch assistance, not a cache-aside DB backend. Table 1 and §2.2, PDF 4 compare strong prior protocols.
- R07 §III-F/G, PDF 7–8: feedback and rate-limited initiation already described; gradual versus instant migration also uses local fallback. The prose does not supply a verified DB-prefetch/bucket-admission budget. Avoid claiming every instant-migration operation is continuously throttled.
- R08 §4.4/§5–6, PDF 6–7: replication and load-aware server selection differ from deterministic single ownership.
- R09 §5.3, PDF 13: failed DB refills can sustain cold cache misses; transient overload alone is insufficient to claim metastability.
- R10 §6–7, PDF 4–6 and R12 §4–5, PDF 6–8: cost-aware TTL elasticity and feedback memory allocation are adjacent prior control mechanisms, not the proposed physical-node transition.
- G01 §6/10/11/12: origin budget, feedback warming, weighted readiness and traffic ramp substantially overlap the broad mechanism. Provenance predates cutoff; research validation and authorship beyond account identity are unverified.

Gate assessment: nearest fully read direct research approach R02; falsifiable differences H1/H4; same-scope characterization selected because broad mechanism novelty is unsupported. Negative findings are admissible. Full-text-access limitation and late discovery followups remain explicit; no claim of exhaustive literature coverage.
