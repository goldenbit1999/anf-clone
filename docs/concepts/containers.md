# 컨테이너 (FR-13: compose 스택과 데모 스크립트)

> FR-13은 클론 전체(anf-api, storage agent, Prometheus, 대시보드)를 `deploy/compose.yaml` 하나로 묶었다. docker 그룹 사용자가 sudo 없이 명령 하나 `docker compose -f deploy/compose.yaml up -d --build --wait`로 전체를 띄운다. PRD §5의 데모 대본 7단계는 `scripts/demo.py` 하나로 재현한다. 이 문서의 핵심은 넷이다. (1) storage agent는 호스트의 커널, LVM, 마운트, Docker를 직접 다루는 프로세스다. 그래서 컨테이너에 넣으려면 특권과 호스트 자원 공유 설정 열 가지, 그리고 새 기기를 위한 바인드 옵션 하나가 필요했다. 그중 여섯은 빠질 때의 실패를 스파이크 S9, 구현, 검증에서 실제로 봤다. 특권 컨테이너는 격리가 아니라 포장이다. (2) 그중 가장 까다로운 것은 마운트 전파(mount propagation)다. agent가 자기 마운트 네임스페이스에서 한 마운트가 호스트를 거쳐 볼륨 인스턴스까지 가야 한다. 재귀 바인드는 agent가 다시 뜰 때 숨은 private 복사본을 만들어 되돌리기를 깨뜨렸다. (3) 볼륨 인스턴스는 agent가 Docker 소켓으로 띄운, compose 밖의 형제 컨테이너다. 그래서 `down`을 해도 클라이언트 I/O가 계속되고, 다시 `up`하면 agent가 이어받는다. (4) 데모 스크립트는 단계마다 클라이언트에서 본 근거를 한 줄씩 출력하고 스스로 치운다. 처리량 단계는 "한도가 천장인가"와 "한도를 바꾸면 따라 바뀌는가"만 판정한다. 한도에 얼마나 가까운지는 FR-08 시험의 몫이다. 이 판정은 검증 1회차의 실패와 2회차의 지적에서 나왔다(3.8). 실환경 검증 결과는 5절에 있다.

코드 인용 기준: 커밋 `8732c9b` (제품 코드 내용 해시 `7c38d8c7…`). FR-13은 `backend/`(테스트 제외)와 `pyproject.toml`을 바꾸지 않아 이 해시는 FR-12 때와 같다. 검증 1회차의 대상은 `01ab88e`, 2회차의 대상은 `4887031`이다. 1회차 뒤 `scripts/demo.py`(6단계 판정), `deploy/compose.yaml`(`create_host_path`), 단위 테스트 `test_demo.py`·`test_compose.py`, e2e `test_compose_stack_live.py`가 바뀌었다. 2회차 뒤에는 `814afb1`이 `scripts/demo.py`의 `follows_limit`과 `test_demo.py`를, `8732c9b`가 설계 §7-3을 바꿨다. `814afb1`의 변경은 실환경에서 다시 돌리지 않았다(5절). 이 문서의 줄 번호는 모두 `8732c9b` 기준이다. FR-13의 변경은 `deploy/`·`scripts/`에 있어서, 그것까지 넣은 참고 해시(pyproject, backend(테스트 제외), deploy, scripts, `.dockerignore`, `.gitattributes`)를 진행 기록에 따로 남긴다. `01ab88e`에서 `c32b76d8…`, `4887031`에서 `64530317…`이었고(2회차 보고서), `814afb1` 뒤의 값은 이 문서의 입력에 없다.

FR-13은 ANF 기능이 아니라 엔지니어링 장치다. PRD §8에서 FR-13은 조사(1단계)를 생략하는 FR이라 조사 브리프가 없고, 아래 1, 2절은 "해당 없음"이다. 사실의 근거는 스파이크 S9(`_workspace/spikes/S9.md`), 설계(`_workspace/containers/02_main_design.md`, 결정 1~14와 §7 구현 중 변경), 진행 기록(`_workspace/containers/00_progress.md`), 검증 보고서(`_workspace/containers/04_verifier_report.md` 1회차, `04_verifier_report_r2.md` 2회차), ADR §4·§5, 그리고 실제 코드다. S9가 관찰이 아니라 추론으로 적은 것은 [추론]으로 남겼다. 같은 종류의 앞 문서는 `docs/concepts/test-automation.md`와 `docs/concepts/ci.md`다.

---

## 1. ANF에서는

해당 없음. 컨테이너 배치는 ANF의 기능이 아니다. 다만 지원하는 직무가 컨테이너, Kubernetes, CI/CD를 강조하므로, 이 결과물은 "커널 수준의 데이터 플레인을 가진 시스템을 컨테이너로 묶을 때 무엇이 필요하고 무엇이 깨지는지를 실측으로 안다"는 것을 보여 준다. PRD FR-13의 수락 기준은 "문서에 적힌 명령 하나로 전체를 띄울 수 있다"이고, PRD §9의 성공 기준 하나가 "§5의 데모 대본을 스크립트 하나로 처음부터 끝까지 재현할 수 있다"이다.

## 2. ONTAP에서는

해당 없음.

면접에서 조심할 것 하나. S9는 "`down`을 해도 데이터 서비스가 이어진다"를 두고 "ONTAP에서 관리 프로세스를 멈춰도 데이터 경로가 서는 것과 비슷하다"고 적었지만 [추론]으로 표시했다. 조사 브리프에서 온 사실이 아니므로, ONTAP의 실제 동작으로 말하지 말고 "이 클론은 컨트롤 경로와 데이터 경로를 나눠 그렇게 만들었다"까지만 말한다 (3.6).

## 3. 이 프로젝트에서는

### 3.1 구조

```
compose 안 (프로젝트 anf-clone)                         compose 밖 (agent가 만들거나 init이 만든 것)
─────────────────────────────────                       ──────────────────────────────────────────
init           한 번 돌고 끝남. 특권, pid host,        → anf-vnet 네트워크, 이미지 anf-nfs-server·client,
               네트워크 없음                              nfsd·dm_thin_pool 모듈, fs.leases-enable=0,
                                                          호스트 /var/lib/anf-clone/ns의 rshared 바인드
storage-agent  특권, host 네트워크·pid·ipc,            → 볼륨 인스턴스 anf-nfs-<uuid> (docker.sock으로 띄움)
               127.0.0.1:8090                           → 호스트 마운트 ns/<token>, .snapshot/<이름> (전파)
                                                        → VG anf, loop 장치, thin LV
anf-api        uid 1000, host 네트워크, 127.0.0.1:8080
               SQLite는 이름 있는 볼륨 anf-api-data
prometheus     host 네트워크, 127.0.0.1:9090
               이름 있는 볼륨 prometheus-data
dashboard      nginx, host 네트워크, 127.0.0.1:8081
               /subscriptions → 8080, /prometheus/ → 9090

Windows 브라우저 ─ WSL localhost 전달 ─> 127.0.0.1:8081 (dashboard)
anf-api ─ ONTAP 모양 REST ─> 127.0.0.1:8090 (storage-agent) ─ LVM·mount·docker·nsenter     ← 컨트롤 경로
NFS 클라이언트 컨테이너 ─ anf-vnet ─> anf-nfs-<uuid>:/<creationToken> ─ /export ─ ext4 ─ thin LV  ← 데이터 경로
```

데이터 경로에는 compose가 관리하는 컨테이너가 하나도 없다. 이것이 3.6의 "`down` 뒤에도 I/O가 계속된다"의 이유다.

### 3.2 명령 하나가 하는 일 (`deploy/compose.yaml`)

README의 빠른 시작(`README.md:17-24`)이 적는 명령은 하나다.

```bash
docker compose -f deploy/compose.yaml up -d --build --wait
```

1. **빌드 (`--build`).** `build:`가 있는 세 서비스의 이미지(`anf-clone-agent`, `anf-clone-api`, `anf-clone-dashboard`)를 만든다. 컨텍스트는 compose 파일 기준 `..`, 즉 저장소 루트이고(`compose.yaml:33-35`, `:72-74`, `:103-105`), 들어가는 파일은 루트의 `.dockerignore`가 정한다 (3.7). Prometheus는 공개 이미지 `prom/prometheus:v3.15.1`을 그대로 쓴다(`:87`). 프로젝트 이름은 `name: anf-clone`(`:10`)이다.
2. **`init`이 호스트를 준비하고 끝난다 (`compose.yaml:14-23`, `deploy/init.sh`).**
   - 설정: `privileged`, `pid: host`, `network_mode: none`, 저장소를 `/repo`에 읽기 전용으로, Docker 소켓(`:17-22`). 이미지는 agent 이미지를 같이 쓰고(`image: anf-clone-agent:latest`, `pull_policy: never`, `:15-16`), 명령은 `bash /repo/deploy/init.sh`(`:23`)다. agent 이미지에 `nsenter`와 docker CLI가 이미 있기 때문이다(설계 §7-6).
   - `init.sh:14-16`: 자기 저장소 바인드의 **호스트 경로**를 찾는다. 네트워크가 없어서 hostname이 컨테이너 ID이고, `docker inspect`로 자기 자신의 `/repo` 바인드 원본(compose가 상대 경로 `..`를 절대 경로로 바꿔 둔 값)을 읽는다. 즉 `/repo` 바인드의 쓸모는 파일을 읽는 것보다 "저장소가 호스트의 어디에 있는가"를 알아내는 데 있다.
   - `init.sh:18` `host()`: `nsenter -t 1 -a`. 호스트 PID 1(systemd)의 모든 네임스페이스(마운트, 네트워크, pid, 사용자 등)로 들어가 호스트 root로 명령을 돈다. `pid: host`가 있어야 PID 1이 호스트의 PID 1이다.
   - `init.sh:20`: 그 경로의 `scripts/setup-wsl-dataplane.sh`를 호스트에서 **그대로** 돈다(모듈, sysctl과 `/etc/sysctl.d` 파일, NFS 이미지 둘, `anf-vnet`). 준비 로직을 compose 쪽에 한 벌 더 두지 않으려는 것이다(결정 2). 같은 스크립트를 테스트 실행기의 안내와 CI data-plane 작업도 쓴다. 스크립트는 자기 위치에서 저장소 경로를 계산하므로(`setup-wsl-dataplane.sh:8`) 호스트 경로로 불러야 이미지 빌드 경로가 맞는다.
   - `init.sh:22-28`: 호스트의 `ns`를 rshared 바인드로 만든다. 마운트 지점이 아니면 바인드하고 private로 떼어 낸 뒤 rshared, 이미 마운트 지점이면 rshared만 다시 한다. 왜 필요한지와 왜 이 순서인지는 3.4에 있다.
3. **서비스 넷이 뜬다.** `storage-agent`만 `depends_on: init: condition: service_completed_successfully`(`compose.yaml:36-38`)로 init의 성공 종료를 기다린다. Docker는 호스트의 `ns`가 공유 마운트가 아니면 agent 컨테이너의 rshared 바인드를 아예 거절하기 때문이다(S9 P1). 다만 기다리는 것은 **시작**이다. compose는 init을 돌리기 전에 컨테이너를 모두 **만든다**(설계 §7-11). 그래서 agent의 두 긴 문법 바인드는 원본 경로가 아직 없어도 만들어지도록 `create_host_path: true`를 가진다 (3.3). anf-api, Prometheus, 대시보드는 순서 없이 바로 뜬다. anf-api가 agent보다 먼저 떠도 된다. S9 R5에서 anf-api만 떠 있는 동안 받은 볼륨 PUT이, 20 s 뒤 agent가 뜨자 준비 3.2 s 뒤 `Succeeded`였다(storage client의 60 s 연결 재시도 안).
4. **`--wait`가 healthy를 기다린다.** 서비스마다 이미지에 이미 있는 도구로 healthcheck를 둔다(agent·anf-api 이미지에는 curl·wget이 없다, S9 Q5).

   | 서비스 | 검사 (`compose.yaml`) | `start_period` | 이유 |
   | --- | --- | --- | --- |
   | storage-agent | venv의 Python `urllib`로 `GET /api/storage/volumes` (`:62-68`) | 300 s | agent의 HTTP는 lifespan의 `check_host()`와 `recover()`가 끝난 뒤에 열린다(`backend/storage_agent/agent_app.py:153-155` `lifespan`). 그래서 이 검사가 통과하면 시작 복구도 끝난 것이다. 인스턴스가 NFSv4 유예 기간(grace)을 기다리면 2분이 넘을 수 있다(`:61` 주석) |
   | anf-api | Python `urllib`로 `GET /metrics` (`:78-84`) | 60 s | |
   | prometheus | `wget /-/ready` (`:93-99`) | 60 s | |
   | dashboard | `wget /` (`:107-113`) | 60 s | |

   모두 `start_interval: 1s`라 준비 직후 곧 healthy가 된다(설계 §7-8). 그래서 명령이 0으로 돌아오면 "쓸 수 있는 상태"다. e2e는 네 서비스가 `running`·`healthy`이고 `init`이 `exited`·0인지 본다(`backend/tests/e2e/test_compose_stack_live.py:199-209` `test_one_command_starts_the_stack_as_a_regular_user`).
5. **걸린 시간.** 일반 사용자의 첫 빌드 포함 62 s, 그 뒤 약 10 s(진행 기록). 검증 1회차에서는 WSL을 다시 시작한 직후 이미지가 있는 채로 세 번 8.8~10.4 s였다(셋째는 VM까지 다시 부팅한 직후). 다시 실행이 왜 몇 초가 걸리는지(서비스 재생성)는 3.7 끝에 있다.

**왜 모두 host 네트워크에 localhost 바인딩인가.**
- localhost가 이 클론의 보안 경계다. anf-api는 인증을 하지 않는다(D-13. 실제 Azure에서는 ARM이 요청이 ANF 리소스 공급자에 닿기 전에 토큰과 RBAC를 본다). 그래서 어떤 서비스도 바깥 인터페이스에 열면 안 된다(ADR §5 "바인딩", NFR-07).
- 서비스들이 이미 서로를 127.0.0.1로 찾는다. host 네트워크면 anf-api가 기본 `ANF_STORAGE_AGENT_URL`(`http://127.0.0.1:8090`)로 agent에 닿고, Prometheus는 FR-12의 설정 파일(`deploy/prometheus/prometheus.yml`, 대상 `127.0.0.1:8080`·`:8090`)을 그대로 쓰며(결정 11), nginx도 127.0.0.1로 넘긴다. S9 Q3에서 같은 anf-api 컨테이너가 agent 컨테이너에도, 호스트 프로세스 agent에도 기본 URL로 닿았다.
- Windows 브라우저는 WSL의 localhost 전달로 `http://127.0.0.1:8081`에 닿는다(`README.md:34`).
- 단위 테스트가 이것을 지킨다: `ports:`를 가진 서비스가 없고, init 말고는 모두 host 네트워크이며, 서버마다 127.0.0.1에만 바인딩한다(`backend/tests/unit/test_compose.py:169-177` `test_services_listen_on_localhost_only`). e2e는 실제로 `ss`의 로컬 주소가 `127.0.0.1:<포트>` 하나뿐인지 본다(`test_compose_stack_live.py:208-209`).
- 예외는 NFS다. 볼륨 인스턴스는 `anf-vnet`(172.30.0.0/24)의 자기 IP에서 받는다. 그 IP가 볼륨의 마운트 대상 IP이고, 처리량 한도도 인스턴스 netns마다 건다 (ADR §5, D-12).

### 3.3 storage agent를 컨테이너로 돌리는 데 필요한 것

storage agent는 root로 loop 장치, LVM·dm-thin, ext4 마운트와 마운트 전파, `nsenter`, tc, iptables, Docker API를 쓰는 호스트 프로세스다. S9는 그것을 컨테이너 안에서 돌려, 설정이 하나씩 빠질 때 무엇이 깨지는지 실측했다. compose 파일의 agent 서비스(`compose.yaml:31-68`)는 그 결과이고, 머리 주석(`:25-30`)이 S9의 번호를 단다. 마지막 행 `create_host_path`만 S9가 아니라 검증 1회차에서 나왔다.

