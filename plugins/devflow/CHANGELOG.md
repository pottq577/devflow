# Changelog

## Unreleased

### Changed

- **Closure provenance is machine-owned, not read from Git.** `devflow audit apply` now records the
  applied finding set as an `audit_provenance` mapping of finding ID to severity on the audited
  scope's own machine-owned metadata (`STATE.plan_review`, `STATE.phases.<key>`,
  `STATE.integration`, or the WORK item's `review`), for both initial and closure modes. A later
  closure recovers the prior finding set from that record. The former Git-history reader for the
  canonical audit file, and its `git log` / `git show` reads, are removed. No DevFlow lifecycle
  operation reads Git history for any file under `domains_root`, so the full delivery and
  audit-remediation lifecycle completes with `docs/` fully gitignored and the canonical audit never
  committed. Source-code Git use (baseline/target SHAs, phase diff ranges, `devflow phase ref`
  ancestry checks, `git show <ref>:<path>` for reading source) is unchanged.
- A closure requested at a scope with no recorded `audit_provenance` is refused deterministically
  and names that scope's recovery command (`devflow plan-review set <domain> pending`,
  `devflow work review <domain> <WORK-ID> pending`, `devflow phase set <domain> <phase> audit`, or
  `devflow integration set <domain> audit`). Provenance is never inferred and never reconstructed
  from Git.
- `render audit --mode closure` prints a `prior_findings` line with the recorded prior finding IDs.
- A closure audit can no longer lower the severity the verdict rubric evaluates. A finding recorded
  as `still_open`, and every ID a `reopened` entry names in `reopened_as`, must carry a severity at
  least as high as the severity recorded for that prior finding. Raising a severity with new
  evidence is still allowed; `resolved` and `accepted_risk` findings leave the active set and are
  exempt. The severity order is read from `finding.schema.yaml`, not hardcoded.
- **The project config protocol version is a floor.** When `.devflow/config.yaml` exists, the 1.3
  audit-apply gate decides from the higher of the STATE and config `protocol_version`. Hand-editing
  `STATE.protocol_version` below the config no longer re-enables `plan-review set`, `work review`,
  `phase set`, or `integration set` `verified`, and `validate` reports a STATE protocol older than
  the config as an error. A project with no config file, or one whose config genuinely records the
  older version, keeps the legacy verified transitions unchanged; a newer-than-runtime config keeps
  its existing read-only-plus-mutation-block behavior.

### Fixed

- **Every lifecycle mutation is atomic.** `work start|done|block|review`, `phase set|ref`,
  `plan-review set`, `integration set` and `decision add|resolve` now project their prospective
  STATE (and any changed WORK) on copies and commit the changed documents through one
  `commit_yaml_transaction()`, mirroring `audit apply`. Previously each wrote its primary artifact
  and only then refreshed derived STATE, so a projection failure on structurally invalid input left
  the artifact mutated while the command reported failure. A command that exits non-zero now leaves
  WORK and STATE byte-identical. This remains process-local failure rollback, not crash recovery or
  concurrent-writer isolation.
- **A stop-blocked WORK review can be re-audited.** `devflow work review <domain> <ID> pending`
  returns a `blocked` work review to `pending`, clears its `remediation_work_ids`, and projects a
  fresh work initial audit. It is refused from any other review status and never sets a review
  verified, so a `SPEC_DRIFT` or other `stop` finding no longer strands its phase. This mirrors the
  existing `plan-review set pending`, `phase set <n> audit` and `integration set <d> audit`
  recoveries, which previously had no work-scope equivalent.

### Compatibility and migration

- STATE and WORK without `audit_provenance` stay readable. The field is required only at the moment
  a closure audit is applied or validated.
- A protocol 1.3.0 domain that is mid-closure when this runtime arrives is refused at closure with a
  named recovery command. Re-running the scope's initial audit records provenance and the closure
  then proceeds. This is the one deliberate migration cost, and it is deterministic rather than
  inferred. No bulk migration command is required.

## 0.5.0

### Added

- **Brownfield audit/remediation workflow.** `init --workflow audit-remediation` creates a
  phase-free `audit_remediation` lifecycle that can move from integration initial audit through
  decisions or `work/integration.yaml` remediation, required WORK review, integration closure, and
  project completion without a fake phase.
