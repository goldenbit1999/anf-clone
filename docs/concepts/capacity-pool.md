# 용량 풀 (capacity pool)

> 용량 풀은 볼륨이 쓸 용량과 처리량을 사는 "예산이자 과금 단위"다. 클라이언트가 마운트하는 대상이 아니고, 이 클론에서는 데이터 플레인에 아무것도 만들지 않는 컨트롤 플레인 리소스다. 이 기능의 내용은 세 가지다. (1) 크기와 서비스 수준에서 처리량 예산을 계산한다. (2) 볼륨이 생기면 지켜야 할 용량 규칙(볼륨 할당량 합 ≤ 풀 크기)을 미리 구현한다. (3) 계정과 달리 PATCH가 비동기인 리소스를 공통 LRO 계층 위에 얹는다.

FR-03(용량 풀)을 다룬다. 공통 비동기 작업(LRO) 계층(작업 상태 URL, 워커, 재시작 복구, 결함 주입)은 [계정 문서](netapp-account.md)에 자세히 있다. 이 문서는 풀이 그 계층을 어떻게 쓰는지와, 풀 때문에 달라진 점만 설명한다.

근거 표시는 브리프를 따른다.

| 표시 | 뜻 |
| --- | --- |
| [스펙] | Azure REST API 스펙(OpenAPI/TypeSpec)에 적혀 있다 |
| [문서] | Microsoft Learn 문서에 적혀 있다 |
| [녹화] | Azure SDK 테스트 세션 녹화에서 실서비스 응답으로 관찰했다. 문서로 보장된 동작은 아니다 |
| [추론] | 근거에서 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |

---

## 1. ANF에서는

### 1.1 풀이란

- 용량 풀은 계정 아래의 ARM 추적 리소스 `netAppAccounts/{a}/capacityPools/{p}`다. 필수 속성은 `size`(바이트, 1 TiB 배수)와 `serviceLevel`이다 [스펙]. 풀 이름은 1~64자, 패턴 `^[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}$`이고 계정 안에서 고유하다 [스펙][문서]. 응답의 `name`은 `"{account}/{pool}"`이다 [스펙][녹화].
- **풀은 "용량·처리량 예산이자 과금 단위"다.** "You purchase capacity and throughput through capacity pools, which are the main units of billing." 풀은 프로비저닝·과금의 단위이고 볼륨은 소비의 단위다. 시간마다 풀 크기와 서비스 수준을 측정해 과금하며, 실제로 쓴 양과는 무관하다 [문서].
- 풀은 계정 하나에만 속하고 다른 계정으로 옮길 수 없다. 풀 하나는 서비스 수준 하나만 가진다. 볼륨을 모두 지우기 전에는 풀을 지울 수 없다 [문서].
- **풀 자체는 마운트 대상이 아니다.** 볼륨만 마운트된다 [문서]. 풀을 만들거나 지워도 클라이언트에서 보이는 변화는 없다 [추론] (볼륨이 풀 아래에만 있고 마운트 대상이 볼륨의 export이기 때문).

### 1.2 서비스 수준이 처리량을 정하는 방식

서비스 수준은 "볼륨 할당량 대비 허용 최대 처리량"의 단가다 [문서].

| 서비스 수준 | 처리량 |
| --- | --- |
| Standard | 16 MiB/s per TiB |
| Premium | 64 MiB/s per TiB |
| Ultra | 128 MiB/s per TiB |

Flexible, StandardZRS(스펙 enum에만 있고 "will be deprecated soon"), Elastic(shared QoS)도 있지만 이번 범위 밖이다 [문서][스펙].

- **Auto QoS:** 볼륨 처리량 한도 = 수준 단가 × 볼륨 할당량(TiB, 2진 단위). 문서 예: Premium 2 TiB 볼륨은 128 MiB/s, Premium 100 GiB 볼륨은 6.25 MiB/s. "regardless of the capacity pool size or the actual volume consumption", 즉 풀 크기나 실제 사용량과 무관하다 [문서].
- **Manual QoS:** 볼륨마다 처리량을 따로 정하고, 볼륨 처리량의 합은 풀 총 처리량(풀 TiB × 수준 단가)을 넘을 수 없다. 예: Ultra 10 TiB는 1,280 MiB/s [문서].
- 풀 GET에는 `totalThroughputMibps`(풀 총 처리량)와 `utilizedThroughputMibps`(풀에서 쓰인 처리량)가 읽기 전용으로 나온다 [스펙]. 녹화에서 4 TiB Premium 풀은 `totalThroughputMibps: 256.0`(= 4 × 64)이었고, 100 GiB 볼륨 하나를 만든 뒤 `utilizedThroughputMibps`는 6.25였다 [녹화]. 볼륨에 I/O가 없던 시점의 값이므로 실측 사용량이 아니라 볼륨들에 **배정된 한도의 합**으로 보인다 [추론].
- 스펙 예시는 같은 4 TiB Premium 풀을 `281.474`(10진 TB 계산)로 적었지만, 실서비스 값은 256.0(2진 TiB)이다 [스펙 vs 녹화].
- 한도에 닿은 클라이언트는 I/O 오류가 아니라 지연 증가와 처리량 상한을 본다 ("the system queues extra I/O requests and latency can rise rapidly while throughput stays capped") [문서]. 이 부분은 FR-08의 몫이다.

### 1.3 크기 규칙과 변경 규칙

- 크기: 최소 1 TiB, 최대 2,048 TiB, 1 TiB 단위로 늘리고 줄인다. 최대는 지원 요청으로도 늘릴 수 없다 [문서]. API 단위는 바이트이고 1099511627776의 배수여야 한다 [스펙]. stable(2026-08-01)은 1 TiB 단위이고, preview 버전은 512 GiB도 허용한다 [스펙]. Basic 네트워크 기능 볼륨이 있으면 최소 4 TiB다 [문서] (이 클론은 네트워크 기능을 다루지 않는다).
- 볼륨 할당량(quota) 합은 풀 크기를 넘을 수 없다 [문서].
- **풀을 줄일 때의 하한**은 문서마다 표현이 다르다. 두 문서는 "볼륨 할당량 합" 기준이고, RP 오류 문서 하나는 "볼륨 usedBytes 합"을 말한다. 할당량 합 쪽이 두 곳이고 볼륨 생성 규칙과도 맞아서 그쪽을 택했다 [추론].

| 속성 | 생성 뒤 변경 | 근거 |
| --- | --- | --- |
| `size` | 가능 (PATCH, PUT) | [스펙][문서] |
| `qosType` Auto → Manual | 가능, 되돌릴 수 없는 영구 변경 | [문서][녹화 PATCH·PUT 둘 다] |
| `qosType` Manual → Auto | 불가. 오류 코드는 [미확인] | [문서] |
| `serviceLevel` | PATCH 모델에 없다 [스펙]. RP 오류 문서가 "ServiceLevel cannot be changed."를 "볼륨이 있는 풀"의 변경에 대해서만 말하므로, 빈 풀은 PUT으로 바꿀 수 있는 것으로 읽힌다 | [문서][추론] |
| `encryptionType` | 생성 때만 | [스펙][문서] |

