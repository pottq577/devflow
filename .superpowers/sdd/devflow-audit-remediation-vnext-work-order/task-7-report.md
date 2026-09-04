# Task 7 완료 보고서

## 1. 시작 상태

- 작업일: 2026-09-04
- 저장소: `/home/hyun2y00/workspaces/devflow-marketplace`
- 시작 branch: `main`
- 시작 HEAD: `5aa8ddd880b1f5f357891c493a59f4478ba56213`
- 시작 tracked working tree: clean
- branch, worktree, subagent는 만들지 않았다.
- `AGENTS.md`, 전체 작업지시서와 section 10 및 11, Task 7 brief, runtime 전체, STATE와 finding 및 audit schema, risk policy, lifecycle과 audit protocol, audit prompt와 template, 기존 tests 전체를 읽었다.

## 2. Assumptions

- Task 7에서는 protocol version을 올리지 않고 현재 runtime protocol `1.2.0`을 유지한다. Protocol `1.3.0` 반영은 Task 9의 별도 범위다.
- `.devflow/config.yaml`에 `protocol_version`이 없는 legacy runtime config는 파일을 고치지 않고 현재 runtime version으로 읽는다.
- protocol 1.2의 front matter 없는 audit Markdown은 계속 읽을 수 있다. STATE protocol이 1.3 이상일 때 verified 근거로는 인정하지 않는다.
- 현재 audit schema의 필수 field에 `phase`와 `task`가 없으므로 legacy artifact의 field 누락은 허용한다. Field가 존재하면 canonical 위치와 STATE target에 맞는지 검증하고, `audit apply` 요청의 phase와 task는 computed next action과 계속 정확히 비교한다.
- Initial audit가 적용된 뒤 lifecycle이 closure를 기다리는 동안 canonical 파일의 `mode: initial`은 정상이다. Initial audit가 필요한 상태에서 closure metadata가 놓인 모순과 initial Git history 없는 closure는 거절한다.
- Runtime은 문서 본문의 자연어 의미를 추론하지 않는다. Delivery placeholder는 template marker와 구조적 requirement heading으로, audit remediation scope와 strategy는 template에서 얻은 required heading 및 nonblank body로 검사한다.

모호한 계약 충돌은 없었다.

## 3. RED

시작 baseline의 Python syntax는 exit 0이었다. 전체 suite는 Task 1에서 먼저 고정한 다음 두 known RED만 실패했다.

- `case_validate_rejects_orphan_phase_manifest`
- `case_validate_rejects_placeholder_delivery_contract_before_execution`

Baseline 전체 결과는 `passed=346 failed=2`, exit 1이었다.

Production 변경 전에 Task 7 named case를 추가했다. 기존 orphan case에는 assertion만 보강했고 duplicate case를 만들지 않았다. 기존 placeholder case도 같은 대상 실행에 포함했다.

```text
passed=4 failed=16
```

결과는 exit 1이었다. Orphan phase와 placeholder delivery, phase 문서 불일치, phase 없는 audit remediation 완료, applied audit lifecycle 모순, config compatibility guard, mutation 차단, severity trust anchor가 구현되지 않은 상태를 재현했다.

## 4. 구현

- STATE phase와 `work/phase-XX.yaml`의 normalized phase, `work_file`, filename, 문서 `phase`를 한 validation 경계에서 비교한다. Delivery integration verified에는 실제 phase 한 개 이상과 모든 phase verified를 요구하며 audit remediation integration은 phase 없이 verified와 complete가 가능하다.
- Delivery PRD와 PLAN placeholder marker를 실제 template에서 읽는다. WORK가 생기거나 required plan review verification을 시도하면 scaffold 문서를 거절한다. Audit remediation의 required section 목록도 mode 전용 template heading에서 읽어 empty scope와 strategy의 initial apply를 막는다.
- Canonical plan, work, phase, integration audit를 STATE와 WORK에서 수집해 schema, scope, optional phase와 task, lifecycle mode, closure initial history, verified verdict와 verification evidence를 함께 검증한다. Pending plan review와 이미 적용된 integration lifecycle의 모순도 거절한다.
- Runtime config protocol version을 실제 compatibility guard로 사용한다. Malformed와 different major는 error, newer same-major는 warning과 status 및 validate만 허용, 모든 artifact mutation은 write 전에 차단한다. Status human 및 JSON에는 runtime, config, state, effective version을 표시한다.
- 신규 init config와 STATE에 현재 runtime protocol을 기록한다. Older same-major와 legacy missing config version은 backward-readable하게 유지한다.
- `severity_reason`을 finding schema trust anchor의 protected required field로 추가했다. Schema 의미, risk policy, audit prompt와 template에 trigger conditions, affected users or systems, current defenses, residual impact, severity 선택 이유를 기록하고 finding severity와 WORK risk level을 분리했다.
- 기존 Task 2부터 6의 lifecycle projection, exact action guard, audit parser와 schema validator, canonical path, initial Git history, prospective validation helper를 재사용했다. 새 dependency, sidecar, background controller, autonomous orchestration은 추가하지 않았다.

