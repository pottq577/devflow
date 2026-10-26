#!/usr/bin/env python3
"""Read-only hosted/suite efficiency analytics with bounded and truthful claims."""
from __future__ import annotations

import contextlib
import io
import json

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import devflow_efficiency as efficiency


class EfficiencyReportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="devflow-efficiency-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def record(self, kind="finish", dispatch_id="a" * 24, *, attempt=0, duration=4.5,
               outcome="completed", role="worker", alias="balanced", legacy=False,
               wait=2.1, packet=4000):
        row = {
            "schema_version": 2 if legacy else 3,
            "event": kind,
            "dispatch_id": dispatch_id,
            "step_id": "b" * 32,
            "fingerprint": "f" * 64,
            "dispatch_kind": "primary",
            "attempt": attempt,
            "task_name": "ignored-private-task-name",
            "role": role,
            "model_alias": alias,
            "model": "gpt-6-luna",
            "reasoning_effort": "high",
            "action": {"command": "run", "work_item": "P01-I01"},
            "started_at": "2026-10-26T00:00:00Z",
            "token_usage": "unmeasured",
        }
        if not legacy:
            row["observations"] = {"source": "caller_reported",
                                   "context_bytes": {"packet": packet},
                                   "stage_duration_seconds": {"child_wait": wait}}
        if kind == "finish":
            row.update(outcome=outcome, finished_at="2026-10-26T00:00:04Z",
                       duration_seconds=duration)
        return row

    def data(self, *rows):
        return ("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8")

    def suite(self, *, partial=False):
        return json.dumps({
            "schema_version": 1, "profile": "full", "complete": not partial,
            "selected": 3, "run": 3, "passed": 2,
            "tests": [
                {"id": "test_alpha.Case.test_ok", "status": "passed", "seconds": 2.0},
                {"id": "test_beta.Case.test_fail", "status": "failed", "seconds": 7.5},
                {"id": "test_gamma.Case.test_ok", "status": "passed", "seconds": 4.0},
            ],
        }).encode("utf-8")

    def test_grouped_counts_are_observations_not_model_quality_or_tokens(self):
        records = self.data(
            self.record("start"), self.record(),
            self.record("start", "c" * 24, attempt=1),
            self.record("finish", "c" * 24, attempt=1, outcome="failed", duration=6.0,
                        wait=None, packet=None),
            self.record("start", "d" * 24, role="auditor", alias="frontier"),
            self.record("finish", "d" * 24, role="auditor", alias="frontier", duration=1.0),
        )
        result = efficiency.report(telemetry=records)
        hosted = result["hosted"]
        self.assertEqual(hosted["finished"], 3)
        self.assertEqual(hosted["outcomes"]["failed"], 1)
        self.assertEqual(hosted["retry_attempts"], 1)
        self.assertEqual(hosted["wall_seconds"], 11.5)
        self.assertEqual(hosted["observed_child_wait"], {"count": 2, "seconds": 4.2})
        self.assertEqual(hosted["observed_packet_bytes"], {"count": 2, "sum": 8000})
        self.assertEqual(hosted["token_usage"], "unmeasured")
        self.assertNotIn("task_name", json.dumps(result))
        self.assertEqual(hosted["groups"][0]["role"], "worker")

    def test_legacy_v2_remains_unmeasured(self):
        data = self.data(self.record("start", legacy=True), self.record(legacy=True))
        report = efficiency.read_hosted(data)
        self.assertEqual(report["observed_child_wait"]["count"], 0)
        self.assertEqual(report["observed_packet_bytes"]["count"], 0)

    def test_orphan_start_is_unknown_not_failed_or_live(self):
        r = efficiency.read_hosted(self.data(self.record("start")))
        self.assertEqual(r["finished"], 0)
        self.assertEqual(r["unconfirmed_starts"], 1)
        self.assertEqual(r["outcomes"]["failed"], 0)

    def test_orphan_finish_is_counted_but_observation_gap_visible(self):
        r = efficiency.read_hosted(self.data(self.record()))
        self.assertEqual(r["finished"], 1)
        self.assertEqual(r["unmatched_finishes"], 1)

    def test_duplicate_and_inconsistent_events_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "duplicate telemetry"):
            efficiency.read_hosted(self.data(self.record(), self.record()))
        with self.assertRaisesRegex(ValueError, "mismatch"):
            efficiency.read_hosted(self.data(self.record("start"),
                                             self.record(role="auditor")))
        with self.assertRaisesRegex(ValueError, "invalid UTF-8 JSON"):
            efficiency.read_hosted(b'{"schema_version":3,"schema_version":3,"event":"start"}\n')
        with self.assertRaisesRegex(ValueError, "unknown token"):
            bad = self.record()
            bad["token_usage"] = 5000
            efficiency.read_hosted(self.data(bad))

    def test_invalid_numeric_observations_rejected(self):
        for value in (True, -1, float("nan"), "4.0"):
            bad = self.record()
            bad["observations"]["stage_duration_seconds"]["child_wait"] = value
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                efficiency.read_hosted(self.data(bad))

    def test_suite_slowest_and_partial_are_not_release_evidence(self):
        summary = efficiency.read_suite(self.suite(partial=True))
        self.assertEqual(summary["scope"], "partial")
        self.assertEqual(summary["nonpassing"], 1)
        self.assertEqual(summary["slowest"][0]["id"], "test_beta.Case.test_fail")
        self.assertEqual(summary["authority"], "historical_test_evidence_only")
        self.assertEqual(efficiency.read_suite(self.suite())["scope"], "full")

    def test_corrupt_suite_and_duplicate_test_id_rejected(self):
        data = json.loads(self.suite())
        data["run"] = 999
        with self.assertRaisesRegex(ValueError, "row count"):
            efficiency.read_suite(json.dumps(data).encode())
        data["run"] = 3
        data["tests"][1]["id"] = data["tests"][0]["id"]
        with self.assertRaisesRegex(ValueError, "duplicate suite"):
            efficiency.read_suite(json.dumps(data).encode())

    def test_missing_domain_and_suite_only_do_not_create_files(self):
        stdout = io.StringIO()
        domain_path = self.root / ".devflow/runtime/attendance"
        with contextlib.redirect_stdout(stdout):
            exit_code = efficiency.main(["--domain", "attendance", "--repo-root", str(self.root)])
        self.assertEqual(exit_code, 0)
        self.assertFalse(domain_path.exists())
        self.assertEqual(json.loads(stdout.getvalue())["hosted"]["source"], "absent")
        path = self.root / "suite.json"
        path.write_bytes(self.suite())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = efficiency.main(["--suite", str(path)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["suite"]["run"], 3)

    def test_symlink_and_oversized_input_are_rejected(self):
        actual = self.root / "real.jsonl"
        actual.write_bytes(self.data(self.record()))
        link = self.root / "fake.jsonl"
        try:
            link.symlink_to(actual)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaisesRegex(ValueError, "nonsymlinked"):
            efficiency._read(link)
        with mock.patch.object(efficiency, "MAX_INPUT", 12):
            with self.assertRaisesRegex(ValueError, "16 MiB input limit"):
                efficiency._read(actual)

    def test_output_is_bounded_with_many_groups_and_slow_tests(self):
        rows = []
        for index in range(80):
            dispatch_id = format(index, "024x")
            rows.extend([
                self.record("start", dispatch_id, role=f"role_{index}", alias=f"alias_{index}"),
                self.record("finish", dispatch_id, role=f"role_{index}", alias=f"alias_{index}"),
            ])
        result = efficiency.report(telemetry=self.data(*rows), suite=self.suite())
        raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(raw), efficiency.MAX_OUTPUT)
        self.assertEqual(result["hosted"]["groups_omitted"], 80 - efficiency.MAX_GROUPS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
