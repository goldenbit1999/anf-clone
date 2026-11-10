# test-automation (FR-10) 검증 보고서 — 2회차

- 진행 상태: 완료
- 검증일: 2026-11-10
- 검증 대상 코드: HEAD `ace0d39`. `git diff --stat db3468c ace0d39 -- scripts backend pyproject.toml .github`가 비어 있다(1회차 대상 `6993c17`·`db3468c`와 같은 코드). 제품 코드 내용 해시 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`. 미커밋 변경: `docs/testing.md`(§3 소요 시간 표), `_workspace/test-automation/00_progress.md`, 이 보고서. 미추적: `.claude/worktrees/`(아래 관찰), `docs/ai-readiness-*`
- 이번 회차 범위: 재검증 AC-01(실행 D의 결과 파일로 판정, 다시 돌리지 않음), AC-07(PR #19 Actions run). 나머지는 1회차 결과를 옮긴다. 1회차 뒤 코드가 바뀌지 않았으므로 1회차 PASS를 다시 돌리지 않았다.

## 결과 요약
PASS 8 / FAIL 0 / UNVERIFIED 0

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | PASS | 2회차 (1회차 UNVERIFIED) |
| AC-02 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-03 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-04 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-05 | PASS | 1회차 (`04_verifier_report.md`). 2회차에 실행 D의 전체 실행 뒤 결과도 확인 |
| AC-06 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-07 | PASS | 2회차 (1회차 UNVERIFIED) |
| AC-08 | PASS | 1회차 (`04_verifier_report.md`) |

## 항목별 결과

### [PASS] AC-01 명령 하나로 전체, 종료 코드 0, skip 0
- 기준: 문서의 명령 하나를 root로 실행하면 데이터 플레인 묶음 전체가 돌고 종료 코드 0. 요약의 수집 수 = `pytest --collect-only -m dataplane`, 실패·오류·skip 0, 3시간 안.
- 근거: 실행 D `/var/tmp/anf-clone-tests/20261110T080605Z/`, 콘솔 `/var/tmp/anf-clone-tests/console-full2.log`.
- 코드 대조: 실행 D는 00:06:05 PST(08:06 UTC, `baseline.txt`)에 시작해 01:34:07에 끝났다(`summary.txt`). 그 사이와 그 뒤의 커밋 `961e316`(00:07), `ace0d39`(00:26)는 `CLAUDE.md`, `docs/concepts/test-automation.md`, `docs/testing.md`, `_workspace/`만 바꿨다. `scripts`·`backend`·`pyproject.toml`·`.github`에서 가장 새로 고친 파일은 `backend/tests/unit/test_testing_doc.py`(전날 20:53:14)다. 13개 로그 모두 `rootdir: /mnt/c/Users/mkimh/Projects/ANF-clone`.
- 인자 없는 실행: `collect.log` `113/176 tests collected (63 deselected)`(기본 경로 `backend/tests/integration`·`e2e`일 때의 수), 콘솔 `collected 113 dataplane tests in 13 files`. 지금 코드의 `python -m pytest --collect-only -q -m dataplane`도 `113/1101 tests collected (988 deselected)`.
- 한 실행의 결과:
  - 콘솔 첫 줄 `VG anf: not attached (WSL restarted?); attaching …`, 13개 파일의 `pytest exit` 줄이 13개이고 `files.tsv`가 모두 0.
  - `summary.txt`: `total 113 113 0 0 0`, `collected 113, skipped 0`, `time: 5279 s for 13 files (monotonic clock)`, `left behind` 줄 없음, `exit 0`. 콘솔 마지막 줄 `rc=0`.
  - 게이트와 별개로 XML 13개의 `testcase`를 직접 셌다. 113개 모두 failure·error·skipped 자식이 없고, 이름 집합이 `collect.log`의 113개와 같다(`same set True`).
- 시간: 5,279 s(약 88분). 3시간 제한 안이다. 가장 긴 파일은 처리량 데이터 2,251 s.

### [PASS] AC-05 보충: 전체 실행 뒤 남은 것
- 실행 D의 `baseline.txt`는 LV·컨테이너 모두 비어 있었고, `summary.txt`에 `left behind` 줄이 없다(빈 기준선에서 한 번에 끝까지 간 실행이라 1회차의 기준선 예외도 걸리지 않는다).
- 지금 상태(WSL root): LV `aggr0`뿐, 컨테이너 0, 8080·8090 리스너 0, `/var/lib/anf-clone/ns`·`exports` 비어 있음.

### [PASS] AC-07 CI와 같은 판정
- 실행한 명령: `gh run view 42782709293 --json event,headSha,headBranch,status,conclusion,jobs`, `gh run view 42782709293 --log`.
- 출력(핵심): `event: pull_request`, `headBranch: feature/test-automation`, `headSha: ace0d39f4445…`, `conclusion: success`. `backend` 작업 success(Lint, Test, Fail on skipped tests, Hook tests 모두 success), `frontend` 작업 success(Install, Type check, Test, Build).
- `Test` 단계: `collected 1101 items / 113 deselected / 988 selected`, `988 passed, 113 deselected in 143.39s`.
- `Fail on skipped tests` 단계: `python backend/tests/junit_gate.py pytest-results.xml`을 실행했고 `pytest-results 988 988 0 0 0 143.4`, `total 988 988 0 0 0`, `collected 988, skipped 0`을 출력했다. 1회차의 WSL 실행(AC-08)과 같은 스크립트·같은 수다.

## 판정 밖 관찰
1. **실행 D 도중 저장소 안에 다른 워크트리가 생겼다.** `.claude/worktrees/agent-aee96ed1b59426045`(브랜치 `spike/s3-runner`, `1dfd386`, locked)가 00:31 PST에 만들어졌다. 실행기의 수집 경로(`backend/tests/integration`·`e2e`)와 기본 `testpaths`(`backend/tests`)에는 들어가지 않아 실행 D의 대상은 변하지 않았다(수집 113, 이름 집합 같음). 그 에이전트가 WSL 데이터 플레인을 같이 썼는지는 보지 않았다. 실행 D의 기준선은 비었고 남은 것도 없어, 겹친 흔적은 보이지 않는다. CLAUDE.md는 세션 워크트리를 형제 폴더(`../ANF-clone-<slug>`)에 두라고 한다.
2. 미커밋 `docs/testing.md`가 1회차 관찰 1(§3 소요 시간이 비어 있음)을 실행 D의 실측으로 채웠다. 표의 파일별 초는 XML `time`(pytest 세션 시간)을 반올림한 값이고, 머리말의 5,279초는 실행기의 단조 시계 값이라 `files.tsv`와 1 s씩 다른 행이 있다(예: `test_restore_new_volume_contract_live` 문서 376, XML 375.9, `files.tsv` 377). 뜻은 같다.
