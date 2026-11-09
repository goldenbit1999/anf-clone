# throughput-limit (FR-08) 검증 보고서 — 2회차

- 진행 상태: 완료 — AC-12 PASS, 정리 끝 (2026-11-09 10:25 실행 종료)
- 검증일: 2026-11-09
- 검증자: real-env-verifier (서브에이전트, 1회차와 같은 맥락)
- 검증 대상 코드: 커밋 `3328486` "Time FR-08 throughput windows with the monotonic clock", 브랜치 `feature/throughput-limit`
  - 시작 시 HEAD `3328486`. 1회차(`47ed3ed`) 뒤 바뀐 것은 시험 코드 2개(`backend/tests/e2e/throughput_live.py`, `backend/tests/e2e/test_throughput_limit_data_live.py`)와 기록 문서뿐
  - 시작 시 내용 해시: `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3` (1회차·리더 확인 값과 같음)
  - 끝난 뒤 내용 해시: `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3` (시작과 같음)
  - 끝난 뒤 HEAD는 `3f877f3`이다. 실행 중에 리더가 `bf4a65c`(AC-05 판정 기록)와 `3f877f3`(개념 문서)을 커밋했다. `git diff 3328486 3f877f3 -- backend/` 결과는 비어 있다. 바뀐 것은 `_workspace/throughput-limit/00_progress.md`·`02_main_design.md`, `docs/ADR.md`, `docs/concepts/throughput-limit.md`뿐이다. 그래서 돌린 시험 코드와 제품 코드는 `3328486`과 같다.
  - 미커밋 변경: 시작할 때는 `_workspace/throughput-limit/02_main_design.md`(리더 기록)였고, 그 뒤 리더가 커밋했다. 끝날 때는 `CLAUDE.md`(리더 변경)다. `docs/ai-readiness-*`는 검증과 무관해 건드리지 않았다. 이 보고서는 커밋하지 않았다.
  - 해시 명령: `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
- 이번 회차 범위: 재검증 — AC-12만. 수정이 시험 코드뿐이고 제품 코드 해시가 같으므로, 1회차에서 실패한 `test_throughput_limit_data_live.py` 한 파일만 다시 돌린다(리더 지시). 다른 기준은 1회차 결과를 그대로 둔다.
- 이전 보고서: `_workspace/throughput-limit/04_verifier_report.md` (1회차)
- 로그 원본: `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\8ccecfbf-a107-4c47-b042-9e3c9ff59a3b\scratchpad\fr08-verify\r2\`

## 환경 사전 점검
2026-11-09 09:46 (PST). 모두 통과.

| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`: Ubuntu `Stopped` → 첫 명령으로 다시 떴다(1회차 뒤 새 부팅). `uptime` 0 min, 커널 `6.18.54.1-microsoft-standard-WSL2`. 유휴 종료 방지로 `wsl -d Ubuntu -u root -e sleep 86400`을 띄워 둠 |
| 메모리 | `free -m`: used 697, buff/cache 1745, available 7081 MiB |
| 커널 모듈 | `nfsd`·`sch_fq_codel` 로드됨. `dm_thin_pool`·`ifb`는 agent를 처음 띄울 때 올라옴, 호스트 IFB 0개 |
| `fs.leases-enable` | `0` |
| Docker | 서버 29.1.3 `linux`, `readlink /usr/bin/docker` rc 1(Desktop 연동 아님), 컨테이너 0개, 네트워크 `anf-vnet` 있음, 이미지 `anf-nfs-server`(11-08)·`anf-nfs-client`(11-09 04:04) |
| 포트 8080·8090 | 비어 있음 |
| VG `anf` | 처음에 붙어 있지 않음(새 부팅). agent를 root로 한 번 띄우고(2.0 s, 레코드 0) 바로 멈춰 `aggr0`(Data 0.00%)를 붙였다. `ns/`·`exports/` 비어 있음 |
| 1회차 DB | `~mkimhome1/.local/state/anf-clone/fr08-verify.db` 남아 있음(정리 때 지운다) |
| **벽시계 건너뜀** | 09:47~09:48에 100 s 동안 0.05 s마다 `time.time()`과 `time.monotonic()`의 증가량을 비교(`r2/clockstep.py`): 벽시계가 **−0.469, −0.678, −0.529 s** 건너뜀 3번, 간격 32.2 s, 32.3 s. 단조 / 벽시계 경과 = 1.017. **새 부팅 직후에도 건너뜀이 있다.** 실행 중에도 같은 탐지기를 계속 돌려 기록한다(아래) |

