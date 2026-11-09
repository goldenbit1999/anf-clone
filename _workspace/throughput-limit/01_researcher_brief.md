# 처리량 제한 (Throughput limit, QoS) 조사 브리프

- 조사 상태: 한도 도달 (30턴 상한. 남은 질문은 "미확인 목록"에)
- 조사일: 2026-11-09
- 기준 api-version: 2026-08-01 (stable). 녹화는 2025-12-15-preview, 2026-08-15-preview 등 (항목마다 적음)
- 범위 가정: FR-08 = Auto QoS 한도, Manual QoS 볼륨 `throughputMibps`(생성·PATCH), 풀 처리량 예산 검사, Auto → Manual 전환. Flexible(`customThroughputMibps`), Elastic(shared QoS), 대용량 볼륨, DP 볼륨은 이름만 적었다.
- 이미 확인된 사실은 다시 조사하지 않고 인용했다: 풀 브리프 `_workspace/capacity-pool/01_researcher_brief.md`, 볼륨 브리프 `_workspace/volume/01_researcher_brief.md`, 스파이크 `_workspace/spikes/S2.md` [A1][A2].

## 요약 (5줄 이내)

1. Auto QoS 한도 = 서비스 수준 단가(16/64/128 MiB/s per TiB) × 볼륨 할당량(2진 TiB)이고, 풀 크기·사용량과 무관하다 [문서 D1]. 응답 값은 소수 셋째 자리로 반올림돼 보인다(101 GiB Premium = 6.3125 → `6.312`) [녹화 R3]. Auto QoS 한도의 **하한은 문서에 없다** [미확인]. ANF 최소 볼륨 50 GiB 기준이면 가장 낮은 Auto 한도는 Standard 50 GiB = 0.78125 MiB/s다 [추론].
2. Manual QoS: 볼륨 `throughputMibps`(float32)는 생성·PATCH 모두 받고 [스펙 S1], 범위는 1~4,500 MiB/s(일반 볼륨)다 [문서 D4]. 녹화에서 4 TiB Premium Manual 풀(`totalThroughputMibps 256.0`)에 100 GiB 볼륨 3개를 각 `throughputMibps: 6`으로 만들자 `utilizedThroughputMibps 18.0`이 됐다 [녹화 R1].
3. 예산 초과는 "Requested throughput not available"로 실패한다 [문서 D5]. HTTP 코드·`error.code`, 생략 시 기본값, Auto 풀 볼륨에 `throughputMibps`를 보냈을 때의 처리, Auto → Manual 전환 뒤 기존 볼륨 값은 공개 자료와 녹화에서 찾지 못했다 [미확인].
4. 한도는 읽기+쓰기 합산이고 [문서 D1, D2], 한도에 닿으면 I/O가 대기열에 쌓여 지연이 늘고 처리량은 상한에 머문다 [문서 D2]. 할당량 변경에 따른 한도 변경은 "nearly instantaneous"하고 I/O를 끊지 않는다 [문서 D2]. 메타데이터("Other") I/O가 한도에 포함되는지는 [미확인].
5. ONTAP 대응: QoS policy group(`/api/storage/qos/policies`, `fixed.max_throughput_mbps`, 볼륨 `qos.policy.{name,uuid}`) [ONTAP O1]. ONTAP adaptive QoS는 IOPS/TB로만 정의돼 MiB/s per TiB인 ANF Auto QoS를 그대로 표현하지 못한다 [ONTAP O1]. ANF가 내부에서 무엇을 쓰는지는 공개되지 않았다 [미확인].

## 1. Auto QoS

### 단가와 공식
- 서비스 수준 단가: Standard 16, Premium 64, Ultra 128 MiB/s per TiB [문서 D1] (풀 브리프 인용).
- 볼륨 한도 = 단가 × 볼륨 할당량(`usageThreshold`, 2진 TiB). 문서 예: Premium 2 TiB → 128 MiB/s, Premium 100 GiB → 6.25 MiB/s (0.09765625 TiB × 64). "This scenario applies regardless of the capacity pool size or the actual volume consumption." [문서 D1].
- `actualThroughputMibps`는 float32, 읽기 전용, "Actual throughput in MiB/s for auto qosType volumes calculated based on size and serviceLevel" [스펙 S1].

### 녹화에서 본 값 (반올림)

| 서비스 수준 | `usageThreshold` | `actualThroughputMibps` | 정확한 공식 값 | 근거 |
| --- | --- | --- | --- | --- |
| Premium | 107374182400 (100 GiB) | 6.25 | 6.25 | [녹화 R2] (2026-03-20, 2025-12-15-preview) |
| Premium | 214748364800 (200 GiB) | 12.5 | 12.5 | [녹화 R6] (볼륨 브리프 V4 인용) |
| Premium | 108447924224 (101 GiB) | **6.312** | 6.3125 | [녹화 R3] (2026-10-30, 2026-08-15-preview, westus2) |
| Premium, `volumeType: DataProtection` | 107374182400 | 3.516 | (공식과 다름) | [녹화 R4] (2025-08-15). DP 볼륨은 범위 밖. 규칙 [미확인] |

