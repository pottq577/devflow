#!/usr/bin/env python3
"""Self-check for the DevFlow runtime.

No framework. Run it directly:

    python3 tests/test_devflow.py

Each case builds a throwaway git repository, drives the CLI, and asserts on real output.
Fixtures are built as Python objects and dumped with PyYAML, never as indented heredocs, so a
malformed fixture cannot masquerade as a passing assertion.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from unittest import mock
from pathlib import Path
from typing import Any

import yaml

PLUGIN = Path(__file__).resolve().parent.parent
CLI = PLUGIN / "scripts" / "devflow.py"
RUNTIME_PROTOCOL = yaml.safe_load((PLUGIN / "core/templates/STATE.yaml").read_text(encoding="utf-8"))["protocol_version"]

PASSED: list[str] = []
FAILED: list[str] = []


def sh(
    cmd: list[str],
    cwd: Path,
    check: bool = False,
    timeout: float = 20,
) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or "<none>"
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or "<none>"
        raise RuntimeError(
            f"command timed out after {timeout} seconds\n"
            f"command: {' '.join(cmd)}\n"
            f"cwd: {cwd}\n"
            f"stdout: {stdout}\n"
            f"stderr: {stderr}"
        ) from exc
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip()}")
    return proc


def devflow(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Drive legacy completion-contract scenarios at the current audit protocol.

    These existing scenarios predate source-comment/PR/Postman evidence. Their fixtures explicitly
    omit the optional additive delivery policy; assertions on lifecycle, rollback, audits and
    WORK v1/v2 remain unchanged. test_delivery.py invokes runtime directly to test the new init
    default and full delivery-enabled lifecycle, without this legacy fixture preparation.
    """
    proc = sh([sys.executable, str(CLI), *args], cwd)
    if proc.returncode == 0 and args and args[0] == "init":
        d = cwd / "docs/domains" / args[1]
        if "audit-remediation" not in args:
            fill_delivery_contract(d)
        state_file = d / "STATE.yaml"
        legacy = yaml.safe_load(state_file.read_text(encoding="utf-8"))
        legacy.pop("delivery", None)
        dump(state_file, legacy)
    return proc


def load_runtime_module():
    spec = importlib.util.spec_from_file_location(f"devflow_runtime_{len(PASSED) + len(FAILED)}", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke_runtime(root: Path, runtime: Any, *args: str) -> subprocess.CompletedProcess:
    stdout = io.StringIO()
    stderr = io.StringIO()
    previous_cwd = Path.cwd()
    previous_argv = sys.argv
    try:
        os.chdir(root)
        sys.argv = [str(CLI), *args]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returncode = runtime.main()
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)
    return subprocess.CompletedProcess([str(CLI), *args], returncode, stdout.getvalue(), stderr.getvalue())


def new_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="devflow-test-"))
    sh(["git", "init", "-q", "."], root, check=True)
    sh(["git", "config", "user.email", "t@example.com"], root, check=True)
    sh(["git", "config", "user.name", "t"], root, check=True)
    (root / "seed.txt").write_text("seed\n")
    sh(["git", "add", "-A"], root, check=True)
    sh(["git", "commit", "-qm", "init"], root, check=True)
    return root


def commit(root: Path, name: str) -> None:
    """Commit one named file. Deliberately not `add -A`, so DevFlow artifacts stay untracked
    and branch switches in the topology fixture cannot clobber them."""
    (root / f"{name}.txt").write_text(f"{name}\n")
    sh(["git", "add", f"{name}.txt"], root, check=True)
    sh(["git", "commit", "-qm", name], root, check=True)


def commit_paths(root: Path, message: str, *paths: Path) -> None:
    relative = [str(path.relative_to(root)) for path in paths]
    sh(["git", "add", *relative], root, check=True)
    sh(["git", "commit", "-qm", message], root, check=True)


def dump(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def phase(status: str, num: str = "05") -> dict[str, Any]:
    return {"status": status, "work_file": f"work/phase-{num}.yaml", "audit_file": f"audits/phase-{num}.md"}


def legacy_config(root: Path, version: str) -> None:
    """Pin .devflow/config.yaml to a pre-1.3 protocol. Pair it with `state(..., protocol_version=<same>)`
    for a test that exercises a legacy `verified` transition: the audit-apply gate reads the higher
    of the STATE and config versions, so both must be pre-1.3 for the legacy command to be allowed."""
    cfg = root / ".devflow/config.yaml"
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    doc["protocol_version"] = version
    dump(cfg, doc)


def state(phases: dict[str, Any], *, integration: str = "pending", **extra: Any) -> dict[str, Any]:
    """A STATE fixture at the current protocol with the legacy optional delivery policy absent. A test
    that needs a genuine pre-1.3 project passes `protocol_version="1.2.0"` and calls `legacy_config`."""
    doc: dict[str, Any] = {
        "protocol_version": RUNTIME_PROTOCOL,
        "domain": "billing",
        "risk_profile": "medium",
        "project_status": "phase_execution",
        "baseline_sha": None,
        "target_sha": None,
        "active_phase": None,
        "plan_review": {"required": False, "status": "skipped", "audit_file": "audits/plan.md"},
        "phases": phases,
        "integration": {"status": integration, "work_file": "work/integration.yaml", "audit_file": "audits/integration.md"},
        "unresolved_decisions": [],
        "next_action": {"role": "executor", "command": "run", "scope": "phase", "phase": None, "work_item": None},
    }
    doc.update(extra)
    return doc


def item(item_id: str, **over: Any) -> dict[str, Any]:
    """A schema-complete WORK item. Anything in `over` replaces or adds a field."""
    doc: dict[str, Any] = {
        "id": item_id,
        "kind": over.pop("kind", "implementation"),
        "title": item_id,
        "origin": {"requirements": over.pop("requirements", []), "findings": [], "plan_items": []},
        "objective": f"objective for {item_id}",
        "dependencies": [],
        "decision_dependencies": [],
        "scope": {"allowed": [], "forbidden": []},
        "requirements": [],
        "verification": {"commands": ["true"]},
        "acceptance": [f"acceptance for {item_id}"],
        "stop_conditions": [],
        "risk": {"level": over.pop("risk_level", "medium"), "axes": []},
        "status": over.pop("status", "ready"),
        "block_reason": None,
        "evidence": {"commit": None, "changed_files": [], "commands": over.pop("commands", []), "deviations": [], "discoveries": []},
    }
    doc.update(over)
    return doc


def work(phase_num: str, *items: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "phase": phase_num, "items": list(items)}


def v2_item(
    item_id: str,
    acceptance: list[Any] | None = None,
    commands: list[Any] | None = None,
) -> dict[str, Any]:
    acceptance = acceptance if acceptance is not None else [{"id": "AC-01", "criterion": f"acceptance for {item_id}"}]
    commands = commands if commands is not None else [{"id": "V-01", "command": "true", "covers": ["AC-01"]}]
    return item(item_id, acceptance=acceptance, verification={"commands": commands})


def work_v2(phase_num: str, *items: dict[str, Any]) -> dict[str, Any]:
    return {"version": 2, "phase": phase_num, "items": list(items)}


def audit_finding(finding_id: str, **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": finding_id,
        "classification": "REJECTED",
        "severity": "minor",
        "severity_reason": "Repository evidence disproves the suspected defect.",
        "axis": "correctness",
        "expected": "The approved behavior remains intact.",
        "actual": "The approved behavior remains intact.",
        "evidence": ["targeted check passed"],
        "root_cause": "The original concern did not reproduce.",
        "disposition": {"action": "record_only", "work_ids": [], "decision_ids": []},
    }
    doc.update(over)
    return doc


def audit_metadata(d: Path, **over: Any) -> dict[str, Any]:
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    doc: dict[str, Any] = {
        "schema": "devflow-audit-v1",
        "scope": "integration",
        "mode": "initial",
        "verdict": "pass",
        "baseline_sha": state_doc["baseline_sha"],
        "target_sha": state_doc["target_sha"],
        "diff_range": "current-head",
        "verification": [{"command": "true", "result": "passed"}],
        "findings": [],
        "closure": [],
    }
    doc.update(over)
    return doc


def write_audit(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    front_matter = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
    path.write_text(f"---\n{front_matter}---\n\n# Audit\n", encoding="utf-8")


def read_audit(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"audit front matter missing: {path}")
    return yaml.safe_load(text.split("---", 2)[1])


def write_open_decision(path: Path, decision_id: str) -> None:
    path.write_text(
        "# Decisions\n\n"
        "## Open\n\n"
        f"### {decision_id} Retention policy\n"
        "- Trigger: An audit found an unresolved product policy.\n"
        "- Affected requirements/work: billing\n"
        "- Option A: Retain records for 30 days.\n"
        "- Option B: Delete records immediately.\n"
        "- Impact: The selected option changes retention behavior.\n\n"
        "## Resolved\n",
        encoding="utf-8",
    )


def fill_delivery_contract(d: Path) -> None:
    (d / "PRD.md").write_text(
        "# Billing PRD\n\n"
        "## 4. Requirements\n\n"
        "### REQ-001 Billing behavior\n"
        "- Requirement: Preserve the approved billing behavior.\n"
        "- Acceptance criteria: AC-001 is verified.\n",
        encoding="utf-8",
    )
    (d / "PLAN.md").write_text(
        "# Implementation PLAN\n\n"
        "## Metadata\n"
        "- Domain: billing\n"
        "- Baseline SHA: HEAD\n"
        "- Risk profile: medium\n\n"
        "## Repository findings\nThe repository structure is recorded.\n\n"
        "## Architecture / implementation strategy\nUse the existing runtime boundary.\n\n"
        "## Requirement traceability\nREQ-001 maps to Phase 01.\n\n"
        "## Phase graph\n\n"
        "### Phase 01 Billing\n"
        "- Objective: Preserve the approved behavior.\n\n"
        "## Verification strategy\nRun the targeted regression suite.\n",
        encoding="utf-8",
    )


def fill_audit_remediation_contract(d: Path) -> None:
    (d / "PRD.md").write_text(
        "# Audit Scope Contract\n\n"
        "## Audit target\nCurrent billing implementation.\n\n"
        "## User-verified flows\nBilling flow.\n\n"
        "## In scope\nBilling runtime.\n\n"
        "## Out of scope\nUnrelated domains.\n\n"
        "## Authoritative requirements and policies\nRepository policy.\n\n"
        "## Success criteria\nAll findings are dispositioned.\n\n"
        "## Open decisions\nNone.\n",
        encoding="utf-8",
    )
    (d / "PLAN.md").write_text(
        "# Audit and Remediation PLAN\n\n"
        "## Metadata\nDomain: billing.\n\n"
        "## Repository reconnaissance\nInspect the current repository.\n\n"
        "## Audit axes\nUse the standard audit axes.\n\n"
        "## Evidence plan\nRun targeted checks.\n\n"
        "## Finding disposition strategy\nClassify every finding.\n\n"
        "## Remediation topology\nUse integration WORK only.\n\n"
        "## Closure criteria\nAll required evidence passes.\n",
        encoding="utf-8",
    )


def audit_remediation_fixture(root: Path) -> Path:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    return d


def broken_delivery_fixture(root: Path) -> Path:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    (d / "PRD.md").write_text((PLUGIN / "core/templates/PRD.md").read_text(encoding="utf-8"), encoding="utf-8")
    (d / "PLAN.md").write_text((PLUGIN / "core/templates/PLAN.md").read_text(encoding="utf-8"), encoding="utf-8")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text())
    state_doc["workflow_type"] = "delivery"
    dump(d / "STATE.yaml", state_doc)
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    (d / "audits/integration.md").write_text("# Existing integration audit\n", encoding="utf-8")
    return d


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}")
        if detail:
            print(textwrap.indent(detail.strip()[:1200], "        "))


# --- fixture sanity -----------------------------------------------------------------
# The first version of this file built YAML with indented f-strings and produced malformed
# STATE files, which made assertions pass for the wrong reason. Guard the fixtures themselves.

def case_fixtures_are_valid_yaml(root: Path) -> None:
    parsed = yaml.safe_load(yaml.safe_dump(state({"5": phase("verified")}), sort_keys=False))
    check("state fixture round-trips with its phase key intact", list(parsed["phases"]) == ["5"], repr(parsed.get("phases")))
    parsed = yaml.safe_load(yaml.safe_dump(work("01", item("P01-I01", premise_checks=["x"])), sort_keys=False))
    check("item fixture carries optional fields", parsed["items"][0].get("premise_checks") == ["x"], repr(parsed["items"][0]))
    check("item fixture keeps required fields", parsed["items"][0]["risk"]["level"] == "medium", repr(parsed["items"][0]))


def case_timeout_diagnostics(root: Path) -> None:
    # Skip third-party site startup so the timeout probe measures its child, not environment hooks.
    try:
        sh(
            [sys.executable, "-S", "-u", "-c", "import sys, time; print('stdout'); print('stderr', file=sys.stderr); time.sleep(5)"],
            root,
            timeout=2.0,
        )
    except RuntimeError as exc:
        diagnostic = str(exc)
        check(
            "timeout diagnostic identifies command, cwd, timeout, stdout, and stderr",
            all(part in diagnostic for part in ["command:", f"cwd: {root}", "2.0 seconds", "stdout: stdout", "stderr: stderr"]),
            diagnostic,
        )
    else:
        check("timeout diagnostic identifies command, cwd, timeout, stdout, and stderr", False, "timeout did not occur")


# --- runtime cases ------------------------------------------------------------------

def case_init_creates_artifacts(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    for name in ["PRD.md", "PLAN.md", "STATE.yaml", "DECISIONS.md", "PITFALLS.md"]:
        check(f"init creates {name}", (d / name).exists())
    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    check("high risk requires a plan review", doc["plan_review"] == {"required": True, "status": "pending", "audit_file": "audits/plan.md"}, repr(doc.get("plan_review")))


def case_domain_must_stay_inside_domains_root(root: Path) -> None:
    def cli(*args: str) -> subprocess.CompletedProcess:
        return sh([sys.executable, str(CLI), *args], root)

    external = root.parent / f"devflow-escape-{root.name}"
    shutil.rmtree(external, ignore_errors=True)
    deep = cli("init", str(Path("..") / ".." / ".." / external.name))
    check(
        "AC-01: init rejects a domain that resolves outside the repository and creates nothing there",
        deep.returncode == 2 and "domains_root" in deep.stderr and not external.exists(),
        deep.stdout + deep.stderr,
    )

    single = cli("init", "../escaped")
    check(
        "AC-02: init rejects a single-.. domain that stays in the repo but leaves domains_root",
        single.returncode == 2 and "domains_root" in single.stderr and not (root / "docs/escaped").exists(),
        single.stdout + single.stderr,
    )

    status_escape = cli("status", "../escaped")
    check(
        "AC-03: status rejects an escaping domain with the same class of message",
        status_escape.returncode == 2 and "domains_root" in status_escape.stderr,
        status_escape.stdout + status_escape.stderr,
    )

    flat = cli("init", "billing")
    nested = cli("init", "team/billing")
    check(
        "AC-04: a flat domain and a nested domain that stay inside domains_root still initialize",
        flat.returncode == 0
        and nested.returncode == 0
        and (root / "docs/domains/billing/STATE.yaml").exists()
        and (root / "docs/domains/team/billing/STATE.yaml").exists(),
        flat.stdout + flat.stderr + nested.stdout + nested.stderr,
    )

    config_path = root / ".devflow/config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["domains_root"] = "areas/devflow"
    dump(config_path, config)
    custom_ok = cli("init", "shipping")
    custom_escape = cli("init", "../../secret")
    check(
        "AC-05: a custom domains_root still admits a contained domain and still rejects an escaping one",
        custom_ok.returncode == 0
        and (root / "areas/devflow/shipping/STATE.yaml").exists()
        and custom_escape.returncode == 2
        and "areas/devflow" in custom_escape.stderr
        and not (root / "areas/secret").exists(),
        custom_ok.stdout + custom_ok.stderr + custom_escape.stdout + custom_escape.stderr,
    )
    shutil.rmtree(external, ignore_errors=True)


def case_audit_remediation_init_projects_integration_audit(root: Path) -> None:
    out = devflow(root, "init", "billing", "--risk", "high", "--workflow", "audit-remediation")
    state_file = root / "docs/domains/billing/STATE.yaml"
    state_doc = yaml.safe_load(state_file.read_text()) if state_file.exists() else {}
    check(
        "audit remediation init starts with a phase-free integration initial audit",
        out.returncode == 0
        and state_doc.get("workflow_type") == "audit_remediation"
        and state_doc.get("project_status") == "integration_audit"
        and state_doc.get("phases") == {}
        and state_doc.get("plan_review") == {
            "required": False,
            "status": "skipped",
            "audit_file": "audits/plan.md",
        }
        and (state_doc.get("integration") or {}).get("status") == "audit"
        and state_doc.get("next_action") == {
            "role": "auditor",
            "command": "audit",
            "scope": "integration",
            "mode": "initial",
            "phase": None,
            "work_item": None,
        },
        out.stdout + out.stderr + repr(state_doc),
    )


def case_audit_remediation_init_uses_mode_specific_templates(root: Path) -> None:
    out = devflow(root, "init", "billing", "--workflow", "audit-remediation")
    domain = root / "docs/domains/billing"
    prd = (domain / "PRD.md").read_text() if (domain / "PRD.md").exists() else ""
    plan = (domain / "PLAN.md").read_text() if (domain / "PLAN.md").exists() else ""
    prd_sections = [
        "# Audit Scope Contract",
        "## Audit target",
        "## User-verified flows",
        "## In scope",
        "## Out of scope",
        "## Authoritative requirements and policies",
        "## Success criteria",
        "## Open decisions",
    ]
    plan_sections = [
        "# Audit and Remediation PLAN",
        "## Metadata",
        "## Repository reconnaissance",
        "## Audit axes",
        "## Evidence plan",
        "## Finding disposition strategy",
        "## Remediation topology",
        "## Closure criteria",
    ]
    check(
        "audit remediation init writes the mode-specific PRD and PLAN contracts",
        out.returncode == 0
        and all(section in prd for section in prd_sections)
        and all(section in plan for section in plan_sections),
        out.stdout + out.stderr + prd + plan,
    )


def case_legacy_120_domain_defaults_to_delivery(root: Path) -> None:
    devflow(root, "init", "billing")
    state_file = root / "docs/domains/billing/STATE.yaml"
    legacy = yaml.safe_load(state_file.read_text())
    legacy["protocol_version"] = "1.2.0"
    legacy.pop("workflow_type", None)
    check(
        "legacy 1.2 fixture explicitly uses protocol 1.2.0",
        legacy.get("protocol_version") == "1.2.0",
        repr(legacy.get("protocol_version")),
    )
    dump(state_file, legacy)
    before = state_file.read_text()
    out = devflow(root, "status", "billing", "--json")
    reported = json.loads(out.stdout) if out.returncode == 0 else {}
    check(
        "legacy protocol 1.2.0 STATE reads as delivery without a migration write",
        reported.get("workflow_type") == "delivery"
        and (reported.get("protocol_versions") or {}).get("state") == "1.2.0"
        and state_file.read_text() == before,
        out.stdout + out.stderr + state_file.read_text(),
    )

    for version in ["1.0.0", "1.1.0"]:
        legacy["protocol_version"] = version
        dump(state_file, legacy)
        before = state_file.read_text()
        out = devflow(root, "status", "billing", "--json")
        reported = json.loads(out.stdout) if out.returncode == 0 else {}
        check(
            f"legacy protocol {version} STATE reads as delivery without a migration write",
            out.returncode == 0
            and reported.get("workflow_type") == "delivery"
            and (reported.get("protocol_versions") or {}).get("state") == version
            and state_file.read_text() == before,
            out.stdout + out.stderr + state_file.read_text(),
        )


def case_init_reports_runtime_and_domain_paths(root: Path) -> None:
    out = devflow(root, "init", "billing")
    check(
        "init reports workflow, runtime config, domains root, and domain directory",
        out.returncode == 0
        and all(
            line in out.stdout
            for line in [
                "workflow_type: delivery",
                "runtime_config: .devflow/config.yaml",
                "domains_root: docs/domains",
                "domain_dir: docs/domains/billing",
            ]
        ),
        out.stdout + out.stderr,
    )


def case_status_reports_workflow_and_domain_paths(root: Path) -> None:
    devflow(root, "init", "billing")
    out = devflow(root, "status", "billing")
    check(
        "status reports workflow, runtime config, domains root, and domain directory",
        out.returncode == 0
        and all(
            line in out.stdout
            for line in [
                "workflow_type: delivery",
                "runtime_config: .devflow/config.yaml",
                "domains_root: docs/domains",
                "domain_dir: docs/domains/billing",
            ]
        ),
        out.stdout + out.stderr,
    )


def case_delivery_render_rejects_out_of_sequence_integration_audit(root: Path) -> None:
    broken_delivery_fixture(root)
    out = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "delivery render rejects an integration audit while plan review is pending",
        out.returncode == 2
        and not out.stdout
        and all(token in out.stderr for token in ["requested", "expected", "devflow status billing"]),
        out.stdout + out.stderr,
    )


def case_render_run_rejects_non_next_work_item(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01"), item("P01-I02")))

    out = devflow(root, "render", "run", "billing", "--task", "P01-I02")
    check(
        "render run accepts only the computed next WORK item",
        out.returncode == 2
        and not out.stdout
        and all(token in out.stderr for token in ["requested", "expected", "P01-I01", "P01-I02", "devflow status billing"]),
        out.stdout + out.stderr,
    )


def case_render_audit_requires_exact_scope_mode_and_target(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", high_done("P01-I01"), item("P01-I02")))

    requests = [
        ("wrong scope", ["--scope", "phase", "--phase", "01"]),
        ("wrong mode", ["--scope", "work", "--task", "P01-I01", "--mode", "closure"]),
        ("wrong phase", ["--scope", "work", "--task", "P01-I01", "--phase", "02"]),
        ("wrong WORK", ["--scope", "work", "--task", "P01-I02"]),
    ]
    for label, request in requests:
        out = devflow(root, "render", "audit", "billing", *request)
        check(
            f"render audit rejects {label}",
            out.returncode == 2
            and not out.stdout
            and all(token in out.stderr for token in ["requested", "expected", "devflow status billing"]),
            out.stdout + out.stderr,
        )

    out = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01")
    check(
        "render audit accepts the exact computed scope, mode, phase, and WORK",
        out.returncode == 0 and "work_item: P01-I01" in out.stdout,
        out.stdout + out.stderr,
    )


def case_audit_remediation_allows_initial_integration_render(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    out = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit remediation allows its initial integration render",
        out.returncode == 0 and "audit_scope: integration" in out.stdout and "audit_mode: initial" in out.stdout,
        out.stdout + out.stderr,
    )


def case_validate_rejects_orphan_phase_manifest(root: Path) -> None:
    broken_delivery_fixture(root)
    out = devflow(root, "validate", "billing")
    check(
        "validate rejects a phase manifest absent from STATE",
        out.returncode != 0 and "orphan" in out.stdout.lower() and "phase-01.yaml" in out.stdout,
        out.stdout + out.stderr,
    )


def case_validate_rejects_phase_document_mismatch(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    mismatched_state = state({"01": {**phase("executing", "01"), "work_file": "work/phase-02.yaml"}})
    dump(d / "STATE.yaml", mismatched_state)
    dump(d / "work/phase-02.yaml", work("02", item("P02-I01")))

    state_mismatch = devflow(root, "validate", "billing")
    check(
        "validate rejects a STATE phase whose work_file names another phase",
        state_mismatch.returncode == 1
        and "Phase 01" in state_mismatch.stdout
        and "work/phase-02.yaml" in state_mismatch.stdout
        and "phase 02" in state_mismatch.stdout,
        state_mismatch.stdout + state_mismatch.stderr,
    )

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    (d / "work/phase-02.yaml").unlink()
    dump(d / "work/phase-01.yaml", work("02", item("P01-I01")))
    document_mismatch = devflow(root, "validate", "billing")
    check(
        "validate rejects a WORK document phase that differs from its filename and STATE phase",
        document_mismatch.returncode == 1
        and "phase-01.yaml" in document_mismatch.stdout
        and "declares phase 02" in document_mismatch.stdout
        and "STATE phase 01" in document_mismatch.stdout,
        document_mismatch.stdout + document_mismatch.stderr,
    )


def case_validate_rejects_placeholder_delivery_contract_before_execution(root: Path) -> None:
    broken_delivery_fixture(root)
    out = devflow(root, "validate", "billing")
    check(
        "validate rejects placeholder delivery PRD and PLAN before execution",
        out.returncode != 0 and "placeholder" in out.stdout.lower() and "PRD.md" in out.stdout and "PLAN.md" in out.stdout,
        out.stdout + out.stderr,
    )


def case_render_guard_does_not_mutate_artifacts(root: Path) -> None:
    d = broken_delivery_fixture(root)
    before = {str(path.relative_to(d)): None if path.is_dir() else path.read_bytes() for path in d.rglob("*")}
    out = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): None if path.is_dir() else path.read_bytes() for path in d.rglob("*")}
    check(
        "rejected render leaves domain artifacts unchanged",
        out.returncode == 2 and before == after,
        f"returncode={out.returncode}\nartifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", high_done("P01-I01")))
    devflow(root, "status", "billing")
    before = {str(path.relative_to(d)): None if path.is_dir() else path.read_bytes() for path in d.rglob("*")}
    out = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01")
    after = {str(path.relative_to(d)): None if path.is_dir() else path.read_bytes() for path in d.rglob("*")}
    check(
        "accepted render leaves stable domain artifacts unchanged",
        out.returncode == 0 and before == after and not (d / "audits/work").exists(),
        f"returncode={out.returncode}\nartifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_audit_apply_rejects_missing_front_matter(root: Path) -> None:
    d = audit_remediation_fixture(root)
    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply requires the canonical audit file",
        out.returncode == 2 and "canonical audit file" in out.stderr.lower(),
        out.stdout + out.stderr,
    )

    (d / "audits/integration.md").write_text("# Audit without metadata\n", encoding="utf-8")

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects a Markdown audit without front matter",
        out.returncode == 2 and "front matter" in out.stderr.lower(),
        out.stdout + out.stderr,
    )


def case_audit_apply_rejects_malformed_front_matter(root: Path) -> None:
    d = audit_remediation_fixture(root)
    (d / "audits/integration.md").write_text("---\nschema: [\n---\n# Audit\n", encoding="utf-8")

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply reports malformed YAML as a clean error",
        out.returncode == 2 and "yaml" in out.stderr.lower() and "traceback" not in out.stderr.lower(),
        out.stdout + out.stderr,
    )

    (d / "audits/integration.md").write_text("---\n- not\n- a mapping\n---\n# Audit\n", encoding="utf-8")
    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects a non-mapping front matter document",
        out.returncode == 2 and "must be a mapping" in out.stderr,
        out.stdout + out.stderr,
    )

    blank = audit_metadata(d, verification=[{"command": " ", "result": "passed"}])
    write_audit(d / "audits/integration.md", blank)
    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects whitespace-only required strings and list entries",
        out.returncode == 2 and "must not be blank" in out.stderr,
        out.stdout + out.stderr,
    )


def case_audit_apply_rejects_duplicate_yaml_keys(root: Path) -> None:
    d = audit_remediation_fixture(root)
    metadata = audit_metadata(d)
    rendered = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True)
    (d / "audits/integration.md").write_text(
        f"---\nschema: devflow-audit-v1\n{rendered}---\n# Audit\n",
        encoding="utf-8",
    )

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects duplicate YAML keys",
        out.returncode == 2 and "duplicate" in out.stderr.lower() and "schema" in out.stderr.lower(),
        out.stdout + out.stderr,
    )


