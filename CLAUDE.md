# Claude Code repository instructions

Read `AGENTS.md` before repository work. It owns the shared `main`-only Git policy, source precedence, lifecycle boundaries and verification gates.

Claude-specific marketplace metadata lives in `.claude-plugin/` and `plugins/devflow/.claude-plugin/`. Keep executable behavior, protocols, schemas, prompts, templates, skills and tests shared under `plugins/devflow/`; do not copy them into Claude-specific adapters.

For conflicts, follow the explicit task instructions first, then `AGENTS.md`, then this file. Keep cross-agent rules in `AGENTS.md` rather than restating them here.
