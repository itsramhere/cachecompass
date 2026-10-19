# Phase 4 confirmation protocol

Historical submission protocol. Its measurements do not certify the corrected Phase 4 claims. The independent review supersedes this protocol with [PHASE4_REVIEW_PROTOCOL.md](PHASE4_REVIEW_PROTOCOL.md); original results and failures remain retained.

Frozen: 2026-10-19 UTC, before the confirmation repetitions.

The pilot set used the same 512-key, 1 KiB immutable dataset, 64 virtual buckets, 32 MiB allkeys-LRU Redis limits, PostgreSQL limited to one container CPU, and an indexed key lookup with `query_cpu_rounds=20000`. The CPU work is the `generate_series`/`md5` expression in the PostgreSQL query path; there are no artificial request sleeps. It was selected after the earlier 1,200-round pilot showed cold misses but no meaningful backend constraint.

The provisional 100 ms target is retained for Phase 4 because it is the inherited application deadline and gives a clear all-offer violation boundary. Successful-request percentiles are reported separately. This phase does not claim that 100 ms is a universal SLO.

Pilot evidence: at 12 and 24 offered DB reads/s, successful p95 was about 60 ms and 57 ms respectively; at 36 reads/s it rose to about 224 ms with 57 of 144 offered requests over the target. The first confirmation matrix is:

| Purpose | Offered rate | Independent repetitions | Acceptance rule |
| --- | ---: | ---: | --- |
| DB curve below/near knee | 12, 24, 36 rps | 3 each | retain all valid runs; no post-hoc rate selection |
| Router/cache/load-generator capacity | 36 rps, old-cache control | 3 | all offers submitted/completed; compare dispatch and cache-hit latency with DB curve |
| Immediate expansion | 36 rps, control and immediate cutover | 3 matched pairs | same seed/schedule, quotas, observation and physical reset; report every run |

Each run recreates the labelled disposable Compose project before startup and removes it afterward. The old-cache preparation writes the complete dataset; a fixed 128-read prefix must observe zero Redis misses, zero initial evictions, and an empty destination. Immediate runs atomically move all affected buckets at 3 s, never pre-copy or warm them, and use the normal cache-aside foreground path. The control leaves routing unchanged.

The fixed windows are pre-event [0, 3 s), transition [3, 5 s), and post-event [5, 8.5 s) from the persisted schedule origin. Run validity requires terminal records for exactly every offer, scheduled timestamps preserved, and no completion before scheduled arrival. Infrastructure or instrumentation faults remain retained and linked to reruns. Independent runs, not requests, are the replication units. This protocol freezes Phase 4 confirmation only; Phase 5+ comparative policy evaluation remains out of scope.
