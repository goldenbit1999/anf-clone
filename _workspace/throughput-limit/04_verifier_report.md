# throughput-limit (FR-08) 검증 보고서 — 1회차

- 진행 상태: 완료 (2026-11-09 09:40)
- 검증일: 2026-11-09
- 검증자: real-env-verifier (서브에이전트)
- 검증 대상 코드: 커밋 `0b44a8f` 제품 코드, 브랜치 `feature/throughput-limit`
  - 시작 시 HEAD `47ed3ed` (0b44a8f 뒤 커밋은 기록 문서 3개뿐: `git diff --stat 0b44a8f HEAD`)
  - 시작 시 내용 해시: `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3` (리더가 준 값과 같음)
  - 끝난 뒤 내용 해시: `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3` (시작과 같음, HEAD `47ed3ed` 그대로)
  - 미커밋 변경: `_workspace/throughput-limit/00_progress.md`(리더 기록), `docs/ai-readiness-*`(검증과 무관, 건드리지 않음)
  - 해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
- 이번 회차 범위: 전체 (AC-01~AC-12)
- 로그·측정 원본: `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\8ccecfbf-a107-4c47-b042-9e3c9ff59a3b\scratchpad\fr08-verify\`

## 환경 사전 점검
2026-11-09 07:02 (PST). 모두 통과.

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`: Ubuntu `Stopped`(다른 배포판도 Stopped) → 첫 명령으로 떴다. uptime 0 min, 커널 `6.18.54.1-microsoft-standard-WSL2`. 유휴 종료 방지로 `wsl -d Ubuntu -u root -e sleep 86400`을 띄워 둠 |
| 메모리 | `free -m`: total 7778, used 667, buff/cache 1647, available 7111 MiB. swap 2048 |
| 커널 모듈 | `nfsd` 로드됨, `sch_fq_codel` 로드됨. `dm_thin_pool`·`ifb`는 처음에 없음 → agent가 처음 뜰 때 올라옴(`ifb`는 `numifbs=0`, 호스트 IFB 0개: `ip -o link show type ifb` 빈 출력) |
| `fs.leases-enable` | `0` |
| Docker | `docker version` 서버 29.1.3 `linux`, `readlink /usr/bin/docker` 빈 출력(rc 1, Desktop 연동 아님). 컨테이너 0개. 네트워크 `anf-vnet` 있음 |
| 이미지 | `anf-nfs-server:latest`(2026-11-08), `anf-nfs-client:latest`(2026-11-09 04:04, 준비 스크립트 재실행분). `anf-nfs-client` 안 `fio-3.36` |
| 포트 8080·8090 | 비어 있음 |
| VG `anf` | 처음에 붙어 있지 않음(`vgs` 빈 출력, 루프 장치 없음 — WSL 막 부팅). agent를 root로 한 번 띄우자(07:04, 2.0 s) VG `anf`(<1024 GiB) + `aggr0`가 붙음. `/var/lib/anf-clone/{ns,exports}` 비어 있음, 볼륨 LV 없음 |
| 시계 비율 | 게스트 `time.monotonic()` / 호스트 Stopwatch = **1.0023** (300.7 s, 호출 지연 최대 1.24 s → ±0.4% 정도). 이 값은 부팅 직후의 것이고, 측정 시간대에는 약 1.02로 바뀌었다("측정값"의 시계 절) |
| 단위·계약 (Windows) | 시작 전 `.venv-win` 전체 914 passed / 176 skipped(통합·e2e skip, Windows 정상), `backend/tests/unit backend/tests/contract`만 914 passed, skip 0 (101 s) |

이번 회차의 도구: 검증 드라이버 `_workspace/throughput-limit/verify/fr08_verify.py`(검증 때는 `backend/tests/e2e/`에서 돌렸고, 끝난 뒤 리더가 기록으로 옮겼다. 표준 라이브러리만 쓴다. implementer의 `throughput_live.py`를 쓰지 않고 fio·tc·`/proc/<pid>/net/dev`를 직접 다룬다), 서비스 제어·실행 스크립트 `fr08-verify/svc.sh`·`step.sh`·`pytest1.sh`·`pytest2.sh`·`regress2.sh`(scratchpad). 사용 가능한 도구: Bash(Git Bash → `wsl -d Ubuntu -u root`), PowerShell, Read/Write/Edit/Grep/Glob, Monitor, ToolSearch. agent는 root(`svc.sh agent-start`, 저장소 작업 트리), anf-api는 `setpriv`로 `mkimhome1` 권한, DB `~mkimhome1/.local/state/anf-clone/fr08-verify.db`, `ANF_MIN_VOLUME_SIZE_GIB=1`.

## 결과 요약
PASS 11 / FAIL 1 / UNVERIFIED 0

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1 |
| AC-02 | PASS | 1 |
| AC-03 | PASS | 1 |
| AC-04 | PASS | 1 |
| AC-05 | PASS (읽기 판정, 쓰기 참고) | 1 |
| AC-06 | PASS | 1 |
| AC-07 | PASS | 1 |
| AC-08 | PASS | 1 |
| AC-09 | PASS | 1 |
| AC-10 | PASS | 1 |
| AC-11 | PASS | 1 |
| AC-12 | FAIL (시험 코드 `throughput_live.py:161`, 제품 코드 아님) | 1 |

## 항목별 결과

### [PASS] AC-11 storage agent API의 qos (agent API)
- 기준: `POST`에 `qos`를 주면 job `success`, GET 레코드에 `qos.policy.max_throughput_mbps`, netns에 `ifb0`·HTB·필터. 같은 uuid에 다른 값 → 태그와 HTB rate가 바뀜. `qos` 없는 POST → netns에 tc 없음. 모양 오류 → `400`. 통합: 걸기 멱등, `recover()` 뒤 다시 걸림, 되돌리기 뒤 태그와 tc 유지.
- 실행: `fr08_verify.py ac11` (07:12, agent만 root로 띄움, anf-api 없음). 로그 `fr08-verify/logs/step-ac11.out`. 통합: `pytest1.sh integration backend/tests/integration` (07:14~07:20, agent 멈춤).
- 출력(핵심):
  - 새 uuid에 `qos.policy.max_throughput_mbps: 10` POST → 202, job `success`. GET 레코드 `"qos": {"policy": {"max_throughput_mbps": 10.0}}`, LV 태그 `anf_qos=10.0`. netns(`nsenter -t <pid> -n`):
    ```
    3: ifb0: <BROADCAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc htb ...
    qdisc htb 1: root refcnt 2 r2q 10 default 0x1 direct_packets_stat 0 direct_qlen 32
    qdisc fq_codel 10: parent 1:1 limit 10240p flows 1024 quantum 1514 target 5ms interval 100ms ...
    class htb 1:1 root leaf 10: prio 0 rate 87710Kbit ceil 87710Kbit burst 1578b cburst 1578b
    qdisc clsact ffff: parent ffff:fff1            (eth0)
    ingress: filter protocol all pref 49152 matchall chain 0 handle 0x1 ... action order 1: mirred (Egress Redirect to device ifb0) stolen
    egress:  (같은 필터 하나)
    ```
    rate 87,710 Kbit = 결정 12의 round(10 × 1048576 × 8 / 0.9564) = 87,710,247 bit/s (tc가 Kbit로 잘라 보임, 차 −3×10⁻⁶).
  - 같은 uuid에 20 POST → job `success`, 태그 `anf_qos=20.0`만(10.0 사라짐), 레코드 20.0, HTB `175420Kbit`(기대 175,420,494), 같은 pid(인스턴스 그대로). 같은 20을 한 번 더 POST, `qos` 없이 한 번 더 POST → 태그 20.0 그대로, 방향마다 필터 하나(`handle 0x1` 하나) 그대로.
  - `qos` 없는 새 볼륨 POST → 레코드에 `qos` 없음, 태그에 `anf_qos` 없음, netns `ip link`에 `lo, eth0`뿐(`Cannot find device "ifb0"`), eth0 qdisc `noqueue`만, 필터 없음.
  - 보조 데이터(10 s 직접 쓰기, 같은 클라이언트): 20 MiB/s 볼륨 19.57 MiB/s, 제한 없는 볼륨 41.77 MiB/s(서버 디스크 쓰기 속도).
  - 모양 오류 10개 모두 `400`: 추가 필드(`qos.name`) / `policy.min_throughput_mbps` / 빈 `policy` / 0 / −5 / `"10"` / `true` / `null` / `qos: 10` / `NaN`(원문 JSON). 문구는 "qos must have exactly the field policy", "qos.policy must have exactly the field max_throughput_mbps", "qos.policy.max_throughput_mbps must be a number of MiB/s greater than 0". 앞뒤 볼륨 목록이 같고 그 uuid의 LV가 없다.
  - DELETE 두 개 → job `success`, 인스턴스 pid 사라짐, 호스트 IFB 0개.
  - 통합 테스트 30 passed, skip 0 (383.5 s). FR-08 것: `test_limit_lives_in_the_instance_netns_and_is_idempotent`(두 번 걸어도 필터 하나, 호스트 IFB 그대로), `test_volume_without_a_limit_has_no_tc`, `test_limit_comes_back_when_the_instance_starts_again`(`docker stop` → `recover()` 뒤 다시 걸림), `test_revert_keeps_the_limit`(되돌리기 뒤 태그 `anf_qos=10.0`, 한도, 차단 규칙 없음), `test_volume_from_snapshot_gets_its_own_limit` 모두 PASSED. 끝난 뒤 컨테이너 0, 볼륨 LV 0, IFB 0, 포트 비어 있음.

