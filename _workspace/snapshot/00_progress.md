# snapshot 진행 기록

- 상태: in_progress
- FR: FR-05 (스냅샷: 생성, 조회, 목록, 삭제, NFS 클라이언트의 `.snapshot`)
- 마지막 완료 단계: 4
- 재개할 단계: 5 (개념 문서)
- 검증 대상 코드: 제품 코드 내용 해시 `f5607a082c70d4dad6899f7722cfdcc486eb67bd249210c3c3cd5e9ecf2738f1`, 커밋 `27757aa` (브랜치 `feature/snapshot`, 작업 트리와 같은 값)
- verifier 에이전트 ID: a5f7546514170897e (1회차, 2026-11-08)
- 미해결: 없음 (FR-05를 막지 않는 관찰 두 가지는 아래 "후속 후보")
- 후속 후보 (4단계 1회차 관찰, 이번 사이클 코드 때문이 아님):
  - knfsd 첫 시도 추적 실패(재시작)율이 이번 환경에서 약 30%였다(볼륨 2회차 7.8%). main과 현재 진입점의 A/B가 7/20 대 6/20이라 이번 변경과 무관하다. 모두 2회째에 성공했지만, 진입점은 5회 연속 실패하면 exit 1이고 볼륨이 `Failed`가 된다(30%면 약 0.24%). 시도 횟수나 판정 방식을 바꿀지는 별도 작업으로 본다.
  - 볼륨 e2e AC-09 앞 단계의 soft v3 `dd conv=fsync`가 4회 중 1회 `I/O error`였다. 테스트 클라이언트의 짧은 `timeo` 때문으로 추정한다[추론].

## 선행 확인 (0단계)

- 상위 리소스: 계정·용량 풀·볼륨 모두 `done` (`docs/feature-status.md`, 볼륨 merge `8a4002d`).
- 결정: D-06(storage agent), D-07(SQLite), D-09(프로세스 안 워커), D-10(Ubuntu 안 Docker Engine), D-11(thin LV + ext4, 스냅샷은 thin 스냅샷), D-12(볼륨마다 knfsd 인스턴스), D-13(인증 없음) 모두 확정. 공통 LRO 계층(`lro.py`, `state_store.py`)과 storage agent(`flexvol.py`, `nfs_instance.py`, `jobs.py`)를 재사용한다.
- 스파이크: S1 통과 (`_workspace/spikes/S1.md`): 호스트 knfsd에서 스냅샷 LV를 `.snapshot/<이름>`에 `ro,noload`로 마운트하고 자기 `fsid`로 `ro` export하면 v3·v4.1 모두 읽기 전용으로 읽혔다.
- **S1 이후 바뀐 전제.** D-12로 export가 볼륨 인스턴스(컨테이너 netns의 knfsd) 안으로 옮겨졌다. 볼륨 사이클의 구현 중 확인(`_workspace/volume/02_main_design.md` "S2 미확인 해결" 2)에서 호스트가 `ns` 아래에 나중에 한 마운트는 인스턴스에 보였지만, **v3 클라이언트가 볼륨 안의 하위 마운트로 넘어가면 "Stale file handle"이었다.** "FR-05에서 다룬다"로 남아 있다. 그래서 설계 확정 전에 인스턴스 구조에서 `.snapshot` 노출 방식을 시험한다 → 스파이크 S4 (`_workspace/spikes/S4.md`). FR-06(되돌리기)·FR-07(새 볼륨 복원)에도 걸리는 데이터 플레인 사실이라 기능 밖 스파이크로 둔다.
- 조사 원문: 스냅샷 녹화(.NET `SnapshotTests__*`, Python `test_snapshot.py*`)는 계정 조사 때 `_workspace/netapp-account/sources/recordings/`에 이미 있다.
- 2단계에서 정할 것 (후보):
  - ARM 스냅샷 리소스 계약: PUT·PATCH·DELETE·GET·목록의 작업별 응답 표 (ADR §6.1)
  - 스냅샷 식별자와 멱등 키 (볼륨 결정 9와 같은 UUID 방식인지, ONTAP처럼 볼륨 안 이름인지)
  - `.snapshot` 노출 방식 (S4 결과), `snapshotDirectoryVisible` 입력을 열지 (볼륨 설계 §2 "미룬다")
  - 스냅샷 공간이 볼륨 할당량에 잡히지 않는 차이 (S1, D-11)
  - 볼륨 삭제와 스냅샷 (자식 리소스 규칙), agent 시작 복구에 스냅샷 포함
  - 스냅샷 대상 결함 주입 키

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | 생성 계약·상태 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-02 | 데이터 NFSv3 (`.snapshot`에서 이전 내용) | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-03 | 데이터 NFSv4.1 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-04 | 불변 (root 클라이언트 쓰기 거절, `.snapshot` +i) | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-05 | 시점 (쓰는 도중 생성, `e2fsck` 깨끗) | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-06 | DELETE (사용 중인 스냅샷) | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-07 | 거절 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-08 | 재전송 PUT | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-09 | 진행 중 충돌 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-10 | 볼륨 연쇄 삭제 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-11 | 실패와 회복 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-12 | 재시작 복구 | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-13 | agent API | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-14 | 회귀 (계정·풀·볼륨 e2e, 통합) | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |
| AC-15 | v4.1 인스턴스 재시작 (결정 1) | PASS | `04_verifier_report.md` | `f5607a08…` (`27757aa`) |

## 이력

