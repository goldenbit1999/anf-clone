# capacity-pool 검증 보고서 — 1회차

- 검증일: 2026-11-07 (로컬 PST). 실행 시각은 UTC 2026-11-08 02:53~03:13
- 검증 대상 코드:
  - 기준 커밋 `e602d11b1c8569064eab3d38156880cdd25aed29` (`git rev-parse HEAD`). 제품 코드는 미커밋이다.
    - 수정(M): `backend/anf_api/accounts.py`, `arm_app.py`, `arm_rules.py`, `lro.py`, `state_store.py`
    - 새 파일(untracked): `backend/anf_api/capacity_pools.py`
    - `pyproject.toml`은 커밋과 같다.
  - 기준 해시는 리더가 정한 명령이다(저장소 루트):
    `cat pyproject.toml backend/anf_api/__init__.py backend/anf_api/accounts.py backend/anf_api/arm_app.py backend/anf_api/arm_rules.py backend/anf_api/capacity_pools.py backend/anf_api/lro.py backend/anf_api/state_store.py | sha256sum`
    = `f58df82db294ebb8061950d4af80ca8e83996e297df8c3a7775952f4bd154723`
  - 검증을 시작할 때(02:53:30Z)와 끝낸 뒤(03:12:23Z)에 Git Bash와 WSL 양쪽에서 계산했고 네 값이 모두 같았다. 리더가 넘긴 값과도 같다.
  - 참고: `git diff HEAD -- pyproject.toml backend/anf_api | sha256sum` = `a3890a595a3871e2f12374351ac1dc6b1f716a878fa66897d1f08f3491a4ac18`. untracked인 `capacity_pools.py`는 이 값에 들어가지 않으므로 기준으로 쓰지 않았다.
- 이번 회차 범위: 전체 (AC-01~AC-13).
  - CV-1~CV-3은 볼륨 사이클로 옮긴 기준이라 판정하지 않았다 (리더 지시, 설계 §8). 실환경에서 볼륨을 만들 방법이 아직 없다.
- 검증 방법:
  - WSL Ubuntu에서 anf-api를 CLAUDE.md의 명령 그대로 **실제 uvicorn 프로세스**로 띄웠다. 요청은 별도 프로세스(pytest)에서 표준 라이브러리 `http.client`로 보냈다. TestClient는 쓰지 않았다.
  - 상태 저장소(`ANF_API_DB`)는 시나리오마다 `/tmp`(ext4) 아래 새 임시 파일이다. 기본 경로는 쓰지 않았다.
  - 교차 확인: 테스트 도구와 무관하게 서버를 손으로 띄우고 `curl -i`로 원시 헤더를 봤다 (AC-01, AC-04, AC-08, 추가 관찰 1).
- 검증 스크립트 (제품 코드는 고치지 않았다):
  - `backend/tests/e2e/test_capacity_pool_live.py` (새로 만듦): AC-01~AC-09. AC-07은 "계정 없음" 부분만.
  - `backend/tests/e2e/test_capacity_pool_lro_faults_live.py` (새로 만듦): AC-07의 "계정 Deleting 중" 부분, AC-10~AC-12, 결함 키 기동 검사(추가 관찰).
  - `backend/tests/e2e/live_api.py` (확장): `POOL_TYPE`, `TIB`, `pool_path`, `pool_url`, `pool_list_url`, `create_pool`, `db_resources`를 더했다. 기존 함수는 바꾸지 않았고 계정 스크립트가 그대로 돈다(계정 2회차 보고서).
  - `backend/tests/e2e/test_netapp_account_lro_faults_live.py` (한 경우 추가): 기동 검사에 `netAppAccounts/patch` 거절을 더했다 (계정 2회차 보고서 AC-09).
  - 모두 `e2e` 마커가 붙어 있고 `ANF_E2E_API_URL`이 없으면 skip한다. 기본 실행(WSL, `ANF_E2E_API_URL` 없음) 결과는 `277 passed, 62 skipped`다.
- 재현 명령 (WSL, 저장소 루트):
  ```
  ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/tmp/anf-e2e-pool.jsonl \
    ~/.venvs/anf-clone/bin/python -m pytest backend/tests/e2e/test_capacity_pool_live.py \
    backend/tests/e2e/test_capacity_pool_lro_faults_live.py -m e2e -v -p no:cacheprovider
  ```
  AC-13은 셸에서 root로 따로 비교한다 (명령은 AC-13 항목에 있다).

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`에서 `Ubuntu Running 2`. 커널 `6.18.54.1-microsoft-standard-WSL2`, Ubuntu 24.04.1 LTS |
| Python 가상환경 | `~/.venvs/anf-clone`: Python 3.12.3, fastapi 0.162.2, uvicorn 0.54.0, starlette 1.10.0, pytest 9.2.0 |
| 포트 `127.0.0.1:8080` | 시작 전에 비어 있었다(`ss -ltn`에 0줄). 끝난 뒤에도 비어 있고 anf-api 프로세스도 남아 있지 않다 |
| 임시 DB 위치 | `/tmp`는 ext4(`/dev/sdd`)다. 계정 설계 결정 10의 9P 회피 조건을 충족한다 |
| 컨트롤 플레인 서비스 | 시나리오마다 테스트가 직접 띄웠다. 준비 여부는 구독 목록 GET이 `200`인지로 확인했다. 기동에 0.62~0.83초 걸렸고, 실패한 기동은 없었다(결함 키 검사의 의도한 기동 실패 2건은 제외) |
| 시계 | WSL 게스트 시계가 호스트보다 약 10% 느리고 벽시계가 약 33초마다 앞으로 건너뛴다. 이번 판정에는 영향이 없다 (추가 관찰 2) |
| root `exportfs` (AC-13) | `/usr/sbin/exportfs`를 root로 쓸 수 있다. `nfs-server`는 `active`다. 현재 export는 0개다 |
| Docker, 커널 모듈 | 순수 컨트롤 플레인 기능이라 점검하지 않았다 (스킬 §0, 리더 지시) |

## 결과 요약

PASS 13 / FAIL 0 / UNVERIFIED 0

- 풀 e2e 두 모듈(38개 테스트)을 세 번 실행했고 세 번 모두 전부 통과했다.
  - 1회: 모듈별로 나눠 실행했다. AC-13 비교를 사이에 끼우려고 나눴다.
  - 2회, 3회: 계정 모듈까지 e2e 폴더 전체(62개)를 한 번에 실행했다.
- 판정이 바뀐 결과는 없었다. 다만 시각 측정에 환경 요인이 끼었다: WSL 안의 벽시계가 약 33초마다 약 3.3초씩 건너뛰었다. 판정에는 영향이 없다 (추가 관찰 2).

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
| AC-12 | PASS | 1회차 |
| AC-13 | PASS | 1회차 |
| CV-1~CV-3 | 판정 대상 아님 | 볼륨 사이클로 옮김 (설계 §8) |

## 항목별 결과

표기:
- `{SUB}` = `/subscriptions/0e2e0000-1111-4222-8333-444455556666`, `{base}` = `http://127.0.0.1:8080`, `M.N` = `Microsoft.NetApp`
- `acct:X` = `{SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts/X`, `pool:Y` = `.../capacityPools/Y`, `op:Z` = `{SUB}/providers/M.N/locations/westus2/operationResults/Z`
- 모든 경로에는 `?api-version=2026-08-01`이 붙어 있다.
- 풀 본문은 `state / tags / size / serviceLevel / qosType / total / util / enc / cool / poolId 앞 8자`로 줄였다. 원본은 `ANF_E2E_LOG` JSONL에 있다.

