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

New records use schema v3 from `core/schemas/host-telemetry.schema.yaml`. Existing
fields and the append-only JSONL format are preserved. A pending v2 start can finish
without migration, using its original version and fields. Supply no observations
file for that legacy finish; an observations file is rejected without changing it.
Historical logs may contain both versions and must not be interpreted as lifecycle state.

Both telemetry commands accept an optional `--observations-file` with at most
65,536 bytes of UTF-8 JSON. For example:

```json
{
  "context_bytes": {"packet": 33205, "protocol": 4096, "capsule": null},
  "stage_duration_seconds": {"packet_render": 0.35, "spawn": 0.02, "child_wait": 12.5}
}
```

Only report actual observations: UTF-8 bytes of the rendered action packet,
protocol text and capsule supplied to the child, and elapsed durations measured
by the host. A dispatch message's length is not the rendered packet's length.
Context categories can overlap and are not a token estimate. Missing or null
values remain unmeasured; zero means an observed zero. Duplicate keys, booleans, unknown fields,
negative values and nonfinite durations are invalid. Finish merges explicitly
supplied fields into start observations while retaining omitted fields.

`observations.source` is `caller_reported` for these values. The runtime alone
measures start preparation before log writes as
`observations.stage_duration_seconds.telemetry_prepare` using a monotonic clock;
finish retains that start measurement. `duration_seconds` retains its existing meaning: the wall-clock window
between telemetry start and finish, including supervisor overhead. It is not
automatically a child execution duration. `token_usage` remains `unmeasured`.

Protocol version remains 1.8.0: this operational format adds no STATE/WORK field,
lifecycle artifact, transition or approval requirement. Native token accounting,
execution budget changes are outside this contract.

## Hosted session fencing and administrator recovery

Hosted ownership and persisted execution progress share a SQLite coordinator. Acquisition,
standalone domain-lease checks, and session release inspect validated pending progress inside
`BEGIN IMMEDIATE`. A foreign, orphan or expired owner's pending step remains a fence; expiry
only removes execution authority. Malformed progress, including duplicate JSON keys or invalid
pending/counter fields, refuses acquisition and release without changing the database. A live
owner may renew its lease while its child runs. `session-end` validates idle progress and deletes
ownership atomically; there is no gap permitting a new reservation between those operations.

`session-recover <domain> --session-id <original_owner> --step-id <exact_step>` additionally
requires `--outcome completed|failed|cancelled|capability_blocked`, `--confirm-child-terminated`
and nonblank `--termination-evidence`. This is a trusted administrator's
`explicit_admin_attestation`, not runtime-verified native child termination. The Goal Supervisor
must not supply its own assertion or equate TTL expiry with child termination. Unknown or live
child state remains fenced. No arbitrary takeover or abandon command is provided.

Recovery accepts the exact persisted progress owner, including an expired or absent lease, and
rejects another current owner. Within one coordinator transaction it applies ordinary step-finish
progress/retry accounting, persists an operational `hosted_recovery` receipt, clears the pending
step and releases the lease. The receipt retains the original owner, exact pending step, outcome,
termination facts, after-action fingerprint and recovery time. Repeating the same owner, step,
outcome and evidence returns that receipt without applying accounting again; changed facts are
rejected. Any failed write rolls back the receipt, progress and lease together. Corrupt stored
receipts refuse recovery. These private runtime rows add no STATE/WORK fields or lifecycle
artifact. Protocol version remains 1.8.0 with backward-readable existing operational progress.
