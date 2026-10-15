# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version 0.11.1 and its protocol version is `1.8.0`.

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

## Version 0.11.1 hosted capsule and delivery corrections

Version 0.11.1 fixes defects found reviewing 0.11.0 and keeps protocol `1.8.0`. A branch record
that predates `postman_structure_sha256` validates again instead of raising `KeyError`. Scout
capsule binding is split from validation: `scout-bind` records creation provenance once,
`scout-validate` only reads it, `stale` is idempotent, and `dispatch --scout-cached` is re-verified
by the host before it skips a scout. The evidence digest now covers the content fingerprints of
every file the index cited, including scoped Git index entries so relevant staged and unstaged
changes invalidate the capsule. An unconfirmed reference outside the creation snapshot triggers
fallback; the capsule does not prove that Scout opened its cited sources. `render evidence` states
and enforces its row and text bounds. The hosted route engine is cached per routing policy instead
of once per process, and `delivery-artifacts.md` records that a same-path DTO, auth or assertion
change is an executor and auditor obligation rather than an automatic signal. Native hosted Goal
end-to-end and installed ELI5 acceptance remain **pending**; see the plugin CHANGELOG.

## Version 0.11.0 hosted Goal efficiency

Version 0.11.0 shipped the hosted Goal runtime refactorings for R00-R18 and recorded the local R19
release gates. Native R19 acceptance remained pending. Read-only hosted children start from a
bounded `render evidence` index instead of a full action packet, hosted renders are pinned to the
dispatch fingerprint and HEAD, one invocation reuses its WORK snapshot and its pinned Git
inspection and Newman digests, the finalizer receives a paged WORK manifest, and observation
commands no longer extend the lease. Additive CLI options (`render evidence`,
`--manifest-page`, `--expected-head`, `--expected-fingerprint`, `--check-only`,
`dispatch --scout-cached`), one optional branch field (`postman_structure_sha256`), and one new
protocol document (`core/protocol/role-instructions.md`) are the only contract changes. Lifecycle
statuses, audit gates, evidence provenance and every STATE/WORK artifact contract are unchanged, so
the artifact protocol remains `1.8.0`.

That implementation status does not establish the R19 acceptance gate. The 0.11.0 release record
is historical evidence from commit `23124f1`; native hosted Goal end-to-end execution and an actual
installed ELI5 invocation remain pending for this review.

## Version 0.10.2 peer-skill composition

Version 0.10.2 adds conditional execution guidance for Vercel, Matt Pocock, and Trail of Bits skills. DevFlow still owns lifecycle routing, verification, audit findings, and artifacts. New peer skills are optional, and peer-managed review workflows never run automatically inside `/goal`. The artifact protocol remains `1.8.0`.

## Version 0.10.1 hosted retry correction

Version 0.10.1 aligns hosted no-progress retry limits with standalone Autopilot. The final configured alternative-model retry can execute before the guard stops an unchanged action. It also publishes the hosted execution and test-gate safeguards added after 0.10.0 without changing protocol `1.8.0`.

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
