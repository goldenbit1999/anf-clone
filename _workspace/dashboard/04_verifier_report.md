# dashboard (FR-09) 검증 보고서 — 1회차

- 진행 상태: 완료 (2026-11-09 18:12 시작, 18:29 끝, -0800)
- 검증일: 2026-11-09
- 검증 대상 코드: 커밋 `5cb9d4b927ce02c12be9fdb8033ae27d64f89482` (`feature/dashboard`). 백엔드 제품 코드 내용 해시 시작·끝 모두 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`, frontend 내용 해시 시작·끝 모두 `61c3eb62ea4cf79d27231f7db469bc45feb8308d6c13dfd65aec6a62b90e3e14`. 둘 다 리더가 준 값과 같다. 미커밋 변경: 시작 때 `_workspace/dashboard/00_progress.md`(M), `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`(??). 이번 회차가 더한 것: 이 보고서와 검증 도구 `backend/tests/e2e/dashboard_watch.py`(해시 범위 밖인 `backend/tests`, ruff 0.14.0 통과, pytest 수집 대상 아님). `frontend/dist`, `frontend/node_modules`는 `frontend/.gitignore`로 무시된다.
  - 백엔드 해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
  - frontend 해시 명령: 같은 방식으로 `-- frontend`
- 이번 회차 범위: 전체 (AC-01~AC-07, AC-09. AC-08은 리더가 확인)

## 환경 사전 점검
| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | OK. `wsl -l -v`: Ubuntu Running (2) |
| 커널 모듈 | OK. `lsmod`: `nfsd`, `dm_thin_pool`, `ifb`, `sch_htb` 로드됨. `fs.leases-enable = 0` |
| Docker | OK. Ubuntu 안 Docker Engine `29.1.3 linux`, `readlink /usr/bin/docker` 비어 있음. 이미지 `anf-nfs-server`, `anf-nfs-client`, 네트워크 `anf-vnet` 있음. 시작 시 컨테이너 0개, LV는 `aggr0`뿐, `ns/`·`exports/` 비어 있음 |
| 포트 | 8080/8090 비어 있음 (시작 전 `ss -ltnp`) |
| Node | Windows Node v22.14.0 / npm 11.3.0. `npm ci` rc=0 (143 packages, 18:15) |
| 컨트롤 플레인 서비스 | OK. storage agent root pid 4882 (18:18:32), anf-api uid 1000 pid 4940 (18:18:38, DB `/home/mkimhome1/fr09-r1/anf.db`, `ANF_MIN_VOLUME_SIZE_GIB=1`, `ANF_FAULT_INJECTION={"netAppAccounts/create":{"delaySeconds":15},"netAppAccounts/delete":{"delaySeconds":15},"capacityPools/patch":{"fail":true}}`). Windows `curl .../subscriptions/x/.../netAppAccounts` → `200` |
| 대시보드 서버 | OK. `npm run build` 결과를 `npm run preview`로 `http://127.0.0.1:4173` 제공. `/` → `200`, 프록시 `/subscriptions/x/...` → `200 {"value":[]}` |
| 브라우저 도구 | 처음 2회 `tabs_context_mcp` → "Browser extension is not connected", `list_connected_browsers` → `[]`. 원인: Windows에 Chrome이 떠 있지 않았다(msedge만 실행 중). Chrome을 `about:blank`로 실행한 뒤 3회째 연결됨(장치 1개, `isLocal: true`). 새 MCP 탭 그룹의 탭 `528666922` 사용 |

## 결과 요약
PASS 8 / FAIL 0 / UNVERIFIED 0 (AC-08은 리더가 GitHub Actions로 확인)

관찰한 반영 지연 상한은 최대 4.2 s(제한 5 s). 최대값 두 건은 모두 탭이 `hidden`일 때다(아래 "측정값"). 결함은 찾지 못했다.

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1회차 |
| AC-02 | PASS | 1회차 |
| AC-03 | PASS | 1회차 |
| AC-04 | PASS | 1회차 |
| AC-05 | PASS | 1회차 |
| AC-06 | PASS | 1회차 |
| AC-07 | PASS | 1회차 |
| AC-08 | 리더가 확인 (GitHub Actions) | |
| AC-09 | PASS | 1회차 |

## 관찰 방법 (AC-01~AC-06 공통)

