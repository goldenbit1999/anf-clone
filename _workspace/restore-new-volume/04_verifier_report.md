# restore-new-volume 검증 보고서 — 1회차

- 진행 상태: 완료 (2026-11-09 01:46 PST)
- 검증일: 2026-11-09
- 검증 대상 코드: 제품 코드 내용 해시 시작 `1e950522c13e991ad33d06e2ad2fbd182685426ef7f774fc8bde4ccbf339a9f7`(작업 트리, 커밋 `a8ddc0a`에서 계산한 값과 같음, 리더가 준 값과 같음), 끝 `1e950522c13e991ad33d06e2ad2fbd182685426ef7f774fc8bde4ccbf339a9f7`(같음, 검증 중 제품 코드 변경 없음). `git rev-parse HEAD` = `7a3e4340ef5410faaa58d380a509658620768976` (`git diff --stat a8ddc0a HEAD`는 `_workspace/restore-new-volume/00_progress.md`만).
  해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
- 미커밋 변경(시작 시): `_workspace/restore-new-volume/00_progress.md`(리더), `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`.
- 이번 회차 범위: 전체 (AC-01~AC-11)

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | 시작 때 `Ubuntu` Stopped(VERSION 2) → 유휴 종료 방지 세션(`wsl -d Ubuntu -u root -e sleep 86400`, 백그라운드)으로 띄움. 커널 `6.18.54.1-microsoft-standard-WSL2` |
| 커널 모듈 | `nfsd` 로드됨. `dm_thin_pool`은 agent가 aggregate를 붙일 때 로드됨(`aggr0 twi-aotz--`) |
| Docker | Ubuntu 안 Docker Engine `server=29.1.3 os=linux`, `readlink /usr/bin/docker` 비어 있음 (Desktop 연동 아님) |
| 이미지·네트워크 | `anf-nfs-server`, `anf-nfs-client` 있음. `anf-vnet` = `172.30.0.0/24 172.30.0.0/25` |
| 위임 꺼짐 | `sysctl -n fs.leases-enable` = `0`, `/etc/sysctl.d/90-anf-clone.conf` = `fs.leases-enable = 0` |
| 창 도구 | `/usr/sbin/iptables` v1.8.10 (nf_tables), `/usr/bin/nsenter` |
| venv | `/home/mkimhome1/.venvs/anf-clone` (fastapi 0.162.2, uvicorn 0.54.0, pytest 9.2.0) |
| 시작 상태 | 포트 8080·8090 비어 있음, uvicorn 없음, `anf-nfs-*` 컨테이너 없음, `ns/`·`exports/` 비어 있음, 호스트에 anf-clone 마운트 없음. WSL이 멈춰 있었으므로 루프 장치가 풀려 VG `anf`가 보이지 않았다. agent를 한 번 띄워(3 s 만에 준비, `GET /api/storage/volumes` = 레코드 0) aggregate를 붙이고 멈췄다: VG `anf`에 `aggr0`(Data 0.00%, Meta 10.42%)과 내부 LV만 있다. 리더가 말한 상태와 같다 |
| 메모리 (시작) | WSL `free -m`: total 7778, used 705, free 5613, available 7073, swap 0/2048. Windows: 여유 물리 메모리 8,456,808 KB / 16,440,692 KB |
| 서비스 | agent(root, 127.0.0.1:8090)와 anf-api(일반 사용자 `mkimhome1`, 127.0.0.1:8080, `ANF_MIN_VOLUME_SIZE_GIB=1`)는 e2e 픽스처가 시험 파일마다 직접 띄우고 멈춘다(`dataplane_live.py`) |

모든 점검이 통과했다.

## 결과 요약

PASS 11 / FAIL 0 / UNVERIFIED 0

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1회차 |
| AC-02 | PASS | 1회차 (이 보고서) |
| AC-03 | PASS | 1회차 |
| AC-04 | PASS | 1회차 |
| AC-05 | PASS | 1회차 |
| AC-06 | PASS | 1회차 |
| AC-07 | PASS | 1회차 |
| AC-08 | PASS | 1회차 |
| AC-09 | PASS | 1회차 |
| AC-10 | PASS | 1회차 |
| AC-11 | PASS | 1회차 |

## 실행 방법

모두 WSL에서 root로, 저장소 루트에서 실행했다. 판정 근거(`note`)는 `-s` 출력과 `ANF_E2E_LOG`(JSON Lines)에 남는다. 출력은 WSL `/root/e2e-logs/<label>.out`, `<label>.jsonl`에 두었다. 메모리 때문에 파일을 하나씩 돌렸고, 실행 사이에 `sync; echo 3 > /proc/sys/vm/drop_caches`로 WSL 페이지 캐시를 비워 Windows에 메모리를 돌려줬다(검증 대상 동작과 무관한 캐시 정리).

```
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash <scratchpad>/run.sh <label> <test file>
# run.sh: cd /mnt/c/Users/mkimh/Projects/ANF-clone && PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 \
#   ANF_E2E_LOG=/root/e2e-logs/<label>.jsonl /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider <file> -v -s
#   앞뒤로 free -m, 끝나고 남은 anf 컨테이너·LV·포트를 출력한다
```

