#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("DevFlow requires PyYAML. Install with: python3 -m pip install PyYAML", file=sys.stderr)
    raise SystemExit(2)

PROTOCOL_VERSION = "1.1.0"
WORK_STATUSES = {"ready", "in_progress", "done", "blocked", "transferred", "cancelled"}
TERMINAL_STATUSES = {"done", "transferred", "cancelled"}
PHASE_STATUSES = {"planned", "executing", "audit", "remediation", "verified", "blocked"}
PROJECT_STATUSES = {"planning", "plan_review", "phase_execution", "phase_audit", "remediation", "integration_audit", "integration_remediation", "integration_closure", "complete", "blocked"}
INTEGRATION_STATUSES = {"pending", "audit", "remediation", "closure", "verified"}
KINDS = {"implementation", "remediation", "evidence", "documentation", "migration", "test"}
RISK_LEVELS = {"low", "medium", "high", "critical"}
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


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000), encoding="utf-8")


def dump_yaml_if_changed(path: Path, data: Any) -> bool:
    """Write only when the rendered YAML differs, so read-only commands stay side-effect free."""
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
    return True


def runtime_config(root: Path) -> dict[str, Any]:
    cfg_path = root / ".devflow" / "config.yaml"
    cfg = load_yaml(cfg_path, {}) or {}
    cfg.setdefault("protocol_version", PROTOCOL_VERSION)
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
        dump_yaml(cfg, {"protocol_version": PROTOCOL_VERSION, "domains_root": "docs/domains", "extension": "default"})


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
    state.setdefault("plan_review", {"required": args.risk in HIGH_RISK, "status": "pending" if args.risk in HIGH_RISK else "skipped"})
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


def deps_satisfied(item: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> bool:
    for dep in item.get("dependencies", []) or []:
        target = index.get(str(dep))
        if not target:
            return False
        if target[1].get("status") not in TERMINAL_STATUSES:
            return False
    return True


def decision_satisfied(item: dict[str, Any], unresolved: set[str]) -> bool:
    return not any(str(d) in unresolved for d in (item.get("decision_dependencies", []) or []))


def choose_next(root: Path, domain: str):
    d = domain_dir(root, domain)
    state = load_yaml(d / "STATE.yaml", {}) or {}
    docs, index, _ = load_work_index(d)
    phases = normalized_phases(state)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or [])

    candidates = []
    for path, doc in docs.items():
        phase = item_phase(path, doc)
        if phase != "integration" and phases.get(phase, {}).get("status") == "verified":
            continue
        for item in doc.get("items", []) or []:
            status = item.get("status")
            if status in {"in_progress", "ready"} and deps_satisfied(item, index) and decision_satisfied(item, unresolved):
                priority = 0 if status == "in_progress" else 1
                risk = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get((item.get("risk") or {}).get("level"), 2)
                candidates.append((priority, phase == "integration", phase, risk, str(item.get("id")), path, item))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    _, _, phase, _, _, path, item = candidates[0]
    return phase, path, item


def compute_next_action(root: Path, domain: str, state: dict[str, Any]) -> dict[str, Any]:
    d = domain_dir(root, domain)
    work = work_files(d)
    if not work:
        return {"role": "architect", "command": "plan", "scope": "project", "phase": None, "work_item": None}

    plan_review = state.get("plan_review", {}) or {}
    if plan_review.get("required") and plan_review.get("status") != "verified":
        return {"role": "auditor", "command": "audit", "scope": "plan", "mode": "initial", "phase": None, "work_item": None}

    nxt = choose_next(root, domain)
    if nxt:
        phase, _, item = nxt
        return {"role": "executor", "command": "run", "scope": "integration" if phase == "integration" else "phase", "phase": None if phase == "integration" else phase, "work_item": item.get("id")}

    docs, _, _ = load_work_index(d)
    phases = normalized_phases(state)
    for key in sorted(phases):
        ps = phases[key]
        if ps.get("status") == "verified":
            continue
        work_file = d / ps.get("work_file", f"work/phase-{key}.yaml")
        doc = docs.get(work_file) or load_yaml(work_file, {}) or {}
        items = doc.get("items", []) or []
        if items and all(i.get("status") in TERMINAL_STATUSES for i in items):
            mode = "closure" if ps.get("status") == "remediation" else "initial"
            return {"role": "auditor", "command": "audit", "scope": "phase", "mode": mode, "phase": key, "work_item": None}
        if any(i.get("status") == "blocked" for i in items):
            return {"role": "human", "command": "decision", "scope": "phase", "phase": key, "work_item": None}

    all_verified = bool(phases) and all(p.get("status") == "verified" for p in phases.values())
    integration = state.get("integration", {}) or {}
    istatus = integration.get("status", "pending")
    if all_verified:
        if istatus in {"pending", "audit"}:
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "initial", "phase": None, "work_item": None}
        if istatus == "closure":
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
        if istatus == "verified":
            return {"role": "none", "command": "complete", "scope": "project", "phase": None, "work_item": None}

    if state.get("unresolved_decisions"):
        return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None}
    return {"role": "auditor", "command": "audit", "scope": "project", "mode": "initial", "phase": None, "work_item": None}


