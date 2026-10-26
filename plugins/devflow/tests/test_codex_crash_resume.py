#!/usr/bin/env python3
"""Subscription-free Codex-only crash and resume acceptance with real SQLite guards.

Only the native model process is simulated. A subprocess exits abruptly after a
source edit and durable step reservation; no Codex subscription is required.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_execution as execution
import devflow_host_guard as guard
import devflow_session as session

POLICY = {
    "orchestration": {"hosted": {"max_steps": 12, "max_action_visits": 5}},
    "escalation": {"retries": {"max_no_progress": 4}},
}
ACTION = {"role": "executor", "command": "run", "scope": "work", "phase": "01",
          "work_item": "P01-I01", "mode": None}
FINGERPRINT = "codex-crash-work-P01-I01"

# The process terminates without step-finish, command-finish, or session-end.
CRASH_SCRIPT = r'''
import json, os, sys
from pathlib import Path
import devflow_execution as execution
import devflow_host_guard as guard
import devflow_session as session
root = Path(sys.argv[1])
runtime = Path(sys.argv[2])
source = Path(sys.argv[3])
work = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
policy = json.loads(sys.argv[5])
action = json.loads(sys.argv[6])
owner = session.start(runtime, host="codex")["session_id"]
anchor = execution.primary_anchor(action, execution.git_snapshot(root)["head"], work)
reservation = guard.begin(runtime, owner, "codex-crash-work-P01-I01", policy,
                          kind="primary", expected_attempt=0,
                          candidate_alias="fast", metadata={"primary_anchor": anchor})
execution.record_command_start(runtime, action=action,
                               git_state=execution.git_snapshot(root),
                               command="work run P01-I01", host="codex")
source.write_text("partial implementation\n", encoding="utf-8")
print(json.dumps({"owner": owner, "step": reservation["step_id"]}), flush=True)
os._exit(23)
'''


class CodexCrashResumeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="devflow-codex-crash-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.runtime = self.root / ".devflow" / "runtime" / "sample"
        self.source = self.root / "src" / "feature.txt"
        self.source.parent.mkdir()
        self.source.write_text("original\n", encoding="utf-8")
        self.work_path = self.root / "work-fixture.json"
        self.work = {"id": "P01-I01", "status": "in_progress",
                     "evidence": {"start_sha": "a" * 40, "commit": None}}
        self.work_path.write_text(json.dumps(self.work, sort_keys=True), encoding="utf-8")
        self.work_before = self.work_path.read_bytes()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "add", "src/feature.txt", "work-fixture.json"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.email=test@example.invalid",
                        "-c", "user.name=DevFlow test", "commit", "-qm", "fixture"],
                       check=True, capture_output=True)
        self.start_crashed_child()

    def start_crashed_child(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + env.get("PYTHONPATH", "")
        child = subprocess.run(
            [sys.executable, "-c", CRASH_SCRIPT, str(self.root), str(self.runtime),
             str(self.source), str(self.work_path), json.dumps(POLICY), json.dumps(ACTION)],
            cwd=self.root, env=env, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(child.returncode, 23, child.stderr[:700])
        private = json.loads(child.stdout.strip())
        self.owner, self.step = private["owner"], private["step"]
        self.assertEqual(self.source.read_text(encoding="utf-8"), "partial implementation\n")

    def test_crash_preserves_pending_work_and_blocks_duplicate_spawn(self):
        observation = session.status(self.runtime)
        self.assertEqual(observation["host"], "codex")
        self.assertTrue(observation["pending_child"])
        self.assertNotIn(self.owner, json.dumps(observation))
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.start(self.runtime, host="codex")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_inflight"):
            guard.begin(self.runtime, self.owner, FINGERPRINT, POLICY,
                        kind="primary", expected_attempt=0, candidate_alias="fast")
        handoff = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(handoff["status"], "pending_child")
        self.assertTrue(handoff["requires_termination_verification"])
        self.assertEqual(handoff["pending_primary"]["work_at_dispatch"]["id"], "P01-I01")
        self.assertEqual(self.work_path.read_bytes(), self.work_before)

    def test_same_codex_owner_can_acknowledge_terminated_child_and_resume(self):
        resumed = session.start(self.runtime, session_id=self.owner, host="codex")
        self.assertEqual(resumed["session_id"], self.owner)
        result = guard.finish(self.runtime, self.owner, self.step, FINGERPRINT, POLICY,
                              outcome="cancelled")
        self.assertEqual(result["attempt"], 1)
        self.assertFalse(result["progressed"])
        self.assertEqual(session.end(self.runtime, self.owner)["status"], "released")
        successor = session.start(self.runtime, host="codex")["session_id"]
        self.assertNotEqual(successor, self.owner)
        self.assertEqual(guard.inspect(self.runtime, successor, FINGERPRINT, POLICY)["attempt"], 1)
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_stale_attempt"):
            guard.begin(self.runtime, successor, FINGERPRINT, POLICY,
                        kind="primary", expected_attempt=0, candidate_alias="fast")
        next_step = guard.begin(self.runtime, successor, FINGERPRINT, POLICY,
                                kind="primary", expected_attempt=1, candidate_alias="fast")
        self.assertEqual(next_step["steps_completed"], 2)
        guard.finish(self.runtime, successor, next_step["step_id"], FINGERPRINT, POLICY,
                     outcome="completed")
        # Child completion is not a WORK completion or an audited commit.
        self.assertEqual(self.work_path.read_bytes(), self.work_before)

    def test_expired_crash_requires_external_termination_attestation(self):
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=0")
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.start(self.runtime, host="codex")
        with self.assertRaisesRegex(guard.GuardBlocked, "termination_unconfirmed"):
            guard.recover(self.runtime, self.owner, self.step, FINGERPRINT, POLICY,
                          outcome="cancelled", confirm_child_terminated=False,
                          termination_evidence="unknown")
        receipt = guard.recover(
            self.runtime, self.owner, self.step, FINGERPRINT, POLICY,
            outcome="cancelled", confirm_child_terminated=True,
            termination_evidence="Test operator observed subprocess exit code 23",
        )
        self.assertEqual(receipt["status"], "recovered")
        self.assertEqual(receipt["termination_confirmation"], "explicit_admin_attestation")
        successor = session.start(self.runtime, host="codex")["session_id"]
        observed = guard.inspect(self.runtime, successor, FINGERPRINT, POLICY)
        self.assertEqual(observed["attempt"], 1)
        self.assertEqual(observed["steps_completed"], 1)
        self.assertEqual(self.work_path.read_bytes(), self.work_before)

    def test_unfinished_command_and_checkpoint_cannot_fabricate_progress(self):
        current_git = execution.git_snapshot(self.root)
        self.assertEqual(current_git["status"], "available")
        self.assertIn("src/feature.txt", current_git["paths"])
        checkpoint = execution.checkpoint(
            self.runtime, action=ACTION, git_state=current_git,
            stage="implementation", note="Crash recovery note",
            completed=["claimed implementation done"],
            pending=["inspect source and verify"], host="codex",
        )
        self.assertEqual(checkpoint["authority"], "caller_reported_unverified")
        projection = execution.read(self.runtime, action=ACTION, git_state=current_git)
        self.assertEqual(projection["authority"], "advisory_only")
        self.assertEqual(len(projection["unconfirmed_commands"]), 1)
        self.assertEqual(projection["checkpoint"]["details"]["completed"],
                         ["claimed implementation done"])
        self.assertTrue(session.status(self.runtime)["pending_child"])
        self.assertEqual(self.work_path.read_bytes(), self.work_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
