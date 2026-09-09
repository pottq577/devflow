# DevFlow Closure and Recovery Hardening Design

## Goal

Make an applied closure audit remain valid after it is persisted, make every advertised legacy
closure recovery command reach a fresh initial audit, and let a resolved decision authorize the
closure outcome that consumed it.

This change also removes two verified maintenance defects from the review report: the flaky
timeout diagnostic budget and the stale root README version statement.

## Current defects

1. `audit apply --mode closure` validates against the prior finding set and then overwrites that
   set with the current audit findings. A later `validate` therefore treats current-only findings
   as prior findings and rejects the audit that was just accepted.
2. The recovery message for a legacy work closure recommends `work review ... pending`, but the
   command rejects a `remediation` review. Plan recovery accepts `pending` while preserving
   `remediation_work_ids`, so lifecycle derivation immediately returns to closure.
3. Finding linkage always requires an Open decision record, while `accepted_risk` closure requires
   the same decision to be Resolved.

## Provenance contract

Keep `audit_provenance.findings` as the finding-to-severity mapping used by the next closure audit.
Add the optional `audit_provenance.applied_against` mapping for the prior finding set used to accept
the currently persisted closure audit.

Initial audit application writes only `findings`. Closure audit application writes:

```yaml
audit_provenance:
  findings:
    F-02: major
  applied_against:
    F-01: major
```

The responsibilities stay separate:

- `audit apply` and closure rendering read `findings` because they operate on the next transition.
- `validate` reads `applied_against` when checking a persisted closure audit, falling back to
  `findings` for legacy artifacts.
- Structural validation checks both mappings with the same finding ID and severity rules.

No audit digest, history file, Git lookup, or extra lifecycle artifact is added.

## Recovery transitions

`work review <domain> <ID> pending` remains valid for a stop-blocked review. It additionally accepts
a `remediation` review only when that review has no `audit_provenance`, which identifies the legacy
mid-closure recovery case. It clears `remediation_work_ids` and returns the review to `pending`.
A normal remediation review with recorded provenance remains protected from this reset.

`plan-review set <domain> pending` clears `remediation_work_ids`. Its next action is therefore a plan
initial audit instead of the old closure. Phase and integration recovery already reach their
initial audits and remain unchanged.

Every transition continues through the existing atomic lifecycle mutation path.

## Decision closure rules

An initial finding and a `still_open` closure finding require valid Open decision records. A prior
finding closed as `resolved`, `reopened`, or `accepted_risk` requires valid Resolved decision records
that are absent from `STATE.unresolved_decisions`. A current-only decision finding still requires
an Open record.

The existing dedicated `accepted_risk` check remains as the outcome-specific guard and error
message. This keeps malformed or prematurely resolved decisions blocked.

## Compatibility and versions

The optional provenance field changes the artifact contract. Release it as plugin `0.6.1` with
protocol `1.5.0`. The protocol minor bump prevents an older 1.4 runtime from claiming full support
for artifacts that carry the new validation basis. Existing provenance records containing only
`findings` remain readable through the fallback behavior.

Update the runtime constant, STATE template, plugin and marketplace manifests, current README
files, tests, schema descriptions, normative protocol, and CHANGELOG. The Codex marketplace adapter
remains a discovery pointer without version metadata.

## Verification

Add regression coverage before implementation for these user-visible flows:

1. A closure containing a resolved prior finding and a new finding applies, survives a disk reload,
   passes `validate`, and supplies the new finding set to the next closure.
2. Legacy work and plan closures follow the exact command printed by the refusal, render and apply
   an initial audit, apply a closure, and pass `validate`.
3. A decision moves from Open to Resolved, an `accepted_risk` closure applies, and the domain reaches
   a valid completed state.

Increase the timeout diagnostic case from `0.5` to `2.0` seconds while its child still sleeps for
five seconds. Run Python compilation, the full framework suite twice, all four JSON manifest checks,
adapter target checks, executable mode validation, `git diff --check`, and `git archive` content
inspection. Real Claude Code and Codex installation remains outside this task.

## Commit boundaries

1. Preserve closure validation provenance.
2. Make legacy closure recovery commands executable.
3. Accept resolved decisions at closure.
4. Synchronize version, documentation, timeout, and release metadata.
