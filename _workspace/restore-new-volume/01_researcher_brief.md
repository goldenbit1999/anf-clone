# 스냅샷에서 새 볼륨으로 복원 (FR-07) 조사 브리프

- 조사 상태: **완료 (필수 질문 다섯 가지에 답함). 단, 허용 범위 규칙(다른 풀·계정·프로토콜, 크기 하한)과 거절 오류 코드는 [미확인]으로 남았다.** 실행 상한에 가까워 추가 조사를 멈췄다. 남은 항목은 "미확인 목록"에 있다.
- 조사일: 2026-11-08
- 기준 api-version: `2026-08-01` (스펙 [1][2]). 녹화는 `2026-08-15-preview`다 [녹화 R4, 2026-10-30]. ONTAP REST는 9.19.1 문서와 `netapp-ontap` 9.19.1.0을 기준으로 했다 [8][9][10].
- 범위 가정: 리더가 준 질문 1~4를 그대로 범위로 삼았다. 일반 볼륨 생성의 계약(경로, 필수 속성, 이름 규칙, mountTargets 등)은 `_workspace/volume/01_researcher_brief.md`를 따르고 다시 조사하지 않았다. 단기 클론(`volumeType: ShortTermClone`), 백업에서 복원, `splitCloneFromParent`는 범위 밖이다.

## 요약 (5줄 이내)

1. 복원은 별도 API가 아니라 **볼륨 PUT에 `properties.snapshotId`(스냅샷의 ARM 리소스 ID)를 넣는 것**이다. `snapshotId`는 생성 때만 쓸 수 있고(`x-ms-mutability [read, create]`, PATCH 모델에 없음), GET에 그대로 남는다. 완료 뒤 `originatingResourceId`에 같은 ARM ID가 채워진다 [스펙 2, 녹화 R4].
2. 응답은 일반 볼륨 생성과 같다: `201` + `Azure-AsyncOperation`/`Location`, 본문 `Creating`, 작업 `Creating`→`Succeeded`(`action CREATE`). 같은 녹화에서 일반 볼륨은 약 6분, 복원 볼륨은 약 11초 걸렸다 [녹화 R4].
3. `Succeeded` 뒤에도 백그라운드 복사가 이어진다. `cloneProgress`가 `0`으로 보이다가 약 5분 45초 뒤 `null`이 됐다(스펙: null이면 진행 중인 클론 없음, 5분마다 갱신). 문서는 그동안 원본 볼륨과 스냅샷을 지울 수 없고, 끝나면 새 볼륨이 독립된다고 쓴다 [녹화 R4, 스펙 2, 문서 3, 4].
4. 새 볼륨에는 원본과 **이름이 같고 `snapshotId`가 다른 base 스냅샷**이 생긴다. `created`는 원본 스냅샷 시각을 초 단위로 자른 값이다 [녹화 R4]. `deleteBaseSnapshot`은 녹화에 없고, 스펙 설명과 문서가 지우는 대상을 다르게 읽힌다 [스펙 2, 문서 3].
5. ONTAP 대응은 SnapRestore가 아니라 **FlexClone(`POST /api/storage/volumes`, `clone.is_flexclone`·`parent_volume`·`parent_snapshot`) + clone split(`clone.split_initiated`, `split_complete_percent`)**로 보인다 [추론]. 근거는 ANF 오류 문구 "Failed to split new volume from source volume snapshot"과 문서의 "clones" 표현이다 [문서 5, 4]. ONTAP은 FlexClone이 있는 동안 부모 볼륨 삭제를 막고, base 스냅샷은 `busy, vclone`이 된다 [문서 11, KB 13 원문 미확인].

## 사용자에게 보이는 동작

### 리소스와 API (질문 1)

- **경로**: 일반 볼륨과 같다. `PUT .../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}` [녹화 R4, 스펙 2]. 복원 전용 action은 없다 [스펙 2: `Volumes_*` 작업 목록에서 확인. `splitCloneFromParent`는 단기 클론용이다].
- **요청 본문 (녹화 R4, 엔트리 43)**
  ```json
  {"tags": {...}, "location": "westus2", "properties": {
    "creationToken": "volume-4194", "usageThreshold": 107374182400,
    "snapshotId": "/subscriptions/.../netAppAccounts/account9903/capacityPools/pool1/volumes/volumeName-9830/snapshots/snapshot-6328",
    "subnetId": ".../subnets/default", "networkFeatures": "Standard"}}
  ```
  - `protocolTypes`, `serviceLevel`, `exportPolicy`는 보내지 않았다. 응답은 기본값 `NFSv3`, 풀의 `Premium`, 기본 규칙(`nfsv3: true`, `0.0.0.0/0`)이었다 [녹화 R4].
- **`properties.snapshotId`** [스펙 1, 2]
  - 형식: `type: string, format: arm-id`, `x-ms-arm-id-details.allowedResources: [Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots]`. 즉 **스냅샷의 ARM 리소스 ID**다. 스냅샷 리소스의 `properties.snapshotId`(UUID)가 아니다. 녹화도 ARM ID를 보냈다 [녹화 R4]. revert 본문(`VolumeRevert.snapshotId`)과 같은 형식이다 [스펙 1, Volume.tsp 1618행].
  - 가변성: `x-ms-mutability [read, create]`, TypeSpec `@visibility(Lifecycle.Read, Lifecycle.Create)`, `x-nullable: true` [스펙 1, 2].
  - `VolumePatchProperties`에 없다. PATCH 모델의 속성은 `usageThreshold`, `protocolTypes`, `exportPolicy`, `serviceLevel`, `throughputMibps`, `snapshotDirectoryVisible` 등 17개뿐이다 [스펙 2].
  - GET 응답에 남는다: 201 본문, `Succeeded` 뒤 GET, 7분 뒤 GET 모두 같은 ARM ID를 돌려줬다 [녹화 R4, 엔트리 43·50·57].
  - **재PUT에서 다른 `snapshotId`를 보냈을 때**의 실동작은 [미확인]. 녹화에 없고, troubleshoot 문서의 "X cannot be changed" 목록(`CreationToken`, `SubnetId`, `ServiceLevel`, `PoolId`, `FileSystemId`, `MountTargets`, `Protocol types` 등)에도 `snapshotId`는 없다 [문서 5]. 기존 볼륨에 처음으로 `snapshotId`를 넣는 재PUT도 [미확인].