### [PASS] AC-01 새 풀 PUT → 201, Creating, Azure-AsyncOperation만 → Succeeded, GET 필드 (계약·상태)
- 기준: `201`, `Creating`, 헤더는 `Azure-AsyncOperation`만(`Location` 없음). 폴링하면 `Succeeded`(`CREATE`). GET 본문에 `name: "{a}/{p}"`, 풀 `type`, UUID `poolId`, `qosType: Auto`, `encryptionType: Single`, `coolAccess: false`, `totalThroughputMibps: 256.0`, `utilizedThroughputMibps: 0.0`.
- 실행: `test_capacity_pool_live.py::test_ac01_create_returns_201_creating_then_succeeded_with_pool_fields`. URL은 정규식 `^{base}{SUB}/providers/Microsoft\.NetApp/locations/westus2/operationResults/{uuid}\?api-version=2026-08-01$`로 확인했다.
- 출력:
  ```
  PUT acct:e2e-pool-acct/pool:e2e-p01  {"location":"westus2","properties":{"size":4398046511104,"serviceLevel":"Premium"}}
  -> 201 (18.1 ms)
     azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/02939a6b-097c-4314-b216-ed47a91d580b?api-version=2026-08-01
     (location 헤더 없음, retry-after 헤더 없음)
     body: {"id":".../capacityPools/e2e-p01","name":"e2e-pool-acct/e2e-p01","type":"Microsoft.NetApp/netAppAccounts/capacityPools",
            "location":"westus2","tags":{},"properties":{"provisioningState":"Creating","poolId":"2a4c2386-13de-40eb-a76f-882f0c77e4f3",
            "serviceLevel":"Premium","size":4398046511104,"qosType":"Auto","totalThroughputMibps":256.0,"utilizedThroughputMibps":0.0,
            "encryptionType":"Single","coolAccess":false}}
  GET op:02939a6b-... -> 200 {"status":"Succeeded","percentComplete":100.0,
        "properties":{"resourceName":"{SUB}/.../capacityPools/e2e-p01","action":"CREATE"},
        "startTime":"2026-11-08T02:57:23.280549Z","endTime":"2026-11-08T02:57:23.287833Z"}
  GET pool:e2e-p01 -> 200 {"id":"{SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts/e2e-pool-acct/capacityPools/e2e-p01",
        "name":"e2e-pool-acct/e2e-p01","type":"Microsoft.NetApp/netAppAccounts/capacityPools","location":"westus2","tags":{},
        "properties":{"provisioningState":"Succeeded","poolId":"2a4c2386-13de-40eb-a76f-882f0c77e4f3","serviceLevel":"Premium",
        "size":4398046511104,"qosType":"Auto","totalThroughputMibps":256.0,"utilizedThroughputMibps":0.0,"encryptionType":"Single","coolAccess":false}}
  ```
- 설계 §4.2의 "201 본문도 GET과 같은 필드"도 확인했다. 201과 GET의 `properties` 키 집합이 같고 `poolId`도 같다.
- curl 교차 확인(추가 관찰 1의 손으로 띄운 서버): `HTTP/1.1 201 Created`. 헤더는 `azure-asyncoperation`, `content-length`, `content-type`, `x-ms-request-id`, `x-ms-correlation-request-id`뿐이고 `location`은 없다.

### [PASS] AC-02 처리량 계산: Standard 2 TiB 32.0, Ultra 1 TiB 128.0, Premium 1 TiB 64.0 (계약)
- 실행: `test_ac02_total_throughput_is_size_tib_times_level_rate` (매개변수 3개)
- 출력 (각각 작업 `Succeeded` 뒤 GET):
  ```
  pool:e2e-p02-standard-2t  size 2199023255552  Standard -> "totalThroughputMibps":32.0,  "utilizedThroughputMibps":0.0
  pool:e2e-p02-ultra-1t     size 1099511627776  Ultra    -> "totalThroughputMibps":128.0, "utilizedThroughputMibps":0.0
  pool:e2e-p02-premium-1t   size 1099511627776  Premium  -> "totalThroughputMibps":64.0,  "utilizedThroughputMibps":0.0
  ```
- AC-01의 4 TiB Premium `256.0`, AC-03의 8 TiB Premium `512.0`, 8 TiB Ultra `1024.0`도 같은 식(2진 TiB × 단가)과 맞다.

