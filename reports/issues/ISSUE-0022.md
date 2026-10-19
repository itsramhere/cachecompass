# ISSUE-0022: Zero-work SQL compatibility path dropped all rows

Opened: 2026-10-19T03:05:00Z
Last updated: 2026-10-19T03:06:00Z
Phase: 4 calibration
Status: verified
Severity: high
Affected component: PostgreSQL adapter query mix
Affected source/config: Phase 4 calibration implementation before this fix
Affected runs/artifacts: `reports/evidence/phase4/actual_client_integration.json`; Phase 3 default-query actual-client regression only

## Expected behavior

`query_cpu_rounds=0` preserves the existing indexed lookup semantics for Phase 3 and actual-client integration tests.

## Observed behavior

The new lateral `generate_series(1, 0)` returned no rows, so the adapter raised `KeyError` for valid keys. The recorded actual-client suite had 6 errors and one failed pressure-sampling assertion.

## Root cause and resolution

The CPU expression was used as a cross-join relation. An empty series removes the base lookup row. The query now uses `GREATEST(%s, 1)`, retaining one cheap MD5 iteration for the zero-configured compatibility path; Phase 4 continues to use 20,000 iterations.

## Verification

The exact actual-client rerun passed 17 checks after a fresh service recreation: `reports/evidence/phase4/actual_client_integration_rerun.json`. A first standalone buffer-probe invocation also exposed the established Windows Proactor incompatibility because it bypassed the package CLI; the probe now explicitly selects the same Windows Selector policy. Its fresh rerun produced `reports/evidence/phase4/buffer_probe.json`. The failed original records are retained.

## Experimental impact

The completed Phase 4 confirmation runs use 20,000 rounds and did not take this zero-round path. They remain raw evidence, but the final handoff must state the linked compatibility rerun.