- **응답의 복원 관련 속성** [스펙 2, 녹화 R4]

| 속성 | 스펙 | 201 (Creating) | Succeeded 직후 GET | 약 6분 뒤 GET |
| --- | --- | --- | --- | --- |
| `snapshotId` | arm-id, read/create | ARM ID | ARM ID | ARM ID |
| `originatingResourceId` | 읽기 전용, "Id of the snapshot or backup that the volume is restored from." | 없음 | 원본 스냅샷 ARM ID | 같음 |
| `cloneProgress` | 읽기 전용 int32, nullable. "When a volume is being restored from another volume's snapshot, will show the percentage completion of this cloning process. When this value is empty/null there is no cloning process currently happening on this volume. This value will update every 5 minutes during cloning." | 없음 | `0` | `null` (응답에서 빠짐) |
| `isRestoring` | 읽기 전용 boolean, 설명 "Restoring" | 없음 | 없음 | 없음 |
| `deleteBaseSnapshot` | boolean, 가변성 제한 없음, 기본 false | 보내지 않음, 응답에 없음 | 없음 | 없음 |
| `maximumNumberOfFiles` | 읽기 전용 | 없음 | **없음** | `21251126` (원본 볼륨과 같은 값) |
| `fileSystemId`, `mountTargets` | 읽기 전용 | 없음 | 있음 (원본과 다른 값, `ipAddress 10.0.1.4`) | 같음 |

  - `isRestoring`이 언제 `true`가 되는지는 [미확인]. 스냅샷 복원 녹화에는 한 번도 나오지 않았다 [녹화 R4]. 백업 복원용일 수 있다 [추론, `originatingResourceId` 설명이 "snapshot or backup"이라서].
  - `cloneProgress`가 사라질 때 etag가 바뀌었고(`00:31:38`), 같은 응답에서 `maximumNumberOfFiles`가 처음 나타났다 [녹화 R4, 엔트리 56→57 비교].
- **`deleteBaseSnapshot`**
  - 스펙: "If enabled (true) the snapshot the volume was created from will be automatically deleted after the volume create operation has finished. Defaults to false" [스펙 1, 2].
  - 문서: "By default, the new volume includes a reference to the snapshot ... referred to as the *base snapshot*. ... If you don't want the new volume to contain this base snapshot, select **Delete base snapshot**" [문서 3].
  - **두 출처가 지우는 대상을 다르게 읽힌다.** 스펙 문장만 보면 "볼륨을 만든 원본 스냅샷"을 지운다고도 읽히고, 문서는 "새 볼륨 안의 base 스냅샷"을 지운다고 쓴다. 녹화가 없어 실동작은 [미확인]. 문서가 "If you don't want the new volume to contain this base snapshot"이라고 대상을 분명히 하므로 새 볼륨 쪽일 가능성이 크다 [추론].
  - "after the volume create operation has finished"가 `Succeeded` 시점인지 clone 복사(`cloneProgress` null) 끝인지도 [미확인].
- **base 스냅샷 (녹화 R4, 엔트리 41·64)**

| 필드 | 원본 볼륨의 스냅샷 | 새 볼륨의 base 스냅샷 |
| --- | --- | --- |
| 이름 | `volumeName-9830/snapshot-6328` | `volume-4194/snapshot-6328` (같은 이름) |
| `snapshotId` | `a53c2a38-3486-a3fe-641a-34f0cbef75cf` | `6e6046a1-21b8-bb69-cc44-312ab78c71e7` (다름) |
| `created` | `2026-10-30T00:25:49.349Z` | `2026-10-30T00:25:49Z` (같은 시각, 초 단위로 잘림) |
| `systemData` | `createdByType: User` | `createdAt` = 위 시각, `lastModifiedByType: Application`, `lastModifiedAt: 00:29:46.712Z` (볼륨 생성 약 4분 뒤) |

  - base 스냅샷은 "does *not* consume any additional space" [문서 3].
  - 새 볼륨의 스냅샷 목록에는 base 스냅샷 하나만 있었다 [녹화 R4, 엔트리 64].
  - 새 볼륨의 base 스냅샷 DELETE는 `202`, 약 3초에 `Succeeded`였다(`cloneProgress`가 null이 된 뒤에 지웠다) [녹화 R4, 엔트리 65~68]. 단기 클론 녹화에서 base 스냅샷 삭제는 약 73초 걸렸다 [녹화 R5, 스냅샷 브리프 59행 인용].
