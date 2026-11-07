# NetApp 계정 (netapp-account) 조사 브리프

- 조사일: 2026-11-07
- 기준 api-version: `2026-08-01`. 이 버전이 최신 stable이다 [스펙 2]. 최신 preview는 `2026-08-15-preview`다 [스펙 2]. 아래 녹화 R1~R4는 모두 `2026-08-15-preview`로 호출됐다 [추론] (근거: 녹화 R1~R4의 RequestUri).
- 범위 가정: 요청받은 범위대로 생성, 조회, 목록, 수정(PATCH), 삭제, 부모·자식 관계, 자식이 남았을 때의 삭제를 조사했다. Active Directory 연결과 암호화(CMK)는 이름과 존재만 적었다. 요청에 언급되지 않은 다른 계정 속성(`nfsV4IDDomain`, `disableShowmount`, `ldapConfiguration` 등)도 조사자가 판단해 같은 수준으로만 다뤘다.
- 근거 표시 보충: 실제 서비스 응답을 녹화한 자료(Azure SDK for .NET 테스트 세션 녹화, 출처 [21])는 스킬의 네 가지 표시 어디에도 딱 맞지 않는다. 그래서 `[추론]`으로 표시하고 괄호 안에 "녹화 Rn"이라고 적었다. 이 자료는 실제 Azure가 돌려준 응답이므로 일반적인 추론보다 강한 근거다. 다만 Microsoft가 문서로 보장한 동작은 아니다.
  - R1 = `NetAppAccountTests/CreateDeleteNetAppAccountAsync.json` (westus2, 2026-10-29)
  - R2 = `NetAppAccountTests/UpdateNetAppAccountAsync.json`
  - R3 = `NetAppAccountTests/UpdateNetAppAccountWithPutAsync.json`
  - R4 = `PoolTests/DeleteAccountWithPoolPresentAsync.json`

## 요약 (5줄 이내)

1. NetApp 계정은 리전 하나에 묶인 관리용 묶음이며 ARM 추적 리소스 `Microsoft.NetApp/netAppAccounts`다 [문서 10][스펙 1]. 용량 풀, 스냅샷 정책, 백업 정책, 백업 볼트, 볼륨 그룹의 부모다 [스펙 5].
2. PUT, PATCH, DELETE는 모두 LRO로 정의돼 있다 [스펙 3]. PUT은 201과 `Azure-AsyncOperation`을 돌려준다. PATCH는 200이나 202와 `Location`을, DELETE는 202와 `Location` 또는 204를 돌려준다 [스펙 3].
3. 용량 풀이 남아 있는 계정을 DELETE하면 즉시 409 `CannotDeleteResource`가 돌아오고 풀은 그대로 남는다 [추론] (녹화 R4). 이 거절은 ARM 게이트웨이에서 나왔다 [추론] (녹화 R4의 `x-ms-failure-cause: gateway` 헤더).
4. 계정을 만들거나 지워도 데이터 플레인에 직접 보이는 변화는 없다 [추론] (계정에는 볼륨이 없다 — 문서 10). 계정 수준 설정(AD, CMK, NFSv4 ID 도메인)이 나중에 볼륨에 간접적으로 영향을 준다 [문서 16, 17, 18].
5. ANF 계정과 1:1로 대응하는 ONTAP 객체는 공개된 자료에서 찾지 못했다 [미확인]. 계정에 담긴 설정은 ONTAP SVM 수준의 설정과 닮았지만, 둘을 대응시키는 것은 추론이다 [추론].

## 사용자에게 보이는 동작

### 리소스와 API

**ARM 리소스 경로** [스펙 3]
- 단건: `/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.NetApp/netAppAccounts/{accountName}`
- 리소스 그룹 목록(`Accounts_List`): `/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.NetApp/netAppAccounts`
- 구독 목록(`Accounts_ListBySubscription`): `/subscriptions/{subscriptionId}/providers/Microsoft.NetApp/netAppAccounts`
- `accountName` 패턴은 `^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,127}$`이고 minLength/maxLength는 따로 없다 [스펙 3, 8]. 이 패턴은 영숫자로 시작하고 영숫자, `-`, `_`만 쓰는 1~128자 이름을 뜻한다 [스펙 3].
- `resourceGroupName`은 1~90자다 [스펙 8].

**작업별 요청·응답** (2026-08-01)

| operationId | 메서드 | 성공 응답 | 응답 헤더 | LRO 설정 | 근거 |
| --- | --- | --- | --- | --- | --- |
| `Accounts_Get` | GET | 200 `NetAppAccount` | 없음 | 없음 | [스펙 3] |
| `Accounts_CreateOrUpdate` | PUT | 200(갱신), 201(생성) | 201에 `Azure-AsyncOperation`, `Retry-After` | `final-state-via: azure-async-operation` | [스펙 3] |
| `Accounts_Update` | PATCH | 200, 202 (둘 다 `NetAppAccount` 본문) | 202에 `Location`, `Retry-After` | `final-state-via: location` | [스펙 3] |
| `Accounts_Delete` | DELETE | 202(삭제 수락), 204("Resource does not exist") | 202에 `Location`, `Retry-After` | `final-state-via: location` | [스펙 3, 8] |
| `Accounts_List`, `Accounts_ListBySubscription` | GET | 200 `NetAppAccountList` | 없음 | 없음 | [스펙 3] |

