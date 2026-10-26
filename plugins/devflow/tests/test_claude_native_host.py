#!/usr/bin/env python3
"""Claude Code routing is host-local and cannot change DevFlow lifecycle authority."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
PLUGIN = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import devflow_autopilot as autopilot
import devflow_claude as claude


class ClaudeNativeHostTests(unittest.TestCase):
    def test_native_agent_presets_match_supported_routes(self):
        self.assertEqual(claude.validate_agent_files(PLUGIN), [])
        self.assertEqual(len(list((PLUGIN / "agents").glob("devflow-*.md"))), 6)

    def test_default_codex_policy_is_not_modified(self):
        before = autopilot.load_policy(PLUGIN, None)
        other = claude.load_policy(PLUGIN, None)
        after = autopilot.load_policy(PLUGIN, None)
        self.assertEqual(before["model_registry"], after["model_registry"])
        self.assertNotEqual(before["model_registry"]["models"]["fast"]["id"], "haiku")
        self.assertEqual(other["model_registry"]["models"]["balanced"]["id"], "sonnet")
        self.assertEqual(other["model_registry"]["models"]["frontier"]["id"], "opus")
        self.assertEqual(other["model_registry"]["models"]["fast"]["id"], "haiku")

    def test_claude_uses_its_own_project_override_and_ignores_codex_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / ".devflow"
            cfg.mkdir()
            (cfg / "models.yaml").write_text("models:\n  fast:\n    id: invalid-codex-id\n")
            (cfg / "routing.yaml").write_text("roles:\n  worker: { profile: frontier, effort: xhigh }\n")
            (cfg / "claude-routing.yaml").write_text("roles:\n  worker: { profile: economy, effort: high }\n")
            policy = claude.load_policy(PLUGIN, root)
            self.assertEqual(policy["roles"]["worker"]["profile"], "economy")
            self.assertEqual(policy["model_registry"]["models"]["fast"]["id"], "haiku")

    def test_claude_policy_never_uses_codex_exec(self):
        policy = claude.load_policy(PLUGIN, None)
        self.assertEqual(policy["backends"]["preference"], ["native_agent"])
        self.assertEqual(policy["profiles"]["economy"]["candidates"], ["balanced"])
        self.assertEqual(policy["roles"]["scout"]["profile"], "scout")
        self.assertEqual(policy["escalation"]["risk"]["critical"]["worker_effort"], "xhigh")
        self.assertTrue(all(step["effort"] != "max" for step in
                            policy["escalation"]["retries"]["worker_stages"]))

    def test_claude_audit_and_diagnosis_use_xhigh_only_for_elevated_risk(self):
        policy = claude.load_policy(PLUGIN, None)
        registry = autopilot.ModelRegistry.from_policy(policy)
        native = {registry.model_id(alias) for alias in registry.aliases()}
        caps = autopilot.CapabilityRegistry.assumed(
            policy, native_models=native, exec_available=False
        )
        router = autopilot.RouteEngine(policy, caps)
        for action, attempt in (
            ({"command": "audit", "scope": "integration"}, 0),
            ({"command": "run", "scope": "phase"}, 3),
        ):
            for risk, effort in (("medium", "high"), ("high", "xhigh"),
                                 ("critical", "xhigh")):
                with self.subTest(action=action["command"], risk=risk):
                    spec = router.resolve(action, {"risk_profile": risk}, attempt)
                    self.assertEqual(spec["model"]["selected"], "opus")
                    self.assertEqual(spec["model"]["reasoning_effort"], effort)

    def test_claude_project_override_cannot_enable_codex_exec(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = root / ".devflow"
            cfg.mkdir()
            (cfg / "claude-routing.yaml").write_text(
                "backends:\n  preference: [codex_exec]\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "native_agent"):
                claude.load_policy(PLUGIN, root)

    def test_dispatch_binds_exact_plugin_agent_and_candidate(self):
        envelope = {
            "status": "dispatch_required", "action": {"command": "run"},
            "primary": {"model": "sonnet", "model_alias": "balanced",
                        "reasoning_effort": "high", "permissions": "inherit",
                        "candidates": [{"alias": "balanced", "model": "sonnet", "reasoning_effort": "high"}]},
            "scout": {"model": "haiku", "model_alias": "fast",
                      "reasoning_effort": "medium", "permissions": "read-only",
                      "candidates": [{"alias": "fast", "model": "haiku", "reasoning_effort": "medium"}]},
        }
        saved = json.dumps(envelope, sort_keys=True)
        routed = claude.decorate(envelope)
        self.assertEqual(json.dumps(envelope, sort_keys=True), saved)
        self.assertEqual(routed["primary"]["claude"]["agent_type"], "devflow:devflow-high")
        self.assertEqual(routed["scout"]["claude"]["agent_type"], "devflow:devflow-medium-ro")
        self.assertEqual(routed["primary"]["claude"]["model"], "sonnet")
        self.assertEqual(routed["scout"]["claude"]["model"], "haiku")
        self.assertEqual(routed["primary"]["candidates"][0]["claude_agent_type"], "devflow:devflow-high")
        self.assertIs(routed["scout"]["claude"]["run_in_background"], False)
        self.assertEqual(routed["scout"]["claude"]["foreground"], True)
        self.assertNotIn("claude", envelope["primary"])

    def test_invocation_model_changes_without_new_agent_definition(self):
        model_types = [
            claude.agent_type({"model": family, "reasoning_effort": "high",
                               "permissions": "read-only"})
            for family in ("haiku", "sonnet", "opus")
        ]
        self.assertEqual(model_types, ["devflow:devflow-high-ro"] * 3)
        for family in ("haiku", "sonnet", "opus"):
            payload = {"status": "dispatch_required", "primary": {
                "model": family, "reasoning_effort": "high", "permissions": "read-only",
                "candidates": [],
            }}
            route = claude.decorate(payload)["primary"]["claude"]
            self.assertEqual(route["model"], family)
            self.assertEqual(route["agent_type"], "devflow:devflow-high-ro")
            self.assertIs(route["run_in_background"], False)

    def test_unsupported_model_effort_or_candidate_fails_closed(self):
        for model, effort in (("sonnet", "max"), ("gpt-6-luna", "high"), ("opus", "invalid"), ("", "high")):
            with self.subTest(model=model, effort=effort), self.assertRaises(ValueError):
                claude.agent_type({"model": model, "reasoning_effort": effort})
        malformed = {"status": "dispatch_required", "primary": {
            "model": "opus", "reasoning_effort": "xhigh", "permissions": "inherit",
            "candidates": [{"model": "gpt-6-luna", "reasoning_effort": "high"}],
        }}
        with self.assertRaises(ValueError):
            claude.decorate(malformed)

    def test_observational_lifecycle_results_remain_unchanged(self):
        for status in ("complete", "paused", "checkpoint", "blocked", "handed_off"):
            record = {"status": status, "reason": "unchanged"}
            self.assertIs(claude.decorate(record), record)

    def test_environment_model_override_fails_closed(self):
        claude.assert_model_environment({})
        claude.assert_model_environment({"CLAUDE_CODE_SUBAGENT_MODEL": "inherit"})
        with self.assertRaisesRegex(ValueError, "overrides DevFlow"):
            claude.assert_model_environment({"CLAUDE_CODE_SUBAGENT_MODEL": "opus"})
        with self.assertRaisesRegex(ValueError, "forces background"):
            claude.assert_model_environment({"CLAUDE_CODE_FORK_SUBAGENT": "1"})

    def test_host_parser_accepts_both_native_hosts_without_claude_cli(self):
        import devflow_host as host
        parser = host.build_parser()
        codex = parser.parse_args(["session-start", "sample", "--host", "codex"])
        claude = parser.parse_args(["--native-host", "claude", "session-start", "sample"])
        self.assertEqual(codex.native_host, "codex")
        self.assertEqual(claude.native_host, "claude")
        self.assertIsNone(claude.host)


if __name__ == "__main__":
    unittest.main(verbosity=2)
