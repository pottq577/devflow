# DevFlow lifecycle

DevFlow exposes four operations:

- `plan`: Architect mode. Convert an approved PRD into a repository-grounded PLAN, phase manifests, decisions, and STATE.
- `run`: Executor mode. Execute exactly one ready WORK item and record evidence.
- `audit`: Auditor mode. Independently verify plan, phase, or integration scope. Confirmed findings create remediation WORK.
- `status`: Deterministic state inspection. Compute the next action from STATE and WORK.

## Lifecycle

```text
PRD
 -> plan
 -> optional plan audit for high-risk work
 -> run phase work
 -> audit phase
 -> run remediation
 -> audit phase --mode closure
 -> next phase
 -> audit integration
 -> run integration remediation
 -> audit integration --mode closure
 -> VERIFIED
```

Return to the human/Chat layer only for product-policy decisions, scope changes, conflicting requirements, or deliberately requested third-party review.

## Artifact budget

Project artifacts are limited to:

| Artifact | Holds |
| --- | --- |
| `PRD.md` | Product and domain contract. No repository paths, commit boundaries, or phase decomposition. |
| `PLAN.md` | Repository-grounded implementation strategy, phase graph, traceability. |
| `STATE.yaml` | Lifecycle position. Machine-owned; the CLI computes `next_action` from it. |
| `PITFALLS.md` | Accumulated domain traps and context that no amount of state can compute. |
| `DECISIONS.md` | Human and product decisions, when any exist. |
| `work/*.yaml` | Every executable change, general and remediation alike. |
| `audits/*.md` | One file per audit scope. |

Do not create separate task Markdown files, handoff documents, remediation plans, focused-review
documents, integration-test plans, or prompt handoff documents. STATE and the CLI reconstruct the
next action.

### Why PITFALLS is a separate artifact

A handoff document has two halves. The first half is lifecycle position, and `status` reproduces it
exactly. The second half is knowledge the project accumulated the hard way: a test double that
always succeeds, a method that no-ops instead of raising, a verification command that skips the
suite it appears to run, the next free migration number, a behavior that looks like a bug but is a
recorded decision.

No state machine can derive that. Deleting the handoff document without giving this half a home
is how the next session repeats an incident the last one already paid for. `plan`, `run`, and
`audit` all load `PITFALLS.md`, so the cost of writing an entry is paid once and returned every
session after.

Entries earn their place by having cost something. Remove one when the trap is actually gone.
