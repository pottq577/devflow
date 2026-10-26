"""Conservative advisory test selection from changed DevFlow source paths.

This is never release evidence. Unknown plugin source changes expand to every
focused test rather than silently omit a potentially affected regression.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

PLUGIN_PREFIX = "plugins/devflow/"
ROOT_SOURCES = frozenset({
    ".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json",
    "README.md", "AGENTS.md", "CLAUDE.md",
})
DOC_TESTS = frozenset({
    "test_docs_consistency", "test_documentation_history",
    "test_protocol_template_ownership", "test_role_instructions",
    "test_skill_prompt_ownership", "test_repository_instructions",
})
VERSION_TESTS = frozenset({"test_release_version", "test_docs_consistency", "test_release_gate"})
HOST_TESTS = frozenset({
    "test_host_autopilot", "test_hosted_guard", "test_hosted_session",
    "test_host_handoff", "test_subagent_handoff",
    "test_cross_host_parity_integration", "test_codex_crash_resume",
})
IMPACT_MAP = {
    "scripts/devflow_host.py": HOST_TESTS | {"test_claude_native_host"},
    "scripts/devflow_host_guard.py": HOST_TESTS,
    "scripts/devflow_session.py": HOST_TESTS | {"test_execution_progress", "test_execution_resume"},
    "scripts/devflow_execution.py": frozenset({
        "test_execution_progress", "test_execution_resume", "test_codex_crash_resume",
        "test_cross_host_parity_integration", "test_host_autopilot",
    }),
    "scripts/devflow_resume.py": frozenset({
        "test_execution_resume", "test_execution_progress", "test_codex_crash_resume",
    }),
    "scripts/devflow_claude.py": frozenset({
        "test_claude_native_host", "test_cross_host_parity_integration",
        "test_host_autopilot",
    }),
    "scripts/devflow_efficiency.py": frozenset({
        "test_efficiency_report", "test_test_impact",
    }),
    "tests/run_suite.py": frozenset({
        "test_suite_runner", "test_suite_output_budget", "test_release_gate",
        "test_test_impact",
    }),
    "tests/devflow_test_impact.py": frozenset({
        "test_test_impact", "test_suite_runner", "test_release_gate",
    }),
    "tests/release_gate.py": frozenset({
        "test_release_gate", "test_suite_runner", "test_test_impact",
    }),
}
ROUTING_TESTS = frozenset({
    "test_autopilot", "test_host_autopilot", "test_claude_native_host",
    "test_cross_host_parity_integration", "test_policy", "test_scout_contract",
    "test_scout_evidence_cache",
})
BASE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./~^@{}+-]*\Z")
MAX_CHANGED = 512


def _git_bytes(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"git change discovery unavailable: {type(exc).__name__}") from exc
    if result.returncode:
        problem = result.stderr.decode("utf-8", "replace").strip()
        raise ValueError("git change discovery failed: " + problem[:240])
    return result.stdout


def changed_paths(root: Path, base: str) -> list[str]:
    """Combine committed differences, index, worktree and untracked files."""
    if not isinstance(base, str) or not BASE_PATTERN.fullmatch(base):
        raise ValueError("--changed-from requires a safe Git commit/ref (e.g. HEAD or HEAD~1)")
    # Validate the base before examining the worktree; don't accept revisions that
    # Git could interpret as CLI flags or non-commit tree objects.
    _git_bytes(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}")
    tracked = _git_bytes(root, "diff", "--name-only", "--no-renames", "-z", base, "--")
    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z", "--")
    names = sorted({os.fsdecode(entry) for entry in (tracked + untracked).split(b"\0") if entry})
    if len(names) > MAX_CHANGED:
        raise ValueError("too many changed files for advisory impact selection")
    return names


def _relevant(path: str) -> str | None:
    if path.startswith(PLUGIN_PREFIX):
        return path[len(PLUGIN_PREFIX):]
    return "root:" + path if path in ROOT_SOURCES else None


def _targets(path: str) -> set[str] | None:
    """Return known test modules, or None for an ambiguous dependency."""
    if path in IMPACT_MAP:
        return set(IMPACT_MAP[path])
    if path.startswith("tests/test_") and path.endswith(".py") and "/" not in path[6:]:
        return {Path(path).stem}
    if path.startswith("core/routing/"):
        return set(ROUTING_TESTS)
    if path.startswith("core/protocol/") or path.startswith("core/prompts/"):
        return set(DOC_TESTS)
    if path.startswith("skills/") and path.endswith(".md"):
        result = set(DOC_TESTS)
        if path.startswith("skills/goal/"):
            result |= {"test_host_autopilot", "test_claude_native_host"}
        return result
    if path.startswith("agents/") and path.endswith(".md"):
        return {"test_claude_native_host", "test_docs_consistency"}
    if path in {"README.md", "CHANGELOG.md"}:
        return set(DOC_TESTS)
    if path in {"version.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json"}:
        return set(VERSION_TESTS)
    if path.startswith("root:"):
        return set(VERSION_TESTS | DOC_TESTS)
    # Python entrypoints, schemas, unknown fixtures/config, deleted helpers,
    # and unclassified sources may affect many suites indirectly.
    return None


def choose_cases(changes: Iterable[str], cases: Iterable[Any], *, base: str) -> tuple[list[Any], dict]:
    """Choose exact discovered unittest IDs, never substring matches.

    A successful targeted run is explicitly partial, not a coverage claim.
    """
    relevant = sorted({name for name in changes if _relevant(name) is not None})
    if not relevant:
        raise ValueError("--changed-from found no DevFlow source changes")
    all_cases = list(cases)
    modules: set[str] = set()
    unknown: list[str] = []
    for path in relevant:
        targets = _targets(_relevant(path) or "")
        if targets is None:
            unknown.append(path)
        else:
            modules.update(targets)
    available = {case.id().split(".", 1)[0] for case in all_cases}
    missing = modules - available
    if missing:
        raise ValueError("impact map targets missing test modules: " + ", ".join(sorted(missing)[:5]))
    fallback = bool(unknown)
    if fallback:
        selected = [case for case in all_cases
                    if ".LifecycleCases." not in case.id()
                    and ".RealNewmanTests." not in case.id()]
        strategy = "fallback_focused"
    else:
        selected = [case for case in all_cases
                    if case.id().split(".", 1)[0] in modules]
        strategy = "mapped_modules"
    if not selected:
        raise ValueError("impact selection chose no runnable tests")
    meta = {
        "base": base, "strategy": strategy,
        "changed_files": len(relevant), "selected_modules": len({x.id().split('.', 1)[0] for x in selected}),
        "unmapped_count": len(unknown), "unmapped_sample": unknown[:4],
        "authority": "advisory_partial_only",
    }
    return selected, meta
