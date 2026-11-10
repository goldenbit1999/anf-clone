# 메트릭 (FR-12) 설계

- 작성: 2026-11-10 (메인). 조사 `01_researcher_brief.md`(한도 도달), 스파이크 `_workspace/spikes/S8.md`(조건부 통과)
- PRD FR-12: "볼륨 사용량, 처리량, 가능하면 IOPS를 수집한다. API 요청과 비동기 작업의 지표도 수집한다." 수락: "Prometheus에서 조회할 수 있다. 대시보드가 차트로 보여 준다. 클라이언트에서 부하를 걸면 그래프에 나타난다."
- 묻는 결정: 없음. ADR §8이 FR-12로 미뤄 둔 것(처리량 출처, 이름 대응)을 여기서 정한다. 확정된 D-nn을 바꾸지 않고 PRD 수락 기준을 줄이지 않는다. 결정 1~14는 모두 `자동 채택`이다.

## 1. 구조

```
클라이언트 I/O → 볼륨 인스턴스(knfsd, netns)
                     │  /proc/<pid>/net/rpc/nfsd (io, rpc, proc4ops)
storage agent ───────┘  statvfs(ns/<token>), LVM 태그, dmsetup status(aggr0)
   GET /metrics (127.0.0.1:8090)          anf-api GET /metrics (127.0.0.1:8080)
            └──────────── Prometheus (컨테이너, host 네트워크, 127.0.0.1:9090, 5 s 수집) ───────┘
                                   │ /api/v1/query_range
                     대시보드 (Vite 프록시 /prometheus → 9090) → 볼륨 차트
```

- 두 프로세스가 각자 `/metrics`를 낸다(ADR §8). Prometheus가 둘을 긁고, 대시보드는 Prometheus 쿼리 API만 읽는다(D-08).
- agent의 값은 **스크레이프 때 읽는다**(백그라운드 수집 스레드 없음). 읽기만 하고 tc·export·LVM 상태를 바꾸지 않는다.

## 2. 메트릭

이름은 Prometheus 관례(접두사 `anf_`, 기본 단위, 누적은 `_total`)를 따르고 Azure Monitor REST 이름과의 대응은 문서 표로 남긴다.

### 2.1 storage agent (`/metrics`)

볼륨 라벨: `volume_uuid`(agent uuid), `creation_token`, `protocol`(`nfs3`|`nfs4.1`).

| 메트릭 | 종류 | 출처 | ANF (Azure Monitor REST 이름) |
| --- | --- | --- | --- |
| `anf_volume_size_bytes` | gauge | `statvfs` 전체 크기 | `VolumeAllocatedSize` (근사: ext4 오버헤드만큼 작다) |
| `anf_volume_used_bytes` | gauge | `statvfs` 사용량 | `VolumeLogicalSize` — **다르다**: ANF는 스냅샷 포함, 클론은 활성 파일시스템만 |
| `anf_volume_inodes_used`, `anf_volume_inodes` | gauge | `statvfs` | `VolumeInodesUsed`, `VolumeInodesTotal` |
| `anf_volume_snapshots` | gauge | 스냅샷 LV 수 | (구독 쿼터 메트릭 쪽. 대응 없음) |
| `anf_volume_read_bytes_total`, `anf_volume_write_bytes_total` | counter | knfsd `io` 줄 | `ReadThroughput`, `WriteThroughput` (`rate()`를 씌운 값) |
| `anf_volume_nfs_requests_total` | counter | knfsd `rpc` 줄의 호출 수 | `TotalIops` (v3는 프로시저 호출, v4.1은 COMPOUND 수) |
| `anf_volume_nfs_operations_total{op="read"\|"write"}` | counter | knfsd `proc4ops`의 READ·WRITE. **NFSv4.1 볼륨만** | `ReadIops`, `WriteIops` |
| `anf_volume_throughput_limit_bytes_per_second` | gauge | LVM 태그 `anf_qos` × 1,048,576 | (ARM `actualThroughputMibps`. 메트릭으로는 풀 수준 `VolumePoolAllocatedToVolumeThroughput`의 볼륨 몫) |
| `anf_aggregate_data_used_bytes`, `anf_aggregate_data_size_bytes`, `anf_aggregate_metadata_used_bytes`, `anf_aggregate_metadata_size_bytes` | gauge | `dmsetup status`의 thin 풀 줄 | 없음(클론 고유, R-09. ONTAP aggregate 사용률에 해당) |
| `anf_agent_scrape_duration_seconds`, `anf_agent_scrape_errors_total` | gauge, counter | 수집기 자신 | 없음 |

