"""Small, advisory resume projection over the existing execution handoff view.

The projection is read-only and never decides lifecycle actions or lease ownership.
No native model is invoked and no secondary STATE/WORK database is written.
"""
from __future__ import annotations

import json
from typing import Any

MAX_BYTES = 4095  # CLI print adds one newline; total stdout stays <= 4096 bytes.
_ACTION_FIELDS = ("role", "command", "scope", "phase", "work_item", "mode")
_RECEIPT_FIELDS = ("decisions", "assumptions", "constraints", "files", "next_steps")


def _text(value: Any, limit: int = 140) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace("\x00", "")
    if not cleaned:
        return None
    # Byte bounds, not code-point bounds: Korean and emoji must honor 4KB.
    return cleaned.encode("utf-8")[:limit].decode("utf-8", "ignore") or None


def _strings(values: Any, *, count: int = 3, size: int = 140) -> list[str]:
    if not isinstance(values, list):
        return []
    return [item for x in values[:count] if (item := _text(x, size)) is not None]


def _action(value: Any) -> dict[str, str | None]:
    data = value if isinstance(value, dict) else {}
    return {key: _text(data.get(key), 96) for key in _ACTION_FIELDS}


def _selected_work(value: Any) -> dict[str, str | None] | None:
    if not isinstance(value, dict):
        return None
    return {key: _text(value.get(key), 96) for key in
            ("id", "status", "start_sha", "recorded_commit")}


def _checkpoint(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    details = value.get("details")
    if not isinstance(details, dict):
        return None
    receipt = details.get("receipt") if isinstance(details.get("receipt"), dict) else {}
    return {
        "stage": _text(details.get("stage"), 48),
        "note": _text(details.get("note"), 180),
        "completed": _strings(details.get("completed")),
        "pending": _strings(details.get("pending")),
        "verification": _strings(details.get("verification")),
        "receipt": {key: _strings(receipt.get(key)) for key in _RECEIPT_FIELDS},
        "stale": bool(value.get("head_changed") or value.get("working_tree_changed")),
        "authority": "caller_reported_unverified",
    }


def _encoded(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def build(handoff: dict[str, Any]) -> dict[str, Any]:
    """Bound a complete handoff view to a token-frugal, fail-closed JSON hint.

    Important: no session/step IDs, owner markers, long events or raw source bodies.
    When truncation is needed, drop advisory fields; never drop safety flags.
    """
    if not isinstance(handoff, dict):
        raise ValueError("resume brief requires a handoff mapping")
    git = handoff.get("git") if isinstance(handoff.get("git"), dict) else {}
    orchestration = handoff.get("orchestration") if isinstance(handoff.get("orchestration"), dict) else {}
    hosted = orchestration.get("hosted") if isinstance(orchestration.get("hosted"), dict) else {}
    standalone = orchestration.get("standalone") if isinstance(orchestration.get("standalone"), dict) else {}
    incomplete = handoff.get("unconfirmed_commands")
    incomplete = incomplete if isinstance(incomplete, list) else []
    record_corrupt = hosted.get("status") == "record_corrupt" or standalone.get("status") == "record_corrupt"
    pending = bool(hosted.get("requires_termination_verification") or
                   hosted.get("status") == "pending_child" or record_corrupt)
    # An active owner still requires normal ownership verification, even on the same host.
    owner_check = (hosted.get("lease_active") is True or pending
                   or hosted.get("status") not in {None, "idle", "no_record"}
                   or standalone.get("status") not in {None, "idle", "no_record", "complete"})
    result: dict[str, Any] = {
        "authority": "advisory_only",
        "safety": {
            "pending_child_or_corrupt": pending,
            "owner_check_required": owner_check,
            "unconfirmed_commands": len(incomplete),
            "no_automatic_replay": True,
        },
        "lifecycle": {
            "project_status": _text(handoff.get("project_status"), 48),
            "next_action": _action(handoff.get("action")),
            "work": _selected_work(handoff.get("work")),
        },
        "git": {
            "head": _text(git.get("head"), 64),
            "status": _text(git.get("status"), 24),
            "paths": _strings(git.get("paths"), count=5, size=115),
            "path_count": git.get("path_count") if type(git.get("path_count")) is int else None,
            "digest": _text(git.get("digest"), 64),
        },
        "hosted": {
            "status": _text(hosted.get("status"), 48),
            "host": _text(hosted.get("host"), 32),
            "pending_kind": _text(hosted.get("pending_kind"), 32),
        },
        "standalone_status": _text(standalone.get("status"), 32),
        "checkpoint": _checkpoint(handoff.get("checkpoint")),
        "unfinished": [
            {"operation": _text(row.get("operation"), 96),
             "action": _action(row.get("action"))}
            for row in incomplete[:3] if isinstance(row, dict)
        ],
        "pending_primary": _selected_primary(hosted.get("pending_primary")),
        "last_primary": _selected_primary(hosted.get("last_primary")),
        "truncated": False,
    }
    # Optional hints are sacrificed before safety or the current computed action.
    if len(_encoded(result)) > MAX_BYTES:
        result["truncated"] = True
        for field in ("last_primary", "unfinished", "pending_primary", "checkpoint", "git"):
            if field == "git":
                result["git"]["paths"] = []
            elif field == "unfinished":
                result[field] = []
            else:
                result[field] = None
            if len(_encoded(result)) <= MAX_BYTES:
                break
    if len(_encoded(result)) > MAX_BYTES:
        raise ValueError("resume brief safety projection exceeds output budget")
    return result


def _selected_primary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "action": _action(value.get("action")),
        "work_at_dispatch": _selected_work(value.get("work_at_dispatch")),
        "head_at_dispatch": _text(value.get("head_at_dispatch"), 64),
        "child_outcome": _text(value.get("child_outcome"), 32),
        "authority": "dispatch_observation_only",
    }
