#!/usr/bin/env python3
"""Check that always-loaded repository guidance stays short and preserves its gates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"


class RepositoryInstructionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agents = AGENTS.read_text(encoding="utf-8")
        self.claude = CLAUDE.read_text(encoding="utf-8")

    def test_main_only_safety_is_repo_specific(self) -> None:
        for required in (
            "git branch --show-current",
            "git status --short",
            "git switch main",
            "uncommitted changes",
            "worktrees",
            "consuming projects",
            "Recheck the branch",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.agents)
        self.assertIn("Never reset, clean, force-checkout", self.agents)

    def test_shared_authority_and_lifecycle_guards_remain(self) -> None:
        for required in (
            "plugins/devflow/core/protocol/",
            "plugins/devflow/core/schemas/",
            "plugins/devflow/scripts/",
            "plugins/devflow/core/protocol/role-instructions.md",
            "exactly one selected ready WORK",
            "high/critical WORK",
            "independent review",
            "STATE.yaml",
            "atomic",
            "finalization.md",
            "Do not weaken validators",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.agents)

    def test_release_rules_are_linked_and_not_reimplemented(self) -> None:
        for required in (
            "plugins/devflow/core/protocol/release-validation.md",
            "release_gate.py",
            "./package.sh",
            "git archive",
            "100755",
            ".agents/plugins/marketplace.json",
            "plugins/devflow/.codex-plugin/",
            "plugins/devflow/.claude-plugin/",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.agents)
        self.assertNotIn("python3 -m py_compile \\", self.agents)
        self.assertNotIn("Run the full suite twice", self.agents)
        self.assertNotRegex(self.agents, r"(?m)^plugin version:\s*\d")
        self.assertNotRegex(self.agents, r"(?m)^protocol version:\s*\d")

    def test_only_existing_owner_documents_are_referenced(self) -> None:
        for relative in (
            "plugins/devflow/core/protocol/role-instructions.md",
            "plugins/devflow/core/protocol/release-validation.md",
            "plugins/devflow/core/protocol/lifecycle.md",
            "plugins/devflow/core/protocol/delivery-artifacts.md",
            "plugins/devflow/core/protocol/finalization.md",
            "plugins/devflow/scripts/devflow.py",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)

    def test_always_loaded_context_is_bounded(self) -> None:
        self.assertLessEqual(len(self.agents.splitlines()), 140)
        self.assertLessEqual(len(self.claude.splitlines()), 20)
        self.assertEqual(self.agents.count("```"), 2)
        self.assertNotRegex(self.agents, r"(?m)^## \d+\. ")
        self.assertNotIn("git branch --show-current", self.claude)
        self.assertIn("Read `AGENTS.md`", self.claude)
        self.assertIn("plugins/devflow/", self.claude)


if __name__ == "__main__":
    unittest.main(verbosity=2)