- 실패 응답은 모두 `default: ErrorResponse`다 [스펙 3].
- `NetAppAccountList`는 `value`(필수, 배열)와 `nextLink`(URI)로 이뤄진다 [스펙 3].

**`NetAppAccount` 본문의 속성** (2026-08-01)
- 최상위 속성:
  - `id`, `name`, `type`, `systemData`는 읽기 전용이다 [스펙 7].
  - `location`은 필수이고, `x-ms-mutability`가 `read`, `create`라서 생성 뒤 바꿀 수 없다 [스펙 7].
  - `tags`의 `x-ms-mutability`는 `read`, `create`, `update`다 [스펙 7].
  - `etag`는 읽기 전용 문자열이다 [스펙 3].
  - `identity`는 쓸 수 있는 `ManagedServiceIdentity`(common-types v6)다 [스펙 3].
  - `properties`의 타입은 `AccountProperties`다 [스펙 3].
- `properties`(`AccountProperties`)의 속성 [스펙 3]:
  - `provisioningState`: 읽기 전용 문자열이며 enum이 없다.
  - `activeDirectories[]`: AD 연결 배열이다. 이번 범위에서는 미룬다.
  - `encryption`(`AccountEncryption`): `keySource`의 기본값은 `"Microsoft.NetApp"`이고, enum은 `Microsoft.NetApp`, `Microsoft.KeyVault`다. 그 밖에 `keyVaultProperties`, `identity`가 있다. 이번 범위에서는 미룬다.
  - `disableShowmount`: 읽기 전용이고 null을 허용하는 boolean이다. 설명은 "Shows the status of disableShowmount for all volumes under the subscription, null equals false"다.
  - `nfsV4IDDomain`: null을 허용한다. 설명은 "This property will be set for all NetApp accounts in the subscription and region"이다.
  - `multiAdStatus`: 읽기 전용이며 `Disabled` 또는 `Enabled`다.
  - `ldapConfiguration`
- `entraIdConfig`는 preview api-version에만 있고 2026-08-01 stable에는 없다 [스펙 1].
- 필수 속성은 `location` 하나다. `TrackedResource`가 `required: ["location"]`이고 [스펙 7], `NetAppAccount` 자체에는 required 목록이 없다 [스펙 3].
- 최소 생성 요청은 스펙 예시에서 `{"location": "eastus", "properties": {}}`다 [스펙 4]. SDK 녹화는 `properties` 없이 `{"tags": {...}, "location": "westus2"}`만 보내서 생성에 성공했다 [추론] (녹화 R1).
- 요청에 넣지 않은 값도 생성 뒤 GET 응답에 채워져 나왔다. `properties.encryption.keySource: "Microsoft.NetApp"`와 `properties.multiADStatus: "Enabled"`였다 [추론] (녹화 R1).
  - **속성 이름 표기 충돌:** 스펙은 `multiAdStatus`라고 쓴다 [스펙 3]. 녹화의 실제 응답은 `multiADStatus`라고 쓴다 [추론] (녹화 R1). 두 표기를 모두 기록해 둔다.
- `etag`는 `W/"datetime'2026-10-29T22%3A05%3A07.5231979Z'"` 같은 약한 ETag였고, `ETag` 응답 헤더에도 같은 값이 들어 있었다 [추론] (녹화 R1). 생성 직후 PUT 응답의 etag와 완료 뒤 GET의 etag가 달랐다 [추론] (녹화 R1).
- 요청에서 `If-Match`를 지원하는지는 확인하지 못했다 [미확인] (찾아본 곳: 스펙 3의 경로 정의 요약, REST 문서 8의 URI 파라미터 표. 둘 다 `If-Match`를 언급하지 않는다).
- 녹화 응답의 tags에는 요청에 없던 `CreatedOnDate` 태그가 들어 있었다 [추론] (녹화 R1~R3). 이 태그 값은 PATCH 때마다 새 시각으로 바뀌었다 [추론] (녹화 R2). 그래서 ANF가 붙인 것이 아니라 테스트 구독의 Azure Policy가 붙인 것으로 보인다 [추론]. 재현할 대상이 아니다.

**PATCH 본문** (`NetAppAccountPatch`, 2026-08-01)
- PATCH 본문에는 `tags`, `identity`, `properties`(`AccountPropertiesPatch`)를 넣을 수 있다 [스펙 3]. `location`, `id`, `name`, `type`은 없다 [스펙 3].
- `AccountPropertiesPatch`에 들어가는 속성은 `activeDirectories`, `encryption`, `nfsV4IDDomain`, `ldapConfiguration`뿐이다 [스펙 1, 3]. 읽기 전용인 `provisioningState`, `disableShowmount`, `multiAdStatus`는 빠져 있다 [스펙 1].
- 이전 stable 버전(2026-03-01~2026-06-01)의 `NetAppAccountPatchStable`에는 `location`, `id`, `name`, `type`도 있었다 [스펙 1]. 이처럼 버전마다 PATCH 모델이 다르다.
- **tags를 PATCH하면 맵 전체가 바뀐다.** 생성 때 tags가 `{key1, key2}`였던 계정에 `{"tags": {"Tag2": "value2"}}`를 PATCH하자, 응답과 이후 GET의 사용자 태그가 `{Tag2}` 하나만 남았다 [추론] (녹화 R2).
- 스펙 예시 `Accounts_Update`의 200 응답 본문에는 `tags`가 빠져 있어서, 예시만으로는 tags가 반영됐는지 확인할 수 없다 [스펙 4].