- 브라우저: Claude in Chrome, 탭 `528666922` 하나. 18:19:10에 `http://127.0.0.1:4173/?subscription=0f09da5b-0000-4000-8000-000000000001`로 한 번 이동한 뒤 이동·새로 고침을 하지 않았다.
- 탭을 다시 읽지 않았다는 근거: 이동 직후 `javascript_tool`로 `window.__marker = "fr09-r1-msgxhd80bhr"`를 심었다. 새로 고침하면 사라지는 값이다. 판정 때마다 같은 값이 남아 있고 `performance.getEntriesByType("navigation")`이 `["navigate"]` 하나인지 확인했다.
- 화면 기록기: 같은 `javascript_tool` 호출로 100 ms마다 DOM(`tbody tr`의 `aria-level`과 칸 글자, 배지 class, `role=alert` 배너, `document.visibilityState`)을 읽어 바뀔 때만 `Date.now()`와 함께 `window.__rec`에 쌓는 `setInterval`을 걸었다. DOM을 읽기만 하고 요청을 보내지 않는다. 판정마다 `get_page_text`·스크린숏으로 화면 글자도 함께 읽었다.
- API 기록기: `backend/tests/e2e/dashboard_watch.py watch` (Windows `.venv-win` Python, Vite를 거치지 않고 anf-api 직접)가 0.5초마다 트리 전체를 읽어, 화면과 같은 행 형식 `[깊이, 이름, 종류, 상태, 속성]`이 바뀔 때마다 `t`(첫 관찰)와 `prev_t`(바로 앞 관찰)를 남긴다. 브라우저와 같은 Windows 시계다.
- 반영 지연 = 화면 기록기의 첫 관찰 시각 − API의 상태 변화 시각. API 변화 시각은 `prev_t`와 `t` 사이라서, 상한 = 화면 − `prev_t`로 판정한다(제한 5초).

## 항목별 결과

### [PASS] AC-02 지연 주입한 계정 생성이 새로 고침 없이 Creating → Succeeded (상태 전이, 화면)
- 기준: `netAppAccounts/create` `delaySeconds` 주입 상태에서 행이 새로 고침 없이 `Creating`으로 나타났다가 `Succeeded`로 바뀐다. 각 변화가 5초 안에 보인다.
- 실행: `PUT .../resourceGroups/rg-dash/providers/Microsoft.NetApp/netAppAccounts/dash-acct-a` `{"location":"westus2"}` (18:19:30.833) → `201 Created`, `azure-asyncoperation: .../operationResults/eb9b9e25-...`, 본문 `provisioningState: "Creating"`. 18:19:34.166 GET도 `Creating`.
- 화면(`get_page_text`, 18:19:36): `dash-acct-a NetApp account Creating rg-dash · westus2` / `Updated 6:19:36 PM · refreshes every 2 s`. 스크린숏에서 `Creating` 배지가 노랑(class `state busy`).
- 시각 비교:

  | 변화 | API (prev_t → t) | 화면 첫 관찰 | 지연 상한 |
  | --- | --- | --- | --- |
  | 행 생김, `Creating` | PUT 응답 18:19:30.9 (watcher 30.781 → 31.282) | 18:19:34.670 (`state busy`) | 3.9 s |
  | `Creating` → `Succeeded` | 18:19:46.307 → 46.807 | 18:19:46.917 (`state ok`) | 0.61 s |

- 새로 고침 없음: 18:19:55 marker `fr09-r1-msgxhd80bhr` 그대로, navigation `["navigate"]` 하나.
- 참고: 18:19:32.677~36.961 동안 탭이 `hidden`이었다(Windows 창 가림). `Creating` 행은 그 사이에 그려졌고 지연은 제한 안이다.

