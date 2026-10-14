#!/usr/bin/env python3
"""Reproducible benchmark for the DevFlow hosted Goal lifecycle (roadmap W0 / R00).

    python3 plugins/devflow/tests/bench_goal_lifecycle.py --include-expensive
    python3 plugins/devflow/tests/bench_goal_lifecycle.py --self-check   # fixture gate only
    python3 plugins/devflow/tests/bench_goal_lifecycle.py --json out.json

Requires Python 3.10+ and PyYAML, the same runtime DevFlow needs. No DevFlow command runs
against a real repository: every fixture is a throwaway git repository under one
`TemporaryDirectory` that is removed even when a section fails.

Contract for every number printed here:

  * A fixture that the runtime rejects is never reported as a measurement. Each fixture is
    built through the public CLI and must reach its own expected exit code first.
  * Source files, comment anchors, delivery artifacts and Newman receipts are produced by
    the real runtime, not hand-written into STATE.yaml.
  * Tampering fixtures exist only to prove that valid evidence is accepted and altered
    evidence is refused. Each one asserts the specific refusal reason, then restores the
    fixture and asserts the same fixture validates again.
  * Rows carry `measurement`: `timed` rows have p50/p95 over `--reps` samples, `single` rows
    are one-shot counters or byte sizes where repetition adds nothing.
  * Tokens are never estimated. Byte counts are measured; token counts are `unmeasured`.
  * Scaling rows only vary the variable under test. Every row also records the lifecycle
    stage it ran at, so a state difference can never be read as a cost difference.

The tracked entry point and test helpers ship with the shared plugin. Result JSON stays
local. Synthetic Newman reports measure validation I/O, not real API or native agent cost.
Use --section or --include-expensive to opt into large raw-report and delivered-WORK sweeps.

Sections:
    integrity    valid fixtures pass, altered evidence is rejected with its reason
    git          F03 Git subprocess count per delivered WORK, real commits and anchors
    newman       F04 accumulated Newman raw re-hash at one fixed lifecycle stage
    ceiling      F04 raw-report size ceiling: 32 MiB accepted, 32 MiB + 1 refused
    scout        F05 Scout routed vs not routed: dispatch shape and input bytes
    projection   F02 lifecycle projection cost by WORK count
    paths        per-command wall clock for the hosted execution paths
    packets      F06 role input bytes actually rendered by the current next action
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter
from contextlib import ExitStack
import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

PLUGIN = Path(__file__).resolve().parent.parent
if not (PLUGIN / "scripts" / "devflow.py").is_file():
    raise SystemExit(
        "Run this script from inside the devflow repository checkout, "
        "or set PLUGIN manually below."
    )

CLI = PLUGIN / "scripts" / "devflow.py"
HOST = PLUGIN / "scripts" / "devflow_host.py"

_spec = importlib.util.spec_from_file_location(
    "devflow_test_helpers", PLUGIN / "tests" / "test_devflow.py"
)
t = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t)

sys.path.insert(0, str(PLUGIN / "scripts"))


def runtime_module():
    """The runtime module the CLI subprocesses actually execute."""
    import devflow

    return devflow

WORK_SIZES = (8, 36, 120, 250)
ANCHOR_COUNTS = (1, 4)
NEWMAN_RUNS = (0, 5, 10, 20)
NEWMAN_HISTORIES = ("none", "clean", "recovered")
NEWMAN_RAW_MIB = (1, 4, 8)
RAW_REPORT_LIMIT = 32 * 1024 * 1024
FINALIZE_WORK_SIZES = (60, 120, 250)
# One delivered-domain size keeps the provenance contrast affordable; the renderer cost is
# per WORK, so one point is enough to separate it from the grandfathered sweep above.
DELIVERED_WORK_SIZE = 60
PR_TEMPLATE = (
    "# Summary\n\n<!-- Describe changes. -->\n\n"
    "## Verification\n\n<!-- Commands and results. -->\n"
)
# The F04 scaling rows must not drift between lifecycle stages. Every history shape is
# measured with finalization still pending, so only the accumulated evidence differs.
NEWMAN_SCALING_STAGE = ("finalize", "project", None)
UNMEASURED = [
    {
        "item": "agent token usage (F16/N04)",
        "reason": "devflow_host guard reports token_usage='unmeasured'; the host does not "
        "expose per-child token counts to the runtime",
    },
    {
        "item": "native hosted Goal end-to-end wall clock and spawn count",
        "reason": "requires a real Codex/Claude Code host session; this script drives the "
        "CLI and guard only, never spawn_agent",
    },
    {
        "item": "Scout capsule spawn cost (F05/N02)",
        "reason": "Scout cost depends on the spawned child model; measured bytes only",
    },
    {
        "item": "cold page cache Newman re-hash",
        "reason": "dropping the OS page cache needs write access to /proc/sys/vm/drop_caches",
    },
]


# Measurement validation ships with the shared regression suite; fixtures remain local.
from functools import partial
sys.path.insert(0, str(PLUGIN / "tests"))
from benchmark_helpers import (
    BenchError, Row, check_json, check_run, percentile, spawn, time_command as measure_command, utf8_len,
)

time_command = partial(measure_command, script=CLI)


def count_git_subprocesses(root: Path, runtime: Any, args: list[str]) -> Row:
    """Count real git subprocesses issued by one in-process CLI run, by subcommand."""
    real_run = subprocess.run
    verbs: Counter[str] = Counter()
    callers: Counter[str] = Counter()
    outside_git: Counter[str] = Counter()
    try:
        def counting(cmd, *rest, **kwargs):
            if isinstance(cmd, (list, tuple)) and len(cmd) > 1 and cmd[0] == "git":
                verbs[cmd[1]] += 1
                callers[inspect.currentframe().f_back.f_globals.get("__name__", "unknown")] += 1
            elif isinstance(cmd, (list, tuple)) and cmd:
                outside_git[str(cmd[0])] += 1
            return real_run(cmd, *rest, **kwargs)

        subprocess.run = counting
        proc = t.invoke_runtime(root, runtime, *args)
    finally:
        subprocess.run = real_run
    check_run(f"git-count {' '.join(args)}", proc)
    return Row(
        label=" ".join(args),
        exit_codes=[proc.returncode],
        reps=1,
        measurement="single",
        extra={"git_calls": dict(sorted(verbs.items())), "git_total": sum(verbs.values()),
               "git_caller_modules": dict(sorted(callers.items())),
               "other_subprocesses": dict(sorted(outside_git.items()))},
    )


def count_yaml_loads(root: Path, runtime: Any, args: list[str]) -> Row:
    """Count YAML reads and WORK index projections performed by one in-process run."""
    real_load_yaml, real_index = runtime.load_yaml, runtime.load_work_index
    real_build = runtime.index_work_docs
    calls: Counter[str] = Counter()
    files: set[str] = set()
    try:
        def load_yaml(path, default=None):
            calls["load_yaml"] += 1
            files.add(str(path))
            if Path(path).parent.name == "work":
                calls["work_yaml_loads"] += 1
            if Path(path).is_file():
                calls["parsed_yaml_bytes"] += Path(path).stat().st_size
            return real_load_yaml(path, default)

        def load_work_index(d, overrides=None):
            calls["load_work_index"] += 1
            return real_index(d, overrides)

        def index_work_docs(docs):
            calls["work_index_builds"] += 1
            return real_build(docs)

        runtime.load_yaml, runtime.load_work_index = load_yaml, load_work_index
        runtime.index_work_docs = index_work_docs
        proc = t.invoke_runtime(root, runtime, *args)
    finally:
        runtime.load_yaml, runtime.load_work_index = real_load_yaml, real_index
        runtime.index_work_docs = real_build
    check_run(f"yaml-count {' '.join(args)}", proc)
    return Row(
        label=" ".join(args),
        exit_codes=[proc.returncode],
        reps=1,
        measurement="single",
        extra={
            "yaml_loads": calls["load_yaml"],
            "work_index_requests": calls["load_work_index"],
            "work_index_builds": calls["work_index_builds"],
            "work_yaml_loads": calls["work_yaml_loads"],
            "distinct_yaml_files": len(files),
            "parsed_yaml_bytes": calls["parsed_yaml_bytes"],
        },
    )


sandbox_root: Path
_fixture_index = 0


def new_sandbox() -> Path:
    """A fresh throwaway repository; the run's TemporaryDirectory removes every one of them."""
    global _fixture_index
    _fixture_index += 1
    root = sandbox_root / f"case{_fixture_index:03d}"
    root.mkdir(parents=True)
    return root


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)
    if proc.returncode:
        raise BenchError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def init_repo(root: Path) -> None:
    git(root, "init", "-q", ".")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")
    (root / "seed.txt").write_text("seed\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")