| 실행 | 파일 | 결과 | 시간 | WSL `free -m` 전 → 후 (free / buff·cache / available) | Windows 여유 메모리 |
| --- | --- | --- | --- | --- | --- |
| data1 | `test_restore_new_volume_data_live.py` | 5 passed | 179 s | 6989/379/7209 → 4575/2645/7029 | 7,357,124 KB(전) → 4,722,992 KB(후), 캐시 비운 뒤 5,875,700 KB |
| contract1 | `test_restore_new_volume_contract_live.py` | 8 passed | 367 s | 7075/239/7154 → 5866/1341/7032 | 5,875,700 KB → 6,319,396 KB(중간) → 5,966,192 KB(후) |
| integration | `backend/tests/integration` (root) | 25 passed | 354 s | 7063/241/7143 → 5128/2055/6999 | 6,110,024 KB(후) |
| reg-* (12개) | AC-11 회귀 e2e, 아래 AC-11 표 | 118 passed | 1,780 s (파일별 합) | 아래 표 | 아래 표 |

남은 것: 실행마다 끝난 뒤 `anf-*` 컨테이너 없음, VG `anf`에 `aggr0`만, 포트 8080·8090 비어 있음. teardown의 `thin_data_percent` = `0.00`.

## 항목별 결과

### [PASS] AC-01 계약·상태 (성공)

- 기준: V의 스냅샷 S의 ARM ID로 N PUT → `201`, `Azure-AsyncOperation`과 `Location`, 본문 `Creating`과 `snapshotId`. `Creating`(`action: CREATE`) → `Succeeded`, 지연 중 GET `Creating`. 끝난 뒤 GET의 `snapshotId`·`originatingResourceId` = S, `fileSystemId`·IP가 V와 다름, `cloneProgress` 없음, 주지 않은 `protocolTypes`·`unixPermissions`는 V 값. N 스냅샷 목록에 base 하나(이름 S, `snapshotId` 다름, `created` 같음).
- 실행: `test_restore_new_volume_contract_live.py::test_ac01_contract_and_states`. V는 기본값과 다른 `NFSv4.1`·`0755`로 만들었다(N이 V 값을 받는지 구별하려고). N 생성은 `ANF_FAULT_INJECTION={"volumes/create": {"delaySeconds": 5}}` 서버(같은 DB)에서.
- 출력(핵심):
  - V의 일반 생성 `201` 헤더: `azure-asyncoperation`, `content-length`, `content-type`, `date`, `server`, `x-ms-correlation-request-id`, `x-ms-request-id` — `location` 없음(녹화 V1, 설계 §9 1번).
  - N PUT `201`: `azure-asyncoperation: http://127.0.0.1:8080/subscriptions/0e2e…/providers/Microsoft.NetApp/locations/westus2/operationResults/d5e74eea-…?api-version=2026-08-01`, `location` = 같은 URL + `&operationResultResponseType=Location`. 본문 `provisioningState: Creating`, `snapshotId` = S의 ARM ID, `protocolTypes ["NFSv4.1"]`, `unixPermissions "0755"`, `originatingResourceId`·`mountTargets` 없음.
  - 지연 중 N GET `Creating`, 작업 `{"status": "Creating", "percentComplete": 0.0, "properties": {"resourceName": "…/volumes/vn1n", "action": "CREATE"}}`. 폴링 `Creating` ×8 → `Succeeded`(7.24 s = 지연 5 s + 생성).
  - `Location` 조회 `200`, 볼륨 본문(`Succeeded`).
  - 끝난 뒤 GET: `snapshotId` = `originatingResourceId` = `…/volumes/vn1/snapshots/S`, `fileSystemId` `5837698f-…` ≠ V `8c83e8f0-…`, IP `172.30.0.130` ≠ V `172.30.0.129`, `cloneProgress` 없음, `protocolTypes ["NFSv4.1"]`, `unixPermissions "0755"`.
  - N 스냅샷 목록: `S` 하나, `provisioningState Succeeded`, `snapshotId` `799d5c0b-…` ≠ 원본 `d054a031-…`, `created` `2026-11-09T09:01:35Z` = 원본 `created`.
  - 클라이언트(v4.1): `cat /m/f` = `snap`(스냅샷 뒤에 V를 `later`로 바꿨다), `.snapshot` = `S`, 루트 `755`, `.snapshot/S/f` = `snap`. 작업 기록 `[("CREATE", "Succeeded")]`.

### [PASS] AC-02 데이터 (내용, NFSv3)

- 기준: V(v3)에 기록 S1 → S2 → S3 → 또 바꿈을 만든 뒤 S2로 N을 만든다. 클라이언트가 N을 v3로 마운트한 트리 = 서버의 S2 트리, `.snapshot`에는 `S2`만, `.snapshot/S2` = S2, 루트 모드 = N의 `unixPermissions`, 서버에서 N의 `.snapshot`이 immutable.
- 실행: `test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_content_and_independence[AC-02-NFSv3-3-None]`. 기록은 `revert_live.build_history`(S2 뒤에 `rm A`, `K` 덮어쓰기, `big` 같은 자리 덮어쓰기, `N`·`d3/Q` 새로 만들기, 또 `N`·`M`·`d2`·`Y` 바꿈). 원본 루트 모드는 기록 전에 클라이언트에서 `chmod 0711 /m`로 바꿨다(N이 이것을 물려받지 않고 자기 `unixPermissions`로 맞추는지 보려고, 결정 11). N은 `protocolTypes`·`unixPermissions` 없이 PUT.
- 출력(핵심):
  - N GET: `protocolTypes ["NFSv3"]`, `unixPermissions "0770"`(V 값), `snapshotId` = `originatingResourceId` = S2의 ARM ID, IP `172.30.0.130`.
  - `client_tree_equal_s2: true`, `client_base_equal_s2: true`, 서버 `tree_equal_s2: true`.
  - 클라이언트 `cat /m/A /m/K && ls -A /m /m/.snapshot && stat -c %a /m` → `a2 / k1 k2`(지운 A가 있고 덮어쓴 K는 S2 내용), `/m: .snapshot A K big d1 d2`, `/m/.snapshot: S2`, `770`. 마운트 `nfs ... vers=3 ... addr=172.30.0.130`.
  - `cat /m/N; ls /m/d3; ls /m/.snapshot/S1; ls /m/.snapshot/S3` → stdout 비어 있고 `No such file or directory` 4개(S2 뒤에 만든 것이 없고, 원본의 S1 마운트 지점 빈 디렉터리도 없다: 결정 8).
  - 서버: `.snapshot` = `["S2"]`, `lsattr -d` = `----i---------e-------`, N 루트 `770`, V 루트 `711`, V의 S2 루트 `711`. LV `Vwi-aotz--`, origin `snap_fb7c…`(V의 S2 LV), `anf_cl_*` 없음, base LV 하나, export 파일과 인스턴스 etab = `[/<N>, /<N>/.snapshot/S2]`. ARM 스냅샷 목록 `["S2"]`.
  - (기록) N의 ext4 UUID = V의 ext4 UUID `149f1ec5-…` (결정 6: 그대로 둠).

