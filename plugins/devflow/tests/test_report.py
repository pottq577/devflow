#!/usr/bin/env python3
"""Checks for deterministic, safe, read-only requirement status projections."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import devflow_report as report


def fixture() -> dict:
    rows = [
        {
            "id": "REQ-001", "title": "Employee creation", "scope": "implement",
            "implementation": "implemented", "difference": "aligned",
            "decision": "not_required", "verification": "passed", "work_ids": ["P01-I01"],
            "acceptance_ids": ["AC-001"], "unmapped_acceptance_ids": [],
            "source_refs": [{"source": "original:v1", "lines": "L1-L3", "disposition": "mapped"}],
            "policy_decisions": [], "technical_decisions": [], "blocking_decisions": [],
            "works": [{"id": "P01-I01", "status": "done"}],
        },
        {
            "id": "RULE-002", "title": "Schedule policy", "scope": "implement",
            "implementation": "implemented", "difference": "policy_deviation",
            "decision": "provisional", "verification": "passed", "work_ids": ["P01-I02"],
            "acceptance_ids": [], "unmapped_acceptance_ids": [],
            "source_refs": [], "policy_decisions": ["DEC-P01"],
            "technical_decisions": [], "blocking_decisions": [], "works": [],
        },
        {
            "id": "REQ-003", "title": "Attendance approval", "scope": "implement",
            "implementation": "partial", "difference": "unknown",
            "decision": "pending", "verification": "pending_review",
            "work_ids": ["P02-I01"], "acceptance_ids": ["AC-003"],
            "unmapped_acceptance_ids": ["AC-003"],
            "source_refs": [], "policy_decisions": ["DEC-P02"],
            "technical_decisions": [], "blocking_decisions": ["DEC-009"],
            "works": [],
        },
        {
            "id": "REQ-004", "title": "Decommissioned rule", "scope": "excluded",
            "implementation": "not_implemented", "difference": "unknown",
            "decision": "approved", "verification": "not_run", "work_ids": [],
            "acceptance_ids": [], "unmapped_acceptance_ids": [],
            "source_refs": [], "policy_decisions": ["DEC-P03"],
            "technical_decisions": [], "blocking_decisions": [], "works": [],
        },
    ]
    return {
        "schema_version": 1, "domain": "test-domain", "head_sha": "a" * 40,
        "source_revisions": {"revision": "v1"},
        "summary": {"total": 4, "in_scope": 3, "implemented": 2},
        "requirements": rows,
        "gaps": {
            "original_without_prd": ["REQ-099"], "prd_without_plan": ["REQ-003"],
            "work_without_prd": ["REQ-900"],
            "unmapped_acceptance": {"REQ-003": ["AC-003"]},
            "unlisted_work": {"REQ-003": ["P99-I01"]},
        },
        "diagnostics": {"errors": ["source mapping inconsistent"], "warnings": ["unknown WORK P99-I01"]},
    }


class RequirementReportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="devflow-report-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.snapshot = fixture()

    def test_one_canonical_line_per_requirement(self) -> None:
        value = report.render_markdown(self.snapshot)
        self.assertEqual(value.count("- [x] **REQ-001"), 1)
        self.assertEqual(value.count("- [x] **RULE-002"), 1)
        self.assertEqual(value.count("- [ ] **REQ-003"), 1)
        self.assertEqual(value.count("- [ ] **REQ-004"), 1)

    def test_provisional_does_not_erase_verified_implementation(self) -> None:
        markdown = report.render_markdown(self.snapshot)
        self.assertIn("- [x] **RULE-002", markdown)
        self.assertIn("- [ ] RULE-002: `provisional`; decisions: DEC-P01", markdown)
        self.assertIn("does **not** mean product-policy approval", markdown)

    def test_not_implemented_scope_exclusion_is_not_checked(self) -> None:
        value = report.render_markdown(self.snapshot)
        self.assertIn("- [ ] **REQ-004", value)
        self.assertIn("Explicitly excluded, deferred or cancelled", value)
        self.assertNotIn("- [x] **REQ-004", value)

    def test_done_work_without_verification_is_unchecked(self) -> None:
        row = self.snapshot["requirements"][0]
        row["verification"] = "stale"
        self.assertIn("- [ ] **REQ-001", report.render_markdown(self.snapshot))

    def test_unverified_original_is_not_marked_aligned(self) -> None:
        self.snapshot["requirements"][0]["difference"] = "unknown"
        result = report.render_markdown(self.snapshot)
        self.assertIn("original: `unknown`", result)
        self.assertNotIn("original: `aligned`", result.split("**REQ-001")[1].split("\n")[0])

    def test_four_axes_are_independent(self) -> None:
        markdown = report.render_markdown(self.snapshot)
        for axis in report.AXES:
            self.assertIn("| " + axis + " |", markdown)
        self.assertIn("| implementation | implemented | 2 |", markdown)
        self.assertIn("| decision | provisional | 1 |", markdown)

    def test_work_acceptance_and_original_location_are_visible(self) -> None:
        markdown = report.render_markdown(self.snapshot)
        self.assertIn("WORK: P01-I01; acceptance: AC-001", markdown)
        self.assertIn("original:v1 L1-L3 (mapped)", markdown)

    def test_unmapped_acceptance_is_explicit(self) -> None:
        markdown = report.render_markdown(self.snapshot)
        self.assertIn("Missing acceptance links: AC-003", markdown)
        self.assertIn("REQ-003: AC-003", markdown)

    def test_gap_sections_come_from_snapshot(self) -> None:
        value = report.render_markdown(self.snapshot)
        for name in ("Original requirements missing from PRD", "PRD requirements missing from PLAN",
                     "WORK requirements missing from PRD", "Unmapped acceptance criteria",
                     "WORK not listed by PLAN"):
            self.assertIn(name, value)
        self.assertIn("- [ ] REQ-099", value)
        self.assertIn("- [ ] REQ-003: P99-I01", value)

    def test_diagnostics_keep_errors_and_warnings(self) -> None:
        value = report.render_markdown(self.snapshot)
        self.assertIn("**1 errors**, **1 warnings**", value)
        self.assertIn("source mapping inconsistent", value)
        self.assertIn("unknown WORK P99-I01", value)

    def test_empty_requirements_do_not_mean_finished(self) -> None:
        self.snapshot["requirements"] = []
        self.snapshot["gaps"] = {}
        markdown = report.render_markdown(self.snapshot)
        self.assertIn("No requirement IDs were detected", markdown)
        self.assertIn("Verified implementations: **0/0**", markdown)
        self.assertNotIn("- [x]", markdown)

    def test_escapes_markdown_and_html_from_prd(self) -> None:
        self.snapshot["requirements"][0]["title"] = "<script>\n- [x] Faked | [link](site) `value`"
        value = report.render_markdown(self.snapshot)
        self.assertNotIn("<script>", value)
        self.assertNotIn("\n- [x] Faked", value)
        self.assertIn("&lt;script&gt;", value)
        self.assertIn(r"\|", value)
        self.assertIn(r"\`value\`", value)

    def test_markdown_is_deterministic_and_does_not_mutate(self) -> None:
        before = copy.deepcopy(self.snapshot)
        self.assertEqual(report.render_markdown(self.snapshot), report.render_markdown(self.snapshot))
        self.assertEqual(before, self.snapshot)

    def test_json_is_exact_p04_snapshot_and_utf8(self) -> None:
        self.snapshot["requirements"][0]["title"] = "사원 등록"
        value = report.render_json(self.snapshot)
        self.assertEqual(json.loads(value), self.snapshot)
        self.assertIn("사원 등록", value)
        self.assertEqual(value, report.render_json(self.snapshot))

    def test_reject_invalid_snapshot_shape(self) -> None:
        for update in ({"schema_version": 99}, {"requirements": None},
                       {"diagnostics": "error"}, {"gaps": []}):
            with self.subTest(update=update):
                changed = {**self.snapshot, **update}
                with self.assertRaises(ValueError):
                    report.render_markdown(changed)

    def test_reject_malformed_requirement_row(self) -> None:
        self.snapshot["requirements"][0]["verification"] = []
        with self.assertRaisesRegex(ValueError, "invalid requirement row"):
            report.render_json(self.snapshot)

    def test_write_generates_two_correct_files(self) -> None:
        a, b = report.write_pair(self.directory, self.snapshot)
        self.assertEqual((a.name, b.name), (report.MARKDOWN_NAME, report.JSON_NAME))
        self.assertEqual(a.read_text(encoding="utf-8"), report.render_markdown(self.snapshot))
        self.assertEqual(json.loads(b.read_text(encoding="utf-8")), self.snapshot)
        self.assertEqual([p for p in self.directory.iterdir() if p.name.startswith(".requirements-")], [])

    def test_identical_repeat_does_not_rewrite(self) -> None:
        a, b = report.write_pair(self.directory, self.snapshot)
        before = (a.stat().st_mtime_ns, b.stat().st_mtime_ns)
        report.write_pair(self.directory, self.snapshot)
        self.assertEqual(before, (a.stat().st_mtime_ns, b.stat().st_mtime_ns))

    def test_write_updates_both_reports(self) -> None:
        a, b = report.write_pair(self.directory, self.snapshot)
        self.snapshot["requirements"][0]["verification"] = "stale"
        report.write_pair(self.directory, self.snapshot)
        self.assertIn("verification: `stale`", a.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(b.read_text(encoding="utf-8")), self.snapshot)

    def test_symlink_output_is_refused_before_any_write(self) -> None:
        external = self.directory / "secret.txt"
        external.write_text("keep me")
        (self.directory / report.JSON_NAME).symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            report.write_pair(self.directory, self.snapshot)
        self.assertFalse((self.directory / report.MARKDOWN_NAME).exists())
        self.assertEqual(external.read_text(), "keep me")

    def test_directory_output_is_refused(self) -> None:
        (self.directory / report.JSON_NAME).mkdir()
        with self.assertRaisesRegex(ValueError, "directory"):
            report.write_pair(self.directory, self.snapshot)

    def test_domain_symlink_is_refused(self) -> None:
        linked = self.directory.parent / (self.directory.name + "-link")
        linked.symlink_to(self.directory, target_is_directory=True)
        self.addCleanup(linked.unlink)
        with self.assertRaisesRegex(ValueError, "real directory"):
            report.write_pair(linked, self.snapshot)

    def test_failed_second_replace_rolls_back_first(self) -> None:
        first, second = report.write_pair(self.directory, self.snapshot)
        originals = (first.read_bytes(), second.read_bytes())
        self.snapshot["requirements"][0]["verification"] = "stale"
        replace = os.replace
        count = 0

        def failing_replace(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected failure")
            return replace(src, dst)

        with mock.patch.object(report.os, "replace", side_effect=failing_replace):
            with self.assertRaisesRegex(OSError, "injected failure"):
                report.write_pair(self.directory, self.snapshot)
        self.assertEqual((first.read_bytes(), second.read_bytes()), originals)
        self.assertFalse(any(p.name.startswith(".requirements-status-") for p in self.directory.iterdir()))

    def test_failed_second_replace_deletes_new_first_output(self) -> None:
        replace = os.replace
        count = 0

        def failing_replace(src, dst):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected failure")
            return replace(src, dst)

        with mock.patch.object(report.os, "replace", side_effect=failing_replace):
            with self.assertRaises(OSError):
                report.write_pair(self.directory, self.snapshot)
        self.assertFalse((self.directory / report.MARKDOWN_NAME).exists())
        self.assertFalse((self.directory / report.JSON_NAME).exists())

    def test_snapshot_printing_does_not_create_files(self) -> None:
        report.render_markdown(self.snapshot)
        report.render_json(self.snapshot)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