def tree_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


# ---------------------------------------------------------------- fixtures

def delivery_cli(root: Path, runtime: Any):
    """In-process CLI. Fixture construction never needs subprocess timing."""

    def cli(*args: str):
        with patch("argparse.ArgumentParser.exit",
                   side_effect=ValueError("unsupported CLI command")):
            return t.invoke_runtime(root, runtime, *args)

    return cli


def require(label: str, proc, expect: tuple[int, ...] = (0,)):
    check_run(label, proc, expect=expect)
    return proc


def source_with_anchors(item_id: str, anchors: int) -> str:
    """`anchors` distinct comment lines occupy lines 1..anchors, then plain functions."""
    head = [f"# Anchor {i + 1} states the {item_id} invariant that must survive refactoring."
            for i in range(anchors)]
    body = [f"def handler_{i}():\n    return {i}\n" for i in range(anchors)]
    return "\n".join(head + body)


def build_delivery_domain(*, done: int = 1, anchors: int = 1) -> dict[str, Any]:
    """A delivery domain whose done WORK carry real commits, real anchors and real artifacts.

    Every WORK goes through `work start` -> real source commit -> PR/Postman -> `work done`,
    so `validate` only succeeds when the runtime itself accepts the evidence.
    """
    root = new_sandbox()
    init_repo(root)
    runtime = t.load_runtime_module()
    cli = delivery_cli(root, runtime)
    require("init billing", cli("init", "billing"))
    d = root / "docs/domains/billing"
    t.fill_delivery_contract(d)
    base = git(root, "rev-parse", "HEAD")
    git(root, "branch", "delivery-base", base)
    git(root, "switch", "-c", "feature/billing")
    template = root / "docs/PR/templates.md"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(PR_TEMPLATE, encoding="utf-8")

    state = t.state({"01": t.phase("executing", "01")})
    state["baseline_sha"] = base
    state["target_sha"] = base
    t.dump(d / "STATE.yaml", state)
    ids = [f"P01-I{i:02d}" for i in range(1, done + 1)]
    t.dump(d / "work/phase-01.yaml", t.work_v2("01", *[t.v2_item(i) for i in ids]))
    # The STATE rewrite above drops the init-time delivery policy; adopt it explicitly.
    require("delivery enable", cli("delivery", "enable", "billing"))

    for item_id in ids:
        require(f"work start {item_id}", cli("work", "start", "billing", item_id))
        rel = f"src/{item_id.lower()}.py"
        source = root / rel
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(source_with_anchors(item_id, anchors), encoding="utf-8")
        git(root, "add", rel)
        git(root, "commit", "-qm", f"implement {item_id}")
        head = git(root, "rev-parse", "HEAD")
        paths = json.loads(require(f"delivery paths {item_id}",
                                   cli("delivery", "paths", "billing")).stdout)
        meta = {"branch": paths["branch"], "base_sha": base, "head_sha": head}
        pr = root / paths["pr_file"]
        pr.parent.mkdir(parents=True, exist_ok=True)
        pr.write_text(
            "<!-- devflow-delivery: " + json.dumps(meta) + " -->\n"
            f"# Summary\n\nDelivers {item_id} with its verified evidence anchors.\n\n"
            "## Verification\n\nUnit checks executed against the delivered branch.\n",
            encoding="utf-8",
        )
        collection = {
            "info": {
                "name": "Billing",
                "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                "description": "Local fixture collection. Configure credentials before manual use.",
                "_devflow": meta,
            },
            "variable": [
                {"key": "baseUrl", "value": "http://localhost:8080"},
                {"key": "accessToken", "value": ""},
            ],
            "auth": {"type": "bearer",
                     "bearer": [{"key": "token", "value": "{{accessToken}}", "type": "string"}]},
            "item": [{
                "name": "Get sample",
                "request": {"method": "GET", "url": "{{baseUrl}}/api/sample", "header": []},
                "event": [{"listen": "test", "script": {"type": "text/javascript",
                        "exec": ['pm.test("Status", () => pm.response.to.have.status(200));']}}],
            }],
        }
        postman = root / paths["postman_file"]
        postman.parent.mkdir(parents=True, exist_ok=True)
        postman.write_text(json.dumps(collection, indent=2), encoding="utf-8")

        doc = yaml.safe_load((d / "work/phase-01.yaml").read_text(encoding="utf-8"))
        entry = next(item for item in doc["items"] if item["id"] == item_id)
        entry["evidence"]["comments"] = [
            {"path": rel, "line": i + 1,
             "reason": f"Anchor {i + 1} states the preserved {item_id} invariant."}
            for i in range(anchors)
        ]
        entry["evidence"].setdefault("delivery", {}).update({
            "base_ref": "delivery-base",
            "pr_file": paths["pr_file"],
            "postman_file": paths["postman_file"],
            "api_endpoints": ["GET /api/sample"],
            "api_note": "Covers the changed sample endpoint.",
        })
        t.dump(d / "work/phase-01.yaml", doc)
        require(f"work done {item_id}",
                cli("work", "done", "billing", item_id, "--commit", head,
                    "--command", "unit checks -> passed"))
    require("validate (fixture gate)", cli("validate", "billing"))
    return {"root": root, "runtime": runtime, "cli": cli, "domain_dir": d, "base": base}


def newman_report(target_bytes: int = 0) -> dict[str, Any]:
    """A Newman-shaped report. `run.stdout` padding is what a large real report carries."""
    return {
        "run": {
            "stats": {
                "requests": {"total": 1, "failed": 0},
                "assertions": {"total": 1, "failed": 0, "pending": 0},
            },
            "failures": [],
            "executions": [{
                "item": {"name": "Get sample"},
                "response": {"code": 200},
                "assertions": [{"assertion": "Status", "skipped": False}],
            }],
        },
        "stdout": "",
    }


def report_padding(target_bytes: int) -> int:
    """Padding that makes the serialized report exactly `target_bytes`, never larger.

    JSON escaping of the surrounding keys is part of the target, so the empty-stdout
    skeleton is serialized first and its real byte length subtracted. A non-positive target
    means "no padding", which is what the failed-run fixture uses.
    """
    if target_bytes <= 0:
        return 0
    overhead = utf8_len(json.dumps(newman_report()))
    padding = target_bytes - overhead
    if padding < 0:
        raise BenchError(
            f"Newman raw target {target_bytes} B is smaller than the report envelope {overhead} B"
        )
    return padding


