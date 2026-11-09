# 스냅샷 조사 브리프

- 조사 상태: **완료 (보완 질문 1~3), 보완 질문 4는 부분**.
  - 처음 조사(한도 도달)에서는 질문 1(ARM 계약)과 4(공간)에 답했다.
  - 2026-11-08 보완 조사에서 다음을 답했다.
    - ONTAP REST 스냅샷 API (보완 1)
    - 스냅샷이 남은 볼륨의 DELETE (보완 2)
    - ONTAP `.snapshot` 옵션 (보완 3)
  - 같은 이름 PUT 재전송(보완 4)은 ARM 쪽 근거를 찾지 못했다. ONTAP 쪽 중복 이름 오류만 확인했다.
  - 남은 항목은 "미확인 목록"에 있다.
- 조사일: 2026-11-08
- 기준 api-version: `2026-08-01` (스펙 [1][2][3]). 녹화는 `2026-08-15-preview`다 [녹화 R1~R5]. ONTAP REST는 9.19.1 문서와 `netapp-ontap` 9.19.1.0을 기준으로 했다 [15][16].
- 범위 가정: 리더가 정한 범위(FR-05: 생성, 조회, 목록, 삭제, NFS `.snapshot`)를 그대로 따랐다. FR-06·FR-07은 스냅샷 리소스에 거는 제약만 봤다. `restoreFiles`와 스냅샷 정책은 이름과 존재만 적었다.

## 요약 (5줄 이내)

1. 스냅샷은 볼륨의 자식 ProxyResource다. 본문은 `location`(필수)과 읽기 전용 `snapshotId`, `created`, `provisioningState`뿐이고, tags와 이름 패턴은 없다 [스펙 1, 2]. 실서비스 PUT은 `201` + `Azure-AsyncOperation`/`Location`에 본문 `Creating`을 돌려준다. 작업 상태는 `Creating`에서 `Succeeded`(`action CREATE`)로 간다. DELETE는 `202`, `Deleting`에서 `Succeeded`(`action DELETE`)로 간다 [녹화 R1, R2].
2. ONTAP REST에서 스냅샷 생성은 `POST /api/storage/volumes/{volume.uuid}/snapshots`이고 필수 필드는 `name` 하나다. 응답은 `202` + `job`이고, 완료를 기다리면 `201`이다. 같은 이름이면 오류 `525059`, 개수 초과면 `525062`다. DELETE는 `.../snapshots/{uuid}`(스냅샷 UUID로 지정)이고 `202` + `job` 또는 `200`이다 [문서 15, 16].
3. 볼륨을 지우면 그 볼륨의 스냅샷도 함께 지워진다("online snapshots ... are deleted with the volume deletion") [문서 6]. 볼륨당 한도는 ANF 255개다 [문서 9]. ONTAP 9.4 이상 FlexVol은 1023개다 [문서 19].
4. NFSv3에서 `.snapshot`은 마운트 지점(루트)의 `ls -a`에만 보인다. 그 밖의 디렉터리에서는 목록에 보이지 않지만 이름으로 들어갈 수 있다. NFSv4.1에서는 어디서도 목록에 나오지 않고 이름으로만 들어갈 수 있다. ONTAP의 `-snapdir-access false`는 접근 자체를 끄고, `-v3-hide-snapshot`은 NFSv3 목록에서만 숨긴다 [문서 5, 7, 17, 18, 20, 21].
5. 스냅샷 공간은 ANF 볼륨 할당량에 들어간다. ANF에는 snapshot reserve 설정이 없다 [문서 4, 6, 10]. ONTAP 볼륨의 기본 reserve는 5%다(`-percent-snapshot-space`) [문서 18, 22].

## 사용자에게 보이는 동작

### 리소스와 API (질문 1)

- **경로**: `.../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}/snapshots/{snapshotName}`. 목록은 `.../volumes/{v}/snapshots`다 [스펙 2].
- **작업과 스펙상 응답** [스펙 1, 2, 3]

| 작업 | operationId | 스펙 응답 | LRO 옵션 |
| --- | --- | --- | --- |
| GET 단건 | Snapshots_Get | 200 `Snapshot` | 없음 |
| GET 목록 | Snapshots_List | 200 `SnapshotsList` (`value` 필수, `nextLink`) | `x-ms-pageable nextLinkName=nextLink` |
| PUT | Snapshots_Create | 201 `Snapshot` + `Location`, `Retry-After` / 202 (본문 없음) + `Location`, `Retry-After` | `final-state-via: location` |
| PATCH | Snapshots_Update | 200 `Snapshot` / 202 + `Location`, `Retry-After` | `final-state-via: location` |
| DELETE | Snapshots_Delete | 200 / 202 + `Location`, `Retry-After` / 204 | `final-state-via: location` |
| POST `restoreFiles` | Snapshots_RestoreFiles | 200 / 202 | 범위 밖 |

- TypeSpec은 PUT을 "CreateOrReplace"로 선언한다. 그런데 응답에 200은 없고 201과 202뿐이다. 응답 코드 규칙 경고(`arm-put-operation-response-codes`)는 "For backward compatibility"를 이유로 꺼져 있다 [스펙 1]. 그래서 **같은 이름으로 다시 PUT했을 때의 응답은 스펙만으로 정할 수 없다** [추론, 스펙 1의 응답 목록에서]. 녹화에도 재전송은 없다 [미확인].
- **본문 모델** [스펙 1, 2]
  - `location`: string, 필수, `x-ms-mutability [read, create]`.
  - `properties.snapshotId`: 읽기 전용. 길이 36, UUID 패턴이며 설명은 "UUID v4".
  - `properties.created`: 읽기 전용, `date-time`.
  - `properties.provisioningState`: 읽기 전용 string. enum 없음.
  - `id`, `name`, `type`, `systemData`는 ProxyResource에서 온다. **`tags`는 없다.**
  - `SnapshotPatch`는 빈 모델 `{}`다. TypeSpec에 "empty-updateable-properties ... backward compatibility"라는 경고 억제가 있다. 스펙 예시는 PATCH 본문 `{}`에 200(전체 Snapshot) 또는 202를 돌려준다 [스펙 1, 3]. PATCH는 녹화에 없다 [미확인].
