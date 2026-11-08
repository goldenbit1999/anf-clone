# capacity-pool 진행 기록

- 상태: done
- FR: FR-03 (용량 풀). 계정 사이클에서 옮겨 온 기준: 자식 풀이 남은 계정 DELETE의 `409 CannotDeleteResource` (FR-02, 계정 설계 결정 8)
- 마지막 완료 단계: 6
- 재개할 단계: 없음. 볼륨 사이클에서 CV-1~CV-3(용량 검사 실환경)을 검증한다
- 검증 대상 코드: 미커밋 (기준 커밋 `e602d11`). 제품 코드 `pyproject.toml`, `backend/anf_api/{__init__,accounts,arm_app,arm_rules,capacity_pools,lro,state_store}.py`를 이 순서로 이어 붙인 sha256 = `a461dbaf36e65c53e3b8a0bb2aee3379fa391f8b9fb5889c08b2247e8a038485` (`cat pyproject.toml backend/anf_api/__init__.py backend/anf_api/accounts.py backend/anf_api/arm_app.py backend/anf_api/arm_rules.py backend/anf_api/capacity_pools.py backend/anf_api/lro.py backend/anf_api/state_store.py | sha256sum`, Git Bash와 WSL 값 같음). `capacity_pools.py`가 새 파일이라 `git diff HEAD`에 잡히지 않아 파일 해시로 남긴다. 1회차 검증 대상은 `f58df82db294ebb8061950d4af80ca8e83996e297df8c3a7775952f4bd154723`였고, 그 뒤 바뀐 것은 `capacity_pools.py`의 오류 메시지 두 줄뿐이다 (`02_main_design.md` "구현 중 변경")
- verifier 에이전트 ID: a768b20fddf69bd04 (1회차·2회차, 2026-11-07. 계정 회귀 재검증도 함께 맡김)
- 미해결: 없음

## 선행 확인 (0단계)

- 상위 리소스: 계정(`netapp-account`)이 `done` (`docs/feature-status.md`).
- 결정: D-07(SQLite), D-09(프로세스 안 워커), D-13(인증 없음) 확정. 공통 LRO 계층(`backend/anf_api/lro.py`, `state_store.py`)을 재사용한다.
- 스파이크: 용량 풀은 S0가 필수가 아니다 (anf-feature-cycle "기능별 선행 확인"). S0는 이미 통과 (`_workspace/spikes/S0.md`).
- 2단계에서 정할 것:
  - 용량 계산 규칙, 동시성·예약 규칙 (ADR §6.4 "풀·볼륨 설계 전에 확정할 규칙"). 볼륨이 아직 없으므로 풀 사이클에서 무엇을 확정하고 무엇을 볼륨 사이클로 넘길지 정한다.
  - ADR §6.1 작업별 응답 표의 풀 행 (특히 PATCH: 녹화에서 `202` + `Patching`, ADR §6.3).
  - ADR §2.3 용량 풀 행 (storage agent에 무엇을 만들지. 지금은 "컨트롤 플레인만").
  - 서비스 수준·QoS 유형(Auto/Manual)이 처리량 제한(FR-08)과 어떻게 이어지는지, 이번에 무엇을 저장만 하고 무엇을 미루는지.

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | 새 풀 PUT → 201 Creating + Azure-AsyncOperation만 → Succeeded, GET 필드 | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-02 | 처리량 계산 (Standard 2 TiB 32.0, Ultra 1 TiB 128.0, Premium 1 TiB 64.0) | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-03 | PUT 갱신 → 200 Updating → Succeeded, tags 교체, 빠진 속성 유지, serviceLevel 변경 | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-04 | PATCH → 202 Patching + 두 헤더 → Succeeded(PATCH), Manual → Auto 거절 | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-05 | 목록, 없는 계정·풀 404, 대소문자 | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-06 | 잘못된 요청 400/409 거절, 작업·상태 변화 없음 | PASS | `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-07 | 없는 계정 404 ParentResourceNotFound, 계정 Deleting 중 409 Conflict | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-08 | DELETE 202 → Location 204 → GET 404 → 재DELETE 204 | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-09 | 풀이 있는 계정 DELETE → 409 CannotDeleteResource (FR-02 이월) | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-10 | 지연·실패 주입: 진행 중 상태, 생성 실패와 회복, PATCH 실패와 되돌리기 | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-11 | 진행 중 충돌 → 409 AnotherOperationInProgress | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-12 | 생성·PATCH 진행 중 SIGKILL → 재시작 뒤 Succeeded | PASS (1회차 판정 유지, 2회차 e2e 회귀 통과) | `04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차) | a461dbaf… |
| AC-13 | 풀 작업 전후 데이터 플레인 불변 | PASS (2회차에서 다시 돌리지 않음, 1회차 판정 유지) | `04_verifier_report.md` (1회차) | f58df82d… |

