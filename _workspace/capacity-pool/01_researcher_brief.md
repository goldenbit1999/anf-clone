# 용량 풀 (capacity-pool) 조사 브리프

- 조사 상태: 완료 (필수 질문 7개 모두 답했다. 오류의 HTTP 코드·`error.code`처럼 출처가 없어 답하지 못한 부분은 "미확인 목록"에 있다)
- 조사일: 2026-11-07
- 기준 api-version: `2026-08-01` (stable) [스펙 1]. 녹화는 모두 `2026-08-15-preview`로 호출됐다 [녹화] (아래 R 목록의 RequestUri).
- 범위 가정: 요청 범위(생성, 조회, 목록, PATCH, PUT 갱신, 삭제, 부모·자식 관계, 용량·처리량 규칙) 그대로 조사했다. 쿨 액세스, 이중 암호화, 풀 변경(change pool), Elastic(shared QoS) 풀은 존재와 이름만 적었다.
- 공통 LRO 규칙(작업 상태 본문 형식, `Retry-After` 없음, 실패 작업의 모습 등)은 계정 브리프(`_workspace/netapp-account/01_researcher_brief.md`, "ARM LRO 공통 규칙" 이하)를 참조하고 다시 쓰지 않았다.
- 녹화 표기 (모두 계정 조사 때 받은 사본, 출처 [R]):
  - N1 = `.NET PoolTests/CreateDeletePoolAsync.json` (westus2, 2026-10-29)
  - N2 = `.NET PoolTests/PatchPoolAsync.json` (2026-10-29)
  - N3 = `.NET PoolTests/UpdatePoolWithPutAsync.json` (2026-10-29)
  - N4 = `.NET PoolTests/DeleteAccountWithPoolPresentAsync.json` (2026-10-29, 계정 브리프의 R4)
  - N5 = `.NET VolumeTests/DeletePooWithVolumePresentAsync.json` (2026-10-31)
  - N6 = `.NET VolumeTests/CreateVolumePoolNotFoundAsync.json` (2026-10-31)
  - P1 = `Python test_pool...test_patch_pool.json` (2026-10-28)
  - P2 = `Python test_pool...test_update_pool.json` (2026-10-28)

## 요약 (5줄 이내)

1. 용량 풀은 계정 아래의 ARM 추적 리소스 `netAppAccounts/{a}/capacityPools/{p}`이고, 필수 속성은 `size`(바이트, 1 TiB 배수)와 `serviceLevel`이다 [스펙 1, 2]. PUT 생성은 201 + `Creating` → 약 0.3~0.5초 뒤 `Succeeded`, PATCH는 tags만 바꿔도 202 + `Patching`, DELETE는 202 + `Deleting`이었다 [녹화 N1~N3, P1].
2. 볼륨이 남은 풀 DELETE는 계정과 같은 패턴으로 즉시 409 `CannotDeleteResource`, `x-ms-failure-cause: gateway`이고 풀은 그대로 남는다 [녹화 N5].
3. 크기 규칙은 최소 1 TiB(Basic 네트워크 볼륨이 있으면 4 TiB), 최대 2,048 TiB, 1 TiB 단위 증감이다 [문서 15, 6, 7]. 풀을 볼륨 할당량 합보다 작게 줄이거나 남은 공간보다 큰 볼륨을 만들면 "Pool size too small for total volume size."가 난다 [문서 8]. HTTP 코드와 동기·비동기 여부는 [미확인].
4. Auto QoS: 볼륨 처리량 한도 = 서비스 수준 MiB/s per TiB(Standard 16, Premium 64, Ultra 128) × 볼륨 할당량(TiB, 2진) [문서 4]. Manual QoS: 볼륨마다 처리량을 정하고, 합은 풀 총 처리량(풀 TiB × 수준 단가, Flexible은 `customThroughputMibps`)을 넘을 수 없다 [문서 4, 5, 11]. 녹화에서 4 TiB Premium 풀의 `totalThroughputMibps`는 256.0, 100 GiB 볼륨 하나가 있을 때 `utilizedThroughputMibps`는 6.25였다 [녹화 N5].
5. ANF 풀에 대응하는 ONTAP 객체는 공개 자료에 없다 [미확인]. 풀은 "용량·처리량 예산이자 과금 단위"로 문서화돼 있고 [문서 11], 볼륨 처리량 한도는 ONTAP QoS 정책 그룹(Auto는 adaptive QoS)과 닮았지만 대응은 [추론]이다.

## 사용자에게 보이는 동작

### 리소스와 API

**ARM 리소스 경로** [스펙 2]
- 단건: `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.NetApp/netAppAccounts/{accountName}/capacityPools/{poolName}`
- 목록(`Pools_List`): 위 경로에서 `/{poolName}`을 뺀 것. 구독 범위 목록은 없다 [스펙 2] (capacityPools 경로는 계정 아래 두 개뿐이다).
- `poolName`: 1~64자, 패턴 `^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$` [스펙 1, 2]. 계정 이름(최대 128자)보다 짧다.
- 응답 본문의 `name`은 `"{account}/{pool}"`, `type`은 `"Microsoft.NetApp/netAppAccounts/capacityPools"`다 [스펙 3][녹화 P1].
- 풀 이름은 계정 안에서 고유해야 한다 [문서 15].
- 풀 아래 자식: 볼륨(`.../capacityPools/{p}/volumes/{v}`)과 캐시(`.../capacityPools/{p}/caches/{c}`)가 있다 [스펙 2]. 캐시는 범위 밖이다.

**작업별 계약** (2026-08-01 스펙) [스펙 2]

| operationId | 메서드 | 성공 응답 | 스펙의 응답 헤더 | LRO 설정 |
| --- | --- | --- | --- | --- |
| `Pools_Get` | GET | 200 `CapacityPool` | 없음 | 없음 |
| `Pools_List` | GET | 200 `CapacityPoolList` (`value` 필수, `nextLink`) | 없음 | 없음 |
| `Pools_CreateOrUpdate` | PUT | 200(갱신), 201(생성), 둘 다 `CapacityPool` 본문 | 201에 `Location`, `Retry-After` | `final-state-via: location` |
| `Pools_Update` | PATCH | 200 `CapacityPool`, 202(본문 없음) | 202에 `Location`, `Retry-After` | `final-state-via: location` |
| `Pools_Delete` | DELETE | 202, 204("Resource does not exist") | 202에 `Location`, `Retry-After` | `final-state-via: location` |