### [PASS] AC-01 트리가 API의 계층·이름·상태와 일치 (API 계약, 화면)
- 기준: 화면의 계정 > 풀 > 볼륨 > 스냅샷 계층, 이름, `provisioningState`가 API와 같다.
- 준비: 구독 `0f09da5b-0000-4000-8000-000000000001`, RG `rg-dash`. 계정 2개(`dash-acct-a` westus2, `dash-acct-b` eastus), `dash-acct-a` 아래 풀 2개(`pool-auto` 4 TiB Premium Auto, `pool-manual` 2 TiB Standard Manual), `pool-auto` 아래 실제 볼륨 2개(`vol-a` 1 GiB NFSv3, `vol-b` 2 GiB NFSv4.1), 스냅샷 3개(`vol-a`: `snap-1`, `snap-2` / `vol-b`: `snap-b1`). 빈 가지(`dash-acct-b`의 풀 없음, `pool-manual`의 볼륨 없음)를 일부러 넣었다. 모두 대시보드 탭을 연 뒤에 만들었다.
- 화면 (18:21:36.521, `javascript_tool`로 `tbody tr`의 `aria-level`과 칸 글자. 같은 탭, marker `fr09-r1-msgxhd80bhr`, navigation `["navigate"]` 하나):

  | 깊이 | 이름 | 종류 | 상태 | 속성 |
  | --- | --- | --- | --- | --- |
  | 1 | dash-acct-a | NetApp account | Succeeded | rg-dash · westus2 |
  | 2 | pool-auto | Capacity pool | Succeeded | 4 TiB · Premium · Auto QoS · 0.187 / 256 MiB/s |
  | 3 | vol-a | Volume | Succeeded | 172.30.0.129:/dash-vol-a · NFSv3 · 1 GiB · 0.062 MiB/s |
  | 4 | snap-1 | Snapshot | Succeeded | 2026-11-10T02:21:24Z |
  | 4 | snap-2 | Snapshot | Succeeded | 2026-11-10T02:21:25Z |
  | 3 | vol-b | Volume | Succeeded | 172.30.0.130:/dash-vol-b · NFSv4.1 · 2 GiB · 0.125 MiB/s |
  | 4 | snap-b1 | Snapshot | Succeeded | 2026-11-10T02:21:27Z |
  | 2 | pool-manual | Capacity pool | Succeeded | 2 TiB · Standard · Manual QoS · 0 / 32 MiB/s |
  | 1 | dash-acct-b | NetApp account | Succeeded | rg-dash · eastus |

- API (18:22:16, 그 사이 API 변화 없음 — watcher의 마지막 변화는 18:21:29.975): `dashboard_watch.py compare` → 9행 모두 `same`, `rows api=9 dom=9 identical=True`, rc 0. 비교기는 API 목록 GET 네 종류로 트리를 다시 만들고 설계 §1의 속성 규칙을 따로 구현한 것이다(프론트엔드 코드를 쓰지 않는다). 원본 목록: 계정 목록 `dash-acct-a`, `dash-acct-b` / `dash-acct-a` 풀 `pool-auto`, `pool-manual` / `dash-acct-b` 풀 없음 / `pool-auto` 볼륨 `vol-a`(172.30.0.129, `dash-vol-a`), `vol-b`(172.30.0.130, `dash-vol-b`) / `pool-manual` 볼륨 없음 / `vol-a` 스냅샷 `snap-1` 02:21:24Z, `snap-2` 02:21:25Z / `vol-b` 스냅샷 `snap-b1` 02:21:27Z.
- 스크린숏(18:22:25): 이름 칸이 깊이마다 들여쓰기되고 배지 9개가 모두 초록. 파일은 "보관 위치"의 `ac01_tree.jpg`.
- DOM 행 원본: `ac01_dom_rows_182136.json`.

