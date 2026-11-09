# 스냅샷(FR-05) 검증 보고서 — 1회차

- 검증일: 2026-11-08 (WSL 시각 PST 15:15~16:55. 배포판 부팅 id `91302461…`, 검증 중 재시작 없음)
- 검증 대상 코드:
  - 제품 코드 내용 해시: 시작 `f5607a082c70d4dad6899f7722cfdcc486eb67bd249210c3c3cd5e9ecf2738f1`, 끝 `f5607a082c70d4dad6899f7722cfdcc486eb67bd249210c3c3cd5e9ecf2738f1` (같다. 리더가 넘긴 값과도 같다)
  - 커밋: HEAD `81020e3366458f85d7b58467033ca5b2dfd2cead` (문서만 바뀐 커밋. 마지막 제품 커밋은 `27757aa`)
  - 미커밋 변경: 제품 코드는 없다. 테스트 파일은 아래 목록에 있다. 그 밖에 `_workspace/snapshot/00_progress.md`, `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`은 이 검증과 무관하다(검증자가 만들지 않았다)
  - 해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum` (Git Bash, 저장소 루트)
- 이번 회차 범위: 전체 (AC-01~AC-15)

## AC별 요약

| AC | 결과 | 한 줄 근거 |
|---|---|---|
| AC-01 생성 계약·상태 | PASS | PUT 201 `Creating`, 두 헤더 → `Succeeded`(CREATE, 1.13 s). GET에 UUID v4 `snapshotId`, ISO `created`, `name` 4단, tags 없음. 빈 목록 `{"value": []}`. 클라이언트 `ls -A .snapshot` = `s1` |
| AC-02 데이터 NFSv3 | PASS | 지운 A, 덮어쓴 d/B를 `.snapshot/S/`에서 이전 내용으로 읽음. `ls -a`에 `.snapshot`, st_dev 다름, 두 번째 v3 클라이언트도 같음 |
| AC-03 데이터 NFSv4.1 | PASS | AC-02와 같은 결과를 v4.1 볼륨·클라이언트 둘에서 확인 |
| AC-04 불변 | PASS | v3·v4.1 root 클라이언트의 스냅샷 안 쓰기 7종과 `.snapshot` 자체 조작 5종 + 보조 3종이 모두 rc≠0. 호스트 sha256·목록·mode·`i` 속성 그대로. 새 볼륨에 빈 `.snapshot`. (errno는 설계 기술과 다름, 관찰 4) |
| AC-05 시점 | PASS | S1/S2/활성 = one/two/three. 900 MiB `dd` 도중 S3 생성(PUT 2.0 s, Succeeded 4.04 s, dd 끝 34.6 s), dd rc 0, S3 `e2fsck -fn` rc 0 |
| AC-06 DELETE | PASS | v3·v4.1 모두 cwd·fd를 쥔 클라이언트가 있는 S1 DELETE: 202(본문 없음, 두 헤더) → Succeeded(DELETE) → GET 404 → 다시 DELETE 204. 모든 클라이언트에서 `No such file or directory`, S2 그대로, 호스트에 LV·마운트·export 줄 없음, 재생성 시 새 내용 |
| AC-07 거절 | PASS | 이름 5종 400(`a/b`는 404, 기록), 본문 4종 400, 없는 볼륨 404 ParentResourceNotFound, Deleting 볼륨 409 Conflict, Creating 볼륨 400 BadRequest, PATCH 405. 작업·행·LV 변화 없음. 255개 한도는 계약 테스트 1 passed |
| AC-08 재전송 PUT | PASS | 200 `Updating`(azure-asyncoperation만) → Succeeded(UPDATE). `snapshotId`·`created` 같음, LV 하나, 내용 first. 다른 location 409 InvalidResourceLocation |
| AC-09 진행 중 충돌 | PASS | 생성 지연 8 s 동안 PUT·DELETE 409 AnotherOperationInProgress, 볼륨 DELETE 409 Conflict, 새 작업 없음. 원래 작업 Succeeded, `.snapshot/s9` 보임 |
| AC-10 볼륨 연쇄 삭제 | PASS | 클라이언트 cwd가 S1에 있는 볼륨 DELETE → Succeeded(약 2 s). 볼륨·스냅샷·목록 404. 스냅샷 LV·볼륨 LV·마운트·ns·exports 디렉터리·인스턴스·DB 행 없음. 같은 token 재생성 시 `.snapshot` 비어 있음 |
| AC-11 실패와 회복 | PASS | 주입 실패 → 작업·스냅샷 Failed, LV 없음 → 주입 끈 서버에서 PUT 200 Updating → Succeeded, `s11` 보임. agent 정지 60.3 s 뒤 Failed → agent 시작 뒤 PUT Succeeded |
| AC-12 재시작 복구 | PASS | (a) 생성 중 anf-api SIGKILL → 재시작 뒤 Succeeded, LV 하나, 읽힘. (b) agent 정지·인스턴스 정지·스냅샷과 볼륨 umount·LV 비활성 뒤 agent 시작: v3·v4.1 모두 S1·S2가 새 클라이언트에서 읽힘 |
| AC-13 agent API | PASS | POST 202 → success, 재전송 success(LV 하나), 같은 name 다른 uuid failure "already exists", `?name=` 1건, GET record, 404들, 없는 uuid DELETE success, 잘못된 입력 400, 없는 볼륨 POST failure |
| AC-14 회귀 | PASS | 계정·풀 live e2e 63개(CI 재현) 통과. 볼륨 e2e 21개는 두 테스트의 기대값을 이번 사이클 변경에 맞게 고친 뒤 모두 통과(AC-09 1회 불안정, 관찰 1). 통합 10 passed |
| AC-15 v4.1 인스턴스 재시작 | PASS | (c) lease 30·grace 45. (a) 마운트 유지 클라이언트: 18.8~20.8 s 뒤 준비, 다시 마운트 없이 I/O. (b) 기록만 남은 클라이언트: agent 시작 51.0 s, 유예 46 s 대기 뒤 새 클라이언트 쓰기. 테스트 전제를 두 번 고쳤다(아래 AC-15 절) |

## 결과 요약

PASS 15 / FAIL 0 / UNVERIFIED 0

따로 표시할 것 (FAIL 아님, 아래 "불안정한 결과와 관찰"):
1. 불안정: 볼륨 AC-09의 앞 단계 `dd conv=fsync`가 한 번 `I/O error` (재실행 3/3 통과).
2. knfsd 첫 시도 추적 실패율이 이번 환경에서 약 30%다. A/B 실험으로 이번 사이클 진입점 변경과 무관함을 확인했다(main 7/20, 현재 6/20).
3. 결정 16(5)의 "v3 쓰기용 열기는 EACCES"가 관찰과 다르다. 이번에는 v3도 모두 `Read-only file system`(EROFS)이었다. 개념 문서를 고쳐야 한다.
4. 볼륨 e2e 두 테스트가 이번 사이클 제품 변경(결정 8의 항상 있는 `.snapshot`, agent 로그 문구)과 맞지 않아 테스트를 고쳤다. 로그 문구를 되돌릴지는 리더가 정한다.

## 만든·바꾼 테스트 파일 (모두 `backend/tests/e2e/`, 제품 코드는 고치지 않음)

| 파일 | 구분 | 내용 |
|---|---|---|
| `backend/tests/e2e/snapshot_live.py` | 새 파일 (도우미) | 스냅샷 URL·생성·삭제, 작업 시간, 스냅샷 LV 이름·목록·attr, 씬 풀 사용량(dmsetup), export 파일·인스턴스 etab·export 경로, 스냅샷 마운트, 호스트 파일 sha256, `lsattr -d`, umount 재시도, 인스턴스 준비 대기·로그 줄, 쓰기 시도 목록, 404 문구, ISO UTC 형식 |
| `backend/tests/e2e/test_snapshot_contract_live.py` | 새 파일 | AC-01, AC-07, AC-08, AC-09, AC-13 (5개) |
| `backend/tests/e2e/test_snapshot_data_live.py` | 새 파일 | AC-02/03(파라미터), AC-04(v3·v4.1), AC-05, AC-06(v3·v4.1), AC-10 (8개) |
| `backend/tests/e2e/test_snapshot_recovery_live.py` | 새 파일 | AC-11 두 개, AC-12a, AC-12b, AC-15 (5개) |
| `backend/tests/e2e/test_volume_data_live.py` | 수정 1줄 | 볼륨 AC-09: 같은 token으로 다시 만든 볼륨의 `ls -A` 기대값을 `"listed\n"`에서 `".snapshot\nlisted\n"`로. 스냅샷 결정 8(`.snapshot`이 항상 있음)의 의도된 결과 |
| `backend/tests/e2e/test_volume_recovery_live.py` | 수정 1줄 | 볼륨 AC-12b[job-start]: job 시작 표시를 `f"POST volume {fsid}: job"`에서 `f"POST /api/storage/volumes/{fsid}: job"`로. `backend/storage_agent/agent_app.py:115`의 로그가 이제 job description(`:123`)을 그대로 쓴다 |

- 표시: 모든 새 테스트는 `e2e`, `dataplane`, `live_api.SKIP_UNLESS_LIVE`, `SKIP_UNLESS_ROOT`.
- `uvx ruff@0.14.0 check backend .claude/hooks`: All checks passed (마지막 변경 뒤).
- Windows 전체 스위트 `.venv-win/Scripts/python -m pytest`: 662 passed, 112 skipped (110 s). skip은 모두 live e2e(`ANF_E2E_API_URL` 없음)와 root 통합 테스트이며, 이전 기준 94에 새 스냅샷 e2e 18개가 더해진 값이다. 이 skip들은 아래 WSL 실행에서 실제로 돌았다.

## 환경 사전 점검

| 항목 | 결과 |
|---|---|
| WSL 배포판 | Ubuntu Running, 커널 `6.18.54.1-microsoft-standard-WSL2`. 부팅 id `91302461…`(journal 시작 15:03:43 PST)가 검증 끝까지 같다. 리더의 `sleep 86400`(PID 638) 그대로 |
| 커널 모듈 | `nfsd`, `dm_thin_pool`, `nfs` 로드됨 |
| Docker | Engine `29.1.3` (linux). `readlink /usr/bin/docker` rc=1 (Desktop 연동 아님) |
| 이미지 | `anf-nfs-server:latest` 8af57e42b272 (2026-11-08 15:47). 이미지 안 `/entrypoint.sh` sha256 `6a3653…12d5`, `nfs.conf` `9507a7…0b1d`가 저장소 파일과 같다. sqlite 3.45.3 포함. `anf-nfs-client:latest` 32f6d230984f (Alpine, coreutils dd) |
| 네트워크 | `anf-vnet` 172.30.0.0/24, ip-range 172.30.0.128/25 |
| 시작 상태 | 포트 8080·8090·18080 비어 있음. LV는 `aggr0`만, `/var/lib/anf-clone/ns`·`exports` 비어 있음. 씬 풀 Data% 0.00 |
| 자원 | 디스크 933G 여유 (`aggr0.img` 실사용 20G), 메모리 약 7.7 GB. dm 장치 `anf-aggr0-tpool`, 청크 524288 B |

## 실행 기록

| # | 실행 | 사용자 | 결과 | 출력 |
|---|---|---|---|---|
| R1 | 스냅샷 e2e 세 파일 | root | 18 passed in 529.32 s (AC-15(b) 전제 무효, AC-15 절) | `/tmp/anf-snap-e2e-r1.out`, `.jsonl` |
| R2 | 볼륨 e2e 세 파일 (AC-14) | root | 19 passed, 2 failed (테스트 기대값 2건) | `/tmp/anf-vol-e2e-snap.out`, `.jsonl` |
| R3 | 통합 테스트 (AC-14) | root | 10 passed in 176.55 s | `/tmp/anf-int-snap.out` |
| R4 | 테스트 수정 뒤: 볼륨 AC-12b 3건, 볼륨 AC-09, 스냅샷 AC-15 | root | AC-12b 3 passed. AC-09 failed(불안정, 관찰 1). AC-15 failed(테스트 전제 단언, AC-15 절) | `/tmp/anf-rerun-r1.out`, `.jsonl` |
| R5 | 볼륨 AC-09 3회 반복 | root | 3/3 passed | `/tmp/anf-vol-ac09-rep{1,2,3}.out` |
| R6 | 스냅샷 AC-15 (최종 테스트) | root | 1 passed in 111.89 s | `/tmp/anf-snap-ac15-rep.out` |
| R7 | CI 재현 (`-m "not dataplane"`, `ANF_E2E_API_URL=http://127.0.0.1:18080`) | mkimhome1 | 725 passed, 49 deselected, skip 0, failure 0. 데이터 플레인 파일 선택 0. hook tests 25 passed | `/tmp/anf-ci-snap.out`, `/tmp/anf-ci-snap/` |
| R8 | 255개 한도 계약 테스트 `backend/tests/test_snapshots_api.py::test_at_most_255_snapshots` | Windows | 1 passed (13.29 s) | 터미널 |
| R9 | knfsd 재시작률 A/B (main 진입점 vs 현재) | root | main 7/20, 현재 6/20 재시작 (관찰 2) | `/tmp/anf-ab.out` |
| R10 | Windows 전체 스위트 | Windows | 662 passed, 112 skipped | 터미널 |