**PUT으로 기존 계정 갱신**
- 이미 있는 이름에 PUT하면 200이 돌아온다 [스펙 3]. 녹화에서 SDK는 기존 tags 전체와 새 태그, `properties.encryption.keySource`를 모두 담아 PUT했다 [추론] (녹화 R3).

**이름 사용 가능 여부 확인** (참고, 이번 범위 밖)
- `POST /subscriptions/{sub}/providers/Microsoft.NetApp/locations/{location}/checkNameAvailability`가 있다. 본문은 `{name, type: "Microsoft.NetApp/netAppAccounts", resourceGroup}`이고 세 필드 모두 필수다. 응답은 `{"isAvailable": true}` 형태다 [스펙 3, 4].
- SDK 테스트는 계정을 만들기 전에 이 API를 호출했다 [추론] (녹화 R1~R3).

**계정에 딸린 POST 액션** (2026-08-01 예시 파일 기준. 모두 CMK, AD/LDAP, 백업 관련이라 미룬다)
- `renewCredentials`, `transitiontocmk`(예시명 `Accounts_TransitionEncryptionKey`), `getKeyVaultStatus`(예시명 `Accounts_GetChangeKeyVaultInformation`), `changeKeyVault`, `refreshLdapBindPassword`, `migrateBackups`(예시명 `BackupsUnderAccount_Migrate`)가 있다 [스펙 1, 4].

**az CLI (사용자 관점)**
- 기본 명령은 `az netappfiles account create|show|list|update|delete|wait`이고, 그 밖에 `ad` 하위 그룹(add/list/remove/show/update), `identity`, `quota-limit`, `renew-credentials`, `transitiontocmk`, `change-key-vault`, `migrate-backup` 등이 있다 [문서 15].
- `create`의 필수 인자는 `--name`과 `--resource-group`이다. `--location`을 생략하면 리소스 그룹의 위치를 쓴다 [문서 15].
- `list`에 `-g`를 주지 않으면 구독 전체를 나열한다 [문서 15].
- `wait --deleted`로 삭제가 끝날 때까지 기다릴 수 있다 [문서 15].
- 포털에서 계정을 만들 때는 이름, 구독, 리소스 그룹, 위치, Service tier(`Other` 또는 `Zone redundant`)를 입력한다 [문서 9].

**부모·자식 관계**
- `@parentResource(NetAppAccount)`를 가진 자식 리소스 타입은 다섯 가지다 [스펙 5]:
  - `capacityPools`(TrackedResource)
  - `snapshotPolicies`(TrackedResource)
  - `backupPolicies`(TrackedResource)
  - `backupVaults`(TrackedResource)
  - `volumeGroups`(ProxyResource)
- 볼륨은 `capacityPools/{poolName}/volumes/{volumeName}` 아래에 있다. 그래서 계정 → 용량 풀 → 볼륨 순서로 중첩된다 [스펙 3].
- 계정은 리전 범위다. 한 리전에 계정을 여러 개 둘 수 있지만, 계정 하나는 리전 하나에만 묶인다 [문서 10].
- 용량 풀은 계정 하나에만 속하고, 다른 계정으로 옮길 수 없다 [문서 10].
- 볼륨이 남아 있는 용량 풀은 삭제할 수 없다 [문서 10].
- ANF는 리소스를 다른 구독으로 옮기는 것을 지원하지 않는다 [문서 10].
- 문서에는 "NetApp accounts must be dedicated to a service level."라는 문장이 있다 [문서 10]. 하지만 2026-08-01 `NetAppAccount` 스펙에는 서비스 수준 속성이 없다 [스펙 3]. 이 문장은 포털의 Service tier "Zone redundant" [문서 9] 및 preview 전용 리소스 `elasticAccounts` [스펙 6]와 관련된 것으로 보인다 [추론]. 두 내용을 모두 기록해 둔다.

### 비동기 동작

**스펙이 정한 패턴** [스펙 3]
- PUT은 `Azure-AsyncOperation` 헤더로 상태를 폴링하고 `final-state-via: azure-async-operation`을 쓴다.
- PATCH와 DELETE는 `Location` 헤더로 폴링하고 `final-state-via: location`을 쓴다.

**스펙 예시** [스펙 4]
- PUT 201 응답 본문의 `provisioningState`는 `"Creating"`, 200 응답은 `"Succeeded"`다.
- PATCH 202 응답 본문의 `provisioningState`는 `"Patching"`이다. `Location` 헤더는 `.../providers/Microsoft.NetApp/locations/eastus/operationResults/{id}?api-version=...&operationResultResponseType=Location`이다.
- DELETE 202는 본문 없이 `Location` 헤더만 있다.
- 2026-08-01 예시의 `Location` URL에는 `api-version=2026-06-15-preview`가 들어 있다 [스펙 4]. 예시끼리 버전이 맞지 않는 사소한 문제다.

**실서비스 녹화에서 관찰한 것**

