# DevFlow Closure and Recovery Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make persisted closure audits self-consistent, make legacy recovery commands executable, and accept resolved decisions during closure.

**Architecture:** Extend the existing machine-owned `audit_provenance` record with one optional validation-basis mapping. Keep every transition in the current runtime functions and transaction path, then synchronize the protocol and release metadata without adding dependencies or lifecycle artifacts.

**Tech Stack:** Python 3.10+, PyYAML, Markdown protocol documents, YAML schemas, JSON plugin manifests

**Spec:** `docs/superpowers/specs/2026-09-09-closure-recovery-hardening-design.md`

## Global Constraints

- Work only on `main`; do not create a branch or worktree.
- Keep Claude Code and Codex on the shared implementation in `plugins/devflow/`.
- Write and run each regression test before its implementation change.
- Preserve atomic STATE and WORK mutation and protocol 1.0 through 1.4 readability.
- Add no dependency, autonomous controller, background worker, or lifecycle artifact.
- Release plugin `0.6.1` with protocol `1.5.0`.

---

### Task 1: Preserve the validation basis of an applied closure

**Files:**

- Modify: `plugins/devflow/tests/test_devflow.py`
- Modify: `plugins/devflow/scripts/devflow.py`
- Modify: `plugins/devflow/core/schemas/state.schema.yaml`
- Modify: `plugins/devflow/core/schemas/work.schema.yaml`
- Modify: `plugins/devflow/core/protocol/audit-core.md`
- Modify: `plugins/devflow/core/protocol/lifecycle.md`

**Interfaces:**

- Consumes: `recorded_audit_provenance(root, domain, state, scope, phase, work_item)`
- Produces: optional keyword `for_applied_audit: bool = False` and optional `audit_provenance.applied_against`

- [ ] **Step 1: Add the failing post-apply validation assertion**

In `case_audit_remediation_full_lifecycle_with_reopened_finding`, immediately after
`applied_first_closure`, reload STATE and run validation:

```python
    validated_first_closure = devflow(root, "validate", "billing")
    persisted_provenance = yaml.safe_load(
        (d / "STATE.yaml").read_text(encoding="utf-8")
    )["integration"]["audit_provenance"]
```

Add these conditions to the first `check`:

```python
        and validated_first_closure.returncode == 0
        and persisted_provenance["applied_against"] == {"F-01": "blocker"}
        and persisted_provenance["findings"] == {"F-01": "blocker", "F-02": "blocker"}
```

Include `validated_first_closure.stdout + validated_first_closure.stderr` in the failure detail.

- [ ] **Step 2: Run the suite and verify the new assertion fails**

Run:

```bash
python3 plugins/devflow/tests/test_devflow.py
```

Expected: nonzero exit with `full reopen lifecycle returns to traced integration remediation`
failing because `validate` reports closure coverage errors and `applied_against` is absent.

- [ ] **Step 3: Preserve both provenance mappings**

Add a keyword to `recorded_audit_provenance`:

```python
    for_applied_audit: bool = False,
```

Select the stored mapping with legacy fallback:

```python
    key = "applied_against" if for_applied_audit and isinstance(record.get("applied_against"), dict) else "findings"
    findings = record.get(key)
```

Pass `for_applied_audit=True` only from `audit_artifact_contract_errors`. Leave audit application
and render calls on the default so they continue to read the next-closure basis.

Before overwriting provenance in `audit_apply`, preserve the current basis for closure mode:

```python
    provenance = {"findings": audit_provenance_findings(metadata)}
    if args.mode == "closure":
        applied_against = recorded_audit_provenance(
            root, args.domain, state, args.scope, args.phase, args.task, work_docs=work_docs
        )
        if applied_against is not None:
            provenance["applied_against"] = applied_against
```

Load `work_docs` from the domain before this block. Reuse it for integration and phase verification
where possible rather than adding another helper.

- [ ] **Step 4: Validate both mappings structurally**

Extract the existing finding-map checks inside `audit_provenance_errors` into a nested loop over
`findings` and optional `applied_against`. Keep the current error prefixes and add equivalent
`audit_provenance.applied_against` errors for a non-mapping, blank ID, or invalid severity.

Describe `applied_against` in both schemas and in the provenance sections of `audit-core.md` and
`lifecycle.md`. State that old records with only `findings` remain readable.

- [ ] **Step 5: Run verification and commit**

