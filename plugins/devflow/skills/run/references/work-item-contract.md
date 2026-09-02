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

## Execution rules

- Dependency order outranks severity. Severity sorts items only inside the same dependency level.
- Re-verify every task premise against current code before editing.
- Stop instead of expanding scope when a stop condition is met.
- Record deviations and discoveries in evidence; do not hide them in prose elsewhere.
- General implementation and remediation use the same schema. Distinguish them with `kind` and `origin.findings`.