R1~R6 명령 (WSL, 저장소 루트):
```
wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && PYTHONDONTWRITEBYTECODE=1 \
  ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/tmp/<name>.jsonl \
  /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider <파일 또는 ::테스트> -v -s -rA'
```
`-m dataplane` 수집은 49개다: 스냅샷 5+8+5, 볼륨 7+7+7, 통합 10.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
|---|---|---|
| AC-01 | PASS | 1회차 (R1) |
| AC-02 | PASS | 1회차 (R1) |
| AC-03 | PASS | 1회차 (R1) |
| AC-04 | PASS | 1회차 (R1) |
| AC-05 | PASS | 1회차 (R1) |
| AC-06 | PASS | 1회차 (R1) |
| AC-07 | PASS | 1회차 (R1, R8) |
| AC-08 | PASS | 1회차 (R1) |
| AC-09 | PASS | 1회차 (R1) |
| AC-10 | PASS | 1회차 (R1) |
| AC-11 | PASS | 1회차 (R1) |
| AC-12 | PASS | 1회차 (R1) |
| AC-13 | PASS | 1회차 (R1) |
| AC-14 | PASS | 1회차 (R2, R3, R4, R5, R7) |
| AC-15 | PASS | 1회차 (R6. R1·R4는 테스트 전제 문제로 판정에 쓰지 않음) |

