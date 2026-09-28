---
name: goal
description: Start or resume a DevFlow autonomous delivery goal, optionally bounded at planning or implementation. Use when the user invokes /goal or asks DevFlow to carry approved requirements through routed lifecycle work without manually selecting each step.
---

# DevFlow Goal

Operate as the thin **Goal Supervisor**. DevFlow runtime owns lifecycle selection and model routing, including new-domain PRD bootstrap.

## Bootstrap

1. Resolve the repository root and domain slug from the request and existing DevFlow domains.
2. Separate explicit `/goal` execution controls from product requirements. `--until plan|implementation|complete` is supervisor control, not product intent.
3. For a new domain, persist the user's approved requirements **verbatim** to a runtime input file such as `.devflow/runtime/<domain>/goal-requirements.md`.
   - Do not summarize, reinterpret, decompose, or turn them into a PRD in the parent session.
   - Do not write execution-control options such as `--until` into the requirements file.
   - Preserve any requirement/acceptance IDs exactly as supplied.
4. Run the routed bootstrap from the repository root:

```bash
python3 <this-skill-directory>/scripts/invoke.py autopilot bootstrap <domain> \
  --requirements-file .devflow/runtime/<domain>/goal-requirements.md \
  --risk <low|medium|high|critical>
```

   - Use an explicit user-provided risk level when present; otherwise use `medium`.
   - Autopilot routes PRD creation to the Architect profile, validates the generated PRD, and initializes the domain only after the routed specialist succeeds.
   - Capability failures use the normal candidate fallback rules.
5. For an existing domain, preserve its current PRD/PLAN/WORK/STATE and skip bootstrap.

## Autonomous execution

For a newly initialized domain or an existing domain without an interrupted controller, run `autopilot start` with the user's explicit execution boundary. Omit `--until` for the default `complete` behavior.

```bash
python3 <this-skill-directory>/scripts/invoke.py autopilot start <domain> [--until plan|implementation|complete]
```

Boundary semantics are deterministic controller policy:

- `plan`: finish planning, including required plan audit, remediation, and closure, then stop before ordinary phase delivery.
- `implementation`: finish phase WORK and required work/phase review gates, then stop before integration or whole-delivery finalization.
- `complete`: preserve the existing full lifecycle through integration completion.

A boundary stop returns controller status `checkpoint` and is a successful requested outcome. Continue from a checkpoint with a fresh `autopilot start` and the next desired boundary. Use `autopilot resume` only when an interrupted or blocked controller run should continue with the same operational telemetry.

The Goal Supervisor does not author product artifacts, implement product code, choose the next WORK item, or manually swap models. Routing policy is owned by `core/routing/default.yaml` plus optional `.devflow/routing.yaml` overrides; concrete model bindings live in `core/routing/models.yaml` plus optional `.devflow/models.yaml` overrides.

## Visibility

Use:

```bash
devflow autopilot status <domain>
devflow autopilot route <domain>
devflow autopilot capabilities
```

`autopilot capabilities` reports the detected Codex CLI version and per-model minimum-version compatibility. Report human decisions and execution blockers immediately. Otherwise keep the user-facing session focused on meaningful lifecycle transitions and the final result.