def fake_newman(root: Path, *, failure: bool = False, target_bytes: int = 0) -> Path:
    """A Newman stand-in that emits a real report of an exact byte size."""
    runner = root / "runner-bin/newman"
    runner.parent.mkdir(parents=True, exist_ok=True)
    report = newman_report()
    if failure:
        report["run"]["stats"]["assertions"]["failed"] = 1
        report["run"]["failures"] = [{"error": {"name": "AssertionError",
                                                "message": "fixture-only failure detail"}}]
    runner.write_text(
        "#!" + sys.executable + " -S\n"
        "import sys, json, pathlib\n"
        'if "--version" in sys.argv:\n    print("6.2.1")\n    sys.exit(0)\n'
        "target = pathlib.Path(sys.argv[sys.argv.index('--reporter-json-export') + 1])\n"
        "payload = " + repr(report) + "\n"
        "payload['stdout'] = 'x' * " + str(report_padding(target_bytes)) + "\n"
        "target.write_text(json.dumps(payload))\n"
        "print('fixture newman output')\n"
        "sys.exit(" + str(1 if failure else 0) + ")\n",
        encoding="utf-8",
    )
    runner.chmod(0o755)
    return runner


HTTP_SERVER_SOURCE = """\
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def owned_server_command(root: Path, port: int) -> list[str]:
    """A real loopback HTTP server, so readiness is an executed check, not a mock."""
    # .txt on purpose: any untracked source-suffix file blocks the Newman preflight.
    script = root / "owned-server.txt"
    script.write_text(HTTP_SERVER_SOURCE, encoding="utf-8")
    return [sys.executable, str(script), str(port)]


def lifecycle_stage(root: Path, domain_dir: Path) -> dict[str, Any]:
    """The lifecycle facts a reader needs to tell a cost difference from a state difference."""
    state = yaml.safe_load((domain_dir / "STATE.yaml").read_text(encoding="utf-8"))
    action = (state.get("next_action") or {})
    fin = (state.get("delivery") or {}).get("finalization") or {}
    return {
        "next_command": action.get("command"),
        "next_scope": action.get("scope"),
        "next_phase": action.get("phase"),
        "next_reason": action.get("reason"),
        "project_status": state.get("project_status"),
        "eli5_recorded": isinstance(fin.get("explanation"), dict),
        "finalize_receipt": isinstance(fin.get("receipt"), dict),
        "newman_statuses": [run.get("status") for run in fin.get("runs", [])],
        "grandfathered_work_ids": (state.get("delivery") or {}).get(
            "grandfathered_work_ids", []),
    }


def finalize_domain(ctx: dict[str, Any], *, runs: int, target_bytes: int,
                    recovered: bool, complete: bool = True,
                    expect_status: tuple[str, ...] = ("passed",),
                    expect_code: int = 0) -> dict[str, Any]:
    """Close the phase audit, then accumulate real Newman runs plus optional ELI5 evidence.

    `complete=False` stops at the same lifecycle stage for every run count, so F04 scaling
    rows differ only in accumulated evidence.
    """
    root, cli, d = ctx["root"], ctx["cli"], ctx["domain_dir"]
    require("phase ref", cli("phase", "ref", "billing", "01",
                             "--base", "delivery-base", "--head", "feature/billing"))
    t.write_audit(d / "audits/phase-01.md", t.audit_metadata(d, scope="phase"))
    require("audit apply (phase)", cli("audit", "apply", "billing", "--scope", "phase",
                                       "--phase", "01", "--mode", "initial"))

    head = git(root, "rev-parse", "HEAD")

    def run_newman(failure: bool) -> str:
        runner = fake_newman(root, failure=failure,
                             target_bytes=0 if failure else target_bytes)
        port = free_port()
        args = [
            "delivery", "newman", "billing", "--branch", "feature/billing",
            "--newman-bin", str(runner), "--base-url", f"http://127.0.0.1:{port}",
            "--server-sha", head,
            "--safety-note",
            "Disposable local server, synthetic fixtures, no live integrations.",
            "--server-command", json.dumps(owned_server_command(root, port)),
            "--readiness-url", f"http://127.0.0.1:{port}/health",
            "--readiness-timeout", "10",
        ]
        result = cli(*args)
        expected = expect_code if not failure else 1
        if result.returncode != expected:
            raise BenchError(
                f"delivery newman exited {result.returncode}, expected {expected}\n"
                f"stderr: {result.stderr[-800:]}"
            )
        recorded = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
        return recorded["delivery"]["finalization"]["runs"][-1]["status"]

    if recovered and runs:
        run_newman(True)
        failed = yaml.safe_load((d / "STATE.yaml").read_text(encoding="utf-8"))
        failed_run = failed["delivery"]["finalization"]["runs"][-1]
        require("delivery triage", cli(
            "delivery", "triage", "billing", "--run-id", failed_run["id"],
            "--classification", "environment",
            "--reason", "The fixture process used the wrong database; source build and "
                        "API contract agree, so no code repair WORK applies."))
    for _ in range(runs):
        status = run_newman(False)
        if status not in expect_status:
            raise BenchError(f"delivery newman recorded {status!r}, expected {expect_status}")

    if not complete:
        return ctx
    return complete_finalize_domain(ctx)


def phase_domain(total: int) -> Path:
    """A single phase with `total` WORK and no delivery policy: pure projection cost."""
    root = new_sandbox()
    init_repo(root)
    d = root / "docs/domains/billing"
    (d / "work").mkdir(parents=True, exist_ok=True)
    entries = [t.item(f"P01-I{i:02d}") for i in range(1, total + 1)]
    t.dump(d / "work/phase-01.yaml", t.work("01", *entries))
    t.dump(d / "STATE.yaml", t.state({"01": t.phase("executing", "01")}))
    return root


def sized_delivery_domain(total: int, *, done: bool = True) -> Path:
    """A delivery domain with `total` WORK. Terminal WORK makes `finalize` the next action;
    ready WORK makes `run` the next action, which is what a worker child receives.

    `delivery enable` runs while these WORK are already terminal, so the runtime
    grandfathers every one of them. Those WORK therefore carry no commit, PR or Postman
    provenance and are NOT a stand-in for a delivered branch. `delivery_work_state` reports
    what actually happened so packet sizes can never be read the wrong way.
    """
    root = new_sandbox()
    init_repo(root)
    runtime = t.load_runtime_module()
    cli = delivery_cli(root, runtime)
    require(f"init billing ({total})", cli("init", "billing"))
    d = root / "docs/domains/billing"
    t.fill_delivery_contract(d)
    template = root / "docs/PR/templates.md"
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text(PR_TEMPLATE, encoding="utf-8")
    head = git(root, "rev-parse", "HEAD")
    state = t.state({"01": t.phase("verified" if done else "executing", "01")})
    state["baseline_sha"] = head
    state["target_sha"] = head
    t.dump(d / "STATE.yaml", state)
    entries = []
    for i in range(1, total + 1):
        entry = t.v2_item(f"P01-I{i:02d}")
        entry["status"] = "done" if done else "ready"
        if done:
            # evidence.commands is a list of executed command strings, not mappings.
            entry["evidence"]["commands"] = ["true -> passed"]
        entries.append(entry)
    t.dump(d / "work/phase-01.yaml", t.work_v2("01", *entries))
    require(f"delivery enable ({total})", cli("delivery", "enable", "billing"))
    if done:
        # A verified phase must own its canonical audit artifact.
        t.write_audit(d / "audits/phase-01.md", t.audit_metadata(d, scope="phase"))
    require(f"validate (sized delivery domain {total})", cli("validate", "billing"))
    return root


def delivery_work_state(root: Path) -> dict[str, Any]:
    """Grandfathered vs provenance-bearing WORK, read back from the runtime's own STATE."""
    state = yaml.safe_load((root / "docs/domains/billing/STATE.yaml").read_text(encoding="utf-8"))
    policy = state.get("delivery") or {}
    grandfathered = list(policy.get("grandfathered_work_ids") or [])
    docs = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted((root / "docs/domains/billing/work").glob("*.yaml"))
    }
    done = [item for doc in docs.values() for item in doc.get("items", [])
            if item.get("status") == "done"]
    with_provenance = [item for item in done
                       if isinstance((item.get("evidence") or {}).get("delivery"), dict)]
    return {
        "done_work": len(done),
        "grandfathered_work_ids": len(grandfathered),
        "done_work_with_delivery_provenance": len(with_provenance),
        "delivery_branches_recorded": len(policy.get("branches") or {}),
    }


