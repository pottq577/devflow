# Newman Server Lifecycle Enforcement Design

**Status:** Approved for implementation

## Goal

Make `devflow delivery newman` own the complete local verification lifecycle for every branch with an HTTP surface:

```text
server start -> readiness check -> Newman run -> result classification -> server stop
```

`delivery finalize` must accept only fresh, successful Newman evidence with a successful server lifecycle. A server, readiness, Newman tool, or environment failure remains an explicit blocker or failed run and cannot become `not_applicable`.

## Decisions

### Process ownership

`delivery newman` starts the server itself with an argv-based command contract. The CLI accepts `--server-command` as a JSON array of argv strings, for example:

```bash
--server-command '["python3", "-m", "http.server", "8080"]'
```

The runtime does not invoke a shell or use `shlex.split`. It starts the process in a dedicated process group, captures private server output, polls the readiness URL, runs Newman only after readiness succeeds, and terminates the process group in `finally`.

`--readiness-url` is required for HTTP collections. Readiness succeeds only for an HTTP response status in `200..299`; the default timeout is bounded and polling is condition-based. The readiness URL uses the same target safety rules as the Newman base URL.

### Evidence and statuses

Each attempted HTTP run records a server lifecycle evidence object containing the argv hash, readiness URL, ordered event timestamps, readiness HTTP status, server log path and hash, Newman result, and cleanup result. A successful Newman run whose cleanup fails is recorded with separate Newman and cleanup outcomes but the overall run is `blocked`, so finalization rejects it.

Startup, readiness, Newman tool, environment, and cleanup failures are persisted as `blocked` or `failed` runs. They never produce `not_applicable`.

`not_applicable` is valid only when both conditions hold:

1. The Collection contains zero leaf HTTP requests.
2. The branch declares zero API endpoints.

The run records the zero request count, empty declared endpoint list, Collection hash, source hash, and the branch API assessment. Finalization rechecks these values against the current Collection and branch record.

### Diagnosis and finalization gate

`code` and `collection` triage is accepted only for a completed Newman run with a successful server lifecycle. Server or environment failures are triaged as `environment` or `unknown` and keep finalization open until a later valid run succeeds.

`final_errors` requires, for every HTTP branch:

- a current run with `status: passed`;
- a real Newman version, report hash, response and assertion counts;
- ordered server start, readiness, Newman completion, and stop evidence;
- successful cleanup;
- source and Collection hashes matching the delivered branch.

Missing lifecycle fields in older readable runs are treated as insufficient finalization evidence, not as a pass.

## Version compatibility

The repository HEAD already contains the released plugin `0.8.0` entry dated 2026-09-10. This change therefore bumps the plugin manifests and current documentation to `0.8.1` and keeps the protocol version domains separate.

The run evidence contract and finalization gate change materially, so the protocol version becomes `1.8.0`. Existing `1.7.0` artifacts remain readable. Existing finalization runs without server lifecycle evidence cannot finalize; they must be rerun through the owned lifecycle. No bulk migration or fabricated evidence is introduced.

## Files in scope

- `plugins/devflow/scripts/devflow_newman.py`: argv parsing, server start, readiness polling, Newman execution, cleanup, and run evidence.
- `plugins/devflow/scripts/devflow_finalization.py`: lifecycle and no-HTTP evidence validation, diagnosis restrictions, and finalization gate.
- `plugins/devflow/scripts/devflow.py`: CLI options and protocol version.
- `plugins/devflow/core/protocol/finalization.md`, `core/protocol/delivery-artifacts.md`, `core/prompts/finalize.md`, and `skills/run/SKILL.md`: executor contract.
- `plugins/devflow/core/schemas/state.schema.yaml` and `core/templates/STATE.yaml`: protocol and new-state contract.
- `plugins/devflow/tests/test_finalization.py`, `tests/test_newman_integration.py`, and related version/manifest assertions: regression coverage.
- Current README, CHANGELOG, and plugin manifests: user-facing contract and release metadata.

## Verification

Add regression coverage for successful lifecycle ordering, missing server command, startup failure, readiness failure, environment failure, Newman failure, cleanup failure after Newman success, strict 200..299 readiness, no-HTTP evidence, and finalization refusal for missing or invalid lifecycle evidence. Run the required syntax, framework, delivery, finalization, and optional real-Newman checks according to `AGENTS.md`.
