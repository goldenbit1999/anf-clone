# 컨테이너 (FR-13) 검증 보고서 — 2회차

- 진행 상태: 완료 (2026-11-10 16:00~16:40 PST 기록 판정, 16:40~16:50 PST 메인의 HEAD 8회 반복 기록을 더해 AC-03 다시 판정)
- 검증일: 2026-11-10
- 검증 대상 코드:
  - HEAD `488703174a195403c99f7914277524f834972552` (`feature/containers`, `4887031`). 1회차 끝(`7cc13c1`) 뒤의 커밋:
    - `a78ae70` 15:19 1회차 보고서
    - `dcf18d7` 15:31 데모 6단계를 "천장 + 한도를 따라 바뀜"으로 판정, 한도 10 → 5를 20 → 5로
    - `8c02910` 15:31 agent의 두 긴 문법 바인드에 `create_host_path: true`(1회차 판정 밖 관찰 1), `test_compose.py` +1 테스트
    - `9120af6` 15:35 README·testing.md·설계
    - `85428ec` 15:49 회마다의 천장 = 한도의 101% + 6 s 창의 1 MiB I/O 하나
    - `4887031` 15:50 문서, `demo.py`는 주석만(38% → 36%), 단위 테스트 0.36
  - 제품 코드 내용 해시: 시작·끝 모두 `7c38d8c7fdf750e4a4c32b06802475b0a5e3e2632ea1f60da9e7ac89ac2df4ed` (1회차와 같음)
  - FR-13 참고 해시(pyproject, backend(테스트 제외), deploy, scripts, .dockerignore, .gitattributes): 시작·끝 모두 `64530317a5e20f2c00d322e58ed2fcbd11395d44b3d56508082656a22519cec6` (1회차 `c32b76d8…`에서 바뀜: `deploy/compose.yaml`, `scripts/demo.py`)
  - `git diff --stat 8c02910 HEAD -- deploy scripts` → `scripts/demo.py`만(아래 10회 반복의 compose 파일은 HEAD와 같다)
  - 미커밋: 이 보고서, 원래 있던 `?? docs/ai-readiness-*`(건드리지 않음). 검증 중에 다른 세션이 `docs/concepts/containers.md`와 `docs/testing.md`를 고치기 시작했다(` M`, 해시 밖, 건드리지 않음, 판정하지 않음)
