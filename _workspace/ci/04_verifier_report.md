# ci 검증 보고서 — 1회차

- 검증일: 2026-11-07 (로컬 PST). Actions 실행 시각은 UTC 2026-11-08 04:04~04:12
- 검증 대상 코드:
  - 커밋 `3fd65119b7c05edda6e969adaf2f1ea43b0444f0` (브랜치 `feature/ci`). 로컬 `git rev-parse HEAD`와 원격 `refs/heads/feature/ci`가 같은 값이다. 성공 run의 checkout 로그도 이 SHA를 가져왔다(`git log -1 --format=%H` → `3fd6511…`).
  - 제품 코드 내용 해시는 `f2b70558c8189ab44ba210081d30ed52978c8e56f529ddba84edeb12656bc955`다. 검증을 시작할 때와 끝낸 뒤에 커밋 명령과 작업 트리 명령으로 각각 계산했고 값이 모두 같았다 (AC-07 항목).
  - 미커밋 변경: 제품 코드에는 없다. 주 작업 디렉터리에 `_workspace/ci/00_progress.md`(M)와 untracked `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`이 있다. 모두 검증 시작 전부터 있었고 제품 코드가 아니다. CI는 커밋을 checkout하므로 판정에 영향이 없다.
- 이번 회차 범위: 전체 (AC-01~AC-07).
- 검증 방법:
  - 판정 근거는 GitHub Actions의 실제 실행 기록만이다. 로컬 실행은 근거로 쓰지 않았다.
  - 조회 도구: `gh run list/view`, `gh api repos/goldenbit1999/anf-clone/actions/runs/{id}`, `.../runs/{id}/jobs`, `.../actions/jobs/{job_id}/logs`(작업 전체 로그), `.../check-runs/{job_id}/annotations`.
  - AC-06은 scratchpad 안 별도 worktree에서 임시 브랜치 세 개를 `origin/feature/ci`(=`3fd6511`)에서 만들고, 각각 한 가지만 바꿔 push했다. 주 작업 디렉터리의 브랜치와 파일은 건드리지 않았다. `main`·`feature/ci`에는 push하지 않았고 PR도 만들지 않았다.

## 환경 사전 점검

이 기능의 실환경은 GitHub Actions라서 gh 인증·권한과 저장소 접근만 점검했다. WSL, Docker, NFS는 리더 지시대로 점검하지 않았다.

| 항목 | 결과 |
| --- | --- |
| gh CLI | 2.89.0. `gh auth status`: `goldenbit1999`로 로그인, 토큰 범위 `gist, read:org, repo, workflow`. `workflow` 범위는 AC-06(c)에서 워크플로 파일을 바꿔 push하는 데 필요하다 |
| 저장소 접근 | `gh repo view`: `anf-clone`, `PRIVATE`, 기본 브랜치 `main`, `viewerPermission: ADMIN` |
| 원격 ref | `feature/ci` = `3fd6511…`, `main` = `41f863d…`. 시작과 끝에 같다 |
| 워크플로 등록 | `actions/workflows`: `ci` (`.github/workflows/ci.yml`), `state: active`, id 410869349 |
| 관찰: API 반영 지연 | 작업이 끝난 직후 jobs API의 `steps`는 빈 배열이거나 단계 결론이 `null`이었고, 몇 분 뒤에 채워졌다(성공 run은 세 번째 조회에서 모든 단계가 `success`). 이 동안 `gh run view --log`는 단계 이름 대신 `UNKNOWN STEP`을 찍거나 로그 일부만 돌려줬다. 그래서 로그 근거는 `gh api .../actions/jobs/{id}/logs`(작업 전체 로그)로 다시 받았다. GitHub API 쪽 지연이며 기능 결함이 아니다 |

## 결과 요약

PASS 7 / FAIL 0 / UNVERIFIED 1

