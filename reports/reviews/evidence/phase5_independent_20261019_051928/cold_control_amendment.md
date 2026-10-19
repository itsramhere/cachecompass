# Finite behavioral-coverage supplement — before execution

The required pair of migration-before-cutover controls should both have direct
actual-client evidence for terminal cold keys plus final atomic admission.
The base protocol's zero-budget case covers only fixed migration; the six live
functional cases cover both with successful budgeted fallback, not zero-budget
cold outcomes. Add exactly one zero-budget adaptive-budget migration case using
the already frozen executable --boundary zero path. No new code, tuning point,
profile-selection criterion, primary smoke or measurement rule changes.

Execute p5ind_20261019_m1_boundary_adaptive_zero once, after the matrix has stopped
its services, with policy adaptive_budget_migration_before_cutover, A, seed606,
16/s conditional total and the same applicable mixed capacity record. Retain its
raw data whatever the policy outcome; stop for diagnosis if measurement invalid.
Maximum review measurements now 25: 24 eligible (2 mixed,12 tuning,6 smoke,
4 boundary) plus the preserved orchestration-interrupted tune3A. No additional
search or superiority inference. The frozen canonical source remains unchanged.
