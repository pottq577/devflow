#!/usr/bin/env python3
"""Contract-preserving documentation lint and its release-gate discovery."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_docs  # noqa: E402
import measure_role_packets  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


class DocumentationConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="devflow-doc-lint-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugins/devflow"
        self.version = "2.3.4"  # Fixture values are independent of the current release.
        self.protocol = "4.5.6"
        self.seed_valid_tree()

    def write(self, name: str, data: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")

    def put_json(self, name: str, data: dict) -> None:
        self.write(name, json.dumps(data))

    def seed_valid_tree(self) -> None:
        self.write("README.md", "# Test marketplace\n[version](plugins/devflow/version.json)\n"
                   "[plugin](plugins/devflow/README.md)\n")
        self.write("AGENTS.md", "# Rules\n")
        self.write("CLAUDE.md", "# Adapter\n")
        self.write("plugins/devflow/README.md", "[version](version.json)\n"
                   "[Protocol](core/protocol/lifecycle.md#heading)\n")
        self.put_json("plugins/devflow/version.json", {"plugin": self.version, "protocol": self.protocol})
        self.write("plugins/devflow/scripts/devflow.py", f'PROTOCOL_VERSION = "{self.protocol}"\n')
        versions = {"name": "devflow", "version": self.version}
        self.put_json("plugins/devflow/.claude-plugin/plugin.json", versions)
        self.put_json("plugins/devflow/.codex-plugin/plugin.json", versions)
        self.put_json(".claude-plugin/marketplace.json", {
            "version": self.version,
            "plugins": [{"name": "devflow", "version": self.version, "source": "./plugins/devflow"}],
        })
        self.put_json(".agents/plugins/marketplace.json", {
            "plugins": [{"name": "devflow", "source": {"path": "./plugins/devflow"}}],
        })
        rules = ("authority.md", "lifecycle.md", "work-item-contract.md", "decision-policy.md",
                 "risk-policy.md", "audit-core.md", "delivery-artifacts.md", "finalization.md",
                 "host-telemetry.md", "release-validation.md", "skill-composition.md")
        schema = ("audit.schema.yaml", "finding.schema.yaml", "work.schema.yaml", "state.schema.yaml",
                  "routing.schema.yaml", "model-registry.schema.yaml", "host-telemetry.schema.yaml")
        matrix = "# Ownership\n" + "\n".join(
            f"- `core/protocol/{f}`" for f in rules
        ) + "\n" + "\n".join(f"- `core/schemas/{f}`" for f in schema) + "\n"
        self.write("plugins/devflow/core/protocol/role-instructions.md", matrix)
        for name in rules:
            self.write(f"plugins/devflow/core/protocol/{name}", f"# {name}\n")
        for name in schema:
            self.write(f"plugins/devflow/core/schemas/{name}", "type: object\n")
        for name in check_docs.SKILLS:
            pointer = " ".join(check_docs.ROLE_POINTERS[f"skills/{name}/SKILL.md"])
            self.write(f"plugins/devflow/skills/{name}/SKILL.md",
                       f"---\nname: {name}\ndescription: Perform this DevFlow {name} workflow with observed evidence.\n---\n"
                       f"# {name}\n{pointer}\n")
            if name != "goal":
                self.write(f"plugins/devflow/skills/{name}/scripts/invoke.py", "# adapter\n")
        for path, tokens in check_docs.ROLE_POINTERS.items():
            if path.startswith("core/"):
                self.write(f"plugins/devflow/{path}", "# role\n" + " ".join(tokens) + "\n")
        metadata = "---\nschema: devflow-audit-v1\n" + "".join(
            f"{field}: null\n" for field in check_docs.NULL_AUDIT_FIELDS
        ) + "".join(f"{field}: []\n" for field in check_docs.EMPTY_AUDIT_FIELDS) + "---\n"
        self.write("plugins/devflow/core/templates/AUDIT.md", metadata + "\n" +
                   "".join(f"### {c}. Axis\n" for c in "ABCDEFGHIJ"))
        self.write("plugins/devflow/core/templates/PITFALLS.md",
                   "no observed pitfalls. Examples are not repository facts.\n")

    def test_clean_fixture_is_repeatable(self) -> None:
        first = check_docs.check_repository(self.root)
        second = check_docs.check_repository(self.root)
        self.assertEqual(first, second)
        self.assertEqual(first["errors"], [])
        self.assertEqual(first["versions"]["protocol"], self.protocol)
        self.assertEqual(first["versions"]["source_plugin"], self.version)
        self.assertTrue(first["duplicate_candidates_are_advisory"])

    def test_relative_link_paths_and_fenced_examples(self) -> None:
        self.write("README.md", (self.root / "README.md").read_text() +
                   "[missing](no-such-file.md)\n")
        self.assertIn("broken relative link", " ".join(check_docs.check_repository(self.root)["errors"]))
        self.write("README.md", "[fine](plugins/devflow/README.md#section)\n"
                   "```md\n[fake](does-not-exist.md)\n```\n"
                   "[external](https://example.com/docs)\n[version](plugins/devflow/version.json)\n")
        self.assertFalse(any("broken relative link" in error
                             for error in check_docs.check_repository(self.root)["errors"]))
        self.write("README.md", "[escape](../../etc/passwd)\n[version](plugins/devflow/version.json)\n")
        self.assertTrue(any("broken relative link" in error
                            for error in check_docs.check_repository(self.root)["errors"]))

    def test_dangling_ownership_and_role_contract_are_blocked(self) -> None:
        path = self.plugin / "core/protocol/role-instructions.md"
        path.write_text(path.read_text() + "\n`core/protocol/ghost.md`\n")
        errors = check_docs.check_repository(self.root)["errors"]
        self.assertTrue(any("ghost.md" in e for e in errors), errors)
        run = self.plugin / "core/prompts/run.md"
        run.write_text("# executor\n")
        errors = check_docs.check_repository(self.root)["errors"]
        self.assertTrue(any("missing required role contract reference: start_sha" in e
                            for e in errors), errors)

    def test_version_and_shared_adapters_must_agree(self) -> None:
        self.put_json("plugins/devflow/.codex-plugin/plugin.json", {"version": "0.0.0"})
        errors = check_docs.check_repository(self.root)["errors"]
        self.assertTrue(any("versions disagree" in e for e in errors), errors)
        self.put_json("plugins/devflow/.codex-plugin/plugin.json", {"version": self.version})
        self.put_json("plugins/devflow/version.json", {"plugin": "2.3.5", "protocol": self.protocol})
        self.assertTrue(any("version.json" in e for e in check_docs.check_repository(self.root)["errors"]))
        self.put_json("plugins/devflow/version.json", {"plugin": self.version, "protocol": self.protocol})
        self.put_json(".agents/plugins/marketplace.json", {
            "version": self.version, "plugins": [{"source": {"path": "./plugins/devflow"}}]
        })
        self.assertTrue(any("must not own" in e for e in check_docs.check_repository(self.root)["errors"]))

    def test_skill_metadata_and_audit_scaffold_fail_closed(self) -> None:
        self.write("plugins/devflow/skills/run/SKILL.md", "---\nname: wrong\ndescription: x\n---\n")
        errors = check_docs.check_repository(self.root)["errors"]
        self.assertTrue(any("incorrect skill name" in e for e in errors), errors)
        template = self.plugin / "core/templates/AUDIT.md"
        template.write_text(template.read_text().replace("verdict: null", "verdict: pass"))
        errors = check_docs.check_repository(self.root)["errors"]
        self.assertTrue(any("unsafe placeholder: verdict" in e for e in errors), errors)

    def test_duplicate_policy_copy_is_report_only(self) -> None:
        policy = ("Always confirm the selected evidence against repository state and keep the audited "
                  "work item inside its preapproved scope without broadening production change permissions.")
        self.write("plugins/devflow/core/protocol/authority.md", policy + "\n")
        self.write("plugins/devflow/core/prompts/plan.md",
                   " ".join(check_docs.ROLE_POINTERS["core/prompts/plan.md"]) + "\n" + policy + "\n")
        report = check_docs.check_repository(self.root)
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(report["duplicate_candidates"]), 1)
        self.assertEqual(len(report["duplicate_candidates"][0]["sources"]), 2)

    def test_command_exit_status_reflects_gate_only(self) -> None:
        # These diagnostics belong to an intentionally broken temporary fixture,
        # not to the checkout under the full release gate.
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(check_docs.main(["--root", str(self.root)]), 0)
            (self.plugin / "skills/status/SKILL.md").unlink()
            self.assertEqual(check_docs.main(["--root", str(self.root)]), 1)
        self.assertIn("skills/status/SKILL.md", captured.getvalue())

    def test_real_packet_measurement_math_and_markers(self) -> None:
        self.assertEqual(measure_role_packets.percent_delta(100, 75), -25.0)
        self.assertEqual(measure_role_packets.percent_delta(100, 125), 25.0)
        self.assertIsNone(measure_role_packets.percent_delta(0, 20))
        self.assertEqual(measure_role_packets.verify_packet(
            "finalize", b"$eli5 / Newman / WORK manifest page"), [])
        self.assertIn("WORK manifest page", measure_role_packets.verify_packet(
            "finalize", b"$eli5 and Newman"))

    def test_packet_measurement_runs_isolated_git_snapshots(self) -> None:
        # Test the benchmark transport with a deterministic fake CLI. The
        # checked-out real CLI is measured separately by the user command.
        self.write("plugins/devflow/scripts/devflow.py", """#!/usr/bin/env python3
