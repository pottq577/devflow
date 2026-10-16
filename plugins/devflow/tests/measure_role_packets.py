#!/usr/bin/env python3
"""Measure *real* DevFlow render output bytes at a historical ref and the working tree.

No model or hosted child is invoked. This reports CLI packets and Scout's bounded
navigation render, not native end-to-end duration or model token consumption.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
FROZEN_BASELINE = "00af6394f7a7830bb9b37c6560e3ec06598e4ad0"
MARKERS = {
    "plan": ("DevFlow lifecycle", "WORK item contract"),
    "run": ("WORK item contract", "P01-I01"),
    "audit": ("AUDIT core", "Default domain audit extension"),
    "finalize": ("$eli5", "Newman", "WORK manifest page"),
    "scout_navigation": ("P01-I01",),
}


def command(argv: list[str], cwd: Path, *, env: dict[str, str] | None = None,
            timeout: int = 90) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=env, timeout=timeout, check=False)


def repo_snapshot(root: Path, revision: str, dest: Path) -> Path:
    """Read a committed source tree without checkout, branches or worktrees."""
    proc = command(["git", "archive", "--format=tar", revision, "plugins/devflow"], root)
    if proc.returncode:
        raise RuntimeError("git archive failed: " + proc.stderr.decode(errors="replace"))
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as archive:
        for member in archive:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe archive member: {member.name}")
            target = dest / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"missing archive member data: {member.name}")
                with stream, target.open("wb") as output:
                    shutil.copyfileobj(stream, output)
    return dest / "plugins/devflow"


def current_snapshot(root: Path, dest: Path) -> Path:
    source = root / "plugins/devflow"
    target = dest / "plugins/devflow"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(
        "__pycache__", ".pytest_cache", ".devflow", "*.pyc", ".ruff_cache", "dist", "build"))
    return target


def make_git_root(path: Path) -> Path:
    path.mkdir(parents=True)
    for arguments in (("init", "-q"), ("config", "user.name", "Fixture"),
                      ("config", "user.email", "fixture@example.invalid")):
        proc = command(["git", *arguments], path)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode(errors="replace"))
    (path / "seed.txt").write_text("fixed fixture\n", encoding="utf-8")
    proc = command(["git", "add", "seed.txt"], path)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    env = dict(os.environ, GIT_AUTHOR_DATE="2020-01-01T00:00:00+0000",
               GIT_COMMITTER_DATE="2020-01-01T00:00:00+0000")
    proc = command(["git", "commit", "-qm", "fixed fixture"], path, env=env)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    return path


def call_cli(repo: Path, plugin: Path, *arguments: str) -> bytes:
    proc = command([sys.executable, str(plugin / "scripts/devflow.py"), *arguments], repo)
    if proc.returncode:
        stderr = proc.stderr.decode(errors="replace")
        raise RuntimeError(f"render {arguments} exited {proc.returncode}: {stderr[-1200:]}")
    return proc.stdout


def seed_phase(repo: Path, *, status: str) -> None:
    """Use the same v1 compatibility fixture for both protocol 1.8 source revisions."""
    domain = repo / "docs/domains/sample"
    state_path = domain / "STATE.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["phases"] = {
        "01": {"status": "verified" if status == "done" else "executing",
               "work_file": "work/phase-01.yaml", "audit_file": "audits/phase-01.md"}
    }
    state["integration"] = {"status": "pending"}
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")
    item = {
        "id": "P01-I01", "kind": "implementation", "title": "Fixture item",
        "origin": {"requirements": [], "findings": [], "plan_items": []},
        "objective": "Verify fixture behavior without editing source", "dependencies": [],
        "decision_dependencies": [], "scope": {"allowed": [], "forbidden": []},
        "requirements": [], "verification": {"commands": ["true"]},
        "acceptance": ["Fixture contract remains true"], "stop_conditions": [],
        "risk": {"level": "medium", "axes": []}, "status": status,
        "block_reason": None,
        "evidence": {"commit": "a" * 40 if status == "done" else None,
                     "changed_files": ["src/example.py"] if status == "done" else [],
                     "commands": ["true -> passed"] if status == "done" else [],
                     "deviations": [], "discoveries": []},
    }
    output = domain / "work/phase-01.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump({"version": 1, "phase": "01", "items": [item]},
                                     sort_keys=False), encoding="utf-8")


def packet(plugin: Path, role: str, fixture_parent: Path) -> bytes:
    repo = make_git_root(fixture_parent / role)
    if role == "audit":
        call_cli(repo, plugin, "init", "sample", "--workflow", "audit-remediation")
        return call_cli(repo, plugin, "render", "audit", "sample", "--scope", "integration",
                        "--mode", "initial")
    call_cli(repo, plugin, "init", "sample")
    if role == "plan":
        return call_cli(repo, plugin, "render", "plan", "sample")
    if role in ("run", "scout_navigation"):
        seed_phase(repo, status="ready")
        if role == "run":
            return call_cli(repo, plugin, "render", "run", "sample")
        return call_cli(repo, plugin, "render", "evidence", "sample")
    if role == "finalize":
        seed_phase(repo, status="done")
        return call_cli(repo, plugin, "render", "finalize", "sample")
    raise ValueError("unsupported role: " + role)


def verify_packet(role: str, packet_bytes: bytes) -> list[str]:
    text = packet_bytes.decode("utf-8")
    return [marker for marker in MARKERS[role] if marker not in text]


def percent_delta(before: int, after: int) -> float | None:
    return round((after - before) / before * 100.0, 2) if before else None


def measure(root: Path, baseline: str) -> dict[str, object]:
    root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="devflow-packet-compare-") as temp:
        place = Path(temp)
        before = repo_snapshot(root, baseline, place / "baseline")
        after = current_snapshot(root, place / "candidate")
        rows: dict[str, dict[str, object]] = {}
        for role in MARKERS:
            previous = packet(before, role, place / "before-fixtures")
            current = packet(after, role, place / "after-fixtures")
            missing_before = verify_packet(role, previous)
            missing_after = verify_packet(role, current)
            if missing_before or missing_after:
                raise RuntimeError(f"{role}: missing required markers, baseline={missing_before}, candidate={missing_after}")
            rows[role] = {
                "baseline_utf8_bytes": len(previous),
                "candidate_utf8_bytes": len(current),
                "delta_utf8_bytes": len(current) - len(previous),
                "delta_percent": percent_delta(len(previous), len(current)),
                "required_markers": list(MARKERS[role]),
            }
        return {
            "schema_version": 1,
            "baseline_ref": baseline,
            "candidate": "current working-tree plugin snapshot (includes uncommitted changes)",
            "measurements": rows,
            "unit": "exact bytes of CLI render stdout on equivalent synthetic fixture paths",
            "not_measured": ["native hosted Goal elapsed time", "model tokens", "billed tokens",
                             "Scout spawn overhead", "installed ELI5 execution", "real HTTP Newman"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", default=FROZEN_BASELINE)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="write the report outside the repository")
    args = parser.parse_args(argv)
    try:
        report = measure(args.root, args.baseline_ref)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"packet measurement blocked: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
