# snapshot-revert 진행 기록

- 상태: in_progress
- FR: FR-06 (스냅샷으로 되돌리기)
- 마지막 완료 단계: 2
- 재개할 단계: 3 (구현)
- 검증 대상 코드: 아직 없음
- verifier 에이전트 ID:
- 미해결: 없음

## 선행 확인 (0단계)

- 상위 리소스: 계정·용량 풀·볼륨·스냅샷 모두 `done` (`docs/feature-status.md`, 스냅샷 merge `a74d1d7`, 문서 정정 `0f2bd5a`).
- 결정: D-06, D-07, D-09, D-10, D-11(되돌리기 후보 = thin 스냅샷 merge), D-12(볼륨마다 knfsd 인스턴스), D-13 모두 확정. 공통 LRO 계층과 storage agent(`flexvol.py`, `nfs_instance.py`, `jobs.py`)를 재사용한다.
- 스파이크: S1 #8 "되돌리기"는 **완료하지 못했다.** 마운트한 클라이언트가 있는 동안 `umount`가 `target is busy`였고 `lvconvert --merge`는 "Delaying merge since snapshot is open"으로 미뤄졌다. S1은 "FR-06 설계에서 언마운트 절차와 클라이언트 영향(같은 `fsid`면 핸들이 유지되는지)을 다시 잰다"로 남겼다. S1 이후 export가 볼륨 인스턴스로 옮겨졌고(D-12), 스냅샷마다 `.snapshot/<이름>`에 마운트·export가 생겼다(S4). 그래서 설계 확정 전에 인스턴스 구조에서 되돌리기를 시험한다 → 스파이크 S5 (`_workspace/spikes/S5.md`). FR-07(새 볼륨 복원)도 같은 thin 스냅샷 조작을 쓰므로 기능 밖 스파이크로 둔다.
- 위험: ADR R-03 (LV 교체로 되돌리면 이미 마운트한 클라이언트가 stale file handle을 볼 수 있다). 설계에서 ONTAP SnapRestore와 대조하고 클론 동작을 문서화한다. PRD FR-06 수락 기준도 "되돌리기 전에 마운트한 클라이언트가 어떻게 보이는지(다시 마운트가 필요한지)를 기록한다"이다.
- 이미 아는 사실 (스냅샷 브리프): revert는 볼륨 POST `revert`, 본문 `{"snapshotId": <스냅샷 ARM ID>}`, `202`, 볼륨이 `Reverting` → `Succeeded`, 약 3초 [녹화 R3]. 고른 스냅샷보다 뒤에 찍은 스냅샷이 사라진다 [문서 13]. revert 중 스냅샷 생성은 ONTAP `1638532`로 거절된다.
- 2단계에서 정할 것 (후보):
  - ARM `revert` POST 계약 (응답, 추적 헤더, 볼륨 상태 `Reverting`, 본문 검사, 거절 코드)
  - 데이터 플레인 방식 (S5): `lvconvert --merge`(스냅샷을 소비) 대 고른 스냅샷의 쓰기 가능 사본으로 볼륨 LV 교체(스냅샷 유지)
  - 마운트한 클라이언트에 주는 영향: 기존 파일 핸들 유지 여부, 스냅샷 뒤에 만든 파일의 ESTALE, 열린 파일, 클라이언트 캐시
  - 더 새 스냅샷 삭제 (ANF·ONTAP 동작), 고른 스냅샷은 남는지
  - 진행 중 충돌(볼륨·스냅샷 작업), 재시작 복구, 결함 주입 키

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |

## 이력

- 2026-11-08 19:02 단계 0 완료 — 스냅샷까지 `done`, `_workspace/snapshot-revert/` 없음 → 1단계부터. 브랜치 `feature/snapshot-revert`. S1 #8이 끝나지 않았고 구조가 바뀌어(D-12, S4) 스파이크 S5를 조사와 병행한다.
- 2026-11-08 19:03 단계 1 시작 — anf-researcher에 조사를 맡겼다. 메인은 S5를 병행했다.
- 2026-11-08 19:20 단계 1 한도 도달 → 이어 쓰기 — 첫 실행은 원문만 모으고 30턴 한도로 브리프 없이 멈췄다. 같은 에이전트에 새 원문 없이 브리프를 쓰라고 이어 맡겼다.
- 2026-11-08 19:22 단계 1 완료 — `01_researcher_brief.md` 조사 상태 "한도 도달": 질문 1~4는 답했고 질문 5(revert 중 I/O)만 남았다. 남은 미확인(revert 전용 오류 코드, revert 중 볼륨 `provisioningState`, 크기 규칙)은 설계를 막지 않는다고 판단했다: 클론 규칙으로 정하고 차이를 기록한다. 클라이언트 영향(다시 마운트, stale handle)은 ANF·ONTAP 원문에 없어서 S5 측정이 유일한 근거다. 바로잡음: 스냅샷 브리프의 "볼륨이 `Reverting`"은 작업 상태였다.
- 2026-11-08 19:38 S5 완료 — `_workspace/spikes/S5.md`. 판정 조건부 통과: 인스턴스를 둔 채 netns 입력 DROP → 언마운트 → `lvconvert --merge`(0.4~0.6 s) → 고른 스냅샷 다시 만들기 → 다시 올리기에서 v3·v4.1 모두 다시 마운트 없이 오류 0. export 제거(v3 EACCES)와 인스턴스 재시작(v4.1 23 s, 위임 되찾기로 틀린 캐시)은 버린다. knfsd 기본 위임에서 v4.1 열린 fd가 16~32 s 옛 캐시를 읽었고, `fs.leases-enable=0`(위임 끔, ONTAP 기본값)에서는 바로 맞았다. dm-thin id가 남은 스냅샷의 생성 순서다(L3). ADR §10 스파이크 표에 S5를 넣었다. 스파이크 자원은 지웠고 `fs.leases-enable`은 1로 되돌렸다.
- 2026-11-08 19:39 단계 2 시작 — 1단계 요약, S5 결과, 기본 설계안과 선택지를 사용자에게 제시했다.
- 2026-11-08 19:48 단계 2 완료 — 사용자가 네 선택지 모두 추천안을 골랐다: (1) NFSv4 위임 끄기(`fs.leases-enable = 0`, agent가 시작 때 확인), (2) 되돌리는 동안 볼륨 `Reverting`, 실패하면 `Failed` → 볼륨 PUT으로 회복, (3) 네트워크 차단 + merge + 고른 스냅샷 다시 만들기, (4) 작업 ID를 agent 멱등 키로(`restore_to.request_uuid`, LVM 태그에 진행·끝 표시). 나머지 기본안(녹화 계약, 거절 규칙, dm-thin id로 더 새 스냅샷 고르기, `operations.params`)에는 이견이 없었다. `02_main_design.md`를 쓰고 ADR §2.3·§6.1·§7.2·§7.4·R-03·D-11·D-12와 CLAUDE.md Decided를 고쳤다. (앞 이력의 시각은 파일 시각으로 바로잡았다.)