| 작업 | 상태 코드 | 본문 `provisioningState` | LRO 헤더 | 완료 방식 | 근거 |
| --- | --- | --- | --- | --- | --- |
| PUT 생성 | 201 | `Creating` | `Azure-AsyncOperation`만 있음 (`Location`, `Retry-After` 없음) | 상태 조회 1회에 `Succeeded` | [추론] (녹화 R1) |
| PUT 갱신 (기존 계정) | 200 | `Updating` | `Azure-AsyncOperation` 있음 | 상태 조회 1회에 `Succeeded` | [추론] (녹화 R3) |
| PATCH (tags만) | 200 | `Succeeded` | 없음 | 동기 완료, 폴링 없음 | [추론] (녹화 R2) |
| DELETE | 202 | 본문 없음 | `Azure-AsyncOperation`과 `Location` 둘 다 있음 (`Retry-After` 없음) | 상태 조회 1회에 `Succeeded`, 이후 GET 404 | [추론] (녹화 R1) |

- 상태 조회 응답의 형식은 `{id, name, status: "Succeeded", startTime, endTime, percentComplete: 100.0, properties: {action: "CREATE"|"DELETE", resourceName}}`였다 [추론] (녹화 R1).
  - 상태 조회 URL은 `/subscriptions/{sub}/providers/Microsoft.NetApp/locations/{location}/operationResults/{operationId}`처럼 리전 단위 경로였다 [추론] (녹화 R1. 스펙 예시 4의 Location 헤더도 같은 경로다).
  - 계정 생성 작업은 startTime부터 endTime까지 약 70ms 걸렸다 [추론] (녹화 R1).
- **스펙과 녹화가 다른 점:**
  - 스펙은 PUT 200 응답에 헤더를 정의하지 않는다 [스펙 3]. 그런데 실제 서비스는 갱신 PUT에 200, `Updating`, `Azure-AsyncOperation`을 돌려줬다 [추론] (녹화 R3). 200이어도 작업이 끝나지 않았을 수 있다는 뜻이다.
  - PATCH는 스펙 예시가 202와 `Patching`을 보여 준다 [스펙 4]. 녹화에서는 tags만 바꾼 PATCH가 200으로 동기 완료됐다 [추론] (녹화 R2). 스펙은 200과 202를 모두 허용한다 [스펙 3].
  - 스펙에는 DELETE 202의 헤더로 `Location`만 있다 [스펙 3]. 녹화에는 `Azure-AsyncOperation`도 함께 있었다 [추론] (녹화 R1).

**provisioningState 값과 전이**
- 스펙에는 enum이 없고 타입만 문자열이다 [스펙 3].
- 확인한 값은 `Creating`, `Succeeded` [스펙 4][녹화 R1], `Updating` [추론] (녹화 R3), `Patching` [스펙 4]이다.
- 관찰된 전이는 다음과 같다 [추론] (근거: 예시 4와 녹화 R1~R3).
  - 생성: `Creating` → `Succeeded`
  - PUT 갱신: `Updating` → `Succeeded`
  - PATCH: `Patching` → `Succeeded`, 또는 즉시 `Succeeded`
- `Deleting`, `Failed` 값이 있는지, 실패했을 때 어떻게 전이하는지는 확인하지 못했다 [미확인] (찾아본 곳: 스펙 3의 AccountProperties, 예시 4, 녹화 R1. 녹화 R1에는 삭제 중에 GET한 기록이 없다).

### 제약과 한도
- 구독 하나에 리전마다 NetApp 계정을 기본 100개까지 만들 수 있다. 지원 요청으로 늘릴 수 있다 [문서 11].
- 계정 하나에 용량 풀을 기본 100개까지 만들 수 있고, 이 한도도 늘릴 수 있다 [문서 11]. CLI 문서는 계정 수준 quota limit이 "Currently PoolsPerAccount is the only one"이라고 적는다 [문서 15].
- 한도를 넘으면 다음 메시지가 나온다 [문서 12]. HTTP 상태 코드는 확인하지 못했다 [미확인] (찾아본 곳: 문서 12).
  > "Creating the resource of type {resourceType} would exceed the quota of {quota} resources of type {resourceType} per {parentResourceType}. The current resource count is {currentCount}, please delete some resources of this type before creating a new one."
- 계정 이름은 위의 패턴(1~128자)을 따라야 한다 [스펙 3].
- `location`은 생성 뒤 바꿀 수 없다 [스펙 7].
- 계정을 만들려면 먼저 구독을 `Microsoft.NetApp` 리소스 공급자에 등록해야 한다 [문서 9, 14].
- AD 연결은 계정당 1개만 둘 수 있다 [문서 17]. (이번 범위에서는 미룬다.)

### 오류 상황

