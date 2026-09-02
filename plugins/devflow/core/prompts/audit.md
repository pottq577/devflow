# Auditor packet

Operate in Auditor mode with an independent mindset. The audit core, the resolved domain extension,
and the domain's pitfalls are appended below.

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
5. Execute the common audit axes and the requested plan/phase/integration scope.
6. Classify every finding using the DevFlow finding taxonomy. Assign severity, and reach a verdict
   of `pass`, `conditional_pass`, or `fail`.
7. Never write `pass` without evidence. Only a command you actually executed, with its output, is
   grounds for a pass.
8. Create remediation WORK directly for `CONFIRMED` and `DOCUMENTATION_DRIFT` findings, carrying
   `context`, `premise_checks`, and `pitfalls` the same as any planned item.
9. Create evidence WORK for `EVIDENCE_REQUIRED` findings. No product-code changes.
10. Record and block `DECISION_REQUIRED` and `SPEC_DRIFT` items instead of guessing.
11. Respect dependency ordering when creating remediation. Dependency outranks severity.
12. Add durable traps you uncovered to `PITFALLS.md`.
13. Update STATE and run validation.

Closure mode verifies previous findings and regressions; it does not repeat speculative planning.
Reopen a finding when evidence disproves its closure.
