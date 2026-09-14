---
name: goal
description: Start or resume a complete DevFlow autonomous delivery goal. Use when the user invokes /goal or asks DevFlow to carry approved requirements through planning, implementation, verification, remediation, finalization, and integration audit without manually selecting each lifecycle step.
---

# DevFlow Goal

Operate as the thin **Goal Supervisor**. DevFlow runtime owns lifecycle selection and model routing, including new-domain PRD bootstrap.

## Bootstrap

1. Resolve the repository root and domain slug from the request and existing DevFlow domains.
2. For a new domain, persist the user's approved requirements **verbatim** to a runtime input file such as `.devflow/runtime/<domain>/goal-requirements.md`.
   - Do not summarize, reinterpret, decompose, or turn them into a PRD in the parent session.
   - Preserve any requirement/acceptance IDs exactly as supplied.
3. Run the routed bootstrap from the repository root:

```bash
python3 <this-skill-directory>/scripts/invoke.py autopilot bootstrap <domain> \
  --requirements-file .devflow/runtime/<domain>/goal-requirements.md \
  --risk <low|medium|high|critical>
```

   - Use an explicit user-provided risk level when present; otherwise use `medium`.
   - Autopilot routes PRD creation to the Architect profile, validates the generated PRD, and initializes the domain only after the routed specialist succeeds.
   - Capability failures use the normal candidate fallback rules.
4. For an existing domain, preserve its current PRD/PLAN/WORK/STATE and skip bootstrap.

## Autonomous execution

For a newly initialized domain or an existing domain without an interrupted controller, run:

```bash
python3 <this-skill-directory>/scripts/invoke.py autopilot start <domain>
```

Use `autopilot resume` only when an interrupted or blocked controller checkpoint for the same run should continue. The foreground controller continues until project completion, a human decision gate, bounded retry exhaustion, or an execution blocker.

The Goal Supervisor does not author product artifacts, implement product code, choose the next WORK item, or manually swap models. Routing is owned by `core/routing/default.yaml` plus optional `.devflow/routing.yaml` overrides.

## Visibility

Use:

```bash
devflow autopilot status <domain>
devflow autopilot route <domain>
devflow autopilot capabilities
```

`autopilot capabilities` reports the detected Codex CLI version and per-model minimum-version compatibility. Report human decisions and execution blockers immediately. Otherwise keep the user-facing session focused on meaningful lifecycle transitions and the final result.
