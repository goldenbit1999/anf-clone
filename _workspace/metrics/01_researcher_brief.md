# 메트릭 (FR-12) 조사 브리프

- 조사 상태: 한도 도달 (30턴 상한에 가까워 마감. 남은 질문은 "미확인 목록"에)
- 조사일: 2026-11-10
- 기준: ANF RP api-version과 무관하다. 메트릭은 Azure Monitor 쪽(`Microsoft.Insights/metrics`)에서 읽는다. 메트릭 정의는 Learn "Supported metrics" 페이지(ms.date 2026-07-31) [D1][D2], 개념 설명은 `azure-netapp-files-metrics.md`(ms.date 09/11/2026) [D3]를 기준으로 삼았다.
- 범위 가정: PRD §8에 따라 "Azure Monitor 메트릭 대응 조사로 한정". 볼륨·용량 풀 수준의 사용량·처리량·IOPS·지연 메트릭, ONTAP 대응, 클론의 Linux 출처 후보, Prometheus 관례만 본다. 백업·복제·cool tier·cache 볼륨·구독 쿼터 메트릭은 이름만 적었다.
- 이미 확인된 사실은 다시 조사하지 않고 인용했다: 처리량 제한 브리프 `_workspace/throughput-limit/01_researcher_brief.md`, ADR §8, CLAUDE.md FR-08 항목.

## 요약 (5줄 이내)

1. ANF 볼륨 메트릭은 Azure Monitor 플랫폼 메트릭이다. **차원(dimension)이 하나도 없고**, 모두 `Average` 집계(풀 크기 2개만 `Total`도 됨), 시간 단위 `PT5M`부터다. 값은 "5분 평균"이다 [문서 D1][D2][D3].
2. 이름은 REST 이름(PascalCase, 예: `ReadThroughput`, `VolumeLogicalSize`, `ThroughputLimitReached`)과 표시 이름("Read throughput", "Volume Consumed Size")이 따로 있고 둘이 어긋나는 경우가 있다(`VolumeLogicalSize` = "Volume Consumed Size") [문서 D1]. 처리량은 BytesPerSecond, IOPS는 CountPerSecond, 지연은 MilliSeconds, 크기는 Bytes다 [문서 D1].
3. ONTAP에는 같은 모양(read/write/other/total × iops/throughput/latency)의 볼륨 `metric.*`(평균)·`statistics.*_raw`(누적 카운터) 필드와 `space.*`·`files.*` 필드가 있다 [ONTAP O1]. ANF 메트릭이 이것에서 나온다는 공개 근거는 없다 [추론]. NetApp Harvest는 같은 ONTAP 필드를 Prometheus `volume_read_ops`, `volume_read_data` 등으로 내보낸다 [문서 H1].
4. 클론 쪽: 커널 6.18에서 `/proc/net/rpc/nfsd`의 `io`(읽기·쓰기 바이트), `rpc`(전체 호출 수), `proc4ops`(v4 연산별 수)는 **netns별**이고, `proc3`·`proc4` 줄(버전별 프로시저 수)은 **모든 netns 합계**다 [스펙 K1~K4, 소스에서 추론]. 그래서 v4.1은 볼륨별 읽기·쓰기 IOPS를 얻을 수 있고, v3는 볼륨별 전체 RPC 수만 얻는다 [추론].
5. Prometheus 관례는 기본 단위(초, 바이트), 단위 접미사, 누적 카운터의 `_total`이다 [문서 P1]. Azure의 "5분 평균 bytes/s"는 Prometheus에서 바이트 카운터 + `rate(...[5m])`로 재현하는 것이 관례에 맞다 [추론].

## 사용자에게 보이는 동작

### 리소스와 API (Azure Monitor 메트릭 계약)

- 메트릭이 붙는 리소스 형식: `Microsoft.NetApp/netAppAccounts/capacityPools`(풀), `Microsoft.NetApp/netAppAccounts/capacityPools/volumes`(볼륨) [문서 D1][D2].
- 조회 경로: Azure Monitor 메트릭 REST(`{resourceUri}/providers/Microsoft.Insights/metrics?metricnames=...&interval=PT5M&aggregation=Average`)와 포털 "Metrics" 블레이드 [문서 D3 "natively integrated into Azure monitor"]. 정확한 Metrics REST api-version은 이번에 확인 못 함 [미확인].
- 모든 행의 "Advanced platform metrics" = No, "DS Export"(진단 설정 내보내기) = Yes [문서 D1][D2].

#### 볼륨 메트릭 (`capacityPools/volumes`) — 범위 안의 것 [문서 D1]

