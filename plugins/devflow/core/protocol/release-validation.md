# Regression and release verification

The regression suite is a test gate, not lifecycle authority and not evidence of a
production deployment. It never edits PRD, PLAN, WORK, audit evidence or domain STATE.

## Version policy and canonical source

Use `plugins/devflow/version.json` as the only editable current version source.
It contains independent `plugin` and `protocol` MAJOR.MINOR.PATCH values.
The script synchronizes three distribution manifests, the runtime protocol constant,
and the STATE scaffold without modifying CHANGELOG or initialized domain artifacts.
Release provenance includes marketplace adapters and the active root documentation;
unrelated local patch files are outside the release-source checks.

- PATCH: compatible bug fixes, documentation corrections and internal tooling.
- MINOR: backward-compatible user-facing features.
- MAJOR: incompatible plugin behavior or entrypoints.
- Protocol: bump independently only when an artifact or lifecycle compatibility change requires it; document migrations or backward readability.

From the marketplace root, inspect, bump and verify versions:

```bash
python3 plugins/devflow/scripts/release_version.py show
python3 plugins/devflow/scripts/release_version.py set --plugin "$NEXT_PLUGIN_VERSION"
python3 plugins/devflow/scripts/release_version.py check
```

Use `--protocol <version>` with `set` only after reviewing artifact compatibility.
Update CHANGELOG manually with the actual release decision; never overwrite history.
Commit canonical metadata and generated mirrors together. Tag/publish only after
an independently passing release gate; pending native hosted Goal/ELI5 acceptance
must remain explicitly disclosed.

## One fresh suite per decision

From the repository root, after applying the proposed change and before merging:

```bash
python3 plugins/devflow/tests/release_gate.py --mode merge \
  --report /tmp/devflow-merge-verdict.json
```

After committing the change, use the stricter release check in an environment with
Newman installed and permission to bind the disposable loopback test server:

```bash
python3 plugins/devflow/tests/release_gate.py --mode release \
  --report /tmp/devflow-release-verdict.json
```

Both commands launch `run_suite.py --profile full` themselves. Do not present a
previous, filtered, list-only or manually edited suite report as fresh release evidence.
Each command generates two atomic JSON files: the named verdict and a sibling
`*.suite.json` report. The verdict includes a SHA-256 of the suite report and the
SHA-256 of the plugin source/contracts snapshot. Keep reports outside the repo.
Exit 0 means the chosen gate passed; exit 1 means it is blocked; exit 2 means
the gate could not run or persist its evidence.

The optional `run_suite.py --profile focused|legacy|newman` modes support development
feedback only. A filtered `--profile full --match ...` is also partial.

During development, prefer the compact test runner rather than dumping per-test
tracebacks or the entire `*.suite.json` file into an agent context:

```bash
# Advisory impacted selection, including staged/untracked changes relative to HEAD:
python3 plugins/devflow/tests/run_suite.py --changed-from HEAD \
  --report /tmp/devflow-impact.json
# Use HEAD~1 after committing the patch to include that commit's changes.
python3 plugins/devflow/tests/run_suite.py --profile focused \
  --match CodexCrashResume --report /tmp/devflow-focused.json
python3 plugins/devflow/tests/run_suite.py --summary-from /tmp/devflow-focused.json
# Rerun only nonpassing exact IDs from the latest complete suite evidence:
python3 plugins/devflow/tests/run_suite.py \
  --rerun-from /tmp/devflow-merge-verdict.suite.json \
  --report /tmp/devflow-rerun.json
# Inspect bounded routing and test duration metrics without exposing full logs:
python3 plugins/devflow/scripts/devflow_efficiency.py --domain <domain> \
  --suite /tmp/devflow-focused.json
```

The default console prints a bounded exception line per failure (no success dots
or source-sized assertion diffs). Use `--verbose` only when a full traceback is
required. `--summary-from` does not run tests, and `--rerun-from` always marks
its report **partial**, even if every retried test passes. Neither command
replaces a fresh, unfiltered `release_gate.py` run.

