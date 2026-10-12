#!/usr/bin/env python3
"""Newman preflight, execution and retry-disposition regressions."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import devflow_newman as newman


class NewmanFailureClassificationTests(unittest.TestCase):
    def test_all_dispositions_are_sanitized_and_deterministic(self):
        cases = [
            ("passed", [], False, "none", "none", "not_required"),
            ("not_applicable", ["no_http_surface"], False, "none", "none", "not_required"),
            ("blocked", ["newman_tool_config_invalid"], True, "preflight", "configuration", "fix_configuration"),
            ("failed", ["assertion_failure"], False, "execution", "api", "triage_and_rerun"),
            ("blocked", ["newman_tool_unavailable"], False, "execution", "tool", "fix_tool"),
            ("blocked", ["newman_tool_failed"], False, "execution", "tool", "fix_tool"),
            ("blocked", ["missing_response"], False, "execution", "report", "inspect_report"),
            ("blocked", ["cleanup_failed"], False, "execution", "environment", "fix_environment"),
            ("blocked", ["readiness_failed"], False, "execution", "environment", "fix_environment"),
            ("blocked", ["source_or_collection_changed_during_run"], False,
             "execution", "provenance", "refresh_and_rerun"),
        ]
        for status, reasons, preflight, stage, kind, retry in cases:
            with self.subTest(status=status, reasons=reasons):
                value = newman.classify_outcome(status, reasons, preflight=preflight)
                self.assertEqual((value["failure_stage"], value["failure_kind"], value["retry_policy"]),
                                 (stage, kind, retry))
                self.assertEqual(set(value), {"failure_stage", "failure_kind", "retry_policy"})

    def test_completed_api_assertion_is_failed(self):
        report = {"run": {"stats": {
            "requests": {"total": 1, "failed": 0},
            "assertions": {"total": 1, "failed": 1, "pending": 0},
        }, "failures": [{"error": {"name": "AssertionError"}}],
            "executions": [{"response": {"code": 500},
                            "assertions": [{"error": {"name": "AssertionError"}}]}]}}
        status, counts, reasons = newman.summarize(report, 1, 1)
        self.assertEqual(status, "failed")
        self.assertEqual(counts["assertion_failures"], 1)
        self.assertIn("assertion_failure", reasons)
        self.assertEqual(newman.classify_outcome(status, reasons)["failure_kind"], "api")

    def test_missing_execution_response_is_blocked_not_a_code_defect(self):
        report = {"run": {"stats": {
            "requests": {"total": 1, "failed": 1},
            "assertions": {"total": 1, "failed": 0, "pending": 0},
        }, "failures": [{"error": {"name": "ECONNREFUSED"}}],
            "executions": [{"assertions": [{"assertion": "response"}]}]}}
        status, _counts, reasons = newman.summarize(report, 1, 1)
        self.assertEqual(status, "blocked")
        self.assertIn("missing_response", reasons)
        self.assertEqual(newman.classify_outcome(status, reasons)["failure_kind"], "report")

    def test_nonzero_tool_exit_with_valid_assertions_is_blocked(self):
        report = {"run": {"stats": {
            "requests": {"total": 1, "failed": 0},
            "assertions": {"total": 1, "failed": 0, "pending": 0},
        }, "failures": [],
            "executions": [{"response": {"code": 200},
                            "assertions": [{"assertion": "Status"}]}]}}
        status, _counts, reasons = newman.summarize(report, 1, 2)
        self.assertEqual(status, "blocked")
        self.assertEqual(reasons, ["newman_tool_failed"])
        self.assertEqual(newman.classify_outcome(status, reasons)["retry_policy"], "fix_tool")


if __name__ == "__main__":
    unittest.main(verbosity=2)
