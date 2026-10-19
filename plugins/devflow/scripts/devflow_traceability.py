"""Validate requirement provenance across captured sources, PRD, PLAN, and WORK.

This reads existing artifacts and never updates lifecycle state. It checks declared
links and evidence locations, not the semantic correctness of product requirements.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import devflow_sources as sources

REQUIREMENT_ID = re.compile(r"(?:REQ|RULE|SEC|NFR|IDEM)-[A-Z0-9-]+\Z")
REQUIREMENT_HEADING = re.compile(
    r"^#{3,6}\s+((?:REQ|RULE|SEC|NFR|IDEM)-[A-Z0-9-]+)(?=\s|$)"
)
ACCEPTANCE = re.compile(r"^\s*(?:-\s*)?(AC-[A-Z0-9-]+)\s*:")
DECISION_ID = re.compile(r"\bDEC-[A-Z0-9-]+\b")
LINE_RANGE = re.compile(r"L([1-9][0-9]*)-L([1-9][0-9]*)\Z")
SOURCE_HEADING = re.compile(r"^##\s+(?:\d+\.\s+)?Source traceability\s*$", re.I)
PLAN_HEADING = re.compile(r"^##\s+(?:\d+\.\s+)?Requirement traceability\s*$", re.I)
SOURCE_COLUMNS = ("source", "lines", "disposition", "requirements", "reason")
PLAN_COLUMNS = ("requirement", "plan item", "phase", "work items", "disposition", "reason")
SOURCE_DISPOSITIONS = frozenset({"mapped", "reference", "background", "excluded", "pending"})
PLAN_DISPOSITIONS = frozenset({"implement", "transferred", "excluded", "deferred", "cancelled"})
MAX_GAPS = 16


def _content_lines(text: str) -> list[str]:
    """Keep line indices stable while ignoring IDs and headings in fenced code."""
    result: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = (token[0], len(token))
            elif token[0] == fence[0] and len(token) >= fence[1]:
                fence = None
            result.append("")
        else:
            result.append("" if fence is not None else line)
    return result


def _cells(text: str) -> list[str] | None:
    if not text.strip().startswith("|") or not text.strip().endswith("|"):
        return None
    # Escaped pipes are supported; literal pipes need to be escaped by the writer.
    return [part.strip().replace(r"\|", "|") for part in re.split(r"(?<!\\)\|", text.strip())[1:-1]]


def _table(
    text: str, pattern: re.Pattern[str], columns: tuple[str, ...], label: str
) -> tuple[list[tuple[int, dict[str, str]]], list[str]]:
    lines = _content_lines(text)
    headings = [i for i, line in enumerate(lines) if pattern.fullmatch(line.strip())]
    if len(headings) != 1:
        return [], [f"{label}: expected one {label} table heading; found {len(headings)}"]
    start = headings[0] + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start + 1 >= len(lines):
        return [], [f"{label}: table header or separator is missing"]
    header = _cells(lines[start])
    divider = _cells(lines[start + 1])
    if header is None or tuple(col.lower() for col in header) != columns:
        return [], [f"{label}: expected table columns: {', '.join(columns)}"]
    if divider is None or len(divider) != len(columns) or any(
        not re.fullmatch(r":?-{3,}:?", col) for col in divider
    ):
        return [], [f"{label}: invalid table separator"]
    rows: list[tuple[int, dict[str, str]]] = []
    errors: list[str] = []
    for offset in range(start + 2, len(lines)):
        line = lines[offset]
        if not line.strip() or line.lstrip().startswith("#"):
            break
        cells = _cells(line)
        if cells is None or len(cells) != len(columns):
            errors.append(f"{label}: invalid row at line {offset + 1}")
            continue
        rows.append((offset + 1, dict(zip(columns, cells))))
    if not rows:
        errors.append(f"{label}: table has no rows")
    return rows, errors


def _ids(cell: str, *, requirement: bool = True) -> list[str] | None:
    if cell in {"", "-"}:
        return []
    parts = [part.strip() for part in cell.split(",")]
    if any(not part or (requirement and not REQUIREMENT_ID.fullmatch(part)) for part in parts):
        return None
    if len(parts) != len(set(parts)):
        return None
    return parts


def _requirements(prd: str) -> tuple[dict[str, set[str]], list[str]]:
    result: dict[str, set[str]] = {}
    acceptance_owner: dict[str, str] = {}
    errors: list[str] = []
    active: str | None = None
    for number, line in enumerate(_content_lines(prd), 1):
        if line.startswith("## "):
            active = None
        heading = REQUIREMENT_HEADING.match(line)
        if heading:
            name = heading.group(1)
            if name in result:
                errors.append(f"PRD: duplicate requirement {name} at line {number}")
            result.setdefault(name, set())
            active = name
        ac = ACCEPTANCE.match(line)
        if ac and active:
            name = ac.group(1)
            if name in acceptance_owner:
                errors.append(f"PRD: duplicate acceptance {name} at line {number}")
            acceptance_owner[name] = active
            result[active].add(name)
    if not result:
        errors.append("PRD: no stable requirement headings found")
    return result, errors


def _resolved_decisions(text: str) -> set[str]:
    resolved: set[str] = set()
    in_resolved = False
    active: str | None = None
    has_decision = False
    for line in _content_lines(text):
        if line.startswith("## "):
            if active and has_decision and in_resolved:
                resolved.add(active)
            active = None
            in_resolved = line.strip().lower() == "## resolved"
            has_decision = False
            continue
        m = re.match(r"^###\s+(DEC-[A-Z0-9-]+)(?=\s|$)", line)
        if m:
            if active and has_decision and in_resolved:
                resolved.add(active)
            active = m.group(1)
            has_decision = False
        elif active and re.match(r"^\s*-\s*Decision:\s*\S", line):
            value = line.split(":", 1)[1].strip()
            has_decision = value.lower() not in {"tbd", "todo"} and not value.startswith("[")
    if active and has_decision and in_resolved:
        resolved.add(active)
    return resolved


def _approved(reason: str, decisions: set[str], *, require_decisions: bool) -> bool:
    cited = set(DECISION_ID.findall(reason))
    return bool(cited & decisions) if require_decisions else bool(cited)


def _gaps(covered: set[int], source_lines: list[str]) -> list[str]:
    missing = [i for i, line in enumerate(source_lines, 1) if line.strip() and i not in covered]
    if not missing:
        return []
    grouped: list[tuple[int, int]] = []
    for line in missing:
        if grouped and grouped[-1][1] + 1 == line:
            grouped[-1] = (grouped[-1][0], line)
        else:
            grouped.append((line, line))
    ranges = [f"L{first}-L{last}" for first, last in grouped[:MAX_GAPS]]
    if len(grouped) > MAX_GAPS:
        ranges.append(f"and {len(grouped) - MAX_GAPS} more ranges")
    return ranges


def has_source_table(prd_file: Path) -> bool:
    """Locate the explicit source contract without depending on document numbering."""
    return prd_file.is_file() and any(
        SOURCE_HEADING.fullmatch(line.strip())
        for line in _content_lines(prd_file.read_text(encoding="utf-8"))
    )


def validate_domain(
    domain_dir: Path,
    index: Mapping[str, tuple[Path, dict[str, Any]]],
    *,
    require_plan: bool = True,
    require_decisions: bool = True,
    strict: bool = False,
) -> tuple[list[str], list[str]]:
    """Validate captured-source traceability, preserving legacy untracked domains."""
    snapshot_dir = domain_dir / "sources" / "v1"
    prd_file = domain_dir / "PRD.md"
    declares_table = has_source_table(prd_file)
    if not snapshot_dir.exists() and not snapshot_dir.is_symlink():
        if strict:
            return ["traceability: required captured sources are missing"], []
        if declares_table:
            return ["traceability: declared source mapping has no captured sources"], []
        return [], []
    errors: list[str] = []
    warnings: list[str] = []
    if not declares_table and not strict:
        warnings.append(
            "traceability: existing captured domain has no source mapping; "
            "add the source table to enable P02 validation"
        )
        return errors, warnings
    try:
        sources.verify(domain_dir, domain_dir, domain_dir.name)
    except (sources.SourceError, OSError) as exc:
        return [f"traceability: invalid source snapshot: {exc}"], warnings

    original_text = (domain_dir / "sources/v1/original.md").read_text(encoding="utf-8-sig")
    context_text = (domain_dir / "sources/v1/context.md").read_text(encoding="utf-8-sig")
    raw_sources = {
        "original:v1": original_text.splitlines(),
        "context:v1": context_text.splitlines(),
    }
    prd_path = domain_dir / "PRD.md"
    if not prd_path.is_file():
        return ["traceability: PRD.md missing"], warnings
    prd_text = prd_path.read_text(encoding="utf-8")
    requirements, found = _requirements(prd_text)
    errors.extend(found)
    resolved = _resolved_decisions(
        (domain_dir / "DECISIONS.md").read_text(encoding="utf-8")
        if (domain_dir / "DECISIONS.md").is_file() else ""
    )
    rows, found = _table(prd_text, SOURCE_HEADING, SOURCE_COLUMNS, "PRD source traceability")
    errors.extend(found)
    covered: dict[str, set[int]] = {role: set() for role in raw_sources}
    originated: set[str] = set()
    for number, row in rows:
        src = row["source"]
        match = LINE_RANGE.fullmatch(row["lines"])
        disposition = row["disposition"].lower()
        ids = _ids(row["requirements"])
        if src not in raw_sources or match is None or disposition not in SOURCE_DISPOSITIONS or ids is None:
            errors.append(f"PRD source traceability: invalid row at line {number}")
            continue
        start, end = (int(match.group(1)), int(match.group(2)))
        if start > end or end > len(raw_sources[src]):
            errors.append(f"PRD source traceability: out-of-bounds {src} {row['lines']}")
            continue
        overlap = covered[src].intersection(range(start, end + 1))
        if overlap:
            errors.append(f"PRD source traceability: overlapping {src} at L{min(overlap)}")
        covered[src].update(range(start, end + 1))
        if not row["reason"] or row["reason"].startswith("["):
            errors.append(f"PRD source traceability: missing reason at line {number}")
        for ident in ids:
            if ident not in requirements:
                errors.append(f"PRD source traceability: unknown requirement {ident}")
        if disposition in {"mapped", "reference"} and not ids:
            errors.append(f"PRD source traceability: {disposition} needs requirements at line {number}")
        if disposition in {"background", "excluded"} and ids:
            errors.append(f"PRD source traceability: {disposition} cannot reference requirements at line {number}")
        if disposition == "excluded" and not _approved(row["reason"], resolved, require_decisions=require_decisions):
            errors.append(f"PRD source traceability: excluded source needs resolved DEC at line {number}")
        if disposition == "reference" and src != "context:v1":
            errors.append(f"PRD source traceability: reference is for supplemental context only at line {number}")
        if disposition == "mapped":
            if src == "context:v1" and not _approved(row["reason"], resolved, require_decisions=require_decisions):
                errors.append(f"PRD source traceability: context-only mapped requirements need resolved DEC at line {number}")
            else:
                originated.update(ids)
    for src, source_lines in raw_sources.items():
        gaps = _gaps(covered[src], source_lines)
        if gaps:
            errors.append(f"PRD source traceability: uncovered {src} lines: {', '.join(gaps)}")
    for req in sorted(set(requirements) - originated):
        errors.append(f"PRD source traceability: {req} has no original or approved source mapping")

    original_headings = {
        m.group(1) for line in _content_lines(original_text)
        if (m := REQUIREMENT_HEADING.match(line))
    }
    for req in sorted(original_headings - set(requirements)):
        # A resolved exclusion may omit an originally identified requirement.
        excluded = any(
            row["source"] == "original:v1" and row["disposition"] == "excluded"
            and _approved(row["reason"], resolved, require_decisions=require_decisions)
            and (m := LINE_RANGE.fullmatch(row["lines"]))
            and any(
                REQUIREMENT_HEADING.match(line) and REQUIREMENT_HEADING.match(line).group(1) == req
                for line in original_text.splitlines()[int(m.group(1)) - 1:int(m.group(2))]
            )
            for _, row in rows
        )
        if not excluded:
            errors.append(f"PRD: original requirement {req} absent from PRD and not excluded")

    if not require_plan:
        return errors, warnings

    plan_path = domain_dir / "PLAN.md"
    if not plan_path.is_file():
        return [*errors, "traceability: PLAN.md missing"], warnings
    plan_rows, found = _table(
        plan_path.read_text(encoding="utf-8"), PLAN_HEADING, PLAN_COLUMNS,
        "PLAN requirement traceability",
    )
    errors.extend(found)
    plan_by_req: dict[str, dict[str, str]] = {}
    linked_work: dict[str, set[str]] = {}
    for number, row in plan_rows:
        req = row["requirement"]
        disposition = row["disposition"].lower()
        work_ids = _ids(row["work items"], requirement=False)
        if not REQUIREMENT_ID.fullmatch(req) or disposition not in PLAN_DISPOSITIONS or work_ids is None:
            errors.append(f"PLAN requirement traceability: invalid row at line {number}")
            continue
        if req not in requirements:
            errors.append(f"PLAN requirement traceability: unknown requirement {req}")
        if req in plan_by_req:
            errors.append(f"PLAN requirement traceability: duplicate requirement {req}")
        plan_by_req[req] = row
        if not row["reason"] or row["reason"].startswith("["):
            errors.append(f"PLAN requirement traceability: missing reason for {req}")
        if disposition in {"excluded", "deferred", "cancelled"} and not _approved(row["reason"], resolved, require_decisions=require_decisions):
            errors.append(f"PLAN requirement traceability: {disposition} {req} needs resolved DEC")
        if disposition in {"excluded", "deferred"} and work_ids:
            errors.append(f"PLAN requirement traceability: {disposition} {req} cannot link active WORK")
        if disposition in {"implement", "transferred"} and (
            not work_ids or row["plan item"] == "-" or row["phase"] == "-"
        ):
            errors.append(f"PLAN requirement traceability: {req} missing plan/phase/WORK")
        linked_work[req] = set(work_ids)
        for work_id in work_ids:
            if work_id not in index:
                errors.append(f"PLAN requirement traceability: {req} unknown WORK {work_id}")
                continue
            work = index[work_id][1]
            origin = work.get("origin") or {}
            if req not in (origin.get("requirements") or []):
                errors.append(f"PLAN requirement traceability: {work_id} does not link {req}")
            if disposition == "cancelled" and work.get("status") != "cancelled":
                errors.append(f"PLAN requirement traceability: {req} links non-cancelled WORK {work_id}")
        if disposition == "transferred":
            senders = [index[work_id][1] for work_id in work_ids if work_id in index
                       and index[work_id][1].get("status") == "transferred"]
            if not senders or not any(
                (sender.get("transfer") or {}).get("to") in work_ids for sender in senders
            ):
                errors.append(f"PLAN requirement traceability: {req} transfer sender/receiver not linked")
    for req in sorted(set(requirements) - set(plan_by_req)):
        errors.append(f"PLAN requirement traceability: missing requirement {req}")
    covered_acceptance: set[str] = set()
    owners = {ac: req for req, criteria in requirements.items() for ac in criteria}
    for work_id, (_, work) in index.items():
        origin = work.get("origin") or {}
        work_reqs = origin.get("requirements") or []
        acs = origin.get("acceptance_criteria") or []
        if (not isinstance(work_reqs, list) or not isinstance(acs, list)
                or any(not isinstance(req, str) for req in work_reqs)
                or any(not isinstance(ac, str) for ac in acs)):
            errors.append(f"{work_id}: origin traceability must use string lists")
            continue
        for req in work_reqs:
            if req not in requirements:
                errors.append(f"{work_id}: unknown PRD requirement {req}")
            elif work_id not in linked_work.get(req, set()):
                errors.append(f"{work_id}: unlisted WORK origin for {req} in PLAN")
        if len(acs) != len(set(str(value) for value in acs)):
            errors.append(f"{work_id}: duplicate origin.acceptance_criteria")
        for ac in acs:
            if ac not in owners:
                errors.append(f"{work_id}: unknown PRD acceptance {ac}")
            elif owners[ac] not in work_reqs:
                errors.append(f"{work_id}: acceptance {ac} lacks parent requirement {owners[ac]}")
            else:
                covered_acceptance.add(ac)
    for req, criteria in requirements.items():
        if plan_by_req.get(req, {}).get("disposition", "").lower() in {"excluded", "deferred", "cancelled"}:
            continue
        for ac in sorted(criteria - covered_acceptance):
            errors.append(f"PLAN requirement traceability: missing WORK mapping for {ac} ({req})")
    return errors, warnings
