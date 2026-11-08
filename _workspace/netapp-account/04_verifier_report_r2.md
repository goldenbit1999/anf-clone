# netapp-account 검증 보고서 — 2회차

- 검증일: 2026-11-07 (로컬 PST). 실행 시각은 UTC 2026-11-08 03:00~03:13
- 검증 대상 코드:
  - 기준 커밋 `e602d11b1c8569064eab3d38156880cdd25aed29` (`git rev-parse HEAD`). 제품 코드는 미커밋이다.
    - 수정(M): `backend/anf_api/accounts.py`, `arm_app.py`, `arm_rules.py`, `lro.py`, `state_store.py`
    - 새 파일(untracked): `backend/anf_api/capacity_pools.py`
  - 기준 해시는 리더가 정한 명령이다(저장소 루트):
    `cat pyproject.toml backend/anf_api/__init__.py backend/anf_api/accounts.py backend/anf_api/arm_app.py backend/anf_api/arm_rules.py backend/anf_api/capacity_pools.py backend/anf_api/lro.py backend/anf_api/state_store.py | sha256sum`
    = `f58df82db294ebb8061950d4af80ca8e83996e297df8c3a7775952f4bd154723`
  - 검증을 시작할 때(02:53:30Z)와 끝낸 뒤(03:12:23Z)에 Git Bash와 WSL 양쪽에서 계산했고 모두 같았다. 리더가 넘긴 값과도 같다.
  - 1회차의 대상은 `bf4e61d3…`(기준 커밋 `b96dbaf`)였다. 용량 풀 사이클이 공통 코드를 바꿔서 1회차 결과가 무효가 됐다.
- 이번 회차 범위: 재검증, 전체(AC-01~AC-13).
  - 다시 실행한 이유: 용량 풀 사이클이 계정이 쓰는 공통 코드를 바꿨다 (풀 설계 "구현 중 변경"). 오류 함수(`arm_rules.py`), 자식 검사(`Tx.ensure_no_children`), 결함 키 생성(`lro.parse_faults`), 라우트·추적 헤더(`arm_app.py`)가 바뀌었다. 계정 기준 13개가 모두 이 코드 경로를 지나므로 모두 다시 실행했다.
  - 1회차에서 용량 풀 사이클로 옮긴 기준("풀이 남은 계정 DELETE → `409 CannotDeleteResource`")은 이번 풀 1회차의 AC-09에서 실환경으로 확인했다 (`_workspace/capacity-pool/04_verifier_report.md` AC-09, PASS).
- 검증 방법: 1회차와 같다.
  - WSL Ubuntu에서 anf-api를 **실제 uvicorn 프로세스**로 띄우고, 별도 프로세스(pytest)에서 `http.client`로 요청했다.
  - 상태 저장소는 시나리오마다 `/tmp`(ext4) 아래 새 임시 파일이다.
  - 교차 확인: 손으로 띄운 서버에 `curl -i`로 계정 PUT·DELETE의 원시 헤더를 봤다 (AC-01, AC-07).
- 검증 스크립트:
  - `backend/tests/e2e/test_netapp_account_live.py`: 1회차와 같다 (바꾸지 않음).
  - `backend/tests/e2e/test_netapp_account_lro_faults_live.py`: `test_s63_fault_injection_startup_guard_and_warning`에 잘못된 값 하나를 더했다. `{"netAppAccounts/patch":{"fail":true}}`이면 서버가 뜨지 않고 로그에 `Unknown fault key 'netAppAccounts/patch'`가 있어야 한다. 리더가 짚은 AC-09 주의점을 확인하려고 넣었다. 다른 테스트는 바꾸지 않았다.
  - `backend/tests/e2e/live_api.py`: 풀용 함수와 상수를 더했다(`POOL_TYPE`, `TIB`, `pool_*`, `create_pool`, `db_resources`). 계정 테스트가 쓰는 기존 함수는 바꾸지 않았다.
