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
  --requirements-file .devflow/runtime/<domain>/goal-requirements.md \
  --risk <low|medium|high|critical>
```

5. Spawn `primary` from the returned envelope. Use `fork_turns="none"`. Wait for that agent to finish.
6. Validate the generated PRD and initialize the domain:

```bash
python3 <this-skill-directory>/scripts/host.py bootstrap-finalize <domain> \
  --risk <low|medium|high|critical>
```

Use an explicit user-provided risk when present. Otherwise use `medium`. For an existing domain, preserve PRD, PLAN, WORK, STATE, and completed audit artifacts, then skip bootstrap.

Standalone compatibility keeps `autopilot bootstrap` available. Do not use it from the host-native Goal Supervisor because it creates a nested agent process.

## Run the autonomous lifecycle

Keep `attempt`, `fingerprint`, `scout_digest`, and `diagnosis` in supervisor state for the current `/goal` invocation. Start with `attempt=0` and no cached scout or diagnosis.

Prepare one deterministic dispatch at a time:

```bash
python3 <this-skill-directory>/scripts/host.py dispatch <domain> \
  --attempt <attempt> \
  --until <plan|implementation|complete>
```

Handle the returned status as follows:

- `complete`: finish the goal
- `checkpoint`: finish the requested boundary successfully
- `paused`: report the human decision immediately
- `dispatch_required`: run the returned sub-agent work

For `dispatch_required`:

1. Compare the returned `fingerprint` with the previous fingerprint. Clear cached scout and diagnosis when it changes.
2. If `scout` is present and no scout result is cached for this fingerprint, spawn it first. Wait for its final answer and cache that answer as `scout_digest`.
3. Build the primary message from `primary.message`. Append the cached scout under `## Repository scout` when present. Append the cached diagnosis under `## Prior independent diagnosis` when present.
4. Spawn `primary` with its routed model, reasoning effort, task name, and `fork_turns`. Wait for the agent to finish. Do not implement the routed action in the parent session.
5. Run `host.py dispatch` again with the same attempt. If the fingerprint changed, reset `attempt=0`, clear cached scout and diagnosis, and continue.
6. If the fingerprint did not change, increment `attempt` by one. When the completed primary role was `diagnostician`, cache its final answer as `diagnosis` before the next worker dispatch.
7. Stop with a blocker when the unchanged action exceeds `retry.max_no_progress`.

When a routed model cannot spawn, retry only the ordered entries in that payload's `candidates`. Keep the same reasoning effort. Do not cross into a model outside the routed profile.

The host wait mechanism owns child runtime and cancellation. Do not add a second DevFlow hard timeout around native sub-agents and do not busy-poll them.

## Preserve lifecycle ownership

The Goal Supervisor does not author product artifacts, implement product code, choose the next WORK item, or manually swap models. Each child reads its role contract and renders the authoritative runtime packet from the repository. The parent only prepares deterministic dispatches, delegates them, observes lifecycle progress, and applies retry routing.

Routing policy lives in `core/routing/default.yaml` plus optional `.devflow/routing.yaml` overrides. Concrete model bindings live in `core/routing/models.yaml` plus optional `.devflow/models.yaml` overrides.

## Inspect state

For a hosted Goal, inspect lifecycle authority with:

```bash
devflow status <domain> --json
python3 <this-skill-directory>/scripts/host.py dispatch <domain> \
  --attempt <attempt> --until <plan|implementation|complete>
```

`devflow autopilot status`, `autopilot start`, and `autopilot resume` describe the standalone controller. Do not treat a stale standalone controller checkpoint as hosted Goal state.