## 5. GREEN

- Task 7 named 8개와 Task 1 placeholder known RED: `passed=20 failed=0`, exit 0
- Task 4, 5, 6 focused regression: `passed=38 failed=0`, exit 0
- Python syntax: exit 0
- 전체 suite 1회차: `passed=366 failed=0`, exit 0
- 전체 suite 2회차: `passed=366 failed=0`, exit 0

Task 7 named case는 파일당 한 번만 정의되어 있으며 orphan case를 포함한 8개 이름을 확인했다.

## 6. Version compatibility matrix

| Config protocol | status | validate | artifact mutation | 진단 |
| --- | --- | --- | --- | --- |
| 누락된 legacy config field | 허용 | 허용 | 허용 | 현재 runtime version으로 메모리에서 읽음 |
| malformed | 차단 | error | 차단 | `Invalid config protocol_version` |
| different major | 차단 | error | 차단 | `Unsupported config protocol_version` |
| older same-major | 허용 | 허용 | 허용 | backward-compatible read |
| runtime과 동일 | 허용 | 허용 | 허용 | runtime, config, state, effective 표시 |
| newer same-major | warning과 함께 허용 | warning과 함께 허용 | 차단 | compatible runtime 사용 안내 |

STATE protocol 1.2의 legacy audit Markdown은 front matter 없이도 readable하다. STATE protocol 1.3 이상에서 verified lifecycle은 canonical front matter, schema-valid verification evidence, `pass` verdict가 필요하다.

## 7. Exact commands와 exits

시작 점검:

```bash
git branch --show-current
git status --short
git rev-parse HEAD
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
```

결과: branch `main`, tracked clean, HEAD `5aa8ddd880b1f5f357891c493a59f4478ba56213`, Git 점검과 py_compile exit 0, baseline suite `passed=346 failed=2`, exit 1.

Task 7과 Task 1 known RED 대상 실행:

```bash
python3 -c 'exec("""import importlib.util, shutil
from pathlib import Path
spec = importlib.util.spec_from_file_location("test_devflow", "plugins/devflow/tests/test_devflow.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
names = ["case_validate_rejects_orphan_phase_manifest", "case_validate_rejects_phase_document_mismatch", "case_delivery_integration_still_requires_verified_phases", "case_audit_remediation_verifies_without_fake_phases", "case_validate_rejects_applied_audit_lifecycle_mismatch", "case_config_protocol_version_is_checked", "case_newer_config_protocol_blocks_mutation", "case_finding_requires_severity_reason", "case_validate_rejects_placeholder_delivery_contract_before_execution"]
for name in names:
    print("\n" + name, flush=True)
    root = m.new_repo()
    try:
        getattr(m, name)(root)
    except Exception as exc:
        m.FAILED.append(name)
        print(f"  FAIL  {name} raised {exc!r}", flush=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
print(f"\npassed={len(m.PASSED)} failed={len(m.FAILED)}")
raise SystemExit(1 if m.FAILED else 0)
""")'
```

Production 변경 전 결과: `passed=4 failed=16`, exit 1. 최종 결과: `passed=20 failed=0`, exit 0.

Task 4, 5, 6 focused regression은 같은 inline import runner에서 다음 case 목록을 실행했다.

