#!/usr/bin/env python3
"""Run unchanged legacy scenarios in isolated repositories with bounded parallelism.

CLI subprocesses omit site initialization, which can load host telemetry/user customization.
PyYAML's explicit package directory is inherited so the runtime's declared dependency is intact.
"""
from __future__ import annotations
import concurrent.futures
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time
import yaml

TEST = Path(__file__).with_name('test_devflow.py')

def load():
    spec = importlib.util.spec_from_file_location('framework_case', TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.sh
    def isolated_sh(cmd, *args, **kwargs):
        if len(cmd) >= 2 and cmd[0] == sys.executable and cmd[1] == str(module.CLI):
            cmd = [cmd[0], '-S', *cmd[1:]]
        return original(cmd, *args, **kwargs)
    module.sh = isolated_sh
    return module

def run_case(name):
    module = load(); output = io.StringIO(); start = time.monotonic(); root = None
    with contextlib.redirect_stdout(output):
        try:
            root = module.new_repo(); getattr(module, name)(root)
        except Exception as exc:
            module.FAILED.append(name); print(f'EXCEPTION {exc!r}')
        finally:
            if root is not None: shutil.rmtree(root, ignore_errors=True)
    return dict(name=name, passed=len(module.PASSED), failures=module.FAILED,
                seconds=round(time.monotonic()-start,2), output=output.getvalue())

if __name__ == '__main__':
    target = Path(sys.argv[1]); workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    os.environ['PYTHONPATH'] = str(Path(yaml.__file__).resolve().parent.parent) + os.pathsep + os.environ.get('PYTHONPATH', '')
    start=time.monotonic(); results=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        pending=[pool.submit(run_case, c.__name__) for c in load().CASES]
        for future in concurrent.futures.as_completed(pending):
            row=future.result(); results.append(row)
            print(row['name'], 'FAIL' if row['failures'] else 'PASS', row['passed'], row['seconds'], flush=True)
            if row['failures']: print(row['output'], flush=True)
            target.write_text(json.dumps({'partial':len(results)!=len(pending), 'cases':results}, indent=2))
    report=dict(scenarios=len(results),passed=sum(r['passed'] for r in results),
                failed=sum(len(r['failures']) for r in results),seconds=round(time.monotonic()-start,2),cases=results)
    target.write_text(json.dumps(report,indent=2)); print({k:v for k,v in report.items() if k!='cases'},flush=True)
    raise SystemExit(bool(report['failed']))
