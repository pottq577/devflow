# Newman Server Lifecycle Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `devflow delivery newman` own server startup, readiness, Newman execution, result classification, and bounded process-group cleanup, while making `delivery finalize` reject every HTTP branch without fresh successful lifecycle evidence.

**Architecture:** Keep orchestration in the existing `devflow_newman.execute` entry point. It will parse an argv JSON array, launch one owned process group, poll an HTTP readiness URL for 2xx, verify the owned process remains alive before Newman, run the existing private Newman profile, and always clean up with SIGTERM, SIGKILL fallback, and group-exit verification. `devflow_finalization` will validate the recorded lifecycle and no-HTTP evidence without adding a second controller.

**Tech Stack:** Python 3.10 standard library (`subprocess`, `signal`, `time`, `urllib.request`, `json`, `hashlib`), PyYAML, existing unittest-style subprocess fixtures, Postman v2.1 JSON.

**Spec:** `docs/superpowers/specs/2026-09-11-newman-server-lifecycle-design.md`

## Global Constraints

- Work only on repository branch `main`; do not create branches or worktrees.
- Plugin version becomes `0.8.1` because the repository already contains the released `0.8.0` entry.
- Protocol version becomes `1.8.0`; existing `1.7.0` artifacts stay readable but old finalization runs cannot satisfy the new gate without rerun.
- An HTTP branch needs `--server-command` as a JSON argv array and `--readiness-url`; no shell or `shlex.split`.
- Readiness accepts only HTTP status `200` through `299` with a bounded condition-based timeout.
- Startup, readiness, environment, Newman tool, and cleanup failures are `blocked`; completed Newman API/assertion failures are `failed`.
- `code` and `collection` triage requires a completed Newman `failed` run with successful server lifecycle.
- `not_applicable` requires zero Collection leaf requests, zero declared API endpoints, and matching persisted no-HTTP evidence.
- No credentials, response bodies, arbitrary exception text, or generated private reports enter tracked artifacts.

---

### Task 1: Update the protocol and release contract

**Files:**
- Modify: `plugins/devflow/scripts/devflow.py:29,3710-3720`
- Modify: `plugins/devflow/core/schemas/state.schema.yaml:delivery_finalization`
- Modify: `plugins/devflow/core/templates/STATE.yaml:1,finalization`
- Modify: `plugins/devflow/core/protocol/finalization.md:80-175`
- Modify: `plugins/devflow/core/protocol/delivery-artifacts.md:whole-work handoff`
- Modify: `plugins/devflow/core/prompts/finalize.md:1-35`
- Modify: `plugins/devflow/skills/run/SKILL.md:whole-work finalization`

**Interfaces:**
- Produces the CLI contract consumed by `devflow_newman.execute`: `args.server_command`, `args.readiness_url`, and `args.readiness_timeout`.
- Produces the persisted run contract consumed by `finalization.structural_errors` and `finalization.final_errors`: `server_lifecycle` and `no_http_evidence`.

- [ ] **Step 1: Write the failing contract assertions**

Add tests that assert the parser exposes the new options, rendered finalize instructions mention owned server startup and cleanup, and the state schema/template identify protocol `1.8.0` and lifecycle evidence.

- [ ] **Step 2: Run the focused contract checks**

Run:

```bash
python3 plugins/devflow/tests/test_finalization.py
```

Expected: FAIL because the parser, documentation, and protocol values still describe the 1.7.0 external-server flow.

- [ ] **Step 3: Apply the minimum contract changes**

Use `PROTOCOL_VERSION = "1.8.0"`, add the three Newman options without making them argparse-required because empty Collections do not need them, and document that runtime rejects their absence for HTTP Collections. Define `server_lifecycle` fields for ordered events, readiness status/code, cleanup status, private log path/hash, and separate Newman and cleanup outcomes. Define `no_http_evidence` fields for collection hash, source hash, zero request count, empty declared endpoints, and the API assessment.

- [ ] **Step 4: Rerun the focused contract checks**

Run:

```bash
python3 plugins/devflow/tests/test_finalization.py
```

Expected: The new parser/document assertions pass; behavior assertions remain red until Tasks 2 and 3.

- [ ] **Step 5: Commit the contract-only changes**

```bash
git add plugins/devflow/scripts/devflow.py plugins/devflow/core/schemas/state.schema.yaml plugins/devflow/core/templates/STATE.yaml plugins/devflow/core/protocol/finalization.md plugins/devflow/core/protocol/delivery-artifacts.md plugins/devflow/core/prompts/finalize.md plugins/devflow/skills/run/SKILL.md plugins/devflow/tests/test_finalization.py
git commit -m "feat: require owned server lifecycle for Newman"
```

### Task 2: Add failing runtime lifecycle tests

**Files:**
- Modify: `plugins/devflow/tests/test_finalization.py:fake_newman,run_newman`
- Modify: `plugins/devflow/tests/test_newman_integration.py:real-Newman fixture`