### [PASS] AC-01 Auto 한도 (계약·데이터)
- 기준: (a) Auto Premium 101 GiB → `actualThroughputMibps` 6.312, 1 GiB → 0.062, `throughputMibps` 없음. 다른 서비스 수준 하나(Standard 1 GiB → 0.016). 풀 `utilizedThroughputMibps` = 볼륨 값의 합. (b) 잴 만한 Auto 볼륨을 v3·v4.1로 하나씩: 순차 쓰기·읽기가 허용 오차(90~101%) 안이고 HTB rate가 결정 12의 값.
- 실행: `fr08_verify.py setup ac01a` (07:20), `ac01b` (07:21~07:28). (b)는 설계 예시 중 Ultra를 골랐다: v3는 **Ultra 80 GiB = 10 MiB/s**(설계가 적은 예), v4.1은 **Ultra 40 GiB = 5 MiB/s**(implementer e2e와 같은 크기). 두 한도를 함께 보려고 크기를 달리 했다. 클라이언트 `fr08v-c1` 하나가 둘을 마운트(기본 옵션 `rsize=wsize=1048576,hard,proto=tcp,timeo=600`, v3는 `nolock`).
- 출력 (a):

  | 볼륨 | PUT | 작업 status | `actualThroughputMibps` | `throughputMibps` | agent 레코드 qos | netns HTB rate (기대) |
  | --- | --- | --- | --- | --- | --- | --- |
  | Premium 101 GiB (NFSv3) | 201 | Creating → Succeeded | **6.312** | 없음 | 6.312 | 55362Kbit (55,362,708) |
  | Premium 1 GiB (NFSv3) | 201 | Creating → Succeeded | **0.062** | 없음 | 0.062 | 543800bit (543,804) |
  | Standard 1 GiB (NFSv4.1) | 201 | Creating → Succeeded | **0.016** | 없음 | 0.016 | 140336bit (140,336) |

  풀 GET: Premium 4 TiB Auto `utilizedThroughputMibps` **6.374** (= 6.312 + 0.062), Standard 1 TiB Auto **0.016**. 101 GiB 볼륨 삭제 뒤 Premium 풀 0.062. 모든 인스턴스에 `ifb0`, HTB 루트 `1:`, leaf `fq_codel 10:`, eth0 `clsact`, 방향마다 redirect 필터 하나.
- 출력 (b): PUT 201 Creating → Succeeded, `actualThroughputMibps` 10.0 / 5.0, `throughputMibps` 없음, 풀 Ultra 1 TiB Auto `utilizedThroughputMibps` 15.0. HTB rate 87710Kbit(기대 87,710,247) / 43855Kbit(기대 43,855,123). fio 직접 I/O(bs 1 MiB, iodepth 16, libaio, `clock_gettime`), 크기 한도 × 15 s, 회마다 앞서 `drop_caches`(읽기), 첫 회 버리고 5회 중앙값:

  | 볼륨 | 방향 | 회별 MiB/s (첫 회 포함 6회) | 중앙값 | 한도 대비 | 데이터/HTB Sent |
  | --- | --- | --- | --- | --- | --- |
  | Ultra 80 GiB, v3, 10 | 쓰기 | 9.812, 9.814, 9.807, 9.813, 9.808, 9.805 | 9.808 | **98.1%** | 0.9534~0.9537 |
  | 〃 | 읽기 | 9.722, 9.719, 9.750, 9.704, 9.739, 9.723 | 9.723 | **97.2%** | 0.9534~0.9537 |
  | Ultra 40 GiB, v4.1, 5 | 쓰기 | 4.955, 4.952, 4.957, 4.948, 4.955, 4.956 | 4.955 | **99.1%** | 0.9513~0.9521 |
  | 〃 | 읽기 | 4.955, 4.950, 4.956, 4.950, 4.955, 4.958 | 4.955 | **99.1%** | 0.9516~0.9520 |

  모든 회가 90~101% 안(최소 97.0%, 최대 99.2%), fio 오류 0. `ext4lazyinit` 스레드는 측정 내내 없었다. 메모리 available 6,906~6,975 MiB.
- 참고: 첫 실행은 드라이버 버그(`log()` 인자 이름 충돌)로 볼륨 생성 직후 멈췄다. 다시 실행할 때 같은 PUT이 200 Updating → Succeeded가 됐고 인스턴스 pid와 HTB는 그대로였다(같은 요청 재전송은 볼륨 설계대로 보장). 위 201은 첫 실행의 응답이다(`logs/fr08v.jsonl`).

### [PASS] AC-02 Manual 풀 볼륨 생성 (계약·데이터)
- 기준: Manual 풀(Ultra 40 TiB, 총 5,120 MiB/s)에 `throughputMibps: 10`(v4.1), `20`(v3) PUT → `201` → `Creating` → `Succeeded`. GET `throughputMibps` = `actualThroughputMibps` = 요청 값, 풀 `utilizedThroughputMibps` = 30. 순차 쓰기·읽기가 허용 오차 안. 소수 값(12.5)도 받고 그대로 건다.
- 실행: `fr08_verify.py ac02` (07:28~07:36). 1 GiB 볼륨, 클라이언트 `fr08v-c1`. 측정 방법은 AC-01 (b)와 같다.
- 출력:

  | 볼륨 | PUT 응답 (즉시 본문) | 작업 status | GET `throughputMibps` / `actualThroughputMibps` | 풀 `utilizedThroughputMibps` 뒤 | HTB rate (기대) |
  | --- | --- | --- | --- | --- | --- |
  | m10 (NFSv4.1, 10) | 201, `Creating`, 10.0/10.0, `Azure-AsyncOperation` 있음 | Creating → Succeeded | 10.0 / 10.0 | 10.0 | 87710Kbit (87,710,247) |
  | m20 (NFSv3, 20) | 201, `Creating`, 20.0/20.0 | Creating → Succeeded | 20.0 / 20.0 | **30.0** | 175420Kbit (175,420,494) |
  | m125 (NFSv4.1, **12.5**) | 201, `Creating`, 12.5/12.5 | Creating → Succeeded | 12.5 / 12.5 | 42.5 | 109637Kbit (109,637,808) |

  | 볼륨 | 방향 | 회별 MiB/s (첫 회 포함) | 중앙값 | 한도 대비 | 데이터/HTB Sent |
  | --- | --- | --- | --- | --- | --- |
  | m10 v4.1 | 쓰기 | 9.814, 9.810, 9.798, 9.716, 9.762, 9.785 | 9.785 | **97.8%** | 0.9535~0.9537 |
  | m10 v4.1 | 읽기 | 9.751, 9.732, 9.707, 9.710, 9.719, 9.737 | 9.719 | **97.2%** | 0.9534~0.9536 |
  | m20 v3 | 쓰기 | 19.492, 19.428, 19.431, 19.423, 19.438, 19.450 | 19.431 | **97.2%** | 0.9545~0.9547 |
  | m20 v3 | 읽기 | 19.094, 19.116, 19.119, 19.158, 19.095, 19.016 | 19.116 | **95.6%** | 0.9543~0.9545 |
  | m125 v4.1 | 쓰기 | 12.244, 12.181, 12.209, 12.183, 12.180, 12.160 | 12.181 | **97.5%** | 0.9538~0.9540 |

  모든 회가 90~101% 안(최소 95.1%, 최대 98.1%), fio 오류 0. 쓰기 clat 최대는 대기열(16 MiB) ÷ 한도와 맞다(10 → 3.06 s, 20 → 1.54 s, 12.5 → 2.46 s).

