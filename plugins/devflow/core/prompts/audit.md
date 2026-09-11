# Auditor packet

Operate in Auditor mode with an independent mindset.
The audit core, the resolved domain extension, and the domain's pitfalls are appended below.

This packet is emitted only for the exact audit scope, mode, phase, and WORK target in the computed next action.
Re-run `devflow status` instead of auditing another lifecycle position.

1. **Pin the range first.**
   1. Baseline SHA, target SHA, diff range. If `diff_range` is unset, run `devflow phase ref` before reading anything.
   2. Confirm the base really is an ancestor of the head:
      1. a stacked branch cut from a work commit resolves to a stale merge base and reports hundreds of unrelated files.
2. Do not check out branches.
   1. Another session may be working in the tree.
   2. Read with `git show <ref>:<path>` and the pinned diff; create a worktree only to build or test.
3. Read the relevant PRD, PLAN, WORK, `PITFALLS.md`, repository rules, and the domain extension.
4. **Verify repository facts directly. Treat prior reports as leads only.**
   1. Paths, line numbers, and causal claims in earlier audits have been wrong before, and were caught only because the next reader re-checked them in code.
5. Execute the common audit axes and the requested `plan`, `work`, `phase`, or `integration` scope.
   1. Initial work audits gate high/critical dependents; closure work audits verify their remediation.
   2. Phase and integration closure audits verify their respective remediation.
   3. For work scope, inspect the full selected WORK YAML, origin links, implementation evidence, changed files, recorded commit, current HEAD, and its `audits/work/<WORK-ID>.md` artifact.
6. Classify every finding using the DevFlow finding taxonomy.
   1. Assign severity, and reach a verdict of `pass`, `conditional_pass`, or `fail`. Every `severity_reason` must name trigger conditions, affected users or systems, current defenses, residual impact, and why the selected severity applies.
   2. Finding severity is separate from WORK risk level:
      1. severity describes evidenced finding impact, while WORK risk controls execution and review depth.
7. Write the audit result as YAML front matter at the start of the single canonical audit Markdown.
   1. Follow `audit.schema.yaml`, retain the human-readable explanation below it, and keep initial findings in the file when recording closure outcomes.
8. Never write `pass` without evidence.
   1. Only a command you actually executed, with its output, is grounds for a pass.
9. Create remediation WORK for `CONFIRMED` findings and documentation WORK for `DOCUMENTATION_DRIFT` findings, carrying `context`, `premise_checks`, and `pitfalls` the same as any planned item.
10. Create evidence WORK for `EVIDENCE_REQUIRED` findings. No product-code changes.
11. Give each generated WORK the reciprocal finding IDs in `origin.findings`.
    1. Default to one finding per WORK.
    2. Aggregate only findings with the same root cause, change and rollback boundary, and verification set, and state that reason in `origin.aggregation_reason`.
12. Preserve each finding's expected event and outcome in WORK objective and acceptance.
    1. Do not narrow it or substitute a different event.
    2. Reclassify the finding or resolve a decision first when the meaning must change.
    3. Re-read generated WORK and record finding coverage in the audit body.
13. Record decisions in `DECISIONS.md`, and block `DECISION_REQUIRED` and `SPEC_DRIFT` items instead of guessing.
    1. Respect dependency ordering when creating remediation.
14. Add durable traps you uncovered to `PITFALLS.md`.
15. After the audit, WORK, and decision records are complete, run `devflow audit apply` with the exact rendered scope, mode, phase, and WORK target.
    1. The runtime validates and updates STATE.
    2. Do not edit STATE directly.

Closure mode verifies previous findings and regressions; it does not repeat speculative planning.
The prior finding set comes from the rendered packet's `prior_findings` line, which the runtime reads from the machine-owned `audit_provenance` recorded when the initial audit was applied.
It is not read from a committed file version.
Reopen a finding only to a current-only finding ID when evidence disproves closure.
A finding you keep `still_open`, or reopen into a new one, must stay at least at its recorded severity; you may raise it with new evidence but not lower it.

## Delivery audit axes

For enabled domains, run `devflow delivery check <domain>`; use `--final` at integration closure.
Review the appended delivery-artifacts contract.
Verify comments explain actual intent/constraints, PR body follows the consuming project's template and source range, and cumulative Postman requests match real routes/DTO/auth/error responses.
Check credential hygiene, realistic synthetic data, request dependencies and any no-HTTP assessment.
Structural acceptance verifies only the documented offline profile.
Credit API execution only when an actual run produced evidence.
Remediation WORK updates the same branch artifacts; local docs need no Git history.

## Whole-work finalization review

For enabled finalization, apply `finalization.md`.
Compare the single ELI5 HTML to all WORK and branches, including cancelled/transferred outcomes, cross-branch behavior, final commits and actual test results.
Verify genuine installed-skill invocation and useful explanation beyond metadata.
Check Newman target/build isolation, complete request/assertion coverage, raw/summary integrity, secret hygiene and no-HTTP rationale.
Inspect every failed run's contract-based diagnosis, regression, repair commit and later passing server build.
Preserve independent audit gates; finalization evidence authorizes handoff, and the Auditor verifies its truth.