- 이번 회차 범위: 재검증. 리더 지시로 나는 스택·데모·테스트 묶음을 다시 돌리지 않았다. implementer와 메인이 남긴 실행 기록, 그리고 짧은 읽기 전용 점검으로 판정한다.
  - 다시 판정: AC-03(1회차 FAIL), AC-01·AC-02(compose 변경), AC-11(README 변경)
  - 수정의 영향을 받을 수 있어 기록으로 갱신: AC-04(데모 판정·문구), AC-06(agent 바인드), AC-07(한도 20 MiB/s의 메모리), AC-10(바뀐 테스트 파일)
  - 그대로 옮김: AC-05, AC-08(관련 파일이 바뀌지 않음). AC-09는 메인이 PR 뒤 채움

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| WSL | 읽기 전용 점검이 VM을 깨움(uptime 약 51 s). 컨테이너 없음, 스택 포트 비어 있음, VG `anf`는 재부팅 뒤라 아직 안 붙음(`lvs` exit 5, 평소 상태) |
| 판정에 쓴 기록 | 셋 다 원본은 그대로 두고 scratchpad로 복사했다. 파일별 sha256 목록이 원본과 같다.<br>- implementer `/var/tmp/anf-clone-tests/fr13-demo-repeat/`(`8c02910`, 데모 10회 연속, 14개 파일)<br>- implementer `fr13-compose-235101/`과 `.out`(HEAD, compose e2e, 7개 파일, `.out` `46fc851a…`)<br>- 메인 `/var/tmp/fr13-demo-repeat-head/`(HEAD, 데모 8회 연속, 11개 파일) |
| 보관 위치 | `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\fr13-r2\` (`fr13-demo-repeat\`, `fr13-compose-235101\`, `fr13-compose-235101.out`, `fr13-demo-repeat-head\`, `*.sha256`, `old\demo-8c02910.py`) |
| 반복 스크립트, 모양 시험 | 메인의 `…\scratchpad\fr13\demo_repeat_head.sh`(`N=8`, 회마다 `python3 scripts/demo.py`, 게스트 단조 시계로 걸린 시간). implementer의 새 기기 모양 시험 `…\scratchpad\fr13\fresh\`(`fresh.sh`, `fresh-out.txt`, compose 사본들) |
| 끝난 상태(16:45 PST, root 읽기) | 컨테이너 0, 이름 있는 볼륨 0, 포트 8080·8081·8090·9090 리스너 0, LV `aggr0`뿐, `/var/lib/anf-clone/ns`·`exports` 비어 있음 |
| 사용한 도구 | Bash(Git Bash → `wsl`), Read·Write·Grep, `.venv-win` Python(판정 함수 재계산, 단위 테스트 3개 파일, collect-only), WSL venv(collect-only), uv 캐시의 ruff 0.14.0. 새로 설치한 것 없음 |

## 결과 요약

PASS 10 / FAIL 0 / UNVERIFIED 0 (AC-09는 메인이 PR 뒤 채움)

- AC-03: HEAD 코드로 데모 10회 연속 `exit 0`. e2e 안의 2회에 메인의 8회 반복을 더했다. 1회차 실패율 p = 0.3의 n = 10을 충족한다. 1회차 결함(아래쪽 판정의 거짓 실패)은 다시 나오지 않았고, 수정 중에 생긴 07회 결함(5 MiB/s에서 101% 천장에 걸린 I/O 하나)의 촉발 조건이 HEAD 8회 중 2회(5.15, 5.1) 실제로 나왔지만 새 천장이 통과시켰다.
- 알려진 한계로 남는 것: `follows_limit`의 내리기 전 쪽 여유가 얇다(8회차 중앙값 7.25 = 36%, 문턱 5.05). 메인은 코드를 바꾸지 않을 생각이다. 나는 일부 이견이 있다(판정 밖 관찰 1).
- 나머지 기준은 HEAD 코드로 돈 e2e 기록(5 passed, skip 0)과 1회차 결과로 충족한다.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 1, 2(기록) |
| AC-02 | PASS | 1, 2(기록) |
| AC-03 | PASS (HEAD 10회 연속, p = 0.3 → n = 10) | 2 (1회차 FAIL) |
| AC-04 | PASS | 1, 2(단위) |
| AC-05 | PASS (headless Chrome) | 1 (`04_verifier_report.md`) |
| AC-06 | PASS | 1, 2(기록) |
| AC-07 | PASS | 1, 2(기록) |
| AC-08 | PASS | 1 (`04_verifier_report.md`) |
| AC-09 | 메인이 채움 | — |
| AC-10 | PASS (전체 묶음은 1회차, 바뀐 파일은 2회차) | 1, 2(부분) |
| AC-11 | PASS | 1, 2 |

## 항목별 결과

### [PASS] AC-03 데모 대본 1~7단계 (API 계약·상태 전이·데이터 효과)

- 기준: 스택이 뜬 상태에서 일반 사용자의 `python3 scripts/demo.py`가 1~7단계를 끝내고 0으로 끝난다. 단계마다 클라이언트에서 관찰한 근거. 끝나면 리소스·클라이언트가 남지 않는다. 3분 안. 1회차에서 10회 중 3회 6단계가 `exit 1`(p = 0.3)이라, `real-env-verify` §4에 따라 수정 뒤 n = ⌈3/0.3⌉ = 10회 연속 `exit 0`이 필요하다.

**수정 내용(HEAD `scripts/demo.py`).** 측정 방법은 1회차와 같다: 같은 fio 명령(1 MiB direct, iodepth 16, ramp 1 s, 6 s) 3회씩. 바뀐 것은 한도와 판정이다.
- 한도 `LIMIT, NEW_LIMIT = 20.0, 5.0`(`:44`), `HIGH = 1.01`(`:45`), `SLOW = 0.90`(`:46`), `FIO_BS_MIB, FIO_RUNTIME_S = 1, 6`(`:52`).
- `ceiling(limit) = limit × 1.01 + 1/6`(`:105-108`): 20 → 20.367, 5 → 5.217. `under_ceiling`(`:111-113`)은 회마다의 최댓값이 이 값 이하인지 본다. 넘으면 `StepFailed`(`:253-254`).
- 중앙값이 90% 아래면 실패가 아니라 안내 한 줄(`:256-258`). 1회차 실패의 원인이던 아래쪽 판정은 없어졌다.
- `follows_limit`(`:116`, 호출 `:339`): 내린 뒤 중앙값 ≤ 5 × 1.01 = 5.05 < 내리기 전 중앙값. I/O 여유는 없다.

**근거 1 — HEAD 코드로 데모 10회 연속 (판정 근거).** 두 기록을 합친다. 둘 다 일반 사용자 `mkimhome1`, README 명령으로 띄운 스택, `85428ec` 이후 코드(출력에 `85428ec`에서 생긴 문구 `no run went above its ceiling (101% of the limit plus one 1 MiB I/O in the 6 s window)`가 있고, `85428ec..4887031`의 `demo.py` 변경은 주석뿐)다. 그 사이에 HEAD 코드로 돈 데모 가운데 실패한 것은 없다.

- 1~2회: implementer의 compose e2e `fr13-compose-235101`, 15:51~15:55 PST(`4887031` 15:50:21 뒤), `5 passed in 253.06s`, skip 0, 실행기 `exit 0`. e2e 단언(`test_compose_stack_live.py:227-229`)이 두 한도 줄과 `the measured write throughput followed the limit: median `을 확인한다.
- 3~10회: 메인의 `/var/tmp/fr13-demo-repeat-head/`. `summary.txt` 머리는 `commit 488703174a195403c99f7914277524f834972552, user mkimhome1, start 2026-11-11T00:21:14Z, command: python3 scripts/demo.py (x8, one after another)`, 끝은 `end 2026-11-11T00:33:37Z: 8 of 8 exited 0`. 회별 로그 8개를 직접 읽었고 값이 `summary.txt`와 같다.
  - 커밋 SHA는 스크립트의 인자다. 스크립트가 계산한 값이 아니다.
  - `up.log`(16:21:13 PST, 소유자 `mkimhome1`)는 네 서비스 `Healthy`, `init` `Exited`로 끝난다. 이 파일에 rc 줄은 없다. `up rc 0`은 메인의 보고다.

| 회 | 기록 | 6단계 20 MiB/s (중앙값) | 6단계 5 MiB/s (중앙값) | 7단계 Prometheus 최고 | 결과 | 걸린 시간 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | e2e `demo` | 19.72, 19.39, 19.64 (98%) | 4.96, 4.9, 5.05 (99%) | 18.8 MiB/s | exit 0 | 87.16 s |
| 2 | e2e `demo-keep` | 19.65, 19.54, 19.47 (98%) | 4.97, 4.97, 4.96 (99%) | 18.8 MiB/s | exit 0 | 79.47 s |
| 3 | head run-1 | 19.33, 19.26, 16.89 (96%) | 4.92, 4.94, 4.96 (99%) | 18.3 MiB/s | exit 0 | 91.36 s |
| 4 | head run-2 | 18.94, 19.19, 19.28 (96%) | 4.96, 4.96, 4.92 (99%) | 18.8 MiB/s | exit 0 | 90.79 s |
| 5 | head run-3 | 19.25, 19.2, 9.3 (96%) | **5.15**, 4.95, 4.95 (99%) | 17.8 MiB/s | exit 0 | 103.04 s |
| 6 | head run-4 | 19.08, 14.39, 18.21 (91%) | 4.69, 4.92, 4.95 (98%) | 14.6 MiB/s | exit 0 | 89.94 s |
| 7 | head run-5 | 19.17, 19.2, **3.68** (96%) | **5.1**, 4.94, 4.95 (99%) | 16.2 MiB/s | exit 0 | 96.39 s |
| 8 | head run-6 | 19.21, 19.21, 10.05 (96%) | 4.95, 4.92, 4.96 (99%) | 17.5 MiB/s | exit 0 | 96.91 s |
| 9 | head run-7 | 16.79, 16.72, 18.27 (**84%**, 안내 줄) | 4.95, 4.97, 4.93 (99%) | 17.7 MiB/s | exit 0 | 95.95 s |
| 10 | head run-8 | 16.14, 5.93, 7.25 (**36%**, 안내 줄) | 4.97, 4.95, 4.94 (99%) | 10.9 MiB/s | exit 0 | 102.69 s |

- 10회 모두 로그에 `[1]`~`[7]` 줄과 `[done] steps 1-7 passed in … s`가 있다. `--keep`이 아닌 9회는 `[cleanup] removed vol-restored, vol-v41, vol-v3, demo-pool, demo-acct and the clients anf-demo-client-1, anf-demo-client-2`가 있다. 2회(`--keep`)는 e2e가 이어서 쓰고 지웠다(`down-v`: `left: {containers: [], volumes: [], clients: [], listening: []}`, `lvs []`). 8회 반복 뒤 `demo.py --clean`(nothing)과 `down -v`는 메인이 했고, 16:45 PST에 내가 읽은 상태도 비어 있다(환경 사전 점검 표).
- 10회 모두 3분 안이다(79.47~103.04 s). 7단계의 Prometheus 최고 쓰기율은 모두 20 MiB/s 아래이고(10.9~18.8), 한도 계열은 5 MiB/s다.
- 같은 판정 함수의 판단과 출력 줄도 맞는다. 9·10회는 중앙값이 90% 아래라 `[6]   the storage wrote slower than the limit this time (median below 90%). Not a failure: …`가 붙었고, `exit 0`이다.

**판정: PASS.** 1회차 p = 0.3의 n = 10을 HEAD 실측 10회 연속 성공으로 충족한다. 3의 규칙으로 말할 수 있는 것은 "이 환경에서 데모 실패율이 95% 신뢰로 약 30% 아래"까지다. 그 이상의 신뢰는 이 횟수로 말할 수 없다.

**두 결함 각각.**
- 1회차 결함(스토리지가 한도보다 느리게 쓸 때 아래쪽 판정이 실패시킴): 같은 모양이 수정 뒤 여러 번 실제로 나왔다. HEAD 9회(84%)와 10회(36%), `8c02910` 반복 10회차(68%)다. 모두 안내 줄만 붙고 `exit 0`이었다.
- 07회 결함(`8c02910` 반복 07회, 5 MiB/s에서 5.12 = 102.4%가 101% 천장에 걸려 `exit 1`): `85428ec`가 회마다 I/O 하나를 더 허용했다.
  - 그 촉발 조건(5 MiB/s의 한 회가 5.05 초과)이 HEAD 실측 10회 가운데 5회의 5.15(103%)와 7회의 5.1(102%)로 두 번 나왔다. 두 번 다 새 천장 5.217 안이라 통과했다. 재계산이 아니라 실행으로 수정이 확인됐다.
  - 수정 뒤 5 MiB/s 측정은 모두 60회다(`8c02910` 반복 30 + e2e 6 + HEAD 반복 24). 최댓값은 5.15로 천장 아래다.
  - 이 결함만 따로 07회의 p(0.1)로 n = 30을 요구하면 횟수는 미달이다(상한 3/10). 나는 1회차 판정의 대상인 결함의 p로 판정했다.
- 보조 근거 — `8c02910`의 10회 연속(implementer, `fr13-demo-repeat`): 9회 `exit 0`, 07회만 위 결함으로 `exit 1`이었다. 회별 값과 HEAD 판정 재계산은 아래 표에 있다.

| 회 | 6단계 20 MiB/s | 6단계 5 MiB/s | 기록된 결과 | 걸린 시간 | HEAD 판정으로 재계산 |
| --- | --- | --- | --- | --- | --- |
| 01 | 19.51, 19.53, 19.52 | 4.96, 4.97, 4.97 | exit 0 | 81.92 s | 통과 |
| 02 | 19.48, 19.43, 19.49 | 4.97, 4.96, 4.97 | exit 0 | 93.79 s | 통과 |
| 03 | 19.25, 19.52, 19.49 | 4.97, 4.95, 4.97 | exit 0 | 83.03 s | 통과 |
| 04 | 19.48, 19.56, 19.01 | 4.97, 4.96, 4.96 | exit 0 | 82.99 s | 통과 |
| 05 | 19.42, 19.42, 19.42 | 4.97, 4.97, 4.96 | exit 0 | 82.96 s | 통과 |
| 06 | 19.31, 19.4, 19.41 | 4.96, 4.96, 4.96 | exit 0 | 87.37 s | 통과 |
| 07 | 19.37, 19.31, 19.39 | 4.96, 4.76, **5.12** | **exit 1** `a run went above 101% of the limit` | 87.86 s | 통과(5.12 ≤ 5.217) |
| 08 | 19.26, 19.43, 19.45 | 4.96, 4.96, 4.96 | exit 0 | 83.57 s | 통과 |
| 09 | 19.42, 19.4, 19.53 | 4.95, 4.96, 4.95 | exit 0 | 83.03 s | 통과 |
| 10 | **13.67, 7.22, 17 (68%)** | 4.96, 4.97, 4.96 | exit 0, 안내 줄 | 87.36 s | 통과 |

- 재계산(내가 직접): `.venv-win` Python으로 HEAD의 `scripts/demo.py`와 `git show 8c02910:scripts/demo.py`를 함께 불러 같은 값에 적용했다. 출력은 `FIO same: True | limits head 20.0 5.0 1.01 old 20.0 5.0 1.01`, `ceilings head: 20.367 5.217`이었고, 10회 모두 `head PASS`, 07회만 `old FAIL`이었다. implementer의 `rejudge.txt`(`10 of 10 runs pass the new step 6 judgement (60 values)`)와 같다.

**새 판정이 진짜 초과를 숨기는가(코드 읽기와 측정값).**
- 잡는 것:
  - 제한기가 없음: 5 MiB/s 단계에서 천장 5.217을 넘고 따라 바뀜도 깨진다. 20 MiB/s 단계도 저장소가 20.367보다 빨리 쓰면 잡힌다.
  - PATCH가 적용되지 않음: 내린 뒤 중앙값이 약 19.5라 `follows_limit`와 5 MiB/s 천장 둘 다 걸린다.
  - 일정한 초과: 20 MiB/s에서는 약 1.8% 넘으면, 5 MiB/s에서는 중앙값이 1% 넘으면 걸린다. 5 MiB/s의 한 회는 104.3%(5.217)까지 허용된다.
- I/O 하나의 여유가 맞는 이유: fio는 창 안에서 끝난 1 MiB I/O만 센다. 완료가 고르게 오면 6 s 창에 N개 또는 N+1개가 들어간다. 5 MiB/s에서 31/6 = 5.167이다. 관찰된 5.12, 5.1, 5.15는 모두 31개 언저리다. 설계의 설명("앞 회에서 밀린 완료")과 기제는 조금 다르지만 같은 상한이 나온다. 여유는 완료 하나뿐이라 두 개 이상(5.33 이상)은 걸린다.
- 잡지 않는 것(설계상 맞바꿈): 한도 아래쪽의 오차. 예를 들어 tc가 한도보다 낮게 걸리거나 한도 값이 아래로 틀려도 데모는 안내 줄만 낸다. 정확도(90~101%)는 FR-08 데이터 시험이 본다(`docs/testing.md` §9 행).
- 거짓 실패가 남은 곳(알려진 한계, 판정 밖 관찰 1): `follows_limit`.
  - 내린 뒤 쪽: I/O 여유가 없어 3회 가운데 2회 이상이 5.05를 넘으면 실패한다. 수정 뒤 5 MiB/s 측정 60회 가운데 5.05 초과는 3회(5.12, 5.15, 5.1)이고, 한 데모 안에서 두 번 나온 적은 없다.
  - 내리기 전 쪽: 중앙값이 5.05(20 MiB/s의 25%) 이하이면 실패한다. HEAD 10회차의 중앙값이 7.25(36%)였고, 한 회 값으로는 HEAD 7회차의 3.68(18%)이 있었다.

### [PASS] AC-01 WSL 재시작 직후 일반 사용자로 명령 하나

- 기준: 1회차와 같다. 이번 변경(`create_host_path: true`)이 기존 경로에서 같은 결과를 내는지와 새 기기에서 만들기가 거절되지 않는지를 본다.
- HEAD의 compose 파일로 돈 기록:
  - `8c02910` 반복의 `up.log`(15:32, `8c02910` 15:31:22 뒤, `deploy/`는 `8c02910`과 HEAD가 같음): `user=mkimhome1 rc=0 elapsed_s=10.41`, 네 서비스 `Healthy`.
  - e2e `up` 태그(15:51): `user mkimhome1, rc 0, 9.26 s`. `services`는 `anf-api running healthy`, `dashboard running healthy`, `init exited 0`, `prometheus running healthy`, `storage-agent running healthy`. `ports`는 네 포트 모두 `127.0.0.1:<port>`만.
  - HEAD 8회 반복의 `up.log`(16:21): 네 서비스 `Healthy`, `init` `Exited`. rc 줄은 없다.
- 읽기 전용 `docker compose -f deploy/compose.yaml config`: agent의 두 바인드가 `create_host_path: true`로 풀린다(`/var/lib/anf-clone`은 `recursive: disabled`, `ns`는 `propagation: rshared`). 짧은 문법 바인드에도 compose가 `create_host_path: true`를 붙이는 것은 평소대로다.
- 새 기기 모양 시험(implementer, `…\scratchpad\fr13\fresh\fresh-out.txt`). `compose-new.yaml`은 HEAD의 compose 파일과, `compose-head.yaml`은 `7cc13c1`의 것과 같다. `toy-*.yaml`은 바인드 원본만 `/var/tmp/fr13-fresh`로 바꿨다. `override.yaml`은 init의 NS 경로를 바꾸고 agent를 탐침으로 바꿨다.
  - control(옛 compose, 디렉터리 없음): `create rc=1: … bind source path does not exist: /var/tmp/fr13-fresh`.
  - fresh(새 compose, 디렉터리 없음): `create rc=0`, `up rc=0`, `after-up: /var/tmp/fr13-fresh exists; …/ns exists; ns mount: shared`, `init: exit=0 last=init: /var/tmp/fr13-fresh/ns shared`. agent 탐침은 `inside: /var/lib/anf-clone/ns shared probe-mounted`이고, 호스트가 `ns/probe/seen`을 본다.
  - empty-ns(ns만 빈 디렉터리로 있음): fresh와 같다. 끝난 뒤 `/var/tmp/fr13-fresh` 없음.
- 1회차의 재시작 직후 3회(10.44 s, 8.82 s, 10.2 s)는 `create_host_path` 이전 파일로 돌았다. 경로가 이미 있으면 `create_host_path`는 아무것도 하지 않으므로 그 결과는 유효하다고 본다. 재시작 직후의 실행을 HEAD 파일로 다시 하지는 않았다.
- 한계: 실제 `/var/lib/anf-clone`을 지운 새 기기의 전체 흐름(agent 서버, aggregate 생성)은 돌리지 않았다. 1회차 판정 밖 관찰 1은 "모양 시험으로 수정 확인"까지다.

### [PASS] AC-02 다시 실행과 down → up

- e2e(`fr13-compose-235101`, HEAD) `test_rerun_and_down_up_keep_volumes_and_client_io` PASSED:
  - `demo-keep` 뒤 `before`: 볼륨 셋 `Succeeded`, IP `.131/.129/.130`, 한도 20/20/5, `snapshots ['snap1']`, 인스턴스 셋(ID `816b8d4a…`, `ed205fb9…`, `ccb8f4c6…`).
  - `rerun`: `rc 0, 9.57 s`. 다시 만들어진 것은 `anf-api`, `dashboard`, `init`, `storage-agent`(결정 13대로).
  - `down`: `rc 0, 0.9 s`, 네 포트 닫힘. 인스턴스 셋은 같은 ID·`StartedAt`으로 running.
  - `up-again`: `rc 0, 8.87 s`. 보기가 `before`와 같고 인스턴스 ID·`StartedAt`도 같다. 쓰기 `163회, 오류 0, max_gap 0.29 s, down 창 11.74 s 안 55회`.
- 1회차 손 확인(`04_verifier_report.md` AC-02)도 그대로 유효하다. 바뀐 것은 agent 바인드 옵션뿐이고, 경로가 있으면 아무것도 하지 않는다.

### [PASS] AC-04 데모의 실패 처리

- Windows `.venv-win`: `python -m pytest backend/tests/unit/test_demo.py backend/tests/unit/test_compose.py -q` → `35 passed in 0.11s`.
  - 종료 코드 테스트 넷(스택 없음 2, 클라이언트 이미지 없음 2, 1단계 실패 뒤 치우고 1, `--keep`)은 그대로다.
  - 새 6단계 테스트 셋: 느린 측정은 안내만, 천장을 넘으면 PATCH 전에 `StepFailed`, 따라 바뀌지 않으면 실패.
  - 경계 표 `test_under_ceiling_allows_101_percent_plus_one_io_per_run`: 20.36 통과, 20.37 실패, 5.21 통과, 5.22 실패, 5.3 실패.
- 실환경 실패 사례: `8c02910` 반복 07회. `exit 1`이었고, 단계 번호와 회마다 값이 출력되고, 치움 줄이 있다(`--keep` 아님). 이 문구는 `8c02910`의 것이다. HEAD에서는 `a run went above the ceiling of …`(`:254`)로 바뀌었고, 이 문구는 단위 테스트로만 확인했다.

### [PASS] AC-05 Windows 브라우저로 대시보드 — 1회차 결과

- `frontend/`와 대시보드 이미지 정의는 `7cc13c1..HEAD`에서 바뀌지 않았다(`git diff --stat`에 없음). 1회차 headless Chrome 결과를 옮긴다. 데모가 만드는 볼륨 한도는 10에서 20 MiB/s로 바뀌었지만, 화면은 API 값을 그대로 보인다.

### [PASS] AC-06 agent를 죽였다 살려도 볼륨·스냅샷·한도 유지, 되돌리기·삭제 성공

- e2e(HEAD) `test_agent_kill_during_writes_keeps_volumes_and_revert_and_delete_work` PASSED:
  - `after-kill`: 다시 띄움 `rc 0, 9.84 s`. 쓰기는 v3 `274회 오류 0, 14.84 s 창 안 226회`, v41 `87회 오류 0, 창 안 69회`. 인스턴스 netns의 tc `rate_bits`는 vol-v3·vol-restored 175,420,000(20 MiB/s ÷ 0.9564), vol-v41 43,855,000(5 MiB/s)이고, `ifb0`와 양방향 필터가 각 1개다.
  - `revert-after-restart`: `Reverting ×3 → Succeeded`. 클라이언트 `ls`는 `['hello.txt']`, 내용은 `'hello from the ANF clone demo'`.
  - `delete-after-restart`: `rc 0, 5.62 s`.
  - `down-v`: `left: {containers: [], volumes: [], clients: [], listening: []}`, `instances {}`, `lvs []`.
- 바뀐 agent 바인드(`create_host_path`)로 돈 실행이다.

### [PASS] AC-07 데모 동안 WSL 메모리 (NFR-06)

- 한도가 20 MiB/s로 올라 쓰기 양이 늘었으므로 기록으로 다시 봤다. e2e(HEAD) `memory` 태그: 17 표본, 최대 `used 1018 MiB / total 7778`, `available 6760`, 한도 7,168 MiB. 그때 agent 96.36 MiB, anf-api 59.02 MiB. 메인의 8회 반복은 메모리를 기록하지 않았다.

### [PASS] AC-08 실행기와 스택 — 1회차 결과

- `scripts/run-dataplane-tests.sh`는 바뀌지 않았다. 이번 e2e 기록에도 실행기가 남은 것을 보고하지 않았다(`summary.txt`: `collected 5, skipped 0`, `exit 0`).

### [PASS] AC-10 회귀 묶음, lint, 프런트엔드

- 전체 `not dataplane` 묶음은 리더 지시로 다시 돌리지 않았다. 1회차에 같은 제품 코드(해시 `7c38d8c7…`)로 `1042 passed`, skip 0이었다.
- `7cc13c1..HEAD`의 변경 가운데 pytest가 읽는 것은 `scripts/demo.py`, `deploy/compose.yaml`, `docs/testing.md`다. `backend/tests`에서 grep하면 이것들을 읽는 테스트 파일은 `test_demo.py`, `test_compose.py`, `test_testing_doc.py`, 그리고 dataplane e2e 하나다.
  - 앞의 셋을 돌렸다: `35 passed`, `2 passed`.
  - e2e는 위의 5 passed다.
- collect-only `-m "not dataplane"`: Windows와 WSL 모두 `1051/1175 tests collected (124 deselected)`. 1회차 1,042보다 9개 많다. `test_demo.py`·`test_compose.py`가 26개에서 35개가 됐다.
- ruff: `uvx --offline ruff@0.14.0 check backend .claude/hooks scripts/demo.py` → `All checks passed!`(CI 범위에 `scripts/demo.py`를 더함).
- 프런트엔드: `frontend/`가 바뀌지 않아 1회차 결과(typecheck, 48 tests, build)를 옮긴다.
- 한계: 1,051개 전체를 HEAD로 한 번에 돌린 기록은 내게 없다. 나머지 1,014개가 읽는 파일은 1회차와 같다.

### [PASS] AC-11 README의 명령과 주소

- `git diff 7cc13c1..HEAD -- README.md`: 데모 문단 하나만 바뀌었다. 시작·내리기 명령, 주소 표, `--keep`·`--clean`, 테스트 전 내리기는 1회차와 같다.
- 새 문장과 코드·출력의 대조:
  - "the throughput step fails if a run goes above 101% of its limit plus one 1 MiB I/O in the 6 s window": `ceiling()`·`CEILING_RULE`(`:56`, `:105`)과 맞고, 출력 문구도 같다.
  - "or if the measured throughput does not drop with the limit": `follows_limit`(`:339-341`)과 맞다.
  - "A run slower than the limit only gets a note": `SLOW`(`:256`)와 맞다. HEAD 9·10회와 `8c02910` 반복 10회차에서 실제로 그랬다.
  - "about a minute and a half": HEAD 10회는 79.47~103.04 s였다(1.3~1.7분). 1회차의 81.9~88.5 s보다 길어졌지만 "약 1분 30초"의 범위로 본다.
  - 종료 코드 0, 1, 2: 0과 1은 실측했다(HEAD 10회, `8c02910` 07회). 2는 1회차 실측과 단위 테스트로 확인했다.

## 판정 밖 관찰

1. **`follows_limit`의 내리기 전 쪽 여유가 얇다. 메인의 "코드는 그대로, 알려진 한계"에 일부 이견이 있다.**
   - 관찰:
     - HEAD 10회차의 20 MiB/s 측정은 16.14, 5.93, 7.25로 중앙값 7.25(36%)였다. 문턱 5.05(20 MiB/s의 25%)와 2.2 MiB/s 차이다. 세 값 가운데 둘이 5.05 아래였으면 이 데모는 한도가 제대로 지켜졌는데도 `the measured write throughput did not follow the limit change`로 `exit 1`이었다.
     - HEAD 7회차에는 한 회가 3.68(18%)이었다. 중앙값 판정이라 통과했다.
     - 느린 회는 한 데모 안에 몰려 나온다(HEAD 10회차, `8c02910` 반복 10회차 13.67·7.22·17, 1회차 실패 셋). 그래서 회마다 독립이라고 보고 확률을 곱하면 위험을 작게 잡는다.
     - 수정 뒤 20회(`8c02910` 반복 10 + e2e 2 + HEAD 8) 가운데 중앙값이 90% 아래인 회는 3회(68%, 84%, 36%)다.
   - 1회차 결함과 같은 종류다. 스토리지가 몇 초 느리게 쓴 것을 데모가 실패로 만든다. 수정이 그 길을 아래쪽 판정에서 없애고 `follows_limit`의 문턱 하나로 좁혔을 뿐이다. 이 e2e는 CI `data-plane` `rest` 조각에서 돈다. 드물게 나오더라도 거짓 실패 하나가 PR을 막는다.
   - 코드 주석과 단위 테스트의 전제가 맞지 않게 됐다:
     - `scripts/demo.py:41-43`의 주석("이 환경에서 잰 쓰기 한 회의 가장 낮은 비율은 36%였고, 20의 36%도 5의 101%보다 크다")은 HEAD 7회차의 3.68(18%)로 틀렸다.
     - `backend/tests/unit/test_demo.py:58-62`의 `test_the_limit_pair_leaves_room_for_the_slowest_write_seen`(`0.36 * LIMIT > NEW_LIMIT * HIGH`)도 같은 전제다. 이 테스트가 지키는 안전 논리는 지금 "한 회"가 아니라 "중앙값"에 대해서만 성립한다.
   - 제안(택일, 리더 판단):
     - (a) 코드는 그대로 두고 알려진 한계로 남긴다. 그 경우에도 위 주석과 테스트 이름·주석은 "중앙값 최저 36%, 한 회 최저 18%"로 고쳐 사실과 맞추는 것을 권한다.
     - (b) 내리기 전 쪽을 `max(before) > ceiling(NEW_LIMIT)`(5.217)로 바꾼다. 첫 한도가 5 근처에 걸려 있는 경우는 여전히 잡는다(그때 최댓값은 천장 논리로 5.217을 넘을 수 없다). 거짓 실패가 나려면 20 MiB/s 3회가 모두 5.217 이하여야 한다. 수정 뒤 20회에서 `max(before)`의 최저는 16.14다. 내린 뒤 쪽(중앙값 ≤ 5.05)과 5 MiB/s 천장은 그대로라 "PATCH가 적용되지 않음"도 그대로 잡는다.
     - (c) 내리기 전 중앙값이 문턱 아래일 때만 3회를 한 번 더 재고 두 묶음을 모두 출력한다.
   - 나는 (b)가 진짜 초과를 숨기지 않으면서 이 한계를 없애는 가장 작은 변경이라고 본다. 다만 이것은 AC-03 판정(10회 연속 성공)을 바꾸지 않는다.
2. **`docs/testing.md:18`의 개수가 실제와 다르다(커밋된 판 기준).** 문서는 `python -m pytest`의 대상이 1,046개라고 한다. collect-only 결과는 Windows와 WSL 모두 1,051개다. `test_testing_doc.py`는 개수를 검사하지 않아 걸리지 않는다. 이 보고서를 쓰는 동안 다른 세션이 이 파일을 고치기 시작했다(` M`). 그 내용은 보지 않았다.
3. 1회차 판정 밖 관찰 1(새 기기에서 바인드 원본 없음)은 `8c02910`로 고쳐졌다. 모양 시험으로 확인했고(AC-01), 실제 새 기기의 전체 흐름은 확인하지 않았다.
4. 개념 문서 `docs/concepts/containers.md`의 6단계 설명은 커밋된 판(`7cc13c1`)에서 지금 코드와 다르다(`:243`의 10 MiB/s, `:255`의 `throughput_ok` 90~101%). 검증 중에 다른 세션이 이 파일을 고치고 있었으므로(` M`) 판정하지 않았다. 고칠 때 위 1의 두 최저값(중앙값 36%, 한 회 18%)도 반영하면 좋다.
5. 데모 시간이 늘었다. HEAD 8회는 89.94~103.04 s로, `8c02910` 반복의 81.92~93.79 s와 1회차의 81.9~88.5 s보다 길다. 6단계의 PATCH가 `Succeeded`까지 1.5~3.6 s 걸렸고, 느린 회가 많았던 것과 함께 나타났다. 3분 기준과는 여유가 크다.
6. 이번 회차의 실측 근거는 모두 implementer와 메인의 실행이다. 리더 지시로 내가 다시 돌린 것은 없다. 실행 기록은 코드 해시를 남기지 않는다. HEAD 코드라는 것은 실행 시각(커밋 뒤), `85428ec`에서 생긴 출력 문구, 그리고 메인 반복의 커밋 인자로 보였다.

## 정리

- 실행한 것은 읽기 전용 점검뿐이다: git, `docker compose config`, 기록 파일 읽기와 복사, 판정 함수 재계산, 단위 테스트 세 파일, collect-only, ruff, 끝난 상태 읽기. 스택·데모·클라이언트·LV·인스턴스는 만들지 않았다. 끝난 상태: 컨테이너 0, 이름 있는 볼륨 0, 리스너 0, LV `aggr0`뿐, `ns`·`exports` 비어 있음.
- implementer와 메인의 WSL 기록 폴더(`/var/tmp/anf-clone-tests/fr13-demo-repeat`, `fr13-compose-235101*`, `/var/tmp/fr13-demo-repeat-head`)는 원본 그대로 두었다. 사본은 위 보관 위치에 있다.
- 저장소: 이 보고서 말고 바꾼 파일 없음. 커밋하지 않았다. `docs/ai-readiness-*`와 다른 세션이 고치는 `docs/concepts/containers.md`·`docs/testing.md`는 건드리지 않았다.