- 2026-11-08 단계 0 완료 — 계정·풀·볼륨 `done`, `_workspace/snapshot/` 없음 → 1단계부터. 브랜치 `feature/snapshot`. S1 이후 export가 볼륨 인스턴스로 옮겨져 `.snapshot` 노출을 다시 시험해야 한다(S4, 조사와 병행). 사용자 지시(2026-11-08): 커밋은 주요 서브 기능마다, push는 5단계 문서까지 끝난 뒤, PR은 그 직후.
- 2026-11-08 단계 1 시작 — anf-researcher에 조사를 맡겼다. 메인은 S4를 병행했다.
- 2026-11-08 단계 1 한도 도달 → 보완 — 첫 조사는 30턴 한도로 질문 2·3 일부와 5(ONTAP REST)가 남았다. 설계를 막는 질문(ONTAP REST 스냅샷 API, 스냅샷이 남은 볼륨 DELETE, ONTAP `.snapshot` 옵션, 같은 이름 PUT)만 같은 에이전트에 보완을 맡겼다.
- 2026-11-08 단계 1 완료 — `01_researcher_brief.md` 조사 상태 "완료 (보완 1~3), 보완 4 부분". 남은 미확인(같은 이름 PUT의 ARM 응답, 255개 초과 코드, `snapshotDirectoryVisible: false`의 정확한 의미)은 설계를 막지 않는다고 판단했다: 클론 규칙으로 정하고 차이를 기록한다.
- 2026-11-08 S4 완료 — `_workspace/spikes/S4.md`. 판정 조건부 통과: 스냅샷마다 자기 `fsid`로 export(부모 `crossmnt`만으로는 v3·v4.1 모두 Stale file handle), `.snapshot`에 `chattr +i`(없으면 root 클라이언트가 `.snapshot`을 `mv`할 수 있었다), export 표를 파일로(재시작 때 `exportfs -ua`로 스냅샷 export가 사라졌다). **볼륨 결함 발견**: NFSv4.1 클라이언트 기록이 남은 인스턴스는 재시작하지 못한다(진입점이 정상 유예 기간을 추적 실패로 오인). 시제품으로 살아 있는 클라이언트는 3 s에 회수, 죽은 클라이언트 기록은 100 s 대기를 확인했다. WSL 배포판이 wsl.exe 세션 없이 잠시 뒤 종료되는 것도 확인했다(백그라운드 `sleep`으로 유지).
- 2026-11-08 단계 2 시작 — 1단계 요약, S4 결과, 기본 설계안(결정 5~16)과 선택지 네 가지를 사용자에게 제시했다.
- 2026-11-08 단계 2 완료 — 사용자가 네 선택지를 모두 추천안으로 확정했다: 볼륨 결함을 이번 사이클에 고침(결정 1), 볼륨 DELETE가 스냅샷을 함께 지움(결정 2), 같은 이름 PUT은 `200` + `Updating` 비동기(결정 3), `snapshotDirectoryVisible`은 계속 미룸(결정 4). 기본 결정 5~16에 이견이 없었다. 검증 기준 AC-01~AC-15. ADR(§2.3 스냅샷 행, §6.1, §7.2, §7.4, S4, R-09, D-11), CLAUDE.md(Decided)를 고쳤다. **무효화**: 결정 1로 볼륨 인스턴스 코드(진입점, `nfs_instance.py`)와 `flexvol.py`가 바뀌므로, 3단계 시작 때 볼륨을 `in_progress`로 되돌리고 AC-14(볼륨 e2e 전체)로 회귀 검증한다. 공통 코드(`state_store.py`, `arm_app.py`)도 바뀌므로 계정·풀도 같은 AC-14로 회귀한다.
- 2026-11-08 단계 3 시작 — 무효화 규칙대로 `docs/feature-status.md`의 계정·풀·볼륨을 `in_progress`로 되돌렸다(AC-14 회귀 대기).
- 2026-11-08 단계 3 agent 쪽 커밋 `a2a819e` — 스냅샷 LV·`.snapshot`(+i)·스냅샷별 export 파일, 볼륨 연쇄 삭제, 시작 복구, 진입점의 lease·grace 30/45와 유예 판정(결정 1). 단위 테스트 GREEN, 통합 테스트(WSL root) 10 passed. 설계 §9 1~6.
- 2026-11-08 단계 3 완료 — anf-api 쪽 커밋 `27757aa`: `snapshots.py`(새), `arm_rules.py`, `state_store.py`(연쇄 삭제), `storage_client.py`, `volumes.py`(스냅샷 작업 중 볼륨 DELETE 409), `arm_app.py`(라우트). 계약 테스트 `tests/contract/test_snapshots_api.py` 26개를 먼저 RED로 확인했다. 전체 662 passed, 94 skipped(실환경·root 테스트), ruff 통과. 설계 §9 7. e2e(실환경) 테스트는 볼륨 사이클처럼 verifier가 `backend/tests/e2e/`에 쓴다.
- 2026-11-08 단계 4 시작 — real-env-verifier 1회차(ID a5f7546514170897e). AC-01~AC-15, AC-14는 계정·풀·볼륨 e2e 전체와 통합 테스트. 스냅샷 e2e는 verifier가 `backend/tests/e2e/test_snapshot_*_live.py`로 쓴다.
- 2026-11-08 단계 4 완료 — 1회차 PASS 15 / FAIL 0 / UNVERIFIED 0 (`04_verifier_report.md`). 해시는 시작과 끝이 같다. verifier가 스냅샷 e2e(`snapshot_live.py`, `test_snapshot_{contract,data,recovery}_live.py`)를 썼고, 이번 사이클 변경에 맞게 볼륨 e2e 두 줄을 고쳤다. 리더 판단: agent 로그 문구는 되돌리지 않고 테스트 수정을 받아들임, errno는 관찰값(EROFS/EPERM/EBUSY)으로 바로잡음(설계 §9 8~9). Windows 662 passed, 112 skipped(live·root), ruff 통과를 메인이 다시 확인했다.
