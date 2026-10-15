#!/usr/bin/env python3
"""Audit scope bounds the delivery check; audit apply still enforces the domain."""

from __future__ import annotations

import unittest
from pathlib import Path

import test_delivery
import test_devflow as fixtures

PLUGIN = Path(__file__).resolve().parents[1]


class AuditDeliveryScopeTests(test_delivery.DeliveryFixtureMixin, unittest.TestCase):
    def prepare(self):
        self.start_and_commit()
        self.write_artifacts()
        self.assertEqual(self.done().returncode, 0)
        return self.read_work()

    def test_work_scope_defers_the_domain_wide_check_but_apply_still_enforces_it(self) -> None:
        for relative in ("core/prompts/audit.md", "skills/audit/SKILL.md"):
            with self.subTest(source=relative):
                text = (PLUGIN / relative).read_text(encoding="utf-8")
                self.assertIn("domain-wide `delivery check`", text)
                self.assertIn("`--final`", text)
                self.assertIn("`audit apply`", text.replace("audit apply already", "`audit apply` already"))

    def test_audit_apply_rejects_broken_delivery_evidence_for_the_audited_item(self) -> None:
        doc = self.prepare()
        item = doc["items"][0]
        item["risk"]["level"] = "high"
        item["premise_checks"] = ["Confirm the retry invariant still holds at HEAD."]
        fixtures.dump(self.work_path, doc)
        audit_path = self.d / "audits/work/P01-I01.md"
        fixtures.write_audit(
            audit_path,
            fixtures.audit_metadata(
                self.d,
                scope="work",
                work_item="P01-I01",
                mode="initial",
            ),
        )
        self.pr.write_text("tampered\n", encoding="utf-8")
        result = self.cli(
            "audit", "apply", "sample", "--scope", "work", "--task", "P01-I01",
            "--mode", "initial",
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("validation:", result.stderr)
        self.assertNotIn("audit applied", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)