### 1.4 작업별 응답: 계정과 다른 점

| 작업 | 응답 | 헤더 | 근거 |
| --- | --- | --- | --- |
| PUT (새 풀) | `201`, `Creating` | 녹화는 `Azure-AsyncOperation`만. 스펙은 `Location` + `Retry-After`로 정의 | [녹화] vs [스펙] |
| PUT (기존 풀) | `200`, `Updating` | `Azure-AsyncOperation` | [녹화] |
| **PATCH (tags만이어도)** | **`202`**, 본문에 풀 전체와 `provisioningState: Patching` | `Azure-AsyncOperation` + `Location` | [녹화]. 스펙은 202 본문이 없다 [스펙] |
| DELETE | `202`, 본문 없음 | 두 헤더 | [녹화] |
| DELETE (없음) | `204` | 없음 | [스펙] |
| DELETE (볼륨이 남음) | 즉시 `409 CannotDeleteResource`, 메시지에 볼륨 ID, `x-ms-failure-cause: gateway`. 풀은 그대로 | 없음 | [녹화] |

핵심 차이는 PATCH다. 계정의 tags PATCH는 추적 헤더 없는 동기 `200`이었는데 [녹화], 풀 PATCH는 tags만 바꿔도 `202` + `Patching`이었다 [녹화]. PATCH의 동기/비동기는 리소스마다 다르다. 풀 PATCH 작업이 끝나는 데는 약 0.3~0.5초였다 [녹화].

### 1.5 용량·처리량 규칙을 어길 때

문서의 오류 문구는 알지만 HTTP 코드, `error.code`, 동기·비동기 여부는 모두 **[미확인]**이다.

- "Pool size too small for total volume size." (제목). NetApp KB의 메시지 예: "The capacity pool size of … bytes is too small for the combined volume size of … bytes of the capacity pool. Make sure that the total size of all the volumes in the capacity pool does not exceed the size of the capacity pool." (KB 원문은 로그인이 필요해서 검색 요약만 확인했다) [문서]
- "ServiceLevel cannot be changed.", "Requested throughput not available"(Manual QoS 처리량 초과) [문서]. 녹화 176개의 `error.code` 집계에도 용량·처리량 관련 코드는 0건이었다 [녹화].

---

## 2. ONTAP에서는

솔직한 답은 **"풀에 1:1로 대응하는 ONTAP 객체를 공개 자료에서 찾지 못했다"**이다 [미확인]. ANF는 "NetApp's bare metal with ONTAP storage OS running inside the Azure datacenter"인 PaaS라는 정도만 공개돼 있다 [문서]. 풀이 애그리게이트, SVM, QoS 정책 그룹 중 무엇으로 구현되는지는 모른다.

| ANF 개념 | 닮은 ONTAP 개념 | 말할 수 있는 수준 |
| --- | --- | --- |
| 풀 = 용량·처리량 예산 + 과금 단위 | (Azure 쪽 개념) | [문서] 과금 단위라는 것은 Azure 측 사실이다 |
| 풀 크기 | 애그리게이트의 물리 용량과는 다른 것으로 보인다 | [추론]. 풀은 "fixed SKUs that you purchased"로 측정되고 사용량과 무관하게 과금된다 [문서]. 그래서 물리 공간이 아니라 볼륨 할당량에 대한 논리적 상한(예약)에 가깝다. ONTAP 애그리게이트의 정의는 이번 조사에서 원문을 확인하지 못했다 [미확인] |
| 볼륨 할당량 합 ≤ 풀 크기 | thin provisioning(오버커밋)의 반대인 엄격한 예약 | [추론]. ANF는 풀 수준에서 합 ≤ 크기를 강제한다 [문서]. ONTAP의 `space-guarantee none`이 오버커밋을 허용한다는 것은 원문 미확인이고, ANF 백엔드 볼륨이 thin인지는 공개되지 않았다 [미확인] |
| Auto QoS 볼륨 한도(할당량에 비례) | ONTAP adaptive QoS 정책 그룹 | [추론]. adaptive QoS는 볼륨 크기 TB당 IOPS 상한을 두고 크기에 따라 상한을 자동으로 바꾼다 (검색 요약만, 원문 미확인). "크기에 비례하는 상한"이 닮았지만 adaptive QoS는 IOPS, ANF는 MiB/s다. ANF가 실제로 이것을 쓰는지는 공개되지 않았다 |
| Manual QoS 볼륨 처리량(고정 MiB/s) | QoS 정책 그룹의 `max-throughput` | [추론]. 원문 미확인 |
| 풀 총 처리량 | 직접 대응 없음 | [추론]. Manual 풀의 "볼륨 한도 합 ≤ 풀 한도"는 공유 상한이 아니라 **배정 검사**다. ONTAP shared policy group의 정확한 의미는 [미확인] |
| 서비스 수준 | 직접 대응 없음 | [추론]. 문서는 서비스 수준을 처리량 상한 단가로 정의하고, 네 수준 모두 "bare-metal flash performance"라고 쓴다. 하드웨어 계층이 다르다는 공식 설명은 없다 |

면접에서 안전한 문장: "ANF 문서상 풀은 용량과 처리량을 사는 과금·예산 단위이고, 볼륨 처리량 한도는 풀의 서비스 수준과 QoS 유형으로 정해진다. ONTAP 쪽에서 가장 닮은 개념은 QoS 정책 그룹(Auto는 adaptive QoS)이지만, ANF가 내부적으로 그렇게 구현한다는 공개 자료는 없다."

이 때문에 풀은 ONTAP 객체(애그리게이트, SVM, QoS 정책 그룹)를 만들지 않는다 (설계 결정 2). 계정이 SVM을 만들지 않은 것과 같은 이유다. 대응이 [미확인]인 것을 코드로 굳히면 면접에서 추측을 사실처럼 말하게 된다.

---

## 3. 이 프로젝트에서는

### 구조

```
  클라이언트
     |  PUT/GET/PATCH/DELETE  .../netAppAccounts/{a}/capacityPools/{p}
     v
  arm_app.py      풀 라우트 (api-version 검사, 상관 ID, 오류 형식은 계정과 공통)
     |                         PATCH는 202 + 풀 본문 + 두 헤더 (_tracking_headers)
     v
  capacity_pools.py   본문 검사, 처리량 계산, 용량·QoS 규칙, 부모 검사
     |   한 트랜잭션: 규칙 검사 + 리소스 상태 변경 + 작업 행 생성
     v
  state_store.py  SQLite (list_children, ensure_no_children)
     ^
     |  종결되지 않은 작업을 찾아 처리기 실행 -> 결과를 한 트랜잭션으로 반영
  lro.py          워커 (공통). 풀의 처리기는 아무것도 하지 않는다

  (storage agent 호출 없음: 풀은 컨트롤 플레인 전용)
```

