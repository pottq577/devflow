#!/usr/bin/env python3
"""Check DevFlow's active documentation contracts without changing the repository.

This is a static documentation gate, not a substitute for a rendered-packet or
lifecycle test. Potentially duplicated policy prose is advisory by design.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


SKILLS = ("plan", "run", "audit", "status", "goal", "autopilot")
NULL_AUDIT_FIELDS = ("scope", "mode", "verdict", "baseline_sha", "target_sha", "diff_range")
EMPTY_AUDIT_FIELDS = ("verification", "findings", "closure")
ROLE_POINTERS = {
    "skills/plan/SKILL.md": ("work-item-contract.md", "finalization.md", "render plan"),
    "skills/run/SKILL.md": ("delivery-artifacts.md", "finalization.md", "render run", "start_sha"),
    "skills/audit/SKILL.md": ("audit-core.md", "risk-policy.md", "audit apply"),
    "skills/status/SKILL.md": ("status", "next"),
    "skills/goal/SKILL.md": ("host-telemetry.md", "session"),
    "skills/autopilot/SKILL.md": ("skills/goal/SKILL.md", "step-start"),
    "core/prompts/plan.md": ("work-item-contract.md", "finalization.md"),
    "core/prompts/run.md": ("delivery-artifacts.md", "finalization.md", "in_progress", "start_sha"),
    "core/prompts/audit.md": ("audit-core.md", "audit apply"),
    "core/prompts/finalize-role.md": ("finalization.md", "Newman precedes ELI5"),
}
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
LOCAL_REFERENCE = re.compile(r"`((?:core|skills|plugins/devflow)/[A-Za-z0-9_./*-]+\.(?:md|yaml|json|py))`")
POLICY_LINE_MIN = 110


def visible_prose(text: str) -> str:
    """Mask fenced example blocks; preserve line numbers for diagnostic links."""
    masked = []
    fence_char: str | None = None
    fence_size = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence_char is None:
                fence_char, fence_size = token[0], len(token)
            elif token[0] == fence_char and len(token) >= fence_size:
                fence_char, fence_size = None, 0
            masked.append("\n" if line.endswith("\n") else "")
        elif fence_char is not None:
            masked.append("\n" if line.endswith("\n") else "")
        else:
            masked.append(line)
    return "".join(masked)


def extract_links(text: str) -> list[str]:
    return [m.group("target").strip("<>") for m in LINK.finditer(visible_prose(text))]


def repeated_policy_lines(documents: dict[str, str]) -> list[dict[str, object]]:
    """Report long exact prose across independently loaded contracts; never gate it."""
    occurrences: dict[str, set[str]] = collections.defaultdict(set)
    for path, content in sorted(documents.items()):
        if not ("/skills/" in path or "/core/prompts/" in path or "/core/protocol/" in path):
            continue
        for raw in visible_prose(content).splitlines():
            normalized = " ".join(raw.split())
            if (len(normalized) < POLICY_LINE_MIN or normalized.startswith(("|", "#", "- `", ">"))
                    or len(normalized.split()) < 10):
                continue
            occurrences[normalized].add(path)
    return [
        {"text": line, "sources": sorted(sources)}
        for line, sources in sorted(occurrences.items())
        if len(sources) > 1
    ]


def check_repository(root: Path) -> dict[str, object]:
    root = root.resolve()
    plugin = root / "plugins" / "devflow"
    errors: list[str] = []
    docs: dict[str, str] = {}
    root_docs = [root / name for name in ("README.md", "AGENTS.md", "CLAUDE.md")]
    for path in root_docs + sorted(plugin.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            errors.append(f"{rel}: symlinked document")
            continue
        try:
            docs[rel] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{rel}: unreadable document ({type(exc).__name__})")
    for mandatory in ("README.md", "AGENTS.md", "CLAUDE.md", "plugins/devflow/README.md",
                      "plugins/devflow/core/protocol/role-instructions.md"):
        if mandatory not in docs:
            errors.append(f"missing document: {mandatory}")

    # Only Markdown link destinations and explicit *plugin-owned* path references.
    # Domain-level docs/PR paths and historical changelog prose are not plugin paths.
    for origin, content in sorted(docs.items()):
        source = root / origin
        for target in extract_links(content):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            dest = (source.parent / unquote(parsed.path)).resolve()
            if not dest.is_relative_to(root) or not dest.exists():
                errors.append(f"{origin}: broken relative link: {target}")
        if origin.endswith("CHANGELOG.md"):
            continue
        for match in LOCAL_REFERENCE.finditer(visible_prose(content)):
            ref = match.group(1)
            if "*" in ref or ".." in Path(ref).parts:
                continue
            base = root if ref.startswith("plugins/devflow/") else plugin
            dest = (base / ref).resolve()
            if not dest.is_relative_to(root) or not dest.is_file():
                errors.append(f"{origin}: missing plugin-owned reference: {ref}")

    matrix_name = "plugins/devflow/core/protocol/role-instructions.md"
    matrix = docs.get(matrix_name, "")
    for ref in sorted(set(LOCAL_REFERENCE.findall(matrix))):
        if "*" not in ref and not (plugin / ref).is_file():
            errors.append(f"{matrix_name}: dangling owner: {ref}")
    for path in sorted((plugin / "core/protocol").glob("*.md")):
        if path.name not in ("role-instructions.md",) and path.name not in matrix:
            errors.append(f"{matrix_name}: unowned protocol: {path.name}")
    for path in sorted((plugin / "core/schemas").glob("*.yaml")):
        if path.name not in matrix:
            errors.append(f"{matrix_name}: unowned schema: {path.name}")

    for name in SKILLS:
        relative = f"plugins/devflow/skills/{name}/SKILL.md"
        content = docs.get(relative, "")
        fm = re.match(r"\A---\n(.*?)\n---\n", content, re.DOTALL)
        if not fm:
            errors.append(f"{relative}: missing YAML front matter")
            continue
        fields = fm.group(1)
        if not re.search(rf"(?m)^name: {re.escape(name)}\s*$", fields):
            errors.append(f"{relative}: incorrect skill name")
        if not re.search(r"(?m)^description: \S.+$", fields):
            errors.append(f"{relative}: missing nonblank skill description")
        if len(fields.splitlines()) != 2:
            errors.append(f"{relative}: unsupported skill front matter fields")
        if not (plugin / f"skills/{name}/scripts/invoke.py").is_file() and name not in ("goal",):
            errors.append(f"{relative}: missing invocation adapter")

    for local, tokens in ROLE_POINTERS.items():
        path = f"plugins/devflow/{local}"
        content = docs.get(path, "")
        if not content:
            errors.append(f"{path}: missing role contract")
        for token in tokens:
            if token not in content:
                errors.append(f"{path}: missing required role contract reference: {token}")

    audit = docs.get("plugins/devflow/core/templates/AUDIT.md", "")
    match = re.match(r"\A---\n(.*?)\n---\n", audit, re.DOTALL)
    if not match:
        errors.append("core/templates/AUDIT.md: missing audit front matter")
    else:
        fm = match.group(1)
        for field in NULL_AUDIT_FIELDS:
            if not re.search(rf"(?m)^{field}: null\s*$", fm):
                errors.append(f"core/templates/AUDIT.md: unsafe placeholder: {field}")
        for field in EMPTY_AUDIT_FIELDS:
            if not re.search(rf"(?m)^{field}: \[\]\s*$", fm):
                errors.append(f"core/templates/AUDIT.md: unsafe placeholder: {field}")
    for axis in "ABCDEFGHIJ":
        if not re.search(rf"(?m)^### {axis}\. ", audit):
            errors.append(f"core/templates/AUDIT.md: missing audit axis: {axis}")
    pitfalls = docs.get("plugins/devflow/core/templates/PITFALLS.md", "")
    if "no observed pitfalls" not in pitfalls or "not repository facts" not in pitfalls:
        errors.append("core/templates/PITFALLS.md: scaffold must not claim observed incidents")

    versions: dict[str, str] = {}
    try:
        claude = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        codex_market = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        claude_plugin = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
        codex_plugin = json.loads((plugin / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        versions = {
            "marketplace": claude["version"],
            "marketplace_plugin": claude["plugins"][0]["version"],
            "claude_plugin": claude_plugin["version"],
            "codex_plugin": codex_plugin["version"],
        }
        if len(set(versions.values())) != 1:
            errors.append("plugin versions disagree: " + json.dumps(versions, sort_keys=True))
        if claude["plugins"][0]["source"] != "./plugins/devflow":
            errors.append("Claude marketplace source must point at the shared plugin")
        if codex_market["plugins"][0]["source"]["path"] != "./plugins/devflow":
            errors.append("Codex marketplace source must point at the shared plugin")
        if "version" in codex_market or "version" in codex_market["plugins"][0]:
            errors.append("Codex discovery adapter must not own the plugin version")
        runtime = (plugin / "scripts/devflow.py").read_text(encoding="utf-8")
        protocol = re.search(r'(?m)^PROTOCOL_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', runtime)
        if not protocol:
            errors.append("scripts/devflow.py: missing protocol version constant")
        else:
            versions["protocol"] = protocol.group(1)
        top = docs.get("README.md", "")
        guide = docs.get("plugins/devflow/README.md", "")
        if versions["claude_plugin"] not in top or versions["claude_plugin"] not in guide:
            errors.append("README plugin version differs from published manifests")
        if "protocol" in versions and (versions["protocol"] not in top or versions["protocol"] not in guide):
            errors.append("README protocol version differs from runtime constant")
    except (OSError, UnicodeError, ValueError, KeyError, IndexError, TypeError) as exc:
        errors.append(f"cannot verify marketplace versions ({type(exc).__name__})")

    repeated = repeated_policy_lines(docs)
    return {
        "schema_version": 1,
        "files_scanned": len(docs),
        "document_utf8_bytes": sum(len(s.encode("utf-8")) for s in docs.values()),
        "versions": versions,
        "errors": sorted(set(errors)),
        "duplicate_candidates": repeated,
        "duplicate_candidates_are_advisory": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--json", action="store_true", help="print full machine-readable report")
    args = parser.parse_args(argv)
    report = check_repository(args.root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Docs: {report['files_scanned']} Markdown files; errors={len(report['errors'])}; "
              f"advisory duplicate lines={len(report['duplicate_candidates'])}")
        for error in report["errors"]:
            print("ERROR: " + error)
        for duplicate in report["duplicate_candidates"]:
            print("ADVISORY: " + ", ".join(duplicate["sources"]) + ": " + duplicate["text"][:140])
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
