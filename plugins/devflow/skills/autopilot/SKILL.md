---
name: autopilot
description: Operate, inspect, resume, or diagnose DevFlow's autonomous routing controller and its model/backend decisions.
---

# DevFlow Autopilot

Use DevFlow's deterministic lifecycle state and routing policy. Choose the execution driver based on the host environment.

## Use the host-native driver inside Codex

This skill explicitly authorizes sub-agent delegation for DevFlow lifecycle work. In a Codex session with `spawn_agent`, first acquire the hosted domain lease and retain its returned session id. Then prepare child dispatches with the host wrapper:

```bash
python3 <this-skill-directory>/scripts/host.py session-start <domain>
python3 <this-skill-directory>/scripts/host.py dispatch <domain> \
  --session-id <session_id> --until <plan|implementation|complete>
```

The host returns the routed action, model and effort. Follow `skills/goal/SKILL.md` and `core/protocol/host-telemetry.md` for the complete lease, bootstrap, guard, recovery and Scout rules. Before every child spawn, reserve `host.py step-start`; acknowledge it with `host.py step-finish` after the host wait. Do not repeat a pending spawn, inherit an unrequested model, or release a lease with running/unacknowledged children. Use `host.py guard-status --session-id <session_id>` when resuming.

Do not run `codex exec` from this host-native path. Do not silently inherit the parent model when the host cannot honor the routed model or reasoning effort. Report that condition as a capability blocker. Use `devflow status <domain> --json` for hosted lifecycle state; `devflow autopilot status` is standalone-controller telemetry.

## Use the standalone driver outside a host session

The existing controller remains available for shells, CI jobs, and hosts without native sub-agents:

```bash
devflow autopilot capabilities
devflow autopilot route <domain> [--attempt N]
devflow autopilot status <domain>
devflow autopilot start <domain> [--until plan|implementation|complete]
devflow autopilot resume <domain> [--until plan|implementation|complete]
```

`route` only inspects the current action. `start` and `resume` run in the foreground and may use the configured native command bridge or isolated `codex exec` fallback. They write operational telemetry under `.devflow/runtime/<domain>/`. PLAN, WORK, STATE, and AUDIT remain lifecycle authority.

`--until plan` completes planning before phase delivery. `--until implementation` completes phase WORK and required review gates before integration or finalization. `--until complete` runs the full lifecycle. A reached boundary returns `checkpoint`. Staged boundaries apply only to delivery workflows.

Use a fresh `start` after a successful checkpoint. Use `resume` only when the standalone controller should retain retry, scout, unavailable-candidate, and token-budget telemetry.

Model selection always precedes execution-backend selection. The host-native driver delegates the selected model directly through Codex sub-agents. The standalone driver keeps the existing backend fallback for non-host environments.
