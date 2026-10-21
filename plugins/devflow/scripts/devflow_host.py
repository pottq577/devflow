#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
import shlex
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import devflow
import devflow_traceability as traceability
import devflow_autopilot as autopilot
import devflow_session as session
import devflow_host_guard as guard
import devflow_scout as scout_contract
from devflow_postman import strict_json

HOST_BACKEND = "host_native_agent"
TELEMETRY_FILENAME = "host-dispatch.jsonl"
TELEMETRY_INFLIGHT_DIR = "host-dispatch-inflight"
TELEMETRY_COMMANDS = {"telemetry-start", "telemetry-finish"}
SCOUT_POINTER_FILENAME = "scout-current.json"
SCOUT_COMMANDS = {"scout-bind", "scout-validate"}


_ROUTING_CACHE: dict[str, Any] = {}


def _host_capabilities(policy: dict[str, Any]) -> autopilot.CapabilityRegistry:
    registry = _host_registry(policy)
    native_models = {
        registry.model_id(alias)
        for alias in registry.aliases()
        if registry.meta(alias).get("multi_agent")
    }
    return autopilot.CapabilityRegistry(
        registry,
        native_models=native_models,
        exec_available=False,
        codex_path=None,
        codex_version=None,
    )


def _host_registry(policy: dict[str, Any]) -> autopilot.ModelRegistry:
    """Build the registry once per CLI process; policy YAML is read only at startup."""
    key = json.dumps(
        policy.get("model_registry") or policy.get("models") or {},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    registry = _ROUTING_CACHE.get(key)
    if registry is None:
        registry = autopilot.ModelRegistry.from_policy(policy)
        _ROUTING_CACHE[key] = registry
    return registry


def _host_router(policy: dict[str, Any]) -> autopilot.RouteEngine:
    """One engine per routing policy; every policy that can change routing gets its own."""
    key = "engine:" + json.dumps(policy, ensure_ascii=False, sort_keys=True, default=str)
    engine = _ROUTING_CACHE.get(key)
    if engine is None:
        host_policy = copy.deepcopy(policy)
        host_policy.setdefault("backends", {})["preference"] = ["native_agent"]
        engine = autopilot.RouteEngine(host_policy, _host_capabilities(host_policy))
        _ROUTING_CACHE[key] = engine
    return engine


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
    registry = _host_registry(policy)
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


def _render_command(
    plugin_root: Path,
    domain: str,
    action: dict[str, Any],
    *,
    no_refresh: bool = False,
    expected_head: str | None = None,
    check_only: bool = False,
    evidence: bool = False,
) -> str:
    command = str(action.get("command") or "")
    base = [
        sys.executable,
        str(plugin_root / "scripts" / "devflow.py"),
        "render",
        "evidence" if evidence else command,
        domain,
    ]
    if not evidence and command == "run" and action.get("work_item"):
        base.extend(["--task", str(action["work_item"])])
    elif not evidence and command == "audit":
        scope = action.get("scope")
        if not scope:
            raise ValueError("Audit host dispatch requires scope")
        base.extend(["--scope", str(scope)])
        if action.get("work_item"):
            base.extend(["--task", str(action["work_item"])])
        if action.get("phase") is not None:
            base.extend(["--phase", str(action["phase"])])
        base.extend(["--mode", str(action.get("mode") or "initial")])
    elif not evidence and command not in {"plan", "finalize"}:
        raise ValueError(f"Action cannot be rendered for host dispatch: {command}")
    if no_refresh:
        base.append("--no-refresh")
    base.extend(["--expected-head", expected_head or "unborn",
                 "--expected-fingerprint", autopilot.AutopilotController.fingerprint(action)])
    if check_only:
        base.append("--check-only")
    return " ".join(shlex.quote(part) for part in base)


def _status_command(
    plugin_root: Path, domain: str, *, no_refresh: bool = False
) -> str:
    parts = [
        sys.executable,
        str(plugin_root / "scripts" / "devflow.py"),
        "status",
        domain,
    ]
    if no_refresh:
        parts.append("--no-refresh")
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


def prune_telemetry_inflight(runtime_dir: Path, keep_step_id: str | None) -> int:
    """Drop settled telemetry inflight files; the live reserved step is always preserved."""
    directory = runtime_dir / TELEMETRY_INFLIGHT_DIR
    if not directory.is_dir():
        return 0
    removed = 0
    for path in sorted(directory.glob("*.json")):
        if keep_step_id:
            try:
                record = strict_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = None
            if isinstance(record, dict) and record.get("step_id") == keep_step_id:
                continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        removed += 1
    return removed


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


def _telemetry_observations(
    file_path: str | None, previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields = {
        "context_bytes": {"packet", "protocol", "capsule"},
        "stage_duration_seconds": {"packet_render", "spawn", "child_wait"},
    }
    observations = copy.deepcopy(previous) if previous is not None else {
        group: {key: None for key in sorted(keys)} for group, keys in fields.items()
    }
    observations["source"] = "caller_reported"
    if file_path is None:
        return observations
    with Path(file_path).open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Telemetry observations exceed 64 KiB")
    supplied = strict_json(raw.decode("utf-8"))
    if not isinstance(supplied, dict) or set(supplied) - {*fields, "source"}:
        raise ValueError("Telemetry observations contain unsupported fields")
    if "source" in supplied and supplied["source"] != "caller_reported":
        raise ValueError("Telemetry observation source must be caller_reported")
    for group, keys in fields.items():
        if group not in supplied:
            continue
        values = supplied[group]
        if not isinstance(values, dict) or set(values) - keys:
            raise ValueError(f"Telemetry {group} contains unsupported fields")
        for key, value in values.items():
            if value is not None:
                numeric = type(value) is int if group == "context_bytes" else type(value) in {int, float}
                if not numeric or value < 0 or not math.isfinite(value):
                    raise ValueError(f"Telemetry {group}.{key} must be a finite nonnegative number")
            observations[group][key] = value
    return observations


def telemetry_start(
    root: Path,
    plugin_root: Path,
    policy: dict[str, Any],
    domain: str,
    *,
    kind: str,
    attempt: int | None,
    until: str,
    candidate_alias: str | None = None,
    session_id: str | None = None,
    step_id: str | None = None,
    observations_file: str | None = None,
) -> dict[str, Any]:
    if attempt is None:
        return {
            "status": "telemetry_unavailable",
            "reason": "telemetry_attempt_missing",
            "error": "Telemetry requires --attempt from the reserved step",
        }
    if type(attempt) is not int or attempt < 0:
        raise guard.GuardBlocked("telemetry_attempt_invalid")
    prepare_started = time.perf_counter()
    observations = _telemetry_observations(observations_file)
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
    guard.require_reserved_step(
        _telemetry_dir(root, domain), session_id, step_id,
        fingerprint=envelope["fingerprint"], kind=kind, attempt=attempt,
        candidate_alias=candidate["alias"],
    )
    started_epoch = time.time()
    prune_telemetry_inflight(_telemetry_dir(root, domain), step_id)
    dispatch_id = hashlib.sha256(
        (
            f"{envelope['fingerprint']}|{attempt}|{kind}|"
            f"{candidate.get('alias')}|{time.time_ns()}"
        ).encode("utf-8")
    ).hexdigest()[:24]
    record = {
        "schema_version": 3,
        "dispatch_id": dispatch_id,
        "step_id": step_id,
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
        "token_usage": "unmeasured",
        "observations": observations,
    }
    observations["stage_duration_seconds"]["telemetry_prepare"] = round(
        max(0.0, time.perf_counter() - prepare_started), 6
    )
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
    session_id: str | None = None,
    step_id: str | None = None,
    observations_file: str | None = None,
) -> dict[str, Any]:
    inflight_path = _telemetry_inflight_path(root, domain, dispatch_id)
    if not inflight_path.is_file():
        raise ValueError(f"Telemetry dispatch is not inflight: {dispatch_id}")
    inflight = json.loads(inflight_path.read_text(encoding="utf-8"))
    if inflight.get("step_id") != step_id or not step_id:
        raise ValueError("Telemetry step id does not match the start record")
    guard.require_reserved_step(
        _telemetry_dir(root, domain), session_id, step_id,
        fingerprint=inflight["fingerprint"], kind=inflight["dispatch_kind"],
        attempt=inflight["attempt"], candidate_alias=inflight["model_alias"],
    )
    if inflight.get("schema_version") == 3:
        inflight["observations"] = _telemetry_observations(
            observations_file, inflight["observations"],
        )
    elif observations_file is not None:
        raise ValueError("Legacy telemetry cannot accept observations; finish without --observations-file")
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
    scout_backed: bool = False,
    expected_head: str | None = None,
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
        (
            "The pinned render/check-only below replaces the role contract's initial status "
            "and render preflight. Do not repeat either before work. Keep post-mutation status."
        ),
        "",
        "Run these steps:",
        f"1. Change directory to `{root}`.",
        f"2. Read the role contract at `{_role_contract_path(plugin_root, role)}`.",
        "If pinned render validation fails, stop without mutation and return the blocker to the parent; do not select another action.",
    ]
    if scout_backed and role in autopilot.ContextAssembler.COMPACT_PACKET_ROLES:
        lines.extend(
            [
                (
                    "3. Validate the pinned action and HEAD without rendering a packet with "
                    f"`{_render_command(plugin_root, domain, action, no_refresh=read_only, expected_head=expected_head, check_only=True)}`."
                ),
                (
                    "4. Use the `## Repository scout` capsule appended by the parent "
                    "as a navigation/evidence index. Do not repeat repository-wide discovery."
                ),
                (
                    "5. Verify the scout's cited files, symbols, tests, and constraints "
                    "directly. Only if material evidence is missing or contradictory, "
                    "render the authoritative action packet with "
                    f"`{_render_command(plugin_root, domain, action, no_refresh=read_only, expected_head=expected_head)}`."
                ),
            ]
        )
        action_step = 6
    elif role == "scout":
        lines.append(
            "3. Read the bounded evidence index for this action with "
            f"`{_render_command(plugin_root, domain, action, no_refresh=read_only, expected_head=expected_head, evidence=True)}`."
        )
        lines.append(
            "4. Explore the repository only for the files, symbols and tests that index cites, "
            "plus the current failing evidence. Do not load the full action protocol, PRD, PLAN "
            "or WORK bodies to rediscover navigation facts."
        )
        action_step = 5
    elif role == "diagnostician":
        lines.append(
            "3. Read the bounded evidence index for this stalled WORK with "
            f"`{_render_command(plugin_root, domain, action, no_refresh=True, expected_head=expected_head, evidence=True)}`."
        )
        lines.append(
            "4. Diagnose from the index's objective, acceptance ids, verification commands, "
            "recorded verification output, evidence files, block or external-wait reason and "
            "delivery index, plus the repository sources and command output they cite. Render the "
            "full authoritative run packet only when you must judge the execution contract itself."
        )
        action_step = 5
    else:
        lines.append(
            "3. Render the authoritative action packet and validate the pinned action and HEAD with "
            f"`{_render_command(plugin_root, domain, action, no_refresh=read_only, expected_head=expected_head)}`."
        )
        action_step = 4
    if read_only:
        lines.extend(
            [
                (
                    f"{action_step}. Perform the routed read-only analysis. Do not mutate "
                    "source, lifecycle files, or runtime state."
                ),
                f"{action_step + 1}. Return the requested evidence or diagnosis to the parent agent.",
            ]
        )
    else:
        lines.extend(
            [
                (
                    f"{action_step}. Follow the role contract and available authoritative "
                    "evidence. Apply every required lifecycle mutation before returning."
                ),
                (
                    f"{action_step + 1}. Re-read lifecycle state with "
                    f"`{_status_command(plugin_root, domain)}` and return a "
                    "concise receipt."
                ),
            ]
        )
    if role == "scout" and scout_max_chars:
        lines.append(
            f"Keep the complete six-section evidence capsule within {int(scout_max_chars)} "
            "characters. Include exact file paths under `## Evidence map`. "
            "The parent rejects malformed or oversized capsules instead of truncating them."
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
    expected_head: str | None = None,
) -> dict[str, Any]:
    model = spec.get("model") or {}
    execution = spec.get("execution") or {}
    payload = {
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
                expected_head=expected_head,
            )
        ),
        "route": spec,
    }
    if (
        message is None
        and spec.get("role") in autopilot.ContextAssembler.COMPACT_PACKET_ROLES
    ):
        payload["scout_message"] = _host_message(
            root,
            plugin_root,
            domain,
            action,
            spec,
            scout_max_chars=scout_max_chars,
            scout_backed=True,
            expected_head=expected_head,
        )
    return payload