| 상황 | HTTP | 코드·메시지 | 근거 |
| --- | --- | --- | --- |
| 자식(용량 풀)이 남아 있는 계정을 DELETE | 409 | `CannotDeleteResource`. 메시지: "Cannot delete resource while nested resources exist. Some existing nested resource IDs include: 'Microsoft.NetApp/netAppAccounts/account9829/capacityPools/pool-792'. Please delete all nested resources before deleting this resource." 응답 헤더에 `x-ms-failure-cause: gateway`가 있다. 비동기 작업이 아니라 즉시 거절된다. | [추론] (녹화 R4. SDK 테스트 `DeleteAccountWithPoolPresent`도 409와 "풀이 그대로 남아 있음"을 단언한다 — 출처 20) |
| 위 409 뒤 풀을 지우고 다시 계정을 DELETE | 202 | 작업이 `Succeeded`로 끝난다 | [추론] (녹화 R4) |
| 존재하지 않는 계정을 GET | 404 | `ResourceNotFound`. 메시지: "The resource with identifier '/subscriptions/.../netAppAccounts/{name}' is not found." | [추론] (녹화 R1. SDK 테스트도 404를 단언한다 — 출처 20) |
| 존재하지 않는 계정을 DELETE | 204 | 본문 없음 | [스펙 3, 8] |
| 계정 수 한도 초과 | 미확인 | 위 "제약과 한도"의 메시지 | [문서 12] |
| 리소스 공급자 미등록 | — | 배포 오류 `DeploymentFailed` 안에 `InvalidResourceType`("The resource type could not be found in the namespace 'Microsoft.NetApp' for api version ...")가 들어 있다. 같은 원인으로 "Creation of `netAppAccounts` has been restricted in this region."도 나온다 | [문서 9, 12] |
| 이름이 너무 길거나 짧음 | 미확인 | 일반 메시지 "Name too long." / "Name too short." | [문서 12] (계정에 대해 실제 상태 코드·코드값은 [미확인]) |
| 읽기 전용 속성에 값을 보냄 | 미확인 | "Received a value for read-only property '{propertyName}'." | [문서 12] |
| 모르는 속성을 보냄 | 미확인 | "Value received for an unknown property '{propertyName}'." | [문서 12] |
| 본문의 name이 URL의 이름과 다름 | 미확인 | "The {resourceType} name must be the same as the resource identifier name." | [문서 12] |
| 잘못된 api-version | 미확인 | "Invalid api-version." | [문서 12] |
| 처리되지 않은 예외 | 미확인 | "Error {action} {resourceTypeName}" (예: action=`deleting`, resourceTypeName=`netAppAccount`) | [문서 12] |
| 기존 계정에 다른 location으로 PUT | 미확인 | 스펙상 location은 바꿀 수 없다 [스펙 7]. 실제 오류 코드는 찾지 못했다 | [미확인] (찾아본 곳: 문서 12, 스펙 3) |

- 오류 본문 형식은 `{"error": {"code", "message", "target", "details": [...], "additionalInfo": [...]}}`(ErrorResponse)다 [스펙 8].
- 409 거절과 ARM의 관계:
  - 409에 붙은 `x-ms-failure-cause: gateway` 헤더로 보면, 이 거절은 ANF 리소스 공급자가 아니라 ARM 프런트(게이트웨이)가 중첩 리소스를 검사해서 낸 것으로 보인다 [추론] (근거: 녹화 R4의 헤더, 그리고 용량 풀이 ARM이 추적하는 TrackedResource라는 점 — 스펙 5).
  - Learn의 ANF 문서와 REST 문서에서 "자식이 있으면 계정을 삭제할 수 없다"는 문장은 찾지 못했다 [미확인] (찾아본 곳: 문서 8 Accounts-Delete, 문서 10 저장소 계층, 문서 12 RP 오류, 문서 13 용량 풀 오류, 문서 14 퀵스타트 정리 절차, 웹 검색 4회).
  - ProxyResource인 `volumeGroups`만 남아 있을 때도 계정 삭제가 막히는지는 확인하지 못했다 [미확인] (찾아본 곳: 녹화와 문서. R4는 용량 풀 경우만 다룬다).
- 리소스 그룹을 통째로 지우는 것은 다른 경로다. ARM은 중첩된 자식 리소스를 먼저 지운 뒤 나머지를 지우므로 [문서 19], 계정과 풀을 담은 리소스 그룹은 한 번에 지워질 것으로 보인다 [추론] (근거: 문서 19의 삭제 순서와 퀵스타트의 정리 절차 — 문서 14).
- AD와 관련된 오류("Only one active directory allowed", "Active Directory credentials are in use" 등)는 미룬다 [문서 12].

## 데이터 플레인에서 보이는 효과

- 계정을 생성, 수정, 삭제하기만 해서는 클라이언트가 마운트로 관찰할 수 있는 변화가 없다 [추론] (근거: 계정은 용량 풀을 묶는 관리 단위이고 볼륨은 용량 풀 아래에만 만들어진다 — 문서 10, 스펙 3).
- 계정 수준 설정의 간접 효과(이번 범위 밖, 나중 기능의 검증 소재):
  - `nfsV4IDDomain`
    - 같은 구독·리전의 모든 NetApp 계정에 걸쳐, LDAP을 쓰지 않는 NFSv4.1 볼륨의 ID 도메인을 정한다 [문서 16].
    - 기본값은 `defaultv4iddomain.com`이다 [문서 16].
    - 클라이언트 `/etc/idmapd.conf`의 `Domain`과 다르면 파일 소유자가 `nobody`로 보인다 [문서 16].
  - AD 연결은 SMB 볼륨, 이중 프로토콜 볼륨, NFSv4.1 Kerberos 볼륨을 만들기 위한 전제다 [문서 17].
  - CMK
    - ANF는 계정 암호화 키(account encryption key)를 Key Vault의 고객 관리 키로 감싼다 [문서 18].
    - Key Vault에 접근할 수 없게 되면 CMK 볼륨을 읽거나 쓸 수 없다 [문서 18].
  - `disableShowmount`는 구독 아래 모든 볼륨의 showmount 상태를 보여 주는 읽기 전용 값이다 [스펙 3].