### [PASS] AC-03 읽기와 쓰기가 한도 하나를 나눠 씀 (데이터)
- 기준: 한 볼륨에 읽기 job 하나와 쓰기 job 하나를 15 s 동안 함께 돌린다. 합이 허용 오차 안(v3, v4.1).
- 실행: `fr08_verify.py ac03` (07:36~07:39). fio 한 명령에 job 둘(읽기 `/mX/f`, 쓰기 `/mX/g`), `--time_based --runtime=15`, 회마다 앞서 `drop_caches`, 첫 회 버림.
- 출력:

  | 볼륨 | 회별 읽기 + 쓰기 = 합 (MiB/s) | 합 중앙값 | 한도 대비 |
  | --- | --- | --- | --- |
  | m10 v4.1, 10 | (5.066+4.734=9.800), 5.069+4.738=9.807, 5.054+4.723=9.777, 5.054+4.724=9.779, 5.042+4.713=9.754, 5.055+4.725=9.780 | 9.779 | **97.8%** |
  | m20 v3, 20 | (10.980+8.316=19.295), 11.019+8.194=19.214, 10.864+8.441=19.305, 10.975+8.221=19.196, 11.020+8.174=19.194, 11.074+8.265=19.339 | 19.214 | **96.1%** |

  각 방향은 한도의 절반 안팎(읽기 5.05 / 쓰기 4.72, 읽기 11.0 / 쓰기 8.2)이고 합이 단독 측정(AC-02: 9.72~9.79, 19.12~19.43)과 같다. 읽기와 쓰기가 따로 한도를 받지 않고 한 버킷을 나눠 쓴다. fio 오류 0.

### [PASS] AC-04 쓰는 중 한도 변경 (데이터, PRD)
- 기준: 시간 기반 쓰기(v4.1)와 읽기(v3)를 각각 돌리는 중에 PATCH `throughputMibps` 10 → 30, 이어서 30 → 5. 매번 `202` → `Patching` → `Succeeded`. `Succeeded` 뒤 2 s 안의 1초 창이 새 한도의 90~101%. 끊긴 창 없음, 다시 마운트 안 함, fio 오류 0. 재PUT(`Updating`)도 한 번.
- 실행: `fr08_verify.py ac04` (07:40~07:42). 먼저 m20을 PATCH 10으로 맞춤(202 Patching → Succeeded 2.3 s). 그 뒤 클라이언트 `fr08v-c1`에서 m10(v4.1) 직접 쓰기, m20(v3) 직접 읽기를 각각 fio `--time_based --runtime=60`(bs 1 MiB, iodepth 16)으로 함께 돌리고, t≈15 s에 두 볼륨을 PATCH 30, t≈36 s에 PATCH 5. 1초 창은 호스트에서 `/proc/<인스턴스 pid>/net/dev`의 `ifb0` 송신 바이트를 0.25 s마다 읽어 만들었다(설계 §9-11 방식, 내 표본기). HTB 클래스 `Sent` 바이트 × 0.9564(약 1 s마다 `tc -s class`)로 교차 확인.
- 출력:

  | PATCH | 응답 (즉시 본문) | 작업 | 걸린 시간 | `Succeeded` 뒤 2 s 안의 1초 창 (MiB/s) | 새 한도 대비 |
  | --- | --- | --- | --- | --- | --- |
  | m10 10 → 30 | 202, `Patching`, 30.0 | Patching → Succeeded | 2.14 s | 29.28~29.49 | **97.6~98.3%** |
  | m20 10 → 30 | 202, `Patching`, 30.0 | Patching → Succeeded | 3.17 s | 29.25~29.43 | **97.5~98.1%** |
  | m10 30 → 5 | 202, `Patching`, 5.0 | Patching → Succeeded | 3.08 s | 4.975~5.040 | **99.5~100.8%** |
  | m20 30 → 5 | 202, `Patching`, 5.0 | Patching → Succeeded | 4.48 s | 5.010~5.025 | **100.2~100.5%** |

  - 끊긴 창 없음: 60 s 동안 1초 창의 최솟값이 m10 4.963, m20 4.985(5 MiB/s 구간). 표본이 빠진 구간 없음.
  - 다시 마운트 안 함: 측정 앞뒤 `/proc/self/mountstats`의 `xprt` connect 횟수 2 → 2(두 볼륨 모두). fio 오류 0, 두 job 모두 rc 0.
  - 따로 센 것: m10 쓰기가 30 MiB/s 구간 중 t≈24~37 s에 약 12 MiB/s로 떨어졌다. 같은 구간 HTB `Sent` 창도 같은 값이라 제한기가 막은 것이 아니고(대기열 없음), 설계가 따로 세라고 한 30 MiB/s 이상 쓰기의 서버 쪽 저하(S7 Q2)다. 판정 창(`Succeeded` 뒤 2 s)은 그 전이다.
  - 측정 잡음: 약 32 s마다 1초 창 하나가 1.55배로 튀었다(44.56, 7.79, 23.2). 이 단계까지는 표본 시각을 `time.time()`으로 찍었는데, WSL의 실시간 시계가 약 32 s마다 0.64 s 뒤로 물러난다(아래 "측정값"의 시계 절). 그 창의 길이가 실제보다 짧게 계산된 것이고, 판정 창에는 들지 않았다. ac06부터는 표본기를 `time.monotonic()`으로 바꿨다.
  - 재PUT: m10 GET 본문에 `throughputMibps: 15` → `200`, `Updating` → Succeeded 2.31 s. GET 15.0/15.0, HTB `131565Kbit`(기대 131,565,370). `Succeeded` 뒤 2 s 안의 창 14.63~14.77 (**97.5~98.5%**).

### [PASS] AC-05 제한 없는 볼륨과의 차이, 독립성 (데이터) — 읽기로 판정, 쓰기는 참고
- 기준: 같은 클라이언트가 10 MiB/s 볼륨 A와 4,500 MiB/s 볼륨 B를 마운트. 함께 쓰는 동안 B가 A의 10배 이상, A는 허용 오차 안. A만일 때와 함께일 때 A 값의 차이가 허용 오차 안. 설계 §9-11과 리더 지시대로 **읽기로 판정**하고("함께 사용하는 동안", 차이는 허용 오차 띠의 너비 = 한도의 11% 이하), 짧은 쓰기 표본(B 쓰기 2 GiB 이하)을 참고로 붙였다.
- 실행: `fr08_verify.py ac05` (07:42~07:47), 쓰기 표본 두 번 더 `ac05w` (07:57~07:58). Manual 풀 `man-ultra`에 A = a10(1 GiB, NFSv4.1, 10), B = b4500(4 GiB, NFSv4.1, 4,500), 클라이언트 `fr08v-c5` 하나가 둘을 마운트. 준비: A에 150 MiB, B에 1 GiB 파일.
- 출력:
  - 생성: 둘 다 201 → Creating → Succeeded. GET A 10.0/10.0, B 4500.0/4500.0. HTB A 87710000bit(기대 87,710,247), B **39469000000bit**(기대 39,469,611,041, 39.5 Gbit). 방향마다 필터 하나.
  - 읽기(판정):

    | 측정 | 회별 (첫 회 포함) | 중앙값 | |
    | --- | --- | --- | --- |
    | A만 (크기 150 MiB, 회마다 `drop_caches`) | 9.835, 9.766, 9.719, 9.714, 9.709, 9.705 | 9.714 | 97.1% |
    | B만 (1 GiB 파일, 서버 캐시, 15 s 시간 기반) | 2127.0, 2132.0, 2254.2 | — | — |
    | 함께: A (15 s 시간 기반, 한 fio에 job 둘) | 9.922, 9.934, 9.925, 9.925, 9.925, 9.919 | **9.925** | **99.25%** |
    | 함께: B | 1939.3, 2027.9, 2035.7, 2041.9, 2129.4, 2080.4 | **2041.9** | B/A = **205.7배** |

    A만과 함께의 차 0.211 MiB/s (허용 오차 띠 너비 1.1 이하). 함께일 때 A가 조금 높은 것은 A만 측정이 크기 기반(마지막 RPC가 빠지는 꼬리 포함)이고 함께 측정이 시간 기반이라서다. fio 오류 0.
  - 쓰기(참고, 판정에 쓰지 않음):

    | 표본 | A 쓰기 (15 s 시간 기반) | B 쓰기 (2 GiB 고정) | B/A | A의 `ifb0` 대기열(1 s마다) |
    | --- | --- | --- | --- | --- |
    | A만 | 9.866 (98.7%) | — | — | — |
    | 함께 1 (ac05) | **8.563 (85.6%)** | 63.44 | 7.4 | (안 봄) |
    | 함께 2 (ac05w) | **7.062 (70.6%)** | 43.74 | 6.2 | A 쓰기 동안 18회 중 0 B 7회, 35~71 KB 11회 |
    | 함께 3 (ac05w) | **7.336 (73.4%)** | 75.33 | 10.3 | 17회 중 0 B 8회, 36~139 KB 9회 |

    B가 디스크에 쓰는 동안 A 쓰기가 한도의 71~86%로 떨어졌다. A의 HTB 클래스는 rate = ceil이라 대기열에 패킷이 있으면 한도로 내보낸다. 출력이 한도의 71~73%였고 대기열이 빈 표본이 40~47%였으니, A로 들어오는 양 자체가 한도보다 적었다. 찼을 때의 대기열도 35~139 KB(10 MiB/s에서 3~14 ms)로 1 MiB RPC 하나를 고르게 내보내는 정도다. 즉 A의 제한기가 A를 한도 밑으로 누른 것이 아니다. 두 볼륨이 같은 aggregate(`aggr0.img` 희소 파일 하나, WSL 가상 디스크)를 쓰므로 서버 디스크 경합으로 본다. 읽기(서버 캐시)는 영향을 받지 않았다. 설계 문구를 글자 그대로("함께 쓰는 동안") 읽으면 쓰기 표본은 기준을 채우지 못한다. 리더 결정 사항으로 올린다(아래).

