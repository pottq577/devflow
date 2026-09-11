# DevFlow lifecycle

DevFlow exposes four operations:

- `plan`: Architect mode. Convert an approved PRD into a repository-grounded PLAN, phase manifests, decisions, and STATE.
- `run`: Executor mode. Execute exactly one ready WORK item and record evidence.
- `audit`: Auditor mode. Independently verify plan, work, phase, or integration scope. Confirmed findings create remediation WORK.
- `status`: Deterministic state inspection. Refresh `target_sha`, `next_action`, `project_status`, and `active_phase` from STATE and WORK.

## Lifecycle

`STATE.yaml` records `workflow_type: delivery|audit_remediation`.
Existing STATE without this field reads as `delivery` without a migration write.
New domains select the workflow with `devflow init <domain> --workflow delivery|audit-remediation`.

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
 -> whole-work ELI5 and Newman finalization (when enabled)
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

Empty phases are valid throughout this workflow.
Unresolved decisions outrank executable remediation.
After all integration remediation WORK is terminal and every required work review is verified, the next action is integration closure.
A verified integration reaches project complete even while its integration WORK manifest remains present.

A required plan review uses `status: remediation` and records `remediation_work_ids` after an initial audit that requires follow-up.
Legacy `pending` state without this field remains readable.
While remediation is active, only the linked remediation or evidence WORK may run.
When those items and their required reviews are terminal, the next action is the plan closure audit.
A passing closure marks the plan review verified and releases ordinary planned WORK.

An audit finding with `disposition.action: stop` blocks its audited plan, WORK, phase, or integration scope and projects a human decision.
It never loops directly back to closure and never releases other remediation until the specification conflict is resolved and the scope is audited again.
Every scope has a command that returns it to a fresh initial audit once the conflict is resolved: `plan-review set <domain> pending`, `work review <domain> <WORK-ID> pending`, `phase set <domain> <phase> audit`, and `integration set <domain> audit`.

Independent low and medium WORK remains batch-reviewed in the phase audit.
A work audit uses `--scope work --task <WORK-ID>` and `--mode initial|closure`; plan, phase, and integration audits use those same modes at their own scope.
The runtime computes the next action from STATE and WORK, but it does not autonomously execute, audit, remediate, or orchestrate those actions.

Return to the human/Chat layer only for product-policy decisions, scope changes, conflicting requirements, or deliberately requested third-party review.

`refresh_state()` owns those derived fields.
Mutation commands update authoritative lifecycle state and then refresh the projection; status writes STATE only when that projection changed.
Render first computes the expected action without writing, rejects any mismatch, and refreshes STATE only for an accepted request.

## Audit apply

`devflow audit apply` is the protocol 1.3 transition boundary for completed audits.
It accepts only the exact computed scope, mode, phase, and WORK target, then reads the canonical audit Markdown named by STATE or WORK.
The command validates its YAML front matter, verdict, links, lifecycle prerequisites, and closure coverage before any mutation.
Invalid input exits with code `2` and leaves STATE, WORK, DECISIONS, and audit artifacts unchanged.

On success, the command registers new unresolved decision IDs, updates the audited lifecycle scope, records the applied finding set as machine-owned `audit_provenance.findings` on that scope's own metadata, and computes derived fields against prospective STATE and WORK before writing.
Closure provenance is machine-owned: no lifecycle artifact's history is delegated to Git, and a later closure recovers the prior finding set from `audit_provenance.findings`, not from `git log` or `git show`.
A closure also records the previous mapping in `audit_provenance.applied_against`, so `validate` can recheck the persisted closure after `findings` advances for the next closure.
Existing records without `applied_against` remain readable.
When both STATE and WORK change, same-directory backups preserve the original bytes before commit; a commit writer failure restores replaced files through an independent rename path.
This is process-local failure rollback, not crash recovery or concurrent-writer isolation.
Linked remediation remains ordinary WORK and becomes executable only after the outcome is applied.
Existing protocol 1.2 and older `plan-review set`, `work review`, `phase set`, and `integration set` transitions remain readable.
Protocol 1.3 and newer verified transitions must use `audit apply`, so the legacy commands cannot bypass metadata validation.
When `.devflow/config.yaml` exists, its `protocol_version` is a floor: the audit-apply gate decides from the higher of the STATE and config versions, and `validate` errors when STATE declares an older protocol than the config.
Hand-editing `STATE.protocol_version` downward cannot re-enable a legacy verified transition on a project that `init` recorded at 1.3 or newer.
A project with no config file, or one whose config genuinely records the older version, keeps the legacy path.