**Interfaces:**
- Consumes: Task 1 CLI options and evidence names.
- Produces: deterministic fixtures covering `delivery newman` server ownership, liveness, readiness, failure classes, cleanup, and strict no-HTTP evidence.

- [ ] **Step 1: Add a reusable owned-server fixture**

Create a temporary Python server script in the test repository and pass it as a JSON argv list such as `json.dumps([sys.executable, str(server_script), str(port)])`. Use a loopback HTTP server that serves `/health` with 200 and the tested API path with the configured response. Add marker files or a process-exit mode so tests can observe whether Newman was invoked and whether the server exited between readiness and Newman.

- [ ] **Step 2: Add the red tests**

Cover these exact behaviors with named unittest methods: `test_http_newman_requires_owned_server_command`, `test_startup_failure_is_blocked_and_persisted`, `test_readiness_requires_2xx_and_newman_does_not_run`, `test_owned_server_exit_blocks_even_when_readiness_endpoint_is_2xx`, `test_newman_api_failure_is_failed_not_blocked`, `test_cleanup_failure_after_newman_pass_is_blocked`, `test_no_http_run_records_matching_evidence`, `test_finalize_rejects_http_run_without_lifecycle_evidence`, and `test_code_collection_triage_rejects_blocked_run`.

The tests must assert persisted STATE status and reason codes, Newman invocation markers, cleanup outcome fields, return codes, and finalization refusal. The no-HTTP test must assert the Collection and declared endpoint proof is present and that changing either proof makes finalization fail.

- [ ] **Step 3: Run only the new tests to verify RED**

Run:

```bash
python3 -m unittest plugins.devflow.tests.test_finalization.FinalizationTests.test_http_newman_requires_owned_server_command
python3 -m unittest plugins.devflow.tests.test_finalization.FinalizationTests.test_startup_failure_is_blocked_and_persisted
python3 -m unittest plugins.devflow.tests.test_finalization.FinalizationTests.test_readiness_requires_2xx_and_newman_does_not_run
```

Expected: FAIL because `delivery newman` neither accepts nor owns a server process.

- [ ] **Step 4: Commit the failing regression tests**

```bash
git add plugins/devflow/tests/test_finalization.py plugins/devflow/tests/test_newman_integration.py
git commit -m "test: cover Newman server lifecycle gates"
```

### Task 3: Implement the owned server lifecycle

**Files:**
- Modify: `plugins/devflow/scripts/devflow_newman.py:imports,execute`
- Modify: `plugins/devflow/scripts/devflow.py:Newman parser options`

**Interfaces:**
- Consumes: JSON argv from `args.server_command`, validated `args.readiness_url`, and `args.readiness_timeout`.
- Produces: `server_lifecycle` evidence with event order and separate `newman` and `cleanup` outcomes; returns overall status `passed`, `failed`, or `blocked`.

- [ ] **Step 1: Parse and validate argv without a shell**

Implement a small parser that accepts only a JSON list of nonblank strings with no NUL bytes. Reject missing or malformed argv as an execution blocker for HTTP Collections. Hash the canonical argv JSON for sanitized evidence and keep the actual argv only in private local diagnostics when diagnostic inspection is required.

- [ ] **Step 2: Implement readiness polling**

Use `urllib.request.urlopen(Request(url, method="GET"), timeout=request_timeout)` with a monotonic deadline. Treat only `200 <= code <= 299` as ready. Record attempt count, success code, and timestamps. If the process exits while polling or the deadline expires, record `readiness_failed` and do not invoke Newman.

- [ ] **Step 3: Implement bounded process-group cleanup**

Launch with `start_new_session=True` and a private 0600 log file. In cleanup, send SIGTERM to the owned process group, wait up to a bounded grace period, send SIGKILL when still alive, then verify `poll()` and process-group absence. Record `term_sent`, `kill_sent`, `stopped`, exit code, and cleanup status. Cleanup errors must not overwrite the separate Newman result.

- [ ] **Step 4: Enforce liveness immediately before Newman**

After readiness returns and again immediately before invoking Newman, check the exact owned `Popen` object and its process group. If it exited, mark the run `blocked` with `owned_server_exited` even if the readiness URL currently returns 2xx. Do not run Newman in that case.

- [ ] **Step 5: Integrate the existing Newman execution under `try/finally`**

Keep the existing private environment, collection snapshot, JSON report, timeout, and summary logic. Set the run classification as follows:

```python
blocked = startup/readiness/environment/Newman-tool/cleanup failure
failed = Newman completed and API/assertion/report checks failed
passed = Newman completed successfully and cleanup succeeded
```

If Newman passes and cleanup fails, persist `newman.status = "passed"`, `cleanup.status = "failed"`, and overall `status = "blocked"`. If Newman was never invoked, set its outcome to `not_run` and never use `not_applicable`.

