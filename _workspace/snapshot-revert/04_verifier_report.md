# snapshot-revert 검증 보고서 — 1회차

- 검증일: 2026-11-08 (현지). 로그 시각은 UTC 2026-11-09 04:52~ 이다.
- 검증 대상 코드: 제품 코드 내용 해시 시작 `8cec38bf9281c5de5db282fa3351e7ca815096822f23e4b4325ccf3cb43f70b5`, 끝 `8cec38bf9281c5de5db282fa3351e7ca815096822f23e4b4325ccf3cb43f70b5`(같음). 리더가 준 값(커밋 `597e5a0`)과 같다. `git rev-parse HEAD` = `e6fa0e5c27a5b5dc21bcfc8b5e2197f233b8748c` (문서 커밋. `git diff --stat 597e5a0 -- backend pyproject.toml scripts`는 비어 있다).
  해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
- 미커밋 변경: 리더의 `_workspace/snapshot-revert/00_progress.md`, `docs/feature-status.md`, `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`(검증 시작 전부터). 이번 회차가 더한 검증 스크립트(해시 밖): `backend/tests/e2e/revert_live.py`, `backend/tests/e2e/test_snapshot_revert_data_live.py`, `backend/tests/e2e/test_snapshot_revert_contract_live.py`. 제품 코드는 고치지 않았다.
- 이번 회차 범위: 전체 (AC-01~AC-11). 기준 밖 관찰 셋을 따로 적었다(§기준 밖 관찰).

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `Ubuntu` Running (VERSION 2). 커널 `6.18.54.1-microsoft-standard-WSL2` |
| 커널 모듈 | `nfsd`, `dm_thin_pool` 로드됨 (`lsmod`) |
| Docker | Ubuntu 안 Docker Engine `server=29.1.3 os=linux`, `readlink /usr/bin/docker` 비어 있음 (Desktop 연동 아님) |
| 이미지·네트워크 | `anf-nfs-server`, `anf-nfs-client` 있음. `anf-vnet` = `172.30.0.0/24 172.30.0.0/25` |
| 위임 꺼짐 | `sysctl -n fs.leases-enable` = `0`, `/etc/sysctl.d/90-anf-clone.conf` = `fs.leases-enable = 0` |
| 창 도구 | `/usr/sbin/iptables`(v1.8.10, nf_tables 백엔드: xtables 잠금 경합 없음), `/usr/bin/nsenter` |
| 시작 상태 | LV는 `aggr0`만, `anf-nfs-*` 컨테이너 없음, uvicorn 없음, `ns/`·`exports/` 비어 있음 |
| 서비스 | agent(root, 127.0.0.1:8090)와 anf-api(일반 사용자 `mkimhome1`, 127.0.0.1:8080, `ANF_MIN_VOLUME_SIZE_GIB=1`)는 e2e 픽스처가 시험 파일마다 직접 띄우고 멈췄다(`dataplane_live.py`) |

모든 점검이 통과해 환경 때문에 UNVERIFIED로 둔 항목은 없다.

## 결과 요약

PASS 11 / FAIL 0 / UNVERIFIED 0

- 제품 결함은 찾지 못했다. 실패한 실행은 둘 다 내 검증 스크립트의 문제였고(기대값의 `lost+found`, AC-08c 탐침을 너무 일찍 읽음), 고친 뒤 다시 돌려 통과했다.
- FR-06의 기록(되돌리기 전에 마운트한 클라이언트): 다시 마운트할 필요가 없다. 되돌리는 동안 오류 없이 3.35~3.36 s 멈춘다(서버 쪽 창 1.95 s). S2에 있던 파일·디렉터리는 fd·cwd까지 S2 내용으로 이어지고, S2 뒤에 만든 것의 fd·cwd는 `Stale file handle`, 경로는 `No such file or directory`다.
- 리더가 알아 둘 관찰(결함 아님): agent가 창 안에서 죽으면 그 볼륨의 hard 마운트 클라이언트는 agent가 돌아올 때까지 멈추고, 그 뒤 TCP 재전송 대기만큼 더 멈춘다(73.6 s 중단 → 117 s 멈춤, 오류 0). §기준 밖 관찰 2·3.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1회차 (이 보고서) |
| AC-02 | PASS | 1회차 |
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

모두 WSL에서 root로, 저장소 루트에서 실행했다. 판정 근거(`note`)는 `-s` 출력과 `ANF_E2E_LOG`(JSON Lines)에 남는다.

```
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && \
  PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/tmp/<log>.jsonl \
  /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider \
  backend/tests/e2e/test_snapshot_revert_data_live.py backend/tests/e2e/test_snapshot_revert_contract_live.py -v -s'
```