## 항목별 결과

### [PASS] AC-01 생성 계약·상태 (계약·상태)
- 기준: `Succeeded` 볼륨 아래 `{"location"}` PUT → 201 `Creating`(snapshotId·created 없음), 헤더 두 개 → 폴링 `Succeeded`(CREATE). GET에 UUID `snapshotId`, ISO 8601 `created`, `name` = `{a}/{p}/{v}/{snap}`, `type`, tags 없음. 목록에 있고 빈 목록은 `{"value": []}`.
- 실행한 명령: R1 `test_snapshot_contract_live.py::test_ac01_create_snapshot_contract_and_state`
- 출력(핵심):
  - 스냅샷 없는 볼륨 목록 `{"value": []}`. PUT 201, 본문 `{"provisioningState":"Creating"}`만, 헤더 `azure-asyncoperation`·`location`. PUT 직후 Location 폴링 202.
  - 작업 Creating → Succeeded, `action: CREATE`, 1.134 s.
  - GET `name` = `e2e-vol-acct/e2e-vol-pool/vs1/s1`, `type` = `Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots`, `tags` 없음, `snapshotId` UUID v4, `created` 예 `2026-11-09T00:15:09Z`. Location 폴링 200 본문이 GET과 같다. 목록 1건.
  - 데이터 플레인: LV attr `Vri-aotz--`(읽기 전용 씬 스냅샷, 활성), origin `vol_<uuid>`, 태그 `anf_snap_name`·`anf_snap_vol`·`anf_snap_time`(created와 같은 시각). 마운트 `ns/<tok>/.snapshot/s1`. export 파일과 인스턴스 etab에 `/<tok>`와 `/<tok>/.snapshot/s1`. 요청의 `x-ms-correlation-request-id`가 agent 로그에 있다.
  - 클라이언트: `ls -A /m/.snapshot` = `s1`.

