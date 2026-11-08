# capacity-pool 검증 보고서 — 2회차

- 검증일: 2026-11-07 (로컬 PST). 실행 시각은 UTC 2026-11-08 03:21~03:27
- 검증 대상 코드:
  - 기준 커밋 `e602d11b1c8569064eab3d38156880cdd25aed29`. 제품 코드는 미커밋이다.
  - 기준 해시는 1회차와 같은 명령으로 계산했다(저장소 루트):
    `cat pyproject.toml backend/anf_api/__init__.py backend/anf_api/accounts.py backend/anf_api/arm_app.py backend/anf_api/arm_rules.py backend/anf_api/capacity_pools.py backend/anf_api/lro.py backend/anf_api/state_store.py | sha256sum`
    = `a461dbaf36e65c53e3b8a0bb2aee3379fa391f8b9fb5889c08b2247e8a038485`
  - 시작(03:21:45Z)과 끝(03:26:53Z)에 Git Bash와 WSL 양쪽에서 계산했고 네 값이 모두 같았다. 리더가 넘긴 값과도 같다.
  - 1회차 대상은 `f58df82d…`였다. 리더에 따르면 바뀐 것은 `backend/anf_api/capacity_pools.py`의 오류 메시지 두 줄이다. 코드에서 확인한 바뀐 곳은 `capacity_pools.py:61-63`(serviceLevel의 Flexible·StandardZRS)과 `:94-99`(encryptionType)다. 두 곳 모두 `unsupported_property` 대신 메시지를 직접 만든다.
- 이번 회차 범위: 재검증.
  - 다시 판정한 기준: AC-06 (1회차 추가 관찰 4의 수정을 직접 받는 기준).
  - 회귀로 다시 실행한 것: 풀과 계정의 live e2e 스크립트 전체(4개 모듈). 리더 지시대로, 스크립트로 덮이지 않는 부분(curl 교차 확인, 데이터 플레인 스냅숏 등)은 손으로 다시 돌리지 않았다.
- 검증 방법: 1회차와 같다. WSL에서 실제 uvicorn 프로세스를 띄우고 pytest가 `http.client`로 요청했다. DB는 시나리오마다 `/tmp`의 새 임시 파일이다.
  - **포트를 8081로 바꿨다.** 검증을 시작할 때 `127.0.0.1:8080`에 이 검증과 무관한 anf-api가 떠 있었다. pid 8387, 03:16:50Z 시작, `ANF_API_DB=~/.local/state/anf-clone/manual-test.db`, 지연 주입 켜짐. 다른 사람의 프로세스라 건드리지 않았다. e2e 도구는 포트를 `ANF_E2E_API_URL`에서 읽으므로 `http://127.0.0.1:8081`로 실행했다. 포트는 수락 기준과 관계가 없다.
- 검증 스크립트 변경: `backend/tests/e2e/test_capacity_pool_live.py`
  - AC-06에 `serviceLevel: StandardZRS` 경우(`serviceLevel-StandardZRS`)를 더했다. 매개변수가 17개에서 18개가 됐다.
  - 미룬 기능 다섯 경우(Flexible, StandardZRS, Double, coolAccess, customThroughputMibps)는 메시지 **전체**를 기대 문자열과 같은지 비교하도록 바꿨다(`UNSUPPORTED_MESSAGES`). 1회차에는 "not supported by this ANF clone"이 들어 있는지만 봤다.
  - 다른 스크립트는 바꾸지 않았다.