# ---------------------------------------------------------------- sections

def section_integrity(reps: int) -> tuple[list[Row], list[dict[str, Any]]]:
    """Valid evidence must pass; altered evidence must be refused. Timings live elsewhere."""
    rows: list[Row] = []
    checks: list[dict[str, Any]] = []

    def note(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": passed, "detail": detail})
        if not passed:
            raise BenchError(f"integrity check failed: {name}. {detail}")

    ctx = build_delivery_domain(done=3, anchors=4)
    root, runtime = ctx["root"], ctx["runtime"]
    work_file = root / "docs/domains/billing/work/phase-01.yaml"
    cli = ctx["cli"]
    baseline = count_git_subprocesses(root, runtime, ("validate", "billing"))
    baseline.extra.update({"done_work": 3, "anchors": 4,
                           "git_calls_per_work": round(baseline.extra["git_total"] / 3, 2)})
    rows.append(baseline)
    note("valid 3-WORK/4-anchor fixture validates", True)

    state = yaml.safe_load((root / "docs/domains/billing/STATE.yaml").read_text())
    work = yaml.safe_load(work_file.read_text())
    item = work["items"][0]
    branch_record = state["delivery"]["branches"]["feature/billing"]
    saved_commit = item["evidence"]["commit"]
    saved_comments = list(item["evidence"]["comments"])

    def rewrite(mutate) -> None:
        document = yaml.safe_load(work_file.read_text())
        mutate(document["items"][0])
        t.dump(work_file, document)

    def tamper(label: str, apply, revert, reason: str, command: tuple[str, ...]) -> None:
        apply()
        try:
            refusal = expect_refused(label, cli, command, reason)
        finally:
            revert()
        require(f"{label}: restored fixture validates", cli(*command))
        checks.append({"check": f"{label} refused with its own reason", "passed": True,
                       "detail": (refusal or "").strip()[-300:]})
        checks.append({"check": f"{label} restored fixture validates", "passed": True,
                       "detail": ""})

    tamper(
        "non-comment anchor",
        lambda: rewrite(lambda i: i["evidence"].update(
            {"comments": [{"path": "src/p01-i01.py", "line": 5,
                           "reason": "anchor on a plain statement"}]})),
        lambda: rewrite(lambda i: i["evidence"].update({"comments": saved_comments})),
        "does not point to a substantive source comment",
        ("validate", "billing"),
    )
    tamper(
        "forged evidence commit",
        lambda: rewrite(lambda i: i["evidence"].update({"commit": "0" * 40})),
        lambda: rewrite(lambda i: i["evidence"].update({"commit": saved_commit})),
        "comment source provenance",
        ("validate", "billing"),
    )

    pr = root / branch_record["pr_file"]
    original_pr = pr.read_text(encoding="utf-8")
    tamper(
        "edited PR artifact",
        lambda: pr.write_text(original_pr + "\nEdited after the recorded hash.\n",
                              encoding="utf-8"),
        lambda: pr.write_text(original_pr, encoding="utf-8"),
        "stale pr_sha256",
        ("validate", "billing"),
    )

    finalize_domain(ctx, runs=2, target_bytes=1024 * 1024, recovered=True)
    recorded = yaml.safe_load((root / "docs/domains/billing/STATE.yaml").read_text())
    raw_path = root / recorded["delivery"]["finalization"]["runs"][-1]["raw_file"]
    raw_bytes = raw_path.read_bytes()
    # Same-stage reference, so the comparison is not against a pre-finalization fixture.
    reference = count_git_subprocesses(root, runtime, ("validate", "billing"))
    tamper(
        "tampered Newman raw report",
        lambda: raw_path.write_bytes(raw_bytes + b" "),
        lambda: raw_path.write_bytes(raw_bytes),
        "Newman raw report hash changed",
        ("delivery", "finalize", "billing"),
    )
    # The same fixture must cost exactly what it did before the last tamper cycle.
    after = count_git_subprocesses(root, runtime, ("validate", "billing"))
    if after.extra["git_calls"] != reference.extra["git_calls"]:
        raise BenchError(
            "fixture drifted across tamper cycles: git calls "
            f"{reference.extra['git_calls']} -> {after.extra['git_calls']}"
        )
    rows.append(after)
    checks.append({"check": "fixture unchanged after all tamper cycles", "passed": True,
                   "detail": json.dumps(after.extra["git_calls"], sort_keys=True)})
    return rows, checks


def expect_refused(label: str, cli, command: tuple[str, ...], reason: str) -> str:
    """Exit code alone is not proof: the refusal must name the contract that rejected it."""
    result = cli(*command)
    if result.returncode == 0:
        raise BenchError(f"{label}: tampered evidence was accepted (exit 0)")
    output = result.stdout + result.stderr
    if reason.lower() not in output.lower():
        raise BenchError(
            f"{label}: refused for an unexpected reason; expected {reason!r}\n"
            f"stdout: {result.stdout[-1500:]}\nstderr: {result.stderr[-1500:]}"
        )
    return output


def section_git(reps: int) -> list[Row]:
    """F03. Git subprocess cost per delivered WORK, on real commits with real anchors."""
    rows = []
    for done in (5, 20, 40):
        for anchors in ANCHOR_COUNTS:
            ctx = build_delivery_domain(done=done, anchors=anchors)
            root, runtime = ctx["root"], ctx["runtime"]
            row = count_git_subprocesses(root, runtime, ("validate", "billing"))
            row.extra.update({"done_work": done, "anchors": anchors,
                              "git_calls_per_work": round(
                                  row.extra["git_total"] / done, 2)})
            rows.append(row)
            row = count_git_subprocesses(root, runtime, ("delivery", "check", "billing"))
            row.extra.update({"done_work": done, "anchors": anchors})
            rows.append(row)
    return rows


def newman_fixture(history: str, runs: int, target_bytes: int) -> dict[str, Any]:
    """Build one Newman history and assert every shape stops at the same lifecycle stage."""
    ctx = build_delivery_domain(done=5, anchors=1)
    finalize_domain(
        ctx, runs=runs, target_bytes=target_bytes,
        recovered=history == "recovered", complete=False,
    )
    stage = lifecycle_stage(ctx["root"], ctx["domain_dir"])
    observed = (stage["next_command"], stage["next_scope"], stage["next_phase"])
    if observed != NEWMAN_SCALING_STAGE:
        raise BenchError(
            f"F04 scaling drifted across lifecycle stages: {history}/{runs} runs sits at "
            f"{observed}, expected {NEWMAN_SCALING_STAGE}"
        )
    if stage["eli5_recorded"] or stage["finalize_receipt"]:
        raise BenchError(f"F04 scaling must stay pre-finalization: {stage}")
    recorded = yaml.safe_load(
        (ctx["domain_dir"] / "STATE.yaml").read_text(encoding="utf-8")
    )["delivery"]["finalization"]["runs"]
    expected_runs = runs + (1 if history == "recovered" and runs else 0)
    if len(recorded) != expected_runs:
        raise BenchError(f"F04 fixture recorded {len(recorded)} runs, expected {expected_runs}")
    ctx["recorded"] = recorded
    return ctx


def count_evidence_io(root: Path, runtime: Any, args: list[str]) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    real_bytes, real_text, real_hash = Path.read_bytes, Path.read_text, hashlib.sha256

    def record(path, size):
        category = None
        if path.is_relative_to(root / ".devflow/private/newman"):
            category = "raw" if path.name == "report.json" else "server_log"
        elif path.is_relative_to(root / "docs/postman") and path.name.endswith(".summary.json"):
            category = "summary"
        if category:
            counts["evidence_read_calls"] += 1
            counts["evidence_read_bytes"] += size
            counts[category + "_read_calls"] += 1
            counts[category + "_read_bytes"] += size

    def read_bytes(path):
        data = real_bytes(path)
        record(path, len(data))
        return data

    def read_text(path, *rest, **kwargs):
        data = real_text(path, *rest, **kwargs)
        record(path, utf8_len(data))
        return data

    def sha256(data=b"", **kwargs):
        counts["sha256_calls"] += 1
        counts["sha256_input_bytes"] += len(data)
        return real_hash(data, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "read_bytes", read_bytes))
        stack.enter_context(patch.object(Path, "read_text", read_text))
        stack.enter_context(patch.object(hashlib, "sha256", sha256))
        proc = t.invoke_runtime(root, runtime, *args)
    check_run("evidence-io " + " ".join(args), proc)
    return {"validation_io": dict(sorted(counts.items())),
            "hash_scope": "all sha256 calls during one real in-process CLI invocation"}


