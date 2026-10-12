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

The durable lease is renewed by those host commands and expires after 24 hours without renewal. An expired owner must stop; do not continue operating on a prior dispatch or release another owner's lease. If a sub-agent may remain active longer than the lease, refresh the lease with the same `session-start --session-id` during the wait; do not let it expire while children are running.

After every child has finished or been cancelled, release ownership on `complete`, `checkpoint`, `paused`, or a terminal blocker:

```bash
python3 <this-skill-directory>/scripts/host.py session-end <domain> \
  --session-id <session_id>
```

Never release a lease while a child is still changing repository artifacts. A failed/crashed session's stale lease is reclaimable after expiry, but first ensure no prior child agent is still active. `session-status <domain>` reports whether the domain remains occupied.

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

The runtime re-reads lifecycle STATE to detect progress. A non-progressing primary increments the persisted semantic retry, even if the child says it succeeded. A scout or model-spawn capability blocker does not increment the semantic retry, but **every reserved spawn consumes a cumulative step**. The default limits are 100 reserved spawns, five non-progressing primary attempts per action, and four visits to one action across progress transitions. The repository can override `orchestration.hosted.max_steps`, `orchestration.hosted.max_action_visits`, and `escalation.retries.max_no_progress`. Exceeding a bound blocks rather than silently resetting it. This is an execution-count guard, **not** a token budget: Codex-hosted sub-agent token usage is not measured reliably by these commands.

On a supervisor restart, resume the **same** hosted session and run `guard-status <domain> --session-id <session_id>`. If it reports `hosted_step_inflight`, do not spawn again or release the lease. Check whether the earlier child is still running; only after it has finished or been cancelled may the supervisor acknowledge the persisted pending `step_id` using `step-finish`. If child state cannot be verified, leave the run blocked for human intervention. An expired session id cannot resume or force-reclaim the state of an active child.

## Record hosted dispatch telemetry

Record each scout and primary spawn attempt around the host wait. Telemetry is optional and fail-open; `step-start`/`step-finish` are mandatory, fail-closed execution controls and cannot be replaced by telemetry.

Before a spawn attempt, run:

```bash
python3 <this-skill-directory>/scripts/host.py telemetry-start <domain> \
  --kind <scout|primary> --attempt <attempt> \
  --until <plan|implementation|complete> [--candidate-alias <alias>]
```

Keep the returned `dispatch_id`. After the wait finishes, run:

```bash
python3 <this-skill-directory>/scripts/host.py telemetry-finish <domain> \
  --dispatch-id <dispatch_id> \
  --outcome <completed|failed|cancelled|capability_blocked>
```

Use `--candidate-alias` when retrying a payload candidate after a spawn capability failure. If either command returns `telemetry_unavailable`, continue the lifecycle. Telemetry must never block or change a routed action.

For `dispatch_required`:

1. Compare `fingerprint` with the previous action and clear cached scout, scout alias, and diagnosis on changes. Trust the guard's persisted `attempt`, not a locally incremented value.
2. If `scout` is present and not cached, call `step-start --kind scout` first, optionally record telemetry, spawn it, wait, optionally finish telemetry, then **always** call `step-finish`. Cache its answer and alias only when it really completed successfully.
3. Build the primary message for the selected candidate. With a successful different-model scout, use `primary.scout_message` and append the cached scout under `## Repository scout`. Otherwise use `primary.message`. Append a prior diagnosis only when it is available.
4. Call `step-start --kind primary`, optionally record telemetry, spawn the routed model and wait for its terminal result, optionally finish telemetry, then call `step-finish` with the truthful outcome. Do not implement the routed action in the parent session.
5. On a successful diagnostician, cache its final answer for the next worker dispatch. Request `host.py dispatch` again without `--attempt`; the guard computes the next attempt from persisted progress, or blocks if a limit is reached.
6. On `complete`, `checkpoint`, `paused`, or a terminal `blocked` result, stop. Release the domain lease only after all reserved steps have been acknowledged and all children have ended.

When a routed model cannot spawn, acknowledge that reservation with `capability_blocked` and retry only ordered entries in that payload's `candidates`, reserving another step for each attempt. Keep the routed reasoning effort; do not cross into a model outside the routed profile.

Finish the failed spawn's telemetry with `capability_blocked` before trying the next routed candidate. Start a new telemetry record with that candidate's alias.

The host wait mechanism owns child runtime and cancellation. Do not add a second DevFlow hard timeout around native sub-agents and do not busy-poll them.

## Preserve lifecycle ownership

The Goal Supervisor does not author product artifacts, implement product code, choose the next WORK item, or manually swap models. Each child reads its role contract and renders the authoritative runtime packet from the repository. The parent only prepares deterministic dispatches, delegates them, observes lifecycle progress, and applies retry routing.

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
