# Task 6 완료 보고서

## 1. 시작 상태

- 작업일: 2026-09-04
- 저장소: `/home/hyun2y00/workspaces/devflow-marketplace`
- 시작 branch: `main`
- 시작 HEAD: `bc385234e7b38566531c1736916bd2f34f4fed51`
- 시작 tracked working tree: clean
- 별도 branch, worktree, subagent는 만들지 않았다.
- `AGENTS.md`, 전체 작업지시서의 Task 6과 section 9, Task 6 brief, 관련 runtime, WORK schema와 template, protocol, prompt, skill, tests를 읽었다.

## 2. Assumptions

- 현재 작업지시서와 Task 6 brief를 이번 task의 계약으로 사용했다.
- WORK 문서에 `version`이 없으면 기존 artifact 호환성을 위해 version 1로 읽는다.
- WORK version 1과 version 2만 지원하며 새 template과 새 WORK 작성 지시는 version 2를 사용한다.
- runtime은 acceptance와 verification의 구조적 coverage만 검증한다.
- API와 E2E acceptance에 대한 command의 기술적 충분성은 runtime이 문자열로 추론하지 않는다. 실제 관찰 가능한 layer를 사용하라는 책임은 protocol, prompt, skill에 둔다.
- 실행 결과는 기존 문자열 목록인 `evidence.commands`에 계속 기록한다.
- Task 7의 cross-artifact validation과 severity calibration은 구현하지 않는다.
- plugin `0.4.0`과 protocol `1.2.0`은 이번 task에서 변경하지 않는다.
- Task 6 brief의 9개 허용 파일 외에는 부모 지시가 별도로 요구한 이 보고서만 추가한다.

모호하거나 선행 task 계약과 충돌하는 사항은 없었다.

## 3. RED

Production 변경 전에 아래 named case를 추가했다.

- `case_work_v2_requires_unique_acceptance_ids`
- `case_work_v2_requires_unique_verification_ids`
- `case_verification_coverage_requires_every_acceptance_id`
- `case_verification_coverage_rejects_unknown_acceptance_id`
- `case_work_v2_rejects_mixed_legacy_shapes`
- `case_work_v1_remains_readable`

RED 결과는 `passed=1 failed=10`, exit 1이었다. v2 관련 10개 assertion은 기존 runtime이 mapping 구조, unique ID, nonblank field, coverage를 검증하지 않아 실패했다. v1 lifecycle assertion은 통과해 기존 호환성 기준선을 확인했다.

## 4. 구현

- `work.schema.yaml`에 현재 WORK version 2, 지원 version 1과 2, v2 acceptance와 verification command 구조, coverage 규칙을 기록했다.
- `work_document_version`, `normalized_acceptance`, `normalized_verification_commands`로 v1과 v2 읽기 경로를 분리했다.
- v2 acceptance의 unique nonblank ID와 nonblank criterion을 검증한다.
- v2 verification command의 unique nonblank ID, nonblank command, nonempty `covers`를 검증한다.
- `covers`가 현재 item의 acceptance ID만 참조하고 모든 acceptance ID가 최소 한 command에서 covered인지 검증한다.
- v2에서 legacy string acceptance와 verification command를 거절한다.
- 신규 WORK template을 version 2 mapping 구조로 변경했다.
- protocol과 plan/run prompt 및 skill에 version 2 작성, coverage mapping, observable layer 검증, 기존 `evidence.commands` 기록 규칙을 동기화했다.
- 새 dependency와 새 lifecycle artifact는 추가하지 않았다.

## 5. GREEN

- Task 6 named cases: `passed=13 failed=0`, exit 0
- Task 5 traceability cases: `passed=20 failed=0`, exit 0
- Task 4 lifecycle cases: `passed=23 failed=0`, exit 0
- Python syntax: exit 0

Task 6의 13개 assertion은 template v2 구조, 정상 v2, acceptance ID와 criterion, verification ID와 command, command별 nonempty coverage, 전체 acceptance coverage, unknown ID, mixed legacy shape, v1 lifecycle 보존을 검증한다.

## 6. Compatibility

- v1 string acceptance와 verification command는 normalization 후 기존 validator와 lifecycle에서 계속 읽힌다.
- v1 `work start`와 `work done` 후에도 WORK version과 두 string list shape가 유지된다.
- v1 artifact를 v2로 자동 rewrite하지 않는다.
- Task 4 audit apply 및 remediation closure lifecycle은 `passed=23 failed=0`으로 유지됐다.
- Task 5 finding 및 WORK 양방향 traceability는 `passed=20 failed=0`으로 유지됐다.
- 실행 evidence는 기존 `evidence.commands` shape를 유지한다.

## 7. Exact commands와 exit

시작 점검:

```bash
git branch --show-current
git status --short
git rev-parse HEAD
```

결과: `main`, clean, `bc385234e7b38566531c1736916bd2f34f4fed51`, 모두 exit 0.