- [ ] **Step 6: Verify the runtime tests are GREEN**

Run:

```bash
python3 -m unittest plugins.devflow.tests.test_finalization
```

Expected: All finalization tests pass, including persisted blocker evidence and cleanup behavior.

### Task 4: Harden finalization and diagnosis gates

**Files:**
- Modify: `plugins/devflow/scripts/devflow_finalization.py:structural_errors,triage,final_errors`
- Modify: `plugins/devflow/core/schemas/state.schema.yaml:delivery_finalization`

**Interfaces:**
- Consumes: runtime `server_lifecycle`, `newman_outcome`, `cleanup_outcome`, and `no_http_evidence` records.
- Produces: deterministic refusal messages for stale, missing, or fabricated lifecycle evidence.

- [ ] **Step 1: Add validation assertions for the new evidence contract**

Test malformed lifecycle mappings, missing ordered events, early owned-server exit evidence, non-2xx readiness, cleanup failure after a pass, mismatched no-HTTP collection hash, nonempty declared endpoint proof, and legacy runs missing lifecycle fields.

- [ ] **Step 2: Enforce triage classification boundaries**

Require `run.status == "failed"`, `newman_outcome.status == "failed"`, and successful lifecycle evidence before accepting `code` or `collection`. Allow `environment` or `unknown` for blocked infrastructure runs only. Keep every unresolved or blocked run in the finalization error set until a later valid pass exists.

- [ ] **Step 3: Enforce HTTP and no-HTTP finalization rules**

For HTTP branches require the latest run to be `passed`, with current source and collection hashes, Newman version and raw report hash, ordered lifecycle events, 2xx readiness evidence, owned-server liveness, and successful cleanup. For no-HTTP branches require zero leaf requests, zero declared endpoints, and evidence values that match the current branch record and Collection hash. A blocked or failed HTTP run can never be reinterpreted as no-HTTP.

- [ ] **Step 4: Verify focused finalization tests**

Run:

```bash
python3 -m unittest plugins.devflow.tests.test_finalization
```

Expected: PASS with finalization refusal for all missing or invalid evidence cases.

### Task 5: Synchronize release metadata, documentation, and run regression coverage

**Files:**
- Modify: `.claude-plugin/marketplace.json:version fields`
- Modify: `plugins/devflow/.claude-plugin/plugin.json:version`
- Modify: `plugins/devflow/.codex-plugin/plugin.json:version`
- Modify: `README.md:current version`
- Modify: `plugins/devflow/README.md:version and finalization instructions`
- Modify: `plugins/devflow/CHANGELOG.md:top entry`
- Modify: `plugins/devflow/tests/test_devflow.py:version expectations`
- Modify: `plugins/devflow/tests/test_delivery.py:syntax and render expectations`

**Interfaces:**
- Consumes: the protocol and CLI behavior from Tasks 1 through 4.
- Produces: consistent release metadata and truthful instructions for agents.

- [ ] **Step 1: Update current documentation and manifests**

Set current plugin references to `0.8.1`, keep `.agents/plugins/marketplace.json` as a discovery pointer without version or description, and describe the JSON argv server command, required readiness URL, 2xx rule, liveness gate, cleanup fallback, failure classification, and strict no-HTTP rule. Add the protocol 1.8.0 compatibility rationale to the top CHANGELOG entry.

- [ ] **Step 2: Update and run version/manifest tests**

Run:

```bash
python3 -m unittest plugins.devflow.tests.test_delivery
python3 plugins/devflow/tests/test_devflow.py
```

Expected: PASS with all adapter metadata still resolving to `./plugins/devflow`.

- [ ] **Step 3: Run required syntax checks**

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/scripts/devflow_newman.py plugins/devflow/scripts/devflow_finalization.py plugins/devflow/scripts/devflow_delivery.py plugins/devflow/scripts/devflow_postman.py plugins/devflow/tests/test_devflow.py
```

- [ ] **Step 4: Run the delivery and finalization suites twice**

```bash
python3 plugins/devflow/tests/test_delivery.py
python3 plugins/devflow/tests/test_finalization.py
python3 plugins/devflow/tests/test_delivery.py
python3 plugins/devflow/tests/test_finalization.py
```

Expected: zero failures. Run `test_newman_integration.py` separately; report a skip if Newman is not installed and do not call that skip real Newman evidence.

- [ ] **Step 5: Review final hygiene and branch**

```bash
git diff --check
git status --short
git branch --show-current
python3 -m json.tool .agents/plugins/marketplace.json >/dev/null
python3 -m json.tool .claude-plugin/marketplace.json >/dev/null
python3 -m json.tool plugins/devflow/.codex-plugin/plugin.json >/dev/null
python3 -m json.tool plugins/devflow/.claude-plugin/plugin.json >/dev/null
```

Expected: no whitespace errors, no transient files, branch `main`, and valid JSON manifests.