def dispatch_envelope(
    root: Path,
    plugin_root: Path,
    policy: dict[str, Any],
    domain: str,
    state: dict[str, Any],
    *,
    attempt: int = 0,
    until: str = "complete",
    scout_cached: bool = False,
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
    orchestration = policy.get("orchestration") or {}
    scout_max_chars = int(orchestration.get("scout_max_chars", 12000))
    scout_payload = None
    # A cached capsule skips the scout only while the host itself still verifies it.
    reused = scout_cached and _scout_capsule_current(root, domain, state, policy)
    if autopilot.should_run_scout(
        primary_spec,
        attempt,
        scout_before=set(orchestration.get("scout_before", [])),
        scout_on_retry=set(orchestration.get("scout_on_retry", [])),
        scout_on_critical=set(orchestration.get("scout_on_critical", [])),
        scout_cached=reused,
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
                expected_head=state.get("target_sha"),
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
            expected_head=state.get("target_sha"),
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
        "fingerprint": autopilot.AutopilotController.fingerprint(action),
        "attempt": 0,
        "target": str(target),
        "primary": payload,
    }


def bootstrap_finalize(root: Path, domain: str, risk: str) -> dict[str, Any]:
    if devflow.state_path(root, domain).exists():
        raise ValueError(f"Domain already initialized: {domain}")
    target = devflow.domain_dir(root, domain) / "PRD.md"
    errors = devflow.required_markdown_section_errors(target, "PRD.md")
    if not errors:
        source_errors, _ = traceability.validate_domain(
            target.parent, {}, require_plan=False, require_decisions=False,
            strict=(target.parent / "sources/v1/manifest.json").is_file(),
        )
        errors.extend(source_errors)
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


def _read_stable_file(path: Path, max_bytes: int) -> bytes | None:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            return None
        chunks = []
        size = 0
        while size <= max_bytes:
            chunk = os.read(descriptor, min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        current = path.lstat()
        identity = lambda value: (
            value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
        )
        if (
            size != before.st_size
            or identity(before) != identity(after)
            or identity(after) != identity(current)
        ):
            return None
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _scout_capsule_record(file_path: Path) -> dict[str, Any]:
    payload = _read_stable_file(file_path.with_suffix(".evidence.json"), 65536)
    if payload is None:
        return {}
    try:
        value = strict_json(payload.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _write_scout_capsule_record(
    file_path: Path, runtime_dir: Path, binding: dict[str, Any]
) -> None:
    """Bind creation provenance once; the sidecar and the current-capsule pointer agree."""
    _write_json_atomic(file_path.with_suffix(".evidence.json"), binding)
    _write_json_atomic(
        runtime_dir / SCOUT_POINTER_FILENAME, {**binding, "capsule_file": str(file_path)}
    )


def _scout_capsule_current(
    root: Path, domain: str, state: dict[str, Any], policy: dict[str, Any],
    capsule_file: Path | None = None, *, evidence: tuple | None = None,
) -> bool:
    """Re-verify the recorded capsule host-side; the caller's claim is never the authority.

    `evidence` is the (index, scope, confirmed, digest) tuple this invocation already computed
    and verified, so one CLI run never rebuilds the same WORK snapshot or scope twice.
    """
    runtime_dir = _telemetry_dir(root, domain)
    pointer_path = runtime_dir / SCOUT_POINTER_FILENAME
    try:
        pointer = _read_stable_file(pointer_path, 65536)
        if pointer is None:
            return False
        record = strict_json(pointer.decode("utf-8"))
    except (UnicodeError, ValueError):
        return False
    if not isinstance(record, dict) or not isinstance(record.get("capsule_file"), str):
        return False
    allowed = (runtime_dir / "scout-capsules").resolve()
    try:
        file_path = Path(record["capsule_file"]).resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    if not file_path.is_relative_to(allowed):
        return False
    if capsule_file is not None and file_path != capsule_file:
        return False
    sidecar = _scout_capsule_record(file_path)
    if not sidecar or {key: value for key, value in record.items() if key != "capsule_file"} != sidecar:
        return False
    cap = int((policy.get("orchestration") or {}).get("scout_max_chars", 12000))
    try:
        payload = _read_stable_file(file_path, cap * 4 + 1)
        text = payload.decode("utf-8") if payload is not None else ""
    except UnicodeError:
        return False
    if evidence is None:
        with devflow._work_snapshot():
            index = devflow.evidence_index(root, domain, state)
            scope, confirmed = devflow.evidence_scope(root, index)
        digest = scout_contract.evidence_digest(index, scope)
    else:
        index, scope, confirmed, digest = evidence
    return (
        scout_contract.capsule_verdict(
            text,
            record,
            fingerprint=autopilot.AutopilotController.fingerprint(
                state.get("next_action") or {}
            ),
            digest=digest,
            scope_confirmed=confirmed,
            max_chars=cap,
        )
        == "valid"
    )


def _guard_view(
    root: Path, domain: str, owner: str, policy: dict[str, Any], until: str,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    state = _load_state(root, domain) if devflow.state_path(root, domain).exists() else None
    action = (state or {}).get("next_action") or {"command": "bootstrap", "scope": "project"}
    fingerprint = autopilot.AutopilotController.fingerprint(action)
    if state is not None and until != "complete" and devflow.effective_workflow_type(state) != "delivery":
        raise ValueError("Staged execution boundaries are supported only for delivery workflows")
    terminal = bool(state is not None and (
        action.get("command") == "complete"
        or action.get("role") == "human"
        or action.get("command") == "decision"
        or autopilot.ExecutionBoundary(until).reached(state, action)
    ))
    safety = guard.inspect(
        _telemetry_dir(root, domain), owner, fingerprint, policy, terminal=terminal
    )
    return state, fingerprint, safety


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devflow-host",
        description=(
            "Prepare host-native DevFlow sub-agent dispatches without nested "
            "codex exec sessions."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    session_start = sub.add_parser("session-start")
    session_start.add_argument("domain")
    session_start.add_argument("--session-id")  # resume existing owner only
    session_end = sub.add_parser("session-end")
    session_end.add_argument("domain")
    session_end.add_argument("--session-id", required=True)
    session_checkpoint = sub.add_parser("session-checkpoint")
    session_checkpoint.add_argument("domain")
    session_checkpoint.add_argument("--session-id", required=True)
    session_recover = sub.add_parser("session-recover")
    session_recover.add_argument("domain")
    session_recover.add_argument("--session-id", required=True)
    session_recover.add_argument("--step-id", required=True)
    session_recover.add_argument("--outcome", choices=sorted(guard.OUTCOMES), required=True)
    session_recover.add_argument("--confirm-child-terminated", action="store_true")
    session_recover.add_argument("--termination-evidence", required=True)
    session_status = sub.add_parser("session-status")
    session_status.add_argument("domain")

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("domain")
    dispatch.add_argument("--session-id", required=True)
    dispatch.add_argument("--attempt", type=int)  # optional assertion, never a reset
    dispatch.add_argument(
        "--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete"
    )
    dispatch.add_argument(
        "--scout-cached",
        action="store_true",
        help="Claim a reusable scout capsule; the host re-verifies its binding before reusing it",
    )

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("domain")
    bootstrap.add_argument("--session-id", required=True)
    bootstrap.add_argument("--requirements-file", required=True)
    bootstrap.add_argument(
        "--risk", choices=sorted(devflow.RISK_LEVELS), default="medium"
    )

    finalize = sub.add_parser("bootstrap-finalize")
    finalize.add_argument("domain")
    finalize.add_argument("--session-id", required=True)
    finalize.add_argument(
        "--risk", choices=sorted(devflow.RISK_LEVELS), default="medium"
    )

    step_start = sub.add_parser("step-start")
    step_start.add_argument("domain")
    step_start.add_argument("--session-id", required=True)
    step_start.add_argument("--kind", choices=["bootstrap", "scout", "primary"], required=True)
    step_start.add_argument("--fingerprint", required=True)
    step_start.add_argument("--candidate-alias", required=True)
    step_start.add_argument("--attempt", type=int, required=True)
    step_start.add_argument("--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete")
    step_start.add_argument("--risk", choices=sorted(devflow.RISK_LEVELS), default="medium")

    step_finish = sub.add_parser("step-finish")
    step_finish.add_argument("domain")
    step_finish.add_argument("--session-id", required=True)
    step_finish.add_argument("--step-id", required=True)
    step_finish.add_argument("--outcome", choices=["completed", "failed", "cancelled", "capability_blocked"], required=True)
    step_finish.add_argument("--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete")

    guard_status = sub.add_parser("guard-status")
    guard_status.add_argument("domain")
    guard_status.add_argument("--session-id", required=True)
    guard_status.add_argument("--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete")

    telemetry_start_parser = sub.add_parser("telemetry-start")
    telemetry_start_parser.add_argument("domain")
    telemetry_start_parser.add_argument(
        "--kind", choices=["scout", "primary"], required=True
    )
    telemetry_start_parser.add_argument("--attempt", type=int)
    telemetry_start_parser.add_argument(
        "--until", choices=autopilot.ExecutionBoundary.VALUES, default="complete"
    )
    telemetry_start_parser.add_argument("--candidate-alias")
    telemetry_start_parser.add_argument("--session-id")
    telemetry_start_parser.add_argument("--step-id")
    telemetry_start_parser.add_argument("--observations-file")

    telemetry_finish_parser = sub.add_parser("telemetry-finish")
    telemetry_finish_parser.add_argument("domain")
    telemetry_finish_parser.add_argument("--dispatch-id", required=True)
    telemetry_finish_parser.add_argument("--session-id")
    telemetry_finish_parser.add_argument("--step-id")
    telemetry_finish_parser.add_argument("--observations-file")
    telemetry_finish_parser.add_argument(
        "--outcome",
        choices=["completed", "failed", "cancelled", "capability_blocked"],
        required=True,
    )
    scout_check = sub.add_parser("scout-validate")
    scout_check.add_argument("domain")
    scout_check.add_argument("--session-id", required=True)
    scout_check.add_argument("--fingerprint", required=True)
    scout_check.add_argument("--capsule-file", required=True)
    scout_bind = sub.add_parser("scout-bind")
    scout_bind.add_argument("domain")
    scout_bind.add_argument("--session-id", required=True)
    scout_bind.add_argument("--fingerprint", required=True)
    scout_bind.add_argument("--capsule-file", required=True)
    scout_bind.add_argument("--step-id", required=True)
    scout_bind.add_argument("--model-alias", required=True)
    return parser


def main() -> int:
    try:
        devflow.configure_work_schema()
        args = build_parser().parse_args()
        root = devflow.repo_root()
        plugin_root = devflow.plugin_root()
        policy = autopilot.load_policy(plugin_root, root)

        runtime_dir = _telemetry_dir(root, args.domain)
        # Observation verifies ownership without extending the lease; a lifecycle edge renews it.
        if args.command in {"dispatch", "guard-status"} | SCOUT_COMMANDS:
            session.require(runtime_dir, args.session_id)
        if args.command in {"bootstrap", "bootstrap-finalize", "step-start", "step-finish"}:
            session.renew(runtime_dir, args.session_id)

        if args.command == "session-start":
            result = session.start(runtime_dir, session_id=args.session_id)
        elif args.command == "session-end":
            result = session.end(runtime_dir, args.session_id)
        elif args.command == "session-checkpoint":
            state = _load_state(root, args.domain) if devflow.state_path(root, args.domain).exists() else None
            action = (state or {}).get("next_action") or {"command": "bootstrap", "scope": "project"}
            fingerprint = autopilot.AutopilotController.fingerprint(action)
            result = guard.checkpoint(runtime_dir, args.session_id, fingerprint, policy)
        elif args.command == "session-recover":
            state = _load_state(root, args.domain) if devflow.state_path(root, args.domain).exists() else None
            action = (state or {}).get("next_action") or {"command": "bootstrap", "scope": "project"}
            fingerprint = autopilot.AutopilotController.fingerprint(action)
            result = guard.recover(
                runtime_dir, args.session_id, args.step_id, fingerprint, policy,
                outcome=args.outcome, confirm_child_terminated=args.confirm_child_terminated,
                termination_evidence=args.termination_evidence,
            )
        elif args.command == "session-status":
            result = session.status(runtime_dir)
        elif args.command == "dispatch":
            state, fingerprint, safety = _guard_view(
                root, args.domain, args.session_id, policy, args.until
            )
            if state is None:
                raise ValueError("Domain not initialized; use bootstrap first")
            if safety["status"] == "blocked":
                result = {"status": "blocked", "reason": safety["reason"], "safety": safety}
            elif args.attempt is not None and args.attempt != safety["attempt"]:
                result = {"status": "blocked", "reason": "hosted_stale_attempt", "safety": safety}
            else:
                result = dispatch_envelope(
                    root, plugin_root, policy, args.domain, state,
                    attempt=safety["attempt"], until=args.until,
                    scout_cached=args.scout_cached,
                )
                result["safety"] = safety
        elif args.command == "bootstrap":
            state, fingerprint, safety = _guard_view(
                root, args.domain, args.session_id, policy, "complete"
            )
            if state is not None:
                raise ValueError("Domain already initialized")
            if safety["status"] == "blocked":
                result = {"status": "blocked", "reason": safety["reason"], "safety": safety}
            else:
                result = bootstrap_envelope(
                    root, plugin_root, policy, args.domain,
                    Path(args.requirements_file).resolve(), args.risk,
                )
                result["safety"] = safety
        elif args.command == "bootstrap-finalize":
            result = bootstrap_finalize(root, args.domain, args.risk)
        elif args.command == "guard-status":
            _state, _fingerprint, result = _guard_view(
                root, args.domain, args.session_id, policy, args.until
            )
        elif args.command == "step-start":
            state, fingerprint, safety = _guard_view(
                root, args.domain, args.session_id, policy, args.until
            )
            if args.fingerprint != fingerprint:
                raise guard.GuardBlocked("hosted_stale_fingerprint")
            if args.kind == "bootstrap":
                if state is not None:
                    raise guard.GuardBlocked("hosted_bootstrap_already_initialized")
                bootstrap_action = {"command": "bootstrap", "scope": "project"}
                spec = _host_route(policy, bootstrap_action, {"risk_profile": args.risk}, 0)
                candidates = _candidate_rows(policy, spec)
                candidates.append({"alias": spec["model"]["alias"]})
            else:
                if state is None:
                    raise guard.GuardBlocked("hosted_domain_not_initialized")
                envelope = dispatch_envelope(
                    root, plugin_root, policy, args.domain, state,
                    attempt=safety["attempt"], until=args.until,
                )
                payload = envelope.get(args.kind)
                if envelope["status"] != "dispatch_required" or not payload:
                    raise guard.GuardBlocked("hosted_step_not_routed")
                candidates = payload.get("candidates") or []
                candidates = [*candidates, {"alias": payload["model_alias"]}]
            if args.candidate_alias not in {row["alias"] for row in candidates}:
                raise guard.GuardBlocked("hosted_candidate_not_routed")
            metadata = None
            if args.kind == "scout":
                # One WORK snapshot per invocation: the index, scope and digest are built once.
                with devflow._work_snapshot():
                    evidence = devflow.evidence_index(root, args.domain, state)
                    scope, confirmed = devflow.evidence_scope(root, evidence)
                metadata = {
                    "evidence_digest": scout_contract.evidence_digest(evidence, scope),
                    "scope": scope,
                    "scope_confirmed": confirmed,
                    "head_sha": devflow.current_sha(root),
                }
            result = guard.begin(
                runtime_dir, args.session_id, fingerprint, policy,
                kind=args.kind, expected_attempt=args.attempt,
                candidate_alias=args.candidate_alias,
                metadata=metadata,
            )
        elif args.command == "step-finish":
            _state, fingerprint, _safety = _guard_view(
                root, args.domain, args.session_id, policy, args.until
            )
            # The ordinary preview is blocked by the pending step; only finish may clear it.
            result = guard.finish(
                runtime_dir, args.session_id, args.step_id, fingerprint, policy,
                outcome=args.outcome,
            )
        elif args.command in SCOUT_COMMANDS:
            # One WORK snapshot for this read-only command: the projected state, the evidence
            # index, the scope and the digest all read the same parsed documents.
            with devflow._work_snapshot():
                state, fingerprint, _safety = _guard_view(
                    root, args.domain, args.session_id, policy, "complete"
                )
                if args.fingerprint != fingerprint:
                    raise guard.GuardBlocked("hosted_stale_fingerprint")
                allowed = (runtime_dir / "scout-capsules").resolve()
                try:
                    file_path = Path(args.capsule_file).resolve(strict=True)
                except (OSError, RuntimeError):
                    file_path = Path(args.capsule_file).resolve()
                if not file_path.is_relative_to(allowed):
                    raise ValueError("Scout capsule must be under the domain scout-capsules directory")
                cap = int((policy.get("orchestration") or {}).get("scout_max_chars", 12000))
                # Read a bounded UTF-8 payload and reject replacement or mid-read changes.
                raw_capsule = _read_stable_file(file_path, cap * 4 + 1)
                try:
                    text = raw_capsule.decode("utf-8") if raw_capsule is not None else ""
                except UnicodeError:
                    text = ""
                valid = scout_contract.validated_capsule(text, cap)
                index = devflow.evidence_index(root, args.domain, state or {})
                scope, confirmed = devflow.evidence_scope(root, index)
                digest = scout_contract.evidence_digest(index, scope)
                if args.command == "scout-bind":
                    # Only a completed, routed Scout step may create this provenance record.
                    if file_path.name != f"{args.step_id}.md":
                        raise guard.GuardBlocked("hosted_scout_step_mismatch")
                    receipt = guard.consume_scout_step(
                        runtime_dir, args.session_id, args.step_id,
                        fingerprint=fingerprint, candidate_alias=args.model_alias,
                    )
                    metadata = receipt["metadata"]
                    cited = set()
                    for name in scout_contract.evidence_map_paths(valid or ""):
                        relative = Path(name)
                        if ".." in relative.parts:
                            cited.add(name)
                            continue
                        candidate = relative if relative.is_absolute() else root / relative
                        try:
                            cited.add(str(candidate.resolve(strict=True)))
                        except (OSError, RuntimeError):
                            cited.add(name)
                    if (
                        not valid
                    ):
                        result = {"status": "invalid", "chars": len(text), "evidence_digest": digest}
                    elif (
                        metadata.get("scope_confirmed") is not True
                        or not confirmed
                        or metadata.get("evidence_digest") != digest
                        or metadata.get("head_sha") != devflow.current_sha(root)
                        or not cited <= set(metadata.get("scope", {}))
                    ):
                        # Operational diagnostics, not permission to extend the
                        # reserved scope or to re-sign a stale capsule.
                        outside = sorted(cited - set(metadata.get("scope", {})))
                        result = {
                            "status": "stale", "chars": len(text),
                            "evidence_digest": digest,
                            "reserved_scope_confirmed": metadata.get("scope_confirmed"),
                            "current_scope_confirmed": confirmed,
                            "scope_digest_changed": metadata.get("evidence_digest") != digest,
                            "head_changed": metadata.get("head_sha") != devflow.current_sha(root),
                            "cited_outside_scope": outside[:12],
                            "cited_outside_scope_omitted": max(0, len(outside) - 12),
                        }
                    else:
                        _write_scout_capsule_record(
                            file_path,
                            runtime_dir,
                            scout_contract.capsule_binding(
                                text,
                                fingerprint=fingerprint,
                                digest=digest,
                                scope_confirmed=confirmed,
                                head_sha=devflow.current_sha(root) or "unborn",
                                step_id=receipt["step_id"],
                                model_alias=receipt["candidate_alias"],
                                bound_at=datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                        result = {"status": "bound", "chars": len(valid), "evidence_digest": digest}
                else:
                    verdict = scout_contract.capsule_verdict(
                        text,
                        _scout_capsule_record(file_path),
                        fingerprint=fingerprint,
                        digest=digest,
                        scope_confirmed=confirmed,
                        max_chars=cap,
                    )
                    if verdict == "valid" and not _scout_capsule_current(
                        root, args.domain, state or {}, policy, file_path,
                        evidence=(index, scope, confirmed, digest),
                    ):
                        verdict = "stale"
                    result = {
                        "status": verdict,
                        "chars": len(valid or ""),
                        "evidence_digest": digest,
                    }
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
                session_id=args.session_id,
                step_id=args.step_id,
                observations_file=args.observations_file,
            )
        elif args.command == "telemetry-finish":
            result = telemetry_finish(
                root,
                args.domain,
                dispatch_id=args.dispatch_id,
                outcome=args.outcome,
                session_id=args.session_id,
                step_id=args.step_id,
                observations_file=args.observations_file,
            )
        else:
            raise AssertionError(f"Unhandled host command: {args.command}")

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") == "blocked" else 0
    except KeyboardInterrupt:
        return 130
    except guard.GuardBlocked as exc:
        if "args" in locals() and getattr(args, "command", None) in TELEMETRY_COMMANDS:
            print(
                json.dumps(
                    {"status": "telemetry_unavailable", "reason": exc.reason, "error": exc.reason},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(json.dumps({"status": "blocked", "reason": exc.reason}))
        return 1
    except Exception as exc:
        if "args" in locals() and getattr(args, "command", None) in TELEMETRY_COMMANDS:
            print(
                json.dumps(
                    {"status": "telemetry_unavailable", "reason": "telemetry_error", "error": str(exc)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        print(f"DevFlow host error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