- 항목 수는 AC-01을 push(AC-01a)와 pull_request(AC-01b)로 나눈 8개다. AC-06의 세 경우(a, b, c)는 한 항목으로 세었고 셋 다 기대대로였다.
- UNVERIFIED 1은 AC-01b다. main 대상 PR이 없어서 `pull_request` 이벤트 실행이 아직 한 번도 없다. PR을 열 때 확인한다.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 트리거 | push: PASS / pull_request: UNVERIFIED (PR을 열 때 확인) | 1회차 (이 보고서) |
| AC-02 환경 | PASS | 1회차 |
| AC-03 린트 | PASS | 1회차 |
| AC-04 테스트 | PASS | 1회차 |
| AC-05 훅 테스트 | PASS | 1회차 |
| AC-06 실패 감지 | PASS (a, b, c 모두) | 1회차 |
| AC-07 제품 코드 불변 | PASS | 1회차 |

## 항목별 결과

### [PASS] AC-01a push 트리거 (API 계약: 워크플로 트리거)
- 기준: `feature/ci`에 push하면 워크플로 `ci`가 자동으로 돈다.
- 실행한 명령: `gh api repos/goldenbit1999/anf-clone/actions/runs/42445326221 --jq '{event,head_branch,head_sha,path,name,run_attempt,conclusion,triggering_actor:.triggering_actor.login}'`
- 출력(핵심 부분):
  - `"event":"push","head_branch":"feature/ci","head_sha":"3fd65119b7c05edda6e969adaf2f1ea43b0444f0","path":".github/workflows/ci.yml","name":"ci","run_attempt":1,"conclusion":"success","triggering_actor":"goldenbit1999"`
  - run URL: https://github.com/goldenbit1999/anf-clone/actions/runs/42445326221 (생성 04:04:53Z, 수동 재실행이 아닌 1차 시도)
- 추가 근거: AC-06의 임시 브랜치 세 개(`ci-verify/*`)도 push만으로 각각 run이 생겼다(`event: push`). 그래서 `feature/ci`가 아닌 브랜치의 push도 트리거한다(설계 결정 7 "모든 브랜치의 push").
- 워크플로 정의(`.github/workflows/ci.yml:5-8`): `on.push`(필터 없음), `on.pull_request.branches: [main]`. 성공 run의 로그에 `GITHUB_TOKEN Permissions: Contents: read, Metadata: read`가 찍혀 결정 7의 `permissions: contents: read`도 적용됐다.

### [UNVERIFIED] AC-01b pull_request 트리거 (API 계약: 워크플로 트리거)
- 기준: main 대상 PR을 열면 `pull_request` 이벤트로도 돈다.
- 실행한 명령: `gh run list -R goldenbit1999/anf-clone --event pull_request --json databaseId --jq length` → `0`. `gh pr list --state open` → 0개. PR #1~#5는 모두 이 워크플로가 생기기 전에 merge됐다.
- 이유: 리더 지시로 PR을 만들지 않았다. 정의(`on.pull_request.branches: [main]`)는 위에서 확인했지만, 정의를 읽은 것은 실행 근거가 아니다. **PR을 열 때 확인**: PR의 Checks에 `ci / backend`가 `pull_request` 이벤트로 뜨는지, `gh run list --event pull_request`에 run이 생기는지 본다.

