#!/usr/bin/env python3
"""Bounded, read-only analysis of existing hosted telemetry and suite evidence.

This is advisory operational analysis, not a lifecycle or release decision.  It
never estimates billed tokens, child completion, or model quality from bytes.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import stat
import sys
from pathlib import Path
from typing import Any

MAX_INPUT = 16 * 1024 * 1024
MAX_LINE = 256 * 1024
MAX_OUTPUT = 4096
MAX_GROUPS = 6
MAX_SLOW_TESTS = 3
OUTCOMES = frozenset({"completed", "failed", "cancelled", "capability_blocked"})
SUITE_OUTCOMES = frozenset({
    "passed", "failed", "error", "skipped", "expected_failure", "unexpected_success",
})
DOMAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                          parse_constant=_invalid_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("invalid UTF-8 JSON evidence") from exc


def _read(path: Path, *, optional: bool = False) -> bytes | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError("requested evidence is absent") from None
    except OSError as exc:
        raise ValueError("cannot stat evidence") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("evidence must be a regular nonsymlinked file")
    if info.st_size > MAX_INPUT:
        raise ValueError("evidence exceeds 16 MiB input limit")
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_INPUT + 1)
    except OSError as exc:
        raise ValueError("cannot read evidence") from exc
    if len(raw) > MAX_INPUT:
        raise ValueError("evidence exceeds 16 MiB input limit")
    return raw


def _label(value: Any, name: str, maximum: int = 48) -> str:
    if (not isinstance(value, str) or not value or len(value) > maximum
            or not re.fullmatch(r"[A-Za-z0-9_.:-]+", value)):
        raise ValueError("invalid telemetry " + name)
    return value


def _number(value: Any, name: str, *, integer: bool = False) -> float | int:
    if integer:
        if type(value) is not int:
            raise ValueError("invalid " + name)
    elif type(value) not in (int, float):
        raise ValueError("invalid " + name)
    if not math.isfinite(value) or value < 0 or value > 1e9:
        raise ValueError("invalid " + name)
    return value


def _elapsed(row: dict) -> tuple[float | None, int | None]:
    observation = row.get("observations")
    if observation is None:
        return None, None  # v2 was not required to have caller observations.
    if not isinstance(observation, dict):
        raise ValueError("invalid telemetry observations")
    durations = observation.get("stage_duration_seconds") or {}
    context = observation.get("context_bytes") or {}
    if not isinstance(durations, dict) or not isinstance(context, dict):
        raise ValueError("invalid telemetry observations")
    wait = durations.get("child_wait")
    packet = context.get("packet")
    if wait is not None:
        wait = float(_number(wait, "child_wait"))
    if packet is not None:
        packet = int(_number(packet, "packet_bytes", integer=True))
    return wait, packet


def read_hosted(raw: bytes | None) -> dict:
    if raw is None:
        return {"source": "absent", "finished": 0, "unconfirmed_starts": 0,
                "unmatched_finishes": 0, "groups": [], "token_usage": "unmeasured"}
    starts: dict[str, dict] = {}
    finishes: dict[str, dict] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        if len(line) > MAX_LINE:
            raise ValueError("telemetry JSONL line exceeds 256 KiB")
        row = _decode(line)
        if not isinstance(row, dict) or type(row.get("schema_version")) is not int \
                or row["schema_version"] not in {2, 3}:
            raise ValueError("unsupported telemetry event")
        event = row.get("event")
        if event not in {"start", "finish"}:
            raise ValueError("invalid telemetry event type")
        dispatch = _label(row.get("dispatch_id"), "dispatch_id", 96)
        if row.get("token_usage") != "unmeasured":
            raise ValueError("unknown token usage semantics; refusing to infer billing")
        target = starts if event == "start" else finishes
        if dispatch in target:
            raise ValueError("duplicate telemetry event for dispatch")
        target[dispatch] = row
    groups: dict[tuple[str, str, str], dict] = {}
    outcomes = collections.Counter()
    retries = 0
    wall = 0.0
    wait = 0.0
    wait_count = 0
    packet_total = 0
    packet_count = 0
    for dispatch, row in finishes.items():
        role = _label(row.get("role"), "role")
        alias = _label(row.get("model_alias"), "model_alias")
        effort = _label(row.get("reasoning_effort"), "reasoning_effort", 16)
        attempt = int(_number(row.get("attempt"), "attempt", integer=True))
        outcome = row.get("outcome")
        if outcome not in OUTCOMES:
            raise ValueError("unknown telemetry outcome")
        seconds = float(_number(row.get("duration_seconds"), "duration_seconds"))
        started = starts.get(dispatch)
        if started:
            for key in ("role", "model_alias", "reasoning_effort", "attempt", "dispatch_kind"):
                if started.get(key) != row.get(key):
                    raise ValueError("telemetry start/finish mismatch")
        child_wait, packet = _elapsed(row)
        key = (role, alias, effort)
        group = groups.setdefault(key, {
            "role": role, "model_alias": alias, "effort": effort,
            "dispatches": 0, "completed": 0, "other_outcomes": 0,
            "retry_attempts": 0, "wall_seconds": 0.0,
        })
        group["dispatches"] += 1
        group["completed" if outcome == "completed" else "other_outcomes"] += 1
        group["retry_attempts"] += int(attempt > 0)
        group["wall_seconds"] += seconds
        outcomes[outcome] += 1
        retries += int(attempt > 0)
        wall += seconds
        if child_wait is not None:
            wait += child_wait
            wait_count += 1
        if packet is not None:
            packet_total += packet
            packet_count += 1
    ranked = sorted(groups.values(), key=lambda g: (-g["wall_seconds"], g["role"], g["model_alias"], g["effort"]))
    for group in ranked:
        group["wall_seconds"] = round(group["wall_seconds"], 3)
    return {
        "source": "read", "finished": len(finishes),
        "unconfirmed_starts": len(starts.keys() - finishes.keys()),
        "unmatched_finishes": len(finishes.keys() - starts.keys()),
        "outcomes": {key: outcomes[key] for key in sorted(OUTCOMES)},
        "retry_attempts": retries,
        "wall_seconds": round(wall, 3),
        "observed_child_wait": {"count": wait_count, "seconds": round(wait, 3)},
        "observed_packet_bytes": {"count": packet_count, "sum": packet_total},
        "groups": ranked[:MAX_GROUPS], "groups_omitted": max(0, len(ranked) - MAX_GROUPS),
        "token_usage": "unmeasured",
    }


def read_suite(raw: bytes) -> dict:
    data = _decode(raw)
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("tests"), list)
            or type(data.get("run")) is not int):
        raise ValueError("invalid suite evidence schema")
    rows = data["tests"]
    if len(rows) != data["run"] or len(rows) > 50000:
        raise ValueError("suite row count mismatch")
    counts = collections.Counter()
    seen: set[str] = set()
    slow: list[tuple[float, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid suite test row")
        name = _label(row.get("id"), "test_id", 256)
        if name in seen:
            raise ValueError("duplicate suite test ID")
        seen.add(name)
        status = row.get("status")
        if status not in SUITE_OUTCOMES:
            raise ValueError("invalid suite status")
        seconds = float(_number(row.get("seconds"), "test_seconds"))
        counts[status] += 1
        slow.append((seconds, name))
    if type(data.get("passed")) is not int or data["passed"] != counts["passed"]:
        raise ValueError("suite passed count mismatch")
    if type(data.get("selected")) is not int or data["selected"] != len(rows):
        raise ValueError("suite selection mismatch")
    if type(data.get("complete")) is not bool:
        raise ValueError("suite completeness invalid")
    slow.sort(key=lambda item: (-item[0], item[1]))
    return {
        "source": "read", "scope": "full" if data["complete"] else "partial",
        "profile": _label(data.get("profile"), "profile", 16),
        "run": len(rows), "passed": counts["passed"],
        "nonpassing": len(rows) - counts["passed"],
        "failed": counts["failed"], "errors": counts["error"],
        "skipped": counts["skipped"],
        "slowest": [{"id": name[:110], "seconds": round(seconds, 3)}
                    for seconds, name in slow[:MAX_SLOW_TESTS]],
        "authority": "historical_test_evidence_only",
    }


def report(*, telemetry: bytes | None = None, suite: bytes | None = None) -> dict:
    result = {
        "schema_version": 1,
        "authority": "advisory_not_release_or_lifecycle_evidence",
        "hosted": read_hosted(telemetry),
        "suite": read_suite(suite) if suite is not None else {"source": "not_provided"},
        "interpretation": [
            "wall_seconds includes supervisor overhead; child_wait is caller-reported",
            "completed child is not completed WORK; token usage and cost are unmeasured",
            "historical or partial suite results never replace a fresh release gate",
        ],
    }
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_OUTPUT:
        raise ValueError("aggregated report exceeds 4 KiB output bound")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--domain", metavar="DOMAIN", help="read existing .devflow/runtime/DOMAIN/host-dispatch.jsonl")
    source.add_argument("--telemetry", type=Path, help="read an explicitly named hosted dispatch JSONL file")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="repository root for --domain")
    parser.add_argument("--suite", type=Path, help="existing run_suite.py JSON report")
    args = parser.parse_args(argv)
    if not (args.domain or args.telemetry or args.suite):
        parser.error("provide --domain, --telemetry, or --suite")
    try:
        if args.domain:
            if not DOMAIN.fullmatch(args.domain):
                raise ValueError("domain must be a simple slug")
            base = (args.repo_root.resolve() / ".devflow" / "runtime").resolve()
            telemetry_path = base / args.domain / "host-dispatch.jsonl"
            if not telemetry_path.resolve().is_relative_to(base):
                raise ValueError("domain telemetry escapes runtime root")
            telemetry = _read(telemetry_path, optional=True)
        else:
            telemetry = _read(args.telemetry) if args.telemetry else None
        suite = _read(args.suite) if args.suite else None
        result = report(telemetry=telemetry, suite=suite)
    except (ValueError, OSError) as exc:
        print("DevFlow efficiency analysis error: " + str(exc)[:180], file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
