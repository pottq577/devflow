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
    return sh([sys.executable, str(CLI), *args], cwd)


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


def state(phases: dict[str, Any], *, integration: str = "pending", **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "protocol_version": "1.1.0",
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


def audit_remediation_fixture(root: Path) -> Path:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    return root / "docs/domains/billing"


def broken_delivery_fixture(root: Path) -> Path:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
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
    try:
        sh(
            [sys.executable, "-u", "-c", "import sys, time; print('stdout'); print('stderr', file=sys.stderr); time.sleep(5)"],
            root,
            timeout=0.5,
        )
    except RuntimeError as exc:
        diagnostic = str(exc)
        check(
            "timeout diagnostic identifies command, cwd, timeout, stdout, and stderr",
            all(part in diagnostic for part in ["command:", f"cwd: {root}", "0.5 seconds", "stdout: stdout", "stderr: stderr"]),
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
    legacy.pop("workflow_type", None)
    dump(state_file, legacy)
    before = state_file.read_text()
    out = devflow(root, "status", "billing", "--json")
    reported = json.loads(out.stdout) if out.returncode == 0 else {}
    check(
        "legacy protocol 1.2.0 STATE reads as delivery without a migration write",
        reported.get("workflow_type") == "delivery" and state_file.read_text() == before,
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


def case_audit_closure_covers_every_prior_finding(root: Path) -> None:
    d = audit_remediation_fixture(root)
    findings = [audit_finding("F-01"), audit_finding("F-02")]
    write_audit(d / "audits/integration.md", audit_metadata(d, findings=findings))
    commit_paths(root, "record initial integration audit", d / "audits/integration.md")
    devflow(root, "status", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
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
    commit_paths(root, "record initial integration finding", d / "audits/integration.md")
    devflow(root, "status", "billing")
    state_doc = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
    state_doc["integration"]["status"] = "closure"
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
    commit_paths(root, "record initial phase finding", phase_domain / "audits/phase-01.md")
    devflow(root, "status", "shipping")
    phase_state = yaml.safe_load((phase_domain / "STATE.yaml").read_text(encoding="utf-8"))
    phase_state["phases"] = {
        "01": {
            **phase("remediation", "01"),
            "diff_range": "current-head",
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


def case_audit_closure_uses_git_history_for_prior_findings(root: Path) -> None:
    devflow(root, "init", "billing", "--workflow", "audit-remediation")
    devflow(root, "init", "bypass", "--workflow", "audit-remediation")
    devflow(root, "init", "uncommitted", "--workflow", "audit-remediation")
    billing = root / "docs/domains/billing"
    bypass = root / "docs/domains/bypass"
    uncommitted = root / "docs/domains/uncommitted"
    prior = audit_finding("F-01")
    write_audit(billing / "audits/integration.md", audit_metadata(billing, findings=[prior]))
    write_audit(bypass / "audits/integration.md", audit_metadata(bypass, findings=[prior]))
    commit_paths(
        root,
        "record initial audit histories",
        billing / "audits/integration.md",
        bypass / "audits/integration.md",
    )
    for domain, directory in [("billing", billing), ("bypass", bypass)]:
        devflow(root, "status", domain)
        state_doc = yaml.safe_load((directory / "STATE.yaml").read_text(encoding="utf-8"))
        state_doc["integration"]["status"] = "closure"
        dump(directory / "STATE.yaml", state_doc)

    new_finding = audit_finding("F-02")
    resolved = [{"finding_id": "F-01", "outcome": "resolved", "evidence": ["regression passed"], "reopened_as": []}]
    write_audit(
        billing / "audits/integration.md",
        audit_metadata(billing, mode="closure", findings=[prior, new_finding], closure=resolved),
    )
    applied = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "closure")
    check(
        "closure covers prior Git findings without treating a current-only finding as prior",
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
    write_audit(
        uncommitted / "audits/integration.md",
        audit_metadata(uncommitted, mode="closure", findings=[prior], closure=resolved),
    )
    no_history = devflow(root, "audit", "apply", "uncommitted", "--scope", "integration", "--mode", "closure")
    check(
        "closure rejects a canonical audit with no committed initial Git history",
        no_history.returncode == 2 and "no initial Git history" in no_history.stderr,
        no_history.stdout + no_history.stderr,
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
    commit_paths(root, "record initial plan audit", d / "audits/plan.md")
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
        write_audit(directory / "audits/integration.md", audit_metadata(directory))
        domains.append((domain, directory))

    for domain, directory, missing in [
        (*domains[0], "audit"),
        (*domains[1], "finding"),
    ]:
        fake_plugin = root / f"fake-plugin-{missing}"
        shutil.copytree(PLUGIN / "core/schemas", fake_plugin / "core/schemas")
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
        fake_plugin = root / f"fake-plugin-{schema_name}"
        shutil.copytree(PLUGIN / "core/schemas", fake_plugin / "core/schemas")
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
    fake_plugin = root / "fake-plugin-audit-anchor"
    shutil.copytree(PLUGIN / "core/schemas", fake_plugin / "core/schemas")
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
    fake_plugin = root / "fake-plugin-finding-anchor"
    shutil.copytree(PLUGIN / "core/schemas", fake_plugin / "core/schemas")
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
    shutil.copytree(PLUGIN / "core/schemas", fake_plugin / "core/schemas")
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
    commit_paths(root, "record initial plan stop audit", plan_dir / "audits/plan.md")
    devflow(root, "status", "plan-stop")
    plan_state = yaml.safe_load((plan_dir / "STATE.yaml").read_text(encoding="utf-8"))
    plan_state["phases"] = {"01": phase("executing", "01")}
    plan_state["plan_review"].update(status="remediation", remediation_work_ids=["P01-R01"])
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
    }
    remediation = item("P01-R01", status="done", commands=["true -> passed"])
    dump(work_dir / "work/phase-01.yaml", work("01", reviewed, remediation))
    work_state = yaml.safe_load((work_dir / "STATE.yaml").read_text(encoding="utf-8"))
    work_state["phases"] = {"01": phase("executing", "01")}
    dump(work_dir / "STATE.yaml", work_state)
    write_audit(work_dir / "audits/work/P01-I01.md", audit_metadata(work_dir, scope="work", verdict="conditional_pass", findings=[prior]))
    commit_paths(root, "record initial work stop audit", work_dir / "audits/work/P01-I01.md")
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
    phase_state["phases"] = {"01": phase("remediation", "01")}
    dump(phase_dir / "STATE.yaml", phase_state)
    write_audit(phase_dir / "audits/phase-01.md", audit_metadata(phase_dir, scope="phase", verdict="conditional_pass", findings=[prior]))
    commit_paths(root, "record initial phase stop audit", phase_dir / "audits/phase-01.md")
    devflow(root, "status", "phase-stop")
    write_audit(phase_dir / "audits/phase-01.md", audit_metadata(phase_dir, scope="phase", mode="closure", verdict="fail", findings=[prior, stop], closure=closure))
    phase_out = devflow(root, "audit", "apply", "phase-stop", "--scope", "phase", "--phase", "01", "--mode", "closure")

    integration_dir = audit_remediation_fixture(root)
    write_audit(integration_dir / "audits/integration.md", audit_metadata(integration_dir, verdict="conditional_pass", findings=[prior]))
    initial = devflow(root, "audit", "apply", "billing", "--scope", "integration", "--mode", "initial")
    commit_paths(root, "record initial integration stop audit", integration_dir / "audits/integration.md")
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
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc.update({"base_sha": "base", "head_sha": "head", "diff_range": "base...head"})
    legacy_plan_review = {"required": True, "status": "pending"}
    dump(d / "STATE.yaml", state({"01": phase_doc}, plan_review=legacy_plan_review))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))

    plan = devflow(root, "render", "audit", "billing", "--scope", "plan")
    check("plan audit uses plan audit artifact", plan.returncode == 0 and "audits/plan.md" in plan.stdout and "audits/integration.md" not in plan.stdout, plan.stdout + plan.stderr)

    missing_work = devflow(root, "render", "audit", "billing", "--scope", "work")
    check("work audit requires the next WORK target", missing_work.returncode == 2 and not missing_work.stdout and "expected" in missing_work.stderr, missing_work.stdout + missing_work.stderr)

    missing_phase = devflow(root, "render", "audit", "billing", "--scope", "phase")
    check("phase audit requires the next phase target", missing_phase.returncode == 2 and not missing_phase.stdout and "expected" in missing_phase.stderr, missing_phase.stdout + missing_phase.stderr)

    dump(d / "STATE.yaml", state({"01": phase_doc}))
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01", status="done", commands=["true -> ok"])))
    known_phase = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01")
    check("phase audit uses normalized phase artifacts", known_phase.returncode == 0 and "work/phase-01.yaml" in known_phase.stdout and "audits/phase-01.md" in known_phase.stdout, known_phase.stdout + known_phase.stderr)

    unknown_phase = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "02")
    check("phase audit rejects a non-next phase", unknown_phase.returncode == 2 and not unknown_phase.stdout and '"phase": "01"' in unknown_phase.stderr, unknown_phase.stdout + unknown_phase.stderr)

    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))
    integration = devflow(root, "render", "audit", "billing", "--scope", "integration")
    check("integration audit uses integration artifact", integration.returncode == 0 and "audits/integration.md" in integration.stdout, integration.stdout + integration.stderr)

    (d / "audits/plan.md").write_text("# plan audit\n")
    dump(d / "STATE.yaml", state({"01": phase_doc}, plan_review=legacy_plan_review))
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
    marketplace_path = PLUGIN.parents[1] / ".claude-plugin/marketplace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
    entries = [entry for entry in marketplace.get("plugins", []) if entry.get("name") == manifest.get("name")]
    check(
        "marketplace plugin version matches manifest",
        len(entries) == 1 and entries[0].get("version") == manifest.get("version") == "0.4.0",
        repr(entries),
    )


def case_codex_adapter_uses_shared_plugin(root: Path) -> None:
    codex_marketplace = PLUGIN.parents[1] / ".agents/plugins/marketplace.json"
    codex_manifest = PLUGIN / ".codex-plugin/plugin.json"
    marketplace = json.loads(codex_marketplace.read_text(encoding="utf-8"))
    manifest = json.loads(codex_manifest.read_text(encoding="utf-8"))
    entries = [entry for entry in marketplace.get("plugins", []) if entry.get("name") == manifest.get("name")]
    skills_root = PLUGIN / manifest.get("skills", "")
    check(
        "Codex adapter points at the shared DevFlow plugin",
        len(entries) == 1 and entries[0].get("source") == {"source": "local", "path": "./plugins/devflow"},
        repr(entries),
    )
    check(
        "Codex plugin discovers the shared 0.4.0 skills",
        manifest.get("version") == "0.4.0"
        and skills_root.resolve() == (PLUGIN / "skills").resolve()
        and {path.parent.name for path in skills_root.glob("*/SKILL.md")} == {"plan", "run", "audit", "status"},
        repr(manifest),
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


def case_lifecycle_walk(root: Path) -> None:
    """One pass through the lifecycle: run the work, audit the phase, verify, then integration."""
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
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
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
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
    d = root / "docs/domains/billing"
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    out = devflow(root, "status", "billing").stdout
    check("critical risk gates on a plan audit before any run", "next.command: audit" in out and "next.scope: plan" in out, out)

    (d / "audits").mkdir(exist_ok=True)
    (d / "audits/plan.md").write_text("# plan audit\n")
    devflow(root, "plan-review", "set", "billing", "verified")
    out = devflow(root, "status", "billing").stdout
    check("a verified plan review releases the gate", "next.command: run" in out, out)


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
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
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
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
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
    d = root / "docs/domains/billing"
    out = devflow(root, "plan-review", "set", "billing", "verified")

    check("plan review cannot verify without audit artifact", out.returncode == 2 and "plan audit artifact" in out.stderr, out.stdout + out.stderr)
    check("plan-review guard defaults legacy audit path", not (d / "audits/plan.md").exists())


def case_phase_verification_rejects_open_work(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state({"01": phase_doc}))
    dump(d / "work/phase-01.yaml", work("01", item("A")))
    (d / "audits/phase-01.md").write_text("# phase audit\n")

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification rejects open WORK", out.returncode == 2 and "open WORK" in out.stderr, out.stdout + out.stderr)


def case_phase_verification_rejects_pending_review(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state({"01": phase_doc}))
    dump(d / "work/phase-01.yaml", work("01", high_done("A")))
    (d / "audits/phase-01.md").write_text("# phase audit\n")

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification rejects pending high-risk review", out.returncode == 2 and "review" in out.stderr, out.stdout + out.stderr)


def case_phase_verification_requires_diff_range(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("audit", "01")}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))
    (d / "audits/phase-01.md").write_text("# phase audit\n")

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification requires diff range", out.returncode == 2 and "diff_range" in out.stderr, out.stdout + out.stderr)