```text
case_audit_apply_rejects_missing_front_matter
case_audit_apply_rejects_malformed_front_matter
case_audit_apply_rejects_duplicate_yaml_keys
case_audit_apply_requires_exact_next_action
case_audit_apply_validates_verdict_against_findings
case_audit_apply_validates_finding_links
case_audit_apply_failure_is_atomic
case_audit_apply_updates_state_and_next_action
case_audit_closure_covers_every_prior_finding
case_audit_closure_reopens_finding
case_multi_finding_work_requires_aggregation_reason
case_multi_finding_work_accepts_coherent_explicit_aggregation
case_audit_work_links_are_bidirectional
case_decision_finding_cannot_generate_ready_work
case_decision_finding_requires_decision_id
case_evidence_finding_requires_evidence_work
case_documentation_drift_requires_documentation_work
case_work_cannot_reference_unknown_audit_finding
case_work_v2_requires_unique_acceptance_ids
case_work_v2_requires_unique_verification_ids
case_verification_coverage_requires_every_acceptance_id
case_verification_coverage_rejects_unknown_acceptance_id
case_work_v2_rejects_mixed_legacy_shapes
case_work_v1_remains_readable
```

실행한 명령은 다음과 같다.

```bash
python3 -c 'exec("""import importlib.util, shutil
spec = importlib.util.spec_from_file_location("test_devflow", "plugins/devflow/tests/test_devflow.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
names = ["case_audit_apply_rejects_missing_front_matter", "case_audit_apply_rejects_malformed_front_matter", "case_audit_apply_rejects_duplicate_yaml_keys", "case_audit_apply_requires_exact_next_action", "case_audit_apply_validates_verdict_against_findings", "case_audit_apply_validates_finding_links", "case_audit_apply_failure_is_atomic", "case_audit_apply_updates_state_and_next_action", "case_audit_closure_covers_every_prior_finding", "case_audit_closure_reopens_finding", "case_multi_finding_work_requires_aggregation_reason", "case_multi_finding_work_accepts_coherent_explicit_aggregation", "case_audit_work_links_are_bidirectional", "case_decision_finding_cannot_generate_ready_work", "case_decision_finding_requires_decision_id", "case_evidence_finding_requires_evidence_work", "case_documentation_drift_requires_documentation_work", "case_work_cannot_reference_unknown_audit_finding", "case_work_v2_requires_unique_acceptance_ids", "case_work_v2_requires_unique_verification_ids", "case_verification_coverage_requires_every_acceptance_id", "case_verification_coverage_rejects_unknown_acceptance_id", "case_work_v2_rejects_mixed_legacy_shapes", "case_work_v1_remains_readable"]
for name in names:
    print("\n" + name, flush=True)
    root = m.new_repo()
    try:
        getattr(m, name)(root)
    except Exception as exc:
        m.FAILED.append(name)
        print(f"  FAIL  {name} raised {exc!r}", flush=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
print(f"\npassed={len(m.PASSED)} failed={len(m.FAILED)}")
raise SystemExit(1 if m.FAILED else 0)
""")'
```

결과: `passed=38 failed=0`, exit 0.