### [PASS] AC-02 데이터 NFSv3 / [PASS] AC-03 데이터 NFSv4.1 (데이터)
- 기준: 파일 A·`d/B` 쓰기 → 스냅샷 S → A 삭제, B 덮어쓰기 → `.snapshot/S/A`와 `.snapshot/S/d/B`가 이전 내용. 루트 `ls -a`에 `.snapshot`, 장치 번호가 다름. 다른 클라이언트도 같은 내용.
- 실행한 명령: R1 `test_snapshot_data_live.py::test_ac02_ac03_snapshot_keeps_point_in_time_content[AC-02-NFSv3-3]`, `[AC-03-NFSv4.1-4.1]`
- 출력(핵심):
  - 두 버전 모두 `.snapshot/S/A`, `.snapshot/S/d/B`가 원래 내용. 64 MiB big 파일의 sha256이 스냅샷 쪽은 덮어쓰기 전 값, 활성 쪽은 새 값.
  - `ls -a`에 `.snapshot`. `stat -c %d`: 루트와 스냅샷이 93/95 (v3), 105/93 (v4.1)로 다르다. 두 번째 클라이언트(vers=3, 4.1)도 같은 내용을 읽었고 스냅샷은 하위 마운트로 잡혔다. 호스트 마운트에서 본 내용도 같다.
  - 스냅샷 생성 1.10 s (v3), 1.15 s (v4.1).
  - 공간: 스냅샷 생성 직후 씬 풀 사용량 +524288 B(청크 하나), 64 MiB 덮어쓰기 뒤 +69730304 B. 클라이언트 `df` 사용량은 67108864에서 변하지 않았다. 스냅샷 공간은 씬 풀에서 나가고 볼륨 할당량에 잡히지 않는다(결정 16(4)와 일치).

### [PASS] AC-04 불변 (데이터)
- 기준: v3·v4.1 root 클라이언트에서 `.snapshot/S/` 안의 덧붙이기, `dd conv=notrunc`, `touch`, `rm`, `mv`, `mkdir`, `chmod`가 모두 rc≠0이고 호스트 내용이 그대로. `.snapshot` 자체의 파일 만들기, `mkdir`, `mv .snapshot`, `chmod`, `rmdir .snapshot/S`도 실패. 새 볼륨에 빈 `.snapshot`.
- 실행한 명령: R1 `test_snapshot_data_live.py::test_ac04_snapshot_and_snapshot_dir_are_immutable[NFSv3-3]`, `[NFSv4.1-4.1]`
- 출력(핵심, v3와 v4.1이 같다):
  - 새 볼륨 `ls -a /m/.snapshot` = `.`, `..`만.
  - 스냅샷 안 7종: 모두 rc 1, `Read-only file system` (예: `dd: failed to open '/m/.snapshot/S/a': Read-only file system`).
  - `.snapshot` 자체: 파일 만들기·`mkdir`·`mv .snapshot`·`chmod`는 `Operation not permitted`. `rmdir .snapshot/S`는 `Resource busy`. 보조 시도 `mv .snapshot/S` 밖으로는 `Resource busy`, `rm -rf .snapshot`은 스냅샷 안 파일마다 `Read-only file system`.
  - 호스트 전후 같음: 파일 sha256(`a` 87428f…25c7, `d/b` 026382…813f), 목록, `.snapshot` mode `0o40755`, inode 11, `lsattr -d` `----i---------e-------`. 클라이언트에서도 루트·`.snapshot`·내용이 그대로.
- 참고: 결정 16(5)는 "v3는 쓰기용 열기가 EACCES"라고 적었지만(S4 E3 관찰), 이번 구성에서는 v3 쓰기용 열기(`>>`, `dd`)도 EROFS였다. 판정 기준은 "실패하고 내용이 그대로"라 PASS다. 개념 문서에는 관찰값을 쓴다(관찰 3).

### [PASS] AC-05 시점 (데이터)
- 기준: S1 → 수정 → S2 → 수정: S1·S2가 각 시점, 활성은 마지막 내용. 계속 쓰는 `dd` 도중 S3를 만들어도 `dd`가 성공하고 S3 `e2fsck -fn`이 깨끗하다.
- 실행한 명령: R1 `test_snapshot_data_live.py::test_ac05_each_snapshot_is_its_own_point_in_time`
- 출력(핵심):
  - `cat .snapshot/S1/f .snapshot/S2/f f` = `one\ntwo\nthree\n` (같은 클라이언트와 새 클라이언트 모두).
  - `dd if=/dev/urandom bs=1M count=900 oflag=direct`: `943718400 bytes (944 MB, 900 MiB) copied, 34.3975 s, 27.4 MB/s`, rc 0. 시간선: PUT 2.0 s, Succeeded 4.04 s, dd 끝 34.6 s (PUT과 Succeeded 시점 모두 dd 실행 중). 스냅샷 작업 1.131 s.
  - S3 장치 `e2fsck -fn` rc 0, `15/65536 files (6.7% non-contiguous), 38043/262144 blocks`. (`ro,noload`로 마운트된 읽기 전용 LV라 "is mounted" 경고가 나오지만 장치가 바뀌지 않으므로 검사는 유효하다.)
  - S3 안 파일 크기 102760448 B, 활성 943718400 B. 스냅샷 시점의 일부 쓰기만 담겼다.

### [PASS] AC-06 스냅샷 DELETE (데이터·상태)
- 기준: 클라이언트가 `.snapshot/S1/` 안에 cwd·열린 파일을 둔 채 S1 DELETE: 202(본문 없음, 두 헤더) → Succeeded(DELETE) → GET 404 ResourceNotFound(녹화 문구) → 다시 DELETE 204. v3·v4.1 클라이언트에서 S1이 `No such file or directory`, S2 그대로. 호스트에 S1 LV·마운트·export 줄 없음. 같은 이름 재생성은 새 시점.
- 실행한 명령: R1 `test_snapshot_data_live.py::test_ac06_delete_snapshot_with_client_inside[NFSv3-3]`, `[NFSv4.1-4.1]`
- 출력(핵심, 두 버전 같음):
  - holder 클라이언트: cwd `/m/.snapshot/S1/d`, fd로 `d/b`를 연 상태.
  - DELETE 202, 본문 없음, 헤더 `azure-asyncoperation`·`location`. Deleting → Succeeded, `action: DELETE`, 약 3 s. GET 404 `ResourceNotFound`(녹화 문구 일치). 두 번째 DELETE 204, LRO 헤더 없음.
  - 관찰 클라이언트(전에 S1을 읽음), holder, 새 클라이언트 모두 `ls .snapshot/S1` → `No such file or directory`. `.snapshot/S2/f` = `two`.
  - 호스트: S1 LV 없음, 마운트 없음, 디렉터리 없음. export 파일과 etab에는 `/<tok>`와 `/<tok>/.snapshot/S2`만.
  - 같은 이름 S1 재생성: 새 `snapshotId`. 새 클라이언트 `cat .snapshot/S1/f .snapshot/S2/f` = `three\ntwo\n`, 마운트를 유지한 옛 관찰 클라이언트도 `.snapshot/S1/f` = `three`.

