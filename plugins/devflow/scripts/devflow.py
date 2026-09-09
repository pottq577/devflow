#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("DevFlow requires PyYAML. Install with: python3 -m pip install PyYAML", file=sys.stderr)
    raise SystemExit(2)

PROTOCOL_VERSION = "1.4.0"
HIGH_RISK = {"high", "critical"}
REQ_PATTERN = re.compile(r"\b(?:REQ|RULE|AC|IDEM|SEC|NFR|DEC)-[A-Z0-9-]+\b", re.I)
PROTOCOL_VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")
MARKDOWN_SECTION_ANCHORS = {
    "PRD.md": ("4. Requirements",),
    "PLAN.md": (
        "Metadata",
        "Repository findings",
        "Architecture / implementation strategy",
        "Requirement traceability",
        "Phase graph",
        "Verification strategy",
    ),
    "PRD.audit-remediation.md": (
        "Audit target",
        "User-verified flows",
        "In scope",
        "Out of scope",
        "Authoritative requirements and policies",
        "Success criteria",
        "Open decisions",
    ),
    "PLAN.audit-remediation.md": (
        "Metadata",
        "Repository reconnaissance",
        "Audit axes",
        "Evidence plan",
        "Finding disposition strategy",
        "Remediation topology",
        "Closure criteria",
    ),
}

PROMPT_PROTOCOLS = {
    "plan": ["authority", "lifecycle", "work-item-contract", "decision-policy"],
    "run": ["authority", "work-item-contract", "risk-policy"],
    "audit": ["authority", "audit-core", "work-item-contract", "risk-policy", "decision-policy"],
}


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_git(args: list[str], cwd: Path, check: bool = False) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_ok(args: list[str], cwd: Path) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def repo_root() -> Path:
    cwd = Path.cwd().resolve()
    root = run_git(["rev-parse", "--show-toplevel"], cwd)
    return Path(root).resolve() if root else cwd


def load_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    return default if data is None else data


def load_schema(name: str) -> dict[str, Any]:
    path = plugin_root() / "core" / "schemas" / f"{name}.schema.yaml"
    data = load_yaml(path, {}) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid DevFlow schema: {path}")
    return data


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys. `yaml.safe_load` silently keeps the
    last value, so a second `phases:` or `items:` block in a hand-edited STATE or WORK file would
    discard the first without warning. Every DevFlow YAML read goes through here."""


def construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key: {key}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def parse_audit_text(text: str, source: str) -> dict[str, Any]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError(f"Audit file must start with YAML front matter: {source}")
    end = next((index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValueError(f"Audit YAML front matter is not closed: {source}")
    try:
        metadata = yaml.load("".join(lines[1:end]), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid audit YAML front matter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Audit YAML front matter must be a mapping")
    return metadata


def parse_audit_metadata(path: Path) -> dict[str, Any]:
    return parse_audit_text(path.read_text(encoding="utf-8"), str(path))


def load_required_audit_schema(name: str) -> dict[str, Any]:
    schema = load_schema(name)
    if not schema:
        raise ValueError(f"Required {name} schema is missing or empty")
    return schema


def nested_schema_value(schema: dict[str, Any], dotted_path: str) -> Any:
    value: Any = schema
    for segment in dotted_path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def schema_node_errors(
    node: Any,
    path: str,
    references: dict[str, dict[str, Any]],
    discovered_references: set[str],
) -> list[str]:
    if not isinstance(node, dict):
        return [f"{path} must be a mapping"]
    if "$ref" in node:
        reference = node.get("$ref")
        if not isinstance(reference, str) or not reference.strip():
            return [f"{path}.$ref must be a nonblank string"]
        discovered_references.add(reference)
        return [] if reference in references else [f"{path} references unavailable schema {reference}"]

    errors: list[str] = []
    schema_type = node.get("type")
    if schema_type not in {"mapping", "list", "string"}:
        errors.append(f"{path}.type is invalid")
    if "allowed" in node:
        allowed = node["allowed"]
        if not isinstance(allowed, list) or not allowed or any(not isinstance(value, str) or not value.strip() for value in allowed):
            errors.append(f"{path}.allowed must be a non-empty list of nonblank strings")
        elif len(set(allowed)) != len(allowed):
            errors.append(f"{path}.allowed contains duplicate values")
    if schema_type == "mapping":
        required = node.get("required")
        properties = node.get("properties")
        if not isinstance(required, list) or not required or any(not isinstance(value, str) or not value.strip() for value in required):
            errors.append(f"{path}.required must be a non-empty list of nonblank strings")
        if not isinstance(properties, dict) or not properties:
            errors.append(f"{path}.properties must be a non-empty mapping")
            return errors
        if isinstance(required, list):
            missing = sorted(str(field) for field in required if field not in properties)
            if missing:
                errors.append(f"{path}.required fields lack properties: {', '.join(missing)}")
        for field, child in properties.items():
            errors.extend(schema_node_errors(child, f"{path}.properties.{field}", references, discovered_references))
    elif schema_type == "list":
        if not isinstance(node.get("items"), dict):
            errors.append(f"{path}.items must be a mapping")
        else:
            errors.extend(schema_node_errors(node["items"], f"{path}.items", references, discovered_references))
    return errors


def audit_schema_contract_errors(
    name: str,
    schema: dict[str, Any],
    references: dict[str, dict[str, Any]],
    work_kinds: set[str],
) -> list[str]:
    anchors = {
        "audit": {
            "root_keys": {"schema", "type", "contract", "required", "properties", "verdict"},
            "contract_keys": {"required_allowed", "references", "rubric"},
            "required_allowed": {
                "properties.scope",
                "properties.mode",
                "properties.verdict",
                "properties.closure.items.properties.outcome",
            },
            "references": {"finding"},
            "rubric": "verdict",
        },
        "finding": {
            "root_keys": {"schema", "type", "contract", "required", "properties", "classification"},
            "contract_keys": {"required_allowed", "required_fields", "references"},
            "required_allowed": {
                "properties.classification",
                "properties.severity",
                "properties.disposition.properties.action",
            },
            "required_fields": {"severity_reason"},
            "references": set(),
            "rubric": None,
        },
    }
    anchor = anchors[name]
    errors: list[str] = []
    missing_root_keys = sorted(anchor["root_keys"] - set(schema))
    if missing_root_keys:
        errors.append(f"missing bootstrap keys: {', '.join(missing_root_keys)}")
    expected_identifier = f"devflow-{name}-v1"
    if schema.get("schema") != expected_identifier:
        errors.append(f"schema identifier must be {expected_identifier}")
    identifier_const = nested_schema_value(schema, "properties.schema.const")
    if identifier_const is not None and identifier_const != expected_identifier:
        errors.append(f"properties.schema.const must be {expected_identifier}")

    contract = schema.get("contract")
    if not isinstance(contract, dict):
        return errors + ["contract must be a mapping"]
    missing_contract_keys = sorted(anchor["contract_keys"] - set(contract))
    if missing_contract_keys:
        errors.append(f"contract missing bootstrap keys: {', '.join(missing_contract_keys)}")
    required_allowed = contract.get("required_allowed")
    if (
        not isinstance(required_allowed, list)
        or not required_allowed
        or any(not isinstance(value, str) or not value.strip() for value in required_allowed)
    ):
        errors.append("contract.required_allowed must be a non-empty list of nonblank strings")
        required_allowed = []
    elif set(required_allowed) != anchor["required_allowed"]:
        errors.append("contract.required_allowed does not match the required enum paths")
    for dotted_path in required_allowed:
        node = nested_schema_value(schema, str(dotted_path))
        allowed = node.get("allowed") if isinstance(node, dict) else None
        if not isinstance(allowed, list) or not allowed:
            errors.append(f"{dotted_path}.allowed is required")

    expected_required_fields = anchor.get("required_fields", set())
    if expected_required_fields:
        required_fields = contract.get("required_fields")
        if not isinstance(required_fields, list) or set(required_fields) != expected_required_fields:
            errors.append("contract.required_fields must protect severity_reason")
        root_required = schema.get("required")
        properties = schema.get("properties")
        for field in expected_required_fields:
            if not isinstance(root_required, list) or field not in root_required:
                errors.append(f"required must include {field}")
            if not isinstance(properties, dict) or field not in properties:
                errors.append(f"properties must include {field}")
            elif not isinstance(properties[field], dict) or properties[field].get("type") != "string":
                errors.append(f"properties.{field} must remain a nonblank string")

    declared_references = contract.get("references")
    if not isinstance(declared_references, list) or any(not isinstance(value, str) or not value.strip() for value in declared_references):
        errors.append("contract.references must be a list of nonblank strings")
        declared_references = []
    elif set(declared_references) != anchor["references"]:
        errors.append("contract.references does not match the required schema references")
    discovered_references: set[str] = set()
    errors.extend(schema_node_errors(schema, name, references, discovered_references))
    if set(declared_references) != discovered_references:
        errors.append("contract.references does not match schema references")

    rubric_name = contract.get("rubric")
    if rubric_name != anchor["rubric"]:
        errors.append(f"contract.rubric must be {anchor['rubric']!r}")
    if rubric_name is not None:
        rubric = schema.get(str(rubric_name))
        allowed = nested_schema_value(schema, f"properties.{rubric_name}.allowed")
        if not isinstance(rubric, dict) or not isinstance(allowed, list) or set(rubric) != set(allowed):
            errors.append(f"{rubric_name} rubric must cover every allowed value exactly")
        elif any(
            not isinstance(rules, dict)
            or not rules
            or any(not isinstance(values, list) or not values for values in rules.values())
            for rules in rubric.values()
        ):
            errors.append(f"{rubric_name} rubric rules must be non-empty collections")
    if name == "finding":
        classifications = nested_schema_value(schema, "properties.classification.allowed")
        dispositions = nested_schema_value(schema, "classification.disposition")
        allowed_actions = nested_schema_value(schema, "properties.disposition.properties.action.allowed")
        if not isinstance(classifications, list) or not isinstance(dispositions, dict) or set(dispositions) != set(classifications):
            errors.append("classification.disposition must cover every allowed classification exactly")
        elif not isinstance(allowed_actions, list):
            errors.append("properties.disposition.properties.action.allowed is required")
        elif any(
            not isinstance(rule, dict)
            or rule.get("action") not in allowed_actions
            or rule.get("work_ids") not in {"required", "empty"}
            or rule.get("decision_ids") not in {"required", "empty"}
            or (
                rule.get("work_ids") == "required"
                and (not isinstance(rule.get("work_kind"), str) or rule.get("work_kind") not in work_kinds)
            )
            for rule in dispositions.values()
        ):
            errors.append("classification.disposition rules are invalid, including required work_kind values")
    return errors


def load_audit_schemas() -> tuple[dict[str, Any], dict[str, Any]]:
    audit_schema = load_required_audit_schema("audit")
    finding_schema = load_required_audit_schema("finding")
    work_schema = load_required_audit_schema("work")
    allowed_work_kinds = nested_schema_value(work_schema, "kind.allowed")
    if (
        not isinstance(allowed_work_kinds, list)
        or not allowed_work_kinds
        or any(not isinstance(value, str) or not value.strip() for value in allowed_work_kinds)
    ):
        raise ValueError("Required work schema is invalid: kind.allowed must be a non-empty list of nonblank strings")
    work_kinds = set(allowed_work_kinds)
    references = {"finding": finding_schema}
    for name, schema in [("audit", audit_schema), ("finding", finding_schema)]:
        errors = audit_schema_contract_errors(name, schema, references, work_kinds)
        if errors:
            raise ValueError(f"Required {name} schema is invalid: {'; '.join(errors)}")
    return audit_schema, finding_schema


def canonical_audit_has_mode(
    root: Path,
    domain: str,
    state: dict[str, Any],
    scope: str,
    mode: str,
    phase: str | None,
    work_item: str | None,
) -> bool:
    try:
        path = canonical_audit_path(root, domain, state, scope, phase, work_item)
        if not path.exists():
            return False
        metadata = parse_audit_metadata(path)
        audit_schema, finding_schema = load_audit_schemas()
        schema_errors = validate_schema_value(
            metadata,
            audit_schema,
            "canonical audit",
            {"finding": finding_schema},
        )
        return (
            not schema_errors
            and not audit_finding_id_errors(metadata.get("findings", []) or [])
            and metadata.get("scope") == scope
            and metadata.get("mode") == mode
            and metadata.get("baseline_sha") == state.get("baseline_sha")
            and metadata.get("target_sha") == current_sha(root)
        )
    except (OSError, UnicodeError, ValueError, KeyError):
        return False


def audit_scope_recovery_command(domain: str, scope: str, phase: str | None, work_item: str | None) -> str:
    """The command that returns a scope to a fresh initial audit, named in a closure refusal."""
    if scope == "plan":
        return f"devflow plan-review set {domain} pending"
    if scope == "phase":
        return f"devflow phase set {domain} {phase_key(phase) if phase is not None else '<phase>'} audit"
    if scope == "work":
        return f"devflow work review {domain} {work_item or '<WORK-ID>'} pending"
    return f"devflow integration set {domain} audit"


def closure_without_provenance_error(domain: str, scope: str, phase: str | None, work_item: str | None) -> str:
    """One message, used by both the apply and validate paths, spelling out the whole recovery: a
    project that predates machine-owned provenance, or whose STATE was reset, records no prior
    finding set for this scope, so the closure cannot be checked and the initial audit must be
    re-applied first."""
    recovery = audit_scope_recovery_command(domain, scope, phase, work_item)
    return (
        f"Closure audit for {scope} has no recorded initial-audit provenance. "
        f"Recover: run '{recovery}', re-render and re-apply the scope's initial audit "
        f"(devflow render audit ... --mode initial, then devflow audit apply ... --mode initial), "
        f"then retry this closure."
    )


def recorded_audit_provenance(
    root: Path,
    domain: str,
    state: dict[str, Any],
    scope: str,
    phase: str | None,
    work_item: str | None,
    *,
    work_docs: dict[Path, dict[str, Any]] | None = None,
) -> dict[str, str] | None:
    """The {finding_id: severity} recorded by `audit apply` when the audit for this scope was
    applied, or None when no audit has been applied there. Reads STATE and WORK only, never Git."""
    record: Any = None
    if scope == "plan":
        review = state.get("plan_review")
        record = review.get("audit_provenance") if isinstance(review, dict) else None
    elif scope == "phase":
        key = phase_key(phase) if phase is not None else None
        entry = normalized_phases(state).get(key) if key is not None else None
        record = entry.get("audit_provenance") if isinstance(entry, dict) else None
    elif scope == "integration":
        integration = state.get("integration")
        record = integration.get("audit_provenance") if isinstance(integration, dict) else None
    elif scope == "work":
        if work_docs is None:
            work_docs, _, _ = load_work_index(domain_dir(root, domain))
        for doc in work_docs.values():
            for item in doc.get("items", []) or []:
                if str(item.get("id")) == str(work_item):
                    review = item.get("review")
                    record = review.get("audit_provenance") if isinstance(review, dict) else None
    if not isinstance(record, dict):
        return None
    findings = record.get("findings")
    return {str(key): str(value) for key, value in findings.items()} if isinstance(findings, dict) else {}


def audit_provenance_findings(metadata: dict[str, Any]) -> dict[str, str]:
    """The provenance record `audit apply` writes onto the audited scope's machine-owned metadata."""
    return {str(finding["id"]): str(finding["severity"]) for finding in metadata.get("findings", []) or []}


def audit_provenance_errors(label: str, record: Any) -> list[str]:
    """Structural check for a stored audit_provenance record. An invalid record is never normalized away."""
    if record is None:
        return []
    if not isinstance(record, dict):
        return [f"{label}.audit_provenance must be a mapping"]
    findings = record.get("findings")
    if not isinstance(findings, dict):
        return [f"{label}.audit_provenance.findings must be a mapping of finding id to severity"]
    errors: list[str] = []
    for key, value in findings.items():
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{label}.audit_provenance.findings has a blank finding id")
        if value not in SEVERITY_RANK:
            errors.append(f"{label}.audit_provenance.findings[{key}] has an invalid severity: {value!r}")
    return errors


def validate_schema_value(
    value: Any,
    spec: dict[str, Any],
    path: str,
    references: dict[str, dict[str, Any]],
) -> list[str]:
    if "$ref" in spec:
        target = references.get(str(spec["$ref"]))
        return [f"{path}: unknown schema reference {spec['$ref']}"] if target is None else validate_schema_value(value, target, path, references)

    errors: list[str] = []
    expected_type = spec.get("type")
    types = {"mapping": dict, "list": list, "string": str}
    if expected_type in types and not isinstance(value, types[expected_type]):
        return [f"{path} must be a {expected_type}"]
    if isinstance(value, str) and not value.strip():
        errors.append(f"{path} must not be blank")
    if "const" in spec and value != spec["const"]:
        errors.append(f"{path} must be {spec['const']!r}")
    if "allowed" in spec and value not in spec["allowed"]:
        errors.append(f"{path} must be one of: {', '.join(str(item) for item in spec['allowed'])}")

    if isinstance(value, dict):
        for field in spec.get("required", []) or []:
            if field not in value:
                errors.append(f"{path} missing required field: {field}")
        for field, child in (spec.get("properties", {}) or {}).items():
            if field in value:
                errors.extend(validate_schema_value(value[field], child, f"{path}.{field}", references))
    elif isinstance(value, list):
        if len(value) < int(spec.get("min_items", 0)):
            errors.append(f"{path} must contain at least {spec['min_items']} item(s)")
        item_spec = spec.get("items")
        if isinstance(item_spec, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema_value(item, item_spec, f"{path}[{index}]", references))
    return errors