def case_state_and_work_reject_duplicate_yaml_keys(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    good_status = devflow(root, "status", "billing")

    # A hand-edited STATE with a second `phases:` block: safe_load would silently keep the last one.
    state_text = (d / "STATE.yaml").read_text(encoding="utf-8")
    (d / "STATE.yaml").write_text(state_text + "\nphases:\n  99:\n    status: verified\n", encoding="utf-8")
    dup_state = devflow(root, "status", "billing")
    dup_state_validate = devflow(root, "validate", "billing")
    check(
        "a STATE file with a duplicate top-level key is rejected, not silently collapsed",
        good_status.returncode == 0
        and dup_state.returncode == 2
        and "duplicate key" in (dup_state.stdout + dup_state.stderr).lower()
        and dup_state_validate.returncode == 2
        and "duplicate key" in (dup_state_validate.stdout + dup_state_validate.stderr).lower(),
        dup_state.stdout + dup_state.stderr + "\n---\n" + dup_state_validate.stdout + dup_state_validate.stderr,
    )

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    work_text = (d / "work/phase-01.yaml").read_text(encoding="utf-8")
    (d / "work/phase-01.yaml").write_text(work_text + "\nitems:\n- id: SNEAKY\n", encoding="utf-8")
    dup_work = devflow(root, "status", "billing")
    check(
        "a WORK file with a duplicate `items:` key is rejected",
        dup_work.returncode == 2 and "duplicate key" in (dup_work.stdout + dup_work.stderr).lower(),
        dup_work.stdout + dup_work.stderr,
    )


def case_audit_apply_requires_exact_next_action(root: Path) -> None:
    d = audit_remediation_fixture(root)
    write_audit(d / "audits/integration.md", audit_metadata(d))
    before = (d / "STATE.yaml").read_bytes()

    out = devflow(root, "audit", "apply", "billing", "--scope", "plan", "--mode", "initial")
    check(
        "audit apply accepts only the exact computed scope, mode, phase, and WORK",
        out.returncode == 2
        and all(token in out.stderr for token in ["requested", "expected", "devflow status billing"])
        and (d / "STATE.yaml").read_bytes() == before,
        out.stdout + out.stderr,
    )

    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.3.0"
    dump(d / "STATE.yaml", state_doc)
    bypass = devflow(root, "integration", "set", "billing", "verified")
    check(
        "protocol 1.3 verified transitions require audit apply",
        bypass.returncode == 2 and "audit apply" in bypass.stderr,
        bypass.stdout + bypass.stderr,
    )


def case_audit_apply_validates_verdict_against_findings(root: Path) -> None:
    d = audit_remediation_fixture(root)
    blocker = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The defect can corrupt persisted state.",
        disposition={"action": "record_only", "work_ids": [], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="pass", findings=[blocker]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects a pass verdict with a blocker finding",
        out.returncode == 2 and "verdict" in out.stderr.lower() and "blocker" in out.stderr.lower(),
        out.stdout + out.stderr,
    )


def case_audit_apply_validates_finding_links(root: Path) -> None:
    d = audit_remediation_fixture(root)
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The defect can corrupt persisted state.",
        disposition={"action": "remediation_work", "work_ids": ["INT-I404"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="fail", findings=[finding]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects a finding linked to missing WORK",
        out.returncode == 2 and "INT-I404" in out.stderr and "WORK" in out.stderr,
        out.stdout + out.stderr,
    )

    finding["severity"] = "major"
    finding["classification"] = "DECISION_REQUIRED"
    finding["disposition"] = {"action": "decision", "work_ids": [], "decision_ids": ["DEC-404"]}
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects a finding linked to a missing decision record",
        out.returncode == 2 and "DEC-404" in out.stderr and "DECISIONS.md" in out.stderr,
        out.stdout + out.stderr,
    )


def case_multi_finding_work_requires_aggregation_reason(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    combined = item(
        "P01-R01",
        kind="remediation",
        origin={"requirements": [], "findings": ["F-01", "F-02"], "plan_items": []},
    )
    dump(d / "work/phase-01.yaml", work("01", combined))

    out = devflow(root, "validate", "billing")
    check(
        "multi-finding WORK requires an explicit aggregation reason",
        out.returncode == 1 and "origin.aggregation_reason" in out.stdout,
        out.stdout + out.stderr,
    )


def case_multi_finding_work_accepts_coherent_explicit_aggregation(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    combined = item(
        "P01-R01",
        kind="remediation",
        origin={
            "requirements": [],
            "findings": ["F-01", "F-02"],
            "plan_items": [],
            "aggregation_reason": "Both findings share one root cause, change boundary, and verification set.",
        },
    )
    dump(d / "work/phase-01.yaml", work("01", combined))

    out = devflow(root, "validate", "billing")
    check(
        "multi-finding WORK accepts a nonblank explicit aggregation reason",
        out.returncode == 0,
        out.stdout + out.stderr,
    )


def case_audit_work_links_are_bidirectional(root: Path) -> None:
    d = audit_remediation_fixture(root)
    remediation = item(
        "INT-R01",
        kind="remediation",
        origin={"requirements": [], "findings": ["F-02"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", remediation))
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The confirmed defect requires remediation.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))

    rejected = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit finding to WORK link requires the reciprocal WORK origin link",
        rejected.returncode == 2 and "INT-R01" in rejected.stderr and "F-01" in rejected.stderr and "origin.findings" in rejected.stderr,
        rejected.stdout + rejected.stderr,
    )

    remediation["origin"]["findings"] = ["F-01"]
    dump(d / "work/integration.yaml", work("integration", remediation))
    accepted = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "reciprocal audit finding and WORK origin links are accepted",
        accepted.returncode == 0,
        accepted.stdout + accepted.stderr,
    )


def case_decision_finding_cannot_generate_ready_work(root: Path) -> None:
    d = audit_remediation_fixture(root)
    write_open_decision(d / "DECISIONS.md", "DEC-001")
    decision_work = item(
        "INT-I01",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
        decision_dependencies=["DEC-001"],
    )
    dump(d / "work/integration.yaml", work("integration", decision_work))
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-001"]},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "decision-required finding cannot generate ready WORK",
        out.returncode == 2 and "DECISION_REQUIRED" in out.stderr and "INT-I01" in out.stderr and "ready" in out.stderr,
        out.stdout + out.stderr,
    )


def case_decision_finding_requires_decision_id(root: Path) -> None:
    d = audit_remediation_fixture(root)
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "decision-required finding requires a decision id",
        out.returncode == 2 and "DECISION_REQUIRED" in out.stderr and "decision_ids" in out.stderr,
        out.stdout + out.stderr,
    )


def case_evidence_finding_requires_evidence_work(root: Path) -> None:
    d = audit_remediation_fixture(root)
    wrong_kind = item(
        "INT-E01",
        kind="remediation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", wrong_kind))
    finding = audit_finding(
        "F-01",
        classification="EVIDENCE_REQUIRED",
        severity="major",
        severity_reason="Repository evidence is incomplete.",
        disposition={"action": "evidence_work", "work_ids": ["INT-E01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "evidence-required finding requires evidence WORK",
        out.returncode == 2 and "INT-E01" in out.stderr and "kind evidence" in out.stderr,
        out.stdout + out.stderr,
    )


def case_documentation_drift_requires_documentation_work(root: Path) -> None:
    d = audit_remediation_fixture(root)
    wrong_kind = item(
        "INT-D01",
        kind="remediation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", wrong_kind))
    finding = audit_finding(
        "F-01",
        classification="DOCUMENTATION_DRIFT",
        severity="major",
        severity_reason="Current documentation contradicts verified behavior.",
        disposition={"action": "documentation_work", "work_ids": ["INT-D01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "documentation drift requires documentation WORK",
        out.returncode == 2 and "INT-D01" in out.stderr and "kind documentation" in out.stderr,
        out.stdout + out.stderr,
    )


def case_work_cannot_reference_unknown_audit_finding(root: Path) -> None:
    d = audit_remediation_fixture(root)
    remediation = item(
        "INT-R01",
        kind="remediation",
        origin={
            "requirements": [],
            "findings": ["F-01", "F-404"],
            "plan_items": [],
            "aggregation_reason": "The two finding IDs are claimed to share one remediation boundary.",
        },
    )
    dump(d / "work/integration.yaml", work("integration", remediation))
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The confirmed defect requires remediation.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "WORK cannot reference a finding absent from its audit",
        out.returncode == 2 and "INT-R01" in out.stderr and "F-404" in out.stderr and "absent from audit" in out.stderr,
        out.stdout + out.stderr,
    )


def case_unlinked_work_cannot_reference_unknown_audit_finding(root: Path) -> None:
    d = audit_remediation_fixture(root)
    unlinked = item(
        "INT-R404",
        kind="remediation",
        status="cancelled",
        origin={"requirements": [], "findings": ["F-404"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", unlinked))
    write_audit(d / "audits/integration.md", audit_metadata(d))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "unlinked terminal WORK cannot reference a finding absent from its audit",
        out.returncode == 2
        and "INT-R404" in out.stderr
        and "F-404" in out.stderr
        and "absent from audit" in out.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_decision_apply_requires_actual_nonblank_options(root: Path) -> None:
    d = audit_remediation_fixture(root)
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-001"]},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "decision apply rejects the DECISIONS template placeholder and blank options",
        out.returncode == 2
        and "DEC-001" in out.stderr
        and "DECISIONS.md" in out.stderr
        and "option" in out.stderr.lower()
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_decisions_state_and_work_dependencies_are_bidirectional(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", decision_dependencies=["DEC-001"])))
    write_open_decision(d / "DECISIONS.md", "DEC-001")
    work_before = (d / "work/phase-01.yaml").read_bytes()

    validated = devflow(root, "validate", "billing")
    started = devflow(root, "work", "start", "billing", "A")
    check(
        "open DECISIONS records must be registered in STATE before validation or WORK start",
        validated.returncode == 1
        and "DEC-001" in validated.stdout
        and "unresolved_decisions" in validated.stdout
        and started.returncode == 2
        and "DEC-001" in started.stderr
        and (d / "work/phase-01.yaml").read_bytes() == work_before,
        validated.stdout + validated.stderr + started.stdout + started.stderr,
    )

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, unresolved_decisions=["DEC-404"]))
    (d / "DECISIONS.md").unlink()
    validated = devflow(root, "validate", "billing")
    check(
        "STATE unresolved decisions require matching structured DECISIONS records",
        validated.returncode == 1
        and "DEC-404" in validated.stdout
        and "DECISIONS.md" in validated.stdout,
        validated.stdout + validated.stderr,
    )


def case_work_audit_rejects_unlinked_unknown_findings_in_same_manifest(root: Path) -> None:
    d = audit_remediation_fixture(root)
    parent_finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The parent integration audit found a defect.",
        disposition={"action": "remediation_work", "work_ids": ["INT-TARGET"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[parent_finding]))
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "remediation"
    dump(d / "STATE.yaml", state_doc)

    target = high_done(
        "INT-TARGET",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    known_parent = item(
        "INT-KNOWN",
        kind="remediation",
        status="cancelled",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    unknown_done = item(
        "INT-UNKNOWN-DONE",
        kind="remediation",
        status="done",
        commands=["true -> passed"],
        origin={"requirements": [], "findings": ["F-404"], "plan_items": []},
    )
    unknown_transferred = item(
        "INT-UNKNOWN-TRANSFERRED",
        kind="remediation",
        status="transferred",
        transfer={"to": "INT-TARGET", "requirements": []},
        origin={"requirements": [], "findings": ["F-404"], "plan_items": []},
    )
    unknown_cancelled = item(
        "INT-UNKNOWN-CANCELLED",
        kind="remediation",
        status="cancelled",
        origin={"requirements": [], "findings": ["F-404"], "plan_items": []},
    )
    dump(
        d / "work/integration.yaml",
        work("integration", target, known_parent, unknown_done, unknown_transferred, unknown_cancelled),
    )
    projected = devflow(root, "status", "billing")
    current_finding = audit_finding("F-W01")
    write_audit(d / "audits/work/INT-TARGET.md", audit_metadata(d, scope="work", findings=[current_finding]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "INT-TARGET", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "work audit rejects unlinked terminal WORK findings absent from canonical audits",
        projected.returncode == 0
        and out.returncode == 2
        and all(work_id in out.stderr for work_id in ["INT-UNKNOWN-DONE", "INT-UNKNOWN-TRANSFERRED", "INT-UNKNOWN-CANCELLED"])
        and "F-404" in out.stderr
        and "F-01" not in out.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{projected.stdout}{projected.stderr}{out.stdout}{out.stderr}",
    )


def case_decision_record_stops_at_next_markdown_heading(root: Path) -> None:
    d = audit_remediation_fixture(root)
    (d / "DECISIONS.md").write_text(
        "# Decisions\n\n"
        "## Open\n\n"
        "### DEC-301 Retention policy\n"
        "- Trigger: An audit found an unresolved policy.\n\n"
        "### Notes\n"
        "- Option A: Retain records for 30 days.\n"
        "- Option B: Delete records immediately.\n\n"
        "## Resolved\n",
        encoding="utf-8",
    )
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-301"]},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "decision options after the next Markdown heading do not belong to the prior record",
        out.returncode == 2
        and "DEC-301" in out.stderr
        and "option" in out.stderr.lower()
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_decision_placeholder_options_are_invalid(root: Path) -> None:
    d = audit_remediation_fixture(root)
    initial_state = (d / "STATE.yaml").read_bytes()
    (d / "DECISIONS.md").write_text(
        "# Decisions\n\n"
        "## Open\n\n"
        "### DEC-302 Retention policy\n"
        "- Trigger: An audit found an unresolved policy.\n"
        "- Option A: TBD\n"
        "- Option B: TODO\n\n"
        "## Resolved\n",
        encoding="utf-8",
    )
    state_doc = yaml.safe_load(initial_state)
    state_doc["unresolved_decisions"] = ["DEC-302"]
    dump(d / "STATE.yaml", state_doc)
    before_validate = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    validated = devflow(root, "validate", "billing")
    after_validate = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "validate rejects TBD and TODO as decision options without changing files",
        validated.returncode == 1
        and "DEC-302" in validated.stdout
        and "option" in validated.stdout.lower()
        and before_validate == after_validate,
        f"artifacts_unchanged={before_validate == after_validate}\n{validated.stdout}{validated.stderr}",
    )

    (d / "STATE.yaml").write_bytes(initial_state)
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-302"]},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    before_apply = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after_apply = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "audit apply rejects placeholder decision options without changing files",
        applied.returncode == 2
        and "DEC-302" in applied.stderr
        and "option" in applied.stderr.lower()
        and before_apply == after_apply,
        f"artifacts_unchanged={before_apply == after_apply}\n{applied.stdout}{applied.stderr}",
    )


def case_malformed_canonical_audit_cannot_authenticate_finding(root: Path) -> None:
    d = audit_remediation_fixture(root)
    valid_parent = audit_finding("F-01")
    write_audit(d / "audits/plan.md", audit_metadata(d, scope="plan", findings=[valid_parent]))
    malformed = {"findings": [{"id": "F-404"}]}
    write_audit(d / "audits/integration.md", malformed)

    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "remediation"
    dump(d / "STATE.yaml", state_doc)
    target = high_done(
        "INT-TARGET",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    known_parent = item(
        "INT-KNOWN",
        kind="remediation",
        status="cancelled",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    malformed_only = item(
        "INT-MALFORMED-ONLY",
        kind="remediation",
        status="cancelled",
        origin={"requirements": [], "findings": ["F-404"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", target, known_parent, malformed_only))
    projected = devflow(root, "status", "billing")
    write_audit(d / "audits/work/INT-TARGET.md", audit_metadata(d, scope="work", findings=[audit_finding("F-W01")]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "INT-TARGET", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "schema-invalid canonical audit findings cannot authenticate WORK origins",
        projected.returncode == 0
        and out.returncode == 2
        and "INT-MALFORMED-ONLY" in out.stderr
        and "F-404" in out.stderr
        and "F-01" not in out.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{projected.stdout}{projected.stderr}{out.stdout}{out.stderr}",
    )


def case_decision_commonmark_indented_heading_boundary(root: Path) -> None:
    d = audit_remediation_fixture(root)
    initial_state = (d / "STATE.yaml").read_bytes()
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-303"]},
    )
    results = []
    for spaces in [1, 2, 3]:
        (d / "STATE.yaml").write_bytes(initial_state)
        (d / "DECISIONS.md").write_text(
            "# Decisions\n\n"
            "## Open\n\n"
            "### DEC-303 Retention policy\n"
            "- Trigger: An audit found an unresolved policy.\n\n"
            f"{' ' * spaces}### Notes\n"
            "- Option A: Retain records for 30 days.\n"
            "- Option B: Delete records immediately.\n\n"
            "## Resolved\n",
            encoding="utf-8",
        )
        write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
        before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
        after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        results.append((spaces, out, before == after))

    (d / "STATE.yaml").write_bytes(initial_state)
    (d / "DECISIONS.md").write_text(
        "# Decisions\n\n"
        "## Open\n\n"
        "### DEC-303 Retention policy\n"
        "- Trigger: An audit found an unresolved policy.\n\n"
        "    ### Notes\n"
        "- Option A: Retain records for 30 days.\n"
        "- Option B: Delete records immediately.\n\n"
        "## Resolved\n",
        encoding="utf-8",
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    code_block = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "CommonMark ATX headings with up to three leading spaces end decision records",
        all(
            out.returncode == 2
            and "DEC-303" in out.stderr
            and "option" in out.stderr.lower()
            and unchanged
            for _, out, unchanged in results
        )
        and code_block.returncode == 0,
        "\n".join(
            f"spaces={spaces} artifacts_unchanged={unchanged}\n{out.stdout}{out.stderr}"
            for spaces, out, unchanged in results
        )
        + f"\nspaces=4\n{code_block.stdout}{code_block.stderr}",
    )


def case_audit_apply_failure_is_atomic(root: Path) -> None:
    d = audit_remediation_fixture(root)
    dump(d / "work/integration.yaml", work("integration", item("INT-I01")))
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product policy choice is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-404"]},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    before = {str(path.relative_to(d)): None if path.is_dir() else path.read_bytes() for path in d.rglob("*")}

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): None if path.is_dir() else path.read_bytes() for path in d.rglob("*")}
    check(
        "failed audit apply leaves STATE, WORK, DECISIONS, and audit artifacts byte-identical",
        out.returncode == 2 and before == after and "DEC-404" in out.stderr,
        f"returncode={out.returncode}\nartifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_audit_apply_updates_state_and_next_action(root: Path) -> None:
    d = audit_remediation_fixture(root)
    write_audit(d / "audits/integration.md", audit_metadata(d))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "valid audit apply atomically verifies integration and derives completion",
        out.returncode == 0
        and state_doc["integration"]["status"] == "verified"
        and state_doc["project_status"] == "complete"
        and state_doc["next_action"] == {
            "role": "none",
            "command": "complete",
            "scope": "project",
            "phase": None,
            "work_item": None,
        }
        and all(token in out.stdout for token in ["verdict: pass", "findings: 0", "next_action: complete"]),
        out.stdout + out.stderr + repr(state_doc),
    )


def case_delivery_integration_still_requires_verified_phases(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({}, integration="verified", workflow_type="delivery"))
    (d / "audits/integration.md").write_text("# Legacy integration audit\n", encoding="utf-8")

    no_phases = devflow(root, "validate", "billing")
    check(
        "delivery integration verification still requires at least one real phase",
        no_phases.returncode == 1 and "integration is verified but delivery has no phases" in no_phases.stdout,
        no_phases.stdout + no_phases.stderr,
    )

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, integration="verified", workflow_type="delivery"))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> passed"])))
    unverified = devflow(root, "validate", "billing")
    check(
        "delivery integration verification still requires every phase to be verified",
        unverified.returncode == 1 and "integration is verified but phases are not: 01" in unverified.stdout,
        unverified.stdout + unverified.stderr,
    )


def case_audit_remediation_verifies_without_fake_phases(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    write_audit(d / "audits/integration.md", audit_metadata(d))
    empty_contract = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit remediation apply rejects empty scope and strategy sections",
        empty_contract.returncode == 2
        and "PRD.md" in empty_contract.stderr
        and "PLAN.md" in empty_contract.stderr
        and "required section" in empty_contract.stderr,
        empty_contract.stdout + empty_contract.stderr,
    )

    fill_audit_remediation_contract(d)
    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    validated = devflow(root, "validate", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    phase_files = list((d / "work").glob("phase-*.yaml"))
    check(
        "audit remediation reaches verified complete without fake phases",
        applied.returncode == 0
        and validated.returncode == 0
        and state_doc["phases"] == {}
        and state_doc["integration"]["status"] == "verified"
        and state_doc["project_status"] == "complete"
        and not phase_files,
        applied.stdout + applied.stderr + validated.stdout + validated.stderr + repr(state_doc),
    )


def case_validate_rejects_applied_audit_lifecycle_mismatch(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.3.0"
    state_doc["integration"]["status"] = "verified"
    dump(d / "STATE.yaml", state_doc)
    write_audit(d / "audits/integration.md", audit_metadata(d))

    out = devflow(root, "validate", "billing")
    check(
        "validate rejects an applied integration audit while plan review is pending",
        out.returncode == 1
        and "plan review is pending" in out.stdout
        and "integration status verified" in out.stdout,
        out.stdout + out.stderr,
    )


def case_validate_rechecks_verified_audit_verdict_rubric(root: Path) -> None:
    d = audit_remediation_fixture(root)
    state_path = d / "STATE.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.3.0"
    state_doc["integration"]["status"] = "verified"
    dump(state_path, state_doc)
    blocker = audit_finding(
        "F-01",
        severity="blocker",
        severity_reason="A concrete production failure remains active.",
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="pass", findings=[blocker]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "validate", "billing")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "validate reapplies the audit verdict rubric to verified protocol 1.3 evidence",
        out.returncode == 1
        and "verdict pass forbids finding severity: blocker" in out.stdout
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_validate_rejects_canonical_audit_path_collision(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    state_path = d / "STATE.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["plan_review"]["audit_file"] = "audits/shared.md"
    state_doc["integration"]["audit_file"] = "audits/shared.md"
    dump(state_path, state_doc)
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "validate", "billing")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "validate rejects one canonical audit path assigned to distinct lifecycle targets",
        out.returncode == 1
        and "canonical audit path collision" in out.stdout
        and "plan" in out.stdout
        and "integration" in out.stdout
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_delivery_placeholder_contract_requires_trusted_sections(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    (d / "PRD.md").write_text(
        "# Billing PRD\n\n"
        "## 4. Requirements\n\n"
        "### REQ-001 Billing behavior\n"
        "- Requirement:\n"
        "- Acceptance criteria:\n\n"
        "## 5. Notes\n"
        "- Requirement: This later section must not satisfy REQ-001.\n"
        "- Acceptance criteria: This later section must not satisfy REQ-001.\n",
        encoding="utf-8",
    )
    (d / "PLAN.md").write_text(
        "# Implementation PLAN\n\n"
        "## Metadata\n"
        "- Domain: billing\n"
        "- Baseline SHA: HEAD\n"
        "- Risk profile: medium\n",
        encoding="utf-8",
    )
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    out = devflow(root, "validate", "billing")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "delivery WORK requires nonblank requirement and acceptance bodies plus trusted PLAN sections",
        out.returncode == 1
        and "Requirement" in out.stdout
        and "Acceptance criteria" in out.stdout
        and "Phase graph" in out.stdout
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )

    fake_plugin = root / "fake-plugin-delivery-sections"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    plan_template = fake_plugin / "core/templates/PLAN.md"
    plan_template.write_text(
        plan_template.read_text(encoding="utf-8").replace("## Phase graph\n", ""),
        encoding="utf-8",
    )
    runtime = load_runtime_module()
    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        tampered = invoke_runtime(root, runtime, "validate", "billing")
    check(
        "delivery section trust anchor rejects a template and artifact missing the same required heading",
        tampered.returncode == 1
        and "template" in tampered.stdout.lower()
        and "Phase graph" in tampered.stdout,
        tampered.stdout + tampered.stderr,
    )


def case_audit_remediation_required_sections_survive_template_tampering(root: Path) -> None:
    d = audit_remediation_fixture(root)
    fake_plugin = root / "fake-plugin-audit-sections"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    prd_template = fake_plugin / "core/templates/PRD.audit-remediation.md"
    plan_template = fake_plugin / "core/templates/PLAN.audit-remediation.md"
    prd_template.write_text(
        prd_template.read_text(encoding="utf-8").replace("## In scope\n\n", ""),
        encoding="utf-8",
    )
    plan_template.write_text(
        plan_template.read_text(encoding="utf-8").replace("## Finding disposition strategy\n\n", ""),
        encoding="utf-8",
    )
    prd_path = d / "PRD.md"
    plan_path = d / "PLAN.md"
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8").replace("## In scope\nBilling runtime.\n\n", ""),
        encoding="utf-8",
    )
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "## Finding disposition strategy\nClassify every finding.\n\n",
            "",
        ),
        encoding="utf-8",
    )
    write_audit(d / "audits/integration.md", audit_metadata(d))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    runtime = load_runtime_module()

    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "audit remediation section trust anchors survive simultaneous template and artifact deletion",
        out.returncode == 2
        and "In scope" in out.stderr
        and "Finding disposition strategy" in out.stderr
        and "template" in out.stderr.lower()
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_validate_closure_reuses_apply_finding_coverage(root: Path) -> None:
    d = audit_remediation_fixture(root)
    state_path = d / "STATE.yaml"
    prior = audit_finding(
        "F-01",
        severity="blocker",
        severity_reason="The prior production failure remains concrete.",
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="fail", findings=[prior]))

    def validate_closure(
        status: str,
        verdict: str,
        findings: list[dict[str, Any]],
        closure: list[dict[str, Any]],
    ) -> tuple[subprocess.CompletedProcess, bool]:
        state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        state_doc["integration"]["status"] = status
        state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": "blocker"}}
        dump(state_path, state_doc)
        write_audit(
            d / "audits/integration.md",
            audit_metadata(d, mode="closure", verdict=verdict, findings=findings, closure=closure),
        )
        before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        out = devflow(root, "validate", "billing")
        after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        return out, before == after

    missing, unchanged = validate_closure(
        "verified",
        "pass",
        [],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["still failing"], "reopened_as": []}],
    )
    check(
        "canonical closure rejects a prior still-open finding omitted from current metadata",
        missing.returncode == 1
        and "closure omits prior findings from current metadata: F-01" in missing.stdout
        and unchanged,
        f"artifacts_unchanged={unchanged}\n{missing.stdout}{missing.stderr}",
    )

    resolved, unchanged = validate_closure(
        "verified",
        "pass",
        [prior],
        [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["fixed"], "reopened_as": []}],
    )
    check(
        "canonical closure permits a covered resolved blocker with a pass verdict",
        resolved.returncode == 0 and unchanged,
        f"artifacts_unchanged={unchanged}\n{resolved.stdout}{resolved.stderr}",
    )

    still_open, unchanged = validate_closure(
        "closure",
        "fail",
        [prior],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["still failing"], "reopened_as": []}],
    )
    check(
        "canonical closure preserves a covered still-open blocker as active",
        still_open.returncode == 0 and unchanged,
        f"artifacts_unchanged={unchanged}\n{still_open.stdout}{still_open.stderr}",
    )

    current = audit_finding(
        "F-02",
        severity="blocker",
        severity_reason="A new production failure was found during closure.",
    )
    current_only, unchanged = validate_closure(
        "closure",
        "fail",
        [prior, current],
        [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["fixed"], "reopened_as": []}],
    )
    check(
        "canonical closure preserves a current-only blocker as active",
        current_only.returncode == 0 and unchanged,
        f"artifacts_unchanged={unchanged}\n{current_only.stdout}{current_only.stderr}",
    )


