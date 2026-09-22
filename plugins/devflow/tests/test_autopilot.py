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
        self.caps = self.ap.CapabilityRegistry.assumed(self.policy, native_models={"gpt-5.6-sol", "gpt-5.6-terra"}, exec_available=True)
        self.router = self.ap.RouteEngine(self.policy, self.caps)

    def test_routes_routine_implementation_to_luna_high(self):
        spec = self.router.resolve({"command": "run", "scope": "phase", "work_item": "P01-I01", "item_kind": "implementation"}, {"risk_profile": "medium"})
        self.assertEqual((spec["role"], spec["model"]["selected"], spec["model"]["reasoning_effort"]), ("worker", "gpt-5.6-luna", "high"))
        self.assertEqual(spec["execution"]["backend"], "codex_exec")

    def test_task_kind_routes_worker_to_matching_model_and_effort(self):
        cases = [
            ("documentation", "gpt-5.6-luna", "medium"),
            ("test", "gpt-5.6-luna", "high"),
            ("evidence", "gpt-5.6-terra", "high"),
            ("remediation", "gpt-5.6-terra", "xhigh"),
            ("migration", "gpt-5.6-terra", "xhigh"),
        ]
        for item_kind, model, effort in cases:
            with self.subTest(item_kind=item_kind):
                spec = self.router.resolve(
                    {"command": "run", "scope": "phase", "item_kind": item_kind},
                    {"risk_profile": "medium"},
                )
                self.assertEqual((spec["model"]["selected"], spec["model"]["reasoning_effort"]), (model, effort))

    def test_routes_planning_to_sol_xhigh(self):
        spec = self.router.resolve({"command": "plan", "scope": "project"}, {"risk_profile": "medium"})
        self.assertEqual((spec["role"], spec["model"]["selected"], spec["model"]["reasoning_effort"]), ("architect", "gpt-5.6-sol", "xhigh"))
        self.assertEqual(spec["execution"]["backend"], "native_agent")

    def test_critical_integration_audit_routes_to_sol_max(self):
        spec = self.router.resolve({"command": "audit", "scope": "integration", "mode": "initial"}, {"risk_profile": "critical"})
        self.assertEqual((spec["model"]["selected"], spec["model"]["reasoning_effort"]), ("gpt-5.6-sol", "max"))

    def test_work_verification_uses_terra_then_promotes_to_sol_for_high_risk(self):
        medium = self.router.resolve(
            {"command": "audit", "scope": "work", "item_kind": "implementation", "item_risk": "medium"},
            {"risk_profile": "medium"},
        )
        high = self.router.resolve(
            {"command": "audit", "scope": "work", "item_kind": "implementation", "item_risk": "high"},
            {"risk_profile": "medium"},
        )
        critical = self.router.resolve(
            {"command": "audit", "scope": "work", "item_kind": "implementation", "item_risk": "critical"},
            {"risk_profile": "medium"},
        )
        self.assertEqual((medium["model"]["selected"], medium["model"]["reasoning_effort"]), ("gpt-5.6-terra", "high"))
        self.assertEqual((high["model"]["selected"], high["model"]["reasoning_effort"]), ("gpt-5.6-sol", "xhigh"))
        self.assertEqual((critical["model"]["selected"], critical["model"]["reasoning_effort"]), ("gpt-5.6-sol", "max"))

    def test_high_risk_worker_uses_terra_xhigh(self):
        spec = self.router.resolve({"command": "run", "scope": "phase", "item_kind": "implementation"}, {"risk_profile": "high"})
        self.assertEqual(spec["model"]["selected"], "gpt-5.6-terra")
        self.assertEqual(spec["model"]["reasoning_effort"], "xhigh")

    def test_high_work_risk_overrides_medium_domain_risk(self):
        spec = self.router.resolve(
            {"command": "run", "scope": "phase", "item_kind": "implementation", "item_risk": "high"},
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["effective_risk"], "high")
        self.assertEqual((spec["model"]["selected"], spec["model"]["reasoning_effort"]), ("gpt-5.6-terra", "xhigh"))

    def test_critical_work_risk_routes_worker_to_sol_xhigh(self):
        spec = self.router.resolve(
            {"command": "run", "scope": "phase", "item_kind": "implementation", "item_risk": "critical"},
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["effective_risk"], "critical")
        self.assertEqual((spec["model"]["selected"], spec["model"]["reasoning_effort"]), ("gpt-5.6-sol", "xhigh"))

    def test_domain_risk_is_a_floor_for_lower_work_risk(self):
        spec = self.router.resolve(
            {"command": "run", "scope": "phase", "item_kind": "implementation", "item_risk": "low"},
            {"risk_profile": "critical"},
        )
        self.assertEqual(spec["effective_risk"], "critical")
        self.assertEqual((spec["model"]["selected"], spec["model"]["reasoning_effort"]), ("gpt-5.6-sol", "xhigh"))

    def test_unavailable_model_backend_pair_falls_back_to_next_candidate(self):
        self.caps.mark_unavailable("gpt-5.6-luna", "codex_exec", "model unavailable")
        spec = self.router.resolve(
            {"command": "run", "scope": "phase", "item_kind": "implementation"},
            {"risk_profile": "medium"},
        )
        self.assertEqual(spec["model"]["selected"], "gpt-5.6-terra")
        self.assertEqual(spec["execution"]["backend"], "native_agent")

    def test_codex_backend_enforces_minimum_cli_version(self):
        old_caps = self.ap.CapabilityRegistry.assumed(
            self.policy, exec_available=True, codex_version="0.143.9",
        )
        self.assertIsNone(old_caps.backend_for("gpt-5.6-sol", ["codex_exec"]))
        self.assertIsNone(old_caps.backend_for("gpt-5.6-terra", ["codex_exec"]))

        new_caps = self.ap.CapabilityRegistry.assumed(
            self.policy, exec_available=True, codex_version="0.144.0",
        )
        self.assertEqual(new_caps.backend_for("gpt-5.6-sol", ["codex_exec"]), "codex_exec")
        self.assertEqual(new_caps.backend_for("gpt-5.6-terra", ["codex_exec"]), "codex_exec")

    def test_detected_codex_version_controls_per_model_compatibility(self):
        import os
        with tempfile.TemporaryDirectory() as td:
            codex = Path(td) / "codex"
            codex.write_text("#!/bin/sh\necho 'codex-cli 0.143.9'\n", encoding="utf-8")
            codex.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            old_runner = os.environ.pop("DEVFLOW_NATIVE_AGENT_RUNNER", None)
            old_models = os.environ.pop("DEVFLOW_NATIVE_AGENT_MODELS", None)
            try:
                os.environ["PATH"] = td + os.pathsep + old_path
                caps = self.ap.CapabilityRegistry.detect(self.policy)
            finally:
                os.environ["PATH"] = old_path
                if old_runner is not None:
                    os.environ["DEVFLOW_NATIVE_AGENT_RUNNER"] = old_runner
                if old_models is not None:
                    os.environ["DEVFLOW_NATIVE_AGENT_MODELS"] = old_models
            self.assertEqual(caps.codex_version, "0.143.9")
            self.assertTrue(caps.exec_available)
            self.assertIsNone(caps.backend_for("gpt-5.6-sol", ["codex_exec"]))
            self.assertIsNone(caps.backend_for("gpt-5.6-terra", ["codex_exec"]))

    def test_route_consumes_context_delegation_and_multi_agent_policy(self):
        spec = self.router.resolve({"command": "plan", "scope": "project"}, {"risk_profile": "medium"})
        self.assertEqual(spec["execution"]["context_mode"], self.policy["context"]["default_mode"] )
        self.assertEqual(spec["execution"]["native_fork_turns"], self.policy["context"]["native_fork_turns"] )
        self.assertFalse(spec["execution"]["allow_recursive_delegation"] )
        self.assertEqual(spec["execution"]["model_multi_agent"], self.policy["models"][spec["model"]["selected"]]["multi_agent"] )

    def test_retry_escalates_worker_model_then_diagnosis_and_sol_retry(self):
        action = {"command": "run", "scope": "phase", "item_kind": "implementation"}
        state = {"risk_profile": "medium"}
        first = self.router.resolve(action, state, attempt=0)
        retry = self.router.resolve(action, state, attempt=1)
        diag = self.router.resolve(action, state, attempt=2)
        post_diag = self.router.resolve(action, state, attempt=3)
        self.assertEqual((first["model"]["selected"], first["model"]["reasoning_effort"]), ("gpt-5.6-luna", "high"))
        self.assertEqual((retry["model"]["selected"], retry["model"]["reasoning_effort"]), ("gpt-5.6-terra", "xhigh"))
        self.assertEqual(diag["role"], "diagnostician")
        self.assertEqual((diag["model"]["selected"], diag["model"]["reasoning_effort"]), ("gpt-5.6-sol", "xhigh"))
        self.assertEqual((post_diag["model"]["selected"], post_diag["model"]["reasoning_effort"]), ("gpt-5.6-sol", "xhigh"))


class AutopilotRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.ap = load_module()

    def test_codex_exec_command_contains_model_effort_and_isolated_session(self):
        backend = self.ap.CodexExecBackend("codex")
        spec = {"model": {"selected": "gpt-5.6-luna", "reasoning_effort": "xhigh"}, "execution": {"sandbox": "workspace-write"}}
        cmd = backend.build_command(Path("/repo"), spec)
        joined = " ".join(cmd)
        self.assertIn("exec", cmd)
        self.assertIn("--ephemeral", cmd)
        self.assertIn("gpt-5.6-luna", cmd)
        self.assertIn('model_reasoning_effort="xhigh"', joined)
        self.assertIn("--json", cmd)

    def test_context_capsule_contains_role_contract_and_packet_without_parent_history(self):
        assembler = self.ap.ContextAssembler(PLUGIN)
        spec = {"role": "worker", "task_id": "P01-I01", "model": {"selected": "gpt-5.6-luna", "reasoning_effort": "high"}}
        text = assembler.build(spec, "RENDERED_PACKET", diagnosis="prior diagnosis")
        self.assertIn("RENDERED_PACKET", text)
        self.assertIn("prior diagnosis", text)
        self.assertIn("DevFlow Run", text)
        self.assertIn(str(PLUGIN / "scripts" / "devflow.py"), text)
        self.assertIn("DEVFLOW_PLUGIN_ROOT", text)
        self.assertNotIn("parent_conversation", text)

    def test_diagnostician_has_dedicated_read_only_contract(self):
        assembler = self.ap.ContextAssembler(PLUGIN)
        spec = {
            "role": "diagnostician",
            "task_id": "P01-I01",
            "model": {"selected": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
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
                "model": {"selected": "gpt-5.6-luna", "reasoning_effort": "high"},
                "execution": {"backend": "codex_exec", "sandbox": "workspace-write"},
                "action": action,
                "attempt": attempt,
            },
            lambda spec, prompt: dispatched.append((spec, prompt)) or {"status": "success"},
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
            with first:
                with self.assertRaises(RuntimeError):
                    second.acquire()
            with second:
                self.assertTrue(second.acquired)

    def test_controller_stops_on_complete_without_dispatch(self):
        states = iter([{"risk_profile": "medium", "next_action": {"command": "complete", "role": "none", "scope": "project"}}])
        dispatched = []
        controller = self.ap.AutopilotController(
            status_fn=lambda: next(states), render_fn=lambda a: "", route_fn=lambda a, s, n: {},
            dispatch_fn=lambda s, p: dispatched.append((s, p)), ledger=None, max_steps=3,
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(dispatched, [])

    def test_controller_pauses_for_human_decision(self):
        state = {"risk_profile": "medium", "next_action": {"command": "decision", "role": "human", "scope": "project"}}
        controller = self.ap.AutopilotController(lambda: state, lambda a: "", lambda a, s, n: {}, lambda s, p: {}, None, 3)
        self.assertEqual(controller.run()["status"], "paused")

    def test_controller_dispatches_until_state_progresses_then_completes(self):
        states = [
            {"risk_profile": "medium", "next_action": {"command": "run", "role": "executor", "scope": "phase", "work_item": "P01-I01"}},
            {"risk_profile": "medium", "next_action": {"command": "complete", "role": "none", "scope": "project"}},
        ]
        calls = {"status": 0, "dispatch": 0}
        def status():
            idx = min(calls["status"], len(states) - 1); calls["status"] += 1; return states[idx]
        def dispatch(spec, prompt):
            calls["dispatch"] += 1; return {"status": "success", "exit_code": 0, "usage": {"input_tokens": 10}}
        controller = self.ap.AutopilotController(status, lambda a: "packet", lambda a, s, n: {"role": "worker", "model": {"selected": "x", "reasoning_effort": "high"}}, dispatch, None, 5)
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(calls["dispatch"], 1)
        self.assertEqual(result["steps"], 1)

    def test_controller_changes_models_across_lifecycle_roles(self):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True, codex_version="0.153.0")
        router = self.ap.RouteEngine(policy, caps)
        actions = [
            {"command": "plan", "role": "architect", "scope": "project"},
            {"command": "run", "role": "executor", "scope": "phase", "work_item": "P01-I01", "item_kind": "implementation"},
            {"command": "audit", "role": "auditor", "scope": "work", "mode": "initial", "work_item": "P01-I01"},
            {"command": "audit", "role": "auditor", "scope": "integration", "mode": "initial", "risk": "critical"},
            {"command": "complete", "role": "none", "scope": "project"},
        ]
        state = {"risk_profile": "medium", "next_action": actions[0]}
        selected = []

        def dispatch(spec, _prompt):
            selected.append((spec["role"], spec["model"]["selected"], spec["model"]["reasoning_effort"]))
            index = actions.index(state["next_action"])
            state["next_action"] = actions[index + 1]
            return {"status": "success", "exit_code": 0, "usage": {"total_tokens": 10}}

        controller = self.ap.AutopilotController(
            lambda: state, lambda _action: "packet", router.resolve, dispatch, None, max_steps=8,
            capabilities=caps, scout_before=set(),
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(selected, [
            ("architect", "gpt-5.6-sol", "xhigh"),
            ("worker", "gpt-5.6-luna", "high"),
            ("verifier", "gpt-5.6-terra", "high"),
            ("integration_auditor", "gpt-5.6-sol", "max"),
        ])

    def test_controller_runs_one_scout_before_expensive_specialist(self):
        current = {"risk_profile": "medium", "next_action": {"command": "plan", "role": "architect", "scope": "project"}}
        roles = []
        def status():
            return current
        def route(action, state, attempt):
            role = action.get("_role_override") or "architect"
            return {
                "role": role,
                "task_id": None,
                "model": {"selected": "gpt-5.6-luna" if role == "scout" else "gpt-5.6-sol", "reasoning_effort": "medium" if role == "scout" else "xhigh"},
                "execution": {"sandbox": "read-only" if role == "scout" else "workspace-write"},
                "action": action,
                "attempt": attempt,
            }
        def dispatch(spec, prompt):
            roles.append(spec["role"])
            if spec["role"] == "scout":
                return {"status": "success", "exit_code": 0, "message": "inspect app/service.py", "usage": {"input_tokens": 10, "output_tokens": 5}}
            current["next_action"] = {"command": "complete", "role": "none", "scope": "project"}
            return {"status": "success", "exit_code": 0, "usage": {"input_tokens": 20, "output_tokens": 5}}
        controller = self.ap.AutopilotController(
            status, lambda a: "packet", route, dispatch, None, 4,
            scout_before={"architect"},
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(roles, ["scout", "architect"])

    def test_controller_persists_attempts_and_resumes_retry_number(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.ap.RuntimeLedger(Path(td))
            state = {"risk_profile": "medium", "next_action": {"command": "run", "role": "executor", "scope": "phase", "work_item": "P01-I01"}}
            seen = []
            def route(action, current, attempt):
                seen.append(attempt)
                return {"role": "worker", "model": {"selected": "x", "reasoning_effort": "high"}, "execution": {"sandbox": "workspace-write"}, "action": action, "attempt": attempt}
            first = self.ap.AutopilotController(lambda: state, lambda a: "packet", route, lambda s, p: {"status": "failed", "exit_code": 1}, ledger, 1, max_no_progress=5, run_id="run-a")
            self.assertEqual(first.run()["status"], "blocked")
            checkpoint = ledger.load_controller()
            second = self.ap.AutopilotController(lambda: state, lambda a: "packet", route, lambda s, p: {"status": "failed", "exit_code": 1}, ledger, 1, max_no_progress=5, run_id="run-a", resume_state=checkpoint)
            second.run()
            self.assertEqual(seen[:2], [0, 1])

    def test_controller_converts_dispatch_exception_to_recorded_failure(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.ap.RuntimeLedger(Path(td))
            state = {"risk_profile": "medium", "next_action": {"command": "run", "role": "executor", "scope": "phase", "work_item": "P01-I01"}}
            controller = self.ap.AutopilotController(
                lambda: state, lambda a: "packet",
                lambda a, s, n: {"role": "worker", "model": {"selected": "x", "reasoning_effort": "high"}, "execution": {"backend": "codex_exec", "sandbox": "workspace-write"}, "action": a, "attempt": n},
                lambda s, p: (_ for _ in ()).throw(TimeoutError("dispatch timed out")),
                ledger, 1, max_no_progress=0,
            )
            result = controller.run()
            self.assertEqual(result["status"], "blocked")
            rows = [json.loads(line) for line in (Path(td) / "dispatch.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["receipt"]["failure_kind"], "timeout")

    def test_controller_capability_failure_marks_pair_and_retries_without_progress_penalty(self):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True)
        router = self.ap.RouteEngine(policy, caps)
        state = {"risk_profile": "medium", "next_action": {"command": "run", "role": "executor", "scope": "phase", "work_item": "P01-I01", "item_kind": "implementation"}}
        selected = []
        calls = {"n": 0}
        def dispatch(spec, prompt):
            selected.append(spec["model"]["selected"]); calls["n"] += 1
            if calls["n"] == 1:
                return {"status": "failed", "exit_code": 1, "stderr": "model unavailable", "failure_kind": "capability_unavailable"}
            state["next_action"] = {"command": "complete", "role": "none", "scope": "project"}
            return {"status": "success", "exit_code": 0}
        controller = self.ap.AutopilotController(
            lambda: state, lambda a: "packet", router.resolve, dispatch, None, 4, capabilities=caps
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(selected, ["gpt-5.6-luna", "gpt-5.6-terra"])

    def test_controller_capacity_response_falls_back_to_next_model(self):
        policy = self.ap.load_policy(PLUGIN, None)
        caps = self.ap.CapabilityRegistry.assumed(policy, exec_available=True, codex_version="0.153.0")
        router = self.ap.RouteEngine(policy, caps)
        state = {
            "risk_profile": "medium",
            "next_action": {"command": "run", "role": "executor", "scope": "phase", "work_item": "P01-I01", "item_kind": "implementation"},
        }
        selected = []

        def dispatch(spec, _prompt):
            selected.append(spec["model"]["selected"])
            if len(selected) == 1:
                return {"status": "failed", "exit_code": 1, "stderr": "Selected model is at capacity. Please try a different model."}
            state["next_action"] = {"command": "complete", "role": "none", "scope": "project"}
            return {"status": "success", "exit_code": 0}

        controller = self.ap.AutopilotController(
            lambda: state, lambda _action: "packet", router.resolve, dispatch, None, 4, capabilities=caps,
        )
        result = controller.run()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(selected, ["gpt-5.6-luna", "gpt-5.6-terra"])
        self.assertEqual(controller.attempts, {})

    def test_capacity_failure_is_classified_for_model_fallback(self):
        receipt = self.ap.classify_receipt({
            "status": "failed",
            "exit_code": 1,
            "stderr": "Selected model is at capacity. Please try a different model.",
        })
        self.assertEqual(receipt["failure_kind"], "capability_unavailable")

    def test_ledger_appends_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            ledger = self.ap.RuntimeLedger(Path(td))
            ledger.record("dispatch", {"id": "d1"})
            rows = [json.loads(x) for x in (Path(td) / "dispatch.jsonl").read_text().splitlines()]
            self.assertEqual(rows[0]["id"], "d1")


class AutopilotCliTests(unittest.TestCase):
    def test_cli_exposes_autopilot_capabilities(self):
        import subprocess, sys
        proc = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "devflow.py"), "autopilot", "capabilities"], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertIn("models", doc)
        self.assertIn("codex_exec", doc)

    def test_cli_help_exposes_autopilot(self):
        import subprocess, sys
        proc = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "devflow.py"), "--help"], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("autopilot", proc.stdout)

    def test_start_help_exposes_token_budget_override(self):
        import subprocess, sys
        proc = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "devflow.py"), "autopilot", "start", "--help"], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--token-budget", proc.stdout)

    def test_bootstrap_routes_prd_creation_through_architect_then_initializes_domain(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            requirements = root / "requirements.md"
            requirements.write_text("Build a routed autonomous workflow.\n", encoding="utf-8")
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
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = "gpt-5.6-sol"
            cli = str(PLUGIN / "scripts" / "devflow.py")
            boot = subprocess.run(
                [sys.executable, cli, "autopilot", "bootstrap", "sample", "--requirements-file", str(requirements)],
                cwd=root, env=env, text=True, capture_output=True,
            )
            self.assertEqual(boot.returncode, 0, boot.stderr + boot.stdout)
            self.assertTrue((root / "docs/domains/sample/PRD.md").exists())
            state = (root / "docs/domains/sample/STATE.yaml").read_text(encoding="utf-8")
            self.assertIn("command: plan", state)
            result = json.loads(boot.stdout)
            self.assertEqual(result["route"]["role"], "architect")
            self.assertEqual(result["route"]["model"]["selected"], "gpt-5.6-sol")

    def test_goal_skill_delegates_new_domain_prd_bootstrap_to_autopilot(self):
        text = (PLUGIN / "skills" / "goal" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("autopilot bootstrap", text)
        self.assertNotIn("turn the user's approved requirements into a PRD", text)

    def test_route_honors_persisted_unavailable_candidate(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = "gpt-5.6-sol,gpt-5.6-terra"
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run([sys.executable, cli, "init", "sample"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "controller.json").write_text(json.dumps({
                "run_id": "run-a",
                "unavailable_candidates": [
                    {"model": "gpt-5.6-sol", "backend": "native_agent", "reason": "model unavailable"},
                    {"model": "gpt-5.6-sol", "backend": "codex_exec", "reason": "model unavailable"}
                ],
            }))
            routed = subprocess.run([sys.executable, cli, "autopilot", "route", "sample"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(routed.returncode, 0, routed.stderr)
            doc = json.loads(routed.stdout)
            self.assertEqual(doc["dispatch"]["model"]["selected"], "gpt-5.6-terra")

    def test_route_is_observational_when_runtime_directory_is_absent(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = "gpt-5.6-sol,gpt-5.6-terra"
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run([sys.executable, cli, "init", "sample"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            self.assertFalse(runtime.exists())
            routed = subprocess.run([sys.executable, cli, "autopilot", "route", "sample"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(routed.returncode, 0, routed.stderr)
            self.assertFalse(runtime.exists())

    def test_concurrent_start_does_not_overwrite_active_controller_checkpoint(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = "gpt-5.6-sol,gpt-5.6-terra"
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run([sys.executable, cli, "init", "sample"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            leases = runtime / "leases"
            leases.mkdir(parents=True, exist_ok=True)
            active = {"status": "running", "run_id": "active-run", "steps_completed": 7}
            (runtime / "controller.json").write_text(json.dumps(active))
            (leases / "mutating-0.lock").write_text(json.dumps({"owner": "active-run", "pid": os.getpid()}))
            started = subprocess.run([sys.executable, cli, "autopilot", "start", "sample", "--max-steps", "1"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(started.returncode, 1, started.stderr)
            self.assertEqual(json.loads((runtime / "controller.json").read_text()), active)
            self.assertEqual(json.loads(started.stdout)["reason"], "mutating_concurrency_limit")

    def test_fresh_start_does_not_inherit_previous_run_unavailable_candidates(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            env = os.environ.copy()
            env["DEVFLOW_NATIVE_AGENT_RUNNER"] = "/bin/true"
            env["DEVFLOW_NATIVE_AGENT_MODELS"] = "gpt-5.6-sol,gpt-5.6-terra"
            cli = str(PLUGIN / "scripts" / "devflow.py")
            init = subprocess.run([sys.executable, cli, "init", "sample"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(init.returncode, 0, init.stderr)
            runtime = root / ".devflow/runtime/sample"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "controller.json").write_text(json.dumps({
                "status": "blocked", "run_id": "old-run",
                "unavailable_candidates": [
                    {"model": "gpt-5.6-sol", "backend": "native_agent", "reason": "old failure"}
                ],
            }))
            started = subprocess.run([sys.executable, cli, "autopilot", "start", "sample", "--max-steps", "1"], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(started.returncode, 1, started.stderr)
            controller = json.loads((runtime / "controller.json").read_text())
            self.assertNotEqual(controller["run_id"], "old-run")
            self.assertFalse(
                any(
                    row.get("model") == "gpt-5.6-sol"
                    and row.get("backend") == "native_agent"
                    and row.get("reason") == "old failure"
                    for row in controller.get("unavailable_candidates", [])
                ),
                controller,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