## 결과 요약
- 이번 회차: AC-12 PASS. `test_throughput_limit_data_live.py` **7 passed**, skip 0, 2,248.09 s (게스트 단조 시계 기준).
- 누적(수락 기준별 최신 결과): **PASS 12 / FAIL 0 / UNVERIFIED 0**.
- 실행 동안 벽시계가 70번 건너뛰었다(−0.52~−0.88 s, 약 32.2 s 간격). 그래도 단조 시계로 바꾼 표본기에서는 한도를 넘는 창이 하나도 없었다. 그래서 1회차 FAIL은 시험 코드의 시계 문제였고, 이번 수정이 그 문제를 고쳤다고 판정한다(아래 AC-12 절).

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1 (`04_verifier_report.md`) |
| AC-02 | PASS | 1 (`04_verifier_report.md`) |
| AC-03 | PASS | 1 (`04_verifier_report.md`) |
| AC-04 | PASS | 1 (`04_verifier_report.md`) |
| AC-05 | PASS (함께 읽는 동안으로 판정, 리더 결정 3) | 1 (`04_verifier_report.md`) |
| AC-06 | PASS | 1 (`04_verifier_report.md`) |
| AC-07 | PASS | 1 (`04_verifier_report.md`) |
| AC-08 | PASS | 1 (`04_verifier_report.md`) |
| AC-09 | PASS | 1 (`04_verifier_report.md`) |
| AC-10 | PASS | 1 (`04_verifier_report.md`) |
| AC-11 | PASS | 1 (`04_verifier_report.md`) |
| AC-12 | PASS | 2 (이 보고서. 1회차 FAIL은 시험 코드 `time.time()` 문제) |

## 항목별 결과
### [PASS] AC-12 회귀 — 1회차에 실패한 파일 재실행
- 기준: 1회차와 같다(`backend/tests/e2e`의 모든 `*_live.py`가 새 코드에서 skip 없이 통과). 1회차에 실패한 파일은 `test_throughput_limit_data_live.py` 하나뿐이었다. 나머지 15개 e2e 파일, 통합 테스트, 단위·계약 테스트는 1회차에 모두 통과했다. 그 뒤 제품 코드 해시가 바뀌지 않았으므로 이 파일만 다시 돌렸다(리더 지시).
- 실행: WSL root, 저장소 루트에서 `r2/run-r2.sh` 순서로 돌렸다.
  1. `sync; echo 3 > /proc/sys/vm/drop_caches`
  2. `ANF_E2E_API_URL=http://127.0.0.1:8080 ANF_E2E_LOG=/root/fr08-r2/r2-throughput_limit_data.jsonl /home/mkimhome1/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider backend/tests/e2e/test_throughput_limit_data_live.py -v -rs`
  3. 실행 내내 시계 건너뜀 탐지기 `clockstep.py 3300`을 함께 돌렸다.
  4. 끝난 뒤 남은 컨테이너·LV·IFB·포트를 확인했다.
  5. 로그는 실행 중 WSL ext4(`/root/fr08-r2`)에 쓰고, 끝난 뒤 scratchpad `r2/`로 복사했다(1회차 `/mnt/c` 직접 기록 문제를 피하려고).
  - agent·anf-api는 e2e 픽스처가 직접 띄우고 멈춘다. 시작 시각은 09:49(PST).
- 출력:
  - `7 passed in 2248.09s (0:37:28)`, rc 0. `SKIPPED`·`FAILED` 줄 없음(`r2/r2-throughput_limit_data.out`).
  - 통과한 시험(순서대로): `test_ac01b_auto_volume_data`, `test_ac02_ac03_manual_volume_data_and_shared_read_write`, `test_ac04_limit_changes_during_io`, `test_ac05_unlimited_volume_next_to_a_limited_one`, `test_ac06_small_auto_limit_keeps_small_io_working`, `test_ac07_limit_survives_lifecycle`, `test_ac09_auto_to_manual_keeps_the_limit`.
  - 끝난 뒤: `anf*` 컨테이너 0, 볼륨 LV 0, 호스트 IFB 0, 8080·8090 비어 있음.
  - 시간 비교:

    | 회차 | 결과 | pytest 시간 (게스트 단조) | 벽시계 (`date`) | `uptime` 증가 |
    | --- | --- | --- | --- | --- |
    | 1 (`reg2-*`) | 1 failed, 6 passed | 2,274.28 s | 2,219 s | — |
    | 2 (이번) | 7 passed | 2,248.09 s | 2,197 s | 2,248.81 s |

    - 차이는 −1.2%다. FR-07 회귀 때는 없던 새 파일이라 그때와 비교할 값은 없다.
    - pytest 시간과 `date` 차이(51 s)는 같은 동안 탐지기가 잰 벽시계 건너뜀 합(−51.85 s)과 맞는다.
- **1회차에 실패한 AC-07의 단계별 증거**(`r2/r2-throughput_limit_data.jsonl`, `tag: AC-07`, 한도 10 MiB/s, 허용 상한 ×1.01 = 10.1):

  | 단계 | 판정 창 중앙값 (비율) | `over_limit` | 1회차 `over_limit` | 표본 공백 | fio 쓰기 MiB/s (오류) | tc rate |
  | --- | --- | --- | --- | --- | --- | --- |
  | (a) agent 재시작 | 9.9515 (0.9951) | **[]** | 2개 (17.33·17.31) | 없음 | 9.891 (0) | 87710000 bit, 방향별 필터 1 |
  | (b) `docker stop` + agent 재시작 | 9.9445 (0.9945) | **[]** | 8개 (16.70~17.39) | 1786.643~1790.004 (인스턴스 재기동) | 9.6526 (0) | 같음 |
  | (c) `docker rm` + 재 PUT | 9.951 (0.9951) | **[]** | 10개 (16.57~17.75) | 없음 | 9.6797 (0) | 같음 |
  | (d) 쓰는 중 되돌리기 | 9.955 (0.9955) | **[]** | 2개 (16.66·16.66) | 없음 | 9.1473 (0) | 같음 |

  - (e) 스냅샷에서 새 볼륨을 만들었다.
    - Manual 풀에 한도 20: `throughputMibps` 20.0, `actualThroughputMibps` 20.0, HTB 175420000 bit, 클라이언트 쓰기 19.63 MiB/s(98.15%).
    - Auto 풀(1 GiB Ultra): `actualThroughputMibps` 0.125, HTB 1096000 bit.
  - 각 단계의 판정 창은 30개다. 다시 흐르기 시작한 뒤 지연은 0.11~0.46 s였다.
