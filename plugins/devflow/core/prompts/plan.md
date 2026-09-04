# Architect packet

Operate in Architect mode. The protocol documents and the domain's accumulated pitfalls are
appended below; everything you need is in this packet.

This packet is emitted only when `plan` is the computed next action. Re-run `devflow status` instead
of rendering or executing another lifecycle action.

1. Read the approved PRD, the repository-enforced rules, and `PITFALLS.md`.
2. Record the immutable git baseline SHA.
3. Explore the current codebase before proposing implementation details. Never infer repository
   facts from the PRD.
4. Detect PRD ambiguity, repository conflicts, and specification drift.
5. Produce repository-grounded `PLAN.md`.
6. Split implementation into phases and WORK items using the Work Item Contract. Create every new
   WORK document as version 2. Give each acceptance criterion and verification command a unique,
   nonblank item-local ID, and map every command to one or more criterion IDs through `covers`.
   Every criterion must be covered.
7. **Write into each WORK item what you learned so the Executor does not have to relearn it.**
   - `context`: repository facts you verified, including what must not change and why.
   - `premise_checks`: the specific facts to re-confirm at HEAD before editing. Mandatory for
     `high` and `critical` risk.
   - `pitfalls`: the mistakes an executor is likely to make here, and their symptoms.
   An item whose objective is a title and whose body is empty pushes the whole planning cost back
   onto execution, where there is less context to spend.
8. Build explicit dependencies and requirement traceability. Register a transferred requirement in
   the receiving phase through `transfer.to`.
9. Preserve finding semantics when turning an audit finding into WORK. Keep the expected event and
   outcome in objective and acceptance. Link both directions through the audit disposition and
   `origin.findings`; explain any multi-finding WORK in `origin.aggregation_reason`. Map each
   criterion to verification at the layer where its outcome is observable. A static source search
   alone does not verify API or end-to-end behavior.
10. Set phase entries with zero-padded keys, and pin each phase's diff range with
   `devflow phase ref` once its branch exists.
11. Record unresolved human decisions in `DECISIONS.md` and STATE. Do not create ready code-changing
    WORK until the decision is resolved.
12. Add domain traps you discovered to `PITFALLS.md`.
13. Run DevFlow validation and correct structural errors.
14. Set STATE so `status` can compute the next action.

For a high-risk domain, leave plan review pending until its initial plan audit is verified. The
runtime reports the next action but does not autonomously orchestrate execution or review.

Do not create separate task Markdown documents or handoff prompts.
