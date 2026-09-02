---
name: run
description: Execute exactly one ready DevFlow WORK item, verify it, and record structured evidence. Use for normal implementation, remediation, migration, tests, evidence collection, or documentation work after DevFlow PLAN/WORK artifacts exist.
---

# DevFlow Run

Operate as the **Executor**. Execute exactly one independently verifiable WORK item.

## Workflow

1. Read `references/authority.md`, `references/work-item-contract.md`, and `references/risk-policy.md`.
2. Run `python3 scripts/invoke.py status <domain>` and confirm the next action is `run`.
3. Run `python3 scripts/invoke.py render run <domain>` or pass `--task <ID>` when the user explicitly selected a ready item.
4. Re-verify the task premise against current code before editing.
5. Run `python3 scripts/invoke.py work start <domain> <ID>`.
6. Implement only the coherent change boundary defined by the WORK item. Follow repository rules and existing patterns.
7. Execute the item's verification commands plus repository-required checks.
8. If a stop condition is reached, run `python3 scripts/invoke.py work block <domain> <ID> --reason "..."` and stop. Record a decision when human/product authority is required.
9. When acceptance criteria are supported by evidence, run `python3 scripts/invoke.py work done ...` with commit/changed files/commands where practical, or update the evidence fields directly and mark the item done.
10. Run `python3 scripts/invoke.py validate <domain>` and `python3 scripts/invoke.py status <domain>`.

## Boundaries

- One invocation handles one WORK item.
- Do not opportunistically fix unrelated findings.
- Do not expand allowed scope to make the implementation easier.
- Do not create a separate completion report; evidence belongs in the WORK item.

Finish with WORK ID, changed files, verification evidence, deviations/discoveries, status, and the next DevFlow action.
