#!/usr/bin/env python3
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import yaml


CAPABILITY_FAILURE = re.compile(
    r"(?:unknown|unsupported|invalid|unavailable|not available|not found|no access|access denied).*model|"
    r"model.*(?:unknown|unsupported|invalid|unavailable|not available|not found|no access|access denied)|"
    r"authentication|unauthorized|forbidden|rate.?limit|quota|http\s*(?:401|403|404|426|429)|"
    r"adapter_eof|upgrade required|at\s+capacity|overloaded|temporarily unavailable|server(?:\s+is)?\s+busy",
    re.IGNORECASE,
)

CODEX_VERSION = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    match = CODEX_VERSION.search(str(value or ""))
    return tuple(int(part) for part in match.groups()) if match else None


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class ModelRegistry:
    """Resolve stable routing aliases to concrete model IDs and capabilities."""

    def __init__(self, config: dict[str, Any]):
        if not isinstance(config, dict):
            raise ValueError("Model registry must be a mapping")
        raw_models = config.get("models")
        if not isinstance(raw_models, dict) or not raw_models:
            raise ValueError("Model registry must define a non-empty models mapping")
        self.version = int(config.get("version", 1))
        self._models: dict[str, dict[str, Any]] = {}
        self._aliases_by_id: dict[str, str] = {}
        for raw_alias, raw_meta in raw_models.items():
            alias = str(raw_alias).strip()
            if not alias or not isinstance(raw_meta, dict):
                raise ValueError("Model registry aliases must be nonblank mappings")
            meta = copy.deepcopy(raw_meta)
            model_id = str(meta.get("id") or "").strip()
            if not model_id:
                raise ValueError(f"Model registry alias {alias!r} must define id")
            if model_id in self._aliases_by_id:
                raise ValueError(f"Concrete model id is mapped more than once: {model_id}")
            efforts = meta.get("efforts")
            if not isinstance(efforts, list) or not efforts or any(not str(value).strip() for value in efforts):
                raise ValueError(f"Model registry alias {alias!r} must define non-empty efforts")
            self._models[alias] = meta
            self._aliases_by_id[model_id] = alias

    @classmethod
    def from_legacy(cls, models: dict[str, dict[str, Any]]) -> "ModelRegistry":
        return cls({
            "version": 0,
            "models": {
                str(model_id): {"id": str(model_id), **copy.deepcopy(meta or {})}
                for model_id, meta in (models or {}).items()
            },
        })

    @classmethod
    def from_policy(cls, policy: dict[str, Any]) -> "ModelRegistry":
        config = policy.get("model_registry")
        if isinstance(config, dict) and config.get("models"):
            return cls(config)
        return cls.from_legacy(policy.get("models", {}))

    def alias_for(self, reference: str) -> str:
        ref = str(reference)
        if ref in self._models:
            return ref
        alias = self._aliases_by_id.get(ref)
        if alias:
            return alias
        raise KeyError(ref)

    def contains(self, reference: str) -> bool:
        try:
            self.alias_for(reference)
        except KeyError:
            return False
        return True

    def model_id(self, reference: str) -> str:
        return str(self._models[self.alias_for(reference)]["id"])

    def meta(self, reference: str) -> dict[str, Any]:
        return self._models[self.alias_for(reference)]

    def codex_min_version(self, reference: str) -> str:
        meta = self.meta(reference)
        backend = ((meta.get("backends") or {}).get("codex_exec") or {})
        return str(backend.get("min_version") or meta.get("codex_min_version") or "").strip()

    def aliases(self) -> list[str]:
        return list(self._models)

    def as_legacy_models(self) -> dict[str, dict[str, Any]]:
        models: dict[str, dict[str, Any]] = {}
        for alias, meta in self._models.items():
            legacy = copy.deepcopy(meta)
            model_id = str(legacy.pop("id"))
            minimum = self.codex_min_version(alias)
            legacy.pop("backends", None)
            if minimum:
                legacy["codex_min_version"] = minimum
            models[model_id] = legacy
        return models

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "models": copy.deepcopy(self._models)}


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a mapping: {path}")
    return value


def _apply_legacy_model_overrides(registry_config: dict[str, Any], legacy: Any) -> dict[str, Any]:
    if not isinstance(legacy, dict) or not legacy:
        return registry_config
    out = copy.deepcopy(registry_config)
    models = out.setdefault("models", {})
    aliases_by_id = {
        str(meta.get("id")): alias
        for alias, meta in models.items()
        if isinstance(meta, dict) and meta.get("id")
    }
    for model_id, meta in legacy.items():
        if not isinstance(meta, dict):
            raise ValueError(f"Legacy model override must be a mapping: {model_id}")
        concrete = str(model_id)
        alias = aliases_by_id.get(concrete, concrete)
        current = models.get(alias) if isinstance(models.get(alias), dict) else {"id": concrete}
        override_meta = copy.deepcopy(meta)
        legacy_minimum = override_meta.pop("codex_min_version", None)
        if legacy_minimum is not None:
            raw_backends = override_meta.get("backends")
            if raw_backends is not None and not isinstance(raw_backends, dict):
                raise ValueError(f"Legacy model override backends must be a mapping: {model_id}")
            backends = copy.deepcopy(raw_backends or {})
            raw_codex = backends.get("codex_exec")
            if raw_codex is not None and not isinstance(raw_codex, dict):
                raise ValueError(f"Legacy codex_exec override must be a mapping: {model_id}")
            codex_exec = copy.deepcopy(raw_codex or {})
            codex_exec["min_version"] = legacy_minimum
            backends["codex_exec"] = codex_exec
            override_meta["backends"] = backends
        models[alias] = _merge(current, {"id": concrete, **override_meta})
    return out


def _validate_routing_model_refs(policy: dict[str, Any], registry: ModelRegistry) -> None:
    profiles = policy.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("Routing policy must define profiles")
    for profile_name, profile in profiles.items():
        candidates = profile.get("candidates") if isinstance(profile, dict) else None
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"Routing profile {profile_name!r} must define candidates")
        unknown = [str(candidate) for candidate in candidates if not registry.contains(str(candidate))]
        if unknown:
            raise ValueError(f"Routing profile {profile_name!r} references unknown model(s): {', '.join(unknown)}")
    for role, config in (policy.get("roles") or {}).items():
        profile = str((config or {}).get("profile") or "")
        if profile not in profiles:
            raise ValueError(f"Routing role {role!r} references unknown profile: {profile}")


