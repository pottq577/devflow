# Executor packet

Operate in Executor mode. Execute exactly one selected WORK item.

1. Re-read the selected WORK contract and linked PRD/PLAN sections.
2. Re-verify the item's assumptions in current code.
3. Stop on a declared stop condition, unresolved decision, or required scope expansion.
4. Make the smallest coherent change that satisfies the contract.
5. Run the specified verification plus repository-required checks.
6. Record commit, changed files, commands/results, deviations, and discoveries in `evidence`.
7. Mark the item `done` only when acceptance criteria are supported by evidence.
8. Validate DevFlow artifacts before returning.

Do not redesign unrelated code and do not create additional narrative completion documents.