- **허용 범위 (같은 풀/다른 풀/다른 계정, 서비스 수준, 프로토콜)**
  - 녹화는 **같은 계정·같은 풀**만 보여 준다 [녹화 R4].
  - 프로토콜: 포털 절차가 "The new volume uses the same protocol that the snapshot uses."라고 쓴다 [문서 3]. API가 다른 `protocolTypes`(예: 원본 NFSv3 → 새 볼륨 NFSv4.1)를 거절하는지는 [미확인]. NFSv3와 NFSv4.1 사이의 변경은 기존 볼륨 PATCH로도 허용된다(`protocolTypes`가 PATCH 모델에 있다) [스펙 2]. 그래서 NFS 버전끼리는 막지 않을 가능성이 있다 [추론]. NFS와 CIFS 혼합은 "Not allowed to mix protocol types CIFS and NFS"다 [문서 5].
  - 다른 풀: 주석 처리된 Elastic 절이 "The new volume must be in the same Elastic capacity pool that contains the source snapshot."이라고 쓴다 [문서 3, 29~37행 주석]. Elastic이 아닌 서비스 수준에서는 다른 풀이 허용된다고 읽을 수 있지만 [추론], 직접 쓴 문장은 찾지 못했다 [미확인]. 백업 복원은 "a different capacity pool within the same NetApp account"를 허용한다고 한다 [WebSearch 요약 14, 원문 미확인]. 백업 복원은 다른 기능이다.
  - 다른 계정·다른 리전: [미확인]. ONTAP FlexClone은 부모와 같은 aggregate에 있다 [추론, 문서 11 split 절의 "the aggregate containing the FlexClone volume and its parent"]. 다른 SVM으로의 클론은 ONTAP이 지원한다(`parent_svm`, "Cloning ... on a different SVM is not supported on MetroCluster") [문서 10, 11].
  - 서비스 수준: 새 볼륨은 자기 풀의 서비스 수준을 따른다(녹화 `Premium`) [녹화 R4]. 원본과 다른 서비스 수준의 풀에 만들 수 있는지는 위 "다른 풀"과 함께 [미확인].
- **`usageThreshold` 규칙**: 녹화는 원본과 같은 100 GiB였다 [녹화 R4]. 원본보다 작은 값, 스냅샷 사용량보다 작은 값의 규칙과 오류 코드는 [미확인]. 찾아본 곳: 스펙 `usageThreshold` 설명(일반 50 GiB~100 TiB만 씀), 문서 3·4·5, 녹화 R4·R5, WebSearch. 단서:
  - 백업 복원은 "Quota value must be at least 20% greater than the size of the backup"라고 한다 [WebSearch 요약 14, 원문 미확인].
  - 주석 처리된 Elastic 절: Elastic Zone-redundant에서는 "the volume quota is set to 1 GiB instead of the source volume's quota" [문서 3 주석]. 그러니 일반 서비스 수준에서는 사용자가 정한 quota를 쓴다고 읽힌다 [추론].
  - ONTAP FlexClone은 만들 때 "the nominal size of the FlexVol volume is the same as its parent's size"다 [문서 12]. ANF가 이 크기를 사용자 `usageThreshold`로 바꾸는 시점(생성 직후 resize인지)은 [미확인].

### 비동기 동작

| 작업 | 실서비스 응답 | 헤더 | 본문 | 작업 상태 | `action` | 소요 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 볼륨 PUT (`snapshotId` 포함) | `201` | `Azure-AsyncOperation`, `Location`. `Retry-After` 없음 | 요청 속성 + `serviceLevel`, `effectiveNetworkFeatures`, `language: c.utf-8`, `provisioningState: Creating`. `originatingResourceId`·`fileSystemId`는 아직 없음 | `Creating` (`percentComplete 0.0`) → `Succeeded` (`100.0`) | `CREATE` | **약 11초** (`startTime 00:25:53.48`, `endTime 00:26:04.69`) | [녹화 R4, 엔트리 43~49] |
| (비교) 같은 녹화의 일반 볼륨 PUT | `201` | 같음 | `Creating` | 같음 | `CREATE` | 약 6분 (`00:19:47`→`00:25:48`) | [녹화 R4, 엔트리 17~35] |
| 완료 뒤 백그라운드 복사 | — | — | GET의 `cloneProgress: 0` | `provisioningState`는 계속 `Succeeded` | — | 약 5분 45초 뒤 `cloneProgress` 사라짐 | [녹화 R4, 엔트리 50~57] |

- 일반 볼륨 생성과 응답 코드·헤더·상태 이름이 같다. 복원 전용 상태(`Restoring` 등)는 녹화에 없다 [녹화 R4].
- 녹화의 원본 볼륨은 거의 빈 볼륨이었다. 크기에 따라 "minutes to hours"가 걸릴 수 있다고 문서가 쓴다 [문서 3]. 이것이 `Succeeded`까지의 시간인지, 백그라운드 복사(`cloneProgress`) 시간인지는 문서가 나누지 않는다. 문서 4가 "near-instantaneous ... almost immediately available for access, while the actual volume and snapshot data blocks are being copied over"라고 하므로 후자로 보인다 [추론].
- 녹화의 테스트는 `Succeeded` 뒤 1분마다 볼륨 GET을 반복하다가 `cloneProgress`가 사라진 뒤 정리를 시작했다 [녹화 R4, 엔트리 50~57]. 테스트 코드가 무엇을 기다렸는지는 원문을 보지 않았다 [미확인, azure-sdk-for-net 테스트 디렉터리 목록만 받음].

### 제약과 한도 (질문 2, 질문 4)

- **복원(복사) 중 원본 삭제 금지**
  - "Depending on volume size and capacity, this process can take considerable time during which the parent volume and snapshot can't be deleted." [문서 4, 115행]
  - "You can't delete a snapshot if it's part of an active file-restore operation or if it's in the process of being cloned." [문서 6]
  - 거절할 때의 HTTP 코드와 오류 코드·메시지는 [미확인]. 녹화는 새 볼륨을 먼저 지우고 원본 스냅샷을 나중에 지웠다 [녹화 R4, 엔트리 65~82].
