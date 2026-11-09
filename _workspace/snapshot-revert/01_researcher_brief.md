# 스냅샷으로 볼륨 되돌리기 (snapshot revert, FR-06) 조사 브리프

- 조사 상태: **한도 도달**. 질문 1~4는 이미 받은 원문으로 답했다. 질문 5(revert 중 I/O 처리)는 조사하지 못했다. 남은 질문은 "미확인 목록"과 "후속 조사 목록"에 있다.
- 조사일: 2026-11-08
- 기준 api-version: `2026-08-01` (stable 스펙). 실서비스 녹화는 `2026-08-15-preview`다.
- 범위 가정: FR-06 볼륨 revert만 다룬다. FR-07(스냅샷에서 새 볼륨 만들기), restoreFiles, 백업, 복제는 범위 밖이고, 거기서 오는 revert 제약은 이름만 적는다.

## 요약 (5줄 이내)

1. revert는 `POST .../volumes/{volumeName}/revert`이고 본문은 `{"snapshotId": <스냅샷 ARM ID>}`다. 스펙의 응답은 `200`(본문 없음)과 `202`(`Location`, `Retry-After`)이고 `final-state-via: location`이다 [스펙 1, 2, 3]. 실서비스는 `202`에 본문 없이 `Azure-AsyncOperation`과 `Location`을 함께 보냈다 [녹화 4].
2. 작업 상태는 `Reverting`에서 `Succeeded`로 가고 `action`은 `POST`다. 걸린 시간은 약 2.6초였다. 끝난 뒤 `Location` URL을 GET하면 볼륨 본문이 왔다. 스펙에는 최종 결과가 `void`로 되어 있어 녹화와 다르다 [녹화 4, 스펙 2].
3. 고른 스냅샷은 revert 뒤에도 남았다 [녹화 4]. ANF 문서에 따르면 고른 스냅샷 뒤의 활성 데이터와 더 새 스냅샷은 사라지고, revert는 되돌릴 수 없다 [문서 6, 7].
4. ANF 문서는 revert가 거의 즉시 끝나고 블록을 복사하지 않는다고 설명한다(inode table 교체) [문서 7]. 다시 마운트해야 하는지, revert 중 볼륨 `provisioningState`가 무엇인지, revert 전용 오류 코드는 무엇인지 ANF 원문에서 찾지 못했다 [미확인].
5. ONTAP에서 대응하는 기능은 `volume snapshot restore`(REST `PATCH /api/storage/volumes/{uuid}?restore_to.snapshot.uuid=…`, `202`)다. 복원 뒤 볼륨 크기는 "현재 크기와 스냅샷 시점 크기 중 큰 값"이 된다 [문서 9, 10].

## 사용자에게 보이는 동작

### 리소스와 API (질문 1)

- **경로**: `POST /subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}/providers/Microsoft.NetApp/netAppAccounts/{accountName}/capacityPools/{poolName}/volumes/{volumeName}/revert?api-version=2026-08-01`. operationId는 `Volumes_Revert`이고 설명은 "Revert a volume to the snapshot specified in the body"다 [스펙 1].
- **본문 모델 `VolumeRevert`**:
  - 속성은 `snapshotId` 하나다. `type: string`, `format: arm-id`이고, 설명은 "Resource id of the snapshot"다. `x-ms-arm-id-details.allowedResources`는 `Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots` 하나다 [스펙 1].
  - 스펙상 **`snapshotId`는 필수가 아니다.** OpenAPI 정의에 `required` 배열이 없고, TypeSpec에서는 `snapshotId?`로 선언된다(`Volume.tsp` 1614~1623행) [스펙 1, 2]. 본문 자체(`body` 파라미터)는 `required: true`다 [스펙 1].
  - 스펙은 "같은 볼륨의 스냅샷이어야 한다"는 제약을 표현하지 않는다. 형식(ARM ID)과 리소스 종류만 지정한다 [스펙 1, 2].
- **응답 코드** [스펙 1]:
  - `200`: "Azure operation completed successfully.", 본문 스키마 없음
  - `202`: "Resource operation accepted.", 헤더 `Location`(string), `Retry-After`(int32)
  - `default`: 공통 `ErrorResponse`
