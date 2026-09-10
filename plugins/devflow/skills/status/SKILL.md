---
name: status
description: Inspect DevFlow STATE and WORK deterministically and report the current lifecycle position and next action. Use when resuming work, switching agent sessions, checking blockers, or deciding whether to plan, run, audit, request a decision, or finish.
---

# DevFlow Status

Use the deterministic runtime instead of reconstructing state from narrative documents.

## Runtime

Every `devflow` command below runs from the repository root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

If that variable is unset, use this skill's wrapper instead. It resolves the plugin root from its
own location, so the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

## Workflow

1. Run `devflow status <domain>`. It reports lifecycle position, blocked work, the computed next
   action, workflow type, runtime config, domains root, domain directory, the phase diff range when
   one is pinned, and the documents that action needs as `next.input` lines.
2. When detailed machine state is needed, run `devflow status <domain> --json`.
3. When the next executable work contract is needed, run `devflow next <domain>`.
4. Read the domain's `PITFALLS.md` before acting on the next action. `status` reports where the work
   is; `PITFALLS.md` holds what will bite you, and no state machine can compute that half.
5. Report exactly the computed lifecycle position, blockers, next role, next command, scope and
   mode, phase, and WORK ID.

`status` computes and reports the next action only. It does not autonomously run WORK, audits, or
remediation. A pending high/critical WORK review appears before a dependent WORK is released.

Do not infer a different next action from a stale README, audit prose, historical chat, or handoff
documents. If STATE or WORK validation fails, report the validation problem as the next thing to fix.

## Delivery inspection

`devflow delivery paths <domain> [--branch <name>]` locates the branch PR and Postman outputs.
`devflow delivery check <domain> [--final]` checks recorded delivery evidence. Legacy policy stays
readable; plan/run adopts it with `delivery enable` before new execution. Status inspection alone
preserves that legacy policy and its completed WORK.

## Whole-work finalization

A computed `finalize` action belongs to the Executor, with no selected WORK. Use
`devflow render finalize <domain>` for the complete ELI5/Newman packet and
`devflow delivery context <domain>` for all-work scope/output metadata. Distinguish failed API
assertions, environment blockers, unknown diagnosis, stale HTML and stale source evidence.
`next` remains a WORK selector and can return nonzero for this non-WORK action.
