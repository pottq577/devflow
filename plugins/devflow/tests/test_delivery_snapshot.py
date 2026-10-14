#!/usr/bin/env python3
"""Validate bounded Git reuse against real committed source and artifact provenance."""

from __future__ import annotations

import copy
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_delivery import DeliveryFixtureMixin, fixtures


class DeliverySnapshotTests(DeliveryFixtureMixin, unittest.TestCase):
    def prepare(self):
        self.start_and_commit()
        source = self.root / self.source
        source.write_text("".join(f"# Preserve retry invariant {i}.\n" for i in range(4)) + "def execute():\n    return 1\n")
        self.git("add", self.source)
        self.git("commit", "-qm", "add four source anchors")
        self.head = self.git("rev-parse", "HEAD")
        self.write_artifacts()
        doc = self.read_work()
        item = doc["items"][0]
        item["evidence"]["comments"] = [
            {"path": self.source, "line": i + 1, "reason": "Explain the retry invariant."}
            for i in range(4)
        ]
        fixtures.dump(self.work_path, doc)
        completed = self.done()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return self.read_work()["items"][0]

    def test_one_and_four_anchors_share_source_and_match_uncached_results(self):
        item = self.prepare()
        delivery = self.runtime.delivery
        for anchors in (1, 4):
            with self.subTest(anchors=anchors):
                selected = copy.deepcopy(item)
                selected["evidence"]["comments"] = selected["evidence"]["comments"][:anchors]
                with mock.patch.object(delivery, "_immutable_git", side_effect=delivery.git):
                    expected = delivery.comment_errors(self.root, selected)
                with mock.patch.object(delivery, "git", wraps=delivery.git) as calls, \
                     mock.patch.object(delivery, "comment_lines", wraps=delivery.comment_lines) as parses:
                    actual = delivery.comment_errors(self.root, selected)
                self.assertEqual(actual, expected)
                self.assertEqual(actual, [])
                self.assertEqual(sum(call.args[1] == "show" for call in calls.call_args_list), 1)
                self.assertEqual(parses.call_count, 1)
        with mock.patch.object(delivery, "git", wraps=delivery.git) as calls:
            with delivery.validation_snapshot():
                self.assertEqual(delivery.comment_errors(self.root, item), [])
                self.assertEqual(delivery.comment_errors(self.root, item), [])
        verbs = [call.args[1] for call in calls.call_args_list]
        self.assertEqual(verbs.count("rev-parse"), 2)
        for verb in ("merge-base", "diff", "show"):
            self.assertEqual(verbs.count(verb), 1)

    def test_root_head_and_invocation_do_not_share_stale_sources(self):
        item = self.prepare()
        delivery = self.runtime.delivery
        clone_parent = Path(tempfile.mkdtemp(prefix="devflow-delivery-clone-"))
        self.addCleanup(shutil.rmtree, clone_parent, True)
        clone = clone_parent / "repo"
        fixtures.sh(["git", "clone", "-q", str(self.root), str(clone)], clone_parent, check=True)
        with mock.patch.object(delivery, "git", wraps=delivery.git) as calls:
            with delivery.validation_snapshot():
                self.assertEqual(delivery.comment_errors(self.root, item), [])
                self.assertEqual(delivery.comment_errors(clone, item), [])
            self.assertEqual(delivery.comment_errors(self.root, item), [])
        self.assertEqual(sum(call.args[1] == "show" for call in calls.call_args_list), 3)
        with delivery.validation_snapshot():
            self.assertEqual(delivery.comment_errors(self.root, item), [])
            old_head = delivery.resolve_commit(self.root, "HEAD")
            (self.root / self.source).write_text("def execute():\n    return 2\n")
            self.git("add", self.source)
            self.git("commit", "-qm", "remove source comments")
            new_head = self.git("rev-parse", "HEAD")
            self.assertNotEqual(old_head, new_head)
            self.assertEqual(delivery.resolve_commit(self.root, "HEAD"), new_head)
            changed = copy.deepcopy(item)
            changed["evidence"]["commit"] = new_head
            self.assertTrue(delivery.comment_errors(self.root, changed))
            self.assertIn("comment source provenance", delivery.comment_errors(clone, changed)[0])

    def test_failed_reads_and_exceptions_leave_no_cached_results(self):
        item = self.prepare()
        delivery = self.runtime.delivery
        invalid = copy.deepcopy(item)
        invalid["evidence"]["commit"] = "0" * 40
        with mock.patch.object(delivery, "git", wraps=delivery.git) as calls:
            with delivery.validation_snapshot():
                for _ in range(2):
                    self.assertIn("comment source provenance", delivery.comment_errors(self.root, invalid)[0])
            invalid_reads = [call for call in calls.call_args_list if "0" * 40 + "^{commit}" in call.args]
            self.assertEqual(len(invalid_reads), 2)
        for failure in (ValueError("inspection failed"), delivery.subprocess.TimeoutExpired(["git"], 20)):
            with self.subTest(failure=type(failure).__name__):
                with mock.patch.object(delivery, "git", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        with delivery.validation_snapshot():
                            delivery.resolve_commit(self.root, self.head)
                self.assertIsNone(delivery._VALIDATION_GIT.get())
        self.assertEqual(delivery.comment_errors(self.root, item), [])

    def test_warm_sources_do_not_hide_tampered_anchors_or_moved_deleted_paths(self):
        item = self.prepare()
        delivery = self.runtime.delivery
        with delivery.validation_snapshot():
            self.assertEqual(delivery.comment_errors(self.root, item), [])
            altered = copy.deepcopy(item)
            altered["evidence"]["comments"][0]["line"] = 5
            self.assertIn("substantive source comment", delivery.comment_errors(self.root, altered)[0])
            self.git("mv", self.source, "src/moved.py")
            self.git("commit", "-qm", "move source")
            altered = copy.deepcopy(item)
            altered["evidence"]["commit"] = self.git("rev-parse", "HEAD")
            self.assertIn("identify changed source", delivery.comment_errors(self.root, altered)[0])
            self.git("rm", "src/moved.py")
            self.git("commit", "-qm", "delete source")
            altered["evidence"]["commit"] = self.git("rev-parse", "HEAD")
            self.assertIn("comments_note", delivery.comment_errors(self.root, altered)[0])

    def test_artifacts_and_branch_refs_are_rechecked_with_warm_git_sources(self):
        self.prepare()
        delivery = self.runtime.delivery
        state = self.read_state()
        docs = {self.work_path: self.read_work()}

        def errors():
            return delivery.validation_errors(self.root, "sample", state, docs, self.runtime.markdown_sections, final=True)

        with delivery.validation_snapshot():
            self.assertEqual(errors(), [])
            original = self.pr.read_text()
            self.pr.write_text(original + "\nChanged artifact.\n")
            self.assertTrue(any("stale pr_sha256" in error for error in errors()))
            self.pr.write_text(original)
            self.assertEqual(errors(), [])
            template = self.template.read_text()
            self.template.write_text(template + "\nChanged guidance.\n")
            self.assertTrue(any("stale template_sha256" in error for error in errors()))
            self.template.write_text(template)
            fixtures.commit(self.root, "advance-branch")
            self.assertTrue(any("branch tip advanced" in error for error in errors()))


if __name__ == "__main__":
    unittest.main()
