#!/usr/bin/env python3
"""Focused tests for immutable DevFlow source capture and verification."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import devflow_sources as sources


class SourceCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.domain = "sample-domain"
        self.target = self.root / "docs" / "domains" / self.domain
        self.original = self.root / "spec" / "original.md"
        self.context = self.root / "spec" / "context.md"
        self.original.parent.mkdir()
        self.original.write_bytes("# 원문\r\n원본 규칙\r\n".encode("utf-8"))
        self.context.write_text("# 추가정리\n검토 사항\n", encoding="utf-8")

    def capture(self) -> dict:
        return sources.capture(
            self.root, self.target, self.domain, self.original, self.context
        )

    def test_capture_preserves_exact_bytes_and_provenance(self) -> None:
        record = self.capture()
        self.assertEqual(record["status"], "captured")
        snapshot = self.target / "sources" / "v1"
        self.assertEqual((snapshot / "original.md").read_bytes(), self.original.read_bytes())
        self.assertEqual((snapshot / "context.md").read_bytes(), self.context.read_bytes())
        self.assertEqual(record["sources"]["original"]["source_path"], "spec/original.md")
        self.assertEqual(sources.verify(self.root, self.target, self.domain)["status"], "verified")

    def test_capture_is_idempotent_when_both_inputs_match(self) -> None:
        self.capture()
        self.assertEqual(self.capture()["status"], "unchanged")

    def test_changed_input_refuses_overwrite(self) -> None:
        self.capture()
        saved = (self.target / "sources" / "v1" / "original.md").read_bytes()
        self.original.write_text("# updated", encoding="utf-8")
        with self.assertRaisesRegex(sources.SourceError, "immutable"):
            self.capture()
        self.assertEqual((self.target / "sources" / "v1" / "original.md").read_bytes(), saved)
        with self.assertRaisesRegex(sources.SourceError, "changed"):
            sources.verify(self.root, self.target, self.domain, check_source=True)
        self.assertEqual(sources.verify(self.root, self.target, self.domain)["status"], "verified")

    def test_modified_snapshot_fails_verification(self) -> None:
        self.capture()
        snapshot = self.target / "sources" / "v1" / "context.md"
        snapshot.write_text("altered", encoding="utf-8")
        with self.assertRaisesRegex(sources.SourceError, "hash mismatch"):
            sources.verify(self.root, self.target, self.domain)

    def test_bad_second_input_leaves_no_capture(self) -> None:
        self.context.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(sources.SourceError, "UTF-8"):
            self.capture()
        self.assertFalse((self.target / "sources" / "v1").exists())

    def test_modified_manifest_snapshot_path_is_rejected(self) -> None:
        self.capture()
        manifest = self.target / "sources" / "v1" / "manifest.json"
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["sources"]["context"]["snapshot"] = "../../escaped.md"
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(sources.SourceError, "Invalid source manifest entry"):
            sources.verify(self.root, self.target, self.domain)

    def test_duplicate_manifest_fields_are_rejected(self) -> None:
        self.capture()
        manifest = self.target / "sources" / "v1" / "manifest.json"
        manifest.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(sources.SourceError, "Duplicate"):
            sources.verify(self.root, self.target, self.domain)

    def test_input_symlink_is_rejected(self) -> None:
        linked = self.root / "spec" / "linked.md"
        linked.symlink_to(self.original)
        with self.assertRaisesRegex(sources.SourceError, "symlink"):
            sources.capture(self.root, self.target, self.domain, linked, self.context)
        self.assertFalse((self.target / "sources" / "v1").exists())

    def test_oversized_input_is_rejected(self) -> None:
        self.context.write_bytes(b"A" * (sources.MAX_SOURCE_BYTES + 1))
        with self.assertRaisesRegex(sources.SourceError, "size"):
            self.capture()
        self.assertFalse((self.target / "sources" / "v1").exists())

    def test_same_file_for_both_roles_is_rejected(self) -> None:
        with self.assertRaisesRegex(sources.SourceError, "different files"):
            sources.capture(
                self.root, self.target, self.domain, self.original, self.original
            )

    def test_capture_path_cannot_be_symlinked(self) -> None:
        other = self.root / "another"
        other.mkdir()
        self.target.mkdir(parents=True)
        (self.target / "sources").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(sources.SourceError, "symlink"):
            self.capture()


if __name__ == "__main__":
    unittest.main(verbosity=2)
