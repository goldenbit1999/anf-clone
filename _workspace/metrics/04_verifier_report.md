# 메트릭 (FR-12) 검증 보고서 — 1회차

- 진행 상태: 완료 (2026-11-10 11:08 PST)
- 검증일: 2026-11-10 (WSL·Windows 모두 PST)
- 검증 대상 코드:
  - 제품 코드 내용 해시: 시작 `7c38d8c7fdf750e4a4c32b06802475b0a5e3e2632ea1f60da9e7ac89ac2df4ed`, 끝 `7c38d8c7fdf750e4a4c32b06802475b0a5e3e2632ea1f60da9e7ac89ac2df4ed` — 리더가 준 값과 같다.
  - 커밋: 리더가 준 HEAD는 `e80c8e7`. 검증 중 메인이 문서 커밋 둘을 더해 HEAD가 `a4322ad`(CLAUDE.md, ADR, 진행 기록) → `413b5b9`(개념 문서, ADR, 설계 결정 10a 한 줄, throughput-limit 개념 문서)로 올라갔다. `git diff --stat 37a341c HEAD -- pyproject.toml backend ':!backend/tests'`가 비어 있고, `e80c8e7..413b5b9`는 `frontend/`·`backend/tests/`·`scripts/`·`deploy/`를 건드리지 않는다. 제품 코드는 `37a341c`(10:09 PST) 이후 그대로다.
  - 미커밋 변경: `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`(검증과 무관, 건드리지 않음), 이 보고서. 검증 중 저장소 파일은 이 보고서만 썼다.
  - 해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
