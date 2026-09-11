# Whole-work explanation and executed API verification

## Contents

- Scope and lifecycle
- Installed ELI5 skill
- Newman execution and evidence
- Diagnosis, repair and commits
- Final receipt and compatibility

## Scope and lifecycle

Protocol 1.8 adds owned server lifecycle evidence to `STATE.delivery.finalization.version: 1` for new domains and for `delivery enable` adoption.
The Executor owns this delivery stage.
Existing WORK, risk-review, phase-audit and integration-audit gates retain their authority.
The runtime executes explicit foreground commands; the host agent follows the rendered procedure.

The computed action `finalize` has role `executor`, scope `project`, and project status `delivery_finalization`.
It is selected at integration handoff once implemented WORK exists, and again after integration remediation changes the scope.
A phase-free initial audit may first identify implementation WORK.
Each ordinary `run` still handles exactly one WORK.
Finalization aggregates the whole domain and may create a bounded integration remediation WORK, then returns to the ordinary WORK executor.
It never bypasses an independent review or approves a merge.

The output set is:

- One cumulative PR and Postman collection for every delivered branch (existing policy).
- One `docs/explanations/<domain-slug-hash>/implementation.html` for this entire domain/run.
- A sanitized JSON summary per Newman attempt under `docs/postman/<domain-slug-hash>/newman/`.
- Private raw diagnostics under `.devflow/private/newman/<run-id>/`, excluded locally from Git.

The narrow allowance covers these derived files and existing STATE/WORK records.
Implementation changes remain inside approved WORK scope.
Keep `docs/` private/ignored when that is repository policy.
Never force-add the generated documents or require their initial Git history.

## Installed ELI5 skill

After branch PR/collections are current, run `devflow delivery context <domain>`.
Its snapshot includes the complete PRD/PLAN/DECISIONS hashes, every WORK including cancelled or transferred scope, every branch/base/head and its deliverable hashes, and all Newman runs/diagnoses.
Read all referenced WORK and source changes.
Use pinned `git show`/diff ranges to inspect other branches without disturbing another session.
Include cross-branch interactions and the end-to-end user/business flow.
The current branch or the last WORK alone cannot define this explanation.

Invoke the host's **installed `eli5` skill** (Codex `$eli5`) after reading its actual `SKILL.md`.
Prefer the host's discovery result; pass its actual path with `--skill-file`.
Fallback discovery checks project/user `.agents/skills/eli5` and Codex skills directories.
Follow that skill's real interface and assets.
Do not invent an `eli5` shell executable, duplicate its implementation, or claim that merely reading the skill means it ran.
Missing ELI5 remains a clear finalization blocker; retain completed implementation and outputs.

Ask ELI5 to write the single path returned by `delivery context` as complete, self-contained HTML: use the user's language, explain purpose, changed behavior, end-to-end flow, branch/WORK contributions, design reasons, meaningful comment examples, API usage, executed tests and limits.
Include an honest disposition for every WORK ID in visible content and source references that let a maintainer locate the implementation.
Embed styles/assets locally in the HTML; no CDN, external script, iframe, telemetry, credentials or raw response payloads.
Follow installed ELI5 presentation guidance while preserving these scope and privacy requirements.

Copy the exact `html_metadata` object from context into one HTML comment:
`<!-- devflow-explanation: {the exact metadata object} -->`.
Then record actual invocation evidence:

```bash
devflow delivery explain <domain> --skill-file <actual-eli5-SKILL.md> --invocation '<actual host invocation and context used>'
```

The first draft precedes Newman.
After any Newman attempt, diagnosis, repair, branch artifact update or scope change, obtain fresh context, invoke ELI5 to update the complete explanation, and record `explain` again.
Final HTML must describe the final tested commits and actual test results.
Runtime verifies scope/content hashes, visible WORK coverage and skill-file provenance.
Semantic quality and truthful skill invocation remain independent audit responsibilities.

## Newman execution and evidence