### [PASS] AC-03 PUT 갱신 → 200, Updating → Succeeded, tags 교체, 빠진 속성 유지, serviceLevel 변경 (계약·상태)
- 실행: `test_ac03_put_update_returns_200_updating_and_keeps_missing_properties`
- 출력:
  ```
  (생성: tags {"old":"1","keep":"no"}, 4 TiB Premium -> Succeeded, poolId 5b0d6cac)
  PUT pool:e2e-p03 {"location":"westus2","tags":{"new":"2"},"properties":{"size":8796093022208}}
  -> 200, azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/9e501e04-..., location 헤더 없음
     body: state=Updating tags={"new":"2"} size=8TiB Premium total=512.0
  GET op:9e501e04-... -> 200 status=Succeeded pc=100.0 action=UPDATE
  GET pool -> state=Succeeded tags={"new":"2"} size=8TiB Premium qos=Auto total=512.0 poolId=5b0d6cac   (old·keep이 남지 않음)

  PUT pool:e2e-p03 {"location":"westus2","tags":{"t":"3"}}          (properties 없음)
  -> 200 Updating -> op Succeeded (UPDATE)
  GET pool -> state=Succeeded tags={"t":"3"} size=8TiB Premium total=512.0   (size·serviceLevel 유지)

  PUT pool:e2e-p03 {"location":"westus2","tags":{"t":"3"},"properties":{"serviceLevel":"Ultra"}}   (볼륨 없는 풀)
  -> 200 Updating (body: size=8TiB Ultra total=1024.0) -> op Succeeded (UPDATE)
  GET pool -> state=Succeeded size=8TiB Ultra total=1024.0
  ```

### [PASS] AC-04 PATCH → 202, Patching, 두 헤더 → Succeeded(PATCH). size·Manual 반영, Manual → Auto 거절 (계약·상태)
- 실행: `test_ac04_patch_is_async_202_patching_and_manual_to_auto_is_rejected`
- 출력:
  ```
  (생성: tags {"a":"1"}, 4 TiB Premium -> Succeeded)
  PATCH pool:e2e-p04 {"tags":{"b":"2"}}
  -> 202 (18.6 ms)
     azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/ca6e0b56-d6da-4e21-9610-dfa3f37c63f2?api-version=2026-08-01
     location:             {base}{SUB}/providers/M.N/locations/westus2/operationResults/ca6e0b56-...?api-version=2026-08-01&operationResultResponseType=Location
     body: state=Patching tags={"b":"2"} size=4TiB Premium qos=Auto total=256.0
  GET op:ca6e0b56-... -> 200 status=Succeeded pc=100.0 action=PATCH
  GET pool -> state=Succeeded tags={"b":"2"}
  GET <location> -> 200, 본문 = 위 GET 본문과 같음   (설계 §4.1: Location 방식으로 끝난 PATCH는 200 + 풀 본문)

  PATCH {"properties":{"size":8796093022208}} -> 202 Patching -> op Succeeded (PATCH)
  GET pool -> size=8TiB total=512.0 tags={"b":"2"}   (tags 없는 PATCH는 tags 유지)
  PATCH {"properties":{"qosType":"Manual"}}   -> 202 Patching -> op Succeeded (PATCH)
  GET pool -> qos=Manual

  PATCH {"properties":{"qosType":"Auto"}} -> 400 {"error":{"code":"BadRequest","message":"The QoS type of a capacity pool can't be changed from Manual to Auto."}}
  PUT   {"location":"westus2","tags":{"b":"2"},"properties":{"qosType":"Auto"}} -> 400 (같은 code·message)
     두 응답 모두 azure-asyncoperation·location 헤더 없음
  각 거절 뒤 GET pool -> 본문이 거절 전과 같음 (qos=Manual, Succeeded)
  보조 증거: 이 풀의 operations 행 목록이 거절 전후에 같음 (새 작업 없음)
  ```
- curl 교차 확인: `HTTP/1.1 202 Accepted`, `location: ...&operationResultResponseType=Location`, `azure-asyncoperation: ...`, `content-type: application/json`, 본문 `provisioningState: Patching`.

### [PASS] AC-05 계정 안 목록, 다른 계정 목록, 없는 계정 404, 없는 풀 404, 대소문자 (계약)
- 실행: `test_ac05_list_in_account_other_account_missing_and_case_insensitive`
- 출력:
  ```
  GET acct:e2e-pool-acct/capacityPools  -> 200 {"value":[e2e-pool-acct/e2e-p01, .../e2e-p02-premium-1t, .../e2e-p02-standard-2t,
                                                       .../e2e-p02-ultra-1t, .../e2e-p03, .../e2e-p04, e2e-pool-acct/E2e-P05-Mixed]}
                                             (e2e-pool-acct2/e2e-p05-other 없음)
  GET acct:e2e-pool-acct2/capacityPools -> 200 {"value":[e2e-pool-acct2/e2e-p05-other]}   (E2e-P05-Mixed 없음)
  GET acct:e2e-pool-no-such-acct/capacityPools -> 404 {"error":{"code":"ResourceNotFound","message":"The resource with identifier '{SUB}/resourceGroups/rg-e2e/providers/Microsoft.NetApp/netAppAccounts/e2e-pool-no-such-acct' is not found."}}
  GET pool:e2e-p05-missing -> 404 ResourceNotFound ("The resource with identifier '.../capacityPools/e2e-p05-missing' is not found.")
  GET pool:E2E-P05-MIXED -> 200, 본문이 처음 GET(pool:E2e-P05-Mixed)과 같음 (name "e2e-pool-acct/E2e-P05-Mixed")
  GET pool:e2e-p05-mixed -> 200, 같음
  GET acct:E2E-POOL-ACCT/pool:E2e-P05-Mixed -> 200, 같음 (추가 확인: 계정 이름 대소문자)
  ```
- 응답 최상위 키는 `value` 하나다.

### [PASS] AC-06 잘못된 요청 거절, 작업·상태 변화 없음 (계약)
- 실행: `test_ac06_rejected_requests_create_no_operation_and_change_nothing`. 경우마다 매개변수화한 테스트 17개가 모두 통과했다.
- 경우마다 확인한 것:
  - 응답 코드와 `error.code`, `error.message`가 비어 있지 않음
  - `Azure-AsyncOperation`·`Location` 헤더가 없다
  - 요청 전후의 두 계정 풀 목록(id·location·tags·properties 전체)이 같다
  - 기존 풀 `e2e-p06`의 GET 본문이 그대로다
  - 이름이 올바른 새 풀이면 그 이름의 GET이 `404`다 (리소스가 생기지 않음)
  - 보조 증거: 상태 저장소의 `operations` 행 목록과 `resources` 행 목록(id·type·parent_id·상태)이 요청 전후에 같다
