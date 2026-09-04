# Executor packet

Operate in Executor mode. Execute exactly one selected WORK item. The item, the protocol documents,
and the domain's pitfalls are appended below.

This packet is emitted only for the exact WORK item in the computed next action. Re-run
`devflow status` instead of selecting a different ready item.

1. Read the selected WORK contract, its `context`, its `pitfalls`, and the linked PRD/PLAN sections.
   Read `PITFALLS.md` before touching anything.
2. **Work through `premise_checks` against current HEAD before editing.** Each entry names a fact to
   confirm. If one is false, the premise moved: that is a stop condition, not a puzzle to solve.
3. Stop on a declared stop condition, unresolved decision, or required scope expansion. Run
   `devflow work block` with the reason rather than improvising.
4. Establish the failing test or verification criterion first, where the change admits one.
5. Make the smallest coherent change that satisfies the contract. Stay inside `scope.allowed`.
6. Run the specified verification plus repository-required checks.
7. Record commit, changed files, commands with their results, deviations, and discoveries in
   `evidence`. A command's result means what it printed, not what you expected it to print.
8. Mark the item `done` only when acceptance criteria are supported by evidence. `devflow work done`
   refuses a completion with no recorded command.
   High and critical completed WORK then waits for its initial work audit before dependents run.
9. If you discovered a trap that outlives this item, add it to `PITFALLS.md`.
10. Validate DevFlow artifacts before returning.

Do not redesign unrelated code and do not create additional narrative completion documents.
