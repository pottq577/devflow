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


def load_policy(plugin_root: Path, repo_root: Path | None) -> dict[str, Any]:
    default_path = plugin_root / "core" / "routing" / "default.yaml"
    policy = yaml.safe_load(default_path.read_text(encoding="utf-8")) or {}
    if repo_root is not None:
        override = repo_root / ".devflow" / "routing.yaml"
        if override.exists():
            policy = _merge(policy, yaml.safe_load(override.read_text(encoding="utf-8")) or {})
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
    def __init__(self, models: dict[str, dict[str, Any]], *, native_models: set[str] | None = None,
                 exec_available: bool = False, codex_path: str | None = None,
                 codex_version: str | None = None, codex_version_error: str | None = None):
        self.models = models
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
        return cls(policy.get("models", {}), native_models=native_models, exec_available=exec_available,
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
            policy.get("models", {}), native_models=native,
            exec_available=bool(codex and codex_version), codex_path=codex,
            codex_version=codex_version, codex_version_error=version_error,
        )

    def supports_effort(self, model: str, effort: str) -> bool:
        return effort in ((self.models.get(model) or {}).get("efforts") or [])

    def supports_recursive_delegation(self, model: str, recursive: bool) -> bool:
        if not recursive:
            return True
        return bool((self.models.get(model) or {}).get("multi_agent"))

    def mark_unavailable(self, model: str, backend: str, reason: str) -> None:
        self.unavailable[(model, backend)] = reason.strip() or "unavailable"

    def codex_compatible(self, model: str) -> bool:
        minimum = str((self.models.get(model) or {}).get("codex_min_version") or "").strip()
        if not minimum:
            return self.exec_available
        required = _version_tuple(minimum)
        return bool(self.exec_available and required and self.codex_version_tuple and self.codex_version_tuple >= required)

    def restore_unavailable(self, rows: Any) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if isinstance(row, dict) and row.get("model") and row.get("backend"):
                self.mark_unavailable(str(row["model"]), str(row["backend"]), str(row.get("reason") or "unavailable"))

    def unavailable_rows(self) -> list[dict[str, str]]:
        return [
            {"model": model, "backend": backend, "reason": reason}
            for (model, backend), reason in sorted(self.unavailable.items())
        ]

    def backend_for(self, model: str, preference: list[str]) -> str | None:
        for backend in preference:
            if (model, backend) in self.unavailable:
                continue
            if backend == "native_agent" and model in self.native_models:
                return backend
            if backend == "codex_exec" and self.codex_compatible(model):
                return backend
        return None

    def as_dict(self) -> dict[str, Any]:
        return {
            "codex_exec": {
                "available": self.exec_available,
                "path": self.codex_path,
                "version": self.codex_version,
                "version_error": self.codex_version_error,
                "model_compatibility": {
                    model: {
                        "compatible": self.codex_compatible(model),
                        "minimum_version": (meta or {}).get("codex_min_version"),
                    }
                    for model, meta in self.models.items()
                },
            },
            "native_agent": {"models": sorted(self.native_models)},
            "models": self.models,
            "unavailable": self.unavailable_rows(),
        }


