#!/usr/bin/env python3
"""One discovery entry point for DevFlow regression tests.

The default profile executes every discovered test exactly once. Smaller profiles
are explicitly partial and are intended for rapid local feedback, not release gates.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Iterable

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

PROFILES = ("full", "focused", "legacy", "newman")


def flatten(suite: unittest.TestSuite) -> Iterable[unittest.case.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def collect_cases(directory: Path = TEST_DIR) -> list[unittest.case.TestCase]:
    """Collect once, rejecting missing or duplicated cases before execution."""
    discovered = list(
        flatten(unittest.TestLoader().discover(str(directory), pattern="test_*.py"))
    )
    if not discovered:
        raise ValueError("no DevFlow regression tests were discovered")
    names = [case.id() for case in discovered]
    duplicates = sorted(
        name for name, count in collections.Counter(names).items() if count > 1
    )
    if duplicates:
        raise ValueError("duplicate DevFlow regression test IDs: " + ", ".join(duplicates))
    return sorted(discovered, key=lambda case: case.id())


def _profile_for(name: str) -> str:
    if ".LifecycleCases." in name:
        return "legacy"
    if ".RealNewmanTests." in name:
        return "newman"
    return "focused"


def select_cases(
    cases: Iterable[unittest.case.TestCase],
    profile: str = "full",
    matches: Iterable[str] = (),
) -> list[unittest.case.TestCase]:
    """Partition by one profile; optional substrings narrow that partition."""
    if profile not in PROFILES:
        raise ValueError(f"unsupported DevFlow test profile: {profile}")
    patterns = tuple(matches)
    selected = [
        case
        for case in cases
        if (profile == "full" or _profile_for(case.id()) == profile)
        and (not patterns or any(pattern in case.id() for pattern in patterns))
    ]
    if not selected:
        raise ValueError("no DevFlow tests match the selected profile and filters")
    return selected


class RecordingResult(unittest.TextTestResult):
    """Machine-readable results without logging stdout or private test fixtures."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows: list[dict[str, object]] = []
        self._started: dict[unittest.case.TestCase, float] = {}
        self._outcomes: dict[unittest.case.TestCase, str] = {}

    def startTest(self, test):
        self._started[test] = time.monotonic()
        super().startTest(test)

    def addSuccess(self, test):
        self._outcomes[test] = "passed"
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._outcomes[test] = "failed"
        super().addFailure(test, err)

    def addError(self, test, err):
        self._outcomes[test] = "error"
        super().addError(test, err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            self._outcomes[test] = (
                "failed" if issubclass(err[0], test.failureException) else "error"
            )
        super().addSubTest(test, subtest, err)

    def addSkip(self, test, reason):
        self._outcomes[test] = "skipped"
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self._outcomes[test] = "expected_failure"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self._outcomes[test] = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def stopTest(self, test):
        started = self._started.pop(test, time.monotonic())
        self.rows.append(
            {
                "id": test.id(),
                "status": self._outcomes.pop(test, "error"),
                "seconds": round(max(0.0, time.monotonic() - started), 3),
            }
        )
        super().stopTest(test)


def write_report(path: Path, report: dict) -> None:
    """Replace the report atomically to avoid mistaking a partial write for success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=".devflow-test-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=PROFILES, default="full",
        help="full is the only complete release gate; others are partial selections",
    )
    parser.add_argument(
        "--match", action="append", default=[], metavar="SUBSTRING",
        help="select tests whose full unittest ID contains SUBSTRING (repeatable)",
    )
    parser.add_argument("--list", action="store_true", help="list without executing")
    parser.add_argument("--report", type=Path, help="write an atomic JSON execution report")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        if any(not part for part in args.match):
            raise ValueError("--match requires a nonempty substring")
        discovered = collect_cases()
        selected = select_cases(discovered, args.profile, args.match)
    except ValueError as exc:
        print(f"DevFlow test selection error: {exc}", file=sys.stderr)
        return 2

    complete = args.profile == "full" and not args.match
    label = "complete" if complete else "PARTIAL"
    print(
        f"DevFlow {label} suite: {len(selected)}/{len(discovered)} tests"
        f" (profile={args.profile})", file=sys.stderr,
    )
    if args.list:
        for case in selected:
            print(case.id())
        return 0

    started = time.monotonic()
    runner = unittest.TextTestRunner(
        verbosity=2 if args.verbose else 1, resultclass=RecordingResult,
    )
    result = runner.run(unittest.TestSuite(selected))
    executed = sum(row["status"] != "skipped" for row in result.rows)
    if executed == 0:
        print("DevFlow test selection ran no tests: all cases were skipped", file=sys.stderr)
    if args.report:
        report = {
            "schema_version": 1,
            "profile": args.profile,
            "complete": complete,
            "discovered": len(discovered),
            "selected": len(selected),
            "run": result.testsRun,
            "executed": executed,
            "passed": sum(row["status"] == "passed" for row in result.rows),
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "unexpected_successes": len(result.unexpectedSuccesses),
            "seconds": round(time.monotonic() - started, 3),
            "tests": result.rows,
        }
        write_report(args.report, report)
    if executed == 0:
        return 2  # A completely skipped selection is not a successful test run.
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