| 실행 | 결과 |
| --- | --- |
| `test_snapshot_revert_data_live.py` (AC-02·03·08d, AC-04 ×2, AC-10) | 5 passed (158.9 s). 그 전 실행 1회는 내 기대값 오류로 2 failed: 볼륨 루트에 `lost+found`가 있다고 적었는데 agent의 루트 초기화가 지운다. 트리 비교(호스트·클라이언트)는 그 실행에서도 모두 같았다 |
| `test_snapshot_revert_contract_live.py` 1차 (AC-01·05·06·07 ×2·08a·08ab·08c ×2·09) | 9 passed, 1 failed (`08c[past-retry]`). 실패한 것은 기준 밖으로 내가 더한 탐침 단언(아래 AC-08 참고). 계측을 더해 다시 돌렸다 |
| 같은 파일 `-k "ac08c or extra"` 2차 | 3 passed (199.2 s): `08c[restart]`, `08c[past-retry]`, 기준 밖 `extra` |
| AC-10 다시 실행 (클라이언트 정리 순서를 고친 뒤, §정리) | 1 passed (24.2 s), 남은 컨테이너 0 |
| AC-11 e2e 회귀 10개 파일 | 102 passed, skip 0 (1047.7 s) |
| AC-11 통합 (`backend/tests/integration -m dataplane`) | 17 passed (259.8 s) |
| 리눅스 단위·계약 (`backend/tests/unit backend/tests/contract`, 일반 사용자) | 741 passed, skip 0 (63 s) |

## 항목별 결과

### [PASS] AC-01 POST revert의 계약과 상태 (API 계약, 상태 전이)

- 기준: `Succeeded` 볼륨에 스냅샷 ARM ID로 POST revert → `202`, 본문 없음, `Azure-AsyncOperation`·`Location`(`Retry-After` 없음). 폴링하면 `Reverting`(`action: POST`, `resourceName` = 볼륨 ID) → `Succeeded`. 지연 주입 중 볼륨 GET `Reverting`. 끝난 뒤 `Location` 조회 `200` + 볼륨 본문(`Succeeded`), 볼륨 GET `Succeeded`.
- 실행: `test_ac01_revert_contract_and_states`. anf-api `ANF_FAULT_INJECTION={"volumes/post": {"delaySeconds": 5}}`. 볼륨 `vr1`(NFSv3)에 AC-02의 기록(S1 → S2 → S3)을 만들고 S2로 되돌렸다.
- 출력(핵심):
  - 응답 `202`, 본문 `""`, `content-length: 0`. 헤더: `azure-asyncoperation: http://127.0.0.1:8080/subscriptions/0e2e…/providers/Microsoft.NetApp/locations/westus2/operationResults/fb0c1b12-…?api-version=2026-08-01`, `location`은 같은 URL + `&operationResultResponseType=Location`, `x-ms-request-id`, `x-ms-correlation-request-id`. `retry-after` 없음.
  - 지연 중 볼륨 GET `provisioningState: Reverting`. 작업 상태 `{"status": "Reverting", "percentComplete": 0.0, "properties": {"resourceName": "…/volumes/vr1", "action": "POST"}}`.
  - 폴링 순서 `Reverting` ×11 → `Succeeded`(`percentComplete: 100.0`, 작업 10.14 s = 지연 5 s + 되돌리기).
  - `Location` 조회 `200`, 본문 `id` = 볼륨 ID, `provisioningState: Succeeded`. 볼륨 GET `Succeeded`.
  - 데이터: 볼륨 트리 = 되돌리기 전 S2 트리, S1·S2 트리와 `snapshotId`·`created` 그대로, S3 `404`, `.snapshot` = `S1 S2` (`assert_reverted_to_s2`).

### [PASS] AC-02 NFSv3 데이터 (데이터 효과)

- 기준: 쓰기 → S1 → 바꿈 → S2 → 지우기·덮어쓰기·새 파일·디렉터리 → S3 → 또 바꿈. S2로 되돌리면 볼륨 트리 체크섬 = 되돌리기 전 S2 트리 체크섬. S1·S2는 ARM 목록과 `.snapshot`에 남고 트리·`snapshotId`·`created`가 그대로. S3는 GET `404`, 목록에 없음, `.snapshot/S3` `No such file or directory`, 호스트에 LV·마운트·export 줄 없음. `.snapshot`에는 `S1`·`S2`만. 되돌린 볼륨에 쓰고 새 스냅샷을 만들 수 있다.
- 실행: `test_ac02_ac03_revert_restores_snapshot_and_deletes_newer[AC-02-NFSv3-3]`. 기록(`revert_live.STEPS`): S1 = `A=a1, K=k1, d1/X, d1/sub/Y=y1, big(8 MiB 난수)`; S2 = `A=a2, K+=k2, d2/Z=z2, d1/X 삭제`; S3 = `A 삭제, K="over"(같은 inode 자르고 쓰기), big 같은 자리 8 MiB 덮어쓰기, N, d3/Q`; 그 뒤 `N=n4, M=m4, d2 삭제, Y=y4`. 트리 = 파일별 sha256 + 디렉터리 목록(최상위 `.snapshot` 제외), 호스트(`NS/<토큰>`)와 클라이언트(`find` + `sha256sum`) 양쪽에서 만들었다.
- 출력(핵심):
  - 작업 `Reverting` ×6 → `Succeeded`, 5.15 s.
  - `tree_equal_s2: true`(호스트), `client_tree_equal_s2: true`(새로 마운트한 클라이언트), `client_s2_equal: true`, `s1_same: true`, `s2_same: true`. 되돌리기 전 볼륨 트리와 S2 트리는 달랐다(사전 단언).
  - 클라이언트(되돌리기 전부터 마운트): `cat /m/A /m/K /m/d2/Z` = `a2 / k1 k2 / z2`, `ls /m` = `A K big d1 d2`, `ls /m/d1` = `sub`, `ls -A /m/.snapshot` = `S1 S2`.
  - 없어진 것: `cat: /m/N: No such file or directory`, `cat: /m/d1/X: …`, `ls: cannot access '/m/d3': …`, `ls: cannot access '/m/.snapshot/S3': No such file or directory`.
  - ARM 목록 `S1 S2`(전 `S1 S2 S3`), S1·S2의 `(id, snapshotId, created, provisioningState)` 그대로. S3 GET `404 ResourceNotFound` + 녹화 문구 "The requested snapshot 'S3' was not found on the volume 'e2e-vol-acct/e2e-vol-pool/vr2'. …".
  - 호스트: 스냅샷 LV 둘(S1·S2), S3 LV 없음, 마운트 `…/.snapshot/S1`, `…/.snapshot/S2`, export 파일과 인스턴스 etab 모두 `/<토큰>`, `/<토큰>/.snapshot/S1`, `/<토큰>/.snapshot/S2`, `.snapshot` 디렉터리 `S1 S2`, 볼륨 LV 하나(`vol_<uuid>`, `_new` 없음), 태그 `anf_rv_done=<작업 ID>`만(진행 표시 없음), DROP 규칙 없음.
  - 되돌린 뒤 `echo after > /m/after` 성공, 스냅샷 S4 생성, 다른 클라이언트에서 `cat /m/after /m/.snapshot/S4/after` = `after after`, `.snapshot` = `S1 S2 S4`.