### [PASS] AC-03 데이터 (독립성, FR-07)

- 기준: N에 쓰고·덮어쓰고·지우면 V 트리, V 클라이언트에서 본 `.snapshot/S2`, N의 base가 그대로. V에 쓰고 지우면 N 트리가 그대로. base `.snapshot/S2` 안 쓰기는 실패(errno 기록).
- 실행: AC-02와 같은 테스트(v3)와 AC-04a 파라미터(v4.1)의 뒷부분. N 클라이언트: `echo nn > n_only; echo over2 > K; rm A; rm -r d1/sub; dd 4 MiB nbig; sync`. V 클라이언트: `echo vv > v_only; rm K; rm -r d1; sync`.
- 출력(핵심, v3과 v4.1 같음): `v_tree_same`, `v_client_s2_same`, `base_host_same`, `base_client_same`, `v_s2_equal_s_tree` 모두 `true`. V에서 `cat /m/K` = `over`(V 자기 내용), `ls /m/n_only /m/nbig` → `No such file or directory` 2개. V에 쓴 뒤 `n_tree_same`·`n_client_same` `true`, N에서 `cat /m/K` = `over2`, `ls /m/v_only` → 없음.
- base 스냅샷 안 쓰기 8가지 모두 rc 1:
  - v3: append·`dd conv=notrunc`·`>` = `Permission denied`(쓰기로 열기), touch·rm·mv·mkdir·chmod = `Read-only file system`.
  - v4.1: 8가지 모두 `Read-only file system`.
  - (기준 밖) `.snapshot` 자체: `rmdir .snapshot/S2` = `Resource busy`, `touch`/`mkdir` in `.snapshot` = `Operation not permitted`(+i). 시도 뒤 base 트리 그대로.

### [PASS] AC-04 데이터 (NFSv4.1, 다른 프로토콜·다른 풀)

- (a) v4.1 볼륨에서 AC-02·AC-03: `[AC-04a-NFSv4.1-4.1-0755]`(N에 `unixPermissions: "0755"`를 줌). 결과는 AC-02·AC-03과 같고, 마운트 `nfs4 ... vers=4.1`, 루트 `755`(요청 값), N `protocolTypes ["NFSv4.1"]`(V 값). 트리·base·독립성 모두 `true`, base 쓰기 8가지 `Read-only file system`.
- (b) `test_ac04b_nfsv41_volume_in_another_pool_from_nfsv3_snapshot`: 같은 계정의 두 번째 풀 `e2e-vol-pool2`(Standard, 4 TiB)에 v3 원본 V(Premium 풀)의 스냅샷 S로 `protocolTypes: ["NFSv4.1"]`인 N.
  - N GET: `serviceLevel "Standard"`, `actualThroughputMibps 0.015625`(= 1 GiB × 16 MiB/s/TiB) / V는 `Premium`, `0.0625`. N `exportPolicy` 규칙 `nfsv3: false, nfsv41: true`.
  - v4.1 마운트 `nfs4 rw,...,vers=4.1`, `client_tree_equal_s: true`, `client_base_equal_s: true`, `cat /m/a /m/d/b` = `one b`(S 시점), 새 파일 쓰기 됨. ARM 목록 `["S"]`.
  - v3 마운트(`retry=0,soft,timeo=20,retrans=1`): rc 32, stderr `mount.nfs: requested NFS version or transport protocol is not supported for /m` / `mount: mounting … failed: Protocol not supported`. 기준의 `Protocol not supported` 문구가 그대로 있다(버전 거절로 실패).

### [PASS] AC-05 데이터 (크기)

- 실행: `test_ac05_larger_volume_from_snapshot`. V 1 GiB(v3)의 스냅샷 S로 `usageThreshold` 2 GiB인 N.
- 출력(핵심):
  - 클라이언트 `df -B1`: V 크기 1,021,313,024, N 크기 2,077,229,056(ext4 메타데이터를 뺀 2 GiB). agent 레코드 `size` 2147483648, LV 2147483648.
  - V 크기를 넘는 쓰기: `dd bs=1M count=1200 conv=fsync` → `1258291200 bytes (1.3 GB, 1.2 GiB) copied, 2.98 s`, rc 0. 그 뒤 df used 1,258,291,200.
  - 채우기: `dd if=/dev/zero of=/m/fill bs=1M conv=fsync` → `dd: error writing '/m/fill': No space left on device`, rc 1. df used 2,060,451,840 / avail 0. (기록: dd가 센 바이트 1,762,656,256은 실제 남은 공간 802,160,640보다 크다. NFS 클라이언트가 쓰기를 캐시했다가 write-back 때 ENOSPC를 돌려주기 때문으로 본다 [추론]. 서버 df가 꽉 찬 것은 같다.)
  - 지우고 base 스냅샷 S로 되돌리기 → `Succeeded`. df 크기 2,077,229,056 그대로, agent `size` 2147483648 그대로(S6 B2의 크기 되돌아감이 없다: base를 늘린 뒤 찍었다). `cat /m/a && ls -A /m` = `one / .snapshot a`.

