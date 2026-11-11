# 컨테이너 (FR-13) 검증 보고서 — 1회차

- 진행 상태: 완료 (2026-11-10 14:44~15:20 PST)
- 검증일: 2026-11-10
- 검증 대상 코드:
  - 시작 커밋 `01ab88ee10c8ea5254f1f45fc08d734841dda98f` (`feature/containers`). 검증 중에 메인이 `f5260a6`(CLAUDE.md, ADR, `_workspace`)과 `7cc13c1`(`docs/concepts/containers.md`)을 커밋해 끝날 때 HEAD는 `7cc13c194b176c6cd3cb450c4a07227474010476`. `01ab88e..HEAD`의 변경은 `CLAUDE.md`, `docs/ADR.md`, `docs/concepts/containers.md`, `_workspace/containers/*`뿐이라 검증 대상 코드는 그대로다. 미커밋: 이 보고서, 추적 안 함 `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`(이 기능과 무관, 건드리지 않음)
  - 제품 코드 내용 해시: 시작·끝 모두 `7c38d8c7fdf750e4a4c32b06802475b0a5e3e2632ea1f60da9e7ac89ac2df4ed`
  - FR-13 참고 해시(pyproject, backend(테스트 제외), deploy, scripts, .dockerignore, .gitattributes): 시작·끝 모두 `c32b76d8db5425bbd661f42406b7dcf52bd932a17240c27fad194dd726508f0f` (implementer 값과 같음)
  - 경로별 마지막 커밋: `deploy/` `ab03418`, `scripts/demo.py` `c99a400`, `scripts/run-dataplane-tests.sh` `d2388b1`, `scripts/setup-wsl-dataplane.sh` `a21541f`, `README.md` `d2388b1`, `.dockerignore` `27b8696`, `.gitattributes` `53f7c8b`, `frontend/` `e7d87d5`
- 이번 회차 범위: 전체 (AC-01~AC-11, AC-09는 메인이 PR 뒤 채움). 사용자 합의로 긴 실행(WSL 전체 묶음, 30분 넘는 실행)은 하지 않는다

## 환경 사전 점검