| 설정 (`compose.yaml`) | 주는 것 | 빠지면 (관찰) | 근거 |
| --- | --- | --- | --- |
| `privileged: true` (`:39`) | 호스트 root와 같은 권한. 아래 설정들이 이 위에서 동작한다 | S9는 이것만 뺀 경우를 시험하지 않았다 | 결정 3 |
| `network_mode: host` (`:40`) | 127.0.0.1:8090에 열고 anf-api·Prometheus가 기본 주소로 닿는다 | 시험하지 않았다(S9는 처음부터 host) | S9 Q3 |
| `pid: host` (`:41`) | Docker가 알려 주는 인스턴스 pid(`nfs_instance.py:238-241` `_pid`, `docker inspect {{.State.Pid}}`)는 **호스트 pid**다. 그 pid로 인스턴스 netns에 들어가 tc 한도(`nfs_instance.py:132-133` `limit` 안의 `netns`)와 되돌리기 창의 iptables(`:233-236` `_iptables`)를 걸고, 메트릭이 `/proc/<pid>/net/rpc/nfsd`를 읽는다(`backend/storage_agent/volume_metrics.py:140`) | 시작 복구 실패: `nsenter -t 6623 -n ip link add ifb0 type ifb exited 1: nsenter: cannot open /proc/6623/ns/net: No such file or directory` | S9 P4 |
| `/var/lib/anf-clone`을 **같은 경로**로, `bind: recursive: disabled` (`:44-48`) | `aggr0.img`와 export 파일 디렉터리. 같은 경로여야 하는 이유: agent가 `docker run --mount src=/var/lib/anf-clone/ns,…`에 넘기는 경로(`nfs_instance.py:161-166` `start`)를 dockerd가 **호스트**에서 읽는다 | 재귀 바인드: agent가 볼륨이 있는 채 다시 뜨면 되돌리기가 `Failed`, 호스트 디렉터리에 `.snapshot`이 생겨 볼륨 DELETE가 `Directory not empty`로 실패 | S9 P3, 3.4 |
| `ns`를 `bind: propagation: rshared` (`:50-54`) + init의 호스트 준비 | agent 컨테이너 안에서 한 볼륨·스냅샷 마운트가 호스트와 볼륨 인스턴스로 간다 | 호스트 준비가 없으면 Docker가 거절: `path /var/lib/anf-clone/ns is mounted on / but it is not a shared mount`. rshared 없이 띄우면 agent는 뜨지만 첫 볼륨 POST가 0.64 s 만에 실패(인스턴스 `docker run` exit 125, `not a shared or slave mount`) | S9 P1, 3.4 |
| `/run/lock/lvm` 공유 (`:56`) | 호스트 udev의 VG 자동 활성화와 같은 잠금으로 줄을 선다 | agent가 시작하지 못했다: `vgchange -ay anf exited 5: Activation of logical volume anf/aggr0 is prohibited while logical volume anf/aggr0_tmeta is active.` | S9 P2, 3.5 |
| `/run/udev:ro` + `ipc: host` (`:57`, `:42`) | LVM이 호스트 프로세스처럼 호스트 udev의 처리를 기다린다 | `/run/udev`만: `lvcreate`가 4분 23초 멈추고 SIGKILL로만 끝남. 둘 다 없음: 기다리지 않아서 `lvcreate` 직후의 mount가 `special device … does not exist`로 실패할 때가 있다(드묾) | S9 L2~L4, 설계 §7-1, 3.5 |
| `/dev` (`:58`) | 새 loop 장치와 dm 노드(`/dev/mapper/anf-*`, `/dev/anf/*`)는 호스트 udev가 호스트 `/dev`에 만든다 | 시험하지 않았다. 컨테이너의 기본 `/dev`는 시작 때의 복사라 새 노드가 보이지 않을 것이다 [추론] | S9 P5 |
| `/lib/modules:ro` (`:59`) | `check_host`의 `modprobe ifb numifbs=0` (`nfs_instance.py:97`) | 시험하지 않았다 | S9 "기능" 표의 시작 항목(붙인 채로 통과) |
| `/var/run/docker.sock` (`:60`) | 형제 컨테이너인 볼륨 인스턴스를 띄우고 다룬다(`docker run/start/exec/inspect/stop/rm`, `nfs_instance.py`). 메트릭은 같은 소켓의 Docker API로 pid를 읽는다(`volume_metrics.py:33`, `:68` `docker_pid`) | 시험하지 않았다. 코드상 `check_host`의 첫 검사 `docker info`가 실패해 agent가 뜨지 않는다(`nfs_instance.py:77-78`) [추론] | |
| 두 긴 문법 바인드에 `bind: create_host_path: true` (`:49`, `:55`) | 원본 경로가 아직 없어도 컨테이너를 만들 수 있다. compose는 init을 돌리기 전에 컨테이너를 모두 만든다 | `/var/lib/anf-clone`이 없는 새 기기에서 만들기가 거절된다: `bind source path does not exist`. 같은 모양의 다른 경로로 재현했다(아래) | 설계 §7-11, 검증 1회차 판정 밖 관찰 1 |

**`create_host_path` (설계 §7-11, 커밋 `8c02910`).**
- 무엇이 문제였나: compose는 init을 **시작**하기 전에 서비스 컨테이너를 모두 **만든다**. 긴 문법(`type: bind`) 바인드는 원본이 없으면 만들기 단계에서 거절된다. 짧은 문법 바인드는 이 옵션이 기본으로 켜져 있다(`docker compose config`로 확인). agent의 두 바인드는 `recursive: disabled`와 `propagation: rshared`를 가진 긴 문법이다(`compose.yaml:44-55`). 그래서 `/var/lib/anf-clone`이 아직 없는 새 기기에서는 README의 명령이 실패한다.
- 왜 늦게 드러났나: 이 기기에는 앞선 기능 작업 때부터 `/var/lib/anf-clone`이 있었다. 준비 스크립트는 이 디렉터리를 만들지 않는다(검증 보고서 관찰 1). verifier는 같은 구조의 장난감 compose 프로젝트로 먼저 확인했다. 그대로 두면 `bind source path does not exist`, rc 1이었고, `create_host_path: true`를 더하면 rc 0이었다.
- 고친 것의 확인(implementer): 실제 `/var/lib/anf-clone`은 지울 수 없어서, 이 compose 파일(HEAD와 수정본)에서 두 바인드의 원본만 같은 루트 ext4(`/dev/sdd`)의 `/var/tmp/fr13-fresh`로 바꿨다. init은 `init.sh`의 `NS`만 바꿔 그대로 돌렸고, agent는 서버 대신 탐침(컨테이너 안 `ns`의 전파 상태, `ns` 아래 tmpfs 마운트)을 돌렸다. compose는 일반 사용자로 돌렸다.
  - HEAD: 만들기 rc 1, `bind source path does not exist: /var/tmp/fr13-fresh` (재현).
  - 수정본, 경로 없음: 만들기 rc 0이었고, 이때 docker는 아무것도 만들지 않았다. `up` rc 0. 경로를 만든 것은 init의 `mkdir -p`(`init.sh:22`)였고, init이 `ns`를 `shared`로 만들었다. agent 컨테이너의 탐침이 본 `ns`도 `shared`였고, 탐침이 `ns` 아래에 건 마운트가 호스트에 보였다(P1의 사슬이 그대로 선다).
  - 수정본, 빈 `ns`가 먼저 있음: 같은 결과. init은 마운트 지점이 아니면 바인드하고 rshared로 만든다(`init.sh:23-27`).
- 돌리지 않은 것: 실제 경로를 지운 새 기기, 그리고 agent 서버가 aggregate를 처음 만드는 경로(`ensure_aggregate`: `ns` mkdir, 희소 파일, `vgcreate`). 단위 테스트가 두 바인드의 옵션을 지킨다(`test_compose.py:125-131` `test_agent_long_binds_create_a_missing_host_path`).

**이미지 쪽 조건.** agent 이미지는 호스트와 같은 `ubuntu:24.04`다(`deploy/agent/Dockerfile:9`). 그래서 컨테이너 안의 LVM(2.03.16)과 iptables(1.8.10 nf_tables)가 호스트와 같다(Dockerfile 머리 주석 `:2-3`, S9 환경). 컨테이너의 docker CLI(29.1.3)도 WSL 데몬과 같은 버전이다.

**agent 코드는 바뀌지 않았다.** 위 설정은 "컨테이너 안을 호스트 프로세스가 보던 세상과 같게" 만드는 일이다. 같은 경로, 같은 pid 공간, 같은 잠금, 같은 udev 동기화. 그래서 FR-13은 제품 코드(`backend/`)를 고치지 않았고 내용 해시가 그대로다. S9 R6에서 호스트 프로세스 agent와 agent 컨테이너를 번갈아 써도 같은 anf-api 컨테이너와 동작했다.

#### 특권 컨테이너는 격리가 아니라 포장이다

- agent 컨테이너는 `privileged`, host 네트워크·pid·ipc, 호스트 `/dev`, Docker 소켓을 가진다. 이것은 호스트 root와 같은 권한이다. 컨테이너가 주는 것은 격리가 아니라 포장이다. 버전이 고정된 이미지(호스트와 같은 LVM·iptables, `pyproject.toml`의 의존성), 다른 서비스와 같은 수명 주기(같은 명령으로 올리고 내림), healthcheck, 그리고 사용자가 sudo를 칠 필요가 없다는 것.
- **docker 그룹은 root와 같은 권한이다.** "sudo 없이"는 "root 권한 없이"가 아니다. S9 Q5에서 docker 그룹 사용자 `mkimhome1`이 sudo 없이 특권 컨테이너로 호스트 디렉터리의 rshared 바인드(`--pid host` + `nsenter -t 1 -m`), 전역 sysctl `fs.leases-enable=0`, `modprobe nfsd`·`dm_thin_pool`(`/lib/modules` 바인드)을 했다. init 서비스가 바로 그 방법이다. 설계 결정 3은 이것을 숨기지 말고 문서에 적으라고 했다.
- 남은 보호 장치는 다른 곳에 있다. 모든 서비스가 127.0.0.1에만 바인딩하고(3.2), agent는 커널 명령을 셸 없이 인자 목록으로 실행하며, 스토리지 루트 아래의 경로만 받는다(ADR §5). 특권은 init과 agent만 가진다. anf-api는 uid 1000으로 돈다 (3.7). 검증 1회차에서 본 프로세스 권한: anf-api uid 1000·특권 없음, Prometheus uid 65534(nobody), agent uid 0·특권. 대시보드 nginx의 master 프로세스는 이미지(`nginx:1.28.0-alpine`) 기본대로 uid 0이지만 특권은 없고 127.0.0.1에만 연다(판정 밖 관찰 2).

### 3.4 마운트 전파가 컨테이너 경계를 넘는 방식

**개념 요약.** 리눅스 마운트의 전파 유형은 그 아래에서 일어난 마운트·언마운트가 다른 마운트 네임스페이스로 퍼지는지를 정한다. private는 주고받지 않는다. shared는 같은 peer group끼리 서로 복제한다. slave는 master에서 받기만 한다. 앞의 r(recursive)은 아래 마운트 전체에 같은 유형을 준다. 자세한 설명과 mountinfo 예는 `docs/concepts/ci.md` §3.8에 있다.

**FR-13 전 (호스트 프로세스 agent).** 마운트 네임스페이스가 둘이었다. agent는 호스트 네임스페이스에서 `ns`를 자기 자신에 바인드해 rshared로 만들고(`nfs_instance.py:101-112` `ensure_shared_ns`), 볼륨 인스턴스는 `ns`를 `/export`로 `bind-propagation=rslave` 바인드한다(`nfs_instance.py:163` `start`). 그래서 인스턴스가 뜬 뒤 호스트에서 하는 마운트(새 스냅샷 등)도 인스턴스 안에 보인다.

**FR-13 뒤 (agent 컨테이너).** 셋이 됐다. agent가 마운트하는 곳이 agent 컨테이너의 네임스페이스라, 그 마운트가 두 번 건너가야 한다.

```
agent 컨테이너                 호스트                           볼륨 인스턴스 anf-nfs-<uuid>
ns  (rshared 바인드) ⇄ peer ⇄ ns (init이 만든 rshared 바인드) ─ master → slave ─> /export (rslave)
 mount ext4 → ns/<token>  ──────> ns/<token>  ──────────────────────────────────> /export/<token>
 mount ro,noload → ns/<token>/.snapshot/<이름>  ───> 같은 경로 ───────────────────> 같은 경로
```

- S9에서 관찰한 대로 컨테이너 안의 ext4·스냅샷 마운트가 호스트와 인스턴스로 갔고, 호스트 `findmnt`에서 모두 `shared`였다. 언마운트도 전파됐다(삭제 뒤 호스트에서 사라짐). agent 컨테이너를 `docker kill`해도 호스트에 전파된 마운트는 남았다(S9 R1).
- 이 사슬에는 조건이 셋 있다. (가) 호스트의 `ns`가 agent 컨테이너가 **만들어지기 전에** 공유 마운트여야 한다. (나) agent 컨테이너의 `ns` 바인드가 rshared여야 한다. (다) 인스턴스의 rslave 바인드는 그대로다. dockerd가 그 바인드를 호스트에서 만드는데, 호스트의 `ns`가 공유 마운트이므로 받아들여진다.

**(가)를 init이 하는 이유 (S9 P1).**
- 호스트 준비 없이 `ns:ns:rshared`로 띄우면 Docker가 컨테이너를 만들지 않는다: `path /var/lib/anf-clone/ns is mounted on / but it is not a shared mount`. WSL의 `/`는 private이기 때문이다.
- rshared 없이 띄우면 agent는 뜬다. 그러나 `ensure_shared_ns`가 **컨테이너 안에서만** 바인드한다(컨테이너에서는 `ns`가 shared, 호스트에서는 "not a mountpoint"). 그다음 인스턴스의 `docker run`을 dockerd가 호스트 경로로 처리하다 거절한다(exit 125, `… is mounted on / but it is not a shared or slave mount`). 볼륨 POST가 0.64 s 만에 실패했고, 인스턴스 컨테이너는 `Created`로 남았다.
- agent의 진입점이 `nsenter -t 1 -m`으로 호스트 `ns`를 먼저 바인드하는 방법은 안 된다. 컨테이너의 바인드는 시작할 때 정해지므로, 진입점이 돌기도 전에 첫 번째 오류로 컨테이너 생성이 실패한다(S9 "설계에 주는 선택지"). 그래서 별도의 한 번 도는 서비스가 먼저 끝나야 한다.

**init의 바인드 순서는 FR-11에서 배운 것이다.** `init.sh:23-27`은 마운트 지점이 아니면 bind → private → rshared 순서로 한다. FR-11의 CI 스파이크 S3가, `/`가 shared인 호스트(systemd 기본값, GitHub 러너)에서는 새 바인드가 `/`의 peer group에 들어가 ns 아래 마운트가 호스트 마운트 표에 두 번 나온다는 것을 찾았다. 그래서 `ensure_shared_ns`를 이 순서로 고쳤다(`docs/concepts/ci.md` §3.8, 커밋 `691d93f`). init은 같은 순서를 호스트 쪽에서 한다(`init.sh:8-10` 주석). init이 만든 바인드를 agent 컨테이너가 rshared로 받으면, 컨테이너 안의 `ensure_shared_ns`는 `findmnt`가 마운트 지점과 `shared` 한 줄을 돌려주므로 아무것도 하지 않는다(`nfs_instance.py:107-112`, S9: 비재귀 바인드에서는 한 줄 `shared`).