### [PASS] AC-06 데이터 (생성 뒤 원본 변경)

- 실행: `test_ac06_new_volume_survives_source_revert_delete_and_agent_restart`. V(v3) 기록 S1→S2→S3, S2로 N(v3). N 클라이언트 d가 `PROBE`(`/m/A`를 0.2 s마다 읽음)와 `WRITER`(`/m/W`에 0.1 s마다 한 줄 덧붙임)를 돌리는 동안 단계마다 확인했다: 탐침·쓰기 실패 0, N 트리(`W` 뺌) = S2, base 서버·클라이언트 트리 = S2, ARM 목록 `["S2"]`(id·snapshotId·created·상태 같음), 클라이언트 `.snapshot` = `S2`, base 마운트 하나.
- 출력(단계별):

| 단계 | 탐침 읽기 / 실패 / 가장 긴 읽기 | 쓰기 / 실패 / 가장 긴 쓰기 | 트리·base·목록 | N LV origin |
| --- | --- | --- | --- | --- |
| 시작 | 19 / 0 / 0.008 s | 31 / 0 / 0.046 s | 모두 같음 | `snap_9253…`(V의 S2) |
| V를 S1로 되돌림(S2·S3 지워짐, V 목록 `["S1"]`) | 63 / 0 / 0.009 s | 110 / 0 / 0.073 s | 모두 같음 | 빈칸 |
| V의 S1 삭제(V 목록 비어 있음) | 82 / 0 | 146 / 0 | 모두 같음 | 빈칸 |
| V 삭제(V LV 없음, 마운트 없음) | 104 / 0 | 186 / 0 | 모두 같음 | 빈칸 |
| agent 프로세스 재시작 | 135 / 0 | 244 / 0 | 모두 같음 | 빈칸 |
| WSL 재시작 흉내 (agent 멈춤 → 인스턴스 `docker stop` → base·볼륨 언마운트(각 1회) → `lvchange -an`(N `Vwi---tz--`, base `Vri---tz--`) → agent 시작, 중단 3.5 s) | 156 / 0 / 3.017 s | 280 / 0 / 3.085 s | 모두 같음, 새 클라이언트 트리·base = S2 | 빈칸 |

  - 흉내 재시작 뒤 agent가 N과 base를 다시 올렸다: export `[/<N>, /<N>/.snapshot/S2]`, 인스턴스 `running`. 같은 마운트(d)의 쓰기는 agent가 준비된 직후 이어졌다(`write_resumed_after_agent_up_s: 0.0`). 가장 긴 읽기·쓰기 3.0~3.1 s는 중단 동안 hard 마운트가 기다린 것이고 오류는 없었다.
  - 쓰기 파일: 성공한 쓰기 287번, 서버 `W` = `w1`…`w287`(빠짐·중복 없음).
  - 인스턴스 로그: 이 파일 동안 인스턴스 10개, knfsd 재시작 0, 포기 0.

### [PASS] AC-07 계약 (거절)

- 기준: 모두 거절이고 볼륨 행·작업이 생기지 않으며 원본이 그대로다. 재PUT·PATCH의 `snapshotId`.
- 실행: `test_ac07_rejections_create_nothing`. V `vn7`(2 GiB, 스냅샷 S·S9), 다른 계정 `e2e-vol-acct2`의 볼륨 `vn7b`·스냅샷 SB. 거절 전후 비교: 작업 수, 리소스 행 ID 목록, V 트리(서버), V 스냅샷 목록(id·snapshotId·created·상태), LV 목록, 스냅샷 LV 목록.
- 출력(핵심): 거절 전후 `ops [9, 9]`, `unchanged: true`, N GET `404 ResourceNotFound`.

| 경우 | 응답 | 문구 |
| --- | --- | --- |
| `snapshotId: 5` | 400 InvalidRequestContent | "The 'properties.snapshotId' property must be a snapshot resource ID: /subscriptions/{id}/…/snapshots/{snapshot}." |
| `snapshotId: "S"` | 400 InvalidRequestContent | 같음 |
| `snapshotId` = V의 볼륨 ID | 400 InvalidRequestContent | 같음 |
| 다른 계정의 스냅샷 | 400 BadRequest | "The snapshot '…/netAppAccounts/e2e-vol-acct2/…/snapshots/SB' must be in the same NetApp account as the new volume '…/vn7n'." |
| (기준 밖) 다른 리소스 그룹·구독의 ID | 400 BadRequest | 같은 문구 |
| 같은 볼륨 아래 없는 스냅샷 `nope` | 404 ResourceNotFound | "The requested snapshot 'nope' was not found on the volume 'e2e-vol-acct/e2e-vol-pool/vn7'. …"(녹화 R1) |
| `usageThreshold` 1 GiB < V 2 GiB | 400 BadRequest | "The 'properties.usageThreshold' of a volume created from a snapshot must be at least the source volume's 2 GiB." |
| `deleteBaseSnapshot: true` | 400 InvalidRequestContent | "The property 'properties.deleteBaseSnapshot' is not supported by this ANF clone." |
| (기준 밖) `deleteBaseSnapshot: "no"` | 400 InvalidRequestContent | "The 'properties.deleteBaseSnapshot' property must be true or false." |
| `usageThreshold` 4 TiB (풀 4 TiB, V 2 GiB 사용) | 400 BadRequest | "Pool size too small for total volume size." |
| 실패 주입(`snapshots/create` fail)으로 `Failed`인 스냅샷 SF | 400 BadRequest | "Volume cannot be created from snapshot '…/SF' because the snapshot isn't in state succeeded." (작업 수 10 → 10) |
| (기준 밖) 실패 주입(`volumes/patch` fail)으로 `Failed`인 V | 400 BadRequest | "Volume cannot be created from snapshot '…/S' because its volume isn't in state succeeded." (작업 수 11 → 11, V 트리 그대로) |