- 인스턴스가 떠 있지 않은 볼륨은 사용량 계열만 내고 knfsd 계열을 내지 않는다. 한 볼륨의 읽기 실패가 다른 볼륨의 값을 막지 않는다(`anf_agent_scrape_errors_total` 증가, 로그 한 줄).
- 인스턴스가 다시 뜨면(재시작, 되돌리기의 재시작 경로, 복구) knfsd 카운터가 0부터 다시 시작한다(S8 Q7). Prometheus의 `rate()`가 카운터 리셋을 처리하므로 agent는 보정하지 않는다.

### 2.2 anf-api (`/metrics`)

| 메트릭 | 종류 | 라벨 |
| --- | --- | --- |
| `anf_api_http_requests_total` | counter | `method`, `route`(경로 템플릿), `status` |
| `anf_api_http_request_duration_seconds` | histogram | `method`, `route` |
| `anf_api_operations_total` | counter | `resource_type`, `action`, `result`(`Succeeded`\|`Failed`) |
| `anf_api_operation_duration_seconds` | histogram | `resource_type`, `action`, `result` |
| `anf_api_operations_in_progress` | gauge | `resource_type`, `action` |

- `route`는 FastAPI 경로 템플릿이다. 맞는 경로가 없으면(`404`) `route="unmatched"` 하나로 모은다. `/metrics` 자신의 요청은 세지 않는다.
- `resource_type`·`action`은 LRO 워커의 핸들러 키(결함 주입 키와 같은 것, 예: `volumes/create`)에서 얻는다. 소요 시간은 작업 행이 만들어진 때부터 끝 상태까지다. 재시작 뒤 다시 돈 작업은 끝났을 때 한 번만 센다.
- 진행 중 gauge는 프로세스 메모리 값이다. 시작할 때 미완료 작업을 다시 돌리는 경로에서도 맞아야 한다.

### 2.3 이번에 내지 않는 것
- 지연(`AverageRead/Write/OtherLatency`): knfsd에 서버 쪽 지연 카운터가 없다(tracepoint/eBPF 필요).
- `ThroughputLimitReached`, `QosLatencyDelta`: HTB `overlimits`는 50% 부하에서도 늘어 신호가 못 된다(S8 Q4). 대신 차트에 한도 선을 그린다.
- `VolumeSnapshotSize`: 스냅샷 고유 블록은 `thin_ls`가 필요하다. 풀 사용률(aggregate)로 간접 관찰한다.
- `OtherIops`, 풀 수준 ANF 메트릭, v3 볼륨의 읽기·쓰기 연산 수(아래 결정 5).

## 3. Prometheus와 대시보드

- **Prometheus**: `prom/prometheus:v3.15.1` 컨테이너, `--network host`, `--web.listen-address=127.0.0.1:9090`(S8 Q7). 설정 파일 `deploy/prometheus/prometheus.yml`: `scrape_interval: 5s`, job `anf-api`(127.0.0.1:8080), job `storage-agent`(127.0.0.1:8090). 띄우는 스크립트 `scripts/run-prometheus.sh`(컨테이너 이름 `anf-prometheus`, 이미 있으면 다시 만든다). 데이터는 컨테이너와 함께 버린다. FR-13의 compose가 이것을 흡수한다.
- **대시보드**: Vite dev·preview 프록시에 `/prometheus` → `ANF_PROMETHEUS_URL`(기본 `http://127.0.0.1:9090`)을 더한다. `Succeeded` 볼륨 행을 누르면 그 볼륨의 차트 패널이 열린다.
  - 처리량: `rate(anf_volume_read_bytes_total[20s])`, `rate(anf_volume_write_bytes_total[20s])` (MiB/s로 표시) + 한도 선.
  - IOPS: `rate(anf_volume_nfs_requests_total[20s])`, v4.1이면 read·write 연산도.
  - 사용량: `anf_volume_used_bytes`와 `anf_volume_size_bytes`.
  - 범위는 최근 5분, step 5 s, 5 s마다 다시 읽는다(겹치지 않게, 실패하면 마지막 값을 두고 오류 표시).
  - 볼륨 연결: ARM 볼륨의 `creationToken`을 `creation_token` 라벨과 맞춘다(agent 하나에서 유일하다).
  - 페이지 아래에 API 패널 하나: 요청률(`sum by (status) (rate(anf_api_http_requests_total[20s]))`)과 진행 중 작업 수.
  - 차트는 의존성 없이 SVG로 그린다(축 눈금 최소, 마지막 값 숫자 표시). Prometheus가 없으면 차트 자리에 "메트릭을 읽을 수 없음"을 보이고 리소스 트리는 그대로 동작한다.