The requested automatic tests authorize ordinary **isolated local/test** execution.
Discover the project's documented startup, test data, authentication and cleanup first.
Confirm its actual server build/commit and migrations.
Use synthetic fixtures; mock payment, SMS, email and other external side effects.
A localhost URL alone proves neither test data nor isolation.
Production calls, real payments, destructive shared-data operations, new remote access and unapproved installation remain separate decisions.
Missing tools/server/credentials are execution blockers, never successful tests or immediate code-defect classifications.

Use an installed, repository-approved Newman binary (`--newman-bin` may name its path).
Node and Newman are execution prerequisites; the Python runtime never silently installs an npm package.
For **each** recorded branch, prepare a server build containing that branch's delivered commit and use a workspace with HEAD matching that build.
A verified integration build can cover several branches if it contains all their commits.
Use an existing isolated worktree when repository policy allows it.
Carry the canonical domain/derived files as local files when needed; integrate returned evidence under one writer.
Keep source refs pinned and do not switch an occupied tree.

```bash
devflow delivery newman <domain> --branch <exact-branch> \
  --base-url http://127.0.0.1:8080 \
  --server-command '["./build/test-server","--port","8080"]' \
  --readiness-url http://127.0.0.1:8080/health \
  --server-sha <verified-build-commit> \
  --environment <local-secret-environment.json> \
  --safety-note '<how build identity, synthetic fixtures and external integrations were verified>'
```

`--server-command` is a JSON argv array. DevFlow starts it directly in a new process group, so
shell command strings and `shlex.split` are not part of the execution contract. The runtime owns
the complete sequence: start the server, poll readiness, run Newman, judge the result and stop the
server. It requires the readiness response to be HTTP 200 through 299. The default readiness
timeout is 60 seconds and it is bounded to 1 through 600 seconds.

The process and its process group must be alive both when readiness succeeds and immediately before
Newman starts. If the owned process exits while another process returns 2xx at the readiness URL,
the run is blocked and Newman is not executed.

Cleanup sends bounded SIGTERM, waits up to 5 seconds, sends SIGKILL when needed, waits up to 2 more
seconds and confirms that the owned process group is gone. Cleanup evidence is recorded separately
from Newman evidence. A Newman pass followed by cleanup failure is blocked, not passed.

Keep the original secret environment outside the repository or in an existing ignored secrets directory; the wrapper only removes its temporary copy.
Omit `--environment` when unnecessary.
Add `--allow-writes` only after confirming write scenarios use disposable test data and safe integrations.
An approved remote test host additionally needs `--allow-host <exact-hostname>`.
Never include credentials in command arguments or safety notes.
Default total timeout is 120 seconds and per-request timeout 10 seconds, configurable up to 3600.

The wrapper snapshots the collection, supplies a private environment, invokes full-collection Newman in the foreground with JSON reporting, request/script timeouts, redirect suppression and restricted file reads.
This conservative execution profile supports explicit ordered requests, inline request data and ordinary `pm.test` assertions.
Use collection variables to capture IDs.
Avoid hidden `pm.sendRequest`, skip/loop/request-jump behavior, baseUrl mutation and external file uploads; these need a separately reviewed execution profile.
Static checks are not a sandbox: review scripts and isolate the target before authorizing execution.

Passing requires exit code zero, exactly the expected executed request count, actual responses, non-skipped assertions for every request, and zero request/assertion/report failures.
Never use `--suppress-exit-code`, `--insecure`, `|| true`, folder-only coverage, assertion deletion, relaxed expected responses, or arbitrary sleeps to manufacture a pass.
Only a collection with zero HTTP request items and an empty declared endpoint list may record
`not_applicable`. The summary must include the current collection hash, source hash, zero request
count, empty declared endpoints and the recorded no-HTTP assessment. Missing or failed servers,
readiness, environment configuration or Newman are never `not_applicable`.

