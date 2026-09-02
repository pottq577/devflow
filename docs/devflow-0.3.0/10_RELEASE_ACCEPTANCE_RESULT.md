# DevFlow 0.3.0 Release Acceptance Result

Independent gate run after work orders 01 to 07 were merged. This record changes no
product behavior. Version stays `0.3.0` because this work happens before any 0.3.0
release, tag, or install distribution.

## Decision

Release decision moves from **FAIL** to **PASS**, with the two real-CLI install line
items recorded as **UNVERIFIED** (see Task 4).

## Task 1: static syntax and manifest checks

| Check | Result |
| --- | --- |
| `python3 -m py_compile` on `devflow.py` and `test_devflow.py` | PASS |
| `.agents/plugins/marketplace.json` parses | PASS |
| `.claude-plugin/marketplace.json` parses | PASS |
| `plugins/devflow/.codex-plugin/plugin.json` parses | PASS |
| `plugins/devflow/.claude-plugin/plugin.json` parses | PASS |
| Both marketplaces resolve the same `./plugins/devflow`, no copied adapter runtime | PASS |

## Task 2: runtime suite twice

`python3 plugins/devflow/tests/test_devflow.py` run twice from a clean tree:
`passed=166 failed=0` both passes, proving throwaway-repo cleanup and state isolation.

## Task 3: original defect reproductions

| Defect | Covering regression | Result |
| --- | --- | --- |
| Integration WORK selected before phases verified | `case_integration_next_action_guards` | CLOSED |
| Remediation bypass via premature `verified` | `case_remediation_review_invariants` | CLOSED |
| Remediation dependency deadlock (direct and transitive) | `case_remediation_review_invariants` | CLOSED |
| Blank / whitespace verification evidence accepted | `case_evidence_required` | CLOSED |

## Task 4: plugin adapters with real tooling

Not run. The `claude` and `codex` CLIs are installed in this environment, but running
`plugin marketplace add` / `plugin install` would install and use the DevFlow plugin,
which is explicitly out of scope for this pass. Static manifest validation and the
`case_codex_adapter_uses_shared_plugin` / `case_marketplace_plugin_version_matches_manifest`
regressions pass. The two real-install line items remain **UNVERIFIED** and must be run
in a throwaway CLI profile before distribution.

## Task 5: clean release archive

`git archive --format=zip HEAD` produces an archive with:

- no `__pycache__/`, `*.pyc`, or `.git/` entries
- all required adapter, wrapper, runtime, and `skills/{plan,run,audit,status}/SKILL.md` files present

The archive is not committed; the repository does not track release binaries.

## Task 6: mandatory checklist

| Mandatory check | Result |
| --- | --- |
| All framework tests pass twice | PASS (`166/166` x2) |
| All four defect reproductions closed | PASS |
| Codex manifest static contract passes | PASS |
| Shared SSOT structure preserved | PASS |
| Release ZIP hygiene passes | PASS |
| No stale current-documentation paths / version examples | PASS |
| Real `claude` / `codex` install | UNVERIFIED |