def case_closure_cannot_lower_a_recorded_finding_severity(root: Path) -> None:
    d = audit_remediation_fixture(root)
    state_path = d / "STATE.yaml"
    devflow(root, "status", "billing")

    def run_closure(
        recorded_severity: str,
        findings: list[dict[str, Any]],
        closure: list[dict[str, Any]],
        verdict: str,
        *,
        via_validate: bool = False,
    ) -> tuple[subprocess.CompletedProcess, bool]:
        state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        state_doc["integration"]["status"] = "closure"
        state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": recorded_severity}}
        dump(state_path, state_doc)
        write_audit(
            d / "audits/integration.md",
            audit_metadata(d, mode="closure", verdict=verdict, findings=findings, closure=closure),
        )
        before_state = state_path.read_bytes()
        before_work = (d / "work/integration.yaml").read_bytes() if (d / "work/integration.yaml").exists() else b""
        out = devflow(root, "validate", "billing") if via_validate else devflow(
            root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure"
        )
        after_state = state_path.read_bytes()
        after_work = (d / "work/integration.yaml").read_bytes() if (d / "work/integration.yaml").exists() else b""
        return out, before_state == after_state and before_work == after_work

    def finding(fid: str, severity: str) -> dict[str, Any]:
        return audit_finding(fid, severity=severity, severity_reason=f"{fid} severity is {severity} by evidence.")

    still_open_low, unchanged = run_closure(
        "blocker",
        [finding("F-01", "nit")],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["not fixed"], "reopened_as": []}],
        "pass",
    )
    check(
        "AC-01: a still_open finding cannot drop below its recorded severity",
        still_open_low.returncode == 2
        and "closure F-01: still_open severity nit is lower than the recorded severity blocker" in still_open_low.stderr
        and unchanged,
        still_open_low.stdout + still_open_low.stderr + f" unchanged={unchanged}",
    )

    reopened_low, unchanged = run_closure(
        "blocker",
        [finding("F-01", "blocker"), finding("F-02", "nit")],
        [{"finding_id": "F-01", "outcome": "reopened", "evidence": ["still fails"], "reopened_as": ["F-02"]}],
        "pass",
    )
    check(
        "AC-02: a reopened target cannot drop below the reopened finding's recorded severity",
        reopened_low.returncode == 2
        and "closure F-01: reopened finding F-02 severity nit is lower than the recorded severity blocker" in reopened_low.stderr
        and unchanged,
        reopened_low.stdout + reopened_low.stderr + f" unchanged={unchanged}",
    )

    still_open_same_fail, unchanged = run_closure(
        "blocker",
        [finding("F-01", "blocker")],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["not fixed"], "reopened_as": []}],
        "fail",
    )
    final = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    check(
        "AC-03: a still_open blocker at its recorded severity applies and leaves the scope unverified",
        still_open_same_fail.returncode == 0 and final["integration"]["status"] != "verified",
        still_open_same_fail.stdout + still_open_same_fail.stderr + repr(final),
    )

    still_open_minor, _ = run_closure(
        "minor",
        [finding("F-01", "minor")],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["accepted"], "reopened_as": []}],
        "pass",
    )
    closed = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    check(
        "AC-04: a still_open minor recorded as minor still closes the scope",
        still_open_minor.returncode == 0 and closed["integration"]["status"] == "verified",
        still_open_minor.stdout + still_open_minor.stderr + repr(closed),
    )

    devflow(root, "status", "billing")
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
    dump(state_path, state_doc)
    raised, _ = run_closure(
        "minor",
        [finding("F-01", "blocker")],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["worse than thought"], "reopened_as": []}],
        "fail",
    )
    check(
        "AC-05: raising a still_open finding above its recorded severity is accepted and needs a fail verdict",
        raised.returncode == 0,
        raised.stdout + raised.stderr,
    )
    raised_wrong_verdict, _ = run_closure(
        "minor",
        [finding("F-01", "blocker")],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["worse than thought"], "reopened_as": []}],
        "pass",
    )
    check(
        "AC-05: the raised still_open blocker is still forced through the verdict rubric",
        raised_wrong_verdict.returncode == 2 and "verdict pass forbids finding severity: blocker" in raised_wrong_verdict.stderr,
        raised_wrong_verdict.stdout + raised_wrong_verdict.stderr,
    )

    resolved_low, _ = run_closure(
        "blocker",
        [finding("F-01", "nit")],
        [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["fixed"], "reopened_as": []}],
        "pass",
    )
    check(
        "AC-06: a resolved finding is not active, so its severity may be re-evaluated downward",
        resolved_low.returncode == 0,
        resolved_low.stdout + resolved_low.stderr,
    )

    on_disk, unchanged = run_closure(
        "blocker",
        [finding("F-01", "nit")],
        [{"finding_id": "F-01", "outcome": "still_open", "evidence": ["not fixed"], "reopened_as": []}],
        "pass",
        via_validate=True,
    )
    check(
        "AC-08: devflow validate reports the same severity floor error for an on-disk closure audit",
        on_disk.returncode == 1
        and "closure F-01: still_open severity nit is lower than the recorded severity blocker" in on_disk.stdout
        and unchanged,
        on_disk.stdout + on_disk.stderr + f" unchanged={unchanged}",
    )


def case_delivery_markdown_sections_follow_commonmark_boundaries(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    def validate_unchanged() -> tuple[subprocess.CompletedProcess, bool]:
        before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        out = devflow(root, "validate", "billing")
        after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        return out, before == after

    valid_prd = (
        "# Billing PRD\n\n"
        "   ## 4. Requirements\n\n"
        "  ### REQ-001 Billing behavior\n"
        "- Requirement: Preserve billing behavior.\n"
        "- Acceptance criteria:\n"
        "  - AC-001: The behavior is verified.\n"
    )
    valid_plan = (
        "# Implementation PLAN\n\n"
        "## Metadata\n- Domain: billing\n- Baseline SHA: HEAD\n- Risk profile: medium\n\n"
        " ## Repository findings\n- Existing runtime inspected.\n\n"
        "  ## Architecture / implementation strategy\n* Reuse the runtime boundary.\n\n"
        "   ## Requirement traceability\n+ REQ-001 maps to Phase 01.\n\n"
        "## Phase graph\n- Phase 01 implements REQ-001.\n\n"
        "   ## Verification strategy\n- Run the targeted suite.\n"
    )
    (d / "PRD.md").write_text(valid_prd, encoding="utf-8")
    (d / "PLAN.md").write_text(valid_plan, encoding="utf-8")
    accepted, unchanged = validate_unchanged()
    check(
        "delivery accepts CommonMark ATX headings with zero through three leading spaces",
        accepted.returncode == 0 and unchanged,
        f"artifacts_unchanged={unchanged}\n{accepted.stdout}{accepted.stderr}",
    )

    (d / "PLAN.md").write_text(valid_plan.replace("## Phase graph", "    ## Phase graph"), encoding="utf-8")
    code_block, unchanged = validate_unchanged()
    check(
        "delivery treats an ATX-looking line with four leading spaces as a code block",
        code_block.returncode == 1 and "Phase graph" in code_block.stdout and unchanged,
        f"artifacts_unchanged={unchanged}\n{code_block.stdout}{code_block.stderr}",
    )

    (d / "PLAN.md").write_text(
        valid_plan + "\n## Phase graph\n<!-- no phase content -->\n*\n",
        encoding="utf-8",
    )
    duplicate, unchanged = validate_unchanged()
    check(
        "delivery rejects an empty duplicate of a required heading",
        duplicate.returncode == 1 and "Phase graph" in duplicate.stdout and unchanged,
        f"artifacts_unchanged={unchanged}\n{duplicate.stdout}{duplicate.stderr}",
    )

    marker_prd = (
        "# Billing PRD\n\n"
        "## 4. Requirements\n\n"
        "### REQ-001 Billing behavior\n"
        "- Requirement: <!-- empty --> -\n"
        "- Acceptance criteria: +\n\n"
        "## 5. Notes\n"
        "- Requirement: A later section must not satisfy REQ-001.\n"
        "- Acceptance criteria: A later section must not satisfy REQ-001.\n"
    )
    (d / "PRD.md").write_text(marker_prd, encoding="utf-8")
    (d / "PLAN.md").write_text(valid_plan, encoding="utf-8")
    markers, unchanged = validate_unchanged()
    check(
        "delivery rejects comment and empty list marker bodies without crossing section boundaries",
        markers.returncode == 1
        and "Requirement body must be nonblank" in markers.stdout
        and "Acceptance criteria body must be nonblank" in markers.stdout
        and unchanged,
        f"artifacts_unchanged={unchanged}\n{markers.stdout}{markers.stderr}",
    )


def case_audit_remediation_markdown_sections_reject_empty_duplicates(root: Path) -> None:
    valid_domain = "valid-audit-sections"
    devflow(root, "init", valid_domain, "--workflow", "audit-remediation")
    valid_dir = root / f"docs/domains/{valid_domain}"
    fill_audit_remediation_contract(valid_dir)
    valid_prd = valid_dir / "PRD.md"
    valid_plan = valid_dir / "PLAN.md"
    valid_prd.write_text(
        valid_prd.read_text(encoding="utf-8").replace("## In scope\nBilling runtime.", "   ## In scope\n- Billing runtime."),
        encoding="utf-8",
    )
    valid_plan.write_text(
        valid_plan.read_text(encoding="utf-8").replace(
            "## Finding disposition strategy\nClassify every finding.",
            "  ## Finding disposition strategy\n+ Classify every finding.",
        ),
        encoding="utf-8",
    )
    write_audit(valid_dir / "audits/integration.md", audit_metadata(valid_dir))
    accepted = devflow(root, "audit", "apply", valid_domain, "--scope", "integration", "--mode", "initial")
    check(
        "audit remediation accepts indented headings and nonblank list item bodies",
        accepted.returncode == 0,
        accepted.stdout + accepted.stderr,
    )

    invalid_domain = "invalid-audit-sections"
    devflow(root, "init", invalid_domain, "--workflow", "audit-remediation")
    invalid_dir = root / f"docs/domains/{invalid_domain}"
    fill_audit_remediation_contract(invalid_dir)
    invalid_prd = invalid_dir / "PRD.md"
    invalid_plan = invalid_dir / "PLAN.md"
    invalid_prd.write_text(
        invalid_prd.read_text(encoding="utf-8").replace(
            "## In scope\nBilling runtime.",
            "## In scope\n- Billing runtime.\n\n   ## In scope\n<!-- empty -->\n-",
        ),
        encoding="utf-8",
    )
    invalid_plan.write_text(
        invalid_plan.read_text(encoding="utf-8").replace(
            "## Finding disposition strategy\nClassify every finding.",
            "## Finding disposition strategy\n+ Classify every finding.\n\n"
            "  ## Finding disposition strategy\n<!-- empty -->\n*\n+",
        ),
        encoding="utf-8",
    )
    write_audit(invalid_dir / "audits/integration.md", audit_metadata(invalid_dir))
    before = {str(path.relative_to(invalid_dir)): path.read_bytes() for path in invalid_dir.rglob("*") if path.is_file()}
    rejected = devflow(root, "audit", "apply", invalid_domain, "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(invalid_dir)): path.read_bytes() for path in invalid_dir.rglob("*") if path.is_file()}
    check(
        "audit remediation rejects empty duplicate required sections without mutation",
        rejected.returncode == 2
        and "In scope" in rejected.stderr
        and "Finding disposition strategy" in rejected.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{rejected.stdout}{rejected.stderr}",
    )


def case_markdown_sections_ignore_fenced_required_headings(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    fill_delivery_contract(d)
    plan_path = d / "PLAN.md"
    phase_section = (
        "## Phase graph\n\n"
        "### Phase 01 Billing\n"
        "- Objective: Preserve the approved behavior.\n\n"
    )
    plan = plan_path.read_text(encoding="utf-8")
    plan_path.write_text(
        plan.replace(phase_section, "## Phase graph\n\n```text\nphase-01\n```\n\n"),
        encoding="utf-8",
    )
    accepted = devflow(root, "validate", "billing")
    check(
        "delivery permits a fenced code block inside a real required section",
        accepted.returncode == 0,
        accepted.stdout + accepted.stderr,
    )

    plan_path.write_text(
        plan.replace(phase_section, "")
        + "\n```markdown\n## Phase graph\nThis heading is only example code.\n```\n",
        encoding="utf-8",
    )
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    rejected = devflow(root, "validate", "billing")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "delivery does not accept a required heading inside a backtick fence",
        rejected.returncode == 1 and "Phase graph" in rejected.stdout and before == after,
        f"artifacts_unchanged={before == after}\n{rejected.stdout}{rejected.stderr}",
    )

    audit_domain = "fenced-audit-sections"
    devflow(root, "init", audit_domain, "--workflow", "audit-remediation")
    audit_dir = root / f"docs/domains/{audit_domain}"
    fill_audit_remediation_contract(audit_dir)
    audit_prd = audit_dir / "PRD.md"
    audit_plan = audit_dir / "PLAN.md"
    audit_prd.write_text(
        audit_prd.read_text(encoding="utf-8").replace("## In scope\nBilling runtime.\n\n", "")
        + "\n ~~~markdown\n  ## In scope\nThis heading is only example code.\n ~~~\n",
        encoding="utf-8",
    )
    audit_plan.write_text(
        audit_plan.read_text(encoding="utf-8").replace(
            "## Finding disposition strategy\nClassify every finding.\n\n",
            "",
        )
        + "\n  ```markdown\n ## Finding disposition strategy\nThis heading is only example code.\n  ```\n",
        encoding="utf-8",
    )
    write_audit(audit_dir / "audits/integration.md", audit_metadata(audit_dir))
    before = {str(path.relative_to(audit_dir)): path.read_bytes() for path in audit_dir.rglob("*") if path.is_file()}
    rejected = devflow(root, "audit", "apply", audit_domain, "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(audit_dir)): path.read_bytes() for path in audit_dir.rglob("*") if path.is_file()}
    check(
        "audit remediation does not accept required headings inside matching fences",
        rejected.returncode == 2
        and "In scope" in rejected.stderr
        and "Finding disposition strategy" in rejected.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{rejected.stdout}{rejected.stderr}",
    )


def case_markdown_body_rejects_empty_ordered_markers(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    fill_delivery_contract(d)
    prd_path = d / "PRD.md"
    prd_path.write_text(
        prd_path.read_text(encoding="utf-8")
        .replace("Requirement: Preserve the approved billing behavior.", "Requirement: 1.")
        .replace("Acceptance criteria: AC-001 is verified.", "Acceptance criteria: 2)"),
        encoding="utf-8",
    )
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    rejected = devflow(root, "validate", "billing")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "delivery rejects ordered list markers without requirement or acceptance text",
        rejected.returncode == 1
        and "Requirement body must be nonblank" in rejected.stdout
        and "Acceptance criteria body must be nonblank" in rejected.stdout
        and before == after,
        f"artifacts_unchanged={before == after}\n{rejected.stdout}{rejected.stderr}",
    )

    audit_domain = "ordered-audit-sections"
    devflow(root, "init", audit_domain, "--workflow", "audit-remediation")
    audit_dir = root / f"docs/domains/{audit_domain}"
    fill_audit_remediation_contract(audit_dir)
    audit_prd = audit_dir / "PRD.md"
    audit_plan = audit_dir / "PLAN.md"
    audit_prd.write_text(
        audit_prd.read_text(encoding="utf-8").replace("## In scope\nBilling runtime.", "## In scope\n1."),
        encoding="utf-8",
    )
    audit_plan.write_text(
        audit_plan.read_text(encoding="utf-8").replace(
            "## Finding disposition strategy\nClassify every finding.",
            "## Finding disposition strategy\n2)",
        ),
        encoding="utf-8",
    )
    write_audit(audit_dir / "audits/integration.md", audit_metadata(audit_dir))
    before = {str(path.relative_to(audit_dir)): path.read_bytes() for path in audit_dir.rglob("*") if path.is_file()}
    rejected = devflow(root, "audit", "apply", audit_domain, "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(audit_dir)): path.read_bytes() for path in audit_dir.rglob("*") if path.is_file()}
    check(
        "audit remediation rejects ordered list markers without section text",
        rejected.returncode == 2
        and "In scope" in rejected.stderr
        and "Finding disposition strategy" in rejected.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{rejected.stdout}{rejected.stderr}",
    )

    valid_domain = "ordered-audit-content"
    devflow(root, "init", valid_domain, "--workflow", "audit-remediation")
    valid_dir = root / f"docs/domains/{valid_domain}"
    fill_audit_remediation_contract(valid_dir)
    valid_prd = valid_dir / "PRD.md"
    valid_plan = valid_dir / "PLAN.md"
    valid_prd.write_text(
        valid_prd.read_text(encoding="utf-8").replace("## In scope\nBilling runtime.", "## In scope\n1. Billing runtime."),
        encoding="utf-8",
    )
    valid_plan.write_text(
        valid_plan.read_text(encoding="utf-8").replace(
            "## Finding disposition strategy\nClassify every finding.",
            "## Finding disposition strategy\n2) Classify every finding.",
        ),
        encoding="utf-8",
    )
    write_audit(valid_dir / "audits/integration.md", audit_metadata(valid_dir))
    accepted = devflow(root, "audit", "apply", valid_domain, "--scope", "integration", "--mode", "initial")
    check(
        "audit remediation accepts ordered list markers followed by actual text",
        accepted.returncode == 0,
        accepted.stdout + accepted.stderr,
    )


def case_validate_rejects_duplicate_canonical_finding_ids(root: Path) -> None:
    d = audit_remediation_fixture(root)
    state_path = d / "STATE.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.3.0"
    state_doc["integration"]["status"] = "verified"
    dump(state_path, state_doc)
    finding = audit_finding("F-01")
    write_audit(d / "audits/integration.md", audit_metadata(d, findings=[finding, finding]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    rejected = devflow(root, "validate", "billing")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "validate rejects duplicate finding IDs in a verified canonical audit",
        rejected.returncode == 1
        and "duplicate audit finding id: F-01" in rejected.stdout
        and before == after,
        f"artifacts_unchanged={before == after}\n{rejected.stdout}{rejected.stderr}",
    )


def case_audit_closure_covers_every_prior_finding(root: Path) -> None:
    d = audit_remediation_fixture(root)
    findings = [audit_finding("F-01"), audit_finding("F-02")]
    write_audit(d / "audits/integration.md", audit_metadata(d, findings=findings))
    devflow(root, "status", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
    state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": "minor", "F-02": "minor"}}
    dump(d / "STATE.yaml", state_doc)
    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", findings=findings, closure=closure))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    check(
        "closure audit must cover every prior finding",
        out.returncode == 2 and "F-02" in out.stderr and "closure" in out.stderr.lower(),
        out.stdout + out.stderr,
    )


def case_audit_closure_reopens_finding(root: Path) -> None:
    d = audit_remediation_fixture(root)
    prior_finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The first remediation did not close the root cause.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[prior_finding]))
    devflow(root, "status", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
    state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": "major"}}
    dump(d / "STATE.yaml", state_doc)
    old_work = item(
        "INT-R01",
        kind="remediation",
        status="done",
        commands=["true -> passed"],
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    new_work = item(
        "INT-R02",
        kind="remediation",
        origin={"requirements": [], "findings": ["F-02"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", old_work, new_work))
    findings = [
        prior_finding,
        audit_finding(
            "F-02",
            classification="CONFIRMED",
            severity="blocker",
            severity_reason="The reopened defect can corrupt persisted state.",
            disposition={"action": "remediation_work", "work_ids": ["INT-R02"], "decision_ids": []},
        ),
    ]
    closure = [{"finding_id": "F-01", "outcome": "reopened", "evidence": ["regression still fails"], "reopened_as": ["F-02"]}]
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", verdict="fail", findings=findings, closure=closure))

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    applied = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "closure audit reopens a finding and schedules its linked remediation WORK",
        out.returncode == 0
        and applied["integration"]["status"] == "remediation"
        and applied["next_action"].get("command") == "run"
        and applied["next_action"].get("work_item") == "INT-R02",
        out.stdout + out.stderr + repr(applied),
    )

    devflow(root, "init", "shipping")
    phase_domain = root / "docs/domains/shipping"
    write_audit(
        phase_domain / "audits/phase-01.md",
        audit_metadata(phase_domain, scope="phase", verdict="conditional_pass", findings=[prior_finding]),
    )
    devflow(root, "status", "shipping")
    phase_state = yaml.safe_load((phase_domain / "STATE.yaml").read_text(encoding="utf-8"))
    phase_state["phases"] = {
        "01": {
            **phase("remediation", "01"),
            "diff_range": "current-head",
            "audit_provenance": {"findings": {"F-01": "major"}},
        }
    }
    phase_state["next_action"] = {
        "role": "auditor",
        "command": "audit",
        "scope": "phase",
        "mode": "closure",
        "phase": "01",
        "work_item": None,
    }
    dump(phase_domain / "STATE.yaml", phase_state)
    dump(phase_domain / "work/phase-01.yaml", work("01", old_work, new_work))
    phase_metadata = audit_metadata(
        phase_domain,
        scope="phase",
        mode="closure",
        verdict="fail",
        findings=findings,
        closure=closure,
    )
    write_audit(phase_domain / "audits/phase-01.md", phase_metadata)

    phase_out = devflow(root, "audit", "apply", "shipping", "--scope", "phase", "--phase", "01", "--mode", "closure")
    phase_applied = yaml.safe_load((phase_domain / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "phase closure applies before releasing newly reopened remediation WORK",
        phase_out.returncode == 0
        and phase_applied["phases"]["01"]["status"] == "remediation"
        and phase_applied["next_action"].get("work_item") == "INT-R02",
        phase_out.stdout + phase_out.stderr + repr(phase_applied),
    )


def case_audit_remediation_lifecycle_reaches_closure_and_complete(root: Path) -> None:
    d = audit_remediation_fixture(root)
    remediation = item(
        "INT-R01",
        kind="remediation",
        risk_level="high",
        premise_checks=["Confirm the finding still reproduces."],
        context=["Integration audit F-01 created this remediation."],
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", remediation))
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The integration defect blocks release.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="fail", findings=[finding]))

    initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after_initial = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "audit remediation initial apply releases linked integration WORK",
        initial.returncode == 0 and after_initial["next_action"].get("work_item") == "INT-R01",
        initial.stdout + initial.stderr + repr(after_initial),
    )
    commit_paths(root, "record initial audit", d / "audits/integration.md")

    started = devflow(root, "work", "start", "billing", "INT-R01")
    done = devflow(root, "work", "done", "billing", "INT-R01", "--command", "true -> passed")
    after_done = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "terminal high-risk remediation returns to its required work audit",
        started.returncode == 0
        and done.returncode == 0
        and after_done["next_action"].get("scope") == "work"
        and after_done["next_action"].get("work_item") == "INT-R01",
        started.stdout + started.stderr + done.stdout + done.stderr + repr(after_done),
    )

    write_audit(
        d / "audits/work/INT-R01.md",
        audit_metadata(d, scope="work", findings=[]),
    )
    reviewed = devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "INT-R01", "--mode", "initial")
    after_review = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "terminal remediation with verified review reaches integration closure",
        reviewed.returncode == 0
        and after_review["next_action"].get("scope") == "integration"
        and after_review["next_action"].get("mode") == "closure",
        reviewed.stdout + reviewed.stderr + repr(after_review),
    )

    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", findings=[finding], closure=closure))
    closed = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "audit remediation closure reaches verified complete with terminal WORK present",
        closed.returncode == 0
        and completed["integration"]["status"] == "verified"
        and completed["project_status"] == "complete"
        and completed["next_action"].get("command") == "complete",
        closed.stdout + closed.stderr + repr(completed),
    )


def case_audit_remediation_full_lifecycle_without_findings(root: Path) -> None:
    initialized = devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    initial_state = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    rendered = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "full no-finding lifecycle renders only the initial integration audit",
        initialized.returncode == 0
        and rendered.returncode == 0
        and initial_state["integration"]["status"] == "audit"
        and initial_state["next_action"]["scope"] == "integration"
        and initial_state["next_action"]["mode"] == "initial"
        and not (d / "work/integration.yaml").exists()
        and "# Decisions" in (d / "DECISIONS.md").read_text(encoding="utf-8")
        and initial_state["unresolved_decisions"] == [],
        initialized.stdout + initialized.stderr + rendered.stdout + rendered.stderr + repr(initial_state),
    )

    write_audit(d / "audits/integration.md", audit_metadata(d))
    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    status = devflow(root, "status", "billing", "--json")
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    audit_doc = read_audit(d / "audits/integration.md")
    reported = json.loads(status.stdout) if status.returncode == 0 else {}
    check(
        "full no-finding lifecycle persists a passing audit and completes",
        applied.returncode == 0
        and status.returncode == 0
        and audit_doc["mode"] == "initial"
        and audit_doc["verdict"] == "pass"
        and audit_doc["findings"] == []
        and completed["integration"]["status"] == "verified"
        and completed["project_status"] == "complete"
        and completed["next_action"]["command"] == "complete"
        and reported["next_action"]["command"] == "complete"
        and devflow(root, "validate", "billing").returncode == 0,
        applied.stdout + applied.stderr + status.stdout + status.stderr + repr(completed),
    )


def case_malformed_closure_metadata_does_not_hide_ready_work(root: Path) -> None:
    d = audit_remediation_fixture(root)
    ready = v2_item("INT-I01")
    dump(d / "work/integration.yaml", work_v2("integration", ready))
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "remediation"
    state_doc["next_action"] = {
        "role": "auditor",
        "command": "audit",
        "scope": "integration",
        "mode": "closure",
        "phase": None,
        "work_item": None,
    }
    dump(d / "STATE.yaml", state_doc)
    (d / "audits").mkdir(parents=True, exist_ok=True)
    (d / "audits/integration.md").write_text("---\nmode: closure\n---\n\n# Invalid closure\n", encoding="utf-8")

    status = devflow(root, "status", "billing", "--json")
    reported = json.loads(status.stdout) if status.returncode == 0 else {}
    check(
        "schema-invalid closure metadata cannot hide ready integration WORK",
        status.returncode == 0
        and reported.get("next_action", {}).get("command") == "run"
        and reported.get("next_action", {}).get("work_item") == "INT-I01",
        status.stdout + status.stderr,
    )


def case_latest_prior_audit_rejects_duplicate_finding_ids(root: Path) -> None:
    d = audit_remediation_fixture(root)
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
    state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": "minor"}}
    state_doc["next_action"] = {
        "role": "auditor",
        "command": "audit",
        "scope": "integration",
        "mode": "closure",
        "phase": None,
        "work_item": None,
    }
    dump(d / "STATE.yaml", state_doc)
    finding = audit_finding("F-01")
    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["verified"], "reopened_as": []}]

    write_audit(
        d / "audits/integration.md",
        audit_metadata(d, mode="closure", findings=[finding, copy.deepcopy(finding)], closure=closure),
    )
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}

    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "a closure audit with duplicate finding IDs is rejected atomically",
        applied.returncode == 2 and "duplicate" in applied.stderr.lower() and before == after,
        applied.stdout + applied.stderr,
    )


def case_audit_remediation_full_lifecycle_with_remediation(root: Path) -> None:
    initialized = devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    remediation = v2_item("INT-R01")
    remediation.update(
        kind="remediation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
        risk={"level": "high", "axes": ["correctness"]},
        premise_checks=["Confirm F-01 still reproduces at current HEAD."],
    )
    dump(d / "work/integration.yaml", work_v2("integration", remediation))
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The integration defect blocks release.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    rendered_initial = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="fail", findings=[finding]))
    applied_initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after_initial = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    work_doc = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))
    check(
        "full remediation lifecycle releases traced WORK v2 after initial audit",
        initialized.returncode == 0
        and rendered_initial.returncode == 0
        and applied_initial.returncode == 0
        and after_initial["integration"]["status"] == "remediation"
        and after_initial["next_action"]["command"] == "run"
        and after_initial["next_action"]["work_item"] == "INT-R01"
        and work_doc["version"] == 2
        and work_doc["items"][0]["origin"]["findings"] == ["F-01"],
        rendered_initial.stdout + rendered_initial.stderr + applied_initial.stdout + applied_initial.stderr + repr(after_initial),
    )
    commit_paths(root, "record initial integration audit", d / "audits/integration.md")

    rendered_run = devflow(root, "render", "run", "billing", "--task", "INT-R01")
    started = devflow(root, "work", "start", "billing", "INT-R01")
    running_state = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    done = devflow(root, "work", "done", "billing", "INT-R01", "--command", "true -> passed")
    after_done = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "full remediation lifecycle executes WORK and enters required work audit",
        rendered_run.returncode == 0
        and started.returncode == 0
        and running_state["next_action"]["command"] == "run"
        and running_state["next_action"]["work_item"] == "INT-R01"
        and done.returncode == 0
        and after_done["next_action"]["command"] == "audit"
        and after_done["next_action"]["scope"] == "work"
        and after_done["next_action"]["mode"] == "initial",
        rendered_run.stdout + rendered_run.stderr + started.stdout + started.stderr + done.stdout + done.stderr + repr(after_done),
    )

    rendered_work_audit = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "INT-R01", "--mode", "initial")
    write_audit(d / "audits/work/INT-R01.md", audit_metadata(d, scope="work"))
    applied_work_audit = devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "INT-R01", "--mode", "initial")
    after_work_audit = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    persisted_work = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))["items"][0]
    check(
        "full remediation lifecycle verifies required work audit before integration closure",
        rendered_work_audit.returncode == 0
        and applied_work_audit.returncode == 0
        and read_audit(d / "audits/work/INT-R01.md")["scope"] == "work"
        and persisted_work["status"] == "done"
        and persisted_work["review"]["status"] == "verified"
        and after_work_audit["next_action"]["scope"] == "integration"
        and after_work_audit["next_action"]["mode"] == "closure",
        rendered_work_audit.stdout + rendered_work_audit.stderr + applied_work_audit.stdout + applied_work_audit.stderr + repr(after_work_audit),
    )

    rendered_closure = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "closure")
    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", findings=[finding], closure=closure))
    applied_closure = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    status = devflow(root, "status", "billing", "--json")
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "full remediation lifecycle applies closure and completes",
        rendered_closure.returncode == 0
        and applied_closure.returncode == 0
        and read_audit(d / "audits/integration.md")["closure"] == closure
        and completed["integration"]["status"] == "verified"
        and completed["next_action"]["command"] == "complete"
        and json.loads(status.stdout)["project_status"] == "complete"
        and devflow(root, "validate", "billing").returncode == 0,
        rendered_closure.stdout + rendered_closure.stderr + applied_closure.stdout + applied_closure.stderr + status.stdout + status.stderr + repr(completed),
    )