| 분류 | 표시 이름 | REST 이름 | 단위 | 집계 | 차원 | 비고 |
| --- | --- | --- | --- | --- | --- | --- |
| 사용량 | Volume allocated size | `VolumeAllocatedSize` | Bytes | Average | 없음 | "The provisioned size of a volume" |
| 사용량 | Volume Consumed Size | `VolumeLogicalSize` | Bytes | Average | 없음 | "Logical size of the volume (used bytes)". 개념 문서: "includes logical space used by active file systems and snapshots" [D3] |
| 사용량 | Volume snapshot size | `VolumeSnapshotSize` | Bytes | Average | 없음 | "Size of all snapshots in volume" |
| 사용량 | Percentage Volume Consumed Size | `VolumeConsumedSizePercentage` | Percent | Average | 없음 | "including snapshots". 개념 문서: min/max 집계 미지원 [D3] |
| 사용량 | Volume Inodes Used / Total / Quota / Percentage | `VolumeInodesUsed`, `VolumeInodesTotal`, `VolumeInodesQuota`, `VolumeInodesPercentage` | Count, Count, Count, Percent | Average | 없음 | Quota는 지원 요청으로 늘렸을 때만 0이 아님 [D3] |
| 처리량 | Read / Write / Other / Total throughput | `ReadThroughput`, `WriteThroughput`, `OtherThroughput`, `TotalThroughput` | BytesPerSecond | Average | 없음 | Other = "not read or write". Total = read+write+other [D3] |
| IOPS | Read / Write / Other / Total iops | `ReadIops`, `WriteIops`, `OtherIops`, `TotalIops` | CountPerSecond | Average | 없음 | Other = 메타데이터 등 [D3] |
| 지연 | Average read / write / other latency | `AverageReadLatency`, `AverageWriteLatency`, `AverageOtherLatency` | MilliSeconds | Average | 없음 | "per operation". "measured within the storage service and doesn't include network latency" [D3] |
| QoS | Throughput limit reached | `ThroughputLimitReached` | Count | Average | 없음 | "1 if it has and 0 if not" |
| QoS | QoS latency delta | `QosLatencyDelta` | MilliSeconds | Average | 없음 | "Latency for Exceeded Throughput" [D1], "the total QoS latency for a volume over a time period" [D3] |

- 범위 밖으로 이름만: 백업 `Cbs*` 5개, 복제 `Xregion*` 7개, cool tier `VolumeCoolTier*` 3개 [문서 D1]. cache 볼륨 메트릭("Cache volume miss blocks", "Client requested blocks" 등)과 구독 쿼터 메트릭은 개념 문서에만 있다 [문서 D3].

#### 풀 메트릭 (`capacityPools`) [문서 D2]

| 표시 이름 | REST 이름 | 단위 | 집계 | 설명 |
| --- | --- | --- | --- | --- |
| Pool Allocated Size | `VolumePoolAllocatedSize` | Bytes | Average, Total | "Provisioned size of this pool" |
| Pool Allocated To Volume Size | `VolumePoolAllocatedUsed` | Bytes | Average | 정의 페이지: "Allocated used size of the pool". 개념 문서: "The total of volume quota (GiB) in a given capacity pool" [D3] |
| Pool Consumed Size | `VolumePoolTotalLogicalSize` | Bytes | Average, Total | "Sum of the logical size of all the volumes belonging to the pool" |
| Total Snapshot size for the pool | `VolumePoolTotalSnapshotSize` | Bytes | Average | "Sum of snapshot size of all volumes in this pool" |
| Pool allocated throughput | `VolumePoolAllocatedToVolumeThroughput` | BytesPerSecond | Average | "Sum of the throughput of all the volumes belonging to the pool" |
| Provisioned throughput for the pool | `VolumePoolProvisionedThroughput` | BytesPerSecond | Average | "Provisioned throughput of this pool" |

- 풀 처리량 메트릭 두 개는 ARM 속성 `utilizedThroughputMibps`, `totalThroughputMibps`와 뜻이 같아 보인다(배정 합, 풀 총량) [추론 — 설명 문장 비교, 처리량 제한 브리프 D6 인용]. 단위는 MiB/s가 아니라 BytesPerSecond다 [문서 D2].
- 풀 메트릭에는 IOPS·실측 처리량이 없다 [문서 D2]. 실측은 볼륨 단위뿐이다.

#### 출처끼리 다른 점 (둘 다 남김)
- 개념 문서 [D3]에는 "Volume Quota Size"("The quota size (GiB) the volume is provisioned with")가 따로 있지만, 정의 페이지 [D1]의 볼륨 표에는 그 메트릭이 없고 `VolumeAllocatedSize`만 있다.
- `VolumePoolAllocatedUsed`의 설명이 "Allocated used size of the pool"[D2]과 "total of volume quota"[D3]로 다르다. 이름("Pool Allocated To Volume Size")으로 보면 [D3] 쪽(할당량 합)이 맞다 [추론].
- 개념 문서는 "Total throughput"을 두 번 적는다(한 번은 "Sum of all throughput", 한 번은 "read, write, and other") [D3]. 같은 메트릭이다 [추론].

### 비동기 동작
- 해당 없음. 메트릭은 읽기 전용이고 ANF 리소스의 `provisioningState`와 무관하다 [추론 — 메트릭은 Azure Monitor 쪽 GET만 있음].

### 제약과 한도 (수집 간격, 지연, 보존)
- 수집 간격: "Unless otherwise specified, Azure NetApp Files metrics represent values over a five-minute average." 짧은 급증은 평균에 묻힌다(예: 100/120/500/110/120 MiB/s → 190 MiB/s로 표시) [문서 D3].
- 시간 단위(time grain): 모든 메트릭이 `PT5M, PT15M, PT30M, PT1H, PT6H, PT12H, P1D` [문서 D1][D2]. 1분 단위가 없다.
- "Throughput limit reached"도 5분마다 수집되며, 1은 "직전 5분 창 안에 한도에 닿은 적이 있다"는 뜻이다 [문서 D3].
- 메트릭이 포털에 보이기까지의 지연, 보존 기간: ANF 문서에는 없다. Azure Monitor 플랫폼 메트릭 일반 보존(93일로 알려짐)은 이번에 원문을 확인 못 함 [미확인].

