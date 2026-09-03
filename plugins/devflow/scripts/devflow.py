#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("DevFlow requires PyYAML. Install with: python3 -m pip install PyYAML", file=sys.stderr)
    raise SystemExit(2)

PROTOCOL_VERSION = "1.2.0"
HIGH_RISK = {"high", "critical"}
REQ_PATTERN = re.compile(r"\b(?:REQ|RULE|AC|IDEM|SEC|NFR|DEC)-[A-Z0-9-]+\b", re.I)

PROMPT_PROTOCOLS = {
    "plan": ["authority", "lifecycle", "work-item-contract", "decision-policy"],
    "run": ["authority", "work-item-contract", "risk-policy"],
    "audit": ["authority", "audit-core", "risk-policy", "decision-policy"],
}


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_git(args: list[str], cwd: Path, check: bool = False) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_ok(args: list[str], cwd: Path) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def repo_root() -> Path:
    cwd = Path.cwd().resolve()
    root = run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(root).resolve() if root else cwd


def load_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if data is None else data


def load_schema(name: str) -> dict[str, Any]:
    path = plugin_root() / "core" / "schemas" / f"{name}.schema.yaml"
    data = load_yaml(path, {}) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid DevFlow schema: {path}")
    return data


STATE_SCHEMA = load_schema("state")
WORK_SCHEMA = load_schema("work")
STATE_REQUIRED_FIELDS = STATE_SCHEMA["required"]
PHASE_ENTRY_REQUIRED_FIELDS = STATE_SCHEMA["phase_entry"]["required"]
PROJECT_STATUSES = set(STATE_SCHEMA["project_status"]["allowed"])
PHASE_STATUSES = set(STATE_SCHEMA["phase_status"]["allowed"])
INTEGRATION_STATUSES = set(STATE_SCHEMA["integration_status"]["allowed"])
WORK_REQUIRED_ITEM_FIELDS = WORK_SCHEMA["required_item_fields"]
WORK_STATUSES = set(WORK_SCHEMA["status"]["allowed"])
TERMINAL_STATUSES = set(WORK_SCHEMA["terminal"])
KINDS = set(WORK_SCHEMA["kind"]["allowed"])
RISK_LEVELS = set(WORK_SCHEMA["risk_level"]["allowed"])
REVIEW_STATUSES = set(WORK_SCHEMA.get("review_status", {}).get("allowed", ["skipped", "pending", "remediation", "blocked", "verified"]))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        os.replace(temp_path, path)
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise


def dump_yaml(path: Path, data: Any) -> None:
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000))


def dump_yaml_if_changed(path: Path, data: Any) -> bool:
    """Write only when the rendered YAML differs, so read-only commands stay side-effect free."""
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    atomic_write_text(path, rendered)
    return True


def has_nonblank_string(values: Any) -> bool:
    """True when `values` is a list holding at least one string with non-whitespace content."""
    return isinstance(values, list) and any(
        isinstance(value, str) and bool(value.strip()) for value in values
    )


def runtime_config(root: Path) -> dict[str, Any]:
    cfg_path = root / ".devflow" / "config.yaml"
    cfg = load_yaml(cfg_path, {}) or {}
    cfg.setdefault("domains_root", "docs/domains")
    return cfg


def domain_dir(root: Path, domain: str) -> Path:
    return root / runtime_config(root)["domains_root"] / domain


def state_path(root: Path, domain: str) -> Path:
    return domain_dir(root, domain) / "STATE.yaml"


def current_sha(root: Path) -> str | None:
    value = run_git(["rev-parse", "HEAD"], root)
    return value or None


def short_sha(value: str | None) -> str:
    return value[:12] if value else "<none>"


def read_template(name: str) -> str:
    return (plugin_root() / "core" / "templates" / name).read_text(encoding="utf-8")


def read_protocol(name: str) -> str:
    return (plugin_root() / "core" / "protocol" / f"{name}.md").read_text(encoding="utf-8")


def resolve_extension(root: Path, state: dict[str, Any]) -> Path:
    """Project-local extension wins, then a bundled named extension, then default."""
    name = state.get("extension") or runtime_config(root).get("extension") or "default"
    for candidate in [
        root / ".devflow" / "extensions" / f"{name}.md",
        plugin_root() / "core" / "extensions" / f"{name}.md",
        plugin_root() / "core" / "extensions" / "default.md",
    ]:
        if candidate.exists():
            return candidate
    return plugin_root() / "core" / "extensions" / "default.md"


def ensure_runtime(root: Path) -> None:
    runtime = root / ".devflow"
    runtime.mkdir(parents=True, exist_ok=True)
    cfg = runtime / "config.yaml"
    if not cfg.exists():
        dump_yaml(cfg, {"domains_root": "docs/domains", "extension": "default"})


def phase_key(value: Any) -> str:
    s = str(value)
    return s.zfill(2) if s.isdigit() else s


