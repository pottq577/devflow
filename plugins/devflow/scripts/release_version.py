#!/usr/bin/env python3
"""Manage DevFlow's two independent version axes from version.json.

Published plugin manifests and the runtime protocol constant are generated mirrors.
CHANGELOG.md is historical evidence and is never rewritten by this utility.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
JSON_VERSION = re.compile(r'("version"\s*:\s*")([^"]+)(")')
PYTHON_PROTOCOL = re.compile(r'(?m)^(PROTOCOL_VERSION = ")([^"]+)(")$')


def version_tuple(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not SEMVER.fullmatch(value):
        raise ValueError(f"invalid MAJOR.MINOR.PATCH version: {value!r}")
    return tuple(int(v) for v in value.split("."))


def load_versions(plugin: Path | None = None) -> dict[str, str]:
    plugin = PLUGIN if plugin is None else plugin
    path = plugin / "version.json"
    if path.is_symlink():
        raise ValueError("version.json cannot be a symlink")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"plugin", "protocol"}:
        raise ValueError("version.json must contain exactly plugin and protocol")
    for value in raw.values():
        version_tuple(value)
    return raw


def mirror_paths(plugin: Path) -> tuple[tuple[Path, int, str], ...]:
    root = plugin.parents[1]
    return (
        (root / ".claude-plugin/marketplace.json", 2, "plugin"),
        (plugin / ".claude-plugin/plugin.json", 1, "plugin"),
        (plugin / ".codex-plugin/plugin.json", 1, "plugin"),
        (plugin / "scripts/devflow.py", 1, "protocol"),
    )


def updated_mirror(path: Path, text: str, count: int, version: str, kind: str) -> str:
    if kind == "plugin":
        # Validate JSON first; replace only explicit version keys without reformatting it.
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: manifest must be an object")
        pattern = JSON_VERSION
    else:
        pattern = PYTHON_PROTOCOL
    if len(pattern.findall(text)) != count:
        raise ValueError(f"{path}: expected {count} version fields")
    return pattern.sub(lambda match: match.group(1) + version + match.group(3), text)


def check_versions(plugin: Path | None = None) -> list[str]:
    """Return precise drift diagnostics without modifying any files."""
    plugin = PLUGIN if plugin is None else plugin
    try:
        expected = load_versions(plugin)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return [f"version.json: {exc}"]
    errors: list[str] = []
    for path, count, kind in mirror_paths(plugin):
        try:
            if path.is_symlink():
                raise ValueError("symlinked mirror")
            content = path.read_text(encoding="utf-8")
            updated = updated_mirror(path, content, count, expected[kind], kind)
            if updated != content:
                errors.append(f"{path}: {kind} version differs from version.json ({expected[kind]})")
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"{path}: {exc}")
    # The Codex discovery adapter is a pointer, not a third plugin-version owner.
    discovery = plugin.parents[1] / ".agents/plugins/marketplace.json"
    try:
        metadata = json.loads(discovery.read_text(encoding="utf-8"))
        if "version" in metadata or any("version" in entry for entry in metadata["plugins"]):
            errors.append(f"{discovery}: discovery adapter must not own a version")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"{discovery}: {exc}")
    return errors


def _write(path: Path, content: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"unsafe version target: {path}")
    fd, temp = tempfile.mkstemp(prefix=".devflow-version-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sync_versions(plugin: Path | None = None, *, versions: dict[str, str] | None = None) -> list[Path]:
    plugin = PLUGIN if plugin is None else plugin
    current = load_versions(plugin)
    desired = current if versions is None else versions
    if set(desired) != {"plugin", "protocol"}:
        raise ValueError("both plugin and protocol versions are required")
    for value in desired.values():
        version_tuple(value)
    replacements: list[tuple[Path, str]] = []
    for path, count, kind in mirror_paths(plugin):
        if path.is_symlink():
            raise ValueError(f"unsafe version target: {path}")
        content = path.read_text(encoding="utf-8")
        updated = updated_mirror(path, content, count, desired[kind], kind)
        if updated != content:
            replacements.append((path, updated))
    if desired != current:
        replacements.insert(0, (plugin / "version.json", json.dumps(desired, indent=2) + "\n"))
    # Precompute and validate every file before the first write.
    for path, content in replacements:
        _write(path, content)
    return [path for path, _ in replacements]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("show", "check", "sync", "set"))
    parser.add_argument("--plugin", help="new plugin MAJOR.MINOR.PATCH (set only)")
    parser.add_argument("--protocol", help="new artifact protocol MAJOR.MINOR.PATCH (set only)")
    args = parser.parse_args(argv)
    try:
        if args.action != "set" and (args.plugin or args.protocol):
            parser.error("--plugin/--protocol are only valid with set")
        if args.action == "show":
            print(json.dumps(load_versions(), indent=2))
        elif args.action == "check":
            errors = check_versions()
            for issue in errors:
                print("ERROR: " + issue, file=sys.stderr)
            return 1 if errors else 0
        elif args.action == "sync":
            for path in sync_versions():
                print(path.relative_to(PLUGIN.parents[1]))
            return 1 if check_versions() else 0
        else:
            if not (args.plugin or args.protocol):
                parser.error("set requires --plugin or --protocol")
            current = load_versions()
            desired = dict(current)
            for kind, value in (("plugin", args.plugin), ("protocol", args.protocol)):
                if value is not None:
                    if version_tuple(value) < version_tuple(current[kind]):
                        raise ValueError(f"{kind} downgrade is forbidden")
                    desired[kind] = value
            for path in sync_versions(versions=desired):
                print(path.relative_to(PLUGIN.parents[1]))
            return 1 if check_versions() else 0
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        print("DevFlow version error: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
