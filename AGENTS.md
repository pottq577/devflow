# DevFlow marketplace repository instructions

This file governs changes to this marketplace repository, not projects that install DevFlow. Keep Claude Code and Codex on the same implementation under `plugins/devflow/`.

## Start on main without losing work

Before each task, inspect the branch and working tree:

```bash
git branch --show-current
git status --short
```

- Work, commit and package only on `main`. If another branch is clean, use `git switch main` first.
- If another branch has uncommitted changes, stop repository modifications and report the blocker. Preserve those changes.
- Do not create or use feature, fix, release or temporary branches, detached HEADs or worktrees for work on this repository.
- Never reset, clean, force-checkout or force-switch to bypass this policy.
- Recheck the branch before committing, packaging and reporting completion.

DevFlow's generic protocols may use branches or worktrees in *consuming projects*. They do not override this repository's `main`-only rule.

## Follow the right source of truth

Resolve conflicts in this order:

1. Explicit instructions for the current task.
2. This `AGENTS.md`.
3. `plugins/devflow/core/protocol/` and `plugins/devflow/core/schemas/` for normative contracts.
4. Relevant modules in `plugins/devflow/scripts/` and their tests for executable behavior.
5. Current plugin README, skills, prompts, templates and changelog.
6. Root marketplace documentation and historical records.

Verify actual behavior when documents and code disagree; repair drift in the affected layers. Historical release records and local `docs/` material are context, not current contracts.

## Keep one shared implementation

- `.agents/plugins/marketplace.json` and `.claude-plugin/marketplace.json` are discovery adapters. `plugins/devflow/.codex-plugin/` and `plugins/devflow/.claude-plugin/` contain plugin-specific metadata.
- Shared CLI, runtime, helpers, protocols, schemas, prompts, templates, skills and tests belong exclusively under `plugins/devflow/`. Do not copy implementations into adapter directories.
- `plugins/devflow/core/protocol/role-instructions.md` assigns rule ownership. Avoid restating normative rules in skills or rendered prompts.
- `docs/` is Git-ignored local working material, not part of the tracked marketplace release. Do not force-add generated artifacts to bypass that boundary.

## Preserve lifecycle and safety contracts

- The manual CLI computes its next action through `status` / `next`; it does not independently implement WORK, run reviews or dispatch background agents. Hosted Goal/Autopilot orchestration must still obey the computed action and ordinary gates.
- Execute exactly one selected ready WORK per `run`; check current-HEAD premises, dependencies and acceptance criteria. Require actual verification evidence before completion.
- Preserve required plan, high/critical WORK, phase and integration audits, including initial/closure reviews, independent review and traced remediation. Never waive a gate to make a test pass.
- `STATE.yaml` is machine-owned. Runtime computes derived fields, rejects invalid transitions before mutation and writes affected state/WORK atomically. Preserve backward-readable artifacts unless a deliberate protocol change is approved.
- Do not add new required lifecycle documents or sidecars. The artifact budget and permitted derived PR/Postman/ELI5/Newman output are owned by `core/protocol/lifecycle.md`, `delivery-artifacts.md` and `finalization.md`.
- Do not add hidden execution, background workers, new subagent loops or broadened authorization without an explicit product-contract change. Keep credentials and raw evidence private.

## Change only the affected contract

Before editing behavior, inspect the relevant protocol, schema, implementation module (including extracted helpers) and regression tests. Confirm the current `main` behavior first.

- Make the smallest coherent change. Add a reproducing regression test before fixing a defect when practical.
- Do not weaken validators, test assertions, review gates, state guards or verification requirements. Do not replace runtime enforcement with instructions alone.
- Keep CLI examples consistent with the actual parser. For STATE/WORK/status changes, align schema, defaults, readers, validators, projections and tests.
- Update only affected protocol, schema, runtime, template, prompt, skill, test, README, changelog and manifest layers. Avoid mechanical edits to unrelated layers.
- Use the existing Python 3.10+ and PyYAML runtime where sufficient; avoid new dependencies without justification.

## Verify the changed surface

- Run targeted regression tests and Python syntax checks for changed runtime/test modules. Execute commands from the repository root unless specified otherwise.
- For merge or release readiness, follow `plugins/devflow/core/protocol/release-validation.md`. Its `release_gate.py` commands own full-suite coverage, Newman skip rules and fresh evidence. A focused run does not establish release readiness.
- For adapter metadata changes, validate all changed JSON manifests and confirm both marketplace pointers still reference `plugins/devflow/`.
- Keep plugin versions synchronized across `.claude-plugin/marketplace.json`, both `plugins/devflow/` plugin manifests and current documentation. `.agents/plugins/marketplace.json` is a discovery pointer and must not acquire `version` or `description`.
- Treat plugin and protocol versions separately. Read the protocol constant from `plugins/devflow/scripts/devflow.py`; change it only after checking compatibility and recording the decision in `plugins/devflow/CHANGELOG.md`.

## Package and report accurately

- Keep `plugins/devflow/bin/devflow` executable (`100755`). Exclude caches, `.git/`, temporary files and generated ZIPs.
- Verify that `git archive` or `./package.sh` includes both marketplace adapters and both plugin manifests. Do not mistake a ZIP containing only `plugins/devflow/` for a complete marketplace distribution.
- Treat `plugins/devflow/README.md` as current user documentation and `core/protocol/` plus `core/schemas/` as the contract. Preserve historical release material as history.
- Before completion, run `git diff --check`, inspect `git status --short`, confirm `main` and review the changed files for scope creep and copied adapter logic.
- Report the checks actually executed, results and unverified acceptance criteria. Do not claim native Claude Code/Codex installation, live Newman/ELI5 execution or release readiness without corresponding evidence.
