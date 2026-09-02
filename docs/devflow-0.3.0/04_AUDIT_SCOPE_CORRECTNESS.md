# Goal 04 — Audit Scope Correctness and Plan Audit Artifact

**Recommended model:** GPT-5.6 Terra medium

**Prerequisites:** Goals 01–03 are applied and tests pass.

**Goal:** Fix audit rendering so `plan`, `work`, `phase`, and `integration` are explicit independent scopes, and make plan review use its own `audits/plan.md` artifact instead of falling into integration metadata.

## Scope

Primary files:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/core/templates/STATE.yaml
plugins/devflow/core/schemas/state.schema.yaml
plugins/devflow/core/prompts/audit.md
plugins/devflow/skills/devflow-audit/SKILL.md
plugins/devflow/tests/test_devflow.py
```

Inspect the current `render()` implementation. The uploaded 0.2.0 code branches audit context by whether `args.phase` is present, so a plan audit with no phase falls through to integration audit metadata.

## Required STATE contract

Normalize `plan_review` to include:

```yaml
plan_review:
  required: false
  status: skipped
  audit_file: audits/plan.md
```

Update:

```text
core/templates/STATE.yaml
init_domain()
state schema documentation/optional structure where appropriate
legacy runtime defaulting
```

Existing STATE without `audit_file` must resolve to `audits/plan.md` without requiring migration.

## Required render implementation

Rewrite audit-context branching explicitly by `args.scope`:

```python
if args.scope == "plan":
    ...
elif args.scope == "work":
    ...
elif args.scope == "phase":
    ...
elif args.scope == "integration":
    ...
else:
    raise ...
```

Do not use `args.phase is not None` as the primary scope discriminator.

### plan scope

Print at least:

```text
audit_scope: plan
audit_mode
baseline_sha
target_sha/current HEAD
PLAN path
PRD path
audit_file: <domain>/audits/plan.md
```

Do not print `audits/integration.md` as the plan audit file.

### work scope

Preserve Goal 02 behavior. Require `--task`. Resolve the exact item and its effective audit file.

### phase scope

Require `--phase`. Resolve normalized phase key and print:

```text
phase
base_sha
head_sha
diff_range
work_file
audit_file
```

If phase is missing/unknown, return a clear non-zero error rather than silently using defaults for an unrelated phase.

### integration scope

Print:

```text
baseline/target range
integration work file
integration audit file
```

## CLI validation

Enforce argument combinations at runtime/parser level:

```text
scope=work requires --task and rejects missing task
scope=phase requires --phase and rejects missing phase
scope=plan does not require phase/task
scope=integration does not require phase/task
```

You may keep harmless extra args rejected for clarity if parser structure makes this simple.

## Required tests

### Plan artifact isolation

```python
out = devflow(
    root,
    "render",
    "audit",
    "billing",
    "--scope",
    "plan",
).stdout

check(
    "plan audit uses plan audit artifact",
    "audits/plan.md" in out and "audits/integration.md" not in out,
    out,
)
```

### Scope argument requirements

Test:

```text
work without --task -> non-zero
phase without --phase -> non-zero
phase with known phase -> correct work/audit files
integration -> integration audit file
```

### Plan review guard integration

With Goal 03 applied:

```text
render plan audit points to audits/plan.md
create that file
plan-review set verified succeeds
```

## Verification

Run:

```bash
python3 tests/test_devflow.py
```

## Acceptance criteria

```text
[ ] plan audit never falls through to integration metadata.
[ ] work/phase/integration scopes remain correct.
[ ] plan_review.audit_file defaults to audits/plan.md for legacy and new STATE.
[ ] scope-specific required arguments are enforced.
[ ] full test suite passes.
```

## Explicit exclusions

Do not implement Markdown section extraction or broad context inlining in this goal; Goal 05 owns context assembly. Do not add an autonomous orchestrator, controller loop, automatic subagent dispatch, parallel execution, or file locking.

## Completion report

Return only:

```markdown
## Result
- Scope branching:
- Plan audit artifact:
- CLI argument validation:
- Tests:
```
