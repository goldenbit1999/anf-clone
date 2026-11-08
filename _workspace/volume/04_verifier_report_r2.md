# volume 검증 보고서 — 2회차

- 검증일: 2026-11-07 (WSL 시각 PST 23:15~23:35)
- 검증 대상 코드:
  - 제품 코드 내용 해시: 시작 `8bb57d912a0124580af7a8c3a58340667e54bb0dee349acdf4d5b4e017e5d77e`, 끝 `8bb57d912a0124580af7a8c3a58340667e54bb0dee349acdf4d5b4e017e5d77e` (같다)
  - 커밋 SHA: `f20ef13a561c7f34a48873cd82e34a014445b07b`
  - 1회차 뒤 바뀐 제품 코드 (모두 미커밋): `backend/storage_agent/nfs_server/entrypoint.sh`, `backend/storage_agent/nfs_instance.py`, `backend/storage_agent/flexvol.py`. 이미지 `anf-nfs-server:latest`는 `27e7d264aede`(2026-11-07 23:11 PST)로 다시 빌드됐다.
  - 이번 회차에 검증자가 바꾼 파일 (테스트, 해시 밖): `backend/tests/e2e/test_volume_live.py`를 나눠 지웠고, `dataplane_live.py`, `test_volume_contract_live.py`, `test_volume_data_live.py`, `test_volume_recovery_live.py`를 만들었다. `conftest.py`도 고쳤다. 제품 코드는 고치지 않았다.
- 이번 회차 범위: 재검증
  - 수정 대상: AC-03
  - 인스턴스 시작 경로가 바뀌어 다시 실행한 것: AC-01, AC-02, AC-04~AC-13, AC-15, 유예 기간 반복 시험(`ANF_E2E_REPEAT=20`), 통합 테스트
  - AC-14는 anf-api가 바뀌지 않아 1회차 결과를 유지한다. 다만 CI 로컬 재현에 계정·풀 e2e 63개가 들어 있어 이번에도 실행됐다.
  - 볼륨 e2e 파일 분리를 검증했다. 나눈 파일로 위 재검증을 돌렸다.

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL·커널 | Ubuntu, `6.18.54.1-microsoft-standard-WSL2`, `nfsd`·`dm_thin_pool` 로드됨 |
| Docker | `29.1.3 linux`, `readlink /usr/bin/docker` 빈 값(rc=1) |
| 이미지·네트워크 | `anf-nfs-server:latest` 27e7d264aede(다시 빌드), `anf-nfs-client:latest` 32f6d230984f, `anf-vnet` |
| 시작 상태 | 시험 파일 세 개의 `baseline`이 모두 `{lvs: [], instances: {}, ns: []}`, 씬 풀 0.00% |
| ruff | Windows `uvx ruff@0.14.0`, WSL은 `pip --target` 임시 설치 |
| dmesg | 이번 실행 전후로 센 추적 실패 줄 차이가 −1이었다. 링 버퍼가 밀려 줄 수 비교를 쓸 수 없다. 리더 말대로 knfsd 재시작은 인스턴스 로그로 셌다 |

환경 문제로 UNVERIFIED가 된 AC는 없다.

## 결과 요약

AC 기준: **PASS 15 / FAIL 0 / UNVERIFIED 0**

추가 항목: CI 로컬 재현 PASS, 통합 테스트 PASS, e2e 파일 분리 PASS, GitHub Actions 실제 실행 UNVERIFIED(push 대기)

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 2회차 |
| AC-02 | PASS | 2회차 |
| AC-03 | **PASS** (1회차 FAIL → 수정 뒤 PASS) | 2회차 |
| AC-04 | PASS | 2회차 |
| AC-05 | PASS | 2회차 |
| AC-06 | PASS | 2회차 |
| AC-07 | PASS | 2회차 |
| AC-08 | PASS | 2회차 |
| AC-09 | PASS | 2회차 |
| AC-10 | PASS | 2회차 |
| AC-11 | PASS | 2회차 |
| AC-12 | PASS | 2회차 |
| AC-13 | PASS | 2회차 |
| AC-14 | PASS | 1회차(`04_verifier_report.md`). 2회차 CI 재현에서 계정·풀 e2e 63개가 다시 통과 |
| AC-15 | PASS | 2회차 |
| CI 로컬 재현 | PASS | 2회차 |
| 통합 테스트 | PASS | 2회차 |
| GitHub Actions 실행 | UNVERIFIED | — (push는 사용자 결정) |

