# Risk and review policy

Risk controls review timing.

- `critical` or `high` WORK: closure audit before any dependent WORK proceeds.
- DB migration, state machine, concurrency, authorization, money, or external-contract changes: audit immediately after implementation when practical.
- Work that later tasks depend on: verify before starting those dependents.
- Independent `medium`/`low` items: batch into the phase audit.
- Documentation-only and nit-level findings: close in the phase audit unless they block traceability.

High-risk domains should run `audit --scope plan` before implementation. Examples include payments, payroll, authorization, security-sensitive flows, and destructive data migrations.

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