AC-06 외의 1회차 PASS를 유지하는 근거: 1회차 뒤의 변경은 `_check_service_level`과 `encryptionType` 검사가 던지는 오류의 메시지 문자열 두 개뿐이다. 오류 코드·상태 코드·분기는 그대로이고, 다른 기준의 코드 경로는 이 메시지를 쓰지 않는다. 2회차에서 e2e 스크립트(풀 39개, 계정 24개)를 새 코드로 두 번 돌려 모두 통과했다. AC-13은 셸 비교 항목이라 e2e에 없고, 데이터 플레인 코드가 없는 이 변경으로 결과가 바뀔 수 없어 1회차 판정을 유지한다.

## 이력

- 2026-11-07 단계 0 완료 — 문서·진행 기록 확인. 계정 `done`, 용량 풀 폴더 없음 → 1단계부터. 풀 녹화(.NET `PoolTests__*`, Python `test_pool.py*`)는 계정 조사 때 `_workspace/netapp-account/sources/recordings/`에 이미 있다.
- 2026-11-07 단계 1 시작 — anf-researcher에 조사를 맡겼다.
- 2026-11-07 단계 1 완료 — 조사 상태 `완료` (`01_researcher_brief.md`). 설계를 막는 미확인은 없다. 실서비스 근거가 없는 것(용량·처리량 초과 오류의 HTTP 코드와 `error.code`, 동기·비동기 여부, Manual → Auto 거절 코드, PUT 갱신에서 빠진 `size`·`serviceLevel` 처리)은 클론이 정하고 문서화한다. 스펙과 녹화가 다른 곳: PUT 201 헤더(스펙 `Location`, 녹화 `Azure-AsyncOperation`), PATCH 202 본문(스펙 없음, 녹화 `Patching` 본문). 리더가 녹화에서 직접 확인: PATCH 작업 상태의 `properties.action`은 `PATCH`이고, PATCH 202 본문은 바뀌기 전 tags에 `Patching`을 붙여 돌려줬다 (N2).
- 2026-11-07 단계 2 시작 — 설계안과 선택지 4개를 사용자에게 제시했다.
- 2026-11-07 단계 2 완료 — 사용자가 선택지 4개를 모두 추천안으로 확정했다: 응답 형식은 녹화를 따름(결정 1), 풀 쪽 용량 검사는 지금 구현·실검증은 볼륨 사이클(결정 3), 규칙 위반은 동기 400(결정 4), serviceLevel은 빈 풀만 변경 허용(결정 5). `02_main_design.md`에 AC-01~AC-13과 볼륨 사이클 이월 기준 CV-1~CV-3을 적었다. ADR §2.3·§6.1·§6.3·§6.4·§9.1과 PRD FR-03을 고쳤다. 새 결정(D-nn)은 없다.
- 2026-11-07 단계 3 시작 — 구현.
- 2026-11-07 단계 3 완료 — TDD로 구현했다(모듈마다 RED 확인 뒤 GREEN: `arm_rules`, `state_store`, `lro`, `capacity_pools`, `arm_app`). 테스트 277 passed, 24 skipped (Windows·WSL 같음). 풀 계약 테스트 43개가 AC-01~AC-12와 CV-1~CV-3을 TestClient로 확인한다 (실환경 PASS 아님). WSL uvicorn 기동 확인: 풀 PUT 201 → Succeeded, PATCH 202 + 두 헤더, 풀이 남은 계정 DELETE 409. 구현 중 변경은 `02_main_design.md` 끝에 있다. 공통 코드(`accounts.py` 정리, `lro.py`, `state_store.py`, `arm_app.py`)가 바뀌어 계정 검증이 무효가 됐다 → 계정을 `in_progress`로 되돌리고, 이번 검증에서 계정 e2e를 함께 다시 돌린다.
- 2026-11-07 단계 4 시작 — real-env-verifier 1회차를 띄웠다 (풀 AC-01~AC-13, 계정 회귀 AC-01~AC-13 → `_workspace/netapp-account/04_verifier_report_r2.md`).
- 2026-11-07 단계 4 1회차 완료 — 풀 PASS 13 / FAIL 0 / UNVERIFIED 0 (`04_verifier_report.md`), 계정 회귀 PASS 13/13 (`_workspace/netapp-account/04_verifier_report_r2.md`). 검증 시작·끝의 코드 해시가 `f58df82d…`로 같았다. 판정 밖 관찰: (1) WSL 단조 시계가 호스트보다 약 10% 느리다 → 처리량 스파이크 S2와 FR-08 측정 조건에 반영할 것, (2) Flexible·Double 거절 메시지의 따옴표가 겹친다 → 고침, (3) PATCH 202 본문이 바뀐 뒤 값 → 설계 결정 9로 의도한 차이.
- 2026-11-07 단계 3 보완 — 관찰 (2)를 TDD로 고쳤다 (메시지 테스트 RED → `capacity_pools.py` 두 줄 → GREEN, 전체 279 passed). 새 해시 `a461dbaf…`. AC-06을 재검증 대기로 돌렸다.
- 2026-11-07 단계 4 2회차 완료 — PASS 13 / FAIL 0 / UNVERIFIED 0 (`04_verifier_report_r2.md`). AC-06을 실환경에서 다시 판정했다: Flexible·StandardZRS·Double의 새 메시지, 나머지 경우는 1회차와 글자 단위로 같음, 거절 뒤 작업·상태 변화 없음. e2e 회귀 63 passed × 2회(풀 30+9, 계정 16+8). 해시는 시작·끝, Git Bash·WSL 모두 `a461dbaf…`. verifier가 `test_capacity_pool_live.py`에 StandardZRS 경우를 더하고 미룬 기능 다섯 경우를 메시지 전체로 비교하게 바꿨다(Windows 전체 279 passed, 63 skipped). 검증 시작 때 8080에 이 검증과 무관한 anf-api(pid 8387, `manual-test.db`, 지연 주입 켜짐)가 떠 있어 verifier는 8081을 썼다. 리더가 확인했을 때는 이미 꺼져 있었다.
- 2026-11-07 단계 5 시작 — concept-explainer에 `docs/concepts/capacity-pool.md`를 맡겼다 (01·02·04·04_r2·00_progress, 변경 파일 목록 전달).
- 2026-11-07 단계 5 완료 — `docs/concepts/capacity-pool.md` (344줄, 면접 Q&A 9개). 리더가 `capacity_pools.py` 인용 범위를 함수 경계와, 계약 테스트 수(43개 수집)를 실행으로 대조했다. 브리프에 없어 쓰지 못한 것(풀에 대응하는 ONTAP 객체, 클론이 정한 오류 코드의 실서비스 값 등)은 문서 부록에 있다.
- 2026-11-07 단계 6 완료 — `done`. 검증 대상 코드 `a461dbaf…`(미커밋). 커밋하면 커밋 SHA로 바꾼다.