def case_audit_remediation_full_lifecycle_with_decision(root: Path) -> None:
    initialized = devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    write_open_decision(d / "DECISIONS.md", "DEC-001")
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="The retention behavior requires a product decision.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-001"]},
    )
    rendered_initial = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    applied_initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    waiting = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "full decision lifecycle records an unresolved decision before creating WORK",
        initialized.returncode == 0
        and rendered_initial.returncode == 0
        and applied_initial.returncode == 0
        and waiting["unresolved_decisions"] == ["DEC-001"]
        and waiting["next_action"]["role"] == "human"
        and waiting["next_action"]["command"] == "decision"
        and not (d / "work/integration.yaml").exists()
        and "### DEC-001" in (d / "DECISIONS.md").read_text(encoding="utf-8"),
        rendered_initial.stdout + rendered_initial.stderr + applied_initial.stdout + applied_initial.stderr + repr(waiting),
    )

    (d / "DECISIONS.md").write_text(
        "# Decisions\n\n## Open\n\n## Resolved\n\n"
        "### DEC-001 Retention policy\n"
        "- Decision: Retain records for 30 days.\n"
        "- Rationale: The selected policy satisfies the approved requirement.\n",
        encoding="utf-8",
    )
    resolved = devflow(root, "decision", "resolve", "billing", "DEC-001")
    after_resolution = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    validated_resolution = devflow(root, "validate", "billing")
    check(
        "full decision lifecycle resolves the decision before creating WORK",
        resolved.returncode == 0
        and after_resolution["unresolved_decisions"] == []
        and validated_resolution.returncode == 0
        and not (d / "work/integration.yaml").exists()
        and "Decision: Retain records for 30 days." in (d / "DECISIONS.md").read_text(encoding="utf-8"),
        resolved.stdout + resolved.stderr + validated_resolution.stdout + validated_resolution.stderr + repr(after_resolution),
    )

    selected = v2_item(
        "INT-I01",
        acceptance=[{"id": "AC-INT-I01-01", "criterion": "Records are retained for exactly 30 days."}],
        commands=[{"id": "V-INT-I01-01", "command": "true", "covers": ["AC-INT-I01-01"]}],
    )
    selected["objective"] = "Implement the selected 30-day retention path."
    selected["decision_dependencies"] = ["DEC-001"]
    dump(d / "work/integration.yaml", work_v2("integration", selected))
    ready_status = devflow(root, "status", "billing", "--json")
    persisted = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))
    check(
        "full decision lifecycle releases one concrete selected-path WORK v2",
        ready_status.returncode == 0
        and json.loads(ready_status.stdout)["next_action"]["command"] == "run"
        and json.loads(ready_status.stdout)["next_action"]["work_item"] == "INT-I01"
        and persisted["version"] == 2
        and persisted["items"][0]["decision_dependencies"] == ["DEC-001"]
        and persisted["items"][0]["status"] == "ready",
        ready_status.stdout + ready_status.stderr + repr(persisted),
    )

    rendered_run = devflow(root, "render", "run", "billing", "--task", "INT-I01")
    started = devflow(root, "work", "start", "billing", "INT-I01")
    done = devflow(root, "work", "done", "billing", "INT-I01", "--command", "true -> passed")
    status = devflow(root, "status", "billing", "--json")
    after_work = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    rendered_closure = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "closure")
    check(
        "full decision lifecycle continues through selected WORK to integration closure",
        rendered_run.returncode == 0
        and started.returncode == 0
        and done.returncode == 0
        and status.returncode == 0
        and after_work["integration"]["status"] == "remediation"
        and after_work["next_action"]["scope"] == "integration"
        and after_work["next_action"]["mode"] == "closure"
        and yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))["items"][0]["status"] == "done"
        and read_audit(d / "audits/integration.md")["findings"][0]["disposition"]["decision_ids"] == ["DEC-001"]
        and rendered_closure.returncode == 0
        and devflow(root, "validate", "billing").returncode == 0,
        rendered_run.stdout + rendered_run.stderr + started.stdout + started.stderr + done.stdout + done.stderr + status.stdout + status.stderr + rendered_closure.stdout + rendered_closure.stderr + repr(after_work),
    )

    closure = [{
        "finding_id": "F-01",
        "outcome": "accepted_risk",
        "evidence": ["the approved decision records the accepted residual risk"],
        "reopened_as": [],
    }]
    write_audit(
        d / "audits/integration.md",
        audit_metadata(d, mode="closure", findings=[finding], closure=closure),
    )
    applied_closure = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    validated_closure = devflow(root, "validate", "billing")
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "accepted risk closure uses its resolved decision and completes",
        applied_closure.returncode == 0
        and validated_closure.returncode == 0
        and completed["integration"]["status"] == "verified"
        and completed["next_action"]["command"] == "complete",
        applied_closure.stdout + applied_closure.stderr
        + validated_closure.stdout + validated_closure.stderr
        + repr(completed),
    )


def case_decision_resolve_rejects_open_record_atomically(root: Path) -> None:
    d = audit_remediation_fixture(root)
    write_open_decision(d / "DECISIONS.md", "DEC-001")
    finding = audit_finding(
        "F-01",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="The retention behavior requires a product decision.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-001"]},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")

    selected = v2_item("INT-I01")
    selected["decision_dependencies"] = ["DEC-001"]
    dump(d / "work/integration.yaml", work_v2("integration", selected))
    state_file = d / "STATE.yaml"
    before = state_file.read_bytes()

    rejected = devflow(root, "decision", "resolve", "billing", "DEC-001")
    after_rejection = yaml.safe_load(state_file.read_text(encoding="utf-8"))
    status = devflow(root, "status", "billing", "--json")
    reported = json.loads(status.stdout) if status.returncode == 0 else {}
    rendered = devflow(root, "render", "run", "billing", "--task", "INT-I01")
    check(
        "decision resolve requires a valid resolved record before releasing WORK",
        applied.returncode == 0
        and rejected.returncode == 2
        and "DEC-001" in rejected.stderr
        and "resolved" in rejected.stderr.lower()
        and state_file.read_bytes() == before
        and after_rejection["unresolved_decisions"] == ["DEC-001"]
        and status.returncode == 0
        and reported["next_action"]["role"] == "human"
        and reported["next_action"]["command"] == "decision"
        and rendered.returncode == 2
        and rendered.stdout == "",
        applied.stdout + applied.stderr + rejected.stdout + rejected.stderr + status.stdout + status.stderr + rendered.stdout + rendered.stderr,
    )


def case_audit_remediation_full_lifecycle_with_reopened_finding(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    first_work = v2_item("INT-R01")
    first_work.update(kind="remediation", origin={"requirements": [], "findings": ["F-01"], "plan_items": []})
    dump(d / "work/integration.yaml", work_v2("integration", first_work))
    first_finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The first defect can corrupt persisted state.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    rendered_initial = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="fail", findings=[first_finding]))
    applied_initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    commit_paths(root, "record first initial audit", d / "audits/integration.md")
    started_first = devflow(root, "work", "start", "billing", "INT-R01")
    done_first = devflow(root, "work", "done", "billing", "INT-R01", "--command", "true -> passed")
    rendered_first_closure = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "closure")

    second_work = v2_item("INT-R02")
    second_work.update(kind="remediation", origin={"requirements": [], "findings": ["F-02"], "plan_items": []})
    integration_work = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))
    integration_work["items"].append(second_work)
    dump(d / "work/integration.yaml", integration_work)
    reopened_finding = audit_finding(
        "F-02",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The reopened defect still corrupts persisted state.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R02"], "decision_ids": []},
    )
    first_closure = [{"finding_id": "F-01", "outcome": "reopened", "evidence": ["regression still fails"], "reopened_as": ["F-02"]}]
    write_audit(
        d / "audits/integration.md",
        audit_metadata(d, mode="closure", verdict="fail", findings=[first_finding, reopened_finding], closure=first_closure),
    )
    applied_first_closure = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    validated_first_closure = devflow(root, "validate", "billing")
    reopened_state = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    persisted_provenance = reopened_state["integration"]["audit_provenance"]
    reopened_work = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))
    check(
        "full reopen lifecycle returns to traced integration remediation",
        rendered_initial.returncode == 0
        and applied_initial.returncode == 0
        and started_first.returncode == 0
        and done_first.returncode == 0
        and rendered_first_closure.returncode == 0
        and applied_first_closure.returncode == 0
        and validated_first_closure.returncode == 0
        and persisted_provenance["applied_against"] == {"F-01": "blocker"}
        and persisted_provenance["findings"] == {"F-01": "blocker", "F-02": "blocker"}
        and read_audit(d / "audits/integration.md")["closure"] == first_closure
        and reopened_state["integration"]["status"] == "remediation"
        and reopened_state["next_action"]["work_item"] == "INT-R02"
        and reopened_work["version"] == 2
        and {entry["id"]: entry["origin"]["findings"] for entry in reopened_work["items"]} == {
            "INT-R01": ["F-01"],
            "INT-R02": ["F-02"],
        },
        applied_first_closure.stdout + applied_first_closure.stderr + validated_first_closure.stdout + validated_first_closure.stderr + repr(reopened_state) + repr(reopened_work),
    )

    commit_paths(root, "record reopened closure", d / "audits/integration.md")
    started_second = devflow(root, "work", "start", "billing", "INT-R02")
    done_second = devflow(root, "work", "done", "billing", "INT-R02", "--command", "true -> passed")
    rendered_second_closure = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "closure")
    second_closure = [
        {"finding_id": "F-01", "outcome": "resolved", "evidence": ["first path replaced"], "reopened_as": []},
        {"finding_id": "F-02", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []},
    ]
    write_audit(
        d / "audits/integration.md",
        audit_metadata(d, mode="closure", findings=[first_finding, reopened_finding], closure=second_closure),
    )
    applied_second_closure = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    status = devflow(root, "status", "billing", "--json")
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    final_work = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))
    check(
        "full reopen lifecycle completes after the second closure",
        started_second.returncode == 0
        and done_second.returncode == 0
        and rendered_second_closure.returncode == 0
        and applied_second_closure.returncode == 0
        and read_audit(d / "audits/integration.md")["closure"] == second_closure
        and all(entry["status"] == "done" for entry in final_work["items"])
        and completed["integration"]["status"] == "verified"
        and completed["next_action"]["command"] == "complete"
        and json.loads(status.stdout)["project_status"] == "complete"
        and devflow(root, "validate", "billing").returncode == 0,
        applied_second_closure.stdout + applied_second_closure.stderr + started_second.stdout + started_second.stderr + done_second.stdout + done_second.stderr + rendered_second_closure.stdout + rendered_second_closure.stderr + status.stdout + status.stderr + repr(completed),
    )


def case_delivery_lifecycle_regression_after_protocol_130(root: Path) -> None:
    initialized = devflow(root, "init", "billing")
    legacy_config(root, "1.3.0")
    d = root / "docs/domains/billing"
    state_path = d / "STATE.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.3.0"
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(state_path, state_doc)
    delivery_work = v2_item("P01-I01")
    delivery_work.update(
        risk={"level": "high", "axes": ["correctness"]},
        premise_checks=["Confirm the delivery contract at current HEAD."],
    )
    dump(d / "work/phase-01.yaml", work_v2("01", delivery_work))
    initial_status = devflow(root, "status", "billing", "--json")
    rendered_run = devflow(root, "render", "run", "billing", "--task", "P01-I01")
    started = devflow(root, "work", "start", "billing", "P01-I01")
    done = devflow(root, "work", "done", "billing", "P01-I01", "--command", "true -> passed")
    after_done = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    check(
        "protocol 1.3 delivery runs phase WORK and preserves required work review",
        initialized.returncode == 0
        and initial_status.returncode == 0
        and json.loads(initial_status.stdout)["protocol_version"] == "1.3.0"
        and rendered_run.returncode == 0
        and started.returncode == 0
        and done.returncode == 0
        and after_done["next_action"]["scope"] == "work"
        and after_done["next_action"]["mode"] == "initial"
        and yaml.safe_load((d / "work/phase-01.yaml").read_text(encoding="utf-8"))["version"] == 2,
        initial_status.stdout + initial_status.stderr + rendered_run.stdout + rendered_run.stderr + started.stdout + started.stderr + done.stdout + done.stderr + repr(after_done),
    )

    rendered_work_audit = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "initial")
    write_audit(d / "audits/work/P01-I01.md", audit_metadata(d, scope="work"))
    applied_work_audit = devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "initial")
    phase_ref = devflow(root, "phase", "ref", "billing", "01", "--base", "HEAD", "--head", "HEAD")
    rendered_phase_audit = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01", "--mode", "initial")
    write_audit(d / "audits/phase-01.md", audit_metadata(d, scope="phase"))
    applied_phase_audit = devflow(root, "audit", "apply", "billing", "--scope", "phase", "--phase", "01", "--mode", "initial")
    after_phase = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    persisted_work = yaml.safe_load((d / "work/phase-01.yaml").read_text(encoding="utf-8"))["items"][0]
    check(
        "protocol 1.3 delivery verifies work and phase audits through audit apply",
        rendered_work_audit.returncode == 0
        and applied_work_audit.returncode == 0
        and phase_ref.returncode == 0
        and rendered_phase_audit.returncode == 0
        and applied_phase_audit.returncode == 0
        and persisted_work["review"]["status"] == "verified"
        and after_phase["phases"]["01"]["status"] == "verified"
        and after_phase["next_action"]["scope"] == "integration"
        and after_phase["next_action"]["mode"] == "initial"
        and read_audit(d / "audits/work/P01-I01.md")["scope"] == "work"
        and read_audit(d / "audits/phase-01.md")["scope"] == "phase",
        rendered_work_audit.stdout + rendered_work_audit.stderr + applied_work_audit.stdout + applied_work_audit.stderr + phase_ref.stdout + phase_ref.stderr + rendered_phase_audit.stdout + rendered_phase_audit.stderr + applied_phase_audit.stdout + applied_phase_audit.stderr + repr(after_phase),
    )

    rendered_integration = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    write_audit(d / "audits/integration.md", audit_metadata(d))
    applied_integration = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    status = devflow(root, "status", "billing", "--json")
    completed = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    check(
        "protocol 1.3 delivery verifies integration and completes",
        rendered_integration.returncode == 0
        and applied_integration.returncode == 0
        and read_audit(d / "audits/integration.md")["verdict"] == "pass"
        and completed["workflow_type"] == "delivery"
        and completed["integration"]["status"] == "verified"
        and completed["project_status"] == "complete"
        and completed["next_action"]["command"] == "complete"
        and json.loads(status.stdout)["next_action"]["command"] == "complete"
        and devflow(root, "validate", "billing").returncode == 0,
        rendered_integration.stdout + rendered_integration.stderr + applied_integration.stdout + applied_integration.stderr + status.stdout + status.stderr + repr(completed),
    )


def case_audit_apply_rolls_back_work_when_state_write_fails(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(d / "STATE.yaml", state_doc)
    dump(d / "work/phase-01.yaml", work("01", high_done("P01-I01")))
    write_audit(d / "audits/work/P01-I01.md", audit_metadata(d, scope="work"))
    before_state = (d / "STATE.yaml").read_bytes()
    before_work = (d / "work/phase-01.yaml").read_bytes()
    runtime = load_runtime_module()
    original_write = runtime.atomic_write_text

    def fail_state_write(path: Path, content: str) -> None:
        if Path(path) == d / "STATE.yaml":
            raise OSError("injected STATE write failure")
        original_write(path, content)

    with mock.patch.object(runtime, "atomic_write_text", side_effect=fail_state_write):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "initial")
    check(
        "audit apply rolls back WORK when the following STATE write fails",
        out.returncode == 2
        and "injected STATE write failure" in out.stderr
        and (d / "STATE.yaml").read_bytes() == before_state
        and (d / "work/phase-01.yaml").read_bytes() == before_work,
        out.stdout + out.stderr,
    )


def case_audit_apply_rollback_survives_atomic_writer_failure(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(d / "STATE.yaml", state_doc)
    dump(d / "work/phase-01.yaml", work("01", high_done("P01-I01")))
    write_audit(d / "audits/work/P01-I01.md", audit_metadata(d, scope="work"))
    before_state = (d / "STATE.yaml").read_bytes()
    before_work = (d / "work/phase-01.yaml").read_bytes()
    runtime = load_runtime_module()
    original_write = runtime.atomic_write_text
    calls = 0

    def fail_commit_and_writer_rollback(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected atomic writer failure {calls}")
        original_write(path, content)

    with mock.patch.object(runtime, "atomic_write_text", side_effect=fail_commit_and_writer_rollback):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "initial")
    check(
        "audit apply restores WORK without reusing the failed atomic writer",
        out.returncode == 2
        and "injected atomic writer failure 2" in out.stderr
        and calls == 2
        and (d / "STATE.yaml").read_bytes() == before_state
        and (d / "work/phase-01.yaml").read_bytes() == before_work,
        out.stdout + out.stderr + f" calls={calls}",
    )


def case_lifecycle_mutations_are_atomic(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    state_path = d / "STATE.yaml"
    base = state({"01": phase("executing", "01")})
    dump(state_path, base)
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01"), item("P01-I02", dependencies=["P01-I01"])))
    devflow(root, "work", "start", "billing", "P01-I01")

    def with_broken_state(mutator_state: dict[str, Any]) -> None:
        broken = yaml.safe_load(state_path.read_text(encoding="utf-8"))
        broken.update(mutator_state)
        dump(state_path, broken)

    commands = [
        ("work", "done", "billing", "P01-I01", "--command", "true -> passed"),
        ("work", "start", "billing", "P01-I02"),
        ("work", "block", "billing", "P01-I02", "--reason", "x"),
        ("work", "review", "billing", "P01-I01", "pending"),
        ("phase", "set", "billing", "01", "remediation"),
        ("phase", "ref", "billing", "01", "--base", "HEAD", "--head", "HEAD"),
        ("plan-review", "set", "billing", "pending"),
        ("integration", "set", "billing", "audit"),
        ("decision", "add", "billing", "DEC-001"),
    ]
    # AC-01..AC-03: a structurally invalid derived-state projection makes every mutation a no-op.
    all_atomic = True
    detail = ""
    for command in commands:
        with_broken_state({"plan_review": {"required": False, "status": "skipped", "remediation_work_ids": "not-a-list"}})
        before_state = state_path.read_bytes()
        before_work = (d / "work/phase-01.yaml").read_bytes()
        out = devflow(root, *command)
        after_state = state_path.read_bytes()
        after_work = (d / "work/phase-01.yaml").read_bytes()
        if not (out.returncode == 2 and before_state == after_state and before_work == after_work):
            all_atomic = False
            detail += f"\n{command}: rc={out.returncode} state_same={before_state == after_state} work_same={before_work == after_work}\n{out.stdout}{out.stderr}"
    check("AC-01..AC-03: a failed projection leaves every mutation command's WORK and STATE unchanged", all_atomic, detail)

    # AC-04: a STATE whose phases value is a string, not a mapping.
    dump(state_path, base)
    devflow(root, "work", "done", "billing", "P01-I01", "--command", "true -> passed")
    with_broken_state({"phases": {"01": "not-a-mapping"}})
    before_state = state_path.read_bytes()
    before_work = (d / "work/phase-01.yaml").read_bytes()
    out = devflow(root, "phase", "set", "billing", "01", "remediation")
    check(
        "AC-04: a phases entry that is a string, not a mapping, makes phase set a no-op",
        out.returncode == 2
        and state_path.read_bytes() == before_state
        and (d / "work/phase-01.yaml").read_bytes() == before_work,
        out.stdout + out.stderr,
    )

    # AC-05: an injected atomic_write_text failure on the STATE write during work done.
    dump(state_path, base)
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="in_progress")))
    before_state = state_path.read_bytes()
    before_work = (d / "work/phase-01.yaml").read_bytes()
    runtime = load_runtime_module()
    original_write = runtime.atomic_write_text

    def fail_state_write(path: Path, content: str) -> None:
        if Path(path) == state_path:
            raise OSError("injected STATE write failure")
        original_write(path, content)

    with mock.patch.object(runtime, "atomic_write_text", side_effect=fail_state_write):
        out = invoke_runtime(root, runtime, "work", "done", "billing", "P01-I01", "--command", "true -> passed")
    check(
        "AC-05: an injected STATE write failure during work done leaves WORK and STATE byte-identical",
        out.returncode == 2
        and state_path.read_bytes() == before_state
        and (d / "work/phase-01.yaml").read_bytes() == before_work,
        out.stdout + out.stderr,
    )