### [PASS] AC-06 작은 Auto 한도 (데이터)
- 기준: 1 GiB Premium Auto 볼륨(0.062 MiB/s)을 v3와 v4.1로 마운트. 작은 파일 쓰기·읽기·`ls`가 오류 없이 된다. 큰 직접 쓰기의 처리량이 0.062 × 1.01 이하. 같은 연결·다른 연결의 메타데이터 지연, mountstats timeouts, dmesg 기록(판정은 오류 0과 상한).
- 실행: `fr08_verify.py ac06` (07:47~07:48). v3는 AC-01 (a)의 p1(Premium 1 GiB NFSv3), v4.1은 새 p1b(Premium 1 GiB NFSv4.1, 201 → Succeeded, `actualThroughputMibps` 0.062, HTB 543800bit). 클라이언트 둘(`fr08v-c6a` = 큰 쓰기와 같은 연결, `fr08v-c6b` = 다른 연결)이 각각 두 볼륨을 마운트. 큰 쓰기는 c6a에서 두 볼륨에 동시에 fio `--direct=1 --bs=64k --iodepth=1 --time_based --runtime=30 --fallocate=none`(설계 §9-11). 그동안 3 s, 10 s, 17 s에 두 클라이언트에서 `ls`와 `dd bs=4k count=1 conv=fsync` 지연을 쟀다.
- 출력:
  - 작은 파일: 두 볼륨 모두 c6a에서 `echo > small`, `cat`, `ls -la` rc 0, c6b에서 `cat`·`ls` rc 0(내용 `hello-p1`, `hello-p1b`).
  - 큰 직접 쓰기: p1(v3) **0.0598 MiB/s**(1,900,544 B / 30.287 s), p1b(v4.1) **0.0597 MiB/s**(1,900,544 B / 30.344 s). 상한 0.06262 이하(한도 대비 96.5%, 96.3%). fio 오류 0, clat 최대 1.19 s / 1.17 s.
  - 메타데이터 지연(3회):

    | 볼륨 | 연결 | `ls` (s) | 4 KiB `dd` + fsync (s) |
    | --- | --- | --- | --- |
    | p1 v3 | 같은 연결 | 1.27, 1.55, 0.00 | 1.11, 1.14, 0.12 |
    | p1 v3 | 다른 연결 | 0.11, 0.03, 0.00 | 0.26, 0.22, 0.08 |
    | p1b v4.1 | 같은 연결 | 0.15, 1.35, 0.00 | 2.15, 2.18, 0.13 |
    | p1b v4.1 | 다른 연결 | 0.05, 0.10, 0.00 | 0.36, 0.32, 0.10 |

    세 번째 회는 큰 쓰기가 끝난 뒤였다. 모든 명령 rc 0.
  - dmesg: 측정 동안 nfs·rpc 줄 0개(`server not responding` 없음). S7 Q4(같은 연결 메타데이터가 1분 넘음, RPC 시간 초과)보다 훨씬 짧은 것은 큰 쓰기가 bs 64 KiB·iodepth 1이라 대기열이 64 KiB뿐이기 때문이다.
  - mountstats: 드라이버의 `awk` 범위가 시작 줄에서 바로 끝나 단계 로그에는 빈 값이 남았다. 단계가 끝난 뒤(07:53, 마운트 그대로) c6a의 `/proc/self/mountstats`를 다시 읽었다. 두 볼륨 모두 모든 연산의 timeouts 0, ops = trans(재전송 없음). WRITE p1 33회 1,918,652 B, RTT 합 32,295 ms / p1b 33회 1,920,960 B, 32,407 ms(회당 약 0.98 s = 64 KiB ÷ 0.062 MiB/s). errors는 LOOKUP 1(파일을 만들기 전 이름 조회, ENOENT)뿐. `xprt` connect 횟수 2(마운트 때).
  - 끝난 뒤 `ls -la`에 `big`(1,900,544 B), `probe-same`, `probe-other`, `small`이 보인다.

### [PASS] AC-07 수명 주기 (데이터)
- 기준: 한도를 건 볼륨에서 각 단계 직후(10 s 안에 시작한 측정) 한도가 허용 오차 안. 제한 없는 창이 있으면 길이를 기록. (a) agent만 재시작, (b) 인스턴스 `docker stop` → agent 재시작(복구의 `docker start`), (c) 인스턴스 `docker rm` → 같은 볼륨 재PUT(agent `docker run`), (d) 쓰는 중 스냅샷 되돌리기, (e) 한도 건 볼륨의 스냅샷에서 새 볼륨 복원(Manual X, Auto 공식), (f) 볼륨 삭제: 호스트 IFB 없음, netns 사라짐.
- 실행: `fr08_verify.py ac07_setup ac07a … ac07f` (07:58~08:07). 볼륨 lc = Manual 풀 `man-ultra`의 2 GiB NFSv4.1, `throughputMibps` 10(HTB 87710000bit), 200 MiB 파일을 쓰고(9.856 MiB/s) 스냅샷 s1(201 → Succeeded). 클라이언트 `fr08v-c7`. (a)~(d)는 fio 시간 기반 쓰기(bs 1 MiB, iodepth 16)를 계속 돌리는 중에 단계를 하고, 호스트 표본기(0.25 s마다 `/proc/<pid>/net/dev`의 `ifb0`·`eth0` 바이트, 1 s마다 HTB `Sent`)로 1초 창을 만들었다. 판정 창 = 단계가 끝난 뒤 I/O가 다시 흐른 때(창 > 한도의 30%)부터 15 s의 1초 창 중앙값(설계 §9-11). "제한 없는 창"은 `ifb0` 창 > 한도 × 1.01 또는 `eth0` 창 > 한도 × 1.5(ifb를 거치지 않은 흐름)로 찾았다(단계 30 s 전부터 끝까지).
- 출력:

  | 단계 | 동작과 걸린 시간 | 인스턴스 pid | 단계 뒤 tc | I/O 멈춤 | 판정 창 15 s (중앙값 / 최소~최대) | 한도 대비 | 제한 없는 창 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | (a) agent만 재시작 | `agent-stop` → `agent-start` 18.3 s(시작 복구 17.4 s) | 46378 그대로 | 87710000bit, 필터 1/1 | 없음(창이 계속 9.5~10.05) | 9.816 / 8.909~9.949 | **98.2%** | 없음 |
  | (b) `docker stop` → agent 재시작 | stop 0.39 s, agent 준비까지 25.5 s(시작 24.2 s) | 46378 → **50211** | 87710000bit, 필터 1/1 | 약 21.6 s(stop부터, 새 인스턴스는 14.5 s 뒤 떴고 I/O는 그 7.3 s 뒤 흐름) | 9.847 / 9.742~9.947 | **98.5%** | 없음 |
  | (c) `docker rm -f` → 재PUT | 재PUT `200` `Updating` → Succeeded 2.32 s | 50211 → **51589** | 87710000bit, 필터 1/1 | 약 2.6 s | 9.843 / 5.249~9.908 | **98.4%** | 없음 |
  | (d) 쓰는 중 되돌리기(s1) | POST `202` → `Reverting` → Succeeded 5.24 s | 51589 그대로 | 87710000bit, 필터 1/1 | POST 0.9 s 뒤부터 약 2.5 s(차단 창) | 9.818 / 9.639~9.928 | **98.2%** | 없음 |

  - (a) 재시작 앞 20 s의 창은 9.94~10.05(`ifb0` 송신 바이트는 데이터보다 약 1% 많다, AC-09 per-run `data_per_ifbtx` 0.99), 뒤는 9.5~9.95. 재시작 뒤 12.8~14.4 s, 19.4~19.9 s에 8.7~9.2로 내려간 창은 서버 쪽 지연이고 위로 넘친 창은 없다. fio 9.795 MiB/s, 오류 0.
  - (b) 새 pid의 첫 표본(t = 3540.32)에는 `ifb0`가 아직 없었고 다음 표본(0.25 s 뒤)부터 있었다. 그사이 `eth0`로 흐른 바이트는 없다(I/O는 7.3 s 뒤 시작). 즉 knfsd가 서비스하기 전에 한도가 걸렸다. fio 오류 0, clat 최대 27.1 s, 150 s 평균 8.222(멈춤 포함).
  - (c) 새 pid 첫 표본 3679.85, `ifb0`는 3680.10부터, I/O는 3681 안팎에 다시 흐름. 판정 창 최소 5.249는 다시 흐르기 시작한 첫 1초 창(앞쪽이 빈 창)이다. fio 오류 0, clat 최대 8.16 s.
  - (d) POST 직전 창 9.73~9.79 → POST 0.08~0.86 s에 8.4 → 1.1로 줄고 1.1~3.1 s 동안 0 → 3.4 s부터 다시 흐르고 4.4 s에 9.81. 다시 마운트하지 않았다(같은 마운트로 fio가 이어 씀). fio 오류 0, clat 최대 6.68 s.
  - (e) Manual 복원: rm7 = 같은 풀에 lc/s1에서 `throughputMibps: 7`(원본 10과 다르게) → `201` `Creating`(본문 7.0/7.0, 두 추적 헤더) → Succeeded. GET 7.0/7.0, `originatingResourceId` = lc/snapshots/s1, HTB **61397000bit**(기대 61,397,173). 쓰기 6.890, 6.918, 6.918, 6.917, 6.906, 6.905 → 중앙값 6.917 (**98.8%**), 오류 0. Auto 복원: ra = Auto 풀 `auto-prem`에 2 GiB, 같은 s1 → 201 → Succeeded, GET `throughputMibps` 없음 / `actualThroughputMibps` **0.125**(2 GiB × 64 / 1024), agent 레코드 `qos.policy.max_throughput_mbps` 0.125, HTB 1096Kbit(기대 1,096,378; tc가 Kbit로 보임). 둘 다 DELETE 202 → Succeeded.
  - (f) lc DELETE `202` → `Deleting` → Succeeded. 그 뒤 인스턴스 pid 51589 없음, 그 netns(`net:[4026534638]`)가 `lsns -t net`에 없음, 컨테이너 없음, 호스트 IFB 앞 `[]` / 뒤 `[]`, 호스트 링크 수 26 → 25(인스턴스 veth 하나가 사라짐).