### [PASS] AC-07 거절 (계약)
- 기준: 이름 `.a`, `-a`, `a/b`(404 가능, 기록), `a b`, 256자 → 400. `location` 누락, `tags` 포함, 모르는 `properties` 키 → 400. 없는 볼륨 → 404 ParentResourceNotFound. `Deleting` 볼륨 → 409 Conflict. `Creating` 볼륨 → 400 BadRequest. PATCH → 405. 작업·LV가 생기지 않는다. 255개 한도는 계약 테스트.
- 실행한 명령: R1 `test_snapshot_contract_live.py::test_ac07_rejections_create_no_operation_or_lv`, R8 `backend/tests/test_snapshots_api.py::test_at_most_255_snapshots`
- 출력(핵심):
  - `.a`, `-a`, `a b`, 256자: 400 `InvalidResourceName`. `a/b`, `a%2Fb`: 404 `{"detail":"Not Found"}` (경로 세그먼트가 늘어 라우트가 없다. FastAPI 기본 본문이며 ARM 오류 형식은 아니다. 설계가 허용한 기록 사항).
  - `location` 누락, `location` 문자열 아님, `tags` 포함, 모르는 `properties` 키, `properties` 비객체: 400 `InvalidRequestContent`.
  - 없는 볼륨: 404 `ParentResourceNotFound`(문구 일치). PATCH: 405.
  - 볼륨 생성 지연 중(`Creating`): 400 `BadRequest`(문구 일치). 볼륨 삭제 지연 중(`Deleting`): PUT 409 `Conflict`, 남아 있던 스냅샷 DELETE도 409 `Conflict`(문구 일치). 볼륨 삭제 뒤 그 스냅샷 GET 404.
  - 각 거절 전후 작업 행·리소스 행·스냅샷 LV·export 줄 변화 없음.
  - 보조: 이름 `daily.2026-11-08_0013`과 255자 이름은 201 → Succeeded이고 클라이언트가 그 경로로 읽었다.
  - 255개 한도 계약 테스트: 1 passed (13.29 s).

### [PASS] AC-08 재전송 PUT (계약·상태)
- 기준: `Succeeded` 스냅샷에 같은 PUT → 200 `Updating` → Succeeded(UPDATE). `snapshotId`·`created` 그대로, LV 하나, 내용 첫 시점. 다른 location → 409 InvalidResourceLocation.
- 실행한 명령: R1 `test_snapshot_contract_live.py::test_ac08_put_again_is_async_update_and_keeps_snapshot`
- 출력(핵심): 200, `provisioningState: Updating`, 헤더는 `azure-asyncoperation`만. 작업 Updating → Succeeded, `action: UPDATE`. `snapshotId`(`1b27697a…`)·`created`(`2026-11-09T00:16:26Z`) 전후 같음. 스냅샷 LV 전후 1개, attr·origin·태그 같음. 스냅샷 뒤 활성 파일을 `second`로 바꿨고, 재전송 뒤 `cat .snapshot/s8/f f` = `first\nsecond\n`. 다른 location 409 `InvalidResourceLocation`. 작업 목록 [CREATE, UPDATE].

### [PASS] AC-09 진행 중 충돌 (계약)
- 기준: 스냅샷 생성 지연 중 그 스냅샷 PUT·DELETE → 409 AnotherOperationInProgress, 볼륨 DELETE → 409 Conflict, 새 작업 없음. 원래 작업은 Succeeded.
- 실행한 명령: R1 `test_snapshot_contract_live.py::test_ac09_requests_during_snapshot_create_conflict` (`ANF_FAULT_INJECTION={"snapshots/create": {"delaySeconds": 8}}`)
- 출력(핵심): 스냅샷 PUT·DELETE 409 `AnotherOperationInProgress`, 볼륨 DELETE 409 `Conflict`(설계 §9-7 문구). 세 응답 모두 LRO 헤더 없음, 작업 행 수 그대로. 원래 작업 Succeeded, 클라이언트 `.snapshot`에 `s9`.

### [PASS] AC-10 볼륨 연쇄 삭제 (데이터·상태)
- 기준: 스냅샷 두 개(클라이언트가 하나를 읽은 상태)인 볼륨 DELETE → 202 → Succeeded → 볼륨·스냅샷 GET·목록 404. 호스트에 스냅샷 LV·마운트·export 디렉터리·인스턴스 없음. 같은 `creationToken`으로 다시 만든 볼륨의 `.snapshot`이 비어 있다.
- 실행한 명령: R1 `test_snapshot_data_live.py::test_ac10_volume_delete_deletes_its_snapshots`
- 출력(핵심): 클라이언트 cwd가 `/m/.snapshot/S1`인 채 DELETE 202 → Succeeded(약 2 s). 볼륨·S1·S2 GET 404, 스냅샷 목록 404. 호스트: 스냅샷 LV 0, 볼륨 LV 없음, `ns/<tok>` 아래 마운트 0, `ns/<tok>`·`exports/<uuid>` 디렉터리 없음, 인스턴스 컨테이너 없음, DB의 스냅샷 행 0. 같은 token 재생성: `ls -A /m/.snapshot` 비어 있음, 스냅샷 목록 `{"value": []}`.

