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

## Superpowers

Superpowers contributes execution disciplines inside the currently selected DevFlow WORK.

### Allowed execution disciplines

For behavior-changing implementation, use test-driven-development when available.

For defects and remediation WORK, use systematic-debugging when available before selecting or applying a fix.

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

## Audit composition

Ponytail review observations are leads, not findings.

A DevFlow auditor must independently verify a lead against the PLAN, WORK scope, codebase, callers, tests, and acceptance criteria.
Map a confirmed lead onto the existing overengineering and scope-intrusion axis in `audit-core.md` rather than a new audit axis.

Only verified observations enter the normal DevFlow AUDIT artifact.

Do not create separate Ponytail review artifacts.

Superpowers code review output is likewise advisory when DevFlow owns the lifecycle.
Verified issues must be represented through normal DevFlow audit and remediation mechanisms.

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

Never simulate successful peer-skill execution or claim that a peer skill was used when it was unavailable.

## Required ELI5 delivery capability

During enabled finalization, invoke the installed `eli5` skill through its actual host interface with all PLAN/WORK/branch context.
Record skill-content provenance and truthful invocation evidence in `STATE.delivery.finalization`; write the one prescribed whole-work HTML.
This explicit protocol exception grants derived explanation output and provenance, while lifecycle ownership stays with DevFlow.
Newman likewise runs only through the explicit foreground finalization command.
Missing capabilities are execution blockers, with successful implementation preserved.
