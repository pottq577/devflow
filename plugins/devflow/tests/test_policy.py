#!/usr/bin/env python3
"""Focused tests for technical decisions, policy assumptions, and closing gates."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import devflow_policy as policy


class PolicyTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="devflow-policy-")
        self.addCleanup(t.cleanup)
        self.d = Path(t.name)
        (self.d / "PRD.md").write_text(
            "# PRD\n## 4. Requirements\n### REQ-001 — feature\n"
            "### REQ-002 — other\n## 5. Business Rules\n### RULE-001 — policy\n",
            encoding="utf-8",
        )
        (self.d / "DECISIONS.md").write_text(
            "# Decisions\n\n## Open\n\n## Resolved\n", encoding="utf-8"
        )
        self.index = {}
        self.reviewed = lambda item: item.get("review", {}).get("status") in {"verified", "skipped"}

    @staticmethod
    def args(**updates):
        base = {
            "decision": "DEC-P01", "title": "Schedule policy", "requirement": ["RULE-001"],
            "text": "Keep internal identifiers stable", "rationale": "Existing repository convention",
            "by": "developer", "original_difference": "technical",
            "original_behavior": "Use the original schedule", "assumption": "Use the revised schedule",
            "basis": "Domain analysis", "alternatives": "Keep original schedule",
            "contract_impact": "possible", "impact_description": "User-visible schedule",
            "rollback": "Revert calculation and tests", "risk": "low", "category": "workflow",
            "confirmation_owner": "product planner", "safe_to_prototype": True,
            "evidence": "approved meeting 2026-10-20", "approved_policy": "Use the revised schedule",
            "matches_assumption": True, "corrective_work": [],
        }
        base.update(updates)
        return SimpleNamespace(**base)

    def update(self, command, args=None):
        body = policy.apply(
            self.d, command, args or self.args(), self.index, self.reviewed
        )
        (self.d / "DECISIONS.md").write_text(body, encoding="utf-8")
        return body

    def index_work(self, name, status="done", reqs=None, links=None, review="verified"):
        self.index[name] = (
            self.d / "work/phase-01.yaml",
            {"id": name, "status": status,
             "origin": {"requirements": reqs if reqs is not None else ["RULE-001"],
                        "policy_assumptions": links if links is not None else ["DEC-P01"]},
             "review": {"required": True, "status": review}},
        )

    def test_technical_decision_is_not_product_approval(self):
        self.update("technical", self.args(decision="DEC-T01", requirement=["REQ-001"]))
        found = policy.summary(self.d)
        self.assertEqual(found[0]["kind"], "technical")
        self.assertEqual(policy.outstanding(self.d, self.index, self.reviewed), [])

    def test_provisional_can_be_declared_without_blocking_work(self):
        self.update("assume")
        self.index_work("P01-I01", status="in_progress")
        problems, warnings = policy.validate(self.d, self.index, self.reviewed, final=False)
        self.assertEqual(problems, [])
        self.assertTrue(any("pending" in msg for msg in warnings))
        self.assertIn("provisional", policy.outstanding(self.d, self.index, self.reviewed)[0])

    def test_approved_matching_policy_clears_confirmation_gate(self):
        self.update("assume")
        self.index_work("P01-I01")
        self.update("approve")
        self.assertEqual(policy.outstanding(self.d, self.index, self.reviewed), [])
        self.assertEqual(policy.validate(self.d, self.index, self.reviewed, final=True)[0], [])
        self.assertEqual(policy.summary(self.d)[0]["Approval authority"], "developer")

    def test_approved_requires_verified_linked_implementation(self):
        self.update("assume")
        self.update("approve")
        self.assertIn("no verified implementation", policy.outstanding(self.d, self.index, self.reviewed)[0])
        self.index_work("P01-I01", status="done", review="pending")
        self.assertIn("no verified implementation", policy.outstanding(self.d, self.index, self.reviewed)[0])
        self.index_work("P01-I01", status="done", review="verified")
        self.assertEqual(policy.outstanding(self.d, self.index, self.reviewed), [])

    def test_policy_changed_by_product_requires_corrective_work(self):
        self.update("assume")
        with self.assertRaisesRegex(policy.PolicyError, "requires --corrective-work"):
            self.update("approve", self.args(matches_assumption=False,
                                             approved_policy="Restore original schedule"))
        self.update("approve", self.args(matches_assumption=False,
                                         approved_policy="Restore original schedule",
                                         corrective_work=["P02-I01"]))
        self.assertTrue(any("absent" in x for x in policy.outstanding(self.d, self.index, self.reviewed)))
        self.index_work("P02-I01", status="in_progress")
        self.assertTrue(any("not verified" in x for x in policy.outstanding(self.d, self.index, self.reviewed)))
        self.index_work("P02-I01")
        self.assertEqual(policy.outstanding(self.d, self.index, self.reviewed), [])

    def test_rejected_policy_blocks_until_corrective_work_and_reconciliation(self):
        self.update("assume")
        self.update("reject", self.args(matches_assumption=False,
                                        approved_policy="Use the original schedule",
                                        corrective_work=["P02-I01"]))
        self.index_work("P02-I01")
        self.assertIn("rejected", policy.outstanding(self.d, self.index, self.reviewed)[0])
        self.update("reconcile", self.args(evidence="acceptance audit 2026-10-21"))
        self.assertEqual(policy.outstanding(self.d, self.index, self.reviewed), [])
        self.assertEqual(policy.summary(self.d)[0]["Status"], "reconciled")

    def test_rejection_must_specify_correction(self):
        self.update("assume")
        with self.assertRaisesRegex(policy.PolicyError, "requires --corrective-work"):
            self.update("reject", self.args(approved_policy="Return to original schedule",
                                            corrective_work=[]))

    def test_reconciliation_rejects_incomplete_or_unlinked_work(self):
        self.update("assume")
        self.update("reject", self.args(approved_policy="Return to original schedule",
                                        corrective_work=["P02-I01"]))
        self.index_work("P02-I01", links=[])
        with self.assertRaisesRegex(policy.PolicyError, "lacks policy_assumptions link"):
            self.update("reconcile")
        self.index_work("P02-I01", review="pending")
        with self.assertRaisesRegex(policy.PolicyError, "not verified"):
            self.update("reconcile")

    def test_work_origin_detects_unknown_decision(self):
        self.index_work("P01-I01", links=["DEC-UNKNOWN"])
        errors, _ = policy.validate(self.d, self.index, self.reviewed)
        self.assertTrue(any("unknown policy" in err for err in errors))

    def test_work_origin_detects_mismatched_requirement(self):
        self.update("assume")
        self.index_work("P01-I01", reqs=["REQ-001"])
        errors, _ = policy.validate(self.d, self.index, self.reviewed)
        self.assertTrue(any("no matching requirement" in err for err in errors))

    def test_new_decision_needs_existing_prd_requirement(self):
        with self.assertRaisesRegex(policy.PolicyError, "No PRD requirement"):
            self.update("assume", self.args(requirement=["RULE-999"]))

    def test_existing_open_decision_id_cannot_be_reused(self):
        (self.d / "DECISIONS.md").write_text(
            "# Decisions\n## Open\n### DEC-P01 — question\n- Option A: X\n- Option B: Y\n## Resolved\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(policy.PolicyError, "already exists"):
            self.update("assume")

    def test_duplicate_ids_across_sections_detected(self):
        self.update("assume")
        path = self.d / "DECISIONS.md"
        path.write_text(path.read_text(encoding="utf-8") +
                        "\n## Open\n### DEC-P01 — same id\n- Option A: A\n- Option B: B\n",
                        encoding="utf-8")
        errors, _ = policy.validate(self.d, self.index, self.reviewed)
        self.assertTrue(any("duplicate" in msg for msg in errors))

    def test_disallowed_high_risk_or_nonreversible_provisional(self):
        for args in (
            self.args(risk="high"),
            self.args(contract_impact="confirmed"),
            self.args(category="billing"),
            self.args(safe_to_prototype=False),
        ):
            with self.subTest(args=args):
                with self.assertRaises(policy.PolicyError):
                    self.update("assume", args)

    def test_approved_policy_must_match_attested_assumption(self):
        self.update("assume")
        with self.assertRaisesRegex(policy.PolicyError, "exact assumed policy"):
            self.update("approve", self.args(approved_policy="Something different"))

    def test_multiline_fields_cannot_inject_headings(self):
        with self.assertRaisesRegex(policy.PolicyError, "single line"):
            self.update("assume", self.args(title="Malicious\n## Resolved"))

    def test_fenced_decision_headings_not_counted(self):
        path = self.d / "DECISIONS.md"
        path.write_text(path.read_text(encoding="utf-8") +
                        "\n```md\n## Policy assumptions\n### DEC-P01 — fake\n```\n",
                        encoding="utf-8")
        self.update("assume")
        self.assertEqual(len(policy.summary(self.d)), 1)

    def test_repeated_transition_not_accepted(self):
        self.update("assume")
        self.update("approve")
        with self.assertRaisesRegex(policy.PolicyError, "requires provisional"):
            self.update("approve")

    def test_final_gate_detects_deleted_policy_record_still_linked_by_work(self):
        self.update("assume")
        self.index_work("P01-I01")
        self.update("approve")
        (self.d / "DECISIONS.md").write_text("# Decisions\n## Open\n## Resolved\n", encoding="utf-8")
        blockers = policy.outstanding(self.d, self.index, self.reviewed)
        self.assertTrue(any("missing referenced policy" in x for x in blockers))

    def test_corrective_remediation_work_id_supported(self):
        self.update("assume")
        self.update("reject", self.args(approved_policy="Return to original schedule",
                                        corrective_work=["P01-R18"]))
        self.index_work("P01-R18")
        self.update("reconcile")
        self.assertEqual(policy.outstanding(self.d, self.index, self.reviewed), [])

    def test_final_validation_errors_when_policy_is_provisional(self):
        self.update("assume")
        errors, _ = policy.validate(self.d, self.index, self.reviewed, final=True)
        self.assertTrue(any("product contract not closed" in x for x in errors))

    def test_final_validation_checks_correction_review(self):
        self.update("assume")
        self.update("approve", self.args(matches_assumption=False,
                                         approved_policy="Restore original schedule",
                                         corrective_work=["P02-I01"]))
        self.index_work("P02-I01", review="pending")
        errors, _ = policy.validate(self.d, self.index, self.reviewed, final=True)
        self.assertTrue(any("not verified" in x for x in errors))

    def test_schema_rejects_mutated_status(self):
        self.update("assume")
        path = self.d / "DECISIONS.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "- Status: provisional", "- Status: magically-approved"), encoding="utf-8")
        errors, _ = policy.validate(self.d, self.index, self.reviewed)
        self.assertTrue(any("invalid policy status" in x for x in errors))


if __name__ == "__main__":
    unittest.main(verbosity=2)
