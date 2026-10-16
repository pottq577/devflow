#!/usr/bin/env python3
"""Whole-work finalization input: bounded manifest, paging and unchanged scope."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
import test_devflow as fixture_helpers

CLI = Path(__file__).resolve().parents[1] / "scripts" / "devflow.py"


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=cwd, text=True, capture_output=True
    )


class FinalizerManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="devflow-finalize-manifest-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        for key, value in (("user.email", "t@e.com"), ("user.name", "t")):
            subprocess.run(["git", "config", key, value], cwd=self.root, check=True)
        (self.root / "seed.txt").write_text("seed\n")
        subprocess.run(["git", "add", "seed.txt"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        initialized = run(self.root, "init", "sample")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.domain = self.root / "docs/domains/sample"
        self.state_path = self.domain / "STATE.yaml"

    def seed_work(self, count: int) -> list[str]:
        ids = []
        items = []
        for index in range(count):
            item_id = f"P01-I{index + 1:02d}"
            item = fixture_helpers.item(item_id)
            item["status"] = "done"
            item["evidence"] = {
                "commit": "a" * 40,
                "changed_files": [f"src/{item_id}.py"],
                "commands": [f"pytest -q {item_id} -> passed"],
            }
            items.append(item)
            ids.append(item_id)
        path = self.domain / "work" / "phase-01.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(fixture_helpers.work("01", *items), sort_keys=False),
            encoding="utf-8",
        )
        state = yaml.safe_load(self.state_path.read_text(encoding="utf-8"))
        state["phases"] = {"01": fixture_helpers.phase("verified", "01")}
        state["integration"] = {"status": "pending"}
        self.state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
        return ids

    def manifest_page(self, output: str, title_fragment: str) -> dict:
        block = output.split(title_fragment, 1)[1]
        return yaml.safe_load(block.split("```yaml", 1)[1].split("```", 1)[0])

    def test_manifest_pages_cover_every_work_item_and_branch(self) -> None:
        for count in (60, 120, 250):
            with self.subTest(work=count):
                ids = self.seed_work(count)
                rendered = run(self.root, "render", "finalize", "sample")
                self.assertEqual(rendered.returncode, 0, rendered.stderr)
                self.assertIn("$eli5", rendered.stdout)
                seen: list[str] = []
                page = 1
                while True:
                    result = (
                        rendered if page == 1
                        else run(self.root, "render", "finalize", "sample", "--manifest-page", str(page))
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    payload = self.manifest_page(result.stdout, "WORK manifest page")
                    self.assertEqual(payload["total_work_items"], count)
                    self.assertEqual(payload["page"], page)
                    seen.extend(str(row["id"]) for row in payload["items"])
                    if page >= payload["pages"]:
                        break
                    page += 1
                self.assertEqual(sorted(seen), sorted(ids))
                self.assertEqual(len(seen), len(set(seen)))
                scope = self.manifest_page(rendered.stdout, "Whole-work scope and HTML metadata")
                self.assertEqual(scope["work_items_in_scope"], count)
                self.assertEqual(scope["html_metadata"]["work_ids"], sorted(ids))
                self.assertEqual(scope["html_file"].endswith("implementation.html"), True)
                # Whole WORK rows stay inside scope_sha256 instead of being printed on every page.
                self.assertNotIn("works", scope["scope"])
                self.assertIn("branches", scope["scope"])
                self.assertIn("sources", scope["scope"])
                first = self.manifest_page(rendered.stdout, "WORK manifest page")["items"][0]
                for key in ("id", "status", "kind", "risk", "phase", "commit",
                            "review", "changed_files", "verification", "work_file"):
                    self.assertIn(key, first)
                self.assertTrue((self.root / first["work_file"]).is_file())
                self.assertEqual(
                    scope["html_metadata"]["scope_sha256"],
                    self.scope_sha256(count),
                )

    def test_a_later_page_work_change_still_fails_the_whole_scope_check(self) -> None:
        """Paging changes what is read per page, never what the final gates verify."""
        ids = self.seed_work(120)
        recorded = self.manifest_page(
            run(self.root, "render", "finalize", "sample").stdout,
            "Whole-work scope and HTML metadata",
        )["html_metadata"]["scope_sha256"]
        self.assertEqual(recorded, self.scope_sha256(120))
        # The item only reachable through page 2 still moves the whole-work digest.
        path = self.domain / "work" / "phase-01.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document["items"][-1]["evidence"]["commit"] = "b" * 40
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        self.assertEqual(ids[-1], document["items"][-1]["id"])
        moved = self.manifest_page(
            run(self.root, "render", "finalize", "sample", "--manifest-page", "2").stdout,
            "Whole-work scope and HTML metadata",
        )["html_metadata"]["scope_sha256"]
        self.assertNotEqual(moved, recorded)
        runtime = fixture_helpers.load_runtime_module()
        state = yaml.safe_load(self.state_path.read_text(encoding="utf-8"))
        docs, _index, _errors = runtime.load_work_index(self.domain)
        pinned = runtime.finalization.scope(
            self.root, "sample", state, docs, self.domain
        )["html_metadata"]["scope_sha256"]
        self.assertEqual(pinned, moved)

    def scope_sha256(self, count: int) -> str:
        runtime = fixture_helpers.load_runtime_module()
        state = yaml.safe_load(self.state_path.read_text(encoding="utf-8"))
        docs, _index, _errors = runtime.load_work_index(self.domain)
        ctx = runtime.finalization.scope(self.root, "sample", state, docs, self.domain)
        self.assertEqual(len(ctx["scope"]["works"]), count)
        return ctx["html_metadata"]["scope_sha256"]

    def test_manifest_page_out_of_range_and_full_document_access(self) -> None:
        self.seed_work(61)
        rendered = run(self.root, "render", "finalize", "sample")
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertEqual(self.manifest_page(rendered.stdout, "WORK manifest page")["pages"], 2)
        self.assertIn("--manifest-page <n>", rendered.stdout)
        rejected = run(self.root, "render", "finalize", "sample", "--manifest-page", "3")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("out of range", rejected.stderr)
        second = run(self.root, "render", "finalize", "sample", "--manifest-page", "2")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(self.manifest_page(second.stdout, "WORK manifest page")["items"]), 1)

    def test_finalizer_role_contract_keeps_newman_before_eli5_and_run_support(self) -> None:
        runtime = fixture_helpers.load_runtime_module()
        self.assertEqual(
            runtime.autopilot.ROLE_CONTRACTS["finalizer"], ("prompt", "finalize-role.md")
        )
        contract = (runtime.plugin_root() / "core" / "prompts" / "finalize-role.md").read_text(
            encoding="utf-8"
        )
        order = contract.split("## Order of operations", 1)[1]
        self.assertLess(order.index("Newman"), order.index("ELI5"))
        self.assertIn("Newman precedes ELI5", contract)
        for required in ("delivery newman", "delivery check --final", "delivery finalize",
                         "validate", "Every WORK disposition"):
            self.assertIn(required, contract)
        run_skill = (runtime.plugin_root() / "skills" / "run" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("finalize", run_skill)
        self.assertIn("delivery newman", run_skill)

    def test_finalizer_still_sees_the_injected_work_documents(self) -> None:
        self.seed_work(3)
        status = run(self.root, "status", "sample", "--json")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(
            json.loads(status.stdout)["next_action"]["command"], "finalize"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)