Task 6 RED 및 GREEN:

```bash
python3 -c 'import importlib.util, pathlib, shutil, sys; p=pathlib.Path("plugins/devflow/tests/test_devflow.py").resolve(); s=importlib.util.spec_from_file_location("task6_green", p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); names=["case_work_v2_requires_unique_acceptance_ids","case_work_v2_requires_unique_verification_ids","case_verification_coverage_requires_every_acceptance_id","case_verification_coverage_rejects_unknown_acceptance_id","case_work_v2_rejects_mixed_legacy_shapes","case_work_v1_remains_readable"]; [(lambda r,n: (print("\n"+n), getattr(m,n)(r), shutil.rmtree(r, ignore_errors=True)))(m.new_repo(), n) for n in names]; print(f"\npassed={len(m.PASSED)} failed={len(m.FAILED)}"); [print("FAILED: "+x) for x in m.FAILED]; sys.exit(1 if m.FAILED else 0)'
```

Production 변경 전 결과: `passed=1 failed=10`, exit 1.

최종 결과: `passed=13 failed=0`, exit 0.

Task 5 traceability:

```bash
python3 -c 'import importlib.util, pathlib, shutil, sys; p=pathlib.Path("plugins/devflow/tests/test_devflow.py").resolve(); s=importlib.util.spec_from_file_location("task5_all_tests", p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); names=["case_multi_finding_work_requires_aggregation_reason","case_multi_finding_work_accepts_coherent_explicit_aggregation","case_audit_work_links_are_bidirectional","case_decision_finding_cannot_generate_ready_work","case_decision_finding_requires_decision_id","case_evidence_finding_requires_evidence_work","case_documentation_drift_requires_documentation_work","case_work_cannot_reference_unknown_audit_finding","case_unlinked_work_cannot_reference_unknown_audit_finding","case_decision_apply_requires_actual_nonblank_options","case_decisions_state_and_work_dependencies_are_bidirectional","case_finding_schema_trust_anchor_requires_work_kind","case_work_audit_rejects_unlinked_unknown_findings_in_same_manifest","case_decision_record_stops_at_next_markdown_heading","case_decision_placeholder_options_are_invalid","case_malformed_canonical_audit_cannot_authenticate_finding","case_decision_commonmark_indented_heading_boundary"]; [(lambda r,n: (print("\n"+n), getattr(m,n)(r), shutil.rmtree(r, ignore_errors=True)))(m.new_repo(), n) for n in names]; print(f"\npassed={len(m.PASSED)} failed={len(m.FAILED)}"); [print("FAILED: "+x) for x in m.FAILED]; sys.exit(1 if m.FAILED else 0)'
```

결과: `passed=20 failed=0`, exit 0.

Task 4 lifecycle:

```bash
python3 -c 'import importlib.util, pathlib, shutil, sys; p=pathlib.Path("plugins/devflow/tests/test_devflow.py").resolve(); s=importlib.util.spec_from_file_location("task4_lifecycle_tests", p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); names=["case_audit_closure_covers_every_prior_finding","case_audit_closure_reopens_finding","case_audit_remediation_lifecycle_reaches_closure_and_complete","case_audit_closure_uses_git_history_for_prior_findings","case_plan_audit_remediation_reaches_closure","case_lifecycle_walk","case_remediation_returns_to_work_closure_audit"]; [(lambda r,n: (print("\n"+n), getattr(m,n)(r), shutil.rmtree(r, ignore_errors=True)))(m.new_repo(), n) for n in names]; print(f"\npassed={len(m.PASSED)} failed={len(m.FAILED)}"); [print("FAILED: "+x) for x in m.FAILED]; sys.exit(1 if m.FAILED else 0)'
```

결과: `passed=23 failed=0`, exit 0.

