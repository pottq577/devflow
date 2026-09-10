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
6. Run every version 2 verification command needed to cover the selected acceptance IDs, plus
   repository-required checks. Verify API and end-to-end criteria at an observable contract layer;
   a static source search alone is not runtime behavior evidence.
7. Record commit, changed files, commands with their results, deviations, and discoveries in
   `evidence`. Keep executed results in `evidence.commands`; the verification mapping does not
   replace them. A command's result means what it printed, not what you expected it to print.
8. Mark the item `done` only when acceptance criteria are supported by evidence. `devflow work done`
   refuses a completion with no recorded command.
   High and critical completed WORK then waits for its initial work audit before dependents run.
9. If you discovered a trap that outlives this item, add it to `PITFALLS.md`.
10. Validate DevFlow artifacts before returning.

Keep unrelated code outside the WORK boundary. The required branch PR and Postman files are
explicit delivery outputs; lifecycle evidence remains in WORK.

## Required source and branch handoff

Before implementation, adopt legacy active work through `devflow delivery enable <domain>`.
Start a ready WORK with `work start`; resume an `in_progress` WORK without starting it again or
changing its recorded `start_sha`.
Record meaningful comments in changed source and their `evidence.comments` path/line/reason.
For pure docs/config/deletions, give the concrete `comments_note` exception. Commit verified source
and tests; then update the cumulative branch PR from `docs/PR/templates.md` and Postman v2.1 JSON
at `devflow delivery paths <domain>` outputs. Fill `evidence.delivery` and source metadata before
`work done --commit HEAD`. Keep credential values empty, declare API coverage and preserve prior
branch requests. All output fields and validation rules appear in the appended delivery protocol.
The branch output allowance covers these files and STATE/WORK evidence. After the runtime selects
`finalize`, render that action and follow the appended whole-work ELI5/Newman protocol. Generation
itself sends no requests; the finalization step explicitly executes authorized isolated tests.
Keep remote PR publication and push/merge under user control.
