> 이 문서는 DevFlow의 최초 설계 근거(design rationale)입니다. 현재 런타임 계약의 정본은 `core/protocol/*.md`와 `core/schemas/`이며, 아래 예시 중 일부는 이후 프로토콜(현재 `protocol_version: 1.2.0`)에서 바뀐 초기 스냅샷입니다. 명령어와 경로, 상태 값은 프로토콜 문서와 스키마를 기준으로 확인하세요.

결론부터 말하면, **재사용 가능한 개발 프로토콜은 충분히 추출 가능하다.** 다만 이전에 제안한 `하나의 Core Skill + 여러 문서 템플릿` 구조는 현재의 문서형 기술부채를 더 정돈된 형태로 재생산할 가능성이 크다.

네 워크플로우의 핵심 병목은 세 가지다.

1. **Chat이 프롬프트 컴파일러 역할을 반복한다.**
2. **계획·작업·검토·개선 단계가 각각 별도 문서로 증식한다.**
3. **현재 상태와 다음 행동을 사람이 문서들을 읽으며 복원한다.**

해결책은 **템플릿 모음**보다 한 단계 위인 **상태 기반 개발 프로토콜 실행기**다.

---

# 1. ZIP에서 확인한 구조적 문제

업로드한 ZIP에는 Markdown 110개, 약 1.98MB의 문서가 있다.

특히 다음 영역에 문서가 집중돼 있다.

| 영역                  | Markdown 수 | 대략적인 크기 |
| --------------------- | ----------: | ------------: |
| `integration-review/` |        47개 |         797KB |
| `phase-review/`       |        14개 |         397KB |
| `design-review/`      |         9개 |         222KB |
| `design-spec/`        |        17개 |         166KB |

대형 문서도 여러 개다.

- `implementation-plan.md`: 약 1,355줄
- `integration-review/README.md`: 약 1,152줄
- `integration-review/remediation-plan.md`: 약 1,535줄
- 통합 remediation 작업지시서: 29개

## 작업지시서 포맷도 실제로 여러 번 변했다

29개 작업지시서는 최소 여섯 종류로 나뉜다.

| 세대   | 대상           | 포맷                                                             |
| ------ | -------------- | ---------------------------------------------------------------- |
| 1세대  | TASK-1~8       | `Objective`, `Why`, `Read First`, `Required Change` 등 영문 중심 |
| 2세대  | TASK-9~11      | 축약된 한글 작업지시서                                           |
| 3세대  | TASK-12~21     | 15개 절로 구성된 정책 중심 포맷                                  |
| 4세대  | TASK-22~26, 29 | 실패 시나리오와 Step A~E 중심                                    |
| 특수형 | TASK-27        | 검증·증거 수집 전용                                              |
| 특수형 | TASK-28        | 문서 동기화 전용                                                 |

이 변화 자체는 개선 과정의 흔적이다. 문제는 **표준 작업 스키마가 없어서 개선 결과가 누적되지 않고 다음 프롬프트 작성자의 판단에 따라 포맷이 다시 만들어진다는 점**이다.

## 문서의 책임도 섞여 있다

`implementation-plan.md`는 원래 구현 순서 문서인데 다음 내용까지 함께 들어가 있다.

- Phase 진행 상태
- Phase별 산출물
- 구현계획
- 계획과 실제 구현의 차이
- Phase 리뷰 후속 조치
- 커밋 규칙
- PR 규칙
- Postman 규칙
- 사용자 확인 상태

`integration-review/remediation-plan.md`는 다음을 한 문서에 포함한다.

- Finding 분류
- 보고서 오류 재검증
- Dependency graph
- 실행 규칙
- 개별 작업지시서
- Focused review 규칙
- 사용자 결정 패킷
- 증거 수집 작업
- 문서 정리
- 최종 회귀 계획
- Exit Criteria

