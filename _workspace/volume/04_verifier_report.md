# volume 검증 보고서 — 1회차

- 검증일: 2026-11-07 (WSL 시각 PST 22:10~23:05, 작업 기록의 UTC는 2026-11-08 06:1x~07:05)
- 검증 대상 코드:
  - 제품 코드 내용 해시: 시작 `443df94c3c2d2d5c1f0be484aac77e33d5c6933036d4c570e4c1ce3eb48f222c`, 끝 `443df94c3c2d2d5c1f0be484aac77e33d5c6933036d4c570e4c1ce3eb48f222c` (같다)
  - 커밋 SHA: `f20ef13a561c7f34a48873cd82e34a014445b07b`
  - 미커밋 제품 코드: 수정 `backend/anf_api/arm_app.py`, `arm_rules.py`, `capacity_pools.py`, `state_store.py`, `pyproject.toml` / 새 파일 `backend/anf_api/storage_client.py`, `backend/anf_api/volumes.py`, `backend/storage_agent/` 전체
  - 이번 회차에 검증자가 만든 파일: `backend/tests/e2e/test_volume_live.py` 하나 (테스트라 해시 밖). 제품 코드는 고치지 않았다.
- 이번 회차 범위: 전체 (AC-01~AC-15, AC-14 회귀, CI 명령 로컬 재현)

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`: Ubuntu Running, WSL 2. 커널 `6.18.54.1-microsoft-standard-WSL2` |
| 커널 모듈 | `lsmod`: `nfsd`, `nfs`(nfsv3·nfsv4 사용 중), `dm_thin_pool` 로드됨 |
| Docker | `docker version`: 서버 `29.1.3 linux`. `readlink /usr/bin/docker` 빈 값(rc=1), Desktop 연동 아님 |
| 이미지·네트워크 | `anf-nfs-server:latest`(532d3bf98cbb), `anf-nfs-client:latest`(32f6d230984f). `anf-vnet` 172.30.0.0/24, ip-range 172.30.0.0/25 |
| aggregate | `lvs anf`: `aggr0` `<1023.75g` Data 0.00% Meta 10.42%. `/var/lib/anf-clone/ns`는 shared 마운트, 볼륨 없음. `/dev/loop0` = `aggr0.img` |
| Python | `/home/mkimhome1/.venvs/anf-clone/bin/python` 3.12.3 |
| 포트 | 시작 때 8080·8090 비어 있음. 호스트 `nfs-server`는 active(2049 수신, 스레드 8)지만 export 없음(`exportfs -v` 0줄). 볼륨 인스턴스는 자기 netns라 영향 없음 |
| 메모리 | 7778 MiB 중 가용 6676 MiB |
| ruff | WSL에 `uvx`·`ruff` 없음. venv 밖 임시 디렉터리에 `pip install --target ... ruff==0.14.0`으로 설치해 실행 (pyproject.toml 무변경) |
| WSL 시계 | `time.time()`과 `time.monotonic()`이 어긋난다: 89 s(monotonic) 동안 벽시계가 30초마다 약 3.2 s씩 뛰어 9.647 s 차이. 테스트의 경과 시간은 monotonic, 작업 상태의 `startTime`·`endTime`은 벽시계라 같은 구간이 약 10% 다르게 보인다(AC-11) |

환경 문제로 UNVERIFIED가 된 AC는 없다.

### 실행 방식

- 테스트 모듈이 storage agent를 root로 직접 띄운다: `python -m uvicorn --factory storage_agent.agent_app:create_app --app-dir backend --host 127.0.0.1 --port 8090`. AC-11·AC-12가 agent를 멈추고 다시 띄워야 하기 때문이다.
- anf-api는 일반 사용자(mkimhome1)로 띄운다: `setpriv --reuid=<uid> --regid=<gid> --init-groups -- python -m uvicorn --factory anf_api.arm_app:create_app --app-dir backend --host 127.0.0.1 --port 8080`. 환경 변수 `ANF_API_DB=/tmp/anf-vol-e2e-XXXX/anf.db`(사용자가 만든 디렉터리), `ANF_MIN_VOLUME_SIZE_GIB=1`(AC-06 하한 확인만 끔), 필요한 테스트만 `ANF_FAULT_INJECTION`. 테스트가 DB를 읽을 때도 `seteuid`로 그 사용자 권한으로 읽는다(root가 WAL 파일을 만들면 anf-api가 DB를 다시 못 연다).
- 클라이언트: `anf-nfs-client` privileged 컨테이너, 네트워크 `anf-vnet`. 마운트 IP는 GET의 `mountTargets[0].ipAddress`. 거절을 확인하는 마운트는 `retry=0,soft,timeo=20,retrans=1`, v3에는 `nolock`.
- 명령의 성공·실패는 종료 코드와 stderr 전체로 판정했다. 모든 결과는 `ANF_E2E_LOG`(jsonl)와 `-s` 출력에 남겼다.

전체 실행 명령:

```
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/tmp/anf-vol-e2e-r1c.jsonl /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider backend/tests/e2e/test_volume_live.py -v -s'
```

| 실행 | 범위 | 결과 |
| --- | --- | --- |
| r1 | 전체(당시 18 항목) | 16 passed, 2 failed in 410.16 s. 둘 다 테스트 결함(아래 "테스트 결함" 참고) |
| r1b | `-k "ac05 or grace or ac15"`, `ANF_E2E_REPEAT=10` | 3 passed in 211.01 s. AC-15 첫 쓰기 101.96 s |
| r1c | 전체 21 항목 | **21 passed in 364.59 s** |
| r1d | `-k "ac03 or ac15"` (유예 기간 단언을 더한 뒤) | 2 passed in 32.57 s, 이 실행 중 추적 실패 0회 |

## 결과 요약

AC 기준: **PASS 14 / FAIL 1 / UNVERIFIED 0**

추가 항목: CI 명령 로컬 재현 PASS, GitHub Actions 실제 실행 UNVERIFIED (push 대기)

FAIL: **AC-03 (불안정)** — NFSv4.1 볼륨 인스턴스가 가끔 NFSv4 클라이언트 추적 없이 시작해 90초 유예 기간에 들어간다. 그동안 `Succeeded`인 볼륨에 첫 쓰기가 90~102초 막힌다.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1회차 (r1, r1c) |
| AC-02 | PASS | 1회차 (r1, r1c) |
| AC-03 | **FAIL (불안정)** | 1회차 (r1, r1b, r1c, r1d) |
| AC-04 | PASS | 1회차 (r1, r1c) |
| AC-05 | PASS | 1회차 (r1b, r1c) |
| AC-06 | PASS | 1회차 (r1, r1c) |
| AC-07 | PASS | 1회차 (r1, r1c) |
| AC-08 | PASS | 1회차 (r1, r1c) |
| AC-09 | PASS | 1회차 (r1, r1c) |
| AC-10 | PASS | 1회차 (r1, r1c) |
| AC-11 | PASS | 1회차 (r1, r1c) |
| AC-12 | PASS | 1회차 (r1, r1c) |
| AC-13 | PASS | 1회차 (r1, r1c) |
| AC-14 | PASS | 1회차 |
| AC-15 | PASS (AC-03 결함의 영향 기록) | 1회차 (r1, r1b, r1c, r1d) |
| CI 로컬 재현 | PASS | 1회차 |
| GitHub Actions 실행 | UNVERIFIED | — (push는 사용자 결정) |

## 항목별 결과

아래 출력은 r1c(전체 21 PASS)에서 가져왔다. 다른 실행에서 가져온 것은 따로 적었다.

### [PASS] AC-01 NFSv3 볼륨 생성 계약과 상태 (계약·상태)
- 기준: Premium 4 TiB 풀 아래 `{creationToken, usageThreshold: 107374182400, subnetId}` PUT → `201` `Creating`, 헤더는 `Azure-AsyncOperation`만. 폴링 → `Succeeded`(`action: CREATE`). GET에 §4.2 값. 풀 목록에 볼륨.
- 실행한 명령: `test_ac01_create_nfsv3_volume_contract_and_state`
- 출력(핵심 부분):
  - PUT: `status 201`, `lro_headers ["azure-asyncoperation"]`, `provisioningState "Creating"`
  - 작업: `seen ["Creating","Creating","Creating","Succeeded"]`, `action "CREATE"`, `startTime 06:39:06.323` → `endTime 06:39:08.480` (2.16 s)
  - GET: `fileSystemId 5725ea72-2af3-42a6-a34c-1d12e5e69430`, `mountTargets [{"mountTargetId": "5725ea72-…", "fileSystemId": "5725ea72-…", "ipAddress": "172.30.0.129"}]`, `protocolTypes ["NFSv3"]`, 규칙 `nfsv3 true / nfsv41 false / unixReadWrite true / allowedClients 0.0.0.0/0 / hasRootAccess true`, `unixPermissions "0770"`, `serviceLevel "Premium"`, `actualThroughputMibps 6.25`
  - 데이터 플레인: 전 `{lvs: [], instances: {}, ns: []}` → 후 LV `vol_5725ea72…`(크기 107374182400, 태그 `anf_ip=172.30.0.129,anf_path=e2ev2ea3-ac01,anf_proto=nfs3,anf_uuid=5725ea72-…`), 인스턴스 `anf-nfs-5725ea72…` running(IP 172.30.0.129), `ns/e2ev2ea3-ac01`. anf-api 상관 ID가 agent 로그에 있다(`correlation_in_agent_log: true`).
  - 풀 아래 목록: `200`, `value`의 ID가 이 볼륨 하나다(테스트 단언).

### [PASS] AC-02 NFSv3 두 클라이언트 (데이터)
- 기준: A가 `vers=3`으로 마운트해 쓰고, B가 같은 경로를 마운트해 읽는다. 루트 권한 `0770`. `vers=4.1`은 실패.
- 실행한 명령: `test_ac02_nfsv3_mount_two_clients`
- 출력:
  - A: rc 0, `stat` `770`, `/proc/mounts` `172.30.0.129:/e2ev2ea3-ac02 /m nfs …vers=3…addr=172.30.0.129`
  - B: rc 0, `from-a-c4d5d422ca8c43678e64b2c048086d79`, `770`
  - `vers=4.1`: rc 32, `mount.nfs: Protocol not supported for 172.30.0.129:/e2ev2ea3-ac02 on /m`

### [FAIL (불안정)] AC-03 NFSv4.1 볼륨 (데이터)
- 기준: `protocolTypes: ["NFSv4.1"]` 볼륨의 기본 규칙은 `nfsv41: true`, `nfsv3: false`. 클라이언트가 `vers=4.1`로 마운트해 읽고 쓴다. `vers=3`, `vers=4.0`은 실패. 공통 조건의 제한 시간은 60초다.
- 실행한 명령: `test_ac03_nfsv41_volume`(4회), `test_ac15_…`(4회), `test_nfsv41_new_instances_skip_grace_repeated`(r1b 10라운드, r1c 6라운드), 커널 로그 `dmesg | grep -E "Unable to initialize client recovery|90-second grace|Using nfsdcld"`
- AC-03 테스트 자체의 출력(4회 모두 같은 결과):
  - GET: `protocolTypes ["NFSv4.1"]`, 규칙 `nfsv3 false, nfsv41 true`
  - 쓰기·읽기: rc 0, 0.29 s(r1c)·0.33 s(r1d), `v41-data`, `vers=4.1 … addr=172.30.0.129`, 인스턴스 로그 `versions=-3 +4 -4.0 +4.1 -4.2 grace_ended=Y`. 두 번째 클라이언트도 같은 내용을 읽었다.
  - `vers=3`: rc 32 `requested NFS version or transport protocol is not supported`. `vers=4.0`: rc 32 `Protocol not supported`
- **실패 관찰** (같은 제품 코드가 만든 NFSv4.1 볼륨, AC-15에서):
  - r1b: 볼륨 `Succeeded`, 마운트 성공, 그러나 `echo a > /m1/a && echo b > /m2/b && sync`가 **101.96 s** 걸렸다. 인스턴스 로그 `anf-nfs: serving /e2ev9333-ac15a (nfs4.1): versions=-3 +4 -4.0 +4.1 -4.2 grace_ended=N`
  - r1: 같은 쓰기가 `nfs4_handle_exception`에서 멈춰 있었다(`ps -o wchan`). 인스턴스 `anf-nfs-4a24d038…`(ac15b) 로그 `grace_ended=N`. 그 인스턴스 안에서 `nfsdcld`(PID 13)는 돌고 있었다. 결국 성공했다(정확한 시간은 그때 테스트가 재지 않았다).
  - 커널 로그(r1의 그 시각):
    ```
    [33000.584515] NFSD: attempt to initialize umh client tracking in a container ignored.
    [33000.584571] NFSD: Unable to initialize client recovery tracking! (-2)
    [33000.584573] NFSD: Is nfsdcld running? If not, enable CONFIG_NFSD_LEGACY_CLIENT_TRACKING.
    [33000.584574] NFSD: starting 90-second grace period (net f0000397)
    ```
    정상 인스턴스는 `NFSD: Using nfsdcld client tracking operations.` / `no clients to reclaim, skipping NFSv4 grace period`다.
- 빈도: 추적 실패 7회를 확인했다(아래 표). 커널 로그는 순환 버퍼라 일부가 밀려났고, 남은 범위에서 성공은 약 85회였다(약 7~8%). 이번 e2e가 만든 NFSv4.1 인스턴스는 약 42개, 그중 2개가 실패했다(둘 다 AC-15). 같은 순서로 두 개씩 만드는 반복 시험은 32개 모두 `grace_ended=Y`, 첫 쓰기 0.73~1.07 s였다.

  | # | 커널 시각 | 실행 | 인스턴스 | 프로토콜 | 관찰된 영향 |
  | --- | --- | --- | --- | --- | --- |
  | 1 | 32994.10 | r1 | AC-13 (agent API) | NFSv3 | 없음 (`nolock` 클라이언트) |
  | 2 | 33000.58 | r1 | AC-15 v15b | NFSv4.1 | 첫 쓰기가 `nfs4_handle_exception`에서 대기 |
  | 3 | 33328.24 | r1b | AC-15 v15a | NFSv4.1 | 첫 쓰기 101.96 s |
  | 4 | 33571.87 | r1c | AC-05 | NFSv3 | 없음 |
  | 5 | 33615.30 | r1c | AC-07 | NFSv3 | 없음 |
  | 6 | 33854.54 | r1c | AC-13 | NFSv3 | 없음 |
  | 7 | 34397.83 | 통합 테스트 | `test_flexvol_linux.py` | 불명 | 통합 테스트가 131.91 s 걸렸다(리더 기록 32.7 s). 차이 약 99 s가 유예 기간과 맞는다(추정) |

- 기대값: 볼륨이 `Succeeded`가 된 뒤 NFSv4.1 클라이언트의 첫 쓰기가 60초 안에 끝난다(정상 0.24~0.33 s). 인스턴스 로그는 `grace_ended=Y`다.
- 판정 이유: 설계 "구현 중 변경" 1번은 `nfsdcld`로 유예 기간을 건너뛴다고 했지만 그것이 항상 되지는 않는다. API는 `Succeeded`인데 클라이언트는 90초 넘게 쓰지 못하므로 "클라이언트에서 관찰한 효과" 기준으로 FAIL이다. AC-03 테스트 자체는 4회 모두 통과했으므로 불안정으로 따로 표시한다.
- 추정 원인 파일:줄:
  - `backend/storage_agent/nfs_server/entrypoint.sh:24` `nfsdcld`를 띄우고 준비를 기다리지 않은 채 다음으로 넘어간다.
  - `backend/storage_agent/nfs_server/entrypoint.sh:32` `rpc.nfsd $versions 4`가 클라이언트 추적을 초기화한다. 커널은 `nfsd/cld` 파이프를 만든 뒤 nfsdcld가 열기를 짧게(약 1초, 커널 소스 기준 추정) 기다린다. 그 안에 nfsdcld가 준비되지 않으면 예전 umh 추적으로 넘어가는데, 컨테이너 안에서는 무시된다. 그래서 추적이 없고 90초 유예 기간을 돈다. 실패한 인스턴스 안에서도 nfsdcld가 돌고 있었으므로 "늦게 준비됨"으로 본다.
  - `backend/storage_agent/nfs_server/entrypoint.sh:33` `grace_ended=N`을 로그에 쓰고 그대로 서비스한다.
  - `backend/storage_agent/nfs_instance.py:71-75` `docker run -d`가 컨테이너가 시작되면 바로 돌아온다. agent는 인스턴스가 준비됐는지(knfsd 시작, 유예 기간 끝) 확인하지 않고 job을 `success`로 끝낸다. 그래서 anf-api가 `Succeeded`를 낸다. `docker start` 경로(`nfs_instance.py:68-69`)도 같다.
- 수정 제안:
  1. 진입점: `rpc.nfsd` 뒤에 `/proc/fs/nfsd/v4_end_grace`를 읽는다. `N`이면 `rpc.nfsd 0` 후 다시 시작한다(그때는 nfsdcld가 떠 있다). 몇 번 해도 `N`이면 0이 아닌 코드로 끝낸다. 프로토콜과 상관없이 적용한다. NFSv3 인스턴스도 같은 실패가 났고, 유예 기간 동안에는 NLM 잠금 요청이 거절될 것이다(추정, 이번 검증은 `nolock`이라 미확인).
  2. agent: 인스턴스를 띄운 뒤(`docker run`·`docker start`) 준비 줄(`serving … grace_ended=Y`)이나 컨테이너 종료를 제한 시간 안에서 기다린다. 준비되지 않으면 job을 실패로 끝낸다. 그래야 `Succeeded`가 "지금 마운트하고 쓸 수 있다"는 뜻이 된다.
  3. 단위 테스트(`test_nfs_instance.py`)에 준비 대기·실패를 넣는다. e2e는 이번에 단언을 더했다(아래).
- 재현 명령 (간헐적이라 전체 실행을 권한다. 인스턴스 시작 약 40회에 한 번 이상 날 확률이 높다):
  ```
  MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && D0=$(dmesg | grep -c "Unable to initialize client recovery"); PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_REPEAT=30 /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider backend/tests/e2e/test_volume_live.py -v -s; D1=$(dmesg | grep -c "Unable to initialize client recovery"); echo tracking_failures=$((D1-D0))'
  ```
  r1d부터 AC-03·AC-15 테스트는 인스턴스 로그가 `grace_ended=Y`이고 첫 쓰기가 60초 미만인지 단언한다. NFSv4.1에서 나면 AC-03·AC-15·반복 시험이 FAIL로 잡는다. NFSv3에서 난 것은 `tracking_failures`로만 보인다. 재검증의 PASS 조건으로 `tracking_failures=0`을 권한다.

### [PASS] AC-04 할당량 초과 쓰기 (데이터)
- 기준: 1 GiB 볼륨의 `df`가 약 1 GiB. 1.2 GiB `dd conv=fsync`는 rc ≠ 0, stderr에 `No space left on device`. 다른 파일은 그대로 읽힌다.
- 실행한 명령: `test_ac04_quota_full_write_fails[NFSv3-3]`, `[NFSv4.1-4.1]`
- 출력 (NFSv3 / NFSv4.1 같음):
  - `df` 전: `1021313024` 바이트 크기(974 MiB, ext4 오버헤드 안)
  - `dd`: rc 1, `dd: fsync failed for '/m/big': No space left on device`, `1288699904 bytes (1.3 GB, 1.2 GiB) copied, 2.54965 s` (v4.1 2.51337 s)
  - 후: `df` 100%, `keep-06ac2641…` 그대로 읽힘(rc 0)
- 관찰(결함 아님): 오류는 `write()`가 아니라 `fsync`에서 나왔다(NFS 비동기 쓰기). 클라이언트 `ls -l`은 `1288699904`를 보이지만 호스트의 실제 파일은 `1179648000`(v3) / `1225785344`(v4.1) 바이트다. 클라이언트가 캐시에 쓴 크기와 서버에 실제로 들어간 크기가 다르다.

### [PASS] AC-05 용량·부모 규칙과 CV-1~CV-3 (계약)
- 실행한 명령: `test_ac05_capacity_and_parent_rules` (풀 삭제·PATCH에 8초 지연 주입)
- 출력:
  - 풀 할당량 합 초과(1 GiB + 4 TiB > 4 TiB): `400 BadRequest "Pool size too small for total volume size."`, 그 볼륨의 작업 없음
  - 없는 풀: `404 ParentResourceNotFound`
  - `Deleting` 풀 아래: `409 Conflict "Cannot create volume '…/p-del/volumes/v4' because its parent capacity pool '…/p-del' is being deleted."`, 작업 없음
  - (보조, §4.3) `Patching` 풀 아래: `400 BadRequest "Volume cannot be created in a pool that isn't in state succeeded."`
  - CV-1: `409 CannotDeleteResource "… nested resource IDs include: 'Microsoft.NetApp/netAppAccounts/e2e-vol-acct/capacityPools/e2e-vol-pool/volumes/v1' …"`, 풀은 `Succeeded`로 남음
  - CV-2: 풀 2 TiB에 1025 GiB 볼륨을 넣었다. aggregate가 약 1 TiB라 agent가 거절해 볼륨은 `Failed`지만 예약은 남는다(agent 로그 `aggregate aggr0 has 1098165256192 bytes left; the volume needs 1100585369600`, 작업 오류 `InternalServerError`). 그 풀을 1 TiB로 PATCH·PUT → 둘 다 `400 BadRequest "The capacity pool size of 1099511627776 bytes is too small for the combined volume size of 1100585369600 bytes …"`, 크기 2 TiB 유지
  - CV-3: PUT `serviceLevel: Ultra` → `400 BadRequest "ServiceLevel cannot be changed."`. PATCH `serviceLevel` → `400 InvalidRequestContent "Value received for an unknown property 'properties.serviceLevel'."` (풀 설계 결정 5·§4.3: 풀 PATCH 모델에 serviceLevel이 없다). 둘 다 400이고 serviceLevel은 Premium 그대로
  - 데이터 플레인: 거절 전후 같다(`v1`의 LV·인스턴스만)

### [PASS] AC-06 잘못된 본문 거절 (계약)
- 실행한 명령: `test_ac06_invalid_bodies_rejected`
- 출력: 22개 모두 `400`. 작업 수 그대로, 볼륨 행 없음, 데이터 플레인 그대로.
  - `InvalidResourceName`: `1vol`, 65자 이름
  - `InvalidRequestContent`: `creationToken` 누락·`-a`·81자, `usageThreshold` GiB+1·0·100 TiB+1 GiB, `protocolTypes` `["CIFS"]`·`["NFSv3","NFSv4.1"]`·`[]`, `subnetId` ID 아님·VNet만·누락, `exportPolicy` 사용자 규칙(`allowedClients 10.0.0.0/8`), `throughputMibps`, `snapshotDirectoryVisible: false`, `snapshotId`, `kerberosEnabled: true`, 모르는 속성(properties·최상위), `serviceLevel: Standard`(풀은 Premium)
  - 대조: 미룬 속성을 기본값으로 보내면(`snapshotDirectoryVisible: true`, `kerberosEnabled: false`, 기본 규칙) `201` → `Succeeded`
  - 최소 크기 주입을 끈 서버: 49 GiB `400 InvalidRequestContent "… from 50 GiB to 100 TiB."`, 50 GiB `201` → `Succeeded`, LV 크기 50 GiB

### [PASS] AC-07 경로 중복과 바꿀 수 없는 속성 (계약)
- 실행한 명령: `test_ac07_path_uniqueness_and_immutable_properties`
- 출력:
  - 같은 `creationToken`, 대소문자만 다른 것: 둘 다 `400 BadRequest "File path already in use."`
  - PUT 갱신 `creationToken` → `400 BadRequest "CreationToken cannot be changed."`, `subnetId` → `400 BadRequest "SubnetId cannot be changed."`, `usageThreshold` → `400 InvalidRequestContent "Changing 'properties.usageThreshold' is not supported by this ANF clone."`
  - 거절 뒤 클라이언트: rc 0, `df` 크기 1021313024, `first` 읽힘. LV 크기 1073741824 그대로
  - 같은 값 PUT: `200`, `Azure-AsyncOperation`, `Updating` → `Succeeded`(`action: UPDATE`)

### [PASS] AC-08 tags PATCH 중 클라이언트 I/O (계약·상태)
- 실행한 명령: `test_ac08_patch_tags_while_client_reads_and_writes`
- 출력: `202`, 본문 `Patching`, 헤더 `azure-asyncoperation`·`location`, `Patching` → `Succeeded`(`action: PATCH`), Location 폴링 `200`, GET tags `{"env": "e2e", "ac": "08"}`. 그동안 클라이언트 쓰기·읽기 루프 rc 0, 475회. PATCH `usageThreshold` → `400 InvalidRequestContent`

### [PASS] AC-09 삭제 (데이터·상태)
- 실행한 명령: `test_ac09_delete_volume`
- 출력:
  - DELETE: `202`, 본문 없음, 헤더 `azure-asyncoperation`·`location`, `Deleting` → `Succeeded`(`action: DELETE`), 3.0 s. GET `404 ResourceNotFound`. 다시 DELETE `204`, 본문·헤더 없음
  - 새 마운트: rc 32 `mount.nfs: Host is unreachable for 172.30.0.129:/e2ev2ea3-ac09`
  - 인스턴스 `docker inspect` rc 1, LV 없음, `ns/e2ev2ea3-ac09` 없음. 씬 풀 사용률 0.00% → 200 MiB 쓴 뒤 0.02% → 삭제 뒤 0.00%(공간 회수)
  - 삭제 전에 마운트해 둔 클라이언트: `cat: /m/f: I/O error`, `ls: cannot open directory '/m': Stale file handle`
  - 같은 `creationToken`으로 다시 생성: IP 172.30.0.129 재사용(비어 있는 가장 낮은 IP), 새 `fileSystemId`, 새 마운트 성공. 예전 마운트는 계속 `Stale file handle`(fsid가 다르다)

### [PASS] AC-10 생성 중 충돌 (계약)
- 실행한 명령: `test_ac10_requests_during_create_conflict` (볼륨 생성 8초 지연 주입)
- 출력: PUT·PATCH·DELETE 모두 `409 RequestConflict "Cannot modify resource with id '…/volumes/v10' because the resource entity provisioning state is not terminal. Please wait for the provisioning state to become terminal and then retry the request."`, LRO 헤더 없음. 작업은 `CREATE` 하나뿐. 원래 작업 `Creating`×10 → `Succeeded`, tags `{}` 그대로, 마운트 성공

### [PASS] AC-11 실패와 회복 (상태)
- 실행한 명령: `test_ac11_injected_failure_keeps_reservation_then_put_recovers`, `test_ac11_agent_down_fails_after_retry_then_put_recovers`
- 출력:
  - 생성 실패 주입: 작업 `Failed`, `error {"code": "InternalServerError", "message": "Injected fault: volumes/create (ANF_FAULT_INJECTION)."}`, 볼륨 `Failed`. 예약이 남은 것을 같은 풀에 남은 용량을 넘는 PUT으로 확인(`400 BadRequest "Pool size too small for total volume size."`). 데이터 플레인 그대로
  - 주입을 끈 서버에서 같은 본문 PUT: `200`, `Updating` → `Succeeded`, 마운트 rc 0
  - agent를 멈춘 채 생성: monotonic 60.3 s 뒤 `Failed`(작업 시각으로는 06:42:23.19 → 06:43:29.91, WSL 시계 차이), `InternalServerError`(작업 ID가 든 일반 메시지), anf-api 로그에 연결 실패 62줄. agent를 띄운 뒤 PUT → `Succeeded`, 마운트 rc 0

### [PASS] AC-12 재시작 복구 (상태)
- 실행한 명령: `test_ac12a_…`, `test_ac12b_agent_killed_during_create_job[job-start|lv-created|mounted]`, `test_ac12c_…`
- 출력:
  - (a) 생성 지연 중 anf-api SIGKILL(rc -9). 그때 작업 `CREATE/Creating`, 데이터 플레인 없음. 다시 띄우자 `Succeeded`, 마운트 rc 0, LV 하나
  - (b) agent를 job 세 단계에서 SIGKILL했다. job 시작 직후(LV 없음), LV 생성 뒤(파일시스템 없음), 마운트 뒤(인스턴스 없음). 각 단계에서 3초 뒤에도 상태가 그대로였다. agent를 다시 띄우자 3.3 / 3.5 / 3.9 s 뒤 `Succeeded`, 그 UUID의 LV가 하나뿐, 인스턴스 running, 마운트 rc 0
  - (c) agent를 멈추고 인스턴스 `docker stop`, 호스트 마운트를 손으로 내림(`instance: exited`, `mounted: false`). 그동안 마운트는 rc 32 `Operation timed out`. agent를 띄우자 인스턴스가 같은 IP 172.30.0.129로 running, 다시 마운트해 `before-restart` 읽음

### [PASS] AC-13 agent API (계약)
- 실행한 명령: `test_ac13_agent_api`
- 출력:
  - POST: `202`, `{"job": {"uuid": …, "_links": {"self": {"href": "/api/cluster/jobs/…"}}}}`, job `success`
  - 같은 uuid·설정으로 다시 POST: job `success`, LV `vol_29f3eb68…` 하나
  - 같은 uuid에 다른 경로: job `failure`, `"volume 29f3eb68-… already exists with path /e2ev2ea3-ac13, size 1073741824, protocol nfs3"`
  - `GET ?name=`: `num_records 1`, `data_lif.ip.address 172.30.0.129`, `state online`
  - 없는 uuid DELETE: job `success`
  - `nas.path` `../x`, `/../x`, `/a/b`, `/`, `/e2ev2ea3-ac13/..`: 모두 `400`

### [PASS] AC-14 회귀 (계정·풀 e2e)
- 실행한 명령 (일반 사용자):
  ```
  MSYS_NO_PATHCONV=1 wsl -d Ubuntu -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider backend/tests/e2e/test_netapp_account_live.py backend/tests/e2e/test_netapp_account_lro_faults_live.py backend/tests/e2e/test_capacity_pool_live.py backend/tests/e2e/test_capacity_pool_lro_faults_live.py -q -rfEs'
  ```
- 출력: `63 passed in 107.36s`, skip 0

### [PASS] AC-15 볼륨마다 따로 있는 서버 (데이터)
- 기준: NFSv4.1 볼륨 두 개의 IP가 다르다. 한 클라이언트가 둘을 마운트하면 `/proc/mounts`의 `addr=`가 각자의 IP이고, `ss -tn`에 두 IP로 가는 2049 연결이 따로 있다.
- 실행한 명령: `test_ac15_each_nfsv41_volume_has_its_own_server` (`ss`는 클라이언트 netns에서 `nsenter -t <pid> -n ss -tn`)
- 출력 (r1c):
  - IP `172.30.0.129`, `172.30.0.130`. 쓰기·읽기 rc 0 `a\nb\n`
  - `/proc/mounts`: `/m1 … addr=172.30.0.129`, `/m2 … addr=172.30.0.130`
  - `ss`: `ESTAB 172.30.0.2:701 → 172.30.0.130:2049`, `ESTAB 172.30.0.2:800 → 172.30.0.129:2049`
- 4회 모두 이 조건을 만족했다(r1의 실패는 테스트 정규식 결함). 다만 r1과 r1b에서는 첫 쓰기가 AC-03의 유예 기간 결함에 걸렸다(r1b 101.96 s). 그 결함은 AC-03에서 FAIL로 판정했다. r1d부터 이 테스트도 `grace_ended=Y`와 60초 미만을 단언한다.

### [PASS] CI 명령 로컬 재현
- 실행한 명령: scratchpad `ci_repro.sh`(일반 사용자, WSL Python 3.12.3). ci.yml의 단계를 같은 명령으로 실행했다. 차이: ruff는 venv 밖에 설치, 포트 18080, `/mnt/c`라 `-p no:cacheprovider`·`PYTHONDONTWRITEBYTECODE=1`.
- 출력:
  - lint: `ruff 0.14.0`, `All checks passed!`
  - test: `ANF_E2E_API_URL=http://127.0.0.1:18080 python -m pytest -m "not dataplane" --junitxml=…` → `576 passed, 25 deselected in 153.04s`
  - skip 검사(ci.yml과 같은 스크립트): `collected 576, skipped 0, failures 0, errors 0`, 선택된 데이터 플레인 파일 `[]`
  - 선택에서 빠진 것: `-m dataplane` 수집 25개 = 볼륨 e2e 21 + 통합 4. 그 수가 deselected 25와 같다
  - hook tests: `25 passed in 6.29s`