- 재현 명령 (WSL, 저장소 루트):
  ```
  ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/tmp/anf-e2e.jsonl \
    ~/.venvs/anf-clone/bin/python -m pytest backend/tests/e2e/test_netapp_account_live.py \
    backend/tests/e2e/test_netapp_account_lro_faults_live.py -m e2e -v -p no:cacheprovider
  ```
  AC-12만 셸에서 root로 따로 비교한다 (명령은 AC-12 항목에 있다).

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`에서 `Ubuntu Running 2`. 커널 `6.18.54.1-microsoft-standard-WSL2`, Ubuntu 24.04.1 LTS |
| Python 가상환경 | `~/.venvs/anf-clone`: Python 3.12.3, fastapi 0.162.2, uvicorn 0.54.0, starlette 1.10.0, pytest 9.2.0 |
| 포트 `127.0.0.1:8080` | 시작 전에 비어 있었다. 끝난 뒤에도 비어 있고 anf-api 프로세스도 남아 있지 않다 (03:12:23Z) |
| 임시 DB 위치 | `/tmp`는 ext4(`/dev/sdd`)다 |
| 컨트롤 플레인 서비스 | 시나리오마다 테스트가 직접 띄웠다. 준비 확인은 구독 목록 GET `200`이다. 실패한 기동은 없었다(§6.3의 의도한 기동 실패 3건은 제외) |
| root `exportfs` (AC-12) | `/usr/sbin/exportfs`를 root로 쓸 수 있다. `nfs-server`는 `active`, export는 0개다 |
| 시계 | WSL 게스트 시계가 호스트보다 약 10% 느리고 벽시계가 약 33초마다 앞으로 건너뛴다. 이번 판정에는 영향이 없다 (추가 관찰 3) |
| Docker, 커널 모듈 | 컨트롤 플레인 전용 기능이라 점검하지 않았다 (스킬 §0) |

## 결과 요약

PASS 13 / FAIL 0 / UNVERIFIED 0

- 계정 e2e 묶음(24개 테스트)을 세 번 실행했고 세 번 모두 전부 통과했다.
  - 1회: 모듈별로 나눠 실행했다(16개 1.47 s, 8개 36.41 s). AC-12 비교를 사이에 끼우려고 나눴다.
  - 2회, 3회: 풀 모듈까지 e2e 폴더 전체(62개)를 한 번에 실행했다(106.10 s, 106.94 s).
- 판정이 바뀐 결과는 없었다. 1회차와 비교해 바뀐 응답은 없고, 결함 키 기동 오류의 문구만 바뀌었다 (AC-09 항목, 추가 관찰 1).

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 2회차 (이 보고서). 1회차 PASS는 코드 변경으로 무효 |
| AC-02 | PASS | 2회차 |
| AC-03 | PASS | 2회차 |
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
| (이월) 풀이 남은 계정 DELETE → 409 | PASS | 용량 풀 1회차 AC-09 (`_workspace/capacity-pool/04_verifier_report.md`) |

## 항목별 결과

표기: `{SUB}` = `/subscriptions/0e2e0000-1111-4222-8333-444455556666`, `{base}` = `http://127.0.0.1:8080`, `M.N` = `Microsoft.NetApp`, `acct:X` = `{SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts/X`, `op:Z` = `{SUB}/providers/M.N/locations/westus2/operationResults/Z`. 모든 경로에는 `?api-version=2026-08-01`이 붙어 있다(따로 적은 경우는 제외). 아래 출력은 1회 실행(모듈별)의 JSONL 기록 `/tmp/anf-e2e-acct-r2.jsonl`에서 뽑았다.