### [PASS] AC-03 실제 볼륨·스냅샷 생성이 새로 고침 없이 보이고 마운트 경로가 API와 같고 실제로 마운트됨 (상태 전이, 데이터 효과)
- 기준: 실제 데이터 플레인에서 볼륨과 스냅샷을 만들면 새로 고침 없이 나타나고, 볼륨이 `Succeeded`가 된 뒤 마운트 경로 `<IP>:/<creationToken>`이 보인다. 그 경로가 API `mountTargets`와 같다. 그 경로로 클라이언트가 실제로 마운트된다.
- 실행: `PUT .../pool-auto/volumes/vol-a` (18:20:53.488, `creationToken dash-vol-a`, 1 GiB, NFSv3) → `201`, `Creating`, `actualThroughputMibps 0.062`. `PUT .../volumes/vol-b` (18:20:53.766, `dash-vol-b`, 2 GiB, NFSv4.1) → `201`, `Creating`. 스냅샷 `PUT .../vol-a/snapshots/snap-1` (18:21:23.411), `snap-2` (23.679), `.../vol-b/snapshots/snap-b1` (24.044) → 각각 `201`, `Creating`. storage agent가 컨테이너 `anf-nfs-53d2968b...`(vol-a), `anf-nfs-4547d6a6...`(vol-b)를 띄웠다.
- 진행 중 화면 (`get_page_text`, 18:20:57): `vol-a Volume Succeeded 172.30.0.129:/dash-vol-a · NFSv3 · 1 GiB · 0.062 MiB/s` / `vol-b Volume Creating NFSv4.1 · 2 GiB · 0.125 MiB/s` — `Creating`인 vol-b에는 마운트 경로가 없다. 같은 순간 API: vol-a `Succeeded` + `mountTargets [{"ipAddress":"172.30.0.129"}]`(18:20:56.136 GET), vol-b `Creating`이고 `mountTargets` 없음.
- 시각 비교 (화면은 기록기 첫 관찰. 기록기는 탭이 `hidden`이면 브라우저가 타이머를 1초 단위로 묶어서 화면 시각이 최대 1초 늦게 찍힌다. 그래도 아래는 상한이다):

  | 변화 | API prev_t → t | 화면 첫 관찰 (vis) | 지연 상한 |
  | --- | --- | --- | --- |
  | vol-a 행 `Creating` | 18:20:53.412 → 53.913 | 18:20:55.670 (hidden) | 2.3 s |
  | vol-b 행 `Creating` | 53.913 → 54.414 | 55.670 (hidden) | 1.8 s |
  | vol-a `Succeeded` + `172.30.0.129:/dash-vol-a` | 55.916 → 56.416 | 58.673 (hidden) | 2.8 s |
  | vol-b `Succeeded` + `172.30.0.130:/dash-vol-b` | 57.919 → 58.420 | 59.915 (visible) | 2.0 s |
  | snap-1 행 `Creating` | 18:21:23.465 → 23.965 | 24.676 (hidden) | 1.2 s |
  | snap-2 행 `Creating` | 23.465 → 23.965 | 27.669 (hidden) | 4.2 s |
  | snap-b1 행 `Creating` | 23.965 → 24.466 | 27.669 (hidden) | 3.7 s |
  | snap-1 `Succeeded` + `2026-11-10T02:21:24Z` | 26.470 → 26.970 | 27.669 (hidden) | 1.2 s |
  | snap-2 `Succeeded` | 27.972 → 28.473 | 30.672 (hidden) | 2.7 s |
  | snap-b1 `Succeeded` | 29.475 → 29.975 | 33.677 (hidden) | 4.2 s |

- 마운트 경로와 API: 화면 `172.30.0.129:/dash-vol-a`, `172.30.0.130:/dash-vol-b` = API `mountTargets[0].ipAddress` + `:/` + `creationToken` (AC-01 비교에서 글자까지 같음).
- 데이터 효과 (WSL root, `anf-vnet`의 `anf-nfs-client` 컨테이너, 화면의 경로를 그대로 사용):
  - 18:21:13 `mount -t nfs -o vers=3,nolock,... 172.30.0.129:/dash-vol-a /m` → `/proc/mounts`: `172.30.0.129:/dash-vol-a /m nfs rw,...,vers=3,...,addr=172.30.0.129`. `echo dashboard-r1 > /m/hello.txt && cat` → `dashboard-r1`. `df`: `974M` (1 GiB 볼륨). rc 0.
  - 18:21:14 `mount -t nfs -o vers=4.1,... 172.30.0.130:/dash-vol-b /m` → `nfs4 rw,...,vers=4.1,...,addr=172.30.0.130`. 쓰기·읽기 `dashboard-r1-b`, `df` `2.0G`. rc 0.
  - 다른 새 클라이언트에서 vol-a를 다시 마운트해 `cat /m/hello.txt` → `dashboard-r1`. rc 0.
  - 스냅샷 행이 실제 스냅샷인지: 18:22 vol-a `ls /m/.snapshot` → `snap-1 snap-2`, `cat /m/.snapshot/snap-1/hello.txt` → `dashboard-r1`. vol-b(v4.1) `ls /m/.snapshot` → `snap-b1`, 내용 `dashboard-r1-b`.
- 새로 고침 없음: 18:21:36 marker 그대로, navigation `["navigate"]` 하나.