### [PASS] AC-08 거절 (계약)
- 기준: §4.2의 각 행이 그 코드와 문구다. 거절이면 볼륨 행·작업이 생기지 않고 기존 `throughputMibps`·풀 값·netns HTB rate가 그대로다. 예산 안의 경계 값(정확히 남은 예산)은 받는다.
- 실행: `fr08_verify.py ac08` (07:48). Manual 풀 `man-small` = Premium 2 TiB Manual(총 128 MiB/s). DB 행 수는 `setpriv`로 anf-api DB를 읽기 전용으로 열어 셌다(`resources`, `operations`).
- 출력:

  | 사례 | 응답 | 문구 | 뒤 DB (작업/자원), 행 |
  | --- | --- | --- | --- |
  | Manual 풀 생성, 값 없음 | 400 `InvalidRequestContent` | "The 'properties.throughputMibps' property is required for a volume in a Manual QoS capacity pool." | 28/18 그대로, GET 404 |
  | 〃 `null` | 400 `InvalidRequestContent` | 위와 같음 | 그대로, 404 |
  | 〃 `0.5`, `4500.5`, `"10"`, `true`, `0`, `4501` | 400 `InvalidRequestContent` (6개 모두) | "The 'properties.throughputMibps' property must be a number from 1 to 4500." | 그대로, 404 |
  | Auto 풀 생성에 `10` | 400 `BadRequest` | "The 'properties.throughputMibps' property can be set only for a volume in a Manual QoS capacity pool." | 그대로, 404 |
  | Auto 풀 생성에 `null` (받아야 함) | 201 → Succeeded, `actualThroughputMibps` 0.062, `throughputMibps` 없음 | — | 29/19 (지운 뒤 30/18) |
  | Auto 볼륨 p1 PATCH `10` | 400 `BadRequest` | Auto 풀 문구 | 30/18 그대로. p1 GET·HTB 543800bit 앞뒤 같음 |
  | 예산: bud1 = 100 만든 뒤 bud2 = 30 | 400 `BadRequest` | "Requested throughput not available. Capacity pool 'man-small' has 128.0 MiB/s in total and 28.0 MiB/s left for this volume." | 31/19 그대로, 404, 풀 utilized 100.0 |
  | bud2 = 28.0005 (셋째 자리 반올림이 28.0) | 201 → Succeeded (설계 §9-3: 예산 비교는 셋째 자리) | — | 만든 뒤 지움 |
  | bud2 = 28.001 | 400 `BadRequest` | 같은 예산 문구(28.0 left) | 33/19 그대로, 404 |
  | **bud2 = 28 (정확히 남은 예산)** | **201 → Succeeded**, GET 28.0/28.0, 풀 utilized **128.0**, HTB 245588000bit(기대 245,588,691) | — | — |
  | bud2 PATCH 29 | 400 `BadRequest` | 예산 문구, "28.0 MiB/s left" | 34/20 그대로 |
  | bud1 PATCH 101 | 400 `BadRequest` | 예산 문구, "100.0 MiB/s left" | 그대로 |
  | bud2 재PUT(GET 본문 + 40) | 400 `BadRequest` | 예산 문구, "28.0 MiB/s left" | 그대로 |
  | Manual 풀 크기 PATCH 2 → 1 TiB | 400 `BadRequest` | "The capacity pool throughput of 64.0 MiB/s is too small for the combined volume throughput of 128.0 MiB/s of the capacity pool." | 그대로, 풀 2 TiB·128.0 그대로 |
  | bud2 PATCH `0.5`, `4500.5`, `"10"`, `true` | 400 `InvalidRequestContent` (4개) | 범위 문구 | 그대로 |
  | 없는 볼륨 PATCH `0.5` | 404 `ResourceNotFound` | 경로 검사가 먼저 | 그대로 |
  | Manual → Auto | 400 `BadRequest` | "The QoS type of a capacity pool can't be changed from Manual to Auto." (기존 문구) | 그대로, 풀 Manual |
  | 볼륨 생성 중(201 직후) Auto 풀 `sw-busy` → Manual | **409 `Conflict`** | "Cannot change the QoS type of capacity pool '…/capacityPools/sw-busy' because an operation is in progress on volume '…/sw-busy/volumes/busy1'. Wait until it is finished, and then retry." | 작업은 볼륨 생성 것 하나만(35/21), 풀 Auto 그대로. 생성은 뒤에 Succeeded |

  - 거절 앞뒤 비교(bud2 PATCH 29부터 없는 볼륨 PATCH까지): bud1·bud2 GET, 풀 GET, 두 인스턴스의 netns HTB(rate 877102000bit = 100 MiB/s, 245588000bit = 28 MiB/s, 필터 수)가 JSON으로 같다(`same: true`).

