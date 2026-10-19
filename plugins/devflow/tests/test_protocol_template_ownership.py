#!/usr/bin/env python3
"""Protocol owners and blank template scaffolds survive documentation refactors."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

PLUGIN = Path(__file__).resolve().parents[1]
TEMPLATES = PLUGIN / "core" / "templates"
PROTOCOL = PLUGIN / "core" / "protocol"


class ProtocolTemplateOwnershipTests(unittest.TestCase):
    def test_pitfalls_template_does_not_assert_unobserved_facts(self) -> None:
        text = (TEMPLATES / "PITFALLS.md").read_text(encoding="utf-8")
        self.assertIn("no observed pitfalls", text)
        self.assertIn("not repository facts", text)
        for heading in (
            "Environment and tooling", "Test doubles and local profiles",
            "Code behavior that surprises", "Schema and migration",
        ):
            with self.subTest(heading=heading):
                self.assertIn("## " + heading, text)
        # No sample incident should be loaded as a recorded observation.
        self.assertNotRegex(text, r"(?m)^- (?:Which|Fakes|Methods|Migrations|Work|What) ")
        self.assertNotIn("## Out of scope", text)
        self.assertNotIn("## Lessons carried forward", text)

    def test_audit_scaffold_preserves_unverified_metadata_and_axes(self) -> None:
        text = (TEMPLATES / "AUDIT.md").read_text(encoding="utf-8")
        fields = yaml.safe_load(text.split("---", 2)[1])
        for key in ("scope", "mode", "verdict", "baseline_sha", "target_sha", "diff_range"):
            self.assertIsNone(fields[key], key)
        for key in ("verification", "findings", "closure"):
            self.assertEqual(fields[key], [], key)
        self.assertNotIn("- Classification: `CONFIRMED`", text)
        self.assertNotIn("- Severity: `major`", text)
        for axis in "ABCDEFGHIJ":
            self.assertRegex(text, rf"(?m)^### {axis}\. ")
        self.assertIn("## Integration-only axes", text)
        self.assertIn("## Verification performed", text)

    def test_audit_template_has_one_machine_metadata_source(self) -> None:
        text = (TEMPLATES / "AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("## Reviewed changes", text)
        self.assertIn("Apply the completed audit with `devflow audit apply`", text)
        self.assertNotIn("| Baseline SHA", text)
        self.assertNotIn("Phase / integration status to set", text)

    def test_protocol_guidance_uses_one_rule_owner(self) -> None:
        decision = (PROTOCOL / "decision-policy.md").read_text(encoding="utf-8")
        authority = (PROTOCOL / "authority.md").read_text(encoding="utf-8")
        lifecycle = (PROTOCOL / "lifecycle.md").read_text(encoding="utf-8")
        host = (PROTOCOL / "host-telemetry.md").read_text(encoding="utf-8")
        delivery = (PROTOCOL / "delivery-artifacts.md").read_text(encoding="utf-8")
        prompt = (PLUGIN / "core/prompts/plan.md").read_text(encoding="utf-8")
        self.assertIn("devflow decision resolve <domain> <DEC-ID>", decision)
        self.assertIn("devflow decision add <domain> <DEC-ID>", prompt)
        self.assertNotIn("Set STATE so", prompt)
        self.assertNotIn("## Pinning a range", authority)
        self.assertNotIn("## Delivery output authority", authority)
        self.assertIn("core/protocol/audit-core.md", authority)
        self.assertIn("core/protocol/host-telemetry.md", lifecycle)
        self.assertIn("## Hosted Scout capsule provenance", host)
        self.assertNotIn("HTTP 200..299 readiness check", delivery)

    def test_required_plan_and_audit_remediation_headings_remain(self) -> None:
        plan = (TEMPLATES / "PLAN.md").read_text(encoding="utf-8")
        for name in (
            "Metadata", "Repository findings", "Architecture / implementation strategy",
            "Requirement traceability", "Phase graph", "Verification strategy",
            "Implementation comments and branch delivery",
        ):
            self.assertIn("## " + name, plan)
        self.assertIn("core/protocol/delivery-artifacts.md", plan)
        anchors = {
            "PRD.audit-remediation.md": (
                "Audit target", "User-verified flows", "In scope", "Out of scope",
                "Authoritative requirements and policies", "Success criteria", "Open decisions",
            ),
            "PLAN.audit-remediation.md": (
                "Metadata", "Repository reconnaissance", "Audit axes", "Evidence plan",
                "Finding disposition strategy", "Remediation topology", "Closure criteria",
            ),
        }
        for filename, required in anchors.items():
            text = (TEMPLATES / filename).read_text(encoding="utf-8")
            for title in required:
                with self.subTest(template=filename, section=title):
                    self.assertIn("## " + title, text)

    def test_severity_and_verdict_have_distinct_owners(self) -> None:
        audit = (PROTOCOL / "audit-core.md").read_text(encoding="utf-8")
        risk = (PROTOCOL / "risk-policy.md").read_text(encoding="utf-8")
        self.assertIn("risk-policy.md", audit)
        self.assertNotRegex(audit, r"(?m)^\| `(?:blocker|major|minor|nit)` ")
        for value in ("blocker", "major", "minor", "nit", "severity_reason", "still_open"):
            self.assertIn(value, risk)
        for verdict in ("pass", "conditional_pass", "fail"):
            self.assertIn("| `" + verdict + "`", audit)

    def test_finalization_owns_detailed_newman_procedures(self) -> None:
        finalization = (PROTOCOL / "finalization.md").read_text(encoding="utf-8")
        lifecycle = (PROTOCOL / "lifecycle.md").read_text(encoding="utf-8")
        work = (PROTOCOL / "work-item-contract.md").read_text(encoding="utf-8")
        for token in ("SIGTERM", "SIGKILL", "readiness", "NEWMAN-<run-id>", "delivery triage"):
            self.assertIn(token, finalization)
        self.assertIn("finalization.md", lifecycle)
        self.assertIn("finalization.md", work)
        self.assertIn("NEWMAN-<run-id>", work)
        self.assertNotIn("SIGTERM/SIGKILL", lifecycle)

    def test_owner_pointer_is_required_in_rendered_consumer(self) -> None:
        ownership = (PROTOCOL / "role-instructions.md").read_text(encoding="utf-8")
        self.assertIn("effective rendered packet", ownership)
        self.assertIn("Standalone entrypoints", ownership)
        for name in ("audit-core.md", "risk-policy.md", "finalization.md"):
            self.assertIn(name, ownership)


if __name__ == "__main__":
    unittest.main(verbosity=2)