- 끝난 N(V를 같은 PUT으로 회복한 뒤 `deleteBaseSnapshot: false`로 만듦 — 기준 밖, 받아졌다):
  - N 재PUT에 S9 → `400 BadRequest "SnapshotId cannot be changed."`, N PATCH에 S9 → 같음, 일반 볼륨 V 재PUT에 `snapshotId` 추가 → 같음, (기준 밖) V PATCH에 `snapshotId` 추가 → 같음. 작업 수 13 → 13.
  - 같은 값 재PUT → `200`, 본문 `Updating`, 헤더는 `Azure-AsyncOperation`만, 작업 `Succeeded`. (기준 밖) 대문자로 바꾼 같은 ID → `200` → `Succeeded`. GET의 `snapshotId`·`originatingResourceId`는 저장된 ID 그대로(§9 5번). base 목록 `["S"]`, base LV 하나, `anf_cl_*` 없음.

### [PASS] AC-08 계약 (진행 중 충돌, 원본 보호)

- 기준: N 생성 지연 중 S DELETE·V DELETE·V revert → `409 Conflict`. 원본에 진행 중 작업이 있을 때(S 생성 지연 중 그 스냅샷으로, V PATCH 지연 중 V의 스냅샷으로) N PUT → `409 Conflict`. N이 `Succeeded`가 된 뒤 S DELETE·V revert·V DELETE가 받아진다.
- 실행: `test_ac08_conflicts_and_source_protection`. V `vn8`(스냅샷 S0, S, S9). N 생성은 `{"volumes/create": {"delaySeconds": 20}}` 서버에서.
- 출력(핵심):
  - N PUT 뒤 0.04 s 안의 네 요청(N `Creating`): S DELETE → `409 Conflict` "Cannot delete '…/vn8/snapshots/S' because volume '…/vn8n' is being created from snapshot '…/vn8/snapshots/S'. Wait until it is created, or delete it, and then retry." / V DELETE → `409 Conflict` "Cannot delete '…/volumes/vn8' because volume '…/vn8n' is being created from snapshot '…/S'. …" / V revert(S0으로, S로) → 둘 다 `409 Conflict` "Cannot revert '…/volumes/vn8' because …". 작업 수 7 → 7, V·S 상태 `Succeeded` 그대로.
  - (기준 밖, §9 8번) 같은 동안 V의 다른 스냅샷 S9 DELETE → `202` → `Succeeded`(막지 않는다).
  - N `Creating` → `Succeeded` 뒤: S DELETE `Succeeded` → V를 S0으로 revert `Succeeded` → V DELETE `Succeeded`. 그 뒤 N 클라이언트 `cat /m/a /m/.snapshot/S/a` = `one one`, `.snapshot` = `S`, ARM 목록 `["S"]`.
  - 원본이 바쁠 때: V2 `vn8b`에 T1 생성 지연(15 s) 중 T1으로 N PUT → `409 Conflict` "Cannot create volume '…/vn8c' from snapshot '…/vn8b/snapshots/T1' because an operation is in progress on '…/vn8b/snapshots/T1'. Wait until it is finished, and then retry." / V2 PATCH 지연(15 s) 중 T0으로 N PUT → `409 Conflict` "… because an operation is in progress on '…/volumes/vn8b'. …". 작업 수 14 → 15(사이에 만든 PATCH 작업 하나), `vn8c`·`vn8d` GET `404 ResourceNotFound`, T1·PATCH 작업 `Succeeded`.

### [PASS] AC-09 상태 (실패, 회복, 재시작 안전)

- 기준: (a) 실패 주입 → 작업·N `Failed`, 원본 그대로, 원본 보호 이어짐, 같은 PUT → `Succeeded`(내용 = AC-02, base 하나). (b) agent 중단 → 60 s 뒤 `Failed`, agent를 띄우고 같은 PUT → `Succeeded`. (c) 지연 중 anf-api SIGKILL → 다시 띄우면 `Succeeded`. (d) 통합 테스트: 진행 표시를 남기고 멈춘 지점에서 같은 POST가 끝내고 base 하나, 진행 표시 사라짐. 진행 표시가 있는 볼륨은 시작 복구에서 올라오지 않고 다음 POST로 끝난다.

