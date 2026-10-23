---
name: goal
description: Start or resume a DevFlow autonomous delivery goal, optionally bounded at planning or implementation. Use when the user invokes /goal or asks DevFlow to carry approved requirements through routed lifecycle work without manually selecting each step.
---

# DevFlow Goal

Operate as the thin **Goal Supervisor**. The DevFlow runtime selects lifecycle actions and model routes. Codex and Claude Code own their native sub-agent lifecycle; DevFlow never launches either host CLI as a nested supervisor.

## Use host-native delegation

This skill explicitly authorizes sub-agent delegation for DevFlow lifecycle work. In **Codex**, use `spawn_agent` and wait, passing the routed `model`, `reasoning_effort`, `task_name`, `fork_turns`, and `message` without rewriting them. In **Claude Code**, use the foreground `Agent` tool with the exact `primary.claude.agent_type` or `scout.claude.agent_type` from the host dispatch envelope and the corresponding routed message. The plugin Agent preset pins `model` and `effort`; do not request a generic subagent or inherit the parent model. `fork_turns` is Codex-specific and is ignored by Claude Code.

For every CLI example in this skill, **Claude Code** replaces `skills/goal/scripts/host.py` with `skills/goal/scripts/claude_host.py` (including resume, dispatch, step reservation, finish, telemetry and recovery). Codex continues to use `host.py`. Do not mix wrappers inside one active host session. Read `core/protocol/claude-native-host.md` before Claude native dispatch.

Do not launch nested `codex exec` or `claude -p`. Do not call `autopilot start` or `autopilot resume` from a host-native `/goal`. They are standalone compatibility drivers.

If the host cannot invoke the **exact** routed model and effort, report a capability blocker. Do not silently inherit or downgrade the model. In Claude Code, inspect the native Agent result for an explicit terminal outcome; partial output on API quota exhaustion is not a successful completion and never authorizes `step-finish --outcome completed`.

## Own the domain before any hosted work

Before writing goal requirements, bootstrapping, or dispatching, inspect the
read-only handoff projection from the repository root:

```bash
python3 <this-skill-directory>/../../scripts/devflow.py execution handoff <domain>
```

Read the computed lifecycle action and hosted ownership separately. If the prior
host still owns the live lease and you lack its exact private session ID, stop
and request a human-verified idle handoff. Never self-attest source termination.
If a child is pending, do not hand off: retain the existing administrator child
recovery gate. Do not interpret a journal checkpoint as WORK completion.

For a fresh domain or after a clean release, acquire the lease with the native
host wrapper. The wrapper binds `codex` or `claude` atomically:

```bash
python3 <this-skill-directory>/scripts/host.py session-start <domain>
```

Keep the returned `session_id` private. Pass it to every `bootstrap`, `bootstrap-finalize`, and `dispatch` call. Resume a restarted Supervisor only with `session-start <domain> --session-id <session_id>`; never invent an owner from telemetry or replace a live session.

The lease expires after 24 hours without a lifecycle renewal. Read-only observation commands do not renew it. Refresh the same owner through `session-start --session-id` during a long-running child wait, and stop if ownership expires. `core/protocol/host-telemetry.md` owns the full lease and pending-child fencing rules.

After every child has finished or been cancelled, release ownership on `complete`, `checkpoint`, `paused`, or a terminal blocker:

```bash
python3 <this-skill-directory>/scripts/host.py session-end <domain> \
  --session-id <session_id>
```

Never release a lease with an unacknowledged or running child. Expiry never proves child termination; an orphan step fences new ownership. When the original owner cannot acknowledge a step, stop for a trusted administrator who confirms the exact child has terminated:

```bash
python3 <this-skill-directory>/scripts/host.py session-recover <domain> \
  --session-id <original_session_id> --step-id <exact_step_id> \
  --outcome <completed|failed|cancelled|capability_blocked> \
  --confirm-child-terminated --termination-evidence '<trusted administrator facts>'
```

`session-recover` records an administrator's explicit attestation, not native termination evidence. The Supervisor must never self-attest or infer termination from TTL. Unknown or live children remain blocked. See `core/protocol/host-telemetry.md` for receipt, idempotence and fencing details.

For an idle source host that stopped but retains a live lease, an operator may
run `session-status` then `session-handoff --to-host <target>
--expected-owner-marker <observed_marker> --confirm-source-stopped
--source-stop-evidence <observed_fact>`. Never call `session-handoff` as the
Supervisor or invent termination evidence. The operator must pass the new
private `session_id` to the new host. Resume that exact owner via `session-start
--session-id <new_id> --host <target>`; do not create a competing owner.

## Bootstrap a new domain

1. Resolve the repository root and domain slug from the request and existing DevFlow domains.
2. Separate `/goal` execution controls from product requirements. `--until plan|implementation|complete` controls the supervisor and is not product intent.
3. Persist the user's approved requirements verbatim to `.devflow/runtime/<domain>/goal-requirements.md`.
   - Do not summarize, reinterpret, decompose, or turn them into a PRD in the parent session.
   - Do not write execution-control options such as `--until` into the requirements file.
   - Preserve requirement and acceptance IDs exactly.
   - When both original and supplemental files are provided, run `python3 <this-skill-directory>/../../scripts/devflow.py sources capture <domain> --original '<original_path>' --context '<context_path>'` before step 4.
   - Preserve both file contents unchanged. If either supplied source is unavailable, stop rather than dropping it. An analysis in the supplemental file does not imply product approval.
4. Prepare the routed bootstrap envelope from the repository root:

```bash
python3 <this-skill-directory>/scripts/host.py bootstrap <domain> \
  --session-id <session_id> \
  --requirements-file .devflow/runtime/<domain>/goal-requirements.md \
  --risk <low|medium|high|critical>
```

5. Before spawning, reserve a durable bootstrap step using the envelope's `fingerprint`, `attempt: 0`, and `primary.model_alias`:

```bash
python3 <this-skill-directory>/scripts/host.py step-start <domain> \
  --session-id <session_id> --kind bootstrap \
  --fingerprint '<fingerprint>' --candidate-alias <alias> --attempt 0 \
  --risk <low|medium|high|critical>
```

6. Keep the returned `step_id`. Spawn `primary` with `fork_turns="none"` and wait for it to finish. Do not reserve another step while this child is running.
7. On successful child completion, validate the PRD and initialize the domain:

```bash
python3 <this-skill-directory>/scripts/host.py bootstrap-finalize <domain> \
  --session-id <session_id> \
  --risk <low|medium|high|critical>
```

8. After `bootstrap-finalize` succeeds, call `step-finish <domain> --session-id <session_id> --step-id <step_id> --outcome completed`. If the spawn fails or is cancelled, finish with the truthful `capability_blocked` or `cancelled` outcome and do not initialize the domain. If `bootstrap-finalize` fails, finish with `failed` and report the blocker. Never fabricate lifecycle progress.

Use an explicit user-provided risk when present. Otherwise use `medium`. For an existing domain, preserve PRD, PLAN, WORK, STATE, and completed audit artifacts, then skip bootstrap.

Standalone compatibility keeps `autopilot bootstrap` available. Do not use it from the host-native Goal Supervisor because it creates a nested agent process.

## Run the autonomous lifecycle

Keep `scout_digest`, `scout_alias`, `diagnosis`, and the latest `fingerprint` only as local supervisor context. **Do not maintain a separate retry or step counter in the parent session.** The session-fenced host guard owns durable `attempt`, cumulative spawn count, and repeated-action visits. On a resumed supervisor, use the same session id and obtain these values from `guard-status` or `dispatch`.

Prepare one deterministic dispatch at a time:

```bash
python3 <this-skill-directory>/scripts/host.py dispatch <domain> \
  --session-id <session_id> --until <plan|implementation|complete>
```

Handle the returned status as follows:

- `complete`: finish the goal
- `checkpoint`: finish the requested boundary successfully
- `paused`: report the human decision immediately
- `dispatch_required`: follow the guarded sub-agent procedure below
- `blocked`: stop without spawning; preserve the reported reason

