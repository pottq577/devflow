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
   1. If captured sources exist, fill the PLAN table using `Requirement | Plan item | Phase | Work items | Disposition | Reason`. Register each PRD requirement once and link every related WORK through `origin.requirements`.
   2. Map PRD acceptance IDs via `origin.acceptance_criteria`, which is distinct from WORK-local `acceptance` IDs. Record both sender and receiver for transferred WORK and an approved decision for excluded/deferred scope.
   3. Register a transferred requirement in the receiving phase through `transfer.to`.
   4. Preserve captured-original source ranges for the Executor's eventual `origin.original_comparison`. Never predeclare alignment without inspecting implemented code; follow the appended WORK contract.
9. For audit-derived WORK, preserve finding semantics and reciprocal `origin.findings` links. Follow the appended WORK contract for aggregation and observable verification.
10. Create each `work/phase-XX.yaml` manifest, then register the phase with `devflow phase set <domain> <phase> planned`. The CLI requires a matching manifest or an existing STATE phase entry; pin its diff range with `devflow phase ref` after the branch exists.
11. Record each open human decision in `DECISIONS.md`, then register its ID with `devflow decision add <domain> <DEC-ID>`.
    1. Before validation, record each existing product approval cited by PRD source mappings or PLAN exclusions under `## Resolved`, with the actual approving authority and evidence. Bootstrap references alone are not approval. Without that evidence, keep the choice open and correct the mapping; never fabricate a resolved decision.
    2. Do not edit machine-owned `STATE.yaml` or create ready code-changing WORK while the decision is unresolved.
    3. Use `core/protocol/decision-policy.md` for separately scoped technical decisions and reversible provisional policies. Link WORK with `origin.technical_decisions` or `origin.policy_assumptions`; never treat provisional assumptions as resolved product policy.
12. Add verified domain traps to `PITFALLS.md`.
13. Run `devflow validate <domain>` and correct structural errors.
14. Use `devflow status <domain>` to inspect the runtime-computed next action.

For a high-risk domain, leave plan review pending until its initial plan audit is verified.

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
