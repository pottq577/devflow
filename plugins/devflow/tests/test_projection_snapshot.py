#!/usr/bin/env python3
"""Invocation-local WORK sources preserve lifecycle actions and mutation freshness."""

from __future__ import annotations

import copy
import shutil
import unittest
from pathlib import Path
from unittest import mock

import test_devflow as t


class ProjectionSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = t.new_repo()
        self.addCleanup(shutil.rmtree, self.root)
        self.runtime = t.load_runtime_module()
        result = t.invoke_runtime(self.root, self.runtime, "init", "billing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.domain = self.root / "docs/domains/billing"
        self.work_file = self.domain / "work/phase-01.yaml"
        self.state = t.state({"01": t.phase("executing", "01")})
        t.dump(self.domain / "STATE.yaml", self.state)

    def invoke(self, *args: str):
        result = t.invoke_runtime(self.root, self.runtime, *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_status_and_render_parse_work_and_project_once(self) -> None:
        blocked = t.item("P01-I02", status="blocked", block_reason="needs decision")
        waiting = t.item("P01-I03", status="blocked", block_kind="external")
        second_file = self.domain / "work/phase-02.yaml"
        t.dump(self.work_file, t.work("01", t.item("P01-I01")))
        t.dump(second_file, t.work("02", blocked, waiting))
        for args in (
            ("status", "billing"),
            ("status", "billing", "--json", "--no-refresh"),
            ("render", "run", "billing", "--task", "P01-I01"),
            ("render", "run", "billing", "--task", "P01-I01", "--no-refresh"),
        ):
            with self.subTest(args=args):
                reads = []
                real_load = self.runtime.load_yaml

                def load(path, default=None):
                    if Path(path).parent.name == "work":
                        reads.append(Path(path))
                    return real_load(path, default)

                with mock.patch.object(self.runtime, "load_yaml", side_effect=load), \
                     mock.patch.object(self.runtime, "index_work_docs", wraps=self.runtime.index_work_docs) as builds, \
                     mock.patch.object(self.runtime, "compute_next_action", wraps=self.runtime.compute_next_action) as projections:
                    result = self.invoke(*args)
                self.assertEqual(reads, [self.work_file, second_file])
                self.assertEqual(builds.call_count, 1)
                self.assertEqual(projections.call_count, 1)
                self.assertIsNone(self.runtime._WORK_INDEX_SNAPSHOT.get())
                if args == ("status", "billing"):
                    self.assertIn("blocked_work: P01-I02", result.stdout)
                    self.assertIn("waiting_external_work: P01-I03", result.stdout)
                    self.assertIn("next.input: work/phase-01.yaml", result.stdout)

    def test_cached_projection_matches_uncached_lifecycle_cases(self) -> None:
        waiting = t.item("P01-I01", status="blocked", block_kind="external")
        cases = (
            ("ready", "executing", t.item("P01-I01"), "run", "phase"),
            ("blocked", "executing", t.item("P01-I01", status="blocked"), "decision", "phase"),
            ("external", "executing", waiting, "provide-evidence", "work"),
            ("review", "executing", t.item("P01-I01", status="done", risk_level="high"), "audit", "work"),
            ("phase", "executing", t.item("P01-I01", status="done"), "audit", "phase"),
            ("integration", "verified", t.item("P01-I01", status="done"), "audit", "integration"),
        )

        def uncached(d, overrides=None):
            docs = {path: self.runtime.load_yaml(path, {}) or {} for path in self.runtime.work_files(d)}
            docs.update(overrides or {})
            return self.runtime.index_work_docs(docs)

        for name, phase_status, item, command, scope in cases:
            with self.subTest(case=name):
                t.dump(self.work_file, t.work("01", item))
                state = t.state({"01": t.phase(phase_status, "01")})
                with mock.patch.object(self.runtime, "load_work_index", side_effect=uncached):
                    expected = self.runtime.project_state(self.root, "billing", copy.deepcopy(state))
                actual = self.runtime.project_state(self.root, "billing", copy.deepcopy(state))
                self.assertEqual(actual, expected)
                self.assertEqual(actual["next_action"]["command"], command)
                self.assertEqual(actual["next_action"]["scope"], scope)

    def test_audit_render_reuses_snapshot_and_preserves_custom_work_documents(self) -> None:
        for scope, custom, empty in (("phase", False, False), ("phase", False, True), ("integration", False, True), ("phase", True, False), ("integration", True, False)):
            with self.subTest(scope=scope, custom=custom, empty=empty):
                phase_status = ("audit" if custom or empty else "executing") if scope == "phase" else "verified"
                state = t.state({"01": t.phase(phase_status, "01")})
                t.dump(self.work_file, t.work("01", t.item("P01-I01", status="done")))
                path = self.work_file if scope == "phase" else self.domain / "work/integration.yaml"
                if custom:
                    path = self.domain / "custom-work.yaml"
                    owner = state["phases"]["01"] if scope == "phase" else state["integration"]
                    owner["work_file"] = "custom-work.yaml"
                document = {"snapshot_marker": f"{scope}-{custom}"} if custom else ({} if empty else t.work("01", t.item("P01-I01", status="done")))
                t.dump(path, document)
                t.dump(self.domain / "STATE.yaml", state)
                reads = []
                real_load = self.runtime.load_yaml

                def load(loaded_path, default=None):
                    if Path(loaded_path) == path:
                        reads.append(Path(loaded_path))
                    return real_load(loaded_path, default)

                before = (self.domain / "STATE.yaml").read_bytes()
                args = ["render", "audit", "billing", "--scope", scope, "--mode", "initial", "--no-refresh"]
                if scope == "phase":
                    args.extend(["--phase", "01"])
                with mock.patch.object(self.runtime, "load_yaml", side_effect=load):
                    rendered = self.invoke(*args)
                self.assertEqual(reads, [path])
                title = "Phase WORK YAML" if scope == "phase" else "Integration WORK YAML"
                self.assertIn(f"## {title}\n```yaml\n", rendered.stdout)
                content = f"snapshot_marker: {scope}-{custom}" if custom else ("{}" if empty else "id: P01-I01")
                self.assertIn(content, rendered.stdout)
                self.assertEqual((self.domain / "STATE.yaml").read_bytes(), before)

    def test_next_invocation_observes_work_edits_new_files_and_head(self) -> None:
        t.dump(self.work_file, t.work("01", t.item("P01-I01")))
        first = self.runtime.project_state(self.root, "billing", copy.deepcopy(self.state))
        self.assertEqual(first["next_action"]["work_item"], "P01-I01")
        t.dump(self.work_file, t.work("01", t.item("P01-I01", status="done")))
        second_file = self.domain / "work/phase-01-extra.yaml"
        t.dump(second_file, t.work("01", t.item("P01-I02")))
        t.commit(self.root, "new-head")
        second = self.runtime.project_state(self.root, "billing", copy.deepcopy(self.state))
        self.assertEqual(second["next_action"]["work_item"], "P01-I02")
        self.assertNotEqual(first["target_sha"], second["target_sha"])

    def test_post_mutation_projection_reads_changed_work(self) -> None:
        t.dump(self.work_file, t.work("01", t.item("P01-I01")))
        self.invoke("status", "billing", "--no-refresh")
        self.invoke("work", "start", "billing", "P01-I01")
        changed = self.runtime.load_yaml(self.work_file)
        self.assertEqual(changed["items"][0]["status"], "in_progress")
        stored = self.runtime.load_yaml(self.domain / "STATE.yaml")
        self.assertEqual(stored["next_action"]["work_item"], "P01-I01")
        self.assertEqual(stored["next_action"], self.runtime.project_state(self.root, "billing", copy.deepcopy(stored))["next_action"])
        stored["phases"]["01"]["status"] = "verified"
        self.runtime.commit_lifecycle_mutation(
            self.root, "billing", stored,
            {self.work_file: t.work("01", t.item("P01-I01", status="done"))},
        )
        projected = self.runtime.project_state(self.root, "billing", copy.deepcopy(stored))
        self.assertEqual(projected["next_action"]["command"], "audit")
        self.assertEqual(projected["next_action"]["scope"], "integration")

    def test_overrides_and_other_roots_do_not_poison_base_snapshot(self) -> None:
        t.dump(self.work_file, t.work("01", t.item("P01-I01")))
        other_domain = self.root / "other/docs/domains/billing"
        other_file = other_domain / "work/phase-01.yaml"
        t.dump(other_file, t.work("01", t.item("OTHER-I01")))
        overrides = {self.work_file: t.work("01", t.item("P01-I02"))}
        with self.runtime._work_snapshot():
            base = self.runtime.load_work_index(self.domain)
            self.assertEqual(set(self.runtime.load_work_index(self.domain, overrides)[1]), {"P01-I02"})
            overrides[self.work_file] = t.work("01", t.item("P01-I03"))
            self.assertEqual(set(self.runtime.load_work_index(self.domain, overrides)[1]), {"P01-I03"})
            self.assertIs(self.runtime.load_work_index(self.domain), base)
            self.assertEqual(set(base[1]), {"P01-I01"})
            self.assertEqual(set(self.runtime.load_work_index(other_domain)[1]), {"OTHER-I01"})
            t.dump(self.work_file, t.work("01", t.item("P01-I04")))
            self.assertIs(self.runtime.load_work_index(self.domain), base)
        self.assertEqual(set(self.runtime.load_work_index(self.domain)[1]), {"P01-I04"})

    def test_rejected_render_and_exception_leave_state_and_scope_unchanged(self) -> None:
        t.dump(self.work_file, t.work("01", t.item("P01-I01")))
        state_file = self.domain / "STATE.yaml"
        before = state_file.read_bytes(), state_file.stat().st_mtime_ns
        result = t.invoke_runtime(self.root, self.runtime, "render", "plan", "billing")
        self.assertEqual(result.returncode, 2)
        self.assertEqual((state_file.read_bytes(), state_file.stat().st_mtime_ns), before)
        self.assertIsNone(self.runtime._WORK_INDEX_SNAPSHOT.get())
        with mock.patch.object(self.runtime, "compute_next_action", side_effect=ValueError("invalid projection")):
            with self.assertRaisesRegex(ValueError, "invalid projection"):
                self.runtime.project_state(self.root, "billing", copy.deepcopy(self.state))
        self.assertIsNone(self.runtime._WORK_INDEX_SNAPSHOT.get())
        t.dump(self.work_file, t.work("01", t.item("P01-I04")))
        projected = self.runtime.project_state(self.root, "billing", copy.deepcopy(self.state))
        self.assertEqual(projected["next_action"]["work_item"], "P01-I04")


if __name__ == "__main__":
    unittest.main()