- (a) `test_ac09a_injected_failure_then_same_put_recovers`: V(기록 S1→S2→S3)의 S2로 N을 `{"volumes/create": {"fail": true}}` 서버에서 PUT → `201` → 작업 `Failed`(폴링 첫 응답부터), `error {"code": "InternalServerError", "message": "Injected fault: volumes/create (ANF_FAULT_INJECTION)."}`, N `Failed`. 원본 그대로(`source_unchanged: true`: V 트리, V 스냅샷 목록, LV·스냅샷 LV 목록 — N LV는 생기지 않음). 원본 보호가 이어진다: S2 DELETE, V DELETE, V revert(S1) 모두 `409 Conflict`("Cannot delete|revert '…' because volume '…/vn9an' is being created from snapshot '…/S2'. …"). 주입을 끈 서버(같은 DB)에서 같은 PUT → `200` `Updating` → `Succeeded`(`Updating` ×3 → `Succeeded`). N: 클라이언트 트리 = S2, base 트리 = S2, `.snapshot` `["S2"]`, ARM 목록 `["S2"]`, agent 스냅샷 `["S2"]`(base 하나), `anf_cl_*` 없음, `originatingResourceId` = S2. 작업 기록 `[("CREATE","Failed"), ("UPDATE","Succeeded")]`. 그 뒤 S2 DELETE `Succeeded`(보호 풀림).
- (b) `test_ac09b_agent_down_then_same_put_recovers`: agent를 멈추고 PUT → `Creating` → 60.3 s 뒤 `Failed`(`InternalServerError`, "Something unexpected occurred … operation id '…'"), anf-api 로그의 `is unreachable` 62줄, N `Failed`, 그동안 S2 DELETE `409 Conflict`. agent를 띄우고 같은 PUT → `Succeeded`, N 결과는 (a)와 같다(트리·base = S2, base 하나, `anf_cl_*` 없음).
- (c) `test_ac09c_anf_api_sigkill_during_injected_delay`: `{"volumes/create": {"delaySeconds": 8}}`로 PUT, 2 s 뒤 N `Creating`, 작업 기록 `[("CREATE","Creating")]`에서 SIGKILL(rc -9). 주입 없이 같은 DB로 다시 띄우자 같은 작업이 `Creating` → `Succeeded`(작업 기록 `[("CREATE","Succeeded")]` 하나). N 결과는 (a)와 같다.
- (기준 밖, 결정 10의 e2e) `test_ac09_extra_agent_sigkill_during_clone_job`: N LV가 호스트에 마운트된 순간 agent SIGKILL. 그때 `anf_cl_name=S2, anf_cl_snap=32fa6363-…, anf_cl_time=2026-11-09T09:06:43Z`, base LV 없음, 인스턴스 없음, 마운트 `ns/<N>`. 2 s 뒤 agent 시작(2.5 s). anf-api 작업 `Creating` → `Succeeded`. agent 로그: 같은 볼륨 POST가 두 번(09:06:47 첫 job, 09:06:52 다시 보낸 job). 끝난 뒤 base LV 하나, `anf_cl_*` 없음, N 트리·base = S2, ARM 목록 `["S2"]`, 작업 기록 `[("CREATE","Succeeded")]`.
- (d) 통합 테스트 `backend/tests/integration/test_flexvol_linux.py` (WSL root, 실제 VG `anf`, knfsd 인스턴스, 클라이언트 컨테이너): 25 passed, skip 0 (353.9 s). 이 기능의 것:
  - `test_volume_from_snapshot_resumes_after_stopping_midway[lvextend-create]`(새 LV만 만든 뒤), `[mount-recover]`(늘린 뒤 마운트 전에 멈춤 → `recover()` 뒤 레코드 `offline`, 즉 시작 복구가 올리지 않음 → 다음 POST가 끝냄), `[resize2fs-create]`(마운트 뒤 fs 늘리기 전), `[chmod-create]`(base 스냅샷 뒤), `[lvchange-create]`(인스턴스까지 띄운 뒤 진행 표시 지우기 전) 모두 PASSED. 각 테스트는 멈춘 뒤 진행 표시가 남고 스냅샷 생성이 "still being created from snapshot"으로 거절되는지, 같은 POST 뒤 `online`·2 GiB·진행 표시 없음·base `["s1"]` 하나·ext4 > 1.5 GiB·클라이언트 내용 `one`·`.snapshot` `s1`·루트 `755`인지 단언한다.
  - `test_volume_from_snapshot_has_its_content_and_is_independent[nfs3|nfs4.1]`, `test_volume_from_snapshot_can_be_larger_and_keeps_its_size` PASSED.
  - 실행 전 → 후 WSL free/cache/available 7063/241/7143 → 5128/2055/6999 MB. 끝난 뒤 `anf-*`·`it-*` 컨테이너 없음, VG `anf`에 `aggr0`만.

### [PASS] AC-10 agent API

- 기준: `POST /api/storage/volumes` + `clone` → `202` + job `success`, GET `online`. 없는 부모 볼륨·스냅샷, 다른 볼륨의 스냅샷, 스냅샷보다 작은 `size` → job `failure`(원인 메시지). `clone` 필드 누락·추가, `is_flexclone: false`, 잘못된 uuid → `400`. 진행 표시가 있는 볼륨에 스냅샷 POST → job `failure`.
- 실행: `test_ac10_agent_clone_api`. ARM으로 V(2 GiB, 스냅샷 S)와 W(스냅샷 T)를 만들고 agent에 직접 요청했다.
- 출력(핵심):
  - 클론 POST → `202`, job `success`(2 s). GET `200` `state: online`, `size 2147483648`, IP `172.30.0.131`. 스냅샷 목록: base `S` 하나(uuid `46b50c4e-…` ≠ 원본 S `11f5af76-…`, `create_time` = 원본). 클라이언트(v3) `cat /m/a` = `one`, `.snapshot` = `S`, 루트 `755`(요청 `unix_permissions: 755`).
  - 실패 job(모두 `202` → `failure`, 그 uuid GET `404`, LV 목록 그대로): 없는 부모 볼륨 "volume 34c9d5b4-… not found" / 없는 스냅샷 "snapshot 50274f0c-… not found" / W의 스냅샷 T "snapshot 0cbec019-… is not a snapshot of volume 1bba68b5-…" / `size` 1 GiB "size 1073741824 is smaller than snapshot 11f5af76-… (2147483648 bytes)".
  - `400`(12가지): `parent_snapshot` 누락, 필드 추가(`split_initiated`), `is_flexclone` 누락 → "clone must have exactly the fields is_flexclone, parent_volume, parent_snapshot"; `is_flexclone: false`·`"true"` → "clone.is_flexclone must be true"; uuid `nope` → "uuid must be a lowercase UUID, got 'nope'"; (기준 밖) 대문자 uuid → 같은 문구; (기준 밖) `parent_snapshot`에 `name` → "clone.parent_snapshot must have exactly the field uuid"; (기준 밖) `clone`이 목록·null → 첫 문구.
  - 진행 표시: 끝난 클론 LV에 `lvchange --addtag`로 `anf_cl_snap/name/time`을 붙여 "진행 표시 지우기 전에 멈춘" 상태를 만들었다(통합 테스트의 `lvchange` 지점과 같은 상태). 스냅샷 POST → job `failure` "volume 6012bc4a-… is still being created from snapshot 11f5af76-…; POST the volume again to finish it". (기준 밖) base 스냅샷 DELETE와 restore PATCH도 같은 문구의 `failure`(§9 2번), 스냅샷 목록 `["S"]` 그대로. 같은 클론 POST → `success`, 진행 표시 사라짐, 그 뒤 스냅샷 POST `success`, 목록 `["S", "s9"]`.