### [PASS] AC-04 삭제: Deleting 뒤 행이 사라짐 (상태 전이, 화면)
- 기준: 리소스를 삭제하면 `Deleting`이 보인 뒤 행이 사라진다.
- 실행: `netAppAccounts/delete` `delaySeconds: 15` 주입 상태에서 `DELETE .../netAppAccounts/dash-acct-b` (18:23:57.971) → `202 Accepted`, `location`·`azure-asyncoperation` 헤더. 18:24:00.293 GET → `provisioningState: "Deleting"`. 18:24:14.280 GET → `404`, `{"error":{"code":"ResourceNotFound",...}}`.
- 화면: `get_page_text` 18:24:01 → `dash-acct-b NetApp account Deleting rg-dash · eastus` (스크린숏 `ac04_deleting.png`에서 노랑 배지). 18:24:22 `javascript_tool` → 행 8개, `dash-acct-b` 없음 (나머지 `dash-acct-a … pool-manual Failed` 그대로).
- 시각 비교:

  | 변화 | API prev_t → t | 화면 첫 관찰 (vis) | 지연 상한 |
  | --- | --- | --- | --- |
  | `dash-acct-b` `Succeeded` → `Deleting` | 18:23:57.722 → 58.222 (DELETE 응답 57.97) | 18:23:59.674 (hidden) | 2.0 s |
  | `dash-acct-b` 행 사라짐 (9행 → 8행) | 18:24:13.249 → 13.750 | 18:24:14.209 (visible) | 1.0 s |

- 오류 배너는 이 동안 한 번도 뜨지 않았다(기록기의 `banner`가 모두 `null`).
- 새로 고침 없음: 18:24:22 marker 그대로, navigation `["navigate"]` 하나.
- 실제 데이터 플레인 삭제(스냅샷·볼륨)도 정리 단계에서 같은 방법으로 관찰했다. 아래 "정리 중 관찰" 참고.

### [PASS] AC-05 강제 실패 주입: Failed 배지 (상태 전이, 화면)
- 기준: 강제 실패를 주입한 작업의 리소스가 `Failed` 배지로 보인다.
- 실행: `ANF_FAULT_INJECTION`의 `capacityPools/patch: {"fail": true}` 상태에서 `PATCH .../capacityPools/pool-manual` `{"tags":{"verify":"fr09-ac05"}}` (18:23:13.944) → `202 Accepted`, `azure-asyncoperation`·`location` 헤더, 본문 `provisioningState: "Patching"`. 18:23:15.753 GET → `provisioningState: "Failed"`, `tags: {}`(이전 값으로 되돌아감). 작업 상태 → `"status":"Failed"`, `"error":{"code":"InternalServerError","message":"Injected fault: capacityPools/patch (ANF_FAULT_INJECTION)."}`.
- 화면 (`get_page_text`, 18:23:21): `pool-manual Capacity pool Failed 2 TiB · Standard · Manual QoS · 0 / 32 MiB/s`. 나머지 8행은 `Succeeded` 그대로.
- 배지 (18:23:27, `javascript_tool`): `pool-manual` 배지 class `state failed`, 글자 `Failed`, 계산된 색 `rgb(242, 149, 142)` / 배경 `rgb(67, 32, 29)` (빨강 계열). 비교용 `state ok` 배지는 `rgb(111, 211, 155)` / `rgb(22, 53, 36)` (초록). 확대 스크린숏 `ac05_failed.png`에서도 빨간 배지.
- 시각: API watcher `Succeeded` 18:23:13.649 → `Failed` 14.149. 화면 기록기 `Failed` 첫 관찰 18:23:14.921 (visible). 지연 상한 1.3 s. `Patching`은 약 10 ms(작업 startTime 02:23:14.390834Z, endTime 02:23:14.400987Z)라 화면과 watcher 모두 보지 못했다(지연 없이 실패하는 주입이라 정상).
- 새로 고침 없음: 18:23:27 marker 그대로, navigation `["navigate"]` 하나.
- 범위 밖 관찰: 화면에는 실패 이유가 없다(설계 §1 "만들지 않는 것"대로).

### [PASS] AC-06 anf-api 중지: 오류 배너 + 마지막 트리, 재시작 뒤 자동 복구 (화면)
- 기준: anf-api를 멈추면 오류 배너가 뜨고 마지막 트리가 남는다. 같은 DB로 다시 띄우면 새로 고침 없이 배너가 사라지고 트리가 갱신된다.
- 중지: 18:24:52.958 `kill -TERM <anf-api pid 4940>` → 18:24:53.412 프로세스 없음, 로그 `Application shutdown complete.` `Finished server process [4940]`. 그 직후 Windows에서 anf-api 직접 → `000`(연결 거부), Vite 프록시 경유 → `502`. API watcher: 18:24:53.314 `WinError 10053`, 53.815 `WinError 10061 No connection could be made`.
- 중지 중 화면 (`get_page_text`, 18:25 무렵):
  - 배너: `Cannot read from anf-api: GET /subscriptions/0f09da5b-0000-4000-8000-000000000001/providers/Microsoft.NetApp/netAppAccounts returned 502. Showing the last successful read. Retrying every 2 s.`
  - 표: 중지 직전 트리 8행 그대로(`dash-acct-a … pool-manual Failed`).
  - `Updated 6:24:52 PM · refreshes every 2 s` (마지막 성공 읽기 시각에서 멈춤).
  - 기록기: 배너 첫 관찰 18:24:56.680 (hidden, 중지 뒤 3.7 s 이내). 18:25:35까지 배너와 8행이 계속 유지(`rows: 8`, 같은 배너 글자). 스크린숏은 이 순간 CDP 시간 초과로 찍지 못했다(창이 가려진 상태로 보임). 글자 판정에는 영향 없음.
