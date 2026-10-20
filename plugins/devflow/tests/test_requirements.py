#!/usr/bin/env python3
"""Requirement snapshot tests: four independent axes and no invented evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import devflow_requirements as requirements
import devflow_policy as policy
import devflow_sources as sources


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="devflow-req-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.d = self.root / "docs/domains/example"
        self.d.mkdir(parents=True)
        self.source = self.root / "original.md"
        self.context = self.root / "context.md"
        self.source.write_text(
            "# Original\n### REQ-001 — Create employee\nCreate employee endpoint\n"
            "### RULE-002 — Schedule policy\nOriginal calculation\n", encoding="utf-8"
        )
        self.context.write_text("# Notes\nInternal implementation context\n", encoding="utf-8")
        sources.capture(self.root, self.d, "example", self.source, self.context)
        self.d.joinpath("PRD.md").write_text(
            "# PRD\n## 4. Requirements\n### REQ-001 — Create employee\n"
            "- Acceptance criteria:\n  - AC-001: Create employee\n"
            "## 5. Business Rules\n### RULE-002 — Schedule policy\n"
            "## 11. Source traceability\n"
            "| Source | Lines | Disposition | Requirements | Reason |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| original:v1 | L1-L1 | background | - | Heading |\n"
            "| original:v1 | L2-L3 | mapped | REQ-001 | Endpoint |\n"
            "| original:v1 | L4-L5 | mapped | RULE-002 | Policy |\n"
            "| context:v1 | L1-L1 | background | - | Heading |\n"
            "| context:v1 | L2-L2 | reference | REQ-001 | Context |\n",
            encoding="utf-8",
        )
        self.rows = [
            "| REQ-001 | P01-01 | 01 | P01-I01 | implement | endpoint |",
            "| RULE-002 | P01-02 | 01 | P01-I02 | implement | policy |",
        ]
        self.write_plan()
        (self.d / "DECISIONS.md").write_text("# Decisions\n## Open\n## Resolved\n", encoding="utf-8")
        self.state = {"phases": {"01": {"work_file": "work/phase-01.yaml", "status": "verified"}},
                      "unresolved_decisions": []}
        self.index = {
            "P01-I01": (self.d / "work/phase-01.yaml", self.work("REQ-001", ["AC-001"])),
            "P01-I02": (self.d / "work/phase-01.yaml", self.work("RULE-002", [])),
        }
        (self.root / "service.py").write_text("def create(): return 1\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "tests@example.com")
        self.git("config", "user.name", "Tests")
        self.git("add", "-A")
        self.git("commit", "-qm", "initial")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        audit = ("---\nschema: devflow-audit-v1\nscope: phase\nmode: initial\n"
                 f"verdict: pass\nbaseline_sha: {self.base}\ntarget_sha: {self.base}\n"
                 "verification:\n  - command: pytest\n    result: passed\nfindings: []\n---\n\n# Audit\n")
        (self.d / "audits/work").mkdir(parents=True)
        (self.d / "audits/phase-01.md").write_text(audit, encoding="utf-8")
        for work_id in ("P01-I01", "P01-I02"):
            (self.d / f"audits/work/{work_id}.md").write_text(
                audit.replace("scope: phase", f"scope: work\ntask: {work_id}"), encoding="utf-8"
            )
        for _, item in self.index.values():
            item["evidence"] = {"commit": self.base, "changed_files": ["service.py"],
                                "commands": [{"command": "pytest", "exit_code": 0}]}
        self.set_compare("P01-I01", "REQ-001", "aligned", "L2-L3")
        self.set_compare("P01-I02", "RULE-002", "aligned", "L4-L5")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True, text=True, capture_output=True)

    @staticmethod
    def work(req, ac):
        return {"status": "done", "kind": "implementation", "origin": {
            "requirements": [req], "acceptance_criteria": ac},
            "review": {"required": True, "status": "verified"}}

    def write_plan(self):
        (self.d / "PLAN.md").write_text(
            "# Plan\n## Requirement traceability\n"
            "| Requirement | Plan item | Phase | Work items | Disposition | Reason |\n"
            "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(self.rows) + "\n", encoding="utf-8"
        )

    def set_compare(self, work_id, req, relation, lines):
        self.index[work_id][1]["origin"].setdefault("original_comparison", {})[req] = {
            "relation": relation, "source": "original:v1 " + lines,
            "evidence": "Direct comparison to captured original and implementation",
        }

    def snap(self):
        return requirements.collect(self.d, self.index, self.state, root=self.root,
                                    head_sha=self.git("rev-parse", "HEAD").stdout.strip(),
                                    review_satisfied=lambda item: (
                                        item.get("review", {}).get("status") in {"verified", "skipped"}
                                    ))

    def row(self, req="REQ-001"):
        return next(x for x in self.snap()["requirements"] if x["id"] == req)

    @staticmethod
    def policy_args(**updates):
        args = {
            "decision": "DEC-P01", "title": "Schedule calculation", "requirement": ["RULE-002"],
            "original_behavior": "Calculate as original", "assumption": "Calculate as revised",
            "basis": "Domain knowledge", "alternatives": "Use the original calculation",
            "contract_impact": "possible", "impact_description": "Time calculation",
            "rollback": "Restore original calculation", "risk": "low", "category": "calculation",
            "by": "developer", "confirmation_owner": "product designer", "safe_to_prototype": True,
            "evidence": "meeting", "approved_policy": "Calculate as revised",
            "matches_assumption": True, "corrective_work": [],
        }
        args.update(updates)
        return SimpleNamespace(**args)

    def policy_event(self, event, **updates):
        new = policy.apply(self.d, event, self.policy_args(**updates), self.index,
                           lambda w: w.get("review", {}).get("status") == "verified")
        (self.d / "DECISIONS.md").write_text(new, encoding="utf-8")

    def test_fully_evidenced_is_implemented_aligned_verified(self):
        row = self.row()
        self.assertEqual((row["implementation"], row["difference"], row["decision"], row["verification"]),
                         ("implemented", "aligned", "not_required", "passed"))

    def test_deterministic_read_only_snapshot(self):
        before = (self.d / "PRD.md").read_bytes()
        a = self.snap()
        b = self.snap()
        self.assertEqual(a, b)
        self.assertEqual((self.d / "PRD.md").read_bytes(), before)
        self.assertEqual(a["summary"]["total"], 2)
        self.assertEqual(a["summary"]["implemented"], 2)
        self.assertEqual(a["diagnostics"]["errors"], [])
        self.assertEqual([row["id"] for row in a["requirements"]], ["REQ-001", "RULE-002"])

    def test_ready_is_not_implemented(self):
        self.index["P01-I01"][1]["status"] = "ready"
        row = self.row()
        self.assertEqual(row["implementation"], "not_implemented")
        self.assertEqual(row["verification"], "not_run")
        self.assertEqual(row["difference"], "unknown")

    def test_work_in_progress_is_partial(self):
        self.index["P01-I01"][1]["status"] = "in_progress"
        self.assertEqual(self.row()["implementation"], "partial")
        self.assertEqual(self.row()["verification"], "pending_review")

    def test_mixed_done_and_ready_is_partial(self):
        self.rows[0] = "| REQ-001 | P01-01 | 01 | P01-I01, P01-I03 | implement | expanded |"
        self.write_plan()
        self.index["P01-I03"] = (self.d / "work/phase-01.yaml", self.work("REQ-001", ["AC-001"]))
        self.index["P01-I03"][1]["status"] = "ready"
        row = self.row()
        self.assertEqual(row["implementation"], "partial")
        self.assertEqual(row["verification"], "pending_review")
        self.assertEqual(row["comparison_completeness"], "partial" if row["comparison_kinds"] else "unknown")

    def test_missing_acceptance_makes_implementation_partial(self):
        self.index["P01-I01"][1]["origin"]["acceptance_criteria"] = []
        row = self.row()
        self.assertEqual(row["implementation"], "partial")
        self.assertEqual(row["unmapped_acceptance_ids"], ["AC-001"])
        self.assertNotEqual(row["verification"], "passed")

    def test_missing_plan_work_is_unknown(self):
        self.rows[0] = "| REQ-001 | P01-01 | 01 | P01-I99 | implement | missing |"
        self.write_plan()
        row = self.row()
        self.assertEqual(row["implementation"], "unknown")
        self.assertEqual(row["verification"], "unknown")

    def test_unlisted_work_is_unknown_instead_of_false_complete(self):
        self.index["P01-I99"] = (self.d / "work/phase-01.yaml", self.work("REQ-001", ["AC-001"]))
        row = self.row()
        self.assertEqual(row["implementation"], "unknown")
        self.assertEqual(row["unlisted_work_ids"], ["P01-I99"])

    def test_transferred_sender_never_counts_as_done(self):
        self.rows[0] = "| REQ-001 | P01-01 | 01 | P01-I01, P02-I01 | transferred | moved |"
        self.write_plan()
        self.index["P01-I01"][1]["status"] = "transferred"
        self.index["P02-I01"] = (self.d / "work/phase-02.yaml", self.work("REQ-001", ["AC-001"]))
        self.index["P02-I01"][1]["status"] = "ready"
        self.assertEqual(self.row()["implementation"], "not_implemented")
        self.index["P02-I01"][1]["status"] = "done"
        self.index["P02-I01"][1]["evidence"] = self.index["P01-I01"][1]["evidence"]
        self.set_compare("P02-I01", "REQ-001", "aligned", "L2-L3")
        self.assertEqual(self.row()["implementation"], "implemented")

    def test_aligned_requires_attested_comparison(self):
        self.index["P01-I01"][1]["origin"].pop("original_comparison")
        self.assertEqual(self.row()["difference"], "unknown")

    def test_source_range_outside_original_mapping_is_not_aligned(self):
        self.set_compare("P01-I01", "REQ-001", "aligned", "L4-L5")
        snap = self.snap()
        self.assertEqual(snap["requirements"][0]["difference"], "unknown")
        self.assertTrue(any("outside" in x for x in snap["diagnostics"]["errors"]))

    def test_missing_captured_snapshot_is_not_aligned(self):
        import shutil
        shutil.rmtree(self.d / "sources")
        snap = self.snap()
        self.assertEqual(snap["requirements"][0]["difference"], "unknown")
        self.assertTrue(any("captured original" in x for x in snap["diagnostics"]["errors"]))

    def test_technical_deviation_is_not_policy_approval(self):
        args = SimpleNamespace(decision="DEC-T01", title="Internal table design",
                               requirement=["REQ-001"], text="Use denormalized table",
                               rationale="Faster read", by="developer", original_difference="technical")
        (self.d / "DECISIONS.md").write_text(
            policy.apply(self.d, "technical", args), encoding="utf-8"
        )
        self.index["P01-I01"][1]["origin"]["technical_decisions"] = ["DEC-T01"]
        self.set_compare("P01-I01", "REQ-001", "technical_deviation", "L2-L3")
        row = self.row()
        self.assertEqual(row["decision"], "developer_confirmed")
        self.assertEqual(row["difference"], "technical_deviation")

    def test_policy_provisional_can_coexist_with_verified_implementation(self):
        self.policy_event("assume")
        self.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        self.set_compare("P01-I02", "RULE-002", "policy_deviation", "L4-L5")
        row = self.row("RULE-002")
        self.assertEqual(row["implementation"], "implemented")
        self.assertEqual(row["difference"], "policy_deviation")
        self.assertEqual(row["decision"], "provisional")
        self.assertEqual(row["verification"], "passed")

    def test_policy_approved_does_not_erase_original_difference(self):
        self.policy_event("assume")
        self.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        self.policy_event("approve")
        self.set_compare("P01-I02", "RULE-002", "policy_deviation", "L4-L5")
        row = self.row("RULE-002")
        self.assertEqual((row["decision"], row["difference"]), ("approved", "policy_deviation"))

    def test_policy_rejected_stays_rejected_without_implicit_approval(self):
        self.policy_event("assume")
        self.index["P01-I02"][1]["origin"]["policy_assumptions"] = ["DEC-P01"]
        self.policy_event("reject", approved_policy="Use original calculation",
                          corrective_work=["P02-I01"], matches_assumption=False)
        self.assertEqual(self.row("RULE-002")["decision"], "rejected")

    def test_open_blocking_decision_is_pending(self):
        self.state["unresolved_decisions"] = ["DEC-BLOCK"]
        self.index["P01-I01"][1]["decision_dependencies"] = ["DEC-BLOCK"]
        self.assertEqual(self.row()["decision"], "pending")
        self.assertEqual(self.row()["blocking_decisions"], ["DEC-BLOCK"])

    def test_missing_commit_evidence_is_unknown_not_passed(self):
        self.index["P01-I01"][1]["evidence"].pop("commit")
        self.assertEqual(self.row()["verification"], "unknown")

    def test_dirty_worktree_is_stale_even_without_commit(self):
        (self.root / "service.py").write_text("def create(): return 3\n", encoding="utf-8")
        self.assertEqual(self.row()["verification"], "stale")

    def test_stale_aligned_attestation_is_unknown(self):
        (self.root / "service.py").write_text("def create(): return 3\n", encoding="utf-8")
        self.assertEqual(self.row()["difference"], "unknown")

    def test_missing_plan_remains_in_implementation_denominator(self):
        (self.d / "PLAN.md").unlink()
        result = self.snap()
        self.assertEqual(result["summary"]["in_scope"], 2)
        self.assertEqual(result["summary"]["implemented"], 0)
        self.assertEqual(result["gaps"]["prd_without_plan"], ["REQ-001", "RULE-002"])

    def test_duplicate_audit_verdict_cannot_pass(self):
        path = self.d / "audits/phase-01.md"
        data = path.read_text(encoding="utf-8")
        path.write_text(data.replace("verdict: pass", "verdict: fail\nverdict: pass"), encoding="utf-8")
        self.assertEqual(self.row()["verification"], "unknown")

    def test_nonreciprocal_plan_work_link_is_unknown(self):
        self.index["P01-I01"][1]["origin"]["requirements"] = ["RULE-002"]
        self.assertEqual(self.row()["implementation"], "unknown")

    def test_transferred_receiver_can_be_verified(self):
        self.rows[0] = "| REQ-001 | P01-01 | 01 | P01-I01, P02-I01 | transferred | moved |"
        self.write_plan()
        self.index["P01-I01"][1]["status"] = "transferred"
        self.index["P02-I01"] = (self.d / "work/phase-02.yaml", self.work("REQ-001", ["AC-001"]))
        self.index["P02-I01"][1]["evidence"] = self.index["P01-I01"][1]["evidence"]
        self.set_compare("P02-I01", "REQ-001", "aligned", "L2-L3")
        self.state["phases"]["02"] = {"status": "verified", "work_file": "work/phase-02.yaml"}
        (self.d / "audits/phase-02.md").write_text(
            (self.d / "audits/phase-01.md").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.d / "audits/work/P02-I01.md").write_text(
            (self.d / "audits/work/P01-I01.md").read_text(encoding="utf-8").replace(
                "task: P01-I01", "task: P02-I01"
            ), encoding="utf-8"
        )
        self.assertEqual(self.row()["verification"], "passed")

    def test_changed_source_since_commit_is_stale(self):
        (self.root / "service.py").write_text("def create(): return 2\n", encoding="utf-8")
        self.git("add", "service.py")
        self.git("commit", "-qm", "changed")
        self.assertEqual(self.row()["verification"], "stale")

    def test_unrelated_commit_does_not_invalidate_source_evidence(self):
        (self.root / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
        self.git("add", "unrelated.txt")
        self.git("commit", "-qm", "unrelated")
        self.assertEqual(self.row()["verification"], "passed")

    def test_failed_execution_evidence_is_failed(self):
        self.index["P01-I01"][1]["evidence"]["commands"] = [{"exit_code": 4}]
        self.assertEqual(self.row()["verification"], "failed")

    def test_pending_review_is_not_verified(self):
        self.index["P01-I01"][1]["review"]["status"] = "pending"
        self.assertEqual(self.row()["verification"], "pending_review")

    def test_missing_phase_audit_does_not_pass(self):
        (self.d / "audits/phase-01.md").unlink()
        self.assertEqual(self.row()["verification"], "unknown")

    def test_unproven_audit_verdict_does_not_pass(self):
        path = self.d / "audits/phase-01.md"
        path.write_text(path.read_text(encoding="utf-8").replace("verdict: pass", "verdict: conditional_pass"), encoding="utf-8")
        self.assertEqual(self.row()["verification"], "pending_review")

    def test_mismatched_work_audit_target_cannot_pass(self):
        path = self.d / "audits/work/P01-I01.md"
        path.write_text(path.read_text(encoding="utf-8").replace("task: P01-I01", "task: P02-I01"), encoding="utf-8")
        self.assertEqual(self.row()["verification"], "unknown")

    def test_legacy_heading_title_is_preserved(self):
        path = self.d / "PRD.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "### REQ-001 — Create employee", "### REQ-001 Create employee"
        ), encoding="utf-8")
        self.assertEqual(self.row()["title"], "Create employee")

    def test_missing_required_work_audit_does_not_pass(self):
        (self.d / "audits/work/P01-I01.md").unlink()
        self.assertEqual(self.row()["verification"], "unknown")

    def test_source_tamper_prevents_aligned(self):
        (self.d / "sources/v1/original.md").write_text("tampered", encoding="utf-8")
        self.assertEqual(self.row()["difference"], "unknown")
        self.assertTrue(any("integrity" in x for x in self.snap()["diagnostics"]["errors"]))

    def test_policy_deviation_requires_linked_policy_decision(self):
        self.set_compare("P01-I02", "RULE-002", "policy_deviation", "L4-L5")
        result = self.row("RULE-002")
        self.assertEqual(result["difference"], "unknown")
        self.assertTrue(any("linked policy" in x for x in self.snap()["diagnostics"]["errors"]))

    def test_unverified_phase_is_not_passed(self):
        self.state["phases"]["01"]["status"] = "audit"
        self.assertEqual(self.row()["verification"], "pending_review")

    def test_scope_excluded_does_not_add_to_implementation_denominator(self):
        self.rows[1] = "| RULE-002 | - | - | - | excluded | DEC-004 excluded |"
        self.index.pop("P01-I02")
        self.write_plan()
        result = self.snap()
        self.assertEqual(result["summary"]["in_scope"], 1)
        self.assertEqual(result["summary"]["implemented"], 1)
        self.assertEqual(self.row("RULE-002")["scope"], "excluded")

    def test_legacy_missing_source_and_plan_is_unknown(self):
        import shutil
        shutil.rmtree(self.d / "sources")
        (self.d / "PLAN.md").unlink()
        for _, item in self.index.values():
            item["origin"].pop("original_comparison", None)
        self.assertEqual(self.row()["implementation"], "unknown")
        self.assertEqual(self.row()["difference"], "unknown")

    def test_inspect_never_writes_state_or_work(self):
        path = self.d / "STATE.yaml"
        path.write_text("next_action: existing\n", encoding="utf-8")
        before = path.read_bytes()
        self.snap()
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