- 출력:

  | 요청 | 응답 | error.code / message |
  | --- | --- | --- |
  | PUT `pool:-p` | 400 | `InvalidResourceName` / "The capacity pool name '-p' is invalid. It must start with an alphanumeric character, contain only alphanumerics, '-' or '_', and be 1 to 64 characters long." |
  | PUT `pool:a×65` | 400 | `InvalidResourceName` |
  | PUT `pool:a.b` | 400 | `InvalidResourceName` |
  | PUT `size: 549755813888` | 400 | `InvalidRequestContent` / "The 'properties.size' property must be a whole number of bytes in 1 TiB (1099511627776) chunks, from 1 TiB to 2048 TiB." |
  | PUT `size: 0` | 400 | `InvalidRequestContent` / 같은 문구 |
  | PUT `size: 2252899325313024` (2,049 TiB) | 400 | `InvalidRequestContent` / 같은 문구 |
  | 생성 PUT, `size` 없음 | 400 | `InvalidRequestContent` / "The 'properties.size' property is required." |
  | 생성 PUT, `serviceLevel` 없음 | 400 | `InvalidRequestContent` / "The 'properties.serviceLevel' property is required." |
  | PUT `serviceLevel: Gold` | 400 | `InvalidRequestContent` / "The 'properties.serviceLevel' property must be one of 'Standard', 'Premium', 'Ultra'." |
  | PUT `serviceLevel: Flexible` | 400 | `InvalidRequestContent` / "The property 'properties.serviceLevel 'Flexible'' is not supported by this ANF clone." |
  | PUT `coolAccess: true` | 400 | `InvalidRequestContent` / "The property 'properties.coolAccess' is not supported by this ANF clone." |
  | PUT `encryptionType: Double` | 400 | `InvalidRequestContent` / "The property 'properties.encryptionType 'Double'' is not supported by this ANF clone." |
  | PUT `customThroughputMibps: 100` | 400 | `InvalidRequestContent` / "The property 'properties.customThroughputMibps' is not supported by this ANF clone." |
  | PUT 최상위 `unknownProp` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'unknownProp'." |
  | PUT `properties.unknownProp` (추가 경우) | 400 | `InvalidRequestContent` / "Value received for an unknown property 'properties.unknownProp'." |
  | PATCH 기존 `e2e-p06` `{"properties":{"serviceLevel":"Ultra"}}` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'properties.serviceLevel'." |
  | 기존 `e2e-p06`(westus2)에 PUT `{"location":"eastus","tags":{"changed":"1"}}` | 409 | `InvalidResourceLocation` / "The resource 'e2e-p06' already exists in location 'westus2' in resource group 'rg-e2e'. ..." |

  - 마지막 경우 뒤의 GET `e2e-p06`도 `location: westus2`, `tags: {"keep":"1"}`, `Succeeded`로 그대로였다.
  - Flexible·Double 메시지의 따옴표가 겹친다(추가 관찰 4). 기준(`400 InvalidRequestContent`, 설계 §4.3의 "not supported by this ANF clone")은 충족한다.

### [PASS] AC-07 부모 규칙: 없는 계정 404 ParentResourceNotFound, 계정 Deleting 중 409 Conflict (계약)
- 실행:
  - `test_capacity_pool_live.py::test_ac07_parent_account_missing_returns_404_parent_resource_not_found`
  - `test_capacity_pool_lro_faults_live.py::test_ac07_pool_put_while_parent_account_is_deleting_returns_409_conflict`. 서버는 `ANF_FAULT_INJECTION={"netAppAccounts/delete":{"delaySeconds":5.0}}` (pid 7510)
- 출력 (계정 없음):
  ```
  PUT acct:e2e-pool-no-such-acct7/pool:e2e-p07 (4 TiB Premium)
  -> 404 {"error":{"code":"ParentResourceNotFound","message":"Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools',
          because the parent resource '{SUB}/resourceGroups/rg-e2e/providers/Microsoft.NetApp/netAppAccounts/e2e-pool-no-such-acct7' could not be found."}}
     (추적 헤더 없음)
  GET pool -> 404 ResourceNotFound,  GET 계정 -> 404 (계정도 생기지 않음)
  보조 증거: operations·resources 행 목록이 요청 전후에 같다
  ```
- 출력 (계정 Deleting 중):
  ```
  (계정 e2e-poolf-acct7 생성 -> Succeeded, 풀 없음)
  DELETE acct:e2e-poolf-acct7 -> 202;  GET <aao> -> status=Deleting pc=0.0;  GET 계정 -> "Deleting"
  PUT acct:e2e-poolf-acct7/pool:e2e-pf07 (4 TiB Premium)   [02:57:36.933Z]
  -> 409 {"error":{"code":"Conflict","message":"Cannot create capacity pool '{SUB}/.../e2e-poolf-acct7/capacityPools/e2e-pf07' because its
          parent NetApp account '{SUB}/.../netAppAccounts/e2e-poolf-acct7' is being deleted."}}   (추적 헤더 없음)
  GET 계정 -> "Deleting" (거절 시점에 삭제가 아직 진행 중이었다)
  보조 증거: 풀의 작업 0개, 풀 리소스 행 없음
  폴링: Deleting ×5 -> Succeeded (endTime 02:57:41.927380Z, startTime부터 5.009 s)
  GET 계정 -> 404,  GET pool:e2e-pf07 -> 404 ResourceNotFound
  보조 증거: DB resources 테이블이 비어 있다 (고아 풀 없음)
  ```

### [PASS] AC-08 DELETE → 202, 본문 없음, 두 헤더 → Succeeded → Location 204, GET 404, 재DELETE 204 (계약·상태)
- 실행: `test_ac08_delete_returns_202_both_headers_then_pool_is_gone`
- 출력:
  ```
  DELETE pool:e2e-p08 -> 202, 본문 b"" 
     location:             {base}{SUB}/providers/M.N/locations/westus2/operationResults/cb957814-...?api-version=2026-08-01&operationResultResponseType=Location
     azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/cb957814-...?api-version=2026-08-01
  GET <aao> -> 200 {"status":"Succeeded","percentComplete":100.0,"properties":{"resourceName":"{SUB}/.../capacityPools/e2e-p08","action":"DELETE"},...}
  GET <location> -> 204, 본문 없음
  GET pool:e2e-p08 -> 404 ResourceNotFound
  DELETE pool:e2e-p08 -> 204, 본문 없음
  ```