def case_audit_closure_uses_recorded_provenance(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    devflow(root, "init", "bypass", "--workflow", "audit-remediation")
    devflow(root, "init", "uncommitted", "--workflow", "audit-remediation")
    billing = root / "docs/domains/billing"
    bypass = root / "docs/domains/bypass"
    uncommitted = root / "docs/domains/uncommitted"
    prior = audit_finding("F-01")
    for directory in (billing, bypass):
        devflow(root, "status", directory.name)
        state_doc = yaml.safe_load((directory / "STATE.yaml").read_text(encoding="utf-8"))
        state_doc["integration"]["status"] = "closure"
        state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": "minor"}}
        dump(directory / "STATE.yaml", state_doc)

    new_finding = audit_finding("F-02")
    resolved = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(
        billing / "audits/integration.md",
        audit_metadata(billing, mode="closure", findings=[prior, new_finding], closure=resolved),
    )
    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    check(
        "closure covers the recorded prior finding without treating a current-only finding as prior",
        applied.returncode == 0,
        applied.stdout + applied.stderr,
    )

    bypass_closure = [{"finding_id": "F-01", "outcome": "reopened", "evidence": ["still fails"], "reopened_as": ["F-01"]}]
    write_audit(
        bypass / "audits/integration.md",
        audit_metadata(bypass, mode="closure", findings=[prior], closure=bypass_closure),
    )
    rejected = devflow(root, "audit", "apply", "bypass", "--scope", "integration", "--mode", "closure")
    check(
        "closure reopened_as must identify a current-only finding",
        rejected.returncode == 2 and "current-only" in rejected.stderr and "F-01" in rejected.stderr,
        rejected.stdout + rejected.stderr,
    )

    uncommitted_state = yaml.safe_load((uncommitted / "STATE.yaml").read_text(encoding="utf-8"))
    uncommitted_state["integration"]["status"] = "closure"
    dump(uncommitted / "STATE.yaml", uncommitted_state)
    before = {str(p.relative_to(uncommitted)): p.read_bytes() for p in uncommitted.rglob("*") if p.is_file()}
    write_audit(
        uncommitted / "audits/integration.md",
        audit_metadata(uncommitted, mode="closure", findings=[prior], closure=resolved),
    )
    no_provenance = devflow(root, "audit", "apply", "uncommitted", "--scope", "integration", "--mode", "closure")
    after = {str(p.relative_to(uncommitted)): p.read_bytes() for p in uncommitted.rglob("*") if p.is_file()}
    after.pop("audits/integration.md", None)
    before.pop("audits/integration.md", None)
    check(
        "closure is refused at a scope with no recorded provenance, naming its recovery command",
        no_provenance.returncode == 2
        and "integration has no recorded initial-audit provenance" in no_provenance.stderr
        and "devflow integration set uncommitted audit" in no_provenance.stderr
        and "--mode initial" in no_provenance.stderr
        and before == after,
        no_provenance.stdout + no_provenance.stderr,
    )


def _gitignored_remediation_lifecycle(root: Path) -> tuple[Path, list[subprocess.CompletedProcess]]:
    (root / ".gitignore").write_text("docs/\n", encoding="utf-8")
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    remediation = v2_item("INT-R01")
    remediation.update(kind="remediation", origin={"requirements": [], "findings": ["F-01"], "plan_items": []})
    dump(d / "work/integration.yaml", work_v2("integration", remediation))
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The integration defect violates an approved contract.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    steps: list[subprocess.CompletedProcess] = []
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    steps.append(devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial"))
    steps.append(devflow(root, "work", "start", "billing", "INT-R01"))
    steps.append(devflow(root, "work", "done", "billing", "INT-R01", "--command", "true -> passed"))
    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", findings=[finding], closure=closure))
    steps.append(devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure"))
    steps.append(devflow(root, "validate", "billing"))
    steps.append(devflow(root, "status", "billing"))
    return d, steps


def case_lifecycle_completes_with_gitignored_docs(root: Path) -> None:
    d, steps = _gitignored_remediation_lifecycle(root)
    ignored = sh(["git", "check-ignore", "-v", "docs/domains/billing/audits/integration.md"], root)
    tracked = sh(["git", "ls-files", "docs"], root)
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "the whole audit-remediation lifecycle completes with docs/ gitignored and never committed",
        all(step.returncode == 0 for step in steps)
        and completed["integration"]["status"] == "verified"
        and completed["project_status"] == "complete",
        "".join(step.stdout + step.stderr for step in steps) + repr(completed),
    )
    check(
        "the canonical audit file is genuinely covered by the docs/ ignore rule and stays untracked",
        "docs/" in ignored.stdout and tracked.stdout.strip() == "",
        f"check-ignore={ignored.stdout!r} ls-files={tracked.stdout!r}",
    )


def case_recorded_provenance_closure_is_deterministic(root: Path) -> None:
    d = audit_remediation_fixture(root)
    prior = audit_finding("F-01", severity="blocker", severity_reason="A concrete production failure remains.")
    devflow(root, "status", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
    state_doc["integration"]["audit_provenance"] = {"findings": {"F-01": "blocker"}}
    dump(d / "STATE.yaml", state_doc)
    current = audit_finding("F-02", severity="blocker", severity_reason="A separate production failure was found during closure.")
    # A closure whose `closure` list omits the recorded prior finding is refused.
    write_audit(
        d / "audits/integration.md",
        audit_metadata(
            d,
            mode="closure",
            verdict="fail",
            findings=[prior, current],
            closure=[{"finding_id": "F-02", "outcome": "still_open", "evidence": ["still failing"], "reopened_as": []}],
        ),
    )
    before_state = (d / "STATE.yaml").read_bytes()
    before_work = (d / "work/integration.yaml").read_bytes() if (d / "work/integration.yaml").exists() else b""
    first = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    mid_state = (d / "STATE.yaml").read_bytes()
    second = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    after_state = (d / "STATE.yaml").read_bytes()
    after_work = (d / "work/integration.yaml").read_bytes() if (d / "work/integration.yaml").exists() else b""
    check(
        "a closure that drops a recorded prior finding is refused deterministically and mutates nothing",
        first.returncode == 2
        and second.returncode == 2
        and "closure does not cover prior findings: F-01" in first.stderr
        and first.stderr == second.stderr
        and before_state == mid_state == after_state
        and before_work == after_work,
        first.stdout + first.stderr + "\n---\n" + second.stdout + second.stderr,
    )


def case_audit_provenance_validation_basis_is_structural(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["audit_provenance"] = {
        "findings": {"F-01": "major"},
        "applied_against": "not-a-mapping",
    }
    dump(d / "STATE.yaml", state_doc)

    validated = devflow(root, "validate", "billing")
    check(
        "validate rejects a non-mapping applied closure basis",
        validated.returncode == 1
        and "integration.audit_provenance.applied_against must be a mapping" in validated.stdout,
        validated.stdout + validated.stderr,
    )


def case_provenance_write_failure_is_atomic(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(d / "STATE.yaml", state_doc)
    dump(d / "work/phase-01.yaml", work("01", high_done("P01-I01")))
    write_audit(d / "audits/work/P01-I01.md", audit_metadata(d, scope="work"))
    before_state = (d / "STATE.yaml").read_bytes()
    before_work = (d / "work/phase-01.yaml").read_bytes()
    runtime = load_runtime_module()
    original_write = runtime.atomic_write_text

    def fail_state_write(path: Path, content: str) -> None:
        if Path(path) == d / "STATE.yaml":
            raise OSError("injected STATE write failure")
        original_write(path, content)

    with mock.patch.object(runtime, "atomic_write_text", side_effect=fail_state_write):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "initial")
    check(
        "a failed work-scope apply leaves no provenance behind in STATE or WORK",
        out.returncode == 2
        and (d / "STATE.yaml").read_bytes() == before_state
        and (d / "work/phase-01.yaml").read_bytes() == before_work
        and b"audit_provenance" not in (d / "work/phase-01.yaml").read_bytes(),
        out.stdout + out.stderr,
    )


def case_legacy_closure_without_provenance(root: Path) -> None:
    # Integration scope: a 1.3.0 domain sitting mid-closure with no recorded provenance is refused,
    # then recovers by re-running its initial audit through the scope's recovery command.
    d = audit_remediation_fixture(root)
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The integration defect violates an approved contract.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    remediation = item(
        "INT-R01",
        kind="remediation",
        status="done",
        commands=["true -> passed"],
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", remediation))
    devflow(root, "status", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
    state_doc["next_action"] = {
        "role": "auditor", "command": "audit", "scope": "integration",
        "mode": "closure", "phase": None, "work_item": None,
    }
    dump(d / "STATE.yaml", state_doc)
    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", findings=[finding], closure=closure))
    before = (d / "STATE.yaml").read_bytes()
    refused = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    check(
        "a legacy mid-closure integration domain without provenance is refused with its recovery command",
        refused.returncode == 2
        and "integration has no recorded initial-audit provenance" in refused.stderr
        and "devflow integration set billing audit" in refused.stderr
        and (d / "STATE.yaml").read_bytes() == before,
        refused.stdout + refused.stderr,
    )
    recovered = devflow(root, "integration", "set", "billing", "audit")
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    reapplied_initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    devflow(root, "work", "start", "billing", "INT-R01")
    devflow(root, "work", "done", "billing", "INT-R01", "--command", "true -> passed")
    write_audit(d / "audits/integration.md", audit_metadata(d, mode="closure", findings=[finding], closure=closure))
    reapplied_closure = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    completed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "re-running the initial audit records provenance and lets the closure proceed",
        recovered.returncode == 0
        and reapplied_initial.returncode == 0
        and reapplied_closure.returncode == 0
        and completed["integration"]["status"] == "verified",
        recovered.stdout + recovered.stderr + reapplied_initial.stdout + reapplied_initial.stderr + reapplied_closure.stdout + reapplied_closure.stderr + repr(completed),
    )

    # Work scope: the same, recovered with `devflow work review <domain> <ID> pending` from DF-AUD-001.
    devflow(root, "init", "shipping")
    sd = root / "docs/domains/shipping"
    sstate = yaml.safe_load((sd / "STATE.yaml").read_text(encoding="utf-8"))
    sstate["phases"] = {"01": phase("executing", "01")}
    dump(sd / "STATE.yaml", sstate)
    reviewed = high_done("P01-I01")
    reviewed["review"] = {
        "required": True,
        "status": "remediation",
        "audit_file": "audits/work/P01-I01.md",
        "remediation_work_ids": ["P01-R01"],
    }
    srem = item("P01-R01", kind="remediation", status="done", commands=["true -> ok"],
                origin={"requirements": [], "findings": ["F-01"], "plan_items": []})
    dump(sd / "work/phase-01.yaml", work("01", reviewed, srem))
    wfinding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The reviewed WORK still violates an approved contract.",
        disposition={"action": "remediation_work", "work_ids": ["P01-R01"], "decision_ids": []},
    )
    wclosure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(sd / "audits/work/P01-I01.md", audit_metadata(sd, scope="work", mode="closure", findings=[wfinding], closure=wclosure))
    before_work_state = (sd / "STATE.yaml").read_bytes()
    before_work_doc = (sd / "work/phase-01.yaml").read_bytes()
    wrefused = devflow(root, "audit", "apply", "shipping", "--scope", "work", "--task", "P01-I01", "--mode", "closure")
    check(
        "a work review with no recorded provenance is refused with the work-scope recovery command",
        wrefused.returncode == 2
        and "work has no recorded initial-audit provenance" in wrefused.stderr
        and "devflow work review shipping P01-I01 pending" in wrefused.stderr
        and (sd / "STATE.yaml").read_bytes() == before_work_state
        and (sd / "work/phase-01.yaml").read_bytes() == before_work_doc,
        wrefused.stdout + wrefused.stderr,
    )
    wrecovered = devflow(root, "work", "review", "shipping", "P01-I01", "pending")
    wrendered_initial = devflow(
        root, "render", "audit", "shipping", "--scope", "work", "--task", "P01-I01", "--mode", "initial"
    )
    write_audit(
        sd / "audits/work/P01-I01.md",
        audit_metadata(sd, scope="work", verdict="conditional_pass", findings=[wfinding]),
    )
    wreapplied_initial = devflow(
        root, "audit", "apply", "shipping", "--scope", "work", "--task", "P01-I01", "--mode", "initial"
    )
    protected_before = (sd / "work/phase-01.yaml").read_bytes()
    protected_reset = devflow(root, "work", "review", "shipping", "P01-I01", "pending")
    protected_unchanged = (sd / "work/phase-01.yaml").read_bytes() == protected_before
    write_audit(
        sd / "audits/work/P01-I01.md",
        audit_metadata(sd, scope="work", mode="closure", findings=[wfinding], closure=wclosure),
    )
    wreapplied_closure = devflow(
        root, "audit", "apply", "shipping", "--scope", "work", "--task", "P01-I01", "--mode", "closure"
    )
    wvalidated = devflow(root, "validate", "shipping")
    recovered_review = yaml.safe_load(
        (sd / "work/phase-01.yaml").read_text(encoding="utf-8")
    )["items"][0]["review"]
    check(
        "the advertised work recovery command completes a fresh audit lifecycle",
        wrecovered.returncode == 0
        and wrendered_initial.returncode == 0
        and wreapplied_initial.returncode == 0
        and protected_reset.returncode == 2
        and protected_unchanged
        and wreapplied_closure.returncode == 0
        and wvalidated.returncode == 0
        and recovered_review["status"] == "verified",
        wrecovered.stdout + wrecovered.stderr
        + wrendered_initial.stdout + wrendered_initial.stderr
        + wreapplied_initial.stdout + wreapplied_initial.stderr
        + protected_reset.stdout + protected_reset.stderr
        + wreapplied_closure.stdout + wreapplied_closure.stderr
        + wvalidated.stdout + wvalidated.stderr,
    )

    # Plan scope: pending must clear stale remediation ids before re-running the initial audit.
    devflow(root, "init", "planning", "--risk", "high")
    pd = root / "docs/domains/planning"
    pstate = yaml.safe_load((pd / "STATE.yaml").read_text(encoding="utf-8"))
    pstate["phases"] = {"01": phase("executing", "01")}
    pstate["plan_review"].update(status="remediation", remediation_work_ids=["P01-R01"])
    dump(pd / "STATE.yaml", pstate)
    prem = item(
        "P01-R01",
        kind="documentation",
        status="done",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(pd / "work/phase-01.yaml", work("01", prem))
    pfinding = audit_finding(
        "F-01",
        classification="DOCUMENTATION_DRIFT",
        severity="major",
        severity_reason="The plan documentation violates the approved contract.",
        disposition={"action": "documentation_work", "work_ids": ["P01-R01"], "decision_ids": []},
    )
    pclosure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["documentation verified"], "reopened_as": []}]
    write_audit(
        pd / "audits/plan.md",
        audit_metadata(pd, scope="plan", mode="closure", findings=[pfinding], closure=pclosure),
    )
    prefused = devflow(root, "audit", "apply", "planning", "--scope", "plan", "--mode", "closure")
    precovered = devflow(root, "plan-review", "set", "planning", "pending")
    recovered_plan_state = yaml.safe_load((pd / "STATE.yaml").read_text(encoding="utf-8"))
    prendered_initial = devflow(root, "render", "audit", "planning", "--scope", "plan", "--mode", "initial")
    write_audit(
        pd / "audits/plan.md",
        audit_metadata(pd, scope="plan", verdict="conditional_pass", findings=[pfinding]),
    )
    preapplied_initial = devflow(root, "audit", "apply", "planning", "--scope", "plan", "--mode", "initial")
    write_audit(
        pd / "audits/plan.md",
        audit_metadata(pd, scope="plan", mode="closure", findings=[pfinding], closure=pclosure),
    )
    preapplied_closure = devflow(root, "audit", "apply", "planning", "--scope", "plan", "--mode", "closure")
    pvalidated = devflow(root, "validate", "planning")
    completed_plan = yaml.safe_load((pd / "STATE.yaml").read_text(encoding="utf-8"))["plan_review"]
    check(
        "the advertised plan recovery command completes a fresh audit lifecycle",
        prefused.returncode == 2
        and "devflow plan-review set planning pending" in prefused.stderr
        and precovered.returncode == 0
        and not recovered_plan_state["plan_review"].get("remediation_work_ids")
        and prendered_initial.returncode == 0
        and preapplied_initial.returncode == 0
        and preapplied_closure.returncode == 0
        and pvalidated.returncode == 0
        and completed_plan["status"] == "verified",
        prefused.stdout + prefused.stderr
        + precovered.stdout + precovered.stderr
        + prendered_initial.stdout + prendered_initial.stderr
        + preapplied_initial.stdout + preapplied_initial.stderr
        + preapplied_closure.stdout + preapplied_closure.stderr
        + pvalidated.stdout + pvalidated.stderr,
    )


def case_plan_audit_remediation_reaches_closure(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(d / "STATE.yaml", state_doc)
    planned = item("P01-I01")
    remediation = item(
        "P01-R01",
        kind="documentation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/phase-01.yaml", work("01", planned, remediation))
    finding = audit_finding(
        "F-01",
        classification="DOCUMENTATION_DRIFT",
        severity="major",
        severity_reason="The PLAN documentation is stale.",
        disposition={"action": "documentation_work", "work_ids": ["P01-R01"], "decision_ids": []},
    )
    write_audit(d / "audits/plan.md", audit_metadata(d, scope="plan", verdict="conditional_pass", findings=[finding]))

    initial = devflow(root, "audit", "apply", "billing", "--scope", "plan", "--mode", "initial")
    after_initial = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "plan audit apply releases only its linked remediation WORK",
        initial.returncode == 0
        and after_initial["plan_review"]["status"] == "remediation"
        and after_initial["plan_review"]["remediation_work_ids"] == ["P01-R01"]
        and after_initial["next_action"].get("work_item") == "P01-R01",
        initial.stdout + initial.stderr + repr(after_initial),
    )
    ordinary = devflow(root, "work", "start", "billing", "P01-I01")
    check(
        "plan remediation rejects direct execution of ordinary planned WORK",
        ordinary.returncode == 2 and "required plan review is pending" in ordinary.stderr,
        ordinary.stdout + ordinary.stderr,
    )
    started = devflow(root, "work", "start", "billing", "P01-R01")
    done = devflow(root, "work", "done", "billing", "P01-R01")
    after_done = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "plan remediation can execute and returns to plan closure",
        started.returncode == 0
        and done.returncode == 0
        and after_done["next_action"].get("scope") == "plan"
        and after_done["next_action"].get("mode") == "closure",
        started.stdout + started.stderr + done.stdout + done.stderr + repr(after_done),
    )

    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["documentation verified"], "reopened_as": []}]
    write_audit(d / "audits/plan.md", audit_metadata(d, scope="plan", mode="closure", findings=[finding], closure=closure))
    closed = devflow(root, "audit", "apply", "billing", "--scope", "plan", "--mode", "closure")
    final_state = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "plan closure verifies review and releases planned implementation",
        closed.returncode == 0
        and final_state["plan_review"]["status"] == "verified"
        and final_state["next_action"].get("work_item") == "P01-I01",
        closed.stdout + closed.stderr + repr(final_state),
    )


def case_audit_apply_requires_schema_files(root: Path) -> None:
    domains: list[tuple[str, Path]] = []
    for domain in ["missing-audit", "missing-finding"]:
        devflow(root, "init", domain, "--workflow", "audit-remediation")
        directory = root / f"docs/domains/{domain}"
        fill_audit_remediation_contract(directory)
        write_audit(directory / "audits/integration.md", audit_metadata(directory))
        domains.append((domain, directory))

    for domain, directory, missing in [
        (*domains[0], "audit"),
        (*domains[1], "finding"),
    ]:
        fake_plugin = root / f"fake-plugin-{missing}"
        shutil.copytree(PLUGIN / "core", fake_plugin / "core")
        schema_path = fake_plugin / f"core/schemas/{missing}.schema.yaml"
        if missing == "audit":
            schema_path.unlink()
        else:
            schema_path.write_text("{}\n", encoding="utf-8")
        before = (directory / "STATE.yaml").read_bytes()
        runtime = load_runtime_module()
        with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
            out = invoke_runtime(root, runtime, "audit", "apply", domain, "--scope", "integration", "--mode", "initial")
        check(
            f"audit apply rejects unavailable {missing} schema",
            out.returncode == 2
            and missing in out.stderr.lower()
            and "schema" in out.stderr.lower()
            and (directory / "STATE.yaml").read_bytes() == before,
            out.stdout + out.stderr,
    )


def case_audit_apply_rejects_corrupt_schema_contracts(root: Path) -> None:
    for domain, schema_name in [("corrupt-audit", "audit"), ("corrupt-finding", "finding")]:
        devflow(root, "init", domain, "--workflow", "audit-remediation")
        d = root / f"docs/domains/{domain}"
        fill_audit_remediation_contract(d)
        fake_plugin = root / f"fake-plugin-{schema_name}"
        shutil.copytree(PLUGIN / "core", fake_plugin / "core")
        schema_path = fake_plugin / f"core/schemas/{schema_name}.schema.yaml"
        schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        schema_doc["schema"] = f"corrupt-{schema_name}-schema"
        if schema_name == "audit":
            schema_doc["properties"]["verdict"].pop("allowed")
            metadata = audit_metadata(d, verdict="bogus")
        else:
            schema_doc["properties"]["classification"].pop("allowed")
            schema_doc["properties"]["disposition"]["properties"]["action"].pop("allowed")
            corrupt_finding = audit_finding(
                "F-01",
                classification="BOGUS",
                disposition={"action": "BOGUS", "work_ids": [], "decision_ids": []},
            )
            metadata = audit_metadata(d, findings=[corrupt_finding])
        dump(schema_path, schema_doc)
        write_audit(d / "audits/integration.md", metadata)
        before = (d / "STATE.yaml").read_bytes()
        runtime = load_runtime_module()
        with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
            out = invoke_runtime(root, runtime, "audit", "apply", domain, "--scope", "integration", "--mode", "initial")
        check(
            f"audit apply rejects a corrupt {schema_name} schema contract",
            out.returncode == 2
            and schema_name in out.stderr.lower()
            and "schema" in out.stderr.lower()
            and (d / "STATE.yaml").read_bytes() == before,
            out.stdout + out.stderr,
        )


def case_audit_schema_trust_anchor_rejects_removed_verdict_contract(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    fake_plugin = root / "fake-plugin-audit-anchor"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    schema_path = fake_plugin / "core/schemas/audit.schema.yaml"
    schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema_doc["contract"]["required_allowed"] = ["properties.scope"]
    schema_doc["contract"].pop("rubric")
    schema_doc["properties"]["verdict"].pop("allowed")
    schema_doc.pop("verdict")
    dump(schema_path, schema_doc)
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="BOGUS"))
    before = (d / "STATE.yaml").read_bytes()
    runtime = load_runtime_module()

    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit schema trust anchor rejects simultaneous verdict contract removal",
        out.returncode == 2
        and "audit schema" in out.stderr.lower()
        and (d / "STATE.yaml").read_bytes() == before,
        out.stdout + out.stderr,
    )


def case_finding_schema_trust_anchor_rejects_removed_enum_contract(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    fake_plugin = root / "fake-plugin-finding-anchor"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    schema_path = fake_plugin / "core/schemas/finding.schema.yaml"
    schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema_doc["contract"]["required_allowed"] = ["properties.severity"]
    schema_doc["properties"]["classification"].pop("allowed")
    schema_doc["properties"]["disposition"]["properties"]["action"].pop("allowed")
    dump(schema_path, schema_doc)
    finding = audit_finding(
        "F-01",
        classification="BOGUS",
        disposition={"action": "BOGUS", "work_ids": [], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, findings=[finding]))
    before = (d / "STATE.yaml").read_bytes()
    runtime = load_runtime_module()

    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "finding schema trust anchor rejects simultaneous enum contract removal",
        out.returncode == 2
        and "finding schema" in out.stderr.lower()
        and (d / "STATE.yaml").read_bytes() == before,
        out.stdout + out.stderr,
    )


def case_finding_schema_trust_anchor_requires_work_kind(root: Path) -> None:
    d = audit_remediation_fixture(root)
    fake_plugin = root / "fake-plugin-finding-work-kind"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    schema_path = fake_plugin / "core/schemas/finding.schema.yaml"
    schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema_doc["classification"]["disposition"]["CONFIRMED"].pop("work_kind")
    dump(schema_path, schema_doc)
    linked_work = item(
        "INT-R01",
        kind="implementation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", linked_work))
    finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The confirmed defect requires remediation.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="conditional_pass", findings=[finding]))
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    runtime = load_runtime_module()

    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "finding schema trust anchor requires work_kind for work dispositions",
        out.returncode == 2
        and "finding schema" in out.stderr.lower()
        and "work_kind" in out.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_audit_remediation_prioritizes_unresolved_decisions(root: Path) -> None:
    d = audit_remediation_fixture(root)
    remediation = item(
        "INT-R01",
        kind="remediation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )
    dump(d / "work/integration.yaml", work("integration", remediation))
    work_finding = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="major",
        severity_reason="The implementation requires remediation.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R01"], "decision_ids": []},
    )
    decision_finding = audit_finding(
        "F-02",
        classification="DECISION_REQUIRED",
        severity="major",
        severity_reason="A product decision is unresolved.",
        disposition={"action": "decision", "work_ids": [], "decision_ids": ["DEC-001"]},
    )
    write_open_decision(d / "DECISIONS.md", "DEC-001")
    write_audit(
        d / "audits/integration.md",
        audit_metadata(d, verdict="conditional_pass", findings=[work_finding, decision_finding]),
    )

    out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    applied = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "audit remediation resolves project decisions before executable WORK",
        out.returncode == 0
        and applied["unresolved_decisions"] == ["DEC-001"]
        and applied["next_action"].get("command") == "decision"
        and applied["next_action"].get("role") == "human",
        out.stdout + out.stderr + repr(applied),
    )


def case_delivery_integration_prioritizes_unresolved_decisions(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(
        d / "STATE.yaml",
        state({"01": phase("verified", "01")}, unresolved_decisions=["DEC-001"]),
    )
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> passed"])))
    dump(d / "work/integration.yaml", work("integration", item("INT-R01")))

    out = devflow(root, "status", "billing")
    projected = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "delivery integration resolves project decisions before ready WORK",
        out.returncode == 0
        and projected["next_action"]["role"] == "human"
        and projected["next_action"]["command"] == "decision"
        and projected["next_action"]["scope"] == "project",
        out.stdout + out.stderr + repr(projected),
    )


def case_plan_review_remediation_metadata_is_validated(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    dump(d / "work/phase-01.yaml", work("01", item(
        "P01-R01",
        kind="documentation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
    )))
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    state_doc["plan_review"].update(status="remediation", remediation_work_ids=7)
    dump(d / "STATE.yaml", state_doc)

    invalid_type = devflow(root, "validate", "billing")
    invalid_status = devflow(root, "status", "billing")
    check(
        "plan review remediation WORK IDs require a list and fail cleanly",
        invalid_type.returncode == 1
        and "plan_review.remediation_work_ids must be a list" in invalid_type.stdout
        and invalid_status.returncode == 2
        and "plan_review.remediation_work_ids must be a list" in invalid_status.stderr,
        invalid_type.stdout + invalid_type.stderr + invalid_status.stdout + invalid_status.stderr,
    )

    state_doc["plan_review"]["remediation_work_ids"] = ["MISSING"]
    dump(d / "STATE.yaml", state_doc)
    unknown = devflow(root, "validate", "billing")
    check(
        "plan review remediation WORK IDs must exist",
        unknown.returncode == 1 and "unknown remediation WORK id MISSING" in unknown.stdout,
        unknown.stdout + unknown.stderr,
    )

    state_doc["plan_review"]["remediation_work_ids"] = ["P01-R01"]
    dump(d / "STATE.yaml", state_doc)
    valid_validation = devflow(root, "validate", "billing")
    valid = devflow(root, "status", "billing")
    projected = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "valid plan review remediation metadata releases its linked WORK",
        valid_validation.returncode == 0
        and valid.returncode == 0
        and projected["next_action"]["command"] == "run"
        and projected["next_action"]["work_item"] == "P01-R01",
        valid_validation.stdout + valid_validation.stderr + valid.stdout + valid.stderr + repr(projected),
    )


def case_spec_drift_stop_blocks_every_audit_scope(root: Path) -> None:
    prior = audit_finding(
        "F-01",
        classification="REJECTED",
        severity="major",
        severity_reason="The initial review retained a prior finding for closure coverage.",
    )
    stop = audit_finding(
        "F-02",
        classification="SPEC_DRIFT",
        severity="blocker",
        severity_reason="The approved specification conflicts with repository evidence.",
        disposition={"action": "stop", "work_ids": [], "decision_ids": []},
    )
    closure = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["prior concern closed"], "reopened_as": []}]

    devflow(root, "init", "plan-stop", "--risk", "high")
    plan_dir = root / "docs/domains/plan-stop"
    plan_work = item("P01-R01", status="done", commands=["true -> passed"])
    dump(plan_dir / "work/phase-01.yaml", work("01", plan_work))
    write_audit(plan_dir / "audits/plan.md", audit_metadata(plan_dir, scope="plan", verdict="conditional_pass", findings=[prior]))
    devflow(root, "status", "plan-stop")
    plan_state = yaml.safe_load((plan_dir / "STATE.yaml").read_text(encoding="utf-8"))
    plan_state["phases"] = {"01": phase("executing", "01")}
    plan_state["plan_review"].update(
        status="remediation",
        remediation_work_ids=["P01-R01"],
        audit_provenance={"findings": {"F-01": "major"}},
    )
    dump(plan_dir / "STATE.yaml", plan_state)
    write_audit(plan_dir / "audits/plan.md", audit_metadata(plan_dir, scope="plan", mode="closure", verdict="fail", findings=[prior, stop], closure=closure))
    plan_out = devflow(root, "audit", "apply", "plan-stop", "--scope", "plan", "--mode", "closure")

    devflow(root, "init", "work-stop")
    work_dir = root / "docs/domains/work-stop"
    reviewed = high_done("P01-I01")
    reviewed["review"] = {
        "required": True,
        "status": "remediation",
        "audit_file": "audits/work/P01-I01.md",
        "remediation_work_ids": ["P01-R01"],
        "audit_provenance": {"findings": {"F-01": "major"}},
    }
    remediation = item("P01-R01", status="done", commands=["true -> passed"])
    dump(work_dir / "work/phase-01.yaml", work("01", reviewed, remediation))
    work_state = yaml.safe_load((work_dir / "STATE.yaml").read_text(encoding="utf-8"))
    work_state["phases"] = {"01": phase("executing", "01")}
    dump(work_dir / "STATE.yaml", work_state)
    devflow(root, "status", "work-stop")
    write_audit(work_dir / "audits/work/P01-I01.md", audit_metadata(work_dir, scope="work", mode="closure", verdict="fail", findings=[prior, stop], closure=closure))
    work_out = devflow(root, "audit", "apply", "work-stop", "--scope", "work", "--task", "P01-I01", "--mode", "closure")

    devflow(root, "init", "phase-stop")
    phase_dir = root / "docs/domains/phase-stop"
    dump(phase_dir / "work/phase-01.yaml", work("01", item(
        "P01-R01",
        status="done",
        commands=["true -> passed"],
    )))
    phase_state = yaml.safe_load((phase_dir / "STATE.yaml").read_text(encoding="utf-8"))
    phase_state["phases"] = {"01": {**phase("remediation", "01"), "audit_provenance": {"findings": {"F-01": "major"}}}}
    dump(phase_dir / "STATE.yaml", phase_state)
    devflow(root, "status", "phase-stop")
    write_audit(phase_dir / "audits/phase-01.md", audit_metadata(phase_dir, scope="phase", mode="closure", verdict="fail", findings=[prior, stop], closure=closure))
    phase_out = devflow(root, "audit", "apply", "phase-stop", "--scope", "phase", "--phase", "01", "--mode", "closure")

    integration_dir = audit_remediation_fixture(root)
    write_audit(integration_dir / "audits/integration.md", audit_metadata(integration_dir, verdict="conditional_pass", findings=[prior]))
    initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    devflow(root, "status", "billing")
    write_audit(integration_dir / "audits/integration.md", audit_metadata(integration_dir, mode="closure", verdict="fail", findings=[prior, stop], closure=closure))
    integration_out = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")

    results = [
        ("plan", plan_out, plan_dir),
        ("work", work_out, work_dir),
        ("phase", phase_out, phase_dir),
        ("integration", integration_out, integration_dir),
    ]
    for scope, out, directory in results:
        projected = yaml.safe_load((directory / "STATE.yaml").read_text(encoding="utf-8"))
        check(
            f"SPEC_DRIFT stop projects a human decision for {scope} audit",
            initial.returncode == 0
            and out.returncode == 0
            and projected["project_status"] == "blocked"
            and projected["next_action"]["role"] == "human"
            and projected["next_action"]["command"] == "decision",
            initial.stdout + initial.stderr + out.stdout + out.stderr + repr(projected),
        )


def case_stop_blocked_work_review_can_be_reopened(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    state_path = d / "STATE.yaml"
    state_doc = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(state_path, state_doc)
    delivery_work = v2_item("P01-I01")
    delivery_work.update(
        risk={"level": "high", "axes": ["correctness"]},
        premise_checks=["Confirm the delivery contract at current HEAD."],
    )
    dump(d / "work/phase-01.yaml", work_v2("01", delivery_work))
    devflow(root, "work", "start", "billing", "P01-I01")
    devflow(root, "work", "done", "billing", "P01-I01", "--command", "true -> passed")

    stop = audit_finding(
        "F-01",
        classification="SPEC_DRIFT",
        severity="blocker",
        severity_reason="The approved specification conflicts with repository evidence.",
        axis="correctness",
        expected="The approved specification and the repository agree.",
        actual="The approved specification contradicts the repository.",
        evidence=["specification and code disagree at the module boundary"],
        root_cause="The specification was approved against a stale interface.",
        disposition={"action": "stop", "work_ids": [], "decision_ids": []},
    )
    write_audit(d / "audits/work/P01-I01.md", audit_metadata(d, scope="work", verdict="fail", findings=[stop]))
    applied = devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "initial")
    after_apply = yaml.safe_load((d / "work/phase-01.yaml").read_text(encoding="utf-8"))["items"][0]
    state_after_apply = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    check(
        "SPEC_DRIFT stop on a work initial audit blocks the review and projects a human decision",
        applied.returncode == 0
        and after_apply["review"]["status"] == "blocked"
        and state_after_apply["next_action"]["role"] == "human"
        and state_after_apply["next_action"]["command"] == "decision",
        applied.stdout + applied.stderr + repr(after_apply) + repr(state_after_apply),
    )

    reopened = devflow(root, "work", "review", "billing", "P01-I01", "pending")
    after_reopen = yaml.safe_load((d / "work/phase-01.yaml").read_text(encoding="utf-8"))["items"][0]
    status_out = devflow(root, "status", "billing").stdout
    check(
        "work review pending reopens a stop-blocked review with an empty remediation set (AC-01, AC-02)",
        reopened.returncode == 0
        and after_reopen["review"]["status"] == "pending"
        and after_reopen["review"]["remediation_work_ids"] == [],
        reopened.stdout + reopened.stderr + repr(after_reopen),
    )
    check(
        "a reopened stop-blocked review projects the work initial audit (AC-03)",
        "next.command: audit" in status_out
        and "next.scope: work" in status_out
        and "next.mode: initial" in status_out
        and "next.work_item: P01-I01" in status_out,
        status_out,
    )

    verified = devflow(root, "work", "review", "billing", "P01-I01", "verified")
    check(
        "work review verified is still refused under protocol 1.3 (AC-05)",
        verified.returncode == 2 and "protocol 1.3+ requires devflow audit apply" in verified.stderr,
        verified.stdout + verified.stderr,
    )

    work_bytes = (d / "work/phase-01.yaml").read_bytes()
    state_bytes = state_path.read_bytes()
    second = devflow(root, "work", "review", "billing", "P01-I01", "pending")
    check(
        "work review pending is refused from a non-blocked status and mutates neither WORK nor STATE (AC-04)",
        second.returncode == 2
        and (d / "work/phase-01.yaml").read_bytes() == work_bytes
        and state_path.read_bytes() == state_bytes,
        second.stdout + second.stderr,
    )


