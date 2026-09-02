#!/usr/bin/env python3
"""Self-check for the DevFlow runtime.

No framework. Run it directly:

    python3 tests/test_devflow.py

Each case builds a throwaway git repository, drives the CLI, and asserts on real output.
Fixtures are built as Python objects and dumped with PyYAML, never as indented heredocs, so a
malformed fixture cannot masquerade as a passing assertion.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
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

    dump(d / "work/phase-01.yaml", work("01", item("P01-I03", status="done", kind="documentation")))
    out = devflow(root, "validate", "billing").stdout
    check("documentation items are exempt from evidence.commands", "done without evidence.commands" not in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I04", verification={"commands": ["   "]})))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects whitespace-only verification.commands", "verification.commands must contain a non-empty command" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I05", status="done", commands=["   "])))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects done whose evidence.commands are whitespace only", "done without evidence.commands" in out, out)


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

    out = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01").stdout
    check("render audit inlines the audit core axes", "Code-level design and contract correctness" in out, out[:600])
    check("render audit inlines the merge-base rule", "merge-base --is-ancestor" in out, out[:600])
    check("render audit reports an unset diff range explicitly", "diff_range: <unset" in out, out[:600])
    check("render audit inlines an extension", "Default domain audit extension" in out, out[:600])

    work_out = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01").stdout
    check("render work audit inlines the selected WORK YAML", "work_item: P01-I01" in work_out and "objective for P01-I01" in work_out, work_out[:1200])
    check("render work audit reports evidence and expected artifact", "work_verification_evidence:" in work_out and "audits/work/P01-I01.md" in work_out, work_out[:1200])
    check("render work audit lazily creates its artifact directory", (d / "audits/work").is_dir())

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
    dump(d / "work/phase-01.yaml", work("01", selected))
    dump(d / "work/phase-02.yaml", work("02", item("P02-I01", objective="UNRELATED_PHASE_WORK_BODY")))
    dump(d / "work/integration.yaml", work("integration", item("INT-I01", objective="UNIQUE_INTEGRATION_WORK_BODY")))

    run = devflow(root, "render", "run", "billing", "--task", "P01-I01").stdout
    check("render run includes matching PRD section and nested details", "UNIQUE_REQ_021" in run and "UNIQUE_REQ_021_DETAILS" in run, run)
    check("render run includes matching PLAN section", "UNIQUE_PLAN_P03_02" in run, run)
    check("render run excludes unrelated PRD section", "UNRELATED_REQ_999" not in run, run)
    check("render run excludes unrelated PLAN section", "UNRELATED_PLAN_P09_99" not in run, run)
    check("render run keeps full selected WORK item", "P01-I01" in run and "objective for P01-I01" in run, run)

    plan = devflow(root, "render", "plan", "billing").stdout
    check("render plan includes full approved PRD", "UNIQUE_REQ_021" in plan and "UNRELATED_REQ_999" in plan, plan)

    phase_out = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01").stdout
    check("phase audit includes selected phase WORK", "P01-I01" in phase_out, phase_out)
    check("phase audit does not inline unrelated phase WORK", "UNRELATED_PHASE_WORK_BODY" not in phase_out, phase_out)

    (d / "audits/work").mkdir(parents=True)
    (d / "audits/work/P01-I01.md").write_text("UNIQUE_WORK_CLOSURE_AUDIT\n", encoding="utf-8")
    work_audit = devflow(root, "render", "audit", "billing", "--scope", "work", "--task", "P01-I01", "--mode", "closure").stdout
    check("work audit includes matching origin context and evidence", "UNIQUE_REQ_021" in work_audit and "UNIQUE_PLAN_P03_02" in work_audit and "true -> context evidence" in work_audit, work_audit)
    check("closure work audit includes its existing audit file", "UNIQUE_WORK_CLOSURE_AUDIT" in work_audit, work_audit)

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
    check("work audit requires task", missing_work.returncode != 0 and "requires --task" in missing_work.stderr, missing_work.stdout + missing_work.stderr)

    missing_phase = devflow(root, "render", "audit", "billing", "--scope", "phase")
    check("phase audit requires phase", missing_phase.returncode != 0 and "requires --phase" in missing_phase.stderr, missing_phase.stdout + missing_phase.stderr)

    known_phase = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "01")
    check("phase audit uses normalized phase artifacts", known_phase.returncode == 0 and "work/phase-01.yaml" in known_phase.stdout and "audits/phase-01.md" in known_phase.stdout, known_phase.stdout + known_phase.stderr)

    unknown_phase = devflow(root, "render", "audit", "billing", "--scope", "phase", "--phase", "02")
    check("phase audit rejects unknown phase", unknown_phase.returncode != 0 and "does not exist" in unknown_phase.stderr, unknown_phase.stdout + unknown_phase.stderr)

    integration = devflow(root, "render", "audit", "billing", "--scope", "integration")
    check("integration audit uses integration artifact", integration.returncode == 0 and "audits/integration.md" in integration.stdout, integration.stdout + integration.stderr)

    (d / "audits/plan.md").write_text("# plan audit\n")
    verified = devflow(root, "plan-review", "set", "billing", "verified")
    check("legacy plan review verifies with its default artifact", verified.returncode == 0, verified.stdout + verified.stderr)


def case_extension_resolution(root: Path) -> None:
    devflow(root, "init", "billing")
    d = root / "docs/domains/billing"
    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, extension="billing.example"))
    out = devflow(root, "render", "audit", "billing", "--scope", "integration").stdout
    check("named bundled extension is resolved", "Billing extension example" in out, out[:600])

    override = root / ".devflow/extensions/billing.example.md"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("# Project override\n\nPROJECT_EXTENSION_MARKER\n")
    out = devflow(root, "render", "audit", "billing", "--scope", "integration").stdout
    check("project-local extension outranks the bundled one", "PROJECT_EXTENSION_MARKER" in out, out[:600])

    dump(d / "STATE.yaml", state({"01": phase("executing", "01")}, extension="does-not-exist"))
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
        len(entries) == 1 and entries[0].get("version") == manifest.get("version") == "0.3.0",
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
        "Codex plugin discovers the shared 0.3.0 skills",
        manifest.get("version") == "0.3.0"
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
        "integration work review derives integration audit status",
        derived["project_status"] == "integration_audit" and derived["active_phase"] is None,
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


CASES = [
    case_fixtures_are_valid_yaml,
    case_timeout_diagnostics,
    case_init_creates_artifacts,
    case_schema_required_fields_are_enforced,
    case_phase_key_normalization,
    case_phase_set_no_duplicate,
    case_status_is_side_effect_free,
    case_premise_checks_required,
    case_evidence_required,
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