## Render guards

`render` emits a packet only for the exact action computed from current STATE and WORK.

- `render plan` requires the next command to be `plan`.
- `render run` requires `run` and the exact next WORK id.
- `render audit` requires the exact scope, mode, phase, and WORK id, with absent targets compared as null.

Phase numbers are normalized before comparison, and a work audit derives its phase from the selected WORK when `--phase` is omitted.

A mismatch exits with code `2`, writes no packet to stdout, and reports both requested and expected actions on stderr with a `devflow status <domain>` hint.
Render does not create audit directories or other lifecycle artifacts.
An accepted render retains the existing derived STATE write contract.

## Peer skill composition

The DevFlow lifecycle stays authoritative even when peer skills are active.
WORK selection, STATE transitions, review gates, remediation scheduling, and completion decisions remain DevFlow's.
Optional peer execution disciplines and minimization guidance compose inside the current lifecycle boundary according to `core/protocol/skill-composition.md`, and a missing peer plugin never blocks a DevFlow command.

## Runtime transition guards

Mutation commands reject invalid transitions with exit code `2` before writing STATE or WORK.
Every mutation command projects its prospective STATE, and any WORK it changes, on copies and then commits the changed documents through one transaction, mirroring `audit apply`.
A command that exits non-zero has written nothing, including when the derived-state projection itself raises on structurally invalid input.
This is process-local failure rollback, not crash recovery or concurrent-writer isolation.

- `work start` requires ready status, completed dependencies with required reviews verified, resolved decisions, an unverified containing phase, and a verified required plan review. Integration WORK also waits for all project phases.
- `work done` requires `in_progress` and completion evidence. `work block` is limited to `ready` and `in_progress` with a non-empty reason.
- `work review pending` is accepted when the current effective review status is `blocked`, or when a legacy `remediation` review has no `audit_provenance`. It clears `remediation_work_ids` and returns the review to `pending` so the WORK can be re-audited. A remediation review with provenance cannot use this reset. The command never sets a review verified and is not gated on `audit apply`.
- A verified plan review requires `PLAN.md` and its audit artifact. Required plan reviews cannot be skipped.
- A phase verification requires terminal phase WORK, completed high-risk WORK reviews, a diff range, a phase audit artifact, and no unresolved phase decision. Verified phases cannot be reopened through `phase set`.
- Integration verification requires verified phases, terminal integration WORK, completed high-risk integration WORK reviews, its audit artifact, and no unresolved project decision. Verified integration cannot be reopened through `integration set`.
- Both verifications additionally require the domain to pass `validate`. A structurally broken WORK manifest cannot ride through to project completion, and the refusal names each validation error.
- `phase set` and `phase ref` act on a phase already present in STATE, or on one whose `work/phase-XX.yaml` exists. Neither invents a phase entry, because a mistyped number would block integration for good.

## Backward-readable artifacts

Existing WORK with no `review` field remains readable.
A legacy high or critical done WORK is treated as pending required review before a dependent can start, without rewriting that WORK merely to normalize it.
Existing `plan_review` metadata without `audit_file` defaults to `audits/plan.md`.
No migration command is required because the runtime supplies these defaults while reading.

### Closure without recorded provenance

A closure audit reads its prior finding set from `audit_provenance`, recorded by the initial `audit apply` for that scope.
A project that predates machine-owned provenance, or whose STATE was reset, has none, so the closure is refused rather than evaluated against an empty prior set.
There is no bulk migration. Recover the one affected scope in place:

1. Return the scope to a fresh initial audit with its recovery command:
   1. `plan-review set <domain> pending`, `work review <domain> <WORK-ID> pending`, `phase set <domain> <phase> audit`, or `integration set <domain> audit`.
   2. Plan and work recovery clear their stale `remediation_work_ids`; work recovery accepts a legacy `remediation` review only when it has no provenance.
2. Re-render the initial audit packet: `devflow render audit <domain> --scope <scope> ... --mode initial`.
3. Rewrite the canonical audit file's front matter back to `mode: initial` with its original findings, then `devflow audit apply <domain> --scope <scope> ... --mode initial`.
   1. This records the provenance.