- **LRO 옵션**: `x-ms-long-running-operation: true`, `x-ms-long-running-operation-options.final-state-via: location` [스펙 1]. TypeSpec 선언은 `revert is ArmResourceActionAsync<Volume, VolumeRevert, { @body body: void; }, LroHeaders = ArmLroLocationHeader<FinalResult = void> & Azure.Core.Foundations.RetryAfterHeader>`다(`Volume.tsp` 2633~2645행). 즉 스펙상 최종 결과에는 본문이 없다 [스펙 2].
- **예제 `Volumes_Revert.json`**: 요청 본문 `snapshotId`에 같은 볼륨 스냅샷의 전체 ARM ID(`.../volumes/volume1/snapshots/snapshot1`)를 넣었다. 응답은 `200: {}`와 `202`이고, `202` 헤더는 `Location` 하나다. URL은 `.../locations/eastus/operationResults/{uuid}?api-version=2026-06-15-preview&operationResultResponseType=Location`이다 [스펙 3].
- **녹화 R3의 실제 순서** (.NET `SnapshotTests__RevertVolumeToSnapshot`, 2026-10-30 UTC, api-version `2026-08-15-preview`) [녹화 4]:
  1. `#42 POST .../volumes/volumeName-295/revert` 요청 본문은 `{"snapshotId": "/subscriptions/…/volumes/volumeName-295/snapshots/snapshot-5490"}`였다. **값은 스냅샷 UUID가 아니라 같은 볼륨 스냅샷의 전체 ARM ID다.** 스냅샷의 `properties.snapshotId`는 `cb161c71-…` 같은 UUID다.
  2. 응답은 `202`, `Content-Length: 0`(본문 없음)이었다. 헤더는 `Azure-AsyncOperation: …/providers/Microsoft.NetApp/locations/westus2/operationResults/{opId}?api-version=…`와 `Location`(같은 URL에 `&operationResultResponseType=Location`)였다. **`Retry-After`는 없었다.**
  3. `#43`, `#44`에서 `Azure-AsyncOperation`을 GET하면 `200`이 왔다. 본문은 `{"id": ".../operationResults/{opId}", "name": "{opId}", "status": "Reverting", "startTime": "2026-10-30T00:54:33.6830831Z", "endTime": "0001-01-01T00:00:00Z", "percentComplete": 0.0, "properties": {"resourceName": "<볼륨 ARM ID>", "action": "POST"}}`였다.
  4. `#45`에서는 `status: "Succeeded"`, `percentComplete: 100.0`, `endTime: 2026-10-30T00:54:36.2464465Z`가 왔다. 작업 시간은 약 2.6초다.
  5. `#46`에서 `Location` URL을 GET하면 `200`과 **볼륨 전체 본문**이 왔다(`provisioningState: "Succeeded"`). 볼륨 `etag`는 `00:54:36.185418Z`로 바뀌었다. `systemData.lastModifiedAt`은 생성 시각(`00:48:40`) 그대로였다.
  6. `#50` 스냅샷 목록에 고른 스냅샷 `snapshot-5490`이 그대로 있었다. 값은 `provisioningState: Succeeded`, `created: 2026-10-30T00:54:09.243Z`였다. 다만 `systemData.lastModifiedAt`이 revert 중의 시각인 `00:54:35.015Z`로 바뀌어 있었다.
- **같은 테스트의 비동기 변형** (`SnapshotTests__RevertVolumeToSnapshotAsync`, 2026-10-30 08:51 UTC): 순서가 같다. `202` 뒤에 `Reverting`이 3번 나온 다음 `Succeeded`(`action POST`)가 왔다. 폴링 기준으로 약 5초가 걸렸다. 마지막 `Location` GET은 `200`이었고 볼륨 `provisioningState`는 `Succeeded`였다. revert 뒤에도 고른 스냅샷이 목록에 남았다 [녹화 5].
- **녹화의 한계**: 이 SDK 테스트는 스냅샷을 하나만 만들고 ARM 호출만 한다. 그래서 "더 새 스냅샷이 지워지는지"와 데이터가 실제로 되돌아갔는지는 녹화로 확인할 수 없다 [추론, 녹화 4의 요청 목록에서].