- **이름 규칙**: TypeSpec이 `NamePattern = ""`이고, OpenAPI의 `snapshotName`에도 pattern과 길이 제한이 없다 [스펙 1, 2]. 실서비스가 어떤 이름을 거절하는지는 찾지 못했다 [미확인]. ONTAP 쪽에는 이름 관련 오류가 둘 있다. `1638518` "The specified snapshot name is invalid"와 `1638477` "User-created snapshot names cannot begin with the specified prefix"다 [문서 15]. 실제로 금지되는 문자와 접두어 목록은 [미확인]. 녹화에서 쓴 이름은 `snapshot-4323`, `sdk-py-tests-snapshot-1-cd95297f`처럼 영숫자와 `-`로만 되어 있다 [녹화].
- **응답 본문 모양** [녹화 R1, 2026-10-30, `2026-08-15-preview`]
  - `name`은 `"account745/pool1/volumeName-8064/snapshot-4323"`, `type`은 `Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots`다. 스펙 예시와 같다 [스펙 3].
  - 완료 뒤 GET: `{"id", "name", "type", "location", "properties": {"provisioningState": "Succeeded", "snapshotId": "484edf8a-7581-ba01-efec-3dbbf8c78b25", "created": "2026-10-30T00:00:51.628Z"}, "systemData": {...}}`.
  - **녹화의 `snapshotId`는 UUID v4 모양이 아니다.** 셋째 묶음이 `ba01`, `292c`, `79ed`이고 `4`로 시작하지 않는다 [녹화 R1, R2]. 스펙은 "UUID v4"라고 설명한다 [스펙 2]. 볼륨 `fileSystemId`(`0babd4c7-ea84-dc0d-...`)도 같은 모양이다 [녹화 R3]. 그래서 ANF가 백엔드(ONTAP) 스냅샷 `uuid`를 그대로 내보내는 것으로 보인다 [추론, 값 모양에서. 공식 출처 없음]. ONTAP 스냅샷 `uuid`는 "uniquely identifies the snapshot in that volume", 즉 볼륨 안에서 유일한 값이다 [문서 16].
- **목록**: 비어 있으면 `{"value": []}`이고 `nextLink`는 없다 [녹화 R1]. 두 개가 있으면 생성 순서로 나왔다(`snapshot-3761`, `snapshot-94`). 하지만 이 순서는 이름순이기도 해서, 정렬 기준이 무엇인지는 알 수 없다 [녹화 R2].

### 비동기 동작 (질문 1)

| 작업 | 실서비스 응답 | 헤더 | 응답 본문 | 작업 상태 진행 | `action` | 소요 | 근거 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PUT 생성 | 201 | `Azure-AsyncOperation`, `Location`(`operationResultResponseType=Location`). `Retry-After` 없음 | `{"id","name","type","location","properties":{"provisioningState":"Creating"}}`. `snapshotId`와 `created`는 아직 없다 | `Creating` → `Succeeded` | `CREATE` | 약 2~3초 | [녹화 R1, R2, R3, R4] |
| DELETE (있음) | 202 | `Azure-AsyncOperation`, `Location`. `Retry-After` 없음 | 없음 | `Deleting` → `Succeeded` | `DELETE` | 약 2초. 클론의 base 스냅샷은 약 73초 | [녹화 R1, R2, R4, R5] |
| DELETE (없음) | 녹화 없음 | | | | | | 스펙은 204를 허용한다 [스펙 2]. 실동작 [미확인] |
| GET 단건·목록 | 200 | | | | | | [녹화 R1, R2] |
| GET 없음 | 404 `ResourceNotFound` | | 아래 "오류 상황" | | | | [녹화 R1] |
| (참고) 볼륨 revert POST | 202 | 같음 | 없음 | `Reverting` → `Succeeded` | `POST` | 약 3초 | [녹화 R3] FR-06 |

- 작업 상태 본문은 다른 리소스와 같은 모양이다: `{"id", "name", "status", "startTime", "endTime": "0001-01-01T00:00:00Z"(진행 중), "percentComplete": 0.0|100.0, "properties": {"resourceName": <스냅샷 ARM ID>, "action": "CREATE"|"DELETE"}}` [녹화 R1]. 공통 LRO 규칙은 `_workspace/netapp-account/01_researcher_brief.md`에 있다.
- **스펙과 녹화가 다른 점**
  - 스펙 예시의 PUT 201 본문은 `provisioningState: Succeeded`이고 `snapshotId`와 `created`가 채워져 있다 [스펙 3]. 실서비스 201 본문은 `Creating`이고 두 속성이 없다 [녹화 R1].
  - 스펙의 PUT 헤더는 `Location`과 `Retry-After`다 [스펙 2]. 실서비스는 `Azure-AsyncOperation`과 `Location`을 보내고 `Retry-After`는 보내지 않았다 [녹화 R1].
- `provisioningState` 값: 녹화에서 본 것은 `Creating`과 `Succeeded`다. 작업 상태의 `status`로는 `Deleting`도 봤다 [녹화]. 리소스 GET에서 `Deleting`이 보이는지는 녹화되지 않았다 [미확인].

### 제약과 한도 (질문 2)

- 볼륨당 스냅샷은 255개이고, 지원 요청으로 늘릴 수 없다 [문서 9, 4]. ANF가 256번째 생성에 돌려주는 ARM 오류는 [미확인]. ONTAP은 개수 초과에 `525062` "Cannot exceed maximum number of snapshots"를 돌려준다 [문서 15].
- **스냅샷이 남은 볼륨의 DELETE: 스냅샷도 함께 지워진다.**
  - 문서: "If a volume is deleted, its vaulted snapshots (backups) are still retained, unlike the online snapshots, which are part of the volume and are deleted with the volume deletion." [문서 6, 202행]
  - 그래서 ANF는 스냅샷이 남은 볼륨의 DELETE를 409로 거절하지 않고 받아들일 것으로 보인다 [추론, 문서 6에서. 녹화로 확인한 동작은 아니다].
  - 녹화의 테스트는 모두 스냅샷을 먼저 지운 뒤 볼륨을 지웠다 [녹화 R1~R5]. 그래서 실서비스 응답은 관찰되지 않았다.
  - 볼륨이 삭제될 때 스냅샷 ARM 리소스가 따로 `Deleting` 상태를 거치는지는 [미확인].
- 다음은 확인하지 못했다. 녹화(.NET·Python 스냅샷 테스트 전부), 스펙, 문서 4·5·10·12를 찾아봤다.
  - 볼륨이 `Succeeded`가 아닐 때 스냅샷 생성 [미확인, ARM]. ONTAP에는 관련 오류가 있다.
    - `524479` "The specified volume is not online or does not have enough space to create a snapshot"
    - `1638532` "Failed to create the snapshot on the specified volume because a revert operation is in progress"
    - [문서 15]
  - 같은 이름으로 다시 PUT [미확인, ARM]. ONTAP은 `525059` "A snapshot with the specified name already exists"를 돌려준다 [문서 15].