def refresh_state(root: Path, domain: str) -> dict[str, Any]:
    path = state_path(root, domain)
    state = load_yaml(path, {}) or {}
    state["target_sha"] = current_sha(root)
    state["next_action"] = compute_next_action(root, domain, state)
    if state["next_action"].get("command") == "complete":
        state["project_status"] = "complete"
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
        if action.get("command") == "audit":
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
        item["status"] = "in_progress"
        item["block_reason"] = None
    elif args.work_command == "done":
        evidence = item.setdefault("evidence", {})
        for attr, key in [("changed_file", "changed_files"), ("command", "commands"), ("deviation", "deviations"), ("discovery", "discoveries")]:
            vals = getattr(args, attr, None) or []
            evidence.setdefault(key, [])
            evidence[key].extend(vals)
        if args.commit:
            evidence["commit"] = args.commit
        if item.get("kind") != "documentation" and not evidence.get("commands"):
            print(f"{args.item}: refusing done with no verification evidence. Pass --command '<cmd> -> <result>'.", file=sys.stderr)
            dump_yaml(path, doc)
            return 2
        item["status"] = "done"
        item["block_reason"] = None
    elif args.work_command == "block":
        item["status"] = "blocked"
        item["block_reason"] = args.reason
    dump_yaml(path, doc)
    refresh_state(root, args.domain)
    print(f"{args.item}: {item['status']}")
    return 0


def phase_entry(state: dict[str, Any], key: str) -> dict[str, Any]:
    phases = state.setdefault("phases", {})
    raw = raw_phase_key(state, key)
    if raw is None:
        phases[key] = {"work_file": f"work/phase-{key}.yaml", "audit_file": f"audits/phase-{key}.md"}
        return phases[key]
    return phases[raw]


def set_phase(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    key = phase_key(args.phase)
    phase = phase_entry(state, key)
    phase["status"] = args.status
    state["active_phase"] = None if args.status == "verified" else key
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
    phase = phase_entry(state, key)

    if args.range:
        phase["diff_range"] = args.range
        phase["base_ref"] = args.base
        phase["head_ref"] = args.head
        dump_yaml(path, state)
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
    print(f"phase {key} diff_range: {short_sha(base_sha)}...{short_sha(head_sha)}")
    return 0


def set_plan_review(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    pr = state.setdefault("plan_review", {"required": False, "status": "skipped"})
    pr["status"] = args.status
    dump_yaml(path, state)
    refresh_state(root, args.domain)
    print(f"plan_review: {args.status}")
    return 0


def set_integration(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    integ = state.setdefault("integration", {"work_file": "work/integration.yaml", "audit_file": "audits/integration.md"})
    integ["status"] = args.status
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


def validate_state(state: dict[str, Any], d: Path, errors: list[str], warnings: list[str]) -> None:
    for field in ["protocol_version", "domain", "risk_profile", "project_status", "phases", "integration", "unresolved_decisions", "next_action"]:
        if field not in state:
            errors.append(f"STATE missing field: {field}")
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
        if phase.get("status") not in PHASE_STATUSES:
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
    required = ["id", "kind", "origin", "objective", "dependencies", "decision_dependencies", "scope", "requirements", "verification", "acceptance", "stop_conditions", "risk", "status", "evidence"]
    for field in required:
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
    if not ((item.get("verification") or {}).get("commands") or []):
        errors.append(f"{item_id}: verification.commands must not be empty")
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
    if status == "done" and kind != "documentation" and not (evidence.get("commands") or []):
        errors.append(f"{item_id}: done without evidence.commands")

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


def validate(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    errors: list[str] = []
    warnings: list[str] = []
    if not d.exists():
        print(f"Domain not initialized: {args.domain}", file=sys.stderr)
        return 2
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
        if args.phase is not None:
            key = phase_key(args.phase)
            ps = phases.get(key, {})
            print(f"- phase: {key}")
            print(f"- phase_base_sha: {ps.get('base_sha') or '<unset>'}")
            print(f"- phase_head_sha: {ps.get('head_sha') or '<unset>'}")
            print(f"- diff_range: {ps.get('diff_range') or '<unset — run devflow phase ref before auditing>'}")
            print(f"- work_file: {d / ps.get('work_file', f'work/phase-{key}.yaml')}")
            print(f"- audit_file: {d / ps.get('audit_file', f'audits/phase-{key}.md')}")
        else:
            integ = state.get("integration", {}) or {}
            print(f"- diff_range: {state.get('baseline_sha')}...{state.get('target_sha')}")
            print(f"- audit_file: {d / integ.get('audit_file', 'audits/integration.md')}")

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
    s = rsub.add_parser("audit"); s.add_argument("domain"); s.add_argument("--scope", choices=["plan", "phase", "integration"], required=True); s.add_argument("--phase"); s.add_argument("--mode", choices=["initial", "closure"], default="initial"); s.set_defaults(func=render)
    return p


def main() -> int:
    try:
        args = build_parser().parse_args()
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"DevFlow error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