- **복원이 끝난 뒤의 독립성**: "After this process is completed, the volume is independent and disassociated from the original volume, and source volumes and snapshot can be managed or removed independently from the new volume." [문서 4]
  - 그래서 복사가 끝난 뒤에는 원본 스냅샷·원본 볼륨 삭제, 원본 revert가 새 볼륨에 영향을 주지 않는다고 본다 [추론, 문서 4에서]. 녹화로 관찰한 순서는 아니다.
  - 복사 중 원본을 revert하면: 문서가 "chained restore operations, such as restoring a snapshot to a new volume while the originating volume itself is being restored from a snapshot, should be avoided"라고 권고한다 [문서 3]. 거절되는지, revert가 원본 스냅샷(고른 스냅샷보다 새 것)을 지우려 할 때 무슨 일이 생기는지는 [미확인]. revert는 고른 스냅샷 뒤의 스냅샷을 지운다 [스냅샷 브리프 86행 인용].
- **새 볼륨의 사용 가능 시점**: "The volume can be used by NFS and SMB clients immediately while the restore operation is completing in the background." [문서 3]. 녹화에서도 `Succeeded` 직후 GET에 `mountTargets`가 있었다 [녹화 R4, 엔트리 50].
- **복사 중 새 볼륨에서 할 일**: "Only enable backup, snapshots, and replication ... on the new volume _after_ it's fully restored from the snapshot. To ensure the volume is fully restored, check the progress indicator in the volume details." [문서 3]. 권고이고, 거절되는지는 [미확인]. ONTAP은 split 중 FlexClone의 새 스냅샷을 만들 수 없다 ("New snapshots of the FlexClone volume cannot be created during the split operation") [문서 11].
- **동시 실행**: "only perform one 'restore snapshot to new volume' operation at a time" (권고) [문서 3]. CRR/CZR 작업은 복원 중 중단되고 추가할 수 없다 [문서 3].
- **공간 (질문 4)**
  - 새 볼륨도 일반 볼륨처럼 `usageThreshold`만큼 풀 할당량을 쓴다 [추론]. 근거: 풀 할당은 볼륨 quota 합계로 계산된다("Pool size too small for total volume size": "create a volume that is larger than the free space in the capacity pool") [문서 5, 333~340행]. 복원 볼륨에 다른 규칙이 있다는 문장은 찾지 못했다.
  - "By nature of the data copy process, storage capacity pool consumption doubles when the restore completes, and the new volume show the full active capacity of the original snapshot." [문서 4]. 즉 복사가 끝나면 새 볼륨이 스냅샷 시점의 활성 데이터 전체만큼 사용량을 갖는다 [문서 4]. 이것이 풀 "할당"(quota 합계)이 아니라 "사용량"을 말하는지는 문서가 나누지 않는다 [미확인].
  - base 스냅샷은 추가 공간을 쓰지 않는다 [문서 3]. 스냅샷 공간은 볼륨 quota에 포함된다(스냅샷 브리프 129행 인용).
  - 단기 클론은 이와 달리 부모와 블록을 공유하고 `inheritedSizeInBytes`를 보고한다 [문서 4, 스펙 2]. 범위 밖이다.

### 오류 상황

- **ANF 문서에 있는 것** [문서 5]
  - "Failed to split new volume from source volume snapshot": "This error can occur when you try to create a volume from a snapshot." 원인 "volume ends in an error state", 해결 "Delete the volume, then retry the volume creation operation from the snapshot." 코드 이름(`code`)과 HTTP 상태는 문서에 없다.
  - "The requested {resource} was not found.": 없는 볼륨·스냅샷을 참조할 때 [문서 5, 404~409행]. `snapshotId`가 없는 스냅샷을 가리킬 때 이 오류가 PUT 응답(4xx)으로 오는지 작업 `Failed`로 오는지는 [미확인].
  - 스냅샷 GET 404의 본문은 확인됐다: `ResourceNotFound`, "The requested snapshot 'snapshot-63281' was not found on the volume 'account9903/pool1/volumeName-9830'. ..." [녹화 R4, 엔트리 58]. 이것은 GET이고 볼륨 PUT의 검사 결과는 아니다.
- **[미확인]**: 형식이 틀린 `snapshotId`(ARM ID가 아님, 다른 리소스 타입), 다른 계정·풀의 스냅샷, 원본보다 작은 `usageThreshold`, 다른 `protocolTypes`, 복사 중 원본 스냅샷·볼륨 DELETE, 재PUT으로 `snapshotId` 변경. 찾아본 곳: 녹화 R4·R5(오류 응답 없음), 스펙, 문서 3·4·5·6, WebSearch 2회.

## 데이터 플레인에서 보이는 효과

- 새 볼륨을 마운트하면 **스냅샷 시점의 내용**이 보인다 ("point-in-time recovery", "the new volume show the full active capacity of the original snapshot") [문서 3, 4].
- 새 볼륨은 바로 마운트할 수 있다. 백그라운드 복사 중에도 클라이언트가 쓴다 [문서 3, 4].
- 새 볼륨은 원본과 다른 `fileSystemId`와 마운트 IP를 갖는다(녹화: 원본 `bfb49e94-...`, 새 볼륨 `61b273f9-...`) [녹화 R4].
- 새 볼륨의 `.snapshot`에는 base 스냅샷(원본과 같은 이름)이 보인다 [추론, 녹화 R4의 스냅샷 목록과 문서 3 "The snapshot used to create the new volume is also present on the new volume"(문서 4)에서].
- 새 볼륨에 쓰면 원본 볼륨과 스냅샷은 바뀌지 않는다 ("separate, independent volumes") [문서 4]. FR-07 수락 기준과 같다.
- 원본 볼륨에 스냅샷 뒤에 쓴 내용은 새 볼륨에 보이지 않는다 [추론, "point-in-time"에서].

