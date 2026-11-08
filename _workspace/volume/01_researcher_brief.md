# 볼륨 (volume, NFS) 조사 브리프

- 조사 상태: 한도 도달. 필수 질문 다섯 가지는 모두 답했다. 다만 ONTAP 쪽 세부 세 가지(REST `POST`의 원본 HTTP 응답, data LIF, 볼륨이 가득 찼을 때 NFS 오류 코드)와 클라이언트 `df` 표시는 실행 상한 때문에 확인하지 못했다. 이 항목들은 "미확인 목록"에 있다.
- 조사일: 2026-11-07
- 기준 api-version: `2026-08-01` (stable) [스펙 1, 2]. 녹화는 모두 `2026-08-15-preview`로 호출됐다 [녹화].
- 범위 가정: NFSv3·NFSv4.1 볼륨의 생성·조회·목록·PATCH·PUT 갱신·삭제와 실제 NFS export를 조사했다. 스냅샷, QoS 측정, export policy 세부, 크기 변경의 데이터 효과는 볼륨 리소스에 나타나는 속성 모양만 적었다. SMB, dual-protocol, backup, replication, volume group, large volume, 가용 영역은 존재만 적었다.
- 공통 LRO 규칙(작업 상태 본문, `Retry-After` 없음, 실패 작업 모양, 진행 중 작업 충돌)과 풀 규칙은 각각 계정 브리프와 풀 브리프에 있어 다시 쓰지 않았다.
- 녹화 표기. 모두 계정 조사 때 받은 사본이다 (`_workspace/netapp-account/sources/recordings/`).
  - V1 = `net/VolumeTests__CreateDeleteVolumeAsync.json` (westus2, 2026-10-31)
  - V2 = `net/VolumeTests__CreateVolumeWithProperties.json` (2026-10-30)
  - V3 = `net/VolumeTests__UpdateVolume.json` (2026-10-31, PATCH)
  - V4 = `py/test_volume.pyTestNetAppVolumetest_patch_volume.json` (2026-10-28)
  - V5 = `py/test_volume.pyTestNetAppVolumetest_update_volume.json` (2026-10-28, PUT 갱신)
  - V6 = `py/test_volume.pyTestNetAppVolumetest_external_migration_volume_fails.json` (2026-10-28, 409)
  - N5, N6 = 풀 브리프의 `DeletePooWithVolumePresentAsync`, `CreateVolumePoolNotFoundAsync`

## 요약 (5줄 이내)

1. 볼륨은 풀 아래의 ARM 추적 리소스 `.../capacityPools/{p}/volumes/{v}`이다. 필수 속성은 `creationToken`(파일 경로, 생성 뒤 불변), `usageThreshold`(바이트, 50 GiB~100 TiB, 1 GiB 배수), `subnetId`다 [스펙 2].
2. 실서비스 생성은 201 + `Creating` + `Azure-AsyncOperation`이고 `Succeeded`까지 약 5분 20초~5분 40초 걸렸다. PATCH는 202 + `Patching` 본문 + 두 헤더로 약 3초, DELETE는 202 + 두 헤더로 73초~106초였다 [녹화 V1, V3~V5].
3. 서비스가 채우는 기본값은 export 규칙 1개(`ruleIndex 1`, `allowedClients 0.0.0.0/0`, `unixReadWrite`, `hasRootAccess true`, 프로토콜 플래그는 `protocolTypes`를 따름), `protocolTypes ["NFSv3"]`, `unixPermissions "0770"`, `snapshotDirectoryVisible true`다. `mountTargets[0]`에는 `ipAddress`가 있고 `mountTargetId`는 `fileSystemId`와 같았다 [녹화 V1].
4. 할당량에 닿으면 볼륨이 자라지 않고 "out of space" 상태가 된다. 스냅샷이 쓰는 용량도 할당량에 포함된다 [문서 3, 4]. 마운트 경로는 `<마운트 대상 IP>:/<creationToken>`이다 [문서 5]. 클라이언트가 받는 errno(ENOSPC인지 EDQUOT인지)는 [미확인]이다.
5. ONTAP 대응: `creationToken`은 junction path, 볼륨은 FlexVol, `mountTargets.ipAddress`는 data LIF와 닮았다. 녹화의 `baremetalTenantId`에 `svm` 문자열이 들어 있다 [녹화 V1]. 그러나 ANF가 내부에서 ONTAP을 어떻게 쓰는지는 공개 자료가 없어 대응 관계는 모두 [추론]이다.

## 사용자에게 보이는 동작

### 리소스와 API (Q1)

**경로** [스펙 2]
- 단건: `/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.NetApp/netAppAccounts/{a}/capacityPools/{p}/volumes/{volumeName}`
- 목록(`Volumes_List`): 위 경로에서 `/{volumeName}`을 뺀 것이다. 응답은 `VolumeList`(`value` 필수, `nextLink`)다. 구독 범위나 계정 범위의 볼륨 목록 경로는 없다 [스펙 2]. 녹화에서는 빈 풀 목록이 `{"value": []}`였다 [녹화 V1].
- `volumeName`: 1~64자, 패턴 `^[a-zA-Z][a-zA-Z0-9\-_]{0,63}$`이다 [스펙 2]. 첫 글자는 영문자여야 한다. 풀 이름은 숫자로 시작할 수 있어 규칙이 다르다.
- 본문의 `name`은 `"{account}/{pool}/{volume}"`, `type`은 `"Microsoft.NetApp/netAppAccounts/capacityPools/volumes"`다 [스펙 3][녹화 V1].
- 볼륨은 풀의 구독, 리소스 그룹, location을 물려받는다 ("A volume inherits subscription, resource group, location attributes from its capacity pool.") [문서 1].

**작업별 계약** (2026-08-01) [스펙 2]

| operationId | 메서드 | 성공 응답 | 스펙의 응답 헤더 | LRO 설정 |
| --- | --- | --- | --- | --- |
| `Volumes_Get` | GET | 200 `Volume` | 없음 | 없음 |
| `Volumes_List` | GET | 200 `VolumeList` | 없음 | 없음 |
| `Volumes_CreateOrUpdate` | PUT | 200(갱신), 201(생성), 202(본문 없음) | 201: `Azure-AsyncOperation`, `Retry-After` / 202: `Location`, `Retry-After` | `final-state-via: azure-async-operation` |
| `Volumes_Update` | PATCH | 200 `Volume`, 202(본문 없음) | 202: `Location`, `Retry-After` | `final-state-via: location` |
| `Volumes_Delete` | DELETE | 202, 204("Resource does not exist") | 202: `Location`, `Retry-After` | `final-state-via: location` |

