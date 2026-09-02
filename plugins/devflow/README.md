# DevFlow Plugin

DevFlow is a state-based development protocol for agentic coding workflows.

It keeps product and domain intent in PRD, repository implementation intent in PLAN, executable
changes in WORK, independent review in AUDIT, accumulated domain traps in PITFALLS, and lifecycle
position in STATE. The normative runtime contract is `core/protocol/*.md` plus the `core/schemas/`
files, because runtime validation derives directly from them. `core/references/vibecoder.md` is the
original design rationale and is kept for background, not as the current contract.

The point is that a fresh session reconstructs what to do next by running one command instead of
reading a pile of narrative documents, and that the knowledge each cycle bought does not evaporate
when the session ends.

## Commands and skills

| Skill | Role | Does |
| --- | --- | --- |
| `plan` | Architect | Repository-grounded architecture and WORK generation |
| `run` | Executor | Exactly one ready WORK item, with evidence |
| `audit` | Auditor | Independent plan, work, phase, and integration verification |
| `status` | none | Deterministic next-action reconstruction |

## Runtime dependency

Python 3.10+ and PyYAML 6.x:

```bash
python3 -m pip install -r requirements.txt
```

## Runtime commands

```bash
devflow init <domain> --prd <path> [--risk low|medium|high|critical] [--extension <name>]
devflow status <domain> [--json]
devflow next <domain> [--json]
devflow validate <domain>

devflow render plan  <domain>
devflow render run   <domain> [--task <ID>]
devflow render audit <domain> --scope plan|work|phase|integration [--task <ID>] [--phase XX] [--mode initial|closure]

devflow work start <domain> <ID>
devflow work done  <domain> <ID> --commit <sha> --command '<cmd> -> <result>' [--changed-file ...]
devflow work block <domain> <ID> --reason "..."
devflow work review <domain> <ID> verified|remediation|blocked [--remediation-work <ID>]

devflow phase set <domain> <phase> <status>
devflow phase ref <domain> <phase> --base <ref> --head <ref> [--range <explicit>]
devflow plan-review set <domain> pending|verified|skipped
devflow integration set <domain> <status>
devflow decision add|resolve <domain> <ID>
```

`bin/devflow` is a thin wrapper if you prefer a bare command name on `PATH`. Skills invoke
`scripts/devflow.py` through each skill's `scripts/invoke.py`, which resolves the plugin root from
its own location and so works from any working directory.

`render` emits a complete prompt: the role packet, the runtime context, the relevant protocol
documents inline, the resolved domain extension for audits, and the domain's `PITFALLS.md`. There is
nothing further to open by hand.

Its context is deliberately bounded. Plan render includes the full approved PRD. Run render includes
the selected WORK plus exact origin-linked PRD and PLAN sections. Work and phase audit render include
scope-linked WORK and origin context. Integration render supplies the current PLAN, phase manifest,
audit paths, and integration WORK without inlining every phase WORK body. This is not semantic search,
repository RAG, or autonomous orchestration.

## Typical manual flow

Use the parser-supported commands below after planning has created `P01-I01`:

```bash
devflow status billing
devflow render run billing --task P01-I01
devflow work start billing P01-I01
devflow work done billing P01-I01 --command "python3 tests/test_billing.py -> pass"
devflow render audit billing --scope work --task P01-I01 --mode initial
devflow work review billing P01-I01 verified
devflow render audit billing --scope phase --phase 01 --mode initial
```

For high or critical WORK, the initial work audit must verify the review before dependent WORK can
start. If it creates remediation, complete that traced WORK and render the same work audit with
`--mode closure`. Independent low and medium WORK is batch-reviewed during the phase audit.

The lifecycle is: PRD, plan, optional required high-risk plan audit, run WORK, high/critical WORK
initial audit, remediation when confirmed, work closure audit, dependent release, phase initial
and closure audits, integration initial and closure audits, then project completion.

## Project artifacts

```text
.devflow/
├── config.yaml            # protocol_version, domains_root, default extension
└── extensions/            # optional project-local audit extensions
docs/domains/<domain>/
├── PRD.md                 # product and domain contract
├── PLAN.md                # repository-grounded implementation strategy
├── STATE.yaml             # lifecycle position, machine-owned
├── PITFALLS.md            # accumulated traps a fresh session must know
├── DECISIONS.md           # human and product decisions
├── work/                  # every executable change, general and remediation alike
└── audits/                # one file per audit scope
```

Initialize a domain with the `plan` skill, or directly:

```bash
python3 scripts/devflow.py init <domain> --prd <path> --risk high
```

If `docs/` is gitignored in your repository, point `domains_root` in `.devflow/config.yaml` at a
tracked directory. `STATE.yaml` is the coordination substrate, and an untracked one cannot hand off
to another machine.

## Why PITFALLS is its own artifact

A handoff document has two halves. `status` reproduces the first half exactly: where the work is,
what is blocked, what runs next. The second half is knowledge the project bought the hard way, and
no state machine can derive it: a test double that always returns success, a method that no-ops
instead of raising, a verification command that skips the suite it appears to run, the next free
migration number, behavior that looks like a defect but is a recorded decision.

`plan`, `run`, and `audit` all load `PITFALLS.md`, so an entry is written once and repays every
session after. Entries earn their place by having cost something; delete one when the trap is
actually gone.

## Audit extensions

Audits load one domain extension on top of the common core. Resolution order:

1. `.devflow/extensions/<name>.md` in the project
2. `core/extensions/<name>.md` in the plugin
3. `core/extensions/default.md`

Set the name per domain in `STATE.yaml` (`extension:`) or per project in `.devflow/config.yaml`.
`core/extensions/billing.example.md` shows the shape of a domain-specific one.

## What `validate` enforces

- STATE required fields, and every status value against its allowed set
- Duplicate phase entries, including two raw keys that normalize to the same phase
- A phase marked `verified` while its own work is unfinished, and an integration marked `verified`
  while a phase is not
- Duplicate WORK ids, unresolved dependencies, and dependency cycles
- Empty `acceptance` or `verification.commands`
- A `ready` item blocked by an unresolved decision
- `premise_checks` present on every `high` and `critical` risk item
- `done` backed by `evidence.commands`, except for `kind: documentation`
- `transferred` items linked through `transfer.to`, with the receiving item carrying the same
  `origin.requirements`
- Requirement ids that do not appear verbatim in the PRD (warning)

## Compatibility and protocol version

Plugin version 0.3.0 keeps protocol version `1.1.0`. The artifact contract is backward-readable:
existing WORK without `review` remains readable, but legacy high or critical done WORK requires
review before dependents. A legacy `plan_review` without `audit_file` reads as `audits/plan.md`.
Runtime normalization supplies these defaults, so no migration command is required.
