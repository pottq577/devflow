# Hosted telemetry

Telemetry is optional operational evidence under `.devflow/runtime/<domain>/`.
It grants no execution or lifecycle authority. A telemetry failure returns
`telemetry_unavailable` with a machine-readable `reason` and the existing `error`
string, exits zero, and leaves the mandatory step reservation/acknowledgement intact.

`telemetry-start` requires an explicit `--attempt` matching the guard-reserved step.
An omitted attempt reports `telemetry_attempt_missing`; reservation mismatch reports
`hosted_telemetry_step_mismatch`. Other logging or observation errors report
`telemetry_error`. Continue the truthful child execution and mandatory `step-finish`
even when optional telemetry is unavailable. The guard's owner, fingerprint, kind,
attempt and candidate checks remain authoritative.

Records retain schema v2. The append-only operational log and pending records
remain readable without a migration. Token accounting and session recovery
are outside this change.

Protocol version remains 1.8.0: attempt validation and failure reasons add no
STATE/WORK field, lifecycle artifact, transition or approval requirement.
