# netapp-account 검증 보고서 — 1회차

- 검증일: 2026-11-07 (로컬 PST. 실행 시각은 UTC 2026-11-08 02:03~02:09)
- 검증 대상 코드:
  - 기준 커밋 `b96dbaf5340edbc9905556e5c47a4ca0a111d8ab` (`git rev-parse HEAD`). 제품 코드는 미커밋이다. `backend/anf_api/` 전체가 새 파일(untracked)이고, `pyproject.toml`이 수정됐다(M).
  - `git diff HEAD`는 untracked 파일인 `backend/`를 담지 않는다. 그래서 리더가 정한 해시를 기준으로 삼았다.
    `cat pyproject.toml backend/anf_api/__init__.py backend/anf_api/accounts.py backend/anf_api/arm_app.py backend/anf_api/arm_rules.py backend/anf_api/lro.py backend/anf_api/state_store.py | sha256sum`
    = `bf4e61d3f5e6f9326985b7009519385eb5706913bfe85877a39bea2284bd01d0`
  - 검증을 시작할 때와 끝낸 뒤에 각각 계산했고 두 값이 같았다. 리더가 넘긴 값과도 같다.
- 이번 회차 범위: 전체 (AC-01~AC-13).
  - 자식이 남은 계정 DELETE의 `409 CannotDeleteResource`는 리더 지시로 넣지 않았다 (설계 결정 8, 용량 풀 사이클로 옮김).
- 검증 방법:
  - WSL Ubuntu에서 anf-api를 설계 §6.5의 명령 그대로 **실제 uvicorn 프로세스**로 띄웠다. 요청은 별도 프로세스(pytest)에서 표준 라이브러리 `http.client`로 보냈다. TestClient는 쓰지 않았다.
  - 상태 저장소(`ANF_API_DB`)는 시나리오마다 `/tmp`(ext4) 아래 새 임시 파일로 두었다. 기본 경로는 쓰지 않았다.
  - 교차 확인: 테스트 도구와 무관하게, 리더가 준 명령으로 서버를 손으로 띄우고 `curl -i`로 원시 헤더를 확인했다 (아래 AC-01·AC-07).
- 검증 스크립트 (새로 만듦, 제품 코드는 고치지 않았다):
  - `backend/tests/e2e/live_api.py`: 서버 실행·SIGKILL, HTTP 호출, 1초 폴링, 요청·응답 JSONL 기록
  - `backend/tests/e2e/conftest.py`: 서버 팩토리 fixture
  - `backend/tests/e2e/test_netapp_account_live.py`: AC-01~AC-07, AC-13
  - `backend/tests/e2e/test_netapp_account_lro_faults_live.py`: AC-08~AC-11, AC-13, 설계 §6.3 추가 관찰
  - 모두 `e2e` 마커가 붙어 있다. `ANF_E2E_API_URL`이 없으면 skip한다. 기본 실행 결과는 Windows와 WSL 모두 `141 passed, 24 skipped`이다.
