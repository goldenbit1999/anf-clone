# 메트릭 (metrics, FR-12)

> ANF 볼륨 메트릭은 Azure Monitor의 플랫폼 메트릭이다. 차원(dimension)이 없고 5분 평균이며, read/write/other/total로 나뉜 처리량(throughput)·IOPS와 read/write/other 지연(latency)이 있고 사용량 메트릭이 따로 있다. 이 클론에서는 storage agent가 스크레이프(scrape) 때마다 세 곳을 읽어 Prometheus 카운터(counter)와 게이지(gauge)로 낸다. 볼륨마다 따로 도는 knfsd 인스턴스의 네트워크 네임스페이스(netns) 카운터(`/proc/<pid>/net/rpc/nfsd`), 볼륨 파일시스템의 `statvfs`, dm-thin 풀 상태다. anf-api는 HTTP 요청과 비동기 작업의 지표를 낸다. Prometheus가 5 s마다 둘을 긁고, 대시보드는 Prometheus 쿼리 API로 `rate(...[20s])`를 그린다. 이 문서의 중심은 두 가지다. 하나는 **볼륨별 카운터가 어디서 나오는가**다. 어떤 커널 카운터는 netns마다 따로 있고 어떤 것은 전역이다. 다른 하나는 **무엇을 내지 않았는가와 그 이유**다. 지연, 한도 도달, NFSv3 읽기·쓰기 IOPS, 스냅샷을 포함한 사용량은 내지 않았다.

코드 인용 기준: 커밋 `e80c8e7` (제품 코드 내용 해시 `7c38d8c7fdf750e4…`). 검증자 보고서에 따르면 제품 코드는 `37a341c` 이후 바뀌지 않았다. 검증 중에 HEAD가 `a4322ad`로 올라갔지만 그 커밋은 문서(`CLAUDE.md`, `docs/ADR.md`, 진행 기록)만 바꿨다.

FR-12(메트릭)를 다룬다. 브랜치는 `feature/metrics`다. 볼륨마다 knfsd 인스턴스와 netns를 두는 구조(D-12)는 [볼륨 문서](volume.md)에, 볼륨 한도와 tc 카운터(`ifb0`, HTB `Sent`)는 [처리량 제한 문서](throughput-limit.md)에, 스냅샷 공간이 씬 풀에서 나가는 이유(R-09)는 [스냅샷 문서](snapshot.md)에, 리소스 트리와 2초 폴링은 [대시보드 문서](dashboard.md)에 있다. 이 문서는 그 위에 메트릭을 어떻게 얹었는지만 설명한다.

근거 표시는 브리프를 따른다. 괄호 안의 ID(D1, O1, K1 …)는 브리프 "출처"의 번호다.

| 표시 | 뜻 |
| --- | --- |
| [문서] | Microsoft Learn(D1~D5), NetApp Harvest 문서(H1), Prometheus 문서(P1~P3)에 적혀 있다 |
| [ONTAP] | `netapp-ontap` 9.19.1.0 휠(ONTAP REST 문서에서 생성된 클라이언트, O1)에 적혀 있다 |
| [스펙] | 이 문서에서는 Linux 커널 v6.18의 소스와 문서(K1~K12)를 뜻한다 |
| [추론] | 근거에서 이끌어 낸 해석이다. 사실로 말하면 안 된다 |
| [추정] | 스파이크가 관찰에서 짐작한 원인이다. 따로 확인하지 않았다 |
| [미확인] | 찾아봤지만 확인하지 못했다 |
| [클론 측정] | 스파이크 S8과 구현자 e2e의 측정이다. ANF·ONTAP 사실이 아니라 이 클론의 동작이다 |

**조사 상태는 "한도 도달"이다(30턴 상한).** Azure Monitor 메트릭의 보존 기간·표시 지연·Metrics REST api-version, `VolumeLogicalSize`가 ONTAP의 어느 필드에서 오는지, `ThroughputLimitReached`의 ONTAP 원천, ANF가 NFSv4.1 IOPS를 COMPOUND 단위로 세는지 연산 단위로 세는지는 [미확인]이다. 면접에서 이것들을 사실처럼 말하면 안 된다.

**설계 결정 1~14는 모두 자동 채택이다.** 확정된 D-nn을 바꾸지 않고 PRD 수락 기준을 줄이지 않아서, 리더가 사람에게 묻지 않고 골랐다. 3절의 표에 버린 대안과 이유를 모두 적었다.

---

## 1. ANF에서는

### 1.1 메트릭이 사는 곳

- 메트릭은 ANF 리소스 API가 아니라 Azure Monitor 쪽에 있다. 붙는 리소스 형식은 용량 풀(`Microsoft.NetApp/netAppAccounts/capacityPools`)과 볼륨(`…/capacityPools/volumes`)이다 [문서 D1][D2].
- 조회는 Azure Monitor 메트릭 REST(`{resourceUri}/providers/Microsoft.Insights/metrics?metricnames=...&interval=PT5M&aggregation=Average`)와 포털의 "Metrics" 블레이드로 한다 [문서 D3]. Metrics REST의 정확한 api-version은 [미확인]이다.
- 모든 메트릭이 "Advanced platform metrics" No, 진단 설정 내보내기(DS Export) Yes다 [문서 D1][D2].
- **차원이 하나도 없다.** 모두 `Average` 집계이고(풀 크기 두 개만 `Total`도 된다), 시간 단위(time grain)는 `PT5M, PT15M, PT30M, PT1H, PT6H, PT12H, P1D`다. 1분 단위가 없다 [문서 D1][D2].
- 이름이 둘이다. REST 이름(PascalCase, 예: `ReadThroughput`)과 표시 이름("Read throughput")이 따로 있고, 서로 어긋나는 것도 있다(`VolumeLogicalSize` = "Volume Consumed Size") [문서 D1].
- 메트릭은 읽기 전용이고 리소스의 `provisioningState`와 상관없다 [추론].

### 1.2 볼륨 메트릭

| 분류 | 표시 이름 | REST 이름 | 단위 | 비고 |
| --- | --- | --- | --- | --- |
| 사용량 | Volume allocated size | `VolumeAllocatedSize` | Bytes | "The provisioned size of a volume" [문서 D1] |
| 사용량 | Volume Consumed Size | `VolumeLogicalSize` | Bytes | "Logical size of the volume (used bytes)" [D1]. "includes logical space used by active file systems and snapshots" [문서 D3] |
| 사용량 | Volume snapshot size | `VolumeSnapshotSize` | Bytes | "Size of all snapshots in volume" [D1] |
| 사용량 | Percentage Volume Consumed Size | `VolumeConsumedSizePercentage` | Percent | 스냅샷 포함. min/max 집계는 지원하지 않는다 [D3] |
| 사용량 | Volume Inodes Used / Total / Quota / Percentage | `VolumeInodesUsed`, `VolumeInodesTotal`, `VolumeInodesQuota`, `VolumeInodesPercentage` | Count, Percent | Quota는 지원 요청으로 늘렸을 때만 0이 아니다 [D3] |
| 처리량 | Read / Write / Other / Total throughput | `ReadThroughput`, `WriteThroughput`, `OtherThroughput`, `TotalThroughput` | BytesPerSecond | Other = 읽기도 쓰기도 아닌 것. Total = read + write + other [D3] |
| IOPS | Read / Write / Other / Total iops | `ReadIops`, `WriteIops`, `OtherIops`, `TotalIops` | CountPerSecond | Other = 메타데이터 등 [D3] |
| 지연 | Average read / write / other latency | `AverageReadLatency`, `AverageWriteLatency`, `AverageOtherLatency` | MilliSeconds | 연산당 값이고, 서비스 안에서 재며 네트워크 지연은 들어가지 않는다 [D3] |
| QoS | Throughput limit reached | `ThroughputLimitReached` | Count | "1 if it has and 0 if not" [D1] |
| QoS | QoS latency delta | `QosLatencyDelta` | MilliSeconds | "Latency for Exceeded Throughput" [D1] |

- 백업(`Cbs*`), 복제(`Xregion*`), cool tier(`VolumeCoolTier*`) 메트릭은 범위 밖이라 이름만 봤다. cache 볼륨 메트릭과 구독 쿼터 메트릭은 개념 문서에만 있다 [문서 D1][D3].

### 1.3 풀 메트릭

| 표시 이름 | REST 이름 | 단위 | 설명 |
| --- | --- | --- | --- |
| Pool Allocated Size | `VolumePoolAllocatedSize` | Bytes | 풀의 프로비전 크기 [문서 D2] |
| Pool Allocated To Volume Size | `VolumePoolAllocatedUsed` | Bytes | 볼륨 할당량의 합 [문서 D3]. 정의 페이지는 "Allocated used size of the pool"이라고 써서 둘이 다르다. 이름으로 보면 할당량 합이 맞다 [추론] |
| Pool Consumed Size | `VolumePoolTotalLogicalSize` | Bytes | 풀의 모든 볼륨 logical size의 합 [D2] |
| Total Snapshot size for the pool | `VolumePoolTotalSnapshotSize` | Bytes | 풀의 모든 볼륨 스냅샷 크기의 합 [D2] |
| Pool allocated throughput | `VolumePoolAllocatedToVolumeThroughput` | BytesPerSecond | 볼륨 처리량(한도)의 합 [D2] |
| Provisioned throughput for the pool | `VolumePoolProvisionedThroughput` | BytesPerSecond | 풀의 총 처리량 [D2] |

- 풀 처리량 메트릭 둘은 ARM 속성 `utilizedThroughputMibps`, `totalThroughputMibps`와 뜻이 같아 보인다 [추론]. 단위만 MiB/s가 아니라 BytesPerSecond다 [문서 D2].
- 풀 메트릭에는 IOPS도 실측 처리량도 없다. 실측값은 볼륨 단위에만 있다 [문서 D2].

### 1.4 시간: 5분 평균

- "Unless otherwise specified, Azure NetApp Files metrics represent values over a five-minute average." 그래서 짧은 급증은 평균에 묻힌다. 문서 예시는 100/120/500/110/120 MiB/s가 190 MiB/s로 보이는 경우다 [문서 D3].
- "Throughput limit reached"도 5분마다 모은다. 1은 "직전 5분 창 안에 한도에 닿은 적이 있다"는 뜻이다 [문서 D3].
- 포털에 보이기까지의 지연과 보존 기간은 ANF 문서에 없다. Azure Monitor 일반 보존 기간은 원문을 확인하지 못했다 [미확인].

### 1.5 정의: 무엇을 세는가

- **처리량**: "The amount of data transmitted across the wire (read/write/other) between Azure NetApp Files and the client ... measured in bytes per second" [문서 D3]. 이 문장만으로는 프로토콜 헤더를 세는지 알 수 없다 [추론].
- **지연**: 요청이 "arrives"한 때부터 "processed and is ready to be sent back to the client"까지다 [문서 D3].
- **Other IOPS**: 목록이 문서에 있다. NFSv3은 NULL, GETATTR, SETATTR, LOOKUP, ACCESS, …, FSSTAT, FSINFO, PATHCONF, COMMIT이고, NFSv4.1은 COMPOUND, ACCESS, CLOSE, COMMIT, GETATTR, LOOKUP, OPEN, PUTFH, SETATTR 등이다. **COMMIT은 Write가 아니라 Other다** [문서 D3]. v4.1 목록에 COMPOUND와 개별 연산이 함께 있어서, COMPOUND 하나 안의 연산을 각각 세는지는 판단할 수 없다 [미확인].
- **사용량과 `df`**: "The `df` command provides an accurate *available space*. However, the *consumed or used space* is an estimate when snapshots are generated on the volume. ... To get the absolute volume consumption, including the capacity used by snapshots, use the Azure NetApp Metrics" [문서 D4]. `du`는 스냅샷 공간을 세지 않는다 [문서 D4]. 즉 ANF에서 "Volume Consumed Size"는 스냅샷을 포함하고, `df`의 used는 추정값이다.

### 1.6 출처끼리 다른 점

- 개념 문서 [D3]에는 "Volume Quota Size"가 따로 있지만, 정의 페이지 [D1]의 볼륨 표에는 없고 `VolumeAllocatedSize`만 있다.
- 개념 문서는 "Total throughput"을 두 번 다른 문장으로 적는다. 같은 메트릭으로 본다 [추론].

---

## 2. ONTAP에서는

### 2.1 볼륨의 `metric.*`와 `statistics.*_raw`

- ONTAP REST 볼륨에는 성능 필드가 두 모양으로 있다. "The `metric.*` fields denote an average whereas `statistics.*` fields denote a real-time monotonically increasing value aggregated across all nodes." [ONTAP O1]
  - `metric.{iops,throughput,latency}.{read,write,other,total}`, `metric.duration`(`PT15S`, `PT4M`, `PT5M`, `PT30M`, `PT2H`, `P1D`), `metric.status`, `metric.timestamp`. "other"는 "metadata operations, such as directory lookups"다 [ONTAP].
  - `statistics.{iops_raw,throughput_raw,latency_raw}.{read,write,other,total}`, `statistics.nfs_ops_raw`, `statistics.timestamp` 등. 누적 카운터다 [ONTAP].