### [PASS] AC-01 새 계정 PUT → 201, Creating, Azure-AsyncOperation만 → 폴링 Succeeded (계약·상태)
- 실행: `test_netapp_account_live.py::test_ac01_create_returns_201_creating_and_operation_succeeds`. URL은 정규식 `^{base}{SUB}/providers/Microsoft\.NetApp/locations/westus2/operationResults/{uuid}\?api-version=2026-08-01$`로 확인했다.
- 출력:
  ```
  PUT acct:e2e-ac01 {"location":"westus2","tags":{"k":"v"}}
  -> 201 (23.4 ms), azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/cbf14505-6379-4d0f-876e-6078a595f635?api-version=2026-08-01
     (location·retry-after 헤더 없음)  body: "provisioningState":"Creating", tags {"k":"v"}
  GET op:cbf14505-... -> 200 status=Succeeded percentComplete=100.0 action=CREATE (start 03:00:51.417954Z, end 03:00:51.425530Z)
  GET acct:e2e-ac01 -> 200 "provisioningState":"Succeeded"
  ```
- curl 교차 확인(손으로 띄운 서버, 리소스 그룹 `rg-curl`): `HTTP/1.1 201 Created`. 헤더는 `date`, `server`, `azure-asyncoperation`, `content-length: 318`, `content-type`, `x-ms-request-id`, `x-ms-correlation-request-id`뿐이고 `location`은 없다. 본문 `{"...","properties":{"provisioningState":"Creating","encryption":{"keySource":"Microsoft.NetApp"}}}`.

### [PASS] AC-02 기존 계정 PUT → 200, Updating → Succeeded, tags 교체 (계약·상태)
- 실행: `test_ac02_put_existing_returns_200_updating_and_replaces_tags`
- 출력:
  ```
  (생성: tags {"old":"1","keep":"no"} -> Succeeded)
  PUT acct:e2e-ac02 {"location":"westus2","tags":{"new":"2","x":"y"}}
  -> 200 (18.5 ms), azure-asyncoperation 있음, location 없음, body "Updating", tags {"new":"2","x":"y"}
  GET op:2d2911e4-... -> 200 status=Succeeded action=UPDATE
  GET acct:e2e-ac02 -> tags {"new":"2","x":"y"}, "Succeeded"   (old·keep이 남지 않음)
  ```

### [PASS] AC-03 GET 본문 필드, 없는 계정 404, 대소문자만 다른 이름 (계약)
- 실행: `test_ac03_get_body_fields_not_found_and_case_insensitive_name`
- 출력:
  ```
  GET acct:E2e-Ac03-Mixed -> 200 {"id":"{SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts/E2e-Ac03-Mixed","name":"E2e-Ac03-Mixed",
        "type":"Microsoft.NetApp/netAppAccounts","location":"westus2","tags":{"k":"v"},
        "properties":{"provisioningState":"Succeeded","encryption":{"keySource":"Microsoft.NetApp"}}}
  GET acct:e2e-ac03-missing -> 404 {"error":{"code":"ResourceNotFound","message":"The resource with identifier '{SUB}/resourceGroups/rg-e2e/providers/Microsoft.NetApp/netAppAccounts/e2e-ac03-missing' is not found."}}
  GET acct:E2E-AC03-MIXED -> 200, 본문이 위와 같음 (name "E2e-Ac03-Mixed")
  GET acct:e2e-ac03-mixed -> 200, 같음
  ```
- 404 문구는 1회차와 같다. 이 문구를 만드는 코드가 `arm_rules.not_found`(`arm_rules.py:113-115`)로 옮겨졌지만 결과는 바뀌지 않았다.

### [PASS] AC-04 리소스 그룹 목록, 다른 리소스 그룹 목록, 구독 목록 (계약)
- 실행: `test_ac04_resource_group_and_subscription_lists`
- 출력:
  ```
  GET {SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts       -> 200 value=[e2e-ac01, e2e-ac02, E2e-Ac03-Mixed, e2e-ac04]   (e2e-ac04-other 없음)
  GET {SUB}/resourceGroups/rg-e2e-other/providers/M.N/netAppAccounts -> 200 value=[e2e-ac04-other]                             (e2e-ac04 없음)
  GET {SUB}/providers/M.N/netAppAccounts                             -> 200 value=[e2e-ac01, e2e-ac02, E2e-Ac03-Mixed, e2e-ac04, e2e-ac04-other]
  GET /subscriptions/0e2e0000-9999-.../providers/M.N/netAppAccounts  -> 200 value=[]   (추가 확인: 다른 구독)
  ```
