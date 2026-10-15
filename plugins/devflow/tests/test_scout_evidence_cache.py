#!/usr/bin/env python3
"""Bound scout input and detect capsule staleness from real source/failure evidence."""

from __future__ import annotations

import contextlib
import copy
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
# Documented input budget for the bounded evidence index, including its markdown wrapper.


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
            "changed_files": ["src.py", "src/service.py"],
            "comments": [{"path": "src.py", "line": 1, "reason": "Retry invariant."}],
        }
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        work_file.parent.mkdir(parents=True, exist_ok=True)
        work_file.write_text(
            yaml.safe_dump(fixture_helpers.work("01", item), sort_keys=False),
            encoding="utf-8",
        )
        (self.root / "src.py").write_text("# Explain the retry invariant.\ndef execute():\n    return 1\n")
        (self.root / "src/service.py").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "src/service.py").write_text("def validate():\n    return True\n")
        (self.root / ".devflow/routing.yaml").parent.mkdir(parents=True, exist_ok=True)
        (self.root / ".devflow/routing.yaml").write_text(
            "orchestration:\n  scout_before: [worker]\n", encoding="utf-8"
        )
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
        return self.run_capsule_command("scout-validate", fingerprint)

    def bind(self, fingerprint: str) -> dict:
        step_id, alias = self.completed_scout_step(fingerprint)
        source = self.capsule
        self.capsule = self.capsule.parent / f"{step_id}.md"
        self.capsule.write_bytes(source.read_bytes())
        return self.run_capsule_command("scout-bind", fingerprint, step_id, alias)

    def completed_scout_step(self, fingerprint: str) -> tuple[str, str]:
        state = self.host._load_state(self.root, "billing")
        policy = self.host.autopilot.load_policy(host_test_helpers.PLUGIN, self.root)
        envelope = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, policy, "billing", state
        )
        alias = envelope["scout"]["model_alias"]
        common = ["billing", "--session-id", self.owner]
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", [
                    str(host_test_helpers.HOST_SCRIPT), "step-start", *common,
                    "--kind", "scout", "--fingerprint", fingerprint,
                    "--candidate-alias", alias, "--attempt", "0",
                ]), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 0, stdout.getvalue())
        step_id = json.loads(stdout.getvalue())["step_id"]
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", [
                    str(host_test_helpers.HOST_SCRIPT), "step-finish", *common,
                    "--step-id", step_id, "--outcome", "completed",
                ]), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 0, stdout.getvalue())
        return step_id, alias

    def run_capsule_command(
        self, command: str, fingerprint: str, step_id: str | None = None,
        model_alias: str | None = None,
    ) -> dict:
        stdout = io.StringIO()
        argv = [
            str(host_test_helpers.HOST_SCRIPT), command, "billing",
            "--session-id", self.owner, "--fingerprint", fingerprint,
            "--capsule-file", str(self.capsule),
        ]
        if step_id:
            argv.extend(["--step-id", step_id, "--model-alias", model_alias or ""])
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 0, stdout.getvalue())
        return json.loads(stdout.getvalue())

    def sidecar(self) -> Path:
        return self.capsule.with_suffix(".evidence.json")

    def current_fingerprint(self) -> str:
        state = self.projected()
        return self.host.autopilot.AutopilotController.fingerprint(state["next_action"])


    def test_capsule_needs_binding_and_stale_never_returns_to_valid(self) -> None:
        """D01: validation is side-effect free, so valid -> stale -> stale cannot flip back."""
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        first = self.validate(fingerprint)
        self.assertEqual(first["status"], "stale", first)
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.assertFalse(self.sidecar().exists())
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        binding = self.sidecar().read_bytes()
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        self.assertEqual(self.sidecar().read_bytes(), binding)
        (self.root / "moved.txt").write_text("new HEAD\n")
        git(self.root, "add", "moved.txt")
        git(self.root, "commit", "-qm", "move HEAD")
        stale = self.validate(fingerprint)
        self.assertEqual(stale["status"], "stale", stale)
        self.assertNotEqual(stale["evidence_digest"], first["evidence_digest"])
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.assertEqual(self.sidecar().read_bytes(), binding)
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        document = yaml.safe_load(work_file.read_text(encoding="utf-8"))
        document["items"][0]["pitfalls"] = ["The retry invariant regresses without this anchor."]
        work_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        changed = self.validate(fingerprint)
        self.assertEqual(changed["status"], "stale", changed)
        self.assertNotEqual(changed["evidence_digest"], stale["evidence_digest"])
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        # Only a fresh scout may rebind, and a new binding is valid again.
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        self.assertNotEqual(self.sidecar().read_bytes(), binding)

    def test_instruction_files_are_part_of_the_reserved_evidence_snapshot(self) -> None:
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        (self.root / "AGENTS.md").write_text("New root instruction.\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        (self.root / "src/AGENTS.md").write_text("New source instruction.\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")

    def test_capsule_cannot_be_bound_without_a_completed_scout_step(self) -> None:
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        argv = [
            str(host_test_helpers.HOST_SCRIPT), "scout-bind", "billing",
            "--session-id", self.owner, "--fingerprint", fingerprint,
            "--capsule-file", str(self.capsule), "--step-id", "arbitrary",
            "--model-alias", "arbitrary",
        ]
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 1, stdout.getvalue())
        self.assertFalse(self.sidecar().exists())

    def test_completed_scout_step_binds_once_and_requires_its_routed_alias(self) -> None:
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        step_id, alias = self.completed_scout_step(fingerprint)
        source = self.capsule
        self.capsule = self.capsule.parent / f"{step_id}.md"
        self.capsule.write_bytes(source.read_bytes())
        wrong_argv = [
            str(host_test_helpers.HOST_SCRIPT), "scout-bind", "billing",
            "--session-id", self.owner, "--fingerprint", fingerprint,
            "--capsule-file", str(self.capsule), "--step-id", step_id,
            "--model-alias", alias + "-wrong",
        ]
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", wrong_argv), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 1, stdout.getvalue())
        self.assertFalse(self.sidecar().exists())
        argv = [
            str(host_test_helpers.HOST_SCRIPT), "scout-bind", "billing",
            "--session-id", self.owner, "--fingerprint", fingerprint,
            "--capsule-file", str(self.capsule), "--step-id", step_id,
            "--model-alias", alias,
        ]
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 0, stdout.getvalue())
        binding = self.sidecar().read_bytes()
        self.assertEqual(json.loads(binding)["step_id"], step_id)
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 1, stdout.getvalue())
        self.assertEqual(self.sidecar().read_bytes(), binding)

    def test_capsule_citation_outside_the_step_start_scope_cannot_be_added_at_bind(self) -> None:
        self.selected_work_item()
        cited = self.root / "src/unindexed.py"
        cited.write_text("def hidden(): return True\n", encoding="utf-8")
        self.capsule.write_text(
            scout_contract_tests.VALID.replace("src/service.py", "src/unindexed.py"),
            encoding="utf-8",
        )
        result = self.bind(self.current_fingerprint())
        self.assertEqual(result["status"], "stale", result)
        self.assertFalse(self.sidecar().exists())

    def test_root_level_file_citation_and_work_reference_are_snapshotted(self) -> None:
        self.selected_work_item()
        helper = self.root / "helper.py"
        helper.write_text("def helper(): return True\n", encoding="utf-8")
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        document = yaml.safe_load(work_file.read_text(encoding="utf-8"))
        document["items"][0]["references"] = ["helper.py"]
        work_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        self.capsule.write_text(
            scout_contract_tests.VALID.replace(
                "`src/service.py:42-58`",
                "`src/service.py:42-58` and `helper.py:1`",
            ),
            encoding="utf-8",
        )
        fingerprint = self.current_fingerprint()
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        helper.write_text("def helper(): return False\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")

    def test_capsule_body_replacement_and_damaged_provenance_are_refused(self) -> None:
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        pointer = self.runtime / "scout-current.json"
        pointer_bytes = pointer.read_bytes()
        pointer_record = json.loads(pointer_bytes)
        pointer_record["evidence_digest"] = "ev1:" + "0" * 64
        pointer.write_text(json.dumps(pointer_record), encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        pointer.write_bytes(pointer_bytes)
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        self.capsule.write_text("## Action\nplain answer\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "invalid")
        self.capsule.write_text(scout_contract_tests.VALID + "\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "invalid")
        self.capsule.write_text(scout_contract_tests.VALID, encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        self.sidecar().write_text("{not json", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.sidecar().write_text(
            json.dumps({"version": 1, "evidence_digest": "ev1:x"}), encoding="utf-8"
        )
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.sidecar().unlink()
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.sidecar().write_bytes(b"\xff\xfe")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        self.sidecar().unlink()
        self.capsule.write_bytes(b"\xff\xfe")
        self.assertEqual(self.validate(fingerprint)["status"], "invalid")

    def test_uncommitted_source_moves_invalidate_a_bound_capsule(self) -> None:
        """D02: the digest covers referenced source bytes, not only index fields."""
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        (self.root / "notes.txt").write_text("unrelated\n", encoding="utf-8")
        git(self.root, "add", "notes.txt")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        source = self.root / "src.py"
        source.write_text("# Explain the retry invariant.\ndef execute():\n    return 2\n")
        unstaged = self.validate(fingerprint)
        self.assertEqual(unstaged["status"], "stale", unstaged)
        git(self.root, "add", "src.py")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        source.write_text("# Explain the retry invariant.\ndef execute():\n    return 1\n")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")
        source.rename(self.root / "renamed.py")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")

    def test_scoped_index_mode_and_removal_invalidate_but_unrelated_staging_does_not(self) -> None:
        self.selected_work_item()
        fingerprint = self.current_fingerprint()
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        git(self.root, "update-index", "--chmod=+x", "src.py")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")

        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        git(self.root, "update-index", "--force-remove", "src.py")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")

    def test_missing_traversal_symlink_and_raced_evidence_fail_closed(self) -> None:
        self.selected_work_item()
        index = self.host.devflow.evidence_index(
            self.root, "billing", self.host._load_state(self.root, "billing")
        )
        scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
        self.assertTrue(confirmed)
        self.assertIn(str((self.root / "src.py").resolve()), scope)
        instructions = self.root / "AGENTS.md"
        instructions.write_text("Optional instruction exists.\n", encoding="utf-8")
        fingerprint_path = self.host.devflow.file_fingerprint
        with mock.patch.object(
            self.host.devflow,
            "file_fingerprint",
            side_effect=lambda path: None
            if path == instructions.resolve()
            else fingerprint_path(path),
        ):
            _scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
        self.assertFalse(confirmed, "an existing unreadable optional source is unconfirmed")
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        for changed_file in ("missing.py", "../outside.py"):
            document = yaml.safe_load(work_file.read_text(encoding="utf-8"))
            document["items"][0]["evidence"]["changed_files"] = [changed_file]
            work_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            index = self.host.devflow.evidence_index(
                self.root, "billing", self.host._load_state(self.root, "billing")
            )
            _scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
            self.assertFalse(confirmed, changed_file)
        outside = self.root.parent / f"{self.root.name}-outside-evidence.py"
        outside.write_text("secret\n", encoding="utf-8")
        try:
            (self.root / "src/escape.py").symlink_to(outside)
            document = yaml.safe_load(work_file.read_text(encoding="utf-8"))
            document["items"][0]["evidence"]["changed_files"] = ["src/escape.py"]
            work_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            index = self.host.devflow.evidence_index(
                self.root, "billing", self.host._load_state(self.root, "billing")
            )
            _scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
            self.assertFalse(confirmed)
            with mock.patch.object(self.host.devflow, "file_fingerprint", return_value=None):
                _scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
            self.assertFalse(confirmed)
        finally:
            outside.unlink(missing_ok=True)

    def test_command_text_is_not_a_path_but_structured_logs_are_snapshotted(self) -> None:
        self.selected_work_item()
        log_file = self.root / "run.log"
        log_file.write_text("first run\n", encoding="utf-8")
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        document = yaml.safe_load(work_file.read_text(encoding="utf-8"))
        document["items"][0]["evidence"]["commands"] = [
            "pytest -q -> passed",
            {"command": "pytest -q --log-file run.log", "log_file": "run.log"},
        ]
        work_file.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        state = self.host._load_state(self.root, "billing")
        index = self.host.devflow.evidence_index(self.root, "billing", state)
        scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
        self.assertTrue(confirmed)
        self.assertIn(str(log_file.resolve()), scope)

        fingerprint = self.host.autopilot.AutopilotController.fingerprint(state["next_action"])
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        self.assertEqual(self.validate(fingerprint)["status"], "valid")
        log_file.write_text("changed run\n", encoding="utf-8")
        self.assertEqual(self.validate(fingerprint)["status"], "stale")

    def test_all_work_documents_are_snapshotted_without_selected_item(self) -> None:
        self.selected_work_item()
        state = self.host._load_state(self.root, "billing")
        index = self.host.devflow.evidence_index(self.root, "billing", state)
        index["work"]["selected"] = {}
        scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
        work_file = self.root / "docs/domains/billing/work/phase-01.yaml"
        self.assertTrue(confirmed)
        self.assertIn(str(work_file.resolve()), scope)
        before = scope[str(work_file.resolve())]

        work_file.write_text(work_file.read_text(encoding="utf-8") + "\n# updated\n", encoding="utf-8")
        updated_scope, confirmed = self.host.devflow.evidence_scope(self.root, index)
        self.assertTrue(confirmed)
        self.assertNotEqual(before, updated_scope[str(work_file.resolve())])

    def test_dispatch_reuses_only_a_host_verified_capsule(self) -> None:
        """D01: --scout-cached is a claim; the host re-verifies before skipping a scout."""
        self.selected_work_item()
        policy = copy.deepcopy(self.policy)
        policy["orchestration"]["scout_on_retry"] = ["worker"]
        state = self.host._load_state(self.root, "billing")
        fingerprint = self.host.autopilot.AutopilotController.fingerprint(state["next_action"])
        self.capsule.write_text(scout_contract_tests.VALID, encoding="utf-8")
        claimed = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, policy, "billing", state,
            attempt=2, scout_cached=True,
        )
        self.assertIsNotNone(claimed["scout"], "an unbound capsule must not suppress the scout")
        self.assertEqual(self.bind(fingerprint)["status"], "bound")
        cached = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, policy, "billing", state,
            attempt=2, scout_cached=True,
        )
        self.assertIsNone(cached["scout"], cached)
        self.sidecar().unlink()
        missing_sidecar = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, policy, "billing", state,
            attempt=2, scout_cached=True,
        )
        self.assertIsNotNone(missing_sidecar["scout"], "pointer alone cannot authorize reuse")
        (self.root / "src.py").write_text("# Changed after binding.\ndef execute():\n    return 1\n")
        moved = self.host.dispatch_envelope(
            self.root, host_test_helpers.PLUGIN, policy, "billing", state,
            attempt=2, scout_cached=True,
        )
        self.assertIsNotNone(moved["scout"], "stale evidence must force a new scout")




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
            attempt=2, scout_cached=True,
        )
        self.assertEqual(cached["fingerprint"], without["fingerprint"])
        self.assertEqual(cached["primary"]["model_alias"], without["primary"]["model_alias"])

    def test_diagnostician_is_routed_once_at_diagnose_at(self) -> None:
        self.selected_work_item()
        engine = self.host.autopilot.RouteEngine(
            self.policy, self.host.autopilot.CapabilityRegistry.assumed(self.policy)
        )
        state = self.host._load_state(self.root, "billing")
        action = state["next_action"]
        self.assertEqual(action["command"], "run")
        roles = [engine.resolve(action, state, attempt)["role"] for attempt in range(6)]
        diagnose_at = int(
            self.policy["escalation"]["retries"]["diagnose_at"]
        )
        self.assertEqual(diagnose_at, 3)
        self.assertEqual(
            roles,
            [
                "diagnostician" if attempt == diagnose_at else "worker"
                for attempt in range(6)
            ],
        )

    def test_diagnostician_child_gets_evidence_index_without_changing_routing(self) -> None:
        self.selected_work_item()
        state = self.projected()
        message = self.host._host_message(
            self.root,
            host_test_helpers.PLUGIN,
            "billing",
            state["next_action"],
            {"role": "diagnostician"},
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
        self.assertFalse([argv for argv in commands(message) if argv[2] == "status"])

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


def commands(message: str) -> list[list[str]]:
    """Extract the concrete lifecycle CLI invocations a child is told to run."""
    found = []
    for inline in re.findall(r"`([^`]+)`", message):
        argv = shlex.split(inline)
        if len(argv) >= 3 and Path(argv[1]).resolve() == CLI.resolve():
            found.append(argv)
    return found


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