### [PASS] AC-03 NFSv4.1 데이터 (데이터 효과)

- 실행: 같은 테스트 `[AC-03-NFSv4.1-4.1]`.
- 출력(핵심): 작업 5.16 s. `tree_equal_s2`, `client_tree_equal_s2`, `client_s2_equal`, `s1_same`, `s2_same` 모두 `true`. 클라이언트 읽기·없어진 것·ARM 목록·S3 `404`·호스트 관찰이 AC-02와 같다(`anf_proto=nfs4.1`). 새 쓰기와 S4도 같다.

### [PASS] AC-04 되돌리기 전에 마운트한 클라이언트 (데이터 효과, FR-06의 기록)

- 기준: v3·v4.1 각각 마운트 유지, 되돌리는 동안 0.2 s 탐침이 한 번도 실패하지 않음(가장 긴 멈춤 기록), 되돌린 뒤 1 s 안에 다시 마운트 없이 `ls`·기존 파일이 S2 시점, 되돌리기 전에 연 fd(S2에 있던 파일)가 S2 내용, S2 뒤에 만든 파일의 fd와 디렉터리 cwd는 `Stale file handle`·그 경로는 `No such file or directory`, S2에 있던 디렉터리의 cwd는 쓸 수 있음, 쓰기가 됨, 쓰기를 계속하는 클라이언트의 결과 기록.
- 실행: `test_ac04_mounted_client_follows_revert_without_remount[NFSv3-3]`, `[NFSv4.1-4.1]`. 기본 hard 마운트(v3는 `nolock`). 클라이언트 a: `P=p1, B=b1, olddir/E=e1, W=base` → S2 → `B=b2`(덮어쓰기), `D`, `n/F`, `olddir/E2` 생성, 읽어 캐시에 올림. a 안에서 `HOLDER`(fd 3 = `/m/B`, fd 4 = `/m/D`, cwd `/m/olddir`, cwd `/m/n`), `PROBE`(`cat /m/P` 0.2 s마다, 시작·끝 시각 기록), 클라이언트 w에서 `WRITER`(`echo w$i >> /m/W` 0.1 s마다). 호스트 스레드가 인스턴스 netns의 DROP 규칙을 0.02 s마다 봤다(`RuleWatch`). 작업 상태는 0.1 s마다 폴링했다.
- 출력(핵심):

| 관찰 | NFSv3 | NFSv4.1 |
| --- | --- | --- |
| 작업 시간 (startTime → endTime) | 4.15 s | 4.15 s |
| 서버 쪽 창 (DROP 규칙이 있던 시간) | 1.956 s (POST 0.69 s 뒤에 열림) | 1.952 s (POST 0.73 s 뒤) |
| 탐침 | 39회, 실패 0, 내용 늘 `p1` | 38회, 실패 0, 내용 늘 `p1` |
| **가장 긴 멈춤** (탐침 한 번) | **3.364 s** (창이 열린 0.15 s 뒤 시작) | **3.352 s** (0.16 s 뒤) |
| 창이 닫힌 뒤 `Succeeded`를 본 시각 | +1.51 s | +1.49 s |
| `Succeeded`를 본 뒤 확인 명령 끝 | 0.246 s | 0.264 s |
| `ls /m` / `cat B P olddir/E` | `B P W olddir` / `b1 p1 e1` | 같음 |
| `cat /m/D`, `ls /m/n` | 둘 다 `No such file or directory` | 같음 |
| 되돌리기 전 연 fd `B` | `b1`, rc 0 | `b1`, rc 0 |
| 되돌리기 전 연 fd `D` | `cat: -: Stale file handle`, rc 1 | 같음 |
| cwd `/m/olddir` | `ls` = `E`(E2 없음) rc 0, `cat E` = `e1` rc 0 | 같음 |
| cwd `/m/n` | `ls: cannot open directory '.': Stale file handle`, `cat: F: Stale file handle` | 같음 |
| 되돌린 뒤 쓰기 `echo new > /m/X && cat /m/X` | `new` | `new` |
| 마운트 줄 (`/proc/mounts`) | 전후 같음 (`vers=3,hard,nolock,timeo=600,retrans=2`) | 전후 같음 (`vers=4.1,hard`) |
| 쓰는 클라이언트 | 67회, 실패 0, 가장 긴 쓰기 3.448 s | 67회, 실패 0, 가장 긴 3.35 s |
| 되돌린 뒤 `W` | `base` + `w27`~`w67` (42줄, NUL 0바이트, 호스트도 같음) | 같음 (`w27`~`w67`) |

  - 쓰는 클라이언트의 결과: 창 전에 쓴 `w1`~`w26`(S2 뒤의 쓰기)은 되돌리기로 사라졌다. `w27`은 창이 열린 0.09 s 뒤 시작해 3.45 s 멈췄다가 성공했고, 되돌린 볼륨에 들어갔다. 그 뒤 쓰기는 모두 이어 붙었다. 구멍(NUL)은 없었다. 설계 §3 "아직 확정하지 않은 것"의 추론(창 동안 도착한 쓰기는 되돌린 볼륨에 들어간다)과 맞다.
  - S5(merge 방식)는 2~5 s 멈춤이었다. 교체 방식은 창 1.95 s, 클라이언트 멈춤 3.35~3.36 s다. 멈춤이 창보다 긴 이유는 아래 "측정값"의 TCP 재전송 계산 참고 [추론].

