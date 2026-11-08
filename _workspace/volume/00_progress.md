# volume 진행 기록

- 상태: in_progress
- FR: FR-04 (볼륨, NFS). 용량 풀 사이클에서 옮겨 온 기준: CV-1~CV-3 (`_workspace/capacity-pool/02_main_design.md` §8), 볼륨 생성이 풀 크기를 넘으면 거절 (FR-03)
- 마지막 완료 단계: 4 (2회차 AC-01~AC-15 PASS. GitHub Actions 실행은 PR에서 확인)
- 재개할 단계: 5 (개념 문서). 그 전에 사용자 지시대로 commit·push·PR·merge
- 검증 대상 코드: 제품 코드 내용 해시 `8bb57d912a0124580af7a8c3a58340667e54bb0dee349acdf4d5b4e017e5d77e` (미커밋, AC-03 수정 뒤. 1회차는 `443df94c…`). 변경 파일:
  - 제품 코드(해시 범위): `pyproject.toml`(`dataplane` 마커), `backend/anf_api/{arm_app,arm_rules,capacity_pools,state_store}.py`(수정), `backend/anf_api/{volumes,storage_client}.py`(새), `backend/storage_agent/`(새: `agent_app.py`, `flexvol.py`, `nfs_instance.py`, `jobs.py`, `runner.py`, `nfs_server/{Dockerfile,entrypoint.sh,nfs.conf}`)
  - 해시 범위 밖: `scripts/setup-wsl-dataplane.sh`(새), `.github/workflows/ci.yml`(`-m "not dataplane"`), `.gitattributes`(새), 테스트(`backend/tests/unit/test_{volumes,storage_client,agent_app,flexvol,nfs_instance,jobs,runner,arm_rules,state_store}.py`, `backend/tests/contract/test_volumes_api.py`, `backend/tests/integration/test_flexvol_linux.py`)
- verifier 에이전트 ID: a601bde8eb311ae06 (1회차, 2026-11-07 시작. 2회차도 같은 ID로 이어 감)
- 미해결: 없음 (1회차 AC-03 FAIL은 2회차 PASS). 아래는 1회차 기록이다. 1회차 AC-03 FAIL(불안정). NFSv4.1 인스턴스의 약 7~8%가 NFSv4 클라이언트 추적(nfsdcld) 초기화에 실패해 90초 유예 기간으로 시작하고, 그동안 첫 쓰기가 90~102초 막힌다(dmesg "Unable to initialize client recovery tracking! (-2)", 인스턴스 로그 `grace_ended=N`). 원인 추정: 진입점이 `rpc.nfsd` 시작 때 nfsdcld 준비를 확인하지 않고 `grace_ended=N`이어도 서비스한다. agent는 `docker run -d`가 돌아오면 인스턴스 준비를 기다리지 않고 job을 끝낸다. 수정함(설계 "구현 중 변경"의 S2 미확인 해결 1): 진입점이 유예 종료를 확인하고 knfsd를 다시 시작하며, agent는 준비 표시를 기다린다. 사용자는 검증이 끝나면 commit·push·PR·merge하라고 했다(2회차 PASS 뒤 진행).

## 구현 중 변경

`02_main_design.md`의 "구현 중 변경" 절로 옮겼다 (S2 미확인 해결, 동작이 바뀐 것, 구현 세부).

## 선행 확인 (0단계)

- 상위 리소스: 계정(`netapp-account`)과 용량 풀(`capacity-pool`)이 `done` (`docs/feature-status.md`).
- 결정: D-06(storage agent, ONTAP REST 부분집합), D-07(SQLite), D-09(프로세스 안 워커), D-10(Ubuntu 안 Docker Engine), D-13(인증 없음) 확정. 공통 LRO 계층(`backend/anf_api/lro.py`, `state_store.py`)을 재사용한다.
- 스파이크:
  - S0 통과 (`_workspace/spikes/S0.md`): nfsd·btrfs·dm-thin 모듈, knfsd v3/v4.1, 루프 파일 위 btrfs, 컨테이너 마운트(`secure` export), 클라이언트 IP 구분, LOCALIO 꺼짐.
  - **S1 없음** → 설계 확정 전에 메인이 실행한다 (`_workspace/spikes/S1.md`). ADR §7.2의 후보 A·B·C 비교.
