# Skill composition

## Status

This document is normative for peer-skill composition in DevFlow.

DevFlow owns lifecycle state, artifact contracts, WORK selection, review gates, remediation scheduling, and completion decisions.

Peer skills may influence how work inside the current lifecycle boundary is performed.
They do not own lifecycle transitions.

## Priority

When instructions conflict, use this order:

1. explicit user instructions and repository instructions
2. DevFlow lifecycle, WORK scope, acceptance criteria, and audit policy
3. applicable peer execution disciplines
4. optional peer optimization/minimization policy

A peer skill must not widen the active WORK scope or bypass a DevFlow lifecycle guard.

## Availability

General peer execution disciplines are optional.
The explicitly requested installed ELI5 capability is required only for an enabled protocol 1.8 finalization gate.

Ordinary DevFlow lifecycle commands remain usable when an optional peer plugin is absent.
General commands require no peer-plugin installation or state.
The enabled ELI5 finalization step has the explicit capability/provenance requirement described below.

When a compatible peer capability is already available to the agent, it may be composed according to this document.
Check that the host exposes its entrypoint and any required commands, agents, and tools before invocation.
Read only the peer instructions needed for the current role, WORK scope, and modified paths.
A skill name in the host registry does not establish that its full external workflow can execute.

## Superpowers

Superpowers contributes execution disciplines inside the currently selected DevFlow WORK.

### Allowed execution disciplines

For behavior-changing implementation, use test-driven-development when available.

For defects and remediation WORK, use one available diagnosis discipline before selecting or applying a fix.
Prefer `diagnosing-bugs` for intermittent failures, performance regressions, or unclear root causes; otherwise use `systematic-debugging` when available.
Do not repeat both complete debugging workflows for one symptom.

Before marking a WORK complete, use verification-before-completion when available.
Fresh verification evidence must correspond to the DevFlow WORK verification criteria recorded as completion evidence.

When acting on audit findings, receiving-code-review may be used as an interpretation discipline.
DevFlow audit findings remain the authoritative review record.

### Controller workflows

Do not transfer DevFlow lifecycle ownership to peer controller workflows after DevFlow owns the task.

The following workflows are outside a DevFlow run invocation:

- writing-plans
- executing-plans
- subagent-driven-development
- dispatching-parallel-agents
- requesting-code-review
- using-git-worktrees
- finishing-a-development-branch

Brainstorming may occur before the PRD enters DevFlow.

## Ponytail

Ponytail contributes minimalism, reuse-first, and YAGNI guidance.

Apply the currently active Ponytail policy when available.

Do not automatically enable Ponytail or change its mode.
DevFlow respects whatever Ponytail mode the environment already supplies and never selects `lite`, `full`, `ultra`, or `off` on its own.

Prefer, in order:

1. no new implementation when the requirement is already satisfied
2. reuse of existing repository code
3. standard or platform capabilities
4. already-installed dependencies
5. the smallest direct implementation
6. new abstraction only when required by the current contract

Ponytail guidance must not remove or weaken:

- explicit requirements
- WORK acceptance criteria
- security controls
- trust-boundary validation
- compatibility requirements
- required tests
- data-loss protection
- repository conventions
- DevFlow lifecycle guards

## Vercel agent skills

These optional execution disciplines apply only to relevant React, Next.js, or UI changes.
The current repository contract and framework version remain authoritative.

- `vercel-react-best-practices`: Use for React/Next.js implementation, refactoring, and performance review. Inspect actual data flow, rendering, and bundle behavior; avoid unrelated speculative optimization.
- `vercel-composition-patterns`: Use when designing or changing reusable React component interfaces. Prefer explicit variants and composition only when a shared interface needs them; preserve established component and Storybook contracts. Apply React 19-only rules only on React 19+.
- `web-design-guidelines`: Use as a review lens for changed user-facing UI, interactions, and accessibility. Fetch its current upstream rules when the host can reach them; report only the rules actually checked. Do not start an unrelated redesign.

## Matt Pocock skills

Use these optional disciplines inside an existing DevFlow action:

- `codebase-design`: Evaluate module depth, interface complexity, and testable seams during architecture planning, bounded refactors, and design audits. Do not introduce an adapter or abstraction solely for a hypothetical future implementation.
- `domain-modeling`: Challenge ambiguous domain terminology, state transitions, and edge cases when developing the PLAN or domain behavior. The approved PRD remains authoritative. Create or change `GLOSSARY.md` or an architecture decision record only if the user or selected WORK authorizes that output.
- `diagnosing-bugs`: Establish a fast, repeatable, symptom-specific failing signal before investigating an unclear, intermittent, or performance-related defect. Keep hypotheses and probes inside the selected WORK; report missing reproduction evidence through DevFlow's existing blocker or evidence workflow.
- `writing-for-agents`: Use when editing agent-facing instructions, skills, `AGENTS.md`, `CLAUDE.md`, or agent-consumed specifications. Make invocation conditions, context pointers, and completion checks explicit. Do not create an additional documentation artifact.
- `setup-matt-pocock-skills`: This is a manually invoked repository setup workflow, not an execution discipline. Never run it automatically during DevFlow planning, WORK, auditing, or finalization; its issue-tracker and documentation scaffolding require an explicit request outside the lifecycle.