- 재시작: 18:25:44.299 같은 DB(`/home/mkimhome1/fr09-r1/anf.db`)로 `run_api.sh` 실행(새 pid 6097, 결함 주입 없음). 로그에 오류 없음(`Application startup complete.`). API watcher: 18:25:42.994(실패) → 45.039 첫 성공, 8행.
- 재시작 뒤 화면:
  - 기록기: 배너 사라짐 첫 관찰 18:25:46.308 (visible, 행 8개 유지). API 복구 관찰 뒤 1.3 s, 재시작 명령 뒤 2.0 s.
  - `get_page_text` 18:25:54: 배너 없음, 8행, `Updated 6:25:54 PM`. 18:25:58 `Updated 6:25:56 PM` (2초마다 갱신 재개).
  - 트리 갱신: 18:26:14.183 `PUT .../netAppAccounts/dash-acct-c` → `201`, `Creating`. API watcher `Succeeded` 18:26:14.251 → 14.751. 화면 기록기 18:26:15.217 `dash-acct-c NetApp account Succeeded` 행 생김(9행). 지연 상한 1.0 s.
  - 18:26:23 DOM 9행과 18:26:37 API 행을 `dashboard_watch.py compare` → `rows api=9 dom=9 identical=True`.
- 새로 고침 없음: 18:26:23 marker `fr09-r1-msgxhd80bhr` 그대로, navigation `["navigate"]` 하나. 중지 전 트리가 남아 있었다는 것 자체도 새로 고침이 없었다는 근거다(새로 고침했다면 첫 읽기 실패로 트리 없이 배너만 보인다).

### [PASS] AC-07 typecheck / build / test (빌드)
- 기준: `npm run typecheck`, `npm run build`, `npm test`가 통과한다.
- 실행 (Windows, `frontend/`, 18:15:32~18:15:58): `npm ci` → rc 0 (143 packages). `npm run typecheck` (`tsc --noEmit`) → rc 0, 출력 없음. `npm run test` (`vitest run`, v5.1.0) → `Test Files 4 passed (4)`, `Tests 23 passed (23)`, rc 0 (skip 없음). `npm run build` (vite v8.3.7) → `19 modules transformed`, `dist/assets/index-Bf288wRx.js 223.21 kB`, `✓ built in 209ms`, rc 0.
- 출력 원본: scratchpad `ac07_typecheck.txt`, `ac07_test.txt`, `ac07_build.txt` (경로는 아래 "보관 위치").
- 화면 검증(AC-01~06)은 이 빌드 결과를 `npm run preview`로 띄워 했다.

### [리더가 확인] AC-08 CI의 `frontend` 작업이 PR에서 통과
- 이번 회차 범위 밖. 리더가 GitHub Actions 결과로 확인한다.

