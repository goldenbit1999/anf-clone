# 기능 현황

`anf-feature-cycle` 하네스가 단계마다 갱신한다. 상세 진행 기록은 `_workspace/{feature}/00_progress.md`에 있다. 완료 정의는 [PRD §8](PRD.md#8-기능-완료-정의)이다.

상태 값: `in_progress`(사이클 진행 중), `partial`(사이클은 끝났지만 UNVERIFIED 항목이 남음), `blocked`(3회 재검증 뒤에도 FAIL이거나 사용자가 보류), `done`(PRD §8의 완료 정의를 모두 충족).

| 기능 | FR | 상태 | 마지막 완료 단계 | 검증 대상 코드 | 검증 보고서 | 갱신일 | 개념 문서 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| netapp-account | FR-01, FR-02 | done | 6 | 미커밋 (기준 `b96dbaf`, 파일 해시는 00_progress.md) | `_workspace/netapp-account/04_verifier_report.md` (1회차, 13/13 PASS) | 2026-11-07 | [netapp-account.md](concepts/netapp-account.md) |

이월된 수락 기준: 자식 용량 풀이 남은 계정 DELETE의 `409 CannotDeleteResource` 실환경 검증은 용량 풀(`capacity-pool`) 사이클에서 한다 (계정 설계 결정 8, PRD FR-02).