`HANDOFF.md` 끝에 새 세션 시작 프롬프트 예시가 있는 것도 같은 문제를 보여준다. 현재 상태와 다음 행동을 시스템이 계산해 주지 않아서 사람이 인수인계 문서와 시작 프롬프트를 별도로 만들어야 한다.

---

# 2. 기존 문서에서 반드시 재사용할 내용

현재 자료에는 좋은 프로토콜 원칙이 상당히 많다.

## 그대로 살릴 핵심 규칙

### Source of Truth 우선순위

현재 `design-spec/README.md`의 우선순위 체계는 좋다.

```text
확정 사양
→ 구현계획
→ 종합 설계 초안
→ 리뷰 및 조사자료
```

범용 프로토콜에서는 다음처럼 일반화하면 된다.

```text
확정된 사용자 결정
→ 승인된 PRD / 설계 사양
→ 저장소 강제 규약
→ 승인된 구현계획
→ 작업지시서
→ 완료보고와 과거 리뷰
```

사양과 코드가 충돌하면 에이전트가 임의로 하나를 선택하지 않고 `SPEC_DRIFT`로 분류한다.

### 기준 SHA 고정

Phase 리뷰와 통합 리뷰 모두 브랜치 이름보다 커밋 SHA를 기준으로 삼는다. 이 규칙은 반드시 유지해야 한다.

```text
baseline_sha
target_sha
diff_range
```

이 세 값이 모든 검토 산출물에 들어가야 한다.

### 감사 보고서를 코드로 재검증

현재 `HANDOFF.md`에 다음 교훈이 들어 있다.

- 감사 보고서의 파일 경로와 사실 관계도 코드에서 다시 확인한다.
- 이전 보고서를 권위 있는 사실로 취급하지 않는다.
- 구현계획 단계에서 코드베이스를 직접 탐색한다.

이 규칙은 Planner와 Auditor 모두에게 적용해야 한다.

### Finding 분류

현재 통합 리뷰에 있는 분류는 범용성이 높다.

```text
CONFIRMED
DECISION_REQUIRED
EVIDENCE_REQUIRED
REJECTED
DOCUMENTATION_DRIFT
```

각 분류의 후속 처리는 고정할 수 있다.

| Finding 분류          | 후속 처리                           |
| --------------------- | ----------------------------------- |
| `CONFIRMED`           | remediation work item 자동 생성     |
| `DECISION_REQUIRED`   | 사용자 결정 항목 생성               |
| `EVIDENCE_REQUIRED`   | 검증 작업 생성, 제품 코드 수정 금지 |
| `REJECTED`            | 기록만 유지                         |
| `DOCUMENTATION_DRIFT` | 문서 동기화 작업 생성               |

### Dependency가 Severity보다 우선

현재 remediation 규칙에 있는 좋은 원칙이다.

```text
실행 순서 = dependency graph 우선
severity = 같은 dependency level 안에서의 정렬 기준
```

Blocker라고 해도 선행 스키마 변경이 필요한 경우 선행 작업부터 수행해야 한다.

### 이관된 요구사항은 받는 Phase에 등록

결제 작업에서 `PRICE-002`가 Phase 2에서 Phase 8로 이관됐지만 Phase 8 추적표에 등록되지 않아 누락됐다. 이 경험은 범용 규칙으로 만들 가치가 크다.

```text
작업이 다른 Phase로 이관되면:
1. 보내는 Phase에서 transferred 상태 기록
2. 받는 Phase work manifest에 동일한 requirement ID 등록
3. 두 항목을 transfer_id로 연결
```

---

# 3. 이전 답변에 대한 비판적 재검토

이전 답변의 다음 방향은 유지할 가치가 있다.

- Protocol과 프로젝트 산출물의 분리
- Source of Truth 고정
- 범용 리뷰 코어와 도메인별 확장 분리
- Finding과 Task 구분
- 작업지시서 입력·출력 계약 표준화

다음 부분은 다시 설계해야 한다.