### [PASS] AC-02 실행 환경 (API 계약: 실행 환경)
- 기준: 실행 로그에 러너 `ubuntu-24.04`, Python 3.12.x, `~/.venvs/anf-clone`에 `pip install -e ".[dev]"`로 설치한 기록이 있다.
- 실행한 명령: `gh run view 42445326221 --log`, `gh api .../actions/runs/42445326221/jobs`
- 출력(핵심 부분, run 42445326221):
  - jobs API: `"labels":["ubuntu-24.04"]`, `runner_group_name: GitHub Actions`
  - 로그 `Operating System`: `Ubuntu 24.04.5 LTS`. `Runner Image`: `Image: ubuntu-24.04`, `Version: 20261101.360.1`
  - setup-python: `Successfully set up CPython (3.12.16)`. Test 단계 pytest 머리말: `platform linux -- Python 3.12.16, pytest-9.2.0, pluggy-1.7.0`
  - Install 단계(`shell: /usr/bin/bash -e {0}`):
    ```
    python -m venv ~/.venvs/anf-clone
    ~/.venvs/anf-clone/bin/pip install -e ".[dev]"
    echo "$HOME/.venvs/anf-clone/bin" >> "$GITHUB_PATH"
    Obtaining file:///home/runner/work/anf-clone/anf-clone
    Building editable for anf-clone (pyproject.toml): finished with status 'done'
    Created wheel for anf-clone: filename=anf_clone-0.1.0-0.editable-py3-none-any.whl
    Successfully installed anf-clone-0.1.0 ... fastapi-0.162.2 ... pytest-9.2.0 ... uvicorn-0.54.0
    ```
  - jobs API 단계 결론: `Install success` (04:04:59Z~04:05:09Z)
- 참고(추론): Test 단계의 `python`이 venv의 Python이라는 직접 출력은 없다(로그의 `env`에는 `PATH`가 찍히지 않는다). 다만 Test 단계의 pytest 버전(9.2.0)과 플러그인(`anyio-4.16.0`)이 Install 단계에서 venv에 설치한 버전과 같고, Hook tests(Linux에서 이 venv를 찾는 TDD 훅의 테스트)도 통과했다. 기준이 요구하는 "설치 기록"은 위에 직접 있다.

### [PASS] AC-03 린트 (API 계약: 정적 검사)
- 기준: `ruff check backend .claude/hooks` 단계가 위반 0건으로 통과한다.
- 출력(핵심 부분, run 42445326221, Lint 단계):
  ```
  pip install ruff==0.14.0
  ruff check backend .claude/hooks
  Successfully installed ruff-0.14.0
  All checks passed!
  ```
- jobs API 단계 결론: `Lint success` (04:05:09Z~04:05:10Z)
- 이 검사가 실제로 위반을 잡는다는 것은 AC-06(b)에서 확인했다.

### [PASS] AC-04 테스트 (API 계약: 테스트 결과)
- 기준: 테스트 단계가 실패 0, 오류 0, skip 0으로 통과한다. 수집 수는 로컬 Windows 실행의 passed + skipped와 같다(342 = 279 + 63).
- 출력(핵심 부분, run 42445326221):
  - Test 단계 env: `ANF_E2E_API_URL: http://127.0.0.1:8080`
  - `collected 342 items` … `======================= 342 passed in 112.05s (0:01:52) ========================`
  - 파일별 통과 수(로그의 진행 표시 `.`를 파일별로 센 값. `s`, `F`, `E`는 0개):

    | 파일 | 통과 |
    | --- | --- |
    | contract/test_arm_app.py | 33 |
    | contract/test_capacity_pools_api.py | 43 |
    | e2e/test_capacity_pool_live.py | 30 |
    | e2e/test_capacity_pool_lro_faults_live.py | 9 |
    | e2e/test_netapp_account_live.py | 16 |
    | e2e/test_netapp_account_lro_faults_live.py | 8 |
    | unit/test_accounts.py | 45 |
    | unit/test_arm_rules.py | 48 |
    | unit/test_capacity_pools.py | 69 |
    | unit/test_lro.py | 26 |
    | unit/test_state_store.py | 15 |
    | **e2e 합계 / 그 밖 / 전체** | **63 / 279 / 342** |
  - Fail on skipped tests 단계: `collected 342, skipped 0`
  - jobs API 단계 결론: `Test success` (04:05:10Z~04:07:03Z), `Fail on skipped tests success`
