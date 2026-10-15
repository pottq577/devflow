# Role instruction ownership

Each DevFlow rule has exactly one authoritative home. Skills, render prompts and role contracts
carry the rules that belong to their role plus a pointer to the owning protocol; they never restate
a protocol's obligations. A rule with no named owner here is unowned and must get one before it is
relied on.

## Ownership matrix

| Rule class | Authoritative source | Consumers |
| ---------- | --------------------- | --------- |
| Lifecycle authority, STATE ownership, statuses, artifact budget | `core/protocol/authority.md` | all roles |
| Transitions, `next_action`, phase and integration handoff, render/status CLI | `core/protocol/lifecycle.md` | all roles |
| Open human decision recording and resolution | `core/protocol/decision-policy.md` | plan, run |
| WORK schema, versions, evidence and acceptance/verification mapping | `core/protocol/work-item-contract.md`, `core/schemas/work.schema.yaml` | plan, run, audit |
| High/critical review, audit scope and remediation rules | `core/protocol/risk-policy.md`, `core/protocol/audit-core.md`, `core/schemas/audit.schema.yaml`, `core/schemas/finding.schema.yaml` | run, audit |
| Branch, commit, comment anchor, PR body and Postman collection contract | `core/protocol/delivery-artifacts.md`, `core/schemas/delivery.schema.yaml` | plan, run, audit |
| Newman ownership, readiness, evidence, diagnosis, ELI5, final receipt | `core/protocol/finalization.md`, `core/schemas/finalization.schema.yaml` | plan, run, audit, finalize |
| Peer skill composition and precedence | `core/protocol/skill-composition.md` | plan, run, audit |
| Hosted session, lease, step reservation, telemetry and recovery | `core/protocol/host-telemetry.md`, `core/schemas/host-telemetry.schema.yaml`, `core/schemas/state.schema.yaml` | goal |
| Routing aliases, capabilities and escalation | `core/schemas/routing.schema.yaml`, `core/schemas/model-registry.schema.yaml` | goal, autopilot |
| Regression and release evidence for each contract | `core/protocol/release-validation.md` | release operator |
| Wrapper invocation and repository-root rules | `skills/*/SKILL.md` runtime section | manual operators |
| Role steps, boundaries and required receipts | the role's own skill or `core/prompts/*.md` contract | that role only |
| State, action, scope and evidence facts | runtime render and status output | all roles |

## What a role contract may add

A role contract states only what is specific to the role: its steps, its boundaries, what it must
return, and which protocol it must read. It must not restate another protocol's obligations, and
it must not assert a lifecycle result. When two documents disagree, the protocol owns the rule and
the other document is the defect.

## Removing duplication

A sentence that exists in both a skill and a render prompt, or in both a skill and a protocol, is
removed from the weaker location and replaced with a pointer. `core/prompts/plan.md` and
`skills/plan/SKILL.md` therefore reference `core/protocol/finalization.md` for the ELI5/Newman
stage instead of repeating it, and the audit finalization review names its protocol once.

Deletion must never remove an obligation. Before removing text, confirm the owning protocol still
states the rule and that the consuming role still receives a pointer to it.