## 3.1 하나의 대형 Skill은 현재의 대형 README를 재현한다

이전에는 하나의 `agent-development-protocol` Skill 아래에 여러 reference와 template을 두는 방식을 제안했다.

현재 `integration-review/README.md`가 이미 사실상 그런 역할을 하고 있으며 1,152줄까지 성장했다. 하나의 Skill이 다음을 모두 책임지면 같은 문제가 반복된다.

- 계획
- Task 생성
- 실행
- Phase 리뷰
- 통합 리뷰
- remediation
- handoff
- 상태 관리

따라서 **공통 프로토콜 패키지 하나와 실행 역할별 얇은 진입점 세 개**가 더 적절하다.

```text
Core Protocol
├── plan
├── run
└── audit
```

## 3.2 템플릿 7개도 문서 증식을 유발한다

이전 답변은 다음 템플릿을 제안했다.

```text
implementation-plan
execution-task
phase-review
integration-review
remediation-task
focused-review
handoff
```

이 구조는 현재 문서 종류를 그대로 정규화한 형태다.

다음처럼 축소하는 편이 좋다.

```text
PRD
PLAN
WORK
AUDIT
STATE
DECISIONS  ← 필요할 때만
```

- 일반 구현과 remediation은 모두 `WORK`다.
- Phase 리뷰와 통합 리뷰는 모두 `AUDIT`다.
- Focused review는 `AUDIT`의 closure 모드다.
- Handoff는 `STATE`에서 자동 생성한다.

## 3.3 상태 머신이 빠져 있었다

템플릿만으로는 다음 질문에 답할 수 없다.

- 지금 어느 단계인가
- 다음에 어느 모델을 실행해야 하는가
- 어떤 문서를 입력해야 하는가
- 어떤 결정 때문에 작업이 막혔는가
- 어떤 Task가 실행 가능한가
- Phase가 완료됐는가

이 정보가 없으면 사람이 다시 README, 계획서, Task, 리뷰 문서를 읽어야 한다.

## 3.4 프롬프트 생성기를 설계하지 않았다

네 불만의 직접적인 원인은 Chat에서 매번 다음 프롬프트를 다시 요청하는 것이다.

- 계획 분할 프롬프트
- 구현 검토 프롬프트
- 검토보고서 분할 프롬프트
- 통합 리뷰 프롬프트
- 통합 검증계획 분할 프롬프트

따라서 Skill에는 문서 템플릿만 들어가면 부족하다. **현재 상태와 실행 모드를 입력받아 동일한 프롬프트를 생성하는 deterministic prompt compiler가 필요하다.**

## 3.5 “하나의 root cause”보다 “하나의 검증 가능한 변경 경계”가 정확하다

현재 규칙의 표현은 다음이다.

```text
한 Task = 하나의 root cause
```

실제 구현에서는 하나의 root cause가 DB, Entity, Service, API, Test를 함께 바꿔야 할 수 있다. 더 정확한 정의는 다음이다.

```text
한 Work Item =
하나의 목적
+ 하나의 독립적인 완료 판정
+ 하나의 rollback 경계
+ 하나의 검증 집합
```

파일 수와 계층 수는 분할 기준이 아니다.

---

# 4. 새 프로토콜의 기본 구조

운영 명령은 네 개면 충분하다.

```text
plan
run
audit
status
```

실제 추론 작업은 세 가지 역할이 수행한다.

| 명령     | 역할            | 권장 모델                                    |
| -------- | --------------- | -------------------------------------------- |
| `plan`   | Architect       | Opus 5 / Sol                                 |
| `run`    | Executor        | Sonnet 5 / Luna 5.6 / Qwen3 Coder Next / Hy3 |
| `audit`  | Auditor         | 새 세션의 Opus 5 / Sol                       |
| `status` | 결정적 스크립트 | 모델 불필요                                  |

`remediation`, `focused review`, `integration review`를 별도 명령으로 만들 필요가 없다.

