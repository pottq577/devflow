---
name: audit
description: Independently audit a DevFlow plan, work, phase, or whole integration using repository evidence, then classify findings and generate remediation/evidence WORK directly. Use for plan review, work review, phase review, closure review, and cross-phase integration review in a fresh reviewer session.
---

# DevFlow Audit

Operate as the **Auditor** in an independent review context.
Verify repository facts directly.

## Runtime

Every `devflow` command below runs from the repository root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

If that variable is unset, use this skill's wrapper instead.
It resolves the plugin root from its own location, so the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

## Workflow

1. Run `devflow status <domain>` and use its exact `scope=plan|work|phase|integration`, `mode=initial|closure`, phase, and WORK id.
   1. Work scope requires `--task <WORK-ID>`.
   2. Render rejects any other lifecycle position.
   3. A work initial audit gates high/critical dependents, and a work closure audit verifies its remediation.
   4. Phase and integration each have initial and closure audits; a high-risk plan review is initial before WORK begins.
   5. Use a fresh high-reasoning session whenever practical.
2. **Pin the range before reading code.**
   1. If the phase has no `diff_range`, run `devflow phase ref <domain> <phase> --base <ref> --head <ref>`.
   2. It verifies that the base is an ancestor of the head and refuses otherwise, because a stacked branch cut from a work commit makes a 3-dot diff resolve to a stale merge base and report hundreds of unrelated files.
   3. Use `--range` for the diverged case, after inspecting `git log --graph --oneline <base> <head>`.
3. Run `devflow render audit <domain> --scope <scope> [--task WORK-ID] [--phase XX] --mode <mode>`.
   1. The packet inlines the audit core with its concrete per-axis checks, the resolved domain extension, the risk and decision policies, and the domain's `PITFALLS.md`.
4. Do not check out branches.
   1. Another session may be working in the tree.
   2. Read with `git show <ref>:<path>` and the pinned diff; create a worktree only to build or test, and remove it afterwards.
5. Inspect current code, git history and diff, tests, repository rules, PRD, PLAN, and the relevant WORK manifests.
   1. Treat prior reports as leads, never as facts.
6. Apply the common audit axes.
   1. For integration scope, also inspect cross-phase contracts, transferred requirements in the receiving manifest, end-to-end state and data flows, transaction boundaries, migration ordering, and regression/evidence gaps.
7. Write or update the single audit artifact under `audits/`.
   1. Work audits use `audits/work/<WORK-ID>.md`; do not create separate review-plan or handoff documents.
   2. Start the Markdown with YAML front matter conforming to `core/schemas/audit.schema.yaml`, and retain the human-readable audit below it.
8. Classify findings as `CONFIRMED`, `DECISION_REQUIRED`, `EVIDENCE_REQUIRED`, `REJECTED`, `DOCUMENTATION_DRIFT`, or `SPEC_DRIFT`.
   1. Assign a severity and reach a verdict of `pass`, `conditional_pass`, or `fail`.
9. **Never record `pass` without evidence.**
   1. Only a command you actually executed, with its output, is grounds for a pass.
10. Create remediation WORK for confirmed findings, documentation WORK for documentation findings, and evidence WORK for evidence-required findings.
    1. Give each generated item `context`, `premise_checks`, and `pitfalls` the same as any planned item.
    2. Link every item and finding in both directions.
    3. Default to one finding per WORK; when root cause, change and rollback boundary, and verification are shared, explain the aggregation in `origin.aggregation_reason`.
    4. Build dependencies before severity ordering.
11. Preserve the finding's expected event and outcome in WORK objective and acceptance.
    1. Do not infer or substitute a different meaning.
    2. Re-read generated WORK and record coverage in the audit body.
12. Document unresolved decisions in `DECISIONS.md`.
    1. Never guess the policy or create ready code WORK before resolution.
    2. `audit apply` registers their IDs in STATE after validating the complete outcome.
13. Add durable traps you uncovered to `PITFALLS.md`.
14. After writing the audit artifact and linked WORK or decisions, run `devflow audit apply <domain> --scope <scope> --mode <mode>` with `--task <WORK-ID>` or `--phase <PHASE>` when required.
    1. Do not edit STATE or use a legacy verified transition to apply the audit.
    2. `audit apply` records the applied finding set as machine-owned provenance, so a later closure needs no documentation commit and works with `docs/` gitignored.
    3. Then run validation and status.

## Peer audit lenses

Follow `core/protocol/skill-composition.md`.

When Ponytail review guidance is available, use it as an additional discovery lens for unnecessary abstractions, duplicate wrappers or layers, speculative extension points, unused configurability, avoidable custom implementations, unnecessary dependencies, and code that can be deleted while preserving the contract.

Treat every Ponytail observation as a lead.
Before recording a finding, independently verify it against the PLAN, the current WORK or audit scope, repository callers, tests, compatibility requirements, repository conventions, and acceptance criteria.
Only a verified lead enters the normal DevFlow AUDIT artifact, as a finding on the existing overengineering and scope-intrusion axis (audit core axis F).
Do not create a new audit axis or a Ponytail-specific audit document, and use the existing classification and remediation lifecycle.

Superpowers `receiving-code-review` output is advisory only.
The DevFlow audit finding is the authoritative record.
Do not trigger `requesting-code-review` from an audit.

## Closure mode

Verify that the prior finding is actually closed, acceptance still holds, and no new regression was introduced.
Reopen or create a finding when evidence disproves closure.
A finding kept `still_open`, and any finding a `reopened` entry points at, must stay at least at its recorded severity; raising a severity with new evidence is fine, lowering an active one is refused.

When a `SPEC_DRIFT` or other `stop` finding blocked a scope, resolve the specification conflict first, then return the scope to a fresh initial audit with its recovery command: `plan-review set <domain> pending`, `work review <domain> <WORK-ID> pending`, `phase set <domain> <phase> audit`, or `integration set <domain> audit`.

Finish with verdict, SHAs and diff range, finding counts by classification and severity, generated WORK IDs, unresolved decisions, residual risk, and next action.

## Delivery-specific review

Read `core/protocol/delivery-artifacts.md`, already in the rendered packet.
For enabled domains, verify comment usefulness at the committed anchors, PR template fidelity and correct base/head scope, cumulative coverage across all branch WORK, Postman routes/DTO/auth/error checks and empty credential defaults.
Confirm every no-HTTP assessment against changed source.
Keep generated-file validation distinct from actual API execution evidence.
Run `devflow delivery check <domain>` and, at integration closure, add `--final`.
Create normal traced WORK for confirmed defects.
Each remediation refreshes the affected branch outputs before its own completion.

## Whole-work finalization review

For enabled finalization, apply `finalization.md`.
Compare the single ELI5 HTML to all WORK and branches, including cancelled/transferred outcomes, cross-branch behavior, final commits and actual test results.
Verify genuine installed-skill invocation and useful explanation beyond metadata.
Check Newman target/build isolation, complete request/assertion coverage, raw/summary integrity, secret hygiene and no-HTTP rationale.
Inspect every failed run's contract-based diagnosis, regression, repair commit and later passing server build.
Preserve independent audit gates; finalization evidence authorizes handoff, and the Auditor verifies its truth.