### [PASS] AC-09 Auto → Manual 전환 (계약·데이터)
- 기준: Auto Premium 풀에 볼륨 둘(예: 160 GiB, 1 GiB)을 두고 풀 PATCH `qosType: Manual`. `Succeeded` 뒤 볼륨 GET `throughputMibps` = 전환 전 `actualThroughputMibps`, 풀 `utilizedThroughputMibps` 그대로. 큰 볼륨의 잰 처리량이 전환 전과 같다(허용 오차 안). 그 뒤 PATCH `throughputMibps`가 받아지고 한도가 바뀐다.
- 실행: `fr08_verify.py ac09` (07:48~07:56). 풀 `sw-prem` = Premium 1 TiB Auto(총 64). 볼륨 w80 = **Premium 80 GiB(5 MiB/s)** NFSv3, w1 = Premium 1 GiB(0.062) NFSv4.1. 160 GiB 대신 80 GiB를 쓴 이유는 설계 §9-11과 같다(ext4 inode 표 0 채우기가 크기에 비례). 측정 중 `ext4lazyinit` 없음. 측정은 AC-01 (b)와 같은 방법(크기 한도 × 15 s, 첫 회 버림, 5회 중앙값), 클라이언트 `fr08v-c9`.
- 출력:

  | 시점 | w80 GET (`throughputMibps` / `actualThroughputMibps`) | w1 GET | 풀 GET (`qosType`, total, utilized) | w80 HTB (pid) | w1 HTB (pid) |
  | --- | --- | --- | --- | --- | --- |
  | 전환 전 | 없음 / 5.0 | 없음 / 0.062 | Auto, 64.0, **5.062** | 43855000bit (43474) | 543800bit (43666) |
  | 풀 PATCH `qosType: Manual` → 202 `Patching` → Succeeded (0.04 s) 뒤 | **5.0 / 5.0** | **0.062 / 0.062** | **Manual**, 64.0, **5.062** | 43855000bit (43474) | 543800bit (43666) |
  | w80 PATCH 8 → 202 `Patching`(본문 8.0) → Succeeded 2.32 s 뒤 | 8.0 / 8.0 | — | Manual, 64.0, 8.062 | **70168000bit** (기대 70,168,197, 43474) | — |

  | w80 측정 | 회별 MiB/s (첫 회 포함) | 중앙값 | 한도 대비 |
  | --- | --- | --- | --- |
  | 전환 전 쓰기 | 4.955, 4.959, 4.959, 4.956, 4.956, 4.957 | 4.957 | 99.1% |
  | 전환 전 읽기 | 4.953, 4.954, 4.957, 4.954, 4.954, 4.956 | 4.954 | 99.1% |
  | 전환 뒤 쓰기 | 4.959, 4.953, 4.955, 4.956, 4.959, 4.956 | 4.956 | **99.1%** (전과 차 −0.0006) |
  | 전환 뒤 읽기 | 4.954, 4.951, 4.952, 4.950, 4.957, 4.956 | 4.952 | **99.0%** (전과 차 −0.0023) |
  | PATCH 8 뒤 쓰기 | 7.863, 7.857, 7.866, 7.858, 7.853, 7.845 | 7.857 | **98.2%** (한도 8) |

  - 전환은 인스턴스와 tc를 건드리지 않았다(같은 pid, 같은 rate). fio 오류 0.
  - 옮겨 받은 1 MiB/s 미만 값: w1 GET 본문 그대로 재PUT → `200` `Updating` → Succeeded, GET 0.062 / 0.062, HTB 543800bit 그대로. 0b44a8f("unchanged throughput limit below 1 MiB/s")가 고친 경로다.

### [PASS] AC-10 실패와 재시작 안전 (상태)
- 기준: (a) `volumes/patch`에 지연 주입, `Patching`인 동안 anf-api SIGKILL 후 다시 띄우면 작업 `Succeeded`, netns HTB rate와 잰 값이 새 한도. (b) `volumes/patch`에 실패 주입 → 작업 `Failed`, 볼륨 `throughputMibps`가 이전 값. 주입을 끄고 같은 PATCH → `Succeeded`, 새 한도.
- 실행: `fr08_verify.py ac10a ac10b` (08:07~08:11). 대상 m10(Manual Ultra, NFSv4.1, AC-04 재PUT 뒤 15 MiB/s), 클라이언트 `fr08v-c1`. anf-api는 `svc.sh`로 멈추고 `ANF_FAULT_INJECTION`을 주어 다시 띄웠다(같은 DB).
- 출력 (a):
  - 주입 `{"volumes/patch": {"delaySeconds": 30}}`로 띄운 뒤 PATCH 17 → `202`, 본문 `Patching`.
  - 4 s 뒤: 볼륨 GET `Patching`(본문 값 17.0), 작업 GET `status: Patching`, `percentComplete` 0, **netns HTB는 아직 131565000bit(15 MiB/s)**. 즉 agent에 아직 보내지 않았다.
  - `api-kill`(SIGKILL, pid 53491 사라짐) → 1 s 뒤 주입 없이 다시 띄움(pid 53534, 0 s 만에 포트 준비).
  - 같은 작업 URL 폴링: `Patching` → **`Succeeded`**, 보낸 때부터 8.77 s. 볼륨 GET Succeeded 17.0/17.0, HTB **149107000bit**(기대 149,107,419), 같은 인스턴스 pid 34788.
  - 쓰기 16.620, 16.513, 16.551, 16.532, 16.516, 16.553 → 중앙값 16.532 (**97.2%**), 오류 0.
- 출력 (b):
  - 주입 `{"volumes/patch": {"fail": true}}`로 다시 띄운 뒤 PATCH 9 → `202` `Patching` → 작업 **`Failed`** (0.1 s), `error.code` `InternalServerError`, "Injected fault: volumes/patch (ANF_FAULT_INJECTION)."
  - 볼륨 GET `provisioningState: Failed`, `throughputMibps` **17.0**(이전 값), `actualThroughputMibps` 17.0. HTB 149107000bit 그대로.
  - 주입 없이 다시 띄우고 같은 PATCH 9 → `202` `Patching` → **Succeeded** 2.42 s. GET 9.0/9.0, HTB **78939000bit**(기대 78,939,222), pid 그대로.
  - 쓰기 8.825, 8.829, 8.839, 8.833, 8.826, 8.844 → 중앙값 8.833 (**98.2%**), 오류 0.

### [FAIL] AC-12 회귀 — 시험 코드 결함 하나 (제품 코드 아님)
- 기준: 계정·풀·볼륨·스냅샷·되돌리기·복원 e2e(`backend/tests/e2e`의 모든 `*_live.py`, 파일 하나씩), 통합 테스트, 단위·계약 테스트가 새 코드에서 통과(skip 0). 기존 데이터 e2e의 걸린 시간을 FR-07 회귀 때와 비교(결정 17).
- 실행: WSL root, 저장소 루트에서 파일마다 `pytest2.sh`(`sync; echo 3 > /proc/sys/vm/drop_caches` → `ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/root/fr08-e2e/<label>.jsonl /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider <파일> -v -rs` → 남은 `anf*` 컨테이너·LV·IFB·포트 확인 → 로그를 scratchpad `logs/pytest/`로 복사). 16개 파일을 `regress2.sh`로 차례로(08:16~09:36). 각 파일의 agent·anf-api는 e2e 픽스처가 직접 띄우고 멈춘다(내 서비스는 먼저 멈춤).
- 출력 — e2e (모두 skip 0, 파일마다 끝난 뒤 남은 컨테이너·LV·IFB·포트 0):

  | 파일 | 결과 | pytest 시간 (게스트 단조) | 벽시계 (`date`) | FR-07 회귀 | 차이 |
  | --- | --- | --- | --- | --- | --- |
  | `test_netapp_account_live.py` | 16 passed | 3.93 s | 5 s | 2 s | (서버 기동 포함, 작음) |
  | `test_netapp_account_lro_faults_live.py` | 8 passed | 38.02 s | 39 s | 38 s | 0% |
  | `test_capacity_pool_live.py` | 30 passed | 2.48 s | 3 s | 3 s | — |
  | `test_capacity_pool_lro_faults_live.py` | 9 passed | 68.67 s | 68 s | 69 s | −0.5% |
  | `test_volume_contract_live.py` | 7 passed | 117.87 s | 117 s | 109 s | +8% |
  | `test_volume_data_live.py` | 7 passed | 204.27 s | 200 s | 192 s | +6% |
  | `test_volume_recovery_live.py` | 7 passed | 156.45 s | 154 s | 165 s | −5% |
  | `test_snapshot_contract_live.py` | 5 passed | 102.82 s | 100 s | 107 s | −4% |
  | `test_snapshot_data_live.py` | 8 passed | 183.87 s | 181 s | 173 s | +6% |
  | `test_snapshot_recovery_live.py` | 5 passed | 249.12 s | 244 s | 254 s | −2% |
  | `test_snapshot_revert_contract_live.py` | 11 passed | 509.63 s | 499 s | 508 s | 0% |
  | `test_snapshot_revert_data_live.py` | 5 passed | 157.99 s | 155 s | 160 s | −1% |
  | `test_restore_new_volume_data_live.py` | 5 passed | 224.37 s | 220 s | 179 s | **+25%** |
  | `test_restore_new_volume_contract_live.py` | 8 passed | 365.24 s | 357 s | 367 s | 0% |
  | `test_throughput_limit_contract_live.py` | 8 passed | 245.51 s | 240 s | (새 파일) | — |
  | `test_throughput_limit_data_live.py` | **1 failed**, 6 passed | 2274.28 s | 2219 s | (새 파일) | — |

  - 기존 14개 파일 합: 2,384.7 s (FR-07 2,326 s, +2.5%). 결정 17의 데이터 쓰기 파일 6개(볼륨 데이터, 스냅샷 데이터, 되돌리기 계약·데이터, 복원 계약·데이터) 합: 1,645.4 s (FR-07 1,579 s, **+4.2%**). pytest 시간은 게스트 단조 시계라 이번 부팅에서는 실제보다 약 2% 길게 나온다(위 시계 절. 벽시계 열이 그만큼 짧다). FR-07 때의 시계 비율은 모른다.
  - 늘어난 곳은 데이터를 많이 쓰는 시험뿐이다(FR-07 `/root/e2e-logs`와 시험별 비교): 복원 AC-05(1,200 MiB + 채우기) 32.6 → 76.6 s, 볼륨 AC-04 할당량 채우기(1,229 MiB) v3 14.4 → 30.3 s · v4.1 12.3 → 33.6 s, 스냅샷 AC-05 31.3 → 42.3 s. `manual_data` 픽스처의 64 MiB/s 한도가 실제로 걸린 결과다. 나머지 시험은 ±2 s 안이다.
  - 첫 시도(`reg-*`, 로그를 `/mnt/c`에 바로 씀)는 시간이 부풀어 판정에 쓰지 않았다("검증 방법과 드라이버에 관한 기록").