### 비동기 동작 (질문 1)

- revert는 항상 비동기로 관찰됐다. 실서비스는 `202`에 본문 없이 `Azure-AsyncOperation`과 `Location`을 함께 보냈다 [녹화 4, 5]. 스펙에는 `200`(동기 완료)도 있지만 녹화에서는 나오지 않았다 [스펙 1, 녹화 4, 5].
- **작업 상태 값**: `Reverting`에서 `Succeeded`로 간다. ARM 표준 값 `InProgress`가 아니라 리소스 상태와 같은 이름을 쓴다. 이것은 다른 ANF 작업(`Creating`, `Deleting`)과 같은 관행이다 [녹화 4, 5, 스냅샷 브리프 12].
- **`action`**: `POST`다. 생성은 `CREATE`, 삭제는 `DELETE`였다 [녹화 4, 12].
- **revert 중 볼륨의 `provisioningState`**: [미확인]. 녹화에는 revert 중의 볼륨 GET이 없다. `Reverting`이 볼륨 상태로도 보이는지는 확인하지 못했다. 스냅샷 브리프 63행의 "볼륨이 `Reverting` → `Succeeded`"는 **작업 상태**를 그렇게 읽은 것이다(변경 이력 참고). 스펙에서 볼륨의 `provisioningState`는 enum이 아닌 읽기 전용 `string`이라 허용 값 목록이 없다(`Volume.tsp` 138~140행) [스펙 2].
- **revert 뒤의 볼륨**: `provisioningState: Succeeded`였고, `etag`는 갱신됐고, `systemData.lastModifiedAt`은 그대로였다 [녹화 4].

### 제약과 한도 (질문 3)

- **잃는 것** [문서 6, 7]:
  - "Active filesystem data and snapshots taken after the selected snapshot will be lost."
  - "The snapshot revert operation replaces *all* the data in the targeted volume with the data in the selected snapshot."
  - "You can't undo reverting a snapshot."
- **되돌아가는 범위**: 볼륨이 "the data and timestamps that it contained when the selected snapshot was taken"으로 돌아간다 [문서 6].
- **고른 스냅샷**: 문서는 "after the selected snapshot"만 잃는다고 말할 뿐, 고른 스냅샷이 남는다고 직접 쓰지 않는다 [문서 6, 7]. 녹화에서는 고른 스냅샷이 남았다 [녹화 4, 5]. 그보다 오래된 스냅샷이 남는지는 문서 문구("after")에서 그렇게 읽힐 뿐, 직접 확인하지 못했다 [추론, 문서 6에서].
- **속도와 원리**: "near-instantaneous and takes only a few seconds to complete, even for the largest volumes"이다. 원리는 "The active volume metadata (*inode table*) is replaced with the snapshot metadata … No data blocks need to be copied"다 [문서 7].
- **포털 확인 절차**: 볼륨의 Snapshots 메뉴에서 스냅샷을 오른쪽 클릭하고 **Revert volume**을 고른 뒤 볼륨 이름을 입력해야 실행된다 [문서 6]. API 본문에는 확인용 필드가 없다 [스펙 1].
- **볼륨 크기(`usageThreshold`)**: 스냅샷 뒤에 크기를 바꾼 볼륨을 revert하면 ANF가 크기를 어떻게 다루는지 [미확인]. ANF revert 문서, 스냅샷 소개, 크기 조정 문서, FAQ(capacity-management)에 언급이 없다 [문서 6, 7, 8]. ONTAP에서는 "the size of the flexible volume will be set to either the current volume size or the snapshot size - whichever is greater"다 [문서 9]. ANF가 이 규칙을 그대로 따르는지, ANF가 `usageThreshold`를 다시 맞추는지는 [미확인].
- **범위 밖 기능에서 오는 제약** (이름만 적는다) [문서 6]:
  - 백업이 켜진 볼륨은 "the latest snapshot used for backup"보다 새 스냅샷으로만 revert할 수 있다.
  - 복제(source 볼륨)는 "the latest SnapMirror snapshot"보다 새 사용자 스냅샷으로만 revert할 수 있다. revert 기능 자체는 복제 구성에서도 쓸 수 있다.