def case_schema_required_fields_are_enforced(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"

    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    doc.pop("baseline_sha")
    dump(d / "STATE.yaml", doc)

    out = devflow(root, "validate", "billing")
    check(
        "STATE schema required fields are enforced by runtime validator",
        out.returncode != 0 and "baseline_sha" in out.stdout,
        out.stdout + out.stderr,
    )

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    doc = work("01", item("P01-I01"))
    doc["items"][0].pop("acceptance")
    dump(d / "work/phase-01.yaml", doc)

    out = devflow(root, "validate", "billing")
    check(
        "WORK schema required fields are enforced by runtime validator",
        out.returncode != 0 and "acceptance" in out.stdout,
        out.stdout + out.stderr,
    )


def case_phase_key_normalization(root: Path) -> None:
    """A verified phase stays verified regardless of how its key was written."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "work/phase-05.yaml", work("05", item("P05-I01")))

    for key in ["5", "05"]:
        dump(d / "STATE.yaml", state({key: phase("verified")}))
        out = devflow(root, "status", "billing").stdout
        check(f"verified phase with key {key!r} hands out no work", "next.work_item: P05-I01" not in out, out)

    # And the same phase, not yet verified, must hand the item out under either key.
    for key in ["5", "05"]:
        dump(d / "STATE.yaml", state({key: phase("executing")}))
        out = devflow(root, "status", "billing").stdout
        check(f"executing phase with key {key!r} hands the work out", "next.work_item: P05-I01" in out, out)


def case_phase_set_no_duplicate(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"5": phase("executing")}))
    devflow(root, "phase", "set", "billing", "5", "remediation")
    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    check("phase set updates in place instead of creating a second entry", list(doc["phases"]) == ["5"], repr(doc["phases"]))
    check("phase set applied the new status", doc["phases"]["5"]["status"] == "remediation", repr(doc["phases"]))

    dump(d / "STATE.yaml", state({"5": phase("verified"), "05": phase("verified")}))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects two raw keys that normalize to one phase", "Duplicate phase entry" in out, out)


def case_status_is_side_effect_free(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    p = d / "STATE.yaml"
    dump(p, state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    devflow(root, "status", "billing")
    before = p.read_text()
    derived = yaml.safe_load(before)
    check("status derives lifecycle fields before stability check", derived["project_status"] == "phase_execution" and derived["active_phase"] == "01", repr(derived))
    devflow(root, "status", "billing")
    check("repeated status does not rewrite STATE", before == p.read_text())


def case_premise_checks_required(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))

    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", risk_level="critical")))
    out = devflow(root, "validate", "billing").stdout
    check("critical risk without premise_checks is an error", "requires premise_checks" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item(
        "P01-I01", risk_level="critical",
        premise_checks=["confirm X at HEAD"], context=["Y is true"], pitfalls=["do not Z"])))
    result = devflow(root, "validate", "billing")
    check("critical risk with premise_checks passes", result.returncode == 0, result.stdout)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I02", risk_level="low")))
    result = devflow(root, "validate", "billing")
    check("low risk without premise_checks is not an error", result.returncode == 0, result.stdout)
    check("missing pitfalls is a warning, not an error", "WARN" in result.stdout and "pitfalls" in result.stdout, result.stdout)


def case_evidence_required(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    refused = devflow(root, "work", "done", "billing", "P01-I01")
    check("work done refuses ready work", refused.returncode == 2 and "status=in_progress" in refused.stderr, refused.stdout + refused.stderr)
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    check("refused ready work is not mutated", doc["items"][0]["status"] == "ready", repr(doc["items"][0]["status"]))

    devflow(root, "work", "start", "billing", "P01-I01")
    refused = devflow(root, "work", "done", "billing", "P01-I01")
    check("work done refuses with no recorded command", refused.returncode != 0, refused.stdout + refused.stderr)
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    check("no-evidence refusal leaves item in progress", doc["items"][0]["status"] == "in_progress", repr(doc["items"][0]["status"]))

    blank = devflow(root, "work", "done", "billing", "P01-I01", "--command", "   ")
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    check("work done refuses a whitespace-only command", blank.returncode == 2, blank.stdout + blank.stderr)
    check("whitespace-only refusal leaves item in progress", doc["items"][0]["status"] == "in_progress", repr(doc["items"][0]["status"]))
    check(
        "whitespace-only command is not persisted as evidence",
        all(str(c).strip() for c in doc["items"][0].get("evidence", {}).get("commands", [])),
        repr(doc["items"][0].get("evidence", {})),
    )

    ok = devflow(root, "work", "done", "billing", "P01-I01", "--command", "pytest -> 12 passed")
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    check("work done accepts a recorded command", ok.returncode == 0 and doc["items"][0]["status"] == "done", ok.stdout + ok.stderr)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I02", status="done")))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects done with empty evidence.commands", "done without evidence.commands" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item(
        "P01-I03",
        status="done",
        kind="documentation",
        origin={"requirements": [], "findings": ["F-DOC-001"], "plan_items": []},
    )))
    out = devflow(root, "validate", "billing").stdout
    check("documentation items are exempt from evidence.commands", "done without evidence.commands" not in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I04", verification={"commands": ["   "]})))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects whitespace-only verification.commands", "verification.commands must contain a non-empty command" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I05", status="done", commands=["   "])))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects done whose evidence.commands are whitespace only", "done without evidence.commands" in out, out)


def case_work_v2_requires_unique_acceptance_ids(root: Path) -> None:
    d = audit_remediation_fixture(root)
    template = yaml.safe_load((PLUGIN / "core/templates/WORK.yaml").read_text(encoding="utf-8"))
    check(
        "new WORK template uses version 2 acceptance and verification mappings",
        template.get("version") == 2
        and all(isinstance(value, dict) for value in template["items"][0]["acceptance"])
        and all(isinstance(value, dict) for value in template["items"][0]["verification"]["commands"]),
        repr(template),
    )
    cases = [
        (
            "duplicate",
            [
                {"id": "AC-01", "criterion": "first"},
                {"id": "AC-01", "criterion": "second"},
            ],
            "duplicate acceptance id",
        ),
        ("blank id", [{"id": "  ", "criterion": "first"}], "acceptance id must be a nonblank string"),
        ("blank criterion", [{"id": "AC-01", "criterion": "  "}], "acceptance criterion must be a nonblank string"),
    ]
    for name, acceptance, expected in cases:
        commands = [{"id": "V-01", "command": "true", "covers": [str(acceptance[0]["id"])]}]
        dump(d / "work/integration.yaml", work_v2("integration", v2_item("INT-I01", acceptance, commands)))
        out = devflow(root, "validate", "billing")
        check(
            f"WORK v2 rejects {name} acceptance metadata",
            out.returncode == 1 and expected in out.stdout,
            out.stdout + out.stderr,
        )
    valid = work_v2("integration", v2_item("INT-I01"))
    dump(d / "work/integration.yaml", valid)
    out = devflow(root, "validate", "billing")
    check("WORK v2 accepts unique complete mappings", out.returncode == 0, out.stdout + out.stderr)


def case_work_v2_requires_unique_verification_ids(root: Path) -> None:
    d = audit_remediation_fixture(root)
    cases = [
        (
            "duplicate",
            [
                {"id": "V-01", "command": "true", "covers": ["AC-01"]},
                {"id": "V-01", "command": "true", "covers": ["AC-01"]},
            ],
            "duplicate verification command id",
        ),
        ("blank id", [{"id": "  ", "command": "true", "covers": ["AC-01"]}], "verification command id must be a nonblank string"),
        ("blank command", [{"id": "V-01", "command": "  ", "covers": ["AC-01"]}], "verification command must be a nonblank string"),
        ("empty coverage", [{"id": "V-01", "command": "true", "covers": []}], "verification command covers must not be empty"),
    ]
    for name, commands, expected in cases:
        dump(d / "work/integration.yaml", work_v2("integration", v2_item("INT-I01", commands=commands)))
        out = devflow(root, "validate", "billing")
        check(
            f"WORK v2 rejects {name} verification metadata",
            out.returncode == 1 and expected in out.stdout,
            out.stdout + out.stderr,
        )


def case_verification_coverage_requires_every_acceptance_id(root: Path) -> None:
    d = audit_remediation_fixture(root)
    acceptance = [
        {"id": "AC-01", "criterion": "first"},
        {"id": "AC-02", "criterion": "second"},
    ]
    commands = [{"id": "V-01", "command": "true", "covers": ["AC-01"]}]
    dump(d / "work/integration.yaml", work_v2("integration", v2_item("INT-I01", acceptance, commands)))

    out = devflow(root, "validate", "billing")
    check(
        "WORK v2 requires every acceptance id to be covered",
        out.returncode == 1 and "acceptance ids lack verification coverage: AC-02" in out.stdout,
        out.stdout + out.stderr,
    )


def case_verification_coverage_rejects_unknown_acceptance_id(root: Path) -> None:
    d = audit_remediation_fixture(root)
    commands = [{"id": "V-01", "command": "true", "covers": ["AC-01", "AC-404"]}]
    dump(d / "work/integration.yaml", work_v2("integration", v2_item("INT-I01", commands=commands)))

    out = devflow(root, "validate", "billing")
    check(
        "WORK v2 rejects verification coverage of unknown acceptance ids",
        out.returncode == 1 and "verification command V-01 covers unknown acceptance id AC-404" in out.stdout,
        out.stdout + out.stderr,
    )


def case_work_v2_rejects_mixed_legacy_shapes(root: Path) -> None:
    d = audit_remediation_fixture(root)
    acceptance = [{"id": "AC-01", "criterion": "first"}, "legacy acceptance"]
    commands = [{"id": "V-01", "command": "true", "covers": ["AC-01"]}, "true"]
    dump(d / "work/integration.yaml", work_v2("integration", v2_item("INT-I01", acceptance, commands)))

    out = devflow(root, "validate", "billing")
    check(
        "WORK v2 rejects legacy acceptance and verification strings",
        out.returncode == 1
        and "acceptance entries must be mappings in WORK version 2" in out.stdout
        and "verification.commands entries must be mappings in WORK version 2" in out.stdout,
        out.stdout + out.stderr,
    )


def case_work_v1_remains_readable(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    dump(d / "STATE.yaml", state_doc)
    work_path = d / "work/phase-01.yaml"
    dump(work_path, work("01", item("P01-I01")))

    validated = devflow(root, "validate", "billing")
    started = devflow(root, "work", "start", "billing", "P01-I01")
    done = devflow(root, "work", "done", "billing", "P01-I01", "--command", "true -> passed")
    persisted = yaml.safe_load(work_path.read_text(encoding="utf-8"))
    check(
        "WORK v1 remains valid through the existing lifecycle without shape rewrite",
        validated.returncode == 0
        and started.returncode == 0
        and done.returncode == 0
        and persisted["version"] == 1
        and all(isinstance(value, str) for value in persisted["items"][0]["acceptance"])
        and all(isinstance(value, str) for value in persisted["items"][0]["verification"]["commands"]),
        validated.stdout + validated.stderr + started.stdout + started.stderr + done.stdout + done.stderr + repr(persisted),
    )


def case_work_mutations_reject_invalid_work_v2_contract(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    (d / "audits/work").mkdir(parents=True)
    (d / "audits/work/P01-I01.md").write_text("# work audit\n", encoding="utf-8")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["phases"] = {"01": phase("executing", "01")}
    invalid_docs = [
        ("empty acceptance and commands", work_v2("01", v2_item("P01-I01", [], []))),
        ("boolean version", {**work_v2("01", v2_item("P01-I01")), "version": True}),
        ("float version", {**work_v2("01", v2_item("P01-I01")), "version": 2.0}),
        ("unsupported version", {**work_v2("01", v2_item("P01-I01")), "version": 3}),
    ]
    mutations = [
        ("start", ["work", "start", "billing", "P01-I01"], "ready", False),
        ("done", ["work", "done", "billing", "P01-I01", "--command", "true -> passed"], "in_progress", False),
        ("block", ["work", "block", "billing", "P01-I01", "--reason", "blocked"], "ready", False),
        ("review", ["work", "review", "billing", "P01-I01", "verified"], "done", True),
    ]
    for invalid_name, invalid_doc in invalid_docs:
        for mutation_name, args, status, is_review in mutations:
            doc = copy.deepcopy(invalid_doc)
            doc["items"][0]["status"] = status
            if is_review:
                doc["items"][0]["risk"]["level"] = "high"
                doc["items"][0]["premise_checks"] = ["confirm current HEAD"]
                doc["items"][0]["evidence"]["commands"] = ["true -> passed"]
                doc["items"][0]["review"] = {
                    "required": True,
                    "status": "pending",
                    "audit_file": "audits/work/P01-I01.md",
                    "remediation_work_ids": [],
                }
                dependent = v2_item("P01-I02")
                dependent["dependencies"] = ["P01-I01"]
                doc["items"].append(dependent)
            dump(d / "STATE.yaml", state_doc)
            dump(d / "work/phase-01.yaml", doc)
            validated = devflow(root, "validate", "billing")
            before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
            mutated = devflow(root, *args)
            after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
            projected = devflow(root, "status", "billing") if is_review else None
            check(
                f"work {mutation_name} rejects {invalid_name} before mutation",
                validated.returncode == 1
                and mutated.returncode == 2
                and before == after
                and (projected is None or "next.work_item: P01-I02" not in projected.stdout),
                validated.stdout
                + validated.stderr
                + mutated.stdout
                + mutated.stderr
                + (projected.stdout + projected.stderr if projected else ""),
            )


def case_work_schema_trust_anchor_rejects_malformed_contract(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    mutations = [
        ("schema identifier", lambda schema: schema.update(schema="corrupt-work-schema")),
        ("missing version 2 contract", lambda schema: schema.pop("version_2")),
        ("extended supported versions", lambda schema: schema["version"].update(supported=[1, 2, 3])),
        ("non-list supported versions", lambda schema: schema["version"].update(supported=True)),
    ]
    for name, mutate in mutations:
        fake_plugin = root / f"fake-plugin-work-{name.replace(' ', '-')}"
        shutil.copytree(PLUGIN / "core", fake_plugin / "core")
        schema_path = fake_plugin / "core/schemas/work.schema.yaml"
        schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        mutate(schema_doc)
        dump(schema_path, schema_doc)
        before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        runtime = load_runtime_module()
        with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
            out = invoke_runtime(root, runtime, "validate", "billing")
        after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
        check(
            f"WORK schema trust anchor rejects {name} with a clean CLI error",
            out.returncode == 2
            and "work schema" in out.stderr.lower()
            and "traceback" not in out.stderr.lower()
            and before == after,
            out.stdout + out.stderr,
        )


def case_render_audit_includes_work_v2_contract(root: Path) -> None:
    audit_remediation_fixture(root)
    out = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "render audit includes the actionable WORK v2 coverage contract",
        out.returncode == 0
        and "version: 2" in out.stdout
        and "stable item-local ID" in out.stdout
        and "covers: [AC-P01-I01-01]" in out.stdout
        and "layer where its outcome is observable" in out.stdout,
        out.stdout + out.stderr,
    )


def case_transfer_enforced(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01"), "08": phase("planned", "08")}))
    dump(d / "work/phase-08.yaml", work("08", item("P08-I03")))

    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="transferred")))
    out = devflow(root, "validate", "billing").stdout
    check("transferred without transfer.to is an error", "transferred without transfer.to" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item(
        "P01-I01", status="transferred", requirements=["REQ-014"],
        transfer={"to": "P08-I03", "requirements": ["REQ-014"]})))
    out = devflow(root, "validate", "billing").stdout
    check("transfer whose target lacks the requirement is an error",
          "transferred requirements not registered on P08-I03: REQ-014" in out, out)

    dump(d / "work/phase-08.yaml", work("08", item("P08-I03", requirements=["REQ-014"])))
    out = devflow(root, "validate", "billing").stdout
    check("transfer registered in the receiving phase passes", "transferred requirements not registered" not in out, out)

    dump(d / "work/phase-01.yaml", work("01", item(
        "P01-I01", status="transferred", requirements=["REQ-014"],
        transfer={"to": "P99-NOPE", "requirements": ["REQ-014"]})))
    out = devflow(root, "validate", "billing").stdout
    check("transfer.to pointing at an unknown item is an error", "unknown item P99-NOPE" in out, out)


def case_lifecycle_consistency(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"05": phase("verified")}))
    dump(d / "work/phase-05.yaml", work("05", item("P05-I01")))
    out = devflow(root, "validate", "billing").stdout
    check("verified phase with open work is an error", "verified but has open work: P05-I01" in out, out)

    dump(d / "STATE.yaml", state({"05": phase("executing")}, integration="verified"))
    out = devflow(root, "validate", "billing").stdout
    check("verified integration over an unverified phase is an error", "integration is verified but phases are not" in out, out)


def case_validate_core_rules(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))

    dump(d / "work/phase-01.yaml", work("01", item("A", dependencies=["B"]), item("B", dependencies=["A"])))
    out = devflow(root, "validate", "billing").stdout
    check("dependency cycles are detected", "Dependency cycle" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("A", dependencies=["MISSING"])))
    out = devflow(root, "validate", "billing").stdout
    check("unknown dependencies are detected", "unknown dependency MISSING" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("A", acceptance=[])))
    out = devflow(root, "validate", "billing").stdout
    check("empty acceptance is an error", "acceptance must not be empty" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("A"), item("A")))
    out = devflow(root, "validate", "billing").stdout
    check("duplicate WORK ids are detected", "Duplicate WORK id: A" in out, out)

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, unresolved_decisions=["DEC-001"]))
    dump(d / "work/phase-01.yaml", work("01", item("A", decision_dependencies=["DEC-001"])))
    out = devflow(root, "validate", "billing").stdout
    check("ready item blocked by an unresolved decision is an error", "READY while blocked by unresolved decision" in out, out)


def case_phase_ref(root: Path) -> None:
    # Build the branch topology before init, so switching branches never touches DevFlow artifacts.
    seed = sh(["git", "rev-list", "--max-parents=0", "HEAD"], root, check=True).stdout.strip()
    sh(["git", "checkout", "-qb", "phase-a"], root, check=True)
    commit(root, "a")
    sh(["git", "checkout", "-qb", "phase-b"], root, check=True)
    commit(root, "b")
    # phase-c forks from the root commit, so phase-b is not one of its ancestors.
    sh(["git", "checkout", "-q", seed], root, check=True)
    sh(["git", "checkout", "-qb", "phase-c"], root, check=True)
    commit(root, "c")
    sh(["git", "checkout", "-q", "phase-b"], root, check=True)

    devflow(root, "init", "billing")
    # A phase is real only once its WORK file exists; the runtime refuses to invent one.
    dump(root / "docs/domains/billing/work/phase-01.yaml", work("01", item("P01-I01")))
    dump(root / "docs/domains/billing/work/phase-02.yaml", work("02", item("P02-I01")))

    ok = devflow(root, "phase", "ref", "billing", "1", "--base", "phase-a", "--head", "phase-b")
    doc = yaml.safe_load((root / "docs/domains/billing/STATE.yaml").read_text())
    check("phase ref pins a range on a linear stack", ok.returncode == 0, ok.stdout + ok.stderr)
    check("phase ref writes under the padded key", list(doc["phases"]) == ["01"], repr(doc["phases"]))
    check("phase ref records base, head, and a 3-dot range",
          doc["phases"]["01"].get("diff_range", "").count(".") == 3 and doc["phases"]["01"].get("base_sha"),
          repr(doc["phases"]["01"]))

    ancestor = sh(["git", "merge-base", "--is-ancestor", "phase-b", "phase-c"], root).returncode
    check("fixture really is a diverged stack", ancestor != 0, f"is-ancestor returned {ancestor}")

    bad = devflow(root, "phase", "ref", "billing", "2", "--base", "phase-b", "--head", "phase-c")
    check("phase ref refuses a diverged stack instead of emitting a stale 3-dot range",
          bad.returncode != 0 and "not an ancestor" in bad.stderr, bad.stdout + bad.stderr)
    doc = yaml.safe_load((root / "docs/domains/billing/STATE.yaml").read_text())
    check("a refused phase ref writes no range", not doc["phases"].get("02", {}).get("diff_range"), repr(doc["phases"]))

    forced = devflow(root, "phase", "ref", "billing", "2", "--base", "phase-b", "--head", "phase-c", "--range", "X..Y")
    doc = yaml.safe_load((root / "docs/domains/billing/STATE.yaml").read_text())
    check("phase ref accepts an explicit range for the diverged case",
          forced.returncode == 0 and doc["phases"]["02"]["diff_range"] == "X..Y", forced.stdout + forced.stderr)


def case_render_assembles_prompt(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    (d / "PITFALLS.md").write_text("# Domain pitfalls\n\nUNIQUE_PITFALL_MARKER\n")

    out = devflow(root, "render", "run", "billing").stdout
    check("render run inlines the selected item", "P01-I01" in out, out[:600])
    check("render run inlines the WORK item contract", "WORK item contract" in out, out[:600])
    check("render run inlines the authority rules", "Authority and conflict rules" in out, out[:600])
    check("render run inlines PITFALLS", "UNIQUE_PITFALL_MARKER" in out, out[:600])
    check("render run does not inline the audit core", "AUDIT core" not in out, out[:600])

    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> ok"])))
    out = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01").stdout
    check("render audit inlines the audit core axes", "Code-level design and contract correctness" in out, out[:600])
    check("render audit inlines the merge-base rule", "merge-base --is-ancestor" in out, out[:600])
    check("render audit reports an unset diff range explicitly", "diff_range: <unset" in out, out[:600])
    check("render audit inlines an extension", "Default domain audit extension" in out, out[:600])

    dump(d / "work/phase-01.yaml", work("01", high_done("P01-I01")))
    work_out = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01").stdout
    check("render work audit inlines the selected WORK YAML", "work_item: P01-I01" in work_out and "objective for P01-I01" in work_out, work_out[:1200])
    check("render work audit reports evidence and expected artifact", "work_verification_evidence:" in work_out and "audits/work/P01-I01.md" in work_out, work_out[:1200])
    check("render work audit does not create its artifact directory", not (d / "audits/work").exists())

    (d / "work/phase-01.yaml").unlink()
    dump(d / "STATE.yaml", state({}))
    plan_out = devflow(root, "render", "plan", "billing").stdout
    check("render plan inlines the lifecycle", "DevFlow lifecycle" in plan_out, plan_out[:600])


def case_render_context_assembler(root: Path) -> None:
    """Render only the stable-ID context each execution scope needs."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    (d / "PRD.md").write_text("""# PRD

### REQ-021 — Wanted
UNIQUE_REQ_021

#### Details
UNIQUE_REQ_021_DETAILS

### REQ-999 — Unrelated
UNRELATED_REQ_999
""", encoding="utf-8")
    (d / "PLAN.md").write_text("""# PLAN

### P03-02 — Wanted plan item
UNIQUE_PLAN_P03_02

### P09-99 — Unrelated
UNRELATED_PLAN_P09_99
""", encoding="utf-8")
    dump(d / "STATE.yaml", state({"01": phase("executing", "01"), "02": phase("planned", "02")}))
    selected = item("P01-I01", commands=["true -> context evidence"], origin={"requirements": ["REQ-021"], "findings": [], "plan_items": ["P03-02"]})
    unrelated = item("P02-I01", objective="UNRELATED_PHASE_WORK_BODY")
    integration_item = item("INT-I01", objective="UNIQUE_INTEGRATION_WORK_BODY")
    dump(d / "work/phase-01.yaml", work("01", selected))
    dump(d / "work/phase-02.yaml", work("02", unrelated))
    dump(d / "work/integration.yaml", work("integration", integration_item))

    run = devflow(root, "render", "run", "billing", "--task", "P01-I01").stdout
    check("render run includes matching PRD section and nested details", "UNIQUE_REQ_021" in run and "UNIQUE_REQ_021_DETAILS" in run, run)
    check("render run includes matching PLAN section", "UNIQUE_PLAN_P03_02" in run, run)
    check("render run excludes unrelated PRD section", "UNRELATED_REQ_999" not in run, run)
    check("render run excludes unrelated PLAN section", "UNRELATED_PLAN_P09_99" not in run, run)
    check("render run keeps full selected WORK item", "P01-I01" in run and "objective for P01-I01" in run, run)

    for path in (d / "work").glob("*.yaml"):
        path.unlink()
    dump(d / "STATE.yaml", state({}))
    plan = devflow(root, "render", "plan", "billing").stdout
    check("render plan includes full approved PRD", "UNIQUE_REQ_021" in plan and "UNRELATED_REQ_999" in plan, plan)

    selected["status"] = "done"
    unrelated["status"] = "cancelled"
    integration_item["status"] = "cancelled"
    dump(d / "STATE.yaml", state({"01": phase("audit", "01"), "02": phase("planned", "02")}))
    dump(d / "work/phase-01.yaml", work("01", selected))
    dump(d / "work/phase-02.yaml", work("02", unrelated))
    dump(d / "work/integration.yaml", work("integration", integration_item))
    phase_out = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01").stdout
    check("phase audit includes selected phase WORK", "P01-I01" in phase_out, phase_out)
    check("phase audit does not inline unrelated phase WORK", "UNRELATED_PHASE_WORK_BODY" not in phase_out, phase_out)

    (d / "audits/work").mkdir(parents=True)
    (d / "audits/work/P01-I01.md").write_text("UNIQUE_WORK_CLOSURE_AUDIT\n", encoding="utf-8")
    reviewed = high_done(
        "P01-I01",
        origin={"requirements": ["REQ-021"], "findings": [], "plan_items": ["P03-02"]},
        review={"required": True, "status": "remediation", "audit_file": "audits/work/P01-I01.md", "remediation_work_ids": ["REM-I01"]},
    )
    reviewed["evidence"]["commands"] = ["true -> context evidence"]
    remediation = item(
        "REM-I01",
        kind="remediation",
        status="done",
        commands=["true -> remediation evidence"],
        origin={"requirements": [], "findings": ["F-REM-001"], "plan_items": []},
    )
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", reviewed, remediation))
    (d / "work/phase-02.yaml").unlink()
    (d / "work/integration.yaml").unlink()
    work_audit = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "closure").stdout
    check("work audit includes matching origin context and evidence", "UNIQUE_REQ_021" in work_audit and "UNIQUE_PLAN_P03_02" in work_audit and "true -> context evidence" in work_audit, work_audit)
    check("closure work audit includes its existing audit file", "UNIQUE_WORK_CLOSURE_AUDIT" in work_audit, work_audit)

    selected["risk"] = {"level": "medium", "axes": []}
    selected["status"] = "done"
    unrelated["status"] = "done"
    integration_item["status"] = "done"
    dump(d / "STATE.yaml", state({"01": phase("verified", "01"), "02": phase("verified", "02")}))
    dump(d / "work/phase-01.yaml", work("01", selected))
    dump(d / "work/phase-02.yaml", work("02", unrelated))
    dump(d / "work/integration.yaml", work("integration", integration_item))
    integration = devflow(root, "render", "audit", "billing", "--scope", "integration").stdout
    check("integration render includes PLAN and phase manifest paths", "UNIQUE_PLAN_P03_02" in integration and "work/phase-01.yaml" in integration and "work/phase-02.yaml" in integration, integration)
    check("integration render includes its WORK without phase WORK bodies", "UNIQUE_INTEGRATION_WORK_BODY" in integration and "UNRELATED_PHASE_WORK_BODY" not in integration, integration)


def case_render_context_marks_missing_ids(root: Path) -> None:
    """A missing stable ID must stay explicit instead of finding a similar section."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    (d / "PRD.md").write_text("# PRD\n\n### REQ-021 — Present\nPRESENT\n", encoding="utf-8")
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", origin={"requirements": ["REQ-404"], "findings": [], "plan_items": []})))

    out = devflow(root, "render", "run", "billing", "--task", "P01-I01").stdout
    check("render marks missing IDs verbatim", "REQ-404: not found verbatim in PRD.md" in out, out)


def case_audit_scopes_use_their_own_artifacts(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc.update({"base_sha": "base", "head_sha": "head", "diff_range": "base...head"})
    legacy_plan_review = {"required": True, "status": "pending"}
    dump(d / "STATE.yaml", state({"01": phase_doc}, plan_review=legacy_plan_review, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    plan = devflow(root, "render", "audit", "billing", "--scope", "plan")
    check("plan audit uses plan audit artifact", plan.returncode == 0 and "audits/plan.md" in plan.stdout and "audits/integration.md" not in plan.stdout, plan.stdout + plan.stderr)

    missing_work = devflow(root, "render", "audit", "billing", "--scope", "work")
    check("work audit requires the next WORK target", missing_work.returncode == 2 and not missing_work.stdout and "expected" in missing_work.stderr, missing_work.stdout + missing_work.stderr)

    missing_phase = devflow(root, "render", "audit", "billing", "--scope", "phase")
    check("phase audit requires the next phase target", missing_phase.returncode == 2 and not missing_phase.stdout and "expected" in missing_phase.stderr, missing_phase.stdout + missing_phase.stderr)

    dump(d / "STATE.yaml", state({"01": phase_doc}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> ok"])))
    known_phase = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01")
    check("phase audit uses normalized phase artifacts", known_phase.returncode == 0 and "work/phase-01.yaml" in known_phase.stdout and "audits/phase-01.md" in known_phase.stdout, known_phase.stdout + known_phase.stderr)

    unknown_phase = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "02")
    check("phase audit rejects a non-next phase", unknown_phase.returncode == 2 and not unknown_phase.stdout and '"phase": "01"' in unknown_phase.stderr, unknown_phase.stdout + unknown_phase.stderr)

    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}, protocol_version="1.2.0"))
    integration = devflow(root, "render", "audit", "billing", "--scope", "integration")
    check("integration audit uses integration artifact", integration.returncode == 0 and "audits/integration.md" in integration.stdout, integration.stdout + integration.stderr)

    (d / "audits/plan.md").write_text("# plan audit\n")
    dump(d / "STATE.yaml", state({"01": phase_doc}, plan_review=legacy_plan_review, protocol_version="1.2.0"))
    verified = devflow(root, "plan-review", "set", "billing", "verified")
    check("legacy plan review verifies with its default artifact", verified.returncode == 0, verified.stdout + verified.stderr)


def case_extension_resolution(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}, extension="billing.example"))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> ok"])))
    out = devflow(root, "render", "audit", "billing", "--scope", "integration").stdout
    check("named bundled extension is resolved", "Billing extension example" in out, out[:600])

    override = root / ".devflow/extensions/billing.example.md"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("# Project override\n\nPROJECT_EXTENSION_MARKER\n")
    out = devflow(root, "render", "audit", "billing", "--scope", "integration").stdout
    check("project-local extension outranks the bundled one", "PROJECT_EXTENSION_MARKER" in out, out[:600])

    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}, extension="does-not-exist"))
    out = devflow(root, "render", "audit", "billing", "--scope", "integration").stdout
    check("unknown extension falls back to default", "Default domain audit extension" in out, out[:600])


