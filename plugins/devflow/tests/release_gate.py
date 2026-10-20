#!/usr/bin/env python3
"""Run and verify one complete DevFlow regression suite before merge or release.

Unlike a standalone unittest exit status, this gate verifies exact discovery coverage,
report consistency, required regression families, optional Newman evidence, and a
stable source snapshot across the test run. It never mutates lifecycle artifacts.
"""

from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import run_suite

TEST_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = TEST_DIR.parent
MIN_LEGACY_CASES = 171
MIN_REAL_NEWMAN_CASES = 3
REQUIRED_MODULES = frozenset({
    "test_autopilot", "test_delivery", "test_finalization", "test_host_autopilot",
    "test_hosted_guard", "test_hosted_session", "test_lifecycle_cases",
    "test_newman_classification", "test_newman_integration", "test_scout_contract",
    "test_suite_runner", "test_test_infrastructure", "test_release_gate",
    "test_docs_consistency", "test_documentation_history",
})
SOURCE_SUFFIXES = frozenset({
    ".py", ".md", ".yaml", ".yml", ".json", ".toml", ".txt", ".sh",
    ".js", ".ts", ".mjs", ".cjs",
})
EXCLUDED_PARTS = frozenset({
    ".git", ".devflow", ".pytest_cache", "__pycache__", ".mypy_cache",
    ".ruff_cache", "node_modules", ".venv", "venv", "dist", "build",
})
OUTCOMES = frozenset({
    "passed", "failed", "error", "skipped", "expected_failure", "unexpected_success",
})


def source_snapshot(plugin_root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    """Hash plugin source and contracts, excluding generated/private runtime files."""
    files = sorted(
        path for path in plugin_root.rglob("*")
        if path.suffix in SOURCE_SUFFIXES
        and not any(part in EXCLUDED_PARTS or part.startswith(".")
                    for part in path.relative_to(plugin_root).parts)
        and (path.is_file() or path.is_symlink())
    )
    sha = hashlib.sha256()
    file_sha256: dict[str, str] = {}
    for path in files:
        if path.is_symlink():
            raise ValueError("plugin source contains a symlink: " + str(path.relative_to(plugin_root)))
        name = path.relative_to(plugin_root).as_posix()
        relative = name.encode("utf-8")
        payload = path.read_bytes()
        file_sha256[name] = hashlib.sha256(payload).hexdigest()
        sha.update(len(relative).to_bytes(4, "big"))
        sha.update(relative)
        sha.update(len(payload).to_bytes(8, "big"))
        sha.update(payload)
    return {"sha256": sha.hexdigest(), "files": len(files), "file_sha256": file_sha256}


def changed_source_paths(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Name added, removed, and changed source files without exposing content."""
    old = before.get("file_sha256", {})
    new = after.get("file_sha256", {})
    return sorted(path for path in old.keys() | new.keys() if old.get(path) != new.get(path))


def compatibility_checks(plugin_root: Path = PLUGIN_ROOT) -> list[str]:
    """Fail closed when the published Python 3.10 source contract cannot parse."""
    issues: list[str] = []
    if sys.version_info < (3, 10):
        issues.append("python_3_10_required")
    for path in sorted(plugin_root.rglob("*.py")):
        if any(part in EXCLUDED_PARTS for part in path.relative_to(plugin_root).parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path),
                      feature_version=(3, 10))
        except (OSError, SyntaxError, UnicodeError, ValueError):
            issues.append("python_3_10_syntax_invalid:" + path.relative_to(plugin_root).as_posix())
    return issues


def provenance(plugin_root: Path = PLUGIN_ROOT) -> dict[str, Any]:
    """Record HEAD and plugin dirtiness without including private file contents."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=plugin_root,
        capture_output=True, text=True, check=False,
    )
    changes = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "."],
        cwd=plugin_root, capture_output=True, text=True, check=False,
    )
    return {
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "plugin_clean": changes.returncode == 0 and not changes.stdout.strip(),
        "git_available": head.returncode == 0 and changes.returncode == 0,
    }