계약 파일 실행: `contract1` 8 passed (367 s). 전 → 후 WSL free/cache/available 7075/239/7154 → 5866/1341/7032 MB, Windows 여유 5,875,700 → 5,966,192 KB. 남은 컨테이너·LV 없음, 포트 비어 있음, teardown `thin_data_percent 0.00`. 인스턴스 19개 중 하나(`vn8b`, AC-08 둘째 부분의 일반 볼륨)가 진입점의 "client tracking did not start" 재시작을 한 번 했다(serving 1, 포기 0). 스냅샷 사이클에 들어간 진입점 동작이고 이 기능의 경로가 아니다.

### [PASS] AC-11 회귀

- 기준: 계정·풀·볼륨·스냅샷·되돌리기 e2e(`backend/tests/e2e`의 모든 `*_live.py`)와 통합 테스트, 단위·계약 테스트가 새 코드에서 통과한다(skip 0).
- 실행: `backend/tests/e2e`의 `test_*_live.py`는 14개다. 이 기능의 2개는 data1·contract1(위 실행 표)로 돌렸고, 나머지 12개는 `regress.sh`로 한 파일씩 돌렸다. 파일마다 앞에서 `sync; echo 3 > /proc/sys/vm/drop_caches`를 하고 `run.sh`(위 실행 방법)로 실행한 뒤, 남은 컨테이너·LV·포트를 확인했다. 출력은 WSL `/root/e2e-logs/reg-<파일>.out`·`.jsonl`·`.run`, 요약은 `/root/e2e-logs/regress-summary.txt`.
- e2e 회귀 결과 (2026-11-09 09:14:32Z~09:44:20Z, 모두 `rc=0`, 출력에 `SKIPPED`·`FAILED` 없음):

| 파일 | 결과 | 시간 | WSL `free -m` 전 → 후 (free / buff·cache / available) | 끝난 뒤 남은 것 |
| --- | --- | --- | --- | --- |
| `test_netapp_account_live.py` | 16 passed | 2 s | 7059/243/7140 → 6964/308/7112 | 없음 |
| `test_netapp_account_lro_faults_live.py` | 8 passed | 38 s | 7025/242/7106 → 6958/309/7107 | 없음 |
| `test_capacity_pool_live.py` | 30 passed | 3 s | 7030/242/7110 → 6943/309/7091 | 없음 |
| `test_capacity_pool_lro_faults_live.py` | 9 passed | 69 s | 7005/242/7086 → 6884/345/7068 | 없음 |
| `test_volume_contract_live.py` | 7 passed | 109 s | 6979/251/7069 → 5596/1639/7057 | 없음 |
| `test_volume_data_live.py` | 7 passed | 192 s | 7000/253/7091 → 3487/3672/6953 | 없음 |
| `test_volume_recovery_live.py` | 7 passed | 165 s | 6915/255/7008 → 6407/764/7001 | 없음 |
| `test_snapshot_contract_live.py` | 5 passed | 107 s | 6917/256/7011 → 6457/723/7012 | 없음 |
| `test_snapshot_data_live.py` | 8 passed | 173 s | 6932/256/7026 → 4986/2189/6986 | 없음 |
| `test_snapshot_recovery_live.py` | 5 passed | 254 s | 6972/248/7057 → 6430/752/7011 | 없음 |
| `test_snapshot_revert_contract_live.py` | 11 passed | 508 s | 6956/248/7042 → 5657/1485/6956 | 없음 |
| `test_snapshot_revert_data_live.py` | 5 passed | 160 s | 6953/250/7040 → 6388/788/7005 | 없음 |

  "남은 것 없음"은 `anf-*` 컨테이너 없음, VG `anf`에 `aggr0`만, 포트 8080·8090 비어 있음이다. 되돌리기 데이터 출력에 `ERROR` 한 줄이 있는데, 위임을 켠(`fs.leases-enable=1`) 상태에서 agent가 시작을 거절한 traceback이다. 그 시험(되돌리기 AC-10)이 기대하는 거절이고 PASSED다. 끝난 뒤 `sysctl -n fs.leases-enable` = `0`.
