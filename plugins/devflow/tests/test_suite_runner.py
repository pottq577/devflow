#!/usr/bin/env python3
"""Regression selection, result reporting, and duplicate-discovery contracts."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_suite



class SuiteRunnerTests(unittest.TestCase):
    class Probe(unittest.TestCase):
        """Fixture test case, nested so discovery cannot collect it."""

        def __init__(self, name: str, outcome: str = "passed"):
            super().__init__("runTest")
            self.name = name
            self.outcome = outcome

        def id(self) -> str:
            return self.name

        def runTest(self):
            if self.outcome == "failed":
                self.fail("intentional fixture failure")
            if self.outcome == "skipped":
                self.skipTest("optional dependency unavailable")
            if self.outcome == "subfailure":
                with self.subTest(case="fixture"):
                    self.fail("intentional fixture subtest failure")

    def fixtures(self):
        return [
            self.Probe("test_host_autopilot.HostAutopilotCliTests.test_guard"),
            self.Probe("test_lifecycle_cases.LifecycleCases.test_case_one"),
            self.Probe("test_newman_integration.RealNewmanTests.test_real_http"),
            self.Probe("test_suite_runner.SuiteRunnerTests.test_profiles_partition"),
        ]

    def test_profiles_partition_full_suite_without_overlap(self):
        cases = self.fixtures()
        full = run_suite.select_cases(cases, "full")
        focused = run_suite.select_cases(cases, "focused")
        legacy = run_suite.select_cases(cases, "legacy")
        newman = run_suite.select_cases(cases, "newman")
        self.assertEqual(len(full), 4)
        self.assertEqual(len(focused), 2)
        self.assertEqual(len(legacy), 1)
        self.assertEqual(len(newman), 1)
        self.assertEqual(
            {case.id() for case in full},
            {case.id() for case in focused + legacy + newman},
        )

    def test_collect_rejects_duplicates_and_empty_discovery(self):
        cases = [self.Probe("identical"), self.Probe("identical")]
        with mock.patch.object(
            unittest.TestLoader, "discover",
            return_value=unittest.TestSuite([unittest.TestSuite(cases)]),
        ):
            with self.assertRaisesRegex(ValueError, "duplicate.*identical"):
                run_suite.collect_cases()
        with mock.patch.object(
            unittest.TestLoader, "discover", return_value=unittest.TestSuite()
        ):
            with self.assertRaisesRegex(ValueError, "no DevFlow regression tests"):
                run_suite.collect_cases()

    def test_collect_sorts_ids_deterministically(self):
        cases = [self.Probe("test_z.Last.test_z"), self.Probe("test_a.First.test_a")]
        with mock.patch.object(
            unittest.TestLoader, "discover", return_value=unittest.TestSuite(cases)
        ):
            self.assertEqual(
                [case.id() for case in run_suite.collect_cases()],
                ["test_a.First.test_a", "test_z.Last.test_z"],
            )

    def test_selection_filters_and_missing_targets_are_fail_closed(self):
        cases = self.fixtures()
        self.assertEqual(
            [case.id() for case in run_suite.select_cases(cases, "full", ["HostAutopilot"])],
            ["test_host_autopilot.HostAutopilotCliTests.test_guard"],
        )
        with self.assertRaisesRegex(ValueError, "no DevFlow tests match"):
            run_suite.select_cases(cases, "legacy", ["nonexistent"])
        with self.assertRaisesRegex(ValueError, "unsupported DevFlow test profile"):
            run_suite.select_cases(cases, "not-a-profile")

    def test_list_only_never_runs_tests(self):
        case = self.Probe("test_lifecycle_cases.LifecycleCases.test_one", "failed")
        with mock.patch.object(run_suite, "collect_cases", return_value=[case]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = run_suite.main(["--profile", "legacy", "--list"])
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue().strip(), case.id())
        self.assertIn("PARTIAL", stderr.getvalue())

    def test_empty_filtered_selection_exits_nonzero(self):
        with mock.patch.object(run_suite, "collect_cases", return_value=self.fixtures()):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_suite.main(["--match", "nothing-matches"]), 2)
                self.assertEqual(run_suite.main(["--match", ""]), 2)

    def test_json_report_marks_filtered_execution_partial(self):
        case = self.Probe("test_host_autopilot.HostAutopilotCliTests.test_guard")
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "reports" / "suite.json"
            with mock.patch.object(run_suite, "collect_cases", return_value=self.fixtures()[:3]):
                with contextlib.redirect_stderr(io.StringIO()):
                    code = run_suite.main(
                        ["--profile", "focused", "--match", "HostAutopilot", "--report", str(report_path)]
                    )
            self.assertEqual(code, 0)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["complete"])
            self.assertEqual(report["selected"], 1)
            self.assertEqual(report["discovered"], 3)
            self.assertEqual(report["passed"], 1)
            self.assertEqual(report["run"], 1)
            self.assertEqual(report["tests"][0]["id"], case.id())
            self.assertEqual(report["tests"][0]["status"], "passed")
            self.assertFalse(list(report_path.parent.glob(".devflow-test-*.tmp")))

    def test_wholly_skipped_newman_profile_cannot_report_success(self):
        case = self.Probe(
            "test_newman_integration.RealNewmanTests.test_real_http", "skipped"
        )
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "suite.json"
            with mock.patch.object(run_suite, "collect_cases", return_value=[case]):
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    code = run_suite.main(
                        ["--profile", "newman", "--report", str(report_path)]
                    )
            self.assertEqual(code, 2)
            self.assertIn("all cases were skipped", stderr.getvalue())
            report = json.loads(report_path.read_text())
            self.assertEqual(report["run"], 1)
            self.assertEqual(report["executed"], 0)
            self.assertEqual(report["skipped"], 1)
            self.assertFalse(report["complete"])

    def test_failed_and_skipped_cases_are_reported_truthfully(self):
        cases = [
            self.Probe("a.Class.test_failure", "failed"),
            self.Probe("b.Class.test_skip", "skipped"),
            self.Probe("c.Class.test_subtest", "subfailure"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "suite.json"
            with mock.patch.object(run_suite, "collect_cases", return_value=cases):
                with contextlib.redirect_stderr(io.StringIO()):
                    code = run_suite.main(["--report", str(report_path)])
            self.assertEqual(code, 1)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["complete"])
            self.assertEqual(report["failures"], 2)
            self.assertEqual(report["skipped"], 1)
            self.assertEqual(report["passed"], 0)
            self.assertEqual(
                [item["status"] for item in report["tests"]],
                ["failed", "skipped", "failed"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
