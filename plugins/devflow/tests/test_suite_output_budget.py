#!/usr/bin/env python3
"""Bounded CLI diagnostics and exact-ID partial retry from existing suite evidence."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_suite


class SuiteOutputBudgetTests(unittest.TestCase):
    class Probe(unittest.TestCase):
        def __init__(self, test_id, outcome="passed"):
            super().__init__("runTest")
            self.test_id = test_id
            self.outcome = outcome

        def id(self):
            return self.test_id

        def runTest(self):
            if self.outcome == "failed":
                self.fail("fixture contains massive document: " + "X" * 30000)
            if self.outcome == "skipped":
                self.skipTest("unavailable fixture")
            if self.outcome == "error":
                raise RuntimeError("fixture raised")

    def run_cli(self, fixtures, *flags):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(run_suite, "collect_cases", return_value=fixtures):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = run_suite.main(list(flags))
        return result, stdout.getvalue(), stderr.getvalue()

    def test_default_console_omits_dots_and_bounds_huge_assertion_diff(self):
        fixtures = [self.Probe("a.Case.test_pass"), self.Probe("b.Case.test_fail", "failed")]
        code, _, output = self.run_cli(fixtures)
        self.assertEqual(code, 1)
        self.assertIn("b.Case.test_fail", output)
        self.assertIn("truncated", output)
        self.assertNotIn("X" * 1000, output)
        self.assertLess(len(output), 1450)

    def test_verbose_keeps_full_trace_for_requested_debugging(self):
        fixtures = [self.Probe("a.Case.test_fail", "failed")]
        code, _, output = self.run_cli(fixtures, "--verbose")
        self.assertEqual(code, 1)
        self.assertIn("X" * 1000, output)

    def test_passing_compact_run_shows_only_summary(self):
        code, _, output = self.run_cli([self.Probe("a.Case.test_a"), self.Probe("b.Case.test_b")])
        self.assertEqual(code, 0)
        self.assertIn("Ran 2 tests", output)
        self.assertNotIn("test_a", output)
        self.assertNotIn("test_b", output)

    def test_rerun_uses_exact_nonpassing_ids_and_reports_partial(self):
        fixtures = [self.Probe("a.Case.test_good"), self.Probe("a.Case.test_bad", "failed"),
                    self.Probe("a.Case.test_bad_neighbor"), self.Probe("b.Case.test_skip", "skipped")]
        with tempfile.TemporaryDirectory() as root:
            old = Path(root) / "first.json"
            code, _, _ = self.run_cli(fixtures, "--report", str(old))
            self.assertEqual(code, 1)
            rerun = Path(root) / "retry.json"
            code, _, output = self.run_cli(fixtures, "--rerun-from", str(old),
                                           "--report", str(rerun))
            self.assertEqual(code, 1)
            report = json.loads(rerun.read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(report["selected"], 2)
            self.assertEqual(report["discovered"], 4)
            self.assertEqual({row["id"] for row in report["tests"]},
                             {"a.Case.test_bad", "b.Case.test_skip"})
            self.assertIn("PARTIAL", output)

    def test_report_summary_is_bounded_without_test_discovery(self):
        fixtures = [self.Probe(f"a.Case.test_{n:03}", "failed" if n < 40 else "passed")
                    for n in range(60)]
        with tempfile.TemporaryDirectory() as root:
            old = Path(root) / "first.json"
            self.run_cli(fixtures, "--report", str(old))
            with mock.patch.object(run_suite, "collect_cases", side_effect=AssertionError("must not discover")):
                code, output, _ = self.run_cli_no_discovery("--summary-from", str(old))
            self.assertEqual(code, 0)
            result = json.loads(output)
            self.assertEqual(len(result["nonpassing"]), 8)
            self.assertEqual(result["omitted_nonpassing"], 32)
            self.assertLess(len(output), 1600)
            self.assertIn("slowest", result)

    @staticmethod
    def run_cli_no_discovery(*args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run_suite.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_corrupt_or_stale_reports_fail_closed(self):
        fixtures = [self.Probe("a.Case.test_good")]
        with tempfile.TemporaryDirectory() as root:
            bad = Path(root) / "bad.json"
            bad.write_text('{"schema_version":1,"tests":[{"id":"stale.Case.test_old",'
                           '"status":"failed","seconds":1}],"run":1}')
            code, _, err = self.run_cli(fixtures, "--rerun-from", str(bad))
            self.assertEqual(code, 2)
            self.assertIn("missing test IDs", err)
            bad.write_text("not json")
            code, _, err = self.run_cli(fixtures, "--rerun-from", str(bad))
            self.assertEqual(code, 2)
            self.assertIn("cannot read suite report", err)

    def test_all_passing_previous_report_cannot_be_called_a_partial_rerun(self):
        fixtures = [self.Probe("a.Case.test_good")]
        with tempfile.TemporaryDirectory() as root:
            old = Path(root) / "all-pass.json"
            self.run_cli(fixtures, "--report", str(old))
            code, _, output = self.run_cli(fixtures, "--rerun-from", str(old))
            self.assertEqual(code, 2)
            self.assertIn("no nonpassing tests", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
