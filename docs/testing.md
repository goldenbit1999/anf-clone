# 테스트

ANF 클론의 테스트 층, 실행 명령, 그리고 PRD §6.1 수락 기준마다 그것을 확인하는 테스트를 한곳에 모은다 (FR-10).
설계는 `_workspace/test-automation/02_main_design.md`, 층의 원칙은 [ADR §9](ADR.md#9-테스트와-ci)에 있다.

## 1. 테스트 층

| 층 | 위치 | 마커 | 확인하는 것 | 필요 조건 |
| --- | --- | --- | --- | --- |
| 단위 | `backend/tests/unit` (15개 파일) | 없음 | 본문 규칙, 상태 전이, 용량·처리량 계산, agent의 명령 순서. 커널 명령은 가짜 실행기로 바꾼다 | 없음 |
| API 계약 | `backend/tests/contract` (6개) | 없음 | ARM 경로, 응답 코드, 헤더, LRO 흐름. FastAPI TestClient와 가짜 storage agent | 없음 |
| 컨트롤 플레인 e2e | `backend/tests/e2e/test_netapp_account_*`, `test_capacity_pool_*` (4개) | `e2e` | 실제 uvicorn 프로세스에 HTTP로 계약, 상태 전이, 결함 주입, SIGKILL 재시작 | `ANF_E2E_API_URL` |
| 통합 | `backend/tests/integration` (1개) | `integration`, `dataplane` | storage agent의 볼륨 관리자가 실제 LVM·ext4·knfsd 인스턴스·tc로 볼륨, 스냅샷, 되돌리기, 새 볼륨, 처리량 한도를 만들고 클라이언트 컨테이너가 마운트한다 | Linux, root, 데이터 플레인 준비 |
| 데이터 플레인 e2e | `backend/tests/e2e/test_volume_*`, `test_snapshot_*`, `test_restore_*`, `test_throughput_*` (12개) | `e2e`, `dataplane` | anf-api(일반 사용자)와 agent(root)를 띄우고 ARM으로 만든 볼륨을 클라이언트 컨테이너가 마운트해 PRD 수락 기준의 데이터 효과를 본다 | 위 조건과 `ANF_E2E_API_URL` |
| 훅 | `.claude/hooks/tests` | 없음 | TDD 훅의 판정 | 없음 (기본 `testpaths` 밖) |
| 프론트엔드 | `frontend/src/*.test.ts(x)` | — | 대시보드의 읽기, 2초 폴링, 렌더링 (Vitest) | Node 22 (Windows) |

`dataplane` 마커가 붙은 테스트는 113개다(통합 30, 데이터 플레인 e2e 83). 나머지 `python -m pytest`의 대상은 988개다.

## 2. 어디서 무엇이 도는가

| 어디서 | 명령 (저장소 루트) | 도는 것 | skip |
| --- | --- | --- | --- |
| Windows, TDD 훅 | 훅이 `.venv-win\Scripts\python -m pytest`로 짝 테스트(Write·Edit 뒤)와 전체(종료 때)를 돌린다 | 단위, 계약 | e2e와 통합은 skip한다(`ANF_E2E_API_URL` 없음, root 아님). 훅은 모두 skip된 실행을 GREEN이 아니라 SKIPPED로 알린다 |
| WSL, 일반 사용자 | `ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest -m "not dataplane"` | 단위, 계약, 컨트롤 플레인 e2e | 0이어야 한다 |
| WSL, root | `scripts/run-dataplane-tests.sh` (§3) | 통합, 데이터 플레인 e2e | 0이어야 한다. 실행기가 실패로 센다 |
| CI `backend` 작업 | lint, 위 WSL 일반 사용자 명령과 같은 pytest(`--junitxml`), `python backend/tests/junit_gate.py pytest-results.xml`, 훅 테스트 | 단위, 계약, 컨트롤 플레인 e2e, 훅 | `junit_gate.py`가 실패로 센다 |
| CI `frontend` 작업 | `frontend/`에서 `npm ci`, `npm run typecheck`, `npm test`, `npm run build` | 프론트엔드 | — |
| CI `data-plane` 작업 | 호스트 러너에서 `sudo bash scripts/setup-wsl-dataplane.sh` 뒤 위 WSL root 명령을 두 조각으로 (§3 "CI에서") | 통합, 데이터 플레인 e2e | 0이어야 한다. 실행기가 실패로 센다 |
| Windows, 프론트엔드 | `frontend/`에서 `npm test` | 프론트엔드 | — |

**skip은 PASS가 아니다** (PRD §8, ADR §9.1). pytest는 skip만 있어도 0으로 끝나므로, CI와 데이터 플레인 실행기는 같은
스크립트 `backend/tests/junit_gate.py`로 JUnit XML을 읽어 수집 0개, skip, 실패, 오류, 읽을 수 없는 XML을 실패로 판정한다.
CI `backend` 작업은 데이터 플레인 테스트를 skip하지 않고 마커로 선택에서 뺀다(`-m "not dataplane"`).
그 테스트는 `data-plane` 작업이 실행기로 돌린다.

## 3. 데이터 플레인 실행기

```bash
# Windows(Git Bash)에서
MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash /mnt/c/Users/mkimh/Projects/ANF-clone/scripts/run-dataplane-tests.sh
# WSL root 셸에서, 저장소 루트
scripts/run-dataplane-tests.sh [경로·pytest 옵션...]
```

- 인자에 경로가 없으면 `backend/tests/integration`과 `backend/tests/e2e`에서 `dataplane` 테스트가 있는 파일 전부를 돈다.
  대상 파일은 `pytest --collect-only -m dataplane`의 결과에서 얻으므로 새 테스트 파일도 저절로 들어간다.
- 경로(파일, 폴더, node ID)를 주면 그것만 돈다. 그 밖의 인자(`-k`, `-x` 등)는 pytest에 그대로 넘긴다. 값이 경로인
  옵션은 `--deselect=<node ID>`처럼 `=`로 붙여 쓴다(따로 쓰면 경로로 읽힌다).
- 처음 준비는 `scripts/setup-wsl-dataplane.sh`(CLAUDE.md Commands)다. 실행기는 준비를 하지 않고 확인만 한다.

### 순서

1. **사전 점검.** Linux, root, venv와 pytest, Docker Engine, 이미지 `anf-nfs-server`·`anf-nfs-client`, 네트워크
   `anf-vnet`(172.30.0.0/24, ip-range /25), `nfsd` 모듈, `fs.leases-enable = 0`, 포트 8080·8090이 비어 있음.
   하나라도 빠지면 원인 한 줄을 쓰고 테스트를 돌리지 않는다(종료 코드 2). 포트가 차 있으면 다른 세션이 데이터 플레인을
   쓰고 있을 수 있으므로 건드리지 않는다.
2. **VG `anf` 붙이기.** WSL이 다시 뜨면 loop 장치가 사라져 VG가 보이지 않고, 그대로 두면 모든 e2e가 setup 오류다.
   붙어 있지 않으면 agent가 시작할 때 부르는 `FlexVolManager.ensure_aggregate()`를 그대로 불러 붙인다.
3. **기준선.** 실행 전의 LV와 컨테이너를 `baseline.txt`에 남긴다.
4. **파일마다 pytest 한 번.** 그 전에 `sync`와 `echo 3 > /proc/sys/vm/drop_caches`로 page cache를 비운다. 한 프로세스로
   이어 돌리면 page cache가 6.8 GB까지 차서 호스트가 실행기를 죽인 적이 있다(FR-08). 실패한 파일이 있어도 끝까지 돈다.
5. **남은 것 검사.** 기준선에 없던 LV, 컨테이너, 8080·8090 리스너를 출력하고 실패로 센다. 지우지는 않는다(정리 결함의
   단서다). 실행 전에 있던 볼륨의 인스턴스(`anf-nfs-<uuid>`)는 시작 복구가 다시 띄운 것이라 세지 않는다.
6. **판정.** `junit_gate.py`가 파일별·합계 표(수집, 통과, 실패, 오류, skip, 초)를 출력한다.

### 환경 변수

| 변수 | 기본 | 뜻 |
| --- | --- | --- |
| `ANF_CLONE_VENV` | 저장소 주인(`stat -c %u`)의 `~/.venvs/anf-clone` | root의 `~`는 `/root`라서 주인의 venv를 쓴다 |
| `ANF_TEST_OUT` | `/var/tmp/anf-clone-tests/<UTC 시각>` | 출력 폴더 |
| `ANF_E2E_API_URL` | `http://127.0.0.1:8080` | e2e가 anf-api를 띄울 주소. 일부러 빈 값으로 두면 e2e가 skip하고, 실행기가 실패로 센다 |
| `ANF_E2E_USER`, `ANF_E2E_FIO_RUNS`, `ANF_E2E_REPEAT` | 각 도우미의 기본 | 그대로 테스트에 전달된다 (`backend/tests/e2e/dataplane_live.py`, `throughput_live.py`) |

### 출력

출력 폴더는 WSL 디스크에 둔다. `/mnt/c`(9P)에 바로 쓰면 요청이 많은 e2e가 3~4배 느려지고, `/tmp`는 WSL이 꺼지면 사라진다.
보관이 필요하면 부르는 쪽(verifier, CI)이 복사한다.

| 파일 | 내용 |
| --- | --- |
| `<테스트 파일>.log` | 그 파일의 pytest 출력(`-v`) |
| `<테스트 파일>.xml` | JUnit XML |
| `<테스트 파일>.jsonl` | e2e의 HTTP 요청·응답, 서버 이벤트, 판정 근거(`note`)를 담은 `ANF_E2E_LOG` |
| `collect.log`, `baseline.txt`, `files.tsv` | 수집 결과, 실행 전 LV·컨테이너, 파일별 pytest 종료 코드와 초 |
| `summary.txt` | 파일별·합계 표, 시간, 남은 것, 종료 코드 |

### 종료 코드

| 코드 | 뜻 |
| --- | --- |
| 0 | 수집 1개 이상, 전부 통과, skip 0, 남은 것 없음 |
| 1 | 실패·오류·skip이 있거나, 수집이 0개거나, 남은 것이 있거나, pytest가 죽어 XML이 없거나 0이 아닌 코드로 끝난 파일이 있다 |
| 2 | 사전 점검 실패. 테스트를 돌리지 않았다 |

### 소요 시간

인자 없는 전체 실행 한 번의 실측이다 (2026-11-10, WSL2 Ubuntu 24.04, 113개 테스트, 13개 파일, 단조 시계로 5,279초 = 약 88분).

| 파일 | 테스트 | 초 |
| --- | --- | --- |
| `integration/test_flexvol_linux.py` | 30 | 421 |
| `e2e/test_restore_new_volume_contract_live.py` | 8 | 376 |
| `e2e/test_restore_new_volume_data_live.py` | 5 | 238 |
| `e2e/test_snapshot_contract_live.py` | 5 | 105 |
| `e2e/test_snapshot_data_live.py` | 8 | 205 |
| `e2e/test_snapshot_recovery_live.py` | 5 | 254 |
| `e2e/test_snapshot_revert_contract_live.py` | 11 | 517 |
| `e2e/test_snapshot_revert_data_live.py` | 5 | 162 |
| `e2e/test_throughput_limit_contract_live.py` | 8 | 255 |
| `e2e/test_throughput_limit_data_live.py` | 7 | 2,250 |
| `e2e/test_volume_contract_live.py` | 7 | 110 |
| `e2e/test_volume_data_live.py` | 7 | 214 |
| `e2e/test_volume_recovery_live.py` | 7 | 161 |

처리량 데이터 파일이 전체의 43%다. 한도가 걸린 채로 데이터를 실제로 흘려 재는 시험이라 줄일 수 없다. 이렇게 긴 실행은 도구 호출 하나에 붙여 두지 말고 WSL 안에서 분리해 띄운다(`setsid nohup bash scripts/run-dataplane-tests.sh > <로그> 2>&1 &`). Windows 호스트의 메모리가 부족해지면 붙어 있던 명령이 강제 종료되고, 그때 돌던 테스트의 볼륨과 컨테이너가 남는다.

### CI에서

`.github/workflows/ci.yml`의 `data-plane` 작업이 GitHub 호스트 러너(`ubuntu-24.04`)에서 같은 준비 스크립트와 실행기를
sudo로 돌린다 (FR-11, 스파이크 S3, 설계 `_workspace/ci/02_main_design_dataplane.md`).

- **언제**: main 대상 PR, main push, 손으로 돌릴 때(`workflow_dispatch`). 기능 브랜치 push에서는 돌지 않는다(PR과 겹친다).
- **두 조각(matrix)**: `throughput`은 `backend/tests/e2e/test_throughput_limit_data_live.py` 하나, `rest`는 그 파일을
  `--ignore=`로 뺀 나머지 전부다. 조각마다 자기 VM에서 준비부터 하고, 한 조각이 실패해도 다른 조각은 끝까지 돈다.
  `rest`는 파일을 나열하지 않으므로 새 데이터 플레인 테스트 파일이 저절로 들어간다.
- **판정**: 실행기의 종료 코드 하나다(위 표). 조각마다 75분이 넘으면 멈춘 것으로 본다.
- **산출물**: 조각마다 실행기 출력 폴더와 `dmesg.txt`가 artifact `dataplane-<조각>-<시도 번호>`로 14일 남는다.
- **러너**: 모듈과 패키지가 이미 있어 설치 단계가 없다(S3). 커널은 WSL과 다르다(러너 7.0 azure, WSL 6.18). `/`가
  systemd 기본값대로 shared라, agent는 ns 바인드를 private로 떼어 낸 뒤 rshared로 만든다. 그러지 않으면 ns 바인드가
  `/`의 peer group에 들어가 ns 아래 마운트가 호스트 마운트 표에 두 번 나온다(S3 Q7). 작업 로그의 "Runner info"와
  "Mount propagation of ns" 단계가 이 상태를 남긴다.

## 4. 수락 기준과 테스트

PRD §6.1 FR-01~FR-08의 수락 기준 문장마다 그것을 확인하는 테스트다. node ID는 저장소 루트 기준이고,
`backend/tests/unit/test_testing_doc.py`가 모두 수집되는지 확인한다. 데이터 플레인 테스트(`dataplane` 마커)는
§3의 실행기로, 나머지는 §2의 WSL 일반 사용자 명령으로 돈다. 판정 근거는 각 테스트의 단언과 `.jsonl`의 `evidence` 기록이다.

| FR | 수락 기준 (PRD §6.1) | 테스트 | 클라이언트에서 관찰하는 것 |
| --- | --- | --- | --- |
| FR-01 | 비동기 작업의 응답이 작업 완료 전에 온다. | `backend/tests/e2e/test_netapp_account_lro_faults_live.py::test_ac08_in_progress_states_with_injected_delay` | 생성에 5 s 지연을 주입한 PUT이 1 s 안에 201로 오고, 그 직후 작업 상태가 `Creating`(0%), 리소스가 `Creating`이다. 5 s 뒤 `Succeeded` |
| FR-01 | 추적 URL을 폴링하면 종결 상태(`Succeeded`, `Failed`, `Canceled`)에 도달한다. | `backend/tests/e2e/test_netapp_account_live.py::test_ac01_create_returns_201_creating_and_operation_succeeds`<br>`backend/tests/e2e/test_netapp_account_lro_faults_live.py::test_ac09_injected_create_failure_then_recovery` | `Azure-AsyncOperation` URL을 1 s마다 GET해 `Succeeded`(100%, `endTime`)나 `Failed`에 닿는다. 클론에는 `Canceled`로 끝나는 경로가 없다(종결 상태 집합에만 있다) |
| FR-01 | 실패하면 리소스가 `Failed`가 되고 오류 코드와 메시지를 보여 준다. | `backend/tests/e2e/test_netapp_account_lro_faults_live.py::test_ac09_injected_create_failure_then_recovery`<br>`backend/tests/e2e/test_netapp_account_lro_faults_live.py::test_ac09_injected_delete_failure_leaves_account_failed`<br>`backend/tests/e2e/test_volume_recovery_live.py::test_ac11_agent_down_fails_after_retry_then_put_recovers` | 실패 주입 뒤 작업 상태가 `Failed`이고 `error.code`·`error.message`가 있으며, Location URL은 500 오류 본문, 리소스 GET은 `Failed`다. 볼륨은 agent가 내려가 있으면 재시도 뒤 작업이 `Failed`(`InternalServerError`), 볼륨이 `Failed`가 되고, 같은 PUT으로 회복해 클라이언트가 마운트한다 |
| FR-01 | 동기 `200`, 본문 없는 `204`, 비동기 `202`를 공통 규칙이 잘못 거절하지 않는다. | `backend/tests/e2e/test_netapp_account_live.py::test_ac05_patch_tags_is_synchronous_and_replaces_map`<br>`backend/tests/e2e/test_netapp_account_live.py::test_ac07_delete_returns_202_with_both_headers_then_resource_is_gone`<br>`backend/tests/e2e/test_snapshot_revert_contract_live.py::test_ac01_revert_contract_and_states` | tags만 바꾼 계정 PATCH가 추적 헤더 없는 `200`, DELETE가 본문 없는 `202`와 두 헤더, 없는 계정의 DELETE가 본문 없는 `204`, 되돌리기 POST가 본문 없는 `202`다 |
| FR-01 | 폴링 간격(`Retry-After`)과 제한 시간, 실패 시나리오는 계정 설계에서 정한다. | `backend/tests/e2e/test_netapp_account_live.py::test_ac01_create_returns_201_creating_and_operation_succeeds`<br>`backend/tests/e2e/test_netapp_account_lro_faults_live.py::test_ac11_operation_resumes_after_sigkill_restart[restart-without-faults]` | 계정 설계가 정한 대로 응답에 `Retry-After`가 없다(설계 결정 5). 클라이언트는 1 s 간격, 30 s(지연을 주입하면 지연 + 30 s) 안에 종결 상태를 본다. 실패 시나리오(주입 실패, 지연 중 SIGKILL 뒤 재개)는 이 행과 위 행의 테스트다 |
| FR-02 | 상태 전이가 FR-01을 따른다. | `backend/tests/e2e/test_netapp_account_live.py::test_ac01_create_returns_201_creating_and_operation_succeeds`<br>`backend/tests/e2e/test_netapp_account_live.py::test_ac02_put_existing_returns_200_updating_and_replaces_tags`<br>`backend/tests/e2e/test_netapp_account_live.py::test_ac07_delete_returns_202_with_both_headers_then_resource_is_gone` | PUT `201` `Creating` → `Succeeded`, 같은 계정 PUT `200` `Updating` → `Succeeded`, DELETE `202` → 작업 `Succeeded` 뒤 GET `404` |
| FR-02 | 자식 용량 풀이 남아 있으면 삭제가 409로 거절되고 풀은 그대로 남는다. | `backend/tests/e2e/test_capacity_pool_live.py::test_ac09_account_with_pool_cannot_be_deleted_until_pool_is_gone` | 계정 DELETE가 `409` `CannotDeleteResource`(메시지에 풀 ID)이고 작업이 생기지 않으며 계정과 풀이 모두 `Succeeded`다. 풀을 지운 뒤에는 계정 DELETE가 `202`로 끝난다 |
| FR-02 | 이 409 기준의 실환경 검증은 용량 풀 사이클에서 한다. 검사 로직은 계정 사이클에서 구현하고 계약 테스트로 확인한다. | `backend/tests/contract/test_arm_app.py::test_delete_with_child_resource_is_409_cannot_delete_resource`<br>`backend/tests/contract/test_capacity_pools_api.py::test_ac09_account_with_pool_cannot_be_deleted_until_pool_is_gone` | 계약 층(TestClient): 자식이 있는 계정 DELETE가 `409` `CannotDeleteResource`. 실환경은 위 행 |
| FR-03 | 볼륨 할당량의 합이 풀 크기를 넘게 되는 볼륨 생성은 거절된다. | `backend/tests/e2e/test_volume_contract_live.py::test_ac05_capacity_and_parent_rules` | 1 GiB 볼륨이 있는 4 TiB 풀에 4 TiB 볼륨 PUT이 `400` `BadRequest` "Pool size too small for total volume size."이고, 작업도 LV도 생기지 않는다 |
| FR-03 | 볼륨이 남은 풀의 삭제는 거절된다. | `backend/tests/e2e/test_volume_contract_live.py::test_ac05_capacity_and_parent_rules`<br>`backend/tests/contract/test_capacity_pools_api.py::test_cv1_pool_with_volume_cannot_be_deleted` | 볼륨이 있는 풀의 DELETE가 `409` `CannotDeleteResource`(메시지에 볼륨 ID)이고 풀은 `Succeeded`로 남는다 |
| FR-03 | 볼륨이 필요한 이 기준들과 풀 축소 하한의 실환경 검증은 볼륨 사이클에서 한다. 풀 쪽 검사는 풀 사이클에서 구현하고 계약 테스트로 확인한다. | `backend/tests/e2e/test_volume_contract_live.py::test_ac05_capacity_and_parent_rules` | 볼륨 예약(1,025 GiB)이 있는 2 TiB 풀을 1 TiB로 줄이는 PATCH와 PUT이 모두 `400` `BadRequest`이고 풀 크기가 그대로다. 위 두 행도 같은 테스트(실환경)다 |
| FR-04 | 클라이언트 컨테이너가 `<마운트 IP>:/<creationToken>`을 지정한 NFS 버전으로 마운트하고 읽고 쓸 수 있다. | `backend/tests/e2e/test_volume_data_live.py::test_ac02_nfsv3_mount_two_clients`<br>`backend/tests/e2e/test_volume_data_live.py::test_ac03_nfsv41_volume`<br>`backend/tests/integration/test_flexvol_linux.py::test_create_mount_delete[nfs3]`<br>`backend/tests/integration/test_flexvol_linux.py::test_create_mount_delete[nfs4.1]` | NFSv3: 클라이언트 A가 `mountTargets[0].ipAddress:/<creationToken>`에 쓰고 B가 같은 내용을 읽는다. `/proc/mounts`에 `vers=3`와 그 IP가 있고, 같은 볼륨의 `vers=4.1` 마운트는 "Protocol not supported"로 거절된다. NFSv4.1: 쓰기·읽기, 첫 쓰기가 10 s 안, `vers=3`·`4.0`은 거절 |
| FR-04 | 할당량을 넘는 쓰기는 실패한다. | `backend/tests/e2e/test_volume_data_live.py::test_ac04_quota_full_write_fails[NFSv3-3]`<br>`backend/tests/e2e/test_volume_data_live.py::test_ac04_quota_full_write_fails[NFSv4.1-4.1]` | 1 GiB 볼륨의 `df` 크기가 0.9~1 GiB이고, 1,229 MiB `dd`가 "No space left on device"로 실패하며, 먼저 쓴 파일은 그대로 읽힌다 |
| FR-04 | 볼륨을 지우면 더 이상 마운트되지 않는다. | `backend/tests/e2e/test_volume_data_live.py::test_ac09_delete_volume` | DELETE `202` → `Succeeded` 뒤 새 클라이언트의 마운트가 실패하고, 그 볼륨의 인스턴스 컨테이너·LV·export 경로가 없다. 다시 DELETE는 `204`. 같은 이름으로 다시 만들면 같은 IP로 빈 볼륨이 마운트된다 |
| FR-05 | 스냅샷을 만든 뒤 지운 파일을 `.snapshot/<이름>/`에서 읽을 수 있다. | `backend/tests/e2e/test_snapshot_data_live.py::test_ac02_ac03_snapshot_keeps_point_in_time_content[AC-02-NFSv3-3]`<br>`backend/tests/e2e/test_snapshot_data_live.py::test_ac02_ac03_snapshot_keeps_point_in_time_content[AC-03-NFSv4.1-4.1]`<br>`backend/tests/integration/test_flexvol_linux.py::test_snapshot_is_a_read_only_point_in_time_copy[nfs3]` | 스냅샷 `S` 뒤에 `A`를 지우고 `d/B`와 64 MiB 파일을 덮어쓴 클라이언트가 `/m/.snapshot/S/`에서 스냅샷 시점의 `A`·`d/B`와 같은 sha256을 읽는다. 새로 마운트한 다른 클라이언트도 같다 |
| FR-05 | 스냅샷 안의 파일은 바꿀 수 없다. | `backend/tests/e2e/test_snapshot_data_live.py::test_ac04_snapshot_and_snapshot_dir_are_immutable[NFSv3-3]`<br>`backend/tests/e2e/test_snapshot_data_live.py::test_ac04_snapshot_and_snapshot_dir_are_immutable[NFSv4.1-4.1]` | root 클라이언트의 덧붙이기, 덮어쓰기, 새 파일, 삭제, 이동, `mkdir`, `chmod`가 스냅샷 안과 `.snapshot` 자체에서 모두 실패하고, 서버 쪽 파일·모드·inode가 전후 같으며 `.snapshot`에 immutable 속성이 있다 |
| FR-06 | 되돌린 뒤 볼륨 내용이 스냅샷 시점과 같다. | `backend/tests/e2e/test_snapshot_revert_data_live.py::test_ac02_ac03_revert_restores_snapshot_and_deletes_newer[AC-02-NFSv3-3]`<br>`backend/tests/e2e/test_snapshot_revert_data_live.py::test_ac02_ac03_revert_restores_snapshot_and_deletes_newer[AC-03-NFSv4.1-4.1]`<br>`backend/tests/integration/test_flexvol_linux.py::test_restore_reverts_under_a_mounted_client[nfs3]` | `S2`로 되돌린 볼륨을 새로 마운트한 클라이언트가 보는 트리(내용·모드)가 `S2`와 같고, `S2` 뒤에 만든 파일과 더 새 스냅샷 `S3`가 없으며, `S1`·`S2`는 그대로다. 같은 볼륨을 더 오래된 `S1`로 다시 되돌릴 수 있다 |
| FR-06 | 되돌리기 전에 마운트한 클라이언트가 어떻게 보이는지(다시 마운트가 필요한지)를 기록한다. | `backend/tests/e2e/test_snapshot_revert_data_live.py::test_ac04_mounted_client_follows_revert_without_remount[NFSv3-3]`<br>`backend/tests/e2e/test_snapshot_revert_data_live.py::test_ac04_mounted_client_follows_revert_without_remount[NFSv4.1-4.1]` | 다시 마운트하지 않은 클라이언트의 `/proc/mounts`가 그대로이고, 끝난 것을 본 뒤 1 s 안에 `S2` 내용을 읽는다. 계속 읽는 탐침의 오류가 0이고, 스냅샷 전부터 연 fd는 계속 읽으며, 스냅샷 뒤에 만든 파일을 잡은 fd만 `Stale file handle`이다. 멈춘 창의 길이와 쓰기 기록은 `.jsonl`의 `AC-04` 근거에 남는다 |
| FR-07 | 새 볼륨이 스냅샷 시점의 내용을 갖는다. | `backend/tests/e2e/test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_content_and_independence[AC-02-NFSv3-3-None]`<br>`backend/tests/e2e/test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_content_and_independence[AC-04a-NFSv4.1-4.1-0755]`<br>`backend/tests/integration/test_flexvol_linux.py::test_volume_from_snapshot_has_its_content_and_is_independent[nfs3]` | `S2`로 만든 새 볼륨을 마운트한 클라이언트가 보는 트리가 `S2`와 같다(지운 `A`가 있고 덮어쓴 `K`는 `S2` 내용). `S2` 뒤에 만든 파일은 없고, `.snapshot`에는 base 스냅샷 `S2`만 있다 |
| FR-07 | 새 볼륨에 써도 원본 볼륨과 스냅샷은 바뀌지 않는다. | `backend/tests/e2e/test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_content_and_independence[AC-02-NFSv3-3-None]`<br>`backend/tests/e2e/test_restore_new_volume_data_live.py::test_ac06_new_volume_survives_source_revert_delete_and_agent_restart` | 새 볼륨에 쓴 뒤 원본의 트리, 원본 클라이언트가 보는 `S2`, 새 볼륨의 base 스냅샷이 그대로다. 반대로 원본에 써도 새 볼륨은 그대로다. 원본을 되돌리고, 원본 스냅샷과 원본을 지우고, agent를 다시 띄워도 새 볼륨의 클라이언트는 읽고 쓴다 |
| FR-08 | 클라이언트에서 잰 처리량이 제한 이하다(허용 오차는 설계 단계에서 정한다). | `backend/tests/e2e/test_throughput_limit_data_live.py::test_ac01b_auto_volume_data`<br>`backend/tests/e2e/test_throughput_limit_data_live.py::test_ac02_ac03_manual_volume_data_and_shared_read_write` | 클라이언트 컨테이너의 `fio --direct=1` 순차 쓰기·읽기를 6회 돌려 첫 회를 버린 5회의 중앙값이 한도의 90~101%다(처리량 설계 결정 15). Auto(Ultra 40 GiB = 5 MiB/s)와 Manual(10·20 MiB/s) 모두, 같은 볼륨의 읽기와 쓰기를 함께 돌리면 그 합이 한도 안이다 |
| FR-08 | 제한을 바꾸면 잰 값도 바뀐다. | `backend/tests/e2e/test_throughput_limit_data_live.py::test_ac04_limit_changes_during_io` | I/O를 멈추지 않고 PATCH로 10 → 30 → 5 MiB/s, 다시 PUT으로 10 MiB/s로 바꾸면 2 s 창마다 잰 값이 새 한도의 90~101%로 따라간다. fio 오류 0, 다시 마운트 없음 |
| FR-08 | 제한이 없는 볼륨과의 차이가 측정으로 드러난다. | `backend/tests/e2e/test_throughput_limit_data_live.py::test_ac05_unlimited_volume_next_to_a_limited_one`<br>`backend/tests/integration/test_flexvol_linux.py::test_volume_without_a_limit_has_no_tc` | 같은 클라이언트가 10 MiB/s 볼륨 A와 4,500 MiB/s(Manual 최대) 볼륨 B를 함께 읽으면 B가 A의 10배 이상이고, A는 혼자 읽을 때와 같은 범위다. ARM 볼륨에는 한도가 없는 경우가 없어서(Auto는 할당량으로, Manual은 필수 값으로 정해진다) 4,500 MiB/s를 쓴다. 한도 없이 만든 agent 볼륨에는 tc가 걸리지 않는다(통합) |
| FR-09 | 생성 중인 리소스가 완료 상태로 바뀌는 과정이 새로 고침 없이 보인다. | 프론트엔드 `frontend/src/useResourceTree.test.tsx`("loads at once, then again every 2 s without a page reload")와 브라우저 검증(`_workspace/dashboard/04_verifier_report.md`) | pytest 대상이 아니다. 대시보드 사이클에서 같은 탭이 새로 고침 없이 `Creating` → `Succeeded`를 보였다 |

## 5. 알려진 한계

- **클라이언트와 서버가 같은 커널이다** (ADR R-08). 클라이언트 컨테이너와 knfsd가 같은 WSL 커널·메모리를 쓴다. 처리량
  측정과 page cache 효과는 실제 ANF(별도 VM, 네트워크)와 다를 수 있다. NFS LOCALIO는 꺼져 있다(S0).
- **처리량 판정은 게스트 단조 시계로 한다.** WSL 벽시계는 약 30초마다 뒤로 건너뛴다. 실행기의 시간도 `/proc/uptime`으로 잰다.
- **데이터 플레인은 기기에 하나다.** VG, IP 대역, 포트 8080·8090을 같이 쓰므로 실행기는 한 번에 하나만 돌고, 파일은
  차례로 돈다. 처리량 시험은 다른 I/O와 겹치면 판정이 흔들린다.
