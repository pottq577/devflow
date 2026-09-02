# DevFlow 0.3.0 Goal Pack — Execution Guide

## Purpose

This package splits the DevFlow 0.3.0 hardening work into small `/goal` jobs that can be executed reliably by GPT-5.6 Terra medium/high or GPT-5.6 Luna xhigh.

The current manual operating model is intentionally preserved:

```text
devflow-plan
→ devflow-run
→ devflow-audit
→ devflow-run
→ devflow-audit
→ ...
```

Autonomous orchestration is a separate future feature. Do not add a controller, `devflow-drive`, automatic subagent dispatch, background worker, parallel execution, or multi-agent lease/lock in this package.

## How to use

Run the goals in numeric order on the same branch/worktree. For each goal, give the entire Markdown file to `/goal` unchanged. Use a fresh agent session when practical so the model receives a narrow objective instead of accumulating unrelated context.

Before each goal, preserve the changes from the previous goal. Each goal begins by inspecting the current repository state and running the relevant existing tests, so it can adapt to earlier edits without re-planning the whole project.

## Model routing

| Goal | Recommended model | Reason |
| --- | --- | --- |
| 01 Schema SSOT + atomic YAML I/O | Terra medium | Mostly deterministic refactor with regression tests |
| 02 High-risk WORK review gate | Terra high | Core state-machine behavior and dependency semantics |
| 03 Transition guards | Terra high | Multiple lifecycle invariants must remain consistent |
| 04 Audit scope correctness | Terra medium | Narrow CLI/render bugfix with explicit acceptance tests |
| 05 Context assembler | Terra high | Markdown extraction and context-boundary reasoning |
| 06 Derived lifecycle state | Terra high | State derivation interacts with every lifecycle stage |
| 07 Test harness hardening | Terra medium | Mechanical subprocess/test-runner reliability work |
| 08 Protocol/docs/version sync | Terra medium or Luna xhigh | Mostly consistency/documentation after runtime is stable |
| 09 Final acceptance audit | Luna xhigh or Terra high | Cross-cutting verification, minimal implementation expected |

If Terra medium starts changing scope or misinterpreting state semantics, stop that goal and rerun the same file with Terra high. Do not promote the whole package to a larger model just because one state-machine goal is difficult.

## Repository baseline

The uploaded repository currently places the plugin at:

```text
plugins/devflow/
```

Important runtime functions in `plugins/devflow/scripts/devflow.py` are currently:

```text
load_yaml / dump_yaml / dump_yaml_if_changed
init_domain
load_work_index
item_phase
deps_satisfied
decision_satisfied
choose_next
compute_next_action
refresh_state
action_inputs
work_update
set_phase
set_plan_review
set_integration
validate_state
validate_item
validate
render
build_parser
```

The current plugin version is `0.2.0` and the runtime protocol constant is `1.1.0`.

## Package-wide invariants

Every goal must preserve these constraints:

1. Keep manual `plan → run → audit` operation as the primary UX.
2. Keep `STATE.yaml` and `work/*.yaml` as machine-readable lifecycle sources.
3. Keep `PITFALLS.md` and `DECISIONS.md` as human-readable accumulated knowledge/decision artifacts.
4. Runtime invariants must be enforced by the CLI, not only documented in Markdown.
5. Existing 0.2.0 domain artifacts should remain readable through normalization/defaulting where practical.
6. Avoid new dependencies unless they materially reduce implementation complexity.
7. Do not perform unrelated refactors.
8. Run `python3 tests/test_devflow.py` after each goal and leave the repository in a passing state before moving on.
9. Do not silently weaken a requirement to make tests pass.
10. If the codebase has changed since this package was generated, preserve the observable behaviors and acceptance criteria from each goal while adapting exact implementation details to the current code.

## Final target lifecycle

Low/medium WORK:

```text
ready
→ in_progress
→ done
→ dependent WORK may proceed
```

High/critical WORK:

```text
ready
→ in_progress
→ done
→ work initial audit
→ [pass] review verified
→ dependent WORK may proceed
```

or:

```text
work initial audit
→ confirmed finding
→ remediation WORK
→ remediation execution
→ work closure audit
→ review verified
→ dependent WORK may proceed
```

Phase lifecycle:

```text
phase work complete
→ phase initial audit
→ remediation if required
→ phase closure audit
→ phase verified
```

Integration lifecycle:

```text
all phases verified
→ integration initial audit
→ remediation if required
→ integration closure audit
→ integration verified
→ project complete
```
