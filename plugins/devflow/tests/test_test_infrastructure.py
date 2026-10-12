#!/usr/bin/env python3
"""Guards against reintroducing duplicate collection or dropping legacy cases."""

from __future__ import annotations

import unittest

import run_suite
import test_devflow as legacy


class TestDiscoveryContract(unittest.TestCase):
    def test_no_duplicate_or_inherited_cases_and_all_legacy_cases_are_discovered(self):
        tests = run_suite.collect_cases()
        test_ids = [test.id() for test in tests]
        self.assertEqual(len(test_ids), len(set(test_ids)), "duplicate unittest IDs")

        legacy_methods = {
            test._testMethodName
            for test in tests
            if type(test).__name__ == "LifecycleCases"
        }
        self.assertEqual(
            legacy_methods,
            {f"test_{case.__name__}" for case in legacy.CASES},
            "missing or unexpected legacy lifecycle scenarios",
        )
        self.assertEqual(
            sum(type(test).__name__ == "LifecycleCases" for test in tests),
            len(legacy.CASES),
            "legacy scenarios must be collected once each",
        )

        for test in tests:
            cls = type(test)
            if cls.__name__ in {"FinalizationTests", "RealNewmanTests"}:
                self.assertIn(
                    test._testMethodName,
                    cls.__dict__,
                    f"{cls.__name__} inherited a test rather than only fixtures",
                )

    def test_partial_profiles_partition_full_discovery_exactly_once(self):
        all_cases = run_suite.collect_cases()
        complete = run_suite.select_cases(all_cases, "full")
        partials = [
            run_suite.select_cases(all_cases, profile)
            for profile in ("focused", "legacy", "newman")
        ]
        identifiers = [test.id() for tests in partials for test in tests]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(set(identifiers), {test.id() for test in complete})
        self.assertEqual(len(identifiers), len(complete))


if __name__ == "__main__":
    unittest.main(verbosity=2)
