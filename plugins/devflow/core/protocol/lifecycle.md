# DevFlow lifecycle

DevFlow exposes four operations:

- `plan`: Architect mode. Convert an approved PRD into a repository-grounded PLAN, phase manifests, decisions, and STATE.
- `run`: Executor mode. Execute exactly one ready WORK item and record evidence.
- `audit`: Auditor mode. Independently verify plan, work, phase, or integration scope. Confirmed findings create remediation WORK.
- `status`: Deterministic state inspection. Refresh `target_sha`, `next_action`, `project_status`, and `active_phase` from STATE and WORK.

## Lifecycle

`STATE.yaml` records `workflow_type: delivery|audit_remediation`. Existing STATE without this field
reads as `delivery` without a migration write. New domains select the workflow with
`devflow init <domain> --workflow delivery|audit-remediation`.

The delivery workflow keeps the phase-based lifecycle:

```text
PRD
 -> plan
 -> optional required plan audit for high-risk domain
 -> run WORK
 -> high/critical WORK initial audit before dependents
 -> remediation WORK when a finding is confirmed
 -> high/critical WORK closure audit
 -> dependent WORK release
 -> phase initial audit
 -> phase remediation
 -> phase closure audit
 -> next phase
 -> integration initial audit
 -> integration remediation
 -> integration closure audit
 -> integration verified
 -> project complete
```

The audit/remediation workflow starts without fake phases:

```text
integration initial audit
 -> decision resolution and/or integration remediation WORK
 -> required WORK-level review
 -> integration closure audit
 -> integration verified
 -> project complete
```

Independent low and medium WORK remains batch-reviewed in the phase audit. A work audit uses
`--scope work --task <WORK-ID>` and `--mode initial|closure`; plan, phase, and integration audits
use those same modes at their own scope. The runtime computes the next action from STATE and WORK,
but it does not autonomously execute, audit, remediate, or orchestrate those actions.

Return to the human/Chat layer only for product-policy decisions, scope changes, conflicting requirements, or deliberately requested third-party review.

`refresh_state()` owns those derived fields. Mutation commands update authoritative lifecycle state and then refresh the projection; status writes STATE only when that projection changed. Render first computes the expected action without writing, rejects any mismatch, and refreshes STATE only for an accepted request.

## Render guards

`render` emits a packet only for the exact action computed from current STATE and WORK. `render plan`
requires the next command to be `plan`. `render run` requires `run` and the exact next WORK id.
`render audit` requires the exact scope, mode, phase, and WORK id, with absent targets compared as
null. Phase numbers are normalized before comparison, and a work audit derives its phase from the
selected WORK when `--phase` is omitted.

A mismatch exits with code `2`, writes no packet to stdout, and reports both requested and expected
actions on stderr with a `devflow status <domain>` hint. Render does not create audit directories or
other lifecycle artifacts. An accepted render retains the existing derived STATE write contract.

## Peer skill composition

The DevFlow lifecycle stays authoritative even when peer skills are active. WORK selection, STATE
transitions, review gates, remediation scheduling, and completion decisions remain DevFlow's.
Optional peer execution disciplines and minimization guidance compose inside the current
lifecycle boundary according to `core/protocol/skill-composition.md`, and a missing peer plugin
never blocks a DevFlow command.

## Runtime transition guards

Mutation commands reject invalid transitions with exit code `2` before writing STATE or WORK.

- `work start` requires ready status, completed dependencies with required reviews verified, resolved decisions, an unverified containing phase, and a verified required plan review. Integration WORK also waits for all project phases.
- `work done` requires `in_progress` and completion evidence. `work block` is limited to `ready` and `in_progress` with a non-empty reason.
- A verified plan review requires `PLAN.md` and its audit artifact. Required plan reviews cannot be skipped.
- A phase verification requires terminal phase WORK, completed high-risk WORK reviews, a diff range, a phase audit artifact, and no unresolved phase decision. Verified phases cannot be reopened through `phase set`.
- Integration verification requires verified phases, terminal integration WORK, completed high-risk integration WORK reviews, its audit artifact, and no unresolved project decision. Verified integration cannot be reopened through `integration set`.
- Both verifications additionally require the domain to pass `validate`. A structurally broken WORK manifest cannot ride through to project completion, and the refusal names each validation error.
- `phase set` and `phase ref` act on a phase already present in STATE, or on one whose `work/phase-XX.yaml` exists. Neither invents a phase entry, because a mistyped number would block integration for good.

## Backward-readable artifacts

Existing WORK with no `review` field remains readable. A legacy high or critical done WORK is
treated as pending required review before a dependent can start, without rewriting that WORK merely
to normalize it. Existing `plan_review` metadata without `audit_file` defaults to `audits/plan.md`.
No migration command is required because the runtime supplies these defaults while reading.

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
