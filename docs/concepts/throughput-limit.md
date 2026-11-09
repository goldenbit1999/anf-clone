# 처리량 제한 (throughput limit, QoS)

> ANF 볼륨의 처리량 한도는 Auto QoS 풀에서는 "서비스 수준 단가 × 할당량"이고, Manual QoS 풀에서는 볼륨마다 정한 `throughputMibps`다. 이 클론은 그 값을 볼륨 NFS 인스턴스의 네트워크 네임스페이스 안에서 tc로 건다. `eth0`의 양방향을 `ifb0` 하나로 보내 HTB 클래스 하나를 지나게 하므로 읽기와 쓰기가 한도 하나를 나눠 쓴다. 헤더 바이트를 빼려고 rate를 ÷0.9564로 걸었고, 클라이언트에서 잰 데이터 처리량의 중앙값은 한도의 95.6~99.3%였다. 이 문서의 중심은 두 가지다. 하나는 이 한도가 **상한일 뿐 격리가 아니라는 것**이다. 같은 aggregate의 이웃이 디스크에 많이 쓰면 한도보다 덜 받았다. 다른 하나는 **무엇으로 재느냐**다. 시계 하나와 카운터 하나를 잘못 골라 측정이 틀어진 일이 두 번 있었다.

코드 인용 기준: 커밋 `0b44a8f` (제품 코드 내용 해시 `f99bc5cfbcf1429d…`. 검증 1회차의 시작과 끝, 2회차의 시작이 모두 같다). e2e 시험 코드(`backend/tests/e2e/`)는 단조 시계 수정 `3328486` 뒤의 작업 트리(HEAD `bf4a65c`)에서 인용했다.

FR-08(처리량 제한)을 다룬다. 브랜치는 `feature/throughput-limit`이다. 풀의 `qosType`·`totalThroughputMibps`는 [용량 풀 문서](capacity-pool.md)에, 볼륨마다 knfsd 인스턴스와 IP를 두는 구조(D-12의 앞부분)는 [볼륨 문서](volume.md)에, 되돌리기 창(인스턴스 netns의 iptables)은 [되돌리기 문서](snapshot-revert.md)에, 스냅샷에서 새 볼륨 만들기는 [복원 문서](restore-new-volume.md)에 있다. 이 문서는 그것들 위에 한도를 어떻게 얹었는지만 설명한다.

근거 표시는 브리프를 따른다.

| 표시 | 뜻 |
| --- | --- |
| [스펙] | Azure REST API 스펙(OpenAPI/TypeSpec)에 적혀 있다 |
| [문서] | Microsoft Learn이나 NetApp 문서에 적혀 있다 |
| [녹화] | Azure SDK 테스트 녹화에서 실서비스 응답으로 관찰했다. 문서로 보장된 동작은 아니다 |
| [ONTAP] | `netapp-ontap` 9.19.1.0 휠(ONTAP REST 문서에서 생성된 클라이언트)에 적혀 있다 |
| [추론] | 근거에서 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |
| [클론 측정] | 스파이크 S7·S2와 검증자의 측정이다. ANF·ONTAP 사실이 아니라 이 클론의 동작이다 |

**이 기능의 조사 상태는 "한도 도달"이다(30턴 상한).** Manual 풀 볼륨에서 `throughputMibps`를 뺐을 때의 기본값, 예산 초과의 HTTP 코드, Auto → Manual 전환 뒤 기존 볼륨 값, 풀 축소 규칙은 [미확인]이다. 그래서 이 문서의 거절 규칙과 코드는 대부분 **클론이 정한 것**이다. 면접에서 실서비스 값처럼 말하면 안 된다.

**설계 결정 1~19는 모두 자동 채택이다.** 로드맵 총괄(`anf-roadmap`)이 사용자에게 물어야 하는 결정(확정된 D-nn이나 `CLAUDE.md` "Decided" 변경, PRD 수락 기준 축소, 기기·저장소 설정, 스파이크 실패)이 없다고 판단해 사람에게 묻지 않고 골랐다. 구현 중 변경 두 건과 검증 뒤 판정 두 건도 리더가 자동 채택했다. 3절의 표에 버린 대안과 그 이유를 모두 적었다.

---

## 1. ANF에서는

### 1.1 Auto QoS: 할당량에 비례하는 한도

- **단가.** Standard 16, Premium 64, Ultra 128 MiB/s per TiB다 [문서].
- **공식.** 볼륨 한도 = 단가 × 볼륨 할당량(`usageThreshold`, 2진 TiB)이다. 문서 예: Premium 2 TiB → 128 MiB/s, Premium 100 GiB → 6.25 MiB/s. "This scenario applies regardless of the capacity pool size or the actual volume consumption." [문서]. 즉 풀 크기도 실제 사용량도 상관없다.
- **응답 필드.** `actualThroughputMibps`(float32, 읽기 전용) "for auto qosType volumes calculated based on size and serviceLevel" [스펙].
- **녹화에서 본 값.**

  | 서비스 수준 | `usageThreshold` | `actualThroughputMibps` | 정확한 공식 값 | 근거 |
  | --- | --- | --- | --- | --- |
  | Premium | 100 GiB | 6.25 | 6.25 | [녹화] |
  | Premium | 200 GiB | 12.5 | 12.5 | [녹화] |
  | Premium | 101 GiB | **6.312** | 6.3125 | [녹화] |

- **반올림.** 6.3125가 6.312로 보였으므로 소수 셋째 자리로 맞춘다. half-up이면 6.313이어야 하니 half-up은 아니다. half-even(Python `round`)과 버림 중 어느 것인지는 이 값 하나로 가를 수 없다 [추론].
- **하한.** Auto 한도에 따로 정한 최소 MiB/s는 문서에 없다 [미확인]. ANF 일반 볼륨의 최소 크기가 50 GiB라서 [문서], 공식만 적용하면 실서비스의 가장 낮은 Auto 한도는 Standard 50 GiB = 0.78125 MiB/s(표시 0.781)다 [추론]. 클론의 검증용 1 GiB Premium 볼륨(0.0625 MiB/s)은 실서비스에서 생기지 않는 값이다 [추론].
- **상한.** 일반 볼륨의 실제 최대는 4,500 MiB/s이고, Premium Auto는 할당량 70.31 TiB에서 그 수준에 닿는다. 그 이상 늘려도 실제 처리량은 늘지 않는다 [문서]. 그때 `actualThroughputMibps`가 공식 값(예: 100 TiB Premium = 6,400)인지 4,500인지는 [미확인].
- **한도가 바뀌는 때.** 할당량을 바꾸면 "the corresponding change in throughput limit is nearly instantaneous. The change does not interrupt or impact the volume access or I/O." [문서]. 녹화에서 볼륨 PATCH(`usageThreshold` 200 GiB) → `202 Patching` → 끝난 뒤 6.25 → 12.5였다 [녹화]. 풀 크기를 바꿔도 Auto 볼륨 한도는 그대로다 [문서].

### 1.2 Manual QoS: 볼륨마다 정하는 한도

- **속성.** `throughputMibps`(float32, `x-nullable`)는 생성 모델과 PATCH 모델 모두에 있고, 설명은 "will be accepted as input only for manual qosType volume"이다. 스펙에 `minimum`·`maximum`·`default`가 없다 [스펙].
- **범위.** 최소 1 MiB/s, 일반 볼륨 최대 4,500 MiB/s, 대용량 볼륨 최대 12,800 MiB/s다 [문서].
- **소수.** 타입은 float다 [스펙]. 녹화는 정수 `6`만 보냈다(응답 `6.0`) [녹화]. `1.5` 같은 소수를 받는지는 [미확인].
- **크기와 무관하다.** "you can assign the capacity and throughput for a volume independently" [문서]. 녹화에서 100 GiB 볼륨(Auto라면 6.25)에 6 MiB/s를 줬다 [녹화].
- **응답.** 볼륨 GET에서 `throughputMibps: 6.0`, `actualThroughputMibps: 6.0`이었다. 같은 녹화의 볼륨 그룹 GET 안에서는 `actualThroughputMibps: 0.0`이었다 [녹화]. 스펙 설명("for auto qosType volumes")과 다르다.
- **Auto 볼륨의 `throughputMibps`.** 파이썬 SDK 녹화에서는 응답에 없고, .NET 녹화에서는 `0.0`이다 [녹화].
- **확인하지 못한 것** [미확인]: Manual 풀 볼륨에서 생략할 때의 기본값, Auto 풀 볼륨에 보냈을 때 거절인지 무시인지, 개별 볼륨 PUT·`throughputMibps` PATCH의 실서비스 응답. 녹화는 볼륨 그룹 경로뿐이었다.

### 1.3 풀 처리량 예산

- **총 처리량.** 풀 `totalThroughputMibps` = 풀 크기(TiB) × 단가다. "The total throughput of all volumes created with a manual QoS capacity pool is limited by the total throughput of the pool." [문서].
- **쓰인 처리량.** 4 TiB Premium Manual 풀(256.0)에 100 GiB 볼륨 3개를 각 6 MiB/s로 만들자 `utilizedThroughputMibps`가 18.0이 됐다 [녹화]. Auto 풀에서도 볼륨 한도의 합이다(4 TiB Premium + 100 GiB 볼륨 하나 → 6.25) [녹화]. 지표 문서도 "Pool allocated throughput: Sum of the throughput of all the volumes belonging to the pool."이라고 쓴다 [문서]. 즉 실측 사용량이 아니라 **배정된 한도의 합**이다.
- **넘으면.** "Volume creation or modification fails with `Requested throughput not available` error. ... you should increase the pool size or adjust the existing volume throughput." [문서]. HTTP 상태 코드, `error.code`, 동기 거절인지 비동기 작업 실패인지는 [미확인].
- **풀을 줄여 총 처리량이 배정 합보다 작아질 때**: 문서에 없다 [미확인]. 거절될 가능성이 높다 [추론].

### 1.4 Auto → Manual 전환

- 영구 변경이고 되돌릴 수 없다 [문서]. 풀 PATCH `{"qosType": "Manual"}` → `202 Patching` → `Succeeded`, 약 0.29~0.48초였다 [녹화].
- "At conversion time, throughput levels might be capped to conform to the throughput limits for volumes of the manual QoS type." [문서].
- 전환 뒤 기존 볼륨의 `throughputMibps` 값은 공개 자료에 없다 [미확인]. 다음 두 근거로 보면 "직전 Auto 한도를 그대로 옮기고, Manual 최대(4,500)를 넘는 값만 깎는다"로 읽힌다 [추론].
  - Manual 풀로 볼륨을 옮기면 "the volume's throughput isn't changed with the volume move" [문서].
  - 같은 풀 안에서는 할당량 합 ≤ 풀 크기이고 단가가 같으므로 Auto 한도 합 ≤ 풀 총 처리량이다. 그래서 "capped"는 4,500을 넘는 큰 볼륨에만 의미가 있다 [추론].

### 1.5 한도가 데이터에 주는 효과

- **읽기와 쓰기의 합이다.** "Throughput limits are a combination of read and write speed." [문서].
- **한도에 닿으면 오류가 아니라 지연이다.** "After the volume throughput limit is reached, the system queues extra I/O requests and latency can rise rapidly while throughput stays capped." [문서].
- **지표.** "Throughput limit reached"(0/1, 5분마다), "QoS Latency Delta"가 있다. 볼륨 처리량은 Read, Write, Other("that isn't read or write"), Total로 나뉜다 [문서].
- 메타데이터("Other")와 `.snapshot` 읽기가 한도에 포함되는지는 [미확인]. `.snapshot`은 같은 볼륨으로 읽으므로 포함된다고 보는 것이 자연스럽다 [추론]. Manual 값 변경이 I/O를 끊지 않는지도 문서에 따로 없다 [미확인]. 할당량 변경과 같은 메커니즘이라 같다고 본다 [추론].

---

## 2. ONTAP에서는

### 2.1 QoS policy

- **경로.** `/api/storage/qos/policies`다. CLI로는 `qos policy-group …`, `qos adaptive-policy-group …`에 대응한다 [ONTAP]. "A policy can be either a fixed policy or an adaptive one, not both." [ONTAP].
- **fixed 정책.** [ONTAP]
  - `max_throughput_mbps`: "specified in terms of Mbps. 0 means no maximum throughput is enforced." IOPS 상한 `max_throughput_iops`도 있다.
  - `min_throughput_mbps`·`min_throughput_iops`: 하한(floor)이다. "These floors are not guaranteed on non-AFF platforms or when FabricPool tiering policies are set."
  - `capacity_shared`(기본 false): true면 정책을 붙인 객체 전체의 **합**이 상한 하나를 나눠 쓴다. false면 객체마다 따로 상한을 받는다. 한 번 정하면 바꿀 수 없다.
- **adaptive 정책.** `expected_iops`, `peak_iops`(둘 다 IOPS per TB), 그 기준(`allocated_space`/`used_space`), `absolute_min_iops`, `block_size`가 있다. "Adaptive parameters can specify the variable SLOs in terms of IOPS/TB." MB/s 필드는 없다 [ONTAP].
- **볼륨 쪽.** 볼륨 스키마의 `qos.policy.{name, uuid, max_throughput_mbps, max_throughput_iops, min_throughput_mbps, …}`로 미리 만든 정책을 붙이거나 값을 직접 준다. 볼륨 POST·PATCH가 `qos.*`를 받는다 [ONTAP]. 개요 문장은 `qos.name`이라고 쓰지만 스키마를 따르는 것이 맞다 [추론].
- **단위.** 필드 이름과 설명은 "Mbps", 개요는 "MB/s"라고 쓴다. 10진 MB인지 MiB인지는 확인하지 못했다 [미확인]. ANF는 MiB/s다 [스펙].

### 2.2 ANF와의 대응