def work_schema_contract_errors(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if schema.get("schema") != "devflow-work-v2":
        errors.append("schema identifier must be devflow-work-v2")
    version = schema.get("version")
    if not isinstance(version, dict):
        errors.append("version must be a mapping")
    else:
        if type(version.get("current")) is not int or version.get("current") != 2:
            errors.append("version.current must be integer 2")
        supported = version.get("supported")
        if (
            not isinstance(supported, list)
            or any(type(value) is not int for value in supported)
            or len(supported) != 2
            or set(supported) != {1, 2}
        ):
            errors.append("version.supported must contain exactly integer versions 1 and 2")
    version_2 = schema.get("version_2")
    if not isinstance(version_2, dict) or not all(
        isinstance(version_2.get(field), dict) for field in ["acceptance", "verification_command"]
    ):
        errors.append("version_2 must define acceptance and verification_command mappings")
    return errors


def configure_work_schema() -> None:
    global WORK_SCHEMA, WORK_REQUIRED_ITEM_FIELDS, WORK_VERSIONS, WORK_STATUSES
    global TERMINAL_STATUSES, KINDS, RISK_LEVELS, REVIEW_STATUSES
    global FINDING_TRACEABILITY_KINDS, AGGREGATION_REASON_THRESHOLD

    schema = load_schema("work")
    errors = work_schema_contract_errors(schema)
    if errors:
        raise ValueError(f"Required WORK schema is invalid: {'; '.join(errors)}")
    try:
        WORK_REQUIRED_ITEM_FIELDS = schema["required_item_fields"]
        WORK_VERSIONS = set(schema["version"]["supported"])
        WORK_STATUSES = set(schema["status"]["allowed"])
        TERMINAL_STATUSES = set(schema["terminal"])
        KINDS = set(schema["kind"]["allowed"])
        RISK_LEVELS = set(schema["risk_level"]["allowed"])
        REVIEW_STATUSES = set(schema.get("review_status", {}).get("allowed", ["skipped", "pending", "remediation", "blocked", "verified"]))
        FINDING_TRACEABILITY_KINDS = set(schema["finding_traceability"]["required_for_kinds"])
        AGGREGATION_REASON_THRESHOLD = int(schema["finding_traceability"]["aggregation_reason_required_when_findings_at_least"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Required WORK schema is invalid: {exc}") from exc
    WORK_SCHEMA = schema


STATE_SCHEMA = load_schema("state")
STATE_REQUIRED_FIELDS = STATE_SCHEMA["required"]
FINDING_SCHEMA = load_schema("finding")
# Severity order is highest-first, taken from the finding schema so it stays the trust anchor.
SEVERITY_ORDER: list[str] = list(FINDING_SCHEMA["severity"]["allowed"])
SEVERITY_RANK: dict[str, int] = {name: index for index, name in enumerate(SEVERITY_ORDER)}
WORKFLOW_TYPES = set(STATE_SCHEMA["workflow_type"]["allowed"])
PHASE_ENTRY_REQUIRED_FIELDS = STATE_SCHEMA["phase_entry"]["required"]
PROJECT_STATUSES = set(STATE_SCHEMA["project_status"]["allowed"])
PHASE_STATUSES = set(STATE_SCHEMA["phase_status"]["allowed"])
INTEGRATION_STATUSES = set(STATE_SCHEMA["integration_status"]["allowed"])
PLAN_REVIEW_STATUSES = set(STATE_SCHEMA["plan_review_status"]["allowed"])
WORK_SCHEMA: dict[str, Any] = {}
WORK_REQUIRED_ITEM_FIELDS: list[str] = []
WORK_VERSIONS: set[int] = set()
WORK_STATUSES: set[str] = set()
TERMINAL_STATUSES: set[str] = set()
KINDS: set[str] = set()
RISK_LEVELS: set[str] = set()
REVIEW_STATUSES: set[str] = set()
FINDING_TRACEABILITY_KINDS: set[str] = set()
AGGREGATION_REASON_THRESHOLD = 0


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        os.replace(temp_path, path)
    except Exception:
        if temp_path and temp_path.exists():
            temp_path.unlink()
        raise


def dump_yaml(path: Path, data: Any) -> None:
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000))


def dump_yaml_if_changed(path: Path, data: Any) -> bool:
    """Write only when the rendered YAML differs, so read-only commands stay side-effect free."""
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    atomic_write_text(path, rendered)
    return True


def commit_yaml_transaction(documents: dict[Path, Any]) -> None:
    rendered = {
        path: yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
        for path, data in documents.items()
    }
    backups: dict[Path, Path | None] = {}
    try:
        for path in documents:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                backups[path] = None
                continue
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as backup:
                backup.write(path.read_bytes())
                backups[path] = Path(backup.name)
    except Exception:
        for backup_path in backups.values():
            if backup_path is not None:
                backup_path.unlink(missing_ok=True)
        raise
    try:
        for path, content in rendered.items():
            atomic_write_text(path, content)
    except Exception as commit_error:
        rollback_errors = []
        for path in reversed(documents):
            backup_path = backups.get(path)
            try:
                if backup_path is None:
                    path.unlink(missing_ok=True)
                elif backup_path.exists():
                    os.replace(backup_path, path)
            except Exception as exc:
                rollback_errors.append(f"{path}: {exc}")
        for backup_path in backups.values():
            if backup_path is not None:
                backup_path.unlink(missing_ok=True)
        if rollback_errors:
            raise RuntimeError("Audit apply rollback failed: " + "; ".join(rollback_errors)) from commit_error
        raise commit_error
    for backup_path in backups.values():
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)


def commit_lifecycle_mutation(
    root: Path,
    domain: str,
    state: dict[str, Any],
    work_overrides: dict[Path, dict[str, Any]] | None = None,
) -> None:
    """Project derived STATE (and any changed WORK) on the prospective documents, then commit them
    atomically, mirroring audit_apply(). project_state() raises on structurally invalid input
    BEFORE any file is written, so a command that reports failure has changed nothing. This is
    process-local failure rollback, not crash recovery or concurrent-writer isolation."""
    project_state(root, domain, state, work_overrides)
    documents: dict[Path, Any] = dict(work_overrides or {})
    documents[state_path(root, domain)] = state
    commit_yaml_transaction(documents)


def has_nonblank_string(values: Any) -> bool:
    """True when `values` is a list holding at least one string with non-whitespace content."""
    return isinstance(values, list) and any(
        isinstance(value, str) and bool(value.strip()) for value in values
    )


def work_document_version(doc: dict[str, Any]) -> int:
    version = doc.get("version", 1)
    return version if type(version) is int else 0


def normalized_acceptance(item: dict[str, Any], version: int) -> list[dict[str, Any]]:
    values = item.get("acceptance")
    if not isinstance(values, list):
        return []
    if version == 1:
        return [{"id": None, "criterion": value} for value in values]
    return [value for value in values if isinstance(value, dict)]


def normalized_verification_commands(item: dict[str, Any], version: int) -> list[dict[str, Any]]:
    verification = item.get("verification")
    values = verification.get("commands") if isinstance(verification, dict) else None
    if not isinstance(values, list):
        return []
    if version == 1:
        return [{"id": None, "command": value, "covers": []} for value in values]
    return [value for value in values if isinstance(value, dict)]


def runtime_config(root: Path) -> dict[str, Any]:
    cfg_path = root / ".devflow" / "config.yaml"
    cfg = load_yaml(cfg_path, {}) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"Runtime config must be a mapping: {cfg_path}")
    cfg.setdefault("domains_root", "docs/domains")
    cfg.setdefault("protocol_version", PROTOCOL_VERSION)
    return cfg


def parsed_protocol_version(value: Any) -> tuple[int, int, int] | None:
    match = PROTOCOL_VERSION_PATTERN.fullmatch(str(value or ""))
    return tuple(map(int, match.groups())) if match else None


def config_protocol_diagnostics(root: Path) -> tuple[list[str], list[str], bool]:
    config_path = root / ".devflow" / "config.yaml"
    if not config_path.exists():
        return [], [], False
    value = runtime_config(root).get("protocol_version")
    version = parsed_protocol_version(value)
    runtime_version = parsed_protocol_version(PROTOCOL_VERSION)
    if version is None:
        return [f"Invalid config protocol_version: {value or '<empty>'}"], [], False
    if version[0] != runtime_version[0]:
        return [f"Unsupported config protocol_version {value}: this runtime implements {PROTOCOL_VERSION}"], [], False
    newer = version[1:] > runtime_version[1:]
    warnings = [f"Config protocol_version {value} is newer than this runtime's {PROTOCOL_VERSION}"] if newer else []
    return [], warnings, newer


def reported_protocol_versions(root: Path, state: dict[str, Any]) -> dict[str, str]:
    config_version = str(runtime_config(root).get("protocol_version") or PROTOCOL_VERSION)
    state_version = str(state.get("protocol_version") or config_version)
    return {
        "runtime": PROTOCOL_VERSION,
        "config": config_version,
        "state": state_version,
        "effective": state_version,
    }


def domain_dir(root: Path, domain: str) -> Path:
    # Every command routes through here, so one containment check covers all call sites. A domain
    # argument with `..` segments (or an absolute path) otherwise places artifacts outside the
    # configured root, where nothing else in the repository looks for them.
    domains_root_rel = runtime_config(root)["domains_root"]
    base = root / domains_root_rel
    try:
        (base / domain).resolve().relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"Domain escapes domains_root: {domain!r} resolves outside {domains_root_rel}") from exc
    return base / domain


def state_path(root: Path, domain: str) -> Path:
    return domain_dir(root, domain) / "STATE.yaml"


def current_sha(root: Path) -> str | None:
    value = run_git(["rev-parse", "HEAD"], root)
    return value or None


def short_sha(value: str | None) -> str:
    return value[:12] if value else "<none>"


def read_template(name: str) -> str:
    return (plugin_root() / "core" / "templates" / name).read_text(encoding="utf-8")


def read_protocol(name: str) -> str:
    return (plugin_root() / "core" / "protocol" / f"{name}.md").read_text(encoding="utf-8")


def resolve_extension(root: Path, state: dict[str, Any]) -> Path:
    """Project-local extension wins, then a bundled named extension, then default."""
    name = state.get("extension") or runtime_config(root).get("extension") or "default"
    for candidate in [
        root / ".devflow" / "extensions" / f"{name}.md",
        plugin_root() / "core" / "extensions" / f"{name}.md",
        plugin_root() / "core" / "extensions" / "default.md",
    ]:
        if candidate.exists():
            return candidate
    return plugin_root() / "core" / "extensions" / "default.md"


def ensure_runtime(root: Path) -> None:
    runtime = root / ".devflow"
    runtime.mkdir(parents=True, exist_ok=True)
    cfg = runtime / "config.yaml"
    if not cfg.exists():
        dump_yaml(cfg, {"protocol_version": PROTOCOL_VERSION, "domains_root": "docs/domains", "extension": "default"})


def phase_key(value: Any) -> str:
    s = str(value)
    return s.zfill(2) if s.isdigit() else s


def normalized_phases(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """STATE phase keys are authored by hand, so normalize before every lookup."""
    out: dict[str, dict[str, Any]] = {}
    for key, value in (state.get("phases", {}) or {}).items():
        out[phase_key(key)] = value or {}
    return out


def effective_workflow_type(state: dict[str, Any]) -> str:
    """Return the legacy-compatible workflow type without mutating STATE."""
    return str(state["workflow_type"]) if "workflow_type" in state else "delivery"


def config_protocol_floor(root: Path) -> tuple[int, int, int] | None:
    """The project's recorded config protocol version, only when .devflow/config.yaml exists on
    disk. Unlike runtime_config(), this does not fabricate the runtime version for a config-less
    project, so a project with no config keeps the legacy verified-transition path."""
    if not (root / ".devflow" / "config.yaml").exists():
        return None
    return parsed_protocol_version(runtime_config(root).get("protocol_version"))


def requires_audit_apply(state: dict[str, Any], root: Path | None = None) -> bool:
    """The 1.3 audit-apply gate. It fires from the higher of the STATE protocol version and the
    project config's, so a STATE downgrade cannot disable the gate that init recorded."""
    candidates = [
        version
        for version in (parsed_protocol_version(state.get("protocol_version")), config_protocol_floor(root) if root is not None else None)
        if version is not None
    ]
    return bool(candidates and max(candidates) >= (1, 3, 0))


def raw_phase_key(state: dict[str, Any], key: str) -> str | None:
    for raw in (state.get("phases", {}) or {}):
        if phase_key(raw) == key:
            return raw
    return None


def init_domain(args: argparse.Namespace) -> int:
    root = repo_root()
    ensure_runtime(root)
    d = domain_dir(root, args.domain)
    workflow_type = args.workflow.replace("-", "_")
    d.mkdir(parents=True, exist_ok=True)
    (d / "work").mkdir(exist_ok=True)
    (d / "audits").mkdir(exist_ok=True)

    prd = d / "PRD.md"
    if args.prd:
        src = Path(args.prd).expanduser().resolve()
        if not src.exists():
            print(f"PRD source not found: {src}", file=sys.stderr)
            return 2
        if not prd.exists() or args.force:
            prd.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    elif not prd.exists():
        template = "PRD.audit-remediation.md" if workflow_type == "audit_remediation" else "PRD.md"
        prd.write_text(read_template(template), encoding="utf-8")

    templates = {
        "PLAN.md": "PLAN.audit-remediation.md" if workflow_type == "audit_remediation" else "PLAN.md",
        "DECISIONS.md": "DECISIONS.md",
        "PITFALLS.md": "PITFALLS.md",
    }
    for name, template in templates.items():
        target = d / name
        if not target.exists():
            target.write_text(read_template(template), encoding="utf-8")

    state = load_yaml(state_path(root, args.domain), {}) or {}
    state.setdefault("protocol_version", PROTOCOL_VERSION)
    state.setdefault("workflow_type", workflow_type)
    state["domain"] = args.domain
    state.setdefault("risk_profile", args.risk)
    state.setdefault("extension", args.extension)
    state.setdefault("project_status", "integration_audit" if workflow_type == "audit_remediation" else "planning")
    state.setdefault("baseline_sha", current_sha(root))
    state.setdefault("target_sha", current_sha(root))
    state.setdefault("active_phase", None)
    plan_review_required = workflow_type == "delivery" and args.risk in HIGH_RISK
    state.setdefault("plan_review", {"required": plan_review_required, "status": "pending" if plan_review_required else "skipped", "audit_file": "audits/plan.md"})
    state.setdefault("phases", {})
    state.setdefault("integration", {"status": "audit" if workflow_type == "audit_remediation" else "pending", "work_file": "work/integration.yaml", "audit_file": "audits/integration.md"})
    state.setdefault("unresolved_decisions", [])
    state.setdefault("next_action", {"role": "auditor", "command": "audit", "scope": "integration", "mode": "initial", "phase": None, "work_item": None} if workflow_type == "audit_remediation" else {"role": "architect", "command": "plan", "scope": "project", "phase": None, "work_item": None})
    dump_yaml(state_path(root, args.domain), state)
    print(f"Initialized DevFlow domain: {d.relative_to(root)}")
    print(f"workflow_type: {effective_workflow_type(state)}")
    print("runtime_config: .devflow/config.yaml")
    print(f"domains_root: {runtime_config(root)['domains_root']}")
    print(f"domain_dir: {d.relative_to(root)}")
    print(f"baseline_sha: {short_sha(state.get('baseline_sha'))}")
    print(f"extension: {resolve_extension(root, state)}")
    return 0


def work_files(d: Path) -> list[Path]:
    work = d / "work"
    return sorted(p for p in work.glob("*.yaml") if p.is_file()) if work.exists() else []


def index_work_docs(docs: dict[Path, dict[str, Any]]):
    index: dict[str, tuple[Path, dict[str, Any]]] = {}
    duplicates: list[str] = []
    for path, doc in docs.items():
        for item in doc.get("items", []) or []:
            item_id = str(item.get("id", ""))
            if item_id in index:
                duplicates.append(item_id)
            index[item_id] = (path, item)
    return docs, index, duplicates


def load_work_index(d: Path, overrides: dict[Path, dict[str, Any]] | None = None):
    docs = {path: load_yaml(path, {}) or {} for path in work_files(d)}
    if overrides:
        docs.update(overrides)
    return index_work_docs(docs)


def item_phase(path: Path, doc: dict[str, Any]) -> str:
    phase = doc.get("phase")
    if phase is not None:
        return phase_key(phase)
    m = re.search(r"phase[-_]?([0-9]+)", path.stem, re.I)
    return phase_key(m.group(1)) if m else "integration"


def effective_review(item: dict[str, Any]) -> dict[str, Any]:
    """Return policy-defaulted review metadata without changing legacy WORK YAML."""
    raw = item.get("review") if isinstance(item.get("review"), dict) else {}
    high_risk = (item.get("risk") or {}).get("level") in HIGH_RISK
    implemented = item.get("status") in {"done", "in_progress", "ready"}
    required = high_risk and implemented
    if not high_risk and isinstance(raw.get("required"), bool):
        required = raw["required"]
    elif high_risk and implemented and raw.get("required") is True:
        required = True
    status = raw.get("status")
    if status not in REVIEW_STATUSES or (high_risk and implemented and raw and raw.get("required") is not True) or (required and status == "skipped"):
        status = "pending" if required else "skipped"
    review = {
        "required": required,
        "status": status,
        "audit_file": raw.get("audit_file") or f"audits/work/{item.get('id')}.md",
        "remediation_work_ids": list(raw.get("remediation_work_ids") or []),
    }
    # Machine-owned closure provenance rides on the review dict; carry it through every rebuild.
    if isinstance(raw.get("audit_provenance"), dict):
        review["audit_provenance"] = raw["audit_provenance"]
    return review


def effective_plan_review(state: dict[str, Any]) -> dict[str, Any]:
    """Return the plan-review defaults without requiring legacy STATE migration."""
    raw = state.get("plan_review") if isinstance(state.get("plan_review"), dict) else {}
    review = {
        "required": bool(raw.get("required")),
        "status": raw.get("status") or ("pending" if raw.get("required") else "skipped"),
        "audit_file": raw.get("audit_file") or "audits/plan.md",
    }
    if "remediation_work_ids" in raw:
        review["remediation_work_ids"] = raw.get("remediation_work_ids")
    if isinstance(raw.get("audit_provenance"), dict):
        review["audit_provenance"] = raw["audit_provenance"]
    return review


def review_satisfied(item: dict[str, Any]) -> bool:
    review = effective_review(item)
    return not review["required"] or review["status"] == "verified"


def dependency_reaches(item_id: str, target_id: str, index: dict[str, tuple[Path, dict[str, Any]]]) -> bool:
    """True when target_id is reachable from item_id by following `dependencies` edges only."""
    target = str(target_id)
    seen: set[str] = set()
    stack = [str(item_id)]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        entry = index.get(current)
        if not entry:
            continue
        for dep in entry[1].get("dependencies", []) or []:
            dep_id = str(dep)
            if dep_id == target:
                return True
            stack.append(dep_id)
    return False


def remediation_completion_blockers(review: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> list[str]:
    """Reasons a registered remediation set is not yet closed, so `verified` may not proceed."""
    blockers: list[str] = []
    for remediation_id in review.get("remediation_work_ids", []) or []:
        entry = index.get(str(remediation_id))
        if not entry:
            blockers.append(f"remediation WORK {remediation_id} is missing")
            continue
        target = entry[1]
        if target.get("status") not in TERMINAL_STATUSES:
            blockers.append(f"remediation WORK {remediation_id} is not terminal")
        elif target.get("status") == "done" and not review_satisfied(target):
            blockers.append(f"remediation WORK {remediation_id} still requires review")
    return blockers


def deps_satisfied(item: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> bool:
    return not dependency_blockers(item, index)


def decision_satisfied(item: dict[str, Any], unresolved: set[str]) -> bool:
    return not decision_blockers(item, unresolved)


def dependency_blockers(item: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any]]]) -> list[str]:
    blockers = []
    for dep in item.get("dependencies", []) or []:
        dependency_id = str(dep)
        target = index.get(dependency_id)
        if not target:
            blockers.append(f"dependency {dependency_id} does not exist")
            continue
        dependency = target[1]
        if dependency.get("status") not in TERMINAL_STATUSES:
            blockers.append(f"dependency {dependency_id} is not terminal")
        elif dependency.get("status") == "done" and not review_satisfied(dependency):
            blockers.append(f"dependency {dependency_id} requires review before dependent WORK may proceed")
    return blockers