- Windows 여유 물리 메모리(회귀 중 표본): 시작 전 6,110,024 KB → 6,847,240(풀 시험 중) → 3,938,036·3,914,564(`test_volume_data_live.py` 중, 가장 낮음) → 4,006,016 → 6,277,412 → 6,409,404 → 5,091,616 → 6,217,916 → 6,348,948 → 6,257,664 KB(끝). 가장 낮을 때의 WSL 메모리는 대부분 페이지 캐시(3.6 GB)였고, available은 6.9 GB 아래로 내려가지 않았다. 메모리 때문에 막힌 시험은 없다.
- 통합 테스트: AC-09 (d)의 실행(`backend/tests/integration`, root) 25 passed, skip 0.
- 단위·계약 (Windows, `.venv-win`): `.venv-win\Scripts\python -m pytest backend/tests/unit backend/tests/contract` → 817 passed, 0 skipped (124 s).
- 단위·계약 (WSL, 일반 사용자 `mkimhome1`): `~/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider backend/tests/unit backend/tests/contract -q` → 817 passed in 72.39 s, skip 줄 없음(`addopts`의 `-rfEs`가 skip을 출력한다).
- 합계: e2e 14개 파일 131 passed(이 기능 13 = data1 5 + contract1 8, 회귀 118), 통합 25 passed, 단위·계약 817 passed(Windows와 WSL 각각). 모두 skip 0, 실패 0.

## 기준 밖 관찰

판정에 넣지 않은 관찰이다. 어느 것도 FAIL 근거가 아니다.

1. **새 볼륨의 ext4 UUID가 원본과 같다.** N의 LV는 S의 thin 스냅샷에서 나오므로 `blkid`의 ext4 UUID가 V와 같다(AC-02 출력). 설계 결정 6이 받아들인 동작이다. 두 볼륨은 서로 다른 마운트 지점·인스턴스·`fsid`를 쓰므로 클라이언트에서 섞이지 않았다(AC-03 독립성). 같은 호스트에서 UUID로 마운트하는 도구를 쓰면 구분할 수 없다는 점은 개념 문서에 적을 만하다.
2. **base 스냅샷 안의 쓰기 거절 문구가 프로토콜마다 다르다.** NFSv3는 덮어쓰기 계열(append, `dd conv=notrunc`, `>`)이 `Permission denied`, 나머지가 `Read-only file system`이다. NFSv4.1은 모두 `Read-only file system`이다. 둘 다 실패이고 내용은 바뀌지 않았다(AC-03). v3 클라이언트가 쓰기 전에 ACCESS로 권한을 묻고 서버가 ro 마운트에서 쓰기 권한을 주지 않기 때문으로 보인다 [추정].
3. **용량을 채울 때 `dd`가 실제 남은 공간보다 많이 썼다고 보고했다.** AC-05에서 남은 공간 802 MB에 `dd`가 1.76 GB를 센 뒤 `No space left on device`로 끝났다. NFS 클라이언트가 쓰기를 캐시에 받았다가 write-back 때 ENOSPC를 돌려받기 때문으로 보인다 [추정]. 판정은 `df`와 오류 문구로 했다.
4. **contract1의 인스턴스 하나가 진입점 재시작을 한 번 했다.** AC-08 둘째 부분의 일반 볼륨 인스턴스(`vn8b`)가 "client tracking did not start"로 knfsd를 한 번 다시 띄웠다(serving 1, 포기 0). 스냅샷 사이클의 진입점 동작이고 이 기능의 경로가 아니다. 회귀 12개 파일의 e2e 출력·JSON 로그에는 이 문구가 없다(`grep` 0건). 다만 e2e 출력이 인스턴스 로그를 모두 담지는 않으므로, 회귀 중 재시작이 한 번도 없었다고 단정하지는 않는다.
5. **AC-04 (b)의 다른 풀 볼륨은 Standard 서비스 수준의 처리량을 받는다.** `actualThroughputMibps` 0.015625(= 1 GiB × 16 MiB/s/TiB) vs V(Premium) 0.0625. 새 볼륨이 원본이 아니라 자기 풀의 서비스 수준을 따른다는 확인이다(기준 문구에는 처리량 값이 없다).

## 정리

- 끝난 뒤(2026-11-09 09:46Z): `anf-*`·`anfe2e-*`·`it-*` 컨테이너 없음, VG `anf`에 `aggr0`(Data 0.00%)만, `ns/`·`exports/` 비어 있음, 포트 8080·8090 비어 있음, uvicorn·pytest 프로세스 없음, `fs.leases-enable` = `0`. `/var/lib/anf-clone/ns`의 rshared 자기 바인드 마운트는 agent가 시작할 때 만드는 것이라 그대로 두었다.
- 메모리(끝): WSL free 6287 / available 7067 MB, Windows 여유 6,320,572 KB.
- 유휴 종료 방지 세션(`sleep 86400`)을 멈췄다.
- 커밋하지 않았다.

## 추가한 검증 스크립트

모두 새 파일이고 커밋하지 않았다. ruff 0.14.0 `All checks passed!`.

- `backend/tests/e2e/restore_live.py`: 도우미(`snapshotId` PUT, 다른 풀 스냅샷 목록, 진행 표시 `anf_cl_*`·origin·ext4 UUID 관찰, base 스냅샷 쓰기 시도 목록, 대기 함수).
- `backend/tests/e2e/test_restore_new_volume_data_live.py`: AC-02/03/04a(v3·v4.1 매개변수), AC-04b, AC-05, AC-06.
- `backend/tests/e2e/test_restore_new_volume_contract_live.py`: AC-01, AC-07, AC-08, AC-09 (a)(b)(c), AC-09 기준 밖(클론 중 agent SIGKILL), AC-10.
- 실행 도구(저장소 밖, 세션 scratchpad): `precheck.sh`, `agent_once.sh`, `run.sh`, `run_int.sh`, `regress.sh`.