- **FR-06·FR-07이 거는 제약 (짧게)**
  - revert를 하면 고른 스냅샷 **뒤에 찍은 스냅샷이 사라진다**("snapshots taken after the selected snapshot will be lost") [문서 13]. revert 요청 본문은 `{"snapshotId": <스냅샷 ARM ID>}`다 [녹화 R3].
  - "active file-restore operation" 중이거나 "in the process of being cloned"인 스냅샷은 지울 수 없다 [문서 12]. 클론이 **끝난 뒤** 원본 스냅샷을 지울 수 있는지는 녹화 순서상 확인되지 않았다 [미확인]. 녹화는 새 볼륨을 먼저 지운 뒤 원본 스냅샷을 지웠다 [녹화 R4]. ONTAP DELETE에는 `1638543` "Failed to delete snapshot because it has an owner"와 `ignore_owners` 쿼리가 있다 [문서 15]. 클론이 쓰는 스냅샷이 "owner"를 갖는지는 [미확인].
  - 스냅샷에서 만든 새 볼륨에는 **같은 이름의 base 스냅샷이 생긴다**. 녹화에서 `volume-4194/snapshots/snapshot-6328`는 원본 스냅샷과 이름이 같았지만, `snapshotId`가 달랐고 `created`는 초 단위로 잘려 있었다 [녹화 R4]. 문서도 이를 "base snapshot"이라 하고 `deleteBaseSnapshot`으로 뺄 수 있다고 쓴다 [문서 14, 스펙 2]. 새 볼륨에는 `originatingResourceId`(원본 스냅샷 ID)가 채워졌다 [녹화 R4].
  - 복원 중 새 볼륨에서 스냅샷을 켜는 것은 완전 복원 뒤로 하라고 권한다. 동시에 하나만 하라는 권고도 있다 [문서 14].

### 오류 상황 (질문 2)

- **ANF에서 확인된 것 [녹화 R1, R2, R4, P1]**
  - 없는 스냅샷 GET은 `404`다. 본문은 `{"error": {"code": "ResourceNotFound", "message": "The requested snapshot '<s>' was not found on the volume '<account>/<pool>/<volume>'. Please check the requested snapshot. Please note: The snapshot may no longer be available based on configured snapshot policies."}}`다. 볼륨 404의 ARM 기본 메시지와 다르게, ANF RP가 직접 만든 메시지다.
  - 스냅샷 녹화 전체(.NET 12개, Python 3개)에 409·400 응답은 없다. `Failed` 작업은 restoreFiles(파일 없음, 2023-03-09 녹화)에 하나 있다 [녹화].
- **ANF 미확인**: 255개 초과, 같은 이름 재전송, 잘못된 이름, `location` 누락, `properties`에 쓰기 속성을 넣은 경우, 볼륨이 `Succeeded`가 아닐 때.
- ONTAP 오류 코드는 아래 "ONTAP REST 스냅샷 API"에 있다. ANF가 이 코드를 ARM 오류로 어떻게 바꾸는지는 [미확인].

## 데이터 플레인에서 보이는 효과 (질문 3, 4)

### `.snapshot` 디렉터리

- **ANF 문서**
  - NFS 클라이언트에서 마운트한 볼륨에는 `.snapshot`이라는 디렉터리가 있다. SMB에서는 `~snapshot`이다. 그 아래에 **스냅샷마다 하위 디렉터리가 하나씩** 있고, 각 디렉터리에 그 시점의 파일이 들어 있다 [문서 7].
  - 하위 디렉터리 이름은 스냅샷 이름이다 [추론]. 문서 예시 `ls .snapshot`이 `daily.2020-05-14_0013/`, `hourly.2020-05-15_1306/`처럼 정책 스냅샷 이름 형식을 보여 준다 [문서 7]. ONTAP REST 목록 예시도 스냅샷 `name`이 `hourly.2019-03-13_1305` 같은 형식이다 [문서 16]. 이름이 같다고 직접 쓴 문장은 찾지 못했다.
  - 스냅샷은 읽기 전용으로 접근된다("all of which are accessible as read-only") [문서 6]. 쓰기를 시도했을 때 클라이언트가 받는 오류(EROFS인지 EACCES인지)는 [미확인].
  - NFSv3: 기본으로 보인다 [문서 5, 8].
  - NFSv4.1: "By design, the `.snapshot` directory is never visible". 즉 `ls -la`에 나오지 않는다 [문서 5, 7]. 하지만 숨김 옵션이 꺼져 있으면 `cd .snapshot`으로 들어갈 수 있다 [문서 7].
- **ONTAP 쪽 (보완 3)**
  - **하위 디렉터리에서도 접근된다.** ONTAP REST 볼륨 필드 `snapshot_directory_access_enabled`의 설명은 이렇다: "if true, enables the visible ".snapshot" directory from the client. The ".snapshot" directory will be available in every directory on the volume." [문서 17]
  - **NFSv3 목록에 보이는 곳은 마운트 지점뿐이다.** NetApp KB "Why isn't the .snapshot directory visible in an 'ls -al' output on an NFS client?"는 `ls -la`에 나오는 조건 네 가지를 든다 [문서 20, 원문 미확인. WebSearch 요약만 봤다].
    - NFSv3 마운트일 것
    - 마운트 지점(base)에서 실행할 것
    - 볼륨의 스냅샷이 켜져 있을 것
    - `v3-hide-snapshot`이 꺼져 있을 것(ONTAP 9.5에서 도입)
  - 같은 KB는 NFSv4가 `.snapshot`을 목록에 보이지 않지만 이름으로는 접근하게 한다고 쓴다 [문서 20, 원문 미확인]. 다른 출처(Red Hat 솔루션, Thales 문서)도 같은 증상을 설명한다 [문서 21, 단서로만 쓴다].
  - 스냅샷 안(`.snapshot/S/`)에서 `.snapshot`이 다시 보이는지는 찾지 못했다 [미확인]. `snapshot_directory_access_enabled` 설명, `-snapdir-access` CLI 설명, KB 검색 요약에서 찾아봤다.
- **`snapshotDirectoryVisible`(포털 이름 "Hide snapshot path"를 뒤집은 값)**
  - 기본값은 `true`다 [스펙 2]. 녹화 기본값도 `true`다 [녹화, 볼륨 브리프].
  - 생성할 때 정할 수 있고, 생성 뒤에도 바꿀 수 있다 [문서 11, 스펙 2]. 녹화에서도 PATCH로 `false`로 바꿨다 [녹화, 볼륨 브리프 V3].
  - **숨겼을 때 효과는 문서끼리 다르다.**
    - (가) "Enabling the Hide snapshot path option will hide the .snapshot directory from NFSv3 clients; the directory will still be accessible." [문서 8]
    - (나) "This option controls whether the directory should be hidden from the clients. Therefore, it also controls access to files and folders in the snapshots." 그리고 "when the Hide Snapshot Path option is not set, you can still access the `.snapshot` directory via NFSv4.1" [문서 7]
    - (가)는 숨겨도 경로로 접근된다고 읽힌다. (나)는 숨기면 접근도 막힌다고 읽힌다.
  - **ONTAP의 두 옵션은 (가)와 (나)에 하나씩 대응한다** (아래 표). (가)는 NFS 서버(SVM) 옵션 `-v3-hide-snapshot`의 동작과 같다. 이 옵션은 NFSv3 목록에서만 숨기고 명시적 접근은 허용한다. (나)는 볼륨 옵션 `-snapdir-access false`의 동작과 같다. 이 옵션은 클라이언트 접근 자체를 끈다 [문서 17, 18, 22]. ANF가 어느 쪽을 쓰는지는 공개되지 않았다 [추론]. 다만 `-v3-hide-snapshot`은 SVM 단위 옵션이고 `snapshotDirectoryVisible`은 볼륨 단위 속성이다. 그래서 볼륨 단위인 `-snapdir-access`에 대응할 가능성이 크다 [추론, 옵션 단위에서].

