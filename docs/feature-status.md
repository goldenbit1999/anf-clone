# 기능 현황

`anf-feature-cycle` 하네스가 단계마다 갱신한다. 상세 진행 기록은 `_workspace/{feature}/00_progress.md`에 있다. 완료 정의는 [PRD §8](PRD.md#8-기능-완료-정의)이다.

상태 값: `in_progress`(사이클 진행 중), `partial`(사이클은 끝났지만 UNVERIFIED 항목이 남음), `blocked`(3회 재검증 뒤에도 FAIL이거나 사용자가 보류), `done`(PRD §8의 완료 정의를 모두 충족).

| 기능 | FR | 상태 | 마지막 완료 단계 | 검증 대상 코드 | 검증 보고서 | 갱신일 | 개념 문서 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| netapp-account | FR-01, FR-02 | done | 6 | `8a4002d` (#7, 내용 해시 `8bb57d91…`) | `_workspace/netapp-account/04_verifier_report_r2.md` (2회차, 13/13 PASS) + 볼륨 2회차 AC-14(계정 e2e 회귀 PASS) | 2026-11-07 | [netapp-account.md](concepts/netapp-account.md) |
| capacity-pool | FR-03 | done | 6 | `8a4002d` (#7, 내용 해시 `8bb57d91…`) | `_workspace/capacity-pool/04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차), 13/13 PASS + 볼륨 2회차 AC-14(풀 e2e 회귀 PASS) | 2026-11-07 | [capacity-pool.md](concepts/capacity-pool.md) |
| volume | FR-04 | in_progress (4단계 PASS, 5단계 개념 문서 대기) | 4 | `8a4002d` (#7, 내용 해시 `8bb57d91…`) | `_workspace/volume/04_verifier_report.md` (1회차, AC-03 FAIL), `04_verifier_report_r2.md` (2회차, 15/15 PASS), PR #7 Actions PASS | 2026-11-07 | — |
| ci | FR-11 | partial | 6 | `8a4002d` (#7, 워크플로에 `-m "not dataplane"` 추가) | `_workspace/ci/04_verifier_report.md` (1회차), `04_verifier_report_r2.md` (2회차), 8/8 PASS + PR #7 Actions 실행 PASS(579 passed, 25 deselected, skip 0) | 2026-11-07 | [ci.md](concepts/ci.md) |

ci가 `partial`인 이유: UNVERIFIED 항목은 없다. 이번 범위(backend 작업)는 수락 기준을 모두 통과했지만, FR-11의 frontend 작업(대시보드 FR-09 뒤)과 data-plane 작업(스파이크 S3 뒤)이 남아 있다.

이월된 수락 기준: 자식 용량 풀이 남은 계정 DELETE의 `409 CannotDeleteResource` 실환경 검증은 용량 풀(`capacity-pool`) 사이클의 AC-09로 옮겼고 1회차에서 PASS했다 (계정 설계 결정 8, PRD FR-02).