## 실행

```
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_REPEAT=20 ANF_E2E_LOG=/tmp/anf-vol-e2e-r2.jsonl /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider -m dataplane backend/tests/e2e -v -s -rA'
```

결과: **21 passed, 63 deselected in 530.55s** (볼륨 e2e 세 파일. 계정·풀 e2e는 `dataplane`이 아니라 선택에서 빠졌다). 실패가 없어 다시 돌리지 않았다.

## 항목별 결과

### [PASS] AC-03 NFSv4.1 볼륨 (데이터) — 1회차 FAIL의 재검증
- 기준 (리더가 정한 PASS 조건):
  1. 모든 인스턴스가 준비 표시를 만들고 `v4_end_grace=Y`로 서비스한다.
  2. 첫 쓰기가 60초보다 훨씬 짧다(수 초).
  3. job이 끝난 직후 바로 마운트해도 된다.
  4. 인스턴스 로그의 첫 시도 실패와 재시작은 FAIL이 아니고 횟수만 보고한다.
- 실행한 명령: 위 전체 실행. `test_ac03_nfsv41_volume`, `test_ac15_…`, `test_nfsv41_new_instances_skip_grace_repeated`(20라운드, 볼륨 40개). 시험 파일마다 `InstanceLogs`가 모든 `anf-nfs-*` 컨테이너의 진입점 로그를 지워지기 전에 0.3초마다 모았다.
- 출력:
  - AC-03: 첫 쓰기·읽기 **0.22 s**, 인스턴스 `{"ready": true, "v4_end_grace": "Y", "serving": "anf-nfs: serving /e2eve90e-ac03 (nfs4.1): versions=-3 +4 -4.0 +4.1 -4.2 attempts=1", "restarts": 0}`. GET 규칙 `nfsv41 true / nfsv3 false`. `vers=3`은 rc 32 `requested NFS version or transport protocol is not supported`, `vers=4.0`은 rc 32 `Protocol not supported`. 두 번째 클라이언트도 같은 내용을 읽었다.
  - AC-15: 첫 I/O **0.35 s**, 두 인스턴스 모두 `ready true, v4_end_grace Y, attempts=1`
  - 반복 시험: 40개 모두 `ready true`, `v4_end_grace Y`, 쓰기 rc 0, `bad 0`.
    - 첫 쓰기: 0.61~**3.25 s**. 새 클라이언트 컨테이너의 마운트 시간을 포함한다.
    - agent job 시간: 1.21~5.69 s, 평균 1.59 s.
    - 라운드마다 두 번째 볼륨은 job `success` 직후(GET 한 번 뒤) 바로 마운트했다. 20개 모두 통과했다.
  - 모든 인스턴스(시험 파일 세 개 합계):

    | 파일 | 인스턴스 | knfsd 시작(serving 줄) | 재시작 | 포기(exit 1) | serving 없음 |
    | --- | --- | --- | --- | --- | --- |
    | contract | 8 | 8 | 0 | 0 | 0 |
    | data | 48 | 48 | 5 | 0 | 0 |
    | recovery | 7 | 8 (AC-12c `docker start`로 한 번 더) | 0 | 0 | 0 |
    | **합계** | **63** | **64** | **5 (7.8%)** | **0** | **0** |

  - 재시작 5회는 모두 한 번 만에 됐다(`attempts=2`). 1회차의 추적 실패율(약 7~8%)과 같은 빈도다.

    | 인스턴스 | 볼륨 | job 시간 | 첫 쓰기 |
    | --- | --- | --- | --- |
    | `anf-nfs-6cceb697…` | 반복 g01 (job 직후 마운트) | 3.84 s | 0.67 s |
    | `anf-nfs-152f9739…` | 반복 g60 | 4.86 s | 2.77 s |
    | `anf-nfs-9cadca52…` | 반복 g61 (job 직후 마운트) | 5.69 s | 3.25 s |
    | `anf-nfs-fa98f046…` | 반복 g101 (job 직후 마운트) | 3.85 s | 0.68 s |
    | `anf-nfs-7f1a2f35…` | AC-04 NFSv4.1 (ARM, 상관 ID `209f8e00…`) | — | `dd`가 3.90 s에 ENOSPC, 정상 |

