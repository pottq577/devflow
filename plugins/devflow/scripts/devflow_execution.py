"""Host-independent, advisory execution journal for DevFlow lifecycle handoffs.

STATE/WORK and the hosted/standalone lease guards remain authoritative. This journal
records *observations*, not completion claims, and cannot authorize another writer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_TEXT = 2000
MAX_ITEMS = 12
MAX_PATHS = 64
HOST_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
EVENT_KINDS = {"command_start", "command_finish", "checkpoint"}


def _require_text(value: str, label: str, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be nonblank and at most {maximum} characters")
    return value.strip()


def _bounded_items(values: list[str], name: str) -> list[str]:
    if len(values) > MAX_ITEMS:
        raise ValueError(f"{name} permits at most {MAX_ITEMS} entries")
    return [_require_text(value, name) for value in values]


def _action_ref(action: dict[str, Any]) -> dict[str, Any]:
    """Never treat a copied next_action as an independent lifecycle decision."""
    return {key: action.get(key) for key in ("role", "command", "scope", "phase", "work_item", "mode")}


def action_fingerprint(action: dict[str, Any]) -> str:
    # This identity is for the advisory journal, not the host retry guard.
    raw = json.dumps(_action_ref(action), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
    )


def git_snapshot(root: Path) -> dict[str, Any]:
    """Capture small, bounded navigation facts, never diffs, file bodies or secrets."""
    try:
        head_proc = _git(root, "rev-parse", "--verify", "HEAD")
        head = head_proc.stdout.decode("ascii", "replace").strip() if head_proc.returncode == 0 else None
        proc = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    except (OSError, subprocess.TimeoutExpired):
        return {"head": None, "status": "unavailable", "paths": [], "path_count": None, "digest": None}
    if proc.returncode:
        return {"head": head, "status": "unavailable", "paths": [], "path_count": None, "digest": None}
    items = proc.stdout.split(b"\0")
    paths: list[str] = []
    markers: list[tuple[Any, ...]] = []
    index = 0
    while index < len(items):
        entry = items[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            return {"head": head, "status": "unavailable", "paths": [], "path_count": None, "digest": None}
        status = entry[:2]
        path = os.fsdecode(entry[3:])
        if b"R" in status or b"C" in status:
            # -z emits a second NUL-delimited path for rename/copy records.
            index += 1
        if path.startswith(".devflow/runtime/") or path.startswith(".git/"):
            continue
        paths.append(path)
        try:
            stat_result = (root / path).lstat()
            marker = (status.decode("ascii", "replace"), path,
                      stat_result.st_size, stat_result.st_mtime_ns)
        except OSError:
            marker = (status.decode("ascii", "replace"), path, None, None)
        if len(markers) < MAX_PATHS:
            markers.append(marker)
    worktree_marker = json.dumps(
        {"files": markers, "path_count": len(paths)},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return {
        "head": head,
        "status": "available",
        "paths": paths[:MAX_PATHS],
        "path_count": len(paths),
        "paths_omitted": max(0, len(paths) - MAX_PATHS),
        "digest": hashlib.sha256(worktree_marker.encode("utf-8")).hexdigest(),
    }


def _database(runtime_dir: Path, *, create: bool) -> sqlite3.Connection | None:
    path = runtime_dir / "execution-journal.sqlite3"
    if not create and not path.is_file():
        return None
    if create:
        runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(
        str(path) if create else path.resolve().as_uri() + "?mode=ro",
        uri=not create, timeout=5,
    )
    connection.row_factory = sqlite3.Row
    if create and os.name == "posix":
        path.chmod(0o600)
    if create:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "event_id TEXT NOT NULL UNIQUE, event_kind TEXT NOT NULL, "
            "command_id TEXT, recorded_at REAL NOT NULL, "
            "action_fingerprint TEXT NOT NULL, action TEXT NOT NULL, "
            "git_state TEXT NOT NULL, details TEXT NOT NULL)"
        )
        connection.commit()
    return connection


def _insert(runtime_dir: Path, *, event_kind: str, command_id: str | None,
            action: dict[str, Any], git_state: dict[str, Any], details: dict[str, Any]) -> str:
    if event_kind not in EVENT_KINDS:
        raise ValueError("unknown execution event kind")
    event_id = uuid.uuid4().hex
    connection = _database(runtime_dir, create=True)
    assert connection is not None
    try:
        with connection:
            connection.execute(
                "INSERT INTO events (event_id, event_kind, command_id, recorded_at, "
                "action_fingerprint, action, git_state, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, event_kind, command_id, time.time(), action_fingerprint(action),
                 json.dumps(_action_ref(action), ensure_ascii=False, sort_keys=True),
                 json.dumps(git_state, ensure_ascii=False, sort_keys=True),
                 json.dumps(details, ensure_ascii=False, sort_keys=True)),
            )
    finally:
        connection.close()
    return event_id


def record_command_start(runtime_dir: Path, *, action: dict[str, Any], git_state: dict[str, Any],
                         command: str, host: str | None = None) -> str:
    operation = _require_text(command, "command", 96)
    if host is not None and not HOST_PATTERN.fullmatch(host):
        raise ValueError("invalid host label")
    command_id = uuid.uuid4().hex
    _insert(runtime_dir, event_kind="command_start", command_id=command_id,
            action=action, git_state=git_state, details={"command": operation, "host": host})
    return command_id


def record_command_finish(runtime_dir: Path, *, command_id: str, action: dict[str, Any],
                          git_state: dict[str, Any], exit_code: int | None) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", command_id):
        raise ValueError("invalid command id")
    if exit_code is not None and type(exit_code) is not int:
        raise ValueError("invalid exit code")
    _insert(runtime_dir, event_kind="command_finish", command_id=command_id,
            action=action, git_state=git_state, details={"exit_code": exit_code})


def checkpoint(runtime_dir: Path, *, action: dict[str, Any], git_state: dict[str, Any],
               stage: str, note: str, completed: list[str] | None = None,
               pending: list[str] | None = None, verification: list[str] | None = None,
               host: str | None = None) -> dict[str, Any]:
    stage = _require_text(stage, "stage", 48)
    note = _require_text(note, "note")
    if host is not None and not HOST_PATTERN.fullmatch(host):
        raise ValueError("invalid host label")
    details = {
        "stage": stage, "note": note,
        "completed": _bounded_items(completed or [], "completed"),
        "pending": _bounded_items(pending or [], "pending"),
        "verification": _bounded_items(verification or [], "verification"),
        "host": host,
        "authority": "caller_reported_unverified",
    }
    event_id = _insert(runtime_dir, event_kind="checkpoint", command_id=None,
                       action=action, git_state=git_state, details=details)
    return {"status": "recorded", "event_id": event_id,
            "authority": "caller_reported_unverified"}


def _row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        if row["event_kind"] not in EVENT_KINDS:
            raise ValueError("unknown event")
        action = json.loads(row["action"])
        git_state = json.loads(row["git_state"])
        details = json.loads(row["details"])
        if not isinstance(action, dict) or not isinstance(git_state, dict) or not isinstance(details, dict):
            raise ValueError("invalid event payload")
        if action_fingerprint(action) != row["action_fingerprint"]:
            raise ValueError("action fingerprint mismatch")
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("execution_journal_corrupt") from exc
    return {
        "event_id": row["event_id"], "kind": row["event_kind"],
        "command_id": row["command_id"], "recorded_at": row["recorded_at"],
        "action_fingerprint": row["action_fingerprint"],
        "action": action, "git": git_state, "details": details,
    }


def read(runtime_dir: Path, *, action: dict[str, Any], git_state: dict[str, Any],
         limit: int = 8) -> dict[str, Any]:
    """Read-only, bounded recovery projection; never grant execution authority."""
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("execution limit must be 1 through 30")
    fingerprint = action_fingerprint(action)
    connection = _database(runtime_dir, create=False)
    if connection is None:
        events: list[dict[str, Any]] = []
        unfinished: list[dict[str, Any]] = []
        relevant: dict[str, Any] | None = None
    else:
        try:
            events = [_row(row) for row in connection.execute(
                "SELECT * FROM events ORDER BY seq DESC LIMIT ?", (limit,))]
            checkpoint_row = connection.execute(
                "SELECT * FROM events WHERE event_kind='checkpoint' "
                "AND action_fingerprint=? ORDER BY seq DESC LIMIT 1", (fingerprint,)
            ).fetchone()
            relevant = _row(checkpoint_row) if checkpoint_row is not None else None
            # SQL anti-join sees all history, not just the bounded display page.
            unfinished = [_row(row) for row in connection.execute(
                "SELECT started.* FROM events AS started WHERE started.event_kind='command_start' "
                "AND NOT EXISTS (SELECT 1 FROM events AS finished "
                "WHERE finished.event_kind='command_finish' AND finished.command_id=started.command_id) "
                "ORDER BY started.seq DESC LIMIT 8")]
        finally:
            connection.close()
    checkpoint_view = None
    if relevant is not None:
        checkpoint_view = {
            "recorded_at": relevant["recorded_at"],
            "details": relevant["details"],
            "git": relevant["git"],
            "head_changed": relevant["git"].get("head") != git_state.get("head"),
            "working_tree_changed": relevant["git"].get("digest") != git_state.get("digest"),
        }
    return {
        "authority": "advisory_only",
        "action": _action_ref(action),
        "action_fingerprint": fingerprint,
        "git": git_state,
        "checkpoint": checkpoint_view,
        "unconfirmed_commands": [
            {"recorded_at": value["recorded_at"], "operation": value["details"].get("command"),
             "action": value["action"], "git": value["git"]}
            for value in unfinished
        ],
        "events": events,
        "note": "Validate STATE/WORK, current Git and active native children before retrying; journal is not completion evidence.",
    }


def orchestration_snapshot(runtime_dir: Path) -> dict[str, Any]:
    """Read existing hosted and standalone guards without extending or releasing them."""
    result: dict[str, Any] = {"hosted": {"status": "no_record"},
                                    "standalone": {"status": "no_record"}}
    controller = runtime_dir / "controller.json"
    if controller.is_file():
        try:
            if controller.stat().st_size > 262144:
                raise ValueError("oversized controller")
            data = json.loads(controller.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("invalid controller")
            result["standalone"] = {
                "status": str(data.get("status") or "unknown")[:80],
                "reason": str(data.get("reason") or "")[:400],
                "updated_at": str(data.get("updated_at") or "")[:80],
                "steps_completed": data.get("steps_completed") if type(data.get("steps_completed")) is int else None,
                "failure_kind": str(data.get("failure_kind") or "")[:80],
            }
        except (OSError, UnicodeError, ValueError, TypeError):
            result["standalone"] = {"status": "record_corrupt"}
    coordinator = runtime_dir / "leases" / "coordinator.sqlite3"
    if coordinator.is_file():
        connection = None
        try:
            # URI read-only prevents an inspection from creating or mutating the coordinator.
            connection = sqlite3.connect(coordinator.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            connection.execute("BEGIN")
            import devflow_session as hosted
            progress = hosted.read_progress(connection)
            active = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_session'"
            ).fetchone()
            lease = connection.execute(
                "SELECT expires_at FROM hosted_session WHERE slot=1"
            ).fetchone() if active else None
            lease_active = bool(lease and lease[0] > time.time())
            pending = progress[1]["inflight"] if progress else None
            result["hosted"] = {
                "status": "pending_child" if pending else "active" if lease_active else "idle",
                "lease_active": lease_active,
                "pending_kind": pending.get("kind") if pending else None,
                "pending_model_alias": pending.get("candidate_alias") if pending else None,
                "requires_termination_verification": bool(pending),
            }
        except (ImportError, OSError, ValueError, TypeError, sqlite3.DatabaseError):
            result["hosted"] = {"status": "record_corrupt", "requires_termination_verification": True}
        finally:
            if connection is not None:
                connection.close()
    return result
