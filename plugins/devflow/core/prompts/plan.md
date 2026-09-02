# Architect packet

Operate in Architect mode. The protocol documents and the domain's accumulated pitfalls are
appended below; everything you need is in this packet.

1. Read the approved PRD, the repository-enforced rules, and `PITFALLS.md`.
2. Record the immutable git baseline SHA.
3. Explore the current codebase before proposing implementation details. Never infer repository
   facts from the PRD.
4. Detect PRD ambiguity, repository conflicts, and specification drift.
5. Produce repository-grounded `PLAN.md`.
6. Split implementation into phases and WORK items using the Work Item Contract.
7. **Write into each WORK item what you learned so the Executor does not have to relearn it.**
   - `context`: repository facts you verified, including what must not change and why.
   - `premise_checks`: the specific facts to re-confirm at HEAD before editing. Mandatory for
     `high` and `critical` risk.
   - `pitfalls`: the mistakes an executor is likely to make here, and their symptoms.
   An item whose objective is a title and whose body is empty pushes the whole planning cost back
   onto execution, where there is less context to spend.
8. Build explicit dependencies and requirement traceability. Register a transferred requirement in
   the receiving phase through `transfer.to`.
9. Set phase entries with zero-padded keys, and pin each phase's diff range with
   `devflow phase ref` once its branch exists.
10. Record unresolved human decisions in `DECISIONS.md` and STATE.
11. Add domain traps you discovered to `PITFALLS.md`.
12. Run DevFlow validation and correct structural errors.
13. Set STATE so `status` can compute the next action.

Do not create separate task Markdown documents or handoff prompts.
