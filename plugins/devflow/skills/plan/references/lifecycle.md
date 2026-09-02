# DevFlow lifecycle

DevFlow exposes four operations:

- `plan`: Architect mode. Convert an approved PRD into a repository-grounded PLAN, phase manifests, decisions, and STATE.
- `run`: Executor mode. Execute exactly one ready WORK item and record evidence.
- `audit`: Auditor mode. Independently verify plan, phase, or integration scope. Confirmed findings create remediation WORK.
- `status`: Deterministic state inspection. Compute the next action from STATE and WORK.

## Lifecycle

```text
PRD
 -> plan
 -> optional plan audit for high-risk work
 -> run phase work
 -> audit phase
 -> run remediation
 -> audit phase --mode closure
 -> next phase
 -> audit integration
 -> run integration remediation
 -> audit integration --mode closure
 -> VERIFIED
```

Return to the human/Chat layer only for product-policy decisions, scope changes, conflicting requirements, or deliberately requested third-party review.

## Artifact budget

Project artifacts are limited to:

- `PRD.md`
- `PLAN.md`
- `STATE.yaml`
- `DECISIONS.md` when decisions exist
- `work/*.yaml`
- `audits/*.md`

Do not create separate task Markdown files, handoff documents, remediation plans, focused-review documents, integration-test plans, or prompt handoff documents. STATE and the CLI reconstruct the next action.
