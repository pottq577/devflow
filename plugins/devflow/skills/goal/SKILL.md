---
name: goal
description: Start or resume a DevFlow autonomous delivery goal, optionally bounded at planning or implementation. Use when the user invokes /goal or asks DevFlow to carry approved requirements through routed lifecycle work without manually selecting each step.
---

# DevFlow Goal

Operate as the thin **Goal Supervisor**. The DevFlow runtime selects lifecycle actions and model routes. The Codex host owns sub-agent lifecycle when host-native delegation is available.

## Use host-native delegation

This skill explicitly authorizes sub-agent delegation for DevFlow lifecycle work. Use the host `spawn_agent` and wait tools for routed specialists. Pass the routed `model`, `reasoning_effort`, `task_name`, `fork_turns`, and `message` from the host dispatch envelope without rewriting them.

Do not launch a nested `codex exec` session from a Codex-hosted `/goal` run. Do not call `autopilot start` or `autopilot resume` from this host-native path. Those commands remain standalone compatibility drivers for environments that do not expose native sub-agents.

If the host does not expose model or reasoning-effort overrides required by the dispatch envelope, report a capability blocker. Do not silently inherit the parent model because that bypasses DevFlow routing policy.

## Own the domain before any hosted work

Before writing goal requirements, bootstrapping, or dispatching, acquire the domain lease from the repository root:

```bash
python3 <this-skill-directory>/scripts/host.py session-start <domain>
```

Keep the returned `session_id` private to the active Goal Supervisor and pass it as `--session-id <session_id>` to **every** `bootstrap`, `bootstrap-finalize`, and `dispatch` call. A second hosted Goal or standalone Autopilot cannot acquire the same domain while this lease is live. A restarted supervisor may resume only with the same id using `session-start <domain> --session-id <session_id>`; never create a replacement session while another owner's session is active. No session id may be inferred from telemetry.

The durable lease is renewed by the lifecycle edges `bootstrap`, `bootstrap-finalize`, `step-start` and `step-finish`, and expires after 24 hours without renewal. Observation commands (`dispatch`, `guard-status`, `scout-validate`, `session-status`) verify ownership and pending-child fencing without extending it. An expired owner must stop; do not continue operating on a prior dispatch or release another owner's lease. If a sub-agent may remain active longer than the lease, refresh the lease with the same `session-start --session-id` during the wait; do not let it expire while children are running.

After every child has finished or been cancelled, release ownership on `complete`, `checkpoint`, `paused`, or a terminal blocker:

```bash
python3 <this-skill-directory>/scripts/host.py session-end <domain> \
  --session-id <session_id>
```

Never release a lease while a child is still changing repository artifacts. TTL expiry removes execution authority, never pending child evidence. An expired or orphan pending step fences both hosted Goal and standalone Autopilot acquisition. `session-status <domain>` reports `blocked` until that evidence is resolved; an idle expired lease can be replaced.

When the original owner cannot acknowledge a pending step, stop for a trusted administrator. The administrator must independently confirm the exact child has terminated, then record the original session and step:

```bash
python3 <this-skill-directory>/scripts/host.py session-recover <domain> \
  --session-id <original_session_id> --step-id <exact_step_id> \
  --outcome <completed|failed|cancelled|capability_blocked> \
  --confirm-child-terminated --termination-evidence '<trusted administrator facts>'
```

This is an `explicit_admin_attestation`, not native PID or terminal-status verification. The Goal Supervisor must never self-attest termination, infer it from TTL, or invent administrator facts. Unknown or live child state stays blocked. Recovery atomically records a SQLite receipt, applies ordinary finish retry accounting, clears the pending step and releases the original lease. Repeating the exact outcome and evidence returns the same receipt; changed facts or a different current owner are rejected. Malformed execution evidence is fail-closed. See `core/protocol/host-telemetry.md` for the operational fencing contract.

## Bootstrap a new domain

1. Resolve the repository root and domain slug from the request and existing DevFlow domains.
2. Separate `/goal` execution controls from product requirements. `--until plan|implementation|complete` controls the supervisor and is not product intent.
3. Persist the user's approved requirements verbatim to `.devflow/runtime/<domain>/goal-requirements.md`.
   - Do not summarize, reinterpret, decompose, or turn them into a PRD in the parent session.
   - Do not write execution-control options such as `--until` into the requirements file.
   - Preserve requirement and acceptance IDs exactly.
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

