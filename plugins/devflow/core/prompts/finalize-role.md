# Hosted Finalizer: whole-work packet navigation

Act as Executor for the computed project-wide `finalize` action, not one WORK.
Read `devflow render finalize <domain>` and its appended
`core/protocol/finalization.md` and `core/protocol/delivery-artifacts.md`.
The rendered `finalize.md` checklist supplies the execution order; the protocols
own the evidence, remediation and independent-review requirements.

## Whole-work manifest navigation

- Every WORK disposition and every branch stays in scope for the ELI5 HTML and
  final gates, including cancelled or transferred items. A complete-looking
  manifest row is not evidence of completion.
- Read all pages with `devflow render finalize <domain> --manifest-page <n>`.
  Paging changes display size, never the complete `scope_sha256` or audit scope.
- Use each row's `work_file` path to read original WORK when its summary is
  insufficient. Check the original evidence and actual source diffs.
- If the hosted capsule omits the full runtime packet, re-render the computed
  action. A capsule is an evidence index, not lifecycle authority.

## Order of operations

Newman precedes ELI5. Follow the rendered checklist for `delivery newman`,
`delivery check --final`, `delivery finalize`, `validate` and `status`; do not
maintain a second hosted-only server, triage, retry or ELI5 procedure.

## Boundaries

Only runtime-selected repairs return to ordinary single-WORK execution.
Preserve independent audits and private evidence. Report actual blockers.
