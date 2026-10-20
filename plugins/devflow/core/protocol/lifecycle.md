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

For work-level remediation, `review.remediation_work_ids` defines the parent audit's closure membership. It does not create execution dependencies between sibling remediation items. The scheduler follows each WORK item's `dependencies` and `decision_dependencies`, continues scanning other review chains when one remediation set is stalled, and can run independent WORK before the parent audit becomes closable.

An audit finding with `disposition.action: stop` blocks its audited plan, WORK, phase, or integration scope and projects a human decision.
It never loops directly back to closure and never releases other remediation until the specification conflict is resolved and the scope is audited again.
Every scope has a command that returns it to a fresh initial audit once the conflict is resolved: `plan-review set <domain> pending`, `work review <domain> <WORK-ID> pending`, `phase set <domain> <phase> audit`, and `integration set <domain> audit`.

External evidence or access is a separate wait from a product decision. Use `work wait-external <domain> <WORK-ID> --reason "..." --missing-evidence "..."` when the current session cannot verify a required fact. DevFlow keeps the WORK nonterminal as a backward-readable `blocked` item with `block_kind: external`, so only dependency edges that reach that WORK wait. Independent runnable WORK and eligible work-review closures continue.

When no executable or auditable action remains, an external wait projects `role: human`, `command: provide-evidence`, and the exact WORK id. It does not create a DECISION entry. After evidence arrives, use `work resume <domain> <WORK-ID> --reason "..."`. Use `work unblock` only for a normal execution block whose blocking condition has cleared.

Independent low and medium WORK remains batch-reviewed in the phase audit.
A work audit uses `--scope work --task <WORK-ID>` and `--mode initial|closure`; plan, phase, and integration audits use those same modes at their own scope.
The runtime computes the next action from STATE and WORK, but it does not autonomously execute, audit, remediate, or orchestrate those actions.

Return to the human/Chat layer for product-policy decisions, scope changes, conflicting requirements, deliberately requested third-party review, or concrete external evidence/access that DevFlow cannot obtain itself. Keep decision and evidence handoffs distinct.

`refresh_state()` owns those derived fields.
Mutation commands update authoritative lifecycle state and then refresh the projection; status writes STATE only when that projection changed.
Render computes the projection once without writing, rejects any mismatch, and persists that projection only for an accepted request. Status and render share one invocation-local WORK snapshot with their nested projection and output readers; later invocations and post-mutation projections read fresh sources.
`status --no-refresh` and `render <action> --no-refresh` compute the same current projection in memory and leave STATE untouched, including when HEAD has moved. The default commands retain the refresh behavior. This option avoids the STATE write; it does not provide an operating-system read-only guarantee for the process.

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
An accepted render retains the existing derived STATE write contract unless `--no-refresh` or `--check-only` is selected.
Hosted child commands pass `--expected-head <full-sha|unborn>` and `--expected-fingerprint <v2-fingerprint>` from the dispatch projection. Before writing STATE or emitting a packet, render checks the current action fingerprint and both projected and current HEAD. `unborn` explicitly pins the absence of a commit. A mismatch exits `2` without output or mutation; the child stops and returns the blocker to its parent instead of choosing another action.
`--check-only` runs the same guards and returns zero without STATE writes or packet output. Compact scout-backed children use it before their capsule; other children render once. Neither path needs an initial full status. Read-only roles keep `--no-refresh`; mutating children still run status after their lifecycle changes and return its receipt. Existing manual render calls without expected pins retain their prior behavior.

`render evidence <domain>` is a bounded read-only navigation projection, not an action packet. It prints the current action and fingerprint, the selected WORK objective, acceptance ids, verification commands, premise checks, pitfalls, references, changed files, comment anchor paths, commit and start SHA, block and external-wait reasons, recorded audit findings, the delivery branch, Newman and receipt index, and the exact paths of the original artifacts. The complete rendered response, including its Markdown wrapper, is limited to 32,768 UTF-8 bytes. Text fields and row collections also have individual limits. When the total budget is exceeded, the compact fallback preserves action pins, the selected blocker and original artifact paths; omitted evidence remains available in the named source files. It never inlines the action protocol, PRD, PLAN or WORK bodies, and it never states a lifecycle result. A read-only role that needs the action contract renders the matching action packet instead.

Its bounds are part of the contract and the projection reports them in `limits`. Cited text is kept up to 400 characters. The index includes up to the first 12 recorded verification rows and up to the first 40 rows for open WORK, unresolved decisions, delivery branches, Newman runs and WORK file lists. If the complete render exceeds 32,768 UTF-8 bytes, the compact fallback can include fewer rows while retaining action pins, the selected blocker and original artifact paths. Every shortened string reports its size and `truncated: true`, and each shortened list reports its `*_omitted` count. IDs, block reasons, failure-evidence availability, original artifact paths and full originals are preserved so a child can open omitted rows from the named source instead of guessing. The index never decides a lifecycle result.

Hosted Scout capsule binding and validation use the step-start evidence snapshot and current source fingerprints. `core/protocol/host-telemetry.md` owns the capsule provenance, freshness and fencing rules. An unbound or stale capsule cannot skip a routed Scout.

## Peer skill composition

