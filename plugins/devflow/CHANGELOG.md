# Changelog

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
