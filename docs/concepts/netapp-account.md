# NetApp 계정과 공통 비동기 작업(LRO) 계층

> NetApp 계정(NetApp account)은 데이터 플레인에 아무것도 만들지 않는 관리용 컨테이너다. 이 기능의 진짜 내용은 계정이 아니라, 이후 모든 리소스가 재사용할 ARM 장기 실행 작업(long-running operation, LRO) 계층이다. "저장한 뒤 응답하고, 같은 프로세스의 워커가 나머지를 끝내고, 재시작해도 이어서 끝낸다"가 핵심이다.

FR-01(공통 비동기 작업)은 계정 사이클에 포함돼 있고(PRD §8), 이 문서가 FR-01과 FR-02(NetApp 계정)를 함께 다룬다.

근거 표시는 브리프를 따른다. 이 문서에서 쓰는 표시의 뜻은 다음과 같다.

| 표시 | 뜻 |
| --- | --- |
| [스펙] | Azure REST API 스펙(OpenAPI/TypeSpec)에 적혀 있다 |
| [문서] | Microsoft Learn 문서 또는 ARM RPC 사본에 적혀 있다. 단, ARM RPC 사본은 2022년 공개 포크라 현재 계약과 다를 수 있다 |
| [녹화] | Azure SDK 테스트 세션 녹화에서 실서비스 응답으로 관찰했다. 문서로 보장된 동작은 아니다 |
| [추론] | 근거에서 조사자가 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |

---

## 1. ANF에서는

### 1.1 계정이란

- NetApp 계정은 리전 하나에 묶인 관리용 묶음이며, ARM 추적 리소스(tracked resource) `Microsoft.NetApp/netAppAccounts`다 [문서][스펙]. 용량 풀(capacity pool), 스냅샷 정책, 백업 정책, 백업 볼트, 볼륨 그룹의 부모다 [스펙]. 볼륨은 `계정 → 용량 풀 → 볼륨` 순서로 중첩된다 [스펙].
- 필수 속성은 `location` 하나다. `location`은 생성 뒤 바꿀 수 없다 [스펙]. 계정 이름은 `^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,127}$` 패턴이다 [스펙].
- 계정을 만들거나 지워도 클라이언트가 마운트로 관찰할 수 있는 변화는 없다 [추론] (계정은 풀을 묶는 단위이고 볼륨은 풀 아래에만 생기기 때문).

### 1.2 작업별 응답 코드: 왜 그렇게 나오나

스펙은 PUT, PATCH, DELETE를 모두 LRO로 정의한다 [스펙]. 응답 코드는 작업마다 다르고, 이것이 이 기능에서 가장 헷갈리는 부분이다.

| 작업 | 응답 | 헤더 | 근거 |
| --- | --- | --- | --- |
| PUT (새 계정) | `201`, 본문 `provisioningState: Creating` | `Azure-AsyncOperation`만 | [스펙] 스펙은 201에 `Azure-AsyncOperation`을 정의하고, 실서비스도 `Location` 없이 이것만 보냈다 [녹화] |
| PUT (기존 계정) | `200`, 본문 `Updating` | `Azure-AsyncOperation` | 스펙은 PUT 200에 헤더를 정의하지 않는다 [스펙]. 그런데 실서비스는 200에 `Updating`과 헤더를 보냈다 [녹화]. 즉 200이어도 아직 끝나지 않았을 수 있다 |
| PATCH (tags만) | `200` 동기, 본문 `Succeeded`, 추적 헤더 없음 | 없음 | 스펙은 200과 202를 모두 허용한다 [스펙]. 계정의 tags PATCH는 모두 200 동기였다 [녹화]. 풀 PATCH는 202 + `Patching`이었다 [녹화]. 즉 PATCH의 동기/비동기는 리소스마다 다르다 |
| DELETE (있음) | `202`, 본문 없음 | `Location`과 `Azure-AsyncOperation` 둘 다 | 스펙은 `Location`만 정의하지만 [스펙], 실서비스는 둘 다 붙였다 [녹화] |
| DELETE (없음) | `204` | 없음 | [스펙] ("Resource does not exist") |
| DELETE (자식 풀이 남음) | 즉시 `409 CannotDeleteResource` | 없음 | [추론] 녹화에서 `x-ms-failure-cause: gateway` 헤더가 있어 ANF가 아니라 ARM 게이트웨이가 거절한 것으로 보인다 |

`200`, `201`, `202`, `204`, `409`를 한 문장으로 정리하면 다음과 같다. 리소스가 새로 생기는 PUT은 "리소스는 이미 보이지만 아직 만드는 중"이라 201이다. 이미 있는 리소스의 갱신은 "이미 있으니 200"이다. 삭제는 리소스가 사라지는 일이라 본문이 없는 202로 수락만 알린다. 없는 것을 지우면 할 일이 없으므로 204다. 409는 요청을 받아들일 수 없는 상태 충돌이다.

### 1.3 ARM LRO의 두 추적 방식

두 방식 모두 [문서](ARM RPC 사본, Learn)에서 가져온 규칙이다.

**(a) `Azure-AsyncOperation` URL을 GET**
- 진행 중이든 종결이든 항상 `200`이다. 진행 여부는 본문의 `status`가 알려 준다. 4xx·5xx는 "상태를 읽는 일"이 실패했다는 뜻이지 작업 실패가 아니다 [문서].
- `status`의 종결 값은 `Succeeded`, `Failed`, `Canceled`뿐이다. 그 밖의 값은 리소스 공급자(RP)가 정하며 모두 "진행 중"이다 [문서].
- `Failed`면 `error: {code, message}`가 필수다 [문서].
- ANF는 진행 중 `status`로 `InProgress`가 아니라 작업별 값(`Creating`, `Deleting`, `Patching`, `Updating` …)을 썼다. `InProgress`는 ANF 녹화에서 한 번도 안 나왔다 [녹화]. 진행 중 `percentComplete`는 `0.0`, 성공은 `100.0`이었고 중간 값은 보지 못했다 [녹화].

**(b) `Location` URL을 GET**
- 진행 중이면 본문 없는 `202`(`Location` 헤더를 다시 붙임)다 [문서].
- 끝나면 "작업이 동기로 실행됐다면 돌려줬을 응답과 정확히 같은 응답"을 돌려준다 [문서]. 그래서 DELETE는 `200`/`204`, PATCH는 동기 성공 응답이다 [문서].
- 이 규칙을 실패에 적용하면 해당 오류 코드와 ErrorResponse 본문이 된다는 것은 [추론]이다. 실패한 작업의 `Location` 응답은 문서에 명시돼 있지 않다 [미확인].
- **ANF가 실제로 이렇게 동작하는지는 확인하지 못했다.** 녹화에서 SDK는 `Azure-AsyncOperation`이 있으면 그것으로 폴링했고, `Location`은 POST 액션이 성공한 뒤 최종 결과를 받을 때 한 번만 GET했다(200 + 리소스 본문) [녹화]. 진행 중 `Location` GET, DELETE·PATCH 뒤의 `Location` GET은 녹화 176개에 0건이다 [미확인].