### 오류 상황 (질문 2)

- **ANF의 revert 전용 오류 코드와 문구는 원문에서 찾지 못했다** [미확인]. 찾아본 곳은 다음과 같다.
  - 스펙: `default` → `ErrorResponse`뿐이다 [스펙 1].
  - 예제: 성공 예제만 있다 [스펙 3].
  - 녹화: 성공 흐름만 있다 [녹화 4, 5].
  - ANF 문서: revert 문서, `azure-netapp-files-troubleshoot-resource-provider-errors.md`, `troubleshoot-volumes.md`, `troubleshoot-snapshot-policies.md`, `troubleshoot-cross-region-replication.md`, FAQ(nfs, capacity-management, backup). 이 중 revert를 언급하는 곳은 revert 문서, 스냅샷 소개, `azure-netapp-files-manage-data-restores.md` 17행(개요 한 줄)뿐이고, 모두 오류는 다루지 않는다 [문서 6, 7, 8].
- 질문별 상태:

| 조건 | ANF 근거 | 비고 |
| --- | --- | --- |
| 없는 스냅샷 | [미확인] | ARM 관행상 404 계열일 수 있지만 근거 없음 [추론] |
| 다른 볼륨의 스냅샷 | [미확인] | 스펙은 리소스 종류만 제한한다 [스펙 1] |
| 형식이 틀린 `snapshotId` | [미확인] | 스펙 `format: arm-id` [스펙 1] |
| `snapshotId` 누락 | [미확인] | 스펙상 선택 속성이다 [스펙 1, 2] |
| 볼륨이 `Succeeded`가 아님 | [미확인] | |
| 볼륨·스냅샷 작업과 충돌 | [미확인] (ANF) | ONTAP: revert 중 스냅샷 생성을 `1638532`로 거절 [문서 12] |
| 백업·복제 기준 스냅샷보다 오래된 스냅샷 | 거절된다는 것만 [문서 6] | 코드와 문구 [미확인] |

- **ONTAP REST `PATCH /storage/volumes/{uuid}`의 복원 관련 오류** (ANF가 이 코드를 그대로 보여 주는지는 [미확인]) [문서 10]:
  - `524511` "Failed to restore snapshot "restore_to.snapshot.name"."
  - `1638480` "Failed to promote snapshot "restore_to.snapshot.name" because one or more newer snapshots are currently used as a reference snapshot for data protection operations."
  - `9437885` "The volume is not online."
  - `9437886` "Volume snapshot restore failed because there are newer unexpired locked snapshots in the volume."
  - `918251` "Specifying a value is not valid for a snapshot restore operation."
  - `1638590` "Promoting a "-pre-conversion" snapshot is not supported."
- ONTAP 스냅샷 생성 쪽 `1638532` "Failed to create the snapshot on the specified volume because a revert operation is in progress"(스냅샷 브리프에서 인용) [문서 12].

## 데이터 플레인에서 보이는 효과

- **볼륨 내용**: 고른 스냅샷 시점의 데이터와 타임스탬프로 돌아간다. 그 뒤에 쓴 데이터는 사라진다 [문서 6, 7].
- **스냅샷 목록과 `.snapshot`**: 더 새 스냅샷은 사라지고 [문서 6, 7], 고른 스냅샷은 남는다 [녹화 4, 5]. `.snapshot` 디렉터리에서 더 새 스냅샷의 항목이 없어지는 것은 문서 문구에서 추론한 것이다. 클라이언트에서 관찰한 근거는 없다 [추론, 문서 6에서].
- **이미 마운트한 NFS 클라이언트** (다시 마운트, 파일 핸들, stale file handle, 열린 파일): **ANF·ONTAP 원문 어디에도 언급이 없다** [미확인]. 찾아본 곳은 다음과 같다. 그래서 클론의 동작을 S5에서 재고 문서화하는 것이 유일한 근거가 된다.
  - ANF: `snapshots-revert-volume.md`, `snapshots-introduction.md` 136~151행, `faq-nfs.md`, `troubleshoot-volumes.md` [문서 6, 7, 8]
  - ONTAP: `restore-contents-volume-snapshot-task.adoc`, CLI `volume snapshot restore`, REST PATCH 페이지 [문서 9, 10, 11]
  - 참고: ONTAP의 `-preserve-lun-ids`는 "non-disruptive to clients"를 LUN·NVMe namespace 식별자에 대해서만 다룬다. NAS 클라이언트에 대한 언급은 없다 [문서 9].