- 응답 최상위 키는 `value` 하나다. 계정 목록에 풀이 섞이지 않았다(목록이 `type`으로 거른다).

### [PASS] AC-05 PATCH tags → 동기 200, 추적 헤더 없음, 맵 교체 (계약)
- 실행: `test_ac05_patch_tags_is_synchronous_and_replaces_map`
- 출력:
  ```
  (생성: tags {"a":"1"} -> Succeeded)
  PATCH acct:e2e-ac05 {"tags":{"b":"2"}} -> 200 (12.4 ms), azure-asyncoperation·location 없음, body tags {"b":"2"}, "Succeeded"
  GET acct:e2e-ac05 -> tags {"b":"2"}, "Succeeded"
  PATCH acct:e2e-ac05-missing -> 404 ResourceNotFound
  ```
- 풀 PATCH는 이번에 `202`(비동기)가 됐지만 계정 PATCH는 여전히 동기 `200`이다. 계정 설계 결정 3이 유지된다.

### [PASS] AC-06 잘못된 요청 거절, 작업·상태 변화 없음 (계약)
- 실행: `test_ac06_rejected_put_creates_no_operation_and_changes_nothing` (매개변수 9개 모두 통과). 확인 항목은 1회차와 같다: 코드, `error.code`, 추적 헤더 없음, 구독 목록 전후 동일, `e2e-ac06` GET 동일, 올바른 이름이면 GET 404, 보조 증거로 `operations` 행 목록 동일.
- 출력 (응답 문구가 1회차와 글자 단위로 같다):

  | 요청 | 응답 | error.code / message |
  | --- | --- | --- |
  | PUT `acct:-abc` | 400 | `InvalidResourceName` / "The NetApp account name '-abc' is invalid. It must start with an alphanumeric character, contain only alphanumerics, '-' or '_', and be 1 to 128 characters long." |
  | PUT `acct:a×129` | 400 | `InvalidResourceName` |
  | PUT `acct:a.b` | 400 | `InvalidResourceName` |
  | PUT `.../e2e-ac06-nover` (쿼리 없음) | 400 | `MissingApiVersionParameter` / "The api-version query parameter (?api-version=) is required for all requests." |
  | PUT `...?api-version=2025-01-01` | 400 | `NoRegisteredProviderFound` / "No registered resource provider found for API version '2025-01-01'. The supported api-versions are '2026-08-01'." |
  | PUT 본문 `{"tags":{"a":"1"}}` | 400 | `InvalidRequestContent` / "The 'location' property is required." |
  | PUT 본문 `{"location":"westus2","unknownProp":1}` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'unknownProp'." |
  | PUT 본문 `{"location":"westus2","identity":{"type":"SystemAssigned"}}` | 400 | `InvalidRequestContent` / "The property 'identity' is not supported by this ANF clone." |
  | 기존 `e2e-ac06`(westus2)에 PUT `{"location":"eastus","tags":{"changed":"1"}}` | 409 | `InvalidResourceLocation` / "The resource 'e2e-ac06' already exists in location 'westus2' in resource group 'rg-e2e'. A resource with the same name cannot be created in location 'eastus'. Please select a new resource name." |

- 아래 셋은 이번에 공통 함수로 옮겨진 문구다. 결과가 1회차와 같다.
  - `invalid_content`, `unknown_property`, `unsupported_property` (`arm_rules.py:92-104`)
  - `location_conflict` (`arm_rules.py:118-125`)

