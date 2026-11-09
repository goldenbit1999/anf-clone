# 스냅샷에서 새 볼륨으로 복원 (restore a snapshot to a new volume)

> ANF의 "스냅샷에서 새 볼륨으로 복원"은 별도 액션이 아니라 `properties.snapshotId`(스냅샷 ARM ID)를 넣은 볼륨 PUT이다. 이 클론은 원본 스냅샷 LV의 쓰기 가능 thin 스냅샷을 새 볼륨 LV로 만든다. 그래서 데이터를 복사하지 않고 LV가 0.2초 안팎에 생기며, 처음부터 원본과 독립이다. ANF는 생성이 끝난 뒤에도 몇 분 동안 백그라운드 복사(`cloneProgress`)를 하고 그동안 원본을 지울 수 없다. 클론에는 복사 단계가 없어서 원본 보호는 생성 작업 동안뿐이다. 이 차이와 그 이유가 이 문서의 중심이다.

코드 인용 기준: 커밋 `a8ddc0a` (제품 코드 내용 해시 `1e950522c13e991a…`, 검증 시작과 끝이 같다)

FR-07(스냅샷에서 새 볼륨으로 복원)을 다룬다. 브랜치는 `feature/restore-new-volume`이다. 공통 비동기 작업(LRO) 계층은 [계정 문서](netapp-account.md), 볼륨 LV와 볼륨마다 knfsd 인스턴스를 두는 구조는 [볼륨 문서](volume.md), 스냅샷 LV·`.snapshot` export·스냅샷마다 `fsid`는 [스냅샷 문서](snapshot.md), "스냅샷의 쓰기 가능 스냅샷으로 볼륨 LV 교체"는 [되돌리기 문서](snapshot-revert.md)에 있다. 이 문서는 그것들을 새 볼륨 복원이 어떻게 다시 쓰는지와 새로 생긴 것만 설명한다.

근거 표시는 브리프를 따른다.

| 표시 | 뜻 |
| --- | --- |
| [스펙] | Azure REST API 스펙(OpenAPI/TypeSpec)에 적혀 있다 |
| [문서] | Microsoft Learn이나 NetApp 문서에 적혀 있다 |
| [녹화] | Azure SDK 테스트 녹화에서 실서비스 응답으로 관찰했다. 문서로 보장된 동작은 아니다 |
| [추론] | 근거에서 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |
| [KB 요약] | NetApp KB를 WebSearch 요약으로만 봤다. 원문 미확인 |
| [클론 측정] | 스파이크 S6·S5와 검증자의 측정이다. ANF·ONTAP 사실이 아니라 이 클론의 동작이다 |

**이 기능의 설계 결정 1~16은 모두 자동 채택이다.** 로드맵 총괄(`anf-roadmap`)이 사용자에게 물어야 하는 결정(확정된 D-nn이나 `CLAUDE.md` "Decided"를 바꾸는 것, PRD 수락 기준 축소, 기기·저장소 설정, 스파이크 실패)이 없다고 판단해 사람에게 묻지 않고 골랐다. 목록은 `_workspace/roadmap.md`의 "검토할 자동 채택 결정"에 있다. 면접에서 "왜 이렇게 골랐나"를 답할 수 있게, 3절의 설계 결정 표에 버린 대안과 이유를 모두 적었다.

---

## 1. ANF에서는

### 1.1 API와 응답

- **경로는 일반 볼륨 PUT과 같다.** `PUT .../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}`에 `properties.snapshotId`를 넣는다 [녹화][스펙]. 복원 전용 액션은 없다 [스펙]. (`splitCloneFromParent`는 단기 클론(short-term clone)용이고 이 기능과 다르다.)
- **`snapshotId`는 스냅샷의 ARM 리소스 ID다.** `format: arm-id`, 허용 타입은 `.../volumes/snapshots`다. 스냅샷 리소스의 `properties.snapshotId`(UUID)가 아니다 [스펙][녹화]. 되돌리기 본문의 `snapshotId`와 같은 형식이다 [스펙].
- **생성 때만 쓸 수 있다.** `x-ms-mutability [read, create]`, `x-nullable: true`이고 PATCH 모델(`VolumePatchProperties`)에 없다 [스펙]. GET에는 그대로 남는다 [녹화]. 재PUT에서 다른 값을 보낼 때의 실동작은 [미확인].
- **응답** (api-version `2026-08-01`, 녹화는 `2026-08-15-preview`):

| 항목 | 실서비스 | 근거 |
| --- | --- | --- |
| PUT 응답 | `201`, 헤더 `Azure-AsyncOperation` + `Location`(`Retry-After` 없음), 본문 `Creating`. `originatingResourceId`·`fileSystemId`는 아직 없다 | [녹화] |
| 작업 상태 | `Creating` → `Succeeded`, `action: CREATE` | [녹화] |
| 걸린 시간 | **약 11초.** 같은 녹화의 일반 볼륨 생성은 약 6분 | [녹화] |
| 끝난 뒤 GET | `originatingResourceId` = 원본 스냅샷 ARM ID, 원본과 다른 `fileSystemId`와 마운트 IP | [녹화] |
| `cloneProgress` | `Succeeded` 직후 `0`, 약 5분 45초 뒤 응답에서 사라짐(null). 스펙: "When this value is empty/null there is no cloning process currently happening … will update every 5 minutes during cloning." | [녹화][스펙] |
| `maximumNumberOfFiles` | `cloneProgress`가 사라진 응답에서 처음 나타남(원본과 같은 값). 같은 때 etag가 바뀜 | [녹화] |
| `isRestoring` | 한 번도 나오지 않음. 언제 `true`인지 [미확인]. 백업 복원용일 수 있다 [추론] | [녹화] |

- 녹화에서 `protocolTypes`·`serviceLevel`·`exportPolicy`를 보내지 않았고 응답은 `NFSv3`, 풀의 `Premium`, 기본 export 규칙이었다 [녹화]. 이것이 원본 볼륨 값을 물려받은 것인지 일반 기본값인지는 브리프로 가를 수 없다.
- **새 볼륨은 바로 쓸 수 있다.** "The volume can be used by NFS and SMB clients immediately while the restore operation is completing in the background." [문서]. 녹화에서도 `Succeeded` 직후 GET에 `mountTargets`가 있었다 [녹화].

### 1.2 base 스냅샷

- 새 볼륨에는 **원본 스냅샷과 이름이 같고 `snapshotId`가 다른 base 스냅샷**이 하나 생긴다. `created`는 원본 스냅샷 시각을 초 단위로 자른 값이다(원본 `00:25:49.349Z`, base `00:25:49Z`) [녹화]. base의 `systemData`는 볼륨 생성 약 4분 뒤 `lastModifiedByType: Application`으로 바뀌었다 [녹화].
- 문서: "By default, the new volume includes a reference to the snapshot … referred to as the *base snapshot*", "does *not* consume any additional space" [문서].
- **`deleteBaseSnapshot`은 출처끼리 대상이 다르게 읽힌다.** 스펙은 "the snapshot the volume was created from will be automatically deleted after the volume create operation has finished"(원본 스냅샷으로도 읽힌다), 문서는 "If you don't want the new volume to contain this base snapshot"(새 볼륨 쪽)이다. 녹화가 없어 실동작은 [미확인]. 문서가 대상을 분명히 하므로 새 볼륨 쪽일 가능성이 크다 [추론].

### 1.3 백그라운드 복사와 원본 보호

- **`Succeeded` 뒤에도 복사가 이어진다.** "near-instantaneous … almost immediately available for access, while the actual volume and snapshot data blocks are being copied over" [문서]. 원본 크기에 따라 "minutes to hours"가 걸릴 수 있다 [문서]. 이것이 `cloneProgress` 시간을 말하는 것으로 본다 [추론].
- **그동안 원본을 지울 수 없다.** "this process can take considerable time during which the parent volume and snapshot can't be deleted", "You can't delete a snapshot if … it's in the process of being cloned" [문서]. 거절할 때의 HTTP 코드와 오류 코드는 [미확인].
- **끝나면 독립이다.** "After this process is completed, the volume is independent and disassociated from the original volume, and source volumes and snapshot can be managed or removed independently" [문서].
- 권고(거절인지는 [미확인]): 새 볼륨의 스냅샷·백업·복제는 완전히 복원된 뒤에 켤 것, 한 번에 하나의 복원만, 원본이 되돌려지는 동안 새 볼륨 복원 같은 연쇄 복원은 피할 것 [문서].

### 1.4 공간

- 새 볼륨도 일반 볼륨처럼 `usageThreshold`만큼 풀 할당량을 쓴다고 본다 [추론, 풀 할당은 볼륨 quota 합계라는 문서에서].
- "By nature of the data copy process, storage capacity pool consumption doubles when the restore completes, and the new volume show the full active capacity of the original snapshot." [문서]. 이것이 풀 "할당"을 말하는지 "사용량"을 말하는지는 문서가 나누지 않는다 [미확인].
- 단기 클론(short-term clone)은 이와 달리 부모와 블록을 공유한다 [문서]. 범위 밖이다.

### 1.5 확인하지 못한 것 [미확인]

다른 풀·계정·서비스 수준의 스냅샷 허용 여부(녹화는 같은 풀만, 문서의 주석 처리된 Elastic 절만 "같은 풀"을 요구), `usageThreshold` 하한, 원본과 다른 `protocolTypes` 허용(포털 문서는 "The new volume uses the same protocol that the snapshot uses."), 거절 코드 전부, 재PUT의 `snapshotId` 변경, 복사 중 원본 revert의 동작. 오류 문서에서 이 기능을 직접 말하는 것은 "Failed to split new volume from source volume snapshot"(원인: 볼륨이 오류 상태로 끝남, 해결: 볼륨을 지우고 스냅샷에서 다시 만든다)이다 [문서]. 없는 리소스를 가리킬 때의 "The requested {resource} was not found."도 있지만, `snapshotId`가 없는 스냅샷을 가리킬 때 이것이 PUT 응답으로 오는지 작업 `Failed`로 오는지는 [미확인]이다.

---

## 2. ONTAP에서는

### 2.1 대응 기능: FlexClone + clone split [추론]

**ANF가 FlexClone을 쓴다는 공식 문장은 없다.** 근거는 둘이다. ANF 문서가 이 작업을 "clones"라고 부르고, 오류 문구가 "Failed to split new volume from source volume snapshot"이다 [문서]. 그래서 "스냅샷으로 FlexClone을 만들고, 백그라운드에서 split한다"로 읽는다 [추론]. 되돌리기(revert)의 대응인 SnapRestore와는 다른 기능이다(SnapRestore는 제자리 복원).

| ANF | ONTAP | 근거 |
| --- | --- | --- |
| 스냅샷에서 새 볼륨 | FlexClone 볼륨 생성 + clone split | 대응 [추론] |
| `snapshotId` | `clone.parent_volume` + `clone.parent_snapshot`. ONTAP은 부모 스냅샷을 주지 않으면 스냅샷을 새로 만든다 | 필드 [문서], 대응 [추론] |
| `cloneProgress` | `clone.split_complete_percent` ("Percentage of FlexClone volume blocks split from its parent volume"). null이 되는 것은 split 완료(더는 FlexClone이 아님)와 맞다 | 필드 [문서], 대응 [추론] |
| 새 볼륨의 base 스냅샷 | "The snapshot used to create a FlexClone volume is also shared with the parent volume." AFF의 ONTAP 9.4 이상 split에서는 "Existing snapshots are not deleted" | [문서] |
| 복사 중 원본 삭제 금지 | "you cannot delete the parent volume while the FlexClone volume exists". 부모 스냅샷은 `busy, vclone`(owner "volume clone")으로 지울 수 없다 | 부모 볼륨 [문서], 스냅샷 [KB 요약]. 오류 `1638543` "Failed to delete snapshot because it has an owner"와의 연결은 [추론] |
| 복사 뒤 독립 | split 뒤 일반 FlexVol. "After a FlexClone volume is split from its parent the two cannot be rejoined." | [문서] |
| 복사 중 새 볼륨 스냅샷 권고 | "New snapshots of the FlexClone volume cannot be created during the split operation" | [문서], 대응 [추론] |

### 2.2 즉시 생기는 이유와 공간

- **만들 때.** FlexClone은 부모와 base 스냅샷을 공유하고, 새 FlexClone은 명목 크기의 약 0.5%만 쓴다 [문서]. 만들 때 명목 크기는 부모 크기와 같다 [문서]. ANF가 이 크기를 사용자의 `usageThreshold`로 언제 바꾸는지는 [미확인]이다. 브리프에는 FlexClone이 왜 즉시 생기는지에 대한 WAFL 내부 설명이 없다. 면접에서 그 이상을 말하려면 따로 확인해야 한다.
- **split 뒤.** "both the parent FlexVol volume and the clone require the full space allocation determined by their volume guarantees" [문서]. 다만 AFF의 ONTAP 9.4 이상에서 non-guaranteed 볼륨은 split이 물리 블록을 공유한 채 데이터를 복사하지 않는다 [문서]. ANF 문서의 "data copy process"(1.4절)와 맞지 않는다. ANF 백엔드가 어떤 플랫폼·설정인지는 브리프에 없어서 이 불일치를 풀 수 없다 [미확인].
- **split 동작.** 백그라운드에서 돌고, split 중에도 clone과 부모의 데이터에 접근할 수 있다. FlexClone을 offline하면 멈추고 online하면 이어진다 [문서]. 이것이 ANF의 "복사 중에도 바로 쓸 수 있다"와 맞는다 [추론].

### 2.3 ONTAP REST FlexClone API (agent 부분집합의 근거)

- 생성: `POST /api/storage/volumes`, 예시 본문 `{"name": "vol1_clone", "clone": {"parent_volume": {"name": "vol1"}, "is_flexclone": true}, "svm": {"name": "vs0"}}`. 응답은 `202` + job (`return_timeout` 안에 끝나면 `201`) [문서].
- `clone`의 POST 필드: `is_flexclone`("needs to be set when creating a FlexClone volume"), `parent_volume.{name,uuid}`, `parent_snapshot.{name,uuid}`, `parent_svm`, `lun_name`, `qtree_name` [문서].
- split: `PATCH /api/storage/volumes/{uuid}` 본문 `{"clone": {"split_initiated": true}}` [문서].
- 클론 관련 오류: `524601` "Parent volume … not found", `918243`(스냅샷 uuid와 이름 불일치), `524597`/`524819`(클론 생성 실패) 등 [문서]. 부모 스냅샷이 없을 때의 전용 코드는 찾지 못했다 [미확인].

---

## 3. 이 프로젝트에서는

### 구조

```
PUT .../volumes/{n}  {"properties": {"snapshotId": <스냅샷 ARM ID>, "usageThreshold": …, …}}
  anf-api  arm_app.put_volume (arm_app.py:245-259)
    volumes.put_volume -> _new_volume -> _restore_source (검사)
    한 트랜잭션: 볼륨 행(Creating, snapshotId) + CREATE 작업 -> 201 + 두 헤더
  LRO 워커 -> 볼륨 ensure 처리기 (volumes.py:562-600)
    clone_source: (원본 볼륨 fileSystemId, 원본 스냅샷 snapshotId)
    StorageClient.ensure_volume(clone=…)
      POST /api/storage/volumes  {uuid, name, size, nas, "clone": {is_flexclone, parent_volume.uuid, parent_snapshot.uuid}}
  storage agent  _parse_clone -> job -> FlexVolManager.create
    _ensure_lv:    lvcreate -s -kn -p rw -n vol_<N>  (볼륨 태그 + 진행 표시 anf_cl_*)  anf/snap_<S>
    _finish_clone: lvextend -> 마운트 -> resize2fs -> .snapshot 정리 -> base 스냅샷 -> chmod
                   -> export 파일·인스턴스 -> 진행 표시 지우기
  anf-api: mountTargets 기록 -> agent 스냅샷 목록 읽기
           -> 한 트랜잭션: base 스냅샷 행(Succeeded) + originatingResourceId -> 작업 Succeeded
```

데이터 플레인에서 LV는 이렇게 이어진다.

```
씬 풀 anf/aggr0
  vol_<V> (원본 볼륨, rw)
    └ snap_<S> (원본 스냅샷, ro)            ns/<V>/.snapshot/S
        └ vol_<N> (새 볼륨, rw 쓰기 가능 thin 스냅샷)   ns/<N>,  인스턴스 anf-nfs-<N>, 새 IP
            └ snap_<base> (base 스냅샷, ro, 이름 S)     ns/<N>/.snapshot/S
```

LVM의 `origin`은 메타데이터 표시일 뿐이다. `snap_<S>`나 `vol_<V>`를 지워도 LVM은 거절하지 않고 `vol_<N>`의 `origin`이 빈칸이 될 뿐이다. 데이터는 그대로다 [클론 측정 S6 I3~I5].

### 코드 따라가기

#### (1) anf-api: 본문 검사 — `volumes.py:44-72`, `:154-160`, `:185`

- `snapshotId`는 `_PROPERTIES`에 있는 쓸 수 있는 속성이다(`volumes.py:63`). `_check_property`(`:154-160`)가 정규식 `_SNAPSHOT_ID`(`:44-46`, 대소문자 무시)로 "스냅샷 ARM ID 모양"인지만 본다. 숫자, 이름만, 볼륨 ID는 `400 InvalidRequestContent`다.
- `snapshotId: null`은 스펙의 `x-nullable`대로 없는 것으로 본다(`_check_properties`, `:185`, 설계 §9-5).
- `originatingResourceId`는 읽기 전용 목록(`:52`)에 있어 요청에 있어도 무시한다(`mountTargets`처럼, 결정 12).
- `deleteBaseSnapshot`은 `_FIXED`(`:55-56`)에 `False`로 있다. 불리언이 아니면 `400 InvalidRequestContent`, `true`면 공통 `unsupported_property`(`400`)다 (결정 7).

#### (2) anf-api: 복원 검사 — `_new_volume`, `volumes.py:301-353`, `_restore_source`, `:356-384`

- 일반 볼륨 생성 검사 순서(풀 존재 → 풀 `Deleting` → 풀 상태 → Manual QoS → 필수 속성) 뒤에 `snapshotId`가 있으면 `_restore_source`를 부른다(`:328-332`). 그 뒤 서비스 수준 → 경로 중복 → 풀 용량은 일반 볼륨 그대로다(`:335-348`). 그래서 새 볼륨의 `usageThreshold`도 풀 할당량에 전부 더해진다.
- `_restore_source`의 순서(결정 13):
  1. **같은 계정인가** (`:360-363`): 새 볼륨 ID의 `/capacityPools/` 앞부분(구독·리소스 그룹·계정)으로 스냅샷 ID가 시작하는지 본다. 아니면 `400 BadRequest`. 같은 계정의 다른 풀은 받는다 (결정 2).
  2. **스냅샷이 있는가** (`:364-367`): 없으면 스냅샷 GET과 같은 `404 ResourceNotFound`(녹화 R1 문구).
  3. **스냅샷이나 원본 볼륨에 진행 중 작업이 있는가** (`:369-373`): `409 Conflict`.
  4. **스냅샷이 `Succeeded`인가, 원본 볼륨이 `Succeeded`인가** (`:374-379`): 아니면 `400 BadRequest`.
  5. **크기 하한** (`:380-383`): 요청 `usageThreshold`가 원본 볼륨의 `usageThreshold`보다 작으면 `400 BadRequest` (결정 4).
- 통과하면 저장하는 `snapshotId`는 **요청 문자열이 아니라 저장된 스냅샷 행의 ID**다(`:331`). ARM ID는 대소문자를 구분하지 않으므로, 요청 대소문자가 달라도 응답과 `originatingResourceId`에는 정규 ID가 나온다(설계 §9-5).
- 주지 않은 `protocolTypes`·`unixPermissions`는 원본 볼륨 값이다(`:331-332`). 요청에 있으면 다음 줄(`:333`)이 덮어쓴다 (결정 3). export 규칙은 그 프로토콜로 만든다(`:334`).

#### (3) anf-api: 라우트 — `arm_app.put_volume`, `arm_app.py:245-259`

- 생성 `201`이고 볼륨에 `snapshotId`가 있을 때만 `_tracking_headers`(`arm_app.py:93-96`)로 `Azure-AsyncOperation`과 `Location`을 둘 다 붙인다(`:255-256`). 일반 생성과 모든 갱신 `200`은 `Azure-AsyncOperation` 하나다(`:257-258`).
- 이유(설계 §9-1): 두 녹화가 다르다. 일반 생성 녹화(V1)는 한 헤더, 스냅샷에서 생성 녹화(R4)는 두 헤더다. 일반 생성까지 바꾸면 이미 검증한 볼륨 계약이 바뀐다.

#### (4) anf-api: 처리기 — `make_handlers`, `volumes.py:546-619`

- **`clone_source`** (`:554-560`): 볼륨에 `snapshotId`가 있고 `originatingResourceId`가 **없을 때만** (원본 볼륨 `fileSystemId`, 원본 스냅샷 `snapshotId`)를 돌려준다. 한 번 끝난 볼륨의 재PUT은 일반 볼륨 보장이다(설계 §9-6). 이 함수는 원본 행이 있다고 가정한다. 그 가정을 지키는 것이 원본 보호(6번)다.
- **`ensure`** (`:562-600`): CREATE·UPDATE·PATCH 공통이다. `storage.ensure_volume(…, clone=clone)`으로 agent를 부르고(`:566-568`) `mountTargets`를 쓴다(`:569-574`). 되돌리기 기능의 "agent에 없는 스냅샷 행 지우기"(`:577-585`)가 그다음이다.
- **끝난 뒤 base 스냅샷 행과 `originatingResourceId`** (`:586-600`): `clone`이 있었으면 agent의 스냅샷 목록(`snapshot_records`)을 읽어 스냅샷마다 `Succeeded` 행을 `put_resource`(upsert)로 쓰고, 같은 트랜잭션에서 `originatingResourceId = snapshotId`를 쓴다. 행 ID는 `<새 볼륨 ID>/snapshots/<이름>`, `snapshotId`는 agent가 정한 base uuid, `created`는 agent의 `create_time`, `tags`는 비어 있다. upsert라서 워커가 이 트랜잭션 뒤 끝내기 전에 죽어 같은 작업이 다시 실행돼도 행이 겹치지 않는다(설계 §9-6). base 행은 `Creating`을 거치지 않는다(설계 §5).
- 결함 주입 키는 기존 `volumes/create`다. 복원도 볼륨 CREATE라 같은 처리기를 탄다 (결정 15).

#### (5) anf-api: `storage_client.py:52-67`, `:96-106`

- `ensure_volume`에 `clone` 인자를 더했다. 있으면 본문에 `{"is_flexclone": true, "parent_volume": {"uuid"}, "parent_snapshot": {"uuid"}}`를 넣는다(`:59-61`). 나머지(job 폴링, 60초 연결 재시도, job이 사라지면 다시 보내기)는 그대로다.
- `snapshot_records`(`:100-106`)를 새로 만들고, 되돌리기의 `snapshot_uuids`(`:96-98`)는 그 위에서 uuid만 고르게 바꿨다(설계 §9-7).

#### (6) anf-api: 원본 보호 — `snapshots.ensure_not_cloning`, `snapshots.py:103-114`

- 모든 볼륨 중 `snapshotId`가 있고 `originatingResourceId`가 없는 것(아직 한 번도 `Succeeded`가 되지 않은 새 볼륨)을 찾는다. 대상 ID가 그 원본 스냅샷이거나(`==`), 원본 볼륨이면(`<볼륨 ID>/snapshots/`로 시작) `409 Conflict`다(`:111-114`).
- 부르는 곳은 셋이다(설계 §9-8): 스냅샷 DELETE(`snapshots.py:199`), 볼륨 DELETE(`volumes.py:493`), 볼륨 revert(`volumes.py:520`). 원본 볼륨의 **다른** 스냅샷 DELETE, 원본 스냅샷 재PUT, 원본 볼륨 PATCH는 막지 않는다. 새 볼륨 생성을 깨지 않기 때문이다.
- 풀리는 때는 둘이다. 새 볼륨이 처음 `Succeeded`가 돼 처리기가 `originatingResourceId`를 쓸 때, 그리고 끝나지 않은 새 볼륨을 지워 그 행이 사라질 때다(계약 테스트 `test_deleting_an_unfinished_new_volume_releases_the_source`).

#### (7) anf-api: `snapshotId`는 바꿀 수 없다 — `_apply_update`, `volumes.py:387-404`

- `_IMMUTABLE`(`:66-71`)에 `"SnapshotId cannot be changed."`가 있다. `same`(`:389-393`)은 ARM ID를 대소문자 무시로 비교하고(`_ARM_IDS`, `:72`), **원래 값이 없으면 같지 않다**고 본다. 그래서 끝난 새 볼륨의 재PUT·PATCH에 다른 `snapshotId`, 일반 볼륨에 `snapshotId`를 더하는 것 모두 `400 BadRequest`다 (결정 12). 같은 값은 받는다.

#### (8) agent: ONTAP FlexClone 모양 API — `agent_app.py:45-82`, `:154-158`

- `parse_volume`(`:59-82`)은 기존 네 필드에 `clone`을 선택으로 받는다(`:61`, `:81`). `_parse_clone`(`:45-56`)은 정확히 세 필드, `is_flexclone`은 `True`(문자열 `"true"`도 거절), 두 부모는 정확히 `{"uuid"}`이고 소문자 UUID여야 한다. 그 밖은 `400`이다 (결정 14, R-07의 입력 다시 검사).
- ONTAP과 다른 점: 새 볼륨 `uuid`를 요청에 넣는 것은 볼륨 기능 때부터의 클론 확장이다. `parent_*.name`, `parent_svm`, `split_*`는 없다. 만든 볼륨은 처음부터 split된 볼륨처럼 독립이다.

#### (9) agent: 새 볼륨 LV — `_ensure_lv`, `flexvol.py:449-497`

- **이미 그 uuid의 볼륨이 있으면** (`:452-461`): 진행 표시가 있으면 크기 비교를 "LV 크기 ≤ 요청 크기"로 느슨하게 한다(`:455`). 아직 늘리기 전에 멈췄을 수 있기 때문이다. 진행 표시가 없으면 일반 볼륨처럼 크기가 같아야 하고 `clone`은 무시된다.
- **없으면 원본 확인** (`:462-473`): 부모 볼륨이 있는가, 스냅샷이 있는가, 그 볼륨의 스냅샷인가, 요청 크기 ≥ 스냅샷 LV 크기인가. 하나라도 아니면 `VolumeError`이고 job은 `failure`다. anf-api가 이미 크기를 막지만 agent도 실제 LV 크기와 다시 비교한다 (결정 4).
- 그다음은 일반 볼륨과 같다: 경로 중복(`:474-476`), 씬 풀 여유(`:477-479`, 새 볼륨도 **요청 크기 전체**로 센다), IP 고르기(`:480-483`, 원본과 다른 IP를 받는다).
- **LV 만들기** (`:484-491`): `lvcreate -s -kn -p rw -n vol_<N> <볼륨 태그 + anf_cl_snap/name/time> anf/snap_<S>`. 원본 스냅샷 LV의 쓰기 가능 thin 스냅샷이고, 되돌리기의 새 볼륨 LV와 같은 명령이다(S5 L2). 태그를 **같은 명령에서** 붙이므로 "LV는 있는데 볼륨 태그가 없는" 순간이 없다. LV는 스냅샷 크기로 생긴다(`_Volume(…, source.size, …)`). thin 스냅샷은 만들 때 크기를 줄 수 없기 때문이다(S6 Z1).

#### (10) agent: 남은 단계 — `create` `flexvol.py:185-210`, `_finish_clone` `:212-234`

`create`는 `_ensure_lv`가 돌려준 볼륨에 진행 표시가 있으면 `_finish_clone`으로 가고 끝난다(`:191-194`). mkfs와 `lost+found` 초기화는 없다. 파일시스템은 원본 스냅샷의 것이고 저널 재생 없이 rw로 마운트된다(S6 C3·C4).

| 단계 | 줄 | 하는 일 | 다시 실행할 때 |
| --- | --- | --- | --- |
| 크기 | `:216-217` | LV가 요청보다 작으면 `lvextend -L <size>b` | 이미 크면 건너뜀 |
| 마운트 | `:218` | `nodelalloc`로 마운트 (`_ensure_mounted`) | 마운트돼 있으면 건너뜀 |
| 파일시스템 크기 | `:220` | 늘 `resize2fs <장치>` (온라인) | ext4가 이미 LV 크기면 아무것도 안 하고 rc 0 (설계 §9-3) |
| `.snapshot` 정리 | `:221-223` | `.snapshot` 보장(+i) 뒤, 이 볼륨에 없는 이름의 빈 디렉터리를 `chattr -i` → `rmdir` → `chattr +i`로 지움 (`_remove_stray_snapshot_dirs`, `:430-435`) | 이미 base가 있으면 그 이름은 남김 |
| base 스냅샷 | `:224-229` | 이름이 `anf_cl_name`인 스냅샷이 없으면 `_snapshot_lv`(`:419-428`)로 읽기 전용 thin 스냅샷. uuid는 `new_uuid()`(`:136`), 시각은 `anf_cl_time`. 그 뒤 `.snapshot/<이름>`에 `ro,noload` | 있으면 만들지 않음 (base는 하나) |
| 루트 권한 | `:231` | `chmod <unix_permissions>` | 같은 값을 다시 씀 |
| export·인스턴스 | `:232-233` | 볼륨 줄 + base 줄을 export 파일에 쓰고 인스턴스 보장 | 일반 볼륨과 같음 |
| 진행 표시 지우기 | `:234` | `lvchange --deltag anf_cl_snap … anf_cl_name … anf_cl_time …` 한 명령 | 이 단계가 끝나야 "다 만든 볼륨"이 됨 |

#### (11) agent: 진행 표시가 있는 동안 — `flexvol.py:156-181`, `:412-417`