계정 때와 달라진 점은 네 가지다. (1) PATCH도 작업을 만든다. (2) 규칙 검사가 풀 안에서 자식(볼륨) 행을 읽는다. (3) 결함 주입 키를 처리기에서 만든다. (4) 실패한 PATCH를 되돌린다.

### 코드 따라가기

#### (1) 본문 검사: 쓸 수 있는 속성만 통과시킨다 — `capacity_pools.py:51-134`

- `_check_size` (`capacity_pools.py:51-57`): 정수이고 `1 TiB`의 배수이며 1~2,048 TiB여야 한다. `bool`은 파이썬에서 `int`의 하위 타입이라 따로 거른다. 어기면 `400 InvalidRequestContent`.
- `_check_service_level` (`capacity_pools.py:60-67`): Standard·Premium·Ultra만 받는다. Flexible과 StandardZRS는 "The value 'Flexible' of 'properties.serviceLevel' is not supported by this ANF clone."로 거절한다. 실제 ANF에는 있으나 미룬 기능을 조용히 무시하지 않고 거절해 "되는 줄 알았다"를 막는다.
- `_check_properties` (`capacity_pools.py:70-105`): 읽기 전용 속성(`provisioningState`, `poolId`, 두 처리량 값)은 요청에 있어도 무시한다(`:76-77`). PUT은 `size`, `serviceLevel`, `qosType`, `encryptionType`, `coolAccess`를, PATCH는 앞의 `serviceLevel`·`encryptionType`을 뺀 나머지를 허용한다(`:46-48`, PATCH 모델에 `serviceLevel`이 없기 때문 [스펙]). PATCH에 `serviceLevel`을 보내면 "모르는 속성"으로 `400 InvalidRequestContent`다. `coolAccess: true`, `encryptionType: Double`, `customThroughputMibps`도 같은 방식으로 거절한다.
- 오류 함수(`invalid_content`, `unknown_property`, `unsupported_property`, `check_tags`, `not_found`, `location_conflict`)는 계정과 같이 쓰도록 `arm_rules.py`로 옮겼다 (`arm_rules.py:92-118`).

#### (2) 처리량 계산 — `capacity_pools.py:137-139`, `:142-163`

- `total_throughput_mibps`는 `size / 2^40 × 단가`다. 4 TiB Premium은 256.0, 8 TiB Premium은 512.0, Standard 2 TiB는 32.0, Ultra 1 TiB는 128.0이다. **2진 TiB를 쓴 이유**는 실서비스 녹화가 256.0이었고 스펙 예시의 281.474(10진)가 아니었기 때문이다 (설계 결정 10).
- 이 값은 저장하지 않고 응답할 때 계산한다 (`capacity_pools.py:157`). 크기나 서비스 수준을 바꾸면 처리량이 자동으로 다시 계산된다.
- **`utilizedThroughputMibps`는 0.0 고정이다** (`capacity_pools.py:159`). 볼륨이 아직 없기 때문이다. 녹화에서 이 값은 "볼륨 처리량 한도의 합"으로 보이므로(6.25 = 100 GiB × 64) [추론], 볼륨 사이클에서 합으로 계산한다.
- **이 값이 실제 I/O를 제한하지는 않는다.** 클론은 처리량을 계산해 보여 줄 뿐 어떤 cgroup 제한도 걸지 않는다. 실제 제한은 FR-08(처리량 제한)과 스파이크 S2에서 한다.

#### (3) 갱신 규칙 — `_apply_changes`, `capacity_pools.py:173-195`

PUT 갱신과 PATCH가 같은 함수를 쓴다. 한 트랜잭션 안에서 부르므로 검사와 쓰기 사이에 다른 요청이 끼어들 수 없다 (`BEGIN IMMEDIATE`, 계정 문서 §3 (3)).

1. **QoS 단방향** (`:177-180`): 현재 `Manual`인데 `Auto`로 바꾸려 하면 `400 BadRequest` "The QoS type of a capacity pool can't be changed from Manual to Auto." Auto → Manual만 된다 [문서]. 이 오류의 코드는 실서비스에서 [미확인]이라 클론이 `BadRequest`로 정했다 (설계 결정 7).
2. **서비스 수준은 빈 풀에서만** (`:181-183`): 값이 바뀌고 자식 행(`tx.child_ids`)이 하나라도 있으면 `400 BadRequest` "ServiceLevel cannot be changed." (설계 결정 5). 지금은 풀의 자식이 볼륨뿐이라 "볼륨이 있는 풀"과 같다.
3. **크기 하한** (`:184-194`): 풀 아래 모든 볼륨 행의 `usageThreshold` 합을 구해 새 `size`가 더 작으면 `400 BadRequest`와 KB 문구를 낸다. **하한은 사용량이 아니라 할당량의 합이고, 상태와 무관하게 모든 볼륨 행이 합계에 들어간다.** 설계 §6의 "볼륨 행 자체가 예약이다" 규칙이다. 생성 중(`Creating`), 실패(`Failed`), 삭제 중(`Deleting`)인 볼륨도 자원이 남아 있을 수 있으므로 용량을 돌려주지 않는다.
4. 돌려주는 값은 `{**props, **changes}`다. 요청에 없는 속성은 기존 값이 유지된다 (설계 결정 8).

볼륨 행을 읽는 `Tx.list_children(parent_id, type)`은 `state_store.py:145-150`에 새로 생겼다.

#### (4) PUT — 부모 검사가 생성 트랜잭션 안에 있다 — `capacity_pools.py:217-266`

- 새 풀이면 같은 트랜잭션에서 부모 계정을 읽는다 (`:228`).
  - 계정이 없으면 `404 ParentResourceNotFound`. 문구는 볼륨의 부모 풀이 없을 때 실서비스가 낸 게이트웨이 메시지를 따랐다 [녹화] (`:229-234`).
  - 계정이 `Deleting`이면 `409 Conflict` (`:235-239`). 계정 삭제가 끝난 뒤 고아 풀이 남지 않게 한다. `Conflict`라는 코드는 클론의 선택이다. 이 상황의 실서비스 응답은 [미확인]이다 (설계 결정 6).
  - 생성에는 `size`와 `serviceLevel`이 필수다 (`:240-242`, [스펙]의 `required`).
  - 기본값은 `qosType: Auto`, `encryptionType: Single`, `coolAccess: false`, 새 UUID `poolId`다 (`:246-249`). `Creating` 상태의 리소스와 `CREATE` 작업을 한 트랜잭션에 쓴다 (`:252-254`). 라우트는 `201`을 준다.
- 기존 풀이면 `location`이 다르면 `409 InvalidResourceLocation` (`:255-256`). 같으면 `_apply_changes`를 거쳐 `Updating`과 `UPDATE` 작업(`200`)이다. 이전 tags·properties를 `previous`로 작업에 남긴다 (`:259-265`). tags는 계정처럼 PUT이 맵 전체를 바꾼다.
- 부모가 `Deleting`인지 읽는 것과 계정 DELETE가 자식을 읽는 것이 모두 쓰기 잠금 아래에 있다. 그래서 "풀을 만드는 요청"과 "계정을 지우는 요청"이 동시에 와도 고아 풀이 생기지 않는다 (설계 §6).