### [PASS] AC-07 DELETE → 202, 두 헤더 → Succeeded → Location 204, GET 404, 재DELETE 204 (계약·상태)
- 실행: `test_ac07_delete_returns_202_with_both_headers_then_resource_is_gone`
- 출력:
  ```
  DELETE acct:e2e-ac07 -> 202 (16.6 ms), 본문 b""
     location:             {base}{SUB}/providers/M.N/locations/westus2/operationResults/50a89d09-...?api-version=2026-08-01&operationResultResponseType=Location
     azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/50a89d09-...?api-version=2026-08-01
  GET <aao> -> 200 status=Succeeded action=DELETE
  GET <location> -> 204, 본문 없음
  GET acct:e2e-ac07 -> 404 ResourceNotFound
  DELETE acct:e2e-ac07 -> 204, 본문 없음
  ```
- 자식이 없는 계정의 DELETE는 이제 `Tx.ensure_no_children`(`state_store.py:152-164`)를 지난다. 자식이 없으면 그대로 통과해 1회차와 같은 결과다.
- curl 교차 확인(풀을 지운 뒤의 `curl-acct`): `HTTP/1.1 202 Accepted`, `location: ...&operationResultResponseType=Location`, `azure-asyncoperation: ...`, `content-length: 0`. 이어서 GET은 `404 ResourceNotFound`였다.

### [PASS] AC-08 지연 주입 중 진행 상태 (상태, FR-01 진행 중)
- 서버: `ANF_FAULT_INJECTION={"netAppAccounts/create":{"delaySeconds":5.0},"netAppAccounts/delete":{"delaySeconds":5.0}}` (pid 7762)
- 실행: `test_netapp_account_lro_faults_live.py::test_ac08_in_progress_states_with_injected_delay`
- 출력:
  ```
  PUT acct:e2e-ac08 -> 201 (14.3 ms, 주입 지연 5 s) body "Creating"
  GET <aao> -> 200 status=Creating percentComplete=0.0 action=CREATE (endTime 없음)
  GET 계정 -> "Creating"
  GET <aao>&operationResultResponseType=Location -> 202, 본문 없음, location 헤더 = 같은 URL
  폴링: Creating -> Succeeded, start 03:01:00.971183Z -> end 03:01:05.981632Z (5.010 s)
  GET 계정 -> "Succeeded"
  DELETE -> 202;  GET <location> -> 202, 본문 b"", location 헤더 = 같은 URL;  GET 계정 -> "Deleting"
  GET <aao> -> status=Deleting percentComplete=0.0
  폴링: Deleting -> Succeeded, start 03:01:06.007516Z -> end 03:01:11.065645Z (5.058 s)
  GET <location> -> 204,  GET 계정 -> 404
  ```

### [PASS] AC-09 실패 주입, 회복, 삭제 실패 (상태, FR-01 실패)
- 실행: `test_ac09_injected_create_failure_then_recovery`, `test_ac09_injected_delete_failure_leaves_account_failed`
- 출력 (생성 실패 → 회복):
  ```
  [pid 7766, ANF_FAULT_INJECTION={"netAppAccounts/create":{"fail":true}}]
  PUT acct:e2e-ac09 {"tags":{"v":"1"}} -> 201 Creating
  GET <aao> -> 200 {"status":"Failed","percentComplete":100.0,"properties":{...,"action":"CREATE"},"endTime":"2026-11-08T03:01:11.952269Z",
                    "error":{"code":"InternalServerError","message":"Injected fault: netAppAccounts/create (ANF_FAULT_INJECTION)."}}
  GET <aao>&operationResultResponseType=Location -> 500 {"error":{"code":"InternalServerError","message":"Injected fault: ..."}}
  GET 계정 -> "Failed"
  [SIGTERM, 같은 DB로 주입 없이 재기동 pid 7767]
  GET 계정 -> "Failed" (재기동 뒤에도 유지)
  PUT acct:e2e-ac09 {"tags":{"v":"2"}} -> 200 "Updating" -> op Succeeded (UPDATE)
  GET 계정 -> "Succeeded", tags {"v":"2"}
  ```