- 단위: IOPS는 초당 연산 수, 처리량은 bytes/s, 지연은 IOP당 평균 응답 시간으로 **마이크로초**다(ANF는 밀리초). 시간 범위를 주지 않으면 "statistics collected at 15 second intervals over the last hour"를 돌려준다(애그리거트 메트릭 API 설명) [ONTAP]. 볼륨 `/api/storage/volumes/{uuid}/metrics`도 같은 모양이라고 본다 [추론].
- 공간: `space.size`, `space.used`("before storage efficiency"), `space.available`, `space.percent_used`, `space.logical_space.used`, `space.logical_space.used_by_snapshots`, `space.snapshot.used`, `space.footprint`("Data used for this volume in the aggregate")가 있다. inode는 `files.maximum`, `files.used`다 [ONTAP].

**면접 포인트.** ONTAP은 같은 값을 "평균"(`metric.*`)과 "누적 카운터"(`statistics.*_raw`) 두 모양으로 준다. 이 클론은 카운터 쪽을 골랐다. agent는 누적 카운터를 내고 평균은 쿼리(PromQL `rate()`)가 만든다(결정 2). 이 대응은 [추론]이다.

### 2.2 ANF ↔ ONTAP 대응

| ANF 메트릭 | 가장 가까운 ONTAP 필드 | 근거 |
| --- | --- | --- |
| Read/Write/Other/Total iops | `metric.iops.*` / `statistics.iops_raw.*` | 필드 [ONTAP], 대응 [추론: 이름·분류가 같다] |
| Read/Write/Other/Total throughput | `metric.throughput.*` / `statistics.throughput_raw.*` | 필드 [ONTAP], 대응 [추론] |
| Average read/write/other latency (ms) | `metric.latency.*` (µs) / `latency_raw ÷ iops_raw` | 필드·단위 [ONTAP], Harvest 계산법 [문서 H1], 대응 [추론] |
| Volume allocated size | `space.size` | [추론] |
| Volume Consumed Size (스냅샷 포함) | `space.logical_space.used` 또는 `space.used` | 이름의 "Logical"만 근거 [추론]. 어느 것인지 [미확인] |
| Volume snapshot size | `space.snapshot.used` 또는 `space.logical_space.used_by_snapshots` | [추론] |
| Volume Inodes Used / Total | `files.used` / `files.maximum` | [추론] |
| Throughput limit reached, QoS latency delta | QoS 지연 분해의 throttle 성분 | 이름에서 [추론]. ONTAP 원문 [미확인]. `/api/storage/qos/workloads`에는 정책·상한 필드만 보였다 [ONTAP] |
| 풀 메트릭 | 직접 대응 없음(볼륨 값의 합) | 풀은 ONTAP 객체가 아니다 [추론] |

- 간접 단서: ANF cache 볼륨 메트릭 "Cache volume miss blocks", "Client requested blocks"[D3]와 ONTAP 볼륨 `statistics.flexcache_raw.cache_miss_blocks`, `client_requested_blocks`[O1]는 이름이 같다. ANF가 ONTAP 카운터를 이름만 바꿔 내보낸다는 가설을 지지하지만 증명은 아니다 [추론].
- **면접에서 안전한 문장** (브리프): "ANF 볼륨 메트릭은 read/write/other/total × IOPS·throughput·latency로 나뉘는데, ONTAP REST 볼륨의 `metric`/`statistics` 필드가 같은 구조다. ANF가 내부에서 그 카운터를 쓰는지는 공개되지 않았다. NetApp Harvest는 ONTAP의 같은 필드를 Prometheus로 내보낸다."

### 2.3 선례: NetApp Harvest

- Harvest는 NetApp 공식 오픈소스로, ONTAP 값을 Prometheus로 내보낸다 [문서 H1]. 예:
  - `volume_read_ops` ← `statistics.iops_raw.read` (단위 per_sec, type rate)
  - `volume_read_data` ← `statistics.throughput_raw.read` (b_per_sec, rate)
  - `volume_read_latency` ← `statistics.latency_raw.read` (microsec, average, base `iops_raw.read`)
  - `volume_size_used`, `volume_size_used_percent`, `volume_snapshots_size_used`, `volume_inode_files_used`, `qos_ops`, `qos_latency`
- Harvest는 원시 카운터를 수집기에서 비율로 바꿔 gauge로 내보내는 것으로 보인다("Type: rate") [추론]. 그래서 Prometheus 관례(기본 단위 `_bytes`·`_seconds`, 누적은 `_total`)와 이름이 다르다.
- 클론은 Harvest 이름을 따르지 않고 Prometheus 관례를 따랐다(결정 1). Harvest는 "NetApp도 같은 ONTAP 카운터를 Prometheus로 낸다"는 선례로만 쓴다.

### 2.4 Prometheus 관례

- 이름: 단일 단어 애플리케이션 접두사, 한 메트릭에 한 단위·한 양, **기본 단위**(초, 바이트), 복수형 단위 접미사, 누적 카운트는 `_total`이다. 같은 메트릭의 라벨 값들은 같은 논리적 대상을 재야 한다 [문서 P1].
- counter vs gauge: 내려갈 수 있는 값(사용량, 진행 중 작업 수)은 gauge, 증가만 하는 값(바이트, 연산 수, 요청 수)은 counter로 두고 `rate()`로 초당 값을 만든다 [문서 P2]. 히스토그램은 [문서 P3].
- Azure Monitor 이름과 Prometheus 이름 사이의 공식 대응 규칙은 찾지 못했다 [미확인]. 그래서 이 문서 3절의 대응표가 그 역할을 한다.
- Azure의 "5분 평균 bytes/s"는 Prometheus에서 바이트 카운터에 `rate(x_total[5m])`를 한 값과 같은 뜻이다 [추론].

### 2.5 클론 agent와 ONTAP REST

storage agent는 ONTAP REST 부분집합을 제공한다(D-06). 그러나 메트릭은 ONTAP 볼륨의 `metric`/`statistics` 필드로 내지 않고 Prometheus 텍스트 형식의 `GET /metrics`로 낸다. ADR §8이 "두 프로세스가 각자 `/metrics`를 낸다"로 정해 두었고, Prometheus는 이 형식을 직접 긁기 때문이다 [추론: ONTAP 모양으로 내는 안은 설계 기록에 버린 대안으로 적혀 있지 않다].

---

## 3. 이 프로젝트에서는

### 구조

```
클라이언트 컨테이너 (fio) ──NFS──▶ 볼륨 인스턴스 anf-nfs-<uuid32> (자기 netns, knfsd)
                                     └ /proc/<pid>/net/rpc/nfsd : io, rpc, proc4ops (netns별)

storage agent (root, 127.0.0.1:8090)  GET /metrics → VolumeCollector.collect()
  ├ FlexVolManager.inventory()     lvs 태그(uuid, 경로, 프로토콜, anf_qos, 스냅샷 LV) + findmnt
  ├ statvfs(ns/<creationToken>)     크기, used, inode            (마운트됐을 때만)
  ├ Docker API 소켓                 인스턴스 pid                  (떠 있을 때만)
  ├ /proc/<pid>/net/rpc/nfsd        읽기·쓰기 바이트, 요청 수, v4.1 READ/WRITE 연산 수
  └ dmsetup status anf-aggr0-tpool  aggregate 데이터·메타데이터 사용량

anf-api (127.0.0.1:8080)              GET /metrics → ApiMetrics
  ├ 요청 미들웨어                    method, route(경로 템플릿), status, 지연
  └ LRO 워커                         작업 수·소요 시간(종류, 결과), 진행 중 작업 수

            ▲ 5 s마다 pull
Prometheus  컨테이너 anf-prometheus (prom/prometheus:v3.15.1, host 네트워크, 127.0.0.1:9090)
            ▲ /api/v1/query_range (최근 5분, step 5 s, 5 s마다)
Vite 프록시 /prometheus/... → 127.0.0.1:9090/...
            ▲
대시보드     볼륨을 고르면 처리량·IOPS·사용량 차트, 아래에 anf-api 차트
```

- agent의 값은 **스크레이프 때 읽는다**. 백그라운드 수집 스레드가 없다. 읽기만 하고 tc·export·LVM 상태를 바꾸지 않는다(결정 8).
- 대시보드는 Prometheus 쿼리 API만 읽는다(D-08). agent나 anf-api의 `/metrics`를 직접 읽지 않는다.

### 메트릭 목록과 Azure 이름 대응

**storage agent** (볼륨 라벨 `volume_uuid`, `creation_token`, `protocol`(`nfs3`|`nfs4.1`))

| 클론 메트릭 | 종류 | 출처 | ANF (Azure Monitor REST 이름) | 같음/다름 |
| --- | --- | --- | --- | --- |
| `anf_volume_size_bytes` | gauge | `statvfs` 전체 크기 | `VolumeAllocatedSize` | 근사. ANF는 프로비전 크기, 클론은 ext4 크기라 ext4 오버헤드만큼 작다(4 GiB 볼륨이 4,143,677,440 B [클론 측정 S8 Q5]) |
| `anf_volume_used_bytes` | gauge | `statvfs` 사용량 | `VolumeLogicalSize` | **다르다.** ANF는 스냅샷 포함, 클론은 활성 파일시스템만(클라이언트 `df`와 같다) |
| `anf_volume_inodes`, `anf_volume_inodes_used` | gauge | `statvfs` | `VolumeInodesTotal`, `VolumeInodesUsed` | 같은 뜻 |
| `anf_volume_snapshots` | gauge | 스냅샷 LV 수 | 볼륨 메트릭 표에는 없다 | 클론 고유 |
| `anf_volume_read_bytes_total`, `anf_volume_write_bytes_total` | counter | knfsd `io` 줄 | `ReadThroughput`, `WriteThroughput` (`rate()`를 씌운 값) | 데이터 바이트만. 헤더와 메타데이터(Other) 바이트는 없다 |
| `anf_volume_nfs_requests_total` | counter | knfsd `rpc` 줄의 호출 수 | `TotalIops` | v3는 프로시저 호출 수(NFSACL 포함), v4.1은 COMPOUND 수 |
| `anf_volume_nfs_operations_total{op="read"\|"write"}` | counter | knfsd `proc4ops`의 READ·WRITE | `ReadIops`, `WriteIops` | **NFSv4.1 볼륨만** |
| `anf_volume_throughput_limit_bytes_per_second` | gauge | LVM 태그 `anf_qos` × 1,048,576 | 메트릭이 아니라 ARM `actualThroughputMibps` | 풀 메트릭 `VolumePoolAllocatedToVolumeThroughput`의 볼륨 몫 |
| `anf_aggregate_data_used_bytes`, `…_data_size_bytes`, `…_metadata_used_bytes`, `…_metadata_size_bytes` | gauge | `dmsetup status`의 thin 풀 줄 | 없음 | 클론 고유(R-09). ONTAP aggregate 사용률에 해당 [추론] |
| `anf_agent_scrape_duration_seconds`, `anf_agent_scrape_errors_total` | gauge, counter | 수집기 자신 | 없음 | 운영용 |

**anf-api**

| 메트릭 | 종류 | 라벨 |
| --- | --- | --- |
| `anf_api_http_requests_total` | counter | `method`, `route`(경로 템플릿), `status` |
| `anf_api_http_request_duration_seconds` | histogram | `method`, `route` (라이브러리 기본 버킷) |
| `anf_api_operations_total` | counter | `resource_type`, `action`, `result`(`Succeeded`\|`Failed`) |
| `anf_api_operation_duration_seconds` | histogram | `resource_type`, `action`, `result` (버킷 0.1~600 s) |
| `anf_api_operations_in_progress` | gauge | `resource_type`, `action` |

브리프가 본 ANF 볼륨·풀 메트릭 표 [D1][D2]에는 API 요청이나 작업 지표가 없다. 이 지표는 클론 컨트롤 플레인을 운영하기 위한 것이다.

**내지 않는 것** (설계 §2.3): 지연 3종, `ThroughputLimitReached`, `QosLatencyDelta`, `VolumeSnapshotSize`, `VolumeConsumedSizePercentage`(used ÷ size로 계산할 수는 있다), `OtherThroughput`·`OtherIops`, 풀 수준 ANF 메트릭, v3 볼륨의 읽기·쓰기 연산 수.

### 코드 따라가기

#### (1) agent: `/metrics` 라우트 — `agent_app.py:236-243`

- 앱마다 `CollectorRegistry`를 따로 두고 `VolumeCollector(manager)`를 등록한다(`:238-239`). 전역 레지스트리를 쓰면 테스트가 앱을 다시 만들 때 메트릭 이름이 겹친다(`:237` 주석).
- `GET /metrics`는 `generate_latest(registry)`를 Prometheus 텍스트 형식(`CONTENT_TYPE_LATEST`)으로 돌려준다(`:241-243`).
- **job 표를 거치지 않는다**(`:236` 주석). agent의 job 표는 한 번에 job 하나라서, 스크레이프가 그 줄에 서면 볼륨 생성 job이 도는 동안 메트릭이 멈춘다. 단위 테스트 `test_agent_app.py:533`(`test_metrics_scrape_does_not_wait_for_a_running_job`)가 이것을 본다.

#### (2) agent: 수집기 — `volume_metrics.VolumeCollector.collect`, `volume_metrics.py:84-171`

`prometheus_client`의 사용자 정의 collector다. 레지스트리가 스크레이프마다 `collect()`를 부른다(결정 10).

