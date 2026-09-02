# Goal 05 — Render Context Assembler

**Recommended model:** GPT-5.6 Terra high

**Prerequisites:** Goals 01–04 are applied and tests pass.

**Goal:** Make `devflow render` provide the minimum repository-development context required for plan/run/audit execution, rather than mostly printing document paths and forcing every fresh agent session to rediscover the same PRD/PLAN sections.

## Scope

Primary files:

```text
plugins/devflow/scripts/devflow.py
plugins/devflow/core/prompts/plan.md
plugins/devflow/core/prompts/run.md
plugins/devflow/core/prompts/audit.md
plugins/devflow/tests/test_devflow.py
```

Read existing:

```text
core/protocol/authority.md
core/protocol/work-item-contract.md
core/protocol/audit-core.md
core/protocol/risk-policy.md
core/protocol/decision-policy.md
```

Do not change the artifact model. PRD/PLAN/STATE/WORK/AUDIT remain the canonical files.

## Design principles

1. `render` assembles context; it does not execute the work.
2. Exact stable IDs drive extraction.
3. Do not fuzzy-match requirement IDs.
4. Avoid dumping every document for every scope.
5. Preserve file paths in runtime context so agents can inspect full artifacts when needed.
6. Read-only render must not mutate STATE/WORK except the existing `refresh_state` computed-field behavior.

## Markdown extraction helper

Add a standard-library-only helper that extracts relevant Markdown context by exact ID.

Target interface:

```python
def extract_markdown_context(path: Path, ids: list[str]) -> list[str]:
    ...
```

Required behavior:

### Heading match

Given:

```markdown
### REQ-021 — Wanted
UNIQUE_REQ_021

#### Details
DETAIL_021

### REQ-999 — Unrelated
UNRELATED_REQ_999
```

For `REQ-021`, include the matched heading section through the next heading of the same or higher level. Nested headings under the matched section are included.

### Non-heading exact match

If an exact ID only appears in a table row or bullet, include that line plus a small deterministic local context window. Use a fixed number of surrounding lines such as 2 before and 2 after.

### Missing ID

Return an explicit marker:

```text
REQ-021: not found verbatim in <filename>
```

Do not substitute a similar ID.

Deduplicate overlapping sections if multiple IDs map to the same Markdown section.

## `render plan`

Architect needs the whole approved product/domain contract.

After runtime paths, print:

```text
## Approved PRD
<full PRD.md>
```

Then print the standard plan protocols and PITFALLS as today.

Do not inline PLAN into plan mode before the architect updates it unless the existing PLAN contains useful prior content; if you keep it, label it clearly as current PLAN rather than approved requirements.

## `render run`

Keep full selected WORK YAML.

Collect origin IDs from:

```yaml
origin:
  requirements: [...]
  plan_items: [...]
  findings: [...]
```

Print:

```text
## Relevant PRD context
<exact sections for origin.requirements>

## Relevant PLAN context
<exact sections/rows for origin.plan_items>
```

If `origin.findings` identify entries in an existing audit Markdown and a deterministic audit file can be resolved, include only the relevant audit context. Do not invent cross-file search heuristics that are not grounded in current artifact structure.

The selected WORK YAML remains the execution contract and must appear before protocol text.

## `render audit --scope work`

Print:

```text
full target WORK YAML
relevant PRD context
relevant PLAN context
implementation evidence
existing work audit file contents when mode=closure and file exists
```

For `mode=initial`, existing audit content may be included only if clearly labeled as previous/stale content; simplest safe behavior is to omit it unless closure mode.

## `render audit --scope phase`

Resolve the phase work manifest and include:

```text
phase-specific WORK YAML
unique requirement IDs referenced by those WORK items -> relevant PRD context
unique plan_items -> relevant PLAN context
phase diff_range metadata
existing phase audit file content only for closure mode when it exists
```

Do not inline unrelated phases.

## `render audit --scope plan`

Plan audit is broad by definition. Include:

```text
full PRD
full PLAN
plan review metadata
```

## `render audit --scope integration`

Integration needs cross-phase visibility without blindly duplicating every file.

Include:

```text
full PLAN
compact phase manifest summary: phase key/status/work_file/audit_file/diff_range
integration WORK YAML if present
integration audit contents for closure mode if present
baseline_sha/target_sha
paths to all phase audit artifacts
```

Do not inline every phase audit and every WORK file by default. The auditor can open those exact paths when evidence requires it.

## Helper structure

Prefer small helpers such as:

```python
def read_text_if_exists(path: Path) -> str:
    ...

def origin_ids(item: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    ...

def extract_markdown_context(path: Path, ids: list[str]) -> list[str]:
    ...

def render_markdown_context(title: str, path: Path, ids: list[str]) -> None:
    ...
```

Keep `render()` as orchestration over helpers instead of growing one monolithic branch.

## Required tests

Create fixture PRD:

```markdown
# PRD

### REQ-021 — Wanted
UNIQUE_REQ_021

### REQ-999 — Unrelated
UNRELATED_REQ_999
```

Create fixture PLAN:

```markdown
# PLAN

### P03-02 — Wanted plan item
UNIQUE_PLAN_P03_02

### P09-99 — Unrelated
UNRELATED_PLAN_P09_99
```

Create WORK whose origin references only `REQ-021` and `P03-02`.

Assert `render run`:

```text
contains UNIQUE_REQ_021
contains UNIQUE_PLAN_P03_02
does not contain UNRELATED_REQ_999
does not contain UNRELATED_PLAN_P09_99
contains full selected WORK id/objective
```

Add a missing-ID test that confirms an explicit `not found verbatim` marker.

Add `render plan` test proving full PRD content is present.

Add phase audit test proving unrelated phase markers are not inlined.

Add integration render test proving PLAN and phase manifest paths are present without requiring every phase WORK body.

## Verification

Run:

```bash
python3 tests/test_devflow.py
python3 -m py_compile scripts/devflow.py
```

## Acceptance criteria

```text
[ ] plan render includes the approved PRD body.
[ ] run render includes only relevant PRD/PLAN sections by exact origin IDs.
[ ] work/phase audit renders scope-relevant context.
[ ] integration audit renders broad summaries/paths without context explosion.
[ ] missing IDs are explicit; fuzzy guesses are absent.
[ ] no new Markdown parser dependency is added.
[ ] full test suite passes.
```

## Explicit exclusions

Do not add embeddings, semantic search, external vector stores, repository-wide RAG, autonomous code exploration, or orchestrator behavior.

## Completion report

Return only:

```markdown
## Result
- New context helpers:
- Plan context behavior:
- Run context behavior:
- Audit context behavior:
- Tests:
```
