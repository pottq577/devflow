#!/usr/bin/env python3
"""Keep optional peer-skill composition reachable from every owning role."""

import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
COMPOSITION = PLUGIN_ROOT / "core" / "protocol" / "skill-composition.md"


class PeerSkillCompositionTests(unittest.TestCase):
    def test_all_supported_peer_skills_have_an_explicit_contract(self):
        protocol = COMPOSITION.read_text(encoding="utf-8")
        for skill in (
            "vercel-react-best-practices", "web-design-guidelines",
            "vercel-composition-patterns", "codebase-design", "diagnosing-bugs",
            "domain-modeling", "writing-for-agents", "setup-matt-pocock-skills",
            "differential-review", "property-based-testing", "spec-to-code-compliance",
        ):
            with self.subTest(skill=skill):
                self.assertIn(f"`{skill}`", protocol)

    def test_role_contracts_load_peer_composition(self):
        for role in ("plan", "run", "audit"):
            with self.subTest(role=role):
                contract = (PLUGIN_ROOT / "skills" / role / "SKILL.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Read `core/protocol/skill-composition.md`", contract)


if __name__ == "__main__":
    unittest.main()