### [PASS] AC-05 거절 (API 계약)

- 기준: 아래가 모두 거절이고 작업이 생기지 않으며 볼륨 트리와 스냅샷 목록이 그대로다.
- 실행: `test_ac05_rejections_create_no_operation`. 작업 수는 상태 DB `operations` 행 수(일반 사용자 권한으로 읽음).
- 출력(핵심):

| 요청 | 응답 | 문구 |
| --- | --- | --- |
| 본문 `[]` | `400 InvalidRequestContent` | "The request content must be a JSON object." |
| `{"snapshotId": <S1>, "extra": 1}` | `400 InvalidRequestContent` | "Value received for an unknown property 'extra'." |
| `{}` | `400 InvalidRequestContent` | "The 'snapshotId' property is required and must be a snapshot resource ID." |
| `{"snapshotId": 5}` | `400 InvalidRequestContent` | 같음 |
| `snapshotId` = 볼륨 ID / `"S1"` | `400 InvalidRequestContent` | "The 'snapshotId' property must be a snapshot resource ID: /subscriptions/{id}/…/snapshots/{snapshot}." |
| 다른 볼륨(`vr5o`)의 스냅샷 `T1` | `400 BadRequest` | "The snapshot '…/volumes/vr5o/snapshots/T1' does not belong to the volume '…/volumes/vr5'." |
| 같은 볼륨 아래 없는 `nope` | `404 ResourceNotFound` | 녹화 문구 "The requested snapshot 'nope' was not found on the volume 'e2e-vol-acct/e2e-vol-pool/vr5'. …" |
| 없는 볼륨 `nope` | `404 ResourceNotFound` | "The resource with identifier '…/volumes/nope' is not found." |
| `snapshots/create` 실패 주입으로 `Failed`가 된 `SF`로 | `400 BadRequest` | "Volume cannot be reverted to snapshot '…/snapshots/SF' because the snapshot isn't in state succeeded." |
| `volumes/patch` 실패 주입(`PATCH {"tags"}` → `202` → `Failed`)으로 `Failed`가 된 볼륨 | `400 BadRequest` | "Volume cannot be reverted when it isn't in state succeeded." |

  - 작업 수: 본문·조회 거절 전후 8 → 8, Failed 스냅샷 거절 전후 9 → 9, Failed 볼륨 거절 전후 10 → 10 (늘어난 것은 주입한 스냅샷 생성·PATCH 작업뿐). `tree_same: true`, `snapshots_same: true` (S1~S3의 정체성 그대로).

### [PASS] AC-06 진행 중 충돌 (API 계약)

- 실행: `test_ac06_conflicts_while_reverting`. `volumes/post` 지연 15 s. 일곱 요청을 0.04 s 안에 보냈고, 그동안 볼륨은 `Reverting`이었다.
- 출력(핵심):
  - 다시 revert, 볼륨 PUT(같은 본문), PATCH(`tags`), DELETE → 모두 `409 RequestConflict` "Cannot modify resource with id '…/volumes/vr6' because the resource entity provisioning state is not terminal. Please wait for the provisioning state to become terminal and then retry the request."
  - 새 스냅샷 `S9` PUT → `400 BadRequest` "Snapshot cannot be created on a volume that isn't in state succeeded." (뒤에 S9 GET `404`.)
  - 기존 `S1` 다시 PUT, 기존 `S3` DELETE → `409 Conflict` "Cannot change snapshot '…/snapshots/S1' because its parent volume '…/volumes/vr6' is being reverted." (S3도 같은 모양)
  - 작업 수 그대로. 진행 중이던 revert는 `Succeeded`, 결과는 AC-02와 같다(트리 = S2, S1·S2 그대로, S3 `404`, `.snapshot` = `S1 S2`).
  - `snapshots/create` 지연 15 s로 S4 PUT(`201`, `Creating`) 중 revert → `409 Conflict` "Cannot revert volume '…/volumes/vr6' because an operation is in progress on its snapshot '…/snapshots/S4'. Wait until it is finished, and then retry." 작업 수 8 → 8. S4는 뒤에 `Succeeded`, 볼륨 `Succeeded`.

### [PASS] AC-07 실패와 회복 (상태 전이)

