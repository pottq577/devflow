# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version 0.10.0 and its protocol version is `1.8.0`.

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

## Version 0.10.0 routing and finalization efficiency

Version 0.10.0 retains artifact protocol `1.8.0`. Hosted `/goal` records fail-open dispatch telemetry, uses GPT-6.1 Sol for frontier decisions and GPT-6 Luna for routine execution, and limits read-only Terra scouting to integration audits, diagnosis, critical analysis and selected retries. WORK routing now follows explicit item risk rather than always inheriting a higher domain risk.

Rendered packets include finalization instructions only for relevant actions. Newman verification, diagnosis and any committed repairs now precede the final installed-ELI5 explanation, avoiding a mandatory early draft and regeneration cycle.

## Version 0.9.4 contract and runtime alignment

Version 0.9.4 keeps protocol `1.8.0` and changes no lifecycle status, enum, or transition. It corrects places where the recorded contract had drifted from the runtime: the schemas now declare the STATE fields the runtime writes and the WORK/audit keys it enforces, the model registry enforces the `multi_agent` requirement its schema has always stated, and the release archive now carries both marketplace adapters so an installed zip can resolve `plugins/devflow`. It also splits the three largest runtime functions into named per-concern units, verified byte-identical by differential harnesses over WORK validation, the next-action state machine, and every `work` CLI transition.

## Version 0.9.3 remediation recovery

DevFlow keeps verified risk mitigation separate from unresolved historical evidence. External evidence waits can link verified mitigation WORK and explicit residual risks without marking the historical fact resolved. The scheduler continues independent remediation and review closures, while `provide-evidence` remains a final handoff after runnable actions are exhausted. Version 0.9.3 also publishes the remediation scheduler fixes under a new plugin version so Codex and Claude plugin caches can load the updated runtime.

## Version 0.9.2 transport-safe autonomous routing

`/goal` keeps one user-facing session while DevFlow separates context processing, judgment, execution, and verification. Terra performs bounded read-only pre-analysis, Sol owns planning and verification decisions, and Luna owns mutation WORK. Codex specialists now inherit the caller's permission profile instead of forcing legacy `--sandbox` modes, and a parent `OPENAI_BASE_URL` is forwarded to child `codex exec` processes so an existing Headroom session is reused without nested wrappers. Model capability failures can still fall through to another candidate, while network, permission, wrapper, and backend failures block as infrastructure errors. A timed-out action enters an independent diagnosis path after the first timeout and blocks after the second timeout without consuming the semantic no-progress retry ladder.

Adopt an existing domain with `devflow delivery enable <domain>`, then use `devflow status <domain>`.
Use `devflow autopilot start <domain>` or invoke the `goal` skill to run the complete lifecycle; use `devflow autopilot status <domain>` and `route` for observability.