- 출력 — 그 밖:
  - 통합(WSL root, `backend/tests/integration`): 30 passed, skip 0, 383.51 s (07:14, AC-11 참고).
  - 단위·계약 Windows(`.venv-win`): 914 passed, 0 skipped (101 s, 07:05).
  - 단위·계약 WSL(일반 사용자 `mkimhome1`, `~/.venvs/anf-clone`): `python -m pytest -p no:cacheprovider backend/tests/unit backend/tests/contract -q` → **914 passed in 92.95 s**, skip 줄 없음(09:38).
- **FAIL 내용**: `test_throughput_limit_data_live.py::test_ac07_limit_survives_lifecycle`
  - 재현: WSL root에서 `ANF_E2E_API_URL=http://127.0.0.1:8080 ~mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider backend/tests/e2e/test_throughput_limit_data_live.py -k ac07 -v`. 게스트 실시간 시계가 주기적으로 뒤로 물러나는 부팅에서 재현된다(아래 확인 명령).
  - 실제 출력: `backend/tests/e2e/test_throughput_limit_data_live.py:377: AssertionError: ('a agent restart', [(1794245167.088, 17.332), (1794245167.589, 17.312)])`. 증거 기록(`logs/pytest/reg2-throughput_limit_data.jsonl`)의 단계별 `over_limit`: (a) 17.33·17.31, (b) 16.70·16.70·17.03·17.03·17.19·17.18·17.39·17.37, (c) 17.74·17.75·17.04·17.03·16.57·16.60·16.82·16.80·16.86·16.88, (d) 16.66·16.66 MiB/s(한도 10). 같은 기록의 판정 창 중앙값은 9.94·9.95·9.96·9.95로 모두 허용 오차 안, fio 오류 0, tc rate 87710000bit.
  - 기대값: `over_limit` 빈 목록(한도 × 1.01 = 10.1을 넘는 1초 창 없음).
  - 원인(시험 코드): 표본 시각을 `time.time()`으로 찍는다 — `backend/tests/e2e/throughput_live.py:161` (`self.samples.append((time.time(), pid, sent))`), 단계 시각도 `backend/tests/e2e/test_throughput_limit_data_live.py:296`·`:298`. 이 부팅의 WSL 실시간은 약 32 s마다 0.85 s씩 뒤로 물러난다(09:35 확인: `python3`로 0.05 s마다 `time.time()`과 `time.monotonic()`을 비교 → 계단 −0.846, −0.875, −0.854 s, 간격 32.3, 32.2 s). 계단을 품은 1초 창은 길이가 실제보다 짧게 계산돼 약 1.7배로 보인다. 근거: (1) `over_limit` 창이 0.5 s 간격의 두 창씩 짝을 이루고, 짝 사이가 31.3~31.7 s로 계단 주기(실시간으로 약 31.4 s)와 같다. (b)의 마지막 짝(…324.235)에서 09:35의 계단(…732.49)까지 408.3 s = 13.0주기다. (2) 인스턴스가 바뀌지 않은 (a)·(d)에도 나온다. (3) 같은 종류의 단계를 단조 시계로 잰 이 검증의 AC-07에서는 `ifb0` 창 > 1.01× 0개, `eth0` 창 > 1.5× 0개였고 HTB `Sent` 창도 한도 밑이었다.
  - 제품 코드 결함 아님: 제한기 동작은 AC-07(이 검증)이 직접 보였다.
  - 수정 제안: `throughput_live.py:161`과 `test_throughput_limit_data_live.py:128·144·296·298`의 `time.time()`을 `time.monotonic()`으로 바꾼다(`:128·144`의 AC-04 시험은 판정 창이 계단을 피해 이번에는 통과했지만 같은 위험이 있다). 이 검증의 드라이버도 같은 이유로 ac06부터 `time.monotonic()`을 쓴다.

## 측정값

### 처리량 측정 모음 (게스트 단조 시계 기준, 허용 오차 90~101%)
| 기준 | 한도 (MiB/s) | 방식 | 판정 값 (중앙값 또는 창) | 한도 대비 |
| --- | --- | --- | --- | --- |
| AC-01 (b) | 10 (Auto Ultra 80 GiB, v3) | 쓰기 / 읽기 5회 중앙값 | 9.808 / 9.723 | 98.1% / 97.2% |
| AC-01 (b) | 5 (Auto Ultra 40 GiB, v4.1) | 쓰기 / 읽기 | 4.955 / 4.955 | 99.1% / 99.1% |
| AC-02 | 10 / 20 / 12.5 (Manual) | 쓰기 / 읽기 | 9.785·9.719 / 19.431·19.116 / 12.181 | 95.6~97.8% |
| AC-03 | 10 / 20 | 읽기 + 쓰기 합 | 9.779 / 19.214 | 97.8% / 96.1% |
| AC-04 | 30 → 5 (PATCH), 15 (재PUT) | `Succeeded` 뒤 2 s 안의 1초 창 | 29.25~29.49 / 4.975~5.040 / 14.63~14.77 | 97.5~100.8% |
| AC-05 | 10 (B = 4,500과 함께) | 읽기 중앙값 | A만 9.714, 함께 9.925 | 97.1% / 99.25% |
| AC-06 | 0.062 (Auto Premium 1 GiB) | 30 s 직접 쓰기 (bs 64 KiB) | 0.0598 / 0.0597 | 96.5% / 96.3% (상한 101%) |
| AC-07 | 10, 복원 7 | 단계 뒤 15 s 창 중앙값, 복원은 쓰기 중앙값 | 9.816 / 9.847 / 9.843 / 9.818, 6.917 | 98.2~98.8% |
| AC-09 | 5 → (전환) 5 → 8 | 쓰기·읽기 중앙값 | 4.957·4.954 → 4.956·4.952 → 7.857 | 98.2~99.1% |
| AC-10 | 17, 9 | 쓰기 중앙값 | 16.532, 8.833 | 97.2%, 98.2% |

- 판정에 쓴 값 중 101%를 넘은 것은 없다(최대 AC-04의 1초 창 100.8%). 90% 밑으로 간 것은 AC-04에서 따로 센 30 MiB/s 쓰기의 서버 쪽 저하 구간(판정 창 밖)과 AC-05의 쓰기 참고 표본뿐이다.
- 데이터 / HTB `Sent` 바이트: 쓰기·읽기 모두 0.951~0.955(결정 12의 이론 상한 0.9564 밑). 데이터 / `ifb0` 송신 바이트: 0.989~0.993.
- 모든 fio 실행의 오류 0.

### 시계 (결정 15의 게스트/호스트 비율)
| 측정 | 때 | 길이 | 게스트 `time.monotonic()` / 호스트 Stopwatch | 게스트 `time.time()` / 호스트 | 호출 지연 |
| --- | --- | --- | --- | --- | --- |
| clock1 | 07:04~07:09 (WSL 부팅 직후) | 300.743 s | **1.0023** | — | 최대 1.24 s |
| clock2 | 07:45~07:52 (AC-05~09 측정 중) | 400.337 s | **1.0205** | 0.9993 | 0.39 s |
| clock-trace | 08:13~09:27 (AC-12 회귀 중, 1분 간격 75회) | 4,463 s | 누적 **1.0239**. 10분 단위 1.0223 → 1.0226 → 1.0233 → 1.0238 → 1.0243 → 1.0250 → 1.0252 → 1.0255(조금씩 커짐), 1분 단위 1.0209~1.0314 | 누적 0.9999 (게스트 실시간 − Windows −0.28~+1.04 s) | 최대 0.91 s |

