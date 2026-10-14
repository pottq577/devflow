#!/usr/bin/env python3
"""Newman preflight, execution and retry-disposition regressions."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import devflow_newman as newman
import test_finalization as finalization_tests
from test_delivery import DeliveryFixtureMixin


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


class NewmanToolPreflightTests(DeliveryFixtureMixin, unittest.TestCase):
    cli = finalization_tests.FinalizationTests.cli
    completed = finalization_tests.FinalizationTests.completed
    fake_newman = finalization_tests.FinalizationTests.fake_newman
    owned_server_command = finalization_tests.FinalizationTests.owned_server_command
    run_newman = finalization_tests.FinalizationTests.run_newman

    def test_tool_checks_fail_without_starting_owned_server(self):
        self.completed()
        cases = [
            ("missing", None, "newman_tool_unavailable"),
            ("invalid_version", 'print("invalid")', "newman_tool_failed"),
            ("nonzero_version", 'print("6.2.1"); sys.exit(2)', "newman_tool_failed"),
            ("invalid_executable", "invalid executable", "newman_tool_failed"),
            ("timeout", 'print("6.2.1")', "newman_tool_failed"),
        ]
        real_run = subprocess.run
        real_popen = subprocess.Popen
        for name, body, reason in cases:
            with self.subTest(name=name):
                runner = self.root / name
                if body is not None:
                    prefix = "" if name == "invalid_executable" else (
                        "#!" + sys.executable + " -S\nimport sys\n"
                    )
                    runner.write_text(prefix + body + "\n")
                    runner.chmod(0o755)
                command = self.owned_server_command()

                def invoke(argv, **kwargs):
                    if name == "timeout" and argv == [str(runner), "--version"]:
                        raise subprocess.TimeoutExpired(argv, 10)
                    return real_run(argv, **kwargs)

                with patch.object(newman.subprocess, "run", side_effect=invoke), patch.object(
                    newman.subprocess, "Popen", wraps=real_popen
                ) as popen:
                    result = self.run_newman(
                        "--newman-bin", str(runner), server_command=command
                    )
                self.assertEqual(result.returncode, 2, result.stderr)
                run = self.read_state()["delivery"]["finalization"]["runs"][-1]
                self.assertEqual(run["reason_codes"], [reason])
                self.assertEqual((run["status"], run["failure_stage"], run["failure_kind"],
                                  run["retry_policy"]),
                                 ("blocked", "execution", "tool", "fix_tool"))
                self.assertEqual([call for call in popen.call_args_list
                                  if call.args[0] == command], [])
                lifecycle = run["server_lifecycle"]
                self.assertEqual(lifecycle["events"], [])
                for stage in ("startup", "readiness", "cleanup"):
                    self.assertEqual(lifecycle[stage]["status"], "not_run")
                self.assertEqual(lifecycle["newman"]["status"], "blocked")
                self.assertEqual(newman.finalization.structural_errors(self.read_state()), [])
                summary = json.loads((self.root / run["summary_file"]).read_text())
                self.assertEqual(summary["server_lifecycle"], lifecycle)
                self.assertFalse((self.root / lifecycle["log_file"]).with_name(
                    "environment.json").exists())
        result = self.cli("delivery", "finalize", "sample")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("requires successful rerun", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