- **revert 중 I/O**: 조사하지 못했다(질문 5, 후속 조사 목록).

## ONTAP 대응 개념

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| 볼륨 revert (`POST .../revert`) | SnapRestore 볼륨 복원: CLI `volume snapshot restore -vserver -volume -snapshot [-force] [-preserve-lun-ids]`, System Manager의 Storage → 볼륨 → Snapshot copies → Restore | ANF 문서는 ONTAP 이름을 말하지 않는다. 설명("inode table 교체, 블록 복사 없음")과 동작("이후 변경 손실")이 ONTAP 설명("replaces the current working copy of the volume with the snapshot that results in a loss of all changes made since the snapshot was created")과 맞는다 | [추론] 문서 7과 문서 9의 대조에서 |
| (내부 호출) | REST `PATCH /api/storage/volumes/{uuid}`, **쿼리 파라미터**로 `restore_to.snapshot.uuid` 또는 `restore_to.snapshot.name`. 응답은 `202 Accepted` | `restore_to.snapshot.force`(9.19)는 "the restore proceeds even if newer snapshots exist or have protective metadata (such as owners, tags, or retention)". `preserve_lun_ids`(9.10). `restore_to.path`, `restore_path`, `start_byte`, `byte_count`(9.10)는 파일 단위 복원용이다(범위 밖) | [문서 10] |
| ANF가 ONTAP에 넘기는 값 | `restore_to.snapshot.uuid` | ANF 스냅샷 `snapshotId`가 ONTAP 스냅샷 uuid로 보인다는 스냅샷 브리프의 추론에 기대므로, 확인되지 않은 연결이다 | [추론] 스냅샷 브리프 12 |
| `202` 이후 진행 | ONTAP job | PATCH 응답은 `202`다 [문서 10]. job 본문 형식은 이 페이지에서 따로 확인하지 않았다. 스냅샷 POST와 같은 job 링크 구조일 것으로 보인다 | [문서 10] / [추론] 스냅샷 브리프 12에서 |
| 더 새 스냅샷의 손실 | ONTAP 복원 후 더 새 스냅샷 | ONTAP 원문에는 "더 새 스냅샷을 지운다"는 문장이 없다. 다만 다음 두 문장은 복원이 더 새 스냅샷을 없앤다는 전제가 있어야 성립한다: `-force` 설명("restored even if the volume has one or more newer snapshots which are currently used as reference snapshot by SnapMirror … this will cause future SnapMirror transfers to fail")과 오류 `1638480`, `9437886` | [추론] 문서 9, 10에서 |
| 크기 | 복원 후 FlexVol 크기 = max(현재 크기, 스냅샷 시점 크기) | ANF `usageThreshold`에 이 규칙이 그대로 적용되는지는 [미확인] | [문서 9] |
| 원리 (WAFL) | active file system의 메타데이터(inode table)를 스냅샷의 것으로 교체한다 | ANF 문서의 설명이다. ONTAP 원문(이번에 받은 범위)에는 WAFL 내부 설명이 없다 | [문서 7] / ONTAP 쪽 [미확인] |
| 백업·복제 제약 | SnapMirror 기준 스냅샷, 잠긴(locked) 스냅샷 | 이름만 적는다 | [문서 6, 9, 10] |

## 구현 범위 후보

