#!/usr/bin/env python3
"""Check read-only lifecycle projection and render guards against current inputs."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
import test_devflow as fixture_helpers
import test_host_autopilot as host_test_helpers

CLI = Path(__file__).resolve().parents[1] / "scripts" / "devflow.py"


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=cwd, text=True, capture_output=True
    )


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


class ReadonlyProjectionTests(unittest.TestCase):
    @staticmethod
    def commands(message: str) -> list[list[str]]:
        commands = [shlex.split(inline) for inline in re.findall(r"`([^`]+)`", message)]
        return [argv for argv in commands if len(argv) >= 3
                and Path(argv[1]).resolve() == CLI.resolve()
                and argv[2] in {"status", "render"}]

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="devflow-projection-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.com")
        git(self.root, "config", "user.name", "test")
        (self.root / "seed.txt").write_text("seed\n")
        git(self.root, "add", "seed.txt")
        git(self.root, "commit", "-qm", "initial")
        initialized = run(self.root, "init", "billing")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.state_file = self.root / "docs/domains/billing/STATE.yaml"

    def test_no_refresh_prints_current_projection_without_file_side_effects(self) -> None:
        before_state = self.state_file.read_bytes()
        before_head = git(self.root, "rev-parse", "HEAD")
        (self.root / "moved.txt").write_text("new HEAD\n")
        git(self.root, "add", "moved.txt")
        git(self.root, "commit", "-qm", "move HEAD")
        current_head = git(self.root, "rev-parse", "HEAD")
        self.assertNotEqual(current_head, before_head)
        status_before = git(self.root, "status", "--short")
        mtime_before = self.state_file.stat().st_mtime_ns

        status = run(self.root, "status", "billing", "--json", "--no-refresh")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["target_sha"], current_head)
        self.assertEqual(self.state_file.read_bytes(), before_state)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime_before)
        self.assertEqual(git(self.root, "status", "--short"), status_before)

        rendered = run(self.root, "render", "plan", "billing", "--no-refresh")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn(f"- target_sha: {current_head}", rendered.stdout)
        self.assertEqual(self.state_file.read_bytes(), before_state)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime_before)
        self.assertEqual(git(self.root, "status", "--short"), status_before)

        host = host_test_helpers.load_host()
        action = json.loads(status.stdout)["next_action"]
        for role in ("scout", "diagnostician"):
            message = host._host_message(
                self.root,
                host_test_helpers.PLUGIN,
                "billing",
                action,
                {"role": role},
                scout_backed=role == "diagnostician",
                expected_head=current_head,
            )
            commands = self.commands(message)
            self.assertTrue(commands, f"{role} message has no lifecycle CLI commands")
            self.assertEqual(
                {command[2] for command in commands}, {"render"}
            )
            for argv in commands:
                self.assertIn("--no-refresh", argv)
                result = subprocess.run(
                    argv, cwd=self.root, text=True, capture_output=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                if "--check-only" in argv:
                    self.assertEqual(result.stdout, "")
                else:
                    self.assertIn("target_sha", result.stdout)
                    self.assertIn(current_head[:12], result.stdout)
                self.assertEqual(self.state_file.read_bytes(), before_state)
                self.assertEqual(self.state_file.stat().st_mtime_ns, mtime_before)

        default_status = run(self.root, "status", "billing", "--json")
        self.assertEqual(default_status.returncode, 0, default_status.stderr)
        self.assertEqual(json.loads(default_status.stdout)["target_sha"], current_head)
        self.assertNotEqual(self.state_file.read_bytes(), before_state)

        (self.root / "moved-again.txt").write_text("another HEAD\n")
        git(self.root, "add", "moved-again.txt")
        git(self.root, "commit", "-qm", "move HEAD again")
        second_head = git(self.root, "rev-parse", "HEAD")
        before_default_render = self.state_file.read_bytes()
        default_render = run(self.root, "render", "plan", "billing")
        self.assertEqual(default_render.returncode, 0, default_render.stderr)
        self.assertIn(f"- target_sha: {second_head}", default_render.stdout)
        self.assertNotEqual(self.state_file.read_bytes(), before_default_render)

    def test_generated_child_commands_guard_head_and_compact_check_is_pure(self) -> None:
        host = host_test_helpers.load_host()
        git(self.root, "commit", "--allow-empty", "-qm", "move before dispatch")
        state = json.loads(run(self.root, "status", "billing", "--json", "--no-refresh").stdout)
        envelope = host.dispatch_envelope(self.root, host_test_helpers.PLUGIN, host.autopilot.load_policy(host_test_helpers.PLUGIN, None), "billing", state)
        self.assertIn("replaces the role contract's initial status", envelope["primary"]["message"])
        self.assertIn("Do not repeat either before work", envelope["primary"]["scout_message"])
        normal = self.commands(envelope["primary"]["message"])
        compact = self.commands(envelope["primary"]["scout_message"])
        self.assertEqual([argv[2] for argv in normal], ["render", "status"])
        self.assertEqual([argv[2] for argv in compact], ["render", "render", "status"])
        self.assertIn("--check-only", compact[0])
        before = self.state_file.read_bytes()
        mtime = self.state_file.stat().st_mtime_ns
        checked = subprocess.run(compact[0], cwd=self.root, text=True, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(checked.stdout, "")
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime)

        git(self.root, "commit", "--allow-empty", "-qm", "move after dispatch")
        for argv in (normal[0], compact[0]):
            rejected = subprocess.run(argv, cwd=self.root, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2, rejected.stderr)
            self.assertIn("hosted HEAD changed", rejected.stderr)
            self.assertEqual(rejected.stdout, "")
            self.assertEqual(self.state_file.read_bytes(), before)
            self.assertEqual(self.state_file.stat().st_mtime_ns, mtime)

        runtime = fixture_helpers.load_runtime_module()
        project = runtime.project_state
        def move_during_projection(*args, **kwargs):
            projected = project(*args, **kwargs)
            head.return_value = "f" * 40
            return projected
        with mock.patch.object(runtime, "current_sha", return_value=state["target_sha"]) as head, \
             mock.patch.object(runtime, "project_state", side_effect=move_during_projection):
            rejected = fixture_helpers.invoke_runtime(self.root, runtime, *normal[0][2:])
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("hosted HEAD changed", rejected.stderr)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime)

    def test_unborn_pin_rejects_first_commit_without_changing_state(self) -> None:
        root = self.root / "unborn"
        root.mkdir()
        git(root, "init", "-q")
        initialized = run(root, "init", "billing")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        host = host_test_helpers.load_host()
        state = json.loads(run(root, "status", "billing", "--json", "--no-refresh").stdout)
        command = shlex.split(host._render_command(host_test_helpers.PLUGIN, "billing", state["next_action"], check_only=True))
        self.assertEqual(command[command.index("--expected-head") + 1], "unborn")
        state_file = root / "docs/domains/billing/STATE.yaml"
        before, mtime = state_file.read_bytes(), state_file.stat().st_mtime_ns
        checked = subprocess.run(command, cwd=root, text=True, capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-qm", "first")
        rejected = subprocess.run(command, cwd=root, text=True, capture_output=True)
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("hosted HEAD changed", rejected.stderr)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(state_file.read_bytes(), before)
        self.assertEqual(state_file.stat().st_mtime_ns, mtime)

    def test_default_render_uses_current_work_when_stored_action_is_stale(self) -> None:
        state = yaml.safe_load(self.state_file.read_text(encoding="utf-8"))
        state["plan_review"] = {"required": False, "status": "skipped"}
        state["phases"] = {"01": fixture_helpers.phase("executing", "01")}
        state["next_action"] = {
            "role": "architect",
            "command": "plan",
            "scope": "project",
            "phase": None,
            "work_item": None,
        }
        self.state_file.write_text(
            yaml.safe_dump(state, sort_keys=False), encoding="utf-8"
        )
        item = fixture_helpers.item("P01-I01")
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        work_file.parent.mkdir(parents=True, exist_ok=True)
        work_file.write_text(
            yaml.safe_dump(
                fixture_helpers.work("01", item),
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        rendered = run(self.root, "render", "run", "billing", "--task", "P01-I01")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("## Selected WORK item", rendered.stdout)
        self.assertIn("id: P01-I01", rendered.stdout)
        self.assertEqual(
            yaml.safe_load(self.state_file.read_text(encoding="utf-8"))["next_action"]["work_item"],
            "P01-I01",
        )
        host = host_test_helpers.load_host()
        projected = json.loads(run(self.root, "status", "billing", "--json", "--no-refresh").stdout)
        command = shlex.split(host._render_command(host_test_helpers.PLUGIN, "billing", projected["next_action"], expected_head=projected["target_sha"]))
        item["risk"]["level"] = "high"
        work_file.write_text(yaml.safe_dump(fixture_helpers.work("01", item), sort_keys=False), encoding="utf-8")
        before, mtime = self.state_file.read_bytes(), self.state_file.stat().st_mtime_ns
        rejected = subprocess.run(command, cwd=self.root, text=True, capture_output=True)
        self.assertEqual(rejected.returncode, 2, rejected.stderr)
        self.assertIn("hosted action fingerprint changed", rejected.stderr)
        self.assertEqual(rejected.stdout, "")
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime)


if __name__ == "__main__":
    unittest.main()