def case_marketplace_plugin_version_matches_manifest(root: Path) -> None:
    manifest_path = PLUGIN / ".claude-plugin/plugin.json"
    codex_manifest_path = PLUGIN / ".codex-plugin/plugin.json"
    marketplace_path = PLUGIN.parents[1] / ".claude-plugin/marketplace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    codex_manifest = json.loads(codex_manifest_path.read_text(encoding="utf-8"))
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
    entries = [entry for entry in marketplace.get("plugins", []) if entry.get("name") == manifest.get("name")]
    check(
        "marketplace plugin version matches manifest",
        len(entries) == 1 and entries[0].get("version") == manifest.get("version") == codex_manifest.get("version") == "0.9.0",
        repr(entries) + repr(codex_manifest.get("version")),
    )


def case_codex_adapter_uses_shared_plugin(root: Path) -> None:
    codex_marketplace = PLUGIN.parents[1] / ".agents/plugins/marketplace.json"
    codex_manifest = PLUGIN / ".codex-plugin/plugin.json"
    claude_manifest = PLUGIN / ".claude-plugin/plugin.json"
    marketplace = json.loads(codex_marketplace.read_text(encoding="utf-8"))
    manifest = json.loads(codex_manifest.read_text(encoding="utf-8"))
    claude = json.loads(claude_manifest.read_text(encoding="utf-8"))
    entries = [entry for entry in marketplace.get("plugins", []) if entry.get("name") == manifest.get("name")]
    skills_root = PLUGIN / manifest.get("skills", "")
    check(
        "Codex adapter points at the shared DevFlow plugin",
        len(entries) == 1 and entries[0].get("source") == {"source": "local", "path": "./plugins/devflow"},
        repr(entries),
    )
    check(
        "Codex plugin discovers the shared skills at the same version as the Claude plugin manifest",
        manifest.get("version") == claude.get("version")
        and skills_root.resolve() == (PLUGIN / "skills").resolve()
        and {path.parent.name for path in skills_root.glob("*/SKILL.md")} == {"plan", "run", "audit", "status", "goal", "autopilot"},
        repr(manifest) + repr(claude.get("version")),
    )
    check(
        "Codex plugin metadata is complete where the Codex marketplace adapter is deliberately minimal",
        manifest.get("name") == "devflow"
        and isinstance(manifest.get("description"), str) and manifest["description"].strip()
        and "version" not in marketplace
        and all("version" not in entry for entry in marketplace.get("plugins", [])),
        repr(manifest.get("description")) + repr(marketplace),
    )
    capabilities = (manifest.get("interface") or {}).get("capabilities")
    check(
        "Codex plugin declares interface capabilities",
        isinstance(capabilities, list)
        and bool(capabilities)
        and all(isinstance(value, str) and value.strip() for value in capabilities),
        repr(capabilities),
    )


def case_status_reports_inputs(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", requirements=["REQ-021"]), item("P01-I02", status="blocked")))
    out = devflow(root, "status", "billing").stdout
    check("status lists blocked work", "blocked_work: P01-I02" in out, out)
    check("status names the documents the next action needs", "next.input:" in out, out)
    check("status names the requirement ids to load", "REQ-021" in out, out)
    check("status names PITFALLS as an input", "PITFALLS.md" in out, out)


def case_next_action_carries_work_routing_metadata(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(
        d / "work/phase-01.yaml",
        work(
            "01",
            item(
                "P01-I01",
                kind="migration",
                risk_level="high",
                context=["schema change is isolated"],
                premise_checks=["migration ordering still holds"],
            ),
        ),
    )
    devflow(root, "status", "billing")
    action = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))["next_action"]
    check(
        "run next_action carries WORK kind and risk into routing",
        action.get("command") == "run"
        and action.get("item_kind") == "migration"
        and action.get("item_risk") == "high",
        repr(action),
    )

    dump(
        d / "work/phase-01.yaml",
        work(
            "01",
            item(
                "P01-I01",
                risk_level="critical",
                status="done",
                commands=["true -> ok"],
                context=["critical path"],
                premise_checks=["critical premise still holds"],
            ),
        ),
    )
    devflow(root, "status", "billing")
    action = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))["next_action"]
    check(
        "work audit next_action carries reviewed WORK risk into verifier routing",
        action.get("command") == "audit"
        and action.get("scope") == "work"
        and action.get("item_kind") == "implementation"
        and action.get("item_risk") == "critical",
        repr(action),
    )


def case_lifecycle_walk(root: Path) -> None:
    """One pass through the lifecycle: run the work, audit the phase, verify, then integration."""
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    out = devflow(root, "status", "billing").stdout
    check("walk: starts by running the ready item", "next.command: run" in out and "next.work_item: P01-I01" in out, out)

    devflow(root, "work", "start", "billing", "P01-I01")
    devflow(root, "work", "done", "billing", "P01-I01", "--command", "true -> ok")
    out = devflow(root, "status", "billing").stdout
    check("walk: completed phase work asks for a phase audit", "next.command: audit" in out and "next.phase: 01" in out, out)

    state_doc = yaml.safe_load((d / "STATE.yaml").read_text())
    state_doc["phases"]["01"]["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state_doc)
    (d / "audits/phase-01.md").write_text("# phase audit\n")
    devflow(root, "phase", "set", "billing", "01", "verified")
    out = devflow(root, "status", "billing").stdout
    check("walk: verified phase moves to the integration audit", "next.scope: integration" in out, out)

    (d / "audits/integration.md").write_text("# integration audit\n")
    devflow(root, "integration", "set", "billing", "verified")
    out = devflow(root, "status", "billing").stdout
    check("walk: verified integration completes the project", "next.command: complete" in out, out)
    check("walk: validation is clean at the end", devflow(root, "validate", "billing").returncode == 0,
          devflow(root, "validate", "billing").stdout)


def case_derived_lifecycle_state(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    devflow(root, "status", "billing")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived execution status and phase", derived["project_status"] == "phase_execution" and derived["active_phase"] == "01", repr(derived))

    devflow(root, "work", "start", "billing", "P01-I01")
    devflow(root, "work", "done", "billing", "P01-I01", "--command", "true -> ok")
    devflow(root, "status", "billing")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived phase audit status and phase", derived["project_status"] == "phase_audit" and derived["active_phase"] == "01", repr(derived))
    check("derived phase audit keeps the phase scope", derived["next_action"]["scope"] == "phase", repr(derived["next_action"]))

    derived["phases"]["01"]["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", derived)
    (d / "audits/phase-01.md").write_text("# phase audit\n")
    devflow(root, "phase", "set", "billing", "01", "verified")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived integration audit clears phase", derived["project_status"] == "integration_audit" and derived["active_phase"] is None, repr(derived))

    dump(d / "work/integration.yaml", work("integration", item("IR1", kind="remediation", origin={"requirements": [], "findings": ["F-INT-001"], "plan_items": []})))
    devflow(root, "integration", "set", "billing", "remediation")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived integration remediation status", derived["project_status"] == "integration_remediation" and derived["active_phase"] is None, repr(derived))

    devflow(root, "work", "start", "billing", "IR1")
    devflow(root, "work", "done", "billing", "IR1", "--command", "true -> ok")
    devflow(root, "integration", "set", "billing", "closure")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived integration closure status", derived["project_status"] == "integration_closure" and derived["active_phase"] is None, repr(derived))

    (d / "audits/integration.md").write_text("# integration audit\n")
    devflow(root, "integration", "set", "billing", "verified")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived completion clears phase", derived["project_status"] == "complete" and derived["active_phase"] is None, repr(derived))


def case_derived_integration_work_review_state(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> ok"])))
    dump(d / "work/integration.yaml", work("integration", high_done("INT-HIGH")))

    devflow(root, "status", "billing")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check(
        "integration work review derives work audit status",
        derived["project_status"] == "work_audit" and derived["active_phase"] is None,
        repr(derived),
    )


def case_derived_blocked_state_and_audit_scopes(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("blocked", "01")}, unresolved_decisions=["DEC-001"]))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", decision_dependencies=["DEC-001"])))

    devflow(root, "status", "billing")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    check("derived blocked status and phase", derived["project_status"] == "blocked" and derived["active_phase"] == "01", repr(derived))

    audits = []
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, risk_profile="high", plan_review={"required": True, "status": "pending", "audit_file": "audits/plan.md"}))
    dump(d / "work/phase-01.yaml", work("01", item("PLAN-GATED")))
    devflow(root, "status", "billing")
    audits.append(yaml.safe_load((d / "STATE.yaml").read_text())["next_action"])

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", high_done("WORK-REVIEW")))
    devflow(root, "status", "billing")
    audits.append(yaml.safe_load((d / "STATE.yaml").read_text())["next_action"])

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("PHASE-REVIEW", status="done", commands=["true -> ok"])))
    devflow(root, "status", "billing")
    audits.append(yaml.safe_load((d / "STATE.yaml").read_text())["next_action"])

    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))
    dump(d / "work/integration.yaml", work("integration", item("INTEGRATION-REVIEW", status="done", commands=["true -> ok"])))
    devflow(root, "status", "billing")
    audits.append(yaml.safe_load((d / "STATE.yaml").read_text())["next_action"])
    check("all computed audit scopes are renderable", {action["scope"] for action in audits} == {"plan", "work", "phase", "integration"}, repr(audits))


def case_integration_next_action_guards(root: Path) -> None:
    """status must never advertise an integration action the mutation guard would reject."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"

    # Preplanned ready integration WORK cannot starve an unverified phase's audit.
    dump(d / "STATE.yaml", state({"01": phase("audit", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))
    dump(d / "work/integration.yaml", work("integration", item("INT-I01")))
    out = devflow(root, "status", "billing").stdout
    check(
        "preplanned integration WORK does not preempt phase audit",
        "next.command: audit" in out and "next.phase: 01" in out and "next.work_item: INT-I01" not in out,
        out,
    )

    # Blocked integration WORK projects a human decision, never an integration audit.
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))
    dump(d / "work/integration.yaml", work("integration", item("INT-I01", status="blocked", block_reason="waiting")))
    out = devflow(root, "status", "billing").stdout
    check(
        "blocked integration WORK asks for a human integration decision",
        "next.role: human" in out and "next.command: decision" in out and "next.scope: integration" in out,
        out,
    )
    check("blocked integration WORK does not project an integration audit", "next.command: audit" not in out, out)

    # An unresolved project decision precedes any integration run or audit.
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}, unresolved_decisions=["DEC-001"]))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))
    dump(d / "work/integration.yaml", work("integration", item("INT-I01", status="done", commands=["true -> ok"])))
    out = devflow(root, "status", "billing").stdout
    check(
        "unresolved project decision precedes any integration run or audit",
        "next.role: human" in out
        and "next.command: decision" in out
        and "next.scope: project" in out
        and "next.command: audit" not in out
        and "next.command: run" not in out,
        out,
    )


def case_plan_review_gate(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "critical")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.2.0"
    dump(d / "STATE.yaml", state_doc)
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    out = devflow(root, "status", "billing").stdout
    check("critical risk gates on a plan audit before any run", "next.command: audit" in out and "next.scope: plan" in out, out)

    (d / "audits").mkdir(exist_ok=True)
    (d / "audits/plan.md").write_text("# plan audit\n")
    devflow(root, "plan-review", "set", "billing", "verified")
    out = devflow(root, "status", "billing").stdout
    check("a legacy verified plan review releases the gate", "next.command: run" in out, out)


def high_done(item_id: str, **over: Any) -> dict[str, Any]:
    return item(item_id, risk_level="high", status=over.pop("status", "done"), commands=["true -> ok"], premise_checks=["confirm current HEAD"], **over)


def case_high_risk_dependency_is_gated(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", high_done("A"), item("B", dependencies=["A"])))

    out = devflow(root, "status", "billing").stdout
    check("high-risk done item asks for a work audit before its dependent", "next.command: audit" in out and "next.scope: work" in out and "next.work_item: A" in out, out)
    check("gated high-risk dependency does not hand out B", "next.work_item: B" not in out, out)


def case_verified_review_releases_dependent(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", high_done("A"), item("B", dependencies=["A"])))
    (d / "audits/work").mkdir(parents=True)
    (d / "audits/work/A.md").write_text("# A audit\n")

    reviewed = devflow(root, "work", "review", "billing", "A", "verified")
    out = devflow(root, "status", "billing").stdout
    check("verified work review succeeds with its audit artifact", reviewed.returncode == 0, reviewed.stdout + reviewed.stderr)
    check("verified work review releases dependent B", "next.command: run" in out and "next.work_item: B" in out, out)


def case_medium_dependency_keeps_old_behavior(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"]), item("B", dependencies=["A"])))

    out = devflow(root, "status", "billing").stdout
    check("medium done dependency immediately releases B", "next.command: run" in out and "next.work_item: B" in out, out)


def case_remediation_returns_to_work_closure_audit(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work(
        "01", high_done("A"),
        item("R1", kind="remediation", origin={"requirements": [], "findings": ["F-A-001"], "plan_items": []}),
        item("B", dependencies=["A"]),
    ))
    (d / "audits/work").mkdir(parents=True)
    (d / "audits/work/A.md").write_text("# A audit\n")

    reviewed = devflow(root, "work", "review", "billing", "A", "remediation", "--remediation-work", "R1")
    out = devflow(root, "status", "billing").stdout
    check("review remediation transition accepts traced remediation WORK", reviewed.returncode == 0, reviewed.stdout + reviewed.stderr)
    check("remediation WORK runs before closure audit", "next.command: run" in out and "next.work_item: R1" in out, out)

    devflow(root, "work", "start", "billing", "R1")
    devflow(root, "work", "done", "billing", "R1", "--command", "true -> ok")
    out = devflow(root, "status", "billing").stdout
    check("completed remediation returns to original work closure audit", "next.command: audit" in out and "next.scope: work" in out and "next.mode: closure" in out and "next.work_item: A" in out, out)

    verified = devflow(root, "work", "review", "billing", "A", "verified")
    out = devflow(root, "status", "billing").stdout
    check("closure verification releases original dependent", verified.returncode == 0 and "next.work_item: B" in out, verified.stdout + verified.stderr + out)


def case_work_closure_audit_reports_work_audit(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    d = root / "docs/domains/billing"
    fill_audit_remediation_contract(d)
    int_a = v2_item("INT-A")
    int_a.update(
        kind="remediation",
        origin={"requirements": [], "findings": ["F-01"], "plan_items": []},
        risk={"level": "high", "axes": ["correctness"]},
        premise_checks=["Confirm F-01 still reproduces at current HEAD."],
    )
    dump(d / "work/integration.yaml", work_v2("integration", int_a))
    f01 = audit_finding(
        "F-01",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The integration defect blocks release.",
        disposition={"action": "remediation_work", "work_ids": ["INT-A"], "decision_ids": []},
    )
    write_audit(d / "audits/integration.md", audit_metadata(d, verdict="fail", findings=[f01]))
    devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    devflow(root, "work", "start", "billing", "INT-A")
    devflow(root, "work", "done", "billing", "INT-A", "--command", "true -> passed")

    int_r2 = v2_item("INT-R2")
    int_r2.update(kind="remediation", origin={"requirements": [], "findings": ["F-02"], "plan_items": []})
    integration_work = yaml.safe_load((d / "work/integration.yaml").read_text(encoding="utf-8"))
    integration_work["items"].append(int_r2)
    dump(d / "work/integration.yaml", integration_work)
    f02 = audit_finding(
        "F-02",
        classification="CONFIRMED",
        severity="blocker",
        severity_reason="The first remediation left a second defect.",
        disposition={"action": "remediation_work", "work_ids": ["INT-R2"], "decision_ids": []},
    )
    write_audit(d / "audits/work/INT-A.md", audit_metadata(d, scope="work", verdict="fail", findings=[f02]))
    devflow(root, "audit", "apply", "billing", "--scope", "work", "--task", "INT-A", "--mode", "initial")
    devflow(root, "work", "start", "billing", "INT-R2")
    devflow(root, "work", "done", "billing", "INT-R2", "--command", "true -> passed")

    out = devflow(root, "status", "billing").stdout
    derived = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "a phaseless work closure audit reports project_status work_audit, not integration_closure",
        "next.command: audit" in out
        and "next.scope: work" in out
        and "next.mode: closure" in out
        and "next.work_item: INT-A" in out
        and derived["project_status"] == "work_audit"
        and derived["next_action"]["scope"] == "work"
        and derived["next_action"]["mode"] == "closure",
        out + repr(derived),
    )
    check(
        "validate accepts the work_audit project_status for a work closure audit",
        devflow(root, "validate", "billing").returncode == 0,
        devflow(root, "validate", "billing").stdout,
    )


def case_remediation_review_invariants(root: Path) -> None:
    """Remediation is a closed unit: no bypass, no self-referential dependency graph."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))

    # Bypass: verified cannot skip a still-open registered remediation.
    dump(d / "work/phase-01.yaml", work(
        "01", high_done("A"),
        item("R1", kind="remediation", origin={"requirements": [], "findings": ["F-A-001"], "plan_items": []}),
        item("B", dependencies=["A"]),
    ))
    (d / "audits/work").mkdir(parents=True)
    (d / "audits/work/A.md").write_text("# A audit\n")
    reg = devflow(root, "work", "review", "billing", "A", "remediation", "--remediation-work", "R1")
    check("remediation registration accepts a traced remediation WORK", reg.returncode == 0, reg.stdout + reg.stderr)

    bypass = devflow(root, "work", "review", "billing", "A", "verified")
    review_status = yaml.safe_load((d / "work/phase-01.yaml").read_text())["items"][0].get("review", {}).get("status")
    check("verified is rejected while remediation is still open", bypass.returncode == 2, bypass.stdout + bypass.stderr)
    check("rejected verified leaves review.status=remediation", review_status == "remediation", repr(review_status))
    started = devflow(root, "work", "start", "billing", "B")
    check("dependent B still cannot start", started.returncode == 2, started.stdout + started.stderr)

    # Direct deadlock: remediation depending on its reviewed WORK is rejected at registration, no mutation.
    dump(d / "work/phase-01.yaml", work(
        "01", high_done("A"),
        item("R1", kind="remediation", dependencies=["A"], origin={"requirements": [], "findings": ["F-A-001"], "plan_items": []}),
    ))
    work_before = (d / "work/phase-01.yaml").read_text()
    direct = devflow(root, "work", "review", "billing", "A", "remediation", "--remediation-work", "R1")
    check("remediation that depends on its reviewed WORK is rejected", direct.returncode == 2 and "R1" in direct.stderr, direct.stdout + direct.stderr)
    check("rejected remediation registration does not mutate WORK", (d / "work/phase-01.yaml").read_text() == work_before, "")

    # Persisted malformed artifact: validate reports the direct dependency-cycle invariant.
    malformed_a = high_done("A", review={"required": True, "status": "remediation", "audit_file": "audits/work/A.md", "remediation_work_ids": ["R1"]})
    dump(d / "work/phase-01.yaml", work(
        "01", malformed_a,
        item("R1", kind="remediation", dependencies=["A"], origin={"requirements": [], "findings": ["F-A-001"], "plan_items": []}),
    ))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects a persisted remediation dependency cycle", "ERROR:" in out and "remediation WORK R1 depends on A" in out, out)

    # Transitive deadlock: R1 -> C -> A must also be rejected.
    dump(d / "work/phase-01.yaml", work(
        "01", malformed_a,
        item("R1", kind="remediation", dependencies=["C"], origin={"requirements": [], "findings": ["F-A-001"], "plan_items": []}),
        item("C", dependencies=["A"]),
    ))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects a transitive remediation dependency path to the reviewed WORK", "ERROR:" in out and "remediation WORK R1 depends on A" in out, out)


def case_legacy_high_risk_work_is_gated_without_mutation(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    work_path = d / "work/phase-01.yaml"
    dump(work_path, work("01", high_done("A"), item("B", dependencies=["A"])))
    before = work_path.read_text()

    out = devflow(root, "status", "billing").stdout
    check("legacy high-risk done item is pending work review", "next.command: audit" in out and "next.scope: work" in out and "next.work_item: A" in out, out)
    check("status does not write normalized legacy review metadata", before == work_path.read_text(), work_path.read_text())


def case_review_metadata_validation(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    malformed = [
        ("unknown review status", {"required": True, "status": "unknown", "audit_file": "audits/work/A.md", "remediation_work_ids": []}),
        ("required skipped review", {"required": True, "status": "skipped", "audit_file": "audits/work/A.md", "remediation_work_ids": []}),
        ("empty remediation review", {"required": True, "status": "remediation", "audit_file": "audits/work/A.md", "remediation_work_ids": []}),
        ("unknown remediation WORK", {"required": True, "status": "remediation", "audit_file": "audits/work/A.md", "remediation_work_ids": ["NOPE"]}),
        ("verified unfinished review", {"required": True, "status": "verified", "audit_file": "audits/work/A.md", "remediation_work_ids": []}),
    ]
    for name, review in malformed:
        status = "ready" if name == "verified unfinished review" else "done"
        dump(d / "work/phase-01.yaml", work("01", high_done("A", status=status, review=review)))
        out = devflow(root, "validate", "billing").stdout
        check(f"validate rejects {name}", "ERROR:" in out, out)


def case_done_rejects_blocked_work(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    work_path = d / "work/phase-01.yaml"
    dump(work_path, work("01", item("A", status="blocked", commands=["true -> ok"])))
    before = work_path.read_text()

    out = devflow(root, "work", "done", "billing", "A")
    check("blocked to done is rejected", out.returncode == 2 and "status=in_progress" in out.stderr, out.stdout + out.stderr)
    check("blocked to done does not rewrite WORK", work_path.read_text() == before, work_path.read_text())


def case_done_marks_high_risk_review_pending(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", risk_level="high", premise_checks=["confirm HEAD"])))

    devflow(root, "work", "start", "billing", "A")
    out = devflow(root, "work", "done", "billing", "A", "--command", "true -> ok")
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    review = doc["items"][0].get("review", {})
    check("high-risk completion records pending review", out.returncode == 0 and review.get("required") is True and review.get("status") == "pending", out.stdout + out.stderr + repr(review))


def case_start_rejects_unfinished_dependency(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    work_path = d / "work/phase-01.yaml"
    dump(work_path, work("01", item("A"), item("B", dependencies=["A"])))
    before = work_path.read_text()

    out = devflow(root, "work", "start", "billing", "B")
    check("unfinished dependency prevents start", out.returncode == 2 and "dependency A" in out.stderr, out.stdout + out.stderr)
    check("dependency refusal does not rewrite WORK", work_path.read_text() == before, work_path.read_text())


def case_start_rejects_pending_high_risk_review(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", high_done("A"), item("B", dependencies=["A"])))

    out = devflow(root, "work", "start", "billing", "B")
    check("pending high-risk review prevents dependent start", out.returncode == 2 and "requires review" in out.stderr, out.stdout + out.stderr)


def case_start_rejects_unresolved_decision(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, unresolved_decisions=["DEC-004"]))
    dump(d / "work/phase-01.yaml", work("01", item("A", decision_dependencies=["DEC-004"])))

    out = devflow(root, "work", "start", "billing", "A")
    check("unresolved decision prevents start", out.returncode == 2 and "DEC-004" in out.stderr, out.stdout + out.stderr)


def case_start_rejects_verified_phase(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A")))

    out = devflow(root, "work", "start", "billing", "A")
    check("verified phase prevents start", out.returncode == 2 and "phase 01 is already verified" in out.stderr, out.stdout + out.stderr)


def case_start_rejects_pending_plan_review(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, plan_review={"required": True, "status": "pending"}))
    dump(d / "work/phase-01.yaml", work("01", item("A")))

    out = devflow(root, "work", "start", "billing", "A")
    check("required pending plan review prevents start", out.returncode == 2 and "plan review is pending" in out.stderr, out.stdout + out.stderr)


def case_plan_review_rejects_required_skip(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    before = (d / "STATE.yaml").read_text()

    out = devflow(root, "plan-review", "set", "billing", "skipped")
    check("required plan review cannot be skipped", out.returncode == 2 and "required" in out.stderr, out.stdout + out.stderr)
    check("rejected plan-review skip does not rewrite STATE", (d / "STATE.yaml").read_text() == before, (d / "STATE.yaml").read_text())


def case_plan_review_requires_audit_artifact(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.2.0"
    dump(d / "STATE.yaml", state_doc)
    out = devflow(root, "plan-review", "set", "billing", "verified")

    check("legacy plan review cannot verify without audit artifact", out.returncode == 2 and "plan audit artifact" in out.stderr, out.stdout + out.stderr)
    check("plan-review guard defaults legacy audit path", not (d / "audits/plan.md").exists())


def case_phase_verification_rejects_open_work(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state({"01": phase_doc}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("A")))
    (d / "audits/phase-01.md").write_text("# phase audit\n")

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification rejects open WORK", out.returncode == 2 and "open WORK" in out.stderr, out.stdout + out.stderr)


def case_phase_verification_rejects_pending_review(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state({"01": phase_doc}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", high_done("A")))
    (d / "audits/phase-01.md").write_text("# phase audit\n")

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification rejects pending high-risk review", out.returncode == 2 and "review" in out.stderr, out.stdout + out.stderr)


def case_phase_verification_requires_diff_range(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("audit", "01")}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))
    (d / "audits/phase-01.md").write_text("# phase audit\n")

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification requires diff range", out.returncode == 2 and "diff_range" in out.stderr, out.stdout + out.stderr)


def case_phase_verification_requires_audit_artifact(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state({"01": phase_doc}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification requires audit artifact", out.returncode == 2 and "phase audit artifact" in out.stderr, out.stdout + out.stderr)


def case_integration_verification_rejects_unverified_phase(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("audit", "01")}, protocol_version="1.2.0"))

    out = devflow(root, "integration", "set", "billing", "verified")
    check("integration verification rejects unverified phase", out.returncode == 2 and "01" in out.stderr, out.stdout + out.stderr)


def case_integration_verification_requires_audit_artifact(root: Path) -> None:
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}, protocol_version="1.2.0"))

    out = devflow(root, "integration", "set", "billing", "verified")
    check("integration verification requires audit artifact", out.returncode == 2 and "integration audit artifact" in out.stderr, out.stdout + out.stderr)


def case_rejected_phase_transition_does_not_mutate_state(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("audit", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))
    before = (d / "STATE.yaml").read_text()

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("rejected phase transition returns CLI error", out.returncode == 2, out.stdout + out.stderr)
    check("rejected phase transition does not mutate STATE", (d / "STATE.yaml").read_text() == before, (d / "STATE.yaml").read_text())


def case_work_block_requires_active_status_and_reason(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"]), item("B")))

    finished = devflow(root, "work", "block", "billing", "A", "--reason", "stop")
    empty = devflow(root, "work", "block", "billing", "B", "--reason", "   ")
    check("work block rejects terminal WORK", finished.returncode == 2 and "cannot block" in finished.stderr, finished.stdout + finished.stderr)
    check("work block requires trimmed reason", empty.returncode == 2 and "reason" in empty.stderr, empty.stdout + empty.stderr)


def case_verification_is_gated_by_validation(root: Path) -> None:
    """A structurally invalid manifest used to reach project completion untouched."""
    devflow(root, "init", "billing")
    legacy_config(root, "1.2.0")
    d = root / "docs/domains/billing"
    broken = item("P01-I01", status="done", commands=["true -> ok"])
    broken.pop("stop_conditions")
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, protocol_version="1.2.0"))
    dump(d / "work/phase-01.yaml", work("01", broken))
    (d / "audits/phase-01.md").parent.mkdir(parents=True, exist_ok=True)
    (d / "audits/phase-01.md").write_text("# phase audit\n")
    derived = yaml.safe_load((d / "STATE.yaml").read_text())
    derived["phases"]["01"]["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", derived)

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check(
        "phase verification refuses a domain that fails validation",
        out.returncode == 2 and "validation:" in out.stderr and "stop_conditions" in out.stderr,
        out.stdout + out.stderr,
    )

    # The same guard must hold at the integration boundary.
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}, protocol_version="1.2.0"))
    (d / "audits/integration.md").write_text("# integration audit\n")
    out = devflow(root, "integration", "set", "billing", "verified")
    check(
        "integration verification refuses a domain that fails validation",
        out.returncode == 2 and "validation:" in out.stderr,
        out.stdout + out.stderr,
    )

    # A clean domain still passes both gates.
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> ok"])))
    out = devflow(root, "integration", "set", "billing", "verified")
    check("a valid domain still verifies", out.returncode == 0, out.stdout + out.stderr)