- **계정과 다른 점 (스펙):** 계정 PUT은 `Azure-AsyncOperation` + `final-state-via: azure-async-operation`인데, 풀 PUT은 `Location` + `final-state-via: location`으로 정의돼 있다 [스펙 1, 2]. 그러나 실서비스 녹화의 풀 PUT 201에는 `Azure-AsyncOperation`만 있었다 (아래 "비동기 동작"). 스펙과 녹화가 다르다.
- 실패는 모두 `default: ErrorResponse`(common-types v6)다 [스펙 2].

**`CapacityPool` 본문** (2026-08-01) [스펙 1, 2]
- 최상위: `id`, `name`, `type`, `systemData`(읽기 전용), `location`(필수, TrackedResource), `tags`, `etag`(읽기 전용). `CapacityPool`은 `properties`를 필수로 둔다 [스펙 2].
- `properties`(`PoolProperties`) — `required: ["size", "serviceLevel"]` [스펙 2]:

| 속성 | 타입 | 쓰기 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `size` | int64 (바이트) | 생성·갱신 | `4398046511104` (4 TiB) | "Allowed values are in 1TiB chunks (value must be multiple of 1099511627776)" |
| `serviceLevel` | enum 문자열 | 생성 (PATCH 모델에 없음) | `Premium` | `Standard`, `Premium`, `Ultra`, `StandardZRS`("will be deprecated soon"), `Flexible` |
| `qosType` | enum 문자열 | 생성·PATCH | `Auto` | `Auto`, `Manual` |
| `customThroughputMibps` | int32, nullable | 생성·PATCH | 없음 | "accepted as input only for manual qosType pool with Flexible service level" |
| `coolAccess` | boolean | 생성·PATCH | `false` | 범위 밖 |
| `encryptionType` | enum, nullable | 생성만 (`x-ms-mutability: read, create`) | `Single` | `Single`, `Double`. "This value can only be set when creating new pool." |
| `poolId` | UUID 문자열 36자 | 읽기 전용 | — | |
| `provisioningState` | 문자열(enum 없음) | 읽기 전용 | — | |
| `totalThroughputMibps` | float32 | 읽기 전용 | — | 풀 총 처리량 |
| `utilizedThroughputMibps` | float32 | 읽기 전용 | — | 풀에서 쓰인 처리량 |

- `size`와 `serviceLevel`은 `required`이면서 기본값도 있다 [스펙 2]. 둘 다 빠진 요청을 서버가 어떻게 다루는지는 [미확인] (아래 PUT 갱신 녹화 참고).
- **버전에 따른 크기 규칙 차이:** TypeSpec에서 stable 버전의 `size`는 "1TiB chunks"이고, preview 버전(`2025-12-15-preview` 이후 모든 `-preview`, `2026-08-15-preview` 포함)의 `size`는 "512GiB (549755813888 bytes) or in 1TiB chunks"다 [스펙 1]. 녹화가 쓴 preview에서는 512 GiB 풀이 허용될 수 있다는 뜻이다 [추론]. 2026-08-01 기준이면 1 TiB 배수다.
- 생성 응답과 GET 응답의 차이 [녹화 N1~N3, P1, P2]:
  - 요청 `{"location", "tags", "properties": {"size": 4398046511104, "serviceLevel": "Premium"}}`에 대한 201 본문은 `provisioningState: Creating`, `totalThroughputMibps: 0.0`, `utilizedThroughputMibps: 0.0`이고 `qosType`, `coolAccess`, `encryptionType`, `poolId`가 없었다.
  - 완료 뒤 GET에는 `qosType: Auto`, `coolAccess: false`, `encryptionType: Single`, `poolId`(UUID), `totalThroughputMibps: 256.0`이 채워졌다.
- **`totalThroughputMibps` 계산 단위 충돌:** 녹화의 4 TiB Premium 풀은 `256.0`(= 4 × 64, 2진 TiB)이다 [녹화 N1]. 스펙 예시의 같은 풀은 `281.474`(= 4.398 × 64, 10진 TB로 계산한 값)다 [스펙 3]. 실서비스 값은 256.0이다.
- 스펙 예시 `Pools_CreateOrUpdate`의 201 본문은 `provisioningState: Succeeded`, Flexible 예시의 201은 `Creating`이다 [스펙 3]. 예시끼리도 다르다.

**PATCH 본문** (`CapacityPoolPatch`) [스펙 1, 2]
- 최상위: `location`(쓰기 가능), `id`·`name`·`type`(읽기 전용), `tags`, `properties`(`PoolPatchProperties`).
- `PoolPatchProperties`: `size`, `qosType`, `coolAccess`, `customThroughputMibps`뿐이다. `serviceLevel`, `encryptionType`은 PATCH로 바꿀 수 없다.
- 녹화의 PATCH 요청: `{"tags": {...}, "location": "westus2"}` (N2), `{"properties": {"qosType": "Manual"}, "tags": {"Tag2": "Value1"}}` (P1). 둘 다 202였다 [녹화].
- tags PATCH는 맵 전체 교체였다. P1에서 PATCH 뒤 tags가 `{"Tag2": "Value1", "CreatedOnDate": ...}`였다 [녹화 P1]. `CreatedOnDate`는 계정 브리프에서 정리한 대로 테스트 구독의 Azure Policy가 붙인 것으로 보인다 [추론].

**PUT으로 기존 풀 갱신**
- N3: 기존 tags + 새 태그 + `properties` 전체(`size`, `serviceLevel`, `qosType`, `coolAccess`, `encryptionType`)를 보낸 PUT → 200, `provisioningState: Updating`, `Azure-AsyncOperation` [녹화 N3].
- P2: `{"properties": {"qosType": "Manual"}, "location": "westus2"}`만 보낸 PUT(`size`, `serviceLevel` 없음) → 200 `Updating`, 완료 뒤 `qosType: Manual`, `size: 4398046511104`, `serviceLevel: Premium` [녹화 P2]. 기존 값이 기본값(4 TiB, Premium)과 같아서, 서버가 빠진 속성을 기존 값으로 유지했는지 기본값을 적용했는지는 구분되지 않는다 [미확인].

