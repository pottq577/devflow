# Authority and conflict rules

Use this precedence when sources disagree:

1. Explicit, resolved user decisions recorded for the current domain.
2. Approved PRD and product/domain specifications.
3. Repository-enforced rules such as `AGENTS.md`, `CLAUDE.md`, linters, schemas, and CI contracts.
4. Approved repository-grounded implementation PLAN.
5. WORK items generated from that PLAN or from confirmed AUDIT findings.
6. Completion evidence and historical reviews.

Treat PRD as the product/domain source of truth and PLAN as the repository implementation source of truth.

## Conflict handling

- Never silently choose between contradictory authoritative sources.
- Record specification-vs-code or specification-vs-plan conflict as `SPEC_DRIFT` or `DECISION_REQUIRED`.
- Verify repository facts directly. Historical reports, completion notes, and file paths are evidence candidates, not authority.
- Record `baseline_sha`, `target_sha`, and `diff_range` for audits. Prefer immutable commit SHAs over branch names.
- When work moves between phases, register the same requirement in the receiving phase and link the transfer explicitly through `transfer.to`. `validate` enforces this.

## Pinning a range

A branch name is not a range, and a 3-dot range is only trustworthy when the base is genuinely an
ancestor of the head. A stacked branch cut from a work commit rather than the previous phase's tip
resolves to a stale merge base and reports hundreds of unrelated files as if they were in scope.

```bash
devflow phase ref <domain> <phase> --base <ref> --head <ref>
```

That command resolves both refs to SHAs, verifies ancestry with `git merge-base --is-ancestor`, and
writes `base_sha`, `head_sha`, and `diff_range` into STATE. It refuses rather than guessing when the
history diverged, and takes `--range` for that case.

Do not check out branches to read code. Another session may be working in the tree. `git show
<ref>:<path>` and the pinned diff are enough; create a worktree only to build or test, and remove it
afterwards.

## Accumulated domain knowledge

`PITFALLS.md` holds traps that no lifecycle state can express: fakes that always succeed, methods
that no-op instead of raising, a verification command that skips the suite it appears to run,
behavior that looks like a defect but is a recorded decision. It is loaded by `plan`, `run`, and
`audit`.

It is context, not authority. When it disagrees with current code, the code wins and the entry is
stale. Fix the entry in the same change.

The render commands assemble bounded context, not repository RAG or semantic search: plan receives
the full PRD, run receives the selected WORK and exact origin-linked PRD/PLAN sections, work and
phase audits receive scope-linked context, and integration receives broad summaries and paths.

## Delivery output authority

`delivery-artifacts.md` grants a narrow allowance for the requested branch PR body and Postman
collection, including existing WORK scope lists. Read the consuming project's
`docs/PR/templates.md` as input; preserve it. Generated outputs stay derived from code, source refs,
executed evidence and existing STATE/WORK, and grant no product-scope or remote-operation authority.

Protocol 1.7 `finalization.md` additionally authorizes the whole-work ELI5 HTML, sanitized Newman
summaries and local private test diagnostics. All source/test corrections use traceable ordinary
WORK and commits. The actual accepted API contract governs code-versus-collection diagnosis.
