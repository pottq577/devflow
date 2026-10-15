"""Cross-process coordinator for hosted Goal and standalone Autopilot leases.

Hosted sessions outlive one host.py subprocess. SQLite serializes their creation with
standalone PID-owned mutating slots; neither surface can claim a domain between the
other surface's occupancy check and acquisition.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from devflow_postman import strict_json

SESSION_TTL_SECONDS = 24 * 60 * 60


class SessionConflict(RuntimeError):
    """The domain is occupied, or the supplied hosted-session owner is invalid."""


class SessionBlocked(SessionConflict):
    """Persisted execution evidence forbids releasing or replacing ownership."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def read_progress(connection: sqlite3.Connection) -> tuple[str, dict] | None:
    """Validate shared execution evidence without hiding a foreign owner's child."""
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_progress'"
    ).fetchone():
        return None
    row = connection.execute(
        "SELECT session_id, progress FROM hosted_progress WHERE slot = 1"
    ).fetchone()
    if not row:
        return None
    try:
        owner, raw = row
        value = strict_json(raw)
        if not isinstance(owner, str) or not owner.strip() or not isinstance(value, dict):
            raise ValueError
        for key in ("steps", "attempt"):
            if type(value[key]) is not int or value[key] < 0:
                raise ValueError
        fingerprint = value["fingerprint"]
        if fingerprint is not None and (not isinstance(fingerprint, str) or not fingerprint.strip()):
            raise ValueError
        visits = value["visits"]
        if not isinstance(visits, dict) or any(
            not isinstance(key, str) or not key.strip() or type(count) is not int or count < 1
            for key, count in visits.items()
        ):
            raise ValueError
        if "segment_progressed" in value and type(value["segment_progressed"]) is not bool:
            raise ValueError
        if value.get("last_outcome") not in {None, "completed", "failed", "cancelled", "capability_blocked"}:
            raise ValueError
        pending = value["inflight"]
        if pending is not None:
            if not isinstance(pending, dict):
                raise ValueError
            for key in ("step_id", "fingerprint", "candidate_alias"):
                if not isinstance(pending[key], str) or not pending[key].strip():
                    raise ValueError
            if (pending["kind"] not in {"bootstrap", "scout", "primary"}
                    or type(pending["attempt"]) is not int
                    or pending["attempt"] != value["attempt"]
                    or pending["fingerprint"] != fingerprint
                    or value["steps"] < 1 or fingerprint not in visits):
                raise ValueError
        # Legacy visits record observed action transitions, never assume progress from age.
        value.setdefault("segment_progressed", len(visits) > 1)
        value.setdefault("last_outcome", None)
    except (ValueError, TypeError, KeyError):
        raise SessionBlocked("hosted_progress_corrupt") from None
    return owner, value


@contextmanager
def coordinator(
    runtime_dir: Path, *, write: bool = True
) -> Iterator[sqlite3.Connection]:
    """Hold a short, transactional cross-process lock around lease transitions.

    `write=False` opens a read-only transaction: ownership checks and health projections
    verify the owner without extending the lease or taking the write lock.
    """
    leases = runtime_dir / "leases"
    leases.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        leases.chmod(0o700)
    db_path = leases / "coordinator.sqlite3"
    connection = sqlite3.connect(str(db_path), timeout=5)
    if os.name == "posix":
        db_path.chmod(0o600)
    try:
        connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        if write:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS hosted_session ("
                "slot INTEGER PRIMARY KEY CHECK (slot = 1), "
                "session_id TEXT NOT NULL, acquired_at REAL NOT NULL, "
                "expires_at REAL NOT NULL)"
            )
        yield connection
        if write:
            connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _active_row(connection: sqlite3.Connection, *, now: float | None = None) -> tuple | None:
    now = time.time() if now is None else now
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hosted_session'"
    ).fetchone():
        return None
    row = connection.execute(
        "SELECT session_id, acquired_at, expires_at FROM hosted_session WHERE slot = 1"
    ).fetchone()
    return row if row and row[2] > now else None