- **Machine-readable audit outcomes.** The single canonical audit Markdown now carries
  `devflow-audit-v1` YAML front matter for scope, mode, verdict, immutable SHAs, executed
  verification, findings, and closure outcomes. `devflow audit apply` validates the complete
  outcome and commits accepted STATE and WORK changes atomically.
- **WORK v2 acceptance coverage.** New WORK gives acceptance criteria and verification commands
  unique IDs and requires each command to declare `covers`, with every acceptance ID covered by at
  least one executable verification command.
- **Finding, decision, and WORK traceability.** Audit dispositions and WORK origins must link in
  both directions. Decision findings block ready code WORK, and multi-finding WORK requires an
  explicit aggregation rationale for its shared change and verification boundary.
- **End-to-end regression coverage.** Tests exercise no-finding, remediation, decision, reopened
  finding, and delivery lifecycles through real CLI subprocesses.

### Changed

- `render` is lifecycle-aware and rejects a plan, run, or audit request that differs from the exact
  next action before printing a packet or creating an artifact.
- Cross-artifact validation rejects placeholder contracts, orphan or mismatched phase manifests,
  unsupported runtime config versions, invalid audit lifecycle evidence, and findings without an
  evidence-backed `severity_reason`.
- `.devflow/config.yaml` is the project runtime configuration and protocol compatibility guard.
  Domain PRD, PLAN, STATE, PITFALLS, DECISIONS, WORK, and AUDIT artifacts remain under
  `docs/domains/<domain>/` by default. `init` and `status` report both paths explicitly.

### Compatibility and migration

- Plugin version is `0.5.0`. Protocol version is `1.3.0`. These are separate version domains: the
  plugin identifies the distribution, while the protocol identifies the artifact contract.
- The protocol minor bump records contract additions that a 1.2 runtime cannot safely mutate:
  explicit workflow type, audit metadata and apply transitions, WORK v2 coverage, and new lifecycle
  states and traceability rules.
- Protocol 1.0 through 1.2 STATE and WORK artifacts remain backward-readable. Missing
  `workflow_type` reads as `delivery`, WORK v1 keeps its legacy string shape, and existing review
  defaults are supplied in memory without rewriting artifacts.
- Legacy audit Markdown without front matter remains readable as historical evidence, but cannot
  authorize a protocol 1.3 verified transition. No bulk migration command is required. A fresh
  project initialization records protocol `1.3.0` in runtime config and STATE, while existing
  artifacts migrate only when a user intentionally adopts the new workflow or audit transition
  contract.

## 0.4.0

### Added

- **Normative peer-skill composition policy.** `core/protocol/skill-composition.md` defines where
  DevFlow authority ends and optional peer skill behavior begins, and `lifecycle.md` cross-references
  it without duplicating the policy.
- **Superpowers execution-discipline composition.** The `run` skill composes test-driven-development
  for behavior-changing WORK, systematic-debugging for defect and remediation WORK, and
  verification-before-completion before a WORK is reported done, all inside the one selected ready
  WORK. Explicit repository or user instructions already authorize a TDD exception, so the run does
  not stop to re-ask.
- **Ponytail reuse/YAGNI composition.** The `plan` and `run` skills apply the currently active
  Ponytail policy as a minimalism lens inside DevFlow-owned boundaries.
- **Ponytail-backed complexity discovery as an advisory audit lens.** The `audit` skill treats
  Ponytail observations as leads mapped to the existing overengineering axis; only an independently
  verified lead becomes a DevFlow AUDIT finding.
- **Regression coverage** protecting DevFlow lifecycle ownership, the optional and non-coupling
  nature of peer composition, and the absence of peer-plugin state fields in templates and schemas.

### Changed

- DevFlow skills now explicitly distinguish lifecycle ownership from optional peer execution and
  minimization policies.
- Documentation describes safe composition with separately installed Superpowers and Ponytail,
  including the warning against running a Superpowers controller workflow nested inside an active
  DevFlow lifecycle.

### Compatibility

