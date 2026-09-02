# Goal 09 — DevFlow 0.3.0 Final Acceptance Audit

**Recommended model:** GPT-5.6 Luna xhigh or GPT-5.6 Terra high

**Prerequisites:** Goals 01–08 are complete.

**Goal:** Independently verify the finished DevFlow 0.3.0 implementation against the required runtime behavior. Prefer finding defects over making speculative refactors. Apply only fixes that are necessary to satisfy the acceptance contract, then rerun the full suite.

## First action: inspect, do not edit

Read:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/tests/test_devflow.py
plugins/devflow/core/schemas/state.schema.yaml
plugins/devflow/core/schemas/work.schema.yaml
plugins/devflow/core/templates/STATE.yaml
plugins/devflow/core/templates/WORK.yaml
plugins/devflow/core/protocol/lifecycle.md
plugins/devflow/core/protocol/risk-policy.md
plugins/devflow/core/protocol/work-item-contract.md
plugins/devflow/core/protocol/audit-core.md
plugins/devflow/skills/plan/SKILL.md
plugins/devflow/skills/run/SKILL.md
plugins/devflow/skills/audit/SKILL.md
plugins/devflow/skills/status/SKILL.md
plugins/devflow/README.md
plugins/devflow/CHANGELOG.md
plugins/devflow/.codex-plugin/plugin.json
```

Run before any edit:

```bash
cd plugins/devflow
python3 tests/test_devflow.py
```

If tests fail, identify the violated contract before changing code.

## Audit checklist

### A. Manual workflow remains primary

Confirm there is no newly required autonomous controller. The user can still manually drive:

```text
plan -> run -> audit -> run -> audit
```

There must be no required `devflow-drive`, daemon, background service, or auto-dispatch loop.

### B. Schema/runtime consistency

Confirm:

```text
state required fields come from state.schema.yaml
work required fields come from work.schema.yaml
allowed state/work/kind/risk values are not independently duplicated in ways that can drift
semantic cross-field validation remains explicit in Python
```

Delete `baseline_sha` in a throwaway domain and verify `devflow validate` fails.

### C. Atomic writes

Inspect YAML write helpers and confirm same-directory temporary file + atomic replace. Confirm `status` repeated twice does not rewrite unchanged STATE.

### D. High-risk dependency gate

In a throwaway repo create:

```text
A high, done, valid evidence/premise_checks
B ready depends on A
```

Confirm:

```text
status asks for work audit of A
B cannot start
```

Create the work audit artifact, mark A review verified, confirm B becomes executable.

### E. Remediation closure

Create:

```text
A high done
R1 remediation
A review remediation -> R1
B depends on A
```

Confirm:

```text
R1 executes
A closure audit follows
B remains gated until A review verified
```

### F. Transition guards

Confirm rejected with no mutation:

```text
ready -> done
start with unresolved dependency
start with unresolved decision
start in verified phase
skip required plan review
phase verified with open work
phase verified without diff range
audit artifact missing on phase verification
integration verified while phase unverified
integration verified without integration audit artifact
```

### G. Audit scopes

Run render commands for:

```text
plan
work
phase
integration
```

Confirm plan uses `audits/plan.md`; integration uses `audits/integration.md`; work uses `audits/work/<ID>.md`; phase uses configured phase artifact.

### H. Context assembly

Use unique markers in PRD/PLAN. Confirm run render includes referenced marker sections and excludes unrelated markers. Confirm no fuzzy substitution for a missing ID.

Confirm integration rendering supplies broad PLAN/manifest/path context without dumping every phase artifact by default.

### I. Derived state

Walk a valid lifecycle and inspect:

```text
next_action
project_status
active_phase
```

Confirm they remain mutually consistent and all computed audit actions use supported scopes only.

### J. Documentation/version

Confirm:

```text
plugin version 0.3.0
protocol version consistent in runtime/templates/config docs
CHANGELOG explains protocol version decision
README command syntax matches parser
skills/protocols include work audit scope and high-risk gate
orchestrator remains a future/non-goal feature
```

## Fix policy

If the audit finds a defect:

1. Add or strengthen a failing integration test that reproduces it.
2. Make the smallest runtime/documentation fix that satisfies the contract.
3. Run the focused test.
4. Run the entire suite.

Do not perform style refactors, file splitting, dependency changes, or new features during final audit unless required to fix a demonstrated acceptance failure.

## Final verification

Run twice:

```bash
python3 tests/test_devflow.py
python3 tests/test_devflow.py
```

Also run:

```bash
python3 -m py_compile scripts/devflow.py
```

## Completion criteria

```text
[ ] all checklist items A–J verified
[ ] any discovered defect has a regression test
[ ] two consecutive full-suite runs pass
[ ] py_compile passes
[ ] no autonomous orchestrator was added
[ ] no known acceptance failure remains
```

## Final report

Return only:

```markdown
## Final acceptance
- Verdict: PASS | FAIL
- Full tests run 1:
- Full tests run 2:
- py_compile:

## Defects found and fixed
- <none> or concise list with regression-test names

## Contract verification
- Schema/runtime: PASS|FAIL
- Atomic writes: PASS|FAIL
- High-risk gate: PASS|FAIL
- Transition guards: PASS|FAIL
- Audit scopes: PASS|FAIL
- Context assembler: PASS|FAIL
- Derived state: PASS|FAIL
- Documentation/version: PASS|FAIL

## Remaining blockers
- <none> or exact blocker only
```
