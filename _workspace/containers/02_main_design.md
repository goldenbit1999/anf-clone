# 컨테이너 (FR-13) 설계

- 작성: 2026-11-10 (메인). 조사 생략(PRD §8). 스파이크 `_workspace/spikes/S9.md`(조건부 통과)
- PRD FR-13: "구성요소를 컨테이너로 묶고 docker compose로 띄운다." 수락: "문서에 적힌 명령 하나로 전체를 띄울 수 있다." PRD §9: "§5의 데모 대본을 스크립트 하나로 처음부터 끝까지 재현할 수 있다"(FR-10에서 여기로 미룸). NFR-06: 데모 전체가 WSL 메모리 약 7 GB 안.
- **사용자 결정 (2026-11-10)**: WSL Ubuntu에 `docker-compose-v2`와 `docker-buildx`를 apt로 설치한다. 설치함(Compose 2.40.3, buildx 0.30.1).
- 그 밖의 결정 1~12는 `자동 채택`이다.

## 1. 구성

```
docker compose -f deploy/compose.yaml up -d --build --wait      ← 문서에 적는 명령 하나
  ├─ init            한 번 돌고 끝남(특권): 호스트 준비 = 지금의 scripts/setup-wsl-dataplane.sh가 하는 일 + ns 바인드
  ├─ storage-agent   특권, host 네트워크·pid, 127.0.0.1:8090
  ├─ anf-api         일반 사용자, host 네트워크, 127.0.0.1:8080, SQLite는 이름 있는 볼륨
  ├─ prometheus      prom/prometheus:v3.15.1, host 네트워크, 127.0.0.1:9090, deploy/prometheus/prometheus.yml
  └─ dashboard       nginx(다단계 빌드: node → nginx), host 네트워크, 127.0.0.1:8081
                     /subscriptions → 8080, /prometheus/ → 9090(접두사 제거), 나머지는 SPA
compose 밖: 볼륨 인스턴스 anf-nfs-<uuid>(agent가 띄운다), 클라이언트 컨테이너, 네트워크 anf-vnet(external)
```

- 모두 host 네트워크에 localhost 바인딩이다(ADR §5 "바인딩"). Windows 브라우저는 `http://127.0.0.1:8081/?subscription=<id>`로 연다.
- sudo 없이 docker 그룹 사용자로 뜬다. 호스트 준비는 특권 `init` 서비스가 한다.

### storage agent 컨테이너 (S9 Q2의 다섯 조건, 모두 필수)
1. `privileged`, `network_mode: host`, `pid: host`(없으면 `nsenter -t <pid>`가 실패한다, P4).
2. `/var/lib/anf-clone`은 **재귀하지 않는** 바인드(`bind-recursive: disabled`. 재귀하면 재시작 때 private 복사본이 생겨 되돌리기가 실패한다, P3).
3. `/var/lib/anf-clone/ns`는 `rshared` 바인드. 그 전에 호스트에서 `ns`가 rshared 바인드여야 한다(P1) — `init`이 한다.
4. `/run/lock/lvm` 공유(호스트 udev 자동 활성화와 겹치지 않게, P2). `/run/udev`는 붙이지 **않는다**(붙이면 `lvcreate`가 udev 세마포어를 4분 넘게 기다린다, L3).
5. `/dev`, `/lib/modules`(ro), `/var/run/docker.sock`.
- 이미지: `ubuntu:24.04` + lvm2, thin-provisioning-tools, e2fsprogs, iproute2, iptables, util-linux, kmod, procps, python3-venv, docker CLI. 저장소 루트의 `pyproject.toml`로 설치한다.

## 2. 데모 대본 스크립트

- `scripts/demo.py`: Python 표준 라이브러리만 쓴다(호스트의 `python3`, venv 불필요). root 없이 docker 그룹으로 돈다. 클라이언트는 `anf-nfs-client` 컨테이너를 `docker run`으로 띄운다.
- PRD §5의 1~7단계를 차례로 하고, 단계마다 한 일과 **클라이언트에서 관찰한 근거**를 한 줄씩 출력한다. 기대와 다르면 그 자리에서 멈추고 0이 아닌 코드로 끝난다.
  1. 계정 → 풀(Manual QoS) → 볼륨 둘(NFSv3, NFSv4.1) 생성. 요청마다 즉시 응답을 보이고 `Succeeded`까지 폴링.
  2. 클라이언트가 `<마운트 대상 IP>:/<creationToken>`을 마운트해 파일을 쓴다(v3, v4.1 각각).
  3. 스냅샷 → 파일 삭제 → `.snapshot/<이름>/`에서 그 파일을 읽는다.
  4. 되돌리기 → 지운 파일이 다시 보인다.
  5. 스냅샷으로 새 볼륨 → 다른 클라이언트가 마운트, 새 볼륨에 써도 원본은 그대로.
  6. 처리량 제한: fio로 쓰기 처리량을 재고(한도의 90~101%), 한도를 바꾸면 잰 값이 따라 바뀐다.
  7. 대시보드와 메트릭: Prometheus 쿼리로 그 볼륨의 처리량 계열에 방금 부하가 보이고, 대시보드(8081)가 페이지와 두 프록시를 돌려준다. 브라우저로 열 주소를 출력한다.
- 끝나면 만든 리소스와 클라이언트를 지운다. `--keep`이면 남겨서 사람이 대시보드를 볼 수 있게 한다. 스택이 떠 있지 않으면 한 줄 안내와 함께 코드 2로 끝난다.
- 걸리는 시간 목표: 3분 안(S9: 1~6단계 62 s).

## 3. 테스트와 CI

- **단위**: `demo.py`의 순수 부분(응답 해석, 판정, 출력 형식)과 compose 파일의 불변 조건(agent 서비스의 다섯 조건이 빠지지 않았는지 — YAML을 읽어 단언)을 단위 테스트로 둔다.
- **실환경**: `backend/tests/e2e/test_compose_stack_live.py`(`dataplane` 마커). compose로 띄우고(`--wait`) `scripts/demo.py`를 돌려 종료 코드 0과 단계별 근거 줄을 확인하고, 내리기 전후 동작(아래 AC-02)과 메모리(AC-07)를 기록한 뒤 내리고 치운다. 실행기와 CI `rest` 조각에 자동으로 들어간다. 다른 데이터 플레인 파일과 포트(8080·8090·9090)를 같이 쓰므로 실행기의 파일별 순차 실행에 기대고, 끝나면 포트와 컨테이너를 남기지 않는다.
- 스택이 떠 있는 동안 실행기는 사전 점검에서 코드 2로 끝난다(이미 있는 포트 점검). 문서에 "테스트 전에 스택을 내린다"를 적는다.
- CI에 새 작업은 만들지 않는다(위 e2e 파일이 `data-plane`의 `rest` 조각에서 돈다).

## 4. 결정 (자동 채택)

| # | 결정 | 고른 것 | 버린 대안과 이유 |
| --- | --- | --- | --- |
| 1 | 명령 하나 | `docker compose -f deploy/compose.yaml up -d --build --wait` | 준비 스크립트 + compose 두 단계(명령이 둘이고 sudo가 필요), 래퍼 스크립트(compose를 가린다) |
| 2 | 호스트 준비 | compose의 한 번 도는 특권 `init` 서비스. 지금의 `setup-wsl-dataplane.sh`가 하는 일을 다시 쓰지 않고 같은 스크립트를 호스트 네임스페이스에서 돌린다(`nsenter -t 1`). 스크립트는 그대로 테스트 경로에서도 쓴다. `ns`의 rshared 바인드를 여기서 더한다 | 준비 로직을 compose 쪽에 한 벌 더 둠(두 벌이 어긋난다) |
| 3 | agent | 컨테이너(특권, 다섯 조건) | 호스트 root 프로세스로 남김(구성요소를 컨테이너로 묶는다는 FR-13에 못 미치고 sudo가 필요). 컨테이너여도 권한은 root와 같다는 점을 문서에 적는다 |
| 4 | `down` 뒤의 볼륨 인스턴스 | 남긴다. 컨트롤 플레인과 agent가 내려가도 데이터 서비스는 계속된다(S9: 내린 상태에서 쓰기 계속). 다시 `up`하면 agent가 복구한다 | `down`에서 인스턴스도 멈춤(compose 밖이라 별도 스크립트가 필요하고, "관리 계층이 죽어도 데이터는 계속"이라는 설명을 잃는다). 다 지우려면 API로 리소스를 지운다(데모 스크립트는 스스로 치운다) |
| 5 | `anf-vnet` | external 네트워크. `init`이 만든다(지금 스크립트와 같은 서브넷) | compose가 소유(`down`이 지우려다 인스턴스 때문에 실패한다) |
| 6 | 대시보드 | nginx 다단계 빌드(74 MB, 11 MiB), 포트 8081 | `vite preview` 컨테이너(534 MB, 78 MiB), Windows의 Vite에 의존(WSL만으로 전체가 뜨지 않는다) |
| 7 | anf-api 상태 | 이름 있는 볼륨의 SQLite. `down`에도 남는다 | 컨테이너 안(재생성하면 리소스 기록이 사라져 agent의 볼륨과 어긋난다) |
| 8 | 데모 스크립트 | Python 표준 라이브러리, `scripts/demo.py`, 스스로 치움 + `--keep` | bash(JSON·폴링이 어렵다), pytest로만(사람이 읽는 대본 출력이 안 된다), e2e 헬퍼 재사용(venv와 root가 필요해진다) |
| 9 | 실환경 테스트 위치 | `dataplane` e2e 한 파일이 compose + 데모를 돌린다 | CI에 별도 작업(실행 경로가 둘이 된다) |
| 10 | 이미지 | 바탕 이미지는 태그로 고정, `.dockerignore`로 빌드 컨텍스트를 줄임(루트가 275 MB) | digest 고정(갱신이 번거롭다. 포트폴리오 범위 밖) |
| 11 | Prometheus | compose 서비스가 같은 설정 파일을 쓴다. `scripts/run-prometheus.sh`는 호스트 프로세스 경로(테스트)용으로 남긴다 | 스크립트 삭제(FR-12 e2e가 쓴다) |
| 12 | 회귀 | PR의 CI `data-plane` 작업. WSL에서는 새 파일과 영향받는 파일만 | WSL 전체 묶음(약 95분) |

## 5. 수락 기준

| ID | 기준 |
| --- | --- |
| AC-01 (PRD) | WSL을 다시 시작한 직후, sudo 없이 docker 그룹 사용자로 문서의 명령 하나를 그대로 실행하면 네 서비스가 healthy가 된다(`--wait`가 0으로 끝남). 걸린 시간을 기록한다(이미지가 있을 때, 처음 빌드할 때). |
| AC-02 | 같은 명령을 다시 실행해도 바뀌는 것이 없다. 볼륨이 있는 상태에서 `down` → 클라이언트 I/O가 계속된다 → `up` → agent가 볼륨을 복구하고 API가 같은 리소스를 보인다. |
| AC-03 (PRD §9) | 스택이 뜬 상태에서 `python3 scripts/demo.py`가 root 없이 1~7단계를 끝내고 0으로 끝난다. 단계마다 클라이언트에서 관찰한 근거(읽은 파일 내용, 잰 MiB/s, Prometheus 값)가 출력에 있다. 끝난 뒤 만든 리소스·클라이언트가 남지 않는다. 3분 안. |
| AC-04 | 스택이 없으면 데모 스크립트가 안내와 함께 코드 2로 끝난다. 단계의 기대가 어긋나면(예: 볼륨이 `Failed`) 0이 아닌 코드로 끝나고 어느 단계인지 보인다(단위 테스트로 확인해도 된다). |
| AC-05 | Windows 브라우저(headless Chrome 포함)로 `http://127.0.0.1:8081/?subscription=<id>`를 열면 리소스 트리와 볼륨 차트가 보인다(nginx 프록시를 거친 API·Prometheus). |
| AC-06 | agent 컨테이너를 쓰는 중에 `docker kill`해도 클라이언트 쓰기 오류가 0이고, 다시 뜨면 볼륨·스냅샷·한도가 그대로다. 되돌리기·삭제가 재시작 뒤에도 성공한다(S9 P3의 회귀). |
| AC-07 (NFR-06) | 데모가 도는 동안 WSL의 사용 메모리가 7 GB 안이다. `free -m`과 `docker stats` 값을 기록한다. |
| AC-08 | 스택이 떠 있으면 `scripts/run-dataplane-tests.sh`가 코드 2로 끝난다. 스택을 내리고 데모가 치운 뒤에는 사전 점검을 통과하고 남은 것이 없다. |
| AC-09 | PR의 CI에서 backend·frontend·`data-plane` 두 조각이 통과한다(`rest` 조각에 compose e2e 포함). |
| AC-10 | WSL `-m "not dataplane"` 묶음 통과·skip 0, ruff 통과, 프런트엔드 typecheck·test·build 통과. |
| AC-11 | 문서(`README.md`의 빠른 시작)에 적힌 명령과 주소가 검증에서 그대로 쓴 것과 같다. |

## 6. 구현 메모

- 새 파일(예): `deploy/compose.yaml`, `deploy/agent/Dockerfile`, `deploy/api/Dockerfile`, `deploy/dashboard/Dockerfile`·`nginx.conf`, `.dockerignore`, `scripts/demo.py`, `README.md`(빠른 시작: 요구 사항, 명령 하나, 데모, 내리기, 테스트 전 내리기).
- `init`이 준비 스크립트를 호스트에서 돌리는 방식이 불안정하면(저장소 경로 전달, `/mnt/c` 접근 등) 근거와 함께 돌아온다. 그때의 후보는 "준비 스크립트는 한 번만 손으로(문서에 적음), 명령 하나는 compose"다 — 이것은 AC-01을 바꾸므로 메인이 정한다.
- 제품 코드(`backend/`)는 되도록 바꾸지 않는다. 바꿔야 하면(예: 컨테이너 안에서의 `check_host`) 최소로 하고 TDD로 한다.
- healthcheck는 이미지에 있는 도구로(파이썬 urllib, wget).
- 문서(ADR, `CLAUDE.md`, 개념 문서)는 메인과 concept-explainer가 한다.

## 7. 구현 중 변경

1. **agent의 LVM이 호스트 udev를 기다린다(§1 조건 4를 바꿈).** `/run/udev`(ro)와 `ipc: host`를 함께 둔다(S9 L4). S9가 고른 L2(`/run/udev` 없음)로 데모를 처음 돌렸을 때 5단계(새 볼륨 복원)가 실패했다: `mount -t ext4 -o ro,noload /dev/anf/snap_… exited 32: special device /dev/anf/snap_… does not exist`. 컨테이너 LVM이 udev와 맞추지 않으니 `lvcreate`가 호스트 udev의 처리 전에 돌아오고, 바로 뒤의 mount가 경합에서 질 때가 있다. 호스트 프로세스 agent는 LVM이 udev 쿠키를 기다려서 이 경합이 없었다. L4에서는 LVM이 호스트 프로세스처럼 기다린다. `/run/udev`만 붙이면 여전히 멈추므로(L3) 단위 테스트가 둘을 함께 요구한다. 같은 순서를 흉내 낸 15회 탐침은 L2·L4 모두 0회 실패였고(경합이 드물다), L4로 바꾼 뒤 데모 6회(아래 3번 전후) 모두 5단계가 통과했다.
2. **명령 하나의 `--build`와 AC-02 "다시 실행해도 바뀌는 것이 없다"가 맞지 않는다 — 메인 결정 필요.** 같은 `up -d --build --wait`를 다시 돌리면(8.5 s, 0으로 끝남) `init`·`storage-agent`·`anf-api`·`dashboard`가 `Recreate`된다. 빌드 단계는 모두 CACHED인데 BuildKit이 빌드마다 provenance attestation(시각·호출 ID가 든 manifest)을 붙여 이미지 ID가 바뀌기 때문이다. compose 2.40.3은 서비스의 `build.provenance: false`를 bake로 넘기지 않아(`build --print`에 없음) 효과가 없었고, `SOURCE_DATE_EPOCH`로도 ID가 같아지지 않았다. 같아지는 방법은 환경 변수 `BUILDX_NO_DEFAULT_ATTESTATIONS=1`(명령 앞에 붙여야 함, `deploy/.env`로는 전달되지 않음)이나 `docker compose build --provenance=false`(up에는 그 옵션이 없음)뿐이다. `--build` 없이 `up -d --wait`를 다시 돌리면 2.7 s에 `init`만 다시 돌고 나머지는 `Running`이다(이미지가 없으면 처음에는 빌드한다). 다시 만들어져도 볼륨 인스턴스는 그대로이고 클라이언트 쓰기와 API 리소스도 그대로다(e2e가 본다). 선택지: (가) 명령에서 `--build`를 빼고, 코드를 바꾼 뒤에만 `--build`를 붙인다고 README에 적는다, (나) `--build`를 두고 AC-02를 "리소스·데이터·인스턴스가 바뀌지 않는다"로 고친다, (다) 명령 앞에 `BUILDX_NO_DEFAULT_ATTESTATIONS=1`을 붙인다. 구현은 결정 1의 명령을 그대로 두었다.
3. **데모의 처리량 한도는 10 → 5 MiB/s다.** 처음의 32 → 16 MiB/s로 돌린 한 회에서 첫 측정이 21.64 MiB/s(68%)였다. S7 Q2의 "30 MiB/s 이상 NFS 쓰기의 서버 쪽 저하"(제한기 원인 아님)와 같고, FR-08도 아래쪽 판정을 10 MiB/s 쓰기로 한다. 그런데 e2e 안의 데모 한 회에서 10 MiB/s 한 번 측정(10 s)이 3.76 MiB/s(38%)였다(바로 앞 데모는 99%). 그래서 한도마다 6 s 쓰기(`--ramp_time=1`)를 3회 재고 **중앙값**이 90~101%이며 **어느 회도 101%를 넘지 않음**(한도는 천장)으로 판정한다. 출력에 회마다 값을 모두 보인다. 원인은 S7 Q2와 같은 서버 쪽 쓰기 멈춤으로 보지만 이번에 확인하지 못했다. 볼륨 50 GiB(스택은 최소 크기를 낮추지 않는다).
4. **데모의 Prometheus 판정은 `volume_uuid`로 고른다.** `creation_token`은 이전 데모의 같은 이름 볼륨이 쿼리 창(3분) 안에 남아 앞 실행의 값(24.5 MiB/s)을 보였다. 판정: `max_over_time(sum(rate(anf_volume_write_bytes_total{volume_uuid=…}[20s]))[3m:5s])`이 새 한도의 절반 이상이고 한도 계열이 새 한도와 같다(30 s 안). Prometheus와 대시보드 확인은 모두 nginx(8081)를 거친다.
5. **데모의 인터페이스.** 종료 코드 0·1·2, `--keep`, 그리고 `--clean`(이전 `--keep` 실행이 남긴 것만 지움)을 더했다. `--keep` 뒤에 지울 방법이 대본 전체 재실행뿐이면 AC-08("데모가 치운 뒤")을 맞추기 번거롭다. 시작할 때도 같은 정리를 한 번 해서 다시 돌릴 수 있다. 실패해도 정리는 한다(`--keep`이 아니면). 데모 전용 구독 `de300000-0000-4000-8000-000000000013`, 계정 `demo-acct`, 풀 `demo-pool`(Premium 4 TiB Manual), 볼륨 `vol-v3`·`vol-v41`·`vol-restored`, 클라이언트 `anf-demo-client-1`·`-2`.
6. **`init`은 저장소의 호스트 경로를 자기 `/repo` 바인드에서 얻는다.** `network_mode: none`이라 hostname이 컨테이너 ID이고, `docker inspect`로 `/repo`의 원본(compose가 `..`를 절대 경로로 바꾼 값)을 읽어 `nsenter -t 1 -a -- bash <경로>/scripts/setup-wsl-dataplane.sh`를 돌린다. 이미지는 agent 이미지(`pull_policy: never`)를 같이 쓴다.
7. **재시작 정책이 없다.** WSL 재시작 뒤에는 같은 명령을 다시 돌린다. 정책으로 agent만 먼저 다시 뜨면 `init`이 `ns` rshared 바인드를 만들기 전이라 P1 오류로 떠지지 않는다.
8. **healthcheck.** agent는 `/api/storage/volumes`(시작 복구가 끝나야 HTTP가 열린다, `start_period` 300 s), anf-api는 `/metrics`, Prometheus는 `/-/ready`, 대시보드는 `/`. 모두 `start_interval` 1 s.
9. **실행기와 e2e.** 실행기의 포트 점검·남은 것 검사에 8081(대시보드)을 더하고, 포트가 차 있으면 스택을 내리라는 안내를 붙였다. e2e는 compose 프로젝트 이름을 `anf-clone-e2e`로 따로 둔다: 사용자 스택(`anf-clone`)의 이름 있는 볼륨(anf-api 상태)을 `down -v`가 지우지 않게 한다. e2e의 마지막 시험은 `down -v` 전에 `demo.py --clean`을 먼저 한다. 한 번은 앞 시험이 실패해 리소스가 남은 채 `down -v`가 anf-api 상태를 지워, LV·인스턴스가 기록 없이 남았다(agent API로 손으로 지웠다). README에도 "`down -v`는 리소스가 없을 때만"을 적었다.
10. **`.gitattributes`.** `deploy/**`, `.dockerignore`, `scripts/demo.py`를 LF로 고정했다(`.dockerignore` 패턴 끝의 `\r`은 아무 파일과도 맞지 않는다).