**재귀 바인드가 만든 숨은 private 복사본 (S9 P3).** 이 문서에서 장애 분석으로 가장 쓸 만한 이야기다.
- 처음 설정은 `-v /var/lib/anf-clone:/var/lib/anf-clone`이었다. 이 바인드는 재귀(recursive)라서 그 아래의 기존 마운트까지 컨테이너로 가져온다.
- agent 컨테이너가 **처음** 뜰 때는 `ns` 아래에 마운트가 없어 아무 일도 없었다. 볼륨이 있는 채 **다시** 뜨자 재귀 바인드가 호스트의 `ns`와 그 아래 볼륨·스냅샷 마운트를 private 복사본으로 가져왔고, 그 위에 rshared `ns` 바인드가 얹혔다. 컨테이너 mountinfo에 `ns`가 private·shared로 두 번, 볼륨 `s9a` 등이 각각 두 번 있었다. 왜 private로 오는지는 S9가 적지 않았다(Docker 바인드의 기본 전파가 rprivate라서로 보인다 [추론]).
- 이 상태에서 볼륨 A의 되돌리기가 `Failed`였다: `docker exec anf-nfs-… exportfs -ra exited 1: exportfs: Failed to stat /export/s9a/.snapshot/snapA: No such file or directory`.
- 원인: agent는 마운트 여부를 `findmnt -rn -o TARGET`이 돌려주는 경로 목록으로 판정한다(`backend/storage_agent/flexvol.py:632-633` `_mounted`). 되돌리기가 보이는 `s9a`를 내린 뒤에도 숨은 복사본이 같은 경로로 목록에 남아 "아직 마운트됨"으로 보였고, 새 LV를 마운트하지 않았다(`flexvol.py:642-648` `_ensure_mounted`가 경로가 있으면 건너뛴다). 그리고 지금 보이는 `ns/s9a`, 즉 호스트의 빈 디렉터리에 `.snapshot`을 만들고 `chattr +i`를 걸었다(`flexvol.py:650-656` `_ensure_snapshot_dir`). 나중에 볼륨 DELETE가 `OSError: [Errno 39] Directory not empty: '/var/lib/anf-clone/ns/s9a'`로 실패해 손으로 `chattr -i` 후 지워야 했다.
- 숨은 복사본은 LV도 잡고 있을 것이다 [추론: `lvremove`의 "in use"는 보지 않았다. 되돌리기가 먼저 실패했다].
- 덤으로 `ensure_shared_ns`의 판정도 흔들렸다. 재귀 바인드에서는 `findmnt -no PROPAGATION`이 `private`·`shared` 두 줄을 돌려줘 `split(",")` 판정이 "shared 아님"으로 읽고 `--make-rshared`를 다시 했다(위쪽 마운트라 해는 없었다).
- 고친 방법: `/var/lib/anf-clone`은 `bind-recursive=disabled`로 그 디렉터리만 가져오고, `ns`는 따로 rshared로 바인드한다(`compose.yaml:44-55`). 다시 띄우자 `ns` 하나(shared)만 보였고, 시작 복구가 끝나지 않은 되돌리기를 끝냈다(3.0 s). 그 뒤 되돌리기 3.1 s, 삭제 2.1 s 모두 `Succeeded`였다.
- 이 결함은 agent가 **다시 뜰 때마다** 생긴다(업데이트, `down`/`up`). 그리고 3.7의 `--build` 때문에 같은 명령을 다시 돌릴 때마다 agent 컨테이너가 다시 만들어진다. 그래서 단위 테스트가 `recursive: disabled`를 지키고(`test_compose.py:108-112` `test_agent_binds_state_dir_without_recursion`), e2e가 agent를 죽였다 살린 뒤 되돌리기와 삭제를 해 본다(`test_compose_stack_live.py:279-321` `test_agent_kill_during_writes_keeps_volumes_and_revert_and_delete_work`, AC-06).

### 3.5 컨테이너 안의 LVM과 호스트 udev

컨테이너 안의 LVM은 두 가지를 호스트와 나눠야 했다. 잠금과 udev 동기화다.

**잠금 (S9 P2).** agent가 시작할 때 loop 장치를 붙이면(`flexvol.py:177-181` `ensure_aggregate`) 호스트 udev 규칙(`69-lvm.rules`)이 VG 자동 활성화(`lvm-activate-anf.service`, `vgchange -aay --autoactivation event anf`)를 돌린다. agent도 바로 `vgchange -ay anf`를 한다(`:186`). 호스트 프로세스 agent는 같은 `/run/lock/lvm`으로 줄을 서지만, 컨테이너는 자기 `/run`의 잠금을 써서 둘이 동시에 활성화했고 agent가 시작하지 못했다(3.3 표의 오류). `/run/lock/lvm`을 공유하자 같은 자동 활성화가 일어나도 agent가 2.5 s에 떴다.

**udev 동기화.** S9는 `lvcreate -V 1G -T anf/aggr0`을 네 조건에서 쟀다.

| # | 조건 | `lvcreate` | 비고 |
| --- | --- | --- | --- |
| L1 | 호스트 | 0.33 s | 호스트 archive 파일 17,548개로 매번 pruning 경고 |
| L2 | 컨테이너, `/run/udev` 없음 (S9가 고름) | 0.13 s | `/dev/anf/<lv>` 링크는 호스트 udev가 만든다 |
| L3 | 컨테이너, `/run/udev:ro`만 | **4분 23초 멈춤**, SIGKILL로만 끝남(rc 137) | `do_semtimedop`에서 기다렸다. udev 쿠키 세마포어가 컨테이너 IPC 네임스페이스에 있어 호스트 udev가 풀어 주지 못한다. `timeout 40`의 SIGTERM도 듣지 않았다. 그동안 VG 잠금을 쥐어 agent `/metrics`의 `lvs`가 약 45개 쌓였다. LV 자체는 만들어졌다 |
| L4 | 컨테이너, `/run/udev:ro` + `ipc: host` | 0.19 s | 정상 |

S9는 가장 빠른 L2를 골랐다. 그러나 구현 중 데모를 처음 돌렸을 때 5단계(새 볼륨 복원)가 실패했다: `mount -t ext4 -o ro,noload /dev/anf/snap_… exited 32: special device /dev/anf/snap_… does not exist` (설계 §7-1).
- 원인: L2의 컨테이너 LVM은 udev와 맞추지 않는다. 그래서 `lvcreate`가 호스트 udev가 장치 노드를 만들기 전에 돌아오고, 바로 뒤의 mount가 경합에서 질 때가 있다. 호스트 프로세스 agent에서는 LVM이 udev 쿠키를 기다려서 이 경합이 없었다.
- 고친 방법: L4. LVM이 `/run/udev`로 호스트 udev를 보고, 쿠키 세마포어가 호스트 IPC 네임스페이스에 있어서 호스트 udev가 풀어 준다. 즉 호스트 프로세스와 같게 기다린다(`compose.yaml:29-30` 주석, `:42`, `:57`).
- 단위 테스트가 둘을 **함께** 요구한다(`test_compose.py:140-147` `test_agent_waits_for_host_udev_like_a_host_process`). `/run/udev`만 남으면 L3처럼 멈추기 때문이다.
- 경합은 드물다. 같은 순서를 흉내 낸 15회 탐침은 L2·L4 모두 0회 실패였다. L4로 바꾼 뒤 데모 6회 모두 5단계가 통과했다. 즉 "고쳤다"의 근거는 원인 설명과 6회 통과이고, 실패를 다시 만들어 낸 재현은 없다.

**LVM 메타데이터 백업 (결정 14).** 컨테이너의 `/etc/lvm/archive`·`backup`은 컨테이너 쓰기 층에 쌓이고 컨테이너와 함께 사라진다. 호스트의 백업은 갱신되지 않는다(S9). 설계 결정 14는 이것을 바인드하지 않고 한계로 적기로 했다. 버린 대안은 호스트의 `/etc/lvm`을 바인드하는 것이다. 그러면 호스트의 LVM 설정까지 컨테이너에 묶이고, 이 클론에는 그 백업으로 `vgcfgrestore`를 해서 복구하는 시나리오가 없다 (4절 한계).

### 3.6 `down`을 해도 볼륨 인스턴스와 클라이언트 I/O가 계속되는 구조

**두 경로.** 데이터 경로는 클라이언트 → `anf-vnet` → 인스턴스 netns의 knfsd → `/export`(호스트 `ns`의 rslave 바인드) → ext4 → thin LV다. 컨트롤 경로는 anf-api → agent → LVM·mount·Docker다. compose가 관리하는 컨테이너는 모두 컨트롤 경로에만 있다.

**`down`이 지우지 않는 것.**
- 볼륨 인스턴스 `anf-nfs-<uuid>`: agent가 Docker 소켓으로 띄운 형제 컨테이너라 compose 프로젝트 밖이다. 남긴다는 것은 결정 4다. `down`에서 인스턴스도 멈추려면 compose 밖의 정리 스크립트가 필요하고, "관리 계층이 내려가도 데이터는 계속된다"는 설명도 잃는다.
- `anf-vnet`: compose가 소유하지 않는 external 네트워크다. init의 준비 스크립트가 만든다(`setup-wsl-dataplane.sh:39-48`). compose가 소유하면 `down`이 인스턴스가 붙은 네트워크를 지우려다 실패한다(결정 5). 단위 테스트가 compose 파일에 `networks:`가 없음을 지킨다(`test_compose.py:180-182` `test_compose_does_not_own_the_volume_network`).
- 호스트 마운트: agent의 마운트가 전파돼 호스트 네임스페이스에 있다(3.4). VG와 loop 장치도 활성인 채다.
- anf-api 상태: 이름 있는 볼륨 `anf-api-data`(`compose.yaml:76-77`, `:115-116`). `down`은 지우지 않는다(결정 7).

**관찰.** S9(`docker run`으로 흉내 낸 내리기)에서 내린 동안 A에 32 MiB 쓰기 28.4 MB/s, B 읽기 md5 같음이었다. compose e2e(`test_compose_stack_live.py:240-276` `test_rerun_and_down_up_keep_volumes_and_client_io`)는 이렇게 본다.
1. 데모를 `--keep`으로 돌려 볼륨 셋을 남기고, 클라이언트 안에서 1 MiB `oflag=direct` 쓰기를 멈출 때까지 되풀이하는 `Writer`(`:121-136`)를 시작한다. 줄마다 `/proc/uptime`(단조 시계)과 `dd` 종료 코드를 남긴다.
2. 같은 명령을 다시 실행한다. 인스턴스의 ID·상태·시작 시각(`instances`, `:91-98`)이 그대로여야 한다.
3. `down`. 네 포트가 모두 닫히고 인스턴스는 그대로다.
4. 10 s 기다린 뒤 다시 `up`. API가 본 볼륨·스냅샷·한도·`fileSystemId`가 전과 같고(`arm_view`, `:106-118`), 인스턴스가 다시 뜨지 않았으며, `down`~`up` 창 안에 쓰기가 있었고 오류가 0이어야 한다(`:274-276`).

검증 1회차는 같은 순서를 손으로도 했다(`demo.py --keep`이 남긴 볼륨 셋, 클라이언트가 `/v41/continuity`에 1 MiB direct 쓰기를 되풀이하는 동안): 다시 실행 11.39 s(`prometheus`는 `Running`, 나머지 넷은 `Recreate`), `down` 0.89 s 뒤 네 포트가 닫히고 인스턴스 셋이 그대로 돌았다. 그동안 다른 클라이언트가 복원 볼륨에 파일을 쓰고 읽었다. 10 s 뒤 `up` 8.68 s. API의 볼륨·스냅샷 목록과 인스턴스에 차이가 없었고, 클라이언트 파일의 md5가 같았으며, 쓰기 170회 중 오류 0, 내린 동안 53회(11.1 s 창)였다.

**다시 `up`할 때의 복구.** agent의 시작 복구(`flexvol.py:188-215` `recover`)는 단계마다 실제 상태를 먼저 본다. loop가 붙어 있으면 그대로 쓰고(`:177-179`), `ns`가 이미 shared면 건너뛰고, 볼륨이 마운트돼 있으면 건너뛰며(`_ensure_mounted`), export 파일을 다시 쓰고 `exportfs -ra`를 하고, 인스턴스가 돌고 있으면 띄우지 않고(`nfs_instance.py:154-166` `start`), tc는 있는 것을 두고 rate만 맞춘다(`:121-152` `limit`). 그래서 이어받기가 "아무것도 바꾸지 않음"으로 끝난다.

**WSL을 다시 시작했을 때.** 인스턴스가 멈추고 호스트 마운트와 loop가 사라진다. README대로 같은 명령을 다시 돌린다(`README.md:24`). init이 다시 준비하고, agent가 VG를 붙이고 마운트를 되살리고, 멈춘 인스턴스를 `docker start`한다(`nfs_instance.py:158-159`). S9 R3(차가운 시작 흉내, `docker run` 구성)에서 agent 준비는 13.3 s였고, 인스턴스 둘이 `Up`, 볼륨·스냅샷 마운트와 tc가 다시 걸렸으며, 클라이언트의 오래된 마운트에서 파일 읽기가 0.5 s였다.

**재시작 정책이 없는 이유 (설계 §7-7).** 정책이 있으면 WSL 재시작 뒤 Docker가 agent만 먼저 다시 띄울 수 있다. 그때는 init이 `ns` rshared 바인드를 만들기 전이라 P1 오류로 컨테이너가 만들어지지 않는다.

**`down -v`는 조심해야 한다.** `-v`는 이름 있는 볼륨, 즉 anf-api의 상태까지 지운다. 리소스가 남은 채 지우면 LV와 인스턴스가 기록 없이 남는다. 구현 중 e2e에서 실제로 한 번 일어났다. 앞 시험이 실패해 리소스가 남은 채 `down -v`가 돌았고, 남은 LV·인스턴스를 agent API로 손으로 지웠다(설계 §7-9). 그래서 e2e는 `down -v` 전에 `demo.py --clean`을 먼저 하고(`test_compose_stack_live.py:324-341` `test_down_leaves_nothing_behind`, `:173-183` `cleanup`), README는 "`down -v`는 리소스가 없을 때만"이라고 적는다(`README.md:65-67`).

### 3.7 이미지 설계

**agent (`deploy/agent/Dockerfile`).**
- 다단계 빌드(multi-stage build)로 `docker:29.1.3-cli`에서 docker CLI 바이너리 하나만 가져온다(`:7`, `:16`). agent가 인스턴스를 `docker run`·`inspect`·`exec`로 다루기 때문이다.
- 바탕은 `ubuntu:24.04`에 apt 도구들이다(`:9-15`). 줄마다 쓰임을 주석으로 단다. LVM·thin 도구는 aggregate와 볼륨, e2fsprogs는 `mkfs.ext4`·`resize2fs`·`chattr`, iproute2는 tc, iptables는 되돌리기 창, util-linux는 `losetup`·`mount`·`findmnt`·`nsenter`, kmod는 `modprobe`, procps는 `sysctl`이다.
- 의존성은 저장소의 `pyproject.toml` 하나가 정한다(D-14). `pip install .`은 패키지 없이(`packages = []`) 의존성만 venv `/opt/venv`에 설치한다(`:19-21`). 그다음 `backend/storage_agent`만 복사한다(`:22`). 의존성 층이 코드 층보다 앞이라 코드만 바뀌면 의존성 층은 캐시를 쓴다.
- init도 이 이미지를 쓴다 (3.2).

**anf-api (`deploy/api/Dockerfile`).**
- `python:3.12-slim`(`:4`), uid 1000 사용자 `anf`, `/data`를 그 사용자 소유로 만든다(`:6`). `USER anf`(`:15`)로 root가 아니다. root가 필요한 일은 storage agent에만 둔다는 ADR AR-06과 같다.
- 상태 DB는 `ANF_API_DB=/data/anf-api.db`(`:14`)이고 compose가 이름 있는 볼륨 `anf-api-data`를 `/data`에 붙인다. 이미지에서 `/data`를 `anf` 소유로 만들어 두면 새 이름 있는 볼륨이 그 소유를 받는다(S9 Q3). 컨테이너 안에 두면 다시 만들 때 리소스 기록이 사라져 agent의 볼륨과 어긋난다(결정 7). S9 R4에서 작업 도중 anf-api 컨테이너를 `docker kill`했다 다시 띄우자, 같은 작업 상태 URL이 폴링 15.2 s 만에 `Succeeded`였다(SQLite가 볼륨에 남았다).

**대시보드 (`deploy/dashboard/Dockerfile`, `nginx.conf`).**
- 다단계 빌드다. `node:22-alpine` 단계가 `npm ci`와 `npm run build`를 하고(`Dockerfile:4-9`), `nginx:1.28.0-alpine` 단계가 빌드 결과와 설정 파일 하나만 갖는다(`:11-13`). `package.json`·`package-lock.json`을 먼저 복사해 `npm ci` 층을 소스 변경과 떼어 놓는다(`:6-7`).
- WSL에는 node가 없다(`CLAUDE.md` Dashboard: Node 22는 Windows에만). 빌드를 이미지 안에서 하므로 WSL만으로 전체가 뜬다(결정 6).
- S9의 비교: nginx 이미지 74 MB(내용 21 MB)·메모리 10~12 MiB, `vite preview` 이미지 534 MB(내용 152 MB)·78 MiB. 둘 다 정적 파일, SPA 대체, 두 프록시가 200이었다. vite preview는 `vite.config.ts`의 프록시를 그대로 쓰는 대신 `node_modules` 전체가 이미지에 남는다.
- nginx 설정(`nginx.conf`)은 Vite dev·preview 서버의 프록시와 같은 규칙이다. `listen 127.0.0.1:8081`(`:4`). `location /`는 `try_files $uri /index.html`로 SPA 대체를 한다(`:8-10`). `/subscriptions`는 경로와 쿼리를 그대로 anf-api로 넘긴다(`:13-15`). `/prometheus/`는 `proxy_pass http://127.0.0.1:9090/;`의 끝 `/` 때문에 접두사가 떨어진 `/api/v1/…`로 간다(`:18-20`). 브라우저가 같은 출처로 부르므로 anf-api에 CORS가 필요 없다.
- 포트 8081은 Windows의 Vite dev(5173)·preview(4173)와 겹치지 않게 고른 값이다(S9 Q4).

**빌드 컨텍스트와 `.dockerignore`.** 컨텍스트는 저장소 루트인데 루트는 275 MB다(`.git`, `.venv-win`, `frontend/node_modules` 등, S9). `.dockerignore`는 `*`로 모두 뺀 뒤 필요한 것만 되살리는 허용 목록이다(`.dockerignore:3-8`). 되살린 폴더 안에서도 `frontend/node_modules/`, `frontend/dist/`, `__pycache__`는 다시 뺀다(`:9-11`). 이 파일은 LF로 고정했다(`.gitattributes:5-7`). Windows 체크아웃의 CRLF면 패턴 끝에 `\r`이 붙어 아무 파일과도 맞지 않는다(설계 §7-10).

**바탕 이미지는 태그로 고정한다** (결정 10). digest 고정은 갱신이 번거로워 버렸다.

**크기.** 구현 뒤 이미지는 agent 314 MB, anf-api 219 MB, 대시보드 74 MB다(메인 세션이 전달한 측정값이고, 설계 §7·진행 기록에는 아직 없다. S9의 실험 이미지는 311·216·74 MB였다).

**`--build`와 다시 실행 (결정 13, 설계 §7-2).**
- 같은 `up -d --build --wait`를 다시 돌리면(8.5 s, 0으로 끝남) `init`·`storage-agent`·`anf-api`·`dashboard`가 `Recreate`된다. 빌드 단계는 모두 CACHED인데도 그렇다. BuildKit이 빌드마다 provenance attestation(시각·호출 ID가 든 manifest)을 붙여 이미지 ID가 바뀌기 때문이다.
- 시도한 것: 서비스의 `build.provenance: false`는 compose 2.40.3이 bake로 넘기지 않아(`build --print`에 없음) 효과가 없었다. `SOURCE_DATE_EPOCH`로도 ID가 같아지지 않았다. ID가 같아지는 방법은 명령 앞의 `BUILDX_NO_DEFAULT_ATTESTATIONS=1`(`deploy/.env`로는 전달되지 않음)이나 `docker compose build --provenance=false`(up에는 그 옵션이 없음)뿐이었다. `--build` 없이 `up -d --wait`를 다시 돌리면 2.7 s에 init만 다시 돌고 나머지는 `Running`이었다.
- 결정: `--build`를 둔다. 빼면 코드를 고친 뒤 옛 이미지로 뜨는 함정이 생기고, 환경 변수를 붙이면 명령이 길어지고 설명이 필요하다. 대신 AC-02를 "같은 명령을 다시 실행해도 리소스·데이터·볼륨 인스턴스가 바뀌지 않는다(스택 서비스 컨테이너는 다시 만들어질 수 있다)"로 고쳤다.
- 이 결정이 안전한 근거는 둘이다. 하나는 3.6의 구조다. agent가 다시 만들어져도 인스턴스와 마운트는 그대로다. 다른 하나는 3.4의 비재귀 바인드다. 다시 만들어진 agent가 숨은 복사본을 만들지 않는다. e2e가 클라이언트가 쓰는 중에 같은 명령을 다시 돌려 인스턴스가 그대로인지 본다(`test_compose_stack_live.py:252-256`).

### 3.8 데모 스크립트 `scripts/demo.py`

**모양 (결정 8).** Python 표준 라이브러리만 쓴다. 그래서 venv 없이 호스트의 `python3`로, root 없이 docker 그룹으로 돈다. bash는 JSON과 폴링이 어렵고, pytest로만 만들면 사람이 읽는 대본 출력이 안 된다. e2e 도우미를 다시 쓰면 venv와 root가 필요해진다. 요청은 ARM API(127.0.0.1:8080)로 보내고, 효과는 `anf-nfs-client` 컨테이너에서 본다. 단계마다 `[n] …` 한 줄씩 무엇을 했고 클라이언트가 무엇을 봤는지 출력한다(`say`, `demo.py:152-153`). 데모 전용 구독 `de300000-0000-4000-8000-000000000013`을 써서 다른 리소스와 섞이지 않는다(`:30`).

**PRD §5의 7단계**

| 단계 | 보내는 요청 | 클라이언트에서 보는 근거 | 코드 |
| --- | --- | --- | --- |
| 1. 계정 → 풀 → 볼륨 둘 | PUT 계정, PUT 풀(Premium, Manual QoS, 4 TiB), PUT 볼륨 `vol-v3`(NFSv3)·`vol-v41`(NFSv4.1), 둘 다 50 GiB·20 MiB/s. 각 PUT의 즉시 응답이 `201`인지 보고 `Azure-AsyncOperation`을 0.5 s마다 종결까지 폴링한 뒤, GET의 `provisioningState`가 `Succeeded`인지 본다 | 즉시 응답 ms와 `Succeeded`까지 걸린 초, 마운트 대상 `<IP>:/<creationToken>` | `step1` `:266-273`, `put` `:181-191`, `wait` `:161-179`, `volume` `:193-204` |
| 2. 마운트와 쓰기 | 없음 | 클라이언트 `anf-demo-client-1`(anf-vnet, privileged)이 v3(`vers=3,nolock`)과 v4.1을 마운트하고 `/proc/mounts`의 `vers=`가 기대와 같은지 본다. `hello.txt`를 쓰고 다시 읽는다 | `step2` `:275-285`, `client` `:217-222`, `mount` `:224-231` |
| 3. 스냅샷과 `.snapshot` | PUT 스냅샷 `vol-v3/snap1` | `rm /v3/hello.txt` 뒤 `ls`에 없고, `/v3/.snapshot/snap1/hello.txt`가 같은 내용으로 읽힌다 | `step3` `:287-300` |
| 4. 되돌리기 | POST `…/vol-v3/revert` `{snapshotId}` → `202` | 다시 마운트하지 않은 채 `/v3/hello.txt`가 다시 읽힐 때까지 1 s마다 `cat`, 되돌리기가 끝나고 몇 초 뒤에 보였는지 | `step4` `:302-309`, `read_until` `:233-243` |
| 5. 새 볼륨 복원 | PUT `vol-restored` `{snapshotId}` (`protocolTypes`를 보내지 않아 원본을 따른다, `:196-197`). `originatingResourceId`가 그 스냅샷 ID인지 본다 | 다른 클라이언트 `anf-demo-client-2`가 마운트해 `hello.txt`를 읽고 `only-in-restored.txt`를 쓴다. 첫 클라이언트의 `ls /v3`에는 그 파일이 없다 | `step5` `:311-330` |
| 6. 처리량 제한 | PATCH `vol-v41` `throughputMibps` 20 → 5 → `202` | 한도마다 fio 6 s 직접 쓰기 3회, 회마다 MiB/s와 중앙값의 비율. 끝에 한 줄: 내리기 전 중앙값과 가장 빠른 회, 내린 뒤 중앙값, "내리기 전 가장 빠른 회가 새 한도의 천장(5.22)보다 빨랐다", "어느 회도 자기 천장(한도의 101% + 6 s 창의 1 MiB I/O 하나)을 넘지 않았다" | `step6` `:332-348`, `fio_write` `:245-262`, `ceiling`·`under_ceiling`·`follows_limit` `:107-121` |
| 7. 대시보드와 메트릭 | GET Prometheus 쿼리(8081의 `/prometheus/` 프록시로), GET `8081/?subscription=…`, GET `8081/subscriptions/…/volumes`, GET `up` | 이번 볼륨의 쓰기 rate 최댓값이 새 한도의 절반 이상이고 한도 계열이 5 MiB/s(30 s 안). 페이지에 `<div id="root">`, `/subscriptions` 프록시로 볼륨 셋, `/prometheus` 프록시로 수집 대상의 `up`. 브라우저로 열 주소를 출력한다 | `step7` `:356-384`, `prom` `:350-354` |

- 볼륨은 50 GiB다(`:34`). 스택은 최소 크기를 낮추지 않는다(`ANF_MIN_VOLUME_SIZE_GIB`는 검증용). thin LV라 실제 디스크는 쓴 만큼만 쓴다.
- 볼륨 셋(`vol-restored` 포함)이 모두 20 MiB/s로 만들어진다(`volume` `:195`). 그래서 풀(Premium 4 TiB Manual, 예산 256 MiB/s, `:36` 주석) 사용은 60 MiB/s이고, 6단계 뒤 45 MiB/s다(설계 §7-3).
- 7단계의 쿼리는 `volume_uuid`(볼륨의 `fileSystemId`)로 고른다(`:359-361`). 처음에는 `creation_token`으로 골랐는데, 이전 데모의 같은 이름 볼륨이 쿼리 창(3분) 안에 남아 앞 실행의 값(24.5 MiB/s)을 보였다(설계 §7-4). Prometheus와 대시보드 확인은 모두 nginx(8081)를 거치므로, 7단계가 프록시도 같이 검사한다.

**처리량 판정: 천장과 "따라 바뀜" (설계 §7-3, 검증 1회차와 2회차 뒤 바뀜).** PRD §5의 6단계는 "제한을 걸고 잰다, 바꾸면 따라 바뀐다"이다. 데모는 그 두 가지만 판정한다.
- **잰다.** 한도마다 `FIO`(`demo.py:55-57`)를 3회(`FIO_RUNS`, `:53`) 돌린다. `--direct=1 --ioengine=libaio --bs=1M --iodepth=16 --time_based --ramp_time=1 --runtime=6`, 즉 1 s 예열 뒤 6 s 동안의 직접 쓰기다. I/O 크기와 측정 창은 상수 `FIO_BS_MIB, FIO_RUNTIME_S = 1, 6`(`:54`)이고, fio 명령과 천장 계산이 같은 값을 쓴다. `fio_mibps`(`:100-104`)가 JSON의 `io_bytes ÷ runtime`으로 MiB/s를 낸다. 출력에는 회마다 값과 중앙값의 비율을 모두 보인다(`fio_write` `:254-255`).
- **천장.** `ceiling(limit)`(`:107-110`) = 한도 × 1.01 + `FIO_BS_MIB ÷ FIO_RUNTIME_S`(1 MiB ÷ 6 s = 0.167 MiB/s)다. 20 MiB/s면 20.367, 5 MiB/s면 5.217이다. 1.01(`HIGH`, `:46`)은 FR-08 결정 15와 같은 위쪽 허용 오차이고, 0.167은 I/O 하나의 여유다(아래). `under_ceiling`(`:113-115`)은 세 회의 **최댓값**이 그 이하인지 본다. 한 회라도 넘으면 `fio_write`가 PATCH를 보내기 전에 `a run went above the ceiling of … MiB/s (101% of the limit plus one 1 MiB I/O in the 6 s window)`로 멈춘다(`:256-257`).
- **따라 바뀜.** `follows_limit`(`:118-121`): `round(median(after) / new_limit, 4) <= HIGH and max(before) > ceiling(new_limit)`. 두 조건이다.
  - 내린 뒤: 세 회의 **중앙값**이 새 한도의 101%(5.05 MiB/s) 이하다.
  - 내리기 전: 세 회 중 **가장 빠른 회**가 새 한도의 천장 `ceiling(5)` = 5.217보다 빠르다. 천장 논리로는 5.217보다 빠른 회는 새 한도로는 나올 수 없으므로, "내리기 전에는 새 한도가 아니었다"는 근거가 된다. 스토리지가 느린 회가 섞여도 흔들리지 않게 중앙값이 아니라 가장 빠른 회를 본다(`:119-120` docstring, 이유는 아래 "내리기 전을 가장 빠른 회로 본 이유").
  - 어긋나면 `did not follow the limit change: …; expected the fastest run before above 5.22 MiB/s (the ceiling of 5 MiB/s) and the median after at most 101% of 5 MiB/s`로 실패한다(`step6` `:343-346`). 통과하면 한 줄을 보인다(`:347-348`): `the measured write throughput followed the limit: median … MiB/s (fastest run …) under 20 MiB/s -> median … MiB/s under 5 MiB/s; the fastest run before was above 5.22 MiB/s, the ceiling of the new limit; no run went above its own ceiling (…)`. e2e는 두 한도의 fio 줄과 이 줄의 앞부분(`the measured write throughput followed the limit: median `)을 확인한다(`test_compose_stack_live.py:227-229`).
- **아래쪽은 판정하지 않는다.** 중앙값이 한도의 90%(`SLOW`, `:47`) 아래면 `the storage wrote slower than the limit this time (median below 90%). Not a failure: the limit is a ceiling, and the FR-08 data tests check how close to it the volume gets`를 한 줄 붙이고 넘어간다(`:259-261`). 한도에 얼마나 가까운지(90~101%)는 FR-08의 처리량 데이터 시험이 본다. 그 시험은 6회 재고 첫 회를 버린 5회의 중앙값을 쓴다(`docs/concepts/test-automation.md` 4절). 데모는 FR-08의 수락 판정을 대신하지 않는다.
- 원인은 S7 Q2와 같은 서버 쪽 쓰기 멈춤으로 보지만 확인하지 못했다. 면접에서는 "확인하지 못했다"까지 말한다.

**판정이 이렇게 된 과정.**
1. 처음에는 32 → 16 MiB/s였다. 한 회에서 첫 측정이 21.64 MiB/s(68%)였다. FR-08 스파이크 S7 Q2의 "30 MiB/s 이상 NFS 쓰기의 서버 쪽 저하"(제한기가 원인이 아님)와 같은 모양이라 10 → 5 MiB/s로 내렸다.
2. e2e 안의 데모 한 회에서 10 MiB/s 한 번 측정(10 s)이 3.76 MiB/s(38%)였다. 한 번 재기로는 믿을 수 없어 6 s × 3회로 바꾸고, "중앙값이 한도의 90~101%이고 어느 회도 101%를 넘지 않음"으로 판정했다. 검증 1회차는 이 판정(`01ab88e`)을 돌렸다.
3. 검증 1회차: 데모 10회 중 3회가 6단계에서 실패했다(AC-03 FAIL). 10 MiB/s의 세 회가 `7.76, 7.8, 6.78`(중앙값 78%), `7.15, 6.24, 9.95`(72%), `6.5, 8.22, 9.89`(82%)였다. 어느 회도 101%를 넘지 않았다. 실패 직후 vol-v41 인스턴스 netns의 HTB가 `rate 87710Kbit`(10 MiB/s ÷ 0.9564)이고 LVM 태그가 `anf_qos=10.0`으로 맞았으며, 같은 볼륨·같은 클라이언트에서 곧바로 잰 같은 fio 4회는 98%였다. 즉 제한기는 맞게 걸려 있었고, 스토리지가 그 순간 한도만큼 쓰지 못했다(S7 Q2, FR-12 AC-06과 같은 현상). verifier의 e2e 재실행도 같은 이유로 1 failed, 4 passed(221.73 s)였다.
4. 첫 수정(메인 세션 자동 채택, verifier의 둘째 제안과 같은 방향): 아래쪽 판정을 빼고 천장과 "따라 바뀜"만 본다. "따라 바뀜"은 그때 내린 뒤 중앙값 ≤ 5.05 < 내리기 전 **중앙값**이었다. 한도 짝도 20 → 5로 바꿨다(아래).
5. 수정 확인 10회(implementer): 그때의 천장은 "회마다 한도의 101%"였는데, 07회가 5 MiB/s에서 실패했다. 둘째 수정으로 천장에 I/O 하나의 여유를 더했다(아래).
6. 검증 2회차(대상 `4887031`): 데모 10회 연속 `exit 0`으로 AC-03 PASS. 다만 verifier는 "따라 바뀜"의 내리기 전 쪽 여유가 얇다고 지적했다. 메인 세션이 그 제안 (b)를 자동 채택해, 내리기 전 쪽을 중앙값에서 가장 빠른 회로 바꿨다(`814afb1`, 설계 `8732c9b`, 아래).

**왜 20 → 5인가 (1회차 뒤의 근거).** 당시의 "따라 바뀜"은 내리기 전 중앙값이 5.05 MiB/s(새 한도의 101%) 이하면 깨졌다. 첫 한도가 10이면 그것은 한도의 50.5%이고, 20이면 25%다.
- 그때 기록에 있던 쓰기 한 회의 최저는 38%(10 MiB/s에서 3.76)였다. 10에서는 이미 5.05 아래이고, 20의 38%는 7.6이다. 데모의 10 MiB/s 기록은 3회 중앙값 최저 72%(7.15), 한 회 최저 62%(6.24)였다.
- 20 MiB/s 쓰기는 10보다 자주 흔들리지만 깊지 않았다. FR-12 AC-06 반복 9회의 5 s 창 72개 중 최저가 11.6(58%)·14.0(70%)·15.2(76%)였고, FR-08 데이터 시험의 20 MiB/s 쓰기 한 회 최저는 15.66(78%)이었다. 10 MiB/s 창 54개는 모두 9.6 이상이었다(설계 §7-3).
- 수정 확인 10회의 10회차에서 20 MiB/s 한 회가 7.22(36%)로 기록을 낮췄고(`13.67, 7.22, 17`, 중앙값 68%, "slower" 안내가 붙고 통과), `4887031`의 단위 테스트는 "한 회 최저 36% × 20 > 5.05"를 고정했다.
- **이 전제는 2회차 동안 틀렸다.** HEAD `4887031`로 돌린 데모 8회 가운데 한 회가 3.68(18%)이었다(설계 §7-3의 `run-5`, 2회차 보고서의 7회차). 중앙값 판정이라 그 데모는 통과했지만, "한 회 최저 36%"라는 근거는 무너졌다. 지금의 한도 짝 근거는 아래의 가장 빠른 회다.

**내리기 전을 가장 빠른 회로 본 이유 (검증 2회차 뒤, 커밋 `814afb1`).**
- 관찰: HEAD `4887031`로 메인 세션이 돌린 데모 8회(`/var/tmp/fr13-demo-repeat-head/run-1.log`~`run-8.log`)는 모두 `exit 0`이었다. `run-8`의 20 MiB/s 세 회는 `16.14, 5.93, 7.25`(중앙값 7.25 = 36%)로, 옛 문턱 5.05와 2.2 MiB/s 차이였다. 세 값 중 둘이 5.05 아래였으면 한도가 지켜졌는데도 `did not follow`로 `exit 1`이었다. `run-5`에는 한 회 3.68(18%)이 있었다.
- verifier의 지적(2회차 판정 밖 관찰 1): 1회차 결함과 같은 종류다. 스토리지가 몇 초 느리게 쓴 것을 실패로 만드는 길이, 아래쪽 판정에서 `follows_limit`의 문턱 하나로 좁아졌을 뿐 남아 있다. 느린 회는 한 데모 안에 몰려 나온다(`run-8`, `8c02910` 반복 10회차 `13.67, 7.22, 17`, 1회차 실패 셋). 그래서 회마다 독립이라고 보고 확률을 곱하면 위험을 작게 잡는다. 그리고 이 e2e는 CI `data-plane` `rest` 조각에서 돌아, 드문 거짓 실패라도 PR을 막는다.
- 바꾼 판정: 내리기 전 쪽을 `max(before) > ceiling(NEW_LIMIT)`(5.217)로 본다.
  - 그래도 잡는 것: 첫 한도가 처음부터 5 근처였다면(PATCH 전부터 5였다면) 천장 때문에 최댓값이 5.217을 넘을 수 없어 실패한다. 내린 뒤 쪽(중앙값 ≤ 5.05)과 두 천장은 그대로라, PATCH가 적용되지 않아 내린 뒤에도 20 근처가 나오는 경우도 그대로 잡는다. 내리기 전의 가장 빠른 회가 이상하게 높으면 천장(20.367)이 잡는다.
  - 거짓 실패가 나는 경우: 20 MiB/s 세 회가 **모두** 5.217 이하일 때뿐이다.
- 근거 수치: 수정 뒤 실제로 돈 데모 20회(`8c02910` 반복 10 + e2e 2 + HEAD 8)의 20 MiB/s 측정에서 한 회 최저는 3.68(18%), 3회 중앙값 최저는 7.25(36%), 3회 중 가장 빠른 회의 최저는 16.14(81%)였다. 이 20회의 측정값을 새 판정(`814afb1`)에 다시 넣으면 20회 모두 통과한다(`/var/tmp/fr13-demo-repeat-head/rejudge-max.txt`).
- 단위 테스트가 이 근거를 고정한다: `16.14 / 20 * demo.LIMIT > demo.ceiling(demo.NEW_LIMIT)`(`test_demo.py:62-65` `test_the_limit_pair_leaves_room_for_the_slowest_write_seen`). 81%의 첫 한도가 새 한도의 천장보다 빨라야 한다는 뜻이다. 한도 짝을 바꾸면 이 테스트가 다시 묻는다. 다만 16.14는 기록에서 옮겨 적은 값이라, 더 느린 묶음이 나오면 사람이 고쳐야 한다.
- 버린 선택지: (a) 중앙값 판정을 그대로 두고 알려진 한계로 기록한다. 스토리지가 느린 순간을 실패로 만드는 길이 남고, 그 길이 CI에서 PR을 막을 수 있다. (c) 내리기 전 중앙값이 문턱 아래일 때만 3회를 더 잰다. 느린 회가 한 데모 안에 몰려 나오므로 다시 재도 같을 수 있고 [추론: 다시 잰 기록은 없다], 데모가 길어지고 출력이 두 묶음이 된다.
- 이 변경은 실환경에서 다시 돌리지 않았다. 근거는 단위 테스트와 실측 20회의 재판정이고, 새 판정으로 데모가 실제로 도는 것은 PR의 CI `rest` 조각이 처음이다(진행 기록).

**천장에 I/O 하나를 더한 이유 (수정 확인 10회 뒤, 커밋 `85428ec`).**
- 07회의 출력: `fio write on vol-v41 with the limit 5 MiB/s: 4.96, 4.76, 5.12 MiB/s (median 4.96 = 99%); a run went above 101% of the limit`. 셋째 회 5.12가 102.4%였고, 바로 앞 회 4.76이 평소(4.95~4.97)보다 낮았다. 세 회 평균은 4.95(99%)다. 같은 10회의 다른 5 MiB/s 측정 27번은 모두 4.97 이하였다.
- fio는 `--ramp_time=1` 뒤 6 s 창 안에서 끝난 1 MiB I/O만 센다. 5 MiB/s면 창 하나에 끝나는 I/O가 약 30개라, I/O 하나가 한도의 3.3%다(20 MiB/s에서는 0.83%). 앞 회에서 끝나야 할 완료 하나가 서버 쪽 쓰기 멈춤으로 밀려 다음 창에 들어가면, 앞 회는 그만큼 낮게, 뒤 회는 그만큼 높게 센다. 07회의 값(앞 회는 약 1 MiB 모자라고 뒤 회는 약 1 MiB 넘침)이 그 모양과 맞는다 [추론: 완료 시각을 직접 보지 않았다]. `ceiling`의 docstring(`demo.py:108-109`)이 같은 설명을 적는다.
- 2회차 verifier는 기제를 조금 다르게 설명했다. 완료가 고르게 오면 6 s 창에 N개 또는 N+1개가 들어가고, 5 MiB/s에서 31개면 31/6 = 5.167이다. 관찰된 5.12, 5.1, 5.15는 모두 31개 언저리다. 설계의 설명("앞 회에서 밀린 완료")과 기제는 다르지만 같은 상한이 나온다고 적었다. 이것도 완료 시각을 본 관찰이 아니라 계산이다.
- 그래서 회마다 측정의 해상도, 즉 I/O 하나만큼 여유를 둔다. I/O 하나로 설명되지 않는 초과(5 MiB/s에서 5.3)는 계속 실패다. 2회차 verifier의 계산으로는 두 개 이상(5.33 이상)은 걸린다.
- 버린 선택지: 세 회 합으로 판정(5 MiB/s × 18 s에서 I/O 하나가 1.1%라 여전히 빠듯하다), 5 MiB/s에서 bs를 줄임(부하 모양이 바뀐다), 상한도 중앙값으로 봄(한 회의 진짜 초과를 놓친다).
- 그 10회의 측정값 60개를 새 판정에 다시 넣자 10회 모두 통과했다(`/var/tmp/anf-clone-tests/fr13-demo-repeat/rejudge.txt`: `10 of 10 runs pass the new step 6 judgement (60 values)`). 2회차 verifier가 같은 값으로 따로 계산해 같은 결과를 얻었다. 07회의 값은 새 천장 5.217 아래다(단위 테스트의 `[4.96, 4.76, 5.12]` 경우).
- 실행으로도 확인됐다. 2회차의 HEAD 8회 가운데 두 회에서 5 MiB/s의 한 회가 5.15(103%)와 5.1(102%)이었다. 07회를 실패시킨 조건과 같지만 새 천장 안이라 통과했다. 수정 뒤 5 MiB/s 측정 60회의 최댓값은 5.15다(2회차 보고서).

**판정의 단위 테스트 (`backend/tests/unit/test_demo.py`).**
- `test_under_ceiling_allows_101_percent_plus_one_io_per_run`(`:28-39`): 20 MiB/s에서 `[14.3, 12.48, 19.9]`(검증 1회차의 72% 모양)는 통과, 20.36은 통과·20.37은 실패. 5 MiB/s에서 07회의 `[4.96, 4.76, 5.12]`는 통과, 5.21은 통과·5.22는 실패, 5.3은 실패(I/O 하나로 설명되지 않는 진짜 초과).
- `test_the_ceiling_uses_the_io_size_and_window_of_the_fio_command`(`:42-45`): fio 명령에 같은 `--bs`·`--runtime`이 들어 있고, `ceiling(5.0)`이 그 값으로 계산된다. fio 명령만 바꾸고 천장을 그대로 두는 실수를 막는다.
- `test_follows_limit_needs_a_run_before_faster_than_the_new_ceiling_and_the_median_after_within_it`(`:51-59`, 내린 뒤 값 `AFTER = [4.97, 4.96, 4.97]` `:48`): `[19.7, 19.8, 19.8]` 통과. 2회차 `run-8`의 `[16.14, 5.93, 7.25]`는 중앙값이 36%여도 가장 빠른 회가 5.217을 넘어 통과. `[3.68, 4.9, 16.0]`은 중앙값 4.9가 5.05 아래라 옛 판정에서는 실패였지만 16.0은 새 한도로 낼 수 없어 통과. `[4.9, 5.1, 5.2]`는 가장 빠른 회 5.2 ≤ 5.217이라 새 한도에서도 나올 수 있는 속도여서 실패. 내린 뒤 `[4.97, 5.1, 5.1]`은 중앙값이 5.05를 넘어 실패.
- `test_the_limit_pair_leaves_room_for_the_slowest_write_seen`(`:62-65`): 위 "근거 수치"의 81%를 고정한다.
- 가짜 fio(`FakeFio`, `:158-166`)로 6단계 전체를 돌린다. 느린 회는 안내 한 줄만 붙고 통과하며, 99%인 두 번째 측정에는 안내가 붙지 않는다. 끝 줄에 내리기 전 중앙값과 가장 빠른 회, `the fastest run before was above 5.22 MiB/s, the ceiling of the new limit`, `no run went above its own ceiling (…)`가 있는지도 본다(`:169-182`). 한 회가 천장을 넘으면 PATCH를 보내지 않고 `above the ceiling of 20.37 MiB/s`로 실패한다(`:185-190`). 내리기 전 가장 빠른 회도 새 한도의 천장 이하(`4.9, 5.1, 5.2`)면 `did not follow … expected the fastest run before above 5.22 MiB/s`로 실패한다(`:193-196`).

**스스로 치우기, `--keep`, `--clean`, 종료 코드 (설계 §7-5, `main` `:425-462`).**
- 시작하기 전에 스택을 확인한다(`check_stack`, `:408-422`). API 목록 GET, 대시보드 `/`, 대시보드를 거친 Prometheus `/-/ready`, 클라이언트 이미지가 있는지 본다. 하나라도 안 되면 시작 명령을 보이고 **2**로 끝난다(`:431-435`).
- 시작할 때 한 번 정리한다(`:437-443`). 이전 `--keep` 실행이 남긴 것을 지워서 데모를 다시 돌릴 수 있다. `--clean`이면 정리만 하고 0으로 끝난다.
- 단계 하나가 기대와 다르면 `[n] FAILED: …`를 표준 오류에 쓰고 **1**이다(`:446-449`). 예상하지 못한 예외도 같은 경로로 단계 번호와 함께 보인다.
- `finally`에서 `--keep`이 아니면 실패해도 치운다(`:450-458`). 정리 순서는 클라이언트 → `vol-restored`·`vol-v41`·`vol-v3` → 풀 → 계정이다(`cleanup`, `:395-406`). DELETE가 `204`면 지울 것이 없었던 것이다(`delete`, `:388-393`). 정리가 실패하면 `--clean`을 안내하고 1이다.
- `--keep`은 사람이 대시보드로 결과를 보게 남긴다. 그 뒤 지울 방법이 대본 전체 재실행뿐이면 AC-08("데모가 치운 뒤 남은 것이 없다")을 맞추기 번거로워서 `--clean`을 더했다.
- 단위 테스트(가짜 HTTP·docker, `FakeApi` `test_demo.py:83-106`, `FakeDocker` `:109-117`): 스택이 없으면 2이고 GET 말고는 아무것도 보내지 않는다(`:120-126`). 클라이언트 이미지가 없으면 2다(`:129-131`). 볼륨이 `Failed`면 1단계에서 멈추고 오류를 보이며 클라이언트를 띄우지 않고 치운다(`:134-144`). `--keep`이면 실패해도 지우지 않는다(`:147-152`).
- 검증 1회차에서 세 종료 코드를 모두 실제로 봤다. 스택을 내린 뒤 실행하면 시작 명령을 보이고 2였고, 아무것도 만들지 않았다. 6단계가 어긋난 `--keep` 실행은 단계 번호와 회마다 값을 표준 오류에 보이고 1이었으며, 리소스를 남겼다. 이어서 `--clean`이 그것을 지우고 0이었다.
- `http_proxy` 환경 변수를 따르지 않는 opener를 쓴다(`demo.py:79`). 프록시가 설정된 셸에서도 127.0.0.1로 바로 간다.

### 3.9 테스트

**단위: compose 파일의 불변 조건 (`backend/tests/unit/test_compose.py`).** 3.3의 조건이 빠지면 compose는 뜨지만 나중에 데이터 플레인이 깨진다(되돌리기 실패, VG 활성화 경합, `lvcreate` 멈춤). 그래서 파일이 조건을 담는지 테스트로 지킨다. 조건이 충분한지는 e2e가 본다(모듈 docstring `:3-5`).
- PyYAML은 의존성에 없다. `pyproject.toml`이 제품 코드 해시에 들어가서, 이 테스트 하나 때문에 바꾸면 완료된 기능의 검증 대상 코드가 달라진다(`docs/concepts/ci.md` §3.4와 같은 이유). 그래서 compose 파일이 쓰는 YAML 부분집합만 읽는 작은 파서를 테스트 파일 안에 뒀다(`parse_compose_subset`, `:22-76`). 파서가 파일 전체를 읽었는지부터 본다(`:95-97`).
- 조건별 테스트: 특권·host 네트워크·pid(`:100-105`), 비재귀 바인드(`:108-112`), `ns` rshared와 init 성공 대기(`:115-122`), 두 긴 문법 바인드의 `create_host_path`(`:125-131`), LVM 잠금(`:134-137`), `/run/udev:ro`와 `ipc: host`를 함께(`:140-147`), `/dev`·`/lib/modules`·Docker 소켓(`:150-154`), init의 모양(`:157-166`), localhost만(`:169-177`), compose가 네트워크를 소유하지 않음(`:180-182`). 각 단언 옆 주석이 S9의 번호(`create_host_path`는 검증 1회차의 관찰)와 실패 모양을 적는다.

**단위: 데모 스크립트 (`backend/tests/unit/test_demo.py`).** 순수 부분(fio JSON 해석, 천장 판정, 내리기 전 가장 빠른 회와 내린 뒤 중앙값으로 보는 "따라 바뀜" 판정, 실측 최저 81%로 고정한 한도 짝의 여유, Prometheus 값, 작업 오류 문구), 종료 코드, 가짜 fio로 돌린 6단계를 본다 (3.8). 2회차 verifier가 Windows `.venv-win`에서 `test_demo.py`와 `test_compose.py`를 돌려 35 passed였다(`4887031` 기준. `814afb1`의 테스트 결과는 이 문서의 입력에 없다).

**실환경 e2e (`backend/tests/e2e/test_compose_stack_live.py`, `dataplane` 마커).**
- README의 명령에 프로젝트 이름만 더한다(`-p anf-clone-e2e`, `:43-45`). 사용자 스택(`anf-clone`)의 이름 있는 볼륨을 이 시험의 `down -v`가 지우지 않게 하려는 것이다(설계 §7-9). 이미지는 같은 것을 쓴다.
- 실행기는 root로 돌지만, 스택과 데모는 docker 그룹의 일반 사용자로 돌린다. `setpriv --reuid --regid --init-groups`로 권한을 내린다(`as_user`, `:56-64`). "sudo 없이"라는 수락 기준을 그대로 시험한다.
- 시간은 `/proc/uptime`(단조 시계)으로 잰다(`:67-69`). WSL 벽시계는 뒤로 건너뛴다.
- 모듈 픽스처가 시작 때 네 포트가 비었는지 보고, 기준선(LV, 인스턴스)을 남기고, 끝나면 실패했더라도 치운다(`stack` `:186-193`, `cleanup` `:173-183`).
- 시험 다섯이 파일 순서대로 돈다. 명령 하나(AC-01) → 데모 1~7단계·정리·메모리(AC-03·07, `:212-237`) → 다시 실행과 `down`/`up`(AC-02) → agent kill 뒤 되돌리기·삭제(AC-06) → `down -v` 뒤 남은 것 없음(AC-08 일부). 메모리는 별도 스레드가 3초마다 `free -m`과 `docker stats`를 적는다(`Memory`, `:147-166`).
- agent kill 시험(`:279-321`)은 쓰는 중에 agent 컨테이너를 `docker kill`하고, 5 s 뒤 8090이 닫혔는지 보고, 같은 명령으로 다시 띄운다. 쓰기 오류 0, API가 본 리소스가 같음, 인스턴스 netns의 HTB·필터가 한도와 맞음(`tc_state`·`matches`, FR-08 도우미)을 본다. 그다음 되돌리기가 `Succeeded`이고 클라이언트가 스냅샷 시점의 파일을 보는지, `demo.py --clean`이 볼륨 셋·풀·계정을 모두 지우는지 본다.
- 이 파일은 CI data-plane 작업의 `rest` 조각에 저절로 들어간다. `rest`가 처리량 데이터 파일만 `--ignore=`로 빼고 나머지 전부를 고르기 때문이다(`docs/concepts/ci.md` §3.7, 결정 9). 새 CI 작업은 만들지 않았다.
- 실행기의 포트 점검과 남은 것 검사에 대시보드 포트 8081을 더했다(`scripts/run-dataplane-tests.sh:26` `listeners`). 포트가 차 있으면 "compose 스택일 수 있으니 내리라"는 안내를 붙인다(`:52-53`).

### 3.10 설계 결정

결정 1~12는 `anf-roadmap` 총괄의 자동 채택이고, 13은 구현 중 메인 세션이 정했으며, 14는 개념 문서 단계에서 더해졌다(설계 §4, 진행 기록). 검증 1회차 뒤의 두 수정(데모 6단계 판정, `create_host_path`)과 2회차 뒤의 수정(`follows_limit`의 내리기 전 쪽)은 번호 없는 자동 채택으로 설계 §7-3·§7-11에 있다. 사용자가 정한 것은 compose 설치 하나다 (6절).

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 1. 명령 하나 `docker compose -f deploy/compose.yaml up -d --build --wait` | 준비 스크립트 + compose 두 단계, 래퍼 스크립트 | 두 단계는 명령이 둘이고 sudo가 필요하다. 래퍼는 compose를 가린다 |
| 2. 호스트 준비는 한 번 도는 특권 `init` 서비스. 기존 `setup-wsl-dataplane.sh`를 `nsenter -t 1`로 호스트에서 그대로 돌리고 `ns` rshared 바인드를 더한다 | 준비 로직을 compose 쪽에 한 벌 더 둠 | 두 벌은 어긋난다. 같은 스크립트를 테스트 경로와 CI도 쓴다 |
| 3. agent는 특권 컨테이너 (S9의 조건 모두) | 호스트 root 프로세스로 남김 | "구성요소를 컨테이너로 묶는다"는 FR-13에 못 미치고 sudo가 필요하다. 컨테이너여도 권한은 root와 같다는 점을 문서에 적는다 |
| 4. `down` 뒤 볼륨 인스턴스는 남긴다. 다시 `up`하면 agent가 이어받는다 | `down`에서 인스턴스도 멈춤 | compose 밖이라 별도 스크립트가 필요하고, "관리 계층이 죽어도 데이터는 계속"이라는 설명을 잃는다. 다 지우려면 API로 지운다 |
| 5. `anf-vnet`은 external. init이 만든다 | compose가 소유 | `down`이 인스턴스가 붙은 네트워크를 지우려다 실패한다 |
| 6. 대시보드는 nginx 다단계 빌드, 포트 8081 | `vite preview` 컨테이너, Windows의 Vite에 의존 | 534 MB·78 MiB 대 74 MB·11 MiB. Windows Vite에 기대면 WSL만으로 전체가 뜨지 않는다 |
| 7. anf-api 상태는 이름 있는 볼륨의 SQLite | 컨테이너 안 | 다시 만들면 리소스 기록이 사라져 agent의 볼륨과 어긋난다 |
| 8. 데모는 표준 라이브러리 Python, 스스로 치움 + `--keep` (구현 중 `--clean` 추가) | bash, pytest로만, e2e 도우미 재사용 | JSON·폴링, 사람이 읽는 대본 출력, venv·root가 필요 없는 실행 |
| 9. 실환경 시험은 `dataplane` e2e 한 파일이 compose + 데모를 돌린다 | CI에 별도 작업 | 실행 경로가 둘이 된다. `rest` 조각이 저절로 고른다 |
| 10. 바탕 이미지는 태그 고정, `.dockerignore`로 컨텍스트를 줄임 | digest 고정 | 갱신이 번거롭다. 포트폴리오 범위 밖 |
| 11. Prometheus 서비스가 FR-12의 설정 파일을 그대로 쓴다. `scripts/run-prometheus.sh`는 테스트 경로용으로 남긴다 | 스크립트 삭제 | FR-12 e2e가 쓴다 |
| 12. 회귀는 PR의 CI `data-plane` 작업, WSL에서는 새 파일과 영향받는 파일만 | WSL 전체 묶음 | WSL 전체 묶음은 약 95분이다. 제품 코드 해시도 그대로다(진행 기록) |
| 13. `--build`를 두고 AC-02를 "리소스·데이터·인스턴스가 바뀌지 않는다"로 고친다 | `--build` 빼기, `BUILDX_NO_DEFAULT_ATTESTATIONS=1` | 빼면 코드를 고친 뒤 옛 이미지로 뜨는 함정이 생긴다. 환경 변수는 명령이 길어지고 설명이 필요하다 (3.7) |
| 14. 컨테이너 안의 LVM 메타데이터 백업(`/etc/lvm/archive`·`backup`)은 바인드하지 않는다. 컨테이너와 함께 사라지고, 한계로 적는다 | 호스트의 `/etc/lvm`을 바인드 | 호스트의 LVM 설정까지 컨테이너에 묶인다. 이 클론에는 `vgcfgrestore`로 복구하는 시나리오가 없다 (3.5) |

구현과 검증 1회차 뒤에 바뀐 것(설계 §7)은 위 절에 위치와 함께 설명했다. 목록만 모으면 이렇다. (1) agent LVM이 호스트 udev를 기다림(`/run/udev:ro` + `ipc: host`, 3.5). (2) `--build`와 다시 실행(결정 13, 3.7). (3) 데모 6단계는 천장(한도의 101% + I/O 하나)과 "따라 바뀜"으로 판정하고 아래쪽은 안내만, 한도 짝은 20 → 5 MiB/s(검증 1회차 뒤). "따라 바뀜"의 내리기 전 쪽은 중앙값이 아니라 가장 빠른 회가 새 한도의 천장을 넘는지로 본다(검증 2회차 뒤, 3.8). (4) Prometheus 판정은 `volume_uuid`로(3.8). (5) 종료 코드 0·1·2, `--keep`, `--clean`(3.8). (6) init이 저장소의 호스트 경로를 자기 `/repo` 바인드에서 얻음(3.2). (7) 재시작 정책 없음(3.6). (8) healthcheck(3.2). (9) 실행기의 8081, e2e 프로젝트 이름, `down -v` 전 `--clean`(3.6, 3.9). (10) `.gitattributes`의 LF 고정(3.7). (11) agent의 두 긴 문법 바인드에 `create_host_path: true`(검증 1회차 뒤, 3.3).

## 4. 실제 ANF와 다른 점

해당 없음(ANF 기능이 아니다). 대신 면접에서 물을 만한 것, 즉 **이 배치의 한계**를 모은다.

| 항목 | 한계 | 이유와 대응 |
| --- | --- | --- |
| 단일 호스트, host 네트워크 | 모든 서비스가 한 Linux 호스트의 host 네트워크에 있다. 서비스 사이의 네트워크 격리가 없고, 여러 노드로 나눌 수 없다 | localhost 바인딩이 보안 경계다(D-13). 데이터 플레인(VG, 커널 knfsd, 마운트)이 원래 호스트 하나에 묶여 있다 |
| 특권 | agent와 init은 호스트 root와 같다. docker 그룹 사용자도 root와 같다 | 커널·LVM·마운트·다른 netns를 다루는 일이라 피할 수 없다. 특권은 이 둘에만 두고, anf-api는 uid 1000이다 (3.3) |
| Docker 소켓 | agent가 호스트 dockerd를 마음대로 쓴다 | 볼륨 인스턴스를 띄우는 방법이 Docker다(D-12). 더 좁히려면 인스턴스를 띄우는 방법 자체를 바꿔야 한다 |
| 재시작 정책 없음 | WSL을 다시 시작하면 스택이 저절로 뜨지 않는다. 같은 명령을 다시 돌려야 한다. WSL 배포판이 유휴 종료되면 스택도 함께 내려간다(검증 1회차에서 실제로 일어남, 볼륨이 없을 때). 볼륨이 있을 때 그렇게 되면 인스턴스도 멈춰 클라이언트 I/O가 끊긴다(verifier의 설명, 관찰하지 않음) | 정책으로 agent가 init보다 먼저 뜨면 P1으로 실패한다 (3.6). README의 "After a WSL restart, run the same command again"으로 돌아왔다 |
| 새 기기 첫 실행 | `create_host_path`는 같은 모양의 다른 경로(`/var/tmp/fr13-fresh`)로만 확인했다. 실제 `/var/lib/anf-clone`을 지운 새 기기, 그리고 agent가 aggregate를 처음 만드는 경로(`ensure_aggregate`: `ns` mkdir, 희소 파일, `vgcreate`)는 이번에 돌리지 않았다 | 실제 데이터 플레인 디렉터리는 지울 수 없었다. 단위 테스트가 옵션을 지킨다 (3.3) |
| WSL 전제 | 개발과 실측은 WSL2 Ubuntu 24.04다. README는 "또는 `nfsd`·`dm-thin` 모듈이 있는 다른 Linux 호스트"라고 적는다 | `/`가 shared인 호스트는 init·agent가 bind → private → rshared 순서로 다룬다(3.4). GitHub 러너에서의 결과는 검증(AC-09)이 본다 |
| 테스트와 동시에 못 돈다 | 스택과 데이터 플레인 테스트가 포트 8080·8081·8090·9090과 VG·IP 대역을 같이 쓴다 | 실행기가 포트가 차 있으면 2로 끝나고 스택을 내리라고 안내한다. README도 "테스트 전에 내린다"를 적는다(`README.md:75-77`) |
| `down -v` | anf-api 상태를 지워, 리소스가 남아 있으면 LV·인스턴스가 기록 없이 남는다 | README 경고, 데모의 `--clean`, e2e의 순서 (3.6) |
| LVM 메타데이터 백업 | 컨테이너의 `/etc/lvm/archive`·`backup`은 컨테이너와 함께 사라지고 호스트 백업은 갱신되지 않는다 | 결정 14: 바인드하지 않는다. 호스트의 `/etc/lvm`을 바인드하면 호스트 LVM 설정까지 컨테이너에 묶이고, 이 클론에는 `vgcfgrestore`로 복구하는 시나리오가 없다 (3.5) |
| 다시 실행하면 서비스 재생성 | `--build`의 provenance 때문에 네 서비스가 매번 다시 만들어진다 | 결정 13. 리소스·데이터·인스턴스는 그대로다 (3.7) |
| Kubernetes가 아니다 | compose 하나, 노드 하나다. 클론을 Kubernetes에서 돌리지도, Kubernetes 워크로드에 볼륨을 주지도 않는다 | Kubernetes가 PVC로 볼륨을 받는 CSI 드라이버(FR-14)는 선택이다. PRD는 그것을 NetApp Trident가 Kubernetes를 ANF에 연결하는 자리에 놓는다 |
| 데모의 처리량 판정 | 한도에 얼마나 가까운지(아래쪽)는 판정하지 않고, 천장과 "따라 바뀜"만 본다. 그래서 tc가 한도보다 낮게 걸리는 오차는 안내 줄만 낸다. 천장의 I/O 하나 여유는 계산과 [추론]에 기댄다(완료 시각을 보지 않았다). 거짓 실패가 남은 곳: 내리기 전 20 MiB/s 세 회가 **모두** 5.217 이하일 때(수정 뒤 20회에서 가장 빠른 회의 최저는 16.14), 그리고 내린 뒤 세 회 중 두 회 이상이 5.05를 넘을 때(내린 뒤 쪽에는 I/O 여유가 없다. 수정 뒤 5 MiB/s 측정 60회 중 5.05 초과는 3회였고 한 데모 안에서 두 번 나온 적은 없다). 내리기 전을 가장 빠른 회로 바꾼 `814afb1`은 실환경에서 다시 돌리지 않았다. 서버 쪽 쓰기 멈춤의 원인은 확인하지 못했다 | 데모는 보여 주는 대본이고, 정확도(90~101%)의 수락 판정은 FR-08의 데이터 시험(5회 중앙값)이 한다. 단위 테스트가 한도 짝의 여유(81%)를 고정한다. 새 판정의 첫 실제 실행은 PR의 CI `rest` 조각이다 (3.8) |

## 5. 검증

수락 기준은 설계 §5의 AC-01~AC-11이다.
- AC-01: WSL을 다시 시작한 직후, sudo 없이 docker 그룹 사용자가 문서의 명령 하나를 그대로 실행하면 네 서비스가 healthy가 된다. 걸린 시간을 기록한다.
- AC-02: 같은 명령을 다시 실행해도 리소스·데이터·볼륨 인스턴스가 바뀌지 않는다(서비스 컨테이너는 다시 만들어질 수 있다). 볼륨이 있는 채 `down` → 클라이언트 I/O 계속 → `up` → agent가 복구하고 API가 같은 리소스를 보인다.
- AC-03: `python3 scripts/demo.py`가 root 없이 1~7단계를 끝내고 0으로 끝난다. 단계마다 클라이언트에서 관찰한 근거가 있고, 끝난 뒤 남은 것이 없으며, 3분 안이다.
- AC-04: 스택이 없으면 코드 2, 단계가 어긋나면 0이 아닌 코드와 단계 표시.
- AC-05: Windows 브라우저(headless Chrome 포함)로 `http://127.0.0.1:8081/?subscription=<id>`를 열면 리소스 트리와 볼륨 차트가 보인다.
- AC-06: agent 컨테이너를 쓰는 중에 `docker kill`해도 쓰기 오류 0, 다시 뜨면 볼륨·스냅샷·한도가 그대로, 되돌리기·삭제가 성공한다.
- AC-07: 데모 동안 WSL 사용 메모리가 7 GB 안이다(NFR-06).
- AC-08: 스택이 떠 있으면 실행기가 2로 끝나고, 내리고 치운 뒤에는 사전 점검을 통과하고 남은 것이 없다.
- AC-09: PR의 CI에서 backend·frontend·`data-plane` 두 조각이 통과한다.
- AC-10: WSL `-m "not dataplane"` 통과·skip 0, ruff, 프런트엔드 typecheck·test·build.
- AC-11: README의 명령과 주소가 검증에서 그대로 쓴 것과 같다.

**검증 1회차 전에 이미 확인된 것.** 아래는 판정이 아니라 판정의 재료다(진행 기록, 설계 §7, ADR §5).
- implementer의 compose e2e 단독 실행: 5 passed, 252 s, 출력 `/var/tmp/anf-clone-tests/fr13-compose-222653`. 이 실행은 `down` 창 동안의 쓰기 오류 0(AC-02)과 agent kill 동안의 쓰기 오류 0(AC-06)을 단언한다.
- 데모 85 s(목표 180 s 안). 데모 동안 메모리 used 최대 1,095 MiB(agent 96, anf-api 60, Prometheus 38, 대시보드 12 MiB). WSL 전체는 약 7,778 MiB다(S9 환경).
- 일반 사용자의 `up`은 첫 빌드 포함 62 s, 그 뒤 약 10 s.
- L4(`/run/udev:ro` + `ipc: host`)로 바꾼 뒤 데모 6회 모두 5단계 통과 (3.5).

**검증 1회차 뒤 수정의 확인 (implementer, 판정 아님).** 자세한 내용은 3.3과 3.8에 있다.
- 데모 6단계: 수정 확인 10회. "회마다 101%" 천장에서 07회가 5 MiB/s의 5.12(102.4%)로 실패했고, 10회차의 20 MiB/s 한 회가 7.22(36%)였다(안내가 붙고 통과). I/O 하나의 여유를 더한 뒤, 그 10회의 측정값 60개를 새 판정에 다시 넣자 10회 모두 통과했다(`/var/tmp/anf-clone-tests/fr13-demo-repeat/rejudge.txt`).
- `create_host_path`: 같은 모양의 경로 `/var/tmp/fr13-fresh`로 HEAD의 실패(만들기 rc 1)를 재현하고, 수정본에서 경로가 없을 때와 빈 `ns`만 있을 때 모두 `up` rc 0을 봤다.
- verifier가 낸 재검증 기준은 관찰된 실패율 3/10에서 나온 "데모 10회 연속 `exit 0`"이다(검증 보고서 AC-03).

**검증 결과.** 1회차의 대상은 `01ab88e`, 2회차의 대상은 `4887031`이다(제품 코드 내용 해시는 둘 다 `7c38d8c7…`). 보고서: `_workspace/containers/04_verifier_report.md`(1회차), `04_verifier_report_r2.md`(2회차). 2회차는 긴 실행을 다시 돌리지 않고 실행 기록으로 판정했다.

| 기준 | 결과 | 근거 |
| --- | --- | --- |
| AC-01 명령 하나 | PASS | 1회차: WSL 재시작 직후 일반 사용자로 README 명령 그대로 3번, 8.8~10.4 s에 네 서비스 healthy. 2회차: `create_host_path`가 든 compose로 `up` rc 0(9.26 s, 10.41 s) |
| AC-02 다시 실행, `down`/`up` | PASS | 다시 실행 9.57 s, `down` 0.9 s, 다시 `up` 8.87 s. API가 같은 리소스를 보이고 인스턴스 ID가 같다. 시험 동안 쓰기 163회(그중 55회가 11.74 s의 `down` 창 안), 오류 0 |
| AC-03 데모 | 1회차 FAIL → 2회차 PASS | 1회차: 10회 중 3회가 6단계의 아래쪽 판정(10 MiB/s 중앙값 72~82%)으로 `exit 1`. 한도를 넘은 회는 없었다. 2회차: `4887031`로 데모 10회 연속 `exit 0`(e2e 안의 2회 + 8회 반복), 79~103 s. 스토리지가 느린 회(중앙값 84%, 36%)는 안내만 붙고 통과했고, 5 MiB/s에서 5.15·5.1이 나온 회는 새 천장(5.217) 안이었다 |
| AC-04 종료 코드 | PASS | 스택이 없으면 2, 단계가 어긋나면 1과 단계 표시(1회차 실측, 단위 테스트). 07회의 `exit 1`이 실제 실패 예다 |
| AC-05 대시보드 | PASS (headless Chrome) | Windows Chrome headless로 `http://127.0.0.1:8081/?subscription=…`을 열어 트리와 볼륨 차트를 봤다. Chrome 확장 프로그램은 연결돼 있지 않았다 |
| AC-06 agent kill | PASS | 쓰는 중 `docker kill` 뒤 다시 띄움: 쓰기 오류 0(v3 274회, v4.1 87회), tc가 한도와 맞음, 되돌리기 `Succeeded`, 삭제 성공 |
| AC-07 메모리 | PASS | 데모 동안 used 최대 1,018~1,224 MiB (7 GiB 한도) |
| AC-08 실행기와 정리 | PASS | 스택이 떠 있으면 실행기 exit 2. 내리고 치운 뒤 사전 점검 통과, 남은 것 없음 |
| AC-09 CI | PR에서 확인 | backend·frontend·`data-plane` 두 조각의 통과가 merge 조건이다. compose e2e는 `rest` 조각에서 돈다 |
| AC-10 회귀 | PASS | WSL `-m "not dataplane"` 통과·skip 0(1회차), 바뀐 테스트 파일과 ruff(2회차), 프런트엔드 typecheck·test·build |
| AC-11 README | PASS | 명령·주소·6단계 설명이 검증에서 쓴 것과 같다 |

**2회차 뒤에 바뀐 것 (`814afb1`, 실환경에서 다시 돌리지 않음).** 2회차의 8회 반복에서 20 MiB/s 세 회가 `16.14, 5.93, 7.25`(중앙값 7.25)인 회가 나왔다. 그때의 "따라 바뀜"은 내리기 전 **중앙값**이 5.05를 넘어야 했으므로 여유가 2.2 MiB/s뿐이었다. verifier의 지적에 따라 내리기 전 쪽을 **가장 빠른 회**가 새 한도의 천장(5.217)을 넘는지로 바꿨다(3.8). 이 변경의 근거는 단위 테스트와, 수정 뒤 실제로 돈 데모 20회(10 + 8 + e2e 2)의 측정값을 새 판정에 다시 넣은 결과(20회 모두 통과, `/var/tmp/fr13-demo-repeat-head/rejudge-max.txt`)다. 새 판정으로 데모가 실제로 도는 것은 PR의 CI `rest` 조각이 처음이다.

판정 밖 관찰: `/var/lib/anf-clone`이 없는 새 기기에서 compose가 실패하던 것은 `create_host_path`로 고쳤지만, 같은 모양의 다른 경로로만 시험했다(3.3). 스토리지가 느린 측정은 한 데모 안에서 몰려 나온다(8회차의 세 회 중 둘이 5.93, 7.25).

**스파이크, 구현, 수정에서 시험하지 않은 것.** 판정과 무관하게 남는 것이다.
- agent 설정 중 `privileged`, `network_mode: host`, `/dev`, `/lib/modules`, Docker 소켓은 하나씩 빼 보지 않았다(3.3 표).
- L2의 mount 경합은 15회 탐침으로 다시 만들지 못했다. L4가 경합을 없앴다는 근거는 원인 분석과 데모 6회 통과다.
- 데모 처리량이 가끔 크게 떨어지는 원인(서버 쪽 쓰기 멈춤으로 봄)은 확인하지 않았다. verifier는 조사 방법으로 실패 때 `/proc/meminfo`의 Dirty·Writeback, `/proc/pressure/io`, 호스트 `iostat`을 함께 남기기를 제안했다(검증 보고서 AC-03). 그 조사의 결과는 기록에 없다.
- 천장에 I/O 하나를 더한 근거인 "앞 회에서 밀린 완료 하나" 설명은 [추론]이다. 2회차 verifier의 "창에 N개 또는 N+1개" 설명도 계산이다. 어느 쪽도 fio의 완료 시각을 보지 않았다.
- `814afb1`의 "따라 바뀜"(내리기 전 가장 빠른 회 > 5.217)은 실환경에서 돌리지 않았다. 근거는 단위 테스트와 실측 20회의 재판정(20/20)이다.
- `create_host_path`: 실제 `/var/lib/anf-clone`을 지운 새 기기와, agent가 aggregate를 처음 만드는 경로(`ensure_aggregate`: `ns` mkdir, 희소 파일, `vgcreate`)는 돌리지 않았다 (3.3).
- LVM 메타데이터 백업은 결정 14로 남기지 않는다. 그 백업으로 복구하는 경로(`vgcfgrestore`)는 시험 대상이 아니다.

## 6. 개발 과정

1. **조사: 생략.** PRD §8에 따라 FR-13은 조사를 거치지 않는다.
2. **스파이크 S9 (2026-11-10).** FR-12의 CI를 기다리는 동안 feature-implementer가 실험 이미지 넷(agent, anf-api, 대시보드 nginx, vite preview)을 빌드했다. 이 기기에 compose가 없어서 같은 구성을 `docker run` 스크립트로 흉내 냈고, 데모 대본 1~6단계를 일반 사용자로 돌렸다(62.1 s). 판정은 조건부 통과였다. 조건 둘: (1) 이 기기에 compose가 없다(`docker compose`도 `docker-compose`도 없고 buildx도 없음. GitHub 러너에는 Compose 2.38.2가 있다). (2) agent 컨테이너는 설정이 모두 있어야 하고, 빠지면 시작 실패(P2, P4), 인스턴스 기동 실패(P1), 재시작 뒤 되돌리기 실패와 호스트 디렉터리 오염(P3), `lvcreate` 무한 대기(L3)가 생긴다. 제품 코드는 바꾸지 않았다.
3. **사람이 내린 결정 (사용자, 2026-11-10).** WSL Ubuntu에 `docker-compose-v2`와 `docker-buildx`를 apt로 설치한다. 메인 세션이 설치했다(Compose 2.40.3, buildx 0.30.1). S9가 사용자에게 물을 것으로 남긴 나머지 둘(`down`에서 인스턴스를 멈출지, agent를 특권 컨테이너로 둘지)은 설계에서 자동 채택으로 정했다(결정 4, 3).
4. **설계.** 결정 1~12 자동 채택, 수락 기준 AC-01~AC-11.
5. **구현 (같은 implementer, S9부터 이어서).** 커밋 `27b8696`(compose 스택), `ab03418`(agent LVM이 호스트 udev를 기다림), `53f7c8b`·`c99a400`(`scripts/demo.py`), `d2388b1`(compose e2e, 실행기 8081, README), `01ab88e`(`docs/testing.md`의 테스트 수). 구현 중 실패와 수정:
   - S9가 고른 L2로 데모 5단계가 실패 → L4로 바꾸고 단위 테스트가 둘을 함께 요구(3.5).
   - 같은 명령을 다시 돌리면 서비스 넷이 재생성됨 → 원인(provenance)을 찾고 우회 셋을 시험한 뒤 메인에 결정을 넘김 → 결정 13(3.7).
   - 데모 처리량이 68%, 38%로 떨어진 회가 있음 → 한도를 10 → 5로 낮추고 3회 중앙값(90~101%)과 천장으로 판정(3.8. 검증 1회차와 2회차 뒤 다시 바뀜, 8·10단계).
   - 데모의 Prometheus 판정이 이전 실행의 같은 이름 볼륨을 봄 → `volume_uuid`로 고름(3.8).
   - e2e의 `down -v`가 리소스가 남은 채 anf-api 상태를 지움 → `--clean`을 먼저, 프로젝트 이름 분리, README 경고(3.6, 3.9).
   - `.dockerignore`의 CRLF → `.gitattributes`로 LF 고정(3.7).
   제품 코드(`backend/`)는 바꾸지 않았다.
6. **결정 13·14 (메인 세션 자동 채택).** 13: `--build`를 두고 AC-02를 "리소스·데이터·인스턴스가 바뀌지 않는다"로 고쳤다. 14: 개념 문서 1판을 쓰는 단계에서, 컨테이너 안의 LVM 메타데이터 백업을 바인드하지 않고 한계로 적기로 했다(진행 기록 단계 5).
7. **실환경 검증 1회차 (real-env-verifier, 대상 `01ab88e`).** PASS 9 / FAIL 1 / UNVERIFIED 0. AC-09(PR의 CI)는 PR 뒤에 메인이 채운다.
   - AC-01: WSL을 다시 시작한 직후 일반 사용자로 README 명령을 그대로 세 번 돌려 8.8~10.4 s에 healthy였다(셋째는 VM까지 다시 부팅한 직후). AC-05는 headless Chrome으로 봤다. AC-07은 데모 동안 최대 used 1,042 MiB였다(verifier의 e2e 재실행 안에서는 1,224 MiB). 통과한 데모는 81.9~88.5 s였다.
   - FAIL은 AC-03이다. 데모 10회 중 3회가 6단계의 아래쪽 판정(10 MiB/s 중앙값 72~82%)으로 `exit 1`이었다. 한도를 넘은 회는 없었고 tc와 `anf_qos`는 맞았다(3.8). verifier는 고칠 방법 셋을 냈다. 아래쪽만 어긋날 때 한 번 더 재기, 판정을 천장 + "따라 바뀜"으로 바꾸고 정확도는 FR-08에 맡기기, 원인 조사.
   - 판정 밖 관찰 셋: (1) `/var/lib/anf-clone`이 없는 새 기기에서는 바인드 원본이 없어 명령이 실패할 것이다(장난감 compose로 재현), (2) 대시보드 nginx master가 uid 0이다, (3) 재시작 정책이 없어 WSL이 유휴 종료되면 스택도 내려간다.
