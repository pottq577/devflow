#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parent.parent
HOST_SCRIPT = PLUGIN / "scripts" / "devflow_host.py"
CLI = PLUGIN / "scripts" / "devflow.py"


def load_host():
    spec = importlib.util.spec_from_file_location("devflow_host_test", HOST_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HostAutopilotUnitTests(unittest.TestCase):
    def setUp(self):
        self.host = load_host()
        self.policy = self.host.autopilot.load_policy(PLUGIN, None)

    def test_host_dispatch_routes_without_backend_detection(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "role": "architect",
                "command": "plan",
                "scope": "project",
            },
        }
        with mock.patch.object(
            self.host.autopilot.CapabilityRegistry,
            "detect",
            side_effect=AssertionError(
                "host dispatch must not detect subprocess backends"
            ),
        ):
            result = self.host.dispatch_envelope(
                Path("/repo"), PLUGIN, self.policy, "sample", state
            )
        self.assertEqual(result["status"], "dispatch_required")
        self.assertEqual(result["primary"]["model_alias"], "frontier")
        self.assertEqual(
            result["primary"]["route"]["execution"]["backend"],
            self.host.HOST_BACKEND,
        )
        self.assertEqual(result["primary"]["fork_turns"], "none")
        self.assertEqual(result["scout"]["model_alias"], "balanced")

    def test_host_dispatch_message_recovers_packet_in_child(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "role": "executor",
                "command": "run",
                "scope": "phase",
                "phase": "01",
                "work_item": "P01-I01",
                "item_kind": "implementation",
                "item_risk": "high",
            },
        }
        result = self.host.dispatch_envelope(
            Path("/repo"), PLUGIN, self.policy, "sample", state
        )
        primary = result["primary"]
        self.assertEqual(primary["model_alias"], "fast")
        self.assertEqual(primary["reasoning_effort"], "xhigh")
        self.assertIsNone(result["scout"])
        self.assertIn("render run sample --task P01-I01", primary["message"])
        self.assertIn("Do not run `codex exec`", primary["message"])
        self.assertNotIn("## Runtime packet", primary["message"])
        self.assertLess(len(primary["message"]), 5000)
        self.assertEqual(
            [row["alias"] for row in primary["candidates"]], ["fast", "balanced"]
        )

    def test_plan_boundary_stops_before_worker_dispatch(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "role": "executor",
                "command": "run",
                "scope": "phase",
                "phase": "01",
                "work_item": "P01-I01",
                "item_kind": "implementation",
            },
        }
        result = self.host.dispatch_envelope(
            Path("/repo"),
            PLUGIN,
            self.policy,
            "sample",
            state,
            until="plan",
        )
        self.assertEqual(result["status"], "checkpoint")
        self.assertEqual(result["reason"], "execution_boundary_reached")

    def test_render_command_preserves_audit_scope(self):
        command = self.host._render_command(
            PLUGIN,
            "sample",
            {
                "command": "audit",
                "scope": "work",
                "mode": "closure",
                "work_item": "P01-I01",
            },
        )
        self.assertIn("render audit sample", command)
        self.assertIn("--scope work", command)
        self.assertIn("--task P01-I01", command)
        self.assertIn("--mode closure", command)


class HostAutopilotCliTests(unittest.TestCase):
    def new_repo(self) -> Path:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        return root

    def tearDown(self):
        temp = getattr(self, "temp", None)
        if temp is not None:
            temp.cleanup()

    def run_host(self, root: Path, *args: str, env: dict[str, str] | None = None):
        return subprocess.run(
            [sys.executable, str(HOST_SCRIPT), *args],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
        )

    def test_cli_dispatch_does_not_require_codex_exec_or_native_runner(self):
        root = self.new_repo()
        initialized = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

        env = os.environ.copy()
        env["DEVFLOW_CODEX_BIN"] = str(root / "missing-codex")
        env.pop("DEVFLOW_NATIVE_AGENT_RUNNER", None)
        env.pop("DEVFLOW_NATIVE_AGENT_MODELS", None)
        dispatched = self.run_host(root, "dispatch", "sample", env=env)
        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        result = json.loads(dispatched.stdout)
        self.assertEqual(result["status"], "dispatch_required")
        self.assertEqual(
            result["primary"]["route"]["execution"]["backend"],
            "host_native_agent",
        )

    def test_bootstrap_is_host_dispatched_then_finalized_locally(self):
        root = self.new_repo()
        requirements = root / "requirements.md"
        requirements.write_text(
            "Build a routed autonomous workflow.\n", encoding="utf-8"
        )

        prepared = self.run_host(
            root,
            "bootstrap",
            "sample",
            "--requirements-file",
            str(requirements),
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        envelope = json.loads(prepared.stdout)
        self.assertEqual(envelope["status"], "dispatch_required")
        self.assertEqual(envelope["primary"]["model_alias"], "frontier")
        self.assertFalse((root / "docs/domains/sample/STATE.yaml").exists())

        target = root / "docs/domains/sample/PRD.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            """# Routed workflow PRD

## 1. Context
Autonomous delivery.

## 2. Goals
Route work by role.

## 3. Non-goals
None.

## 4. Requirements

### REQ-001 - Routed lifecycle
- Requirement: Route planning and execution to suitable models.
- Acceptance criteria:
  - AC-001: Planning and implementation use routed specialists.

## 5. Business Rules

### RULE-001 - Preserve lifecycle
Use DevFlow state.

## 6. Domain Model / State
DevFlow state.

## 7. Flows
Goal to completion.

## 8. Constraints
Use installed backends.

## 9. Assumptions
Approved requirements are stable.

## 10. Open Decisions
None.
""",
            encoding="utf-8",
        )
        finalized = self.run_host(root, "bootstrap-finalize", "sample")
        self.assertEqual(finalized.returncode, 0, finalized.stderr + finalized.stdout)
        result = json.loads(finalized.stdout)
        self.assertEqual(result["status"], "initialized")
        self.assertTrue((root / "docs/domains/sample/STATE.yaml").exists())

    def test_goal_skill_prefers_host_native_subagents(self):
        text = (PLUGIN / "skills" / "goal" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("spawn_agent", text)
        self.assertIn("host.py dispatch", text)
        self.assertIn('fork_turns="none"', text)
        self.assertIn("Do not launch a nested `codex exec`", text)
        self.assertIn("autopilot bootstrap", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
