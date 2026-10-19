from pathlib import Path
groups = {
17: ('Shared-fill deadlines, cancellation and terminal accounting diverge at runtime',
     'foreground router / request accounting',
     'One captured owner, creator-bounded shared fills, independent waiter cancellation, terminal issued outcomes, complete creator retries after cancellation, submitted demand including refusals, and valid DB values surviving cache-fill failure.',
     'Later-deadline followers outlive the creator deadline; cancelled cache operations remain nonterminal; refusals disappear from demand; a write backoff failure discards a valid DB value. Creator records are emitted before later retries finish.',
     'The router trusted client deadlines, emitted creator counts before draining, and handled only selected exceptions. Enforce attempt deadlines and final operation outcomes; defer/serialize summaries without changing terminal timestamps; protect closing generations; stop after unconfirmed cleanup; count all submissions; preserve valid DB reads after fill errors. Actual clients notify issuance only after acquiring connections. Failed permit waits issue zero work.',
     '`behavioral_corrected.json`, `actual_issuance_behavior.json`, and `live_races_expanded.json` pass the affected checks. Final exact-source reruns are pending.'),
18: ('Migration faults strand workers and stale reservations mint grant credit',
     'migration scheduler / resource enforcement',
     'Faults and cancellation drain finite workers; no expired/stale reservation can issue or credit a new grant; empty-start rate/burst tokens bound work independently of interval maxima.',
     'Wrong-payload workers strand queue.join; cancellation leaves donor IO active; releasing an old reservation credits a replacement zero grant; destination IO issues after expiry. The submitted runtime has no token enforcer and charges payload length as encoded bytes.',
     'Independent tasks were not joined on failure; reservations lacked generations/expiry checks. Use a structured bounded worker/producer group, finite drain, generation-specific reservations, post-permit issuance and refunds only for unissued work. Add five empty-start token dimensions, payload+1024 encoded ceilings, explicit queue maxima, source/write links and every cancellation/failure attempt. Flush telemetry outside worker/payload slots and wait paused grants only within original deadlines.',
     '`pair1_validation.json` passes actual rate/burst, byte/grant, pool/queue/buffer and drain audits. `grant_epoch_typo_failure.json` preserves a review-introduced wrong field name; `grant_wait_corrected.json` passes its correction. Final source checks are pending.'),
19: ('Shared cache pools, incomplete sampling and coarse clocks violate runtime contracts',
     'Redis/PostgreSQL adapters / observation / expiry',
     'Separate foreground/background permits; bounded pool waits and cleanup; no implicit retries; preserved original expiry; charged fixed PING/INFO/DB rounds while idle or paused.',
     'The submission combines foreground/background cache quotas, issues PING plus three INFO calls while charging two operations, and samples only after handover. expanded_live_checks.json reproduces an 8 ms donor expiry extension despite the earlier TTL fix (seven of eight cases passed).',
     'Add separate pools and permit deadlines, zero Redis retries, finite PostgreSQL cancel/drain/discard, and periodic no-overlap sampling independent of migration grants. Store original monotonic expiry in a 12-byte envelope; cap reconstructed expiry, subtract clock-resolution uncertainty, and refuse unsafe short TTL writes. Eviction and observed misses invalidate destination residency. Bound overflow buckets and align complete demand windows to run origin.',
     '`integration_intermediate.json` preserves a review-introduced Windows Selector socket-close failure; `integration_cleanup_corrected.json` verifies drain before discard. `expanded_live_ttl_corrected.json` and `live_races_expanded.json` pass TTL, actual shared-fill deadline, replacement backend PID, idle sampling and pool separation checks. Final expanded checks remain pending.'),
20: ('Offered schedules and validators certify claims without independent runtime evidence',
     'generator / reset / artifact validation',
     'Persisted arrivals determine deadlines/dispatch independently of responses; every terminal outcome and operation reconciles; raw payloads and resource evidence support verification; fresh caches exclude foreign namespaces; preparation refuses unrecognized tables.',
     'Submitted relative arrivals are replaced by current time during sequential post-request dispatch. Reconciliation accepts wrong keys/times and nonterminal outcomes. Validation trusts booleans and aggregate claims; initial state excludes foreign namespaces; preparation drops any table of the expected name.',
     'Persist absolute origins/times and dispatch without awaiting earlier responses; retain due arrivals and explicit non-submissions on generator cancellation; execute fixed horizon/stability subwindows. Retain returned hashes, destination values, individual operations, parents and task dispositions; audit grants/tokens/bursts/pools/queues/buffers and canonical/checksummed artifacts. Require physical key counts/evictions to match complete initial contents. Label-check disposable containers and marker-check tables before replacement.',
     '`expansion_intermediate.json` retains early dispatch from coarse timer wakeups; `expansion_dispatch_corrected.json` rechecks absolute sleeps. `paired_cycle_intermediate.json` completes a fresh-instance pair with 34 passing checks. Final exact-source checks remain pending.')}
