#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
MODULE = PLUGIN / "scripts" / "devflow_autopilot.py"


def load_module():
    spec = importlib.util.spec_from_file_location("devflow_autopilot_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutopilotRoutingTests(unittest.TestCase):
    def setUp(self):
        self.ap = load_module()
        self.policy = self.ap.load_policy(PLUGIN, None)
        self.registry = self.ap.ModelRegistry.from_policy(self.policy)
        self.models = {
            alias: self.registry.model_id(alias) for alias in self.registry.aliases()
        }
        self.caps = self.ap.CapabilityRegistry.assumed(
            self.policy,
            native_models={self.models["frontier"], self.models["balanced"]},
            exec_available=True,
        )
        self.router = self.ap.RouteEngine(self.policy, self.caps)

    def assert_route(self, spec, alias, effort):
        self.assertEqual(
            (spec["model"]["alias"], spec["model"]["reasoning_effort"]), (alias, effort)
        )

    def test_routing_policy_uses_logical_model_aliases(self):
        routing_text = (PLUGIN / "core" / "routing" / "default.yaml").read_text(
            encoding="utf-8"
        )
        for model_id in self.models.values():
            self.assertNotIn(model_id, routing_text)
        self.assertEqual(self.models["fast"], "gpt-6-luna")
        self.assertEqual(self.models["balanced"], "gpt-5.6-terra")
        self.assertEqual(self.models["frontier"], "gpt-6.1-sol")
        self.assertEqual(
            self.policy["profiles"]["economy"]["candidates"], ["fast", "balanced"]
        )
        self.assertEqual(
            self.policy["profiles"]["balanced"]["candidates"], ["balanced", "frontier"]
        )
        self.assertEqual(
            self.policy["profiles"]["alternative"]["candidates"], ["balanced"]
        )
        self.assertEqual(
            self.policy["profiles"]["frontier"]["candidates"],
            ["frontier", "balanced"],
        )
        self.assertEqual(self.policy["profiles"]["hardest"]["candidates"], ["frontier"])
        self.assertEqual(
            self.policy["orchestration"]["scout_before"],
            [
                "architect",
                "verifier",
                "auditor",
                "integration_auditor",
                "diagnostician",
                "finalizer",
            ],
        )

    def test_routing_and_model_registry_schemas_match_split_sources(self):
        routing_schema = self.ap._load_yaml(
            PLUGIN / "core" / "schemas" / "routing.schema.yaml"
        )
        model_schema = self.ap._load_yaml(
            PLUGIN / "core" / "schemas" / "model-registry.schema.yaml"
        )
        self.assertNotIn("models", routing_schema["required"])
        self.assertIn("models", model_schema["required"])

    def test_project_model_override_changes_concrete_model_without_routing_changes(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".devflow"
            config.mkdir()
            replacement = "replacement-fast-model"
            (config / "models.yaml").write_text(
                f"models:\n  fast:\n    id: {replacement}\n",
                encoding="utf-8",
            )
            policy = self.ap.load_policy(PLUGIN, root)
            caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True)
            router = self.ap.RouteEngine(policy, caps)
            spec = router.resolve(
                {"command": "run", "scope": "phase", "item_kind": "implementation"},
                {"risk_profile": "medium"},
            )
            self.assertEqual(
                policy["profiles"]["economy"]["candidates"], ["fast", "balanced"]
            )
            self.assertEqual(spec["model"]["alias"], "fast")
            self.assertEqual(spec["model"]["selected"], replacement)

    def test_legacy_sandbox_override_maps_to_permission_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".devflow"
            config.mkdir()
            (config / "routing.yaml").write_text(
                "roles:\n  worker:\n    sandbox: read-only\n", encoding="utf-8"
            )
            policy = self.ap.load_policy(PLUGIN, root)
            caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True)
            spec = self.ap.RouteEngine(policy, caps).resolve(
                {"command": "run", "scope": "phase", "item_kind": "implementation"},
                {"risk_profile": "medium"},
            )
            self.assertEqual(spec["execution"]["permissions"], "read-only")

    def test_legacy_worker_retry_override_replaces_staged_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".devflow"
            config.mkdir()
            (config / "routing.yaml").write_text(
                "escalation:\n  retries:\n    worker_retry_effort: xhigh\n",
                encoding="utf-8",
            )
            policy = self.ap.load_policy(PLUGIN, root)
            retries = policy["escalation"]["retries"]
            self.assertNotIn("worker_stages", retries)
            self.assertEqual(retries["diagnose_at"], 2)
            self.assertEqual(retries["worker_retry_profile"], "balanced")
            caps = self.ap.CapabilityRegistry.assumed(
                policy,
                native_models={self.models["frontier"], self.models["balanced"]},
                exec_available=True,
            )
            router = self.ap.RouteEngine(policy, caps)
            action = {"command": "run", "scope": "phase", "item_kind": "implementation"}
            state = {"risk_profile": "medium"}
            self.assert_route(
                router.resolve(action, state, attempt=1), "balanced", "xhigh"
            )
            diagnosis = router.resolve(action, state, attempt=2)
            self.assertEqual(diagnosis["role"], "diagnostician")
            self.assert_route(diagnosis, "frontier", "xhigh")
            self.assert_route(
                router.resolve(action, state, attempt=3), "frontier", "xhigh"
            )

    def test_legacy_routing_override_translates_codex_min_version(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".devflow"
            config.mkdir()
            model_id = self.models["fast"]
            (config / "routing.yaml").write_text(
                f"models:\n  {model_id}:\n    codex_min_version: 9.9.9\n",
                encoding="utf-8",
            )
            policy = self.ap.load_policy(PLUGIN, root)
            registry = self.ap.ModelRegistry.from_policy(policy)
            self.assertEqual(registry.codex_min_version("fast"), "9.9.9")
            self.assertEqual(policy["models"][model_id]["codex_min_version"], "9.9.9")

    def test_model_registry_requires_multi_agent(self):
        config = {
            "version": 1,
            "models": {"fast": {"id": "some-model", "efforts": ["high"]}},
        }
        with self.assertRaisesRegex(ValueError, "must define multi_agent"):
            self.ap.ModelRegistry(config)

    def test_legacy_models_default_multi_agent_to_false(self):
        registry = self.ap.ModelRegistry.from_legacy(
            {self.models["fast"]: {"efforts": ["high"]}}
        )
        self.assertFalse(registry.meta(self.models["fast"])["multi_agent"])

    def test_route_decision_is_independent_from_concrete_model_resolution(self):
        decision = self.router.decide(
            {"command": "run", "scope": "phase", "item_kind": "implementation"},
            {"risk_profile": "medium"},
        )
        self.assertEqual(
            (decision["role"], decision["profile"], decision["effort"]),
            ("worker", "economy", "high"),
        )
        self.assertNotIn("model", decision)

    def test_unknown_model_alias_fails_during_policy_load(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".devflow"
            config.mkdir()
            (config / "routing.yaml").write_text(
                "profiles:\n  economy:\n    candidates: [missing-model]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown model"):
                self.ap.load_policy(PLUGIN, root)

    def test_routes_routine_implementation_to_fast_high(self):
        spec = self.router.resolve(
            {
                "command": "run",
                "scope": "phase",
                "work_item": "P01-I01",
                "item_kind": "implementation",
            },
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["role"], "worker")
        self.assert_route(spec, "fast", "high")
        self.assertEqual(spec["execution"]["backend"], "codex_exec")

    def test_scout_is_terra_medium_by_default_and_high_for_high_risk(self):
        spec = self.router.resolve(
            {"command": "plan", "scope": "project", "_role_override": "scout"},
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["role"], "scout")
        self.assert_route(spec, "balanced", "medium")
        high = self.router.resolve(
            {"command": "plan", "scope": "project", "_role_override": "scout"},
            {"risk_profile": "high"},
        )
        self.assert_route(high, "balanced", "high")

    def test_task_kind_routes_worker_to_matching_alias_and_effort(self):
        cases = [
            ("documentation", "fast", "high"),
            ("test", "fast", "high"),
            ("evidence", "fast", "high"),
            ("remediation", "fast", "xhigh"),
            ("migration", "fast", "xhigh"),
        ]
        for item_kind, alias, effort in cases:
            with self.subTest(item_kind=item_kind):
                spec = self.router.resolve(
                    {"command": "run", "scope": "phase", "item_kind": item_kind},
                    {"risk_profile": "medium"},
                )
                self.assert_route(spec, alias, effort)

    def test_routes_planning_to_frontier_high(self):
        spec = self.router.resolve(
            {"command": "plan", "scope": "project"}, {"risk_profile": "medium"}
        )
        self.assertEqual(spec["role"], "architect")
        self.assert_route(spec, "frontier", "high")
        self.assertEqual(spec["execution"]["backend"], "native_agent")

    def test_critical_integration_audit_routes_to_frontier_xhigh(self):
        spec = self.router.resolve(
            {"command": "audit", "scope": "integration", "mode": "initial"},
            {"risk_profile": "critical"},
        )
        self.assert_route(spec, "frontier", "xhigh")

    def test_work_verification_stays_on_sol_and_escalates_effort_for_risk(self):
        medium = self.router.resolve(
            {
                "command": "audit",
                "scope": "work",
                "item_kind": "implementation",
                "item_risk": "medium",
            },
            {"risk_profile": "medium"},
        )
        high = self.router.resolve(
            {
                "command": "audit",
                "scope": "work",
                "item_kind": "implementation",
                "item_risk": "high",
            },
            {"risk_profile": "medium"},
        )
        critical = self.router.resolve(
            {
                "command": "audit",
                "scope": "work",
                "item_kind": "implementation",
                "item_risk": "critical",
            },
            {"risk_profile": "medium"},
        )
        self.assert_route(medium, "frontier", "high")
        self.assert_route(high, "frontier", "xhigh")
        self.assert_route(critical, "frontier", "xhigh")

    def test_high_risk_worker_keeps_luna_and_raises_effort(self):
        spec = self.router.resolve(
            {"command": "run", "scope": "phase", "item_kind": "implementation"},
            {"risk_profile": "high"},
        )
        self.assert_route(spec, "fast", "xhigh")

    def test_high_work_risk_overrides_medium_domain_risk(self):
        spec = self.router.resolve(
            {
                "command": "run",
                "scope": "phase",
                "item_kind": "implementation",
                "item_risk": "high",
            },
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["effective_risk"], "high")
        self.assert_route(spec, "fast", "xhigh")

    def test_critical_work_risk_keeps_worker_on_luna_max(self):
        spec = self.router.resolve(
            {
                "command": "run",
                "scope": "phase",
                "item_kind": "implementation",
                "item_risk": "critical",
            },
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["effective_risk"], "critical")
        self.assert_route(spec, "fast", "max")

    def test_domain_risk_is_a_floor_for_lower_work_risk(self):
        spec = self.router.resolve(
            {
                "command": "run",
                "scope": "phase",
                "item_kind": "implementation",
                "item_risk": "low",
            },
            {"risk_profile": "critical"},
        )
        self.assertEqual(spec["effective_risk"], "critical")
        self.assert_route(spec, "fast", "max")

    def test_critical_worker_fails_closed_when_luna_is_unavailable(self):
        self.caps.mark_unavailable("fast", "codex_exec", "model unavailable")
        with self.assertRaisesRegex(RuntimeError, "profile=economy effort=max"):
            self.router.resolve(
                {
                    "command": "run",
                    "scope": "phase",
                    "item_kind": "implementation",
                    "item_risk": "critical",
                },
                {"risk_profile": "medium"},
            )

    def test_unavailable_model_backend_pair_falls_back_to_next_candidate(self):
        self.caps.mark_unavailable("fast", "codex_exec", "model unavailable")
        spec = self.router.resolve(
            {"command": "run", "scope": "phase", "item_kind": "implementation"},
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["model"]["alias"], "balanced")
        self.assertEqual(spec["execution"]["backend"], "native_agent")

    def test_frontier_authority_falls_back_to_terra(self):
        self.caps.mark_unavailable("frontier", "native_agent", "model unavailable")
        self.caps.mark_unavailable("frontier", "codex_exec", "model unavailable")
        spec = self.router.resolve(
            {"command": "plan", "scope": "project"}, {"risk_profile": "medium"}
        )
        self.assert_route(spec, "balanced", "high")
        self.assertEqual(spec["execution"]["backend"], "native_agent")

    def test_hardest_authority_still_fails_closed_without_frontier(self):
        self.caps.mark_unavailable("frontier", "native_agent", "model unavailable")
        self.caps.mark_unavailable("frontier", "codex_exec", "model unavailable")
        with self.assertRaisesRegex(RuntimeError, "profile=hardest effort=xhigh"):
            self.router.resolve(
                {"command": "audit", "scope": "integration", "mode": "initial"},
                {"risk_profile": "critical"},
            )

    def test_unavailable_state_records_alias_and_restores_same_model(self):
        self.caps.mark_unavailable("fast", "codex_exec", "model unavailable")
        rows = self.caps.unavailable_rows()
        self.assertEqual(rows[0]["alias"], "fast")
        self.assertEqual(rows[0]["model"], self.models["fast"])

        restored = self.ap.CapabilityRegistry.assumed(self.policy, exec_available=True)
        restored.restore_unavailable(rows)
        self.assertIsNone(restored.backend_for("fast", ["codex_exec"]))

    def test_stale_unavailable_state_is_ignored_after_alias_remap(self):
        self.caps.mark_unavailable("fast", "codex_exec", "model unavailable")
        rows = self.caps.unavailable_rows()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / ".devflow"
            config.mkdir()
            (config / "models.yaml").write_text(
                "models:\n  fast:\n    id: replacement-fast-model\n",
                encoding="utf-8",
            )
            policy = self.ap.load_policy(PLUGIN, root)
            remapped = self.ap.CapabilityRegistry.assumed(policy, exec_available=True)
            remapped.restore_unavailable(rows)
            remapped.restore_unavailable(
                [
                    {
                        "model": self.models["fast"],
                        "backend": "codex_exec",
                        "reason": "legacy failure",
                    },
                ]
            )
            self.assertEqual(remapped.unavailable_rows(), [])
            self.assertEqual(remapped.backend_for("fast", ["codex_exec"]), "codex_exec")

    def test_codex_backend_enforces_minimum_cli_version(self):
        old_caps = self.ap.CapabilityRegistry.assumed(
            self.policy,
            exec_available=True,
            codex_version="0.143.9",
        )
        self.assertIsNone(old_caps.backend_for("frontier", ["codex_exec"]))
        self.assertIsNone(old_caps.backend_for("balanced", ["codex_exec"]))

        new_caps = self.ap.CapabilityRegistry.assumed(
            self.policy,
            exec_available=True,
            codex_version="0.144.0",
        )
        self.assertEqual(new_caps.backend_for("frontier", ["codex_exec"]), "codex_exec")
        self.assertEqual(new_caps.backend_for("balanced", ["codex_exec"]), "codex_exec")

    def test_detected_codex_version_controls_per_model_compatibility(self):
        import os

        with tempfile.TemporaryDirectory() as td:
            codex = Path(td) / "codex"
            codex.write_text("#!/bin/sh\necho 'codex-cli 0.143.9'\n", encoding="utf-8")
            codex.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            old_bin = os.environ.pop("DEVFLOW_CODEX_BIN", None)
            old_base_url = os.environ.pop("OPENAI_BASE_URL", None)
            old_runner = os.environ.pop("DEVFLOW_NATIVE_AGENT_RUNNER", None)
            old_models = os.environ.pop("DEVFLOW_NATIVE_AGENT_MODELS", None)
            try:
                os.environ["PATH"] = td + os.pathsep + old_path
                caps = self.ap.CapabilityRegistry.detect(self.policy)
            finally:
                os.environ["PATH"] = old_path
                if old_bin is not None:
                    os.environ["DEVFLOW_CODEX_BIN"] = old_bin
                if old_base_url is not None:
                    os.environ["OPENAI_BASE_URL"] = old_base_url
                if old_runner is not None:
                    os.environ["DEVFLOW_NATIVE_AGENT_RUNNER"] = old_runner
                if old_models is not None:
                    os.environ["DEVFLOW_NATIVE_AGENT_MODELS"] = old_models
            self.assertEqual(caps.codex_version, "0.143.9")
            self.assertTrue(caps.exec_available)
            self.assertIsNone(caps.backend_for("frontier", ["codex_exec"]))
            self.assertIsNone(caps.backend_for("balanced", ["codex_exec"]))

    def test_detect_prefers_explicit_codex_bin_when_path_has_no_codex(self):
        import os

        with tempfile.TemporaryDirectory() as td:
            codex = Path(td) / "explicit-codex"
            codex.write_text("#!/bin/sh\necho 'codex-cli 0.158.0'\n", encoding="utf-8")
            codex.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            old_bin = os.environ.get("DEVFLOW_CODEX_BIN")
            try:
                os.environ["PATH"] = ""
                os.environ["DEVFLOW_CODEX_BIN"] = str(codex)
                caps = self.ap.CapabilityRegistry.detect(self.policy)
            finally:
                os.environ["PATH"] = old_path
                if old_bin is None:
                    os.environ.pop("DEVFLOW_CODEX_BIN", None)
                else:
                    os.environ["DEVFLOW_CODEX_BIN"] = old_bin
            self.assertTrue(caps.exec_available)
            self.assertEqual(caps.codex_path, str(codex))
            self.assertEqual(caps.codex_version, "0.158.0")

    def test_invalid_explicit_codex_bin_fails_closed(self):
        import os

        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing-codex"
            old_bin = os.environ.get("DEVFLOW_CODEX_BIN")
            try:
                os.environ["DEVFLOW_CODEX_BIN"] = str(missing)
                caps = self.ap.CapabilityRegistry.detect(self.policy)
            finally:
                if old_bin is None:
                    os.environ.pop("DEVFLOW_CODEX_BIN", None)
                else:
                    os.environ["DEVFLOW_CODEX_BIN"] = old_bin
            self.assertFalse(caps.exec_available)
            self.assertIsNone(caps.codex_path)
            self.assertIn("DEVFLOW_CODEX_BIN", caps.codex_launch_error)

    def test_detect_inherits_openai_base_url_for_child_codex_transport(self):
        import os

        with tempfile.TemporaryDirectory() as td:
            codex = Path(td) / "codex"
            codex.write_text("#!/bin/sh\necho 'codex-cli 0.158.0'\n", encoding="utf-8")
            codex.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            old_bin = os.environ.pop("DEVFLOW_CODEX_BIN", None)
            old_base_url = os.environ.get("OPENAI_BASE_URL")
            try:
                os.environ["PATH"] = td + os.pathsep + old_path
                os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:8787/v1"
                caps = self.ap.CapabilityRegistry.detect(self.policy)
            finally:
                os.environ["PATH"] = old_path
                if old_bin is not None:
                    os.environ["DEVFLOW_CODEX_BIN"] = old_bin
                if old_base_url is None:
                    os.environ.pop("OPENAI_BASE_URL", None)
                else:
                    os.environ["OPENAI_BASE_URL"] = old_base_url
            self.assertEqual(caps.codex_openai_base_url, "http://127.0.0.1:8787/v1")
            self.assertEqual(
                caps.as_dict()["codex_exec"]["transport"],
                "inherited_openai_base_url",
            )

    def test_capabilities_keep_legacy_model_keys_and_add_alias_registry(self):
        doc = self.caps.as_dict()
        fast_model = self.models["fast"]
        self.assertIn(fast_model, doc["models"])
        self.assertEqual(doc["model_registry"]["models"]["fast"]["id"], fast_model)
        self.assertIn(fast_model, doc["codex_exec"]["model_compatibility"])
        self.assertEqual(
            doc["codex_exec"]["alias_compatibility"]["fast"]["model"], fast_model
        )

    def test_route_consumes_context_delegation_and_multi_agent_policy(self):
        spec = self.router.resolve(
            {"command": "plan", "scope": "project"}, {"risk_profile": "medium"}
        )
        self.assertEqual(
            spec["execution"]["context_mode"], self.policy["context"]["default_mode"]
        )
        self.assertEqual(
            spec["execution"]["native_fork_turns"],
            self.policy["context"]["native_fork_turns"],
        )
        self.assertFalse(spec["execution"]["allow_recursive_delegation"])
        self.assertEqual(spec["execution"]["permissions"], "inherit")
        self.assertEqual(spec["model"]["alias"], "frontier")
        self.assertEqual(
            spec["execution"]["model_multi_agent"],
            self.caps.model_meta(spec["model"]["alias"])["multi_agent"],
        )

    def test_retry_uses_luna_ladder_then_sol_diagnosis_and_terra_fallback(self):
        action = {"command": "run", "scope": "phase", "item_kind": "implementation"}
        state = {"risk_profile": "medium"}
        first = self.router.resolve(action, state, attempt=0)
        xhigh = self.router.resolve(action, state, attempt=1)
        maximum = self.router.resolve(action, state, attempt=2)
        diag = self.router.resolve(action, state, attempt=3)
        post_diag = self.router.resolve(action, state, attempt=4)
        fallback = self.router.resolve(action, state, attempt=5)
        self.assert_route(first, "fast", "high")
        self.assert_route(xhigh, "fast", "xhigh")
        self.assert_route(maximum, "fast", "max")
        self.assertEqual(diag["role"], "diagnostician")
        self.assert_route(diag, "frontier", "xhigh")
        self.assert_route(post_diag, "fast", "max")
        self.assert_route(fallback, "balanced", "xhigh")


class AutopilotRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.ap = load_module()

    def test_codex_exec_command_contains_model_effort_and_inherits_permissions(self):
        backend = self.ap.CodexExecBackend("codex")
        spec = {
            "model": {"selected": "fixture-fast-model", "reasoning_effort": "xhigh"},
            "execution": {"permissions": "inherit"},
        }
        cmd = backend.build_command(Path("/repo"), spec)
        joined = " ".join(cmd)
        self.assertIn("exec", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("fixture-fast-model", cmd)
        self.assertIn('model_reasoning_effort="xhigh"', joined)
        self.assertIn("--json", cmd)
        self.assertNotIn("--sandbox", cmd)
        self.assertNotIn('default_permissions=":read-only"', cmd)

    def test_codex_exec_command_reuses_inherited_openai_base_url(self):
        backend = self.ap.CodexExecBackend(
            "/opt/codex", openai_base_url="http://127.0.0.1:8787/v1"
        )
        spec = {
            "model": {"selected": "fixture-fast-model", "reasoning_effort": "high"},
            "execution": {"permissions": "inherit"},
        }
        cmd = backend.build_command(Path("/repo"), spec)
        self.assertEqual(cmd[0:2], ["/opt/codex", "exec"])
        self.assertIn('openai_base_url="http://127.0.0.1:8787/v1"', cmd)
        self.assertNotIn("headroom", cmd)

    def test_codex_exec_read_only_uses_permission_profile_not_legacy_sandbox(self):
        backend = self.ap.CodexExecBackend("codex")
        spec = {
            "model": {"selected": "fixture-fast-model", "reasoning_effort": "high"},
            "execution": {"permissions": "read-only"},
        }
        cmd = backend.build_command(Path("/repo"), spec)
        self.assertIn('default_permissions=":read-only"', cmd)
        self.assertNotIn("--sandbox", cmd)

    def test_context_capsule_contains_role_contract_and_packet_without_parent_history(
        self,
    ):
        assembler = self.ap.ContextAssembler(PLUGIN)
        spec = {
            "role": "worker",
            "task_id": "P01-I01",
            "model": {"selected": "fixture-fast-model", "reasoning_effort": "high"},
        }
        text = assembler.build(spec, "RENDERED_PACKET", diagnosis="prior diagnosis")
        self.assertIn("RENDERED_PACKET", text)
        self.assertIn("prior diagnosis", text)
        self.assertIn("DevFlow Run", text)
        self.assertIn(str(PLUGIN / "scripts" / "devflow.py"), text)
        self.assertIn("DEVFLOW_PLUGIN_ROOT", text)
        self.assertNotIn("parent_conversation", text)

    def test_sol_context_uses_terra_capsule_instead_of_full_runtime_packet(self):
        assembler = self.ap.ContextAssembler(PLUGIN)
        spec = {
            "role": "architect",
            "task_id": None,
            "action": {"command": "plan", "scope": "project"},
            "model": {"selected": "fixture-frontier-model", "reasoning_effort": "high"},
            "execution": {"allow_recursive_delegation": False},
        }
        packet = "## Runtime context\n- domain: billing\n\nFULL_PACKET_SENTINEL"
        text = assembler.build(
            spec, packet, scout_digest="src/billing.py:42 - existing contract"
        )
        self.assertIn("Terra pre-analysis capsule", text)
        self.assertIn("src/billing.py:42", text)
        self.assertIn("status billing", text)
        self.assertNotIn("FULL_PACKET_SENTINEL", text)

    def test_diagnostician_has_dedicated_read_only_contract(self):
        assembler = self.ap.ContextAssembler(PLUGIN)
        spec = {
            "role": "diagnostician",
            "task_id": "P01-I01",
            "model": {
                "selected": "fixture-frontier-model",
                "reasoning_effort": "xhigh",
            },
            "execution": {"allow_recursive_delegation": False},
        }
        text = assembler.build(spec, "RENDERED_PACKET")
        self.assertIn("read-only independent diagnosis", text)
        self.assertNotIn("audit apply", text.lower())
        self.assertNotIn("create remediation work", text.lower())

    def test_token_budget_accounts_usage_and_enforces_total_limit(self):
        budget = self.ap.TokenBudget(
            {
                "total_tokens": 100,
                "planning_percent": 15,
                "implementation_percent": 45,
                "verification_percent": 20,
                "finalization_percent": 10,
                "reserve_percent": 10,
                "dispatch_reserve_tokens": 25,
                "scout_reserve_tokens": 10,
            }
        )
        budget.consume("implementation", {"input_tokens": 60, "output_tokens": 40})
        self.assertEqual(budget.total_used, 100)
        self.assertFalse(budget.can_dispatch("implementation"))
        self.assertEqual(budget.snapshot("implementation")["pressure"], "exhausted")

    def test_token_budget_refuses_dispatch_when_remaining_is_below_reservation(self):
        budget = self.ap.TokenBudget(
            {
                "total_tokens": 100,
                "planning_percent": 15,
                "implementation_percent": 45,
                "verification_percent": 20,
                "finalization_percent": 10,
                "reserve_percent": 10,
                "dispatch_reserve_tokens": 25,
                "scout_reserve_tokens": 10,
            }
        )
        budget.consume("implementation", {"total_tokens": 40})
        self.assertTrue(budget.can_dispatch("implementation"))
        self.assertFalse(budget.can_dispatch("implementation", required_tokens=25))
        self.assertEqual(budget.reservation_for_role("worker"), 25)

    def test_controller_blocks_before_dispatch_when_reservation_cannot_be_met(self):
        budget = self.ap.TokenBudget(
            {
                "total_tokens": 100,
                "planning_percent": 15,
                "implementation_percent": 45,
                "verification_percent": 20,
                "finalization_percent": 10,
                "reserve_percent": 10,
                "dispatch_reserve_tokens": 25,
                "scout_reserve_tokens": 10,
            }
        )
        budget.consume("implementation", {"total_tokens": 40})
        dispatched = []
        state = {
            "risk_profile": "medium",
            "next_action": {"command": "run", "scope": "phase", "work_item": "P01-I01"},
        }
        controller = self.ap.AutopilotController(
            lambda: state,
            lambda _action: "packet",
            lambda action, _state, attempt: {
                "role": "worker",
                "model": {"selected": "fixture-fast-model", "reasoning_effort": "high"},
                "execution": {"backend": "codex_exec", "sandbox": "workspace-write"},
                "action": action,
                "attempt": attempt,
            },
            lambda spec, prompt: (
                dispatched.append((spec, prompt)) or {"status": "success"}
            ),
            None,
            1,
            budget=budget,
        )
        result = controller.run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "token_budget_dispatch_reserve_exhausted")
        self.assertEqual(dispatched, [])

    def test_token_budget_state_round_trips_for_resume(self):
        config = {
            "total_tokens": 1000,
            "planning_percent": 15,
            "implementation_percent": 45,
            "verification_percent": 20,
            "finalization_percent": 10,
            "reserve_percent": 10,
        }
        budget = self.ap.TokenBudget(config)
        budget.consume("verification", {"input_tokens": 120, "output_tokens": 30})
        restored = self.ap.TokenBudget(config, state=budget.state_dict())
        self.assertEqual(restored.total_used, 150)
        self.assertEqual(restored.used_by_bucket["verification"], 150)

    def test_domain_lease_enforces_mutating_concurrency(self):
        with tempfile.TemporaryDirectory() as td:
            first = self.ap.DomainLease(Path(td), 1, owner="run-a")
            second = self.ap.DomainLease(Path(td), 1, owner="run-b")
            with first, self.assertRaises(RuntimeError):
                second.acquire()
            with second:
                self.assertTrue(second.acquired)

    def test_controller_stops_on_complete_without_dispatch(self):
        states = iter(
            [
                {
                    "risk_profile": "medium",
                    "next_action": {
                        "command": "complete",
                        "role": "none",
                        "scope": "project",
                    },
                }
            ]
        )
        dispatched = []
        controller = self.ap.AutopilotController(
            status_fn=lambda: next(states),
            render_fn=lambda a: "",
            route_fn=lambda a, s, n: {},
            dispatch_fn=lambda s, p: dispatched.append((s, p)),
            ledger=None,
            max_steps=3,
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(dispatched, [])

    def test_controller_pauses_for_human_decision(self):
        state = {
            "risk_profile": "medium",
            "next_action": {"command": "decision", "role": "human", "scope": "project"},
        }
        controller = self.ap.AutopilotController(
            lambda: state, lambda a: "", lambda a, s, n: {}, lambda s, p: {}, None, 3
        )
        self.assertEqual(controller.run()["status"], "paused")

    def test_execution_boundary_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            self.ap.ExecutionBoundary("unknown")

    def test_plan_boundary_runs_plan_review_remediation_then_stops_before_phase_work(
        self,
    ):
        actions = [
            {"command": "plan", "role": "architect", "scope": "project"},
            {"command": "audit", "role": "auditor", "scope": "plan", "mode": "initial"},
            {
                "command": "run",
                "role": "executor",
                "scope": "integration",
                "work_item": "P00-R01",
            },
            {
                "command": "audit",
                "role": "auditor",
                "scope": "work",
                "mode": "initial",
                "work_item": "P00-R01",
            },
            {"command": "audit", "role": "auditor", "scope": "plan", "mode": "closure"},
            {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "phase": "01",
                "work_item": "P01-I01",
            },
        ]
        state = {
            "risk_profile": "high",
            "plan_review": {
                "required": True,
                "status": "pending",
                "remediation_work_ids": [],
            },
            "next_action": actions[0],
        }
        rendered = []
        dispatched = []

        def route(action, _state, attempt):
            if action["command"] == "plan":
                role = "architect"
            elif action["command"] == "run":
                role = "worker"
            else:
                role = "auditor"
            return {
                "role": role,
                "model": {"selected": "fixture-model", "reasoning_effort": "high"},
                "execution": {"sandbox": "workspace-write"},
                "action": action,
                "attempt": attempt,
            }

        def dispatch(_spec, _prompt):
            current = state["next_action"]
            dispatched.append(current)
            index = actions.index(current)
            if index == 1:
                state["plan_review"]["status"] = "remediation"
                state["plan_review"]["remediation_work_ids"] = ["P00-R01"]
            elif index == 4:
                state["plan_review"]["status"] = "verified"
            state["next_action"] = actions[index + 1]
            return {"status": "success", "exit_code": 0}

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda action: rendered.append(action) or "packet",
            route,
            dispatch,
            None,
            10,
            until="plan",
        )
        result = controller.run()
        self.assertEqual(result["status"], "checkpoint")
        self.assertEqual(result["reason"], "execution_boundary_reached")
        self.assertEqual(result["execution_boundary"], "plan")
        self.assertEqual(result["action"], actions[-1])
        self.assertEqual(dispatched, actions[:-1])
        self.assertEqual(rendered, actions[:-1])

    def test_implementation_boundary_stops_before_finalization_without_render_or_dispatch(
        self,
    ):
        actions = [
            {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "phase": "01",
                "work_item": "P01-I01",
            },
            {
                "command": "audit",
                "role": "auditor",
                "scope": "phase",
                "phase": "01",
                "mode": "initial",
            },
            {"command": "finalize", "role": "executor", "scope": "project"},
        ]
        state = {"risk_profile": "medium", "next_action": actions[0]}
        rendered = []
        dispatched = []

        def dispatch(_spec, _prompt):
            current = state["next_action"]
            dispatched.append(current)
            state["next_action"] = actions[actions.index(current) + 1]
            return {"status": "success", "exit_code": 0}

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda action: rendered.append(action) or "packet",
            lambda action, _state, attempt: {
                "role": "worker" if action["command"] == "run" else "auditor",
                "model": {"selected": "fixture-model", "reasoning_effort": "high"},
                "execution": {"sandbox": "workspace-write"},
                "action": action,
                "attempt": attempt,
            },
            dispatch,
            None,
            6,
            until="implementation",
        )
        result = controller.run()
        self.assertEqual(result["status"], "checkpoint")
        self.assertEqual(result["execution_boundary"], "implementation")
        self.assertEqual(result["action"], actions[-1])
        self.assertEqual(dispatched, actions[:-1])
        self.assertEqual(rendered, actions[:-1])
        planning_state = {"plan_review": {"remediation_work_ids": ["P00-R01"]}}
        self.assertFalse(
            self.ap.ExecutionBoundary("implementation").reached(
                planning_state,
                {"command": "run", "scope": "integration", "work_item": "P00-R01"},
            )
        )
        self.assertTrue(
            self.ap.ExecutionBoundary("implementation").reached(
                state, {"command": "audit", "scope": "integration", "mode": "initial"}
            )
        )

    def test_controller_dispatches_until_state_progresses_then_completes(self):
        states = [
            {
                "risk_profile": "medium",
                "next_action": {
                    "command": "run",
                    "role": "executor",
                    "scope": "phase",
                    "work_item": "P01-I01",
                },
            },
            {
                "risk_profile": "medium",
                "next_action": {
                    "command": "complete",
                    "role": "none",
                    "scope": "project",
                },
            },
        ]
        calls = {"status": 0, "dispatch": 0}

        def status():
            idx = min(calls["status"], len(states) - 1)
            calls["status"] += 1
            return states[idx]

        def dispatch(spec, prompt):
            calls["dispatch"] += 1
            return {"status": "success", "exit_code": 0, "usage": {"input_tokens": 10}}

        controller = self.ap.AutopilotController(
            status,
            lambda a: "packet",
            lambda a, s, n: {
                "role": "worker",
                "model": {"selected": "x", "reasoning_effort": "high"},
            },
            dispatch,
            None,
            5,
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls["dispatch"], 1)
        self.assertEqual(result["steps"], 1)

    def test_controller_changes_model_aliases_across_lifecycle_roles(self):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(
            policy, exec_available=True, codex_version="0.153.0"
        )
        router = self.ap.RouteEngine(policy, caps)
        actions = [
            {"command": "plan", "role": "architect", "scope": "project"},
            {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "work_item": "P01-I01",
                "item_kind": "implementation",
            },
            {
                "command": "audit",
                "role": "auditor",
                "scope": "work",
                "mode": "initial",
                "work_item": "P01-I01",
            },
            {
                "command": "audit",
                "role": "auditor",
                "scope": "integration",
                "mode": "initial",
                "risk": "critical",
            },
            {"command": "complete", "role": "none", "scope": "project"},
        ]
        state = {"risk_profile": "medium", "next_action": actions[0]}
        selected = []

        def dispatch(spec, _prompt):
            selected.append(
                (
                    spec["role"],
                    spec["model"]["alias"],
                    spec["model"]["reasoning_effort"],
                )
            )
            index = actions.index(state["next_action"])
            state["next_action"] = actions[index + 1]
            return {"status": "success", "exit_code": 0, "usage": {"total_tokens": 10}}

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda _action: "packet",
            router.resolve,
            dispatch,
            None,
            max_steps=8,
            capabilities=caps,
            scout_before=set(),
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            selected,
            [
                ("architect", "frontier", "high"),
                ("worker", "fast", "high"),
                ("verifier", "frontier", "high"),
                ("integration_auditor", "frontier", "xhigh"),
            ],
        )

    def test_controller_runs_one_scout_before_expensive_specialist(self):
        current = {
            "risk_profile": "medium",
            "next_action": {"command": "plan", "role": "architect", "scope": "project"},
        }
        roles = []
        specialist_capsules = []

        def status():
            return current

        def route(action, state, attempt):
            role = action.get("_role_override") or "architect"
            return {
                "role": role,
                "task_id": None,
                "model": {
                    "selected": "fixture-fast-model"
                    if role == "scout"
                    else "fixture-frontier-model",
                    "reasoning_effort": "medium" if role == "scout" else "xhigh",
                },
                "execution": {
                    "sandbox": "read-only" if role == "scout" else "workspace-write"
                },
                "action": action,
                "attempt": attempt,
            }

        def dispatch(spec, prompt):
            roles.append(spec["role"])
            if spec["role"] == "scout":
                return {
                    "status": "success",
                    "exit_code": 0,
                    "message": "inspect app/service.py",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                }
            specialist_capsules.append(spec.get("scout_digest"))
            current["next_action"] = {
                "command": "complete",
                "role": "none",
                "scope": "project",
            }
            return {
                "status": "success",
                "exit_code": 0,
                "usage": {"input_tokens": 20, "output_tokens": 5},
            }

        controller = self.ap.AutopilotController(
            status,
            lambda a: "packet",
            route,
            dispatch,
            None,
            4,
            scout_before={"architect"},
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(roles, ["scout", "architect"])
        self.assertEqual(specialist_capsules, ["inspect app/service.py"])

    def test_controller_persists_attempts_and_resumes_retry_number(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.ap.RuntimeLedger(Path(td))
            state = {
                "risk_profile": "medium",
                "next_action": {
                    "command": "run",
                    "role": "executor",
                    "scope": "phase",
                    "work_item": "P01-I01",
                },
            }
            seen = []

            def route(action, current, attempt):
                seen.append(attempt)
                return {
                    "role": "worker",
                    "model": {"selected": "x", "reasoning_effort": "high"},
                    "execution": {"sandbox": "workspace-write"},
                    "action": action,
                    "attempt": attempt,
                }

            first = self.ap.AutopilotController(
                lambda: state,
                lambda a: "packet",
                route,
                lambda s, p: {"status": "failed", "exit_code": 1},
                ledger,
                1,
                max_no_progress=5,
                run_id="run-a",
            )
            self.assertEqual(first.run()["status"], "blocked")
            checkpoint = ledger.load_controller()
            second = self.ap.AutopilotController(
                lambda: state,
                lambda a: "packet",
                route,
                lambda s, p: {"status": "failed", "exit_code": 1},
                ledger,
                1,
                max_no_progress=5,
                run_id="run-a",
                resume_state=checkpoint,
            )
            second.run()
            self.assertEqual(seen[:2], [0, 1])

    def test_controller_converts_dispatch_exception_to_recorded_failure(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.ap.RuntimeLedger(Path(td))
            state = {
                "risk_profile": "medium",
                "next_action": {
                    "command": "run",
                    "role": "executor",
                    "scope": "phase",
                    "work_item": "P01-I01",
                },
            }
            controller = self.ap.AutopilotController(
                lambda: state,
                lambda a: "packet",
                lambda a, s, n: {
                    "role": "worker",
                    "model": {"selected": "x", "reasoning_effort": "high"},
                    "execution": {
                        "backend": "codex_exec",
                        "permissions": "inherit",
                    },
                    "action": a,
                    "attempt": n,
                },
                lambda s, p: (_ for _ in ()).throw(TimeoutError("dispatch timed out")),
                ledger,
                1,
                max_no_progress=0,
                max_consecutive_timeouts=1,
            )
            result = controller.run()
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "consecutive_dispatch_timeouts")
            self.assertEqual(controller.attempts, {})
            rows = [
                json.loads(line)
                for line in (Path(td) / "dispatch.jsonl").read_text().splitlines()
            ]
            self.assertEqual(rows[-1]["receipt"]["failure_kind"], "timeout")

    def test_controller_timeout_enters_diagnosis_then_blocks_on_second_timeout(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "work_item": "P01-I01",
            },
        }
        roles = []

        def route(action, _state, attempt):
            role = action.get("_role_override") or "worker"
            return {
                "role": role,
                "model": {"selected": f"fixture-{role}", "reasoning_effort": "high"},
                "execution": {"backend": "codex_exec", "permissions": "inherit"},
                "action": action,
                "attempt": attempt,
            }

        def dispatch(spec, _prompt):
            roles.append(spec["role"])
            if spec["role"] == "diagnostician":
                return {
                    "status": "success",
                    "exit_code": 0,
                    "message": "inspect the stalled command before retrying",
                }
            return {
                "status": "failed",
                "exit_code": 124,
                "failure_kind": "timeout",
                "stderr": "dispatch timed out",
            }

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda _action: "packet",
            route,
            dispatch,
            None,
            4,
            max_no_progress=5,
            max_consecutive_timeouts=2,
            timeout_diagnose_at=1,
        )
        result = controller.run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "consecutive_dispatch_timeouts")
        self.assertEqual(roles, ["worker", "diagnostician", "worker"])
        self.assertEqual(controller.attempts, {})
        self.assertEqual(next(iter(controller.timeout_counts.values())), 2)

    def test_controller_infrastructure_failure_blocks_without_model_poisoning(self):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True)
        router = self.ap.RouteEngine(policy, caps)
        state = {
            "risk_profile": "medium",
            "next_action": {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "work_item": "P01-I01",
                "item_kind": "implementation",
            },
        }
        calls = []

        def dispatch(spec, _prompt):
            calls.append(spec["model"]["alias"])
            return {
                "status": "failed",
                "exit_code": 1,
                "stderr": (
                    'Network access to "raw.githubusercontent.com" was blocked: '
                    "domain is not on the allowlist"
                ),
            }

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda _action: "packet",
            router.resolve,
            dispatch,
            None,
            4,
            capabilities=caps,
        )
        result = controller.run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "dispatch_infrastructure_failure")
        self.assertEqual(result["failure_kind"], "network_unavailable")
        self.assertEqual(calls, ["fast"])
        self.assertEqual(caps.unavailable_rows(), [])
        self.assertEqual(controller.attempts, {})

    def test_controller_preserves_route_failure_detail(self):
        state = {
            "risk_profile": "medium",
            "next_action": {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "work_item": "P01-I01",
            },
        }

        def route(_action, _state, _attempt):
            raise RuntimeError(
                "No available model/backend for profile=economy effort=max"
            )

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda _action: "packet",
            route,
            lambda _spec, _packet: {"status": "success", "exit_code": 0},
            None,
            1,
        )
        result = controller.run()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "route_unavailable")
        self.assertIn("No available model/backend", result["detail"])
        self.assertIn("profile=economy effort=max", result["detail"])

    def test_controller_capability_failure_marks_pair_and_retries_without_progress_penalty(
        self,
    ):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True)
        router = self.ap.RouteEngine(policy, caps)
        state = {
            "risk_profile": "medium",
            "next_action": {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "work_item": "P01-I01",
                "item_kind": "implementation",
            },
        }
        selected = []
        calls = {"n": 0}

        def dispatch(spec, prompt):
            selected.append(spec["model"]["alias"])
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "status": "failed",
                    "exit_code": 1,
                    "stderr": "model unavailable",
                    "failure_kind": "capability_unavailable",
                }
            state["next_action"] = {
                "command": "complete",
                "role": "none",
                "scope": "project",
            }
            return {"status": "success", "exit_code": 0}

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda a: "packet",
            router.resolve,
            dispatch,
            None,
            4,
            capabilities=caps,
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(selected, ["fast", "balanced"])

    def test_controller_capacity_response_falls_back_to_next_model(self):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(
            policy, exec_available=True, codex_version="0.153.0"
        )
        router = self.ap.RouteEngine(policy, caps)
        state = {
            "risk_profile": "medium",
            "next_action": {
                "command": "run",
                "role": "executor",
                "scope": "phase",
                "work_item": "P01-I01",
                "item_kind": "implementation",
            },
        }
        selected = []

        def dispatch(spec, _prompt):
            selected.append(spec["model"]["alias"])
            if len(selected) == 1:
                return {
                    "status": "failed",
                    "exit_code": 1,
                    "stderr": "Selected model is at capacity. Please try a different model.",
                }
            state["next_action"] = {
                "command": "complete",
                "role": "none",
                "scope": "project",
            }
            return {"status": "success", "exit_code": 0}

        controller = self.ap.AutopilotController(
            lambda: state,
            lambda _action: "packet",
            router.resolve,
            dispatch,
            None,
            4,
            capabilities=caps,
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(selected, ["fast", "balanced"])
        self.assertEqual(controller.attempts, {})

    def test_capacity_failure_is_classified_for_model_fallback(self):
        receipt = self.ap.classify_receipt(
            {
                "status": "failed",
                "exit_code": 1,
                "stderr": "Selected model is at capacity. Please try a different model.",
            }
        )
        self.assertEqual(receipt["failure_kind"], "capability_unavailable")

    def test_infrastructure_failures_are_not_classified_as_model_capability(self):
        cases = [
            (
                (
                    'Network access to "raw.githubusercontent.com" was blocked: '
                    "domain is not on the allowlist"
                ),
                "network_unavailable",
            ),
            ("Request denied for codex to run command", "permission_denied"),
            (
                "Error: Proxy dependencies not installed: No module named socksio",
                "backend_unavailable",
            ),
        ]
        for stderr, expected in cases:
            with self.subTest(stderr=stderr):
                receipt = self.ap.classify_receipt(
                    {"status": "failed", "exit_code": 1, "stderr": stderr}
                )
                self.assertEqual(receipt["failure_kind"], expected)

    def test_ledger_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.ap.RuntimeLedger(Path(td))
            ledger.record("dispatch", {"id": "d1"})
            rows = [
                json.loads(x)
                for x in (Path(td) / "dispatch.jsonl").read_text().splitlines()
            ]
            self.assertEqual(rows[0]["id"], "d1")


class AutopilotCliTests(unittest.TestCase):
    def setUp(self):
        self.ap = load_module()
        policy = self.ap.load_policy(PLUGIN, None)
        registry = self.ap.ModelRegistry.from_policy(policy)
        self.models = {alias: registry.model_id(alias) for alias in registry.aliases()}

    def test_cli_exposes_autopilot_capabilities(self):
        import subprocess
        import sys

        proc = subprocess.run(
            [
                sys.executable,
                str(PLUGIN / "scripts" / "devflow.py"),
                "autopilot",
                "capabilities",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertIn("models", doc)
        self.assertIn("model_registry", doc)
        self.assertIn("codex_exec", doc)
        self.assertIn(self.models["fast"], doc["models"])
        self.assertEqual(
            doc["model_registry"]["models"]["fast"]["id"], self.models["fast"]
        )
        self.assertIn(self.models["fast"], doc["codex_exec"]["model_compatibility"])
        self.assertEqual(
            doc["codex_exec"]["alias_compatibility"]["fast"]["model"],
            self.models["fast"],
        )

    def test_cli_help_exposes_autopilot(self):
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, str(PLUGIN / "scripts" / "devflow.py"), "--help"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("autopilot", proc.stdout)

    def test_start_help_exposes_token_budget_override(self):
        import subprocess
        import sys

        proc = subprocess.run(
            [
                sys.executable,
                str(PLUGIN / "scripts" / "devflow.py"),
                "autopilot",
                "start",
                "--help",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--token-budget", proc.stdout)
        self.assertIn("--until", proc.stdout)

    def test_resume_help_exposes_execution_boundary(self):
        import subprocess
        import sys

        proc = subprocess.run(
            [
                sys.executable,
                str(PLUGIN / "scripts" / "devflow.py"),
                "autopilot",
                "resume",
                "--help",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--until", proc.stdout)
        self.assertIn("plan", proc.stdout)
        self.assertIn("implementation", proc.stdout)
        self.assertIn("complete", proc.stdout)

    def test_staged_boundary_rejects_audit_remediation_workflow(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            cli = str(PLUGIN / "scripts" / "devflow.py")
            initialized = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "init",
                    "sample",
                    "--workflow",
                    "audit-remediation",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            started = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "autopilot",
                    "start",
                    "sample",
                    "--until",
                    "plan",
                ],
                cwd=root,
                text=True,
                capture_output=True,
            )
            self.assertEqual(started.returncode, 2)
            self.assertIn(
                "Staged execution boundaries are supported only for delivery workflows",
                started.stderr,
            )

    def test_bootstrap_routes_prd_creation_through_architect_then_initializes_domain(
        self,
    ):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            requirements = root / "requirements.md"
            requirements.write_text(
                "Build a routed autonomous workflow.\n", encoding="utf-8"
            )
            runner = root / "native-runner.py"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import json, re, sys\n"
                "from pathlib import Path\n"
                "payload = json.load(sys.stdin)\n"
                "prompt = payload['prompt']\n"
                "target = re.search(r'^Target PRD path: (.+)$', prompt, re.M).group(1).strip()\n"
                "Path(target).parent.mkdir(parents=True, exist_ok=True)\n"
                "Path(target).write_text('''# Routed workflow PRD\\n\\n## 1. Context\\nAutonomous delivery.\\n\\n## 2. Goals\\nRoute work by role.\\n\\n## 3. Non-goals\\nNone.\\n\\n## 4. Requirements\\n\\n### REQ-001 - Routed lifecycle\\n- Requirement: Route planning and execution to suitable models.\\n- Acceptance criteria:\\n  - AC-001: Planning and implementation use routed specialists.\\n\\n## 5. Business Rules\\n\\n### RULE-001 - Preserve lifecycle\\nUse DevFlow state.\\n\\n## 6. Domain Model / State\\nDevFlow state.\\n\\n## 7. Flows\\nGoal to completion.\\n\\n## 8. Constraints\\nUse installed backends.\\n\\n## 9. Assumptions\\nApproved requirements are stable.\\n\\n## 10. Open Decisions\\nNone.\\n''', encoding='utf-8')\n"
                "print(json.dumps({'status':'success','exit_code':0,'message':'PRD written','usage':{'total_tokens':123}}))\n",
                encoding="utf-8",
            )
            runner.chmod(0o755)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = str(runner)
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = self.models["frontier"]
            cli = str(PLUGIN / "scripts" / "devflow.py")
            boot = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "autopilot",
                    "bootstrap",
                    "sample",
                    "--requirements-file",
                    str(requirements),
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(boot.returncode, 0, boot.stderr + boot.stdout)
            self.assertTrue((root / "docs/domains/sample/PRD.md").exists())
            state = (root / "docs/domains/sample/STATE.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("command: plan", state)
            result = json.loads(boot.stdout)
            self.assertEqual(result["route"]["role"], "architect")
            self.assertEqual(
                result["route"]["model"]["selected"], self.models["frontier"]
            )

    def test_goal_skill_delegates_new_domain_prd_bootstrap_to_autopilot(self):
        text = (PLUGIN / "skills" / "goal" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("autopilot bootstrap", text)
        self.assertIn("--until", text)
        self.assertIn("Do not write execution-control options", text)
        self.assertNotIn("turn the user's approved requirements into a PRD", text)

    def test_route_fails_closed_when_all_frontier_profile_candidates_are_unavailable(self):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = ",".join(
                [self.models["frontier"], self.models["balanced"]]
            )
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run(
                [sys.executable, cli, "init", "sample"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "controller.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-a",
                        "unavailable_candidates": [
                            {
                                "alias": "frontier",
                                "model": self.models["frontier"],
                                "backend": "native_agent",
                                "reason": "model unavailable",
                            },
                            {
                                "alias": "frontier",
                                "model": self.models["frontier"],
                                "backend": "codex_exec",
                                "reason": "model unavailable",
                            },
                            {
                                "alias": "balanced",
                                "model": self.models["balanced"],
                                "backend": "native_agent",
                                "reason": "fallback unavailable",
                            },
                            {
                                "alias": "balanced",
                                "model": self.models["balanced"],
                                "backend": "codex_exec",
                                "reason": "fallback unavailable",
                            },
                        ],
                    }
                )
            )
            routed = subprocess.run(
                [sys.executable, cli, "autopilot", "route", "sample"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(routed.returncode, 2)
            self.assertIn(
                "No available model/backend for profile=frontier effort=high",
                routed.stderr,
            )

    def test_route_is_observational_when_runtime_directory_is_absent(self):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = ",".join(
                [self.models["frontier"], self.models["balanced"]]
            )
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run(
                [sys.executable, cli, "init", "sample"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            self.assertFalse(runtime.exists())
            routed = subprocess.run(
                [sys.executable, cli, "autopilot", "route", "sample"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(routed.returncode, 0, routed.stderr)
            self.assertFalse(runtime.exists())

    def test_concurrent_start_does_not_overwrite_active_controller_checkpoint(self):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = ",".join(
                [self.models["frontier"], self.models["balanced"]]
            )
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run(
                [sys.executable, cli, "init", "sample"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            leases = runtime / "leases"
            leases.mkdir(parents=True, exist_ok=True)
            active = {"status": "running", "run_id": "active-run", "steps_completed": 7}
            (runtime / "controller.json").write_text(json.dumps(active))
            (leases / "mutating-0.lock").write_text(
                json.dumps({"owner": "active-run", "pid": os.getpid()})
            )
            started = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "autopilot",
                    "start",
                    "sample",
                    "--max-steps",
                    "1",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(started.returncode, 1, started.stderr)
            self.assertEqual(
                json.loads((runtime / "controller.json").read_text()), active
            )
            self.assertEqual(
                json.loads(started.stdout)["reason"], "mutating_concurrency_limit"
            )

    def test_fresh_start_does_not_inherit_previous_run_unavailable_candidates(self):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = ",".join(
                [self.models["frontier"], self.models["balanced"]]
            )
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run(
                [sys.executable, cli, "init", "sample"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "controller.json").write_text(
                json.dumps(
                    {
                        "status": "blocked",
                        "run_id": "old-run",
                        "unavailable_candidates": [
                            {
                                "alias": "frontier",
                                "model": self.models["frontier"],
                                "backend": "native_agent",
                                "reason": "old failure",
                            }
                        ],
                    }
                )
            )
            started = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "autopilot",
                    "start",
                    "sample",
                    "--max-steps",
                    "1",
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(started.returncode, 1, started.stderr)
            controller = json.loads((runtime / "controller.json").read_text())
            self.assertNotEqual(controller["run_id"], "old-run")
            self.assertFalse(
                any(
                    row.get("model") == self.models["frontier"]
                    and row.get("backend") == "native_agent"
                    and row.get("reason") == "old failure"
                    for row in controller.get("unavailable_candidates", [])
                ),
                controller,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
