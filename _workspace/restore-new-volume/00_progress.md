# restore-new-volume 진행 기록

- 상태: in_progress
- FR: FR-07 (스냅샷에서 새 볼륨으로 복원)
- 마지막 완료 단계: 0
- 재개할 단계: 1 (조사)와 스파이크 S6 병행
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

## 이력
- 2026-11-08 단계 0 완료 — 브랜치 `feature/restore-new-volume`. 조사와 스파이크 S6를 함께 시작