- 6.3125가 6.312로 보였으므로 소수 셋째 자리로 자른다. 반올림 방식은 half-up이 아니다(half-up이면 6.313). half-even(Python `round(6.3125, 3)` = 6.312, 6.3125는 2진수로 정확히 표현된다)과 버림 중 어느 것인지는 이 값 하나로 구분되지 않는다 [추론 — 녹화 R3].

### 하한
- Auto QoS 볼륨에 따로 정한 최소 MiB/s는 찾지 못했다. 서비스 수준 문서 [D1], 성능 고려 문서 [D2], 리소스 한도 [D4]에는 Manual QoS 볼륨의 최소(1 MiB/s)만 있다 [미확인].
- ANF 일반 볼륨 최소 크기는 50 GiB다 [문서 D7]. 그래서 공식만 적용하면 실서비스의 가장 낮은 Auto 한도는 Standard 50 GiB = 0.78125 MiB/s(표시 0.781)다 [추론 — 공식 + 최소 크기].
- 클론의 검증용 1 GiB 볼륨(`ANF_MIN_VOLUME_SIZE_GIB=1`) Premium은 0.0625 MiB/s로, 실서비스에서는 생기지 않는 값이다 [추론].

### 상한
- 일반 볼륨의 실측 최대는 4,500 MiB/s다. Premium Auto에서 할당량 70.31 TiB면 이 수준에 닿고, 그 이상 할당량을 늘려도 실제 처리량은 늘지 않는다 [문서 D2].
- 그 경우 `actualThroughputMibps`가 공식 값(예: 100 TiB Premium = 6,400)인지 4,500으로 잘린 값인지는 [미확인].

### 한도가 바뀌는 때
- 볼륨 할당량을 바꾸면: "When volume quota is changed, the corresponding change in throughput limit is nearly instantaneous. The change does not interrupt or impact the volume access or I/O." [문서 D2]. 녹화: 볼륨 PATCH `{"properties": {"usageThreshold": 214748364800}}` → 202 `Patching` → 완료 뒤 `actualThroughputMibps` 6.25 → 12.5 [녹화 R6]. 할당량 변경은 클론에서 FR-16(볼륨 크기 조정)이다.
- 풀 크기를 바꾸면: Auto 볼륨의 한도는 바뀌지 않는다("regardless of the capacity pool size") [문서 D1].
- 볼륨을 다른 서비스 수준의 Auto 풀로 옮기면 한도가 새 수준에 맞게 바뀐다 [문서 D8]. 풀 변경은 범위 밖이다.

### 풀 쪽 값
- Auto 풀의 `utilizedThroughputMibps`는 볼륨 한도의 합이다. 4 TiB Premium Auto 풀 + 100 GiB 볼륨 1개 → `totalThroughputMibps 256.0`, `utilizedThroughputMibps 6.25`였다 [녹화 R2]. 지표 문서도 "Pool allocated throughput: Sum of the throughput of all the volumes belonging to the pool."이라고 쓴다 [문서 D6].

## 2. Manual QoS

### `throughputMibps` 속성
- `VolumeProperties.throughputMibps`: float32, nullable(`x-nullable: true`). `VolumePatchProperties.throughputMibps`: float32. 둘 다 "Maximum throughput in MiB/s that can be achieved by this volume and this will be accepted as input only for manual qosType volume" [스펙 S1]. 즉 생성(PUT)과 PATCH 모두에서 쓸 수 있다.
- 스펙에 `minimum`·`maximum`·`default`가 없다 [스펙 S1 — `netapp-2026-08-01.json` 16478, 16899행, `Volume.tsp` 291, 1489행].
- 범위: 최소 1 MiB/s, 일반 볼륨 최대 4,500 MiB/s, 대용량 볼륨 최대 12,800 MiB/s [문서 D4] (풀 브리프 [문서 7]과 2026-10-14판 원문 52~54행에서 두 번 확인).
- 소수: 타입은 float다 [스펙 S1]. 녹화는 정수 `6`을 보내 `6.0`을 받았다 [녹화 R1]. `1.5` 같은 소수를 받는지는 [미확인].
- 볼륨 크기와 무관하다: 녹화에서 100 GiB 볼륨에 6 MiB/s(Auto라면 6.25)를 줬다 [녹화 R1]. "you can assign the capacity and throughput for a volume independently" [문서 D1].