| ANF | ONTAP | 설명 | 근거 |
| --- | --- | --- | --- |
| Manual 볼륨 `throughputMibps` | fixed 정책(`capacity_shared: false`)의 `max_throughput_mbps`, 또는 볼륨 `qos.policy.max_throughput_mbps` | 객체 하나에 고정 상한 하나. 단위가 MiB/s와 Mbps로 다르다 | 필드 [ONTAP], 대응 [추론] |
| Auto QoS (할당량 비례) | adaptive QoS와 "크기에 비례하는 상한"이라는 생각이 같다 | adaptive는 IOPS/TB만 정의해 MiB/s per TiB를 표현하지 못한다. 할당량이 바뀔 때마다 fixed 상한을 다시 계산해 넣는 방식과도 결과가 같다. 어느 쪽인지 공개 근거는 없다 | 필드 [ONTAP], 대응 [추론] |
| Manual 풀 예산 | 직접 대응 없음 | ANF는 볼륨 상한의 합을 **배정할 때 검사**한다. `capacity_shared: true`는 상한 하나를 **실행 중에 나눠 쓰는** 것이라 다르다. ANF Elastic(shared QoS) 풀이 그쪽에 가깝다 | [추론] |
| QoS 하한 | `min_throughput_*` | ANF 볼륨 API에는 하한 속성이 없다 | [스펙], [ONTAP] |

- **ANF가 내부에서 ONTAP QoS policy를 쓰는지는 공개되지 않았다** [미확인]. ANF 지표 이름("the volume is hitting its QoS limits", "QoS Latency Delta")이 ONTAP 용어와 같지만 그것만으로 구현을 단정할 수 없다 [추론].
- **면접에서 안전한 문장** (브리프): "ANF Manual QoS는 볼륨마다 MiB/s 상한을 주고, 풀은 그 합을 예산으로 검사한다. ONTAP에서 가장 닮은 것은 non-shared fixed QoS policy의 `max_throughput_mbps`이고, Auto QoS의 할당량 비례는 adaptive QoS와 생각이 같지만 adaptive는 IOPS/TB라 단위가 다르다. ANF 내부 구현은 공개되지 않았다."

### 2.3 클론 agent가 받는 ONTAP 모양

storage agent는 ONTAP REST 부분집합을 제공한다(D-06). 이번에 볼륨 POST의 인라인 필드 `qos: {"policy": {"max_throughput_mbps": N}}`을 더했다(결정 8). ONTAP과 다른 점은 셋이다.

1. **값은 MiB/s이고 소수를 받는다.** Auto 한도가 0.062, 6.312처럼 소수이기 때문이다. ONTAP 필드 이름의 "Mbps"를 그대로 두고, 단위 차이는 문서로 설명한다. (설계 기록은 ONTAP 값을 정수로 적었지만, 브리프가 인용한 원문에는 타입이 없다.)
2. **정책 객체가 없다.** `/api/storage/qos/policies`, `qos.policy.name`/`uuid`, IOPS·하한 필드는 없다. GET 레코드는 ONTAP처럼 정책 이름이 아니라 값(`qos.policy.max_throughput_mbps`)을 보인다.
3. **한도 변경도 볼륨 POST다.** ONTAP 볼륨은 PATCH로도 `qos.*`를 받는다 [ONTAP]. 클론의 볼륨 POST는 처음부터 uuid를 멱등 키로 쓰는 "보장(ensure)"이라, 같은 uuid에 다른 한도로 POST하면 태그와 tc가 그 값으로 맞춰진다.

---

## 3. 이 프로젝트에서는

### 구조

**컨트롤 플레인 → 데이터 플레인** (Manual 볼륨의 한도를 20으로 바꾸는 PATCH)

```
PATCH .../volumes/{v}  {"properties": {"throughputMibps": 20}}
  anf-api  volumes.patch_volume (volumes.py:529-552)
    _settle_throughput -> _apply_update -> _check_throughput_change (_check_qos_type, 올릴 때만 _check_budget)
    한 트랜잭션: 볼륨 행(Patching, 새 값) + PATCH 작업 -> 202 + 두 추적 헤더
  LRO 워커 -> 볼륨 ensure 처리기 (volumes.py:635-642)
    qos = volume_throughput_mibps(props)          <- 응답의 actualThroughputMibps와 같은 값
    StorageClient.ensure_volume(..., qos=20.0)
      POST /api/storage/volumes {uuid, name, size, nas, "qos": {"policy": {"max_throughput_mbps": 20.0}}}
  storage agent  _parse_qos -> job 키 "POST <uuid> qos=20.0" -> FlexVolManager.create
    _ensure_qos:  lvchange --deltag anf_qos=10.0 --addtag anf_qos=20.0 anf/vol_<uuid32>
    NfsInstances.ensure:  start(이미 돎) -> limit -> wait_ready
      nsenter -t <pid> -n tc class replace dev ifb0 parent 1: classid 1:1 htb rate 175420494bit ceil 175420494bit
```

**데이터 경로** (볼륨 인스턴스 하나)

```
클라이언트 컨테이너 (anf-vnet)
   │  NFS over TCP -> 볼륨 IP (172.30.0.129~)
   ▼
anf-vnet 브리지 ── veth 호스트 쪽 끝 (여기에는 tc가 없다)
                     │
── 인스턴스 netns (컨테이너 anf-nfs-<uuid32>) ─────────────────────────────
                     ▼
                   eth0   qdisc clsact
                     ├ ingress: matchall -> mirred egress redirect dev ifb0   (들어오는 쪽: WRITE 데이터, 요청)
                     └ egress:  matchall -> mirred egress redirect dev ifb0   (나가는 쪽: READ 데이터, 응답)
                     ▼
                   ifb0   root qdisc htb 1:  default 1
                            └ class 1:1   rate = ceil = 한도 × 1,048,576 × 8 ÷ 0.9564  (bit/s)
                                 └ leaf qdisc fq_codel 10:   (흐름마다 대기열)
                     ▼
                   knfsd (들어오는 패킷) / 클라이언트 (나가는 패킷)
```

한 방향마다 필터 하나가 같은 `ifb0`의 같은 클래스로 보낸다. 그래서 버킷이 하나다. 명령은 호스트의 `ip`·`tc`를 `nsenter -t <인스턴스 pid> -n`으로 netns 안에서 쓴다. 인스턴스 이미지(alpine)에는 `tc`가 없다(S7 N5).

### 코드 따라가기

#### (1) anf-api: 한도 공식 — `capacity_pools.py:139-155`

- `total_throughput_mibps`(`:139-141`): 풀 크기(2진 TiB) × 단가(`MIBPS_PER_TIB`, `:41`). 4 TiB Premium = 256.0.
- `volume_throughput_mibps`(`:144-150`): **한도는 이 함수 하나에서 나온다.** 볼륨 행에 `throughputMibps`가 있으면(Manual) 그 값을, 없으면(Auto) `round(usageThreshold / TIB × 단가, 3)`을 돌려준다.
- 이 값을 세 곳이 쓴다. 응답의 `actualThroughputMibps`(`volumes.py:302`, `volume_body`), 풀의 `utilizedThroughputMibps`(`utilized_throughput_mibps`, `:153-155`), agent에 거는 값(`volumes.py:642`)이다. 그래서 **보이는 값이 곧 거는 값**이다(결정 2).
- `utilizedThroughputMibps`는 풀의 모든 볼륨 행(상태와 무관)의 한도 합을 셋째 자리로 반올림한다(설계 §9-3). 풀 본문이 볼륨 행을 받아야 하므로 `pool_body(res, volumes)`(`:158-180`)로 바꿨고, `arm_app.py:118-120`이 `store.list_children(res.id, VOLUME_TYPE)`을 넘기는 감싼 함수를 등록한다. 한도 공식을 `capacity_pools`에 두고 `volumes`가 가져다 써서 순환 import를 피했다(설계 §9-7).

#### (2) anf-api: `throughputMibps` 본문 규칙 — `volumes.py:165-168`, `:182-201`, `:222`

- 본문 단계(`_check_property`, `:165-168`)는 **타입만** 본다. 숫자이고 불리언이 아니어야 하며, `float`로 저장한다. 그래서 `10`은 `10.0`으로 응답한다.
- `null`은 없는 것으로 본다(`:222`, 스펙 `x-nullable`, 설계 §9-6).
- 범위 1~4,500(`_MAX_THROUGHPUT`, `:47`)은 `_check_throughput_range`(`:186-190`)가 본다. 생성은 늘 본다(`put_volume`, `:506`). 갱신은 `_settle_throughput`(`:193-201`)을 거친다. 새 값이 저장된 값과 **소수 셋째 자리까지 같으면** "바꾸지 않음"으로 보고 저장된 값을 그대로 두며 범위를 보지 않는다. 다를 때만 범위를 본다(설계 §9-5, §9-13). 이유는 3.8절에 있다.
- `throughputMibps`는 `_CHANGEABLE`(`:85`)에 있어 생성 뒤에도 PUT·PATCH로 바꿀 수 있다.

#### (3) anf-api: 풀에 기대는 규칙 — `volumes.py:334-365`, `:383`, `:415-416`

- `_check_qos_type`(`:334-343`): Auto 풀 볼륨에 값이 있으면 `400 BadRequest`, Manual 풀 볼륨 생성에 값이 없으면 `400 InvalidRequestContent`다(결정 3·4).
- `_check_budget`(`:346-355`): "같은 풀의 다른 모든 볼륨 행 한도 합 + 새 값 > 풀 총 처리량"이면 `400 BadRequest` "Requested throughput not available. Capacity pool '{pool}' has {total} MiB/s in total and {free} MiB/s left for this volume."이다. 비교는 셋째 자리에서 하고, `free`는 0 밑으로 내려가지 않는다(설계 §9-3).
- 생성(`_new_volume`)은 풀 상태 검사 뒤 `_check_qos_type`(`:383`), 풀 용량 검사 뒤 Manual 풀이면 `_check_budget`(`:415-416`)이다. 스냅샷에서 새 볼륨을 만들 때도 같은 함수라 같은 규칙이다.
- 갱신(`_check_throughput_change`, `:358-365`)은 **한도를 올릴 때만** 예산을 본다(설계 §9-1). 줄이거나 같은 값이면 예산을 더 쓰지 않기 때문이다.
- 생성의 검사 순서: 본문 형식(범위 포함) → 풀 존재·상태 → QoS 유형 → 필수 속성 → … → 풀 용량 → 예산. 갱신은 리소스 존재·진행 중 작업·location 뒤에 범위(`_settle_throughput`), 그 뒤 바꿀 수 없는 속성, QoS 유형, 예산이다. 거절이면 볼륨 행도 작업도 생기지 않는다.

#### (4) anf-api: Auto → Manual 전환 — `capacity_pools._apply_changes`, `capacity_pools.py:190-238`

- 풀 PATCH(또는 재PUT)가 `qosType`을 Auto에서 Manual로 바꾸면(`to_manual`, `:214`):
  1. 자식 볼륨에 진행 중 작업이 하나라도 있으면 `409 Conflict`다(`:215-222`). 그 작업이 실패해 워커가 이전 properties로 되돌리면 아래에서 채운 값이 사라지기 때문이다(결정 6).
  2. 같은 트랜잭션에서 각 볼륨 행에 `throughputMibps = volume_throughput_mibps(직전 properties)`를 쓴다(`:233-237`). 직전 Auto 한도 그대로라 **데이터 플레인 작업이 없다.** 풀 PATCH는 지금처럼 agent를 부르지 않는다.
- Manual 풀 **크기를 줄일 때만**(`:223-232`) 새 총 처리량 < 배정 합이면 `400 BadRequest` "The capacity pool throughput of {total} MiB/s is too small for the combined volume throughput of {utilized} MiB/s of the capacity pool."이다(설계 §9-2).
- Manual → Auto는 기존대로 `400`이다(`:194-197`).

#### (5) anf-api: 처리기와 agent 클라이언트 — `volumes.py:635-642`, `storage_client.py:52-70`

- 볼륨 CREATE·UPDATE·PATCH 처리기 `ensure`는 늘 `qos=volume_throughput_mibps(props)`를 넘긴다(`:642`). 한도를 바꾸지 않은 PATCH(태그만)도 같은 값을 다시 보낸다. agent POST가 멱등 보장이라 해가 없다(결정 8).
- `StorageClient.ensure_volume`(`storage_client.py:52-70`)은 `qos`가 있으면 본문에 `{"qos": {"policy": {"max_throughput_mbps": qos}}}`를 넣는다(`:63-64`). job 폴링, 60초 연결 재시도, job이 사라지면 다시 보내기는 그대로다.
- 결함 주입 키는 기존 `volumes/create`·`volumes/update`·`volumes/patch`·`capacityPools/patch`다(결정 18).

#### (6) agent: 입력 다시 검사와 job 키 — `agent_app.py:60-99`, `:171-177`

- `_parse_qos`(`:60-72`): `qos`는 정확히 `policy` 하나, `policy`는 정확히 `max_throughput_mbps` 하나다. 값은 불리언이 아닌 유한한 숫자이고 0보다 커야 한다. **위쪽 한도는 두지 않는다.** Auto 값은 4,500을 넘을 수 있다. 그 밖은 `400`이다(R-07: agent도 입력을 다시 검사한다).
- `post_volume`(`:171-177`)의 job 키에 한도를 넣는다(`:175`): `POST <uuid> qos=<값>`. job 표는 같은 키의 요청에 진행 중인 job을 돌려준다. 키에 한도가 없으면, anf-api가 포기한 이전 job(예: 한도 10)이 아직 도는 동안 한도 20의 요청이 그 job에 합쳐져 "성공"을 받고 실제로는 10이 걸릴 수 있다. 되돌리기의 요청 키와 같은 이유다(결정 8).

#### (7) agent: 한도는 LVM 태그 — `flexvol.py:82-90`, `:124-125`, `:195-231`, `:540`, `:583-584`