- 부팅 뒤 전체 경과: systemd journal 항목의 `__REALTIME_TIMESTAMP`와 `__MONOTONIC_TIMESTAMP` 차이를 5분 단위로 보면, 게스트 실시간 대비 단조 시계가 07:07~07:11 **+0.6%**, 07:11~07:16 +1.4%, 07:16~07:41 **+1.8%**, 07:41~08:21 **+2.0~2.2%** 빨랐고, 그 뒤 clock-trace에서 09:27까지 +2.6%로 조금씩 더 커졌다. 게스트 실시간은 약 32 s마다 뒤로 물러나며(07:45쯤 0.64 s, 09:35에는 0.85 s씩) Windows 시각에 맞춰진다(clock2 끝에서 차 0.112 s, clock-trace에서 호출 지연(최대 0.91 s)을 포함해 −0.28~+1.04 s). 즉 **WSL이 막 떴을 때는 단조 시계가 호스트와 거의 같았고, 15분쯤 뒤부터 약 2% 빨리 가는 상태로 굳었다.** 이번 회차의 처리량 측정(07:21~08:11)은 모두 +1.8~2.2% 구간에 있다. clock1이 1.0023으로 나온 것은 그 전에 쟀기 때문이다.
- 영향: HTB(커널 ktime)와 fio(`clock_gettime`)는 같은 게스트 시계를 쓴다. 그래서 이 보고서의 "한도 대비"(게스트 시계 기준, 결정 15가 정한 판정 시계)는 시계 오차와 무관하게 HTB 설정과 데이터의 관계를 보여 준다. 하지만 Windows 벽시계로 환산하면 처리량이 약 2% 높다. 예: AC-01 (b) 최대 99.2% → 약 101.0%, AC-09 99.1% → 약 101.1%, AC-04 창 최대 100.8% → 약 102.8%, AC-02 최소 95.1% → 약 97.0%. 즉 호스트 시간 기준이면 위쪽 1% 여유를 넘는 값이 여럿 생긴다. 제품 코드의 문제가 아니라 WSL 게스트 시계의 성질이다(S2 때는 0.908이었다). 리더 결정 사항으로 올린다(아래).


## 검증 방법과 드라이버에 관한 기록
- 데이터 효과는 implementer의 e2e 결과를 쓰지 않고 새 드라이버 `fr08_verify.py`(검증 때 `backend/tests/e2e/`에 둔 pytest가 모으지 않는 이름, ruff 통과. 지금은 `_workspace/throughput-limit/verify/`)로 직접 쟀다. fio는 클라이언트 컨테이너(`anf-nfs-client`, fio-3.36) 안에서, tc 상태와 카운터는 호스트에서 `nsenter -t <인스턴스 pid> -n tc …`와 `/proc/<pid>/net/dev`로, 응답은 anf-api HTTP로 봤다.
- 드라이버를 도중에 고친 것: tc 필터 수를 `matchall chain 0 handle 0x`로 세게 함, `mem()` 인자 이름, HTB `Sent` 1 s 표본 추가, `mountstats()`·`db_counts()` 추가, ac06부터 시각을 `time.monotonic()`으로(위 시계 절), AC-05 쓰기 표본 단계 `ac05w` 추가. ac01b 첫 실행은 드라이버의 `log()` 인자 이름 충돌로 볼륨 생성 직후 멈췄고 다시 돌렸다(AC-01 참고).
- AC-12 첫 시도(`reg-*`)는 pytest 출력과 `ANF_E2E_LOG`를 scratchpad(`/mnt/c`, 9P)에 바로 썼다. e2e 도우미는 HTTP 요청마다 그 파일을 열어 한 줄 붙이므로, 요청이 많은 시험이 3~4배 느려졌다(풀 계약 2.48 s → 10.48 s). 시간 비교가 틀어지므로 네 번째 파일 도중에 멈추고, 실행 중에는 WSL ext4(`/root/fr08-e2e`)에 쓰고 끝나면 scratchpad로 복사하는 `pytest2.sh`로 16개 파일을 처음부터 다시 돌렸다(`reg2-*`). 멈출 때 루프만 끄려 했는데 WSL 세션과 함께 돌던 pytest도 끝났다(풀 결함 주입 파일 6/9까지 PASSED, 남은 것 없음 확인). AC-12 판정은 `reg2-*`로만 한다.

## 리더·사용자 결정 사항
0. **AC-12 FAIL 처리.** 실패한 것은 FR-08 데이터 e2e의 시험 코드(`time.time()` 표본 시각)다. 수정 제안대로 `time.monotonic()`으로 바꾼 뒤 `test_throughput_limit_data_live.py`만 다시 돌리면 된다(약 38분). 제품 코드 해시는 바뀌지 않으므로 다른 기준은 다시 돌릴 필요가 없다. 재검증을 맡기면 그 파일을 다시 돌린다(계약 e2e는 표본기를 쓰지 않는다).
1. **시계 기준.** 이번 부팅에서 WSL 게스트 단조 시계가 15분쯤 뒤부터 호스트보다 약 2% 빨리 갔다(위 시계 절). 판정은 결정 15대로 게스트 시계로 했고 모두 허용 오차 안이다. Windows 시간으로 환산하면 약 2% 높아져 101%를 넘는 값이 여럿 생긴다(최대 약 102.8%, AC-04 1초 창). 제안: 판정 시계는 그대로 두고(HTB와 클라이언트가 같은 게스트 시계를 쓰고, 오차는 부팅마다 달라 S2는 0.908이었다), 개념 문서와 ADR §8에 "게스트 시계 기준이며 이 부팅에서는 호스트 대비 +2%"를 적는다. 호스트 시간 기준이 필요하다고 보면 측정 방법을 바꿔야 한다(제품 코드가 아니라 시계를 보정하는 쪽).
2. **AC-05 쓰기.** 설계 §9-11과 리더 지시대로 읽기로 판정해 PASS다. 하지만 같은 aggregate의 다른 볼륨이 디스크에 많이 쓰면 10 MiB/s 볼륨의 쓰기가 한도의 71~86%로 떨어졌다(3회, A의 제한기 원인 아님). 제한기는 상한일 뿐이고 aggregate 디스크를 나누지 않는다. 기준 문구를 "함께 읽는 동안"으로 고칠지, 개념 문서에 "클론의 한도는 상한일 뿐이고, 같은 aggregate 이웃 볼륨의 디스크 경합은 막지 않는다"를 적을지 정해야 한다. 실제 ANF가 이웃 경합을 어떻게 다루는지는 이 검증에서 확인하지 않았다.
3. **새 파일 `backend/tests/e2e/fr08_verify.py`.** 이번 검증의 드라이버(약 1,250줄, pytest가 모으지 않는 이름, ruff 통과, 커밋 안 함). 남길지(재검증 회차에서 같은 측정을 다시 돌릴 수 있다) 지울지 정해야 한다. → 리더 결정: `_workspace/throughput-limit/verify/fr08_verify.py`로 옮겨 기록으로 남긴다(제품·테스트 경로 밖, 다음 회차에서 다시 돌릴 수 있다).
4. (하네스 제안) e2e를 돌릴 때 `ANF_E2E_LOG`와 pytest 출력을 `/mnt/c`에 바로 쓰면 요청이 많은 시험이 3~4배 느려진다. 실행 중에는 WSL ext4에 쓰고 끝난 뒤 복사하는 것을 `real-env-verify` 스킬에 적어 두면 다음 회차의 시간 비교가 흔들리지 않는다.

## 정리 상태 (09:40)
- 이 검증이 만든 계정 `fr08v`·풀 7개·볼륨·스냅샷·클라이언트 컨테이너(`fr08v-*`)는 `cleanup` 단계(08:12)로 지웠고, agent 레코드 0개를 확인했다. 회귀 e2e는 파일마다 스스로 정리했다.
- 끝난 뒤: 컨테이너 0개(`anf-*`·`anfe2e-*`·`fr08v-*` 없음), 호스트 IFB 0개, VG `anf`에 `aggr0`(Data 0.00%)만, `/var/lib/anf-clone/ns`·`exports` 비어 있음, `ns/` 아래 마운트 없음, 포트 8080·8090 비어 있음, uvicorn·pytest·fio 프로세스 없음, `fs.leases-enable` = 0. 내 agent와 anf-api는 08:13에 멈췄다. WSL 쪽 임시 로그 `/root/fr08-e2e`는 scratchpad와 같은지 `cmp`로 확인한 뒤 지웠다. 내 anf-api DB `~mkimhome1/.local/state/anf-clone/fr08-verify.db`는 남아 있다(행은 지운 자원의 작업 기록뿐).
- 저장소: 제품 코드 변경 없음(해시 그대로). 새 추적 안 된 파일 `backend/tests/e2e/fr08_verify.py`(결정 사항 3), 이 보고서. `docs/ai-readiness-*`는 건드리지 않았다.
