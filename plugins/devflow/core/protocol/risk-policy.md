# Risk and review policy

Risk controls review timing.

- `critical` or `high` WORK: a work-level audit is required before any dependent WORK proceeds.
- High/critical WORK becomes review status `pending` when it is done. Its initial work audit can
  verify it, block it, or register remediation WORK. After all registered remediation is terminal
  and reviewed where required, a closure work audit decides whether the original WORK is verified.
- Phase and integration verification require every completed high/critical WORK in that scope to have
  a satisfied review. A review is never verified automatically by `work done`.
- `transferred` and `cancelled` WORK remain terminal routing outcomes and do not wait for review.
- DB migration, state machine, concurrency, authorization, money, or external-contract changes: audit immediately after implementation when practical.
- Work that later tasks depend on: verify before starting those dependents.
- Independent `medium`/`low` items: batch into the phase audit.
- Documentation-only and nit-level findings: close in the phase audit unless they block traceability.

High-risk domains should run `audit --scope plan` before implementation. Examples include payments, payroll, authorization, security-sensitive flows, and destructive data migrations.

The audit scopes are `plan`, `work`, `phase`, and `integration`. Initial and closure modes apply to
work, phase, and integration; a high-risk plan review is initial before WORK begins.

## Why the timing is graded rather than uniform

Reviewing after every single item costs more than it returns on independent low-risk work. Batching
an entire phase and reviewing once costs more when it goes wrong: later items build on a premise the
review would have invalidated, so a single early defect propagates through everything stacked on it.
Deferring review of a batch has already produced several late findings in practice, and they were
survivable only because none of them were blockers.

Grade by dependency and blast radius, not by uniform cadence. The question is never "how often do we
review", it is "does anything build on this before it is verified".

## Risk metadata drives contract depth

`high` and `critical` items must carry `premise_checks`, and `validate` rejects them otherwise. The
reasoning is the same: the more a later item depends on this one, the more expensive a wrong premise
becomes, so the premise gets checked explicitly instead of assumed.