def load_policy(plugin_root: Path, repo_root: Path | None) -> dict[str, Any]:
    routing_path = plugin_root / "core" / "routing" / "default.yaml"
    models_path = plugin_root / "core" / "routing" / "models.yaml"
    policy = _load_yaml(routing_path)
    if repo_root is not None:
        override = repo_root / ".devflow" / "routing.yaml"
        if override.exists():
            routing_override = _load_yaml(override)
            policy = _merge(policy, routing_override)
            override_retries = ((routing_override.get("escalation") or {}).get("retries") or {})
            legacy_retry_keys = {
                "worker_promote_at", "worker_xhigh_at", "worker_retry_profile", "worker_retry_effort",
                "worker_post_diagnosis_profile", "worker_post_diagnosis_effort",
            }
            if isinstance(override_retries, dict) and "worker_stages" not in override_retries and any(
                key in override_retries for key in legacy_retry_keys
            ):
                policy.setdefault("escalation", {})["retries"] = _merge({
                    "worker_promote_at": 1,
                    "worker_retry_profile": "balanced",
                    "worker_retry_effort": "xhigh",
                    "diagnose_at": 2,
                    "worker_post_diagnosis_profile": "frontier",
                    "worker_post_diagnosis_effort": "xhigh",
                    "max_no_progress": 3,
                }, override_retries)

    registry_config = _load_yaml(models_path)
    registry_config = _apply_legacy_model_overrides(registry_config, policy.pop("models", None))
    if repo_root is not None:
        model_override = repo_root / ".devflow" / "models.yaml"
        if model_override.exists():
            registry_config = _merge(registry_config, _load_yaml(model_override))

    registry = ModelRegistry(registry_config)
    _validate_routing_model_refs(policy, registry)
    policy["model_registry"] = registry.as_dict()
    # Keep the legacy concrete-ID view derived from the registry for compatibility with callers
    # that inspect policy["models"]. The concrete model source of truth remains models.yaml.
    policy["models"] = registry.as_legacy_models()
    return policy


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


class DomainLease:
    """Cross-process slot lease for one domain controller.

    The default policy has one mutating slot. A small slot pool keeps the implementation faithful
    when a project deliberately raises the policy value, while stale PID-owned files are reclaimed.
    """

    def __init__(self, runtime_dir: Path, limit: int, *, owner: str | None = None):
        self.runtime_dir = runtime_dir
        self.limit = int(limit)
        self.owner = owner or f"run-{uuid.uuid4().hex[:12]}"
        self.lock_dir = runtime_dir / "leases"
        self.path: Path | None = None
        self.acquired = False

    def _try_slot(self, path: Path) -> bool:
        payload = {
            "owner": self.owner,
            "pid": os.getpid(),
            "acquired_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                    pid = int(current.get("pid") or 0)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    pid = 0
                if _pid_alive(pid):
                    return False
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            else:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, ensure_ascii=False)
                    stream.write("\n")
                self.path = path
                self.acquired = True
                return True
        return False

    def acquire(self) -> "DomainLease":
        if self.acquired:
            return self
        if self.limit < 1:
            raise RuntimeError("Autopilot concurrency.mutating must be at least 1")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        for slot in range(self.limit):
            if self._try_slot(self.lock_dir / f"mutating-{slot}.lock"):
                return self
        raise RuntimeError(f"Autopilot mutating concurrency limit reached ({self.limit})")

    def release(self) -> None:
        path = self.path
        self.path = None
        self.acquired = False
        if path is None:
            return
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        if current.get("owner") in {None, self.owner}:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "DomainLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