- 풀 PUT과 달리 볼륨 PUT의 스펙은 `Azure-AsyncOperation`과 `final-state-via: azure-async-operation`이다. 계정 PUT과 같은 모양이다 [스펙 2]. 녹화와도 맞는다(아래).
- 실패 응답은 모두 `default: ErrorResponse`(common-types v6)다 [스펙 2].

**`VolumeProperties`** (2026-08-01). `required: ["creationToken", "usageThreshold", "subnetId"]` [스펙 2]. 범위 안 속성만 적는다.

| 속성 | 타입·규칙 | 쓰기 | 기본값 | 근거 |
| --- | --- | --- | --- | --- |
| `creationToken` | 1~80자, 패턴 `^[a-zA-Z][a-zA-Z0-9\-_]{0,79}$`. 설명: "A unique file path for the volume. Used when creating mount targets" | 생성만 (`x-ms-mutability: read, create`) | 없음 | [스펙 2] |
| `usageThreshold` | int64 바이트, `minimum` 53687091200(50 GiB), `maximum` 2638827906662400(2400 TiB) | 생성·PATCH·PUT | 107374182400 (100 GiB) | [스펙 2] |
| `subnetId` | 문자열. "Must have the delegation Microsoft.NetApp/volumes" | `x-ms-mutability` 표시 없음 | 없음 | [스펙 2] |
| `protocolTypes` | 문자열 배열. "Supported values are NFSv3, NFSv4.1, and CIFS ... Default: NFSv3" | 생성, PATCH 모델에도 있음 | `["NFSv3"]` (녹화) | [스펙 2][녹화 V1] |
| `serviceLevel` | `Standard`·`Premium`·`Ultra`·`StandardZRS`·`Flexible` | 생성, PATCH 모델에도 있음 | `Premium`(스펙). 녹화에서는 요청에 없을 때 풀 값(Premium)이 채워졌다 | [스펙 2][녹화 V1] |
| `exportPolicy.rules[]` | `ExportPolicyRule` 배열 (아래) | 생성·PATCH | 서비스가 규칙 1개를 채운다 (아래) | [스펙 2][녹화 V1] |
| `fileSystemId` | UUID, 읽기 전용 | — | — | [스펙 2] |
| `mountTargets[]` | 읽기 전용. 원소는 `mountTargetId`(UUID, 읽기 전용), `fileSystemId`(UUID, 원소의 유일한 required), `ipAddress`(IPv4, 읽기 전용), `smbServerFqdn` | — | — | [스펙 2] |
| `provisioningState` | 문자열, enum 없음, 읽기 전용 | — | — | [스펙 2] |
| `throughputMibps` | float, nullable. "accepted as input only for manual qosType volume" | 생성·PATCH | — | [스펙 2] |
| `actualThroughputMibps` | float, 읽기 전용. "for auto qosType volumes calculated based on size and serviceLevel" | — | — | [스펙 2] |
| `snapshotDirectoryVisible` | boolean | 생성·PATCH | `true` | [스펙 2] |
| `unixPermissions` | 8진수 4자리 문자열, nullable | 생성·PATCH | 녹화 `"0770"` | [스펙 2][녹화 V1][문서 1] |
| `securityStyle` | `ntfs`·`unix` | 생성만 | `unix` (녹화 응답은 대문자 `"Unix"`) | [스펙 2][녹화 V1] |
| `networkFeatures` | `Basic`·`Standard` 등 | — | 스펙 `Basic`. 녹화 요청은 모두 `Standard`를 명시했다 | [스펙 2][녹화] |
| `kerberosEnabled`, `ldapEnabled`, `isLargeVolume`, `volumeType`, `snapshotId`, `backupId` | 생성만 | | `false` 등 | [스펙 2], 범위 밖 |

- 모순 하나: 스펙의 `usageThreshold` 설명은 "This is a soft quota used for alerting only."라고 쓴다 [스펙 2]. 그러나 Learn 문서는 "The storage capacity of an Azure NetApp Files volume is limited to the set size (quota) of the volume."라고 쓰고 [문서 3], FAQ는 "hard volume quota"라는 표현을 쓴다 [문서 4]. 두 내용을 모두 남긴다. 실제 동작을 설명하는 쪽은 Learn 문서다 [추론]. 스펙 설명은 오래된 문구로 보인다.
- 크기 단위: 스펙은 "Values expressed in bytes as multiples of 1 GiB", "For regular volumes, valid values are in the range 50GiB to 100TiB. For large volumes ... 100TiB to 500TiB"라고 쓴다 [스펙 2]. Resource limits 문서의 표는 일반 볼륨을 50 GiB~100 TiB로 적어 스펙과 같다. 반면 large volume 최소값은 표에서 50 TiB라 스펙의 100 TiB와 다르다 [문서 9]. large volume은 범위 밖이다.
- 스펙 `maximum`(2400 TiB)은 large volume 한도까지 포함한 값이다. 일반 볼륨의 상한 100 TiB는 패턴이 아니라 설명에만 있다 [스펙 2].

**`creationToken`(파일 경로) 규칙과 유일성 범위**. 출처끼리 문구가 다르다.
- 스펙: 1~80자, 영문자로 시작, 허용 문자는 영문자·숫자·`-`·`_` [스펙 2].
- 볼륨 생성 문서: 영문자로 시작, "letters, numbers, or dashes (`-`)", 80자 이하 [문서 1]. 밑줄은 적혀 있지 않다.
- RP 오류 문서: "The file path name can contain letters, numbers, underscores ("_"), and hyphens ("-") only." [문서 7]. 또 오류 제목은 "CreationToken must be at least 16 characters long."인데, 본문은 "The length of the file path must be at least one character in length."라고 쓴다 [문서 7]. 제목과 본문이 서로 다르다. 녹화에서는 15자인 `volumeName-7316`이 성공했다 [녹화 V1]. 따라서 16자 최소값은 현재 적용되지 않는다.
- 유일성 범위: "For volumes not in an availability zone or volumes in the same availability zone, it must be unique within each subnet in the region." [문서 1]. NFS FAQ도 같은 내용이다. 다른 리전, 다른 가용 영역, 다른 위임 서브넷에서는 같은 경로를 쓸 수 있다 [문서 6].
- 중복이면 RP 오류 "File path already in use."가 난다 [문서 7]. HTTP 코드는 [미확인].