- 실행: `test_ac07_injected_failure_then_put_recovers`, `test_ac07_agent_down_fails_after_retry_then_put_recovers`.
- 출력(핵심):
  - 주입(`volumes/post` `fail`): 작업 `Failed`, `error: {"code": "InternalServerError", "message": "Injected fault: volumes/post (ANF_FAULT_INJECTION)."}`, 볼륨 `Failed`. 볼륨 트리·ARM 스냅샷 목록·스냅샷 LV 그대로, 진행 표시 태그 없음, 클라이언트 `cat /m/N /m/M` = `n4 m4`(되돌리기 전 데이터). 주입 없는 서버에서 같은 볼륨 PUT → `200`, `Updating` → `Succeeded`, 그 뒤 revert `Succeeded`, 결과 AC-02와 같음. 작업 기록 `CREATE Succeeded, POST Failed, UPDATE Succeeded, POST Succeeded`.
  - agent 중단: revert → 60.3 s 뒤 작업 `Failed`(`InternalServerError`, 공통 문구 "Something unexpected occurred … provide the operation id '…'."), 볼륨 `Failed`, anf-api 로그 "is unreachable" 62줄. 트리·스냅샷 LV 그대로. agent를 띄우고 볼륨 PUT → `Succeeded` → revert `Succeeded`, 결과 AC-02와 같음.

### [PASS] AC-08 재시작 안전 (상태 전이)

- (a) 지연 중 SIGKILL — `test_ac08a_anf_api_sigkill_during_injected_delay` (`volumes/post` 지연 8 s): 2 s 뒤 볼륨 `Reverting`, SIGKILL(rc `-9`), 그때 데이터 그대로, DB 작업 `POST Reverting`. 주입 없이 같은 DB로 다시 띄우자 같은 작업 ID가 `Succeeded`, 작업 기록 `CREATE Succeeded, POST Succeeded`(POST 하나), 결과 AC-02와 같음.
- (a, 추가) agent job 중 SIGKILL — `test_ac08ab_…`: S3 마운트가 사라진 순간(agent가 되돌리기를 시작함) anf-api를 SIGKILL했다. 그때 호스트: 옛 LV에 `anf_rv_req`·`anf_rv_snap`, 새 LV `_new`(`anf_rv_new=1`), DROP 규칙 있음(창 안). 다시 띄운 anf-api에서 작업 `Succeeded`, 결과 AC-02와 같음, 태그 `anf_rv_done=<작업 ID>`만.
- (b) 같은 키 — 같은 테스트: 첫 되돌리기 뒤 클라이언트가 `/m/after`를 쓰고, agent에 `PATCH /api/storage/volumes/<uuid>?restore_to.snapshot.uuid=<S2>&restore_to.request_uuid=<작업 ID>`를 두 번 보냈다(그대로, 그리고 agent 재시작 뒤 job 표가 빈 상태). 둘 다 `202` + job `success`(0~1 s), `cat /m/after` = `after`, 볼륨 트리·볼륨 LV 태그·스냅샷 LV 그대로, DROP 규칙 없음. 끝난 job은 같은 키여도 새 job이 되므로(`jobs.py`는 끝나지 않은 job만 묶는다) 이것은 LVM 태그 `anf_rv_done`에 의한 멱등이다.
- (c) 중간 상태 복구:
  - 통합 테스트 `test_restore_resumes_after_stopping_midway`의 다섯 경우(새 LV 만들기 전 + 같은 키 PATCH, 창 안 마운트 전 + agent 재시작, 같은 상태 + 볼륨 POST, 옛 LV 삭제 전 + 같은 키 PATCH, 이름 넘겨받기 전 + agent 재시작): 다섯 모두 PASSED (AC-11의 통합 실행). 각 경우 `.snapshot/s2/a` = `two`, s2 레코드 그대로, 볼륨 LV 하나, `anf_rv_done=<키>`, 차단 규칙 없음을 단언한다. "볼륨 POST(보장)도 같은 상태를 끝낸다"는 이 통합 테스트(`mount-0-create`)로만 확인했다: e2e에서는 agent가 떠 있는 채 진행 표시가 남는 상태를 결함 주입 없이 만들 수 없다(agent가 죽으면 시작 복구가 먼저 끝낸다).
  - 실환경(e2e) `test_ac08c_agent_killed_inside_the_window`: S2 마운트가 사라진 순간(창 안, S2 언마운트 직후) agent를 SIGSTOP → 0.5 s 뒤 상태 기록 → SIGKILL. 멈춘 상태: 볼륨 LV `vol_<uuid>`와 `vol_<uuid>_new`가 함께 있음, 진행 표시 `anf_rv_req`·`anf_rv_snap`(두 LV) + `anf_rv_new=1`, DROP 규칙 있음, 마운트는 볼륨과 `.snapshot/S1`만(S2 없음). 두 변형:

| 변형 | restart (NFSv4.1) | past-retry (NFSv3) |
| --- | --- | --- |
| agent가 내려가 있던 시간 | 8.7 s | 73.6 s |
| anf-api 작업 | `Succeeded` (agent가 다시 뜬 뒤 재시도로 같은 키를 다시 보냄) | 죽인 68.3 s 뒤 `Failed`, 볼륨 `Failed`, 그때 ARM 목록 `S1 S2 S3`(agent는 S3를 이미 지웠다), DROP 규칙 남음 |
| agent 시작 복구 뒤 | — | ARM 목록 아직 `S1 S2 S3`, 볼륨 `Failed` → 볼륨 PUT `Succeeded` → 목록 `S1 S2`, S3 `404` (§9-5 행 맞추기) |
| 작업 기록 | `CREATE, POST Succeeded` | `CREATE, POST Failed, UPDATE Succeeded` |
| 결과 | 트리 = S2, S1·S2 그대로, `.snapshot` = `S1 S2`, LV 하나, 태그 `anf_rv_done=<키>`만, DROP 규칙 없음 | 같음 |
| S2의 agent 레코드 (uuid·이름·`create_time`) | 전후 같음 (`2026-11-09T05:06:28Z`) | 전후 같음 (`05:07:08Z`) |
| 다시 마운트 없이 같은 클라이언트 `cat A K d1/sub/Y; ls -A .snapshot` | `a2 k1 k2 y1 S1 S2` | 같음 |
| 탐침(`cat /m/d1/sub/Y` 0.2 s마다) | 실패 0, 내용 `y4` → `y1` | 실패 0, 내용 `y4` → `y1` |
| 서버 쪽 창 (DROP 규칙) | 7.76 s | 72.63 s |
| 탐침의 가장 긴 멈춤 / 창이 닫힌 뒤 재개까지 | 13.49 s / 5.82 s | 117.21 s / 44.61 s |
| 창이 닫힌 약 3.5 s 뒤 새로 띄운 읽기 | 2.31 s 걸림 | 40.99 s 걸림 |

  표의 값은 계측을 더한 2차 실행이다. 1차 실행도 agent 쪽 결과(멈춘 상태, LV 하나, 태그, S2 레코드, 트리, PUT 뒤 S3 행 삭제)는 같았다. 1차의 past-retry가 실패한 것은 기준 밖으로 내가 더한 "탐침이 `y1`을 읽었다" 단언 때문이다: 창이 닫힌 뒤에도 탐침의 막힌 읽기가 44.6 s 더 걸려, 그보다 일찍 기록을 읽었다. 2차는 탐침이 재개할 때까지(최대 240 s) 기다리고 그 시간을 기록한다.

- (d) 두 번째 되돌리기 — AC-02·AC-03 테스트 안에서 S2로 되돌린 뒤 S4를 만들고 더 오래된 S1로 다시 되돌렸다. v3·v4.1 모두 작업 `Succeeded`(5.15 s, 5.13 s), 볼륨 트리 = 되돌리기 전 S1 트리, S1 트리 그대로, ARM 목록 `S1`만(정체성 그대로), S2·S4 GET `404 ResourceNotFound`, 클라이언트 `cat A K d1/X` = `a1 k1 x1`, `/m/after`와 `.snapshot/S2/A`는 `No such file or directory`, 스냅샷 LV는 S1 하나, 볼륨 LV 하나, 태그 `anf_rv_done=<두 번째 작업 ID>`. merge 방식에서 실패하던 경우(§9-1)가 실환경에서 된다.

### [PASS] AC-09 agent API (API 계약)

- 실행: `test_ac09_agent_restore_api` (agent에 직접).
- 출력(핵심):
  - `PATCH …/volumes/<uuid>?restore_to.snapshot.uuid=<S1>&restore_to.request_uuid=<새 키>` → `202` + job `success`(3 s), 클라이언트 `cat /m/f` = `one`(S1 시점, 되돌리기 전 `two`). 본문 `{}`로도 `202` + `success`.
  - 없는 볼륨 → `202` + job `failure` "volume 16809aa4-… not found". 없는 스냅샷 → `202` + job `failure` "snapshot 5f9fc620-… not found"(메시지에 그 uuid).
  - `400`: 볼륨 uuid `not-a-uuid`, 스냅샷 uuid `not-a-uuid`, 대문자 uuid(추가) — "uuid must be a lowercase UUID, got '…'"; `request_uuid` `nope` — 같은 문구; `request_uuid` 없음, 모르는 쿼리 `&foo=1`, `restore_to.snapshot.name`(추가), 쿼리 없음(추가) — "PATCH needs exactly the query parameters restore_to.snapshot.uuid and restore_to.request_uuid; changing volume properties is not supported"; 본문 `{"size": 1}` — "body must be empty or {}". 400 뒤 볼륨 트리 그대로.

### [PASS] AC-10 위임 꺼짐 (호스트)

- 실행: `test_ac10_delegations_are_off`.
- 출력(핵심):
  - 먼저 `sysctl -w fs.leases-enable=1`로 바꾼 뒤 `bash scripts/setup-wsl-dataplane.sh` → rc 0, "… NFSv4 delegations off", 뒤에 `fs.leases-enable` = `0`, `/etc/sysctl.d/90-anf-clone.conf` = `fs.leases-enable = 0\n`.
  - v4.1 클라이언트가 `exec 3<>/m/held 4</m/ro`로 쓰고 열어 둔 동안(`/proc/*/fd`에 `3 -> /m/held`, `4 -> /m/ro`) 인스턴스의 `/proc/fs/nfsd/clients/*/states`: `type: open, access: rw … filename: "/held"`, `type: open, access: r- … "/ro"`, `deleg` 없음.
  - 대조(기준 밖): 값을 잠깐 1로 바꾸고 다른 v4.1 클라이언트가 새 파일을 열자 같은 검사가 `type: deleg, access: w, … filename: "/other"`를 찾았다. 그래서 위 "deleg 없음"은 검사가 헛돌아서가 아니다. 곧바로 0으로 되돌렸다.
  - 클라이언트 정리 순서를 고친 뒤 다시 돌린 실행(§정리)에서도 검사 쪽 `deleg` 없음, 대조 쪽 `type: deleg, access: w … "/other"`, agent 거절 rc 3(1.2 s)이 같았다.
  - agent를 멈추고 값 1에서 agent를 띄우면 1.2 s 만에 rc 3으로 끝났다: "storage_agent.nfs_instance.StartupError: NFSv4 delegations must be off: fs.leases-enable must be 0, or NFSv4.1 clients read stale data after a snapshot revert. Run scripts/setup-wsl-dataplane.sh as root first." + "Application startup failed. Exiting." 값을 0으로 되돌리고(확인 `0`) agent를 다시 띄우자 볼륨을 다시 읽을 수 있었다(`cat /m/held` = `z`).