### 응답에서 보이는 값
- Manual 볼륨 GET(볼륨 목록): `throughputMibps: 6.0`, `actualThroughputMibps: 6.0` [녹화 R1, 항목 35].
- 같은 녹화의 볼륨 그룹 GET 안에 들어 있는 같은 볼륨들은 `throughputMibps: 6.0`, `actualThroughputMibps: 0.0`이었다 [녹화 R1, 항목 28]. 볼륨 리소스 자체의 응답(항목 35)에서는 `actualThroughputMibps`가 `throughputMibps`와 같다. 스펙 설명("for auto qosType volumes")과는 다르다 [녹화 R1 vs 스펙 S1].
- Auto 볼륨의 `throughputMibps`: 응답에 없거나(파이썬 녹화, R4·R6) `0.0`이다(.NET 녹화, 예: `SnapshotPolicyTests__ListVolumesWithSnapshotPolicy.json`, `actualThroughputMibps 6.25`와 함께) [녹화]. 스펙 예시는 Premium 100 GiB 볼륨에 `throughputMibps: 128`을 보여 공식과 맞지 않는다 [스펙 S2]. 실서비스는 녹화 쪽이다.

### 풀 처리량 예산
- 풀 총 처리량(`totalThroughputMibps`) = 풀 크기(TiB) × 단가 [문서 D1, D7]. Manual 풀의 볼륨 `throughputMibps` 합은 이 값을 넘을 수 없다 ("The total throughput of all volumes created with a manual QoS capacity pool is limited by the total throughput of the pool.") [문서 D7].
- 녹화 R1 (`VolumeGroupTests__CreateDeleteVolumeGroup.json`, 2026-10-30, api-version 2026-08-15-preview, northeurope):
  - 풀 PUT `{"size": 4398046511104, "serviceLevel": "Premium", "qosType": "Manual"}` → 201, `qosType: Manual`, `totalThroughputMibps: 0.0`, `Creating`, `Azure-AsyncOperation` → 같은 초에 작업 `Succeeded` → GET `totalThroughputMibps: 256.0`, `utilizedThroughputMibps: 0.0`.
  - 볼륨 그룹 PUT(SAP HANA, 볼륨 3개, 각 `usageThreshold 107374182400`, `throughputMibps 6`) → 201 `Creating`, `Azure-AsyncOperation` + `Location`. 작업 상태가 `Creating`으로 약 6분(03:27:49 → 03:33:52) 이어진 뒤 `Succeeded`.
  - 그 뒤 풀 GET: `totalThroughputMibps 256.0`, `utilizedThroughputMibps 18.0` (= 6 × 3).
  - 개별 볼륨 PUT이 아니라 볼륨 그룹 경로(`netAppAccounts/{a}/volumeGroups/{g}`)로 만들었다. Manual 풀에 볼륨을 하나씩 PUT하거나 `throughputMibps`를 PATCH한 녹화는 찾지 못했다 (.NET 144개, 파이썬 32개 녹화의 요청 본문에서 `throughputMibps` 검색) [미확인].
- 예산 초과: "Volume creation or modification fails with `Requested throughput not available` error. Available throughput for a volume is determined by its capacity pool's size and the service level. If you do not have sufficient throughput, you should increase the pool size or adjust the existing volume throughput." [문서 D5]. HTTP 상태 코드, `error.code`, 동기 거절(400/409)인지 비동기 작업 실패인지는 [미확인].
- 풀을 줄여 총 처리량이 배정된 합보다 작아질 때: 문서에 없다 [미확인]. 위 예산 규칙으로 보면 거절될 가능성이 높다 [추론].

### 지정하지 않을 때와 Auto 풀에 보낼 때
- Manual 풀 볼륨에서 `throughputMibps`를 생략하면: 기본값을 찾지 못했다 (스펙에 `default` 없음, 문서 D1·D3·D7에 없음, 녹화는 항상 지정) [미확인].
- Auto 풀 볼륨에 `throughputMibps`를 보내면: 스펙은 "accepted as input only for manual qosType volume"이라고만 쓴다 [스펙 S1]. 거절(400)인지 무시인지는 [미확인].

### Auto → Manual 전환
- 영구 변경이고 되돌릴 수 없다 [문서 D3, D7] (풀 브리프 인용). 풀 PATCH `{"properties": {"qosType": "Manual"}}` → 202 `Patching` → `Succeeded`, 약 0.29~0.48초 [녹화 P1, 풀 브리프 인용]. 이 녹화의 풀에 볼륨이 있었는지는 확인하지 않았다 [미확인].
- "At conversion time, throughput levels might be capped to conform to the throughput limits for volumes of the manual QoS type. See Resource limits" [문서 D3].
- 전환 뒤 기존 볼륨의 `throughputMibps` 값: 공개 자료에 없다 [미확인]. 다음 두 근거로 보면 "직전 Auto 한도를 그대로 `throughputMibps`로 옮기고, Manual 범위(최대 4,500 MiB/s)를 넘는 값만 깎는다"로 읽힌다 [추론]:
  - Manual 풀로 볼륨을 옮기면 "the volume's throughput isn't changed with the volume move" [문서 D8]. 볼륨이 한도 값을 들고 이동한다.
  - "capped"는 Auto 공식 값이 Manual 최대(4,500)를 넘는 큰 볼륨(예: Premium 100 TiB = 6,400)에서만 의미가 있다. 같은 풀 안에서는 할당량 합 ≤ 풀 크기이고 단가가 같으므로 Auto 한도 합 ≤ 풀 총 처리량이어서, 전환 때문에 예산을 넘는 일은 없다 [추론].