- **이번에 재현할 것** (이유)
  - `POST revert`, `202`, 본문 없음, 두 추적 헤더, 작업 상태 `Reverting` → `Succeeded`, `action POST`: 녹화로 확인된 실제 계약이다 [녹화 4, 5].
  - 볼륨 내용을 고른 스냅샷 시점으로 되돌리기: FR-06의 핵심이고 "실제로 동작"해야 한다는 요구에 해당한다.
  - 더 새 스냅샷 삭제와 고른 스냅샷 유지: 문서와 녹화로 확인된 사용자 관찰 동작이다 [문서 6, 녹화 4].
  - 이미 마운트한 클라이언트의 관찰 결과 기록: FR-06 수락 기준이다. ANF·ONTAP 원문에 근거가 없어 클론이 직접 측정해야 한다.
- **다음으로 미룰 것**
  - 백업·복제 기준 스냅샷 제약: 해당 기능이 없다.
  - `force`, 잠긴 스냅샷, LUN 관련 옵션: ONTAP 전용이고 ANF API에 노출되지 않는다 [스펙 1].
- **리더·사용자가 정해야 할 선택지**
  1. **최종 `Location` GET 응답**: 스펙은 최종 결과 `void`로 `200` 본문 없음 [스펙 2, 3], 실서비스는 `200`에 볼륨 본문을 보냈다 [녹화 4, 5]. 어느 쪽을 따를지 정해야 한다.
  2. **revert 중 볼륨 `provisioningState`**: ANF 값은 [미확인]이다. 작업 상태 이름을 따라 `Reverting`을 볼륨에도 보일지, 볼륨은 `Succeeded`로 두고 작업 상태만 `Reverting`으로 할지 정해야 한다.
  3. **`202` 헤더**: 스펙은 `Location`과 `Retry-After`, 실서비스는 `Azure-AsyncOperation`과 `Location`(`Retry-After` 없음)이다.
  4. **`snapshotId` 검사**: 스펙상 선택 속성이고 같은 볼륨 제약도 표현되지 않는다. 누락, 형식 오류, 다른 볼륨, 없는 스냅샷 각각의 응답 코드와 ARM 오류 코드는 ANF 근거가 없어([미확인]) 클론이 정해야 한다.
  5. **고른 스냅샷 유지와 데이터 플레인 방식**: ANF에서는 고른 스냅샷이 남는다 [녹화 4]. 스냅샷을 소비하는 방식(예: thin merge)을 쓰면 같은 이름과 ID의 스냅샷을 다시 만들어야 하므로, S5 결과와 함께 판단해야 한다.
  6. **크기 규칙**: ONTAP의 max(현재, 스냅샷 시점) 규칙을 따를지, `usageThreshold`를 그대로 둘지 정해야 한다(ANF [미확인]).
  7. **충돌 규칙**: revert 중 스냅샷 생성·삭제, 볼륨 PATCH·DELETE를 어떻게 거절할지 정해야 한다. ANF 근거는 [미확인]이고 ONTAP에는 `1638532`가 있다.
- **검증 기준 후보** (클라이언트에서 관찰)
  1. `POST revert` → `202`, 본문 없음, `Azure-AsyncOperation`과 `Location` 헤더. 폴링하면 `Reverting`(`action POST`, `resourceName` = 볼륨 ID)을 거쳐 `Succeeded`가 된다.
  2. 스냅샷 뒤에 만든 파일은 사라지고, 스냅샷 뒤에 지운 파일은 돌아오고, 바꾼 파일은 스냅샷 시점 내용과 같다. 볼륨 트리의 체크섬이 revert 전 `.snapshot/<고른 이름>` 트리의 체크섬과 같다.
  3. 고른 스냅샷과 그보다 오래된 스냅샷은 ARM 목록과 `.snapshot`에 남고 내용이 바뀌지 않는다. 더 새 스냅샷은 ARM 목록과 `.snapshot` 양쪽에서 사라진다.
  4. revert 전부터 마운트한 클라이언트(NFSv3, NFSv4.1 각각)에서 다음을 기록한다: 다시 마운트하지 않고 `ls`와 기존 파일 읽기를 할 수 있는지, revert 전에 열어 둔 파일 디스크립터, 스냅샷 뒤에 만든 파일의 핸들(ESTALE 여부), 다시 마운트한 뒤의 결과.
  5. revert 중에 같은 볼륨으로 스냅샷 생성 요청을 보내면 정한 규칙대로 거절된다.
  6. 거절 조건(선택지 4) 각각에서 데이터 플레인이 바뀌지 않는다(체크섬이 그대로다).