### 스냅샷 공간 (질문 4)

- "The capacity consumed by volume snapshots counts towards the provisioned space in the volume." [문서 4, 10]. 그래서 스냅샷이 커지면 볼륨이 가득 찰 수 있다. FAQ는 볼륨이 찼을 때의 대처(크기 늘리기, 스냅샷 지우기)를 안내한다 [문서 10]. 할당량이 다 차면 볼륨은 "out of space"가 되고, 자동으로 늘어나지 않는다 [문서 4].
- 스냅샷 자체는 만들 때 공간을 쓰지 않는다. 그 뒤 바뀐 블록만큼 쓴다 [문서 6]. 스냅샷을 지우면 그 스냅샷만 잡고 있던 블록이 풀린다 [문서 6]. 큰 삭제 뒤 공간 회수에는 몇 분이 걸릴 수 있다 [문서, 볼륨 브리프].
- ANF 문서와 스펙에는 snapshot reserve 같은 설정이 없다. 문서 4·6·10에서 찾지 못했고, 스펙의 `VolumeProperties`에도 그런 속성이 없다 [스펙 2].
- ONTAP에는 reserve가 있다. "The snapshot reserve sets aside a percentage of disk space for snapshots, five percent by default. Because snapshots use space in the active file system when the snapshot reserve is exhausted..." [문서 22]. CLI는 `volume modify -percent-snapshot-space`이고 기본값은 5%다 [문서 18].
- ANF가 내부적으로 reserve를 0으로 두는지는 [미확인]. ANF 문서가 "스냅샷 사용량이 볼륨 할당량에 포함된다"고 쓰는 것은 reserve 없이 활성 파일 시스템과 같은 공간을 쓰는 모습과 맞는다 [추론, 문서 4와 22에서].
- 클라이언트 `df`에 스냅샷 사용량이 어떻게 보이는지(used에 포함되는지)는 [미확인].

## ONTAP 대응 개념 (질문 5)

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| 스냅샷 리소스 | 볼륨 스냅샷 (`/api/storage/volumes/{volume.uuid}/snapshots`, CLI `snapshot create`) | ANF 문서는 "Redirect on Write"로 설명한다. 스냅샷은 블록 포인터를 보존하고 데이터 블록을 복사하지 않는다. ONTAP REST는 스냅샷을 "the view of the filesystem as it exists at the time when the snapshot is created"로 정의한다 | [문서 6, 16] |
| `snapshotId` | ONTAP 스냅샷 `uuid` (볼륨 안에서 유일). 별도로 `version_uuid`(128비트 식별자)도 있다 | 녹화 값이 v4가 아니라서 백엔드 UUID로 보인다 | 대응 [추론] (녹화 값 모양), 필드 [문서 16] |
| 스냅샷 이름 | ONTAP `name` (POST 필수, PATCH로 rename 가능) | ONTAP은 같은 볼륨 안에서 이름 중복을 `525059`로 거절한다 | [문서 15, 16] |
| `created` | ONTAP `create_time` ("the volume access time when the snapshot was created") | | 대응 [추론], 필드 [문서 16] |
| `.snapshot`, `snapshotDirectoryVisible` | 볼륨 `-snapdir-access` (REST `snapshot_directory_access_enabled`, 기본값 true). SVM NFS `-v3-hide-snapshot` (REST `protocol.v3_features.hide_snapshot_enabled`, 기본값 disabled) | `-snapdir-access`는 접근 자체를 켜고 끈다. `-v3-hide-snapshot`은 NFSv3 목록에서만 숨긴다. NFSv4.1용 hide 옵션은 `nfs_service_protocol_v41_features` 모델에 없다 | 옵션 [문서 17, 18, 23]. ANF 대응 [추론] |
| 255개 한도 | ONTAP 9.4 이상 FlexVol 1023개 (9.3 이하 255개) | ANF 한도는 ONTAP 한도보다 낮다. ANF가 왜 255를 쓰는지는 공개되지 않았다 | [문서 9, 19], 이유 [미확인] |
| 스냅샷 공간이 할당량에 포함 | ONTAP snapshot reserve (`-percent-snapshot-space`, 기본 5%). reserve가 다 차면 활성 파일 시스템 공간을 쓴다 | ANF에는 reserve 설정이 없다 | ONTAP [문서 18, 22]. 대응 [추론] |
| 볼륨 삭제 시 스냅샷 삭제 | 스냅샷은 볼륨의 일부 | ANF 문서가 "part of the volume"이라고 쓴다 | [문서 6] |
| revert | SnapRestore (volume) | 이름 대응만 적는다 | [추론], FR-06 |
| 스냅샷에서 새 볼륨 | FlexClone, 분할(split) | 문서가 "restore to new volume"을 "clones"라고 부른다 [문서 6]. ONTAP FlexClone이라는 직접 언급은 확인하지 못했다 | [추론], FR-07 |

### ONTAP REST 스냅샷 API (보완 1)

기준: ONTAP 9.19.1 REST API reference [문서 15]와 `netapp-ontap` 9.19.1.0 `resources/snapshot.py` [문서 16]. 둘 다 "automatically generated based on the ONTAP REST API documentation"이라고 밝힌다 [문서 16].

- **경로** [문서 16]
  - `POST /api/storage/volumes/{volume.uuid}/snapshots`
  - `GET /api/storage/volumes/{volume.uuid}/snapshots`
  - `GET .../snapshots/{uuid}`
  - `PATCH .../snapshots/{uuid}`
  - `DELETE .../snapshots/{uuid}`
  - 여러 볼륨을 한 번에 다루는 bulk 경로(`/api/storage/volumes/*/snapshots`)도 있다. 범위 밖이다.
