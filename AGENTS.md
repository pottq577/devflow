# DevFlow Marketplace Agent Instructions

## 1. Repository purpose

This repository is the monorepo and distribution source of truth for DevFlow across Claude Code and OpenAI Codex.

Both marketplace adapters must resolve to the same shared plugin implementation under `plugins/devflow/`. Keep runtime code, protocol documents, schemas, templates, prompts, skills, and tests in that shared plugin. Adapter directories exist only for product-specific discovery and metadata.

## 2. Mandatory Git branch policy

All agent work in this repository happens on `main`.

Run this preflight at the beginning of every task:

```bash
git branch --show-current
git status --short
```

Rules:

- Continue the task only while the current branch is `main`.
- If the current branch is not `main` and the working tree is clean, switch to `main` before continuing:

  ```bash
  git switch main
  ```

- If the current branch is not `main` and the working tree contains changes, preserve the existing work. Do not reset, discard, overwrite, or force-switch those changes merely to satisfy this rule. Report the blocker before making repository changes.
- Do not create or use feature branches, fix branches, release branches, temporary branches, detached HEADs, or Git worktrees for agent work in this repository.
- Re-check `git branch --show-current` before committing, packaging, or declaring the task complete.
- Do not use destructive Git commands such as `git reset --hard`, `git clean -fd`, or forced checkout/switch operations to reach `main`.

The generic DevFlow protocol may discuss branch refs or temporary worktrees for repositories operated on by DevFlow. When modifying this marketplace repository itself, this `main`-only repository rule takes precedence.

## 3. Authority and source-of-truth order

When repository sources disagree, use this order:

1. Explicit instructions for the current task.
2. This repository instruction file (`AGENTS.md`).
3. `plugins/devflow/core/protocol/*.md` and `plugins/devflow/core/schemas/*` as the normative DevFlow contract.
4. `plugins/devflow/scripts/devflow.py` and the test suite as the executable implementation of that contract.
5. Current plugin documentation, templates, prompts, skills, and `CHANGELOG.md`.
6. Root marketplace documentation and release/implementation records under `docs/`.

`plugins/devflow/core/references/vibecoder.md` is design background. It is not the current protocol contract.

Historical work orders and acceptance reports describe how a release was produced. Do not let historical wording override the current protocol, schemas, runtime, or tests.

When contract, implementation, and documentation drift apart, verify the current behavior and repair the drift in the same coherent change.

## 4. Repository map

```text
.
├── .claude-plugin/marketplace.json       # Claude Code marketplace adapter
├── .agents/plugins/marketplace.json      # Codex marketplace adapter
├── plugins/devflow/                      # shared DevFlow implementation
│   ├── .claude-plugin/plugin.json        # Claude Code plugin metadata
│   ├── .codex-plugin/plugin.json         # Codex plugin metadata
│   ├── bin/devflow                       # executable wrapper
│   ├── scripts/devflow.py                # runtime and CLI
│   ├── core/
│   │   ├── protocol/                     # normative protocol rules
│   │   ├── schemas/                      # machine-readable contracts
│   │   ├── prompts/                      # rendered role prompts
│   │   ├── templates/                    # project artifact templates
│   │   ├── extensions/                   # audit extensions
│   │   └── references/                   # non-normative background material
│   ├── skills/{plan,run,audit,status}/   # agent-facing skills
│   └── tests/test_devflow.py             # framework regression suite
└── docs/                                 # implementation and release records
```

Do not copy shared runtime, protocol, schema, prompt, template, or skill implementations into `.agents/`, `.claude-plugin/`, `.codex-plugin/`, or another adapter-specific location.

## 5. Core architectural invariants

Preserve these invariants unless the task explicitly changes the DevFlow product contract.

### Shared implementation

- Claude Code and Codex use one shared implementation: `plugins/devflow/`.
- Product-specific adapters contain metadata and discovery configuration only.
- Fix shared behavior once in the shared implementation.

### Manual lifecycle

DevFlow remains a manual, state-based protocol:

```text
PRD
-> plan
-> optional required plan audit for high-risk domains
-> run exactly one ready WORK item
-> high/critical WORK initial audit before dependents
-> remediation WORK when findings are confirmed
-> high/critical WORK closure audit
-> dependent WORK release
-> phase initial audit
-> phase remediation
-> phase closure audit
-> next phase
-> integration initial audit
-> integration remediation
-> integration closure audit
-> integration verified
-> project complete
```

`status` and `next` compute what should happen next. The runtime does not autonomously execute, audit, remediate, dispatch subagents, or run a background controller.

### WORK execution

- One WORK item is one independently verifiable change boundary.
- `run` executes exactly one selected ready WORK item.
- Dependency order outranks severity.
- Re-check `premise_checks` against current HEAD before editing.
- `high` and `critical` WORK requires premise checks and work-level review before dependents proceed.
- Remediation WORK uses the same WORK schema and remains traceable to the originating finding.
- Completion requires real evidence. Do not substitute assertions for executed verification.

### Audits

Supported audit scopes are:

```text
plan
work
phase
integration
```

Work, phase, and integration audits support initial and closure semantics where required. Keep audit artifacts and runtime transitions consistent with `core/protocol/audit-core.md`, `risk-policy.md`, and `lifecycle.md`.

### Lifecycle state

- `STATE.yaml` is machine-owned lifecycle state.
- Derived fields such as next action, project status, active phase, and target SHA are computed by runtime logic.
- Mutation commands must reject invalid transitions before writing state or WORK artifacts.
- Preserve atomic YAML writes and schema-backed validation.
- Preserve backward-readable artifacts unless an explicit protocol-breaking change is approved.

### Artifact budget

