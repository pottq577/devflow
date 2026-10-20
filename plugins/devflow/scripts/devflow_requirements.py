"""Derive independent requirement states from PRD, PLAN, WORK, and decisions.

The snapshot is read-only. Absence of implementation, comparison or verification
proof is not evidence that a feature is absent, aligned, or successfully tested.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

import devflow_policy as policy
import devflow_sources as sources
import devflow_traceability as traceability
import yaml

COMPARISONS = frozenset({"aligned", "technical_deviation", "policy_deviation"})
SOURCE_LOCATION = re.compile(r"original:v1\s+L([1-9][0-9]*)-L([1-9][0-9]*)\Z")
REQUIREMENT_TITLE = re.compile(
    r"^#{3,6}\s+((?:REQ|RULE|SEC|NFR|IDEM)-[A-Z0-9-]+)(?:\s+(?:[-\u2014]\s*)?(.*))?$"
)
SCOPE_CLOSED = frozenset({"excluded", "deferred", "cancelled"})


def _origin(item: Mapping[str, Any]) -> dict[str, Any]:
    value = item.get("origin")
    return value if isinstance(value, dict) else {}


def _ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def _declared_comparisons(
    domain: Path, index: Mapping[str, tuple[Path, dict[str, Any]]],
    *, source_valid: bool,
) -> tuple[list[str], set[tuple[str, str]]]:
    """Check optional per-WORK assertions, including cited original-line provenance."""
    errors: list[str] = []
    valid: set[tuple[str, str]] = set()
    source = domain / "sources/v1/original.md"
    original = source.read_text(encoding="utf-8-sig").splitlines() if source_valid and source.is_file() and not source.is_symlink() else []
    prd = domain / "PRD.md"
    rows: list[tuple[int, dict[str, str]]] = []
    if prd.is_file() and traceability.has_source_table(prd):
        rows, _ = traceability._table(
            prd.read_text(encoding="utf-8"), traceability.SOURCE_HEADING,
            traceability.SOURCE_COLUMNS, "PRD source traceability",
        )
    mapped: dict[str, list[tuple[int, int]]] = {}
    records, _, _ = policy.parse((domain / "DECISIONS.md").read_text(encoding="utf-8")
                                 if (domain / "DECISIONS.md").is_file() else "")
    for _, row in rows:
        location = traceability.LINE_RANGE.fullmatch(row["lines"])
        if row["source"] != "original:v1" or row["disposition"] != "mapped" or not location:
            continue
        for req in (traceability._ids(row["requirements"]) or []):
            mapped.setdefault(req, []).append((int(location.group(1)), int(location.group(2))))
    for work_id, (_, item) in sorted(index.items()):
        origin = _origin(item)
        comparisons = origin.get("original_comparison")
        if comparisons is None:
            continue
        if not isinstance(comparisons, dict):
            errors.append(f"{work_id}: origin.original_comparison must be a mapping")
            continue
        for req, entry in comparisons.items():
            starting_errors = len(errors)
            label = f"{work_id}: original_comparison[{req}]"
            if not isinstance(req, str) or req not in _ids(origin.get("requirements")):
                errors.append(f"{label}: requirement must belong to WORK origin")
            if not isinstance(entry, dict) or set(entry) != {"relation", "source", "evidence"}:
                errors.append(f"{label}: expected relation, source, evidence")
                continue
            relation = entry["relation"]
            if relation not in COMPARISONS:
                errors.append(f"{label}: invalid relation")
            technical_links = _ids(origin.get("technical_decisions"))
            policy_links = _ids(origin.get("policy_assumptions"))
            technical_difference = any(
                dec in records and records[dec].kind == "technical"
                and records[dec].fields.get("Original difference") == "technical"
                and req in [x.strip() for x in records[dec].fields.get("Requirements", "").split(",")]
                for dec in technical_links
            )
            policy_linked = any(
                dec in records and records[dec].kind == "policy"
                and req in [x.strip() for x in records[dec].fields.get("Requirements", "").split(",")]
                for dec in policy_links
            )
            if relation == "aligned" and technical_difference:
                errors.append(f"{label}: aligned contradicts linked technical difference")
            if relation == "technical_deviation" and not technical_difference:
                errors.append(f"{label}: technical deviation requires linked developer decision")
            if relation == "policy_deviation" and not policy_linked:
                errors.append(f"{label}: policy deviation requires linked policy record")
            evidence = entry["evidence"]
            if not isinstance(evidence, str) or not evidence.strip() or evidence.strip().upper() in {"TODO", "TBD"}:
                errors.append(f"{label}: comparison needs concrete evidence")
            location = entry["source"]
            match = SOURCE_LOCATION.fullmatch(location) if isinstance(location, str) else None
            if not match or not original:
                errors.append(f"{label}: captured original:v1 line range is required")
                continue
            start, end = int(match.group(1)), int(match.group(2))
            if start > end or end > len(original) or not any(
                left <= start <= end <= right for left, right in mapped.get(req, [])
            ):
                errors.append(f"{label}: source range is outside the PRD original mapping")
            if len(errors) == starting_errors:
                valid.add((work_id, req))
    return errors, valid


def _titles(prd: str) -> dict[str, str]:
    titles: dict[str, str] = {}
    for line in traceability._content_lines(prd):
        match = REQUIREMENT_TITLE.fullmatch(line.strip())
        if match:
            titles.setdefault(match.group(1), (match.group(2) or "").strip())
    return titles


def _plan_rows(domain: Path) -> tuple[dict[str, dict[str, str]], list[str]]:
    path = domain / "PLAN.md"
    if not path.is_file():
        return {}, []
    if not any(traceability.PLAN_HEADING.fullmatch(line.strip()) for line in
               traceability._content_lines(path.read_text(encoding="utf-8"))):
        return {}, []
    rows, errors = traceability._table(
        path.read_text(encoding="utf-8"), traceability.PLAN_HEADING,
        traceability.PLAN_COLUMNS, "PLAN requirement traceability",
    )
    by_id: dict[str, dict[str, str]] = {}
    for line, row in rows:
        req = row["requirement"]
        if req in by_id:
            errors.append(f"PLAN requirement traceability: duplicate {req} at line {line}")
        else:
            by_id[req] = row
    return by_id, errors


def validate_comparisons(
    domain: Path, index: Mapping[str, tuple[Path, dict[str, Any]]]
) -> tuple[list[str], set[tuple[str, str]]]:
    """Enforce declarations only when provided; existing WORK remains untouched."""
    snapshot = domain / "sources/v1"
    source_valid = False
    errors: list[str] = []
    if snapshot.exists() or snapshot.is_symlink():
        try:
            sources.verify(domain, domain, domain.name)
            source_valid = True
        except (sources.SourceError, OSError) as exc:
            errors.append(f"source integrity: {exc}")
    declared, valid = _declared_comparisons(domain, index, source_valid=source_valid)
    return [*errors, *declared], valid


def _sources(domain: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    mapped: dict[str, list[dict[str, str]]] = {}
    metadata: dict[str, Any] = {}
    manifest = domain / "sources/v1/manifest.json"
    if manifest.is_file() and not manifest.is_symlink():
        try:
            obj = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(obj, dict) and isinstance(obj.get("sources"), dict):
                metadata = {
                    "revision": obj.get("revision"),
                    "sources": {
                        role: {"sha256": value.get("sha256"), "size_bytes": value.get("size_bytes")}
                        for role, value in obj["sources"].items() if isinstance(value, dict)
                    },
                }
        except (OSError, UnicodeError, ValueError):
            pass
    prd = domain / "PRD.md"
    if not prd.is_file() or not traceability.has_source_table(prd):
        return mapped, metadata
    rows, _ = traceability._table(
        prd.read_text(encoding="utf-8"), traceability.SOURCE_HEADING,
        traceability.SOURCE_COLUMNS, "PRD source traceability",
    )
    for _, row in rows:
        for req in traceability._ids(row["requirements"]) or []:
            mapped.setdefault(req, []).append({
                "source": row["source"], "lines": row["lines"],
                "disposition": row["disposition"],
            })
    return mapped, metadata


def _decisions(domain: Path) -> tuple[list[policy.Record], list[str]]:
    path = domain / "DECISIONS.md"
    if not path.is_file():
        return [], []
    records, errors, _ = policy.parse(path.read_text(encoding="utf-8"))
    for record in records.values():
        errors.extend(policy.record_errors(record))
    return list(records.values()), sorted(set(errors))


def _related_decisions(records: list[policy.Record], req: str, kind: str) -> list[policy.Record]:
    return [r for r in records if r.kind == kind and req in
            [x.strip() for x in r.fields.get("Requirements", "").split(",")]]


def _work_status(items: list[tuple[str, dict[str, Any]]], disposition: str, missing: bool) -> str:
    if disposition in SCOPE_CLOSED:
        return "not_implemented"
    if missing or not items:
        return "unknown"
    statuses = [item.get("status") for _, item in items]
    # A transferred sender is never evidence of implementation; its receiver must be present.
    active = [s for s in statuses if s != "transferred"]
    if not active or any(s not in {"done", "ready", "in_progress", "blocked", "cancelled"} for s in active):
        return "unknown"
    if all(s == "done" for s in active):
        return "implemented"
    if any(s in {"done", "in_progress"} for s in active):
        return "partial"
    if any(s == "cancelled" for s in active):
        return "unknown"
    return "not_implemented"


def _difference(
    items: list[tuple[str, dict[str, Any]]], req: str,
    tech: list[policy.Record], captured: bool, valid: set[tuple[str, str]],
) -> tuple[str, list[str], str]:
    kinds: set[str] = set()
    complete = bool(items) and captured
    for record in tech:
        if record.fields.get("Original difference") == "technical" and any(
            record.identifier in _ids(_origin(item).get("technical_decisions"))
            and item.get("status") == "done" for _, item in items
        ):
            kinds.add("technical_deviation")
    for work_id, item in items:
        if item.get("status") != "done":
            complete = False
            continue
        comparison = _origin(item).get("original_comparison")
        value = comparison.get(req) if isinstance(comparison, dict) else None
        if not isinstance(value, dict) or value.get("relation") not in COMPARISONS or (work_id, req) not in valid:
            complete = False
            continue
        if value["relation"] != "aligned":
            kinds.add(value["relation"])
    if "policy_deviation" in kinds:
        result = "policy_deviation"
    elif "technical_deviation" in kinds:
        result = "technical_deviation"
    elif complete:
        result = "aligned"
    else:
        result = "unknown"
    completeness = "complete" if complete else "partial" if kinds else "unknown"
    return result, sorted(kinds), completeness


def _approval(
    req: str, records: list[policy.Record],
    work: list[tuple[str, dict[str, Any]]], unresolved: set[str]
) -> tuple[str, list[str], list[str]]:
    tech = _related_decisions(records, req, "technical")
    policies = _related_decisions(records, req, "policy")
    blocking = sorted({dec for _, item in work for dec in _ids(item.get("decision_dependencies")) if dec in unresolved})
    if blocking:
        return "pending", [r.identifier for r in tech], [r.identifier for r in policies]
    raw_statuses = {r.fields.get("Status") for r in policies}
    if "rejected" in raw_statuses:
        result = "rejected"
    elif "provisional" in raw_statuses:
        result = "provisional"
    elif raw_statuses and raw_statuses <= {"approved", "reconciled"}:
        result = "approved"
    elif raw_statuses:
        result = "pending"
    elif tech:
        result = "developer_confirmed"
    else:
        result = "not_required"
    return result, sorted(r.identifier for r in tech), sorted(r.identifier for r in policies)


def _failed(item: Mapping[str, Any]) -> bool:
    evidence = item.get("evidence")
    commands = evidence.get("commands", []) if isinstance(evidence, dict) else []
    if not isinstance(commands, list):
        return False
    for row in commands:
        if not isinstance(row, dict):
            continue
        code = row.get("exit_code", row.get("returncode"))
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            return True
        if row.get("passed") is False or row.get("status") in {"fail", "failed", "error"}:
            return True
    return False


def _phase_status(domain: Path, state: Mapping[str, Any], path: Path) -> str | None:
    phases = state.get("phases") or {}
    if not isinstance(phases, dict):
        return None
    for phase in phases.values():
        if isinstance(phase, dict) and isinstance(phase.get("work_file"), str):
            if domain / phase["work_file"] == path:
                return phase.get("status")
    return None


def _freshness(root: Path | None, head: str | None, item: Mapping[str, Any]) -> str:
    if root is None or not head:
        return "unknown"
    evidence = item.get("evidence")
    if not isinstance(evidence, dict):
        return "unknown"
    commit, paths = evidence.get("commit"), evidence.get("changed_files")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        return "unknown"
    if not isinstance(paths, list) or not paths or any(
        not isinstance(p, str) or not p.strip() or Path(p).is_absolute()
        or ".." in Path(p).parts for p in paths
    ):
        return "unknown"
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, head], cwd=root,
            capture_output=True, check=False, timeout=5,
        )
        if ancestor.returncode != 0:
            return "unknown"
        diff = subprocess.run(
            ["git", "diff", "--quiet", commit, head, "--", *paths], cwd=root,
            capture_output=True, check=False, timeout=5,
        )
        if diff.returncode != 0:
            return "stale" if diff.returncode == 1 else "unknown"
        dirty = subprocess.run(
            ["git", "diff", "--quiet", head, "--", *paths], cwd=root,
            capture_output=True, check=False, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return "fresh" if dirty.returncode == 0 else "stale" if dirty.returncode == 1 else "unknown"


def _audit_verdict(
    path: Path, domain: Path, scope: str, *, expected_item: str | None = None,
) -> str:
    """Only a canonical in-domain audit with executed verification can pass."""
    if not path.resolve().is_relative_to(domain.resolve()) or not path.is_file() or path.is_symlink():
        return "unknown"
    try:
        text = path.read_text(encoding="utf-8")
        parts = text.split("---\n", 2)
        if len(parts) != 3 or parts[0] != "":
            return "unknown"
        node = yaml.compose(parts[1])
        if not isinstance(node, yaml.MappingNode) or any(
            not isinstance(key, yaml.ScalarNode) for key, _ in node.value
        ) or len(set(key.value for key, _ in node.value)) != len(node.value):
            return "unknown"
        data = yaml.safe_load(parts[1])
        if not isinstance(data, dict) or data.get("schema") != "devflow-audit-v1" or data.get("scope") != scope:
            return "unknown"
        if expected_item is not None and data.get("task") != expected_item:
            return "unknown"
        if not isinstance(data.get("target_sha"), str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}", data["target_sha"]
        ):
            return "unknown"
        commands = data.get("verification")
        if not isinstance(commands, list) or not commands or any(
            not isinstance(row, dict) or not row.get("command") or not row.get("result")
            for row in commands
        ):
            return "unknown"
        verdict = data.get("verdict")
        if any(str(row["result"]).strip().lower() in {"fail", "failed", "error"} for row in commands):
            return "failed"
        if verdict == "fail":
            return "failed"
        if verdict == "pass":
            return "passed"
        return "pending_review"
    except (OSError, UnicodeError, yaml.YAMLError):
        return "unknown"


def _phase_audit(domain: Path, state: Mapping[str, Any], path: Path) -> str:
    phases = state.get("phases") or {}
    if not isinstance(phases, dict):
        return "unknown"
    for phase_id, phase in phases.items():
        if not isinstance(phase, dict) or not isinstance(phase.get("work_file"), str):
            continue
        if domain / phase["work_file"] != path:
            continue
        if phase.get("status") != "verified":
            return "pending_review"
        file = phase.get("audit_file") or f"audits/phase-{phase_id}.md"
        return _audit_verdict(domain / file, domain, "phase")
    integration = state.get("integration") or {}
    if isinstance(integration, dict) and domain / integration.get("work_file", "work/integration.yaml") == path:
        if integration.get("status") != "verified":
            return "pending_review"
        return _audit_verdict(domain / integration.get("audit_file", "audits/integration.md"), domain, "integration")
    return "unknown"


def _verification(
    domain: Path, state: Mapping[str, Any], items: list[tuple[str, dict[str, Any]]],
    root: Path | None, head: str | None, review_satisfied: Callable[[dict[str, Any]], bool],
    acceptance_complete: bool, implementation: str,
) -> str:
    if not items or implementation == "unknown":
        return "unknown"
    if any(_failed(item) for _, item in items):
        return "failed"
    if all(item.get("status") == "ready" for _, item in items):
        return "not_run"
    if implementation != "implemented" or not acceptance_complete:
        return "pending_review"
    for work_id, item in items:
        if not review_satisfied(item):
            return "pending_review"
        # Even successful source tests must be revisited when the tested source changes.
        path = item.get("__manifest_path__")
        if isinstance(path, Path):
            phase = _phase_audit(domain, state, path)
            if phase == "failed":
                return "failed"
            if phase != "passed":
                return "pending_review" if phase == "pending_review" else "unknown"
        else:
            return "unknown"
        review = item.get("review")
        if isinstance(review, dict) and review.get("required") is True:
            audit_path = review.get("audit_file") or f"audits/work/{work_id}.md"
            audit_result = _audit_verdict(
                domain / audit_path, domain, "work", expected_item=work_id,
            )
            if audit_result == "failed":
                return "failed"
            if audit_result != "passed":
                return "pending_review" if audit_result == "pending_review" else "unknown"
        freshness = _freshness(root, head, item)
        if freshness != "fresh":
            return "stale" if freshness == "stale" else "unknown"
    return "passed"


def collect(
    domain: Path,
    index: Mapping[str, tuple[Path, dict[str, Any]]],
    state: Mapping[str, Any],
    *,
    root: Path | None = None,
    head_sha: str | None = None,
    review_satisfied: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Compute a deterministic, non-mutating P04 evidence snapshot."""
    if review_satisfied is None:
        review_satisfied = lambda item: (
            isinstance(item.get("review"), dict)
            and item["review"].get("status") in {"skipped", "verified"}
        )
    prd = domain / "PRD.md"
    requirements, errors = traceability._requirements(prd.read_text(encoding="utf-8") if prd.is_file() else "")
    titles = _titles(prd.read_text(encoding="utf-8") if prd.is_file() else "")
    plan, plan_errors = _plan_rows(domain)
    errors.extend(plan_errors)
    records, decision_errors = _decisions(domain)
    errors.extend(decision_errors)
    source_refs, source_versions = _sources(domain)
    comparison_errors, valid_comparisons = validate_comparisons(domain, index)
    errors.extend(comparison_errors)
    source_valid = bool(source_versions) and not any(
        error.startswith("source integrity:") for error in comparison_errors
    )
    if source_valid:
        traced_errors, traced_warnings = traceability.validate_domain(
            domain, index, strict=state.get("traceability_version") == 1,
        )
        errors.extend(traced_errors)
        if traced_errors:
            # An inconsistent source/PLAN mapping cannot prove original alignment.
            source_valid = False
            valid_comparisons.clear()
    else:
        traced_warnings = []
    warnings: list[str] = list(traced_warnings)
    unresolved = set(_ids(state.get("unresolved_decisions", [])))
    output = []
    for req in requirements:
        entry = plan.get(req)
        disposition = entry["disposition"].lower() if entry else "unknown"
        expected_ids = traceability._ids(entry["work items"], requirement=False) if entry else []
        expected_ids = expected_ids or []
        missing = any(work_id not in index or req not in _ids(_origin(index[work_id][1]).get("requirements"))
                      for work_id in expected_ids)
        if entry is None:
            warnings.append(f"{req}: no PLAN traceability row; implementation unknown")
        if missing:
            warnings.append(f"{req}: PLAN references missing or nonreciprocal WORK; implementation unknown")
        linked = [(work_id, index[work_id][1]) for work_id in expected_ids if work_id in index]
        actual_work = [(work_id, item) for work_id, item in linked if item.get("status") != "transferred"]
        # A malformed plan must not silently count unlisted WORK as completed.
        unlisted = sorted(
            work_id for work_id, (_, item) in index.items()
            if req in _ids(_origin(item).get("requirements")) and work_id not in expected_ids
        )
        if unlisted:
            warnings.append(f"{req}: unlisted WORK origin in PLAN: {', '.join(unlisted)}")
        status = _work_status(linked, disposition, missing or bool(unlisted) or entry is None)
        all_acceptance = requirements[req]
        covered = {
            ac for _, item in actual_work
            if req in _ids(_origin(item).get("requirements"))
            for ac in _ids(_origin(item).get("acceptance_criteria"))
        }
        uncovered = sorted(all_acceptance - covered)
        if status == "implemented" and uncovered:
            status = "partial"
        tech = _related_decisions(records, req, "technical")
        comparison, kinds, completeness = _difference(actual_work, req, tech, source_valid, valid_comparisons)
        decision, tech_ids, policy_ids = _approval(req, records, linked, unresolved)
        if any(policy.record_errors(r) for r in _related_decisions(records, req, "policy")):
            decision = "pending"
        all_work = []
        for work_id, item in linked:
            work_path = index[work_id][0]
            record = {
                "id": work_id,
                "status": item.get("status"),
                "phase_status": _phase_status(domain, state, work_path),
                "commit": ((item.get("evidence") or {}).get("commit") if isinstance(item.get("evidence"), dict) else None),
                "review": item.get("review", {}).get("status") if isinstance(item.get("review"), dict) else None,
            }
            all_work.append(record)
        # Pass manifest paths separately; never mutate the caller's WORK dictionaries.
        annotated = [
            (work_id, {**item, "__manifest_path__": index[work_id][0]}) for work_id, item in actual_work
        ]
        verification = _verification(
            domain, state, annotated, root, head_sha, review_satisfied,
            not uncovered, status,
        )
        if status == "implemented" and verification == "stale":
            comparison = "unknown"
            completeness = "unknown"
        if disposition in SCOPE_CLOSED:
            verification = "not_run"
            comparison = "unknown"
        output.append({
            "id": req, "title": titles.get(req, ""), "scope": disposition,
            "implementation": status, "difference": comparison, "comparison_kinds": kinds,
            "comparison_completeness": completeness, "decision": decision,
            "verification": verification, "acceptance_ids": sorted(all_acceptance),
            "unmapped_acceptance_ids": uncovered, "source_refs": source_refs.get(req, []),
            "plan": entry or None, "work_ids": expected_ids, "works": all_work,
            "technical_decisions": tech_ids, "policy_decisions": policy_ids,
            "blocking_decisions": sorted({d for _, item in linked for d in _ids(item.get("decision_dependencies")) if d in unresolved}),
            "unlisted_work_ids": unlisted,
        })
    # A single requirement contributes exactly once per axis, regardless of WORK count.
    axes = ("implementation", "difference", "decision", "verification")
    counts = {axis: dict(sorted(Counter(row[axis] for row in output).items())) for axis in axes}
    in_scope = [row for row in output if row["scope"] not in SCOPE_CLOSED]
    original_without_prd: list[str] = []
    original = domain / "sources/v1/original.md"
    if source_valid and original.is_file():
        original_without_prd = sorted(set(traceability._requirements(
            original.read_text(encoding="utf-8-sig"))[0]) - set(requirements))
    unmapped_acceptance = {
        row["id"]: row["unmapped_acceptance_ids"] for row in output
        if row["unmapped_acceptance_ids"]
    }
    gaps = {
        "original_without_prd": original_without_prd,
        "prd_without_plan": sorted(set(requirements) - set(plan)),
        "work_without_prd": sorted({req for _, item in index.values()
                                    for req in _ids(_origin(item).get("requirements")) if req not in requirements}),
        "unmapped_acceptance": unmapped_acceptance,
        "unlisted_work": {row["id"]: row["unlisted_work_ids"] for row in output
                          if row["unlisted_work_ids"]},
    }
    return {
        "schema_version": 1, "domain": domain.name, "head_sha": head_sha,
        "source_revisions": source_versions,
        "summary": {"total": len(output), "in_scope": len(in_scope), "implemented": sum(
            row["implementation"] == "implemented" for row in in_scope), "by_axis": counts},
        "requirements": output, "gaps": gaps,
        "diagnostics": {"errors": sorted(set(errors)), "warnings": sorted(set(warnings))},
    }