```text
run --kind implementation
run --kind remediation

audit --scope plan
audit --scope phase
audit --scope integration
audit --mode initial
audit --mode closure
```

---

# 5. TO-BE 메인 워크플로우

## 5.1 PRD 작성

Chat에서는 여기까지만 수행한다.

```text
요구사항 구체화
→ 제품/도메인 설계
→ 요구사항 ID
→ Acceptance Criteria
→ 제약과 Non-goals
→ 미확정 정책
```

PRD에는 저장소 파일 경로, 구현 순서, 커밋 단위까지 넣지 않는다. 그 내용은 repo를 실제로 탐색하는 Architect가 작성한다.

현재 PRD에서 “계획”으로 다루던 내용은 다음 두 종류로 분리한다.

| 종류                  | 위치 |
| --------------------- | ---- |
| 제품·도메인 수준 계획 | PRD  |
| 저장소 기반 구현 순서 | PLAN |

## 5.2 구현계획과 작업 분할

Opus/Sol에서 한 번에 수행한다.

```text
/flow plan <PRD 경로>
```

Architect 내부 절차:

```text
1. PRD와 저장소 규약 확인
2. baseline SHA 고정
3. 코드베이스 탐색
4. PRD 모호성·충돌 검사
5. 구현계획 작성
6. Phase와 dependency 구성
7. 각 Phase의 Work Item 생성
8. traceability 검사
9. schema validator 실행
10. STATE 갱신
```

출력:

```text
PLAN.md
work/phase-*.yaml
DECISIONS.md        ← 결정이 필요한 경우
STATE.yaml
```

현재 메인 플로우의 2, 4, 5단계가 하나로 합쳐진다.

구현계획을 별도로 검증할 필요가 있는 고위험 작업에서는 Chat으로 돌아가지 않고 새 Reviewer 세션에서 실행한다.

```text
/flow audit --scope plan
```

결제, 급여, 권한, 보안, 데이터 마이그레이션처럼 위험도가 높은 도메인은 이 Gate를 기본 적용한다.

## 5.3 구현

Executor는 프롬프트 전체를 전달받지 않는다.

```text
/flow run --next
```

`STATE.yaml`과 dependency graph를 읽어 실행 가능한 Work Item 하나를 선택한다.

내부 절차:

```text
1. READY 상태와 dependency 확인
2. 현재 HEAD와 작업 공간 확인
3. 필요한 PRD/PLAN 섹션만 로드
4. 현재 코드에서 Task 전제 재검증
5. 실패 테스트 또는 검증 기준 확립
6. 최소 변경 수행
7. 검증 명령 실행
8. Work Item에 evidence 기록
9. 상태를 DONE 또는 BLOCKED로 변경
10. 다음 작업에 영향을 주는 발견만 기록
```

Executor는 작업지시서 문서를 생성하지 않는다. 이미 생성된 `work/phase-N.yaml`의 Work Item을 실행한다.

## 5.4 Phase Audit

새 Opus/Sol 세션에서 실행한다.

```text
/flow audit --scope phase --phase 5
```

Auditor가 한 번에 수행한다.

```text
1. baseline SHA와 target SHA 고정
2. PRD / PLAN / Work Item 계약 확인
3. diff, 현재 코드, 테스트 직접 확인
4. 완료보고를 실제 코드와 대조
5. Phase Review Core 수행
6. Finding 분류
7. CONFIRMED Finding에서 remediation Work Item 생성
8. DECISION_REQUIRED와 EVIDENCE_REQUIRED 분리
9. STATE 갱신
```

출력:

```text
audits/phase-05.md
work/phase-05.yaml에 remediation 항목 추가
DECISIONS.md 갱신
STATE.yaml 갱신
```

현재 메인 플로우의 7, 8, 9, 10단계가 하나로 합쳐진다.

## 5.5 개선 및 종료 검증

```text
/flow run --next
/flow audit --scope phase --phase 5 --mode closure
```