**부모·자식 관계**
- 풀은 계정 하나에만 속하고, 다른 계정으로 옮길 수 없다 [문서 6].
- 풀 하나는 서비스 수준 하나만 가진다 [문서 6].
- 볼륨을 모두 지우기 전에는 풀을 지울 수 없다 [문서 6].
- 볼륨의 서비스 수준 변경은 볼륨을 같은 계정의 다른 풀로 옮기는 기능(`Volumes_PoolChange`, POST `poolChange`)으로 한다 [문서 9][스펙 3]. 범위 밖.

**az CLI** — 명령 그룹은 `az netappfiles pool`이다 [문서 7]. 세부 인자는 조사하지 않았다.

### 비동기 동작

**녹화에서 관찰한 것**

| 작업 | 상태 코드 | 본문 `provisioningState` | LRO 헤더 | 작업 상태 `status` 전이 | 걸린 시간(startTime→endTime) | 근거 |
| --- | --- | --- | --- | --- | --- | --- |
| PUT 생성 | 201 | `Creating` | `Azure-AsyncOperation`만 (`Location`, `Retry-After` 없음) | `Creating` → `Succeeded` | 0.20~0.45초 | [녹화 N1, N2, N3, N5, P1, P2] |
| PUT 갱신 | 200 | `Updating` | `Azure-AsyncOperation` | → `Succeeded` | 약 0.26~0.30초 | [녹화 N3, P2] |
| PATCH (tags만, 또는 qosType) | 202 | `Patching` (본문 있음) | `Azure-AsyncOperation` + `Location` | `Patching` → `Succeeded` | 약 0.29~0.48초 | [녹화 N2, P1] |
| DELETE | 202 | 본문 없음 | `Azure-AsyncOperation` + `Location` | `Deleting` → `Succeeded` | 약 0.26~0.32초 | [녹화 N1, N3, N5] |

- 폴링 횟수: 생성은 상태 조회 1~2회였다 [녹화]. P2에서는 첫 조회(`Creating`)와 둘째 조회(`Succeeded`) 사이가 30초였는데, 작업 자체는 0.45초에 끝났다 [녹화 P2]. ANF가 `Retry-After`를 주지 않아 Python SDK가 기본 간격으로 기다린 것으로 보인다 [추론] (계정 브리프의 "`Retry-After`는 Microsoft.NetApp 응답 어디에도 없었다"와 같다).
- 진행 중 작업 상태 본문: `status: Creating|Patching|Deleting`, `percentComplete: 0.0`, `endTime: "0001-01-01T00:00:00Z"` [녹화 N1, N2, N3]. 계정 브리프의 공통 형식과 같다.
- **스펙과 녹화가 다른 점:**
  - PUT 201: 스펙은 `Location` + `Retry-After`, `final-state-via: location` [스펙 2]. 녹화는 `Azure-AsyncOperation`만 [녹화]. 녹화가 preview api-version으로 호출됐다는 점도 함께 기록한다. preview 스펙의 헤더 정의는 확인하지 않았다 [미확인].
  - PATCH: 스펙은 202 본문이 없다 [스펙 2]. 녹화의 202에는 풀 전체 본문(`provisioningState: Patching`)이 있었다 [녹화 N2, P1].
  - PUT 200(갱신): 스펙은 헤더가 없다 [스펙 2]. 녹화는 `Updating` + `Azure-AsyncOperation` [녹화 N3]. 계정과 같은 패턴이다.
- **PATCH가 동기인 경우:** 풀 PATCH는 tags만 바꿔도 202였다 [녹화 N2]. 계정 PATCH(tags만)가 200 동기였던 것과 다르다 (계정 브리프).
- **provisioningState 값:** 리소스 본문에서 관찰한 값은 `Creating`, `Updating`, `Patching`, `Succeeded` [녹화]. 작업 상태 `status`에서는 `Deleting`도 관찰됐다 [녹화 N3]. 리소스 본문의 `Deleting`·`Failed`는 녹화에 없다 [미확인].
- **실패한 풀의 모습:** ANF 오류 문서는 풀이 "failed state"일 수 있다고 쓴다("If the pool is in a failed state (not "Succeeded"), try performing an update on the capacity pool by adding a tag name and value pair, then save.") [문서 10]. 실패한 풀에 tags PATCH를 하면 회복을 시도할 수 있다는 단서다. 또 "Volume cannot be created in a pool that isn't in state succeeded." 오류가 있다 [문서 8]. 실패 상태 값의 정확한 문자열은 [미확인].
- **삭제 직후의 계정 삭제:** P1·P2에서 풀 DELETE 작업이 `Succeeded`로 끝난 직후 계정 DELETE가 10초 간격으로 두 번 409 `CannotDeleteResource`(풀 ID 포함)를 받고, 세 번째에 202였다 [녹화 P1, P2]. ARM 게이트웨이의 자식 리소스 정보가 몇 초~수십 초 늦게 갱신되는 것으로 보인다 [추론]. .NET 테스트는 풀 삭제 뒤 약 40초 기다린 다음 계정을 지웠다 [녹화 N1, N2].

### 제약과 한도

**크기** (2026-08-01 기준)
- 최소 1 TiB, 최대 2,048 TiB, 1 TiB 단위로 늘리거나 줄인다 [문서 15, 7, 11]. 최대 크기는 resource limits 표에서 "Adjustable via support request: No"다 [문서 7].
- 1 TiB 최소는 풀 안 모든 볼륨이 Standard 네트워크 기능일 때만이고, Basic 네트워크 기능 볼륨이 하나라도 있으면 최소 4 TiB다 [문서 15, 6.1(resize)].
- API 단위는 바이트이고 1099511627776의 배수여야 한다 [스펙 1, 2]. preview는 512 GiB도 허용한다 [스펙 1].
- 1 TiB 풀을 tag와 함께 만들려면 `2023-07-01-preview`~`2024-01-01-preview` 또는 `2024-01-01` 이후 stable을 써야 한다 [문서 15]. 크기 최소값이 4 TiB에서 1 TiB로 바뀐 이력의 단서다 [추론].
- 풀을 줄일 때 하한: 문서마다 표현이 다르다. 두 내용을 모두 기록한다.
  - "the capacity pool size cannot be smaller than the sum of the capacity of the volumes hosted in the pool" [문서 6.1(resize)], "down to the capacity allocated to the volumes in the capacity pool" [문서 11] → 볼륨 **할당량(quota) 합**.
  - "the size is smaller than the total usedBytes value of all volumes in that capacity pool" [문서 8] → 볼륨 **사용량** 합.
  - 할당량 합 쪽이 두 문서이고, 볼륨 생성 규칙("sum of volume capacity quotas in a pool can't exceed the pool size" [문서 11])과도 맞는다 [추론].