- 판정: 네 조건을 모두 만족했다. 재시작이 있었던 인스턴스도 job이 끝났을 때는 이미 유예 기간이 끝나 있었다. 그 대가로 job이 2~4초 길어졌다. 1회차의 90~102초 대기는 이번 실행에서 한 번도 나오지 않았다.

### [PASS] 나머지 AC (2회차 핵심 출력)

단언은 1회차와 같다(아래 "e2e 파일 분리"). 출력의 자세한 형식은 1회차 보고서와 같으므로 핵심 값만 적는다.

| 기준 | 2회차 출력 |
| --- | --- |
| AC-01 | PUT 201 `Creating`, LRO 헤더 `["azure-asyncoperation"]`. 작업 `Creating`×3 → `Succeeded`, 2.12 s(07:22:42.107 → 07:22:44.231 UTC). IP 172.30.0.129. LV·인스턴스·ns 생성, 상관 ID가 agent 로그에 있음 |
| AC-02 | B가 `from-a-10ccdd0d…`와 `770`을 읽음. `vers=4.1`은 rc 32 `Protocol not supported` |
| AC-04 | v3·v4.1 모두 `df` 1021313024 B, `dd` rc 1 + `No space left on device`, keep 파일 그대로 읽힘 |
| AC-05 | `400 BadRequest "Pool size too small…"`, `404 ParentResourceNotFound`, `409 Conflict`(풀 Deleting). CV-1 `409 CannotDeleteResource`. CV-2 PATCH·PUT `400 BadRequest`. CV-3 PUT `400 BadRequest "ServiceLevel cannot be changed."`(PATCH는 `400 InvalidRequestContent`, 풀 설계 결정 5) |
| AC-06 | 22개 모두 400. 기본값 대조 201. 하한 주입을 끄면 49 GiB `400`(…from 50 GiB…), 50 GiB `201` |
| AC-07 | 중복·대소문자 중복 `400 BadRequest "File path already in use."`. 변경 거절 `BadRequest`/`BadRequest`/`InvalidRequestContent`. 같은 값 PUT 200, `Updating` → `Succeeded` |
| AC-08 | 202 `Patching`, 헤더 둘, → `Succeeded`, tags `{"env": "e2e", "ac": "08"}`. 그동안 클라이언트 I/O 루프 694회, rc 0 |
| AC-09 | DELETE 3.0 s, 다시 DELETE 204. 새 마운트 rc 32(`Host is unreachable`), 인스턴스·LV·ns 없음. 씬 풀 0.00 → 0.02 → 0.00%. 미리 마운트한 클라이언트는 `I/O error` / `Stale file handle`. 같은 토큰으로 다시 만들면 IP .129 재사용, 마운트 rc 0 |
| AC-10 | PUT·PATCH·DELETE 모두 `409 RequestConflict`, 작업 `[CREATE]` 하나, 원래 작업 `Succeeded` |
| AC-11 | 실패 주입: `Failed`·`InternalServerError`, 볼륨 `Failed`, 예약 유지(`400 BadRequest`), 데이터 플레인 그대로 → PUT `Succeeded`, 마운트 rc 0. agent 정지: monotonic 60.2 s 뒤 `Failed`, 연결 실패 로그 62줄 → agent를 띄우고 PUT하면 `Succeeded` |
| AC-12 | (a) SIGKILL rc −9, 작업 `CREATE/Creating` → `Succeeded`, 마운트 rc 0, LV 하나. (b) job 시작 / LV 생성 / 마운트 단계에서 kill → 4.5 / 2.5 / 3.4 s 뒤 `Succeeded`, 그 UUID의 LV 하나, 마운트 rc 0. (c) 인스턴스 `exited`·언마운트 상태에서 마운트 rc 32 → agent 시작 뒤 같은 IP .129로 running, `before-restart` 읽음. `docker start` 경로에서도 준비 표시를 기다렸다(serving 줄 2개, 재시작 0) |
| AC-13 | POST `success`, 다시 POST `success`·LV 하나, 다른 경로 `failure`, `?name=` 1건, 없는 uuid DELETE `success`, 잘못된 경로 5개 모두 400 |
| AC-15 | IP .129·.130, `addr=`가 각자의 IP, `ss`에 2049 연결 2개 |

