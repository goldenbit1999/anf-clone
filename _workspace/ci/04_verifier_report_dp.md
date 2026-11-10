# ci 2부 (FR-11 data-plane 작업) 검증 보고서 — 1회차

- 진행 상태: 완료 (2026-11-10 12:45Z)
- 검증일: 2026-11-10
- 검증 대상 코드: 제품 코드 내용 해시 시작·끝 모두 `9a023d13b647ba1f0363bfa75a22c66ea362991e5baca42796bef74e6cab92f1`. 커밋 `f6f2e1c` (`origin/feature/ci-dataplane`와 같음. `5cb8b17`과의 차이는 `_workspace/ci/00_progress.md`뿐). PR #20 실행은 merge 커밋 `833a155`(트리 = `f6f2e1c` 트리 `214fa7aa…`). 검증 중 주 체크아웃에 메인 세션의 로컬 커밋 `932cdc8`(CLAUDE.md·docs/ADR.md만, push 안 됨)과 미커밋 문서 변경(`_workspace/ci/00_progress.md`, `docs/concepts/ci.md`, `docs/concepts/test-automation.md`)이 생겼다. 모두 제품 코드 해시 밖이다. 추적 안 함 `docs/ai-readiness-*`, `.claude/worktrees/`
- 원본 보관 위치(세션 scratchpad `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\`): job 로그 `logs\`, artifact `art-pr20-throughput\`, `art-pr20-rest\`, `art-pr21-fail\`, `art-pr21-pass\`, WSL 출력 `wsl\fr11-verify.tgz`(sha256 `cd60e015…51499`, WSL 쪽과 같음을 확인한 뒤 WSL 쪽 삭제)와 풀어 둔 `wsl\fr11-verify\`, 합산 스크립트 `tools\merge_shards.py`, `tools\tp_values.py`, 흉내 스크립트 `ns_shared_root_sim.sh`, 임시 브랜치 파일 `test_verify_ac03_fail_live.py`, `test_verify_fr11_ac05_live.py`, `ci-matrix-ac03.diff`
- 이번 회차 범위: 전체 (AC-01~AC-08)
- 판정 방법: 사용자와 합의한 규칙(리더 프롬프트). AC-06은 implementer의 WSL 실행 결과 파일, AC-01·02·04·07·08은 PR #20의 Actions 실행, AC-03은 임시 브랜치의 draft PR, AC-05는 WSL에서 직접 확인

## 환경 사전 점검
| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `Ubuntu` 처음엔 Stopped, 첫 명령으로 부팅(11:59:46Z, `uptime` 0 min). 커널 `6.18.58.1-microsoft-standard-WSL2` |
| 커널 모듈 | `nfsd` 로드됨. `dm_thin_pool`은 VG가 떨어져 있어 아직 없음(실행기가 붙인다) |
| Docker | Ubuntu 안 Engine `29.1.3 linux`, `readlink /usr/bin/docker` 비어 있음(rc=1, Desktop 연동 아님) |
| `/` 전파 (WSL) | `private` |
| 데이터 플레인 | `vgs` 비어 있음(VG `anf` 떨어짐), ns는 마운트 지점이 아님(`findmnt --mountpoint /var/lib/anf-clone/ns` 없음, mountinfo 0줄) |
| gh CLI | 2.89.0, `goldenbit1999` 로그인 |
| Actions | PR #20의 `pull_request` 실행 `42811747210`(headSha `f6f2e1c`, 11:57:57Z 생성), 같은 커밋의 `push` 실행 `42811738312` |

## 결과 요약
PASS 7 / FAIL 1 / UNVERIFIED 0

- FAIL: AC-01. PR #20의 `throughput` 조각이 failure다. 처리량 데이터 파일 7개 중 2개(`test_ac04_limit_changes_during_io`, `test_ac09_auto_to_manual_keeps_the_limit`)가 "한도를 올린 직후 쓰기 측정값이 한도의 0.90 미만"으로 실패했다(26.392/30 = 0.880, 17.3506/20 = 0.8675). 한도 초과는 없었고 tc 규칙은 맞았다. ns 수정과는 무관한 것으로 판단한다(근거는 AC-01 항목). 같은 파일이 러너에서 돈 3번 중 1번 실패다(S3 두 job 통과).

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | FAIL | 1회차 |
| AC-02 | PASS | 1회차 |
| AC-03 | PASS | 1회차 |
| AC-04 | PASS | 1회차 |
| AC-05 | PASS | 1회차 |
| AC-06 | PASS | 1회차 |
| AC-07 | PASS | 1회차 |
| AC-08 | PASS | 1회차 |

## 항목별 결과

### [FAIL] AC-01 data-plane 작업 (CI, 데이터 효과)
- 기준: main 대상 PR에서 `data-plane` 작업의 두 조각이 모두 success다. 두 조각의 실행기 요약을 합치면 수집 113(= `pytest --collect-only -m dataplane`의 수), 통과 113, 실패·오류·skip 0이고, 두 조각에 겹치거나 빠진 파일이 없다(13개 파일).
- 실행한 명령: `gh run view 42811747210 --json jobs,status,conclusion`, `gh api repos/goldenbit1999/anf-clone/actions/jobs/{129814648050,129814648451}/logs`, `gh run download 42811747210 -n dataplane-throughput-1|dataplane-rest-1 -D <scratchpad>/art-pr20-…`, `python -I tools/merge_shards.py ref/wsl-collect.log art-pr20-throughput art-pr20-rest`.
- 출력(핵심 부분):
  - run `42811747210`(pull_request, headSha `f6f2e1c`) 결론 **failure**. job `129814648050` `data-plane (throughput, …)` **failure**(11:58:00Z~12:34:48Z), job `129814648451` `data-plane (rest, …)` success(11:58:01Z~12:36:16Z).
  - throughput `summary.txt`: `test_throughput_limit_data_live 7 5 2 0 0 2171.8`, `2 failed, 0 errors.`, `nonzero exit: …test_throughput_limit_data_live.py (pytest exit 1)`, `exit 1`. `left behind` 없음, teardown `leftovers_deleted: []`.
  - rest `summary.txt`: `total 106 106 0 0 0 2257.4`, `collected 106, skipped 0`, `exit 0`.
  - 합산(JUnit XML 직접 파싱):
    ```
    art-pr20-throughput: collected 7 in 1 files, junit 7 {'passed': 5, 'failed': 2, 'error': 0, 'skipped': 0}
    art-pr20-rest: collected 106 in 12 files, junit 106 {'passed': 106, 'failed': 0, 'error': 0, 'skipped': 0}
    union: 113 ids (113 with repeats), 13 files (13 with repeats)
    file overlap: []
    missing vs reference: 0 []      ← 기준은 WSL 회귀 실행의 collect.log 113개 ID (같은 제품·테스트 코드)
    extra vs reference: 0 []
    merged results: {'passed': 111, 'failed': 2, 'error': 0, 'skipped': 0}
    ```
    러너에서도 backend job이 `collected 1102 items / 113 deselected`로 dataplane 마커 113개를 보였다. 수집·분할 부분(113, 13개 파일, 겹침·누락 없음, skip 0)은 기준대로다. 통과 113과 두 조각 success가 기준에 못 미친다.
- 실패 1: `test_ac04_limit_changes_during_io` (`backend/tests/e2e/test_throughput_limit_data_live.py:164`)
  ```
  assert ch["windows_2s"] and all(within(w[1] / ch["mibps"]) for w in ch["windows_2s"]), (name, ch)
  E  AssertionError: ('w41', {'how': 'PATCH', 'mibps': 30, 'status': 202, 'state': 'Patching', ...})
  E  assert ([(1062.795, 26.392), (1063.295, 30.003), (1063.796, 30.002), (1064.296, 30.001)] and False)
  ```
  NFSv4.1 쓰기 중 10 → 30 MiB/s PATCH가 `Succeeded`된 시각(t_ok 1062.533) 뒤 2 s 안의 1 s 창 4개 중 첫 창이 26.392(0.880)다. 창은 1061.3부터 14.3 → 23.5 → 25.5 → 26.4 → 30.0으로 약 2 s에 걸쳐 올라갔다. 30 MiB/s 유지 구간 중간에도 28.07, 그리고 다음 PATCH 전 1071.3~1073.8에 23.6·18.3·20.4·22.3·26.1·26.5로 떨어졌다(이 구간은 단언 대상이 아님). 나머지 변경(→5, PUT→10)과 `r3` 읽기 쪽은 모두 범위 안이다. 창 최댓값은 쓰기 30.065(1.0022), 읽기 30.081(1.0027)로 상한 1.01 안이다. S3 러너에서 같은 창은 30.000~30.003(private), 30.002~30.067(as-is)였다.
- 실패 2: `test_ac09_auto_to_manual_keeps_the_limit` (`…test_throughput_limit_data_live.py:431`)
  ```
  assert matches(changed["tc"], 20) and within(changed["write"]["ratio"]), changed
  E  'tc': {'rate_bits': 175420000, 'filters': {'ingress': 1, 'egress': 1}, 'ifb0': True}, 'write': {'limit': 20, 'write': 17.3506, 'ratio': 0.8675}
  E  assert (True and False)   where True = matches(…, 20)  and False = within(0.8675)
  ```
  Auto → Manual 전환 전후 5 MiB/s 쓰기는 중앙값 4.97(0.994)·4.983(0.9966)으로 통과했고, 볼륨을 20 MiB/s로 PATCH한 뒤 `quick`(15 s 시간 기반 쓰기 한 번, `throughput_live.py:267-271`)이 17.3506(0.8675)이었다. tc HTB rate는 20 MiB/s 값(`175420000` = `htb_rate_bits(20)`)과 맞다.
- 같은 job의 다른 측정(`tools/tp_values.py`): 5 MiB/s 0.9942~0.9984, 10 MiB/s 0.9947~0.9966, 20 MiB/s 쓰기 runs `19.439, 19.886, 19.738, 19.412, 19.922, 19.372`(중앙값 0.9869), AC-07 Manual 20 쓰기 19.8324(0.9916). S3 러너의 20 MiB/s 쓰기는 `19.965~19.969`(0.9984, 흔들림 0.1% 안)였다. 이 VM은 20~30 MiB/s 쓰기에서 S3 VM보다 낮고 흔들렸다(최대 약 2.8% 폭, 가끔 10% 넘게 처짐). dmesg(1,169줄)에 hung task, `blocked for more`, Call Trace, oom-kill, AppArmor DENIED 0건.
- 기대값: 두 조각 success, 113 통과.
- 추정 원인 [추론]: 호스트 러너 VM의 쓰기 처리량 변동이 시험의 하한(한도의 0.90)을 짧은 측정에서 넘었다. 제품 결함으로 보지 않는 이유:
  1. 실패는 둘 다 하한 쪽(덜 나옴)이다. 상한(1.01)은 모든 창과 측정에서 지켜졌고, tc 규칙(`matches`)은 바뀐 한도와 맞았다. FR-08의 주장(한도는 상한)은 이 실행에서도 성립한다.
  2. 이번 제품 변경은 ns 바인드의 마운트 전파(`nfs_instance.py:107-112`)뿐이고 I/O·tc 경로를 건드리지 않는다. S3의 `private` job은 이 수정과 같은 마운트 상태에서 7개를 모두 통과했고, WSL 회귀(AC-06)도 통과했다.
  3. 같은 VM의 다른 측정이 전반적으로 S3보다 낮고 흔들렸다(위 수치).
  다만 러너 3회 중 1회 실패라 표본이 작다. "VM 변동"은 디스크·CPU 지표를 남기지 않아 확인하지 못했다.
- 재현: 같은 PR에서 `gh run rerun 42811747210 --failed`(throughput 조각만 다시), 또는 임시 브랜치에서 matrix로 처리량 데이터 파일만 여러 조각에 돌린다. 이번 검증에서는 PR #20의 체크 상태를 바꾸지 않으려고 다시 돌리지 않았다.
- 수정 제안(리더 판단, 제품 코드가 아니라 시험 쪽):
  1. 상한은 모든 창·측정에 그대로 두고, 하한만 한 번의 짧은 측정이 아니라 묶음으로 본다. AC-04는 바꾼 직후 창(`t_ok`~`t_ok + 2`)의 상한은 그대로 보고, 하한은 `t_ok + 1` 이후 창이나 2 s 창들의 중앙값으로 본다. AC-09의 바꾼 뒤 쓰기는 전후 측정처럼 `measure`(6회, 첫 회 버림, 중앙값)로 잰다.
  2. 고친 뒤에는 3의 규칙을 따른다. 파일 단위 실패율을 러너 3회 중 1회(p ≈ 1/3)로 보면 n = ⌈3/p⌉ = 9회 연속 통과가 필요하다. 처리량 파일만 9개 matrix 조각으로 임시 브랜치에서 돌리면 한 번(약 40분)에 모은다(public 저장소라 러너 시간은 무료).
  3. 원인을 더 가르려면 처리량 조각에 VM 지표(`/proc/pressure/{cpu,io}`, `iostat -x 1` 또는 `vmstat 1`)를 시험 중 기록해 artifact에 넣는다.

### [PASS] AC-02 그대로의 러너 (CI)
- 기준: 그 실행의 워크플로에 ns 전파를 손대는 단계가 없고, 러너 정보 기록에 `/`의 전파가 `shared`로 찍혀 있다. S3에서 실패했던 8개 테스트가 통과 목록에 있다.
- 실행한 명령: `git show f6f2e1c:.github/workflows/ci.yml | grep -nE "mount|propagation|make-|unshare|nsenter"`, 같은 grep을 `scripts/setup-wsl-dataplane.sh`, `scripts/run-dataplane-tests.sh`에. job 로그 grep. `merge_shards.py`의 S3 8개 확인.
- 출력(핵심 부분):
  - 워크플로에서 걸리는 줄은 읽기만 하는 셋뿐이다: `123: echo "propagation of /: $(findmnt -no PROPAGATION /)"`, `137: findmnt -o TARGET,PROPAGATION --mountpoint …ns …`, `138: grep -E ' / / | …ns ' /proc/self/mountinfo`. 준비 스크립트와 실행기에는 해당 줄이 없다(`mount --`·`make-` 0건). ns 바인드는 agent의 `ensure_shared_ns()`만 만든다.
  - Runner info: 두 조각 모두 `image: ubuntu24 20261101.360.1`, `kernel: 7.0.0-1017-azure`, `propagation of /: shared`(throughput 로그 257행, rest 로그 257행).
  - S3 as-is 실패 8개가 모두 rest 조각의 JUnit에서 `passed`다: `test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_content_and_independence[AC-02-NFSv3-3-None]`, `[AC-04a-NFSv4.1-4.1-0755]`, `::test_ac06_new_volume_survives_source_revert_delete_and_agent_restart`, `test_snapshot_contract_live.py::test_ac01_create_snapshot_contract_and_state`, `test_snapshot_data_live.py::test_ac06_delete_snapshot_with_client_inside[NFSv3-3]`, `[NFSv4.1-4.1]`, `test_snapshot_revert_data_live.py::test_ac02_ac03_revert_restores_snapshot_and_deletes_newer[AC-02-NFSv3-3]`, `[AC-03-NFSv4.1-4.1]`.
- 판정 메모: 이 기준이 따로 요구하는 세 가지(ns 단계 없음, `/` shared, 8개 통과)는 모두 충족했다. 기준 문장의 "S3의 as-is 조건에서 통과한 것이다"에서 "통과"(113개 전부)는 AC-01이 판정하고, 거기서 FAIL이다. 실패 2개는 처리량 하한이며 ns 전파와 무관하다. 8개가 실패하던 원인(as-is의 두 벌 마운트)은 이 실행에서 사라졌다.

### [PASS] AC-04 artifact (CI)
- 기준: 조각마다 실행기 출력 폴더(JUnit XML, `.log`, `.jsonl`, `summary.txt`)와 dmesg가 artifact로 남고 내려받아 읽을 수 있다.
- 실행한 명령: `gh api repos/goldenbit1999/anf-clone/actions/runs/42811747210/artifacts`, `gh run download 42811747210 -n <이름> -D <scratchpad>/art-pr20-<조각>`.
- 출력(핵심 부분):
  - artifact 목록: `13766075819 dataplane-throughput-1 68991`, `13765601080 dataplane-rest-1 438840`(보관 14일).
  - `dataplane-throughput-1`: `baseline.txt`, `collect.log`, `files.tsv`, `summary.txt`, `test_throughput_limit_data_live.{xml,log,jsonl}`, `dmesg.txt`(1,169줄, 첫 줄 `Linux version 7.0.0-1017-azure`). 실패한 조각인데도 `Upload logs`(`if: always()`)가 success였다. AC-03을 진짜 조각에서 한 번 더 본 셈이다.
  - `dataplane-rest-1`: `baseline.txt`, `collect.log`, `files.tsv`, `summary.txt`, XML 12개, `.log` 13개(파일별 12 + collect), `.jsonl` 11개(통합 테스트 `test_flexvol_linux`는 `.jsonl`을 쓰지 않는다. WSL 회귀 실행도 같다), `dmesg.txt`(3,663줄).
  - 읽을 수 있다: 위 AC-01 합산 스크립트가 두 artifact의 XML 19개와 `collect.log`를 모두 파싱했고, `tp_values.py`가 `.jsonl`을 읽었다.
- 판정 밖 메모: rest 조각의 `dmesg.txt`는 `[Tue Nov 10 12:07:47 2026] EXT4-fs (dm-7): unmounting …`부터 시작한다. 커널 링 버퍼가 넘쳐 11:58~12:07의 커널 로그가 빠졌다(아래 관찰 6).

### [PASS] AC-08 시간 (CI)
- 기준: 각 조각이 50분 안에 끝난다.
- 출력(job API의 started/completed): throughput 11:58:00Z~12:34:48Z = **36분 48초**(테스트 단계 11:58:24~12:34:43, 실행기 `2174 s for 1 files`), rest 11:58:01Z~12:36:16Z = **38분 15초**(테스트 단계 11:58:21~12:36:11, 실행기 `2267 s for 12 files`). 준비 단계는 10 s·9 s였다. 두 조각 모두 50분, `timeout-minutes: 75` 안이다. 실행 전체(생성 11:57:57Z ~ 마지막 job 12:36:16Z)는 약 38분이다.

### [PASS] AC-06 WSL 전체 회귀 (데이터 효과, 회귀)
- 기준: 수정한 코드로 `scripts/run-dataplane-tests.sh` 전체 1회: 113 통과, skip 0, exit 0, 남은 것 없음.
- 근거 파일(WSL): `/var/tmp/anf-clone-tests/20261110T102847Z/`(summary.txt, files.tsv, baseline.txt, collect.log, 파일별 `.xml`·`.log`·`.jsonl`), 콘솔 `/var/tmp/anf-clone-tests/console-fr11.log`.
- 출력(핵심 부분):
  - `summary.txt`: `total 113 113 0 0 0 5186.4`, `collected 113, skipped 0`, `time: 5198 s for 13 files (monotonic clock)`, `exit 0`. `nonzero exit:`·`left behind` 줄 없음.
  - `files.tsv`: 13개 파일 모두 pytest exit 0 (flexvol_linux 391 s … throughput_limit_data_live 2264 s … volume_recovery_live 157 s).
  - JUnit XML 13개를 직접 읽음: 모두 `errors="0" failures="0" skipped="0"`, tests 합 30+8+5+5+8+5+11+5+8+7+7+7+7 = 113.
  - `collect.log` 끝: `113/176 tests collected (63 deselected)` (= `pytest --collect-only -m dataplane`의 수).
  - 콘솔: `VG anf: attached`, `collected 113 dataplane tests in 13 files; venv /home/mkimhome1/.venvs/anf-clone`, `rootdir: /mnt/c/Users/mkimh/Projects/ANF-clone`, 끝 `exit 0` / `rc=0`.
  - `baseline.txt`: 실행 전 LV·컨테이너 없음.
- 이 실행이 검증 대상 코드로 돌았다는 근거:
  - 실행 시작 `20261110T102847Z`(02:28:47 PST, baseline.txt mtime 02:28:47.75). 제품 수정 커밋 `691d93f`와 워크플로 커밋 `02f6d7f`는 02:28:11 PST(author·committer 같음). 끝 03:55:27 PST.
  - 제품 코드(`pyproject.toml`, `backend` 중 tests 밖)의 가장 늦은 mtime은 `backend/storage_agent/nfs_instance.py` 02:15:21 PST로 실행 시작 전이고, 그 뒤 바뀐 제품 파일이 없다. `git diff --stat 691d93f HEAD -- pyproject.toml backend ':!backend/tests'` 비어 있음, `backend/tests`도 차이 없음(차이는 `scripts/setup-wsl-dataplane.sh` 주석 1줄뿐, mtime 02:17로 역시 실행 전). 지금 계산한 제품 코드 해시가 `9a023d13…`이므로 실행 중의 제품 코드도 이 해시다.

### [PASS] AC-07 기존 작업 (CI)
- 기준: 같은 PR 실행에서 backend·frontend 작업이 통과한다(단위 테스트에 `ensure_shared_ns`의 새 경우 포함, skip 0, ruff).
- 실행한 명령: `gh run view 42811747210 --json jobs`, `gh api repos/goldenbit1999/anf-clone/actions/jobs/{129814648691,129814648555}/logs`(로그 보관: scratchpad `logs/pr20-backend-129814648691.log`, `logs/pr20-frontend-129814648555.log`).
- 검증 대상: PR 실행의 checkout은 `refs/remotes/pull/20/merge` = `833a155 Merge f6f2e1c… into 7255e3e…`. `git rev-parse 833a155^{tree}` = `f6f2e1c^{tree}` = `214fa7aa…`(main `7255e3e`가 `f6f2e1c`의 조상이라 merge 트리가 브랜치 트리와 같다).
- 출력(핵심 부분):
  - backend job `129814648691` success (11:58:01Z~12:00:56Z): Lint `ruff check backend .claude/hooks` → `All checks passed!`. Test `collected 1102 items / 113 deselected / 989 selected` → `989 passed, 113 deselected in 147.89s`. Gate `collected 989, skipped 0`. Hook tests `25 passed`.
  - 새 단위 테스트가 돌았다: 로그의 `backend/tests/unit/test_nfs_instance.py` 줄이 점 32 + 다음 줄 16 = 48개로, 로컬 `--collect-only`의 48개(그중 `test_shared_ns_from_plain_directory`, `test_shared_ns_new_bind_leaves_the_peer_group_of_a_shared_root` 포함)와 같다. 실패 표시 없음.
  - frontend job `129814648555` success (11:58:01Z~11:58:17Z): `tsc --noEmit` 통과, Vitest `Test Files 4 passed (4)`, `Tests 23 passed (23)`, build `✓ built in 161ms`.

### [PASS] AC-03 실패를 알림 (CI)
- 기준: 데이터 플레인 테스트가 실패하면 그 조각이 failure다. 실패해도 artifact는 올라온다.
- 방법: 주 체크아웃을 건드리지 않고 scratchpad 아래 worktree(`wt-ac03`)에서 `f6f2e1c`로부터 임시 브랜치 `verify/fr11-ac03-fail`(커밋 `976a726`)을 만들었다. 바꾼 것은 셋뿐이다(제품 코드 해시는 worktree에서도 `9a023d13…`).
  - `backend/tests/e2e/test_verify_ac03_fail_live.py`: `dataplane` 마커 테스트 2개. 둘 다 진짜 볼륨을 만들어 NFSv3 클라이언트에서 쓰고 읽고 볼륨을 지운다. `test_verify_ac03_real_write_read_passes`는 맞는 내용을 기대해 통과, `test_verify_ac03_deliberate_failure`는 마지막에 일부러 틀린 내용을 기대해 실패(볼륨을 지운 뒤라 "남은 것" 검사가 섞이지 않음).
  - `backend/tests/e2e/test_verify_fr11_ac05_live.py`: AC-05용(아래).
  - `.github/workflows/ci.yml` matrix만 `fail`(위 실패 파일)과 `pass`(`test_snapshot_contract_live.py` + AC-05 파일)로 좁힘.
  - draft PR #21 "[verify, do not merge] FR-11 AC-03: failing data-plane shard"(main 대상). `main`·`feature/ci-dataplane`에는 push하지 않았다.
  - 먼저 WSL에서 같은 파일을 worktree의 실행기로 돌려 의도대로 실패하는지 봤다: `1 failed, 1 passed`, 실행기 `exit 1`, `nonzero exit: …test_verify_ac03_fail_live.py (pytest exit 1)`, `left behind` 없음, teardown `leftovers_deleted: []`.
- Actions: run `42813156652`(pull_request, headSha `976a726…`), job `129819414501` `data-plane (fail, …)` → **failure** (12:08:05Z~12:08:54Z). 단계 결론: `7 Data-plane tests (fail): failure`, `8 Mount propagation of ns: success`, `9 Collect logs: success`, `10 Upload logs: success`.
- 출력(핵심 부분, job 로그 scratchpad `logs/pr21-fail-129819414501.log`):
  ```
  test_verify_ac03_real_write_read_passes PASSED [ 50%]
  test_verify_ac03_deliberate_failure FAILED [100%]
  E       AssertionError: deliberate failure for FR-11 AC-03
  E         - AC-03 deliberately wrong expectation: ac03-b908ee1ceaa54e5d85e68db53f32ad77
  [1/1] backend/tests/e2e/test_verify_ac03_fail_live.py: pytest exit 1, 16 s
  total  2  1  1  0  0  15.1
  nonzero exit: backend/tests/e2e/test_verify_ac03_fail_live.py (pytest exit 1)
  exit 1
  ##[error]Process completed with exit code 1.
  Artifact dataplane-fail-1 has been successfully uploaded! Final size is 23376 bytes. Artifact ID is 13763516843
  ```
  - 실패 이유를 확인했다: 실패는 일부러 넣은 단언 하나(`failures="1" errors="0" skipped="0" tests="2"`)이고, 사전 점검(exit 2)이나 환경 오류가 아니다. 같은 파일의 통과 테스트는 진짜 쓰기·읽기를 했다.
  - artifact를 내려받아 읽었다: `gh run download 42813156652 -n dataplane-fail-1 -D <scratchpad>/art-pr21-fail` → `baseline.txt`, `collect.log`, `files.tsv`, `summary.txt`(위 내용, `exit 1`), `test_verify_ac03_fail_live.{xml,log,jsonl}`, `dmesg.txt`(735줄, 첫 줄 `Linux version 7.0.0-1017-azure`).
  - 같은 실행의 `pass` 조각(job `129819415013`)은 success로 끝났다(`fail-fast: false`, 결정 7). 실행 전체 결론 `failure`, `gh pr checks 21`에 `data-plane (fail, …) fail 49s`, `data-plane (pass, …) pass 1m58s`.
- 정리: PR #21은 merge 없이 닫았고(`CLOSED`), 원격 브랜치 `verify/fr11-ac03-fail`를 지웠고(`git ls-remote` 0줄), worktree와 로컬 브랜치를 지웠다. 임시 브랜치의 두 테스트 파일과 matrix diff는 scratchpad(`test_verify_ac03_fail_live.py`, `test_verify_fr11_ac05_live.py`, `ci-matrix-ac03.diff`)에 남겼다. 실행 기록과 artifact(14일 보관)는 run `42813156652`에 남는다.

### [PASS] AC-05 제품 수정의 효과 (데이터 효과, WSL + 러너 기록)
- 기준: 수정한 코드로 WSL에서 볼륨과 스냅샷을 만들면 호스트 마운트 표에 각 마운트가 한 번만 있고, 클라이언트 컨테이너에서 볼륨과 `.snapshot/<이름>`이 보인다(인스턴스의 rslave 바인드가 여전히 동작). `/`가 shared인 호스트에서 ns의 peer group이 `/`와 다른 것은 러너 실행의 기록으로 본다.
- (1) WSL, 독립 근거: 검증용 테스트 `test_verify_fr11_ac05_live.py`(임시 브랜치에만 있음, 위 AC-03 참고)를 worktree의 실행기로 돌렸다.
  - 실행한 명령: `cd <worktree> && ANF_TEST_OUT=/var/tmp/anf-clone-tests/fr11-verify/local bash scripts/run-dataplane-tests.sh backend/tests/e2e/test_verify_fr11_ac05_live.py backend/tests/e2e/test_verify_ac03_fail_live.py`(root, `setsid nohup`). 실행 전 ns는 마운트 지점이 아니었다(WSL 재부팅 직후, mountinfo 0줄). 그래서 ns 바인드는 이 실행에서 agent의 수정된 `ensure_shared_ns()`가 만들었다.
  - 테스트 내용: NFSv3 볼륨을 만들고 클라이언트가 `a.txt`에 `before`를 쓴 뒤 스냅샷 `s1`을 API로 만든다. 클라이언트가 `after`로 덮어쓰고 `cat /m/a.txt; ls /m/.snapshot; cat /m/.snapshot/s1/a.txt`. 호스트 `findmnt -rn -o TARGET`에서 볼륨·스냅샷 경로 수, 호스트와 인스턴스 컨테이너의 mountinfo를 남긴다.
  - 결과: `1 passed`(16 s). 증거(`.jsonl`):
    ```
    client view: rc 0, stdout "after\ns1\nbefore\n"
    counts {"volume": 1, "snapshot": 1}, ns_propagation "shared", root_propagation "private"
    host:     85 69 8:48 / / rw,relatime - ext4 /dev/sdd …                      (/ = private)
              445 85 8:48 /var/lib/anf-clone/ns /var/lib/anf-clone/ns … shared:355 - ext4 …
              446 445 253:4 / /var/lib/anf-clone/ns/e2ev503a-f11 … shared:356 - ext4 /dev/mapper/anf-vol_0574…
              608 446 253:5 / /var/lib/anf-clone/ns/e2ev503a-f11/.snapshot/s1 ro … shared:373 - ext4 /dev/mapper/anf-snap_de9b…
    instance: 645 636 8:48 /var/lib/anf-clone/ns /export … master:355
              646 645 253:4 / /export/e2ev503a-f11 … master:356
              609 646 253:5 / /export/e2ev503a-f11/.snapshot/s1 ro … master:373
    teardown: leftovers_deleted [], dataplane {"lvs": [], "instances": {}, "ns": []}
    ```
    볼륨과 스냅샷이 호스트 마운트 표에 한 번씩이다. 인스턴스의 `/export`는 ns 그룹 355의 slave(`master:355`)이고, 인스턴스가 뜬 뒤에 만든 스냅샷 마운트(`609`, `master:373`)가 그 안으로 전파됐다. 클라이언트는 현재 내용 `after`와 `.snapshot/s1`의 스냅샷 시점 내용 `before`를 읽었다.
- (2) WSL에서 `/`가 shared인 호스트를 흉내 냄(수정 전 순서 대 제품 함수): scratchpad `ns_shared_root_sim.sh`. `unshare -m --propagation private` 안에서 `mount --make-rshared /` 뒤, (가) 수정 전 순서(bind 뒤 shared로 보이면 rshared 건너뜀)를 셸로, (나) 제품 `NfsInstances(Runner(), Path(D/new), …).ensure_shared_ns()`를 두 번 불러 각각 아래에 tmpfs 탐침 하나를 마운트했다.
  ```
  == / in this namespace: shared         474 461 8:48 / / … shared:355
  (가) bind propagation right after bind: shared  (pre-fix code skips --make-rshared)
       617 474 … /var/tmp/fr11-sim.nFjpfG/old … shared:355        ← / 와 같은 group
       probe entries in mountinfo: 2   (618 under 617, 619 under 474, both shared:392)
  (나) ensure_shared_ns called twice; ns propagation: shared
       620 474 … /var/tmp/fr11-sim.nFjpfG/new … shared:393        ← 자기 group
       bind mounts of …/new: 1; probe entries in mountinfo: 1
  cleanup: 두 경우 모두 한 번의 umount 뒤 0. exit=0. 호스트 네임스페이스에 남은 fr11-sim 마운트 0, / 는 여전히 private
  ```
  S3의 러너 탐침(as-is 2줄 `shared:1`, private 1줄 자기 group)과 같은 모양이 WSL 커널 6.18에서도 재현됐고, 제품 함수는 1줄·자기 group을 만든다. 두 번째 호출은 바인드를 더 만들지 않았다(1개).
- (3) 러너(`/`가 shared) 기록, PR #21 실행 `42813156652`(검증 대상과 같은 제품 코드):
  - `fail` 조각 job `129819414501`: `propagation of /: shared`, 테스트 뒤 `28 1 259:1 / / … shared:1`, `273 28 259:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns … shared:333`.
  - `pass` 조각 job `129819415013` success: `test_snapshot_contract_live.py` 5 통과(S3 as-is 실패 8개 중 하나인 `test_ac01_create_snapshot_contract_and_state` 포함), `test_verify_fr11_ac05_live.py` 1 통과, 실행기 `exit 0`. artifact `dataplane-pass-1`의 `.jsonl`: `counts {"volume": 1, "snapshot": 1}`, `root_propagation "shared"`, `ns_propagation "shared"`, 호스트 `28 1 … / / … shared:1` 대 `99 28 … /var/lib/anf-clone/ns … shared:334`, 볼륨 `100 99 … shared:325`, 스냅샷 `422 100 … .snapshot/s1 … shared:371`, 인스턴스 `/export … master:334`, `/export/…/.snapshot/s1 … master:371`, 클라이언트 `after\ns1\nbefore\n`.
- (4) PR #20 실행 `42811747210`의 "Mount propagation of ns" 단계(테스트 뒤, `if: always()`):
  - throughput job `129814648050`: `28 1 259:1 / / … shared:1`, `61 28 259:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns … shared:324`.
  - rest job `129814648451`: `28 1 259:1 / / … shared:1`, `102 28 259:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns … shared:333`.
  두 조각 모두 `/`가 shared인 러너에서 ns 바인드가 `/`(shared:1)와 다른 자기 peer group을 받았다. 같은 실행의 rest 조각에서 마운트 수를 세는 S3 실패 8개가 모두 통과했다(AC-02).
- 판정: WSL에서 각 마운트가 호스트 마운트 표에 한 번, 인스턴스 안에도 보이고, 클라이언트가 볼륨과 `.snapshot/s1`을 읽었다((1)). `/`가 shared인 러너에서 ns의 peer group이 `/`와 다르다((3)(4)). (2)는 그 차이가 제품 함수 때문임을 같은 커널에서 수정 전 순서와 나란히 보였다.

## 판정 밖 관찰

1. **WSL 배포판이 검증 중에 한 번 다시 시작됐다(유휴 정지로 추정).** AC-05 (1) 실행 직후 확인에서는 `/`가 mount `85`, ns 바인드 `445 … shared:355`가 있었는데, 1~2분 뒤 명령에서는 `/`가 `86`이고 ns 바인드가 없었으며 `uptime`이 `up 2 min`이었다. VG `anf`는 그대로 보였다. 내 명령 사이에 WSL 안에 도는 프로세스가 없던 틈이다. AC-05 (1)은 실행기 한 프로세스 안에서 끝났고(콘솔 완전, 실행기 `exit 1`은 AC-03 실패 파일 때문), (2) 흉내는 이전 상태에 기대지 않으므로 판정에 영향이 없다. 다음 세션이 WSL에 상태를 남겨 두고 이어 쓸 계획이면 이 정지를 감안해야 한다.
2. **메인 세션의 로컬 커밋 `932cdc8`**(CLAUDE.md, docs/ADR.md만, 03:59:18 PST)이 검증 중에 주 체크아웃에 생겼다. push되지 않았고(`origin/feature/ci-dataplane` = `f6f2e1c`), 제품 코드 해시는 그대로 `9a023d13…`다. push하면 `concurrency: cancel-in-progress` 때문에 PR #20의 진행 중 실행이 취소되고 새로 돈다.
3. **새 단위 테스트의 응답 하나가 쓰이지 않는다.** `test_shared_ns_new_bind_leaves_the_peer_group_of_a_shared_root`(`backend/tests/unit/test_nfs_instance.py`)는 `runner.sequence("findmnt", (1, ""), (0, "shared\n"))`로 "바인드 뒤 shared로 보임"을 흉내 내지만, `ensure_shared_ns()`(`backend/storage_agent/nfs_instance.py:107-112`)는 findmnt를 한 번만 부르므로 두 번째 응답은 소비되지 않는다. 단언(bind → private → rshared 순서)은 맞고 실제 shared `/` 조건은 위 AC-05 (2)(3)이 덮으므로 결함은 아니다. 테스트 이름이 말하는 조건을 테스트가 실제로 만들지는 않는다는 점만 적는다.
4. **`actions/upload-artifact@v4` Node.js 20 경고.** PR #21 job 로그 끝: `Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/upload-artifact@v4`. 지금은 동작한다. 나중에 v5 이상으로 올릴 거리다.
5. 러너의 준비 단계(`Set up the data plane`)는 PR #21의 두 조각에서 6 s(`pass`)와 13 s(`fail`), PR #20에서 10 s·9 s였다(이미지 빌드 포함).
6. **rest 조각의 dmesg 앞부분이 빠진다.** `dataplane-rest-1/dmesg.txt`는 12:07:47부터 시작한다(3,663줄). 조각이 약 38분 도는 동안 커널 링 버퍼가 넘쳐 부팅~12:07의 커널 로그가 덮였다. 처리량 조각(1,169줄)은 부팅부터 남았다. 앞부분이 필요한 실패를 가르려면 `Collect logs`에서 `journalctl -k -b`(journal은 링 버퍼보다 오래 남는다)를 쓰거나 테스트 전 단계에서 한 번 더 dmesg를 남기는 방법이 있다.
7. **push 실행에서 data-plane이 돌지 않음을 확인했다(결정 5).** 같은 커밋의 push 실행 `42811738312`에서 `data-plane` job은 `skipped`, backend·frontend는 success다. PR #21의 push 실행 `42813126597`에서도 `data-plane skipping`이었다.
