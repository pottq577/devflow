# Goal 03 — Runtime Transition Guards

**Recommended model:** GPT-5.6 Terra high

**Prerequisites:** Goals 01 and 02 are applied and `python3 tests/test_devflow.py` passes.

**Goal:** Make invalid WORK, plan-review, phase, and integration state transitions fail at the CLI boundary instead of trusting callers to mutate lifecycle state correctly.

## Scope

Primary files:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/tests/test_devflow.py
plugins/devflow/core/protocol/lifecycle.md
plugins/devflow/core/protocol/work-item-contract.md
plugins/devflow/core/protocol/risk-policy.md
```

Inspect current implementations of:

```text
work_update
set_phase
set_plan_review
set_integration
deps_satisfied
decision_satisfied
effective_review/review_satisfied from Goal 02
load_work_index
normalized_phases
```

## Design rule

Centralize guards in small helper functions. Do not duplicate the same dependency/review checks inside multiple command handlers.

Use clear failure messages and return exit code `2` for rejected mutation commands, consistent with existing CLI error behavior.

A rejected transition must not modify STATE or WORK files.

## WORK start guard

`devflow work start <domain> <ID>` is allowed only when all are true:

```text
item.status == ready
all dependencies exist and are satisfied
all required upstream WORK reviews are verified
all decision_dependencies are resolved
containing phase is not verified
project plan-review gate is either not required or verified
```

For integration WORK, phase verification rules do not apply, but integration WORK must not start before all project phases required by the current lifecycle are verified.

Use existing `item_phase()` and normalized phase state to determine scope.

Required error messages must identify the cause, for example:

```text
P01-I02 cannot start: dependency P01-I01 requires review before dependent WORK may proceed
P01-I02 cannot start: unresolved decision DEC-004
P01-I02 cannot start: phase 01 is already verified
P01-I02 cannot start: required plan review is pending
```

Exact punctuation may differ; tests should assert stable identifying substrings.

## WORK done guard

`devflow work done` is allowed only from `in_progress`.

Reject direct:

```text
ready -> done
blocked -> done
transferred -> done
cancelled -> done
```

Preserve the existing evidence rule:

```text
non-documentation done requires at least one evidence.commands entry after merging CLI evidence
```

A rejected no-evidence transition must leave the original item unchanged. The current implementation writes the document even on the evidence error path; remove that side effect.

After successful completion of a high/critical implementation WORK, its effective review state must be pending unless it was already explicitly in a valid later review state. Do not mark review verified automatically.

## WORK block guard

`devflow work block` is allowed only from:

```text
ready
in_progress
```

Reject attempts to block `done`, `transferred`, or `cancelled` WORK.

Require a non-empty reason after trimming whitespace.

## Plan review transition guard

Current command:

```bash
devflow plan-review set <domain> <status>
```

Keep this command surface.

For `verified`:

```text
plan_review.required may be true or false
plan_review.audit_file must resolve to an existing file
PLAN.md must exist
```

Goal 04 will guarantee the plan audit file is rendered correctly. If the `audit_file` field is absent on legacy STATE, default it to `audits/plan.md` for the guard.

`skipped` is allowed only when plan review is not required. Reject skipping a required high-risk plan review.

## Phase transition guard

Keep:

```bash
devflow phase set <domain> <phase> <status>
```

Focus strict guarding on terminal/verification claims.

`phase ... verified` is allowed only when:

```text
phase exists
all items in phase work_file are terminal
all `done` high/critical items have review_satisfied == true
phase.diff_range is present
phase.audit_file exists
no phase WORK is blocked
no unresolved decision referenced by phase WORK remains
```

If the phase has zero WORK items, reject `verified` unless the repository already uses an explicit documentation-only empty phase convention. Inspect existing protocol/tests before deciding; do not silently verify an accidental empty phase.

Allow non-terminal status changes (`planned`, `executing`, `audit`, `remediation`, `blocked`) only when they do not contradict an already verified phase. A verified phase cannot be reopened through plain `phase set`; reopening requires a future explicit feature and is outside this goal.

## Integration transition guard

`integration ... verified` is allowed only when:

```text
all phases exist and are verified
integration.audit_file exists
all integration WORK items are terminal
all done high/critical integration WORK reviews are satisfied
no integration WORK is blocked
no unresolved project decision remains
```

Reject `verified` if there are zero phases unless current documented lifecycle explicitly supports a no-phase project. Preserve documented behavior if such a case exists.

A verified integration cannot be reopened through plain `integration set` in this goal.

## Shared guard helpers

Prefer helpers with explicit results/messages, for example:

```python
def dependency_blockers(item, index) -> list[str]:
    ...

def work_start_errors(root, domain, state, path, doc, item, index) -> list[str]:
    ...

def phase_verify_errors(root, domain, state, phase_key, docs, index) -> list[str]:
    ...

def integration_verify_errors(root, domain, state, docs, index) -> list[str]:
    ...
```

The exact names can differ. Keep them deterministic and side-effect free.

## Required tests

Add separate cases for each invariant.

1. `ready -> done` is rejected and YAML remains `ready`.
2. `blocked -> done` is rejected.
3. WORK with unfinished dependency cannot start.
4. WORK whose dependency is high-risk done/review-pending cannot start.
5. WORK with unresolved decision dependency cannot start.
6. WORK in verified phase cannot start.
7. Required pending plan review prevents WORK start.
8. Required plan review cannot be `skipped`.
9. Plan review cannot become verified without `audits/plan.md`.
10. Phase cannot become verified with open WORK.
11. Phase cannot become verified with high-risk review pending.
12. Phase cannot become verified without `diff_range`.
13. Phase cannot become verified without audit artifact.
14. Integration cannot become verified while any phase is unverified.
15. Integration cannot become verified without its audit artifact.
16. Rejected transition produces no file mutation beyond normal read-only refresh semantics.

Update existing lifecycle tests so they create the required audit artifacts and diff ranges before setting verified states. Do not weaken the new guards just to preserve old shortcut tests.

## Verification

Run:

```bash
python3 tests/test_devflow.py
python3 -m py_compile scripts/devflow.py
```

## Acceptance criteria

```text
[ ] invalid transitions fail before writing files.
[ ] WORK start checks dependency, review, decision, phase, and plan-review gates.
[ ] WORK done requires in_progress and verification evidence.
[ ] phase verified is an evidence-backed claim.
[ ] integration verified is an evidence-backed claim.
[ ] old lifecycle tests are updated to perform valid state transitions.
[ ] full test suite passes.
```

## Explicit exclusions

Do not add a generic event-sourcing engine, state-machine package, automatic test-command execution, orchestrator, or admin `--force` escape hatch in this goal.

## Completion report

Return only:

```markdown
## Result
- WORK guards:
- Phase guards:
- Integration guards:
- Plan-review guards:
- Tests:
```
