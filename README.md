# DevFlow Marketplace

One source of truth for the DevFlow plugin distributed to Claude Code and OpenAI Codex.
Both marketplace adapters load the same `plugins/devflow` directory. The shared plugin is version
0.4.0 and its protocol version is `1.2.0`.

## Claude Code

```bash
claude plugin marketplace add /path/to/devflow-marketplace
claude plugin install devflow@devflow-team
```

## Codex

```bash
codex plugin marketplace add /path/to/devflow-marketplace
codex plugin add devflow@devflow-team
```

## DevFlow

DevFlow turns an approved PRD into repository-grounded plans and work items, executes one verified
item at a time, and supports independent work, phase, and integration audits. See
[`plugins/devflow/README.md`](plugins/devflow/README.md) for its commands and artifact contract.
