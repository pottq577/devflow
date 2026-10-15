"""Validate untrusted, bounded repository-scout capsules before compact dispatch.

A valid capsule is a navigation index, never evidence of lifecycle completion.
Reject incomplete/oversized output instead of truncating away provenance or
silently replacing the authoritative runtime packet with a free-form answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

REQUIRED_SECTIONS = (
    "Action",
    "Evidence map",
    "Existing patterns",
    "Constraints and risks",
    "Candidate concerns",
    "Uncertainty",
)
BINDING_VERSION = 2
_HEADING = re.compile(r"(?m)^#{2,3}[ \t]+([A-Za-z][A-Za-z ]*?)[ \t]*$")
_PATH = re.compile(
    r"(?:^|[\s`(])((?:[\w.-]+/)+[\w.-]+)(?::\d+(?:-\d+)?)?(?=$|[\s`),;])",
    re.MULTILINE,
)


def capsule_sha256(text: str) -> str:
    """Digest the exact capsule body a binding was created for."""
    return "cp1:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def evidence_digest(index: Any, scope: dict[str, str] | None = None) -> str:
    """Bind a capsule to the evidence index and the source bytes it may have inspected.

    The index path list is navigation, not proof of access; `scope` carries the content
    fingerprint of every file the index told the scout to open.
    """
    payload = json.dumps(
        {"index": index, "scope": dict(scope or {})},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return "ev1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def referenced_paths(text: str) -> list[str]:
    """Extract only path-shaped citations; line ranges are not part of the path."""
    return sorted({match.group(1) for match in _PATH.finditer(text)})


def capsule_binding(
    text: str,
    *,
    fingerprint: str,
    digest: str,
    scope_confirmed: bool,
    head_sha: str | None = None,
    step_id: str | None = None,
    model_alias: str | None = None,
    bound_at: str | None = None,
) -> dict[str, Any]:
    """Creation provenance; written once by `scout-bind` and never re-signed by validation."""
    return {
        "version": BINDING_VERSION,
        "capsule_sha256": capsule_sha256(text),
        "fingerprint": fingerprint,
        "evidence_digest": digest,
        "scope_confirmed": bool(scope_confirmed),
        "head_sha": head_sha,
        "step_id": step_id,
        "model_alias": model_alias,
        "bound_at": bound_at,
    }


def capsule_verdict(
    text: str,
    binding: Any,
    *,
    fingerprint: str,
    digest: str,
    scope_confirmed: bool,
    max_chars: int = 12000,
) -> str:
    """Side-effect-free, idempotent verdict: invalid shape/body, stale provenance, else valid.

    Missing or mismatched provenance is never repaired here; it falls back to a new scout.
    """
    if validated_capsule(text, max_chars) is None:
        return "invalid"
    if not isinstance(binding, dict) or binding.get("version") != BINDING_VERSION:
        return "stale"
    if (
        not isinstance(binding.get("step_id"), str)
        or not re.fullmatch(r"[0-9a-f]{32}", binding["step_id"])
        or not isinstance(binding.get("model_alias"), str)
        or not binding["model_alias"].strip()
        or not isinstance(binding.get("head_sha"), str)
        or not re.fullmatch(r"(?:[0-9a-f]{40}|unborn)", binding["head_sha"])
        or not isinstance(binding.get("bound_at"), str)
    ):
        return "stale"
    try:
        if datetime.fromisoformat(binding["bound_at"]).utcoffset() is None:
            return "stale"
    except ValueError:
        return "stale"
    if binding.get("capsule_sha256") != capsule_sha256(text):
        return "invalid"
    if binding.get("scope_confirmed") is not True or not scope_confirmed:
        return "stale"
    if binding.get("fingerprint") != fingerprint or binding.get("evidence_digest") != digest:
        return "stale"
    return "valid"


def validated_capsule(value: Any, max_chars: int = 12000) -> str | None:
    """Accept exactly six populated sections, at least one evidence path, and no truncation.

    This validates shape only, not the truth of cited files, facts, or safety.
    The receiving specialist must re-open cited evidence before any decision.
    """
    if type(max_chars) is not int or max_chars < 1 or not isinstance(value, str):
        return None
    capsule = value.strip()
    if not capsule or len(capsule) > max_chars or "\x00" in capsule:
        return None
    headings = list(_HEADING.finditer(capsule))
    if [match.group(1) for match in headings] != list(REQUIRED_SECTIONS):
        return None
    if capsule[: headings[0].start()].strip():
        return None
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(capsule)
        body = capsule[match.end() : end].strip()
        if not body:
            return None
        if match.group(1) == "Evidence map" and not _PATH.search(body):
            return None
    return capsule
