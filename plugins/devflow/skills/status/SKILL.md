---
name: status
description: Inspect DevFlow STATE and WORK deterministically and report the current lifecycle position and next action. Use when resuming work, switching agent sessions, checking blockers, or deciding whether to plan, run, audit, request a decision, or finish.
---

# DevFlow Status

Use the deterministic runtime instead of reconstructing state from narrative documents.

1. Run `python3 scripts/invoke.py status <domain>`.
2. When detailed machine state is needed, run `python3 scripts/invoke.py status <domain> --json`.
3. When the next executable work contract is needed, run `python3 scripts/invoke.py next <domain>`.
4. Report exactly the computed lifecycle position, blockers, next role, next command, scope/mode, phase, and WORK ID.

Do not infer a different next action from stale README, audit prose, historical chat, or handoff documents. If STATE/WORK validation fails, report the validation problem as the next thing to fix.
