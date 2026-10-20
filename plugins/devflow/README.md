# DevFlow plugin

DevFlow runs repository-grounded planning, one-item implementation, independent audits, and delivery finalization. Use this page to start or resume a domain, choose a skill, and run verification. The authoritative rules live in [`core/protocol/role-instructions.md`](core/protocol/role-instructions.md), its owned protocols, and `core/schemas/`.

Plugin version `0.12.0` ships artifact protocol `1.8.0`. See [CHANGELOG](CHANGELOG.md) for historical behavior and release notes; historical design reviews are available only through Git history.

## Requirements and entrypoints

Install Python 3.10+ and the Python dependencies from the plugin directory:

```bash
python3 -m pip install -r requirements.txt
```

All commands below run from the consuming repository root. Use the installed skills for conversational operation, or the `devflow` CLI wrapper for explicit commands. Each skill resolves its own plugin path on Claude Code and Codex; `bin/devflow` is an optional PATH wrapper.

| Skill | Responsibility |
| --- | --- |
| `plan` | Architect: PRD to repository-grounded PLAN, WORK, and decisions |
| `run` | Executor: the selected WORK or whole-work finalization |
| `audit` | Auditor: independent plan, work, phase, or integration review |
| `status` | Read the computed state and next action |
| `goal` | Host-native foreground Goal supervisor |
| `autopilot` | Standalone routed-controller entrypoint and diagnostics |

The runtime computes the next action from STATE and WORK. Do not select a different WORK, bypass a review, or manually edit machine-owned state. Role instructions come from the rendered packet; skill wrappers are entrypoints, not copies of protocol rules.

## Start or resume a domain

Initialize a new delivery domain from approved requirements, or adopt a legacy domain without resetting completed WORK:

```bash
devflow init <domain> --prd <path>
devflow delivery enable <domain>
devflow status <domain> --json
```

Use `devflow status <domain>` before each action. The reported next action determines the role, scope, mode, and WORK target. For audit-only remediation of an existing codebase, initialize with `--workflow audit-remediation`; it does not invent phases.

### Manual plan, run, and audit

Render the indicated role's authoritative instructions, perform the bounded work, and record evidence through the CLI:

```bash
devflow render plan <domain>
devflow render run <domain> --task <ID>
devflow work start <domain> <ID>
devflow work done <domain> <ID> --commit <sha> --command '<command> -> <result>'
devflow render audit <domain> --scope work --task <ID> --mode initial
devflow audit apply <domain> --scope work --task <ID> --mode initial
```

These are example command shapes, **not** a sequence to execute unconditionally. `status` chooses which command is valid; an audit might target `plan`, `phase`, or `integration` rather than `work`. `render` and `audit apply` reject mismatched scope or target. Source changes require an ordinary WORK; completed audits are applied from canonical Markdown and schema-conformant YAML front matter.

Use `devflow validate <domain>` to check artifacts without silently rewriting them. Record unresolved decisions in DECISIONS and operational traps in PITFALLS. The lifecycle rules and command guards live in [`lifecycle.md`](core/protocol/lifecycle.md), [`work-item-contract.md`](core/protocol/work-item-contract.md), and [`audit-core.md`](core/protocol/audit-core.md).

Use `devflow requirements inspect <domain>` for the canonical read-only JSON snapshot. The human checklist and JSON report use that same snapshot:

```bash
devflow requirements report <domain>                 # print Markdown checkboxes
devflow requirements report <domain> --format json   # print JSON
devflow requirements report <domain> --write         # regenerate both local reports
```

`--write` produces `REQUIREMENTS_STATUS.md` and `REQUIREMENTS_STATUS.json` inside the domain directory without changing STATE, PRD or WORK. Checked boxes mean implementation plus passing verification, not product approval. The command still returns nonzero on snapshot diagnostics errors; the generated files contain those findings. These are derived local views, not extra authoritative lifecycle records.

For new `traceability_version: 1` domains, final ELI5 HTML must include a verified
requirement table derived from the **current** P04 snapshot (not stored reports).
Its evidence hash is pinned with the existing Newman/WORK finalization scope and
receipt. See [`finalization.md`](core/protocol/finalization.md) for the exact HTML
contract. Existing domains without strict source traceability remain compatible.

## Run Goal or Autopilot

In a Codex session with host-native subagents, invoke the `goal` skill. It uses the host supervisor to dispatch one routed specialist at a time; it does **not** start nested `codex exec` or the standalone Autopilot controller.

Use these commands for standalone foreground operation and inspection:

```bash
devflow autopilot capabilities
devflow autopilot bootstrap <domain> --requirements-file <path>
devflow autopilot start <domain> --until plan
devflow autopilot start <domain> --until implementation
devflow autopilot start <domain> --until complete
devflow autopilot status <domain>
devflow autopilot resume <domain> --until complete
```