### [PASS] AC-11 실패와 회복 (상태)
- 기준: 생성 실패 주입 → 작업 Failed(`error`), 스냅샷 Failed, LV 없음. 주입 끈 서버에서 같은 PUT → 200 `Updating` → Succeeded, `.snapshot`에 보임. agent 정지 중 생성 → 60 s 재시도 뒤 Failed, agent 시작 뒤 PUT → Succeeded.
- 실행한 명령: R1 `test_snapshot_recovery_live.py::test_ac11_injected_failure_then_put_recovers`, `::test_ac11_agent_down_fails_after_retry_then_put_recovers`
- 출력(핵심):
  - 주입: 작업 Failed, `error.code` `InternalServerError`, 메시지 "Injected fault: snapshots/create…". 스냅샷 GET `Failed`. 스냅샷 LV 없음, export 파일은 볼륨 줄만.
  - 같은 DB로 주입 없이 다시 띄운 서버: PUT 200 `Updating` → Succeeded(UPDATE). 클라이언트 `.snapshot`에 `s11`. 작업 [CREATE Failed, UPDATE Succeeded].
  - agent 정지: 60.3 s 뒤 Failed, anf-api 로그에 "is unreachable" 62줄. agent 시작 뒤 PUT Succeeded, 스냅샷 안 `kept` 읽힘.

### [PASS] AC-12 재시작 복구 (상태)
- 기준: (a) 생성 지연 중 anf-api SIGKILL → 재시작 뒤 Succeeded, `.snapshot`에 보임. (b) agent 정지, 인스턴스 정지, 스냅샷·볼륨 umount(WSL 재시작 흉내) 뒤 agent 시작: v3·v4.1 볼륨의 스냅샷이 모두 새 클라이언트에서 읽힌다.
- 실행한 명령: R1 `test_snapshot_recovery_live.py::test_ac12a_anf_api_sigkill_during_snapshot_create`, `::test_ac12b_agent_restart_recovers_snapshots_after_simulated_wsl_restart`
- 출력(핵심):
  - (a) SIGKILL rc −9. kill 시점 작업 [CREATE Creating], 스냅샷 LV 없음. 재시작 뒤 Succeeded, LV 1개, `.snapshot` 안 `before` 읽힘.
  - (b) v3·v4.1 볼륨 각각 S1·S2. agent 정지 → `docker stop` → 스냅샷 두 개와 볼륨 umount(각 1회 시도에 성공) → `lvchange -an`(스냅샷 attr `Vri---tz--`, 볼륨 `Vwi---tz--`, 비활성) → 이때 클라이언트 마운트 rc 32. agent 시작 3.9 s 뒤 두 볼륨 모두 스냅샷 `Vri-aotz--`, 볼륨 `Vwi-aotz--`(활성·열림), `.snapshot/S1`·`S2` 마운트, 인스턴스 etab에 볼륨과 S1·S2. 새 클라이언트 읽기 `three\none\ntwo`(활성, S1, S2). 두 인스턴스 모두 lease=30 grace=45 (v4.1 인스턴스는 knfsd 재시작 1회).

### [PASS] AC-13 agent API (agent API)
- 기준: 설계 표의 AC-13.
- 실행한 명령: R1 `test_snapshot_contract_live.py::test_ac13_agent_snapshot_api` (agent에 직접 HTTP)
- 출력(핵심): POST 202 + job → `success`. 같은 uuid·name 재전송 → `success`, 스냅샷 LV 1개. 같은 name 다른 uuid → `failure`, "A snapshot with the specified name already exists.". `GET ?name=` 1건. `GET .../{uuid}` 레코드(`create_time` 포함). 없는 uuid GET 404, 없는 볼륨의 목록 404. 없는 uuid DELETE → `success`. 이름 `../x`, `a/b`, `.a`, 256자, 대문자 uuid, uuid 형식 아님, 모르는 필드, 경로의 볼륨 uuid 형식 아님, GET·DELETE의 잘못된 스냅샷 uuid → 모두 400. 없는 볼륨 POST → job `failure`("volume … not found"). 마지막 DELETE 뒤 스냅샷 마운트 없음.

### [PASS] AC-14 회귀 (회귀)
- 기준: 계정·풀·볼륨 e2e와 통합 테스트가 새 코드로 통과. 볼륨 e2e는 전체.
- 실행한 명령: R7(계정·풀 live 63개), R2·R4·R5(볼륨 e2e 21개), R3(통합 10개)
- 출력(핵심):
  - R7: 725 passed, 49 deselected, skip 0, failure 0. live 계정·풀 e2e 63개 포함.
  - R2: 19 passed, 2 failed. 실패 둘은 테스트 기대값이 이번 사이클의 의도된 제품 변경과 어긋나서였다.
    - 볼륨 AC-09: 같은 token으로 다시 만든 볼륨의 `ls -A` 결과 `.snapshot\nlisted\n`, 기대 `listed\n`. 스냅샷 결정 8로 `.snapshot`이 항상 있다.
    - 볼륨 AC-12b[job-start]: "stage job-start never reached". agent 로그가 `POST volume <uuid>: job …`에서 `POST /api/storage/volumes/<uuid>: job …`로 바뀌었다(`backend/storage_agent/agent_app.py:115`가 description을 그대로 쓰고, `:123`의 description이 그 문자열이다).
  - 두 테스트를 고친 뒤 R4에서 AC-12b 3건 통과(job-start 7.9 s, lv-created 5.0 s, mounted 10.0 s 뒤 Succeeded, 마운트 `ok`). 볼륨 AC-09는 R4에서 앞 단계가 불안정하게 한 번 실패했고(관찰 1), R5 3회 반복 3/3 통과. 최종 코드에서 볼륨 e2e 21개 모두 통과가 확인됐다.
  - R3: 10 passed (스냅샷 통합 5개 포함. live 클라이언트 재시작 20.8 s, 기록만 남은 클라이언트 47.4 s 뒤 준비).