- 재현 명령 (WSL, 저장소 루트):
  ```
  ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/tmp/anf-e2e.jsonl \
    ~/.venvs/anf-clone/bin/python -m pytest backend/tests/e2e -m e2e -v -p no:cacheprovider
  ```
  AC-12만 셸에서 root로 따로 비교한다 (명령은 AC-12 항목에 있다).

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`에서 `Ubuntu Running 2`. 커널 `6.18.54.1-microsoft-standard-WSL2`, Ubuntu 24.04.1 LTS |
| Python 가상환경 | `~/.venvs/anf-clone`: Python 3.12.3, fastapi 0.162.2, uvicorn 0.54.0, starlette 1.10.0 |
| 포트 `127.0.0.1:8080` | 시작 전에 비어 있었다(`ss -ltn`). 끝난 뒤에도 비어 있고 anf-api 프로세스도 남아 있지 않다 |
| 임시 DB 위치 | `/tmp`는 ext4(`/dev/sdd`)다. 설계 결정 10의 9P 회피 조건을 충족한다 |
| 컨트롤 플레인 서비스 | 시나리오마다 테스트가 직접 띄웠다. 준비 여부는 구독 목록 GET이 `200`인지로 확인했다. 기동에 0.6초쯤 걸렸고, 실패한 기동은 없었다(§6.3의 의도된 기동 실패는 제외) |
| root `exportfs` (AC-12) | `/usr/sbin/exportfs`를 쓸 수 있다. `nfs-server`는 `active`다. 현재 export는 0개다 |
| Docker, 커널 모듈 | 컨트롤 플레인 전용 기능이라 필요 없어서 점검하지 않았다 (스킬 §0) |

## 결과 요약

PASS 13 / FAIL 0 / UNVERIFIED 0

- 같은 e2e 묶음(24개 테스트)을 세 번 실행했고 세 번 모두 전부 통과했다.
  - 1회: 모듈별로 나눠 실행. AC-12 비교를 사이에 끼우려고 나눴다.
  - 2회, 3회: 두 모듈을 한 번에 실행.
- 불안정한 결과는 없었다.

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

## 항목별 결과

표기: 아래 출력에서 `{SUB}`는 `/subscriptions/0e2e0000-1111-4222-8333-444455556666`, `{base}`는 `http://127.0.0.1:8080`, `M.N`은 `Microsoft.NetApp`이다. 모든 경로에는 `?api-version=2026-08-01`이 붙어 있다(따로 적은 경우는 제외).

### [PASS] AC-01 새 계정 PUT → 201, Creating, Azure-AsyncOperation만 → 폴링 Succeeded (계약·상태)
- 기준: `201`, 본문 `Creating`, 헤더는 `Azure-AsyncOperation`만(`Location` 없음), URL은 `{opUrl}` 형식, 폴링하면 `200`·`Succeeded`·`100.0`·`CREATE`, 이후 GET은 `Succeeded`.
- 실행: `test_netapp_account_live.py::test_ac01_create_returns_201_creating_and_operation_succeeds`. URL은 정규식 `^{base}/subscriptions/{sub}/providers/Microsoft\.NetApp/locations/westus2/operationResults/{uuid}\?api-version=2026-08-01$`로 확인했다.
- 출력:
  ```
  PUT {SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts/e2e-ac01  body {"location":"westus2","tags":{"k":"v"}}
  -> 201 (20.4 ms)
     azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/3b822c7c-a169-4b2f-b614-5ae7cc91a01f?api-version=2026-08-01
     (location 헤더 없음, retry-after 헤더 없음)
     body: {"id":".../netAppAccounts/e2e-ac01","name":"e2e-ac01","type":"Microsoft.NetApp/netAppAccounts","location":"westus2",
            "tags":{"k":"v"},"properties":{"provisioningState":"Creating","encryption":{"keySource":"Microsoft.NetApp"}}}
  GET <azure-asyncoperation> -> 200
     {"id":"{SUB}/providers/M.N/locations/westus2/operationResults/3b822c7c-...","name":"3b822c7c-...","status":"Succeeded",
      "startTime":"2026-11-08T02:04:05.025881Z","percentComplete":100.0,
      "properties":{"resourceName":".../netAppAccounts/e2e-ac01","action":"CREATE"},"endTime":"2026-11-08T02:04:05.032838Z"}
  GET 계정 -> 200, "provisioningState":"Succeeded"
  ```
- curl 교차 확인(손으로 띄운 서버): `HTTP/1.1 201 Created`. 헤더는 `azure-asyncoperation`, `content-length`, `content-type`, `x-ms-request-id`, `x-ms-correlation-request-id`뿐이고 `location`은 없다.

### [PASS] AC-02 기존 계정 PUT → 200, Updating → Succeeded, tags 교체 (계약·상태)
- 실행: `test_ac02_put_existing_returns_200_updating_and_replaces_tags`
- 출력:
  ```
  (생성: tags {"old":"1","keep":"no"} -> 201 -> 작업 Succeeded)
  PUT e2e-ac02  body {"location":"westus2","tags":{"new":"2","x":"y"}}
  -> 200, azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/d7cf149e-..., location 헤더 없음
     body: ... "tags":{"new":"2","x":"y"},"properties":{"provisioningState":"Updating",...}
  GET <aao> -> 200 {"status":"Succeeded","percentComplete":100.0,"properties":{...,"action":"UPDATE"},...}
  GET 계정 -> 200 "tags":{"new":"2","x":"y"}, "provisioningState":"Succeeded"   (이전 키 old·keep이 남지 않음)
  ```

