# 볼륨 (volume, NFS)

> ANF 볼륨은 풀 아래의 ARM 리소스이면서, 클라이언트가 `<IP>:/<creationToken>`으로 마운트하는 실제 NFS export다. 이 클론은 볼륨 하나를 thin LV + ext4(ONTAP FlexVol에 해당하는 자리)로 만들고, 볼륨마다 자기 네트워크 네임스페이스에서 도는 knfsd 인스턴스와 IP(data LIF에 해당하는 자리)를 준다. 이 기능이 처음으로 컨트롤 플레인(anf-api)이 데이터 플레인(storage agent)을 부르는 구조를 만들었고, 그래서 ARM의 비동기 작업 위에 ONTAP 모양의 비동기 job이 한 층 더 생겼다.

FR-04(볼륨)와 용량 풀 사이클에서 넘어온 기준 CV-1~CV-3을 다룬다. 대상 코드는 `main`의 `8a4002d`(PR #7, 제품 코드 내용 해시 `8bb57d91…`)이고, 검증한 해시와 같다. 공통 비동기 작업(LRO) 계층(작업 상태 URL, 워커, 재시작 복구, 결함 주입, 오류 형식)은 [계정 문서](netapp-account.md), 풀의 용량 규칙과 처리량 계산은 [풀 문서](capacity-pool.md)에 있다. 이 문서는 볼륨이 그 계층을 어떻게 쓰는지와, 볼륨 때문에 새로 생긴 것(storage agent, 저장 방식, NFS 서버 인스턴스)만 설명한다.

근거 표시는 브리프를 따른다.

| 표시 | 뜻 |
| --- | --- |
| [스펙] | Azure REST API 스펙(OpenAPI/TypeSpec)에 적혀 있다 |
| [문서] | Microsoft Learn이나 NetApp 문서에 적혀 있다 |
| [녹화] | Azure SDK 테스트 세션 녹화에서 실서비스 응답으로 관찰했다. 문서로 보장된 동작은 아니다 |
| [추론] | 근거에서 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |

---

## 1. ANF에서는

### 1.1 리소스와 API

- 볼륨은 풀 아래의 ARM 추적 리소스 `.../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}`다. 필수 속성은 `creationToken`(파일 경로, 생성 뒤 불변), `usageThreshold`(바이트, 50 GiB~100 TiB, 1 GiB 배수), `subnetId`다 [스펙]. 볼륨 이름은 `^[a-zA-Z][a-zA-Z0-9\-_]{0,63}$`다(풀과 달리 첫 글자가 영문자여야 한다) [스펙]. 응답의 `name`은 `"{account}/{pool}/{volume}"`이다 [스펙][녹화].
- 볼륨은 풀의 구독, 리소스 그룹, location을 물려받는다 [문서]. 구독·계정 범위의 볼륨 목록 경로는 없고, 풀 아래 목록만 있다 [스펙].
- **작업별 응답** (api-version `2026-08-01`, 녹화는 preview 버전으로 호출됨):

| 작업 | 응답 | 헤더 | 걸린 시간 | 근거 |
| --- | --- | --- | --- | --- |
| PUT 생성 | `201`, `Creating` | `Azure-AsyncOperation`만 (스펙은 `Retry-After`도 정의) | 약 5분 17초~5분 41초 | [녹화] |
| PUT 갱신 | `200`, `Updating` | `Azure-AsyncOperation` | 약 2.9초 | [녹화] |
| PATCH | `202`, `Patching` + 전체 본문 | `Azure-AsyncOperation` + `Location` | 약 2.6~3.1초 | [녹화] (스펙은 202 본문 없음) |
| DELETE | `202`, 본문 없음 | 두 헤더 | 73~106초 | [녹화] |
| 없는 볼륨 DELETE | `204` | 없음 | — | [스펙] |

  생성 중 .NET SDK의 폴링 간격은 1, 1, 2, 2, 5, 8, 16초를 거쳐 약 32초로 늘었다. ANF가 `Retry-After`를 주지 않기 때문이다 [녹화].
- **진행 중인 볼륨에 PUT을 보내면** 즉시 `409 RequestConflict`, "Cannot modify resource with id '…' because the resource entity provisioning state is not terminal. …"이다 [녹화]. 계정·풀의 `AnotherOperationInProgress`와 코드가 다르다.
- 없는 풀 아래 PUT은 `404 ParentResourceNotFound`, 볼륨이 남은 풀 DELETE는 `409 CannotDeleteResource`다 [녹화] (풀 브리프).

### 1.2 서비스가 채우는 값

- 기본 export 규칙 1개: `ruleIndex 1`, `allowedClients 0.0.0.0/0`, `unixReadWrite true`, `hasRootAccess true`, `chownMode Restricted`. 이 규칙은 201 본문에는 없고 완료 뒤 GET에 나타났다 [녹화]. 프로토콜 플래그(`nfsv3`, `nfsv41`)가 `protocolTypes`를 따른다는 것은 NFSv3 사례만 있어 NFSv4.1 쪽은 [추론]이다.
- `protocolTypes ["NFSv3"]`, `unixPermissions "0770"`(마운트 경로, 즉 볼륨 루트에만 적용), `snapshotDirectoryVisible true` [녹화][문서].
- `fileSystemId` = `mountTargets[0].mountTargetId` = `mountTargets[0].fileSystemId`(같은 UUID), `mountTargets[0].ipAddress`는 위임 서브넷 안 주소(녹화에서 `10.0.1.4`)다. 이 값들은 201 본문에는 없고 완료 뒤 GET에 있었다 [녹화].
- `actualThroughputMibps`: Auto QoS 풀에서 100 GiB Premium 볼륨은 6.25(= 100 GiB × 64 MiB/s/TiB)였고, 200 GiB로 PATCH하자 12.5가 됐다 [녹화]. 계산은 [풀 문서](capacity-pool.md)와 같다.

### 1.3 데이터 플레인에서 보이는 효과

- 마운트 경로는 `<마운트 대상 IP>:/<creationToken>`이다 [문서]. NFSv4.1은 `vers=4.1`을 명시해야 한다. 명시하지 않으면 클라이언트가 공식 지원이 아닌 4.2로 협상할 수 있다 [문서].
- 지원 프로토콜은 NFSv3와 NFSv4.1이다. CIFS와 NFS를 섞으면 "Not allowed to mix protocol types CIFS and NFS"다 [문서].
- **할당량.** 소비량이 할당량에 닿으면 볼륨도 풀도 자동으로 자라지 않고 볼륨이 "out of space" 상태가 된다 [문서]. 스냅샷이 쓰는 용량도 할당량에 포함된다 [문서]. 클라이언트가 받는 errno가 ENOSPC인지 EDQUOT인지는 [미확인]이다. 문서가 "quota"가 아니라 "out of space"라고 쓰므로 ENOSPC일 가능성이 높다 [추론].
- **`usageThreshold`의 의미에 출처끼리 모순이 있다.** 스펙 설명은 "soft quota used for alerting only"인데, Learn 문서는 "limited to the set size (quota) of the volume"이라고 쓰고 FAQ는 "hard volume quota"라는 표현을 쓴다. 실제 동작을 설명하는 쪽은 Learn 문서로 보인다 [추론].
- `creationToken` 유일성: "서브넷 안에서 유일"이다 [문서]. 중복이면 RP 오류 "File path already in use."가 난다 [문서]. 이 오류의 HTTP 코드는 [미확인]이다. 허용 문자는 출처마다 조금 다르다(밑줄 허용 여부). 녹화에서는 15자 토큰이 성공해서 오류 문서 제목의 "16자 이상"은 적용되지 않는다 [녹화].
- 같은 마운트 IP를 여러 볼륨이 공유할 수 있다 ([문서]의 `nconnect` 예는 IP 하나에 볼륨 세 개, [스펙]의 `networkSiblingSetId`는 "group of volumes sharing networking resources") [추론]. 어떤 조건에서 공유되는지는 [미확인]이다.
- 클라이언트 `df`가 보여 주는 크기가 할당량인지, 스냅샷 사용량이 들어가는지는 [미확인]이다.

---

## 2. ONTAP에서는

솔직한 요약은 **"ANF 볼륨이 ONTAP 볼륨 하나라는 직접 공개 근거는 찾지 못했다"**이다 [미확인]. 단서는 세 가지다. (1) 녹화의 `baremetalTenantId: "baremetalTenant_svm_<hex>_<hex>"`에 `svm`이 들어 있다 [녹화]. (2) ANF 스냅샷 문서의 "Redirect on Write", 포인터 기반 설명이 ONTAP의 스냅샷과 일치한다 [문서]. (3) 풀 브리프의 "NetApp's bare metal with ONTAP storage OS" 문구다. 이 단서로 보면 "볼륨 하나 = 테넌트 SVM 안의 ONTAP 볼륨 하나"는 그럴듯하지만 [추론]이다.

| ANF 개념 | ONTAP 개념 | 말할 수 있는 수준 |
| --- | --- | --- |
| 볼륨 | FlexVol 볼륨 | ONTAP REST `POST /api/storage/volumes`의 최소 예는 `name`, `svm.name`, `aggregates[].name`이다 [문서]. ANF 볼륨이 FlexVol이라는 직접 근거는 없다 [추론] |
| `creationToken` (파일 경로) | junction path (`nas.path`) | ONTAP에서는 볼륨이 SVM 네임스페이스의 junction path에 마운트되어야 클라이언트가 데이터를 볼 수 있다("A volume must include a junction path for its data to be made available to clients"). junction path는 255자 이하이고 `* # " > < \| ? \`를 쓸 수 없다 [문서]. ANF 마운트 경로 `<IP>:/<creationToken>`의 모양이 SVM 루트 바로 아래 junction과 같다 [추론] |
| 네임스페이스 | SVM 네임스페이스 | "Every SVM has a unique namespace. The SVM root volume is the entry point to the namespace hierarchy." [문서]. NFSv4 pseudo-fs의 ONTAP 원문은 받지 못했다 [미확인] |
| 마운트 대상 `ipAddress` | SVM의 data LIF | LIF 원문은 확인하지 못했다 [미확인]. 녹화의 `svm` 문자열을 근거로 한 [추론]이다 |
| `exportPolicy.rules[]` | export policy와 rule (`nas.export_policy`) | ONTAP 볼륨 GET 예에 `nas.export_policy`, `security_style`, `unix_permissions`가 있다 [문서]. ANF 규칙 필드가 ONTAP rule의 clientmatch, rorule/rwrule, superuser, protocol과 닮았다 [추론] |
| `unixPermissions`, `securityStyle` | `nas.unix_permissions`, `nas.security_style` | 같은 이름의 필드가 있다 [문서] |
| `usageThreshold` | 볼륨 `size` (quota는 별개) | ONTAP에는 볼륨 크기와 별도로 사용자·그룹·qtree quota가 있다 [문서]. ANF의 값이 어느 쪽인지는 공개되지 않았다 [미확인]. "out of space"라는 표현은 `size`에 가깝다 [추론] |
| 할당량 합 ≤ 풀 크기 | thin provisioning의 반대 (예약) | ONTAP thin provisioning은 공간을 미리 예약하지 않아 aggregate를 overcommit할 수 있다 [문서]. ANF 백엔드가 thin인지는 [미확인] |
| 비동기 작업 | ONTAP job (`/api/cluster/jobs/{uuid}`) | job `state`는 `queued`, `running`, `paused`, `success`, `failure`. 종료된 job은 기본 300초 뒤 삭제되고 그 뒤 GET은 404다 [문서] |
| 볼륨이 가득 참 | FlexVol fullness 경고 (EMS) | "full"은 활성 파일 시스템에 쓸 수 있는 공간의 비율이 임계값 아래로 떨어진 상태다 [문서]. NFS 클라이언트가 받는 errno 원문은 [미확인] |
| 처리량 제한 | QoS policy group (스토리지 계층) | ONTAP이 스토리지 계층에서 볼륨 단위 상한을 건다는 것은 [추론] (처리량 조사). 이 클론은 FR-08에서 네트워크 경계에서 건다 (D-12) |

**클론이 정한 비유 (공개 근거가 아니라 설계 선택이다).** 아래는 이 프로젝트가 ONTAP 어휘로 설명하려고 고른 대응이다. ANF가 내부적으로 그렇게 구현했다는 뜻이 아니다.

| 클론의 구성 | 비유한 ONTAP 개념 | 근거 |
| --- | --- | --- |
| dm-thin 씬 풀 `anf/aggr0` | aggregate | ONTAP 볼륨 생성이 `aggregates[].name`을 받는다 [문서]. aggregate의 정의 원문은 이번 조사에서 확인하지 못했다 [미확인] |
| thin LV `vol_<uuid>` + ext4 | FlexVol | 위와 같다 [추론] |
| `ns/` 디렉터리와 인스턴스 안의 `/export` (`rootdir`) | SVM 네임스페이스 | [문서]의 SVM 네임스페이스 설명 + 설계 결정 2 [추론] |
| `/<creationToken>` export 경로 | junction path | [문서] + [추론] |
| 볼륨 인스턴스의 IP | data LIF | [미확인] 개념에 대한 [추론]. ONTAP은 SVM 하나가 여러 볼륨을 서비스하지만 클론은 볼륨마다 인스턴스를 하나 둔다 |
| agent의 job (`/api/cluster/jobs/{uuid}`) | ONTAP job | [문서]: 상태 값과 300초 보관을 그대로 따랐다 |

`fsid`(export 옵션)에 대응하는 ONTAP 개념은 브리프에서 찾지 못했다. 이 문서는 그 대응을 쓰지 않는다. 클론에서 `fsid`는 Linux knfsd의 export 옵션이다(3절).

면접에서 안전한 문장: "ANF 볼륨의 파일 경로(`creationToken`)는 마운트 경로가 된다. ONTAP에서 이와 가장 닮은 것은 SVM 네임스페이스의 junction path다. ANF가 내부적으로 ONTAP 볼륨을 junction path에 마운트한다는 공개 문서는 없지만, 응답의 `baremetalTenantId`에 `svm`이 들어 있다."

---

## 3. 이 프로젝트에서는

### 구조

```
  클라이언트 (curl, SDK)                         NFS 클라이언트 (컨테이너)
     | PUT/PATCH/DELETE/GET .../volumes/{v}           | mount <볼륨 IP>:/<creationToken>
     v                                                 |
  anf-api (일반 사용자, :8080)                         |
   arm_app.py   볼륨 라우트 (201/200/202/204)          |
   volumes.py   본문 검사 + 부모/경로/용량 규칙         |
        |  한 트랜잭션: 리소스(Creating) + 작업 행     |
        v                                              |
   state_store.py (SQLite)  <--- lro.py 워커 (공통) ---+
                                  | 처리기 volumes.make_handlers
                                  v
   storage_client.py  ONTAP 모양 REST + job 폴링 (urllib, 스레드)
        | POST /api/storage/volumes -> 202 + job -> GET /api/cluster/jobs/{uuid}
        v
  storage agent (root, :8090)
   agent_app.py  입력 재검사, job 접수      jobs.py   메모리 job 표 (한 번에 하나)
   flexvol.py    LV -> ext4 -> mount -> 루트 초기화 -> 인스턴스
   nfs_instance.py  docker run anf-nfs-<uuid> (고정 IP, 준비 대기)
        |                                              |
        v                                              v
  dm-thin 풀 anf/aggr0  ->  thin LV  ->  ext4  ->  ns/<token>  --bind-->  컨테이너 /export
                                                          (볼륨 인스턴스: 자기 netns의 knfsd)
```

요청 하나가 두 개의 비동기 층을 지난다. 바깥은 ARM LRO(`Creating` → `Succeeded`, 클라이언트가 작업 상태 URL을 폴링)이고, 안쪽은 ONTAP job(`queued` → `running` → `success`, 워커가 job을 폴링)이다. D-06이 이 구조를 고른 이유는 "실제 ANF와 같은 구조이고, 각 기능을 ONTAP 객체 이름으로 설명할 수 있고, 이 PC와 CI에서 돌릴 수 있기 때문"이다.

### 코드 따라가기

#### (1) anf-api: 본문 검사와 "미룬 속성은 거절" — `volumes.py:33-169`

- 검사 순서는 이름 → 본문 형식 → (트랜잭션 안) 부모 존재·상태 → 진행 중 작업 → 불변 속성 → 경로 중복 → 용량이다 (`volumes.py:1-9`). 규칙 위반은 검사와 쓰기를 같은 트랜잭션에서 하고 동기 `400`으로 거절한다. 작업도 리소스 변경도 만들지 않으므로 정리할 상태가 남지 않는다 (풀 문서의 결정 4와 같은 이유).
- `_check_token`(`:69-82`)은 RP 오류 문서의 문구("File path too long." 등)를 쓴다. `_check_size`(`:85-91`)는 1 GiB 배수와 `최소 ~ 100 TiB`를 본다. 최소값은 기본 50 GiB(`DEFAULT_MIN_SIZE`, `:34`)이고 `ANF_MIN_VOLUME_SIZE_GIB`로만 낮출 수 있다 (`arm_app.py:64-72`, 아래 결정 3). `_check_protocols`(`:94-101`)는 `["NFSv3"]`이나 `["NFSv4.1"]` 하나만 받고 `CIFS`는 "not supported by this ANF clone"으로 거절한다.
- **데이터 효과가 아직 없는 속성은 저장만 하지 않고 거절한다.** `_NOT_YET`(`:50`: `throughputMibps`, `snapshotId`, `backupId`, `dataProtection`)은 값이 있으면 거절한다(`:159-161`). `_FIXED`(`:48`: `kerberosEnabled` 등)는 클론이 지원하는 값(false)과 같을 때만 받는다(`:162-166`). `_SERVICE_HELD`(`:54`: `serviceLevel`, `snapshotDirectoryVisible`, `securityStyle`, `exportPolicy`)는 서비스가 정하는 값과 같으면 받고 다르면 거절한다(`:294-298`). 이유는 NFR-01이다: 받아서 저장만 하면 상태만 바뀌는 시뮬레이션이 된다. 각 기능 사이클(export policy, 스냅샷 등)이 데이터 효과를 구현할 때 연다.

#### (2) 새 볼륨 규칙 — `_new_volume`, `volumes.py:265-312`

한 트랜잭션 안에서 순서대로 본다.

1. 부모 풀이 없으면 `404 ParentResourceNotFound`(녹화의 게이트웨이 문구, `:267-273`), 풀이 `Deleting`이면 `409 Conflict`(`:274-277`), `Succeeded`가 아니면 `400 BadRequest`(`:278-279`), Manual QoS 풀이면 거절(`:280-281`, FR-08 몫).
2. 속성을 채운다(`:286-293`). **`fileSystemId`를 PUT 때 만들어 저장한다**(`str(uuid.uuid4())`, `:287`). 이것이 agent 볼륨의 UUID이자 멱등 키다(결정 9). `serviceLevel`은 풀 값을 물려받고, 기본 export 규칙(`default_export_rule`, `:204-214`)은 `protocolTypes`를 따라 `nfsv3`/`nfsv41` 플래그를 정한다.
3. `creationToken`은 **클론 전체에서, 대소문자 무시로 유일**해야 한다(`:300-303`). 어기면 `400 BadRequest` "File path already in use." (결정 15).
4. **용량.** 풀 아래 모든 볼륨 행의 `usageThreshold` 합 + 새 볼륨이 풀 `size`를 넘으면 `400 BadRequest` "Pool size too small for total volume size."(`:305-307`). 상태와 무관하게 모든 볼륨 행이 예약이다. 풀 문서의 "볼륨 행 자체가 예약이다" 규칙의 볼륨 쪽이다.

#### (3) PUT 갱신·PATCH·DELETE — `volumes.py:315-421`

- `_ensure_terminal`(`:249-256`): 활성 작업이 있으면 `409 RequestConflict`(녹화 V6 문구). 계정·풀의 공통 `AnotherOperationInProgress`를 바꾸지 않고 볼륨 모듈 안에서만 다르게 했다(결정 14). 공통 코드를 바꾸면 이미 검증한 계정·풀의 계약이 바뀌기 때문이다.
- `_apply_update`(`:315-331`): `creationToken`·`subnetId`·`fileSystemId`를 다른 값으로 보내면 `400 BadRequest`("CreationToken cannot be changed." 등, `:322-324`). 같은 값을 다시 보내는 것은 허용한다(PUT 갱신은 필수 속성을 다시 보내야 하므로). `usageThreshold` 등 데이터 효과가 없는 속성의 변경은 "Changing '…' is not supported by this ANF clone."로 거절한다(`:330`). 지금 실제로 바뀌는 속성은 `networkFeatures`(Azure 네트워크 개념이라 저장만)와 tags뿐이다.
- `patch_volume`(`:385-406`)은 풀과 같은 방식이다: tags만 바꿔도 `Patching` + `PATCH` 작업(202). 새 값을 바로 쓰고 이전 값을 `previous`에 남겨, 워커가 실패로 끝내면 되돌린다(`lro.py:144-147`).
- `delete_volume`(`:409-421`): 없으면 `None`(라우트가 `204`), 있으면 `Deleting` + `DELETE` 작업.
- 라우트(`arm_app.py:239-285`)는 PUT에 `Azure-AsyncOperation`만(생성 201, 갱신 200), PATCH에 202 + 본문 + 두 헤더, DELETE에 본문 없는 202 + 두 헤더를 준다.

#### (4) 처리기: agent를 부르고 `mountTargets`를 기록한다 — `make_handlers`, `volumes.py:429-454`

- CREATE, UPDATE, PATCH 처리기가 **모두 같은 `ensure`**다(`:436-447`). 저장된 속성으로 agent에 "볼륨이 있게 하라"고 요청하고, 돌려받은 IP로 `mountTargets`를 기록한다(`:445-446`). `mountTargetId`는 `fileSystemId`와 같다 [녹화]. 그래서 생성에 `Failed`가 난 볼륨을 같은 본문으로 다시 PUT하면 데이터 플레인까지 완성된다. 처리기가 멱등이기 때문이다.
- DELETE 처리기(`:449-451`)는 agent에 볼륨 삭제를 요청한다.
- 처리기가 예외를 던지면 공통 워커가 작업을 `Failed`로 끝낸다. 응답에는 작업 ID가 든 일반 `InternalServerError` 메시지가 나가고, agent의 job 메시지(예: umount busy)는 anf-api 로그에만 남는다 (`lro.py:127-133`). 계정·풀의 처리기 실패와 같은 규칙이다.
- `mountTargets`는 **생성이 한 번 성공한 뒤부터** 나온다. 녹화의 201 본문에 없고 완료 뒤 GET에 있던 것과 맞춘 것이다 [녹화].

#### (5) `storage_client.py`: agent 호출의 세 가지 규칙

- **urllib + 스레드** (`:22-31`, `:91`): 새 HTTP 의존성을 늘리지 않고 표준 라이브러리를 `asyncio.to_thread`로 불러 이벤트 루프를 막지 않는다. 런타임 의존성이 바뀌면 `pyproject.toml`(제품 코드 해시 범위)이 바뀌므로 호출 몇 개에 의존성을 더할 이유가 없었다(결정 11).
- **60초 연결 재시도** (`_call`, `:86-99`): `OSError`(연결 안 됨)면 처음 실패한 시각부터 60초 동안 1초 간격으로 다시 시도하고, 넘으면 `StorageError`다. 이 오류가 작업을 `Failed`로 만든다. 검증에서 agent를 멈춘 채 생성하면 monotonic 60.2~60.3초 뒤 `Failed`였다(AC-11).
- **job 폴링과 재요청** (`_run_job`, `:67-84`): 변경 요청은 `202`와 job 링크로 답하고, 워커가 그 링크를 1초 간격으로 폴링해 `success`/`failure`를 기다린다. **job이 `404`면(agent가 재시작해 메모리 job 표가 비었다) 같은 요청을 다시 보낸다**(`:75-77`). 요청이 멱등이라 가능한 일이다. job ID를 DB에 저장하지 않는 것도 같은 이유다(결정 9): 저장 전후 어느 시점에 죽어도 결국 멱등 POST가 필요하므로 저장한 ID는 쓸 데가 없다.
- `ensure_volume`(`:52-62`)은 POST job이 끝나면 `GET /api/storage/volumes/{uuid}`로 `data_lif.ip.address`를 읽어 돌려준다.

#### (6) agent의 API: ONTAP REST 부분집합 — `agent_app.py`

- 경로: `POST/GET /api/storage/volumes`, `GET/DELETE /api/storage/volumes/{uuid}`, `GET /api/cluster/jobs/{uuid}` (`:101-129`). POST·DELETE는 `202 {"job": {"uuid", "_links": {"self": {"href"}}}}`로 답한다(`:93-99`).
- **ONTAP과 다른 점은 표시한다**(R-04): POST가 `uuid`를 요청에서 받는다(멱등 키, ONTAP은 안 받음). `svm`·`aggregates`는 받지 않는다(하나뿐). `nas.protocols`는 클론 확장이다. GET에 `data_lif`가 있다(ONTAP에서 IP는 볼륨이 아니라 SVM의 네트워크 인터페이스에 있다). 없는 볼륨 DELETE는 성공 job이다(ONTAP은 오류).
- **입력을 agent에서 다시 검사한다**(R-07, `parse_volume`, `:43-65`): `uuid`는 소문자 UUID, `name`은 `vol_<uuid 32자리>`와 같아야 하고, `size`는 1 GiB 배수, `nas.path`는 `/` + `creationToken` 규칙이다. 모르는 필드는 400이다. 커널 명령 인자에 들어가는 값이라 anf-api를 믿지 않고 한 번 더 본다. 검증에서 `../x`, `/`, `/a/b`가 모두 400이었다(AC-13).
- 볼륨 관리자를 부르는 GET/DELETE 경로는 `def`로 둔다(`:110`). 커널 명령을 기다리는 동안 이벤트 루프를 막지 않게 스레드에서 돌게 하려는 것이다.
- `jobs.py`: 메모리 job 표. 키는 **"작업 종류 + 볼륨 UUID"**다(`agent_app.py:95`). 끝나지 않은 같은 키가 있으면 새 job을 만들지 않고 그 job을 돌려준다(`jobs.py:37-41`). UUID만 키로 쓰면 같은 볼륨에 DELETE job이 진행 중일 때 들어온 POST가 그 DELETE job을 받아 "성공"으로 오인한다. job은 **한 번에 하나씩** 돈다(`_run`, `:66-77`): LVM 변경과 IP 선택이 겹치지 않게 하기 위해서다. 끝난 job은 300초 뒤 지운다(`:85-90`, ONTAP 기본값).
- `runner.py:33-46`: 커널 명령은 셸 없이 인자 목록으로 실행한다(R-07). 입력이 없으면 빈 입력을 줘서(`:36-37`) LVM의 확인 질문이 root 데몬의 표준 입력을 기다리며 멈추지 않게 한다.

#### (7) `flexvol.py`: aggregate와 thin LV + ext4

- **aggregate** (`ensure_aggregate`, `:69-83`): `/var/lib/anf-clone/aggr0.img` 희소 파일(기본 1 TiB, 실제 디스크는 쓴 만큼) → 루프 장치 → VG `anf` → 씬 풀 `aggr0`. 매번 실제 상태를 보고 없는 것만 만든다. WSL이 재시작해 루프 장치가 사라졌으면 다시 붙인다(`:77-78`).
- **생성은 다섯 단계이고 단계마다 실제 상태를 먼저 본다** (`create`, `:97-111`): (1) LV 확인·생성 → (2) `blkid`로 파일시스템 확인, 없으면 `mkfs.ext4 -m 0 -U <fileSystemId>` → (3) 마운트 확인·마운트(`nodelalloc`, `:215`) → (4) 루트 초기화 → (5) 인스턴스 확인·생성·시작. 어느 단계에서 멈춰도 같은 요청을 다시 보내면 이어서 끝난다. 실패 때 되돌리는 보상 정리를 두지 않은 이유다: 같은 UUID로 다시 POST하면 이어서 완성되고, ARM `Failed` 볼륨은 DELETE로 정리되므로 정리 코드가 둘이 될 필요가 없다 (결정 10).
- **LV 단계의 멱등성** (`_ensure_lv`, `:136-162`): 같은 UUID가 있으면 경로·크기·프로토콜이 같을 때만 그대로 쓰고 다르면 `VolumeError`(`:138-145`, 검증에서 `failure` job). 다른 UUID가 같은 경로를 쓰면 거절(`:146-148`, 대소문자 무시). 씬 풀에 남은 공간보다 크면 거절(`:149-151`, **overcommit을 하지 않는다**). IP는 다른 LV 태그에 없는 가장 작은 주소를 고른다(`:152-155`, 최대 126개).
- **상태를 LVM 태그에 둔다** (`:157-161`, `_report`, `:164-177`): `anf_path`, `anf_uuid`, `anf_ip`, `anf_proto`. agent에는 DB가 없다. 재시작 복구는 LVM에서 실제 상태를 읽는 것이 더 정확하다(ADR §6.4 "실제 상태와 대조"). IP를 같은 `lvcreate`에서 태그로 함께 정하므로 같은 UUID로 다시 POST해도 같은 IP가 된다.
- **루트 초기화 판단** (`:106-110`): "이번 호출에서 mkfs를 했는가"가 아니라 "`lost+found`가 있는가"로 판단한다. mkfs 뒤·초기화 전에 멈춰도 다시 POST하면 초기화되고, 초기화가 끝난 볼륨의 권한은 클라이언트가 바꿨을 수 있으므로 다시 바꾸지 않는다.
- **삭제 순서** (`delete`, `:113-125`): 인스턴스 제거 → 언마운트(재시도) → 마운트 지점 제거 → `lvremove`. knfsd가 파일시스템을 잡고 있으므로 인스턴스가 먼저다. 인스턴스를 지운 뒤에도 umount가 잠시 busy일 수 있어서 0.5초 간격으로 60초까지 다시 시도한다(`_umount`, `:203-208`). 마운트 지점 제거를 `lvremove` 앞에 둔 이유: LV가 남아 있는 동안에는 태그로 경로를 알 수 있어서, 어느 단계에서 멈춰도 다시 DELETE하면 끝난다.
- **시작 복구** (`recover`, `:85-93`): aggregate → `ns` 공유 마운트 → 볼륨 마운트 → 인스턴스. `ns`를 자기 자신에 바인드하는 일은 볼륨 마운트보다 먼저다. 나중에 바인드하면 그 아래의 기존 마운트를 가린다.

#### (8) `nfs_instance.py`와 `entrypoint.sh`: 볼륨마다 knfsd 하나

- **인스턴스** = privileged Docker 컨테이너 `anf-nfs-<uuid 32자리>`, 이미지 `anf-nfs-server`(alpine + `nfs-utils`, `rpcbind`; `nfs.conf`에 `[exports] rootdir=/export`), 네트워크 `anf-vnet`, 고정 IP. 호스트의 `ns`를 `/export`로 바인드한다 (`nfs_instance.py:81-85`).
- **IP 배치**: `anf-vnet`(172.30.0.0/24)은 준비 스크립트가 `--ip-range 172.30.0.0/25`로 만든다(`setup-wsl-dataplane.sh:37`). Docker가 클라이언트 컨테이너에 .2~.127을 동적으로 주고, 볼륨 인스턴스는 .129~.254(`VOLUME_IPS`, `nfs_instance.py:23`)에서 agent가 정한 고정 IP를 받는다. 두 범위가 겹치지 않는다. agent는 시작할 때 이 네트워크의 subnet과 ip-range가 맞는지 확인하고 아니면 뜨지 않는다(`check_host`, `:49-62`).
- **`ns` 공유 마운트** (`ensure_shared_ns`, `:64-71`): WSL의 `/`는 private 마운트라 컨테이너의 `rslave` 바인드가 거절된다. 그래서 `ns`를 자기 자신에 바인드하고 `--make-rshared`로 만든다.
- **진입점** (`entrypoint.sh`): `rootdir` 확인(`:16`) → 프로토콜에 맞는 버전만 켤 옵션 선택(`:17-21`: NFSv3면 `-V 3 -N 4`, NFSv4.1이면 `-N 3 -N 4.0 -V 4.1 -N 4.2`) → nfsd·rpc_pipefs 마운트, `nfsdcld`, `rpcbind`(`:23-30`) → `exportfs`(`:34`) → `rpc.mountd`(`:35`) → `rpc.nfsd`와 유예 기간 확인 루프(`:40-53`) → 준비 표시(`:54`).
- **export 옵션** (`:34`): `rw,sync,no_subtree_check,no_root_squash,secure,crossmnt,mp,fsid=<fileSystemId>`, 대상 `*:/<creationToken>`. 이유가 옵션마다 있다.
  - `no_root_squash`와 `rw`는 ANF 기본 규칙(`unixReadWrite`, `hasRootAccess`)이다.
  - `*`: 본문은 `allowedClients 0.0.0.0/0`이지만 실제 export 클라이언트는 `*`다. `0.0.0.0/0`은 mountd가 127.0.0.1도 "unmatched host"로 거절했다(구현 중 확인).
  - `mp`: 마운트되지 않은 `ns/<token>`의 export를 mountd가 거절한다("request to export an unmounted filesystem"). 부팅 직후 빈 디렉터리가 export되는 것을 막는다.
  - `fsid=<fileSystemId>`: thin 스냅샷·복원 볼륨은 ext4 UUID가 원본과 같다(S1). knfsd는 기본적으로 UUID로 export의 fsid를 만드므로 명시하지 않으면 충돌한다. 지금은 스냅샷이 없지만, FR-05를 위해 처음부터 `mkfs -U <fileSystemId>`와 함께 맞춰 뒀다.
  - `crossmnt`: FR-05의 스냅샷 하위 마운트를 위해 미리 둔 것이다(S1).
- **버전 제한**: 인스턴스가 `protocolTypes`의 버전만 켠다. 그래서 NFSv3 볼륨을 `vers=4.1`로 마운트하면 `Protocol not supported`로 실패한다(AC-02). 호스트 knfsd 하나로는 export마다 버전을 막지 못했다.
- **종료** (`stop`, `:58-66`): `docker stop`의 SIGTERM을 받으면 `unlock_filesystem`에 경로를 써서 NFS 잠금·NFSv4 상태를 풀고 `rpc.nfsd 0`, `exportfs -ua`를 한다.
- **준비 대기** (`ensure`/`_wait_ready`, `nfs_instance.py:73-105`): `docker run -d`는 진입점이 knfsd를 띄우기 전에 돌아온다. 그래서 agent는 `/run/anf-ready`가 생길 때까지 0.5초 간격으로 60초 기다리고, 컨테이너가 끝나면 로그 끝부분을 넣어 job을 실패시킨다. **`Succeeded`가 "서비스 중"을 뜻하게 하는 장치다.** 이 부분은 5.1절의 사건에서 생겼다.

### 설계 결정

설계 문서(`_workspace/volume/02_main_design.md`)의 결정 1~18 중 면접에서 물을 만한 것들이다. 결정 1~4는 사용자가 선택지 중에서 골랐고, 5~16은 메인이 기본안으로 제시해 사용자가 이견을 내지 않았다. 17·18은 스파이크 S2 결과를 반영한 것이다(사용자 지시).

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | **D-11 = C: 씬 풀 하나 위에 볼륨마다 thin LV + ext4** (사용자 선택) | A. btrfs 하나 + 서브볼륨 + qgroup. B. 볼륨마다 btrfs | S1 실측: A는 **NFSv3로 파일 소유자(`no_root_squash`)가 읽기 전용 스냅샷 파일에 append했고 서버의 내용이 바뀌었다**, 클라이언트 `df`가 풀 전체(2 GiB)를 보였고, 스냅샷 루트가 볼륨 루트와 같은 dev·inode(256)로 보였다. B는 스냅샷 구조가 A와 같고 새 볼륨 복원에 send/receive 복사가 필요하다. C는 v3·v4.1 모두 스냅샷이 읽기 전용이고, `df`가 볼륨 크기를 보이고, 초과 쓰기는 ENOSPC이고, 새 볼륨 복원이 즉시이고(thin 스냅샷 0.127 s), 볼륨마다 블록 장치가 있다 |
| 2 | **마운트 경로는 nfs-utils `[exports] rootdir`로 만든다** (사용자 선택). 볼륨은 `ns/<token>`에 마운트하고 인스턴스가 `/<token>`으로 export한다 | 서버 루트에 직접 마운트(`/<token>`), 전체 경로, 심볼릭 링크 | 직접 마운트는 WSL 루트에 디렉터리를 만들고 `/etc` 같은 이름을 막아야 한다. 전체 경로는 FR-04의 경로와 다르다. 심볼릭 링크는 S1에서 v3만 되고 v4.1은 `No such file or directory`였다 [추론: v4 pseudo-fs가 링크를 따라가지 않음] |
| 3 | **최소 크기는 기본 50 GiB(ANF), 검증할 때만 `ANF_MIN_VOLUME_SIZE_GIB`로 낮춘다** (사용자 선택). 기본값과 다르면 경고 로그 | 50 GiB 고정, 1 GiB 고정 | 50 GiB 고정이면 초과 쓰기 검증마다 50 GiB 넘게 써야 한다(수 분, 호스트 디스크 50 GB, CI 러너 디스크 약 14 GB로는 불가능). 1 GiB 고정은 ANF 계약과 다르다. `ANF_FAULT_INJECTION`과 같은 방식이라 잘못된 값이면 서버가 뜨지 않는다 |
| 4 | **데이터 효과가 없는 속성 변경은 `400`으로 거절한다** (사용자 선택). 같은 값은 허용 | 받아서 저장만, `usageThreshold` 확장만 지금 구현 | 저장만 하면 NFR-01(실제 효과)을 어기는 시뮬레이션이다. 크기 변경은 FR-16의 조사(축소 규칙, `maxfiles`)를 건너뛰게 된다 |
| 5 | **씬 풀 하나가 aggregate 역할이다.** 용량 풀은 지금처럼 컨트롤 플레인 예산이고 agent에 아무것도 만들지 않는다 | 용량 풀마다 씬 풀 | 풀 생성·삭제·크기 변경이 데이터 플레인 작업이 되어 풀 사이클을 다시 연다. 풀에 대응하는 ONTAP 객체도 공개 자료에 없다 |
| 6 | **ext4를 `nodelalloc`으로 마운트한다** | 기본(delalloc), XFS | S1: 둘 다 클라이언트가 오류를 받았지만, 오류 뒤 남은 데이터가 원본의 앞부분(prefix)인 것은 `nodelalloc`뿐이었다. XFS는 시험하지 않았다 |
| 8 | **agent는 ARM을 모른다.** 메타데이터는 LV 이름과 LVM 태그, DB 없음 | agent SQLite | 재시작 복구는 실제 상태를 LVM에서 읽는 편이 정확하다 |
| 9 | **안정적인 작업 식별자 = `fileSystemId`.** agent 생성은 "있으면 확인, 없으면 만들기" | job ID를 작업 행에 저장 | 저장 전후 어느 시점에 죽어도 같은 결과가 나와야 하므로 결국 멱등 POST가 필요하다. ONTAP POST는 `uuid`를 받지 않는다: 클론의 확장이고 표시했다 |
| 10 | **단계별 복구, 보상 정리 없음** | 실패 때 만든 것을 지우기 | 같은 UUID로 다시 POST하면 이어서 완성되고, `Failed` 볼륨은 DELETE로 정리된다 |
| 13 | **ANF 코드가 확인되지 않은 위반은 동기 `400 BadRequest` + ANF 문서의 메시지** | 작업을 만든 뒤 `Failed`, 코드 지어내기 | 실패한 볼륨 행이 예약을 계속 잡아 정리 규칙이 더 필요하다. 근거 없는 코드를 지어내지 않는다 |
| 14 | **진행 중인 볼륨은 `409 RequestConflict`** (볼륨 모듈 안에서만) | 공통 코드 변경 | 계정·풀의 확정된 계약이 바뀐다 |
| 15 | **`creationToken`은 클론 전체에서 유일(대소문자 무시)** | `subnetId`별 유일 | 호스트 마운트 지점 `ns/<creationToken>`을 모든 볼륨이 나눠 쓰므로 경로가 겹치면 충돌한다 |
| 16 | **`protocolTypes`는 하나만, 인스턴스가 그 버전만 켠다. PATCH로 프로토콜 변경 불가** | 프로토콜 변경 PATCH 허용 | 인스턴스의 버전을 바꾸는 데이터 플레인 작업이 필요하다 |
| 17 | **볼륨마다 NFS 서버 인스턴스 하나** (D-12 = S2 T1n) | 호스트 knfsd 하나, 풀마다 인스턴스, 볼륨마다 Ganesha(T3), 컨테이너 안 tmpfs `fsid=0` 루트 | 아래 설명 |
| 18 | **볼륨 IP는 agent가 정하고 LV 태그에 기록한다** | anf-api가 정함, Docker에 맡김 | IP는 데이터 플레인 자원이고 재시작 복구 때 agent가 태그에서 다시 읽어야 한다. Docker에 맡기면 인스턴스를 다시 만들 때 IP가 바뀌어 `mountTargets`와 어긋난다 |

**결정 17을 풀어 쓰면 (S2).** 처음 설계는 호스트 knfsd 하나에 마운트 IP 하나였다. FR-08은 볼륨마다 처리량을 제한해야 하는데, S2에서 호스트 knfsd 하나 + 볼륨마다 IP + tc(T1)를 시험하니 **NFSv3에서는 통과했지만 NFSv4.1에서는 볼륨을 구분하지 못했다.** 클라이언트가 세 볼륨(.11, .12, .13)을 v4.1로 마운트하면 세 마운트 모두 `addr=172.30.0.11`이 되고 TCP 연결이 하나뿐이었다. 커널 NFS 클라이언트는 EXCHANGE_ID 응답의 server owner와 clientid가 같으면 같은 서버로 보고 연결(`nfs_client`)을 합치기 때문이다(`notrunkdiscovery`를 줘도 합쳐졌다). knfsd 하나는 모든 IP에서 같은 값을 준다. 그래서 b의 트래픽이 .11의 tc 클래스로 들어가 "제한 없는" 볼륨이 10 MiB/s로 걸렸다. 반면 knfsd는 네트워크 네임스페이스마다 따로 뜨므로(스레드, export 캐시, 서버 신원), 볼륨마다 자기 netns의 인스턴스를 두면 연결이 분리된다. T1n은 v3·v4.1 모두 설정값의 약 95%, 읽기+쓰기 합산, 실시간 변경, 같은 클라이언트의 다른 볼륨 영향 없음을 통과했다. 버린 것: T2(cgroup `io.max`)는 WSL에서 knfsd 스레드가 보이지 않아 불가능했고(10 MiB/s 설정에 241 MiB/s), 설령 되더라도 읽기·쓰기를 따로 세고 캐시 적중 읽기를 제한하지 못한다(T3 메커니즘 확인: 10+10=20 MiB/s, 4310 MiB/s). **이번 사이클은 인스턴스와 IP까지만 만들고, tc 제한은 FR-08에서 더한다.** AC-15가 그 전제(볼륨마다 IP와 연결이 따로 있음)를 검증한다.

---

## 4. 실제 ANF와 다른 점

### 4.1 비교표

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 생성 시간 | 약 5분 20초~5분 40초 [녹화] | 약 2초 (100 GiB NFSv3, 작업 시각 2.12 s) | 클론은 파일 몇 개와 컨테이너 하나를 만들 뿐이다. 검증용 지연은 결함 주입으로만 만든다 |
| 마운트 IP | 여러 볼륨이 공유할 수 있다 [추론] | **볼륨마다 IP 하나** (172.30.0.129~254) | FR-08의 볼륨별 제한 (결정 17, 18). 설계 문서가 클론의 차이로 기록했다 |
| NFS 서버 | ONTAP SVM 하나가 여러 볼륨을 서비스 [추론] | 볼륨마다 knfsd 인스턴스 하나 | 위와 같다 |
| 저장 방식 | ONTAP (WAFL). ANF 내부 구현은 공개 자료 없음 [미확인] | dm-thin thin LV + ext4 (`nodelalloc`) | S1. 스냅샷 단계에서 WAFL과의 차이를 다시 정리한다 |
| `usageThreshold`의 의미 | 스펙은 "soft quota", Learn은 "limited to the set size" [스펙][문서] | **하드 한도.** 블록 장치 크기로 강제한다 | NFR-01. Learn 문서를 근거로 삼았다 |
| `creationToken` 유일성 | 서브넷마다 유일 [문서] | 클론 전체에서 유일, 대소문자 무시 | 호스트 마운트 지점 `ns/<token>`을 나눠 쓴다 (결정 15) |
| 201 본문 | `fileSystemId`, `mountTargets`, `exportPolicy`, `protocolTypes`가 없다 [녹화] | `fileSystemId`, `protocolTypes`, 기본 export 규칙은 201부터 있다. **`mountTargets`만 완료 뒤에 나온다** | 단순화 (설계 결정 12). `mountTargets`는 실제로 IP가 정해진 뒤에만 의미가 있다 |
| 기본 export 규칙 | `allowedClients 0.0.0.0/0` [녹화] | 본문은 `0.0.0.0/0`, **실제 export는 `*`** | mountd가 `0.0.0.0/0`을 거절했다. 규칙 입력(사용자 지정 규칙)은 FR-15 전까지 `400` |
| 데이터 효과가 없는 속성 | 받아서 저장한다 [추론] | 기본값과 다르면 `400 InvalidRequestContent` | 상태만 바뀌는 시뮬레이션 방지 (결정 4) |
| PATCH / PUT 갱신으로 바뀌는 것 | `usageThreshold`, `exportPolicy`, `protocolTypes` 등 [스펙][녹화] | tags와 `networkFeatures`만 | 크기 변경(FR-16), export policy(FR-15)는 뒤 사이클 |
| 규칙 위반의 HTTP 코드 | "File path already in use." 등은 메시지만 알려져 있고 코드는 [미확인] | 동기 `400 BadRequest` + ANF 문서의 메시지 | **클론이 정한 값이다.** 실서비스 값이라고 말하면 안 된다 (결정 13) |
| `Deleting` 풀 아래 볼륨 생성 | 응답 [미확인] | `409 Conflict` | 클론의 선택. 고아 볼륨 방지 |
| 진행 중 충돌 | 볼륨은 `409 RequestConflict` [녹화] | 볼륨은 `RequestConflict`, 계정·풀은 `AnotherOperationInProgress` | 볼륨만 녹화가 있고, 공통 코드를 바꾸지 않았다 (결정 14) |
| agent 작업 실패 | — | 작업 오류는 공통 `InternalServerError`, 이유는 anf-api·agent 로그에만 | 계정·풀의 처리기 실패와 같은 규칙 |
| 할당량 초과 시 errno | [미확인] (ENOSPC일 가능성이 높음 [추론]) | `No space left on device`(ENOSPC), 오류가 `fsync`에서 보인다 | S1, 검증 AC-04 |
| 풀 할당량 합이 aggregate를 넘을 때 | 백엔드 용량 한계 [미확인] | agent job이 실패한다(overcommit 안 함) | thin provisioning을 쓰지 않는 선택 (설계 "아직 확정하지 않은 것") |
| `subnetId` | 위임 서브넷 필요 [스펙] | ARM 서브넷 ID 형식만 검사하고 생성 뒤 변경 불가 | PRD 비목표: VNet·위임은 다루지 않는다 |
| 처리량 한도 | 실제 I/O에 적용 [문서] | **아직 제한하지 않는다.** `actualThroughputMibps`는 계산 값이고 풀의 `utilizedThroughputMibps`는 0.0 | FR-08에서 tc로 구현 |
| 스냅샷·`.snapshot`·`snapshotDirectoryVisible` | 있음 | 없음. `snapshotDirectoryVisible: false`는 `400` | FR-05 |
| 인증 | ARM이 토큰·RBAC 검증 | 없음 (localhost 바인딩, D-13) | ANF 리소스 공급자 앞단의 일이다 |

### 4.2 알려진 한계·차이 (검증에서 관찰한 것)

- **초과 쓰기 오류가 `write()`가 아니라 `fsync`에서 보인다.** AC-04에서 `dd conv=fsync`가 `dd: fsync failed for '/m/big': No space left on device`(종료 코드 1)를 냈다. NFS 클라이언트가 쓰기를 캐시에 쌓았다가 서버에 내려 보낼 때 ENOSPC를 받기 때문이다. 같은 실행에서 클라이언트 `ls -l`은 1,288,699,904바이트를 보였지만 호스트의 실제 파일은 1,179,648,000(v3)/1,225,785,344(v4.1)바이트였다. 클라이언트가 보는 크기와 서버에 들어간 크기가 다르다. S1 첫 측정의 실수(`dd` 출력을 `tail`로 잘라 오류 줄을 놓침)와 같은 종류의 함정이라, 이후 검증은 종료 코드와 stderr 전체로 판정한다.
- **ext4 오버헤드.** 1 GiB 볼륨의 클라이언트 `df`가 1,021,313,024바이트(974 MiB)를 보인다. 50 GiB 이상에서는 비율이 작다.
- **볼륨을 지우면 이미 마운트한 클라이언트는 오류를 받는다.** AC-09에서 삭제 전에 마운트해 둔 클라이언트는 `cat: /m/f: I/O error`, `ls: cannot open directory '/m': Stale file handle`을 보았다. 같은 `creationToken`으로 다시 만들면 IP(.129)는 재사용되지만 `fsid`가 새 `fileSystemId`라서 예전 마운트는 계속 `Stale file handle`이다. 새 마운트는 `Host is unreachable`(인스턴스가 사라짐)였다. 실제 ANF에서 같은 상황의 클라이언트 오류는 확인하지 못했다 [미확인].
- **NFSv3 테스트가 `nolock`으로 마운트한다.** 진입점 주석은 90초 유예 기간이 같은 netns의 NLM 잠금도 막는다고 쓰고 있고, 거절을 확인하는 마운트(`retry=0,soft,timeo=20,retrans=1`)와 S1·검증의 v3 마운트는 `nolock`을 쓴다. 잠금 동작 자체는 직접 시험하지 않았다(검증자의 표현으로 "추정, 이번 검증은 `nolock`이라 미확인"). 그래서 이 클론이 NFS 잠금을 제대로 서비스한다고 주장하지 않는다.
- **NFSv4 상태가 컨테이너 안에만 있다.** `nfsdcld`의 추적 기록은 컨테이너 파일시스템에 있다. `docker start`(WSL 재시작 뒤 복구)는 기록이 남지만, 인스턴스를 다시 만들면 이전 NFSv4 상태를 되찾지 못한다.
- **재시작 정책이 없다.** WSL이 재시작하면 인스턴스는 멈춘 채 남고, agent가 시작할 때 `docker start`로 같은 IP로 다시 띄운다(AC-12c). agent가 떠 있지 않으면 마운트는 `Operation timed out`이다.
- **인스턴스 시작의 약 8%가 knfsd를 한 번 재시작한다.** 5절 참고. 그 대가로 job이 2~4초 길어진다(평균 1.59 s, 재시작한 것 3.84~5.69 s).
- **agent는 job을 한 번에 하나씩 처리하고 job 표가 메모리에만 있다.** 동시성이 낮고, agent 재시작 뒤 job 조회가 404가 된다(anf-api가 같은 요청을 다시 보내 메운다).
- **규모 상한.** 볼륨 IP는 126개, aggregate는 희소 파일 1 TiB(overcommit 안 함). 인스턴스당 메모리는 유휴 약 4 MiB(`docker stats`)라 126개를 띄워도 NFR-06(약 7 GB) 안이다.
- **CI는 데이터 플레인 테스트를 돌리지 않는다.** `-m "not dataplane"`으로 선택에서 뺀다(skip이 있으면 CI가 실패하므로 skip이 아니라 선택에서 뺀다). 데이터 플레인 CI 작업은 스파이크 S3 뒤에 만든다. PR #7의 GitHub Actions는 579 passed, 25 deselected(= 볼륨 e2e 21 + 통합 4), skip 0이었다.
- **WSL 게스트 시계가 호스트보다 약 9~10% 느리다**(S2: 0.908배, 검증: 89 s 동안 벽시계가 약 3.2 s씩 뛰어 9.647 s 차이). 작업 시각의 `startTime`·`endTime`은 벽시계라 같은 구간이 다르게 보인다(AC-11의 60 s 재시도가 작업 시각으로는 66.7 s). FR-08 처리량 검증은 게스트 단조 시계로 판정하기로 했다 (S2).

---

## 5. 검증

검증 보고서: `_workspace/volume/04_verifier_report.md`(1회차)와 `04_verifier_report_r2.md`(2회차). 둘 다 2026-11-07.

**방법.** 계정·풀과 같다: WSL Ubuntu에서 실제 uvicorn 프로세스를 띄우고 별도 프로세스(pytest)에서 요청한다. 여기에 데이터 플레인이 더해졌다. 테스트 모듈이 storage agent를 root로 직접 띄우고(AC-11·AC-12가 agent를 멈추고 다시 띄워야 하므로), anf-api는 일반 사용자로 띄운다(`ANF_MIN_VOLUME_SIZE_GIB=1`). 클라이언트는 `anf-vnet`의 privileged `anf-nfs-client` 컨테이너이고, 마운트 IP는 하드코딩하지 않고 볼륨 GET의 `mountTargets[0].ipAddress`를 쓴다. 명령의 성공·실패는 종료 코드와 stderr 전체로 판정한다. 검증 대상 코드의 해시는 시작과 끝에서 같았다(2회차 `8bb57d91…`).

**결과: 1회차 PASS 14 / FAIL 1 / UNVERIFIED 0 → 2회차 PASS 15 / FAIL 0 / UNVERIFIED 0.** PR #7의 GitHub Actions(push와 PR 실행 모두)도 PASS였다.

| 기준 | 증명한 것 (2회차 핵심 값) |
| --- | --- |
| AC-01 | 풀 아래 PUT `201` + `Creating` + `Azure-AsyncOperation`만 → `Succeeded`(2.12 s). GET에 UUID `fileSystemId`, `mountTargets[0]`(IP 172.30.0.129), 기본 export 규칙, `unixPermissions "0770"`, `actualThroughputMibps 6.25`. 데이터 플레인에 LV(태그 `anf_ip`, `anf_path`, `anf_proto`, `anf_uuid`), 인스턴스, `ns/<token>`이 생김. anf-api 상관 ID가 agent 로그에 있음 |
| AC-02 | 클라이언트 A가 `vers=3`으로 쓰고 B가 같은 경로에서 읽음. 루트 권한 770. `vers=4.1`은 `Protocol not supported` |
| AC-03 | NFSv4.1 볼륨: 기본 규칙 `nfsv41 true / nfsv3 false`, 첫 쓰기·읽기 0.22 s. `vers=3`과 `vers=4.0`은 거절. (5.1절의 FAIL → PASS) |
| AC-04 | v3·v4.1 모두 `df` 약 974 MiB, 1.2 GiB `dd conv=fsync`는 rc 1 + `No space left on device`, 다른 파일은 그대로 읽힘 |
| AC-05 | 풀 초과 `400 BadRequest`, 없는 풀 `404 ParentResourceNotFound`, `Deleting` 풀 `409 Conflict`. CV-1: 볼륨이 있는 풀 DELETE `409 CannotDeleteResource`(볼륨 ID 포함). CV-2: 볼륨 할당량 합보다 작은 풀 PATCH·PUT `400`(aggregate가 약 1 TiB라 볼륨이 `Failed`여도 예약이 남는 것까지 확인). CV-3: `serviceLevel` PUT `400 BadRequest`, PATCH는 풀 모델에 속성이 없어 `400 InvalidRequestContent` |
| AC-06 | 잘못된 본문 22가지가 모두 `400`이고 작업·LV·인스턴스가 생기지 않음. 대조: 미룬 속성을 기본값으로 보내면 `201`. 최소 크기 주입을 끄면 49 GiB `400`, 50 GiB `201` |
| AC-07 | 같은 토큰(대소문자만 달라도) `400 "File path already in use."`. 토큰·`subnetId` 변경 `400 BadRequest`, `usageThreshold` 변경 `400 InvalidRequestContent`. 거절 뒤에도 클라이언트가 계속 읽고 `df` 크기 그대로. 같은 값 PUT은 `200` |
| AC-08 | tags PATCH `202` + `Patching` + 두 헤더 → `Succeeded`. 그동안 클라이언트 읽기·쓰기 루프 694회, 오류 0 |
| AC-09 | DELETE `202` → `Succeeded`(3.0 s) → GET `404` → 재DELETE `204`. 새 마운트 실패, 인스턴스·LV·`ns/<token>` 없음, 씬 풀 사용률 0.00 → 0.02 → 0.00%(공간 회수). 같은 토큰으로 재생성하면 IP 재사용 |
| AC-10 | 생성 지연 중 PUT·PATCH·DELETE 모두 `409 RequestConflict`, 새 작업 없음, 원래 작업은 `Succeeded` |
| AC-11 | 실패 주입: 작업·볼륨 `Failed`, 예약 유지(같은 풀 초과 PUT `400`), 데이터 플레인 그대로 → 같은 본문 PUT `200`, `Updating` → `Succeeded`, 마운트 가능. agent 정지: 60.2 s 뒤 `Failed` → agent 기동 뒤 PUT으로 회복 |
| AC-12 | (a) anf-api SIGKILL → 재시작 뒤 `Succeeded`, LV 하나. (b) agent를 job 시작 직후 / LV 생성 직후 / 마운트 직후에 SIGKILL → 다시 띄우면 4.5 / 2.5 / 3.4 s 뒤 `Succeeded`, LV가 하나뿐. (c) 인스턴스 정지 + 언마운트(WSL 재시작 흉내) → agent 기동 뒤 같은 IP로 복구되고 이전 파일이 읽힘 |
| AC-13 | agent API: POST `202` + job, 같은 요청 반복 `success`·LV 하나, 같은 uuid에 다른 경로 `failure`, `?name=` 1건, 없는 uuid DELETE `success`, 잘못된 경로 5개 `400` |
| AC-14 | 계정·풀 e2e 63개 회귀 통과 (anf-api 코드가 2회차에 바뀌지 않아 1회차 결과 유지, CI 재현에서도 통과) |
| AC-15 | NFSv4.1 볼륨 두 개의 IP가 다르다(.129, .130). 한 클라이언트가 둘을 마운트하면 `/proc/mounts`의 `addr=`가 각자의 IP이고 `ss -tn`에 2049 연결이 둘 따로 있다. S2에서 호스트 knfsd 하나로는 합쳐졌던 것이 분리됨 |
| 추가 | 통합 테스트 4 passed(32.5 s), CI 명령 로컬 재현: lint 통과, `579 passed, 25 deselected`, skip 0, 훅 테스트 25 passed |

**검증이 증명하지 못하는 것.**
- 실제 ANF와의 비교가 아니다. 클론이 설계한 계약을 확인한 것이다. 오류 코드 몇 개, 초과 쓰기의 errno, 삭제 중 클라이언트 오류는 실제 ANF 값이 [미확인]이다.
- 처리량 제한은 없다(FR-08). AC-15는 그 전제만 확인한다.
- NFS 잠금(NLM)과 NFSv4 상태 복구는 시험하지 않았다(4.2절).
- 검증은 WSL 한 환경에서 했고 GitHub Actions는 데이터 플레인 테스트를 돌리지 않는다.

### 5.1 1회차 AC-03 FAIL: 90초 유예 기간 (이번 사이클에서 가장 어려웠던 문제)

**증상.** 1회차에서 AC-03 테스트 자체는 4번 모두 통과했는데, 다른 시험(AC-15, 반복 시험)에서 같은 코드가 만든 NFSv4.1 볼륨이 이상했다. 볼륨은 `Succeeded`이고 마운트도 성공했는데 첫 쓰기가 **101.96초** 걸렸다(정상은 0.24~0.33 s). 다른 실행에서는 쓰기가 `nfs4_handle_exception`에서 멈춰 있었다(`ps -o wchan`). API는 `Succeeded`를 말하는데 클라이언트는 90초 넘게 쓰지 못하므로 "클라이언트에서 관찰한 효과" 기준으로 FAIL이다. 간헐적이라서 AC-03은 "FAIL (불안정)"로 판정했다.

**진단 근거 (verifier가 모은 것).**
- 인스턴스 로그: 정상은 `…serving /… (nfs4.1): versions=-3 +4 -4.0 +4.1 -4.2 grace_ended=Y`, 실패는 `grace_ended=N`.
- 호스트 커널 로그(`dmesg`): 실패한 인스턴스 시작에서 `NFSD: attempt to initialize umh client tracking in a container ignored.` / `NFSD: Unable to initialize client recovery tracking! (-2)` / `NFSD: Is nfsdcld running? …` / `NFSD: starting 90-second grace period`. 정상 인스턴스는 `NFSD: Using nfsdcld client tracking operations.` / `no clients to reclaim, skipping NFSv4 grace period`.
- 실패한 인스턴스 안에서도 `nfsdcld` 프로세스는 돌고 있었다. 그래서 "nfsdcld가 없었다"가 아니라 "늦게 준비됐다"로 읽었다.
- 빈도: 추적 실패 7회를 확인했고, 커널 로그에 남은 시작 약 92회 중 약 7~8%였다. 같은 순서로 두 개씩 만드는 반복 시험 32개는 모두 정상이었다. 그래서 40개 안팎을 만들어야 한 번 걸리는 간헐 실패다. NFSv3 인스턴스에서도 났지만(`nolock` 클라이언트라 영향이 없었다) 같은 원인으로 본다.
- 통합 테스트가 131.91 s 걸렸다(정상 32.7 s). 차이 약 99 s가 유예 기간과 맞는다(추정).

**원인.** 두 층이다.
1. (S2에서 이미 한 번 풀었던 문제) 컨테이너(init 밖 netns)의 knfsd는 NFSv4 클라이언트 추적에 `nfsdcld`만 쓸 수 있다. 추적 수단이 없으면 knfsd가 90초 유예 기간을 돌고 그동안 v4.1 OPEN이 막힌다. 진입점에 `nfsdcld`와 rpc_pipefs를 넣어 해결했다(v4.1 마운트 0.09초).
2. 그래도 시작의 7~8%는 실패했다. 원인 추정은 이렇다: knfsd는 시작할 때 `nfsdcld`가 추적 파이프를 열기를 약 1초만 기다린다(커널 소스 기준 추정 [추론]). 그 안에 못 열면 추적 없이 유예 기간으로 들어간다. 그런데 **진입점도 agent도 그 결과를 확인하지 않았다.** 진입점은 `grace_ended=N`을 로그에 쓰고 그대로 서비스했고, agent는 `docker run -d`가 돌아오면(knfsd가 뜨기도 전에) job을 `success`로 끝냈다. 즉 정확한 커널 타이밍은 추정이지만, "결과를 확인하지 않고 성공이라 말했다"는 것은 코드로 확인되는 결함이다.
- 테스트도 한몫했다. 1회차 전까지 AC-03·AC-15 테스트는 읽고 쓴 값이 맞는지만 보고 시간은 보지 않아서, 유예 기간에 걸려도 통과했다. verifier는 `grace_ended=Y`와 첫 쓰기 60초 미만 단언을 더한 뒤(r1d) 실패를 잡을 수 있게 했다.

**수정 (두 곳).**
1. 진입점(`entrypoint.sh:40-54`): `rpc.nfsd` 뒤에 `/proc/fs/nfsd/v4_end_grace`가 `Y`인지 확인한다. 아니면 `rpc.nfsd 0`으로 내리고 1초 뒤 다시 띄운다. 5번 안에 안 되면 0이 아닌 코드로 끝난다. NFSv3 인스턴스에도 적용한다(유예 기간은 같은 netns의 NLM 잠금도 막는다). 다 되면 준비 표시 `/run/anf-ready`를 만든다. 컨테이너 파일시스템은 `docker stop`·`start` 사이에 남으므로 시작할 때 먼저 지운다(`:13-14`).
2. agent(`nfs_instance.py:73-105`): `docker run`·`docker start` 뒤에 준비 표시를 기다리고, 컨테이너가 끝나면 로그 끝부분을 넣어 job을 실패시킨다. 이제 `Succeeded`는 "지금 마운트하고 쓸 수 있다"는 뜻이다. 단위 테스트(`test_nfs_instance.py`)에 준비 대기·실패를 먼저 넣고(RED) 구현했다.

**재검증 결과 (2회차).**
- 인스턴스 63개, knfsd 시작 64번(AC-12c의 `docker start` 한 번 포함) 중 **5번(7.8%)이 첫 시도에서 실패했고 모두 두 번째 시도에서 성공**했다(`attempts=2`). 1회차의 추적 실패율(약 7~8%)과 같다. 즉 실패는 사라진 것이 아니라 **숨겨졌다**: 진입점이 잡아서 다시 시작한다.
- 포기(exit 1) 0, serving 줄 없음 0, 90초 대기 0회. 반복 시험 40개(20라운드)에서 첫 쓰기 0.61~3.25 s(새 클라이언트 컨테이너 마운트 시간 포함). 라운드마다 두 번째 볼륨은 job `success` 직후 바로 마운트했고 20개 모두 통과했다. AC-03 첫 쓰기·읽기 0.22 s, AC-15 첫 I/O 0.35 s.
- 대가: 재시작한 인스턴스는 job이 2~4초 길어졌다(3.84~5.69 s, 전체 평균 1.59 s). 그 대신 job이 끝났을 때는 이미 유예 기간이 끝나 있다.
- 첫 쓰기 한도를 60초에서 `FIRST_IO_SECONDS = 10`으로 좁혔다. 이 값은 실패를 놓치지 않으려고 좁힌 것이다.
- 통합 테스트는 131.91 s → 32.5 s로 돌아왔다.

**교훈 (면접에서 말할 수 있는 것).** (1) "성공"을 보고하는 쪽(agent job)이 서비스 상태를 확인하지 않으면 컨트롤 플레인의 `Succeeded`가 거짓말이 된다. (2) 간헐 실패는 원인 추정이 틀려도 "결과를 확인하고 재시도"로 막을 수 있다. 다만 원인(커널 타이밍)은 추정으로 남겼다. (3) 테스트는 값만 보면 안 되고 시간 같은 비기능 조건도 단언해야 한다. 이 실패는 단언이 없어서 1회차 대부분의 시험을 통과했다.

### 5.2 테스트 구조

| 층 | 파일 | 무엇을 확인하나 | 어디서 도나 |
| --- | --- | --- | --- |
| 단위 | `unit/test_volumes.py`, `test_storage_client.py` | 볼륨 본문 규칙·검사 순서·처리기(가짜 agent). agent 클라이언트의 재시도·job 폴링·404 재요청(실제 로컬 HTTP 서버로 urllib 전송도 확인) | Windows(TDD 훅), WSL, CI |
| 단위 | `unit/test_agent_app.py`, `test_flexvol.py`, `test_nfs_instance.py`, `test_jobs.py`, `test_runner.py` | agent 입력 재검사와 job 키, 볼륨 관리자의 명령 순서·멱등·복구(가짜 실행기), 인스턴스 준비 대기, job 표의 중복 방지, 셸 없는 실행기 | Windows, WSL, CI |
| 계약 | `contract/test_volumes_api.py` | 볼륨 라우트의 상태 코드·헤더·본문(TestClient + 가짜 agent) | Windows, WSL, CI |
| 통합 | `integration/test_flexvol_linux.py` (마커 `dataplane`) | 실제 LVM·ext4·Docker·knfsd로 볼륨을 만들고 쓰고 지움. 프로토콜별로 만들어 다른 버전 거절을 보고, 인스턴스 정지 + 언마운트 뒤 복구까지. 4개, 32.5 s | WSL root |
| E2E | `e2e/test_volume_{contract,data,recovery}_live.py` + 도우미 `dataplane_live.py` | anf-api + agent + 클라이언트 컨테이너 마운트로 AC-01~AC-15를 확인 (21개) | WSL root, `ANF_E2E_API_URL` |

- **왜 층을 나눴나.** TDD 훅이 Windows에서 단위·계약 테스트를 돌리므로, 커널이 필요한 부분은 가짜 실행기로 명령 순서만 확인하고(Windows에서도 돈다), 진짜 LVM·knfsd는 통합·E2E에서만 본다. 단위 테스트는 "어떤 명령을 어떤 순서로 부르는가", E2E는 "클라이언트에서 실제로 보이는가"를 맡는다. 가짜 실행기를 쓰는 단위 테스트가 GREEN이어도 데이터 플레인이 동작한다는 증거가 아니라는 것이 이 프로젝트의 규칙이다(skip은 PASS가 아니다).
- **e2e 파일을 왜 나눴나.** 1회차에 verifier가 만든 `test_volume_live.py`가 약 1,300줄이 되어 사용자가 분리를 요청했다. 2회차에 도우미 모듈 `dataplane_live.py`(531줄: 상수, `ApiServer`, `Agent`, `Client`, 픽스처, 데이터 플레인 관찰, 인스턴스 로그 수집)와 주제별 세 파일로 나눴다: 계약(AC-01, 05, 06, 07, 08, 10, 13; 463줄), 클라이언트에서 보이는 데이터 효과(AC-02, 03, 04, 09, 15, 유예 기간 반복; 272줄), 실패와 복구(AC-11, 12; 202줄). 옮길 때는 `ast`로 최상위 정의를 그대로 잘라 붙였고, 78개 블록 중 77개가 바이트 그대로 같다(나머지 하나는 파일마다 다시 쓴 `pytestmark`). 픽스처는 도우미 모듈에 두고 `conftest.py`에서 등록한다(시험 파일이 직접 import하면 ruff F811이 난다). 파일 맨 위 docstring에 확인하는 AC와 실행 명령을 적었다.
- **CI와의 관계.** 데이터 플레인 테스트(`dataplane` 마커: E2E 21 + 통합 4)는 CI에서 빠지고, 단위·계약 테스트와 계정·풀 E2E는 CI에서 돈다.

---

## 6. 개발 과정

1. **조사.** anf-researcher가 볼륨 API 계약, 서비스가 채우는 값, 비동기 동작(녹화 V1~V6), 제약, ONTAP 대응을 조사했다. 조사 상태는 "한도 도달"이었다. 필수 질문 다섯 가지는 답했고, ONTAP `POST /api/storage/volumes`의 원본 HTTP 응답, data LIF, 볼륨이 가득 찼을 때의 errno, 클라이언트 `df` 표시는 확인하지 못했다. 설계를 막지 않는다고 판단했다: agent의 job 모델은 클론이 정하고 차이를 표시한다(R-04), errno는 S1이 클론의 동작을 재고 수락 기준에서 ANF 값으로 고정하지 않는다.
2. **스파이크.** 설계 전에 S1(저장 방식: A/B/C 비교)을 메인 세션이 실행했고, 그 사이 다른 세션이 S2(처리량 제한)를 같은 WSL에서 돌렸다. 두 세션이 같은 knfsd를 건드릴 수 있어서 S1은 중간부터 `exportfs -ra`를 쓰지 않고 자기 export만 바꿨다. S1은 측정 실수를 하나 정정했다(`dd | tail`이 오류 줄을 잘라 "오류 없이 성공"으로 오독). S2는 호스트 knfsd 하나로는 v4.1 볼륨별 제한이 불가능함을 찾았고, 새 변형 T1n을 제안했다.
3. **설계.** 설계안과 선택지 4개를 사용자에게 제시했고 사용자가 모두 추천안으로 확정했다. **사람이 내린 결정**: D-11 = C(결정 1), 마운트 경로는 `rootdir`(결정 2), 최소 크기는 검증용 환경 변수(결정 3), 데이터 효과가 없는 속성은 400(결정 4). 구현 중간에 S2 결과를 설계에 넣으라는 사용자 지시가 있었고, 볼륨 인스턴스(결정 17, 18)가 이번 사이클에 들어왔다. 그래서 호스트 knfsd 기반 구현을 인스턴스 기반으로 바꾸는 작업이 구현 중에 생겼다(`flexvol.py`를 T1n으로 변경, 호스트 export·unlock 제거).
4. **구현.** Claude가 TDD 훅 아래서 구현했다(모듈마다 RED 확인 뒤 GREEN). 순서는 `arm_rules` → `runner`/`jobs`/`flexvol` → `volumes` → `nfs_instance`와 이미지 → `agent_app` → `storage_client` → `arm_app`. 구현 중에 알게 된 것들(`0.0.0.0/0` 거절, `mp` 옵션, 삭제 순서, `ns` 공유 마운트, job 키 변경, 인스턴스 v4.1의 grace)은 설계 문서 "구현 중 변경"에 기록했다. 스모크(검증 기록 아님)에서 NFSv3·NFSv4.1 볼륨이 1.5~2.5 s에 `Succeeded`였다. 공통 코드(`arm_rules.py`, `arm_app.py` 등)를 바꿨으므로 계정·풀을 `in_progress`로 되돌리고 AC-14로 회귀를 검증하는 규칙이 이번에도 적용됐다.
5. **검증 1회차.** PASS 14 / FAIL 1(AC-03 불안정). 테스트 결함도 3건 나왔다(CV-3 PATCH 기대 코드, AC-15의 `addr=` 정규식이 `clientaddr=`에 먼저 걸림, 유예 기간 단언 없음). 모두 제품이 아니라 테스트를 고쳤다.
6. **수정과 재검증 (5.1절).** 수정은 인스턴스 시작 경로 전체에 걸쳐서 영향받는 기준만이 아니라 볼륨 e2e 전체를 2회차에서 다시 돌렸다(AC-14는 anf-api가 바뀌지 않아 1회차 결과 유지). PASS 15/15. 사용자 요청으로 e2e 파일도 이때 나눴다. 사용자가 검증이 끝나면 commit·push·PR·merge하라고 지시했다.
7. **merge.** 브랜치 `feature/volume` 커밋 `501d699`(내용 해시 `8bb57d91…` = 검증한 값) → PR #7, GitHub Actions 통과(579 passed, 25 deselected, skip 0) → squash merge로 `main`의 `8a4002d`. merge 뒤 해시도 같다. 계정·풀은 AC-14 회귀 PASS로 `done`에 복귀했다.
8. **개념 문서(이 문서).**

AI와 일한 방식으로 설명할 수 있는 것: 조사 → 스파이크(사실을 재고 설계를 바꿈) → 설계(사람이 선택지를 결정) → 테스트 먼저 구현(TDD 훅) → 구현자와 다른 에이전트의 실환경 검증(검증자는 제품 코드를 고치지 않고 테스트만 만들었다) → 실패 시 수정과 재검증 → 개념 문서. 이번에는 검증자가 **통과하는 테스트의 빈틈**(시간 단언 없음)까지 찾았다는 점이 중요하다.

---

## 7. Interview Q&A

### Q1. (개념) What does an Azure NetApp Files volume look like to a client, and how is the mount path formed?

**A.** A volume is an ARM resource under a capacity pool, and also a real NFS export. The client mounts `<mount target IP>:/<creationToken>`. The creationToken is the file path, immutable after creation, and the IP comes from `mountTargets[0].ipAddress`. The create call returns 201 with `Creating`, and the mount target appears after completion. In the recordings, creation takes about five minutes, while my clone takes about two seconds. The closest ONTAP concept for the creationToken is the junction path in the SVM namespace. I should be careful: no public document says ANF mounts its ONTAP volume at that junction path. The only hint I found is `svm` in the tenant ID of the recorded response, so I label it an inference.

### Q2. (개념) How do you map your clone's components to ONTAP, and which mappings can you not claim?

**A.** I use ONTAP vocabulary as my own design analogy. The dm-thin pool plays the aggregate, a thin LV with ext4 plays the FlexVol, the `ns` directory plays the SVM namespace, the export path plays the junction path, and the instance IP plays a data LIF. The agent's job API follows ONTAP's job states and the 300-second retention, which I did confirm from the ONTAP docs. What I cannot claim is that ANF implements it this way. I found no public source for ANF's internals, and I never found the ONTAP source text for data LIFs or the NFSv4 pseudo filesystem. So I say "closest analogue", not "equals". Also, ONTAP serves many volumes from one SVM, while my clone runs one NFS server per volume.

### Q3. (설계) Why did you store volumes on dm-thin with ext4 instead of btrfs subvolumes?

**A.** I ran a spike comparing three options with the same scenarios. With btrfs subvolumes, an NFSv3 client, as the file owner with `no_root_squash`, could append to a file in a read-only snapshot, and the server-side content actually changed. The client `df` also showed the whole pool size, and the snapshot root had the same device and inode as the volume root. With a thin LV and ext4, snapshots were read-only over both v3 and v4.1, `df` showed the volume size, and exceeding the size gave ENOSPC. A restore to a new volume was a thin snapshot, about 0.13 seconds. I mount ext4 with `nodelalloc` because only then was the leftover data after the error a prefix of the original. The tradeoff is that the thin pool, not the volume quota, pays for snapshots.

### Q4. (설계) Why does each volume get its own NFS server instance and IP? Isn't that wasteful?

**A.** It is a deliberate cost for per-volume throughput limits, which come in a later feature. In a spike, I put a tc limit on each volume's IP using one host knfsd. NFSv3 worked, but an NFSv4.1 client merged connections to all those IPs into one, because the server returned the same server owner and clientid. An unlimited volume got throttled by another volume's class. Since knfsd runs per network namespace, one containerized instance per volume gives each volume its own server identity and connection. Measured idle memory is about 4 MiB per instance, so the 126 IPs fit the memory limit. The tradeoff is that real ANF can share a mount IP across volumes, so this is a documented difference. The limit itself is not implemented yet.

### Q5. (설계) How do you make volume creation safe against crashes in the middle?

**A.** Every step is idempotent and keyed by the volume's `fileSystemId`, which anf-api generates at PUT time and sends as the uuid. The agent creates the LV, then the filesystem, the mount, the root setup, and the instance, and each step checks real state first. If anything dies, the same request resumes. I do not store job IDs: if the agent restarts, the job lookup returns 404 and the client just re-sends the same POST. State lives in LVM tags, so no separate database can disagree with reality. I verified it by killing the agent at three points: after job start, after LV creation, and after mount. Each recovered within 2.5 to 4.5 seconds with exactly one LV. The tradeoff: there is no rollback code, so a failed create stays `Failed` and holds its quota until retried or deleted.

### Q6. (디버깅) Tell me about the hardest bug in this feature.

**A.** In verification, about 7 to 8 percent of NFSv4.1 instances started in a 90-second grace period. The API said `Succeeded`, but the client's first write blocked for 102 seconds. Evidence: the kernel log said "Unable to initialize client recovery tracking", and the instance log showed the grace period had not ended. My entrypoint started `nfsdcld`, but nothing checked the result, and the agent finished the job as soon as `docker run` returned. The fix has two parts. The entrypoint checks `v4_end_grace` and restarts knfsd up to five times. The agent waits for a ready marker. Re-verification showed 5 of 64 starts needed a restart, all recovered, and zero long waits. The kernel timing cause is still an estimate. Also, my test only compared values, not timing, so I added a timing assertion.

### Q7. (한계) Where does your volume differ from real ANF, and which differences are guesses?

**A.** Some differences are intentional. One NFS server and IP per volume, a hard size limit enforced by the block device, a two-second create, and immediate 400 rejection of properties whose data effect is not built yet. Others are my choices where ANF's behavior is unknown: the 400 BadRequest for a duplicate file path, and the errno. My clone returns ENOSPC, and the error appears at `fsync`, not `write`. Real ANF's errno is unconfirmed. What the clone does not do yet: throughput limiting, snapshots, and export policy input. Also, after a delete, a client that is still mounted sees I/O errors and stale file handles, and I do not know what real ANF shows. I mark these as clone decisions, never as observed ANF behavior.

### Q8. (테스트/REST) How did you test a feature that spans a REST API, a storage agent, and the Linux kernel?

**A.** I used layers. Unit tests use a fake command runner, so they check which commands run in which order, on Windows too. Contract tests check status codes, headers, and bodies with a fake agent. Integration and end-to-end tests run on real LVM, Docker, and knfsd, with client containers that mount over NFS and check what the client sees: file content, `df`, ENOSPC, and the error after delete. Pass or fail is judged by exit code and complete stderr, because an earlier measurement of mine misread a truncated `dd` output. A skipped test never counts as a pass. Data-plane tests are excluded from CI with a marker instead of skipping, because CI fails on any skip. The one-file 1,300-line end-to-end suite was split into a helper module and three themed files.

### Q9. (설계) Why did you reject properties like `exportPolicy` and `snapshotDirectoryVisible` instead of just storing them?

**A.** Because storing a value that has no effect makes the clone a state-only simulation, which the project explicitly rejects. If a client sets a custom export rule and gets 201, it would believe the rule is enforced. So I accept a deferred property only if it equals what the clone really does, and otherwise return 400 with a message saying it is not supported. The same-value rule matters because a PUT update must resend required properties. Each later feature, like export policy or resize, opens its property when it implements the real effect. The tradeoff is that a real SDK client sending those values gets rejected, where real ANF would accept them.

### Q10. (다시 한다면) If you did this again, what would you do differently?

**A.** Three things. First, I would put the readiness check into the first design. The principle that `Succeeded` must mean "serving" was learned from the grace-period failure, and it would have saved a verification round. Second, I would try to confirm the unknowns against real systems: the ONTAP job response for volume creation, the client errno when a volume is full, and how real ANF treats clients of a deleted volume. Third, I would measure the kernel's wait for the client-tracking daemon directly, instead of leaving the cause as an estimate. For the next feature, throughput limiting, I would first decide which clock to judge by, because my WSL guest clock runs about nine percent slower than the host.

---

## 부록. 이 문서가 쓰지 못한 것

브리프·스파이크·검증 보고서에 근거가 없거나 [미확인]이라 쓰지 못한 것이다.

- ANF 볼륨과 ONTAP FlexVol/SVM/data LIF의 직접 대응. 공개 근거가 없어 모두 [추론]으로 남겼다. data LIF와 NFSv4 pseudo-fs의 ONTAP 원문은 받지 못했다.
- `fsid`(export 옵션)와 `fileSystemId`에 대응하는 ONTAP 개념. 브리프에 없어서 쓰지 않았다.
- aggregate의 ONTAP 정의 원문. 대응은 `aggregates[].name`을 받는 REST 예시에 의존한 클론의 비유다.
- ONTAP `POST /api/storage/volumes`의 원본 HTTP 응답(202 + job 링크라는 원문).
- 할당량 초과 때 ANF NFS 클라이언트의 errno(ENOSPC/EDQUOT), 클라이언트 `df`가 보이는 크기.
- 파일 경로 중복, 불변 속성 변경, 용량 초과, export 규칙 오류의 ANF HTTP 코드·`error.code`·동기 여부.
- NFSv4.1 볼륨의 기본 export 규칙 모양(녹화가 NFSv3뿐), PATCH로 `protocolTypes`·`serviceLevel`을 바꿀 때의 실제 동작, `subnetId` 변경 가능 여부.
- 볼륨을 삭제할 때 마운트 중인 클라이언트가 실제 ANF에서 받는 오류.
- NFSv3 NLM 잠금과 NFSv4 상태 복구의 실제 동작(시험하지 않음).
- knfsd가 `nfsdcld`의 추적 파이프를 기다리는 시간(약 1초)은 커널 소스 기반 추정이고 직접 재지 않았다.
- 인스턴스 안 rslave 전파의 FR-05 스냅샷 하위 마운트 동작(v3 클라이언트가 하위 마운트로 넘어가면 `Stale file handle`이 났다고 설계 문서에 있으나, 원인을 조사하지 않았다. FR-05에서 다룬다).