1. 메트릭 패밀리를 만든다(`:108-118`). 볼륨 계열은 모두 `LABELS = ["volume_uuid", "creation_token", "protocol"]`(`:31`)을 쓰고, 연산 수만 `op` 라벨을 더한다.
2. `manager.inventory()`로 볼륨 목록을 얻는다(`:121-125`). 실패하면 오류 하나를 세고 빈 목록으로 계속한다. aggregate 값은 그래도 나온다(`test_volume_metrics.py:170`).
3. 볼륨마다(`:126-149`):
   - **태그에서 나오는 값은 늘 낸다**: 스냅샷 수, 한도가 있으면 한도 × `MIB`(`:128-130`).
   - **마운트돼 있으면** `statvfs`로 크기 `f_blocks × f_frsize`, used `(f_blocks − f_bfree) × f_frsize`, inode를 낸다(`:132-137`). used의 식이 `df`와 같아서 클라이언트 `df`와 맞는다.
   - **인스턴스가 떠 있으면**(`pid`가 있으면) `/proc/<pid>/net/rpc/nfsd`를 읽어 바이트·요청 수를 내고(`:138-143`), `protocol == "nfs4.1"`일 때만 READ·WRITE 연산 수를 낸다(`:144-146`). v3 볼륨에 `proc4ops`의 0을 내면 "연산이 없다"로 읽힐 것이다 [추론].
   - 한 볼륨에서 예외가 나면 경고 한 줄을 남기고 오류 하나를 센 뒤 다음 볼륨으로 간다(`:147-149`). 다른 볼륨의 값은 막지 않는다(`test_volume_metrics.py:154`).
4. aggregate: `manager.aggregate_usage()`의 네 값을 라벨 없는 gauge로 낸다(`:151-163`). 실패해도 볼륨 값은 나온다(`test_volume_metrics.py:179`).
5. 오류 수는 수집기 인스턴스에 누적해 counter로 낸다. `/metrics`가 동기 함수라 스레드에서 돌고 스크레이프가 겹칠 수 있어서 잠금 아래 더한다(`:97`, `:165-167`). 마지막에 이번 스크레이프의 소요 시간 gauge와 오류 counter를 낸다(`:168-171`).

- 인스턴스가 내려가 있는 것은 오류가 아니다. pid가 `None`이면 knfsd 계열만 빠진다(`:139`). e2e AC-09가 그동안 오류 counter가 그대로인지 본다(`test_metrics_data_live.py:268`).

#### (3) agent: `/proc/<pid>/net/rpc/nfsd` 파싱 — `parse_nfsd`, `volume_metrics.py:36-49`

- 줄마다 첫 단어를 키로 한 사전을 만든다(`:46`). 그래서 실제 파일에 있는 `ra` 줄 같은 다른 줄은 상관없다(설계 §7).
- `io`: 두 값이 읽기 바이트와 쓰기 바이트다(`:47`).
- `rpc`: 첫 값이 호출 수다(`:49`).
- `proc4ops`: **첫 값은 연산 개수(76)라서 건너뛴다**(`:48`). 그 뒤의 배열에서 READ = 25, WRITE = 38이다(`OP_READ`, `OP_WRITE`, `:32`, RFC 8881 §16.2 번호).
- **`proc3`·`proc4` 줄은 읽지 않는다.** 모든 netns의 합이기 때문이다(3.1절).
- 설계는 이 형식을 정하지 않았다. 구현자가 실제 파일을 보고 `ra` 줄과 `proc4ops`의 개수 칸을 찾아 파서와 단위 테스트 입력(`test_volume_metrics.py:50`)을 맞췄다(설계 §7).

#### (4) agent: 인스턴스 pid — `docker_pid`, `volume_metrics.py:52-81`

- Docker Engine API 유닉스 소켓(`/var/run/docker.sock`)에 `GET /containers/<이름>/json`을 보내고 `State.Pid`를 읽는다(`:68-81`). `http.client.HTTPConnection`의 `connect`만 유닉스 소켓으로 바꿨다(`:52-65`). 표준 라이브러리만 쓴다.
- `404`이거나 `Pid`가 0이면 "인스턴스 없음"(`None`)이고, 그 밖의 상태는 예외라서 그 볼륨만 실패로 센다(`:77-81`, `test_volume_metrics.py:199-216`).
- **스크레이프마다 새로 연결한다**(설계 §7). 연결을 들고 있지 않아서 Docker가 다시 떠도 수집기에 남는 상태가 없다.
- 왜 CLI가 아닌가: S8에서 `docker inspect` CLI는 호출마다 약 150 ms였고, 소켓 API는 볼륨 둘에 1.73 ms였다 [클론 측정 S8 Q6]. agent의 다른 코드(`nfs_instance._pid`)는 지금도 CLI를 쓴다. job 안에서 한 번 부르는 것과 스크레이프마다 볼륨 수만큼 부르는 것은 다르다.

#### (5) agent: 볼륨 목록과 aggregate — `flexvol.py:113-133`, `:314-333`

- `VolumeInfo`(`:113-123`)는 수집기가 보는 볼륨이다. `mountpoint`는 **마운트됐을 때만** 있다. 마운트되지 않은 마운트 지점에 `statvfs`를 하면 그 아래 호스트 파일시스템의 값이 나오기 때문이다(`:115-116` 주석).
- `inventory`(`:314-323`)는 기존 `_report`(`lvs` JSON으로 태그 읽기, `:566-603`)와 `_mounted`(`findmnt`, `:632-633`)를 그대로 쓴다. 스냅샷 수는 스냅샷 LV의 `anf_snap_vol` 태그로 센다. LVM 태그가 진실의 근원이라는 agent의 원칙(DB 없음)을 따른다.
- `aggregate_usage`(`:325-333`)는 `dmsetup status anf-aggr0-tpool` 한 줄을 읽는다. 형식은 `0 <섹터> thin-pool <tid> <메타 사용>/<메타 전체> <데이터 사용>/<데이터 전체> …`다.
  - 데이터 블록 크기 = 장치 크기(섹터 × 512) ÷ 데이터 블록 총수다. 이 기기에서는 512 KiB다(S8 환경).
  - 메타데이터 블록은 4,096 B로 고정한다(`METADATA_BLOCK`, `:38`). 커널 상수라 풀 크기와 무관하다(설계 §7).
  - `lvs -o data_percent`를 쓰지 않은 이유: 소수 둘째 자리 백분율이라 1 TiB 풀에서 512 MiB가 0.05로만 보였고, 55 ms로 `dmsetup`(5.6 ms)보다 느렸다 [클론 측정 S8 Q5·Q6].
  - `anf-aggr0-tpool` 장치는 thin LV가 하나도 없어도 있다(설계 §7).

#### (6) anf-api: 지표 객체 — `api_metrics.ApiMetrics`, `api_metrics.py:21-60`

- 앱마다 `CollectorRegistry`를 하나 만들고 counter·histogram·gauge 다섯 개를 등록한다(`:22-36`).
- 작업 소요 시간 버킷은 0.1~600 s다(`OPERATION_BUCKETS`, `:17-18`). 계정·풀 작업은 1초 미만이고, 볼륨 작업은 인스턴스 준비와 NFSv4 유예 기간(45 s) 때문에 수십 초가 걸린다.
- `observe_request`(`:38-40`): 요청 counter와 지연 histogram.
- `declare_operation`(`:42-44`): 진행 중 gauge의 계열을 값 0으로 미리 만든다. 작업이 한 번도 없던 종류도 계열이 있어서, 대시보드의 `sum(...)`이 처음부터 0을 그린다(설계 §7).
- `operation_started` / `operation_stopped`(`:46-50`): gauge를 올리고 내린다.
- `operation_finished`(`:52-57`): 작업 행의 `start_time`(DB에 저장된 UTC 문자열, `:16`)부터 지금까지를 재고, **음수면 0으로 자른다**(`:55`). 그다음 작업 counter와 소요 시간 histogram에 한 건씩 넣는다.
- 값은 프로세스 메모리에 있다. anf-api가 다시 뜨면 0부터 센다(`:6` 주석). 그 리셋은 Prometheus `rate()`가 처리한다.

#### (7) anf-api: 요청 미들웨어 — `arm_app.py:119-120`, `:150-169`

- `ApiMetrics()`를 하나 만들어 LRO 워커에 넘긴다(`:119-120`). 미들웨어와 워커가 같은 객체에 쓴다.
- `count_requests`(`:150-165`):
  - `/metrics` 자신은 세지 않는다(`:154-155`). 세면 5 s마다 오는 스크레이프가 요청률에 섞인다 [추론: 설계는 이유를 적지 않았다].
  - `route`는 라우터가 고른 경로 템플릿(`request.scope["route"].path`)이다. 맞는 경로가 없으면 `"unmatched"` 하나로 모은다(`:163-164`). 그래서 구독 ID와 리소스 이름이 라벨에 들어가지 않는다(`test_arm_app.py:371`).
  - 상태 코드의 기본값이 500이다(`:157`). 처리되지 않은 예외가 나면 `call_next`가 값을 돌려주지 않는데, 바깥 미들웨어가 그것을 500으로 응답하기 때문이다(설계 §7). `finally`에서 세므로 예외도 빠지지 않는다.
- `GET /metrics`(`:167-169`)는 OpenAPI 스키마에서 뺐다(`include_in_schema=False`). ARM API가 아니라서로 본다 [추론].

#### (8) anf-api: LRO 워커 계측 — `lro.py:30-32`, `:85-87`, `:125-132`, `:156-171`

- 라벨은 `_labels`(`:30-32`)로 만든다. 리소스 종류의 마지막 조각과 소문자 작업이라 `("volumes", "create")`이 된다. **결함 주입 키(`volumes/create`)와 같은 이름이다**(`_key`, `:35-36`). 운영자가 메트릭에서 본 이름으로 그대로 결함을 주입할 수 있다.
- 워커를 만들 때 등록된 처리기마다 `declare_operation`을 부른다(`:86-87`).
- `_process`(`:125-132`): 작업 태스크가 시작될 때 gauge를 올리고 `finally`에서 내린다. 그래서 anf-api가 멈추면서 태스크가 취소돼도 gauge가 내려간다.
- `_finish`(`:156-171`): 리소스와 작업의 끝 상태를 한 트랜잭션에 저장한 **뒤에** 작업 수와 소요 시간을 센다(`:169-171`). 순서가 중요한 이유는 3.9절에 있다.

#### (9) Prometheus — `deploy/prometheus/prometheus.yml`, `scripts/run-prometheus.sh`

- 설정(`prometheus.yml:4-13`): `scrape_interval: 5s`, job `anf-api`(127.0.0.1:8080), job `storage-agent`(127.0.0.1:8090). 5 s 간격이면 대시보드의 `rate(...[20s])` 창마다 표본이 4개 들어간다(`:3` 주석).
- 스크립트(`run-prometheus.sh`):
  - 이미 있는 `anf-prometheus`를 지운다(`:15`). `stop`이면 거기서 끝난다(`:16-18`).
  - `docker run --network host`로 띄우고, 설정 파일을 읽기 전용으로 붙인다. `--web.listen-address=127.0.0.1:9090`이라서 localhost에만 연다(`:20-23`). 이미지 기본 인자를 덮어쓰므로 `--config.file`과 `--storage.tsdb.path`도 함께 줘야 한다(S8 P2).
  - `/-/ready`를 0.2 s마다 최대 30 s 기다린다(`:25-33`).
- host 네트워크 + 127.0.0.1 바인드라서 컨테이너가 WSL 호스트 프로세스(8080, 8090)를 그대로 긁는다. Windows에서도 WSL의 localhost 전달로 `127.0.0.1:9090`에 닿는다 [클론 측정 S8 Q7 P3·P4]. D-13(localhost만, 인증 없음)과 맞는다.

#### (10) 대시보드 — `frontend/src/`

- **프록시** (`vite.config.ts:7-13`): `/prometheus/...` → `ANF_PROMETHEUS_URL`(기본 `http://127.0.0.1:9090`). 접두사 `/prometheus`를 떼고 넘긴다(`:11`). dev와 preview 모두에 붙는다(`:17-18`). 브라우저는 같은 출처만 부르므로 Prometheus에도 CORS 설정이 필요 없다(anf-api와 같은 방식).
- **쿼리 클라이언트** (`promClient.ts:17-34`): `/prometheus/api/v1/query_range?query&start&end&step`을 부른다. HTTP 오류와 `status != "success"`는 예외다(`:26`, `:28`). **값이 문자열로 온다**("1048576", "NaN")라서 숫자로 바꾼다(`:29-33`).
- **폴링** (`useMetrics.ts:24-59`): 이름 붙은 쿼리 묶음을 최근 5분(`RANGE_SECONDS`), step 5 s, 5 s마다 읽는다(`:4-6`).
  - 한 번의 읽기가 끝난 뒤에 다음 타이머를 건다(`:48`). 그래서 요청이 겹치지 않는다.
  - 실패하면 마지막 데이터를 두고 오류만 바꾼다(`:44-47`).
  - 쿼리가 바뀌거나 화면이 닫힌 뒤 도착한 응답은 `stopped` 표시로 버린다(`:32`, `:42`, `:52-55`).
  - 쿼리 객체는 `JSON.stringify`로 내용 비교한다(`:26`).