- curl 교차 확인: `HTTP/1.1 202 Accepted`, `location: ...&operationResultResponseType=Location`, `azure-asyncoperation: ...`, `content-length: 0`.

### [PASS] AC-09 풀이 있는 계정 DELETE → 409 CannotDeleteResource, 풀 삭제 뒤 202 → Succeeded (계약, FR-02 이월)
- 실행: `test_ac09_account_with_pool_cannot_be_deleted_until_pool_is_gone`
- 출력:
  ```
  (계정 e2e-pool-acct9, 풀 e2e-p09 생성 -> 둘 다 Succeeded)
  DELETE acct:e2e-pool-acct9
  -> 409 {"error":{"code":"CannotDeleteResource","message":"Cannot delete resource while nested resources exist. Some existing nested
          resource IDs include: 'Microsoft.NetApp/netAppAccounts/e2e-pool-acct9/capacityPools/e2e-p09'. Please delete all nested
          resources before deleting this resource."}}   (추적 헤더 없음)
  보조 증거: 계정의 operations 행이 거절 전후에 같다 (새 작업 없음)
  GET 계정 -> Succeeded,  GET 풀 -> Succeeded
  DELETE pool:e2e-p09 -> 202 -> op Succeeded (DELETE)
  DELETE acct:e2e-pool-acct9 -> 202 -> op Succeeded (DELETE)
  GET 계정 -> 404
  ```
- 이 결과는 계정 설계 §7의 "용량 풀 사이클로 옮긴 기준"을 실환경에서 확인한 것이다.

### [PASS] AC-10 지연·실패 주입: 진행 중 상태, Location 202, 생성 실패와 회복, PATCH 실패와 되돌리기 (상태)
- 서버: `ANF_FAULT_INJECTION={"capacityPools/create":{"delaySeconds":5.0},"capacityPools/update":{...5.0},"capacityPools/patch":{...5.0},"capacityPools/delete":{...5.0}}` (pid 7515). 기동 로그 첫 줄에 `Fault injection is enabled (ANF_FAULT_INJECTION): {...}`가 찍혔다.
- 실행: `test_capacity_pool_lro_faults_live.py::test_ac10_in_progress_states_create_patch_delete`
- 출력 (진행 중):
  ```
  PUT pool:e2e-pf10 -> 201 (14.0 ms, 주입 지연 5 s) body "Creating"
  GET <aao> -> 200 {"status":"Creating","percentComplete":0.0,"properties":{...,"action":"CREATE"}}   (endTime 없음)
  GET pool -> "Creating"
  폴링 (1초 간격): Creating ×5 -> Succeeded, startTime 02:57:42.786995Z -> endTime 02:57:47.797010Z (5.010 s)

  PATCH pool:e2e-pf10 {"tags":{"b":"2"}} -> 202 (14.3 ms) body "Patching"
  GET <aao> -> 200 status=Patching pc=0.0 action=PATCH
  GET pool -> "Patching"
  GET <location> -> 202, 본문 b"", location 헤더 = 같은 URL
  폴링: Patching ×5 -> Succeeded (5.012 s)
  GET <location> -> 200, 풀 본문 (tags {"b":"2"}, Succeeded)

  DELETE pool:e2e-pf10 -> 202 (11.0 ms)
  GET <aao> -> 200 status=Deleting pc=0.0 action=DELETE;  GET pool -> "Deleting";  GET <location> -> 202
  폴링: Deleting ×5 -> Succeeded (5.010 s);  GET <location> -> 204;  GET pool -> 404
  ```
- 실행: `test_ac10_injected_create_failure_then_recovery_by_put`
- 출력 (생성 실패 → 회복):
  ```
  [pid 7516, ANF_FAULT_INJECTION={"capacityPools/create":{"fail":true}}]
  PUT pool:e2e-pf10-cfail {"tags":{"v":"1"}, 4 TiB Premium} -> 201 Creating
  GET <aao> -> 200 {"status":"Failed","percentComplete":100.0,"properties":{...,"action":"CREATE"},"endTime":"2026-11-08T02:57:58.826534Z",
                    "error":{"code":"InternalServerError","message":"Injected fault: capacityPools/create (ANF_FAULT_INJECTION)."}}
  GET pool -> "Failed";  GET <location> -> 500 {"error":{...같은 code·message}}
  [SIGTERM, 같은 DB로 주입 없이 재기동 pid 7517]
  GET pool -> "Failed" (재기동 뒤에도 유지)
  PUT pool:e2e-pf10-cfail {"tags":{"v":"2"}, ...} -> 200 "Updating"
  GET <aao> -> status=Succeeded action=UPDATE;  GET pool -> Succeeded, tags {"v":"2"}
  ```
- 실행: `test_ac10_injected_patch_failure_rolls_back_tags_and_size`
- 출력 (PATCH 실패 → 되돌리기):
  ```
  [pid 7518, ANF_FAULT_INJECTION={"capacityPools/patch":{"fail":true}}]
  (풀 e2e-pf10-pfail: tags {"a":"1"}, 4 TiB Premium Auto -> Succeeded, poolId 72a8b529)
  PATCH {"tags":{"b":"2"},"properties":{"size":8796093022208,"qosType":"Manual"}}
  -> 202 body: state=Patching tags={"b":"2"} size=8TiB qos=Manual total=512.0   (설계 결정 9: 새 값을 바로 쓴다)
  GET <aao> -> 200 {"status":"Failed","percentComplete":100.0,"properties":{...,"action":"PATCH"},
                    "error":{"code":"InternalServerError","message":"Injected fault: capacityPools/patch (ANF_FAULT_INJECTION)."}}
  GET pool -> state=Failed tags={"a":"1"} size=4TiB Premium qos=Auto total=256.0 poolId=72a8b529   (tags·size·qosType 모두 PATCH 전 값)
  GET <location> -> 500
  ```
  - 추가 확인 (설계 §5 `Failed → Patching → Succeeded`): 같은 DB로 주입 없이 다시 띄운 서버(pid 7519)에서 `PATCH {"tags":{"c":"3"}}` → `202` → `Succeeded`(PATCH). GET은 `Succeeded`, tags `{"c":"3"}`, size 4 TiB.

