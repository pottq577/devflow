# AUDIT core

Auditors work in a fresh reasoning context whenever practical and verify the repository directly.
A prior report is a lead, never a fact.
Paths, line numbers, and causal claims in earlier audits have been wrong before, and were only caught because the next reader re-checked them in code.

## 0. Pin the range before reading anything

An audit without an immutable range is not reproducible.

- Record `baseline_sha`, `target_sha`, and `diff_range`. Prefer SHAs over branch names.
- **Confirm the ancestry before trusting a 3-dot diff.**
  - A stacked branch may have been cut from a work commit rather than the previous phase's tip, and the 3-dot range then resolves to a stale merge base and reports hundreds of unrelated files.

  ```bash
  git merge-base --is-ancestor <base> <head> && echo linear || echo diverged
  git log --graph --oneline <base> <head> | head -20
  ```

  - When it is diverged, use the phase's own commit range instead: the parent of its first work commit through its last work commit, excluding any merge commit at the tip.

- `devflow phase ref <domain> <phase> --base <ref> --head <ref>` performs this check and writes the range into STATE.
  - It refuses rather than guessing, and takes `--range` for the diverged case.

## 1. Do not disturb other work

Do not check out branches. Another session may be working in the tree.

- `git show <ref>:<path>` and the pinned diff are enough to read code.
- Create a worktree only to build or test, and remove it afterwards.

## 2. Common axes

Axes A and B ask "was the approved thing built". C through J ask "was it built correctly".

### A. Requirement and PLAN traceability

- Every PLAN item has a commit and a file behind it.
- Classes and files the PLAN declared as deliverables exist under those names.
- Changes present in the diff but absent from the PLAN: do they belong to this phase, or did they pull later work forward?
- Anything the PLAN left incomplete or moved to a later phase is recorded honestly, and the receiving phase has a row for it.

### B. Source-of-truth compliance

Map each requirement id the phase cites onto a code location.
Ids that fail to map are this axis's result.

- Conditions in the requirement match the conditions in code, especially defaults, negations, and boundary values.
- State transitions admit only the allowed set and reject the rest.
- Idempotency keys match the specified scope and collision behavior.
- API contracts match in path, method, status code, and field names.

### C. Repository and architecture conventions

- Rules the repository enforces mechanically (architecture tests, linters, CI gates) still pass, and no new placement violates them.
- Naming rules for new tables, columns, and types.
- Migration hygiene: new version numbers exceed the current maximum, already-applied migrations are untouched, and files sit in the directory their runner actually reads.
- Entities extend the designated base and do not redeclare its fields.
- Async and context-propagating code uses the sanctioned wrapper rather than raw thread-local access.
- Residue of removed concepts is not reintroduced by new code, comments, or docs.

### D. Code-level design and contract correctness

These are the places that actually cause incidents.

- **Transaction boundaries**:
  - external I/O inside a database transaction, and the window where a commit failure leaves external state inconsistent.
- **Concurrency**:
  - two simultaneous requests on the same entity.
  - What stops the double effect, a unique constraint, a lock, or a retry? An application-level check alone is a defect.
- **Idempotency**:
  - a retry must not repeat the side effect.
  - Is the key minted by the server or by the client?
- **State transitions**:
  - is the transition decision in one place, or scattered across services? Reverse and self transitions handled.
- **Money and currency**:
  - no floating-point types, rounding matches the specification, and the server-computed amount is compared against the provider-approved amount.
- **Time**:
  - stored timezone, and an injected clock rather than a direct call to "now", so the behavior is testable.
- **Failure and ambiguity**:
  - there is a path for "the external system did not answer" that does not quietly resolve to success.
- **Exception mapping**:
  - domain errors surface as the intended status, and internal messages do not leak.
- **Input validation**:
  - enforced at the trust boundary, and services do not assume the controller already validated.
- **Security**:
  - no secrets or card data in logs, and ownership is checked before returning another party's record.
- **Query and lock cost**:
  - repeated queries per row, and slow work performed while holding a lock.

### E. Tests and executable evidence

- Every test case the PLAN required exists.
- Tests can actually fail.
  - Look for missing assertions, tautological assertions, and swallowed exceptions.
- Boundaries and failure paths are covered.
  - A suite that only walks the happy path is a finding.
- Evidence in WORK items matches what the commands actually print.
  - Re-run the ones that matter.

### F. Overengineering, residue, and scope intrusion

- Interfaces with one implementation, unused extension points, configuration with one possible value.
- Abstraction layers the PLAN never asked for.
- Temporary scaffolding from an earlier phase that was supposed to be removed: mocks, flags, TODOs.
- A new helper that duplicates one already present in the repository.

### G. Failure and recovery behavior

- Partial failure leaves a state the system can resume from.
- Retries are bounded, and a permanently failed item is distinguishable from a retryable one.
- Compensating actions do not run against records that already reached a terminal state.

