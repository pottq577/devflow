# Decision policy

Use `DECISIONS.md` for human/product decisions and `STATE.yaml.unresolved_decisions` for machine-readable blocking IDs.

Escalate when:

- two authoritative requirements conflict,
- implementation requires a product policy that the PRD leaves open,
- a migration or destructive behavior exceeds the approved scope,
- a security/authorization trade-off has no approved rule,
- the current code invalidates a PLAN premise and multiple valid redesigns exist.

Do not escalate ordinary implementation choices that repository conventions or the approved PLAN already determine.

The runtime exposes a computed next action, not autonomous orchestration.
A human or agent still chooses whether to execute that action and records any decision that needs product authority.

A `DECISION_REQUIRED` audit finding must use `disposition.action: decision`, list at least one ID in `decision_ids`, and leave `work_ids` empty.
An initial, current-only, or `still_open` finding requires every listed ID to exist as an open record with options in `DECISIONS.md`.
Successful initial `devflow audit apply` atomically adds those IDs to `STATE.yaml.unresolved_decisions`.
A closure outcome of `resolved`, `reopened`, or `accepted_risk` instead requires the prior finding's linked IDs to be resolved and absent from `STATE.yaml.unresolved_decisions`; `accepted_risk` requires at least one such decision.
Do not create ready code-changing WORK for an unresolved finding.
After resolution, create WORK for only the selected path and carry the decision ID in `decision_dependencies`; unresolved dependencies cannot be `ready`.

An open decision record is a `### DEC-*` heading under `## Open` with at least two nonblank `- Option ...:` fields.
The record ends at the next Markdown ATX heading, including a heading with up to three leading spaces.
Four leading spaces form a code block, not a heading boundary.
Bracketed template values, `TBD`, and `TODO` do not count as values.
`validate` requires the open decision IDs and `STATE.yaml.unresolved_decisions` to match in both directions.
WORK start uses the open records as blockers even when STATE is inconsistent.
A record under `## Resolved` requires a nonblank `- Decision:` field.

When a decision is resolved:

1. Move the record to `## Resolved` in `DECISIONS.md`, including the chosen option and rationale.
2. Update the PRD if the approved product contract changed.
3. Run `devflow decision resolve <domain> <DEC-ID>` to update machine-owned STATE. Never edit `STATE.yaml.unresolved_decisions` directly.
4. Re-plan affected WORK if required.
5. Run `devflow validate <domain>` before resuming execution.

## Developer decisions and provisional policy

Technical implementation choices use `devflow decision technical`; the record belongs under
`## Technical decisions` in the same `DECISIONS.md`. Link affected WORK with
`origin.technical_decisions`. A technical record may explain a deviation in the implementation,
but cannot amend the product contract or resolve a product decision.

A reversible, low/medium-risk policy interpretation may use `devflow decision assume`.
The record lives under `## Policy assumptions`, with the original behavior, assumed behavior,
domain basis, alternatives, possible contract impact, rollback, affected requirement IDs,
and the intended product confirmation owner. Link affected WORK using
`origin.policy_assumptions`, not `decision_dependencies`. The required
`--safe-to-prototype` flag is a developer attestation, not product approval.

Do not use provisional policy for security, authorization, payment or billing, destructive
migration, irreversible data changes, legal/compliance obligations, or high/critical risk.
If contract impact is confirmed, a specification conflicts with another authoritative
specification, or audit has emitted `DECISION_REQUIRED`, preserve the existing blocking
`## Open` / `STATE.unresolved_decisions` contract. A provisional record cannot override it.
The CLI's risk/category checks cannot independently establish product safety; the architect
and auditor must verify actual impact.

Product confirmation uses `devflow decision approve` or `devflow decision reject` with an
identified approving authority and concrete evidence. Approval never follows automatically
from a passing test or developer agreement. If approved policy differs from the assumption,
register `--corrective-work` and verify every linked WORK. Rejection always requires
corrective WORK. After rejecting, `devflow decision reconcile` requires every correction
WORK to be done with its mandatory review verified, plus a reconciliation evidence reference.
Update the PRD to the approved policy, re-plan where needed, and retain the original source
snapshot and decision history. The CLI verifies references and declared evidence, not the
semantic correctness of the product owner's statement.

Unconfirmed or rejected policies, and outstanding corrective WORK, allow independent
implementation/phase work but block the integration audit, integration verification,
and the project's `complete` result. `devflow decision list <domain>` returns all technical
and provisional policy records. Legacy domains without these records remain compatible.