- Manual 풀에서 Auto 풀로 볼륨을 옮기면 한도가 대상 풀 공식으로 바뀐다 [문서 D8] (범위 밖).

## 4. ONTAP 대응 개념

### ONTAP REST: QoS policy [ONTAP O1]
- 경로 `/api/storage/qos/policies` (`QosPolicy._path`). CLI 대응: `qos policy-group create|modify|delete|show`, `qos adaptive-policy-group create|modify|delete|show`.
- "A policy can be either a fixed policy or an adaptive one, not both." 생성 필수: `svm.uuid` 또는 `svm.name`, `name`, `fixed.*` 또는 `adaptive.*`.
- 정책 필드: `name`, `uuid`, `svm`, `scope`(`cluster`|`svm`), `object_count`, `pgid`, `policy_class`(`undefined`, `preset`, `user_defined`, `system_defined`, `autovolume`, `load_control`).
- `fixed.*`:
  - `max_throughput_mbps`: "specified in terms of Mbps. 0 means no maximum throughput is enforced."
  - `max_throughput_iops`: IOPS 상한. `max_throughput`: "Kbps, Mbps or Gbps along with or without IOPS"를 담는 문자열.
  - `min_throughput_mbps`, `min_throughput_iops`, `min_throughput`: 하한(floor). "These floors are not guaranteed on non-AFF platforms or when FabricPool tiering policies are set."
  - `capacity_shared`(기본 false): true면 정책을 붙인 객체 전체의 **합**이 상한을 공유한다(예: 1000 IOPS 정책을 볼륨 4개에 붙이면 4개 합이 1000). false면 객체마다 따로 1000. "Once capacity_shared is set, it cannot be modified."
- `adaptive.*`: `expected_iops`, `peak_iops`(둘 다 IOPS per TB), `expected_iops_allocation`·`peak_iops_allocation`(`allocated_space`|`used_space`), `absolute_min_iops`, `block_size`. "Adaptive parameters can specify the variable SLOs in terms of IOPS/TB. The actual IOPS enforced on the storage object can be calculated using the allocated space on the storage object." 즉 adaptive에는 MB/s 필드가 없다.
- 단위: 필드 이름과 설명은 "Mbps", 개요는 "MB/s"라고 쓴다. 10진 MB(10^6)인지 MiB인지는 이 원문에서 확인되지 않는다 [미확인]. ANF는 MiB/s다 [스펙 S1].
- 비동기: 휠 예제가 `post(hydrate=True, return_timeout=0)`, `patch(..., return_timeout=0)`를 쓴다. 이 인자는 job으로 끝나는 작업에 쓰이므로 POST/PATCH/DELETE가 job(202)을 돌려줄 수 있다고 본다 [추론 — 휠 예제]. ONTAP REST 원문의 응답 코드와 오류 코드는 [미확인].

### ONTAP REST: 볼륨의 `qos` [ONTAP O1 — `resources/volume.py`, `models/volume_qos.py`]
- "SLO can be set by specifying qos.max_throughput_iops and/or qos.max_throughput_mbps or qos.min_throughput_iops and/or qos.min_throughput_mbps ... A pre-created QoS policy can also be used by specifying qos.name or qos.uuid property."
- 스키마는 `qos.policy` 아래에 있다: `qos.policy.{name, uuid, max_throughput, max_throughput_iops, max_throughput_mbps, min_throughput, min_throughput_iops, min_throughput_mbps}`. 예시 GET: `"qos": {"policy": {"uuid": "228454af-…", "name": "pg1"}}`. 개요 문장의 `qos.name`/`qos.uuid`와 스키마의 `qos.policy.name`/`qos.policy.uuid`가 다르다. 스키마를 따르는 것이 맞다 [추론].
- 볼륨 POST·PATCH의 받는 필드 목록에 `qos.*`가 있다. 즉 볼륨 PATCH로 정책을 붙이거나 정책 없이 상한 값을 직접 줄 수 있다. ASA r2 personality에서는 `qos.policy.*`가 PATCH 불가(immutable) 목록에 있다.

### ANF ↔ ONTAP 대응표