### [PASS] AC-03 GET 본문 필드, 없는 계정 404, 대소문자만 다른 이름 (계약)
- 실행: `test_ac03_get_body_fields_not_found_and_case_insensitive_name`
- 출력:
  ```
  GET .../netAppAccounts/E2e-Ac03-Mixed -> 200
     {"id":"{SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts/E2e-Ac03-Mixed","name":"E2e-Ac03-Mixed",
      "type":"Microsoft.NetApp/netAppAccounts","location":"westus2","tags":{"k":"v"},
      "properties":{"provisioningState":"Succeeded","encryption":{"keySource":"Microsoft.NetApp"}}}
  GET .../e2e-ac03-missing -> 404 {"error":{"code":"ResourceNotFound","message":"The resource with identifier '.../e2e-ac03-missing' is not found."}}
  GET .../E2E-AC03-MIXED -> 200, 본문이 위와 바이트 단위로 같음 (name은 처음 받은 "E2e-Ac03-Mixed" 그대로)
  GET .../e2e-ac03-mixed -> 200, 같음
  ```
- §4.4의 필드 `id`, `name`, `type`, `location`, `tags`, `properties.provisioningState`, `properties.encryption.keySource`가 모두 있다.

### [PASS] AC-04 리소스 그룹 목록, 다른 리소스 그룹 목록, 구독 목록 (계약)
- 실행: `test_ac04_resource_group_and_subscription_lists`. `rg-e2e`에 `e2e-ac04`를, `rg-e2e-other`에 `e2e-ac04-other`를 만들었다.
- 출력:
  ```
  GET {SUB}/resourceGroups/rg-e2e/providers/M.N/netAppAccounts        -> 200 {"value":[...e2e-ac01, e2e-ac02, ..., e2e-ac04 ...]}  (e2e-ac04-other 없음)
  GET {SUB}/resourceGroups/rg-e2e-other/providers/M.N/netAppAccounts  -> 200 {"value":[{"name":"e2e-ac04-other",...}]}         (e2e-ac04 없음)
  GET {SUB}/providers/M.N/netAppAccounts                              -> 200 {"value":[... 둘 다 포함 ...]}
  GET /subscriptions/0e2e0000-9999-.../providers/M.N/netAppAccounts   -> 200 {"value":[]}   (추가 확인: 다른 구독)
  ```
- 응답 최상위 키는 `value` 하나다.

### [PASS] AC-05 PATCH tags → 동기 200, 추적 헤더 없음, 맵 교체 (계약)
- 실행: `test_ac05_patch_tags_is_synchronous_and_replaces_map`
- 출력:
  ```
  (생성: tags {"a":"1"} -> Succeeded)
  PATCH e2e-ac05  body {"tags":{"b":"2"}}
  -> 200 (12.1 ms), 헤더: content-length, content-type, x-ms-request-id, x-ms-correlation-request-id 뿐 (azure-asyncoperation·location 없음)
     body: ... "tags":{"b":"2"},"properties":{"provisioningState":"Succeeded",...}
  GET e2e-ac05 -> 200 "tags":{"b":"2"}, "provisioningState":"Succeeded"
  PATCH e2e-ac05-missing -> 404 {"error":{"code":"ResourceNotFound",...}}
  ```