**URL 위치.** 작업 상태 URL은 `/subscriptions/{sub}/providers/Microsoft.NetApp/locations/{loc}/operationResults/{opId}`처럼 구독·리전 범위다. 리소스 아래에 두면 DELETE가 끝난 뒤 조회할 수 없기 때문이다 [문서]. ANF도 같은 모양을 쓴다 [녹화].

### 1.4 그 밖의 동작

- **계정 작업은 아주 빨리 끝난다.** 계정 생성은 startTime부터 endTime까지 약 70ms였다 [녹화]. 실제 일이 없다는 증거로 읽을 수 있지만 그것은 [추론]이다.
- **`Retry-After`는 Microsoft.NetApp 응답에 한 번도 없었다.** 초기 응답과 상태 조회 모두 녹화 176개에서 0건이다 [녹화]. 같은 녹화의 Microsoft.Network 응답은 붙였다 [녹화]. 반면 RPC 사본은 `Location` 패턴에서 10초~10분 범위의 값을 권한다 [문서]. 즉 ANF의 관행과 RPC 권고가 다르다.
- **진행 중 충돌.** ANF 오류 문서에는 "Volume is being created and cannot be deleted at the moment" 같은 메시지가 있다 [문서]. 이 문구로 보면 ANF는 충돌하는 요청을 대기열에 넣지 않고 즉시 거절한다 [추론]. 그러나 그 메시지의 HTTP 코드와 `error.code`는 문서에도 녹화에도 없다 [미확인].
- **실패한 작업의 모습.** 작업 상태가 HTTP 200으로 오면서 본문 `status: "Failed"`, `percentComplete: 100.0`, `error.code`는 `BadRequest` 같은 일반 코드이고 구체 코드는 `error.details[]`에 있었다 [녹화]. 단, 녹화된 실패는 모두 볼륨의 POST 액션이었다. PUT·PATCH·DELETE가 비동기로 실패한 녹화는 없고, 실패 뒤 리소스 `provisioningState`가 `Failed`가 되는지도 확인하지 못했다 [미확인].
- **api-version 오류.** api-version을 빼면 `400 MissingApiVersionParameter`가 온다는 사용자 보고가 있다 [미확인: 포럼 단서뿐]. 지원하지 않는 api-version의 오류 코드는 1차 출처에서 확인하지 못했다 [미확인]. 이 거절은 요청이 ANF에 닿기 전에 ARM이 하는 것으로 보인다 [추론].
- **리소스 그룹 전체 삭제**는 다른 경로다. ARM이 중첩 리소스를 먼저 지운다 [문서].

---

## 2. ONTAP에서는

솔직하게 말하면, 이 기능에서 "ONTAP의 무엇에 해당하는가"에 대한 답은 **"1:1로 대응하는 객체를 공개 자료에서 찾지 못했다"**이다 [미확인].

| 질문 | 근거 수준에 맞는 답 |
| --- | --- |
| ANF 계정에 대응하는 ONTAP 객체는? | 공개 자료에 없다 [미확인]. 가장 가까운 후보는 SVM(Storage VM, vserver)이다. 그러나 이것은 닮았다는 [추론]이지 대응 관계가 아니다 |
| SVM이란? | 볼륨, LIF, 프로토콜 설정을 담는 논리 스토리지 서버이자 멀티테넌시 단위다. 단, 이 설명은 docs.netapp.com이 403이라 원문을 못 읽고 검색 요약으로 가져온 것이다 [문서, 원문 미확인] |
| 닮은 점 | 계정의 AD 연결 1개는 SVM의 CIFS 서버(AD에 가입하면 컴퓨터 계정이 생김)와 구조가 닮았다 [추론]. `nfsV4IDDomain`은 ONTAP의 `vserver nfs modify -v4-id-domain`과 닮았다 [추론]. 자식(볼륨)이 있으면 SVM을 지울 수 없다는 점도 닮았다 [추론, ONTAP 쪽은 원문 미확인] |
| 다른 점 | `nfsV4IDDomain`의 적용 범위가 계정이 아니라 구독·리전이다 [문서][스펙]. 과거의 Shared AD도 구독·리전 단위였고 [문서], CMK 전환은 볼륨이 있는 VNet마다 해야 한다 [문서]. 이 단서로 보면 백엔드의 ONTAP 테넌시(SVM)는 계정이 아니라 구독·리전·VNet 기준으로 나뉘는 것 같다 [추론] |
| 백엔드에 SVM이 있기는 한가? | 있다. CMK 문서가 위임 서브넷 NSG는 "NetApp's storage VM"에서 오는 트래픽을 허용해야 한다고 쓴다 [문서]. 하지만 이것이 계정과 몇 대 몇인지는 공개되지 않았다 [미확인] |

그래서 이 프로젝트의 결정은 이렇다. **계정을 SVM으로 구현하지 않았다.** 근거 없는 대응을 코드로 굳히면 면접에서 "ANF 계정은 SVM이다"라고 사실처럼 말하게 되기 때문이다. 면접에서는 "공개 자료로는 대응 관계를 확인할 수 없고, 단서로 보면 SVM이 계정 단위가 아닌 것 같아서 만들지 않았다"라고 말하면 된다.

참고로, 이 기능의 핵심인 LRO(Azure-AsyncOperation, Location)는 ARM의 규약이지 ONTAP 개념이 아니다. ONTAP 쪽의 비동기 작업 메커니즘은 이번 브리프에 없어서 이 문서에 쓰지 않았다.

---

## 3. 이 프로젝트에서는

### 구조

```
  클라이언트 (curl, SDK, 검증 스크립트)
        |  HTTP  (api-version=2026-08-01)
        v
  +-------------------------------- anf-api 프로세스 (uvicorn 워커 1개) --------------------+
  |  arm_app.py   ARM 앞단 역할: api-version 검사, 이름 검사, 상관 ID, 오류 형식, 라우트    |
  |      |                                                                                    |
  |      v                                                                                    |
  |  accounts.py  본문 규칙, PUT/PATCH/DELETE 흐름 (오류 함수는 arm_rules.py에서 가져옴)     |
  |      |   (한 트랜잭션: 리소스 상태 변경 + 작업 행 생성)                                  |
  |      v                                                                                    |
  |  state_store.py  SQLite (resources, operations, 부분 유니크 인덱스, 자식 검사)  <-+       |
  |                                                                            |              |
  |  lro.py  asyncio 워커: 진행 중 작업을 찾아 처리기 실행 -> 결과를 한 트랜잭션으로 반영     |
  +-------------------------------------------------------------------------------------------+
                         (storage agent 호출 없음: 계정은 컨트롤 플레인 전용)
```

요청 하나의 생명 주기는 이렇다.
1. 요청이 오면 `arm_app.py`가 api-version과 이름을 검사한다.
2. `accounts.py`가 한 트랜잭션 안에서 리소스를 진행 중 상태(`Creating`/`Updating`/`Deleting`)로 바꾸고 작업 행을 만든다.
3. 커밋된 뒤에야 `201/200/202`로 응답한다. 이것이 "저장한 뒤 응답한다"이다.
4. 워커가 작업 행을 보고 처리기를 실행한 뒤, 리소스와 작업을 종결 상태로 한 트랜잭션에 바꾼다.
5. 클라이언트는 응답 헤더의 작업 상태 URL을 폴링한다.

### 코드 따라가기

> 계정과 용량 풀이 함께 쓰는 코드(본문 오류 함수, 자식 검사, 결함 키 만들기, Location 최종 본문 고르기)는 용량 풀 사이클에서 공통 파일(`arm_rules.py`, `state_store.py`, `lro.py`, `arm_app.py`)로 옮겼다. 계정의 외부 동작은 바뀌지 않았고 계정 검증은 2회차에서 다시 PASS했다(§5). 아래 줄 번호는 옮긴 뒤의 코드 기준이다. 풀 기능 자체는 이 문서의 범위가 아니다.

#### (1) 앱 조립과 lifespan의 워커 — `arm_app.py`

- `create_app()` (`arm_app.py:69`)이 상태 저장소, 처리기 표(`{**accounts.HANDLERS, **pools.HANDLERS}`, `arm_app.py:74`), 결함 주입 설정, 워커를 만든다. 결함 주입 값이 잘못되면 `ValueError`로 서버가 뜨지 않는다(`arm_app.py:75`, 파싱은 `lro.py:33`).
- 워커는 FastAPI lifespan이 띄우는 asyncio 태스크다 (`arm_app.py:80-86`). 별도 프로세스나 큐 서비스가 아니다 (ADR D-09). 종료할 때 태스크를 취소하고, 취소된 작업은 종결되지 않은 채 남아 다음 시작 때 다시 실행된다.
- 서버는 uvicorn 워커 1개로 띄운다. 프로세스 안의 워커라는 전제가 "프로세스가 하나"이기 때문이다 (설계 결정 11).

#### (2) 상관 ID와 오류 형식 — `arm_app.py:92-104`

- 미들웨어가 `x-ms-correlation-request-id`를 받은 값 그대로 이어 쓰고, 없으면 새 UUID를 만든다. 응답마다 새 `x-ms-request-id`를 붙인다 (`arm_app.py:93-100`). 상관 ID는 작업 행에도 저장된다 (`state_store.py:214-232`).
- `ArmError`(`arm_rules.py:22`)를 던지면 핸들러가 `{"error": {"code", "message"}}`로 바꾼다 (`arm_app.py:102-104`). 코드 어디서든 `raise ArmError(...)`만 하면 ARM 형식 오류가 된다.

#### (3) PUT — "저장한 뒤 응답한다" — `accounts.py:111-136`, `arm_app.py:106-116`

- `store.transaction()` 안에서 계정을 찾는다 (`accounts.py:117-118`).
  - 없으면: `Creating` 상태의 리소스를 만들고 `CREATE` 작업을 만든다 → `201` (`accounts.py:119-127`).
  - 있으면: `location`이 다르면 `409 InvalidResourceLocation` (`accounts.py:128-129`, 오류 본체는 `arm_rules.py`의 `location_conflict`). 같으면 이전 tags·properties를 `previous`로 보관하고(실패 시 되돌리기용), `Updating`으로 바꾸고 `UPDATE` 작업을 만든다 → `200` (`accounts.py:130-136`).
- 트랜잭션은 시작할 때 쓰기 잠금을 잡는다(`BEGIN IMMEDIATE`, `state_store.py:256-266`, 잠금은 260). 확인(존재 여부, 진행 중 작업)과 쓰기 사이에 다른 요청이 끼어들 틈이 없다.
- 라우트는 커밋이 끝난 뒤 `worker.notify()`를 부르고 `Azure-AsyncOperation` 헤더를 달아 응답한다 (`arm_app.py:113-116`). 응답이 나갔다는 것은 리소스와 작업이 이미 디스크에 있다는 뜻이다. 응답 직후 프로세스가 죽어도 작업이 남는다.
- tags는 요청의 맵 전체로 바꾼다(PUT도 PATCH도). `tags`가 없는 PATCH는 그대로 둔다 (`accounts.py:63-76`, tags 검사 본체는 `arm_rules.py:107`의 `check_tags`, 녹화로 확인한 동작 [녹화]).

#### (4) PATCH — 동기 200 — `accounts.py:139-152`

- tags만 바꾸고 `provisioningState`는 건드리지 않는다. 작업을 만들지 않는다. 단, 진행 중 작업이 있으면 `ensure_no_active_operation`이 409로 막는다 (`accounts.py:148`).
- `Failed` 계정을 복구하는 방법은 PATCH가 아니라 PUT을 다시 보내는 것이다 (설계 결정 3).

#### (5) DELETE — 자식 검사가 같은 트랜잭션 안에 있다 — `accounts.py:155-168`

- 없으면 `None` → 라우트가 `204`를 준다 (`arm_app.py:139-140`).
- 계정 코드는 `tx.ensure_no_children(rid)` 한 줄만 부른다 (`accounts.py:164`). 검사 본체는 공통 코드인 `Tx.ensure_no_children`(`state_store.py:152-164`)에 있고, `child_ids`(`state_store.py:139-143`)로 이 리소스를 부모로 가진 리소스를 찾는다. 있으면 `409 CannotDeleteResource`이고, 메시지에 자식 ID(`Microsoft.NetApp/netAppAccounts/{a}/capacityPools/{p}` 형식)를 넣는다 (녹화 R4의 형식). 자식의 상태와는 무관하게 거절한다. 이 검사를 용량 풀 사이클에서 계정 코드 밖으로 옮긴 것은 풀 DELETE도 같은 규칙을 쓰기 때문이다.
- 없으면 `Deleting`으로 바꾸고 `DELETE` 작업을 만든다 (`accounts.py:165-168`). 라우트는 본문 없는 `202`에 `Location`과 `Azure-AsyncOperation`을 둘 다 붙인다 (`arm_app.py:141-143`, 헤더는 `_tracking_headers`, `arm_app.py:63-66`).
- **이 409는 계정 사이클에서는 계약 테스트로만 확인했지만, 지금은 실환경에서 확인됐다.** 용량 풀 사이클의 검증 AC-09가 실제 uvicorn 프로세스에서 풀이 남은 계정의 DELETE → `409 CannotDeleteResource`(작업 행이 새로 생기지 않음), 풀을 먼저 지운 뒤 DELETE → `202` → `Succeeded`를 보였다 (`_workspace/capacity-pool/04_verifier_report.md` AC-09, PASS). 계정 2회차 보고서도 이 항목을 이월 기준으로 그대로 인용한다 (설계 결정 8).

#### (6) 워커 — `lro.py:68-149`

- `start_pending()`이 종결되지 않은 작업 중 아직 실행 중이 아닌 것을 작업마다 asyncio 태스크로 띄운다 (`lro.py:83-94`). 한 작업이 지연돼도 다른 작업이 막히지 않는다.
- `run()`은 새 작업 알림(`notify`)이나 1초마다 깨어나 위를 반복한다 (`lro.py:100-113`). 알림을 놓쳐도 1초 안에 다시 훑는다.
- `_process()`는 (a) 결함 주입이 있으면 지연하고, (b) `fail`이면 처리기 없이 `Failed`로 끝내며, (c) 아니면 `(리소스 종류, action)`으로 처리기를 찾아 실행한다. 처리기가 예외를 던지면 `InternalServerError`로 끝낸다 (`lro.py:115-135`).
- `_finish()`는 리소스와 작업을 한 트랜잭션으로 갱신한다 (`lro.py:137-149`).
  - 성공 + DELETE → 리소스 행 삭제.
  - 성공 → `Succeeded`.
  - 실패 + UPDATE 또는 PATCH → `previous`로 tags·properties를 되돌리고 `Failed`. 계정에는 PATCH 작업이 없어 UPDATE만 해당한다. PATCH 쪽은 용량 풀 사이클에서 공통 코드에 들어왔다.
  - 실패 + 그 밖 → `Failed`. 실패한 DELETE는 리소스가 `Failed`로 남는다.
  - 작업과 리소스의 상태가 따로 놀지 않게 같은 트랜잭션에 넣는다.
- 계정의 처리기는 아무것도 하지 않는다 (`accounts.py:171-175`, `_no_storage_work`). 상태 전이만 한다. 아무것도 하지 않으므로 몇 번을 다시 실행해도 결과가 같다(멱등).

#### (7) 재시작하면 이어서 끝낸다 — 멱등성

- 서버가 시작해 워커가 처음 훑을 때 `active_operations()`가 종결되지 않은 작업을 모두 돌려준다 (`state_store.py:191-196`, `lro.py:86`). 즉 죽기 전에 진행 중이던 작업이 처음부터 다시 실행된다.
- 이것이 안전한 이유는 처리기가 멱등이기 때문이다. 계정 처리기는 할 일이 없어서 당연히 멱등이다. **실제 자원을 만드는 볼륨부터는 이 가정이 깨진다.** 볼륨 설계에서 ADR §6.4의 "단계별 복구"를 정해야 한다.

#### (8) 리소스 하나에 진행 중 작업 하나 — 두 겹의 방어

- 1차: `Tx.ensure_no_active_operation`이 진행 중 작업이 있으면 `409 AnotherOperationInProgress`로 즉시 거절한다 (`state_store.py:205-212`). 대기열에 넣지 않는다. 작업 생성(`create_operation`, `state_store.py:214-218`)과 동기 PATCH가 같은 검사를 쓴다.
- 2차: 부분 유니크 인덱스 `operations_one_active_per_resource`가 `resource_id`에 걸려 있고, 조건은 `status NOT IN ('Succeeded','Failed','Canceled')`다 (`state_store.py:52-53`). 종결된 작업은 여러 개 쌓일 수 있지만 진행 중 작업은 리소스당 하나만 DB가 허용한다. 1차 검사가 빠져도 DB가 막는 안전장치다 (설계 "구현 중 변경").

#### (9) 작업 상태 URL 하나, 두 방식 — `arm_app.py:207-234`, `lro.py:152-166`

같은 경로 `…/locations/{location}/operationResults/{operationId}`가 쿼리 `operationResultResponseType=Location` 유무로 두 방식이 된다.

| 조건 | 응답 | 코드 위치 |
| --- | --- | --- |
| 쿼리 없음 (`Azure-AsyncOperation`) | 항상 `200` + `operation_status_body` | `arm_app.py:218-220` |
| `Location`, 진행 중 | 본문 없는 `202` + `Location` 헤더 | `arm_app.py:222-223` |
| `Location`, 실패 | 저장된 `httpStatus`와 ErrorResponse | `arm_app.py:224-227` |
| `Location`, 성공 + DELETE | `204` | `arm_app.py:228-229` |
| `Location`, 성공 + CREATE/UPDATE | `200` + 리소스 본문 | `arm_app.py:230-234` |
| 작업 없음 / 구독·location 다름 | `404 ResourceNotFound` | `arm_app.py:214-217` |

마지막 두 줄의 리소스 본문은 리소스 종류별 함수 표 `_BODIES`(`arm_app.py:43`)에서 고른다. 계정 때는 계정 본문 하나뿐이었고, 용량 풀 사이클에서 종류별로 고르도록 바뀌었다. 계정의 응답은 같다.

상태 본문은 `{id, name, status, startTime, percentComplete, properties: {resourceName, action}, endTime?, error?}`다 (`lro.py:152-166`). 진행 중 `percentComplete`는 `0.0`, 종결은 `100.0`이다. 진행 중에도 `properties`를 넣는데, 이는 ANF 녹화를 따른 것이고 RPC 사본의 "properties는 Succeeded일 때만" 권고와는 다르다 [녹화 vs 문서].

#### (10) 결함 주입 — `lro.py:23-61`, `lro.py:115-124`

- 서버를 띄울 때 환경 변수 `ANF_FAULT_INJECTION`에 JSON을 넣는다. 예: `{"netAppAccounts/create": {"delaySeconds": 5}, "netAppAccounts/delete": {"fail": true}}`. 기본은 꺼짐이고, 켜져 있으면 시작할 때 경고 로그를 남긴다 (`arm_app.py:76-77`).
- 키는 `{리소스 종류}/{작업}`, 값은 `delaySeconds`와 `fail`뿐이다. 받을 수 있는 키는 고정 목록이 아니라 등록된 처리기의 (리소스 종류, 작업)에서 만든다 (`parse_faults(text, handler_keys)`, `lro.py:33-51`). 그래서 계정은 `netAppAccounts/{create|update|delete}`만 받는다. 계정에는 PATCH 작업이 없어(PATCH가 동기라 작업 행을 만들지 않는다) `netAppAccounts/patch`는 처리기가 없으므로 서버 시작 때 거절된다(2회차에서 실환경 확인). 모르는 키나 값이 있으면 서버가 뜨지 않는다.
- **왜 필요했나.** 계정 작업은 실제 일이 없어서 밀리초 안에 끝난다 (클론 측정 7~10ms, 실서비스도 약 70ms [녹화]). 그러면 "진행 중" 상태, 실패, 재시작 복구를 실환경에서 볼 수가 없다. 지연을 넣어야 `Creating`을 폴링으로 잡을 수 있고, 지연 중에 SIGKILL을 보내야 복구를 재현할 수 있다.
- **한계.** 클론 전용 장치다(실제 ANF에는 없다). 실패는 처리기 앞에서 일어난다. 즉 "일을 반쯤 하다 죽는" 경우는 재현하지 못한다. 지연은 처리기 앞에서 한 번 자는 것이라, 재시작하면 지연이 처음부터 다시 시작된다(검증에서 약 4.8초). `percentComplete`의 중간 값도 만들지 못한다. 계정의 처리기가 멱등이라 재시작 복구가 쉽게 통과한 것이고, 볼륨의 부분 실패를 검증한 것은 아니다.

### 설계 결정

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | 계정은 storage agent에 아무것도 만들지 않는다 | 계정마다 SVM 생성 | 1:1 대응의 공개 근거가 없고, 단서로는 SVM이 구독·리전·VNet 기준으로 나뉘는 것 같다 [추론]. 근거 없는 대응을 코드로 굳히지 않는다 |
| 2 | 기존 계정 PUT은 비동기 `200` + `Updating` + `Azure-AsyncOperation` | 스펙대로 동기 `200` + `Succeeded` | 실서비스가 그렇게 응답했다 [녹화]. "200이어도 안 끝났을 수 있다"를 보여 준다 |
| 3 | PATCH(tags)는 동기 `200`, `provisioningState` 불변 | 비동기 `202` + `Patching` | 계정 PATCH 녹화는 모두 동기 200이었다 [녹화]. 풀은 202였으므로 풀 설계에서 다시 정한다 |
| 4 | 진행 중 `status`는 작업별 값(`Creating`/`Updating`/`Deleting`) | ARM 예시의 `InProgress` | ANF 녹화에 `InProgress`가 없다 [녹화] |
| 5 | `Retry-After`를 보내지 않는다. 클라이언트는 1초 간격, 30초 제한 | RPC 범위(10초~10분)로 보내기 | ANF도 0건 [녹화]. 10초 이상이면 검증이 느려진다 |
| 6 | 진행 중 충돌은 `409 AnotherOperationInProgress`로 즉시 거절 | 대기열에 넣기, `Conflict` 코드 | ANF 문구가 "기다렸다가 재시도"라서 거절 방식이 맞다 [추론]. 코드값은 ANF에서 확인 못 했다 [미확인]. `AnotherOperationInProgress`는 ARM 공통 오류 목록에 있다. 사용자가 기본안 `Conflict` 대신 이것을 골랐다 |
| 7 | 결함 주입(지연, 강제 실패)을 둔다 | 단위·계약 테스트로만 검증 | 그러면 실환경 기준이 볼륨 사이클까지 UNVERIFIED로 남고 계정이 `partial`이 된다 |
| 8 | 자식 검사는 일반 규칙으로 지금 구현, 실환경 검증은 풀 사이클로 이월 | 이번에 수락 기준으로 남기기 | 풀이 done이 될 때까지 계정이 `partial`이 되기 때문이다. **결과:** 용량 풀 사이클 AC-09에서 실환경 PASS로 이월이 닫혔다. 검사 코드는 그 사이클에서 `Tx.ensure_no_children`(`state_store.py:152`)으로 옮겨졌다 |
| 9 | 리소스 ID를 대소문자 구분 없이 찾는다 (`COLLATE NOCASE`), 이름은 처음 받은 그대로 보존 | 대소문자 구분 | ARM은 이름을 대소문자 구분 없이 다룬다 [문서, 이번 조사에서 원문 재확인은 안 함] |
| 10 | 상태 저장소 파일 위치는 `ANF_API_DB`, 기본값 WSL ext4 | 저장소(`/mnt/c`, 9P) 안 | 9P에서는 SQLite 파일 잠금을 믿을 수 없다 [추론] |
| 11 | uvicorn 워커 1개, `127.0.0.1:8080` | 워커 여러 개 | 프로세스 안 워커(D-09)는 프로세스가 하나라는 전제다 |

---

## 4. 실제 ANF와 다른 점

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 자식 리소스 검사 위치 | ARM 게이트웨이가 RP보다 먼저 거절 [추론: `x-ms-failure-cause: gateway`] | DELETE 트랜잭션 안 (`accounts.py:164`가 `Tx.ensure_no_children`을 부름, `state_store.py:152-164`) | 별도 단계로 두면 검사와 삭제 사이에 자식 풀이 생겨 고아 리소스가 생길 수 있다 (ADR §6.4). 응답 코드와 메시지 형식은 녹화와 같다 |
| 자식 409의 실환경 검증 | 해당 없음 | 실환경에서 확인함: 용량 풀 사이클 AC-09 PASS. 계정 사이클에서는 계약 테스트만이었고 풀 사이클로 이월했다 | 이월 후 풀이 구현돼 닫혔다 (설계 결정 8). 이 확인은 클론 계약의 확인이지 ANF와의 비교가 아니다 |
| `Retry-After` | 안 보냄 [녹화]. RPC 사본은 10초~10분 권고 [문서] | 안 보냄 | ANF를 따랐다. 즉 클론은 ANF와는 같고 RPC 권고와는 다르다. 클라이언트가 1초 폴링을 직접 정한다 |
| 진행 중 충돌 코드 | HTTP 코드·`error.code` 모름 [미확인] (거절한다는 것만 [추론]) | `409 AnotherOperationInProgress` | **클론이 고른 값이다.** 실서비스 값이라고 말하면 안 된다 |
| api-version 오류 | 누락: `400 MissingApiVersionParameter`는 포럼 보고뿐 [미확인]. 미지원 버전: 코드 모름 [미확인] | 누락 `400 MissingApiVersionParameter`, 미지원 `400 NoRegisteredProviderFound` (`arm_rules.py:35-48`) | **클론이 고른 값이다.** `NoRegisteredProviderFound`가 이 상황에서 나온다는 것은 [추론]이다. ARM이 ANF 앞에서 하는 일을 anf-api가 맡는다 |
| 작업 상태 URL | 서명 파라미터 `t`, `c`, `s`, `h`가 붙은 절대 URL [녹화] | `api-version`만 붙은 절대 URL (`arm_app.py:57-60`) | 서명은 ARM이 붙이는 것이라 재현할 대상이 아니다 [추론] |
| `Location` URL의 실제 동작 | 진행 중 응답과 DELETE·PATCH 완료 응답 모두 [미확인] (진행 중에 `Location`을 폴링한 녹화가 없다). 완료된 POST 뒤 200 + 리소스 본문만 확인 [녹화] | RPC 규칙대로 구현: 진행 중 202, DELETE 204, 실패는 오류 응답 (`arm_app.py:218-234`) | 스펙이 DELETE·PATCH에 `final-state-via: location`을 선언해서 [스펙] 규칙(ARM RPC [문서])을 따랐다. ANF가 정확히 이렇다고 말할 수 없다 |
| 읽기 전용 속성 | RPC: 서버 값과 다르면 `400`으로 거절 [문서] | 요청에 있어도 무시 (`accounts.py:25-26`, 검사 `36-37`, `56`) | SDK가 GET 본문을 그대로 PUT하는 경우를 막지 않으려는 클론의 선택 (설계 §4.3) |
| 미룬 속성 | `identity`, AD, CMK, `nfsV4IDDomain`, `ldapConfiguration` 지원 | 받으면 `400 InvalidRequestContent`로 거절 (`accounts.py:28-29`, `38-39`, `54-55`) | 이후 기능에서 다룬다. 조용히 무시하지 않고 거절해 "되는 줄 알았다"를 막는다 |
| 응답 필드 | `etag`, `systemData`를 돌려준다 [녹화] | 돌려주지 않음 | 미룬 항목이다. `If-Match` 지원은 [미확인] |
| 목록 | `nextLink` 페이징 [스펙] | 항상 한 페이지에 전부 | 미룬 항목 |
| 작업 상태 `properties` | RPC는 Succeeded일 때만 권고 [문서], ANF는 진행 중에도 포함 [녹화] | ANF를 따라 항상 포함 | 녹화가 더 강한 근거다 |
| 작업 기록 보존 | 보존 기간 [미확인] | 지우지 않음 | 클론에서는 데이터가 작다 |
| `percentComplete` | ANF는 녹화에서 0.0과 100.0만 [녹화] | 진행 중 0.0, 종결 100.0 | 중간 값은 어디서도 못 봤다 |
| 결함 주입 | 없음 | `ANF_FAULT_INJECTION` | **클론 전용 장치.** 진행 중·실패·재시작을 실환경에서 재현하기 위한 것이다 |
| 비동기 실패 뒤 리소스 상태 | `Failed`가 되는지 [미확인] | `Failed`로 남기고 PUT으로 회복 (`lro.py:147`) | RPC가 종결 값 `Failed`를 정의하므로 [문서] 사용했다. 실서비스 동작이라고 말할 수 없다 |
| 인증, 구독 검사 | ARM이 토큰·RBAC 검증 | 하지 않음 (D-13) | 로컬 전용, 필요한 때만 Azure 개념을 넣는다는 원칙 |
| 저장소와 워커 | ANF 내부 구조는 비공개 [미확인] | SQLite + 프로세스 안 asyncio 워커 | 이 구현은 클론의 선택이다. ANF의 내부 구현을 설명하는 것이 아니다 |

---

## 5. 검증

검증 보고서: `_workspace/netapp-account/04_verifier_report.md` (1회차, 검증일 2026-11-07)와 `_workspace/netapp-account/04_verifier_report_r2.md` (2회차, 같은 날).

2회차는 용량 풀 사이클이 계정이 쓰는 공통 코드(오류 함수, 자식 검사, 결함 키 만들기, 라우트와 추적 헤더)를 바꿔서 1회차 결과가 무효가 됐기 때문에 AC-01~AC-13 전체를 다시 돌린 것이다. 결과는 PASS 13 / FAIL 0 / UNVERIFIED 0으로 같고, 바뀐 응답은 없었다. 달라진 것은 결함 키 기동 오류의 문구뿐이다(서버가 받는 키 목록이 처리기 기준으로 나온다). 2회차에서 `{"netAppAccounts/patch":{"fail":true}}`로 서버가 뜨지 않는 것도 확인했다. 아래 방법·표·측정값은 1회차 기준이고, 2회차에서도 같은 판정이다.

**방법.** WSL Ubuntu에서 설계 §6.5의 명령 그대로 실제 uvicorn 프로세스를 띄우고, 별도 프로세스(pytest)에서 표준 라이브러리 `http.client`로 요청을 보냈다(TestClient 미사용). 상태 저장소는 시나리오마다 `/tmp`(ext4)의 새 파일을 썼고, 손으로 띄운 서버에 `curl -i`로도 교차 확인했다. 검증 대상 코드의 sha256 해시는 시작과 끝에서 같았다.

**결과: PASS 13 / FAIL 0 / UNVERIFIED 0.** 같은 묶음(24개 테스트)을 3번 돌려 모두 통과했고 불안정한 결과는 없었다.

| 기준 | 증명한 것 |
| --- | --- |
| AC-01, AC-02 | PUT 신규 `201` + `Creating` + `Azure-AsyncOperation`만(`Location` 없음, curl로도 확인) → 폴링하면 `Succeeded`. PUT 기존 `200` + `Updating` → `Succeeded`, 이전 tags 키가 남지 않음 |
| AC-03~AC-05 | GET 본문 필드, 404 `ResourceNotFound`, 이름 대소문자만 달라도 같은 계정, 리소스 그룹·구독 목록, PATCH가 추적 헤더 없는 동기 200이고 tags 맵을 통째로 교체 |
| AC-06 | 잘못된 이름·api-version·본문·`location` 변경이 모두 거절되고 작업과 상태 변화가 없음 (매개변수 9개 경우) |
| AC-07 | DELETE `202` + 두 헤더 → `Succeeded` → `Location` GET `204` → 계정 GET `404` → 재DELETE `204` |
| AC-08 | 생성·삭제에 5초 지연을 주입하면 PUT은 약 10ms에 `201`을 돌려주고, 지연 중 상태가 `Creating`/`0.0`, 계정 GET이 `Creating`, 삭제 중 `Location` GET이 `202`. 작업 시간은 5.010초 |
| AC-09 | 생성 실패 주입 → `status: Failed` + `error`, `Location` GET `500`, 계정 `Failed`. 주입 없이 재기동해 PUT하면 `Updating`을 거쳐 `Succeeded`. 삭제 실패 주입 시 계정이 `Failed`로 남음 |
| AC-10 | 진행 중에 PUT·PATCH·DELETE를 보내면 각각 `409 AnotherOperationInProgress`, 새 작업이 생기지 않음(작업 테이블에서 이 리소스의 작업 1개), 거절된 요청의 tags가 반영되지 않음 |
| AC-11 | 지연 중 SIGKILL 뒤 같은 DB로 재기동하면 같은 작업이 `Succeeded`가 되고 새 작업이 생기지 않음. 같은 지연으로 재기동하면 재시작 뒤 약 4.8초(지연을 처음부터 다시 실행). 주입 없이 재기동하면 기동 직후 워커가 복구해 첫 폴링에서 `Succeeded` |
| AC-12 | 계정 작업 전후와 전체 실행 뒤의 `exportfs -v`, `/etc/exports.d/`, `/proc/fs/nfsd/exports`가 같음 |
| AC-13 | 모든 응답에 서로 다른 `x-ms-request-id`, 보낸 상관 ID는 그대로 반환, 안 보내면 새 값, 작업 행에 `correlation_id` 저장 |

**측정값.** 지연 없는 작업의 startTime→endTime은 7~10ms, 서버 기동(준비 확인까지)은 약 0.62초다.

**추가 관찰(판정에 넣지 않음).**
- 수락 기준에 없던 전이 두 개도 curl로 확인했다. `Updating → Failed`(tags가 이전 값으로 되돌아감)와 `Failed → Deleting → 삭제됨`이다.
- 결함 주입 JSON이 잘못됐거나 모르는 키면 서버가 뜨지 않는다.
- 진행 중 충돌은 `Creating`과 `Deleting` 중에만 확인했다. `Updating` 중 충돌은 실서버에서 보지 않았지만 같은 검사(`state_store.py:205`)를 지난다.

**이 검증이 증명하지 못하는 것.**
- AC-12는 비교하기 전부터 export가 0개였다. 그래서 "계정 작업이 export를 만들거나 바꾸지 않았다"만 보이고, 기존 export가 지워지지 않는지는 이 조건으로 보이지 않았다. 계정 코드에 storage agent 호출이 없으므로(`accounts.py:171`) 영향은 없다고 판단한다.
- 1회차 시점에는 자식 풀이 남은 계정의 `409 CannotDeleteResource`가 계약 테스트로만 확인된 상태였고 실환경 검증을 용량 풀 사이클로 옮겼다 (설계 결정 8). **이 항목은 이제 닫혔다.** 용량 풀 사이클 AC-09가 실환경에서 PASS했고, 2회차 보고서가 이를 이월 기준의 결과로 인용한다.
- 이 검증은 클론이 설계한 계약을 확인한 것이지, 클론이 실제 ANF와 같다는 증명이 아니다. 실서비스와의 차이는 §4에 있다.

**테스트 구성.** 단위·계약 테스트와 e2e를 합쳐 계정 사이클을 끝낸 시점의 기본 실행은 141 passed, 24 skipped(풀 기능이 들어온 뒤에는 테스트 수가 늘어 이 숫자가 아니다. e2e는 `ANF_E2E_API_URL`이 없으면 skip)다. e2e 24개는 verifier가 만든 라이브 서버 검증(`backend/tests/e2e/`)이다. 단위 테스트는 `backend/tests/unit/`, 계약 테스트는 `backend/tests/contract/test_arm_app.py`(TestClient)에 있다.

---

## 6. 개발 과정

1. **조사.** anf-researcher가 계정 API 계약과 실서비스 녹화(R1~R4)를 조사했다. 이어서 LRO 계층에 필요한 질문 5개(ARM 공통 규칙, 작업 상태 조회의 실제 응답, 진행 중 충돌, 실패한 작업, api-version 오류)를 보완 조사했다. 설계를 막는 [미확인]은 없었고, 남은 [미확인]은 RPC 규칙을 따르거나 클론이 정해서 이 문서에 적기로 했다.
2. **설계.** 설계안과 선택지 4개(백엔드 없음, 결함 주입, PUT 갱신 비동기, 자식 409의 실환경 검증 이월)를 사용자에게 제시했고, 사용자가 4개 모두 추천안으로 확정했다. 충돌 오류 코드는 제시한 기본값 `Conflict` 대신 사용자가 ARM 공통 오류 목록에 있는 `AnotherOperationInProgress`로 바꿨다. 사람이 내린 결정은 이 다섯 가지다.
3. **구현.** Claude가 TDD로 구현했다(모듈마다 RED 확인 뒤 GREEN). 구현 중 바뀐 것은 다음과 같다. 설계 문서 끝의 "구현 중 변경"에 적혀 있다.
   - 모듈 이름: `arm_ids.py` → `arm_rules.py`, `lro_worker.py` → `lro.py`.
   - 자식 리소스 검사를 DELETE 트랜잭션 안으로 옮겼다 (경합 방지). 이후 용량 풀 사이클에서 이 검사를 `Tx.ensure_no_children`으로 공통화했다.
   - 진행 중 작업 검사를 `ensure_no_active_operation` 하나로 모았고, 부분 유니크 인덱스는 안전장치로 두었다.
   - 테스트 의존성이 `httpx` 대신 `httpx2`가 됐다 (Starlette 1.10 TestClient의 deprecated 경고 때문).
4. **실환경 검증.** real-env-verifier 1회차에서 PASS 13 / FAIL 0 / UNVERIFIED 0이었다. 실패와 수정 과정은 없었다. 이 문서를 쓰는 시점에 미해결 항목은 없다.
5. **공통 코드 이동과 재검증.** 용량 풀 사이클이 공통 코드를 옮겨서(오류 함수 → `arm_rules.py`, 자식 검사 → `state_store.py`, 결함 키 → `lro.parse_faults`, 라우트 → `arm_app.py`) 1회차 결과가 무효가 됐다. 2회차에서 계정 13개 기준을 모두 다시 돌려 PASS 13 / FAIL 0 / UNVERIFIED 0이었다. 1회차에서 이월한 자식 409도 풀 사이클 AC-09에서 닫혔다.
6. **개념 문서(이 문서).** 위 이동에 맞춰 코드 인용을 고쳤다.

AI와 일한 방식으로 설명할 수 있는 것: 조사 → 설계(사람이 선택지를 결정) → 테스트 먼저 구현(TDD 훅) → 구현자와 다른 에이전트의 실환경 검증 → 개념 문서의 순서다. 검증자는 제품 코드를 고치지 않고 검증 스크립트만 새로 만들었다.

---

## 7. Interview Q&A

### Q1. (개념) Walk me through the two ways a client tracks an Azure long-running operation, and why the status codes differ.

**A.** There are two polling URLs. The `Azure-AsyncOperation` URL always returns HTTP 200, and the body's `status` field tells you whether the work is running, `Succeeded`, `Failed`, or `Canceled`. A 4xx there means reading the status failed, not that the operation failed. The `Location` URL returns 202 with no body while the work is running. When it finishes, it returns exactly what the synchronous call would have returned, so 200 with the resource for a PUT or PATCH, or 204 for a DELETE. I implemented both on one path, switched by the `operationResultResponseType=Location` query. One caveat: I confirmed ANF's recorded clients poll `Azure-AsyncOperation`. I could not confirm how ANF's real `Location` URL behaves in progress, so that part follows the ARM contract, not observed ANF behavior.

### Q2. (개념) Is an ANF NetApp account an ONTAP SVM?

**A.** I can't say that, and I deliberately didn't build it that way. I found no public source that maps an ANF account to a specific ONTAP object. An account is an Azure-side management container for capacity pools. It resembles an SVM in some ways: an account holds one Active Directory connection, like an SVM's CIFS server, and neither can be deleted while children exist. But the NFSv4 ID domain scopes to subscription and region, and CMK transitions are per VNet. That suggests the backend SVM boundary is not the account. That is my inference, not documented fact. So the account creates nothing on the storage agent. I'd rather say "unknown, here is the evidence" than invent a mapping.

### Q3. (구현) How does your implementation guarantee that a 201 response never lies about the state of the system?

**A.** The resource's in-progress state and the operation row are written in one SQLite transaction, and the API responds only after the commit. This is the "store first, then respond" rule. In `accounts.put_account`, a new account is stored as `Creating` together with a `CREATE` operation, using `BEGIN IMMEDIATE` so no other request can slip in between the check and the write. If the process dies right after responding, the operation row is already on disk, so a worker will finish it. If the transaction fails, nothing is stored and the client gets no 201. The worker also updates the resource and the operation together, so the two states cannot diverge.

### Q4. (구현) What happens if the API crashes while an operation is in flight, and what does that require from the handlers?

**A.** On startup, the in-process asyncio worker scans for operations that are not in a terminal state and re-runs them from the beginning. I tested this by sending SIGKILL during an injected 5-second delay. After restart, the same operation reached `Succeeded` and no new operation was created. This only works because handlers are idempotent. Account handlers do nothing but state transitions, so re-running is trivially safe. That will not hold for volumes, which create real resources, so volume design needs step-level recovery. Also, the re-run restarts the injected delay from zero, so my test shows recovery works, not that partial failures are handled.

### Q5. (설계) Why did you add fault injection, and what are its limits?

**A.** Account operations do no real work, so they finish in about 10 milliseconds. Without help, I could never observe an in-progress state, a failed operation, or a crash recovery against a real running server. I added an `ANF_FAULT_INJECTION` environment variable that sets a delay or a forced failure per resource type and action. It is off by default, logs a warning when on, and refuses to start on invalid input. The limits are real. It is clone-only, so real ANF has nothing like it. Failure happens before the handler runs, so it cannot simulate a half-finished job. And it cannot produce intermediate `percentComplete` values. It proves the LRO plumbing, not realistic failure behavior.

### Q6. (설계) How do you enforce one active operation per resource, and what does the client see on a conflict?

**A.** Two layers. First, `ensure_no_active_operation` runs inside the same transaction as the write. If the resource already has an in-progress operation, the request fails immediately with `409 AnotherOperationInProgress` and creates no new operation. Second, a partial unique index on `operations(resource_id)` where status is not terminal makes the database itself reject a second active operation. I chose rejection over queueing because ANF's error messages say "wait until it finishes, then retry." But I must be honest: ANF's actual HTTP and error codes for this case are unknown. I picked `AnotherOperationInProgress` from the ARM common error list. It is the clone's choice.

### Q7. (한계) Where does your clone differ from real ANF, and which of those differences are guesses?

**A.** Several. The parent-child delete check is the clearest. Real ANF's ARM gateway rejects deleting an account that still has pools, inferred from an `x-ms-failure-cause: gateway` header. I do it inside the DELETE transaction, because a separate check could let a pool be created between the check and the delete. I also send no `Retry-After`, which matches ANF recordings but differs from the ARM RPC guidance. The conflict code and the api-version error codes are my choices, not observed ANF behavior. I skip the signed query parameters on operation URLs and ignore read-only properties instead of rejecting them. Finally, the child-pool 409 was only contract-tested when the account feature shipped. It has since been verified on a live server during the capacity pool cycle, but that only proves my contract, not ANF's behavior.

### Q8. (디버깅/검증) How did you verify the async behavior, and what would you do differently?

**A.** An independent verifier ran the real uvicorn process in WSL and sent HTTP requests from a separate pytest process, not the in-process test client. It checked 13 acceptance criteria, including raw headers via curl, a SIGKILL restart, and that `exportfs` output was unchanged. All 13 passed, three runs in a row. What I'd improve: the data-plane check started with zero exports, so it could not show that existing exports survive. Conflict testing covered `Creating` and `Deleting` but not `Updating`. And the strongest remaining gap is that none of this compares against real ANF. If I did it again, I would try to poll a real `Location` URL on a live subscription to settle the unknowns.

---

## 부록. 이 문서가 쓰지 못한 것

- ONTAP 쪽 비동기 작업(job) 개념: 브리프에 없다.
- 실서비스의 진행 중 충돌 코드, api-version 오류 코드, `Location` URL의 진행 중 응답과 DELETE·PATCH 완료 응답, 비동기 실패 뒤 `provisioningState`: 브리프에서 [미확인]이다.
- ONTAP 문서(SVM, `vserver cifs create`, `vserver nfs modify`, `vserver delete`)는 원문을 읽지 못하고 검색 요약만 근거였다.
