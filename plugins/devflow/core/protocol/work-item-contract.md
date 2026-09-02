# WORK item contract

A WORK item is one independently verifiable change boundary. It has:

- one objective,
- one independent completion decision,
- one rollback boundary,
- one verification set.

File count and architectural layer count are not splitting criteria.

Every executable item must include:

- stable ID,
- kind,
- origin links to requirements/findings/plan items,
- dependencies and decision dependencies,
- objective,
- allowed and forbidden scope,
- concrete requirements,
- verification commands,
- acceptance criteria,
- stop conditions,
- risk metadata,
- status,
- evidence fields.

## The item must carry what the Architect learned

The Architect reads the repository. The Executor does not get to repeat that reading, and an item
that omits what was learned forces it to re-derive the same facts with less context and get them
wrong. Three fields carry that knowledge. They are the difference between a task the Executor can
execute and a title it has to reverse-engineer.

### `context`

Repository facts already verified during planning, each naming the class, file, or migration that
carries it. Include the facts that say what must **not** change when nearby code invites the change.

> `RecurringBillingService.findDueForRecurringBilling` does not include suspended subscriptions, so
> they never enter the scheduler. Do not widen that entry condition.

### `premise_checks`

The first execution step: specific facts to re-confirm at current HEAD before editing. Name the
method, condition, or number to look at and what you expect to find. If one is false, the premise
moved, which is a stop condition rather than a puzzle to solve.

Mandatory for `high` and `critical` risk. `validate` rejects the item without it.

### `pitfalls`

Known failure modes for this specific change. Each entry names the mistake and the symptom it
produces, so the failure is recognizable rather than merely forbidden.

> Duplicating the result-application logic into a new class splits reconciliation, and the existing
> stuck-record sweeper then mishandles the rows this path creates. Reuse the existing applier.

Domain-wide traps belong in `PITFALLS.md`. Only change-specific ones belong here.

## Transfers

A requirement that moves to another phase must be registered in the phase that receives it.
Recording the move only in prose leaves it invisible in both manifests, and it stays invisible until
an integration audit finds it much later.

```yaml
status: transferred
transfer:
  to: P08-I03
  requirements: [REQ-014]
```

`validate` checks that `transfer.to` exists and that the target carries the same
`origin.requirements`.

## Execution rules

- Dependency order outranks severity. Severity sorts items only inside the same dependency level.
- Re-verify every task premise against current code before editing. `premise_checks` is that list.
- Establish the failing test or verification criterion before implementing, where the change admits
  one.
- Make the smallest coherent change that satisfies the contract.
- Stop instead of expanding scope when a stop condition is met.
- Record deviations and discoveries in evidence; do not hide them in prose elsewhere.
- A discovery that generalizes beyond this item belongs in `PITFALLS.md`, not only in evidence.
- General implementation and remediation use the same schema. Distinguish them with `kind` and
  `origin.findings`.

## Completion

`done` requires evidence, not assertion. `validate` and `devflow work done` both refuse a completion
with no `evidence.commands`, except for `kind: documentation`. Record the command and its result,
not a claim that it passed.
