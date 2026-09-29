---
name: autopilot
description: Operate, inspect, resume, or diagnose DevFlow's autonomous routing controller and its model/backend decisions.
---

# DevFlow Autopilot

Use DevFlow's deterministic lifecycle state and routing policy. Choose the execution driver based on the host environment.

## Use the host-native driver inside Codex

This skill explicitly authorizes sub-agent delegation for DevFlow lifecycle work. In a Codex session with `spawn_agent`, prepare child dispatches with the host wrapper:

```bash
python3 <this-skill-directory>/scripts/host.py dispatch <domain> \
  --attempt <attempt> \
  --until <plan|implementation|complete>
```

The command returns the exact lifecycle action, routed model and reasoning effort, a bounded child message, retry limits, and an optional scout dispatch. Spawn those agents with the host tools and `fork_turns` from the envelope. The child recovers the full runtime packet from the repository, so the parent does not copy PRD, PLAN, WORK, or protocol text into a nested model prompt.

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