- **패널** (`MetricsPanels.tsx`):
  - `VolumeMetrics`(`:44-83`)의 쿼리(`:45-55`)는 3.11절에 있다. ARM 볼륨의 `creationToken`을 `creation_token` 라벨로 잇는다(결정 9).
  - `ApiMetrics`(`:86-102`): `sum by (status) (rate(anf_api_http_requests_total[20s]))`와 `sum(anf_api_operations_in_progress)`.
  - `Panel`(`:24-38`): 오류가 있으면 "Cannot read metrics … Showing the last successful read" 배너를 보이고, 마지막 차트를 그대로 둔다.
- **차트** (`LineChart.tsx:30-74`): 의존성 없는 SVG다(결정 12).
  - 세로축은 0부터 최댓값까지다. 축 눈금 대신 최댓값과 선마다 마지막 값을 숫자로 보인다.
  - Prometheus가 준 `NaN` 점은 그리지 않는다(`:32`).
  - 1 미만 값은 소수 셋째 자리로 보인다(`:21-23`). 0.062 MiB/s 같은 한도 때문이다.
  - 한도와 크기는 점선이다(`:54`).
- **선택** (`App.tsx:26-27`, `:59-66`; `ResourceTree.tsx:63`):
  - `Succeeded`이고 `creationToken`이 있는 볼륨만 누를 수 있다. 인스턴스가 없으면 계열도 없기 때문이다.
  - 고른 볼륨은 ID로 기억하고, 매번 최신 트리에서 다시 찾는다(`findResource`, `:13-20`). 지워지거나 구독이 바뀌면 패널이 닫힌다.
  - `key={selected.id}`라서 다른 볼륨을 고르면 패널을 새로 만든다.
  - API 패널은 트리를 한 번 읽은 뒤에만 보인다(`:66`, 설계 §7).
  - Prometheus가 없어도 위의 트리는 anf-api에서 계속 갱신된다(`:58` 주석).

### 핵심 설명 (면접에서 나올 것)

#### 3.1 볼륨별 카운터는 netns에서 나온다

- **전제.** D-12로 볼륨마다 knfsd 인스턴스가 자기 netns에서 돈다. 커널의 nfsd 통계 일부는 netns마다 따로 있다. 호스트의 root는 `/proc/<인스턴스 pid>/net/rpc/nfsd`로 그 netns의 파일을 바로 읽는다. `nsenter`나 `docker exec`가 필요 없다 [클론 측정 S8 Q1].
- **줄마다 범위가 다르다.** 브리프가 커널 소스에서 추론했고, S8이 실제 WSL 커널(`6.18.58.1-microsoft-standard-WSL2`)에서 볼륨 A(v3)·B(v4.1)와 호스트 netns의 파일을 함께 읽어 확인했다.

  | 줄 | 내용 | 범위 | 소스 근거 | 실측 [클론 측정 S8 Q1] |
  | --- | --- | --- | --- | --- |
  | `io` | 읽기 응답 바이트, 쓰기 요청 바이트 | netns별 | `struct nfsd_net`의 per-netns `counter[]` [스펙 K1, K2] | A에 256 MiB 쓰기: A +268,435,456, B·호스트 +0 |
  | `rpc` | 전체 RPC 호출 수 | netns별 | `nn->nfsd_svcstats` [스펙 K1, K9] | A 쓰기: A +260, B +1(v4.1 lease 갱신 SEQUENCE), 호스트 +0 |
  | `proc4ops` | NFSv4 연산별 수 | netns별 | `nn->counter[NFSD_STATS_NFS4_OP(i)]` [스펙 K2] | B 쓰기: B WRITE +256, A·호스트 0 |
  | `proc3`, `proc4` | 버전별 프로시저 수 | **전역** | `struct svc_version`의 per-cpu `vs_count`. nfsd의 버전 객체는 정적 배열 `nfsd_version[]`이다 [스펙 K10, K11]. 그래서 전역이다 [추론: 소스 구조] | A v3 쓰기: A·B·호스트 셋 다 WRITE +256. B v4.1 쓰기: A·B 모두 COMPOUND +260 |

- **결과.** NFSv4.1 볼륨은 `proc4ops`로 읽기·쓰기 연산 수를 볼륨별로 얻는다. NFSv3 볼륨은 볼륨별 전체 호출 수만 얻는다. `proc3`의 READ/WRITE를 볼륨 라벨로 내면 **모든 v3 볼륨의 합**이 된다. 그래서 v3 볼륨에는 그 계열을 내지 않는다(결정 5).
- **다른 길도 봤다** [클론 측정 S8 Q1]:
  - `export_stats`(nfsd 파일시스템, export별 `io_read`·`io_write`)는 netns별이지만 바이트만 있고 연산 수가 없다. 게다가 `exportfs -ra`·`-f` 뒤에 항목이 모두 사라졌다가 0부터 다시 생긴다. agent는 스냅샷을 만들거나 지울 때 `-ra`, 되돌리기 창에서 `-f`를 하므로 그때마다 초기화된다.
  - `rc` 줄(응답 캐시 hits/misses/nocache)은 per-cpu라 정확하고 v3에서 misses = 변경 연산, nocache = 그 밖으로 나뉜다. 데이터 부하에서는 쓰기·읽기 연산 수와 맞는다. 하지만 파일 200개를 만들고 지우면 WRITE는 200인데 misses는 602였다(CREATE·REMOVE 포함). 설명하기 어려운 근사라서 버렸다(결정 5).
- 인스턴스 pid가 바뀌면(다시 뜨면) 새 netns라서 카운터가 0부터 시작한다(3.4절).

#### 3.2 처리량 출처: 왜 knfsd `io`인가

같은 fio 실행의 증가량을 fio가 보고한 바이트로 나눈 비율이다 [클론 측정 S8 Q2, 한도 32 MiB/s 볼륨].

| 출처 | 방향 | 1 MiB 순차 | 4 KiB 임의 | 비고 |
| --- | --- | --- | --- | --- |
| knfsd `io` | 읽기·쓰기 나뉨 | 1.0000 | 1.0000 | 바이트 단위로 일치. 서버 페이지 캐시에서 나간 읽기도 센다(warm 읽기: 디스크 읽기 0, `io` 268,435,456) |
| `eth0` 수신/송신 | 나뉨 | 1.0016~1.0038 | 1.044~1.098 | 헤더 포함. 반대 방향에도 응답·ACK가 0.1~0.2%(1 MiB), 4.8~8.8%(4 KiB) 흐른다. 쓰기만 해도 "읽기"가 0이 아니게 보인다 |
| `ifb0` 송신 | **합만** | 1.0027~1.0036 | 1.12~1.15 | 처리량 제한의 IFB. 방향을 나누지 못한다 |
| HTB `Sent` | **합만** | 1.047~1.050 | 1.15~1.16 | 한도가 이 값에 걸린다. `nsenter tc`가 필요하다 |
| thin LV 디스크 | — | 쓰기 1.01 | 쓰기 2.35~2.50 | 저널·메타데이터 쓰기가 섞인다 [추정]. 캐시 읽기는 0 |

- `io`는 "READ 응답으로 돌려준 바이트"와 "WRITE 요청으로 받은 바이트"다 [스펙 K1, K2]. 그래서 서버 캐시 적중과 무관하게 클라이언트가 받은 데이터를 센다. ANF 처리량 정의("between Azure NetApp Files and the client")와 같은 방향이다 [추론].
- [처리량 제한 문서](throughput-limit.md) 3.10절과 Q9는 FR-12 전에 `ifb0` 송신을 "볼륨 처리량" 후보로 적었다. S8이 `io`가 방향을 나누고 fio와 정확히 같음을 보여서 `io`로 정했다(결정 3, ADR §8).
- **ANF와 다른 점.** ANF Total은 read + write + other이고 "across the wire"다 [문서 D3]. 클론의 `io`에는 메타데이터(Other) 바이트도 헤더도 없다. 그래서 `OtherThroughput`·`TotalThroughput`을 내지 않고, 대시보드는 읽기·쓰기 선만 그린다.
- 한도와 비교할 때 단위가 맞는다. 볼륨 한도(`throughputMibps`)는 데이터 기준이고, tc는 그것을 ÷0.9564로 wire 기준으로 바꿔 건다(FR-08). `io`도 데이터 기준이라서 차트의 한도 선과 처리량 선을 그대로 비교할 수 있다. e2e에서 포화 쓰기의 안정 구간이 한도의 99.33%(10 MiB/s)·99.0%(20 MiB/s)였다 [클론 측정, 구현자 e2e AC-06].

#### 3.3 IOPS: 요청 수와 연산 수

- **`anf_volume_nfs_requests_total` = `rpc` 줄의 호출 수**(결정 4).
  - v3에서는 프로시저 호출 수다. NFSACL 호출도 들어간다. 파일 200개 만들기·`ls -l`·지우기에서 `rpc`는 810, `proc3` 합은 608이었다. 차이 202는 `ls -l`이 파일마다 ACL을 묻는 GETACL로 본다 [추정 S8 Q1].
  - v4.1에서는 COMPOUND 수다. `proc4ops`를 모두 더하지 않은 이유: COMPOUND 하나에 SEQUENCE + PUTFH + READ가 들어가서 합이 약 3배가 된다(4 KiB 임의 읽기: 합 183,753 대 COMPOUND 61,249) [클론 측정 S8 Q3].
- **`anf_volume_nfs_operations_total{op}` = `proc4ops`의 READ·WRITE**, v4.1만.
  - 서버가 받은 READ/WRITE 연산 수와 정확히 같았다. 클라이언트 mountstats와 1의 자리까지 같았다(61,245 = 61,245).
  - fio 연산 수와는 블록이 rsize/wsize(1 MiB) 이하일 때만 같다. fio 4 MiB 읽기 64회는 1 MiB 넷으로 쪼개져 READ 256이 됐다. **서버가 세는 것은 wire 연산이다** [클론 측정 S8 Q3]. ANF도 서버 쪽에서 센다면 같은 성질일 것이다 [추론].
- **`rpc` 줄의 두 가지 주의점** [클론 측정 S8 Q1·Q3].
  - 필드가 32비트 `unsigned int`라 2^32에서 돈다 [스펙 K1, K9]. 6,124 IOPS로 약 8일이다(계산). Prometheus에는 리셋처럼 보인다 [추론].
  - 4 KiB 고부하에서 다른 카운터보다 1~13(0.01~0.02%) 적었다. 필드 증가가 원자적이지 않아 동시 증가를 잃는 것으로 본다 [추정. 증가 위치(`net/sunrpc/svc.c`)는 확인하지 못했다]. per-cpu인 `rc`·`proc4ops`는 정확했다.
  - 이 때문에 e2e AC-05는 v4.1을 `proc4ops` READ로 판정하고(± 2%), v3 부하는 iodepth 1로 건다(`test_metrics_data_live.py:108-112`). 구현자 실행에서도 v4.1 `requests`가 fio보다 15 적었다(48,468 대 48,483)(설계 §7).
- ANF가 v4.1 IOPS를 COMPOUND 단위로 세는지 연산 단위로 세는지는 [미확인]이다.

#### 3.4 counter + `rate()`와 카운터 리셋

- **종류.** 증가만 하는 값은 counter다. 바이트, 요청 수, 연산 수, 수집 오류 수, API 요청 수, 작업 수가 여기에 든다. 내려갈 수 있는 값은 gauge다. 크기, used, inode, 스냅샷 수, 한도, aggregate, 스크레이프 시간, 진행 중 작업 수가 여기에 든다. 지연 분포는 histogram이다 [문서 P2].
- **왜 원시 카운터인가** (결정 2).
  - 평균 창을 쿼리가 정한다. 대시보드는 20 s 창을 쓰고, 같은 데이터에 `rate(...[5m])`를 쓰면 ANF와 같은 5분 평균이 된다 [추론].
  - agent에 상태가 없다. 5분 평균 gauge를 agent가 계산하려면 이전 값과 타이머를 들고 있어야 하고, 창이 고정되며, 리셋 처리도 직접 해야 한다.
- **리셋이 생기는 때.** 볼륨 인스턴스가 다시 뜨면 새 netns가 생겨서 카운터가 0부터 시작한다. 일반 재시작, 되돌리기의 재시작 경로, 시작 복구가 모두 해당한다(설계 §2.1). S8에서 `docker restart`(0.8 s) 뒤 pid가 1058 → 8090으로 바뀌었고, `io 1063170048 1634509200` → `io 0 0`, `rpc 69942` → `rpc 0`이 됐다 [클론 측정 S8 Q1]. anf-api가 다시 뜨면 그 메모리 counter도 0부터다(`api_metrics.py:6`).
- **보정하지 않는다.** Prometheus의 `rate()`가 카운터 리셋을 처리한다. 잃는 것은 리셋 직전 마지막 스크레이프 뒤의 증가분 일부뿐이다(S8 "설계에 주는 선택지").
- **e2e로 확인했다** (AC-09, `test_metrics_data_live.py:214-274`). 인스턴스를 `docker rm -f`로 지우고 같은 볼륨 PUT으로 다시 띄웠다. 쓰기 카운터가 64 MiB → 0 → 32 MiB로 다시 시작했고 같은 라벨의 계열 하나로 이어졌으며, `rate()`의 최솟값이 0 이상이었다(설계 §7, 테스트 단언 `:270-273`).
- 인스턴스가 내려간 동안 `/metrics`는 `200`이다. 그 볼륨은 사용량·한도·스냅샷 계열만 남고, 다른 볼륨의 값은 그대로 나온다(`:265-268`). 볼륨을 지우면 다음 스크레이프부터 계열이 없고, Prometheus 즉시 쿼리에서도 사라진다(`:247-252`, `:274`).