| ANF 개념 | ONTAP 개념 | 설명 | 근거 표시 |
| --- | --- | --- | --- |
| Manual QoS 볼륨 `throughputMibps` | fixed QoS policy(`capacity_shared: false`)의 `max_throughput_mbps`, 또는 볼륨 `qos.policy.max_throughput_mbps` | 객체 하나에 고정 상한 하나. 단위가 MiB/s와 Mbps로 다르다. | 필드 [ONTAP O1], 대응 [추론] |
| Auto QoS (할당량 비례) | adaptive QoS와 "크기에 비례하는 상한"이라는 점이 닮았다 | adaptive는 IOPS/TB만 정의해 MiB/s per TiB를 표현하지 못한다. 그래서 ANF가 adaptive 정책을 그대로 쓴다고 보기 어렵다. 할당량이 바뀔 때마다 fixed 상한을 다시 계산해 넣는 방식과도 같은 결과가 나온다. 어느 쪽인지 공개 근거는 없다. | adaptive 필드 [ONTAP O1], 대응 [추론] |
| Manual 풀 예산 (`utilizedThroughputMibps` ≤ `totalThroughputMibps`) | 직접 대응 없음 | ANF는 볼륨별 상한의 **합을 배정할 때 검사**한다. ONTAP `capacity_shared: true`는 여러 객체가 상한 하나를 **실행 중에 나눠 쓰는** 것이라 다르다. ANF Elastic(shared QoS) 풀이 `capacity_shared`에 가깝다 [문서 D1]. | [추론] |
| 서비스 수준 | 직접 대응 없음 | 서비스 수준은 "볼륨 할당량 대비 허용 최대 처리량"으로 정의된다 [문서 D1]. 풀 브리프의 [추론] 인용. | [추론] |
| QoS 하한 | `min_throughput_*` (floor) | ANF 볼륨 API에는 하한 속성이 없다 [스펙 S1]. | [스펙], [ONTAP O1] |

- ANF가 내부에서 ONTAP QoS policy group을 쓰는지: 이번 조사 범위의 원문(Learn 문서 9개, 스펙, 녹화, ONTAP 휠)에서 찾지 못했다 [미확인]. ANF 문서는 "Throughput limit reached ... the volume is hitting its QoS limits", "QoS Latency Delta"라는 지표 이름을 쓴다 [문서 D6]. ONTAP QoS 용어와 같은 말이지만 그것만으로 구현을 단정할 수 없다 [추론].
- 면접에서 쓸 때 안전한 문장: "ANF Manual QoS는 볼륨마다 MiB/s 상한을 주고, 풀은 그 합을 예산으로 검사한다. ONTAP에서 가장 닮은 것은 non-shared fixed QoS policy의 `max_throughput_mbps`이고, Auto QoS의 할당량 비례는 adaptive QoS와 생각이 같지만 adaptive는 IOPS/TB라 단위가 다르다. ANF 내부 구현은 공개되지 않았다."

## 3. 한도의 의미 (데이터 플레인에서 보이는 효과)

- **읽기+쓰기 합산**: "Throughput is a combination of read and write speed." [문서 D1], "Throughput limits are a combination of read and write speed." [문서 D2].
- **한도에 닿았을 때**: "When a volume approaches its configured QoS throughput limit, latency starts to increase. After the volume throughput limit is reached, the system queues extra I/O requests and latency can rise rapidly while throughput stays capped." [문서 D2]. 즉 I/O 오류가 아니라 지연 증가와 처리량 상한으로 보인다.
- **지표**: "Throughput limit reached"(0/1, 5분마다 수집), "QoS Latency Delta"(볼륨의 QoS 지연 합) [문서 D6]. 볼륨 처리량 지표는 Read, Write, Other("Other throughput (that isn't read or write)"), Total("Sum of all throughput (read, write, and other)")로 나뉜다 [문서 D6]. 풀 지표 "Pool allocated throughput"은 볼륨 처리량(배정값) 합이다 [문서 D6].
- **메타데이터·스냅샷 읽기**: 메타데이터 I/O는 "Other" 지표로 따로 집계된다 [문서 D6]. 그것이 QoS 한도에 포함되는지, `.snapshot` 아래 파일 읽기가 같은 볼륨 한도에 포함되는지는 문서에 없다 [미확인]. 스냅샷은 같은 볼륨의 `.snapshot`으로 읽으므로 볼륨 한도에 포함된다고 보는 것이 자연스럽다 [추론].
- **한도 변경과 I/O**: 할당량 변경은 "nearly instantaneous", "does not interrupt or impact the volume access or I/O" [문서 D2]. Manual `throughputMibps` 변경도 "you can modify the allotted volume throughput as needed" [문서 D3]라고만 쓰고, 끊김 여부는 따로 적지 않았다 [미확인]. 같은 QoS 메커니즘이므로 같다고 본다 [추론].
- **클론에서 이미 잰 것** (S2 [A1] 인용, 실험 인스턴스 `s2-srv-*`, 2026-11-07): tc HTB로 v3·v4.1 모두 설정값의 약 95%(헤더 바이트 포함), 읽기+쓰기 합산, `tc class change`로 실시간 변경, 같은 클라이언트의 다른 볼륨은 영향 없음. 지금의 agent 인스턴스(`anf-nfs-<uuid>`, 재시작·되돌리기 창·복구)와 1 MiB/s 미만의 낮은 한도에서는 재지 않았다 (`00_progress.md`, 스파이크 S7 대상).

## 비동기 동작