## ONTAP 대응 개념 (질문 3)

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| 스냅샷에서 새 볼륨 (restore to new volume) | FlexClone 볼륨 생성 + clone split | ANF 문서가 이 작업을 "clones"라고 부르고, 오류 문구가 "split new volume from source volume snapshot"이다. ANF가 FlexClone을 쓴다고 직접 쓴 공식 문장은 찾지 못했다 | 대응 [추론, 문서 4·5에서] |
| (구분) revert | SnapRestore (`volume snapshot restore`, REST `PATCH ...?restore_to.snapshot`) | 제자리 복원이다. 새 볼륨 복원과 다르다 | FR-06 브리프 인용 |
| `snapshotId` (원본 스냅샷) | `clone.parent_volume` + `clone.parent_snapshot` | ONTAP은 부모 스냅샷을 지정하지 않으면 스냅샷을 새로 만든다 | ONTAP [문서 11 create-flexclone-task], 대응 [추론] |
| `cloneProgress` | `clone.split_complete_percent` ("Percentage of FlexClone volume blocks split from its parent volume") | ANF 값이 null이 되는 것은 split 완료(더는 FlexClone이 아님)와 맞다 | 필드 [문서 9], 대응 [추론] |
| 새 볼륨의 base 스냅샷 | FlexClone이 부모와 공유하는 base 스냅샷 ("The snapshot used to create a FlexClone volume is also shared with the parent volume") | AFF의 ONTAP 9.4 이상 split에서는 "Existing snapshots are not deleted" | [문서 12, 11] |
| 복사 중 원본 스냅샷·볼륨 삭제 금지 | FlexClone이 있는 동안 부모 볼륨 삭제 불가. 부모 스냅샷은 `busy, vclone`, owner "volume clone" | 스냅샷 DELETE 오류 `1638543` "Failed to delete snapshot because it has an owner"가 이 경우로 보인다 | 부모 볼륨 [문서 11]. busy/owner [KB 13, WebSearch 요약만, 원문 미확인]. `1638543`과 vclone의 연결 [추론] |
| 복사 뒤 독립 | split 뒤 일반 FlexVol (`clone-volume false`). "After a FlexClone volume is split from its parent the two cannot be rejoined." | | [문서 11] |
| 복사 중 새 볼륨 스냅샷 권고 | split 중 FlexClone의 새 스냅샷 생성 불가 | | [문서 11], 대응 [추론] |
| 공간 2배 | split 뒤 "both the parent FlexVol volume and the clone require the full space allocation determined by their volume guarantees". 새 FlexClone은 명목 크기의 약 0.5%만 쓴다 | AFF 9.4 이상 non-guaranteed 볼륨은 split이 물리 블록을 공유하고 데이터를 복사하지 않는다. ANF 문서의 "data copy process"와 다르다 | [문서 11, 12, 4] |

### ONTAP REST FlexClone API (storage agent 부분집합 후보용)

기준: ONTAP 9.19.1 `POST /storage/volumes` 문서 [8]와 `netapp-ontap` 9.19.1.0 `resources/volume.py`, `models/volume_clone.py` [9][10].

- **생성**: `POST /api/storage/volumes` (CLI `volume create`, `volume clone create`) [문서 8].
  - 일반 볼륨 필수 속성: `svm.uuid|svm.name`, `name`, `aggregates.name|aggregates.uuid` [문서 8].
  - FlexClone 예시 본문은 aggregate 없이 이렇다 [문서 9]:
    ```json
    {"name": "vol1_clone", "clone": {"parent_volume": {"name": "vol1"}, "is_flexclone": true}, "svm": {"name": "vs0"}}
    ```
  - `clone`의 POST 가능 필드: `is_flexclone`("This field needs to be set when creating a FlexClone volume. Valid in POST."), `parent_volume.{name,uuid}`, `parent_snapshot.{name,uuid}`, `parent_svm.{name,uuid}`, `lun_name`, `qtree_name` [문서 10].
  - 응답: `202 Accepted` + `{"job": {"uuid": ...}}`, 헤더 `Location`. `return_timeout` 안에 끝나면 `201 Created` [문서 8]. job 모델은 볼륨 조사의 `job.py.txt`와 같다.
  - 응답에 새 볼륨 `uuid`가 바로 들어 있지 않다. job이 끝난 뒤 `GET ?name=`으로 찾는다 [추론, 스냅샷 POST와 같은 구조. 스냅샷 브리프 169행 인용].
  - 클론 관련 오류 코드 [문서 8]:

| 코드 | 메시지 |
| --- | --- |
| 524601 | Parent volume "name" not found. |
| 918243 | The specified snapshot UUID is not correct for the specified snapshot name. |
| 918236 | The specified "parent_volume.uuid" and "parent_volume.name" do not refer to the same volume. |
| 918244 | Invalid "volume.type" for clone volume. |
| 918247 | Specifying a value is not valid for a volume FlexClone creation. |
| 524597 / 524819 | Failed to create the clone volume (on the node). |
| 917526 | The volume name specified is a duplicate. |
| 460770 | [Job "jobid"] Job failed. |
| 917775 | Volume "{0}:{1}" is not online. |

  - 부모 스냅샷이 없을 때의 전용 코드는 위 목록에서 찾지 못했다 [미확인]. 9.19.1 문서는 이 코드들이 HTTP 오류인지 job 실패인지 나누지 않는다 [문서 8].