## 미확인 목록

- **revert 중 볼륨 GET의 `provisioningState`**: 설계를 막는다(선택지 2). 녹화 R3와 비동기 변형에 revert 중 볼륨 GET이 없고, 스펙에는 enum이 없다.
- **revert 전용 ANF 오류 코드와 문구** (없는 스냅샷, 다른 볼륨 스냅샷, 형식 오류, 누락, 볼륨 상태, 진행 중 작업 충돌): 클론이 정하면 막지 않는다. 찾아본 곳은 스펙, 예제, 녹화 2개, ANF 문서 10개(위 "오류 상황")다.
- **이미 마운트한 NFS 클라이언트에 대한 ANF·ONTAP의 공식 언급**: 막지 않지만, 면접에서는 "공식 언급 없음, 클론 측정값"이라고 말해야 한다. 찾아본 곳은 ANF revert 문서, 스냅샷 소개, faq-nfs, troubleshoot-volumes, ONTAP restore 작업 문서, CLI, REST PATCH다.
- **revert 뒤 `usageThreshold` 처리**(ANF): 선택지 6에 영향을 준다. ONTAP 규칙만 확인했다 [문서 9].
- **"ONTAP이 더 새 스냅샷을 지운다"는 직접 문장**: [추론]으로만 있다. 이번에 받은 ONTAP 원문 3개에는 그런 문장이 없다.
- **WAFL 수준의 SnapRestore 원리를 다룬 ONTAP 원문**: 개념 문서용이고 설계는 막지 않는다. ANF 문서 7의 설명만 있다.
- **revert 뒤 고른 스냅샷의 `systemData.lastModifiedAt`이 바뀐 이유** [녹화 4]: 막지 않는다.

## 후속 조사 목록

- (질문 5) revert 중 볼륨에 오는 클라이언트 I/O를 ANF·ONTAP이 어떻게 다루는지(차단, 실패, 지연). 원문 미조사.
- ONTAP REST `PATCH /storage/volumes` `202` job 본문과 SnapRestore job의 상태 전이(스냅샷 브리프의 job 모델과 같은지).
- ONTAP 개념 문서 중 SnapRestore 원리(WAFL root inode 교체 등) 설명이 있는 TR이나 개념 adoc.
- revert 실패 경로를 담은 Python SDK 녹화나 az CLI 문서(`az netappfiles volume revert`)의 인자와 예시.
- 백업·복제 기준 스냅샷 제약의 오류 문구(해당 기능을 만들 때).

## 출처

