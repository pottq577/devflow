# DevFlow plugin

DevFlow runs repository-grounded planning, one-item implementation, independent audits, and delivery finalization. Use this page to start or resume a domain, choose a skill, and run verification. The authoritative rules live in [`core/protocol/role-instructions.md`](core/protocol/role-instructions.md), its owned protocols, and `core/schemas/`.

Plugin version `0.11.1` ships artifact protocol `1.8.0`. See [CHANGELOG](CHANGELOG.md) for historical behavior and release notes; historical design reviews are available only through Git history.

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

## Compatibility and verification

Protocol `1.8.0` supports older compatible STATE/WORK documents without bulk rewriting. Missing optional fields remain subject to the runtime's version-aware validation, and newer or incompatible protocol declarations block mutation. Refer to [`lifecycle.md`](core/protocol/lifecycle.md) for authoritative version and migration behavior.

Use these commands from the marketplace root for documentation changes and focused regression checks:

```bash
python3 plugins/devflow/scripts/check_docs.py --json > /tmp/devflow-docs.json
python3 plugins/devflow/tests/test_documentation_history.py
python3 plugins/devflow/tests/test_docs_consistency.py
```

For a new *release decision*, the full gate runs a fresh, unfiltered suite and records both the verdict and per-test evidence:

```bash
python3 plugins/devflow/tests/release_gate.py --mode release \
  --report /tmp/devflow-release-verdict.json
```

The release gate requires actual Newman smoke-test execution and a clean plugin tree. Development-focused checks are not a substitute for that release verdict. See [`release-validation.md`](core/protocol/release-validation.md).

To compare real CLI-rendered Plan, Run, Audit, Finalize and Scout bytes between revisions, run:

```bash
python3 plugins/devflow/tests/measure_role_packets.py \
  --baseline-ref 00af6394f7a7830bb9b37c6560e3ec06598e4ad0 \
  --output /tmp/devflow-packets.json
```

The comparison does not measure agent tokens or native Goal end-to-end performance. Native hosted Goal end-to-end acceptance and actual invocation of the installed ELI5 skill remain pending. Read [CHANGELOG](CHANGELOG.md) for release history and CLI benchmark caveats.
