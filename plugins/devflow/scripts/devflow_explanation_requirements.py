"""Bind traced-source requirement evidence to the existing whole-work ELI5 receipt.

The P04 snapshot remains authoritative and P05 remains its only report renderer.
This adapter supplies a stable digest and a strict final-only gate; it never
modifies WORK, STATE, reports or source snapshots.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Mapping

import devflow_report as report
import devflow_requirements as requirements
import devflow_sources as sources
import devflow_traceability as traceability

CLOSED_SCOPE = frozenset({"excluded", "deferred", "cancelled"})
ACCEPTABLE_DECISIONS = frozenset({"not_required", "developer_confirmed", "approved"})
AXES = ("implementation", "difference", "decision", "verification")


def _review_satisfied(item: dict[str, Any]) -> bool:
    """Mirror the required-review gate for implemented high/critical WORK."""
    raw = item.get("review") if isinstance(item.get("review"), dict) else {}
    risk = item.get("risk") if isinstance(item.get("risk"), dict) else {}
    high = risk.get("level") in {"high", "critical"} and item.get("status") in {
        "ready", "in_progress", "done",
    }
    required = high or raw.get("required") is True
    return not required or raw.get("status") == "verified"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=root,
            text=True, capture_output=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    head = result.stdout.strip()
    return head if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", head) else None


def _audit_hashes(domain: Path, docs: Mapping[Path, dict[str, Any]], state: Mapping[str, Any]) -> dict[str, str | None]:
    """Include only WORK/phase audit evidence already closed before ELI5.

    Integration audit is intentionally excluded: it runs *after* finalization
    and would otherwise invalidate the receipt on successful handoff.
    """
    names: set[str] = set()
    phases = state.get("phases")
    if isinstance(phases, dict):
        for phase_id, record in phases.items():
            if isinstance(record, dict) and record.get("status") == "verified":
                names.add(str(record.get("audit_file") or f"audits/phase-{phase_id}.md"))
    for doc in docs.values():
        for item in doc.get("items", []) or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            review = item.get("review") if isinstance(item.get("review"), dict) else {}
            if review.get("required") is True or (
                isinstance(item.get("risk"), dict)
                and item["risk"].get("level") in {"high", "critical"}
                and item.get("status") == "done"
            ):
                names.add(str(review.get("audit_file") or f"audits/work/{item['id']}.md"))
    result: dict[str, str | None] = {}
    for name in sorted(names):
        path = domain / name
        # Reject absolute/escaping paths and symlinks; never read arbitrary host files.
        if (not name or Path(name).is_absolute() or ".." in Path(name).parts
                or path.is_symlink() or not path.resolve().is_relative_to(domain.resolve())
                or not path.is_file()):
            result[name] = None
        else:
            result[name] = _sha(path.read_bytes())
    return result


def derive(
    root: Path, domain: Path, state: Mapping[str, Any],
    docs: Mapping[Path, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return bounded ELI5 evidence for v1 traced domains; None for legacy.

    Requirements without provenance cannot be counted as completed, but older
    domains are never silently enrolled in the new finalization contract.
    """
    if state.get("traceability_version") != 1:
        return None
    index: dict[str, tuple[Path, dict[str, Any]]] = {
        str(item["id"]): (path, item)
        for path, doc in docs.items()
        for item in doc.get("items", []) or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    head = _git_head(root)
    snap = requirements.collect(
        domain, index, state, root=root, head_sha=head,
        review_satisfied=_review_satisfied,
    )
    failures: list[str] = list(snap["diagnostics"].get("errors") or [])
    if head is None:
        failures.append("cannot establish current Git HEAD for requirement evidence")
    if not (domain / "sources/v1").is_dir():
        failures.append("captured original/context v1 evidence is missing")
    else:
        try:
            sources.verify(domain, domain, domain.name)
        except (sources.SourceError, OSError, UnicodeError) as exc:
            failures.append(f"captured sources are invalid: {exc}")
    linked, _ = traceability.validate_domain(domain, index, strict=True)
    failures.extend(linked)
    rows = snap.get("requirements", [])
    if not rows:
        failures.append("no PRD requirement IDs were found")
    for key, value in snap["gaps"].items():
        if value:
            failures.append(f"traceability gap: {key}")
    exposed = []
    for row in rows:
        ident = row["id"]
        if row.get("scope") not in CLOSED_SCOPE:
            if row["implementation"] != "implemented":
                failures.append(f"{ident}: implementation={row['implementation']}")
            if row["verification"] != "passed":
                failures.append(f"{ident}: verification={row['verification']}")
            if row["difference"] == "unknown":
                failures.append(f"{ident}: original comparison has no verified evidence")
            if row["decision"] not in ACCEPTABLE_DECISIONS:
                failures.append(f"{ident}: policy decision={row['decision']}")
        exposed.append({
            "id": ident,
            "title": row.get("title") or "",
            "scope": row.get("scope") or "unknown",
            **{axis: row[axis] for axis in AXES},
            "work_ids": row.get("work_ids", []),
            "policy_decisions": row.get("policy_decisions", []),
            "source_refs": row.get("source_refs", []),
        })
    audit_hashes = _audit_hashes(domain, docs, state)
    for path, sha in audit_hashes.items():
        if sha is None:
            failures.append(f"audit evidence missing or unsafe: {path}")
    snapshot_sha = _sha(report.render_json(snap).encode("utf-8"))
    evidence_sha = _sha(json.dumps(
        {"p05_json_sha256": snapshot_sha, "audits": audit_hashes},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return {
        "snapshot_sha256": snapshot_sha,
        "sha256": evidence_sha,
        "head_sha": head,
        "source_revisions": snap.get("source_revisions", {}),
        "summary": snap["summary"],
        "requirements": exposed,
        "audit_sha256": audit_hashes,
        "blockers": sorted(set(failures)),
        "diagnostics": snap["diagnostics"],
    }


class _RequirementTableParser(HTMLParser):
    """Read visible ELI5 requirement table rows, not comments or metadata claims."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_count = 0
        self.section_attrs: dict[str, str | None] = {}
        self.section_open = False
        self.nested_sections = 0
        self.rows: list[tuple[dict[str, str | None], str]] = []
        self.row_attrs: dict[str, str | None] | None = None
        self.row_text: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        if tag == "section":
            if self.section_open:
                self.nested_sections += 1
            elif values.get("id") == "devflow-requirements":
                self.section_open = True
                self.section_count += 1
                self.section_attrs = values
        if tag == "tr" and self.section_open and values.get("data-requirement-id") is not None:
            self.row_attrs = values
            self.row_text = []

    def handle_data(self, data: str) -> None:
        if self.row_attrs is not None and self.hidden_depth == 0:
            self.row_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        if tag == "tr" and self.row_attrs is not None:
            self.rows.append((self.row_attrs, " ".join(self.row_text)))
            self.row_attrs = None
        if tag == "section" and self.section_open:
            if self.nested_sections:
                self.nested_sections -= 1
            else:
                self.section_open = False


def html_errors(html_text: str, evidence: Mapping[str, Any]) -> list[str]:
    """Assert each ELI5 table row has exactly the current P04/P05 four-axis values."""
    parsed = _RequirementTableParser()
    parsed.feed(html_text)
    parsed.close()
    errors: list[str] = []
    if parsed.section_count != 1:
        errors.append("ELI5 requires exactly one visible devflow-requirements section")
    if parsed.section_attrs.get("data-snapshot-sha256") != evidence["snapshot_sha256"]:
        errors.append("ELI5 requirement snapshot hash differs from P05 JSON")
    if parsed.section_attrs.get("data-evidence-sha256") != evidence["sha256"]:
        errors.append("ELI5 requirement audit/source evidence hash is stale")
    expected = {row["id"]: row for row in evidence["requirements"]}
    seen: set[str] = set()
    for row, visible in parsed.rows:
        ident = row["data-requirement-id"]
        if ident not in expected:
            errors.append(f"ELI5 has unexpected requirement row: {ident}")
            continue
        if ident in seen:
            errors.append(f"ELI5 has duplicate requirement row: {ident}")
        seen.add(ident)
        if ident not in visible:
            errors.append(f"ELI5 requirement {ident} must be visibly labeled in its row")
        for field in AXES:
            if row.get("data-" + field) != expected[ident][field]:
                errors.append(f"ELI5 requirement {ident} {field} disagrees with P04 evidence")
    for ident in sorted(set(expected) - seen):
        errors.append(f"ELI5 requirement row is missing: {ident}")
    return errors
