# Goal 01 — Schema SSOT and Atomic YAML I/O

**Recommended model:** GPT-5.6 Terra medium

**Goal:** Remove duplicated schema enums/required-field lists from `devflow.py`, make bundled YAML schemas the runtime source of truth for structural validation constants, and make YAML writes atomic without changing lifecycle behavior.

## Scope

Work only in the DevFlow plugin under `plugins/devflow/`.

Primary files:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/core/schemas/state.schema.yaml
plugins/devflow/core/schemas/work.schema.yaml
plugins/devflow/tests/test_devflow.py
```

Read these before editing:

```text
plugins/devflow/core/schemas/finding.schema.yaml
plugins/devflow/core/templates/STATE.yaml
plugins/devflow/core/templates/WORK.yaml
```

## Baseline verification

From `plugins/devflow` run:

```bash
python3 tests/test_devflow.py
```

Record any pre-existing failure before modifying code. Do not continue with an unexplained failing baseline.

## Required implementation

### 1. Add schema loading helpers

`devflow.py` currently hardcodes values such as:

```python
WORK_STATUSES = {...}
PHASE_STATUSES = {...}
PROJECT_STATUSES = {...}
INTEGRATION_STATUSES = {...}
KINDS = {...}
RISK_LEVELS = {...}
```

and separately hardcodes required fields in `validate_state()` and `validate_item()`.

Add a helper that loads bundled schema files from `core/schemas/` through `plugin_root()`.

Target interface:

```python
def load_schema(name: str) -> dict[str, Any]:
    path = plugin_root() / "core" / "schemas" / f"{name}.schema.yaml"
    data = load_yaml(path, {}) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid DevFlow schema: {path}")
    return data
```

Initialize schema-backed constants after `plugin_root`, `load_yaml`, and schema loading are available. If module initialization order makes direct top-level initialization awkward, use a small cached/lazy helper. Keep the code simple.

The runtime must derive at least these from schemas:

```text
STATE required fields
PROJECT_STATUSES
PHASE_STATUSES
INTEGRATION_STATUSES
WORK required_item_fields
WORK_STATUSES
TERMINAL_STATUSES
KINDS
RISK_LEVELS
```

`HIGH_RISK = {"high", "critical"}` may remain a semantic policy constant because the schema only defines allowed risk values, not review policy.

### 2. Make `validate_state()` use `state.schema.yaml.required`

The current runtime omits `baseline_sha` from its hardcoded required list even though `state.schema.yaml` requires it.

After this change, deleting any field listed in `state.schema.yaml.required` must produce a validation error without maintaining a second Python list.

### 3. Make `validate_item()` use `work.schema.yaml.required_item_fields`

Remove the duplicated Python list of required WORK fields. Preserve semantic checks such as:

```text
acceptance non-empty
verification.commands non-empty
dependency resolution
high/critical premise_checks
done evidence
transfer integrity
```

These checks remain Python logic because they are cross-field/domain invariants.

### 4. Add atomic text/YAML write helper

Replace direct YAML overwrite paths in `dump_yaml()` and `dump_yaml_if_changed()` with same-directory temporary file + `os.replace()`.

Required properties:

```text
- parent directory is created first
- temp file is created in the same directory as the target
- content is fully written and closed before replace
- os.replace(temp, target) performs the final swap
- a leftover temp file is removed on failure when possible
- dump_yaml_if_changed still avoids writes when rendered content is unchanged
```

Use the standard library only (`tempfile`, `os`). Do not introduce a file-locking system in this goal.

Suggested helper shape:

```python
def atomic_write_text(path: Path, content: str) -> None:
    ...
```

### 5. Preserve current behavior

This goal must not change:

```text
choose_next ordering
compute_next_action lifecycle semantics
WORK review semantics
phase/integration transition rules
render behavior
CLI command surface
protocol version
plugin version
```

Those are handled by later goals.

## Tests to add

Add a case proving runtime required-field validation comes from the state schema. Use the existing throwaway repo helpers.

Required scenario:

```python
def case_state_schema_required_fields_are_enforced(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"

    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    doc.pop("baseline_sha")
    dump(d / "STATE.yaml", doc)

    out = devflow(root, "validate", "billing")
    check(
        "STATE schema required fields are enforced by runtime validator",
        out.returncode != 0 and "baseline_sha" in out.stdout,
        out.stdout + out.stderr,
    )
```

Also add a WORK required-field regression test that removes one field listed in `work.schema.yaml.required_item_fields`, for example `acceptance`, and confirms `validate` fails with that field name.

The existing `case_status_is_side_effect_free` must continue passing after atomic-write changes.

## Verification

Run:

```bash
python3 tests/test_devflow.py
```

Then run:

```bash
python3 -m py_compile scripts/devflow.py
```

## Acceptance criteria

The goal is complete only when all are true:

```text
[ ] `baseline_sha` removal is caught by runtime validation.
[ ] WORK required fields are read from work.schema.yaml.
[ ] Allowed lifecycle/status/kind/risk sets are schema-backed rather than separately duplicated.
[ ] Cross-field semantic validation remains in Python.
[ ] dump_yaml and dump_yaml_if_changed use atomic replacement.
[ ] Read-only/status behavior remains side-effect free.
[ ] No new third-party dependency is added.
[ ] Full existing + new test suite passes.
```

## Explicit exclusions

Do not add WORK review metadata, audit scope `work`, transition guards, derived project status, context extraction, orchestrator behavior, parallelism, or locks in this goal.

## Completion report

Return only:

```markdown
## Result
- Files changed:
- Tests added:
- Full test result:
- Any compatibility note:
```
