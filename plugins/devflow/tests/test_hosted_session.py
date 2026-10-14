#!/usr/bin/env python3
"""Hosted Goal/standalone Autopilot domain-ownership regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import devflow_autopilot as autopilot
import devflow_host_guard as guard
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

    def test_expired_or_orphan_pending_blocks_hosted_and_standalone(self):
        owner = session.start(self.runtime)["session_id"]
        step = guard.begin(self.runtime, owner, "a", {}, kind="primary", expected_attempt=0, candidate_alias="fast")
        for orphan in (False, True):
            with self.subTest(orphan=orphan):
                with session.coordinator(self.runtime) as connection:
                    if orphan:
                        connection.execute("DELETE FROM hosted_session")
                    else:
                        connection.execute("UPDATE hosted_session SET expires_at=0")
                    before = list(connection.iterdump())
                for attempted_owner in (None, owner, "foreign"):
                    with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
                        session.start(self.runtime, session_id=attempted_owner)
                with self.assertRaises(session.SessionConflict):
                    autopilot.DomainLease(self.runtime, 1).acquire()
                self.assertEqual(session.status(self.runtime)["status"], "blocked")
                with session.coordinator(self.runtime) as connection:
                    self.assertEqual(list(connection.iterdump()), before)
                    self.assertEqual(session.read_progress(connection)[1]["inflight"]["step_id"], step["step_id"])

    def test_active_owner_heartbeat_keeps_pending_child_fenced(self):
        owner = session.start(self.runtime)["session_id"]
        guard.begin(self.runtime, owner, "a", {}, kind="primary", expected_attempt=0, candidate_alias="fast")
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=expires_at-3600")
        old_expiry = session.status(self.runtime)["expires_at"]
        self.assertGreater(session.start(self.runtime, session_id=owner)["expires_at"], old_expiry)
        with self.assertRaises(session.SessionBlocked):
            session.end(self.runtime, owner)

    def test_concurrent_reservation_and_end_cannot_leave_an_unowned_child(self):
        for index in range(12):
            runtime = self.runtime / str(index)
            owner = session.start(runtime)["session_id"]
            barrier = threading.Barrier(2)

            def reserve():
                barrier.wait()
                try:
                    guard.begin(runtime, owner, "a", {}, kind="primary", expected_attempt=0, candidate_alias="fast")
                    return "started"
                except session.SessionConflict:
                    return "denied"

            def release():
                barrier.wait()
                try:
                    session.end(runtime, owner)
                    return "released"
                except session.SessionBlocked:
                    return "denied"

            with ThreadPoolExecutor(max_workers=2) as executor:
                started, ended = executor.submit(reserve), executor.submit(release)
                results = (started.result(), ended.result())
            self.assertIn(results, {("started", "denied"), ("denied", "released")})
            with session.coordinator(runtime) as connection:
                progress = session.read_progress(connection)
                row = connection.execute("SELECT session_id FROM hosted_session").fetchone()
                if progress and progress[1]["inflight"]:
                    self.assertEqual(row[0], progress[0])

    def test_crashed_supervisor_and_unknown_child_remain_fenced_after_expiry(self):
        env = dict(os.environ, PYTHONPATH=str(SCRIPTS))
        code = (
            "import json,sys,time;from pathlib import Path;"
            "import devflow_session as s,devflow_host_guard as g;"
            "p=Path(sys.argv[1]);o=s.start(p)['session_id'];"
            "r=g.begin(p,o,'a',{},kind='primary',expected_attempt=0,candidate_alias='fast');"
            "print(json.dumps({'owner':o,'step':r['step_id']}),flush=True);time.sleep(60)"
        )
        supervisor = subprocess.Popen([sys.executable, "-c", code, str(self.runtime)], env=env, stdout=subprocess.PIPE, text=True)
        self.addCleanup(supervisor.stdout.close)
        self.addCleanup(lambda: supervisor.poll() is None and supervisor.kill())
        record = json.loads(supervisor.stdout.readline())
        supervisor.kill()
        supervisor.wait(timeout=5)
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=0")
        with self.assertRaises(session.SessionBlocked):
            session.start(self.runtime)
        with self.assertRaises(session.SessionConflict):
            autopilot.DomainLease(self.runtime, 1).acquire()
        with self.assertRaisesRegex(guard.GuardBlocked, "termination_unconfirmed"):
            guard.recover(self.runtime, record["owner"], record["step"], "a", {}, outcome="cancelled", confirm_child_terminated=False, termination_evidence="Child state is unknown")

    def test_checkpoint_serializes_with_reservation_release_and_other_checkpoints(self):
        for competitor in ("begin", "end", "checkpoint"):
            with self.subTest(competitor=competitor):
                runtime = self.runtime / competitor
                owner = session.start(runtime)["session_id"]
                step = guard.begin(runtime, owner, "a", {}, kind="primary", expected_attempt=0, candidate_alias="fast")
                guard.finish(runtime, owner, step["step_id"], "b", {}, outcome="completed")
                barrier = threading.Barrier(2)

                def transition(command):
                    barrier.wait()
                    try:
                        if command == "begin":
                            return guard.begin(runtime, owner, "b", {}, kind="primary", expected_attempt=0, candidate_alias="fast")["status"]
                        if command == "end":
                            return session.end(runtime, owner)["status"]
                        return guard.checkpoint(runtime, owner, "b", {})["status"]
                    except session.SessionConflict:
                        return "denied"

                with ThreadPoolExecutor(max_workers=2) as executor:
                    checkpoint = executor.submit(transition, "checkpoint")
                    other = executor.submit(transition, competitor)
                    results = (checkpoint.result(), other.result())
                allowed = {("checkpointed", "denied"), ("denied", {
                    "begin": "started", "end": "released", "checkpoint": "checkpointed",
                }[competitor])}
                self.assertIn(results, allowed)
                with session.coordinator(runtime) as connection:
                    progress_owner, progress = session.read_progress(connection)
                    row = connection.execute("SELECT session_id FROM hosted_session").fetchone()
                    if progress["inflight"] is not None or "checkpointed" in results:
                        self.assertEqual(row[0], progress_owner)

    def test_living_child_blocks_takeover_until_administrator_observes_termination(self):
        owner = session.start(self.runtime)["session_id"]
        record = guard.begin(self.runtime, owner, "a", {}, kind="primary", expected_attempt=0, candidate_alias="fast")
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
        self.addCleanup(lambda: child.poll() is None and child.kill())
        with session.coordinator(self.runtime) as connection:
            connection.execute("UPDATE hosted_session SET expires_at=0")
        with self.assertRaises(session.SessionBlocked):
            session.start(self.runtime)
        with self.assertRaises(session.SessionConflict):
            autopilot.DomainLease(self.runtime, 1).acquire()
        self.assertIsNone(child.poll())
        child.terminate()
        terminal_code = child.wait(timeout=5)
        recovered = guard.recover(
            self.runtime, owner, record["step_id"], "a", {}, outcome="cancelled",
            confirm_child_terminated=True,
            termination_evidence=f"Test administrator waited for child PID {child.pid} termination, exit {terminal_code}",
        )
        self.assertEqual(recovered["status"], "recovered")
        self.assertEqual(session.start(self.runtime)["status"], "acquired")

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
