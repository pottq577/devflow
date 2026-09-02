# Changelog

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
