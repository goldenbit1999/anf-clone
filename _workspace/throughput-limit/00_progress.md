# throughput-limit 진행 기록

- 상태: in_progress
- FR: FR-08 (처리량 제한)
- 마지막 완료 단계: 1
- 재개할 단계: 2 (스파이크 S7 결과를 기다림)
- 검증 대상 코드: (구현 뒤)
- implementer 에이전트 ID: acadc68bbbccab96e (스파이크 S7부터)
- researcher 에이전트 ID: ae21e308facd1f3ae
- verifier 에이전트 ID:
- 미해결: 없음

## 선행 확인 (0단계)

- 상위 리소스: 계정·용량 풀·볼륨·스냅샷·되돌리기·새 볼륨 복원 모두 `done` (`docs/feature-status.md`, FR-07 merge `8e42911`).
- 결정: D-12 = T1n (볼륨마다 knfsd 인스턴스와 IP, 인스턴스 호스트 쪽 veth에 clsact → 양방향을 IFB 하나로 → HTB 클래스 하나, 읽기·쓰기 합산). 인스턴스와 IP는 볼륨 사이클에서 만들었고 tc는 이 FR에서 더한다 (ADR §7.3, CLAUDE.md "Decided").
- 스파이크: S2(`_workspace/spikes/S2.md`)는 2026-11-07, 볼륨 구현 전의 실험용 인스턴스(`s2-srv-*`, 네트워크 `s2-net`)에서 쟀다: v3·v4.1 모두 설정값의 약 95%(헤더 바이트 포함), 읽기+쓰기 합산, `tc class change`로 실시간 변경, 같은 클라이언트의 다른 볼륨은 영향 없음. 지금 agent의 인스턴스(`anf-nfs-<uuid>`, `anf-vnet`, 재시작·되돌리기 창·복구)에서 tc를 건 적은 없다. 또 검증은 `ANF_MIN_VOLUME_SIZE_GIB=1`의 작은 볼륨을 쓰는데, Auto QoS 공식이면 1 GiB Premium이 0.0625 MiB/s다. 이런 낮은 한도에서 NFS 동작(마운트, v4.1 lease 갱신)을 잰 적이 없다. 그래서 설계 확정 전에 스파이크 S7로 확인한다 (사이클 0단계 5번).
- 위험: ADR R-08 (클라이언트와 서버가 같은 커널, LOCALIO 꺼짐 확인됨), R-01 (해소됨).
- 이미 아는 사실: 풀은 `qosType` Auto/Manual을 받고 Auto → Manual은 한 방향이다 (`capacity_pools.py`). 볼륨은 Manual QoS 풀을 거절하고 `throughputMibps`를 미룬 기능으로 거절한다 (`volumes.py` `_NOT_YET`). `actualThroughputMibps` = 할당량(TiB) × 서비스 수준 단가를 응답에 이미 보인다.
- 2단계에서 정할 것 (후보):
  - Manual QoS 범위: 볼륨 `throughputMibps`(생성·PATCH), 풀의 처리량 예산 검사, Auto → Manual 전환 때 기존 볼륨 값
  - Auto QoS 한도를 바꾸는 방법: 할당량 변경은 FR-16이다. FR-08 수락 기준 "제한을 바꾸면 잰 값도 바뀐다"를 무엇으로 보일지
  - 작은 검증 볼륨의 낮은 한도를 어떻게 다룰지
  - tc 적용 시점(인스턴스 시작, 재시작, 복구)과 헤더 바이트 보정, 허용 오차
  - agent API: ONTAP QoS policy(`/api/storage/qos/policies`, 볼륨 `qos.policy`)와의 대응

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |

## 이력
- 2026-11-09 단계 0 완료 — 브랜치 `feature/throughput-limit`. 조사와 스파이크 S7을 함께 시작
- 2026-11-09 단계 1 완료 — 브리프 `01_researcher_brief.md`(조사 상태 "한도 도달": 30턴 상한, 받은 원문으로 SendMessage 이어 쓰기). 미확인(Manual 풀 볼륨의 `throughputMibps` 생략 시 기본값, Auto 풀 볼륨에 보낸 값, 예산 초과 오류 코드, Auto→Manual 전환 뒤 기존 볼륨 값, Manual 풀 축소)은 설계를 막지 않고 클론 규칙으로 정한다. ONTAP 대응(fixed QoS policy, 볼륨 `qos.policy`)은 [추론]으로 채워졌다