### [PASS] AC-06 잘못된 요청 거절, 작업·상태 변화 없음 (계약)
- 실행: `test_ac06_rejected_put_creates_no_operation_and_changes_nothing`. 경우마다 매개변수화한 테스트 9개가 모두 통과했다.
- 경우마다 확인한 것:
  - 응답 코드와 `error.code`
  - `Azure-AsyncOperation`·`Location` 헤더가 없다
  - 요청 전후의 구독 목록(id·location·tags·상태)이 같다
  - 기존 계정 `e2e-ac06`의 GET 본문이 그대로다
  - 이름이 올바른 경우 그 이름의 GET이 `404`다. 리소스가 생기지 않았다는 뜻이다
  - 보조 증거: 상태 저장소 `operations` 테이블의 행 목록이 요청 전후에 같다
- 출력:

  | 요청 | 응답 | error.code / message |
  | --- | --- | --- |
  | PUT `.../netAppAccounts/-abc` | 400 | `InvalidResourceName` / "The NetApp account name '-abc' is invalid. It must start with an alphanumeric character, ..." |
  | PUT `.../netAppAccounts/a×129` | 400 | `InvalidResourceName` |
  | PUT `.../netAppAccounts/a.b` | 400 | `InvalidResourceName` |
  | PUT `.../e2e-ac06-nover` (쿼리 없음) | 400 | `MissingApiVersionParameter` / "The api-version query parameter (?api-version=) is required for all requests." |
  | PUT `...?api-version=2025-01-01` | 400 | `NoRegisteredProviderFound` / "... The supported api-versions are '2026-08-01'." |
  | PUT 본문 `{"tags":{"a":"1"}}` | 400 | `InvalidRequestContent` / "The 'location' property is required." |
  | PUT 본문 `{"location":"westus2","unknownProp":1}` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'unknownProp'." |
  | PUT 본문 `{"location":"westus2","identity":{"type":"SystemAssigned"}}` | 400 | `InvalidRequestContent` / "The property 'identity' is not supported by this ANF clone." |
  | 기존 `e2e-ac06`(westus2)에 PUT `{"location":"eastus","tags":{"changed":"1"}}` | 409 | `InvalidResourceLocation` / "The resource 'e2e-ac06' already exists in location 'westus2' ..." |

  - 마지막 경우 뒤의 GET `e2e-ac06`도 `location: westus2`, `tags: {"keep":"1"}`, `Succeeded`로 그대로였다.

### [PASS] AC-07 DELETE → 202, 두 헤더 → Succeeded → Location 204, GET 404, 재DELETE 204 (계약·상태)
- 실행: `test_ac07_delete_returns_202_with_both_headers_then_resource_is_gone`
- 출력:
  ```
  DELETE e2e-ac07 -> 202, 본문 b"" (content-length: 0)
     location:             {base}{SUB}/providers/M.N/locations/westus2/operationResults/3af0188f-...?api-version=2026-08-01&operationResultResponseType=Location
     azure-asyncoperation: {base}{SUB}/providers/M.N/locations/westus2/operationResults/3af0188f-...?api-version=2026-08-01
  GET <aao> -> 200 {"status":"Succeeded","percentComplete":100.0,"properties":{...,"action":"DELETE"},...}
  GET <location> -> 204, 본문 없음
  GET e2e-ac07 -> 404 ResourceNotFound
  DELETE e2e-ac07 -> 204, 본문 없음
  ```
- curl 교차 확인: `HTTP/1.1 202 Accepted`, `location: ...&operationResultResponseType=Location`, `azure-asyncoperation: ...`, `content-length: 0`. 완료 뒤 Location GET은 `HTTP/1.1 204 No Content`, 계정 GET은 `404`였다.

