---
schema: devflow-audit-v1
scope: integration
mode: initial
verdict: pass
baseline_sha: replace-with-full-sha
target_sha: replace-with-full-sha
diff_range: current-head
verification:
  - command: replace-with-executed-command
    result: replace-with-observed-result
findings: []
closure: []
---

# DevFlow Audit

The YAML front matter is the machine-readable audit outcome.
Keep the explanation below for human review, but make the front matter authoritative and run `devflow audit apply` after writing it.

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

`pass` | `conditional_pass` | `fail`

- `pass`: no blocker and no major finding.
- `conditional_pass`: only major findings, each with a specific fix named.
- `fail`: at least one blocker.

Never write `pass` without evidence.
Only a command that was actually executed, with its output, counts as grounds for a pass.

## Summary

Three sentences at most. What matched the plan, and what did not.

## Findings

| #   | Severity | Classification | Axis | Location (`file:line`) | Summary | Origin ID |
| --- | -------- | -------------- | ---- | ---------------------- | ------- | --------- |

### [FINDING-ID] — [Title]

- Classification: `CONFIRMED`
- Severity: `major`
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
  - Finding severity is separate from WORK risk level.

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
