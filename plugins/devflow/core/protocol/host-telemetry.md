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
session recovery and execution budget changes are outside this contract.