- 2단계에서 정할 것:
  - D-11 (볼륨·스냅샷 저장 방식, S1 결과로)
  - 스토리지 루트 확정 (ADR §5, 제안값 `/var/lib/anf-clone`)
  - storage agent 첫 구현: 프로세스·포트·권한, ONTAP REST 부분집합(`/api/storage/volumes`, `/api/cluster/jobs/{uuid}`), job 모델
  - ADR §6.4 "볼륨 설계에서 정함": 안정적인 작업 식별자(멱등 키), 단계별 복구(파일시스템 생성 → quota → export), 예약 정리
  - ADR §6.1 작업별 응답 표의 볼륨 행, `subnetId` 같은 클론에서 의미 없는 필수 속성 처리
  - ADR §7.4 export 적용 방식(`/etc/exports.d/`와 `exportfs`), NFSv4 pseudo-root, 마운트 대상 IP(Docker 네트워크 쪽 호스트 IP)
  - 볼륨 대상 결함 주입 키

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | 생성 계약·상태, GET 값, mountTargets | PASS | `04_verifier_report_r2.md` | `8bb57d91…` |
| AC-02 | NFSv3 두 클라이언트 읽기·쓰기, 770, v4.1 거절 | PASS | r2 | `8bb57d91…` |
| AC-03 | NFSv4.1 읽기·쓰기, v3·v4.0 거절 | PASS (1회차 FAIL: 90초 유예 기간, 수정 뒤 재시작 5/64회 모두 회복, 첫 쓰기 0.22 s) | r2 | `8bb57d91…` |
| AC-04 | 할당량 초과 쓰기 ENOSPC | PASS | r2 | `8bb57d91…` |
| AC-05 | 용량·부모 규칙, CV-1~CV-3 | PASS | r2 | `8bb57d91…` |
| AC-06 | 거절 22가지, 50 GiB 하한 | PASS | r2 | `8bb57d91…` |
| AC-07 | 경로 유일·불변 속성 | PASS | r2 | `8bb57d91…` |
| AC-08 | PATCH 202, I/O 중단 없음 | PASS | r2 | `8bb57d91…` |
| AC-09 | DELETE 흐름, 데이터 플레인 제거, IP 재사용 | PASS | r2 | `8bb57d91…` |
| AC-10 | 진행 중 409 RequestConflict | PASS | r2 | `8bb57d91…` |
| AC-11 | 실패 주입·agent 정지 60 s 뒤 Failed, PUT 회복 | PASS | r2 | `8bb57d91…` |
| AC-12 | anf-api·agent 강제 종료, WSL 재시작 흉내 복구 | PASS | r2 | `8bb57d91…` |
| AC-13 | agent API 계약 | PASS | r2 | `8bb57d91…` |
| AC-14 | 계정·풀 e2e 회귀 | PASS (1회차 63 passed. anf-api 코드는 2회차에 바뀌지 않았고, 2회차 CI 재현에서도 63개 통과) | `04_verifier_report.md`, r2 | `443df94c…`, `8bb57d91…` |
| AC-15 | 볼륨별 서버(IP·연결 분리) | PASS | r2 | `8bb57d91…` |
| (추가) | 통합 테스트, CI 로컬 재현(579 passed, 25 deselected, skip 0) | PASS | r2 | `8bb57d91…` |
| (추가) | GitHub Actions 실행 | UNVERIFIED → PR에서 확인 | — | — |

## 이력