Run:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
git diff --check
```

Expected: compilation succeeds and the suite ends with zero failures.

Commit:

```bash
git add plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py plugins/devflow/core/schemas/state.schema.yaml plugins/devflow/core/schemas/work.schema.yaml plugins/devflow/core/protocol/audit-core.md plugins/devflow/core/protocol/lifecycle.md
git commit -m "fix(devflow): preserve closure validation provenance"
```

### Task 2: Make legacy closure recovery commands executable

**Files:**

- Modify: `plugins/devflow/tests/test_devflow.py`
- Modify: `plugins/devflow/scripts/devflow.py`
- Modify: `plugins/devflow/core/protocol/lifecycle.md`
- Modify: `plugins/devflow/core/schemas/state.schema.yaml`
- Modify: `plugins/devflow/core/schemas/work.schema.yaml`

**Interfaces:**

- Consumes: `work review <domain> <ID> pending`, `plan-review set <domain> pending`
- Produces: guarded remediation-to-pending legacy recovery and an empty remediation set

- [ ] **Step 1: Extend the legacy recovery case with failing command execution**

After the work-scope refusal in `case_legacy_closure_without_provenance`, execute the printed command
and assert the next action is an initial work audit:

```python
    work_recovered = devflow(root, "work", "review", "shipping", "P01-I01", "pending")
    work_recovery_status = devflow(root, "status", "shipping", "--json")
    recovered_action = json.loads(work_recovery_status.stdout)["next_action"]
```

Assert `work_recovered.returncode == 0`, `recovered_action["scope"] == "work"`, and
`recovered_action["mode"] == "initial"`.

Rewrite the canonical work audit as initial, apply it, rewrite it as closure, apply it, and run
`validate shipping`. Assert every command exits `0` and the reviewed WORK ends with
`review.status: verified`.

Add a plan fixture whose required review has `status: remediation`, one completed remediation ID,
and no provenance. Apply its legacy closure to get the recovery refusal, run
`plan-review set planning pending`, then assert `remediation_work_ids` is empty and `status --json`
selects a plan initial audit.

Rewrite the canonical plan audit as initial, apply it, rewrite it as closure, apply it, and run
`validate planning`. Assert every command exits `0` and the plan review ends with
`plan_review.status: verified`.

- [ ] **Step 2: Run the suite and verify both recovery assertions fail**

Run:

```bash
python3 plugins/devflow/tests/test_devflow.py
```

Expected: the legacy recovery case fails because work recovery exits `2` and plan recovery returns
to closure.

- [ ] **Step 3: Implement the guarded recovery transitions**

In `review_work`, replace the blocked-only predicate with:

```python
        legacy_mid_closure = review["status"] == "remediation" and "audit_provenance" not in review
        if review["status"] != "blocked" and not legacy_mid_closure:
            print(f"{args.item}: review pending requires a blocked review or legacy remediation without provenance, not {review['status']}", file=sys.stderr)
            return 2
```

Continue clearing `remediation_work_ids`. In `set_plan_review`, when `args.status == "pending"`, set
`pr["remediation_work_ids"] = []` before committing.

Add one assertion that a remediation review with valid provenance is still rejected and remains
byte-identical.

- [ ] **Step 4: Synchronize the migration contract and verify**

Update lifecycle and schema compatibility text to describe the executable plan and work recovery
semantics.

Run:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
git diff --check
```

Expected: zero failures.

Commit:

```bash
git add plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py plugins/devflow/core/protocol/lifecycle.md plugins/devflow/core/schemas/state.schema.yaml plugins/devflow/core/schemas/work.schema.yaml
git commit -m "fix(devflow): make closure recovery commands executable"
```

### Task 3: Accept resolved decisions during closure

**Files:**

- Modify: `plugins/devflow/tests/test_devflow.py`
- Modify: `plugins/devflow/scripts/devflow.py`
- Modify: `plugins/devflow/core/protocol/audit-core.md`
- Modify: `plugins/devflow/core/protocol/decision-policy.md`

**Interfaces:**

- Consumes: closure entries, Open and Resolved `DECISIONS.md` records, `STATE.unresolved_decisions`
- Produces: outcome-aware decision linkage validation

- [ ] **Step 1: Add a failing accepted-risk lifecycle case**

Create `case_accepted_risk_closure_requires_resolved_decision` beside the existing decision lifecycle.
Initialize audit-remediation, write an Open `DEC-001`, apply a major `DECISION_REQUIRED` finding,
move the record under `## Resolved`, and run `decision resolve`. Write this closure:

```python
    closure = [{
        "finding_id": "F-01",
        "outcome": "accepted_risk",
        "evidence": ["the approved decision records the accepted residual risk"],
        "reopened_as": [],
    }]
```

Apply it and assert exit `0`, integration status `verified`, next command `complete`, and a final
`validate` exit `0`. Register the case in `CASES`.

- [ ] **Step 2: Run the suite and verify the linkage check fails**

Run:

```bash
python3 plugins/devflow/tests/test_devflow.py
```

Expected: nonzero exit containing `must be an open DECISIONS.md record`.

- [ ] **Step 3: Make decision validation closure-aware**

For each finding, obtain `closure_outcome = closure_by_id.get(str(finding["id"]), {}).get("outcome")`.
Use Resolved records when the mode is closure and the prior finding outcome is `resolved`,
`reopened`, or `accepted_risk`. Also require that the ID is absent from
`STATE.unresolved_decisions`. Continue requiring Open records for initial, `still_open`, and
current-only findings.

Keep the dedicated `accepted_risk requires a resolved decision` check. Update `audit-core.md` and
`decision-policy.md` with the same distinction.

- [ ] **Step 4: Run verification and commit**

Run:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
git diff --check
```

Expected: zero failures.

Commit:

```bash
git add plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py plugins/devflow/core/protocol/audit-core.md plugins/devflow/core/protocol/decision-policy.md
git commit -m "fix(devflow): validate resolved closure decisions"
```

### Task 4: Synchronize release metadata and verification

**Files:**

- Modify: `plugins/devflow/tests/test_devflow.py`
- Modify: `plugins/devflow/scripts/devflow.py`
- Modify: `plugins/devflow/core/templates/STATE.yaml`
- Modify: `plugins/devflow/README.md`
- Modify: `plugins/devflow/CHANGELOG.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `plugins/devflow/.claude-plugin/plugin.json`
- Modify: `plugins/devflow/.codex-plugin/plugin.json`

**Interfaces:**

- Consumes: current plugin `0.6.0`, protocol `1.4.0`, timeout diagnostic `0.5`
- Produces: plugin `0.6.1`, protocol `1.5.0`, timeout diagnostic `2.0`

- [ ] **Step 1: Update exact version expectations and timeout budget**

Set `PROTOCOL_VERSION = "1.5.0"`, update the STATE template, generated-version assertions, status
version assertions, downgrade diagnostics, and current-runtime wording in tests. Keep explicit
legacy fixture versions unchanged.

Change the timeout case to `timeout=2.0` and expect `"2.0 seconds"`; keep the child sleep at five
seconds. Change the marketplace version assertion to `"0.6.1"`.

- [ ] **Step 2: Synchronize manifests and current documentation**

Set plugin version `0.6.1` in both entries of `.claude-plugin/marketplace.json` and both plugin
manifests. Do not add a version to `.agents/plugins/marketplace.json`.

Update root README, plugin README, and AGENTS to plugin `0.6.1` and protocol `1.5.0`. Add a
CHANGELOG `0.6.1` section covering all three fixes, the provenance compatibility rationale, and the
protocol minor decision. Retain historical release entries unchanged.

- [ ] **Step 3: Run required release verification twice**

Run:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
python3 -m json.tool .agents/plugins/marketplace.json >/dev/null
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
python3 -m json.tool plugins/devflow/.codex-plugin/plugin.json >/dev/null
python3 -m json.tool plugins/devflow/.claude-plugin/plugin.json >/dev/null
test "$(git ls-files -s plugins/devflow/bin/devflow | awk '{print $1}')" = "100755"
git diff --check
git branch --show-current
git status --short
```

Expected: compilation and JSON parsing succeed, both suites report zero failures, the executable
mode is `100755`, and the branch is `main`.

- [ ] **Step 4: Commit and inspect the release archive**

Commit:

```bash
git add AGENTS.md README.md .claude-plugin/marketplace.json plugins/devflow
git commit -m "release(devflow): publish 0.6.1 with protocol 1.5.0"
```

Create `/tmp/devflow-marketplace-0.6.1.zip` from committed HEAD with `git archive`. Inspect its
listing for both adapters and the shared plugin. Reject entries containing `.git`, `__pycache__`,
`.pyc`, `.superpowers`, or another ZIP. Then run `git diff --check`, `git status --short`, and
`git branch --show-current` once more.