### H. Concurrency and idempotency

- Lock ordering is consistent across call paths, so two paths cannot deadlock.
- Duplicate delivery of the same external event applies once.
- Reprocessing an old event does not overwrite newer state.

### I. Security, authorization, and ownership

- Every handler carries an authorization decision, or an explicit, justified exemption.
- Ownership is derived from server-side state, not from a client-supplied identifier.
- Sensitive values are masked in logs, including partial-key matches and non-string values.

### J. Migration, configuration, and deployment

- Migration ordering is safe against a rolling deploy, in both directions.
- Configuration required by new code exists in every deployment combination that ships.
- Deployment artifacts that reference each other stay consistent.

## 3. Audit scopes and modes

DevFlow has four audit scopes: `plan`, `work`, `phase`, and `integration`.

- A plan initial audit verifies the repository-grounded PLAN before high-risk WORK begins.
- A work initial audit gates dependents of completed high or critical WORK.
- A work closure audit verifies traced remediation and the original WORK acceptance criteria.
- A phase initial audit batch-reviews terminal independent low/medium WORK and the completed phase.
- A phase closure audit verifies phase remediation before the phase is marked verified.
- An integration initial audit verifies the verified phases together.
- An integration closure audit verifies integration remediation before integration is marked verified.

The runtime renders context for the selected scope.
It does not autonomously run reviews or create remediation; the auditor records the outcome and any traced WORK.

## 4. Work audit

For `scope=work`, inspect the selected WORK YAML, its origin requirements and PLAN items, recorded evidence, changed files, commit when recorded, current HEAD, and the expected `audits/work/<WORK-ID>.md` artifact.
An initial audit either supports verification, records a block, or creates traced remediation WORK.
Closure mode verifies the remediation and the original acceptance criteria before the review is marked verified.

## 5. Phase audit

Concentrate on the phase PLAN, its WORK items, the pinned diff, tests, and acceptance criteria.

## 6. Integration audit

Everything above, plus:

- producer/consumer contracts across phases,
- transferred requirements, checked in the **receiving** phase's manifest,
- end-to-end state machines,
- end-to-end data flows,
- cross-module transaction boundaries,
- migration and deployment ordering,
- regression and evidence gaps.

## 7. Finding classification

- `CONFIRMED`: defect is supported by current repository evidence; create remediation WORK.
- `DECISION_REQUIRED`: product or policy choice is unresolved; record decision and block dependent WORK.
- `EVIDENCE_REQUIRED`: more verification is needed; create evidence-oriented WORK, not product-code changes.
- `REJECTED`: suspected defect is disproved; retain the audit record only.
- `DOCUMENTATION_DRIFT`: code and approved behavior align but documentation is stale; create documentation WORK.
- `SPEC_DRIFT`: authoritative sources conflict; stop affected execution until resolved.

Every finding must state expected:

- behavior, actual behavior, evidence, root cause or uncertainty, classification, severity, a nonblank severity reason, and disposition.

Finding disposition is structural.
`CONFIRMED`, `EVIDENCE_REQUIRED`, and `DOCUMENTATION_DRIFT` link respectively to `remediation`, `evidence`, and `documentation` WORK.
Each linked WORK carries the finding ID in `origin.findings`, and each such origin link is listed in the finding's `disposition.work_ids`.
Two or more findings may share one WORK only when `origin.aggregation_reason` states why they share one root cause, change and rollback boundary, and verification set.
The runtime validates the links and the presence of this rationale.
It does not infer semantic equivalence from prose.

`DECISION_REQUIRED` uses `disposition.action: decision`, has one or more `decision_ids`, and has no `work_ids`.
An initial, current-only, or `still_open` finding requires each ID to be open with its options in `DECISIONS.md`.
A closure outcome of `resolved`, `reopened`, or `accepted_risk` requires the prior finding's linked IDs to be resolved and absent from `STATE.unresolved_decisions`.
`accepted_risk` requires at least one such resolved decision.
Initial audit apply registers open IDs in `STATE.unresolved_decisions`; do not create ready implementation WORK from the finding before the decision is resolved.

## 8. Machine-readable audit outcome

The canonical audit Markdown starts with YAML front matter conforming to `core/schemas/audit.schema.yaml`.
It contains the audit scope and mode, verdict, immutable SHAs, executed verification, structured findings, and closure outcomes.
The Markdown body remains the human-readable explanation.
Do not create a YAML sidecar or another lifecycle artifact.

After writing the audit, any linked WORK, and any decision records, apply the outcome with the exact current lifecycle target:

```text
devflow audit apply <domain> --scope plan --mode initial
devflow audit apply <domain> --scope work --mode initial|closure --task <WORK-ID>
devflow audit apply <domain> --scope phase --mode initial|closure --phase <PHASE>
devflow audit apply <domain> --scope integration --mode initial|closure
```

