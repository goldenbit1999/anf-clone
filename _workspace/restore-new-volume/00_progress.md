# restore-new-volume 진행 기록

- 상태: in_progress
- FR: FR-07 (스냅샷에서 새 볼륨으로 복원)
- 마지막 완료 단계: 2
- 재개할 단계: 3 (구현, implementer에게 맡김)
- 검증 대상 코드: (구현 뒤)
- implementer 에이전트 ID: a41cc624ee346fccd (스파이크 S6부터)
- researcher 에이전트 ID: a5124c3e4df55979d
- verifier 에이전트 ID:
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
| AC-01 | 계약·상태 (성공), base 스냅샷 | 미검증 | | |
| AC-02 | 내용 NFSv3, `.snapshot` 정리 | 미검증 | | |
| AC-03 | 독립성 (FR-07) | 미검증 | | |
| AC-04 | NFSv4.1, 다른 프로토콜·다른 풀 | 미검증 | | |
| AC-05 | 크기 (원본보다 큼) | 미검증 | | |
| AC-06 | 생성 뒤 원본 되돌리기·삭제 | 미검증 | | |
| AC-07 | 거절 | 미검증 | | |
| AC-08 | 진행 중 충돌, 원본 보호 | 미검증 | | |
| AC-09 | 실패·회복·재시작 안전 | 미검증 | | |
| AC-10 | agent API | 미검증 | | |
| AC-11 | 회귀 | 미검증 | | |

## 이력
- 2026-11-08 단계 0 완료 — 브랜치 `feature/restore-new-volume`. 조사와 스파이크 S6를 함께 시작
- 2026-11-08 단계 1 완료 — 브리프 `01_researcher_brief.md` (조사 상태 완료). researcher가 30턴 상한에 닿았지만 브리프는 다 썼다. 미확인(다른 풀·프로토콜 허용, 크기 하한, 거절 오류 코드, `deleteBaseSnapshot` 대상)은 설계를 막지 않고 클론 규칙으로 정한다. ONTAP 대응(FlexClone + split)은 [추론]으로 채워졌다
- 2026-11-08 스파이크 S6 완료 — 조건부 통과 (`_workspace/spikes/S6.md`)
- 2026-11-08 단계 2 완료 — `02_main_design.md`. 사용자에게 묻는 결정이 없어 결정 1~16 자동 채택(`roadmap.md` 표)