- `_Volume.qos`(`:82`)는 태그 `anf_qos=<MiB/s>`다. `tags()`(`:88-90`)가 경로·uuid·IP·프로토콜 태그와 함께 낸다. `_qos_tag`(`:124-125`)는 `repr`로 써서 float로 되읽어도 같은 값이다(0.062, 12.5, 10.0).
- **새 LV는 만들 때부터 태그를 갖는다.** 일반 볼륨(`:514-518`), 스냅샷에서 만든 볼륨(`:509-512`), 되돌리기의 새 LV(`:382-385`, `vol.tags()`)가 모두 `tags()`를 쓴다. 그래서 되돌리기와 새 볼륨 복원이 한도를 그대로 물려받는다(결정 11).
- **있는 LV는 `_ensure_qos`(`:225-231`)가 맞춘다.** 요청 값이 없거나 같으면 아무것도 하지 않는다. 다르면 `lvchange --deltag anf_qos=<옛 값> --addtag anf_qos=<새 값>` **한 명령**이다. 끝나지 않은 되돌리기가 있으면 그것을 먼저 끝낸 뒤 바꾼다(`create`, `:207-209`). 새 LV가 옛 태그를 물려받은 뒤여야 하기 때문이다.
- `_report`(`:540`)가 태그를 읽고, GET 레코드(`_record`, `:583-584`)가 `qos.policy.max_throughput_mbps`를 보인다.
- `create`(`:195-223`)는 끝에서 `instances.ensure(..., vol.qos)`(`:223`)를 부른다. 스냅샷에서 만드는 볼륨은 `_finish_clone`이 같은 호출을 한다(`:254`).

#### (8) agent: tc 걸기 — `nfs_instance.py:44-53`, `:110-148`

- `htb_rate_bits`(`:51-53`) = `round(mibps × 1048576 × 8 / 0.9564)`(`DATA_PER_WIRE`, `:44-46`). 10 MiB/s → 87,710,247 bit/s다.
- `ensure`(`:110-115`)는 `start` → `limit` → `wait_ready` 순서다(결정 10).
- `limit`(`:117-148`)는 한도가 `None`이면 아무것도 하지 않는다(`:122-123`). 있으면 pid를 얻어(`_pid`, `:234-237`) 차례로 한다. **모든 단계가 "있으면 건너뛴다"이고, rate만 늘 다시 쓴다.**

  | 순서 | 줄 | 명령 (`nsenter -t <pid> -n` 뒤) | 이미 있으면 |
  | --- | --- | --- | --- |
  | 1 | `:134-136` | `ip link add ifb0 type ifb`, `ip link set ifb0 up` | add 건너뜀, up은 늘 |
  | 2 | `:137-139` | `tc qdisc add dev ifb0 root handle 1: htb default 1` | 건너뜀 (`qdisc replace`는 실패한다, S7 N8) |
  | 3 | `:140-141` | `tc class replace dev ifb0 parent 1: classid 1:1 htb rate R ceil R` | 늘 실행 (rate 맞추기) |
  | 4 | `:142-143` | `tc qdisc add dev ifb0 parent 1:1 handle 10: fq_codel` | 건너뜀 |
  | 5 | `:144-145` | `tc qdisc add dev eth0 clsact` | 건너뜀 |
  | 6 | `:146-148` | 방향마다 `tc filter add dev eth0 {ingress,egress} matchall action mirred egress redirect dev ifb0` | 건너뜀 (방향마다 필터 하나) |

- **`ifb0`과 HTB가 먼저, 필터가 나중이다.** 없는 장치로 redirect하면 트래픽이 모두 버려진다(S7 L6, 3.3절).
- 이미 있는지는 `tc -j … show`의 JSON으로 판단한다(`shown`, `:131-132`).
- `check_host`(`:95-99`)는 agent 시작 때 `modprobe ifb numifbs=0`을 한다(결정 14). HTB의 `quantum … is big` 경고는 stderr에 나오지만 종료 코드가 0이라 `Runner`가 성공으로 본다(S7 N7).

#### (9) agent: 시작 복구 — `flexvol.recover`, `flexvol.py:164-191`

- 볼륨마다 마운트·스냅샷·export를 맞추고 `instances.start`(`:186`) 바로 뒤 `instances.limit(vol.uuid, vol.qos)`(`:188`)다. 새 netns에는 tc가 없기 때문이다(S7 L5). 준비 대기는 모든 인스턴스를 띄운 뒤 한꺼번에 한다(`:190-191`).

#### (10) e2e 측정 도구 — `backend/tests/e2e/throughput_live.py`

- 허용 오차 `LOW, HIGH = 0.90, 1.01`(`:25`, 결정 15). `measure`(`:240-251`)는 한도 × 15 s 크기를 RUNS + 1회 재고 첫 회를 버린 뒤 중앙값을 낸다.
- `ifb_tx_bytes`(`:127-137`)는 호스트에서 `/proc/<pid>/net/dev`의 `ifb0` 줄을 읽는다. `nsenter`·`tc` 프로세스를 띄우지 않아 표본 시각의 흔들림이 작다(설계 §9-11).
- `Sampler`(`:140-182`)는 0.5초마다 표본을 찍는다. 시각은 **`time.monotonic()`**(`:162`)이다. 1회차 검증 때 이것이 `time.time()`이었고 AC-12가 실패했다(3.6절). 인스턴스가 다시 뜨면 새 pid를 따라가고, 같은 netns의 표본끼리만 1초 창을 만든다(`windows`, `:170-177`).
- 데이터 e2e의 창과 비교하는 시각도 모두 단조 시계다: AC-04 `t_start`·`t_ok`·`t_last`(`test_throughput_limit_data_live.py:128`, `:140`, `:145`), AC-07 `t_step`·`t_done`(`:297`, `:299`). `fast_poll`이 돌려주는 시각은 FR-06 되돌리기 e2e가 클라이언트 `date`와 비교하므로 벽시계 그대로다(`:139`의 주석). **2회차 검증 대상 코드에서 이 수정을 확인했다.**

### 핵심 설명 (면접에서 나올 것)

#### 3.1 Auto 공식과 반올림: 작은 볼륨은 0.062 MiB/s

- **계산.** 1 GiB Premium = 1/1024 TiB × 64 = 0.0625 MiB/s. Python `round(0.0625, 3)`은 0.062다. 0.0625는 2진수로 정확히 표현되는 "정확히 반"이라 half-even이 짝수 쪽(2)으로 간다. 101 GiB Premium의 6.3125도 같은 이유로 6.312다(녹화와 같다). Standard 1 GiB는 0.015625 → 0.016, Ultra 40 GiB는 5.0이다.
- **보이는 값 = 거는 값.** 반올림한 값이 응답, 풀 합, tc에 모두 쓰인다. 1 GiB Premium의 HTB rate는 0.062 기준인 543,804 bit/s다(검증 AC-01). ANF가 내부에서 6.3125를 거는지 6.312를 거는지는 [미확인]이다. 차이는 최대 0.0005 MiB/s다.
- **하한을 두지 않았다**(결정 2). 0.062 MiB/s는 `ANF_MIN_VOLUME_SIZE_GIB=1`로만 만들 수 있는 검증 전용 크기의 결과다. 실서비스 최저는 Standard 50 GiB = 0.781이다 [추론]. 검증 볼륨을 위해 하한을 두면 응답과 동작이 ANF와 달라진다. 그 대신 이 낮은 한도에서 NFS가 어떻게 되는지 쟀다(3.7절).
- **Auto 풀에는 예산 검사를 하지 않는다**(설계 §9-1). 할당량 규칙(할당량 합 ≤ 풀 크기)이 같은 것을 지키기 때문이다. 게다가 **반올림한 Auto 한도의 합은 총 처리량을 조금 넘을 수 있다.** Premium 4 TiB 풀에 3 GiB 볼륨 341개를 두면 0.1875 → 0.188이고 0.188 × 341 = 64.108 > 64다. 이 합을 Auto → Manual 전환으로 옮겨 받은 Manual 풀도 생길 수 있어서, 갱신은 한도를 올릴 때만 예산을 본다.
- **ANF와 같은 점**: 공식, 풀 크기와 무관, 셋째 자리 표시, 읽기 전용 `actualThroughputMibps`. **다른 점**: 반올림 방식은 클론의 선택(half-even)이다. 4,500을 넘는 공식 값도 그대로 보이고 건다(ANF 표시는 [미확인]). 할당량 변경으로 한도를 바꾸는 길은 아직 없다(FR-16).

#### 3.2 tc 구조와 읽기·쓰기 합산

- **방향.** NFS WRITE의 데이터는 클라이언트 → 서버라 인스턴스 `eth0`의 ingress로 들어오고, READ의 데이터는 서버 → 클라이언트라 egress로 나간다. 두 방향을 같은 `ifb0`의 같은 HTB 클래스 1:1로 보내므로 **버킷이 하나**다. ANF의 "읽기와 쓰기의 합"과 같은 계약이다 [문서].
- **측정.** 10 MiB/s 볼륨에서 읽기 job과 쓰기 job을 함께 돌리면 읽기 5.05 + 쓰기 4.72 = 9.78 MiB/s(97.8%)였다. 20 MiB/s에서는 11.0 + 8.2 = 19.21(96.1%)이었다. 합이 혼자 쟀을 때(9.72~9.79, 19.12~19.43)와 같다 [클론 측정, AC-03].
- **IFB가 필요한 이유.** HTB 같은 대기열 qdisc는 장치에서 **나가는** 패킷에 걸린다(Linux tc의 일반 성질이고, 스파이크 문서에 따로 적힌 것은 아니다). 들어오는 트래픽을 같은 HTB에 태우려면 `clsact` ingress 훅에서 IFB로 redirect해야 한다. 나가는 쪽도 같은 IFB로 보내야 한 클래스로 묶인다.
- **IFB가 패킷을 돌려보내는 곳.** 들어오는 패킷은 HTB를 지난 뒤 `eth0` 입력으로 돌아간다. 되돌리기 창의 `iptables INPUT -i eth0 DROP`이 tc 뒤에서도 그대로 효과가 있었다(S7 M3: 5 s 동안 0.0, 풀자 바로 9.44~9.58). 다만 이 경로 해석은 결과에서 읽은 것이다 [추론, S7].
- **fq_codel leaf.** 흐름(5-tuple)마다 대기열을 나눠, 큰 흐름 뒤에 다른 연결을 줄 세우지 않는다 [추론, S7]. 3.7절의 "다른 연결은 빨랐다"가 그 결과다.
- **D-12에서 이미 버린 것** (스파이크 S2, ADR §7.3):
  - **T1. 호스트 knfsd 하나 + 볼륨마다 IP + IP별 tc**: NFSv3만 통과했다. NFSv4.1 클라이언트는 같은 서버 신원(knfsd 하나)의 IP들을 연결 하나로 합쳐서 볼륨을 구분하지 못했다(`notrunkdiscovery`로도 안 됨). 그래서 볼륨마다 knfsd 인스턴스와 netns를 둔다.
  - **T2. cgroup v2 `io.max`**: WSL 배포판은 자기 PID 네임스페이스에서 돌아 knfsd 커널 스레드가 보이지 않았다. 10 MiB/s를 걸었는데 241 MiB/s였다.
  - **T3. 볼륨마다 NFS-Ganesha + `io.max`**: `io.max`는 읽기와 쓰기를 따로 센다(10 + 10 = 20 MiB/s). 캐시에 맞은 읽기는 제한하지 못한다(4,310 MiB/s). 둘 다 ANF 계약과 어긋난다.

#### 3.3 호스트 veth 방식을 버린 이유

ADR §7.3은 처음에 "인스턴스의 호스트 쪽 veth에 clsact"(S2 T1n)라고 적었다. S7에서 실제 agent 인스턴스에 두 위치를 모두 걸어 봤다.

- **정확도와 기능은 같았다.** 10 MiB/s, 보정 없음, NFSv3에서 호스트 쪽은 쓰기 9.475·읽기 9.401, netns 쪽은 9.436·9.402였다. 데이터/wire 비율도 0.9534로 같았다(S7 Q2·M1). 실시간 변경(Q3·M2)과 되돌리기 창과의 공존(L3·M3·M6)도 같았다.
- **차이는 수명과 이름이었다.** 호스트 쪽의 문제는 이랬다.
  - Docker가 시작할 때마다 veth를 새로 만들어 이름(`veth` + 무작위 7자리)과 ifindex가 바뀐다. 걸 때마다 pid → `nsenter … ip -j link show eth0`의 `link_index` → 호스트 `ip -j link`로 다시 찾아야 한다(V1·V4).
  - 인터페이스 이름은 15자까지라 IFB 이름에 uuid를 쓸 수 없다. altname은 `ip`로는 되지만 iproute2 6.1의 `tc`가 이름을 15자로 잘라 `Cannot find device`였다(N2·N3).
  - IFB가 인스턴스보다 오래 산다. 볼륨을 지운 뒤에도 IFB와 HTB 설정이 남았다(L7). 볼륨 IP는 지운 볼륨의 것을 새 볼륨이 다시 받으므로(S7에서 D가 C의 .131을 받음), IP로 IFB 이름을 지으면 새 볼륨이 남은 HTB 값을 물려받을 수 있다.
  - 남은 IFB에 다시 걸면 HTB 루트의 `tc qdisc replace`가 `Change operation not supported`로 실패했다(N8).
  - **지우는 순서를 틀리면 트래픽이 끊긴다.** 필터가 가리키는 채로 IFB를 먼저 지우자 dmesg에 `tc mirred: target device is gone`이 나오고 veth 카운터가 약 12 s 동안 0.0 MiB/s였다(t=8~20 s). clsact를 지운 3 s 뒤에야 제한 없이 흘렀다(L6, fio 오류 0, clat 최대 15.5 s).
