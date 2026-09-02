---
name: plan
description: Convert an approved PRD into a repository-grounded DevFlow PLAN, phase WORK manifests, decisions, and STATE. Use when starting a new domain/feature or re-planning after an approved scope change. Always inspect the live repository and git baseline before writing implementation details.
---

# DevFlow Plan

Operate as the **Architect**. Treat the PRD as the product/domain contract and derive implementation
details only after inspecting the live repository.

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

1. Determine the domain name and PRD path. If the domain is not initialized, run
   `devflow init <domain> --prd <path> --risk <level> [--extension <name>]`.
2. Run `devflow render plan <domain>`. The packet inlines the authority rules, lifecycle, WORK item
   contract, decision policy, and the domain's `PITFALLS.md`. Follow it; there is no separate
   reference file to open.
3. Inspect repository rules (`AGENTS.md`, `CLAUDE.md`, CI/lint/test configuration), current git
   status, git history when relevant, and the actual implementation surfaces.
4. Write `docs/domains/<domain>/PLAN.md` using the plan template. Record the immutable baseline SHA.
5. Create one `work/phase-XX.yaml` per implementation phase. Keep all tasks in the standard WORK
   schema; do not create per-task Markdown files.
6. **Carry your findings into each WORK item.** `context` for repository facts you verified,
   `premise_checks` for what the Executor must re-confirm at HEAD, `pitfalls` for the mistakes it is
   likely to make. `premise_checks` is mandatory for `high` and `critical` risk and `validate`
   rejects the item without it. An item that is only a title pushes the whole planning cost into
   execution, where there is less context to spend.
7. Populate STATE phase entries with zero-padded keys (`"01"`, not `"1"`) and explicit dependencies.
   Register a transferred requirement in the receiving phase and link it with `transfer.to`.
8. Once a phase's branch exists, pin its range:
   `devflow phase ref <domain> <phase> --base <ref> --head <ref>`. It verifies ancestry and refuses
   rather than producing a stale 3-dot range.
9. Put product/policy questions in `DECISIONS.md` and add their IDs to
   `STATE.yaml.unresolved_decisions`.
10. Record durable domain traps you discovered in `PITFALLS.md`.
11. For high/critical risk, keep `plan_review.required: true` and `plan_review.status: pending`;
    otherwise mark it `skipped`. A high-risk plan initial audit verifies this gate before WORK begins.
12. Run `devflow validate <domain>`. Fix structural errors before reporting completion.

## Boundaries

- Do not implement product code in this skill.
- Do not invent repository details from the PRD.
- Do not create handoff prompts, task documents, remediation plans, or integration-test plan
  documents.
- When authoritative sources conflict, record `SPEC_DRIFT` or a decision instead of choosing
  silently.

Finish with the domain, baseline SHA, phase count, work-item count, unresolved decisions, validation
result, and the next DevFlow action.