#### (5) PATCH — 비동기 202, 새 값을 바로 쓴다 — `capacity_pools.py:269-290`, `arm_app.py:177-187`

- `patch_pool`은 tags만 바꿔도 `Patching` 상태로 바꾸고 `PATCH` 작업을 만든다. 계정의 `patch_account`(동기, 작업 없음)와 다르다. 이유는 녹화다 [녹화 N2, P1].
- 라우트는 `202`에 풀 본문(`Patching`)을 싣고 `_tracking_headers(request, op)`로 `Location`과 `Azure-AsyncOperation` 두 헤더를 붙인다 (`arm_app.py:185-187`). `_tracking_headers`는 원래 계정 DELETE용이었는데 풀의 PATCH·DELETE가 같이 쓰도록 `arm_app.py:63-66`에 공통으로 뒀다.
- **202 본문은 바뀐 뒤 값이다.** `res.tags`와 `res.properties`를 먼저 새 값으로 쓰고 `Patching`으로 응답한다 (`capacity_pools.py:285-288`). 녹화(N2)의 202 본문은 바뀌기 전 tags였다 [녹화]. 클론이 의도적으로 다르게 한 부분이다 (설계 결정 9, 검증 1회차 추가 관찰 3). 바뀌기 전 값을 보이려면 작업에 요청 내용을 따로 저장해야 해서 스키마가 바뀌기 때문이다.
- PATCH 본문에 `location`이 있고 기존과 다르면 `409 InvalidResourceLocation`이다 (`:279-280`). 없는 풀이면 `404`다.

#### (6) 실패한 PATCH는 이전 값으로 되돌린다 — `lro.py:137-149`

- 새 값을 바로 썼기 때문에, 워커가 처리 중 실패하면 리소스를 원래대로 돌려야 한다. `_finish`는 작업이 실패했고 action이 `UPDATE`나 `PATCH`이며 `previous`가 있으면 tags와 properties를 `previous`로 되돌리고 `Failed`로 표시한다 (`lro.py:144-147`). 계정 사이클에서는 UPDATE만 해당했고, PATCH는 풀 사이클에서 공통 코드에 들어왔다.
- 리소스와 작업의 상태를 같은 트랜잭션에서 바꾸므로 둘이 따로 놀지 않는다 (`lro.py:139-149`).
- 검증 1회차에서 실제로 확인했다. tags를 바꾸고 `size`를 8 TiB로, `qosType`을 Manual로 바꾸는 PATCH에 실패를 주입하면 202 본문은 새 값을 보였고, 작업이 `Failed`가 된 뒤 풀 GET은 `Failed` 상태에 tags·size·qosType이 모두 PATCH 전 값이었다.
- 실패 뒤 회복은 PUT이나 PATCH로 다시 보내는 것이다 (`Failed → Updating/Patching → Succeeded`). ANF 오류 문서가 실패한 풀에 tag를 추가해 update하라고 쓰는 것과 맞다 [문서].

#### (7) DELETE와 자식 검사 — `capacity_pools.py:293-306`, `state_store.py:152-164`

- 풀이 없으면 `None`, 라우트는 `204`. 있으면 `tx.ensure_no_children(rid)`를 부른 뒤 `Deleting`과 `DELETE` 작업을 만든다 (`:302-305`). 라우트는 본문 없는 `202`에 두 헤더(`arm_app.py:189-198`).
- `ensure_no_children`은 계정 DELETE 안에 있던 검사를 공통 함수로 옮긴 것이다. 자식이 있으면 자식의 상태와 무관하게 `409 CannotDeleteResource`이고 메시지에 자식 ID를 넣는다. 지금은 볼륨 행을 직접 저장소에 넣는 계약 테스트로만 풀 쪽을 확인했다 (§5, CV-1).

#### (8) 처리기는 아무것도 하지 않는다 — `capacity_pools.py:309-314`

- `_no_storage_work`는 빈 함수다. `HANDLERS`는 `(POOL_TYPE, action)`을 CREATE·UPDATE·PATCH·DELETE 네 개 모두 이 함수에 연결한다. 아무것도 하지 않으므로 몇 번을 다시 실행해도 결과가 같다(멱등). 그래서 재시작 복구가 쉽게 통과한다 (계정 문서 §3 (7)).
- `arm_app.py:74`가 `{**accounts.HANDLERS, **pools.HANDLERS}`로 두 리소스의 처리기를 한 표로 합쳐 워커에 준다.

#### (9) 공통 계층이 풀 때문에 바뀐 세 곳

- **결함 주입 키를 처리기에서 만든다** — `lro.py:29-30`, `:33-61`. `parse_faults(text, handler_keys)`는 등록된 처리기의 `(리소스 종류, 작업)`에서 받을 수 있는 키를 만든다 (`_key`가 `capacityPools/patch` 형식으로 바꾼다). 풀은 `capacityPools/{create|update|patch|delete}`를 받는다. 계정에는 PATCH 작업이 없어 `netAppAccounts/patch`는 서버 시작 때 거절된다. 처음 설계는 이 키도 "형식상 받는다"였지만, 쓰이지 않는 키를 받으면 검증자가 결함을 걸었다고 착각할 수 있어서 바꿨다 (설계 "구현 중 변경"). 키 목록이 고정이 아니라 처리기에서 나오므로, 새 리소스가 처리기를 등록하면 키가 저절로 늘어난다.
- **`_BODIES`** — `arm_app.py:43`, `:234`. `Location` 방식으로 끝난 작업을 조회하면 리소스 본문이 필요하다. 계정 때는 본문이 하나뿐이었다. 지금은 `{ACCOUNT_TYPE: accounts.account_body, POOL_TYPE: pools.pool_body}` 표에서 `res.type`으로 고른다. 그래서 풀 PATCH가 끝난 뒤 `Location` URL을 GET하면 `200`과 풀 본문이 온다.
- **`_tracking_headers`** — `arm_app.py:63-66`. 위 (5), (7)에서 설명했다.
- **`Tx.ensure_no_children`과 `list_children`** — `state_store.py:145-164`. 위 (3), (7)에서 설명했다.

### 설계 결정

