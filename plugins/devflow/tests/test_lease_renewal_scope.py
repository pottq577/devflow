#!/usr/bin/env python3
"""Observation verifies ownership; only lifecycle edges extend the hosted lease."""

from __future__ import annotations


import sqlite3
import unittest
from pathlib import Path

from test_hosted_session import SCRIPTS  # noqa: F401  (keeps the plugin import path explicit)

import devflow_host_guard as guard
import devflow_session as session


class LeaseRenewalScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.temp = tempfile.TemporaryDirectory(prefix="devflow-lease-scope-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.policy = {
            "escalation": {"retries": {"max_no_progress": 5, "max_consecutive_timeouts": 2}},
            "orchestration": {"hosted": {"max_steps": 100, "max_action_visits": 4}},
        }
        self.owner = session.start(self.runtime)["session_id"]

    def expires_at(self) -> float:
        return session.status(self.runtime)["expires_at"]

    def test_observation_paths_do_not_extend_the_lease(self) -> None:
        before = self.expires_at()
        with session.coordinator(self.runtime) as connection:
            connection.execute(
                "UPDATE hosted_session SET expires_at = expires_at - 3600 WHERE slot = 1"
            )
        near_expiry = self.expires_at()
        session.require(self.runtime, self.owner)
        guard.inspect(self.runtime, self.owner, "v2:" + "a" * 64, self.policy)
        self.assertEqual(self.expires_at(), near_expiry)
        self.assertLess(near_expiry, before)

    def test_lifecycle_edges_still_renew_the_lease(self) -> None:
        with session.coordinator(self.runtime) as connection:
            connection.execute(
                "UPDATE hosted_session SET expires_at = expires_at - 3600 WHERE slot = 1"
            )
        before = self.expires_at()
        self.assertGreater(session.renew(self.runtime, self.owner)["expires_at"], before)
        step = guard.begin(
            self.runtime, self.owner, "v2:" + "a" * 64, self.policy,
            kind="primary", expected_attempt=0, candidate_alias="fast",
        )
        self.assertGreater(self.expires_at(), before)
        guard.finish(
            self.runtime, self.owner, step["step_id"], "v2:" + "a" * 64, self.policy,
            outcome="completed",
        )
        self.assertGreater(self.expires_at(), before)

    def test_observation_keeps_ownership_and_inflight_fencing(self) -> None:
        with self.assertRaisesRegex(session.SessionConflict, "another hosted Goal session"):
            session.require(self.runtime, "not-the-owner")
        session.end(self.runtime, self.owner)
        with self.assertRaisesRegex(session.SessionConflict, "expired or does not exist"):
            session.require(self.runtime, self.owner)
        replacement = session.start(self.runtime)["session_id"]
        step = guard.begin(
            self.runtime, replacement, "v2:" + "a" * 64, self.policy,
            kind="primary", expected_attempt=0, candidate_alias="fast",
        )
        self.assertIsNotNone(step["step_id"])
        with session.coordinator(self.runtime) as connection:
            connection.execute("DELETE FROM hosted_session WHERE slot = 1")
        # An expired lease never releases a child whose termination was never confirmed.
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.require(self.runtime, "any-other-owner")
        with self.assertRaisesRegex(session.SessionConflict, "expired or ownership changed"):
            guard.inspect(self.runtime, "any-other-owner", "v2:" + "a" * 64, self.policy)
        with self.assertRaisesRegex(session.SessionBlocked, "hosted_step_inflight"):
            session.start(self.runtime)

    def test_read_only_paths_do_not_write_sqlite(self) -> None:
        database = self.runtime / "leases" / "coordinator.sqlite3"
        for _ in range(3):
            session.require(self.runtime, self.owner)
            session.status(self.runtime)
            guard.inspect(self.runtime, self.owner, "v2:" + "a" * 64, self.policy)
        before = database.stat().st_mtime_ns
        digest_before = database.read_bytes()
        session.require(self.runtime, self.owner)
        session.status(self.runtime)
        guard.inspect(self.runtime, self.owner, "v2:" + "a" * 64, self.policy)
        self.assertEqual(database.read_bytes(), digest_before)
        self.assertEqual(database.stat().st_mtime_ns, before)
        with sqlite3.connect(str(database)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)