#!/usr/bin/env python3
"""Version metadata stays single-sourced across distribution adapters."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_version  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


class ReleaseVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="devflow-version-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugins/devflow"
        self.write("plugins/devflow/version.json", '{"plugin":"2.3.4","protocol":"4.5.6"}\n')
        self.write(".claude-plugin/marketplace.json", json.dumps({
            "version": "2.3.4", "plugins": [{"name": "devflow", "version": "2.3.4"}],
        }) + "\n")
        for adapter in (".claude-plugin", ".codex-plugin"):
            self.write(f"plugins/devflow/{adapter}/plugin.json", '{"version":"2.3.4"}\n')
        self.write("plugins/devflow/scripts/devflow.py", 'PROTOCOL_VERSION = "4.5.6"\n')
        self.write(".agents/plugins/marketplace.json", '{"plugins":[{"source": {"path":"./plugins/devflow"}}]}\n')

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def test_consistent_fixture_and_check_are_read_only(self) -> None:
        before = {path: path.read_bytes() for path, _, _ in release_version.mirror_paths(self.plugin)}
        self.assertEqual(release_version.check_versions(self.plugin), [])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_manifest_drift_blocks_until_resynced(self) -> None:
        self.write("plugins/devflow/.codex-plugin/plugin.json", '{"version":"9.9.9"}\n')
        self.assertTrue(any("codex-plugin" in x for x in release_version.check_versions(self.plugin)))
        changed = release_version.sync_versions(self.plugin)
        self.assertEqual(len(changed), 1)
        self.assertEqual(release_version.check_versions(self.plugin), [])

    def test_setting_plugin_version_updates_only_distribution_mirrors(self) -> None:
        modified = release_version.sync_versions(self.plugin, versions={
            "plugin": "2.3.5", "protocol": "4.5.6",
        })
        self.assertEqual(len(modified), 4)
        self.assertEqual(release_version.load_versions(self.plugin)["plugin"], "2.3.5")
        self.assertEqual(release_version.check_versions(self.plugin), [])
        self.assertEqual((self.plugin / "scripts/devflow.py").read_text(), 'PROTOCOL_VERSION = "4.5.6"\n')

    def test_setting_protocol_version_updates_runtime_constant(self) -> None:
        changed = release_version.sync_versions(self.plugin, versions={
            "plugin": "2.3.4", "protocol": "4.6.0",
        })
        self.assertEqual({path.name for path in changed}, {"version.json", "devflow.py"})
        self.assertEqual(release_version.check_versions(self.plugin), [])

    def test_invalid_or_reversed_semver_is_rejected(self) -> None:
        for invalid in ("v1.2.3", "1.2", "01.2.3", "1.2.3-rc1"):
            with self.assertRaises(ValueError):
                release_version.version_tuple(invalid)
        with mock.patch.object(release_version, "PLUGIN", self.plugin):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(release_version.main(["set", "--plugin", "2.3.3"]), 2)
        self.assertEqual(release_version.load_versions(self.plugin)["plugin"], "2.3.4")

    def test_missing_canonical_or_discovery_owned_version_fails_closed(self) -> None:
        (self.plugin / "version.json").unlink()
        self.assertTrue(release_version.check_versions(self.plugin))
        self.write("plugins/devflow/version.json", '{"plugin":"2.3.4","protocol":"4.5.6"}\n')
        self.write(".agents/plugins/marketplace.json", '{"version":"2.3.4","plugins":[{}]}\n')
        self.assertTrue(any("discovery adapter" in x for x in release_version.check_versions(self.plugin)))

    def test_checked_out_repository_versions_are_in_sync(self) -> None:
        if not (ROOT / "plugins/devflow/version.json").exists():
            self.skipTest("Outside a complete DevFlow checkout")
        self.assertEqual(release_version.check_versions(ROOT / "plugins/devflow"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
