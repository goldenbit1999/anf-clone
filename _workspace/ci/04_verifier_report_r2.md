# ci 검증 보고서 — 2회차

- 검증일: 2026-11-07 (로컬 PST). 조회 시각은 UTC 2026-11-08 04:20~04:22. 판정한 run은 04:17:44Z에 생성됐다
- 검증 대상 코드:
  - 커밋 `3fd65119b7c05edda6e969adaf2f1ea43b0444f0` (브랜치 `feature/ci`, PR #6의 head). 로컬 `git rev-parse HEAD`, 원격 `refs/heads/feature/ci`, PR #6의 `headRefOid`가 모두 이 값이다.
  - 제품 코드 내용 해시(작업 트리 명령): `f2b70558c8189ab44ba210081d30ed52978c8e56f529ddba84edeb12656bc955`. 검증을 시작할 때와 끝낼 때(04:21:23Z) 계산했고 값이 같다. 1회차와도 같다.
    `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum`
  - 미커밋 변경: 제품 코드에는 없다. 주 작업 디렉터리에 `_workspace/ci/00_progress.md`(M), untracked `_workspace/ci/04_verifier_report.md`, `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`, `docs/concepts/ci.md`가 있다. 모두 제품 코드가 아니고 해시에 들어가지 않는다.
  - 1회차 이후 바뀐 것: 코드와 워크플로는 그대로다(리더 보고). 사용자 요청으로 main 대상 PR #6이 열렸다.
- 이번 회차 범위: 재검증. AC-01b(main 대상 PR의 `pull_request` 이벤트로 실행)만 판정한다. 코드가 바뀌지 않아 AC-01a, AC-02~AC-07은 다시 실행하지 않았고 1회차 결과를 그대로 적는다.
- 검증 방법: GitHub Actions의 실제 실행 기록만을 근거로 썼다. 워크플로 정의를 읽은 것은 근거로 쓰지 않았다. 조회 명령은 `gh api .../actions/runs/{id}`, `.../runs/{id}/jobs`, `.../actions/jobs/{job_id}/logs`(작업 전체 로그), `.../commits/{sha}`, `gh pr view 6`, `gh pr checks 6`이다. 이번 회차에는 브랜치, PR, push, 저장소 파일(이 보고서 제외)을 만들거나 바꾸지 않았다.

## 환경 사전 점검

| 항목 | 결과 |
| --- | --- |
| gh CLI | 2.89.0. `goldenbit1999`로 로그인했고 토큰 범위는 `gist, read:org, repo, workflow`다 (1회차와 같다) |
| 저장소 접근 | 1회차와 같다(`PRIVATE`, `viewerPermission: ADMIN`). 이번 조회도 모두 성공했다 |
| 원격 ref | `feature/ci` = `3fd6511…`, `main` = `41f863d…`. 1회차와 같다 |
| PR #6 | `gh pr view 6`: `state: OPEN`, `isDraft: false`, `headRefName: feature/ci`, `headRefOid: 3fd6511…`, `baseRefName: main`, `mergeable: MERGEABLE` |
| API 반영 지연 | 이번에는 없었다. 첫 조회에서 모든 단계 결론이 채워져 있었다 |

## 결과 요약

PASS 1 / FAIL 0 / UNVERIFIED 0 (이번 회차에 실행한 항목: AC-01b)

수락 기준 전체로 보면 PASS 8 / FAIL 0 / UNVERIFIED 0이다. 1회차의 7개 항목(AC-01a, AC-02~AC-07)과 이번 AC-01b를 합한 수다.

## 수락 기준별 최신 결과

| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01a push 트리거 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-01b pull_request 트리거 | PASS | 2회차 (이 보고서). 1회차에는 UNVERIFIED였다(PR 없음) |
| AC-02 환경 | PASS | 1회차 (`04_verifier_report.md`). 이번 PR run에서도 `ubuntu-24.04`, CPython 3.12.16, venv 설치 기록이 같게 나왔다(참고) |
| AC-03 린트 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-04 테스트 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-05 훅 테스트 | PASS | 1회차 (`04_verifier_report.md`) |
| AC-06 실패 감지 | PASS (a, b, c) | 1회차 (`04_verifier_report.md`) |
| AC-07 제품 코드 불변 | PASS | 1회차 (`04_verifier_report.md`). 이번 회차의 작업 트리 해시도 `f2b70558…`로 같다 |

## 항목별 결과

### [PASS] AC-01b pull_request 트리거 (API 계약: 워크플로 트리거)
- 기준: main 대상 PR을 열면 `pull_request` 이벤트로도 워크플로 `ci`가 돈다.
- 실행한 명령과 출력(핵심 부분):
  1. **run이 `pull_request` 이벤트이고 PR #6과 연결돼 있다.**
     `gh api repos/goldenbit1999/anf-clone/actions/runs/42446223916`
     ```
     "event":"pull_request", "name":"ci", "path":".github/workflows/ci.yml",
     "head_branch":"feature/ci", "head_sha":"3fd65119b7c05edda6e969adaf2f1ea43b0444f0",
     "run_attempt":1, "status":"completed", "conclusion":"success",
     "triggering_actor":"goldenbit1999", "created_at":"2026-11-08T04:17:44Z",
     "pull_requests":[{"number":6,"head":{"ref":"feature/ci","sha":"3fd6511…"},"base":{"ref":"main","sha":"41f863d…"}}]
     ```
     run URL: https://github.com/goldenbit1999/anf-clone/actions/runs/42446223916. `gh run list --event pull_request`도 이 run 하나(`42446223916 feature/ci 3fd6511 success`)를 돌려준다. 1회차 때는 0개였다.
  2. **PR merge ref를 체크아웃했다.** 작업 로그(job 128625608018)의 checkout 단계:
     ```
     git ... fetch ... --depth=1 origin +86b20aa561583da8e7ed25c5344b3c79a2ef510a:refs/remotes/pull/6/merge
      * [new ref]         86b20aa561583da8e7ed25c5344b3c79a2ef510a -> pull/6/merge
     git checkout --progress --force refs/remotes/pull/6/merge
     HEAD is now at 86b20aa Merge 3fd65119b7c05edda6e969adaf2f1ea43b0444f0 into 41f863d3f8c477b61ca85c60cdd64cefa6c540e6
     ```
     이 merge 커밋의 트리는 `3fd6511`의 트리와 같다:
     - `gh api repos/goldenbit1999/anf-clone/commits/86b20aa…` → `tree: c26d3131e7904d3e9b25ef6668fb8aec20f27da1`, `parents: [41f863d…, 3fd6511…]`
     - `git rev-parse '3fd6511^{tree}'` → `c26d3131e7904d3e9b25ef6668fb8aec20f27da1`
     - `git merge-base --is-ancestor 41f863d 3fd6511` → 참. main이 PR head의 조상이라 merge 결과의 내용이 PR head와 같다.

     그래서 PR run이 검증한 파일 내용은 검증 대상 커밋 `3fd6511`과 같다.
  3. **backend 작업이 이 이벤트로 끝까지 돌았다.**
     `gh api .../actions/runs/42446223916/jobs`: `job backend conclusion=success labels=["ubuntu-24.04"]` (04:17:48Z~04:20:03Z, 2분 15초)

     | # | 단계 | 결론 | 시간(UTC) |
     | --- | --- | --- | --- |
     | 1 | Set up job | success | 04:17:49 |
     | 2 | Run actions/checkout@v5 | success | 04:17:49~04:17:50 |
     | 3 | Run actions/setup-python@v6 | success | 04:17:50 |
     | 4 | Install | success | 04:17:50~04:17:59 |
     | 5 | Lint | success | 04:17:59~04:18:01 |
     | 6 | Test | success | 04:18:01~04:19:53 |
     | 7 | Fail on skipped tests | success | 04:19:53 |
     | 8 | Hook tests | success | 04:19:53~04:20:00 |
     | 15–17 | Post setup-python, Post checkout, Complete job | success | 04:20:00~04:20:01 |

     작업 로그의 핵심 줄:
     ```
     Image: ubuntu-24.04          (Operating System: Ubuntu 24.04.5)
     Contents: read               (GITHUB_TOKEN Permissions)
     Successfully set up CPython (3.12.16)
     Successfully installed anf-clone-0.1.0 ... pytest-9.2.0 ... uvicorn-0.54.0
     All checks passed!                                  (Lint)
       ANF_E2E_API_URL: http://127.0.0.1:8080            (Test 단계 env)
     collected 342 items
     ======================= 342 passed in 111.44s (0:01:51) ========================
     collected 342, skipped 0                            (Fail on skipped tests)
     collected 25 items
     .claude/hooks/tests/test_tdd_guard.py .........................          [100%]
     ============================== 25 passed in 6.79s ==============================
     ```
     Test 단계의 진행 표시를 파일별로 세면 e2e 63개, 그 밖 279개, 합계 342개가 통과(`.`)했다. `s`, `F`, `E`, `x`는 0개다. 1회차 push run과 같은 분할이다.
  4. **PR 쪽에서 체크가 보인다.**
     `gh pr checks 6` (종료 코드 0):
     ```
     backend	pass	2m16s	https://github.com/goldenbit1999/anf-clone/actions/runs/42445326221/job/128622932547
     backend	pass	2m15s	https://github.com/goldenbit1999/anf-clone/actions/runs/42446223916/job/128625608018
     ```
     `gh pr checks 6 --json name,state,event,workflow,link`:
     ```
     {"name":"backend","workflow":"ci","event":"pull_request","state":"SUCCESS","link":".../runs/42446223916/job/128625608018", ...}
     {"name":"backend","workflow":"ci","event":"push","state":"SUCCESS","link":".../runs/42445326221/job/128622932547", ...}
     ```
     PR #6에는 `pull_request` 체크(이번 run)와 `push` 체크(1회차 run 42445326221)가 둘 다 붙어 있다. 같은 head 커밋 `3fd6511`에서 돈 체크이기 때문이다.
- 판단: main 대상 PR을 열자 `pull_request` 이벤트로 워크플로 `ci`가 자동으로 돌았다. 그 run은 PR #6에 연결돼 있고 `refs/pull/6/merge`를 체크아웃했다. backend 작업은 모든 단계를 성공으로 마쳤고(342 passed, skip 0, 훅 테스트 25 passed), PR의 체크 목록에 `pull_request` 이벤트의 체크로 보인다. AC-01b를 PASS로 판정한다. AC-01(push와 PR)이 모두 PASS다.

## 관찰 (판정에 영향 없음)

1. **PR 하나에 같은 이름의 체크가 둘 붙는다(관찰).** push와 main 대상 PR이 모두 트리거라서(설계 결정 7), PR #6에는 `backend` 체크가 push run과 pull_request run 두 개로 보인다. 앞으로 PR이 열린 브랜치에 push하면 `backend`가 두 번 돌 것이다. 하나는 브랜치 head를, 다른 하나는 merge 결과를 검증한다. 동시성 그룹이 `ci-${{ github.ref }}`이고 두 이벤트의 ref(`refs/heads/feature/ci`, `refs/pull/6/merge`)가 다르므로 서로 취소하지 않을 것으로 추론한다. 이번에는 두 run의 실행 시간이 겹치지 않아(04:04~04:07, 04:17~04:20) 실제로 관찰하지는 않았다. 실행이 두 배로 드는 것이 문제가 되면 push 트리거를 좁히는 방법이 있다(선택. 설계 결정 7을 바꾸는 일이라 리더가 판단할 일이다).
2. **이번 PR run은 merge 결과가 PR head와 같은 경우다.** main이 PR head의 조상이라 merge 커밋의 트리가 `3fd6511`과 같았다. main이 앞서 나간 뒤 PR을 다시 돌리면, `pull_request` run은 `3fd6511`이 아니라 새 merge 결과를 검증한다. 그때의 판정 대상 코드는 그 run의 merge 커밋으로 적어야 한다.