## 4. 결정 (모두 자동 채택)

| # | 결정 | 고른 것 | 버린 대안과 이유 |
| --- | --- | --- | --- |
| 1 | 이름 체계 | Prometheus 관례 `anf_*` + 문서의 Azure 이름 대응표 | Azure REST 이름 그대로(단위가 bytes/s gauge라 관례와 어긋남), Harvest 이름(기본 단위·`_total` 관례와 다름. 개념 문서에서 선례로만 언급) |
| 2 | 카운터 대 비율 | 원시 카운터를 내고 PromQL `rate()` | 수집기가 5분 평균 gauge를 계산(ANF와 모양은 같지만 창이 고정되고 리셋 처리를 직접 해야 함) |
| 3 | 처리량 출처 (ADR §8이 미룬 것) | knfsd `io` 줄: 데이터 바이트, 읽기·쓰기 분리, fio와 바이트 단위로 같음(S8 Q2) | `eth0`(헤더 포함 0.2~10% 큼, 반대 방향 섞임), `ifb0`·HTB Sent(읽기·쓰기 합만, `nsenter tc` 필요). ANF 정의("across the wire")와는 다르다: 메타데이터(Other) 바이트가 없다. 문서에 적는다 |
| 4 | IOPS 합계 | `rpc` 줄의 호출 수(`anf_volume_nfs_requests_total`). v4.1은 COMPOUND 수 | `proc4ops` 전체 합(SEQUENCE·PUTFH까지 세어 약 3배, S8 Q3) |
| 5 | v3의 읽기·쓰기 연산 수 | 내지 않는다(v3 볼륨은 합계만). `proc3`는 모든 netns의 합이라 볼륨별로 쓰면 틀린다(S8 Q1) | `rc` 줄 근사(misses = 변경 연산 전체라 WRITE와 다르고 설명하기 어렵다), 전역 값 사용(틀림) |
| 6 | 한도 도달 신호 | 내지 않는다. 한도 gauge를 내고 차트에 선으로 그린다 | HTB `overlimits`(부하와 무관하게 늘어남), 사용률 임계값(91% 부하와 포화의 간격이 좁다, S8 Q4) |
| 7 | 사용량의 뜻 | `statvfs` used(활성 파일시스템). 스냅샷 공간은 aggregate 메트릭으로 따로 | thin LV 매핑 블록(파일을 지워도 줄지 않음, S8 Q5), ANF 이름을 그대로 써서 스냅샷 포함처럼 보이게 하는 것 |
| 8 | 수집 시점 | 스크레이프 때 읽는다. 인스턴스 pid는 Docker API 소켓으로(1.7 ms), 풀은 `dmsetup status`(5.6 ms) | 백그라운드 주기 수집(상태·스레드가 늘어남), `docker inspect` CLI(호출마다 150 ms), `lvs` 백분율(소수 둘째 자리) |
| 9 | 볼륨 식별 라벨 | `volume_uuid`, `creation_token`, `protocol`. ARM 이름은 붙이지 않고 대시보드가 `creationToken`으로 잇는다 | anf-api가 info 메트릭으로 ARM 이름 매핑을 냄(이번 차트에는 필요 없음), agent가 ARM ID를 앎(agent는 ONTAP 쪽 계층이라 ARM을 모른다) |
| 10 | 라이브러리 | `prometheus_client`(anf-api의 counter·histogram, agent의 사용자 정의 collector) | 텍스트 형식을 직접 씀(히스토그램·이스케이프를 다시 만들게 됨) |
| 11 | Prometheus 운영 | 컨테이너 + 저장소의 설정 파일 + 스크립트 하나, 5 s 수집, 데이터는 버림 | WSL에 패키지 설치(기기 설정 변경), 이름 있는 볼륨에 보존(데모에 필요 없음) |
| 12 | 차트 | 의존성 없는 SVG, `rate(...[20s])`, 최근 5분 | 차트 라이브러리(캔버스 기반은 jsdom 테스트가 어렵고 의존성이 늘어남), `irate`(더 빠르지만 들쭉날쭉) |
| 13 | ANF와의 시간 단위 차이 | 클론은 5 s 수집·20 s 창. ANF는 최소 5분 평균. 같은 값은 `rate(...[5m])`로 얻는다고 문서에 적는다 | 5분 창을 기본으로(부하가 그래프에 나타나기까지 분 단위가 걸림) |
| 14 | 전체 회귀 | PR의 CI `data-plane` 작업(러너에서 113개 + 새 테스트)을 회귀 근거로 쓴다. WSL에서는 새 테스트 파일과 영향받는 파일만 돌린다 | WSL 전체 묶음 1회(약 90분. 사용자가 긴 검증 실행을 원하지 않는다) |

