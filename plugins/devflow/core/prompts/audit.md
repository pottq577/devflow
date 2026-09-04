# Auditor packet

Operate in Auditor mode with an independent mindset. The audit core, the resolved domain extension,
and the domain's pitfalls are appended below.

This packet is emitted only for the exact audit scope, mode, phase, and WORK target in the computed
next action. Re-run `devflow status` instead of auditing another lifecycle position.

1. **Pin the range first.** Baseline SHA, target SHA, diff range. If `diff_range` is unset, run
   `devflow phase ref` before reading anything. Confirm the base really is an ancestor of the head:
   a stacked branch cut from a work commit resolves to a stale merge base and reports hundreds of
   unrelated files.
2. Do not check out branches. Another session may be working in the tree. Read with
   `git show <ref>:<path>` and the pinned diff; create a worktree only to build or test.
3. Read the relevant PRD, PLAN, WORK, `PITFALLS.md`, repository rules, and the domain extension.
4. **Verify repository facts directly. Treat prior reports as leads only.** Paths, line numbers, and
   causal claims in earlier audits have been wrong before, and were caught only because the next
   reader re-checked them in code.
5. Execute the common audit axes and the requested `plan`, `work`, `phase`, or `integration` scope.
   Initial work audits gate high/critical dependents; closure work audits verify their remediation.
   Phase and integration closure audits verify their respective remediation. For work scope,
   inspect the full selected WORK YAML, origin links, implementation evidence, changed files, recorded
   commit, current HEAD, and its `audits/work/<WORK-ID>.md` artifact.
6. Classify every finding using the DevFlow finding taxonomy. Assign severity, and reach a verdict
   of `pass`, `conditional_pass`, or `fail`.
7. Write the audit result as YAML front matter at the start of the single canonical audit Markdown.
   Follow `audit.schema.yaml`, retain the human-readable explanation below it, and keep initial
   findings in the file when recording closure outcomes.
8. Never write `pass` without evidence. Only a command you actually executed, with its output, is
   grounds for a pass.
9. Create remediation WORK directly for `CONFIRMED` and `DOCUMENTATION_DRIFT` findings, carrying
   `context`, `premise_checks`, and `pitfalls` the same as any planned item.
10. Create evidence WORK for `EVIDENCE_REQUIRED` findings. No product-code changes.
11. Record decisions in `DECISIONS.md`, and block `DECISION_REQUIRED` and `SPEC_DRIFT` items instead
    of guessing. Respect dependency ordering when creating remediation.
12. Add durable traps you uncovered to `PITFALLS.md`.
13. After the audit, WORK, and decision records are complete, run `devflow audit apply` with the exact
    rendered scope, mode, phase, and WORK target. The runtime validates and updates STATE. Do not edit
    STATE directly.

Closure mode verifies previous findings and regressions; it does not repeat speculative planning.
Reopen a finding when evidence disproves its closure.