### [PASS] AC-08 지연 주입 중 진행 상태 (상태, FR-01 진행 중)
- 서버: `ANF_FAULT_INJECTION={"netAppAccounts/create":{"delaySeconds":5.0},"netAppAccounts/delete":{"delaySeconds":5.0}}` (pid 6651). 시작 로그에 `Fault injection is enabled (ANF_FAULT_INJECTION): {...}`가 찍혔다.
- 실행: `test_netapp_account_lro_faults_live.py::test_ac08_in_progress_states_with_injected_delay`
- 출력:
  ```
  PUT e2e-ac08 -> 201 (10.5 ms, 주입 지연 5 s)  body "provisioningState":"Creating"
  GET <aao> -> 200 {"status":"Creating","startTime":"2026-11-08T02:04:55.300718Z","percentComplete":0.0,
                    "properties":{"resourceName":".../e2e-ac08","action":"CREATE"}}   (endTime 없음)
  GET 계정 -> 200 "provisioningState":"Creating"
  GET <aao>&operationResultResponseType=Location -> 202, 본문 없음, location 헤더 = 같은 URL   (추가 확인)
  폴링 (1초 간격): Creating ×5 -> Succeeded, endTime 02:05:00.310781Z (startTime부터 5.010 s)
  GET 계정 -> 200 Succeeded
  DELETE e2e-ac08 -> 202
  GET <location> -> 202, 본문 b"", location: {base}{SUB}/.../operationResults/93c548c6-...?api-version=2026-08-01&operationResultResponseType=Location
  GET 계정 -> 200 "provisioningState":"Deleting"
  GET <aao> -> 200 {"status":"Deleting","percentComplete":0.0,...,"action":"DELETE"}
  폴링: Deleting ×5 -> Succeeded, endTime 02:05:05.392040Z (5.010 s)
  GET <location> -> 204,  GET 계정 -> 404
  ```

### [PASS] AC-09 실패 주입, 회복, 삭제 실패 (상태, FR-01 실패)
- 실행: `test_ac09_injected_create_failure_then_recovery`, `test_ac09_injected_delete_failure_leaves_account_failed`. 두 테스트 모두 같은 DB로 서버를 다시 띄워 확인했다.
- 출력 (생성 실패 → 회복):
  ```
  [서버 pid 6655, ANF_FAULT_INJECTION={"netAppAccounts/create":{"fail":true}}]
  PUT e2e-ac09 {"location":"westus2","tags":{"v":"1"}} -> 201 Creating
  GET <aao> -> 200 {"status":"Failed","percentComplete":100.0,"properties":{...,"action":"CREATE"},"endTime":"...",
                    "error":{"code":"InternalServerError","message":"Injected fault: netAppAccounts/create (ANF_FAULT_INJECTION)."}}
  GET <aao>&operationResultResponseType=Location -> 500 {"error":{"code":"InternalServerError","message":"Injected fault: ..."}}
  GET 계정 -> 200 "provisioningState":"Failed"
  [SIGTERM, 같은 DB로 주입 없이 재기동 pid 6656]
  GET 계정 -> 200 Failed   (재기동 뒤에도 유지)
  PUT e2e-ac09 {"location":"westus2","tags":{"v":"2"}} -> 200, "provisioningState":"Updating", azure-asyncoperation 있음
  GET <aao> -> 200 {"status":"Succeeded","properties":{...,"action":"UPDATE"}}
  GET 계정 -> 200 Succeeded, "tags":{"v":"2"}
  ```
- 출력 (삭제 실패):
  ```
  [pid 6657, 주입 없음] PUT e2e-ac09-del -> 201 -> Succeeded   [SIGTERM]
  [pid 6658, ANF_FAULT_INJECTION={"netAppAccounts/delete":{"fail":true}}, 같은 DB]
  DELETE e2e-ac09-del -> 202 (두 헤더)
  GET <aao> -> 200 {"status":"Failed","properties":{...,"action":"DELETE"},"error":{"code":"InternalServerError","message":"Injected fault: netAppAccounts/delete (ANF_FAULT_INJECTION)."}}
  GET 계정 -> 200 "provisioningState":"Failed"   (계정이 남아 있음)
  GET <location> -> 500 ErrorResponse
  ```