- **POST 생성** [문서 15, 16]
  - 필수 속성은 `name`("Name of the snapshot to be created") 하나다. 권장 선택 속성은 `comment`, `expiry_time`, `snapmirror_label`, `snaplock_expiry_time`다. 대응 CLI는 `snapshot create`다.
  - 클라이언트 예시의 요청 본문은 `{"name": "snapshot_copy", "comment": "Store this copy."}`다 [문서 16].
  - 쿼리 `return_timeout`: 기본 0, 최대 120. 설명은 이렇다: "if an asynchronous operation is started, the server immediately returns HTTP code 202 (Accepted) along with a link to the job. If a non-zero value is specified ... ONTAP waits that length of time to see if the job completes so it can return something other than 202." 쿼리 `return_records`(기본 false)도 있다 [문서 15].
  - 응답
    - `202 Accepted`: 본문 `{"job": {"uuid": ..., "_links": ...}}`, 헤더 `Location`("Useful for tracking the resource location") [문서 15].
    - `201 Created`: `return_timeout` 안에 job이 끝났을 때로 보인다 [추론, `return_timeout` 설명에서].
  - 응답에 새 스냅샷의 `uuid`가 바로 들어 있지는 않다. 202 본문은 `job`뿐이다 [문서 15]. 그래서 job이 끝난 뒤 `GET ...?name=<이름>`으로 `uuid`를 얻는 흐름이 필요하다 [추론]. 클라이언트의 `post(hydrate=True)`가 이 일을 대신하는 것으로 보인다 [추론, 문서 16의 인자에서].
  - POST 오류 코드 (발췌) [문서 15]

| 코드 | 메시지 |
| --- | --- |
| 525059 | A snapshot with the specified name already exists. |
| 525062 | Cannot exceed maximum number of snapshots. |
| 524479 | The specified volume is not online or does not have enough space to create a snapshot. |
| 1638518 | The specified snapshot name is invalid. |
| 1638477 | User-created snapshot names cannot begin with the specified prefix. |
| 1638532 | Failed to create the snapshot on the specified volume because a revert operation is in progress. |
| 1638461 | Snapshots can only be created on read/write (RW) volumes. |
| 1520351 | Snapshot operation is not allowed. |

  - 이 코드들이 HTTP 응답 오류로 오는지 job 실패로 오는지는 문서에 나뉘어 있지 않다 [미확인]. 문서는 "Error Status: Default ONTAP Error Response Code"라고만 쓴다 [문서 15].
- **레코드 필드** (`gettable_fields`) [문서 15, 16]
  - `uuid`: "uniquely identifies the snapshot in that volume"
  - `name`
  - `create_time`: 예 `2019-02-04T19:00:00.000+0000`. 설명은 "the volume access time when the snapshot was created"
  - `comment`
  - `size`: "Size of the active file system at the time the snapshot is captured", 바이트
  - `state`: `valid`, `invalid`, `partial`, `unknown`, `pre_conversion`. 설명은 FlexGroup 스냅샷 기준이다
  - `version_uuid`, `expiry_time`, `snapmirror_label`, `owners`, `provenance_volume`, `logical_size`, `reclaimable_space`·`delta`(advanced), `svm{name,uuid}`, `volume{name,uuid}`, `_links`
  - 단건 GET 예시: `{"uuid", "volume": {"uuid","name"}, "create_time": "2019-03-13T13:05:00-04:00", "size": 122880, "name": "hourly.2019-03-13_1305", "svm": {...}}` [문서 16]
- **GET 목록** [문서 15, 16]
  - 응답은 `{"num_records": n, "records": [...]}`다. 기본 레코드에는 `uuid`, `name`, `_links`만 있다. 다른 필드는 `fields=`로 요청한다 [문서 16 예시].
  - 쿼리 `fields`, `max_records`, `order_by`, `return_records`, `return_timeout`가 있다 [문서 15].
  - 이름으로 거르는 예시가 있다: `get_collection("{volume.uuid}", name="a|b|c")`이고, `|`가 OR다 [문서 16]. 이것이 HTTP 쿼리 `?name=`로 나간다고 본다 [추론, 클라이언트 문법에서. HTTP 쿼리 표의 `name` 행은 HTML 변환본에서 찾지 못했다].
  - 목록 오류: `918235` "The specified volume is invalid" [문서 15].
- **DELETE** `/api/storage/volumes/{volume.uuid}/snapshots/{uuid}` [문서 15]
  - 스냅샷을 이름이 아니라 **UUID**로 지정한다.
  - 쿼리는 `return_timeout`과 `ignore_owners`(9.19 도입)다.
  - 응답은 `202 Accepted` + `job`, 또는 `200 OK`다.
  - 오류 (발췌)

| 코드 | 메시지 |
| --- | --- |
| 1638600 | The snapshot does not exist. |
| 1638543 | Failed to delete snapshot because it has an owner. |
| 1638555 | The specified snapshot has not expired or is locked. |
| 524481 | Snapshot was not deleted because the associated volume is locked or fenced. |
| 1638521 | Snapshots can only be deleted on read/write (RW) volumes. |

  - 오류 본문 예시: `{"error": {"arguments": [...], "code": "4", "message": "entry doesn't exist", "target": "uuid"}}` [문서 15].
- **PATCH**: 이름 바꾸기(`snapshot rename`)와 `comment` 같은 속성 수정이다 [문서 16]. ARM `SnapshotPatch`는 빈 모델이라 대응하는 기능이 없다 [스펙 1].
- 기존 클론과의 관계(참고): 볼륨 조사 때 정리한 ONTAP job 모델(`job.py.txt`)이 스냅샷 POST·DELETE의 202 + job에도 그대로 쓰인다 [문서 15의 `job_link` 정의에서].

## 구현 범위 후보

### 이번에 재현할 것

- ARM PUT·GET·목록·DELETE와 작업 상태(`Creating`/`Deleting`, `action CREATE`/`DELETE`). 실서비스가 이렇게 동작한다는 근거가 녹화에 있다.
- storage agent의 ONTAP 부분집합: `POST/GET/DELETE /api/storage/volumes/{uuid}/snapshots[/{uuid}]`. POST·DELETE는 202 + job으로, 같은 이름은 `525059`로 응답한다. 근거는 문서 15·16이다. ADR §2.3이 이 경로를 따르기로 했다.
- NFSv3에서 `.snapshot/<이름>/` 읽기와 쓰기 거절. FR-05 수락 기준이 이것을 요구한다.
- NFSv4.1에서 `ls`에는 안 보이고 `cd`는 되는 동작. ANF 문서와 ONTAP KB가 같은 말을 한다. 구현 가능 여부는 스파이크 S4에서 판단한다.

### 다음으로 미룰 것 (이유)

- `restoreFiles`: 범위 밖이다.
- 스냅샷 정책: FR-17이다.
- PATCH: 본문이 빈 모델이라 바꿀 것이 없다. 다만 라우트를 둘지는 선택지 3이다.
- ONTAP의 `comment`, `expiry_time`, `snapmirror_label`, `owners`, bulk API: ARM 쪽에 대응 속성이 없다.
- 255개 초과 ARM 오류: 코드가 미확인이다.

### 리더·사용자가 정해야 할 선택지

1. **PUT 201 본문과 헤더.**
   - (a) 녹화를 따른다: `Creating`, 속성 없음, `Azure-AsyncOperation` + `Location`.
   - (b) 스펙 예시를 따른다: `Succeeded`, `Location` + `Retry-After`.
   - 기존 리소스들은 녹화를 따랐다 [추론, 계정·볼륨 브리프].