def _newman_row(root: Path, ctx: dict[str, Any], history: str, runs: int,
                target_bytes: int, args: list[str], reps: int,
                series: str) -> Row:
    recorded = ctx["recorded"]
    raw_files = [root / r["raw_file"] for r in recorded if r.get("raw_file")]
    total_bytes = sum(p.stat().st_size for p in raw_files)
    row = time_command(root, args, reps=reps)
    row.extra.update(count_evidence_io(root, ctx["runtime"], args))
    row.extra.update({
        "series": series,
        "history": history,
        "requested_runs": runs,
        "recorded_runs": len(recorded),
        "raw_target_bytes_each": target_bytes,
        "raw_bytes_total": total_bytes,
        "raw_sha256_ms_warm": round(_hash_cost(raw_files), 2),
        "cold_cache": _cold_cache_status(),
        "sandbox_bytes": tree_bytes(root),
        **lifecycle_stage(root, ctx["domain_dir"]),
    })
    return row


def section_newman(reps: int) -> list[Row]:
    """F04. Accumulated Newman evidence re-hash, with the lifecycle stage held constant.

    Every scaling row is pre-finalization at the same `next_action`, so the only variable is
    how much recorded evidence exists. The last row deliberately changes the stage and is
    reported as a control, never as part of the series.
    """
    rows: list[Row] = []
    targets = [mib * 1024 * 1024 for mib in NEWMAN_RAW_MIB]
    commands = (("status", ["status", "billing"]),
                ("validate", ["validate", "billing"]),
                ("delivery check", ["delivery", "check", "billing"]))

    # A. Run-count scaling at one fixed raw size, across all three history shapes.
    for history in NEWMAN_HISTORIES:
        for runs in NEWMAN_RUNS:
            if (history == "none") != (runs == 0):
                continue
            ctx = newman_fixture(history, runs, targets[0])
            for _label, args in commands:
                rows.append(_newman_row(ctx["root"], ctx, history, runs, targets[0], args,
                                        reps, "run_count"))

    # B. Byte scaling at one fixed run count.
    for target in targets:
        ctx = newman_fixture("clean", 20, target)
        rows.append(_newman_row(ctx["root"], ctx, "clean", 20, target, ["status", "billing"],
                                reps, "byte_sweep"))

    # C. Stage control: identical evidence, next lifecycle stage.
    control = newman_fixture("clean", 20, targets[-1])
    complete_finalize_domain(control)
    stage = lifecycle_stage(control["root"], control["domain_dir"])
    if stage["next_command"] != "audit" or not stage["eli5_recorded"]:
        raise BenchError(f"stage control did not reach the post-finalization stage: {stage}")
    rows.append(_newman_row(control["root"], control, "clean", 20, targets[-1],
                            ["status", "billing"], reps, "stage_control"))
    return rows


def section_ceiling(reps: int) -> list[Row]:
    """F04. The 32 MiB raw ceiling: at the limit accepted, one byte over refused."""
    rows: list[Row] = []
    for label, target, expected_status, expected_code in (
            ("at_limit", RAW_REPORT_LIMIT, "passed", 0),
            ("over_limit", RAW_REPORT_LIMIT + 1, "blocked", 2)):
        ctx = build_delivery_domain(done=1, anchors=1)
        root = ctx["root"]
        finalize_domain(ctx, runs=1, target_bytes=target, recovered=False, complete=False,
                        expect_status=(expected_status,), expect_code=expected_code)
        recorded = yaml.safe_load(
            (ctx["domain_dir"] / "STATE.yaml").read_text(encoding="utf-8")
        )["delivery"]["finalization"]["runs"]
        run = recorded[-1]
        raw = root / run["raw_file"] if run.get("raw_file") else None
        measured = raw.stat().st_size if raw else None
        if measured != target:
            raise BenchError(
                f"{label}: generated raw report is {measured} B, expected exactly {target} B"
            )
        if expected_status == "passed" and measured > RAW_REPORT_LIMIT:
            raise BenchError(f"{label}: accepted raw report exceeds the {RAW_REPORT_LIMIT} B ceiling")
        if expected_status == "blocked" and run.get("raw_sha256"):
            raise BenchError(f"{label}: over-limit raw report was hashed and recorded")
        # `delivery newman` returns non-zero for a blocked run; prove the process code too.
        probe = _probe_newman(ctx, target)
        if probe.returncode != expected_code:
            raise BenchError(
                f"{label}: `delivery newman` exited {probe.returncode}, expected {expected_code}\n"
                f"stderr: {probe.stderr[-800:]}"
            )
        rows.append(Row(
            label=f"newman raw {label}",
            measurement="single",
            reps=1,
            exit_codes=[probe.returncode],
            stdout_bytes=None,
            extra={
                "target_bytes": target,
                "measured_raw_bytes": measured,
                "ceiling_bytes": RAW_REPORT_LIMIT,
                "accepted": run["status"] == "passed",
                "recorded_status": run["status"],
                "reason_codes": run["reason_codes"],
                "raw_sha256_recorded": bool(run.get("raw_sha256")),
                "expected_exit_code": expected_code,
            },
        ))
    return rows


