---
schema: devflow-audit-v1
# Fill from the computed audit action and observed verification. Nulls intentionally fail validation.
scope: null
mode: null
verdict: null
baseline_sha: null
target_sha: null
diff_range: null
verification: []
findings: []
closure: []
---

# DevFlow Audit

The YAML front matter becomes the machine-readable audit outcome after review. Set scope and mode from the computed next action, pin the actual commit SHAs and diff range, record executed verification, and select a verdict from the findings. The `null` fields and empty verification list prevent this scaffold from passing `devflow audit apply`.

Keep the human-readable explanation below. Apply a completed audit with `devflow audit apply`.

## Metadata

| Field                   | Value                             |
| ----------------------- | --------------------------------- |
| Scope                   | plan / work / phase / integration |
| Mode                    | initial / closure                 |
| Phase                   |                                   |
| WORK ID                 | Required for work scope           |
| Baseline SHA            |                                   |
| Target SHA              |                                   |
| Diff range              |                                   |
| Commits / changed files |                                   |
| Date                    |                                   |

Branch names are not a range. Pin immutable SHAs, and confirm the base really is an ancestor of the head before trusting a 3-dot diff.

## Verdict

Use `core/protocol/audit-core.md` for the `pass`, `conditional_pass`, or `fail` verdict rubric and `core/protocol/risk-policy.md` for finding severity. Record observed command evidence before selecting `pass`.

## Summary

Three sentences at most. What matched the plan, and what did not.

## Findings

| #   | Severity | Classification | Axis | Location (`file:line`) | Summary | Origin ID |
| --- | -------- | -------------- | ---- | ---------------------- | ------- | --------- |

### [FINDING-ID] — [Title]

- Classification: [Select from `core/schemas/finding.schema.yaml`; no finding is pre-confirmed]
- Severity: [Select and justify under `core/protocol/risk-policy.md`]
- Axis:
- Expected:
- Actual:
- Evidence: file and line range, or command and result
- Root cause / uncertainty:
- Disposition:
- Generated work item:
- Severity reason:
  - Trigger conditions:
  - Affected users or systems:
  - Current defenses:
  - Residual impact:
  - Why the selected severity applies:

## Axis results

### A. Requirement and PLAN traceability

| Requirement / plan item | Implementation | Verdict |
| ----------------------- | -------------- | ------- |

### B. Source-of-truth compliance

### C. Repository and architecture conventions

### D. Code-level design and contract correctness

For each defect: what goes wrong, on which input and ordering, and where the fix belongs.

### E. Tests and executable evidence

| Required test | Corresponding test | Verdict |
| ------------- | ------------------ | ------- |

### F. Overengineering, residue, and scope intrusion

### G. Failure and recovery behavior

### H. Concurrency and idempotency

### I. Security, authorization, and ownership

### J. Migration, configuration, and deployment

## Integration-only axes

Fill this section only for `scope=integration`.

- Producer/consumer contracts across phases:
- Transferred requirements, checked in the receiving phase:
- End-to-end state machine:
- End-to-end data flow:
- Cross-module transaction boundaries:
- Migration and deployment ordering:
- Regression and evidence gaps:

## Verification performed

| Command | Result |
| ------- | ------ |

## Traceability / coverage gaps

## Residual risks

## Next state

- Phase / integration status to set:
- Generated WORK ids:
- Unresolved decision ids:
