# 스냅샷 (snapshot, NFS `.snapshot`)

> ANF 스냅샷은 볼륨 아래의 ARM 자식 리소스이면서, NFS 클라이언트가 `<볼륨 IP>:/<creationToken>/.snapshot/<이름>/`에서 읽는 그 시점의 읽기 전용 사본이다. 이 클론은 스냅샷 하나를 읽기 전용 dm-thin 스냅샷 LV(ONTAP Snapshot copy가 들어갈 자리)로 만들고, 볼륨 인스턴스(knfsd) 안에서 스냅샷마다 자기 `fsid`로 따로 export한다. 이 기능은 볼륨 기능의 결함(NFSv4.1 인스턴스가 재시작하지 못함)도 함께 고쳤다.

FR-05(스냅샷)를 다루고, 결함 수정으로 FR-04(볼륨)도 건드렸다. 대상 코드는 `feature/snapshot` 브랜치의 제품 커밋 `a2a819e`(storage agent)와 `27757aa`(anf-api)이고, 제품 코드 내용 해시 `f5607a08…`은 검증 시작과 끝이 같다. 공통 비동기 작업(LRO) 계층은 [계정 문서](netapp-account.md), 볼륨 저장 방식과 인스턴스 구조는 [볼륨 문서](volume.md)에 있다. 이 문서는 스냅샷이 그것들을 어떻게 쓰는지와 새로 생긴 것만 설명한다.

근거 표시는 브리프를 따른다.

| 표시 | 뜻 |
| --- | --- |
| [스펙] | Azure REST API 스펙(OpenAPI/TypeSpec)에 적혀 있다 |
| [문서] | Microsoft Learn이나 NetApp 문서에 적혀 있다 |
| [녹화] | Azure SDK 테스트 세션 녹화에서 실서비스 응답으로 관찰했다. 문서로 보장된 동작은 아니다 |
| [추론] | 근거에서 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |
| [브리프 밖] | 조사 브리프에 없는 설명이다. 클론 코드 주석이나 스파이크·검증 관찰에 기대었고, ANF·ONTAP 사실로 말하면 안 된다 |

---

## 1. ANF에서는

### 1.1 리소스와 API

- 스냅샷은 볼륨의 자식 ProxyResource다: `.../volumes/{v}/snapshots/{snapshotName}`. 본문은 `location`(필수)과 읽기 전용 `snapshotId`, `created`, `provisioningState`뿐이다. **`tags`는 없다** [스펙]. 응답의 `name`은 `"{account}/{pool}/{volume}/{snapshot}"`이다 [녹화].
- 스펙에는 이름 패턴이 없다. 실서비스가 거절하는 이름은 찾지 못했다 [미확인]. ONTAP에는 "이름이 잘못됨"(`1638518`)과 "금지 접두어"(`1638477`) 오류가 있지만 규칙 내용은 [미확인]이다.
- **작업별 응답** (api-version `2026-08-01`, 녹화는 `2026-08-15-preview`):

| 작업 | 응답 | 헤더 | 작업 상태 | 걸린 시간 | 근거 |
| --- | --- | --- | --- | --- | --- |
| PUT 생성 | `201`, 본문 `Creating`, `snapshotId`·`created` 없음 | `Azure-AsyncOperation` + `Location` (`Retry-After` 없음) | `Creating` → `Succeeded`, `action CREATE` | 약 2~3초 | [녹화] (스펙 예시는 `Succeeded` 본문과 `Location`+`Retry-After`로 다르다 [스펙]) |
| DELETE | `202`, 본문 없음 | 두 헤더 | `Deleting` → `Succeeded`, `action DELETE` | 약 2초 | [녹화] |
| 없는 스냅샷 DELETE | `204` | 없음 | — | — | [스펙]. 실동작 [미확인] |
| GET | `200` | | | | [녹화] |
| GET 없음 | `404 ResourceNotFound`, ANF 전용 문구 | | | | [녹화] |
| 목록 | `200 {"value": [...]}`, 비면 `{"value": []}` | | | | [녹화] |
| PATCH | 스펙은 빈 본문 `{}`에 200/202. 실동작 [미확인] | | | | [스펙] |

- 404 문구는 ANF RP가 직접 만든 것이다: "The requested snapshot '<s>' was not found on the volume '<a>/<p>/<v>'. Please check the requested snapshot. Please note: The snapshot may no longer be available based on configured snapshot policies." [녹화].
- **`snapshotId`.** 스펙은 "UUID v4"라 하지만 녹화 값은 셋째 묶음이 `ba01`, `292c`처럼 `4`로 시작하지 않는다. ANF가 백엔드(ONTAP) 스냅샷 `uuid`를 그대로 내보내는 것으로 보인다 [추론, 값 모양에서. 공식 출처 없음].
- **한도.** 볼륨당 스냅샷 255개, 지원 요청으로도 늘릴 수 없다 [문서]. 256번째에 ANF가 돌려주는 오류는 [미확인]이다.
- **볼륨 DELETE.** "online snapshots ... are part of the volume and are deleted with the volume deletion" [문서]. 그래서 스냅샷이 남은 볼륨의 DELETE를 ANF가 받아 연쇄로 지울 것으로 본다 [추론]. 녹화의 테스트는 모두 스냅샷을 먼저 지웠다 [녹화]. 같은 이름 PUT 재전송의 ARM 응답은 스펙에 200이 없어 정할 수 없고 녹화도 없다 [미확인].

### 1.2 데이터 플레인에서 보이는 효과

- 마운트한 볼륨에 `.snapshot`(SMB는 `~snapshot`)이 있고, 그 아래 스냅샷마다 하위 디렉터리가 하나 있다 [문서]. 하위 디렉터리 이름이 스냅샷 이름이라는 직접 문장은 못 찾았다. 정책 스냅샷 예시(`daily.2020-05-14_0013`)에서 본 [추론]이다. 스냅샷은 읽기 전용으로 접근된다 [문서]. 쓰기 때 클라이언트가 받는 errno는 [미확인]이다.
- NFSv3: `.snapshot`이 기본으로 보인다. NFSv4.1: "By design, the `.snapshot` directory is never visible"이고, 숨김 옵션이 꺼져 있으면 `cd .snapshot`으로 이름을 직접 넣어 들어갈 수 있다 [문서].
- `snapshotDirectoryVisible`(포털 이름 "Hide snapshot path"의 반대)의 기본값은 `true`다 [스펙][녹화]. **숨겼을 때 효과는 ANF 문서끼리 다르다.** 한 문서는 "NFSv3 클라이언트에게 숨기지만 접근은 된다", 다른 문서는 "숨기면 스냅샷 안 파일 접근도 막힌다"고 쓴다 [문서]. ANF가 어느 쪽인지는 공개되지 않았다 [추론].
- **공간.** 스냅샷이 쓰는 용량은 볼륨 할당량에 들어간다("The capacity consumed by volume snapshots counts towards the provisioned space in the volume") [문서]. ANF에는 snapshot reserve 설정이 없다 [문서][스펙]. 스냅샷은 만들 때는 공간을 쓰지 않고, 그 뒤 바뀐 블록만큼 쓴다 [문서]. 클라이언트 `df`에 스냅샷 사용량이 어떻게 보이는지는 [미확인]이다.

---

## 2. ONTAP에서는

| ANF 개념 | ONTAP 개념 | 말할 수 있는 수준 |
| --- | --- | --- |
| 스냅샷 | 볼륨 스냅샷(Snapshot copy). REST `POST /api/storage/volumes/{volume.uuid}/snapshots` | ANF 문서가 "Redirect on Write"로 설명하고, 스냅샷은 블록 포인터를 보존하며 데이터 블록을 복사하지 않는다고 쓴다 [문서]. ONTAP REST는 "the view of the filesystem as it exists at the time when the snapshot is created"로 정의한다 [문서]. ANF 스냅샷이 ONTAP 볼륨 스냅샷이라는 직접 문장은 없다 [추론] |
| `snapshotId` | 스냅샷 `uuid` ("uniquely identifies the snapshot in that volume") | 대응은 [추론], 필드는 [문서] |
| `created` | `create_time` | 대응 [추론] |
| 255개 한도 | ONTAP 9.4 이상 FlexVol은 1023개 | ANF 한도가 더 낮다. 이유는 [미확인] |
| `.snapshot`, `snapshotDirectoryVisible` | 볼륨 `-snapdir-access`(REST `snapshot_directory_access_enabled`, 기본 true), SVM NFS `-v3-hide-snapshot` | 앞의 것은 접근 자체를 켜고 끈다. 뒤의 것은 NFSv3 목록에서만 숨긴다. ANF 문서 두 개의 서로 다른 설명이 이 두 옵션에 하나씩 대응한다. 볼륨 단위 속성이라 `-snapdir-access`에 가까울 것이다 [추론] |
| 스냅샷 공간이 할당량에 포함 | snapshot reserve (`-percent-snapshot-space`, 기본 5%) | ANF에는 reserve 설정이 없다. ANF가 내부에서 reserve를 0으로 두는지는 [미확인] |
| 볼륨 삭제 시 스냅샷 삭제 | 스냅샷은 볼륨의 일부 | [문서] |

- **ONTAP REST 스냅샷 API** [문서]: 생성은 `POST /api/storage/volumes/{volume.uuid}/snapshots`이고 필수 필드는 `name` 하나다. 응답은 `202` + `job`(`return_timeout` 안에 끝나면 `201`로 보인다 [추론])이다. 같은 이름은 `525059`, 개수 초과는 `525062`다. 삭제는 `DELETE .../snapshots/{uuid}`로 이름이 아니라 **UUID**로 지정하고, 없는 스냅샷은 `1638600`이다. 202 본문에는 새 스냅샷의 `uuid`가 없어서 job이 끝난 뒤 `GET ...?name=`으로 얻어야 한다 [추론].
- **`.snapshot`은 어디서 보이는가.** ONTAP REST 설명은 "The .snapshot directory will be available in every directory on the volume"이다 [문서]. NFSv3 `ls -la`에 보이는 곳은 마운트 지점뿐이고, NFSv4는 목록에 안 보이지만 이름으로는 접근된다 [문서, NetApp KB의 WebSearch 요약만 확인, 원문 미확인].

### 2.1 스냅샷이 즉시 만들어지는 이유 (ONTAP Snapshot copy와 클론의 dm-thin)

- **ONTAP 쪽.** ANF 문서는 스냅샷을 "Redirect on Write"로 설명한다. 스냅샷을 만들 때 파일시스템의 블록 포인터를 보존할 뿐이고 데이터 블록은 복사하지 않는다. 그 뒤 활성 파일시스템에서 블록을 고치면 새 블록에 쓰고 포인터만 새 블록으로 옮기며, 옛 블록은 스냅샷이 계속 가리킨다 [문서 요지, 문서 6]. 그래서 만들 때 공간이 들지 않고, 바뀐 블록만큼 쓴다. 이 구조를 WAFL이라는 이름으로 부르는 설명은 조사 브리프에 없다 [브리프 밖]. 면접에서 "WAFL"을 말하려면 이 문서가 아니라 NetApp 자료로 따로 확인해야 한다.
- **클론 쪽 (dm-thin).** 스냅샷은 `lvcreate -s`로 만드는 thin 스냅샷 LV다 (`flexvol.py:209-214`). 스냅샷과 원본이 같은 블록을 공유하고, 원본에 쓰기가 오면 그 블록(청크)을 새로 할당해 쓴다. 이를 블록 단위 Copy-on-Write로 설명한다 [추론, 요청자의 설명과 아래 측정에서. S1 원문에는 이 문장이 없다]. 측정이 이를 뒷받침한다 (검증 AC-02, AC-03): 스냅샷을 만든 직후 씬 풀 사용량은 +524288 B(청크 하나)만 늘었고, 64 MiB 파일을 덮어쓴 뒤에는 +69730304 B(약 66.5 MiB) 늘었다. 클라이언트 `df`의 사용량은 67108864에서 변하지 않았다. 씬 풀의 할당 단위(청크)는 512 KiB다 (`lvs -o chunk_size anf/aggr0` = `512.00k`, `dmsetup table`의 블록 크기 1024 섹터, WSL에서 2026-11-08 확인). 그래서 +524288 B는 정확히 청크 1개이고, +69730304 B는 청크 133개(64 MiB 데이터 = 128개 + 5개)다. 공유를 깨는 단위가 파일 블록(4 KiB)이 아니라 이 청크라는 점이 ONTAP과 다르다 [측정 + 추론].
- **대응 표.**

| | ONTAP Snapshot copy | 클론의 dm-thin 스냅샷 |
| --- | --- | --- |
| 만들 때 비용 | 포인터 보존, 데이터 복사 없음 [문서] | thin 스냅샷 생성. 스냅샷 생성 작업은 1.10~1.15 s, 청크 하나만 늘었다 (검증) |
| 바뀐 데이터 처리 | 활성 파일시스템이 새 블록에 쓰고 포인터를 옮김(redirect on write) [문서] | 같은 청크(512 KiB)를 공유하다가 쓰기 때 새 청크를 할당(청크 단위 CoW) [측정 + 추론] |
| 공간이 나가는 곳 | 볼륨 할당량(ANF) [문서] | **씬 풀 = aggregate에 해당하는 자리**. 볼륨 할당량에는 잡히지 않는다 (검증 AC-02) |
| 보호 단위 | 스냅샷은 볼륨의 일부 [문서] | 스냅샷 LV는 원본 LV와 별개 장치다. 그래서 삭제와 복구를 따로 챙겨야 한다 |

- **면접에서 안전한 문장.** "ANF 문서는 스냅샷이 Redirect on Write로 블록 포인터만 보존한다고 쓴다. 클론은 dm-thin의 읽기 전용 스냅샷 LV로 같은 효과(만들 때 공간이 안 들고 바뀐 블록만큼 쓴다)를 냈다. 메커니즘은 다르다. 이것이 ONTAP이 실제로 하는 일이라고 말하지는 않는다."

---

## 3. 이 프로젝트에서는

### 구조

```
  클라이언트 (curl, SDK)                               NFS 클라이언트 (컨테이너)
     | PUT/GET/DELETE .../volumes/{v}/snapshots/{s}         | mount <볼륨 IP>:/<creationToken>
     v                                                       |  ls .snapshot/<이름>/
  anf-api (일반 사용자, :8080)                               |
   arm_app.py       스냅샷 라우트 (201/200/202/204)          |
   snapshots.py     본문 검사, 흐름, 처리기                  |
        | 한 트랜잭션: 리소스(Creating) + 작업 행(CREATE)    |
        v                                                    |
   state_store.py  <--- lro.py 워커 (공통) ---+              |
                             | ensure / delete 처리기        |
                             v                               |
   storage_client.py  POST .../snapshots (uuid 포함) -> 202 + job -> job 폴링 -> GET 레코드
        v
  storage agent (root, :8090)
   agent_app.py    입력 재검사, job 접수 (accepted)
   flexvol.py      스냅샷 LV -> .snapshot(+i) -> 마운트 지점·ro 마운트 -> export 파일
   nfs_instance.py export 파일 쓰기 + exportfs -ra (인스턴스 안)
        v
  dm-thin 풀 anf/aggr0 -> snap_<uuid> (읽기 전용 thin 스냅샷)
        -> ns/<token>/.snapshot/<이름>  (ro,noload 마운트)
        -> 볼륨 인스턴스(knfsd)가 /<token>/.snapshot/<이름> 을 자기 fsid로 export
```

볼륨과 같은 두 겹의 비동기 구조다(바깥은 ARM LRO, 안쪽은 ONTAP 모양 job). 새로 생긴 것은 세 가지다. (1) 스냅샷 하나를 클라이언트에게 보이게 하는 데이터 플레인 구성(스냅샷마다 마운트와 export 줄), (2) 볼륨을 지우면 스냅샷이 따라 지워지는 연쇄 삭제, (3) 이 과정에서 발견해 고친 볼륨 인스턴스 재시작 결함이다.

### 코드 따라가기

#### (1) anf-api: 본문과 PUT — `snapshots.py:37-158`

- `parse_put_body`(`:37-53`)는 최상위 `location`(필수)과 `properties`(선택)만 받는다. 읽기 전용 키(`id`, `name`, `type`, `systemData`, `provisioningState`, `snapshotId`, `created`)는 무시하고, 그 밖의 키는 `tags` 포함 `400 InvalidRequestContent`다. 스냅샷 모델에 `tags`가 없기 때문이다 [스펙] (설계 결정 12).
- `_new_snapshot`(`:95-106`): 볼륨이 `Succeeded`가 아니면 `400 BadRequest`, 255개를 넘으면 `400 BadRequest`(ONTAP `525062` 문구를 빌림. ANF 코드는 [미확인])다(`:96-100`). **`snapshotId`를 PUT 때 `uuid4()`로 만들어 저장한다**(`:104`). 이것이 agent 스냅샷 uuid이자 멱등 키다 (결정 9, 볼륨의 `fileSystemId`와 같은 방식).
- `put_snapshot`(`:130-158`): 한 트랜잭션 안에서 부모 볼륨 없음 → `404 ParentResourceNotFound`(`:139-144`), 볼륨 `Deleting` → `409 Conflict`(`:145`), 스냅샷이 없으면 `Creating` + `CREATE` 작업(`:147-151`)을 쓴다. **이미 있으면** 진행 중 작업을 막고(`:152`) `Updating` + `UPDATE` 작업으로 `200`을 낸다(`:155-158`). 바꿀 속성이 없으므로 처리기는 데이터 플레인 보장만 다시 한다. 그래서 `Failed` 스냅샷도 같은 PUT으로 고쳐진다 (결정 3, 근거가 없는 선택이다: 스펙 응답 목록에 200이 없고 ARM 실동작은 [미확인]).
- 라우트(`arm_app.py:293-303`): 생성 `201`에는 두 헤더를 주고, 다시 PUT인 `200`에는 `Azure-AsyncOperation`만 준다(`:301-302`). `snapshot_body`(`snapshots.py:56-68`)는 `created`가 생긴 뒤에만 `snapshotId`·`created`를 내보낸다 [녹화] (201 본문에 없고 GET에 나온다).
- `snapshotId`는 클론에서 uuid4이고 ANF 녹화 값은 v4 모양이 아니다. 클론은 스펙 설명("UUID v4")에 맞췄다 (결정 9, 4절 (6)).

#### (2) anf-api: DELETE와 연쇄 삭제 — `snapshots.py:161-173`, `volumes.py:410-429`, `state_store.py:189-194`

- 스냅샷 DELETE는 있으면 `Deleting` + `DELETE` 작업(`202`), 없으면 `204`다 (`snapshots.py:161-173`). 볼륨이 `Deleting`이면 `409`다(`:169`).
- **볼륨 DELETE** (`volumes.py:410-429`): 자식 스냅샷 중 진행 중인 작업이 하나라도 있으면 `409 Conflict`("Cannot delete volume ... because an operation is in progress on its snapshot ...")다(`:421-425`). 계정·풀은 자식이 있으면 `409 CannotDeleteResource`로 막지만 볼륨은 스냅샷을 **받아들이고 같이 지운다** [문서 근거, 결정 2].
- 작업이 끝나면 `Tx.delete_resource`(`state_store.py:189-194`)가 자식 행까지 재귀로 지운다. 볼륨 행과 스냅샷 행이 한 트랜잭션에서 사라진다. 계정·풀은 DELETE 전에 자식을 막으므로 이 재귀에 자식이 오지 않아 동작이 같다.

#### (3) 처리기와 agent 호출 — `snapshots.py:179-200`, `storage_client.py:67-80`

- `ensure`(`:185-193`)는 부모 볼륨의 `fileSystemId`로 agent를 부른다: `POST /api/storage/volumes/{fsid}/snapshots` 본문 `{"name", "uuid"}`, job을 폴링하고, 끝나면 `GET .../snapshots/{uuid}`로 `create_time`을 읽어 `created`에 기록한다 (`storage_client.py:67-77`). CREATE와 UPDATE가 같은 `ensure`다.
- `delete`(`:195-198`)는 `DELETE .../snapshots/{uuid}`다. agent 호출이 실패하면 예외가 공통 워커로 올라가 작업이 `Failed`(`InternalServerError`)가 되고 스냅샷도 `Failed`가 된다. 같은 PUT이 다시 보장한다.
- 결함 주입 키 `snapshots/{create|update|delete}`는 등록된 처리기에서 자동으로 생긴다 (`lro.py`의 공통 규칙).

#### (4) agent API — `agent_app.py:70`, `:112`, `:142-166`

- ONTAP REST 부분집합: `POST`·`GET /api/storage/volumes/{volume.uuid}/snapshots`, `GET`·`DELETE .../snapshots/{uuid}`. 응답은 레코드 `{"uuid", "name", "create_time", "volume": {"uuid"}}`뿐이다.
- `POST`는 요청에서 `uuid`를 받는다(ONTAP 필수 필드는 `name`뿐이라 클론 확장). 같은 uuid·이름이면 성공 job, **같은 이름에 다른 uuid면 실패 job**("A snapshot with the specified name already exists." = ONTAP `525059` 문구)이다. 입력은 agent가 다시 검사한다: 이름은 같은 정규식, uuid는 소문자 UUID, 모르는 필드는 400 (`parse_snapshot`, `:70`).
- `accepted()`(`:112`)는 볼륨 job과 스냅샷 job이 함께 쓰는 접수 함수다. job은 한 번에 하나씩 돈다 (결정 15). 이 때문에 job 시작 로그 문구가 `POST volume {uuid}: job`에서 `POST /api/storage/volumes/{uuid}: job`으로 바뀌었다 (4단계에서 볼륨 e2e의 표시 문자열만 고쳤다, 6절).

#### (5) `flexvol.py`: 스냅샷 생성 — `create_snapshot`, `flexvol.py:190-218`

1. **확인** (`:193-204`): 볼륨이 없으면 실패, 호스트에 마운트돼 있지 않으면(`offline`) 실패한다. offline이면 `.snapshot`이 빈 마운트 지점 아래에 생기기 때문이다 (설계 §9 4). 같은 uuid·다른 이름은 실패, 같은 이름·다른 uuid는 실패("already exists")다.
2. **스냅샷 LV** (`:205-215`): `lvcreate -s -kn -p r -n snap_<uuid 32자리> <VG>/<볼륨 LV>`. `-p r`은 블록 장치부터 읽기 전용으로 만들고, `-kn`은 activation skip을 꺼서 agent 시작 때의 `vgchange -ay`가 스냅샷도 활성화하게 한다. **메타데이터는 LVM 태그**에 둔다: `anf_snap_uuid`, `anf_snap_name`, `anf_snap_vol`, `anf_snap_time`(UTC ISO 8601). agent에는 DB가 없다 (볼륨 결정 8). 만든 시각은 `lv_time` 대신 태그에 둔다. `lv_time`은 형식이 설정에 따라 달라지기 때문이다.
3. **`.snapshot` 보장** (`:216`, `_ensure_snapshot_dir` `:338-344`): `.snapshot`이 없으면 만들고, `lsattr -d`로 `i` 플래그를 보고 없으면 `chattr +i`를 한다. 플래그까지 확인하는 이유: `mkdir`은 됐는데 `chattr`가 실패한 볼륨이 영영 `+i`가 되지 않을 수 있기 때문이다 (설계 §9 3). 볼륨 생성(`create`, `:153`)과 시작 복구(`recover`, `:126`)에서도 같은 함수를 부른다. 그래서 스냅샷이 없는 볼륨에도 빈 `.snapshot`이 있다 (ONTAP의 `.snapshot`이 스냅샷이 없어도 있는 가상 디렉터리인 것에 맞춤. 설계 결정 8).
4. **마운트** (`:217`, `_ensure_snapshot_mounted` `:355-362`): 마운트 지점은 `ns/<token>/.snapshot/<이름>`이다. `.snapshot`은 `+i`이므로 마운트 지점을 만들 때 `_change_snapshot_dir`(`:346-353`)가 `chattr -i` → `mkdir` → `chattr +i`를 하고, `finally`로 실패해도 다시 잠근다. 마운트는 `-t ext4 -o ro,noload`다. `noload`는 읽기 전용 장치라 저널을 재생하지 않는다는 뜻이다.
5. **export 파일** (`:218`, `_write_exports` `:364`).

#### (6) 스냅샷마다 export 줄 — `nfs_instance.py:30-42`, `:130-141`

- `write_exports`가 볼륨 줄 하나와 스냅샷 줄을 이름순으로 `<exports>/<uuid>/volume.exports`에 쓴다(임시 파일 + `os.replace`, `:137-139`). 인스턴스가 돌고 있으면 `docker exec <인스턴스> exportfs -ra`로 적용한다(`:140-141`). 내용이 같아도 늘 다시 쓰고 적용한다: 파일 쓰기는 됐는데 `exportfs -ra`가 실패한 job을 다시 보냈을 때, 내용이 같다고 건너뛰면 export 없이 job이 성공하기 때문이다 (설계 §9 2).
- 스냅샷 줄 옵션 `SNAPSHOT_OPTIONS = ro,sync,no_subtree_check,no_root_squash,secure,mp`에 **`fsid=<스냅샷 uuid>`**를 붙인다(`:42`, `:134`). 볼륨 줄(`:39`)의 `crossmnt`는 그대로 두어 클라이언트가 스냅샷 하위 마운트로 넘어가게 한다.
- **왜 스냅샷마다 fsid가 필요한가 (S4 E1·E2).** 부모의 `crossmnt`만 두고 스냅샷을 하위 마운트하면 v3·v4.1 모두 `Stale file handle`이었다. thin 스냅샷의 ext4 UUID가 원본과 같아서, mountd가 자동으로 만드는 하위 export의 fsid가 부모와 겹친 것으로 본다 [추론]. 스냅샷마다 자기 `fsid`로 따로 export하면 v3·v4.1 모두 읽혔다.
- **왜 export 표를 파일로 두는가 (S4 E5·F1).** 스냅샷마다 `docker exec exportfs -o`로 export하면, 인스턴스가 재시작할 때 진입점의 종료 처리(`exportfs -ua`)가 스냅샷 export를 지우고 시작 때는 볼륨만 export한다. 클라이언트가 `Symbolic link loop`(ELOOP)를 본다. 파일은 `/etc/exports.d`로 읽기 전용 바인드되어(`:104`) 진입점이 `exportfs -ra`로 적용하므로(`entrypoint.sh:38`) 재시작에도 줄이 남는다. 이 파일은 LVM 상태(볼륨 + 그 스냅샷)에서 언제든 다시 만들 수 있다.

#### (7) 스냅샷 삭제와 볼륨 연쇄 삭제 — `flexvol.py:157-179`, `:220-235`

- `delete_snapshot`: **export 줄 제거(`_write_exports` + `exportfs -ra`) → 인스턴스 안 `unlock_filesystem` → 호스트 `umount` 재시도 → `chattr -i; rmdir; chattr +i` → `lvremove`** (결정 13). 클라이언트가 스냅샷 안에 cwd나 열린 파일을 두고 있어도 export를 빼고 knfsd가 잡은 상태를 `unlock_filesystem`(`nfs_instance.py:146-151`)으로 풀면 내릴 수 있다 (S4 E4). `_umount`(`flexvol.py:323-328`)는 0.5 s 간격으로 60 s까지 다시 시도한다. 없는 스냅샷은 성공이다(ONTAP은 `1638600`을 돌려주므로 클론 차이다).
- `delete`(볼륨): **인스턴스 제거 → 스냅샷마다 umount·`lvremove` → 볼륨 umount → 마운트 지점 → export 디렉터리 → 볼륨 LV** (`:157-179`). 스냅샷 마운트가 볼륨 마운트 아래에 있어서 스냅샷이 먼저여야 한다. 반대로 하면 볼륨 umount가 `busy`로 실패한다 (설계 결정 13).

#### (8) 시작 복구 — `recover`, `flexvol.py:114-134`

순서는 aggregate → `ns` 공유 → (볼륨마다) 볼륨 마운트 → `.snapshot` 보장 → 스냅샷 마운트 → export 파일 쓰기 → 인스턴스 **시작**이다. 인스턴스는 **모두 띄운 뒤**(`:133-134`) 준비를 기다린다. 죽은 NFSv4.1 클라이언트 기록이 있는 인스턴스마다 유예 기간(약 45~60 s)을 기다리는데, 하나씩 기다리면 볼륨 수만큼 늘어나기 때문이다 (결정 14). 이를 위해 `NfsInstances.ensure`를 `start`와 `wait_ready`로 나눴다(`nfs_instance.py:89-117`, 설계 §9 5).

### 3.1 볼륨 결함 수정: NFSv4.1 인스턴스 재시작 (설계 결정 1, S4 G)

스냅샷 구현 도중이 아니라 설계 전에 S4 스파이크에서 찾은 **기존 볼륨 기능의 결함**이다. 인스턴스 시작 경로(진입점 `entrypoint.sh`, `nfs_instance.py`)를 스냅샷 export 때문에 어차피 바꿔야 해서 별도 사이클로 나누지 않고 이번에 고쳤다 (사용자 선택). 그래서 볼륨(과 공통 코드를 쓰는 계정·풀)을 `in_progress`로 되돌리고 AC-14로 회귀 검증했다.

- **증상 (S4 E5).** NFSv4.1 클라이언트가 마운트를 유지한 채 인스턴스를 `docker stop`·`docker start`하면 진입점이 "NFSv4 client tracking did not start"를 5번 찍고 exit 1로 끝난다. 그 볼륨은 서비스되지 않는다.
- **원인.** 인스턴스의 nfsdcld DB에 이전 부팅의 클라이언트 기록이 남아 있다. 커널은 이 클라이언트들이 상태를 되찾도록 **정상적인 유예 기간**(grace period)을 돈다. 그런데 진입점은 `rpc.nfsd` 뒤 `v4_end_grace`가 `N`이면 모두 "추적 시작 실패"로 보고 1초 뒤 knfsd를 다시 띄웠다. 클라이언트가 되찾을 틈이 없으니 계속 `N`이고, 5번 뒤 포기한다. 볼륨 1회차 검증의 AC-12(c)는 클라이언트가 마운트를 풀고 끝난 뒤 재시작해서 이 경우를 만나지 않았다. 현실 시나리오는 WSL 재시작이다: 클라이언트가 깔끔히 언마운트하지 못하면 기록이 남고, 다음 agent 시작의 복구에서 그 NFSv4.1 볼륨이 살아나지 않는다 [추론, S4 G3이 같은 조건을 만든다].
- **수정** (`entrypoint.sh:26-29`, `:41-84`):
  1. **정상 유예 기간과 추적 실패를 구분한다.** `reclaimable()`(`:44-48`)이 nfsdcld DB(`/var/lib/nfs/nfsdcld/main.sqlite`)의 `grace.recovery`(되찾을 시대) 기록 표에서 클라이언트 수를 센다. 기록이 있으면 정상 유예 기간으로 보고 `v4_end_grace`가 `Y`가 될 때까지 기다린다(`:62-75`). 기록이 없을 때만 예전처럼 knfsd를 내렸다 다시 띄운다(`:76-83`, 추적 시작 실패는 볼륨 1회차 검증에서 시작의 7~8%였다). 이를 위해 이미지에 `sqlite`를 더했다 (`nfs_server/Dockerfile`).
  2. **lease·grace를 ONTAP 기본 30 s / 45 s로 둔다** (`:28-29`). knfsd 기본값은 90 s / 90 s다. ONTAP 기본값은 `vserver nfs modify`의 `-v4-lease-seconds`, `-v4-grace-seconds` 문서에서 가져왔다 (S4). 죽은 클라이언트 기록이 있을 때의 대기가 100 s에서 줄어든다.
  3. 대기 상한을 늘렸다: 진입점은 100 s(`:66`), agent의 준비 대기는 60 s → 150 s (`nfs_instance.py:33-34`, `READY_ATTEMPTS = 300` × 0.5 s).
- **잰 시간** (설계 §9 6, 검증 AC-15):

| 조건 | 시간 | 근거 |
| --- | --- | --- |
| 살아 있는 v4.1 클라이언트가 마운트를 유지한 채 인스턴스 재시작 | 통합 **20.1 s**, e2e **18.8 s**(R6) 뒤 준비 (다른 회차 20.2, 20.8 s). 클라이언트는 다시 마운트 없이 계속 읽고 썼다 | 20 s는 Linux NFS 클라이언트의 lease 갱신 주기(lease의 2/3 = 20 s)와 맞는다. 클라이언트가 다음 갱신 때 서버 재시작을 알아채고 상태를 되찾자 유예가 바로 끝났다 [추론] |
| 클라이언트가 사라지고 기록만 남은 채 재시작 | 통합 **47.4 s**, e2e **51.0 s**(agent 시작 기준, 유예 46 s) 뒤 준비. 그 뒤 새 클라이언트가 0.9 s에 마운트해 썼다 | grace 45 s + 판정 간격. 예전 100 s(S4 G3, knfsd 기본 90/90)에서 줄었고 agent 준비 대기 150 s 안이다 |
| 예전, 살아 있는 클라이언트 (S4 G1, 시제품) | 3.85 s | lease가 90 s였을 때. 이번에 30 s로 줄여서 20 s로 늘었다는 해석은 [추론] |

- **볼륨 동작이 바뀐 점.** (a) 인스턴스는 lease 30·grace 45로 돈다. 이는 검증 AC-15(c)가 확인했다 (`/proc/fs/nfsd/nfsv4leasetime`·`nfsv4gracetime` = 30, 45). (b) NFSv4.1 볼륨이 WSL 재시작 뒤에도 복구된다(AC-12b에서 v3·v4.1 볼륨 모두 다시 읽힘, v4.1 인스턴스는 knfsd 재시작 1회). (c) 인스턴스가 준비되는 데 최대 150 s가 걸릴 수 있다. 볼륨 생성 시간이 달라졌는지는 이번 검증에서 따로 재지 않았다 [미확인].

### 설계 결정

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 스냅샷 = 읽기 전용 thin 스냅샷 LV (`-p r`, `-kn`), 메타데이터는 LVM 태그 (결정 5) | 스냅샷 메타데이터를 agent DB에 두기, `lv_time`을 생성 시각으로, 쓰기 가능 스냅샷 | agent에는 DB가 없다. `lv_time` 형식은 설정마다 다르다. 불변성이 마운트 옵션에만 기대면 안 된다 |
| 스냅샷마다 `fsid=<스냅샷 uuid>`로 따로 export (결정 6) | 부모 `crossmnt`만, 스냅샷 ext4 UUID를 `tune2fs -U`로 바꾸기 | 부모만으로는 Stale file handle (S4 E1). UUID를 바꾸면 `metadata_csum` 때문에 메타데이터를 다시 써서 즉시 스냅샷이 아니게 된다 [추론, 시험 안 함] |
| export 표는 볼륨마다 파일 하나, agent가 LVM 상태에서 다시 만든다 (결정 7) | 스냅샷마다 `docker exec exportfs -o`, 시작 뒤 agent가 다시 export | 인스턴스 재시작 때 진입점이 export를 비워 ELOOP (S4 E5). 파일이면 재시작·복구 후에도 줄이 처음부터 있다 |
| `.snapshot`은 늘 있고 `chattr +i` (결정 8) | 평범한 디렉터리, 읽기 전용 tmpfs | 평범한 디렉터리면 root 클라이언트가 `.snapshot` 안에 파일을 만들거나 `mv .snapshot`으로 스냅샷 마운트째 옮겼다 (S4 E3). tmpfs는 파일시스템 경계와 export가 하나씩 더 는다 |
| 삭제 순서: export 제거 → unlock → umount → rmdir → lvremove (결정 13) | 스냅샷 LV를 볼륨 LV 뒤에 지움 | 스냅샷 마운트가 볼륨 아래에 있어 볼륨 umount가 먼저 실패한다. 클라이언트가 안에 있어도 unlock으로 내릴 수 있다 (S4 E4) |
| 볼륨 DELETE가 스냅샷도 지움 (결정 2) | `409 CannotDeleteResource` (계정·풀 방식) | ANF 문서가 "deleted with the volume deletion"이라 쓴다 [문서]. 단 실서비스 응답 코드와 스냅샷이 `Deleting`을 거치는지는 [미확인] |
| 같은 이름 PUT은 `200` + `Updating`, 비동기 `UPDATE` (결정 3) | `200` 동기, `409` | `Failed` 스냅샷을 고칠 길이 필요하고(처리기가 멱등), ARM PUT의 멱등성과 맞는다. **근거 없는 선택**이다 |
| `snapshotId`는 anf-api가 만든 uuid4, agent POST에 `uuid`로 넘김 (결정 9) | agent가 uuid를 정하고 `GET ?name=`으로 읽기 | 재시도 때 "이름 중복"이 내 요청인지 남의 것인지 구분해야 한다. 볼륨 `fileSystemId`와 같은 방식이 단순하다. ANF는 백엔드 uuid로 보이므로 ANF와는 다르다 (4절) |
| 이름 규칙 `^[a-zA-Z0-9][a-zA-Z0-9\-_.]{0,254}$` (결정 10) | 볼륨 이름 규칙 재사용, 검사 없음 | 이름이 `.snapshot/<이름>` 디렉터리와 export 경로가 되므로 `/`, 공백, `.`·`..`를 막는다. 정책 스냅샷 이름(`daily.2020-05-14_0013`)의 `.`은 허용해야 한다. 길이 255는 ext4 파일 이름 한도다. ARM 스펙에 패턴이 없어 이 규칙 자체는 클론 규칙이다 [스펙] |
| 시작 복구에서 인스턴스를 모두 띄운 뒤 기다림 (결정 14) | 볼륨마다 시작하고 기다림 | 볼륨 N개면 최대 N × 60 s |
| 볼륨 결함을 이번 사이클에 고침 (결정 1, 사용자 선택) | 별도 버그 수정 사이클, 알려진 결함으로 기록만 | 같은 진입점·`nfs_instance.py`를 어차피 바꾸므로 회귀 검증을 두 번 하게 된다. FR-06(되돌리기)도 이 경로를 쓴다 |

---

## 4. 실제 ANF와 다른 점

### 4.1 설계 결정 16의 (1)~(6)

| # | 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- | --- |
| (1) | NFSv4.1에서 `.snapshot` 목록 | v4.1 목록에서 숨기고 이름으로만 들어가게 한다 [문서] | v3·v4.1 모두 볼륨 루트 `ls -a`에 `.snapshot`이 보인다 (검증 AC-03) | 클론은 v4.1 목록 숨김을 만들지 않았다. 데이터 효과(읽기, 접근)는 같다. FR-05 수락 기준에 필요 없었다 |
| (2) | `.snapshot`의 위치 | ONTAP은 볼륨의 모든 디렉터리에서 접근된다 [문서] (NFSv3 `ls`에 보이는 곳은 마운트 지점뿐 [문서, KB 요약]) | 볼륨 루트에만 있다. 하위 디렉터리의 `d/.snapshot`은 `No such file or directory` (S4 E3b) | 스냅샷을 스냅샷 LV의 마운트 지점으로 노출하는 방식이라 디렉터리마다 만들 수 없다 |
| (3) | 스냅샷 안의 `.snapshot` | 스냅샷 안에서 `.snapshot`이 다시 보이는지는 [미확인] | 스냅샷 안에 `.snapshot`이 빈 디렉터리로 보이고, 그 시점에 있던 스냅샷 이름의 빈 디렉터리가 보인다 (S4 E3b 관찰. 이번 검증에서 따로 확인하지 않았다) | 스냅샷이 원본의 시점 사본이라 그때의 `.snapshot` 디렉터리가 그대로 들어 있다 (설계 결정 8, 16) |
| (4) | 스냅샷 공간 | 볼륨 할당량에 들어간다 [문서] | 씬 풀(aggregate)에서 나가고 볼륨 할당량과 클라이언트 `df`에 잡히지 않는다 (검증 AC-02: 풀 +69730304 B, `df` 불변). 스냅샷이 커져도 볼륨은 안 차고 대신 씬 풀이 찰 수 있다 (R-09) | dm-thin의 성질. 할당량 계산에 스냅샷을 넣으려면 풀 사용량을 읽어 쓰기를 막는 별도 구현이 필요하다 |
| (5) | 스냅샷 안 쓰기 오류 | 클라이언트 errno는 [미확인] | 쓰기는 모두 실패하고, 호스트에서 본 스냅샷 파일 sha256, 목록, mode가 그대로다. errno는 버전과 클라이언트 상태에 따라 다르다. v4.1: 스냅샷 안 쓰기 7종(덧붙이기, `dd conv=notrunc`, 새 파일 `touch`, `rm`, `mv`, `mkdir`, `chmod`)이 모두 `EROFS`(Read-only file system). v3: 이미 있는 파일을 쓰기용으로 여는 둘(덧붙이기, `dd`)은 클라이언트가 그 파일을 아직 모르면 `EROFS`, `cat`·`stat`·`ls -l`로 이미 본 파일이면 `EACCES`(Permission denied)다. `O_CREAT` 없이 열면(`dd conv=nocreat`) 처음이어도 `EACCES`다. 나머지 다섯은 `EROFS`. `.snapshot` 자체 조작(파일 만들기, `mkdir`, `mv .snapshot`, `chmod`)은 `EPERM`(immutable). `rmdir .snapshot/S`는 `EBUSY`(마운트 지점) | 거절은 늘 서버의 읽기 전용(스냅샷마다 `ro` export 줄, `ro,noload` 마운트)에서 나온다. 갈리는 것은 errno를 누가 정하느냐다. v3 클라이언트는 모르는 파일을 `O_CREAT`로 열면 LOOKUP 없이 CREATE를 보내고(커널 `nfs_atomic_open_v23`), 서버가 `NFS3ERR_ROFS`로 거절한다. 아는 파일이면 ACCESS 응답에 쓰기 비트가 없어 클라이언트가 스스로 `EACCES`를 내고, 쓰기 RPC는 나가지 않는다. v4.1은 OPEN이 늘 서버로 가서 `NFS4ERR_ROFS`다. 클라이언트 RPC 카운터로 재현했다 (설계 §9 10). S4 E3의 `EACCES`와 검증 1회차(AC-04는 첫 접촉이 덧붙이기다)의 `EROFS`는 각각 한쪽 경우다 |
| (6) | `snapshotId` | 백엔드 uuid로 보인다. 녹화 값이 v4 모양이 아니다 [녹화][추론] | anf-api가 만든 uuid4 | 스펙 설명("UUID v4")에는 맞는다. 백엔드(ONTAP) uuid를 쓰려면 agent가 uuid를 정해야 하는데 멱등 키로 쓰기 어렵다 (결정 9) |

### 4.2 그 밖의 차이와 한계

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 생성 시간 | 약 2~3초 [녹화] | 1.10~1.15 s | 로컬 thin 스냅샷 |
| 응답 코드 (클론 규칙) | 255개 초과, 볼륨이 `Succeeded` 아님, 볼륨 없음, 볼륨 `Deleting` 때의 코드는 [미확인] | 400 `BadRequest`(255 초과, `Succeeded` 아님), 404 `ParentResourceNotFound`, 409 `Conflict` | 설계 결정 11. ANF 코드가 확인되지 않은 규칙은 클론 규칙으로 정했다 |
| 같은 이름 PUT | [미확인] | `200` + `Updating` 비동기 | 결정 3. 근거 없는 선택 |
| 볼륨 DELETE | 문서상 스냅샷도 함께 삭제 [문서], 실응답 [미확인] | 연쇄 삭제. 스냅샷 작업 중이면 409 | 결정 2 |
| PATCH | 스펙은 빈 본문에 200/202 [스펙] | `405` | `SnapshotPatch`가 빈 모델이라 바꿀 속성이 없다. 이번 범위 밖 |
| `snapshotDirectoryVisible: false` | 지원 | 볼륨 PUT에서 `400` | 결정 4. ANF 문서 둘이 의미를 다르게 쓴다 |
| `a/b`, `a%2Fb` 이름 | [미확인] | 경로 세그먼트가 늘어 `404 {"detail":"Not Found"}`(FastAPI 기본 본문, ARM 오류 형식이 아님) | 설계가 "404 가능, 기록"으로 허용했다 (AC-07) |
| 스냅샷이 남은 볼륨 삭제 | — | 같은 `creationToken`으로 다시 만든 볼륨의 `.snapshot`은 비어 있다 | 연쇄 삭제가 스냅샷 LV·마운트·export 디렉터리를 모두 치운다 (AC-10) |
| 복원, 되돌리기, 정책 | 있음 | 없음 (FR-06, FR-07, FR-17, `restoreFiles`) | 다음 사이클 |

---

## 5. 검증

real-env-verifier 1회차, 2026-11-08. **PASS 15 / FAIL 0 / UNVERIFIED 0.** 재검증 회차는 없다. 제품 코드 내용 해시는 시작과 끝이 `f5607a08…`로 같고 검증 대상 커밋과 같다.

| AC | 결과 | 증명한 것과 측정값 |
| --- | --- | --- |
| AC-01 생성 계약 | PASS | PUT 201 `Creating`(두 헤더), `Succeeded`까지 1.13 s. GET에 UUID v4 `snapshotId`, ISO `created`, 4단 `name`, `tags` 없음. 빈 목록 `{"value": []}`. LV attr `Vri-aotz--`(읽기 전용 thin) |
| AC-02, AC-03 NFSv3, NFSv4.1 | PASS | 지운 파일 A, 덮어쓴 `d/B`를 `.snapshot/S/`에서 이전 내용으로 읽음. `ls -a`에 `.snapshot`, `stat` 장치 번호가 다름. 다른 클라이언트도 같은 내용. 씬 풀 +524288 B(생성), 64 MiB 덮어쓰기 뒤 +69730304 B, `df` 불변 |
| AC-04 불변 | PASS | v3·v4.1 root 클라이언트의 쓰기 7종이 모두 실패(이 테스트 순서에서는 모두 `EROFS`. v3는 순서에 따라 `EACCES`도 나온다, 4.1절 (5)), `.snapshot` 조작 `EPERM`, `rmdir .snapshot/S` `EBUSY`. 호스트 sha256·mode·`lsattr`(`i` 속성) 그대로 |
| AC-05 시점 | PASS | S1/S2/활성 = one/two/three. 900 MiB `dd`(34.4 s) 도중 S3 생성(Succeeded 4.04 s), `dd` rc 0, S3 `e2fsck -fn` rc 0 |
| AC-06 DELETE | PASS | cwd·열린 fd를 쥔 클라이언트가 있는 스냅샷 DELETE: 202 → `Succeeded`(약 3 s) → GET 404 → 다시 DELETE 204. 모든 클라이언트에서 `No such file or directory`, 다른 스냅샷은 그대로, 호스트에 LV·마운트·export 줄 없음 |
| AC-07 거절 | PASS | 이름 5종 400, 본문 4종 400, 없는 볼륨 404, `Deleting` 볼륨 409, `Creating` 볼륨 400, PATCH 405. 작업·LV 변화 없음. 255개 한도는 계약 테스트(가짜 agent) |
| AC-08 재전송 PUT | PASS | 200 `Updating` → `Succeeded`(UPDATE). `snapshotId`·`created` 그대로, LV 하나, 내용은 첫 시점. 다른 location은 409 |
| AC-09 진행 중 충돌 | PASS | 생성 지연 중 PUT·DELETE `409 AnotherOperationInProgress`, 볼륨 DELETE `409 Conflict`. 원래 작업은 `Succeeded` |
| AC-10 볼륨 연쇄 삭제 | PASS | 클라이언트 cwd가 스냅샷 안인 볼륨 DELETE가 약 2 s에 `Succeeded`. 볼륨·스냅샷 404, LV·마운트·export 디렉터리·인스턴스·DB 행 없음 |
| AC-11 실패와 회복 | PASS | 주입 실패 → `Failed`, LV 없음 → 같은 PUT이 `Succeeded`. agent 정지 60.3 s 뒤 `Failed` → agent 시작 뒤 PUT `Succeeded` |
| AC-12 재시작 복구 | PASS | (a) 생성 중 anf-api SIGKILL → 재시작 뒤 `Succeeded`, LV 하나. (b) agent·인스턴스 정지, 스냅샷·볼륨 umount(WSL 재시작 흉내) 뒤 agent 시작 3.9 s: v3·v4.1 스냅샷이 모두 다시 읽힘 |
| AC-13 agent API | PASS | POST 202 → success, 재전송 success, 같은 name 다른 uuid failure, `?name=` 필터, 없는 uuid DELETE success, 잘못된 입력 400 |
| AC-14 회귀 | PASS | 계정·풀 live e2e 63개(CI 재현 725 passed, skip 0), 볼륨 e2e 21개, 통합 10개 |
| AC-15 v4.1 인스턴스 재시작 | PASS | lease 30·grace 45 확인. 살아 있는 클라이언트 18.8~20.8 s, 기록만 남은 경우 51.0 s(agent 시작) |

- **관찰: knfsd 첫 시도 추적 실패율이 약 30%였다 — "알려진 위험"으로 다룬다.** 진입점이 `v4_end_grace = N`이고 되찾을 기록이 없어서 knfsd를 한 번 내렸다 다시 띄운 비율이 R1 8/25(32%), R2 12/36(33%)였다. 볼륨 2회차 보고서는 5/64(7.8%)였다. 모두 2회째에 성공했고 `giving up`은 0이다.
  - **이번 변경 때문인지 A/B로 가렸다 (R9).** tmpfs export 하나로 main(`b84c7a9`)의 진입점 이미지와 현재 이미지를 번갈아 20회씩 띄웠다. 재시작은 **main 7/20, 현재 6/20**으로 차이가 없다. 재시작은 실행 중반에 몰렸고 마지막 14회는 둘 다 1회 시도였다. 그래서 이번 진입점 변경(lease/grace echo, `exportfs -ra`)과 무관하고 환경 상태에 따라 비율이 변하는 것으로 보인다 [추론].
  - **위험.** 5회 연속 실패하면 진입점이 exit 1을 하고 볼륨이 `Failed`가 된다. 비율이 30%라면 0.3^5 ≈ 0.24%다. 이번 회차에는 일어나지 않았다. 시도 횟수나 판정 방식을 바꿀지는 별도 작업으로 본다 (진행 기록 "후속 후보").
