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

## WORK versions and verification coverage

Architects and auditors create new WORK documents with `version: 2`. Version 2 gives every acceptance criterion and verification command a stable item-local ID:

```yaml
version: 2
items:
  - id: P01-I01
    acceptance:
      - id: AC-P01-I01-01
        criterion: The billing API returns the persisted invoice.
    verification:
      commands:
        - id: V-P01-I01-01
          command: ./gradlew integrationTest --tests '*BillingApiIT*'
          covers: [AC-P01-I01-01]
```

Within one item, acceptance IDs and verification command IDs are unique and nonblank.
Criteria and commands are nonblank.
Every command covers at least one acceptance ID, every referenced acceptance ID exists, and every acceptance criterion is covered by at least one command.
Do not mix the legacy string shape into a version 2 document.

Choose commands that verify each criterion at the layer where its outcome is observable.
API and end-to-end behavior requires a controller, API integration, browser, or equivalent contract check.
A static source search alone does not establish that runtime behavior.
The runtime validates the declared mapping but does not infer whether a command is technically sufficient.

Record executed command results in the existing `evidence.commands` list.
Coverage declarations do not replace execution evidence.

## The item must carry what the Architect learned

The Architect reads the repository.
The Executor does not get to repeat that reading, and an item that omits what was learned forces it to re-derive the same facts with less context and get them wrong.
Three fields carry that knowledge.
They are the difference between a task the Executor can execute and a title it has to reverse-engineer.

### `context`

Repository facts already verified during planning, each naming the class, file, or migration that carries it.
Include the facts that say what must **not** change when nearby code invites the change.

> `RecurringBillingService.findDueForRecurringBilling` does not include suspended subscriptions, so they never enter the scheduler.
> Do not widen that entry condition.

### `premise_checks`

The first execution step: specific facts to re-confirm at current HEAD before editing.
Name the method, condition, or number to look at and what you expect to find.
If one is false, the premise moved, which is a stop condition rather than a puzzle to solve.

Mandatory for `high` and `critical` risk. `validate` rejects the item without it.

### `pitfalls`

Known failure modes for this specific change.
Each entry names the mistake and the symptom it produces, so the failure is recognizable rather than merely forbidden.

> Duplicating the result-application logic into a new class splits reconciliation, and the existing stuck-record sweeper then mishandles the rows this path creates.
> Reuse the existing applier.

Domain-wide traps belong in `PITFALLS.md`. Only change-specific ones belong here.

## Transfers

A requirement that moves to another phase must be registered in the phase that receives it.
Recording the move only in prose leaves it invisible in both manifests, and it stays invisible until an integration audit finds it much later.

```yaml
status: transferred
transfer:
  to: P08-I03
  requirements: [REQ-014]
```

`validate` checks that `transfer.to` exists and that the target carries the same `origin.requirements`.

## Execution rules

- Dependency order outranks severity. Severity sorts items only inside the same dependency level.
- Re-verify every task premise against current code before editing. `premise_checks` is that list.
- Establish the failing test or verification criterion before implementing, where the change admits one.
- Make the smallest coherent change that satisfies the contract.
- Stop instead of expanding scope when a stop condition is met.
- Record deviations and discoveries in evidence; do not hide them in prose elsewhere.
- A discovery that generalizes beyond this item belongs in `PITFALLS.md`, not only in evidence.
- General implementation and remediation use the same schema. Distinguish them with `kind` and `origin.findings`.

## Finding traceability

`remediation`, `evidence`, and `documentation` WORK require nonempty `origin.findings`.
One finding per WORK is the default.
When one WORK covers two or more findings, add a nonblank `origin.aggregation_reason` explaining the shared root cause, change and rollback boundary, and verification set.
The audit disposition and WORK origin links must match in both directions.
Unknown finding and WORK IDs are invalid.

The finding classification fixes the generated WORK kind:

| Finding classification | Disposition action   | WORK kind       |
| ---------------------- | -------------------- | --------------- |
| `CONFIRMED`            | `remediation_work`   | `remediation`   |
| `EVIDENCE_REQUIRED`    | `evidence_work`      | `evidence`      |
| `DOCUMENTATION_DRIFT`  | `documentation_work` | `documentation` |

`DECISION_REQUIRED` creates no WORK while unresolved.
Its decision IDs are recorded in `DECISIONS.md` and registered in STATE by audit apply.
A later WORK for the selected path records the resolved ID in `decision_dependencies`.

## Completion

`done` requires evidence, not assertion.
`validate` and `devflow work done` both refuse a completion with no `evidence.commands`, except for `kind: documentation`.
Record the command and its result, not a claim that it passed.

The runtime also requires `in_progress` before `done`.
A high or critical implementation completion records a pending required review unless WORK already contains a later valid review state.
`start` only accepts ready WORK after dependency, decision, phase, and required plan-review gates pass.
`block` only accepts ready or in-progress WORK and requires a non-empty reason.

## Backward compatibility

Version 1 WORK keeps its string lists under `acceptance` and `verification.commands`.
The runtime normalizes that shape for reading and preserves its lifecycle without rewriting it to version 2.

`review` is optional for existing WORK.
The runtime reads legacy high or critical done WORK as requiring review before a dependent starts, without requiring an artifact migration.
New high and critical WORK should record the review metadata explicitly.

## Protocol 1.6 delivery evidence

When `STATE.delivery` is enabled, every new completion obeys `delivery-artifacts.md`.
`work start` records `evidence.start_sha`.
Before completion, commit source/tests, record source comment anchors and intent, and generate the cumulative branch PR and Postman outputs.
`work done` requires current HEAD, refuses uncommitted executable source, derives changed files, and validates source-comment existence and delivery provenance in the existing atomic transaction.
Semantic usefulness and API correctness remain audited.
No executable change requires an explained `comments_note`; no HTTP surface requires an explained empty collection.

The two derived output files plus existing STATE/WORK evidence receive a narrow allowance for older scope lists.
Already-done WORK snapshotted by `delivery enable` remains intact; ready and in-progress WORK adopts the new obligations.
One selected WORK per invocation remains the boundary.

## Protocol 1.8 Newman repairs

A confirmed code/collection failure becomes normal integration remediation WORK.
Its `origin.findings` contains `NEWMAN-<run-id>` and its `references` includes that run's sanitized summary.
Define bounded files, accepted contract, failing reproduction, regression coverage and risk.
Register it using `delivery triage`; then follow ordinary start, commit, delivery and done.
Preserve the evidence of previously completed WORK.
For a collection defect with ignored derived JSON, commit a meaningful tracked regression fixture/test or generator correction.
Environment failures keep setup evidence and reruns, with no speculative code repair commit.