#### 3.5 라벨과 카디널리티

- **agent.** 볼륨 계열의 라벨은 `volume_uuid`, `creation_token`, `protocol` 셋이다. 값의 수가 볼륨 수에 비례할 뿐이다. 연산 수는 `op`이 `read`·`write` 둘이라 볼륨당 두 배다.
- **ARM 이름은 붙이지 않는다**(결정 9). agent는 ONTAP 쪽 계층이라 ARM을 모른다. LVM 태그에는 uuid·경로·IP·프로토콜·한도만 있다. 대시보드가 ARM 볼륨의 `creationToken`으로 잇는다. agent 하나 안에서는 경로가 유일하다.
  - 볼륨을 지우고 같은 경로로 다시 만들면 `volume_uuid`가 다른 두 계열이 5분 창 안에 겹친다. 그래서 대시보드 쿼리를 `sum(...)`으로 감싼다(설계 §7). 볼륨당 계열이 하나인 평소에는 값이 같다.
  - 버린 안: anf-api가 info 메트릭으로 uuid ↔ ARM 이름을 냄(이번 차트에는 필요 없다).
- **anf-api.** `route`는 실제 URL이 아니라 경로 템플릿이다. 맞는 경로가 없으면 `unmatched` 하나다(ADR §8, 3절 코드 (7)). 실제 URL을 라벨로 쓰면 계정·풀·볼륨이 생길 때마다 새 계열이 생기고, 아무 경로나 두드리는 스캐너가 시계열을 무한히 늘릴 수 있다 [추론].
- 작업 라벨 `resource_type`·`action`은 등록된 처리기 키에서만 나오고, `result`는 `Succeeded`·`Failed` 둘이다. 요청 지연 histogram에는 `status`를 넣지 않았다(설계 §2.2). 버킷 수만큼 계열이 곱해지기 때문이다 [추론].

#### 3.6 pull 모델: 스크레이프 때 읽기

- Prometheus가 5 s마다 `/metrics`를 부르면 그때 읽는다(결정 8). 버린 안은 백그라운드 주기 수집이다. 상태와 스레드가 늘어난다.
- **한 번의 스크레이프가 하는 일**: `lvs` JSON과 `findmnt` 한 번(볼륨 목록), 볼륨마다 `statvfs`와 Docker API 호출 하나와 `/proc` 파일 하나, `dmsetup status` 한 번. **`nsenter`·`tc`는 부르지 않는다.** `overlimits`나 HTB `Sent`를 내지 않기로 했으므로 필요 없다.
- **비용** [클론 측정 S8 Q6, 볼륨 둘, 30회 중앙값]:

  | 출처 | 시간 |
  | --- | --- |
  | `docker inspect` CLI, 볼륨마다 (×2) | 304.8 ms |
  | Docker API 소켓 (×2) | 1.73 ms |
  | `/proc/<pid>/net/rpc/nfsd` (×2) | 0.05 ms |
  | `nsenter tc -s class show` (×2) | 4.08 ms |
  | `statvfs` (×2) | < 0.01 ms |
  | `lvs` JSON (한 번) | 55.3 ms |
  | `dmsetup status` (한 번) | 5.64 ms |

  S8의 임시 exporter(Docker API + `/proc` + tc + `statvfs`, `lvs` 없음)는 스크레이프마다 평균 6.9 ms, 최대 9.4 ms였다. 제품 수집기는 볼륨 목록 때문에 스크레이프마다 `lvs`와 `findmnt`를 부른다. 그래서 구현자 e2e의 스크레이프 최대 0.153 s(AC-11)는 주로 그 몫으로 본다 [추론: 원인을 따로 재지 않았다].
- **방해하지 않는다는 근거.**
  1. 읽기 전용 명령과 파일만 쓴다. tc·export·LVM 상태를 바꾸지 않는다(`volume_metrics.py:3` 독스트링).
  2. `/metrics`가 agent의 job 표를 거치지 않는다(코드 (1)).
  3. 실측(AC-11, `test_metrics_data_live.py:314-347`): 1 s 간격으로 agent `/metrics`를 긁는 동안 10 MiB/s 볼륨의 한도를 재고 다른 볼륨을 만들었다. 구현자 실행에서 스크레이프 98번이 모두 `200`이었고 가장 느린 것이 0.153 s였다(기준 0.5 s) [클론 측정].
- **실패 격리.** 볼륨 하나, 볼륨 목록, aggregate가 각각 따로 실패한다(코드 (2)). 실패는 로그 한 줄과 `anf_agent_scrape_errors_total` 증가로 보인다.

#### 3.7 사용량, 스냅샷, aggregate

- **세 값이 다르다** [클론 측정 S8 Q5, v4.1 4 GiB 볼륨].

  | 단계 | `statvfs` used | 클라이언트 `df` used | thin LV 매핑 | 풀 사용 블록(512 KiB) |
  | --- | --- | --- | --- | --- |
  | 시작 | 343,953,408 | 343,932,928 | 489,684,992 | 1,864 |
  | 새 파일 512 MiB | +536,870,912 | +536,870,912 | 1,026,555,904 | 2,888 |
  | 스냅샷 | 그대로 | 그대로 | 그대로 | 2,889 |
  | 같은 파일 덮어쓰기 | **그대로** | **그대로** | **그대로** | **3,932 (+1,043 = 521.5 MiB)** |
  | 파일 지움 | 343,957,504 | 343,932,928 | 그대로(1,026,555,904) | 3,932 |
  | 스냅샷 삭제 | 343,953,408 | 343,932,928 | 그대로 | 2,888 |

- **`statvfs` used = `df` used.** 차이는 20~28 KiB(0.01% 미만)였다. 그래서 볼륨 사용량은 이것이다(결정 7).
- **스냅샷 뒤 덮어쓰기는 풀만 키운다.** 덮어쓴 새 블록은 볼륨 LV에 매핑되고, 옛 블록은 스냅샷이 붙잡는다. 볼륨 쪽 값은 그대로이고 씬 풀이 쓴 만큼 는다. ADR R-09(스냅샷 공간은 풀에서 나간다)가 숫자로 보인 것이다. 그래서 스냅샷 공간은 `anf_aggregate_data_used_bytes`로 간접 관찰한다.
- **thin LV 매핑(`data_percent`)은 사용량이 아니다.** 볼륨을 `discard` 없이 마운트하므로 파일을 지워도 매핑이 줄지 않는다. 빈 볼륨에도 ext4 메타데이터·저널 몫이 있다. 결정 7에서 버렸다.
- **스냅샷 고유 크기(`VolumeSnapshotSize`)는 내지 못했다.** dm-thin 상태 줄에는 장치별 고유 블록 수가 없다. `thin_ls`(메타데이터 스냅샷 필요)가 보여 준다고 알려져 있지만 원문을 확인하지 못했다 [미확인].
- e2e AC-10(`test_metrics_data_live.py:280-308`): 256 MiB 파일을 쓰고 스냅샷을 찍은 뒤 같은 파일을 덮어썼다. aggregate 증가가 덮어쓴 바이트의 +1.2%였고(기준 ±10%), 볼륨 used는 그대로였다. `anf_volume_snapshots`는 [0, 1, 1, 0]으로 바뀌었다 [클론 측정, 구현자 e2e].
- **ANF와 다르다.** ANF "Volume Consumed Size"는 스냅샷을 포함하고 `df`는 추정이다 [문서 D3, D4]. 클론은 `df`와 같고 스냅샷은 aggregate 쪽에 있다. 그래서 이름을 ANF처럼 "consumed"나 "logical"로 짓지 않고 `used`로 지었다. ANF 이름을 쓰면 스냅샷을 포함하는 것처럼 보이기 때문이다(결정 7).

#### 3.8 한도 도달 신호를 만들지 못한 이유

- **ANF의 뜻.** `ThroughputLimitReached`는 직전 5분 창 안에 한도에 닿았으면 1이다 [문서 D3].
- **처음 후보는 HTB `overlimits`였다.** 클래스가 "보낼 수 없음"(`HTB_CANT_SEND`)이 될 때마다 1씩 는다 [스펙 K12 `sch_htb.c` 566~572행]. 구간 안에서 늘었으면 "닿았다"로 쓸 수 있다고 봤다 [추론, 브리프].
- **S8에서 신호가 못 됐다** [클론 측정 S8 Q4, 한도 32 MiB/s, 1 MiB 직접 I/O, iodepth 16, 1초 창]:

  | 부하 | 사용률 p50 (HTB `Sent` 속도 ÷ HTB rate) | `overlimits`/s p50 | `overlimits`가 늘어난 1초 창 | `fq_codel` 드롭(20 s) |
  | --- | --- | --- | --- | --- |
  | 쓰기 50% | 0.503 | 276 | 42/42 | 0 |
  | 쓰기 81% | 0.808 | 519 | 42/42 | 21 |
  | 쓰기 91% | 0.906 | 599 | 42/42 | 30 |
  | 쓰기 포화 | 0.979 | 705 | 43/43 | 32 |
  | 읽기 포화 | 0.951 (p10 0.936) | 725 | 43/43 | 37 |
  | 유휴 | — | 0 | — | — |

  - `overlimits`는 **절반 부하에서도 1초 창마다 늘었다**. 증가량은 보낸 바이트에 거의 비례했다(wire MiB당 16.5~22.8). 기본 burst가 1,543 B인데 GSO 패킷은 최대 68,130 B라서, 큰 패킷마다 클래스가 잠깐 "보낼 수 없음"이 되는 것으로 본다 [추론, S8].
  - burst를 256k로 키워도 50% 부하에서 초당 227로 계속 늘었다.
  - `fq_codel` 드롭은 81% 부하부터 나와서 포화와 가르지 못한다. backlog, `tokens`, `lended`도 이진 신호가 아니었다.
- **사용률은 부하를 따라가지만 간격이 좁다.** 91% 부하(0.906)와 포화(쓰기 0.979, 읽기 0.951) 사이가 0.045~0.07이다. 임계값 0.95면 이번 포화 창의 중앙값은 모두 넘는다. 그러나 읽기 포화의 p10(0.936)은 못 넘어서, 1초 창 하나로 판정하면 놓친다. 창 길이와 "창 안의 최댓값/평균" 중 무엇을 쓰느냐가 결과를 바꾼다. HTB `Sent` 기준 사용률은 스크레이프마다 볼륨마다 `nsenter tc`(약 2 ms)도 필요하다. S8이 적은 다른 정의(데이터 처리량 ÷ 한도)는 지금 내는 두 계열로 Prometheus 쿼리에서 계산할 수 있다 [추론]. AC-06의 비율이 바로 그 값이다.
- **결정 6: 내지 않는다.** 대신 한도 gauge(`anf_volume_throughput_limit_bytes_per_second`)를 내고 처리량 차트에 점선으로 그린다. 사용자는 처리량 선이 한도 선에 붙었는지를 눈으로 본다. AC-06(`test_metrics_data_live.py:150-208`)이 그 비교를 숫자로 확인한다. 안정 구간 `rate(read)+rate(write)` 중앙값이 한도 gauge의 99.33%(10 MiB/s), PATCH 뒤 99.0%(20 MiB/s)였고, gauge가 PATCH를 따라 20 × 1,048,576으로 바뀌었다 [클론 측정, 구현자 e2e].
- `QosLatencyDelta`도 대응 신호가 없다. 지연 카운터 자체가 없기 때문이다(3.10절 아래 참고).
- [처리량 제한 문서](throughput-limit.md) 3.9절이 보인 것처럼, 한도보다 낮은 처리량은 한도가 아니라 이웃의 디스크 경합 때문일 수도 있다. 한도 선만으로는 그 둘을 가르지 못한다. 이것은 이 기능의 한계다.

#### 3.9 anf-api: 요청과 비동기 작업

- **요청.** 경로 템플릿, 메서드, 상태 코드별 counter와 메서드·경로별 지연 histogram이다(ADR §8). 계약 테스트 `test_arm_app.py:371`이 확인한다. 계정 PUT 한 번, GET 두 번, 없는 경로 하나 뒤에 각각 1, 2, `unmatched` 1이 되고, 구독 ID와 이름이 어떤 라벨에도 없다.
- **작업 소요 시간의 정의**: 작업 행이 만들어진 때(`start_time`)부터 끝 상태까지다(설계 §2.2, §7).
  - 요청을 받은 순간부터 재므로 결함 주입 지연, agent job, 재시작으로 멈춘 시간까지 들어간다. 사용자가 폴링하며 기다린 시간과 같은 뜻이다 [추론].
  - **벽시계를 쓴다.** 재시작 뒤 다시 돈 작업도 원래 행이 만들어진 때부터 재야 하므로, 프로세스마다 기준이 다른 단조 시계는 쓸 수 없다. WSL 벽시계는 뒤로 건너뛸 수 있어서([처리량 제한 문서](throughput-limit.md) 3.6절) 음수는 0으로 자른다(`api_metrics.py:54-55`).