root = Path('reports/reviews/evidence/phase3_20261019_independent')
for number, (title, component, expected, observed, resolution, verification) in groups.items():
    target = Path(f'reports/issues/ISSUE-{number:04d}.md')
    content = f'''# ISSUE-{number:04d}: {title}

Opened: 2026-10-18T21:14:07Z
Last updated: 2026-10-18T21:36:00Z
Phase: 3 independent review
Status: fixed_unverified
Severity: high
Affected component: {component}
Affected source/config: submitted Phase 3 SHA256 69b5d9776b9291a335c279265fa7cba882c60a771f276bc0fd777c728486aaa2
Affected runs/artifacts: submitted Phase 3 gate and smoke claims; historical evidence retained

## Expected behavior

{expected}

## Observed behavior and original evidence

{observed}

Original runtime is archived under [original](../reviews/evidence/phase3_20261019_independent/original/). The corrected [negative harness record](../reviews/evidence/phase3_20261019_independent/negatives_before_corrected_harness.json) ran ten tests, exit 1, ten failures. The first harness record retains two test-author mistakes and is not the corrected reproduction. Existing 53 service-free tests were insufficient proof of these paths.

## Minimal reproduction

Run `.venv/Scripts/python.exe -B -m unittest tests.test_phase3_independent -v` against the archived submitted runtime. For adapters, start pinned disposable services and set `PAPER2_INTEGRATION=1`, then execute `tests.test_phase3_integration`. Exact commands, timestamps, outputs and source fingerprints are in the independent evidence directory. Reproduction outcome: reproduced as described; static omissions are identified separately from executed failures.

## Root cause and resolution

{resolution}

## Debugging and verification

{verification} All named records are under `reports/reviews/evidence/phase3_20261019_independent/`. The issue's final closure will link exact-source reruns. Original failures remain retained.

## Experimental impact and remaining scope

The submitted gate claim is superseded; prior smoke runs remain historical diagnostics and do not certify corrected behavior. No scientific performance result or Phase 4 calibration exists. Single-router immutable reads and single-host process-lifetime expiry remain the supported architecture. SQL/full driver-encoded bytes are null when unknown. Exact allocator/LRU equivalence, calibrated thresholds and performance remain later measurements. See DECISION-0011 and the normative execution-contract clarification; later policies must share the corrected mechanisms.
'''
    with target.open('x', encoding='utf-8') as f:
        f.write(content)
Path('reports/STATUS.md').write_text('''# Project status

Updated: 2026-10-18T21:36:00Z
Active phase: 3 - independent runtime review and correction
Phase status: in_progress
Source state: per-command fingerprints under `reports/reviews/evidence/phase3_20261019_independent/`
Environment: pinned disposable Redis/PostgreSQL services; native Windows CPython 3.12.10

The submitted Phase 3 PASS is superseded during independent review. Ten focused negative checks failed against the submitted runtime. ISSUE-0017 through ISSUE-0020 document corrections to foreground lifecycle/accounting, migration resources/grants, adapters/TTL/sampling, and offered/reset/artifact evidence. Original source and historical evidence are retained. A first real reset pair passed 34 artifact checks, and ten expanded live cases passed; later corrections require final exact-source suite and reset reruns.

Next: finish behavioral/actual-client checks and a fresh exact-source pair, capture source identity, then issue PASS/FAIL. Phase 4 remains unstarted. The user authorized commit/push only after a Phase 3 PASS. No capacity or performance-improvement claim is supported.
''', encoding='utf-8')