def decision_blockers(item: dict[str, Any], unresolved: set[str]) -> list[str]:
    return [f"unresolved decision {decision}" for decision in item.get("decision_dependencies", []) or [] if str(decision) in unresolved]


def work_start_errors(
    state: dict[str, Any],
    d: Path,
    path: Path,
    doc: dict[str, Any],
    item: dict[str, Any],
    index: dict[str, tuple[Path, dict[str, Any]]],
) -> list[str]:
    errors = []
    if item.get("status") != "ready":
        errors.append(f"status must be ready, not {item.get('status')}")
    errors.extend(dependency_blockers(item, index))
    decision_errors, open_decisions = decision_state_errors(state, d)
    errors.extend(decision_errors)
    unresolved = {str(value) for value in state.get("unresolved_decisions", []) or []} | open_decisions
    errors.extend(decision_blockers(item, unresolved))

    phase = item_phase(path, doc)
    phases = normalized_phases(state)
    if phase == "integration":
        unverified = sorted(key for key, entry in phases.items() if entry.get("status") != "verified")
        if unverified:
            errors.append(f"project phases are not verified: {', '.join(unverified)}")
    elif phases.get(phase, {}).get("status") == "verified":
        errors.append(f"phase {phase} is already verified")

    plan_review = effective_plan_review(state)
    plan_remediation = (
        plan_review.get("status") in {"pending", "remediation"}
        and isinstance(plan_review.get("remediation_work_ids"), list)
        and str(item.get("id")) in plan_review.get("remediation_work_ids", [])
    )
    if plan_review.get("required") and plan_review.get("status") != "verified" and not plan_remediation:
        errors.append("required plan review is pending")
    return errors


def phase_items(d: Path, docs: dict[Path, dict[str, Any]], key: str, phase: dict[str, Any]) -> list[dict[str, Any]]:
    work_path = d / phase.get("work_file", f"work/phase-{key}.yaml")
    doc = docs.get(work_path) or load_yaml(work_path, {}) or {}
    return list(doc.get("items", []) or [])


def phase_verify_errors(root: Path, domain: str, state: dict[str, Any], phase_key_value: str, docs: dict[Path, dict[str, Any]]) -> list[str]:
    phases = normalized_phases(state)
    phase = phases.get(phase_key_value)
    if phase is None:
        return [f"phase {phase_key_value} does not exist"]

    d = domain_dir(root, domain)
    items = phase_items(d, docs, phase_key_value, phase)
    errors = []
    if not items:
        errors.append(f"phase {phase_key_value} has no WORK items")
    open_items = [str(item.get("id")) for item in items if item.get("status") not in TERMINAL_STATUSES]
    if open_items:
        errors.append(f"open WORK remains: {', '.join(open_items)}")
    blocked_items = [str(item.get("id")) for item in items if item.get("status") == "blocked"]
    if blocked_items:
        errors.append(f"blocked WORK remains: {', '.join(blocked_items)}")
    pending_reviews = [str(item.get("id")) for item in items if item.get("status") == "done" and (item.get("risk") or {}).get("level") in HIGH_RISK and not review_satisfied(item)]
    if pending_reviews:
        errors.append(f"high-risk WORK requires review: {', '.join(pending_reviews)}")
    unresolved = {str(value) for value in state.get("unresolved_decisions", []) or []}
    decisions = sorted({str(decision) for item in items for decision in (item.get("decision_dependencies", []) or []) if str(decision) in unresolved})
    if decisions:
        errors.append(f"unresolved decisions: {', '.join(decisions)}")
    if not phase.get("diff_range"):
        errors.append("diff_range is required")
    audit_path = d / phase.get("audit_file", f"audits/phase-{phase_key_value}.md")
    if not audit_path.exists():
        errors.append(f"phase audit artifact not found: {audit_path}")
    return errors


def integration_verify_errors(root: Path, domain: str, state: dict[str, Any], docs: dict[Path, dict[str, Any]]) -> list[str]:
    phases = normalized_phases(state)
    errors = []
    if not phases and effective_workflow_type(state) != "audit_remediation":
        errors.append("project has no phases to verify")
    unverified = sorted(key for key, phase in phases.items() if phase.get("status") != "verified")
    if unverified:
        errors.append(f"phases are not verified: {', '.join(unverified)}")

    integration_items = [item for path, doc in docs.items() if item_phase(path, doc) == "integration" for item in (doc.get("items", []) or [])]
    open_items = [str(item.get("id")) for item in integration_items if item.get("status") not in TERMINAL_STATUSES]
    if open_items:
        errors.append(f"open integration WORK remains: {', '.join(open_items)}")
    blocked_items = [str(item.get("id")) for item in integration_items if item.get("status") == "blocked"]
    if blocked_items:
        errors.append(f"blocked integration WORK remains: {', '.join(blocked_items)}")
    pending_reviews = [str(item.get("id")) for item in integration_items if item.get("status") == "done" and (item.get("risk") or {}).get("level") in HIGH_RISK and not review_satisfied(item)]
    if pending_reviews:
        errors.append(f"high-risk integration WORK requires review: {', '.join(pending_reviews)}")
    unresolved = sorted(str(value) for value in state.get("unresolved_decisions", []) or [])
    if unresolved:
        errors.append(f"unresolved project decisions: {', '.join(unresolved)}")
    d = domain_dir(root, domain)
    integration = state.get("integration", {}) or {}
    audit_path = d / integration.get("audit_file", "audits/integration.md")
    if not audit_path.exists():
        errors.append(f"integration audit artifact not found: {audit_path}")
    return errors


def reject_transition(subject: str, action: str, errors: list[str]) -> int:
    for error in errors:
        print(f"{subject} cannot {action}: {error}", file=sys.stderr)
    return 2


def choose_next(
    root: Path,
    domain: str,
    state: dict[str, Any],
    statuses: set[str] | None = None,
    work_overrides: dict[Path, dict[str, Any]] | None = None,
):
    d = domain_dir(root, domain)
    docs, index, _ = load_work_index(d, work_overrides)
    phases = normalized_phases(state)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or [])
    all_phases_verified = effective_workflow_type(state) == "audit_remediation" or (
        bool(phases) and all(entry.get("status") == "verified" for entry in phases.values())
    )

    candidates = []
    for path, doc in docs.items():
        phase = item_phase(path, doc)
        if phase == "integration":
            if not all_phases_verified:
                continue
        elif phases.get(phase, {}).get("status") == "verified":
            continue
        for item in doc.get("items", []) or []:
            status = item.get("status")
            if status in {"in_progress", "ready"} and (statuses is None or status in statuses) and deps_satisfied(item, index) and decision_satisfied(item, unresolved):
                priority = 0 if status == "in_progress" else 1
                risk = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get((item.get("risk") or {}).get("level"), 2)
                candidates.append((priority, phase == "integration", phase, risk, str(item.get("id")), path, item))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4]))
    _, _, phase, _, _, path, item = candidates[0]
    return phase, path, item