- 개수: 계정당 풀 100개(늘릴 수 있음), 풀당 볼륨 1,000개(늘릴 수 있음), 구독·리전당 용량 할당량 100 TiB(늘릴 수 있음) [문서 7].

**서비스 수준과 처리량 단가** [문서 4]

| 서비스 수준 | 처리량 | 비고 |
| --- | --- | --- |
| Standard | 16 MiB/s per TiB | |
| Premium | 64 MiB/s per TiB | |
| Ultra | 128 MiB/s per TiB | |
| Flexible | 풀 처리량을 따로 정한다. 최소 128 MiB/s(풀 크기와 무관), 최대 5 × 128 MiB/s/TiB × 풀 TiB | Manual QoS 전용, 새 풀에서만 |
| StandardZRS | 스펙 enum에만 있고 "will be deprecated soon" [스펙 2] | 범위 밖 |
| (Elastic, preview) | 32 MiB/s per TiB, shared QoS, 1~128 TiB | 별도 리소스 `elasticAccounts` 계열. 범위 밖 [문서 4, 6] |

**생성 뒤 바꿀 수 있는 것과 없는 것**

| 속성 | 변경 | 근거 |
| --- | --- | --- |
| `size` | 가능 (PATCH, PUT). 1 TiB 단위 증감, 하한은 위 참고 | [스펙 2][문서 6.1(resize), 11] |
| `qosType` Auto → Manual | 가능, 되돌릴 수 없는 영구 변경. 변환 시 처리량이 manual 한도에 맞게 깎일 수 있다 | [문서 15, 5, 6][녹화 P1(PATCH), P2(PUT)] |
| `qosType` Manual → Auto | 불가 | [문서 15, 5, 6]. 오류 코드 [미확인] |
| `serviceLevel` | PATCH 모델에 없다 [스펙 2]. RP 오류 문서에 "ServiceLevel cannot be changed." — "update or patch a capacity pool with a different service level when the capacity pool already has volumes in it" [문서 8]. 즉 볼륨이 없는 풀은 PUT으로 서비스 수준을 바꿀 수 있는 것으로 읽힌다 [추론]. Flexible ↔ 다른 수준 변환은 불가 [문서 15, 9] | |
| `encryptionType` | 생성만 | [스펙 2][문서 15] |
| `customThroughputMibps` (Flexible) | 증가는 언제나, 감소는 마지막 처리량 변경 뒤 24시간 쿨다운이 지나야 | [문서 15, 5] |
| `poolId` | 읽기 전용. 다른 값을 보내면 "PoolId cannot be changed" | [스펙 2][문서 8] |
| `location` | 생성 뒤 불변 (TrackedResource) | 계정 브리프 [스펙 7]과 같은 규칙 [추론] |

**Flexible 세부** [문서 15, 4, 5]
- Manual QoS 풀에서만, 새로 만드는 풀에서만 쓸 수 있다. 기존 풀을 Flexible로 바꾸거나 Flexible을 다른 수준으로 바꿀 수 없다.
- 단일 암호화만 지원한다.
- Flexible 풀의 볼륨은 다른 풀로 옮길 수 없고, 다른 풀의 볼륨을 Flexible 풀로 옮길 수도 없다.
- 포털 안내는 "Enter a value between 128 and 2560 MiB/s"다 [문서 5]. 2560은 4 TiB 풀의 최대값(5 × 128 × 4)과 같아서 예시 풀 기준 문구로 보인다 [추론]. 공식은 위 표다.
- 스펙 예시: 4 TiB Flexible·Manual 풀, `customThroughputMibps: 128` → `totalThroughputMibps: 128` [스펙 3].

**Manual QoS 볼륨 처리량 한도** [문서 7]
- 볼륨당 최소 1 MiB/s, 일반 볼륨 최대 4,500 MiB/s, 대용량 볼륨 최대 12,800 MiB/s.

### 오류 상황