`--changed-from <Git ref>` is also **advisory and partial**. It selects exact
unittest IDs from known source-to-test mappings (not substring guesses) and
includes committed differences from the ref, staged/unstaged edits and untracked
files. Unmapped plugin source changes conservatively expand to the complete
focused profile; missing test modules, invalid refs, and empty DevFlow changes
fail closed. The selected strategy and count are recorded in JSON under `impact`.
The mapping is a fast-feedback heuristic, not proof of complete coverage.
Never pass this partial report to the release gate as full suite evidence.

## Required checks

- Full, unfiltered discovery and test execution, with no duplicate, missing or
  unexpected test IDs. Every test's outcome must reconcile with the JSON summary.
- At least the original 171 lifecycle cases, all three real-Newman cases and the
  required regression test modules must remain discoverable. The legacy entry point
  `test_devflow.py` is executed through the unittest lifecycle adapter, not twice.
- Every non-Newman skipped test, test failure, error, expected failure or unexpected
  success is a blocker. A nonzero full suite exit code is always a blocker, even if
  its JSON summary appears successful.
- The Python plugin and test source must parse using the declared Python 3.10
  syntax contract, and the source snapshot must not change during the test run.
- Git HEAD must be available for provenance. Merge mode allows uncommitted plugin
  changes so that the candidate patch can be tested before committing.
- Merge mode can pass **with an explicit warning** when real-Newman smoke tests are
  skipped. This does **not** claim that real HTTP tests passed. Release mode requires
  all real-Newman smoke tests to run and pass, with no skipped tests, and a clean
  plugin working tree after the suite.

The gate does not infer billed tokens, certify a production endpoint or substitute
for required independent audits, application acceptance testing, or a human release
decision. Missing system dependencies and sandbox denial remain visible blockers
for the strict release gate rather than fabricated execution evidence.

## Documentation integrity and input-volume measurement

`test_docs_consistency.py` is a required full-suite module. Its read-only checker
validates current relative links, plugin versions, role front matter, owner references,
role-to-protocol pointers, and the invalid-until-completed AUDIT scaffold. Potential
long copied policy lines are advisory only; they do not replace review evidence.

`measure_role_packets.py` compares actual CLI `render` stdout UTF-8 bytes from the
frozen baseline and working-tree plugin at equivalent synthetic domains for plan,
run, audit, finalize, and Scout's bounded evidence-navigation output. It uses
`git archive`, not a branch switch or worktree, and writes no lifecycle artifacts in
the source repository. Save its JSON outside the repository; treat missing commands
or missing required contract markers as measurement failures. Packet bytes are not
model tokens, native hosted execution, installed ELI5, or real Newman acceptance.

## Regression areas protected

| Improvement | Regression coverage |
| --- | --- |
| Test collection and standalone compatibility | `test_test_infrastructure.py`, `test_suite_runner.py`, `test_lifecycle_cases.py` |
| Remediation scheduling and lifecycle corrections | Legacy `case_*` scenarios, `test_finalization.py` |
| Capability-aware routing | `test_autopilot.py` |
| Hosted domain ownership and bounded execution | `test_hosted_session.py`, `test_hosted_guard.py`, `test_host_autopilot.py` |
| Scout capsule and dispatch contracts | `test_scout_contract.py`, `test_host_autopilot.py` |
| Newman failure semantics | `test_newman_classification.py`, `test_finalization.py`, `test_newman_integration.py` |
| Suite and gate contracts | `test_suite_runner.py`, `test_release_gate.py` |
| Documentation and prompt input integrity | `test_docs_consistency.py`, `test_documentation_history.py`, `test_protocol_template_ownership.py` |

A partial profile is useful during development but cannot replace this complete
cross-module regression gate. Inspect the verdict's `blockers`, `warnings` and
`coverage`, plus the standalone suite JSON, before deciding whether to merge or
release.
