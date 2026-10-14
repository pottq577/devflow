#!/usr/bin/env python3
"""A failed or malformed CLI sample must never become a benchmark success."""

from pathlib import Path
import tempfile
import unittest

import benchmark_helpers as bench
import bench_goal_lifecycle as lifecycle


class BenchmarkMeasurementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.script = self.root / "command.py"

    def measure(self, source, **kwargs):
        self.script.write_text(source, encoding="utf-8")
        return bench.time_command(
            self.root, [], script=self.script, reps=2, **kwargs
        )

    def test_nonzero_sample_is_refused_with_exit_code(self):
        with self.assertRaisesRegex(bench.BenchError, "got 9"):
            self.measure("import sys; sys.exit(9)")

    def test_json_keys_require_an_object_not_a_list_of_key_names(self):
        with self.assertRaisesRegex(bench.BenchError, "JSON.*object"):
            self.measure('print(\'["status", "fingerprint"]\')',
                         json_keys=("status", "fingerprint"))

    def test_each_json_sample_must_match_the_expected_next_action(self):
        source = (
            "import json\nfrom pathlib import Path\n"
            "counter = Path('counter')\n"
            "number = int(counter.read_text()) if counter.exists() else 0\n"
            "counter.write_text(str(number + 1))\n"
            "print(json.dumps({'next_action': {'command': "
            "'run' if number == 0 else 'audit', 'work_item': 'P01-I01'}}))\n"
        )
        with self.assertRaisesRegex(bench.BenchError, "next_action.command.*audit"):
            self.measure(source, json_keys=("next_action",),
                         json_values={"next_action.command": "run",
                                      "next_action.work_item": "P01-I01"})

    def test_null_next_action_is_refused_instead_of_measured(self):
        with self.assertRaisesRegex(bench.BenchError, "next_action.command"):
            self.measure('print(\'{"next_action": null}\')',
                         json_values={"next_action.command": "run"})

    def test_success_preserves_every_raw_elapsed_and_output_size_sample(self):
        row = self.measure('print("한글")')
        recorded = row.as_dict()
        self.assertEqual(recorded["exit_codes"], [0, 0])
        self.assertEqual(recorded["stdout_bytes_samples"], [7, 7])
        samples = recorded["elapsed_ms_samples"]
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(value > 0 for value in samples))
        self.assertEqual(recorded["p50_ms"], round(sum(samples) / 2, 2))
        self.assertEqual(recorded["p95_ms"], round(max(samples), 2))

    def test_empty_sample_set_is_refused_explicitly(self):
        self.script.write_text('print("ok")', encoding="utf-8")
        with self.assertRaisesRegex(bench.BenchError, "reps.*positive"):
            bench.time_command(self.root, [], script=self.script, reps=0)

    def test_hung_command_is_terminated_and_never_measured(self):
        self.script.write_text("import time; time.sleep(30)", encoding="utf-8")
        with self.assertRaisesRegex(bench.BenchError, "timed out"):
            bench.time_command(self.root, [], script=self.script, reps=1,
                               timeout_seconds=0.02)


class LifecycleBenchmarkFixtureTests(unittest.TestCase):
    def test_committed_sources_and_tamper_refusals_use_real_runtime(self):
        with tempfile.TemporaryDirectory(prefix="devflow-bench-test-") as directory:
            lifecycle.sandbox_root = Path(directory)
            rows, checks = lifecycle.section_integrity(1)
            self.assertTrue(rows)
            self.assertTrue(all(check["passed"] for check in checks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
