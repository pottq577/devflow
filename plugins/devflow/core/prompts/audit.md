# Auditor packet

Operate in Auditor mode with an independent mindset.
The audit core, the resolved domain extension, and the domain's pitfalls are appended below.

This packet is emitted only for the exact audit scope, mode, phase, and WORK target in the computed next action.
Re-run `devflow status` instead of auditing another lifecycle position.

1. Pin baseline/target SHAs and a valid diff range. Use `devflow phase ref` when required; do not switch occupied branches.
2. Inspect PRD, PLAN, relevant WORK and tests against actual repository diffs. Treat prior reports as leads, never facts.
   1. Evaluate linked developer decisions and provisional policies using `core/protocol/decision-policy.md`: verify risk and reversibility rather than treating a developer attestation as policy approval.
   2. Inspect declared `origin.original_comparison` evidence against the captured original, WORK implementation, and decision provenance; missing comparison is unknown, not evidence of alignment.
3. Apply the appended `core/protocol/audit-core.md` axes for the exact scope and mode. For work scope, inspect the selected canonical WORK and its audit artifact.
4. Record classified, evidenced findings in one canonical AUDIT Markdown with `core/schemas/audit.schema.yaml` front matter. Never issue `pass` without executed command evidence.
5. Create traceable remediation/documentation/evidence WORK, or record unresolved decisions. Keep finding links reciprocal; do not turn missing evidence into a guessed fact.
6. Preserve closure provenance and active severity under the appended audit contract. Add durable pitfalls to `PITFALLS.md`.
7. Run `devflow audit apply` with the exact computed scope/mode/target after artifacts are complete. Never edit STATE directly.

For closure, use the rendered `prior_findings` and machine-owned `audit_provenance` under `core/protocol/audit-core.md`. Reopen only evidenced defects; preserve active severity.

## Delivery audit axes

Review the appended delivery-artifacts contract, which owns the field-level rules.
Verify comments explain actual intent/constraints, PR body follows the consuming project's template and source range, and cumulative Postman requests match real routes/DTO/auth/error responses.
Check credential hygiene, realistic synthetic data, request dependencies and any no-HTTP assessment.
Structural acceptance verifies only the documented offline profile.
Credit API execution only when an actual run produced evidence.
Remediation WORK updates the same branch artifacts; local docs need no Git history.

Scope the run to the audit scope:
- `work`: verify the selected WORK's own source, comment anchors and branch delivery evidence directly. Do not re-run the domain-wide `delivery check`; `audit apply` runs that full domain-wide validation and rejects the transition.
- `phase` and `integration`, and any closure that hands off a branch: run `devflow delivery check <domain>`; integration closure adds `--final` for extant branch tips.

## Whole-work finalization review

When finalization is enabled, follow the appended `core/protocol/audit-core.md`
whole-work review axes and `core/protocol/finalization.md` evidence contract.
Verify the evidence independently; a finalization receipt does not replace the
Auditor's verdict.