closure audit 결과:

- Blocker/Major Finding 해결
- Acceptance Criteria 충족
- 요구사항 추적성 유지
- 새 회귀 없음

이 조건을 만족하면 Phase 상태가 `VERIFIED`가 된다.

---

# 6. TO-BE 통합 리뷰 워크플로우

현재 통합 플로우의 다음 두 문서는 책임이 겹친다.

```text
통합테스트계획서
통합검증계획서
```

유효한 통합 검증계획은 코드베이스와 git 이력을 탐색한 뒤에만 만들 수 있다. 따라서 한 번의 repo-aware 통합 감사로 합친다.

```text
/flow audit --scope integration
```

Auditor 내부 절차:

```text
1. 전체 Phase의 baseline과 merge history 확인
2. PRD 요구사항 전체 추적성 확인
3. Phase 간 producer/consumer 계약 확인
4. 데이터와 상태 전이 연결 확인
5. 실패·복구·동시성·멱등성 확인
6. 보안·권한·소유권 확인
7. 마이그레이션·설정·배포 확인
8. 테스트와 실제 증거 확인
9. 도메인 확장 Audit 수행
10. Finding 분류
11. remediation Work Item 직접 생성
12. dependency graph 구성
```

그다음:

```text
/flow run --scope integration --kind remediation
/flow audit --scope integration --mode closure
```

현재 통합 워크플로우의 3~8단계가 `audit` 한 번으로 축소된다.

---

# 7. 현재 단계와 새 단계의 대응

| 현재 작업                            | 새 프로토콜                        |
| ------------------------------------ | ---------------------------------- |
| Chat에서 PRD 작성                    | Chat에서 PRD 작성                  |
| Agent가 실제 구현계획 추출           | `plan`                             |
| Chat에서 구현계획 검증 프롬프트 작성 | `audit --scope plan`               |
| Chat에서 작업 분할 프롬프트 작성     | 제거                               |
| Agent가 작업지시서 생성              | `plan`이 직접 생성                 |
| Agent 구현                           | `run`                              |
| Chat에서 검토 프롬프트 작성          | 제거                               |
| Agent 검토                           | `audit --scope phase`              |
| Chat에서 검토결과 분할 프롬프트 작성 | 제거                               |
| Agent가 검토작업지시서 생성          | `audit`가 직접 생성                |
| Agent 개선                           | `run --kind remediation`           |
| Chat에서 통합 리뷰 프롬프트 작성     | 제거                               |
| 통합테스트계획서 작성                | 제거                               |
| 통합검증계획서 작성                  | `audit --scope integration`에 흡수 |
| 통합개선지시서 생성                  | `audit`가 직접 생성                |
| HANDOFF 작성                         | `status`가 동적으로 출력           |

Chat은 정상 흐름에서 PRD 작성 후 빠진다. 다음 상황에서만 다시 사용한다.

- 제품 정책 결정
- 범위 변경
- 상충하는 요구사항 해소
- 고위험 설계에 대한 제3자 의견

---

# 8. 표준 Artifact 구조

## 재사용 프로토콜

```text
.devflow/
├── protocol/
│   ├── lifecycle.md
│   ├── authority.md
│   ├── work-item-contract.md
│   ├── audit-core.md
│   ├── decision-policy.md
│   └── risk-policy.md
│
├── extensions/
│   ├── default.md
│   ├── billing.md
│   ├── attendance.md
│   └── payroll.md
│
├── schemas/
│   ├── state.schema.yaml
│   ├── work.schema.yaml
│   └── finding.schema.yaml
│
├── prompts/
│   ├── plan.md
│   ├── run.md
│   └── audit.md
│
├── templates/
│   ├── PRD.md
│   ├── PLAN.md
│   ├── STATE.yaml
│   ├── WORK.yaml
│   ├── AUDIT.md
│   └── DECISIONS.md
│
└── scripts/
    └── devflow.py
```