- 출력 (삭제 실패):
  ```
  [pid 7768, 주입 없음] PUT e2e-ac09-del -> 201 -> Succeeded   [SIGTERM]
  [pid 7769, ANF_FAULT_INJECTION={"netAppAccounts/delete":{"fail":true}}, 같은 DB]
  DELETE -> 202 (두 헤더)
  GET <aao> -> 200 status=Failed action=DELETE, error {"code":"InternalServerError","message":"Injected fault: netAppAccounts/delete (ANF_FAULT_INJECTION)."}
  GET 계정 -> 200 "Failed" (남아 있음);  GET <location> -> 500
  ```
- **결함 키 (리더가 짚은 주의점).** 결함 키는 이제 등록된 처리기에서 만든다(`lro.py:33-61`, `arm_app.py:74-75`). 계정에서 바뀐 것과 바뀌지 않은 것은 다음과 같다.
  - 계정이 받는 키는 1회차와 같은 `netAppAccounts/{create|update|delete}` 세 개다. 위 주입(`create`·`delete`)은 모두 받아들여졌다. `update`도 받는다(풀 보고서 추가 관찰 3에서 7개 키를 모두 켜고 기동했다).
  - `netAppAccounts/patch`는 서버 시작을 막는다. `test_s63_fault_injection_startup_guard_and_warning`에 더한 경우의 결과는 다음과 같다: uvicorn이 0이 아닌 코드로 끝났고, 포트를 열지 않았고, 로그에 `ValueError: Unknown fault key 'netAppAccounts/patch'. Use one of ['capacityPools/create', 'capacityPools/delete', 'capacityPools/patch', 'capacityPools/update', 'netAppAccounts/create', 'netAppAccounts/delete', 'netAppAccounts/update']`가 남았다. 계정 PATCH는 동기라 작업이 없으므로 거절이 맞다.
  - 바뀐 것은 오류 문구뿐이다. 1회차의 모르는 키 오류는 `Use '{type}/{create|update|delete}' with type in ['netAppAccounts']`였고, 이제는 받는 키 목록 전체를 보여 준다. 계정 설계 §6.3("모르는 키가 있으면 서버가 뜨지 않는다")은 그대로 지켜진다.

### [PASS] AC-10 진행 중 충돌 → 409 AnotherOperationInProgress (계약)
- 서버: 생성·삭제 지연 5 s (pid 7770)
- 실행: `test_ac10_conflicting_requests_while_in_progress`
- 출력:
  ```
  PUT acct:e2e-ac10 {"tags":{"orig":"1"}} -> 201;  GET <aao> -> "Creating"
  PUT    {"tags":{"other":"x"}}   -> 409 {"error":{"code":"AnotherOperationInProgress","message":"Another operation is in progress on resource '{SUB}/.../netAppAccounts/e2e-ac10'. Wait until it is finished, and then retry."}}
  PATCH  {"tags":{"patched":"1"}} -> 409 AnotherOperationInProgress
  DELETE                          -> 409 AnotherOperationInProgress
     (세 응답 모두 추적 헤더 없음. 보조 증거: 이 계정의 작업 = 1개)
  폴링 -> Succeeded (end 03:01:20.625430Z);  GET 계정 -> tags {"orig":"1"}, Succeeded
  DELETE -> 202 "Deleting" 중에 PUT·PATCH·DELETE -> 각각 409 AnotherOperationInProgress
  폴링 -> Succeeded, GET -> 404.  operations 테이블의 이 계정 작업 = ["CREATE","DELETE"]
  ```

### [PASS] AC-11 SIGKILL 뒤 재시작하면 진행 중 작업이 끝까지 실행된다 (상태, AR-04)
- 실행: `test_ac11_operation_resumes_after_sigkill_restart` (매개변수 2개)
- 출력 (같은 지연으로 재기동):
  ```
  [pid 7772, 생성 지연 5 s] PUT e2e-ac11 -> 201;  GET <aao> -> "Creating"
  SIGKILL pid 7772 -> returncode -9 (03:01:29.968Z), 포트 닫힘. 보조 증거: DB 작업 상태 = ["Creating"]
  [같은 DB, 같은 주입으로 재기동 pid 7773, ready 03:01:30.596Z]
  같은 <aao> 폴링 -> Succeeded, end 03:01:35.413435Z (재기동 준비 뒤 약 4.8 s)
  GET 계정 -> 200 Succeeded.  작업 수 = 1
  ```