class TokenBudget:
    BUCKETS = ("planning", "implementation", "verification", "finalization")
    ROLE_BUCKET = {
        "architect": "planning",
        "worker": "implementation",
        "diagnostician": "implementation",
        "verifier": "verification",
        "auditor": "verification",
        "integration_auditor": "verification",
        "finalizer": "finalization",
        "scout": "implementation",
    }

    def __init__(self, config: dict[str, Any] | None, *, total_tokens: int | None = None,
                 state: dict[str, Any] | None = None):
        config = config or {}
        configured_total = total_tokens if total_tokens is not None else config.get("total_tokens", 1_000_000)
        self.total_tokens = int(configured_total)
        if self.total_tokens < 1:
            raise ValueError("Autopilot token budget must be a positive integer")
        self.percent: dict[str, int] = {}
        for bucket in self.BUCKETS:
            value = int(config.get(f"{bucket}_percent", 0))
            if value < 0:
                raise ValueError(f"budget.{bucket}_percent must be non-negative")
            self.percent[bucket] = value
        self.reserve_percent = int(config.get("reserve_percent", 0))
        if self.reserve_percent < 0 or sum(self.percent.values()) + self.reserve_percent != 100:
            raise ValueError("Autopilot budget percentages including reserve must total 100")
        self.dispatch_reserve_tokens = max(1, int(config.get("dispatch_reserve_tokens", 1)))
        self.scout_reserve_tokens = max(1, int(config.get("scout_reserve_tokens", 1)))
        previous = (state or {}).get("used_by_bucket") or {}
        self.used_by_bucket = {bucket: max(0, int(previous.get(bucket, 0))) for bucket in self.BUCKETS}

    @staticmethod
    def tokens_from_usage(usage: Any) -> int:
        if not isinstance(usage, dict):
            return 0
        total = usage.get("total_tokens")
        if isinstance(total, (int, float)) and total >= 0:
            return int(total)
        amount = 0
        for key in ("input_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                amount += int(value)
        return amount

    @classmethod
    def bucket_for_role(cls, role: str) -> str:
        return cls.ROLE_BUCKET.get(role, "implementation")

    @property
    def total_used(self) -> int:
        return sum(self.used_by_bucket.values())

    def allocation(self, bucket: str) -> int:
        if bucket not in self.BUCKETS:
            raise ValueError(f"Unknown token budget bucket: {bucket}")
        return (self.total_tokens * self.percent[bucket]) // 100

    @property
    def reserve_allocation(self) -> int:
        return (self.total_tokens * self.reserve_percent) // 100

    @property
    def reserve_used(self) -> int:
        return sum(max(0, used - self.allocation(bucket)) for bucket, used in self.used_by_bucket.items())

    @property
    def reserve_remaining(self) -> int:
        return max(0, self.reserve_allocation - self.reserve_used)

    def can_dispatch(self, bucket: str, *, required_tokens: int = 1) -> bool:
        required = max(1, int(required_tokens))
        total_remaining = self.total_tokens - self.total_used
        if total_remaining < required:
            return False
        bucket_remaining = self.allocation(bucket) + self.reserve_remaining - self.used_by_bucket[bucket]
        return bucket_remaining >= required

    def reservation_for_role(self, role: str) -> int:
        return self.scout_reserve_tokens if role == "scout" else self.dispatch_reserve_tokens

    def consume(self, bucket: str, usage: Any) -> int:
        tokens = self.tokens_from_usage(usage)
        if bucket not in self.BUCKETS:
            raise ValueError(f"Unknown token budget bucket: {bucket}")
        self.used_by_bucket[bucket] += tokens
        return tokens

    def snapshot(self, bucket: str) -> dict[str, Any]:
        allocation = self.allocation(bucket)
        used = self.used_by_bucket[bucket]
        if not self.can_dispatch(bucket):
            pressure = "exhausted"
        elif (allocation and used >= allocation * 0.8) or self.total_used >= self.total_tokens * 0.85:
            pressure = "high"
        else:
            pressure = "normal"
        return {
            "bucket": bucket,
            "total_tokens": self.total_tokens,
            "total_used": self.total_used,
            "total_remaining": max(0, self.total_tokens - self.total_used),
            "allocation": allocation,
            "used": used,
            "bucket_remaining": max(0, allocation + self.reserve_remaining - used),
            "reserve_remaining": self.reserve_remaining,
            "dispatch_reserve_tokens": self.dispatch_reserve_tokens,
            "scout_reserve_tokens": self.scout_reserve_tokens,
            "pressure": pressure,
        }

    def allow_scout(self, bucket: str, next_role: str | None = None) -> bool:
        required = self.scout_reserve_tokens
        if next_role:
            required += self.reservation_for_role(next_role)
        return self.can_dispatch(bucket, required_tokens=required) and self.snapshot(bucket)["pressure"] == "normal"

    def state_dict(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "used_by_bucket": dict(self.used_by_bucket),
            "reserve_used": self.reserve_used,
            "total_used": self.total_used,
        }


class CapabilityRegistry:
    def __init__(self, models: ModelRegistry | dict[str, dict[str, Any]], *, native_models: set[str] | None = None,
                 exec_available: bool = False, codex_path: str | None = None,
                 codex_version: str | None = None, codex_version_error: str | None = None):
        self.model_registry = models if isinstance(models, ModelRegistry) else ModelRegistry.from_legacy(models)
        self.models = self.model_registry.as_legacy_models()
        self.native_models = native_models or set()
        self.exec_available = exec_available
        self.codex_path = codex_path
        self.codex_version = codex_version
        self.codex_version_tuple = _version_tuple(codex_version)
        self.codex_version_error = codex_version_error
        self.unavailable: dict[tuple[str, str], str] = {}

    @classmethod
    def assumed(cls, policy: dict[str, Any], *, native_models: set[str] | None = None,
                exec_available: bool = True, codex_version: str | None = None) -> "CapabilityRegistry":
        assumed_version = codex_version or ("999.0.0" if exec_available else None)
        return cls(ModelRegistry.from_policy(policy), native_models=native_models, exec_available=exec_available,
                   codex_path="codex" if exec_available else None, codex_version=assumed_version)

    @classmethod
    def detect(cls, policy: dict[str, Any]) -> "CapabilityRegistry":
        codex = shutil.which("codex")
        codex_version = None
        version_error = None
        if codex:
            try:
                proc = subprocess.run(
                    [codex, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5,
                )
                output = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
                version = _version_tuple(output)
                if proc.returncode == 0 and version:
                    codex_version = ".".join(str(part) for part in version)
                else:
                    version_error = output or f"codex --version exited {proc.returncode}"
            except (OSError, subprocess.TimeoutExpired) as exc:
                version_error = str(exc)
        native_env = os.environ.get("DEVFLOW_NATIVE_AGENT_MODELS", "")
        native_runner = os.environ.get("DEVFLOW_NATIVE_AGENT_RUNNER")
        native = {x.strip() for x in native_env.split(",") if x.strip()} if native_runner else set()
        return cls(
            ModelRegistry.from_policy(policy), native_models=native,
            exec_available=bool(codex and codex_version), codex_path=codex,
            codex_version=codex_version, codex_version_error=version_error,
        )

    def model_id(self, model: str) -> str:
        return self.model_registry.model_id(model)

    def model_meta(self, model: str) -> dict[str, Any]:
        return self.model_registry.meta(model)

    def supports_effort(self, model: str, effort: str) -> bool:
        return effort in (self.model_meta(model).get("efforts") or [])

    def supports_recursive_delegation(self, model: str, recursive: bool) -> bool:
        if not recursive:
            return True
        return bool(self.model_meta(model).get("multi_agent"))

    def mark_unavailable(self, model: str, backend: str, reason: str) -> None:
        self.unavailable[(self.model_id(model), backend)] = reason.strip() or "unavailable"

    def codex_compatible(self, model: str) -> bool:
        minimum = self.model_registry.codex_min_version(model)
        if not minimum:
            return self.exec_available
        required = _version_tuple(minimum)
        return bool(self.exec_available and required and self.codex_version_tuple and self.codex_version_tuple >= required)

    def restore_unavailable(self, rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            alias = str(row.get("alias") or "").strip()
            model = str(row.get("model") or "").strip()
            backend = str(row.get("backend") or "").strip()
            if not backend or not (alias or model):
                continue
            if alias and self.model_registry.contains(alias):
                reference = alias
            elif model and self.model_registry.contains(model):
                reference = model
            else:
                continue
            current_model = self.model_id(reference)
            if model and current_model != model:
                continue
            self.mark_unavailable(reference, backend, str(row.get("reason") or "unavailable"))

    def unavailable_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for (model, backend), reason in sorted(self.unavailable.items()):
            rows.append({
                "alias": self.model_registry.alias_for(model),
                "model": model,
                "backend": backend,
                "reason": reason,
            })
        return rows

    def backend_for(self, model: str, preference: list[str]) -> str | None:
        concrete = self.model_id(model)
        for backend in preference:
            if (concrete, backend) in self.unavailable:
                continue
            if backend == "native_agent" and concrete in self.native_models:
                return backend
            if backend == "codex_exec" and self.codex_compatible(model):
                return backend
        return None

    def as_dict(self) -> dict[str, Any]:
        aliases = self.model_registry.aliases()
        return {
            "codex_exec": {
                "available": self.exec_available,
                "path": self.codex_path,
                "version": self.codex_version,
                "version_error": self.codex_version_error,
                "model_compatibility": {
                    self.model_id(alias): {
                        "compatible": self.codex_compatible(alias),
                        "minimum_version": self.model_registry.codex_min_version(alias),
                    }
                    for alias in aliases
                },
                "alias_compatibility": {
                    alias: {
                        "model": self.model_id(alias),
                        "compatible": self.codex_compatible(alias),
                        "minimum_version": self.model_registry.codex_min_version(alias),
                    }
                    for alias in aliases
                },
            },
            "native_agent": {"models": sorted(self.native_models)},
            "models": self.model_registry.as_legacy_models(),
            "model_registry": self.model_registry.as_dict(),
            "unavailable": self.unavailable_rows(),
        }


class ModelResolver:
    """Bind a logical routing decision to an available concrete model/backend pair."""

    def __init__(self, policy: dict[str, Any], capabilities: CapabilityRegistry):
        self.policy = policy
        self.capabilities = capabilities

    def resolve(self, decision: dict[str, Any], action: dict[str, Any], attempt: int) -> dict[str, Any]:
        profile = self.policy["profiles"][decision["profile"]]
        preference = list(self.policy.get("backends", {}).get("preference") or ["codex_exec"])
        recursive = bool((self.policy.get("delegation") or {}).get("recursive", False))
        context = self.policy.get("context") or {}
        selected_ref = backend = None
        for model_ref in profile.get("candidates", []):
            if not self.capabilities.supports_effort(model_ref, decision["effort"]):
                continue
            if not self.capabilities.supports_recursive_delegation(model_ref, recursive):
                continue
            candidate_backend = self.capabilities.backend_for(model_ref, preference)
            if candidate_backend:
                selected_ref, backend = str(model_ref), candidate_backend
                break
        if not selected_ref:
            raise RuntimeError(
                f"No available model/backend for profile={decision['profile']} effort={decision['effort']}"
            )
        alias = self.capabilities.model_registry.alias_for(selected_ref)
        selected = self.capabilities.model_id(selected_ref)
        model_meta = self.capabilities.model_meta(selected_ref)
        return {
            "dispatch_id": f"dsp_{uuid.uuid4().hex[:12]}",
            "role": decision["role"],
            "task_id": action.get("work_item"),
            "action": copy.deepcopy(action),
            "effective_risk": decision["effective_risk"],
            "model": {
                "profile": decision["profile"],
                "alias": alias,
                "selected": selected,
                "reasoning_effort": decision["effort"],
            },
            "execution": {
                "backend": backend,
                "sandbox": decision["sandbox"],
                "context_mode": context.get("default_mode", "capsule"),
                "native_fork_turns": context.get("native_fork_turns", "none"),
                "allow_recursive_delegation": recursive,
                "model_multi_agent": model_meta.get("multi_agent"),
            },
            "attempt": attempt,
        }


class RouteEngine:
    EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}

    def __init__(self, policy: dict[str, Any], capabilities: CapabilityRegistry):
        self.policy = policy
        self.capabilities = capabilities
        self.model_resolver = ModelResolver(policy, capabilities)

    def _role(self, action: dict[str, Any], attempt: int) -> str:
        override = action.get("_role_override")
        if override:
            return str(override)
        command, scope = action.get("command"), action.get("scope")
        if command in {"bootstrap", "plan"}:
            return "architect"
        if command == "run":
            diagnose_at = int(self.policy["escalation"]["retries"].get("diagnose_at", 2))
            return "diagnostician" if attempt == diagnose_at else "worker"
        if command == "audit":
            if scope == "work":
                return "verifier"
            if scope == "integration":
                return "integration_auditor"
            return "auditor"
        if command == "finalize":
            return "finalizer"
        raise ValueError(f"Action is not dispatchable: {command}")

    @staticmethod
    def _effective_risk(action: dict[str, Any], state: dict[str, Any]) -> str:
        order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        candidates = [state.get("risk_profile"), action.get("risk"), action.get("item_risk")]
        valid = [str(value) for value in candidates if str(value) in order]
        return max(valid, key=order.__getitem__) if valid else "medium"

    @staticmethod
    def _apply_role_override(cfg: dict[str, Any], override: dict[str, Any], role: str) -> None:
        profile = override.get(f"{role}_profile")
        effort = override.get(f"{role}_effort")
        if profile:
            cfg["profile"] = str(profile)
        if effort:
            cfg["effort"] = str(effort)

    def _stronger_profile(self, current: str, candidate: Any) -> str:
        if not candidate:
            return current
        candidate = str(candidate)
        order = list(self.policy.get("profile_order") or self.policy.get("profiles", {}).keys())
        ranks = {name: index for index, name in enumerate(order)}
        if current not in ranks or candidate not in ranks:
            return candidate
        return candidate if ranks[candidate] > ranks[current] else current

    @classmethod
    def _stronger_effort(cls, current: str, candidate: Any) -> str:
        if not candidate:
            return current
        candidate = str(candidate)
        if current not in cls.EFFORT_ORDER or candidate not in cls.EFFORT_ORDER:
            return candidate
        return candidate if cls.EFFORT_ORDER[candidate] > cls.EFFORT_ORDER[current] else current

    @staticmethod
    def _worker_retry_stage(retries: dict[str, Any], attempt: int) -> dict[str, Any] | None:
        stages = retries.get("worker_stages")
        if not isinstance(stages, list):
            raise ValueError("escalation.retries.worker_stages must be a list")
        selected: tuple[int, dict[str, Any]] | None = None
        previous = 0
        for raw in stages:
            if not isinstance(raw, dict):
                raise ValueError("worker retry stages must be mappings")
            try:
                threshold = int(raw["attempt"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("worker retry stages require integer attempt") from exc
            if threshold <= previous:
                raise ValueError("worker retry stage attempts must be strictly increasing positive integers")
            previous = threshold
            if attempt >= threshold:
                selected = (threshold, raw)
        return copy.deepcopy(selected[1]) if selected else None

    def decide(self, action: dict[str, Any], state: dict[str, Any], attempt: int = 0) -> dict[str, Any]:
        role = self._role(action, attempt)
        cfg = copy.deepcopy(self.policy["roles"][role])
        escalation = self.policy.get("escalation", {})
        item_kind = str(action.get("item_kind") or "")
        kind_over = (escalation.get("kind", {}).get(item_kind) or {})
        self._apply_role_override(cfg, kind_over, role)

        risk = self._effective_risk(action, state)
        risk_over = (escalation.get("risk", {}).get(risk) or {})
        self._apply_role_override(cfg, risk_over, role)

        if role == "worker":
            retries = escalation.get("retries", {})
            if "worker_stages" in retries:
                stage = self._worker_retry_stage(retries, attempt)
                if stage:
                    if stage.get("replace"):
                        cfg["profile"] = str(stage.get("profile") or cfg["profile"])
                        cfg["effort"] = str(stage.get("effort") or cfg["effort"])
                    else:
                        cfg["profile"] = self._stronger_profile(cfg["profile"], stage.get("profile"))
                        cfg["effort"] = self._stronger_effort(cfg["effort"], stage.get("effort"))
            else:
                diagnose_at = int(retries.get("diagnose_at", 2))
                promote_at = int(retries.get("worker_promote_at", retries.get("worker_xhigh_at", 1)))
                if attempt > diagnose_at:
                    cfg["profile"] = self._stronger_profile(cfg["profile"], retries.get("worker_post_diagnosis_profile"))
                    cfg["effort"] = self._stronger_effort(cfg["effort"], retries.get("worker_post_diagnosis_effort", "xhigh"))
                elif attempt >= promote_at:
                    cfg["profile"] = self._stronger_profile(cfg["profile"], retries.get("worker_retry_profile"))
                    cfg["effort"] = self._stronger_effort(cfg["effort"], retries.get("worker_retry_effort", "xhigh"))

        return {
            "role": role,
            "profile": cfg["profile"],
            "effort": cfg["effort"],
            "sandbox": cfg.get("sandbox", "workspace-write"),
            "effective_risk": risk,
        }

    def resolve(self, action: dict[str, Any], state: dict[str, Any], attempt: int = 0) -> dict[str, Any]:
        return self.model_resolver.resolve(self.decide(action, state, attempt), action, attempt)


ROLE_CONTRACTS = {
    "architect": ("skill", "plan"),
    "worker": ("skill", "run"),
    "verifier": ("skill", "audit"),
    "auditor": ("skill", "audit"),
    "integration_auditor": ("skill", "audit"),
    "diagnostician": ("prompt", "diagnose.md"),
    "finalizer": ("skill", "run"),
    "scout": ("prompt", "scout.md"),
}


class ContextAssembler:
    COMPACT_PACKET_ROLES = frozenset({
        "architect", "verifier", "auditor", "integration_auditor", "diagnostician", "finalizer",
    })

    def __init__(self, plugin_root: Path):
        self.plugin_root = plugin_root

    def _role_contract(self, role: str) -> str:
        return self._role_contract_for(role, None)

    def _role_contract_for(self, role: str, command: str | None) -> str:
        if role == "architect" and command == "bootstrap":
            path = self.plugin_root / "core" / "prompts" / "bootstrap.md"
            return path.read_text(encoding="utf-8") if path.exists() else ""
        source = ROLE_CONTRACTS.get(role)
        if not source:
            return ""
        kind, name = source
        path = self.plugin_root / "skills" / name / "SKILL.md" if kind == "skill" else self.plugin_root / "core" / "prompts" / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @staticmethod
    def _runtime_domain(rendered_packet: str) -> str | None:
        match = re.search(r"(?m)^- domain: (.+?)\s*$", rendered_packet)
        return match.group(1).strip() if match else None

    def _packet_section(self, spec: dict[str, Any], rendered_packet: str, scout_digest: str | None) -> str:
        role = str(spec.get("role") or "")
        if not scout_digest or role not in self.COMPACT_PACKET_ROLES:
            return "## Runtime packet\n" + rendered_packet
        domain = self._runtime_domain(rendered_packet)
        if domain:
            recovery = (
                f" If material evidence is missing or contradictory, run `python3 \"{self.plugin_root / 'scripts' / 'devflow.py'}\" "
                f"status {domain}` and re-render the exact current action before deciding."
            )
        else:
            recovery = (
                " If material evidence is missing or contradictory, use the concrete lifecycle CLI above to run status and "
                "re-render the exact current action before deciding."
            )
        return (
            "## Terra pre-analysis capsule\n" + scout_digest + "\n\n"
            "## Authoritative packet recovery\n"
            "The full rendered runtime packet is intentionally omitted from this Sol dispatch to avoid paying twice for "
            "repository-wide context. Treat the Terra capsule as a navigation/evidence index, not lifecycle authority. "
            "Verify cited repository evidence before making the final architecture, audit, diagnosis, or completion decision."
            + recovery
        )

    def build(self, spec: dict[str, Any], rendered_packet: str, diagnosis: str | None = None,
              scout_digest: str | None = None) -> str:
        command = str((spec.get("action") or {}).get("command") or "")
        contract = self._role_contract_for(spec["role"], command)
        execution = spec.get("execution") or {}
        runtime_cli = self.plugin_root / "scripts" / "devflow.py"
        header = {
            "role": spec["role"],
            "task_id": spec.get("task_id"),
            "action": spec.get("action"),
            "model": spec.get("model"),
            "autopilot": True,
            "context_mode": execution.get("context_mode", "capsule"),
            "recursive_delegation": bool(execution.get("allow_recursive_delegation", False)),
        }
        parts = [
            "# DevFlow Autopilot Dispatch\n" + yaml.safe_dump(header, sort_keys=False, allow_unicode=True),
            "## Runtime invocation\n"
            f"DEVFLOW_PLUGIN_ROOT={self.plugin_root}\n"
            f"Use this exact lifecycle CLI from the repository root: `python3 \"{runtime_cli}\" <args>`. "
            "This concrete path overrides placeholder plugin-root examples in the role contract.",
            "## Role contract\n" + contract,
            self._packet_section(spec, rendered_packet, scout_digest),
        ]
        if scout_digest and spec["role"] not in self.COMPACT_PACKET_ROLES:
            parts.append("## Repository scout\n" + scout_digest)
        if diagnosis:
            parts.append("## Prior independent diagnosis\n" + diagnosis)
        if command == "bootstrap":
            parts.append(
                "## Completion contract\nWrite only the requested PRD bootstrap artifact to the exact target path. "
                "Do not initialize the domain or mutate lifecycle/source files. Return a concise receipt."
            )
        elif spec["role"] == "diagnostician":
            parts.append(
                "## Completion contract\nPerform read-only independent diagnosis of the stalled WORK. "
                "Do not mutate lifecycle state, documentation, or source. Return the concrete root cause, "
                "evidence, and a bounded remediation recommendation for the next worker."
            )
        elif spec["role"] == "scout":
            parts.append(
                "## Completion contract\nPerform read-only repository pre-analysis only. Return a compact evidence capsule "
                "with exact files, symbols, tests, constraints, candidate concerns, and unresolved uncertainty. "
                "Do not make the specialist's final architecture/audit verdict and do not mutate anything."
            )
        else:
            delegation = (
                "Nested delegation is permitted only within the routed role and current lifecycle action."
                if execution.get("allow_recursive_delegation")
                else "Do not dispatch nested agents."
            )
            parts.append(
                "## Completion contract\nPerform only this routed role. Apply the normal DevFlow lifecycle mutation before returning. "
                f"{delegation} Re-read status after mutation and return a concise receipt."
            )
        return "\n\n".join(parts)

class RuntimeLedger:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def record(self, stream: str, payload: dict[str, Any]) -> None:
        row = dict(payload)
        row.setdefault("recorded_at", time.time())
        with (self.directory / f"{stream}.jsonl").open("a", encoding="utf-8") as stream_file:
            stream_file.write(json.dumps(row, ensure_ascii=False) + "\n")

    def load_controller(self) -> dict[str, Any]:
        path = self.directory / "controller.json"
        if not path.exists():
            return {}
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return body if isinstance(body, dict) else {}

    def write_controller(self, payload: dict[str, Any]) -> None:
        target = self.directory / "controller.json"
        temporary = self.directory / f".controller.{uuid.uuid4().hex}.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, target)


class CodexExecBackend:
    def __init__(self, executable: str = "codex"):
        self.executable = executable

    def build_command(self, repo_root: Path, spec: dict[str, Any]) -> list[str]:
        model = spec["model"]["selected"]
        effort = spec["model"]["reasoning_effort"]
        sandbox = spec.get("execution", {}).get("sandbox", "workspace-write")
        return [
            self.executable, "exec", "--ephemeral", "--json", "--cd", str(repo_root), "--sandbox", sandbox,
            "--model", model, "--config", f'model_reasoning_effort="{effort}"', "-",
        ]

    def execute(self, repo_root: Path, spec: dict[str, Any], prompt: str, timeout: int | None = None) -> dict[str, Any]:
        started = time.time()
        proc = subprocess.run(
            self.build_command(repo_root, spec), input=prompt, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout,
        )
        usage, last_message = {}, ""
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "turn.completed":
                usage = event.get("usage") or usage
            item = event.get("item") or {}
            if item.get("type") == "agent_message":
                last_message = item.get("text") or last_message
        return {
            "status": "success" if proc.returncode == 0 else "failed",
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "message": last_message,
            "usage": usage,
            "duration_seconds": round(time.time() - started, 3),
        }


class NativeAgentBackend:
    """Adapter contract for a host-provided native spawn bridge."""

    def __init__(self, command: str | None = None):
        self.command = command or os.environ.get("DEVFLOW_NATIVE_AGENT_RUNNER")

    def execute(self, repo_root: Path, spec: dict[str, Any], prompt: str, timeout: int | None = None) -> dict[str, Any]:
        if not self.command:
            raise RuntimeError("Native agent backend selected without DEVFLOW_NATIVE_AGENT_RUNNER")
        payload = json.dumps({"repo_root": str(repo_root), "spec": spec, "prompt": prompt}, ensure_ascii=False)
        proc = subprocess.run(
            [self.command], input=payload, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        try:
            body = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except json.JSONDecodeError:
            body = {"message": proc.stdout}
        body.setdefault("status", "success" if proc.returncode == 0 else "failed")
        body.setdefault("exit_code", proc.returncode)
        body.setdefault("stderr", proc.stderr)
        return body


def _failure_text(receipt: dict[str, Any]) -> str:
    return "\n".join(str(receipt.get(key) or "") for key in ("message", "stderr", "stdout"))


def classify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    out = dict(receipt)
    if out.get("status") == "success":
        out.pop("failure_kind", None)
        return out
    if out.get("failure_kind"):
        return out
    text = _failure_text(out)
    out["failure_kind"] = "capability_unavailable" if CAPABILITY_FAILURE.search(text) else "execution_failed"
    return out


def exception_receipt(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
        return {
            "status": "failed", "exit_code": 124, "failure_kind": "timeout",
            "message": str(exc), "stderr": str(exc), "stdout": "", "usage": {},
        }
    if isinstance(exc, OSError):
        return {
            "status": "failed", "exit_code": 127, "failure_kind": "capability_unavailable",
            "message": str(exc), "stderr": str(exc), "stdout": "", "usage": {},
        }
    return {
        "status": "failed", "exit_code": 1, "failure_kind": "execution_exception",
        "message": str(exc), "stderr": str(exc), "stdout": "", "usage": {},
    }


class DispatchBroker:
    def __init__(self, repo_root: Path, capabilities: CapabilityRegistry):
        self.repo_root = repo_root
        self.backends = {
            "codex_exec": CodexExecBackend(capabilities.codex_path or "codex"),
            "native_agent": NativeAgentBackend(),
        }

    def execute(self, spec: dict[str, Any], prompt: str, timeout: int | None = None) -> dict[str, Any]:
        backend = self.backends[spec["execution"]["backend"]]
        try:
            receipt = backend.execute(self.repo_root, spec, prompt, timeout)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            receipt = exception_receipt(exc)
        return classify_receipt(receipt)


class ExecutionBoundary:
    VALUES = ("plan", "implementation", "complete")

    def __init__(self, value: str = "complete"):
        if value not in self.VALUES:
            raise ValueError(f"Unsupported execution boundary: {value}")
        self.value = value

    @staticmethod
    def _plan_remediation_ids(state: dict[str, Any]) -> set[str]:
        review = state.get("plan_review") or {}
        values = review.get("remediation_work_ids") or []
        return {str(item_id) for item_id in values}

    @classmethod
    def _is_planning_action(cls, state: dict[str, Any], action: dict[str, Any]) -> bool:
        if action.get("command") == "plan" or action.get("scope") == "plan":
            return True
        work_item = action.get("work_item")
        return work_item is not None and str(work_item) in cls._plan_remediation_ids(state)

    def reached(self, state: dict[str, Any], action: dict[str, Any]) -> bool:
        if self.value == "complete":
            return False
        if self.value == "plan":
            return not self._is_planning_action(state, action)
        if self.value == "implementation":
            if self._is_planning_action(state, action):
                return False
            return action.get("command") == "finalize" or action.get("scope") == "integration"
        raise AssertionError(f"Unhandled execution boundary: {self.value}")


class AutopilotController:
    def __init__(self, status_fn: Callable[[], dict[str, Any]], render_fn: Callable[[dict[str, Any]], str],
                 route_fn: Callable[[dict[str, Any], dict[str, Any], int], dict[str, Any]],
                 dispatch_fn: Callable[[dict[str, Any], str], dict[str, Any]], ledger: RuntimeLedger | None,
                 max_steps: int = 100, max_no_progress: int = 3, *, run_id: str | None = None,
                 resume_state: dict[str, Any] | None = None, capabilities: CapabilityRegistry | None = None,
                 budget: TokenBudget | None = None, scout_before: set[str] | None = None,
                 scout_max_chars: int = 12000, until: str = "complete"):
        self.status_fn = status_fn
        self.render_fn = render_fn
        self.route_fn = route_fn
        self.dispatch_fn = dispatch_fn
        self.ledger = ledger
        self.max_steps = max_steps
        self.max_no_progress = max_no_progress
        self.capabilities = capabilities
        self.budget = budget
        self.scout_before = set(scout_before or set())
        self.scout_max_chars = int(scout_max_chars)
        if self.scout_max_chars < 1:
            raise ValueError("orchestration.scout_max_chars must be positive")
        self.boundary = ExecutionBoundary(until)
        resume = resume_state or {}
        self.run_id = run_id or str(resume.get("run_id") or f"run_{uuid.uuid4().hex[:12]}")
        self.attempts = {str(k): int(v) for k, v in (resume.get("attempts") or {}).items()}
        self.diagnoses = {str(k): str(v) for k, v in (resume.get("diagnoses") or {}).items()}
        self.scouts = {
            str(k): self._bounded_scout_digest(str(v))
            for k, v in (resume.get("scouts") or {}).items()
            if str(v).strip()
        }
        self.steps_completed = int(resume.get("steps_completed") or 0)
        if self.capabilities:
            self.capabilities.restore_unavailable(resume.get("unavailable_candidates"))

    @staticmethod
    def fingerprint(action: dict[str, Any]) -> str:
        keys = ("command", "scope", "mode", "phase", "work_item")
        return json.dumps({key: action.get(key) for key in keys}, sort_keys=True)

    @staticmethod
    def _bucket(spec: dict[str, Any]) -> str:
        return TokenBudget.bucket_for_role(str(spec.get("role") or "worker"))

    @staticmethod
    def _same_model(left: dict[str, Any], right: dict[str, Any]) -> bool:
        return str((left.get("model") or {}).get("selected") or "") == str((right.get("model") or {}).get("selected") or "")

    def _bounded_scout_digest(self, value: str) -> str:
        digest = value.strip()
        if len(digest) <= self.scout_max_chars:
            return digest
        marker = "\n[pre-analysis capsule truncated by DevFlow]"
        keep = max(0, self.scout_max_chars - len(marker))
        return digest[:keep].rstrip() + marker

    def _checkpoint(self, status: str, *, action: dict[str, Any] | None = None,
                    reason: str | None = None, steps: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "run_id": self.run_id,
            "execution_boundary": self.boundary.value,
            "steps_completed": self.steps_completed if steps is None else steps,
            "attempts": dict(self.attempts),
            "diagnoses": dict(self.diagnoses),
            "scouts": dict(self.scouts),
            "action": copy.deepcopy(action) if action is not None else None,
            "unavailable_candidates": self.capabilities.unavailable_rows() if self.capabilities else [],
            "budget": self.budget.state_dict() if self.budget else None,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        if reason:
            payload["reason"] = reason
        if self.ledger:
            self.ledger.write_controller(payload)
        return payload

    def _dispatch(self, spec: dict[str, Any], packet: str, *, step: int,
                  budget_bucket: str | None = None) -> dict[str, Any]:
        try:
            receipt = classify_receipt(self.dispatch_fn(spec, packet))
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            receipt = exception_receipt(exc)
        bucket = budget_bucket or self._bucket(spec)
        if self.budget:
            used = self.budget.consume(bucket, receipt.get("usage") or {})
            spec.setdefault("budget", {})
            spec["budget"].update(self.budget.snapshot(bucket))
            spec["budget"]["dispatch_tokens"] = used
        if self.ledger:
            self.ledger.record("dispatch", {"run_id": self.run_id, "step": step, "spec": spec, "receipt": receipt})
        return receipt

    def _mark_capability_failure(self, spec: dict[str, Any], receipt: dict[str, Any]) -> bool:
        if receipt.get("failure_kind") != "capability_unavailable" or not self.capabilities:
            return False
        model = str((spec.get("model") or {}).get("selected") or "")
        backend = str((spec.get("execution") or {}).get("backend") or "")
        if model and backend:
            self.capabilities.mark_unavailable(model, backend, _failure_text(receipt) or "capability unavailable")
            return True
        return False

    def _route(self, action: dict[str, Any], state: dict[str, Any], attempt: int) -> dict[str, Any] | None:
        try:
            return self.route_fn(action, state, attempt)
        except Exception:
            return None

    def run(self) -> dict[str, Any]:
        starting_steps = self.steps_completed
        for local_step in range(self.max_steps):
            step = starting_steps + local_step
            try:
                state = self.status_fn()
            except Exception as exc:
                result = self._checkpoint("blocked", reason=f"status_failed: {exc}", steps=step)
                result["steps"] = step
                return result
            action = state.get("next_action") or {}
            command = action.get("command")
            if command == "complete":
                self.steps_completed = step
                result = self._checkpoint("complete", action=action, steps=step)
                result["steps"] = step
                return result
            if command == "decision" or action.get("role") == "human":
                self.steps_completed = step
                result = self._checkpoint("paused", action=action, steps=step)
                result["steps"] = step
                return result
            if self.boundary.reached(state, action):
                self.steps_completed = step
                result = self._checkpoint(
                    "checkpoint", action=action, reason="execution_boundary_reached", steps=step,
                )
                result["steps"] = step
                return result

            fp = self.fingerprint(action)
            attempt = self.attempts.get(fp, 0)
            spec = self._route(action, state, attempt)
            if spec is None:
                self.steps_completed = step
                result = self._checkpoint("blocked", action=action, reason="route_unavailable", steps=step)
                result["steps"] = step
                return result
            bucket = self._bucket(spec)
            required_tokens = self.budget.reservation_for_role(spec.get("role", "worker")) if self.budget else 1
            if self.budget and not self.budget.can_dispatch(bucket, required_tokens=required_tokens):
                self.steps_completed = step
                result = self._checkpoint("blocked", action=action, reason="token_budget_dispatch_reserve_exhausted", steps=step)
                result["steps"] = step
                result["budget"] = self.budget.snapshot(bucket)
                return result
            if fp in self.diagnoses:
                spec["diagnosis"] = self.diagnoses[fp]
            if fp in self.scouts:
                spec["scout_digest"] = self.scouts[fp]
            try:
                packet = self.render_fn(action)
            except Exception as exc:
                self.steps_completed = step
                result = self._checkpoint("blocked", action=action, reason=f"render_failed: {exc}", steps=step)
                result["steps"] = step
                return result

            if (
                spec.get("role") in self.scout_before
                and fp not in self.scouts
                and (self.budget is None or self.budget.allow_scout(bucket, spec.get("role")))
            ):
                scout_action = copy.deepcopy(action)
                scout_action["_role_override"] = "scout"
                scout_spec = self._route(scout_action, state, attempt)
                scout_receipt: dict[str, Any] | None = None
                if scout_spec is not None and not self._same_model(scout_spec, spec):
                    scout_receipt = self._dispatch(scout_spec, packet, step=step, budget_bucket=bucket)
                    if self._mark_capability_failure(scout_spec, scout_receipt):
                        scout_spec = self._route(scout_action, state, attempt)
                        if scout_spec is not None and not self._same_model(scout_spec, spec):
                            scout_receipt = self._dispatch(scout_spec, packet, step=step, budget_bucket=bucket)
                            self._mark_capability_failure(scout_spec, scout_receipt)
                        else:
                            scout_receipt = None
                if scout_receipt is not None and scout_receipt.get("status") == "success":
                    digest = scout_receipt.get("message") or scout_receipt.get("stdout")
                    if isinstance(digest, str) and digest.strip():
                        self.scouts[fp] = self._bounded_scout_digest(digest)
                        spec["scout_digest"] = self.scouts[fp]

            if self.budget and not self.budget.can_dispatch(bucket, required_tokens=required_tokens):
                self.steps_completed = step
                result = self._checkpoint(
                    "blocked", action=action, reason="token_budget_dispatch_reserve_exhausted", steps=step,
                )
                result["steps"] = step
                result["budget"] = self.budget.snapshot(bucket)
                return result

            receipt = self._dispatch(spec, packet, step=step, budget_bucket=bucket)
            if self._mark_capability_failure(spec, receipt):
                self.steps_completed = step + 1
                self._checkpoint("running", action=action, steps=self.steps_completed)
                continue
            if spec.get("role") == "diagnostician" and receipt.get("status") == "success":
                self.diagnoses[fp] = str(receipt.get("message") or receipt.get("stdout") or "diagnosis completed")

            try:
                after = self.status_fn()
            except Exception as exc:
                self.steps_completed = step + 1
                result = self._checkpoint("blocked", action=action, reason=f"status_failed_after_dispatch: {exc}", steps=self.steps_completed)
                result["steps"] = self.steps_completed
                return result
            after_fp = self.fingerprint(after.get("next_action") or {})
            if after_fp == fp:
                self.attempts[fp] = attempt + 1
                if self.attempts[fp] > self.max_no_progress:
                    self.steps_completed = step + 1
                    result = self._checkpoint(
                        "blocked", action=action, reason="no_progress_retry_budget_exhausted", steps=self.steps_completed,
                    )
                    result["attempts_exhausted"] = self.attempts[fp]
                    result["steps"] = self.steps_completed
                    return result
            else:
                self.attempts.pop(fp, None)
                self.diagnoses.pop(fp, None)
                self.scouts.pop(fp, None)
            self.steps_completed = step + 1
            self._checkpoint("running", action=after.get("next_action") or {}, steps=self.steps_completed)

        result = self._checkpoint("blocked", reason="max_steps_exhausted", steps=self.steps_completed)
        result["steps"] = self.steps_completed
        return result
