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

The command returns the routed action, model, reasoning effort, and a compact repository-recovery message. **Before each scout or primary spawn**, use `host.py step-start` with the envelope's fingerprint, attempt and candidate alias. After its host wait, acknowledge the step with `host.py step-finish`. The durable guard bounds total spawns, semantic retries and repeated-action cycles; `dispatch` alone does not consume a step. Use `host.py guard-status --session-id <session_id>` when resuming the original session. Never repeat a pending spawn or release a session with an unacknowledged child. The child renders the authoritative packet; the supervisor does not copy PRD, PLAN or WORK. See `skills/goal/SKILL.md` for the required bootstrap and failure procedure. Keep the same session id, renew it before expiry, and run `host.py session-end` only after all children finish. Never take over another owner's lease. Bind optional telemetry to its step id and validate Scout capsules with `scout-validate` before omitting the specialist's full runtime packet.

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
