"""Claude Code native routing adapter; DevFlow lifecycle and leases stay shared.

The adapter never launches Claude CLI processes. A Claude Code /goal supervisor
spawns one foreground native Agent from the returned, verified agent_type.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import devflow_autopilot as autopilot

# Each plugin-shipped agent definition pins both the model family and effort.
# Do not fall back to inherited models or invent a missing agent definition.
FAMILIES = {"fast": "haiku", "balanced": "sonnet", "frontier": "opus"}
SUPPORTED_EFFORTS = {
    "haiku": frozenset({"medium", "high"}),
    "sonnet": frozenset({"medium", "high", "xhigh"}),
    "opus": frozenset({"medium", "high", "xhigh"}),
}


def load_policy(plugin_root: Path, repo_root: Path | None) -> dict[str, Any]:
    """Build Claude-only routing without consuming Codex project overrides."""
    policy = autopilot.load_policy(plugin_root, None)
    core = plugin_root / "core" / "routing"
    policy = autopilot._merge(policy, autopilot._load_yaml(core / "claude.yaml"))
    if repo_root is not None:
        override = repo_root / ".devflow" / "claude-routing.yaml"
        if override.is_file():
            policy = autopilot._merge(policy, autopilot._load_yaml(override))

    if (policy.get("backends") or {}).get("preference") != ["native_agent"]:
        raise ValueError("Claude Code host routing must use only native_agent")

    registry_config = autopilot._load_yaml(core / "claude-models.yaml")
    registry = autopilot.ModelRegistry(registry_config)
    if set(registry.aliases()) != set(FAMILIES):
        raise ValueError("Claude model aliases must remain fast/balanced/frontier")
    for alias, family in FAMILIES.items():
        meta = registry.meta(alias)
        if registry.model_id(alias) != family:
            raise ValueError("Claude native agents require supported model family aliases")
        if set(meta["efforts"]) - SUPPORTED_EFFORTS[family]:
            raise ValueError("Claude model registry requests an unsupported agent effort")
        if not meta.get("multi_agent"):
            raise ValueError("Claude host requires native Agent capability")
    autopilot._validate_routing_model_refs(policy, registry)
    policy["model_registry"] = registry.as_dict()
    policy["models"] = registry.as_legacy_models()
    return policy


def agent_type(payload: dict[str, Any], *, readonly: bool | None = None) -> str:
    """Fail closed instead of silently inheriting the parent's model or effort."""
    family = payload.get("model")
    effort = payload.get("reasoning_effort")
    if not isinstance(family, str) or family not in SUPPORTED_EFFORTS:
        raise ValueError("Claude dispatch has no supported model family")
    if not isinstance(effort, str) or effort not in SUPPORTED_EFFORTS[family]:
        raise ValueError("Claude dispatch has no supported model/effort agent")
    if readonly is None:
        readonly = payload.get("permissions") == "read-only"
    return f"devflow:devflow-{family}-{effort}" + ("-ro" if readonly else "")


def decorate(result: dict[str, Any]) -> dict[str, Any]:
    """Annotate host-native Agent calls, not the lifecycle or persisted work."""
    if result.get("status") != "dispatch_required":
        return result
    decorated = copy.deepcopy(result)
    for field in ("scout", "primary"):
        payload = decorated.get(field)
        if payload is None:
            continue
        # Agent is an in-process Claude Code tool, not `claude -p` or a nested CLI.
        payload["claude"] = {
            "tool": "Agent",
            "agent_type": agent_type(payload),
            "foreground": True,
            "isolation": "shared_checkout",
        }
        for candidate in payload.get("candidates") or []:
            candidate["claude_agent_type"] = agent_type({
                "model": candidate.get("model"),
                "reasoning_effort": candidate.get("reasoning_effort"),
                "permissions": payload.get("permissions"),
            })
    return decorated


def validate_agent_files(plugin_root: Path) -> list[str]:
    """Check bundled Agent definitions match every advertised native route."""
    import yaml

    errors: list[str] = []
    for family, efforts in sorted(SUPPORTED_EFFORTS.items()):
        for effort in sorted(efforts):
            for readonly in (False, True):
                suffix = "-ro" if readonly else ""
                name = f"devflow-{family}-{effort}{suffix}"
                path = plugin_root / "agents" / f"{name}.md"
                if not path.is_file():
                    errors.append(f"missing Claude agent: {name}")
                    continue
                raw = path.read_text(encoding="utf-8")
                if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
                    errors.append(f"invalid Claude agent frontmatter: {name}")
                    continue
                meta = yaml.safe_load(raw.split("---", 2)[1])
                if not isinstance(meta, dict) or any(meta.get(k) != v for k, v in {
                    "name": name, "model": family, "effort": effort,
                    "background": False,
                }.items()):
                    errors.append(f"Claude agent preset drift: {name}")
                denied = {value.strip() for value in str((meta or {}).get("disallowedTools", "")).split(",")}
                required = {"Agent"} | ({"Write", "Edit", "NotebookEdit"} if readonly else set())
                if not required <= denied:
                    errors.append(f"Claude agent tools not fenced: {name}")
    return errors


def assert_model_environment(env: dict[str, str] | None = None) -> None:
    """Reject higher-priority host-wide model overrides before Agent spawn."""
    import os
    environment = os.environ if env is None else env
    forced = environment.get("CLAUDE_CODE_SUBAGENT_MODEL", "").strip()
    if forced not in {"", "inherit"}:
        raise ValueError("CLAUDE_CODE_SUBAGENT_MODEL overrides DevFlow native Agent routing")