- **한 번만 센다.** `_finish`가 끝 상태를 저장한 **뒤에** 센다(`lro.py:169-171`). anf-api가 작업 중에 멈추면 그 프로세스는 아직 끝 상태가 아니라 세지 않는다. 다음 프로세스가 작업을 다시 돌려 끝내면 거기서 한 번 센다. 단위 테스트(`test_lro.py:297`)와 계약 테스트(`test_arm_app.py:409`)가 "첫 프로세스 0, 다음 프로세스 1, 진행 중 0"을 본다.
- **진행 중 gauge**는 "이 프로세스의 워커가 지금 돌리는 작업 태스크 수"다. DB의 미완료 작업 수가 아니다. 태스크 시작에 오르고 `finally`에서 내린다(`lro.py:125-132`). 재시작 직후에는 0이었다가, 새 워커가 시작하면서 미완료 작업을 다시 띄우면 오른다(`lro.py:93-104`, `:110-120`). 결함 주입으로 1 s 지연시킨 작업 동안 1이고 끝나면 0이다(`test_arm_app.py:387`).
- **실패.** 결함 주입 실패와 처리기 예외 모두 `result="Failed"`로 센다(`test_lro.py:271`, `test_arm_app.py:401`).

#### 3.10 시간: 5 s 수집, 20 s 창, ANF 5분 평균

- **클론**: Prometheus가 5 s마다 긁고, 대시보드는 `rate(...[20s])`를 최근 5분 범위, step 5 s로 그린다(결정 12·13).
- **창에 따른 반응 시간** [클론 측정 S8 Q7 P7, 30 s 쓰기, 0.25 s마다 쿼리, 3회]:

  | 식 | 평균의 50%를 넘을 때까지 | 끝난 뒤 10% 밑까지 | 최고값(MiB/s, fio 약 31) |
  | --- | --- | --- | --- |
  | `irate(…[20s])` | 2.43~5.45 s | 6.34~9.36 s | 31.2~31.6 |
  | `rate(…[15s])` | 7.27~10.26 s | 9.36~13.24 s | 27.1~31.5 |
  | `rate(…[20s])` | 9.32~12.35 s | 14.45~18.33 s | 24.3~31.5 |
  | `rate(…[1m])` | 29.40~30.33 s | — | 12.4~17.4 |

  - 지연은 "다음 스크레이프까지(0~5 s) + 창 안에 표본 둘이 들어올 때까지"다 [추론, S8].
  - `rate[1m]`은 30 s 부하를 절반 높이로만 보였다. ANF의 5분 평균은 이보다 훨씬 늦고 낮게 보일 것이다 [추론].
- **`irate`를 버린 이유**(결정 12): 더 빠르지만 마지막 표본 둘만 써서 들쭉날쭉하다.
- **5분 창을 기본으로 하지 않은 이유**(결정 13): 수락 기준이 "클라이언트에서 부하를 걸면 그래프에 나타난다"인데, 5분 창이면 분 단위가 걸린다. ANF와 같은 값이 필요하면 같은 카운터에 `rate(...[5m])`를 쓰면 된다 [추론].
- e2e AC-07: 부하를 건 뒤 `rate(...[20s])`가 0보다 커지기까지 5.03 s였다(기준 15 s) [클론 측정, 구현자 e2e]. "0보다 커짐"이라서 위 표의 "50%를 넘음"보다 빠르다.
- **지연(latency)을 내지 않는 이유**: knfsd 카운터 형식에 시간 항목이 없다 [추론, 스펙 K1]. 연산별 서버 지연을 얻으려면 nfsd tracepoint나 eBPF가 필요하고, 이번 조사 범위 밖이었다.

#### 3.11 대시보드와 PromQL

볼륨 하나(`creation_token="<token>"`를 `sel`로 줄임)의 쿼리다(`MetricsPanels.tsx:45-55`).

| 차트 | 선 | PromQL |
| --- | --- | --- |
| Throughput (MiB/s) | read | `sum(rate(anf_volume_read_bytes_total{sel}[20s]))` |
| | write | `sum(rate(anf_volume_write_bytes_total{sel}[20s]))` |
| | limit (점선) | `sum(anf_volume_throughput_limit_bytes_per_second{sel})` |
| IOPS (/s) | requests | `sum(rate(anf_volume_nfs_requests_total{sel}[20s]))` |
| | read ops, write ops | `sum by (op) (rate(anf_volume_nfs_operations_total{sel}[20s]))` |
| Usage (GiB) | used | `sum(anf_volume_used_bytes{sel})` |
| | size (점선) | `sum(anf_volume_size_bytes{sel})` |
| anf-api Requests (/s) | 상태 코드별 | `sum by (status) (rate(anf_api_http_requests_total[20s]))` |
| Operations in progress | in progress | `sum(anf_api_operations_in_progress)` |

- counter에는 `rate()`를 씌우고 gauge는 그대로 읽는다.
- `sum`으로 감싸는 이유는 3.5절에 있다(같은 경로로 다시 만든 볼륨).
- **연산 수 선은 응답에 계열이 있을 때만 그린다**(`linesBy`, `MetricsPanels.tsx:20-22`). 프로토콜을 보고 고르지 않는다. NFSv3 볼륨은 agent가 그 계열을 내지 않아서 요청 수 선만 남는다(설계 §7).
- 표시 단위로 나누는 것은 브라우저가 한다(MiB, GiB). Prometheus에는 기본 단위(바이트)만 있다.
- 대시보드는 `query_range` 하나만 쓴다. 쿼리 묶음은 `Promise.all`로 한꺼번에 보내고, 하나라도 실패하면 그 회차 전체를 오류로 본다(`useMetrics.ts:38-47`).

### 설계 결정

#### 결정 1~14 (모두 자동 채택)

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | 이름은 Prometheus 관례 `anf_*`(기본 단위, 누적 `_total`). Azure 이름은 문서의 대응표로 | Azure REST 이름 그대로 / Harvest 이름 | Azure 이름은 단위가 bytes/s gauge라 관례와 어긋난다. Harvest 이름도 기본 단위·`_total` 관례와 다르다. Harvest는 선례로만 언급한다 |
| 2 | 원시 카운터를 내고 PromQL `rate()` | 수집기가 5분 평균 gauge를 계산 | ANF와 모양은 같지만 창이 고정되고 리셋 처리를 직접 해야 한다 |
| 3 | 처리량은 knfsd `io` 줄 | `eth0`(헤더 포함 0.2~10% 큼, 반대 방향 섞임), `ifb0`·HTB `Sent`(읽기·쓰기 합만, `nsenter tc` 필요) | `io`는 데이터 바이트이고 방향이 나뉘며 fio와 바이트 단위로 같다(S8 Q2). ANF 정의와 달리 메타데이터 바이트가 없다는 점은 문서에 적는다 |
| 4 | IOPS 합계는 `rpc` 호출 수. v4.1은 COMPOUND 수 | `proc4ops` 전체 합 | SEQUENCE·PUTFH까지 세어 약 3배가 된다(S8 Q3) |
| 5 | v3 볼륨의 읽기·쓰기 연산 수는 내지 않는다 | `rc` 줄 근사 / 전역 `proc3` | `rc` misses는 변경 연산 전체라 WRITE와 다르고 설명하기 어렵다. `proc3`는 모든 netns의 합이라 틀린다(S8 Q1) |
| 6 | 한도 도달 신호는 내지 않는다. 한도 gauge를 내고 선으로 그린다 | HTB `overlimits` / 사용률 임계값 | `overlimits`는 부하와 무관하게 는다. 사용률은 91% 부하와 포화의 간격이 좁다(S8 Q4) |
| 7 | 사용량은 `statvfs` used(활성 파일시스템). 스냅샷 공간은 aggregate 메트릭으로 따로 | thin LV 매핑 블록 / ANF 이름을 그대로 써서 스냅샷 포함처럼 보이게 함 | 매핑은 파일을 지워도 줄지 않는다(S8 Q5). 이름이 뜻을 속인다 |
| 8 | 스크레이프 때 읽는다. pid는 Docker API 소켓(1.7 ms), 풀은 `dmsetup status`(5.6 ms) | 백그라운드 주기 수집 / `docker inspect` CLI(호출마다 150 ms) / `lvs` 백분율(소수 둘째 자리) | 상태와 스레드가 늘지 않는다. CLI는 볼륨이 늘면 스크레이프가 초 단위가 된다 |
| 9 | 볼륨 라벨은 `volume_uuid`, `creation_token`, `protocol`. 대시보드가 `creationToken`으로 잇는다 | anf-api의 info 메트릭으로 ARM 이름 매핑 / agent가 ARM ID를 앎 | 이번 차트에는 매핑이 필요 없다. agent는 ONTAP 쪽 계층이라 ARM을 모른다 |
| 10 | `prometheus_client`(anf-api의 counter·histogram, agent의 사용자 정의 collector) | 텍스트 형식을 직접 씀 | 히스토그램과 이스케이프를 다시 만들게 된다 |
| 11 | Prometheus는 컨테이너 + 저장소의 설정 파일 + 스크립트 하나, 5 s 수집, 데이터는 버림 | WSL에 패키지 설치 / 이름 있는 볼륨에 보존 | 패키지는 기기 설정을 바꾼다. 데모에 보존이 필요 없다 |
| 12 | 의존성 없는 SVG 차트, `rate(...[20s])`, 최근 5분 | 차트 라이브러리 / `irate` | 캔버스 기반은 jsdom 테스트가 어렵고 의존성이 는다. `irate`는 빠르지만 들쭉날쭉하다 |
| 13 | 클론은 5 s 수집·20 s 창. ANF 5분 평균과 같은 값은 `rate(...[5m])`로 얻는다고 문서에 적음 | 5분 창을 기본으로 | 부하가 그래프에 나타나기까지 분 단위가 걸린다 |
| 14 | 전체 회귀는 PR의 CI `data-plane` 작업을 근거로. WSL에서는 새 파일과 영향받는 파일만 | WSL 전체 묶음 1회(약 90분) | 사용자가 긴 검증 실행을 원하지 않는다 |

#### 구현 중 변경 (설계 §7)

설계가 정하지 않은 세부를 구현하며 정한 것이다. 결정 1~14는 바뀌지 않았다.

| 무엇 | 왜 |
| --- | --- |
| 볼륨 목록(`inventory`)과 풀 사용량(`aggregate_usage`)을 `FlexVolManager`에 둠. 수집기는 그 결과, knfsd 파일, `statvfs`만 읽음 | 태그와 마운트 표를 읽는 코드(`_report`, `_mounted`)가 이미 거기 있다 |
| 마운트되지 않은 볼륨은 태그 계열만, 인스턴스가 없으면 knfsd 계열 없음 | 마운트 안 된 지점의 `statvfs`는 호스트 값이다 |
| Docker API 소켓은 스크레이프마다 새로 연결. `404`·`Pid 0`은 인스턴스 없음, 그 밖은 그 볼륨만 실패 | 수집기에 상태가 남지 않는다 |
| dm-thin 메타데이터 블록 4,096 B 고정, 데이터 블록 크기는 테이블 크기 ÷ 총수 | 상태 줄의 메타데이터 칸은 블록 수이고 블록 크기는 커널 상수다 |
| 파서가 `ra` 줄과 `proc4ops`의 첫 값(개수 76)을 처리 | 실제 파일의 모양이다 |
| 작업 소요 시간은 작업 행의 시작 시각(벽시계)부터, 음수는 0 | 재시작을 넘어 재야 하고, WSL 벽시계는 뒤로 건너뛴다 |
| 진행 중 gauge를 처리기 키마다 0으로 미리 선언. 작업 수·소요 시간은 `_finish`의 트랜잭션 뒤에 셈 | 대시보드의 `sum`이 처음부터 0이다. 재시작 뒤 한 번만 센다 |
| 요청 미들웨어는 처리되지 않은 예외를 `500`으로 셈 | 바깥 미들웨어가 그렇게 응답한다 |
| 이미지는 Docker Hub `prom/prometheus:v3.15.1` | CI 러너에서 익명 pull 한도에 걸리면 quay.io 사본으로 바꿀 수 있다. 지금은 그대로 둠 |
| e2e는 Prometheus를 모듈 fixture로 한 번 띄우고 `run-prometheus.sh stop`으로 지움. 실행기는 9090을 사전 점검하고, 남은 `anf-prometheus`와 9090 리스너를 실패로 셈 | 데이터 플레인은 기기에 하나다 |
| AC-05의 NFSv3 부하는 iodepth 1 | `rpc` 줄이 동시 증가를 잃어 "요청 수 ≥ fio 연산 수"가 깨질 수 있다(3.3절) |
| AC-09의 인스턴스 재시작은 `docker rm -f` 뒤 같은 볼륨 PUT(`200 Updating`) | agent에 인스턴스만 다시 띄우는 API가 없고, 볼륨 ensure가 없어진 인스턴스를 다시 만든다 |
| 대시보드 쿼리를 `sum(...)`(ops는 `sum by (op)`)으로 감쌈 | 같은 경로로 다시 만든 볼륨의 두 계열이 5분 창에 겹친다 |
| IOPS의 연산 선은 응답에 계열이 있을 때만 | v3 볼륨은 계열이 없다 |
| 사용량 차트의 size를 점선으로 | 한도 선과 같은 "기준선" 표시 |
| 볼륨은 `Succeeded`이고 `creationToken`이 있을 때만 고름. 고른 뒤에는 트리에 있는 동안 패널 유지 | 인스턴스가 없으면 계열이 없다. 상태가 `Updating`으로 바뀌어도 패널을 닫지 않는다 |
| API 패널은 트리를 한 번 읽은 뒤에 보임 | "Loading…" 두 개가 겹치지 않게 |
| Prometheus 프록시가 `/prometheus` 접두사를 뗌 | Windows의 Vite dev에서 WSL Prometheus까지 `query`·`query_range`가 `200`인 것을 확인했다 |