## ONTAP 대응 개념

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| NetApp 계정 | 직접 대응하는 객체 없음. 가장 가까운 것은 SVM(Storage VM, vserver) | 계정은 Azure 쪽의 관리 묶음이다 [문서 10]. ONTAP의 SVM은 볼륨, LIF, 프로토콜 설정을 담는 논리 스토리지 서버이자 멀티테넌시 단위다 [문서 22 — docs.netapp.com 403, 원문 미확인·검색 요약]. ANF가 계정을 ONTAP 객체로 어떻게 구현하는지는 공개 자료에서 찾지 못했다. | 대응 관계 [미확인] |
| (계정 ≠ SVM 1:1로 보이는 단서) | — | `nfsV4IDDomain`은 계정이 아니라 구독·리전 범위다 [문서 16][스펙 3]. 과거의 Shared AD는 구독·리전 단위로 AD 설정 하나를 공유했다 [문서 17]. AD 연결 하나로 AD 컴퓨터 계정을 "필요에 따라" 더 만든다 [문서 17]. CMK 전환은 계정이 볼륨을 가진 VNet마다 따로 해야 한다 [문서 18]. 이 단서들로 보면 백엔드의 ONTAP 테넌시(SVM)는 계정이 아니라 구독·리전·VNet 기준으로 나뉘는 것 같다. | [추론] |
| ANF 백엔드의 스토리지 VM | SVM | CMK 문서는 볼륨의 위임 서브넷 NSG가 "NetApp's storage VM"에서 들어오는 트래픽을 허용해야 한다고 쓴다 [문서 18]. 이 스토리지 VM이 계정과 몇 대 몇으로 대응하는지는 공개되지 않았다. | 존재 [문서 18], 수 대응 [미확인] |
| 계정의 AD 연결(`activeDirectories`) | SVM의 CIFS(SMB) 서버 (`vserver cifs create`로 AD에 가입하면 AD에 컴퓨터 계정이 생긴다) | ANF는 계정당 AD 연결 1개를 두고, SMB 서버 이름 접두사로 AD 컴퓨터 계정을 만든다. 기본 OU는 `CN=Computers`다 [문서 17][스펙 3]. ONTAP은 SVM당 CIFS 서버 1개를 두고, 기본 OU가 `CN=Computers`다 [문서 22 원문 미확인]. 구조가 닮았다. | 대응 [추론] |
| `nfsV4IDDomain` | `vserver nfs modify -v4-id-domain` | ANF의 기본값은 `defaultv4iddomain.com`이다 [문서 16]. ONTAP CLI 문서의 기본값도 같다는 검색 요약이 있다. 다만 다른 NetApp 페이지는 NIS/DNS 도메인으로 대체한다고 적는다는 요약도 있다 [문서 22 원문 미확인]. | 대응 [추론] |
| `disableShowmount` | `vserver nfs modify -showmount` (기본 enabled) | ONTAP 쪽 설명은 검색 요약이다 [문서 22 원문 미확인]. | 대응 [추론] |
| `encryption` (CMK) | ONTAP 볼륨 암호화(NVE/NAE)와 외부 키 관리자 | ANF 쪽은 계정 암호화 키를 CMK로 감싼다 [문서 18]. ONTAP 쪽 문서는 확인하지 않았다. | 대응 [추론], ONTAP 세부 [미확인] |
| 자식이 남아 있으면 부모 삭제 거절 | `vserver delete`: SVM에 볼륨이 있으면 먼저 수동으로 삭제해야 한다 | 동작이 닮았다는 점만 말할 수 있다. ANF에서는 ARM 게이트웨이가 거절했다 [추론] (녹화 R4). 이것을 계정 = SVM의 근거로 쓰면 안 된다. | ONTAP 쪽 [문서 22 원문 미확인], 유사성 [추론] |

## 구현 범위 후보

### 이번에 재현할 것 (후보 — 확정은 리더와 사용자가 한다)
1. **PUT 생성·교체.** 요청 본문은 `location` 필수, 선택적 `tags`, 빈 `properties`를 허용한다. 생성이면 201과 `Azure-AsyncOperation`, 기존 계정이면 200을 돌려준다. `provisioningState`는 `Creating` → `Succeeded`로 바뀐다. 상태 조회 엔드포인트 `operationResults`도 필요하다.
   - 이유: CLAUDE.md가 확정한 "ARM LRO 스타일의 비동기 control plane"을 처음 구현하는 리소스다. 이후의 풀, 볼륨, 스냅샷이 같은 패턴을 다시 쓴다.
2. **GET 단건과 404 `ResourceNotFound`.**
   - 이유: 요청 범위다. 녹화로 확인한 오류 형식이 있다.
3. **목록 두 가지(리소스 그룹, 구독).** `{value, nextLink}` 형식이다.
   - 이유: 요청 범위다. 포털 대시보드에 목록이 필요하다.
4. **PATCH.** 대상은 tags다. tags 맵 전체를 바꾸고, 200 또는 202를 돌려준다.
   - 이유: 요청 범위다. 계정에서 AD/CMK를 빼면 PATCH로 바꿀 수 있는 것이 사실상 tags(와 identity)뿐이다 [스펙 3].
5. **DELETE.** 202와 `Location`(실서비스는 `Azure-AsyncOperation`도 함께)을 돌려주고, 없는 계정이면 204, 삭제가 끝나면 GET 404다.
   - 이유: 요청 범위다.
6. **자식이 남아 있으면 409 `CannotDeleteResource`.**
   - 이유: 요청 범위다. 다만 지금은 자식(용량 풀)이 아직 구현되지 않았다. 검사 자리만 먼저 둘지, 용량 풀 기능 때 함께 검증할지는 결정이 필요하다.