- 출력 (주입 없이 재기동): `[pid 7776] PUT -> 201 Creating -> SIGKILL rc -9 -> [pid 7777, 주입 없음, ready 03:01:37.079Z]`. 같은 `<aao>`의 첫 폴링이 `Succeeded`(end 03:01:36.898219Z)였다. 준비 확인 응답보다 먼저 끝났다. GET 계정은 `Succeeded`였다.

### [PASS] AC-12 계정 작업 전후 데이터 플레인 불변 (데이터 플레인 불변)
- 실행 (root): 풀 보고서 AC-13과 같은 스냅숏 스크립트를 썼다.
  ```
  wsl -d Ubuntu -u root -e bash -c 'exportfs -v; echo rc=$?; ls -la --time-style=full-iso /etc/exports.d/ | grep -v " \.\.$";
      sha256sum /etc/exports /var/lib/nfs/etab; cat /proc/fs/nfsd/exports; systemctl is-active nfs-server'
  ```
  - 시점: `acct_before` 03:00:50.04Z (AC-01~AC-07 모듈 직전), `acct_after_live` 03:00:52.27Z (직후), `final` 03:12:23.29Z (계정 결함 모듈, 반복 실행 2회, curl 확인까지 끝난 뒤). 셋 다 풀 검증 시작 전의 `before`(02:57:16.96Z)와도 비교했다.
- 출력 (모든 시점이 같다):
  ```
  ## exportfs -v            (출력 없음) rc=0
  ## ls -la /etc/exports.d/  total 8, "." 2026-11-07 17:06:06.408602641 -0800 (항목 없음)
  ## sha256 /etc/exports      3f95c811c082f8c8a0cfda159146c0ce388a37248fe173907a5cb57c98f2fee3
  ## sha256 /var/lib/nfs/etab e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 (빈 파일)
  ## /proc/fs/nfsd/exports    "# Version 1.1" / "# Path Client(Flags) # IPs"
  ## nfs-server               active
  diff before acct_before / acct_after_live / final -> 모두 IDENTICAL
  ```
- 1회차와 같은 값이다(`/etc/exports` 해시 동일).
- 한계는 1회차와 같다. export가 처음부터 0개라서, 이 항목은 "계정 작업이 export를 만들거나 바꾸지 않았다"만 보여 준다. 계정 처리기는 storage agent를 부르지 않는다(`accounts.py:171` `_no_storage_work`).

### [PASS] AC-13 x-ms-request-id와 x-ms-correlation-request-id (계약, 추적성)
- 실행: `test_ac13_request_and_correlation_ids`, `test_ac13_request_id_on_every_fault_scenario_response`
- 출력:
  - 모듈 1: HTTP 응답 97개 모두에 `x-ms-request-id`가 있었고 값이 서로 모두 달랐다. 상태 코드는 200×65, 201×9, 202×1, 204×3, 400×9, 404×9, 409×1이다. 테스트는 AC-13 테스트 전까지 받은 응답이 모두 UUID인지도 단언했다.
  - 모듈 2: 응답 85개 모두에 있었고 서로 모두 달랐다. 200·201·202·204·404·409·500이 모두 나왔다.
  - 보낸 상관 ID는 그대로 돌아왔다(7건, 모두 같은 값): GET 200, GET 없는 계정 404, PUT `-bad` 400, PATCH 200, DELETE 없는 계정 204, GET 구독 목록 200, PUT 갱신 200.
  - 보내지 않으면 연속한 GET 두 번에 서로 다른 새 UUID가 왔다.
  - 보조 증거: 상관 ID를 넣어 보낸 PUT의 작업 행에 `correlation_id`가 그 값으로 저장됐다.
  - curl: 상관 ID를 보내지 않은 계정 PUT·DELETE 응답에 새 UUID가 있었다(`a1caee6a-...`, `148b126c-...`).