### [PASS] AC-10 진행 중 충돌 → 409 AnotherOperationInProgress (계약)
- 서버: 생성·삭제 지연 5 s (pid 6659)
- 실행: `test_ac10_conflicting_requests_while_in_progress`
- 출력:
  ```
  PUT e2e-ac10 {"tags":{"orig":"1"}} -> 201;  GET <aao> -> status "Creating"
  PUT    e2e-ac10 {"tags":{"other":"x"}} -> 409 {"error":{"code":"AnotherOperationInProgress","message":"Another operation is in progress on resource '.../e2e-ac10'. Wait until it is finished, and then retry."}}
  PATCH  e2e-ac10 {"tags":{"patched":"1"}} -> 409 AnotherOperationInProgress
  DELETE e2e-ac10 -> 409 AnotherOperationInProgress
     (세 응답 모두 azure-asyncoperation·location 헤더 없음)
  보조 증거: operations 테이블에서 이 리소스의 작업 = 1개
  폴링: Creating ×5 -> Succeeded (endTime 02:05:14.857799Z)
  GET 계정 -> tags {"orig":"1"}, Succeeded   (거절된 PUT·PATCH의 tags가 반영되지 않음)
  추가: DELETE -> 202, status "Deleting" 중에 PUT·PATCH·DELETE -> 각각 409 AnotherOperationInProgress
  폴링 -> Succeeded, GET -> 404.  operations 테이블의 이 리소스 작업 = ["CREATE","DELETE"] (거절된 요청은 작업을 만들지 않음)
  ```

### [PASS] AC-11 SIGKILL 뒤 재시작하면 진행 중 작업이 끝까지 실행된다 (상태, AR-04)
- 실행: `test_ac11_operation_resumes_after_sigkill_restart`. 매개변수 2개다. 같은 주입 설정으로 다시 띄운 경우와 주입 없이 다시 띄운 경우다.
- 출력 (재기동에 같은 지연 적용):
  ```
  [pid 6660, 생성 지연 5 s] PUT e2e-ac11 -> 201;  GET <aao> -> "Creating"
  SIGKILL pid 6660 -> returncode -9 (02:05:24.188Z). 서버 로그에 "Shutting down" 없음(강제 종료). 포트 8080 닫힘
  보조 증거: DB의 작업 상태 = ["Creating"]   (죽을 때 진행 중이었음)
  [같은 DB, 같은 주입으로 재기동 pid 6661, ready 02:05:24.816Z]
  같은 <aao> 폴링: Creating ×5 -> Succeeded, endTime 02:05:29.601127Z (재기동 뒤 약 4.8 s: 지연을 처음부터 다시 실행)
  GET 계정 -> 200 Succeeded.  이 리소스의 작업 수 = 1 (새 작업이 생기지 않음)
  ```
- 출력 (주입 없이 재기동):
  ```
  [pid 6662] PUT -> 201, "Creating" -> SIGKILL rc -9 -> [pid 6663, 주입 없음] 
  같은 <aao> 첫 폴링 -> Succeeded, endTime 02:05:31.150061Z (준비 확인 응답 02:05:31.340Z보다 먼저 끝남: 기동 직후 워커가 복구 실행)
  GET 계정 -> 200 Succeeded
  ```

### [PASS] AC-12 계정 작업 전후 데이터 플레인 불변 (데이터 플레인 불변)
- 실행 (root):
  ```
  wsl -d Ubuntu -u root -e bash -c 'exportfs -v; ls -la --time-style=full-iso /etc/exports.d/;
      sha256sum /etc/exports /var/lib/nfs/etab; cat /proc/fs/nfsd/exports'
  ```
  - 이 명령을 AC-01~AC-07 모듈을 실행하기 직전(02:03:56Z)과 직후(02:04:12Z)에 실행했다.
  - 모든 실행이 끝난 뒤(02:07:52Z)에도 한 번 더 실행했다. 그 사이에 live 모듈 3회, 결함 주입 모듈 3회, curl 확인을 했다.
- 출력 (세 시점 모두 같다):
  ```
  ## exportfs -v           (출력 없음, rc=0)
  ## ls -la /etc/exports.d/  total 8, "." 2026-11-07 17:06:06.408602641 (항목 없음)
  ## sha256 /etc/exports      3f95c811c082f8c8a0cfda159146c0ce388a37248fe173907a5cb57c98f2fee3
  ## sha256 /var/lib/nfs/etab e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 (빈 파일)
  ## /proc/fs/nfsd/exports    "# Version 1.1" / "# Path Client(Flags) # IPs" (export 없음)
  diff (before vs after_live, before vs after_all) -> IDENTICAL
  ```
