# Goal 02 — High/Critical WORK Review Gate

**Recommended model:** GPT-5.6 Terra high

**Prerequisite:** Goal 01 is already applied and the full test suite passes.

**Goal:** Make the existing `risk-policy.md` rule executable: high/critical WORK must pass a work-level audit before dependent WORK can proceed.

## Scope

Primary runtime files:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/core/schemas/work.schema.yaml
plugins/devflow/core/templates/WORK.yaml
plugins/devflow/core/protocol/risk-policy.md
plugins/devflow/core/protocol/lifecycle.md
plugins/devflow/core/protocol/audit-core.md
plugins/devflow/core/prompts/audit.md
plugins/devflow/skills/audit/SKILL.md
plugins/devflow/tests/test_devflow.py
```

Inspect the current implementation of:

```text
deps_satisfied
choose_next
compute_next_action
find_item
work_update
render
build_parser
validate_item
```

## Existing invariant to implement

The current policy says:

```text
critical or high WORK: closure audit before any dependent WORK proceeds
work that later tasks depend on: verify before starting those dependents
```

The current runtime only requires a dependency status to be terminal, so `done` immediately releases dependents. Fix this mismatch.

## Required data contract

Add optional WORK review metadata:

```yaml
review:
  required: true
  status: pending
  audit_file: audits/work/P01-I01.md
  remediation_work_ids: []
```

Supported review statuses:

```text
skipped
pending
remediation
blocked
verified
```

Policy defaults:

```text
risk low/medium   -> required=false, status=skipped
risk high/critical -> required=true, status=pending
```

`review` must remain optional in the WORK schema so existing 0.2.0 files remain readable. Add the field description under `optional_item_fields` and add an explicit review-status contract to the schema if the schema format supports it cleanly.

Add `review` to `core/templates/WORK.yaml` as a low/medium example with `required: false`, `status: skipped`, and an audit file derived from the item ID in explanatory comments. Do not force every authored low-risk item to carry the field; runtime normalization is the compatibility mechanism.

## Runtime normalization helpers

Implement a single helper that computes effective review metadata without mutating the item during read-only commands.

Target behavior:

```python
def effective_review(item: dict[str, Any]) -> dict[str, Any]:
    ...
```

For an item without `review`:

```text
high/critical + status done/in_progress/ready -> required true; pending unless an explicit valid status exists
low/medium -> required false; skipped
```

Do not infer `verified` merely because a legacy high-risk item is `done`. Safety wins for existing completed high-risk WORK: it must be considered pending review until explicitly verified.

Add:

```python
def review_satisfied(item: dict[str, Any]) -> bool:
    review = effective_review(item)
    return not review["required"] or review["status"] == "verified"
```

Update dependency satisfaction so a dependent WORK is released only when:

```text
dependency has terminal implementation status
AND
required dependency review is satisfied
```

Preserve transferred/cancelled semantics. A transferred or cancelled item must not deadlock the graph merely because its risk field is high; review gating is for implemented `done` WORK. Encode this explicitly rather than relying on accidental defaults.

## Add work-level audit scope

Extend:

```bash
devflow render audit <domain> --scope work --task <WORK-ID> --mode initial
devflow render audit <domain> --scope work --task <WORK-ID> --mode closure
```

Update parser choices from:

```text
plan, phase, integration
```

to:

```text
plan, work, phase, integration
```

Add `--task` for audit rendering when scope is `work`.

The work audit context must identify:

```text
WORK id
full WORK YAML
risk
origin requirements/plan items
implementation evidence
commit if recorded
changed files
verification evidence
expected work audit file
current HEAD/target SHA
PITFALLS
standard audit/risk/decision protocols
```

Default audit file:

```text
audits/work/<WORK-ID>.md
```

Create the `audits/work` directory when needed; do not require it to exist at domain init time if lazy creation is simpler.

## Add explicit review transition command

Add a CLI command under `work`:

```bash
devflow work review <domain> <WORK-ID> verified
devflow work review <domain> <WORK-ID> remediation --remediation-work <ID> --remediation-work <ID>
devflow work review <domain> <WORK-ID> blocked
```

Rules:

### verified

Allowed only when:

```text
target WORK status == done
effective review.required == true
work audit artifact exists at effective review.audit_file
```

Persist:

```yaml
review:
  required: true
  status: verified
  audit_file: audits/work/<ID>.md
  remediation_work_ids: [...existing...]