- Plugin version: 0.4.0.
- Protocol version: 1.2.0, unchanged. Peer composition is documentation and skill guidance only and
  creates no new artifact contract.
- No STATE, WORK, or AUDIT schema migration is required, and existing 0.3.1 project artifacts remain
  readable.
- Superpowers and Ponytail remain optional external plugins. No DevFlow command fails when a peer
  plugin is absent.

## 0.3.1

### Fixed

- **`validate` now gates verification instead of only reporting.** A domain whose WORK manifests
  failed validation could be driven all the way to `project_status: complete`. No transition
  consulted the validator, so items missing `objective`, `scope`, `requirements`, and
  `stop_conditions` rode through phase verification and integration verification untouched. `phase
  set <phase> verified` and `integration set verified` now refuse while the domain has validation
  errors, and report them prefixed with `validation:`.
- **`protocol_version` is read, not just written.** The runtime recorded the version in STATE and in
  `.devflow/config.yaml` and never compared it to its own. A STATE claiming `2.0.0`, or a malformed
  value, validated cleanly. `protocol_version` must use the numeric x.y.z form. Malformed short,
  extended, prefixed, or non-numeric forms are rejected. `validate` now errors on a different major
  version, errors on an unparseable one, and warns when the minor version is newer than the runtime's.
- **The schema's required phase entry fields are enforced.** `state.schema.yaml` declared
  `phase_entry.required: [status, work_file, audit_file]`, but the validator only checked `status`,
  so a phase entry missing both file paths passed without so much as a warning.
- **`phase set` and `phase ref` no longer invent a phase.** A mistyped number created a new STATE
  entry that could never be verified, which blocked integration permanently because integration
  requires every phase verified. Both commands now accept a phase that is already in STATE or has its
  WORK file on disk, and refuse otherwise.
- **An initial work audit reports its own lifecycle position.** `project_status` projected a
  work-scope audit as `phase_audit`, contradicting the `next.scope: work` printed beside it. The
  derived value is now `work_audit`.
- **Work review selection orders by phase before id.** `work_review_action` sorted by WORK id first
  while `choose_next` sorted by phase first, so a later phase's review could be handed out ahead of
  an earlier phase's. Both halves of the runtime now use the same ordering.
- **An unknown WORK id prints a clean message.** `str(KeyError)` is the repr of its argument, so the
  CLI reported `DevFlow error: 'Unknown WORK item: X'` with the quotes included.
- **`bin/devflow` resolves symlinks.** Linking it into a `PATH` directory made `dirname "$0"` resolve
  to the link's directory, and the wrapper looked for the runtime under the wrong root.

### Changed

- Generated `.devflow/config.yaml` no longer duplicates `protocol_version`. `STATE.yaml` is the
  protocol-version source of truth for each domain. Existing configs carrying the old field remain
  readable and the stale field is ignored.
- Protocol version is `1.2.0`. `project_status` gained the derived value `work_audit`, and a `1.1.0`
  runtime validates that field against its own allowed set, so it would reject a STATE this runtime
  writes. Existing `1.0.0` and `1.1.0` domains keep validating here, and no migration is required.
- Removed four parameters that every caller passed and no body read: `root` and `domain` from
  `work_start_errors`, `index` from `phase_verify_errors` and `integration_verify_errors`, and
  `state` from `project_status_for_action`.

## 0.3.0

### Added

- Schema-backed validation constants, atomic YAML writes, computed lifecycle state, and subprocess
  timeouts for diagnostics.
- `work` audit scope with initial and closure modes, plus the high/critical WORK review gate before
  dependents proceed.
- Runtime transition guards for WORK, plan review, phase, and integration state changes.
- Scope-aware context assembly: full PRD for planning, origin-linked context for WORK and work/phase
  audits, and bounded integration summaries and paths.

### Changed

- Plan review now uses its own artifact and defaults legacy missing `audit_file` to `audits/plan.md`.
- Existing WORK without review remains readable. Legacy high/critical done WORK is treated as
  requiring review before dependents, with no mandatory migration command.
- Plugin version is 0.3.0. Protocol version remains `1.1.0`: review metadata and plan audit-file
  defaults are backward-readable runtime normalization, so this release does not create an
  incompatible artifact contract. The stronger dependency gate is a runtime behavior change, not a
  protocol-version reset.
