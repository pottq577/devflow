# Executor: finalize the entire implemented domain

Continue with the implementation model. Treat the complete domain's PLAN, every WORK and every
branch as the explanation scope. Read the appended `finalization` protocol before execution.

1. Inspect `delivery context`, all WORK/branch evidence and the actual diffs. Ensure cumulative PRs
   follow `docs/PR/templates.md` and collections represent all affected HTTP contracts.
2. Discover and invoke the installed `eli5` skill using the host (Codex `$eli5`). Read its actual
   SKILL.md. Generate one self-contained whole-work HTML at the context path with exact metadata,
   visible WORK dispositions and cross-branch flow. Record `delivery explain` with actual evidence.
3. Discover existing Newman, startup commands, build identity and local/test fixture/integration
   safety. Bring up only authorized test services. Execute `delivery newman` for every branch with
   verified server SHA and safety note. Use the fixed bounded profile and truthful exit status.
4. For each unsuccessful attempt, inspect contract, requests/assertions and private server/report
   evidence. Classify code, collection, environment or unknown via `delivery triage`.
5. For a confirmed code/collection defect, create one scoped integration remediation WORK with
   NEWMAN-<run-id> origin, summary reference and a failing regression. Register it, then execute
   only the runtime-selected ordinary WORK. Commit the tested repair; retain all review gates.
   For ignored collection-only changes, commit a meaningful tracked regression fixture/test or
   generator fix, and keep generated private docs local. Environment corrections require reruns;
   unresolved cases stay blocked. Stop after three unsuccessful root-cause fixes for review.
6. After repair, rebuild the matching server, refresh affected PR/collection outputs and rerun
   Newman. Record current test results in PR, `delivery refresh`, and repeat if collections changed.
7. Obtain fresh whole-domain context. Invoke ELI5 to update the complete explanation to the final
   repaired commits and final test outcomes, then record `delivery explain` again.
8. Run `delivery check --final`, `delivery finalize`, `validate`, then `status`. Hand off to the
   computed independent audit or decision. Keep remote publication/push/merge under user control.

Report paths, request/assertion counts, diagnoses and repair commits, plus any actual execution
blockers. Keep credentials and raw payloads private. Reading a skill or parsing a collection
alone establishes neither skill execution nor live API success.
