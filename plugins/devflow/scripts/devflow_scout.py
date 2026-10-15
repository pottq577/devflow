"""Validate untrusted, bounded repository-scout capsules before compact dispatch.

A valid capsule is a navigation index, never evidence of lifecycle completion.
Reject incomplete/oversized output instead of truncating away provenance or
silently replacing the authoritative runtime packet with a free-form answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

REQUIRED_SECTIONS = (
    "Action",
    "Evidence map",
    "Existing patterns",
    "Constraints and risks",
    "Candidate concerns",
    "Uncertainty",
)
_HEADING = re.compile(r"(?m)^#{2,3}[ \t]+([A-Za-z][A-Za-z ]*?)[ \t]*$")
_PATH = re.compile(
    r"(?:^|[\s`(])(?:[\w.-]+/)+[\w.-]+(?::\d+(?:-\d+)?)?(?=$|[\s`),;])",
    re.MULTILINE,
)


def evidence_digest(index: Any) -> str:
    """Bind a capsule to the source and failure evidence it actually inspected."""
    payload = json.dumps(
        index, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return "ev1:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
