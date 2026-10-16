---
name: plan
description: Convert an approved PRD into a repository-grounded DevFlow PLAN, phase WORK manifests, decisions, and STATE. Use when starting a new domain/feature or re-planning after an approved scope change. Always inspect the live repository and git baseline before writing implementation details.
---

# DevFlow Plan

Operate as the **Architect**.
Treat the PRD as the product/domain contract and derive implementation details only after inspecting the live repository.

## Runtime

Every `devflow` command below runs from the repository root.
Use this skill's wrapper. It resolves the plugin root from its own location, so it works under
both the Claude Code and the Codex adapter and the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

Under Claude Code only, the runtime path is equivalent when the variable is set:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

## Workflow

1. Run `devflow init <domain> --prd <path> --risk <level>` for a new domain, or `devflow delivery enable <domain>` for an existing active domain.
2. Run `devflow status <domain>`. Proceed only when the computed action is `plan`.
3. Run `devflow render plan <domain>` and execute its full Architect packet. The packet owns the PLAN/WORK procedure; `core/protocol/lifecycle.md`, `core/protocol/work-item-contract.md`, `core/protocol/decision-policy.md`, and `core/protocol/delivery-artifacts.md` own the rules.
4. Inspect the real repository and baseline; read the consuming project's `docs/PR/templates.md`. Build the PLAN, version 2 phase WORK, and unresolved decisions without inventing implementation facts.
5. Preserve actionable `context`, `premise_checks`, and `pitfalls` in each WORK. Keep the high-risk plan audit pending until the Auditor verifies it.
6. Run `devflow validate <domain>` and report actual errors and the computed next action.

## Boundaries

- Do not implement product code in this skill.
- Do not invent repository details from the PRD.
- Do not create handoff prompts, task documents, remediation plans, or integration-test plan documents.
- When authoritative sources conflict, record `SPEC_DRIFT` or a decision instead of choosing silently.

## Peer skill composition

Read `core/protocol/skill-composition.md` when peer skills are available.
DevFlow owns PLAN and WORK decomposition.
Apply a peer planning lens only when relevant, as defined by `core/protocol/skill-composition.md`.
When Ponytail is available, use its reuse-first planning lens without overriding the PRD, acceptance, security, or compatibility. Never change its mode automatically.

Do not start a separate Superpowers writing-plans, executing-plans, subagent-driven-development, or worktree lifecycle from inside DevFlow planning.

Finish with the domain, baseline SHA, phase count, work-item count, unresolved decisions, validation result, and the next DevFlow action.

## Whole-work final delivery

Plan for ELI5/Newman final acceptance; `core/protocol/finalization.md` owns the execution and evidence contract.