- **관찰: 볼륨 AC-09 앞 단계의 `dd conv=fsync`가 4회 중 1회 `I/O error`**였다. 스냅샷 코드 경로가 아니라 soft 마운트의 짧은 `timeo` 때문으로 추정한다 [추론]. 재실행 3/3 통과.
- **관찰: `docker rm -f` 실패.** 서버가 없는 동안 NFS 마운트를 가진 클라이언트 컨테이너, 클라이언트 없이 SIGKILL한 서버 컨테이너가 "did not receive an exit event"로 지워지지 않는 일이 있었다(R9에서 40회 중 5회). 이때 다음 인스턴스 준비가 42~48 s 걸렸다. agent는 `docker stop -t 30` 뒤 `docker rm`을 쓰므로(`nfs_instance.py:124-126`) 이 경로를 타지 않는다 (검증 보고서 관찰 3). 환경·커널 동작으로 기록한다.
- **테스트를 고친 두 군데.** 볼륨 e2e AC-09의 `ls -A` 기대값을 `listed`에서 `.snapshot\nlisted`로(결정 8의 의도된 결과), 볼륨 AC-12b의 job 시작 표시 문자열을 새 로그 문구로. 후자는 `accepted()`가 볼륨·스냅샷 경로를 합치면서 로그 문구가 바뀐 결과다. 로그는 API 계약이 아니라서 문구를 되돌리지 않았다 (설계 §9 9).
- **AC-15 테스트 전제를 두 번 고쳤다.** 1회차(R1)에서는 hard 마운트 클라이언트의 `docker rm -f`가 실패해 컨테이너가 남았고, 서버가 돌아오자 그 클라이언트가 5 s 만에 상태를 되찾았다. "기록만 남은 클라이언트"라는 전제가 깨져서 R1 결과를 판정에 쓰지 않았다. 최종 테스트는 컨테이너 제거가 아니라 **서버에서 관찰한 것**(nfsdcld 기록 1개 이상, `grace period: waiting for` 줄, 대기 30 s 이상)으로 전제를 판정한다. R6에서 통과했다.
- **NFSv4.1 `ls`에서 `.snapshot` 숨김은 검증하지 않았다.** 클론이 보이는 쪽이 4절 (1)의 차이다.

---

## 6. 개발 과정

1. **조사.** anf-researcher가 스냅샷 API 계약과 녹화(R1~R6), ONTAP REST 스냅샷 API, `.snapshot` 옵션(`-snapdir-access`, `-v3-hide-snapshot`), 공간(reserve), 볼륨 삭제 시 스냅샷을 조사했다. 첫 조사가 30턴 한도에 닿아 ONTAP REST와 볼륨 DELETE, `.snapshot` 옵션만 보완 조사했다(보완 1~3). 같은 이름 PUT의 ARM 응답은 끝내 못 찾았다(보완 4 부분). 설계를 막지 않는다고 판단해 클론 규칙으로 정하고 차이를 기록하기로 했다.
2. **스파이크 S4.** 조사와 병행해 메인 세션이 시험했다. S1(호스트 knfsd에서의 스냅샷)이 통과했지만, D-12로 export가 볼륨 인스턴스(컨테이너 netns의 knfsd) 안으로 옮겨졌고 볼륨 구현 중 "v3 클라이언트가 하위 마운트로 넘어가면 Stale file handle"이 관찰돼 있었다. S4가 **부모 `crossmnt`만으로는 v3·v4.1 모두 Stale file handle**이고 스냅샷마다 자기 `fsid`가 필요함, `.snapshot`을 평범한 디렉터리로 두면 root 클라이언트가 `mv`로 옮긴다는 것(그래서 `chattr +i`), 인스턴스 재시작 때 export가 사라져 export 표를 파일로 둬야 한다는 것을 밝혔다. 그리고 **볼륨 기능의 결함**(NFSv4.1 재시작 불가)을 발견했다. 스파이크를 설계 전에 한 이유가 이것이다: 노출 방식이 틀렸다면 설계 전체가 틀어졌을 것이다.
3. **설계.** 기본안(결정 5~16)과 선택지 네 가지를 사용자에게 제시했다. **사람이 내린 결정**(모두 추천안): 볼륨 결함을 이번 사이클에 고침(결정 1), 볼륨 DELETE가 스냅샷을 함께 지움(결정 2), 같은 이름 PUT은 `200` + `Updating` 비동기(결정 3), `snapshotDirectoryVisible`은 계속 미룸(결정 4). 결정 1 때문에 볼륨·계정·풀을 `in_progress`로 되돌리는 **무효화 규칙**이 적용됐다.
4. **구현.** Claude가 TDD 훅 아래서 구현했다. 두 커밋으로 나눴다: storage agent(`a2a819e`, 통합 테스트 10 passed)와 anf-api(`27757aa`, 계약 테스트 26개를 먼저 RED로 확인, 전체 662 passed, 94 skipped(실환경·root), ruff 통과). 구현 중 설계와 달라진 것이 9가지 있다(설계 §9): export 줄을 `nfs_instance.py`가 만든다(NFS export 옵션은 인스턴스 쪽 지식이다), export 파일은 늘 다시 쓰고 `exportfs -ra`한다(적용 실패를 놓치지 않으려고), `.snapshot`의 immutable은 `lsattr`로 확인한다, 오프라인 볼륨에는 스냅샷을 만들지 않는다, 인스턴스 시작과 준비 대기를 나눴다, 잰 시간(20.1 s / 47.4 s), 볼륨 DELETE 409 문구, errno 정정(검증 단계), 로그 문구 변경.
5. **검증 1회차.** PASS 15 / FAIL 0 / UNVERIFIED 0. 검증자(구현자와 다른 에이전트)는 제품 코드를 고치지 않고 e2e 테스트(`snapshot_live.py`와 `test_snapshot_{contract,data,recovery}_live.py`, 18개)를 썼다. 테스트 전제를 둘 고쳤다(AC-15, 볼륨 e2e 두 줄). 전체 실행 `18 passed in 529 s`(스냅샷 e2e). 개인적으로 가장 중요한 점은 검증자가 **"통과했지만 전제가 무효인 테스트"**(AC-15 R1)를 찾아 판정에서 뺐다는 것이다. 리더 판단: 로그 문구는 되돌리지 않고 테스트 수정을 받아들임, errno는 관찰값으로 바로잡음(설계 §9 8~9).
6. **개념 문서(이 문서).** 이 사이클에서 push·PR은 이 문서 뒤에 한다 (진행 기록의 사용자 지시).

AI와 일한 방식으로 설명할 수 있는 것: 조사 → 스파이크(설계 전에 데이터 플레인 사실을 재고 설계를 바꿈) → 설계(사람이 선택지를 결정, 무효화 규칙 적용) → 테스트 먼저 구현(TDD 훅) → 구현자와 다른 에이전트의 실환경 검증(검증자는 테스트만 만들고 제품 코드는 고치지 않음) → 개념 문서. 이번에는 **스파이크가 기능 밖의 기존 결함까지 찾았고**, 검증자가 설계 문서와 다른 errno를 관찰로 짚었다는 점이 중요하다. 그 차이는 뒤에 v3 클라이언트의 캐시 상태 때문으로 밝혀졌다(4.1절 (5)).

---

## 7. Interview Q&A

### Q1. (개념) How does an Azure NetApp Files snapshot look to a client, and how does it map to ONTAP?

**A.** A snapshot is a child ARM resource of a volume, and also a read-only point-in-time copy that NFS clients read under `.snapshot/<name>/`. The create call returns 201 with `Creating`, and the `snapshotId` and `created` fields appear after completion, which is what the recordings show. ANF's docs describe snapshots as Redirect on Write: they preserve block pointers and do not copy data blocks, so creation costs almost no space and later you pay only for changed blocks. The closest ONTAP object is a volume Snapshot copy, with a REST API under `/api/storage/volumes/{uuid}/snapshots`. I should be careful, though. No public document says ANF's snapshot is exactly an ONTAP Snapshot copy, so I call the mapping an inference.

### Q2. (개념) Why is a snapshot created instantly, and how does your clone get the same effect?

**A.** ANF's docs say snapshots only preserve block pointers, so nothing is copied at creation time. In my clone, a snapshot is a read-only dm-thin snapshot logical volume. It shares blocks with the origin, and when the origin is written, the thin pool allocates a new chunk for it. I measured this. Right after creating a snapshot, the thin pool grew by one 512 KiB chunk, and after overwriting a 64 MiB file, it grew by about 66 MiB, while the client's `df` stayed unchanged. Creation took about 1.1 seconds. The mechanism is block-level copy-on-write, not ONTAP's pointer redirect, so I say the effect matches, not the implementation. Calling it WAFL is something I did not verify from my sources.

