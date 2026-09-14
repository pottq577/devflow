# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version
0.9.0 and its protocol version is `1.9.0`.

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

## Version 0.9.0 autonomous routing

`/goal` can now keep one user-facing session while DevFlow deterministically routes lifecycle actions to task-appropriate specialist models. New-domain PRD bootstrap is routed through the Architect profile before initialization; routine implementation defaults to Luna, high/critical WORK is promoted by its own risk, planning and verification default to Sol, and critical integration reasoning stays on Sol at maximum effort with Terra as the fallback candidate. Runtime capacity/model/backend failures fall through to persisted candidate fallback, Codex CLI versions are checked per model before dispatch, and retry/diagnosis state survives resume. A measured-token pre-dispatch budget, bounded read-only scouting, and a per-domain mutating lease make the controller cost-aware and safe against competing workspace writers. Existing manual plan/run/audit/status commands remain supported.

Adopt an existing domain with `devflow delivery enable <domain>`, then use `devflow status <domain>`.
Use `devflow autopilot start <domain>` or invoke the `goal` skill to run the complete lifecycle; use `devflow autopilot status <domain>` and `route` for observability.