Python syntax와 full suite:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
```

결과: py_compile exit 0. Full suite는 `passed=329 failed=2`, exit 1.

최종 hygiene:

```bash
git diff --cached --check
git status --short
git branch --show-current
git diff --cached --name-only
git diff --cached -U0 | rg -n --pcre2 '^\+.*(?:\x{2014}|\x{2013}|\x{00B7}|\x{2026})'
```

결과: `git diff --cached --check` exit 0, branch `main`, staged file 10개가 아래 File list와 일치했다. 금지 문장부호 검색은 출력 없이 exit 1이었다.

## 8. Full suite

`python3 plugins/devflow/tests/test_devflow.py`의 최종 결과는 `passed=329 failed=2`, exit 1이었다. 실패는 작업 시작 baseline과 같은 Task 7 known RED 두 건뿐이다.

- `case_validate_rejects_orphan_phase_manifest`
- `case_validate_rejects_placeholder_delivery_contract_before_execution`

Task 6, Task 5 traceability, Task 4 lifecycle, v1 lifecycle에서 추가 실패는 없다.

## 9. Self-review

- 문서 version을 한 번 읽어 item validator에 전달하며 v1과 v2 normalization helper를 공통으로 재사용한다.
- v2 구조 검증은 WORK item 내부 ID와 coverage에만 한정했다.
- runtime에 command 문자열 분석, 테스트 종류 추론, API 및 E2E heuristic을 추가하지 않았다.
- v1 lifecycle과 string shape를 유지하고 migration write를 추가하지 않았다.
- Task 7 소유의 orphan manifest, placeholder contract, cross-artifact, severity 규칙은 수정하지 않았다.
- 기존 `evidence.commands`, review gate, finding traceability, audit apply 전이는 변경하지 않았다.
- 새 dependency, adapter 복제, background orchestration, 추가 artifact는 없다.
- 변경은 Task 6 brief의 9개 파일과 이 보고서로 제한했다.

## 10. File list

```text
.superpowers/sdd/devflow-audit-remediation-vnext-work-order/task-6-report.md
plugins/devflow/core/prompts/plan.md
plugins/devflow/core/prompts/run.md
plugins/devflow/core/protocol/work-item-contract.md
plugins/devflow/core/schemas/work.schema.yaml
plugins/devflow/core/templates/WORK.yaml
plugins/devflow/scripts/devflow.py
plugins/devflow/skills/plan/SKILL.md
plugins/devflow/skills/run/SKILL.md
plugins/devflow/tests/test_devflow.py
```

커밋 메시지: `feat(devflow): map acceptance criteria to verification`

## Fix round 1

### 독립 리뷰 지적과 원인

- invalid WORK v2 문서는 `validate`에서 거절됐지만 `work start`, `work done`, `work block`은 `validate_item` 경계를 거치지 않고 직접 상태를 썼다.
- WORK schema는 module import 시 상수로 펼쳐져 schema 식별자와 v2 계약 자체가 변조돼도 신뢰 경계를 확인하지 않았다.
- audit render는 `audit-core`만 포함해 감사자가 생성할 WORK v2 ID, `covers`, observable layer 지침을 받지 못했다.

### RED

- mutation과 schema 및 render 회귀 3개 case를 먼저 추가했다.
- 첫 실행은 `passed=5 failed=12`, exit 1이었다.
- 실패 12개는 empty v2 계약, boolean version, float version, unsupported version 각각에 대한 start, done, block mutation이었다. 각 명령이 exit 0으로 문서를 변경해 결함을 재현했다.
- schema trust anchor 4개 assertion과 audit render 1개 assertion은 이전 구현 세션의 미커밋 production 변경 때문에 이미 통과했다. 해당 변경을 검토한 뒤 유지했다.

### 수정

- `configure_work_schema`가 매 CLI 진입 시 bundled WORK schema를 다시 읽고 schema 식별자, 현재 version 2, 지원 version 1과 2, v2 acceptance와 verification contract를 확인한 뒤 runtime 상수를 구성한다.
- `validate_work_file`로 기존 `validate_item` 경로를 재사용했다. `collect_validation`과 세 work mutation이 같은 대상 문서 검증을 거친다.
- mutation 검증은 대상 WORK 파일에만 적용한다. 전체 domain validation을 호출하지 않아 Task 7의 known RED가 mutation을 막지 않는다.
- start는 기존 전이 오류와 문서 오류를 함께 보고해 구체적인 unresolved decision ID를 보존한다. done과 block은 문서 오류를 쓰기 전에 반환한다.
- audit render가 기존 `work-item-contract.md`를 포함하도록 구성했다. 새 prompt나 중복 규칙은 추가하지 않았다.

### GREEN과 검증

- Task 6 기존 6개와 신규 3개 case: `passed=30 failed=0`, exit 0.
- invalid mutation 12개 assertion은 모두 exit 2와 전체 domain file bytes 불변을 확인했다.
- 명시적 WORK v1 lifecycle은 기존 case에서 validate, start, done과 문자열 shape 보존을 확인했다.
- `version`이 없는 legacy WORK는 별도 실행에서 `validate=0 start=0 done=0 shape_preserved=True`를 확인했다.
- Task 5 traceability: `passed=20 failed=0`, exit 0.
- Task 4 lifecycle: `passed=23 failed=0`, exit 0.
- `python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py`: exit 0.
- full suite: `passed=346 failed=2`, exit 1. 실패는 Task 7 소유의 `case_validate_rejects_orphan_phase_manifest`, `case_validate_rejects_placeholder_delivery_contract_before_execution` 두 건뿐이다.

### 변경 파일과 커밋

```text
.superpowers/sdd/devflow-audit-remediation-vnext-work-order/task-6-report.md
plugins/devflow/scripts/devflow.py
plugins/devflow/tests/test_devflow.py
```

커밋 메시지: `fix(devflow): enforce work v2 at mutation boundaries`

남은 우려 사항은 없다. Task 7의 두 known RED는 이 수정 범위에 포함하지 않았다.
