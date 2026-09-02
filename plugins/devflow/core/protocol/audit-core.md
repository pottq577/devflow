# AUDIT core

Auditors work in a fresh reasoning context whenever practical and verify the repository directly.
A prior report is a lead, never a fact. Paths, line numbers, and causal claims in earlier audits
have been wrong before, and were only caught because the next reader re-checked them in code.

## 0. Pin the range before reading anything

An audit without an immutable range is not reproducible.

- Record `baseline_sha`, `target_sha`, and `diff_range`. Prefer SHAs over branch names.
- **Confirm the ancestry before trusting a 3-dot diff.** A stacked branch may have been cut from a
  work commit rather than the previous phase's tip, and the 3-dot range then resolves to a stale
  merge base and reports hundreds of unrelated files.

  ```bash
  git merge-base --is-ancestor <base> <head> && echo linear || echo diverged
  git log --graph --oneline <base> <head> | head -20
  ```

  When it is diverged, use the phase's own commit range instead: the parent of its first work
  commit through its last work commit, excluding any merge commit at the tip.
- `devflow phase ref <domain> <phase> --base <ref> --head <ref>` performs this check and writes the
  range into STATE. It refuses rather than guessing, and takes `--range` for the diverged case.

## 1. Do not disturb other work

Do not check out branches. Another session may be working in the tree.

- `git show <ref>:<path>` and the pinned diff are enough to read code.
- Create a worktree only to build or test, and remove it afterwards.

## 2. Common axes

Axes A and B ask "was the approved thing built". C through J ask "was it built correctly".

### A. Requirement and PLAN traceability

- Every PLAN item has a commit and a file behind it.
- Classes and files the PLAN declared as deliverables exist under those names.
- Changes present in the diff but absent from the PLAN: do they belong to this phase, or did they
  pull later work forward?
- Anything the PLAN left incomplete or moved to a later phase is recorded honestly, and the
  receiving phase has a row for it.

### B. Source-of-truth compliance

Map each requirement id the phase cites onto a code location. Ids that fail to map are this axis's
result.

- Conditions in the requirement match the conditions in code, especially defaults, negations, and
  boundary values.
- State transitions admit only the allowed set and reject the rest.
- Idempotency keys match the specified scope and collision behavior.
- API contracts match in path, method, status code, and field names.

### C. Repository and architecture conventions

- Rules the repository enforces mechanically (architecture tests, linters, CI gates) still pass, and
  no new placement violates them.
- Naming rules for new tables, columns, and types.
- Migration hygiene: new version numbers exceed the current maximum, already-applied migrations are
  untouched, and files sit in the directory their runner actually reads.
- Entities extend the designated base and do not redeclare its fields.
- Async and context-propagating code uses the sanctioned wrapper rather than raw thread-local access.
- Residue of removed concepts is not reintroduced by new code, comments, or docs.

### D. Code-level design and contract correctness

These are the places that actually cause incidents.

- **Transaction boundaries**: external I/O inside a database transaction, and the window where a
  commit failure leaves external state inconsistent.
- **Concurrency**: two simultaneous requests on the same entity. What stops the double effect, a
  unique constraint, a lock, or a retry? An application-level check alone is a defect.
- **Idempotency**: a retry must not repeat the side effect. Is the key minted by the server or by
  the client?
- **State transitions**: is the transition decision in one place, or scattered across services?
  Reverse and self transitions handled.
- **Money and currency**: no floating-point types, rounding matches the specification, and the
  server-computed amount is compared against the provider-approved amount.
- **Time**: stored timezone, and an injected clock rather than a direct call to "now", so the
  behavior is testable.
- **Failure and ambiguity**: there is a path for "the external system did not answer" that does not
  quietly resolve to success.
- **Exception mapping**: domain errors surface as the intended status, and internal messages do not
  leak.
- **Input validation**: enforced at the trust boundary, and services do not assume the controller
  already validated.
- **Security**: no secrets or card data in logs, and ownership is checked before returning another
  party's record.
- **Query and lock cost**: repeated queries per row, and slow work performed while holding a lock.

### E. Tests and executable evidence

- Every test case the PLAN required exists.
- Tests can actually fail. Look for missing assertions, tautological assertions, and swallowed
  exceptions.
- Boundaries and failure paths are covered. A suite that only walks the happy path is a finding.
- Evidence in WORK items matches what the commands actually print. Re-run the ones that matter.

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

## 3. Phase audit

Concentrate on the phase PLAN, its WORK items, the pinned diff, tests, and acceptance criteria.

## 4. Integration audit

Everything above, plus:

- producer/consumer contracts across phases,
- transferred requirements, checked in the **receiving** phase's manifest,
- end-to-end state machines,
- end-to-end data flows,
- cross-module transaction boundaries,
- migration and deployment ordering,
- regression and evidence gaps.

## 5. Finding classification

- `CONFIRMED`: defect is supported by current repository evidence; create remediation WORK.
- `DECISION_REQUIRED`: product or policy choice is unresolved; record decision and block dependent WORK.
- `EVIDENCE_REQUIRED`: more verification is needed; create evidence-oriented WORK, not product-code changes.
- `REJECTED`: suspected defect is disproved; retain the audit record only.
- `DOCUMENTATION_DRIFT`: code and approved behavior align but documentation is stale; create documentation WORK.
- `SPEC_DRIFT`: authoritative sources conflict; stop affected execution until resolved.

Every finding must state expected behavior, actual behavior, evidence, root cause or uncertainty,
classification, severity, and disposition.

## 6. Severity and verdict

| Severity | Meaning |
| --- | --- |
| `blocker` | Shipping this corrupts data or gets money wrong. Fix before any dependent work starts. |
| `major` | Violates an approved specification or a repository-enforced rule. Fix inside this phase. |
| `minor` | Behavior is correct but carries maintenance risk. May travel to the next phase. |
| `nit` | Taste and readability. Closing it is optional. |

| Verdict | Condition |
| --- | --- |
| `pass` | No blocker and no major finding. |
| `conditional_pass` | Only major findings, each with a specific fix named. |
| `fail` | At least one blocker. |

**Never write `pass` without evidence.** Only a command that was actually executed, with its
output, is grounds for a pass.

## 7. Review timing

A closure audit after every single item costs more than it returns, and batching a whole phase lets
defects stack on a wrong premise. Let risk decide. See `risk-policy.md`.