### [PASS] AC-14 회귀
- 1회차 결과(63 passed)를 유지한다. 2회차 CI 재현의 junit에도 계정·풀 live e2e 63개가 있고 모두 통과했다.

### [PASS] 통합 테스트
- 실행한 명령: `wsl -d Ubuntu -u root … python -m pytest -p no:cacheprovider backend/tests/integration -q -rfEs`
- 출력: `4 passed in 32.51s`. 1회차의 131.91 s(유예 기간 추정)와 달리 리더 기록(32.7 s)과 같다.

### [PASS] CI 명령 로컬 재현
- 실행한 명령: scratchpad `ci_repro.sh`(일반 사용자, 포트 18080). 볼륨 e2e와 동시에 돌렸다.
- 출력:
  - lint: `ruff 0.14.0`, `All checks passed!`
  - test: `ANF_E2E_API_URL=http://127.0.0.1:18080 python -m pytest -m "not dataplane"` → `579 passed, 25 deselected in 149.31s`
  - skip 검사: `collected 579, skipped 0, failures 0, errors 0`, 선택된 데이터 플레인 파일 `[]`(`test_volume_(contract|data|recovery)_live`와 `test_flexvol_linux`가 없다)
  - `-m dataplane` 수집 25개 = 볼륨 e2e 21 + 통합 4. deselected 25와 같다
  - hook tests: `25 passed in 9.13s`

### [UNVERIFIED] GitHub Actions 실제 실행
- push가 필요하다. push는 사용자가 정한다.

## e2e 파일 분리 (사용자 요청)

| 파일 | 줄 수 | 내용 |
| --- | --- | --- |
| `backend/tests/e2e/dataplane_live.py` | 531 | 테스트가 아닌 도우미 모듈(`live_api.py`와 같은 자리). 상수, `ApiServer`, `Agent`, `Client`, 픽스처 `agent`·`api`·`clients`, 데이터 플레인 관찰, ARM 볼륨 도우미, 인스턴스 준비 확인(`instance_status`, `instance_ok`), 진입점 로그 수집(`InstanceLogs`) |
| `backend/tests/e2e/test_volume_contract_live.py` | 463 | AC-01, 05, 06, 07, 08, 10, 13 (테스트 7개) |
| `backend/tests/e2e/test_volume_data_live.py` | 272 | AC-02, 03, 04(×2), 09, 15, 유예 기간 반복 시험 (테스트 7개) |
| `backend/tests/e2e/test_volume_recovery_live.py` | 202 | AC-11(×2), AC-12a, 12b(×3), 12c (테스트 7개) |
| `backend/tests/e2e/conftest.py` | 25 (+3) | `from dataplane_live import agent, api, clients  # noqa: F401`. 픽스처를 도우미 모듈에 두고 conftest에서 등록한다. 시험 파일이 직접 import하면 ruff F811(인자가 import를 가림)이 난다 |
| `backend/tests/e2e/test_volume_live.py` | 삭제 | 1회차 원본은 scratchpad `test_volume_live.r1.py`에 남겼다 |