def assess_suite(
    report: Any, expected_ids: list[str], *, mode: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Validate coverage and all individual outcomes; never trust summary counts alone."""
    blockers: list[str] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {"discovered": len(expected_ids), "newman": "missing"}
    if mode not in {"merge", "release"}:
        raise ValueError("unsupported gate mode")
    if not isinstance(report, dict):
        return ["suite_report_invalid"], warnings, summary
    rows = report.get("tests")
    if not isinstance(rows, list) or not rows:
        return ["suite_report_tests_missing"], warnings, summary
    if not all(
        isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and row["id"]
        and row.get("status") in OUTCOMES
        and type(row.get("seconds")) in {int, float}
        and row["seconds"] >= 0
        for row in rows
    ):
        return ["suite_report_test_rows_invalid"], warnings, summary

    names = [row["id"] for row in rows]
    counts = collections.Counter(row["status"] for row in rows)
    summary.update({
        "run": len(rows), "passed": counts["passed"], "skipped": counts["skipped"],
        "failed": counts["failed"], "errors": counts["error"],
    })
    if (
        report.get("schema_version") != 1
        or report.get("profile") != "full"
        or report.get("complete") is not True
    ):
        blockers.append("suite_not_full_unfiltered")
    if len(set(names)) != len(names):
        blockers.append("suite_test_ids_duplicated")
    if set(names) != set(expected_ids) or len(names) != len(expected_ids):
        blockers.append("suite_discovery_mismatch")
    required_counts = {
        "discovered": len(expected_ids), "selected": len(expected_ids),
        "run": len(rows), "executed": len(rows) - counts["skipped"],
        "passed": counts["passed"], "skipped": counts["skipped"],
        "unexpected_successes": counts["unexpected_success"],
    }
    if any(type(report.get(key)) is not int or report[key] != expected
           for key, expected in required_counts.items()):
        blockers.append("suite_summary_counts_inconsistent")
    if (
        type(report.get("failures")) is not int
        or type(report.get("errors")) is not int
        or report["failures"] < counts["failed"]
        or report["errors"] < counts["error"]
    ):
        blockers.append("suite_failure_counts_inconsistent")
    if not names or counts["passed"] == 0:
        blockers.append("suite_no_executed_passes")
    if (
        counts["failed"] or counts["error"] or counts["unexpected_success"]
        or counts["expected_failure"]
        or report.get("failures") != 0 or report.get("errors") != 0
        or report.get("unexpected_successes") != 0
    ):
        blockers.append("suite_tests_not_all_passing")

    modules = {name.split(".", 1)[0] for name in expected_ids}
    missing = sorted(REQUIRED_MODULES - modules)
    if missing:
        blockers.append("required_regression_modules_missing:" + ",".join(missing))
    legacy = sum(".LifecycleCases." in name for name in expected_ids)
    if legacy < MIN_LEGACY_CASES:
        blockers.append("legacy_lifecycle_coverage_shrunk")
    newman = [row for row in rows if ".RealNewmanTests." in row["id"]]
    if len(newman) < MIN_REAL_NEWMAN_CASES:
        blockers.append("real_newman_smoke_coverage_missing")
    skipped = [row["id"] for row in rows if row["status"] == "skipped"]
    unexplained = [name for name in skipped if ".RealNewmanTests." not in name]
    if unexplained:
        blockers.append("unexpected_skipped_tests")
    if any(row["status"] == "skipped" for row in newman):
        summary["newman"] = "partial_or_skipped"
        if mode == "release":
            blockers.append("release_requires_real_newman_smoke")
        else:
            warnings.append("real_newman_smoke_not_fully_executed")
    else:
        summary["newman"] = "executed" if newman else "missing"
    return sorted(set(blockers)), sorted(set(warnings)), summary


def validate_report(report: Any, *, mode: str, cases: list[Any] | None = None) -> dict[str, Any]:
    """Standalone decision function for deterministic, fixture-based regression tests."""
    discovered = run_suite.collect_cases() if cases is None else cases
    expected_ids = [case.id() for case in discovered]
    blockers, warnings, summary = assess_suite(report, expected_ids, mode=mode)
    return {
        "verdict": "blocked" if blockers else "pass",
        "blockers": blockers, "warnings": warnings, "coverage": summary,
    }


def _evaluate_fresh(mode: str, suite_path: Path) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    before = source_snapshot()
    syntax = compatibility_checks()
    repo_before = provenance()
    if syntax:
        blockers.extend(syntax)
    suite_path.parent.mkdir(parents=True, exist_ok=True)
    # No shared reports or previous results are accepted as release evidence.
    suite_path.unlink(missing_ok=True)
    completed = subprocess.run(
        [sys.executable, str(TEST_DIR / "run_suite.py"),
         "--profile", "full", "--report", str(suite_path)], check=False,
    )
    after = source_snapshot()
    repo_after = provenance()
    changed_paths = changed_source_paths(before, after)
    if before != after:
        blockers.append("plugin_source_changed_during_suite")
    if not (repo_before["git_available"] and repo_after["git_available"]):
        blockers.append("git_provenance_unavailable")
    elif repo_before["head"] != repo_after["head"]:
        blockers.append("git_head_changed_during_suite")
    if mode == "release" and not (
        repo_before["plugin_clean"] and repo_after["plugin_clean"]
    ):
        blockers.append("release_requires_clean_plugin_tree")
    if completed.returncode != 0:
        blockers.append("full_suite_exited_nonzero")
    raw: Any = None
    suite_hash: str | None = None
    if suite_path.is_file():
        data = suite_path.read_bytes()
        suite_hash = hashlib.sha256(data).hexdigest()
        try:
            raw = json.loads(data)
        except (UnicodeError, ValueError):
            blockers.append("suite_report_not_json")
    else:
        blockers.append("suite_report_missing")
    try:
        assessment = validate_report(raw, mode=mode)
        blockers.extend(assessment["blockers"])
        warnings.extend(assessment["warnings"])
        coverage = assessment["coverage"]
    except Exception:
        blockers.append("suite_discovery_unavailable")
        coverage = {}
    return {
        "schema_version": 1,
        "mode": mode,
        "verdict": "blocked" if blockers else "pass",
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "coverage": coverage,
        "evidence": {
            "suite_report": str(suite_path),
            "suite_sha256": suite_hash,
            "plugin_sha256": after["sha256"],
            "plugin_sha256_before": before["sha256"],
            "source_file_count": after["files"],
            "changed_source_paths": changed_paths,
            "head_before": repo_before["head"],
            **repo_after,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("merge", "release"), default="merge")
    parser.add_argument(
        "--report", type=Path,
        help="persist verdict JSON and sibling .suite.json; otherwise use temporary evidence",
    )
    args = parser.parse_args(argv)
    try:
        if args.report:
            suite_path = args.report.with_name(args.report.stem + ".suite.json")
            if args.report.resolve() == suite_path.resolve():
                raise ValueError("verdict and suite paths cannot be identical")
            verdict = _evaluate_fresh(args.mode, suite_path)
            run_suite.write_report(args.report, verdict)
        else:
            with tempfile.TemporaryDirectory(prefix="devflow-release-") as temporary:
                verdict = _evaluate_fresh(args.mode, Path(temporary) / "suite.json")
                # Temporary suite evidence is not retained or represented as a durable path.
                verdict["evidence"]["suite_report"] = None
    except (OSError, ValueError) as exc:
        print("DevFlow release gate error: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
