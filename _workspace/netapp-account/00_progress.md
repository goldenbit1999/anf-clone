# netapp-account 진행 기록

- 상태: done (용량 풀 사이클의 공통 코드 변경 뒤 재검증·문서 수정을 마치고 복원, 2026-11-07)
- FR: FR-01 (비동기 작업, 공통 LRO 계층), FR-02 (NetApp 계정)
- 마지막 완료 단계: 6
- 재개할 단계: 없음
- 검증 대상 코드: 커밋 `41f863d` (main, PR #5 squash merge, 2026-11-07). 제품 코드 내용 해시 `f2b70558c8189ab44ba210081d30ed52978c8e56f529ddba84edeb12656bc955` (`anf-feature-cycle` 3단계 4번의 명령, 줄 끝 무관). 검증은 미커밋 상태에서 옛 방식 해시 `a461dbaf…`로 했다. 옛 방식은 파일 8개를 그대로 이어 붙여 줄 끝에 따라 값이 달라진다. `41f863d`의 내용을 검증 당시의 줄 끝(`capacity_pools.py`만 LF, 나머지 7개 CRLF)으로 재구성하면 `a461dbaf…`가 정확히 나오므로, 검증한 코드와 커밋된 코드는 같다
- verifier 에이전트 ID: adc067e6dfaf099df (1회차), a768b20fddf69bd04 (2회차, 용량 풀 verifier가 함께 맡음)
- 미해결: 없음

## 선행 확인 (0단계)

- 결정: D-07(SQLite), D-09(anf-api 프로세스 안의 워커), D-13(인증 없음) 모두 확정 (ADR §11). 다시 묻지 않는다.
- 스파이크: 계정은 S0가 필수가 아니다 (anf-feature-cycle "기능별 선행 확인"). S0는 이미 통과 (`_workspace/spikes/S0.md`).
- 2단계에서 정할 것: ADR §6.1 작업별 응답 표, ADR §6.5 저장 모델(스키마), ADR §2.3 계정 행(백엔드에 무엇을 만들지).
- 상위 리소스: 없음. 계정이 계층의 맨 위다.

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | PUT 신규 → 201 Creating + Azure-AsyncOperation → Succeeded | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-02 | PUT 기존 → 200 Updating → Succeeded, tags 교체 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-03 | GET 본문, 404 ResourceNotFound, 대소문자 무시 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-04 | 리소스 그룹·구독 목록 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-05 | PATCH tags 동기 200 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-06 | 이름·api-version·본문·location 검증 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-07 | DELETE 202 → Location 204 → GET 404 → 재DELETE 204 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-08 | 지연 주입 중 진행 상태, Location 202 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-09 | 실패 주입 → Failed, PUT으로 회복, 삭제 실패 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-10 | 진행 중 충돌 409 AnotherOperationInProgress | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-11 | SIGKILL 뒤 재시작 복구 | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-12 | 데이터 플레인 불변 (exportfs 전후 동일) | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |
| AC-13 | x-ms-request-id, 상관 ID | PASS | `04_verifier_report_r2.md` (2회차) | f58df82d… |

용량 풀 사이클로 옮긴 기준: 자식 풀이 남은 계정 DELETE의 `409 CannotDeleteResource` (설계 결정 8).

2회차는 용량 풀 사이클의 공통 코드 변경 뒤 계정 e2e 스크립트로 다시 돌린 회귀다. 옮긴 기준은 풀 사이클의 AC-09에서 PASS했다 (`_workspace/capacity-pool/04_verifier_report.md`). 2회차 뒤 `capacity_pools.py`의 풀 전용 오류 메시지 두 줄이 바뀌어 해시가 `a461dbaf…`가 됐다. 계정 코드 경로는 이 메시지를 쓰지 않으며, 풀 2회차에서 계정 e2e를 새 코드로 다시 돌린다.

## 이력

- 2026-11-07 단계 0 완료 — 문서·진행 기록 확인. `docs/feature-status.md`를 처음 만들었다.
- 2026-11-07 단계 1 시작 — 계정 브리프(2026-11-07)는 있음. FR-01 공통 LRO 계층 설계에 필요한 질문(ARM 작업 상태 본문, `Location` 폴링 의미, `Retry-After`, 진행 중 작업과의 충돌 오류, 실패한 작업의 모습, api-version 오류)만 보완 조사로 맡겼다.
- 2026-11-07 단계 1 완료 — 보완 조사 상태 `완료`. 설계를 막는 미확인은 없다. 남은 [미확인](ANF `Location` 폴링의 실제 응답, 충돌 오류 코드, 비동기 실패 뒤 `provisioningState`, api-version 오류 코드)은 RPC 규칙을 따르거나 클론이 정하고 개념 문서에 적는다.
- 2026-11-07 단계 2 시작 — 설계안과 선택지 4개를 사용자에게 제시했다.
- 2026-11-07 단계 2 완료 — 사용자가 선택지 4개를 모두 추천안으로 확정했다(백엔드 없음, 결함 주입, PUT 갱신 비동기, 409 검사는 지금 구현하고 실환경 검증은 풀 사이클). 충돌 코드는 제시한 기본값 `Conflict` 대신 ARM 공통 오류 목록에 있는 `AnotherOperationInProgress`로 바꿨다. ADR §2.3·§6.1·§6.3·§6.4·§6.5·§9.1과 PRD FR-02를 고쳤다.
- 2026-11-07 단계 3 시작 — 구현.
- 2026-11-07 단계 3 완료 — TDD로 구현했다 (모듈마다 RED 확인 뒤 GREEN). 단위·계약 테스트 141개가 Windows와 WSL에서 모두 통과했다. AC-01~AC-11, AC-13과 자식 409는 계약 테스트(TestClient)로도 확인했지만, 이것은 실환경 PASS가 아니다. WSL에서 문서의 uvicorn 명령으로 기동하고 PUT 한 번을 해 봤다(201 → Succeeded). 구현 중 변경은 `02_main_design.md` 끝에 있다.
- 2026-11-07 단계 4 시작 — real-env-verifier 1회차를 띄웠다 (WSL에서 uvicorn으로 띄운 HTTP 서버, AC-01~AC-13).
- 2026-11-07 단계 4 완료 — 1회차 PASS 13 / FAIL 0 / UNVERIFIED 0. 검증 대상 코드 해시가 시작과 끝에서 일치했다. AC-12의 한계: 검증 전 export가 0개라, 기존 export가 지워지지 않는지는 이 조건으로 보이지 않았다. 계정 코드에는 storage 호출이 없어 영향은 없다고 판단한다. 검증 스크립트 `backend/tests/e2e/`(ANF_E2E_API_URL이 없으면 skip). 기본 실행은 141 passed, 24 skipped.
- 2026-11-07 단계 5 시작 — concept-explainer에 개념 문서를 맡겼다.
- 2026-11-07 단계 5 완료 — `docs/concepts/netapp-account.md` (면접 Q&A 8개). 리더가 검토하면서 "실제 ANF와 다른 점" 표의 `Location` 행과 부록 한 줄을 고쳤다: ANF의 진행 중 `Location` 응답도 [미확인]인데 확인된 것처럼 읽혔다.
- 2026-11-07 단계 6 완료 — PRD §8의 완료 정의를 모두 충족해 `done`으로 기록했다. 검증 대상 코드 해시는 검증 뒤에도 그대로다(`bf4e61d3…`). 제품 코드는 아직 커밋하지 않았다.
- 2026-11-07 커밋·merge — 브랜치 커밋 `ca95839`을 PR #4로 main에 squash merge했다(`e602d11`, 트리 동일). 커밋 직전 제품 코드 해시가 검증 때와 같았다(`bf4e61d3…`). 테스트 141 passed, 24 skipped (Windows).
- 2026-11-07 무효화 — 용량 풀 사이클(3단계)이 계정이 쓰는 공통 코드를 바꿨다: `accounts.py`(오류·본문 검사 함수를 `arm_rules.py`로, 자식 검사를 `Tx.ensure_no_children`으로 옮김. 동작 변화 없음), `lro.py`(PATCH 작업, 결함 키를 처리기에서 만듦), `state_store.py`, `arm_app.py`(풀 라우트, 종류별 본문). 계정 단위·계약 테스트는 모두 통과하지만, 검증 대상 코드 해시가 `bf4e61d3…`에서 `f58df82d…`로 바뀌어 AC-01~AC-13의 실환경 결과는 다시 확인하기 전까지 유효하지 않다. 개념 문서의 코드 인용(`accounts.py` 줄 번호, 자식 검사 위치 `accounts.py:192-200`)도 낡았다.
- 2026-11-07 단계 4 2회차 완료 — 용량 풀 verifier(a768b20fddf69bd04)가 계정 e2e 회귀를 새 공통 코드(`f58df82d…`)로 돌렸다: PASS 13 / FAIL 0 / UNVERIFIED 0 (`04_verifier_report_r2.md`). 남은 일: 5단계(개념 문서의 낡은 코드 인용 고치기) 뒤 `done`으로 복원.
- 2026-11-07 단계 5 완료 (문서만 수정) — concept-explainer가 `docs/concepts/netapp-account.md`의 코드 인용 약 50곳을 현재 코드에 맞췄다. 자식 검사 위치(`Tx.ensure_no_children`), 결함 키를 처리기에서 만드는 방식, `_finish`의 UPDATE·PATCH 되돌리기, 자식 409의 실환경 PASS(풀 AC-09), 2회차 보고서를 반영했다. 면접 Q&A 8개 유지, Q7 한 문장만 고침. 리더가 인용 일부(`accounts.py:164`, `state_store.py:152-164`, `lro.py:147`, `arm_rules.py:22·35·107`, `state_store.py:260`)를 코드와 대조했다. 수락 기준은 그대로다. 남은 일: 풀 2회차의 계정 e2e 회귀(`a461dbaf…`) 결과를 받으면 `done`으로 복원.
- 2026-11-07 단계 6 완료 — `done` 복원. 용량 풀 2회차에서 계정 e2e(`test_netapp_account_live.py` 16, `test_netapp_account_lro_faults_live.py` 8)를 새 코드 `a461dbaf…`로 두 번 돌려 모두 통과했다. `f58df82d…` → `a461dbaf…` 사이에 바뀐 것은 풀 전용 오류 메시지 두 줄뿐이라 계정 AC 판정(2회차)은 그대로 유효하다.
- 2026-11-07 기록 정리 — 공통 코드가 PR #5로 merge됐다(`41f863d`). 검증 대상 코드를 그 커밋과 줄 끝에 무관한 내용 해시 `f2b70558…`로 바꿨다. 이유는 용량 풀 진행 기록의 같은 날 "기록 정리" 항목에 있다. 판정은 그대로다.
