#!/usr/bin/env python3
"""Bound scout input and detect capsule staleness from real source/failure evidence."""

from __future__ import annotations

import contextlib
import io
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
import test_scout_contract as scout_contract_tests

CLI = Path(__file__).resolve().parents[1] / "scripts" / "devflow.py"


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=cwd, text=True, capture_output=True
    )


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, capture_output=True, check=True
    ).stdout.strip()


class ScoutEvidenceCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="devflow-scout-cache-")
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
        self.host = host_test_helpers.load_host()
        self.policy = self.host.autopilot.load_policy(host_test_helpers.PLUGIN, self.root)
        self.state_file = self.root / "docs/domains/billing/STATE.yaml"
        self.runtime = self.root / ".devflow/runtime/billing"
        self.capsule = self.runtime / "scout-capsules/run.md"
        self.capsule.parent.mkdir(parents=True, exist_ok=True)
        self.capsule.write_text(scout_contract_tests.VALID, encoding="utf-8")
        self.owner = self.host.session.start(self.runtime)["session_id"]

    def selected_work_item(self) -> None:
        """Move the domain onto one executable WORK item and commit its evidence."""
        state = yaml.safe_load(self.state_file.read_text(encoding="utf-8"))
        state["plan_review"] = {"required": False, "status": "skipped"}
        state["phases"] = {"01": fixture_helpers.phase("executing", "01")}
        state["next_action"] = None
        self.state_file.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
        item = fixture_helpers.item("P01-I01")
        item["evidence"] = {
            "commit": git(self.root, "rev-parse", "HEAD"),
            "changed_files": ["src.py"],
            "comments": [{"path": "src.py", "line": 1, "reason": "Retry invariant."}],
        }
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        work_file.parent.mkdir(parents=True, exist_ok=True)
        work_file.write_text(
            yaml.safe_dump(fixture_helpers.work("01", item), sort_keys=False),
            encoding="utf-8",
        )
        (self.root / "src.py").write_text("# Explain the retry invariant.\ndef execute():\n    return 1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "add source anchor")

    def projected(self) -> dict:
        status = run(self.root, "status", "billing", "--json", "--no-refresh")
        self.assertEqual(status.returncode, 0, status.stderr)
        return json.loads(status.stdout)

    def evidence_render(self) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        state = self.projected()
        argv = shlex.split(
            self.host._render_command(
                host_test_helpers.PLUGIN,
                "billing",
                state["next_action"],
                no_refresh=True,
                expected_head=state["target_sha"],
                evidence=True,
            )
        )
        return run(self.root, *argv[2:]), argv

    def validate(self, fingerprint: str) -> dict:
        stdout = io.StringIO()
        argv = [
            str(host_test_helpers.HOST_SCRIPT), "scout-validate", "billing",
            "--session-id", self.owner, "--fingerprint", fingerprint,
            "--capsule-file", str(self.capsule),
        ]
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 0, stdout.getvalue())
        return json.loads(stdout.getvalue())

    def test_evidence_render_is_bounded_and_omits_the_action_protocol(self) -> None:
        self.selected_work_item()
        state = self.projected()
        before = self.state_file.read_bytes()
        mtime = self.state_file.stat().st_mtime_ns
        rendered, argv = self.evidence_render()
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("evidence", argv)
        payload = yaml.safe_load(
            re.search(r"```yaml\n(.*?)\n```", rendered.stdout, re.DOTALL).group(1)
        )
        self.assertEqual(
            payload["fingerprint"],
            self.host.autopilot.AutopilotController.fingerprint(state["next_action"]),
        )
        self.assertEqual(payload["current_head"], git(self.root, "rev-parse", "HEAD"))
        selected = payload["work"]["selected"]
        self.assertEqual(selected["id"], "P01-I01")
        self.assertEqual(selected["verification"], item_commands(self.root))
        self.assertEqual(selected["comment_paths"], ["src.py"])
        self.assertEqual(payload["originals"]["PLAN"], str(
            self.root / "docs/domains/billing/PLAN.md"))
        self.assertNotIn("## Protocol", rendered.stdout)
        self.assertNotIn("Architecture / implementation strategy", rendered.stdout)
        self.assertLess(len(rendered.stdout), 8000)
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(self.state_file.stat().st_mtime_ns, mtime)

    def test_capsule_is_valid_until_its_evidence_moves(self) -> None:
        self.selected_work_item()
        fingerprint = self.projected()["next_action"]
        fingerprint = self.host.autopilot.AutopilotController.fingerprint(fingerprint)
        first = self.validate(fingerprint)
        self.assertEqual(first["status"], "valid", first)
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        self.capsule.write_text("## Action\nplain answer\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "invalid")
        self.capsule.write_text(scout_contract_tests.VALID, encoding="utf-8")
        (self.root / "moved.txt").write_text("new HEAD\n")
        git(self.root, "add", "moved.txt")
        git(self.root, "commit", "-qm", "move HEAD")
        stale = self.validate(fingerprint)
        self.assertEqual(stale["status"], "stale", stale)
        self.assertNotEqual(stale["evidence_digest"], first["evidence_digest"])
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        document = yaml.safe_load(work_file.read_text(encoding="utf-8"))
        document["items"][0]["pitfalls"] = ["The retry invariant regresses without this anchor."]
        work_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        changed = self.validate(fingerprint)
        self.assertEqual(changed["status"], "stale", changed)
        self.assertNotEqual(changed["evidence_digest"], stale["evidence_digest"])

    def test_retry_scout_requires_no_current_capsule(self) -> None:
        spec = {"role": "diagnostician", "effective_risk": "medium"}
        scout = self.host.autopilot
        self.assertTrue(scout.should_run_scout(spec, 2, scout_on_retry={"diagnostician"}))
        self.assertFalse(scout.should_run_scout(spec, 0, scout_on_retry={"diagnostician"}))
        self.assertFalse(
            scout.should_run_scout(spec, 2, scout_on_retry={"diagnostician"}, scout_cached=True)
        )
        self.assertTrue(
            scout.should_run_scout(spec, 2, scout_before={"diagnostician"}, scout_cached=True)
        )
        state = self.host._load_state(self.root, "billing")
        without = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, self.policy, "billing", state, attempt=3
        )
        cached = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, self.policy, "billing", state,
            attempt=3, scout_cached=True,
        )
        self.assertEqual(cached["fingerprint"], without["fingerprint"])
        self.assertEqual(cached["primary"]["model_alias"], without["primary"]["model_alias"])

    def test_scout_child_reads_the_evidence_index_not_the_full_packet(self) -> None:
        self.selected_work_item()
        state = self.projected()
        message = self.host._host_message(
            self.root,
            host_test_helpers.PLUGIN,
            "billing",
            state["next_action"],
            {"role": "scout"},
            expected_head=state["target_sha"],
        )
        renders = [
            shlex.split(inline)
            for inline in re.findall(r"`([^`]+)`", message)
            if " render " in inline
        ]
        self.assertEqual(len(renders), 1, message)
        self.assertIn("evidence", renders[0])
        self.assertIn("--no-refresh", renders[0])
        self.assertIn("--expected-head", renders[0])
        self.assertIn("--expected-fingerprint", renders[0])
        self.assertNotIn(" status ", " ".join(" ".join(argv[3:]) for argv in renders))


def item_commands(root: Path) -> list[str]:
    import test_devflow

    item = test_devflow.item("P01-I01")
    return [
        str(entry.get("command"))
        for entry in (item.get("verification") or [])
        if isinstance(entry, dict)
    ]


if __name__ == "__main__":
    unittest.main(verbosity=2)