The runtime re-reads lifecycle STATE to detect progress. A non-progressing primary increments the persisted semantic retry, even if the child says it succeeded. A scout or model-spawn capability blocker does not increment the semantic retry, but **every reserved spawn consumes a resource-segment step**. The default limits are 100 reserved spawns per segment, a final no-progress retry index of five (attempts 0 through 5), and four visits to one action across progress transitions. Fingerprints are versioned SHA-256 identities over routing-relevant action/risk fields; transient role overrides are excluded. Existing v1 operational checkpoints reset their per-action counters when first observed as v2, without modifying lifecycle artifacts. The repository can override `orchestration.hosted.max_steps`, `orchestration.hosted.max_action_visits`, and `escalation.retries.max_no_progress`. Attempts, visits and resource steps survive ordinary session end/start, expiry and administrator recovery. This is an execution-count guard, **not** a token budget: Codex-hosted sub-agent token usage is not measured reliably by these commands.

To continue after `hosted_max_steps_exhausted`, independently confirm all children have terminated, acknowledge every reserved step, and require an idle guard. Then explicitly renew the resource segment:

```bash
python3 <this-skill-directory>/scripts/host.py session-checkpoint <domain> \
  --session-id <session_id>
```

Replace the saved owner with the returned `session_id` before reserving another child. Checkpoint requires actual acknowledged action progress in this segment and satisfied retry/cycle guards; a latest `capability_blocked` outcome refuses renewal. It atomically resets only resource steps, never attempts or visits, and launches no child. Do not use ordinary end/start to replenish budgets. Legacy records require positive evidence from at least two distinct persisted action visits; single-action exhaustion remains blocked. Historical last outcomes are unavailable for legacy records; this migration allowance can renew at most once without new progress. These resource checkpoints are separate from a requested lifecycle `--until` boundary.

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

Use `--candidate-alias` when retrying a payload candidate after a spawn capability failure. Run `telemetry-finish` **before** acknowledging its `step-finish`, while that step is still reserved. If either telemetry command returns `telemetry_unavailable`, continue the lifecycle; do not fabricate a `dispatch_id`. Telemetry must never block or change a routed action.

Always pass the guard's current `attempt`, including zero. Record the returned `reason` on `telemetry_unavailable` so missing attempts and reservation mismatches are visible. When reporting packet/protocol/capsule bytes or stage durations, read `core/protocol/host-telemetry.md` for the observation format and measurement boundaries. Supply only directly observed values; omitted values and native token usage remain unmeasured. Finish a legacy v2 inflight record without an observations file.

For `dispatch_required`:

1. Compare `fingerprint` with the previous action and clear cached scout, scout alias, and diagnosis on changes. Trust the guard's persisted `attempt`, not a locally incremented value.
2. If `scout` is present and not cached, call `step-start --kind scout` first, optionally record telemetry, spawn it, wait, optionally finish telemetry, then **always** call `step-finish`. Save a successful scout's final text as UTF-8 under `.devflow/runtime/<domain>/scout-capsules/`. Validate it with `host.py scout-validate <domain> --session-id <session_id> --fingerprint '<fingerprint>' --capsule-file <path>`. Cache the text and scout alias **only** if validation returns `valid` and the action fingerprint remains unchanged; otherwise discard it. A `stale` verdict means the evidence the scout actually read has moved, so treat the capsule as absent even though its shape is valid. When you do hold a capsule that still validates, pass `dispatch --scout-cached` so a retry does not spend a second scout on unchanged evidence.
3. Build the primary message for the selected candidate. **Only** with a validated different-model scout, use `primary.scout_message` and append the validated capsule under `## Repository scout`. Otherwise use `primary.message` so the specialist renders the full authoritative packet. Preserve the generated `--expected-head` (full SHA or `unborn`) and `--expected-fingerprint` pins. The child starts with pinned render, or pinned `render --check-only` for the compact path, without an initial full status. A failed pin check stops the child without mutation; return the blocker, acknowledge the step truthfully, and obtain a fresh dispatch instead of selecting another action in that child. Mutating children retain their final status check and receipt; read-only roles retain `--no-refresh`. A scout child receives `render evidence` instead of the full action packet and must open the cited originals itself. Do not truncate a scout response to fit the limit. Append a prior diagnosis only when it is available.
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

Routing policy lives in `core/routing/default.yaml` plus optional `.devflow/routing.yaml` overrides. Concrete model bindings live in `core/routing/models.yaml` plus optional `.devflow/models.yaml` overrides.

## Inspect state

For a hosted Goal, inspect lifecycle authority with:

```bash
devflow status <domain> --json
python3 <this-skill-directory>/scripts/host.py dispatch <domain> \
  --session-id <session_id> \
  --until <plan|implementation|complete>
python3 <this-skill-directory>/scripts/host.py guard-status <domain> \
  --session-id <session_id>
```

`devflow autopilot status`, `autopilot start`, and `autopilot resume` describe the standalone controller. Do not treat a stale standalone controller checkpoint as hosted Goal state.