| 상황 | HTTP | 코드·메시지 | 동기/비동기 | 근거 |
| --- | --- | --- | --- | --- |
| 볼륨이 남은 풀 DELETE | 409 | `CannotDeleteResource`, "Cannot delete resource while nested resources exist. Some existing nested resource IDs include: 'Microsoft.NetApp/netAppAccounts/{a}/capacityPools/{p}/volumes/{v}'. Please delete all nested resources before deleting this resource." 헤더 `x-ms-failure-cause: gateway`. 직후 풀 GET은 200 `Succeeded` | 즉시 거절 (작업 생성 없음) | [녹화 N5] |
| 풀이 남은 계정 DELETE | 409 | 같은 코드, 메시지에 풀 ID | 즉시 | [녹화 N4, P1, P2] (계정 브리프 R4) |
| 없는 풀에 볼륨 PUT | 404 | `ParentResourceNotFound`, "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools/volumes', because the parent resource '{pool id}' could not be found." `x-ms-failure-cause: gateway` | 즉시 | [녹화 N6] |
| 없는 풀 GET (계정은 있음) | 404 | `ResourceNotFound`, 형식이 두 가지였다 (아래) | 즉시 | [녹화 N1, N6] |
| 없는 풀 DELETE | 204 | 본문 없음 | — | [스펙 2] (녹화 없음) |
| 풀을 볼륨 할당량 합보다 작게 줄임 / 남은 공간보다 큰 볼륨 생성 / 볼륨을 남은 공간보다 크게 늘림 | [미확인] | 문서 제목: "Pool size too small for total volume size." [문서 8]. NetApp KB의 실제 메시지 예: "The capacity pool size of 59373627899904 bytes is too small for the combined volume size of 59910498811904 bytes of the capacity pool. Make sure that the total size of all the volumes in the capacity pool does not exceed the size of the capacity pool." [문서 13 — KB 원문은 로그인 필요, 검색 요약만] | [미확인] | [문서 8, 13] |
| Manual QoS 풀에서 볼륨 처리량 합이 풀 처리량을 넘는 볼륨 생성·수정 | [미확인] | "Requested throughput not available" [문서 10] | [미확인] | [문서 10] |
| 볼륨이 있는 풀의 서비스 수준 변경 | [미확인] | "ServiceLevel cannot be changed." | [미확인] | [문서 8] |
| `poolId`를 다른 값으로 보냄 | [미확인] | "PoolId cannot be changed" | [미확인] | [문서 8] |
| 실패 상태 풀에 볼륨 생성 | [미확인] | "Volume cannot be created in a pool that isn't in state succeeded." | [미확인] | [문서 8] |
| 볼륨 생성 시 풀 없음 (RP 쪽 메시지) | [미확인] | "Parent pool not found" — 풀이 다 만들어지지 않았거나 이미 지워진 경우 | [미확인] | [문서 8]. 녹화에서는 게이트웨이의 404 `ParentResourceNotFound`였다 [녹화 N6] |
| 볼륨 서비스 수준이 풀보다 높음 | [미확인] | "Service level '{volumeServiceLevel}' is higher than parent '{poolServiceLevel}'" | [미확인] | [문서 8] |
| 계정당 풀 수 초과 | [미확인] | "Creating the resource of type {resourceType} would exceed the quota of {quota} resources of type {resourceType} per {parentResourceType}. ..." | [미확인] | [문서 8] |
| Manual → Auto 변경 | [미확인] | 문서는 "불가"라고만 쓴다 | [미확인] | [문서 15, 5] |

- **404 형식 두 가지** [녹화 N1]:
  - 한 번도 없던 이름(`pool-61831`): `"The Resource 'Microsoft.NetApp/netAppAccounts/{a}/capacityPools/{p}' under resource group '{rg}' was not found. For more details please go to https://aka.ms/ARMResourceNotFoundFix"` + `x-ms-failure-cause: gateway`.
  - 방금 삭제한 이름: `"The resource with identifier '/subscriptions/.../capacityPools/{p}' is not found."`, `x-ms-failure-cause` 없음. RP가 낸 404로 보인다 [추론] (계정 브리프의 계정 404 메시지와 같은 형식).
  - 둘 다 `error.code`는 `ResourceNotFound`다.
- **용량 초과 오류가 동기인지:** 문서와 녹화 어디에도 HTTP 코드나 작업 실패 본문이 없다 [미확인] (찾아본 곳: 문서 8·10, .NET 144개·Python 32개 녹화의 `error.code` 전체 집계 — `ResourceNotFound`, `CannotDeleteResource`, `ParentResourceNotFound`, `BadRequest`, `Conflict`, `InternalServerError` 등뿐이고 용량·처리량 관련 코드는 0건, 웹 검색 1회).
- 계정 브리프의 실패 녹화에서 ANF는 비동기 실패 시 최상위 `error.code`에 일반 코드(`BadRequest`), `details[].code`에 구체 코드를 넣었다. 용량 오류도 이 패턴일 수 있지만 근거는 없다 [추론].

## 데이터 플레인에서 보이는 효과

- **풀 자체는 클라이언트가 마운트하는 대상이 아니다.** 볼륨만 마운트된다 [문서 6]. 풀을 만들거나 지우는 것만으로 클라이언트에서 보이는 변화는 없다 [추론] (근거: 볼륨은 풀 아래에만 있고 마운트 대상은 볼륨의 export다 — 문서 6, 스펙 2).
- **풀이 볼륨에 주는 간접 효과는 두 가지다.**
  1. **용량:** 볼륨 할당량(quota) 합은 풀 크기를 넘을 수 없다 [문서 11]. 풀은 프로비저닝된 크기로 과금되고, 실제 쓴 양과 무관하다 [문서 11]. 클라이언트에서 보이는 크기는 볼륨 할당량이다 (볼륨 사이클에서 확인) [추론].
  2. **처리량:** 볼륨 처리량 한도가 풀의 서비스 수준과 QoS 유형으로 정해진다 [문서 4].
- **처리량 공식 (FR-08 근거)**
  - Auto QoS (Standard/Premium/Ultra): `볼륨 한도(MiB/s) = 수준 단가(16|64|128 MiB/s per TiB) × 볼륨 할당량(TiB)` [문서 4]. 할당량은 2진 단위다. 문서 예: Premium 2 TiB → 128 MiB/s, Premium 100 GiB → 6.25 MiB/s(0.09765625 TiB × 64). "This scenario applies regardless of the capacity pool size or the actual volume consumption." [문서 4].
    - 녹화 확인: 4 TiB Premium Auto 풀에 100 GiB 볼륨 하나를 만든 뒤 풀 GET이 `totalThroughputMibps: 256.0`, `utilizedThroughputMibps: 6.25`였다 [녹화 N5]. 볼륨에 I/O가 없던 시점이므로 `utilizedThroughputMibps`는 실측 사용량이 아니라 볼륨들에 **배정된 한도의 합**으로 보인다 [추론].
  - Manual QoS (Standard/Premium/Ultra): 풀 총 처리량 = 풀 크기(TiB) × 수준 단가. 예: Ultra 10 TiB → 1,280 MiB/s. 볼륨마다 처리량을 따로 정하고, 볼륨 처리량 합은 풀 총 처리량을 넘을 수 없다 [문서 4, 6].
  - Manual QoS (Flexible): 풀 총 처리량 = `customThroughputMibps` (128 ≤ x ≤ 5 × 128 × 풀 TiB). 볼륨 처리량 합 ≤ 풀 처리량 [문서 4, 11].
  - 상한: 일반 볼륨의 실측 최대는 4,500 MiB/s이고, Premium Auto에서 할당량 70.31 TiB를 넘겨도 실제 처리량은 더 늘지 않는다 [문서 12].
- **한도에 닿았을 때 클라이언트가 보는 것:** "After the volume throughput limit is reached, the system queues extra I/O requests and latency can rise rapidly while throughput stays capped." [문서 12]. 즉 I/O 오류가 아니라 지연 증가와 처리량 상한으로 나타난다. ANF는 "Throughput limit reached" 지표를 제공한다 [문서 12].
- **변경 반영 속도:** "When volume quota is changed, the corresponding change in throughput limit is nearly instantaneous." [문서 12]. Auto→Manual 변환 시 처리량이 manual 한도에 맞게 깎일 수 있다 [문서 5].
- 한도는 읽기와 쓰기를 합친 값이다 ("Throughput is a combination of read and write speed.") [문서 4, 12].

## ONTAP 대응 개념

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| 용량 풀 | 직접 대응하는 공개된 객체 없음 | ANF는 "NetApp's bare metal with ONTAP storage OS running inside the Azure datacenter"이고 PaaS라고만 쓴다 [문서 12]. 풀이 ONTAP의 애그리게이트, SVM, QoS 정책 그룹 중 무엇으로 구현되는지는 공개 자료에서 찾지 못했다 (Learn 문서, 웹 검색 2회. 검색에 나온 Cloud Volumes ONTAP 자료는 다른 제품이라 근거로 쓰지 않았다). | [미확인] |
| 용량 풀 = 용량·처리량 예산 + 과금 단위 | (Azure 쪽 개념) | "You purchase capacity and throughput through capacity pools, which are the main units of billing." "capacity pools are the main units for provisioning and billing. Volumes are the units for consumption." 시간마다 풀 크기, 서비스 수준, (Flexible이면) 처리량을 측정한다 [문서 11]. | [문서 11] |
| 풀 크기 (프로비저닝된 용량) | 애그리게이트의 물리 용량과는 다른 것으로 보인다 | ONTAP 애그리게이트는 디스크를 묶은 물리 저장 공간이다 [미확인 — docs.netapp.com 원문은 이번에 확인하지 않음]. ANF 풀은 "fixed SKUs that you purchased"로 측정되고 [문서 6] 사용량과 무관하게 과금된다 [문서 11]. 그래서 풀은 물리 공간이 아니라 볼륨 할당량에 대한 논리적 상한(예약)에 가깝다 [추론]. | [추론] |
| 볼륨 할당량 ≤ 풀 크기 규칙 | thin provisioning과 반대되는 엄격한 예약 | ONTAP은 볼륨 `space-guarantee none`으로 애그리게이트보다 큰 볼륨 합을 허용(오버커밋)할 수 있다 [미확인 — 이번 검색에서 원문 확인 못함]. ANF는 풀 수준에서 할당량 합 ≤ 풀 크기를 강제한다 [문서 11]. ANF 백엔드가 ONTAP 볼륨을 thin으로 만드는지는 공개되지 않았다 [미확인]. | 대응 [추론] |
| Auto QoS 볼륨 처리량 한도 (할당량에 비례) | ONTAP adaptive QoS 정책 그룹 | ONTAP adaptive QoS는 볼륨 크기(할당 공간 또는 사용 공간) TB당 IOPS 상한(peak-iops per TB)을 두고 볼륨 크기에 따라 상한을 자동으로 바꾼다 [문서 14 — docs.netapp.com, 검색 요약만, 원문 미확인]. "크기에 비례하는 상한"이라는 점이 ANF Auto QoS와 닮았다. 단 ONTAP adaptive QoS는 IOPS 단위이고, ANF Auto QoS는 MiB/s 단위다. ANF가 실제로 이것을 쓰는지는 공개되지 않았다. | 대응 [추론] |
| Manual QoS 볼륨 처리량 (고정 MiB/s) | ONTAP QoS 정책 그룹의 `max-throughput` (처리량 상한) | ONTAP QoS 정책 그룹은 볼륨 같은 스토리지 객체에 처리량 상한(ceiling)을 건다 [미확인 — 이번 검색에서 원문 확인 못함]. ANF Manual QoS는 볼륨마다 MiB/s를 정한다 [문서 4]. | 대응 [추론] |
| 풀 총 처리량 (`totalThroughputMibps`) | 직접 대응 없음 | ONTAP QoS 정책 그룹은 여러 객체가 상한을 공유하게 할 수 있지만(shared policy group), ANF Manual 풀은 "볼륨 한도들의 합 ≤ 풀 한도"라는 **배정 검사**이지 공유 상한이 아니다 [문서 4, 11]. ANF의 shared QoS(Elastic)는 공유 상한에 가깝다 [문서 4, 6]. ONTAP shared policy group의 정확한 의미는 [미확인]. | [추론] |
| 서비스 수준 | 직접 대응 없음 | ANF 문서는 서비스 수준을 "볼륨 할당량 대비 허용 최대 처리량"으로 정의한다 [문서 4]. 서로 다른 하드웨어 계층이라는 공식 설명은 없다 (Standard·Premium·Ultra·Flexible 모두 "bare-metal flash performance" [문서 4]). 즉 수준 차이는 QoS 상한 차이다 [추론]. | [추론] |

- 면접에서 쓸 때 안전한 문장: "ANF 문서상 풀은 용량과 처리량을 사는 과금·예산 단위이고, 볼륨 처리량 한도는 풀의 서비스 수준과 QoS 유형으로 정해진다 [문서 4, 11]. ONTAP 쪽에서 가장 닮은 개념은 QoS 정책 그룹(Auto는 adaptive QoS)이지만, ANF가 내부적으로 그렇게 구현한다는 공개 자료는 없다."

## 구현 범위 후보