import sys
from pathlib import Path
import yaml
args = sys.argv[1:]
if args[0] == 'init':
    home = Path.cwd() / 'docs/domains/sample'
    home.mkdir(parents=True, exist_ok=True)
    (home / 'STATE.yaml').write_text(yaml.safe_dump({'phases': {}, 'integration': {}}))
elif args[0] == 'render':
    print({'plan': 'DevFlow lifecycle WORK item contract',
           'run': 'WORK item contract P01-I01',
           'audit': 'AUDIT core Default domain audit extension',
           'finalize': '$eli5 Newman WORK manifest page',
           'evidence': 'P01-I01'}[args[1]])
""")
        for args in (("init", "-q"), ("config", "user.name", "Fixture"),
                     ("config", "user.email", "fixture@example.invalid"),
                     ("add", "-A"), ("commit", "-qm", "baseline")):
            subprocess.run(["git", *args], cwd=self.root, check=True,
                           capture_output=True)
        report = measure_role_packets.measure(self.root, "HEAD")
        self.assertEqual(set(report["measurements"]), set(measure_role_packets.MARKERS))
        self.assertTrue(all(row["delta_utf8_bytes"] == 0
                            for row in report["measurements"].values()))
        self.assertIn("model tokens", report["not_measured"])

    def test_checked_out_repository_contract(self) -> None:
        """Automatically discovered by the full merge/release gate."""
        if not (ROOT / "plugins/devflow/scripts/devflow.py").exists():
            self.skipTest("Running outside the complete DevFlow repository")
        report = check_docs.check_repository(ROOT)
        self.assertEqual(report["errors"], [], "\n".join(report["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