- **조회 필드** (`clone.*` gettable) [문서 10]: `is_flexclone`, `has_flexclone`("Specifies whether this volume is a parent of any FlexClone volume"), `parent_volume.{name,uuid}`, `parent_snapshot.{name,uuid}`, `parent_svm.{name,uuid}`, `split_initiated`, `split_complete_percent`, `split_estimate`("Space required by the containing-aggregate to split the FlexClone volume"), `inherited_physical_used`, `inherited_savings`.
- **split**: `PATCH /api/storage/volumes/{uuid}` 본문 `{"clone": {"split_initiated": true}}`로 시작하고, `false`로 멈춘다 [문서 9]. PATCH 가능 필드는 `split_initiated`, `parent_snapshot.{name,uuid}`다 [문서 10]. CLI는 `volume clone split start|show|stop`이고, 완료 확인은 `volume show -fields clone-volume`이 `false`가 되는 것이다 [문서 11]. split 완료 뒤 REST `clone.is_flexclone`이 `false`가 되는지는 [추론, CLI `clone-volume`에서].
- **split 동작** [문서 11]: 백그라운드에서 돌고, split 중에도 clone과 부모의 데이터에 접근할 수 있다. FlexClone을 offline하면 멈추고 online하면 이어진다. split에는 부모와 clone이 모두 online이어야 한다.
- **부모 쪽 제약**: "After you create a FlexClone volume, you cannot delete the parent volume while the FlexClone volume exists." [문서 11]. 부모 스냅샷 삭제는 owner 때문에 거절된다(`busy, vclone`) [KB 13, 원문 미확인]. 해결은 split 또는 clone 삭제라고 한다 [KB 13·커뮤니티, WebSearch 요약].

## 구현 범위 후보

### 이번에 재현할 것 (근거)

- 볼륨 PUT의 `snapshotId`(ARM ID)를 받아 스냅샷 시점 내용을 가진 새 볼륨을 만든다. 응답·상태 흐름은 기존 볼륨 생성과 같다(`201`, `Creating`→`Succeeded`, `action CREATE`) [녹화 R4].
- GET에 `snapshotId`와 `originatingResourceId`(같은 ARM ID)를 남긴다 [녹화 R4].
- 새 볼륨에 같은 이름의 base 스냅샷 리소스를 만든다(새 `snapshotId`, `created`는 원본 시각) [녹화 R4, 문서 3].
- 새 볼륨에 써도 원본 볼륨·스냅샷이 바뀌지 않는다 (FR-07 수락 기준) [문서 4].
- storage agent: `POST /api/storage/volumes`에 `clone.is_flexclone`, `clone.parent_volume`, `clone.parent_snapshot`을 받는 부분집합. 202 + job [문서 8, 10].

### 다음으로 미룰 것 (이유)

- 단기 클론(`ShortTermClone`, `inheritedSizeInBytes`, `acceptGrowCapacityPoolForShortTermCloneSplit`), `splitCloneFromParent`: 다른 기능이다.
- 백업에서 복원(`backupId`): 백업 기능이 없다.
- `isRestoring`: 스냅샷 복원에서 쓰이는 것을 관찰하지 못했다.
- ONTAP `split_estimate`, `inherited_*`, `lun_name`, `qtree_name`: ARM 쪽에 대응이 없다.

### 리더·사용자가 정해야 할 선택지

1. **허용 범위.** 다른 풀·계정의 스냅샷을 받을지. (a) 같은 풀만 (녹화가 보여 준 범위), (b) 같은 계정의 다른 풀까지 (Elastic 주석의 반대 해석, 백업 복원 규칙과 같음), (c) 제한 없음. 실서비스 규칙은 미확인이다. 클론은 모든 풀이 같은 thin pool(aggr0)을 쓰므로 기술적으로는 (b)도 가능하다 [추론, CLAUDE.md D-11].
2. **`usageThreshold` 하한.** (a) 원본 볼륨 `usageThreshold` 이상, (b) 스냅샷 시점 사용량 이상, (c) 일반 볼륨 규칙(50 GiB 이상, 풀 여유)만. 실서비스 규칙과 오류 코드는 미확인이다. 원본보다 작게 허용하면 데이터 플레인에서 파일 시스템 축소가 필요할 수 있다 [추론]. S6 결과와 함께 정한다.
3. **`protocolTypes`.** 원본과 다른 NFS 버전을 허용할지. 문서는 "same protocol"(포털), 스펙은 PATCH로 NFS 버전 변경을 허용한다. 실서비스 검사는 미확인.
4. **`cloneProgress` 표현.** 클론의 데이터 플레인에 ANF식 백그라운드 복사가 없다면 (a) 처음부터 null, (b) `0`을 잠깐 보였다가 null, (c) 실제 진행률. 어느 쪽이든 ANF와의 차이를 개념 문서에 적는다.
5. **복사 중 원본 삭제 금지 창.** (a) 클론의 복사 단계가 없다면 바로 독립으로 두고 삭제를 허용한다, (b) 복사 단계가 있으면 그동안 원본 스냅샷·볼륨 DELETE를 거절한다(코드는 클론이 정함, ONTAP은 `1638543`). ANF 오류 코드는 미확인.
6. **`deleteBaseSnapshot`.** 받을지, 받으면 무엇을 지울지(문서: 새 볼륨의 base 스냅샷 / 스펙 문장은 모호), 언제 지울지(`Succeeded` 시점 / 복사 끝).
7. **재PUT의 `snapshotId` 변경.** (a) 400으로 거절(다른 create-only 속성처럼 "cannot be changed"), (b) 무시. 실동작 미확인.
8. **agent API 모양.** ONTAP처럼 `POST /api/storage/volumes`에 `clone.*`를 받을지, `parent_snapshot`을 uuid로 받을지 name으로 받을지(ONTAP은 둘 다 받고 불일치를 `918243`으로 거절). split을 따로 둘지(`PATCH clone.split_initiated`).