**이번에 재현할 것 (후보, 이유)**
- PUT 생성(201 + `Creating` + `Azure-AsyncOperation`), PUT 갱신(200 + `Updating`), PATCH(202 + 본문 `Patching` + 두 헤더), DELETE(202 + 두 헤더, `Deleting` → `Succeeded`), 없는 풀 DELETE 204, GET, 목록 — 계정과 같은 공통 LRO 계층을 재사용할 수 있다.
- 본문 규칙: `size`(1 TiB 배수, 1~2,048 TiB), `serviceLevel` enum, `qosType`(기본 Auto), `encryptionType`(생성만, 기본 Single), `poolId`(UUID, 읽기 전용), `totalThroughputMibps` 계산값, `utilizedThroughputMibps`(볼륨이 없으면 0.0).
- Auto → Manual 단방향 전환, Manual → Auto 거절.
- 볼륨이 남은 풀 DELETE → 409 `CannotDeleteResource` (볼륨이 생기기 전까지는 검증할 수 없으므로 볼륨 사이클로 넘길 수도 있다).
- 풀이 남은 계정 DELETE → 409 (계정 사이클에서 넘어온 기준).
- `totalThroughputMibps`, `utilizedThroughputMibps` 공식을 저장·계산만 한다. 실제 I/O 제한은 FR-08(S2 스파이크 뒤).

**다음으로 미룰 것**
- 볼륨 할당량 합 ≤ 풀 크기 검사와 풀 축소 하한 검사: 볼륨이 있어야 의미가 있다. 다만 규칙(어디서, 동기 4xx인지 작업 실패인지)은 ADR §6.4에 따라 지금 정할 수 있다.
- Manual QoS 처리량 배정 검사("Requested throughput not available"): 볼륨의 처리량 속성이 필요하다.
- Flexible(`customThroughputMibps`, 24시간 쿨다운), StandardZRS, 쿨 액세스, Double 암호화, 풀 변경, 캐시.

**리더·사용자가 정해야 할 선택지**
1. **PUT 201의 추적 헤더:** 스펙(2026-08-01)은 `Location` + `final-state-via: location`, 녹화는 `Azure-AsyncOperation`만이다. 계정 설계 §4가 정한 공통 계약과 어느 쪽이 맞는지 정한다.
2. **PATCH 202 본문:** 스펙은 본문 없음, 녹화는 `Patching` 본문 있음. 녹화를 따를지.
3. **용량·처리량 초과 오류의 형태:** 동기 4xx(예: 400 + `error.code`)로 할지, 작업을 만든 뒤 `Failed`로 끝낼지. 실서비스 근거가 없으므로 클론의 결정으로 문서화해야 한다. `error.code` 이름도 정해야 한다 (문서는 메시지만 준다).
4. **풀 축소 하한의 기준:** 볼륨 할당량 합(문서 두 곳)인지 사용량 합(RP 오류 문서)인지.
5. **`serviceLevel` 변경:** 빈 풀의 PUT으로 서비스 수준 변경을 허용할지(오류 문서에서 추론), 아예 불변으로 둘지.
6. **`size` 단위 버전 차이:** 2026-08-01만 지원하므로 512 GiB는 거절할지(stable 규칙), preview 규칙을 무시할지.
7. **PUT 갱신에서 빠진 `size`/`serviceLevel`:** 기존 값 유지, 기본값 적용, 400 거절 중 무엇으로 할지 (실서비스 동작 [미확인]).
8. **`totalThroughputMibps` 계산 단위:** 녹화(2진, 256.0)를 따를지 스펙 예시(10진, 281.474)를 따를지. 녹화를 따르는 쪽이 실서비스와 같다.
9. **삭제 직후 계정 DELETE 409(게이트웨이 지연)를 재현할지:** 재현할 이유는 약하다.

**검증 기준 후보** (컨트롤 플레인 위주. REST 응답으로 쓴다)
1. `PUT {size: 4398046511104, serviceLevel: "Premium"}` → 201, 본문 `provisioningState: Creating`, 추적 헤더가 있다. 폴링하면 `Succeeded`, 이후 GET에 `qosType: Auto`, `encryptionType: Single`, `coolAccess: false`, UUID `poolId`, `totalThroughputMibps: 256.0`, `utilizedThroughputMibps: 0.0`.
2. Standard 2 TiB → `totalThroughputMibps: 32.0`, Ultra 1 TiB → `128.0` (공식 확인).
3. `size`가 1 TiB 배수가 아님(예: 549755813888), 0, 2,049 TiB → 4xx, 풀이 생기지 않는다.
4. `serviceLevel`이 enum 밖, 이름 패턴 위반(`-p`, 65자) → 4xx.
5. PATCH `{"tags": {"b": "2"}}` → 202 + `Patching`, 폴링 뒤 GET tags가 정확히 `{b:2}`.
6. PATCH `{"properties": {"qosType": "Manual"}}` → 성공 후 `qosType: Manual`. 이어서 PATCH `{"properties": {"qosType": "Auto"}}` → 거절되고 `Manual` 유지.
7. PATCH `{"properties": {"size": 8796093022208}}` → 성공 후 `size` 8 TiB, Premium Auto면 `totalThroughputMibps: 512.0`.
8. 생성 뒤 `encryptionType`을 바꾼 PUT → 거절, 원래 값 유지.
9. DELETE → 202 + 추적 헤더, 폴링 `Succeeded`, GET 404 `ResourceNotFound`, 다시 DELETE → 204.
10. 풀이 있는 계정 DELETE → 409 `CannotDeleteResource`, 메시지에 풀 ID, 풀 GET은 200.
11. 없는 계정 아래 풀 PUT → 404 (게이트웨이 패턴은 볼륨의 `ParentResourceNotFound` [녹화 N6]에서 추론).
12. 풀 생성·삭제 전후에 storage agent의 NFS export 목록(`exportfs -v`)이 바뀌지 않는다 (풀 자체는 데이터 플레인을 건드리지 않음).

## 미확인 목록