최종 syntax와 full suite:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
```

결과: py_compile exit 0. Full suite 1회차와 2회차 모두 `passed=366 failed=0`, exit 0.

최종 hygiene:

```bash
git diff --cached --check
git branch --show-current
git status --short
git diff --cached --name-only
git diff --cached --unified=0 | rg -n --pcre2 '^\+.*(?:\x{2014}|\x{2013}|\x{00B7}|\x{2026})'
rg -n '^def case_(validate_rejects_orphan_phase_manifest|validate_rejects_phase_document_mismatch|delivery_integration_still_requires_verified_phases|audit_remediation_verifies_without_fake_phases|validate_rejects_applied_audit_lifecycle_mismatch|config_protocol_version_is_checked|newer_config_protocol_blocks_mutation|finding_requires_severity_reason)' plugins/devflow/tests/test_devflow.py
```

결과: 공백 검사, branch, status, file list, named case 검색은 exit 0이었다. 금지 문장부호 검색은 출력 없이 exit 1이었다. Branch는 `main`, named case 8개는 각 한 번만 정의됐고 변경 범위는 아래 File list와 일치한다.

## 8. Full suite twice

Lifecycle과 state machine 변경이므로 같은 최종 code tree에서 전체 suite를 연속 두 번 실행했다.

```text
run 1: passed=366 failed=0, exit 0
run 2: passed=366 failed=0, exit 0
```

추가 실패와 known RED는 남지 않았다.

## 9. Self-review

- Orphan phase manifest와 STATE work_file 및 document phase 불일치를 독립 오류로 보고한다.
- Audit remediation integration WORK를 phase manifest로 오인하지 않는다.
- Delivery의 phase requirement와 audit remediation의 phase-free completion을 workflow type으로 분리했다.
- Canonical audit 파일 존재 자체는 lifecycle을 변경하지 않는다. Mutation은 명시적 apply 또는 legacy set command에서만 수행된다.
- Protocol 1.3 verified state는 canonical audit의 front matter, schema-valid verification, verdict와 initial history 규칙으로 검증한다.
- Future config 상태의 status는 derived 값을 계산하되 파일을 쓰지 않으며 mutation matrix가 전체 artifact bytes 불변을 확인한다.
- Finding contract의 actual allowed value는 계속 schema에서 읽는다. Python trust anchor는 `severity_reason` required 계약이 함께 제거되는 공격만 막는다.
- Placeholder validator는 template marker와 required heading을 읽고 자연어 내용의 적절성을 추론하지 않는다.
- 기존 helper를 재사용했고 새 dependency, sidecar, adapter 복제, autonomous orchestration은 없다.
- 변경은 Task 7 brief의 7개 파일과 이 보고서만 포함한다.

## 10. File list

```text
.superpowers/sdd/devflow-audit-remediation-vnext-work-order/task-7-report.md
plugins/devflow/core/prompts/audit.md
plugins/devflow/core/protocol/risk-policy.md
plugins/devflow/core/schemas/finding.schema.yaml
plugins/devflow/core/schemas/state.schema.yaml
plugins/devflow/core/templates/AUDIT.md
plugins/devflow/scripts/devflow.py
plugins/devflow/tests/test_devflow.py
```

커밋 메시지: `fix(devflow): validate lifecycle artifacts as one contract`

## Fix round 1

### 시작 상태

- 작업일: 2026-09-04
- branch: `main`
- 시작 HEAD: `bc41e1d9306eafc308520da1e4f6ec911f9527c2`
- 시작 tracked working tree: clean
- branch, worktree, subagent를 만들지 않았다.

### 리뷰 검증과 assumptions

독립 리뷰의 Important 5건을 현재 runtime 경로에서 확인했다.

- `collect_validation`은 schema shape와 verified `pass` 값만 확인하고 active finding에 대한 verdict rubric을 다시 적용하지 않았다.
- Canonical audit spec을 `Path` key dict에 직접 대입해 동일 path의 앞선 lifecycle target을 조용히 덮어썼다.
- Delivery placeholder 검사는 bracket marker와 REQ heading 존재만 확인해 빈 requirement와 acceptance body 및 누락 PLAN section을 허용했다.
- Audit remediation required section 목록을 현재 template에서만 얻어 template과 artifact를 함께 약화하면 검사를 우회했다.
- Finding schema trust anchor는 `severity_reason`의 required 존재만 확인해 property type을 list로 바꾸는 동시 손상을 허용했다.

`audit.schema.yaml`의 실제 verdict rubric과 severity 목록을 source of truth로 계속 사용한다. Reviewer가 별도로 관찰한 `pass.forbidden_severities` 값 변조 방어는 Python 상수로 복제하지 않았다. Runtime은 Markdown heading, label과 nonblank body shape만 확인하고 자연어 의미는 추론하지 않는다. 계약 충돌과 막힌 사항은 없었다.

### RED

Production 변경 전에 다음 adversarial case 5개를 추가했다.

- `case_validate_rechecks_verified_audit_verdict_rubric`
- `case_validate_rejects_canonical_audit_path_collision`
- `case_delivery_placeholder_contract_requires_trusted_sections`
- `case_audit_remediation_required_sections_survive_template_tampering`
- `case_finding_schema_trust_anchor_requires_severity_reason_string`

첫 대상 실행은 `passed=0 failed=6`, exit 1이었다. Delivery case는 artifact shape와 template 동시 손상을 별도 assertion으로 검사해 총 6개 assertion이다. Invalid validate 3개가 exit 0이었고 audit remediation template 및 severity schema 동시 손상 apply 2개가 성공해 STATE bytes를 변경했다.

Delivery body case에는 빈 REQ 뒤의 다른 PRD section에 같은 label을 둔 변형을 추가했다. 첫 수정 뒤 이 assertion은 `passed=1 failed=1`, exit 1로 REQ body 범위가 다음 section까지 새는 결함을 재현했다.

### 구현

- Audit apply에서 사용하던 schema 기반 verdict rubric 검사를 `audit_verdict_errors`로 추출하고 canonical audit validation에서도 재사용했다.
- Closure audit는 initial Git metadata와 closure outcome으로 active finding ID를 계산해 resolved finding은 verdict severity에서 제외하고 current-only 및 still-open finding만 검사한다.
- Plan, work, phase, integration audit spec을 먼저 list로 모은 뒤 resolved canonical path별 lifecycle target 충돌을 명시적 validation error로 보고한다.
- Delivery PRD와 PLAN, audit remediation PRD와 PLAN의 최소 required heading을 고정 trust anchor로 정의했다. Validator는 anchor가 현재 template에 있는지와 artifact의 해당 body가 nonblank인지 각각 검사한다.
- Delivery의 각 REQ block은 `4. Requirements` section 내부에서 nonblank `Requirement`와 `Acceptance criteria` 또는 `AC-*` body를 요구한다. 뒤 section의 같은 label은 앞 REQ를 만족시키지 않는다.
- Finding trust anchor가 `severity_reason` property의 `type: string`을 고정한다. 기존 schema validator가 blank string을 계속 거절한다.
- 새 dependency, sidecar, schema 값 복제, autonomous orchestration은 추가하지 않았다.

### GREEN과 exact commands

새 adversarial case 5개:

```bash
python3 -c 'exec("""import importlib.util, shutil
spec = importlib.util.spec_from_file_location("test_devflow", "plugins/devflow/tests/test_devflow.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
names = ["case_validate_rechecks_verified_audit_verdict_rubric", "case_validate_rejects_canonical_audit_path_collision", "case_delivery_placeholder_contract_requires_trusted_sections", "case_audit_remediation_required_sections_survive_template_tampering", "case_finding_schema_trust_anchor_requires_severity_reason_string"]
for name in names:
    print("\n" + name, flush=True)
    root = m.new_repo()
    try:
        getattr(m, name)(root)
    except Exception as exc:
        m.FAILED.append(name)
        print(f"  FAIL  {name} raised {exc!r}", flush=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
print(f"\npassed={len(m.PASSED)} failed={len(m.FAILED)}")
raise SystemExit(1 if m.FAILED else 0)
""")'
```

RED 결과: `passed=0 failed=6`, exit 1. 최종 결과: `passed=6 failed=0`, exit 0.

Task 7 named, Task 1 placeholder known RED, config mutation matrix는 기존 보고서의 같은 inline runner로 실행했다. 결과는 `passed=20 failed=0`, exit 0이었다.

Task 4부터 6 focused regression도 기존 보고서의 같은 inline runner로 실행했다. 결과는 `passed=38 failed=0`, exit 0이었다.

최종 syntax와 full suite:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
```

결과: py_compile exit 0. Full suite 1회차와 2회차 모두 `passed=372 failed=0`, exit 0.

### Atomicity evidence

- 새 validate case 3개는 실행 전후 domain 전체 file bytes가 동일함을 확인한다.
- Audit remediation template 동시 삭제와 severity schema type 손상 case는 apply 전후 domain 전체 file bytes가 동일함을 확인한다.
- 두 invalid apply는 각각 exit 2이며 STATE와 다른 artifact를 변경하지 않는다.

### Self-review

- Verdict 판단은 `audit.schema.yaml` rubric을 읽는 한 helper에서 apply와 validate가 동일하게 수행한다.
- `pass.forbidden_severities`와 다른 실제 rubric 값은 Python에 복제하지 않았다.
- Path collision은 resolved path와 scope, phase, task target을 비교해 silent overwrite를 제거했다.
- Fixed heading 목록은 template과 artifact를 각각 검증한다. Markdown 본문의 자연어 적절성은 판단하지 않는다.
- `severity_reason`은 required, property 존재, string type, runtime nonblank 검사를 모두 통과해야 한다.
- 기존 Task 7 named와 Task 4부터 6 focused 회귀 및 config mutation matrix가 모두 유지됐다.
- 변경은 runtime, tests, 이 보고서로 제한했다.

### 변경 파일

```text
.superpowers/sdd/devflow-audit-remediation-vnext-work-order/task-7-report.md
plugins/devflow/scripts/devflow.py
plugins/devflow/tests/test_devflow.py
```

커밋 메시지: `fix(devflow): close lifecycle validation gaps`

남은 우려 사항은 없다.

## Fix round 2

### 시작 상태와 assumptions

- 작업일: 2026-09-04
- branch: `main`
- 시작 HEAD: `c9ac22f8da59d79449d3f8c3ea15d5474f58506e`
- 시작 tracked working tree: clean
- branch, worktree, subagent를 만들지 않았다.
- Closure의 prior finding coverage, reopened target, active finding 계산은 apply와 canonical validate가 같은 helper를 사용해야 한다.
- Markdown 검증은 CommonMark ATX heading의 선행 ASCII space 0칸부터 3칸과 고정된 section 및 field shape만 판정한다. 자연어 의미는 판정하지 않는다.
- 빈 list marker와 HTML comment만 있는 body는 evidence가 아니다. 실제 text가 있는 list item은 허용한다.
- 계약 충돌과 막힌 사항은 없었다.

### RED

Production 변경 전에 다음 adversarial case 3개를 추가했다.

- `case_validate_closure_reuses_apply_finding_coverage`
- `case_delivery_markdown_sections_follow_commonmark_boundaries`
- `case_audit_remediation_markdown_sections_reject_empty_duplicates`

실행한 명령은 다음과 같다.

```bash
python3 -c 'import sys; sys.path.insert(0,"plugins/devflow/tests"); import test_devflow as t; t.CASES=[t.case_validate_closure_reuses_apply_finding_coverage,t.case_delivery_markdown_sections_follow_commonmark_boundaries,t.case_audit_remediation_markdown_sections_reject_empty_duplicates]; raise SystemExit(t.main())'
```

Production 변경 전 결과는 `passed=4 failed=6`, exit 1이었다.

- Canonical validate가 prior still-open finding 누락을 허용했다.
- 선행 space 0칸부터 3칸인 정상 heading을 일관되게 읽지 못했다.
- 뒤의 빈 duplicate required heading을 무시했다.
- HTML comment와 빈 list marker를 meaningful body로 허용했다.
- Audit remediation의 유효한 indented heading apply를 거절했다.
- Audit remediation의 빈 duplicate section apply가 성공해 artifact bytes를 변경했다.

### 구현

- `audit_closure_contract` helper가 prior finding 누락, closure coverage, unknown coverage, reopened target, current-only finding, active finding을 한 번 계산한다.
- Audit apply 경로의 `validate_audit_metadata`와 canonical artifact 경로의 `audit_artifact_contract_errors`가 같은 closure helper를 사용한다.
- Canonical closure validation도 Git history에서 읽은 initial audit의 schema와 scope를 확인한 뒤 verdict rubric을 active finding에 적용한다.
- `markdown_sections`가 선행 ASCII space 0칸부터 3칸인 ATX heading을 읽고 4칸인 줄은 heading에서 제외한다. 같은 level 또는 상위 level heading까지만 section body로 묶는다.
- `meaningful_markdown_body`가 HTML comment, 빈 줄, 빈 list marker, 값이 없는 list label을 내용으로 세지 않는다.
- Delivery와 audit remediation required section 검증이 같은 Markdown parser를 사용한다. Required heading이 반복되면 모든 occurrence가 meaningful body를 가져야 한다.
- Delivery REQ 검증은 `4. Requirements` section 내부에서 각 `Requirement`와 `Acceptance criteria` body를 검사한다. 다음 top-level section의 label은 앞 REQ를 만족시키지 않는다.
- 새 dependency, sidecar, autonomous orchestration은 추가하지 않았다.

### GREEN과 exact commands

새 adversarial case 3개:

```bash
python3 -c 'import sys; sys.path.insert(0,"plugins/devflow/tests"); import test_devflow as t; t.CASES=[t.case_validate_closure_reuses_apply_finding_coverage,t.case_delivery_markdown_sections_follow_commonmark_boundaries,t.case_audit_remediation_markdown_sections_reject_empty_duplicates]; raise SystemExit(t.main())'
```

결과: `passed=10 failed=0`, exit 0. Invalid validate와 invalid apply의 실행 전후 domain 전체 file bytes가 동일했다.

Task 7 named, Task 1 placeholder known RED, config mutation matrix:

```bash
python3 -c 'import sys; sys.path.insert(0,"plugins/devflow/tests"); import test_devflow as t; names=["case_validate_rejects_orphan_phase_manifest","case_validate_rejects_phase_document_mismatch","case_delivery_integration_still_requires_verified_phases","case_audit_remediation_verifies_without_fake_phases","case_validate_rejects_applied_audit_lifecycle_mismatch","case_config_protocol_version_is_checked","case_newer_config_protocol_blocks_mutation","case_finding_requires_severity_reason","case_validate_rejects_placeholder_delivery_contract_before_execution"]; t.CASES=[getattr(t,n) for n in names]; raise SystemExit(t.main())'
```

결과: `passed=20 failed=0`, exit 0.

Fix round 1 adversarial regression:

```bash
python3 -c 'import sys; sys.path.insert(0,"plugins/devflow/tests"); import test_devflow as t; names=["case_validate_rechecks_verified_audit_verdict_rubric","case_validate_rejects_canonical_audit_path_collision","case_delivery_placeholder_contract_requires_trusted_sections","case_audit_remediation_required_sections_survive_template_tampering","case_finding_schema_trust_anchor_requires_severity_reason_string"]; t.CASES=[getattr(t,n) for n in names]; raise SystemExit(t.main())'
```

결과: `passed=6 failed=0`, exit 0.

Task 4부터 6 focused regression:

```bash
python3 -c 'import sys; sys.path.insert(0,"plugins/devflow/tests"); import test_devflow as t; names=["case_audit_apply_rejects_missing_front_matter","case_audit_apply_rejects_malformed_front_matter","case_audit_apply_rejects_duplicate_yaml_keys","case_audit_apply_requires_exact_next_action","case_audit_apply_validates_verdict_against_findings","case_audit_apply_validates_finding_links","case_audit_apply_failure_is_atomic","case_audit_apply_updates_state_and_next_action","case_audit_closure_covers_every_prior_finding","case_audit_closure_reopens_finding","case_multi_finding_work_requires_aggregation_reason","case_multi_finding_work_accepts_coherent_explicit_aggregation","case_audit_work_links_are_bidirectional","case_decision_finding_cannot_generate_ready_work","case_decision_finding_requires_decision_id","case_evidence_finding_requires_evidence_work","case_documentation_drift_requires_documentation_work","case_work_cannot_reference_unknown_audit_finding","case_work_v2_requires_unique_acceptance_ids","case_work_v2_requires_unique_verification_ids","case_verification_coverage_requires_every_acceptance_id","case_verification_coverage_rejects_unknown_acceptance_id","case_work_v2_rejects_mixed_legacy_shapes","case_work_v1_remains_readable"]; t.CASES=[getattr(t,n) for n in names]; raise SystemExit(t.main())'
```

결과: `passed=38 failed=0`, exit 0.

Syntax와 full suite:

```bash
python3 -m py_compile plugins/devflow/scripts/devflow.py plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
python3 plugins/devflow/tests/test_devflow.py
```

결과: py_compile exit 0. Full suite 1회차와 2회차 모두 `passed=382 failed=0`, exit 0.

최종 hygiene 명령:

```bash
git diff --check
git branch --show-current
git status --short
git diff --name-only
git diff --unified=0 | rg -n --pcre2 '^\+.*(?:\x{2014}|\x{2013}|\x{00B7}|\x{2026})'
```

결과: diff 공백 검사는 exit 0, branch는 `main`, status와 file list는 아래 변경 파일과 일치했다. 금지 문장부호 검색은 출력 없이 exit 1이었다.

### Full suite twice

같은 최종 code tree에서 전체 suite를 연속 두 번 실행했다.

```text
run 1: passed=382 failed=0, exit 0
run 2: passed=382 failed=0, exit 0
```

추가 실패는 남지 않았다.

### Self-review

- Prior still-open finding이 current metadata에서 사라지면 canonical validate가 명시적으로 거절한다.
- Resolved, still-open, current-only finding 정상 경로는 유지된다.
- Apply와 validate의 closure coverage 및 active finding 판정은 한 helper에 있다.
- Required heading의 모든 occurrence를 검사하며 4칸 indented heading은 code block으로 취급한다.
- HTML comment와 빈 list marker는 delivery와 audit remediation 양쪽에서 meaningful body로 취급하지 않는다.
- 정상 nonblank list item과 선행 space 0칸부터 3칸인 heading은 허용한다.
- 변경은 runtime, tests, 이 보고서로 제한했다.

### 변경 파일

```text
.superpowers/sdd/devflow-audit-remediation-vnext-work-order/task-7-report.md
plugins/devflow/scripts/devflow.py
plugins/devflow/tests/test_devflow.py
```

커밋 메시지: `fix(devflow): unify lifecycle evidence validation`

남은 우려 사항은 없다.