def case_phase_verification_requires_audit_artifact(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    phase_doc = phase("audit", "01")
    phase_doc["diff_range"] = "HEAD^..HEAD"
    dump(d / "STATE.yaml", state({"01": phase_doc}))
    dump(d / "work/phase-01.yaml", work("01", item("A", status="done", commands=["true -> ok"])))

    out = devflow(root, "phase", "set", "billing", "01", "verified")
    check("phase verification requires audit artifact", out.returncode == 2 and "phase audit artifact" in out.stderr, out.stdout + out.stderr)


def case_integration_verification_rejects_unverified_phase(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("audit", "01")}))

    out = devflow(root, "integration", "set", "billing", "verified")
    check("integration verification rejects unverified phase", out.returncode == 2 and "01" in out.stderr, out.stdout + out.stderr)


def case_integration_verification_requires_audit_artifact(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))

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
    d = root / "docs/domains/billing"
    broken = item("P01-I01", status="done", commands=["true -> ok"])
    broken.pop("stop_conditions")
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}))
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
    dump(d / "STATE.yaml", state({"01": phase("verified", "01")}))
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


def case_state_is_protocol_version_source_of_truth(root: Path) -> None:
    out = devflow(root, "init", "billing")
    check("init succeeds for protocol source test", out.returncode == 0, out.stdout + out.stderr)

    config_path = root / ".devflow/config.yaml"
    state_path = root / "docs/domains/billing/STATE.yaml"

    config = yaml.safe_load(config_path.read_text())
    state_doc = yaml.safe_load(state_path.read_text())

    check(
        "generated config does not duplicate protocol_version",
        "protocol_version" not in config,
        repr(config),
    )
    check(
        "generated STATE owns protocol_version",
        state_doc.get("protocol_version") == "1.2.0",
        repr(state_doc),
    )

    # Legacy projects may still have this obsolete config field.
    # It must not override the domain artifact contract.
    config["protocol_version"] = "9.9.9"
    dump(config_path, config)

    out = devflow(root, "validate", "billing")
    check(
        "legacy config protocol_version does not override STATE",
        out.returncode == 0,
        out.stdout + out.stderr,
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
        "Peer integrations are optional.",
        "DevFlow must remain fully usable when a named peer plugin is absent.",
        "They do not own lifecycle transitions.",
        "Do not automatically enable Ponytail or change its mode.",
        "Do not create separate Ponytail review artifacts.",
        "Missing peer plugins never block DevFlow.",
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
    case_validate_rejects_placeholder_delivery_contract_before_execution,
    case_render_guard_does_not_mutate_artifacts,
    case_audit_apply_rejects_missing_front_matter,
    case_audit_apply_rejects_malformed_front_matter,
    case_audit_apply_rejects_duplicate_yaml_keys,
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
    case_audit_closure_covers_every_prior_finding,
    case_audit_closure_reopens_finding,
    case_audit_remediation_lifecycle_reaches_closure_and_complete,
    case_audit_apply_rolls_back_work_when_state_write_fails,
    case_audit_apply_rollback_survives_atomic_writer_failure,
    case_audit_closure_uses_git_history_for_prior_findings,
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
    case_state_is_protocol_version_source_of_truth,
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