- 비교에서 `ls`의 `..` 줄(`/etc` 자체)은 뺐다. `/etc`의 mtime은 WSL을 띄울 때마다 바뀌어서 계정 작업과 무관하다(02:03:56 → 02:04:12).
- 한계: 비교하기 전부터 export가 0개였다. 그래서 이 항목이 보여 주는 것은 "계정 작업이 export를 만들거나 바꾸지 않았다"이다. 기존 export가 지워지지 않는지는 이번 조건으로 확인할 수 없다(계정 코드에는 storage agent 호출이 없다. `accounts.py:207` `_no_storage_work`).

### [PASS] AC-13 x-ms-request-id와 x-ms-correlation-request-id (계약, 추적성)
- 실행: `test_ac13_request_and_correlation_ids`, `test_ac13_request_id_on_every_fault_scenario_response`
- 출력:
  - 모듈 1에서 AC-13 테스트 전까지 받은 응답 84개(준비 확인 GET, 오류 응답, 본문 없는 204·202 포함)에 모두 `x-ms-request-id`가 있었다. 값은 UUID이고 서로 모두 달랐다(테스트 단언). AC-13 테스트 안의 상관 ID 경우 6개도 하나씩 확인했다. 모듈 1의 HTTP 응답은 모두 97개였다.
  - 모듈 2도 같았다. 상태 코드 200·201·202·204·404·409·500이 모두 나왔고, 그 모든 응답에 `x-ms-request-id`가 있었으며 서로 모두 달랐다.
  - 보낸 상관 ID는 그대로 돌아왔다. 성공, 오류, 본문 없는 응답 모두 같았다:
    ```
    GET 계정 200 / GET 없는 계정 404 / PUT -bad 400 / PATCH 200 / DELETE 없는 계정 204 / GET 구독 목록 200
      요청 x-ms-correlation-request-id: e2e-corr-<uuid>  -> 응답에 같은 값
    ```
  - 보내지 않으면 응답마다 새 UUID가 왔다. 연속한 GET 두 번의 값이 서로 달랐다.
  - curl 확인: PUT에 `x-ms-correlation-request-id: curl-corr-1`을 보내자 응답에 `x-ms-correlation-request-id: curl-corr-1`이 왔다. 보내지 않은 요청에는 `7ce301d0-...` 같은 새 값이 왔다.
  - 보조 증거(설계 §4.5): 상관 ID를 넣어 보낸 PUT의 작업 행에 `correlation_id`가 그 값으로 저장돼 있었다.

## 측정값

| 항목 | 값 | 반복 |
| --- | --- | --- |
| 지연 없는 작업의 startTime → endTime | 7~10 ms (예: AC-01 6.96 ms, AC-07 DELETE 7.8 ms) | 실행마다 여러 작업 |
| 5 s 생성 지연을 주입했을 때의 PUT 응답 시간 | 10.5 ms (AC-08), 9.9 ms·11.6 ms (AC-11), 60.0 ms (AC-10) | 1회 실행 안에서 4회 |
| 5 s 지연을 주입했을 때의 작업 시간 (startTime → endTime) | 생성 5.010 s, 삭제 5.010 s (AC-08) | 1회 |
| SIGKILL 재기동 뒤 완료까지 (같은 지연) | 재기동 준비 뒤 약 4.8 s | 1회 |
| 서버 기동(준비 확인 200까지) | 0.622~0.628 s (`/mnt/c`의 코드를 import) | 1회 실행에서 기동 12번 |
| e2e 전체 실행 | 1회: 1.30 s + 35.62 s (모듈별), 2회: 36.56 s, 3회: 36.64 s | 3회, 모두 24/24 통과 |

## 추가 관찰 (판정에 넣지 않음)