- **netns 방식**은 모든 인스턴스가 이름 `ifb0`을 쓴다(netns마다 따로, N4). veth를 찾지 않고 "pid → `nsenter`"뿐이다. 되돌리기 창의 iptables(`_iptables`, `nfs_instance.py:229-232`)와 같은 경로다. 인스턴스를 멈추거나 지우면 함께 사라져 정리할 것이 없다(M4·M7). 검증 AC-07(f)도 볼륨 삭제 뒤 netns가 `lsns`에서 사라졌고 호스트 IFB는 앞뒤 모두 0개였다.
- **잃은 것**: 카운터를 호스트에서 IFB 이름만으로 읽을 수 없고, 인스턴스가 멈춘 동안에는 읽을 것이 없다. 카운터는 `/proc/<pid>/net/dev`로 대신 읽는다(3.6절, 3.10절).
- **진입점에서 거는 안도 버렸다.** 이미지에 iproute2를 넣고 한도를 환경 변수로 넘겨야 한다. 실시간 변경은 여전히 밖에서 해야 해서 tc를 다루는 곳이 둘이 된다.
- 리더는 이것을 사용자에게 묻는 결정이 아니라 D-12의 다듬기로 봤다. D-12의 결정문("인스턴스 veth를 tc HTB로, 읽기·쓰기 합산")은 그대로다. netns 안의 `eth0`도 같은 veth 쌍의 한쪽 끝이기 때문이다.

#### 3.4 시작 경로마다 다시 거는 이유

- **tc는 netns와 함께 사라진다.** 인스턴스를 `docker start`·`docker run`할 때마다 새 netns와 새 veth가 생긴다. 다시 걸기 전에는 제한이 없다. S7에서 10 MiB/s 볼륨이 다시 걸기 전에 이렇게 흘렀다.

  | 상황 | 다시 걸기 전 | 근거 |
  | --- | --- | --- |
  | `docker stop` → `docker start` | 48.14 MiB/s | S7 L1 |
  | `docker rm` → agent `docker run` | 144.93 MiB/s | S7 L2 |
  | 인스턴스 멈춤 → agent 시작(`recover()`의 `docker start`) | 78.67 MiB/s | S7 L5 |
  | netns 방식에서 `docker start` | 185.9 MiB/s | S7 M5 |

- **그래서 인스턴스를 띄우는 모든 경로가 `start` → 한도 걸기 → `wait_ready`다**(결정 10). 생성·같은 요청의 재전송·되돌리기 뒤 보장·새 볼륨 복원은 `NfsInstances.ensure`(`nfs_instance.py:110-115`), 시작 복구는 `recover`(`flexvol.py:186-188`)다.
- **왜 준비 전에 걸 수 있나.** `docker run -d`·`docker start`는 컨테이너가 시작된 뒤 돌아오고, knfsd는 그 뒤에 진입점이 띄운다. 그래서 knfsd가 서비스하기 전에 제한이 걸린다. 진입점이 NFSv4 유예 기간(grace 45 s)을 기다리는 경우에도 그 전이다. 검증 AC-07(b)에서 새 pid의 첫 표본에는 `ifb0`이 없었고, 0.25 s 뒤 표본부터 있었다. 그사이 `eth0`로 흐른 바이트는 없었고 I/O는 7.3 s 뒤에 다시 흘렀다 [클론 측정]. 즉 제한 없는 창이 없었다.
- **agent만 재시작하면 tc가 남는다**(S7 L4: 9.40 MiB/s). `recover()`가 같은 값을 다시 맞출 뿐이다. 검증 AC-07(a)에서 I/O 멈춤 없이 98.2%였다.
- **되돌리기는 인스턴스를 그대로 둔다**(S7 L3·M6). 그래서 tc도 그대로이고, 2.5 s 남짓 멈춘 뒤 한도로 돌아왔다(AC-07(d)).
- **멱등이어야 하는 이유.** `start`는 인스턴스가 이미 돌면 아무것도 하지 않는다. 그 뒤의 `limit`는 tc가 이미 있는 인스턴스에서도 불린다. 그래서 "있으면 건너뛰고 rate만 `class replace`"로 썼다(3절 (8)). 통합 테스트 `test_limit_lives_in_the_instance_netns_and_is_idempotent`(`test_flexvol_linux.py:639`)가 두 번 걸어도 필터가 방향마다 하나인지 본다.
- **한도는 왜 LVM 태그인가**(결정 11). `recover()`가 다시 걸려면 agent가 한도를 알아야 한다. anf-api가 다시 보내게 하면 anf-api는 agent나 WSL이 재시작한 것을 모르므로 그사이 제한이 없다. agent는 DB 없이 LVM 상태만 진실로 쓰므로 다른 볼륨 속성과 같은 자리에 둔다.

#### 3.5 헤더 보정: ÷0.9564

- **문제.** HTB는 헤더를 포함한 wire 바이트를 센다. 클라이언트(fio)가 재는 것은 데이터 바이트다. 보정 없이 rate = 한도로 걸면 데이터는 한도의 **92.1~94.7%**였다(S7 Q2: 10 MiB/s 94.0~94.7%, 30 MiB/s 92.1~93.4%).
- **0.9564의 출처** (S7 Q7). `anf-vnet` MTU 1500에 TCP 타임스탬프를 쓰면 MSS가 1448이다. 데이터 세그먼트 하나의 L2 길이는 1448 + 32(TCP) + 20(IP) + 14(Ethernet) = 1514 B다. 그래서 데이터/wire의 **이론 상한이 1448/1514 = 0.9564**다. 반대 방향의 ACK와 RPC 헤더도 같은 클래스에서 세므로 실제 비율은 그보다 낮다(측정 0.9532~0.9551). 그래서 rate = 한도 ÷ 0.9564로 걸면 **어떤 I/O 모양에서도 데이터가 한도를 넘지 않는다** [추론, S7].
- **측정값 0.9534를 쓰지 않은 이유.** 0.9534로 보정하자 98.0~99.3%였고 모든 회가 한도 이하였다(S7 Q7). 하지만 30 MiB/s 읽기의 데이터/wire가 0.9551이었다. HTB가 rate를 꽉 채우면 데이터가 한도의 100.2%가 될 수 있다 [추론, 관찰되지는 않음]. 0.9564는 그보다 0.3% 덜 보정해 상한을 지킨다.
- **결과.** 검증 1회차의 판정 중앙값은 한도의 **95.6~99.3%**였다(가장 낮은 것은 AC-02의 20 MiB/s v3 읽기, 가장 높은 것은 AC-05의 함께 읽기). 단계 뒤 1초 창의 중앙값은 98.2~98.8%였다. 판정 값 중 가장 높은 것은 AC-04의 1초 창 100.8%로 허용 오차(101%) 안이었다. 데이터/HTB `Sent`는 0.951~0.955로 이론 상한 밑이었다 [클론 측정].
- **남은 1~3%.** fio가 잰 구간의 시작과 끝(램프)에서 HTB가 rate보다 덜 내보낸 몫이다 [추론, S7 Q2].
- **조건.** MTU가 바뀌면 이 값도 바뀐다. `bs=4k` 순차 쓰기는 대역폭이 아니라 지연이 한계라 10 MiB/s 한도에서 1.476 MiB/s였다. 4 KiB 임의 읽기는 9.048 MiB/s(2,316 IOPS, 90.5%)였다(S7 Q7, 각 1회). 클론은 IOPS를 따로 제한하지 않는다.

#### 3.6 측정과 시계: 단조 시계로 재는 이유

**판정 시계는 게스트 단조 시계다**(결정 15, ADR §7.3). HTB(커널 시간)와 fio(`clock_gettime`)가 같은 게스트 시계를 쓰므로, 게스트 시계로 재면 "설정과 데이터의 관계"가 시계 오차와 무관하게 보인다 [검증자 판단].

- **WSL 게스트 시계는 호스트보다 약 2% 빨랐다** [클론 측정, 검증 1회차]. Windows Stopwatch 대비 게스트 `time.monotonic()`의 비율은 이랬다. 부팅 직후 300 s는 1.0023, AC-05~09 측정 중 400 s는 1.0205, AC-12 회귀 중 4,463 s는 누적 1.0239(10분 단위 1.0223 → 1.0255로 조금씩 커짐)였다. 처리량 측정(07:21~08:11)은 모두 +1.8~2.2% 구간에 있었다.
- **영향.** Windows 시간으로 환산하면 처리량이 약 2% 높다. AC-04 1초 창 최대 100.8%는 약 102.8%가 된다. 즉 **호스트 시간 기준이면 위쪽 1% 여유를 넘는 값이 여럿 생긴다.** 리더 결정(자동 채택): 판정 시계는 게스트 단조 시계로 두고, 호스트 비율은 검증마다 재서 기록한다. 이 비율은 부팅마다 달랐다. S2에서 0.908, S7에서 0.9948~1.0009였다.
- **벽시계는 약 32 s마다 뒤로 건너뛰었다.** 게스트 실시간(`time.time()`)은 빨리 가는 시계를 Windows 시각에 맞추려고 주기적으로 뒤로 물러났다. 07:45쯤에는 0.64 s, 09:35에는 0.85 s씩이었다. 0.05초마다 `time.time()`과 `time.monotonic()`을 비교하자 계단 −0.846, −0.875, −0.854 s가 32.3 s, 32.2 s 간격으로 보였다.
- **1회차 AC-12 실패가 이것이었다.** FR-08 데이터 e2e의 `Sampler`가 표본 시각을 `time.time()`으로 찍었다. 건너뜀이 들어간 1초 창은 계산된 길이가 실제보다 짧아, 10 MiB/s 볼륨에서 16.6~17.7 MiB/s(약 1.7배)로 읽혔다. AC-07이 이것을 "한도를 넘은 창"으로 보고 실패했다. 제품 결함이 아니라는 근거는 셋이었다.
  1. 넘은 창이 0.5 s 간격의 두 창씩 짝을 이루고, 짝 사이가 31.3~31.7 s로 계단 주기와 같았다.
  2. 인스턴스가 바뀌지 않은 단계(agent만 재시작, 되돌리기)에서도 나왔다.
  3. 같은 종류의 단계를 단조 시계로 잰 검증자 드라이버에서는 넘은 창이 0개였고 HTB `Sent` 창도 한도 밑이었다. 같은 기록의 판정 창 중앙값은 9.94~9.96으로 허용 오차 안이었다.
- **수정**(`3328486`, 설계 §9-14): 표본 시각과 창과 비교하는 시각을 모두 `time.monotonic()`으로 바꿨다(3절 (10)). 제품 코드는 바뀌지 않았다. 검증자 드라이버는 이미 AC-04에서 1.55배 창을 보고 ac06부터 단조 시계로 바꿔 둔 상태였다.
- **측정에서 배운 것 하나 더: fio 초당 로그는 멈춤을 숨긴다.** fio의 `--write_bw_log`는 완료가 없는 초를 건너뛴다. S7은 처음에 L6(IFB를 먼저 지움)을 fio 로그로 보고 "제한 없이 흘렀다"고 잘못 읽었다. 실제로는 12 s 동안 0이었다. 그래서 멈춤과 바뀐 한도는 커널 카운터의 1초 창으로 판정한다(결정 15).

#### 3.7 낮은 한도에서의 NFS: 같은 연결은 느려지고, 다른 연결은 fq_codel이 지킨다

**S7 Q4** (0.0625 MiB/s, 1 MiB 직접 쓰기 × iodepth 16 = 대기열 16 MiB, 180 s, v3·v4.1, hard 마운트)

| 관찰 | 3.125 MiB/s | 1 MiB/s | 0.0625 MiB/s |
| --- | --- | --- | --- |
| `ls` / 4 KiB 쓰기, **같은 마운트**(큰 쓰기와 같은 TCP 연결) | 0.86~1.24 / 0.88~2.10 s | 5.65~8.81 / 8.00~8.74 s | **47~76 / 68~86 s** |
| `ls` / 4 KiB 쓰기, 다른 연결 | 0.01~0.31 / 0.03~1.19 s | 0.00~0.68 / 0.03~0.80 s | 0.03~0.57 / 0.17~1.80 s |
| 큰 쓰기 완료 지연 평균 / 최대 | 5.4 / 10.1 s | 16.7 / 31.4 s | **266 / 448 s** |
| WRITE timeouts (v4.1, v3) | 0, 0 | 0, 0 | **16, 19** |
| dmesg | 없음 | 없음 | `server … not responding, still trying` ↔ `OK` 39줄 |

- **오류는 없었다.** 재전송 0, 다시 연결 0, fio 오류 0이었다. hard 마운트라 시간 초과가 앱에 오류로 가지 않았다. soft 마운트라면 EIO가 됐을 것이다 [추론, 시험 안 함].
- **v4.1 lease도 굶지 않았다.** 3분 넘게 클라이언트는 `confirmed`였고, 서버가 본 마지막 갱신은 최대 16 s 전이었다(lease 30 s).
- **같은 연결이 느린 이유.** 1 MiB WRITE 하나가 0.0625 MiB/s에서 연결을 약 16 s 차지한다. 그사이 다른 RPC가 기다린다 [추론, S7]. 이 구성(wsize 1 MiB, lease 30 s)에서는 한도가 약 0.035 MiB/s 밑이면 갱신 간격이 lease를 넘을 수 있다 [추론, 시험 안 함].
- **다른 연결이 빠른 이유.** leaf `fq_codel`이 흐름마다 대기열을 나눠 큰 흐름 뒤에 줄 세우지 않기 때문이다 [추론, S7]. `pfifo`면 GSO 패킷 1,000개가 한 줄로 쌓여 이 이점이 없다 [추론, 낮은 한도에서 시험 안 함]. 이것이 leaf로 `fq_codel`을 고른 이유다(결정 13).
- **검증 AC-06은 다른 조건이었다.** 64 KiB 직접 쓰기 × iodepth 1(대기열 64 KiB), 30 s였다(설계 §9-11: 1 MiB × 16이면 대기열을 비우는 데만 4분이 넘는다). 이 조건에서 같은 연결의 `ls`는 최대 1.55 s, 4 KiB `dd` + fsync는 최대 2.18 s였다. 다른 연결은 최대 0.36 s였다. dmesg에 NFS 줄이 없었고 timeouts는 0이었다. 큰 쓰기는 0.0598·0.0597 MiB/s로 상한 0.0626 아래(96.5%·96.3%)였다 [클론 측정].
- **정리.** 같은 연결의 메타데이터 지연은 대략 "그 연결의 대기열이 비는 시간"에 따라 늘었다. 대기열 16 MiB에서는 1분을 넘었고, 64 KiB에서는 2.2 s였다. 실서비스 최저(0.78 MiB/s)는 S7의 1 MiB/s 결과(같은 연결 `ls` 6~9 s, 시간 초과 없음)와 비슷한 범위로 본다 [추론].