**기본 export 규칙** (요청에 `exportPolicy`가 없을 때, `protocolTypes ["NFSv3"]`) [녹화 V1]
```
{"ruleIndex": 1, "unixReadOnly": false, "unixReadWrite": true, "cifs": false,
 "nfsv3": true, "nfsv41": false, "allowedClients": "0.0.0.0/0",
 "kerberos5ReadOnly": false, ... "kerberos5pReadWrite": false,
 "hasRootAccess": true, "chownMode": "Restricted"}
```
- 이 규칙은 201 응답 본문에는 없고, 완료 뒤 GET에 나타났다 [녹화 V1]. 요청에 규칙을 직접 넣으면 201 본문에 그 규칙이 그대로 나오고(`hasRootAccess`, `chownMode` 없음), 완료 뒤 GET에서 기본값이 채워진다 [녹화 V2, V3].
- NFSv4.1 볼륨의 기본 규칙이 `nfsv41: true`가 되는지는 녹화가 없어 [미확인]이다. 녹화 사례가 NFSv3뿐이라, 프로토콜 플래그가 `protocolTypes`를 따른다는 것은 [추론]이다.
- 스펙 `ExportPolicyRule`의 기본값은 `hasRootAccess: true`, `chownMode: Restricted`, kerberos 플래그 `false`다. `unixReadOnly`, `unixReadWrite`, `nfsv3`, `nfsv41`, `allowedClients`에는 기본값이 없다 [스펙 2].
- 규칙 수는 1~5개이고 `ruleIndex`는 1~5 사이에서 서로 달라야 한다. 위반하면 "Duplicate value error for object ExportPolicy.Rules[RuleIndex]."가 난다 [문서 7].

**완료 뒤 GET 본문** (100 GiB, Premium Auto 풀, 요청 속성은 `creationToken`·`usageThreshold`·`subnetId`·`networkFeatures`만) [녹화 V1]
- `fileSystemId` = `mountTargets[0].mountTargetId` = `mountTargets[0].fileSystemId` (같은 UUID). `mountTargets[0].ipAddress` = `"10.0.1.4"`(서브넷 안 주소).
- `actualThroughputMibps: 6.25` (= 100 GiB × 64 MiB/s/TiB). `throughputMibps`는 응답에 없었다. 스펙 예시에는 `throughputMibps: 128`이 있다 [스펙 3]. 예시와 녹화가 다르다.
- 그 밖의 값: `baremetalTenantId: "baremetalTenant_svm_<32자리 16진수>_<8자리 16진수>"`, `networkSiblingSetId`(UUID), `storageToNetworkProximity: "T2"`, `provisionedAvailabilityZone: "3"`, `encryptionKeySource: "Microsoft.NetApp"`, `isLargeVolume: false`, `coolAccess: false`, `language: "c.utf-8"`(스펙에 없음), `geoNamespaceProperties`(스펙에 없음, preview 속성으로 보임 [추론]).
- 201 본문에는 `serviceLevel`, `creationToken`, `usageThreshold`, `subnetId`, `networkFeatures`, `effectiveNetworkFeatures`, `language`, `provisioningState: Creating`만 있었다. `fileSystemId`, `mountTargets`, `exportPolicy`, `protocolTypes`는 없었다 [녹화 V1].

**PATCH 모델 (`VolumePatchProperties`)** [스펙 2]
- 바꿀 수 있는 속성: `serviceLevel`, `usageThreshold`, `exportPolicy`, `protocolTypes`, `throughputMibps`, `dataProtection`, `isDefaultQuotaEnabled`·`defaultUserQuotaInKiBs`·`defaultGroupQuotaInKiBs`, `unixPermissions`, `coolAccess` 계열, `snapshotDirectoryVisible`, SMB 계열.
- PATCH 모델에 없는 속성: `creationToken`, `subnetId`, `securityStyle`, `kerberosEnabled`, `ldapEnabled`, `isLargeVolume`, `volumeType`.
- `protocolTypes`와 `serviceLevel`이 PATCH 모델에 있지만, 실제로 바뀌는지는 문서로 확인하지 못했다 [미확인]. 서비스 수준 변경은 문서상 볼륨을 다른 풀로 옮기는 `poolChange`로 한다 (풀 브리프 [문서 9]).
- 녹화의 PATCH 요청: `{"properties": {"usageThreshold": 214748364800}}` [녹화 V4], `{"tags": {...}, "location": "westus2", "properties": {"snapshotDirectoryVisible": false}}` [녹화 V3]. 둘 다 반영됐다. `usageThreshold`를 200 GiB로 바꾸자 `actualThroughputMibps`가 6.25에서 12.5가 됐다 [녹화 V4].

### 비동기 동작 (Q2)

| 작업 | 상태 코드 | 본문 `provisioningState` | LRO 헤더 | 작업 상태 `status` 전이 | 걸린 시간 (startTime→endTime) | 근거 |
| --- | --- | --- | --- | --- | --- | --- |
| PUT 생성 | 201 | `Creating` | `Azure-AsyncOperation`만 | `Creating` → `Succeeded` | 5분 17초 / 5분 40초 / 5분 41초 | [녹화 V1, V4, V5] |
| PUT 갱신 (`usageThreshold` 변경) | 200 | `Updating` | `Azure-AsyncOperation` | `Updating` → `Succeeded` | 2.9초 | [녹화 V5] |
| PATCH | 202 | `Patching` (전체 본문 있음) | `Azure-AsyncOperation` + `Location` | `Patching` → `Succeeded` | 2.6초 / 3.1초 | [녹화 V3, V4] |
| DELETE | 202 | 본문 없음 | `Azure-AsyncOperation` + `Location` | `Deleting` → `Succeeded` | 73초 / 87초 / 106초 | [녹화 V1, V4, V5] |
| 없는 볼륨 DELETE | 204 | 없음 | 없음 | — | — | [스펙 2], 녹화 없음 |