- 2026-11-07 단계 0 완료 — 계정·용량 풀 `done`, `_workspace/volume/` 없음 → 1단계부터. S1 결과 파일이 없어 설계 전에 실행한다. 볼륨 녹화(.NET `VolumeTests__*` 등)는 계정 조사 때 `_workspace/netapp-account/sources/recordings/`에 이미 있다.
- 2026-11-07 단계 1 시작 — anf-researcher에 조사를 맡겼다. 메인은 S1을 병행했다.
- 2026-11-07 단계 1 완료 — 조사 상태 `한도 도달` (`01_researcher_brief.md`). 필수 질문 다섯 가지는 답했다. 미확인은 ONTAP `POST /api/storage/volumes` 원본 응답, data LIF·NFSv4 pseudo-fs 원문, ANF 볼륨이 가득 찼을 때의 errno, 클라이언트 `df` 표시다. 설계를 막지 않는다고 판단했다: storage agent의 job 모델은 클론이 정하고 차이를 표시한다(R-04). errno와 `df`는 S1이 클론의 동작을 재고, 수락 기준에서 errno를 ANF 값으로 고정하지 않는다. 오류 HTTP 코드, `creationToken` 유일성 범위, `subnetId` 처리, PATCH 범위는 2단계 선택지로 넘긴다.
- 2026-11-07 S1 완료 — `_workspace/spikes/S1.md`. 판정: C(씬 풀 + thin LV + ext4) 통과, A 실패(NFSv3로 읽기 전용 btrfs 스냅샷이 수정됨, 스냅샷 inode가 볼륨과 겹침), B 조건부. 측정 중 실수 한 건을 정정했다: `dd` 출력을 `tail`로 잘라 ENOSPC 오류 줄을 놓쳤고, 종료 코드로 다시 재니 모든 경우에 클라이언트가 오류를 받았다. 같은 시간에 다른 세션이 S2를 같은 WSL에서 돌렸다. S1은 1차 시험에서 `exportfs -ra`를 썼고, 그 세션의 요청을 받은 뒤에는 `exportfs -o`/`-u`만 썼다(그 세션에 알렸다). 마운트 경로 사전 확인: 심볼릭 링크로는 v3만 된다. nfs-utils 2.6.4의 `[exports] rootdir`가 후보지만, nfs-server 재시작이 필요해 S2가 끝난 뒤 시험한다.
- 2026-11-07 단계 2 시작 — 설계안과 선택지를 사용자에게 제시했다.
- 2026-11-07 단계 2 완료 — 사용자가 네 선택지를 모두 추천안으로 확정했다: D-11 = C(결정 1), 마운트 경로는 nfs `rootdir`(결정 2), 최소 크기는 검증용 환경 변수(결정 3), 데이터 효과가 없는 속성 변경은 400(결정 4, 각 기능 사이클에서 연다). 메인이 기본으로 제시한 결정 5~16에 이견이 없었고, 수락 기준 AC-01~AC-14를 확인했다. nfs-server 재시작은 "지금"으로 골랐다(S2 세션도 동의). `rootdir`를 바로 시험해 v3·v4.1 모두 `/<path>` 마운트를 확인했다(`/etc/nfs.conf.d/anf-clone.conf`는 남겼다). ADR(D-11, §2.2, §2.3, §5, §6.1, §6.2, §6.4, §7.2, §7.4, §9.1, §9.3, R-02, §13), PRD(G2 예, §11), CLAUDE.md(Decided, Not decided, Kernel)를 고쳤다. S2 중간 결과(호스트 knfsd 공유 때 v4.1 연결 합침)를 설계의 위험으로 적었다.
- 2026-11-07 단계 3 시작 — 구현. 공통 코드(`arm_rules.py`, `arm_app.py`)가 바뀌므로 계정·풀을 `in_progress`로 되돌리고 AC-14로 회귀 검증한다 (무효화 규칙).
- 2026-11-07 단계 3 진행 — `arm_rules.py`(볼륨 이름·ID), `storage_agent/runner.py`, `jobs.py`, `flexvol.py`와 단위 테스트(GREEN), `dataplane` 마커, CI `-m "not dataplane"`. 통합 테스트 `tests/integration/test_flexvol_linux.py`를 WSL root로 돌려 3개 PASS(aggregate, 생성·삭제, 재시작 흉내 후 복구와 `mp`). 정리 단계의 umount busy로 재시도를 넣었고, 다시 돌려 3개 PASS(정리 25.0 s), 남은 export·LV 없음. 위 "구현 중 변경" 참고.
- 2026-11-07 단계 3 진행 — `anf_api/volumes.py`(본문 규칙, 응답 본문, PUT·PATCH·DELETE·GET·목록, 부모·경로·용량·불변·진행 중 409)와 `test_volumes.py` 96개 GREEN. `Tx.all_of_type`(클론 전체 경로 유일성), `capacity_pools.MIBPS_PER_TIB` 공개. 전체(데이터 플레인 제외) 424 passed, ruff 통과. 미룬 속성은 "클론이 지금 하는 값과 같으면 받고, 다르면 400"으로 통일했다(결정 4의 "같은 값 허용"을 생성에도 적용). 그래서 AC-06의 미룬 속성 시험은 기본값과 다른 값(예: `snapshotDirectoryVisible: false`, 사용자 지정 export 규칙)으로 보내야 한다.
- 2026-11-07 단계 3 일부 중단 — S2 세션이 결론(D-12 제안 T1n)을 알렸고, 사용자 지시로 그 세션이 볼륨 설계의 export·IP 부분을 고치는 중이다. 그 부분의 구현과 해당 절 편집을 멈췄다. export와 상관없는 anf-api 볼륨 본문·용량·부모 규칙을 이어서 한다.
- 2026-11-07 단계 3 재개 — S2 세션이 설계 반영(결정 17·18, ADR D-12, CLAUDE.md)을 끝냈다고 알렸다. 인스턴스 시제품(scratchpad `proto.sh`)으로 §3 미확인 네 가지를 확인했다(v4.1 멈춤 = grace, `nfsdcld`로 해결 등). `nfs_instance.py`(15 GREEN)와 `nfs_server/`(이미지 `anf-nfs-server`)를 만들었다.
- 2026-11-07 단계 3 진행 — `flexvol.py`를 T1n으로 바꿨다(호스트 export·unlock 제거, `anf_ip`·`anf_proto` 태그, 인스턴스 보장·제거, 복구 순서). 단위 25 GREEN. `scripts/setup-wsl-dataplane.sh`를 실행했다(이미지 두 개, anf-vnet 유지, 호스트 `anf-clone.conf`·`anf-clone.exports` 제거). 통합 테스트를 클라이언트 컨테이너 방식으로 바꿔 WSL root에서 4 PASS(32.7 s), 남은 컨테이너·LV·마운트 없음.
- 2026-11-07 단계 3 진행 — `agent_app.py`(40 GREEN, job 키를 작업 종류 + UUID로 다듬음), `storage_client.py`(11 GREEN, 실제 HTTP 서버로 urllib 전송 확인), `volumes.make_handlers`(103 GREEN), `arm_app.py` 볼륨 라우트·`ANF_STORAGE_AGENT_URL`·`ANF_MIN_VOLUME_SIZE_GIB`(계약 `test_volumes_api.py` 12 PASS, `test_arm_app.py` 33 GREEN). 전체 513 passed, 67 skipped(WSL·live 전용), ruff 통과.
- 2026-11-07 단계 3 완료 — WSL에서 root agent(8090)와 anf-api(8080, `ANF_MIN_VOLUME_SIZE_GIB=1`)를 띄워 스모크(검증 기록 아님): NFSv3·NFSv4.1 1 GiB 볼륨이 1.5~2.5 s에 `Succeeded`, IP .129·.130. 클라이언트 컨테이너가 각자의 버전으로 쓰고 읽었고(루트 권한 770, `df` 974M), 다른 버전은 거절됐다. DELETE는 2.5 s에 `Succeeded` → GET 404. agent 로그에 anf-api 상관 ID가 남았다. 정리 뒤 남은 것 없음. `02_main_design.md` "구현 중 변경"과 CLAUDE.md 명령·아키텍처 줄을 썼다. 제품 코드 해시 `443df94c…`.
- 2026-11-07 단계 4 시작 — real-env-verifier 1회차(AC-01~AC-15, AC-14 회귀, CI 명령 로컬 재현). GitHub Actions 실행은 push가 필요해 사용자 결정을 기다린다.
- 2026-11-07 단계 4 FAIL (1회차) — `04_verifier_report.md`: PASS 14, FAIL 1(AC-03 불안정), CI 로컬 재현 PASS(576 passed, 25 deselected, skip 0), GitHub Actions UNVERIFIED(push 대기). 제품 코드 해시 그대로 `443df94c…`. verifier가 `backend/tests/e2e/test_volume_live.py`(약 1310줄)를 만들었다. 사용자 요청으로 이 파일을 공용 도우미와 2~3개 파일로 나누는 일을 2회차에 함께 맡긴다. 재개: 3단계 수정.
- 2026-11-07 단계 3 수정 (AC-03) — `nfs_instance.py` 준비 대기(`READY_FILE`, `InstanceError`, 단위 18 GREEN), 진입점의 유예 종료 확인·knfsd 재시작·준비 표시, `flexvol.py`가 sleep을 넘김. 이미지를 다시 빌드했다. 인스턴스 45번 시작에서 3번 재시도, 모두 `Y`(생성 평균 1.36 s, 최대 4.26 s). 통합 4 PASS(42.7 s), 전체 516 passed, ruff 통과. 제품 코드 해시 `8bb57d91…`. 수정이 인스턴스 시작 경로 전체에 걸려 2회차는 볼륨 e2e 전체를 다시 맡긴다.
- 2026-11-07 단계 4 완료 (2회차) — `04_verifier_report_r2.md`: AC-01~AC-15 PASS 15. 볼륨 e2e 21 passed(530.55 s), 반복 시험 20회. knfsd 시작 64회 중 5회 재시작, 모두 두 번째 시도에 회복. 90 s 대기 0회. 통합 4 PASS(32.51 s). CI 로컬 재현: 579 passed, 25 deselected, skip 0, 훅 25 passed. 제품 코드 해시 `8bb57d91…` 그대로. e2e를 `dataplane_live.py`(도우미 531줄)와 `test_volume_{contract,data,recovery}_live.py`(463·272·202줄)로 나눴다(본문은 그대로 옮김, 첫 쓰기 한도는 10 s로 좁힘). 사용자 지시로 commit·push·PR·merge를 진행한다.