DevFlow project output is intentionally bounded to the documented PRD, PLAN, STATE, PITFALLS, DECISIONS, WORK, and AUDIT artifacts.

Do not introduce separate task handoffs, remediation-plan documents, focused-review documents, integration-test-plan documents, or prompt-handoff documents as new lifecycle requirements. The runtime and STATE must remain sufficient to reconstruct the next action.

## 6. Change discipline

Before changing behavior:

1. Read the relevant protocol files and schemas.
2. Read the affected runtime path in `scripts/devflow.py`.
3. Read the existing regression tests for that behavior.
4. Confirm the behavior at current `main` before editing.

Implementation rules:

- Make the smallest coherent change that satisfies the task.
- Avoid unrelated refactors and formatting churn.
- Prefer regression tests that reproduce a defect before fixing the implementation when practical.
- Keep validation in runtime/schema logic. Do not weaken tests, validators, review gates, or transition guards to make a scenario pass.
- Do not bypass an invariant through documentation-only wording changes.
- Do not add autonomous orchestration, hidden background workers, or subagent dispatch loops unless the product contract is explicitly changed.
- Avoid new dependencies when the existing Python 3.10+ and PyYAML runtime can express the change cleanly.

When a behavior or artifact contract changes, synchronize every affected layer in the same task as applicable:

```text
core/protocol
core/schemas
core/templates
core/prompts
scripts/devflow.py
skills/*
tests/test_devflow.py
plugins/devflow/README.md
plugins/devflow/CHANGELOG.md
plugin/marketplace manifests
```

Do not mechanically edit every layer. Update only the layers whose contract actually changed.

## 7. CLI and schema consistency

- CLI examples must match the parser implemented in `scripts/devflow.py`.
- New or changed STATE/WORK fields require corresponding schema, template/default, normalization/reader, validation, and regression-test updates where applicable.
- New statuses or transitions must be represented consistently across schema constants, runtime guards, lifecycle documentation, render behavior, and tests.
- A validator must reject malformed states rather than normalize away a real contract violation.
- Verification command/evidence strings that require meaningful content must reject blank or whitespace-only values.

## 8. Required verification

Use repository-root paths unless a command explicitly changes directory.

### Python syntax

For runtime or test changes:

```bash
python3 -m py_compile \
  plugins/devflow/scripts/devflow.py \
  plugins/devflow/tests/test_devflow.py
```

### Framework suite

For changes to runtime, schemas, protocol semantics, prompts, templates, or skills:

```bash
python3 plugins/devflow/tests/test_devflow.py
```

Run the full suite twice before declaring a release, lifecycle-wide change, state-machine change, review-gate change, or packaging-sensitive change release-ready.

### Manifest syntax

When adapter or plugin metadata changes:

```bash
python3 -m json.tool .agents/plugins/marketplace.json >/dev/null
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
python3 -m json.tool plugins/devflow/.codex-plugin/plugin.json >/dev/null
python3 -m json.tool plugins/devflow/.claude-plugin/plugin.json >/dev/null
```

Also verify that both marketplace adapters still resolve to the same `plugins/devflow` directory.

### Git and packaging hygiene

Before completion:

```bash
git diff --check
git status --short
git branch --show-current
```

`plugins/devflow/bin/devflow` must remain executable in Git (`100755`). Do not commit `__pycache__/`, `*.pyc`, `.git/`, generated release ZIPs, or other transient build/runtime output.

For release packaging, prefer:

```bash
git archive --format=zip --output=devflow-marketplace-<version>.zip HEAD
```

Inspect the archive for required adapter/plugin files and reject repository/cache metadata.

## 9. Versioning and release rules

Current baseline:

```text
plugin version:   0.6.1
protocol version: 1.5.0
```

Treat these as separate version domains.

- Keep the plugin version synchronized wherever it is represented in marketplace/plugin manifests and current documentation. It is represented in `.claude-plugin/marketplace.json` (twice), `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json`. `.agents/plugins/marketplace.json` is a discovery pointer only: it deliberately carries no `version` or `description`, because the Codex plugin's full metadata lives in `.codex-plugin/plugin.json`. Do not add version or description fields to it.
- Do not automatically set protocol version equal to plugin version.
- Change protocol version only after evaluating artifact-contract compatibility.
- Record the protocol-version decision and compatibility rationale in `CHANGELOG.md` when protocol behavior changes materially.
- Preserve backward-readable behavior when the selected protocol version promises it.
- Keep `plugins/devflow/bin/devflow` executable in the release tree.
- Do not claim real Claude Code or Codex installation validation unless that installation/import flow was actually executed in an isolated or throwaway CLI profile.

## 10. Documentation rules

- Treat `plugins/devflow/README.md` as current user-facing plugin documentation.
- Treat `core/protocol/*.md` plus `core/schemas/*` as the normative runtime contract.
- Keep skills concise and role-specific; detailed policy belongs in protocol files rather than duplicated skill references.
- Keep `vibecoder.md` labeled as background rationale.
- Preserve historical release/work-order records as history unless the task explicitly asks to correct those records.
- Avoid absolute local paths, scratch-workspace links, machine-specific paths, or stale pre-monorepo repository names in current documentation.

## 11. Completion standard

Before reporting a task complete:

- Confirm the repository is still on `main`.
- Review the final diff for scope creep and duplicated adapter logic.
- Run the verification appropriate to the changed surface.
- Confirm protocol/runtime/schema/docs consistency for any changed contract.
- State which checks were actually executed and their results.
- Explicitly identify any validation that remains unverified because the required external CLI or environment was not exercised.

Do not claim completion, release readiness, or adapter validation from static inspection alone when the relevant acceptance criterion requires executed verification.