def case_protocol_version_is_enforced(root: Path) -> None:
    devflow(root, "init", "billing")
    p = root / "docs/domains/billing/STATE.yaml"

    invalid_versions = ["", "1.2", "1.2.foo", "1.2.0.0", "v1.2.0"]
    for value in invalid_versions:
        doc = yaml.safe_load(p.read_text())
        doc["protocol_version"] = value
        dump(p, doc)
        out = devflow(root, "validate", "billing")
        check(
            f"validate rejects malformed protocol_version {value!r}",
            out.returncode != 0 and "Invalid protocol_version" in out.stdout,
            out.stdout + out.stderr,
        )

    doc = yaml.safe_load(p.read_text())
    doc["protocol_version"] = "2.0.0"
    dump(p, doc)
    out = devflow(root, "validate", "billing")
    check(
        "validate rejects unsupported protocol major version",
        out.returncode != 0 and "Unsupported protocol_version" in out.stdout,
        out.stdout + out.stderr,
    )

    doc = yaml.safe_load(p.read_text())
    doc["protocol_version"] = "1.99.0"
    dump(p, doc)
    out = devflow(root, "validate", "billing")
    check(
        "validate warns about a newer minor protocol version without failing",
        out.returncode == 0 and "newer than this runtime" in out.stdout,
        out.stdout + out.stderr,
    )

    # The audit-apply gate threshold is 1.3.0, not the runtime version. A genuine 1.3.0 project
    # (config and STATE both 1.3.0) still cannot use a legacy verified transition under a 1.8.0
    # runtime.
    devflow(root, "init", "legacy13")
    legacy_config(root, "1.3.0")
    ld = root / "docs/domains/legacy13"
    doc = yaml.safe_load((ld / "STATE.yaml").read_text(encoding="utf-8"))
    doc["protocol_version"] = "1.3.0"
    doc["phases"] = {"01": phase("audit", "01")}
    dump(ld / "STATE.yaml", doc)
    gated = devflow(root, "phase", "set", "legacy13", "01", "verified")
    check(
        "a 1.3.0 STATE still requires audit apply under the 1.8.0 runtime",
        gated.returncode == 2 and "protocol 1.3+ requires devflow audit apply" in gated.stderr,
        gated.stdout + gated.stderr,
    )


def case_state_protocol_downgrade_cannot_disable_the_audit_gate(root: Path) -> None:
    def verifiable_phase(domain: str) -> Path:
        devflow(root, "init", domain)
        dd = root / f"docs/domains/{domain}"
        dump(dd / "STATE.yaml", state({"01": phase("executing", "01")}))
        dump(dd / "work/phase-01.yaml", work("01", item("P01-I01")))
        devflow(root, "work", "start", domain, "P01-I01")
        devflow(root, "work", "done", domain, "P01-I01", "--command", "true -> ok")
        state_doc = yaml.safe_load((dd / "STATE.yaml").read_text(encoding="utf-8"))
        state_doc["phases"]["01"]["diff_range"] = "HEAD^..HEAD"
        dump(dd / "STATE.yaml", state_doc)
        (dd / "audits/phase-01.md").write_text("# phase audit\n")
        return dd

    # config 1.8.0 (from init), STATE hand-downgraded to 1.2.0
    d = verifiable_phase("billing")
    high = high_done("P01-I02")
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01"), high))
    (d / "audits/work").mkdir(parents=True, exist_ok=True)
    (d / "audits/work/P01-I02.md").write_text("# work audit\n")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["protocol_version"] = "1.2.0"
    dump(d / "STATE.yaml", state_doc)
    before_state = (d / "STATE.yaml").read_bytes()

    phase_v = devflow(root, "phase", "set", "billing", "01", "verified")
    integ_v = devflow(root, "integration", "set", "billing", "verified")
    plan_v = devflow(root, "plan-review", "set", "billing", "verified")
    work_v = devflow(root, "work", "review", "billing", "P01-I02", "verified")
    validated = devflow(root, "validate", "billing")
    check(
        "AC-01/AC-02: a STATE downgrade under a 1.8.0 config cannot re-enable any legacy verified transition",
        all(
            out.returncode == 2 and "protocol 1.3+ requires devflow audit apply" in out.stderr
            for out in (phase_v, integ_v, plan_v, work_v)
        )
        and (d / "STATE.yaml").read_bytes() == before_state,
        "".join(o.stdout + o.stderr for o in (phase_v, integ_v, plan_v, work_v)),
    )
    check(
        "AC-03: validate reports the STATE-older-than-config protocol downgrade",
        validated.returncode == 1
        and "STATE protocol_version 1.2.0 is older than the project's .devflow/config.yaml protocol_version 1.8.0" in validated.stdout,
        validated.stdout + validated.stderr,
    )

    # AC-07: the F-003 reproduction, a narrative phase audit plus a STATE downgrade
    narrative = verifiable_phase("shipping")
    (narrative / "audits/phase-01.md").write_text("# Phase audit\n\nNarrative only, no front matter.\n")
    sd = yaml.safe_load((narrative / "STATE.yaml").read_text(encoding="utf-8"))
    sd["protocol_version"] = "1.2.0"
    dump(narrative / "STATE.yaml", sd)
    f003 = devflow(root, "phase", "set", "shipping", "01", "verified")
    check(
        "AC-07: a narrative phase audit plus a STATE downgrade no longer verifies the phase",
        f003.returncode == 2 and "protocol 1.3+ requires devflow audit apply" in f003.stderr,
        f003.stdout + f003.stderr,
    )

    # AC-04: no .devflow/config.yaml at all, STATE 1.2.0, legacy transition still works
    noconfig = verifiable_phase("logistics")
    (root / ".devflow/config.yaml").unlink()
    sd = yaml.safe_load((noconfig / "STATE.yaml").read_text(encoding="utf-8"))
    sd["protocol_version"] = "1.2.0"
    dump(noconfig / "STATE.yaml", sd)
    ac04_validate = devflow(root, "validate", "logistics")
    ac04 = devflow(root, "phase", "set", "logistics", "01", "verified")
    after = yaml.safe_load((noconfig / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "AC-04: with no config file and a 1.2.0 STATE the legacy verified transition still applies",
        ac04_validate.returncode == 0
        and ac04.returncode == 0
        and after["phases"]["01"]["status"] == "verified",
        ac04_validate.stdout + ac04_validate.stderr + ac04.stdout + ac04.stderr + repr(after),
    )

    # AC-05: config genuinely records 1.2.0 and STATE records 1.2.0, legacy path intact
    legacy = verifiable_phase("procurement")
    legacy_config(root, "1.2.0")
    sd = yaml.safe_load((legacy / "STATE.yaml").read_text(encoding="utf-8"))
    sd["protocol_version"] = "1.2.0"
    dump(legacy / "STATE.yaml", sd)
    ac05_validate = devflow(root, "validate", "procurement")
    ac05 = devflow(root, "phase", "set", "procurement", "01", "verified")
    after = yaml.safe_load((legacy / "STATE.yaml").read_text(encoding="utf-8"))
    check(
        "AC-05: a genuine 1.2.0 config plus 1.2.0 STATE keeps the legacy verified transition and reports no protocol error",
        ac05_validate.returncode == 0
        and "older than the project's" not in ac05_validate.stdout
        and ac05.returncode == 0
        and after["phases"]["01"]["status"] == "verified",
        ac05_validate.stdout + ac05_validate.stderr + ac05.stdout + ac05.stderr + repr(after),
    )


def case_config_protocol_version_is_checked(root: Path) -> None:
    out = devflow(root, "init", "billing")
    check("init succeeds for config protocol compatibility test", out.returncode == 0, out.stdout + out.stderr)

    config_path = root / ".devflow/config.yaml"
    state_path = root / "docs/domains/billing/STATE.yaml"
    config = yaml.safe_load(config_path.read_text())
    state_doc = yaml.safe_load(state_path.read_text())
    state_template = yaml.safe_load((PLUGIN / "core/templates/STATE.yaml").read_text())
    check(
        "new init and the STATE template record the current runtime protocol",
        config.get("protocol_version") == "1.8.0"
        and state_doc.get("protocol_version") == "1.8.0"
        and state_template.get("protocol_version") == "1.8.0",
        repr(config) + repr(state_doc) + repr(state_template),
    )

    for value, expected in [("1.2", "Invalid config protocol_version"), ("2.0.0", "Unsupported config protocol_version")]:
        config["protocol_version"] = value
        dump(config_path, config)
        invalid = devflow(root, "validate", "billing")
        check(
            f"validate rejects config protocol_version {value!r}",
            invalid.returncode == 1 and expected in invalid.stdout,
            invalid.stdout + invalid.stderr,
        )

    config["protocol_version"] = "1.1.0"
    dump(config_path, config)
    older = devflow(root, "validate", "billing")
    check(
        "validate reads an older same-major config protocol",
        older.returncode == 0 and "Unsupported config protocol_version" not in older.stdout,
        older.stdout + older.stderr,
    )

    config["protocol_version"] = "1.8.0"
    dump(config_path, config)
    human = devflow(root, "status", "billing")
    machine = devflow(root, "status", "billing", "--json")
    report = json.loads(machine.stdout) if machine.returncode == 0 else {}
    expected_versions = {"runtime": "1.8.0", "config": "1.8.0", "state": "1.8.0", "effective": "1.8.0"}
    check(
        "human and JSON status expose runtime, config, state, and effective protocol versions",
        human.returncode == 0
        and all(f"protocol.{key}: {value}" in human.stdout for key, value in expected_versions.items())
        and machine.returncode == 0
        and report.get("protocol_versions") == expected_versions,
        human.stdout + human.stderr + machine.stdout + machine.stderr,
    )


def case_newer_config_protocol_blocks_mutation(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    devflow(root, "status", "billing")
    config_path = root / ".devflow/config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["protocol_version"] = "1.99.0"
    dump(config_path, config)
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for base in [root / ".devflow", root / "docs/domains"]
        for path in base.rglob("*")
        if path.is_file()
    }

    validated = devflow(root, "validate", "billing")
    status = devflow(root, "status", "billing")
    mutations = [
        ("init", "shipping"),
        ("work", "start", "billing", "P01-I01"),
        ("work", "done", "billing", "P01-I01", "--command", "true -> passed"),
        ("work", "block", "billing", "P01-I01", "--reason", "blocked"),
        ("work", "review", "billing", "P01-I01", "blocked"),
        ("phase", "set", "billing", "01", "remediation"),
        ("phase", "ref", "billing", "01", "--base", "HEAD", "--head", "HEAD"),
        ("plan-review", "set", "billing", "pending"),
        ("integration", "set", "billing", "audit"),
        ("decision", "add", "billing", "DEC-001"),
        ("audit", "apply", "billing", "--scope", "integration", "--mode", "initial"),
    ]
    results = [devflow(root, *command) for command in mutations]
    after = {
        str(path.relative_to(root)): path.read_bytes()
        for base in [root / ".devflow", root / "docs/domains"]
        for path in base.rglob("*")
        if path.is_file()
    }
    check(
        "newer same-major config permits read-only status and validate with a warning",
        validated.returncode == 0
        and "newer than this runtime" in validated.stdout
        and status.returncode == 0
        and "protocol.config: 1.99.0" in status.stdout,
        validated.stdout + validated.stderr + status.stdout + status.stderr,
    )
    check(
        "newer same-major config blocks every artifact mutation before writing",
        all(result.returncode == 2 and "newer config protocol" in result.stderr for result in results)
        and before == after
        and not (root / "docs/domains/shipping").exists(),
        "\n".join(result.stdout + result.stderr for result in results)
        + f"\nartifacts_unchanged={before == after}",
    )


def case_finding_requires_severity_reason(root: Path) -> None:
    d = audit_remediation_fixture(root)
    finding = audit_finding("F-01")
    finding.pop("severity_reason")
    write_audit(d / "audits/integration.md", audit_metadata(d, findings=[finding]))
    missing = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "audit apply rejects a finding without a nonblank severity_reason",
        missing.returncode == 2 and "severity_reason" in missing.stderr,
        missing.stdout + missing.stderr,
    )

    fake_plugin = root / "fake-plugin-severity-anchor"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    schema_path = fake_plugin / "core/schemas/finding.schema.yaml"
    schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema_doc["required"].remove("severity_reason")
    schema_doc["properties"].pop("severity_reason")
    (schema_doc.get("contract") or {}).pop("required_fields", None)
    dump(schema_path, schema_doc)
    runtime = load_runtime_module()
    before = (d / "STATE.yaml").read_bytes()
    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        weakened = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    check(
        "finding schema trust anchor protects the severity_reason requirement",
        weakened.returncode == 2
        and "finding schema" in weakened.stderr.lower()
        and "severity_reason" in weakened.stderr
        and (d / "STATE.yaml").read_bytes() == before,
        weakened.stdout + weakened.stderr,
    )

    rendered = devflow(root, "render", "audit", "billing", "--scope", "integration", "--mode", "initial")
    required_guidance = [
        "trigger conditions",
        "affected users or systems",
        "current defenses",
        "residual impact",
        "why the selected severity applies",
        "Finding severity is separate from WORK risk level",
    ]
    check(
        "audit packet carries the evidence-backed severity calibration contract",
        rendered.returncode == 0 and all(text in rendered.stdout for text in required_guidance),
        rendered.stdout + rendered.stderr,
    )


def case_finding_schema_trust_anchor_requires_severity_reason_string(root: Path) -> None:
    d = audit_remediation_fixture(root)
    fake_plugin = root / "fake-plugin-severity-shape"
    shutil.copytree(PLUGIN / "core", fake_plugin / "core")
    schema_path = fake_plugin / "core/schemas/finding.schema.yaml"
    schema_doc = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema_doc["properties"]["severity_reason"] = {"type": "list", "items": {"type": "string"}}
    dump(schema_path, schema_doc)
    write_audit(
        d / "audits/integration.md",
        audit_metadata(d, findings=[audit_finding("F-01", severity_reason=[])]),
    )
    before = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    runtime = load_runtime_module()

    with mock.patch.object(runtime, "plugin_root", return_value=fake_plugin):
        out = invoke_runtime(root, runtime, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    after = {str(path.relative_to(d)): path.read_bytes() for path in d.rglob("*") if path.is_file()}
    check(
        "finding schema trust anchor requires severity_reason to remain a nonblank string",
        out.returncode == 2
        and "finding schema" in out.stderr.lower()
        and "severity_reason" in out.stderr
        and before == after,
        f"artifacts_unchanged={before == after}\n{out.stdout}{out.stderr}",
    )


def case_phase_entry_schema_fields_are_enforced(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": {"status": "executing"}}))
    out = devflow(root, "validate", "billing")
    check(
        "validate enforces the schema's required phase entry fields",
        out.returncode != 0 and "Phase 01 missing field: work_file" in out.stdout and "audit_file" in out.stdout,
        out.stdout + out.stderr,
    )


def case_phase_commands_refuse_to_invent_a_phase(root: Path) -> None:
    """A mistyped phase number used to enter STATE and block integration forever."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    typo = devflow(root, "phase", "set", "billing", "99", "executing")
    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    check(
        "phase set refuses a phase with no WORK file",
        typo.returncode == 2 and "does not exist" in typo.stderr,
        typo.stdout + typo.stderr,
    )
    check("the refused phase never reached STATE", "99" not in doc["phases"], repr(doc["phases"]))

    ref_typo = devflow(root, "phase", "ref", "billing", "99", "--base", "HEAD", "--head", "HEAD")
    check(
        "phase ref refuses a phase with no WORK file",
        ref_typo.returncode == 2 and "does not exist" in ref_typo.stderr,
        ref_typo.stdout + ref_typo.stderr,
    )

    dump(d / "work/phase-02.yaml", work("02", item("P02-I01")))
    real = devflow(root, "phase", "set", "billing", "02", "executing")
    check("phase set still creates a phase whose WORK file exists", real.returncode == 0, real.stdout + real.stderr)


def case_work_review_order_follows_phase(root: Path) -> None:
    """Review selection must order by phase first, the same way choose_next does."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01"), "02": phase("executing", "02")}))
    dump(d / "work/phase-01.yaml", work("01", high_done("Z-EARLY-PHASE")))
    dump(d / "work/phase-02.yaml", work("02", high_done("A-LATE-PHASE")))

    devflow(root, "status", "billing")
    action = yaml.safe_load((d / "STATE.yaml").read_text())["next_action"]
    check(
        "the earlier phase's review is selected even when its id sorts later",
        action["work_item"] == "Z-EARLY-PHASE" and action["phase"] == "01",
        repr(action),
    )


def case_unknown_work_id_reports_a_clean_error(root: Path) -> None:
    devflow(root, "init", "billing")
    out = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "NOPE")
    check(
        "an unknown WORK id reports its message without KeyError quoting",
        out.returncode == 2 and "DevFlow error: Unknown WORK item: NOPE" in out.stderr,
        out.stdout + out.stderr,
    )


def case_peer_skill_composition_contract(root: Path) -> None:
    """0.4.0 peer composition must stay optional documentation, never lifecycle coupling."""
    protocol = PLUGIN / "core/protocol/skill-composition.md"
    check("skill-composition protocol exists", protocol.is_file())
    # Collapse wrapping so a stable sentence is matched regardless of where it breaks lines.
    text = " ".join(protocol.read_text(encoding="utf-8").split())
    for phrase in [
        "Superpowers",
        "Ponytail",
        "General peer execution disciplines are optional.",
        "Ordinary DevFlow lifecycle commands remain usable when an optional peer plugin is absent.",
        "They do not own lifecycle transitions.",
        "Do not automatically enable Ponytail or change its mode.",
        "Do not create separate Ponytail review artifacts.",
        "Missing optional peer disciplines never block ordinary DevFlow execution.",
    ]:
        check(f"skill-composition states: {phrase!r}", phrase in text, text)

    plan_skill = " ".join((PLUGIN / "skills/plan/SKILL.md").read_text(encoding="utf-8").split())
    for phrase in ["core/protocol/skill-composition.md", "planning lens", "DevFlow owns PLAN and WORK decomposition."]:
        check(f"plan skill states: {phrase!r}", phrase in plan_skill, plan_skill)
    check("plan skill keeps Ponytail reuse/minimalism framing", "reuse" in plan_skill and "Ponytail" in plan_skill, plan_skill)

    run_skill = " ".join((PLUGIN / "skills/run/SKILL.md").read_text(encoding="utf-8").split())
    for phrase in [
        "core/protocol/skill-composition.md",
        "test-driven-development",
        "systematic-debugging",
        "verification-before-completion",
        "one selected ready WORK item",
        "Do not change Ponytail mode automatically.",
    ]:
        check(f"run skill states: {phrase!r}", phrase in run_skill, run_skill)
    check("run skill keeps fresh-verification framing", "Fresh verification evidence" in run_skill, run_skill)

    audit_skill = " ".join((PLUGIN / "skills/audit/SKILL.md").read_text(encoding="utf-8").split())
    for phrase in [
        "core/protocol/skill-composition.md",
        "Treat every Ponytail observation as a lead.",
        "independently verify it",
        "normal DevFlow AUDIT artifact",
    ]:
        check(f"audit skill states: {phrase!r}", phrase in audit_skill, audit_skill)


def case_no_peer_plugin_lifecycle_state(root: Path) -> None:
    """Peer composition adds no machine-owned state fields to templates, schemas, or config."""
    forbidden = ["superpowers", "ponytail", "ponytail_mode", "peer_skills", "skill_composition"]

    contract_docs = {
        "STATE template": PLUGIN / "core/templates/STATE.yaml",
        "STATE schema": PLUGIN / "core/schemas/state.schema.yaml",
        "WORK schema": PLUGIN / "core/schemas/work.schema.yaml",
    }
    for name, path in contract_docs.items():
        lowered = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            check(f"{name} introduces no {token!r} field", token not in lowered, lowered)

    devflow(root, "init", "billing")
    config = (root / ".devflow/config.yaml").read_text(encoding="utf-8").lower()
    for token in forbidden:
        check(f"generated .devflow config has no {token!r} field", token not in config, config)


def case_lifecycle_runs_without_peer_plugins(root: Path) -> None:
    """A normal DevFlow flow must not assume Superpowers or Ponytail exists."""
    init = devflow(root, "init", "billing")
    check("init succeeds without peer plugins", init.returncode == 0, init.stdout + init.stderr)

    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    rendered = devflow(root, "render", "run", "billing")
    validated = devflow(root, "validate", "billing")
    for name, proc in [("render run", rendered), ("validate", validated)]:
        check(f"{name} succeeds without peer plugins", proc.returncode == 0, proc.stdout + proc.stderr)
        check(f"{name} reports no peer dependency error", "Superpowers" not in proc.stderr and "Ponytail" not in proc.stderr, proc.stderr)


CASES = [
    case_fixtures_are_valid_yaml,
    case_timeout_diagnostics,
    case_init_creates_artifacts,
    case_domain_must_stay_inside_domains_root,
    case_audit_remediation_init_projects_integration_audit,
    case_audit_remediation_init_uses_mode_specific_templates,
    case_legacy_120_domain_defaults_to_delivery,
    case_init_reports_runtime_and_domain_paths,
    case_status_reports_workflow_and_domain_paths,
    case_delivery_render_rejects_out_of_sequence_integration_audit,
    case_render_run_rejects_non_next_work_item,
    case_render_audit_requires_exact_scope_mode_and_target,
    case_audit_remediation_allows_initial_integration_render,
    case_validate_rejects_orphan_phase_manifest,
    case_validate_rejects_phase_document_mismatch,
    case_validate_rejects_placeholder_delivery_contract_before_execution,
    case_render_guard_does_not_mutate_artifacts,
    case_audit_apply_rejects_missing_front_matter,
    case_audit_apply_rejects_malformed_front_matter,
    case_audit_apply_rejects_duplicate_yaml_keys,
    case_state_and_work_reject_duplicate_yaml_keys,
    case_audit_apply_requires_exact_next_action,
    case_audit_apply_validates_verdict_against_findings,
    case_audit_apply_validates_finding_links,
    case_multi_finding_work_requires_aggregation_reason,
    case_multi_finding_work_accepts_coherent_explicit_aggregation,
    case_audit_work_links_are_bidirectional,
    case_decision_finding_cannot_generate_ready_work,
    case_decision_finding_requires_decision_id,
    case_evidence_finding_requires_evidence_work,
    case_documentation_drift_requires_documentation_work,
    case_work_cannot_reference_unknown_audit_finding,
    case_unlinked_work_cannot_reference_unknown_audit_finding,
    case_decision_apply_requires_actual_nonblank_options,
    case_decisions_state_and_work_dependencies_are_bidirectional,
    case_work_audit_rejects_unlinked_unknown_findings_in_same_manifest,
    case_decision_record_stops_at_next_markdown_heading,
    case_decision_placeholder_options_are_invalid,
    case_malformed_canonical_audit_cannot_authenticate_finding,
    case_decision_commonmark_indented_heading_boundary,
    case_audit_apply_failure_is_atomic,
    case_audit_apply_updates_state_and_next_action,
    case_delivery_integration_still_requires_verified_phases,
    case_audit_remediation_verifies_without_fake_phases,
    case_validate_rejects_applied_audit_lifecycle_mismatch,
    case_validate_rechecks_verified_audit_verdict_rubric,
    case_validate_rejects_canonical_audit_path_collision,
    case_delivery_placeholder_contract_requires_trusted_sections,
    case_audit_remediation_required_sections_survive_template_tampering,
    case_validate_closure_reuses_apply_finding_coverage,
    case_closure_cannot_lower_a_recorded_finding_severity,
    case_delivery_markdown_sections_follow_commonmark_boundaries,
    case_audit_remediation_markdown_sections_reject_empty_duplicates,
    case_markdown_sections_ignore_fenced_required_headings,
    case_markdown_body_rejects_empty_ordered_markers,
    case_validate_rejects_duplicate_canonical_finding_ids,
    case_audit_closure_covers_every_prior_finding,
    case_audit_closure_reopens_finding,
    case_audit_remediation_lifecycle_reaches_closure_and_complete,
    case_malformed_closure_metadata_does_not_hide_ready_work,
    case_latest_prior_audit_rejects_duplicate_finding_ids,
    case_audit_remediation_full_lifecycle_without_findings,
    case_audit_remediation_full_lifecycle_with_remediation,
    case_audit_remediation_full_lifecycle_with_decision,
    case_decision_resolve_rejects_open_record_atomically,
    case_audit_remediation_full_lifecycle_with_reopened_finding,
    case_delivery_lifecycle_regression_after_protocol_130,
    case_audit_apply_rolls_back_work_when_state_write_fails,
    case_audit_apply_rollback_survives_atomic_writer_failure,
    case_lifecycle_mutations_are_atomic,
    case_audit_closure_uses_recorded_provenance,
    case_lifecycle_completes_with_gitignored_docs,
    case_recorded_provenance_closure_is_deterministic,
    case_audit_provenance_validation_basis_is_structural,
    case_provenance_write_failure_is_atomic,
    case_legacy_closure_without_provenance,
    case_plan_audit_remediation_reaches_closure,
    case_audit_apply_requires_schema_files,
    case_audit_apply_rejects_corrupt_schema_contracts,
    case_audit_schema_trust_anchor_rejects_removed_verdict_contract,
    case_finding_schema_trust_anchor_rejects_removed_enum_contract,
    case_finding_schema_trust_anchor_requires_work_kind,
    case_audit_remediation_prioritizes_unresolved_decisions,
    case_delivery_integration_prioritizes_unresolved_decisions,
    case_plan_review_remediation_metadata_is_validated,
    case_spec_drift_stop_blocks_every_audit_scope,
    case_stop_blocked_work_review_can_be_reopened,
    case_schema_required_fields_are_enforced,
    case_phase_key_normalization,
    case_phase_set_no_duplicate,
    case_status_is_side_effect_free,
    case_premise_checks_required,
    case_evidence_required,
    case_work_v2_requires_unique_acceptance_ids,
    case_work_v2_requires_unique_verification_ids,
    case_verification_coverage_requires_every_acceptance_id,
    case_verification_coverage_rejects_unknown_acceptance_id,
    case_work_v2_rejects_mixed_legacy_shapes,
    case_work_v1_remains_readable,
    case_work_mutations_reject_invalid_work_v2_contract,
    case_work_schema_trust_anchor_rejects_malformed_contract,
    case_render_audit_includes_work_v2_contract,
    case_transfer_enforced,
    case_lifecycle_consistency,
    case_validate_core_rules,
    case_phase_ref,
    case_render_assembles_prompt,
    case_render_context_assembler,
    case_render_context_marks_missing_ids,
    case_audit_scopes_use_their_own_artifacts,
    case_extension_resolution,
    case_marketplace_plugin_version_matches_manifest,
    case_codex_adapter_uses_shared_plugin,
    case_status_reports_inputs,
    case_next_action_carries_work_routing_metadata,
    case_lifecycle_walk,
    case_derived_lifecycle_state,
    case_derived_integration_work_review_state,
    case_derived_blocked_state_and_audit_scopes,
    case_integration_next_action_guards,
    case_plan_review_gate,
    case_high_risk_dependency_is_gated,
    case_verified_review_releases_dependent,
    case_medium_dependency_keeps_old_behavior,
    case_remediation_returns_to_work_closure_audit,
    case_work_closure_audit_reports_work_audit,
    case_remediation_review_invariants,
    case_legacy_high_risk_work_is_gated_without_mutation,
    case_review_metadata_validation,
    case_done_rejects_blocked_work,
    case_done_marks_high_risk_review_pending,
    case_start_rejects_unfinished_dependency,
    case_start_rejects_pending_high_risk_review,
    case_start_rejects_unresolved_decision,
    case_start_rejects_verified_phase,
    case_start_rejects_pending_plan_review,
    case_plan_review_rejects_required_skip,
    case_plan_review_requires_audit_artifact,
    case_phase_verification_rejects_open_work,
    case_phase_verification_rejects_pending_review,
    case_phase_verification_requires_diff_range,
    case_phase_verification_requires_audit_artifact,
    case_integration_verification_rejects_unverified_phase,
    case_integration_verification_requires_audit_artifact,
    case_rejected_phase_transition_does_not_mutate_state,
    case_work_block_requires_active_status_and_reason,
    case_verification_is_gated_by_validation,
    case_protocol_version_is_enforced,
    case_state_protocol_downgrade_cannot_disable_the_audit_gate,
    case_config_protocol_version_is_checked,
    case_newer_config_protocol_blocks_mutation,
    case_finding_requires_severity_reason,
    case_finding_schema_trust_anchor_requires_severity_reason_string,
    case_phase_entry_schema_fields_are_enforced,
    case_phase_commands_refuse_to_invent_a_phase,
    case_work_review_order_follows_phase,
    case_unknown_work_id_reports_a_clean_error,
    case_peer_skill_composition_contract,
    case_no_peer_plugin_lifecycle_state,
    case_lifecycle_runs_without_peer_plugins,
]


def main() -> int:
    for case in CASES:
        print(f"\n{case.__name__}", flush=True)
        root = new_repo()
        try:
            case(root)
        except Exception as exc:  # a crashing case is a failing case
            FAILED.append(case.__name__)
            print(f"  FAIL  {case.__name__} raised {exc!r}", flush=True)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    print(f"\npassed={len(PASSED)} failed={len(FAILED)}")
    for name in FAILED:
        print(f"FAILED: {name}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
