# dashboard 진행 기록

- 상태: in_progress
- FR: FR-09 (대시보드, 리소스)
- 마지막 완료 단계: 0
- 재개할 단계: 2 (설계 상의. 1단계 조사는 PRD §8 표에 따라 생략)
- 검증 대상 코드: 아직 없음
- verifier 에이전트 ID:
- 미해결: 2단계에서 사용자에게 물은 설계 선택 (API 연결 방식, 갱신 방식, 범위)

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

## 이력

- 2026-11-09 18:01 단계 0 완료 — 브랜치 `feature/dashboard`, 선행 확인. 1단계 생략, 2단계 설계 상의 시작