- 진행 중 작업 상태 본문: `{"id", "name", "status": "Creating", "startTime", "endTime": "0001-01-01T00:00:00Z", "percentComplete": 0.0, "properties": {"resourceName": "<볼륨 ARM ID>", "action": "CREATE"}}`. 완료하면 `percentComplete: 100.0`이 되고 `endTime`이 채워진다 [녹화 V1]. `properties.resourceName`과 `action`은 볼륨 작업 상태 본문에서 관찰됐다. 계정·풀 브리프의 공통 형식에 이 필드가 있었는지는 이번에 대조하지 않았다.
- 생성 중 .NET SDK의 폴링 간격은 1, 1, 2, 2, 5, 8, 16초를 거쳐 약 32초로 늘었다. ANF가 `Retry-After`를 주지 않기 때문이다 [녹화 V1]. 계정 브리프의 관찰과 같다.
- 스펙과 녹화가 다른 점:
  - PUT 201: 스펙에는 `Retry-After`가 있는데, 녹화에는 없었다.
  - PATCH 202: 스펙은 본문이 없는데, 녹화에는 `Patching` 전체 본문이 있었다. 풀과 같은 패턴이다.
  - PUT 200 갱신: 스펙에는 헤더가 없는데, 녹화에는 `Updating` + `Azure-AsyncOperation`이 있었다. 계정·풀과 같은 패턴이다.
  - 스펙 예시의 201 본문은 `provisioningState: Succeeded`인데, 실서비스는 `Creating`이었다 [스펙 3][녹화 V1].
- 관찰된 `provisioningState` 값: 리소스 본문에서는 `Creating`, `Updating`, `Patching`, `Succeeded`, 작업 상태에서는 `Deleting`도 보였다 [녹화]. 리소스 본문의 `Deleting`·`Failed`는 녹화에 없다 [미확인].
- 진행 중(종료 상태가 아님)인 볼륨에 PUT을 보내면 즉시 409가 났다. 응답은 `RequestConflict`, "Cannot modify resource with id '...' because the resource entity provisioning state is not terminal. Please wait for the provisioning state to become terminal and then retry the request."이고 `x-ms-failure-cause` 헤더는 없었다 [녹화 V6]. 이 테스트는 이전 실행이 남긴 볼륨에 PUT을 보낸 것으로 보인다 [추론].
- PUT 갱신에서 tags가 맵 전체 교체인지: PATCH에서 tags는 요청 맵 + 정책 태그(`CreatedOnDate`, 값이 새로 바뀜)가 됐다 [녹화 V3]. 풀 브리프와 같다.

### 제약과 한도

- 일반 볼륨 크기: 50 GiB~100 TiB, 1 GiB 배수 [스펙 2][문서 9]. "Adjustable via support request: No" [문서 9].
- 개수: 풀당 볼륨 1,000개(늘릴 수 있음), 구독당 볼륨 2,000개(늘릴 수 있음), 볼륨당 스냅샷 255개(고정) [문서 9].
- 할당량 합 ≤ 풀 크기 규칙과 그 오류 메시지는 풀 브리프에 있다 ("Pool size too small for total volume size.", HTTP 코드 [미확인]).
- 볼륨 크기 변경은 "nearly instantaneous but not always immediate"이고 데이터 손실이 없다. `maxfiles` 한도를 넘긴 볼륨은 그에 해당하는 할당량 아래로 줄일 수 없다 [문서 8].
- 생성 뒤 불변: `creationToken`("CreationToken cannot be changed."), `fileSystemId`("FileSystemId cannot be changed."). 오류 문서는 "Don't include FileSystemId in a patch and update (put) request. Alternatively make sure that FileSystemId is the same in the request."라고 쓴다 [문서 7]. 즉 같은 값을 다시 보내는 것은 허용된다.
- `subnetId`에는 `x-ms-mutability` 표시가 없지만 PATCH 모델에도 없다 [스펙 2]. 생성 뒤 바꿀 수 있는지는 [미확인]이다.
- 프로토콜: NFSv3와 NFSv4.1을 지원한다 [문서 6]. CIFS와 NFS를 섞으면 "Not allowed to mix protocol types CIFS and NFS"가 난다 [문서 7]. NFSv4.1 볼륨에서는 NFSv4.2도 켜져 있지만 공식 지원은 아니다 [문서 5].
- `mount-rootonly`는 기본으로 켜져 있다(권한 없는 클라이언트 포트에서 온 마운트 요청을 거절한다). `nfs-rootonly`는 ONTAP 기본값과 같이 꺼져 있다 [문서 6].

### 오류 상황 (Q3)

| 상황 | HTTP | 코드·메시지 | 동기/비동기 | 근거 |
| --- | --- | --- | --- | --- |
| 없는 풀 아래 볼륨 PUT | 404 | `ParentResourceNotFound`, "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools/volumes', because the parent resource '{pool id}' could not be found.", `x-ms-failure-cause: gateway` | 즉시 | [녹화 N6] (풀 브리프) |
| 볼륨이 남은 풀 DELETE | 409 | `CannotDeleteResource`, "Cannot delete resource while nested resources exist. Some existing nested resource IDs include: 'Microsoft.NetApp/netAppAccounts/{a}/capacityPools/{p}/volumes/{v}'. Please delete all nested resources before deleting this resource.", `x-ms-failure-cause: gateway` | 즉시 | [녹화 N5] (풀 브리프) |
| 한 번도 없던 볼륨 GET | 404 | `ResourceNotFound`, "The Resource 'Microsoft.NetApp/netAppAccounts/{a}/capacityPools/{p}/volumes/{v}' under resource group '{rg}' was not found. For more details please go to https://aka.ms/ARMResourceNotFoundFix", `x-ms-failure-cause: gateway` | 즉시 | [녹화 V1] |
| 방금 지운 볼륨 GET | 404 | `ResourceNotFound`, "The resource with identifier '/subscriptions/.../volumes/{v}' is not found." | 즉시 | [녹화 V5] |
| 종료 상태가 아닌 볼륨에 PUT | 409 | `RequestConflict` (위 메시지) | 즉시 | [녹화 V6] |
| `creationToken` 중복 (같은 서브넷) | [미확인] | "File path already in use." | [미확인] | [문서 7] |
| `creationToken` 변경 | [미확인] | "CreationToken cannot be changed." | [미확인] | [문서 7] |
| `creationToken` 허용 밖 문자 | [미확인] | "The file path name can contain letters, numbers, underscores ("_"), and hyphens ("-") only." | [미확인] | [문서 7] |
| `creationToken` 너무 김·짧음 | [미확인] | "File path too long." / "File path too short." | [미확인] | [문서 7] |
| `fileSystemId`를 다른 값으로 변경 | [미확인] | "FileSystemId cannot be changed." | [미확인] | [문서 7] |
| export 규칙 `ruleIndex` 중복이나 범위(1~5) 밖 | [미확인] | "Duplicate value error for object ExportPolicy.Rules[RuleIndex]." | [미확인] | [문서 7] |
| CIFS와 NFS를 함께 지정 | [미확인] | "Not allowed to mix protocol types CIFS and NFS" | [미확인] | [문서 7] |
| 풀의 남은 용량보다 큰 볼륨 | [미확인] | "Pool size too small for total volume size." | [미확인] | 풀 브리프 [문서 8] |
| `Succeeded`가 아닌 풀에 볼륨 생성 | [미확인] | "Volume cannot be created in a pool that isn't in state succeeded." | [미확인] | 풀 브리프 [문서 8] |