### [PASS] AC-11 진행 중 충돌 → 409 AnotherOperationInProgress (계약)
- 서버: AC-10과 같은 지연 4종 (pid 7520)
- 실행: `test_ac11_conflicting_requests_while_each_operation_is_in_progress`. 기준은 "풀 작업이 진행 중일 때"라서 네 가지 진행 중 상태(`Creating`, `Updating`, `Patching`, `Deleting`)에서 모두 확인했다.
- 출력:
  ```
  PUT pool:e2e-pf11 {"tags":{"orig":"1"}, 4 TiB Premium} -> 201;  GET <aao> -> "Creating"
  PUT    {"location":"westus2","tags":{"other":"x"},"properties":{"size":17592186044416}} -> 409
         {"error":{"code":"AnotherOperationInProgress","message":"Another operation is in progress on resource '{SUB}/.../capacityPools/e2e-pf11'. Wait until it is finished, and then retry."}}
  PATCH  {"tags":{"patched":"x"},"properties":{"size":17592186044416}} -> 409 AnotherOperationInProgress
  DELETE -> 409 AnotherOperationInProgress
     (세 응답 모두 azure-asyncoperation·location 헤더 없음)
  보조 증거: 이 풀의 작업 = 1개
  폴링 -> Succeeded (CREATE);  GET pool -> tags {"orig":"1"}, size 4 TiB (거절된 PUT·PATCH의 값이 반영되지 않음)

  PUT {"tags":{"upd":"1"}} -> 200 "Updating";  같은 세 요청 -> 각각 409;  작업 = 2개;  -> Succeeded, tags {"upd":"1"}, 4 TiB
  PATCH {"tags":{"pat":"1"}} -> 202 "Patching"; 같은 세 요청 -> 각각 409;  작업 = 3개;  -> Succeeded, tags {"pat":"1"}, 4 TiB
  DELETE -> 202 "Deleting";                     같은 세 요청 -> 각각 409;  작업 = 4개;  -> Succeeded, GET 404
  operations 테이블의 이 풀 작업 = ["CREATE","UPDATE","PATCH","DELETE"], 모두 Succeeded
  ```

### [PASS] AC-12 생성·PATCH 진행 중 SIGKILL → 재시작 뒤 둘 다 Succeeded (상태, AR-04)
- 실행: `test_ac12_create_and_patch_resume_after_sigkill_restart`. 매개변수 2개다: 같은 주입 설정으로 다시 띄운 경우, 주입 없이 다시 띄운 경우.
- 출력 (재기동에 같은 지연 적용):
  ```
  [pid 7524, 지연 4종] 계정 생성, 풀 B(e2e-pf12-b, tags {"before":"patch"}, 4 TiB Premium) 생성 -> Succeeded
  PATCH B {"tags":{"after":"patch"},"properties":{"size":8796093022208}} -> 202 "Patching"
  PUT   A (e2e-pf12-a, 4 TiB Ultra) -> 201 "Creating"
  GET <aao A> -> "Creating",  GET <aao B> -> "Patching"
  SIGKILL pid 7524 -> returncode -9 (02:58:31.855Z). 서버 로그가 요청 줄에서 끊김("Shutting down" 없음). 포트 8080 닫힘
  보조 증거: DB 작업 상태 A = ["Creating"], B = ["Succeeded","Patching"]   (죽을 때 진행 중)
  [같은 DB, 같은 주입으로 재기동 pid 7525, ready 02:58:32.482Z]
  같은 <aao A> -> Succeeded (CREATE), endTime 02:58:37.303740Z
  같은 <aao B> -> Succeeded (PATCH),  endTime 02:58:37.291449Z   (재기동 준비 뒤 약 4.8 s: 지연을 처음부터 다시 실행)
  GET A -> Succeeded, 4 TiB Ultra total 512.0
  GET B -> Succeeded, tags {"after":"patch"}, size 8 TiB, total 512.0
  작업 수: A 1개, B 2개 (새 작업이 생기지 않음)
  ```
- 출력 (주입 없이 재기동):
  ```
  [pid 7526] ... PATCH B -> 202, PUT A -> 201 -> SIGKILL rc -9 -> [pid 7527, 주입 없음, ready 02:58:47.328Z]
  <aao A> Succeeded endTime 02:58:47.210224Z, <aao B> Succeeded endTime 02:58:47.142907Z (준비 확인 응답보다 먼저 끝남: 기동 직후 워커가 복구 실행)
  GET A -> Succeeded,  GET B -> Succeeded, tags {"after":"patch"}, 8 TiB
  ```

### [PASS] AC-13 풀 작업 전후 데이터 플레인 불변 (데이터 플레인 불변)
- 실행 (root). 스크래치 스크립트 `dp_snapshot.sh`가 아래를 한 파일에 모은다:
  ```
  wsl -d Ubuntu -u root -e bash -c 'exportfs -v; echo rc=$?; ls -la --time-style=full-iso /etc/exports.d/ | grep -v " \.\.$";
      sha256sum /etc/exports /var/lib/nfs/etab; cat /proc/fs/nfsd/exports; systemctl is-active nfs-server'
  ```
  - 시점:
    - `before` 02:57:16.96Z: 풀 모듈을 실행하기 직전
    - `after_pool_live` 02:57:28.42Z: AC-01~AC-09 모듈 직후
    - `after_pool_faults` 03:00:41.94Z: AC-07(Deleting)·AC-10~AC-12 모듈 직후
    - `final` 03:12:23.29Z: 계정 모듈과 반복 실행 2회, curl 확인까지 모두 끝난 뒤
- 출력 (네 시점 모두 같다):
  ```
  ## exportfs -v            (출력 없음) rc=0
  ## ls -la /etc/exports.d/  total 8, "." 2026-11-07 17:06:06.408602641 -0800 (항목 없음)
  ## sha256 /etc/exports      3f95c811c082f8c8a0cfda159146c0ce388a37248fe173907a5cb57c98f2fee3
  ## sha256 /var/lib/nfs/etab e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 (빈 파일)
  ## /proc/fs/nfsd/exports    "# Version 1.1" / "# Path Client(Flags) # IPs" (export 없음)
  ## nfs-server               active
  diff before after_pool_live -> IDENTICAL;  diff before after_pool_faults -> IDENTICAL;  diff before final -> IDENTICAL
  ```
