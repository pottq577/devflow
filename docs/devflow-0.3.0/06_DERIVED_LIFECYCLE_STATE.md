# Goal 06 — Derived Lifecycle State

**Recommended model:** GPT-5.6 Terra high

**Prerequisites:** Goals 01–05 are applied and tests pass.

**Goal:** Make `target_sha`, `next_action`, `project_status`, and `active_phase` deterministic projections of current STATE + WORK instead of allowing these fields to drift from the actual lifecycle.

## Scope

Primary files:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/core/schemas/state.schema.yaml
plugins/devflow/core/templates/STATE.yaml
plugins/devflow/core/protocol/lifecycle.md
plugins/devflow/tests/test_devflow.py
```

Inspect:

```text
choose_next
compute_next_action
refresh_state
action_inputs
print_status
phase_entry
set_phase
set_integration
```

## Core rule

`refresh_state()` is the only place that updates derived lifecycle fields during normal read/status flow.

Derived fields:

```text
target_sha
next_action
project_status
active_phase
```

Mutation commands may update authoritative state such as WORK status, phase status, integration status, plan review status, decisions, audit review status, and refs. After mutation they call `refresh_state()`, which derives the projection fields.

Remove direct/manual writes to `active_phase` from mutation handlers such as `set_phase()` when they conflict with this model.

## Derive `project_status`

Create a pure helper:

```python
def project_status_for_action(state: dict[str, Any], action: dict[str, Any]) -> str:
    ...
```

Use the existing `state.schema.yaml project_status.allowed` values.

Required mapping:

```text
action command=plan                         -> planning
action scope=plan, command=audit           -> plan_review
action command=run, phase scope            -> phase_execution
action scope=work, command=audit initial    -> phase_audit or remediation according to review state
action scope=work, command=audit closure    -> remediation
action scope=phase, command=audit initial   -> phase_audit
action scope=phase, command=audit closure   -> remediation
action command=run on remediation item      -> remediation
action command=run, integration scope       -> integration_remediation when item kind is remediation/evidence, otherwise integration_audit if current lifecycle legitimately has integration execution work
action scope=integration, audit initial     -> integration_audit
action scope=integration, audit closure     -> integration_closure
action command=decision/human blocked       -> blocked
action command=complete                     -> complete
```

The uploaded schema currently allows:

```text
planning
plan_review
phase_execution
phase_audit
remediation
integration_audit
integration_remediation
integration_closure
complete
blocked
```

Do not add statuses unless an existing lifecycle state cannot be represented. Prefer mapping to these values.

## Derive `active_phase`

Create a helper based on `next_action` and current work/review state.

Rules:

```text
phase run/audit/work-audit action -> normalized phase key
integration/project action -> null
human action with a specific phase -> that phase
```

For work-level audit, find the WORK item's manifest phase through `find_item`/`item_phase`.

If no action-specific phase exists but exactly one phase is actively `executing`, `audit`, `remediation`, or `blocked`, it may be used as fallback. Avoid ambiguous guesses when multiple phases are open; `next_action` should already identify deterministic execution order.

## Reconcile `compute_next_action`

Review the state-machine ordering after Goals 02/03. Ensure it never returns the generic fallback:

```text
scope=project audit
```

for a normal valid lifecycle state that should instead be plan/work/phase/integration audit or human decision.

If such fallback remains for invalid/incomplete state, label it clearly or return a human/block-style action rather than silently inventing an unsupported project audit scope. The audit parser supports plan/work/phase/integration, not generic project audit.

This is important: `status` must never recommend a command that `render audit` cannot execute.

## Read-only stability

`status` and `render` may rewrite STATE only when a derived value actually changed. Goal 01's `dump_yaml_if_changed()` behavior must be preserved.

Running `devflow status` twice with no repository/state/work changes must leave STATE bytes unchanged on the second run.

## Required lifecycle tests

Extend/create one end-to-end lifecycle walk using valid guarded transitions from Goal 03.

At minimum assert these states at the appropriate points:

```text
planning
phase_execution
phase_audit or remediation during high-risk work review
phase_audit after phase work is complete
integration_audit after all phases verify
integration_closure after integration remediation when applicable
complete after integration verifies
blocked when unresolved decision prevents progress
```

Add assertions for `active_phase`:

```text
phase execution -> "01"
phase audit -> "01"
integration audit -> null
complete -> null
```

Add a test proving every computed audit action has a supported scope in:

```text
plan
work
phase
integration
```

Add a read-only stability test around repeated `status` calls if the existing side-effect-free case does not already fully cover derived fields.

## Verification

Run:

```bash
python3 tests/test_devflow.py
```

## Acceptance criteria

```text
[ ] project_status always matches computed next_action/lifecycle.
[ ] active_phase matches the active phase or is null for project/integration scope.
[ ] mutation handlers no longer create conflicting derived state.
[ ] status never recommends unsupported generic audit scope.
[ ] repeated status with no changes is stable.
[ ] full test suite passes.
```

## Explicit exclusions

Do not implement an autonomous loop that executes `next_action`. This goal only makes the projection deterministic so a future orchestrator can safely consume it.

## Completion report

Return only:

```markdown
## Result
- Derived fields:
- next_action changes:
- Lifecycle tests:
- Read-only stability:
```