### 오류 상황
- 범위 밖(Azure Monitor 공통 오류). 확인 못 함 [미확인].

## 데이터 플레인에서 보이는 효과
- 메트릭 자체는 클라이언트에 효과가 없다. 클라이언트가 만든 I/O가 메트릭에 나타날 뿐이다.
- 클라이언트 `df`와 메트릭의 관계: "The `df` command provides an accurate *available space*. However, the *consumed or used space* is an estimate when snapshots are generated on the volume. The consumed snapshot capacity counts towards the total consumed space on the volume. To get the absolute volume consumption, including the capacity used by snapshots, use the Azure NetApp Metrics" [문서 D4]. `du`는 스냅샷 공간을 세지 않는다 [문서 D4]. 즉 ANF에서 "Volume Consumed Size"는 스냅샷을 포함하고, `df` used는 추정이다.
- 처리량 정의: "The amount of data transmitted across the wire (read/write/other) between Azure NetApp Files and the client ... measured in bytes per second" [문서 D3]. 지연 정의: "from the time it arrives to the time it's processed and is ready to be sent back to the client" [문서 D3].
- "Other IOPS"에 들어가는 NFSv3 프로시저(NULL, GETATTR, SETATTR, LOOKUP, ACCESS, READLINK, CREATE, MKDIR, SYMLINK, MKNOD, REMOVE, RMDIR, RENAME, LINK, READDIR, READDIRPLUS, FSSTAT, FSINFO, PATHCONF, COMMIT)와 NFSv4.1 연산(COMPOUND, ACCESS, CLOSE, COMMIT, GETATTR, LOOKUP, OPEN, PUTFH, SETATTR 등) 목록이 문서에 있다 [문서 D3]. 즉 COMMIT은 Write가 아니라 Other다. v4.1 목록이 COMPOUND와 개별 연산을 모두 넣어서 한 COMPOUND 안의 여러 연산을 각각 세는지는 문서로 판단할 수 없다 [미확인].

## ONTAP 대응 개념

### ONTAP REST 볼륨 필드 [ONTAP O1]
- "Performance of a volume can be monitored by the `metric.*` and `statistics.*` fields. ... The `metric.*` fields denote an average whereas `statistics.*` fields denote a real-time monotonically increasing value aggregated across all nodes." (`resources/volume.py` 개요)
- `metric.{iops,throughput,latency}.{read,write,other,total}`, `metric.duration`(`PT15S`, `PT4M`, `PT30M`, `PT2H`, `P1D`, `PT5M`), `metric.status`, `metric.timestamp`. "other"는 "metadata operations, such as directory lookups" (`performance_metric_io_type`).
- `statistics.{iops_raw,throughput_raw,latency_raw}.{read,write,other,total}`, `statistics.nfs_ops_raw`, `statistics.cifs_ops_raw`, `statistics.timestamp`, `statistics.status`. 예시: `"latency_raw": {"other": 38298, ...}, "iops_raw": {"other": 3, ...}` (누적).
- 단위(성능 메트릭 API 개요): "IOPs are the number of I/O operations reported per second, throughput is the amount of I/O operations measured in bytes per second and latency is the average response time for an IOP, reported in microseconds." 시간 범위를 주지 않으면 "statistics collected at 15 second intervals over the last hour" (`resources/performance_metric.py`, 애그리거트 메트릭 API 설명. 볼륨 `/api/storage/volumes/{uuid}/metrics`도 같은 모양이라고 본다 [추론]).
- 공간: `space.size`("Total provisioned size"), `space.used`("The virtual space used ... before storage efficiency"), `space.available`, `space.percent_used`, `space.logical_space.used`, `space.logical_space.used_by_snapshots`, `space.snapshot.used`("The total space used by snapshots in the volume"), `space.snapshot.reserve_size`, `space.footprint`("Data used for this volume in the aggregate") (`models/volume_space*.py`).
- inode: `files.maximum`, `files.used` (`models/volume_files.py`).
- QoS 워크로드: `/api/storage/qos/workloads`(`qos workload show`)는 "a storage object that is tracked by QoS"이고 정책·상한 필드만 보였다 [ONTAP O1 `resources/qos_workload.py`]. QoS 지연 분해(예: CLI `qos statistics volume latency show`의 Throttle 열)는 이번에 원문을 확인 못 함 [미확인].

### ANF ↔ ONTAP 대응표

