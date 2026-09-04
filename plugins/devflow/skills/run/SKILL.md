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
2. Run `devflow render run <domain>`, or pass the exact reported WORK id with `--task <ID>`.
   Render rejects a different ready item. The packet inlines the selected item, the authority
   rules, the WORK item contract, the risk policy, and the domain's `PITFALLS.md`.
3. Read the item's `context` and `pitfalls`, then read `PITFALLS.md`. These exist so you do not
   rediscover what the Architect already paid for.
4. **Work through `premise_checks` against current HEAD before editing anything.** Each entry names
   a fact to confirm. If one is false, the premise moved: stop, do not adapt the plan yourself.
5. Run `devflow work start <domain> <ID>`.
6. Establish the failing test or verification criterion first, where the change admits one.
7. Implement only the coherent change boundary defined by the WORK item, staying inside
   `scope.allowed`. Follow repository rules and existing patterns.
8. Execute the item's verification commands plus repository-required checks. For version 2, confirm
   the executed set covers every acceptance ID. Verify API and end-to-end criteria at an observable
   contract layer; static source search alone is not runtime behavior evidence.
9. If a stop condition is reached, run `devflow work block <domain> <ID> --reason "..."` and stop.
   Record a decision when human or product authority is required.
10. When acceptance criteria are supported by evidence, run
    `devflow work done <domain> <ID> --commit <sha> --command '<cmd> -> <result>' ...`. It refuses a
    completion with no recorded command, because an unevidenced completion is the failure this
    protocol exists to prevent. Keep actual command results in `evidence.commands`; version 2
    `covers` metadata does not replace execution evidence.
    A completed high/critical item then receives an initial work audit before a dependent can start.
11. If you discovered a trap that outlives this item, add it to `PITFALLS.md`.
12. Run `devflow validate <domain>` and `devflow status <domain>`.

## Boundaries

- One invocation handles one WORK item.
- Do not opportunistically fix unrelated findings.
- Do not expand allowed scope to make the implementation easier.
- Do not create a separate completion report; evidence belongs in the WORK item.

## Peer execution disciplines

Follow `core/protocol/skill-composition.md`. The active WORK is the hard execution boundary.

### Behavior-changing WORK

When Superpowers test-driven-development is available, use it before production behavior changes:

1. establish the required behavior from the WORK contract;
2. add or identify a test that fails for the expected reason;
3. make the minimum production change;
4. verify the targeted test passes;
5. run the WORK verification DevFlow requires.

Explicit repository or user instructions already carry sufficient authority for a TDD exception.
Do not halt the run to ask again for permission that repository or user instructions already
grant. This does not weaken TDD in general.

### Defect and remediation WORK

When systematic-debugging is available:

1. reproduce or verify the defect;
2. identify evidence for the root cause;
3. avoid speculative fixes;
4. add regression coverage when behavior changes;
5. implement the minimum confirmed fix;
6. execute the WORK verification.

### Completion

Before reporting a WORK complete, use verification-before-completion when available. Fresh
verification evidence must support the same behavior the WORK verification criteria require.
Record the actual executed evidence through `devflow work done`. Never record peer-skill
invocation itself as proof that the WORK passed.

### Ponytail

Apply the currently active Ponytail policy when available. Prefer reuse and the smallest
implementation that satisfies the WORK. Ponytail must not widen or shrink required WORK scope,
remove acceptance criteria, weaken security or validation, skip required tests, bypass premise
checks, or bypass DevFlow lifecycle gates. Do not change Ponytail mode automatically.

### Lifecycle ownership

One invocation executes exactly one selected ready WORK item. Do not invoke peer controller
workflows that select multiple tasks, dispatch subagents, create worktrees, run a separate final
review, or finish branches.

Finish with WORK ID, changed files, verification evidence, deviations/discoveries, status, and the
next DevFlow action.