## 도메인별 실행 산출물

```text
docs/domains/{domain}/
├── PRD.md
├── PLAN.md
├── STATE.yaml
├── DECISIONS.md
│
├── work/
│   ├── phase-00.yaml
│   ├── phase-01.yaml
│   └── integration.yaml
│
└── audits/
    ├── phase-00.md
    ├── phase-01.md
    └── integration.md
```

다음 문서들은 사라진다.

```text
개별 TASK-*.md 29개
remediation-plan.md
remediation/README.md
focused-review 별도 문서
HANDOFF.md
통합테스트계획서
통합검증계획서
작업검토지시서
```

복잡한 Work Item도 `work/phase-N.yaml` 안에 저장한다. Prompt compiler가 선택된 Work Item 하나만 추출해 Executor에게 제공한다.

---

# 9. `STATE.yaml`: 인수인계와 다음 행동의 기준

예시는 다음과 같다.

```yaml
protocol_version: 1.1.0

domain: subscription-payment
risk_profile: high
baseline_sha: 4b7fab3
target_sha: cfc84c7

project_status: phase_execution
active_phase: 5

phases:
  "5":
    status: remediation
    work_file: work/phase-05.yaml
    audit_file: audits/phase-05.md

unresolved_decisions:
  - UD-003

next_action:
  role: executor
  command: run
  scope: phase
  phase: 5
  work_item: P05-R02
```

새 세션에서는 다음 한 줄만 실행하면 된다.

```text
/flow status
```

출력:

```text
현재 상태: Phase 5 remediation
다음 역할: Executor
다음 명령: /flow run --task P05-R02
차단 결정: 없음
입력 문서: STATE, PRD의 REQ-021/RULE-014, PLAN Phase 5, P05-R02
```

`HANDOFF.md`와 새 세션 시작 프롬프트를 수동으로 작성할 이유가 사라진다.

---

# 10. 단일 Work Item 스키마

일반 구현, remediation, 테스트, 마이그레이션, 문서 동기화에 동일한 스키마를 사용한다.

```yaml
- id: P05-R02
  kind: remediation
  origin:
    findings: [P05-F03]
    requirements: [RULE-014, IDEM-003]
    plan_items: [P05-04]

  objective: >
    동일한 외부 이벤트가 중복 도착해도 원장 상태가 한 번만 변경되게 한다.

  dependencies: [P05-I04]
  decision_dependencies: []

  scope:
    allowed:
      - core/domain-saas/**/WebhookService.java
      - core/domain-saas/**/WebhookServiceTest.java
    forbidden:
      - API response contract
      - existing Flyway migrations
      - unrelated refactoring

  requirements:
    - 동일 event key는 한 번만 적용한다.
    - 처리 실패 상태는 재시도 가능해야 한다.
    - producer와 consumer 계약을 함께 보존한다.

  verification:
    commands:
      - ./gradlew :core:domain-saas:test --tests '*WebhookServiceTest'
      - ./gradlew check

  acceptance:
    - 중복 이벤트 테스트가 통과한다.
    - 실패 후 재처리 테스트가 통과한다.
    - 기존 API 계약에 diff가 없다.

  stop_conditions:
    - 현재 코드가 Finding의 전제와 다름
    - 허용 범위를 벗어난 스키마 변경이 필요함
    - 사용자 정책 결정이 필요함

  status: ready

  evidence:
    commit: null
    changed_files: []
    commands: []
    deviations: []
    discoveries: []
```

`Completion Report`도 별도 문서가 아니라 `evidence` 필드에 기록한다.

---

# 11. 단일 Audit 스키마

Phase와 Integration이 같은 Finding 형식을 사용한다.

