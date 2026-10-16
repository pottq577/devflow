---
name: audit
description: Independently audit a DevFlow plan, work, phase, or whole integration using repository evidence, then classify findings and generate remediation/evidence WORK directly. Use for plan review, work review, phase review, closure review, and cross-phase integration review in a fresh reviewer session.
---

# DevFlow Audit

Operate as the **Auditor** in an independent review context.
Verify repository facts directly.

## Runtime

Every `devflow` command below runs from the repository root.
Use this skill's wrapper. It resolves the plugin root from its own location, so it works under
both the Claude Code and the Codex adapter and the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

Under Claude Code only, the runtime path is equivalent when the variable is set:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

## Workflow

1. Run `devflow status <domain>` and use the exact computed scope, mode, phase, and WORK ID. Prefer a fresh review context.
2. Run `devflow render audit <domain> --scope <scope> --mode <initial|closure> [--task <ID>] [--phase <XX>]` and follow the complete Auditor packet.
3. Pin the audited Git range and independently inspect source, tests, requirements and WORK evidence. Read old reports as leads, not conclusions; do not switch an occupied tree.
4. Write one canonical `audits/` Markdown with schema-conformant YAML front matter. Use `core/protocol/audit-core.md` and `core/protocol/risk-policy.md` for classification, severity, closure and findings-to-WORK links.
5. Never record `pass` without commands actually executed and their observed results. Preserve unknown evidence and unresolved product decisions.
6. Record linked WORK, decisions and durable pitfalls, then run `devflow audit apply <domain>` with the exact rendered arguments. Never edit STATE directly.
7. Run `devflow validate <domain>` and `devflow status <domain>`; report the verified result and next action.

## Peer audit lenses

Read `core/protocol/skill-composition.md` when peer skills are available.

Treat every Ponytail observation as a lead. For each potential finding, independently verify it against requirements, callers, tests and the pinned range before it enters the normal DevFlow AUDIT artifact.
Use `web-design-guidelines`, `differential-review`, `spec-to-code-compliance`, or `codebase-design` as applicable lenses under `core/protocol/skill-composition.md`. Peer results do not create their own review or finding lifecycle.

## Closure mode

Independently verify closure against previous findings and fresh regressions. Preserve active finding severity and follow the recovery commands in `core/protocol/audit-core.md` after a `stop` finding is resolved.

Finish with verdict, SHAs and diff range, finding counts by classification and severity, generated WORK IDs, unresolved decisions, residual risk, and next action.

## Delivery-specific review

Apply `core/protocol/delivery-artifacts.md` to source comments, branch PR and Postman evidence. Distinguish structural checks from executed HTTP verification.
Run `devflow delivery check <domain>` for phase/integration scopes and add `--final` at integration closure.
Work audits inspect only their own source, comments, and branch evidence; `audit apply`
owns the domain-wide `delivery check` before advancing lifecycle state.

## Whole-work finalization review

The whole-work review checklist and its acceptance bar live in the rendered audit packet and in
`core/protocol/finalization.md`.
The rendered audit packet carries the review checklist; apply it there. Preserve independent audit
gates: finalization evidence authorizes handoff, and the Auditor verifies its truth.