---

## 4. 실제 ANF와 다른 점

### 같은 점

- 볼륨 단위의 사용량(크기, used, inode), 읽기·쓰기 처리량(bytes/s), 읽기·쓰기·전체 IOPS를 본다 [문서 D1]. 클론은 서버(knfsd)가 받은 것을 센다. ANF도 서버 쪽에서 센다면 같은 성질이다 [추론].
- 메트릭은 읽기 전용이고 리소스의 `provisioningState`와 무관하다 [추론].
- Azure 메트릭에 차원이 없고 리소스마다 계열이 하나인 것처럼, 클론도 볼륨마다 메트릭당 계열이 하나다(연산 수만 `op`별로 둘). 라벨이 리소스 식별 역할을 한다 [추론].

### 다른 점

| 항목 | 실제 ANF | 이 프로젝트 | 이유 |
| --- | --- | --- | --- |
| 수집·조회 | Azure Monitor 플랫폼 메트릭, Metrics REST·포털 [문서 D3] | Prometheus가 두 프로세스의 `/metrics`를 pull, 대시보드가 쿼리 API를 읽음 | D-08, ADR §8 |
| 차원·라벨 | 차원 없음 [문서 D1] | 볼륨 라벨(`volume_uuid`, `creation_token`, `protocol`), 연산 `op` | 한 Prometheus에 모든 볼륨이 들어가므로 리소스를 라벨로 구분한다 |
| 시간 단위 | 5분 평균, 최소 `PT5M` [문서 D1][D3] | 5 s 수집, 대시보드 20 s 창. 같은 데이터에 `rate(...[5m])`로 5분 평균 | 결정 13. "부하를 걸면 그래프에 나타난다" |
| 값의 모양 | 초당 값(평균) | 누적 카운터, 초당 값은 `rate()`가 계산 | 결정 2. ONTAP `statistics.*_raw`와 같은 쪽 [추론] |
| 사용량 | 스냅샷 포함(`VolumeLogicalSize`) [문서 D3]. `df`는 추정 [문서 D4] | `statvfs` used = 클라이언트 `df`. 스냅샷 제외 | 클론 스냅샷 공간은 씬 풀에서 나간다(R-09). 결정 7 |
| 크기 | 프로비전 크기 [문서 D1] | ext4 크기(오버헤드만큼 작다) | `statvfs`에서 읽는다 |
| 스냅샷 크기 | `VolumeSnapshotSize`, `VolumePoolTotalSnapshotSize` [문서 D1][D2] | 없음. aggregate 사용량으로 간접 관찰 | 고유 블록은 `thin_ls`가 필요하다 [미확인] |
| 처리량의 바이트 | "across the wire", read/write/other [문서 D3] | knfsd 데이터 바이트, 읽기·쓰기만. 헤더·메타데이터 없음 | 결정 3 |
| Other 처리량·IOPS | 있음 [문서 D1] | 없음 | knfsd `io`에 메타데이터 바이트가 없다. Other IOPS는 정의(COMPOUND 단위?)부터 [미확인] |
| v3 읽기·쓰기 IOPS | 있음 [문서 D1] | 없음. 전체 요청 수만 | 커널 `proc3`가 전역이다(3.1절). 결정 5 |
| Total IOPS 단위 | v4.1에서 COMPOUND인지 연산인지 [미확인] | v4.1은 COMPOUND 수, v3는 RPC 호출 수(NFSACL 포함) | 결정 4 |
| 지연 | read/write/other, ms, 서비스 안에서 잼 [문서 D3] | 없음 | knfsd에 지연 카운터가 없다(tracepoint/eBPF 필요) |
| 한도 도달 | `ThroughputLimitReached`(0/1, 5분), `QosLatencyDelta` [문서 D1][D3] | 없음. 한도 gauge와 차트의 점선 | HTB `overlimits`가 부하와 무관하게 는다. 결정 6 |
| 풀 메트릭 | 6개 [문서 D2] | 없음 | 풀 처리량 합은 ARM 풀 속성(`utilizedThroughputMibps`)으로 이미 보인다(FR-08) |
| aggregate | ANF 메트릭 표에 없음 | `anf_aggregate_*`(dm-thin 풀) | 클론 고유. R-09(스냅샷이 풀을 채울 수 있음)를 보이기 위해 |
| 카운터 리셋 | 해당 정보 없음 | 볼륨 인스턴스가 다시 뜨면 knfsd 계열이 0부터. 인스턴스가 내려가 있으면 그 계열이 없다 | 카운터가 인스턴스 netns 안에 있다 |
| 보존 | [미확인] | Prometheus 데이터는 컨테이너와 함께 버린다 | 결정 11 |
| API·작업 지표 | 브리프가 본 메트릭 표에 없다 | anf-api의 요청·작업 지표 | 클론 컨트롤 플레인 운영용 |

---

## 5. 검증

### 구현자 e2e (참고)

구현자가 `backend/tests/e2e/test_metrics_data_live.py`(5개, 단독 실행 359 s, 2026-11-10, `docs/testing.md`)를 실제 데이터 플레인에서 돌려 기록한 값이다. 판정은 아래 검증자 표가 한다.

| AC | 테스트 | 기록된 값 |
| --- | --- | --- |
| AC-03 사용량 | `:80` | 256 MiB 쓰기 뒤 used 증가가 268,435,456과 0.0015% 차이. 클라이언트 `df` used와 0.006% 차이 |
| AC-04 처리량 | `:80` | v3·v4.1 모두 쓰기 카운터 증가 = fio 바이트(268,435,456), 같은 구간 다른 볼륨 0 |
| AC-05 IOPS | `:80` | v4.1 READ 연산 48,483 = fio. v4.1 `requests`는 48,468(15 적음, 3.3절) |
| AC-06 한도와 함께 | `:150` | 안정 구간 `rate(read+write)` ÷ 한도 gauge = 99.33%(10 MiB/s), PATCH 뒤 99.0%(20 MiB/s) |
| AC-07 Prometheus | `:150` | 부하 시작 5.03 s 뒤 `rate(...[20s])` > 0 |
| AC-09 수명 주기 | `:214` | 쓰기 카운터 64 MiB → 0 → 32 MiB, 계열 하나 |
| AC-10 aggregate | `:280` | 스냅샷 뒤 덮어쓰기: aggregate +1.2%(덮어쓴 바이트 대비), 볼륨 used 그대로 |
| AC-11 간섭 없음 | `:314` | 1 s 스크레이프 98번 모두 `200`, 가장 느린 스크레이프 0.153 s |

anf-api 지표(AC-01, AC-02)는 계약 테스트(`test_arm_app.py:371-417`)와 단위 테스트(`test_lro.py:256-316`, `test_api_metrics.py`)가 본다. e2e는 Prometheus가 실제 anf-api에서 작업 지표와 경로 템플릿을 긁는 것만 본다(`:187-188`, `:201-202`).

### 실환경 검증 (real-env-verifier)

검증 대상 코드는 `7eac56c`(제품 코드 내용 해시 `7c38d8c7…`)다. 보고서: `_workspace/metrics/04_verifier_report.md`(1회차), `04_verifier_report_r2.md`(2회차).

| 기준 | 결과 | 근거 |
| --- | --- | --- |
| AC-01 요청 지표 | PASS | 실제 uvicorn: 요청 수와 히스토그램 `_count`가 보낸 만큼 늘고, `route`는 경로 템플릿 또는 `unmatched`. 출력 어디에도 구독 ID·리소스 이름이 없다 |
| AC-02 작업 지표 | PASS | 결함 주입: 지연된 생성 동안 gauge 1 → 0, 강제 실패는 `Failed`. 작업 도중 재시작(SIGTERM, SIGKILL)해도 새 프로세스에서 한 번만 세고 gauge가 0으로 돌아옴 |
| AC-03 사용량 | PASS | 256 MiB 쓰기에 used +268,439,552, 클라이언트 `df`와 0.006% 차이 |
| AC-04 처리량 분리 | PASS | 쓰기 카운터가 fio와 바이트 단위로 같고(268,435,456), 다른 볼륨 0, 읽기 때 쓰기 카운터 0 (v3, v4.1) |
| AC-05 IOPS | PASS | v4.1 READ 연산 수 = fio 연산 수. v3는 요청 수만 있고 연산 계열 없음 |
| AC-06 Prometheus와 한도 | 1회차 FAIL → 2회차 PASS | 1회차: 한도를 20 MiB/s로 올린 구간에서 Prometheus 값이 한도의 76.7%(3번 중 1번). fio가 실제로 덜 썼다(WSL 스토리지 흔들림). 시험이 메트릭 정확성과 한도 도달(FR-08의 몫)을 함께 보고 있어 나눴다. 2회차(9회 반복 결과 파일로 판정): Prometheus 카운터 증가 ÷ fio 바이트 0.9966~1.0013, 20 s 처리량 최대가 한도의 95.8~99.5%, 9회 모두 통과. 스토리지가 느려진 회(11.6~15.2 MiB/s)가 3번 있었지만 fio와 같은 값을 보였다 |
| AC-07 Prometheus | PASS | 두 대상 `up`. Windows에서 `:9090`과 Vite 프록시 양쪽으로 볼륨 계열 조회. 부하 뒤 3.2~4.8 s에 rate > 0 |
| AC-08 대시보드 | PASS (headless Chrome) | 실제 스택 + Windows `npm run dev`를 Chrome 157 headless로 열어 볼륨 행을 눌렀다. 쓰기 처리량 0 → 9.9(한도 10) → 19.7(한도 20). Prometheus를 멈추면 두 패널에 오류, 트리는 계속 갱신. Chrome 확장 프로그램은 연결돼 있지 않았다 |
| AC-09 수명 주기 | PASS | 인스턴스가 내려가 있어도 `/metrics` 200. 다시 뜨면 카운터가 0부터, 계열은 하나, rate 음수 없음. 삭제 뒤 계열 사라짐 |
| AC-10 aggregate | PASS | 스냅샷 뒤 덮어쓰기: aggregate +1.2%(쓴 바이트 대비), 볼륨 used 그대로 |
| AC-11 간섭 없음 | PASS | 1 s 스크레이프 98번 모두 200, 한도 측정 99.4%, 스크레이프 최대 0.153 s |
| AC-12 회귀 | PASS | WSL `-m "not dataplane"` 1016 passed·skip 0, ruff 통과. 기존 데이터 플레인 묶음의 회귀는 PR의 CI `data-plane` 작업이 맡는다(통과가 merge 조건. WSL 전체 묶음은 돌리지 않았다) |
| AC-13 프런트엔드 | PASS | typecheck, Vitest 48개, build |

관찰: `anf_volume_nfs_requests_total`은 v4.1 고부하에서 fio 연산 수보다 0.06% 적었다(`rpc` 줄의 특성). 쉬는 마운트도 초당 약 0.067 요청을 낸다. "진행 중 작업" 차트는 5 s 수집 간격보다 짧은 작업을 놓친다.

---

## 6. 개발 과정

1. **선행 확인 (0단계).** FR-08(처리량 제한)과 FR-09(대시보드)가 `done`이었다. FR-11은 사용자 결정으로 `partial`로 merge됐고 FR-12는 그 위에서 시작했다. PRD §8은 조사를 "Azure Monitor 메트릭 대응"으로 한정한다.
2. **조사.** anf-researcher가 Learn의 메트릭 정의 페이지(D1, D2)와 개념 문서(D3, D4), ONTAP 휠(O1), Harvest 문서(H1), Prometheus 문서(P1~P3), 커널 v6.18 소스(K1~K12)를 봤다. 30턴 상한에 가까워 "한도 도달"로 마감했다. 가장 중요한 결론인 "`io`·`rpc`·`proc4ops`는 netns별이고 `proc3`는 전역이다"는 **소스에서 추론한 것**이었고, 브리프가 스스로 "설계 전에 인스턴스 둘로 확인 권장"이라고 적었다.
3. **스파이크 S8 (조건부 통과).** 구현자가 실제 agent와 anf-api를 띄우고 v3·v4.1 볼륨 둘에서 쟀다. 브리프의 추론이 실제 WSL 커널에서 그대로 나왔다. 조건 넷이 설계 결정이 됐다.
   - v3 볼륨은 READ/WRITE 수를 볼륨별로 얻을 수 없다 → 결정 5.
   - HTB `overlimits`는 절반 부하에서도 는다 → 결정 6. **코드를 쓰기 전에 "늘 1인 메트릭"을 걸러 냈다.**
   - `docker inspect` CLI는 호출마다 약 150 ms다 → 결정 8.
   - 인스턴스가 다시 뜨면 카운터가 0부터 시작한다 → AC-09.
