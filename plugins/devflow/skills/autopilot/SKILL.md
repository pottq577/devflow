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
devflow autopilot start <domain>
devflow autopilot resume <domain>
```

`route` is a dry inspection of the current action. `start` and `resume` run in the foreground and write operational telemetry only under `.devflow/runtime/<domain>/`. PLAN, WORK, STATE, and AUDIT remain lifecycle authority.

Model selection precedes backend selection. The router selects a logical capability profile and effort; the capability resolver then uses a compatible native bridge when configured or an isolated `codex exec` session. Specialists receive bounded rendered packets rather than the parent conversation history.