설계 문서의 결정 1~11 중 면접에서 물을 만한 것들이다. 아래 4행(1, 3, 4, 5)은 사용자가 선택지로 직접 고른 것이다.

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | **응답 형식은 녹화를 따른다.** PUT 201은 `Azure-AsyncOperation`만, PATCH는 `202` + `Patching` 본문 + 두 헤더 (사용자 선택) | 스펙대로 201에 `Location` + `final-state-via: location`, PATCH 202 본문 없음 | 실서비스 응답과 같고, 계정과 풀의 PUT 응답 헤더가 같아져 공통 계층에 생성 흐름이 하나 더 생기지 않는다. 녹화가 preview api-version으로 호출됐다는 점은 남는 단서다 |
| 2 | 풀은 storage agent에 아무것도 만들지 않는다 | ONTAP 객체(애그리게이트, SVM, QoS 정책 그룹) 생성 | 대응이 공개 자료에 없다 [미확인] |
| 3 | **용량 검사는 지금 구현하고, 실환경 검증은 볼륨 사이클로 넘긴다** (사용자 선택). 풀 축소 하한과 볼륨이 남은 풀의 DELETE 409를 구현하고, 볼륨 행을 저장소에 직접 넣는 계약 테스트로 확인한다 | 볼륨 사이클에서 구현 | 볼륨 사이클이 풀 코드를 다시 고치게 되어 풀의 검증 일부를 다시 해야 한다. 계정의 409를 풀 사이클로 넘긴 것과 같은 방식이다 |
| 4 | **규칙 위반은 요청 즉시 동기 `400`이다** (사용자 선택). 검사와 쓰기를 같은 트랜잭션에서 하고, 위반이면 작업도 리소스 변경도 만들지 않는다 | 작업을 만든 뒤 `Failed`로 끝내기 | 실패한 리소스가 남으면 정리 규칙(실패한 볼륨이 할당량을 계속 차지하는지)이 더 필요하다. 실서비스의 형태는 [미확인]이다 |
| 5 | **`serviceLevel`은 볼륨이 없는 풀에서만 PUT으로 바꾼다** (사용자 선택). 볼륨이 있으면 `400 BadRequest` "ServiceLevel cannot be changed." | 생성 뒤 불변 | ANF 오류 문서가 "볼륨이 있는 풀"의 변경만 거절한다고 쓴 것과 맞는다 [추론]. PATCH로는 바꿀 수 없다 [스펙] |
| 6 | 부모가 없으면 `404 ParentResourceNotFound`, 부모가 `Deleting`이면 `409 Conflict`. 둘 다 풀 생성 트랜잭션 안에서 검사 | 삭제 중인 부모를 허용 | 계정 삭제가 끝나면 고아 풀이 남는다 (ADR §6.4) |
| 7 | 실서비스 코드가 [미확인]인 규칙 위반은 `400 BadRequest` + ANF 문서의 문구 | 구체 코드를 지어내기(예: `PoolSizeTooSmall`) | 근거가 없다. ANF는 비동기 실패의 최상위 코드로 `BadRequest` 같은 일반 코드를 썼다 [녹화] |
| 8 | 생성 PUT은 `size`와 `serviceLevel` 필수. 갱신 PUT에서 빠진 속성은 기존 값 유지 | 갱신에서 기본값 적용 | 기본값 적용은 실수로 풀을 4 TiB로 줄이거나 Manual을 Auto로 되돌릴 수 있다. 실서비스 동작은 [미확인] |
| 9 | PATCH는 PUT 갱신과 같은 방식으로 저장한다(새 값을 바로 쓰고 `previous`를 남겨 실패하면 되돌림) | 202 본문에 바뀌기 전 값을 보이고 완료 때 적용 | 작업에 요청 내용을 따로 저장해야 해서 스키마가 바뀐다 |
| 10 | `totalThroughputMibps`는 2진 TiB로 계산 | 10진 TB(스펙 예시 281.474) | 실서비스 녹화가 256.0이다 |
| 11 | 크기는 stable 규칙(1 TiB 배수, 1~2,048 TiB). 512 GiB는 거절 | preview의 512 GiB 허용 | 클론은 `2026-08-01`만 지원한다 |

---

## 4. 실제 ANF와 다른 점

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 처리량 한도 | 볼륨 처리량 한도가 실제 I/O에 적용된다 [문서] | `totalThroughputMibps`를 계산해 보여 주기만 하고 실제로 제한하지 않는다 | 실제 제한은 FR-08과 스파이크 S2에서 한다 |
| `utilizedThroughputMibps` | 볼륨 한도의 합으로 보인다 [추론, 녹화] | 0.0 고정 (`capacity_pools.py:159`) | 볼륨이 없다. 볼륨 사이클에서 합으로 계산한다 |
| PUT 201의 추적 헤더 | 스펙은 `Location` + `Retry-After`, 녹화는 `Azure-AsyncOperation`만 | 녹화를 따라 `Azure-AsyncOperation`만 | 설계 결정 1. 녹화가 preview api-version으로 호출됐다는 단서가 있다 |
| PATCH 202 본문 | 스펙은 본문 없음. 녹화는 풀 전체 + `Patching` 본문(바뀌기 전 값) | 풀 전체 + `Patching`, **바뀐 뒤 값** | 의도한 차이다 (설계 결정 9) |
| 201 본문의 필드 | 녹화의 201에는 `qosType`, `poolId` 등이 없고 `totalThroughputMibps: 0.0` [녹화] | 201도 GET과 같은 필드를 모두 준다 | 단순화 (설계 §4.2) |
| 서비스 수준·기능 | Standard, Premium, Ultra, StandardZRS, Flexible 등 | Standard·Premium·Ultra만. 나머지는 `400 InvalidRequestContent` | 미룬 기능을 조용히 무시하지 않고 거절 |
| `size` 단위 | preview 버전은 512 GiB도 허용 [스펙] | 1 TiB 배수만 | `2026-08-01`만 지원 |
| 용량 초과·Manual → Auto·서비스 수준 변경 거절 | HTTP 코드, `error.code`, 동기/비동기 모두 [미확인] | 동기 `400 BadRequest` + 문서의 메시지 | **클론이 정한 값이다.** 실서비스 값이라고 말하면 안 된다 (설계 결정 4, 7) |
| 부모 계정이 `Deleting`일 때 풀 생성 | 응답 [미확인] | `409 Conflict` | **클론이 정한 값이다.** 고아 풀 방지 (설계 결정 6) |
| 자식(볼륨) 검사 위치 | ARM 게이트웨이가 RP보다 먼저 거절 [추론: `x-ms-failure-cause: gateway`] | DELETE 트랜잭션 안 (`capacity_pools.py:302`) | 검사와 삭제 사이에 자식이 생기는 경합을 막는다. 응답 코드와 메시지 형식은 녹화와 같다 |
| 삭제 직후 부모 삭제 | 풀 삭제가 `Succeeded`로 끝난 직후 계정 DELETE가 몇 초간 409(게이트웨이의 자식 정보 갱신 지연으로 보임) [녹화, 추론] | 재현하지 않는다. 풀이 지워지는 즉시 계정 삭제가 된다 | 재현할 이유가 약하다 |
| 목록 | `nextLink` 페이징 [스펙] | 한 페이지에 전부 | 미룬 항목 |
| 읽기 전용 속성 | 서버 값과 다르면 거절한다는 규칙이 있다 (RPC) | 요청에 있어도 무시 | SDK가 GET 본문을 그대로 PUT하는 경우를 막지 않으려는 선택. 계정과 같다 |
| 결함 주입 | 없음 | `capacityPools/{create\|update\|patch\|delete}` | 클론 전용 장치 |
| 풀 변경(`poolChange`), 계정당 풀 수 한도, ETag, `systemData` | 있음 | 없음 | 미룬 항목 |