| ANF 메트릭 | 가장 가까운 ONTAP 필드 | 근거 표시 |
| --- | --- | --- |
| Read/Write/Other/Total iops | `metric.iops.*` / `statistics.iops_raw.*` | 필드 [ONTAP O1], 대응 [추론 — 이름·분류가 같다] |
| Read/Write/Other/Total throughput | `metric.throughput.*` / `statistics.throughput_raw.*` | 필드 [ONTAP O1], 대응 [추론] |
| Average read/write/other latency (ms) | `metric.latency.*` (µs) / `latency_raw ÷ iops_raw` | 필드·단위 [ONTAP O1], Harvest 계산법 [문서 H1], 대응 [추론]. 단위가 ms 대 µs로 다르다 |
| Volume allocated size | `space.size` | [추론] |
| Volume Consumed Size (`VolumeLogicalSize`, 스냅샷 포함) | `space.logical_space.used` 또는 `space.used` | 이름의 "Logical"이 `logical_space`와 같다는 것만 근거 [추론]. 어느 것인지 [미확인] |
| Volume snapshot size | `space.snapshot.used` 또는 `space.logical_space.used_by_snapshots` | [추론] |
| Percentage Volume Consumed Size | `space.percent_used` 또는 `logical_space.used_percent` | [추론] |
| Volume Inodes Used / Total | `files.used` / `files.maximum` | [추론] |
| Throughput limit reached, QoS latency delta | QoS 지연 분해의 throttle 성분 | 이름("QoS limits", "Latency for Exceeded Throughput")에서 [추론]. ONTAP 원문 [미확인] |
| Pool Consumed Size 등 풀 메트릭 | 직접 대응 없음(볼륨 값의 합) | 풀은 ONTAP 객체가 아니다(풀 브리프 [추론] 인용) |

- 간접 단서: ANF cache 볼륨 메트릭 "Cache volume miss blocks", "Client requested blocks"[D3]는 ONTAP 볼륨 `statistics.flexcache_raw.cache_miss_blocks`, `client_requested_blocks`[O1]와 이름이 같다. ANF 메트릭이 ONTAP 카운터를 이름만 바꿔 내보낸다는 가설을 지지하지만 증명은 아니다 [추론].
- 면접에서 안전한 문장: "ANF 볼륨 메트릭은 read/write/other/total × IOPS·throughput·latency로 나뉘는데, ONTAP REST 볼륨의 `metric`/`statistics` 필드가 같은 구조다. ANF가 내부에서 그 카운터를 쓰는지는 공개되지 않았다. NetApp Harvest는 ONTAP의 같은 필드를 Prometheus로 내보낸다."

## 클론의 Linux 출처 후보 (사실 위주, 설계는 메인)

### 1. 볼륨 사용량
- ext4 마운트(`ns/<creationToken>`)의 `statfs`: 활성 파일시스템 사용량. 클론 스냅샷 공간은 볼륨 할당량·`df`에 잡히지 않고 씬 풀에서 나간다 [ADR R-09, 스냅샷 조사]. 그래서 ANF "Volume Consumed Size(스냅샷 포함)"와 뜻이 다르다 [추론].
- dm-thin 풀 상태 줄: `<transaction id> <used metadata blocks>/<total metadata blocks> <used data blocks>/<total data blocks> <held metadata root> ro|rw|out_of_data_space ...` [스펙 K5 — thin-provisioning.rst 303~327행]. 풀 사용률(R-09)은 여기서(`lvs -o data_percent anf/aggr0`도 같은 값) 얻는다 [추론 — lvs가 이 상태를 읽음은 원문 미확인].
- thin LV의 `data_percent`는 매핑된 블록 비율이다. 스냅샷과 공유하는 블록도 세고, ext4가 지운 블록은 discard가 없으면 매핑이 남는다 [추론 — dm-thin 동작, discard 옵션 K5 277~323행]. 스냅샷만의 고유 블록 수는 dm-thin 상태 줄에 없다. `thin_ls`(thin-provisioning-tools, 메타데이터 스냅샷 필요)가 장치별 exclusive/shared 바이트를 보여 준다고 알려져 있으나 이번에 원문 확인 못 함 [미확인].
- inode: `statfs`의 `f_files`/`f_ffree` [추론 — POSIX statvfs].

### 2. 처리량 (볼륨별)
- 볼륨마다 knfsd 인스턴스와 netns가 따로 있으므로 netns 단위 카운터가 곧 볼륨 단위다 [CLAUDE.md D-12].
- 이미 잰 두 값 [ADR §8 인용]: `/proc/<pid>/net/dev`의 `ifb0` 송신 바이트(skb 길이, 데이터보다 0.5% 안팎 큼)와 `tc -s class show dev ifb0`의 HTB Sent 바이트(세그먼트별 헤더 포함 wire 바이트, `ifb0`보다 4.2~4.4% 큼, 한도가 이 값에 걸림). 둘 다 읽기·쓰기 합이라 방향을 나누지 못한다 [추론 — ifb0에 양방향을 모으는 구조(CLAUDE.md FR-08)].
- `eth0` 수신/송신 바이트(`/proc/<pid>/net/dev`): 클라이언트 쓰기 ≈ eth0 수신, 읽기 ≈ eth0 송신으로 방향을 나눌 수 있다 [추론]. `/proc/net/dev`는 역사적 텍스트 인터페이스이고 rtnetlink가 권장 경로다 [스펙 K6 statistics.rst 125, 152행].
- knfsd `io` 줄: `io <bytes-read> <bytes-written>` = "bytes returned to read requests", "bytes passed in write requests"(`NFSD_STATS_IO_READ/WRITE`, `struct nfsd_net`의 per-netns `counter[]`) [스펙 K1 stats.c, K2 netns.h 39~40, 179~180행]. 헤더 없는 순수 데이터 바이트로 읽기·쓰기를 나눠 준다. ANF Read/Write throughput에 가장 가깝다 [추론]. 단 ANF Total에 들어가는 Other(메타데이터) 바이트는 없다.
- export별 통계: nfsd 파일시스템의 `export_stats` 파일이 export마다 `fh_stale`, `io_read`, `io_write`를 보인다 [스펙 K7 export.c 756~790행, nfsctl.c 1279행]. 볼륨 export와 `.snapshot/<name>` export가 따로 잡힐 것이다 [추론]. nfsd 파일시스템은 netns로 키를 잡는다(`get_tree_keyed(..., fc->net_ns)`, nfsctl.c 1321행) [스펙 K8].

