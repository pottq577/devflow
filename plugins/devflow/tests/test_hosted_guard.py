#!/usr/bin/env python3
"""Persistent host Goal execution bounds: atomic reservations and resume safety."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_host_guard as guard
import devflow_autopilot as autopilot
import devflow_session as session


class HostedExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name) / ".devflow/runtime/sample"
        self.owner = session.start(self.runtime)["session_id"]
        self.policy = {
            "orchestration": {"hosted": {"max_steps": 6, "max_action_visits": 2}},
            "escalation": {"retries": {"max_no_progress": 2}},
        }

    def preview(self, fingerprint="action-a"):
        return guard.inspect(self.runtime, self.owner, fingerprint, self.policy)

    def start(self, fingerprint="action-a", *, kind="primary", attempt=None):
        if attempt is None:
            attempt = self.preview(fingerprint)["attempt"]
        return guard.begin(
            self.runtime, self.owner, fingerprint, self.policy,
            kind=kind, expected_attempt=attempt, candidate_alias="fast",
        )

    def finish(self, record, fingerprint="action-a", outcome="completed"):
        return guard.finish(
            self.runtime, self.owner, record["step_id"], fingerprint,
            self.policy, outcome=outcome,
        )

    def test_preview_is_observational_and_reservation_counts_once(self):
        self.assertEqual(self.preview()["steps_completed"], 0)
        self.assertEqual(self.preview()["steps_completed"], 0)
        record = self.start()
        self.assertEqual(record["steps_completed"], 1)
        self.assertEqual(self.preview()["reason"], "hosted_step_inflight")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_inflight"):
            self.start()
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_inflight"):
            guard.assert_idle(self.runtime, self.owner)
        outcome = self.finish(record, "action-b")
        self.assertTrue(outcome["progressed"])
        self.assertEqual(self.preview("action-b")["attempt"], 0)
        guard.assert_idle(self.runtime, self.owner)

    def test_semantic_retry_bound_survives_renewed_session(self):
        first = self.start()
        self.assertEqual(self.finish(first)["attempt"], 1)
        session.start(self.runtime, session_id=self.owner)
        self.assertEqual(self.preview()["attempt"], 1)
        second = self.start()
        self.assertEqual(self.finish(second)["attempt"], 2)
        self.assertEqual(self.preview()["status"], "ready")
        final = self.start(attempt=2)
        self.assertEqual(self.finish(final)["attempt"], 3)
        self.assertEqual(self.preview()["reason"], "hosted_no_progress_retries_exhausted")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_no_progress_retries_exhausted"):
            self.start()

    def test_default_worker_fallback_attempt_five_is_executable(self):
        self.policy["escalation"]["retries"]["max_no_progress"] = 5
        self.policy["orchestration"]["hosted"]["max_steps"] = 7
        for attempt in range(5):
            record = self.start(attempt=attempt)
            self.assertEqual(self.finish(record)["attempt"], attempt + 1)
        self.assertEqual(self.preview()["attempt"], 5)
        self.assertEqual(self.preview()["status"], "ready")
        last = self.start(attempt=5)
        self.assertEqual(self.finish(last)["attempt"], 6)
        self.assertEqual(self.preview()["reason"], "hosted_no_progress_retries_exhausted")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_no_progress_retries_exhausted"):
            self.start(attempt=6)

    def test_final_permitted_attempt_can_advance_lifecycle(self):
        for attempt in range(2):
            self.finish(self.start(attempt=attempt))
        last = self.start(attempt=2)
        result = self.finish(last, "action-b")
        self.assertTrue(result["progressed"])
        self.assertEqual(self.preview("action-b")["attempt"], 0)
        self.assertEqual(self.preview("action-b")["status"], "ready")

    def test_scout_and_capability_fallback_count_steps_not_semantic_attempt(self):
        scout = self.start(kind="scout")
        self.assertEqual(self.finish(scout)["attempt"], 0)
        incompatible = self.start()
        self.assertEqual(self.finish(incompatible, outcome="capability_blocked")["attempt"], 0)
        self.assertEqual(self.preview()["steps_completed"], 2)
        actual = self.start()
        self.assertEqual(self.finish(actual)["attempt"], 1)

    def test_dispatch_ceiling_is_cumulative_over_scout_and_fallback(self):
        self.policy["orchestration"]["hosted"]["max_steps"] = 2
        first = self.start(kind="scout")
        self.finish(first)
        second = self.start()
        self.finish(second, outcome="capability_blocked")
        self.assertEqual(self.preview()["reason"], "hosted_max_steps_exhausted")
        with self.assertRaises(guard.GuardBlocked):
            self.start()
        # Completion can be reported even when the dispatch budget is used up.
        done = guard.inspect(self.runtime, self.owner, "complete", self.policy, terminal=True)
        self.assertEqual(done["status"], "ready")

    def test_detects_action_cycles_across_independently_progressing_steps(self):
        first = self.start("a")
        self.finish(first, "b")
        second = self.start("b")
        self.finish(second, "a")
        self.assertEqual(self.preview("a")["action_visits"], 2)
        third = self.start("a")
        self.finish(third, "b")
        fourth = self.start("b")
        self.finish(fourth, "a")
        self.assertEqual(self.preview("a")["reason"], "hosted_action_cycle_detected")

    def test_stale_attempt_and_wrong_step_token_are_fail_closed(self):
        first = self.start()
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_owner_mismatch"):
            guard.finish(self.runtime, self.owner, "wrong", "action-b", self.policy, outcome="completed")
        self.finish(first)
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_stale_attempt"):
            self.start(attempt=0)
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_owner_mismatch"):
            self.finish(first)

    def test_foreign_or_expired_session_cannot_read_or_write_progress(self):
        with self.assertRaises(session.SessionConflict):
            guard.inspect(self.runtime, "foreign", "a", self.policy)
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=0 WHERE slot=1")
        with self.assertRaises(session.SessionConflict):
            self.preview()
        with self.assertRaises(session.SessionConflict):
            self.start()
        new_owner = session.start(self.runtime)["session_id"]
        self.assertNotEqual(new_owner, self.owner)
        self.assertEqual(guard.inspect(self.runtime, new_owner, "a", self.policy)["steps_completed"], 0)

    def test_corrupt_and_invalid_configuration_never_allows_unbounded_runs(self):
        self.policy["orchestration"]["hosted"]["max_steps"] = 0
        with self.assertRaisesRegex(ValueError, "max_steps"):
            self.preview()
        self.policy["orchestration"]["hosted"]["max_steps"] = True
        with self.assertRaises(ValueError):
            self.preview()
        self.policy["orchestration"]["hosted"]["max_steps"] = 5
        with session.coordinator(self.runtime) as connection:
            connection.execute("CREATE TABLE hosted_progress (slot INTEGER PRIMARY KEY, session_id TEXT NOT NULL, progress TEXT NOT NULL)")
            connection.execute(
                "INSERT INTO hosted_progress (slot, session_id, progress) VALUES (1, ?, ?)",
                (self.owner, json.dumps({"steps": "x"})),
            )
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_progress_corrupt"):
            self.preview()

    def test_durable_state_survives_separate_python_process(self):
        record = self.start()
        self.finish(record)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + env.get("PYTHONPATH", "")
        code = (
            "import json,sys;from pathlib import Path;import devflow_host_guard as g;"
            "policy=json.loads(sys.argv[3]);"
            "r=g.inspect(Path(sys.argv[1]),sys.argv[2],'action-a',policy);"
            "assert r['steps_completed']==1 and r['attempt']==1"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code, str(self.runtime), self.owner, json.dumps(self.policy)],
            env=env, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def recover(self, record, **overrides):
        arguments = {
            "outcome": "cancelled", "confirm_child_terminated": True,
            "termination_evidence": "Administrator verified native child terminal status at 12:00 UTC",
        }
        arguments.update(overrides)
        return guard.recover(self.runtime, self.owner, record["step_id"], "action-a", self.policy, **arguments)

    def snapshot(self):
        with session.coordinator(self.runtime) as connection:
            return list(connection.iterdump())

    def test_expired_owner_recovery_is_exact_once_and_auditable(self):
        record = self.start()
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=0")
        with ThreadPoolExecutor(max_workers=4) as executor:
            receipts = list(executor.map(lambda _: self.recover(record), range(4)))
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        receipt = receipts[0]
        self.assertEqual(receipt["termination_confirmation"], "explicit_admin_attestation")
        self.assertEqual(receipt["pending_step"]["step_id"], record["step_id"])
        self.assertEqual(receipt["attempt"], 1)
        self.assertEqual(session.status(self.runtime)["status"], "idle")
        with session.coordinator(self.runtime) as connection:
            owner, value = session.read_progress(connection)
            self.assertEqual(owner, self.owner)
            self.assertIsNone(value["inflight"])
            self.assertEqual(value["attempt"], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM hosted_recovery").fetchone()[0], 1)
        before = self.snapshot()
        for changed in ({"outcome": "failed"}, {"termination_evidence": "Different administrator facts"}):
            with self.assertRaisesRegex(guard.GuardBlocked, "hosted_recovery_conflict"):
                self.recover(record, **changed)
            self.assertEqual(self.snapshot(), before)
        replacement = session.start(self.runtime)["session_id"]
        with self.assertRaises(session.SessionConflict):
            self.recover(record)
        session.end(self.runtime, replacement)

    def test_recovery_refusals_preserve_pending_and_owner(self):
        record = self.start()
        before = self.snapshot()
        for override in ({"confirm_child_terminated": False}, {"termination_evidence": "  \n"}):
            with self.assertRaisesRegex(guard.GuardBlocked, "termination_unconfirmed"):
                self.recover(record, **override)
            self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_owner_mismatch"):
            self.recover({"step_id": "wrong"})
        with self.assertRaises(session.SessionConflict):
            guard.recover(self.runtime, "foreign", record["step_id"], "a", self.policy, outcome="cancelled", confirm_child_terminated=True, termination_evidence="Trusted facts")
        self.assertEqual(self.snapshot(), before)

    def test_orphan_recovery_keeps_finish_semantics(self):
        record = self.start()
        with session.coordinator(self.runtime) as connection:
            connection.execute("DELETE FROM hosted_session")
        receipt = self.recover(record, outcome="capability_blocked")
        self.assertEqual(receipt["attempt"], 0)
        self.assertEqual(receipt["steps_completed"], 1)
        self.assertEqual(session.status(self.runtime)["status"], "idle")

    def test_recovery_rolls_back_clear_and_release_when_receipt_write_fails(self):
        record = self.start()
        before = self.snapshot()
        original_save = guard._save

        def fail_after_save(connection, owner, value):
            original_save(connection, owner, value)
            raise OSError("Injected receipt persistence failure")

        with mock.patch.object(guard, "_save", side_effect=fail_after_save):
            with self.assertRaises(OSError):
                self.recover(record)
        self.assertEqual(self.snapshot(), before)

    def test_malformed_progress_is_fenced_before_any_owner_change(self):
        record = self.start()
        original = self.snapshot()
        with session.coordinator(self.runtime) as connection:
            good = session.read_progress(connection)[1]
        malformed = [
            "{invalid", json.dumps({**good, "inflight": {}}),
            json.dumps({**good, "inflight": []}), json.dumps({**good, "attempt": -1}),
            json.dumps({**good, "visits": {"action-a": True}}),
            json.dumps(good)[:-1] + ', "inflight": null}',
        ]
        for raw in malformed:
            with self.subTest(raw=raw):
                with session.coordinator(self.runtime) as connection:
                    connection.execute("UPDATE hosted_progress SET progress=?", (raw,))
                    connection.execute("UPDATE hosted_session SET expires_at=0")
                before = self.snapshot()
                for command in (lambda: session.start(self.runtime), lambda: session.end(self.runtime, self.owner), lambda: self.recover(record), lambda: autopilot.DomainLease(self.runtime, 1).acquire()):
                    with self.assertRaisesRegex(guard.GuardBlocked, "hosted_progress_corrupt"):
                        command()
                    self.assertEqual(self.snapshot(), before)
        self.assertNotEqual(self.snapshot(), original)

    def test_corrupt_recovery_receipt_cannot_be_treated_as_exact_confirmation(self):
        record = self.start()
        receipt = self.recover(record)
        stored = json.dumps(receipt)
        malformed = [
            stored[:-1] + ', "status": "recovered"}',
            json.dumps({key: receipt[key] for key in (
                "session_id", "step_id", "status", "termination_confirmation", "outcome", "termination_evidence",
            )}),
        ]
        for key in ("pending_step", "after_fingerprint", "recovered_at", "progressed", "attempt", "steps_completed", "next_guard"):
            malformed.append(json.dumps({name: value for name, value in receipt.items() if name != key}))
        for key in ("step_id", "kind", "fingerprint", "attempt", "candidate_alias"):
            malformed.append(json.dumps({**receipt, "pending_step": {
                name: value for name, value in receipt["pending_step"].items() if name != key
            }}))
        for key, value in (
            ("after_fingerprint", " "), ("recovered_at", True), ("recovered_at", -1),
            ("progressed", 1), ("attempt", True), ("steps_completed", 0), ("next_guard", {}),
        ):
            malformed.append(json.dumps({**receipt, key: value}))
        for key, value in (("step_id", "foreign-step"), ("kind", []), ("attempt", True), ("fingerprint", ""), ("candidate_alias", 1)):
            malformed.append(json.dumps({**receipt, "pending_step": {**receipt["pending_step"], key: value}}))
        for raw in malformed:
            with self.subTest(raw=raw):
                with session.coordinator(self.runtime) as connection:
                    connection.execute("UPDATE hosted_recovery SET receipt=?", (raw,))
                before = self.snapshot()
                with self.assertRaisesRegex(guard.GuardBlocked, "hosted_recovery_corrupt"):
                    self.recover(record)
                self.assertEqual(self.snapshot(), before)

    def test_foreign_current_owner_cannot_hide_or_recover_original_pending_child(self):
        record = self.start()
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET session_id='foreign'")
        before = self.snapshot()
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_inflight"):
            session.start(self.runtime, session_id="foreign")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_inflight"):
            guard.inspect(self.runtime, "foreign", "a", self.policy)
        with self.assertRaises(session.SessionConflict):
            self.recover(record)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