```

### remediation

Allowed only when:

```text
target WORK status == done
at least one --remediation-work ID is supplied
each supplied ID exists in the WORK index
each supplied item has kind remediation or evidence
each supplied item carries an origin.findings/origin reference that can trace it back to the audit finding or target WORK where the current schema allows it
```

Do not invent a new large finding database in this goal. Use the current WORK origin structure and audit Markdown artifact.

### blocked

Persist status `blocked` in the review block. Keep the implementation WORK status as `done`; review block state is distinct from implementation completion.

## next_action semantics

Before choosing normal dependent work, detect completed high/critical WORK whose required review is unresolved.

Priority:

```text
1. in_progress executable WORK
2. required work review/remediation that blocks dependency progress
3. normal ready WORK
4. phase audit
5. integration audit
```

A completed high/critical item with `review.status=pending` yields:

```yaml
role: auditor
command: audit
scope: work
mode: initial
phase: <phase-or-null>
work_item: <ID>
```

A high/critical item with `review.status=remediation` behaves as follows:

```text
any listed remediation WORK executable -> run that remediation WORK
all listed remediation WORK terminal and their own required reviews satisfied -> work closure audit
```

Closure action:

```yaml
role: auditor
command: audit
scope: work
mode: closure
phase: <phase-or-null>
work_item: <original-ID>
```

A high/critical item with `review.status=blocked` yields a human/decision-style blocked action rather than releasing dependencies.

## Validation

Extend `validate_item()`/cross-item validation so malformed explicit review metadata is rejected:

```text
unknown review.status
required=true + status=skipped
remediation status with no remediation_work_ids
unknown remediation WORK id
verified explicit review on a non-done implementation item
```

Backward-compatible absence of `review` remains valid.

## Required tests

Add separate integration cases using existing helpers.

### A. high-risk dependency is gated

Build:

```text
A: high, done, valid evidence, premise_checks
B: ready, dependencies=[A]
```

Expected:

```text
status -> next.command audit
next.scope work
next.work_item A
B is not returned by `next`
```

### B. verified review releases dependent

Create `audits/work/A.md`, invoke the new review command with `verified`, then confirm `B` becomes the next run item.

### C. medium dependency preserves old behavior

`A medium done -> B ready` must immediately release B without work audit.

### D. remediation path

Build:

```text
A high done
R1 remediation ready
B depends on A
```

Set A review to remediation with R1.

Expected sequence:

```text
R1 run
R1 done
A work closure audit
A verified
B run
```

### E. legacy high-risk WORK without review

A legacy high-risk `done` item without a review field must be treated as pending review and must not release B.

## Verification

Run:

```bash
python3 tests/test_devflow.py
python3 -m py_compile scripts/devflow.py
```

## Acceptance criteria

```text
[ ] high/critical done WORK does not release dependents before verified review.
[ ] low/medium behavior remains unchanged.
[ ] work audit is a supported render scope.
[ ] explicit work review CLI transitions exist.
[ ] remediation returns to a closure work audit.
[ ] legacy high-risk done WORK is safely gated.
[ ] read-only status/render does not mutate legacy WORK just to normalize review state.
[ ] full test suite passes.
```

## Explicit exclusions

Do not add automatic orchestration, concurrent agents, file locks, external finding storage, or automatic execution of verification commands in this goal.

## Completion report

Return only:

```markdown
## Result
- Review data contract:
- Dependency behavior:
- New CLI surface:
- Tests:
- Compatibility behavior for legacy high-risk WORK:
```