2. **`snapshotId` 값.**
   - (a) storage agent가 돌려준 ONTAP식 `uuid`를 그대로 쓴다. 녹화가 이 방식으로 보이고, 스펙 패턴(UUID 모양)은 만족한다.
   - (b) anf-api가 uuid4를 만든다. 스펙 설명("v4")과 맞는다.
   - ONTAP DELETE는 UUID로 지정하므로, (b)를 고르면 anf-api가 두 UUID의 대응을 따로 들고 있어야 한다 [추론, 문서 15에서].
3. **PATCH 라우트.**
   - (a) 스펙대로 받는다: 빈 본문에 200 + 현재 리소스.
   - (b) 405 등으로 두지 않는다.
   - 실서비스 동작은 미확인이다.
4. **이름 규칙.**
   - ARM 스펙에는 패턴이 없다. ONTAP에는 "invalid name"(`1638518`)과 "금지 접두어"(`1638477`) 오류가 있지만 규칙 내용은 미확인이다.
   - (a) 받는 대로 두고 agent가 거절하게 한다. (b) 클론이 패턴을 정한다(예: 볼륨 이름 규칙).
   - `.snapshot/<이름>`이 디렉터리 이름이 되므로 `/`, `.`, `..` 같은 값은 데이터 플레인에서 문제가 된다 [추론].
5. **스냅샷이 남은 볼륨 DELETE.**
   - 문서 6은 "online snapshots ... are deleted with the volume deletion"이라고 쓴다. 그래서 (b) 연쇄 삭제가 ANF 문서와 맞는다.
   - (a) 409 거절(기존 `Tx.ensure_no_children` 방식)을 고르면 ANF와 다른 점으로 적어야 한다.
   - (b)를 고르면 storage agent의 볼륨 삭제가 스냅샷(thin 스냅샷 LV, `.snapshot` 마운트)을 먼저 치워야 한다 [추론].
6. **같은 이름 재전송 PUT.**
   - (a) 200 + 현재 리소스(멱등).
   - (b) 409.
   - (c) 201을 다시 보낸다.
   - ARM 쪽 근거: 스펙의 응답 목록에 200이 없다.
   - ONTAP 쪽 근거: 백엔드는 같은 이름을 `525059`로 거절한다. 그래서 ANF RP가 재전송을 백엔드까지 보내지 않고 자기 상태에서 처리할 것으로 보인다 [추론].
7. **`snapshotDirectoryVisible: false`의 의미.**
   - (가) `-v3-hide-snapshot`식: NFSv3 목록에서만 숨기고 경로 접근은 둔다 [문서 8].
   - (나) `-snapdir-access false`식: 접근도 막는다 [문서 7].
   - 볼륨 단위 속성이라는 점은 (나)에 가깝다 [추론]. 이번에 이 입력을 열지도 함께 정한다(볼륨 설계 §2에서 "미룬다"로 남아 있다).
8. **`.snapshot`을 어디에 보일지.** ONTAP은 모든 디렉터리에서 `.snapshot`에 접근하게 한다 [문서 17]. 클론이 볼륨 루트에서만 제공한다면 그 차이를 기록해야 한다. 구현 가능 범위는 S4가 정한다.
9. **FR-06·07 대비.**
   - 스냅샷 저장에 생성 순서(`created`)를 남긴다. revert가 "뒤에 찍은 스냅샷"을 지워야 하기 때문이다.
   - 스냅샷 DELETE에 "사용 중" 거절 자리를 둘지 정한다. 문서 12는 "복원 중"인 스냅샷만 막는다. ONTAP은 owner가 있는 스냅샷을 `1638543`으로 막는다.

### 검증 기준 후보 (클라이언트에서 관찰)

- V1: PUT → `201`이고 `Azure-AsyncOperation` 헤더가 있다. 본문은 `provisioningState: Creating`이다. 작업 상태를 폴링하면 `Creating`에서 `Succeeded`로 가고 `action: CREATE`다. 그 뒤 GET은 `Succeeded`이고 `snapshotId`(36자 UUID)와 `created`(ISO 8601)가 있다.
- V2: NFSv3 클라이언트에서 파일 A를 쓴다 → 스냅샷 S를 만든다 → A를 지운다 → `cat .snapshot/S/A`가 원래 내용을 돌려준다. 볼륨 루트의 `ls -a`에 `.snapshot`이 보인다.
- V3: `.snapshot/S/` 안에서 쓰기, 삭제, 이름 바꾸기가 모두 실패하고 원본은 바뀌지 않는다. 기대 errno는 EROFS로 둘 수 있지만 ANF 실동작은 미확인이라, "실패하고 내용이 그대로"를 기준으로 삼는다.
- V4: NFSv4.1 클라이언트에서 루트의 `ls -a`에 `.snapshot`이 없고, `ls .snapshot/S/A`는 된다. 스파이크 S4 결과에 따라 범위를 조정한다.
- V5: 목록 GET이 `{"value": [...]}`에 만든 스냅샷을 모두 담고, 비어 있으면 `{"value": []}`다.
- V6: DELETE → `202`, 작업 상태가 `Deleting`에서 `Succeeded`로 간다. 그 뒤 GET은 `404 ResourceNotFound`이고, 클라이언트의 `.snapshot/S`도 사라진다.
- V7: 스냅샷을 만든 뒤 활성 파일을 덮어쓰면 스냅샷 쪽 내용은 바뀌지 않는다(포인터 보존).
- V8 (공간): ANF는 스냅샷이 잡은 블록을 볼륨 할당량에 넣는다 [문서 4]. 클론이 이와 다르면(D-11, S1) 차이로 기록할 항목이다.
- V9 (storage agent, ONTAP 부분집합):
  - 같은 볼륨에 같은 `name`으로 두 번째 POST를 보내면 오류 `525059`로 실패한다.
  - `GET ...snapshots?name=<이름>`이 그 스냅샷의 `uuid`를 돌려준다.
  - `DELETE ...snapshots/{uuid}` 뒤 같은 uuid로 GET하면 "없음"이다.
- V10 (선택지 5에 따라): 스냅샷이 있는 볼륨을 DELETE한다. 연쇄 삭제를 골랐다면 볼륨과 스냅샷 목록이 모두 404가 되고, 호스트에 스냅샷 LV가 남지 않는다.

## 미확인 목록