- 이번 회차 범위: 전체 (AC-01~AC-13). 리더와 합의한 규칙대로 30분 넘는 실행(WSL 전체 데이터 플레인 묶음)은 하지 않았다. 메트릭 e2e 파일은 실행기로 한 번만 다시 돌렸다. AC-12의 CI 부분은 메인이 PR을 연 뒤 채운다.
- 증거 보관 위치(Windows, 세션 scratchpad `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\`):
  - `...\scratchpad\wsl-evidence\fr12-verify\`, `...\scratchpad\wsl-evidence\fr12-verify.out` — e2e 독립 재실행(실행기 출력, `.jsonl`, `.xml`, agent·anf-api 로그)
  - `...\scratchpad\wsl-evidence\fr12-v1\` — 수동 확인 로그(`ac01_ac02.out`, `stack_up.out`, `notdp.xml`, agent·anf-api 로그, `/metrics` 원본 `m0.txt`·`m1.txt`)
  - `...\scratchpad\ac08\` — 대시보드 관찰 `ac08.jsonl`과 스크린샷 6장(`ac08-0-tree.png` ~ `ac08-5-prometheus-back.png`)
  - 스크립트: `...\scratchpad\ac01_ac02.sh`, `...\scratchpad\stack_up.sh`, `...\scratchpad\cdp_dashboard.mjs`
  - WSL 쪽 원본(`/var/tmp/fr12-v1`, `/var/tmp/anf-clone-tests/fr12-verify*`)은 36개 파일의 sha256이 같음을 확인하고 지웠다. implementer 실행 `/var/tmp/anf-clone-tests/fr12-e2e-1*`은 그대로 두었다.

## 환경 사전 점검
| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | Ubuntu `Stopped` → keepalive(`sleep`) 세션으로 띄움 |
| 커널 모듈·sysctl | `nfsd` 로드됨, `fs.leases-enable = 0` |
| Docker Engine | 서버 `29.1.3 linux`, `readlink /usr/bin/docker` 비어 있음(Desktop 연동 아님) |
| 데이터 플레인 비어 있음 | 8080·8090·9090 리스너 없음, `anf-nfs-*`·`anf-prometheus`·클라이언트 컨테이너 없음, VG `anf` 미부착(WSL 재부팅 뒤. 실행기가 붙였다) |
| Node (Windows) | `v22.14.0`, npm `11.3.0`, `frontend/node_modules` 있음. `npm run dev` → `http://127.0.0.1:5173/` `200` |
| anf-api·Prometheus가 Windows에 보임 | Windows `curl http://127.0.0.1:9090/api/v1/query?query=up` → 두 job `"1"`; Vite 프록시 경유 `/subscriptions/...`·`/prometheus/...` `200` (AC-07·AC-08 근거) |
| 브라우저 도구 | **Claude in Chrome 연결 안 됨**: `tabs_context_mcp` → "Browser extension is not connected", `list_connected_browsers` → `[]`. 대신 Windows에 설치된 Chrome `157.0.8103.50`을 headless(`--headless=new`, 별도 프로필)로 띄우고 DevTools 프로토콜(Node 22 내장 WebSocket)로 조작했다. 아래 AC-08에 방법과 한계 |

## 결과 요약
PASS 11 / FAIL 1 / UNVERIFIED 0 / 대기 1

- FAIL: AC-06 (불안정: 20 MiB/s 구간 3표본 중 1회 77%)
- 대기: AC-12의 CI 부분(메인이 채움). WSL `-m "not dataplane"`과 ruff는 통과

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1 |
| AC-02 | PASS | 1 |
| AC-03 | PASS | 1 |
| AC-04 | PASS | 1 |
| AC-05 | PASS | 1 |
| AC-06 | FAIL (불안정) | 1 |
| AC-07 | PASS | 1 |
| AC-08 | PASS (headless Chrome) | 1 |
| AC-09 | PASS | 1 |
| AC-10 | PASS | 1 |
| AC-11 | PASS | 1 |
| AC-12 | 대기 — WSL 묶음·ruff PASS, CI는 메인이 채움 | 1 |
| AC-13 | PASS | 1 |

## e2e 결과의 출처
- **implementer 실행** `/var/tmp/anf-clone-tests/fr12-e2e-1/`(10:20~10:26 PST, 5 passed, 358.9 s). 제품 코드는 `37a341c`(10:09) 이후 바뀌지 않아 같은 제품 코드로 돌았다. 다만 e2e 파일·`metrics_live.py`·`scripts/run-prometheus.sh`는 그 뒤 10:32 커밋(`3c403b1`)에 들어가 실행 당시 내용을 증명할 수 없다. 그래서 판정은 아래 독립 재실행으로 하고, 이 실행은 비교 자료로만 쓴다.
- **독립 재실행(이번 회차)** 10:43~10:49 PST, 제품 코드 해시 `7c38d8c7…`. 명령: `MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/Users/mkimh/Projects/ANF-clone && ANF_TEST_OUT=/var/tmp/anf-clone-tests/fr12-verify setsid nohup bash scripts/run-dataplane-tests.sh backend/tests/e2e/test_metrics_data_live.py > /var/tmp/anf-clone-tests/fr12-verify.out 2>&1 &'`
  - 결과: **1 failed, 4 passed in 349.50s**, 실행기 `exit 1`, skip 0. 실패는 `test_ac06_ac07_prometheus_shows_the_load_and_follows_the_limit`의 AC-06 단언 하나(`backend/tests/e2e/test_metrics_data_live.py:208`, `within(0.7667)`). 같은 테스트의 AC-07 단언(198~202행)은 모두 통과했다.
  - 실행 뒤 잔여물 없음: 컨테이너 없음, LV는 `aggr0`만, 8080·8090·9090 리스너 없음.

## 항목별 결과

### [PASS] AC-01 anf-api 요청 지표 (API 계약, 실제 프로세스)
- 기준: `GET /metrics`가 `200`·Prometheus 텍스트 형식. 계정 PUT·GET 뒤 `anf_api_http_requests_total{method,route,status}`가 그만큼 늘고 `route`는 경로 템플릿(구독·이름 없음). 없는 경로는 `route="unmatched"`. 지연 히스토그램 `_count`도 는다.
- 실행한 명령: WSL root에서 `scratchpad\ac01_ac02.sh`의 마지막 절. anf-api는 `setpriv --reuid=1000`으로 띄운 실제 uvicorn(`anf_api.arm_app:create_app`, 127.0.0.1:8080). `/metrics`를 긁고 → `PUT …/netAppAccounts/acct-ac01`(201), `GET …/acct-ok`(200), `GET …/no-such-acct`(404), `GET /not/a/route`(404) → 다시 긁어 `diff`.
- 출력(핵심):
  - `content-type: text/plain; version=1.0.0; charset=utf-8`, 본문 `# HELP anf_api_http_requests_total …`/`# TYPE … counter`
  - 늘어난 줄(이전 값 없음 → 1):
    - `anf_api_http_requests_total{method="PUT",route="/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.NetApp/netAppAccounts/{account_name}",status="201"} 1.0`
    - 같은 route `method="GET",status="200"} 1.0`, `status="404"} 1.0` (없는 계정은 route가 맞으므로 템플릿으로 센다)
    - `anf_api_http_requests_total{method="GET",route="unmatched",status="404"} 1.0`
    - `anf_api_http_request_duration_seconds_count{method="GET",route=".../netAppAccounts/{account_name}"} 2.0`, `{method="PUT",…} 1.0`, `{method="GET",route="unmatched"} 1.0`
  - 노출 전체에서 구독 ID·리소스 그룹·계정 이름·요청 경로 문자열 검색(`grep -cE "0e2e0000-…|rg-fr12v|acct-|no-such|not/a/route"`) → `0`
  - `route` 값은 템플릿 둘과 `unmatched`뿐. `route="/metrics"` → `0`(자기 요청은 세지 않음)
  - 볼륨 경로 템플릿도 실제 Prometheus에서 확인(e2e 재실행 `api_routes`: `…/capacityPools/{pool_name}/volumes/{volume_name}` 등 템플릿 5개만)
- 원본: `wsl-evidence\fr12-v1\ac01_ac02.out`, `m0.txt`, `m1.txt`

### [PASS] AC-02 anf-api 작업 지표 (API 계약·상태 전이, 실제 프로세스 + 결함 주입 + 재시작)
- 기준: 작업이 끝나면 `anf_api_operations_total{…,result="Succeeded"}`와 소요 시간 히스토그램이 한 건 는다. 지연 작업 동안 `anf_api_operations_in_progress` 1, 끝나면 0. 강제 실패는 `result="Failed"`. 작업 중 재시작해도 한 번만 세고 gauge가 0으로 돌아온다.
- 실행한 명령: WSL root에서 `bash /var/tmp/fr12-v1/ac01_ac02.sh` (원본 `scratchpad\ac01_ac02.sh`). `ANF_FAULT_INJECTION='{"netAppAccounts/create":{"delaySeconds":20},"capacityPools/create":{"fail":true}}'`, DB `/var/tmp/fr12-v1/ac02.db`. 시각은 게스트 단조 시계(`/proc/uptime`).
- 출력(핵심):
  - 시작 직후: `anf_api_operations_in_progress{action="create",resource_type="netAppAccounts"} 0.0`, `…capacityPools… 0.0` (미리 선언됨)
  - (a) 지연 계정 생성: 3 s 뒤 `in_progress … 1.0` → 20.8 s 뒤 `Succeeded` → `anf_api_operations_total{action="create",resource_type="netAppAccounts",result="Succeeded"} 1.0`, `…duration_seconds_count … 1.0`, `…_sum … 20.022194`, `in_progress … 0.0`
  - (b) 강제 실패 풀 생성: 작업 본문 `"status":"Failed"`, `"error":{"code":"InternalServerError","message":"Injected fault: capacityPools/create (ANF_FAULT_INJECTION)."}` → `anf_api_operations_total{action="create",resource_type="capacityPools",result="Failed"} 1.0`, `_count 1.0`, `in_progress 0.0`
  - (c) SIGTERM 재시작: PUT 5 s 뒤 `in_progress 1.0`(옛 프로세스 Succeeded 수는 1 그대로) → SIGTERM(rc 0) → 새 프로세스 시작 직후 `in_progress 1.0`, `operations_total` 줄 없음 → PUT부터 26.6 s 뒤 Succeeded → `operations_total … 1.0`, `_count 1.0`, `_sum 25.800285`(행 생성부터 잰 값. 재시작 뒤 20 s만이 아니다), `in_progress 0.0` → 6 s 뒤 다시 긁어도 `1.0`, `0.0`
  - (d) SIGKILL(충돌) 재시작: 같은 결과 — 새 프로세스 `in_progress 1.0` → Succeeded 뒤 `operations_total 1.0`, `_sum 25.661924`, `in_progress 0.0`, 6 s 뒤에도 같음
  - 풀·볼륨 PUT 성공(AC-08 세션, 결함 주입 없음): `anf_api_operations_total{action="create",resource_type="capacityPools",result="Succeeded"} 1.0`, `{action="create",resource_type="volumes",result="Succeeded"} 1.0`, 각 `_count 1.0` (`wsl-evidence\fr12-v1\stack_up.out`). e2e 재실행에서도 `sum(anf_api_operations_total{resource_type="volumes",result="Succeeded"})` = 2 (create, patch)
- 판정 메모: `_sum`(25.8 s)이 단조 시계로 잰 PUT→Succeeded(26.6 s)보다 0.8 s 짧다. 작업 행 `startTime`(벽시계)과 단조 시계의 차이로 보이며 기준(한 번만 셈, gauge 0 복귀)과 무관하다.
- 처음 실행(`ac01_ac02.try1-badgrep.out`)은 내 grep 패턴이 노출 형식의 라벨 순서(`action`이 먼저)와 맞지 않아 작업 줄을 못 보였다. 패턴만 고쳐 다시 돌린 결과가 위다.

### [PASS] AC-03 사용량 (데이터 효과)
- 기준: 클라이언트가 256 MiB를 쓰면 `anf_volume_used_bytes`가 268,435,456 ± 1% 늘고 클라이언트 `df` used와 1% 안. 크기·inode·스냅샷 수가 맞다.
- 실행한 명령: 독립 재실행의 `test_ac03_ac04_ac05_usage_throughput_and_iops_per_volume` PASSED (스냅샷 수는 `test_ac10…` PASSED)
- 출력(핵심, `fr12-verify\test_metrics_data_live.jsonl`의 `AC-03/04`):
  - v3 볼륨: used 12,288 → 268,451,840 (증가 268,439,552, +0.0015%), 클라이언트 df used 268,435,456 (차 0.006%), size agent 1,020,702,720 / df 1,021,313,024 (차 0.06%), inode 65,536/12 = df 65,536/12, snapshots 0
  - v4.1 볼륨: 같은 값
  - 스냅샷 수: 생성 전 0 → 생성 뒤 1 → 덮어쓴 뒤 1 → 삭제 뒤 0
  - 대시보드 세션에서도 64 MiB를 쓴 뒤 사용량 차트 `used 0.063 GiB`, `size 0.951 GiB`

### [PASS] AC-04 처리량, 볼륨·방향 분리 (데이터 효과)
- 기준: A에만 쓰면 A의 쓰기 카운터 증가 = fio 바이트 ± 1%, 같은 구간 B는 0. 읽기만 하면 읽기 카운터만 는다(v3, v4.1).
- 실행한 명령: 독립 재실행의 `test_ac03_ac04_ac05…` PASSED
- 출력(핵심): v3·v4.1 모두 쓰기 구간 `w` 268,435,456 = fio write 268,435,456 (0%), 다른 볼륨 `other_w` 0, `other_r` 0, 쓰기 구간 `r` 0; 읽기 구간 `r` 268,435,456 = fio read 268,435,456, `w` 0

### [PASS] AC-05 IOPS (데이터 효과)
- 기준: v4.1 4 KiB 임의 읽기의 `anf_volume_nfs_operations_total{op="read"}` 증가 = fio 연산 수 ± 2%. v3는 `anf_volume_nfs_requests_total`이 fio 연산 수 이상이고 `…operations_total` 계열이 없다.
- 실행한 명령: 독립 재실행의 `test_ac03_ac04_ac05…` PASSED
- 출력(핵심): v4.1 `fio_ios` 40,698, `read_ops` 40,698 (0%), `requests` 40,673; v3(iodepth 1) `fio_ios` 9,930, `requests` 9,934 (≥), `op_series` `[]`

### [FAIL] AC-06 Manual 한도와 함께 본 처리량 (데이터 효과, PRD "부하를 걸면") — 불안정
- 기준: Manual 한도 X MiB/s 볼륨에 포화 쓰기를 걸고 Prometheus `rate(read+write)`의 안정 구간 값이 `anf_volume_throughput_limit_bytes_per_second`(= X × 1,048,576)의 90~101%. 한도를 PATCH하면 한도 gauge와 처리량이 따라 바뀐다.
- 실행한 명령:
  1. 독립 재실행의 `test_ac06_ac07…` (10 MiB/s로 만들고 fio `--rw=write --bs=1M --size=64M --iodepth=16 --time_based --runtime=100`, 45 s에 PATCH 20 MiB/s)
  2. 같은 절차를 대시보드 세션에서 수동으로 한 번 더(`scratchpad\cdp_dashboard.mjs`: 같은 fio 인자, 45 s에 PATCH, 같은 창 `[25 s, PATCH]`·`[PATCH 끝 + 25 s, 끝 − 1 s]`, 같은 쿼리)
- 출력(핵심):

  | 표본 | 10 MiB/s 구간 비율 | 20 MiB/s 구간 비율 | 20 MiB/s 구간 rate (MiB/s) | fio 쓴 바이트(100 s) |
  | --- | --- | --- | --- | --- |
  | implementer 실행(비교용, 10:23) | 0.9933 | 0.99 | 19.8, 19.867, 19.8, 19.8, 19.733, 19.8 | 1,621,098,496 |
  | **독립 e2e 재실행(10:44~10:46)** | 0.9933 | **0.7667** | 17.533, 14.8, 12.267, 13.133, 15.867, 18.4 | 1,478,492,160 |
  | 수동 재현(대시보드 세션, 10:58~11:00) | 0.9867 | 0.9833 | 19.6, 19.667, 19.667, 19.667, 19.667, 19.667 | 1,595,932,672 |

  - 실패한 실행의 assert: `E  assert False  +  where False = within(0.7667)` (`test_metrics_data_live.py:208`). 같은 실행에서 한도 gauge는 구간마다 `[10485760.0]`, `[20971520.0]`, PATCH 직후 agent gauge `20971520.0`, PATCH 작업 `Patching → Succeeded`로 맞았다.
  - PATCH를 따라 바뀌는 것(기준 둘째 문장)은 세 표본 모두 보였다. 수동 재현에서 대시보드 값: 한도 10 → 20, 쓰기 9.9 → 10.3 → 13.6 → 16.8 → 19.7 MiB/s.
- 판정: 기준 첫 문장이 독립 실행 1회에서 깨졌다. 20 MiB/s 구간 3표본 중 1회 실패(관찰 실패율 약 1/3, 표본이 적어 추정 폭이 크다). 증거 없이 PASS로 둘 수 없어 FAIL로 두고 불안정으로 표시한다.
- 추정 원인 (메트릭 쪽이 아니라 그 시간에 실제로 덜 쓴 것):
  - 메트릭은 클라이언트가 실제로 쓴 양을 따랐다. 실패한 실행의 fio 총량은 다른 두 표본보다 117~143 MB 적다. 20 MiB/s 구간 rate 평균 약 15.3 MiB/s × 약 28 s의 부족분(약 131 MiB ≈ 138 MB)과 맞는다. 즉 Prometheus가 낮게 본 것이 아니라 그 30초 동안 볼륨이 실제로 20 MiB/s를 못 냈다.
  - 저장 장치 쪽 처리량이 출렁인다: 같은 볼륨의 한도를 100 MiB/s로 올리고 15 s 순차 쓰기를 세 번 재니 74.55, 46.36, 93.6 MiB/s였다(`fio … --runtime=15`, 대시보드 세션 뒤). 순간 처리량이 20 MiB/s 밑으로 떨어지는 구간이 있으면 "포화 쓰기"라는 전제가 깨진다. 실패 구간(10:45:33~10:46:02 PST)의 WSL `journalctl`·커널 로그에는 특이 사항이 없었고, 그 구간에 이 검증자가 돌린 명령도 없었다(Windows의 `npm`·`ruff`는 10:43~10:45, 10 MiB/s 구간과 겹쳤지만 그 구간은 0.9933).
  - 위치: 판정식은 `backend/tests/e2e/test_metrics_data_live.py:178-185, 206-208`(안정 구간 중앙값 / 한도). 이 단언은 "메트릭이 부하를 보인다"와 "데이터 플레인이 한도까지 낸다"(FR-08이 따로 검증하는 것)를 한꺼번에 묻는다.
- 수정 제안 (리더 판단):
  1. 같은 구간의 클라이언트 실측과 비교하도록 단언을 바꾼다. 예: fio에 `--write_bw_log`·`--log_avg_msec=1000`을 주고 같은 창의 fio 평균과 Prometheus `rate()` 중앙값이 ±5% 안인지 보고, 한도에는 상한(≤101%)과 "PATCH 뒤 구간 중앙값 > PATCH 전 구간 최댓값"만 요구한다. 그러면 메트릭의 충실도를 묻고, 저장 장치가 잠깐 느려진 것에 흔들리지 않는다.
  2. 기준 문장(설계 §5 AC-06)을 그대로 두려면, 이 테스트는 CI `data-plane` 조각에서도 같은 확률로 깨질 수 있다는 점을 PR 전에 감안해야 한다. 바꾼 뒤 재검증은 3의 규칙에 따라 원래 실패율(약 1/3)로 n = ⌈3/0.33⌉ = 9회 이상 실패 없이 돌아야 PASS로 볼 수 있다(테스트 한 개 약 2.5분, 9회 약 23분).

### [PASS] AC-07 Prometheus (데이터 효과·연결)
- 기준: `scripts/run-prometheus.sh` 뒤 두 대상이 `up == 1`. Windows에서 `http://127.0.0.1:9090/api/v1/query_range`가 볼륨 계열을 돌려준다. 부하를 시작한 뒤 15 s 안에 `rate(...[20s])`가 0보다 커진다.
- 실행한 명령:
  - WSL root `bash /var/tmp/fr12-v1/stack_up.sh` 안에서 `bash scripts/run-prometheus.sh` → `Prometheus is ready at http://127.0.0.1:9090`, rc 0
  - Windows Git Bash `curl -s 'http://127.0.0.1:9090/api/v1/query?query=up'`, `/api/v1/targets?state=active`
  - Windows Node(`cdp_dashboard.mjs`)에서 `query_range` 3종을 직접(`:9090`)과 Vite 프록시(`:5173/prometheus`)로, 그리고 부하 시작 뒤 0.25 s마다 `rate(anf_volume_write_bytes_total{creation_token="fr12v-vol1"}[20s])`
- 출력(핵심):
  - `up`: `{"job":"anf-api"} "1"`, `{"job":"storage-agent"} "1"`; targets `('anf-api', 'http://127.0.0.1:8080/metrics', 'up', '')`, `('storage-agent', 'http://127.0.0.1:8090/metrics', 'up', '')`
  - Windows `query_range`(직접·프록시 모두 HTTP 200, `status: success`, 계열 1개): `anf_volume_write_bytes_total` 라벨 `{"creation_token":"fr12v-vol1","instance":"127.0.0.1:8090","job":"storage-agent","protocol":"nfs4.1","volume_uuid":"a9f2ef4d-…"}` 점 7개; `anf_volume_throughput_limit_bytes_per_second` 마지막 값 `"10485760"`; `rate(...)` 점 6개
  - 부하 시작 → rate > 0: **3.21 s** (Windows, 값 1,275,403.96 B/s). e2e 재실행에서도 4.82 s, 부하 전 `idle_rate` 0.0
  - e2e 재실행의 AC-07 단언(up 둘, idle 0·15 s 안, 원시 계열 1개, 볼륨 작업 수 ≥ 2, 볼륨 route 템플릿) 모두 통과

### [PASS] AC-08 대시보드 (PRD 수락 기준) — headless Chrome으로 관찰
- 기준: 실제 브라우저(또는 그에 준하는 방법)로 대시보드를 열어 볼륨을 고르면 처리량·IOPS·사용량 차트가 보이고, 클라이언트 부하를 건 뒤 처리량 차트의 마지막 값이 오른다. Prometheus를 멈추면 차트 자리에 오류 표시가 나오고 리소스 트리는 계속 갱신된다.
- 방법: Claude in Chrome이 연결돼 있지 않아(환경 사전 점검) Windows의 Chrome 157을 `--headless=new --remote-debugging-port=9333 --user-data-dir=<scratchpad>` 로 띄우고 `scratchpad\cdp_dashboard.mjs`로 조작했다. 화면은 Windows의 `npm run dev`(Vite 8.3.7, `http://127.0.0.1:5173/?subscription=0e2e0000-…`)가 낸 실제 빌드이고, anf-api·agent·Prometheus는 WSL에서 실제로 돌았다(`stack_up.sh`). 볼륨 행 클릭은 JS `click()`이 아니라 `Input.dispatchMouseEvent`(mouseMoved/Pressed/Released, 좌표 149,182)로 했다. 탭 하나를 한 번만 열고 이동·새로 고침 없이 같은 탭의 DOM을 2.5~5 s마다 45회 읽었다.
- 한계: headless 렌더링이고 사람이 보는 창은 아니다. 리더가 "실제 브라우저"를 확장 프로그램이 붙은 Chrome으로 해석한다면 이 항목을 UNVERIFIED로 바꾸면 된다(화면 근거는 스크린샷으로 남겼다).
- 출력(핵심, `scratchpad\ac08\ac08.jsonl`):
  - 트리: `va | NetApp account | Succeeded`, `vp | Capacity pool | Succeeded`, `vol1 | Volume | Succeeded` (1.7 s)
  - 클릭 0.5 s 뒤 패널 `Volume vol1`에 차트 3개 `["Throughput","IOPS","Usage"]`, SVG polyline 3·3·2개, 오류 없음
  - 부하 전(idle): 처리량 legend `write 0`, `limit 10`, IOPS `requests 0.067`, 사용량 `used 0`
  - fio 시작 뒤 처리량 차트의 `write` 마지막 값(부하 시작부터 초): 3 s `0` → 6 s `1.3` → 11 s `3.9` → 16 s `6.5` → 21 s `9.1` → 26~46 s `9.9`(한도 10) → PATCH 20 뒤 52 s `10.3` → 57 s `13.6` → 62 s `16.8` → 67~102 s `19.6~19.7`(한도 선 `20`). IOPS `write ops`도 같이 0 → 9.9 → 19.7, `used` 0 → 0.063 GiB
  - Prometheus 정지(`run-prometheus.sh stop`, rc 0) 4.6 s 뒤 두 패널에 `role=alert`: `Cannot read metrics: Prometheus query_range returned 502. Showing the last successful read. Retrying every 5 s.` 차트는 마지막 값을 유지
  - 정지 중 스냅샷 PUT `201` → `Creating → Succeeded` → 1.5 s 뒤 같은 탭 트리에 `snap-prom-down | Snapshot | Succeeded`, 같은 순간 API GET 스냅샷 목록 `[['va/vp/vol1/snap-prom-down', 'Succeeded']]`. `Updated` 시각은 11:00:37 → 11:00:41 → 11:00:43 → 11:00:45로 계속 바뀜
  - Prometheus 재시작 5.6 s 뒤 경고가 사라짐(데이터는 버려져 차트는 잠시 `No data yet`)
  - 같은 탭: target ID `BFF3A8C6…` 처음과 끝이 같음, `performance.getEntriesByType("navigation")` → `["navigate"]` 하나
  - 스크린샷: `scratchpad\ac08\ac08-0-tree.png`(트리), `ac08-1-idle.png`(차트, 부하 전), `ac08-2-load-limit10.png`(10 MiB/s), `ac08-3-load-limit20.png`(20 MiB/s, write 19.7), `ac08-4-prometheus-down.png`(오류 배너 + 스냅샷 행), `ac08-5-prometheus-back.png`

### [PASS] AC-09 수명 주기 (데이터 효과)
- 기준: 인스턴스 재시작 뒤 카운터가 0부터여도 같은 라벨 계열이 이어지고 `rate()`가 음수가 아니다. 볼륨을 지우면 다음 스크레이프부터 그 계열이 없다. 인스턴스가 내려가 있어도 `/metrics`는 `200`이고 다른 볼륨 값이 나온다.
- 실행한 명령: 독립 재실행의 `test_ac09_series_across_instance_restart_and_volume_delete` PASSED
- 출력(핵심): 내려간 동안 `down_status` 200, 내려간 볼륨은 사용량 계열 6개만(`anf_volume_inodes`, `…inodes_used`, `…size_bytes`, `…snapshots`, `…throughput_limit_bytes_per_second`, `…used_bytes`), 다른 볼륨은 `read/write_bytes_total`, `nfs_requests_total` 포함 9개, `anf_agent_scrape_errors_total` 0 → 0; 재PUT `Updating → Succeeded`; 쓰기 카운터 64 MiB → 0 → 32 MiB; Prometheus 원시 계열 1개, `rate` 최솟값 0.0; 삭제한 볼륨 계열 agent에서 `[]`, Prometheus에서 1.5 s 뒤 사라짐. 대시보드 세션 정리 때도 볼륨 DELETE 6 s 뒤 agent `/metrics`의 `fr12v-vol1` 줄 수 `0`

### [PASS] AC-10 aggregate (데이터 효과, R-09)
- 기준: 스냅샷 뒤 같은 파일을 덮어쓰면 `anf_aggregate_data_used_bytes`가 쓴 만큼(±10%) 늘고 볼륨 used는 그대로(±1%).
- 실행한 명령: 독립 재실행의 `test_ac10_snapshot_overwrite_grows_the_aggregate_not_the_volume` PASSED
- 출력(핵심): aggregate 증가 273,154,048 / fio 268,435,456 = +1.8%; 볼륨 used 268,455,936 → 268,455,936 (0%); aggregate 322,961,408 → 323,485,696 → 596,639,744 → (스냅샷 삭제 뒤) 322,961,408

### [PASS] AC-11 간섭 없음 (데이터 효과)
- 기준: 1 s 간격 agent 스크레이프 중에도 한도 측정(쓰기 중앙값) 90~101%, 볼륨 생성 job 중 스크레이프 `200`·job 성공, 볼륨 둘에서 스크레이프 0.5 s 안.
- 실행한 명령: 독립 재실행의 `test_ac11_one_second_scrapes_do_not_disturb_limits_or_jobs` PASSED
- 출력(핵심): 스크레이프 97회 모두 `200`; job 중 스크레이프 3회, job `Creating → Succeeded` 3.1 s; 10 MiB/s 쓰기 6회 `[9.93, 9.944, 9.932, 9.942, 9.934, 9.94]`, 중앙값 9.94 (99.4%); 측정 중 스크레이프 93회, 최대 0.1316 s, 중앙값 0.0681 s

### [대기] AC-12 회귀 — WSL·ruff 부분 PASS, CI 부분은 메인이 채움
- 기준: WSL `-m "not dataplane"` 묶음 통과·skip 0, ruff 통과. PR의 CI에서 backend·frontend·`data-plane` 두 조각이 통과.
- 실행한 명령:
  - WSL(일반 사용자 `mkimhome1`): `cd /mnt/c/Users/mkimh/Projects/ANF-clone && PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest -m "not dataplane" -p no:cacheprovider -q -rs --junitxml=/var/tmp/fr12-v1/notdp.xml`, 이어서 `backend/tests/junit_gate.py`로 skip·실패 집계
  - Windows: `uvx ruff@0.14.0 check backend .claude/hooks`
- 출력(핵심): `1016 passed, 119 deselected in 218.69s`; junit_gate `collected 1016, skipped 0`, rc 0 (`{'tests': '1016', 'failures': '0', 'errors': '0', 'skipped': '0'}`); ruff `All checks passed!` (`ruff 0.14.0`)
- CI: 메인이 채움. AC-06의 불안정 때문에 CI `data-plane` 조각(메트릭 e2e가 들어간 `rest` 조각)이 같은 이유로 깨질 수 있다.

### [PASS] AC-13 프런트엔드 명령과 Vitest (계약)
- 기준: `npm run typecheck`, `npm test`, `npm run build` 통과. 차트 컴포넌트와 Prometheus 클라이언트에 Vitest 테스트(응답 → 점, 오류 표시, 겹치지 않는 폴링).
- 실행한 명령 (Windows PowerShell, `frontend/`): `npm run typecheck`, `npm test`, `npm run build`, `npx vitest run --reporter=verbose promClient LineChart useMetrics MetricsPanels App`
- 출력(핵심):
  - `tsc --noEmit` 오류 없음
  - `Test Files 8 passed (8)`, `Tests 48 passed (48)`
  - `vite build` → `dist/assets/index-C-xMrAKK.js 227.96 kB`, `✓ built in 585ms`
  - 해당 테스트: `promClient.test.ts > asks the Prometheus range API through the /prometheus proxy and turns values into numeric points`, `… an HTTP failure (Prometheus down behind the proxy) is an error`; `useMetrics.test.tsx > reads never overlap: the 5 s wait starts when a read ends`, `… a failed read keeps the last data, shows the error, and recovers on the next success`; `LineChart.test.tsx > draws one line per series …`, `… skips points Prometheus returned as NaN`; `MetricsPanels.test.tsx > a failed read shows the error and keeps the charts of the last good read` 등 29개
- 빌드 뒤 `git status`에 추적 파일 변경 없음(`dist/`는 무시 대상).

## 측정값

### AC-06 처리량 비율 (Prometheus `rate(read)+rate(write)` 안정 구간 중앙값 / 한도 gauge)
| 표본 | 10 MiB/s | 20 MiB/s |
| --- | --- | --- |
| implementer 실행 (비교용) | 0.9933 | 0.99 |
| 독립 e2e 재실행 | 0.9933 | **0.7667** |
| 수동 재현 (대시보드 세션) | 0.9867 | 0.9833 |
| AC-11 (1 s 스크레이프 중, fio 6회 중앙값) | 0.994 | — |

### 저장 장치 순차 쓰기 (한도 100 MiB/s, 1 GiB NFSv4.1 볼륨, fio 1 MiB·iodepth 16·15 s)
74.55, 46.36, 93.6 MiB/s (3회)

### 지연 시간
- 부하 시작 → `rate(...[20s]) > 0`: 3.21 s (Windows), 4.82 s (e2e)
- Prometheus 정지 → 대시보드 오류 표시: 4.6 s; 재시작 → 오류 해제: 5.6 s
- 스냅샷 Succeeded → 대시보드 트리에 행: 1.5 s (Prometheus 정지 중)
- agent `/metrics` 스크레이프(볼륨 둘, 1 s 간격 93회): 최대 0.1316 s, 중앙값 0.0681 s

## 판정 밖 관찰
1. **implementer 실행의 출처**: `fr12-e2e-1`은 e2e 파일·도우미·`run-prometheus.sh`가 커밋되기 전(10:20~10:26) 작업 트리로 돌았다. 제품 코드는 같지만 테스트 코드가 지금과 같다는 증거는 없다. 이번 판정은 독립 재실행으로 했다.
2. **v4.1 `requests`(COMPOUND 수)가 fio 연산 수보다 조금 적다**: 40,673 대 40,698(−25, 0.06%). 설계 §7에 적힌 `rpc` 줄의 비원자적 증가와 같은 현상이다. AC-05는 v4.1을 `proc4ops` READ로 판정하므로 영향이 없다. 개념 문서에서 "IOPS 합계는 근사"라고 설명할 근거다.
3. **유휴 볼륨의 IOPS가 0이 아니다**: 마운트만 하고 I/O가 없을 때 `requests 0.067 /s`(NFSv4.1 lease 갱신 등 SEQUENCE 호출). ANF `TotalIops`와 비교할 때 설명할 거리다.
4. **"Operations in progress" 차트는 짧은 작업을 거의 못 본다**: 5 s 수집이라 2~3 s짜리 PATCH·스냅샷 생성 동안 gauge 1이 긁히지 않았다(세션 내내 0). 결함은 아니고 수집 간격의 한계다. 데모에서 보이려면 결함 주입 지연을 쓰면 된다.
5. **Prometheus를 다시 띄우면 데이터가 비어** 차트가 잠시 `No data yet`이 된다. 설계 결정 11(데이터는 버림)대로다.
6. **검증자 쪽 실수 하나**: 정리 스크립트의 `pkill -f "anf_api.arm_app:create_app"`이 그 문자열을 담은 자기 `bash -c`까지 맞혀 스크립트가 중간에 끝났다. anf-api와 agent는 둘 다 `Application shutdown complete`/`Finished server process`로 정상 종료했고(agent는 PID로 따로 멈춤), 결과에 영향은 없다.
7. **정리 상태(11:06 PST)**: 8080·8090·9090 리스너 없음, 컨테이너 없음, VG `anf`의 LV는 `aggr0`만, `/var/lib/anf-clone/ns`·`exports` 비어 있음, uvicorn 없음. Windows의 Vite(5173)와 headless Chrome(9333) 종료, 임시 Chrome 프로필 삭제. VG `anf`는 실행기가 붙인 상태로 둔다(평소 상태).