| 작업 | 응답 | 상태 전이 | 근거 |
| --- | --- | --- | --- |
| Manual 풀 PUT | 201 `Creating` + `Azure-AsyncOperation` | 같은 초에 `Succeeded`, 이어서 `totalThroughputMibps` 채워짐 | [녹화 R1] |
| 풀 PATCH `qosType: Manual` | 202 `Patching` + 추적 헤더 | `Succeeded`, 약 0.29~0.48초 | [녹화 P1] (풀 브리프 인용) |
| 볼륨 그룹 PUT (Manual 볼륨 3개) | 201 `Creating` + `Azure-AsyncOperation` + `Location` | 약 6분 `Creating` → `Succeeded` | [녹화 R1] |
| 볼륨 PATCH `usageThreshold` (Auto 한도 변경) | 202 `Patching` | `Succeeded` 뒤 `actualThroughputMibps` 변경 | [녹화 R6] (볼륨 브리프 V4 인용) |
| 볼륨 PATCH `throughputMibps` (Manual) | [미확인] | [미확인] | 녹화 없음. 다른 볼륨 PATCH처럼 202 `Patching`일 것 [추론] |
| 개별 볼륨 PUT (Manual 풀, `throughputMibps`) | [미확인] | [미확인] | 녹화 없음. 볼륨 PUT과 같은 201 `Creating`일 것 [추론] |

## 구현 범위 후보

### 이번에 재현할 것 (후보)
- Auto QoS 한도의 실제 적용: 볼륨 생성·복구·되돌리기 뒤에도 인스턴스의 tc 한도 = `actualThroughputMibps` (FR-08 핵심, 문서 D1·D2).
- Manual QoS 볼륨 `throughputMibps`: 생성과 PATCH, 1~4,500 범위 검사, 풀 예산 검사("Requested throughput not available"), `utilizedThroughputMibps` = 배정 합 (FR-08 수락 기준 "제한을 바꾸면 잰 값도 바뀐다"를 Manual PATCH로 보일 수 있다).
- Auto → Manual 전환 때 기존 볼륨 값 채우기 (이미 풀 PATCH가 전환을 받으므로, 전환 뒤 볼륨에 값이 없으면 Manual 규칙이 깨진다).

### 다음으로 미룰 것
- 할당량(`usageThreshold`) 변경에 따른 Auto 한도 변경: FR-16(볼륨 크기 조정). FR-16에서 tc 갱신 경로만 재사용하면 된다.
- Flexible(`customThroughputMibps`, 24시간 쿨다운), Elastic(shared QoS), 대용량 볼륨 12,800 MiB/s, DP 볼륨의 별도 값(3.516): 이번 FR과 무관.
- 지표 "Throughput limit reached", "QoS Latency Delta": FR 지표 단계(Prometheus)에서.

### 리더·사용자가 정해야 할 선택지
1. **"제한을 바꾸면 잰 값도 바뀐다"를 무엇으로 보일지**: (a) Manual 볼륨 `throughputMibps` PATCH, (b) 할당량 PATCH(FR-16을 당겨 옴), (c) 둘 다.
2. **작은 검증 볼륨의 낮은 Auto 한도**: 1 GiB Premium = 0.0625 MiB/s는 실서비스에 없는 값이다(실서비스 최저 약 0.78 MiB/s [추론]). (a) 검증은 Manual 볼륨(최소 1 MiB/s)이나 Ultra·큰 sparse 볼륨으로 한다, (b) 공식대로 두고 S7 결과로 동작을 확인한다, (c) 클론에 하한을 둔다(실서비스와 달라지므로 문서화 필요).
3. **Manual 풀에서 `throughputMibps` 생략 시**: 기본값 [미확인]. (a) 400으로 거절, (b) Auto 공식 값으로 채움, (c) 남은 예산 등. 실서비스 근거가 없으므로 어느 쪽이든 "클론의 선택"으로 문서화해야 한다.
4. **Auto 풀 볼륨에 `throughputMibps`가 오면**: (a) 400 거절, (b) 무시. 지금 클론은 미룬 기능으로 거절한다(`00_progress.md`).
5. **Auto → Manual 전환 뒤 기존 볼륨 값**: [추론]대로 직전 `actualThroughputMibps`를 옮기고 4,500으로 자를지.
6. **예산 초과 오류의 형식**: 문구만 공개됐다. 동기 400(요청 검증) vs 비동기 작업 실패, `error.code` 이름을 클론이 정해야 한다.
7. **반올림**: 응답 값을 소수 셋째 자리로 자를지(녹화 6.312). half-even이면 Python `round`와 같다.
8. **Manual 볼륨의 `actualThroughputMibps`**: 녹화처럼 `throughputMibps`와 같게 보일지, 스펙 설명처럼 Auto 전용으로 둘지.
9. **agent API 모양**: (a) ONTAP처럼 `/api/storage/qos/policies`를 만들고 볼륨 `qos.policy.uuid`로 붙인다, (b) 볼륨 PATCH의 `qos.policy.max_throughput_mbps`만 받는다(정책 객체 없음, 더 단순). 단위도 정해야 한다(ONTAP `mbps` 이름에 MiB/s 값을 넣을지, 클론 확장 필드를 둘지).
10. **풀 축소로 예산 < 배정 합이 될 때**: 실서비스 동작 [미확인]. 거절할지.

