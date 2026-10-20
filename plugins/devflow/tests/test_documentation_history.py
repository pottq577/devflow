#!/usr/bin/env python3
"""Current public instructions must not acquire stale release-history authority."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "devflow"


class DocumentationHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.plugin_readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        self.changelog = (PLUGIN / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_design_snapshot_is_retired_without_live_references(self) -> None:
        self.assertFalse((PLUGIN / "core/references/vibecoder.md").exists())
        for name, text in (
            ("AGENTS.md", (ROOT / "AGENTS.md").read_text(encoding="utf-8")),
            ("root README", self.root_readme),
            ("plugin README", self.plugin_readme),
        ):
            with self.subTest(document=name):
                self.assertNotIn("vibecoder.md", text)
        self.assertIn("vibecoder.md", self.changelog)
        self.assertIn("Git history", self.changelog)

    def test_root_is_installation_and_current_acceptance_not_release_notes(self) -> None:
        self.assertLessEqual(len(self.root_readme.splitlines()), 55)
        self.assertNotRegex(self.root_readme, r"(?m)^## Version \d")
        for required in (
            "claude plugin marketplace add",
            "codex plugin marketplace add",
            "devflow status <domain>",
            "plugins/devflow/README.md",
            "plugins/devflow/CHANGELOG.md",
            "pending acceptance",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.root_readme)

    def test_current_guidance_retains_runtime_entrypoints(self) -> None:
        for required in (
            "devflow render evidence",
            "devflow autopilot start",
            "devflow delivery enable",
            "devflow delivery check",
            "core/protocol/finalization.md",
            "core/routing/default.yaml",
            "core/routing/models.yaml",
            "remain pending",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.plugin_readme)
        self.assertNotIn("## Hosted Goal efficiency (0.11.0)", self.plugin_readme)
        self.assertNotIn("## Autonomous `/goal` routing (0.10.1", self.plugin_readme)

    def test_plugin_readme_is_a_compact_entrypoint(self) -> None:
        self.assertLessEqual(len(self.plugin_readme.splitlines()), 200)
        self.assertNotIn("--baseline-ref", self.plugin_readme)
        for owner in (
            "core/protocol/role-instructions.md",
            "core/protocol/lifecycle.md",
            "core/protocol/host-telemetry.md",
            "core/protocol/delivery-artifacts.md",
            "core/protocol/finalization.md",
        ):
            with self.subTest(owner=owner):
                self.assertIn(f"]({owner})", self.plugin_readme)

    def test_release_entries_are_nested_without_claiming_native_acceptance(self) -> None:
        manifest = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertIn(f"## {manifest['version']} - ", self.changelog)
        self.assertNotRegex(self.changelog, r"(?m)^## Unreleased - R\d")
        section = self.changelog.split("## 0.11.0 - ", 1)[1].split("## 0.10.1 - ", 1)[0]
        self.assertEqual(len(re.findall(r"(?m)^### R\d\d\b", section)), 19)
        self.assertIn("Native R19 acceptance remains pending", section)
        self.assertIn("installed ELI5 invocation", section)
        self.assertIn("token usage remain unmeasured", self.changelog)

    def test_current_version_and_links_resolve(self) -> None:
        manifest = json.loads(
            (PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8")
        )
        codex = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], codex["version"])
        self.assertEqual(manifest["version"], marketplace["version"])
        self.assertEqual(manifest["version"], marketplace["plugins"][0]["version"])
        for target in (
            "plugins/devflow/README.md",
            "plugins/devflow/CHANGELOG.md",
        ):
            self.assertTrue((ROOT / target).is_file(), target)
        self.assertIn("core/protocol/role-instructions.md", self.plugin_readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
