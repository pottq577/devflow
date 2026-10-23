# Claude Code native Goal host

Claude Code runs the same DevFlow `/goal` skill and the same STATE/WORK/audit
runtime as Codex. It does **not** run a nested `claude -p`, `codex exec`, or a
supervising DevFlow daemon. Only the host-native Agent invocation changes.

## Host entrypoint and handoff

In Claude Code, replace the Codex `skills/goal/scripts/host.py` entrypoint with
`skills/goal/scripts/claude_host.py` for **every** host action. The wrapper
selects the Claude provider before any routing or lease operation. It refuses
a different host's active lease; use `devflow execution handoff <domain>` and
the explicit, independently attested `session-handoff` procedure first. An
inflight or unconfirmed child must go through the existing administrator
recovery gate; lease age or API quota alone does not authorize takeover.

Call `claude_host.py session-start <domain>` after an idle transfer or clean
release, or use the **new private** `session_id` returned by the prior handoff.
Never reuse the Codex token or treat `owner_marker` as a token. Keep all native
steps sequential; no background workers, worktrees, or recursive Agent spawns.

## Provider-specific routing

`core/routing/claude.yaml` and `core/routing/claude-models.yaml` are Claude-only
sources. Codex continues to use `default.yaml`, `models.yaml` and its ordinary
`.devflow/routing.yaml`/`.devflow/models.yaml` overrides. Claude can use a
host-specific `.devflow/claude-routing.yaml` override, but concrete native
model families remain pinned to `haiku`, `sonnet`, `opus` so every route maps
to an installed plugin Agent definition. Unsupported model/effort combinations
are **blockers**, never silently inherited or downgraded. If the environment
forces `CLAUDE_CODE_SUBAGENT_MODEL` to a non-`inherit` value, stop before
routing; that override can silently supersede the DevFlow model decision.

Default: Scout uses Haiku (read-only intent); implementation, tests and
remediation use Sonnet; architecture, independent review, diagnostics and
finalization use Opus. Higher-risk/retry efforts may increase within these
families. This is a resource-cost default, not a cross-provider strength
comparison. Family aliases track provider releases and are not fixed model
snapshots.

Every `dispatch_required` / `bootstrap` envelope supplies
`primary.claude.agent_type` and, when needed, `scout.claude.agent_type`.
Call Claude Code's **Agent** tool using the exact plugin-scoped agent type,
passing the supplied `message` (or validated `scout_message` + capsule) without
rewriting its pinned render. Use the foreground completion result. The static
agent definitions pin both `model` and `effort`; do not use the parent model,
spawn a generic unpinned agent, or substitute `fork_turns` for Claude arguments.
A capability error, an unexpected agent type, or an unverified model selection
stops dispatch and leaves the WORK state unchanged.

Read-only agent presets deny Edit/Write/NotebookEdit, but a Bash tool is needed
for DevFlow's pinned render and can execute shell side effects. These presets
are **not** an OS-enforced read-only sandbox. Never claim hard isolation; use
an external sandbox if the workflow requires strict enforcement.

The Codex/Claude wrappers share `session-start`, `dispatch`, `step-start`,
`step-finish`, `session-recover` and `session-handoff`. A native Agent terminal
result still cannot establish WORK completion: recheck the actual WORK, Git
and verification state before acknowledging the reserved step. Partial Agent
output on a usage-limit error is **not** a completed outcome. Do not replay
or reissue a still-running child; the host guard is authoritative.

## Verification boundary

The Python regressions validate route selection, native Agent definitions,
provider isolation and persisted guard invariants. They do not verify a live
Claude Code Agent tool call, plan entitlements, exact provider model selection,
permission enforcement or quota interruption. Those require an installed
Claude Code session and the final bidirectional acceptance run.
