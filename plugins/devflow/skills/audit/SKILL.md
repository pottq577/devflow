---
name: audit
description: Independently audit a DevFlow plan, phase, or whole integration using repository evidence, then classify findings and generate remediation/evidence WORK directly. Use for plan review, phase review, closure review, and cross-phase integration review in a fresh reviewer session.
---

# DevFlow Audit

Operate as the **Auditor** in an independent review context. Verify repository facts directly.

## Workflow

1. Read `references/authority.md`, `references/audit-core.md`, and `references/risk-policy.md`.
2. Determine `scope=plan|phase|integration` and `mode=initial|closure`. Use a fresh high-reasoning session whenever practical.
3. Run `python3 scripts/invoke.py render audit <domain> --scope <scope> [--phase XX] --mode <mode>`.
4. Pin baseline SHA, target SHA, and diff range. Inspect current code, git history/diff, tests, repository rules, PRD, PLAN, and relevant WORK manifests.
5. Apply the common audit axes. For integration scope, also inspect cross-phase contracts, transfers, end-to-end state/data flows, transaction boundaries, migration ordering, and regression/evidence gaps.
6. Write or update the single audit artifact under `audits/`; do not create separate review-plan or handoff documents.
7. Classify findings as `CONFIRMED`, `DECISION_REQUIRED`, `EVIDENCE_REQUIRED`, `REJECTED`, `DOCUMENTATION_DRIFT`, or `SPEC_DRIFT`.
8. Create remediation WORK directly for confirmed/documentation findings and evidence WORK for evidence-required findings. Build dependencies before severity ordering.
9. Add unresolved decision IDs to STATE and document them in `DECISIONS.md`. Never guess the policy.
10. Update phase/integration state (`phase set`, `plan-review set`, `integration set`), run validation, then run status.

## Closure mode

Verify that the prior finding is actually closed, acceptance still holds, and no new regression was introduced. Reopen or create a finding when evidence disproves closure.

Finish with verdict, SHAs/diff range, finding counts by classification/severity, generated WORK IDs, unresolved decisions, residual risk, and next action.