#### 3.8 Manual 규칙, 예산, Auto → Manual 전환, 그리고 "1 미만 값"

- **클론 규칙** (ANF 동작이 [미확인]이라 정했다)
  - Manual 풀 볼륨 생성에 값이 없으면 `400 InvalidRequestContent`다(결정 3).
  - Auto 풀 볼륨에 값이 있으면 `400 BadRequest`다(결정 4).
  - 예산 초과는 동기 `400 BadRequest`에 ANF 문서 문구다(결정 7).
  - Manual 풀 축소로 예산이 배정 합보다 작아지면 `400`이다.
  - 전환 때는 직전 Auto 한도를 `throughputMibps`로 옮긴다(결정 6).
- **전환이 만든 문제** (설계 §9-5). Auto 한도는 1 MiB/s보다 작을 수 있다. 기본 최소 크기 50 GiB의 Standard 볼륨도 0.781이다. 전환 뒤 그 볼륨의 GET 본문을 그대로 PUT하면 범위(1~4,500) 검사에 걸려 `400`이었다. ARM 클라이언트(Terraform, Bicep, `az` 재배포)는 GET 본문을 그대로 다시 보낸다. 그러면 전환한 풀의 볼륨을 재배포할 수 없다.
- **고친 방식** (리더 자동 채택, §9-13): 갱신에서 저장된 값과 셋째 자리까지 같으면 "바꾸지 않음"이다. 범위를 보지 않고, 예산도 더 쓰지 않는다(올릴 때만 예산 검사). 새 볼륨 생성은 여전히 1~4,500이다. 셋째 자리 아래만 다른 값(0.125에 0.1254)은 무시되고 저장 값이 남는다.
  - 버린 대안: 지금대로 `400`(위 이유). 전환 때 1로 올림(전환이 한도를 말없이 바꾼다. 결정 6 "직전 한도를 채운다"와 어긋난다).
  - 부작용: 오류 우선순위가 바뀌었다. 범위 오류가 본문 단계에서 갱신 흐름 안으로 옮겨져, 없는 볼륨에 `throughputMibps: 0.5`를 PATCH하면 전에는 `400`, 지금은 `404`다.
  - 시험: 단위 `test_resending_a_stored_limit_below_1_skips_the_range`(`test_volumes.py:605`), `test_resending_a_stored_limit_passes_an_overcommitted_budget`(`:627`), 계약 `test_switched_volume_below_1_takes_its_get_body_back`(`test_volumes_api.py:278`).
- **주입 실패에서만 생기는 상태** (§9-4, 리더 자동 채택: 그대로 둔다). 전환 값은 풀 PATCH 요청의 트랜잭션에서 쓴다. 풀 PATCH 작업이 실패하면 워커가 풀만 Auto로 되돌리고 볼륨 행의 `throughputMibps`는 남는다. 풀 PATCH는 agent를 부르지 않아서 실패는 결함 주입에서만 생긴다. 재시작 뒤에는 워커가 작업을 다시 돌려 성공시킨다. 한도 값도 Auto 공식과 같다.

#### 3.9 한도는 상한이고 격리가 아니다

- **관찰** (검증 1회차 AC-05, 쓰기 표본, 판정에 쓰지 않음). 같은 클라이언트가 10 MiB/s 볼륨 A와 4,500 MiB/s 볼륨 B를 NFSv4.1로 마운트했다. B가 2 GiB를 디스크에 쓰는 동안 A의 15 s 쓰기는 이랬다.

  | 표본 | A 쓰기 | B 쓰기 | A의 `ifb0` 대기열 |
  | --- | --- | --- | --- |
  | A만 | 9.866 (98.7%) | — | — |
  | 함께 1 | **8.563 (85.6%)** | 63.44 | (안 봄) |
  | 함께 2 | **7.062 (70.6%)** | 43.74 | 18회 중 0 B 7회, 35~71 KB 11회 |
  | 함께 3 | **7.336 (73.4%)** | 75.33 | 17회 중 0 B 8회, 36~139 KB 9회 |

- **제한기가 누른 것이 아니다.** A의 HTB 클래스는 rate = ceil이라 대기열에 패킷이 있으면 한도로 내보낸다. 대기열이 빈 표본이 40~47%였으니 **A로 들어오는 양 자체가 한도보다 적었다.** 찼을 때의 대기열도 35~139 KB(10 MiB/s에서 3~14 ms)로, 1 MiB RPC 하나를 고르게 내보내는 정도였다. 두 볼륨이 같은 aggregate(희소 파일 `aggr0.img` 하나, 그 아래 WSL 가상 디스크)를 쓰므로 서버 디스크 경합으로 본다 [검증자 판단].
- **같은 현상의 다른 관찰.**
  - S7 Q2: 30 MiB/s 쓰기에서 가끔 17~22 MiB/s인 회가 나왔다. 그동안 HTB backlog가 대부분 0이었고 `/proc/pressure/io`의 `some avg10`이 3.9 → 46%로 올랐다. NFS·tc 없이 같은 ext4에 `--rate=30m`으로 쓰면 8회 모두 30.06 MiB/s였다. 서버 쪽 쓰기 경로가 몇 초씩 막힌 것이다 [추정, S7].
  - S7 Q6: A(10)와 C(30)가 함께 쓴 6회 중 2회는 둘 다 낮았다(A 7.986·7.218, C 21.03·14.10) [추정, S7].
  - 검증 AC-04: 30 MiB/s 구간의 쓰기가 약 12 MiB/s로 떨어진 구간이 있었다. HTB `Sent` 창도 같은 값이라 제한기 원인이 아니었다.
- **읽기는 영향이 없었다.** B가 서버 캐시에서 2,041.9 MiB/s(A의 205.7배)로 읽는 동안 A는 9.925(99.25%)였다. A만 읽을 때(9.714)와의 차이는 0.211로 허용 띠(1.1) 안이었다.
- **판정 변경** (리더 자동 채택, 1회차 뒤): AC-05의 "제한이 없는 볼륨과의 차이"와 "독립성"은 **읽기로** 판정한다. 쓰기 경합은 이 절에 적는다. PRD 수락 기준("제한이 없는 볼륨과의 차이가 측정으로 드러난다")은 읽기로 충족한다.
- **실제 ANF·ONTAP은 이것을 무엇으로 다루나.**
  - ONTAP QoS 정책에는 하한(`min_throughput_mbps`·`min_throughput_iops`)이 있다. 원문은 "These floors are not guaranteed on non-AFF platforms or when FabricPool tiering policies are set."까지만 말한다 [ONTAP]. **이웃 때문에 한도보다 덜 받는 문제를 다루는 ONTAP 도구는 이 하한일 것이다** [추론]. 경합 때 하한이 어떻게 지켜지는지는 브리프에 없다 [미확인].
  - adaptive QoS에는 `expected_iops`·`peak_iops`·`absolute_min_iops` 필드가 있다 [ONTAP]. 이 값들이 경합에서 무엇을 보장하는지는 브리프에 없다 [미확인].
  - ANF 볼륨 API에는 하한 속성이 없다 [스펙]. ANF 문서가 말하는 것은 자기 한도에 닿았을 때의 지연뿐이다 [문서]. **ANF가 이웃 경합을 어떻게 다루는지는 확인하지 못했다** [미확인].
- **클론의 한계.** 클론에는 하한이 없고, 만들 길도 지금 데이터 플레인에는 없다. 블록 계층 제어(cgroup `io.max`)는 WSL에서 knfsd 스레드가 보이지 않아 효과가 없었다(S2 T2). 그래서 하한을 만들려면 다른 데이터 플레인 환경이 필요하다 [추론]. 면접에서는 "클론의 한도는 상한이다. 같은 aggregate 이웃의 디스크 경합은 막지 않는다"라고 말한다.

#### 3.10 카운터 두 개: FR-12 메트릭이 고를 값

설계 §6.3은 처음에 "`ifb0` 송신 바이트와 HTB `Sent` 바이트는 같은 값"이라고 썼다. **틀렸다**(설계 §9-12).

| 카운터 | 읽는 법 | 세는 것 | 데이터 대비 |
| --- | --- | --- | --- |
| `ifb0` 송신 바이트 | 호스트에서 `/proc/<pid>/net/dev`의 `ifb0` 줄 (프로세스를 띄우지 않음) | skb 길이. GSO 묶음마다 헤더를 한 번만 센다 | 데이터에 가깝다. 구현자 e2e는 같은 시험 fio 값보다 0.5% 안팎 크다고 기록했다. 검증자 측정은 데이터/`ifb0` 송신 0.989~0.993(0.7~1.1% 큼)이었다 |
| HTB 클래스 `Sent` | `nsenter … tc -s class show dev ifb0` (텍스트. iproute2 6.1은 HTB 클래스를 JSON으로 내지 않음, S7 N6) | 묶음을 세그먼트로 나눠 세그먼트마다 헤더를 더한 wire 바이트(`qdisc_pkt_len`). **rate가 이 값에 걸린다** | 데이터/HTB `Sent` 0.951~0.955 |

- 같은 인스턴스에서 `ifb0` 송신 3,024,712,382 B, HTB `Sent` 3,153,075,794 B로 **HTB가 4.24% 컸다**(10 MiB/s v4.1). 20 MiB/s v3에서는 4.35%였다.
- **어떻게 드러났나** (§9-11). e2e는 처음에 `ifb0` 창에 0.9564를 곱해 데이터로 환산했다. 그러자 창이 fio 값보다 4% 낮았다(AC-07 창 중앙값 9.55 대 fio 9.93). 그래서 환산을 빼고 두 카운터를 비교했다.
- **FR-12에 주는 선택지.** "볼륨 처리량"(ANF의 Read·Write 지표에 대응)처럼 데이터에 가까운 값은 `ifb0` 송신이다. "한도에 닿았나"(ANF의 "Throughput limit reached")를 보려면 rate가 걸리는 HTB `Sent`와 rate를 비교해야 한다. 어느 값을 메트릭으로 할지는 FR-12가 정한다. 제품 코드는 지금 어느 카운터도 읽지 않는다. ADR §8은 같은 내용으로 고쳤다.
- 두 카운터 모두 netns 안에 있어 인스턴스 pid가 필요하고, 인스턴스가 멈춘 동안에는 읽을 것이 없다(3.3절에서 잃은 것).

### 설계 결정

#### 이 기능 전에 정해진 것 (D-12)

| 결정 | 버린 대안 | 이유 (S2) |
| --- | --- | --- |
| T1n: 볼륨마다 knfsd 인스턴스(자기 netns)와 IP, 그 veth의 양방향을 IFB 하나로 보내 HTB 클래스 하나 | T1 호스트 knfsd 하나 + IP별 tc / T2 cgroup `io.max` / T3 Ganesha + `io.max` | 3.2절. T1은 v4.1이 연결을 합쳐 볼륨을 구분하지 못함. T2는 10 MiB/s 설정에 241 MiB/s. T3은 읽기·쓰기 따로(10 + 10 = 20)이고 캐시 읽기 4,310 MiB/s |

