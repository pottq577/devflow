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
- Record specification-vs-code or specification-vs-plan conflict as `SPEC_DRIFT` or `DECISION_REQUIRED`.
- Verify repository facts directly. Historical reports, completion notes, and file paths are evidence candidates, not authority.
- Record `baseline_sha`, `target_sha`, and `diff_range` for audits. Prefer immutable commit SHAs over branch names.
- When work moves between phases, register the same requirement in the receiving phase and link the transfer explicitly.
