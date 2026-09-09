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
devflow init <domain> [--prd <path>] [--risk low|medium|high|critical] [--workflow delivery|audit-remediation] [--extension <name>]
devflow status <domain> [--json]
devflow next <domain> [--json]
devflow validate <domain>

devflow render plan  <domain>
devflow render run   <domain> [--task <ID>]
devflow render audit <domain> --scope plan|work|phase|integration [--task <ID>] [--phase XX] [--mode initial|closure]
devflow audit apply  <domain> --scope plan|work|phase|integration [--task <ID>] [--phase XX] [--mode initial|closure]

devflow work start <domain> <ID>
devflow work done  <domain> <ID> --commit <sha> --command '<cmd> -> <result>' [--changed-file ...]
devflow work block <domain> <ID> --reason "..."
devflow work review <domain> <ID> verified|remediation|blocked|pending [--remediation-work <ID>]

devflow phase set <domain> <phase> <status>
devflow phase ref <domain> <phase> --base <ref> --head <ref> [--range <explicit>]
devflow plan-review set <domain> pending|verified|skipped
devflow integration set <domain> <status>
devflow decision add|resolve <domain> <ID>
```

`render` and `audit apply` accept only the exact scope, mode, phase, and WORK target reported by
`status`. A mismatch exits before a packet or lifecycle mutation is produced. `audit apply` reads
the canonical audit Markdown selected by STATE or WORK, validates its YAML front matter and traced
artifacts, and commits the accepted lifecycle transition atomically.

Every lifecycle mutation command (`work start|done|block|review`, `phase set|ref`, `plan-review
set`, `integration set`, `decision add|resolve`) projects its prospective state on copies and
commits the changed STATE and WORK together in one transaction. A command that exits non-zero has
written nothing. `validate` reports structural defects; it never rewrites STATE to normalize them.

The legacy `plan-review set`, `work review`, `phase set`, and `integration set` commands remain
available for protocol 1.2 and older artifacts. Protocol 1.3 verified audit transitions go through
`audit apply` so they cannot bypass audit metadata validation.

`phase set` and `phase ref` operate on a phase that already exists in `STATE.yaml`, or on one whose
`work/phase-XX.yaml` is on disk. They refuse anything else rather than inventing a phase entry, since
a mistyped number would otherwise sit in STATE and block integration forever.

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
devflow audit apply billing --scope work --task P01-I01 --mode initial
devflow render audit billing --scope phase --phase 01 --mode initial
devflow audit apply billing --scope phase --phase 01 --mode initial
```

For high or critical WORK, the initial work audit must verify the review before dependent WORK can
start. If it creates remediation, complete that traced WORK and render the same work audit with
`--mode closure`. Independent low and medium WORK is batch-reviewed during the phase audit.

The lifecycle is: PRD, plan, optional required high-risk plan audit, run WORK, high/critical WORK
initial audit, remediation when confirmed, work closure audit, dependent release, phase initial
and closure audits, integration initial and closure audits, then project completion.

## Audit and remediation flow

Use `audit-remediation` to inspect an existing codebase and convert findings into traced decisions
or integration WORK without inventing a phase:

```bash
devflow init billing-prod-readiness --risk high --workflow audit-remediation
devflow status billing-prod-readiness
devflow render audit billing-prod-readiness --scope integration --mode initial
# auditor writes canonical audit + WORK/DECISIONS
devflow audit apply billing-prod-readiness --scope integration --mode initial
devflow validate billing-prod-readiness
```

The initial audit may complete immediately, request a human decision, or release traced remediation,
evidence, or documentation WORK from `work/integration.yaml`. After that WORK and any required work
reviews are complete, `status` selects the integration closure audit. A passing closure completes
the project. DevFlow computes each next action but never executes or audits it autonomously.

## Project artifacts