### [PASS] AC-11 회귀 (계정·풀·볼륨·스냅샷 e2e, 통합)

- 기준: 계정·풀·볼륨·스냅샷 e2e와 통합 테스트가 새 코드와 위임 꺼짐(`fs.leases-enable = 0`)에서 통과한다.
- 실행 (WSL, root, 위임 꺼짐):
  - `python -m pytest -p no:cacheprovider backend/tests/e2e/test_netapp_account_live.py …/test_netapp_account_lro_faults_live.py …/test_capacity_pool_live.py …/test_capacity_pool_lro_faults_live.py …/test_volume_contract_live.py …/test_volume_data_live.py …/test_volume_recovery_live.py …/test_snapshot_contract_live.py …/test_snapshot_data_live.py …/test_snapshot_recovery_live.py -v -s` (`ANF_E2E_API_URL=http://127.0.0.1:8080`)
  - `python -m pytest -p no:cacheprovider backend/tests/integration -m dataplane -v`
- 출력(핵심):
  - e2e: **102 passed in 1047.69 s**, skip 0, fail 0 (수집 102개). 판정에 쓴 근거 줄 예: 볼륨 AC-04 `dd: fsync failed … No space left on device`, 볼륨 AC-09 삭제 뒤 `Host is unreachable`, 스냅샷 AC-04 `.snapshot/S/a` 덮어쓰기 `Read-only file system`.
  - 통합: **17 passed in 259.79 s** — `test_aggregate_is_a_thin_pool_and_idempotent`, `test_create_mount_delete[nfs3|nfs4.1]`, `test_recover_after_wsl_restart`, `test_snapshot_is_a_read_only_point_in_time_copy[nfs3|nfs4.1]`, `test_delete_volume_deletes_its_snapshots`, `test_recover_snapshots_after_wsl_restart[nfs3|nfs4.1]`, `test_restore_reverts_under_a_mounted_client[nfs3|nfs4.1]`, `test_restore_resumes_after_stopping_midway` 다섯 경우, `test_nfs41_instance_restarts_with_client_records`.
  - 리눅스 단위·계약(기준 밖, 일반 사용자): 741 passed, skip 0.

## 기준 밖 관찰

1. **원본 스냅샷 삭제와 WSL 재시작 흉내 (LV 교체의 남은 위험)** — `test_extra_reverted_volume_survives_origin_delete_and_simulated_wsl_restart`: PASS. S2로 되돌린 뒤 볼륨 LV의 `origin`은 `snap_<S2>`였다. S4를 만들고, 볼륨 LV의 원본인 S2를 ARM DELETE하자 볼륨 트리가 그대로이고 `origin`이 빈 값이 됐다. 그 뒤 agent 정지 → 인스턴스 `docker stop` → S1·S4·볼륨 언마운트(각 1회) → `lvchange -an`(볼륨 `Vwi---tz--`, 스냅샷 `Vri---tz--`) → agent 시작: LV가 모두 다시 켜지고(`…-aotz--`) 새 클라이언트가 `a2 k1 k2 s4 s4 a1`, `.snapshot` = `S1 S4`를 읽었다. 볼륨·S1·S4 트리 그대로.
2. **멈춤이 창보다 긴 이유 (TCP 재전송)** [추론]: 창은 netns 입력 DROP이라 클라이언트의 TCP는 응답 없는 재전송 간격을 두 배씩 늘린다. 첫 RTO를 약 0.23 s로 두면 재전송은 창이 열린 뒤 0.23·(2^n − 1) s = 0.23, 0.69, 1.61, 3.45, 7.1, 14.5, 29, 58, 117 s에 나간다. 측정과 맞는다: 창 1.95 s → 멈춤 3.35~3.36 s(AC-04), 창 7.76 s → 13.49 s(AC-08c restart), 창 72.63 s → 117.21 s(AC-08c past-retry). 즉 클라이언트는 창이 닫힌 뒤 다음 재전송까지 기다린다.
3. **창 안에서 agent가 오래 죽으면 클라이언트가 그만큼 + 재전송 대기만큼 멈춘다** (AC-08c past-retry): 창 72.63 s 동안 hard 마운트 v3 클라이언트는 오류 없이 멈췄고, 창이 닫힌 뒤에도 막혀 있던 읽기는 44.6 s 뒤(합계 117 s)에 끝났다. 창이 닫힌 3.6 s 뒤 새로 띄운 읽기도 41.0 s 걸렸다(같은 TCP 연결을 쓴다 [추론]). 1차 실행에서 실패한 단언은 이 대기보다 일찍 탐침 기록을 읽은 내 테스트의 문제였다. 데이터는 맞고 오류도 없으므로 결함으로 보지 않는다. 다만 운영상 의미는 있다: agent가 창 안에서 죽으면 그 볼륨의 클라이언트는 agent가 돌아올 때까지 멈춘다(설계 §6.2대로 시작 복구가 창을 닫는다). 개념 문서의 "ANF와 다른 점"에 적을 만하다.
4. **작업 시간 편차**: 같은 코드에서 ARM 작업(startTime → endTime)이 4.15~5.16 s였고, 버린 첫 실행의 v3 한 번은 8.75 s였다(원인은 보지 않았다). 녹화의 ANF는 약 2.6 s다. 창이 닫힌 뒤 `Succeeded`까지 약 1.5 s(옛 LV `lvremove`, `lvrename`, 태그, anf-api의 job 폴링)다.
5. **AC-11 문구**: `test_netapp_account_*_live.py`·`test_capacity_pool_*_live.py`라는 글롭은 `test_netapp_account_live.py`와 `test_capacity_pool_live.py`를 고르지 못한다. 뜻대로 계정·풀 e2e 네 파일을 모두 돌렸다.