4. Rewrite the canonical audit file as the closure again and re-run `audit apply --mode closure`.

## Artifact budget

Lifecycle records and their prescribed delivery outputs are:

| Artifact                                                                     | Holds                                                                                        |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `PRD.md`                                                                     | Product and domain contract. No repository paths, commit boundaries, or phase decomposition. |
| `PLAN.md`                                                                    | Repository-grounded implementation strategy, phase graph, traceability.                      |
| `STATE.yaml`                                                                 | Lifecycle position. Machine-owned; the CLI computes `next_action` from it.                   |
| `PITFALLS.md`                                                                | Accumulated domain traps and context that no amount of state can compute.                    |
| `DECISIONS.md`                                                               | Human and product decisions, when any exist.                                                 |
| `work/*.yaml`                                                                | Every executable change, general and remediation alike.                                      |
| `audits/*.md`                                                                | One file per audit scope.                                                                    |
| `docs/PR/<domain-slug-hash>/<branch-slug-hash>.md`                           | Cumulative local PR body derived from the consuming project template.                        |
| `docs/postman/<domain-slug-hash>/<branch-slug-hash>.postman_collection.json` | Cumulative importable collection for the delivered branch.                                   |

Do not create separate task Markdown files, handoff documents, remediation plans, focused-review documents, integration-test plans, or prompt handoff documents.
STATE and the CLI reconstruct the next action.

### Why PITFALLS is a separate artifact

A handoff document has two halves.
The first half is lifecycle position, and `status` reproduces it exactly.
The second half is knowledge the project accumulated the hard way: a test double that always succeeds, a method that no-ops instead of raising, a verification command that skips the suite it appears to run, the next free migration number, a behavior that looks like a bug but is a recorded decision.

No state machine can derive that.
Deleting the handoff document without giving this half a home is how the next session repeats an incident the last one already paid for. `plan`, `run`, and `audit` all load `PITFALLS.md`, so the cost of writing an entry is paid once and returned every session after.

Entries earn their place by having cost something.
Remove one when the trap is actually gone.

## Protocol 1.6 branch delivery gate

New domains carry `delivery.version: 1`. `delivery enable` adopts legacy domains idempotently, preserving completed WORK; plan/run invokes this preflight.
The exact source-comment and per-branch PR/Postman contract is `delivery-artifacts.md`.
Derived artifacts use existing STATE/WORK provenance, so the lifecycle controller and four role operations remain unchanged.

`work done` validates delivery before its atomic commit.
Domain validation checks all recorded branch outputs; verified integration also checks extant branch tips.
`delivery refresh` repairs artifact-only changes at the same source HEAD.
New source commits use ordinary WORK.
Local output paths under `docs/PR/` and `docs/postman/` are permitted additions to the lifecycle artifact budget.

## Protocol 1.8 whole-work delivery gate

The computed executor action `finalize` aggregates the entire domain before integration handoff and after integration remediation.
It produces one installed-ELI5 HTML and actual per-branch Newman receipts under `finalization.md`.
Confirmed API failures register traced integration remediation WORK; that work executes through normal dependency, commit and review gates. `delivery finalize` records a fresh receipt and releases the existing independent integration audit.
It never marks integration verified itself.
A phase-free initial audit can first discover implementation work.

New derived artifacts are `docs/explanations/<domain-slug-hash>/implementation.html` and sanitized `docs/postman/<domain-slug-hash>/newman/<run-id>.summary.json`.
Raw responses stay in locally Git-excluded `.devflow/private/newman/<run-id>/` through closure.
`delivery newman` persists run results even when returning nonzero; rejected lifecycle transitions still preserve STATE/WORK.
`delivery newman` owns the server argv process group, HTTP 200..299 readiness, Newman execution and
bounded SIGTERM/SIGKILL cleanup. Finalization requires the ordered lifecycle and owned-process
liveness evidence. Only a collection with no HTTP requests and no declared endpoints may be
`not_applicable`.
The optional `delivery.finalization` field is adopted idempotently with `delivery enable`.

`status` can report `next.command: finalize`; `render finalize` supplies its entire-domain packet.
`next` remains the one-WORK selector and returns nonzero when the next action is finalization.
