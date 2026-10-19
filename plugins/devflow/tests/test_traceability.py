#!/usr/bin/env python3
"""P02 coverage for captured source and PRD/PLAN/WORK traceability."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import devflow_sources as sources
import devflow_traceability as traceability


class TraceabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="devflow-trace-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.domain = self.root / "docs/domains/sample"
        self.domain.mkdir(parents=True)
        self.original = self.root / "original.md"
        self.context = self.root / "context.md"
        self.original.write_text(
            "# Original\n### REQ-001 Add employee\nAdd employee by API\n"
            "### RULE-002 Access\nCheck ownership\n", encoding="utf-8"
        )
        self.context.write_text(
            "# Review\nInterpret API behavior\nDiscuss access policy\n", encoding="utf-8"
        )
        sources.capture(self.root, self.domain, "sample", self.original, self.context)
        self.source_rows = [
            "| original:v1 | L1-L1 | background | - | Overview |",
            "| original:v1 | L2-L3 | mapped | REQ-001 | Requirement |",
            "| original:v1 | L4-L5 | mapped | RULE-002 | Original rule |",
            "| context:v1 | L1-L1 | background | - | Context heading |",
            "| context:v1 | L2-L3 | reference | REQ-001, RULE-002 | Analysis only |",
        ]
        self.plan_rows = [
            "| REQ-001 | P01-01 | 01 | P01-I01 | implement | Implement API |",
            "| RULE-002 | P01-02 | 01 | P01-I02 | implement | Enforce ownership |",
        ]
        self.index = {
            "P01-I01": (Path("work/phase-01.yaml"), {
                "status": "done", "origin": {
                    "requirements": ["REQ-001"], "acceptance_criteria": ["AC-001"]
                }
            }),
            "P01-I02": (Path("work/phase-01.yaml"), {
                "status": "ready", "origin": {"requirements": ["RULE-002"], "acceptance_criteria": []}
            }),
        }
        self.write_artifacts()

    def write_artifacts(self) -> None:
        self.domain.joinpath("PRD.md").write_text(
            "# Domain PRD\n\n## 4. Requirements\n\n"
            "### REQ-001 Add employee\n- Acceptance criteria:\n  - AC-001: Employee can be added\n\n"
            "## 5. Business Rules\n\n### RULE-002 Access\n\n"
            "## 10. Open Decisions\n\n## 11. Source traceability\n\n"
            "| Source | Lines | Disposition | Requirements | Reason |\n"
            "| --- | --- | --- | --- | --- |\n" + "\n".join(self.source_rows) + "\n",
            encoding="utf-8",
        )
        self.domain.joinpath("PLAN.md").write_text(
            "# Implementation plan\n\n## Requirement traceability\n\n"
            "| Requirement | Plan item | Phase | Work items | Disposition | Reason |\n"
            "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(self.plan_rows) + "\n",
            encoding="utf-8",
        )
        self.domain.joinpath("DECISIONS.md").write_text(
            "# Decisions\n\n## Open\n\n## Resolved\n", encoding="utf-8"
        )

    def inspect(self, require_plan: bool = True) -> tuple[list[str], list[str]]:
        return traceability.validate_domain(self.domain, self.index, require_plan=require_plan)

    def test_complete_bidirectional_mapping(self) -> None:
        self.assertEqual(self.inspect(), ([], []))

    def test_source_ranges_are_covered_and_nonoverlapping(self) -> None:
        self.source_rows.pop(1)
        self.source_rows.append("| original:v1 | L4-L5 | mapped | RULE-002 | Duplicate |")
        self.write_artifacts()
        errors, _ = self.inspect()
        self.assertTrue(any("uncovered original:v1 lines: L2-L3" in s for s in errors), errors)
        self.assertTrue(any("overlapping original:v1" in s for s in errors), errors)

    def test_unknown_source_id_and_invalid_range(self) -> None:
        self.source_rows[1] = "| original:v1 | L2-L7 | mapped | REQ-999 | Invalid |"
        self.write_artifacts()
        errors, _ = self.inspect()
        self.assertTrue(any("out-of-bounds" in s for s in errors), errors)
        self.assertTrue(any("no original or approved source mapping" in s for s in errors), errors)

    def test_requirements_missing_or_duplicated_in_plan(self) -> None:
        self.plan_rows.pop(1)
        self.plan_rows.append(self.plan_rows[0])
        self.write_artifacts()
        errors, _ = self.inspect()
        self.assertTrue(any("duplicate requirement REQ-001" in s for s in errors), errors)
        self.assertTrue(any("missing requirement RULE-002" in s for s in errors), errors)

    def test_unknown_work_and_missing_reciprocal_origin(self) -> None:
        self.plan_rows[0] = "| REQ-001 | P01-01 | 01 | P01-I99 | implement | Unknown |"
        self.index["P01-I02"][1]["origin"]["requirements"] = ["REQ-001"]
        self.write_artifacts()
        errors, _ = self.inspect()
        self.assertTrue(any("unknown WORK P01-I99" in s for s in errors), errors)
        self.assertTrue(any("unlisted WORK origin for REQ-001" in s for s in errors), errors)
        self.assertTrue(any("does not link RULE-002" in s for s in errors), errors)

    def test_acceptance_criteria_reverse_coverage(self) -> None:
        self.index["P01-I01"][1]["origin"]["acceptance_criteria"] = []
        errors, _ = self.inspect()
        self.assertTrue(any("missing WORK mapping for AC-001" in s for s in errors), errors)

    def test_acceptance_criteria_cannot_map_to_another_parent(self) -> None:
        self.index["P01-I02"][1]["origin"]["acceptance_criteria"] = ["AC-001"]
        errors, _ = self.inspect()
        self.assertTrue(any("lacks parent requirement REQ-001" in s for s in errors), errors)

    def test_transfer_requires_sender_and_receiver(self) -> None:
        self.index["P01-I01"][1]["status"] = "transferred"
        self.index["P01-I01"][1]["transfer"] = {"to": "P02-I01", "requirements": ["REQ-001"]}
        self.index["P02-I01"] = (Path("work/phase-02.yaml"), {
            "status": "ready", "origin": {
                "requirements": ["REQ-001"], "acceptance_criteria": ["AC-001"]
            }
        })
        self.plan_rows[0] = (
            "| REQ-001 | P01-01 | 01 | P01-I01, P02-I01 | transferred | Moved to phase 02 |"
        )
        self.write_artifacts()
        self.assertEqual(self.inspect(), ([], []))
        self.plan_rows[0] = "| REQ-001 | P01-01 | 01 | P01-I01 | transferred | Missing target |"
        self.write_artifacts()
        errors, _ = self.inspect()
        self.assertTrue(any("transfer sender/receiver not linked" in s for s in errors), errors)

    def test_exclusion_requires_resolved_decision(self) -> None:
        self.plan_rows[1] = "| RULE-002 | - | - | - | excluded | DEC-004 scope exclusion |"
        self.index.pop("P01-I02")
        self.write_artifacts()
        errors, _ = self.inspect()
        self.assertTrue(any("needs resolved DEC" in s for s in errors), errors)
        self.domain.joinpath("DECISIONS.md").write_text(
            "# Decisions\n\n## Resolved\n\n### DEC-004 Scope exclusion\n"
            "- Decision: Rule is outside this release\n- Rationale: Product owner approved\n",
            encoding="utf-8",
        )
        self.assertEqual(self.inspect(), ([], []))

    def test_source_approved_by_context_only_requires_decision(self) -> None:
        self.source_rows[2] = "| original:v1 | L4-L5 | background | - | Background only |"
        self.source_rows[4] = "| context:v1 | L2-L3 | mapped | RULE-002 | DEC-005 adds rule |"
        self.source_rows.append("| context:v1 | L2-L3 | reference | REQ-001 | Overlap invalid |")
        self.write_artifacts()
        errors, _ = self.inspect(require_plan=False)
        self.assertTrue(any("context-only mapped requirements need resolved DEC" in s for s in errors), errors)
        self.source_rows.pop()
        self.write_artifacts()
        self.domain.joinpath("DECISIONS.md").write_text(
            "# Decisions\n\n## Resolved\n\n### DEC-005 Add rule\n- Decision: Approved\n",
            encoding="utf-8",
        )
        self.assertEqual(self.inspect(), ([], []))

    def test_bootstrap_checks_decision_reference_before_resolution(self) -> None:
        self.source_rows[2] = "| original:v1 | L4-L5 | background | - | Background only |"
        self.source_rows[4] = "| context:v1 | L2-L3 | mapped | RULE-002 | DEC-005 pending |"
        self.write_artifacts()
        self.assertEqual(
            traceability.validate_domain(
                self.domain, {}, require_plan=False, require_decisions=False
            ), ([], []),
        )
        errors, _ = self.inspect(require_plan=False)
        self.assertTrue(any("context-only mapped requirements need resolved DEC" in s for s in errors), errors)

    def test_original_id_is_not_silently_discarded(self) -> None:
        other = self.original.read_text(encoding="utf-8") + "### REQ-006 Hidden feature\n"
        self.original.write_text(other, encoding="utf-8")
        # Recreate the initial capture rather than mutating evidence in place.
        import shutil
        shutil.rmtree(self.domain / "sources")
        sources.capture(self.root, self.domain, "sample", self.original, self.context)
        self.source_rows.append("| original:v1 | L6-L6 | background | - | Hidden feature |")
        self.write_artifacts()
        errors, _ = self.inspect(require_plan=False)
        self.assertTrue(any("original requirement REQ-006 absent" in s for s in errors), errors)

    def test_legacy_domain_without_capture_is_unchanged(self) -> None:
        import shutil
        shutil.rmtree(self.domain / "sources")
        prd = self.domain / "PRD.md"
        prd.write_text(prd.read_text(encoding="utf-8").split("## 11. Source traceability")[0])
        self.assertEqual(self.inspect(), ([], []))

    def test_missing_source_snapshot_does_not_bypass_declared_mapping(self) -> None:
        import shutil
        shutil.rmtree(self.domain / "sources")
        errors, _ = self.inspect()
        self.assertTrue(any("no captured sources" in s for s in errors), errors)

    def test_invalid_work_origin_fields_report_errors_instead_of_crashing(self) -> None:
        self.index["P01-I01"][1]["origin"]["acceptance_criteria"] = [{"bad": 1}]
        errors, _ = self.inspect()
        self.assertTrue(any("must use string lists" in s for s in errors), errors)

    def test_legacy_capture_without_table_warns_before_migration(self) -> None:
        prd = self.domain / "PRD.md"
        text = prd.read_text(encoding="utf-8")
        prd.write_text(text.split("## 11. Source traceability")[0], encoding="utf-8")
        errors, warnings = self.inspect(require_plan=False)
        self.assertEqual(errors, [])
        self.assertTrue(any("no source mapping" in s for s in warnings), warnings)

    def test_strict_capture_requires_source_table(self) -> None:
        prd = self.domain / "PRD.md"
        text = prd.read_text(encoding="utf-8")
        prd.write_text(text.split("## 11. Source traceability")[0], encoding="utf-8")
        errors, _ = traceability.validate_domain(
            self.domain, self.index, require_plan=False, strict=True
        )
        self.assertTrue(any("table heading" in s for s in errors), errors)

    def test_strict_domain_cannot_remove_sources_and_mapping(self) -> None:
        import shutil
        shutil.rmtree(self.domain / "sources")
        prd = self.domain / "PRD.md"
        prd.write_text(prd.read_text(encoding="utf-8").split("## 11. Source traceability")[0])
        errors, _ = traceability.validate_domain(
            self.domain, self.index, require_plan=False, strict=True
        )
        self.assertTrue(any("required captured sources" in s for s in errors), errors)

    def test_plan_columns_missing_fail_with_a_traced_work(self) -> None:
        plan = self.domain / "PLAN.md"
        text = plan.read_text(encoding="utf-8")
        plan.write_text(text.replace(
            "| Requirement | Plan item | Phase | Work items | Disposition | Reason |",
            "| Requirement | Plan item | Phase | Notes |",
        ), encoding="utf-8")
        errors, _ = self.inspect()
        self.assertTrue(any("expected table columns" in s for s in errors), errors)

    def test_split_one_source_span_into_multiple_requirements(self) -> None:
        self.source_rows[1] = (
            "| original:v1 | L2-L3 | mapped | REQ-001, RULE-002 | Shared behavior |"
        )
        self.write_artifacts()
        self.assertEqual(self.inspect(), ([], []))

    def test_duplicate_prd_acceptance_is_rejected(self) -> None:
        prd = self.domain / "PRD.md"
        text = prd.read_text(encoding="utf-8")
        prd.write_text(text.replace(
            "### RULE-002 Access",
            "### RULE-002 Access\n- AC-001: Duplicate global acceptance",
        ), encoding="utf-8")
        errors, _ = self.inspect(require_plan=False)
        self.assertTrue(any("duplicate acceptance AC-001" in s for s in errors), errors)

    def test_new_domain_without_work_can_validate_prd_before_plan(self) -> None:
        self.domain.joinpath("PLAN.md").unlink()
        self.assertEqual(self.inspect(require_plan=False), ([], []))

    def test_duplicate_prd_requirement_is_rejected(self) -> None:
        prd = self.domain / "PRD.md"
        text = prd.read_text(encoding="utf-8")
        text = text.replace("## 5. Business Rules", "### REQ-001 Duplicate\n\n## 5. Business Rules")
        prd.write_text(text, encoding="utf-8")
        errors, _ = self.inspect(require_plan=False)
        self.assertTrue(any("duplicate requirement REQ-001" in s for s in errors), errors)

    def test_invalid_source_snapshot_prevents_false_coverage(self) -> None:
        (self.domain / "sources/v1/original.md").write_bytes(b"tampered")
        errors, _ = self.inspect()
        self.assertTrue(any("invalid source snapshot" in s for s in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