8. **검증 1회차 뒤 수정 (메인 세션 자동 채택, 같은 implementer에 수정과 10회 반복을 맡김).**
   - 데모 6단계를 천장과 "따라 바뀜"으로 바꾸고 한도 짝을 20 → 5로 했다(커밋 `dcf18d7`, 3.8).
   - 수정 확인 10회에서 07회가 "회마다 101%" 천장에 걸렸다 → 천장에 1 MiB I/O 하나의 여유를 더했다(`85428ec`). 10회의 측정값 재판정은 10/10 통과였다. 같은 10회의 10회차에 나온 36%를 "한 회 최저"로 보고 한도 짝의 근거로 삼았는데(`4887031`), 이 전제는 2회차 동안 3.68(18%)로 틀렸다(10단계, 3.8).
   - 관찰 1을 고칠 대상으로 받아 두 긴 문법 바인드에 `create_host_path: true`를 더했다(`8c02910`). 같은 모양의 경로로 HEAD의 실패를 재현하고 수정본의 통과를 확인했다(3.3).
   - 문서: `9120af6`(README, `docs/testing.md`, 설계가 새 6단계와 `create_host_path`를 적음), `4887031`(천장의 I/O 하나와 새 최저 기록).
   - 관찰 2와 3은 바꾸지 않았다. 지금 코드에서도 대시보드 Dockerfile의 마지막 단계(`deploy/dashboard/Dockerfile:11`, `nginx:1.28.0-alpine`)에 `USER`가 없고, compose에 재시작 정책이 없다. verifier는 2를 "특권이 없고 127.0.0.1에만 열어 기준과 무관"으로, 3을 README의 "After a WSL restart, run the same command again"과 맞는 WSL 특성으로 적었다(4절 표).
   - 재검증 기준은 데모 10회 연속 `exit 0`이다. 결과는 5절에 있다.
9. **실환경 검증 2회차 (real-env-verifier, 대상 `4887031`).** 리더 지시로 스택·데모를 다시 돌리지 않고, implementer와 메인의 실행 기록과 읽기 전용 점검으로 판정했다. 처음에는 HEAD 코드로 돈 데모가 e2e 안의 2회뿐이라 AC-03이 UNVERIFIED였고, 메인이 HEAD로 데모 8회를 더 돌려(8/8 `exit 0`) PASS 10 / FAIL 0이 됐다(진행 기록, 5절 표). 판정 밖 관찰 가운데 이 문서와 관련된 것:
   - 관찰 1: "따라 바뀜"의 내리기 전 쪽 여유가 얇다. 8회 중 한 회가 `16.14, 5.93, 7.25`(중앙값 36%)였고, 한 회 최저는 3.68(18%)이었다. 그래서 코드 주석과 단위 테스트의 "한 회 최저 36%" 전제가 틀렸다. verifier는 셋 중 하나를 고르라고 제안했다. (a) 코드는 그대로 두고 한계로 기록, (b) 내리기 전 쪽을 `max(before) > ceiling(NEW_LIMIT)`으로, (c) 문턱 아래일 때만 다시 재기. verifier는 (b)를 권했다.
   - 관찰 2: `docs/testing.md`의 테스트 수가 실제(1,051)와 달랐다. 관찰 4: 이 문서의 커밋된 판이 지금 코드와 달랐다. 관찰 5: 데모 시간이 늘었다(HEAD 8회 89.94~103.04 s).
10. **검증 2회차 뒤 수정 (메인 세션 자동 채택, verifier 2회차 제안 (b)).** `follows_limit`의 내리기 전 쪽을 가장 빠른 회 > 새 한도의 천장(5.217)으로 바꾸고, 단위 테스트의 근거를 "가장 빠른 회의 최저 81%(16.14)"로 고쳤다(`814afb1`). 설계 §7-3에 이유를 적었다(`8732c9b`). 실측 20회를 새 판정에 다시 넣자 20/20 통과였다. 실환경에서 다시 돌리지는 않고 PR의 CI에 맡겼다(3.8).
11. **AI를 쓴 방식.** 스파이크, 구현, 검증, 이 문서를 Claude 에이전트(로드맵 총괄, implementer, verifier, 문서 작성)가 나눠 맡았다. 사람은 이 기기에 무엇을 설치할지를 정했다. implementer는 우회가 명령의 모양이나 수락 기준을 바꾸는 경우(`--build`), 고르지 않고 선택지와 측정값을 들고 메인에 돌아왔다. 판정 밖 관찰도 고칠 대상이 됐다(`create_host_path`). 실제 데이터 플레인 디렉터리는 지울 수 없어서, implementer는 같은 모양의 다른 경로로 실패 재현과 수정을 확인하고, 돌리지 않은 경로를 함께 적어 돌아왔다. 2회차에서 메인은 처음에 "따라 바뀜"을 그대로 두고 한계로 적을 생각이었다. verifier가 판정과 별도로 이견을 적었고(관찰 1), 메인이 그 제안 (b)를 채택했다.

---

## 7. Interview Q&A

### Q1. Why does your storage agent run as a privileged container, and is that safe?

**A.** It must be privileged because its job is host-level work. It attaches a loop device, builds LVM thin volumes through device-mapper, mounts ext4, enters other containers' network namespaces to set tc limits and iptables rules, and loads a kernel module. So the container is packaging, not isolation. It gives me a pinned image with the same LVM and iptables versions as the host, and one command to start and stop everything. But its power equals a root process on the host. The Docker group is the same: anyone who can start a privileged container is effectively root. I documented that instead of hiding it. The real protections are elsewhere: every service binds only to localhost, the agent runs commands without a shell, only the agent and a one-shot init service are privileged, and the API runs as UID 1000.

### Q2. What is mount propagation, and why did it matter when you containerized the agent?

**A.** Mount propagation decides whether a mount made under one mount point appears in other mount namespaces. Private shares nothing, shared copies mounts between peers, and slave only receives. My agent mounts every volume under a directory called ns, and each volume's NFS server container binds that directory as rslave. Once the agent itself ran in a container, its mounts happened in its own namespace, so they had to cross two boundaries: agent to host as shared peers, then host to each NFS container as slaves. Docker accepts a shared bind only if the host side is already a shared mount. So a one-shot init service makes the host directory a shared bind before the agent starts. Without that, the agent started, but the first volume failed because Docker rejected the NFS container's bind.

### Q3. Why does the agent need the host PID namespace?

**A.** Because the agent reaches each NFS server container through its process ID. Docker inspect returns the host PID. The agent runs nsenter with that PID to enter the container's network namespace, for the tc throughput limit and for iptables during a revert, and the metrics code reads per-namespace NFS server statistics from /proc of that PID. In a container with its own PID namespace, that PID does not exist. In the spike, startup recovery failed exactly there: nsenter could not open /proc/<pid>/ns/net. With pid host, the agent sees the same /proc as a host process, so I did not change product code. The init service uses host PID for a similar reason: nsenter to PID 1 must reach the host's systemd, not the container's own first process.

### Q4. What went wrong with LVM inside the container?

**A.** Two things, both about sharing host state. First, locking. When the agent attached the loop device, host udev auto-activated the volume group at the same moment as the agent's vgchange, and activation failed. LVM serializes through /run/lock/lvm, so I bind that directory from the host. Second, udev synchronization. With /run/udev mounted but a private IPC namespace, lvcreate hung for over four minutes, waiting on a udev cookie semaphore that host udev could not see. Without /run/udev it did not wait at all, and once in the demo, a mount right after lvcreate failed because the device node did not exist yet. The fix is both together: /run/udev read-only plus the host IPC namespace, so LVM waits for host udev like a host process. A unit test requires both.

### Q5. Tell me about a bug that only appeared when the agent container restarted.

**A.** At first I bound the agent's state directory recursively, which pulls in any mounts below it. On the first start nothing was mounted there, so everything worked. On a restart with volumes present, the recursive bind copied the host's volume and snapshot mounts into the container as private copies, under the shared bind. Then a revert failed. The agent unmounted the visible volume, but its mount check reads findmnt targets, so it still saw the hidden copy at the same path and skipped mounting the new volume. It even created the immutable .snapshot directory on the empty host directory, which later blocked deletion. The fix was a non-recursive bind plus a separate shared bind of ns. If I did it again, I would test restarts in the very first spike run.

### Q6. Why host networking and localhost binding, instead of a bridge network with published ports?

**A.** Because localhost is my security boundary, and the services already find each other there. The API has no authentication, much as ANF relies on ARM for tokens, so nothing may listen on an external interface. With host networking, the API reaches the agent at its default URL, Prometheus reuses the scrape configuration from the metrics feature unchanged, nginx proxies to 127.0.0.1, and a Windows browser reaches the dashboard through WSL's localhost forwarding. A unit test checks that no service publishes ports and that every server binds 127.0.0.1. NFS is the exception: each volume instance has its own IP on a Docker bridge network, because that IP is the volume's mount target and the throughput limit lives in that network namespace. The trade-off is no network isolation between stack services, and a single host.

### Q7. What is the risk of mounting the Docker socket into a container?

**A.** Whoever can talk to the Docker socket controls the host. They can start a privileged container with the host's filesystem and become root. So giving it to the agent is a deliberate grant, not a convenience. I need it because the agent starts one NFS server container per volume and inspects them for their PIDs, and the metrics code reads those PIDs through the Docker API. The init service also uses it to find the host path of its own repository bind. A useful side effect is that the NFS containers are siblings created by the host daemon, not children of the stack, so they live outside the compose project. That is why compose down leaves data service running. To shrink the risk, I would have to change how instances are launched, which I chose not to do for a single-host lab.

### Q8. Why do mounted clients keep working after `docker compose down`?

**A.** Because the data path never passes through the containers that compose manages. A client sends NFS to the volume's instance container on anf-vnet. That container's kernel NFS server reads the volume through a bind of the host's ns directory, and the ext4 file system sits on a thin LV. The API and the agent are only the control path: they create and change those objects. The agent starts instances through the host Docker daemon, so they are outside the project, and anf-vnet is an external network, so down removes neither. Host mounts stay because the agent's mounts had propagated to the host. In the end-to-end test, a client kept writing through a ten-second down window with zero errors. On up, the agent's startup recovery found everything in place, and the instances were not restarted.

### Q9. Why a multi-stage build for the dashboard, and why nginx instead of the Vite preview server?

**A.** For size, memory, and independence from Windows. The first stage uses a Node 22 image to run npm ci and the Vite build. The second stage is nginx with only the built files and one config file, so Node never ships, and WSL, which has no Node installed, can build the whole stack by itself. In the spike, the nginx image was 74 MB and used about 11 MiB, while a Vite preview container was 534 MB and 78 MiB. nginx also replaces the dev-server proxy: /subscriptions goes to the API unchanged, /prometheus/ goes to Prometheus with the prefix stripped, and other paths fall back to index.html for the single-page app. Same origin means the API needs no CORS. The agent image uses the same multi-stage trick to copy only the Docker CLI binary.

### Q10. How do health checks and startup order work in your stack?

**A.** Only one ordering matters: the agent starts only after init completes successfully, because Docker rejects the agent's shared bind until init has made the host directory a shared mount. Everything else starts in parallel. The API may start before the agent, since its storage client retries connections for sixty seconds. Each service has a health check that uses tools already in its image, Python urllib or wget. The agent's check is a real readiness signal, because its HTTP port opens only after startup recovery finishes. That can take minutes if NFS servers wait out a grace period, so the start period is 300 seconds. The wait flag makes the single command return only when all four services are healthy. I set no restart policy on purpose: after a WSL reboot, Docker could restart the agent before init, and it would fail.

### Q11. How does your demo script decide that the throughput limit works?

**A.** It judges the two things the scenario promises: the limit is a ceiling, and throughput follows a limit change. For each limit, 20 and then 5 MiB/s, a client container runs three six-second direct-I/O fio writes, and the script prints every run. No single run may exceed 101 percent of its limit plus one 1 MiB I/O over the window. After the PATCH, the median must be within 101 percent of 5 MiB/s, and before it, the fastest run must beat 5.217, a speed the new limit cannot produce. A run slower than the limit only gets a note. I used to fail medians below 90 percent, but 3 of 10 demos failed that way while tc was correct, so accuracy now belongs to the FR-08 data tests. The fastest-run rule has not run on real hardware yet; I checked it against twenty recorded demos.

### Q12. If you moved this stack to Kubernetes, what would change?

**A.** I have not built it, so this is a plan. The API, Prometheus, and dashboard map simply: Deployments, with a persistent volume for the API's SQLite file and one API replica, because its worker runs in-process. The agent is the hard part. It would be a privileged pod pinned to the storage node, with host PID and host network, host path mounts for the state directory, devices, LVM lock, and udev, and bidirectional mount propagation for ns. The bigger change is the Docker socket. The agent launches NFS server containers through Docker, and a Kubernetes node may not run a Docker daemon at all, so instances would probably become pods created through the Kubernetes API. That is separate from FR-14, the optional CSI driver, which lets Kubernetes workloads consume the clone's volumes, the place Trident takes for ANF.

### Q13. Why does re-running the same `up --build` command recreate your containers, and why did you accept that?

**A.** Because BuildKit attaches a provenance attestation to every build, with a timestamp and an invocation ID, so the image ID changes even when every layer is cached. Compose sees a new image and recreates four services. I tried build.provenance false in the compose file, but Compose 2.40.3 did not pass it through, and SOURCE_DATE_EPOCH did not help. The working options were an environment variable in front of the command, or dropping the build flag. I kept the flag, because a command that silently runs an old image after a code change is a worse trap. Instead I restated the acceptance criterion: resources, data, and volume instances must not change. The end-to-end test re-runs the command while a client writes and checks that the instance IDs and start times are unchanged.

### Q14. Why does the demo's throughput ceiling allow one extra I/O per run? Isn't that loosening the test?

**A.** Because one I/O is the resolution of the measurement. fio counts only the 1 MiB writes that finish inside the six-second window. At 5 MiB/s that is about thirty writes, so one write is 3.3 percent of the limit. In a ten-run check, one run read 5.12, or 102 percent, right after a run that read 4.76, which was low. The other 27 measurements at that limit were at most 4.97. My explanation is that one completion slipped from one window into the next, but I did not observe completion times, so it is an inference. The ceiling is now 5.217 at 5 MiB/s and 20.367 at 20, and a real overshoot such as 5.3 still fails. I rejected judging the three-run sum, still tight at 1.1 percent, a smaller block size, which changes the load, and a median upper bound, which hides one real overshoot.

### Q15. Why did you raise the demo's first limit from 10 to 20 MiB/s, and what changed after that?

**A.** To keep the "follows the limit" check from failing on slow storage. At first that check needed the median before the change above 5.05 MiB/s, 101 percent of the new limit. With a first limit of 10, that is 50.5 percent; with 20, 25 percent. I had seen a single run at 38 percent, so 10 was too tight. Then, in the second verification, one demo measured 16.14, 5.93, and 7.25 at 20, a median of 36 percent, and another had a single run at 18 percent. Slow runs cluster within one demo, so the margin was thinner than it looked. Now the check uses the fastest run before the change, which must beat 5.217, the new limit's ceiling. Across twenty recorded demos, the lowest fastest run was 16.14, 81 percent. A unit test pins that number, which I copied by hand from the records.

### Q16. Tell me about a bug that would only show up on a fresh machine.

**A.** The stack would not start on a machine that had never run the clone. Compose creates every container before it starts the one-shot init service. The agent's two binds use the long syntax, which rejects a missing source path at creation; the short syntax creates it by default. My machine had /var/lib/anf-clone from earlier features, so nobody saw it until the verifier reproduced it with a toy compose project. The fix is create_host_path on both binds, plus a unit test. I could not delete the real directory, so the check used a same-shaped path: the old file failed with "bind source path does not exist", the new one came up, init's mkdir created the path, and a probe in the agent's container saw its mount reach the host. I have not tried a truly new machine or the agent's first aggregate creation, so I say exactly that.
