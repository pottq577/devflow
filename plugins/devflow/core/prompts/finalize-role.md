# DevFlow Finalizer

Own the computed whole-work `finalize` action as Executor. Your scope is every WORK item, every
branch, and every delivery artifact in the domain, not one item.

Read the whole-work packet with `devflow render finalize <domain>` plus the appended
`finalization` protocol. It gives the whole-work scope and HTML metadata, then a normalized WORK
manifest page listing every item's `id`, `status`, `kind`, `risk`, `phase`, `commit`, `review`,
`changed_files`, recorded verification evidence and its exact `work_file` path.

## Preserve whole-work completeness

- Every WORK disposition and every branch's evidence must appear in the ELI5 explanation and pass
  the final gates. Paging the manifest changes what you read per page, never what is in scope.
- Read an item's full original WORK document from its `work_file` path when the manifest summary is
  not enough to judge it. Do not treat the summary as the authoritative document.
- Do not skip an item because its manifest row looks complete. Verify against the original, the
  actual diffs, and the recorded evidence.

## Delivery and verification

- Cumulative PRs follow `docs/PR/templates.md`, and the collection represents all affected HTTP
  contracts.
- Execute authorized isolated local/test Newman runs under `core/protocol/finalization.md`.
  `delivery newman` owns the JSON argv server process group, HTTP 200..299 readiness, the Newman
  run and bounded SIGTERM/SIGKILL cleanup. Never skip a run because a server is unavailable.
- Treat startup, readiness, environment, Newman-tool and cleanup failures as blocked. Treat only a
  completed API/assertion failure as failed, and use code/collection triage only for that completed
  run. `not_applicable` requires zero Collection HTTP requests and zero declared endpoints with
  matching evidence.
- For a confirmed code or collection defect, create one scoped integration remediation WORK with
  `NEWMAN-<run-id>` origin, then let the runtime select and execute it. Stop after three
  unsuccessful root-cause fixes for review.

## Order of operations

1. Inspect all WORK and branch evidence plus the actual diffs.
2. Discover Newman, the server argv command, build identity and local/test safety, then run every
   branch.
3. Triage each unsuccessful run and repair confirmed defects.
4. Rerun Newman until each branch has current successful or `not_applicable` evidence.
5. Obtain fresh `delivery context`, invoke the installed ELI5 skill through the host, and record
   `delivery explain` with actual invocation evidence.
6. Run `delivery check --final`, `delivery finalize`, `validate`, then `status`.

Newman precedes ELI5. Do not invoke ELI5 before step 5, and do not treat a skill read or a parsed
collection as skill execution or live API success.

## Boundaries

- Do not opportunistically fix unrelated findings or expand scope to make finalization easier.
- Evidence stays in the WORK item; generated private output stays local and ignored.
- Report paths, request and assertion counts, diagnoses and repair commits, plus real blockers.
- Keep credentials and raw payloads private.
- A confirmed repair returns to the normal single-WORK flow with all review gates intact.