#### 결정 1~19 (모두 자동 채택)

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | 범위는 Auto와 Manual 둘 다. "제한을 바꾸면 잰 값도 바뀐다"는 Manual `throughputMibps`의 PATCH·재PUT으로 보인다. 할당량 변경으로 Auto 한도 바꾸기는 FR-16 | 할당량 PATCH를 당겨 옴 / Auto만 | 할당량 PATCH는 ext4 온라인 확장, 축소 거절, 풀 용량 재검사를 함께 끌고 와 범위가 두 배가 된다. Auto만은 PRD가 둘 다 적었으니 범위를 줄이는 것이다 |
| 2 | Auto 한도는 공식 그대로, 클론 하한 없음. 셋째 자리 half-even(Python `round`). 응답 값 = tc 값 | 클론 하한 / 버림(truncate) | 하한은 ANF와 응답·동작이 달라진다. 검증 볼륨을 위해 제품 규칙을 바꾸는 것이다. S7 Q4에서 0.0625 MiB/s로도 마운트·읽기·쓰기·lease가 오류 없었다. 버림은 녹화 값 하나(6.312)로 half-even과 구분되지 않고, Python 기본이 설명하기 쉽다 |
| 3 | Manual 풀 볼륨은 `throughputMibps` 필수(없거나 `null`이면 `400 InvalidRequestContent`). 숫자(불리언 아님), 1~4,500, 소수 허용, 받은 값 그대로 저장 | Auto 공식 값으로 채움 / 남은 예산 전부 | 공식 값 채우기는 Manual을 고른 이유(용량과 처리량을 따로 정함)와 맞지 않고 숨은 값이 예산을 쓴다. 남은 예산 전부는 다음 볼륨이 바로 예산 초과가 된다. 실서비스 기본값은 [미확인] |
| 4 | Auto 풀 볼륨에 값(null 아님)이 오면 `400 BadRequest`. Auto 볼륨 응답에는 `throughputMibps`가 없음 | 무시 / .NET 녹화처럼 `0.0` 표시 | 무시하면 사용자는 한도가 바뀐 줄 안다. `0.0`은 파이썬 녹화와 다르고, 0을 다시 보내는 왕복 요청을 따로 다뤄야 한다 |
| 5 | Manual 볼륨 `actualThroughputMibps` = `throughputMibps`. 풀 `utilizedThroughputMibps` = 모든 볼륨 행(상태 무관)의 한도 합 | 스펙 설명대로 Manual 볼륨의 `actualThroughputMibps`를 비움 | 녹화의 볼륨 리소스 응답이 6.0/6.0이다 |
| 6 | Auto → Manual은 같은 풀 PATCH 트랜잭션에서 볼륨 행에 직전 `actualThroughputMibps`를 씀. 데이터 플레인 작업 없음. 4,500 넘는 값은 자르지 않음. 자식 볼륨에 진행 중 작업이 있으면 `409` | 4,500으로 자름 / 값을 비워 둠 / 진행 중 작업 무시 | 자르면 한도가 바뀌어 풀 PATCH가 agent 작업을 가져야 하는데, 해당 볼륨은 검증 범위 밖의 큰 볼륨뿐이다. 비우면 결정 3이 깨진다. 진행 중 작업이 실패해 되돌리면 채운 값이 사라진다. 검증: 전환 0.04 s, 같은 pid·rate, 전후 99.1% |
| 7 | 예산 검사는 동기 `400 BadRequest`, 문구는 문서의 "Requested throughput not available"로 시작. 셋째 자리 비교. Manual 풀 축소로 총 처리량 < 배정 합이면 `400` | 비동기 작업 `Failed` / 새 오류 코드(`PoolThroughputExceeded` 등) / 축소 허용 | 비동기면 사용자가 폴링해야 안다. 새 코드는 근거 없이 이름을 짓는다. 축소를 허용하면 배정 합 > 예산인 상태가 생긴다. 풀 설계 결정 7과 같은 방식. 검증: 남은 예산 정확히 28 → 201, 28.001 → 400, 28.0005 → 201 |
| 8 | agent API = 볼륨 POST의 인라인 `qos.policy.max_throughput_mbps`(MiB/s, 소수). 없으면 제한 없음. job 키에 한도. GET 레코드에 값 | `/api/storage/qos/policies` 정책 객체 + `qos.policy.uuid` / ONTAP처럼 변경은 볼륨 PATCH로 따로 / 클론 확장 필드 `max_throughput_mibps` | 정책 객체는 볼륨마다 한도 하나인데 객체 수명(만들기·지우기·고아 정리)이 하나 더 생긴다. ANF Manual은 공유 정책이 아니다. 따로 PATCH하면 재시작 뒤 이어 하기에 호출 두 개와 순서 규칙이 필요하다. 확장 필드는 ONTAP 이름을 버린다 |
| 9 | tc는 인스턴스 netns 안: `eth0` clsact → `ifb0` → HTB 1:1 → fq_codel. 호스트 `ip`·`tc`를 `nsenter -t <pid> -n`으로 | 호스트 쪽 veth + 호스트 IFB(ADR §7.3의 S2 방식) / 진입점에서 걸기 | 3.3절. 호스트 쪽은 veth 매번 찾기, IFB 15자, 삭제 뒤 남는 IFB, 순서를 틀리면 12 s 끊김, 남은 IFB에 `qdisc replace` 실패. 정확도는 같았다(9.436 대 9.475) |
| 10 | 인스턴스를 띄우는 모든 경로에서 `start` → 한도 걸기 → `wait_ready`. 걸기는 멱등 | 준비가 끝난 뒤 걸기 / anf-api가 다시 걸기 요청 | 3.4절. 준비 뒤 걸면 그사이 48~186 MiB/s로 제한 없이 흘렀다. anf-api는 agent·WSL 재시작을 모른다 |
| 11 | 한도는 볼륨 LV 태그 `anf_qos`. POST에 `qos`가 없으면 태그를 바꾸지 않음. 이 FR 전에 만든 볼륨은 다음 보장 전까지 제한 없음(이전 작업 없음) | anf-api가 다시 보냄 / 별도 파일 | 재시작 사이에 제한 없는 창이 생긴다. agent는 DB 없이 LVM 상태만 진실로 쓴다. 개발 기기에 그런 볼륨이 없었다 |
| 12 | HTB rate = 한도 ÷ 0.9564, bit/s 정수(반올림) | 보정 없음 / 측정값 0.9534 | 3.5절. 보정 없이는 92~95%(오차 범위 −10%). 0.9534는 읽기 데이터/wire 0.9551 때문에 100.2%까지 갈 수 있다 |
| 13 | leaf는 `fq_codel` | `pfifo` / HTB 기본 leaf | 3.7절. 0.0625 MiB/s에서도 다른 연결의 `ls`가 0.6 s 안. 30 MiB/s 쓰기에서 450 MiB마다 드롭 25~35개·재전송 830~1,120세그먼트가 있지만 처리량은 pfifo와 같았다(S7 P2c). pfifo는 드롭이 없지만 한 줄 대기열이다. HTB 기본 leaf는 pfifo와 같다 |
| 14 | `ifb` 모듈은 agent 시작 때 없으면 `modprobe ifb numifbs=0`. 다른 tc 모듈은 필요할 때 자동. HTB `quantum` 경고는 무시 | 준비 스크립트에서 올리고 modprobe 옵션 파일 고정 | 저절로 올라가면 호스트 netns에 `ifb0`·`ifb1`이 덤으로 생긴다(S7 N1). 사용자 기기 설정을 하나 더 바꾸지 않고, 없을 때 올리는 것으로 충분하다 |
| 15 | 허용 오차: 데이터가 한도의 90~101%. fio 직접 I/O, 게스트 단조 시계, 첫 회 버림, 5회 이상 중앙값. 바뀐 한도와 멈춤은 커널 카운터의 1초 창. 30 MiB/s 이상 쓰기의 서버 쪽 저하 회는 따로 셈 | 0~−10%(보정 없음 기준) / 평균 | 결정 12로 −10%가 필요 없다. 평균은 저하 회 하나가 크게 끌어내린다(S7: 30 MiB/s v4.1 쓰기 5회 중 3회가 17.72~22.44). 위쪽 1%는 시계와 측정 구간의 여유다 |
| 16 | "제한이 없는 볼륨"은 Manual 4,500 MiB/s 볼륨 | agent에 `qos` 없이 만든 볼륨 / tc를 손으로 지움 | ANF에는 한도 없는 볼륨이 없고 4,500이 일반 볼륨의 최대다. 클론의 데이터 경로(약 2 GB/s)보다 커서 사실상 제한이 없다. `qos` 없는 볼륨은 ARM 경로로 만들 수 없고, 손으로 지운 tc는 제품 상태가 아니다 |
| 17 | 기존 데이터 e2e는 Manual 풀(Premium 4 TiB, 256 MiB/s)에 `throughputMibps: 64`로 만듦 | 검증용 한도 끄기 손잡이(`ANF_...`) / 기본 볼륨을 크게(예: 100 GiB) | 1 GiB Premium Auto(0.062 MiB/s)면 볼륨 채우기 1,229 MiB만 약 5.5시간이다(계산). 끄기 손잡이는 회귀가 tc를 지나지 않게 하고 제품에 끄는 길을 만든다. 큰 볼륨은 크기 단언·채우기 시험을 깨고 ext4 lazy init이 실제 공간과 I/O를 쓴다 |
| 18 | 결함 주입 키는 기존 키(`volumes/create`, `volumes/update`, `volumes/patch`, `capacityPools/patch`) | 새 키 `volumes/throughput` | 한도 변경도 볼륨 UPDATE·PATCH 작업이라 같은 처리기를 탄다. 새 키는 공통 계층에 특례를 만든다 |
| 19 | 측정은 fio(또는 직접 I/O `dd`). 저장소의 클라이언트 이미지 `anf-nfs-client`에 fio를 넣음 | S7의 `anf-s2-client:spike` 이미지 | 저장소 밖에 남은 실험 이미지라 재현할 수 없다. 준비 스크립트를 다시 돌리면 다시 만들어진다 |

### 구현 중 변경 (설계 §9)

| # | 무엇 | 왜 |
| --- | --- | --- |
| 1 | 예산 검사는 Manual 풀에서만, 갱신에서는 한도를 올릴 때만 | 반올림한 Auto 한도의 합은 총 처리량을 넘을 수 있다(341 × 0.188 = 64.108 > 64). 그 값을 옮겨 받은 풀에서도 줄이거나 같은 값으로 두는 갱신은 받아야 한다 |
| 2 | Manual 풀 "축소" 검사는 새 크기가 지금보다 작을 때만. 문구의 두 수는 셋째 자리 | 같은 이유. 태그·같은 크기 PATCH는 넘는 상태를 새로 만들지 않는다 |
| 3 | `utilizedThroughputMibps`와 예산 비교는 셋째 자리. 남은 예산(`free`)은 0 밑으로 안 내려감. `throughputMibps`는 float로 저장 | 반올림하지 않으면 float 합의 오차(0.062 + 0.188)가 응답에 보인다 |
| 4 | Auto → Manual 채우기는 풀 PATCH 요청의 트랜잭션. 풀 작업이 실패해도 볼륨 행의 값은 남김 (리더 자동 채택) | 3.8절. 주입 실패에서만 생기고 한도는 바뀌지 않는다. 버린 대안: 실패 되돌리기에서 볼륨 행도 지움(주입 전용 코드), Auto 풀 볼륨 응답에서 값 숨김(볼륨 본문이 풀을 읽어야 함) |
| 5 | 갱신에서 저장된 값과 같으면(셋째 자리) 1~4,500 범위를 보지 않음 (리더 자동 채택) | 3.8절. 전환한 풀의 0.781 같은 값을 GET 본문 재PUT으로 다시 보낼 수 있어야 한다 |
| 6 | `throughputMibps: null`은 없는 것 | 스펙 `x-nullable`. e2e는 이 규칙으로 Auto 풀 볼륨을 만든다 |
| 7 | `pool_body(res, volumes)`가 자식 볼륨 행을 받음. 한도 공식은 `capacity_pools`에 | 순환 import 없이 풀 본문이 합을 계산한다 |
| 8 | 준비 스크립트에 `ip`·`tc` 확인 추가, `anf-nfs-client`에 fio | 결정 19 |
| 9 | 4,500 MiB/s HTB 클래스는 `burst 0b`와 quantum 경고를 보임. burst를 따로 정하지 않음 | 걸기는 성공(rc 0)하고, 이 클래스로도 읽기가 약 2,019 MiB/s였다(같은 클라이언트의 10 MiB/s 볼륨은 9.96) |
| 10 | 기존 데이터 시험 파일 여섯이 `manual_data` 픽스처로 Manual 풀 사용. 복원 데이터 AC-04b의 Auto 값 비교는 Manual 값 비교로, 볼륨 계약 AC-06의 "Manual QoS 미지원" 사례는 `0.5` 거절로 바꿈 | 결정 17. Auto 공식은 FR-08 계약 e2e(AC-01a)가 본다 |
| 11 | e2e 측정 해석: 1초 창은 `/proc/<pid>/net/dev`의 `ifb0` 송신을 그대로 데이터로 읽음(처음의 ×0.9564 환산을 뺌). Ultra 40 GiB(5 MiB/s) 사용. AC-05는 읽기. AC-06은 64 KiB × iodepth 1. AC-07은 계속 쓰는 중에 단계를 하고 다시 흐른 때부터 15 s 창 중앙값 | 3.10절. Premium 160 GiB는 ext4가 마운트 뒤 inode 표를 크기에 비례해 0으로 채워(약 2.5 GiB) 측정 중 디스크를 쓴다. 4,500 MiB/s 쓰기 6회는 회마다 수십 GB다 |
| 12 | "`ifb0` 송신 = HTB `Sent`" 문장 정정 | 3.10절. HTB가 4.24~4.35% 크다. ADR §8도 고쳤다 |
| 13 | 범위 검사를 본문 단계에서 빼 생성과 갱신에 나눔. 오류 우선순위가 바뀜(없는 볼륨에 `0.5` PATCH: 400 → 404) | 5번의 구현 |
| 14 | e2e의 1초 창 시각을 `time.monotonic()`으로 (검증 1회차 AC-12 FAIL 수정, `3328486`) | 3.6절. WSL 벽시계가 32 s마다 약 0.85 s 뒤로 건너뛰어 창이 1.7배로 읽혔다 |

### 검증 뒤 리더 결정 (자동 채택)

| 결정 | 내용 |
| --- | --- |
| AC-05는 "함께 읽는 동안"으로 판정 | 쓰기 경합(71~86%)은 제한기 원인이 아니고, 이 문서 3.9절에 "한도는 상한이고 디스크 경합을 막지 않는다"로 적는다 |
| 판정 시계는 게스트 단조 시계 | 호스트 비율(이번 부팅 +2%)은 검증마다 재서 기록한다. ADR §7.3에 FR-08 관찰을 더했다 |
| 검증 드라이버 보존 | 검증자의 `fr08_verify.py`(약 1,250줄)는 `_workspace/throughput-limit/verify/`로 옮겨 기록으로 남긴다 |

---

## 4. 실제 ANF와 다른 점

### 같은 점

- Auto 한도 공식(단가 × 할당량 2진 TiB), 풀 크기와 무관함, 소수 셋째 자리 표시 [문서][녹화].
- Manual 범위 1~4,500 MiB/s, 크기와 무관한 볼륨별 값, 볼륨 GET에서 `actualThroughputMibps` = `throughputMibps` [문서][녹화].
- 풀 `utilizedThroughputMibps` = 배정된 한도의 합, Manual 풀의 합 ≤ 총 처리량, 예산 초과 문구 "Requested throughput not available" [문서][녹화].
- Auto → Manual은 한 방향이고 `202 Patching`으로 짧게 끝난다 [문서][녹화].
- 한도는 읽기와 쓰기의 합이고, 닿으면 오류가 아니라 지연이 늘고 처리량이 상한에 머문다 [문서]. 클론에서는 fio 오류가 한 번도 없었고, 쓰기 완료 지연 최대가 한도에 반비례했다(10 MiB/s 3.06 s, 12.5 MiB/s 2.46 s, 20 MiB/s 1.54 s) [클론 측정].
- 한도 변경이 I/O를 끊지 않고 바로 반영된다 [문서]. 클론에서는 `Succeeded` 뒤 2 s 안의 1초 창이 새 한도의 97.5~100.8%였고 끊긴 창·다시 마운트가 없었다 [클론 측정].