- 옮긴 방법: scratchpad `split_volume_e2e.py`가 원본을 `ast`로 읽어 최상위 정의를 그대로 잘라 붙였다. 대조 결과 최상위 블록 78개 가운데 77개가 바이트 그대로 새 파일에 있다. 나머지 하나는 `pytestmark`다. 각 시험 파일에서 `[e2e, dataplane, SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]`로 다시 썼고, 마커와 skip 조건은 같다.
- 각 파일 맨 위 docstring에 확인하는 AC와 실행 명령을 적었다. 세 파일을 한 번에 돌리려면 `-m dataplane backend/tests/e2e`.
- 옮긴 뒤 일부러 바꾼 것 (모두 `test_volume_data_live.py`와 도우미, 약하게 바꾼 것은 없다):
  - 제품의 진입점 로그가 바뀌어(`grace_ended=` 없음, 유예 기간이 끝난 뒤에만 `serving … attempts=n`) `instance_grace_line`을 `instance_status`로 바꿨다. 준비 표시 `/run/anf-ready`, 인스턴스 안 `/proc/fs/nfsd/v4_end_grace`, serving 줄, 재시작 수를 직접 본다.
  - AC-03·AC-15의 첫 쓰기 한도를 60 s에서 `FIRST_IO_SECONDS = 10` s로 좁혔다. 반복 시험에도 같은 한도를 넣었다.
  - 반복 시험은 라운드마다 두 번째 볼륨부터(job 직후) 마운트하고, job 시간과 재시작 수를 기록한다.
  - `agent` 픽스처가 `InstanceLogs`를 띄우고, 끝날 때 `[instance logs]` 증거를 남긴다(판정용 기록이며 단언은 아니다).
- ruff 0.14.0: `All checks passed!` (Windows `uvx`, WSL CI 재현 둘 다). Windows 수집: e2e 84개, import 오류 없음.

## 측정값

| 항목 | 값 | 횟수 |
| --- | --- | --- |
| knfsd 시작 중 재시작(첫 시도 실패) | 5 / 64 (7.8%), 모두 두 번째 시도에서 성공 | 이번 실행 전체 |
| agent job 시간 (반복 시험, NFSv4.1 1 GiB) | 1.21~5.69 s, 평균 1.59 s. 재시작한 것 3.84~5.69 s | 40 |
| 첫 NFSv4.1 쓰기 (마운트 포함) | 0.61~3.25 s | 40 |
| AC-03 / AC-15 첫 I/O | 0.22 s / 0.35 s | 1 / 1 |
| NFSv3 100 GiB 생성 → `Succeeded` (AC-01) | 2.12 s | 1 |
| DELETE → `Succeeded` (AC-09) | 3.0 s | 1 |
| agent 재시작 뒤 `Succeeded` (AC-12b) | 4.5 / 2.5 / 3.4 s | 3 |
| 볼륨 e2e 전체 | 530.55 s (1회차 r1c 364.59 s. 반복 시험이 12개에서 40개로 늘었고 agent가 파일마다 뜬다) | 1 |
| 통합 테스트 | 32.51 s | 1 |
| CI 재현 테스트 단계 | 149.31 s | 1 |

## 정리 상태 (검증 끝)

- 서버 프로세스: `pgrep -af "[u]vicorn|[s]torage_agent"` 없음(rc 1). 8080·8090·18080 수신 없음
- 컨테이너 0개(`anf-nfs-*`, `anfe2e-cli-*` 없음). `lvs anf`에 `aggr0`만. `/var/lib/anf-clone/ns` 아래 마운트·디렉터리 없음. 시험 파일 세 개의 teardown이 모두 `leftovers_deleted: []`, 씬 풀 0.00%
- 지운 것: `/tmp/anf-vol-e2e-*` DB 디렉터리 19개, ruff 임시 설치
- 남긴 것: aggregate, 이미지(`anf-nfs-server:latest`, `anf-nfs-client:latest`·`:spike`), `anf-vnet`
- 증거(WSL): `/tmp/anf-vol-e2e-r2.out`, `/tmp/anf-vol-e2e-r2.jsonl`, `/tmp/anf-ci-repro-r2.out`, `/tmp/anf-ci-repro-r2/pytest-results.xml`, agent 로그 `/tmp/pytest-of-root/pytest-8/agent*/agent.log`. 사본은 scratchpad에 있다.
