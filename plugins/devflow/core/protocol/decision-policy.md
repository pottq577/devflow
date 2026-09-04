# Decision policy

Use `DECISIONS.md` for human/product decisions and `STATE.yaml.unresolved_decisions` for machine-readable blocking IDs.

Escalate when:

- two authoritative requirements conflict,
- implementation requires a product policy that the PRD leaves open,
- a migration or destructive behavior exceeds the approved scope,
- a security/authorization trade-off has no approved rule,
- the current code invalidates a PLAN premise and multiple valid redesigns exist.

Do not escalate ordinary implementation choices that repository conventions or the approved PLAN already determine.

The runtime exposes a computed next action, not autonomous orchestration. A human or agent still
chooses whether to execute that action and records any decision that needs product authority.

A `DECISION_REQUIRED` audit finding must use `disposition.action: decision`, list at least one ID in
`decision_ids`, and leave `work_ids` empty. Every listed ID must already exist with its options in
`DECISIONS.md`. Successful `devflow audit apply` atomically adds those IDs to
`STATE.yaml.unresolved_decisions`. Do not create ready code-changing WORK for the unresolved
finding. After resolution, create WORK for only the selected path and carry the decision ID in
`decision_dependencies`; unresolved dependencies cannot be `ready`.

When a decision is resolved:

1. record the chosen option and rationale in `DECISIONS.md`,
2. update PRD if the product contract changed,
3. remove the decision ID from `STATE.yaml.unresolved_decisions`,
4. re-plan affected WORK if required,
5. validate before resuming execution.