4. **설계.** 결정 1~14를 모두 자동 채택했다. 사람에게 물은 결정은 없다. 수락 기준은 AC-01~13이다. ADR §8이 FR-12로 미뤄 둔 처리량 출처와 이름 대응을 여기서 정했다.
5. **구현.** Claude(implementer, 스파이크와 같은 에이전트)가 TDD 훅 아래서 구현했다. agent `/metrics` `e2581cd`, anf-api `/metrics` `37a341c`, Prometheus 컨테이너와 데이터 e2e `3c403b1`, 대시보드 차트 `290f726`, 수락 문장 ↔ 테스트 대응과 구현 중 변경 기록 `e80c8e7`.
   - 실제 `/proc/net/rpc/nfsd`의 모양(`ra` 줄, `proc4ops`의 개수 칸)에 파서를 맞췄다.
   - e2e에서 v4.1 `requests`가 fio보다 15 적은 것을 보고, S8의 `rpc` 덜 세기와 같은 현상으로 판단해 AC-05의 v3 부하를 iodepth 1로 바꿨다.
   - 볼륨을 같은 경로로 다시 만들 때 계열이 겹치는 것을 보고 대시보드 쿼리를 `sum`으로 감쌌다.
   - 이런 변경을 조용히 넣지 않고 설계 §7에 남겼다.
6. **검증.** real-env-verifier 1회차다. 리더와 합의한 규칙에 따라 30분 넘는 실행(WSL 전체 데이터 플레인 묶음)은 하지 않고, AC-12의 CI 부분은 PR을 연 뒤 채운다. 브라우저 확장(Claude in Chrome)이 연결되지 않아 AC-08(대시보드)은 headless Chrome + DevTools 프로토콜로 대신 본다고 보고서에 적었다. 결과는 5절이다.
7. **개념 문서(이 문서).**

AI와 일한 방식으로 설명할 수 있는 것:
- 조사가 소스 코드에서 추론한 결론에 [추론]을 달았고, 그 결론이 설계를 좌우하므로 설계 전에 스파이크로 실측했다. 추론이 맞았지만, 같은 스파이크가 다른 후보(`overlimits`)는 틀렸음을 보였다.
- 설계 문장과 실제가 다른 것(파일 모양, `rpc` 덜 세기, 계열 겹침)은 구현자가 고치고 설계 §7에 기록했다. 리더와 개념 문서는 그 기록을 근거로 쓴다.

---

## 7. Interview Q&A

### Q1. (Concept) What metrics does Azure NetApp Files expose for a volume, and how are they aggregated?

**A.** They're Azure Monitor platform metrics on the volume resource. They have no dimensions and are averaged over five minutes. Usage metrics cover allocated size, consumed size, snapshot size, consumed percentage, and inodes. Performance metrics are split into read, write, other, and total, each with throughput in bytes per second, IOPS, and, except for total, latency in milliseconds. There are also two QoS metrics: "Throughput limit reached", which is 1 if the volume hit its limit in the five-minute window, and "QoS latency delta". The smallest time grain is PT5M, so short spikes average away. Microsoft's example shows 100, 120, 500, 110, and 120 MiB/s displayed as 190. Latency is measured inside the service and excludes the network. Consumed size includes snapshots.

### Q2. (Concept) How do those relate to ONTAP, and where does NetApp Harvest fit?

**A.** ONTAP's volume API has the same structure, but I can't claim ANF is built on it, because that isn't published. ONTAP REST volumes have `metric` fields for IOPS, throughput, and latency, split into read, write, other, and total, as averages over a duration such as 15 seconds. They also have `statistics` raw fields, which are monotonically increasing counters aggregated across nodes. So ONTAP offers both shapes. NetApp Harvest, NetApp's open-source exporter, turns those ONTAP counters into Prometheus metrics like `volume_read_ops` and `volume_read_data`. Its docs list them as rate types, so it seems to compute rates in the collector, and its names don't follow Prometheus's base-unit and `_total` conventions. I chose the raw-counter side: my agent exposes cumulative counters, PromQL computes rates, and a table maps my names to Azure's.

### Q3. (Design) Why export raw counters and use `rate()`, and what happens when a counter resets?

**A.** Counters let each query choose its own averaging window, and they keep the agent stateless. The agent exposes cumulative values such as `anf_volume_write_bytes_total` straight from the kernel. The dashboard uses `rate()` over 20 seconds, and `rate(...[5m])` on the same data gives an ANF-style five-minute average. Values that can go down, like used bytes, are gauges. Resets happen when a volume's NFS instance restarts. The counters live in its network namespace, and the new namespace starts at zero. I don't compensate, because `rate()` treats a decrease as a reset. In the end-to-end test the write counter went from 64 MiB to 0 to 32 MiB as one series, and the rate never went negative. We only lose the increase after the last scrape before the restart.

### Q4. (Design) Where does per-volume throughput come from in your clone?

**A.** From knfsd's `io` line inside the volume's network namespace. Each volume has its own knfsd instance in its own namespace, so the agent reads `/proc/<instance pid>/net/rpc/nfsd` from the host. The `io`, `rpc`, and `proc4ops` lines in that file are per namespace. In the spike, `io` matched fio's byte count exactly in every case. It separated reads from writes and also counted reads served from the server's page cache. I compared three alternatives. `eth0` counters include headers, 0.2 to 10 percent extra, and leak response bytes into the opposite direction. The `ifb0` and HTB counters from the throughput limiter only give reads plus writes combined. The trade-off is that ANF defines throughput as bytes across the wire, including metadata traffic, and `io` counts only data.

### Q5. (Limitation) Why don't your NFSv3 volumes report read and write IOPS?

**A.** Because the kernel keeps NFSv3 procedure counts only globally, so a per-volume number would be wrong. The `proc3` line has a counter for each procedure, but it lives in a static per-version structure that every network namespace shares. The spike proved it: a write to volume A raised WRITE by 256 in A's file, B's file, and the host's file. NFSv4.1 is different. Its per-operation counts, `proc4ops`, are per namespace, and they matched fio and the client's mountstats exactly. For v3 I only export total requests from the per-namespace `rpc` line. The reply-cache line could approximate writes, but it counts every operation that changes data or metadata, so creating and deleting 200 files showed 602 "writes". I'd rather show nothing than a number nobody can explain.

### Q6. (Trade-off) How does your throughput graph differ from ANF's five-minute average?

**A.** Mine reacts in seconds, while ANF smooths over five minutes. Prometheus scrapes every five seconds and the dashboard plots `rate()` over a 20-second window. In the implementer's end-to-end run, the rate rose above zero 5.03 seconds after the load started. ANF's smallest time grain is five minutes, so a short burst would barely show. In the spike, even a one-minute window drew a 30-second write at about half its real height. I picked the short window because the acceptance test says load from a client must appear on the graph. The underlying data is the same, so `rate(...[5m])` gives the five-minute view. I used `rate` instead of `irate`. `irate` reacts in about five seconds, but it uses only the last two samples, so the line is noisy.

### Q7. (Trade-off) Why is there no "throughput limit reached" metric?

**A.** The obvious signal turned out to be meaningless, and the alternative needed a threshold I couldn't justify yet. I expected HTB's `overlimits` counter to work, since it increments when the traffic class can't send. But in the spike it grew in every one-second window, even at 50 percent load, roughly in proportion to bytes sent. A larger burst didn't change that. Utilization, meaning HTB bytes sent divided by its rate, did track load: 0.50 at half load, 0.906 at 91 percent, and 0.951 to 0.979 when saturated. But that gap is only 0.045 to 0.07, so the window and threshold would decide the answer. Instead I export the limit as a gauge and draw it as a dashed line over the throughput chart. Under saturated writes, measured throughput sat at about 99 percent of it.

### Q8. (Design) How did you keep label cardinality bounded?

**A.** Every label comes from a fixed set or grows only with the number of volumes. Volume series carry the volume UUID, creation token, and protocol. The agent plays ONTAP's role under ARM, so it doesn't know ARM names. The dashboard joins them on `creationToken`. On anf-api, the request counter uses the FastAPI route template, never the raw URL. That keeps subscription IDs and resource names out of labels, and any path that matches no route is counted as `unmatched`. Operation metrics use the worker's handler key, such as `volumes/create`, plus `Succeeded` or `Failed`. With raw URLs, every new account would add series, and a scanner hitting random paths could grow the time-series database without limit. The latency histogram also has no status label, which keeps its bucket series from multiplying.

### Q9. (Observability) How do you know scraping doesn't disturb I/O or the agent's jobs?

**A.** The collector only reads, it bypasses the job queue, and I measured it under load. It runs at scrape time, with no background thread. It reads `/proc` files and calls `statvfs`, `lvs`, `findmnt`, and `dmsetup status`. It asks the Docker API socket for each instance's PID. It never runs `tc` or `nsenter`, and it never touches exports. The `/metrics` route skips the agent's one-at-a-time job table, so a scrape never waits behind a volume creation. In the spike, the `docker inspect` CLI cost about 150 milliseconds per call, while the socket took 1.7 milliseconds for two volumes, so I used the socket. In the end-to-end test, I scraped every second while measuring a 10 MiB/s limit and creating another volume. All 98 scrapes returned 200, the slowest took 0.153 seconds, and the volume creation succeeded.

### Q10. (Difference) Does your used-space metric include snapshots like ANF's?

**A.** No, on purpose. ANF's "Volume Consumed Size" includes snapshot space, and Microsoft says client `df` is only an estimate once snapshots exist. In my clone a snapshot is a dm-thin snapshot, and the blocks it holds come from the thin pool, which plays the aggregate, not from the volume's file system. So `anf_volume_used_bytes` comes from `statvfs` and matches client `df`. In the spike, writing 512 MiB raised both by exactly 536,870,912 bytes. To show snapshot space, I export the thin pool's usage from `dmsetup status`. When the test overwrote a file after a snapshot, volume usage stayed flat and the aggregate grew by about the bytes written, 1.2 percent more. I named the metric "used", not "consumed", so it doesn't pretend to mean ANF's version.

### Q11. (Debugging) Your NFSv3 IOPS check could fail even when everything works. Why?

**A.** The kernel's `rpc` call counter loses a few increments under heavy concurrency. In the spike, at about 6,000 4 KiB operations per second, the `rpc` line was 1 to 13 lower than other counters for the same work, 0.01 to 0.02 percent. Its fields are plain 32-bit integers. My guess is that the increments aren't atomic, but I couldn't confirm the exact code. The per-CPU counters, `proc4ops` and the reply cache, were exact. So the test checks NFSv4.1 read operations against fio within 2 percent. It runs the NFSv3 load at queue depth 1, so the check "requests are at least fio's operations" can't break from that tiny undercount. In the implementer's run, v4.1 requests were 15 below fio's 48,483, while the READ count matched exactly.

### Q12. (REST API, LRO) How do you measure asynchronous operation duration across restarts?

**A.** From the moment the operation row was created until it reaches a terminal state, and each operation is counted once. The start time is stored in SQLite when the request is accepted. The duration therefore covers everything after acceptance, including agent jobs and injected delays, and it survives a restart. If anf-api dies mid-operation, the next process resumes it and still measures from the original start. A monotonic clock can't span processes, and the WSL wall clock can step backward, so I clamp negative values to zero. The counter and histogram update only after the terminal state is committed. The first process doesn't count an interrupted operation, and the next one counts it once. The in-progress gauge belongs to each process. It rises and falls around each worker task.

### Q13. (Retrospective) If you did this again, what would you change?

**A.** Three things. First, latency. ANF exposes read, write, and other latency, and knfsd's counters have no timing, so I'd look at nfsd tracepoints or eBPF. Second, a limit-reached signal based on utilization, with an explicit window and threshold, shown next to queue state. My throughput-limit verification showed a volume can stay below its limit because a neighbor saturates the shared disk. Operators need to tell that apart from throttling, and a limit line alone can't. Third, scale. Each scrape runs `lvs` and `findmnt` and makes one Docker API call per volume. That's fine for a demo, but I'd measure it with fifty volumes. I might also cache instance PIDs and invalidate the cache when an instance restarts.

---

## 부록. 이 문서가 쓰지 못한 것

브리프·스파이크·설계에 근거가 없거나 [미확인]이라 쓰지 못한 것이다.

- **Azure Monitor 메트릭의 보존 기간, 포털 표시 지연, Metrics REST api-version.** 브리프가 확인하지 못했다.
- **`VolumeLogicalSize`가 ONTAP `space.used`인지 `space.logical_space.used`인지.** 이름만 근거다.
- **`ThroughputLimitReached`와 `QosLatencyDelta`가 ONTAP의 무엇(QoS throttle 지연 등)에서 오는지.** ONTAP `qos statistics volume latency show`의 지연 분해는 후속 조사 목록에 있다.
- **ANF가 NFSv4.1 IOPS를 COMPOUND 단위로 세는지 연산 단위로 세는지.** 문서 목록에 둘이 함께 있다.
- **"Volume Quota Size" 메트릭이 실제로 있는지.** 개념 문서에만 있다.
- **Azure Monitor → Prometheus 이름 대응 관례(azure-metrics-exporter 등)와 FastAPI·OpenTelemetry HTTP 메트릭의 기본 이름.** 조사하지 못했다.
- **`thin_ls`로 스냅샷 고유 크기를 얻는 방법.** 원문을 받지 못했다.
- **`rpc` 줄이 덜 세는 정확한 원인.** 증가 위치(`net/sunrpc/svc.c`)를 확인하지 못했다.
- **S8의 `fstrim` 첫 회(512 KiB)와 두 번째(767.9 MiB)가 다른 이유.** 스파이크가 원인을 보지 않았다.
- **ANF가 이 클론처럼 API 요청·비동기 작업 지표를 사용자에게 내는지.** 브리프가 본 메트릭 표에는 없다.
