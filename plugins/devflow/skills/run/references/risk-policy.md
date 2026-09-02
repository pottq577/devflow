# Risk and review policy

Risk controls review timing.

- `critical` or `high` WORK: closure audit before any dependent WORK proceeds.
- DB migration, state machine, concurrency, authorization, money, or external-contract changes: audit immediately after implementation when practical.
- Work that later tasks depend on: verify before starting those dependents.
- Independent `medium`/`low` items: batch into the phase audit.
- Documentation-only and nit-level findings: close in the phase audit unless they block traceability.

High-risk domains should run `audit --scope plan` before implementation. Examples include payments, payroll, authorization, security-sensitive flows, and destructive data migrations.
