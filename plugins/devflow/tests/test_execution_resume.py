#!/usr/bin/env python3
"""Subscription-free, compact, advisory Goal resume evidence regressions."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_execution as execution
import devflow_resume as resume


class ExecutionResumeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="devflow-resume-")
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name) / ".devflow/runtime/sample"
        self.action = {"role": "executor", "command": "run", "scope": "work",
                       "phase": "01", "work_item": "P01-I01", "mode": None}
        self.git = {"head": "a" * 40, "status": "available", "paths": [],
                    "path_count": 0, "digest": "b" * 64}

    def view(self):
        data = execution.read(self.runtime, action=self.action, git_state=self.git)
        data["orchestration"] = {"hosted": {"status": "idle"}, "standalone": {"status": "no_record"}}
        data["project_status"] = "implementation"
        data["work"] = {"id": "P01-I01", "status": "in_progress",
                        "start_sha": "a" * 40, "recorded_commit": None}
        return data

    def test_initial_resume_does_not_create_runtime_files(self):
        brief = resume.build(self.view())
        self.assertFalse(self.runtime.exists())
        self.assertEqual(brief["authority"], "advisory_only")
        self.assertIsNone(brief["checkpoint"])
        self.assertEqual(brief["lifecycle"]["work"]["status"], "in_progress")
        self.assertLessEqual(len(resume._encoded(brief)), resume.MAX_BYTES)

    def test_structured_receipt_persists_and_is_not_approval(self):
        execution.checkpoint(
            self.runtime, action=self.action, git_state=self.git,
            stage="implementation", note="Controller test pending", host="codex",
            completed=["Service implemented"], pending=["Controller tests"],
            decisions=["Reuse existing time validator"],
            assumptions=["Policy details require product review"],
            constraints=["Do not change API response shape"],
            files=["apps/hr/src/WorkStandardService.java"],
            next_steps=["Run targeted controller regression"],
        )
        brief = resume.build(self.view())
        ck = brief["checkpoint"]
        self.assertEqual(ck["receipt"]["decisions"], ["Reuse existing time validator"])
        self.assertEqual(ck["receipt"]["files"], ["apps/hr/src/WorkStandardService.java"])
        self.assertEqual(ck["receipt"]["next_steps"], ["Run targeted controller regression"])
        self.assertEqual(ck["authority"], "caller_reported_unverified")
        self.assertEqual(brief["lifecycle"]["work"]["status"], "in_progress")
        self.assertFalse(ck["stale"])

    def test_changed_git_markers_do_not_make_checkpoint_current(self):
        execution.checkpoint(self.runtime, action=self.action, git_state=self.git,
                             stage="verification", note="Reported passing")
        self.git = {**self.git, "head": "c" * 40, "digest": "d" * 64}
        brief = resume.build(self.view())
        self.assertTrue(brief["checkpoint"]["stale"])
        self.assertEqual(brief["lifecycle"]["work"]["status"], "in_progress")

    def test_other_action_cannot_reuse_checkpoint(self):
        execution.checkpoint(self.runtime, action=self.action, git_state=self.git,
                             stage="implementation", note="Old action")
        self.action = {**self.action, "work_item": "P01-I02"}
        brief = resume.build(self.view())
        self.assertIsNone(brief["checkpoint"])

    def test_blocked_owner_and_pending_child_are_not_hidden(self):
        view = self.view()
        view["orchestration"]["hosted"] = {
            "status": "pending_child", "host": "codex", "lease_active": True,
            "requires_termination_verification": True,
            "owner_marker": "PRIVATE_MARKER_SHOULD_NOT_LEAK",
            "pending_primary": {"action": self.action, "work_at_dispatch":
                                {"id": "P01-I01", "status": "in_progress"}},
        }
        view["unconfirmed_commands"] = [{"operation": "work.start", "action": self.action}]
        result = resume.build(view)
        self.assertTrue(result["safety"]["pending_child_or_corrupt"])
        self.assertTrue(result["safety"]["owner_check_required"])
        self.assertTrue(result["safety"]["no_automatic_replay"])
        self.assertEqual(result["safety"]["unconfirmed_commands"], 1)
        self.assertNotIn("PRIVATE_MARKER_SHOULD_NOT_LEAK", json.dumps(result))
        self.assertEqual(result["pending_primary"]["authority"], "dispatch_observation_only")

    def test_overlong_caller_data_stays_bounded(self):
        view = self.view()
        view["checkpoint"] = {"details": {"stage": "run", "note": "x" * 200000,
                                              "pending": ["p" * 90000] * 12,
                                              "receipt": {"decisions": ["d" * 80000] * 12,
                                                          "assumptions": ["a" * 80000] * 12,
                                                          "next_steps": ["n" * 80000] * 12}}}
        view["git"]["paths"] = ["f" * 10000] * 20
        result = resume.build(view)
        self.assertLessEqual(len(resume._encoded(result)), resume.MAX_BYTES)
        self.assertEqual(result["authority"], "advisory_only")

    def test_multibyte_caller_data_still_honors_byte_budget(self):
        view = self.view()
        view["action"] = {key: "한" * 1000 for key in
                          ("role", "command", "scope", "phase", "work_item", "mode")}
        view["git"]["paths"] = ["😀" * 1000] * 20
        view["checkpoint"] = {"details": {"stage": "run", "note": "한" * 10000,
                                              "receipt": {"decisions": ["😀" * 10000] * 5}}}
        brief = resume.build(view)
        self.assertLessEqual(len(resume._encoded(brief)), resume.MAX_BYTES)
        self.assertEqual(brief["authority"], "advisory_only")

    def test_receipt_rejects_unsafe_paths_and_excessive_entries(self):
        for unsafe in ("/etc/passwd", "../other/file", "apps/../secret", "C:\\private\\file"):
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                execution.checkpoint(self.runtime, action=self.action, git_state=self.git,
                                     stage="run", note="sample", files=[unsafe])
        with self.assertRaises(ValueError):
            execution.checkpoint(self.runtime, action=self.action, git_state=self.git,
                                 stage="run", note="sample", decisions=["a"] * 9)
        self.assertFalse(self.runtime.exists())

    def test_existing_checkpoint_remains_backward_compatible(self):
        execution.checkpoint(self.runtime, action=self.action, git_state=self.git,
                             stage="run", note="legacy", completed=["step A"])
        brief = resume.build(self.view())
        self.assertEqual(brief["checkpoint"]["completed"], ["step A"])
        self.assertEqual(brief["checkpoint"]["receipt"]["decisions"], [])


    def test_active_standalone_run_requires_lease_inspection(self):
        view = self.view()
        view["orchestration"]["standalone"] = {"status": "running"}
        brief = resume.build(view)
        self.assertTrue(brief["safety"]["owner_check_required"])
        self.assertTrue(brief["safety"]["no_automatic_replay"])

    def test_corrupt_standalone_observation_never_claims_unblocked(self):
        view = self.view()
        view["orchestration"]["standalone"] = {"status": "record_corrupt"}
        brief = resume.build(view)
        self.assertTrue(brief["safety"]["pending_child_or_corrupt"])
        self.assertTrue(brief["safety"]["owner_check_required"])

    def test_cli_resume_brief_is_compact_and_observational(self):
        import devflow
        parser = devflow.build_parser()
        args = parser.parse_args(["execution", "resume-brief", "sample"])
        action = self.action
        view = self.view()
        with (mock.patch.object(devflow, "repo_root", return_value=self.runtime.parent),
              mock.patch.object(devflow, "execution_context", return_value=(
                  self.runtime, {"next_action": action, "project_status": "implementation"}, self.git)),
              mock.patch.object(devflow.execution, "read", return_value=view),
              mock.patch.object(devflow.execution, "orchestration_snapshot", return_value=view["orchestration"]),
              mock.patch.object(devflow, "find_item", return_value=(None, None, {
                  "status": "in_progress", "evidence": {"start_sha": "a" * 40}}))):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(devflow.execution_command(args), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["authority"], "advisory_only")
        self.assertEqual(payload["lifecycle"]["work"]["status"], "in_progress")
        self.assertLessEqual(len(output.getvalue().encode("utf-8")), resume.MAX_BYTES + 1)
        self.assertFalse(self.runtime.exists())

    def test_cli_exposes_readonly_brief_and_structured_receipt(self):
        import devflow
        parser = devflow.build_parser()
        brief = parser.parse_args(["execution", "resume-brief", "sample"])
        self.assertEqual(brief.func, devflow.execution_command)
        self.assertEqual(brief.execution_command, "resume-brief")
        self.assertIsNone(devflow.execution_operation(brief))
        checkpoint = parser.parse_args([
            "execution", "checkpoint", "sample", "--stage", "run", "--note", "partial",
            "--decision", "reused validator", "--assumption", "policy pending",
            "--constraint", "no API change", "--file", "apps/hr/service.java",
            "--next-step", "run unit tests",
        ])
        self.assertEqual(checkpoint.decisions, ["reused validator"])
        self.assertEqual(checkpoint.next_steps, ["run unit tests"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
