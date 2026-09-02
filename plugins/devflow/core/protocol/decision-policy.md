# Decision policy

Use `DECISIONS.md` for human/product decisions and `STATE.yaml.unresolved_decisions` for machine-readable blocking IDs.

Escalate when:

- two authoritative requirements conflict,
- implementation requires a product policy that the PRD leaves open,
- a migration or destructive behavior exceeds the approved scope,
- a security/authorization trade-off has no approved rule,
- the current code invalidates a PLAN premise and multiple valid redesigns exist.

Do not escalate ordinary implementation choices that repository conventions or the approved PLAN already determine.

When a decision is resolved:

1. record the chosen option and rationale in `DECISIONS.md`,
2. update PRD if the product contract changed,
3. remove the decision ID from `STATE.yaml.unresolved_decisions`,
4. re-plan affected WORK if required,
5. validate before resuming execution.
