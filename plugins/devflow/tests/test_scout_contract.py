#!/usr/bin/env python3
"""Validation regressions for untrusted scout pre-analysis capsules."""

from __future__ import annotations

import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "scripts" / "devflow_scout.py"
sys.path.insert(0, str(SOURCE.parent))

import devflow_host_guard as guard
import devflow_session as session
spec = importlib.util.spec_from_file_location("devflow_scout_contract_test", SOURCE)
scout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scout)

VALID = """## Action
Review plan for phase 01.

## Evidence map
- `src/service.py:42-58`: existing validation path.

## Existing patterns
- Repository uses explicit command objects.

## Constraints and risks
- Scope is limited to this domain.

## Candidate concerns
- Verify whether existing tests cover null input.

## Uncertainty
- External client compatibility is not verified.
"""


class ScoutContractTests(unittest.TestCase):
    def test_valid_six_section_capsule(self):
        self.assertEqual(scout.validated_capsule(VALID), VALID.strip())

    def test_plain_unsupported_output_does_not_replace_packet(self):
        for value in ("inspect src/service.py", "all looks good", "", None):
            with self.subTest(value=value):
                self.assertIsNone(scout.validated_capsule(value))

    def test_missing_or_out_of_order_sections_rejected(self):
        self.assertIsNone(scout.validated_capsule(VALID.replace("## Uncertainty", "## Conclusion")))
        self.assertIsNone(scout.validated_capsule(VALID.replace("## Existing patterns", "## Extra")))
        self.assertIsNone(scout.validated_capsule(VALID.replace("## Candidate concerns", "## Uncertainty")))

    def test_empty_and_nonprovenanced_evidence_rejected(self):
        self.assertIsNone(scout.validated_capsule(VALID.replace("`src/service.py:42-58`", "the service")))
        self.assertIsNone(scout.validated_capsule(VALID.replace("- Scope is limited to this domain.", "")))

    def test_oversize_cannot_be_truncated_into_accepted_evidence(self):
        self.assertIsNone(scout.validated_capsule(VALID + "extra", max_chars=len(VALID.strip())))
        self.assertEqual(scout.validated_capsule(VALID, max_chars=len(VALID.strip())), VALID.strip())

    def test_invalid_limits_and_nul_rejected(self):
        self.assertIsNone(scout.validated_capsule(VALID, 0))
        self.assertIsNone(scout.validated_capsule(VALID, 12.5))
        self.assertIsNone(scout.validated_capsule(VALID + "\x00"))

    def test_preamble_and_duplicate_section_rejected(self):
        self.assertIsNone(scout.validated_capsule("done\n" + VALID))
        self.assertIsNone(scout.validated_capsule(VALID + "\n## Evidence map\n- `a/b.py`"))

    def test_capsule_binding_requires_creation_provenance(self):
        binding = scout.capsule_binding(
            VALID, fingerprint="v2:" + "a" * 64, digest="ev1:" + "b" * 64,
            scope_confirmed=True, head_sha="c" * 40, step_id="d" * 32,
            model_alias="balanced", bound_at="2026-10-16T00:00:00+00:00",
        )
        args = {
            "fingerprint": binding["fingerprint"],
            "digest": binding["evidence_digest"],
            "scope_confirmed": True,
        }
        self.assertEqual(scout.capsule_verdict(VALID, binding, **args), "valid")
        unborn = scout.capsule_binding(
            VALID, fingerprint=binding["fingerprint"], digest=binding["evidence_digest"],
            scope_confirmed=True, head_sha="unborn", step_id="e" * 32,
            model_alias="balanced", bound_at="2026-10-16T00:00:00+00:00",
        )
        self.assertEqual(scout.capsule_verdict(VALID, unborn, **args), "valid")
        for key in ("step_id", "model_alias", "head_sha", "bound_at"):
            damaged = dict(binding)
            damaged.pop(key)
            with self.subTest(key=key):
                self.assertEqual(scout.capsule_verdict(VALID, damaged, **args), "stale")
        for key, value in (
            ("step_id", ""), ("model_alias", " "), ("head_sha", "short"),
            ("bound_at", "not-a-date"),
        ):
            damaged = {**binding, key: value}
            with self.subTest(key=key, value=value):
                self.assertEqual(scout.capsule_verdict(VALID, damaged, **args), "stale")



class ReservedTelemetryContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.runtime = Path(temporary.name) / ".devflow/runtime/sample"
        self.owner = session.start(self.runtime)["session_id"]
        self.policy = {
            "orchestration": {"hosted": {"max_steps": 5, "max_action_visits": 4}},
            "escalation": {"retries": {"max_no_progress": 3}},
        }
        self.fingerprint = "v2:" + "a" * 64
        self.step = guard.begin(
            self.runtime, self.owner, self.fingerprint, self.policy,
            kind="primary", expected_attempt=0, candidate_alias="fast",
        )["step_id"]

    def check(self, **overrides):
        args = {
            "fingerprint": self.fingerprint, "kind": "primary",
            "attempt": 0, "candidate_alias": "fast",
        }
        args.update(overrides)
        return guard.require_reserved_step(self.runtime, self.owner, self.step, **args)

    def test_exact_reserved_step_is_accepted_without_mutating_it(self):
        record = self.check()
        self.assertEqual(record["step_id"], self.step)
        self.assertEqual(self.check(), record)
        self.assertEqual(guard.inspect(
            self.runtime, self.owner, self.fingerprint, self.policy,
        )["reason"], "hosted_step_inflight")

    def test_wrong_risk_fingerprint_role_attempt_and_candidate_are_rejected(self):
        for changed in (
            {"fingerprint": "v2:" + "b" * 64}, {"kind": "scout"},
            {"attempt": 1}, {"candidate_alias": "balanced"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(guard.GuardBlocked, "telemetry_step_mismatch"):
                    self.check(**changed)
        with self.assertRaisesRegex(guard.GuardBlocked, "telemetry_step_mismatch"):
            guard.require_reserved_step(
                self.runtime, self.owner, "wrong", fingerprint=self.fingerprint,
                kind="primary", attempt=0, candidate_alias="fast",
            )

    def test_session_ownership_is_required_and_step_expires_after_finish(self):
        with self.assertRaises(session.SessionConflict):
            guard.require_reserved_step(
                self.runtime, "foreign", self.step,
                fingerprint=self.fingerprint, kind="primary", attempt=0,
                candidate_alias="fast",
            )
        guard.finish(
            self.runtime, self.owner, self.step, self.fingerprint,
            self.policy, outcome="completed",
        )
        with self.assertRaisesRegex(guard.GuardBlocked, "telemetry_step_mismatch"):
            self.check()


if __name__ == "__main__":
    unittest.main(verbosity=2)