### [UNVERIFIED] GitHub Actions 실제 실행
- 이유: push가 필요하다. push는 사용자가 정한다.

## 테스트 결함 (제품 결함 아님, 고친 뒤 다시 실행)

- r1 AC-05: CV-3 PATCH를 `BadRequest`로 기대했다. 풀 설계 결정 5·§4.3에 따르면 풀 PATCH에는 serviceLevel이 없어 `InvalidRequestContent`(모르는 속성)가 맞다. 단언을 고쳤다. r1b·r1c PASS.
- r1 AC-15: `addr=` 정규식이 `clientaddr=172.30.0.2`에 먼저 걸렸다. `,addr=`로 고쳤다. r1 원본 출력에서도 `/proc/mounts`는 `addr=172.30.0.130`·`172.30.0.131`, `ss`는 두 연결이었다.
- r1d: AC-03·AC-15에 `grace_ended=Y`와 첫 쓰기 60초 미만 단언을 더했다. 그 전에는 유예 기간에 걸려도 통과했다.

## 측정값

| 항목 | 값 | 횟수 |
| --- | --- | --- |
| NFSv3 100 GiB 생성 → `Succeeded` | 2.16 s (AC-01, 작업 시각) | 1 |
| DELETE → `Succeeded` | 3.0 s (AC-09) | 1 |
| NFSv4.1 첫 쓰기 (정상) | AC-03 0.29·0.33 s, AC-15 0.24·0.27 s, 반복 시험 0.73~1.07 s(마운트 포함) | 36 |
| NFSv4.1 첫 쓰기 (유예 기간) | 101.96 s (r1b). r1은 같은 상태로 대기 확인 | 2 |
| knfsd 클라이언트 추적 실패 | 7회 / 커널 로그에 남은 시작 약 92회 (약 7~8%) | 이번 회차 전체 |
| `dd` 1.2 GiB(할당량 초과) | 2.51~4.51 s, 286~513 MB/s (처리량 제한 없음, FR-08 전) | 4 |
| agent 재시작 뒤 `Succeeded` (AC-12b) | 3.3 / 3.5 / 3.9 s | 3 |
| agent 정지 중 생성 실패까지 | monotonic 60.3 s / 작업 시각 66.7 s | 1 |
| PATCH 중 클라이언트 I/O 루프 | 475회, 오류 0 | 1 |
| `df` 크기 (1 GiB 볼륨) | 1021313024 바이트 (974 MiB) | 6 |
| 씬 풀 사용률 | 0.00% → 200 MiB 쓴 뒤 0.02% → 삭제 뒤 0.00% | 1 |
| 통합 테스트 (`backend/tests/integration`, root) | 4 passed in 131.91 s (추적 실패 1회 포함) | 1 |
| 전체 e2e (r1c) | 21 passed in 364.59 s | 1 |

