---
name: plan
description: Convert an approved PRD into a repository-grounded DevFlow PLAN, phase WORK manifests, decisions, and STATE. Use when starting a new domain/feature or re-planning after an approved scope change. Always inspect the live repository and git baseline before writing implementation details.
---

# DevFlow Plan

Operate as the **Architect**.
Treat the PRD as the product/domain contract and derive implementation details only after inspecting the live repository.

## Runtime

Every `devflow` command below runs from the repository root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

If that variable is unset, use this skill's wrapper instead.
It resolves the plugin root from its own location, so the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

## Workflow

1. Determine the domain name and PRD path. If the domain is not initialized, run `devflow init <domain> --prd <path> --risk <level> [--extension <name>]`.
   1. For an existing domain, run `devflow delivery enable <domain>` before continuing.
   2. It preserves completed WORK and adds requirements to future completion.
   3. Read `docs/PR/templates.md`; a missing template becomes an explicit prerequisite to resolve before implementation completion.
2. Confirm `devflow status <domain>` reports `plan`, then run `devflow render plan <domain>`.
   1. Render rejects any other lifecycle position.
   2. The packet inlines the authority rules, lifecycle, WORK item contract, decision policy, and the domain's `PITFALLS.md`.
   3. Follow it; there is no separate reference file to open.
3. Inspect repository rules (`AGENTS.md`, `CLAUDE.md`, CI/lint/test configuration), current git status, git history when relevant, and the actual implementation surfaces.
4. Write `docs/domains/<domain>/PLAN.md` using the plan template.
   1. Record the immutable baseline SHA.
   2. Include the branch/base mapping, code comment intent, affected HTTP contracts and per-branch PR/Postman delivery strategy from `core/protocol/delivery-artifacts.md`.
   3. Put those concrete obligations in each WORK's requirements and acceptance/verification mapping.
   4. Use the narrow output allowance for derived files; keep implementation scope intact.
5. Create one version 2 `work/phase-XX.yaml` per implementation phase.
   1. Keep all tasks in the standard WORK schema; do not create per-task Markdown files.
   2. Give each acceptance criterion and verification command a unique, nonblank item-local ID.
   3. Each command declares nonempty `covers`, and every acceptance ID must be covered.
6. **Carry your findings into each WORK item.**
   1. `context` for repository facts you verified, `premise_checks` for what the Executor must re-confirm at HEAD, `pitfalls` for the mistakes it is likely to make.
   2. `premise_checks` is mandatory for `high` and `critical` risk and `validate` rejects the item without it.
   3. An item that is only a title pushes the whole planning cost into execution, where there is less context to spend.
7. Populate STATE phase entries with zero-padded keys (`"01"`, not `"1"`) and explicit dependencies.
   1. Register a transferred requirement in the receiving phase and link it with `transfer.to`.
8. For audit-derived WORK, preserve each finding's expected event and outcome in objective and acceptance.
   1. Link audit disposition and `origin.findings` in both directions.
   2. Default to one finding per WORK; explain a shared root cause, change and rollback boundary, and verification set in `origin.aggregation_reason` when aggregation is necessary.
   3. Use version 2 and map each acceptance criterion to a command that observes the required outcome.
   4. Static source search alone does not verify API or end-to-end behavior.
9. Once a phase's branch exists, pin its range: `devflow phase ref <domain> <phase> --base <ref> --head <ref>`.
   1. It verifies ancestry and refuses rather than producing a stale 3-dot range.
10. Put product/policy questions in `DECISIONS.md` and add their IDs to `STATE.yaml.unresolved_decisions`.
    1. Do not create ready code-changing WORK before resolution.
11. Record durable domain traps you discovered in `PITFALLS.md`.
12. For high/critical risk, keep `plan_review.required: true` and `plan_review.status: pending`; otherwise mark it `skipped`.
    1. A high-risk plan initial audit verifies this gate before WORK begins.
13. Run `devflow validate <domain>`. Fix structural errors before reporting completion.

## Boundaries

- Do not implement product code in this skill.
- Do not invent repository details from the PRD.
- Do not create handoff prompts, task documents, remediation plans, or integration-test plan documents.
- When authoritative sources conflict, record `SPEC_DRIFT` or a decision instead of choosing silently.

## Peer skill composition

Follow `core/protocol/skill-composition.md`.
DevFlow owns PLAN and WORK decomposition.

When Ponytail guidance is available, use it as a planning lens:

- inspect existing implementation before proposing new components;
- reuse repository patterns and installed capabilities where suitable;
- keep each WORK item to the smallest independently verifiable change;
- avoid speculative abstractions and future-proofing the PRD or repository constraints do not require.

Ponytail does not override explicit PRD requirements, security, compatibility, or required verification, and its mode is never changed automatically.

Do not start a separate Superpowers writing-plans, executing-plans, subagent-driven-development, or worktree lifecycle from inside DevFlow planning.

Finish with the domain, baseline SHA, phase count, work-item count, unresolved decisions, validation result, and the next DevFlow action.

## Whole-work final delivery

Include the protocol 1.8 ELI5/Newman stage in final acceptance and task handoff, including the owned server lifecycle and readiness evidence.
Inspect actual installed ELI5 discovery, Newman availability, documented test startup, authentication, fixture cleanup and side-effect isolation.
Plan branch/build coverage and tracked collection regression fixtures where generated docs are ignored.
Use existing WORK for bounded code/test fixes; retain one whole-domain explanation and actual per-branch test evidence under `finalization.md`.