### 검증 기준 후보 (클라이언트에서 관찰)

- V1 (계약): `snapshotId`에 스냅샷 ARM ID를 넣은 볼륨 PUT → `201` + `Azure-AsyncOperation`, 본문 `Creating`, 작업 `Creating`→`Succeeded`, `action: CREATE`. 그 뒤 GET에 `snapshotId`와 `originatingResourceId`가 같은 ARM ID로 있다.
- V2 (내용): 원본에 파일 A를 쓴다 → 스냅샷 S → 원본에서 A를 바꾸고 B를 추가 → S로 새 볼륨 N. N을 마운트하면 A는 S 시점 내용이고 B는 없다.
- V3 (독립성, FR-07): N에 쓰고 지운다 → 원본 볼륨의 A·B와 원본 `.snapshot/S/A`가 그대로다. 반대로 원본에 쓴 내용도 N에 보이지 않는다.
- V4 (base 스냅샷): N의 스냅샷 목록에 이름 S, 원본과 다른 `snapshotId`, `created`가 원본 S와 같은 시각인 항목이 있다. N의 `.snapshot/S/A`가 보인다.
- V5 (마운트): `Succeeded` 직후 GET에 `mountTargets`가 있고 클라이언트가 바로 마운트된다.
- V6 (독립 뒤 삭제·되돌리기): 원본 스냅샷 S와 원본 볼륨을 지우거나 원본을 이전 스냅샷으로 revert해도 N의 내용과 마운트가 그대로다.
- V7 (오류): 없는 스냅샷 ARM ID, 형식이 틀린 `snapshotId`는 실패하고 볼륨이 만들어지지 않는다(코드는 선택지에 따라). 선택지 1·2·3에서 거절하기로 한 입력은 거절된다.
- V8 (갱신 불가): PATCH 본문에 `snapshotId`를 넣으면 반영되지 않는다(선택지 7).
- V9 (공간): N의 `usageThreshold`가 풀 할당량에 더해지고, 풀 여유보다 큰 N은 일반 볼륨과 같은 오류로 거절된다.

## 미확인 목록

| 항목 | 설계를 막는가 | 찾아본 곳 |
| --- | --- | --- |
| 다른 풀·다른 계정·다른 서비스 수준의 스냅샷 허용 여부와 오류 | 선택지 1 (클론 규칙으로 정할 수 있음) | 녹화 R4·R5(같은 풀만), 문서 3(Elastic 주석만), 스펙, WebSearch 2회 |
| `usageThreshold` 하한(원본 크기·사용량)과 오류 코드 | 선택지 2. S6의 크기 처리와 함께 정해야 한다 | 스펙 설명, 문서 3·4·5, 녹화, WebSearch(백업 복원 20% 규칙만, 원문 미확인) |
| 다른 `protocolTypes` 허용 여부 | 선택지 3 | 문서 3(포털 "same protocol"), 스펙 PATCH 모델 |
| 복사 중 원본 스냅샷·볼륨 DELETE의 HTTP·오류 코드 | 선택지 5 (문서로 "거절"은 확인됨) | 녹화 R4(순서상 관찰 불가), 문서 4·5·6 |
| 복사 중 원본 revert의 동작 | 아니다 (권고만 있음) | 문서 3 |
| `deleteBaseSnapshot`이 지우는 대상과 시점 | 선택지 6 | 스펙 1·2, 문서 3. 녹화 없음 |
| 재PUT으로 `snapshotId`를 바꿀 때 | 선택지 7 | 문서 5 "cannot be changed" 목록, 녹화 |
| `isRestoring`이 `true`가 되는 조건 | 아니다 | 녹화 R4 (항상 없음), 스펙 |
| 없는 스냅샷을 가리키는 PUT이 4xx인지 작업 `Failed`인지 | 아니다 (클론 규칙으로 정할 수 있음) | 녹화, 문서 5 |
| 녹화 테스트가 기다린 조건 (`cloneProgress` null인지) | 아니다 | azure-sdk-for-net 테스트 디렉터리 목록만 받음 (커밋 `b45e5bc0`) |
| ANF가 FlexClone + split을 쓴다는 공식 문장 | 아니다 (개념 문서에서 [추론]으로 설명) | 문서 3·4·5, ONTAP 문서 |
| ONTAP 부모 스냅샷 `busy, vclone`/owner 원문 | 아니다 | NetApp KB (로그인 일부 필요, WebSearch 요약만) |
| ONTAP에서 부모 스냅샷이 없을 때의 전용 오류 코드 | agent 오류 모델 설계 시 | 문서 8 오류 표 |

## 후속 조사 목록

- 단기 클론(`ShortTermClone`, 32일 뒤 일반 볼륨 전환, `splitCloneFromParent`, `inheritedSizeInBytes`) [문서 4, 스펙 2, 녹화 R5].
- 백업에서 새 볼륨 복원(`backupId`, quota 20% 규칙) [WebSearch 요약 14].
- CRR 대상 볼륨의 스냅샷에서 새 볼륨 만들기 [문서 4, 122행].
- ONTAP `split_estimate`와 aggregate 여유 확인 절차 [문서 11].

## 출처