def _probe_newman(ctx: dict[str, Any], target: int) -> subprocess.CompletedProcess:
    """Run `delivery newman` as a real process at this size and return its result."""
    root = ctx["root"]
    head = git(root, "rev-parse", "HEAD")
    runner = fake_newman(root, target_bytes=target)
    port = free_port()
    return subprocess.run(
        [sys.executable, str(CLI), "delivery", "newman", "billing",
         "--branch", "feature/billing", "--newman-bin", str(runner),
         "--base-url", f"http://127.0.0.1:{port}", "--server-sha", head,
         "--safety-note", "Disposable local server, synthetic fixtures, no live integrations.",
         "--server-command", json.dumps(owned_server_command(root, port)),
         "--readiness-url", f"http://127.0.0.1:{port}/health", "--readiness-timeout", "10"],
        cwd=root, text=True, capture_output=True,
    )


def complete_finalize_domain(ctx: dict[str, Any]) -> dict[str, Any]:
    """Record ELI5 evidence and the receipt so the domain reaches the next lifecycle stage."""
    root, cli, d = ctx["root"], ctx["cli"], ctx["domain_dir"]
    skill = root / ".agents/skills/eli5/SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\nname: eli5\ndescription: Explain repository work as HTML.\n---\n"
                     "Read full work context.\n", encoding="utf-8")
    context = json.loads(require("delivery context", cli("delivery", "context", "billing")).stdout)
    html = root / context["html_file"]
    html.parent.mkdir(parents=True, exist_ok=True)
    meta = context["html_metadata"]
    html.write_text(
        "<!doctype html><html><head><title>Implementation explanation</title></head><body>"
        "<!-- devflow-explanation: " + json.dumps(meta) + " -->"
        "<h1>Whole work explanation</h1><p>" + " ".join(meta["work_ids"]) + "</p>"
        "<p>Purpose, flow, implementation changes, decisions, verification results and known "
        "limits are explained with source references.</p></body></html>", encoding="utf-8")
    require("delivery explain", cli("delivery", "explain", "billing", "--skill-file",
                                    str(skill), "--invocation",
                                    "$eli5 with complete PLAN, WORK, branch snapshots"))
    require("delivery finalize", cli("delivery", "finalize", "billing"))
    require("validate (stage control)", cli("validate", "billing"))
    return ctx


def section_scout(reps: int) -> list[Row]:
    """F05/N02. Scout on vs off for the *same* action and the *same* routing model.

    Only `orchestration.scout_before` changes between the two runs, via the fixture's own
    `.devflow/routing.yaml` override, so the primary route, model, effort and permissions are
    identical and the only difference is whether a Scout child is routed.

    Native spawn cost, Scout capsule execution and tokens stay unmeasured: they need a real
    host `spawn_agent`.
    """
    ctx = build_delivery_domain(done=1, anchors=1)
    root = ctx["root"]
    finalize_domain(ctx, runs=1, target_bytes=1024 * 1024, recovered=False)
    rows = []
    for label, scout_before in (("scout_on", None), ("scout_off", [])):
        override = root / ".devflow/routing.yaml"
        if scout_before is None:
            override.unlink(missing_ok=True)
        else:
            t.dump(override, {"version": 1, "orchestration": {"scout_before": scout_before}})
        sid = json.loads(
            require(f"{label}: session-start",
                    _run(root, HOST, ["session-start", "billing"])).stdout
        )["session_id"]
        row = time_command(root, ["dispatch", "billing", "--session-id", sid], reps=reps,
                           script=HOST, json_keys=("status", "fingerprint"),
                           json_values={"status": "dispatch_required"})
        envelope = json.loads(_last_stdout(root, HOST, ["dispatch", "billing",
                                                        "--session-id", sid]))
        require(f"{label}: session-end",
                _run(root, HOST, ["session-end", "billing", "--session-id", sid]))
        primary = envelope.get("primary") or {}
        scout = envelope.get("scout")
        action = envelope.get("action") or {}
        route = primary.get("route") or {}
        row.label = f"dispatch billing ({label})"
        row.extra.update({
            "command": action.get("command"),
            "scope": action.get("scope"),
            "phase": action.get("phase"),
            "action_role": action.get("role"),
            "routing_role": route.get("role"),
            "scout_before_override": scout_before,
            "scout_routed": scout is not None,
            "primary_model_alias": primary.get("model_alias"),
            "primary_model": primary.get("model"),
            "primary_reasoning_effort": primary.get("reasoning_effort"),
            "primary_permissions": primary.get("permissions"),
            "primary_message_bytes": utf8_len(primary.get("message") or ""),
            "primary_scout_message_bytes": utf8_len(primary.get("scout_message") or ""),
            "scout_model_alias": (scout or {}).get("model_alias"),
            "scout_permissions": (scout or {}).get("permissions"),
            "scout_message_bytes": utf8_len((scout or {}).get("message") or ""),
            "envelope_bytes": utf8_len(json.dumps(envelope)),
            "scout_capsule_executed": "unmeasured",
            "native_spawn_ms": "unmeasured",
            "token_usage": "unmeasured",
        })
        rows.append(row)

    on, off = rows
    # Only the Scout decision may differ, so a routing or action drift fails the comparison.
    for key in ("command", "scope", "phase", "action_role", "routing_role",
                "primary_model_alias", "primary_model", "primary_reasoning_effort",
                "primary_permissions", "primary_message_bytes",
                "primary_scout_message_bytes"):
        if on.extra[key] != off.extra[key]:
            raise BenchError(f"Scout comparison is not controlled: {key} differs, "
                             f"{on.extra[key]!r} vs {off.extra[key]!r}")
    if on.extra["scout_routed"] is not True or off.extra["scout_routed"] is not False:
        raise BenchError("Scout comparison did not observe both routing states")
    if on.extra["scout_model_alias"] == on.extra["primary_model_alias"]:
        raise BenchError("Scout reused the primary model, which never spawns")
    return rows


def _hash_cost(paths: list[Path]) -> float:
    start = time.perf_counter()
    for path in paths:
        hashlib.sha256(path.read_bytes()).hexdigest()
    return (time.perf_counter() - start) * 1000


def _cold_cache_status() -> str:
    """Report cold-cache feasibility instead of silently presenting warm numbers as both."""
    try:
        return "available" if os.access("/proc/sys/vm/drop_caches", os.W_OK) else "unavailable"
    except OSError:
        return "unavailable"


def section_projection(reps: int) -> list[Row]:
    """F02. Lifecycle projection cost by WORK count, with YAML read counts."""
    rows = []
    for total in WORK_SIZES:
        root = phase_domain(total)
        runtime = t.load_runtime_module()
        rows.append(_projection_row(root, runtime, ("status", "billing"), total, reps))
        rows.append(_projection_row(root, runtime,
                                    ("render", "run", "billing", "--task", "P01-I01"),
                                    total, reps))
    return rows


def _projection_row(root: Path, runtime: Any, args: tuple[str, ...], total: int,
                   reps: int) -> Row:
    """Time the real text path and verify the same action through the JSON schema."""
    counts = count_yaml_loads(root, runtime, args)
    wall = time_command(root, list(args), reps=reps)
    time_command(root, ["status", "billing", "--json"], reps=1,
                 json_values={"next_action.command": "run",
                              "next_action.work_item": "P01-I01"})
    extra = {
        "work": total,
        "yaml_loads": counts.extra["yaml_loads"],
        "work_index_builds": counts.extra["work_index_builds"],
        "work_index_requests": counts.extra["work_index_requests"],
        "work_yaml_loads": counts.extra["work_yaml_loads"],
        "distinct_yaml_files": counts.extra["distinct_yaml_files"],
        "parsed_yaml_bytes": counts.extra["parsed_yaml_bytes"],
    }
    if args[0] == "status" and "--json" not in args:
        probe = _run(root, CLI, [*args, "--json"])
        check_run(f"{' '.join(args)} --json", probe)
        payload = json.loads(probe.stdout)
        if "next_action" not in payload:
            raise BenchError("status --json: missing next_action")
        extra["next_command"] = payload["next_action"].get("command")
    wall.extra.update(extra)
    return wall


