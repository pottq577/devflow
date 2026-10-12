#!/usr/bin/env python3
"""Fail-closed merge and release verification without real network dependencies."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import release_gate as gate


class ReleaseGateTests(unittest.TestCase):
    class Case:
        def __init__(self, name: str):
            self.name = name

        def id(self) -> str:
            return self.name

    def ids(self) -> list[str]:
        modules = sorted(gate.REQUIRED_MODULES - {
            "test_lifecycle_cases", "test_newman_integration"
        })
        return (
            [f"test_lifecycle_cases.LifecycleCases.test_case_{i:03d}" for i in range(171)]
            + [f"{module}.SampleTests.test_contract" for module in modules]
            + [
                f"test_newman_integration.RealNewmanTests.test_real_{i}"
                for i in range(3)
            ]
        )

    def make_report(self, *, skipped: list[str] | None = None) -> tuple[dict, list[str]]:
        names = self.ids()
        skipped = skipped or []
        rows = [
            {"id": name, "status": "skipped" if name in skipped else "passed", "seconds": 0.01}
            for name in names
        ]
        return ({
            "schema_version": 1,
            "profile": "full",
            "complete": True,
            "discovered": len(names), "selected": len(names), "run": len(names),
            "executed": len(names) - len(skipped), "passed": len(names) - len(skipped),
            "failures": 0, "errors": 0, "skipped": len(skipped),
            "unexpected_successes": 0, "seconds": 1.0, "tests": rows,
        }, names)

    def assess(self, report, names=None, mode="merge"):
        if names is None:
            names = self.ids()
        return gate.assess_suite(report, names, mode=mode)

    def test_complete_report_satisfies_merge_and_release(self):
        report, names = self.make_report()
        for mode in ("merge", "release"):
            blocked, warnings, coverage = self.assess(report, names, mode)
            self.assertEqual(blocked, [])
            self.assertEqual(warnings, [])
            self.assertEqual(coverage["newman"], "executed")

    def test_absent_real_newman_is_warning_for_merge_and_blocker_for_release(self):
        skips = [name for name in self.ids() if ".RealNewmanTests." in name]
        report, names = self.make_report(skipped=skips)
        blockers, warnings, summary = self.assess(report, names)
        self.assertEqual(blockers, [])
        self.assertEqual(warnings, ["real_newman_smoke_not_fully_executed"])
        self.assertEqual(summary["skipped"], 3)
        blockers, warnings, _ = self.assess(report, names, "release")
        self.assertIn("release_requires_real_newman_smoke", blockers)
        self.assertEqual(warnings, [])

    def test_skipped_non_newman_regression_is_blocker(self):
        first = self.ids()[0]
        report, names = self.make_report(skipped=[first])
        blockers, _, _ = self.assess(report, names)
        self.assertIn("unexpected_skipped_tests", blockers)

    def test_rejects_partial_or_filtered_suite_even_when_all_pass(self):
        report, names = self.make_report()
        for key, value in (("profile", "focused"), ("complete", False)):
            attempt = dict(report, **{key: value})
            self.assertIn("suite_not_full_unfiltered", self.assess(attempt, names)[0])

    def test_missing_or_extra_test_and_duplicate_are_blockers(self):
        report, names = self.make_report()
        missing = copy.deepcopy(report)
        missing["tests"].pop()
        self.assertIn("suite_discovery_mismatch", self.assess(missing, names)[0])
        duplicate = copy.deepcopy(report)
        duplicate["tests"][1]["id"] = duplicate["tests"][0]["id"]
        blockers, _, _ = self.assess(duplicate, names)
        self.assertIn("suite_test_ids_duplicated", blockers)
        self.assertIn("suite_discovery_mismatch", blockers)

    def test_summary_counts_cannot_hide_failure_or_skip(self):
        report, names = self.make_report()
        report["executed"] -= 1
        self.assertIn("suite_summary_counts_inconsistent", self.assess(report, names)[0])
        report["executed"] += 1
        report["tests"][0]["status"] = "failed"
        report["failures"] = 1
        report["passed"] -= 1
        self.assertIn("suite_tests_not_all_passing", self.assess(report, names)[0])

    def test_unexpected_success_and_expected_failure_block_release(self):
        for status in ("unexpected_success", "expected_failure", "error"):
            report, names = self.make_report()
            report["tests"][0]["status"] = status
            report["passed"] -= 1
            if status == "error":
                report["errors"] = 1
            if status == "unexpected_success":
                report["unexpected_successes"] = 1
            self.assertIn("suite_tests_not_all_passing", self.assess(report, names)[0])

    def test_required_regression_module_and_legacy_floor(self):
        report, names = self.make_report()
        shortened = [n for n in names if not n.startswith("test_hosted_guard.")]
        self.assertIn(
            "required_regression_modules_missing:test_hosted_guard",
            self.assess(report, shortened)[0],
        )
        less_legacy = names[1:]
        self.assertIn("legacy_lifecycle_coverage_shrunk", self.assess(report, less_legacy)[0])

    def test_invalid_report_fails_closed(self):
        for report in (None, {}, {"tests": []}, {"tests": [{"id": None}]}):
            self.assertTrue(self.assess(report)[0])
        report, names = self.make_report()
        report["tests"][0]["seconds"] = -1
        self.assertIn("suite_report_test_rows_invalid", self.assess(report, names)[0])

    def test_validate_report_uses_discovered_case_ids(self):
        report, names = self.make_report()
        result = gate.validate_report(
            report, mode="release", cases=[self.Case(name) for name in names]
        )
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["blockers"], [])

    def test_source_snapshot_detects_mutation_ignores_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "scripts" / "devflow.py"
            script.parent.mkdir()
            script.write_text("answer = 1\n")
            before = gate.source_snapshot(root)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "temp.json").write_text("{}")
            self.assertEqual(before, gate.source_snapshot(root))
            script.write_text("answer = 2\n")
            self.assertNotEqual(before, gate.source_snapshot(root))

    def test_symlinked_source_is_not_release_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real.py").write_text("pass\n")
            (root / "alias.py").symlink_to(root / "real.py")
            with self.assertRaisesRegex(ValueError, "symlink"):
                gate.source_snapshot(root)

    def test_declared_python_3_10_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "good.py").write_text("from __future__ import annotations\nx: int | None = None\n")
            self.assertEqual(gate.compatibility_checks(root), [])
            (root / "bad.py").write_text("def broken(:\n")
            self.assertTrue(any("bad.py" in x for x in gate.compatibility_checks(root)))

    def run_fake_gate(
        self, mode="merge", *, changes=False, rc=0, leave_report=True,
        clean=True, dirtied=False, head_changed=False,
    ):
        report, names = self.make_report()
        cases = [self.Case(name) for name in names]
        snapshots = [
            {"sha256": "a" * 64, "files": 40},
            {"sha256": ("b" if changes else "a") * 64, "files": 40},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            suite = Path(temporary) / "suite.json"
            def execute(argv, **kwargs):
                if leave_report:
                    gate.run_suite.write_report(Path(argv[-1]), report)
                return mock.Mock(returncode=rc)
            with (
                mock.patch.object(gate, "source_snapshot", side_effect=snapshots),
                mock.patch.object(gate, "compatibility_checks", return_value=[]),
                mock.patch.object(gate, "provenance", side_effect=[
                    {"head": "c" * 40, "plugin_clean": clean, "git_available": True},
                    {"head": ("d" if head_changed else "c") * 40,
                     "plugin_clean": clean and not dirtied, "git_available": True},
                ]),
                mock.patch.object(gate.run_suite, "collect_cases", return_value=cases),
                mock.patch.object(gate.subprocess, "run", side_effect=execute),
            ):
                result = gate._evaluate_fresh(mode, suite)
            return result

    def test_fresh_complete_merge_gate_passes_with_report_digest(self):
        result = self.run_fake_gate()
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["blockers"], [])
        self.assertEqual(len(result["evidence"]["suite_sha256"]), 64)
        self.assertEqual(result["coverage"]["run"], len(self.ids()))

    def test_source_modified_during_run_blocks(self):
        result = self.run_fake_gate(changes=True)
        self.assertEqual(result["verdict"], "blocked")
        self.assertIn("plugin_source_changed_during_suite", result["blockers"])

    def test_nonzero_suite_exit_blocks_even_with_passing_json(self):
        result = self.run_fake_gate(rc=1)
        self.assertIn("full_suite_exited_nonzero", result["blockers"])

    def test_missing_suite_report_blocks_even_on_zero_exit(self):
        result = self.run_fake_gate(leave_report=False)
        self.assertIn("suite_report_missing", result["blockers"])

    def test_clean_plugin_is_required_only_for_release(self):
        self.assertEqual(self.run_fake_gate(mode="merge", clean=False)["verdict"], "pass")
        result = self.run_fake_gate(mode="release", clean=False)
        self.assertIn("release_requires_clean_plugin_tree", result["blockers"])

    def test_head_changed_during_suite_blocks_release(self):
        result = self.run_fake_gate(head_changed=True)
        self.assertIn("git_head_changed_during_suite", result["blockers"])
        self.assertNotEqual(
            result["evidence"]["head_before"], result["evidence"]["head"]
        )

    def test_release_rejects_plugin_dirtied_during_suite(self):
        result = self.run_fake_gate(mode="release", dirtied=True)
        self.assertIn("release_requires_clean_plugin_tree", result["blockers"])

    def test_cli_reports_failure_when_report_cannot_be_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "verdict.json"
            fake = {
                "schema_version": 1, "mode": "merge", "verdict": "blocked",
                "blockers": ["suite_report_missing"], "warnings": [], "coverage": {},
                "evidence": {"suite_sha256": None},
            }
            with mock.patch.object(gate, "_evaluate_fresh", return_value=fake):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = gate.main(["--report", str(path)])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(path.read_text())["verdict"], "blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