- **벽시계 건너뜀이 있는 상태에서 통과했는가** — 그렇다.
  - 탐지기(`r2/clockstep-run.jsonl`)는 0.05 s마다 `time.time()`과 `time.monotonic()`의 증가량을 비교했다. 실행 동안(단조 167.9~2,393.2 s) 벽시계가 **70번** 뒤로 건너뛰었다.
    - 크기: 최소 −0.878, 중앙값 −0.763, 최대 −0.518 s, 합 −51.85 s
    - 간격: 32.2~32.3 s
  - 실행 전 100 s(09:47~09:48)에도 3번 있었다(사전 점검 표). 이번 부팅 내내 건너뜀이 있었다는 뜻이다.
  - AC-07 표본 구간 안에 든 건너뜀은 **12번**이다(단계별 a 1, b 4, c 5, d 2).
    - 표본 구간은 증거 기록 시각을 단조 시계로 옮긴 값에서 fio `runtime`(50·150·150·50 s)과 2 s를 뺀 데부터 그 기록 시각까지로 잡았다.
    - (b)의 표본 공백(단조 1786.6~1790.0 s)이 이렇게 잡은 (b) 구간(1781.3~1933.3 s) 안에 떨어진다. 그래서 단조 시계로 옮긴 값이 맞다고 본다.
    - 1회차에는 같은 종류의 단계에서 건너뜀마다 한도를 넘는 창이 짝으로 나왔다(1.7배쯤). 이번에는 12번 모두에서 한도를 넘는 창이 0개다.
  - AC-04 판정 창에도 건너뜀이 들어갔다. 1회차에는 판정 창이 건너뜀을 우연히 피했었다.
    - 쓰기(`w41`): 창 142개(단조 1195.5~1266.1 s)에 건너뜀 3번. 가장 큰 창 29.559(한도 30). Succeeded 뒤 판정 창은 30 → 29.39~29.42, 5 → 5.01~5.03, PUT 10 → 9.91~9.94. fio 오류 0.
    - 읽기(`r3`): 창 142개(1287.7~1358.3 s)에 건너뜀 2번. 가장 큰 창 29.581. 판정 창은 28.90~29.28, 5.016~5.026, 9.905~9.956. fio 오류 0.
  - 노트 로그의 창 시각은 이제 부팅 뒤 초(단조)다. 차이로만 쓰므로 판정에는 영향이 없다.
- 판정: **PASS**.
  - 1회차 FAIL(`throughput_live.py:161`의 `time.time()` 표본 시각)은 `3328486`이 고쳤다.
  - 벽시계 건너뜀이 1회차와 같은 크기와 주기로 계속 있는 부팅에서, 같은 파일이 skip 없이 통과했다.
  - 제품 코드 해시는 1회차와 같다(`f99bc5cf…c1a6d3`). 그래서 1회차의 다른 15개 e2e 파일, 통합 30개, 단위·계약 914개의 통과 결과를 그대로 쓴다.

## 정리 상태 (10:30)
- 남은 것 없음:
  - `anf*` 컨테이너 0
  - 호스트 IFB 0
  - VG `anf`의 LV는 `aggr0`(Data 0.00%)만
  - `ns/`·`exports/` 비어 있음
  - 8080·8090 비어 있음
  - uvicorn·pytest·fio·탐지기 프로세스 없음
- `/var/lib/anf-clone/ns` 바인드 마운트(agent가 rshared로 만든 것)는 다음 agent 기동에 쓰이므로 그대로 둔다.
- 지운 것:
  - 1회차 DB `~mkimhome1/.local/state/anf-clone/fr08-verify.db` (이제 그 폴더는 비어 있다)
  - 이번 회차 e2e DB·서버 로그 `/tmp/anf-vol-e2e-*` 7개(09:55~10:25)와 `/tmp/pytest-of-root`
  - WSL 쪽 로그 `/root/fr08-r2`. 지우기 전에 scratchpad 사본과 sha256이 같은지 5개 파일 모두 확인했다.
- 이번 회차에는 agent·anf-api를 내가 띄우지 않았다. 사전 점검의 agent 1회 기동만 바로 멈췄다. 나머지는 e2e 픽스처가 띄우고 멈췄다.
- 유휴 종료 방지 `sleep 86400`을 멈췄다. 모니터는 없다.
