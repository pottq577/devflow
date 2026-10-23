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

A capsule is reusable only when its validated text, action fingerprint, and evidence digest match the bounded index and step-start source snapshot. The snapshot covers the selected WORK, verification and failure references, WORK source paths, cited files, applicable repository instructions, routing configuration, and role protocols. Resolve paths under the repository or plugin root. Scout binding checks primary Evidence map anchors and other explicitly rooted file references from the capsule against the reserved scope; incidental numeric fractions, domain pairs and unqualified class names are not file citations. Missing required files, traversal, symlink escape, unstable reads, or out-of-scope cited paths make the snapshot unconfirmed.

`step-start --kind scout` reserves the snapshot and routed alias. Only a completed matching step can bind the exact `<step_id>.md` capsule once through `scout-bind`. The binding records the body digest, action fingerprint, step ID, model alias, HEAD, evidence digest and scope confirmation. `scout-validate` reads but never re-signs the capsule, sidecar and current pointer; all must agree. Stale, invalid, unbound or superseded capsules cannot skip Scout. A new completed reservation is required to bind again. `dispatch --scout-cached` independently verifies the binding; `orchestration.scout_on_retry` and `scout_on_critical` reuse a current valid capsule, while explicitly configured `scout_before` still forces a fresh read-only analysis. Scout bind failures return bounded provenance diagnostics without extending the source snapshot.

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
`session-checkpoint`, `session-handoff` and `session-recover` write `expires_at`.
Polling `dispatch`, `guard-status`,
`scout-validate` or `session-status` therefore cannot keep a dead owner alive, and still refuses a
foreign, orphan or expired owner exactly as before.

`session-recover <domain> --session-id <original_owner> --step-id <exact_step>` additionally
requires `--outcome completed|failed|cancelled|capability_blocked`, `--confirm-child-terminated`
and nonblank `--termination-evidence`. This is a trusted administrator's
`explicit_admin_attestation`, not runtime-verified native child termination. The Goal Supervisor
must not supply its own assertion or equate TTL expiry with child termination. Unknown or live
child state remains fenced. There is no automated takeover or abandon command.

Recovery accepts the exact persisted progress owner, including an expired or absent lease, and
rejects another current owner. Within one coordinator transaction it applies ordinary step-finish
progress/retry accounting, persists an operational `hosted_recovery` receipt, clears the pending
step and releases the lease. The receipt retains the original owner, exact pending step, outcome,
termination facts, after-action fingerprint and recovery time. Repeating the same owner, step,
outcome and evidence returns that receipt without applying accounting again; changed facts are
rejected. Any failed write rolls back the receipt, progress and lease together. Corrupt stored
receipts refuse recovery. These private runtime rows add no STATE/WORK fields or lifecycle
artifact. Existing operational progress remains backward-readable.

## Operator-attested idle host handoff

Hosted Goal sessions may retain a live lease when their native CLI host stops
without reaching `session-end`. `session-status <domain>` and
`devflow execution handoff <domain>` return a read-only `host` label and
`owner_marker`; the marker is a one-owner observation fingerprint, **not** the
private session ID or a permission to take ownership. Legacy unlabeled sessions
remain readable and acquire an optional `host` column on the next write.

If there is no live owner and no pending child, `session-start --host <target>`
remains sufficient. If the old owner still holds a live lease, an **operator** who
independently verified the source CLI has stopped and no child is running may
run the following command from the same repository:

```bash
python3 <goal-skill-directory>/scripts/host.py session-status <domain>
python3 <goal-skill-directory>/scripts/host.py session-handoff <domain> \
  --to-host claude --expected-owner-marker '<marker-from-status>' \
  --confirm-source-stopped --source-stop-evidence '<observed source termination>'
```

`session-handoff` atomically compares the current marker, validates the
persisted pending-child guard, checks for a standalone mutating lease, records
operator evidence and previous/target hosts, and rotates the session owner.
The old token is fenced. The operator must provide the returned **new private
session ID** only to the resumed host, which calls `session-start --session-id
<new_id> --host <target>`. No second host may be started in parallel. A stale
marker, unknown child, corrupt guard or missing attestation never changes the
owner. The Goal Supervisor must never manufacture the operator's attestation.

The transition preserves existing WORK, STATE, Git edits, attempt/visit counts,
resource steps, and completion gates. A pending child **cannot** use idle handoff,
even after TTL expiry; first use `session-recover` with exact original owner,
step ID and truthful observed child outcome. Handoff receipts stay inside the
private SQLite coordinator. They are operational evidence, not lifecycle
completion or a release-gate waiver. Claude-native invocation and model routing
are separate work; a stored target label alone does not enable Claude execution.

## Primary child dispatch provenance

A hosted primary `step-start` stores a bounded snapshot of the chosen lifecycle
action and, for a `run` action, the selected WORK ID/status/recorded evidence
SHA at reservation. The guard retains it with the pending step and the last
acknowledged step. Cross-host projections omit session and step tokens. These
are navigation facts only; a child receipt, even `completed`, never completes
WORK or replaces review. On recovery, compare this original identity to the
current repository WORK and next action before repeating or skipping work.
Administrative `session-recover` also retains this anchor in the last-step
operational receipt, labeled recovered, after the existing termination attestation.
No new replay permission or automatic orphan-child release is introduced.

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