def section_paths(reps: int) -> list[Row]:
    """Per-command wall clock for every hosted execution path, each gated on exit code."""
    rows = []
    ctx = build_delivery_domain(done=1, anchors=1)
    root = ctx["root"]
    finalize_domain(ctx, runs=1, target_bytes=1024 * 1024, recovered=False)
    sid = json.loads(
        require("session-start", _run(root, HOST, ["session-start", "billing"])).stdout
    )["session_id"]

    rows.append(time_command(root, ["status", "billing", "--json"], reps=reps,
                             json_keys=("next_action",),
                             json_values={"next_action.command": "audit",
                                          "next_action.scope": "integration"}))
    rows.append(time_command(root, ["validate", "billing"], reps=reps))
    rows.append(time_command(root, ["delivery", "check", "billing", "--final"], reps=reps))
    rows.append(time_command(root, ["delivery", "finalize", "billing"], reps=reps))

    dispatch = time_command(root, ["dispatch", "billing", "--session-id", sid], reps=reps,
                            script=HOST, json_keys=("status", "fingerprint"),
                           json_values={"status": "dispatch_required"})
    dispatch.label = "dispatch billing --session-id <sid>"
    rows.append(dispatch)
    envelope = json.loads(_last_stdout(root, HOST, ["dispatch", "billing",
                                                     "--session-id", sid]))
    action = envelope["action"]
    require("session-end", _run(root, HOST,
                                ["session-end", "billing", "--session-id", sid]))
    samples: dict[str, list[float]] = {}
    sizes: dict[str, list[int]] = {}

    def measured(label, script, args, **expectations):
        elapsed, proc = spawn(script, root, args)
        check_run(label, proc)
        payload = check_json(label, proc, **expectations) if expectations else None
        samples.setdefault(label, []).append(elapsed)
        sizes.setdefault(label, []).append(utf8_len(proc.stdout))
        return payload

    for _ in range(reps):
        # Each sample starts with an idle guard, without erasing an active reservation.
        fresh = json.loads(require("session-start", _run(
            root, HOST, ["session-start", "billing"])).stdout)["session_id"]
        started = time.perf_counter()
        measured("step dispatch", HOST, ["dispatch", "billing", "--session-id", fresh],
                 json_values={"status": "dispatch_required", "action": action})
        current = measured("guard-status", HOST,
            ["guard-status", "billing", "--session-id", fresh],
            json_values={"status": "ready"})
        attempt = current["attempt"]
        step = measured("step-start", HOST, [
            "step-start", "billing", "--session-id", fresh, "--kind", "primary",
            "--fingerprint", envelope["fingerprint"],
            "--candidate-alias", envelope["primary"]["model_alias"],
            "--attempt", str(attempt)], json_keys=("step_id",),
            json_values={"status": "started", "attempt": attempt})
        step_id = step["step_id"]
        telemetry = measured("telemetry-start", HOST, [
            "telemetry-start", "billing", "--kind", "primary", "--attempt", str(attempt),
            "--session-id", fresh, "--step-id", step_id],
            json_keys=("dispatch_id",), json_values={"status": "started"})
        dispatch_id = telemetry["dispatch_id"]
        measured("child status", CLI, ["status", "billing", "--json"],
                 json_values={"next_action": action})
        child_render = _render_row(root, action, 1)
        samples.setdefault("child render", []).extend(child_render.elapsed_ms_samples)
        sizes.setdefault("child render", []).extend(child_render.stdout_bytes_samples)
        measured("telemetry-finish", HOST, [
            "telemetry-finish", "billing", "--dispatch-id", dispatch_id,
            "--session-id", fresh, "--step-id", step_id, "--outcome", "completed"],
            json_values={"status": "recorded", "dispatch_id": dispatch_id})
        measured("step-finish", HOST, [
            "step-finish", "billing", "--session-id", fresh, "--step-id", step_id,
            "--outcome", "completed"],
            json_values={"status": "recorded", "progressed": False, "attempt": attempt + 1})
        samples.setdefault("hosted CLI step total", []).append(
            (time.perf_counter() - started) * 1000)
        require("session-end", _run(root, HOST,
                                    ["session-end", "billing", "--session-id", fresh]))
        _reset_runtime(root)
    for label, values in samples.items():
        rows.append(Row(label=label, p50_ms=round(statistics.median(values), 2),
                        p95_ms=round(percentile(values, 0.95), 2),
                        exit_codes=[0] * reps, reps=reps, elapsed_ms_samples=values,
                        stdout_bytes_samples=sizes.get(label, []),
                        extra={"native_child_execution": "unmeasured"}))
    return rows


def _run(root: Path, script: Path, args: list[str]) -> subprocess.CompletedProcess:
    _ms, proc = spawn(script, root, args)
    return proc


def _last_stdout(root: Path, script: Path, args: list[str]) -> str:
    proc = _run(root, script, args)
    check_run(" ".join(args), proc)
    return proc.stdout


def _reset_runtime(root: Path) -> None:
    shutil.rmtree(root / ".devflow/runtime", ignore_errors=True)


def section_packets(reps: int) -> list[Row]:
    """F06. Role input bytes actually rendered by the current next action.

    Two packet families are reported and never mixed: grandfathered WORK (no provenance) and
    delivered WORK (real commit, comment anchor, PR and Postman evidence).
    """
    rows = []
    ctx = build_delivery_domain(done=1, anchors=1)
    root = ctx["root"]
    rows.append(_render_row(root, _next_action(root), reps))
    finalize_domain(ctx, runs=1, target_bytes=1024 * 1024, recovered=False)
    rows.append(_render_row(root, _next_action(root), reps))
    execution = sized_delivery_domain(1, done=False)
    rows.append(_render_row(execution, _next_action(execution), reps))

    for total in FINALIZE_WORK_SIZES:
        big = sized_delivery_domain(total)
        state = delivery_work_state(big)
        if state["grandfathered_work_ids"] != state["done_work"]:
            raise BenchError(f"terminal WORK were not grandfathered at {total}: {state}")
        row = _render_row(big, _next_action(big), reps)
        row.extra.update({"work": total, "work_provenance": "grandfathered", **state})
        rows.append(row)

    delivered = build_delivery_domain(done=DELIVERED_WORK_SIZE, anchors=1)
    finalize_domain(delivered, runs=0, target_bytes=0, recovered=False, complete=False)
    delivered_root = delivered["root"]
    state = delivery_work_state(delivered_root)
    if (state["grandfathered_work_ids"]
            or state["done_work_with_delivery_provenance"] != DELIVERED_WORK_SIZE):
        raise BenchError(f"delivered fixture is not provenance-bearing: {state}")
    row = _render_row(delivered_root, _next_action(delivered_root), reps)
    row.extra.update({"work": DELIVERED_WORK_SIZE,
                      "work_provenance": "delivered: real commit, anchors, PR and Postman",
                      **state})
    rows.append(row)
    return rows


def _next_action(root: Path) -> dict[str, Any]:
    proc = _run(root, CLI, ["status", "billing", "--json"])
    check_run("next action", proc)
    status = check_json("next action", proc, json_keys=("next_action",))
    if not isinstance(status["next_action"], dict) or not status["next_action"].get("command"):
        raise BenchError("next action missing command")
    return status["next_action"]


