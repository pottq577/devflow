#!/usr/bin/env python3
"""Self-check for the DevFlow runtime.

No framework. Run it directly:

    python3 tests/test_devflow.py

Each case builds a throwaway git repository, drives the CLI, and asserts on real output.
Fixtures are built as Python objects and dumped with PyYAML, never as indented heredocs, so a
malformed fixture cannot masquerade as a passing assertion.
"""
from __future__ import annotations

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


def sh(cmd: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
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
        "plan_review": {"required": False, "status": "skipped"},
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


# --- runtime cases ------------------------------------------------------------------

def case_init_creates_artifacts(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "high")
    d = root / "docs/domains/billing"
    for name in ["PRD.md", "PLAN.md", "STATE.yaml", "DECISIONS.md", "PITFALLS.md"]:
        check(f"init creates {name}", (d / name).exists())
    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    check("high risk requires a plan review", doc["plan_review"] == {"required": True, "status": "pending"}, repr(doc.get("plan_review")))


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
    dump(d / "STATE.yaml", state({"5": phase("verified")}))
    devflow(root, "phase", "set", "billing", "5", "remediation")
    doc = yaml.safe_load((d / "STATE.yaml").read_text())
    check("phase set updates in place instead of creating a second entry", list(doc["phases"]) == ["5"], repr(doc["phases"]))
    check("phase set applied the new status", doc["phases"]["5"]["status"] == "remediation", repr(doc["phases"]))

    dump(d / "STATE.yaml", state({"5": phase("verified"), "05": phase("verified")}))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects two raw keys that normalize to one phase", "Duplicate phase entry" in out, out)


def case_status_is_side_effect_free(root: Path) -> None:
    devflow(root, "init", "billing")
    p = root / "docs/domains/billing/STATE.yaml"
    devflow(root, "status", "billing")
    before = p.read_text()
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
    check("work done refuses with no recorded command", refused.returncode != 0, refused.stdout + refused.stderr)
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    check("refused item is not marked done", doc["items"][0]["status"] != "done", repr(doc["items"][0]["status"]))

    ok = devflow(root, "work", "done", "billing", "P01-I01", "--command", "pytest -> 12 passed")
    doc = yaml.safe_load((d / "work/phase-01.yaml").read_text())
    check("work done accepts a recorded command", ok.returncode == 0 and doc["items"][0]["status"] == "done", ok.stdout + ok.stderr)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I02", status="done")))
    out = devflow(root, "validate", "billing").stdout
    check("validate rejects done with empty evidence.commands", "done without evidence.commands" in out, out)

    dump(d / "work/phase-01.yaml", work("01", item("P01-I03", status="done", kind="documentation")))
    out = devflow(root, "validate", "billing").stdout
    check("documentation items are exempt from evidence.commands", "done without evidence.commands" not in out, out)


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

    plan_out = devflow(root, "render", "plan", "billing").stdout
    check("render plan inlines the lifecycle", "DevFlow lifecycle" in plan_out, plan_out[:600])


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

    devflow(root, "phase", "set", "billing", "01", "verified")
    out = devflow(root, "status", "billing").stdout
    check("walk: verified phase moves to the integration audit", "next.scope: integration" in out, out)

    devflow(root, "integration", "set", "billing", "verified")
    out = devflow(root, "status", "billing").stdout
    check("walk: verified integration completes the project", "next.command: complete" in out, out)
    check("walk: validation is clean at the end", devflow(root, "validate", "billing").returncode == 0,
          devflow(root, "validate", "billing").stdout)


def case_plan_review_gate(root: Path) -> None:
    devflow(root, "init", "billing", "--risk", "critical")
    d = root / "docs/domains/billing"
    dump(d / "work/phase-01.yaml", work("01", item("P01-I01")))
    out = devflow(root, "status", "billing").stdout
    check("critical risk gates on a plan audit before any run", "next.command: audit" in out and "next.scope: plan" in out, out)

    devflow(root, "plan-review", "set", "billing", "verified")
    out = devflow(root, "status", "billing").stdout
    check("a verified plan review releases the gate", "next.command: run" in out, out)


CASES = [
    case_fixtures_are_valid_yaml,
    case_init_creates_artifacts,
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
    case_extension_resolution,
    case_status_reports_inputs,
    case_lifecycle_walk,
    case_plan_review_gate,
]


def main() -> int:
    for case in CASES:
        print(f"\n{case.__name__}")
        root = new_repo()
        try:
            case(root)
        except Exception as exc:  # a crashing case is a failing case
            FAILED.append(f"{case.__name__} raised {exc!r}")
            print(f"  FAIL  {case.__name__} raised {exc!r}")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    print(f"\npassed={len(PASSED)} failed={len(FAILED)}")
    for name in FAILED:
        print(f"FAILED: {name}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
