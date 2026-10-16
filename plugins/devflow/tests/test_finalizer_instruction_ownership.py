#!/usr/bin/env python3
"""Finalizer entry points delegate procedure and evidence rules to their owners."""

from __future__ import annotations

import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
PROMPTS = PLUGIN / "core" / "prompts"


class FinalizerInstructionOwnershipTests(unittest.TestCase):
    def test_hosted_entry_reads_rendered_packet_and_all_manifest_pages(self) -> None:
        role = (PROMPTS / "finalize-role.md").read_text(encoding="utf-8")
        for required in (
            "devflow render finalize <domain>",
            "--manifest-page <n>",
            "work_file",
            "scope_sha256",
            "Every WORK disposition",
            "core/protocol/finalization.md",
            "core/protocol/delivery-artifacts.md",
        ):
            with self.subTest(required=required):
                self.assertIn(required, role)
        self.assertIn("Newman precedes ELI5", role)
        self.assertNotIn("SIGTERM/SIGKILL", role)
        self.assertNotIn("`not_applicable` requires", role)
        self.assertNotIn("NEWMAN-<run-id>", role)

    def test_rendered_execution_steps_preserve_order_and_handoff(self) -> None:
        prompt = (PROMPTS / "finalize.md").read_text(encoding="utf-8")
        sequence = (
            "Inspect every WORK",
            "delivery newman",
            "delivery triage",
            "delivery refresh",
            "delivery context",
            "delivery explain",
            "delivery check --final",
            "delivery finalize",
            "`validate`",
            "`status`",
        )
        positions = [prompt.find(token) for token in sequence]
        self.assertTrue(all(pos >= 0 for pos in positions), positions)
        self.assertEqual(positions, sorted(positions))
        self.assertIn("independent audit or decision", prompt)
        self.assertIn("core/protocol/finalization.md", prompt)
        self.assertIn("core/protocol/delivery-artifacts.md", prompt)

    def test_prompts_do_not_copy_long_procedural_lines(self) -> None:
        role = (PROMPTS / "finalize-role.md").read_text(encoding="utf-8")
        execution = (PROMPTS / "finalize.md").read_text(encoding="utf-8")
        def long_lines(content: str) -> set[str]:
            return {
                line.strip()
                for line in content.splitlines()
                if len(line.strip()) >= 80
            }

        self.assertEqual(long_lines(role) & long_lines(execution), set())

    def test_auditor_defers_finalization_criteria_to_protocol(self) -> None:
        audit = (PROMPTS / "audit.md").read_text(encoding="utf-8")
        final_section = audit.split("## Whole-work finalization review", 1)[1]
        self.assertIn("core/protocol/audit-core.md", final_section)
        self.assertIn("core/protocol/finalization.md", final_section)
        self.assertIn("Auditor's verdict", final_section)
        self.assertNotIn("SIGTERM/SIGKILL", final_section)


if __name__ == "__main__":
    unittest.main(verbosity=2)