- 재현 명령 (WSL, 저장소 루트):
  ```
  ANF_E2E_API_URL=http://127.0.0.1:8081 ANF_E2E_LOG=/tmp/anf-e2e.jsonl \
    ~/.venvs/anf-clone/bin/python -m pytest backend/tests/e2e -m e2e -v -p no:cacheprovider
  ```

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL 배포판, Python 가상환경 | 1회차와 같다 (Ubuntu Running, Python 3.12.3, fastapi 0.162.2, uvicorn 0.54.0) |
| 포트 | `8080`: 무관한 anf-api(pid 8387)가 사용 중이다. 그래서 `8081`을 썼다. `8081`은 시작 전과 끝난 뒤 모두 비어 있다 |
| 임시 DB 위치 | `/tmp` (ext4) |
| 컨트롤 플레인 서비스 | 시나리오마다 테스트가 직접 띄웠다. 실패한 기동은 없었다(결함 키 검사의 의도한 기동 실패는 제외) |
| Docker, 커널 모듈, root `exportfs` | 이번 회차에서는 쓰지 않았다 (AC-13은 1회차 결과를 유지) |

## 결과 요약

PASS 13 / FAIL 0 / UNVERIFIED 0

- 이번에 다시 판정한 AC-06은 PASS다.
- 나머지 12개는 1회차 PASS를 유지한다. 변경은 메시지 문자열 두 개뿐이고, e2e 회귀가 모두 통과했다.
- e2e 폴더 전체(63개 테스트)를 두 번 실행했고 두 번 모두 `63 passed`(실패 0, skip 0)였다.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac01_*`) |
| AC-02 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac02_*` 3개) |
| AC-03 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac03_*`) |
| AC-04 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac04_*`) |
| AC-05 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac05_*`) |
| AC-06 | PASS | **2회차 (이 보고서)** |
| AC-07 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (두 모듈의 `test_ac07_*`) |
| AC-08 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac08_*`) |
| AC-09 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac09_*`) |
| AC-10 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac10_*` 3개) |
| AC-11 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac11_*`) |
| AC-12 | PASS | 1회차 PASS 유지 + 2회차 e2e 회귀 통과 (`test_ac12_*` 2개) |
| AC-13 | PASS | 1회차 PASS 유지 (`04_verifier_report.md`). 셸 비교 항목이라 이번에는 다시 돌리지 않았다. 바뀐 코드는 오류 메시지뿐이고, storage agent 호출이 없다(`capacity_pools.py` `_no_storage_work`) |
| CV-1~CV-3 | 판정 대상 아님 | 볼륨 사이클로 옮김 (설계 §8) |

## 항목별 결과

표기: `pool:Y` = `{SUB}/resourceGroups/rg-e2e/providers/Microsoft.NetApp/netAppAccounts/e2e-pool-acct/capacityPools/Y`. 모든 경로에는 `?api-version=2026-08-01`이 붙어 있다. 출력은 1회 실행의 JSONL 기록 `/tmp/anf-e2e-pool-r2-run1.jsonl`(WSL)에서 뽑았다.

### [PASS] AC-06 잘못된 요청 거절, 작업·상태 변화 없음 (계약)
- 기준: 잘못된 이름은 `400 InvalidResourceName`이다. 크기 규칙 위반, 생성 필수값 누락, 서비스 수준 오류, 미룬 기능, 모르는 속성, PATCH의 `serviceLevel`은 `400 InvalidRequestContent`다. 다른 `location`의 PUT은 `409 InvalidResourceLocation`이다. 모두 작업도 상태 변화도 남기지 않는다.
- 실행: `test_capacity_pool_live.py::test_ac06_rejected_requests_create_no_operation_and_change_nothing`. 매개변수 18개가 두 번의 실행에서 모두 통과했다.
- 경우마다 확인한 것 (1회차와 같다):
  - 응답 코드와 `error.code`, 그리고 `error.message`가 비어 있지 않음. 미룬 기능 다섯 경우는 메시지 전체가 기대값과 같음
  - `Azure-AsyncOperation`·`Location` 헤더가 없다
  - 요청 전후의 두 계정 풀 목록(id·location·tags·properties 전체)이 같다
  - 기존 풀 `e2e-p06`의 GET 본문이 그대로다
  - 이름이 올바른 새 풀이면 그 이름의 GET이 `404`다
  - 보조 증거: 상태 저장소의 `operations` 행 목록과 `resources` 행 목록이 요청 전후에 같다
- 출력:

  | 요청 | 응답 | error.code / message |
  | --- | --- | --- |
  | PUT `pool:-p` | 400 | `InvalidResourceName` / "The capacity pool name '-p' is invalid. It must start with an alphanumeric character, contain only alphanumerics, '-' or '_', and be 1 to 64 characters long." |
  | PUT `pool:a×65` | 400 | `InvalidResourceName` / 같은 형식 |
  | PUT `pool:a.b` | 400 | `InvalidResourceName` / 같은 형식 |
  | PUT `size: 549755813888` | 400 | `InvalidRequestContent` / "The 'properties.size' property must be a whole number of bytes in 1 TiB (1099511627776) chunks, from 1 TiB to 2048 TiB." |
  | PUT `size: 0` | 400 | `InvalidRequestContent` / 같은 문구 |
  | PUT `size: 2252899325313024` (2,049 TiB) | 400 | `InvalidRequestContent` / 같은 문구 |
  | 생성 PUT, `size` 없음 | 400 | `InvalidRequestContent` / "The 'properties.size' property is required." |
  | 생성 PUT, `serviceLevel` 없음 | 400 | `InvalidRequestContent` / "The 'properties.serviceLevel' property is required." |
  | PUT `serviceLevel: Gold` | 400 | `InvalidRequestContent` / "The 'properties.serviceLevel' property must be one of 'Standard', 'Premium', 'Ultra'." |
  | PUT `serviceLevel: Flexible` | 400 | `InvalidRequestContent` / **"The value 'Flexible' of 'properties.serviceLevel' is not supported by this ANF clone."** |
  | PUT `serviceLevel: StandardZRS` (이번에 추가) | 400 | `InvalidRequestContent` / **"The value 'StandardZRS' of 'properties.serviceLevel' is not supported by this ANF clone."** |
  | PUT `coolAccess: true` | 400 | `InvalidRequestContent` / "The property 'properties.coolAccess' is not supported by this ANF clone." (1회차와 같다) |
  | PUT `encryptionType: Double` | 400 | `InvalidRequestContent` / **"The value 'Double' of 'properties.encryptionType' is not supported by this ANF clone."** |
  | PUT `customThroughputMibps: 100` | 400 | `InvalidRequestContent` / "The property 'properties.customThroughputMibps' is not supported by this ANF clone." (1회차와 같다) |
  | PUT 최상위 `unknownProp` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'unknownProp'." |
  | PUT `properties.unknownProp` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'properties.unknownProp'." |
  | PATCH 기존 `e2e-p06` `{"properties":{"serviceLevel":"Ultra"}}` | 400 | `InvalidRequestContent` / "Value received for an unknown property 'properties.serviceLevel'." |
  | 기존 `e2e-p06`(westus2)에 PUT `{"location":"eastus","tags":{"changed":"1"}}` | 409 | `InvalidResourceLocation` / "The resource 'e2e-p06' already exists in location 'westus2' in resource group 'rg-e2e'. A resource with the same name cannot be created in location 'eastus'. Please select a new resource name." |

  - 굵게 표시한 세 메시지가 이번 수정의 결과다. 1회차의 겹친 따옴표(`'properties.serviceLevel 'Flexible''`)는 없어졌다. 2회 실행 기록에서도 "The value …" 메시지는 위 세 가지가 한 번씩만 나왔다.
  - 나머지 메시지는 1회차와 글자 단위로 같다.
  - 새 이름의 GET은 모두 `404 ResourceNotFound`였다. 예: `pool:e2e-p06-flex`, `pool:e2e-p06-zrs`, `pool:e2e-p06-dbl`.
  - 마지막 경우 뒤의 GET `e2e-p06`도 `location: westus2`, `tags: {"keep":"1"}`, `Succeeded`로 그대로였다.

## e2e 회귀 결과

| 실행 | 범위 | 결과 | 시간 |
| --- | --- | --- | --- |
| 1 (03:22:27Z~, `-v`) | `backend/tests/e2e` 전체 | **63 passed, 0 failed, 0 skipped** | 111.76 s |
| 2 (03:24:44Z~, `-q`) | 같다 | **63 passed, 0 failed, 0 skipped** | 109.27 s |

모듈별 (두 실행 모두 같다):

| 모듈 | 테스트 수 | 결과 | 덮는 기준 |
| --- | --- | --- | --- |
| `test_capacity_pool_live.py` | 30 (1회차 29 + StandardZRS 1) | 모두 passed | 풀 AC-01~AC-09, 추가 관찰 2건 |
| `test_capacity_pool_lro_faults_live.py` | 9 | 모두 passed | 풀 AC-07(Deleting), AC-10~AC-12, 결함 키 기동 검사, request-id |
| `test_netapp_account_live.py` | 16 | 모두 passed | 계정 AC-01~AC-07, AC-13 |
| `test_netapp_account_lro_faults_live.py` | 8 | 모두 passed | 계정 AC-08~AC-11, AC-13, §6.3 기동 검사(`netAppAccounts/patch` 거절 포함) |

### 계정 e2e 회귀
- 계정 두 모듈 24개가 새 코드(`a461dbaf…`)로 두 번 모두 통과했다. 계정 2회차 보고서(`_workspace/netapp-account/04_verifier_report_r2.md`, 대상 `f58df82d…`)의 판정을 바꿀 결과는 없다.
- 계정 AC-06의 `identity` 메시지는 계정 2회차와 같은 "The property 'identity' is not supported by this ANF clone."이다. 계정은 바뀐 줄을 지나지 않는다(`accounts.py`는 `capacity_pools.py`를 import하지 않는다).
- 계정 AC-12(데이터 플레인 불변)는 셸 비교 항목이라 다시 돌리지 않았다. 계정 2회차 결과를 유지한다.

## 측정값

| 항목 | 값 | 반복 |
| --- | --- | --- |
| AC-06 거절 응답 시간 (JSONL `elapsed_ms`, 풀 모듈만) | 1회 실행 0.9~3.9 ms, 2회 실행 0.9~2.4 ms | 실행마다 18건 |
| e2e 폴더 전체 실행 시간 | 111.76 s, 109.27 s | 2회 |

## 추가 관찰 (판정에 넣지 않음)

1. **8080 포트의 무관한 anf-api.**
   - 상태: pid 8387이 03:16:50Z부터 `127.0.0.1:8080`에 떠 있다. 1회차 검증이 끝난 03:12:23Z 뒤에 시작됐다.
   - 설정: `ANF_API_DB=/home/mkimhome1/.local/state/anf-clone/manual-test.db`, `ANF_FAULT_INJECTION={"netAppAccounts/create":{"delaySeconds":5},"netAppAccounts/delete":{"delaySeconds":5},"capacityPools/create":{"delaySeconds":5},"capacityPools/patch":{"delaySeconds":5},"capacityPools/delete":{"delaySeconds":5}}`.
   - 이 검증이 띄운 프로세스가 아니어서 그대로 두었다. 끝난 시점에도 떠 있다.
   - 이 프로세스가 어떤 버전의 코드를 import했는지는 확인하지 않았다. 시작 시각으로 보면 이번 수정 전 코드일 수 있다.
   - 수동 확인용이라면 리더나 사용자가 정리하면 된다.
2. 1회차 추가 관찰 2(WSL 시계)는 이번 회차와 관계없다. 이번에 판정한 AC-06에는 시간 조건이 없다.
3. 정리:
   - 이번 회차의 서버 프로세스는 모두 멈췄고 8081은 비어 있다.
   - pytest 임시 디렉터리(`/tmp/anf-e2e-r2-run1`, `/tmp/anf-e2e-r2-run2`)는 지웠다.
   - 요청·응답 기록 `/tmp/anf-e2e-pool-r2-run1.jsonl`, `/tmp/anf-e2e-pool-r2-run2.jsonl`(WSL)은 증거로 남겼다.