### 3. IOPS (볼륨별) — "가능하면 IOPS"의 관건
- `/proc/net/rpc/nfsd`는 `svc_proc_register(net, &nn->nfsd_svcstats, ...)`로 netns마다 등록된다 [스펙 K1, K9 sunrpc/stats.c 294, 315행]. 호스트에서 `/proc/<인스턴스 pid>/net/rpc/nfsd`로 볼륨 netns의 파일을 읽을 수 있다 [추론 — `/proc/<pid>/net`은 그 프로세스 netns의 proc_net. ADR §8이 `/proc/<pid>/net/dev`를 같은 방식으로 씀].
- 줄별 범위 (커널 v6.18 소스 기준):

| 줄 | 내용 | 범위 | 근거 |
| --- | --- | --- | --- |
| `rc`, `fh`, `io` | 응답 캐시, stale FH, 읽기/쓰기 바이트 | netns별 | [스펙 K1, K2] |
| `th` | 스레드 수 | 전역 (`nfsd_th_cnt`) | [스펙 K1] |
| `net`, `rpc` | 네트워크 수, 전체 RPC 호출 수·불량 수 | netns별 (`nn->nfsd_svcstats`) | [스펙 K1, K9 82~100행] |
| `proc2`/`proc3`/`proc4` | 버전별 프로시저 호출 수 (v3 READ=6, WRITE=7) | **전역** — `prog->pg_vers[i]->vs_count`. `vs_count`는 `struct svc_version`의 per-cpu 필드이고, nfsd의 버전 객체는 정적 배열 `nfsd_version[]`(`[3] = &nfsd_version3`)이다 | 필드 [스펙 K10 svc.h 393행, K11 nfssvc.c 97~101행], 전역이라는 결론 [추론 — 소스 구조] |
| `proc4ops` | NFSv4 연산별 수 (READ=25, WRITE=38 등) | netns별 (`nn->counter[NFSD_STATS_NFS4_OP(i)]`) | [스펙 K1, K2 42~44행] |

- 결론 [추론]: NFSv4.1 볼륨은 `proc4ops`로 읽기·쓰기·기타 연산 수를 볼륨별로 얻는다. NFSv3 볼륨은 `rpc` 줄의 전체 호출 수(Total IOPS 근사, NULL 포함)만 볼륨별이고, 읽기·쓰기 연산 수는 볼륨별로 나뉘지 않는다(모든 인스턴스의 합). 이 결론은 실제 WSL 커널(Microsoft 6.18 계열)에서 재 보지 않았다.
- v4.1에서 IOPS 단위: `proc4ops`는 COMPOUND 안의 개별 연산(PUTFH, SEQUENCE 포함)을 센다 [추론 — 카운터 이름]. ANF "Other IOPS" 목록도 COMPOUND와 개별 연산을 함께 적는다 [문서 D3].
- 지연: knfsd 카운터에는 연산별 서버 지연이 없다 [추론 — K1 형식에 시간 항목 없음]. tracepoint(`nfsd:*`)나 eBPF는 조사 범위 밖이다.

### 4. "한도 도달" 후보
- HTB 클래스 `overlimits`: 클래스 모드가 `HTB_CANT_SEND`로 바뀔 때마다 `cl->overlimits++` [스펙 K12 sch_htb.c 566~572행], `tc -s class show`에 노출(1329행). 구간 안에서 증가했으면 "한도에 닿았다"로 쓸 수 있다 [추론]. 정확히 ANF의 판정 기준과 같은지는 알 수 없다 [미확인].

## Prometheus 관례

