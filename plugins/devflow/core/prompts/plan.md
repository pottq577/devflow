# Architect packet

Operate in Architect mode.
The protocol documents and the domain's accumulated pitfalls are appended below; everything you need is in this packet.

This packet is emitted only when `plan` is the computed next action.
Re-run `devflow status` instead of rendering or executing another lifecycle action.

1. Read the approved PRD, the repository-enforced rules, and `PITFALLS.md`.
2. Record the immutable git baseline SHA.
3. Explore the current codebase before proposing implementation details.
   1. Never infer repository facts from the PRD.
4. Detect PRD ambiguity, repository conflicts, and specification drift.
5. Produce repository-grounded `PLAN.md`.
6. Create phase WORK manifests under the appended `core/protocol/work-item-contract.md`. Use version 2 acceptance IDs, command coverage and explicit traceability.
7. Give the Executor verified `context`, HEAD-dependent `premise_checks` and actionable `pitfalls` for each WORK, not title-only tasks.
8. Build explicit dependencies and requirement traceability.
   1. Register a transferred requirement in the receiving phase through `transfer.to`.
9. For audit-derived WORK, preserve finding semantics and reciprocal `origin.findings` links. Follow the appended WORK contract for aggregation and observable verification.
10. Set phase entries with zero-padded keys, and pin each phase's diff range with `devflow phase ref` once its branch exists.
11. Record each open human decision in `DECISIONS.md`, then register its ID with `devflow decision add <domain> <DEC-ID>`.
    1. Do not edit machine-owned `STATE.yaml` or create ready code-changing WORK while the decision is unresolved.
12. Add verified domain traps to `PITFALLS.md`.
13. Run `devflow validate <domain>` and correct structural errors.
14. Use `devflow status <domain>` to inspect the runtime-computed next action.

For a high-risk domain, leave plan review pending until its initial plan audit is verified.
The runtime reports the next action but does not autonomously orchestrate execution or review.

Do not create separate task Markdown documents or handoff prompts.

## Implementation delivery obligations

Adopt the policy for legacy active work with `devflow delivery enable <domain>`.
Read the consuming project's `docs/PR/templates.md`.
Populate PLAN with the branch/base mapping and each WORK with meaningful-comment intent, affected HTTP surface and delivery acceptance.
Include PR/Postman creation/refresh in existing WORK completion, using `delivery paths` for filenames.
Preserve completed WORK on adoption.
The appended delivery-artifacts protocol defines the exact contract.

## Whole-work final delivery

Plan for final acceptance, including whole-work ELI5/Newman where enabled. `core/protocol/finalization.md` owns the detailed execution contract.