## Trail of Bits skills

Apply these disciplines only when their verification shape matches the selected scope:

- `property-based-testing`: Use in a WORK with a meaningful, independently checkable property such as roundtrip, idempotence, invariant, or reference oracle. Prefer the existing test framework and the smallest useful generated sample set. Do not add a new testing dependency or broad random-test suite without authorization.
- `differential-review`: Use git history, previous-version comparison, and caller/blast-radius analysis as a security review lens when a change affects authorization, secrets, payments, validation, or another trust boundary. Inspect baseline content with read-only Git commands; do not checkout another revision in the active worktree. The peer's standalone report and agent workflow are outside DevFlow-owned audits.
- `spec-to-code-compliance`: Use requirement-by-requirement checks when an authoritative specification and implementation both exist. Read enforcement, callees, and callers; record search coverage for an absence. The peer's namespaced command, fan-out agents, and separate report are outside DevFlow-owned audits. Do not claim its full compliance workflow ran unless it actually did.

For either audit-focused Trail of Bits skill, use compatible analysis techniques within the existing Auditor context. Do not start peer-controlled subagents, a second audit lifecycle, or standalone report generation during a DevFlow action.

## External execution tools

External execution tools may assist work inside the currently selected DevFlow lifecycle boundary.
They do not own lifecycle transitions, WORK selection, routing decisions, verification gates, or completion decisions.

### Serena

Serena contributes semantic code navigation and refactoring capabilities.

Prefer Serena when symbol-aware information is useful, including:

- symbol and reference discovery
- implementation and type-hierarchy analysis
- cross-file semantic analysis
- semantic rename and refactoring

Use native agent capabilities for ordinary shell operations, Git, configuration files, exact text search, and small localized edits when they are more direct.

Serena adds no DevFlow lifecycle state or required artifacts.

### Headroom

Headroom may provide transparent transport-level context compression.

DevFlow retains ownership of:

- model selection
- reasoning-effort routing
- specialist and task routing
- retry and escalation decisions
- lifecycle state and completion decisions

DevFlow must not depend on Headroom for project memory, lifecycle state, routing state, or completion evidence.

Headroom adds no DevFlow lifecycle state or required artifacts.

Serena and Headroom are optional.
Their absence does not block ordinary DevFlow execution.

## Audit composition

Ponytail review observations are leads, not findings.

A DevFlow auditor must independently verify a lead against the PLAN, WORK scope, codebase, callers, tests, and acceptance criteria.
Map a confirmed lead onto the existing overengineering and scope-intrusion axis in `audit-core.md` rather than a new audit axis.

Only verified observations enter the normal DevFlow AUDIT artifact.

Do not create separate Ponytail review artifacts.

Superpowers code review output is likewise advisory when DevFlow owns the lifecycle.
Verified issues must be represented through normal DevFlow audit and remediation mechanisms.

Additional peer review observations are leads until independently verified by the DevFlow Auditor:

- Map specification divergences from `spec-to-code-compliance` onto axes A/B of `audit-core.md` and its existing finding classes (`CONFIRMED`, `EVIDENCE_REQUIRED`, `DOCUMENTATION_DRIFT`, `SPEC_DRIFT`, or a decision when needed).
- Map security regressions from `differential-review` onto axes D/I/J, with concrete trust-boundary evidence and the pinned diff range.
- Map UI and React observations onto axes C/D/E, and module-design observations onto axes C/F. Confirm applicability to the actual framework and requirements before classifying them.

Use the existing AUDIT file, finding dispositions, and traced WORK. A peer review cannot issue a DevFlow pass, add an audit axis, or waive a gate.

## Artifact budget

Peer composition adds no required lifecycle artifacts.

Do not persist peer-plugin mode or runtime state in:

- STATE.yaml
- WORK manifests
- AUDIT files
- .devflow/config.yaml

unless a future protocol revision explicitly adds such a contract.

## Failure and absence

Missing optional peer disciplines never block ordinary DevFlow execution.
Missing ELI5 blocks only the requested whole-work finalization under `finalization.md`, preserving implemented WORK.

If an optional discipline cannot be invoked, continue using the native DevFlow procedure and repository verification requirements.
If the peer requires unavailable tools, external network rules, another agent tree, or its own artifacts, use only independently verified techniques compatible with the current scope.
Distinguish applying a peer review lens from invoking that peer's complete workflow.

Never simulate successful peer-skill execution or claim that a peer skill was used when it was unavailable.

## Required ELI5 delivery capability

`core/protocol/finalization.md` owns the installed ELI5 invocation, evidence and generated HTML contract. This mandatory capability applies only during enabled finalization; never simulate success when the skill is unavailable.
