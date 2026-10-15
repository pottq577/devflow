#!/usr/bin/env python3
"""Every role rule has one owner; duplicated obligations are removed, not restated."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
PROMPTS = sorted((PLUGIN / "core" / "prompts").glob("*.md"))
MINIMUM_RULE_LINE = 90


def significant_lines(path: Path) -> set[str]:
    return {
        re.sub(r"\s+", " ", line).strip()
        for line in path.read_text(encoding="utf-8").split("\n")
        if len(re.sub(r"\s+", " ", line).strip()) >= MINIMUM_RULE_LINE
    }


class RoleInstructionTests(unittest.TestCase):
    def test_skills_and_render_prompts_do_not_restate_each_other(self) -> None:
        shared: dict[str, set[str]] = {}
        for path in SKILLS + PROMPTS:
            for line in significant_lines(path):
                shared.setdefault(line, set()).add(str(path.relative_to(PLUGIN)))
        offenders = {
            line: sorted(owners)
            for line, owners in shared.items()
            if len({Path(owner).parent.name for owner in owners}) > 1
            and "wrapper" not in line
        }
        self.assertEqual(offenders, {})

    def test_ownership_matrix_names_every_protocol_and_schema_family(self) -> None:
        matrix = (PLUGIN / "core" / "protocol" / "role-instructions.md").read_text(
            encoding="utf-8"
        )
        for name in (
            "authority.md",
            "lifecycle.md",
            "work-item-contract.md",
            "risk-policy.md",
            "audit-core.md",
            "delivery-artifacts.md",
            "finalization.md",
            "skill-composition.md",
            "work.schema.yaml",
            "delivery.schema.yaml",
            "finalization.schema.yaml",
        ):
            self.assertIn(name, matrix)

    def test_every_protocol_and_schema_is_owned_or_explicitly_scoped(self) -> None:
        matrix = (PLUGIN / "core" / "protocol" / "role-instructions.md").read_text(
            encoding="utf-8"
        )
        owned = set(re.findall(r"[\w.-]+\.(?:md|yaml)", matrix))
        unscoped = [
            path.name
            for path in sorted((PLUGIN / "core" / "protocol").glob("*.md"))
            + sorted((PLUGIN / "core" / "schemas").glob("*.yaml"))
            if path.name not in owned
            and path.name not in {"role-instructions.md", "vibecoder.md"}
        ]
        self.assertEqual(unscoped, [])

    def test_removed_duplicates_keep_their_obligation_with_an_owner(self) -> None:
        finalization = (PLUGIN / "core" / "protocol" / "finalization.md").read_text(
            encoding="utf-8"
        )
        for obligation in (
            "ELI5",
            "Newman",
            "readiness",
            "server",
        ):
            self.assertIn(obligation, finalization)
        for consumer in (
            PLUGIN / "skills" / "plan" / "SKILL.md",
            PLUGIN / "core" / "prompts" / "plan.md",
            PLUGIN / "skills" / "audit" / "SKILL.md",
        ):
            text = consumer.read_text(encoding="utf-8")
            self.assertIn("finalization.md", text)
            self.assertNotIn("Include the protocol 1.8 ELI5/Newman stage in final acceptance", text)

    def test_finalizer_contract_keeps_run_skill_finalize_support(self) -> None:
        run_skill = (PLUGIN / "skills" / "run" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("render finalize", run_skill)
        self.assertIn("finalization.md", run_skill)
        role = (PLUGIN / "core" / "prompts" / "finalize-role.md").read_text(encoding="utf-8")
        self.assertIn("render finalize", role)
        self.assertIn("finalization.md", role)


if __name__ == "__main__":
    unittest.main(verbosity=2)