```text
.devflow/
├── config.yaml            # runtime protocol compatibility, domains_root, default extension
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

These roots have different jobs. `.devflow/config.yaml` configures the runtime and checks whether
the CLI can safely read or mutate project artifacts. `.devflow/extensions/` contains optional local
audit guidance. The PRD, PLAN, STATE, PITFALLS, DECISIONS, WORK, and AUDIT artifacts live under
`docs/domains/<domain>/` by default. `init` and `status` print `runtime_config`, `domains_root`, and
`domain_dir` so the boundary is visible. Normal initialization does not place domain artifacts
inside `.devflow/`.

Initialize a domain with the `plan` skill, or directly:

```bash
devflow init <domain> --prd <path> --risk high --workflow delivery
```

`docs/` is your personal working directory. DevFlow works with it fully gitignored and never
committed: no lifecycle operation, closure audits included, reads Git history for a file under
`domains_root`. A gitignored `docs/` simply is not shared between machines, which is a handoff
consideration, not a correctness one. Source-code Git use is unchanged: baseline and target SHAs,
phase diff ranges, `devflow phase ref` ancestry checks, and `git show <ref>:<path>` for reading
source all still apply.

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

- Runtime config and STATE protocol compatibility, with malformed or different-major versions
  rejected and newer config versions blocked from mutation
- STATE workflow, lifecycle statuses, required fields, phase keys, and referenced artifact paths
- Delivery placeholder contracts and phase/WORK mismatches, including orphan phase manifests
- Delivery integration gates requiring real verified phases, while audit/remediation can complete
  without fake phases
- Canonical audit front matter, verdict rubric, closure coverage, and evidence for protocol 1.3
  verified states
- Bidirectional finding, decision, and WORK links, including explicit rationale for a WORK that
  aggregates multiple findings
- WORK v2 unique acceptance and verification IDs, nonblank commands, and complete `covers` mappings
- WORK dependencies, decisions, transfers, risk premise checks, review gates, and completion evidence
- Legacy WORK v1 string-shaped acceptance and verification commands without rewriting the file

`validate` is not only a report. Lifecycle mutations reject structural errors before writing, so a
broken manifest cannot ride through to project completion. For protocol 1.3 audits, `audit apply`
performs the same validation against the prospective state before it commits the transition.

## Optional peer skill composition

DevFlow can compose with separately installed Superpowers and Ponytail. DevFlow stays the
lifecycle owner. `core/protocol/skill-composition.md` is the normative contract.

When available:

- Superpowers can provide test-driven-development, systematic-debugging, and
  verification-before-completion disciplines inside the active WORK.
- Ponytail can provide reuse-first and YAGNI guidance during planning, execution, and audit.
  Ponytail observations in an audit are leads that a DevFlow auditor verifies before they become
  findings.

Both integrations are optional. DevFlow does not bundle these plugins, does not require them to
execute a project, and does not switch Ponytail modes. Peer tools do not replace PLAN, WORK,
STATE, AUDIT, lifecycle gates, or remediation. There is no discovery API; a peer capability is
used only when the environment already provides it.

Usage:

1. Optionally enable and configure Superpowers or Ponytail the normal way.
2. Run DevFlow as usual.
3. DevFlow composes compatible peer skills inside its current stage.

Do not run Superpowers subagent-driven-development or executing-plans as a nested controller
inside an active DevFlow lifecycle. DevFlow already owns task selection, reviews, remediation, and
completion, so a nested controller would duplicate the lifecycle.

## Compatibility and protocol version

Plugin version `0.5.0` ships protocol version `1.3.0`. These are separate version domains: the plugin
version identifies the distributed implementation, while the protocol version identifies the
artifact contract that runtime config and STATE declare.

Protocol 1.3 adds explicit workflow type, audit front matter and `audit apply`, lifecycle-aware
render guards, finding/decision/WORK traceability, and WORK v2 acceptance coverage. A protocol 1.2
runtime cannot safely create or mutate those artifacts, which is why this is a protocol minor bump
instead of a plugin-only release.

Protocol 1.0 through 1.2 artifacts remain backward-readable. Missing `workflow_type` defaults to
`delivery` without rewriting STATE. WORK v1 keeps its string-shaped acceptance and verification
commands, existing WORK without `review` retains the required high-risk review gate, and a legacy
`plan_review` without `audit_file` reads as `audits/plan.md`. Existing audit Markdown without YAML
front matter remains readable as a legacy artifact, but it cannot authorize a protocol 1.3 verified
transition. No bulk migration or automatic rewrite is required.

A fresh project initialization records `1.3.0` in both `.devflow/config.yaml` and the domain's
`STATE.yaml`. The config value is a project runtime compatibility guard, while STATE identifies the
domain artifact contract. Older same-major versions are readable. A malformed or different-major
version is an error, and a newer config minor permits read-only status and validation but blocks
mutation.

When `.devflow/config.yaml` exists, its `protocol_version` is a floor. The audit-apply gate decides
from the higher of the STATE and config versions, so hand-editing `STATE.protocol_version` below the
config cannot re-enable `plan-review set`, `work review`, `phase set`, or `integration set`
`verified` on a project `init` recorded at 1.3 or newer, and `validate` reports STATE declaring an
older protocol than the config as an error. A project with no config file, or one whose config
genuinely records the older version, keeps the legacy verified transitions.