## 측정값

| 항목 | 값 | 반복 |
| --- | --- | --- |
| 지연 없는 작업의 startTime → endTime | 7~10 ms (AC-01 CREATE 7.6 ms, AC-07 DELETE 6.2 ms, AC-02 UPDATE 9.7 ms) | 1회 실행 안의 여러 작업 |
| 5 s 생성 지연을 주입했을 때의 PUT 응답 시간 | 14.3 ms (AC-08), 63.2 ms (AC-10), 12.3 ms·10.9 ms (AC-11) | 1회 실행 안에서 4회 |
| 5 s 지연 작업 시간 (startTime → endTime, 벽시계) | 생성 5.010 s·5.058 s, 삭제 5.058 s. 예외: AC-10 삭제 6.438 s (벽시계 건너뜀, 추가 관찰 3) | 1회 실행 |
| SIGKILL 재기동 뒤 완료까지 (같은 지연) | 재기동 준비 뒤 약 4.8 s | 1회 |
| e2e 실행 시간 | 1회: 1.47 s + 36.41 s (모듈별). 2회·3회: e2e 폴더 전체(풀 포함) 106.10 s, 106.94 s | 3회, 계정 24/24 모두 통과 |

## 추가 관찰 (판정에 넣지 않음)

1. **1회차와 비교한 차이.** 같은 요청의 응답 코드·헤더·본문·오류 문구가 모두 1회차와 같았다. 바뀐 것은 둘이다.
   - 결함 키 기동 오류의 문구가 바뀌었다 (AC-09 항목).
   - 계정 1회차의 "자식이 남은 계정 DELETE → `409 CannotDeleteResource`"는 1회차에 리더 지시로 빠졌다. 이번에 풀 사이클 AC-09에서 실환경으로 확인했다. 메시지는 "Cannot delete resource while nested resources exist. Some existing nested resource IDs include: 'Microsoft.NetApp/netAppAccounts/e2e-pool-acct9/capacityPools/e2e-p09'. Please delete all nested resources before deleting this resource."이다.
2. **1회차 추가 관찰 2(기동 경고 로그)는 그대로다.** `Fault injection is enabled (ANF_FAULT_INJECTION): {'netAppAccounts/create': Fault(delay_seconds=5.0, fail=False), ...}`가 레벨 접두사 없이 stderr로 나간다(`arm_app.py:76-77`). FR-12에서 다룰 거리다.
3. **WSL 시계.** 게스트 단조 시계가 Windows 호스트보다 약 10% 느리게 간다(60 s 비교 2회: 0.9034, 0.9009). 게스트 벽시계는 약 33초마다 +3.3 s씩 앞으로 맞춰진다. 그래서 1초 폴링 사이에 2~4 s 간격이 보이고, 작업 시간이 벽시계로 6.4 s처럼 보인 경우가 있었다. 판정에 쓴 시간 조건은 단조 시계로 쟀고 여유가 커서 영향이 없다. 자세한 측정과 FR-08에 주는 의미는 풀 보고서 추가 관찰 2에 있다.
4. 1회차 추가 관찰 6(`e2e` 마커 설명이 Docker 마운트를 가리킴)은 그대로다. 이번 풀 e2e도 Docker를 쓰지 않는다.
5. 정리: 검증용 서버 프로세스는 모두 멈췄고 8080 포트는 비어 있다. pytest 임시 디렉터리는 지웠다. 요청·응답 기록 `/tmp/anf-e2e-acct-r2.jsonl`과 데이터 플레인 스냅숏 `/tmp/anf-e2e-dp/`는 증거로 남겼다(WSL).
