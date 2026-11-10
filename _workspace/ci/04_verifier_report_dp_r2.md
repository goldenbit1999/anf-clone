# ci 2부 (FR-11 data-plane 작업) 검증 보고서 — 2회차

- 진행 상태: 완료 (2026-11-10 14:30Z쯤). 임시 PR #22는 닫았고 원격 브랜치 `verify/fr11-r2-tp-repeat`, 로컬 브랜치, scratchpad worktree `wt-r2`는 지웠다
- 검증일: 2026-11-10
- 검증 대상 코드: 제품 코드 내용 해시 시작 `9a023d13b647ba1f0363bfa75a22c66ea362991e5baca42796bef74e6cab92f1`, 끝 `9a023d13b647ba1f0363bfa75a22c66ea362991e5baca42796bef74e6cab92f1`(1회차와 같음). 커밋 `89af8b6`(`origin/feature/ci-dataplane`와 같음, Actions 실행의 대상). 검증 중 주 체크아웃에 문서 커밋 `9514dda`가 더해졌다(`_workspace/throughput-limit/02_main_design.md`, `docs/concepts/throughput-limit.md` 각 1줄, 제품 해시 변화 없음, 아직 push 안 됨). 미커밋 변경 없음(추적 안 함 `docs/ai-readiness-*`, `.claude/worktrees/`, 이 보고서)
- 이번 회차 범위: 재검증. 다시 실행: AC-01(PR #20 새 실행 + 처리량 파일 9회 반복), AC-02·05(새 실행의 기록), AC-04(`kernel-journal.txt`), AC-07(새 실행), AC-08(조각 시간). 영향 확인 후 유지: AC-03·06(AC-03은 반복 실행의 실패 조각으로 다시 관찰됨)
- 이전 보고서: `_workspace/ci/04_verifier_report_dp.md`(1회차, PASS 7 / FAIL 1)

## 1회차 뒤 바뀐 것 (`f6f2e1c..89af8b6`)
커밋 `932cdc8`, `504e984`(문서·기록), `c66e51a`(시험 수정), `89af8b6`(기록). `git diff --stat f6f2e1c 89af8b6`:

| 파일 | 종류 | 영향을 받는 기준 |
| --- | --- | --- |
| `backend/tests/e2e/test_throughput_limit_data_live.py` (+23/-) | 시험: AC-04 하한을 `Succeeded` 뒤 1~5 s 창의 중앙값으로, 올렸을 때 첫 창 > 옛 한도 × 1.01, 상한은 0~2 s 모든 창 그대로. AC-07 (e)·AC-09의 바꾼 뒤 쓰기를 `quick` → `measure` | AC-01, AC-08 |
| `backend/tests/e2e/throughput_live.py` (-7) | 시험: `quick` 삭제 | AC-01 |
| `.github/workflows/ci.yml` (+4/-) | "Collect logs"에 `sudo journalctl -k -b --no-pager \| sudo tee "$OUT/kernel-journal.txt" > /dev/null \|\| true`, 주석 | AC-04 |
| `docs/testing.md`, `docs/ADR.md`, `CLAUDE.md`, `docs/concepts/ci.md`, `docs/concepts/test-automation.md`, `_workspace/ci/*` | 문서·기록 | 없음 |

제품 코드(`pyproject.toml`, `backend` 중 tests 밖)는 바뀌지 않았다. 해시를 직접 계산했다: `9a023d13…cab92f1`(주 체크아웃 `89af8b6`과 `9514dda`, 임시 브랜치 worktree 모두). 데이터 플레인의 다른 12개 시험 파일, 실행기, 준비 스크립트도 바뀌지 않았다.

## 환경 사전 점검
| 항목 | 결과 |
| --- | --- |
| gh CLI | `goldenbit1999` 로그인, 원격 `origin/feature/ci-dataplane` = `89af8b6` |
| Actions | PR #20의 새 `pull_request` 실행 `42824999459`(headSha `89af8b6`, 13:29:38Z), `push` 실행 `42824990246` |
| 반복용 임시 브랜치 | scratchpad worktree `wt-r2`에서 `89af8b6` → `verify/fr11-r2-tp-repeat`(커밋 `26122fb`, ci.yml matrix만 `shard: [tp1..tp9]` × `args: [backend/tests/e2e/test_throughput_limit_data_live.py]`). draft PR #22 "[verify, do not merge] FR-11 round 2: throughput data file x9", 실행 `42825248067`(13:31Z), data-plane job 9개가 동시에 시작 |
| 러너 VM | 실행마다 다르다(EPYC 7763, EPYC 9V45, Xeon 8573C·6973P-C·8370C, 메모리 약 16 GB). 실패한 tp8은 EPYC 9V45이고, 같은 종류인 tp2·tp3·tp9는 통과했다 |
| WSL | implementer 결과 파일을 읽는 데만 썼다(전체 묶음은 돌리지 않음). `/var/tmp/anf-clone-tests/fr11-tp-floor` 존재 |

## 결과 요약
PASS 7 / FAIL 1 / UNVERIFIED 0

- AC-01 FAIL(간헐). PR #20 실행 자체는 두 조각 success, 113/113이라 기준 문장은 채웠다. 그러나 3의 규칙에 따른 반복(처리량 파일 10회: PR #20 + 9회)에서 1회(tp8)가 실패했다.
- 1회차 결함(하한 미달)은 10회 중 0회다. 하한·상한 위반 창이 한 번도 없었다. tp8은 다른 결함이다: `test_ac07_limit_survives_lifecycle`의 (c) "docker rm + re-PUT"에서 볼륨 PUT 작업이 1초 만에 `InternalServerError`로 끝났고, 시험이 그 상태를 확인하지 않은 채 hard mount 쓰기를 450 s 기다리다 시간 초과로 실패했다.

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | FAIL (간헐 1/10. PR #20 실행은 success 113/113, 하한 결함 0/10, 새 결함 AC-07 (c) 1/10) | 2회차 |
| AC-02 | PASS | 2회차 |
| AC-03 | PASS (1회차 유지 + 2회차 tp8 조각에서 다시 관찰) | 1회차 + 2회차 |
| AC-04 | PASS | 2회차 |
| AC-05 | PASS (WSL 부분 1회차 유지, 러너 부분 2회차) | 1회차 + 2회차 |
| AC-06 | PASS (1회차 유지, `fr11-tp-floor` 7/7) | 1회차 + 2회차 근거 |
| AC-07 | PASS | 2회차 |
| AC-08 | PASS | 2회차 |

## 항목별 결과

### [FAIL, 간헐] AC-01 data-plane 작업 (PRD FR-11)
- 기준: main 대상 PR에서 `data-plane` 작업의 두 조각이 모두 success, 합쳐 수집 113, 통과 113, 실패·오류·skip 0, 13개 파일이 겹치거나 빠지지 않는다. 1회차 FAIL이 간헐이었으므로 1회차 보고서의 계획대로 3의 규칙을 적용했다: p ≈ 1/3(러너 3회 중 1회) → n = ⌈3/p⌉ = 9회 연속 통과.
- 실행 1, PR #20 run `42824999459`(success):
  - throughput job `129859912509`: 13:29:42Z~14:08:24Z, 실행기 `7 7 0 0 0`, `time: 2293 s`, `exit 0`
  - rest job `129859912655`: 13:29:42Z~14:06:14Z, 실행기 106/106, `time: 2165 s`, `exit 0`
  - 두 artifact를 `merge_shards.py`로 합침: 13개 파일, 113개 ID, 겹침 0, 빠짐 0, 남는 것 0, 통과 113, 실패·오류·skip 0. 여기까지는 기준 문장을 채운다.
- 실행 2, 반복: PR #22 run `42825248067`, 처리량 파일만 9조각(결론 failure). 아래 "반복 근거" 절의 표.
  - tp1~tp7·tp9는 7/7, tp8은 6/7.
  - PR #20을 더해 10회 중 9회 통과. 9회 연속 통과에 못 미쳐 FAIL이다.
- 1회차 결함은 고쳐졌다:
  - 10회 모두 AC-04 하한(1~5 s 중앙값, 0.9879~1.0060)과 상한(0~2 s 창 최대 1.0084), AC-09·AC-07 (e)의 `measure`(0.9956~0.9986)가 범위 안이다.
  - 1회차에 실패했던 두 시험(`test_ac04_limit_changes_during_io`, `test_ac09_auto_to_manual_keeps_the_limit`)은 10/10 통과했다.
- tp8 실패(새 결함): `test_ac07_limit_survives_lifecycle`. 근거는 tp8 artifact(`dataplane-tp8-1`)의 `.log`, `.jsonl`, `kernel-journal.txt`, `summary.txt`:
  - 단계 (a) 1.0014, (b) 1.0013(다시 흐를 때까지 1.51 s)은 통과했다.
  - 단계 (c) "docker rm + re-PUT"에서 `subprocess.TimeoutExpired: Command '['docker', 'exec', 'anfe2e-cli-bb25313d', 'sh', '-c', 'fio … --runtime=150 --name=write --rw=write --filename=/m/f --size=150M']' timed out after 450 seconds` (`test_throughput_limit_data_live.py:370` → `through_step` `:315`).
  - 시각(`.jsonl`):
    - 13:59:53.5 (b)의 기록이 끝나고 (c)의 쓰기가 시작됐다. 6 s 뒤 `docker rm -f`가 나갔다(추정 13:59:59.5).
    - 14:00:11.525 re-PUT `200`이 왔다. 그 앞의 `docker rm -f`는 약 12 s 걸렸다. 통과한 9회에서는 단계 (c) 전체(rm + PUT + `Succeeded`까지 폴링)가 2.14~3.21 s였고 `docker_rm_rc` 0이었다.
    - 14:00:12.531 작업 `6b661aae-a775-4a41-abb7-449241369d13`이 `Failed`로 끝났다. `"code": "InternalServerError"`, "Something unexpected occurred when performing this action. Please try again, and provide the operation id '6b661aae-…'"였다. 이것은 처리기 예외를 모두 덮는 일반 문구다(`backend/anf_api/lro.py:127-133`). 원인은 anf-api 로그에만 남는데, 그 로그는 artifact에 없다(설계 §6 4번).
  - 커널 저널(tp8에만 있음. 나머지 9회는 아래 두 줄이 모두 0줄):
    - `rpcbind: server localhost not responding, timed out`가 14줄 찍혔다. 14:00:09부터 14:02:22까지 약 10 s 간격이다. 함께 `svc: failed to register nfsdv3 RPC service (errno 5).`, `nfsaclv3`, `lockdv1`, `failed to unregister tcp/udp with rpcbind`도 있다.
    - 지운 인스턴스의 veth `veth948afd9`는 (b)에서 13:57:28에 생겼다. 그것이 14:02:22에야 bridge에서 빠졌다(`entered disabled state`).
    - 그 볼륨의 새 인스턴스 veth는 끝까지 생기지 않았다(다음 veth는 14:07:38의 ac09 것).
    - 14:02:58~14:03:22에 `nfs: server 172.30.0.129 not responding, still trying`가 16줄 찍혔다. 클라이언트 hard mount다.
  - 실행기 요약: `1 failed, 0 errors.`, `left behind (not removed): container anfe2e-cli-bb25313d`(I/O에 걸린 클라이언트), `exit 1`.
- 추정 원인 [추론, agent·anf-api 로그가 없어 확정 못 함]:
  1. `docker rm -f`로 knfsd 인스턴스를 SIGKILL하면 커널이 그 netns를 정리하면서 nfsd/lockd의 rpcbind 등록을 지운다. 그런데 컨테이너 안의 rpcbind는 이미 죽어 있다. 이 실행에서는 그 호출이 10 s씩 시간 초과하며 netns 정리가 약 2분 20초 걸렸다.
  2. 그 사이 바로 들어온 re-PUT에서 agent의 인스턴스 시작 경로가 곧바로 실패했다. 이 경로는 `NfsInstances.start()`(`backend/storage_agent/nfs_instance.py:154-166`)다. `docker inspect`로 상태를 보고, 컨테이너가 있으면 `docker start`, 없을 때만 `docker run`을 한다. 그 뒤 `limit()`(`:130`, pid가 없으면 InstanceError)과 `wait_ready`(`:168-177`)가 이어진다. 1초 만에 끝났으니 150 s `wait_ready` 시간 초과는 아니다. 이름·고정 IP·컨테이너 상태 중 무엇이 막았는지는 로그 없이는 모른다.
  3. 작업이 `Failed`인데 시험은 그것을 보지 않고 쓰기만 기다렸다. 그래서 진짜 원인이 450 s 시간 초과와 남은 클라이언트 컨테이너로 드러났다.
- 분류:
  - 제한기(tc)나 처리량 판정 범위의 문제가 아니다. 이 실행에서도 앞 단계와 다른 6개 시험은 범위 안이었다.
  - 운영자가 인스턴스 컨테이너를 강제로 지운 직후의 재ensure 경로에 있는 드문 결함이다(제품 견고성 + 시험의 진단 부족).
  - 이 단계는 러너에서 약 13번 돌았다(S3 2, 1회차 1, 이번 10). 그중 1번 보였다. WSL에서는 본 적이 없다.
  - 새 결함의 관찰 실패율 p ≈ 1/10이므로, 고친 뒤 3의 규칙으로는 n = 30회가 필요하다(처리량 파일 단위로 반복하면 약 40분짜리 조각 30개).
- 수정 제안(리더 판단용, 제품 코드는 고치지 않았다):
  1. 시험(`backend/tests/e2e/test_throughput_limit_data_live.py:353-364`의 `remove_instance_then_put`, `revert_to_s1`, `:305` `through_step`):
     - 단계 함수가 `final == "Succeeded"`를 단언한다. 실패하면 바로 작업 본문을 보여 주고 쓰기를 기다리지 않는다.
     - 실패 경로에서 클라이언트 컨테이너를 지운다(hard mount라 `docker rm -f`가 필요할 수 있다).
  2. 제품(`backend/storage_agent/nfs_instance.py:154-166`):
     - 컨테이너가 있지만 running이 아니거나 지워지는 중이면, 사라질 때까지(`docker wait`/`docker rm -f` 뒤 확인) 기다렸다 `docker run`을 다시 한다.
     - `docker run`의 이름·IP 충돌은 제한 시간 안에서 재시도한다.
     - 실패를 InstanceError로 올릴 때 docker stderr를 job 오류에 담는다. anf-api는 agent 오류를 일반 `InternalServerError` 대신 작업 오류에 싣는다(`backend/anf_api/lro.py:127-133`, `storage_client.py`).
  3. 관측: data-plane artifact에 pytest tmp의 `agent.log`와 anf-api 로그를 다시 올린다(설계 §6 4번에서 뺀 것). 이번 원인을 확정하지 못한 직접 이유다.
  4. 판정 범위를 넓히는 것은 도움이 안 된다. 범위 문제가 아니기 때문이다.

### [PASS] AC-02 그대로의 러너
- 기준: 워크플로에 ns 전파를 손대는 단계가 없고, Runner info에 `/`가 `shared`, S3에서 실패했던 8개 테스트가 통과 목록에 있다.
- 워크플로: 1회차 뒤 ci.yml에서 바뀐 것은 "Collect logs"의 `journalctl` 줄과 주석뿐이다. ns 전파를 바꾸는 단계는 여전히 없다.
- PR #20 run `42824999459`의 Runner info:
  - throughput job `129859912509`: `2026-11-10T13:29:55.5023408Z propagation of /: shared`
  - rest job `129859912655`: `2026-11-10T13:29:55.8330761Z propagation of /: shared`
- S3 as-is 실패 8개는 rest 조각에서 모두 passed였다(`merge_shards.py` 출력, 1회차와 같은 ID 목록으로 대조).

### [PASS, 1회차 유지 + 2회차 재관찰] AC-03 실패를 알림 (CI)
- 1회차 근거: `04_verifier_report_dp.md` AC-03 (PR #21 run `42813156652`, `fail` 조각 failure, artifact 업로드).
- 2회차: 반복 실행의 tp8이 진짜 시험 실패로 같은 경로를 다시 보였다. job `129860744632` 결론 failure였다.
  - 단계별 결과: "Data-plane tests (tp8)" failure → "Mount propagation of ns" success → "Collect logs" success → "Upload logs" success.
  - artifact `dataplane-tp8-1`을 내려받아 읽었다.
  - 실행기 `summary.txt`: `nonzero exit: … (pytest exit 1)`, `exit 1`.
- ci.yml에서 바뀐 `journalctl` 줄은 `|| true`가 붙어 실패 경로를 바꾸지 않는다. 실패 조각에서도 `kernel-journal.txt`가 올라왔다.

### [PASS] AC-04 artifact
- 기준: 조각마다 실행기 출력 폴더(JUnit XML, `.log`, `.jsonl`, `summary.txt`)와 dmesg가 artifact로 남고 내려받아 읽을 수 있다. 이번 회차에 더한 `kernel-journal.txt`도 본다.
- PR #20:
  - `dataplane-throughput-1`(77,715 B)과 `dataplane-rest-1`(480,964 B)을 `gh run download`로 받았다.
  - 둘 다 `summary.txt`, `baseline.txt`, `files.tsv`, `collect.log`, 파일별 `.xml`·`.log`·`.jsonl`, `dmesg.txt`, `kernel-journal.txt`가 있다(rest는 12개 파일분).
- PR #22: `dataplane-tp1-1`~`dataplane-tp9-1`(각 약 78 KB) 9개가 모두 같은 구성으로 있다.
- 읽을 수 있다는 근거: 이 보고서의 측정값과 tp8 분석이 모두 이 파일들(scratchpad `r2/`)에서 나왔다. tp8의 원인 추적은 새로 더한 `kernel-journal.txt`가 있어서 가능했다.

### [PASS] AC-05 제품 수정의 효과
- WSL 부분(1회차 유지): ns `shared:355`, 볼륨·스냅샷 마운트가 각각 한 번, 클라이언트가 볼륨과 `.snapshot/s1`을 읽음. 제품 코드 해시가 같아 유지한다.
- 러너 부분, PR #20 새 실행의 "Mount propagation of ns" 기록:
  - throughput: `28 1 259:1 / / rw,relatime shared:1 …`, `264 28 259:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns rw,relatime shared:302 …`
  - rest: `28 1 8:1 / / rw,relatime shared:1 …`, `97 28 8:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns rw,relatime shared:333 …`
- 두 조각 모두 ns의 peer group이 `/`(`shared:1`)와 다르다.

### [PASS, 1회차 유지] AC-06 WSL 전체 회귀 (회귀)
- 1회차 근거: `04_verifier_report_dp.md` AC-06 (`/var/tmp/anf-clone-tests/20261110T102847Z`, 113/113, skip 0, exit 0, 남은 것 없음).
- 유지 이유: 제품 코드 해시가 같다(`9a023d13…`). 실행기·준비 스크립트와, 처리량 데이터 파일 밖의 데이터 플레인 시험 12개 파일은 바뀌지 않았다. 바뀐 시험 파일은 implementer가 WSL에서 새 코드로 다시 돌렸다(합의 규칙대로 전체 묶음은 다시 돌리지 않음):
  - `/var/tmp/anf-clone-tests/fr11-tp-floor/summary.txt`: `test_throughput_limit_data_live 7 7 0 0 0 2423.2`, `collected 7, skipped 0`, `time: 2424 s`, `exit 0`. XML `errors="0" failures="0" skipped="0" tests="7"`.
  - 새 코드로 돌았다는 근거: 실행 시작(baseline.txt) 04:47:35 PST가 시험 파일 mtime 04:45:43과 커밋 `c66e51a` 04:47:10보다 늦다. 또 `.jsonl`에 새 필드 `settled_ratio`가 있다(0.9919, 1.0042, 0.9991, 0.9839, 1.0052, 0.9988).
  - 그 실행의 측정 요약(`tools/tp_repeat.py`, 폴더 사본 scratchpad `ref/wsl-fr11-tp-floor`):
    - AC-04 1~5 s 중앙값 비율 0.9839~1.0052, 0~2 s 창 상한 비율 최대 1.0088
    - `measure` 중앙값 비율 0.9863~0.9944
    - AC-07 창 중앙값 0.9982~0.9998, over_limit 0
- WSL은 tp8의 결함을 다시 해 보지 않았다(전체 묶음 재실행 금지. 이 결함은 러너에서만 관찰됐다).

### [PASS] AC-07 기존 작업 (CI) — 2회차 다시 실행
- 기준: 같은 PR 실행에서 backend·frontend 작업이 통과한다(단위 테스트에 `ensure_shared_ns`의 새 경우 포함, skip 0, ruff).
- 실행: PR #20 run `42824999459`. checkout `HEAD is now at 67c7cba Merge 89af8b6… into 7255e3e…`. `67c7cba^{tree}` = `89af8b6^{tree}` = `2d2aa407…`.
- 출력(핵심 부분, 로그 scratchpad `logs-r2/pr20-backend-129859912834.log`, `logs-r2/pr20-frontend-129859912189.log`):
  - backend job `129859912834` success (13:29:42Z~13:32:44Z): `All checks passed!`, `collected 1102 items / 113 deselected / 989 selected`, `989 passed, 113 deselected in 152.82s`, 게이트 `collected 989, skipped 0`, hook 테스트 `25 passed`. `test_nfs_instance.py` 점 32 + 16 = 48(새 `ensure_shared_ns` 테스트 2개 포함).
  - frontend job `129859912189` success (13:29:42Z~13:29:57Z): `tsc --noEmit`, `Test Files 4 passed (4)`, `Tests 23 passed (23)`, `✓ built in 153ms`.

### [PASS] AC-08 시간
- 기준: 각 조각이 50분 안에 끝난다.
- PR #20: throughput 13:29:42Z~14:08:24Z = 38분 42초, rest 13:29:42Z~14:06:14Z = 36분 32초.
- PR #22(같은 처리량 파일): 통과한 8개 조각은 38분 28초~38분 43초였다. 실패한 tp8은 13:31:15Z~14:12:30Z = 41분 15초로, 450 s 시간 초과를 포함한 최악의 경우다.
- 모두 50분 안이다.

## 반복 근거: 처리량 데이터 파일 10회
PR #20 throughput 조각 1회와 PR #22 9조각을 합친 것이다. 분석 스크립트는 scratchpad `tools/tp_repeat.py`, 출력은 `r2/tp_repeat.out`이다. 비율은 측정값 ÷ 한도.

| 실행 | 결과 | 실행기 시간 | AC-04 1~5 s 중앙값 비율 | AC-04 0~2 s 창 최대 | AC-04 가장 낮은 활성 창(5 MiB/s) | AC-07 (c) |
| --- | --- | --- | --- | --- | --- | --- |
| PR #20 | 7/7 | 2,293 s | 1.0002~1.0053 | 1.0076 | 4.960 | 1.0013, 다시 흐를 때까지 0.90 s |
| tp1 | 7/7 | 2,299 s | 0.9879~1.0036 | 1.0039 | 4.975 | 1.0005, 0.34 s |
| tp2 | 7/7 | 2,291 s | 1.0001~1.0053 | 1.0052 | 4.978 | 1.0013, 0.90 s |
| tp3 | 7/7 | 2,296 s | 1.0010~1.0060 | 1.0064 | 4.979 | 1.0016, 0.82 s |
| tp4 | 7/7 | 2,293 s | 1.0010~1.0050 | 1.0082 | 4.979 | 1.0016, 0.87 s |
| tp5 | 7/7 | 2,295 s | 0.9960~1.0047 | 1.0084 | 4.979 | 1.0013, 0.87 s |
| tp6 | 7/7 | 2,292 s | 1.0001~1.0058 | 1.0076 | 4.989 | 1.0011, 0.89 s |
| tp7 | 7/7 | 2,282 s | 1.0010~1.0050 | 1.0070 | 4.985 | 1.0015, 0.90 s |
| tp8 | 6/7 (AC-07 failure) | 2,450 s | 1.0000~1.0048 | 1.0078 | 4.992 | 작업 `Failed`(InternalServerError), 쓰기 450 s 시간 초과 |
| tp9 | 7/7 | 2,292 s | 1.0012~1.0052 | 1.0082 | 4.964 | 1.0013, 0.88 s |

10회 전체(`== all`):
- AC-04:
  - 1~5 s 중앙값 비율: n=60, 0.9879~1.0060(하한 0.90, 상한 1.01)
  - 0~2 s 창 상한 비율: n=60, 0.9969~1.0084. 1.01을 넘은 창 0
  - 올렸을 때 첫 창 ÷ 옛 한도: n=40. 10→30은 약 3.0, 5→10은 약 2.0이다(최소 1.9942, 최대 3.0078). 모두 1.01 초과
- `measure` 중앙값 비율: n=149, 0.9934~1.0017. 한 회라도 1.01을 넘은 측정 0. 이 중 AC-09·AC-07 (e)의 바꾼 뒤 쓰기(전의 `quick`)는 0.9956~0.9986이었다.
- 측정별 범위:
  - AC-01b 읽기 0.9934~0.9948, 쓰기 0.9964~0.9986
  - AC-02/03 10 MiB/s: 쓰기 0.9984~0.9986, 읽기 0.9954~0.9968, 섞음 0.9988~1.0017
  - AC-02/03 20 MiB/s: 쓰기 0.9976~0.9986, 읽기 0.9945~0.9976, 섞음 0.9969~1.0002
  - AC-05 홀로 0.9936~0.9967
  - AC-06 큰 쓰기 0.0591~0.0593(한도 0.062)
- AC-07 단계 창 중앙값 비율: n=38, 1.0002~1.0021, over_limit 창 0. 새 하한 판정이 실제 느려짐을 가린 흔적은 없다.
- 판정: 1회차 결함(하한)은 0/10이다. 그러나 반복 전체로는 1/10 실패라 3의 규칙(n=9, 실패 0)을 채우지 못했다 → AC-01 FAIL.

## 판정 밖 관찰
- tp8 실패 뒤 실행기가 클라이언트 컨테이너 `anfe2e-cli-bb25313d`를 남겼다. CI 러너는 버려지므로 해가 없다. 하지만 WSL에서 같은 일이 생기면 사람이 지워야 한다(실행기는 목록만 낸다. 설계대로다).
- 같은 결함이 사용자에게 보이는 모습은 이렇다. 볼륨이 `Failed`이고, 오류는 일반 문구뿐이며, 인스턴스는 다시 뜨지 않았다(새 veth 없음). 재시도 PUT이 회복시키는지는 이번 실행에서 보지 못했다(시험이 재시도하지 않음). [추론] agent는 매 단계 실제 상태를 먼저 확인하므로, netns 정리가 끝난 뒤의 재시도는 성공할 가능성이 높다.
- 검증 중 주 체크아웃에 문서 커밋 `9514dda`가 생겼다. Actions 실행은 `89af8b6` 대상이다. 둘의 차이는 문서 2줄이고 제품·시험·워크플로 차이는 없다.

## 정리
- PR #22: `gh pr close 22`(설명 댓글), 상태 `CLOSED`.
- 원격 브랜치 `verify/fr11-r2-tp-repeat` 삭제(`git ls-remote --heads origin`에 `verify/` 0개). 로컬 브랜치 삭제(`26122fb`). worktree `wt-r2` 제거.
- `git worktree list`: 주 체크아웃과 원래 있던 `.claude/worktrees/agent-aee96ed1b59426045 [spike/s3-runner] locked`만 남았다(건드리지 않음).
- `main`과 `feature/ci-dataplane`에는 push하지 않았다. 주 체크아웃에서 바꾼 것은 이 보고서뿐이다.
- 내려받은 artifact와 로그는 scratchpad `r2/`, `logs-r2/`에 있다(커밋하지 않음).