## 측정값

| 측정 | 값 | 반복 |
| --- | --- | --- |
| 서버 쪽 창 (DROP 규칙, 0.02 s 간격 관찰) | v3 1.956 s, v4.1 1.952 s | 각 1회 (AC-04) |
| 0.2 s 탐침의 가장 긴 멈춤 | v3 3.364 s, v4.1 3.352 s, 실패 0 (39·38회) | 각 1회 |
| 계속 쓰는 클라이언트의 가장 긴 쓰기 | v3 3.448 s, v4.1 3.35 s, 실패 0 (67·67회) | 각 1회 |
| ARM 작업 시간 (지연·중단 없음) | 5.15, 5.16, 5.15, 5.13 (AC-02·03·08d), 4.15, 4.15 (AC-04) s. 버린 첫 실행: 8.75 (v3), 5.13 (v4.1) s | 6회 + 2회 |
| 창이 닫힌 뒤 `Succeeded` | 1.51 s, 1.49 s | 2회 |
| agent API 되돌리기 job (start → end, 초 단위) | 3 s, 3 s | 2회 (AC-09) |
| agent 중단 시 작업이 `Failed`가 되기까지 | 60.3 s (AC-07), 68.3 s (창 안에서 죽인 뒤, AC-08c) | 각 1회 |

## 정리

- 검증이 끝난 뒤 WSL 상태: LV는 `aggr0`만, 컨테이너 0개, `ns/`·`exports/` 비어 있음, agent·anf-api 프로세스 없음, 호스트 iptables의 DROP은 Docker 자체 규칙(`-P FORWARD DROP`, `DOCKER` 체인)뿐(되돌리기 규칙은 인스턴스 netns 안에만 있고 인스턴스와 함께 사라졌다), `fs.leases-enable` = `0`, `/etc/sysctl.d/90-anf-clone.conf` 그대로. 남은 마운트는 시작 때도 있던 `ns` 자기 바인드(agent의 `ensure_shared_ns`)뿐이다. 배포판 유지용 `sleep 86400`은 그대로 두었다.
- e2e 픽스처의 정리(`agent` 픽스처가 이번 실행의 `e2ev<RUN>-` 볼륨을 agent API로 지움)는 실패한 `08c[past-retry]` 1차 실행이 남긴 볼륨 하나(`/e2evb987-rac08cp`)를 지웠다.
- 내 스크립트가 남긴 것 하나: AC-10 대조용 클라이언트 컨테이너(`anfe2e-cli-a4e07a07`, `exited`)가 남아 있었다. 볼륨(서버)을 먼저 지운 뒤 위임을 쥔 hard 마운트 클라이언트를 픽스처가 `docker rm -f`했는데 지워지지 않은 것으로 본다(`sh()`가 종료 코드를 보지 않는다). 나중에 `docker rm -f`로 지웠다(rc 0). `test_ac10_delegations_are_off`가 클라이언트를 볼륨보다 먼저 지우고 지워졌는지 단언하도록 고친 뒤 다시 돌려 PASS(24.2 s), 남은 컨테이너 0개, 대조에서 `type: deleg, access: w … "/other"`를 다시 봤다.

## 이번 회차가 만든 검증 스크립트

- `backend/tests/e2e/revert_live.py`: revert 경로·폴링, 트리 체크섬(호스트·클라이언트), AC-02 기록 만들기, 차단 규칙 관찰(`RuleWatch`), 클라이언트 안의 탐침·쓰기·fd 스크립트.
- `backend/tests/e2e/test_snapshot_revert_data_live.py`: AC-02·03(+08d), AC-04 ×2, AC-10.
- `backend/tests/e2e/test_snapshot_revert_contract_live.py`: AC-01, AC-05, AC-06, AC-07 ×2, AC-08a, AC-08a+b, AC-08c ×2, 기준 밖 `extra`, AC-09.
- 셋 모두 `e2e`·`dataplane` 마커, `ANF_E2E_API_URL`과 root가 없으면 skip이다(Windows에서는 수집만 된다). `uvx ruff@0.14.0 check backend/tests/e2e/` 통과. 두 파일을 다 돌리면 약 13분이다(AC-07 agent 중단 60 s, AC-08c past-retry 약 3분 포함).