### Q3. (설계) Why did you export every snapshot with its own `fsid` instead of relying on the parent export's `crossmnt`?

**A.** Because the parent-only approach failed in a spike. With only `crossmnt` on the volume export, both NFSv3 and NFSv4.1 clients got `Stale file handle` on the snapshot directory. A thin snapshot of an ext4 volume has the same filesystem UUID as its origin, so I believe the automatically generated sub-export collided with the parent's fsid. That is my inference; I did not prove it. Exporting each snapshot with `fsid=<snapshot uuid>` fixed both protocols. I also keep the export table in a file that the instance reads at start, because with a `docker exec exportfs` approach the entrypoint's shutdown cleared the snapshot exports, and clients saw a symbolic link loop after a restart.

### Q4. (설계) Why does deleting a volume delete its snapshots, and how did you implement it safely?

**A.** ANF's docs say online snapshots are part of the volume and are deleted with it, so I chose cascade delete over rejecting with 409 like pools do. I could not confirm the real response code, so it is a documented inference. The agent deletes in a fixed order: remove the instance, then each snapshot's mount and LV, then the volume mount and LV. The snapshot mounts sit under the volume mount, so reversing it fails with `busy`. In anf-api, one transaction removes the volume row and its snapshot rows. If any snapshot has an operation in flight, the volume DELETE returns 409. I verified it with a client whose working directory was inside a snapshot; the delete finished in about two seconds and left no LV, mount, or export.

### Q5. (트레이드오프) Where does your snapshot behavior differ from real ANF?

**A.** Four differences matter most. First, space: ANF counts snapshot space against the volume quota, while mine comes from the thin pool, so a growing snapshot never fills the volume but can fill the pool. Second, visibility: `.snapshot` appears in `ls -a` over NFSv4.1 in my clone, while ANF hides it there, and it exists only at the volume root, while ONTAP serves it in every directory. Third, `snapshotId`: ANF's recorded values are not UUID v4, so I think it exposes the backend UUID, but mine is a v4 UUID generated by anf-api. Fourth, the errno: writes inside a snapshot fail with `EROFS`, except that an NFSv3 client gets `EACCES` when it opens a file it has already looked up; `.snapshot` itself gives `EPERM`, and `rmdir` gives `EBUSY`. ANF's errno is unconfirmed. I mark each as a clone decision, not observed ANF behavior.

### Q6. (설계) How do you keep snapshot creation safe against crashes, and why does anf-api generate the snapshot ID?

**A.** anf-api generates the `snapshotId` at PUT time and sends it to the agent as the uuid, so it works as an idempotency key. The agent checks real state at every step: LV, `.snapshot`, mount, export file. Re-sending the same request resumes where it stopped. The same uuid with the same name succeeds, and the same name with a different uuid fails, with ONTAP's "already exists" message. Metadata lives in LVM tags, so no database can disagree with the system. I verified it by killing anf-api during a snapshot create; after restart the operation succeeded with exactly one LV. I also verified that `Failed` snapshots recover with the same PUT. The tradeoff is that the clone's ID is not the backend's ID, unlike real ANF.

### Q7. (디버깅) Tell me about the volume bug you found while building snapshots.

**A.** A spike found that an NFSv4.1 instance cannot restart while client records remain. The entrypoint looked at `v4_end_grace`, saw `N`, and treated it as a client-tracking failure, so it restarted knfsd five times and exited. But the kernel was actually running a normal grace period so clients could reclaim state, and my restart loop kept resetting it. The evidence was the nfsdcld database still holding client records. The fix: if the database has reclaimable records, wait for the grace period; restart only when there are none. I also set lease and grace to ONTAP's defaults of 30 and 45 seconds. Measured restart-to-ready time was about 19 to 20 seconds with a live client, and 47 to 51 seconds with only dead records. The earlier verification missed it because that test unmounted cleanly first.

### Q8. (한계/관측) During verification you saw knfsd restart about 30 percent of the time on first start. Is that your change?

**A.** No, and I checked it. In the first runs, about a third of instance starts needed a second knfsd attempt, versus 7.8 percent in the previous cycle's report. To see whether my entrypoint change caused it, I ran an A/B test: alternating the main branch's entrypoint image and the current one, 20 starts each. The restart count was 7 of 20 on main and 6 of 20 on mine, and the restarts clustered in the middle of the run. So the rate depends on environment state, which is my inference. The remaining risk is real: after five consecutive failures the entrypoint exits and the volume becomes `Failed`. At 30 percent that is about 0.24 percent per start. I recorded it as a known risk and a follow-up item.

### Q9. (테스트/REST) How did you test a feature that spans REST, an agent, and the kernel, and what did the verifier catch?

**A.** I used layers. Unit tests use a fake command runner for ordering. Contract tests check status codes, headers, and bodies with a fake agent; 26 of them were written first and confirmed red. Then a separate verifier ran real end-to-end tests on LVM, Docker, and knfsd, with NFS client containers. It judged by exit codes and full stderr, and it caught three things. A test whose precondition was invalid: a client container could not be removed, so the "dead client" was alive. An errno mismatch: my design said `EACCES` for NFSv3 writes, but the verifier saw `EROFS`. Later a client got `EACCES` again, so I counted the client's NFS RPCs. Both are real. An NFSv3 client that has not looked up the file sends CREATE, and the server rejects it as read-only. A client that already knows the file refuses on its own, because the ACCESS reply has no write bit. And two volume tests that depended on log wording. I fixed the tests and the document, not the product code.

### Q10. (다시 한다면) If you did this again, what would you do differently?

**A.** Three things. First, I would fix the knfsd first-attempt restart rate before shipping more features, because five consecutive failures turn a volume `Failed`, and I only quantified it, not removed it. Second, I would confirm the unknowns against real systems: ANF's response for re-PUT of an existing snapshot, the 256th-snapshot error code, and what real ANF does when you delete a volume that has snapshots. I chose those behaviors by inference. Third, I would add a quota-style check so snapshot growth cannot silently fill the thin pool, since ANF counts snapshot space against the volume. I would also record the client's state with each observation. The spike and the verifier reported different errnos for the same write, and the only difference was whether the NFSv3 client had already looked up the file.

---

## 부록. 이 문서가 쓰지 못한 것

브리프·스파이크·검증 보고서에 근거가 없거나 [미확인]이라 쓰지 못한 것이다.

- **WAFL이라는 이름과 ONTAP Snapshot copy의 내부 구조(포인터 복사, redirect-on-write)에 대한 ONTAP 쪽 원문.** 브리프는 ANF 문서의 "Redirect on Write" 표현과 ONTAP REST의 스냅샷 정의만 담고 있다. 클론 코드 주석(`flexvol.py:8`)의 "WAFL처럼"은 설명이지 브리프 근거가 아니다.
- **dm-thin이 청크 단위 CoW라는 설명의 원문.** S1 스파이크 본문에서 이 문장을 찾지 못했다. 청크 크기(512 KiB)는 직접 확인했고, 씬 풀 사용량이 청크의 정수배로 늘어난 측정(검증 AC-02, AC-03)과 맞는다. 공유와 새 할당이라는 메커니즘 자체는 커널 문서(`Documentation/admin-guide/device-mapper/thin-provisioning.rst`)로 확인하지 않아 [추론]으로 남겼다.
- 같은 이름 PUT 재전송, 255개 초과, 볼륨이 `Succeeded`가 아닐 때 생성, 없는 스냅샷 DELETE, 스냅샷이 남은 볼륨 DELETE의 ANF 실응답.
- 쓰기 시 ANF 클라이언트 errno.
- 스냅샷 안에서 `.snapshot`이 다시 보이는지(ONTAP, ANF). 클론의 관찰(4절 (3))은 S4 E3b에서만 확인했고 이번 검증에서 재확인하지 않았다.
- `snapshotDirectoryVisible: false`가 ONTAP의 어느 옵션에 대응하는지(ANF 문서끼리 충돌).
- 클라이언트 `df`에 스냅샷 사용량이 보이는 방식, ANF 내부 snapshot reserve 값.
- NetApp KB의 `.snapshot` 가시성 원문(WebSearch 요약만 확인).
- 같은 이름 PUT 재전송 응답 코드의 ARM 근거. 설계 결정 3은 근거 없는 선택이다.
