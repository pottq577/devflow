# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow/` implementation; current version and acceptance status appear below.

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

## Start or resume a domain

```bash
devflow delivery enable <domain>  # adopt an existing domain; preserves completed WORK
devflow status <domain>           # inspect the computed next action
```

Use the `plan`, `run`, `audit`, and `status` skills for manual operation; use the `goal` skill
for host-native routed execution or `devflow autopilot start <domain>` for the standalone
foreground controller. See [the plugin guide](plugins/devflow/README.md) for supported commands,
dependencies, evidence requirements, delivery outputs, and environment limitations.

## Current compatibility and acceptance

- Plugin version: **0.11.1**; artifact protocol: **1.8.0**. Older compatible artifacts remain readable.
- Native hosted Goal end-to-end execution and invocation of the installed ELI5 skill remain
  **pending acceptance**. Local tests and synthetic CLI measurements are not that evidence.
- Historical releases, R00-R18 implementation notes, and measured CLI component results are
  recorded in [CHANGELOG](plugins/devflow/CHANGELOG.md); they are not new runtime commands.