```yaml
id: P05-F03
scope: phase
classification: confirmed
severity: major
axis: concurrency

expected: 동일 이벤트가 한 번만 원장에 반영된다.
actual: 두 요청이 동시에 처리되면 두 번 반영될 수 있다.

evidence:
  - file: WebhookService.java
    lines: 84-112
  - command: ./gradlew ...
    result: failed

root_cause: 중복 확인과 상태 변경이 하나의 원자적 경계에 있지 않음

disposition:
  action: create_remediation
  work_item: P05-R02
```

다음 분류에서는 코드 수정 Task를 생성하지 않는다.

```text
DECISION_REQUIRED
EVIDENCE_REQUIRED
REJECTED
```

---

# 12. Phase Audit과 Integration Audit의 공통 코어

## 공통 Audit Core

```text
A. 요구사항 및 계획 추적성
B. Source of Truth 준수
C. 저장소 및 아키텍처 규약
D. 코드 수준 설계와 계약
E. 테스트 및 실행 증거
F. 과설계, 잔재, 범위 침범
G. 실패와 복구
H. 동시성 및 멱등성
I. 보안, 권한, 소유권
J. 마이그레이션, 설정, 배포
```

## Phase 모드

현재 Phase의 계획, diff, 테스트, acceptance를 집중 검증한다.

## Integration 모드

다음 항목을 추가한다.

```text
Phase 간 producer/consumer 계약
Phase 간 요구사항 이관
전체 상태 머신
end-to-end 데이터 흐름
교차 모듈 transaction 경계
배포 및 migration 순서
전체 회귀와 evidence gap
```

## 도메인 확장

결제 전용 항목은 Core에서 분리한다.

```text
billing.md
- 금액 보존 불변식
- 결제·취소·환불 원장
- PG 상태 매핑
- Webhook/reconciliation
- 결제와 구독 상태의 결합

attendance.md
- 출퇴근 시각 불변식
- 타임존과 날짜 경계
- 수정 승인 상태 머신
- 근로시간 집계

payroll.md
- 계산·재계산 불변식
- 마감 이후 변경
- 소급 적용
- 원 단위 반올림과 합계 보존
```

---

# 13. Prompt compiler의 역할

`devflow.py`가 다음 기능을 담당해야 한다.

```bash
devflow init <domain>
devflow validate <domain>
devflow status <domain>
devflow next <domain>
devflow render plan <domain>
devflow render run <domain> --task P05-R02
devflow render audit <domain> --scope phase --phase 5
```

## `render`가 조립할 내용

### Plan

```text
공통 Architect 규칙
+ PRD
+ 저장소 규약
+ 현재 baseline
+ PLAN/WORK output schema
```

### Run

```text
공통 Executor 규칙
+ 선택된 Work Item 하나
+ 연결된 요구사항 섹션
+ 연결된 PLAN 항목
+ 관련 저장소 규약
```

### Audit

```text
공통 Auditor 규칙
+ Audit Core
+ 도메인 extension
+ baseline / target
+ 관련 PRD / PLAN / WORK
+ Finding output schema
```

Chat에서 프롬프트를 작성하는 단계가 이 스크립트로 대체된다.

`validate`는 최소한 다음을 검사해야 한다.

- 중복 ID
- 존재하지 않는 dependency
- dependency cycle
- 누락된 Acceptance Criteria
- 검증 명령 누락
- 해결되지 않은 결정에 의존하는 READY Task
- PRD ID와 PLAN/WORK 추적성
- 허용되지 않은 상태 전이
- Phase 간 이관 누락
- YAML 파싱 오류

---

# 14. Agent별 Adapter

공통 프로토콜은 특정 AI 제품에서 분리한다.

```text
Core Protocol
        │
        ├── ChatGPT adapter
        ├── Claude Code adapter
        ├── Codex adapter
        ├── Kiro adapter
        └── OpenCode adapter
```

각 Adapter는 아주 얇게 유지한다.

## ChatGPT

- PRD 작성
- 사용자 결정 정리
- 필요 시 Plan에 대한 제3자 검토

## Claude Code / Codex

- `plan`
- `run`
- `audit`
- `status`

## Kiro / OpenCode