---

## 5. 검증

검증 보고서: `_workspace/capacity-pool/04_verifier_report.md` (1회차)와 `04_verifier_report_r2.md` (2회차). 둘 다 2026-11-07.

**방법.** 계정과 같다. WSL Ubuntu에서 실제 uvicorn 프로세스를 띄우고 별도 프로세스(pytest)에서 `http.client`로 요청했다(TestClient 미사용). 상태 저장소는 시나리오마다 `/tmp`의 새 임시 파일이다. 손으로 띄운 서버에 `curl -i`로도 원시 헤더를 교차 확인했다(AC-01, AC-04, AC-08). 검증 대상 코드의 sha256은 시작과 끝에서 같았다.

**결과: PASS 13 / FAIL 0 / UNVERIFIED 0** (1회차, 2회차 모두).

| 기준 | 증명한 것 |
| --- | --- |
| AC-01 | 새 풀 PUT이 `201` + `Creating` + `Azure-AsyncOperation`만(`Location` 없음, curl로도 확인) → `Succeeded`. GET에 UUID `poolId`, `qosType: Auto`, `encryptionType: Single`, `totalThroughputMibps: 256.0`, `utilizedThroughputMibps: 0.0` |
| AC-02 | 처리량 계산: Standard 2 TiB 32.0, Ultra 1 TiB 128.0, Premium 1 TiB 64.0 (8 TiB Premium 512.0, 8 TiB Ultra 1024.0도 같은 식) |
| AC-03 | PUT 갱신 `200` + `Updating` → `Succeeded`. tags가 새 맵으로 교체(이전 키가 남지 않음), `size`·`serviceLevel`을 빼면 기존 값 유지, 빈 풀의 `serviceLevel` Premium → Ultra 변경 후 처리량 재계산 |
| AC-04 | PATCH `202` + `Patching` + 두 헤더(curl로도 확인) → `Succeeded`(`action: PATCH`). `Location` URL은 `200` + 풀 본문. `size`·`qosType: Manual` 반영. 이어서 Auto로 PATCH·PUT하면 `400 BadRequest`, Manual 유지, 새 작업 없음 |
| AC-05 | 계정의 풀 목록, 다른 계정 목록에 없음, 없는 계정 `404`, 없는 풀 `404 ResourceNotFound`, 이름 대소문자만 달라도 같은 풀 |
| AC-06 | 잘못된 요청이 모두 거절되고 작업·상태 변화 없음 (아래 2회차 설명) |
| AC-07 | 없는 계정 아래 풀 PUT은 `404 ParentResourceNotFound`. 계정 삭제에 5초 지연을 주입하고 `Deleting` 중에 풀 PUT하면 `409 Conflict`. 계정 삭제가 끝난 뒤 고아 풀 없음 |
| AC-08 | DELETE `202` + 두 헤더 → `Succeeded` → `Location` GET `204` → 풀 GET `404` → 재DELETE `204` |
| AC-09 | 풀이 있는 계정 DELETE → `409 CannotDeleteResource`(메시지에 풀 ID, 새 작업 없음). 풀을 지운 뒤 계정 DELETE → `202` → `Succeeded`. 계정 사이클에서 넘어온 기준이다 |
| AC-10 | 5초 지연 중 상태 `Creating`/`Patching`/`Deleting`(`percentComplete: 0.0`), PATCH 중 `Location` GET `202`. 생성 실패 주입 → 풀 `Failed`, 주입 없는 서버에서 PUT하면 `Succeeded`로 회복. PATCH 실패 주입 → 풀 `Failed`, tags·size·qosType가 PATCH 전 값 |
| AC-11 | `Creating`, `Updating`, `Patching`, `Deleting` 네 상태 모두에서 PUT·PATCH·DELETE가 `409 AnotherOperationInProgress`, 새 작업이 생기지 않음 |
| AC-12 | 생성과 PATCH가 지연 중일 때 SIGKILL → 재시작 뒤 둘 다 `Succeeded`(같은 지연이면 재시작 뒤 약 4.8초), 작업이 늘지 않음 |
| AC-13 | 풀 작업 전후와 모든 실행이 끝난 뒤의 `exportfs -v`, `/etc/exports.d/`, `/proc/fs/nfsd/exports`가 네 시점 모두 같음 |

**2회차 (AC-06 재검증).** 1회차 판정은 PASS였지만 verifier가 "추가 관찰"로 기록한 것이 있었다. `serviceLevel: Flexible`·`encryptionType: Double`의 거절 메시지가 "The property 'properties.serviceLevel 'Flexible'' is not supported …"처럼 따옴표가 겹쳤다. 값까지 붙인 이름을 속성 이름용 `unsupported_property`에 넘겼기 때문이다. 판정을 막는 문제는 아니었지만 고쳤고(TDD: 메시지 테스트 RED → `capacity_pools.py`의 두 곳 → GREEN), 바뀐 기준(AC-06)만 실환경에서 다시 판정했다. 새 메시지는 "The value 'Flexible' of 'properties.serviceLevel' is not supported by this ANF clone."이고, verifier는 StandardZRS 경우를 하나 더하고 미룬 기능 다섯 경우를 메시지 전체로 비교하도록 스크립트를 강화했다. 나머지 메시지는 글자 단위로 같았다. e2e 폴더 전체(63개, 풀 39 + 계정 24)를 두 번 돌려 모두 통과했다.

**측정값.** 지연 없는 풀 작업의 startTime→endTime은 7~10 ms. 5초 지연을 주입하면 PUT 응답은 9~14 ms에 돌아오고 작업 시간은 약 5.01초다. 서버 기동(준비 확인까지)은 약 0.62초다.

**계정 회귀.** 풀이 공통 코드를 바꿔 계정 검증이 무효가 됐고, 계정의 AC-01~AC-13을 새 코드로 다시 돌려 PASS 13/13을 확인했다 (`_workspace/netapp-account/04_verifier_report_r2.md`). 2회차 e2e에서도 계정 24개가 다시 통과했다.