- `_report`(`:515-517`)가 `anf_cl_snap` 태그를 보고 `_Volume.clone`(`_Clone`, `:56-66`)을 채운다. agent에는 DB가 없고 이 태그가 유일한 진행 기록이다.
- **시작 복구는 건너뛴다** (`recover`, `:170`): mkfs 전 볼륨을 건너뛰는 것과 같은 줄이다. 그 볼륨은 `offline` 레코드로 남고 다음 볼륨 POST가 끝낸다 (결정 10).
- **스냅샷 생성·삭제와 되돌리기를 거절한다** (`_refuse_during_clone`, `:412-417`, 부르는 곳 `:279`, `:305`, `:327`). 문구는 셋이 같다: "volume X is still being created from snapshot Y; POST the volume again to finish it". 되돌리기 거절은 구현 중 더했다(설계 §9-2): 되돌리기가 만드는 새 LV는 볼륨 태그만 갖고 진행 표시가 없어서, 남은 클론 단계(base 스냅샷, 권한, 진행 표시 지우기)를 잃는다. anf-api도 끝나지 않은 새 볼륨의 revert를 이미 막지만(`Creating`은 진행 중 작업, `Failed`는 상태) agent가 스스로도 지킨다.

### 핵심 설명 (면접에서 나올 것)

#### 3.1 dm-thin 블록 공유와 ANF의 "복사 뒤 공간 2배"

- **ANF.** 문서는 "data copy process" 때문에 복원이 끝나면 풀 사용량이 두 배가 되고 새 볼륨이 원본 스냅샷의 활성 용량 전체를 보인다고 쓴다 [문서]. 할당인지 사용량인지는 [미확인]이다.
- **클론.** 새 볼륨은 원본 스냅샷과 블록을 공유하고, 쓴 만큼만 씬 풀에서 나간다. S6(씬 풀 chunk 64 KiB인 스파이크 전용 풀)에서 원본 데이터 약 150 MB로 새 볼륨을 만든 직후, 새 볼륨은 mapped 152,961,024 B 중 exclusive 65,536 B(rw 마운트가 쓴 슈퍼블록 chunk로 본다 [추론])였고 풀 사용량은 1.80% 그대로였다. 50 MiB를 쓴 뒤 exclusive 73,269,248 B가 됐다 [클론 측정 S6 R].
- **할당은 같고 사용량이 다르다.** anf-api는 새 볼륨의 `usageThreshold` 전체를 풀 할당량에 더하고(`volumes.py:346-348`), agent도 씬 풀 여유를 볼륨 크기 전체로 센다(`flexvol.py:477`). 그래서 "풀 할당" 규칙은 일반 볼륨과 같다. 다른 것은 실제 블록 사용량이다.
- **대가.** (a) 씬 풀이 차는 위험(ADR R-09)을 원본과 함께 진다. (b) 원본을 지워도 공유 블록은 남은 볼륨이 쓰므로 풀 사용량이 줄지 않는다(S6 R: 원본 볼륨과 그 스냅샷을 모두 지운 뒤에도 풀은 2.77~2.80%였다. 원본을 되돌리기 전에는 2.70%였고, 그동안 클라이언트 쓰기가 계속됐다). (c) ext4가 discard 없이 마운트돼 새 볼륨에서 지운 블록은 `fstrim` 전까지 풀로 돌아오지 않는다(S6 Z4). (c)는 일반 볼륨과 같은 성질이라 이번에 다루지 않았다.
- **버린 대안.** `cp -a`·`rsync`·블록 복사는 시간이 데이터에 비례하고 dm-thin의 이점을 버린다. ANF의 "2배"를 흉내 낼 이유가 없다 (결정 5).

#### 3.2 원본 보호 창의 차이 (`cloneProgress`)

- **ANF**: `Succeeded` 뒤 백그라운드 복사(`cloneProgress`)가 끝날 때까지 원본 볼륨·스냅샷을 지울 수 없다 [문서]. 녹화에서는 약 5분 45초였다 [녹화].
- **클론**: 기다릴 복사가 없다. dm-thin thin 스냅샷은 원본 LV를 지워도 남는다. 새 볼륨 N을 클라이언트가 쓰는 동안 원본 스냅샷 `lvremove`, 원본 되돌리기(교체 방식), 원본과 스냅샷 전부 삭제를 해도 LVM은 거절하지 않았고 N의 마운트·쓰기·열린 fd가 오류 없이 이어졌다 [클론 측정 S6 I3~I6]. 그래서 `cloneProgress`는 응답에 없다.
- **그래도 생성 작업 동안은 지킨다** (결정 9). 위험한 것은 agent가 새 LV를 만들기 **전**의 창이다.
  - agent job은 한 번에 하나씩 돈다. 클론 job이 기다리는 사이 원본 스냅샷이 지워지면 생성이 실패하고, 같은 PUT으로도 회복할 수 없다.
  - anf-api 처리기(`clone_source`)도 원본 행을 읽어 클론 필드를 만든다.
  - LV를 만든 **뒤**에는 진행 표시가 base의 이름·시각을 갖고 있어 agent는 원본 없이도 끝낼 수 있다(결정 10). 그래서 보호는 "새 볼륨이 처음 `Succeeded`가 될 때까지"면 충분하다.
- **되돌리기도 막는 이유**: 원본 볼륨을 더 오래된 스냅샷으로 되돌리면 더 새 스냅샷이 지워지는데, 그중에 원본 스냅샷이 있을 수 있다.
- **버린 대안**: ANF처럼 몇 분 보호(클론에는 기다릴 복사가 없다), 보호 없음(생성 중 원본 스냅샷을 지우면 새 볼륨이 회복할 수 없는 `Failed`로 남는다).

#### 3.3 base 스냅샷이 공유 스냅샷이 아니라 별도 thin 스냅샷인 이유

- ONTAP FlexClone의 base 스냅샷은 부모와 **공유**한다 [문서]. ANF 녹화의 base는 원본과 `snapshotId`가 다르다 [녹화]. ANF 내부에서 공유인지 별도인지는 브리프로 알 수 없다.
- 클론의 스냅샷 LV는 태그 `anf_snap_vol`로 **볼륨 하나에 속한다.** dm-thin에는 두 볼륨이 함께 갖는 스냅샷이 없다. 새 볼륨의 `.snapshot/S`가 원본의 `snap_<S>`를 가리키게 하면, 생성이 끝난 뒤(보호가 풀린 뒤) 원본 스냅샷을 지울 때 새 볼륨 쪽도 사라진다.
- 그래서 새 볼륨 LV의 읽기 전용 thin 스냅샷을 새로 찍는다. 이름 = 원본 스냅샷 이름, 시각 = 원본의 `anf_snap_time`(초 단위라 ANF의 `created` 모양과 같다), uuid = agent가 새로 정함 (결정 7). 이것도 블록을 공유하므로 만들 때 공간이 거의 들지 않는다(S6 R 마지막 행: 볼륨 3개 + base 2개, 각 약 150 MB인데 풀 약 151 MiB). 이름이 같은 두 `S`는 `_report`가 `anf_snap_vol`로 갈라 본다(S6 B1).
- base의 dm-thin id는 뒤에 찍는 스냅샷보다 작아서, 되돌리기의 "더 새 스냅샷 = id가 더 큰 것" 판단이 그대로 맞는다(S6 B1~B3).
- uuid를 agent가 정하고 anf-api가 생성 뒤 스냅샷 목록에서 읽는 이유: anf-api가 정해 넘기면 ONTAP에 없는 필드가 하나 더 생긴다. ONTAP 클라이언트도 클론 뒤 스냅샷 목록으로 찾는다 [추론, 브리프의 "job 뒤 `GET ?name=`으로 찾는다"와 같은 구조].

#### 3.4 크기를 늘린 뒤 base를 찍는 이유 (S6 B2)

- thin 스냅샷은 원본 크기로만 생긴다. `lvcreate -s … -L 2G`는 옛 COW 스냅샷으로 해석돼 실패하고, `-V 2G`는 "Command does not accept option" [클론 측정 S6 Z1]. 그래서 원본보다 큰 새 볼륨은 "만든 뒤 `lvextend` + 온라인 `resize2fs`"다(S6 Z2: 0.176 s + 0.043 s).
- **S6 B2의 관찰**: 1 GiB 때 base를 찍고 새 볼륨을 2 GiB로 키운 뒤 base로 되돌렸더니, 되돌린 볼륨의 LV와 ext4가 **1 GiB로 돌아갔다.** 되돌리기(FR-06)의 교체 방식은 볼륨 LV를 "고른 스냅샷의 쓰기 가능 스냅샷"으로 바꾸고, 그 스냅샷은 찍던 때의 크기를 갖기 때문이다.
- 그래서 `_finish_clone`은 `lvextend` → 마운트 → `resize2fs`를 끝낸 **뒤에** base를 찍는다(`flexvol.py:216-229`, 주석 `:226`). 검증 AC-05에서 2 GiB 새 볼륨을 base로 되돌린 뒤에도 `df` 크기 2,077,229,056 B, agent `size` 2147483648이 그대로였다.
- 같은 이유로 base는 루트 권한 `chmod` **전에** 찍는다(`:227` → `:231`). 그래야 base 내용이 원본 스냅샷과 같다 (결정 7·11).
- 일반화: 볼륨 크기 변경(FR-16)이 생기면 되돌리기 일반이 크기를 스냅샷 시점으로 돌린다. 이것은 FR-06 코드의 성질이다(S6 "설계에 주는 선택지").

#### 3.5 ext4 UUID가 같아도 NFS가 볼륨을 구분하는 이유

- 새 볼륨 LV는 원본 스냅샷의 블록 그대로라 **ext4 UUID가 원본 볼륨과 같다.** 원본은 `mkfs.ext4 -U <원본 fileSystemId>`로 만들었으므로(`flexvol.py:199`), 새 볼륨의 ext4 UUID = 원본의 `fileSystemId`다. 검증 AC-02에서도 그랬다.
- **NFS는 ext4 UUID를 보지 않는다.** 각 볼륨 인스턴스의 export 파일은 볼륨 줄에 `fsid=<그 볼륨의 fileSystemId>`, 스냅샷 줄에 `fsid=<스냅샷 uuid>`를 명시한다(`nfs_instance.py:139-140`, `write_exports`). NFS 파일 핸들에 들어가는 파일시스템 식별자가 볼륨마다 다르므로 핸들이 겹치지 않는다. 한 클라이언트가 원본(v3)과 새 볼륨(v4.1)을 함께 마운트했을 때 `stat` 장치 번호가 109와 117로 달랐고 쓴 데이터가 섞이지 않았다. ext4 UUID가 같은 v4.1 볼륨 둘을 한 클라이언트가 마운트해도 같았다 [클론 측정 S6 Ua4·Ua5]. 거기에 볼륨마다 knfsd 인스턴스와 IP가 따로다(D-12).
- 스냅샷 기능 때 같은 문제를 이미 만났다: 부모 `crossmnt`만 두면 thin 스냅샷의 ext4 UUID가 원본과 같아 Stale file handle이 났고, 스냅샷마다 `fsid`를 명시해서 풀었다 [스냅샷 문서, S4 E1·E2. 원인 해석은 추론].
- **영향은 호스트에서만 보인다.** `/dev/disk/by-uuid`, `blkid -U`, `findfs`가 같은 UUID 장치 여럿 중 하나만 가리킨다(S6 Ua2). agent는 장치를 `/dev/anf/<lv>`로만 부르므로(`_Volume.device`, `flexvol.py:81-83`) 영향이 없다. 운영자가 UUID로 마운트하는 도구를 쓰면 구분할 수 없다(검증 기준 밖 관찰 1).
- **버린 대안** (결정 6):
  - `e2fsck -f` + `tune2fs -U`: `tune2fs -U`는 다시 마운트된 적 있는 볼륨에 "freshly checked filesystem"을 요구한다(S6 Ub2). `e2fsck -f`는 rc 1로 `lost+found`를 만든다(Ub3). `create()`는 `lost+found`가 있으면 "mkfs 직후"로 보고 루트 권한을 초기화하므로(`flexvol.py:203-207`) 엉뚱한 판정을 일으킨다. 메타데이터 체크섬을 모두 다시 써서 그만큼 풀을 쓴다(4 GiB·2만 파일에서 7.1 MB).
  - `tune2fs -O metadata_csum_seed -U`: 검사 없이 0.02~0.03 s에 되지만(Ub4), 새 볼륨만 ext4 기능이 달라진다.
  - 스냅샷은 S1 이후 이미 같은 UUID로 돌고 있었다.

#### 3.6 진행 표시 태그로 재시작에 안전하게 만든 방식

- **원칙**: agent에는 DB가 없다. LVM 태그가 진행 기록이고, 모든 단계는 실제 상태를 먼저 본다. 그래서 "같은 요청을 다시 보내면 남은 단계부터 끝난다".
- **시작과 끝이 각각 한 명령이다.** 진행 표시 `anf_cl_snap`(원본 스냅샷 uuid), `anf_cl_name`, `anf_cl_time`은 LV를 만드는 `lvcreate`에서 붙고(`flexvol.py:489-490`), 끝은 `lvchange --deltag` 한 번이다(`:234`). 중간에 멈춘 볼륨은 늘 "진행 표시가 있는 볼륨"으로 보인다.
- **이름·시각을 복사해 두는 이유**: base 스냅샷을 원본 스냅샷 없이도 찍을 수 있게. 원본 스냅샷 LV는 새 LV를 만들 때만 필요하다.
- **누가 끝내나**: 같은 uuid의 볼륨 POST다. anf-api는 재시작 때 끝나지 않은 작업을 다시 실행하고, 실패한 볼륨은 같은 PUT(`UPDATE`)이 다시 보장한다. 처리기는 `originatingResourceId`가 없는 동안 같은 클론 필드를 보낸다. agent `_ensure_lv`가 진행 표시를 보고 `_finish_clone`으로 보낸다.
- **시작 복구는 끝내지 않는다** (결정 10의 버린 대안): 요청 크기와 루트 권한이 태그에 없어서다. 태그를 더 늘리는 대신, 어차피 오는 다음 POST에 맡겼다.
- **진행 표시가 있는 동안 막는 것**: agent의 스냅샷 생성·삭제와 되돌리기(3절 (11)). 스냅샷을 먼저 만들면 base 이름을 빼앗을 수 있고, 되돌리기는 진행 표시를 잃는다.
- **anf-api 쪽 짝**: base 스냅샷 행과 `originatingResourceId`를 한 트랜잭션에서 upsert한다(`volumes.py:586-600`). 다시 실행해도 행이 겹치지 않는다.
- **검증**: 통합 테스트가 다섯 지점(새 LV만 만든 뒤, 늘린 뒤 마운트 전(이때는 시작 복구도 거침), 마운트 뒤 `resize2fs` 전, base 뒤, 인스턴스 뒤 진행 표시 지우기 전)에서 멈춘 뒤 같은 POST로 끝내고, base가 하나이며 진행 표시가 사라짐을 단언한다(`test_flexvol_linux.py:565-596`, `test_volume_from_snapshot_resumes_after_stopping_midway`). e2e에서는 새 LV가 마운트된 순간 agent를 SIGKILL했다(5절 AC-09).

### 설계 결정

모두 **자동 채택**이다(머리말 참고). "버린 대안"은 설계 기록(`02_main_design.md` §3)의 것이다.

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | ARM 계약은 일반 볼륨 PUT 그대로. `snapshotId`(스냅샷 ARM ID, 생성 때만), `201`, `Creating` → `Succeeded`(`CREATE`), 끝나면 `originatingResourceId` | 복원 전용 액션(`POST .../restore`) | ANF에 없다 [스펙] |
| 2 | 원본 스냅샷은 같은 NetApp 계정이면 어느 풀이든. 다른 계정·리소스 그룹·구독은 `400`. 서비스 수준·처리량은 새 볼륨 자기 풀을 따름 | 같은 풀만 / 제한 없음 | 같은 풀만: 근거가 Elastic 절의 주석뿐이고 다른 풀 복원 데모를 막는다. 클론은 모든 풀이 한 씬 풀을 써서 데이터 플레인 제약이 없다. 제한 없음: ANF가 계정을 권한 경계로 쓰는 것과 맞지 않는다 [추론]. ANF 규칙은 [미확인] |
| 3 | `protocolTypes`·`unixPermissions`를 주지 않으면 원본 볼륨 값. 다른 NFS 버전(v3 ↔ v4.1)도 받음 | 늘 기본값(NFSv3, `0770`) / 다른 버전 거절 | 포털 문서가 "same protocol"이라, 늘 기본값을 쓰면 원본이 v4.1일 때 버전이 바뀐다. 원본 v3·새 볼륨 v4.1도 데이터 플레인에서 된다(S6 F2). 스펙은 PATCH로 NFS 버전 변경을 허용한다. ANF API 검사는 [미확인] |
| 4 | `usageThreshold` ≥ 원본 볼륨 `usageThreshold`. 작으면 `400`. 크면 `lvextend` + 온라인 `resize2fs`. agent도 스냅샷 LV 크기와 다시 비교 | 작은 크기 허용 / 사용량 기준 하한 | ext4 축소는 오프라인뿐이고 최소 크기 검사가 있으며 `lost+found`를 만든다(S6 Z6). 사용량은 시간에 따라 바뀌어 검사 시점과 데이터 플레인 시점이 어긋난다. 크기 변경(FR-16)이 없으니 스냅샷 크기 = 원본의 지금 `usageThreshold`다 |
| 5 | 데이터 플레인 = 원본 스냅샷 LV의 쓰기 가능 thin 스냅샷 (`lvcreate -s -kn -p rw`) | 데이터 복사 | 3.1절 |
| 6 | ext4 UUID는 원본 그대로 | `e2fsck -f` + `tune2fs -U` / `metadata_csum_seed` | 3.5절 |
| 7 | base 스냅샷 = 새 볼륨의 읽기 전용 thin 스냅샷, 크기를 늘린 뒤·권한 적용 전. `deleteBaseSnapshot`은 `false`만 | base 없음 / 부모와 공유 / anf-api가 base uuid를 정함 / `true` 지원 | base 없음은 녹화와 다르다. 공유는 3.3절. `true`는 스펙과 문서가 지울 대상을 다르게 읽히고 녹화가 없다 |
| 8 | `.snapshot`에 남은 원본의 마운트 지점을 base 전에 지움 | 그대로 둠 | 새 볼륨의 `.snapshot`은 원본 스냅샷을 찍던 때의 것이라 그때 있던 다른 스냅샷 이름의 빈 디렉터리가 있고 `+i`를 물려받는다(S6 D4). 두면 새 볼륨에 없는 스냅샷 이름이 보이고 base에도 남는다. 지우는 방법은 되돌리기와 같다(S6 D5) |
| 9 | 생성이 끝나면 바로 독립. 그 전까지만 원본 스냅샷 DELETE, 원본 볼륨 DELETE·revert `409` | ANF처럼 몇 분 보호 / 보호 없음 | 3.2절 |
| 10 | 재시작 안전은 LVM 태그 진행 표시. 시작 복구는 건너뛰고 다음 POST가 끝냄 | 시작 복구에서 끝냄 | 3.6절 |
| 11 | 새 볼륨 루트 권한은 base 뒤에 `unixPermissions`로 맞춤 | 적용하지 않음 | 루트 inode는 원본 스냅샷에서 온다(S6 D3). 원본 클라이언트가 루트 모드를 바꿨으면 응답과 실제가 다르다. 일반 볼륨이 만들 때 한 번 적용하는 것과 같은 뜻이다 |
| 12 | 재PUT·PATCH의 `snapshotId`는 불변. 같은 값(대소문자 무시)만 받음, 다르거나 원래 없던 볼륨에 넣으면 `400 "SnapshotId cannot be changed."` | 무시 | 무시하면 사용자가 바뀌었다고 오해한다. 문구는 기존 불변 속성과 같은 모양으로 지었다. ANF 실동작은 [미확인] |
| 13 | 거절 규칙과 순서(클론 규칙). 계정 → 스냅샷 존재 → 진행 중 작업 → 스냅샷 상태 → 원본 상태 → 크기 | 작업 `Failed`로 늦게 실패 | 사용자가 폴링해야 오류를 안다. 동기 거절이면 볼륨 행도 작업도 생기지 않는다(AC-07). ANF 응답은 [미확인] |
| 14 | agent API = ONTAP FlexClone 모양(`clone.is_flexclone`, `parent_volume.uuid`, `parent_snapshot.uuid`) | 새 경로(`POST .../volumes/{uuid}/restore`) / `parent_snapshot.name`도 받기 | 새 경로는 ONTAP과 다르다. anf-api는 uuid만 쓴다. split이 필요 없어 `split_*`는 없다 |
| 15 | 결함 주입 키는 기존 `volumes/create` | `volumes/restore` 키 | 공통 계층에 특례가 생긴다 |
| 16 | ANF와 다른 점을 개념 문서에 남김 | — | 4절 |

### 구현 중 변경 (설계 §9)

| # | 무엇 | 왜 |
| --- | --- | --- |
| 1 | 두 헤더는 스냅샷에서 만드는 생성 `201`에만 | 녹화 V1(일반 생성, 한 헤더)과 R4(스냅샷에서, 두 헤더)가 다르다. 일반 생성까지 바꾸면 확정된 볼륨 계약이 바뀐다. 메인 세션이 받아들였다 |
| 2 | agent 되돌리기도 진행 표시가 있으면 거절 | 3절 (11) |
| 3 | 파일시스템 크기 단계는 비교 없이 늘 `resize2fs` | 같은 크기면 rc 0으로 아무것도 안 한다. ext4 크기를 읽으려면 `dumpe2fs` 파싱이 필요하다. 늘린 뒤 `resize2fs` 전에 멈춘 경우도 한 줄이 덮는다 |
| 4 | base uuid는 `FlexVolManager.new_uuid`(기본 `uuid4`) | 단위 테스트가 값을 고정하려고 |
| 5 | 저장하는 `snapshotId`는 저장된 스냅샷 행의 ID, `null`은 없는 것 | ARM ID는 대소문자를 구분하지 않는다. 되돌리기 작업 입력과 같은 방식 |
| 6 | base 행과 `originatingResourceId`는 한 트랜잭션, upsert. `clone`은 `originatingResourceId`가 없는 동안만 | 다시 실행해도 겹치지 않고, 끝난 볼륨의 재PUT은 일반 보장이 된다 |
| 7 | `StorageClient.snapshot_records()` 추가 | `snapshot_uuids()`는 그 위에서 uuid만 고른다 |
| 8 | `ensure_not_cloning` 한 함수를 세 곳이 부름 | 원본 볼륨의 다른 스냅샷 DELETE, 원본 스냅샷 재PUT, 원본 볼륨 PATCH는 막지 않는다 |
| 9 | 단위 테스트의 가짜 호스트가 `chattr +i`를 파일시스템마다 기억 | 스냅샷에서 만든 LV가 `+i`를 물려받는 것(S6 D4)을 단위 층에서 재현하려고. 제품 코드 영향 없음 |
| 10 | 테스트 파일: 계약 `tests/contract/test_restore_new_volume_api.py`, 통합 `test_flexvol_linux.py`에 내용·독립성·크기·다섯 지점 | 다른 계약 테스트의 가짜 agent는 `clone=None` 키워드만 더했다 |

---

## 4. 실제 ANF와 다른 점

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 데이터를 만드는 방식 | FlexClone + split으로 보인다 [추론]. 문서는 "data copy process" [문서] | 원본 스냅샷 LV의 쓰기 가능 thin 스냅샷. split 없이 처음부터 독립 | dm-thin thin 장치는 서로 독립이고 블록만 공유한다(S6 I) |
| 백그라운드 복사, `cloneProgress` | `Succeeded` 뒤 복사, `0` → null(녹화 약 5분 45초) [녹화][스펙] | 없다. 응답에 `cloneProgress`가 없다 | 기다릴 복사가 없다 (결정 9) |
| 원본 보호 창 | 복사가 끝날 때까지 원본 볼륨·스냅샷 삭제 불가 [문서], 코드 [미확인] | 새 볼륨이 처음 `Succeeded`가 될 때까지만 원본 스냅샷 DELETE, 원본 볼륨 DELETE·revert `409 Conflict` | 3.2절 |
| 공간 | 복원이 끝나면 풀 사용량 2배 [문서](할당인지 사용량인지 [미확인]) | 할당은 `usageThreshold` 전체로 같다. 사용량은 블록 공유라 쓴 만큼만. 대신 씬 풀 위험(R-09)을 원본과 함께 지고, 원본을 지워도 공유 블록은 남는다 | 3.1절 |
| base 스냅샷 | 이름 같음, 새 `snapshotId`, `created` 원본(초) [녹화]. ONTAP FlexClone은 부모와 공유 [문서] | 새 볼륨의 별도 읽기 전용 thin 스냅샷. 생성 작업 안에서 생긴다 | 3.3절 |
| base의 `systemData` | 생성 약 4분 뒤 `Application`이 바꿈 [녹화] | base 행은 생성 작업이 끝날 때 바로 `Succeeded`로 생긴다 | 복사 단계가 없다 |
| `deleteBaseSnapshot` | 지원(지울 대상이 출처마다 다르게 읽힘) [스펙][문서] | `false`만. `true`는 `400` | 결정 7 |
| ext4 UUID | 해당 없음 | 원본과 같다. NFS에는 보이지 않고 호스트의 `by-uuid`만 하나를 가리킨다 | 3.5절 |
| 허용 범위 | [미확인] (녹화는 같은 풀만) | 같은 계정의 어느 풀이든. 다른 계정은 `400 BadRequest` | 결정 2 |
| 크기 | [미확인] | 원본 `usageThreshold` 이상, 작으면 `400`, 크면 늘림 | 결정 4 |
| 프로토콜·권한 | 포털 "same protocol" [문서], API [미확인]. `unixPermissions` 기본값은 브리프에 없다 | 기본은 원본 값, 다른 NFS 버전 허용 | 결정 3 |
| 거절 코드·문구 | [미확인] | 설계 §4.2의 클론 규칙(`400 InvalidRequestContent`·`BadRequest`, `404 ResourceNotFound`, `409 Conflict`) | 결정 13 |
| 재PUT의 `snapshotId` 변경 | [미확인] | `400 "SnapshotId cannot be changed."` | 결정 12 |
| 실패 회복 | "Failed to split…": 볼륨을 지우고 다시 만든다 [문서] | 같은 PUT(`UPDATE`)이 agent에서 남은 단계를 이어서 끝낸다 | 결정 10 |
| 걸린 시간 | 약 11초 [녹화] | ARM 작업 약 2.2 s(지연 주입 5 s를 뺀 값, AC-01 1회), agent job 2 s(AC-10 1회) | 로컬 thin 스냅샷 0.12~0.21 s(S6 C1) + 인스턴스 준비 0.57~0.65 s(S6 F1) |
| 새 볼륨 스냅샷 | 완전히 복원된 뒤에 켜라는 권고 [문서]. ONTAP은 split 중 불가 [문서] | `Succeeded`가 되면 바로 된다. 그 전에는 기존 규칙과 진행 표시로 거절 | 복사 단계가 없다 |
| `maximumNumberOfFiles`, `isRestoring` | 앞의 것은 복사가 끝난 뒤 나타남, 뒤의 것은 관찰 안 됨 [녹화] | 둘 다 응답에 없다(제품 코드에 이 속성이 없다) | 이번 범위에서 다루지 않았다 |

---

## 5. 검증

real-env-verifier 1회차, 2026-11-09. **PASS 11 / FAIL 0 / UNVERIFIED 0.** 재검증 회차는 없다. 제품 코드 내용 해시는 시작과 끝이 `1e950522…`로 같다. 검증자(구현자와 다른 에이전트)는 제품 코드를 고치지 않고 e2e 테스트(`restore_live.py`, `test_restore_new_volume_data_live.py`, `test_restore_new_volume_contract_live.py`)를 썼다. 메모리 때문에 e2e를 파일마다 돌리고 그 사이 WSL 페이지 캐시를 비웠다.

| AC | 결과 | 증명한 것과 측정값 |
| --- | --- | --- |
| AC-01 계약·상태 | PASS | 새 볼륨 PUT `201` + `Azure-AsyncOperation` + `Location`(일반 생성 `201`은 `location` 없음). 5 s 지연 주입 중 GET `Creating`, 작업 `action: CREATE`, `Succeeded`까지 7.24 s. 끝난 뒤 `snapshotId` = `originatingResourceId` = S, `fileSystemId`·IP가 원본과 다름, `cloneProgress` 없음, 주지 않은 `protocolTypes`(`NFSv4.1`)·`unixPermissions`(`0755`)가 원본 값. base 하나: 이름 S, `snapshotId` 다름, `created` 같음 |
| AC-02 내용 (v3) | PASS | 원본 기록 S1 → S2 → S3 → 또 바꿈, S2로 새 볼륨. 클라이언트 트리 체크섬 = 서버 S2 트리, `.snapshot`에는 `S2`만(원본의 `S1` 빈 디렉터리 없음), 새 볼륨 루트 `770`(원본 루트는 `711`로 바꿔 둠), `.snapshot` immutable, 진행 표시 없음, base LV 하나 |
| AC-03 독립성 (FR-07) | PASS | 새 볼륨에 쓰고·덮어쓰고·지워도 원본 트리, 원본 클라이언트의 `.snapshot/S2`, base가 그대로. 반대 방향도 같다(v3·v4.1) |
| AC-04 v4.1, 다른 프로토콜·풀 | PASS | (a) v4.1에서 AC-02·03 핵심. (b) v3 원본(Premium 풀)의 스냅샷으로 다른 풀(Standard)에 v4.1 새 볼륨: `actualThroughputMibps` 0.015625(원본 0.0625), 내용 = S, v3 마운트는 rc 32 `Protocol not supported` |
| AC-05 크기 | PASS | 1 GiB 원본에서 2 GiB 새 볼륨: 클라이언트 `df` 2,077,229,056 B, 1.2 GiB 쓰기 rc 0, 채우면 `No space left on device`. base로 되돌린 뒤에도 크기 그대로 |
| AC-06 생성 뒤 원본 변경 | PASS | 아래 표 |
| AC-07 거절 | PASS | 아래 경우가 모두 거절. 거절 전후 작업 수·리소스 행·원본 트리·원본 스냅샷 목록·LV 목록이 같음 |
| AC-08 원본 보호 | PASS | 20 s 지연 주입 중 S DELETE·V DELETE·V revert 모두 `409 Conflict`. 같은 동안 V의 다른 스냅샷 S9 DELETE는 `Succeeded`(막지 않음). 새 볼륨 `Succeeded` 뒤에는 셋 다 받아짐. 원본에 진행 중 작업이 있으면 새 볼륨 PUT `409` |
| AC-09 실패·회복·재시작 | PASS | (a) 실패 주입 → `Failed`, 원본 보호 유지, 주입 없는 서버에서 같은 PUT → `UPDATE` `Succeeded`, base 하나. (b) agent 정지 → 60.3 s 뒤 `Failed` → 같은 PUT으로 회복. (c) 지연 중 anf-api SIGKILL → 재시작 뒤 같은 작업이 `Succeeded`. (d) 통합 다섯 지점 모두 PASS |
| AC-10 agent API | PASS | 클론 POST `202` → job `success`(2 s). 실패 job 4종(없는 부모 볼륨, 없는 스냅샷, 다른 볼륨의 스냅샷, 작은 `size`), `400` 12종, 진행 표시가 있는 볼륨에 스냅샷 POST·DELETE·restore PATCH → job `failure` |
| AC-11 회귀 | PASS | e2e 14개 파일 131 passed(이 기능 13, 회귀 118), 통합 25 passed, 단위·계약 817 passed(Windows와 WSL 각각). 모두 skip 0 |

