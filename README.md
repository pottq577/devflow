# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version
0.9.1 and its protocol version is `1.8.0`.

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

## Version 0.9.1 cost-aware autonomous routing

`/goal` keeps one user-facing session while DevFlow separates context processing, judgment, execution, and verification. Terra performs bounded read-only pre-analysis and compresses the full runtime/repository context into an evidence capsule. Sol receives that capsule instead of the full rendered packet for planning, verification, audit, diagnosis, and finalization, while retaining an explicit re-render escape hatch when evidence is incomplete. Luna owns mutation WORK and escalates `high -> xhigh -> max`; after independent Sol diagnosis, Luna retries at `max` before Terra `xhigh` is used as the final alternative executor. Sol remains the final decision authority and does not silently fall back to Terra. Runtime capacity/model/backend failures, retry/diagnosis state, measured-token budgeting, and the per-domain mutating lease remain resumable and observable.

Adopt an existing domain with `devflow delivery enable <domain>`, then use `devflow status <domain>`.
Use `devflow autopilot start <domain>` or invoke the `goal` skill to run the complete lifecycle; use `devflow autopilot status <domain>` and `route` for observability.
