# DevFlow Marketplace

Claude Code and OpenAI Codex load the same `plugins/devflow/` implementation. The [canonical version metadata](plugins/devflow/version.json) and the acceptance status are maintained separately from release history.

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

- Read [version.json](plugins/devflow/version.json) for the published plugin version and artifact protocol version. Older compatible artifacts remain readable.
- Native hosted Goal end-to-end execution and invocation of the installed ELI5 skill remain
  **pending acceptance**. Local tests and synthetic CLI measurements are not that evidence.
- See [CHANGELOG](plugins/devflow/CHANGELOG.md) for historical releases and measurements.
