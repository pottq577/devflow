---
name: plan
description: Convert an approved PRD into a repository-grounded DevFlow PLAN, phase WORK manifests, decisions, and STATE. Use when starting a new domain/feature or re-planning after an approved scope change. Always inspect the live repository and git baseline before writing implementation details.
---

# DevFlow Plan

Operate as the **Architect**. Treat the PRD as the product/domain contract and derive implementation details only after inspecting the live repository.

## Workflow

1. Determine the domain name and PRD path. If the domain has not been initialized, run `python3 scripts/invoke.py init <domain> --prd <path> --risk <level>` from this skill directory.
2. Read `references/authority.md`, `references/work-item-contract.md`, and `references/lifecycle.md`.
3. Run `python3 scripts/invoke.py render plan <domain>` and follow the emitted Architect packet.
4. Inspect repository rules (`AGENTS.md`, `CLAUDE.md`, CI/lint/test configuration), current git status, git history when relevant, and the actual implementation surfaces.
5. Write `docs/domains/<domain>/PLAN.md` using the plan template. Record the immutable baseline SHA.
6. Create one `work/phase-XX.yaml` per implementation phase. Keep all tasks in the standard WORK schema; do not create per-task Markdown files.
7. Populate STATE phase entries and explicit dependencies. Register transferred requirements in both sending and receiving phases.
8. Put product/policy questions in `DECISIONS.md` and add their IDs to `STATE.yaml.unresolved_decisions`.
9. For high/critical risk, keep `plan_review.required: true` and `plan_review.status: pending`; otherwise mark it `skipped`.
10. Run `python3 scripts/invoke.py validate <domain>`. Fix structural errors before reporting completion.

## Boundaries

- Do not implement product code in this skill.
- Do not invent repository details from the PRD.
- Do not create handoff prompts, task documents, remediation plans, or integration-test plan documents.
- When authoritative sources conflict, record `SPEC_DRIFT`/a decision instead of choosing silently.

Finish with the domain, baseline SHA, phase count, work-item count, unresolved decisions, validation result, and the next DevFlow action.