**AC-06 (생성 뒤 원본 되돌리기·삭제, v3, 각 1회).** 새 볼륨 클라이언트가 0.2 s마다 읽고(`PROBE`) 0.1 s마다 한 줄 덧붙이는(`WRITER`) 동안 차례로 진행했다.

| 단계 | 읽기 / 실패 | 쓰기 / 실패 | 트리·base·ARM 목록 |
| --- | --- | --- | --- |
| 원본을 S1로 되돌림(S2·S3 지워짐) | 63 / 0 | 110 / 0 | 그대로. 새 볼륨 LV `origin`이 빈칸이 됨 |
| 원본의 S1 삭제 | 82 / 0 | 146 / 0 | 그대로 |
| 원본 볼륨 삭제 | 104 / 0 | 186 / 0 | 그대로 |
| agent 재시작 | 135 / 0 | 244 / 0 | 그대로 |
| WSL 재시작 흉내(인스턴스 정지, 언마운트, `lvchange -an`, 중단 3.5 s) | 156 / 0 (가장 긴 읽기 3.017 s) | 280 / 0 (3.085 s) | 그대로. agent가 새 볼륨과 base를 다시 올림 |

성공한 쓰기 287번, 서버 파일은 `w1`…`w287`로 빠짐·중복이 없었다. 3 s 남짓의 멈춤은 중단 동안 hard 마운트가 기다린 것이고 오류는 없었다.

**AC-07 거절 (각 1회).** `snapshotId` 숫자·이름만·볼륨 ID → `400 InvalidRequestContent`. 다른 계정(그리고 다른 리소스 그룹·구독) → `400 BadRequest`. 없는 스냅샷 → `404 ResourceNotFound`(녹화 R1 문구). 원본보다 작은 크기 → `400 BadRequest`. `deleteBaseSnapshot: true` → `400 InvalidRequestContent` "not supported by this ANF clone". 풀 여유 초과 → `400` "Pool size too small for total volume size." `Failed` 스냅샷·`Failed` 원본 볼륨 → `400 BadRequest`. 끝난 새 볼륨의 재PUT·PATCH에 다른 `snapshotId`, 일반 볼륨에 `snapshotId` 추가 → `400 "SnapshotId cannot be changed."`. 같은 값(대문자로 바꾼 것 포함) 재PUT → `200` `Updating` → `Succeeded`, 헤더는 `Azure-AsyncOperation`만.

**기준 밖 관찰 (판정에 넣지 않음).**
1. 새 볼륨의 ext4 UUID가 원본과 같다(결정 6). 서로 다른 마운트 지점·인스턴스·`fsid`라서 클라이언트에서 섞이지 않았다.
2. **base 스냅샷 안 쓰기 오류 문구는 프로토콜과 연산마다 다르다.** AC-03 테스트의 순서에서 NFSv3는 덮어쓰기 계열(덧붙이기, `dd conv=notrunc`, `>`)이 `Permission denied`, `touch`·`rm`·`mv`·`mkdir`·`chmod`가 `Read-only file system`이었다. NFSv4.1은 여덟 가지 모두 `Read-only file system`이었다. 모두 rc 1이고 내용은 바뀌지 않았다. 검증자는 v3 클라이언트가 쓰기 전에 ACCESS로 권한을 묻고 서버가 ro 마운트에서 쓰기 권한을 주지 않기 때문으로 보았다 [추론, 검증자]. 스냅샷 문서 4.1절 (5)가 일반 스냅샷에서 같은 갈림을 클라이언트 RPC 카운터로 설명했다(v3 클라이언트가 그 파일을 이미 봤는지에 따라 `EACCES`/`EROFS`). base에서 그 조건을 따로 나눠 시험하지는 않았다.
3. AC-05에서 남은 공간 802 MB에 `dd`가 1.76 GB를 썼다고 센 뒤 ENOSPC로 끝났다. NFS 클라이언트가 쓰기를 캐시했다가 write-back 때 ENOSPC를 받기 때문으로 본다 [추론]. 판정은 `df`와 오류 문구로 했다.
4. contract 실행의 인스턴스 19개 중 하나(AC-08의 일반 볼륨)가 진입점의 "client tracking did not start" 재시작을 한 번 했다. 스냅샷 사이클의 진입점 동작이고 이 기능의 경로가 아니다.
5. 다른 풀의 새 볼륨은 자기 풀(Standard)의 처리량을 받는다.

---

## 6. 개발 과정

1. **선행 확인 (0단계).** 계정·풀·볼륨·스냅샷·되돌리기가 모두 `done`이었다. 되돌리기의 "스냅샷의 쓰기 가능 스냅샷"(`_resume_restore`)을 다시 쓸 수 있었다. 다만 S1 #9("쓰기 가능 thin 스냅샷으로 새 볼륨 0.127 s, 내용 독립, **ext4 UUID가 원본과 같음**")는 볼륨마다 인스턴스(D-12)와 `.snapshot` export(S4) **전**의 측정이라, 설계 전에 지금 구조에서 다시 재기로 했다.
2. **조사.** anf-researcher가 ARM 계약(녹화 R4), 문서의 제약, ONTAP FlexClone API를 조사했다. 30턴 상한에 닿았지만 필수 질문 다섯 가지에 답한 브리프를 다 썼다. 허용 범위, 크기 하한, 거절 코드, `deleteBaseSnapshot` 대상은 [미확인]으로 남았다. 설계를 막지 않는다고 보고 클론 규칙으로 정하기로 했다. ONTAP 대응(FlexClone + split)은 [추론]으로 채워졌다.
3. **스파이크 S6 (조사와 병행).** 결과는 **조건부 통과**였다. 생성 0.15 s 안팎, 저널 재생 없는 rw 마운트, 내용 일치, 원본 삭제·되돌리기 뒤에도 새 볼륨이 남음, agent의 복구 코드가 수정 없이 새 볼륨을 다룸. 조건 넷이 설계 결정이 됐다: `.snapshot`에 남은 마운트 지점(결정 8), 같은 ext4 UUID(결정 6), 만들 때 크기를 줄 수 없음(결정 4), 되돌리기가 크기까지 돌림(B2, 결정 7의 순서). 스파이크가 구현 전에 B2를 찾지 않았다면, "base로 되돌리면 볼륨이 줄어드는" 결함이 검증 단계에서야 나왔을 것이다.
4. **설계.** 결정 1~16을 모두 자동 채택했다. 사람이 내린 결정은 없다. 채택 목록과 버린 대안을 `roadmap.md`에 남겨 사용자가 나중에 검토할 수 있게 했다.
5. **구현.** Claude(implementer)가 TDD 훅 아래서 다섯 커밋으로 나눠 구현했다(`fa75aff`, `b7a26b2`, `def0999`, `bbb482a`, `a8ddc0a`). Windows `python -m pytest` 817 passed / 143 skipped(root·e2e 조건) / 0 failed, ruff 통과, WSL 통합 25 passed(새 8개). WSL 전체와 e2e 회귀는 Windows 호스트 메모리가 모자라 background shell이 정리되면서 결과를 얻지 못했다(테스트 실패가 아니다). 그래서 AC-11은 검증 단계에서 돌렸다. 구현 중 변경 10개를 설계 §9에 남겼다. 그중 §9-1(헤더 둘은 스냅샷에서 만드는 생성에만)은 녹화 둘이 서로 달라서 생긴 판단이고 메인 세션이 받아들였다.
6. **검증 1회차.** 11/11 PASS. 제품 결함은 없었다. 메모리 문제를 피하려고 e2e를 파일마다 돌렸고(Windows 여유 메모리 최저 약 3.9 GB), 기준 밖 관찰 다섯을 남겼다.
7. **개념 문서(이 문서).**