def work_review_action(
    root: Path,
    domain: str,
    state: dict[str, Any],
    work_overrides: dict[Path, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return the unresolved high-risk review action before normal ready WORK."""
    d = domain_dir(root, domain)
    docs, index, _ = load_work_index(d, work_overrides)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or [])
    reviews = []
    for path, doc in docs.items():
        for item in doc.get("items", []) or []:
            review = effective_review(item)
            if item.get("status") == "done" and review["required"] and review["status"] != "verified":
                reviews.append((str(item.get("id")), item_phase(path, doc), item, review))
    # Phase before id, the same ordering choose_next uses, so both halves of the runtime agree.
    for item_id, phase, _, review in sorted(reviews, key=lambda entry: (entry[1], entry[0])):
        if review["status"] == "pending":
            return {"role": "auditor", "command": "audit", "scope": "work", "mode": "initial", "phase": None if phase == "integration" else phase, "work_item": item_id}
        if review["status"] == "blocked":
            return {"role": "human", "command": "decision", "scope": "work", "phase": None if phase == "integration" else phase, "work_item": item_id}
    for item_id, phase, _, review in sorted(reviews, key=lambda entry: (entry[1], entry[0])):
        if review["status"] != "remediation":
            continue
        remediation = [index.get(str(remediation_id)) for remediation_id in review["remediation_work_ids"]]
        executable = [target for target in remediation if target and target[1].get("status") in {"in_progress", "ready"} and deps_satisfied(target[1], index) and decision_satisfied(target[1], unresolved)]
        if executable:
            executable.sort(key=lambda target: (0 if target[1].get("status") == "in_progress" else 1, str(target[1].get("id"))))
            remediation_item = executable[0][1]
            remediation_phase = item_phase(executable[0][0], docs[executable[0][0]])
            return {"role": "executor", "command": "run", "scope": "integration" if remediation_phase == "integration" else "phase", "phase": None if remediation_phase == "integration" else remediation_phase, "work_item": remediation_item.get("id"), "item_kind": remediation_item.get("kind")}
        if remediation and all(target and target[1].get("status") in TERMINAL_STATUSES and review_satisfied(target[1]) for target in remediation):
            return {"role": "auditor", "command": "audit", "scope": "work", "mode": "closure", "phase": None if phase == "integration" else phase, "work_item": item_id}
        return {"role": "human", "command": "decision", "scope": "work", "phase": None if phase == "integration" else phase, "work_item": item_id}
    return None


def plan_remediation_action(
    root: Path,
    domain: str,
    state: dict[str, Any],
    review: dict[str, Any],
    work_overrides: dict[Path, dict[str, Any]] | None,
) -> dict[str, Any]:
    if state.get("unresolved_decisions"):
        return {"role": "human", "command": "decision", "scope": "plan", "phase": None, "work_item": None}
    d = domain_dir(root, domain)
    docs, index, _ = load_work_index(d, work_overrides)
    targets = [index.get(str(item_id)) for item_id in review.get("remediation_work_ids", [])]
    for status in ["in_progress", "ready"]:
        for target in targets:
            if not target or target[1].get("status") != status:
                continue
            path, item = target
            if deps_satisfied(item, index) and decision_satisfied(item, set()):
                phase = item_phase(path, docs[path])
                return {
                    "role": "executor",
                    "command": "run",
                    "scope": "integration" if phase == "integration" else "phase",
                    "phase": None if phase == "integration" else phase,
                    "work_item": item.get("id"),
                    "item_kind": item.get("kind"),
                }
    for target in targets:
        if not target or target[1].get("status") != "done":
            continue
        path, item = target
        item_review = effective_review(item)
        phase = item_phase(path, docs[path])
        if item_review["required"] and item_review["status"] == "pending":
            return {"role": "auditor", "command": "audit", "scope": "work", "mode": "initial", "phase": None if phase == "integration" else phase, "work_item": item.get("id")}
        if item_review["required"] and item_review["status"] != "verified":
            action = work_review_action(root, domain, state, work_overrides)
            if action and action.get("work_item") == item.get("id"):
                return action
            return {"role": "human", "command": "decision", "scope": "work", "phase": None if phase == "integration" else phase, "work_item": item.get("id")}
    if targets and all(target and target[1].get("status") in TERMINAL_STATUSES and review_satisfied(target[1]) for target in targets):
        return {"role": "auditor", "command": "audit", "scope": "plan", "mode": "closure", "phase": None, "work_item": None}
    return {"role": "human", "command": "decision", "scope": "plan", "phase": None, "work_item": None}


def compute_next_action(
    root: Path,
    domain: str,
    state: dict[str, Any],
    work_overrides: dict[Path, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    d = domain_dir(root, domain)
    work = work_files(d)
    workflow_type = effective_workflow_type(state)
    integration = state.get("integration", {}) or {}
    phases = normalized_phases(state)
    all_verified = bool(phases) and all(phase.get("status") == "verified" for phase in phases.values())
    plan_review = effective_plan_review(state)
    remediation_work_ids = plan_review.get("remediation_work_ids", [])
    if not isinstance(remediation_work_ids, list):
        raise ValueError("plan_review.remediation_work_ids must be a list")
    if state.get("unresolved_decisions") and (workflow_type == "audit_remediation" or all_verified):
        return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None}
    if integration.get("status") == "blocked" and (workflow_type == "audit_remediation" or all_verified):
        return {"role": "human", "command": "decision", "scope": "integration", "phase": None, "work_item": None}
    if workflow_type == "audit_remediation":
        integration_status = integration.get("status", "audit")
        if integration_status in {"pending", "audit"}:
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "initial", "phase": None, "work_item": None}
        if integration_status == "closure":
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
        if integration_status == "verified":
            return {"role": "none", "command": "complete", "scope": "project", "phase": None, "work_item": None}
        if not work:
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
    elif not work:
        return {"role": "architect", "command": "plan", "scope": "project", "phase": None, "work_item": None}

    if plan_review.get("required") and plan_review.get("status") != "verified":
        if plan_review.get("status") == "blocked":
            return {"role": "human", "command": "decision", "scope": "plan", "phase": None, "work_item": None}
        if plan_review.get("status") in {"pending", "remediation"} and remediation_work_ids:
            return plan_remediation_action(root, domain, state, plan_review, work_overrides)
        return {"role": "auditor", "command": "audit", "scope": "plan", "mode": "initial", "phase": None, "work_item": None}

    pending_phase_audits = [key for key, phase in sorted(phases.items()) if phase.get("status") == "audit"]
    if pending_phase_audits:
        return {"role": "auditor", "command": "audit", "scope": "phase", "mode": "initial", "phase": pending_phase_audits[0], "work_item": None}
    recorded_action = state.get("next_action") or {}
    recorded_phase = phase_key(recorded_action.get("phase")) if recorded_action.get("phase") is not None else None
    if (
        recorded_action.get("command") == "audit"
        and recorded_action.get("scope") == "phase"
        and recorded_action.get("mode") == "closure"
        and recorded_phase in phases
        and phases[recorded_phase].get("status") == "remediation"
    ):
        return {"role": "auditor", "command": "audit", "scope": "phase", "mode": "closure", "phase": recorded_phase, "work_item": None}
    if (
        recorded_action.get("command") == "audit"
        and recorded_action.get("scope") == "integration"
        and recorded_action.get("mode") == "closure"
        and integration.get("status") == "remediation"
        and canonical_audit_has_mode(root, domain, state, "integration", "closure", None, None)
    ):
        return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
    integration_audit_is_active = all_verified and integration.get("status") in {"audit", "closure"}
    if integration_audit_is_active:
        if integration.get("status") in {"pending", "audit"}:
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "initial", "phase": None, "work_item": None}
        if integration.get("status") == "closure":
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}

    nxt = choose_next(root, domain, state, {"in_progress"}, work_overrides)
    if nxt:
        phase, _, item = nxt
        return {"role": "executor", "command": "run", "scope": "integration" if phase == "integration" else "phase", "phase": None if phase == "integration" else phase, "work_item": item.get("id"), "item_kind": item.get("kind")}

    review_action = work_review_action(root, domain, state, work_overrides)
    if review_action:
        return review_action

    nxt = choose_next(root, domain, state, {"ready"}, work_overrides)
    if nxt:
        phase, _, item = nxt
        return {"role": "executor", "command": "run", "scope": "integration" if phase == "integration" else "phase", "phase": None if phase == "integration" else phase, "work_item": item.get("id"), "item_kind": item.get("kind")}

    docs, _, _ = load_work_index(d, work_overrides)
    for key in sorted(phases):
        ps = phases[key]
        if ps.get("status") == "verified":
            continue
        work_file = d / ps.get("work_file", f"work/phase-{key}.yaml")
        doc = docs.get(work_file) or load_yaml(work_file, {}) or {}
        items = doc.get("items", []) or []
        if ps.get("status") == "blocked" or any(i.get("status") == "blocked" for i in items):
            return {"role": "human", "command": "decision", "scope": "phase", "phase": key, "work_item": None}
        if items and all(i.get("status") in TERMINAL_STATUSES for i in items):
            mode = "closure" if ps.get("status") == "remediation" else "initial"
            return {"role": "auditor", "command": "audit", "scope": "phase", "mode": mode, "phase": key, "work_item": None}

    if workflow_type == "audit_remediation":
        integration_items = [
            item
            for path, doc in docs.items()
            if item_phase(path, doc) == "integration"
            for item in (doc.get("items", []) or [])
        ]
        blocked = [str(item.get("id")) for item in integration_items if item.get("status") == "blocked"]
        if blocked:
            return {"role": "human", "command": "decision", "scope": "integration", "phase": None, "work_item": blocked[0] if len(blocked) == 1 else None}
        if integration.get("status") == "remediation" and all(
            item.get("status") in TERMINAL_STATUSES and review_satisfied(item)
            for item in integration_items
        ):
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
        return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None, "reason": "lifecycle is incomplete"}

    all_verified = bool(phases) and all(p.get("status") == "verified" for p in phases.values())
    istatus = integration.get("status", "pending")
    if all_verified:
        # An unresolved project decision must clear before any integration audit/closure.
        if state.get("unresolved_decisions"):
            return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None}
        # Blocked integration WORK needs a human decision, never an audit projection.
        integration_items = [
            item
            for path, doc in docs.items() if item_phase(path, doc) == "integration"
            for item in (doc.get("items", []) or [])
        ]
        blocked = [str(item.get("id")) for item in integration_items if item.get("status") == "blocked"]
        if blocked:
            action = {"role": "human", "command": "decision", "scope": "integration", "phase": None, "work_item": None}
            if len(blocked) == 1:
                action["work_item"] = blocked[0]
            return action
        if istatus in {"pending", "audit"}:
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "initial", "phase": None, "work_item": None}
        if istatus == "closure":
            return {"role": "auditor", "command": "audit", "scope": "integration", "mode": "closure", "phase": None, "work_item": None}
        if istatus == "verified":
            return {"role": "none", "command": "complete", "scope": "project", "phase": None, "work_item": None}

    if state.get("unresolved_decisions"):
        return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None}
    return {"role": "human", "command": "decision", "scope": "project", "phase": None, "work_item": None, "reason": "lifecycle is incomplete"}


def project_status_for_action(action: dict[str, Any]) -> str:
    """Map a computed action to the schema's lifecycle projection."""
    command = action.get("command")
    scope = action.get("scope")
    if command == "plan":
        return "planning"
    if command == "complete":
        return "complete"
    if command == "decision" or action.get("role") == "human":
        return "blocked"
    if command == "run":
        remediation = action.get("item_kind") in {"remediation", "evidence"}
        if scope == "integration":
            return "integration_remediation" if remediation else "integration_audit"
        return "remediation" if remediation else "phase_execution"
    if command == "audit":
        if scope == "plan":
            return "plan_review"
        if scope == "work":
            # A work audit is its own lifecycle position in both modes. Reporting the initial mode
            # as phase_audit, and the closure mode as integration_closure or remediation,
            # contradicted the next.scope printed beside it.
            return "work_audit"
        if scope == "phase":
            return "remediation" if action.get("mode") == "closure" else "phase_audit"
        if scope == "integration":
            return "integration_closure" if action.get("mode") == "closure" else "integration_audit"
    return "blocked"


def active_phase_for_action(root: Path, domain: str, state: dict[str, Any], action: dict[str, Any]) -> str | None:
    """Project the single phase that owns the computed action, without guessing ambiguously."""
    scope = action.get("scope")
    if scope in {"project", "integration"}:
        return None
    if scope == "work" and action.get("work_item"):
        try:
            path, doc, _ = find_item(root, domain, str(action["work_item"]))
        except KeyError:
            return None
        phase = item_phase(path, doc)
        return None if phase == "integration" else phase
    if action.get("phase") is not None:
        return phase_key(action["phase"])
    active = [key for key, phase in normalized_phases(state).items() if phase.get("status") in {"executing", "audit", "remediation", "blocked"}]
    return active[0] if len(active) == 1 else None


def project_state(
    root: Path,
    domain: str,
    state: dict[str, Any],
    work_overrides: dict[Path, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state["target_sha"] = current_sha(root)
    state["next_action"] = compute_next_action(root, domain, state, work_overrides)
    state["project_status"] = project_status_for_action(state["next_action"])
    state["active_phase"] = active_phase_for_action(root, domain, state, state["next_action"])
    return state


def refresh_state(root: Path, domain: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    path = state_path(root, domain)
    state = project_state(root, domain, state if state is not None else load_yaml(path, {}) or {})
    dump_yaml_if_changed(path, state)
    return state


def action_inputs(root: Path, domain: str, state: dict[str, Any]) -> list[str]:
    """The documents a fresh session must load for the computed next action."""
    d = domain_dir(root, domain)
    action = state.get("next_action", {}) or {}
    inputs = [f"{domain}/STATE.yaml", f"{domain}/PRD.md", f"{domain}/PLAN.md"]
    if (d / "PITFALLS.md").exists():
        inputs.append(f"{domain}/PITFALLS.md")
    if state.get("unresolved_decisions"):
        inputs.append(f"{domain}/DECISIONS.md")
    phase = action.get("phase")
    if phase:
        ps = normalized_phases(state).get(phase, {})
        inputs.append(ps.get("work_file", f"work/phase-{phase}.yaml"))
        if action.get("command") == "audit" and action.get("scope") != "work":
            inputs.append(ps.get("audit_file", f"audits/phase-{phase}.md"))
    item_id = action.get("work_item")
    if item_id:
        try:
            _, _, item = find_item(root, domain, item_id)
        except KeyError:
            return inputs
        origin = item.get("origin") or {}
        ids = [str(x) for key in ["requirements", "findings", "plan_items"] for x in (origin.get(key) or [])]
        if ids:
            inputs.append(f"PRD/PLAN sections: {', '.join(ids)}")
        if action.get("command") == "audit" and action.get("scope") == "work":
            inputs.append(effective_review(item)["audit_file"])
    return inputs


def print_status(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    if not path.exists():
        print(f"Domain not initialized: {args.domain}", file=sys.stderr)
        return 2
    config_errors, config_warnings, newer_config = config_protocol_diagnostics(root)
    if config_errors:
        for error in config_errors:
            print(f"DevFlow error: {error}", file=sys.stderr)
        return 2
    for warning in config_warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    raw_state = load_yaml(path, {}) or {}
    state = project_state(root, args.domain, copy.deepcopy(raw_state)) if newer_config else refresh_state(root, args.domain, raw_state)
    cfg = runtime_config(root)
    d = domain_dir(root, args.domain)
    protocol_versions = reported_protocol_versions(root, state)
    if args.json:
        report = dict(state)
        report.setdefault("workflow_type", effective_workflow_type(state))
        report["runtime_config"] = ".devflow/config.yaml"
        report["domains_root"] = cfg["domains_root"]
        report["domain_dir"] = str(d.relative_to(root))
        report["protocol_versions"] = protocol_versions
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    action = state.get("next_action", {}) or {}
    print(f"domain: {state.get('domain')}")
    print(f"workflow_type: {effective_workflow_type(state)}")
    print("runtime_config: .devflow/config.yaml")
    print(f"domains_root: {cfg['domains_root']}")
    print(f"domain_dir: {d.relative_to(root)}")
    for name, value in protocol_versions.items():
        print(f"protocol.{name}: {value}")
    print(f"project_status: {state.get('project_status')}")
    print(f"risk_profile: {state.get('risk_profile')}")
    print(f"baseline_sha: {short_sha(state.get('baseline_sha'))}")
    print(f"target_sha: {short_sha(state.get('target_sha'))}")
    print(f"unresolved_decisions: {', '.join(state.get('unresolved_decisions', []) or []) or '<none>'}")
    blocked = [i for _, (_, i) in load_work_index(domain_dir(root, args.domain))[1].items() if i.get("status") == "blocked"]
    if blocked:
        print(f"blocked_work: {', '.join(str(i.get('id')) for i in blocked)}")
    print(f"next.role: {action.get('role')}")
    print(f"next.command: {action.get('command')}")
    print(f"next.scope: {action.get('scope')}")
    if action.get("mode"):
        print(f"next.mode: {action.get('mode')}")
    if action.get("phase") is not None:
        print(f"next.phase: {action.get('phase')}")
        ps = normalized_phases(state).get(action.get("phase"), {})
        if ps.get("diff_range"):
            print(f"next.diff_range: {ps['diff_range']}")
    if action.get("work_item"):
        print(f"next.work_item: {action.get('work_item')}")
    for entry in action_inputs(root, args.domain, state):
        print(f"next.input: {entry}")
    return 0


def find_item(root: Path, domain: str, item_id: str):
    d = domain_dir(root, domain)
    docs, index, _ = load_work_index(d)
    found = index.get(item_id)
    if not found:
        raise KeyError(f"Unknown WORK item: {item_id}")
    path, item = found
    return path, docs[path], item


def next_item(args: argparse.Namespace) -> int:
    root = repo_root()
    state = refresh_state(root, args.domain)
    action = state.get("next_action", {}) or {}
    if action.get("command") != "run" or not action.get("work_item"):
        print(json.dumps(action, ensure_ascii=False, indent=2) if args.json else f"No executable WORK item. Next action: {action}")
        return 1
    _, _, item = find_item(root, args.domain, action["work_item"])
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(item, sort_keys=False, allow_unicode=True))
    return 0


def work_update(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    try:
        path, doc, item = find_item(root, args.domain, args.item)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    state = load_yaml(state_path(root, args.domain), {}) or {}
    _, index, _ = load_work_index(d)
    _, open_decisions = decision_state_errors(state, d)
    unresolved = {str(value) for value in state.get("unresolved_decisions", []) or []} | open_decisions
    document_errors, _ = validate_work_file(path, doc, index, unresolved)
    if args.work_command == "start":
        errors = document_errors + work_start_errors(state, d, path, doc, item, index)
        if errors:
            return reject_transition(args.item, "start", errors)
        item["status"] = "in_progress"
        item["block_reason"] = None
    elif args.work_command == "done":
        if document_errors:
            return reject_transition(args.item, "done", document_errors)
        if item.get("status") != "in_progress":
            return reject_transition(args.item, "done", [f"status=in_progress is required, not {item.get('status')}"])
        current_commands = list((item.get("evidence") or {}).get("commands") or [])
        cli_commands = list(getattr(args, "command", None) or [])
        if item.get("kind") != "documentation" and not has_nonblank_string(current_commands + cli_commands):
            return reject_transition(args.item, "done", ["verification evidence is required. Pass --command '<cmd> -> <result>'."])
        evidence = item.setdefault("evidence", {})
        for attr, key in [("changed_file", "changed_files"), ("command", "commands"), ("deviation", "deviations"), ("discovery", "discoveries")]:
            vals = getattr(args, attr, None) or []
            if key == "commands":
                vals = [value for value in vals if isinstance(value, str) and value.strip()]
            evidence.setdefault(key, [])
            evidence[key].extend(vals)
        if args.commit:
            evidence["commit"] = args.commit
        if (item.get("risk") or {}).get("level") in HIGH_RISK:
            review = effective_review(item)
            if review["status"] not in {"remediation", "blocked", "verified"}:
                review["status"] = "pending"
            item["review"] = review
        item["status"] = "done"
        item["block_reason"] = None
    elif args.work_command == "block":
        if document_errors:
            return reject_transition(args.item, "block", document_errors)
        if item.get("status") not in {"ready", "in_progress"}:
            return reject_transition(args.item, "block", [f"cannot block status {item.get('status')}"])
        reason = (args.reason or "").strip()
        if not reason:
            return reject_transition(args.item, "block", ["a non-empty reason is required"])
        item["status"] = "blocked"
        item["block_reason"] = reason
    commit_lifecycle_mutation(root, args.domain, copy.deepcopy(state), {path: doc})
    print(f"{args.item}: {item['status']}")
    return 0


def work_review(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    state = load_yaml(state_path(root, args.domain), {}) or {}
    if args.review_status == "verified" and requires_audit_apply(state, root):
        return reject_transition(args.item, "be verified", ["protocol 1.3+ requires devflow audit apply"])
    try:
        path, doc, item = find_item(root, args.domain, args.item)
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 2
    _, index, _ = load_work_index(d)
    _, open_decisions = decision_state_errors(state, d)
    unresolved = {str(value) for value in state.get("unresolved_decisions", []) or []} | open_decisions
    document_errors, _ = validate_work_file(path, doc, index, unresolved)
    if document_errors:
        return reject_transition(args.item, "be reviewed", document_errors)
    review = effective_review(item)
    if item.get("status") != "done":
        print(f"{args.item}: review requires status=done", file=sys.stderr)
        return 2
    if not review["required"]:
        print(f"{args.item}: review is not required", file=sys.stderr)
        return 2
    if args.review_status == "verified":
        if review["status"] == "remediation":
            blockers = remediation_completion_blockers(review, index)
            if blockers:
                for blocker in blockers:
                    print(f"{args.item}: {blocker}", file=sys.stderr)
                return 2
        audit_path = d / review["audit_file"]
        if not audit_path.exists():
            print(f"{args.item}: work audit artifact not found: {audit_path}", file=sys.stderr)
            return 2
        review["status"] = "verified"
    elif args.review_status == "remediation":
        if not args.remediation_work:
            print(f"{args.item}: remediation review requires --remediation-work", file=sys.stderr)
            return 2
        for remediation_id in args.remediation_work:
            target = index.get(remediation_id)
            if not target:
                print(f"{args.item}: unknown remediation WORK {remediation_id}", file=sys.stderr)
                return 2
            remediation = target[1]
            if remediation.get("kind") not in {"remediation", "evidence"}:
                print(f"{args.item}: {remediation_id} must be kind remediation or evidence", file=sys.stderr)
                return 2
            if not ((remediation.get("origin") or {}).get("findings") or []):
                print(f"{args.item}: {remediation_id} must carry origin.findings traceability", file=sys.stderr)
                return 2
            if dependency_reaches(str(remediation_id), args.item, index):
                print(
                    f"{args.item}: remediation WORK {remediation_id} depends on {args.item} and cannot run before {args.item} review closure",
                    file=sys.stderr,
                )
                return 2
        review["status"] = "remediation"
        review["remediation_work_ids"] = list(dict.fromkeys(args.remediation_work))
    elif args.review_status == "pending":
        # The stop-blocked recovery: return a `blocked` work review to `pending` so the scope
        # can be audited again, mirroring `plan-review set pending`, `phase set <n> audit` and
        # `integration set <d> audit`. Only `blocked` may reopen; it never sets anything verified.
        if review["status"] != "blocked":
            print(f"{args.item}: review pending requires a blocked review, not {review['status']}", file=sys.stderr)
            return 2
        review["status"] = "pending"
        review["remediation_work_ids"] = []
    else:
        review["status"] = "blocked"
    item["review"] = review
    commit_lifecycle_mutation(root, args.domain, copy.deepcopy(state), {path: doc})
    print(f"{args.item}: review {review['status']}")
    return 0


def phase_entry(state: dict[str, Any], key: str) -> dict[str, Any]:
    phases = state.setdefault("phases", {})
    raw = raw_phase_key(state, key)
    if raw is None:
        phases[key] = {"status": "planned", "work_file": f"work/phase-{key}.yaml", "audit_file": f"audits/phase-{key}.md"}
        return phases[key]
    return phases[raw]


def phase_creation_errors(root: Path, domain: str, state: dict[str, Any], key: str) -> list[str]:
    """A mistyped phase number used to appear in STATE and block integration forever."""
    if raw_phase_key(state, key) is not None:
        return []
    work_file = domain_dir(root, domain) / f"work/phase-{key}.yaml"
    if work_file.exists():
        return []
    return [
        f"phase {key} is not in STATE and {work_file.relative_to(root)} does not exist. "
        "Add the phase in PLAN and STATE, or create its WORK file first."
    ]


def set_phase(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    key = phase_key(args.phase)
    phases = normalized_phases(state)
    existing = phases.get(key)
    creation_errors = phase_creation_errors(root, args.domain, state, key)
    if creation_errors:
        return reject_transition(f"phase {key}", "be created", creation_errors)
    if existing and existing.get("status") == "verified" and args.status != "verified":
        return reject_transition(f"phase {key}", "change", ["a verified phase cannot be reopened"])
    if args.status == "verified" and requires_audit_apply(state, root):
        return reject_transition(f"phase {key}", "be verified", ["protocol 1.3+ requires devflow audit apply"])
    if args.status == "verified":
        docs, _, _ = load_work_index(domain_dir(root, args.domain))
        errors = phase_verify_errors(root, args.domain, state, key, docs)
        errors.extend(f"validation: {error}" for error in collect_validation(root, args.domain)[0])
        if errors:
            return reject_transition(f"phase {key}", "be verified", errors)
    phase = phase_entry(state, key)
    phase["status"] = args.status
    commit_lifecycle_mutation(root, args.domain, state)
    print(f"phase {key}: {args.status}")
    return 0


def set_phase_ref(args: argparse.Namespace) -> int:
    """Pin an auditable diff range, refusing the stale-3-dot trap when the stack is not linear."""
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    key = phase_key(args.phase)
    creation_errors = phase_creation_errors(root, args.domain, state, key)
    if creation_errors:
        return reject_transition(f"phase {key}", "be created", creation_errors)
    phase = phase_entry(state, key)

    if args.range:
        phase["diff_range"] = args.range
        phase["base_ref"] = args.base
        phase["head_ref"] = args.head
        commit_lifecycle_mutation(root, args.domain, state)
        print(f"phase {key} diff_range: {args.range} (explicit)")
        return 0

    base_sha = run_git(["rev-parse", "--verify", f"{args.base}^{{commit}}"], root)
    head_sha = run_git(["rev-parse", "--verify", f"{args.head}^{{commit}}"], root)
    if not base_sha or not head_sha:
        print(f"Cannot resolve refs: base={args.base} head={args.head}", file=sys.stderr)
        return 2
    if not git_ok(["merge-base", "--is-ancestor", base_sha, head_sha], root):
        print(f"{args.base} is not an ancestor of {args.head}. A 3-dot diff would pick a stale merge base.", file=sys.stderr)
        print("Inspect the graph, then re-run with an explicit range:", file=sys.stderr)
        print(f"  git log --graph --oneline {args.base} {args.head} | head -20", file=sys.stderr)
        print(f"  devflow phase ref {args.domain} {args.phase} --base {args.base} --head {args.head} --range '<first>^..<last>'", file=sys.stderr)
        return 2

    phase["base_ref"] = args.base
    phase["head_ref"] = args.head
    phase["base_sha"] = base_sha
    phase["head_sha"] = head_sha
    phase["diff_range"] = f"{base_sha}...{head_sha}"
    commit_lifecycle_mutation(root, args.domain, state)
    print(f"phase {key} diff_range: {short_sha(base_sha)}...{short_sha(head_sha)}")
    return 0


def set_plan_review(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    pr = effective_plan_review(state)
    required = bool(pr.get("required"))
    audit_file = pr["audit_file"]
    if args.status == "skipped" and required:
        return reject_transition("plan review", "be skipped", ["review is required"])
    if args.status == "verified" and requires_audit_apply(state, root):
        return reject_transition("plan review", "be verified", ["protocol 1.3+ requires devflow audit apply"])
    if args.status == "verified":
        d = domain_dir(root, args.domain)
        errors = []
        docs, _, _ = load_work_index(d)
        errors.extend(delivery_placeholder_errors(d, state, docs))
        if not (d / "PLAN.md").exists():
            errors.append(f"PLAN.md not found: {d / 'PLAN.md'}")
        if not (d / audit_file).exists():
            errors.append(f"plan audit artifact not found: {d / audit_file}")
        if errors:
            return reject_transition("plan review", "be verified", errors)
        pr["audit_file"] = audit_file
    pr["status"] = args.status
    state["plan_review"] = pr
    commit_lifecycle_mutation(root, args.domain, state)
    print(f"plan_review: {args.status}")
    return 0


def set_integration(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    integ = dict(state.get("integration", {}) or {})
    if integ.get("status") == "verified" and args.status != "verified":
        return reject_transition("integration", "change", ["a verified integration cannot be reopened"])
    if args.status == "verified" and requires_audit_apply(state, root):
        return reject_transition("integration", "be verified", ["protocol 1.3+ requires devflow audit apply"])
    if args.status == "verified":
        docs, _, _ = load_work_index(domain_dir(root, args.domain))
        errors = integration_verify_errors(root, args.domain, state, docs)
        errors.extend(f"validation: {error}" for error in collect_validation(root, args.domain)[0])
        if errors:
            return reject_transition("integration", "be verified", errors)
    integ["status"] = args.status
    state["integration"] = integ
    commit_lifecycle_mutation(root, args.domain, state)
    print(f"integration: {args.status}")
    return 0


def decision_update(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    unresolved = [str(x) for x in state.get("unresolved_decisions", []) or []]
    if args.decision_command == "add" and args.decision not in unresolved:
        unresolved.append(args.decision)
    if args.decision_command == "resolve":
        unresolved = [x for x in unresolved if x != args.decision]
        open_ids, resolved_ids, _ = decision_document_records(d / "DECISIONS.md")
        if args.decision in open_ids:
            errors = [
                f"DECISIONS.md decision {args.decision} is still open; record a valid entry under ## Resolved first"
            ]
        elif args.decision not in resolved_ids:
            errors = [f"DECISIONS.md has no valid resolved decision record for {args.decision}"]
        else:
            errors = []
        prospective = dict(state)
        prospective["unresolved_decisions"] = unresolved
        decision_errors, _ = decision_state_errors(prospective, d)
        errors.extend(decision_errors)
        if errors:
            return reject_transition(f"decision {args.decision}", "be resolved", errors)
    state["unresolved_decisions"] = unresolved
    commit_lifecycle_mutation(root, args.domain, state)
    print(f"unresolved_decisions: {', '.join(unresolved) or '<none>'}")
    return 0


def is_placeholder_text(value: str) -> bool:
    stripped = value.strip()
    return (
        not stripped
        or (stripped.startswith("[") and stripped.endswith("]"))
        or stripped.upper() in {"TBD", "TODO"}
    )


def decision_document_records(path: Path) -> tuple[set[str], set[str], list[str]]:
    if not path.exists():
        return set(), set(), []

    records: list[tuple[str, str, str, list[str]]] = []
    section = ""
    current: tuple[str, str, str, list[str]] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        markdown_heading = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*$", line)
        if markdown_heading:
            current = None
            level, heading = len(markdown_heading.group(1)), markdown_heading.group(2)
            if level == 2:
                section = heading.lower() if heading.lower() in {"open", "resolved"} else ""
            elif level == 3 and section in {"open", "resolved"}:
                decision_heading = re.match(r"^(DEC-[A-Z0-9][A-Z0-9-]*)(?:\s+(.*))?$", heading, re.I)
                if decision_heading:
                    current = (section, decision_heading.group(1), (decision_heading.group(2) or "").strip(), [])
                    records.append(current)
            continue
        if current is not None:
            current[3].append(line)

    open_ids: set[str] = set()
    resolved_ids: set[str] = set()
    errors: list[str] = []
    seen: set[str] = set()
    for record_section, decision_id, title, lines in records:
        if decision_id.upper() == "DEC-XXX" or "[Question]" in title or "[Decision]" in title:
            continue
        if decision_id in seen:
            errors.append(f"DECISIONS.md contains duplicate decision id: {decision_id}")
            continue
        seen.add(decision_id)
        if record_section == "open":
            options = []
            for line in lines:
                option_match = re.match(r"^\s*-\s*Option(?:\s+[^:]+)?:\s*(.*?)\s*$", line, re.I)
                if option_match:
                    value = option_match.group(1).strip()
                    if not is_placeholder_text(value):
                        options.append(value)
            if len(options) < 2:
                errors.append(f"DECISIONS.md open decision {decision_id} requires at least two nonblank options")
            else:
                open_ids.add(decision_id)
        else:
            choices = []
            for line in lines:
                decision_match = re.match(r"^\s*-\s*Decision:\s*(.*?)\s*$", line, re.I)
                if decision_match:
                    value = decision_match.group(1).strip()
                    if not is_placeholder_text(value):
                        choices.append(value)
            if not choices:
                errors.append(f"DECISIONS.md resolved decision {decision_id} requires a nonblank Decision field")
            else:
                resolved_ids.add(decision_id)
    return open_ids, resolved_ids, errors


def decision_state_errors(state: dict[str, Any], d: Path) -> tuple[list[str], set[str]]:
    raw_unresolved = state.get("unresolved_decisions", []) or []
    if not isinstance(raw_unresolved, list):
        return ["STATE.unresolved_decisions must be a list"], set()
    unresolved = {str(value) for value in raw_unresolved if isinstance(value, str) and value.strip()}
    errors = []
    if len(unresolved) != len(raw_unresolved):
        errors.append("STATE.unresolved_decisions must contain unique nonblank strings")

    decisions_path = d / "DECISIONS.md"
    open_ids, _resolved_ids, document_errors = decision_document_records(decisions_path)
    errors.extend(document_errors)
    if unresolved and not decisions_path.exists():
        errors.append("DECISIONS.md is required when STATE.unresolved_decisions is nonempty")
    for decision_id in sorted(unresolved - open_ids):
        errors.append(f"STATE.unresolved_decisions references no valid open DECISIONS.md record: {decision_id}")
    for decision_id in sorted(open_ids - unresolved):
        errors.append(f"DECISIONS.md open decision is missing from STATE.unresolved_decisions: {decision_id}")
    return errors, open_ids


def validate_protocol_version(state: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    """The version was recorded but never read, so an artifact from any protocol validated."""
    if "protocol_version" not in state:
        return
    value = str(state.get("protocol_version") or "")
    version = parsed_protocol_version(value)
    if version is None:
        errors.append(f"Invalid protocol_version: {value or '<empty>'}")
        return
    major, minor, _patch = version
    runtime_major, runtime_minor, _runtime_patch = parsed_protocol_version(PROTOCOL_VERSION)
    if major != runtime_major:
        errors.append(f"Unsupported protocol_version {value}: this runtime implements {PROTOCOL_VERSION}")
    elif minor > runtime_minor:
        warnings.append(f"STATE protocol_version {value} is newer than this runtime's {PROTOCOL_VERSION}")


def validate_state(state: dict[str, Any], d: Path, errors: list[str], warnings: list[str]) -> None:
    for field in STATE_REQUIRED_FIELDS:
        if field not in state:
            errors.append(f"STATE missing field: {field}")
    validate_protocol_version(state, errors, warnings)
    if effective_workflow_type(state) not in WORKFLOW_TYPES:
        errors.append(f"Invalid workflow_type: {state.get('workflow_type')}")
    if state.get("project_status") not in PROJECT_STATUSES:
        errors.append(f"Invalid project_status: {state.get('project_status')}")
    if state.get("risk_profile") not in RISK_LEVELS:
        errors.append(f"Invalid risk_profile: {state.get('risk_profile')}")

    plan_review = state.get("plan_review")
    if plan_review is not None:
        if not isinstance(plan_review, dict):
            errors.append("plan_review must be a mapping")
        else:
            if not isinstance(plan_review.get("required"), bool):
                errors.append("plan_review.required must be boolean")
            if plan_review.get("status") not in PLAN_REVIEW_STATUSES:
                errors.append(f"Invalid plan_review.status: {plan_review.get('status')}")
            if "audit_file" in plan_review and (
                not isinstance(plan_review["audit_file"], str) or not plan_review["audit_file"].strip()
            ):
                errors.append("plan_review.audit_file must be a nonblank string")
            remediation_ids = plan_review.get("remediation_work_ids", [])
            if not isinstance(remediation_ids, list):
                errors.append("plan_review.remediation_work_ids must be a list")
            elif any(not isinstance(value, str) or not value.strip() for value in remediation_ids):
                errors.append("plan_review.remediation_work_ids must contain nonblank strings")
            elif plan_review.get("status") == "remediation" and not remediation_ids:
                errors.append("plan_review.status=remediation requires remediation_work_ids")
            errors.extend(audit_provenance_errors("plan_review", plan_review.get("audit_provenance")))

    integration = state.get("integration")
    if isinstance(integration, dict):
        errors.extend(audit_provenance_errors("integration", integration.get("audit_provenance")))

    seen: dict[str, str] = {}
    for raw in (state.get("phases", {}) or {}):
        key = phase_key(raw)
        if key in seen:
            errors.append(f"Duplicate phase entry: {seen[key]!r} and {raw!r} both normalize to {key!r}")
        seen[key] = str(raw)

    for key, phase in normalized_phases(state).items():
        for field in PHASE_ENTRY_REQUIRED_FIELDS:
            if field not in phase:
                errors.append(f"Phase {key} missing field: {field}")
        if "status" in phase and phase.get("status") not in PHASE_STATUSES:
            errors.append(f"Phase {key} invalid status: {phase.get('status')}")
        wf = phase.get("work_file")
        if wf and not (d / wf).exists():
            warnings.append(f"Phase {key} work file not created yet: {wf}")
        if phase.get("status") in {"audit", "verified"} and not phase.get("diff_range"):
            warnings.append(f"Phase {key} has no diff_range. Run 'devflow phase ref' before auditing.")
        if isinstance(phase, dict):
            errors.extend(audit_provenance_errors(f"phase {key}", phase.get("audit_provenance")))

    istatus = (state.get("integration", {}) or {}).get("status")
    if istatus not in INTEGRATION_STATUSES:
        errors.append(f"Invalid integration.status: {istatus}")


def validate_item(
    item: dict[str, Any],
    version: int,
    all_ids: set[str],
    index,
    unresolved: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    item_id = str(item.get("id", "<missing>"))
    for field in WORK_REQUIRED_ITEM_FIELDS:
        if field not in item:
            errors.append(f"{item_id}: missing {field}")
    kind = item.get("kind")
    status = item.get("status")
    level = (item.get("risk") or {}).get("level")
    if kind not in KINDS:
        errors.append(f"{item_id}: invalid kind {kind}")
    if status not in WORK_STATUSES:
        errors.append(f"{item_id}: invalid status {status}")
    if level not in RISK_LEVELS:
        errors.append(f"{item_id}: invalid risk.level {level}")
    origin = item.get("origin") or {}
    findings = origin.get("findings", []) if isinstance(origin, dict) else []
    if kind in FINDING_TRACEABILITY_KINDS and not has_nonblank_string(findings):
        errors.append(f"{item_id}: kind={kind} requires nonempty origin.findings")
    if isinstance(findings, list) and len(findings) >= AGGREGATION_REASON_THRESHOLD:
        aggregation_reason = origin.get("aggregation_reason")
        if not isinstance(aggregation_reason, str) or not aggregation_reason.strip():
            errors.append(f"{item_id}: multiple origin.findings require nonblank origin.aggregation_reason")
    acceptance = normalized_acceptance(item, version)
    commands = normalized_verification_commands(item, version)
    if version == 1:
        if not acceptance:
            errors.append(f"{item_id}: acceptance must not be empty")
        if not has_nonblank_string([command["command"] for command in commands]):
            errors.append(f"{item_id}: verification.commands must contain a non-empty command")
    else:
        raw_acceptance = item.get("acceptance")
        raw_commands = (item.get("verification") or {}).get("commands") if isinstance(item.get("verification"), dict) else None
        if not isinstance(raw_acceptance, list) or not raw_acceptance:
            errors.append(f"{item_id}: acceptance must not be empty")
        elif any(not isinstance(value, dict) for value in raw_acceptance):
            errors.append(f"{item_id}: acceptance entries must be mappings in WORK version 2")
        if not isinstance(raw_commands, list) or not raw_commands:
            errors.append(f"{item_id}: verification.commands must not be empty")
        elif any(not isinstance(value, dict) for value in raw_commands):
            errors.append(f"{item_id}: verification.commands entries must be mappings in WORK version 2")

        acceptance_ids: set[str] = set()
        for acceptance_entry in acceptance:
            acceptance_id = acceptance_entry.get("id")
            if not isinstance(acceptance_id, str) or not acceptance_id.strip():
                errors.append(f"{item_id}: acceptance id must be a nonblank string")
            elif acceptance_id in acceptance_ids:
                errors.append(f"{item_id}: duplicate acceptance id {acceptance_id}")
            else:
                acceptance_ids.add(acceptance_id)
            criterion = acceptance_entry.get("criterion")
            if not isinstance(criterion, str) or not criterion.strip():
                errors.append(f"{item_id}: acceptance criterion must be a nonblank string")

        command_ids: set[str] = set()
        covered_ids: set[str] = set()
        for command in commands:
            command_id = command.get("id")
            if not isinstance(command_id, str) or not command_id.strip():
                errors.append(f"{item_id}: verification command id must be a nonblank string")
            elif command_id in command_ids:
                errors.append(f"{item_id}: duplicate verification command id {command_id}")
            else:
                command_ids.add(command_id)
            if not isinstance(command.get("command"), str) or not command["command"].strip():
                errors.append(f"{item_id}: verification command must be a nonblank string")
            covers = command.get("covers")
            if not isinstance(covers, list) or not covers:
                errors.append(f"{item_id}: verification command covers must not be empty")
                continue
            for acceptance_id in covers:
                if not isinstance(acceptance_id, str) or not acceptance_id.strip():
                    errors.append(f"{item_id}: verification command covers must contain nonblank acceptance ids")
                elif acceptance_id not in acceptance_ids:
                    errors.append(f"{item_id}: verification command {command_id} covers unknown acceptance id {acceptance_id}")
                else:
                    covered_ids.add(acceptance_id)
        uncovered_ids = sorted(acceptance_ids - covered_ids)
        if uncovered_ids:
            errors.append(f"{item_id}: acceptance ids lack verification coverage: {', '.join(uncovered_ids)}")
    for dep in item.get("dependencies", []) or []:
        if str(dep) not in all_ids:
            errors.append(f"{item_id}: unknown dependency {dep}")
    if status == "ready" and any(str(dec) in unresolved for dec in item.get("decision_dependencies", []) or []):
        errors.append(f"{item_id}: READY while blocked by unresolved decision")

    # Executable contract depth. High risk items must tell the executor what to re-verify.
    if level in HIGH_RISK and not (item.get("premise_checks") or []):
        errors.append(f"{item_id}: risk={level} requires premise_checks (facts to re-verify at HEAD before editing)")
    if level in HIGH_RISK and not (item.get("context") or []):
        warnings.append(f"{item_id}: risk={level} has no context (architect-verified repository facts)")
    if not (item.get("pitfalls") or []):
        warnings.append(f"{item_id}: no pitfalls recorded (known failure modes for this change)")

    # Evidence must back a completion claim.
    evidence = item.get("evidence") or {}
    if status == "done" and kind != "documentation" and not has_nonblank_string(evidence.get("commands")):
        errors.append(f"{item_id}: done without evidence.commands")

    review = item.get("review")
    if review is not None:
        if not isinstance(review, dict):
            errors.append(f"{item_id}: review must be a mapping")
        else:
            review_status = review.get("status")
            review_required = review.get("required")
            if review_status not in REVIEW_STATUSES:
                errors.append(f"{item_id}: invalid review.status {review_status}")
            if not isinstance(review_required, bool):
                errors.append(f"{item_id}: review.required must be boolean")
            if not review.get("audit_file"):
                errors.append(f"{item_id}: review.audit_file is required")
            errors.extend(audit_provenance_errors(f"{item_id}: review", review.get("audit_provenance")))
            remediation_ids = review.get("remediation_work_ids")
            if not isinstance(remediation_ids, list):
                errors.append(f"{item_id}: review.remediation_work_ids must be a list")
                remediation_ids = []
            if review_required is True and review_status == "skipped":
                errors.append(f"{item_id}: review.required=true cannot use status=skipped")
            if review_status == "remediation" and not remediation_ids:
                errors.append(f"{item_id}: review.status=remediation requires remediation_work_ids")
            for remediation_id in remediation_ids:
                if str(remediation_id) not in all_ids:
                    errors.append(f"{item_id}: unknown remediation WORK id {remediation_id}")
                elif review_status == "remediation" and dependency_reaches(str(remediation_id), item_id, index):
                    errors.append(
                        f"{item_id}: remediation WORK {remediation_id} depends on {item_id}; remediation cannot precede the reviewed WORK's own closure"
                    )
            if review_status == "verified" and status != "done":
                errors.append(f"{item_id}: review.status=verified requires status=done")
            if level in HIGH_RISK and status in {"done", "in_progress", "ready"} and review_required is not True:
                errors.append(f"{item_id}: risk={level} review.required must be true")

    # The transfer rule exists because a silently transferred requirement was missed for a whole cycle.
    if status == "transferred":
        transfer = item.get("transfer") or {}
        target_id = str(transfer.get("to", ""))
        if not target_id:
            errors.append(f"{item_id}: transferred without transfer.to")
        elif target_id not in index:
            errors.append(f"{item_id}: transfer.to points at unknown item {target_id}")
        else:
            target_path, target_item = index[target_id]
            source_reqs = {str(r) for r in ((item.get("origin") or {}).get("requirements") or [])}
            target_reqs = {str(r) for r in ((target_item.get("origin") or {}).get("requirements") or [])}
            missing = source_reqs - target_reqs
            if missing:
                errors.append(f"{item_id}: transferred requirements not registered on {target_id}: {', '.join(sorted(missing))}")


def validate_work_file(
    path: Path,
    doc: dict[str, Any],
    index: dict[str, tuple[Path, dict[str, Any]]],
    unresolved: set[str],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    version = work_document_version(doc)
    if version not in WORK_VERSIONS:
        return [f"{path.name}: unsupported WORK version {doc.get('version')!r}"], warnings
    items = doc.get("items", []) or []
    if not isinstance(items, list):
        return [f"{path.name}: items must be a list"], warnings
    for item in items:
        validate_item(item, version, set(index), index, unresolved, errors, warnings)
    return errors, warnings


def markdown_sections(text: str) -> list[tuple[int, str, str]]:
    heading_pattern = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*")
    fence_pattern = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
    headings: list[tuple[int, int, int, str]] = []
    fence_char: str | None = None
    fence_length = 0
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        if fence_char is not None:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*", line):
                fence_char = None
            offset += len(raw_line)
            continue
        fence = fence_pattern.fullmatch(line)
        if fence:
            marker, info = fence.groups()
            if marker[0] == "~" or "`" not in info:
                fence_char = marker[0]
                fence_length = len(marker)
                offset += len(raw_line)
                continue
        heading = heading_pattern.fullmatch(line)
        if heading:
            level = len(heading.group(1))
            title = re.sub(r"[ \t]+#+[ \t]*$", "", (heading.group(2) or "").strip())
            headings.append((offset, offset + len(line), level, title))
        offset += len(raw_line)

    sections: list[tuple[int, str, str]] = []
    for index, heading in enumerate(headings):
        _start, end, level, title = heading
        body_end = len(text)
        for following in headings[index + 1:]:
            if following[2] <= level:
                body_end = following[0]
                break
        sections.append((level, title, text[end:body_end]))
    return sections


def meaningful_markdown_body(body: str) -> bool:
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or re.fullmatch(r"(?:[-*+]|\d+[.)])", stripped):
            continue
        if re.fullmatch(r"[-*+]\s+[^:]+:\s*", stripped):
            continue
        if re.fullmatch(r" {0,3}#{1,6}(?:[ \t]+.*?)?[ \t]*", line):
            continue
        return True
    return False


def markdown_field_has_meaningful_body(body: str, label: str) -> bool:
    field_pattern = re.compile(r"^[ \t]*[-*+][ \t]+(Requirement|Acceptance criteria):[ \t]*(.*)$", re.M | re.I)
    fields = list(field_pattern.finditer(body))
    selected = [index for index, field in enumerate(fields) if field.group(1).casefold() == label.casefold()]
    if not selected:
        return False
    for index in selected:
        field = fields[index]
        body_end = fields[index + 1].start() if index + 1 < len(fields) else len(body)
        if not meaningful_markdown_body(field.group(2) + "\n" + body[field.end():body_end]):
            return False
    return True


def required_markdown_section_errors(path: Path, template_name: str) -> list[str]:
    template = read_template(template_name)
    template_headings = {title for level, title, _body in markdown_sections(template) if level == 2}
    required = MARKDOWN_SECTION_ANCHORS[template_name]
    text = read_text_if_exists(path)
    sections = markdown_sections(text)
    errors: list[str] = []
    for heading in required:
        if heading not in template_headings:
            errors.append(f"template {template_name} is missing required section: {heading}")
        bodies = [body for level, title, body in sections if level == 2 and title == heading]
        if not bodies:
            errors.append(f"{path.name} required section is empty: {heading}")
        elif any(not meaningful_markdown_body(body) for body in bodies):
            errors.append(f"{path.name} required section has an empty occurrence: {heading}")
    return errors


def delivery_placeholder_errors(d: Path, state: dict[str, Any], docs: dict[Path, dict[str, Any]]) -> list[str]:
    review = effective_plan_review(state)
    if not docs and not (review.get("required") and review.get("status") != "verified"):
        return []
    errors: list[str] = []
    for name in ["PRD.md", "PLAN.md"]:
        path = d / name
        text = read_text_if_exists(path)
        template = read_template(name)
        markers = set(re.findall(r"\[[^\]\n]+\]", template))
        if not text or any(marker in text for marker in markers):
            errors.append(f"{name} still contains placeholder scaffold markers")
        errors.extend(required_markdown_section_errors(path, name))
    prd_sections = markdown_sections(read_text_if_exists(d / "PRD.md"))
    requirement_sections = [body for level, title, body in prd_sections if level == 2 and title.casefold() == "4. requirements"]
    found_requirement = False
    for requirements_text in requirement_sections:
        requirements = [
            (title.split(maxsplit=1)[0], body)
            for level, title, body in markdown_sections(requirements_text)
            if level >= 3 and re.match(r"REQ-[A-Z0-9-]+\b", title, re.I)
        ]
        if not requirements:
            errors.append("PRD.md 4. Requirements section has no concrete requirement heading")
        found_requirement = found_requirement or bool(requirements)
        for requirement_id, body in requirements:
            if not markdown_field_has_meaningful_body(body, "Requirement"):
                errors.append(f"PRD.md {requirement_id} Requirement body must be nonblank")
            if not markdown_field_has_meaningful_body(body, "Acceptance criteria"):
                errors.append(f"PRD.md {requirement_id} Acceptance criteria body must be nonblank")
    if not found_requirement:
        errors.append("PRD.md placeholder contract has no concrete requirement heading")
    plan_text = read_text_if_exists(d / "PLAN.md")
    if re.search(r"^-\s*(?:Domain|Baseline SHA|Risk profile):\s*$", plan_text, re.M | re.I):
        errors.append("PLAN.md placeholder contract has blank metadata")
    return errors


def manifest_phase(path: Path) -> str | None:
    match = re.fullmatch(r"phase[-_]?([0-9]+)", path.stem, re.I)
    return phase_key(match.group(1)) if match else None


def phase_work_contract_errors(
    d: Path,
    state: dict[str, Any],
    docs: dict[Path, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    phases = normalized_phases(state)
    for key, phase_state in phases.items():
        relative = str(phase_state.get("work_file", f"work/phase-{key}.yaml"))
        path = d / relative
        named_phase = manifest_phase(path)
        if named_phase is not None and named_phase != key:
            errors.append(f"Phase {key} work_file {relative} names phase {named_phase}")
        doc = docs.get(path)
        if doc is not None:
            declared = phase_key(doc.get("phase")) if doc.get("phase") is not None else None
            if declared != key:
                errors.append(f"{path.name} declares phase {declared or '<missing>'}, not STATE phase {key}")

    for path, doc in docs.items():
        named_phase = manifest_phase(path)
        if named_phase is not None:
            if named_phase not in phases:
                errors.append(f"orphan phase manifest {path.name}: STATE has no phase {named_phase}")
            declared = phase_key(doc.get("phase")) if doc.get("phase") is not None else None
            if declared != named_phase:
                errors.append(
                    f"{path.name} declares phase {declared or '<missing>'}, but filename and STATE phase {named_phase}"
                )
        elif path.name == "integration.yaml" and item_phase(path, doc) != "integration":
            errors.append(f"integration.yaml declares non-integration phase {item_phase(path, doc)}")
    return errors


def audit_artifact_contract_errors(
    root: Path,
    d: Path,
    state: dict[str, Any],
    docs: dict[Path, dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    metadata_required = requires_audit_apply(state, root)
    candidates: list[tuple[Path, tuple[str, str | None, str | None, bool]]] = []
    plan_review = effective_plan_review(state)
    candidates.append(
        (
            d / plan_review["audit_file"],
            ("plan", None, None, plan_review.get("status") == "verified"),
        )
    )
    for key, phase_state in normalized_phases(state).items():
        candidates.append(
            (
                d / phase_state.get("audit_file", f"audits/phase-{key}.md"),
                ("phase", key, None, phase_state.get("status") == "verified"),
            )
        )
    integration = state.get("integration", {}) or {}
    candidates.append(
        (
            d / integration.get("audit_file", "audits/integration.md"),
            ("integration", None, None, integration.get("status") == "verified"),
        )
    )
    for work_path, doc in docs.items():
        for item in doc.get("items", []) or []:
            review = effective_review(item)
            candidates.append(
                (
                    d / review["audit_file"],
                    (
                        "work",
                        None if item_phase(work_path, doc) == "integration" else item_phase(work_path, doc),
                        str(item.get("id")),
                        review.get("status") == "verified",
                    ),
                )
            )

    specs: dict[Path, tuple[str, str | None, str | None, bool]] = {}
    for path, spec in candidates:
        canonical_path = path.resolve()
        previous = specs.get(canonical_path)
        if previous is not None and previous[:3] != spec[:3]:
            errors.append(
                f"canonical audit path collision at {canonical_path.relative_to(d.resolve())}: "
                f"{previous[:3]} and {spec[:3]}"
            )
            continue
        specs[canonical_path] = spec

    try:
        expected = compute_next_action(root, str(state.get("domain")), state)
    except (KeyError, TypeError, ValueError):
        expected = {}
    audit_schema: dict[str, Any] | None = None
    finding_schema: dict[str, Any] | None = None
    for path, (scope, phase, task, verified) in specs.items():
        if not path.exists():
            if verified and metadata_required:
                errors.append(f"verified {scope} has no canonical audit artifact: {path.relative_to(d)}")
            continue
        text = read_text_if_exists(path)
        if not text.startswith("---"):
            if verified and metadata_required:
                errors.append(
                    f"verified {scope} requires protocol 1.3 audit metadata: {path.relative_to(d)}"
                )
            continue
        try:
            metadata = parse_audit_text(text, str(path))
            if audit_schema is None or finding_schema is None:
                audit_schema, finding_schema = load_audit_schemas()
            schema_errors = validate_schema_value(
                metadata,
                audit_schema,
                f"canonical audit {path.relative_to(d)}",
                {"finding": finding_schema},
            )
            errors.extend(schema_errors)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if schema_errors:
            continue
        errors.extend(audit_finding_id_errors(metadata.get("findings", []) or []))
        if metadata.get("scope") != scope:
            errors.append(f"canonical audit {path.relative_to(d)} scope must be {scope}")
        if "phase" in metadata:
            actual_phase = phase_key(metadata.get("phase")) if metadata.get("phase") is not None else None
            if actual_phase != phase:
                errors.append(f"canonical audit {path.relative_to(d)} phase must be {phase or '<none>'}")
        if "task" in metadata and metadata.get("task") != task:
            errors.append(f"canonical audit {path.relative_to(d)} task must be {task or '<none>'}")
        if (
            expected.get("command") == "audit"
            and expected.get("mode") == "initial"
            and expected.get("scope") == scope
            and (expected.get("phase") or None) == (phase or None)
            and (expected.get("work_item") or None) == (task or None)
            and metadata.get("mode") != expected.get("mode")
        ):
            errors.append(
                f"canonical audit {path.relative_to(d)} mode must match lifecycle {expected.get('mode')}"
            )
        if metadata.get("mode") == "closure":
            domain = str(state.get("domain"))
            prior_severities = recorded_audit_provenance(
                root, domain, state, scope, phase, task, work_docs=docs
            )
            if prior_severities is None:
                errors.append(closure_without_provenance_error(domain, scope, phase, task))
            closure_errors, _closure_by_id, active_ids = audit_closure_contract(metadata, prior_severities)
            errors.extend(closure_errors)
        else:
            active_ids = {str(finding["id"]) for finding in metadata.get("findings", [])}
        severities = [
            str(finding["severity"])
            for finding in metadata.get("findings", [])
            if str(finding["id"]) in active_ids
        ]
        errors.extend(audit_verdict_errors(audit_schema, str(metadata.get("verdict")), severities))
        if verified and metadata_required and metadata.get("verdict") != "pass":
            errors.append(f"verified {scope} requires a pass verdict in {path.relative_to(d)}")
    return errors


def collect_validation(
    root: Path,
    domain: str,
    *,
    state_override: dict[str, Any] | None = None,
    work_overrides: dict[Path, dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """Structural findings for a domain, so state transitions can gate on them too."""
    d = domain_dir(root, domain)
    errors: list[str] = []
    warnings: list[str] = []
    config_errors, config_warnings, _newer_config = config_protocol_diagnostics(root)
    errors.extend(config_errors)
    warnings.extend(config_warnings)
    state = state_override if state_override is not None else load_yaml(d / "STATE.yaml", {}) or {}
    validate_state(state, d, errors, warnings)
    floor = config_protocol_floor(root)
    state_version = parsed_protocol_version(state.get("protocol_version"))
    runtime_version = parsed_protocol_version(PROTOCOL_VERSION)
    if (
        floor is not None
        and floor <= runtime_version
        and state_version is not None
        and state_version < floor
    ):
        errors.append(
            f"STATE protocol_version {state.get('protocol_version')} is older than the project's "
            f".devflow/config.yaml protocol_version {runtime_config(root).get('protocol_version')}"
        )
    decision_errors, open_decisions = decision_state_errors(state, d)
    errors.extend(decision_errors)

    docs, index, duplicates = load_work_index(d)
    if work_overrides:
        docs.update(work_overrides)
        docs, index, duplicates = index_work_docs(docs)
    for dup in duplicates:
        errors.append(f"Duplicate WORK id: {dup}")
    all_ids = set(index)
    unresolved = set(str(x) for x in state.get("unresolved_decisions", []) or []) | open_decisions
    phases = normalized_phases(state)
    errors.extend(phase_work_contract_errors(d, state, docs))
    if effective_workflow_type(state) == "delivery":
        errors.extend(delivery_placeholder_errors(d, state, docs))

    plan_review_state = effective_plan_review(state)
    integration_state = state.get("integration", {}) or {}
    if (
        effective_workflow_type(state) == "delivery"
        and plan_review_state.get("required")
        and plan_review_state.get("status") != "verified"
        and integration_state.get("status") != "pending"
    ):
        errors.append(
            f"plan review is pending but integration status {integration_state.get('status')} indicates an applied audit lifecycle"
        )

    plan_review = state.get("plan_review") if isinstance(state.get("plan_review"), dict) else {}
    remediation_ids = plan_review.get("remediation_work_ids", [])
    if isinstance(remediation_ids, list):
        for remediation_id in remediation_ids:
            if isinstance(remediation_id, str) and remediation_id.strip() and remediation_id not in all_ids:
                errors.append(f"plan_review: unknown remediation WORK id {remediation_id}")

    for path, doc in docs.items():
        file_errors, file_warnings = validate_work_file(path, doc, index, unresolved)
        errors.extend(file_errors)
        warnings.extend(file_warnings)

    # A phase cannot be verified while its own work is unfinished.
    for key, phase_state in phases.items():
        if phase_state.get("status") != "verified":
            continue
        work_file = d / phase_state.get("work_file", f"work/phase-{key}.yaml")
        doc = docs.get(work_file) or load_yaml(work_file, {}) or {}
        open_items = [str(i.get("id")) for i in (doc.get("items", []) or []) if i.get("status") not in TERMINAL_STATUSES]
        if open_items:
            errors.append(f"Phase {key} is verified but has open work: {', '.join(open_items)}")
    if integration_state.get("status") == "verified":
        if effective_workflow_type(state) == "delivery" and not phases:
            errors.append("integration is verified but delivery has no phases")
        unfinished = [k for k, p in phases.items() if p.get("status") != "verified"]
        if unfinished:
            errors.append(f"integration is verified but phases are not: {', '.join(sorted(unfinished))}")

    errors.extend(audit_artifact_contract_errors(root, d, state, docs))

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, stack: list[str]):
        if node in visiting:
            errors.append("Dependency cycle: " + " -> ".join(stack + [node]))
            return
        if node in visited or node not in index:
            return
        visiting.add(node)
        stack.append(node)
        for dep in index[node][1].get("dependencies", []) or []:
            dfs(str(dep), stack)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in list(index):
        dfs(node, [])

    prd_path = d / "PRD.md"
    prd_ids = set(REQ_PATTERN.findall(prd_path.read_text(encoding="utf-8"))) if prd_path.exists() else set()
    if prd_ids:
        for item_id, (_, item) in index.items():
            for req in (item.get("origin") or {}).get("requirements", []) or []:
                if str(req) not in prd_ids:
                    warnings.append(f"{item_id}: requirement id not found verbatim in PRD: {req}")

    return errors, warnings


def validate(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    if not d.exists():
        print(f"Domain not initialized: {args.domain}", file=sys.stderr)
        return 2
    errors, warnings = collect_validation(root, args.domain)
    _, index, _ = load_work_index(d)

    print(f"DevFlow validation: {args.domain}")
    for warning in warnings:
        print(f"WARN: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    print(f"errors={len(errors)} warnings={len(warnings)} work_items={len(index)}")
    return 1 if errors else 0


def canonical_audit_path(
    root: Path,
    domain: str,
    state: dict[str, Any],
    scope: str,
    phase: str | None,
    work_item: str | None,
) -> Path:
    d = domain_dir(root, domain)
    if scope == "plan":
        relative = effective_plan_review(state)["audit_file"]
    elif scope == "work":
        if work_item is None:
            raise ValueError("Work audit apply requires --task <WORK-ID>")
        _, _, item = find_item(root, domain, work_item)
        relative = effective_review(item)["audit_file"]
    elif scope == "phase":
        if phase is None:
            raise ValueError("Phase audit apply requires --phase <PHASE>")
        key = phase_key(phase)
        phase_state = normalized_phases(state).get(key)
        if phase_state is None:
            raise ValueError(f"Phase audit phase does not exist: {key}")
        relative = phase_state.get("audit_file", f"audits/phase-{key}.md")
    else:
        relative = (state.get("integration") or {}).get("audit_file", "audits/integration.md")
    path = (d / str(relative)).resolve()
    try:
        path.relative_to(d.resolve())
    except ValueError as exc:
        raise ValueError(f"Canonical audit file escapes the domain directory: {relative}") from exc
    return path


def known_canonical_finding_ids(
    d: Path,
    state: dict[str, Any],
    work_index: dict[str, tuple[Path, dict[str, Any]]],
    audit_schema: dict[str, Any],
    references: dict[str, dict[str, Any]],
) -> set[str]:
    relative_paths = {
        str(effective_plan_review(state)["audit_file"]),
        str((state.get("integration") or {}).get("audit_file", "audits/integration.md")),
    }
    relative_paths.update(
        str(phase_state.get("audit_file", f"audits/phase-{phase_key_value}.md"))
        for phase_key_value, phase_state in normalized_phases(state).items()
    )
    relative_paths.update(
        str(effective_review(item)["audit_file"])
        for _, item in work_index.values()
    )

    finding_ids: set[str] = set()
    domain_path = d.resolve()
    for relative in relative_paths:
        path = (d / relative).resolve()
        if not path.is_relative_to(domain_path) or not path.exists():
            continue
        try:
            metadata = parse_audit_metadata(path)
        except (OSError, UnicodeError, ValueError):
            continue
        if validate_schema_value(metadata, audit_schema, "canonical audit", references):
            continue
        findings = metadata.get("findings", []) or []
        if not isinstance(findings, list):
            continue
        finding_ids.update(
            str(finding["id"])
            for finding in findings
            if isinstance(finding, dict) and isinstance(finding.get("id"), str) and finding["id"].strip()
        )
    return finding_ids


def audit_verdict_errors(
    audit_schema: dict[str, Any],
    verdict: str,
    severities: list[str],
) -> list[str]:
    rubric = (audit_schema.get("verdict") or {}).get(verdict, {})
    forbidden = sorted(set(severities) & set(rubric.get("forbidden_severities", []) or []))
    required = set(rubric.get("required_severities", []) or [])
    errors = []
    if forbidden:
        errors.append(f"verdict {verdict} forbids finding severity: {', '.join(forbidden)}")
    if required and not required.intersection(severities):
        errors.append(f"verdict {verdict} requires finding severity: {', '.join(sorted(required))}")
    return errors


def audit_finding_id_errors(findings: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for finding in findings:
        finding_id = str(finding["id"])
        if finding_id in seen:
            duplicates.add(finding_id)
        seen.add(finding_id)
    return [f"duplicate audit finding id: {finding_id}" for finding_id in sorted(duplicates)]


def audit_closure_contract(
    metadata: dict[str, Any],
    prior_severities: dict[str, str] | None,
) -> tuple[list[str], dict[str, dict[str, Any]], set[str]]:
    findings = metadata.get("findings", []) or []
    current_ids = {str(finding["id"]) for finding in findings}
    severity_by_id = {str(finding["id"]): str(finding["severity"]) for finding in findings}
    closure = metadata.get("closure", []) or []
    closure_by_id = {str(entry["finding_id"]): entry for entry in closure}
    errors: list[str] = []
    if len(closure_by_id) != len(closure):
        errors.append("closure contains duplicate finding_id entries")
    if prior_severities is None:
        return errors, closure_by_id, current_ids

    prior_ids = set(prior_severities)
    current_only_ids = current_ids - prior_ids
    missing_findings = sorted(prior_ids - current_ids)
    missing = sorted(prior_ids - set(closure_by_id))
    unknown = sorted(set(closure_by_id) - prior_ids)
    if missing_findings:
        errors.append(f"closure omits prior findings from current metadata: {', '.join(missing_findings)}")
    if missing:
        errors.append(f"closure does not cover prior findings: {', '.join(missing)}")
    if unknown:
        errors.append(f"closure covers findings that were not in the initial audit: {', '.join(unknown)}")

    reopened_ids: set[str] = set()
    for finding_id, entry in closure_by_id.items():
        reopened_as = [str(value) for value in entry.get("reopened_as", []) or []]
        if entry.get("outcome") == "reopened":
            if not reopened_as:
                errors.append(f"closure {finding_id}: reopened requires reopened_as")
            reopened_ids.update(reopened_as)
            for reopened_id in reopened_as:
                if reopened_id not in current_ids:
                    errors.append(f"closure {finding_id}: reopened finding does not exist: {reopened_id}")
        elif reopened_as:
            errors.append(f"closure {finding_id}: reopened_as is only valid for outcome reopened")
    invalid_reopened = sorted(reopened_ids - current_only_ids)
    if invalid_reopened:
        errors.append(f"closure reopened_as must reference current-only findings: {', '.join(invalid_reopened)}")

    # A finding that is still open, or reopened into a new finding, cannot pass the verdict rubric
    # below the severity recorded when the audit that raised it was applied. Rank comes from the
    # finding schema (SEVERITY_RANK), so the schema stays the trust anchor. An auditor may raise a
    # severity; only lowering an active finding is refused. resolved and accepted_risk are exempt
    # because they leave active_ids, so their severity never reaches the rubric.
    def below_recorded(current: str | None, recorded: str | None) -> bool:
        return (
            current in SEVERITY_RANK
            and recorded in SEVERITY_RANK
            and SEVERITY_RANK[current] > SEVERITY_RANK[recorded]
        )

    for finding_id, entry in closure_by_id.items():
        recorded = prior_severities.get(finding_id)
        if entry.get("outcome") == "still_open" and below_recorded(severity_by_id.get(finding_id), recorded):
            errors.append(
                f"closure {finding_id}: still_open severity {severity_by_id.get(finding_id)} "
                f"is lower than the recorded severity {recorded}"
            )
        if entry.get("outcome") == "reopened":
            for reopened_id in (str(value) for value in entry.get("reopened_as", []) or []):
                if below_recorded(severity_by_id.get(reopened_id), recorded):
                    errors.append(
                        f"closure {finding_id}: reopened finding {reopened_id} severity "
                        f"{severity_by_id.get(reopened_id)} is lower than the recorded severity {recorded}"
                    )

    active_ids = current_only_ids | {
        finding_id
        for finding_id, entry in closure_by_id.items()
        if entry.get("outcome") == "still_open"
    }
    return errors, closure_by_id, active_ids


def validate_audit_metadata(
    root: Path,
    domain: str,
    state: dict[str, Any],
    metadata: dict[str, Any],
    *,
    scope: str,
    mode: str,
    phase: str | None,
    work_item: str | None,
) -> list[str]:
    audit_schema, finding_schema = load_audit_schemas()
    references = {"finding": finding_schema}
    errors = validate_schema_value(metadata, audit_schema, "audit", references)
    if errors:
        return errors

    if metadata["scope"] != scope:
        errors.append(f"audit.scope must match requested scope {scope!r}")
    if metadata["mode"] != mode:
        errors.append(f"audit.mode must match requested mode {mode!r}")
    if state.get("baseline_sha") and metadata["baseline_sha"] != state.get("baseline_sha"):
        errors.append("audit.baseline_sha does not match STATE baseline_sha")
    head = current_sha(root)
    if head and metadata["target_sha"] != head:
        errors.append("audit.target_sha does not match current HEAD")

    findings = metadata["findings"]
    finding_ids = [str(finding["id"]) for finding in findings]
    errors.extend(audit_finding_id_errors(findings))

    d = domain_dir(root, domain)
    work_docs, work_index, _ = load_work_index(d)

    closure = metadata.get("closure", []) or []
    closure_by_id: dict[str, dict[str, Any]] = {}
    active_ids = set(finding_ids)
    if mode == "closure":
        prior_severities = recorded_audit_provenance(root, domain, state, scope, phase, work_item, work_docs=work_docs)
        if prior_severities is None:
            errors.append(closure_without_provenance_error(domain, scope, phase, work_item))
        closure_errors, closure_by_id, active_ids = audit_closure_contract(metadata, prior_severities)
        errors.extend(closure_errors)
    elif closure:
        errors.append("initial audit closure must be empty")

    severities = [str(finding["severity"]) for finding in findings if str(finding["id"]) in active_ids]
    verdict = str(metadata["verdict"])
    errors.extend(audit_verdict_errors(audit_schema, verdict, severities))

    open_decisions, resolved_decisions, decision_errors = decision_document_records(d / "DECISIONS.md")
    errors.extend(decision_errors)
    finding_by_id = {str(finding["id"]): finding for finding in findings}
    disposition_contracts = finding_schema["classification"]["disposition"]
    for finding in findings:
        disposition = finding["disposition"]
        classification = str(finding["classification"])
        contract = disposition_contracts[classification]
        if disposition["action"] != contract["action"]:
            errors.append(
                f"{finding['id']}: {classification} requires disposition.action={contract['action']}"
            )
        for field in ["work_ids", "decision_ids"]:
            values = disposition[field]
            if contract[field] == "required" and not values:
                errors.append(f"{finding['id']}: {classification} requires at least one {field}")
            elif contract[field] == "empty" and values:
                errors.append(f"{finding['id']}: {classification} requires empty {field}")
        for linked_work in disposition["work_ids"]:
            target = work_index.get(str(linked_work))
            if target is None:
                errors.append(f"{finding['id']}: linked WORK does not exist: {linked_work}")
                continue
            work_item_doc = target[1]
            work_origin = work_item_doc.get("origin") or {}
            work_findings = [
                str(value)
                for value in (work_origin.get("findings", []) or [])
            ] if isinstance(work_origin, dict) else []
            if str(finding["id"]) not in work_findings:
                errors.append(
                    f"{finding['id']}: linked WORK {linked_work} origin.findings does not include {finding['id']}"
                )
            expected_kind = contract.get("work_kind")
            if expected_kind and work_item_doc.get("kind") != expected_kind:
                errors.append(
                    f"{finding['id']}: linked WORK {linked_work} must use kind {expected_kind}, not {work_item_doc.get('kind')}"
                )
        for decision_id in disposition["decision_ids"]:
            if str(decision_id) not in open_decisions:
                errors.append(
                    f"{finding['id']}: linked decision {decision_id} must be an open DECISIONS.md record with at least two nonblank options"
                )

    linked_work_ids = {
        str(work_id)
        for finding in findings
        for work_id in finding["disposition"]["work_ids"]
    }
    if scope == "integration":
        relevant_work_paths = {d / (state.get("integration") or {}).get("work_file", "work/integration.yaml")}
    elif scope == "phase" and phase is not None:
        phase_state = normalized_phases(state).get(phase_key(phase), {})
        relevant_work_paths = {d / phase_state.get("work_file", f"work/phase-{phase_key(phase)}.yaml")}
    elif scope == "work" and work_item is not None and work_item in work_index:
        relevant_work_paths = {work_index[work_item][0]}
    else:
        relevant_work_paths = set(work_docs)

    known_finding_ids = set(finding_ids) | known_canonical_finding_ids(
        d,
        state,
        work_index,
        audit_schema,
        references,
    )
    for work_id, (work_path, work_item_doc) in work_index.items():
        if work_path not in relevant_work_paths and work_id not in linked_work_ids:
            continue
        work_origin = work_item_doc.get("origin") or {}
        work_findings = {
            str(value)
            for value in (work_origin.get("findings", []) or [])
        } if isinstance(work_origin, dict) else set()
        unknown_findings = sorted(work_findings - known_finding_ids)
        if unknown_findings:
            errors.append(
                f"{work_id}: origin.findings references finding absent from audit: {', '.join(unknown_findings)}"
            )
        for finding_id in sorted(work_findings & set(finding_ids)):
            finding = finding_by_id[finding_id]
            disposition = finding["disposition"]
            if work_id not in {str(value) for value in disposition["work_ids"]}:
                errors.append(f"{work_id}: origin.findings includes {finding_id}, but its audit disposition does not link this WORK")
            if finding["classification"] == "DECISION_REQUIRED" and work_item_doc.get("status") == "ready":
                errors.append(f"{finding_id}: DECISION_REQUIRED finding cannot generate ready WORK {work_id}")

    if mode == "closure":
        for finding_id, entry in closure_by_id.items():
            finding = finding_by_id.get(finding_id)
            if finding is None:
                continue
            outcome = entry["outcome"]
            if outcome == "accepted_risk":
                decision_ids = [str(value) for value in finding["disposition"]["decision_ids"]]
                resolved = [value for value in decision_ids if value in resolved_decisions and value not in (state.get("unresolved_decisions") or [])]
                if not resolved:
                    errors.append(f"closure {finding_id}: accepted_risk requires a resolved decision")
            for linked_work in finding["disposition"]["work_ids"]:
                target = work_index.get(str(linked_work))
                if target and target[1].get("status") not in TERMINAL_STATUSES:
                    errors.append(f"closure {finding_id}: remediation WORK {linked_work} is not terminal")
                elif target and target[1].get("status") == "done" and not review_satisfied(target[1]):
                    errors.append(f"closure {finding_id}: remediation WORK {linked_work} still requires review")
    return errors


def audit_apply(args: argparse.Namespace) -> int:
    root = repo_root()
    path = state_path(root, args.domain)
    state = load_yaml(path, {}) or {}
    expected = compute_next_action(root, args.domain, state)
    requested, request_error = render_request(root, args, expected)
    expected_request = {key: expected.get(key) for key in requested}
    if request_error or requested != expected_request:
        return reject_render(args.domain, requested, expected_request, request_error)

    audit_path = canonical_audit_path(root, args.domain, state, args.scope, args.phase, args.task)
    if not audit_path.exists():
        return reject_transition("audit", "be applied", [f"canonical audit file not found: {audit_path}"])
    try:
        metadata = parse_audit_metadata(audit_path)
    except ValueError as exc:
        return reject_transition("audit", "be applied", [str(exc)])
    if effective_workflow_type(state) == "audit_remediation" and args.mode == "initial":
        d = domain_dir(root, args.domain)
        contract_errors = required_markdown_section_errors(d / "PRD.md", "PRD.audit-remediation.md")
        contract_errors.extend(required_markdown_section_errors(d / "PLAN.md", "PLAN.audit-remediation.md"))
        if contract_errors:
            return reject_transition("audit", "be applied", contract_errors)
    errors = validate_audit_metadata(
        root,
        args.domain,
        state,
        metadata,
        scope=args.scope,
        mode=args.mode,
        phase=args.phase,
        work_item=args.task,
    )
    if errors:
        return reject_transition("audit", "be applied", errors)

    prospective = copy.deepcopy(state)
    findings = metadata["findings"]
    closure_entries = metadata.get("closure", []) or []
    closure_ids = {str(entry["finding_id"]) for entry in closure_entries}
    follow_up = findings if args.mode == "initial" else [finding for finding in findings if str(finding["id"]) not in closure_ids]
    still_open_ids = {str(entry["finding_id"]) for entry in closure_entries if entry["outcome"] == "still_open"}
    has_stop = any(
        finding["disposition"]["action"] == "stop"
        for finding in findings
        if args.mode == "initial" or str(finding["id"]) not in closure_ids or str(finding["id"]) in still_open_ids
    )
    generated_work = list(dict.fromkeys(str(work_id) for finding in follow_up for work_id in finding["disposition"]["work_ids"]))
    new_decisions = list(
        dict.fromkeys(
            str(decision_id)
            for finding in follow_up
            if finding["disposition"]["action"] == "decision"
            for decision_id in finding["disposition"]["decision_ids"]
        )
    )
    unresolved = list(dict.fromkeys([str(value) for value in prospective.get("unresolved_decisions", []) or []] + new_decisions))
    prospective["unresolved_decisions"] = unresolved
    closes_scope = metadata["verdict"] == "pass" and not generated_work and not new_decisions and not has_stop
    work_overrides: dict[Path, dict[str, Any]] = {}
    # Machine-owned closure provenance: the finding set a later closure at this scope compares
    # against. It is written for both initial and closure modes, but only after this apply's own
    # validation runs, so a closure is checked against the PRIOR applied audit, never the record
    # this apply is about to write. `provenance_target` is the dict that receives it.
    provenance = {"findings": audit_provenance_findings(metadata)}
    provenance_target: dict[str, Any]

    if args.scope == "plan":
        review = effective_plan_review(prospective)
        review["status"] = "verified" if closes_scope else ("blocked" if has_stop else ("remediation" if generated_work else "pending"))
        if generated_work:
            review["remediation_work_ids"] = generated_work
        else:
            review.pop("remediation_work_ids", None)
        prospective["plan_review"] = review
        provenance_target = review
    elif args.scope == "work":
        work_path, work_doc, _ = find_item(root, args.domain, str(args.task))
        next_doc = copy.deepcopy(work_doc)
        next_item_doc = next(item for item in next_doc.get("items", []) if str(item.get("id")) == str(args.task))
        review = effective_review(next_item_doc)
        if closes_scope:
            review["status"] = "verified"
        elif generated_work and not has_stop:
            review["status"] = "remediation"
            review["remediation_work_ids"] = generated_work
        else:
            review["status"] = "blocked"
        next_item_doc["review"] = review
        work_overrides[work_path] = next_doc
        provenance_target = review
    elif args.scope == "phase":
        key = phase_key(args.phase)
        raw = raw_phase_key(prospective, key)
        phase_entry_doc = prospective["phases"][raw if raw is not None else key]
        phase_entry_doc["status"] = "verified" if closes_scope else ("remediation" if generated_work and not has_stop else "blocked")
        provenance_target = phase_entry_doc
    else:
        integration = dict(prospective.get("integration") or {})
        integration["status"] = "verified" if closes_scope else ("blocked" if has_stop else "remediation")
        prospective["integration"] = integration
        provenance_target = integration
    if args.mode == "closure" and not closes_scope:
        prospective["next_action"] = {}

    if closes_scope and args.scope == "plan" and not (domain_dir(root, args.domain) / "PLAN.md").exists():
        errors.append(f"PLAN.md not found: {domain_dir(root, args.domain) / 'PLAN.md'}")
    if closes_scope and args.scope == "phase":
        docs, _, _ = load_work_index(domain_dir(root, args.domain))
        errors.extend(phase_verify_errors(root, args.domain, prospective, phase_key(args.phase), docs))
    if closes_scope and args.scope == "integration":
        docs, _, _ = load_work_index(domain_dir(root, args.domain))
        errors.extend(integration_verify_errors(root, args.domain, prospective, docs))
    project_state(root, args.domain, prospective, work_overrides)
    validation_errors, _ = collect_validation(
        root,
        args.domain,
        state_override=prospective,
        work_overrides=work_overrides,
    )
    errors.extend(f"validation: {error}" for error in validation_errors)
    if errors:
        return reject_transition("audit", "be applied", errors)

    # Validation passed: now record the provenance this apply establishes for a later closure.
    provenance_target["audit_provenance"] = provenance

    documents: dict[Path, Any] = dict(work_overrides)
    documents[path] = prospective
    commit_yaml_transaction(documents)
    applied = prospective
    next_action = applied.get("next_action") or {}
    print(f"audit applied: {args.scope} {args.mode}")
    print(f"verdict: {metadata['verdict']}")
    print(f"findings: {len(findings)}")
    print(f"generated WORK: {', '.join(generated_work) or '<none>'}")
    print(f"unresolved_decisions: {', '.join(unresolved) or '<none>'}")
    print(f"next_action: {next_action.get('command')}" + (f" {next_action.get('work_item')}" if next_action.get("work_item") else ""))
    return 0


def print_section(title: str, body: str) -> None:
    print(f"\n---\n\n<!-- {title} -->")
    print(body.rstrip())


def read_text_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def origin_ids(item: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    origin = item.get("origin") or {}
    return (
        [str(value) for value in origin.get("requirements", []) or []],
        [str(value) for value in origin.get("plan_items", []) or []],
        [str(value) for value in origin.get("findings", []) or []],
    )


def exact_id_pattern(value: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9-]){re.escape(value)}(?![A-Za-z0-9-])")


def extract_markdown_context(path: Path, ids: list[str]) -> list[str]:
    lines = read_text_if_exists(path).splitlines()
    ranges: list[tuple[int, int]] = []
    missing: list[str] = []

    for value in ids:
        pattern = exact_id_pattern(value)
        headings = []
        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s+", line)
            if match and pattern.search(line):
                headings.append((index, len(match.group(1))))
        if headings:
            for start, level in headings:
                end = len(lines)
                for index in range(start + 1, len(lines)):
                    match = re.match(r"^(#{1,6})\s+", lines[index])
                    if match and len(match.group(1)) <= level:
                        end = index
                        break
                ranges.append((start, end))
            continue

        matches = [index for index, line in enumerate(lines) if pattern.search(line)]
        if not matches:
            missing.append(f"{value}: not found verbatim in {path.name}")
            continue
        ranges.extend((max(0, index - 2), min(len(lines), index + 3)) for index in matches)

    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return ["\n".join(lines[start:end]).rstrip() for start, end in merged] + missing


def render_markdown_context(title: str, path: Path, ids: list[str]) -> None:
    print(f"\n## {title}")
    context = extract_markdown_context(path, ids)
    print("\n\n".join(context) if context else "<no referenced IDs>")


def render_markdown_file(title: str, path: Path) -> None:
    print(f"\n## {title}")
    print(read_text_if_exists(path).rstrip() or f"{path.name}: not found")


def render_yaml_context(title: str, data: Any) -> None:
    print(f"\n## {title}")
    print("```yaml")
    print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip())
    print("```")


def render_closure_audit(title: str, path: Path, mode: str) -> None:
    if mode == "closure" and path.exists():
        render_markdown_file(title, path)


def render_request(root: Path, args: argparse.Namespace, expected: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    role = args.render_command
    if role == "plan":
        return {"command": role}, None
    if role == "run":
        item_id = args.task or (expected.get("work_item") if expected.get("command") == "run" else None)
        if args.task:
            try:
                find_item(root, args.domain, args.task)
            except KeyError:
                return {"command": role, "work_item": item_id}, f"Unknown WORK item: {args.task}"
        return {"command": role, "work_item": item_id}, None

    phase = phase_key(args.phase) if args.phase else None
    if args.scope == "work" and args.task:
        try:
            path, doc, _ = find_item(root, args.domain, args.task)
        except KeyError:
            request = {"command": role, "scope": args.scope, "mode": args.mode, "phase": phase, "work_item": args.task}
            return request, f"Unknown WORK item: {args.task}"
        if phase is None:
            item_phase_key = item_phase(path, doc)
            phase = None if item_phase_key == "integration" else item_phase_key
    return {"command": role, "scope": args.scope, "mode": args.mode, "phase": phase, "work_item": args.task}, None


def reject_render(domain: str, requested: dict[str, Any], expected: dict[str, Any], reason: str | None = None) -> int:
    print(f"DevFlow error: {reason or 'render request does not match the lifecycle next action'}", file=sys.stderr)
    print(f"requested: {json.dumps(requested, sort_keys=True)}", file=sys.stderr)
    print(f"expected: {json.dumps(expected, sort_keys=True)}", file=sys.stderr)
    print(f"Run 'devflow status {domain}' to inspect the current next action.", file=sys.stderr)
    return 2


def render(args: argparse.Namespace) -> int:
    root = repo_root()
    d = domain_dir(root, args.domain)
    role = args.render_command
    state = load_yaml(state_path(root, args.domain), {}) or {}
    expected = compute_next_action(root, args.domain, state)
    requested, error = render_request(root, args, expected)
    expected_request = {key: expected.get(key) for key in requested}
    if error or requested != expected_request:
        return reject_render(args.domain, requested, expected_request, error)
    state = refresh_state(root, args.domain)

    print((plugin_root() / "core" / "prompts" / f"{role}.md").read_text(encoding="utf-8").rstrip())

    print("\n## Runtime context")
    print(f"- repository: {root}")
    print(f"- domain: {args.domain}")
    print(f"- PRD: {d / 'PRD.md'}")
    print(f"- PLAN: {d / 'PLAN.md'}")
    print(f"- STATE: {d / 'STATE.yaml'}")
    print(f"- DECISIONS: {d / 'DECISIONS.md'}")
    print(f"- PITFALLS: {d / 'PITFALLS.md'}")
    print(f"- baseline_sha: {state.get('baseline_sha')}")
    print(f"- target_sha: {state.get('target_sha')}")
    print(f"- risk_profile: {state.get('risk_profile')}")
    print(f"- unresolved_decisions: {', '.join(state.get('unresolved_decisions', []) or []) or '<none>'}")

    if role == "audit":
        phases = normalized_phases(state)
        print(f"- audit_scope: {args.scope}")
        print(f"- audit_mode: {args.mode}")
        if args.mode == "closure":
            prior = recorded_audit_provenance(root, args.domain, state, args.scope, args.phase, args.task)
            print(f"- prior_findings: {', '.join(sorted(prior)) if prior else '<none recorded>'}")
        if args.scope == "plan":
            review = effective_plan_review(state)
            print(f"- current_head: {current_sha(root) or '<none>'}")
            print(f"- audit_file: {d / review['audit_file']}")
            render_markdown_file("Approved PRD", d / "PRD.md")
            render_markdown_file("Current PLAN", d / "PLAN.md")
            render_yaml_context("Plan review metadata", review)
        elif args.scope == "work":
            if not args.task:
                print("Work audit requires --task <WORK-ID>", file=sys.stderr)
                return 2
            path, doc, item = find_item(root, args.domain, args.task)
            review = effective_review(item)
            audit_path = d / review["audit_file"]
            print(f"- work_item: {item.get('id')}")
            print(f"- work_phase: {item_phase(path, doc)}")
            print(f"- work_risk: {(item.get('risk') or {}).get('level')}")
            print(f"- work_origin_requirements: {', '.join(str(x) for x in ((item.get('origin') or {}).get('requirements') or [])) or '<none>'}")
            print(f"- work_origin_plan_items: {', '.join(str(x) for x in ((item.get('origin') or {}).get('plan_items') or [])) or '<none>'}")
            print(f"- work_evidence_commit: {(item.get('evidence') or {}).get('commit') or '<none>'}")
            print(f"- work_changed_files: {', '.join((item.get('evidence') or {}).get('changed_files') or []) or '<none>'}")
            print(f"- work_verification_evidence: {', '.join((item.get('evidence') or {}).get('commands') or []) or '<none>'}")
            print(f"- audit_file: {audit_path}")
            print(f"- current_head: {current_sha(root) or '<none>'}")
            print("\n## Selected WORK item")
            print("```yaml")
            print(yaml.safe_dump(item, sort_keys=False, allow_unicode=True).rstrip())
            print("```")
            requirements, plan_items, _ = origin_ids(item)
            render_markdown_context("Relevant PRD context", d / "PRD.md", requirements)
            render_markdown_context("Relevant PLAN context", d / "PLAN.md", plan_items)
            render_yaml_context("Implementation evidence", item.get("evidence") or {})
            render_closure_audit("Existing work audit", audit_path, args.mode)
        elif args.scope == "phase":
            if not args.phase:
                print("Phase audit requires --phase <PHASE>", file=sys.stderr)
                return 2
            key = phase_key(args.phase)
            ps = phases.get(key)
            if ps is None:
                print(f"Phase audit phase does not exist: {key}", file=sys.stderr)
                return 2
            print(f"- phase: {key}")
            print(f"- phase_base_sha: {ps.get('base_sha') or '<unset>'}")
            print(f"- phase_head_sha: {ps.get('head_sha') or '<unset>'}")
            print(f"- diff_range: {ps.get('diff_range') or '<unset — run devflow phase ref before auditing>'}")
            print(f"- work_file: {d / ps.get('work_file', f'work/phase-{key}.yaml')}")
            print(f"- audit_file: {d / ps.get('audit_file', f'audits/phase-{key}.md')}")
            work_path = d / ps.get("work_file", f"work/phase-{key}.yaml")
            audit_path = d / ps.get("audit_file", f"audits/phase-{key}.md")
            work_doc = load_yaml(work_path, {}) or {}
            items = list(work_doc.get("items", []) or [])
            requirements = list(dict.fromkeys(requirement for item in items for requirement in origin_ids(item)[0]))
            plan_items = list(dict.fromkeys(plan_item for item in items for plan_item in origin_ids(item)[1]))
            render_yaml_context("Phase WORK YAML", work_doc)
            render_markdown_context("Relevant PRD context", d / "PRD.md", requirements)
            render_markdown_context("Relevant PLAN context", d / "PLAN.md", plan_items)
            render_closure_audit("Existing phase audit", audit_path, args.mode)
        elif args.scope == "integration":
            integ = state.get("integration", {}) or {}
            print(f"- diff_range: {state.get('baseline_sha')}...{state.get('target_sha')}")
            print(f"- work_file: {d / integ.get('work_file', 'work/integration.yaml')}")
            print(f"- audit_file: {d / integ.get('audit_file', 'audits/integration.md')}")
            render_markdown_file("Current PLAN", d / "PLAN.md")
            manifest = [
                {
                    "phase": key,
                    "status": entry.get("status"),
                    "work_file": entry.get("work_file", f"work/phase-{key}.yaml"),
                    "audit_file": entry.get("audit_file", f"audits/phase-{key}.md"),
                    "diff_range": entry.get("diff_range"),
                }
                for key, entry in sorted(phases.items())
            ]
            render_yaml_context("Phase manifest", manifest)
            print("\n## Phase audit artifacts")
            for entry in manifest:
                print(f"- {d / entry['audit_file']}")
            integration_work_path = d / integ.get("work_file", "work/integration.yaml")
            if integration_work_path.exists():
                render_yaml_context("Integration WORK YAML", load_yaml(integration_work_path, {}) or {})
            render_closure_audit("Existing integration audit", d / integ.get("audit_file", "audits/integration.md"), args.mode)
        else:
            raise ValueError(f"Unsupported audit scope: {args.scope}")

    if role == "run":
        item_id = args.task or (state.get("next_action", {}) or {}).get("work_item")
        if not item_id:
            print("\nNo executable WORK item is available.")
            return 1
        _, _, item = find_item(root, args.domain, item_id)
        print("\n## Selected WORK item")
        print("```yaml")
        print(yaml.safe_dump(item, sort_keys=False, allow_unicode=True).rstrip())
        print("```")
        requirements, plan_items, _ = origin_ids(item)
        render_markdown_context("Relevant PRD context", d / "PRD.md", requirements)
        render_markdown_context("Relevant PLAN context", d / "PLAN.md", plan_items)

    if role == "plan":
        render_markdown_file("Approved PRD", d / "PRD.md")

    for name in PROMPT_PROTOCOLS[role]:
        print_section(f"protocol/{name}.md", read_protocol(name))

    if role == "audit":
        extension = resolve_extension(root, state)
        print_section(f"extension: {extension}", extension.read_text(encoding="utf-8"))

    pitfalls = d / "PITFALLS.md"
    if pitfalls.exists():
        print_section(f"{args.domain}/PITFALLS.md", pitfalls.read_text(encoding="utf-8"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="devflow", description="State-based agent development protocol runtime")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init")
    sp.add_argument("domain")
    sp.add_argument("--risk", choices=sorted(RISK_LEVELS), default="medium")
    sp.add_argument("--workflow", choices=["delivery", "audit-remediation"], default="delivery")
    sp.add_argument("--extension", default="default")
    sp.add_argument("--prd")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=init_domain)

    sp = sub.add_parser("validate")
    sp.add_argument("domain")
    sp.set_defaults(func=validate)

    sp = sub.add_parser("status")
    sp.add_argument("domain")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=print_status)

    sp = sub.add_parser("next")
    sp.add_argument("domain")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=next_item)

    sp = sub.add_parser("work")
    worksub = sp.add_subparsers(dest="work_command", required=True)
    s = worksub.add_parser("start")
    s.add_argument("domain"); s.add_argument("item"); s.set_defaults(func=work_update)
    s = worksub.add_parser("done")
    s.add_argument("domain"); s.add_argument("item"); s.add_argument("--commit")
    s.add_argument("--changed-file", action="append", default=[])
    s.add_argument("--command", action="append", default=[])
    s.add_argument("--deviation", action="append", default=[])
    s.add_argument("--discovery", action="append", default=[])
    s.set_defaults(func=work_update)
    s = worksub.add_parser("block")
    s.add_argument("domain"); s.add_argument("item"); s.add_argument("--reason", required=True); s.set_defaults(func=work_update)
    s = worksub.add_parser("review")
    s.add_argument("domain"); s.add_argument("item"); s.add_argument("review_status", choices=["verified", "remediation", "blocked", "pending"])
    s.add_argument("--remediation-work", action="append", default=[])
    s.set_defaults(func=work_review)

    sp = sub.add_parser("phase")
    phasesub = sp.add_subparsers(dest="phase_command", required=True)
    s = phasesub.add_parser("set")
    s.add_argument("domain"); s.add_argument("phase"); s.add_argument("status", choices=sorted(PHASE_STATUSES)); s.set_defaults(func=set_phase)
    s = phasesub.add_parser("ref")
    s.add_argument("domain"); s.add_argument("phase")
    s.add_argument("--base", required=True); s.add_argument("--head", required=True)
    s.add_argument("--range", help="Explicit diff range, for stacks where base is not an ancestor of head")
    s.set_defaults(func=set_phase_ref)

    sp = sub.add_parser("plan-review")
    prsub = sp.add_subparsers(dest="plan_review_command", required=True)
    s = prsub.add_parser("set")
    s.add_argument("domain"); s.add_argument("status", choices=["pending", "verified", "skipped"]); s.set_defaults(func=set_plan_review)

    sp = sub.add_parser("integration")
    insub = sp.add_subparsers(dest="integration_command", required=True)
    s = insub.add_parser("set")
    s.add_argument("domain"); s.add_argument("status", choices=sorted(INTEGRATION_STATUSES)); s.set_defaults(func=set_integration)

    sp = sub.add_parser("decision")
    dsub = sp.add_subparsers(dest="decision_command", required=True)
    for name in ["add", "resolve"]:
        s = dsub.add_parser(name); s.add_argument("domain"); s.add_argument("decision"); s.set_defaults(func=decision_update)

    sp = sub.add_parser("audit")
    asub = sp.add_subparsers(dest="audit_command", required=True)
    s = asub.add_parser("apply")
    s.add_argument("domain")
    s.add_argument("--scope", choices=["plan", "work", "phase", "integration"], required=True)
    s.add_argument("--task")
    s.add_argument("--phase")
    s.add_argument("--mode", choices=["initial", "closure"], default="initial")
    s.set_defaults(func=audit_apply, render_command="audit")

    sp = sub.add_parser("render")
    rsub = sp.add_subparsers(dest="render_command", required=True)
    s = rsub.add_parser("plan"); s.add_argument("domain"); s.set_defaults(func=render)
    s = rsub.add_parser("run"); s.add_argument("domain"); s.add_argument("--task"); s.set_defaults(func=render)
    s = rsub.add_parser("audit"); s.add_argument("domain"); s.add_argument("--scope", choices=["plan", "work", "phase", "integration"], required=True); s.add_argument("--task"); s.add_argument("--phase"); s.add_argument("--mode", choices=["initial", "closure"], default="initial"); s.set_defaults(func=render)
    return p


def main() -> int:
    try:
        configure_work_schema()
        args = build_parser().parse_args()
        if args.func not in {validate, print_status}:
            config_errors, _config_warnings, newer_config = config_protocol_diagnostics(repo_root())
            if config_errors:
                for error in config_errors:
                    print(f"DevFlow error: {error}", file=sys.stderr)
                return 2
            if newer_config:
                value = runtime_config(repo_root()).get("protocol_version")
                print(
                    f"DevFlow error: newer config protocol {value} blocks artifact mutation; "
                    f"this runtime implements {PROTOCOL_VERSION}. Use status or validate with a compatible runtime.",
                    file=sys.stderr,
                )
                return 2
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except KeyError as exc:
        # str(KeyError) is the repr of its argument, which printed the message inside quotes.
        print(f"DevFlow error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"DevFlow error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