The DevFlow lifecycle stays authoritative even when peer skills are active.
WORK selection, STATE transitions, review gates, remediation scheduling, and completion decisions remain DevFlow's.
Optional peer execution disciplines and minimization guidance compose inside the current lifecycle boundary according to `core/protocol/skill-composition.md`, and a missing peer plugin never blocks a DevFlow command.

## Automated execution surfaces

The `goal` and `autopilot` skills are execution drivers, not a second lifecycle.
They read the same computed `next_action` that `status` and `next` print, and they own no transition.

- A driver dispatches the action the runtime selected. It never selects a different WORK item, closes a review, or applies an audit on its own.
- `plan`, `run`, `audit`, and `finalize` retain their role contract and their one-change or one-scope boundary while dispatched. A dispatched child is still bound by this document.
- `finalize` is the one aggregated action. Its packet covers the whole domain by design, not because the driver widened the scope.
- A driver stops at `role: human`, a decision handoff, a missing evidence handoff, a blocker, or `command: complete`. It reports the blocker instead of retrying around a lifecycle guard.
- Model selection, execution backend, context assembly, retry escalation, token budget, and concurrency live in `core/routing/` as runtime configuration. They never enter PLAN, WORK, or STATE as product authority, and a routing change cannot alter a lifecycle decision.
- Controller telemetry under `.devflow/runtime/<domain>/` and private test diagnostics under `.devflow/private/` are operational records. They grant no lifecycle authority and are not lifecycle artifacts.

Manual operation remains the default. Removing a driver changes who performs the work, never what the next action is.

## Runtime transition guards

Mutation commands reject invalid transitions with exit code `2` before writing STATE or WORK.
Every mutation command projects its prospective STATE, and any WORK it changes, on copies and then commits the changed documents through one transaction, mirroring `audit apply`.
A command that exits non-zero has written nothing, including when the derived-state projection itself raises on structurally invalid input.
This is process-local failure rollback, not crash recovery or concurrent-writer isolation.

- `work start` requires ready status, completed dependencies with required reviews verified, resolved decisions, an unverified containing phase, and a verified required plan review. Integration WORK also waits for all project phases.
- `work done` requires `in_progress` and completion evidence. `work start` normalizes `evidence.delivery: null` to an empty mapping before recording delivery provenance.
- `work block` is limited to `ready` and `in_progress` with a non-empty reason. It records the prior active status and transition history.
- `work unblock` restores the recorded `ready` or `in_progress` state after a normal execution block clears. It cannot bypass an external evidence wait.
- `work wait-external` accepts `ready`, `in_progress`, or legacy `blocked` WORK, requires a reason and explicit missing-evidence entries, and records unverified evidence provenance without converting unknown facts to false.
- `work resume` resolves that external-wait provenance and restores the recorded active status. It does not mark the WORK done or verified.
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
| `sources/v1/{original.md,context.md,manifest.json}`                          | Captured source evidence for Goal; not independent product-policy approval.                  |
| `DECISIONS.md`                                                               | Blocking human decisions, developer choices, provisional and approved product policies.       |
| `work/*.yaml`                                                                | Every executable change, general and remediation alike.                                      |
| `audits/*.md`                                                                | One file per audit scope.                                                                    |
| `REQUIREMENTS_STATUS.md` / `REQUIREMENTS_STATUS.json`                        | Optional CLI-generated requirement views; never an independent status authority.            |
| `docs/PR/<domain-slug-hash>/<branch-slug-hash>.md`                           | Cumulative local PR body derived from the consuming project template.                        |
| `docs/postman/<domain-slug-hash>/<branch-slug-hash>.postman_collection.json` | Cumulative importable collection for the delivered branch.                                   |

Do not create separate task Markdown files, handoff documents, remediation plans, focused-review documents, integration-test plans, or prompt handoff documents.
STATE and the CLI reconstruct the next action.
`devflow requirements report <domain> --write` generates both local-only status views from the same P04 snapshot.
No lifecycle state, WORK, PRD or approval is modified. Checkboxes require verified implementation;
product approval and original alignment remain independent status fields. Do not edit generated reports by hand.

### Why PITFALLS is a separate artifact

`status` reconstructs lifecycle position; `PITFALLS.md` records verified repository traps that STATE cannot infer. `plan`, `run`, and `audit` load it. Keep fresh template sections empty until evidence establishes a trap, and remove stale entries.

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
`finalization.md` owns `delivery newman` execution, server readiness/liveness/cleanup, durable failure evidence, and the no-HTTP proof required for `not_applicable`. Recorded attempts persist even on failure; rejected lifecycle transitions preserve STATE/WORK.
The optional `delivery.finalization` field is adopted idempotently with `delivery enable`.

`status` can report `next.command: finalize`; `render finalize` supplies its entire-domain packet.
The packet carries the whole-work scope and HTML metadata plus a normalized WORK manifest of
`id`, `status`, `kind`, `risk`, `phase`, `commit`, `review`, `changed_files`, recorded verification
and each item's exact `work_file`. It is paged 60 rows per page through `--manifest-page <n>`, and
an out-of-range page is rejected. The original WORK documents stay on disk and are read on demand.
Paging bounds what is read per page, never what is in scope: every WORK disposition and every
branch evidence still reaches the ELI5 explanation and the final gates.
`next` remains the one-WORK selector and returns nonzero when the next action is finalization.
