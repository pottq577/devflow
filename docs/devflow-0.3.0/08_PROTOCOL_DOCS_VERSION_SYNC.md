# Goal 08 — Protocol, Skill, Template, README, and Version Sync

**Recommended model:** GPT-5.6 Terra medium or GPT-5.6 Luna xhigh

**Prerequisites:** Goals 01–07 are applied and runtime/tests pass.

**Goal:** Synchronize every user/agent-facing contract with the implemented runtime, update version metadata, and leave no documentation that describes the pre-0.3.0 lifecycle.

## Scope

Read the final runtime and tests first. Then update only documentation/templates/schema metadata that must reflect implemented behavior.

Files to inspect and update as required:

```text
plugins/devflow/core/protocol/lifecycle.md
plugins/devflow/core/protocol/risk-policy.md
plugins/devflow/core/protocol/work-item-contract.md
plugins/devflow/core/protocol/audit-core.md
plugins/devflow/core/protocol/decision-policy.md
plugins/devflow/core/protocol/authority.md

plugins/devflow/core/prompts/plan.md
plugins/devflow/core/prompts/run.md
plugins/devflow/core/prompts/audit.md

plugins/devflow/core/templates/STATE.yaml
plugins/devflow/core/templates/WORK.yaml
plugins/devflow/core/templates/AUDIT.md

plugins/devflow/core/schemas/state.schema.yaml
plugins/devflow/core/schemas/work.schema.yaml
plugins/devflow/core/schemas/finding.schema.yaml

plugins/devflow/skills/devflow-plan/SKILL.md
plugins/devflow/skills/devflow-run/SKILL.md
plugins/devflow/skills/devflow-audit/SKILL.md
plugins/devflow/skills/devflow-status/SKILL.md

plugins/devflow/README.md
plugins/devflow/CHANGELOG.md
plugins/devflow/.codex-plugin/plugin.json
```

Do not mechanically edit every file. Make only consistency-required changes.

## Required documented lifecycle

Documentation must accurately show:

```text
PRD
→ plan
→ optional required plan audit for high-risk domain
→ run WORK
→ high/critical WORK initial audit before dependents
→ remediation WORK when finding confirmed
→ high/critical WORK closure audit
→ dependent WORK release
→ phase initial audit
→ phase remediation
→ phase closure audit
→ next phase
→ integration initial audit
→ integration remediation
→ integration closure audit
→ integration verified
→ project complete
```

Low/medium independent WORK remains batch-reviewed at phase audit.

## Required audit scopes

All relevant docs/skills must agree on:

```text
plan
work
phase
integration
```

The audit skill must explain:

```text
work initial audit
work closure audit
phase initial audit
phase closure audit
integration initial audit
integration closure audit
```

## Required command examples

README should show a realistic manual flow. Include commands matching the actual parser after Goals 02–04, for example:

```bash
devflow status billing
devflow render run billing --task P01-I01
devflow work start billing P01-I01
devflow work done billing P01-I01 --command "<real verification> -> pass"
devflow render audit billing --scope work --task P01-I01 --mode initial
devflow work review billing P01-I01 verified
devflow render audit billing --scope phase --phase 01 --mode initial
```

Use the exact CLI syntax implemented in code. Inspect `build_parser()` before writing examples.

## Context assembler documentation

Document that:

```text
plan render includes full PRD
run render includes selected WORK + exact origin-linked PRD/PLAN context
phase/work audit render includes scope-linked context
integration render provides broad summaries/paths to avoid context explosion
```

Do not promise semantic search, automatic repository RAG, or autonomous orchestration.

## Backward compatibility documentation

Document 0.2.0 artifact behavior:

```text
existing WORK without review remains readable
legacy high/critical done WORK without review is treated as requiring review before dependents
existing plan_review without audit_file defaults to audits/plan.md
no mandatory migration command is required if runtime normalization handles the artifact
```

Adjust these statements to the actual final implementation; never document behavior the runtime does not provide.

## Versioning

Update plugin manifest version:

```json
"version": "0.3.0"
```

Evaluate `PROTOCOL_VERSION` based on the final artifact contract.

The uploaded runtime currently uses:

```python
PROTOCOL_VERSION = "1.1.0"
```

The new optional WORK review metadata and plan-review audit-file default are backward-readable changes, but high-risk dependency semantics are behaviorally stronger. Decide whether protocol version stays `1.1.0` or increments based on how this repository defines protocol compatibility.

Requirements:

```text
- plugin version must become 0.3.0
- protocol version decision must be explicit in CHANGELOG
- do not automatically make protocol version equal plugin version
- templates/config/runtime constant must agree on the selected protocol version
```

## CHANGELOG

Add a 0.3.0 entry covering:

```text
schema-backed validation constants
atomic YAML writes
high/critical WORK review gate
work audit scope
runtime transition guards
plan audit artifact/scope fix
context assembler
computed lifecycle state
test subprocess timeouts
backward compatibility behavior
explicit orchestrator non-goal
```

## Skills consistency

Each skill should describe only its responsibility:

```text
devflow-plan   -> repository-grounded planning and WORK generation
devflow-run    -> exactly one selected executable WORK item + evidence
devflow-audit  -> independent plan/work/phase/integration verification
devflow-status -> deterministic next-action/status inspection
```

Keep skills concise. Move detailed policy to existing protocol files rather than duplicating long rules in every SKILL.md.

## Verification

Run:

```bash
python3 tests/test_devflow.py
```

Then search for stale statements:

```bash
grep -R "plan, phase, or integration\|plan.*phase.*integration\|three.*scope" -n core skills README.md || true
grep -R "0\.2\.0" -n . --exclude-dir=.git || true
```

Review every hit manually; historical CHANGELOG references to 0.2.0 are valid.

## Acceptance criteria

```text
[ ] plugin manifest reports 0.3.0.
[ ] protocol version is intentionally decided and consistent everywhere.
[ ] all lifecycle docs describe work-level high-risk review gating.
[ ] all audit docs/skills list plan/work/phase/integration.
[ ] README command syntax matches build_parser exactly.
[ ] context assembler behavior is documented accurately.
[ ] backward compatibility behavior is documented accurately.
[ ] orchestrator is clearly outside 0.3.0 scope.
[ ] full test suite still passes.
```

## Completion report

Return only:

```markdown
## Result
- Plugin version:
- Protocol version and rationale:
- Files synchronized:
- Stale-reference scan:
- Full tests:
```
