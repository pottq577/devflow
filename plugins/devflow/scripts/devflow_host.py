#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import re
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import devflow
import devflow_autopilot as autopilot

HOST_BACKEND = "host_native_agent"
TELEMETRY_FILENAME = "host-dispatch.jsonl"
TELEMETRY_INFLIGHT_DIR = "host-dispatch-inflight"
TELEMETRY_COMMANDS = {"telemetry-start", "telemetry-finish"}


def _host_capabilities(policy: dict[str, Any]) -> autopilot.CapabilityRegistry:
    registry = autopilot.ModelRegistry.from_policy(policy)
    native_models = {
        registry.model_id(alias)
        for alias in registry.aliases()
        if registry.meta(alias).get("multi_agent")
    }
    return autopilot.CapabilityRegistry.assumed(
        policy,
        native_models=native_models,
        exec_available=False,
    )


def _host_router(policy: dict[str, Any]) -> autopilot.RouteEngine:
    host_policy = copy.deepcopy(policy)
    host_policy.setdefault("backends", {})["preference"] = ["native_agent"]
    return autopilot.RouteEngine(host_policy, _host_capabilities(host_policy))


def _host_route(
    policy: dict[str, Any],
    action: dict[str, Any],
    state: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    spec = _host_router(policy).resolve(action, state, attempt)
    spec = copy.deepcopy(spec)
    spec.setdefault("execution", {})["backend"] = HOST_BACKEND
    spec["execution"]["context_mode"] = "repository_recovery"
    spec["execution"]["native_fork_turns"] = str(
        (policy.get("context") or {}).get("native_fork_turns") or "none"
    )
    return spec


def _candidate_rows(
    policy: dict[str, Any], spec: dict[str, Any]
) -> list[dict[str, Any]]:
    registry = autopilot.ModelRegistry.from_policy(policy)
    profile = str((spec.get("model") or {}).get("profile") or "")
    effort = str((spec.get("model") or {}).get("reasoning_effort") or "")
    rows: list[dict[str, Any]] = []
    for reference in (policy.get("profiles", {}).get(profile, {}) or {}).get(
        "candidates", []
    ):
        if not registry.contains(str(reference)):
            continue
        meta = registry.meta(str(reference))
        if not meta.get("multi_agent"):
            continue
        if effort not in (meta.get("efforts") or []):
            continue
        rows.append(
            {
                "alias": registry.alias_for(str(reference)),
                "model": registry.model_id(str(reference)),
                "reasoning_effort": effort,
            }
        )
    return rows


def _role_contract_path(plugin_root: Path, role: str) -> Path:
    source = autopilot.ROLE_CONTRACTS.get(role)
    if not source:
        raise ValueError(f"Unknown host dispatch role: {role}")
    kind, name = source
    if kind == "skill":
        return plugin_root / "skills" / name / "SKILL.md"
    return plugin_root / "core" / "prompts" / name


def _render_command(plugin_root: Path, domain: str, action: dict[str, Any]) -> str:
    command = str(action.get("command") or "")
    base = [
        sys.executable,
        str(plugin_root / "scripts" / "devflow.py"),
        "render",
        command,
        domain,
    ]
    if command == "run" and action.get("work_item"):
        base.extend(["--task", str(action["work_item"])])
    elif command == "audit":
        scope = action.get("scope")
        if not scope:
            raise ValueError("Audit host dispatch requires scope")
        base.extend(["--scope", str(scope)])
        if action.get("work_item"):
            base.extend(["--task", str(action["work_item"])])
        if action.get("phase") is not None:
            base.extend(["--phase", str(action["phase"])])
        base.extend(["--mode", str(action.get("mode") or "initial")])
    elif command not in {"plan", "finalize"}:
        raise ValueError(f"Action cannot be rendered for host dispatch: {command}")
    return " ".join(shlex.quote(part) for part in base)


def _status_command(plugin_root: Path, domain: str) -> str:
    parts = [
        sys.executable,
        str(plugin_root / "scripts" / "devflow.py"),
        "status",
        domain,
    ]
    return " ".join(shlex.quote(part) for part in parts)


def _task_name(domain: str, spec: dict[str, Any]) -> str:
    action = spec.get("action") or {}
    raw = "_".join(
        str(value)
        for value in (
            "devflow",
            domain,
            spec.get("role"),
            action.get("work_item") or action.get("command"),
            spec.get("attempt"),
        )
        if value not in {None, ""}
    ).lower()
    value = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    return value[:64] or "devflow_task"


def _telemetry_dir(root: Path, domain: str) -> Path:
    return root / ".devflow" / "runtime" / domain


def _telemetry_path(root: Path, domain: str) -> Path:
    return _telemetry_dir(root, domain) / TELEMETRY_FILENAME


def _telemetry_inflight_path(root: Path, domain: str, dispatch_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{24}", dispatch_id):
        raise ValueError("Telemetry dispatch id must be 24 lowercase hex characters")
    return _telemetry_dir(root, domain) / TELEMETRY_INFLIGHT_DIR / f"{dispatch_id}.json"


def _utc_timestamp(epoch_seconds: float) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _append_telemetry(root: Path, domain: str, record: dict[str, Any]) -> None:
    path = _telemetry_path(root, domain)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _telemetry_candidate(
    payload: dict[str, Any], candidate_alias: str | None
) -> dict[str, Any]:
    selected = {
        "alias": payload.get("model_alias"),
        "model": payload.get("model"),
        "reasoning_effort": payload.get("reasoning_effort"),
    }
    if not candidate_alias or candidate_alias == selected["alias"]:
        return selected
    for candidate in payload.get("candidates") or []:
        if candidate.get("alias") == candidate_alias:
            return {
                "alias": candidate.get("alias"),
                "model": candidate.get("model"),
                "reasoning_effort": candidate.get("reasoning_effort"),
            }
    raise ValueError(
        f"Telemetry candidate alias is not routed for this dispatch: {candidate_alias}"
    )


def telemetry_start(
    root: Path,
    plugin_root: Path,
    policy: dict[str, Any],
    domain: str,
    *,
    kind: str,
    attempt: int,
    until: str,
    candidate_alias: str | None = None,
) -> dict[str, Any]:
    state = _load_state(root, domain)
    envelope = dispatch_envelope(
        root,
        plugin_root,
        policy,
        domain,
        state,
        attempt=attempt,
        until=until,
    )
    if envelope.get("status") != "dispatch_required":
        raise ValueError(
            "Telemetry can start only while the lifecycle requires a hosted dispatch"
        )
    payload = envelope.get(kind)
    if not payload:
        raise ValueError(f"No {kind} dispatch is routed for the current lifecycle action")

    candidate = _telemetry_candidate(payload, candidate_alias)
    started_epoch = time.time()
    dispatch_id = hashlib.sha256(
        (
            f"{envelope['fingerprint']}|{attempt}|{kind}|"
            f"{candidate.get('alias')}|{time.time_ns()}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    record = {
        "schema_version": 1,
        "dispatch_id": dispatch_id,
        "fingerprint": envelope["fingerprint"],
        "dispatch_kind": kind,
        "attempt": int(attempt),
        "task_name": payload.get("task_name"),
        "role": payload.get("role"),
        "model_alias": candidate.get("alias"),
        "model": candidate.get("model"),
        "reasoning_effort": candidate.get("reasoning_effort"),
        "action": envelope.get("action") or {},
        "started_at": _utc_timestamp(started_epoch),
    }
    inflight = dict(record)
    inflight["started_epoch"] = started_epoch
    inflight_path = _telemetry_inflight_path(root, domain, dispatch_id)
    inflight_path.parent.mkdir(parents=True, exist_ok=True)
    inflight_path.write_text(
        json.dumps(inflight, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _append_telemetry(root, domain, {"event": "start", **record})
    return {
        "status": "started",
        "dispatch_id": dispatch_id,
        "telemetry_path": str(_telemetry_path(root, domain)),
    }


def telemetry_finish(
    root: Path,
    domain: str,
    *,
    dispatch_id: str,
    outcome: str,
) -> dict[str, Any]:
    inflight_path = _telemetry_inflight_path(root, domain, dispatch_id)
    if not inflight_path.is_file():
        raise ValueError(f"Telemetry dispatch is not inflight: {dispatch_id}")
    inflight = json.loads(inflight_path.read_text(encoding="utf-8"))
    started_epoch = float(inflight.pop("started_epoch"))
    finished_epoch = time.time()
    record = {
        **inflight,
        "event": "finish",
        "outcome": outcome,
        "finished_at": _utc_timestamp(finished_epoch),
        "duration_seconds": round(max(0.0, finished_epoch - started_epoch), 3),
    }
    _append_telemetry(root, domain, record)
    inflight_path.unlink()
    return {
        "status": "recorded",
        "dispatch_id": dispatch_id,
        "duration_seconds": record["duration_seconds"],
        "telemetry_path": str(_telemetry_path(root, domain)),
    }


def _host_message(
    root: Path,
    plugin_root: Path,
    domain: str,
    action: dict[str, Any],
    spec: dict[str, Any],
    *,
    scout_max_chars: int | None = None,
) -> str:
    role = str(spec["role"])
    read_only = role in {"scout", "diagnostician"}
    lines = [
        "# DevFlow host-native dispatch",
        "",
        f"Repository root: {root}",
        f"Domain: {domain}",
        f"Role: {role}",
        f"Task: {spec.get('task_id') or action.get('command')}",
        f"Action: {json.dumps(action, ensure_ascii=False, sort_keys=True)}",
        "",
        (
            "This child owns one routed DevFlow action. Do not run `codex exec` "
            "and do not spawn nested agents."
        ),
        (
            "Use repository files and DevFlow runtime output as authority. "
            "Do not depend on parent chat history."
        ),
        "",
        "Run these steps:",
        f"1. Change directory to `{root}`.",
        f"2. Read the role contract at `{_role_contract_path(plugin_root, role)}`.",
        (
            "3. Read current lifecycle state with "
            f"`{_status_command(plugin_root, domain)}`."
        ),
        (
            "4. Render the authoritative action packet with "
            f"`{_render_command(plugin_root, domain, action)}`."
        ),
    ]
    if read_only:
        lines.extend(
            [
                (
                    "5. Perform the routed read-only analysis. Do not mutate source, "
                    "lifecycle files, or runtime state."
                ),
                "6. Return the requested evidence or diagnosis to the parent agent.",
            ]
        )
    else:
        lines.extend(
            [
                (
                    "5. Follow the role contract and rendered packet. Apply every "
                    "required lifecycle mutation before returning."
                ),
                (
                    "6. Re-read lifecycle state with "
                    f"`{_status_command(plugin_root, domain)}` and return a "
                    "concise receipt."
                ),
            ]
        )
    if role == "scout" and scout_max_chars:
        lines.append(
            f"Keep the evidence capsule under {int(scout_max_chars)} characters "
            "so the parent can pass it to the specialist."
        )
    return "\n".join(lines) + "\n"


def _spawn_payload(
    policy: dict[str, Any],
    root: Path,
    plugin_root: Path,
    domain: str,
    action: dict[str, Any],
    spec: dict[str, Any],
    *,
    scout_max_chars: int | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    model = spec.get("model") or {}
    execution = spec.get("execution") or {}
    return {
        "task_name": _task_name(domain, spec),
        "role": spec.get("role"),
        "model": model.get("selected"),
        "model_alias": model.get("alias"),
        "reasoning_effort": model.get("reasoning_effort"),
        "fork_turns": execution.get("native_fork_turns", "none"),
        "permissions": execution.get("permissions", "inherit"),
        "candidates": _candidate_rows(policy, spec),
        "message": (
            message
            if message is not None
            else _host_message(
                root,
                plugin_root,
                domain,
                action,
                spec,
                scout_max_chars=scout_max_chars,
            )
        ),
        "route": spec,
    }


def dispatch_envelope(
    root: Path,
    plugin_root: Path,
    policy: dict[str, Any],
    domain: str,
    state: dict[str, Any],
    *,
    attempt: int = 0,
    until: str = "complete",
) -> dict[str, Any]:
    action = copy.deepcopy(state.get("next_action") or {})
    command = action.get("command")
    boundary = autopilot.ExecutionBoundary(until)
    if command == "complete":
        return {"status": "complete", "action": action, "execution_boundary": until}
    if command == "decision" or action.get("role") == "human":
        return {"status": "paused", "action": action, "execution_boundary": until}
    if boundary.reached(state, action):
        return {
            "status": "checkpoint",
            "reason": "execution_boundary_reached",
            "action": action,
            "execution_boundary": until,
        }

    primary_spec = _host_route(policy, action, state, attempt)
    scout_max_chars = int(
        (policy.get("orchestration") or {}).get("scout_max_chars", 12000)
    )
    scout_payload = None
    if primary_spec.get("role") in set(
        (policy.get("orchestration") or {}).get("scout_before", [])
    ):
        scout_action = copy.deepcopy(action)
        scout_action["_role_override"] = "scout"
        scout_spec = _host_route(policy, scout_action, state, attempt)
        if (scout_spec.get("model") or {}).get("selected") != (
            primary_spec.get("model") or {}
        ).get("selected"):
            scout_payload = _spawn_payload(
                policy,
                root,
                plugin_root,
                domain,
                action,
                scout_spec,
                scout_max_chars=scout_max_chars,
            )

    retries = policy.get("escalation", {}).get("retries", {}) or {}
    return {
        "status": "dispatch_required",
        "execution_boundary": until,
        "fingerprint": autopilot.AutopilotController.fingerprint(action),
        "attempt": int(attempt),
        "action": action,
        "scout": scout_payload,
        "primary": _spawn_payload(
            policy,
            root,
            plugin_root,
            domain,
            action,
            primary_spec,
        ),
        "retry": {
            "max_no_progress": int(retries.get("max_no_progress", 3)),
            "diagnose_at": int(retries.get("diagnose_at", 2)),
        },
    }


def bootstrap_envelope(
    root: Path,
    plugin_root: Path,
    policy: dict[str, Any],
    domain: str,
    requirements: Path,
    risk: str,
) -> dict[str, Any]:
    if devflow.state_path(root, domain).exists():
        raise ValueError(f"Domain already initialized: {domain}")
    if not requirements.is_file():
        raise ValueError(f"Requirements file not found: {requirements}")

    action = {"command": "bootstrap", "scope": "project"}
    spec = _host_route(policy, action, {"risk_profile": risk}, 0)
    target = devflow.domain_dir(root, domain) / "PRD.md"
    contract = plugin_root / "core" / "prompts" / "bootstrap.md"
    message = (
        "\n".join(
            [
                "# DevFlow host-native bootstrap",
                "",
                f"Repository root: {root}",
                f"Target PRD path: {target}",
                f"Approved requirements file: {requirements}",
                f"Bootstrap contract: {contract}",
                "",
                "Do not run `codex exec` and do not spawn nested agents.",
                "Read the bootstrap contract and approved requirements from disk.",
                (
                    "Write only the requested PRD to the target path. Preserve requirement "
                    "and acceptance IDs exactly."
                ),
                (
                    "Do not initialize the domain or mutate lifecycle state. Return a "
                    "concise receipt to the parent agent."
                ),
            ]
        )
        + "\n"
    )
    payload = _spawn_payload(
        policy,
        root,
        plugin_root,
        domain,
        action,
        spec,
        message=message,
    )
    return {
        "status": "dispatch_required",
        "bootstrap": True,
        "target": str(target),
        "primary": payload,
    }


def bootstrap_finalize(root: Path, domain: str, risk: str) -> dict[str, Any]:
    if devflow.state_path(root, domain).exists():
        raise ValueError(f"Domain already initialized: {domain}")
    target = devflow.domain_dir(root, domain) / "PRD.md"
    errors = devflow.required_markdown_section_errors(target, "PRD.md")
    if errors:
        return {"status": "blocked", "errors": errors, "target": str(target)}
    with contextlib.redirect_stdout(io.StringIO()):
        devflow.init_domain(
            argparse.Namespace(
                domain=domain,
                risk=risk,
                workflow="delivery",
                extension="default",
                prd=None,
                force=False,
            )
        )
    return {"status": "initialized", "target": str(target)}


def _load_state(root: Path, domain: str) -> dict[str, Any]:
    path = devflow.state_path(root, domain)
    if not path.exists():
        raise ValueError(f"Domain not initialized: {domain}")
    raw = devflow.load_yaml(path, {}) or {}
    return devflow.project_state(root, domain, copy.deepcopy(raw))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devflow-host",
        description=(
            "Prepare host-native DevFlow sub-agent dispatches without nested "
            "codex exec sessions."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("domain")
    dispatch.add_argument("--attempt", type=int, default=0)
    dispatch.add_argument(
        "--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete"
    )

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("domain")
    bootstrap.add_argument("--requirements-file", required=True)
    bootstrap.add_argument(
        "--risk", choices=sorted(devflow.RISK_LEVELS), default="medium"
    )

    finalize = sub.add_parser("bootstrap-finalize")
    finalize.add_argument("domain")
    finalize.add_argument(
        "--risk", choices=sorted(devflow.RISK_LEVELS), default="medium"
    )

    telemetry_start_parser = sub.add_parser("telemetry-start")
    telemetry_start_parser.add_argument("domain")
    telemetry_start_parser.add_argument(
        "--kind", choices=["scout", "primary"], required=True
    )
    telemetry_start_parser.add_argument("--attempt", type=int, default=0)
    telemetry_start_parser.add_argument(
        "--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete"
    )
    telemetry_start_parser.add_argument("--candidate-alias")

    telemetry_finish_parser = sub.add_parser("telemetry-finish")
    telemetry_finish_parser.add_argument("domain")
    telemetry_finish_parser.add_argument("--dispatch-id", required=True)
    telemetry_finish_parser.add_argument(
        "--outcome",
        choices=["completed", "failed", "cancelled", "capability_blocked"],
        required=True,
    )
    return parser


def main() -> int:
    try:
        devflow.configure_work_schema()
        args = build_parser().parse_args()
        root = devflow.repo_root()
        plugin_root = devflow.plugin_root()
        policy = autopilot.load_policy(plugin_root, root)

        if args.command == "dispatch":
            state = _load_state(root, args.domain)
            if (
                args.until != "complete"
                and devflow.effective_workflow_type(state) != "delivery"
            ):
                raise ValueError(
                    "Staged execution boundaries are supported only for delivery "
                    "workflows"
                )
            result = dispatch_envelope(
                root,
                plugin_root,
                policy,
                args.domain,
                state,
                attempt=args.attempt,
                until=args.until,
            )
        elif args.command == "bootstrap":
            result = bootstrap_envelope(
                root,
                plugin_root,
                policy,
                args.domain,
                Path(args.requirements_file).resolve(),
                args.risk,
            )
        elif args.command == "bootstrap-finalize":
            result = bootstrap_finalize(root, args.domain, args.risk)
        elif args.command == "telemetry-start":
            result = telemetry_start(
                root,
                plugin_root,
                policy,
                args.domain,
                kind=args.kind,
                attempt=args.attempt,
                until=args.until,
                candidate_alias=args.candidate_alias,
            )
        elif args.command == "telemetry-finish":
            result = telemetry_finish(
                root,
                args.domain,
                dispatch_id=args.dispatch_id,
                outcome=args.outcome,
            )
        else:
            raise AssertionError(f"Unhandled host command: {args.command}")

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") == "blocked" else 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if "args" in locals() and getattr(args, "command", None) in TELEMETRY_COMMANDS:
            print(
                json.dumps(
                    {"status": "telemetry_unavailable", "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(f"DevFlow host error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
