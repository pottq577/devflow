"""Developer decisions and reversible provisional product policies.

The records live in DECISIONS.md, separately from blocking Open decisions. A
provisional policy never resolves an existing blocking decision or audit finding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEC_ID = re.compile(r"DEC-[A-Z0-9][A-Z0-9-]*\Z")
REQ_ID = re.compile(r"(?:REQ|RULE|SEC|NFR|IDEM)-[A-Z0-9-]+\Z")
WORK_ID = re.compile(r"[A-Z0-9]+-(?:I|R)[A-Z0-9-]+\Z")
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*$")
DEC_HEADING = re.compile(r"^(DEC-[A-Z0-9][A-Z0-9-]*)(?:\s+[\u2014-]\s+(.+))?$", re.I)
FIELD = re.compile(r"^\s*-\s*([A-Za-z][A-Za-z ]*):\s*(.*?)\s*$")
SECTIONS = {"Technical decisions": "technical", "Policy assumptions": "policy"}
POLICY_STATUSES = frozenset({"provisional", "approved", "rejected", "reconciled"})
CONTRACT_IMPACT = frozenset({"none", "possible"})
CATEGORIES = frozenset({"ui", "workflow", "business-rule", "calculation"})
RISK = frozenset({"low", "medium"})
TECH_FIELDS = ("Decision", "Rationale", "Decided by", "Original difference", "Requirements")
POLICY_FIELDS = (
    "Status", "Original behavior", "Assumption", "Basis", "Alternatives",
    "Contract impact", "Impact description", "Rollback", "Risk", "Category",
    "Proposed by", "Confirmation owner", "Requirements", "Approved policy",
    "Approval authority", "Approval evidence", "Conformance", "Corrective WORK",
    "Resolution evidence",
)


class PolicyError(ValueError):
    """The decision record or proposed transition is invalid."""


@dataclass
class Record:
    identifier: str
    title: str
    kind: str
    fields: dict[str, str]
    start: int
    end: int


def _value(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{name} must be a nonblank single line")
    value = value.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise PolicyError(f"{name} must be a nonblank single line")
    if value in {"-", "TBD", "TODO"} or (value.startswith("[") and value.endswith("]")):
        raise PolicyError(f"{name} must be a concrete value")
    return value


def _ids(name: str, values: Any, pattern: re.Pattern[str], *, needed: bool = True) -> list[str]:
    if not isinstance(values, list):
        raise PolicyError(f"{name} must be a list")
    ids = [_value(name, value) for value in values]
    if (needed and not ids) or any(not pattern.fullmatch(x) for x in ids) or len(ids) != len(set(ids)):
        raise PolicyError(f"{name} must contain unique valid identifiers")
    return ids


def _split_ids(value: str, pattern: re.Pattern[str]) -> list[str]:
    if value == "-":
        return []
    ids = [v.strip() for v in value.split(",")]
    if not ids or any(not pattern.fullmatch(v) for v in ids) or len(ids) != len(set(ids)):
        raise PolicyError(f"Invalid identifier list: {value}")
    return ids


def _visible_lines(text: str) -> list[str]:
    """Ignore fenced code when interpreting headings and decision fields."""
    result = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        m = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if m:
            token = m.group(1)
            if fence is None:
                fence = (token[0], len(token))
            elif fence[0] == token[0] and len(token) >= fence[1]:
                fence = None
            result.append("\n")
        else:
            result.append("\n" if fence else line)
    return result


def parse(text: str) -> tuple[dict[str, Record], list[str], set[str]]:
    """Parse only the two new sections but detect collisions with legacy DEC IDs."""
    lines = text.splitlines(keepends=True)
    visible = _visible_lines(text)
    starts = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    section = ""
    candidates: list[tuple[str, str, str, int, int]] = []
    existing: set[str] = set()
    errors: list[str] = []
    open_record = -1
    for i, line in enumerate(visible):
        m = HEADING.match(line.strip("\r\n"))
        if m is None:
            continue
        level, name = len(m.group(1)), m.group(2).strip()
        if level <= 3 and open_record >= 0:
            part = list(candidates[open_record])
            part[4] = starts[i]
            candidates[open_record] = tuple(part)  # type: ignore[assignment]
            open_record = -1
        if level == 2:
            section = SECTIONS.get(name, "")
        elif level == 3:
            match = DEC_HEADING.fullmatch(name)
            if match and match.group(1).upper() != "DEC-XXX":
                identifier = match.group(1).upper()
                if identifier in existing:
                    errors.append(f"DECISIONS.md duplicate decision id: {identifier}")
                existing.add(identifier)
                if section:
                    candidates.append((identifier, (match.group(2) or "").strip(), section, starts[i], offset))
                    open_record = len(candidates) - 1
    records: dict[str, Record] = {}
    for identifier, title, kind, start, end in candidates:
        fields: dict[str, str] = {}
        raw = text[start:end].splitlines()[1:]
        for line in raw:
            match = FIELD.match(line)
            if not match:
                continue
            name, value = match.groups()
            if name in fields:
                errors.append(f"{identifier}: duplicate field {name}")
            fields[name] = value.strip()
        expected = TECH_FIELDS if kind == "technical" else POLICY_FIELDS
        for name in expected:
            if name not in fields:
                errors.append(f"{identifier}: missing field {name}")
        for name in fields:
            if name not in expected:
                errors.append(f"{identifier}: unsupported field {name}")
        if not title:
            errors.append(f"{identifier}: missing decision title")
        if identifier in records:
            continue
        records[identifier] = Record(identifier, title, kind, fields, start, end)
    return records, errors, existing


def _record_errors(record: Record) -> list[str]:
    f = record.fields
    errors = []
    for key in (TECH_FIELDS if record.kind == "technical" else POLICY_FIELDS):
        if key not in f:
            continue
        if key not in {"Approved policy", "Approval authority", "Approval evidence", "Conformance", "Corrective WORK", "Resolution evidence"}:
            try:
                _value(key, f[key])
            except PolicyError as exc:
                errors.append(f"{record.identifier}: {exc}")
    try:
        _split_ids(f.get("Requirements", ""), REQ_ID)
        if record.kind == "technical":
            if f.get("Original difference") not in {"none", "technical"}:
                errors.append(f"{record.identifier}: invalid original difference")
        else:
            if f.get("Status") not in POLICY_STATUSES:
                errors.append(f"{record.identifier}: invalid policy status")
            if f.get("Contract impact") not in CONTRACT_IMPACT:
                errors.append(f"{record.identifier}: cannot provisionally assume confirmed-impact policy")
            if f.get("Risk") not in RISK or f.get("Category") not in CATEGORIES:
                errors.append(f"{record.identifier}: unsafe provisional classification")
            followups = _split_ids(f.get("Corrective WORK", ""), WORK_ID)
            if f.get("Status") in {"approved", "rejected", "reconciled"}:
                for key in ("Approved policy", "Approval authority", "Approval evidence"):
                    _value(key, f.get(key))
                if f.get("Conformance") not in {"matches", "changed"}:
                    errors.append(f"{record.identifier}: approval requires conformance")
                if f.get("Conformance") == "changed" and not followups:
                    errors.append(f"{record.identifier}: changed policy requires corrective WORK")
            if f.get("Status") in {"rejected", "reconciled"} and not followups:
                errors.append(f"{record.identifier}: rejected policy requires corrective WORK")
            if f.get("Status") == "reconciled":
                _value("Resolution evidence", f.get("Resolution evidence"))
    except PolicyError as exc:
        errors.append(f"{record.identifier}: {exc}")
    return errors


def record_errors(record: Record) -> list[str]:
    """Structural errors for one parsed decision record."""
    return _record_errors(record)


def _prds(d: Path) -> set[str]:
    path = d / "PRD.md"
    if not path.is_file():
        return set()
    return set(re.findall(
        r"(?m)^#{3,6}\s+((?:REQ|RULE|SEC|NFR|IDEM)-[A-Z0-9-]+)(?=\s|$)",
        "".join(_visible_lines(path.read_text(encoding="utf-8"))),
    ))


def _render(identifier: str, title: str, fields: dict[str, str]) -> str:
    return "### " + identifier + " — " + title + "\n\n" + "".join(
        f"- {name}: {value}\n" for name, value in fields.items()
    )


def _section_append(text: str, heading: str, body: str) -> str:
    visible = _visible_lines(text)
    pos = 0
    found_start = -1
    insertion = len(text)
    for raw_line, line in zip(text.splitlines(keepends=True), visible):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if found_start >= 0:
                insertion = pos
                break
            if m.group(1).strip() == heading:
                found_start = pos
        pos += len(raw_line)
    if found_start < 0:
        return text.rstrip() + f"\n\n## {heading}\n\n" + body + "\n"
    return text[:insertion].rstrip() + "\n\n" + body + "\n\n" + text[insertion:].lstrip("\n")


def _check_new(d: Path, existing: set[str], identifier: str, requirements: list[str]) -> None:
    if not DEC_ID.fullmatch(identifier) or identifier in existing:
        raise PolicyError(f"Decision ID is invalid or already exists: {identifier}")
    unknown = sorted(set(requirements) - _prds(d))
    if unknown:
        raise PolicyError("No PRD requirement heading for: " + ", ".join(unknown))


def _corrective_errors(
    decision: Record,
    index: dict[str, tuple[Path, dict[str, Any]]],
    review_satisfied: Callable[[dict[str, Any]], bool],
) -> list[str]:
    work_ids = _split_ids(decision.fields["Corrective WORK"], WORK_ID)
    reqs = set(_split_ids(decision.fields["Requirements"], REQ_ID))
    errors: list[str] = []
    for work_id in work_ids:
        item_pair = index.get(work_id)
        if item_pair is None:
            errors.append(f"{decision.identifier}: corrective WORK absent: {work_id}")
            continue
        item = item_pair[1]
        origin = item.get("origin") or {}
        if not isinstance(origin, dict):
            origin = {}
        if decision.identifier not in (origin.get("policy_assumptions") or []):
            errors.append(f"{decision.identifier}: corrective WORK {work_id} lacks policy_assumptions link")
        if not reqs.intersection(origin.get("requirements") or []):
            errors.append(f"{decision.identifier}: corrective WORK {work_id} lacks requirement link")
        if item.get("status") != "done" or not review_satisfied(item):
            errors.append(f"{decision.identifier}: corrective WORK {work_id} is not verified done")
    return errors


def outstanding(
    d: Path,
    index: dict[str, tuple[Path, dict[str, Any]]],
    review_satisfied: Callable[[dict[str, Any]], bool],
) -> list[str]:
    """Return finalization blockers without blocking independent implementation WORK."""
    path = d / "DECISIONS.md"
    if not path.is_file():
        return []
    records, errors, _ = parse(path.read_text(encoding="utf-8"))
    for record in records.values():
        errors.extend(_record_errors(record))
    if errors:
        return errors
    blockers = []
    for work_id, (_, item) in index.items():
        origin = item.get("origin") or {}
        if not isinstance(origin, dict):
            continue
        for decision_id in origin.get("policy_assumptions") or []:
            record = records.get(decision_id)
            if record is None or record.kind != "policy":
                blockers.append(f"{work_id}: missing referenced policy {decision_id}")
    for record in records.values():
        if record.kind != "policy":
            continue
        status = record.fields.get("Status")
        if status in {"provisional", "rejected"}:
            blockers.append(f"{record.identifier}: policy {status}, product contract not closed")
        elif status in {"approved", "reconciled"}:
            matching_work = [
                item for _, item in index.values()
                if isinstance(item.get("origin"), dict)
                and record.identifier in (item["origin"].get("policy_assumptions") or [])
            ]
            if not matching_work or not any(
                item.get("status") == "done" and review_satisfied(item)
                for item in matching_work
            ):
                blockers.append(f"{record.identifier}: no verified implementation WORK linked")
            if record.fields.get("Corrective WORK") != "-":
                blockers.extend(_corrective_errors(record, index, review_satisfied))
    return blockers


def validate(
    d: Path,
    index: dict[str, tuple[Path, dict[str, Any]]],
    review_satisfied: Callable[[dict[str, Any]], bool],
    *,
    final: bool = False,
) -> tuple[list[str], list[str]]:
    path = d / "DECISIONS.md"
    if not path.is_file():
        return [], []
    records, errors, _ = parse(path.read_text(encoding="utf-8"))
    warnings: list[str] = []
    prd_ids = _prds(d)
    linked: set[str] = set()
    for record in records.values():
        errors.extend(_record_errors(record))
        try:
            refs = set(_split_ids(record.fields.get("Requirements", ""), REQ_ID))
        except PolicyError:
            continue
        for missing in sorted(refs - prd_ids):
            errors.append(f"{record.identifier}: requirement missing from PRD: {missing}")
    for work_id, (_, item) in index.items():
        origin = item.get("origin") or {}
        if not isinstance(origin, dict):
            continue
        reqs = set(origin.get("requirements") or [])
        for field, kind in (("technical_decisions", "technical"), ("policy_assumptions", "policy")):
            values = origin.get(field, []) or []
            if not isinstance(values, list) or len(values) != len(set(str(v) for v in values)):
                errors.append(f"{work_id}: origin.{field} must be unique list")
                continue
            for identifier in values:
                record = records.get(identifier)
                if record is None or record.kind != kind:
                    errors.append(f"{work_id}: origin.{field} references unknown {kind} decision {identifier}")
                    continue
                linked.add(identifier)
                try:
                    linked_reqs = set(_split_ids(record.fields.get("Requirements", ""), REQ_ID))
                except PolicyError:
                    continue
                if not (reqs & linked_reqs):
                    errors.append(f"{work_id}: {identifier} has no matching requirement origin")
    for record in records.values():
        if record.identifier not in linked:
            warnings.append(f"{record.identifier}: no WORK origin links decision")
        if record.kind == "policy" and record.fields.get("Status") in {"provisional", "rejected"}:
            warnings.append(f"{record.identifier}: product policy confirmation/reconciliation pending")
    if final:
        errors.extend(outstanding(d, index, review_satisfied))
    return sorted(set(errors)), sorted(set(warnings))


def apply(
    d: Path,
    command: str,
    args: Any,
    index: dict[str, tuple[Path, dict[str, Any]]] | None = None,
    review_satisfied: Callable[[dict[str, Any]], bool] | None = None,
) -> str:
    """Return a complete updated DECISIONS.md; caller owns its atomic write."""
    path = d / "DECISIONS.md"
    if not path.is_file():
        raise PolicyError("DECISIONS.md not found")
    text = path.read_text(encoding="utf-8")
    records, errors, existing = parse(text)
    if errors:
        raise PolicyError("; ".join(errors))
    identifier = _value("decision", args.decision)
    if command in {"technical", "assume"}:
        reqs = _ids("requirements", args.requirement, REQ_ID)
        _check_new(d, existing, identifier, reqs)
        title = _value("title", args.title)
        if command == "technical":
            fields = {
                "Decision": _value("decision text", args.text),
                "Rationale": _value("rationale", args.rationale),
                "Decided by": _value("decided by", args.by),
                "Original difference": args.original_difference,
                "Requirements": ", ".join(reqs),
            }
            heading = "Technical decisions"
        else:
            if args.risk not in RISK or args.contract_impact not in CONTRACT_IMPACT or args.category not in CATEGORIES:
                raise PolicyError("Provisional policy is restricted to low/medium reversible product choices")
            if not args.safe_to_prototype:
                raise PolicyError("--safe-to-prototype attestation is required")
            fields = {
                "Status": "provisional",
                "Original behavior": _value("original behavior", args.original_behavior),
                "Assumption": _value("assumption", args.assumption),
                "Basis": _value("basis", args.basis),
                "Alternatives": _value("alternatives", args.alternatives),
                "Contract impact": args.contract_impact,
                "Impact description": _value("impact description", args.impact_description),
                "Rollback": _value("rollback", args.rollback),
                "Risk": args.risk,
                "Category": args.category,
                "Proposed by": _value("proposed by", args.by),
                "Confirmation owner": _value("confirmation owner", args.confirmation_owner),
                "Requirements": ", ".join(reqs),
                "Approved policy": "-",
                "Approval authority": "-",
                "Approval evidence": "-",
                "Conformance": "-",
                "Corrective WORK": "-",
                "Resolution evidence": "-",
            }
            heading = "Policy assumptions"
        return _section_append(text, heading, _render(identifier, title, fields))

    record = records.get(identifier)
    if record is None or record.kind != "policy":
        raise PolicyError(f"No provisional policy record: {identifier}")
    fields = dict(record.fields)
    if command in {"approve", "reject"}:
        if fields.get("Status") != "provisional":
            raise PolicyError(f"{identifier}: transition requires provisional status")
        authority = _value("approval authority", args.by)
        evidence = _value("approval evidence", args.evidence)
        approved_policy = _value("approved policy", args.approved_policy)
        fixes = _ids("corrective WORK", args.corrective_work, WORK_ID, needed=False)
        if command == "approve":
            matches = args.matches_assumption
            if matches and approved_policy != fields["Assumption"]:
                raise PolicyError("--matches-assumption requires the exact assumed policy")
            if not matches and not fixes:
                raise PolicyError("Changed approved policy requires --corrective-work")
            status = "approved"
            conformance = "matches" if matches else "changed"
        else:
            if not fixes:
                raise PolicyError("Rejected policy requires --corrective-work")
            if approved_policy == fields["Assumption"]:
                raise PolicyError("Rejected policy must select a different product contract")
            status, conformance = "rejected", "changed"
        fields.update({
            "Status": status,
            "Approved policy": approved_policy,
            "Approval authority": authority,
            "Approval evidence": evidence,
            "Conformance": conformance,
            "Corrective WORK": ", ".join(fixes) if fixes else "-",
        })
    elif command == "reconcile":
        if fields.get("Status") != "rejected":
            raise PolicyError("Only rejected policies can be reconciled")
        if index is None or review_satisfied is None:
            raise PolicyError("Work evidence is required to reconcile a rejected policy")
        blockers = _corrective_errors(record, index, review_satisfied)
        if blockers:
            raise PolicyError("; ".join(blockers))
        fields.update({
            "Status": "reconciled",
            "Resolution evidence": _value("resolution evidence", args.evidence),
        })
    else:
        raise PolicyError(f"Unknown policy action: {command}")
    replacement = _render(identifier, record.title, fields)
    return text[:record.start] + replacement + text[record.end:]


def summary(d: Path) -> list[dict[str, Any]]:
    path = d / "DECISIONS.md"
    if not path.is_file():
        return []
    records, errors, _ = parse(path.read_text(encoding="utf-8"))
    if errors:
        raise PolicyError("; ".join(errors))
    return [
        {"id": r.identifier, "kind": r.kind, "title": r.title, **r.fields}
        for r in records.values()
    ]