### 검증 기준 후보 (클라이언트에서 관찰)
1. Auto 볼륨: GET `actualThroughputMibps` = 공식 값. 클라이언트 컨테이너의 fio 순차 읽기·쓰기 처리량이 그 값 이하(허용 오차는 S2/S7 기준)다. NFSv3·v4.1 둘 다.
2. 읽기와 쓰기를 동시에 돌리면 둘의 합이 한도 이하다.
3. 제한 없는(또는 훨씬 높은 한도의) 볼륨을 같은 클라이언트에서 함께 재면 그쪽이 확실히 빠르다. 한 볼륨이 한도에 걸려도 다른 볼륨은 느려지지 않는다.
4. Manual 볼륨: `throughputMibps` X로 만들면 잰 값 ≤ X. PATCH로 Y로 바꾸면 리마운트 없이, I/O 오류 없이 잰 값이 Y 근처로 바뀐다.
5. 한도에 걸린 동안 I/O 오류가 없고 지연만 늘어난다.
6. Manual 풀에서 `throughputMibps` 합이 `totalThroughputMibps`를 넘는 생성·PATCH는 실패하고, 기존 볼륨 값과 tc 한도는 그대로다. 풀 GET `utilizedThroughputMibps`는 배정 합이다.
7. 범위 밖 값(0.5, 4,501)은 거절된다.
8. Auto → Manual 전환 뒤 기존 볼륨의 잰 처리량이 바뀌지 않는다(선택지 5를 [추론]대로 정했을 때).
9. agent 재시작, 인스턴스 재시작, 스냅샷 되돌리기 뒤에도 한도가 유지된다.

## 미확인 목록

| 항목 | 설계를 막는가 (리더 판단용) | 시도한 곳 |
| --- | --- | --- |
| Manual 풀 볼륨에서 `throughputMibps` 생략 시 기본값·오류 | 선택지 3을 정해야 함. 근거 없이 클론 선택으로 갈 수 있음 | 스펙 S1(`default` 없음), 문서 D1·D3·D5·D7, 녹화 176개 요청 본문 |
| Auto 풀 볼륨에 `throughputMibps`를 보낼 때 거절/무시 | 선택지 4 | 스펙 S1 설명, 문서 D1·D3, 녹화 |
| 예산 초과 "Requested throughput not available"의 HTTP 코드·`error.code`·동기/비동기 | 선택지 6 (오류 형식) | 문서 D5(문구만), 녹화 (실패 사례 없음) |
| Auto → Manual 전환 뒤 기존 볼륨 `throughputMibps` | 선택지 5. [추론]은 있음 | 문서 D3("might be capped"), D7, D8, 녹화 P1·P2(볼륨 유무 미확인) |
| Auto QoS 한도의 하한 | 선택지 2. 문서상 없음으로 보임 | 문서 D1, D2, D4 |
| `throughputMibps` 소수 허용 여부 | 막지 않음 (float이므로 받는 쪽이 자연스러움) | 스펙 S1, 녹화 R1(정수만) |
| 반올림 방식(half-even vs 버림) | 막지 않음 | 녹화 R3(값 하나) |
| Auto 공식 값이 4,500을 넘을 때 `actualThroughputMibps` 표시 | 막지 않음 (검증 볼륨은 작음) | 문서 D2, 녹화 |
| 풀 축소로 예산 < 배정 합 | 선택지 10 | 문서 D5, D9 |
| 메타데이터("Other")·`.snapshot` 읽기가 한도에 포함되는지 | 막지 않음 (tc는 바이트 전체를 센다) | 문서 D6 |
| Manual `throughputMibps` 변경이 I/O를 끊지 않는지 | 막지 않음 ([추론] 같음) | 문서 D2, D3 |
| ONTAP `max_throughput_mbps` 단위(MB vs MiB), QoS policy REST 응답 코드·job·오류 코드 | 막지 않음 (agent 계약은 클론이 정함, 개념 문서용) | ONTAP 휠 9.19.1.0. docs.netapp.com은 이번에 시도하지 않음 |
| ANF가 내부에서 ONTAP QoS policy를 쓰는지 | 막지 않음 (개념 문서에서 [추론]으로) | 문서 9개, 스펙, 녹화 |
| Manual 볼륨 개별 PUT·`throughputMibps` PATCH의 실서비스 응답과 걸린 시간 | 막지 않음 ([추론] 202/201) | .NET 144개, 파이썬 32개 녹화 |

## 후속 조사 목록
- DP(복제 대상) 볼륨의 `actualThroughputMibps` 3.516 규칙 (CRR 사이클).
- Flexible 풀 `customThroughputMibps`와 24시간 쿨다운 (풀 브리프에 있음).
- Elastic(shared QoS) 풀과 ONTAP `capacity_shared`의 관계.
- 지표 "Throughput limit reached", "QoS Latency Delta", "Other throughput" (지표 단계).
- ONTAP `qos policy-group` 원문(docs.netapp.com)과 `policy_class: autovolume`의 뜻 (개념 문서용).

