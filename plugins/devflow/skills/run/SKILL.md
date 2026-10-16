---
name: run
description: Use when executing or resuming DevFlow implementation, remediation, or the computed whole-work finalize action after PLAN/WORK artifacts exist, including requested ELI5 HTML and Newman verification.
---

# DevFlow Run

Operate as the **Executor**. Execute the runtime-selected WORK or whole-work delivery finalization.

## Runtime

Every `devflow` command below runs from the repository root.
Use this skill's wrapper. It resolves the plugin root from its own location, so it works under both
the Claude Code and the Codex adapter and the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

Under Claude Code only, the runtime path is equivalent when the variable is set:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

## Workflow

1. Run `devflow delivery enable <domain>` for active legacy domains, then `devflow status <domain>`.
2. For `run`, use `devflow render run <domain> [--task <ID>]` and execute its full single-WORK packet. Do not select a different item.
3. Confirm `premise_checks` against HEAD before editing. Stop on a failed premise, missing decision, external evidence wait, or required scope expansion.
4. For one selected ready WORK item, run `devflow work start <domain> <ID>`. Resume
   `in_progress` work without replacing its recorded `evidence.start_sha` or
   `evidence.delivery.branch`.
5. Test, implement, and verify within WORK scope. Commit source and tests, then update the cumulative PR/Postman outputs and WORK evidence under `core/protocol/delivery-artifacts.md`.
6. Use `devflow work done <domain> <ID> --commit <sha> --command '<command> -> <result>'` only for executed and evidenced acceptance. Hand off the computed audit to the Auditor.
7. Run `devflow validate <domain>` and `devflow status <domain>`.
8. For `finalize`, use `devflow render finalize <domain>` and `core/protocol/finalization.md`; the runtime selects the whole-work action. `delivery newman` is an owned-server test, never a simulated pass.

## Boundaries

- One invocation performs only its selected WORK or computed whole-work `finalize` action. Never expand WORK scope or bypass independent reviews.
- Keep evidence in WORK; preserve the narrow derived PR/Postman and ELI5/Newman allowance of `core/protocol/delivery-artifacts.md` and `core/protocol/finalization.md`.
- Keep generated private outputs local. Newman availability and server failures are blockers, not fabricated `not_applicable` results.

## Peer execution disciplines

Read `core/protocol/skill-composition.md` when peer skills are available. Keep the active WORK as the hard execution boundary.
For behavior changes, apply `test-driven-development` when available; for defects, select one applicable `diagnosing-bugs` or `systematic-debugging` workflow. Use `verification-before-completion` when available.
Fresh verification evidence must match WORK acceptance; record observed commands via `devflow work done`. Peer invocation alone is not proof.
Apply the active Ponytail reuse policy without weakening security, acceptance, review gates, or scope. Do not change Ponytail mode automatically.
One invocation executes one selected ready WORK item; never delegate lifecycle ownership to peer controllers.

Finish with WORK ID, changed files, comment anchors, PR/Postman paths, structural verification and actual API execution status, deviations/discoveries, status, and the next DevFlow action.