- 이름 [문서 P1 naming.md]: 단일 단어 애플리케이션 접두사(예: `http_request_duration_seconds`), 하나의 단위·하나의 양, **기본 단위**(초, 바이트 — 밀리초·메가바이트가 아님), 단위 접미사(복수형), 누적 카운트는 `_total`(예: `process_cpu_seconds_total`). 같은 메트릭의 라벨 값들은 같은 논리적 대상을 재야 한다.
- counter vs gauge [문서 P2 instrumentation.md "Counter vs. gauge, summary vs. histogram"]: 내려갈 수 있는 값(사용량, 진행 중 작업 수)은 gauge, 증가만 하는 값(바이트, 연산 수, 요청 수)은 counter로 두고 `rate()`로 초당 값을 만든다. 히스토그램·서머리는 [문서 P3 histograms.md].
- HTTP 요청 지표 관례: 문서 예시 이름 `http_request_duration_seconds`(히스토그램) [문서 P1]. FastAPI용 라이브러리(`prometheus-fastapi-instrumentator`)나 OpenTelemetry HTTP 시맨틱 규약의 기본 이름·라벨은 이번에 원문을 확인 못 함 [미확인]. 라벨에 실제 경로 대신 경로 템플릿을 써야 카디널리티가 터지지 않는다는 것은 ADR §8이 이미 정했다("경로 템플릿, 메서드, 상태 코드별").
- Azure Monitor 이름 ↔ Prometheus 이름: 공식 대응 규칙은 찾지 못했다 [미확인]. 참고할 선례:
  - NetApp Harvest(NetApp 공식 오픈소스, ONTAP → Prometheus) [문서 H1]: `volume_read_ops`(← `statistics.iops_raw.read`, 단위 per_sec, type rate), `volume_read_data`(← `statistics.throughput_raw.read`, b_per_sec, rate), `volume_read_latency`(← `statistics.latency_raw.read`, microsec, average, base `iops_raw.read`), `volume_size_used`, `volume_size_used_percent`, `volume_snapshots_size_used`, `volume_inode_files_used`, `qos_ops`, `qos_latency`. Harvest는 원시 카운터를 수집기에서 rate로 계산해 gauge로 내보낸다 [추론 — "Type: rate"]. Prometheus 기본 단위 관례(`_bytes`, `_seconds`, `_total`)와는 다르다.
  - Azure Monitor → Prometheus 내보내기 도구(예: azure-metrics-exporter)의 이름 규칙은 확인 못 함 [미확인].
- Azure "5분 평균"과의 대응 [추론]: Azure Average(5분)는 Prometheus에서 카운터에 `rate(x_total[5m])`를 한 값과 같은 뜻이다. 클론은 스크레이프 간격을 짧게 두어 "부하를 걸면 그래프에 나타난다"를 빨리 보일 수 있다. 이는 ANF와 다른 점(ANF는 최소 5분 단위)으로 적어야 한다.

## 구현 범위 후보

### 이번에 재현할 것 (후보)
- 볼륨 처리량 Read/Write(/Total): knfsd `io` 줄(netns별, 방향 분리) 또는 `eth0`/`ifb0` 바이트. 수락 기준 "부하를 걸면 그래프에 나타난다"의 중심.
- 볼륨 사용량: `statfs` 기반 used/size/percent, inode. 스냅샷 크기 제외라는 차이를 문서화.
- 풀 사용률(R-09): dm-thin 풀 데이터·메타데이터 사용률. ANF에는 없는 클론 고유 메트릭이다 (aggregate 사용률에 해당 [추론]).
- IOPS: v4.1은 `proc4ops`로 Read/Write/Other/Total, v3는 `rpc` 호출 수로 Total만 [추론 결론에 따름].
- 한도 정보: 볼륨의 설정 한도(gauge)와 HTB `overlimits`(counter).
- anf-api: 요청 수·지연 히스토그램(경로 템플릿·메서드·상태 코드), 작업 수·소요 시간(종류·결과), 진행 중 작업 수 [ADR §8].

### 다음으로 미룰 것
- 지연(Average read/write/other latency): knfsd에 서버 쪽 지연 카운터가 없다. tracepoint/eBPF가 필요하다.
- `QosLatencyDelta`: 대응 신호가 없다.
- 스냅샷 크기(고유 블록): `thin_ls`와 메타데이터 스냅샷이 필요하고 원문을 확인 못 했다.
- 백업·복제·cool tier·cache·구독 쿼터 메트릭: 해당 기능 없음.

### 리더·사용자가 정해야 할 선택지
1. **메트릭 이름 체계**: (a) Prometheus 관례(`anf_volume_read_bytes_total` 등, 기본 단위 + `_total`)에 라벨·문서로 Azure REST 이름을 대응, (b) Azure REST 이름을 그대로 snake_case로(`anf_volume_read_throughput` 등, 단위가 bytes/s gauge), (c) Harvest 이름(`volume_read_data`, `volume_read_ops`)을 따름. (a)는 Prometheus 관례에 맞고, (c)는 NetApp 맥락 설명에 유리하다.
2. **카운터를 내보낼지 비율을 내보낼지**: 원시 카운터 + PromQL `rate()`(관례) vs 수집기가 5분 평균을 계산한 gauge(ANF와 같은 모양).
3. **처리량 출처**: knfsd `io`(데이터 바이트, 방향 분리, 메타데이터 없음) / `eth0` 수신·송신(방향 분리, 헤더·메타데이터 포함) / `ifb0` 또는 HTB Sent(합만, 한도와 같은 기준). ADR §8이 FR-12로 미룬 결정이다.
4. **v3 IOPS**: v3 볼륨은 Total(RPC 수)만 내보낼지, 아니면 v3 Read/Write IOPS를 "지원 안 함"으로 비울지. 전역 `proc3`를 볼륨별로 쓰면 틀린 값이 된다.
5. **Volume Consumed Size의 뜻**: ext4 used(스냅샷 제외)를 그 이름으로 낼지, 이름을 바꿔 차이를 드러낼지. thin LV `data_percent`를 함께 낼지.
6. **스크레이프·조회 간격**: Prometheus 스크레이프 간격과 대시보드 `rate` 창(예: 15 s 수집, 1 m 창)과 ANF 5분 평균의 차이를 어떻게 문서화할지.
7. **라벨**: 볼륨 식별자(볼륨 uuid, ARM 리소스 ID, 계정/풀/볼륨 이름)를 어떤 라벨로 둘지. Azure 메트릭은 차원 없이 리소스 단위라서, Prometheus에서는 리소스 식별 라벨이 그 역할을 한다 [추론].
8. **누가 수집하나**: storage agent가 `/metrics`로 볼륨·풀 값을 내고 anf-api가 API·작업 값을 낸다(ADR §8)는 틀은 있다. 볼륨 ↔ ARM 이름 매핑을 어느 쪽이 붙일지(agent는 LVM 태그에 uuid·경로만 앎)는 미정.