7. **입력 검증.** `accountName` 패턴과 `location` 불변을 검사한다.
   - 이유: 스펙에 명시된 제약이다.

### 다음으로 미룰 것
- **Active Directory 연결**(`properties.activeDirectories`, `az netappfiles account ad ...`, `multiAdStatus`).
  - 이유: AD DS가 필요하고 SMB, 이중 프로토콜, Kerberos 볼륨의 전제다 [문서 17]. 범위 지시에 따라 미룬다.
- **암호화·CMK**(`properties.encryption`의 `Microsoft.KeyVault`, `keyVaultProperties`, `identity`, POST `renewCredentials`, `transitiontocmk`, `getKeyVaultStatus`, `changeKeyVault`).
  - 이유: Key Vault, 관리 ID, 프라이빗 엔드포인트가 필요하다 [문서 18]. 범위 지시에 따라 미룬다.
- **관리 ID**(`identity`).
  - 이유: 주로 CMK에 쓰인다 [문서 18].
- **`nfsV4IDDomain`, `disableShowmount`.**
  - 이유: NFSv4.1 볼륨이 생긴 뒤에야 효과를 관찰할 수 있다. 적용 범위가 계정이 아니라 구독·리전이라 따로 모델링을 정해야 한다 [문서 16][스펙 3].
- **`ldapConfiguration`, `refreshLdapBindPassword`, `entraIdConfig`**(`entraIdConfig`는 preview 전용).
  - 이유: LDAP/디렉터리 기능과 함께 다룬다 [스펙 1].
- **`migrateBackups`와 자식 `backupPolicies`, `backupVaults`, `snapshotPolicies`, `volumeGroups`.**
  - 이유: 각자 별도 기능이다 [스펙 5].
- **`checkNameAvailability`, 계정 수준 `quotaLimits`, 리전당 계정 100개 한도.**
  - 이유: 기본 CRUD에 꼭 필요하지 않다 [스펙 3][문서 11].
- **`elasticAccounts`**(포털의 "Zone redundant" 서비스 등급으로 보이는 preview 전용 별도 리소스).
  - 이유: stable API에 없다 [스펙 6].
- **ETag와 `If-Match` 동시성 제어.**
  - 이유: 실서비스가 etag를 돌려주지만 [추론] (녹화 R1), 요청 쪽 지원 여부가 [미확인]이다.

### 리더·사용자가 정해야 할 선택지 (조사에서 드러난 것. 조사자는 정하지 않는다)
- **경로 형식:** 경로에 `subscriptionId`와 `resourceGroupName`을 ARM 그대로 둘지 정해야 한다. CLAUDE.md는 Azure 쪽 개념을 필요할 때만 넣으라고 한다.
- **백엔드에 만들 것:** 계정을 만들 때 백엔드(Linux 또는 ONTAP Simulator)에 무엇을 만들지 정해야 한다. 실제 ANF의 대응 관계는 공개되지 않았다 [미확인]. "아무것도 만들지 않는다"도 실제 서비스와 어긋나지 않는 선택지다 [추론].
- **PATCH 응답 방식:** PATCH를 동기 200으로 할지 비동기 202로 할지 정해야 한다. 실서비스는 두 경우를 모두 보여 줬다 [스펙 4][추론] (녹화 R2).
- **PUT 갱신 응답:** 실서비스처럼 200, `Updating`, `Azure-AsyncOperation`을 돌려줄지 [추론] (녹화 R3), 스펙의 단순한 200을 따를지 정해야 한다.
- **409 검사의 위치:** 중첩 리소스 검사를 "게이트웨이" 계층에 둘지 리소스 공급자 계층에 둘지 정해야 한다. 실서비스에서는 게이트웨이가 거절했다 [추론] (녹화 R4). 설계 설명(면접)과 연결되는 지점이다.

### 검증 기준 후보
계정은 데이터 플레인 효과가 없으므로 [추론], 기준은 REST 클라이언트가 관찰할 수 있는 응답으로 쓴다.
1. 새 계정을 PUT하면 201이 오고, 본문 `provisioningState`가 `Creating`이며, `Azure-AsyncOperation` 헤더가 있다. 그 URL을 폴링하면 `status`가 `Succeeded`가 되고, 이후 GET은 200과 `Succeeded`를 돌려준다.
2. 같은 이름으로 다시 PUT하면 201이 아니라 200이 온다.
3. 없는 이름을 GET하면 404와 `error.code == "ResourceNotFound"`가 온다.
4. 리소스 그룹 목록에는 만든 계정이 있고, 다른 리소스 그룹의 목록에는 없다. 구독 목록에는 있다.
5. tags가 `{a:1}`인 계정에 `PATCH {"tags": {"b": "2"}}`를 보낸 뒤 GET하면 tags가 정확히 `{b:2}`다.
6. 기존 계정에 다른 `location`으로 PUT하면 4xx로 거절된다 (실제 코드는 [미확인]이라 코드값까지는 고정하지 않는다).
7. 패턴을 어긴 이름(`-abc`, 129자 이름, `a.b`)으로 PUT하면 4xx가 온다.
8. DELETE하면 202와 `Location`이 온다. 폴링이 끝난 뒤 GET은 404다. 같은 이름을 다시 DELETE하면 204가 온다.
9. (용량 풀을 구현한 뒤) 풀이 있는 계정을 DELETE하면 409 `CannotDeleteResource`가 오고, 메시지에 풀의 리소스 ID가 들어 있으며, 풀 GET은 여전히 200이다. 풀을 지운 뒤 계정을 DELETE하면 202가 온다.
10. 계정을 만들기 전과 지운 뒤 백엔드의 NFS export 목록(예: 서버의 `exportfs -v` 또는 클라이언트의 `showmount -e`)이 바뀌지 않는다. 계정 자체가 데이터 플레인을 건드리지 않는다는 확인이다.