### 다른 점

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 한도를 거는 곳 | 공개되지 않음 [미확인]. ONTAP QoS 정책은 볼륨 같은 스토리지 객체에 붙는다 [ONTAP] | 볼륨 NFS 인스턴스 netns의 네트워크 경계(tc HTB) | D-12. 블록 계층(`io.max`)은 WSL에서 효과가 없었다(S2) |
| 세는 바이트 | 읽기와 쓰기 [문서]. 메타데이터("Other") 포함 여부 [미확인] | 양방향 wire 바이트 전부(헤더, ACK, RPC, 메타데이터, `.snapshot` 읽기 포함)를 세고 ÷0.9564로 보정 | 네트워크에서 세기 때문이다. 보정으로 데이터는 한도를 넘지 않는다 |
| 단위·정밀도 | MiB/s, float32 [스펙] | MiB/s, 받은 값을 Python float로 저장(float32 흉내 없음). agent는 ONTAP 이름 `max_throughput_mbps`에 MiB/s 소수 | 2.3절 |
| 반올림 | 셋째 자리, half-even인지 버림인지 [추론] | half-even. 보이는 값을 그대로 건다 | 결정 2 |
| 가장 낮은 Auto 한도 | 최소 크기 50 GiB라 Standard 0.781 [추론] | 검증 전용 크기(`ANF_MIN_VOLUME_SIZE_GIB`)로 0.062(Premium 1 GiB), 0.016(Standard 1 GiB)까지 | 결정 2. 제품 규칙(최소 50 GiB)은 같다 |
| 4,500을 넘는 Auto 값 | 실제 처리량은 4,500에서 멈춤 [문서], 표시 [미확인] | 공식 값을 보이고 그대로 건다. 전환 때도 자르지 않는다 | 미룸(설계 §2). 검증 볼륨은 작다 |
| Manual 풀에서 값 생략 | [미확인] | `400 InvalidRequestContent` | 결정 3 |
| Auto 풀 볼륨에 값 | 스펙은 "Manual에서만 입력으로 받는다" [스펙], 동작 [미확인] | `400 BadRequest` | 결정 4 |
| 예산 초과 응답 | 문구 [문서], 코드·동기 여부 [미확인] | 동기 `400 BadRequest` + 문서 문구 + 총량·남은 양 | 결정 7 |
| Manual 풀 축소 | [미확인] (거절 [추론]) | 크기를 줄일 때만, 배정 합보다 작으면 `400` | 결정 7, §9-2 |
| 전환 뒤 기존 볼륨 값 | [미확인]. "might be capped" [문서] | 직전 Auto 한도를 그대로 옮김. 4,500을 넘어도 자르지 않음. 자식 볼륨이 바쁘면 `409` | 결정 6 |
| 1 미만 값의 재PUT | [미확인] | 저장 값과 같으면 범위 검사 생략 | §9-5 |
| 이웃 경합 | [미확인]. ONTAP에는 하한 필드가 있다 [ONTAP], ANF API에는 없다 [스펙] | 상한뿐. 같은 aggregate 이웃이 많이 쓰면 쓰기가 한도의 71~86% | 3.9절 |
| IOPS 한도 | ANF 한도는 MiB/s. ONTAP 정책에는 IOPS 필드도 있다 [ONTAP] | IOPS는 제한하지 않는다 | 범위 밖 |
| 할당량 변경 → 한도 | 바로 바뀌고 I/O를 끊지 않는다 [문서][녹화] | 할당량 변경 자체가 아직 없다 | FR-16. agent 경로(POST `qos`)를 그대로 쓴다 |
| Manual PATCH 응답 | [미확인] (`202` [추론]) | `202 Patching` → `Succeeded`(`action: PATCH`), 2.1~4.5 s | 볼륨 PATCH 녹화 모양 |
| 지표 | "Throughput limit reached", "QoS Latency Delta", Read·Write·Other·Total [문서] | 없음. 카운터 두 개만 확인 | FR-12 (3.10절) |
| Flexible·Elastic·대용량 볼륨 | 있음 [문서] | 지금처럼 거절 | 범위 밖 |

---

## 5. 검증

real-env-verifier 1회차, 2026-11-09. **PASS 11 / FAIL 1 / UNVERIFIED 0.** FAIL은 AC-12 회귀이고 원인은 시험 코드(`time.time()` 표본 시각)였다. 제품 코드 내용 해시는 시작과 끝이 `f99bc5cf…`로 같다. 검증자(구현자와 다른 에이전트)는 구현자의 e2e를 쓰지 않고 자기 드라이버(`fr08_verify.py`, 표준 라이브러리만)로 fio·tc·`/proc/<pid>/net/dev`를 직접 다뤘다. 모든 처리량 값은 게스트 단조 시계 기준이고, 이 부팅에서 호스트보다 약 2% 빨랐다(3.6절).

| AC | 결과 | 증명한 것과 측정값 |
| --- | --- | --- |
| AC-01 Auto | PASS | (a) Premium 101 GiB → `actualThroughputMibps` 6.312, Premium 1 GiB → 0.062, Standard 1 GiB → 0.016, `throughputMibps` 없음. 풀 `utilizedThroughputMibps` 6.374(= 6.312 + 0.062). HTB rate 55,362,708 / 543,804 / 140,336 bit/s. (b) Ultra 80 GiB v3(10 MiB/s): 쓰기 9.808(98.1%), 읽기 9.723(97.2%). Ultra 40 GiB v4.1(5 MiB/s): 쓰기·읽기 4.955(99.1%) |
| AC-02 Manual 생성 | PASS | Manual 풀에 10(v4.1)·20(v3)·12.5(v4.1) → `201 Creating` → `Succeeded`, GET 값 = 요청 값, `utilizedThroughputMibps` 30.0 → 42.5. 중앙값 95.6~97.8%. 쓰기 완료 지연 최대는 한도에 반비례(10 → 3.06 s, 20 → 1.54 s) |
| AC-03 합산 | PASS | 읽기 + 쓰기: 5.05 + 4.72 = 9.78(97.8%, v4.1), 11.0 + 8.2 = 19.21(96.1%, v3) |
| AC-04 한도 변경 (PRD) | PASS | 쓰는 중(v4.1)·읽는 중(v3) PATCH 10 → 30 → 5: 매번 `202 Patching` → `Succeeded`(2.1~4.5 s), 그 뒤 2 s 안의 1초 창 97.5~100.8%. 60 s 동안 끊긴 창 없음(5 MiB/s 구간 최소 4.963), 다시 마운트 없음(connect 횟수 2 → 2), fio 오류 0. 재PUT 15 → `200 Updating` → 97.5~98.5% |
| AC-05 제한 없는 볼륨과 차이 | PASS (읽기) | A(10)와 B(4,500, HTB 39.5 Gbit) 함께 읽기: A 9.925(99.25%), B 2,041.9(A의 205.7배). A만 9.714와의 차이 0.211. 쓰기 표본(참고): A 71~86%(3.9절) |
| AC-06 작은 Auto 한도 | PASS | 0.062 MiB/s, v3·v4.1. 작은 파일 쓰기·읽기·`ls` rc 0. 64 KiB 직접 쓰기 0.0598·0.0597(상한 0.0626 이하). 같은 연결 메타데이터 최대 2.18 s, 다른 연결 0.36 s, timeouts 0, dmesg NFS 줄 0 |
| AC-07 수명 주기 | PASS | 아래 표 |
| AC-08 거절 | PASS | 설계 §4.2 행마다 코드와 문구(값 없음·`null`, `0.5`·`4500.5`·`"10"`·`true`·`0`·`4501`, Auto 풀에 값, 예산 초과 생성·PATCH·재PUT, Manual 풀 축소, Manual → Auto). 앞뒤로 DB 행 수, 볼륨·풀 GET, netns HTB rate가 같음(`same: true`). 남은 예산 정확히 28 → `201`, 풀 utilized 128.0. 바쁜 풀 Auto → Manual `409`. 없는 볼륨에 `0.5` PATCH는 `404`(§9-13) |
| AC-09 Auto → Manual | PASS | Premium 80 GiB(5.0)와 1 GiB(0.062). 전환 `202` → `Succeeded`(0.04 s) 뒤 GET 5.0/5.0, 0.062/0.062, utilized 5.062 그대로, 같은 pid·같은 rate. 쓰기·읽기 전후 99.1%·99.0%. PATCH 8 → 98.2%. 0.062 볼륨 GET 본문 재PUT → `200 Updating` → `Succeeded`, rate 그대로 |
| AC-10 실패·재시작 | PASS | (a) PATCH 17에 30 s 지연 주입, `Patching` 중 HTB는 아직 15. anf-api SIGKILL → 재시작 → 같은 작업 `Succeeded`(8.77 s), HTB 17, 97.2%. (b) 실패 주입 → `Failed`, `throughputMibps` 17 유지, HTB 그대로. 주입 없이 같은 PATCH 9 → `Succeeded`, 98.2% |
| AC-11 agent API | PASS | `qos` POST → job `success`, 레코드·태그·netns tc. 같은 uuid에 20 → 태그가 `anf_qos=20.0` 하나로 바뀌고 HTB rate도 바뀜, 같은 pid. `qos` 없는 볼륨은 netns에 `lo, eth0`뿐. 모양 오류 10가지 `400`. 통합 30 passed(FR-08 다섯: `test_flexvol_linux.py:639`, `:660`, `:668`, `:687`, `:698`) |
| AC-12 회귀 | 1회차 FAIL → 2회차 (리더가 채운다) | 1회차: 기존 e2e 14개 파일 통과(합 2,384.7 s, FR-07 2,326 s 대비 +2.5%. 데이터 쓰는 6개 +4.2%: 64 MiB/s 한도가 실제로 걸림), FR-08 계약 8 passed, 단위·계약 914 passed(Windows·WSL), 통합 30 passed. FR-08 데이터 e2e는 6 passed / 1 failed(AC-07 `over_limit`, 3.6절). 2회차: |

**AC-07 수명 주기** (Manual 10 MiB/s, NFSv4.1, 쓰는 중에 단계를 하고 다시 흐른 때부터 15 s의 1초 창 중앙값)

| 단계 | 인스턴스 pid | I/O 멈춤 | 판정 창 | 제한 없는 창 |
| --- | --- | --- | --- | --- |
| (a) agent만 재시작 | 그대로 | 없음 | 9.816 (98.2%) | 없음 |
| (b) `docker stop` → agent 재시작(복구의 `docker start`) | 바뀜 | 약 21.6 s(새 인스턴스 14.5 s 뒤, I/O는 그 7.3 s 뒤) | 9.847 (98.5%) | 없음. `ifb0`이 I/O보다 먼저 생김 |
| (c) `docker rm -f` → 재PUT(agent `docker run`) | 바뀜 | 약 2.6 s | 9.843 (98.4%) | 없음 |
| (d) 쓰는 중 되돌리기 | 그대로 | 약 2.5 s(차단 창) | 9.818 (98.2%) | 없음 |
| (e) 스냅샷에서 새 볼륨: Manual 7 / Auto(0.125) | 새 인스턴스 | — | 6.917 (98.8%) / rate 1,096,378 bit/s | — |
| (f) 볼륨 삭제 | 사라짐 | — | netns가 `lsns`에서 사라짐, 호스트 IFB 앞뒤 0개 | — |

**측정에서 따로 센 것.** AC-04에서 30 MiB/s 쓰기가 t≈24~37 s에 약 12 MiB/s로 떨어졌다. HTB `Sent` 창도 같은 값이라 제한기가 아니라 서버 쪽 쓰기 저하였고, 판정 창 밖이었다. AC-05 쓰기 표본은 3.9절이다.

---

## 6. 개발 과정

1. **선행 확인 (0단계).** 계정·풀·볼륨·스냅샷·되돌리기·복원이 모두 `done`이었다. D-12(T1n)는 S2에서 정했지만, S2는 볼륨 구현 전의 실험용 인스턴스에서 쟀다. 지금 agent 인스턴스(재시작, 되돌리기 창, 시작 복구)에서 tc를 건 적이 없었다. 또 검증용 1 GiB 볼륨의 Auto 한도 0.0625 MiB/s에서 NFS가 어떻게 되는지 몰랐다. 그래서 설계 전에 스파이크 S7을 조사와 병행했다.
2. **조사.** anf-researcher가 Learn 문서 9개, 스펙, SDK 녹화, ONTAP 휠을 봤다. 30턴 상한에 닿아 "한도 도달"로 마감했다. Manual 기본값, 예산 초과 코드, 전환 뒤 값, 풀 축소는 [미확인]으로 남았다. 설계를 막지 않는다고 보고 클론 규칙으로 정했다. ONTAP 대응은 [추론]으로 채워졌다.
3. **스파이크 S7 (조건부 통과).** 실제 agent 인스턴스에서 T1n이 v3·v4.1 모두 동작했다. 조건 넷이 설계 결정이 됐다.
   - 인스턴스가 다시 뜰 때마다 tc가 사라진다 → 결정 10·11.
   - 호스트 IFB의 이름·정리 문제와 netns 변형의 결과 → 결정 9.
   - 0.0625 MiB/s에서 같은 연결 메타데이터가 1분을 넘는다 → 결정 2·13·17, AC-06.
   - 헤더 보정의 이론 상한 0.9564 → 결정 12.
   - 30 MiB/s 쓰기의 서버 쪽 저하 → 결정 15.
4. **설계.** 결정 1~19를 모두 자동 채택했다. 사람이 내린 결정은 없다. 결정 9가 ADR §7.3의 "호스트 쪽 veth" 문구와 다르지만, D-12의 결정문은 그대로라 묻지 않고 다듬기로 봤다. 채택 목록과 버린 대안을 `roadmap.md`에 남겨 사용자가 나중에 검토할 수 있게 했다.
5. **구현.** Claude(implementer, 스파이크와 같은 에이전트)가 TDD 훅 아래서 구현했다. agent `9c0b84d`, API `540957d`, e2e `b6d2711`, 설계 §9 기록 `38689e4`.
   - 1차 보고 때 AC-12 회귀는 14개 파일 중 5개만 돌았다. WSL 페이지 캐시 6.8 GB로 호스트 메모리가 모자라 실행기가 강제 종료됐다.
   - 리더가 §9-4(그대로 둠)와 §9-5(같은 값이면 범위 검사 생략)를 자동 채택했다. 카운터 문장(§6.3, ADR §8)을 고쳤다.
   - implementer가 §9-5를 구현했다(`0b44a8f`). 오류 순서 변화는 §9-13에 기록했다(`a3ad172`). 남은 회귀는 파일 사이에 `drop_caches`를 넣어 돌렸고 모두 통과했다.
