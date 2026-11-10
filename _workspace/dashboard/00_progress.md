# dashboard 진행 기록

- 상태: in_progress
- FR: FR-09 (대시보드, 리소스)
- 마지막 완료 단계: 4
- 재개할 단계: 5 (개념 문서)
- 검증 대상 코드: `5cb9d4b` (`feature/dashboard`). frontend 내용 해시 `61c3eb62ea4cf79d27231f7db469bc45feb8308d6c13dfd65aec6a62b90e3e14` (`git ls-files -co --exclude-standard -- frontend`로 같은 방식), 백엔드 제품 코드 내용 해시 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3` (FR-08 검증 값과 같음)
- verifier 에이전트 ID: a5087c107ac5a921c (1회차, 2026-11-09 18:17 시작)
- 미해결: 없음

## 선행 확인 (0단계)

- 순서: `_workspace/roadmap.md`는 FR-10 다음에 FR-09를 두었지만, 사용자가 FR-09를 먼저 지정했다 (2026-11-09). FR-09의 의존(FR-02~FR-05)은 모두 `done`이라 순서를 바꿔도 막히지 않는다.
- 조사: 생략 (PRD §8 "FR별 사이클 단계": ANF 포털을 재현하지 않는다).
- 결정: D-02 (React + TypeScript, Vite) 확정. D-08 (메트릭 차트는 Prometheus 쿼리 API)은 FR-12의 일이라 이번 범위가 아니다. D-13 (인증 없음, localhost).
- 스파이크: 데이터 플레인 동작에 기대는 설계가 없어 필요 없다.
- 지금 API가 주는 것 (`backend/anf_api/arm_app.py`): 구독 단위 계정 목록, 계정별 풀 목록, 풀별 볼륨 목록, 볼륨별 스냅샷 목록 GET이 모두 있다. 모든 요청에 `?api-version=2026-08-01`이 필요하다. CORS 헤더는 없다. 구독 목록을 주는 엔드포인트는 없다 (구독 ID는 대시보드가 알아야 한다).
- 환경: Node v22.14.0 / npm 11.3.0은 Windows에만 있다. WSL Ubuntu에는 node가 없다. 브라우저 검증 도구는 Claude in Chrome (`mcp__claude-in-chrome__*`)을 쓸 수 있다.
- 사이클에 딸린 일 (스킬 "기능별 선행 확인"): 프론트엔드 타입 검사·빌드 명령을 `CLAUDE.md` Commands에 더한다. CI frontend 작업(ADR §9.3)을 연다. `real-env-verify`의 환경 점검과 검증 패턴에 브라우저 항목을 더한다.
- 작업 위치: `main` `b5e0e56`에서 `feature/dashboard`. worktree는 하나뿐이다.

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | 트리가 API의 계층·이름·상태와 일치 | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-02 | 지연 주입한 계정 생성: 새로 고침 없이 Creating → Succeeded | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-03 | 실제 볼륨·스냅샷 생성이 새로 고침 없이 보이고 마운트 경로가 API와 같음 | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-04 | 삭제: Deleting 뒤 행이 사라짐 | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-05 | 강제 실패 주입: Failed 배지 | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-06 | anf-api 중지: 오류 배너 + 마지막 트리, 재시작 뒤 자동 복구 | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-07 | typecheck / build / test 통과 | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |
| AC-08 | CI frontend 작업이 PR에서 통과 | PASS | 리더 확인: PR #18 Actions 실행 42741004014 (`pull_request`), `frontend` 작업의 Install·Type check·Test(4 파일 통과)·Build 모두 success. `backend` 작업도 pass | `5cb9d4b` |
| AC-09 | 백엔드 해시 불변, 기존 pytest GREEN | PASS | `04_verifier_report.md` (1회차) | `5cb9d4b` |

## 이력

- 2026-11-09 18:01 단계 0 완료 — 브랜치 `feature/dashboard`, 선행 확인. 1단계 생략, 2단계 설계 상의 시작
- 2026-11-09 18:05 단계 2 완료 — 사용자 확인: Vite 프록시, 목록 GET 폴링(2초), 읽기 전용, AC-01~09. `02_main_design.md`
- 2026-11-09 18:15 단계 3 완료 — `frontend/` (Vitest 23개 통과, 타입 검사·빌드 통과, 테스트를 먼저 써서 모듈마다 RED 확인), CI frontend 작업, `CLAUDE.md`·ADR·`real-env-verify` 갱신. 커밋 `5cb9d4b`. Windows → WSL `127.0.0.1` 전달과 preview 프록시는 손으로 확인(빈 구독 목록 `200`)
- 2026-11-09 18:25 단계 4 시작 — verifier 1회차(AC-01~07, 09). push, PR #18. AC-08 PASS (Actions 실행 42741004014)
- 2026-11-09 18:35 단계 4 완료 — 1회차 8/8 PASS (AC-08은 리더 확인 PASS), FAIL·UNVERIFIED 없음. 23개 변화의 최대 반영 지연 4.2 s(제한 5 s; 4 s를 넘은 둘은 탭이 가려져 Chrome이 타이머를 늦춘 때). 검증 도우미 `backend/tests/e2e/dashboard_watch.py` 추가(해시 범위 밖). 화면 검증 전에 Chrome이 떠 있어야 한다
