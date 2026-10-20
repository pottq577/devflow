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

The telemetry format adds no STATE/WORK field, lifecycle artifact, transition or
approval requirement. Native token accounting, including hosted token-budget
enforcement, remains outside this contract.

Starting telemetry prunes settled inflight files under `host-dispatch-inflight/`, keeping only
the file whose `step_id` is the live reserved step. A supervisor that crashed between start and
finish therefore cannot accumulate files without bound, and another session's live record is never
removed because only one owner holds the domain lease.

Hosted-only configuration boundaries: `budget.total_tokens` and its buckets are standalone
Autopilot settings and enforce nothing for hosted `/goal`, whose native child token usage is
unmeasured. `concurrency.read_only` is likewise a standalone setting; hosted children are
dispatched sequentially, so the value does not limit them and read-only roles keep read-only
permissions instead of parallelism.

## Hosted Scout capsule provenance

A capsule is reusable only when its validated text, action fingerprint, and evidence digest match the bounded index and step-start source snapshot. The snapshot covers the selected WORK, verification and failure references, WORK source paths, cited files, applicable repository instructions, routing configuration, and role protocols. Resolve paths under the repository or plugin root. Missing required files, traversal, symlink escape, unstable reads, or out-of-scope cited paths make the snapshot unconfirmed.

`step-start --kind scout` reserves the snapshot and routed alias. Only a completed matching step can bind the exact `<step_id>.md` capsule once through `scout-bind`. The binding records the body digest, action fingerprint, step ID, model alias, HEAD, evidence digest and scope confirmation. `scout-validate` reads but never re-signs the capsule, sidecar and current pointer; all must agree. Stale, invalid, unbound or superseded capsules cannot skip Scout. A new completed reservation is required to bind again. `dispatch --scout-cached` independently verifies the binding; `orchestration.scout_on_retry` only requests a new Scout when no current valid capsule exists.

## Hosted session fencing and administrator recovery

Hosted ownership and persisted execution progress share a SQLite coordinator. Acquisition,
standalone domain-lease checks, and session release inspect validated pending progress inside
`BEGIN IMMEDIATE`. A foreign, orphan or expired owner's pending step remains a fence; expiry
only removes execution authority. Malformed progress, including duplicate JSON keys or invalid
pending/counter fields, refuses acquisition and release without changing the database. A live
owner may renew its lease while its child runs. `session-end` validates idle progress and deletes
ownership atomically; there is no gap permitting a new reservation between those operations.

Ownership verification and health projections are read-only: they open a deferred transaction,
verify the current owner and the pending-child fence, and never extend the lease. Only the lifecycle
edges `bootstrap`, `bootstrap-finalize`, `step-start`, `step-finish`, `session-start`,
`session-checkpoint` and `session-recover` write `expires_at`. Polling `dispatch`, `guard-status`,
`scout-validate` or `session-status` therefore cannot keep a dead owner alive, and still refuses a
foreign, orphan or expired owner exactly as before.

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
artifact. Existing operational progress remains backward-readable.

## Hosted resource checkpoints

`orchestration.hosted.max_steps` bounds reserved child spawns within one resource segment, including Scouts and capability fallbacks (default 100). A non-progressing primary increments the persisted semantic retry index; Scout and spawn-capability failures do not. The default final no-progress retry index is five (attempts 0 through 5), and the default per-action visit ceiling is four. Every reserved spawn consumes a resource step. These counts are execution guards, not measured Codex child tokens.

Action fingerprints are versioned SHA-256 identities over routing-relevant action/risk fields. Transient role overrides are excluded. A legacy v1 operational checkpoint resets per-action counters on first v2 observation without changing lifecycle artifacts. Semantic attempts, visits and resource steps persist across checkpoints, ordinary session end/start, TTL owner replacement and administrator recovery. Only an explicit valid `session-checkpoint` resets the resource segment.

After independently observing every child has terminated and acknowledging every reserved
step, the Supervisor may explicitly call `session-checkpoint <domain> --session-id <owner>`.
The host re-reads the current lifecycle action. One coordinator transaction requires a live
matching owner, idle progress, a completed action transition since the previous resource
checkpoint, and satisfied no-progress/cycle guards. The latest `capability_blocked` outcome
also refuses checkpointing. Only the step ceiling is excluded from this check. The transaction
replaces the owner and resets segment steps, preserving semantic attempts and action visits.
The Supervisor must retain the returned new `session_id` before scheduling another child.
No worker is launched by this command. Concurrent old-owner begin/end/checkpoint commands
cannot change the new owner; failed checks or writes preserve progress and ownership together.

Operational progress adds optional `segment_progressed` (boolean) and `last_outcome`
(`completed`, `failed`, `cancelled`, `capability_blocked`, or null). Older records remain
readable. A legacy record with at least two distinct persisted action visits supplies positive
transition evidence for one checkpoint; a single visited action supplies none. Legacy records
cannot reconstruct the last outcome, so a historical capability failure after earlier progress
cannot be identified. The first checkpoint writes explicit false progress and null outcome,
preventing repeated legacy budget renewal without a newly acknowledged action transition.
These operational fields introduce no lifecycle artifact, field or transition changes.
