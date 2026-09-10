# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version
0.8.0 and its protocol version is `1.7.0`.

## Claude Code

```bash
claude plugin marketplace add /path/to/devflow
claude plugin install devflow@devflow-team
```

## Codex

```bash
codex plugin marketplace add /path/to/devflow
codex plugin add devflow@devflow-team
```

## DevFlow

DevFlow supports delivery from an approved PRD and brownfield audit/remediation without fake phases.
It executes one verified item at a time and applies machine-readable audit outcomes through guarded
lifecycle transitions. See
[`plugins/devflow/README.md`](plugins/devflow/README.md) for its commands and artifact contract.

## Version 0.7.0 delivery additions

Implementation WORK now carries source-comment evidence, a cumulative PR body per branch using
`docs/PR/templates.md`, and an importable Postman collection per branch. The shared runtime checks
these outputs before completion. Local documentation remains compatible with a fully ignored
`docs/` directory.

Existing domains keep their PLAN/WORK documents. Run `devflow delivery enable <domain>` once to
adopt the new completion requirements; completed WORK is preserved. New domains enable it by
default, and the plan/run skills perform the adoption preflight. See the plugin README for the
source-first completion order and the offline Postman validation boundary.

## Version 0.8.0 whole-work completion

After branch PR/collection generation, the Executor invokes the installed `eli5` skill to produce
one HTML explanation of the whole domain, executes collections with installed Newman against
verified isolated test builds, diagnoses code/collection/environment failures, and routes code or
collection defects through normal tested, committed remediation WORK. It refreshes all delivery
outputs and the explanation before independent integration audit.

Adopt an existing domain with `devflow delivery enable <domain>`, then use `devflow status <domain>`.
When `next.command` is `finalize`, use `devflow render finalize <domain>`. See
`docs/devflow-0.8.0/VERIFICATION.md` for the tested scope and execution limitations.
