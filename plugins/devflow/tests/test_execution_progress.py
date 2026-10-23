#!/usr/bin/env python3
"""Cross-host, cross-role operational continuity without a second lifecycle authority."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
import types
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import closing

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_execution as progress


class ExecutionProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.runtime = self.base / ".devflow/runtime/attendance"
        self.action = {
            "role": "executor", "command": "run", "scope": "work",
            "phase": "01", "work_item": "P01-I07", "mode": None,
        }
        self.git = {"head": "a" * 40, "status": "available", "paths": [], "path_count": 0, "digest": "b" * 64}

    def test_cli_work_done_verification_flags_do_not_break_execution_journal(self):
        # The `--command` option of `work done` shadows the root `command`
        # argparse destination. Exercise the actual parser rather than a hand-
        # constructed Namespace so this regression cannot hide in CLI wiring.
        import devflow
        parser = devflow.build_parser()
        for evidence in ([], ["pytest -> passed"], ["pytest -> passed", "gradle -> passed"]):
            argv = ["work", "done", "attendance", "P01-I07"]
            for value in evidence:
                argv.extend(["--command", value])
            with self.subTest(evidence=evidence):
                args = parser.parse_args(argv)
                self.assertEqual(args.command, evidence)
                self.assertEqual(devflow.execution_operation(args), "work.done")
        start = parser.parse_args(["work", "start", "attendance", "P01-I07"])
        self.assertEqual(devflow.execution_operation(start), "work.start")
        audit = parser.parse_args([
            "audit", "apply", "attendance", "--scope", "work", "--task", "P01-I07",
        ])
        self.assertEqual(devflow.execution_operation(audit), "audit.apply")

    def test_read_is_read_only_for_new_domain(self):
        output = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(output["events"], [])
        self.assertEqual(output["unconfirmed_commands"], [])
        self.assertIsNone(output["checkpoint"])
        self.assertFalse(self.runtime.exists())

    def test_checkpoint_is_scoped_to_current_lifecycle_action(self):
        receipt = progress.checkpoint(
            self.runtime, action=self.action, git_state=self.git, stage="implementation",
            note="Service done, controller outstanding", completed=["Service"],
            pending=["Controller"], host="codex",
        )
        self.assertEqual(receipt["authority"], "caller_reported_unverified")
        first = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(first["checkpoint"]["details"]["pending"], ["Controller"])
        other = {**self.action, "command": "audit", "role": "auditor"}
        self.assertIsNone(progress.read(self.runtime, action=other, git_state=self.git)["checkpoint"])
        self.assertEqual(len(progress.read(self.runtime, action=other, git_state=self.git)["events"]), 1)

    def test_bidirectional_handoff_preserves_existing_checkpoint(self):
        progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                            stage="run", note="Entity persisted", host="codex")
        claude = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(claude["checkpoint"]["details"]["host"], "codex")
        progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                            stage="test", note="Test running", host="claude")
        codex = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(codex["checkpoint"]["details"]["host"], "claude")
        self.assertEqual(codex["checkpoint"]["details"]["note"], "Test running")

    def test_abrupt_interruption_is_unknown_not_completed(self):
        progress.record_command_start(self.runtime, action=self.action, git_state=self.git,
                                      command="work.start", host="codex")
        state = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(len(state["unconfirmed_commands"]), 1)
        self.assertEqual(state["unconfirmed_commands"][0]["operation"], "work.start")
        self.assertEqual(state["authority"], "advisory_only")

    def test_command_finish_reconciles_exact_execution_id(self):
        receipt = progress.record_command_start(self.runtime, action=self.action,
                                                 git_state=self.git, command="audit.apply")
        progress.record_command_finish(self.runtime, command_id=receipt, action=self.action,
                                       git_state=self.git, exit_code=0)
        state = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(state["unconfirmed_commands"], [])
        self.assertEqual(state["events"][0]["details"]["exit_code"], 0)

    def test_failed_command_is_recorded_not_treated_as_completion(self):
        receipt = progress.record_command_start(self.runtime, action=self.action,
                                                 git_state=self.git, command="work.done")
        progress.record_command_finish(self.runtime, command_id=receipt, action=self.action,
                                       git_state=self.git, exit_code=2)
        state = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(state["events"][0]["details"]["exit_code"], 2)
        self.assertIsNone(state["checkpoint"])

    def test_uncertain_command_is_found_beyond_display_limit(self):
        progress.record_command_start(self.runtime, action=self.action, git_state=self.git,
                                      command="audit.apply")
        for index in range(15):
            progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                                stage="testing", note=f"Probe {index}")
        state = progress.read(self.runtime, action=self.action, git_state=self.git, limit=3)
        self.assertEqual(len(state["events"]), 3)
        self.assertEqual(len(state["unconfirmed_commands"]), 1)

    def test_head_or_worktree_change_does_not_fabricate_a_success(self):
        progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                            stage="test", note="Pending tests")
        new_git = {**self.git, "head": "c" * 40, "digest": "d" * 64}
        state = progress.read(self.runtime, action=self.action, git_state=new_git)
        self.assertTrue(state["checkpoint"]["head_changed"])
        self.assertTrue(state["checkpoint"]["working_tree_changed"])
        self.assertEqual(state["checkpoint"]["details"]["authority"], "caller_reported_unverified")

    def test_identical_action_core_ignores_incidental_metadata(self):
        first = progress.action_fingerprint(self.action)
        self.assertEqual(first, progress.action_fingerprint({**self.action, "reason": "display only"}))

    def test_reject_blank_overlong_note_and_bogus_host(self):
        for opts in ({"note": " "}, {"note": "a" * 2001}, {"note": "ok", "host": "Claude Code!!"}):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                                    stage="run", **opts)
        self.assertFalse(self.runtime.exists())

    def test_reject_excessive_context(self):
        with self.assertRaisesRegex(ValueError, "at most 12"):
            progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                                stage="run", note="ok", completed=["x"] * 13)

    def test_corrupt_event_fails_explicitly(self):
        progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                            stage="run", note="ok")
        with closing(sqlite3.connect(self.runtime / "execution-journal.sqlite3")) as db, db:
            db.execute("UPDATE events SET action_fingerprint='incorrect'")
        with self.assertRaisesRegex(ValueError, "execution_journal_corrupt"):
            progress.read(self.runtime, action=self.action, git_state=self.git)

    def test_verification_checkpoint_retains_observed_results(self):
        progress.checkpoint(self.runtime, action=self.action, git_state=self.git,
                            stage="verification", note="Unit suite failed",
                            verification=["./gradlew test -> failed: 1"])
        state = progress.read(self.runtime, action=self.action, git_state=self.git)
        self.assertEqual(state["checkpoint"]["details"]["verification"],
                         ["./gradlew test -> failed: 1"])

    def test_plan_and_audit_checkpoints_use_same_implementation(self):
        for role, command in (("architect", "plan"), ("auditor", "audit"), ("executor", "finalize")):
            action = {**self.action, "role": role, "command": command}
            progress.checkpoint(self.runtime, action=action, git_state=self.git,
                                stage="review", note=f"{command} in progress")
            state = progress.read(self.runtime, action=action, git_state=self.git)
            self.assertEqual(state["checkpoint"]["details"]["note"], f"{command} in progress")

    def test_handoff_surfaces_unacknowledged_hosted_child_without_lease_mutation(self):
        leases = self.runtime / "leases"
        leases.mkdir(parents=True)
        database = leases / "coordinator.sqlite3"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE hosted_session (slot INTEGER PRIMARY KEY, session_id TEXT, acquired_at REAL, expires_at REAL)")
            connection.execute("INSERT INTO hosted_session VALUES (1, 'owner', ?, ?)", (time.time(), time.time() + 300))
            connection.execute("CREATE TABLE hosted_progress (slot INTEGER PRIMARY KEY, session_id TEXT, progress TEXT)")
            connection.execute("INSERT INTO hosted_progress VALUES (1, 'owner', ?)",
                               (json.dumps({"inflight": {"kind": "primary", "candidate_alias": "fast"}}),))
        def read_progress(connection):
            row = connection.execute("SELECT session_id, progress FROM hosted_progress WHERE slot=1").fetchone()
            return row[0], json.loads(row[1])
        with mock.patch.dict(sys.modules, {"devflow_session": types.SimpleNamespace(read_progress=read_progress)}):
            state = progress.orchestration_snapshot(self.runtime)
        self.assertEqual(state["hosted"]["status"], "pending_child")
        self.assertTrue(state["hosted"]["requires_termination_verification"])
        self.assertNotIn("step_id", state["hosted"])
        self.assertNotIn("session_id", state["hosted"])

    def test_handoff_includes_standalone_controller_status_without_duplicating_state(self):
        self.runtime.mkdir(parents=True)
        (self.runtime / "controller.json").write_text(json.dumps({
            "status": "checkpoint", "reason": "execution_boundary_reached",
            "steps_completed": 4, "model_secret": "do-not-copy",
        }))
        state = progress.orchestration_snapshot(self.runtime)
        self.assertEqual(state["standalone"]["status"], "checkpoint")
        self.assertEqual(state["standalone"]["steps_completed"], 4)
        self.assertNotIn("model_secret", state["standalone"])

    def test_corrupt_hosted_or_standalone_record_does_not_claim_idle(self):
        leases = self.runtime / "leases"
        leases.mkdir(parents=True)
        (leases / "coordinator.sqlite3").write_bytes(b"corrupt")
        (self.runtime / "controller.json").write_text("not json")
        state = progress.orchestration_snapshot(self.runtime)
        self.assertEqual(state["hosted"]["status"], "record_corrupt")
        self.assertEqual(state["standalone"]["status"], "record_corrupt")

    def test_git_snapshot_captures_untracked_and_modified_paths(self):
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)
        subprocess.run(["git", "-C", str(self.base), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.base), "config", "user.name", "DevFlow Test"], check=True)
        (self.base / "example.txt").write_text("first\n")
        subprocess.run(["git", "-C", str(self.base), "add", "example.txt"], check=True)
        subprocess.run(["git", "-C", str(self.base), "commit", "-qm", "base"], check=True)
        (self.base / "example.txt").write_text("second\n")
        (self.base / "new.txt").write_text("new\n")
        snapshot = progress.git_snapshot(self.base)
        self.assertEqual(snapshot["status"], "available")
        self.assertIn("example.txt", snapshot["paths"])
        self.assertIn("new.txt", snapshot["paths"])
        self.assertEqual(snapshot["path_count"], 2)

    def test_same_changed_path_with_new_file_content_updates_git_marker(self):
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)
        subprocess.run(["git", "-C", str(self.base), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.base), "config", "user.name", "DevFlow Test"], check=True)
        file = self.base / "service.java"
        file.write_text("original")
        subprocess.run(["git", "-C", str(self.base), "add", "service.java"], check=True)
        subprocess.run(["git", "-C", str(self.base), "commit", "-qm", "base"], check=True)
        file.write_text("first edit")
        before = progress.git_snapshot(self.base)
        file.write_text("different second edit")
        after = progress.git_snapshot(self.base)
        self.assertEqual(before["paths"], after["paths"])
        self.assertNotEqual(before["digest"], after["digest"])

    def test_git_snapshot_excludes_runtime_store(self):
        subprocess.run(["git", "init", "-q", str(self.base)], check=True)
        self.runtime.mkdir(parents=True)
        (self.runtime / "execution-journal.sqlite3").write_bytes(b"test")
        snapshot = progress.git_snapshot(self.base)
        self.assertNotIn(".devflow/runtime/attendance/execution-journal.sqlite3", snapshot["paths"])


if __name__ == "__main__":
    unittest.main()