### 검증 기준 후보 (클라이언트에서 관찰)
1. 클라이언트 컨테이너에서 fio로 쓰기를 걸면, 그 볼륨의 쓰기 처리량 메트릭이 오르고 같은 시각 다른 볼륨의 값은 오르지 않는다(netns별 분리).
2. 읽기만 걸면 읽기 처리량이 오르고 쓰기 처리량은 거의 0이다(방향 분리를 택했을 때).
3. 한도 X MiB/s 볼륨에 포화 부하를 걸면 처리량 메트릭(초당 바이트)이 X×1,048,576 근처에서 멈추고, 한도 도달 신호(HTB `overlimits` 증가 등)가 1이 된다.
4. v4.1 볼륨에 작은 블록 랜덤 읽기를 걸면 Read IOPS가 fio가 보고한 IOPS와 비슷하다(허용 오차는 설계에서). v3 볼륨에서는 정한 선택지대로 Total만 나오거나 비어 있다.
5. 파일을 써서 N GiB를 채우면 사용량 메트릭이 N GiB 늘고, 클라이언트 `df` used와 맞는다. 스냅샷 뒤 덮어쓰면 볼륨 사용량은 그대로이고 풀 사용률이 오른다(R-09의 차이를 보임).
6. anf-api에 볼륨 PUT을 하면 요청 카운터가 경로 템플릿·메서드·상태 코드 라벨로 늘고, 작업 완료 뒤 작업 소요 시간 히스토그램에 한 건이 들어간다.
7. 대시보드 차트가 Prometheus 쿼리 API에서 읽은 값을 그리고, 부하를 건 뒤 차트에 나타난다(PRD 수락 기준).
8. 메트릭 수집이 데이터 플레인을 바꾸지 않는다: 수집 중에도 한도·I/O 결과가 같다(수집기가 tc·export를 건드리지 않는다).

## 미확인 목록

| 항목 | 설계를 막는가 (리더 판단용) | 시도한 곳 |
| --- | --- | --- |
| `proc3` 전역·`proc4ops` netns별이라는 결론의 실측 | 선택지 4. 소스 근거는 강하지만 WSL 커널에서 재 보지 않음. 설계 전에 인스턴스 둘로 확인 권장 | 커널 v6.18 소스 K1, K2, K9~K11. `net/sunrpc/svc.c`(증가 위치)는 429로 못 받음 |
| Azure Monitor 메트릭 보존 기간·표시 지연·Metrics REST api-version | 막지 않음 (개념 문서용) | ANF 문서 D3, D5에 없음. Azure Monitor 문서는 시도 못 함 |
| `VolumeLogicalSize`가 ONTAP `space.used`인지 `logical_space.used`인지 | 막지 않음 ([추론]으로 설명) | Learn D1·D3, ONTAP 휠 O1 |
| `ThroughputLimitReached`·`QosLatencyDelta`의 ONTAP 원천(QoS throttle 지연 등) | 막지 않음 | ONTAP 휠 `qos_workload`(지연 필드 없음). docs.netapp.com은 시도 못 함 |
| "Volume Quota Size" 메트릭 존재 여부(개념 문서에만 있음) | 막지 않음 | D1 vs D3 |
| v4.1 IOPS를 COMPOUND 단위로 세는지 연산 단위로 세는지(ANF) | 선택지 4 세부 | D3 |
| `thin_ls`로 스냅샷 고유 크기를 얻는 방법 | 미룬 항목 | 원문 받지 않음 |
| FastAPI 계측 라이브러리·OpenTelemetry HTTP 메트릭의 기본 이름·라벨 | 막지 않음 (ADR §8로 충분) | 시도 못 함 |
| Azure Monitor → Prometheus 이름 대응 관례(azure-metrics-exporter 등) | 선택지 1 | 시도 못 함 |
| `lvs data_percent`가 dm-thin 상태 줄에서 나오는지 | 막지 않음 | K5만 읽음 |

## 후속 조사 목록
- ONTAP `qos statistics volume latency show`의 지연 분해(Network/Throttle/Data 등)와 ANF `QosLatencyDelta`의 관계 (개념 문서용).
- nfsd tracepoint로 연산별 서버 지연을 얻는 방법 (지연 메트릭을 할 때).
- Elastic 서비스 수준의 별도 메트릭 문서(`elastic-metrics.md`) — 범위 밖.
- 구독 쿼터 메트릭(Snapshots per volume 등) — 클론 255개 한도와 이어 볼 수 있음.