- `run`만 설치해도 충분
- 이미 Opus/Sol이 생성한 Work Item 실행
- 동일한 Work Item schema와 Completion evidence 사용

이 구조에서 Kiro와 OpenCode용 프롬프트를 별도로 만들 필요가 없다.

---

# 15. 리뷰 체크포인트도 위험도 기반으로 바꿔야 한다

현재 문서에는 Task마다 다음 순서를 강제한다.

```text
Luna 수정
→ 검증
→ Opus Focused Review
→ 다음 Task
```

8개 Task를 한꺼번에 끝낸 뒤 리뷰하면서 결함이 누적된 경험 때문에 나온 규칙이다. 이 경험은 유효하다.

모든 Task를 동일하게 리뷰하면 비용과 시간이 커진다. 다음처럼 위험도와 dependency를 기준으로 적용하는 편이 좋다.

| Work Item                                  | Review 시점                       |
| ------------------------------------------ | --------------------------------- |
| Blocker, Major                             | 다음 의존 Task 전에 closure audit |
| DB migration, 상태 머신, 동시성, 외부 계약 | Task 직후 closure audit           |
| 후행 Task가 현재 결과에 의존               | 후행 Task 전에 closure audit      |
| 독립적인 Minor, 문서 정리                  | Phase 끝에 묶어서 audit           |
| Nit                                        | Phase Audit에서만 확인            |

이 규칙은 품질과 모델 사용량을 함께 관리한다.

---

# 16. 실제 구축 순서

현재 `구독-결제` 문서를 먼저 재배치하는 작업은 뒤로 미루는 게 맞다.

## 1단계: 프로토콜 추출

다음 문서에서 범용 규칙만 가져온다.

```text
design-spec/README.md
implementation-plan.md의 공통 실행 규칙
phase-review/README.md
integration-review/README.md
integration-review/remediation.md
integration-review/HANDOFF.md의 learned lessons
대표 TASK 4종
```

결제 상태, PortOne, 가격 규칙 같은 내용은 `billing` extension 예시로만 사용한다.

## 2단계: Artifact schema 확정

먼저 다음 세 스키마를 고정한다.

```text
STATE
WORK
FINDING
```

Markdown 템플릿보다 이 스키마가 먼저다.

## 3단계: validator와 prompt compiler 구현

```text
init
validate
status
next
render
```

이 다섯 기능을 만든다.

## 4단계: 역할별 프롬프트 작성

```text
plan
run
audit
```

세 개만 작성한다.

## 5단계: 도구별 얇은 Adapter 생성

같은 Core Protocol을 Claude Code, Codex, Kiro, OpenCode에서 읽도록 연결한다.

## 6단계: 다음 신규 도메인에서 Pilot

기존 결제 문서를 전부 변환하기보다 다음 도메인에 처음부터 적용한다.

Pilot에서 확인할 항목:

- Chat 왕복이 실제로 줄었는가
- Work Item 품질이 일정한가
- 상태 복원이 가능한가
- Plan과 Audit이 동일한 스키마를 지키는가
- 사용자 결정만 정확히 차단되는가
- 다른 모델에서도 동일하게 실행되는가

## 7단계: 결제 문서는 Archive 사례로 보존

새 프로토콜이 검증된 다음 기존 결제 문서는 다음 정도만 정리한다.

```text
현재 Source of Truth
현재 STATE
최종 PLAN
최종 Audit
나머지 전체 Archive
```

---

가장 적절한 최종 형태는 **하나의 거대한 개발 Skill**이 아니라, **repo에 상주하는 Core Protocol + `plan/run/audit` 세 진입점 + 상태·스키마·프롬프트를 관리하는 `devflow` 실행기**다. 이 구조를 기준으로 만들면 정상 작업에서 Chat은 PRD 작성 한 번만 사용하고, 이후 Phase 작업과 통합 리뷰는 에이전트 명령만으로 끝낼 수 있다.
