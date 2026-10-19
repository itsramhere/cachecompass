# ISSUE-0035: Conditional 16/s mixed point rejected by dispatch criterion

Opened: 2026-10-19T05:57:00Z
Phase: 5 independent review
Status: accepted_limitation
Severity: medium
Affected component: host/load-generator operating-point applicability
Affected source: 61bef47bffd635fedfaf8c9388fe832d67c2ea1e75b307861b4330a1b9e46490
Affected case: p5ind_20261019_m2_mixed12_2

All 112 real queries, 20 DB probes and payloads reconcile. Foreground p95
60.16530925 ms and warm-up p95 51.8322345 ms satisfy the registered <=100 ms
criterion. Maximum foreground dispatch is 52.376628 ms, violating <=50 ms.
The slowest offer has 52.38 ms dispatch, 2.33 ms pre-issue wait and 53.10 ms
issued service. DB used about 0.38 CPU core over the interval, with no added
cgroup throttling count. This does not prove physical DB saturation. An earlier
same-rate check passed; short shared-host timing variability remains visible.

The matrix stopped before any corrected-source tuning. Exact records are in
reports/evidence/phase5/p5ind_20261019_m2/ and review replacement_command.json.
Status completed is the raw measurement status, not capacity eligibility. No
assertion is changed, no point is silently retried, and no negative is erased.

The protocol now permits a single lower common12 attempt, splits8+2 and6+4
with2/s probes and the same reserve. Both must pass unchanged criteria; else
gate remains unmet. Lower load is a conservative new choice, not evidence of
the cause of a host scheduling stall. All policy tuning and fresh comparison
must use that same choice and new stable source. No search extension, rate16
safety claim or Phase6 work. This rejected operating point remains an accepted
limitation even if lower cases pass, not a fixed runtime defect.
