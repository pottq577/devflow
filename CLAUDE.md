# Claude Code Repository Instructions

Before doing any work in this repository, read `./AGENTS.md` in full and follow it as the repository-wide source of truth for agent behavior.

## Mandatory startup

Run:

```bash
git branch --show-current
git status --short
```

Claude Code must work only on `main` in this repository.

- If the working tree is clean and the current branch is not `main`, run `git switch main` before continuing.
- If another branch contains uncommitted changes, preserve them and do not modify the repository until the `main`-only rule can be satisfied safely.
- Do not create feature/fix/release branches, temporary branches, detached HEADs, or worktrees.
- Re-check the branch before committing or reporting completion.

## Claude adapter boundary

`.claude-plugin/` and `plugins/devflow/.claude-plugin/` are Claude Code marketplace/plugin adapters. Shared DevFlow behavior belongs in `plugins/devflow/` and must remain shared with Codex.

Do not copy runtime, protocol, schemas, templates, prompts, tests, or skills into Claude-specific adapter directories.

## Instruction precedence

For repository work, follow this order:

1. Explicit instructions for the current task.
2. `AGENTS.md`.
3. This Claude-specific adapter file.

Keep this file intentionally thin. Add cross-agent repository policy to `AGENTS.md` rather than duplicating it here.