### [PASS] AC-15 NFSv4.1 인스턴스 재시작 (데이터, 결정 1)
- 기준: (a) v4.1 클라이언트가 마운트를 유지한 채 인스턴스 `docker stop`·`start`: 인스턴스가 준비되고 그 클라이언트가 다시 마운트 없이 읽고 쓴다. (b) 클라이언트 기록만 남기고 재시작: 150 s 안에 준비, 새 클라이언트가 마운트해 쓴다. (c) lease·grace 30·45.
- 실행한 명령: R6 `test_snapshot_recovery_live.py::test_ac15_nfsv41_instance_restart_with_client_records`
- 출력(핵심, R6):
  - (c) `/proc/fs/nfsd/nfsv4leasetime`·`nfsv4gracetime` = `30`, `45`. serving 줄 `… attempts=2 lease=30 grace=45`.
  - (a) `docker stop -t 30`·`start` 뒤 18.8 s에 준비. 로그 `grace period: waiting for 1 NFSv4 client(s) to reclaim state` → `grace period ended after 18 s`(클라이언트가 되찾아 grace 45 s 전에 끝남). 다시 마운트 없이 `cat`·덧붙이기·스냅샷 읽기 0.33 s, `one\ntwo\none\n`. nfs4 마운트 수 2 → 2. `v4_end_grace` Y.
  - (b) soft 마운트 클라이언트(`soft,timeo=20,retrans=1`)가 쓰고, agent 정지 → 인스턴스 정지 → 클라이언트 `docker rm -f`. nfsdcld 기록 `rec-0000000000000003: 1`. agent 시작 51.0 s(150 s 안). 로그 `waiting for 1 NFSv4 client(s)` → `grace period ended after 46 s`(되찾는 클라이언트 없이 grace 끝까지). 새 클라이언트가 0.91 s에 마운트·쓰기, `one\ntwo\nthree\nfour\nfive\none\n`.
- 테스트를 고친 과정 (판정에 쓴 것은 R6뿐이다):
  - R1(통과했지만 전제 무효): hard 마운트 클라이언트의 `docker rm -f`가 "could not kill container: tried to kill container, but did not receive an exit event"로 실패해 컨테이너가 남았고, 서버가 돌아오자 그 클라이언트가 5 s 만에 상태를 되찾았다. "기록만 남은 클라이언트"가 아니었다.
  - 고침 1: (a) 뒤 live 클라이언트를 스냅샷 하위 마운트부터 umount해 기록을 지우고 제거한다. (b)는 soft 마운트 클라이언트를 쓴다. R4에서 실패했다. soft여도 `docker rm -f`가 12.3 s 뒤 같은 오류로 실패해, 테스트의 전제 단언(`rm.returncode == 0 and gone`)에 걸렸다. 서버 쪽은 기록 1개, grace 45 s 끝까지 대기, 새 클라이언트 쓰기 성공으로 기준을 충족했다.
  - 고침 2: 전제를 컨테이너 제거가 아니라 서버에서 관찰한 것으로 판정한다. nfsdcld 기록 1개 이상, `grace period: waiting for` 줄, 대기 30 s 이상. R6 통과.

## 불안정한 결과와 관찰

1. **불안정 (볼륨 AC-09 앞 단계)**: R4에서 미리 마운트한 soft 클라이언트(v3)의 `dd if=/dev/urandom of=/m/data bs=1M count=200 conv=fsync`가 `dd: fsync failed for '/m/data': I/O error`로 rc 1이었다(`200+0 records out … 5.75516 s, 36.4 MB/s`). 반복: 4회 중 1회 실패, 3회(R5) 통과. soft 마운트의 `timeo`가 짧아 서버 응답이 늦은 순간 EIO가 났을 가능성이 있다[추론]. 스냅샷 코드 경로가 아니라 볼륨 AC-09의 클라이언트 준비 단계다.
2. **knfsd 첫 시도 추적 실패(재시작)율**: 진입점이 `v4_end_grace = N`이고 되찾을 기록이 없어 knfsd를 한 번 내렸다 다시 띄운 비율이 R1 8/25(32%), R2 12/36(33%)였다. 볼륨 2회차 보고서는 5/64(7.8%)였다. 모두 2회째에 성공했고 `giving up`은 0이다. 이번 사이클의 진입점 변경(lease/grace echo, `exportfs -ra`) 때문인지 가리려고 R9 A/B를 했다: tmpfs export 하나로 main(`b84c7a9`)의 진입점 이미지와 현재 이미지를 번갈아 20회씩 띄웠다. 재시작은 main 7/20, 현재 6/20로 차이가 없다. 재시작은 실행 중반에 몰렸고 마지막 14회는 둘 다 1회 시도였다. 환경 상태에 따라 비율이 변하는 것으로 보인다[추론]. 위험: 5회 연속 실패하면 진입점이 exit 1을 하고 볼륨이 Failed가 된다. 30%라면 0.3^5 ≈ 0.24%다. 이번 회차에는 일어나지 않았다.
3. **`docker rm -f` 실패**: 서버가 없는 동안 NFS 마운트를 가진 클라이언트 컨테이너(hard·soft 모두)와, R9에서 클라이언트 없이 SIGKILL한 서버 컨테이너(40회 중 5회)가 "did not receive an exit event"로 지워지지 않았다. R9에서는 그때마다 다음 인스턴스의 준비가 42~48 s 걸렸다(평소 0.2~2.7 s). agent는 `docker stop -t 30` 뒤 `docker rm`을 쓰므로(`backend/storage_agent/nfs_instance.py:124-126`) 이 경로를 타지 않는다. 이번 검증의 볼륨·스냅샷 삭제에서는 문제가 없었다. 환경·커널 동작으로 기록한다.
4. **결정 16(5)와 다른 errno**: 설계와 S4 E3는 "v3 쓰기용 열기는 `EACCES`"라고 적었다. 이번 구성(스냅샷 export 줄, `ro,noload` 마운트)에서는 v3·v4.1 모두 스냅샷 안 쓰기 7종이 `Read-only file system`이었다. 개념 문서의 "ANF와 다른 점"에는 관찰값(둘 다 EROFS, `.snapshot` 자체는 EPERM, `rmdir .snapshot/S`는 EBUSY)을 쓰는 것을 제안한다.
5. **볼륨 e2e 테스트 두 개 수정**: 위 AC-14. 볼륨 AC-09의 기대값 변경은 결정 8의 의도된 결과다. agent 로그 문구 변경은 기능에는 영향이 없지만 볼륨 e2e가 그 문구에 의존했다. 문구를 main처럼 되돌릴지, 테스트 수정을 받아들일지는 리더가 정한다.
6. **AC-07 `a/b`의 404 본문**: `{"detail":"Not Found"}`로 FastAPI 기본 형식이다. 설계가 "404 가능, 기록"으로 허용했으므로 판정에 영향은 없다.