| 항목 | 설계를 막는가 | 찾아본 곳 |
| --- | --- | --- |
| 같은 이름 재전송 PUT의 ARM 응답 | 선택지 6 | 스펙 [1][2][3], 녹화 R1~R5·P1~P3. ONTAP 중복 오류 `525059`만 확인 [15] |
| 볼륨이 `Succeeded`가 아닐 때 스냅샷 생성 (ARM) | 아니다 (클론 규칙으로 정할 수 있음) | 녹화, 문서 12·13·14. ONTAP `524479`·`1638532` [15] |
| 스냅샷이 남은 볼륨 DELETE의 실서비스 응답 코드 | 아니다. 문서 6이 연쇄 삭제를 말한다 | 녹화 (모두 스냅샷을 먼저 삭제). 볼륨 삭제 전용 문서(`azure-netapp-files-delete-volumes.md`, `delete-volumes.md`)는 해당 커밋에 없었다 |
| 클론이 끝난 뒤 원본 스냅샷 DELETE, 클론 스냅샷의 ONTAP owner 여부 | 아니다 (FR-07) | 녹화 R4·R5 순서상 관찰 불가, 문서 12·15 |
| 255개 초과 시 ARM 오류 코드 | 아니다 | 문서 9, 녹화 |
| 없는 스냅샷 DELETE의 실제 ARM 응답 (스펙은 204 허용) | 아니다 (스펙 204를 따를 수 있음) | 녹화 |
| 스냅샷 PATCH 실동작 | 선택지 3 | 녹화 없음 |
| 실서비스와 ONTAP의 이름 규칙 내용 (금지 문자, 금지 접두어 목록) | 선택지 4 | 스펙(패턴 없음), 문서 2·15 |
| ONTAP POST 오류가 HTTP 오류로 오는지 job 실패로 오는지 | agent 오류 모델 설계 시 | 문서 15 (구분 없음) |
| ONTAP GET의 HTTP 쿼리 `name` 행 | 아니다 (클라이언트 예시로 대신함) | 문서 15의 HTML 변환본 |
| `.snapshot` 쓰기 시 errno | 아니다 (V3을 "실패"로 씀) | 문서 6·7 |
| 스냅샷 안에서 `.snapshot`이 다시 보이는지 | 아니다 | 문서 17·18·20 |
| 숨김(`false`) 시 ANF가 쓰는 ONTAP 옵션 (`-snapdir-access`인지 `-v3-hide-snapshot`인지) | 선택지 7 | ANF 문서 7·8 (서로 충돌), ONTAP 문서 17·18·23 |
| `df`에 스냅샷 사용량이 보이는 방식, ANF 내부 reserve 값 | 아니다 (V8 기록) | 문서 4·6·10·22, 스펙 |
| NetApp KB `.snapshot` 가시성 원문 | 아니다 (ANF 문서와 같은 내용) | WebSearch 요약만 봤다 [20]. 원문은 받지 않았다 |

## 후속 조사 목록

- `restoreFiles`(단일 파일 복원): `filePaths` 1~10개, `destinationPath`. 200/202 [스펙 1, 2]. 파일이 없으면 작업이 `Failed`가 된다 [녹화 R6, 2023-03-09].
- 스냅샷 정책(FR-17): 정책 스냅샷 이름은 `daily.YYYY-MM-DD_HHMM` 형식으로 보인다 [문서 7].
- 단기 클론(`volumeType: ShortTermClone`, 32일 뒤 일반 볼륨으로 전환) [문서 6, 녹화 R5].
- 백업·복제가 만드는 스냅샷의 삭제·revert 제약 [문서 12, 13].
- SMB `~snapshot`과 Previous Versions [문서 7].
- ONTAP 스냅샷 `expiry_time`, SnapLock, `owners`(`ignore_owners`) [문서 15, 16].

## 출처

- [1] Azure REST API specs — `Snapshot.tsp` (TypeSpec) — https://raw.githubusercontent.com/Azure/azure-rest-api-specs/3b64c3a12af9938128abcf05d04c323a518ea78a/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/Snapshot.tsp (커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`, 2026-11-08 받음). 사본: `sources/spec/Snapshot.tsp`
- [2] Azure REST API specs — `stable/2026-08-01/netapp.json`: snapshots 경로, `Snapshot`, `SnapshotProperties`, `SnapshotPatch`, `SnapshotsList`, `SnapshotRestoreFiles`, `VolumeProperties.snapshotDirectoryVisible`·`snapshotId`·`deleteBaseSnapshot`. 같은 커밋. 사본은 재사용: `_workspace/capacity-pool/sources/spec/netapp-2026-08-01.json`
- [3] 같은 커밋의 `stable/2026-08-01/examples/` 중 `Snapshots_Create.json`, `Snapshots_Get.json`, `Snapshots_List.json`, `Snapshots_Update.json`, `Snapshots_Delete.json`, `Snapshots_SingleFileRestore.json`. 사본: `sources/spec/examples/`
- [4] Microsoft Learn — Understand volume quota (`volume-quota-introduction.md`). azure-docs 커밋 `548a6fcfecc7e850241c77f1a29db21d781d5d1b`. 사본은 재사용: `_workspace/volume/sources/docs/`
- [5] Microsoft Learn — NFS FAQ (`faq-nfs.md`, "Why is the .snapshot directory not visible in an NFSv4.1 volume") — 같은 커밋. 사본은 재사용: `_workspace/volume/sources/docs/`
- [6] Microsoft Learn — How Azure NetApp Files snapshots work (`snapshots-introduction.md`. 202행에 볼륨 삭제와 online snapshot 삭제) — 같은 커밋. 사본은 재사용: `_workspace/volume/sources/docs/`
- [7] Microsoft Learn — Restore a file from a snapshot using a client (`snapshots-restore-file-client.md`) — 같은 커밋. 사본: `sources/docs/`
- [8] Microsoft Learn — Create an NFS volume (`azure-netapp-files-create-volumes.md`, Hide snapshot path 주석) — 같은 커밋. 사본은 재사용: `_workspace/volume/sources/docs/`
- [9] Microsoft Learn — Resource limits (`azure-netapp-files-resource-limits.md`, "Number of snapshots per volume | 255 | No", 31행. 85~98행의 같은 값은 주석 처리된 Elastic 표다) — 같은 커밋. 사본: `sources/docs/`
- [10] Microsoft Learn — Capacity management FAQ (`faq-capacity-management.md`) — 같은 커밋. 사본은 재사용: `_workspace/volume/sources/docs/`
- [11] Microsoft Learn — Manage snapshot policies, "Edit the Hide snapshot path option" (`snapshots-manage-policy.md`) — 같은 커밋. 사본: `sources/docs/`
- [12] Microsoft Learn — Delete snapshots (`snapshots-delete.md`) — 같은 커밋. 사본: `sources/docs/`
- [13] Microsoft Learn — Revert a volume using snapshot revert (`snapshots-revert-volume.md`) — 같은 커밋. 사본: `sources/docs/`
- [14] Microsoft Learn — Restore a snapshot to a new volume (`snapshots-restore-new-volume.md`) — 같은 커밋. 사본: `sources/docs/`
- (참고) 같은 커밋의 `azure-netapp-files-manage-snapshots.md`(포털 절차뿐), `faq-data-migration-protection.md`, `faq-integration.md`(볼륨 삭제와 스냅샷 관련 내용 없음). 사본: `sources/docs/`
- [15] NetApp ONTAP 9.19.1 REST API reference (2026-11-08 curl로 받음, 페이지 날짜 10/06/2026). HTML과 텍스트 변환본 사본: `sources/ontap/restapi/*.html`, `*.txt`
  - POST: https://docs.netapp.com/us-en/ontap-restapi/ontap/post-storage-volumes-snapshots.html
  - GET 목록: https://docs.netapp.com/us-en/ontap-restapi/ontap/get-storage-volumes-snapshots.html
  - DELETE: https://docs.netapp.com/us-en/ontap-restapi/ontap/delete-storage-volumes-snapshots-.html
