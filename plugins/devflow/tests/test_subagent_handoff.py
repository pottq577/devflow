#!/usr/bin/env python3
"""Durable primary-child anchors: a native child is not WORK completion."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_execution as execution
import devflow_host_guard as guard
import devflow_session as session


class SubagentHandoffTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name) / ".devflow/runtime/demo"
        self.owner = session.start(self.runtime, host="codex")["session_id"]
        self.action = {
            "role": "executor", "command": "run", "scope": "phase",
            "phase": "01", "work_item": "P01-I01", "mode": None,
        }
        self.work = {
            "id": "P01-I01", "status": "in_progress",
            "evidence": {"start_sha": "a" * 40, "commit": None},
        }
        self.anchor = execution.primary_anchor(self.action, "a" * 40, self.work)
        self.policy = {"orchestration": {"hosted": {"max_steps": 10, "max_action_visits": 4}},
                       "escalation": {"retries": {"max_no_progress": 3}}}

    def reserve(self, kind="primary", *, metadata=True):
        return guard.begin(
            self.runtime, self.owner, "action-a", self.policy, kind=kind,
            expected_attempt=0, candidate_alias="fast",
            metadata={"primary_anchor": self.anchor} if metadata else None,
        )

    def handoff(self):
        status = session.status(self.runtime)
        return session.handoff(
            self.runtime, expected_owner_marker=status["owner_marker"],
            target_host="claude", confirm_source_stopped=True,
            source_stop_evidence="Operator verified old parent and children stopped",
        )["session_id"]

    def test_pending_primary_remains_fenced_and_recoverable_by_work_id(self):
        reservation = self.reserve()
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["status"], "pending_child")
        self.assertEqual(observed["pending_primary"]["work_at_dispatch"]["id"], "P01-I01")
        self.assertEqual(observed["pending_primary"]["work_at_dispatch"]["status"], "in_progress")
        self.assertEqual(observed["pending_primary"]["authority"], "dispatch_observation_only")
        self.assertNotIn(self.owner, json.dumps(observed))
        self.assertNotIn(reservation["step_id"], json.dumps(observed))
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            self.handoff()
        with session.coordinator(self.runtime, write=False) as db:
            self.assertEqual(session.read_progress(db)[1]["inflight"]["step_id"], reservation["step_id"])

    def test_completed_child_does_not_change_work_or_reset_retry_guards(self):
        before = json.dumps(self.work, sort_keys=True)
        reservation = self.reserve()
        guard.finish(self.runtime, self.owner, reservation["step_id"], "action-a", self.policy,
                     outcome="completed")
        self.assertEqual(json.dumps(self.work, sort_keys=True), before)
        self.assertEqual(guard.inspect(self.runtime, self.owner, "action-a", self.policy)["attempt"], 1)
        other = self.handoff()
        self.assertEqual(guard.inspect(self.runtime, other, "action-a", self.policy)["attempt"], 1)
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertIsNone(observed["pending_primary"])
        self.assertEqual(observed["last_primary"]["work_at_dispatch"]["status"], "in_progress")
        self.assertEqual(observed["last_primary"]["child_outcome"], "completed")
        self.assertEqual(observed["last_primary"]["authority"], "dispatch_observation_only")
        with self.assertRaises(session.SessionConflict):
            guard.begin(self.runtime, self.owner, "action-a", self.policy, kind="primary",
                        expected_attempt=1, candidate_alias="fast")

    def test_failed_child_does_not_claim_success_after_handoff(self):
        record = self.reserve()
        guard.finish(self.runtime, self.owner, record["step_id"], "action-a", self.policy,
                     outcome="failed")
        other = self.handoff()
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["last_primary"]["child_outcome"], "failed")
        new = guard.begin(self.runtime, other, "action-a", self.policy, kind="primary",
                          expected_attempt=1, candidate_alias="fast",
                          metadata={"primary_anchor": self.anchor})
        self.assertEqual(new["status"], "started")
        self.assertEqual(execution.orchestration_snapshot(self.runtime)["hosted"]["pending_primary"]["work_at_dispatch"]["id"], "P01-I01")

    def test_reservation_is_backward_compatible_with_legacy_primary(self):
        self.reserve(metadata=False)
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["status"], "pending_child")
        self.assertIsNone(observed["pending_primary"])

    def test_scout_anchor_is_not_exposed_as_primary(self):
        self.reserve(kind="scout")
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertIsNone(observed["pending_primary"])

    def test_acknowledged_primary_anchor_survives_bidirectional_handoff(self):
        record = self.reserve()
        guard.finish(self.runtime, self.owner, record["step_id"], "action-b", self.policy,
                     outcome="completed")
        claude = self.handoff()
        report = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(report["last_primary"]["action"]["work_item"], "P01-I01")
        status = session.status(self.runtime)
        codex = session.handoff(self.runtime, expected_owner_marker=status["owner_marker"],
                                target_host="codex", confirm_source_stopped=True,
                                source_stop_evidence="Operator confirmed stopped")["session_id"]
        self.assertNotEqual(claude, codex)
        report = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(report["last_primary"]["head_at_dispatch"], "a" * 40)

    def test_recovered_primary_retains_original_work_anchor_after_termination_attestation(self):
        reservation = self.reserve()
        with session.coordinator(self.runtime) as db:
            db.execute("UPDATE hosted_session SET expires_at=0 WHERE slot=1")
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.start(self.runtime, host="claude")
        facts = "Administrator verified prior child exited before recovery"
        receipt = guard.recover(
            self.runtime, self.owner, reservation["step_id"], "action-a",
            self.policy, outcome="cancelled", confirm_child_terminated=True,
            termination_evidence=facts,
        )
        self.assertEqual(receipt["status"], "recovered")
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["status"], "idle")
        self.assertIsNone(observed["pending_primary"])
        self.assertEqual(observed["last_primary"]["work_at_dispatch"]["id"], "P01-I01")
        self.assertEqual(observed["last_primary"]["child_outcome"], "cancelled")
        self.assertTrue(observed["last_primary"]["recovered_after_termination_attestation"])
        self.assertNotIn(self.owner, json.dumps(observed))
        self.assertNotIn(reservation["step_id"], json.dumps(observed))
        # Recovery is exactly-once before ownership is assigned to a new host.
        self.assertEqual(guard.recover(
            self.runtime, self.owner, reservation["step_id"], "action-a",
            self.policy, outcome="cancelled", confirm_child_terminated=True,
            termination_evidence=facts,
        ), receipt)
        replacement = session.start(self.runtime, host="claude")["session_id"]
        self.assertEqual(guard.inspect(self.runtime, replacement, "action-a", self.policy)["attempt"], 1)
        with self.assertRaises(session.SessionConflict):
            guard.recover(self.runtime, self.owner, reservation["step_id"], "action-a",
                          self.policy, outcome="cancelled", confirm_child_terminated=True,
                          termination_evidence=facts)

    def test_duplicate_primary_acknowledgement_cannot_clear_another_step(self):
        reservation = self.reserve()
        guard.finish(self.runtime, self.owner, reservation["step_id"], "action-a", self.policy,
                     outcome="completed")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_owner_mismatch"):
            guard.finish(self.runtime, self.owner, reservation["step_id"], "action-a", self.policy,
                         outcome="completed")
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["last_primary"]["child_outcome"], "completed")

    def test_primary_anchor_does_not_copy_secret_or_extraneous_metadata(self):
        self.work["secret"] = "do-not-store"
        self.action["instructions"] = "do-not-store"
        anchor = execution.primary_anchor(self.action, None, self.work)
        self.assertNotIn("do-not-store", json.dumps(anchor))
        self.assertEqual(anchor["work"]["status"], "in_progress")

    def test_non_work_primary_keeps_action_without_work_claim(self):
        action = {"role": "auditor", "command": "audit", "scope": "work", "work_item": "P01-I01"}
        anchor = execution.primary_anchor(action, "b" * 40)
        self.assertNotIn("work", anchor)
        shown = execution.primary_anchor_view({"kind": "primary", "metadata": {"primary_anchor": anchor}})
        self.assertIsNone(shown["work_at_dispatch"])
        self.assertEqual(shown["action"]["command"], "audit")

    def test_run_requires_actual_selected_work_at_reservation(self):
        with self.assertRaisesRegex(ValueError, "selected WORK"):
            execution.primary_anchor(self.action, "a" * 40, None)

    def test_corrupt_optional_anchor_does_not_expose_untrusted_data(self):
        shown = execution.primary_anchor_view({
            "kind": "primary", "metadata": {"primary_anchor": {
                "action": {"command": "run"}, "work": {"id": "x" * 1000, "status": "done"}}},
        })
        self.assertIsNone(shown)


if __name__ == "__main__":
    unittest.main(verbosity=2)
