---
name: run
description: Use when executing or resuming DevFlow implementation, remediation, or the computed whole-work finalize action after PLAN/WORK artifacts exist, including requested ELI5 HTML and Newman verification.
---

# DevFlow Run

Operate as the **Executor**. Execute the runtime-selected WORK or whole-work delivery finalization.

## Runtime

Every `devflow` command below runs from the repository root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/devflow.py" <args>
```

If that variable is unset, use this skill's wrapper instead. It resolves the plugin root from its
own location, so the working directory does not matter:

```bash
python3 <this-skill-directory>/scripts/invoke.py <args>
```

## Workflow

1. Run `devflow delivery enable <domain>` to adopt the policy on legacy active work, then run `devflow status <domain>`.
   1. For `run`, follow the single-WORK flow below.
   2. For `finalize`, run `devflow render finalize <domain>` and follow the whole-work procedure in that packet.
2. Run `devflow render run <domain>`, or pass the exact reported WORK id with `--task <ID>`.
   1. Render rejects a different ready item.
   2. The packet inlines the selected item, the authority rules, the WORK item contract, the risk policy, and the domain's `PITFALLS.md`.
3. Read the item's `context` and `pitfalls`, then read `PITFALLS.md`.
   1. These exist so you do not rediscover what the Architect already paid for.
4. **Work through `premise_checks` against current HEAD before editing anything.**
   1. Each entry names a fact to confirm.
   2. If one is false, the premise moved: stop, do not adapt the plan yourself.
5. For a ready item, run `devflow work start <domain> <ID>`.
   1. For an already `in_progress` item, resume it with its existing `evidence.start_sha`; keep the original source baseline intact.
6. Establish the failing test or verification criterion first, where the change admits one.
7. Implement only the coherent change boundary defined by the WORK item, staying inside `scope.allowed`.
   1. Follow repository rules and existing patterns.
   2. Add or retain accurate comments explaining important intent, invariants or constraints in changed executable source.
   3. Record a relevant source anchor and reason under `evidence.comments`.
   4. Pure docs/config/deletion work uses an explained `comments_note`.
   5. Comment usefulness receives independent review.
8. Execute the item's verification commands plus repository-required checks.
   1. For version 2, confirm the executed set covers every acceptance ID.
   2. Verify API and end-to-end criteria at an observable contract layer; static source search alone is not runtime behavior evidence.
9. If a stop condition is reached, run `devflow work block <domain> <ID> --reason "..."` and stop.
   1. Record a decision when human or product authority is required.
10. Commit the verified source/test changes first.
    1. Read the actual `docs/PR/templates.md`, run `devflow delivery paths <domain>`, and generate/update the cumulative PR body and Postman v2.1 collection at those paths against this HEAD.
    2. Preserve the actual branch base, template headings, prior WORK coverage, empty credential variables and honest execution status.
    3. Follow the full `delivery-artifacts` protocol in the rendered packet.
    4. Fill `evidence.delivery` and comment anchors in WORK.
    5. Keep derived output local/ignored; do not alter the source PR template.
    6. When acceptance criteria and these deliverables are supported by evidence, run `devflow work done <domain> <ID> --commit <sha> --command '<cmd> -> <result>' ...`.
    7. It refuses a completion with missing comments, artifacts, source provenance or required command evidence.
    8. A failed completion preserves STATE/WORK.
    9. Unevidenced completion is the failure this protocol exists to prevent.
    10. Keep actual command results in `evidence.commands`; version 2 `covers` metadata does not replace execution evidence.
    11. A completed high/critical item then receives an initial work audit before a dependent can start.
11. If you discovered a trap that outlives this item, add it to `PITFALLS.md`.
12. Run `devflow validate <domain>` and `devflow status <domain>`.
    1. When the computed action is `finalize`, continue as Executor with `devflow render finalize <domain>` and the installed ELI5/Newman procedure.
    2. Hand off actual audit actions to the Auditor.

## Boundaries

- A `run` action handles one WORK item.
  The `finalize` action aggregates all completed work; its confirmed repairs return to the normal single-WORK flow.
- Do not opportunistically fix unrelated findings.
- Do not expand allowed scope to make the implementation easier.
- Evidence remains in the WORK item.
  - The prescribed PR body and Postman collection are delivery outputs under the narrow protocol allowance.
  - Avoid duplicate narrative completion reports.
- Generate files locally.
  - At finalization, execute authorized isolated local/test Newman runs under `core/protocol/finalization.md`. `delivery newman` owns the JSON argv server process group, HTTP 200..299 readiness, Newman run and bounded SIGTERM/SIGKILL cleanup; never skip the run because the server is unavailable.
  - Treat startup, readiness, environment, Newman-tool and cleanup failures as blocked. Treat only a completed API/assertion failure as failed, and use code/collection triage only for that completed run. `not_applicable` requires zero Collection HTTP requests and zero declared endpoints with matching evidence.
  - Postman file generation itself sends no requests.

## Peer execution disciplines

Follow `core/protocol/skill-composition.md`.
The active WORK is the hard execution boundary.

### Behavior-changing WORK

When Superpowers test-driven-development is available, use it before production behavior changes:

1. establish the required behavior from the WORK contract;
2. add or identify a test that fails for the expected reason;
3. make the minimum production change;
4. verify the targeted test passes;
5. run the WORK verification DevFlow requires.

Explicit repository or user instructions already carry sufficient authority for a TDD exception.
Do not halt the run to ask again for permission that repository or user instructions already grant.
This does not weaken TDD in general.

### Defect and remediation WORK

When systematic-debugging is available:

1. reproduce or verify the defect;
2. identify evidence for the root cause;
3. avoid speculative fixes;
4. add regression coverage when behavior changes;
5. implement the minimum confirmed fix;
6. execute the WORK verification.

### Completion

Before reporting a WORK complete, use verification-before-completion when available.
Fresh verification evidence must support the same behavior the WORK verification criteria require.
Record the actual executed evidence through `devflow work done`.
Never record peer-skill invocation itself as proof that the WORK passed.

### Ponytail

Apply the currently active Ponytail policy when available.
Prefer reuse and the smallest implementation that satisfies the WORK.
Ponytail must not widen or shrink required WORK scope, remove acceptance criteria, weaken security or validation, skip required tests, bypass premise checks, or bypass DevFlow lifecycle gates.
Do not change Ponytail mode automatically.

### Lifecycle ownership

One invocation executes exactly one selected ready WORK item.
Do not invoke peer controller workflows that select multiple tasks, dispatch subagents, create worktrees, run a separate final review, or finish branches.

Finish with WORK ID, changed files, comment anchors, PR/Postman paths, structural verification and actual API execution status, deviations/discoveries, status, and the next DevFlow action.