## 5. 수락 기준

| ID | 종류 | 기준 |
| --- | --- | --- |
| AC-01 | 계약 (anf-api 요청) | anf-api `GET /metrics`가 `200`, Prometheus 텍스트 형식이다. 계정 PUT·GET 뒤 `anf_api_http_requests_total{method,route,status}`가 그만큼 늘고 `route`는 경로 템플릿이다(구독·이름이 라벨에 들어가지 않는다). 없는 경로 요청은 `route="unmatched"`. 지연 히스토그램의 `_count`가 같이 는다. |
| AC-02 | 계약 (작업) | 볼륨(또는 풀) PUT이 끝나면 `anf_api_operations_total{…,result="Succeeded"}`와 소요 시간 히스토그램이 한 건 는다. 결함 주입으로 지연시킨 작업 동안 `anf_api_operations_in_progress`가 1이고 끝나면 0이다. 강제 실패 작업은 `result="Failed"`로 센다. anf-api를 작업 중에 재시작해도 그 작업은 한 번만 세고 gauge가 0으로 돌아온다. |
| AC-03 | 데이터 (사용량) | 클라이언트에서 256 MiB를 쓰면 그 볼륨의 `anf_volume_used_bytes`가 268,435,456 ± 1% 늘고 클라이언트 `df` used와 1% 안에서 맞는다. `anf_volume_size_bytes`, inode, `anf_volume_snapshots`(스냅샷 생성·삭제에 따라)가 맞다. |
| AC-04 | 데이터 (처리량, 볼륨·방향 분리) | 볼륨 A에만 쓰면 A의 `anf_volume_write_bytes_total` 증가가 fio 바이트 ± 1%이고, 같은 구간 볼륨 B의 증가는 0이다. 읽기만 하면 읽기 카운터가 그만큼 늘고 쓰기 카운터는 늘지 않는다(v3, v4.1). |
| AC-05 | 데이터 (IOPS) | v4.1 볼륨에 4 KiB 임의 읽기를 걸면 `anf_volume_nfs_operations_total{op="read"}` 증가가 fio 연산 수 ± 2%다. v3 볼륨은 `anf_volume_nfs_requests_total`이 fio 연산 수 이상으로 늘고 `…operations_total` 계열이 없다. |
| AC-06 | 데이터 (한도와 함께, PRD "부하를 걸면") | Manual 한도 X MiB/s 볼륨에 포화 쓰기를 걸고 Prometheus에서 `rate(read+write)`를 조회하면 안정 구간 값이 `anf_volume_throughput_limit_bytes_per_second`(= X × 1,048,576)의 90~101%다. 한도를 PATCH하면 한도 gauge와 처리량이 따라 바뀐다. |
| AC-07 | Prometheus | `scripts/run-prometheus.sh` 뒤 두 대상이 `up == 1`이다. Windows에서 `http://127.0.0.1:9090/api/v1/query_range`가 볼륨 계열을 돌려준다. 부하를 시작한 뒤 15 s 안에 `rate(...[20s])`가 0보다 커진다. |
| AC-08 | 대시보드 (PRD) | 실제 브라우저(또는 그에 준하는 방법)로 대시보드를 열어 볼륨을 고르면 처리량·IOPS·사용량 차트가 보이고, 클라이언트 부하를 건 뒤 처리량 차트의 마지막 값이 오른다. Prometheus를 멈추면 차트 자리에 오류 표시가 나오고 리소스 트리는 계속 갱신된다. |
| AC-09 | 수명 주기 | 인스턴스를 재시작하면 카운터가 0부터 다시 시작해도 같은 라벨의 계열이 이어지고 `rate()`가 음수가 되지 않는다. 볼륨을 지우면 다음 스크레이프부터 그 볼륨의 계열이 없다. 인스턴스가 내려가 있는 볼륨이 있어도 `/metrics`는 `200`이고 다른 볼륨의 값이 나온다. |
| AC-10 | 데이터 (aggregate, R-09) | 스냅샷 뒤 같은 파일을 덮어쓰면 `anf_aggregate_data_used_bytes`가 쓴 만큼(±10%) 늘고 그 볼륨의 `anf_volume_used_bytes`는 그대로(±1%)다. |
| AC-11 | 간섭 없음 | 1 s 간격으로 agent `/metrics`를 긁는 동안에도 처리량 한도 측정(쓰기 중앙값)이 90~101%다. 볼륨 생성 job이 도는 중의 스크레이프가 `200`이고 job이 성공한다. 볼륨 둘에서 스크레이프 한 번이 0.5 s 안이다. |
| AC-12 | 회귀 | WSL `-m "not dataplane"` 묶음 통과·skip 0, ruff 통과. PR의 CI에서 backend·frontend·`data-plane` 두 조각이 통과한다(기존 113개 + 새 데이터 플레인 테스트). |
| AC-13 | 프런트엔드 | `npm run typecheck`, `npm test`, `npm run build` 통과. 차트 컴포넌트와 Prometheus 클라이언트에 Vitest 테스트가 있다(응답 → 점, 오류 표시, 겹치지 않는 폴링). |

