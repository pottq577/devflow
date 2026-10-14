#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
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
        self.assertIsNone(result["scout"])
        self.assertIn("scout_message", result["primary"])

    def test_critical_architect_gets_scout_backed_specialist_message(self):
        state = {
            "risk_profile": "critical",
            "next_action": {
                "role": "architect",
                "command": "plan",
                "scope": "project",
            },
        }
        result = self.host.dispatch_envelope(
            Path("/repo"), PLUGIN, self.policy, "sample", state
        )
        self.assertEqual(result["scout"]["model_alias"], "balanced")
        self.assertEqual(result["scout"]["reasoning_effort"], "high")
        self.assertIn(
            "Do not repeat repository-wide discovery",
            result["primary"]["scout_message"],
        )
        self.assertIn(
            "Only if material evidence is missing or contradictory",
            result["primary"]["scout_message"],
        )
        self.assertIn(
            "Render the authoritative action packet", result["primary"]["message"]
        )

    def test_host_dispatch_adds_scout_only_after_retry_for_auditor(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "role": "auditor",
                "command": "audit",
                "scope": "phase",
                "mode": "initial",
                "phase": "01",
            },
        }
        first = self.host.dispatch_envelope(
            Path("/repo"), PLUGIN, self.policy, "sample", state, attempt=0
        )
        retry = self.host.dispatch_envelope(
            Path("/repo"), PLUGIN, self.policy, "sample", state, attempt=1
        )
        self.assertIsNone(first["scout"])
        self.assertEqual(retry["scout"]["model_alias"], "balanced")

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

    def test_final_worker_retry_routes_to_alternative_model(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "role": "executor",
                "command": "run",
                "scope": "phase",
                "phase": "01",
                "work_item": "P01-I01",
                "item_kind": "implementation",
                "item_risk": "medium",
            },
        }
        envelope = self.host.dispatch_envelope(
            Path("/repo"), PLUGIN, self.policy, "sample", state, attempt=5
        )
        self.assertEqual(envelope["attempt"], 5)
        self.assertEqual(envelope["primary"]["model_alias"], "balanced")
        self.assertEqual(envelope["primary"]["model"], "gpt-5.6-terra")
        self.assertEqual(envelope["primary"]["reasoning_effort"], "xhigh")
        self.assertIsNone(envelope["scout"])

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


class HostTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        initialized = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=self.root, text=True, capture_output=True,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.host = load_host()
        self.policy = self.host.autopilot.load_policy(PLUGIN, self.root)
        self.runtime = self.root / ".devflow/runtime/sample"
        self.owner = self.host.session.start(self.runtime)["session_id"]
        self.state = self.host._load_state(self.root, "sample")
        self.envelope = self.host.dispatch_envelope(
            self.root, PLUGIN, self.policy, "sample", self.state,
        )
        self.fingerprint = self.envelope["fingerprint"]
        self.log = self.runtime / "host-dispatch.jsonl"

    def call_host(self, *args):
        stdout = io.StringIO()
        with mock.patch.object(self.host.devflow, "repo_root", return_value=self.root), \
                mock.patch.object(sys, "argv", [str(HOST_SCRIPT), *args]), \
                contextlib.redirect_stdout(stdout):
            code = self.host.main()
        self.assertEqual(code, 0, stdout.getvalue())
        return json.loads(stdout.getvalue())

    def reserve(self, attempt=0):
        for retry in range(attempt + 1):
            self.envelope = self.host.dispatch_envelope(
                self.root, PLUGIN, self.policy, "sample", self.state, attempt=retry,
            )
            step = self.host.guard.begin(
                self.runtime, self.owner, self.fingerprint, self.policy,
                kind="primary", expected_attempt=retry,
                candidate_alias=self.envelope["primary"]["model_alias"],
            )
            if retry < attempt:
                self.host.guard.finish(
                    self.runtime, self.owner, step["step_id"], self.fingerprint,
                    self.policy, outcome="failed",
                )
        self.step_id = step["step_id"]
        return [
            "telemetry-start", "sample", "--kind", "primary", "--attempt", str(attempt),
            "--session-id", self.owner, "--step-id", self.step_id,
        ]

    def snapshot(self):
        return (
            (self.root / "docs/domains/sample/STATE.yaml").read_bytes(),
            self.host.guard.inspect(self.runtime, self.owner, self.fingerprint, self.policy),
        )

    def test_attempt_zero_one_three_five_record_actual_reserved_routes(self):
        original_state = self.snapshot()[0]
        recorded_attempts = []
        for attempt in range(6):
            envelope = self.host.dispatch_envelope(
                self.root, PLUGIN, self.policy, "sample", self.state, attempt=attempt,
            )
            step = self.host.guard.begin(
                self.runtime, self.owner, self.fingerprint, self.policy,
                kind="primary", expected_attempt=attempt,
                candidate_alias=envelope["primary"]["model_alias"],
            )
            before = self.snapshot()
            if attempt in {0, 1, 3, 5}:
                started = self.call_host(
                    "telemetry-start", "sample", "--kind", "primary", "--attempt", str(attempt),
                    "--session-id", self.owner, "--step-id", step["step_id"],
                )
                self.assertEqual(started["status"], "started")
                finished = self.call_host(
                    "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
                    "--session-id", self.owner, "--step-id", step["step_id"], "--outcome", "failed",
                )
                self.assertEqual(finished["status"], "recorded")
                rows = [json.loads(line) for line in self.log.read_text().splitlines()][-2:]
                self.assertEqual([row["event"] for row in rows], ["start", "finish"])
                for row in rows:
                    self.assertEqual(row["attempt"], attempt)
                    self.assertEqual(row["schema_version"], 3)
                    self.assertEqual(row["model_alias"], envelope["primary"]["model_alias"])
                    self.assertEqual(row["model"], envelope["primary"]["model"])
                    self.assertEqual(row["token_usage"], "unmeasured")
                    self.assertEqual(row["observations"]["source"], "caller_reported")
                    self.assertEqual(row["observations"]["context_bytes"], {
                        "packet": None, "protocol": None, "capsule": None,
                    })
                    durations = row["observations"]["stage_duration_seconds"]
                    self.assertEqual({key: durations[key] for key in ("packet_render", "spawn", "child_wait")}, {
                        "packet_render": None, "spawn": None, "child_wait": None,
                    })
                    self.assertGreaterEqual(durations["telemetry_prepare"], 0)
                self.assertEqual(rows[1]["outcome"], "failed")
                self.assertGreaterEqual(rows[1]["duration_seconds"], 0)
                recorded_attempts.append(attempt)
                self.assertEqual(self.snapshot(), before)
            acknowledgement = self.host.guard.finish(
                self.runtime, self.owner, step["step_id"], self.fingerprint,
                self.policy, outcome="failed",
            )
            self.assertEqual(acknowledgement["attempt"], attempt + 1)
        self.assertEqual(recorded_attempts, [0, 1, 3, 5])
        self.assertEqual(self.snapshot()[0], original_state)

    def test_rejected_start_and_finish_leave_state_and_reservation_unchanged(self):
        args = self.reserve(attempt=1)
        before = self.snapshot()
        for field, value, reason in (
            ("--attempt", None, "telemetry_attempt_missing"),
            ("--attempt", "0", "hosted_telemetry_step_mismatch"),
            ("--session-id", "wrong", "telemetry_error"),
            ("--step-id", "wrong", "hosted_telemetry_step_mismatch"),
        ):
            with self.subTest(field=field, value=value):
                invalid = args.copy()
                index = invalid.index(field)
                if value is None:
                    del invalid[index:index + 2]
                else:
                    invalid[index + 1] = value
                result = self.call_host(*invalid)
                self.assertEqual(result["status"], "telemetry_unavailable")
                self.assertEqual(result["reason"], reason)
                self.assertIsInstance(result["error"], str)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.log.exists())
        started = self.call_host(*args)
        self.assertEqual(started["status"], "started")
        log_before = self.log.read_bytes()
        inflight = self.host._telemetry_inflight_path(self.root, "sample", started["dispatch_id"])
        inflight_before = inflight.read_bytes()
        for owner, step in (("wrong", self.step_id), (self.owner, "wrong")):
            with self.subTest(owner=owner, step=step):
                result = self.call_host(
                    "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
                    "--session-id", owner, "--step-id", step, "--outcome", "completed",
                )
                self.assertEqual(result["status"], "telemetry_unavailable")
                self.assertEqual(result["reason"], "telemetry_error")
                self.assertEqual(self.log.read_bytes(), log_before)
                self.assertEqual(inflight.read_bytes(), inflight_before)
                self.assertEqual(self.snapshot(), before)

    def test_caller_observations_merge_only_supplied_fields(self):
        args = self.reserve()
        observation_file = self.root / "observations.json"
        observation_file.write_text(json.dumps({
            "context_bytes": {"packet": len("한글".encode("utf-8")), "capsule": 0},
            "stage_duration_seconds": {"packet_render": 0.2, "spawn": 0, "child_wait": None},
            "source": "caller_reported",
        }), encoding="utf-8")
        started = self.call_host(*args, "--observations-file", str(observation_file))
        self.assertEqual(started["status"], "started")
        before = self.snapshot()
        observation_file.write_text(json.dumps({
            "context_bytes": {"protocol": 123}, "stage_duration_seconds": {"child_wait": 1.25},
        }), encoding="utf-8")
        finished = self.call_host(
            "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
            "--session-id", self.owner, "--step-id", self.step_id, "--outcome", "completed",
            "--observations-file", str(observation_file),
        )
        self.assertEqual(finished["status"], "recorded")
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertIsNone(rows[0]["observations"]["context_bytes"]["protocol"])
        self.assertEqual(rows[1]["observations"]["context_bytes"], {
            "packet": 6, "protocol": 123, "capsule": 0,
        })
        durations = rows[1]["observations"]["stage_duration_seconds"]
        self.assertEqual({key: durations[key] for key in ("packet_render", "spawn", "child_wait")}, {
            "packet_render": 0.2, "spawn": 0, "child_wait": 1.25,
        })
        self.assertEqual(rows[1]["token_usage"], "unmeasured")
        self.assertEqual(self.snapshot(), before)

    def test_explicit_null_observations_replace_values_and_omitted_fields_remain(self):
        args = self.reserve()
        observation_file = self.root / "observations.json"
        observation_file.write_text(json.dumps({
            "context_bytes": {"packet": 32, "protocol": 24},
            "stage_duration_seconds": {"spawn": 0.1, "packet_render": 0.5},
        }), encoding="utf-8")
        started = self.call_host(*args, "--observations-file", str(observation_file))
        self.assertEqual(started["status"], "started")
        observation_file.write_text(json.dumps({
            "context_bytes": {"packet": None}, "stage_duration_seconds": {"spawn": None},
        }), encoding="utf-8")
        finished = self.call_host(
            "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
            "--session-id", self.owner, "--step-id", self.step_id, "--outcome", "completed",
            "--observations-file", str(observation_file),
        )
        self.assertEqual(finished["status"], "recorded")
        observations = json.loads(self.log.read_text().splitlines()[-1])["observations"]
        self.assertIsNone(observations["context_bytes"]["packet"])
        self.assertEqual(observations["context_bytes"]["protocol"], 24)
        self.assertIsNone(observations["stage_duration_seconds"]["spawn"])
        self.assertEqual(observations["stage_duration_seconds"]["packet_render"], 0.5)

    def test_invalid_observations_are_fail_open_without_log_or_guard_changes(self):
        args = self.reserve()
        started = self.call_host(*args)
        self.assertEqual(started["status"], "started")
        finish_args = [
            "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
            "--session-id", self.owner, "--step-id", self.step_id, "--outcome", "failed",
        ]
        before = self.snapshot()
        log_before = self.log.read_bytes()
        inflight = self.host._telemetry_inflight_path(self.root, "sample", started["dispatch_id"])
        inflight_before = inflight.read_bytes()
        invalid = [
            [], {"unknown": 1}, {"source": "runtime_measured"},
            {"context_bytes": []}, {"context_bytes": {"unknown": 1}},
            {"stage_duration_seconds": {"telemetry_prepare": 0}},
        ]
        invalid.extend({"context_bytes": {"packet": value}} for value in (True, -1, 1.5, "1"))
        invalid.extend({"stage_duration_seconds": {"spawn": value}} for value in (
            False, -0.1, float("nan"), float("inf"), "1",
        ))
        raw_inputs = [json.dumps(value) for value in invalid] + [
            "{", " " * (64 * 1024 + 1),
            '{"source":"runtime_measured","source":"caller_reported"}',
            '{"context_bytes":{"packet":-1,"packet":6}}',
        ]
        observation_file = self.root / "observations.json"
        for command in (args, finish_args):
            for raw in raw_inputs:
                with self.subTest(command=command[0], raw=raw[:80]):
                    observation_file.write_text(raw, encoding="utf-8")
                    result = self.call_host(*command, "--observations-file", str(observation_file))
                    self.assertEqual(result["status"], "telemetry_unavailable")
                    self.assertEqual(result["reason"], "telemetry_error")
                    self.assertIsInstance(result["error"], str)
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(self.log.read_bytes(), log_before)
                    self.assertEqual(inflight.read_bytes(), inflight_before)

    def test_telemetry_write_failures_preserve_execution_and_can_be_retried(self):
        args = self.reserve()
        before = self.snapshot()
        with mock.patch.object(self.host, "_append_telemetry", side_effect=PermissionError("read only telemetry")):
            failed_start = self.call_host(*args)
        self.assertEqual(failed_start["status"], "telemetry_unavailable")
        self.assertEqual(failed_start["reason"], "telemetry_error")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.log.exists())
        started = self.call_host(*args)
        self.assertEqual(started["status"], "started")
        finish_args = [
            "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
            "--session-id", self.owner, "--step-id", self.step_id, "--outcome", "failed",
        ]
        inflight = self.host._telemetry_inflight_path(self.root, "sample", started["dispatch_id"])
        inflight_before = inflight.read_bytes()
        log_before = self.log.read_bytes()
        with mock.patch.object(self.host, "_append_telemetry", side_effect=PermissionError("read only telemetry")):
            failed_finish = self.call_host(*finish_args)
        self.assertEqual(failed_finish["status"], "telemetry_unavailable")
        self.assertEqual(failed_finish["reason"], "telemetry_error")
        self.assertEqual(inflight.read_bytes(), inflight_before)
        self.assertEqual(self.log.read_bytes(), log_before)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.call_host(*finish_args)["status"], "recorded")
        self.assertEqual(self.snapshot(), before)
        acknowledgement = self.host.guard.finish(
            self.runtime, self.owner, self.step_id, self.fingerprint,
            self.policy, outcome="failed",
        )
        self.assertEqual(acknowledgement["attempt"], 1)
        self.assertEqual(acknowledgement["outcome"], "failed")

    def test_version_two_inflight_and_old_log_are_preserved(self):
        args = self.reserve()
        started = self.call_host(*args)
        self.assertEqual(started["status"], "started")
        inflight = self.host._telemetry_inflight_path(self.root, "sample", started["dispatch_id"])
        legacy = json.loads(inflight.read_text())
        legacy["schema_version"] = 2
        legacy.pop("token_usage")
        legacy.pop("observations")
        inflight.write_text(json.dumps(legacy), encoding="utf-8")
        old_records = [
            {"schema_version": 1, "event": "finish", "dispatch_id": "1" * 24, "duration_seconds": 0.5},
            {"event": "start", **{key: value for key, value in legacy.items() if key != "started_epoch"}},
        ]
        self.log.write_text("".join(json.dumps(row) + "\n" for row in old_records), encoding="utf-8")
        before = self.snapshot()
        old_log = self.log.read_bytes()
        legacy_bytes = inflight.read_bytes()
        finish_args = [
            "telemetry-finish", "sample", "--dispatch-id", started["dispatch_id"],
            "--session-id", self.owner, "--step-id", self.step_id, "--outcome", "completed",
        ]
        observation_file = self.root / "observations.json"
        observation_file.write_text("{}", encoding="utf-8")
        unavailable = self.call_host(*finish_args, "--observations-file", str(observation_file))
        self.assertEqual(unavailable["status"], "telemetry_unavailable")
        self.assertEqual(unavailable["reason"], "telemetry_error")
        self.assertEqual(self.log.read_bytes(), old_log)
        self.assertEqual(inflight.read_bytes(), legacy_bytes)
        finished = self.call_host(*finish_args)
        self.assertEqual(finished["status"], "recorded")
        self.assertTrue(self.log.read_bytes().startswith(old_log))
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(rows[:2], old_records)
        self.assertEqual(rows[2]["schema_version"], 2)
        for key, value in legacy.items():
            if key != "started_epoch":
                self.assertEqual(rows[2][key], value)
        self.assertNotIn("token_usage", rows[2])
        self.assertNotIn("observations", rows[2])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(inflight.exists())

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
        session_result = self.run_host(root, "session-start", "sample")
        self.assertEqual(session_result.returncode, 0, session_result.stderr)
        owner = json.loads(session_result.stdout)["session_id"]
        dispatched = self.run_host(
            root, "dispatch", "sample", "--session-id", owner, env=env
        )
        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        result = json.loads(dispatched.stdout)
        self.assertEqual(result["status"], "dispatch_required")
        self.assertEqual(
            result["primary"]["route"]["execution"]["backend"],
            "host_native_agent",
        )

    def test_host_dispatch_telemetry_records_completed_primary(self):
        root = self.new_repo()
        initialized = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)

        acquired = self.run_host(root, "session-start", "sample")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        owner = json.loads(acquired.stdout)["session_id"]
        envelope = json.loads(self.run_host(
            root, "dispatch", "sample", "--session-id", owner
        ).stdout)
        reserved = self.run_host(
            root, "step-start", "sample", "--session-id", owner,
            "--kind", "primary", "--fingerprint", envelope["fingerprint"],
            "--candidate-alias", envelope["primary"]["model_alias"],
            "--attempt", "0",
        )
        self.assertEqual(reserved.returncode, 0, reserved.stderr)
        step_id = json.loads(reserved.stdout)["step_id"]
        started = self.run_host(
            root, "telemetry-start", "sample", "--kind", "primary",
            "--attempt", "0", "--session-id", owner, "--step-id", step_id,
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        start_result = json.loads(started.stdout)
        self.assertEqual(start_result["status"], "started")
        dispatch_id = start_result["dispatch_id"]
        self.assertRegex(dispatch_id, r"^[0-9a-f]{24}$")
        unauthorized = self.run_host(
            root, "telemetry-start", "sample", "--kind", "primary",
            "--session-id", owner, "--step-id", "wrong",
        )
        self.assertEqual(unauthorized.returncode, 0, unauthorized.stderr)
        self.assertEqual(json.loads(unauthorized.stdout)["status"], "telemetry_unavailable")
        # Rejected telemetry must not append a second start event.
        telemetry = root / ".devflow/runtime/sample/host-dispatch.jsonl"
        self.assertEqual(len(telemetry.read_text(encoding="utf-8").splitlines()), 1)

        finished = self.run_host(
            root,
            "telemetry-finish",
            "sample",
            "--dispatch-id", dispatch_id, "--session-id", owner,
            "--step-id", step_id,
            "--outcome", "completed",
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        finish_result = json.loads(finished.stdout)
        self.assertEqual(finish_result["status"], "recorded")
        self.assertGreaterEqual(finish_result["duration_seconds"], 0)

        telemetry_path = root / ".devflow/runtime/sample/host-dispatch.jsonl"
        records = [
            json.loads(line)
            for line in telemetry_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual([row["event"] for row in records], ["start", "finish"])
        self.assertEqual(records[0]["dispatch_id"], dispatch_id)
        self.assertEqual(records[1]["dispatch_id"], dispatch_id)
        self.assertEqual(records[1]["outcome"], "completed")
        self.assertEqual(records[0]["step_id"], step_id)
        self.assertEqual(records[1]["step_id"], step_id)
        self.assertEqual(records[0]["schema_version"], 3)
        self.assertGreaterEqual(records[1]["duration_seconds"], 0)
        ack = self.run_host(
            root, "step-finish", "sample", "--session-id", owner,
            "--step-id", step_id, "--outcome", "completed",
        )
        self.assertEqual(ack.returncode, 0, ack.stderr)
        self.assertTrue(records[0]["model_alias"])
        self.assertTrue(records[0]["model"])
        self.assertTrue(records[0]["reasoning_effort"])

    def test_telemetry_start_without_attempt_is_unavailable_at_attempt_zero(self):
        root = self.new_repo()
        initialized = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        acquired = self.run_host(root, "session-start", "sample")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        owner = json.loads(acquired.stdout)["session_id"]
        dispatched = self.run_host(root, "dispatch", "sample", "--session-id", owner)
        self.assertEqual(dispatched.returncode, 0, dispatched.stderr)
        envelope = json.loads(dispatched.stdout)
        reserved = self.run_host(
            root, "step-start", "sample", "--session-id", owner,
            "--kind", "primary", "--fingerprint", envelope["fingerprint"],
            "--candidate-alias", envelope["primary"]["model_alias"], "--attempt", "0",
        )
        self.assertEqual(reserved.returncode, 0, reserved.stderr)
        step_id = json.loads(reserved.stdout)["step_id"]
        result = self.run_host(
            root, "telemetry-start", "sample", "--kind", "primary",
            "--session-id", owner, "--step-id", step_id,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "telemetry_unavailable")
        self.assertEqual(payload["reason"], "telemetry_attempt_missing")
        self.assertIsInstance(payload["error"], str)
        self.assertFalse((root / ".devflow/runtime/sample/host-dispatch.jsonl").exists())

    def test_telemetry_failure_does_not_block_lifecycle(self):
        root = self.new_repo()
        result = self.run_host(
            root,
            "telemetry-finish",
            "sample",
            "--dispatch-id",
            "0" * 24,
            "--outcome",
            "failed",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "telemetry_unavailable")

    def test_bootstrap_is_host_dispatched_then_finalized_locally(self):
        root = self.new_repo()
        requirements = root / "requirements.md"
        requirements.write_text(
            "Build a routed autonomous workflow.\n", encoding="utf-8"
        )

        session_result = self.run_host(root, "session-start", "sample")
        self.assertEqual(session_result.returncode, 0, session_result.stderr)
        owner = json.loads(session_result.stdout)["session_id"]
        prepared = self.run_host(
            root,
            "bootstrap",
            "sample",
            "--session-id",
            owner,
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
        finalized = self.run_host(
            root, "bootstrap-finalize", "sample", "--session-id", owner
        )
        self.assertEqual(finalized.returncode, 0, finalized.stderr + finalized.stdout)
        result = json.loads(finalized.stdout)
        self.assertEqual(result["status"], "initialized")
        self.assertTrue((root / "docs/domains/sample/STATE.yaml").exists())

    def test_cli_session_prevents_unauthorized_dispatch_and_standalone_start(self):
        root = self.new_repo()
        initialized = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(self.run_host(root, "dispatch", "sample").returncode, 2)
        acquired = self.run_host(root, "session-start", "sample")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        owner = json.loads(acquired.stdout)["session_id"]
        self.assertEqual(self.run_host(root, "session-start", "sample").returncode, 2)
        self.assertEqual(self.run_host(root, "dispatch", "sample", "--session-id", "wrong").returncode, 2)
        permitted = self.run_host(root, "dispatch", "sample", "--session-id", owner)
        self.assertEqual(permitted.returncode, 0, permitted.stderr)
        blocked = subprocess.run(
            [sys.executable, str(CLI), "autopilot", "start", "sample", "--max-steps", "1"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertEqual(json.loads(blocked.stdout)["reason"], "hosted_goal_session_active")
        released = self.run_host(root, "session-end", "sample", "--session-id", owner)
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(json.loads(released.stdout)["status"], "released")

    def test_hosted_session_blocks_standalone_bootstrap_before_init(self):
        root = self.new_repo()
        requirements = root / "requirements.md"
        requirements.write_text("A new hosted domain must be exclusive.\n")
        acquired = self.run_host(root, "session-start", "sample")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        owner = json.loads(acquired.stdout)["session_id"]
        blocked = subprocess.run(
            [sys.executable, str(CLI), "autopilot", "bootstrap", "sample",
             "--requirements-file", str(requirements)],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertEqual(json.loads(blocked.stdout)["reason"], "hosted_goal_session_active")
        self.assertFalse((root / "docs/domains/sample/STATE.yaml").exists())
        released = self.run_host(root, "session-end", "sample", "--session-id", owner)
        self.assertEqual(released.returncode, 0, released.stderr)

    def test_cli_guard_requires_reserved_and_acknowledged_primary(self):
        root = self.new_repo()
        initialized = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=root, text=True, capture_output=True,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        acquired = self.run_host(root, "session-start", "sample")
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        owner = json.loads(acquired.stdout)["session_id"]

        preview = self.run_host(root, "dispatch", "sample", "--session-id", owner)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        envelope = json.loads(preview.stdout)
        self.assertEqual(envelope["safety"]["steps_completed"], 0)
        self.assertEqual(envelope["attempt"], 0)
        second_preview = self.run_host(root, "dispatch", "sample", "--session-id", owner)
        self.assertEqual(json.loads(second_preview.stdout)["safety"]["steps_completed"], 0)

        started = self.run_host(
            root, "step-start", "sample", "--session-id", owner,
            "--kind", "primary", "--fingerprint", envelope["fingerprint"],
            "--candidate-alias", envelope["primary"]["model_alias"],
            "--attempt", "0",
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        step = json.loads(started.stdout)
        self.assertEqual(step["steps_completed"], 1)
        blocked = self.run_host(root, "dispatch", "sample", "--session-id", owner)
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertEqual(json.loads(blocked.stdout)["reason"], "hosted_step_inflight")
        premature = self.run_host(root, "session-end", "sample", "--session-id", owner)
        self.assertEqual(premature.returncode, 1, premature.stderr)

        finished = self.run_host(
            root, "step-finish", "sample", "--session-id", owner,
            "--step-id", step["step_id"], "--outcome", "completed",
        )
        self.assertEqual(finished.returncode, 0, finished.stderr)
        self.assertFalse(json.loads(finished.stdout)["progressed"])
        resumed = self.run_host(root, "session-start", "sample", "--session-id", owner)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        after = self.run_host(root, "dispatch", "sample", "--session-id", owner)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(json.loads(after.stdout)["attempt"], 1)
        stale = self.run_host(root, "dispatch", "sample", "--session-id", owner, "--attempt", "0")
        self.assertEqual(stale.returncode, 1, stale.stderr)
        self.assertEqual(json.loads(stale.stdout)["reason"], "hosted_stale_attempt")
        self.assertEqual(
            self.run_host(root, "session-end", "sample", "--session-id", owner).returncode,
            0,
        )

    def test_scout_validation_is_fingerprint_bound_and_read_only(self):
        root = self.new_repo()
        init = subprocess.run(
            [sys.executable, str(CLI), "init", "sample"],
            cwd=root, capture_output=True, text=True,
        )
        self.assertEqual(init.returncode, 0, init.stderr)
        acquired = self.run_host(root, "session-start", "sample")
        owner = json.loads(acquired.stdout)["session_id"]
        envelope = json.loads(self.run_host(root, "dispatch", "sample", "--session-id", owner).stdout)
        folder = root / ".devflow/runtime/sample/scout-capsules"
        folder.mkdir(parents=True)
        path = folder / "scout.txt"
        path.write_text("bad narrative", encoding="utf-8")
        invalid = self.run_host(
            root, "scout-validate", "sample", "--session-id", owner,
            "--fingerprint", envelope["fingerprint"], "--capsule-file", str(path),
        )
        self.assertEqual(invalid.returncode, 0, invalid.stderr)
        self.assertEqual(json.loads(invalid.stdout)["status"], "invalid")
        stale = self.run_host(
            root, "scout-validate", "sample", "--session-id", owner,
            "--fingerprint", "wrong", "--capsule-file", str(path),
        )
        self.assertEqual(stale.returncode, 1, stale.stderr)
        self.assertEqual(json.loads(stale.stdout)["reason"], "hosted_stale_fingerprint")

    def test_goal_skill_prefers_host_native_subagents(self):
        text = (PLUGIN / "skills" / "goal" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("session-start", text)
        self.assertIn("session-end", text)
        self.assertIn("--session-id", text)
        self.assertIn("spawn_agent", text)
        self.assertIn("host.py dispatch", text)
        self.assertIn('fork_turns="none"', text)
        self.assertIn("Do not launch a nested `codex exec`", text)
        self.assertIn("autopilot bootstrap", text)
        self.assertIn("telemetry-start", text)
        self.assertIn("telemetry-finish", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
