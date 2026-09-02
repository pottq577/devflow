# Goal 07 — Test Harness Hardening

**Recommended model:** GPT-5.6 Terra medium

**Prerequisites:** Goals 01–06 are applied and the current test suite passes.

**Goal:** Make the framework-free integration test runner fail fast with useful diagnostics when a subprocess hangs, while preserving all real CLI integration behavior.

## Scope

Primary file:

```text
plugins/devflow/tests/test_devflow.py
```

Only modify runtime code if a test exposes a real runtime hang/bug. Keep runtime changes narrowly scoped and report them.

## Current problem

The test helper currently calls:

```python
subprocess.run(..., capture_output=True)
```

with no timeout. A stuck CLI/git process can stall the full suite without identifying the case/command.

## Required changes

### 1. Add subprocess timeout

Change helper signature to:

```python
def sh(
    cmd: list[str],
    cwd: Path,
    check: bool = False,
    timeout: int = 20,
) -> subprocess.CompletedProcess:
    ...
```

Use `subprocess.run(..., timeout=timeout)`.

Catch `subprocess.TimeoutExpired` and raise a diagnostic exception that includes:

```text
command
cwd
timeout seconds
captured stdout/stderr when available
```

Keep the default at 20 seconds unless an existing legitimate operation demonstrably needs more. A specific call may pass a larger timeout with an explanatory comment.

### 2. Flush case names

In `main()` print case names with `flush=True` before creating/running the case.

Example:

```python
print(f"\n{case.__name__}", flush=True)
```

PASS/FAIL lines may also flush for immediate CI visibility.

### 3. Preserve cleanup

Throwaway repositories must still be removed in `finally` even after timeout exceptions.

### 4. Improve summary diagnostics

A raised timeout/crash must append a stable failure entry containing the case name. Keep final:

```text
passed=N failed=M
```

summary behavior.

Do not replace this lightweight runner with pytest in this goal.

## Add a self-testable timeout path

Avoid adding a test that actually waits 20 seconds.

Add a small test helper case or internal direct call using a very small explicit timeout, for example:

```python
sh([sys.executable, "-c", "import time; time.sleep(1)"], root, timeout=0.05)
```

Confirm it raises a timeout diagnostic quickly. Structure it so the expected timeout does not count as a suite failure.

If floating-point timeout typing complicates the declared `int`, use `float` for the helper parameter:

```python
timeout: float = 20
```

### 5. Run complete regression suite

The suite now includes state-machine tests from Goals 01–06. Run the whole thing and investigate any test that exceeds the default timeout. Do not increase the global timeout to hide a deterministic hang.

## Verification

Run:

```bash
python3 tests/test_devflow.py
```

Then run it a second time to catch cleanup/state leakage issues:

```bash
python3 tests/test_devflow.py
```

## Acceptance criteria

```text
[ ] every subprocess has a finite timeout by default.
[ ] timeout diagnostics identify case/command/cwd.
[ ] case names appear before long-running work.
[ ] cleanup happens after timeout/crash.
[ ] timeout behavior is covered without a long-running test.
[ ] two consecutive full-suite runs pass.
```

## Explicit exclusions

Do not migrate to pytest, add CI configuration, or benchmark performance in this goal.

## Completion report

Return only:

```markdown
## Result
- Timeout behavior:
- Diagnostic behavior:
- First full run:
- Second full run:
- Runtime bugs discovered, if any:
```