## 출처
- [S1] Azure REST API specs — `specification/netapp/resource-manager/Microsoft.NetApp/NetApp/stable/2026-08-01/netapp.json` (`VolumeProperties`, `VolumePatchProperties`, `PoolProperties`, `QosType`), 같은 커밋의 `Volume.tsp`. 저장소 `Azure/azure-rest-api-specs`, 커밋 `3b64c3a12af9938128abcf05d04c323a518ea78a`. 사본: `_workspace/capacity-pool/sources/spec/netapp-2026-08-01.json`, `_workspace/volume/sources/spec/Volume.tsp` (재사용).
- [S2] 같은 커밋의 `examples/Volumes_CreateOrUpdate.json`, `Volumes_Get.json`, `Volumes_List.json`, `Volumes_Update.json`. 사본: `_workspace/volume/sources/spec/examples/` (재사용).
- [D1] Microsoft Learn — Service levels for Azure NetApp Files (`azure-netapp-files-service-levels.md`, ms.date 02/02/2026).
- [D2] Microsoft Learn — General performance considerations for Azure NetApp Files (`azure-netapp-files-performance-considerations.md`, ms.date 10/14/2026).
- [D3] Microsoft Learn — Manage a manual QoS capacity pool (`manage-manual-qos-capacity-pool.md`, ms.date 03/24/2025).
- [D4] Microsoft Learn — Resource limits for Azure NetApp Files (`azure-netapp-files-resource-limits.md`, ms.date 10/14/2026; 52~54행 Manual QoS 1/4,500/12,800 MiB/s, 37행 최소 볼륨 50 GiB).
- [D5] Microsoft Learn — Troubleshoot capacity pool errors (`troubleshoot-capacity-pools.md`, ms.date 05/18/2025; 24행).
- [D6] Microsoft Learn — Metrics for Azure NetApp Files (`azure-netapp-files-metrics.md`, ms.date 09/11/2026).
- D1~D6: 저장소 `MicrosoftDocs/azure-docs`, `articles/azure-netapp-files/`, 커밋 `121e31ad51402bbcc82f923c0951ac55cef58de2` (2026-11-09 받음). 사본: `_workspace/throughput-limit/sources/docs/`. 같은 곳에 `faq-performance.md`, `performance-benchmarks-linux.md`도 받았지만 읽지 않았다.
- [D7] Microsoft Learn — Storage hierarchy of Azure NetApp Files (QoS types). 사본: `_workspace/capacity-pool/sources/docs/azure-netapp-files-understand-storage-hierarchy.txt` (풀 조사 때 받은 HTML 텍스트, 재사용).
- [D8] Microsoft Learn — Dynamically change the service level of a volume. 사본: `_workspace/capacity-pool/sources/docs/dynamic-change-volume-service-level.txt` (재사용).
- [D9] Microsoft Learn — Resize a capacity pool or a volume. 사본: `_workspace/capacity-pool/sources/docs/azure-netapp-files-resize-capacity-pools-or-volumes.txt` (재사용).
- [R1] .NET SDK 녹화 `VolumeGroupTests__CreateDeleteVolumeGroup.json` (2026-10-30, api-version 2026-08-15-preview, northeurope).
- [R2] .NET SDK 녹화 `ANFBackupTests__CreateDeleteBackup.json` (2026-03-20, api-version 2025-12-15-preview).
- [R3] .NET SDK 녹화 `SnapshotTests__CreateShortTermCloneVolumeFromSnapshot.json` (2026-10-30, api-version 2026-08-15-preview, westus2), 항목 59.
- [R4] 파이썬 SDK 녹화 `test_volume.pyTestNetAppVolumetest_volume_replication.json` (2025-08-15), 항목 31~35.
- [R6] 파이썬 SDK 녹화 `test_volume.pyTestNetAppVolumetest_patch_volume.json` (볼륨 브리프 V4).
- [P1] 파이썬 SDK 녹화 `test_pool.pyTestNetAppCapacityPooltest_patch_pool.json` (풀 브리프 P1).
- R·P 녹화 사본: `_workspace/netapp-account/sources/recordings/net/`, `py/` (계정 조사 때 `Azure/azure-sdk-assets`에서 받음. 태그는 그 브리프의 출처 항목).
- [O1] NetApp ONTAP Python client library `netapp-ontap` 9.19.1.0 (PyPI wheel, "automatically generated based on the ONTAP REST API documentation") — `resources/qos_policy.py`, `models/qos_policy_fixed.py`, `models/qos_policy_adaptive.py`, `models/volume_qos.py`, `resources/volume.py`. 휠 사본: `_workspace/snapshot/sources/ontap/wheel/`, 추출 텍스트: `_workspace/throughput-limit/sources/ontap/`.
- [A1][A2] `_workspace/spikes/S2.md`의 출처 (Learn performance considerations, service levels) — 인용만.

## 변경 이력
- 2026-11-09 골격 저장, 요약·1·2절 작성
- 2026-11-09 4·3절, 비동기, 구현 범위 후보, 미확인 목록, 출처 작성. 30턴 상한으로 "한도 도달"로 마감