### [PASS] AC-09 백엔드 해시 불변, 기존 pytest GREEN (회귀)
- 기준: 백엔드 제품 코드 내용 해시가 `f99bc5cf…`(FR-08 검증 값) 그대로이고 기존 pytest가 GREEN이다.
- 해시: 시작(18:11:49)과 끝(18:28:42) 모두 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`. 명령은 머리말.
- pytest (Windows, `.venv-win\Scripts\python -m pytest -q -rs`, 18:15:31~18:17:28): `914 passed, 176 skipped in 107.92s`, 실패·오류 0, 종료 코드 0. skip 이유는 두 가지뿐: `ANF_E2E_API_URL is not set (live anf-api e2e runs in WSL)` 146개, `needs root on Linux (WSL Ubuntu)` 30개. 둘 다 Windows에서 돌릴 수 없는 live e2e·root 통합 시험이고, 같은 해시의 코드에서 FR-08 검증 때 실행된 것들이다. 이번 회차는 그 시험들을 다시 돌리지 않았다(백엔드 코드가 바뀌지 않았으므로 리더가 지정한 범위대로 Windows 결과만 본다).
- 원본: scratchpad `ac09_pytest.txt`.

## 정리 중 관찰 (AC-04 보강: 실제 데이터 플레인 삭제)

결함 주입 없이 다시 띄운 anf-api에서 실제 스냅샷·볼륨을 지우며 같은 탭을 계속 관찰했다.

| 변화 | API prev_t → t | 화면 첫 관찰 (vis) | 지연 상한 |
| --- | --- | --- | --- |
| `snap-2`(실제 스냅샷), `vol-b`(실제 볼륨) `Deleting` (DELETE 18:27:05.733, 06.032 → 둘 다 `202`) | 18:27:05.832 → 06.332 | 18:27:08.681 (hidden) | 2.9 s |
| `snap-2` 행 사라짐 | 07.834 → 08.335 | 10.012 (visible) | 2.2 s |
| `vol-b`와 그 스냅샷 `snap-b1` 행이 함께 사라짐 (8행 → 6행) | 10.342 → 10.843 | 12.110 (visible) | 1.8 s |

- `get_page_text` 18:27:09: `vol-b Volume Deleting 172.30.0.130:/dash-vol-b · NFSv4.1 · 2 GiB · 0.125 MiB/s` / `snap-b1 Snapshot Succeeded …` (부모만 `Deleting`).
- 18:27:16 데이터 플레인: 컨테이너는 `anf-nfs-53d2968b…`(vol-a)만, LV는 `aggr0`, `snap_07266d9c…`(snap-1), `vol_53d2968b…`(vol-a)만 남음 — vol-b와 그 스냅샷 LV·인스턴스가 실제로 지워졌다.
- 이어서 `snap-1` → `vol-a` → 풀 2개 → 계정 2개를 지웠다. 화면은 `snap-1 Deleting`(18:27:41.116) → `vol-a Deleting`(43.211) → 행 사라짐(45.310) → `No NetApp accounts in this subscription.`(47.315; API 계정 목록 `{"value":[]}`은 47.6).
- 세션 전체(18:19:12~18:27:52, 기록 47건)에서 오류 배너는 AC-06 중지 구간의 502 배너 하나뿐이었다. 부모가 지워지는 동안(설계 결정 7) 배너가 깜박이지 않았다.
- 탭은 끝까지 한 번만 이동했다: 18:27:52 navigation `[{"type":"navigate","name":"http://127.0.0.1:4173/?subscription=0f09da5b-…"}]`, marker 그대로.

## 통합 정합성 (설계 §4 · real-env-verify §3)
- 응답 구조: 대시보드가 읽는 필드(`value`, `id`, `name`, `location`, `properties.provisioningState`, 풀의 `size`·`serviceLevel`·`qosType`·`utilizedThroughputMibps`·`totalThroughputMibps`, 볼륨의 `mountTargets[0].ipAddress`·`creationToken`·`protocolTypes`·`usageThreshold`·`actualThroughputMibps`, 스냅샷의 `created`)가 이번에 받은 실제 anf-api 응답에 모두 같은 이름·대소문자로 있었다(위 PUT/GET 본문). 볼륨 `Creating` 본문에는 `mountTargets`가 없고, 화면도 그때 경로를 비웠다.
- 호출 관계: 대시보드가 부르는 것은 설계 §4의 목록 GET 네 종류뿐이고(`armClient.ts`), 모두 anf-api에 있다. 프록시 경유 오류(`502`)는 "그 회의 실패"로 처리됐다(AC-06).
- 이름: 풀·볼륨·스냅샷의 `name`은 `dash-acct-a/pool-auto/vol-a/snap-1` 형식이고 화면은 마지막 조각만 보인다(설계대로).

## 측정값

반영 지연 상한(화면 첫 관찰 − API `prev_t`), 단위 s. 탭이 `hidden`이면 Chrome이 타이머를 1초 단위로 묶어서 대시보드의 폴링과 기록기의 샘플이 함께 늦어진다.

| 기준 | 변화 | 상한 | 탭 |
| --- | --- | --- | --- |
| AC-02 | 계정 행 `Creating` / `Succeeded` | 3.9 / 0.6 | hidden / visible |
| AC-01 준비 | 계정 B `Creating` / `Succeeded` | 2.8 / 2.6 | hidden / visible |
| AC-03 | vol-a 행 / vol-b 행 / vol-a 경로 / vol-b 경로 | 2.3 / 1.8 / 2.8 / 2.0 | hidden ×3 / visible |
| AC-03 | snap-1·snap-2·snap-b1 행 | 1.2 / 4.2 / 3.7 | hidden |
| AC-03 | snap-1·snap-2·snap-b1 `Succeeded` | 1.2 / 2.7 / 4.2 | hidden |
| AC-04 | 계정 `Deleting` / 행 사라짐 | 2.0 / 1.0 | hidden / visible |
| AC-04 보강 | 실제 삭제 `Deleting` / 스냅샷 사라짐 / 볼륨+스냅샷 사라짐 | 2.9 / 2.2 / 1.8 | hidden / visible / visible |
| AC-05 | `Failed` | 1.3 | visible |
| AC-06 | 배너 뜸(중지 명령부터) / 배너 사라짐(API 복구부터) / 새 계정 행 | 3.7 / 1.3 / 1.0 | hidden / visible / visible |

- 표본 23개, 최대 4.2 s, 모두 5 s 이하. 4 s를 넘은 두 건(snap-2 행, snap-b1 `Succeeded`)은 둘 다 `hidden` 구간이다. 탭 가시성은 18:19~18:27 동안 22번 바뀌었다(브라우저 도구가 탭을 다룰 때 `visible`, 약 20~40초 뒤 `hidden`). 창이 가려진 채 5분 넘게 두면 Chrome의 강한 타이머 제한이 걸릴 수 있어서, 사람이 화면을 보는 상황(visible)보다 이번 값이 보수적이다.

## 참고 사항 (리더에게)
- Chrome: 검증 시작 때 Windows에 Chrome이 실행 중이 아니어서 확장 연결이 실패했다. `C:\Program Files\Google\Chrome\Application\chrome.exe about:blank`로 직접 띄웠고, 검증용 탭은 닫았지만 Chrome 자체(내가 띄운 `about:blank` 창)는 사용자의 브라우저라 닫지 않고 두었다. 다음 화면 검증 전에는 Chrome이 떠 있어야 한다.
- 스크린숏 한 번(AC-06 중지 직후)이 CDP `Page.captureScreenshot` 30초 시간 초과로 실패했다. 판정은 같은 순간의 `get_page_text`와 기록기 글자로 했다.
- 즉시 실패 주입(`fail: true`, 지연 없음)에서는 `Patching`이 약 10 ms라 화면에 보이지 않는다. 진행 중 상태와 `Failed`를 한 번에 보이려면 `{"delaySeconds": N, "fail": true}`를 쓰면 된다(AC-05 기준에는 필요 없음).

## 보관 위치

실행 중 로그는 WSL 디스크(`/home/mkimhome1/fr09-r1`, `/root/fr09-r1`)에 쓰고, 끝난 뒤 아래로 복사해 sha256이 모두 같음을 확인한 다음 WSL 쪽을 지웠다.

scratchpad: `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\6c68f06d-7444-4df0-bc74-fa18593a1c49\scratchpad\`
- `api_watch.jsonl`: API watcher 기록(Windows 시계, 변화마다 한 줄)
- `ac01_dom_rows_182136.json`, `ac06_dom_rows_182623.json`: 비교에 쓴 DOM 행
- `ac01_tree.jpg`, `ac05_failed.png`, `ac04_deleting.png`: 스크린숏
- `ac07_typecheck.txt`, `ac07_test.txt`, `ac07_build.txt`, `ac09_pytest.txt`: 명령 출력
- `wsl_logs\api\` (`anf.db`, `api-1.log`(결함 주입 실행), `api-2.log`(재시작 뒤)), `wsl_logs\agent\agent.log`
- `run_api.sh`, `run_agent.sh`, `faults1.json`, `arm.sh`, `ac06_restart_time.txt`: 실행 스크립트

## 정리 결과
- 만든 ARM 리소스: 모두 API로 삭제(마지막 계정 목록 `{"value":[]}`).
- 데이터 플레인: 컨테이너 0개, LV `aggr0`(Data% 0.00)뿐, `ns/`·`exports/` 비어 있음. 시작 때와 같다.
- 프로세스: anf-api(pid 6097), storage agent(pid 4882), API watcher, Vite preview 종료. 8080/8090/4173/5173 비어 있음.
- 브라우저: 검증용 탭 `528666922` 닫음(MCP 탭 그룹 자동 제거). 기록기 `setInterval`은 닫기 전에 해제.
