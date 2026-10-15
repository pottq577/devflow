#!/usr/bin/env python3
"""Finalization projections skip known blockers without weakening evidence gates."""

from __future__ import annotations

import hashlib
import os
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import test_finalization as base
from test_delivery import DeliveryFixtureMixin, fixtures


class FinalizationProjectionTests(DeliveryFixtureMixin, unittest.TestCase):
    cli = base.FinalizationTests.cli
    completed = base.FinalizationTests.completed
    context = base.FinalizationTests.context
    skill = base.FinalizationTests.skill
    html = base.FinalizationTests.html
    explain = base.FinalizationTests.explain
    fake_newman = base.FinalizationTests.fake_newman
    owned_server_command = base.FinalizationTests.owned_server_command
    run_newman = base.FinalizationTests.run_newman

    def final_errors(self, **kwargs):
        state = self.read_state()
        docs, _, _ = self.runtime.load_work_index(self.d)
        return self.runtime.finalization.final_errors(
            self.root, "sample", state, docs, self.d, require_receipt=True, **kwargs
        )

    def passed_run(self):
        self.completed()
        result = self.run_newman()
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.read_state()["delivery"]["finalization"]["runs"][-1]

    def test_known_blocker_keeps_first_error_without_reading_evidence(self):
        run = self.passed_run()
        evidence = {
            self.root / run["raw_file"],
            self.root / run["summary_file"],
            self.root / run["server_lifecycle"]["log_file"],
        }
        reads = Counter()
        real_read = Path.read_bytes

        def read(path):
            reads[path] += 1
            return real_read(path)

        with patch.object(Path, "read_bytes", read):
            projected = self.final_errors(first_error_only=True)
            self.assertEqual(sum(reads[p] for p in evidence), 0)
            full = self.final_errors()
        self.assertEqual(projected, full[:1])
        self.assertEqual(projected, ["ELI5 explanation evidence is missing"])
        self.assertTrue(all(reads[p] == 1 for p in evidence), reads)
        self.assertGreater(len(full), 1)

    def test_successful_projection_checks_content_and_invalidates_same_scope_changes(self):
        run = self.passed_run()
        self.assertEqual(self.explain().returncode, 0)
        self.assertEqual(self.cli("delivery", "finalize", "sample").returncode, 0)
        paths = (
            (self.root / run["raw_file"], "Newman raw report hash changed"),
            (self.root / run["summary_file"], "Newman summary content hash changed"),
            (self.root / run["server_lifecycle"]["log_file"], "Newman server log hash changed"),
        )
        fin = self.runtime.finalization
        with fin.evidence_snapshot():
            self.assertEqual(self.final_errors(first_error_only=True), [])
            for path, expected in paths:
                with self.subTest(path=path.name):
                    original = path.read_bytes()
                    stat = path.stat()
                    changed = original[:-1] + bytes([original[-1] ^ 1]) if original else b"x"
                    try:
                        path.write_bytes(changed)
                        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                        full = self.final_errors()
                        projected = self.final_errors(first_error_only=True)
                        self.assertTrue(any(expected in error for error in full), full)
                        self.assertEqual(projected, full[:1])
                    finally:
                        path.write_bytes(original)
                    self.assertEqual(self.final_errors(first_error_only=True), [])
        self.assertIsNone(fin._EVIDENCE_HASHES.get())

    def test_repeated_full_checks_and_failed_run_share_only_raw_and_log_digests(self):
        self.completed()
        self.assertEqual(self.run_newman(failure=True).returncode, 1)
        failed = self.read_state()["delivery"]["finalization"]["runs"][-1]
        self.assertEqual(self.run_newman().returncode, 0)
        passed = self.read_state()["delivery"]["finalization"]["runs"][-1]
        paths = {
            self.root / run[key]
            for run in (failed, passed)
            for key in ("raw_file", "summary_file")
        } | {
            self.root / run["server_lifecycle"]["log_file"]
            for run in (failed, passed)
        }
        reads = Counter()
        real_read = Path.read_bytes

        def read(path):
            reads[path] += 1
            return real_read(path)

        fin = self.runtime.finalization
        with patch.object(Path, "read_bytes", read):
            with fin.evidence_snapshot():
                expected = self.final_errors()
                self.assertEqual(self.final_errors(), expected)
                self.assertTrue(fin.completed_failed_newman(self.root, failed))
            for path in paths:
                self.assertEqual(reads[path], 2 if path.name.endswith(".summary.json") else 1)
            self.assertTrue(fin.completed_failed_newman(self.root, failed))
        self.assertEqual(reads[self.root / failed["raw_file"]], 2)
        self.assertIsNone(fin._EVIDENCE_HASHES.get())

    def test_mutating_gates_and_verified_validation_reject_tampered_history(self):
        run = self.passed_run()
        self.finish_phase_audit()
        self.assertEqual(self.explain().returncode, 0)
        self.assertEqual(self.cli("delivery", "finalize", "sample").returncode, 0)
        fixtures.write_audit(
            self.d / "audits/integration.md", fixtures.audit_metadata(self.d)
        )
        audit = ("audit", "apply", "sample", "--scope", "integration", "--mode", "initial")
        paths = (
            self.root / run["raw_file"],
            self.root / run["summary_file"],
            self.root / run["server_lifecycle"]["log_file"],
        )
        for path in paths:
            original = path.read_bytes()
            before = self.state_path.read_bytes(), self.work_path.read_bytes()
            try:
                path.write_bytes(original + b" ")
                for args in (("delivery", "finalize", "sample"), audit):
                    with self.subTest(path=path.name, command=args[0]):
                        result = self.cli(*args)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual((self.state_path.read_bytes(), self.work_path.read_bytes()), before)
            finally:
                path.write_bytes(original)
        result = self.cli(*audit)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in paths:
            original = path.read_bytes()
            try:
                path.write_bytes(original + b" ")
                result = self.cli("validate", "sample")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            finally:
                path.write_bytes(original)

    def test_changed_read_and_exceptions_never_cache_or_leak_scope(self):
        path = self.root / "evidence.json"
        path.write_bytes(b"one")
        other = self.root / "other/evidence.json"
        other.parent.mkdir()
        other.write_bytes(b"two")
        fin = self.runtime.finalization
        real_read = Path.read_bytes

        def changing_read(target):
            value = real_read(target)
            target.write_bytes(b"new")
            return value

        with self.assertRaisesRegex(ValueError, "changed while reading"):
            with fin.evidence_snapshot():
                with fin.evidence_snapshot():
                    with patch.object(Path, "read_bytes", changing_read):
                        try:
                            fin._evidence_sha256(path)
                        finally:
                            self.assertEqual(fin._EVIDENCE_HASHES.get(), {})
        self.assertIsNone(fin._EVIDENCE_HASHES.get())
        with fin.evidence_snapshot():
            self.assertEqual(fin._evidence_sha256(path), hashlib.sha256(b"new").hexdigest())
            self.assertEqual(fin._evidence_sha256(other), hashlib.sha256(b"two").hexdigest())
            path.unlink()
            with self.assertRaises(OSError):
                fin._evidence_sha256(path)
            path.write_bytes(b"end")
            self.assertEqual(fin._evidence_sha256(path), hashlib.sha256(b"end").hexdigest())
        self.assertIsNone(fin._EVIDENCE_HASHES.get())


if __name__ == "__main__":
    unittest.main()