`--until plan` stops after planning and required plan review; `--until implementation` stops before integration/finalization; `complete` runs the full lifecycle. These staged boundaries apply only to delivery workflows. Resume an interrupted run when its operational state must be preserved; use a fresh start for a new stage.

The active routing aliases and model capabilities are defined in `core/routing/default.yaml` and `core/routing/models.yaml`. Read [`host-telemetry.md`](core/protocol/host-telemetry.md) for hosted leases, step fencing, recovery, checkpoints, and telemetry. A pending live or unconfirmed child is a blocker, not evidence of termination. Read [`skill-composition.md`](core/protocol/skill-composition.md) for optional Superpowers, Ponytail, Vercel, Matt Pocock, and Trail of Bits peer disciplines; peer skills never replace DevFlow lifecycle authority.

## Rendered context and evidence

`devflow render <action>` emits the applicable role contract and selected protocol documents. Plan receives the approved PRD; Run receives one WORK and linked requirements; Audit receives scope-specific context. Finalize uses a paged WORK manifest rather than inlining every WORK body.

For bounded read-only Scout/Diagnostician navigation, use:

```bash
devflow render evidence <domain>
devflow status <domain> --no-refresh
devflow render run <domain> --no-refresh
```

Hosted child renders pin `--expected-head` and `--expected-fingerprint`. A changed pin stops execution without a partial packet or STATE mutation; `--check-only` verifies pins before compact scout-backed execution. Scout capsules are reused only with valid creation evidence and current source fingerprints. Consult the rendered packet and [`host-telemetry.md`](core/protocol/host-telemetry.md) for complete constraints.

## Domain artifacts and delivery

A domain records its intent, work, review, and progression under `docs/domains/<domain>/`:

```text
PRD.md              Product requirements
PLAN.md             Implementation plan
STATE.yaml          Runtime-owned lifecycle state
DECISIONS.md        Human decisions
PITFALLS.md         Verified domain traps
work/               Phase and integration WORK manifests
audits/             Canonical plan, work, phase and integration audits
```

For each source-changing WORK, commit verified source and tests first, then update the cumulative branch PR body and Postman collection using the generated paths:

```bash
devflow delivery paths <domain>
devflow delivery refresh <domain> --branch <name>
devflow delivery check <domain>
```

Source comments, evidence fields, branch ranges, PR-template fidelity, API coverage, and local-only artifact rules belong to [`delivery-artifacts.md`](core/protocol/delivery-artifacts.md). Documentation-only WORK uses a justified source-comment exception. A non-HTTP branch still has an explained, importable empty collection. Offline collection validation is not evidence of executed HTTP tests.

### Whole-work finalization

When finalization is enabled, the Executor refreshes every branch's delivery evidence, runs installed Newman against an approved isolated test server, triages/repairs failures through traced WORK, then invokes installed ELI5 to generate one domain-wide HTML explanation. Only fresh successful or proven non-HTTP run evidence can authorize finalization; independent integration audits still apply.

```bash
devflow render finalize <domain>
devflow delivery newman <domain> --branch <name> --base-url <test-url> \
  --server-command '["./build/test-server","--port","8080"]' \
  --readiness-url <readiness-url> --server-sha <build-sha> \
  --safety-note '<isolation evidence>'
devflow delivery finalize <domain>
```

Install ELI5 and Node/Newman separately for enabled finalization. Do not treat a simulated, skipped, or structurally checked Newman run as executed verification. Follow [`finalization.md`](core/protocol/finalization.md) for server ownership, readiness, cleanup, triage, provenance, and ELI5 invocation; no automatic push, merge, or remote publication occurs.

## Decision traceability

`devflow decision technical` records developer-owned implementation choices;
`devflow decision assume` records reversible provisional policy, and `approve`, `reject`,
`reconcile`, and `list` manage its explicit product lifecycle. WORK carries
`origin.technical_decisions` / `origin.policy_assumptions` references. Pending product
confirmation does not block unrelated WORK but prevents integration closure. Refer to
[`decision-policy.md`](core/protocol/decision-policy.md) for required fields and restrictions.

## Compatibility and verification

Artifact protocol `1.8.0` reads older compatible STATE/WORK documents without rewriting them. Newer or incompatible versions block mutation. See [`lifecycle.md`](core/protocol/lifecycle.md) for compatibility rules.

For documentation changes, run `python3 plugins/devflow/scripts/check_docs.py --json` from the marketplace root, then the affected documentation tests. For merge/release decisions, follow [`release-validation.md`](core/protocol/release-validation.md). The release gate requires actual Newman smoke-test evidence.

Native hosted Goal end-to-end acceptance and invocation of the installed ELI5 skill remain pending. CLI packet measurements and historical release notes are recorded in [CHANGELOG](CHANGELOG.md) and [`release-validation.md`](core/protocol/release-validation.md); they are not model-token or native Goal acceptance evidence.
