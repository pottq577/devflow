#!/usr/bin/env python3
"""A copied audit scaffold cannot authorize a lifecycle transition."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import yaml

import test_devflow as fixtures

PLUGIN = Path(__file__).resolve().parents[1]
TEMPLATE = PLUGIN / "core" / "templates" / "AUDIT.md"


class AuditTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = fixtures.new_repo()
        self.domain = fixtures.audit_remediation_fixture(self.root)
        self.audit_path = self.domain / "audits" / "integration.md"
        self.template = TEMPLATE.read_text(encoding="utf-8")
        self.metadata = yaml.safe_load(self.template.split("---", 2)[1])

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_fresh_domain_has_no_audit_verdict(self) -> None:
        self.assertFalse(self.audit_path.exists())
        for field in (
            "scope", "mode", "verdict", "baseline_sha", "target_sha", "diff_range"
        ):
            with self.subTest(field=field):
                self.assertIsNone(self.metadata[field])
        self.assertEqual(self.metadata["verification"], [])
        self.assertEqual(self.metadata["findings"], [])
        self.assertEqual(self.metadata["closure"], [])

    def test_unfilled_template_is_invalid_for_initial_and_closure(self) -> None:
        runtime = fixtures.load_runtime_module()
        state = yaml.safe_load((self.domain / "STATE.yaml").read_text(encoding="utf-8"))
        for mode in ("initial", "closure"):
            with self.subTest(mode=mode):
                errors = runtime.validate_audit_metadata(
                    self.root, "billing", state, self.metadata,
                    scope="integration", mode=mode, phase=None, work_item=None,
                )
                self.assertTrue(
                    any("audit.verdict must be a string" in error for error in errors),
                    errors,
                )
                self.assertTrue(
                    any("audit.verification must contain at least 1" in error for error in errors),
                    errors,
                )

    def test_audit_apply_rejects_scaffold_without_mutation(self) -> None:
        self.audit_path.write_text(self.template, encoding="utf-8")
        before = {
            str(path.relative_to(self.domain)): path.read_bytes()
            for path in self.domain.rglob("*") if path.is_file()
        }
        rejected = fixtures.devflow(
            self.root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial"
        )
        validated = fixtures.devflow(self.root, "validate", "billing")
        after = {
            str(path.relative_to(self.domain)): path.read_bytes()
            for path in self.domain.rglob("*") if path.is_file()
        }
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertIn("audit.verdict must be a string", rejected.stderr)
        self.assertEqual(validated.returncode, 1, validated.stdout + validated.stderr)
        self.assertIn("canonical audit", validated.stdout + validated.stderr)
        self.assertEqual(before, after)

    def test_pass_without_executed_verification_is_rejected(self) -> None:
        incomplete = dict(self.metadata)
        incomplete.update(fixtures.audit_metadata(self.domain))
        incomplete["verification"] = []
        fixtures.write_audit(self.audit_path, incomplete)
        before = (self.domain / "STATE.yaml").read_bytes()
        rejected = fixtures.devflow(
            self.root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial"
        )
        self.assertEqual(rejected.returncode, 2, rejected.stdout + rejected.stderr)
        self.assertIn("audit.verification must contain at least 1", rejected.stderr)
        self.assertEqual((self.domain / "STATE.yaml").read_bytes(), before)

    def test_completed_template_remains_compatible(self) -> None:
        completed = dict(self.metadata)
        completed.update(fixtures.audit_metadata(self.domain))
        observed = fixtures.sh(["true"], self.root)
        self.assertEqual(observed.returncode, 0)
        completed["verification"] = [{"command": "true", "result": "exit 0"}]
        fixtures.write_audit(self.audit_path, completed)
        applied = fixtures.devflow(
            self.root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial"
        )
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        state = yaml.safe_load((self.domain / "STATE.yaml").read_text(encoding="utf-8"))
        self.assertEqual(state["integration"]["status"], "verified")


if __name__ == "__main__":
    unittest.main(verbosity=2)