## 출처
- [D1] Microsoft Learn — Supported metrics for Microsoft.NetApp/netAppAccounts/capacityPools/volumes — https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-netapp-netappaccounts-capacitypools-volumes-metrics (2026-11-10 받음, ms.date 2026-07-31, git_commit_id `6826eb8f500267014038df72b1cfc5e559191f41`, 원본 저장소 `MicrosoftDocs/azure-monitor-docs-pr`는 비공개). 사본: `_workspace/metrics/sources/docs/learn-supported-metrics-capacitypools-volumes.html`, 표 추출 `.txt`.
- [D2] 같은 페이지의 capacityPools 판 — https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-metrics/microsoft-netapp-netappaccounts-capacitypools-metrics (같은 날짜·커밋). 사본: `learn-supported-metrics-capacitypools.html`, `.txt`.
- [D3] Microsoft Learn — Metrics for Azure NetApp Files (`azure-netapp-files-metrics.md`, ms.date 09/11/2026). 저장소 `MicrosoftDocs/azure-docs`, 커밋 `121e31ad51402bbcc82f923c0951ac55cef58de2`. 사본 재사용: `_workspace/throughput-limit/sources/docs/azure-netapp-files-metrics.md`.
- [D4] Microsoft Learn — Monitor the capacity of a volume (`monitor-volume-capacity.md`, ms.date 09/04/2024), 같은 커밋. 사본: `_workspace/metrics/sources/docs/`.
- [D5] Microsoft Learn — Ways to monitor Azure NetApp Files (`monitor-azure-netapp-files.md`, ms.date 04/18/2025), 같은 커밋. 같은 곳에 `azure-netapp-files-performance-metrics-volumes.md`도 받았지만 읽지 않았다.
- [O1] NetApp ONTAP Python client library `netapp-ontap` 9.19.1.0 (PyPI wheel, "automatically generated based on the ONTAP REST API documentation"): `resources/volume.py`(사본 재사용 `_workspace/throughput-limit/sources/ontap/volume.py.txt`), `resources/volume_metrics.py`, `models/volume_statistics.py`, `models/performance_metric_io_type.py`, `models/performance_metric_raw.py`, `models/volume_space*.py`, `models/volume_files.py`, `resources/performance_metric.py`, `resources/qos_workload.py`. 휠: `_workspace/snapshot/sources/ontap/wheel/`, 추출: `_workspace/metrics/sources/ontap/`.
- [H1] NetApp Harvest — `docs/ontap-metrics.md`, 저장소 `NetApp/harvest`, 커밋 `9c0f8f6d6e51ed9a16d6a189de36f10ebf28be83`. 사본: `_workspace/metrics/sources/prometheus/harvest-ontap-metrics.md`.
- [P1][P2][P3] Prometheus docs — `docs/practices/naming.md`, `instrumentation.md`, `histograms.md`, 저장소 `prometheus/docs`, 커밋 `cc0672badce86173b9afaa95a59904576bcd6d6a` (https://prometheus.io/docs/practices/naming/). 사본: `_workspace/metrics/sources/prometheus/`.
- 커널: 저장소 `torvalds/linux`, 태그 `v6.18`(태그 객체 `f7b88edb52c8dd01b7e576390d658ae6eef0e134`). 사본: `_workspace/metrics/sources/kernel/` (경로의 `/`를 `_`로 바꾼 파일 이름).
  - [K1] `fs/nfsd/stats.c` (`/proc/net/rpc/nfsd` 형식, `nfsd_proc_stat_init`)
  - [K2] `fs/nfsd/netns.h` (`NFSD_STATS_*`, per-netns `counter[]`, `nfsd_svcstats`)
  - [K3] `fs/nfsd/stats.h` (증가 함수, export 통계 동시 증가)
  - [K5] `Documentation/admin-guide/device-mapper/thin-provisioning.rst` (풀 상태 줄 303~327행)
  - [K6] `Documentation/networking/statistics.rst` (`/proc/net/dev`, rtnetlink)
  - [K7] `fs/nfsd/export.c` (`export_stats` 출력 756~790행)
  - [K8] `fs/nfsd/nfsctl.c` (`export_stats` 파일 1279행, `get_tree_keyed` 1321행)
  - [K9] `net/sunrpc/stats.c` (`svc_seq_show` 82~117행, `svc_proc_register` 294·315행)
  - [K10] `include/linux/sunrpc/svc.h` (`vs_count` 393행)
  - [K11] `fs/nfsd/nfssvc.c` (`nfsd_version[]` 97~101행)
  - [K12] `net/sched/sch_htb.c` (`overlimits` 566~572, 1216, 1329행)
- 저장소 안 근거: `docs/ADR.md` §8, R-09, D-08, `docs/PRD.md` FR-12·§8, `CLAUDE.md` FR-08 항목, `_workspace/throughput-limit/01_researcher_brief.md`.

## 변경 이력
- 2026-11-10 골격 저장
- 2026-11-10 전 절 작성. 30턴 상한에 가까워 "한도 도달"로 마감