def _render_row(root: Path, action: dict[str, Any], reps: int) -> Row:
    """Render exactly what the lifecycle asked for, so the byte count is a real packet."""
    command = action.get("command")
    args = ["render", command, "billing"]
    if command == "run":
        if action.get("work_item"):
            args += ["--task", action["work_item"]]
    elif command == "audit":
        args += ["--scope", action["scope"], "--mode", action.get("mode", "initial")]
        if action.get("phase"):
            args += ["--phase", action["phase"]]
        if action.get("work_item"):
            args += ["--task", action["work_item"]]
    elif command not in {"finalize", "plan"}:
        return Row(label=f"render {command}", reps=0, measurement="single",
                   extra={"note": "not applicable at this lifecycle state"})
    row = time_command(root, args, reps=reps)
    row.extra["rendered_for_action"] = f"{command}/{action.get('scope')}"
    return row


# ---------------------------------------------------------------- reporting

def table(title: str, rows: list[Row], columns: list[str]) -> None:
    print(f"\n### {title}")
    if not rows:
        print("    no rows")
        return
    print("    " + " ".join(f"{c:>14}" for c in columns))
    for row in rows:
        cells = []
        for column in columns:
            value: Any = row.extra.get(column, getattr(row, column, None))
            if isinstance(value, float):
                cells.append(f"{value:>14.1f}")
            elif isinstance(value, (list, dict)):
                cells.append(f"{str(value):>14}")
            elif value is None:
                cells.append(f"{'-':>14}")
            else:
                cells.append(f"{str(value):>14}")
        print("    " + " ".join(cells))


def environment() -> dict[str, Any]:
    """Plugin and protocol versions are different domains and are recorded separately."""
    return {
        "python": sys.version.split()[0],
        "git": subprocess.run(["git", "--version"], capture_output=True,
                              text=True).stdout.strip(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "cpu_description": platform.processor() or "unmeasured",
        "memory_bytes": (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                         if hasattr(os, "sysconf") else "unmeasured"),
        "working_tree_dirty": bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=PLUGIN,
            capture_output=True, text=True).stdout.strip()),
        "cache_policy": "warm page cache after fixture validation; no OS cache eviction",
        "measurement_entrypoint_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime_source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((PLUGIN / "scripts").glob("*.py"))
        },
        "checkout_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=PLUGIN,
                                        capture_output=True, text=True).stdout.strip() or "unmeasured",
        "devflow_plugin_version": json.loads(
            (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        ).get("version"),
        "devflow_protocol_version": t.RUNTIME_PROTOCOL,
        "devflow_runtime_protocol_version": runtime_module().PROTOCOL_VERSION,
    }


SECTIONS = ("integrity", "git", "newman", "ceiling", "scout", "projection", "paths", "packets")


def main() -> int:
    global sandbox_root
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-check", action="store_true",
                        help="run only the fixture validity gate")
    parser.add_argument("--section", action="append", default=[], choices=list(SECTIONS))
    parser.add_argument("--include-expensive", action="store_true",
                        help="include large raw-report and delivered-WORK sweeps")
    parser.add_argument("--reps", type=int, default=7,
                        help="samples for every timed row; single-shot counters ignore it")
    parser.add_argument("--json", type=Path, help="write the raw result document here")
    args = parser.parse_args()
    if args.reps < 1:
        parser.error("--reps must be at least 1")

    selected = args.section or (["integrity"] if args.self_check else
                               list(SECTIONS) if args.include_expensive else
                               ["integrity", "scout", "projection", "paths"])
    results: dict[str, Any] = {}
    status = "ok"
    error = None
    started = time.perf_counter()
    print(f"DevFlow lifecycle benchmark ({', '.join(selected)})")
    print(json.dumps(environment(), ensure_ascii=False))
    print(f"timed rows: --reps {args.reps}; rows marked measurement=single are one-shot")

    with tempfile.TemporaryDirectory(prefix="devflow-bench-root-") as outer:
        sandbox_root = Path(outer)
        for name in selected:
            try:
                if name == "integrity":
                    rows, checks = section_integrity(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows], "checks": checks}
                    table("integrity: valid fixture, git calls inside one `validate`",
                          rows, ["done_work", "anchors", "git_total", "git_calls_per_work"])
                    print("    checks:", ", ".join(
                        f"{c['check']}={'ok' if c['passed'] else 'FAIL'}"
                        for c in checks))
                elif name == "git":
                    rows = section_git(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("F03 git subprocess count (valid committed sources)",
                          rows, ["done_work", "anchors", "label", "git_total", "git_calls",
                                 "git_calls_per_work"])
                elif name == "newman":
                    rows = section_newman(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("F04 accumulated Newman evidence (stage held at finalize)",
                          rows, ["series", "history", "requested_runs", "recorded_runs",
                                 "raw_target_bytes_each", "raw_bytes_total", "label",
                                 "p50_ms", "raw_sha256_ms_warm", "next_command",
                                 "eli5_recorded"])
                elif name == "ceiling":
                    rows = section_ceiling(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("F04 raw report size ceiling",
                          rows, ["label", "target_bytes", "measured_raw_bytes",
                                 "recorded_status", "accepted", "raw_sha256_recorded",
                                 "exit_codes"])
                elif name == "scout":
                    rows = section_scout(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("F05 Scout on vs off, same action and routing",
                          rows, ["label", "scope", "routing_role", "scout_routed",
                                 "scout_before_override", "primary_model_alias",
                                 "scout_model_alias", "primary_message_bytes",
                                 "primary_scout_message_bytes", "scout_message_bytes",
                                 "envelope_bytes", "p50_ms"])
                elif name == "projection":
                    rows = section_projection(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("F02 lifecycle projection by WORK count",
                          rows, ["work", "label", "p50_ms", "yaml_loads",
                                 "work_index_requests", "work_index_builds", "work_yaml_loads", "distinct_yaml_files",
                                 "next_command"])
                elif name == "paths":
                    rows = section_paths(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("hosted execution path wall clock",
                          rows, ["label", "p50_ms", "p95_ms", "exit_codes", "stdout_bytes"])
                elif name == "packets":
                    rows = section_packets(args.reps)
                    results[name] = {"rows": [r.as_dict() for r in rows]}
                    table("F06 rendered role input bytes",
                          rows, ["work", "work_provenance", "grandfathered_work_ids",
                                 "done_work_with_delivery_provenance", "label", "p50_ms",
                                 "stdout_bytes", "rendered_for_action", "note"])
            except BenchError as exc:
                status, error = "failed", str(exc)
                print(f"\nBENCHMARK FAILED in section {name}:\n{exc}")
                break
            except Exception as exc:  # an unexpected defect must never read as a pass
                status, error = "failed", f"unexpected {type(exc).__name__}: {exc}"
                print(f"\nBENCHMARK CRASHED in section {name}:\n"
                      f"{traceback.format_exc()}")
                break

    document = {
        "schema": "devflow-goal-lifecycle-bench/4",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status,
        "error": error,
        "completed_sections": sorted(results),
        "requested_sections": selected,
        "elapsed_seconds": round(time.perf_counter() - started, 1),
        "reps": args.reps,
        "environment": environment(),
        "sections": results,
        "unmeasured": UNMEASURED,
    }
    print("\nstatus:", status, "| elapsed", document["elapsed_seconds"], "s")
    print("unmeasured:", ", ".join(item["item"] for item in UNMEASURED))
    if args.json:
        try:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
            print("raw results:", args.json)
        except OSError as exc:
            print(f"could not write {args.json}: {exc}", file=sys.stderr)
            status = "failed"
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