## Reserve and acknowledge every hosted child

`dispatch` and `guard-status` are observational: calling either repeatedly does not spend an execution step. A **real** scout or primary spawn must first reserve one step using the current envelope `fingerprint`, `attempt`, and selected candidate alias. Use the same execution boundary as the envelope:

```bash
python3 <this-skill-directory>/scripts/host.py step-start <domain> \
  --session-id <session_id> --kind <scout|primary> \
  --fingerprint '<fingerprint>' --candidate-alias <alias> \
  --attempt <attempt> --until <plan|implementation|complete>
```

If `step-start` is blocked, **do not spawn**. Preserve the returned `step_id`. Only after the host wait confirms the child has ended, acknowledge that exact step:

```bash
python3 <this-skill-directory>/scripts/host.py step-finish <domain> \
  --session-id <session_id> --step-id <step_id> \
  --outcome <completed|failed|cancelled|capability_blocked> \
  --until <plan|implementation|complete>
```

The runtime detects progress from lifecycle STATE. Follow the guard's persisted attempt, visit and resource-step counters; never reset them in Supervisor memory or treat a child's success message as lifecycle progress. `core/protocol/host-telemetry.md` owns their defaults, fingerprints, limits and migration rules.

After `hosted_max_steps_exhausted`, confirm all children terminated, acknowledge all reserved steps, and require an idle guard. Then request a resource checkpoint:

```bash
python3 <this-skill-directory>/scripts/host.py session-checkpoint <domain> \
  --session-id <session_id>
```

Save the returned new `session_id` before spawning again. Checkpoint requires recorded progress, acknowledged children and satisfied retry/cycle guards. It resets resource steps only, never semantic attempts or visits, and launches no child. End/start cannot replenish the budget. See `core/protocol/host-telemetry.md` for legacy checkpoint handling.

On a supervisor restart, resume the **same** hosted session and run `guard-status <domain> --session-id <session_id>`. If it reports `hosted_step_inflight`, do not spawn again or release the lease. Check whether the earlier child is still running; only after it has finished or been cancelled may the supervisor acknowledge the persisted pending `step_id` using `step-finish`. If child state cannot be verified, leave the run blocked for human intervention. An expired session id cannot resume or force-reclaim the state of an active child.

## Record hosted dispatch telemetry

Record each scout and primary spawn attempt around the host wait. Telemetry is optional and fail-open; `step-start`/`step-finish` are mandatory, fail-closed execution controls and cannot be replaced by telemetry. Only a session-owned reserved `step_id` can create a telemetry record; `step_id` connects both telemetry events to one concrete spawn, not just an action name.

Before a spawn attempt, run:

```bash
python3 <this-skill-directory>/scripts/host.py telemetry-start <domain> \
  --session-id <session_id> --step-id <step_id> \
  --kind <scout|primary> --attempt <attempt> \
  --until <plan|implementation|complete> [--candidate-alias <alias>] \
  [--observations-file <path>]
```

Keep the returned `dispatch_id`. After the wait finishes, run:

```bash
python3 <this-skill-directory>/scripts/host.py telemetry-finish <domain> \
  --session-id <session_id> --step-id <step_id> \
  --dispatch-id <dispatch_id> \
  --outcome <completed|failed|cancelled|capability_blocked> \
  [--observations-file <path>]
```

Use `--candidate-alias` for a spawn-capability fallback. Call `telemetry-finish` before mandatory `step-finish`. Pass the guard's `attempt`, including zero. If telemetry is unavailable, record its reason and continue without inventing `dispatch_id` or measurements. `core/protocol/host-telemetry.md` owns the observation format and legacy compatibility.

For `dispatch_required`:

1. Compare `fingerprint` with the previous action and clear cached scout, scout alias, and diagnosis on changes. Trust the guard's persisted `attempt`, not a locally incremented value.
2. If `scout` is present and not cached, call `step-start --kind scout` first, optionally record telemetry, spawn it, wait, optionally finish telemetry, then **always** call `step-finish`. After a completed scout step, save its final text as UTF-8 to `.devflow/runtime/<domain>/scout-capsules/<step_id>.md`. Bind it once with `host.py scout-bind <domain> --session-id <session_id> --fingerprint '<fingerprint>' --capsule-file <path> --step-id <step_id> --model-alias <routed scout alias>`, then confirm it with `host.py scout-validate <domain> --session-id <session_id> --fingerprint '<fingerprint>' --capsule-file <path>`. The host accepts only the routed alias and completed receipt from that exact step, and consumes the receipt once. Cache the text and scout alias **only** if validation returns `valid` and the action fingerprint remains unchanged; otherwise discard it. Validation never writes, so an unbound or `stale` capsule stays `stale` until a new scout binds one. A `stale` verdict means the evidence snapshot has moved, so treat the capsule as absent even though its shape is valid. When you do hold a capsule that still validates, pass `dispatch --scout-cached`; the host checks the capsule, sidecar and current-capsule pointer before it skips a scout.
3. Build the primary message for the selected candidate. **Only** with a validated different-model scout, use `primary.scout_message` and append the validated capsule under `## Repository scout`. Otherwise use `primary.message` so the specialist renders the full authoritative packet. Preserve the generated `--expected-head` (full SHA or `unborn`) and `--expected-fingerprint` pins. The child starts with pinned render, or pinned `render --check-only` for the compact path, without an initial full status. A failed pin check stops the child without mutation; return the blocker, acknowledge the step truthfully, and obtain a fresh dispatch instead of selecting another action in that child. Mutating children retain their final status check and receipt; read-only roles retain `--no-refresh`. A scout child receives `render evidence` instead of the full action packet and must open the cited originals itself. The complete evidence render is capped at 32,768 UTF-8 bytes including its wrapper; omissions point to the original artifacts. Do not truncate a scout response to fit the separate capsule limit. Append a prior diagnosis only when it is available.
4. Call `step-start --kind primary`, optionally record telemetry, spawn the routed model and wait for its terminal result, optionally finish telemetry, then call `step-finish` with the truthful outcome. Do not implement the routed action in the parent session.
5. On a successful diagnostician, cache its final answer for the next worker dispatch. Request `host.py dispatch` again without `--attempt`; the guard computes the next attempt from persisted progress, or blocks if a limit is reached.
6. On `complete`, `checkpoint`, `paused`, or a terminal `blocked` result, stop. Release the domain lease only after all reserved steps have been acknowledged and all children have ended.

When a routed model cannot spawn, acknowledge that reservation with `capability_blocked` and retry only ordered entries in that payload's `candidates`, reserving another step for each attempt. Keep the routed reasoning effort; do not cross into a model outside the routed profile.

Finish the failed spawn's telemetry with `capability_blocked` before trying the next routed candidate. Start a new telemetry record with that candidate's alias.

The host wait mechanism owns child runtime and cancellation. Do not add a second DevFlow hard timeout around native sub-agents and do not busy-poll them.

Native `spawn_agent` does not provide a per-child sandbox override. A routed `permissions: read-only` value directs scout and diagnostician behavior but does not enforce filesystem isolation. Do not claim an OS-level read-only boundary without host-provided isolation; if strict isolation is required and unavailable, stop before spawning.

## Preserve lifecycle ownership

The Goal Supervisor does not author product artifacts, implement product code, choose the next WORK item, or manually swap models. Each child reads its role contract and renders the authoritative runtime packet from the repository. The parent only prepares deterministic dispatches, delegates them, observes lifecycle progress, and applies retry routing.
For hosted children, the generated pinned render/check-only replaces the role contract's initial status and render preflight. Do not repeat either before work; mutating children still run their required final status.

Routing policy lives in `core/routing/default.yaml` and `core/routing/models.yaml`, with optional `.devflow/routing.yaml` and `.devflow/models.yaml` overrides.

## Inspect state

Use `devflow status <domain> --json` for hosted lifecycle authority, and the session-scoped `host.py dispatch` and `host.py guard-status` commands above for ownership and retry state. Standalone `autopilot status/start/resume` telemetry is not hosted Goal state.
