# AUDIT core

Auditors work in a fresh reasoning context whenever practical and verify the repository directly.

## Common axes

A. Requirement and PLAN traceability  
B. Source-of-truth compliance  
C. Repository and architecture conventions  
D. Code-level design and contract correctness  
E. Tests and executable evidence  
F. Overengineering, residue, and scope intrusion  
G. Failure and recovery behavior  
H. Concurrency and idempotency  
I. Security, authorization, and ownership  
J. Migration, configuration, and deployment

## Phase audit

Concentrate on the phase PLAN, its WORK items, the actual diff, tests, and acceptance criteria.

## Integration audit

Add:

- producer/consumer contracts across phases,
- transferred requirements,
- end-to-end state machines,
- end-to-end data flows,
- cross-module transaction boundaries,
- migration/deployment ordering,
- regression and evidence gaps.

## Finding classification

- `CONFIRMED`: defect is supported by current repository evidence; create remediation WORK.
- `DECISION_REQUIRED`: product or policy choice is unresolved; record decision and block dependent WORK.
- `EVIDENCE_REQUIRED`: more verification is needed; create evidence-oriented WORK, not product-code changes.
- `REJECTED`: suspected defect is disproved; retain the audit record only.
- `DOCUMENTATION_DRIFT`: code and approved behavior align but documentation is stale; create documentation WORK.
- `SPEC_DRIFT`: authoritative sources conflict; stop affected execution until resolved.

Every finding must state expected behavior, actual behavior, evidence, root cause or uncertainty, classification, severity, and disposition.