**이 검증이 증명하지 못하는 것.**
- **풀은 컨트롤 플레인 전용이다.** AC-13은 "풀 작업이 export를 만들거나 바꾸지 않았다"만 보인다. 비교하기 전부터 export가 0개였으므로 기존 export가 지워지지 않는지는 보이지 않았다. 풀 처리기가 storage agent를 부르지 않는 것은 코드로 확인된다 (`capacity_pools.py:309`).
- **용량 검사는 실환경 PASS가 아니다.** 풀 축소 하한(CV-2), 볼륨이 있는 풀의 DELETE 409(CV-1), 볼륨이 있는 풀의 서비스 수준 변경 거절(CV-3)은 볼륨 사이클로 넘겼다. 실환경에서 볼륨을 만들 방법이 아직 없다. 이번에는 `test_capacity_pools_api.py`가 볼륨 행을 저장소에 직접 넣어(`add_volume`) 로직만 TestClient로 확인했다. 볼륨 생성이 풀 크기를 넘으면 거절되는 기준도 볼륨 사이클이 구현하고 검증한다.
- **실서비스와의 비교가 아니다.** 용량·처리량 초과 오류의 코드, Manual → Auto 거절 코드, 부모 `Deleting` 때의 응답은 클론이 정한 값이다. 이 검증은 클론이 설계한 계약을 확인한 것이다.
- **WSL 시계 관찰 (판정 무관).** WSL 게스트 시계가 호스트보다 약 10% 느리고(단조 시계 비율 0.90) 벽시계는 약 33초마다 약 3.3초씩 앞으로 건너뛴다. 이번 시간 조건은 단조 시계로 쟀고 여유가 커서 판정에 영향이 없다. 하지만 FR-08에서 처리량(MiB/s)을 잴 때는 어느 시계를 기준으로 삼을지 정해야 한다. 게스트 안에서 잰 값이 설정값과 맞아도 호스트 실시간 기준으로는 약 10% 낮을 수 있다 [추론].

**테스트 구성.** 풀 단위 테스트 `backend/tests/unit/test_capacity_pools.py`, 계약 테스트 `backend/tests/contract/test_capacity_pools_api.py`(AC-01~AC-12와 CV-1~CV-3을 TestClient로 확인, 매개변수 포함 43개), e2e `backend/tests/e2e/test_capacity_pool_live.py`·`test_capacity_pool_lro_faults_live.py`. 공통 코드를 바꾼 만큼 `test_arm_rules.py`, `test_state_store.py`, `test_lro.py`에도 테스트를 더했다. e2e는 `ANF_E2E_API_URL`이 없으면 skip한다.

---

## 6. 개발 과정

1. **조사.** anf-researcher가 풀 API 계약, 서비스 수준과 처리량 규칙, 크기 규칙, 실서비스 녹화(N1~N6, P1~P2)를 조사했다. 스펙과 녹화가 다른 곳(PUT 201 헤더, PATCH 202 본문)과, 실서비스 근거가 없는 곳(용량·처리량 초과 오류의 HTTP 코드와 동기·비동기 여부, Manual → Auto 거절 코드, PUT 갱신에서 빠진 `size`·`serviceLevel`의 처리)을 구분해 적었다. 설계를 막는 [미확인]은 없었고, 클론이 정하고 문서화하기로 했다.
2. **설계.** 설계안과 선택지 4개를 사용자에게 제시했고, 사용자가 4개 모두 추천안으로 확정했다. **사람이 내린 결정**은 (a) 응답 형식은 스펙이 아니라 녹화를 따름, (b) 용량 검사는 지금 구현하고 실환경 검증은 볼륨 사이클로 넘김, (c) 규칙 위반은 동기 400, (d) `serviceLevel`은 빈 풀에서만 변경 가능이다. 버린 대안은 각각 스펙 따르기, 볼륨 사이클에서 구현, 작업을 만든 뒤 `Failed`로 끝내기, 생성 뒤 불변이다. 같은 설계에서 ADR §6.4의 용량 예약·동시성 규칙(볼륨 행 자체가 예약이다 등)을 확정했다.
3. **구현.** Claude가 TDD로 구현했다(`arm_rules`, `state_store`, `lro`, `capacity_pools`, `arm_app` 순으로 모듈마다 RED 확인 뒤 GREEN). 구현 중 바뀐 것은 설계 문서 끝의 "구현 중 변경"에 있다.
   - 결함 주입 키를 고정 목록에서 처리기 기반으로 바꿨다 (§3 (9)).
   - 계정과 풀이 같이 쓰는 함수(오류 함수, 자식 검사)를 공통 파일로 옮겼다. 계정의 외부 동작은 바뀌지 않았다.
4. **실환경 검증 1회차.** real-env-verifier가 PASS 13 / FAIL 0 / UNVERIFIED 0을 냈다. 판정 밖 관찰이 세 개 있었다. (1) WSL 시계가 느리다, (2) 거절 메시지의 따옴표가 겹친다, (3) PATCH 202 본문이 바뀐 뒤 값이다. (3)은 설계 결정 9로 정한 의도한 차이이므로 그대로 두었다.
5. **공통 코드 변경 → 계정 검증 무효화 → 영향받는 기준만 재검증.**
   - 풀 구현이 공통 코드(`accounts.py`, `lro.py`, `state_store.py`, `arm_app.py`)를 바꿔서 계정의 검증 대상 코드 해시가 달라졌다. 그래서 계정을 `done`에서 `in_progress`로 되돌리고, 이번 검증에서 계정 AC-01~AC-13을 함께 다시 돌렸다(PASS 13/13).
   - 관찰 (2)는 TDD로 고쳤다. 메시지 테스트가 먼저 RED가 되는 것을 확인하고 `capacity_pools.py`의 두 곳을 고쳐 GREEN으로 만들었다. 새 코드 해시가 나왔으므로 영향받는 AC-06만 판정을 대기로 돌려 2회차에서 다시 판정했고, 나머지 12개는 "바뀐 것이 오류 메시지 문자열 두 개뿐이고 다른 기준의 코드 경로는 이 메시지를 쓰지 않는다"는 근거와 e2e 회귀 통과로 1회차 PASS를 유지했다. AC-13(셸 비교)만 다시 돌리지 않았고 데이터 플레인 코드가 없는 변경이라 1회차 판정을 유지했다.
6. **검증 중 사건.** 2회차 시작 때 포트 8080에 이 검증과 무관한 anf-api가 떠 있었다. verifier는 그것을 건드리지 않고 포트를 8081로 바꿔 검증했다(포트는 수락 기준과 무관하다).
7. **개념 문서(이 문서).**

AI와 일한 방식으로 설명할 수 있는 것: 조사 → 설계(사람이 선택지를 결정) → 테스트 먼저 구현(TDD 훅) → 구현자와 다른 에이전트의 실환경 검증 → 개념 문서. 검증자는 제품 코드를 고치지 않고 검증 스크립트만 만들었다. 공통 코드를 건드리면 이미 끝난 기능의 검증이 무효가 된다는 규칙이 실제로 작동한 사이클이다.

---

## 7. Interview Q&A

### Q1. (개념) What is a capacity pool in Azure NetApp Files, and how does the service level determine throughput?

**A.** A capacity pool is the provisioning and billing unit: you buy capacity and throughput through the pool, and volumes are the unit of consumption. The pool is billed by provisioned size and service level, not by what you actually write. The service level sets a per-TiB throughput rate: Standard 16, Premium 64, Ultra 128 MiB/s per TiB. With Auto QoS, a volume's limit is that rate times its quota. With Manual QoS, each volume gets its own throughput, and the sum cannot exceed the pool total, which is pool TiB times the rate. In my clone a 4 TiB Premium pool reports 256 MiB/s total. I should be clear that the pool is not something a client mounts, only volumes are.

