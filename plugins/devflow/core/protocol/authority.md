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

## Captured-source requirement traceability

When the domain has `sources/v1/manifest.json`, keep its original and supplemental files immutable. The approved PRD is the current product contract; captured source text is immutable historical evidence. Supplemental analysis never approves product behavior on its own.

For that domain, append `## 11. Source traceability` to the PRD. Each `### REQ-*`, `### RULE-*`, `### SEC-*`, `### NFR-*`, or `### IDEM-*` heading declares one product requirement. Use distinct `AC-*` IDs for each acceptance criterion under its parent heading. Keep existing IDs; assign new IDs from stable source anchors rather than document order. A split source span may map to multiple IDs in one row. A moved requirement retains its ID.

The source table columns are `Source | Lines | Disposition | Requirements | Reason`. Source is `original:v1` or `context:v1`. Lines are inclusive `Lx-Ly` ranges in that snapshot. Every nonblank line in both snapshots needs exactly one coverage row; overlaps and gaps fail validation. Dispositions are `mapped` (approved requirement), `reference` (supplemental analysis linked to a requirement), `background`, `pending`, and `excluded`. `mapped` and `reference` need PRD IDs. Context-only mapped requirements and excluded source text require a resolved `DEC-*` ID in Reason. `reference` never authorizes a product policy. The resolved decision must exist in `DECISIONS.md` at full validation; see `decision-policy.md` for approval authority.

The PLAN `## Requirement traceability` table has columns `Requirement | Plan item | Phase | Work items | Disposition | Reason`. List every PRD requirement once. Use comma-separated WORK IDs for many-to-many mappings. Dispositions are `implement`, `transferred`, `excluded`, `deferred`, and `cancelled`. The last three require a resolved `DEC-*` in Reason. A transferred row names the original WORK and its receiver. Each listed WORK uses `origin.requirements` to reference its PRD IDs and `origin.acceptance_criteria` for PRD acceptance IDs. Local WORK `acceptance` IDs remain separate verification targets.

`devflow validate` checks the declared links, source ranges, missing and duplicated requirement IDs, scope disposition, transfer edges, and acceptance coverage. It does not infer semantics or proof of implementation from a declared mapping. Plan and audit agents must review whether every `background`/`pending` span is classified correctly. Legacy domains without captured sources keep their existing validation behavior.
Legacy captured domains created before this traceability contract may omit the table until migrated. Validation warns without blocking. New Goal-bootstrapped captures record `STATE.traceability_version: 1`, which requires the table and source evidence to remain available. Removing either fails validation.