def normalized_phases(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """STATE phase keys are authored by hand, so normalize before every lookup."""
    out: dict[str, dict[str, Any]] = {}
    for key, value in (state.get("phases", {}) or {}).items():
        out[phase_key(key)] = value or {}
    return out


def raw_phase_key(state: dict[str, Any], key: str) -> str | None:
    for raw in (state.get("phases", {}) or {}):
        if phase_key(raw) == key:
            return raw
    return None


def init_domain(args: argparse.Namespace) -> int:
    root = repo_root()
    ensure_runtime(root)
    d = domain_dir(root, args.domain)
    d.mkdir(parents=True, exist_ok=True)
    (d / "work").mkdir(exist_ok=True)
    (d / "audits").mkdir(exist_ok=True)

    prd = d / "PRD.md"
    if args.prd:
        src = Path(args.prd).expanduser().resolve()
        if not src.exists():
            print(f"PRD source not found: {src}", file=sys.stderr)
            return 2
        if not prd.exists() or args.force:
            prd.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    elif not prd.exists():
        prd.write_text(read_template("PRD.md"), encoding="utf-8")

    for name in ["PLAN.md", "DECISIONS.md", "PITFALLS.md"]:
        target = d / name
        if not target.exists():
            target.write_text(read_template(name), encoding="utf-8")

    state = load_yaml(state_path(root, args.domain), {}) or {}
    state.setdefault("protocol_version", PROTOCOL_VERSION)
    state["domain"] = args.domain
    state.setdefault("risk_profile", args.risk)
    state.setdefault("extension", args.extension)
    state.setdefault("project_status", "planning")
    state.setdefault("baseline_sha", current_sha(root))
    state.setdefault("target_sha", current_sha(root))
    state.setdefault("active_phase", None)
    state.setdefault("plan_review", {"required": args.risk in HIGH_RISK, "status": "pending" if args.risk in HIGH_RISK else "skipped", "audit_file": "audits/plan.md"})
    state.setdefault("phases", {})
    state.setdefault("integration", {"status": "pending", "work_file": "work/integration.yaml", "audit_file": "audits/integration.md"})
    state.setdefault("unresolved_decisions", [])
    state.setdefault("next_action", {"role": "architect", "command": "plan", "scope": "project", "phase": None, "work_item": None})
    dump_yaml(state_path(root, args.domain), state)
    print(f"Initialized DevFlow domain: {d.relative_to(root)}")
    print(f"baseline_sha: {short_sha(state.get('baseline_sha'))}")
    print(f"extension: {resolve_extension(root, state)}")
    return 0


def work_files(d: Path) -> list[Path]:
    work = d / "work"
    return sorted(p for p in work.glob("*.yaml") if p.is_file()) if work.exists() else []


def load_work_index(d: Path):
    docs: dict[Path, dict[str, Any]] = {}
    index: dict[str, tuple[Path, dict[str, Any]]] = {}
    duplicates: list[str] = []
    for path in work_files(d):
        doc = load_yaml(path, {}) or {}
        docs[path] = doc
        for item in doc.get("items", []) or []:
            item_id = str(item.get("id", ""))
            if item_id in index:
                duplicates.append(item_id)
            index[item_id] = (path, item)
    return docs, index, duplicates


def item_phase(path: Path, doc: dict[str, Any]) -> str:
    phase = doc.get("phase")
    if phase is not None:
        return phase_key(phase)
    m = re.search(r"phase[-_]?([0-9]+)", path.stem, re.I)
    return phase_key(m.group(1)) if m else "integration"


def effective_review(item: dict[str, Any]) -> dict[str, Any]:
    """Return policy-defaulted review metadata without changing legacy WORK YAML."""
    raw = item.get("review") if isinstance(item.get("review"), dict) else {}
    high_risk = (item.get("risk") or {}).get("level") in HIGH_RISK
    implemented = item.get("status") in {"done", "in_progress", "ready"}
    required = high_risk and implemented
    if not high_risk and isinstance(raw.get("required"), bool):
        required = raw["required"]
    elif high_risk and implemented and raw.get("required") is True:
        required = True
    status = raw.get("status")
    if status not in REVIEW_STATUSES or (high_risk and implemented and raw and raw.get("required") is not True) or (required and status == "skipped"):
        status = "pending" if required else "skipped"
    return {
        "required": required,
        "status": status,
        "audit_file": raw.get("audit_file") or f"audits/work/{item.get('id')}.md",
        "remediation_work_ids": list(raw.get("remediation_work_ids") or []),
    }


def effective_plan_review(state: dict[str, Any]) -> dict[str, Any]:
    """Return the plan-review defaults without requiring legacy STATE migration."""
    raw = state.get("plan_review") if isinstance(state.get("plan_review"), dict) else {}
    return {
        "required": bool(raw.get("required")),
        "status": raw.get("status") or ("pending" if raw.get("required") else "skipped"),
        "audit_file": raw.get("audit_file") or "audits/plan.md",
    }


def review_satisfied(item: dict[str, Any]) -> bool:
    review = effective_review(item)
    return not review["required"] or review["status"] == "verified"


def dependency_reaches(item_id: str, target_id: str, index: dict[str, tuple[Path, dict[str, Any]]]) -> bool:
    """True when target_id is reachable from item_id by following `dependencies` edges only."""
    target = str(target_id)
    seen: set[str] = set()
    stack = [str(item_id)]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        entry = index.get(current)
        if not entry:
            continue
        for dep in entry[1].get("dependencies", []) or []:
            dep_id = str(dep)
            if dep_id == target:
                return True
            stack.append(dep_id)
    return False


def remediation_completion_blockers(review: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> list[str]:
    """Reasons a registered remediation set is not yet closed, so `verified` may not proceed."""
    blockers: list[str] = []
    for remediation_id in review.get("remediation_work_ids", []) or []:
        entry = index.get(str(remediation_id))
        if not entry:
            blockers.append(f"remediation WORK {remediation_id} is missing")
            continue
        target = entry[1]
        if target.get("status") not in TERMINAL_STATUSES:
            blockers.append(f"remediation WORK {remediation_id} is not terminal")
        elif target.get("status") == "done" and not review_satisfied(target):
            blockers.append(f"remediation WORK {remediation_id} still requires review")
    return blockers


def deps_satisfied(item: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> bool:
    return not dependency_blockers(item, index)


def decision_satisfied(item: dict[str, Any], unresolved: set[str]) -> bool:
    return not decision_blockers(item, unresolved)


def dependency_blockers(item: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> list[str]:
    blockers = []
    for dep in item.get("dependencies", []) or []:
        dependency_id = str(dep)
        target = index.get(dependency_id)
        if not target:
            blockers.append(f"dependency {dependency_id} does not exist")
            continue
        dependency = target[1]
        if dependency.get("status") not in TERMINAL_STATUSES:
            blockers.append(f"dependency {dependency_id} is not terminal")
        elif dependency.get("status") == "done" and not review_satisfied(dependency):
            blockers.append(f"dependency {dependency_id} requires review before dependent WORK may proceed")
    return blockers


def decision_blockers(item: dict[str, Any], unresolved: set[str]) -> list[str]:
    return [f"unresolved decision {decision}" for decision in item.get("decision_dependencies", []) or [] if str(decision) in unresolved]


def work_start_errors(state: dict[str, Any], path: Path, doc: dict[str, Any], item: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> list[str]:
    errors = []
    if item.get("status") != "ready":
        errors.append(f"status must be ready, not {item.get('status')}")
    errors.extend(dependency_blockers(item, index))
    unresolved = {str(value) for value in state.get("unresolved_decisions", []) or []}
    errors.extend(decision_blockers(item, unresolved))

    phase = item_phase(path, doc)
    phases = normalized_phases(state)
    if phase == "integration":
        unverified = sorted(key for key, entry in phases.items() if entry.get("status") != "verified")
        if unverified:
            errors.append(f"project phases are not verified: {', '.join(unverified)}")
    elif phases.get(phase, {}).get("status") == "verified":
        errors.append(f"phase {phase} is already verified")

    plan_review = effective_plan_review(state)
    if plan_review.get("required") and plan_review.get("status") != "verified":
        errors.append("required plan review is pending")
    return errors


def phase_items(d: Path, docs: dict[Path, dict[str, Any]], key: str, phase: dict[str, Any]) -> list[dict[str, Any]]:
    work_path = d / phase.get("work_file", f"work/phase-{key}.yaml")
    doc = docs.get(work_path) or load_yaml(work_path, {}) or {}
    return list(doc.get("items", []) or [])


def phase_verify_errors(root: Path, domain: str, state: dict[str, Any], phase_key_value: str, docs: dict[Path, dict[str, Any]]) -> list[str]:
    phases = normalized_phases(state)
    phase = phases.get(phase_key_value)
    if phase is None:
        return [f"phase {phase_key_value} does not exist"]

    d = domain_dir(root, domain)
    items = phase_items(d, docs, phase_key_value, phase)
    errors = []
    if not items:
        errors.append(f"phase {phase_key_value} has no WORK items")
    open_items = [str(item.get("id")) for item in items if item.get("status") not in TERMINAL_STATUSES]
    if open_items:
        errors.append(f"open WORK remains: {', '.join(open_items)}")
    blocked_items = [str(item.get("id")) for item in items if item.get("status") == "blocked"]
    if blocked_items:
        errors.append(f"blocked WORK remains: {', '.join(blocked_items)}")
    pending_reviews = [str(item.get("id")) for item in items if item.get("status") == "done" and (item.get("risk") or {}).get("level") in HIGH_RISK and not review_satisfied(item)]
    if pending_reviews:
        errors.append(f"high-risk WORK requires review: {', '.join(pending_reviews)}")
    unresolved = {str(value) for value in state.get("unresolved_decisions", []) or []}
    decisions = sorted({str(decision) for item in items for decision in (item.get("decision_dependencies", []) or []) if str(decision) in unresolved})
    if decisions:
        errors.append(f"unresolved decisions: {', '.join(decisions)}")
    if not phase.get("diff_range"):
        errors.append("diff_range is required")
    audit_path = d / phase.get("audit_file", f"audits/phase-{phase_key_value}.md")
    if not audit_path.exists():
        errors.append(f"phase audit artifact not found: {audit_path}")
    return errors


def integration_verify_errors(root: Path, domain: str, state: dict[str, Any], docs: dict[Path, dict[str, Any]]) -> list[str]:
    phases = normalized_phases(state)
    errors = []
    if not phases:
        errors.append("project has no phases to verify")
    unverified = sorted(key for key, phase in phases.items() if phase.get("status") != "verified")
    if unverified:
        errors.append(f"phases are not verified: {', '.join(unverified)}")

    integration_items = [item for path, doc in docs.items() if item_phase(path, doc) == "integration" for item in (doc.get("items", []) or [])]
    open_items = [str(item.get("id")) for item in integration_items if item.get("status") not in TERMINAL_STATUSES]
    if open_items:
        errors.append(f"open integration WORK remains: {', '.join(open_items)}")
    blocked_items = [str(item.get("id")) for item in integration_items if item.get("status") == "blocked"]
    if blocked_items:
        errors.append(f"blocked integration WORK remains: {', '.join(blocked_items)}")
    pending_reviews = [str(item.get("id")) for item in integration_items if item.get("status") == "done" and (item.get("risk") or {}).get("level") in HIGH_RISK and not review_satisfied(item)]
    if pending_reviews:
        errors.append(f"high-risk integration WORK requires review: {', '.join(pending_reviews)}")
    unresolved = sorted(str(value) for value in state.get("unresolved_decisions", []) or [])
    if unresolved:
        errors.append(f"unresolved project decisions: {', '.join(unresolved)}")
    d = domain_dir(root, domain)
    integration = state.get("integration", {}) or {}
    audit_path = d / integration.get("audit_file", "audits/integration.md")
    if not audit_path.exists():
        errors.append(f"integration audit artifact not found: {audit_path}")
    return errors


def reject_transition(subject: str, action: str, errors: list[str]) -> int:
    for error in errors:
        print(f"{subject} cannot {action}: {error}", file=sys.stderr)
    return 2


def choose_next(root: Path, domain: str, statuses: set[str] | None = None):
    d = domain_dir(root, domain)
    state = load_yaml(d / "STATE.yaml", {}) or {}
    docs, index, _ = load_work_index(d)
    phases = normalized_phases(state)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or [])
    all_phases_verified = bool(phases) and all(
        entry.get("status") == "verified" for entry in phases.values()
    )

    candidates = []
    for path, doc in docs.items():
        phase = item_phase(path, doc)
        if phase == "integration":
            if not all_phases_verified:
                continue
        elif phases.get(phase, {}).get("status") == "verified":
            continue
        for item in doc.get("items", []) or []:
            status = item.get("status")
            if status in {"in_progress", "ready"} and (statuses is None or status in statuses) and deps_satisfied(item, index) and decision_satisfied(item, unresolved):
                priority = 0 if status == "in_progress" else 1
                risk = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get((item.get("risk") or {}).get("level"), 2)
                candidates.append((priority, phase == "integration", phase, risk, str(item.get("id")), path, item))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    _, _, phase, _, _, path, item = candidates[0]
    return phase, path, item


def work_review_action(root: Path, domain: str, state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the unresolved high-risk review action before normal ready WORK."""
    d = domain_dir(root, domain)
    docs, index, _ = load_work_index(d)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or [])
    reviews = []
    for path, doc in docs.items():
        for item in doc.get("items", []) or []:
            review = effective_review(item)
            if item.get("status") == "done" and review["required"] and review["status"] != "verified":
                reviews.append((str(item.get("id")), item_phase(path, doc), item, review))
    # Phase before id, the same ordering choose_next uses, so both halves of the runtime agree.
    for item_id, phase, _, review in sorted(reviews, key=lambda entry: (entry[1], entry[0])):
        if review["status"] == "pending":
            return {"role": "auditor", "command": "audit", "scope": "work", "mode": "initial", "phase": None if phase == "integration" else phase, "work_item": item_id}
        if review["status"] == "blocked":
            return {"role": "human", "command": "decision", "scope": "work", "phase": None if phase == "integration" else phase, "work_item": item_id}
    for item_id, phase, _, review in sorted(reviews, key=lambda entry: (entry[1], entry[0])):
        if review["status"] != "remediation":
            continue
        remediation = [index.get(str(remediation_id)) for remediation_id in review["remediation_work_ids"]]
        executable = [target for target in remediation if target and target[1].get("status") in {"in_progress", "ready"} and deps_satisfied(target[1], index) and decision_satisfied(target[1], unresolved)]
        if executable:
            executable.sort(key=lambda target: (0 if target[1].get("status") == "in_progress" else 1, str(target[1].get("id"))))
            remediation_item = executable[0][1]
            remediation_phase = item_phase(executable[0][0], docs[executable[0][0]])
            return {"role": "executor", "command": "run", "scope": "integration" if remediation_phase == "integration" else "phase", "phase": None if remediation_phase == "integration" else remediation_phase, "work_item": remediation_item.get("id"), "item_kind": remediation_item.get("kind")}
        if remediation and all(target and target[1].get("status") in TERMINAL_STATUSES and review_satisfied(target[1]) for target in remediation):
            return {"role": "auditor", "command": "audit", "scope": "work", "mode": "closure", "phase": None if phase == "integration" else phase, "work_item": item_id}
        return {"role": "human", "command": "decision", "scope": "work", "phase": None if phase == "integration" else phase, "work_item": item_id}
    return None


def compute_next_action(root: Path, domain: str, state: dict[str, Any]) -> dict[str, Any]:
    d = domain_dir(root, domain)
    work = work_files(d)
    if not work:
        return {"role": "architect", "command": "plan", "scope": "project", "phase": None, "work_item": None}

    plan_review = effective_plan_review(state)
    if plan_review.get("required") and plan_review.get("status") != "verified":
        return {"role": "auditor", "command": "audit", "scope": "plan", "mode": "initial", "phase": None, "work_item": None}

    nxt = choose_next(root, domain, {"in_progress"})
    if nxt:
        phase, _, item = nxt
        return {"role": "executor", "command": "run", "scope": "integration" if phase == "integration" else "phase", "phase": None if phase == "integration" else phase, "work_item": item.get("id"), "item_kind": item.get("kind")}

    review_action = work_review_action(root, domain, state)
    if review_action:
        return review_action

    nxt = choose_next(root, domain, {"ready"})
    if nxt:
        phase, _, item = nxt
        return {"role": "executor", "command": "run", "scope": "integration" if phase == "integration" else "phase", "phase": None if phase == "integration" else phase, "work_item": item.get("id"), "item_kind": item.get("kind")}

    docs, _, _ = load_work_index(d)
    phases = normalized_phases(state)
    for key in sorted(phases):
        ps = phases[key]
        if ps.get("status") == "verified":
            continue
        work_file = d / ps.get("work_file", f"work/phase-{key}.yaml")
        doc = docs.get(work_file) or load_yaml(work_file, {}) or {}
        items = doc.get("items", []) or []
        if ps.get("status") == "blocked" or any(i.get("status") == "blocked" for i in items):
            return {"role": "human", "command": "decision", "scope": "phase", "phase": key, "work_item": None}
        if items and all(i.get("status") in TERMINAL_STATUSES for i in items):
            mode = "closure" if ps.get("status") == "remediation" else "initial"
            return {"role": "auditor", "command": "audit", "scope": "phase", "mode": mode, "phase": key, "work_item": None}

    all_verified = bool(phases) and all(p.get("status") == "verified" for p in phases.values())
    integration = state.get("integration", {}) or {}
    istatus = integration.get("status", "pending")
    if all_verified:
        # An unresolved project decision must clear before any integration audit/closure.
        if state.get("unresolved_decisions"):
            return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None}
        # Blocked integration WORK needs a human decision, never an audit projection.
        integration_items = [
            item
            for path, doc in docs.items() if item_phase(path, doc) == "integration"
            for item in (doc.get("items", []) or [])
        ]
        blocked = [str(item.get("id")) for item in integration_items if item.get("status") == "blocked"]
        if blocked:
            action = {"role": "human", "command": "decision", "scope": "integration", "phase": None, "work_item": None}
            if len(blocked) == 1:
                action["work_item"] = blocked[0]
            return action
        if istatus in {"pending", "audit"}:
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "initial", "phase": None, "work_item": None}
        if istatus == "closure":
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
        if istatus == "verified":
            return {"role": "none", "command": "complete", "scope": "project", "phase": None, "work_item": None}

    if state.get("unresolved_decisions"):
        return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None}
    return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None, "reason": "lifecycle is incomplete"}


def project_status_for_action(action: dict[str, Any]) -> str:
    """Map a computed action to the schema's lifecycle projection."""
    command = action.get("command")
    scope = action.get("scope")
    if command == "plan":
        return "planning"
    if command == "complete":
        return "complete"
    if command == "decision" or action.get("role") == "human":
        return "blocked"
    if command == "run":
        remediation = action.get("item_kind") in {"remediation", "evidence"}
        if scope == "integration":
            return "integration_remediation" if remediation else "integration_audit"
        return "remediation" if remediation else "phase_execution"
    if command == "audit":
        if scope == "plan":
            return "plan_review"
        if scope == "work":
            # An initial work audit is its own lifecycle position. Reporting it as phase_audit
            # contradicted the next.scope printed beside it.
            if action.get("mode") != "closure":
                return "work_audit"
            return "integration_closure" if action.get("phase") is None else "remediation"
        if scope == "phase":
            return "remediation" if action.get("mode") == "closure" else "phase_audit"
        if scope == "integration":
            return "integration_closure" if action.get("mode") == "closure" else "integration_audit"
    return "blocked"


def active_phase_for_action(root: Path, domain: str, state: dict[str, Any], action: dict[str, Any]) -> str | None:
    """Project the single phase that owns the computed action, without guessing ambiguously."""
    scope = action.get("scope")
    if scope in {"project", "integration"}:
        return None
    if scope == "work" and action.get("work_item"):
        try:
            path, doc, _ = find_item(root, domain, str(action["work_item"]))
        except KeyError:
            return None
        phase = item_phase(path, doc)
        return None if phase == "integration" else phase
    if action.get("phase") is not None:
        return phase_key(action["phase"])
    active = [key for key, phase in normalized_phases(state).items() if phase.get("status") in {"executing", "audit", "remediation", "blocked"}]
    return active[0] if len(active) == 1 else None


def refresh_state(root: Path, domain: str) -> dict[str, Any]:
    path = state_path(root, domain)
    state = load_yaml(path, {}) or {}
    state["target_sha"] = current_sha(root)
    state["next_action"] = compute_next_action(root, domain, state)
    state["project_status"] = project_status_for_action(state["next_action"])
    state["active_phase"] = active_phase_for_action(root, domain, state, state["next_action"])
    dump_yaml_if_changed(path, state)
    return state


def action_inputs(root: Path, domain: str, state: dict[str, Any]) -> list[str]:
    """The documents a fresh session must load for the computed next action."""
    d = domain_dir(root, domain)
    action = state.get("next_action", {}) or {}
    inputs = [f"{domain}/STATE.yaml", f"{domain}/PRD.md", f"{domain}/PLAN.md"]
    if (d / "PITFALLS.md").exists():
        inputs.append(f"{domain}/PITFALLS.md")
    if state.get("unresolved_decisions"):
        inputs.append(f"{domain}/DECISIONS.md")
    phase = action.get("phase")
    if phase:
        ps = normalized_phases(state).get(phase, {})
        inputs.append(ps.get("work_file", f"work/phase-{phase}.yaml"))
        if action.get("command") == "audit" and action.get("scope") != "work":
            inputs.append(ps.get("audit_file", f"audits/phase-{phase}.md"))
    item_id = action.get("work_item")
    if item_id:
        try:
            _, _, item = find_item(root, domain, item_id)
        except KeyError:
            return inputs
        origin = item.get("origin") or {}
        ids = [str(x) for key in ["requirements", "findings", "plan_items"] for x in (origin.get(key) or [])]
        if ids:
            inputs.append(f"PRD/PLAN sections: {', '.join(ids)}")
        if action.get("command") == "audit" and action.get("scope") == "work":
            inputs.append(effective_review(item)["audit_file"])
    return inputs


def print_status(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    if not path.exists():
        print(f"Domain not initialized: {args.domain}", file=sys.stderr)
        return 2
    state = refresh_state(root, args.domain)
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    action = state.get("next_action", {}) or {}
    print(f"domain: {state.get('domain')}")
    print(f"project_status: {state.get('project_status')}")
    print(f"risk_profile: {state.get('risk_profile')}")
    print(f"baseline_sha: {short_sha(state.get('baseline_sha'))}")
    print(f"target_sha: {short_sha(state.get('target_sha'))}")
    print(f"unresolved_decisions: {', '.join(state.get('unresolved_decisions', []) or []) or '<none>'}")
    blocked = [i for _, (_, i) in load_work_index(domain_dir(root, args.domain))[1].items() if i.get("status") == "blocked"]
    if blocked:
        print(f"blocked_work: {', '.join(str(i.get('id')) for i in blocked)}")
    print(f"next.role: {action.get('role')}")
    print(f"next.command: {action.get('command')}")
    print(f"next.scope: {action.get('scope')}")
    if action.get("mode"):
        print(f"next.mode: {action.get('mode')}")
    if action.get("phase") is not None:
        print(f"next.phase: {action.get('phase')}")
        ps = normalized_phases(state).get(action.get("phase"), {})
        if ps.get("diff_range"):
            print(f"next.diff_range: {ps['diff_range']}")
    if action.get("work_item"):
        print(f"next.work_item: {action.get('work_item')}")
    for entry in action_inputs(root, args.domain, state):
        print(f"next.input: {entry}")
    return 0


def find_item(root: Path, domain: str, item_id: str):
    d = domain_dir(root, domain)
    docs, index, _ = load_work_index(d)
    found = index.get(item_id)
    if not found:
        raise KeyError(f"Unknown WORK item: {item_id}")
    path, item = found
    return path, docs[path], item


def next_item(args: argparse.Namespace) -> int:
    root = repo_root()
    state = refresh_state(root, args.domain)
    action = state.get("next_action", {}) or {}
    if action.get("command") != "run" or not action.get("work_item"):
        print(json.dumps(action, ensure_ascii=False, indent=2) if args.json else f"No executable WORK item. Next action: {action}")
        return 1
    _, _, item = find_item(root, args.domain, action["work_item"])
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(item, sort_keys=False, allow_unicode=True))
    return 0


def work_update(args: argparse.Namespace) -> int:
    root = repo_root()
    try:
        path, doc, item = find_item(root, args.domain, args.item)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.work_command == "start":
        state = load_yaml(state_path(root, args.domain), {}) or {}
        _, index, _ = load_work_index(domain_dir(root, args.domain))
        errors = work_start_errors(state, path, doc, item, index)
        if errors:
            return reject_transition(args.item, "start", errors)
        item["status"] = "in_progress"
        item["block_reason"] = None
    elif args.work_command == "done":
        if item.get("status") != "in_progress":
            return reject_transition(args.item, "done", [f"status=in_progress is required, not {item.get('status')}"])
        current_commands = list((item.get("evidence") or {}).get("commands") or [])
        cli_commands = list(getattr(args, "command", None) or [])
        if item.get("kind") != "documentation" and not has_nonblank_string(current_commands + cli_commands):
            return reject_transition(args.item, "done", ["verification evidence is required. Pass --command '<cmd> -> <result>'."])
        evidence = item.setdefault("evidence", {})
        for attr, key in [("changed_file", "changed_files"), ("command", "commands"), ("deviation", "deviations"), ("discovery", "discoveries")]:
            vals = getattr(args, attr, None) or []
            if key == "commands":
                vals = [value for value in vals if isinstance(value, str) and value.strip()]
            evidence.setdefault(key, [])
            evidence[key].extend(vals)
        if args.commit:
            evidence["commit"] = args.commit
        if (item.get("risk") or {}).get("level") in HIGH_RISK:
            review = effective_review(item)
            if review["status"] not in {"remediation", "blocked", "verified"}:
                review["status"] = "pending"
            item["review"] = review
        item["status"] = "done"
        item["block_reason"] = None
    elif args.work_command == "block":
        if item.get("status") not in {"ready", "in_progress"}:
            return reject_transition(args.item, "block", [f"cannot block status {item.get('status')}"])
        reason = (args.reason or "").strip()
        if not reason:
            return reject_transition(args.item, "block", ["a non-empty reason is required"])
        item["status"] = "blocked"
        item["block_reason"] = reason
    dump_yaml(path, doc)
    refresh_state(root, args.domain)
    print(f"{args.item}: {item['status']}")
    return 0


def work_review(args: argparse.Namespace) -> int:
    root = repo_root()
    try:
        path, doc, item = find_item(root, args.domain, args.item)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    review = effective_review(item)
    if item.get("status") != "done":
        print(f"{args.item}: review requires status=done", file=sys.stderr)
        return 2
    if not review["required"]:
        print(f"{args.item}: review is not required", file=sys.stderr)
        return 2
    if args.review_status == "verified":
        if review["status"] == "remediation":
            _, index, _ = load_work_index(domain_dir(root, args.domain))
            blockers = remediation_completion_blockers(review, index)
            if blockers:
                for blocker in blockers:
                    print(f"{args.item}: {blocker}", file=sys.stderr)
                return 2
        audit_path = domain_dir(root, args.domain) / review["audit_file"]
        if not audit_path.exists():
            print(f"{args.item}: work audit artifact not found: {audit_path}", file=sys.stderr)
            return 2
        review["status"] = "verified"
    elif args.review_status == "remediation":
        if not args.remediation_work:
            print(f"{args.item}: remediation review requires --remediation-work", file=sys.stderr)
            return 2
        _, index, _ = load_work_index(domain_dir(root, args.domain))
        for remediation_id in args.remediation_work:
            target = index.get(remediation_id)
            if not target:
                print(f"{args.item}: unknown remediation WORK {remediation_id}", file=sys.stderr)
                return 2
            remediation = target[1]
            if remediation.get("kind") not in {"remediation", "evidence"}:
                print(f"{args.item}: {remediation_id} must be kind remediation or evidence", file=sys.stderr)
                return 2
            if not ((remediation.get("origin") or {}).get("findings") or []):
                print(f"{args.item}: {remediation_id} must carry origin.findings traceability", file=sys.stderr)
                return 2
            if dependency_reaches(str(remediation_id), args.item, index):
                print(
                    f"{args.item}: remediation WORK {remediation_id} depends on {args.item} and cannot run before {args.item} review closure",
                    file=sys.stderr,
                )
                return 2
        review["status"] = "remediation"
        review["remediation_work_ids"] = list(dict.fromkeys(args.remediation_work))
    else:
        review["status"] = "blocked"
    item["review"] = review
    dump_yaml(path, doc)
    refresh_state(root, args.domain)
    print(f"{args.item}: review {review['status']}")
    return 0


def phase_entry(state: dict[str, Any], key: str) -> dict[str, Any]:
    phases = state.setdefault("phases", {})
    raw = raw_phase_key(state, key)
    if raw is None:
        phases[key] = {"status": "planned", "work_file": f"work/phase-{key}.yaml", "audit_file": f"audits/phase-{key}.md"}
        return phases[key]
    return phases[raw]


def phase_creation_errors(root: Path, domain: str, state: dict[str, Any], key: str) -> list[str]:
    """A mistyped phase number used to appear in STATE and block integration forever."""
    if raw_phase_key(state, key) is not None:
        return []
    work_file = domain_dir(root, domain) / f"work/phase-{key}.yaml"
    if work_file.exists():
        return []
    return [
        f"phase {key} is not in STATE and {work_file.relative_to(root)} does not exist. "
        "Add the phase in PLAN and STATE, or create its WORK file first."
    ]


def set_phase(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    key = phase_key(args.phase)
    phases = normalized_phases(state)
    existing = phases.get(key)
    creation_errors = phase_creation_errors(root, args.domain, state, key)
    if creation_errors:
        return reject_transition(f"phase {key}", "be created", creation_errors)
    if existing and existing.get("status") == "verified" and args.status != "verified":
        return reject_transition(f"phase {key}", "change", ["a verified phase cannot be reopened"])
    if args.status == "verified":
        docs, _, _ = load_work_index(domain_dir(root, args.domain))
        errors = phase_verify_errors(root, args.domain, state, key, docs)
        errors.extend(f"validation: {error}" for error in collect_validation(root, args.domain)[0])
        if errors:
            return reject_transition(f"phase {key}", "be verified", errors)
    phase = phase_entry(state, key)
    phase["status"] = args.status
    dump_yaml(path, state)
    refresh_state(root, args.domain)
    print(f"phase {key}: {args.status}")
    return 0


def set_phase_ref(args: argparse.Namespace) -> int:
    """Pin an auditable diff range, refusing the stale-3-dot trap when the stack is not linear."""
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    key = phase_key(args.phase)
    creation_errors = phase_creation_errors(root, args.domain, state, key)
    if creation_errors:
        return reject_transition(f"phase {key}", "be created", creation_errors)
    phase = phase_entry(state, key)

    if args.range:
        phase["diff_range"] = args.range
        phase["base_ref"] = args.base
        phase["head_ref"] = args.head
        dump_yaml(path, state)
        refresh_state(root, args.domain)
        print(f"phase {key} diff_range: {args.range} (explicit)")
        return 0

    base_sha = run_git(["rev-parse", "--verify", f"{args.base}^{{commit}}"], root)
    head_sha = run_git(["rev-parse", "--verify", f"{args.head}^{{commit}}"], root)
    if not base_sha or not head_sha:
        print(f"Cannot resolve refs: base={args.base} head={args.head}", file=sys.stderr)
        return 2
    if not git_ok(["merge-base", "--is-ancestor", base_sha, head_sha], root):
        print(f"{args.base} is not an ancestor of {args.head}. A 3-dot diff would pick a stale merge base.", file=sys.stderr)
        print("Inspect the graph, then re-run with an explicit range:", file=sys.stderr)
        print(f"  git log --graph --oneline {args.base} {args.head} | head -20", file=sys.stderr)
        print(f"  devflow phase ref {args.domain} {args.phase} --base {args.base} --head {args.head} --range '<first>^..<last>'", file=sys.stderr)
        return 2

    phase["base_ref"] = args.base
    phase["head_ref"] = args.head
    phase["base_sha"] = base_sha
    phase["head_sha"] = head_sha
    phase["diff_range"] = f"{base_sha}...{head_sha}"
    dump_yaml(path, state)
    refresh_state(root, args.domain)
    print(f"phase {key} diff_range: {short_sha(base_sha)}...{short_sha(head_sha)}")
    return 0


def set_plan_review(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    pr = effective_plan_review(state)
    required = bool(pr.get("required"))
    audit_file = pr["audit_file"]
    if args.status == "skipped" and required:
        return reject_transition("plan review", "be skipped", ["review is required"])
    if args.status == "verified":
        d = domain_dir(root, args.domain)
        errors = []
        if not (d / "PLAN.md").exists():
            errors.append(f"PLAN.md not found: {d / 'PLAN.md'}")
        if not (d / audit_file).exists():
            errors.append(f"plan audit artifact not found: {d / audit_file}")
        if errors:
            return reject_transition("plan review", "be verified", errors)
        pr["audit_file"] = audit_file
    pr["status"] = args.status
    state["plan_review"] = pr
    dump_yaml(path, state)
    refresh_state(root, args.domain)
    print(f"plan_review: {args.status}")
    return 0


def set_integration(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    integ = dict(state.get("integration", {}) or {})
    if integ.get("status") == "verified" and args.status != "verified":
        return reject_transition("integration", "change", ["a verified integration cannot be reopened"])
    if args.status == "verified":
        docs, _, _ = load_work_index(domain_dir(root, args.domain))
        errors = integration_verify_errors(root, args.domain, state, docs)
        errors.extend(f"validation: {error}" for error in collect_validation(root, args.domain)[0])
        if errors:
            return reject_transition("integration", "be verified", errors)
    integ["status"] = args.status
    state["integration"] = integ
    dump_yaml(path, state)
    refresh_state(root, args.domain)
    print(f"integration: {args.status}")
    return 0


def decision_update(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    unresolved = [str(x) for x in state.setdefault("unresolved_decisions", [])]
    if args.decision_command == "add" and args.decision not in unresolved:
        unresolved.append(args.decision)
    if args.decision_command == "resolve":
        unresolved = [x for x in unresolved if x != args.decision]
    state["unresolved_decisions"] = unresolved
    dump_yaml(path, state)
    refresh_state(root, args.domain)
    print(f"unresolved_decisions: {', '.join(unresolved) or '<none>'}")
    return 0


def validate_protocol_version(state: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    """The version was recorded but never read, so an artifact from any protocol validated."""
    if "protocol_version" not in state:
        return
    value = str(state.get("protocol_version") or "")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        errors.append(f"Invalid protocol_version: {value or '<empty>'}")
        return
    major, minor, _patch = map(int, match.groups())
    runtime_major, runtime_minor, _runtime_patch = map(int, PROTOCOL_VERSION.split("."))
    if major != runtime_major:
        errors.append(f"Unsupported protocol_version {value}: this runtime implements {PROTOCOL_VERSION}")
    elif minor > runtime_minor:
        warnings.append(f"STATE protocol_version {value} is newer than this runtime's {PROTOCOL_VERSION}")


def validate_state(state: dict[str, Any], d: Path, errors: list[str], warnings: list[str]) -> None:
    for field in STATE_REQUIRED_FIELDS:
        if field not in state:
            errors.append(f"STATE missing field: {field}")
    validate_protocol_version(state, errors, warnings)
    if state.get("project_status") not in PROJECT_STATUSES:
        errors.append(f"Invalid project_status: {state.get('project_status')}")
    if state.get("risk_profile") not in RISK_LEVELS:
        errors.append(f"Invalid risk_profile: {state.get('risk_profile')}")

    seen: dict[str, str] = {}
    for raw in (state.get("phases", {}) or {}):
        key = phase_key(raw)
        if key in seen:
            errors.append(f"Duplicate phase entry: {seen[key]!r} and {raw!r} both normalize to {key!r}")
        seen[key] = str(raw)

    for key, phase in normalized_phases(state).items():
        for field in PHASE_ENTRY_REQUIRED_FIELDS:
            if field not in phase:
                errors.append(f"Phase {key} missing field: {field}")
        if "status" in phase and phase.get("status") not in PHASE_STATUSES:
            errors.append(f"Phase {key} invalid status: {phase.get('status')}")
        wf = phase.get("work_file")
        if wf and not (d / wf).exists():
            warnings.append(f"Phase {key} work file not created yet: {wf}")
        if phase.get("status") in {"audit", "verified"} and not phase.get("diff_range"):
            warnings.append(f"Phase {key} has no diff_range. Run 'devflow phase ref' before auditing.")

    istatus = (state.get("integration", {}) or {}).get("status")
    if istatus not in INTEGRATION_STATUSES:
        errors.append(f"Invalid integration.status: {istatus}")


def validate_item(item: dict[str, Any], all_ids: set[str], index, unresolved: set[str], errors: list[str], warnings: list[str]) -> None:
    item_id = str(item.get("id", "<missing>"))
    for field in WORK_REQUIRED_ITEM_FIELDS:
        if field not in item:
            errors.append(f"{item_id}: missing {field}")
    kind = item.get("kind")
    status = item.get("status")
    level = (item.get("risk") or {}).get("level")
    if kind not in KINDS:
        errors.append(f"{item_id}: invalid kind {kind}")
    if status not in WORK_STATUSES:
        errors.append(f"{item_id}: invalid status {status}")
    if level not in RISK_LEVELS:
        errors.append(f"{item_id}: invalid risk.level {level}")
    if not (item.get("acceptance") or []):
        errors.append(f"{item_id}: acceptance must not be empty")
    if not has_nonblank_string((item.get("verification") or {}).get("commands")):
        errors.append(f"{item_id}: verification.commands must contain a non-empty command")
    for dep in item.get("dependencies", []) or []:
        if str(dep) not in all_ids:
            errors.append(f"{item_id}: unknown dependency {dep}")
    if status == "ready" and any(str(dec) in unresolved for dec in item.get("decision_dependencies", []) or []):
        errors.append(f"{item_id}: READY while blocked by unresolved decision")

    # Executable contract depth. High risk items must tell the executor what to re-verify.
    if level in HIGH_RISK and not (item.get("premise_checks") or []):
        errors.append(f"{item_id}: risk={level} requires premise_checks (facts to re-verify at HEAD before editing)")
    if level in HIGH_RISK and not (item.get("context") or []):
        warnings.append(f"{item_id}: risk={level} has no context (architect-verified repository facts)")
    if not (item.get("pitfalls") or []):
        warnings.append(f"{item_id}: no pitfalls recorded (known failure modes for this change)")

    # Evidence must back a completion claim.
    evidence = item.get("evidence") or {}
    if status == "done" and kind != "documentation" and not has_nonblank_string(evidence.get("commands")):
        errors.append(f"{item_id}: done without evidence.commands")

    review = item.get("review")
    if review is not None:
        if not isinstance(review, dict):
            errors.append(f"{item_id}: review must be a mapping")
        else:
            review_status = review.get("status")
            review_required = review.get("required")
            if review_status not in REVIEW_STATUSES:
                errors.append(f"{item_id}: invalid review.status {review_status}")
            if not isinstance(review_required, bool):
                errors.append(f"{item_id}: review.required must be boolean")
            if not review.get("audit_file"):
                errors.append(f"{item_id}: review.audit_file is required")
            remediation_ids = review.get("remediation_work_ids")
            if not isinstance(remediation_ids, list):
                errors.append(f"{item_id}: review.remediation_work_ids must be a list")
                remediation_ids = []
            if review_required is True and review_status == "skipped":
                errors.append(f"{item_id}: review.required=true cannot use status=skipped")
            if review_status == "remediation" and not remediation_ids:
                errors.append(f"{item_id}: review.status=remediation requires remediation_work_ids")
            for remediation_id in remediation_ids:
                if str(remediation_id) not in all_ids:
                    errors.append(f"{item_id}: unknown remediation WORK id {remediation_id}")
                elif review_status == "remediation" and dependency_reaches(str(remediation_id), item_id, index):
                    errors.append(
                        f"{item_id}: remediation WORK {remediation_id} depends on {item_id}; remediation cannot precede the reviewed WORK's own closure"
                    )
            if review_status == "verified" and status != "done":
                errors.append(f"{item_id}: review.status=verified requires status=done")
            if level in HIGH_RISK and status in {"done", "in_progress", "ready"} and review_required is not True:
                errors.append(f"{item_id}: risk={level} review.required must be true")

    # The transfer rule exists because a silently transferred requirement was missed for a whole cycle.
    if status == "transferred":
        transfer = item.get("transfer") or {}
        target_id = str(transfer.get("to", ""))
        if not target_id:
            errors.append(f"{item_id}: transferred without transfer.to")
        elif target_id not in index:
            errors.append(f"{item_id}: transfer.to points at unknown item {target_id}")
        else:
            target_path, target_item = index[target_id]
            source_reqs = {str(r) for r in ((item.get("origin") or {}).get("requirements") or [])}
            target_reqs = {str(r) for r in ((target_item.get("origin") or {}).get("requirements") or [])}
            missing = source_reqs - target_reqs
            if missing:
                errors.append(f"{item_id}: transferred requirements not registered on {target_id}: {', '.join(sorted(missing))}")


def collect_validation(root: Path, domain: str) -> tuple[list[str], list[str]]:
    """Structural findings for a domain, so state transitions can gate on them too."""
    d = domain_dir(root, domain)
    errors: list[str] = []
    warnings: list[str] = []
    state = load_yaml(d / "STATE.yaml", {}) or {}
    validate_state(state, d, errors, warnings)

    docs, index, duplicates = load_work_index(d)
    for dup in duplicates:
        errors.append(f"Duplicate WORK id: {dup}")
    all_ids = set(index)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or [])
    phases = normalized_phases(state)

    for path, doc in docs.items():
        items = doc.get("items", []) or []
        if not isinstance(items, list):
            errors.append(f"{path.name}: items must be a list")
            continue
        for item in items:
            validate_item(item, all_ids, index, unresolved, errors, warnings)

    # A phase cannot be verified while its own work is unfinished.
    for key, phase_state in phases.items():
        if phase_state.get("status") != "verified":
            continue
        work_file = d / phase_state.get("work_file", f"work/phase-{key}.yaml")
        doc = docs.get(work_file) or load_yaml(work_file, {}) or {}
        open_items = [str(i.get("id")) for i in (doc.get("items", []) or []) if i.get("status") not in TERMINAL_STATUSES]
        if open_items:
            errors.append(f"Phase {key} is verified but has open work: {', '.join(open_items)}")
    if (state.get("integration", {}) or {}).get("status") == "verified":
        unfinished = [k for k, p in phases.items() if p.get("status") != "verified"]
        if unfinished:
            errors.append(f"integration is verified but phases are not: {', '.join(sorted(unfinished))}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, stack: list[str]):
        if node in visiting:
            errors.append("Dependency cycle: " + " -> ".join(stack + [node]))
            return
        if node in visited or node not in index:
            return
        visiting.add(node)
        stack.append(node)
        for dep in index[node][1].get("dependencies", []) or []:
            dfs(str(dep), stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in list(index):
        dfs(node, [])

    prd_path = d / "PRD.md"
    prd_ids = set(REQ_PATTERN.findall(prd_path.read_text(encoding="utf-8"))) if prd_path.exists() else set()
    if prd_ids:
        for item_id, (_, item) in index.items():
            for req in (item.get("origin") or {}).get("requirements", []) or []:
                if str(req) not in prd_ids:
                    warnings.append(f"{item_id}: requirement id not found verbatim in PRD: {req}")

    return errors, warnings


def validate(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    if not d.exists():
        print(f"Domain not initialized: {args.domain}", file=sys.stderr)
        return 2
    errors, warnings = collect_validation(root, args.domain)
    _, index, _ = load_work_index(d)

    print(f"DevFlow validation: {args.domain}")
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"errors={len(errors)} warnings={len(warnings)} work_items={len(index)}")
    return 1 if errors else 0


def print_section(title: str, body: str) -> None:
    print(f"\n---\n\n<!-- {title} -->")
    print(body.rstrip())


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def origin_ids(item: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    origin = item.get("origin") or {}
    return (
        [str(value) for value in origin.get("requirements", []) or []],
        [str(value) for value in origin.get("plan_items", []) or []],
        [str(value) for value in origin.get("findings", []) or []],
    )


def exact_id_pattern(value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9-]){re.escape(value)}(?![A-Za-z0-9-])")


def extract_markdown_context(path: Path, ids: list[str]) -> list[str]:
    lines = read_text_if_exists(path).splitlines()
    ranges: list[tuple[int, int]] = []
    missing: list[str] = []

    for value in ids:
        pattern = exact_id_pattern(value)
        headings = []
        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s+", line)
            if match and pattern.search(line):
                headings.append((index, len(match.group(1))))
        if headings:
            for start, level in headings:
                end = len(lines)
                for index in range(start + 1, len(lines)):
                    match = re.match(r"^(#{1,6})\s+", lines[index])
                    if match and len(match.group(1)) <= level:
                        end = index
                        break
                ranges.append((start, end))
            continue

        matches = [index for index, line in enumerate(lines) if pattern.search(line)]
        if not matches:
            missing.append(f"{value}: not found verbatim in {path.name}")
            continue
        ranges.extend((max(0, index - 2), min(len(lines), index + 3)) for index in matches)

    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return ["\n".join(lines[start:end]).rstrip() for start, end in merged] + missing


def render_markdown_context(title: str, path: Path, ids: list[str]) -> None:
    print(f"\n## {title}")
    context = extract_markdown_context(path, ids)
    print("\n\n".join(context) if context else "<no referenced IDs>")


def render_markdown_file(title: str, path: Path) -> None:
    print(f"\n## {title}")
    print(read_text_if_exists(path).rstrip() or f"{path.name}: not found")


def render_yaml_context(title: str, data: Any) -> None:
    print(f"\n## {title}")
    print("```yaml")
    print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip())
    print("```")


def render_closure_audit(title: str, path: Path, mode: str) -> None:
    if mode == "closure" and path.exists():
        render_markdown_file(title, path)


def render(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    role = args.render_command
    state = refresh_state(root, args.domain)

    print((plugin_root() / "core" / "prompts" / f"{role}.md").read_text(encoding="utf-8").rstrip())

    print("\n## Runtime context")
    print(f"- repository: {root}")
    print(f"- domain: {args.domain}")
    print(f"- PRD: {d / 'PRD.md'}")
    print(f"- PLAN: {d / 'PLAN.md'}")
    print(f"- STATE: {d / 'STATE.yaml'}")
    print(f"- DECISIONS: {d / 'DECISIONS.md'}")
    print(f"- PITFALLS: {d / 'PITFALLS.md'}")
    print(f"- baseline_sha: {state.get('baseline_sha')}")
    print(f"- target_sha: {state.get('target_sha')}")
    print(f"- risk_profile: {state.get('risk_profile')}")
    print(f"- unresolved_decisions: {', '.join(state.get('unresolved_decisions', []) or []) or '<none>'}")

    if role == "audit":
        phases = normalized_phases(state)
        print(f"- audit_scope: {args.scope}")
        print(f"- audit_mode: {args.mode}")
        if args.scope == "plan":
            review = effective_plan_review(state)
            print(f"- current_head: {current_sha(root) or '<none>'}")
            print(f"- audit_file: {d / review['audit_file']}")
            render_markdown_file("Approved PRD", d / "PRD.md")
            render_markdown_file("Current PLAN", d / "PLAN.md")
            render_yaml_context("Plan review metadata", review)
        elif args.scope == "work":
            if not args.task:
                print("Work audit requires --task <WORK-ID>", file=sys.stderr)
                return 2
            path, doc, item = find_item(root, args.domain, args.task)
            review = effective_review(item)
            audit_path = d / review["audit_file"]
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            print(f"- work_item: {item.get('id')}")
            print(f"- work_phase: {item_phase(path, doc)}")
            print(f"- work_risk: {(item.get('risk') or {}).get('level')}")
            print(f"- work_origin_requirements: {', '.join(str(x) for x in ((item.get('origin') or {}).get('requirements') or [])) or '<none>'}")
            print(f"- work_origin_plan_items: {', '.join(str(x) for x in ((item.get('origin') or {}).get('plan_items') or [])) or '<none>'}")
            print(f"- work_evidence_commit: {(item.get('evidence') or {}).get('commit') or '<none>'}")
            print(f"- work_changed_files: {', '.join((item.get('evidence') or {}).get('changed_files') or []) or '<none>'}")
            print(f"- work_verification_evidence: {', '.join((item.get('evidence') or {}).get('commands') or []) or '<none>'}")
            print(f"- audit_file: {audit_path}")
            print(f"- current_head: {current_sha(root) or '<none>'}")
            print("\n## Selected WORK item")
            print("```yaml")
            print(yaml.safe_dump(item, sort_keys=False, allow_unicode=True).rstrip())
            print("```")
            requirements, plan_items, _ = origin_ids(item)
            render_markdown_context("Relevant PRD context", d / "PRD.md", requirements)
            render_markdown_context("Relevant PLAN context", d / "PLAN.md", plan_items)
            render_yaml_context("Implementation evidence", item.get("evidence") or {})
            render_closure_audit("Existing work audit", audit_path, args.mode)
        elif args.scope == "phase":
            if not args.phase:
                print("Phase audit requires --phase <PHASE>", file=sys.stderr)
                return 2
            key = phase_key(args.phase)
            ps = phases.get(key)
            if ps is None:
                print(f"Phase audit phase does not exist: {key}", file=sys.stderr)
                return 2
            print(f"- phase: {key}")
            print(f"- phase_base_sha: {ps.get('base_sha') or '<unset>'}")
            print(f"- phase_head_sha: {ps.get('head_sha') or '<unset>'}")
            print(f"- diff_range: {ps.get('diff_range') or '<unset — run devflow phase ref before auditing>'}")
            print(f"- work_file: {d / ps.get('work_file', f'work/phase-{key}.yaml')}")
            print(f"- audit_file: {d / ps.get('audit_file', f'audits/phase-{key}.md')}")
            work_path = d / ps.get("work_file", f"work/phase-{key}.yaml")
            audit_path = d / ps.get("audit_file", f"audits/phase-{key}.md")
            work_doc = load_yaml(work_path, {}) or {}
            items = list(work_doc.get("items", []) or [])
            requirements = list(dict.fromkeys(requirement for item in items for requirement in origin_ids(item)[0]))
            plan_items = list(dict.fromkeys(plan_item for item in items for plan_item in origin_ids(item)[1]))
            render_yaml_context("Phase WORK YAML", work_doc)
            render_markdown_context("Relevant PRD context", d / "PRD.md", requirements)
            render_markdown_context("Relevant PLAN context", d / "PLAN.md", plan_items)
            render_closure_audit("Existing phase audit", audit_path, args.mode)
        elif args.scope == "integration":
            integ = state.get("integration", {}) or {}
            print(f"- diff_range: {state.get('baseline_sha')}...{state.get('target_sha')}")
            print(f"- work_file: {d / integ.get('work_file', 'work/integration.yaml')}")
            print(f"- audit_file: {d / integ.get('audit_file', 'audits/integration.md')}")
            render_markdown_file("Current PLAN", d / "PLAN.md")
            manifest = [
                {
                    "phase": key,
                    "status": entry.get("status"),
                    "work_file": entry.get("work_file", f"work/phase-{key}.yaml"),
                    "audit_file": entry.get("audit_file", f"audits/phase-{key}.md"),
                    "diff_range": entry.get("diff_range"),
                }
                for key, entry in sorted(phases.items())
            ]
            render_yaml_context("Phase manifest", manifest)
            print("\n## Phase audit artifacts")
            for entry in manifest:
                print(f"- {d / entry['audit_file']}")
            integration_work_path = d / integ.get("work_file", "work/integration.yaml")
            if integration_work_path.exists():
                render_yaml_context("Integration WORK YAML", load_yaml(integration_work_path, {}) or {})
            render_closure_audit("Existing integration audit", d / integ.get("audit_file", "audits/integration.md"), args.mode)
        else:
            raise ValueError(f"Unsupported audit scope: {args.scope}")

    if role == "run":
        item_id = args.task or (state.get("next_action", {}) or {}).get("work_item")
        if not item_id:
            print("\nNo executable WORK item is available.")
            return 1
        _, _, item = find_item(root, args.domain, item_id)
        print("\n## Selected WORK item")
        print("```yaml")
        print(yaml.safe_dump(item, sort_keys=False, allow_unicode=True).rstrip())
        print("```")
        requirements, plan_items, _ = origin_ids(item)
        render_markdown_context("Relevant PRD context", d / "PRD.md", requirements)
        render_markdown_context("Relevant PLAN context", d / "PLAN.md", plan_items)

    if role == "plan":
        render_markdown_file("Approved PRD", d / "PRD.md")

    for name in PROMPT_PROTOCOLS[role]:
        print_section(f"protocol/{name}.md", read_protocol(name))

    if role == "audit":
        extension = resolve_extension(root, state)
        print_section(f"extension: {extension}", extension.read_text(encoding="utf-8"))

    pitfalls = d / "PITFALLS.md"
    if pitfalls.exists():
        print_section(f"{args.domain}/PITFALLS.md", pitfalls.read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="devflow", description="State-based agent development protocol runtime")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init")
    sp.add_argument("domain")
    sp.add_argument("--risk", choices=sorted(RISK_LEVELS), default="medium")
    sp.add_argument("--extension", default="default")
    sp.add_argument("--prd")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=init_domain)

    sp = sub.add_parser("validate")
    sp.add_argument("domain")
    sp.set_defaults(func=validate)

    sp = sub.add_parser("status")
    sp.add_argument("domain")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=print_status)

    sp = sub.add_parser("next")
    sp.add_argument("domain")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=next_item)

    sp = sub.add_parser("work")
    worksub = sp.add_subparsers(dest="work_command", required=True)
    s = worksub.add_parser("start")
    s.add_argument("domain"); s.add_argument("item"); s.set_defaults(func=work_update)
    s = worksub.add_parser("done")
    s.add_argument("domain"); s.add_argument("item"); s.add_argument("--commit")
    s.add_argument("--changed-file", action="append", default=[])
    s.add_argument("--command", action="append", default=[])
    s.add_argument("--deviation", action="append", default=[])
    s.add_argument("--discovery", action="append", default=[])
    s.set_defaults(func=work_update)
    s = worksub.add_parser("block")
    s.add_argument("domain"); s.add_argument("item"); s.add_argument("--reason", required=True); s.set_defaults(func=work_update)
    s = worksub.add_parser("review")
    s.add_argument("domain"); s.add_argument("item"); s.add_argument("review_status", choices=["verified", "remediation", "blocked"])
    s.add_argument("--remediation-work", action="append", default=[])
    s.set_defaults(func=work_review)

    sp = sub.add_parser("phase")
    phasesub = sp.add_subparsers(dest="phase_command", required=True)
    s = phasesub.add_parser("set")
    s.add_argument("domain"); s.add_argument("phase"); s.add_argument("status", choices=sorted(PHASE_STATUSES)); s.set_defaults(func=set_phase)
    s = phasesub.add_parser("ref")
    s.add_argument("domain"); s.add_argument("phase")
    s.add_argument("--base", required=True); s.add_argument("--head", required=True)
    s.add_argument("--range", help="Explicit diff range, for stacks where base is not an ancestor of head")
    s.set_defaults(func=set_phase_ref)

    sp = sub.add_parser("plan-review")
    prsub = sp.add_subparsers(dest="plan_review_command", required=True)
    s = prsub.add_parser("set")
    s.add_argument("domain"); s.add_argument("status", choices=["pending", "verified", "skipped"]); s.set_defaults(func=set_plan_review)

    sp = sub.add_parser("integration")
    insub = sp.add_subparsers(dest="integration_command", required=True)
    s = insub.add_parser("set")
    s.add_argument("domain"); s.add_argument("status", choices=sorted(INTEGRATION_STATUSES)); s.set_defaults(func=set_integration)

    sp = sub.add_parser("decision")
    dsub = sp.add_subparsers(dest="decision_command", required=True)
    for name in ["add", "resolve"]:
        s = dsub.add_parser(name); s.add_argument("domain"); s.add_argument("decision"); s.set_defaults(func=decision_update)

    sp = sub.add_parser("render")
    rsub = sp.add_subparsers(dest="render_command", required=True)
    s = rsub.add_parser("plan"); s.add_argument("domain"); s.set_defaults(func=render)
    s = rsub.add_parser("run"); s.add_argument("domain"); s.add_argument("--task"); s.set_defaults(func=render)
    s = rsub.add_parser("audit"); s.add_argument("domain"); s.add_argument("--scope", choices=["plan", "work", "phase", "integration"], required=True); s.add_argument("--task"); s.add_argument("--phase"); s.add_argument("--mode", choices=["initial", "closure"], default="initial"); s.set_defaults(func=render)
    return p


def main() -> int:
    try:
        args = build_parser().parse_args()
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except KeyError as exc:
        # str(KeyError) is the repr of its argument, which printed the message inside quotes.
        print(f"DevFlow error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"DevFlow error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