- 비교에서 `ls`의 `..` 줄(`/etc` 자체)은 뺐다. `/etc`의 mtime은 풀 작업과 무관하게 바뀐다(계정 1회차 보고서와 같은 처리).
- 한계: 비교하기 전부터 export가 0개였다. 그래서 이 항목이 보여 주는 것은 "풀 작업이 export를 만들거나 바꾸지 않았다"이다. 풀 처리기는 storage agent를 부르지 않는다(`capacity_pools.py:307` `_no_storage_work`).

## 측정값

| 항목 | 값 | 반복 |
| --- | --- | --- |
| 지연 없는 풀 작업의 startTime → endTime | 7~10 ms (AC-01 CREATE 7.3 ms, AC-08 DELETE 8.0 ms, AC-03 UPDATE 7.6 ms) | 1회차 실행 안의 여러 작업 |
| 5 s 지연을 주입했을 때의 응답 시간 | PUT 201 14.0 ms·9.2 ms, PATCH 202 14.3 ms·12.5 ms, DELETE 202 11.0 ms·9.0 ms | 1회차 |
| 5 s 지연을 주입했을 때의 작업 시간 (startTime → endTime, 벽시계) | 생성 5.010 s, PATCH 5.012 s, 삭제 5.010 s, UPDATE 5.009 s. 예외: AC-11 생성 8.342 s, AC-12(주입 없이 재기동) 풀 B 생성 8.357 s | 1회차. 예외 2건은 추가 관찰 2 |
| SIGKILL 재기동 뒤 완료까지 (같은 지연) | 재기동 준비 뒤 약 4.8 s (CREATE·PATCH 모두) | 1회차 |
| 서버 기동(준비 확인 200까지) | 0.617~0.629 s. 첫 기동만 0.831 s (`/mnt/c`의 코드를 import) | 1회 실행에서 기동 13번 (의도한 실패 2번 제외) |
| e2e 실행 시간 | 1회: 풀 2.22 s + 66.72 s (모듈별). 2회: e2e 폴더 전체 106.10 s. 3회: 106.94 s | 3회, 모두 통과 (1회 38/38, 2·3회 62/62) |
| WSL 게스트 단조 시계 / 호스트(Windows UTC) 시계 | 60.641 s / 67.122 s = 0.9034, 60.415 s / 67.062 s = 0.9009 | 2회 (추가 관찰 2) |
| 벽시계 건너뜀 | +3.317 s (03:09:15Z), +3.271 s (03:09:48Z). 단조 시계는 건너뛰지 않음 | 75 s 관찰 1회 |

## 추가 관찰 (판정에 넣지 않음)

1. **curl 교차 확인과 기준 밖 상태 전이.**
   - 서버는 CLAUDE.md의 명령으로 손으로 띄웠다: `ANF_API_DB=/tmp/anf-curl-pool/anf.db`, `ANF_FAULT_INJECTION={"capacityPools/update":{"fail":true},"capacityPools/delete":{"fail":true}}` (pid 8066). 스크립트는 스크래치 `curl_check.sh`다.
   - 풀 PUT(새 풀): `HTTP/1.1 201 Created`. 헤더는 `date`, `server`(uvicorn), `azure-asyncoperation`, `content-length: 545`, `content-type`, `x-ms-request-id`, `x-ms-correlation-request-id`이고 `location`은 없다.
   - 풀 PATCH(tags만): `HTTP/1.1 202 Accepted`, `location: .../operationResults/41ed5286-...?api-version=2026-08-01&operationResultResponseType=Location`, `azure-asyncoperation: .../operationResults/41ed5286-...?api-version=2026-08-01`, 본문 `provisioningState: Patching`.
   - `Updating → Failed`(되돌리기): tags `{"p":"1"}`·4 TiB인 풀에 tags `{"new":"2"}`·8 TiB로 PUT했다. 작업은 `Failed`(`UPDATE`, `Injected fault: capacityPools/update (ANF_FAULT_INJECTION).`)로 끝났다. GET은 `Failed`, tags `{"p":"1"}`, size `4398046511104`, total `256.0`이었다. 이전 값으로 돌아갔다.
   - `Deleting → Failed`: DELETE는 `HTTP/1.1 202 Accepted`, `content-length: 0`, 두 헤더였다. 작업이 실패한 뒤 풀 GET은 `200`, `Failed`였다. 풀이 남아 있다.
   - `Failed → Deleting → [*]`: 같은 DB로 주입 없이 다시 띄우고(pid 8118) DELETE하자 작업이 `Succeeded`(`DELETE`)로 끝났고 풀 GET은 `404`였다.
   - 계정 PUT 201과 계정 DELETE 202의 원시 헤더도 같은 세션에서 봤다 (계정 2회차 보고서).
   - 임시 DB와 서버 로그는 확인 뒤 지웠다.
2. **WSL 게스트 시계가 약 10% 느리고, 벽시계가 약 33초마다 앞으로 건너뛴다 (환경, 판정 영향 없음).**
   - 발견: JSONL 기록에서 연속한 요청 사이가 1.4 s를 넘은 곳을 찾았다. 1초 폴링 중에 2.0~4.3 s 간격이 생겼다. 1회차 풀 모듈 2번(02:58:05→02:58:09, 02:58:38→02:58:42), 계정 모듈 1번, 2회차 4번, 3회차 4번이다. 약 33초 간격으로 나타났다.
   - 같은 때 서버의 작업 시간(ARM startTime → endTime, 벽시계)도 늘었다. 5 s 지연 작업이 8.34 s로 보였다 (AC-11 생성, AC-12 풀 B 생성).
   - 원인 확인 1: 75초 동안 0.25초마다 `time.time()`과 `time.monotonic()`을 비교했다(스크래치 `clockcheck.py`). 벽시계만 03:09:15Z에 +3.317 s, 03:09:48Z에 +3.271 s 건너뛰었다. 단조 시계는 건너뛰지 않았다.
   - 원인 확인 2: 게스트 단조 시계를 Windows 호스트 시계(`[DateTimeOffset]::UtcNow`, WSL interop)와 60초 동안 비교했다(스크래치 `hostclock.sh`). 두 번 모두 게스트가 약 10% 느렸다: 60.641 s / 67.122 s = 0.9034, 60.415 s / 67.062 s = 0.9009. 게스트 벽시계는 호스트와 맞았다(67.043 s, 67.031 s). 게스트 시계가 느리게 가고, 시간 동기화가 벽시계만 주기적으로 앞으로 당기는 것으로 보인다. 클럭소스는 `tsc`다. TSC 보정 문제일 수 있다 [추정, 확인하지 않음].
   - 판정 영향: 없다. 시간 조건(PUT 응답 < 1 s, 지연 + 30 s 안에 종결)은 단조 시계로 쟀고 여유가 크다. 주입한 5 s 지연은 실제로는 약 5.5 s 걸린다.
   - **FR-08(처리량) 주의:** blk-cgroup 제한과 컨테이너 안의 fio는 모두 게스트 커널 시계를 쓴다. 그래서 게스트 안에서 잰 MiB/s가 설정값과 맞더라도, 호스트 실시간 기준 처리량은 약 10% 낮을 수 있다 [추론]. 벽시계(`date`, ARM 시각)로 구간을 재면 3.3 s 건너뜀이 섞인다. 스파이크 S2에서 어느 시계를 기준으로 삼을지 리더가 정할 일이다. 계정 1회차 보고서의 "5.010 s" 같은 값도 같은 영향을 받는다.