## 6. 구현 메모

- 테스트 층: 수집기 파싱(`/proc/net/rpc/nfsd` 줄, `dmsetup status` 줄)과 메트릭 미들웨어·작업 지표는 단위·계약 테스트(가짜 실행기, Windows에서 돈다). 데이터 효과(AC-03~06, 09~11)와 Prometheus(AC-07)는 `dataplane` e2e 한 파일(`backend/tests/e2e/test_metrics_data_live.py`)로 두고 실행기와 CI `rest` 조각에 자동으로 들어간다. 그 파일은 15분 안에 끝나게 한다(조각 제한). Prometheus 컨테이너는 테스트가 띄우고 지운다.
- 새 모듈 이름은 기존 파일과 겹치지 않게 짓는다(TDD 훅이 파일 이름으로 짝짓는다). 예: `anf_api/api_metrics.py`, `storage_agent/volume_metrics.py`.
- `pyproject.toml`에 `prometheus_client`를 더한다(제품 코드 해시가 바뀐다). WSL venv와 `.venv-win` 모두 다시 설치한다.
- 실행기의 사전 점검·잔여물 검사에 Prometheus 컨테이너와 포트 9090을 넣을지 확인한다(테스트가 남기면 잡아야 한다).
- `docs/testing.md`의 대응표와 `test_testing_doc.py`가 FR-12 문장을 요구하는지 확인하고 맞춘다.
- 문서(ADR §8·§10 S8, `CLAUDE.md`, 개념 문서)는 메인과 concept-explainer가 한다.

## 7. 구현 중 변경

(구현 중 채움)