- [16] `netapp-ontap` 9.19.1.0 PyPI 휠의 `netapp_ontap/resources/snapshot.py` 문서 문자열과 스키마. 텍스트로만 추출했고 실행하지 않았다.
  - 휠 URL: https://files.pythonhosted.org/packages/33/8a/84a18edb0f12e607231356de56f7dee6242ae43f7987492c5604e0df28d8/netapp_ontap-9.19.1.0-py3-none-any.whl
  - 휠 sha256 `916c329e9fb968d200c9451ebb10eb4ab80b9fc96c24ce674a0b1782c1ad9ab0` (볼륨 조사의 `pypi.json` 값과 같다)
  - 추출 파일 sha256 `5f22a786a78f14dd3a0d27b5d8406b0ef8bed6f301afdff93efc9f7ac77abc9d`
  - 사본: `sources/ontap/snapshot.py.txt`, 휠 `sources/ontap/wheel/`
- [17] 같은 휠의 `netapp_ontap/resources/volume.py`, `snapshot_directory_access_enabled` 필드(1497~1501행). 사본은 재사용: `_workspace/volume/sources/ontap/volume.py.txt`
- [18] NetApp ONTAP command reference — `volume modify`(`-snapdir-access`, `-percent-snapshot-space`) — https://docs.netapp.com/us-en/ontap-cli/volume-modify.html (2026-11-08 curl). 사본: `sources/ontap/restapi/cli-volume-modify.html`, `.txt`
- [19] NetAppDocs/ontap — `data-protection/manage-local-snapshot-copies-concept.adoc` (9.4 이상 FlexVol 1023개, 9.3 이하 255개, 16~17행) — 커밋 `37d53f2a6cff395e1fb457f522c61826a8dbf379`. 사본: `sources/ontap/adoc/`
- [20] NetApp KB — "Why isn't the .snapshot directory visible in an 'ls -al' output on an NFS client?" — https://kb.netapp.com/onprem/ontap/da/NAS/Why_isnt_the_snapshot_directory_visible_in_an_ls_al_output_on_an_NFS_client (WebSearch 요약만, 원문 미확인, 2026-11-08)
- [21] 단서: Red Hat 솔루션 "After mounting a share from a NetApp filer with NFSv4, .snapshot dir is not listed, but can be accessed" — https://access.redhat.com/node/3440571 . Thales 문서 "NetApp Snapshot Directory" — https://thalesdocs.com/ctp/cte-con/cte/7.6.0/integrations/lin-int/lin-int-netapp/index.html (둘 다 WebSearch 요약만)
- [22] NetAppDocs/ontap — `data-protection/manage-snapshot-copy-reserve-concept.adoc` (기본 reserve 5%), `data-protection/enable-disable-snapshot-dir-access-task.adoc` (`-snapdir-access`, 기본으로 접근 가능) — 커밋 `37d53f2a6cff395e1fb457f522c61826a8dbf379`. 사본: `sources/ontap/adoc/`
- [23] NetApp ONTAP command reference — `vserver nfs modify`(`-v3-hide-snapshot`, 197~198행) — https://docs.netapp.com/us-en/ontap-cli/vserver-nfs-modify.html (2026-11-08 curl). 같은 휠의 `models/nfs_service_protocol_v3_features.py`(`hide_snapshot_enabled`, sha256 `f9d84972...`)와 `models/nfs_service_protocol_v41_features.py`(hide 옵션 없음). 사본: `sources/ontap/restapi/cli-vserver-nfs-modify.*`, `sources/ontap/nfs_service_protocol_v3_features.py.txt`, `nfs_service_protocol_v41_features.py.txt`, `nfs_service.py.txt`
- **녹화.** 모두 계정 조사 때 받은 사본을 재사용했다.
  - .NET 녹화의 태그는 `net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c`이고, 경로는 `net/sdk/netapp/Azure.ResourceManager.NetApp/tests/SessionRecords/SnapshotTests/`다. 사본: `_workspace/netapp-account/sources/recordings/net/SnapshotTests__*.json`. 녹화일은 2026-10-29~30이고 api-version은 `2026-08-15-preview`다.
    - R1 `CreateDeleteSnapshot`
    - R2 `ListSnapshots`
    - R3 `RevertVolumeToSnapshot`
    - R4 `CreateVolumeFromSnapshot`
    - R5 `CreateShortTermCloneVolumeFromSnapshot`
    - R6 `RestoreFilesFromSnapshotFileDoesNotExist` (2023-03-09 녹화)
  - Python 녹화의 태그는 `python/netapp/azure-mgmt-netapp_c350090f50`다. 사본: `_workspace/netapp-account/sources/recordings/py/`
    - P1 `test_create_delete_snapshot`
    - P2 `test_get_snapshot_by_name`
    - P3 `test_list_snapshots`
- 이전 브리프: `_workspace/volume/01_researcher_brief.md`(볼륨의 `snapshotDirectoryVisible` 기본값, 녹화 V3 PATCH), `_workspace/netapp-account/01_researcher_brief.md`(LRO 공통 규칙)

## 변경 이력

- 2026-11-08: 처음 작성. 한도 도달로 질문 5(ONTAP REST·옵션 원문)가 남았다.
- 2026-11-08: 보완 조사(리더 요청 1~4).
  - (1) ONTAP REST 스냅샷 API 절을 새로 썼다 [15][16]. POST 필수 필드 `name`, 202 + job/201, 레코드 필드, 목록의 `name` 필터, UUID로 지정하는 DELETE, 오류 코드(`525059` 중복 이름, `525062` 개수 초과 등)를 담았다.
  - (2) 스냅샷이 남은 볼륨의 DELETE를 [미확인]에서 "문서상 함께 삭제" [문서 6]로 바꾸고, 선택지 5를 고쳤다.
  - (3) ONTAP `-snapdir-access`, `-v3-hide-snapshot`, 하위 디렉터리 접근, ONTAP 한도 1023개, reserve 5%를 더했다. ANF 문서 충돌 (가)·(나)를 두 ONTAP 옵션에 대응시켰고, 이 대응은 [추론]으로 표시했다. 선택지 8과 검증 기준 V9·V10을 더했다.
  - (4) 같은 이름 PUT의 ARM 근거는 찾지 못했다. ONTAP 중복 오류만 선택지 6에 더했다.
  - 조사 상태를 바꿨다.