## 통합 정합성

- anf-api ↔ agent: 상관 ID가 agent 로그에 남는다(AC-01). agent job 실패는 anf-api 작업 오류 `InternalServerError`(작업 ID가 든 일반 메시지)가 되고, 이유는 agent 로그에만 있다(CV-2, AC-11). 설계 "구현 중 변경"과 같다.
- agent job 성공과 인스턴스 준비 사이에 틈이 있다. job은 `docker run -d`가 돌아오면 끝나서, 인스턴스가 유예 기간에 들어가도 `Succeeded`가 된다. AC-03 FAIL의 연결 지점이다.

## 정리 상태 (검증 끝)

- 서버 프로세스: `pgrep -af "[u]vicorn|[s]torage_agent"` 없음(rc 1). 8080·8090·18080 수신 없음
- 컨테이너: `docker ps -a` 0개 (`anf-nfs-*`, `anfe2e-cli-*` 없음)
- LV: `lvs anf`에 `aggr0`만 (Data 0.00%). `/var/lib/anf-clone/ns` 아래 마운트·디렉터리 없음
- 남긴 것: aggregate(`aggr0.img`, `anf/aggr0`), 이미지(`anf-nfs-server:latest`, `anf-nfs-client:latest`, `anf-nfs-client:spike`), 네트워크 `anf-vnet`, 호스트 `nfs-server`(export 없음)
- 지운 것: 테스트 DB 디렉터리 `/tmp/anf-vol-e2e-*`, ruff 임시 설치
- 증거로 남긴 파일(WSL): `/tmp/anf-vol-e2e-r1{,b,c,d}.out`, `/tmp/anf-vol-e2e-r1{,b,c}.jsonl`, `/tmp/anf-ci-repro/pytest-results.xml`, agent 로그 `/tmp/pytest-of-root/pytest-*/agent0/agent.log`

## 검증 스크립트

- `backend/tests/e2e/test_volume_live.py`: 마커 `e2e`, `dataplane`. `ANF_E2E_API_URL`이 없거나 Linux root가 아니면 skip. CI는 `-m "not dataplane"`으로 선택에서 뺀다.
- 환경 변수: `ANF_E2E_USER`(anf-api 사용자, 없으면 venv 소유자), `ANF_E2E_REPEAT`(유예 기간 반복 시험 라운드, 기본 6), `ANF_E2E_LOG`(jsonl 증거).
- 테스트가 만든 볼륨 경로는 `e2ev<임의 4자리>-`로 시작한다. 모듈이 끝나면 agent API로 남은 것을 지운다.