1. **§5 상태 전이를 실서버에서 모두 확인했다.**
   - 수락 기준이 다루지 않는 두 전이는 curl로 따로 확인했다. 서버는 손으로 띄웠고, 임시 DB는 확인 뒤 지웠다.
   - `Updating → Failed`(되돌리기):
     - `{"netAppAccounts/update":{"fail":true}}`를 켜고 tags `{"orig":"1"}`인 계정에 tags `{"new":"2"}`로 PUT했다.
     - 응답은 `200`, `Updating`이었고 본문 tags는 `{"new":"2"}`였다.
     - 작업은 `Failed`(`UPDATE`, `InternalServerError`)로 끝났다.
     - 그 뒤 GET은 `Failed`이고 tags가 `{"orig":"1"}`로 되돌아가 있었다.
   - `Failed → Deleting → [*]`: 주입 없는 서버에서 위의 `Failed` 계정을 DELETE하자 작업이 `Succeeded`(`DELETE`)로 끝났고, GET은 `404`였다.
   - 수락 기준으로 확인한 전이:
     - `Creating → Succeeded`, `Creating → Failed`
     - `Succeeded → Updating → Succeeded`, `Failed → Updating → Succeeded`
     - `Succeeded → Deleting → [*]`, `Succeeded → Deleting → Failed`
2. **설계 §6.3 기동 검사** (`test_s63_fault_injection_startup_guard_and_warning`, 통과):
   - JSON이 아닌 값을 넣으면 uvicorn이 0이 아닌 코드로 끝나고 포트를 열지 않는다. 로그는 `ValueError: ANF_FAULT_INJECTION is not valid JSON: Expecting ',' delimiter: line 1 column 46 (char 45)`이다.
   - 모르는 키 `netAppAccounts/resize`를 넣어도 같다. 로그는 `ValueError: Unknown fault key 'netAppAccounts/resize'. Use '{type}/{create|update|delete}' with type in ['netAppAccounts']`이다.
   - 올바른 값이면 기동 로그 첫 줄에 `Fault injection is enabled (ANF_FAULT_INJECTION): {...}`가 찍힌다.
   - 참고:
     - 이 경고는 uvicorn이 설정한 로거가 아니라 Python 기본 lastResort 핸들러로 stderr에 나간다. 그래서 uvicorn 줄과 달리 `WARNING:` 같은 레벨 접두사나 시각이 붙지 않는다(`arm_app.py:65`).
     - 작업 처리기 예외 로그(`lro.py:129`)도 같은 경로로 나갈 것이다.
     - 설계를 어긴 것은 아니다. FR-12(구조화 로그)에서 다룰 거리다.
3. 실패한 작업도 `percentComplete: 100.0`이다. 브리프의 ANF 녹화(실패 시 100.0)와 같다.
4. SIGTERM으로 멈춘 서버의 종료 코드는 `-15`다. 로그에는 "Application shutdown complete"가 남는다. uvicorn이 정상 종료를 마친 뒤 신호를 다시 올리는 동작이라 문제가 아니다.
5. 진행 중 충돌(AC-10)은 `Creating`과 `Deleting` 중에 확인했다. `Updating` 중 충돌은 실서버에서 보지 않았다. 세 경우 모두 같은 검사(`state_store.py:184` `ensure_no_active_operation`)를 지난다.
6. `pyproject.toml:29`의 `e2e` 마커 설명은 "Docker 클라이언트 컨테이너로 마운트한다"이다. 이번 e2e 테스트는 리더 지시로 `e2e` 마커를 달았지만 Docker를 쓰지 않는다. 마커 설명을 넓힐지는 리더가 판단할 일이다. 제품 설정이라 고치지 않았다.
7. 통합 정합성(스킬 §3): 구성 요소가 anf-api 하나뿐이다(대시보드·CLI 없음). 응답 구조나 호출 관계를 대조할 상대가 아직 없다.
8. 정리:
   - 검증용 서버 프로세스는 모두 멈췄다. 확인한 결과 `uvicorn --factory anf_api` 프로세스가 없고 8080 포트도 비어 있다.
   - 임시 디렉터리 `/tmp/anf-e2e-account`와 `/tmp/anf-e2e-extra.*`(DB, 서버 로그, JSONL 기록)는 지웠다.
   - WSL `/tmp/anf-smoke.log`는 이번 검증이 만든 파일이 아니어서 그대로 두었다.
