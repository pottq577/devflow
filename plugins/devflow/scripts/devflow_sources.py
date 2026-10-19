"""Capture and verify a domain's original requirements and supplemental context.

The v1 capture is write-once. Later source revisions must use an explicit
revision operation; a changed input must never replace historical evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

MAX_SOURCE_BYTES = 8 * 1024 * 1024
SOURCE_ROLES = ("original", "context")
SOURCE_REVISION = "v1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class SourceError(ValueError):
    """Source evidence is incomplete, stale or inconsistent."""


def _read_input(path: Path) -> tuple[Path, bytes]:
    path = path.expanduser()
    if path.is_symlink():
        raise SourceError(f"Source input cannot be a symlink: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SourceError(f"Source input unavailable: {path}: {exc}") from exc
    if not resolved.is_file() or resolved.suffix.lower() not in {".md", ".txt"}:
        raise SourceError(f"Source must be a Markdown or text file: {path}")
    size = resolved.stat().st_size
    if size < 1 or size > MAX_SOURCE_BYTES:
        raise SourceError(f"Source size must be 1..{MAX_SOURCE_BYTES} bytes: {path}")
    data = resolved.read_bytes()
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise SourceError(f"Invalid source size: {path}")
    try:
        data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceError(f"Source is not UTF-8: {path}") from exc
    return resolved, data


def _source_path(root: Path, path: Path) -> str:
    root = root.resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _snapshot_dir(domain_dir: Path) -> Path:
    sources_dir = domain_dir / "sources"
    snapshot_dir = sources_dir / SOURCE_REVISION
    if sources_dir.is_symlink() or snapshot_dir.is_symlink():
        raise SourceError("Source evidence directory cannot be a symlink")
    if sources_dir.exists() and not sources_dir.is_dir():
        raise SourceError("Source evidence path is not a directory")
    return snapshot_dir


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise SourceError(f"Duplicate source manifest field: {key}")
        obj[key] = value
    return obj


def _load_manifest(snapshot_dir: Path, domain: str) -> dict[str, Any]:
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SourceError("Source manifest is missing or is a symlink")
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_pairs,
        )
    except (OSError, ValueError, UnicodeError) as exc:
        raise SourceError(f"Invalid source manifest: {exc}") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
        or manifest.get("domain") != domain
        or manifest.get("revision") != SOURCE_REVISION
        or not isinstance(manifest.get("sources"), dict)
        or set(manifest["sources"]) != set(SOURCE_ROLES)
    ):
        raise SourceError("Source manifest has an unsupported shape or domain")
    return manifest


def verify(
    root: Path, domain_dir: Path, domain: str, *, check_source: bool = False
) -> dict[str, Any]:
    """Check captured bytes; optionally detect changes in the original input files."""
    snapshot_dir = _snapshot_dir(domain_dir)
    if not snapshot_dir.is_dir():
        raise SourceError(f"Source snapshot not found: {snapshot_dir}")
    manifest = _load_manifest(snapshot_dir, domain)
    for role in SOURCE_ROLES:
        record = manifest["sources"][role]
        expected = f"{role}.md"
        if (
            not isinstance(record, dict)
            or record.get("snapshot") != expected
            or not isinstance(record.get("source_path"), str)
            or not record["source_path"].strip()
            or not isinstance(record.get("sha256"), str)
            or not SHA256.fullmatch(record["sha256"])
            or type(record.get("size_bytes")) is not int
            or not 1 <= record["size_bytes"] <= MAX_SOURCE_BYTES
        ):
            raise SourceError(f"Invalid source manifest entry: {role}")
        snapshot = snapshot_dir / expected
        if snapshot.is_symlink() or not snapshot.is_file():
            raise SourceError(f"Source snapshot missing or symlinked: {role}")
        raw = snapshot.read_bytes()
        if (
            len(raw) != record["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != record["sha256"]
        ):
            raise SourceError(f"Source snapshot hash mismatch: {role}")
        if check_source:
            input_path = Path(record["source_path"])
            if not input_path.is_absolute():
                input_path = root / input_path
            try:
                actual_path, current = _read_input(input_path)
            except (OSError, SourceError) as exc:
                raise SourceError(f"Source input unavailable: {role}: {exc}") from exc
            if (
                _source_path(root, actual_path) != record["source_path"]
                or hashlib.sha256(current).hexdigest() != record["sha256"]
            ):
                raise SourceError(f"Source input changed since capture: {role}")
    return {
        "status": "verified",
        "domain": domain,
        "revision": SOURCE_REVISION,
        "manifest": str(snapshot_dir / "manifest.json"),
        "sources": manifest["sources"],
    }


def capture(
    root: Path, domain_dir: Path, domain: str, original: Path, context: Path
) -> dict[str, Any]:
    """Atomically register one immutable v1 source pair, or verify an exact retry."""
    original_path, original_bytes = _read_input(original)
    context_path, context_bytes = _read_input(context)
    if original_path == context_path:
        raise SourceError("Original and supplemental context must be different files")
    inputs = {"original": (original_path, original_bytes), "context": (context_path, context_bytes)}
    sources = {
        role: {
            "snapshot": f"{role}.md",
            "source_path": _source_path(root, path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
        for role, (path, data) in inputs.items()
    }
    snapshot_dir = _snapshot_dir(domain_dir)
    if snapshot_dir.exists():
        current = verify(root, domain_dir, domain)
        if current["sources"] != sources:
            raise SourceError(
                "Captured sources differ; v1 is immutable. Register a new revision instead."
            )
        return {**current, "status": "unchanged"}

    sources_dir = snapshot_dir.parent
    sources_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".capture-", dir=sources_dir))
    try:
        for role in SOURCE_ROLES:
            (stage / f"{role}.md").write_bytes(inputs[role][1])
        manifest = {
            "schema_version": 1,
            "domain": domain,
            "revision": SOURCE_REVISION,
            "sources": sources,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if snapshot_dir.exists():
            raise SourceError("Source snapshot was concurrently created; retry verification")
        stage.rename(snapshot_dir)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {**verify(root, domain_dir, domain), "status": "captured"}
