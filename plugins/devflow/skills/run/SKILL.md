---
name: run
description: Execute exactly one ready DevFlow WORK item, verify it, and record structured evidence. Use for normal implementation, remediation, migration, tests, evidence collection, or documentation work after DevFlow PLAN/WORK artifacts exist.
---

# DevFlow Run

Operate as the **Executor**. Execute exactly one independently verifiable WORK item.

## Runtime

Every `devflow` command below runs from the repository root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

If that variable is unset, use this skill's wrapper instead. It resolves the plugin root from its
own location, so the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

## Workflow

1. Run `devflow status <domain>` and confirm the next action is `run`.
2. Run `devflow render run <domain>`, or pass `--task <ID>` when the user explicitly selected a
   ready item. The packet inlines the selected item, the authority rules, the WORK item contract,
   the risk policy, and the domain's `PITFALLS.md`.
3. Read the item's `context` and `pitfalls`, then read `PITFALLS.md`. These exist so you do not
   rediscover what the Architect already paid for.
4. **Work through `premise_checks` against current HEAD before editing anything.** Each entry names
   a fact to confirm. If one is false, the premise moved: stop, do not adapt the plan yourself.
5. Run `devflow work start <domain> <ID>`.
6. Establish the failing test or verification criterion first, where the change admits one.
7. Implement only the coherent change boundary defined by the WORK item, staying inside
   `scope.allowed`. Follow repository rules and existing patterns.
8. Execute the item's verification commands plus repository-required checks.
9. If a stop condition is reached, run `devflow work block <domain> <ID> --reason "..."` and stop.
   Record a decision when human or product authority is required.
10. When acceptance criteria are supported by evidence, run
    `devflow work done <domain> <ID> --commit <sha> --command '<cmd> -> <result>' ...`. It refuses a
    completion with no recorded command, because an unevidenced completion is the failure this
    protocol exists to prevent.
    A completed high/critical item then receives an initial work audit before a dependent can start.
11. If you discovered a trap that outlives this item, add it to `PITFALLS.md`.
12. Run `devflow validate <domain>` and `devflow status <domain>`.

## Boundaries

- One invocation handles one WORK item.
- Do not opportunistically fix unrelated findings.
- Do not expand allowed scope to make the implementation easier.
- Do not create a separate completion report; evidence belongs in the WORK item.

Finish with WORK ID, changed files, verification evidence, deviations/discoveries, status, and the
next DevFlow action.