## 측정값

| 측정 | 값 | 반복 |
|---|---|---|
| 스냅샷 생성 작업 (PUT → Succeeded) | 1.10, 1.13, 1.134, 1.15 s | AC-01·02·03·05 각 1회 |
| 스냅샷 DELETE 작업 | 약 3 s | v3·v4.1 각 1회 |
| 볼륨 DELETE (스냅샷 두 개) | 약 2 s | 1회 |
| 스냅샷 생성 시 씬 풀 증가 | +524288 B (청크 하나) | v3·v4.1 각 1회 |
| 64 MiB 덮어쓰기 뒤 씬 풀 증가 | +69730304 B | v3·v4.1 각 1회 |
| `dd` 900 MiB `oflag=direct` (스냅샷 생성과 겹침) | 34.40 s, 27.4 MB/s | 1회 |
| agent 정지 중 생성 실패까지 | 60.3 s | 1회 |
| AC-12b agent 시작 뒤 LV 활성 | 3.9 s | 1회 |
| AC-15(a) 마운트 유지 클라이언트, 재시작 뒤 준비 | 20.2 s (R1), 20.8 s (R4), 18.8 s (R6). 통합 20.8 s | 4회 |
| AC-15(b) 기록만 남은 클라이언트, agent 시작 | 48.9 s (R4), 51.0 s (R6). 유예 45, 46 s. 통합 47.4 s | 3회 |
| AC-15(b) 새 클라이언트 마운트·쓰기 | 0.86, 0.91 s | 2회 |
| knfsd 재시작률 | R1 8/25, R2 12/36, R9 main 7/20, 현재 6/20 | 위 |

## 정리 상태 (검증 끝, 2026-11-08 16:54 PST)

- LV: `aggr0`만 (`twi-aotz--`, Data% 0.00). 볼륨·스냅샷 LV 없음.
- 컨테이너: 0개 (`docker ps -a` 비어 있음. `anf-vnet`에 연결된 컨테이너 없음). R9가 남긴 `anfe2e-ab-*` 5개와 이미지 `anf-nfs-server:abmain`은 지웠다.
- `/var/lib/anf-clone/ns`, `/var/lib/anf-clone/exports`: 비어 있음. `/var/lib/anf-clone/` 아래 마운트는 `ns` 자신(rshared 바인드) 하나뿐. NFS 마운트 없음.
- 포트 8080·8090·18080: 리슨 없음. uvicorn 없음.
- 실패한 테스트가 남긴 볼륨(`/e2eve860-ac09`, `/e2eve860-ac12bjo`, `/e2ev5f1a-ac09`, `/e2ev5f1a-sac15`)은 각 파일의 teardown이 agent로 지웠다.
- 남겨 둔 것: WSL `/tmp/anf-vol-e2e-*` 46개(e2e `api` 픽스처가 만든 DB와 서버 로그, 각 약 68K, 기존 픽스처가 지우지 않는 설계)와 `/tmp/anf-*.out`·`.jsonl` 증거 파일. 필요 없으면 `wsl -d Ubuntu -u root -e bash -c 'rm -rf /tmp/anf-vol-e2e-* /tmp/anf-ci-snap'`로 지운다.
- 이미지 `anf-nfs-server:latest`, `anf-nfs-client:latest`와 기존 spike 이미지는 그대로.

## 증거 경로

WSL `/tmp`의 원본과 같은 사본이 `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\b7994a5e-88b3-45b1-8bc2-d4fc6bda8500\scratchpad\evidence\`에 있다(세션 임시 폴더라 오래 남지 않는다):
`anf-snap-e2e-r1.out`·`.jsonl` (R1), `anf-vol-e2e-snap.out`·`.jsonl` (R2), `anf-int-snap.out` (R3), `anf-rerun-r1.out`·`.jsonl` (R4), `anf-vol-ac09-rep1~3.out` (R5), `anf-snap-ac15-rep.out` (R6), `anf-ci-snap.out`·`anf-ci-snap/` (R7), `anf-ab.out` (R9).