6. **검증 1회차.** 11 PASS, 1 FAIL(AC-12, 시험 코드).
   - 검증자는 측정을 구현자의 e2e에 맡기지 않고 자기 드라이버로 다시 쟀다. 그 과정에서 WSL 벽시계의 32초 계단을 찾았다. 자기 드라이버는 ac06부터 단조 시계로 바꿨고, 구현자 e2e의 같은 결함을 AC-12 실패로 보고했다.
   - AC-12 첫 시도는 로그를 `/mnt/c`(9P)에 바로 써서 요청이 많은 시험이 3~4배 느려졌다(풀 계약 2.48 s → 10.48 s). 시간 비교가 틀어져 WSL ext4에 쓰고 끝난 뒤 복사하는 방식으로 16개 파일을 다시 돌렸다.
   - 리더 결정(자동 채택): AC-05 읽기 판정, 게스트 단조 시계 유지, 검증 드라이버 보존(3절 표).
7. **수정.** implementer가 표본 시각과 비교 시각을 `time.monotonic()`으로 바꿨다(`3328486`). 제품 코드 해시는 그대로다.
8. **검증 2회차.** 처리량 데이터 e2e 한 파일만 다시 돌린다(약 38분). 결과는 5절 AC-12 행에 리더가 채운다.
9. **개념 문서(이 문서).**

AI와 일한 방식으로 설명할 수 있는 것:
- 이번 사이클도 사람에게 묻는 결정 없이 굴러갔다. 그 대신 (a) 이전 스파이크(S2)가 지금 구조 전의 측정이라는 점을 0단계에서 잡아 S7로 다시 쟀다. (b) 자동 채택한 결정을 버린 대안과 함께 남겼다.
- 측정 결함 두 개는 서로 다른 에이전트가 잡았다. 구현자는 자기 e2e에서 "`ifb0` = HTB `Sent`"라는 설계 문장이 틀렸음을 4% 차이로 찾았다(§9-12). 검증자는 독립 드라이버로 다시 재다가 시계 결함을 찾았다(§9-14).
- 검증자가 판단할 수 없는 해석(AC-05를 쓰기로 볼지 읽기로 볼지)은 PASS/FAIL로 덮지 않고 리더 결정으로 올렸다.

---

## 7. Interview Q&A

### Q1. (개념) How does Azure NetApp Files decide a volume's throughput limit?

**A.** It depends on the capacity pool's QoS type. In an Auto pool, the limit is the service level's rate times the volume quota in binary TiB: 16, 64, or 128 MiB/s per TiB for Standard, Premium, and Ultra. Pool size and actual usage don't matter. A 100 GiB Premium volume gets 6.25 MiB/s, and a recording showed 101 GiB as 6.312, so the response is rounded to three decimals. In a Manual pool, you set `throughputMibps` on each volume, from 1 to 4,500 MiB/s for a regular volume, independent of its size. The sum can't exceed the pool's total, which is pool TiB times the same rate. Either way, the limit covers reads and writes combined, and reaching it shows up as latency, not errors.

### Q2. (개념) What is the ONTAP equivalent, and how confident are you?

**A.** The closest match is a fixed QoS policy ceiling, but that mapping is my inference, because ANF doesn't publish its internals. In ONTAP REST, a policy lives at `/api/storage/qos/policies` and is either fixed or adaptive, not both. A fixed policy has `max_throughput_mbps`, where 0 means no limit, plus IOPS ceilings and optional floors. A volume can reference a policy or carry values inline under `qos.policy`. Manual QoS looks like a non-shared fixed policy per volume. Auto QoS resembles adaptive QoS, since both scale with size, but adaptive policies are defined only in IOPS per TB, so they can't express MiB/s per TiB. The pool budget has no direct counterpart: ANF checks the sum when assigning, while `capacity_shared` splits one ceiling at runtime.

### Q3. (설계) How does your clone enforce the limit on real I/O?

**A.** With Linux traffic control inside each volume's network namespace. Every volume already has its own knfsd instance and IP. The agent attaches a `clsact` qdisc to the instance's `eth0` and redirects both ingress and egress to an IFB device, `ifb0`, in the same namespace. On `ifb0` there is one HTB class, with rate equal to ceil, and an `fq_codel` leaf. Write data arrives as ingress and read data leaves as egress, so both drain one token bucket, which matches ANF's "reads plus writes" rule. The verifier measured 5.05 MiB/s of reads plus 4.72 of writes, 9.78 in total, on a 10 MiB/s volume. I rejected cgroup `io.max` because it counts reads and writes separately, misses cache hits, and couldn't see knfsd threads in WSL.

### Q4. (설계) Why did you put tc inside the namespace instead of on the host-side veth, as your architecture doc first said?

**A.** Because the host side had lifecycle problems, while accuracy was the same. In spike S7, both placements gave about 9.4 MiB/s on a 10 MiB/s limit before correction, and both worked with the revert window. But on the host, Docker gives the veth a new random name on every start, so I'd have to find it again each time. Interface names are limited to 15 characters, so a UUID can't name the IFB, and tc can't use altnames. The host IFB outlived volume deletion. Deleting it before its filter dropped all traffic for about 12 seconds. Inside the namespace, every instance just uses `ifb0`. The agent enters by PID with `nsenter`, the same path the revert window uses, and everything disappears with the instance.

### Q5. (설계) Why do you divide the limit by 0.9564?

**A.** Because HTB counts wire bytes, including Ethernet, IP, and TCP headers, while the client measures data. With MTU 1500 and TCP timestamps, a full segment carries 1,448 data bytes in 1,514 bytes on the wire. So data can be at most 1448/1514, or 0.9564, of what HTB lets through. Without correction, the spike measured 92 to 95 percent of the limit. Dividing by 0.9564 keeps data under the limit for any I/O shape, because ACKs and RPC headers only lower the ratio. I didn't use the measured 0.9534, which gave 98 to 99 percent, because reads showed 0.9551, so a full bucket could reach 100.2 percent. Verification medians landed between 95.6 and 99.3 percent. The factor depends on the MTU.

### Q6. (설계/재시작) What happens to the limit when an instance restarts, and how did you avoid an unlimited window?

**A.** The limit disappears with the namespace, so the agent reapplies it on every start path, before the server is ready. In S7, after `docker start`, `docker run`, or startup recovery, the new namespace had no tc, and a 10 MiB/s volume took 48 to 186 MiB/s until the limit was reapplied. So creation, re-sends, and recovery all run `start`, then the limit, then `wait_ready`. `docker start` returns before the entrypoint launches knfsd. The value lives in an LVM tag, `anf_qos`, so the agent can recover alone, without anf-api. Applying is idempotent: create what's missing, then `tc class replace` the rate. In verification, `ifb0` existed about seven seconds before I/O resumed, and the limit held at 98.5 percent.

### Q7. (트레이드오프) Does a throughput limit isolate a volume from its neighbors?

**A.** No. In my clone it's a ceiling, not a guarantee, and verification showed it. A 10 MiB/s volume and a 4,500 MiB/s volume shared one client and one thin pool. Reading together, the small volume held 99 percent while the large one read 2,042 MiB/s from cache. But while the large one wrote gigabytes to the same aggregate, the small volume's writes fell to 71 to 86 percent of its limit. Its HTB queue was empty in 40 to 47 percent of samples, so the limiter wasn't holding it back; the disk was. ONTAP QoS policies have minimum-throughput floors, documented as not guaranteed on non-AFF platforms, and the ANF volume API has no floor. I couldn't confirm how ANF handles noisy neighbors.

### Q8. (장애·디버깅) Your e2e test saw one-second windows at 1.7 times the limit. How did you find the cause?

**A.** By noticing the pattern was periodic, not tied to operations. The failing lifecycle test reported windows around 17 MiB/s on a 10 MiB/s volume. But they came in pairs 0.5 seconds apart, every 31 to 32 seconds, even in steps that didn't touch the instance. The verifier's own driver, which used the monotonic clock, saw no such windows, and HTB's byte counter stayed under the limit. Comparing `time.time()` with `time.monotonic()` every 50 milliseconds showed the WSL wall clock stepping back about 0.85 seconds every 32 seconds. A window spanning a step was computed shorter than it was, so the rate looked higher. The fix touched only test code: timestamp samples with the monotonic clock. Separately, the guest clock ran about 2 percent fast versus the host.

### Q9. (관측성) Which counter would you export as a per-volume throughput metric?

**A.** It depends on what the metric should mean, because the two candidates differ by about 4 percent. The `ifb0` transmit counter, read from `/proc/<pid>/net/dev`, counts each GSO batch's headers once, so it's close to data, about 0.5 to 1 percent above fio. HTB's `Sent` bytes count headers per segment. That's real wire traffic, and it's what the rate limits, 4.2 to 4.4 percent higher. My design first said they were equal. The e2e proved otherwise when converting `ifb0` by 0.9564 made the windows 4 percent low. For user-facing volume throughput, like ANF's read and write metrics, `ifb0` fits. For a "throughput limit reached" signal, compare HTB `Sent` with the rate. That choice belongs to the metrics feature, FR-12.

### Q10. (트레이드오프) What happens with a tiny limit like 0.062 MiB/s?

**A.** I/O keeps working, but small requests on the same TCP connection wait behind large writes. 0.062 MiB/s is a 1 GiB Premium volume, a size only my verification setting allows. ANF's 50 GiB minimum makes the lowest Auto limit about 0.78. In the spike, with 1 MiB writes and 16 in flight, there were no errors, and the NFSv4.1 lease stayed confirmed. But `ls` on the same mount took 47 to 76 seconds, and the kernel logged RPC timeouts, because one 1 MiB write holds the connection for about 16 seconds. Other clients stayed under 2 seconds, because `fq_codel` gives each flow its own queue. In verification, with 64 KiB writes and one in flight, same-connection metadata took at most 2.2 seconds, with no timeouts.

### Q11. (REST API) Which rules did you have to invent, and why does a same-value re-PUT skip the 1-to-4,500 range check?

**A.** Several, because ANF doesn't document them. Manual-pool volumes must send `throughputMibps`, Auto-pool volumes may not, and an over-budget request is a synchronous 400 with ANF's documented message, "Requested throughput not available". The range exception came from Auto-to-Manual conversion. Conversion copies each volume's previous Auto limit into `throughputMibps`, and that can be below 1, for example 0.781 for a 50 GiB Standard volume. ARM clients like Terraform or `az` redeploy by sending the GET body back. If that unchanged value failed the range check, a converted pool's volumes could never be redeployed. So on update, a value equal to the stored one at three decimals counts as unchanged and skips the range check. New volumes still need 1 to 4,500.

### Q12. (테스트) How did you prove the limit has a real effect, not just a stored value?

**A.** By measuring from real NFS clients and reading kernel state, with an independent verifier. A separate agent wrote its own driver instead of reusing the implementer's tests. For each case it ran fio with direct I/O, 1 MiB blocks, and 16 in flight, discarded the first run, and required the median of five to fall within 90 to 101 percent. It checked tc inside the instance namespace: the HTB rate in bits per second and one redirect filter per direction. It changed limits during I/O and read one-second windows from the `ifb0` counter. New limits appeared within two seconds, with no stalls or remounts. It also killed anf-api during a PATCH, injected failures, restarted the agent, removed the instance, and reverted while writing.

### Q13. (다시 한다면) If you did this again, what would you change?

**A.** Three things. First, I'd make neighbor contention visible. My limit is only a ceiling, and on one shared sparse file, a heavy writer cut a neighbor's writes to about 71 percent. In the metrics feature I'd expose "below the limit with an empty queue" separately from "at the limit", so contention isn't mistaken for throttling. Second, I'd use a monotonic clock in every measurement helper from the start. The spikes had already shown that the WSL clock ratio changes between boots, yet the e2e first used wall time and failed. Third, I'd show the riskiest of the nineteen automatically adopted decisions to a person before implementing, especially the invented error codes and the conversion rule, since ANF's behavior there is unconfirmed.

---

## 부록. 이 문서가 쓰지 못한 것

브리프·스파이크·검증 보고서에 근거가 없거나 [미확인]이라 쓰지 못한 것이다.

- **ANF가 이웃 볼륨의 디스크 경합(noisy neighbor)을 어떻게 다루는지.** 브리프에 없다.
- **ONTAP 하한(`min_throughput_*`)과 adaptive QoS(`expected_iops`, `absolute_min_iops`)가 경합 때 실제로 무엇을 보장하는지.** 브리프는 필드 이름과 "non-AFF·FabricPool에서는 하한이 보장되지 않는다"까지만 있다.
- **ANF가 내부에서 ONTAP QoS policy를 쓰는지, 한도를 어느 계층에서 세는지.** ADR §7.3은 "ONTAP은 스토리지 계층에서 제한한다"고 [추론]으로 적었지만 브리프에는 그 근거 문장이 없다.
- **ONTAP `max_throughput_mbps`의 단위(10진 MB인지 MiB인지)와 타입(정수인지).** 설계 기록은 정수로 적었다.
- **ANF Auto 한도의 반올림 방식(half-even인지 버림인지)과, 내부에서 거는 값이 6.3125인지 6.312인지.**
- **4,500을 넘는 Auto 공식 값의 ANF 표시.**
- **Manual 볼륨 개별 PUT·`throughputMibps` PATCH의 실서비스 응답과 걸린 시간.** 녹화는 볼륨 그룹 경로뿐이다.
- **메타데이터("Other")와 `.snapshot` 읽기가 ANF 한도에 포함되는지.**
- **ONTAP `policy_class: autovolume`의 뜻.** 브리프의 후속 조사 목록에 있다.
- **WSL 게스트 시계가 왜 2% 빨리 가는지, 왜 부팅마다 비율이 다른지.** 관찰만 있다.
