# Executor: finalize the implemented domain

Continue with the implementation model for the computed project-wide `finalize` action.
The appended `core/protocol/finalization.md` and `core/protocol/delivery-artifacts.md`
own server safety, failure classification, remediation, evidence and review gates.
Follow this execution order without replacing those contracts.

1. Inspect every WORK and branch, including actual diffs, verification evidence,
   cumulative PRs (`docs/PR/templates.md`) and affected HTTP contracts.
2. Confirm each branch's build identity and isolated local/test environment. Discover
   Newman, then run `delivery newman` with a JSON `--server-command` and `--readiness-url`.
3. Inspect unsuccessful runs and use `delivery triage`. Create scoped integration
   remediation WORK only for confirmed code/collection defects. Let the runtime
   select each repair and its review gate; keep unresolved causes blocked.
4. Verify and commit repairs, rebuild the matching server, update branch artifacts
   with `delivery refresh`, and rerun affected Newman checks. Require current
   success or proven `not_applicable` evidence for every delivered branch.
5. After Newman, obtain fresh `delivery context`. Read and invoke the installed
   `eli5` skill through the host (Codex `$eli5`). Generate one whole-domain HTML
   with exact metadata, every WORK disposition, cross-branch behavior and current
   test outcomes. Record actual invocation evidence with `delivery explain`.
6. Run `delivery check --final`, `delivery finalize`, `validate`, then `status`.
   Hand off to the computed independent audit or decision, not publication.

Report evidence paths, request/assertion counts, diagnoses, repair commits and
observed blockers. Keep credentials and raw payloads private. Neither skill
inspection nor collection parsing proves an executed skill or live API test.
