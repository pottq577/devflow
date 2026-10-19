# Authority and conflict rules

Use this precedence when sources disagree:

1. Explicit, resolved user decisions recorded for the current domain.
2. Approved PRD and product/domain specifications.
3. Repository-enforced rules such as `AGENTS.md`, `CLAUDE.md`, linters, schemas, and CI contracts.
4. Approved repository-grounded implementation PLAN.
5. WORK items generated from that PLAN or from confirmed AUDIT findings.
6. Completion evidence and historical reviews.

Treat PRD as the product/domain source of truth and PLAN as the repository implementation source of truth.

## Conflict handling

- Never silently choose between contradictory authoritative sources.
- Record specification-vs-code or specification-vs-plan conflicts as `SPEC_DRIFT` or `DECISION_REQUIRED`.
- Verify repository facts directly. Historical reports, completion notes, file paths, and `PITFALLS.md` are evidence or context, not authority. Correct stale pitfalls when discovered.

For immutable Git ranges and audit scope, follow `core/protocol/audit-core.md`. For requirement transfers, follow `core/protocol/work-item-contract.md`. The runtime's rendered context is defined by `core/protocol/lifecycle.md`. Derived PR/Postman and finalization outputs are governed by `core/protocol/delivery-artifacts.md` and `core/protocol/finalization.md`.