- 판단: 요약 줄이 `342 passed`뿐이라 실패·오류는 0이다(있으면 `N failed`, `N errors`가 붙고 단계가 실패한다). e2e 63개가 skip이 아니라 실제로 uvicorn을 띄워 통과했다. 수집 수 342는 설계의 기준값(로컬 Windows 279 + 63)과 같다. 같은 커밋에서 `ANF_E2E_API_URL`만 뺀 AC-06(c) run은 `279 passed, 63 skipped`였다. 이것도 Windows 기준값과 같은 분할이다.
- 소요 시간: 작업 전체 2분 16초(04:04:57Z~04:07:13Z), Test 단계 112초. 결정 8의 제한 15분 안이다.

### [PASS] AC-05 훅 테스트 (API 계약: 테스트 결과)
- 기준: `.claude/hooks/tests`가 통과한다 (지금 25개).
- 출력(핵심 부분, run 42445326221, Hook tests 단계):
  ```
  python -m pytest .claude/hooks/tests
  collected 25 items
  .claude/hooks/tests/test_tdd_guard.py .........................          [100%]
  ============================== 25 passed in 6.87s ==============================
  ```
- jobs API 단계 결론: `Hook tests success` (04:07:03Z~04:07:10Z)

### [PASS] AC-06 실패 감지 (상태 전이: 작업 결론)
- 기준: 임시 브랜치에서 세 경우가 각각 작업 실패로 끝나고, 실패한 단계가 원인을 가리킨다. 확인 뒤 임시 브랜치를 지운다.
- 공통: 세 브랜치 모두 `origin/feature/ci`(`3fd6511`)에서 만들고 커밋 하나만 더했다. 세 run 모두 `event: push`, 러너 `ubuntu-24.04`, `CPython (3.12.16)`이다. 단계 이름은 jobs API의 단계 목록과 작업 로그의 `##[group]Run …` 경계로 확인했다(위 "API 반영 지연" 참조).