- 녹화 176개 전체에서 볼륨 경로의 오류를 모았다. 용량 초과, 파일 경로 중복, 불변 속성 변경 사례는 없었다 [녹화]. 그래서 이 오류들의 HTTP 코드와 `error.code`는 모두 [미확인]이다.

## 데이터 플레인에서 보이는 효과 (Q4)

- 마운트 경로: `$MOUNTTARGETIPADDRESS:/$VOLUMENAME`. 문서 예는 `sudo mount -t nfs -o rw,hard,rsize=65536,wsize=65536,vers=4.1,tcp,sec=sys ...`(NFSv4.1)와 fstab `$ANFIP:/$FILEPATH /$MOUNTPOINT nfs bg,rw,hard,noatime,nolock,rsize=65536,wsize=65536,vers=3,tcp,_netdev 0 0`(NFSv3)이다 [문서 5]. fstab 예의 변수 이름이 `$FILEPATH`라서, export 경로는 `creationToken`이다 [문서 1, 5]. 볼륨 생성 문서의 "This path is used when you create mount targets"도 이와 맞는다 [문서 1].
- NFSv4.1은 `vers=4.1`을 명시해야 한다. 명시하지 않으면 클라이언트가 지원되지 않는 4.2로 협상할 수 있다 [문서 5].
- `rsize`·`wsize`는 최대 1 MiB까지 되지만, 권장값은 256 KiB(262,144) 이하다 [문서 10]. `nconnect`는 최대 16이다. 같은 엔드포인트(IP)에 대한 마운트는 첫 마운트의 `nconnect` 설정을 물려받는다 [문서 10].
- 같은 IP를 여러 볼륨이 공유하는지: 문서의 `nconnect` 예는 `10.10.10.10:/volume1`, `10.10.10.10:/volume2`, `10.10.10.10:/volume3`처럼 IP 하나에 여러 볼륨을 둔다 [문서 10]. 스펙의 `networkSiblingSetId`는 "group of volumes sharing networking resources"다 [스펙 2]. 따라서 여러 볼륨이 마운트 IP 하나를 공유할 수 있다 [추론]. 어떤 조건에서 IP가 공유되는지는 [미확인]이다.
- 할당량에 닿았을 때: "When volume consumption maxes out, neither the volume nor the underlying capacity pool grows automatically. Instead, the volume will receive an "out of space" condition." [문서 3]. 클라이언트 쪽 errno가 ENOSPC인지 EDQUOT인지는 공개 문서에서 찾지 못했다 [미확인]. 문서가 "quota"가 아니라 "out of space"라고 쓰므로 ENOSPC일 가능성이 높다 [추론].
- 스냅샷과 사용량: "The capacity consumed by volume snapshots counts towards the provisioned space in the volume." [문서 3, 4]. 문서는 별도의 스냅샷 reserve를 언급하지 않는다. 스냅샷은 변경된 블록만 쓴다 [문서 11]. 큰 삭제 뒤 공간을 회수하는 데 몇 분이 걸릴 수 있다 [문서 4].
- `.snapshot` 디렉터리: NFSv3 클라이언트에는 기본으로 보이고, NFSv4.1 클라이언트에는 보이지 않는다("by design"). `snapshotDirectoryVisible: false`로 바꾸면 NFSv3에서도 숨겨지지만, 경로로 접근하는 것은 여전히 된다 [문서 6, 1].
- 마운트 루트 권한: 기본 `unixPermissions`는 `0770`이다. 이 값은 마운트 경로(볼륨 루트)에만 적용되고 그 아래 파일에는 적용되지 않는다 [문서 1][녹화 V1].
- 클라이언트 `df`가 보여 주는 크기(할당량인지, 스냅샷 사용량이 포함되는지)는 [미확인]이다. "Verify the size from a host perspective"라는 문구로 보아, 호스트에서 크기 변경을 볼 수 있다 [문서 8][추론].
- 마운트 포트: 문서는 rquotad(4049)를 선택 포트로 적는다 [문서 5]. 클라이언트가 원격 quota 조회를 할 수 있다는 단서다 [추론].

