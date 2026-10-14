"""Measurement contracts shared by local lifecycle benchmarks and regression tests."""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

class BenchError(RuntimeError):
    """A fixture or expectation failed. Nothing measured after this point is valid."""


# ---------------------------------------------------------------- measurement core

@dataclass
class Row:
    label: str
    p50_ms: float | None = None
    p95_ms: float | None = None
    exit_codes: list[int] = field(default_factory=list)
    stdout_bytes: int | None = None
    reps: int = 0
    measurement: str = "timed"
    elapsed_ms_samples: list[float] = field(default_factory=list)
    stdout_bytes_samples: list[int] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "label": self.label,
            "measurement": self.measurement,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "reps": self.reps,
            "exit_codes": self.exit_codes,
            "stdout_bytes": self.stdout_bytes,
            "elapsed_ms_samples": self.elapsed_ms_samples,
            "stdout_bytes_samples": self.stdout_bytes_samples,
        }
        data.update(self.extra)
        return data


def utf8_len(text: str) -> int:
    """Bytes on the wire, not characters. `text=True` already decoded the stream."""
    return len(text.encode("utf-8"))


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; with 7 reps p95 is the slowest observed sample."""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(-(-fraction * len(ordered) // 1)) - 1))
    return ordered[index]


def spawn(script: Path, root: Path, args: list[str], *, timeout_seconds: float = 120
          ) -> tuple[float, subprocess.CompletedProcess]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args], cwd=root, text=True,
            capture_output=True, timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise BenchError(f"{' '.join(args)} timed out after {timeout_seconds} seconds") from exc
    return (time.perf_counter() - start) * 1000, proc


def check_run(
    label: str,
    proc: subprocess.CompletedProcess,
    *,
    expect: tuple[int, ...] = (0,),
    contains: tuple[str, ...] = (),
) -> None:
    if proc.returncode not in expect:
        raise BenchError(
            f"{label}: expected exit code in {expect}, got {proc.returncode}\n"
            f"stdout: {proc.stdout[-1500:]}\nstderr: {proc.stderr[-1500:]}"
        )
    blob = proc.stdout + proc.stderr
    for needle in contains:
        if needle.lower() not in blob.lower():
            raise BenchError(
                f"{label}: expected {needle!r} in output\n"
                f"stdout: {proc.stdout[-1500:]}\nstderr: {proc.stderr[-1500:]}"
            )


def check_json(label, proc, *, json_keys=(), json_values=None):
    """Validate response meaning as well as a successful process exit."""
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        raise BenchError(f"{label}: stdout is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise BenchError(f"{label}: JSON must be an object")
    missing = [key for key in json_keys if key not in payload]
    if missing:
        raise BenchError(f"{label}: JSON missing keys {missing}")
    for path, expected in (json_values or {}).items():
        value = payload
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise BenchError(f"{label}: JSON missing {path}")
            value = value[part]
        if value != expected:
            raise BenchError(
                f"{label}: JSON {path} expected {expected!r}, got {value!r}"
            )
    return payload


def time_command(
    root: Path,
    args: list[str],
    *,
    reps: int,
    expect: tuple[int, ...] = (0,),
    contains: tuple[str, ...] = (),
    script: Path,
    json_keys: tuple[str, ...] = (),
    json_values: dict[str, Any] | None = None,
    timeout_seconds: float = 120,
) -> Row:
    """Run one real CLI invocation `reps` times and gate every sample on its result."""
    if reps < 1:
        raise BenchError("reps must be positive")
    times: list[float] = []
    codes: list[int] = []
    sizes: list[int] = []
    size = 0
    for index in range(reps):
        elapsed, proc = spawn(script, root, args, timeout_seconds=timeout_seconds)
        check_run(f"{' '.join(args)} rep {index + 1}/{reps}", proc, expect=expect,
                  contains=contains)
        if json_keys or json_values:
            check_json(" ".join(args), proc, json_keys=json_keys, json_values=json_values)
        times.append(elapsed)
        codes.append(proc.returncode)
        size = utf8_len(proc.stdout)
        sizes.append(size)
    return Row(
        label=" ".join(args),
        p50_ms=round(statistics.median(times), 2),
        p95_ms=round(percentile(times, 0.95), 2),
        exit_codes=codes,
        stdout_bytes=size,
        reps=reps,
        measurement="timed",
        elapsed_ms_samples=times,
        stdout_bytes_samples=sizes,
    )