## 출처

확인일은 모두 2026-11-07이다.

- [1] Azure REST API specs — `NetAppAccount.tsp` (TypeSpec) — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/NetAppAccount.tsp
- [2] Azure REST API specs — `main.tsp` (Versions enum) — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/main.tsp , stable 목록 https://api.github.com/repos/Azure/azure-rest-api-specs/contents/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/stable
- [3] Azure REST API specs — `stable/2026-08-01/netapp.json` (OpenAPI) — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/stable/2026-08-01/netapp.json
- [4] Azure REST API specs — `stable/2026-08-01/examples/` 중 `Accounts_CreateOrUpdate.json`, `Accounts_Update.json`, `Accounts_Delete.json`, `Accounts_Get.json`, `Accounts_List.json`, `CheckNameAvailability.json`와 예시 파일 목록 — https://github.com/Azure/azure-rest-api-specs/tree/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/stable/2026-08-01/examples
- [5] Azure REST API specs — `CapacityPool.tsp`, `SnapshotPolicy.tsp`, `BackupPolicy.tsp`, `BackupVault.tsp`, `VolumeGroupDetails.tsp` — https://github.com/Azure/azure-rest-api-specs/tree/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp
- [6] Azure REST API specs — `Elastic/ElasticAccount.tsp` — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/Elastic/ElasticAccount.tsp
- [7] Azure REST API specs — common-types `resource-management/v6/types.json` (TrackedResource, Resource) — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/main/specification/common-types/resource-management/v6/types.json
- [8] Microsoft Learn REST — Accounts - Delete (2026-08-01) — https://learn.microsoft.com/en-us/rest/api/netapp/accounts/delete?view=rest-netapp-2026-08-01
- [9] Microsoft Learn — Create a NetApp account to access Azure NetApp Files — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-create-netapp-account
- [10] Microsoft Learn — Storage hierarchy of Azure NetApp Files — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-understand-storage-hierarchy
- [11] Microsoft Learn — Resource limits for Azure NetApp Files — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-resource-limits
- [12] Microsoft Learn — Troubleshoot Azure NetApp Files Resource Provider errors — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-troubleshoot-resource-provider-errors
- [13] Microsoft Learn — Troubleshoot capacity pool errors — https://learn.microsoft.com/en-us/azure/azure-netapp-files/troubleshoot-capacity-pools
- [14] Microsoft Learn — Quickstart: Set up Azure NetApp Files and NFS volume — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-quickstart-set-up-account-create-volumes
- [15] Microsoft Learn CLI — az netappfiles account — https://learn.microsoft.com/en-us/cli/azure/netappfiles/account
- [16] Microsoft Learn — Configure NFSv4.1 ID domain for Azure NetApp Files — https://learn.microsoft.com/en-us/azure/azure-netapp-files/azure-netapp-files-configure-nfsv41-domain
- [17] Microsoft Learn — Create and manage Active Directory connections for Azure NetApp Files — https://learn.microsoft.com/en-us/azure/azure-netapp-files/create-active-directory-connections
- [18] Microsoft Learn — Configure customer-managed keys for Azure NetApp Files volume encryption — https://learn.microsoft.com/en-us/azure/azure-netapp-files/configure-customer-managed-keys
- [19] Microsoft Learn — Delete resource groups and resources (Azure Resource Manager) — https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/delete-resource-group
- [20] Azure SDK for .NET — `Azure.ResourceManager.NetApp` 테스트 `PoolTests.cs`(`DeleteAccountWithPoolPresent`), `NetAppAccountTests.cs` — https://github.com/Azure/azure-sdk-for-net/tree/main/sdk/netapp/Azure.ResourceManager.NetApp/tests/ResourceTests
- [21] Azure SDK assets — 위 테스트의 세션 녹화. 태그는 `net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c`(`assets.json` 기준)다. R1~R4 경로는 `net/sdk/netapp/Azure.ResourceManager.NetApp/tests/SessionRecords/{NetAppAccountTests|PoolTests}/...` — https://github.com/Azure/azure-sdk-assets/tree/net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c/net/sdk/netapp/Azure.ResourceManager.NetApp/tests/SessionRecords
- [22] NetApp ONTAP 문서. WebFetch가 403으로 거절해서 원문은 확인하지 못했고, WebSearch 결과 요약만 썼다.
  - SVM 개념: https://docs.netapp.com/us-en/ontap/concepts/storage-virtualization-concept.html (403)
  - `vserver nfs modify`: https://docs.netapp.com/us-en/ontap-cli/vserver-nfs-modify.html (403)
  - `vserver cifs create`와 AD 가입: https://docs.netapp.com/us-en/ontap-cli/vserver-cifs-create.html , https://docs.netapp.com/us-en/ontap/smb-admin/join-svm-active-directory-domain-task.html
  - `vserver delete`: https://docs.netapp.com/us-en/ontap-cli-9131/vserver-delete.html

## 변경 이력

- 2026-11-07: 처음 작성했다.
