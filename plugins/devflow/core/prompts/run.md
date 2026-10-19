# Executor packet

Operate in Executor mode.
Execute exactly one selected WORK item.
The item, the protocol documents, and the domain's pitfalls are appended below.

This packet is emitted only for the exact WORK item in the computed next action.
Re-run `devflow status` instead of selecting a different ready item.

1. Read the selected WORK contract, its `context`, its `pitfalls`, and the linked PRD/PLAN sections.
   1. Read `PITFALLS.md` before touching anything.
   2. Follow any `origin.technical_decisions` and `origin.policy_assumptions` links to DECISIONS.md. Provisional policy allows the stated reversible implementation only, not contract approval or bypass of `decision_dependencies`.
2. **Work through `premise_checks` against current HEAD before editing.**
   1. Each entry names a fact to confirm.
   2. If one is false, the premise moved: that is a stop condition, not a puzzle to solve.
3. Stop on a declared stop condition, unresolved decision, or required scope expansion.
   1. Run `devflow work block` with the reason rather than improvising.
4. Establish the failing test or verification criterion first, where the change admits one.
5. Make the smallest coherent change that satisfies the contract. Stay inside `scope.allowed`.
6. Run every version 2 verification command needed to cover the selected acceptance IDs, plus repository-required checks.
   1. Verify API and end-to-end criteria at an observable contract layer; a static source search alone is not runtime behavior evidence.
7. Record commit, changed files, commands with their results, deviations, and discoveries in `evidence`.
   1. Keep executed results in `evidence.commands`; the verification mapping does not replace them.
   2. A command's result means what it printed, not what you expected it to print.
8. Mark the item `done` only when acceptance criteria are supported by evidence.
   1. `devflow work done` refuses a completion with no recorded command.
   2. High and critical completed WORK then waits for its initial work audit before dependents run.
9. If you discovered a trap that outlives this item, add it to `PITFALLS.md`.
10. Validate DevFlow artifacts before returning.

Keep unrelated code outside the WORK boundary.
The required branch PR and Postman files are explicit delivery outputs; lifecycle evidence remains in WORK.

## Required source and branch handoff

Adopt active legacy domains with `devflow delivery enable <domain>`. Start only a ready WORK.
Resume `in_progress` WORK without rerunning `work start` or replacing its recorded `evidence.start_sha` and `evidence.delivery.branch`.
Commit verified source/tests, record meaningful source comments (or an explicit docs-only exception), then refresh cumulative PR and Postman outputs at `devflow delivery paths <domain>`.
Follow the appended `core/protocol/delivery-artifacts.md` for fields, coverage, provenance and private outputs. The Executor never publishes, pushes or merges on the user's behalf.
When the runtime selects `finalize`, run `devflow render finalize <domain>`; `core/protocol/finalization.md` owns the actual `delivery newman` server lifecycle and ELI5 evidence.
