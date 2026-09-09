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

1. Run `devflow status <domain>` and use its exact `scope=plan|work|phase|integration`,
   `mode=initial|closure`, phase, and WORK id. Work scope requires `--task <WORK-ID>`. Render rejects
   any other lifecycle position. A work initial audit gates high/critical dependents, and a work
   closure audit verifies its remediation. Phase and integration each have initial and closure
   audits; a high-risk plan review is initial before WORK begins. Use a fresh high-reasoning session
   whenever practical.
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
   `audits/work/<WORK-ID>.md`; do not create separate review-plan or handoff documents. Start the
   Markdown with YAML front matter conforming to `core/schemas/audit.schema.yaml`, and retain the
   human-readable audit below it.
8. Classify findings as `CONFIRMED`, `DECISION_REQUIRED`, `EVIDENCE_REQUIRED`, `REJECTED`,
   `DOCUMENTATION_DRIFT`, or `SPEC_DRIFT`. Assign a severity and reach a verdict of `pass`,
   `conditional_pass`, or `fail`.
9. **Never record `pass` without evidence.** Only a command you actually executed, with its output,
   is grounds for a pass.
10. Create remediation WORK for confirmed findings, documentation WORK for documentation findings,
    and evidence WORK for evidence-required findings. Give each generated item `context`, `premise_checks`, and `pitfalls`
    the same as any planned item. Link every item and finding in both directions. Default to one
    finding per WORK; when root cause, change and rollback boundary, and verification are shared,
    explain the aggregation in `origin.aggregation_reason`. Build dependencies before severity ordering.
11. Preserve the finding's expected event and outcome in WORK objective and acceptance. Do not infer
    or substitute a different meaning. Re-read generated WORK and record coverage in the audit body.
12. Document unresolved decisions in `DECISIONS.md`. Never guess the policy or create ready code WORK
    before resolution. `audit apply` registers
    their IDs in STATE after validating the complete outcome.
13. Add durable traps you uncovered to `PITFALLS.md`.
14. After writing the audit artifact and linked WORK or decisions, run
    `devflow audit apply <domain> --scope <scope> --mode <mode>` with `--task <WORK-ID>` or
    `--phase <PHASE>` when required. Do not edit STATE or use a legacy verified transition to apply
    the audit. `audit apply` records the applied finding set as machine-owned provenance, so a later
    closure needs no documentation commit and works with `docs/` gitignored. Then run validation and
    status.

## Peer audit lenses

Follow `core/protocol/skill-composition.md`.

When Ponytail review guidance is available, use it as an additional discovery lens for
unnecessary abstractions, duplicate wrappers or layers, speculative extension points, unused
configurability, avoidable custom implementations, unnecessary dependencies, and code that can be
deleted while preserving the contract.

Treat every Ponytail observation as a lead. Before recording a finding, independently verify it
against the PLAN, the current WORK or audit scope, repository callers, tests, compatibility
requirements, repository conventions, and acceptance criteria. Only a verified lead enters the
normal DevFlow AUDIT artifact, as a finding on the existing overengineering and scope-intrusion
axis (audit core axis F). Do not create a new audit axis or a Ponytail-specific audit document,
and use the existing classification and remediation lifecycle.

Superpowers `receiving-code-review` output is advisory only. The DevFlow audit finding is the
authoritative record. Do not trigger `requesting-code-review` from an audit.

## Closure mode

Verify that the prior finding is actually closed, acceptance still holds, and no new regression was
introduced. Reopen or create a finding when evidence disproves closure. A finding kept `still_open`,
and any finding a `reopened` entry points at, must stay at least at its recorded severity; raising a
severity with new evidence is fine, lowering an active one is refused.

When a `SPEC_DRIFT` or other `stop` finding blocked a scope, resolve the specification conflict
first, then return the scope to a fresh initial audit with its recovery command: `plan-review set
<domain> pending`, `work review <domain> <WORK-ID> pending`, `phase set <domain> <phase> audit`, or
`integration set <domain> audit`.

Finish with verdict, SHAs and diff range, finding counts by classification and severity, generated
WORK IDs, unresolved decisions, residual risk, and next action.