### Q2. (개념) What ONTAP object does a capacity pool map to?

**A.** I can't claim a mapping, because I found no public source that says which ONTAP object backs an ANF pool. What I can say from the Azure docs is that the pool is a budget and billing unit, not physical space like an aggregate. The closest ONTAP concept for the throughput side is QoS policy groups, and Auto QoS resembles adaptive QoS, where the limit scales with volume size. But adaptive QoS is IOPS-based and ANF's is MiB/s, and nothing public says ANF uses it. That is my inference, so I labeled it that way in the doc. This is also why the pool creates nothing on the storage agent: I did not want to hard-code an unverified mapping.

### Q3. (구현) Why is PATCH asynchronous for a pool when it is synchronous for an account, and how does your implementation handle a failed PATCH?

**A.** I followed the recorded production behavior: a pool PATCH returns 202 with a `Patching` body and both tracking headers, even for a tags-only change, while an account PATCH is a synchronous 200. So the sync or async behavior is per resource. In `patch_pool`, I write the new values immediately, keep the old tags and properties on the operation row, and set the state to `Patching` in one transaction. If the worker finishes the operation as failed, `_finish` restores the previous values and marks the pool `Failed`. I verified it by injecting a failure into a PATCH that changed tags, size, and QoS type; all three came back to their old values. One deliberate difference: my 202 body shows the new values, while the recording showed the old ones.

### Q4. (구현) Walk me through the capacity checks on resize, and why is "volume rows are the reservation" an important rule?

**A.** When a pool is resized, `_apply_changes` sums the `usageThreshold` of every volume row under the pool inside the same transaction. If the new size is smaller, it returns a synchronous 400 and creates no operation. The floor is the sum of quotas, not used bytes, which is what two Microsoft docs say; one error doc mentions used bytes, so that is a documented ambiguity. The rule that a volume row itself is the reservation, in any state including `Creating` or `Failed`, matters because a half-created volume may still own real resources. Releasing the capacity early could oversubscribe the pool. I implemented the pool side now, but it is only contract-tested; live verification waits for the volume cycle.

### Q5. (설계) Why did you reject rule violations with a synchronous 400 instead of creating an operation that fails?

**A.** Two reasons. First, a failed operation leaves a resource in a `Failed` state, and I would then need cleanup rules, for example whether a failed volume keeps holding quota. A synchronous 400 inside the same transaction as the check leaves no state to clean. Second, there is no evidence of what real ANF does: the HTTP code, error code, and sync or async shape are all unconfirmed for capacity errors. So the 400 `BadRequest` with the documented message is the clone's choice, and I documented it as such. The tradeoff is that a real client might expect the failure to appear on the operation. If I find evidence, the change would be isolated in `_apply_changes`.

### Q6. (한계) What does your pool not prove, and where does the clone differ from real ANF?

**A.** Three things. First, `totalThroughputMibps` is only a computed number. Nothing throttles I/O yet, and `utilizedThroughputMibps` is fixed at 0.0 because there are no volumes. Real throttling is a later feature. Second, the capacity checks (shrink floor, delete with volumes, service level change with volumes) are tested only with volume rows inserted directly into the store, so they are not counted as live-environment passes. Third, several error codes are my choice, not observed ANF behavior: the capacity errors, Manual to Auto rejection, and 409 `Conflict` when the parent account is deleting. The data plane is also untouched: the export list was identical before and after, though it started empty.

### Q7. (디버깅/테스트 전략) You changed shared code for pools. How did you keep earlier features trustworthy, and how did you handle the verifier's findings?

**A.** I treat verification as bound to a code hash. When the pool work changed shared files, the account feature's verified hash changed, so I moved the account back to in-progress and the verifier reran all 13 account criteria with the pool ones. They passed. Later the verifier noted that two error messages had doubled quotes. It did not fail any criterion, but I fixed it test-first: a failing message test, then a two-line change. Then I invalidated only the affected criterion, AC-06, and re-verified it live, plus a full end-to-end regression, 63 passing twice. The other twelve kept their results because only message strings changed. That is a risk-based re-test: invalidate by what the change can reach.

### Q8. (디버깅/관측성) The fault-injection key list changed during implementation. Why, and how does it relate to testing in a data-plane team?

**A.** The original design accepted a key for account PATCH, but accounts have no PATCH operation, since that call is synchronous. A key that can never fire is dangerous: a tester sets a fault, sees nothing happen, and wrongly concludes the system is resilient. So `parse_faults` now builds the allowed keys from the registered handlers, and the server refuses to start on an unknown key, with the valid list in the error. The verifier confirmed both `capacityPools/resize` and `netAppAccounts/patch` abort startup. For data-plane work, the same idea applies: a test harness should fail loudly when a fault cannot be applied. It also means new resources get their keys automatically when they register handlers.

### Q9. (다시 한다면) If you did this again, what would you do differently, and what is next for the pool?

**A.** I would try to settle the unknowns against a real subscription: the actual status codes for capacity errors and Manual to Auto, and the exact PATCH 202 body semantics. I would also start the data-plane check with a non-empty export list so it can show that existing exports survive, not just that none are created. Next, the volume cycle owns three things: computing `utilizedThroughputMibps` as the sum of volume limits, implementing the reservation rule on volume create and resize, and live-verifying the deferred criteria CV-1 to CV-3. FR-08 then enforces throughput for real, and it must pick a clock, because my WSL guest clock runs about ten percent slow.

---

## 부록. 이 문서가 쓰지 못한 것

브리프에 없거나 [미확인]이라 쓰지 못한 것이다.

- ANF 풀에 대응하는 ONTAP 객체. 애그리게이트, SVM, QoS 정책 그룹 중 무엇인지 공개 자료에 없다.
- ONTAP의 `space-guarantee none`, QoS `max-throughput`, shared policy group의 원문. adaptive QoS도 검색 요약만 근거다.
- 용량·처리량 초과, Manual → Auto, 볼륨이 있는 풀의 서비스 수준 변경, `poolId` 변경의 실서비스 HTTP 코드·`error.code`·동기/비동기 여부.
- PUT 갱신에서 `size`·`serviceLevel`을 빼면 기존 값 유지인지 기본값 적용인지(녹화 P2는 기존 값이 기본값과 같아 구분할 수 없었다).
- 리소스 본문의 `provisioningState: Deleting`·`Failed` 값, 실패한 풀 상태의 정확한 문자열.
- preview(`2026-08-15-preview`) 스펙의 풀 PUT 201 헤더 정의.
- 같은 풀에 작업이 진행 중일 때 새 PATCH·PUT·DELETE의 실서비스 응답. 클론의 `409 AnotherOperationInProgress`는 클론의 선택이다.