| 항목 | 설계를 막는가 | 찾아본 곳 |
| --- | --- | --- |
| 용량 초과(풀 축소, 볼륨 생성·확장) 오류의 HTTP 코드, `error.code`, 동기/비동기 | 선택 필요 (선택지 3) | 문서 8·10, NetApp KB(로그인 필요, 검색 요약만), 녹화 176개 `error.code` 집계, 웹 검색 1회 |
| Manual QoS "Requested throughput not available"의 HTTP 코드·`error.code` | 막지 않음 (볼륨 사이클) | 문서 10, 녹화 |
| Manual → Auto 거절, 볼륨 있는 풀의 서비스 수준 변경 거절의 HTTP 코드 | 선택 필요 | 문서 15·5·8, 녹화(관련 실패 0건) |
| PUT 갱신에서 `size`/`serviceLevel`을 빼면 기존 값 유지인지 기본값 적용인지 | 선택 필요 (선택지 7) | 녹화 P2(기존 값 = 기본값이라 구분 불가), 스펙 2 |
| preview(`2026-08-15-preview`) 스펙의 풀 PUT 201 헤더 정의 | 막지 않음 | 2026-08-01 스펙만 확인 |
| 리소스 본문의 `provisioningState: Deleting`, `Failed` 값 | 막지 않음 (계정 브리프와 같음) | 녹화(삭제 중 GET 없음), 문서 10("failed state") |
| ANF 풀에 대응하는 ONTAP 객체 | 막지 않음 (개념 문서에서 [추론]으로 설명) | Learn 문서, 웹 검색 2회 |
| ONTAP QoS `max-throughput`, shared policy group, `space-guarantee none`의 원문 | 막지 않음 (개념 문서용) | 웹 검색 1회(adaptive QoS만 나옴). docs.netapp.com은 계정 조사 때 WebFetch 403 |
| 같은 풀에 작업이 진행 중일 때 새 PATCH/PUT/DELETE의 응답 | 선택 필요 (계정 브리프와 같은 미확인) | 계정 브리프 참조 |

## 후속 조사 목록

- 볼륨 사이클: 볼륨 할당량(`usageThreshold`)과 Manual QoS 볼륨 `throughputMibps` 속성, 볼륨 생성·확장 시 용량 초과 오류의 실제 응답.
- FR-08 사이클: Auto→Manual 변환 시 "throughput levels might be capped"의 구체 규칙 [문서 5].
- Flexible 풀(`customThroughputMibps` 범위 검증, 24시간 쿨다운)을 재현할지.
- 풀 변경(`Volumes_PoolChange`)과 그 오류들 [문서 10].
- 쿨 액세스(`coolAccess`), 이중 암호화(`encryptionType: Double`), StandardZRS, Elastic(shared QoS) 풀.
- az CLI `az netappfiles pool` 인자.

## 출처

확인일은 모두 2026-11-07이다.

- [1] Azure REST API specs — `CapacityPool.tsp` (TypeSpec) — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/CapacityPool.tsp (받을 때 `main` 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`). 사본: `sources/spec/CapacityPool.tsp`
- [2] Azure REST API specs — `stable/2026-08-01/netapp.json` (OpenAPI; capacityPools 경로, `CapacityPool`, `PoolProperties`, `CapacityPoolPatch`, `PoolPatchProperties`, `CapacityPoolList`) — 같은 커밋. 사본: `sources/spec/netapp-2026-08-01.json`
- [3] Azure REST API specs — `stable/2026-08-01/examples/` 중 `Pools_CreateOrUpdate.json`, `Pools_CreateOrUpdate_CustomThroughput.json`, `Pools_Delete.json`, `Pools_Get.json`, `Pools_Get_CustomThroughput.json`, `Pools_List.json`, `Pools_Update.json`, `Pools_Update_CustomThroughput.json`, `Volumes_PoolChange.json` — 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`. 사본: `sources/spec/examples/`
- [4] Microsoft Learn — Service levels for Azure NetApp Files (ms.date 2026-02-02) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-service-levels
- [5] Microsoft Learn — Manage a manual QoS capacity pool (ms.date 2025-03-24) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/manage-manual-qos-capacity-pool
- [15] Microsoft Learn — Create a capacity pool for Azure NetApp Files (ms.date 2025-10-02) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-set-up-capacity-pool
- [6] Microsoft Learn — Storage hierarchy of Azure NetApp Files (ms.date 2026-02-04) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-understand-storage-hierarchy
- [6.1] Microsoft Learn — Resize a capacity pool or a volume (ms.date 2025-05-20) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-resize-capacity-pools-or-volumes
- [7] Microsoft Learn — Resource limits for Azure NetApp Files (ms.date 2026-10-14) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-resource-limits
- [8] Microsoft Learn — Troubleshoot Azure NetApp Files Resource Provider errors (ms.date 2025-08-15) — 계정 조사 사본 재사용: `_workspace/netapp-account/sources/arm-rpc/anf-rp-errors.{html,txt}`
- [9] Microsoft Learn — Dynamically change the service level of a volume (ms.date 2026-09-15) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/dynamic-change-volume-service-level
- [10] Microsoft Learn — Troubleshoot capacity pool errors (ms.date 2025-05-18) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/troubleshoot-capacity-pools
- [11] Microsoft Learn — Cost model for Azure NetApp Files (ms.date 2026-06-15) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-cost-model
- [12] Microsoft Learn — Performance considerations for Azure NetApp Files (ms.date 2026-10-14) — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-performance-considerations
- [13] NetApp KB — SCSQL Clone Failure due to Capacity Pool Size — https://kb.netapp.com/data-mgmt/SnapCenter/SC_KBs/SCSQL_Clone_Failure_due_to_Capacity_Pool_Size (로그인 필요. 웹 검색 요약의 메시지 인용만 썼다. 원문 미확인)
- [14] NetApp ONTAP — Adaptive QoS policy groups — https://docs.netapp.com/us-en/ontap/performance-admin/adaptive-qos-policy-groups-task.html , KB "What is Adaptive QoS and how does it work" — https://kb.netapp.com/onprem/ontap/Performance/What_is_Adaptive_QoS_and_how_does_it_work (웹 검색 요약만, 원문 미확인)
- [R] 녹화 (계정 브리프 출처 [21]·[27] 재사용): .NET 태그 `net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c`, Python 태그 `python/netapp/azure-mgmt-netapp_c350090f50`. 사본: `_workspace/netapp-account/sources/recordings/{net,py}/`. 이번에 읽은 파일은 맨 위 N1~N6, P1~P2.
- Learn 문서 사본(HTML과 변환한 텍스트): `_workspace/capacity-pool/sources/docs/`

## 변경 이력

- 2026-11-07: 처음 작성했다. 골격을 먼저 저장한 뒤 필수 질문 7개를 채웠다.
