"""Durable, session-fenced execution bounds for host-native DevFlow Goal.

Each hosted sub-agent spawn is explicitly reserved and acknowledged. The ordinary
`dispatch` preview does not consume a step; telemetry remains optional and does
not stand in for actual lifecycle progress or measured token consumption.
"""

from __future__ import annotations

import copy
import json
import secrets
import time
from pathlib import Path
from typing import Any

import devflow_session as session


class GuardBlocked(RuntimeError):
    """Refuse execution before it can silently exceed a hosted safety bound."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _positive(value: Any, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 10000:
        raise ValueError(f"{label} must be an integer between 1 and 10000")
    return value


def limits(policy: dict[str, Any]) -> dict[str, int]:
    orchestration = policy.get("orchestration") or {}
    hosted = orchestration.get("hosted") or {}
    if not isinstance(hosted, dict):
        raise ValueError("orchestration.hosted must be a mapping")
    retries = (policy.get("escalation") or {}).get("retries") or {}
    return {
        "max_steps": _positive(hosted.get("max_steps", 100), "orchestration.hosted.max_steps"),
        "max_visits": _positive(
            hosted.get("max_action_visits", 4), "orchestration.hosted.max_action_visits"
        ),
        "max_no_progress": _positive(
            retries.get("max_no_progress", 3), "escalation.retries.max_no_progress"
        ),
    }


def _owner(connection: Any, session_id: str) -> None:
    if not session_id:
        raise session.SessionConflict("hosted Goal commands require --session-id")
    row = connection.execute(
        "SELECT session_id, expires_at FROM hosted_session WHERE slot = 1"
    ).fetchone()
    if not row or row[0] != session_id or row[1] <= time.time():
        raise session.SessionConflict("hosted Goal session has expired or ownership changed")


def _load(connection: Any, session_id: str) -> dict[str, Any]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS hosted_progress ("
        "slot INTEGER PRIMARY KEY CHECK (slot = 1), "
        "session_id TEXT NOT NULL, progress TEXT NOT NULL)"
    )
    row = connection.execute(
        "SELECT session_id, progress FROM hosted_progress WHERE slot = 1"
    ).fetchone()
    if not row or row[0] != session_id:
        # Starting a new explicit session resets operational counters, never lifecycle state.
        return {
            "steps": 0,
            "fingerprint": None,
            "attempt": 0,
            "visits": {},
            "inflight": None,
        }
    value = json.loads(row[1])
    if not isinstance(value, dict) or not all(
        key in value for key in ("steps", "fingerprint", "attempt", "visits", "inflight")
    ):
        raise GuardBlocked("hosted_progress_corrupt")
    if (type(value["steps"]) is not int or type(value["attempt"]) is not int
            or not isinstance(value["visits"], dict)):
        raise GuardBlocked("hosted_progress_corrupt")
    return value


def _save(connection: Any, session_id: str, value: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO hosted_progress (slot, session_id, progress) VALUES (1, ?, ?) "
        "ON CONFLICT(slot) DO UPDATE SET session_id=excluded.session_id, "
        "progress=excluded.progress",
        (session_id, json.dumps(value, sort_keys=True, ensure_ascii=False)),
    )


def _observe(value: dict[str, Any], fingerprint: str) -> None:
    if value["fingerprint"] != fingerprint:
        value["fingerprint"] = fingerprint
        value["attempt"] = 0
        value["visits"][fingerprint] = int(value["visits"].get(fingerprint, 0)) + 1


def _projection(
    value: dict[str, Any], fingerprint: str, bounds: dict[str, int],
    *, terminal: bool = False,
) -> dict[str, Any]:
    candidate = copy.deepcopy(value)
    pending = candidate["inflight"]
    if pending:
        reason = "hosted_step_inflight"
    else:
        _observe(candidate, fingerprint)
        if terminal:
            reason = None  # A completed/paused/checkpointed lifecycle can always be reported.
        elif candidate["steps"] >= bounds["max_steps"]:
            reason = "hosted_max_steps_exhausted"
        # Attempts start at zero. The final configured retry index is executable.
        elif candidate["attempt"] > bounds["max_no_progress"]:
            reason = "hosted_no_progress_retries_exhausted"
        elif candidate["visits"][fingerprint] > bounds["max_visits"]:
            reason = "hosted_action_cycle_detected"
        else:
            reason = None
    return {
        "status": "blocked" if reason else "ready",
        "reason": reason,
        "fingerprint": fingerprint,
        "attempt": candidate["attempt"],
        "steps_completed": candidate["steps"],
        "max_steps": bounds["max_steps"],
        "max_no_progress": bounds["max_no_progress"],
        "max_action_visits": bounds["max_visits"],
        "action_visits": candidate["visits"].get(fingerprint, 0),
        "pending_step": copy.deepcopy(pending),
        "token_usage": "unmeasured",
    }


def inspect(
    runtime_dir: Path, session_id: str, fingerprint: str,
    policy: dict[str, Any], *, terminal: bool = False,
) -> dict[str, Any]:
    bounds = limits(policy)
    with session.coordinator(runtime_dir) as connection:
        _owner(connection, session_id)
        return _projection(_load(connection, session_id), fingerprint, bounds, terminal=terminal)


def begin(
    runtime_dir: Path, session_id: str, fingerprint: str,
    policy: dict[str, Any], *, kind: str, expected_attempt: int,
    candidate_alias: str,
) -> dict[str, Any]:
    if kind not in {"bootstrap", "scout", "primary"}:
        raise ValueError("hosted step kind must be bootstrap, scout or primary")
    if not candidate_alias:
        raise ValueError("hosted step requires a routed candidate alias")
    bounds = limits(policy)
    with session.coordinator(runtime_dir) as connection:
        _owner(connection, session_id)
        value = _load(connection, session_id)
        result = _projection(value, fingerprint, bounds)
        if result["status"] != "ready":
            raise GuardBlocked(result["reason"])
        if result["attempt"] != expected_attempt:
            raise GuardBlocked("hosted_stale_attempt")
        _observe(value, fingerprint)
        step_id = secrets.token_hex(16)
        value["steps"] += 1
        value["inflight"] = {
            "step_id": step_id,
            "fingerprint": fingerprint,
            "kind": kind,
            "attempt": expected_attempt,
            "candidate_alias": candidate_alias,
        }
        _save(connection, session_id, value)
        return {
            "status": "started",
            "step_id": step_id,
            "kind": kind,
            "attempt": expected_attempt,
            "steps_completed": value["steps"],
            "max_steps": bounds["max_steps"],
        }


def finish(
    runtime_dir: Path, session_id: str, step_id: str,
    after_fingerprint: str, policy: dict[str, Any], *, outcome: str,
) -> dict[str, Any]:
    if outcome not in {"completed", "failed", "cancelled", "capability_blocked"}:
        raise ValueError("hosted step outcome is unsupported")
    if not step_id:
        raise ValueError("hosted step finish requires a step id")
    bounds = limits(policy)
    with session.coordinator(runtime_dir) as connection:
        _owner(connection, session_id)
        value = _load(connection, session_id)
        pending = value["inflight"]
        if not isinstance(pending, dict) or pending.get("step_id") != step_id:
            raise GuardBlocked("hosted_step_owner_mismatch")
        before = pending["fingerprint"]
        changed = before != after_fingerprint
        value["inflight"] = None
        if changed:
            _observe(value, after_fingerprint)
        elif pending["kind"] in {"primary", "bootstrap"} and outcome != "capability_blocked":
            # A successful child that did not move STATE still consumes a semantic retry.
            value["attempt"] += 1
        _save(connection, session_id, value)
        next_state = _projection(value, after_fingerprint, bounds)
        return {
            "status": "recorded",
            "progressed": changed,
            "outcome": outcome,
            "attempt": value["attempt"],
            "steps_completed": value["steps"],
            "next_guard": next_state,
        }


def require_reserved_step(
    runtime_dir: Path, session_id: str, step_id: str, *,
    fingerprint: str, kind: str, attempt: int, candidate_alias: str,
) -> dict[str, Any]:
    """Bind optional telemetry to an actual pending, session-owned child spawn."""
    with session.coordinator(runtime_dir) as connection:
        _owner(connection, session_id)
        pending = _load(connection, session_id)["inflight"]
        expected = {
            "step_id": step_id,
            "fingerprint": fingerprint,
            "kind": kind,
            "attempt": attempt,
            "candidate_alias": candidate_alias,
        }
        if not isinstance(pending, dict) or any(
            pending.get(key) != value for key, value in expected.items()
        ):
            raise GuardBlocked("hosted_telemetry_step_mismatch")
        return copy.deepcopy(pending)


def assert_idle(runtime_dir: Path, session_id: str) -> None:
    """Never release a hosted lease with an unacknowledged child dispatch."""
    with session.coordinator(runtime_dir) as connection:
        _owner(connection, session_id)
        if _load(connection, session_id)["inflight"]:
            raise GuardBlocked("hosted_step_inflight")
