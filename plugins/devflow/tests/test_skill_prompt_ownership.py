#!/usr/bin/env python3
"""Agent skill entrypoints keep role packets and protocol contracts authoritative."""

from __future__ import annotations

import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]


def skill(name: str) -> str:
    return (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def prompt(name: str) -> str:
    return (PLUGIN / "core" / "prompts" / f"{name}.md").read_text(encoding="utf-8")


class SkillPromptOwnershipTests(unittest.TestCase):
    def test_six_skills_retain_metadata_and_entrypoints(self) -> None:
        for name in ("plan", "run", "audit", "status", "goal", "autopilot"):
            with self.subTest(skill=name):
                content = skill(name)
                self.assertTrue(content.startswith("---\nname: " + name + "\n"))
                self.assertIn("description: ", content)
                self.assertTrue(content.rstrip().endswith("."))
        for name in ("plan", "run", "audit", "status"):
            self.assertIn("scripts/invoke.py", skill(name))
        for name in ("goal", "autopilot"):
            self.assertIn("scripts/host.py", skill(name))

    def test_role_entrypoints_delegate_steps_without_losing_gates(self) -> None:
        required = {
            "plan": ("render plan", "work-item-contract.md", "context", "premise_checks", "finalization.md"),
            "run": ("render run", "work start", "work done", "render finalize", "delivery newman"),
            "audit": ("render audit", "audit apply", "audit-core.md", "Never record `pass`"),
        }
        for name, markers in required.items():
            with self.subTest(role=name):
                combined = skill(name)
                for marker in markers:
                    self.assertIn(marker, combined)
                self.assertIn("core/protocol/skill-composition.md", combined)
                self.assertLessEqual(len(combined.splitlines()), 95)

    def test_render_packets_keep_unique_role_procedures(self) -> None:
        for name in ("plan", "run", "audit"):
            with self.subTest(role=name):
                content = prompt(name)
                self.assertIn("devflow status", content)
                self.assertIn("PITFALLS.md", content)
        self.assertIn("PLAN.md", prompt("plan"))
        self.assertIn("work done", prompt("run"))
        self.assertIn("audit apply", prompt("audit"))
        self.assertIn("core/protocol/audit-core.md", prompt("audit"))

    def test_architect_registers_phases_through_cli(self) -> None:
        packet = prompt("plan")
        for detail in (
            "work/phase-XX.yaml", "devflow phase set <domain> <phase> planned",
            "matching manifest or an existing STATE phase entry", "devflow phase ref",
            "Do not edit machine-owned `STATE.yaml`",
        ):
            with self.subTest(detail=detail):
                self.assertIn(detail, packet)
        self.assertNotIn("Set phase entries with zero-padded keys", packet)

    def test_hosted_safety_and_observation_only_status_survive(self) -> None:
        goal = skill("goal")
        autopilot = skill("autopilot")
        for marker in ("session-start", "session-end", "step-start", "step-finish",
                       "session-recover", "confirm-child-terminated", "spawn_agent"):
            self.assertIn(marker, goal)
        self.assertIn("skills/goal/SKILL.md", autopilot)
        self.assertIn("step-start", autopilot)
        self.assertIn("step-finish", autopilot)
        self.assertIn("not for a status-only inspection", skill("status"))
        self.assertIn("core/protocol/finalization.md", skill("status"))

    def test_protocol_details_are_not_duplicated_in_entrypoints(self) -> None:
        self.assertNotIn("HTTP 200..299 readiness", skill("run"))
        self.assertNotIn("a stale merge base and report hundreds", skill("audit"))
        self.assertNotIn("a static source search alone", skill("plan").lower())
        self.assertNotIn("Every `severity_reason` must name trigger conditions", prompt("audit"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
