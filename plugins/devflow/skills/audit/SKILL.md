---
name: audit
description: Independently audit a DevFlow plan, work, phase, or whole integration using repository evidence, then classify findings and generate remediation/evidence WORK directly. Use for plan review, work review, phase review, closure review, and cross-phase integration review in a fresh reviewer session.
---

# DevFlow Audit

Operate as the **Auditor** in an independent review context. Verify repository facts directly.

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

1. Determine `scope=plan|work|phase|integration` and `mode=initial|closure`. Work scope requires
   `--task <WORK-ID>`. A work initial audit gates high/critical dependents, and a work closure audit
   verifies its remediation. Phase and integration each have initial and closure audits; a high-risk
   plan review is initial before WORK begins. Use a fresh high-reasoning
   session whenever practical.
2. **Pin the range before reading code.** If the phase has no `diff_range`, run
   `devflow phase ref <domain> <phase> --base <ref> --head <ref>`. It verifies that the base is an
   ancestor of the head and refuses otherwise, because a stacked branch cut from a work commit makes
   a 3-dot diff resolve to a stale merge base and report hundreds of unrelated files. Use `--range`
   for the diverged case, after inspecting `git log --graph --oneline <base> <head>`.
3. Run `devflow render audit <domain> --scope <scope> [--task WORK-ID] [--phase XX] --mode <mode>`. The packet inlines
   the audit core with its concrete per-axis checks, the resolved domain extension, the risk and
   decision policies, and the domain's `PITFALLS.md`.
4. Do not check out branches. Another session may be working in the tree. Read with
   `git show <ref>:<path>` and the pinned diff; create a worktree only to build or test, and remove
   it afterwards.
5. Inspect current code, git history and diff, tests, repository rules, PRD, PLAN, and the relevant
   WORK manifests. Treat prior reports as leads, never as facts.
6. Apply the common audit axes. For integration scope, also inspect cross-phase contracts,
   transferred requirements in the receiving manifest, end-to-end state and data flows, transaction
   boundaries, migration ordering, and regression/evidence gaps.
7. Write or update the single audit artifact under `audits/`. Work audits use
   `audits/work/<WORK-ID>.md`; do not create separate review-plan or
   handoff documents.
8. Classify findings as `CONFIRMED`, `DECISION_REQUIRED`, `EVIDENCE_REQUIRED`, `REJECTED`,
   `DOCUMENTATION_DRIFT`, or `SPEC_DRIFT`. Assign a severity and reach a verdict of `pass`,
   `conditional_pass`, or `fail`.
9. **Never record `pass` without evidence.** Only a command you actually executed, with its output,
   is grounds for a pass.
10. Create remediation WORK for confirmed and documentation findings, and evidence WORK for
    evidence-required findings. Give each generated item `context`, `premise_checks`, and `pitfalls`
    the same as any planned item. Build dependencies before severity ordering.
11. Add unresolved decision IDs to STATE and document them in `DECISIONS.md`. Never guess the policy.
12. Add durable traps you uncovered to `PITFALLS.md`.
13. For work scope, record `devflow work review <domain> <WORK-ID> verified`,
    `remediation --remediation-work <ID>`, or `blocked` after writing the audit artifact. Update
    phase/integration state when applicable, run validation, then run status.

## Closure mode

Verify that the prior finding is actually closed, acceptance still holds, and no new regression was
introduced. Reopen or create a finding when evidence disproves closure.

Finish with verdict, SHAs and diff range, finding counts by classification and severity, generated
WORK IDs, unresolved decisions, residual risk, and next action.
