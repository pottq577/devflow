# Role instruction ownership

Each DevFlow rule has exactly one authoritative home. Skills, render prompts and role contracts
carry the rules that belong to their role plus a pointer to the owning protocol; they never restate
a protocol's obligations. A rule with no named owner here is unowned and must get one before it is
relied on.

## Ownership matrix

| Rule class | Authoritative source | Consumers |
| ---------- | --------------------- | --------- |
| Product/domain source precedence and conflict handling | `core/protocol/authority.md` | all roles |
| Lifecycle statuses, transitions, `next_action`, artifact budget, phase and integration handoff, render/status CLI | `core/protocol/lifecycle.md` | all roles |
| Open human decision recording and resolution | `core/protocol/decision-policy.md` | plan, run |
| WORK schema, versions, evidence and acceptance/verification mapping | `core/protocol/work-item-contract.md`, `core/schemas/work.schema.yaml` | plan, run, audit |
| Machine-owned STATE fields and delivery/finalization records | `core/protocol/lifecycle.md`, `core/schemas/state.schema.yaml` | all roles |
| High/critical review, audit scope and remediation rules | `core/protocol/risk-policy.md`, `core/protocol/audit-core.md`, `core/schemas/audit.schema.yaml`, `core/schemas/finding.schema.yaml` | run, audit |
| Branch, commit, comment anchor, PR body and Postman collection contract | `core/protocol/delivery-artifacts.md` | plan, run, audit |
| Newman ownership, readiness, evidence, diagnosis, ELI5, final receipt | `core/protocol/finalization.md` | plan, run, audit, finalize |
| Peer skill composition and precedence | `core/protocol/skill-composition.md` | plan, run, audit |
| Hosted session, lease, Scout capsule provenance, step reservation, telemetry and recovery | `core/protocol/host-telemetry.md`, `core/schemas/host-telemetry.schema.yaml`, `core/schemas/state.schema.yaml` | goal |
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

Replace repeated normative text in a skill, prompt or template with a pointer to its owner. Before deleting a rule, confirm the owner still states it and the consuming action receives that protocol in its effective rendered packet. Standalone entrypoints must retain the instructions needed to load that packet; a missing protocol is not replaced by a reference alone.