## ONTAP 대응 개념 (Q5, Q6)

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| 볼륨 | FlexVol 볼륨 | ONTAP REST `POST /api/storage/volumes`의 최소 예는 `name`, `svm.name`, `aggregates[].name`이다 [문서 13]. ANF 볼륨이 FlexVol이라는 직접 공개 근거는 찾지 못했다. ANF 스냅샷 문서의 "Redirect on Write", 포인터 기반 설명이 ONTAP WAFL과 일치한다 [문서 11] | 대응 [추론] |
| `creationToken` (파일 경로) | junction path (`nas.path`) | ONTAP에서는 볼륨이 SVM 네임스페이스의 junction path에 마운트되어야 클라이언트가 데이터를 볼 수 있다. "A volume must include a junction path for its data to be made available to clients." [문서 12]. junction path는 255자 이하이고 `* # " > < \| ? \`를 쓸 수 없다 [문서 12]. ANF 마운트 경로 `<IP>:/<creationToken>`의 모양이 SVM 루트 바로 아래 junction과 같다 | 대응 [추론] |
| 마운트 대상 `ipAddress` | SVM의 data LIF | ONTAP 원문(LIF)은 이번에 확인하지 못했다 [미확인]. 녹화의 `baremetalTenantId: "baremetalTenant_svm_..."` 이름에 `svm`이 들어 있다 [녹화 V1]. 테넌트별 SVM과 그 data LIF가 마운트 IP일 가능성이 있다 | [추론] |
| `subnetId`의 위임 서브넷 | (Azure 쪽) | 마운트 IP가 고객 VNet의 위임 서브넷에서 할당된다 [스펙 2][녹화 V1: 10.0.1.4] | [스펙][녹화] |
| 네임스페이스 / NFSv4 pseudo-fs | SVM 네임스페이스 (루트 볼륨이 진입점) | "Every SVM has a unique namespace. The SVM root volume is the entry point to the namespace hierarchy." [문서 12]. NFSv4 pseudo-fs에 대한 ONTAP 원문은 이번에 받지 못했다 [미확인] | [문서] / pseudo-fs [미확인] |
| `exportPolicy.rules[]` | export policy와 rule (`nas.export_policy`) | ONTAP 볼륨 GET 예에 `"nas": {"export_policy": {"name": "default", ...}, "security_style": "unix", "unix_permissions": 4755, ...}`가 있다 [문서 13]. ANF 규칙 필드(`allowedClients`, `unixReadWrite`, `hasRootAccess`, `nfsv3`/`nfsv41`)는 ONTAP rule의 clientmatch, rorule/rwrule, superuser, protocol과 닮았다 | 필드 대응 [추론] |
| `unixPermissions`, `securityStyle` | `nas.unix_permissions`, `nas.security_style` | 같은 이름의 ONTAP 필드가 있다 [문서 13] | 대응 [추론] |
| `usageThreshold` (할당량) | 볼륨 크기 `size` | ANF는 할당량을 "볼륨 크기"라고도 부른다 [문서 3]. ONTAP 볼륨에는 크기와 별도로 quota(사용자, 그룹, qtree) 기능이 있다 [문서 13]. ANF의 `usageThreshold`가 ONTAP 볼륨 `size`인지 quota인지는 공개되지 않았다 [미확인]. "out of space"라는 표현은 볼륨 `size`에 가깝다 [추론] | [추론] |
| 할당량 합 ≤ 풀 크기 | thin provisioning 반대 (예약) | ONTAP thin provisioning은 공간을 미리 예약하지 않아 애그리게이트를 overcommit할 수 있다 [문서 14]. ANF가 백엔드에서 thin인지는 공개되지 않았다 [미확인] | [문서] / 대응 [추론] |
| 비동기 작업 (`operationResults`) | ONTAP job (`/api/cluster/jobs/{uuid}`) | job `state` 값은 `queued`, `running`, `paused`, `success`, `failure`이다. 필드는 `uuid`, `code`, `description`, `message`, `error`, `start_time`, `end_time`, `state`, `svm` 등이다. 종료 상태가 된 job은 기본 300초 뒤 삭제되고, 그 뒤 GET은 404다 [문서 15] | [문서] |
| ONTAP `POST /api/storage/volumes`의 원본 HTTP 응답 | — | 202 + `job` 링크라는 원문은 이번에 확인하지 못했다 (Python 클라이언트 예제는 `resource.post(hydrate=True)`만 보인다 [문서 13]) | [미확인] |
| 볼륨이 가득 참 | FlexVol fullness 경고 (EMS) | ONTAP은 볼륨이 공간이 부족해지면 EMS 메시지를 낸다. "full"은 활성 파일 시스템에 쓸 수 있는 공간의 비율이 임계값 아래로 떨어진 상태다 [문서 16]. NFS 클라이언트가 받는 errno 원문은 [미확인] | [문서] / errno [미확인] |
| `.snapshot` 디렉터리 (NFSv3에서 보임) | ONTAP `.snapshot` 디렉터리 | ANF 문서가 ONTAP 기본값과 같다고 명시한 것은 `nfs-rootonly`뿐이다 [문서 6] | [추론] |

- ANF의 ARM 볼륨과 ONTAP 볼륨이 일대일로 대응한다는 공개 자료는 찾지 못했다. 찾아본 곳은 Learn 문서 11개와 NetAppDocs ONTAP 원문 5개다. 웹 검색은 상한 때문에 하지 않았다 [미확인]. 근거가 될 단서는 세 가지다. `baremetalTenantId`에 들어 있는 `svm` [녹화 V1], WAFL과 같은 스냅샷 설명 [문서 11], 풀 브리프의 "NetApp's bare metal with ONTAP storage OS" 문구다. 이 단서로 볼 때 볼륨 하나가 테넌트 SVM 안의 ONTAP 볼륨 하나라는 추론은 그럴듯하다 [추론].
- 면접에서 써도 안전한 문장: "ANF 볼륨의 파일 경로(`creationToken`)는 마운트 경로가 된다. ONTAP에서 이와 가장 닮은 것은 SVM 네임스페이스의 junction path다. ANF가 내부적으로 ONTAP 볼륨을 junction path에 마운트한다는 공개 문서는 없지만, 응답의 `baremetalTenantId`에 `svm`이 들어 있다."

## 구현 범위 후보

**이번에 재현할 것 (후보와 이유)**
- PUT 생성(201 + `Creating` + `Azure-AsyncOperation`), PUT 갱신(200 + `Updating`), PATCH(202 + `Patching` 본문 + 두 헤더), DELETE(202 + 두 헤더), 없는 볼륨 DELETE 204, GET, 목록. 공통 LRO 계층을 그대로 재사용한다.
- 본문 규칙: `creationToken` 패턴과 불변성, `usageThreshold` 50 GiB~100 TiB와 1 GiB 배수, `protocolTypes`(`NFSv3`·`NFSv4.1`, 기본 `["NFSv3"]`, CIFS 거절), `subnetId` 필수.
- 서비스가 채우는 값: `fileSystemId`, `mountTargets[{mountTargetId=fileSystemId, fileSystemId, ipAddress}]`, 기본 export 규칙, `unixPermissions "0770"`, `snapshotDirectoryVisible true`, `actualThroughputMibps`(풀 공식 재사용).
- 부모·자식 규칙: 없는 풀이면 404 `ParentResourceNotFound`, 볼륨이 있는 풀 DELETE는 409 `CannotDeleteResource`, 할당량 합 ≤ 풀 크기.
- 데이터 플레인: 볼륨마다 할당량 크기의 파일시스템을 만들고 `creationToken` 경로로 NFS export한다. 마운트 대상 IP로 v3와 v4.1 마운트가 되고, 할당량을 넘는 쓰기는 실패해야 한다.

**다음으로 미룰 것**
- export 규칙 세부 적용(`allowedClients`, ro/rw, root squash). FR "export policy" 사이클이다. 이번에는 기본 규칙(전체 허용, rw, root 허용)만 실제 export에 반영하는 후보가 있다.
- `throughputMibps`(Manual QoS)와 실제 I/O 제한: FR-08, S2 이후.
- `.snapshot` 디렉터리와 `snapshotDirectoryVisible` 효과: 스냅샷 사이클.
- 크기 변경의 데이터 효과(호스트에서 크기가 바뀌는 것): 볼륨 크기 변경 사이클. 다만 PATCH `usageThreshold`의 API 동작은 이번 범위다.
- poolChange, large volume, 가용 영역, Kerberos, LDAP, SMB.

**리더·사용자가 정해야 할 선택지** (조사자는 정리만 한다)
1. **생성 소요 시간:** 실서비스는 약 5분 넘게 걸린다. 클론은 실제 작업 시간을 그대로 둘지, 검증용 지연은 결함 주입으로만 만들지 정한다.
2. **`creationToken` 유일성 범위:** 문서상 "서브넷 안에서 유일"이다. 클론에는 서브넷이 하나뿐이다. 클론 전체에서 유일하게 할지, `subnetId` 값별로 유일하게 할지, 마운트 IP별로 유일하게 할지 정한다. 실제 export 경로 충돌을 막으려면 마운트 IP(스토리지 호스트) 하나 안에서는 유일해야 한다 [추론].
3. **`creationToken` 허용 문자:** 스펙과 RP 오류 문서는 밑줄을 허용하고, 생성 문서는 밑줄을 적지 않았다. 16자 최소값은 녹화(15자 성공)로 보아 적용되지 않는다.
4. **`subnetId` 처리:** 필수 속성이다. 클론에서는 형식(ARM ID 모양)만 검사할지, 값을 무시할지, 특정 Docker 네트워크로 연결할지 정한다. 또 생성 뒤 변경을 거절할지 정한다(PATCH 모델에는 없다).
5. **`usageThreshold`의 의미:** 스펙은 "soft quota used for alerting only", Learn 문서는 "limited to the set size"라고 한다. 클론은 프로젝트 요구사항(실제 효과)에 따라 하드 한도로 할 가능성이 높지만, 그 근거로 Learn 문서를 쓴다는 것을 기록해야 한다.
6. **오류의 HTTP 코드:** 파일 경로 중복, 불변 속성 변경, 용량 초과의 실서비스 HTTP 코드와 `error.code`는 근거가 없다. 동기 400/409로 할지, 작업 실패로 할지 클론이 정하고 문서화한다.
7. **PATCH의 `protocolTypes`·`serviceLevel`:** 스펙상 PATCH할 수 있다. 클론에서 받아들일지(프로토콜 변경은 export 변경), 거절할지 정한다.
8. **NFSv4.1 기본 export 규칙:** 녹화가 없다. `nfsv41: true`, `nfsv3: false`로 채우는 것은 추론이다.
9. **`throughputMibps` 노출:** Auto 풀에서 녹화는 `actualThroughputMibps`만 주고, 스펙 예시는 `throughputMibps`를 준다.

**검증 기준 후보** (클라이언트에서 관찰할 수 있는 효과)
1. PUT `{creationToken, usageThreshold: 107374182400, subnetId}` → 201 + `Creating` + `Azure-AsyncOperation`. 폴링하면 `Succeeded`가 되고, GET에 `fileSystemId`(UUID), `mountTargets[0].ipAddress`, `protocolTypes ["NFSv3"]`, 기본 export 규칙 1개, `actualThroughputMibps 6.25`(Premium)가 있다.
2. 컨테이너에서 `mount -t nfs -o vers=3 <ipAddress>:/<creationToken>`과 `vers=4.1` 마운트가 성공하고, 파일 쓰기와 읽기가 된다.
3. 할당량(예: 1 GiB 클론 설정)을 넘게 쓰면 클라이언트 쓰기가 실패한다. errno는 기록만 하고 기준으로 고정하지 않는다(미확인).
4. 같은 `creationToken`으로 두 번째 볼륨을 만들면 거절되고, 첫 볼륨의 export는 그대로다.
5. `creationToken`을 바꾼 PUT/PATCH는 거절되고 마운트 경로가 바뀌지 않는다. 같은 값을 다시 보내는 것은 허용된다.
6. PATCH `{"properties": {"usageThreshold": 214748364800}}` → 202 + `Patching`. 완료 뒤 `usageThreshold`와 `actualThroughputMibps 12.5`가 바뀐다.
7. 없는 풀 아래 PUT → 404 `ParentResourceNotFound`. 볼륨이 있는 풀 DELETE → 409 `CannotDeleteResource` (풀 사이클 CV 기준).
8. DELETE → 202 + 두 헤더 → `Succeeded`. 그 뒤 클라이언트 마운트가 실패하고 export 목록에서 사라진다. GET은 404, 다시 DELETE하면 204다.
9. `usageThreshold`가 50 GiB 미만이거나 1 GiB 배수가 아니면, 또는 `protocolTypes`에 CIFS가 있으면 4xx이고 export가 생기지 않는다.
10. 생성 진행 중 같은 볼륨에 PUT → 409 `RequestConflict` [녹화 V6].

## 미확인 목록

| 항목 | 설계를 막는가 | 찾아본 곳 |
| --- | --- | --- |
| 파일 경로 중복, 불변 속성 변경, 용량 초과, export 규칙 오류의 HTTP 코드·`error.code`·동기 여부 | 선택 필요 (선택지 6) | RP 오류 문서(메시지만), 녹화 176개의 오류 집계 |
| 할당량 초과 시 NFS 클라이언트 errno(ENOSPC/EDQUOT), ONTAP 쪽 원문 | 막지 않음 (검증 기준에서 errno를 고정하지 않으면) | Learn `volume-quota-introduction`, `faq-capacity-management`, ONTAP `flexvol-fullness` 원문 |
| 클라이언트 `df`가 보여 주는 크기와 스냅샷 사용량 포함 여부 | 막지 않음 | 위 Learn 문서들. 웹 검색은 하지 않음 |
| NFSv4.1 볼륨의 기본 export 규칙 모양 | 선택 필요 (선택지 8) | 녹화(NFSv3 사례뿐) |
| PATCH로 `protocolTypes`·`serviceLevel`을 바꿀 때의 실제 동작 | 선택 필요 (선택지 7) | 스펙(PATCH 모델에 있음), 녹화 없음 |
| `subnetId`의 생성 뒤 변경 가능 여부 | 선택 필요 (선택지 4) | 스펙(mutability 표시 없음, PATCH 모델에 없음) |
| 여러 볼륨이 마운트 IP를 공유하는 조건 | 막지 않음 | Learn `performance-linux-mount-options`(예시만), 스펙 `networkSiblingSetId` |
| 리소스 본문의 `provisioningState: Deleting`, `Failed` | 막지 않음 (계정·풀과 같음) | 녹화 |
| ONTAP `POST /api/storage/volumes`의 원본 HTTP 응답(202 + job 링크) | 막지 않음 (storage agent의 job 모델은 클론이 정함) | netapp-ontap 9.19.1.0 `resources/volume.py`(클라이언트 예제뿐). docs.netapp.com ONTAP REST 참조는 받지 않음 |
| ONTAP data LIF, NFSv4 pseudo-fs 원문 | 막지 않음 (개념 문서용) | NetAppDocs 트리 검색(파일 이름에 pseudo 없음). LIF 원문은 받지 않음 |
| ANF 볼륨 = ONTAP FlexVol이라는 공개 근거 | 막지 않음 ([추론]으로 설명) | Learn 문서 11개, NetAppDocs 5개 |
| 볼륨 작업 상태 본문의 `properties.resourceName`·`action`이 계정·풀 작업에도 있는지 | 막지 않음 | 볼륨 녹화에서만 확인 |

## 후속 조사 목록

- export policy 사이클: `allowedClients` 형식, ro/rw 우선순위, `hasRootAccess false`(root squash), `chownMode`, 규칙 PATCH의 반영 시간.
- 크기 변경 사이클: 클라이언트 `df`의 즉시 반영, 할당량 축소 하한(`maxfiles`).
- 스냅샷 사이클: `.snapshot` 표시 규칙(NFSv3/v4.1), 스냅샷 사용량이 할당량에 잡히는 모습.
- FR-08: Manual QoS 볼륨의 `throughputMibps` 범위와 "Requested throughput not available" 오류.
- poolChange, `networkFeatures`(Basic/Standard), 가용 영역 볼륨 배치, large volume, NFSv4.1 ID 도메인, Kerberos, LDAP.
- ONTAP REST: `POST /api/storage/volumes` → 202 + job, `GET /api/storage/volumes?name=`, `DELETE /api/storage/volumes/{uuid}` 원문(ontap-restapi 문서)과 data LIF 개념 원문.

## 출처

확인일은 모두 2026-11-07이다.

- [1] Microsoft Learn — Create an NFS volume for Azure NetApp Files. 원본 markdown `articles/azure-netapp-files/azure-netapp-files-create-volumes.md`, `MicrosoftDocs/azure-docs` 커밋 `548a6fcfecc7e850241c77f1a29db21d781d5d1b`. 사본: `sources/docs/`
- [2] Azure REST API specs — `stable/2026-08-01/netapp.json` (volumes 경로, `Volume`, `VolumeProperties`, `MountTargetProperties`, `ExportPolicyRule`, `VolumePatch`, `VolumePatchProperties`, `VolumeList`). 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`. 풀 조사 사본을 재사용했다: `_workspace/capacity-pool/sources/spec/netapp-2026-08-01.json`. 같은 커밋의 `Volume.tsp`는 `sources/spec/Volume.tsp`에 받았지만 읽지 않았다.
- [3] Azure REST API specs — `stable/2026-08-01/examples/Volumes_CreateOrUpdate.json`, `Volumes_Get.json`, `Volumes_List.json`, `Volumes_Update.json`, `Volumes_Delete.json`. 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`. 사본: `sources/spec/examples/`
- 번호 표기: 본문의 `[스펙 n]`은 [2]·[3](스펙과 예시)을 가리키고, `[문서 n]`은 같은 번호의 문서를 가리킨다. 번호 3은 둘이 겹친다. `[스펙 3]`은 위의 예시이고, `[문서 3]`은 바로 아래 문서다.
- [문서 3] Microsoft Learn — Understand volume quota (`volume-quota-introduction.md`), 같은 azure-docs 커밋
- [4] Microsoft Learn — Capacity management FAQs (`faq-capacity-management.md`), 같은 커밋
- [5] Microsoft Learn — Mount NFS volumes for Linux or Windows VMs (`azure-netapp-files-mount-unmount-volumes-for-virtual-machines.md`), 같은 커밋
- [6] Microsoft Learn — NFS FAQs for Azure NetApp Files (`faq-nfs.md`), 같은 커밋
- [7] Microsoft Learn — Troubleshoot Azure NetApp Files Resource Provider errors. 계정 조사 사본을 재사용했다: `_workspace/netapp-account/sources/arm-rpc/anf-rp-errors.txt`
- [8] Microsoft Learn — Resize a capacity pool or a volume (`azure-netapp-files-resize-capacity-pools-or-volumes.md`), 같은 커밋
- [9] Microsoft Learn — Resource limits for Azure NetApp Files. 풀 조사 사본을 재사용했다: `_workspace/capacity-pool/sources/docs/azure-netapp-files-resource-limits.txt`
- [10] Microsoft Learn — Linux NFS mount options best practices (`performance-linux-mount-options.md`), 같은 커밋
- [11] Microsoft Learn — How Azure NetApp Files snapshots work (`snapshots-introduction.md`), 같은 커밋
- 같은 커밋에서 `troubleshoot-volumes.md`도 받았지만 읽지 않았다.
- [12] NetApp ONTAP 문서 원본 — `NetAppDocs/ontap` 커밋 `37d53f2a6cff395e1fb457f522c61826a8dbf379`: `nfs-admin/namespaces-junction-points-concept.adoc`, `nfs-admin/create-volumes-specified-junction-task.adoc`, `nfs-config/create-volume-task.adoc`. 사본: `sources/ontap/adoc/`
- [13] NetApp ONTAP Python 클라이언트 `netapp-ontap` 9.19.1.0 (PyPI 휠), `netapp_ontap/resources/volume.py`의 문서 문자열(ONTAP REST 문서와 같은 내용). 사본: `sources/ontap/volume.py.txt` (텍스트로만 추출했고 실행하지 않았다)
- [14] NetAppDocs `concepts/thin-provisioning-concept.adoc` (커밋은 [12]와 같다)
- [15] `netapp-ontap` 9.19.1.0 `netapp_ontap/resources/job.py` 문서 문자열. 사본: `sources/ontap/job.py.txt`
- [16] NetAppDocs `volumes/flexvol-fullness-overallocation-alerts-concept.adoc` (커밋은 [12]와 같다)
- [R] 녹화 — .NET 태그 `net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c`, Python 태그 `python/netapp/azure-mgmt-netapp_c350090f50` (계정 브리프 출처 [21]·[27]). 사본: `_workspace/netapp-account/sources/recordings/`. 이번에 읽은 파일은 맨 위 V1~V6이다. 오류 집계에는 176개 전체를 썼다.

## 변경 이력

- 2026-11-07: 처음 작성했다. 골격을 먼저 저장한 뒤 Q1~Q5를 채웠다. 실행 상한 때문에 ONTAP REST 원본 응답, data LIF, NFS full errno, `df` 표시는 미확인으로 남겼다.
