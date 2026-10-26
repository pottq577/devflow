#!/usr/bin/env python3
"""Git-based advisory impact selection, conservative fallback and CLI proof."""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import devflow_test_impact as impact
import run_suite


class TestImpactTests(unittest.TestCase):
    class Probe(unittest.TestCase):
        def __init__(self, name: str):
            super().__init__("runTest")
            self.name = name

        def id(self):
            return self.name

        def runTest(self):
            pass

    def fixtures(self):
        modules = sorted(set(impact.DOC_TESTS | impact.VERSION_TESTS | impact.HOST_TESTS
                             | impact.ROUTING_TESTS | {"test_test_impact", "test_suite_runner",
                                                    "test_suite_output_budget", "test_execution_progress",
                                                    "test_execution_resume", "test_lifecycle_cases",
                                                    "test_newman_integration", "test_autopilot"}))
        cases = [self.Probe(f"{name}.Fixture.test_case") for name in modules]
        cases += [
            self.Probe("test_lifecycle_cases.LifecycleCases.test_case_001"),
            self.Probe("test_newman_integration.RealNewmanTests.test_real_smoke"),
        ]
        return cases

    @staticmethod
    def git(repo: Path, *args: str):
        return subprocess.run(["git", *args], cwd=repo, check=True,
                              capture_output=True, text=True)

    def repo_fixture(self):
        temp = tempfile.TemporaryDirectory(prefix="devflow-impact-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.git(root, "init", "-q")
        self.git(root, "config", "user.name", "Impact Fixture")
        self.git(root, "config", "user.email", "impact@example.invalid")
        path = root / "plugins/devflow/tests/run_suite.py"
        path.parent.mkdir(parents=True)
        path.write_text("original\n", encoding="utf-8")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "base")
        return root, path

    def test_changes_include_committed_staged_unstaged_and_untracked(self):
        root, tracked = self.repo_fixture()
        tracked.write_text("committed\n", encoding="utf-8")
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "second")
        tracked.write_text("unstaged\n", encoding="utf-8")
        staged = root / "plugins/devflow/tests/test_test_impact.py"
        staged.write_text("stage\n", encoding="utf-8")
        self.git(root, "add", str(staged.relative_to(root)))
        untracked = root / "plugins/devflow/tests/test_new_thing.py"
        untracked.write_text("untracked\n", encoding="utf-8")
        paths = impact.changed_paths(root, "HEAD~1")
        self.assertEqual(paths, [
            "plugins/devflow/tests/run_suite.py",
            "plugins/devflow/tests/test_new_thing.py",
            "plugins/devflow/tests/test_test_impact.py",
        ])
        self.assertEqual(impact.changed_paths(root, "HEAD"), paths)

    def test_empty_changes_and_nonplugin_paths_do_not_pass(self):
        root, _ = self.repo_fixture()
        self.assertEqual(impact.changed_paths(root, "HEAD"), [])
        with self.assertRaisesRegex(ValueError, "no DevFlow source changes"):
            impact.choose_cases([], self.fixtures(), base="HEAD")
        with self.assertRaisesRegex(ValueError, "no DevFlow source changes"):
            impact.choose_cases(["other-project/src.py"], self.fixtures(), base="HEAD")

    def test_invalid_or_unknown_git_revision_fails_closed(self):
        root, _ = self.repo_fixture()
        with self.assertRaisesRegex(ValueError, "safe Git"):
            impact.changed_paths(root, "--dangerous")
        with self.assertRaisesRegex(ValueError, "git change discovery failed"):
            impact.changed_paths(root, "nonexistent-branch")

    def test_targeted_script_includes_all_declared_dependent_modules(self):
        selected, meta = impact.choose_cases(
            ["plugins/devflow/scripts/devflow_execution.py"], self.fixtures(), base="HEAD")
        self.assertEqual({item.id().split(".")[0] for item in selected},
                         impact.IMPACT_MAP["scripts/devflow_execution.py"])
        self.assertEqual(meta["strategy"], "mapped_modules")
        self.assertEqual(meta["authority"], "advisory_partial_only")
        self.assertFalse(any("LifecycleCases" in c.id() for c in selected))

    def test_doc_and_skill_changes_include_contracts_not_full_suite(self):
        selected, meta = impact.choose_cases(
            ["plugins/devflow/skills/goal/SKILL.md", "plugins/devflow/README.md"],
            self.fixtures(), base="HEAD")
        modules = {x.id().split(".")[0] for x in selected}
        self.assertTrue(impact.DOC_TESTS <= modules)
        self.assertIn("test_host_autopilot", modules)
        self.assertNotIn("test_autopilot", modules)
        self.assertEqual(meta["strategy"], "mapped_modules")

    def test_unmapped_python_falls_back_to_all_focused(self):
        selected, meta = impact.choose_cases(
            ["plugins/devflow/scripts/devflow.py"], self.fixtures(), base="HEAD")
        self.assertEqual(meta["strategy"], "fallback_focused")
        self.assertEqual(meta["unmapped_count"], 1)
        self.assertNotIn("test_lifecycle_cases.LifecycleCases.test_case_001", {c.id() for c in selected})
        self.assertNotIn("test_newman_integration.RealNewmanTests.test_real_smoke", {c.id() for c in selected})
        self.assertIn("test_autopilot.Fixture.test_case", {c.id() for c in selected})

    def test_removed_test_module_is_not_treated_as_covered(self):
        with self.assertRaisesRegex(ValueError, "missing test modules"):
            impact.choose_cases(["plugins/devflow/tests/test_deleted.py"],
                                self.fixtures(), base="HEAD")

    def test_git_changed_mode_runs_exact_ids_and_reports_partial(self):
        cases = [self.Probe("test_test_impact.Case.test_one"),
                 self.Probe("test_suite_runner.Case.test_two")]
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "results.json"
            output = io.StringIO()
            with (mock.patch.object(run_suite, "collect_cases", return_value=cases),
                  mock.patch.object(impact, "changed_paths",
                                    return_value=["plugins/devflow/tests/test_test_impact.py"]),
                  contextlib.redirect_stderr(output)):
                code = run_suite.main(["--changed-from", "HEAD", "--report", str(result_path)])
            self.assertEqual(code, 0)
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual([row["id"] for row in payload["tests"]],
                             ["test_test_impact.Case.test_one"])
            self.assertFalse(payload["complete"])
            self.assertEqual(payload["impact"]["authority"], "advisory_partial_only")
            self.assertIn("PARTIAL", output.getvalue())

    def test_git_changed_mode_cannot_disguise_release_or_combine_filters(self):
        cases = [self.Probe("test_test_impact.Case.test_one")]
        with mock.patch.object(run_suite, "collect_cases", return_value=cases):
            for options in (["--changed-from", "HEAD", "--match", "anything"],
                            ["--changed-from", "HEAD", "--profile", "focused"],
                            ["--changed-from", "HEAD", "--rerun-from", "foo.json"],
                            ["--changed-from", "HEAD", "--summary-from", "foo.json"]):
                with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(run_suite.main(options), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
