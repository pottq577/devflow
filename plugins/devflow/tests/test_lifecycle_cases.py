#!/usr/bin/env python3
"""Expose the unchanged, self-checking lifecycle scenarios to unittest discovery.

Legacy checks append failures to a list instead of raising. Each adapter method
captures its own failures and keeps the legacy direct runner available unchanged.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import unittest

import test_devflow as legacy


class LifecycleCases(unittest.TestCase):
    def run_legacy_case(self, case):
        root = legacy.new_repo()
        passed_before = len(legacy.PASSED)
        failed_before = len(legacy.FAILED)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                case(root)
            self.assertEqual(
                legacy.FAILED[failed_before:],
                [],
                f"{case.__name__} failed:\n{output.getvalue()}",
            )
        finally:
            del legacy.PASSED[passed_before:]
            del legacy.FAILED[failed_before:]
            shutil.rmtree(root, ignore_errors=True)


def _adapt_case(case):
    def test_case(self):
        self.run_legacy_case(case)

    test_case.__name__ = f"test_{case.__name__}"
    test_case.__doc__ = case.__doc__
    return test_case


for _case in legacy.CASES:
    setattr(LifecycleCases, f"test_{_case.__name__}", _adapt_case(_case))


if __name__ == "__main__":
    unittest.main(verbosity=2)