- [1] Azure REST API specs — `Volume.tsp` (`snapshotId` 147행, `deleteBaseSnapshot` 158행, `isRestoring` 239행, `cloneProgress` 372행, `originatingResourceId` 507행, `VolumeRevert` 1618행). 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`. 사본은 재사용: `_workspace/volume/sources/spec/Volume.tsp`
- [2] Azure REST API specs — `stable/2026-08-01/netapp.json` (`VolumeProperties`, `VolumePatchProperties`, `Volumes_SplitCloneFromParent`). 같은 커밋. 사본은 재사용: `_workspace/capacity-pool/sources/spec/netapp-2026-08-01.json`
- [3] Microsoft Learn — Restore a snapshot to a new volume (`snapshots-restore-new-volume.md`, ms.date 02/03/2026). azure-docs 커밋 `548a6fcfecc7e850241c77f1a29db21d781d5d1b`. 사본은 재사용: `_workspace/snapshot/sources/docs/`
- [4] Microsoft Learn — How Azure NetApp Files snapshots work (`snapshots-introduction.md`, 113~134행). 같은 커밋. 사본은 재사용: `_workspace/volume/sources/docs/`
- [5] Microsoft Learn — Troubleshoot Resource Provider errors (`azure-netapp-files-troubleshoot-resource-provider-errors.md`, 323~340행, 404~409행, 669~676행). 같은 커밋. 사본은 재사용: `_workspace/snapshot-revert/sources/docs/`
- [6] Microsoft Learn — Delete snapshots (`snapshots-delete.md`, 22행). 같은 커밋. 사본은 재사용: `_workspace/snapshot/sources/docs/`
- [7] (미사용 번호)
- [8] NetApp ONTAP 9.19.1 REST API reference — `POST /storage/volumes` — https://docs.netapp.com/us-en/ontap-restapi/post-storage-volumes.html (2026-11-08 curl, 옛 주소 `/ontap/post-storage-volumes.html`은 301). 사본: `sources/ontap/post-storage-volumes.html`, 텍스트 변환본 `post-storage-volumes.txt`
- [9] `netapp-ontap` 9.19.1.0 휠의 `netapp_ontap/resources/volume.py` (FlexClone POST 예시 191~221행, split PATCH 예시 605~626행, `post_collection` 문서). 사본은 재사용: `_workspace/volume/sources/ontap/volume.py.txt`. 휠 sha256 `916c329e9fb968d200c9451ebb10eb4ab80b9fc96c24ce674a0b1782c1ad9ab0` (`_workspace/snapshot/sources/ontap/wheel/`)
- [10] 같은 휠의 `netapp_ontap/models/volume_clone.py`. 텍스트로만 추출했고 실행하지 않았다. sha256 `23c33dc744a8b6dce51ece8c6faf10edf30c8712e2522aeee04133aca2e5887f`. 사본: `sources/ontap/netapp_ontap__models__volume_clone.py.txt`
- [11] NetAppDocs/ontap — `volumes/create-flexclone-task.adoc`, `volumes/split-flexclone-from-parent-task.adoc`. 커밋 `37d53f2a6cff395e1fb457f522c61826a8dbf379`. 사본: `sources/ontap/adoc__*.adoc`
- [12] NetAppDocs/ontap — `volumes/flexclone-efficient-copies-concept.adoc`, `volumes/determine-space-used-flexclone-task.adoc`. 같은 커밋. 사본: `sources/ontap/adoc__*.adoc`
- [13] NetApp KB — "FlexClone preventing Snapshot deletion" — https://kb.netapp.com/on-prem/ontap/DP/SnapMirror/SnapMirror-KBs/FlexClone_preventing_Snapshot_deletion , 커뮤니티 "Snapshot Delete busy,vclone" — https://community.netapp.com/t5/ONTAP-Discussions/Snapshot-Delete-busy-vclone/td-p/116522 (WebSearch 요약만, 원문 미확인, 2026-11-08)
- [14] Microsoft Learn — Restore a backup to a new volume — https://learn.microsoft.com/en-us/azure/azure-netapp-files/backup-restore-new-volume (WebSearch 요약만, 원문 미확인, 2026-11-08). 백업 복원 규칙의 단서로만 썼다.
- **녹화.** 계정 조사 때 받은 사본을 재사용했다. .NET 태그 `net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c`.
  - R4 `SnapshotTests__CreateVolumeFromSnapshot.json` (2026-10-30, `2026-08-15-preview`). 사본: `_workspace/netapp-account/sources/recordings/net/`. 이 브리프의 엔트리 번호는 이 파일의 `Entries` 배열 색인이다(43: 복원 PUT, 44~49: 작업 상태, 50~57: 볼륨 GET, 64: 새 볼륨 스냅샷 목록, 65~82: 정리).
  - R5 `SnapshotTests__CreateShortTermCloneVolumeFromSnapshot.json` (스냅샷 브리프의 base 스냅샷 삭제 시간만 인용).
- (참고) azure-sdk-for-net `sdk/netapp/Azure.ResourceManager.NetApp/tests` 디렉터리 목록, 커밋 `b45e5bc0115ee91195fd433981781c417ac76bcb`. 사본: `sources/spec/net-tests-dir.json`. 테스트 코드는 받지 않았다.
- 이전 브리프 인용: `_workspace/snapshot/01_researcher_brief.md`(86~88행 revert·base 스냅샷, 59행 base 스냅샷 삭제 시간, 129행 스냅샷 공간, 169행 ONTAP POST 흐름), `_workspace/volume/01_researcher_brief.md`(일반 볼륨 계약), `_workspace/snapshot-revert/01_researcher_brief.md`(SnapRestore).

## 변경 이력

- 2026-11-08: 골격 저장 뒤 처음 작성. 필수 질문 다섯 가지에 답했고, 허용 범위·크기 규칙·거절 오류 코드는 [미확인]으로 남겼다.
