#!/usr/bin/env python3
"""Subscription-free integration of both native hosts with one persisted DevFlow runtime.

Real session/guard/journal/router modules are used; only model execution is simulated.
A simulated terminal child does not mark WORK done, nor does it prove Claude Agent UI behavior.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PLUGIN = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import devflow_autopilot as autopilot
import devflow_claude as claude
import devflow_execution as execution
import devflow_host as host
import devflow_host_guard as guard
import devflow_session as session


class CrossHostParityIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="devflow-native-parity-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / ".devflow/runtime/sample"
        self.owner = session.start(self.runtime, host="codex")["session_id"]
        self.policy = {"orchestration": {"hosted": {"max_steps": 10, "max_action_visits": 4}},
                       "escalation": {"retries": {"max_no_progress": 3}}}
        self.action = {"role": "executor", "command": "run", "scope": "phase",
                       "phase": "01", "work_item": "P01-I01", "mode": None}
        self.work = {"id": "P01-I01", "status": "in_progress",
                     "evidence": {"start_sha": "a" * 40, "commit": None}}
        self.anchor = execution.primary_anchor(self.action, "a" * 40, self.work)
        self.work_bytes = json.dumps(self.work, sort_keys=True)

    def reserve(self, owner, *, attempt=0, alias="fast", action="a"):
        return guard.begin(self.runtime, owner, action, self.policy, kind="primary",
                           expected_attempt=attempt, candidate_alias=alias,
                           metadata={"primary_anchor": self.anchor})

    def finish(self, owner, reservation, *, outcome="completed", next_action="a"):
        return guard.finish(self.runtime, owner, reservation["step_id"], next_action,
                            self.policy, outcome=outcome)

    def switch(self, destination):
        marker = session.status(self.runtime)["owner_marker"]
        return session.handoff(
            self.runtime, expected_owner_marker=marker, target_host=destination,
            confirm_source_stopped=True,
            source_stop_evidence="Test operator confirmed the prior simulated child is terminal",
        )["session_id"]

    def test_roundtrip_preserves_work_receipts_and_semantic_retry_counters(self):
        initial = self.owner
        first = self.reserve(initial)
        self.finish(initial, first, outcome="failed")
        self.assertEqual(guard.inspect(self.runtime, initial, "a", self.policy)["attempt"], 1)
        claude_owner = self.switch("claude")
        with self.assertRaises(session.SessionConflict):
            session.require(self.runtime, initial)
        self.assertEqual(guard.inspect(self.runtime, claude_owner, "a", self.policy)["attempt"], 1)
        claude_payload = {"status": "dispatch_required", "primary": {
            "model": "sonnet", "reasoning_effort": "high", "permissions": "inherit",
            "candidates": [{"alias": "balanced", "model": "sonnet", "reasoning_effort": "high"}],
        }}
        instructions = claude.decorate(claude_payload)["primary"]["claude"]
        self.assertEqual(instructions["agent_type"], "devflow:devflow-high")
        self.assertEqual(instructions["model"], "sonnet")
        self.assertIs(instructions["run_in_background"], False)
        second = self.reserve(claude_owner, attempt=1, alias="balanced")
        self.finish(claude_owner, second, outcome="completed", next_action="b")
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["last_primary"]["work_at_dispatch"]["id"], "P01-I01")
        self.assertEqual(observed["last_primary"]["child_outcome"], "completed")
        self.assertEqual(observed["last_primary"]["authority"], "dispatch_observation_only")
        self.assertEqual(self.work_bytes, json.dumps(self.work, sort_keys=True))
        codex_owner = self.switch("codex")
        self.assertEqual(guard.inspect(self.runtime, codex_owner, "b", self.policy)["attempt"], 0)
        self.assertEqual(guard.inspect(self.runtime, codex_owner, "b", self.policy)["steps_completed"], 2)
        with self.assertRaises(session.SessionConflict):
            session.require(self.runtime, claude_owner)
        self.assertEqual(session.status(self.runtime)["host"], "codex")

    def test_pending_child_cannot_be_duplicated_or_handed_off_to_either_host(self):
        first = self.reserve(self.owner)
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            self.switch("claude")
        with self.assertRaisesRegex(guard.GuardBlocked, "hosted_step_inflight"):
            self.reserve(self.owner)
        observed = execution.orchestration_snapshot(self.runtime)["hosted"]
        self.assertEqual(observed["status"], "pending_child")
        self.assertTrue(observed["requires_termination_verification"])
        self.assertNotIn(self.owner, json.dumps(observed))
        self.assertNotIn(first["step_id"], json.dumps(observed))
        self.finish(self.owner, first, outcome="cancelled")
        claude_owner = self.switch("claude")
        second = self.reserve(claude_owner, attempt=1, alias="balanced")
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            self.switch("codex")
        self.finish(claude_owner, second, outcome="failed")
        self.switch("codex")

    def test_simulated_quota_interruption_needs_explicit_child_recovery(self):
        first = self.reserve(self.owner)
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=0")
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.start(self.runtime, host="claude")
        with self.assertRaisesRegex(guard.GuardBlocked, "termination_unconfirmed"):
            guard.recover(self.runtime, self.owner, first["step_id"], "a", self.policy,
                          outcome="cancelled", confirm_child_terminated=False,
                          termination_evidence="Unknown child status")
        with session.coordinator(self.runtime, write=False) as connection:
            self.assertEqual(session.read_progress(connection)[1]["inflight"]["step_id"], first["step_id"])
        guard.recover(self.runtime, self.owner, first["step_id"], "a", self.policy,
                      outcome="cancelled", confirm_child_terminated=True,
                      termination_evidence="Trusted test observer verified simulated native child termination")
        new_owner = session.start(self.runtime, host="claude")["session_id"]
        self.assertEqual(guard.inspect(self.runtime, new_owner, "a", self.policy)["attempt"], 1)
        self.assertEqual(self.work_bytes, json.dumps(self.work, sort_keys=True))
        self.assertEqual(execution.orchestration_snapshot(self.runtime)["hosted"]["last_primary"]["child_outcome"], "cancelled")

    def test_journal_and_checkpoints_do_not_remove_pending_child_fence(self):
        self.reserve(self.owner)
        execution.checkpoint(self.runtime, action=self.action, git_state={"head": "a" * 40, "digest": "stable"},
                             stage="implementation", note="Test-only continuation hint",
                             completed=["reported complete by caller"])
        projection = execution.read(self.runtime, action=self.action,
                                    git_state={"head": "a" * 40, "digest": "stable"})
        self.assertEqual(projection["authority"], "advisory_only")
        self.assertEqual(projection["checkpoint"]["details"]["completed"], ["reported complete by caller"])
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            self.switch("claude")
        self.assertEqual(self.work_bytes, json.dumps(self.work, sort_keys=True))

    def test_provider_routes_preserve_roles_but_choose_distinct_model_families(self):
        codex_policy = autopilot.load_policy(PLUGIN, None)
        claude_policy = claude.load_policy(PLUGIN, None)
        cases = [
            ({"command": "plan", "scope": "project"}, "gpt-6.1-sol", "opus"),
            ({"command": "run", "scope": "work", "work_item": "P01-I01"}, "gpt-6-luna", "sonnet"),
            ({"command": "audit", "scope": "work", "work_item": "P01-I01"}, "gpt-6.1-sol", "opus"),
            ({"command": "audit", "scope": "integration"}, "gpt-6.1-sol", "opus"),
        ]
        for action, codex_id, claude_id in cases:
            with self.subTest(action=action):
                codex_route = host._host_route(codex_policy, action, {"risk_profile": "medium"}, 0)
                claude_route = host._host_route(claude_policy, action, {"risk_profile": "medium"}, 0)
                self.assertEqual(codex_route["model"]["selected"], codex_id)
                self.assertEqual(claude_route["model"]["selected"], claude_id)
                self.assertEqual(codex_route["role"], claude_route["role"])
                self.assertEqual(claude_route["execution"]["backend"], "host_native_agent")

    def test_claude_and_codex_user_overrides_remain_isolated(self):
        config = self.root / ".devflow"
        config.mkdir(exist_ok=True)
        (config / "routing.yaml").write_text(
            "roles:\n  worker: { profile: frontier, effort: xhigh }\n", encoding="utf-8")
        (config / "claude-routing.yaml").write_text(
            "roles:\n  worker: { profile: economy, effort: high }\n", encoding="utf-8")
        codex_policy = autopilot.load_policy(PLUGIN, self.root)
        claude_policy = claude.load_policy(PLUGIN, self.root)
        self.assertEqual(codex_policy["roles"]["worker"]["profile"], "frontier")
        self.assertEqual(claude_policy["roles"]["worker"]["profile"], "economy")
        self.assertEqual(codex_policy["model_registry"]["models"]["frontier"]["id"], "gpt-6.1-sol")
        self.assertEqual(claude_policy["model_registry"]["models"]["frontier"]["id"], "opus")

    def test_claude_plugin_wrapper_loads_without_authentication(self):
        wrapper = PLUGIN / "skills/goal/scripts/claude_host.py"
        process = subprocess.run([sys.executable, str(wrapper), "--help"],
                                 capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("session-handoff", process.stdout)
        self.assertIn("step-start", process.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