시작 때(2026-11-10 14:44 PST, WSL은 꺼져 있다가 이 점검으로 부팅, `/proc/uptime` 10 s) root로 읽기만 했다.

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`: Ubuntu `Stopped`(다른 세션이 쓰지 않음), docker-desktop·kali-linux도 `Stopped` |
| Docker Engine | `docker version` 서버 29.1.3 `linux`, `readlink /usr/bin/docker` 비어 있음(rc 1, Desktop 연동 아님). Compose 2.40.3, buildx 0.30.1 |
| 데이터 플레인 비어 있음 | 컨테이너 0개, 이름 있는 볼륨 0개, 포트 8080·8081·8090·9090 비어 있음, loop 장치 없음(VG `anf` 안 붙음), `ns`는 마운트 지점 아님 |
| 커널 모듈·sysctl | `nfsd`만 로드(배포판 부팅 때 nfs-server가 올림), `dm_thin_pool`·`ifb` 없음. `fs.leases-enable = 0`(`/etc/sysctl.d`로 부팅 때 적용) |
| 이미지 | `anf-clone-agent`·`anf-clone-api`·`anf-clone-dashboard`·`anf-nfs-server`·`anf-nfs-client` `latest`(13:42 PST 빌드), `prom/prometheus:v3.15.1` |
| 일반 사용자 | `mkimhome1`(uid 1000), `docker` 그룹(1001). sudo는 암호가 필요해 쓰지 않음 |
| implementer e2e 기록 | `/var/tmp/anf-clone-tests/fr13-compose-222653/` 있음. 보관 사본 `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\impl-e2e-222653\`(jsonl sha256 `265fabe2…` 원본과 같음) |
| 브라우저 | Claude in Chrome 연결 안 됨(`tabs_context_mcp` → "Browser extension is not connected", `list_connected_browsers` → `[]`). Windows의 Chrome 157.0.8103.50을 headless로 썼다(AC-05) |
| 사용한 도구 | Bash(Git Bash → `wsl`), PowerShell, Read·Write·Edit·Grep·Glob, Node 22.14(DevTools 스크립트), uv 캐시의 ruff 0.14.0. 기기에 새로 설치한 것 없음 |

## 결과 요약

PASS 9 / FAIL 1 / UNVERIFIED 0 (AC-09는 메인이 PR 뒤 채움)

- FAIL: AC-03 — 데모가 10회 중 3회 6단계(10 MiB/s 쓰기 처리량의 중앙값이 한도의 72~82%)에서 `exit 1`. 같은 원인으로 내 e2e 재실행도 `1 failed, 4 passed`. 한도는 천장으로 지켜졌고(어느 회도 101% 초과 없음) tc 설정도 맞다 — 측정 흔들림을 데모의 아래쪽 판정이 실패로 만든다. `scripts/demo.py:43-51`, `:100-106`.
- 판정 밖 관찰 1(새 기기에서 `/var/lib/anf-clone`가 없으면 README 명령이 바인드 원본 없음으로 실패, `deploy/compose.yaml:43-52`)은 수정이 필요해 보이지만 이번 기준 밖이다.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1 |
| AC-02 | PASS | 1 |
| AC-03 | FAIL (간헐, 3/10) | 1 |
| AC-04 | PASS | 1 |
| AC-05 | PASS (headless Chrome) | 1 |
| AC-06 | PASS | 1 |
| AC-07 | PASS | 1 |
| AC-08 | PASS | 1 |
| AC-09 | 메인이 채움 | — |
| AC-10 | PASS | 1 |
| AC-11 | PASS | 1 |

## 항목별 결과

### [PASS] AC-01 WSL 재시작 직후 일반 사용자로 명령 하나 (상태 전이·데이터 효과의 전제)

- 기준: WSL을 다시 시작한 직후, sudo 없이 docker 그룹 사용자로 README의 명령을 그대로 실행하면 네 서비스가 healthy(`--wait` 0). 걸린 시간 기록. `init`이 호스트 준비를 실제로 한다.
- 실행한 명령(일반 사용자 `mkimhome1`, `wsl -d Ubuntu -e bash -c`, sudo 없음). 명령 앞의 읽기 전용 탐침 뒤에 README의 줄을 글자 그대로:
  `cd /mnt/c/Users/mkimh/Projects/ANF-clone && docker compose -f deploy/compose.yaml up -d --build --wait`
- 1회(`wsl --terminate Ubuntu` 뒤 첫 명령, 14:46 PST): 탐침 — `nfsd`만 로드, `dm_thin_pool`·`ifb` 없음, `ns: not a mount point`, loop 장치 없음. 결과 `rc=0 elapsed_s=10.44`(이미지 있음, 빌드 단계 모두 `CACHED`). compose 출력의 끝: `anf-clone-dashboard-1 Healthy`, `anf-clone-init-1 Exited`, `anf-clone-anf-api-1 Healthy`, `anf-clone-prometheus-1 Healthy`, `anf-clone-storage-agent-1 Healthy`. 원본: `…\scratchpad\ac01-up.txt`.
  - 주의: 이때 커널(VM)은 다시 부팅되지 않았다(`/proc/uptime` 111 s — 사전 점검이 VM을 깨운 뒤 terminate까지 VM 유휴 종료 시간이 지나지 않았다). 그러나 사전 점검부터 이 명령 전까지 호스트 준비를 한 것이 없어서 loop·dm·`dm_thin_pool`·`ns` 바인드가 모두 없는 상태였다(위 탐침).
  - 명령 직후 `init`의 효과(root로 확인): `dm_thin_pool`·`dm_persistent_data`·`ifb` 로드, `fs.leases-enable = 0`, `/dev/loop0`(aggr0.img), VG `anf` 활성·`aggr0` `twi-aotz--`, `anf-vnet` 172.30.0.0/24 ip-range /25, `init exit=0`(1.8 s), 로그 `data plane ready: images anf-nfs-server, anf-nfs-client; network anf-vnet …; NFSv4 delegations off` / `init: /var/lib/anf-clone/ns shared`. VG를 붙인 것은 `init`이 아니라 agent의 시작 복구다(`backend/storage_agent/flexvol.py:177-186`, loop의 backing file이 agent 컨테이너 기준 경로 `/aggr0.img`로 보인다).
- 2회(배포판 재시작 직후, 14:47 PST): 1회 직후 내가 keepalive 세션을 늦게 붙여 배포판이 유휴 종료됐다(PID 1 경과 43 s, 스택 컨테이너 넷 모두 `Exited`, 재시작 정책 없음 — 설계 §7.7). 그 상태에서 같은 명령을 다시 실행: 탐침 `ns: not a mount point` → `rc=0 elapsed_s=8.82`, 네 서비스 `Recreate` 뒤 `Healthy`. 원본 `…\scratchpad\ac01-up-run2.txt`. 이 회의 커널은 1회 그대로라 loop·dm은 남아 있었다(1회 뒤 VG가 붙은 채). 직후 호스트에서 `findmnt --mountpoint /var/lib/anf-clone/ns` → `/dev/sdd[/var/lib/anf-clone/ns] shared`. `compose ps`: `anf-api running healthy`, `dashboard running healthy`, `init exited 0`, `prometheus running healthy`, `storage-agent running healthy`. "After a WSL restart, run the same command again"(README)이 실제로 그대로 된다.
- 3회(VM까지 다시 부팅한 직후, 15:14 PST): `wsl --terminate Ubuntu` 뒤 100 s 기다려 VM이 유휴 종료되게 했다. 첫 명령의 탐침 `vm_uptime=7.53 distro_pid1_etimes=4`(커널 새로 부팅), `nfsd`만 로드, `ns: not a mount point`, `loop: 0 devices` → README 명령 `rc=0 elapsed_s=10.2`, `anf-api running healthy`, `dashboard running healthy`, `init exited 0`, `prometheus running healthy`, `storage-agent running healthy`. 직후 `dm_thin_pool`·`ifb` 로드, `/var/lib/anf-clone/ns shared`, `/dev/loop0 (/var/lib/anf-clone/aggr0.img)`. 원본 `…\scratchpad\ac01-up-run3.txt`. 이어서 데모 1회 `exit 0, 87.29 s`(AC-03 표 10회).
- 바인딩과 권한(2회 뒤, `ss -Hltnp`, `docker inspect`, `/proc/<pid>/status`):
  - 네 포트 모두 `127.0.0.1`에만: `127.0.0.1:8080` python, `127.0.0.1:8081` nginx, `127.0.0.1:8090` python, `127.0.0.1:9090` prometheus.
  - anf-api: `Config.User=anf`, 프로세스 uid 1000, `docker exec … id` → `uid=1000(anf)`, privileged false. agent: uid 0, privileged, host net·pid, IPC·PID 네임스페이스가 호스트 PID 1과 같다(`ipc:[4026532199]`, `pid:[4026532226]`), 마운트 `/run/udev` ro, `/run/lock/lvm`, `/var/lib/anf-clone`, `/var/lib/anf-clone/ns` `shared:305`. Prometheus uid 65534(nobody). 대시보드 nginx master uid 0(판정 밖 관찰 1).
- 처음 빌드할 때의 시간: 이번 회차에서 이미지 캐시를 지우고 재지 않았다. implementer 기록(진행 기록 `00_progress.md`: "일반 사용자 첫 빌드 62 s·이후 약 10 s")을 그대로 옮긴다. 판정은 이미지가 있을 때의 세 회(10.44 s, 8.82 s, 10.2 s)로 한다.
- implementer e2e(`fr13-compose-222653`, `up` 태그): `rc 0, 9.89 s`, 서비스 넷 `running healthy`, `init exited 0`, 포트 넷 `127.0.0.1:<port>`.

### [PASS] AC-02 다시 실행과 down → up (상태 전이·데이터 효과)

- 기준: 같은 명령을 다시 실행해도 리소스·데이터·볼륨 인스턴스가 바뀌지 않는다(스택 서비스 컨테이너는 다시 만들어질 수 있다, 결정 13). 볼륨이 있는 상태에서 `down` → 클라이언트 I/O 계속 → `up` → agent가 볼륨을 복구하고 API가 같은 리소스를 보인다.
- 손으로 확인(일반 사용자, `demo.py --keep`이 남긴 볼륨 셋·스냅샷·클라이언트 둘, 스크립트 `…\scratchpad\ac02.sh`, 출력 `…\scratchpad\verify\ac02-manual.txt`). `anf-demo-client-1`이 `/v41/continuity`에 1 MiB direct 쓰기를 멈추지 않고 되풀이하는 동안:
  - README 명령 다시 실행: `rc=0 seconds=11.39`. `prometheus` `Running`, `anf-api`·`dashboard`·`init`·`storage-agent` `Recreate`(결정 13의 예상대로). 볼륨 인스턴스 셋 컨테이너 ID 그대로.
  - README의 `docker compose -f deploy/compose.yaml down`: `rc=0 0.89 s`, `8080:closed 8081:closed 8090:closed 9090:closed`, 인스턴스 셋 그대로 running. 그동안 `anf-demo-client-2`가 `/r/written-while-down.txt`를 쓰고 읽음(`during-down`).
  - 10 s 뒤 같은 명령으로 `up`: `rc=0 8.68 s`, 네 서비스 `Healthy`.
  - 비교: API 볼륨 목록(이름·상태·마운트 IP·한도·fileSystemId)과 스냅샷 목록 `diff` 없음, 인스턴스 `diff` 없음, 클라이언트의 파일 md5(`/v3/hello.txt`, `/v41/hello.txt`, `/r/hello.txt` `ffb57ea7…`, `/r/only-in-restored.txt` `9cd599a3…`) 같음. 쓰기 `writes=170 errors=0 writes_while_down=53 (window 11.1 s) max_gap_s=0.28`.
  - 인스턴스 `StartedAt` 23:00:56·23:00:59·23:01:12Z(데모가 만든 때), `RestartCount 0` — agent가 23:03:43Z에 다시 뜬 뒤에도 인스턴스는 재시작되지 않았다.
- implementer e2e(`rerun`·`down`·`up-again` 태그): 다시 실행 `rc 0 11.4 s`, 다시 만들어진 넷 같음, 인스턴스 그대로, down 동안 쓰기 47회 오류 0, `after == before`.

### [FAIL] AC-03 데모 대본 1~7단계 (API 계약·상태 전이·데이터 효과) — 간헐, 10회 중 3회 6단계 실패

- 판정 이유: 대본이 동작하는 것은 보였으나(아래 첫 실행 출력), 이번 회차에 10회 돌려(손으로 8회 + 내 e2e 재실행 안의 2회) 3회(30%)가 6단계 판정으로 `exit=1`이었다. PRD §9 "스크립트 하나로 처음부터 끝까지 재현할 수 있다"를 매번 만족하지 못한다. 같은 실패로 compose e2e(`test_demo_replays_steps_1_to_7_cleans_up_and_fits_in_memory`)도 떨어지므로, CI `data-plane`의 `rest` 조각(AC-09)도 같은 확률로 떨어질 수 있다.
- 내 e2e 재실행(아래 "e2e 재실행")의 데모: `[6] FAILED: fio write /v41/fio with the limit 10 MiB/s: 6.5, 8.22, 9.89 MiB/s (median 8.22 = 82%)`, `rc 1, 53.86 s`(치움). 같은 실행의 `demo.py --keep`은 `rc 0, 81.94 s`.
- 10회 기록(모두 일반 사용자. 1~7회는 AC-01 2회의 스택, 8·9회는 e2e의 `anf-clone-e2e` 스택, 10회는 AC-01 3회의 스택. 원본 `…\scratchpad\ac03-demo.txt`, `ac05-demo-keep.txt`, `ac05-demo-keep2.txt`, `verify\demo-rep1..4.txt`, `verify-e2e\test_compose_stack_live.jsonl`, `verify\demo-after-vm-restart.txt`):

| 회 | 실행 | 6단계 10 MiB/s (3회, 중앙값) | 6단계 5 MiB/s | 결과 | 걸린 시간 |
| --- | --- | --- | --- | --- | --- |
| 1 | `demo.py` | 9.73, 9.85, 9.86 (98%) | 4.97, 4.96, 4.97 (99%) | exit 0 | 85.8 s |
| 2 | `demo.py --keep` | **7.76, 7.8, 6.78 (78%)** | — | **exit 1** `[6] FAILED` | — |
| 3 | `demo.py` | 9.85, 9.85, 9.88 (98%) | 4.97, 4.98, 4.97 (99%) | exit 0 | 86.1 s |
| 4 | `demo.py` | 9.86, 9.75, 9.85 (98%) | 4.97, 4.93, 4.97 (99%) | exit 0 | 86.5 s |
| 5 | `demo.py` | **7.15, 6.24, 9.95 (72%)** | — | **exit 1** `[6] FAILED` | 62.8 s |
| 6 | `demo.py` | 9.85, 9.86, 9.79 (98%) | 4.94, 4.9, 4.95 (99%) | exit 0 | 88.5 s |
| 7 | `demo.py --keep` | 9.82, 9.66, 9.75 (98%) | 4.96, 4.97, 4.96 (99%) | exit 0 | 약 86 s |
| 8 | e2e 안 `demo.py` | **6.5, 8.22, 9.89 (82%)** | — | **exit 1** `[6] FAILED` | 53.9 s |
| 9 | e2e 안 `demo.py --keep` | (출력 끝만 기록됨) | — | exit 0 | 81.9 s |
| 10 | `demo.py`(VM 재부팅 직후) | 9.81, 9.89, 9.87 (99%) | 4.97, 4.97, 4.96 (99%) | exit 0 | 87.3 s |

- 재현: 스택을 띄우고 `python3 scripts/demo.py`를 연달아 돌린다. 실패 출력: `[6] FAILED: fio write /v41/fio with the limit 10 MiB/s: 7.15, 6.24, 9.95 MiB/s (median 7.15 = 72%); expected the median in 90%-101% and no run above 101%`.
- 실패는 언제나 **한도 아래쪽**이다(어느 회도 101%를 넘지 않았다). 2회 실패 직후 확인: vol-v41 인스턴스 netns의 HTB `rate 87710Kbit`(= 10 MiB/s ÷ 0.9564, 맞음), LVM 태그 `anf_qos=10.0`, API `throughputMibps 10.0`. 같은 볼륨·같은 클라이언트에서 같은 fio를 곧바로 4회 → `9.81, 9.84, 9.84, 9.85 MiB/s`(98%). fq_codel 드롭은 정상 회에도 회마다 약 22개라 원인이 아니다. 실패 직후 load average 2.98(정상 회 끝 0.57~1.63). 제한기가 아니라 설계 §7.3이 적은 서버 쪽 쓰기 멈춤(S7 Q2)과 같은 모양이다. 원인은 확인하지 못했다.
- 기대값: `exit 0`이 매번. 추정 원인 위치: `scripts/demo.py:43-51`(10 MiB/s 한도, 6 s × 3회)와 `scripts/demo.py:100-106`(중앙값 90% 아래쪽 판정) — 측정 환경의 흔들림을 아래쪽 판정이 그대로 실패로 만든다.
- 수정 제안(택일 또는 조합):
  1. 아래쪽이 어긋나고 위쪽(101%)은 지켰을 때만 3회 측정을 한 번 더 하고, 두 묶음을 모두 출력한다(2회 실패 직후 같은 볼륨에서 다시 잰 4회는 모두 98%였다).
  2. 데모의 판정을 "한도는 천장(어느 회도 101% 이하)" + "한도를 바꾸면 따라 바뀐다(5 MiB/s 중앙값 < 10 MiB/s 측정의 최댓값 × 0.6)"로 바꾸고, 90~101%의 정확도는 FR-08 시험에 맡긴다(FR-12 1회차 AC-06과 같은 분리).
  3. 원인 조사: 실패 때 `/proc/meminfo`의 Dirty·Writeback, `/proc/pressure/io`, 호스트 `iostat`을 함께 남겨 S7 Q2의 서버 쪽 멈춤인지 확인한다.
- 수정 뒤 재검증 기준(`real-env-verify` §4): 관찰된 실패율 p = 3/10 → n = ⌈3/p⌉ = 10회 연속 `exit 0`.
- 나머지 조건은 충족했다. 통과한 7회 모두 3분 안(81.9~88.5 s)이고, `--keep`이 아닌 회는 스스로 치웠다. 실패한 5·8회도 치웠다(`[cleanup] removed vol-restored, vol-v41, vol-v3, demo-pool, demo-acct and the clients …`). 단계별 근거 줄은 첫 실행 출력과 같다(아래).

- 기준: 스택이 뜬 상태에서 `python3 scripts/demo.py`가 root 없이 1~7단계를 끝내고 0으로 끝난다. 단계마다 클라이언트에서 관찰한 근거. 끝난 뒤 리소스·클라이언트가 남지 않는다. 3분 안.
- 실행한 명령(일반 사용자, README 그대로, AC-01 2회의 스택): `cd /mnt/c/Users/mkimh/Projects/ANF-clone && python3 scripts/demo.py`
- 출력 전체(`…\scratchpad\ac03-demo.txt`):

```
[1] PUT account demo-acct -> 201 in 78 ms; Succeeded after 0.0 s
[1] PUT pool demo-pool (Premium, Manual QoS, 4 TiB) -> 201 in 18 ms; Succeeded after 0.0 s
[1] PUT volume vol-v3 (NFSv3, 50 GiB, 10 MiB/s) -> 201 in 14 ms; Succeeded after 2.5 s
[1]   mount target 172.30.0.129:/demo-v3 (NFSv3)
[1] PUT volume vol-v41 (NFSv4.1, 50 GiB, 10 MiB/s) -> 201 in 66 ms; Succeeded after 2.5 s
[1]   mount target 172.30.0.130:/demo-v41 (NFSv4.1)
[2] anf-demo-client-1 mounted 172.30.0.129:/demo-v3 on /v3 (nfs, vers=3)
[2] anf-demo-client-1 wrote /v3/hello.txt and read it back: 'hello from the ANF clone demo'
[2] anf-demo-client-1 mounted 172.30.0.130:/demo-v41 on /v41 (nfs4, vers=4.1)
[2] anf-demo-client-1 wrote /v41/hello.txt and read it back: 'hello from the ANF clone demo'
[3] PUT snapshot vol-v3/snap1 -> 201 in 70 ms; Succeeded after 1.5 s
[3] anf-demo-client-1 deleted /v3/hello.txt (ls /v3: empty); /v3/.snapshot/snap1/hello.txt still reads 'hello from the ANF clone demo'
[4] POST revert vol-v3 to snap1 -> 202; Succeeded after 2.5 s
[4] anf-demo-client-1 reads /v3/hello.txt again without remounting (0.2 s after the revert): 'hello from the ANF clone demo'
[5] PUT volume vol-restored (NFSv3, 50 GiB, 10 MiB/s) -> 201 in 83 ms; Succeeded after 2.5 s
[5]   mount target 172.30.0.131:/demo-restored (NFSv3)
[5] originatingResourceId = .../vol-v3/snapshots/snap1
[5] anf-demo-client-2 mounted 172.30.0.131:/demo-restored on /r (nfs, vers=3)
[5] anf-demo-client-2 reads /r/hello.txt 'hello from the ANF clone demo' and wrote /r/only-in-restored.txt; source unchanged (ls /v3 on anf-demo-client-1: hello.txt)
[6] fio write on vol-v41 with the limit 10 MiB/s: 9.73, 9.85, 9.86 MiB/s (median 9.85 = 98%)
[6] PATCH vol-v41 throughputMibps 10 -> 5 -> 202; Succeeded after 1.5 s
[6] fio write on vol-v41 with the limit 5 MiB/s: 4.97, 4.96, 4.97 MiB/s (median 4.97 = 99%)
[7] Prometheus (via http://127.0.0.1:8081/prometheus/): demo-v41 write rate peaked at 9.1 MiB/s during the fio runs; its limit series is 5 MiB/s
[7] dashboard http://127.0.0.1:8081/ -> 200 (index.html); /subscriptions proxy -> volumes vol-restored, vol-v3, vol-v41; /prometheus proxy -> up {'storage-agent': '1', 'anf-api': '1'}
[7] open http://127.0.0.1:8081/?subscription=de300000-0000-4000-8000-000000000013 in a browser
[cleanup] removed vol-restored, vol-v41, vol-v3, demo-pool, demo-acct and the clients anf-demo-client-1, anf-demo-client-2
[done] steps 1-7 passed in 85 s
exit=0 elapsed_s=85.81
```

- 끝난 뒤 남은 것(root로 확인): 데모 구독 계정 목록 `{"value":[]}`, 컨테이너는 스택 다섯(`init` Exited 0 포함)뿐(`anf-nfs-*`·`anf-demo-client-*` 없음), LV `aggr0`뿐, `/var/lib/anf-clone/exports`·`ns` 비어 있음, agent `GET /api/storage/volumes` → `{"records":[],"num_records":0}`.
- implementer e2e(`demo` 태그)도 `rc 0, 85.31 s`, 계정 목록 `[]`.

### [PASS] AC-07 데모 동안 WSL 메모리 (NFR-06)

- 기준: 데모가 도는 동안 WSL 사용 메모리가 7 GB 안. `free -m`과 `docker stats` 기록.
- 실행한 명령: AC-03 데모 동안 root 표본기(`free -m` + `docker stats --no-stream`, 약 4 s 간격 23회). 원본 `…\scratchpad\verify\ac07-mem.txt`(sha256 `c3fad535…`, WSL 원본과 같음).
- 출력: 시작 `total=7778 used=813 available=6964` → 최대 `t=365.45 used=1042 available=6736`. 그 순간 `docker stats`: storage-agent 70.25 MiB, anf-api 40.56 MiB, prometheus 31.5 MiB, dashboard 11.23 MiB, `anf-demo-client-1` 27.28 MiB, 볼륨 인스턴스 셋 2.2·2.1·5.3 MiB, `anf-demo-client-2` 1.0 MiB.
- implementer e2e(`memory` 태그): 16 표본, 최대 used 1,095 MiB / 7,168 MiB 한도.
- 측정 방식 한계: 4 s 간격이라 그 사이의 순간 최대는 놓칠 수 있다. 한도(7,168 MiB)와 6 GB 넘게 떨어져 판정에는 영향이 없다.

### [PASS] AC-04 데모의 실패 처리

- 단위 테스트(Windows `.venv-win`): `python -m pytest backend/tests/unit/test_demo.py backend/tests/unit/test_compose.py -v` → `26 passed in 0.17s`. 그 가운데 `test_stack_down_exits_2_with_the_start_command_and_sends_nothing_else`, `test_missing_client_image_exits_2`, `test_failed_volume_stops_at_step_1_shows_the_error_and_cleans_up`, `test_keep_leaves_resources_after_a_failure`.
- 실환경에서 기대가 어긋난 실제 사례(AC-03의 `--keep` 실행, 아래): `[6] FAILED: fio write /v41/fio with the limit 10 MiB/s: 7.76, 7.8, 6.78 MiB/s (median 7.76 = 78%); expected the median in 90%-101% and no run above 101%` → `exit=1`, 단계 번호와 회마다 값이 stderr에 보이고, `--keep`이라 리소스·클라이언트가 남았다(설계 §7.5대로). 이어서 `--clean` → `[cleanup] removed what an earlier run left: vol-restored, vol-v41, vol-v3, demo-pool, demo-acct`, `exit=0`.
- 스택 없이 실행: `demo.py --clean` → `docker compose -f deploy/compose.yaml down -v` 뒤 일반 사용자로 `python3 scripts/demo.py` → `The stack is not running (http://127.0.0.1:8080/subscriptions/de300000-…/netAppAccounts?api-version=2026-08-01: <urlopen error [Errno 111] Connection refused>). Start it from the repository root:` / `  docker compose -f deploy/compose.yaml up -d --build --wait`, `exit=2`. 그 뒤 컨테이너·이름 있는 볼륨 없음, LV `aggr0`뿐, 포트 비어 있음(아무것도 만들지 않았다).

### [PASS] AC-05 Windows 브라우저로 대시보드 (화면) — headless Chrome

- 기준: Windows 브라우저(headless Chrome 포함)로 `http://127.0.0.1:8081/?subscription=<id>`를 열면 리소스 트리와 볼륨 차트가 보인다(nginx 프록시를 거친 API·Prometheus).
- 브라우저: Claude in Chrome은 연결돼 있지 않았다(`tabs_context_mcp` → "Browser extension is not connected", `list_connected_browsers` → `[]`). FR-12 때처럼 Windows의 Chrome 157.0.8103.50을 `--headless=new --remote-debugging-port=9334 --user-data-dir=<scratchpad>\chrome-prof`로 띄우고 DevTools 프로토콜(Node 22.14 내장 WebSocket)로 조작했다. 스크립트 `…\scratchpad\cdp_dashboard.mjs`.
- 절차: `demo.py --keep`(7회 표의 7회, exit 0) 직후, 새 탭 하나로 `http://127.0.0.1:8081/?subscription=de300000-0000-4000-8000-000000000013`을 한 번 열고 트리를 읽은 뒤, `vol-v41` 버튼을 좌표(234, 318.5)에 `Input.dispatchMouseEvent`(mouseMoved/Pressed/Released)로 눌러 차트를 기다렸다.
- 출력(`…\scratchpad\ac05\ac05-evidence.json`):
  - 트리: `demo-acct NetApp account Succeeded demo-rg · westus2` / `demo-pool Capacity pool Succeeded 4 TiB · Premium · Manual QoS · 25 / 256 MiB/s` / `vol-restored Volume Succeeded 172.30.0.131:/demo-restored · NFSv3 · 50 GiB · 10 MiB/s` / `snap1 Snapshot Succeeded` / `vol-v3 … 172.30.0.129:/demo-v3 · NFSv3 · 50 GiB · 10 MiB/s` / `snap1` / `vol-v41 … 172.30.0.130:/demo-v41 · NFSv4.1 · 50 GiB · 5 MiB/s`. 같은 때 Windows에서 nginx를 거친 API GET: `vol-restored Succeeded 10`, `vol-v3 Succeeded 10`, `vol-v41 Succeeded 5` — 화면과 같다.
  - 볼륨 패널 `Volume vol-v41`: 차트 셋(Throughput: 선 3개 51·51·50점, 한도는 점선 / IOPS 3개 / Usage 2개). 글자 `write 1.3 MiB/s`, `limit 5 MiB/s`, `max 10 MiB/s`, `used 0.049 GiB`, `size 48.9 GiB`. 오류 배너 없음. anf-api 패널도 그려짐.
  - 네트워크(모두 8081, 모두 200): `/`, 자산, `/subscriptions/…`(계정·풀·볼륨·스냅샷 목록 6개), `/prometheus/api/v1/query_range?…`(9개, `creation_token="demo-v41"` 쿼리 7개 포함).
  - 탭을 다시 읽지 않음: `performance.getEntriesByType('navigation')` = 1개, `type: navigate`.
- 스크린샷: `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\ac05\ac05-tree.png`, `…\ac05\ac05-volume-charts.png`(트리, `vol-v41`의 처리량 차트에 fio 부하 두 봉우리와 10 → 5 MiB/s 한도 점선).
- 한계: headless 렌더링이다. 리더가 "실제 브라우저"를 확장 프로그램이 붙은 Chrome으로 해석하면 UNVERIFIED로 바꾸면 된다(FR-12 1회차와 같은 조건).

### [PASS] AC-06 agent를 죽였다 살려도 볼륨·스냅샷·한도 유지, 되돌리기·삭제 성공 (데이터 효과)

- 기준: agent 컨테이너를 쓰는 중에 `docker kill`해도 클라이언트 쓰기 오류 0, 다시 뜨면 볼륨·스냅샷·한도 그대로, 되돌리기·삭제가 재시작 뒤에도 성공(S9 P3 회귀).
- 근거는 e2e `test_agent_kill_during_writes_keeps_volumes_and_revert_and_delete_work` 두 실행(손으로 따로 하지 않았다):
  - 내 재실행(`fr13-verify`, PASSED): `after-kill` — README 명령으로 다시 띄움 `rc 0 9.46 s`, 쓰기 v3 `154회 오류 0, 죽인 뒤~다시 뜰 때 14.46 s 창 안 125회`, v41 `85회 오류 0, 창 안 69회`, API 보기 kill 전과 같음(볼륨 셋 `Succeeded`, IP·한도·fileSystemId, `snapshots ['snap1']`), 인스턴스 netns tc `rate_bits` vol-v3·vol-restored 87,710,000(10 MiB/s), vol-v41 43,855,000(5 MiB/s), `ifb0`와 양방향 필터 각 1. `revert-after-restart` — `Reverting ×3 → Succeeded`, 클라이언트 `ls /v3` = `['hello.txt']`, 내용 `'hello from the ANF clone demo'`(kill 동안 쓴 `during-kill` 사라짐). `delete-after-restart` — `demo.py --clean` `rc 0`, `vol-restored, vol-v41, vol-v3, demo-pool, demo-acct` 삭제, 인스턴스·LV가 시작 때와 같음.
  - implementer 실행(`fr13-compose-222653`, PASSED): 같은 모양(v3 119회·v41 63회 창 안, 오류 0, tc 같음, 되돌리기 `Succeeded`, 삭제 성공).
- 단언 방식 확인(`backend/tests/e2e/test_compose_stack_live.py:277-319`): 쓰기는 클라이언트 컨테이너 안의 `dd oflag=direct` 종료 코드로, 한도는 API 값이 아니라 인스턴스 netns의 HTB·필터(`throughput_live.tc_state`)로, 되돌리기는 클라이언트가 읽은 파일로 판정한다.

### [PASS] AC-08 실행기와 스택

- 1부(스택이 떠 있을 때): `ANF_TEST_OUT=/var/tmp/anf-clone-tests/fr13-verify-busy bash scripts/run-dataplane-tests.sh backend/tests/e2e/test_compose_stack_live.py`(root) → 종료 코드 2, `precheck failed: port 8080, 8081, 8090, or 9090 is in use, maybe by the compose stack (stop it: docker compose -f deploy/compose.yaml down) or by another session's data plane: 127.0.0.1:8090 users:(("python",pid=1560,…)) 127.0.0.1:8080 … 127.0.0.1:8081 … nginx … 127.0.0.1:9090 … prometheus`. 출력 폴더도 만들지 않았다.
- 2부(내린 뒤 사전 점검 통과): `demo.py --clean`(exit 0) → `docker compose -f deploy/compose.yaml down -v`(exit 0, 컨테이너 다섯·이름 있는 볼륨 둘 제거) 뒤 남은 것: 컨테이너 없음, 이름 있는 볼륨 없음, LV `aggr0`뿐, `ns`·`exports` 비어 있음, 포트 비어 있음. 그 상태에서 실행기를 돌리자 사전 점검을 통과해 `VG anf: attached` / `collected 5 dataplane tests in 1 files` 로 시험을 시작했다(아래 e2e 재실행). 실행기는 끝에 남은 LV·컨테이너·리스너를 보고하지 않았고(`summary.txt`에 남은 것 줄 없음), 끝난 뒤 root로 다시 봐도 컨테이너·이름 있는 볼륨 없음, LV `aggr0`뿐, 포트 비어 있음. e2e의 `down-v` 기록도 `left: {containers: [], volumes: [], clients: [], listening: []}`, `instances {}`, `lvs []`.

### [PASS] AC-10 회귀 묶음, lint, 프런트엔드

- WSL 일반 사용자, 스택을 내린 뒤: `ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest -m "not dataplane" -q -p no:cacheprovider --junitxml=/var/tmp/fr13-verify/not-dataplane.xml` → `1042 passed, 124 deselected in 208.72s`, exit 0. `python backend/tests/junit_gate.py …` → `collected 1042, skipped 0`, gate exit 0. (docs/testing.md의 1,042와 같다.)
- ruff: `uvx --offline ruff@0.14.0 check backend .claude/hooks`(uv 캐시에 있던 ruff 0.14.0, 내려받지 않음) → `All checks passed!`, exit 0.
- Windows `frontend/`: `npm run typecheck`(`tsc --noEmit`) exit 0, `npm test` → `Test Files 8 passed (8)`, `Tests 48 passed (48)`, exit 0, `npm run build` → `dist/assets/index-C-xMrAKK.js 227.96 kB`, `dist/assets/index-D-TFYJHs.css 2.76 kB`, exit 0. 이 자산 이름은 AC-05에서 nginx 컨테이너가 준 것과 같다 — 대시보드 이미지가 지금의 `frontend/` 소스로 빌드됐다는 교차 확인. `git status frontend` 변경 없음(`dist`는 무시됨).

### [PASS] AC-11 README의 명령과 주소

- 기준: README 빠른 시작의 명령과 주소가 검증에서 그대로 쓴 것과 같다.
- 대조(`README.md`):
  - 시작 `docker compose -f deploy/compose.yaml up -d --build --wait`(저장소 루트, WSL 안) — AC-01 세 번, AC-02 두 번 이 줄을 그대로 썼다. "later runs take seconds" — 8.82~11.39 s. "After a WSL restart, run the same command again" — AC-01 2회.
  - 주소 표 `127.0.0.1:8080`·`8081/?subscription=<id>`·`8090`·`9090` — `ss`로 본 리스너와 같다(AC-01). "A Windows browser reaches these addresses" — Windows `curl`·headless Chrome으로 8081 `200`(AC-05).
  - 데모 `python3 scripts/demo.py`, `--keep`, 출력된 주소 `http://127.0.0.1:8081/?subscription=de300000-0000-4000-8000-000000000013`, `--clean` — 그대로 썼다. "about a minute and a half" — 통과 회 81.9~88.5 s. 종료 코드 0·1·2 — 셋 다 관찰했다(AC-03·AC-04).
  - 내리기 `docker compose -f deploy/compose.yaml down` — 인스턴스가 남아 클라이언트가 계속 쓰고, 다음 `up`이 이어받는다(AC-02). `down -v`는 리소스가 없을 때만 — 그렇게 썼다.
  - 테스트 전 내리기와 포트 8080·8081·8090·9090 — 실행기 문구와 같다(AC-08).
- 다만 "The first run builds the images and takes about a minute"는 `/var/lib/anf-clone`가 이미 있는 기기에서만 맞다(판정 밖 관찰 1). 명령·주소 자체는 맞으므로 이 기준은 PASS로 둔다.

### e2e 재실행 (AC-01·02·03·06·07·08의 독립 근거)

- 명령(root, 스택을 내린 뒤): `cd /mnt/c/Users/mkimh/Projects/ANF-clone && ANF_TEST_OUT=/var/tmp/anf-clone-tests/fr13-verify bash scripts/run-dataplane-tests.sh backend/tests/e2e/test_compose_stack_live.py`
- 결과: **1 failed, 4 passed in 221.73s**, 실행기 `exit 1`. 실패는 `test_demo_replays_steps_1_to_7_cleans_up_and_fits_in_memory`(AC-03의 6단계 간헐 실패, 위). 나머지: `test_one_command_starts_the_stack_as_a_regular_user` PASSED(`up rc 0 11.91 s`, 서비스 넷 `running healthy`, `init exited 0`, 포트 넷 `127.0.0.1:<port>`), `test_rerun_and_down_up_keep_volumes_and_client_io` PASSED(다시 실행 `rc 0 9.48 s` 다시 만들어진 넷, down `0.95 s` 포트 넷 닫힘, up `8.55 s`, 보기 같음, 쓰기 166회 오류 0 down 창 안 57회), `test_agent_kill_during_writes…` PASSED, `test_down_leaves_nothing_behind` PASSED. skip 0. 메모리 최대 used 1,224 MiB(10 표본).
- 원본 보관: `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\verify-e2e\`(jsonl sha256 `c9980dbd…` 원본과 같음, `runner.out`은 실행기 표준 출력).
- implementer 실행(`fr13-compose-222653`, 14:26:56~14:31:01 PST)은 5 passed지만, 커밋 `c99a400`·`d2388b1`(14:31:34)보다 앞서 미커밋 작업 트리로 돌았다. 실행기는 코드 해시를 남기지 않아 검증 대상 코드와 같은지 증명할 수 없다. 그래서 판정은 내 재실행을 주 근거로 하고, implementer 기록은 보조로만 쓴다.

## 판정 밖 관찰

1. **새 기기에서는 README 명령이 실패할 것이다(`/var/lib/anf-clone`가 없을 때).** compose는 `init`을 시작하기 전에 모든 컨테이너를 만든다. `storage-agent`의 두 바인드(`deploy/compose.yaml:43-52`)는 긴 문법이라 원본 경로가 없으면 만들기 단계에서 docker가 거절한다. 이 기기에는 앞선 기능 작업 때부터 `/var/lib/anf-clone`가 있어 드러나지 않았다(`ns`·aggregate는 agent가 만들고 `flexvol.py:173-183`, 준비 스크립트는 이 디렉터리를 만들지 않는다). 실제 데이터 플레인 디렉터리는 지울 수 없어서, 같은 구조의 장난감 compose 프로젝트로 확인했다(`…\scratchpad\toy-compose\compose.yaml`: 한 번 도는 `a`가 `/tmp/fr13-toy-src`를 만들고, `b`가 `depends_on: service_completed_successfully` + `bind.recursive: disabled`로 그 경로를 바인드):
   - 그대로: `Container fr13-toy-b-1  Error response from daemon: invalid mount config for type "bind": bind source path does not exist: /tmp/fr13-toy-src`, `rc=1`, `a`는 `created`인 채로 시작조차 안 됨.
   - `bind.create_host_path: true`를 더하면(`compose-create.yaml`): `rc=0`, `b`가 `a`가 만든 `sub`를 본다.
   - 수정 제안: `storage-agent`의 두 긴 문법 바인드에 `create_host_path: true`를 더하고, compose 단위 테스트에 그 조건을 넣는다. AC-01의 기준("WSL을 다시 시작한 직후")은 이 기기에서 충족하므로 판정에는 넣지 않았다. README의 "The first run builds the images and takes about a minute"는 이미지만 없고 디렉터리가 있는 기기에서만 맞다.
2. 대시보드 nginx master 프로세스는 uid 0이다(`nginx:1.28.0-alpine` 기본). 127.0.0.1에만 열고 특권이 없으므로 이 기능의 기준과 무관하다.
3. 스택 컨테이너는 재시작 정책이 없어(설계 §7.7) WSL 배포판이 유휴 종료되면 함께 내려간다. AC-01 1회 직후 실제로 그랬고(컨테이너 넷 `Exited (143)`/`(0)`), README대로 같은 명령을 다시 실행해 돌아왔다(AC-01 2회). 볼륨이 있을 때 이렇게 되면 볼륨 인스턴스도 같이 멈추므로 클라이언트 I/O는 끊긴다(이번에는 볼륨이 없을 때였다). WSL 특성이며 README의 "After a WSL restart, run the same command again"과 맞다.
## 정리

- 데모 리소스: 마지막 데모가 스스로 치웠고 `demo.py --clean` → `removed … nothing`. 스택: `docker compose -f deploy/compose.yaml down -v`(exit 0).
- 끝난 상태(root, 15:20 PST): 컨테이너 없음, 이름 있는 볼륨 없음, LV `aggr0`뿐, `/var/lib/anf-clone/ns`·`exports` 비어 있음, 포트 8080·8081·8090·9090 비어 있음. 호스트 `ns`의 rshared 바인드와 VG `anf`는 붙은 채로 둔다(실행기·`init`이 다시 해도 바뀌지 않는 평소 상태). 이미지(`anf-clone-*`, `anf-nfs-*`)는 남겼다.
- 임시 파일: 장난감 compose의 `/tmp/fr13-toy-src`·컨테이너 지움. WSL 쪽 로그(`/root/fr13-verify`, `/var/tmp/fr13-verify`, `/var/tmp/anf-clone-tests/fr13-verify`, `/tmp/ac02*`)는 scratchpad 사본과 sha256·`cmp`로 같음을 확인한 뒤 지웠다. `fr13-verify-busy`는 만들어지지 않았다. implementer의 `fr13-compose-*` 폴더는 건드리지 않았다.
- headless Chrome(포트 9334) 종료, 임시 프로필 `scratchpad\chrome-prof` 삭제.
- 저장소: 이 보고서 외에 바꾼 파일 없음(`git status`: `?? _workspace/containers/04_verifier_report.md`와 원래 있던 `docs/ai-readiness-*`). 커밋하지 않았다.
- 보관 위치: `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\`(`ac01-up*.txt`, `ac03-demo.txt`, `ac05-demo-keep*.txt`, `ac05\`, `verify\`, `verify-e2e\`, `impl-e2e-222653\`, `toy-compose\`, `ac02.sh`, `cdp_dashboard.mjs`).
