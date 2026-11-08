# ci 진행 기록

- 상태: in_progress
- FR: FR-11 (CI). 이번 범위는 backend 작업이다. frontend 작업(FR-09 뒤)과 data-plane 작업(S3 뒤)은 남는다
- 마지막 완료 단계: 3
- 재개할 단계: 4 (GitHub Actions 실행 결과로 검증)
- 검증 대상 코드: 제품 코드는 바꾸지 않는다 (내용 해시 `f2b70558…` 유지, AC-07). 검증 대상은 워크플로 파일과 커밋 SHA다
- verifier 에이전트 ID:
- 미해결: 없음

## 선행 확인 (0단계)

- PRD §8: FR-11은 1단계(조사)를 생략하고 2~6단계를 거친다. 개념 문서는 엔지니어링 관점이고 ANF·ONTAP 절은 "해당 없음"이다.
- ADR §9.3: backend 작업은 선행 조건이 없다. data-plane 작업은 S3 통과 뒤다.
- 계획상 FR-11은 2단계(핵심 기능 뒤)지만, 사용자가 지금 만들기로 했다. 이유: PR #4, #5가 검사 없이 merge됐고, 다음 기능(볼륨)이 공통 코드를 크게 바꾼다.
- 미리 확인한 것: ruff 0.14.0 기본 규칙 위반은 `backend/tests/e2e/test_netapp_account_lro_faults_live.py:37`의 F841 1건뿐이다. 훅 테스트는 WSL(Linux)에서 25 passed(약 10초)다. 라이브 e2e는 root가 필요 없고 테스트가 uvicorn을 직접 띄운다.

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |

## 이력

- 2026-11-07 단계 0 완료 — 문서 확인. 조사 생략(PRD §8).
- 2026-11-07 단계 2 완료 — 사용자가 범위(단위·계약 + 라이브 API e2e), 린트(ruff 기본 규칙), 러너(ubuntu만)를 골랐다. `02_main_design.md`에 결정 1~8과 AC-01~AC-07을 적었다. 같은 브랜치의 앞 커밋(`e4acc7a`)에서 해시 절차와 계정·풀 기록을 따로 정리했다.
- 2026-11-07 단계 3 완료 — `.github/workflows/ci.yml`(backend 작업: 설치, 린트, 테스트, skip 검사, 훅 테스트), F841 수정(`test_netapp_account_lro_faults_live.py:37`, 쓰지 않는 변수), `CLAUDE.md` 명령 절, ADR §9.1·§9.3. WSL의 새 venv에서 CI 단계를 재현했다: 린트 통과, 342 passed / skip 0(테스트 단계 약 2분 반), 훅 테스트 25 passed. `ANF_E2E_API_URL` 없이 e2e를 돌리면 skip 검사가 종료 코드 1로 실패하는 것도 확인했다. 제품 코드 내용 해시는 `f2b70558…` 그대로다. 로컬 재현은 PASS가 아니다(판정은 Actions 실행으로 한다).