- [1] Azure REST API specs — `specification/netapp/resource-manager/Microsoft.NetApp/NetApp/stable/2026-08-01/` OpenAPI JSON. `paths["…/volumes/{volumeName}/revert"]`와 `definitions.VolumeRevert`를 봤다. 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`. 사본은 재사용: `_workspace/capacity-pool/sources/spec/netapp-2026-08-01.json`
- [2] Azure REST API specs — `Volume.tsp`. https://raw.githubusercontent.com/Azure/azure-rest-api-specs/3b64c3a12af9938128abcf05d04c323a518ea78a/specification/netapp/resource-manager/Microsoft.NetApp/NetApp/Volume.tsp (2026-11-08 받음). 138~140행(`provisioningState?: string`), 1612~1623행(`VolumeRevert`), 2633~2645행(`revert`). 사본: `_workspace/snapshot-revert/sources/spec/Volume.tsp`
- [3] Azure REST API specs — `stable/2026-08-01/examples/Volumes_Revert.json`, 같은 커밋(2026-11-08 받음). 사본: `_workspace/snapshot-revert/sources/spec/examples/Volumes_Revert.json`
- [4] Azure SDK 녹화 (.NET) — `SnapshotTests__RevertVolumeToSnapshot.json`. azure-sdk-assets 태그 `net/netapp/Azure.ResourceManager.NetApp_1c0dc6690c`, 경로 `net/sdk/netapp/Azure.ResourceManager.NetApp/tests/SessionRecords/SnapshotTests/`. 녹화 2026-10-30 00:47~00:58 UTC, api-version `2026-08-15-preview`. 본 항목은 `#42`~`#46`, `#50`이다. 사본은 재사용: `_workspace/netapp-account/sources/recordings/net/`
- [5] 같은 태그의 `SnapshotTests__RevertVolumeToSnapshotAsync.json`. 녹화 2026-10-30 08:51 UTC. 본 항목은 `#41`~`#46`, `#50`이다. 사본은 [4]와 같은 곳이다.
- [6] Microsoft Learn — Revert a volume using snapshot revert (`articles/azure-netapp-files/snapshots-revert-volume.md`, ms.date 03/28/2025). MicrosoftDocs/azure-docs 커밋 `548a6fcfecc7e850241c77f1a29db21d781d5d1b`. 사본은 재사용: `_workspace/snapshot/sources/docs/`
- [7] Microsoft Learn — How Azure NetApp Files snapshots work (`snapshots-introduction.md`) 136~151행 "Restoring (reverting) an online snapshot in-place". 같은 커밋. 사본: `_workspace/snapshot-revert/sources/docs/`
- [8] Microsoft Learn — 같은 커밋의 `azure-netapp-files-troubleshoot-resource-provider-errors.md`, `troubleshoot-volumes.md`, `troubleshoot-snapshot-policies.md`, `troubleshoot-cross-region-replication.md`, `faq-nfs.md`, `faq-capacity-management.md`, `faq-backup.md`, `azure-netapp-files-resize-capacity-pools-or-volumes.md`, `azure-netapp-files-manage-data-restores.md`. revert 관련 언급이 있는지 찾는 데 썼다. 사본: `_workspace/snapshot-revert/sources/docs/`
- [9] NetApp ONTAP 9.19.1 command reference — `volume snapshot restore` (페이지 날짜 10/06/2026). https://docs.netapp.com/us-en/ontap-cli/volume-snapshot-restore.html (2026-11-08 curl). 사본: `_workspace/snapshot-revert/sources/ontap/cli-volume-snapshot-restore.html`, `.txt`
- [10] NetApp ONTAP REST API reference — `PATCH /storage/volumes/{uuid}` "Update volume attributes" (페이지 날짜 10/13/2026). https://docs.netapp.com/us-en/ontap-restapi/patch-storage-volumes-.html (2026-11-08 curl, `/ontap/patch-storage-volumes-.html`에서 301 리디렉트). 사본: `_workspace/snapshot-revert/sources/ontap/patch-storage-volumes.html`, `.txt`(파라미터 86~131행, 오류 1010~1180행)
- [11] NetAppDocs/ontap — `data-protection/restore-contents-volume-snapshot-task.adoc`, `_include/restore-snapshots-cli.adoc`. 커밋 `37d53f2a6cff395e1fb457f522c61826a8dbf379` (2026-11-08 받음). 사본: `_workspace/snapshot-revert/sources/ontap/`
- [12] 스냅샷 조사 브리프 `_workspace/snapshot/01_researcher_brief.md`. 작업 상태 형식(`CREATE`, `DELETE`), 스냅샷 ID 모양에 대한 추론, ONTAP `1638532`(그 브리프의 [문서 15], ONTAP REST POST snapshots)를 인용했다.
- [13] (참고) `netapp_ontap` 9.19.1.0 휠의 `netapp_ontap/resources/volume.py`. `restore_to.*`가 PATCH 필드 목록에만 있고 스키마 필드는 없다. 휠 출처는 스냅샷 브리프 [17] 부근에 있다. 추출 사본: `_workspace/snapshot-revert/sources/ontap/netapp_ontap__resources__volume.py.txt`

## 변경 이력

- 2026-11-08: 처음 작성(한도 도달). 스냅샷 브리프 63행의 "볼륨이 `Reverting` → `Succeeded`"를 녹화 원문과 대조했다. `Reverting`은 **작업 상태(`status`)**이고, revert 중 볼륨 GET은 녹화에 없다는 점을 바로잡아 적었다(스냅샷 브리프 자체는 고치지 않았다).