| 경우 | 브랜치 / 커밋 | 바꾼 것 | run | 결론 | 실패한 단계 |
| --- | --- | --- | --- | --- | --- |
| (a) | `ci-verify/test-fail` / `1ec275e` | `backend/tests/unit/test_arm_rules.py:27` `assert API_VERSION == "1999-01-01"` | [42445665196](https://github.com/goldenbit1999/anf-clone/actions/runs/42445665196) | failure | Test |
| (b) | `ci-verify/lint-fail` / `46074d6` | `backend/tests/unit/test_arm_rules.py:3`에 `import os`(쓰지 않음) | [42445687864](https://github.com/goldenbit1999/anf-clone/actions/runs/42445687864) | failure | Lint |
| (c) | `ci-verify/skip-fail` / `83c024c` | `.github/workflows/ci.yml` Test 단계의 `env: ANF_E2E_API_URL` 두 줄 삭제 | [42445712865](https://github.com/goldenbit1999/anf-clone/actions/runs/42445712865) | failure | Fail on skipped tests |

- (a) 단계별 로그 핵심 (job 128623942778):
  - Lint: `All checks passed!` (통과)
  - Test (env에 `ANF_E2E_API_URL: http://127.0.0.1:8080` 있음):
    ```
    >       assert API_VERSION == "1999-01-01"  # ci-verify: deliberate failure (AC-06a)
    E       AssertionError: assert '2026-08-01' == '1999-01-01'
    backend/tests/unit/test_arm_rules.py:27: AssertionError
    FAILED backend/tests/unit/test_arm_rules.py::test_supported_api_version_passes - AssertionError: assert '2026-08-01' == '1999-01-01'
    ================== 1 failed, 341 passed in 115.35s (0:01:55) ===================
    ##[error]Process completed with exit code 1.
    ```
  - 그 뒤 `Fail on skipped tests`, `Hook tests`의 `##[group]Run` 줄이 로그에 없다(실행되지 않음). 바로 `Post job cleanup`.
  - jobs API 단계 결론: `Lint success`, `Test failure`, `Fail on skipped tests skipped`, `Hook tests skipped`
- (b) 단계별 로그 핵심 (job 128624008101):
  - Install: 통과. Lint:
    ```
    F401 [*] `os` imported but unused
     --> backend/tests/unit/test_arm_rules.py:3:8
    3 | import os  # ci-verify: deliberate unused import (AC-06b)
    Found 1 error.
    [*] 1 fixable with the `--fix` option.
    ##[error]Process completed with exit code 1.
    ```
  - 로그에 `Run python -m pytest` 줄이 0개다. Test, Fail on skipped tests, Hook tests는 실행되지 않았다.
  - jobs API 단계 결론: `Install success`, `Lint failure`, `Test skipped`, `Fail on skipped tests skipped`, `Hook tests skipped`
- (c) 단계별 로그 핵심 (job 128624076811):
  - Lint: `All checks passed!`
  - Test: 단계 env에 `ANF_E2E_API_URL`이 없다(`pythonLocation` … `LD_LIBRARY_PATH`만 있음). `collected 342 items`, skip 사유는 모두 `ANF_E2E_API_URL is not set (live anf-api e2e runs in WSL)`, `======================= 279 passed, 63 skipped in 13.04s =======================`. 이 단계는 성공으로 끝났다.
  - Fail on skipped tests:
    ```
    Skipped tests are not passes. Run them here or deselect them by marker on purpose.
    collected 342, skipped 63
    ##[error]Process completed with exit code 1.
    ```
  - jobs API 단계 결론: `Install success`, `Lint success`, `Test success`, `Fail on skipped tests failure`, `Hook tests skipped`
- 판단: 세 경우 모두 작업 결론이 `failure`이고, 실패한 단계가 각각 원인(테스트 실패, 린트 위반, skip)을 가리킨다. 특히 (c)에서 pytest는 63개 skip에도 성공(종료 코드 0)으로 끝났고, skip 검사 단계만 실패했다. 결정 6이 막으려던 "조용한 초록색"을 실제로 막는다.
- 정리: 아래 "정리 결과" 절.

### [PASS] AC-07 제품 코드 불변 (데이터 효과 없음: 해시 비교)
- 기준: 이번 변경 뒤에도 제품 코드 내용 해시가 `f2b70558…`(커밋 `41f863d`)와 같다.
- 실행한 명령 (Git Bash, 저장소 루트. `anf-feature-cycle` 3단계 4번):
  ```bash
  # 커밋
  git ls-tree -r --name-only "$SHA" -- pyproject.toml backend | grep -v '^backend/tests/' | LC_ALL=C sort | while IFS= read -r f; do git show "$SHA:$f"; done | tr -d '\r' | sha256sum
  # 작업 트리
  git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum
  ```
- 출력(핵심 부분):

  | 대상 | 시점 | 해시 |
  | --- | --- | --- |
  | 커밋 `3fd6511` | 시작, 끝 | `f2b70558c8189ab44ba210081d30ed52978c8e56f529ddba84edeb12656bc955` |
  | 커밋 `41f863d` | 시작 | `f2b70558c8189ab44ba210081d30ed52978c8e56f529ddba84edeb12656bc955` |
  | 작업 트리 (HEAD `3fd6511`) | 시작, 끝 | `f2b70558c8189ab44ba210081d30ed52978c8e56f529ddba84edeb12656bc955` |

  - `git diff --name-only 41f863d 3fd6511 -- pyproject.toml backend ':!backend/tests'` → 출력 없음.
  - `git diff --stat 41f863d 3fd6511`에서 `backend/`의 변경은 `backend/tests/e2e/test_netapp_account_lro_faults_live.py` 한 줄뿐이다(`srv = start_server(faults=DELAYS)` → `start_server(faults=DELAYS)`, F841). 이 파일의 8개 테스트는 CI에서 모두 통과했다(AC-04 표).
- 판단: 제품 코드는 바뀌지 않았다. 계정·풀의 판정은 그대로 유지된다.

## 단계 결론 표 (jobs API)

| run | 경우 | 단계 결론 |
| --- | --- | --- |
| 42445326221 | 성공 run | Set up job, checkout, setup-python, Install, Lint, Test, Fail on skipped tests, Hook tests, Post 단계, Complete job 모두 `success` |
| 42445665196 | (a) | Set up job, checkout, setup-python, Install, Lint `success` / **Test `failure`** / Fail on skipped tests `skipped`, Hook tests `skipped` |
| 42445687864 | (b) | Set up job, checkout, setup-python, Install `success` / **Lint `failure`** / Test `skipped`, Fail on skipped tests `skipped`, Hook tests `skipped` |
| 42445712865 | (c) | Set up job, checkout, setup-python, Install, Lint, Test `success` / **Fail on skipped tests `failure`** / Hook tests `skipped` |

세 실패 run 모두 실패한 단계는 하나뿐이고, 그 뒤 단계는 `skipped`, `Complete job`은 `success`(작업 결론은 `failure`)다. 이 표는 작업이 끝나고 몇 분 뒤에 다시 조회해 얻었다(환경 사전 점검의 "API 반영 지연").

## 정리 결과

- 실행한 명령 (주 저장소에서):
  ```
  git worktree remove <scratchpad>/ci-verify-wt
  git push origin --delete ci-verify/test-fail ci-verify/lint-fail ci-verify/skip-fail
  git branch -D ci-verify/test-fail ci-verify/lint-fail ci-verify/skip-fail
  git worktree prune
  ```
- 출력:
  - `- [deleted] ci-verify/lint-fail`, `- [deleted] ci-verify/skip-fail`, `- [deleted] ci-verify/test-fail`
  - `Deleted branch ci-verify/test-fail (was 1ec275e).` 외 2건
  - `git ls-remote --heads origin 'ci-verify/*'` → 출력 없음 (비었음)
  - `git worktree list` → `C:/Users/mkimh/Projects/ANF-clone  3fd6511 [feature/ci]` 한 줄
  - `git branch --list 'ci-verify/*'` → 출력 없음
  - worktree 디렉터리는 지워졌다(`ls` → `No such file or directory`).
- 주 작업 디렉터리: 브랜치 `feature/ci`, HEAD `3fd6511`, `git status --short`는 검증 시작 때와 같다. 원격 `main`(`41f863d`)과 `feature/ci`(`3fd6511`)도 바뀌지 않았다. 열린 PR은 0개다.
- 임시 브랜치의 Actions run 기록 세 개는 남아 있다(허용됨).

## 관찰 (판정에 영향 없음)

1. **skip 검사 출력 순서**: (c)에서 `sys.exit` 메시지(stderr)가 `print`한 `collected 342, skipped 63`(stdout)보다 먼저 찍혔다. 파이프로 연결된 stdout은 버퍼링되고 stderr는 즉시 쓰이기 때문이다. 판정에는 영향이 없다. 순서를 맞추려면 `.github/workflows/ci.yml:57`을 `print(..., flush=True)`로 바꾸면 된다(선택).
2. **실패 annotation이 일반적이다**: 세 실패 run의 annotation은 모두 `Process completed with exit code 1.` 한 건이다. 실패 원인(테스트 이름, ruff 위치)은 로그를 열어야 보인다. PR 화면에서 바로 보이게 하려면 `ruff check --output-format=github`를 쓰는 방법이 있다(선택, 설계 범위 밖).
3. **기준 밖 결정은 실행으로 확인하지 않았다**: 결정 7의 `concurrency`(같은 ref의 이전 실행 취소)와 결정 8의 `timeout-minutes: 15`가 실제로 작동하는 것은 AC에 없어서 시험하지 않았다. 성공 run이 2분 16초에 끝나 제한 안이라는 것만 확인했다.