- Autonomous orchestration is explicitly out of scope. The runtime computes and renders the next
  action; agents or humans perform it.

## 0.2.0

### Fixed

- **Phase key normalization.** `choose_next` normalized its lookup key but not the STATE keys it
  looked up in, so a phase written as `"5"` never matched `"05"` and the runtime kept handing out
  work items from a phase already marked `verified`. The SSOT's own example used the unpadded form,
  so following the reference documentation produced the broken state. All readers now normalize both
  sides.
- **Duplicate phase entries.** `phase set` created a second entry when STATE already held the same
  phase under a differently formatted key, and `validate` reported no error. `phase set` now updates
  the existing entry, and `validate` rejects two raw keys that normalize to one phase.
- **`status` no longer rewrites STATE on every read.** It writes only when the computed state
  actually changed, so an inspection command stops producing diff noise.

### Added

- **`PITFALLS.md`, a seventh project artifact.** The half of a handoff that no state machine can
  compute: fakes that always succeed, methods that no-op instead of raising, a verification command
  that skips the suite it appears to run, the next free migration number, behavior that looks like a
  defect but is a recorded decision. `plan`, `run`, and `audit` all load it.
- **WORK item contract depth.** New `context`, `premise_checks`, `pitfalls`, `blocks`, `transfer`,
  and `references` fields, so an item carries what the Architect learned instead of forcing the
  Executor to re-derive it. `validate` requires `premise_checks` on `high` and `critical` risk.
- **`devflow phase ref`.** Pins `base_sha`, `head_sha`, and `diff_range` into STATE after verifying
  with `git merge-base --is-ancestor` that a 3-dot range is trustworthy. It refuses rather than
  guessing when the history diverged, and takes `--range` for that case. `authority.md` documented
  `diff_range` as mandatory but nothing computed it.
- **Transfer enforcement.** `validate` now requires a `transferred` item to name `transfer.to` and
  requires the receiving item to carry the same `origin.requirements`. The rule existed in the
  protocol; the check that makes it real did not.
- **Evidence enforcement.** `devflow work done` refuses a completion with no recorded command, and
  `validate` errors on a `done` item with an empty `evidence.commands`, except for
  `kind: documentation`.
- **Lifecycle consistency checks.** `validate` rejects a phase marked `verified` while its own work
  is unfinished, and an integration marked `verified` while a phase is not.
- **Audit extension resolution.** `.devflow/extensions/<name>.md`, then the bundled
  `core/extensions/<name>.md`, then `default.md`, selected per domain through `STATE.extension` or
  per project through `.devflow/config.yaml`. Previously every audit silently got `default.md`.
- **`status` reports more.** Blocked work items, the phase diff range, and `next.input` lines naming
  the documents and requirement ids the next action needs.

### Changed

- **`render` now assembles a complete prompt.** It inlines the relevant protocol documents, the
  resolved extension, and `PITFALLS.md` instead of printing a list of file paths.
- **`audit-core.md` restored to working depth.** Ten one-line axis labels became concrete per-axis
  checks, plus severity definitions, a pass / conditional_pass / fail rubric, the "never write pass
  without evidence" rule, the merge-base verification procedure, and the do-not-check-out-branches
  rule.
- **`AUDIT.md` template** gained a verdict rubric, a findings table, per-axis sections, an
  integration-only section, and an executed-verification table.
- **Skill reference duplication removed.** Eight byte-identical copies of `core/protocol/*.md` under
  `skills/*/references/` are gone; `render` inlines the originals, so they cannot drift.
- **Skill runtime invocation documented explicitly** instead of assuming a working directory.
- `finding.schema.yaml` carries severity meanings, verdicts, and per-classification dispositions.
- Agent interface descriptions no longer truncate mid-word.
- Protocol version is `1.1.0`. Existing `1.0.0` domains keep validating.
- Removed an unused `os` import from the runtime.

## 0.1.0

- Initial DevFlow protocol extracted from vibecoder.md.
- Added plan, run, audit, status lifecycle.
- Added STATE/WORK validation and prompt rendering runtime.
