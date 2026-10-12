#!/usr/bin/env python3
"""Hosted Goal/standalone Autopilot domain-ownership regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_autopilot as autopilot
import devflow_session as session


class HostedSessionLeaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name) / ".devflow/runtime/sample"

    def test_hosted_session_survives_short_lived_commands_and_blocks_standalone(self):
        first = session.start(self.runtime)
        owner = first["session_id"]
        self.assertEqual(session.status(self.runtime)["status"], "active")
        self.assertEqual(session.start(self.runtime, session_id=owner)["session_id"], owner)
        with self.assertRaisesRegex(session.SessionConflict, "another hosted Goal"):
            session.start(self.runtime)
        with self.assertRaisesRegex(session.SessionConflict, "hosted Goal session"):
            autopilot.DomainLease(self.runtime, 1).acquire()
        with self.assertRaisesRegex(session.SessionConflict, "owner does not match"):
            session.end(self.runtime, "another-owner")
        session.end(self.runtime, owner)
        with autopilot.DomainLease(self.runtime, 1) as lease:
            self.assertTrue(lease.acquired)

    def test_live_standalone_blocks_host_and_cannot_be_evicted(self):
        with autopilot.DomainLease(self.runtime, 2, owner="standalone") as lease:
            self.assertTrue(lease.path.is_file())
            with self.assertRaisesRegex(session.SessionConflict, "standalone Autopilot"):
                session.start(self.runtime)
            self.assertTrue(lease.path.is_file())
        owner = session.start(self.runtime)["session_id"]
        self.assertEqual(session.end(self.runtime, owner)["status"], "released")

    def test_stale_standalone_pid_slot_can_be_reclaimed(self):
        leases = self.runtime / "leases"
        leases.mkdir(parents=True, exist_ok=True)
        stale = leases / "mutating-99.lock"
        stale.write_text(json.dumps({"owner": "dead", "pid": -1}))
        owner = session.start(self.runtime)["session_id"]
        self.assertFalse(stale.exists())
        session.end(self.runtime, owner)

    def test_expired_host_owner_cannot_renew_or_release_new_owner(self):
        owner = session.start(self.runtime)["session_id"]
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at = 0 WHERE slot = 1")
        with self.assertRaisesRegex(session.SessionConflict, "expired"):
            session.require(self.runtime, owner)
        replacement = session.start(self.runtime)["session_id"]
        self.assertNotEqual(replacement, owner)
        with self.assertRaises(session.SessionConflict):
            session.end(self.runtime, owner)
        session.end(self.runtime, replacement)

    def test_cross_thread_start_is_atomic_and_only_one_owner_wins(self):
        def attempt(_):
            try:
                return session.start(self.runtime)["session_id"]
            except session.SessionConflict:
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            owners = list(executor.map(attempt, range(8)))
        winners = [owner for owner in owners if owner]
        self.assertEqual(len(winners), 1)
        session.end(self.runtime, winners[0])

    def test_session_ownership_is_durable_across_processes(self):
        code = (
            "import sys, devflow_session as session; from pathlib import Path; "
            "session.require(Path(sys.argv[1]), sys.argv[2])"
        )
        owner = session.start(self.runtime)["session_id"]
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + environment.get("PYTHONPATH", "")
        child = subprocess.run(
            [sys.executable, "-c", code, str(self.runtime), owner],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(session.status(self.runtime)["status"], "active")
        session.end(self.runtime, owner)
        denied = subprocess.run(
            [sys.executable, "-c", code, str(self.runtime), owner],
            env=environment, capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(denied.returncode, 0)

    def test_importlib_file_loader_finds_sibling_session_without_pythonpath(self):
        """The standalone routing test harness loads autopilot by filename."""
        code = (
            "import importlib.util,sys; "
            "spec=importlib.util.spec_from_file_location('isolated_autopilot', sys.argv[1]); "
            "module=importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(module); "
            "assert callable(module.DomainLease)"
        )
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        probe = subprocess.run(
            [sys.executable, "-c", code, str(SCRIPTS / "devflow_autopilot.py")],
            cwd=self.runtime.parent.parent.parent,
            env=environment, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_session_is_independent_per_domain(self):
        first = session.start(self.runtime)["session_id"]
        second_runtime = self.runtime.parent / "other"
        second = session.start(second_runtime)["session_id"]
        self.assertEqual(session.status(second_runtime)["status"], "active")
        session.end(self.runtime, first)
        self.assertEqual(session.status(second_runtime)["status"], "active")
        session.end(second_runtime, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
