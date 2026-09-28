---
name: autopilot
description: Operate, inspect, resume, or diagnose DevFlow's autonomous routing controller and its model/backend decisions.
---

# DevFlow Autopilot

Use the deterministic runtime controller. Do not reconstruct routes from chat history.

```bash
devflow autopilot capabilities
devflow autopilot route <domain> [--attempt N]
devflow autopilot status <domain>
devflow autopilot start <domain> [--until plan|implementation|complete]
devflow autopilot resume <domain> [--until plan|implementation|complete]
```

`route` is a dry inspection of the current action. `start` and `resume` run in the foreground and write operational telemetry only under `.devflow/runtime/<domain>/`. PLAN, WORK, STATE, and AUDIT remain lifecycle authority.

`--until plan` completes the planning lifecycle before phase delivery. `--until implementation` completes phase delivery and its required review gates before integration or finalization. `--until complete` is the default full lifecycle. A reached boundary records status `checkpoint` and exits successfully. Staged boundaries apply only to `delivery` workflows.

Use a fresh `start` after a successful checkpoint so the next stage gets a new run budget and operational state. Use `resume` for an interrupted or blocked run that should retain its retry, scout, unavailable-candidate, and token-budget telemetry.

Model selection precedes backend selection. The router selects a logical capability profile and effort; the capability resolver then uses a compatible native bridge when configured or an isolated `codex exec` session. Specialists receive bounded rendered packets rather than the parent conversation history.
