# ISSUE-0021: Early Phase 4 pilots used a pre-preparation schedule origin; first immediate pilot had a Zipf builder defect

Opened: 2026-10-19T02:43:00Z
Last updated: 2026-10-19T02:50:00Z
Phase: 4 calibration
Status: verified
Severity: high
Affected component: calibration load generator
Affected source/config: Phase 4 harness before the corrected source fingerprint
Affected runs/artifacts: `p4cal_pilot_r12_a`, `p4cal_pilot_r12_b`, `p4exp_pilot_control_r192_a`

## Expected behavior

The persisted open-loop origin begins after all preparation/provenance work; each scheduled offer is eligible when dispatched. The deterministic Zipf key selector builds its cumulative distribution without type errors.

## Observed behavior

The first two 12-rps pilots started the schedule before source capture, making some early requests stale. The first immediate pilot then failed before dispatch because the cumulative list was incremented as a scalar.

## Resolution and verification

`phase4.py` now begins the calibration origin after provenance capture and the expansion origin after warm-prefix validation; `_zipf_keys` uses a scalar `running` value and a list of CDF edges. The invalid directories remain in `runs/`; `p4cal_pilot_r12_c`, `p4exp_pilot_control_r192_b`, and later runs are corrected evidence. No confirmation run began before the frozen protocol.

## Experimental impact

The first two calibration pilots and failed immediate directory are excluded from analysis. They are retained as linked exploratory failures; no claim uses them.
