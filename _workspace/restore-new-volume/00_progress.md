# restore-new-volume 진행 기록

- 상태: done
- FR: FR-07 (스냅샷에서 새 볼륨으로 복원)
- 마지막 완료 단계: 6
- 재개할 단계: 없음 (사이클 완료, 출하만 남음)
- 검증 대상 코드: 제품 코드 내용 해시 `1e950522c13e991ad33d06e2ad2fbd182685426ef7f774fc8bde4ccbf339a9f7`, 커밋 `a8ddc0a`
- implementer 에이전트 ID: a41cc624ee346fccd (스파이크 S6부터)
- researcher 에이전트 ID: a5124c3e4df55979d
- verifier 에이전트 ID: ab657ccad3b0c38a8 (1회차)
- 미해결: 없음

## 선행 확인 (0단계)

- 상위 리소스: 계정·용량 풀·볼륨·스냅샷·되돌리기 모두 `done` (`docs/feature-status.md`, 되돌리기 merge `a49535d`).
- 결정: D-06, D-07, D-09, D-10, D-11, D-12, D-13 모두 확정. 공통 LRO 계층, storage agent(`flexvol.py`, `nfs_instance.py`, `jobs.py`), 되돌리기의 "스냅샷의 쓰기 가능 스냅샷"(`lvcreate -s -kn -p rw`, `flexvol.py` `_resume_restore`)을 재사용할 수 있다.
- 스파이크: S1 #9(쓰기 가능 thin 스냅샷으로 새 볼륨 0.127 s, 내용 독립, **ext4 UUID가 원본과 같음**)는 볼륨 인스턴스 구조(D-12)와 `.snapshot`(S4) 전의 측정이다. 지금 구조에서 실측한 적이 없으므로 설계 확정 전에 스파이크 S6로 확인한다 (사이클 0단계 5번).
- 위험: ADR R-09 (스냅샷·클론 공간은 씬 풀에서 나간다).
- 이미 아는 사실 (스냅샷 브리프 88행): 스냅샷에서 만든 새 볼륨에는 같은 이름의 base 스냅샷이 생기고(`deleteBaseSnapshot`으로 뺄 수 있다), 새 볼륨에 `originatingResourceId`(원본 스냅샷 ID)가 채워진다 [녹화 R4, 문서 14, 스펙 2].
- 2단계에서 정할 것 (후보):
  - ARM 계약: 볼륨 PUT의 `snapshotId` 형식과 검사, 다른 풀·프로토콜·크기 허용 범위, 응답 코드, `originatingResourceId`, base 스냅샷, `deleteBaseSnapshot`
  - 데이터 플레인 방식 (S6): 스냅샷 LV의 쓰기 가능 스냅샷 + 크기 확장, ext4 UUID 처리, `.snapshot`의 남은 마운트 지점 정리
  - 독립성: 원본 스냅샷·볼륨 삭제, 원본 되돌리기 뒤에도 새 볼륨이 남는가
  - agent API: ONTAP FlexClone(`clone.parent_snapshot`)과의 대응

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | 계약·상태 (성공), base 스냅샷 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-02 | 내용 NFSv3, `.snapshot` 정리 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-03 | 독립성 (FR-07) | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-04 | NFSv4.1, 다른 프로토콜·다른 풀 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-05 | 크기 (원본보다 큼) | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-06 | 생성 뒤 원본 되돌리기·삭제 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-07 | 거절 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-08 | 진행 중 충돌, 원본 보호 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-09 | 실패·회복·재시작 안전 | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-10 | agent API | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |
| AC-11 | 회귀 (e2e 14파일 131, 통합 25, 단위·계약 817, skip 0) | PASS | `04_verifier_report.md` (1회차) | `1e950522…` (`a8ddc0a`) |

## 이력
- 2026-11-08 단계 0 완료 — 브랜치 `feature/restore-new-volume`. 조사와 스파이크 S6를 함께 시작
- 2026-11-08 단계 1 완료 — 브리프 `01_researcher_brief.md` (조사 상태 완료). researcher가 30턴 상한에 닿았지만 브리프는 다 썼다. 미확인(다른 풀·프로토콜 허용, 크기 하한, 거절 오류 코드, `deleteBaseSnapshot` 대상)은 설계를 막지 않고 클론 규칙으로 정한다. ONTAP 대응(FlexClone + split)은 [추론]으로 채워졌다
- 2026-11-08 스파이크 S6 완료 — 조건부 통과 (`_workspace/spikes/S6.md`)
- 2026-11-08 단계 2 완료 — `02_main_design.md`. 사용자에게 묻는 결정이 없어 결정 1~16 자동 채택(`roadmap.md` 표)
- 2026-11-09 단계 3 완료 — implementer 커밋 `fa75aff`·`b7a26b2`·`def0999`·`bbb482a`·`a8ddc0a`. Windows `python -m pytest` 817 passed / 143 skipped(root·e2e 조건) / 0 failed, ruff 통과, WSL 통합 25 passed(새 8개). WSL 전체 + e2e 회귀는 Windows 호스트 메모리 부족으로 background shell이 정리돼 결과 없음(테스트 실패 아님) → AC-11은 검증에서 돌린다. 남은 데이터 플레인 자원은 implementer가 정리함. 구현 중 변경 10개(설계 §9). 그중 1번: 헤더 두 개(`Azure-AsyncOperation` + `Location`)는 스냅샷에서 만드는 생성 201에만 — 설계 §4.1·AC-01(녹화 R4)을 따르고 일반 생성(V1, 헤더 하나)은 그대로 둔다. 메인이 받아들였다
- 2026-11-09 단계 4 시작 — verifier 1회차. AC-11 e2e는 메모리 때문에 파일별로 돌리라고 지시
- 2026-11-09 단계 4 완료 — 1회차 11/11 PASS (FAIL 0, UNVERIFIED 0). e2e는 파일별로 돌려 메모리 문제 없음(Windows 여유 최저 약 3.9 GB). 검증 스크립트 `backend/tests/e2e/restore_live.py`, `test_restore_new_volume_{data,contract}_live.py`
- 2026-11-09 단계 5 완료 — `docs/concepts/restore-new-volume.md`, 면접 Q&A 12개. concept-explainer가 설계 결정 3의 근거 오기(`S6 N5` → `S6 F2`)를 찾아 고쳤다. "쓰지 못한 것"은 문서 부록에 있다(ANF가 FlexClone을 쓴다는 공식 문장, ANF 거절 응답, `deleteBaseSnapshot` 대상 등). 볼륨 전체의 빈칸으로 `maximumNumberOfFiles`·`isRestoring` 미구현을 문서 4절에 적었다
- 2026-11-09 단계 6 완료 — `docs/feature-status.md` done. 문서만 바뀌어 검증 대상 코드(`1e950522…`)는 그대로다