def hosted_active(connection: sqlite3.Connection) -> bool:
    """Called inside coordinator() while acquiring standalone PID-owned slots."""
    progress = read_progress(connection)
    return bool((progress and progress[1]["inflight"] is not None) or _active_row(connection))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _standalone_active(runtime_dir: Path) -> bool:
    """Check all mutating slots, not just the current policy's slot count."""
    active = False
    for slot in (runtime_dir / "leases").glob("mutating-*.lock"):
        try:
            current = json.loads(slot.read_text(encoding="utf-8"))
            pid = int(current.get("pid") or 0)
        except (OSError, ValueError, TypeError, AttributeError):
            pid = 0
        if _pid_alive(pid):
            active = True
            continue
        try:
            slot.unlink()
        except FileNotFoundError:
            pass
    return active


def start(runtime_dir: Path, *, session_id: str | None = None) -> dict:
    """Create or resume a hosted session without ever stealing an active owner."""
    with coordinator(runtime_dir) as connection:
        now = time.time()
        progress = read_progress(connection)
        active = _active_row(connection, now=now)
        if progress and progress[1]["inflight"] is not None:
            if not active or active[0] != progress[0] or session_id != progress[0]:
                raise SessionBlocked("hosted_step_inflight")
        if active:
            if session_id != active[0]:
                raise SessionConflict("another hosted Goal session owns this domain")
            owner, acquired, _ = active
        else:
            if session_id:
                raise SessionConflict("hosted Goal session has expired or does not exist")
            if _standalone_active(runtime_dir):
                raise SessionConflict("standalone Autopilot holds a mutating domain lease")
            owner, acquired = uuid.uuid4().hex, now
        expires = now + SESSION_TTL_SECONDS
        connection.execute(
            "INSERT INTO hosted_session (slot, session_id, acquired_at, expires_at) "
            "VALUES (1, ?, ?, ?) ON CONFLICT(slot) DO UPDATE SET "
            "session_id = excluded.session_id, acquired_at = excluded.acquired_at, "
            "expires_at = excluded.expires_at",
            (owner, acquired, expires),
        )
        return {"status": "acquired", "session_id": owner, "expires_at": expires}


def require(runtime_dir: Path, session_id: str | None) -> None:
    """Verify ownership and inflight fencing without writing or extending the lease."""
    if not session_id:
        raise SessionConflict("hosted Goal commands require --session-id")
    with coordinator(runtime_dir, write=False) as connection:
        _verify_owner(connection, session_id)


def renew(runtime_dir: Path, session_id: str | None) -> dict:
    """Extend the lease of the verified current owner; the explicit heartbeat edge."""
    if not session_id:
        raise SessionConflict("hosted Goal commands require --session-id")
    return start(runtime_dir, session_id=session_id)


def _verify_owner(connection: sqlite3.Connection, session_id: str | None) -> None:
    progress = read_progress(connection)
    active = _active_row(connection)
    if progress and progress[1]["inflight"] is not None and (
        not active or active[0] != progress[0]
    ):
        raise SessionBlocked("hosted_step_inflight")
    if not active:
        raise SessionConflict("hosted Goal session has expired or does not exist")
    if session_id != active[0]:
        raise SessionConflict("another hosted Goal session owns this domain")


def end(runtime_dir: Path, session_id: str | None) -> dict:
    """Release only the current hosted owner, not a concurrently replaced session."""
    if not session_id:
        raise SessionConflict("session-end requires --session-id")
    with coordinator(runtime_dir) as connection:
        row = connection.execute(
            "SELECT session_id FROM hosted_session WHERE slot = 1"
        ).fetchone()
        if not row or row[0] != session_id:
            raise SessionConflict("hosted Goal session owner does not match")
        progress = read_progress(connection)
        if progress and progress[1]["inflight"] is not None:
            raise SessionBlocked("hosted_step_inflight")
        connection.execute("DELETE FROM hosted_session WHERE slot = 1")
    return {"status": "released", "session_id": session_id}


def status(runtime_dir: Path) -> dict:
    """Read-only health projection; the session identifier is never disclosed."""
    with coordinator(runtime_dir, write=False) as connection:
        progress = read_progress(connection)
        active = _active_row(connection)
        blocked = bool(progress and progress[1]["inflight"] is not None and (
            not active or active[0] != progress[0]
        ))
        return {
            "status": "blocked" if blocked else "active" if active else "idle",
            "expires_at": active[2] if active else None,
            "reason": "hosted_step_inflight" if blocked else None,
        }