class RouteEngine:
    EFFORT_ORDER = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}

    def __init__(self, policy: dict[str, Any], capabilities: CapabilityRegistry):
        self.policy = policy
        self.capabilities = capabilities

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

    def resolve(self, action: dict[str, Any], state: dict[str, Any], attempt: int = 0) -> dict[str, Any]:
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
            diagnose_at = int(retries.get("diagnose_at", 2))
            promote_at = int(retries.get("worker_promote_at", retries.get("worker_xhigh_at", 1)))
            if attempt > diagnose_at:
                cfg["profile"] = self._stronger_profile(cfg["profile"], retries.get("worker_post_diagnosis_profile"))
                cfg["effort"] = self._stronger_effort(cfg["effort"], retries.get("worker_post_diagnosis_effort", "xhigh"))
            elif attempt >= promote_at:
                cfg["profile"] = self._stronger_profile(cfg["profile"], retries.get("worker_retry_profile"))
                cfg["effort"] = self._stronger_effort(cfg["effort"], retries.get("worker_retry_effort", "xhigh"))

        profile = self.policy["profiles"][cfg["profile"]]
        preference = list(self.policy.get("backends", {}).get("preference") or ["codex_exec"])
        recursive = bool((self.policy.get("delegation") or {}).get("recursive", False))
        context = self.policy.get("context") or {}
        selected = backend = None
        for model in profile.get("candidates", []):
            if not self.capabilities.supports_effort(model, cfg["effort"]):
                continue
            if not self.capabilities.supports_recursive_delegation(model, recursive):
                continue
            candidate_backend = self.capabilities.backend_for(model, preference)
            if candidate_backend:
                selected, backend = model, candidate_backend
                break
        if not selected:
            raise RuntimeError(f"No available model/backend for profile={cfg['profile']} effort={cfg['effort']}")
        model_meta = self.policy.get("models", {}).get(selected) or {}
        return {
            "dispatch_id": f"dsp_{uuid.uuid4().hex[:12]}",
            "role": role,
            "task_id": action.get("work_item"),
            "action": copy.deepcopy(action),
            "effective_risk": risk,
            "model": {"profile": cfg["profile"], "selected": selected, "reasoning_effort": cfg["effort"]},
            "execution": {
                "backend": backend,
                "sandbox": cfg.get("sandbox", "workspace-write"),
                "context_mode": context.get("default_mode", "capsule"),
                "native_fork_turns": context.get("native_fork_turns", "none"),
                "allow_recursive_delegation": recursive,
                "model_multi_agent": model_meta.get("multi_agent"),
            },
            "attempt": attempt,
        }


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

    def build(self, spec: dict[str, Any], rendered_packet: str, diagnosis: str | None = None,
              scout_digest: str | None = None) -> str:
        command = str((spec.get("action") or {}).get("command") or "")
        contract = self._role_contract_for(spec["role"], command)
        execution = spec.get("execution") or {}
        runtime_cli = self.plugin_root / "scripts" / "devflow.py"
        header = {
            "role": spec["role"],
            "task_id": spec.get("task_id"),
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
            "## Runtime packet\n" + rendered_packet,
        ]
        if scout_digest:
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
                "## Completion contract\nPerform read-only repository reconnaissance only. Return a compact digest of "
                "the exact files, symbols, contracts, tests, and risks the routed specialist should inspect. Do not mutate anything."
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


class AutopilotController:
    def __init__(self, status_fn: Callable[[], dict[str, Any]], render_fn: Callable[[dict[str, Any]], str],
                 route_fn: Callable[[dict[str, Any], dict[str, Any], int], dict[str, Any]],
                 dispatch_fn: Callable[[dict[str, Any], str], dict[str, Any]], ledger: RuntimeLedger | None,
                 max_steps: int = 100, max_no_progress: int = 3, *, run_id: str | None = None,
                 resume_state: dict[str, Any] | None = None, capabilities: CapabilityRegistry | None = None,
                 budget: TokenBudget | None = None, scout_before: set[str] | None = None):
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
        resume = resume_state or {}
        self.run_id = run_id or str(resume.get("run_id") or f"run_{uuid.uuid4().hex[:12]}")
        self.attempts = {str(k): int(v) for k, v in (resume.get("attempts") or {}).items()}
        self.diagnoses = {str(k): str(v) for k, v in (resume.get("diagnoses") or {}).items()}
        self.scouts = {str(k): str(v) for k, v in (resume.get("scouts") or {}).items()}
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

    def _checkpoint(self, status: str, *, action: dict[str, Any] | None = None,
                    reason: str | None = None, steps: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "run_id": self.run_id,
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
                if scout_spec is not None:
                    scout_receipt = self._dispatch(scout_spec, packet, step=step, budget_bucket=bucket)
                    if self._mark_capability_failure(scout_spec, scout_receipt):
                        scout_spec = self._route(scout_action, state, attempt)
                        if scout_spec is not None:
                            scout_receipt = self._dispatch(scout_spec, packet, step=step, budget_bucket=bucket)
                            self._mark_capability_failure(scout_spec, scout_receipt)
                    if scout_receipt.get("status") == "success":
                        digest = scout_receipt.get("message") or scout_receipt.get("stdout")
                        if isinstance(digest, str) and digest.strip():
                            self.scouts[fp] = digest.strip()
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
