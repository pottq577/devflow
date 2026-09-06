# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version
0.5.0 and its protocol version is `1.3.0`.

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