AI와 일한 방식으로 설명할 수 있는 것: 이번 사이클은 사람에게 묻는 결정 없이 자동으로 굴러갔다. 그 대신 (a) 이전 스파이크(S1 #9)가 지금 구조 전의 측정이라는 점을 0단계에서 잡아 S6로 다시 쟀고, (b) 스파이크의 관찰 넷을 그대로 설계 결정으로 옮겼으며, (c) 자동 채택한 결정을 버린 대안과 함께 기록해 사람이 뒤에서 검토할 수 있게 했다. 구현 중에는 설계가 정하지 않은 위험(되돌리기가 진행 표시를 잃음, §9-2)을 찾아 막았다. 검증은 구현자와 다른 에이전트가 실환경에서 했다.

---

## 7. Interview Q&A

### Q1. (개념) How does "restore a snapshot to a new volume" work in Azure NetApp Files from the API side?

**A.** It is not a separate action. You send a normal volume PUT with `properties.snapshotId` set to the snapshot's full ARM resource ID. That property is create-only in the spec and is not in the PATCH model. The recorded service answered 201 with `Azure-AsyncOperation` and `Location`, the volume in `Creating`, and the operation reached `Succeeded` with `action: CREATE` in about 11 seconds, versus about six minutes for a normal volume in the same recording. Afterward, `originatingResourceId` held the same snapshot ID, and the new volume had a base snapshot with the source snapshot's name, a new `snapshotId`, and the same `created` time. A background copy then continued: `cloneProgress` showed 0 and disappeared after about six minutes.

### Q2. (개념) What does it correspond to in ONTAP, and how sure are you?

**A.** I believe it maps to a FlexClone volume followed by a clone split, but that is an inference, not documented. The evidence is that ANF's docs call the process cloning, and its error message says "Failed to split new volume from source volume snapshot". In ONTAP REST you create one with `POST /api/storage/volumes` and the fields `clone.is_flexclone`, `parent_volume`, and `parent_snapshot`. A FlexClone shares its base snapshot with the parent, and the parent cannot be deleted while the clone exists. A split runs in the background and reports `split_complete_percent`, which looks like ANF's `cloneProgress`. After a split, the two cannot be rejoined. It is not SnapRestore. That is the in-place revert, a different feature.

### Q3. (설계) Why did you build the new volume as a writable thin snapshot instead of copying the data?

**A.** Because dm-thin already gives an instant, independent volume, and copying would throw that away. The agent runs `lvcreate -s -kn -p rw` on the source snapshot's LV and attaches the volume tags in the same command. In spike S6 that took about 0.12 to 0.21 seconds, ext4 mounted read-write with no journal replay, and the pool did not grow: the new volume mapped about 150 MB but owned only 64 KiB. After that, writes cost only what they change. Copying with rsync or a block copy would take time proportional to the data, and the only reason would be to imitate ANF's note that pool consumption doubles after the copy. The tradeoff is shared thin-pool risk, and deleting the source frees no shared blocks.

### Q4. (설계) The new volume has the same ext4 UUID as its source. Why is that safe for NFS, and why didn't you change it?

**A.** It is safe because NFS never sees the ext4 UUID in my setup. Each volume's export line sets `fsid` explicitly to that volume's own `fileSystemId`, so file handles from the two volumes cannot collide. In the spike, one client mounted the source and the new volume at once and got different device numbers and separate data, and the same held for two NFSv4.1 volumes. The only effect is on the host: `/dev/disk/by-uuid` and `blkid -U` point to just one device, and my agent addresses devices by LV path only. Changing it was costly. `tune2fs -U` demands a freshly checked filesystem, `e2fsck -f` creates `lost+found`, which my create code reads as "just formatted", and the change rewrites every metadata checksum.

### Q5. (설계) Why is the base snapshot a separate snapshot of the new volume, and why do you take it after resizing?

**A.** Because dm-thin has no shared snapshot. In ONTAP, a FlexClone's base snapshot is shared with the parent. In my clone, a snapshot LV belongs to one volume through its tags. If the new volume pointed at the source's snapshot, deleting that snapshot later would remove it from the new volume too. So the agent takes a fresh read-only thin snapshot of the new volume, with the source's name and creation time and a new UUID. It still costs almost no space, because it shares blocks. The order came from spike S6. A base taken before growing the volume from 1 to 2 GiB made a later revert shrink it back to 1 GiB, because my revert swaps in a writable snapshot of that snapshot, at the snapshot's size. Taking it after `lvextend` and `resize2fs` fixed that.

### Q6. (설계) Why do you still block deleting the source while the new volume is being created, if dm-thin doesn't need it?

**A.** Because the risk is the window before the data plane has the new LV, not after. Agent jobs run one at a time, so a clone job can still be waiting when a snapshot delete arrives. If the source snapshot is gone before `lvcreate`, creation fails and the same PUT cannot recover. The anf-api handler also reads the source rows to build the clone fields. So until the new volume first reaches `Succeeded`, which is when `originatingResourceId` is written, deleting the source snapshot or volume, or reverting the volume, returns 409. A revert could delete the source snapshot as a newer snapshot. One function, `ensure_not_cloning`, covers all three. Other snapshots of the source stay deletable. Once the LV exists, its progress tags hold the base snapshot's name and time.

### Q7. (설계/장애) How did you make volume creation from a snapshot restart-safe?

**A.** With progress markers in LVM tags, so the system state itself records how far it got. The `lvcreate` that makes the new volume LV also attaches `anf_cl_snap`, `anf_cl_name`, and `anf_cl_time`, and one `lvchange --deltag` removes them at the end. Every step in between checks real state first: extend only if smaller, mount only if unmounted, create the base snapshot only if missing. Startup recovery skips marked volumes, because the requested size and permissions are not in tags. anf-api re-runs unfinished operations after a restart, and a failed volume is fixed with the same PUT, so the same agent POST finishes the job. Integration tests stop at five points, and the verifier killed the agent mid-job. Each time exactly one base snapshot remained and the markers were gone.

### Q8. (트레이드오프) Where does your implementation differ from real ANF, and what did you trade off?

**A.** The biggest difference is that there is no background copy. A thin snapshot is independent from the moment it exists, so there is no `cloneProgress`, and I protect the source only until the new volume first succeeds, while ANF documents a copy that can take minutes. Second, space: ANF's docs say pool consumption doubles when the restore completes. My new volume shares blocks and uses only what it writes, but it shares thin-pool overcommit risk with the source. Third, the base snapshot is a separate snapshot, not a shared one. Fourth, the ext4 UUID matches the source. Finally, several rules are mine, because ANF's are unconfirmed: other pools in the same account are allowed, the size must be at least the source's, `deleteBaseSnapshot: true` is rejected, and the error codes are my own.

### Q9. (장애·디버깅) A volume created from a snapshot is stuck in `Failed`. How would you investigate and recover it?

**A.** I would start from the operation ID and work down to the data plane. The operation error is a generic `InternalServerError` that includes the operation ID. The anf-api log has the exception for that ID. It holds the agent's job message, such as "snapshot … not found", or 60 seconds of `is unreachable` retries if the agent was down. The agent logs each job with the correlation request ID. Next I check LVM: does `vol_<uuid>` exist, and does it still carry `anf_cl_*` tags? If so, creation stopped midway. The fix is the same PUT, which runs as an `UPDATE` and lets the agent resume. While the volume is unfinished, the source stays protected, so recovery remains possible. The verifier tested this after an injected failure, a stopped agent, and kills of both processes. ANF's docs instead say to delete and retry.

### Q10. (REST/LRO) Your create-from-snapshot response has two tracking headers, but a normal create has one. Why?

**A.** Because the two real recordings disagree, and I followed each instead of forcing one answer. The recording of a normal volume create shows only `Azure-AsyncOperation`. The recording of a create from a snapshot shows `Azure-AsyncOperation` and `Location`. My volume contract was already verified against the first, so changing every create would have broken a confirmed contract. So only a 201 whose volume has a `snapshotId` gets both headers, and updates still return 200 with one. I recorded that as an implementation change. The same care applies to the property itself: `snapshotId` is create-only, so a different value on re-PUT or PATCH is a 400, "SnapshotId cannot be changed", and the same value, compared case-insensitively, is accepted.

### Q11. (테스트) How did you prove the new volume is really independent of its source?

**A.** With checksums and live NFS clients, in both directions, and then by destroying the source. The verifier built a history on the source, with snapshots S1, S2, and S3 and changes in between, and created the new volume from S2. File-by-file sha256 lists matched S2 on the server and on a client, over NFSv3 and NFSv4.1. Writes, overwrites, and deletes on the new volume left the source tree, the source snapshot, and the base snapshot unchanged, and the reverse held too. Then, while a client read every 0.2 seconds and appended every 0.1 seconds, the verifier reverted the source to S1, which deleted S2, deleted its last snapshot and the source volume, and restarted the agent. Reads and writes had zero failures, and the 287 appended lines had no gaps.

### Q12. (다시 한다면) If you did this again, what would you change?

**A.** Three things. First, all sixteen design decisions were adopted automatically, with no human choice, because none changed a confirmed decision or reduced acceptance criteria. Next time I would show the riskiest ones to a person before implementing, especially the size floor and allowing other pools, since ANF's rules are unconfirmed. Second, I would test those unknowns against a real ANF account: the rejection codes, the `usageThreshold` rule, and what `deleteBaseSnapshot` deletes. Third, I would revisit the ext4 UUID. If every volume were formatted with `metadata_csum_seed`, each new volume could get its own UUID cheaply without a filesystem check. I would also watch thin-pool usage, because clones share blocks and nothing runs `fstrim`, so deleted space does not return to the pool.

---

## 부록. 이 문서가 쓰지 못한 것

브리프·스파이크·검증 보고서에 근거가 없거나 [미확인]이라 쓰지 못한 것이다.

- **ANF가 FlexClone + split을 쓴다는 공식 문장.** 대응은 오류 문구와 "clones" 표현에서 읽은 [추론]이다.
- **FlexClone이 즉시 생기는 ONTAP 내부 원리(WAFL).** 브리프에는 "base 스냅샷을 공유한다", "명목 크기의 약 0.5%를 쓴다"까지만 있다.
- **ANF의 "data copy process"와 ONTAP 9.4 이상 AFF의 "split은 데이터를 복사하지 않는다"가 맞지 않는 이유.** ANF 백엔드의 플랫폼·볼륨 보장 설정은 브리프에 없다.
- **ANF의 거절 응답 전부**: 다른 풀·계정·서비스 수준, 원본보다 작은 `usageThreshold`, 다른 `protocolTypes`, 복사 중 원본 스냅샷·볼륨 DELETE, 재PUT으로 `snapshotId` 변경, 없는 스냅샷이 PUT 4xx인지 작업 `Failed`인지.
- **`deleteBaseSnapshot`이 지우는 대상과 시점.**
- **ANF "공간 2배"가 풀 할당인지 사용량인지.**
- **ANF가 FlexClone의 명목 크기(부모 크기)를 사용자 `usageThreshold`로 바꾸는 시점.**
- **`isRestoring`이 `true`가 되는 조건**, 복사 중 원본을 revert할 때의 동작, 녹화 테스트가 무엇을 기다렸는지.
- **ONTAP 부모 스냅샷의 `busy, vclone`/owner 원문**(KB 요약만), 부모 스냅샷이 없을 때의 ONTAP 전용 오류 코드.
- **새 볼륨 복원에서 ANF의 `unixPermissions` 기본값.** 브리프에 없다. 클론은 원본 값을 쓴다(결정 3).
- **dm-thin 블록 공유의 커널 문서 근거.** 스냅샷 문서와 같이 측정(S6 R의 mapped/exclusive)으로만 뒷받침한다.
- **base 스냅샷 안 쓰기에서 v3 errno가 갈리는 조건.** 검증자는 [추정]으로 남겼고, 스냅샷 문서의 RPC 카운터 설명을 base에서 따로 시험하지 않았다.