Return codes: 0 = passed or proven no-HTTP N/A, 1 = Newman completed with API/assertion failure,
2 = startup, readiness, environment, Newman-tool or cleanup blocker.
**Attempted Newman execution persists its result despite a nonzero return.**
Rejected preflight leaves run history unchanged because no test was attempted.
Sanitized summaries contain counts, classifications' source ids and hashes, never resolved credentials, response bodies or arbitrary exception messages.
Read sensitive raw JSON and stdout only locally.
Raw files are mode 0600 beneath private mode-0700 directories; their hashes support local revalidation, and `.git/info/exclude` protects ordinary staging.
The temporary resolved environment is removed after execution. Keep raw evidence through closure.

## Diagnosis, repair and commits

Inspect the actual failing request/assertion, private report, server logs, controller/DTO/auth contract, accepted PRD/PLAN and reproducible test before classifying.
Expected HTTP error scenarios may be successful tests when their assertions match the contract.
HTTP status alone gives no root cause. Use:

- `code`: accepted contract is sound; implementation violates it.
- `collection`: implementation matches the accepted contract; request/auth/fixture/expected-result or assertion is wrong.
- `environment`: startup, build identity, test data, network, tool or credential setup is missing.
- `unknown`: evidence remains ambiguous; record the unresolved question and keep finalization open.

For code/collection, author one normal bounded remediation WORK in the domain's canonical integration WORK file.
Use the existing WORK schema and a fresh id, with `origin.findings: [NEWMAN-<run-id>]`, `references` including the sanitized summary path, explicit allowed files, acceptance criteria, reproduction/regression commands and dependencies.
Use a justified risk classification and the usual required work-review gate.
Do not rewrite completed WORK or reopen a verified integration; subsequent defects use a new repair domain.

```bash
devflow delivery triage <domain> --run-id <failed-run-id> \
  --classification code --work-id <repair-WORK-id> \
  --reason '<contract evidence, reproduction and exact root cause>'
```

Use `collection` for collection defects.
Environment/unknown classification omits `--work-id`.
Triage registers the finding; the next normal `run` executes its repair.
Establish a failing regression first, fix the root cause within scope, run repository checks, and **commit the verified source/test change** before ordinary `work done`.
Collection defects require a meaningful tracked collection/generator or regression-test/fixture change under repository policy.
If the generated collection is ignored, commit its reproducible regression fixture/test or generator correction, then regenerate the ignored output; do not force-add private docs or create an empty fix commit.
An environment-only correction records setup evidence and reruns without a fabricated code commit.

After every repair commit: rebuild/restart the verified server, update affected branch PR and collection provenance, refresh their hashes, and rerun affected branches plus required regression coverage.
A successful rerun's server commit must contain the repair commit.
Correct PR test results at the same source HEAD with `delivery refresh`; if the collection content changed, rerun it.
Update the whole ELI5 HTML last.
Keep all failed attempts and diagnoses.

Limit each uninterrupted diagnosis loop to three attempted root-cause fixes.
Persistent failures, new product ambiguity or scope expansion become a blocked WORK/decision for review.
Never broaden an assertion just because the implementation currently returns a different result.

## Final receipt and compatibility

```bash
devflow delivery check <domain> --final
devflow delivery finalize <domain>
devflow validate <domain>
devflow status <domain>
```

`finalize` requires terminal WORK, current branch artifacts/source tips, fresh ELI5 evidence, current successful/N/A branch runs, intact private report/summary hashes, and traced committed repairs for every code/collection failure.
It records a content-addressed receipt.
It authorizes only the handoff to the original independent integration audit, never push/merge/publication.
New evidence or content changes invalidate the receipt; finalization repeats after remediation.

`delivery enable` upgrades an existing domain additively, preserves PLAN/WORK bytes and the original grandfathered set, and never exempts additional work on repeated calls.
Legacy domains without this optional field retain their previous behavior until adoption.
Already-done legacy WORK is explained with its recorded limits; no old API execution evidence is invented.
