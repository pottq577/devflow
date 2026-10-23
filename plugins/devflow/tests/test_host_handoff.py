#!/usr/bin/env python3
"""Host-neutral Goal ownership handoff and native child-fencing regressions."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_session as session
import devflow_host_guard as guard

EVIDENCE = "Operator closed the originating host and verified no child is active."


class HostedHandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name) / ".devflow/runtime/sample"
        self.codex = session.start(self.runtime, host="codex")["session_id"]
        self.marker = session.status(self.runtime)["owner_marker"]

    def transition(self, *, marker=None, host="claude", confirmed=True, evidence=EVIDENCE):
        return session.handoff(
            self.runtime, expected_owner_marker=marker or self.marker,
            target_host=host, confirm_source_stopped=confirmed,
            source_stop_evidence=evidence,
        )

    def test_labels_and_observation_marker_do_not_reveal_session_secret(self):
        status = session.status(self.runtime)
        self.assertEqual(status["status"], "active")
        self.assertEqual(status["host"], "codex")
        self.assertFalse(status["pending_child"])
        self.assertEqual(len(status["owner_marker"]), 64)
        self.assertNotIn(self.codex, json.dumps(status))
        session.start(self.runtime, session_id=self.codex, host="codex")
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_host_mismatch"):
            session.start(self.runtime, session_id=self.codex, host="claude")

    def test_no_unconfirmed_takeover_and_no_stale_takeover(self):
        for confirmed, evidence in ((False, EVIDENCE), (True, ""), (True, " "), (True, "x" * 1025)):
            with self.subTest(confirmed=confirmed, evidence=evidence[:10]):
                with self.assertRaisesRegex(session.SessionBlocked, "hosted_source_stop_unconfirmed"):
                    self.transition(confirmed=confirmed, evidence=evidence)
        session.require(self.runtime, self.codex)
        claude = self.transition()
        self.assertNotEqual(claude["session_id"], self.codex)
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_stale_handoff_marker"):
            self.transition(host="codex")
        session.require(self.runtime, claude["session_id"])
        with self.assertRaises(session.SessionConflict):
            session.require(self.runtime, self.codex)

    def test_bidirectional_handoff_and_persisted_history(self):
        claude = self.transition()
        self.assertEqual(claude["previous_host"], "codex")
        self.assertEqual(claude["host"], "claude")
        codex = self.transition(marker=claude["owner_marker"], host="codex")
        self.assertEqual(codex["host"], "codex")
        session.require(self.runtime, codex["session_id"])
        with session.coordinator(self.runtime, write=False) as connection:
            rows = connection.execute("SELECT source_host, target_host FROM hosted_handoff ORDER BY id").fetchall()
        self.assertEqual(rows, [("codex", "claude"), ("claude", "codex")])

    def test_pending_child_blocks_attested_handoff_without_state_mutation(self):
        step = guard.begin(self.runtime, self.codex, "action-a", {},
                           kind="primary", expected_attempt=0, candidate_alias="fast")
        self.assertTrue(session.status(self.runtime)["pending_child"])
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            self.transition()
        with session.coordinator(self.runtime, write=False) as connection:
            self.assertEqual(session.read_progress(connection)[1]["inflight"]["step_id"], step["step_id"])
        guard.finish(self.runtime, self.codex, step["step_id"], "action-a", {}, outcome="failed")
        self.transition()

    def test_attempts_and_steps_survive_switch_without_reset(self):
        step = guard.begin(self.runtime, self.codex, "action-a", {},
                           kind="primary", expected_attempt=0, candidate_alias="fast")
        guard.finish(self.runtime, self.codex, step["step_id"], "action-a", {}, outcome="failed")
        before = guard.inspect(self.runtime, self.codex, "action-a", {})
        self.assertEqual(before["attempt"], 1)
        new_owner = self.transition()["session_id"]
        after = guard.inspect(self.runtime, new_owner, "action-a", {})
        self.assertEqual(after["attempt"], before["attempt"])
        self.assertEqual(after["steps_completed"], before["steps_completed"])
        with self.assertRaises(session.SessionConflict):
            guard.begin(self.runtime, self.codex, "action-a", {},
                        kind="primary", expected_attempt=1, candidate_alias="fast")
        self.assertEqual(guard.begin(self.runtime, new_owner, "action-a", {},
                         kind="primary", expected_attempt=1, candidate_alias="fast")["status"], "started")

    def test_concurrent_handoffs_require_fresh_marker(self):
        barrier = threading.Barrier(2)
        def run(target):
            barrier.wait()
            try:
                return self.transition(host=target)["status"]
            except session.SessionBlocked as exc:
                return exc.reason
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = {executor.submit(run, "claude"), executor.submit(run, "codex")}
            answers = {future.result() for future in results}
        self.assertEqual(answers, {"handed_off", "hosted_stale_handoff_marker"})

    def test_concurrent_child_reservation_and_handoff_cannot_both_win(self):
        barrier = threading.Barrier(2)
        def begin():
            barrier.wait()
            try:
                guard.begin(self.runtime, self.codex, "a", {}, kind="primary",
                            expected_attempt=0, candidate_alias="fast")
                return "started"
            except session.SessionConflict:
                return "denied"
        def transfer():
            barrier.wait()
            try:
                self.transition()
                return "transferred"
            except session.SessionConflict:
                return "denied"
        with ThreadPoolExecutor(max_workers=2) as executor:
            a, b = executor.submit(begin), executor.submit(transfer)
            outcome = (a.result(), b.result())
        self.assertIn(outcome, {("started", "denied"), ("denied", "transferred")})

    def test_host_column_upgrade_from_legacy_session(self):
        with session.coordinator(self.runtime) as connection:
            connection.execute("ALTER TABLE hosted_session RENAME TO older")
            connection.execute("CREATE TABLE hosted_session (slot INTEGER PRIMARY KEY, "
                               "session_id TEXT, acquired_at REAL, expires_at REAL)")
            connection.execute("INSERT INTO hosted_session VALUES (1, ?, 1, 9999999999)", (self.codex,))
            connection.execute("DROP TABLE older")
        self.assertIsNone(session.status(self.runtime)["host"])
        self.assertIsNone(self.transition()["previous_host"])
        self.assertEqual(session.status(self.runtime)["host"], "claude")

    def test_expired_owner_uses_normal_start_not_attested_handoff(self):
        with session.coordinator(self.runtime) as db:
            db.execute("UPDATE hosted_session SET expires_at=0 WHERE slot=1")
        with self.assertRaisesRegex(session.SessionConflict, "no active hosted owner"):
            self.transition()
        replacement = session.start(self.runtime, host="claude")
        self.assertNotEqual(replacement["session_id"], self.codex)
        self.assertEqual(session.status(self.runtime)["host"], "claude")

    def test_expired_pending_child_still_cannot_be_handed_off(self):
        guard.begin(self.runtime, self.codex, "a", {}, kind="primary",
                    expected_attempt=0, candidate_alias="fast")
        with session.coordinator(self.runtime) as db:
            db.execute("UPDATE hosted_session SET expires_at=0 WHERE slot=1")
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            self.transition()
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.start(self.runtime, host="claude")

    def test_invalid_metadata_never_changes_owner(self):
        for name in ("Claude Code", "", "123", "x" * 50):
            with self.subTest(host=name), self.assertRaises(ValueError):
                self.transition(host=name)
        with self.assertRaises(ValueError):
            self.transition(marker="invalid")
        session.require(self.runtime, self.codex)


if __name__ == "__main__":
    unittest.main(verbosity=2)