3. **결함 키는 등록된 처리기에서 만든다 (설계 "구현 중 변경").** `test_extra_fault_keys_follow_registered_handlers`:
   - `{"capacityPools/resize":{"fail":true}}` → uvicorn이 0이 아닌 코드로 끝나고 포트를 열지 않았다. 로그: `ValueError: Unknown fault key 'capacityPools/resize'. Use one of ['capacityPools/create', 'capacityPools/delete', 'capacityPools/patch', 'capacityPools/update', 'netAppAccounts/create', 'netAppAccounts/delete', 'netAppAccounts/update']`
   - `{"netAppAccounts/patch":{"fail":true}}` → 같은 방식으로 거절. 로그: `ValueError: Unknown fault key 'netAppAccounts/patch'. Use one of [...같은 7개...]`
   - 7개 키를 모두 켜면 기동하고 `Fault injection is enabled (ANF_FAULT_INJECTION): {'capacityPools/create': Fault(delay_seconds=5.0, fail=False), ..., 'netAppAccounts/delete': Fault(delay_seconds=0.0, fail=False)}`가 찍힌다.
4. **미룬 속성 메시지의 따옴표가 겹친다 (표시 문제).** `serviceLevel: Flexible`은 "The property 'properties.serviceLevel 'Flexible'' is not supported by this ANF clone."이다. `encryptionType: Double`도 같다. `capacity_pools.py:62`, `:97`이 값까지 넣은 이름을 `unsupported_property`(`arm_rules.py:102-104`)에 넘기고, 그 함수가 이름을 다시 따옴표로 감싸서 생긴다. 기준은 충족하므로 FAIL로 세지 않았다. 고친다면 예: `unsupported_property("properties.serviceLevel")`처럼 이름만 넘기거나 메시지를 "The value 'Flexible' of 'properties.serviceLevel' is not supported by this ANF clone."로 바꾼다.
5. **§5 상태 전이를 실서버에서 확인한 범위.**
   - 수락 기준으로 확인: `Creating → Succeeded`, `Creating → Failed`, `Succeeded → Updating → Succeeded`, `Failed → Updating → Succeeded`, `Succeeded → Patching → Succeeded`, `Succeeded → Patching → Failed`(되돌리기), `Succeeded → Deleting → [*]`
   - 추가 확인: `Failed → Patching → Succeeded` (AC-10 추가 확인), `Updating → Failed`(되돌리기)와 `Deleting → Failed`, `Failed → Deleting → [*]` (추가 관찰 1)
6. **설계 결정 9의 결과가 보인다.** PATCH 202 본문은 바뀐 뒤의 값이다(AC-04, AC-10). 녹화(N2)의 202 본문은 바뀌기 전 값이었다. 설계에 적힌 의도된 차이다.
7. **계정 이름 대소문자.** `acct:E2E-POOL-ACCT/pool:E2e-P05-Mixed` GET의 `id`·`name`은 처음 저장한 철자(`e2e-pool-acct/E2e-P05-Mixed`)다. 풀 본문의 `name`이 요청 경로가 아니라 저장된 ID에서 계정 이름을 꺼내기 때문이다(`capacity_pools.py:142`).
8. **PATCH의 다른 location과 없는 풀 (설계 §4.1, §4.3).** `PATCH {"location":"eastus","tags":{"x":"1"}}` → `409 InvalidResourceLocation`, 풀 그대로. 없는 풀 PATCH → `404 ResourceNotFound`. (`test_extra_patch_other_location_and_missing_pool`)
9. **모든 응답에 `x-ms-request-id`.** 1회차 풀 모듈 1의 응답 209개, 모듈 2의 응답 182개 모두에 있었고 서로 모두 달랐다. 모듈 1에는 200·201·202·204·400·404·409, 모듈 2에는 200·201·202·204·404·409·500이 나왔다.
10. 통합 정합성(스킬 §3): 구성 요소가 anf-api 하나뿐이다(대시보드·CLI 없음). 대조할 상대가 아직 없다.
11. 정리:
    - 검증용 서버 프로세스는 모두 멈췄다. `uvicorn --factory` 프로세스가 없고 8080 포트도 비어 있다(03:12:23Z 확인).
    - pytest 임시 디렉터리(`/tmp/anf-e2e-pool-*`, `/tmp/anf-e2e-acct-*`, `/tmp/anf-e2e-all-run*`)와 curl용 `/tmp/anf-curl-pool`은 지웠다.
    - 증거로 남긴 것(WSL): 요청·응답 JSONL `/tmp/anf-e2e-pool-r1.jsonl`(1회차 풀), `/tmp/anf-e2e-acct-r2.jsonl`(1회차 계정), `/tmp/anf-e2e-all-run2.jsonl`, `/tmp/anf-e2e-all-run3.jsonl`, 데이터 플레인 스냅숏 `/tmp/anf-e2e-dp/*.txt`(root 소유).
    - `/tmp/anf-smoke.log`는 이번 검증이 만든 파일이 아니어서 그대로 두었다.
    - 보조 스크립트(`dp_snapshot.sh`, `dump_compact.py`, `gaps.py`, `clockcheck.py`, `hostclock.sh`, `curl_check.sh`, `ac13.py`)는 세션 스크래치 디렉터리에만 있다. 저장소에는 넣지 않았다.