The runtime reads only the canonical audit file recorded by STATE or WORK.
It rejects malformed or duplicate-key front matter, schema and verdict mismatches, missing or one-way finding links, incomplete closure coverage, unfinished remediation, and any request that differs from the computed next action.
It validates the prospective domain before writing lifecycle state.
The auditor never edits STATE to apply an outcome.

Closure coverage comes from the provenance the runtime recorded when the prior audit for this scope was applied.
`devflow audit apply` writes `audit_provenance.findings`, a mapping of finding ID to severity, onto the audited scope's machine-owned metadata (`STATE.plan_review`, `STATE.phases.<key>`, `STATE.integration`, or the WORK item's `review`) on every applied audit, and a later closure reads it.
A closure application also writes `applied_against` with the previous mapping it was validated against.
`validate` uses `applied_against` for that persisted closure while the next closure render and apply continue to use `findings`.
No Git history is consulted, so the lifecycle completes with `docs/` fully gitignored and the canonical audit never committed.
Every recorded finding needs one closure outcome.
Findings present only in the current file are new findings, and `reopened_as` may reference only those current-only IDs.
A closure at a scope with no recorded audit fails cleanly and names its recovery command:

- `devflow plan-review set <domain> pending`
- `devflow work review <domain> <WORK-ID> pending`
- `devflow phase set <domain> <phase> audit`
- `devflow integration set <domain> audit`

The runtime writes `audit_provenance`, and a closure author who only edits the canonical audit file cannot shrink the prior finding set.
The record still lives in STATE and WORK, which are machine-owned but on-disk and editable, so its integrity has the same trust boundary as every other lifecycle gate: hand-edited STATE that removes a recorded finding is undetected here, exactly as a hand-edited phase status or review status would be.
`validate` rejects a structurally malformed `audit_provenance` record but does not attest that its contents match a real prior audit.
Existing records without `applied_against` remain readable and use `findings` for both purposes.

`disposition.action: stop` is an explicit lifecycle block.
Applying it marks the audited scope blocked and makes the next action a human decision for plan, work, phase, and integration audits.
It cannot be treated as an empty remediation set or projected back to the same closure audit.

## 9. Severity and verdict

| Severity  | Meaning                                                                                  |
| --------- | ---------------------------------------------------------------------------------------- |
| `blocker` | Shipping this corrupts data or gets money wrong. Fix before any dependent work starts.   |
| `major`   | Violates an approved specification or a repository-enforced rule. Fix inside this phase. |
| `minor`   | Behavior is correct but carries maintenance risk. May travel to the next phase.          |
| `nit`     | Taste and readability. Closing it is optional.                                           |

| Verdict            | Condition                                            |
| ------------------ | ---------------------------------------------------- |
| `pass`             | No blocker and no major finding.                     |
| `conditional_pass` | Only major findings, each with a specific fix named. |
| `fail`             | At least one blocker.                                |

- **Never write `pass` without evidence.**
  - Only a command that was actually executed, with its output, is grounds for a pass.

In a closure audit, a finding recorded as `still_open`, and every finding a `reopened` entry lists in `reopened_as`, must keep a severity at least as high as the severity recorded for that prior finding when its initial audit was applied.
The auditor may raise a severity with new evidence, but cannot lower a still-open or reopened finding past the verdict rubric.
`resolved` and `accepted_risk` leave the active set, so re-evaluating a closed finding's severity is allowed.
The severity order is read from `finding.schema.yaml`.

## 10. Review timing

A closure audit after every single item costs more than it returns, and batching a whole phase lets defects stack on a wrong premise.
Let risk decide.
See `risk-policy.md`.

## Implementation delivery evidence

Apply `delivery-artifacts.md` for domains carrying `STATE.delivery`.
Validate recorded output provenance, inspect the semantic usefulness of source comments, compare PR content to the real branch base/head diff, and review collection coverage/auth/DTO/error assertions.
An empty collection requires a verified no-HTTP rationale.
Integration closure requires current per-branch outputs.
Treat local file validation and actual API execution as separate evidence.
Report discovered issues through existing finding classification and traced remediation WORK.

## Whole-work finalization review

For enabled finalization, apply `finalization.md`.
Compare the single ELI5 HTML to all WORK and branches, including cancelled/transferred outcomes, cross-branch behavior, final commits and actual test results.
Verify genuine installed-skill invocation and useful explanation beyond metadata.
Check Newman target/build isolation, complete request/assertion coverage, raw/summary integrity, secret hygiene and no-HTTP rationale.
Inspect every failed run's contract-based diagnosis, regression, repair commit and later passing server build.
Preserve independent audit gates; finalization evidence authorizes handoff, and the Auditor verifies its truth.
