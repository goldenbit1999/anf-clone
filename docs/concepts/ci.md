# CI (GitHub Actions, backend 작업)

> CI는 "push와 PR마다 같은 절차로 설치, 린트, 테스트를 돌려 결과를 한 곳에 남기는 장치"다. 이 문서의 핵심은 세 가지다. (1) pytest는 skip이 있어도 종료 코드 0이라서, skip을 실패로 바꾸는 단계를 따로 둔다. (2) CI가 초록색이라는 사실만으로는 CI가 실패를 잡는다는 증거가 못 되므로, 일부러 깨뜨린 임시 브랜치 세 개로 확인했다. (3) 지금은 컨트롤 플레인만 CI에서 돈다. 데이터 플레인은 스파이크 S3 뒤라서 FR-11은 `partial`이다.

FR-11(CI)을 다룬다. 이 기능은 ANF 기능이 아니라 엔지니어링 장치다. PRD §8에서 FR-11은 조사(1단계)를 생략하는 FR이라 조사 브리프가 없고, 아래 1, 2절은 "해당 없음"이다. 사실의 근거는 설계 기록(`_workspace/ci/02_main_design.md`), 검증 보고서(`_workspace/ci/04_verifier_report.md`), 그리고 실제 워크플로 파일이다. 브리프의 근거 표시([스펙], [녹화] 등)는 쓰지 않는다. 대신 GitHub Actions 실행 기록에서 직접 확인한 값에는 run ID를 붙였다.

---

## 1. ANF에서는

해당 없음. CI는 ANF의 기능이 아니다. 다만 이 공고(ANF 데이터 플레인 엔지니어)가 "Python 테스트 자동화, CI/CD"를 강조하므로, 이 프로젝트가 그 기술을 어떻게 쓰는지를 보여 주는 결과물이다 (PRD G4).

## 2. ONTAP에서는

해당 없음.

## 3. 이 프로젝트에서는

### 3.1 구조

```
push (모든 브랜치) ─┐
PR (main 대상) ─────┴─> GitHub Actions: 워크플로 ci, 작업 backend (ubuntu-24.04, Python 3.12)
                          1. checkout, setup-python
                          2. Install   : 문서의 WSL 설정 명령 그대로 (venv + pip install -e ".[dev]")
                          3. Lint      : ruff 0.14.0 기본 규칙
                          4. Test      : pytest 전체 (단위 + 계약 + 라이브 API e2e), JUnit XML 저장
                          5. Fail on skipped tests : XML에서 skipped != 0 이면 실패
                          6. Hook tests: TDD 훅 자체의 테스트
                        앞 단계가 실패하면 뒤 단계는 실행되지 않는다 (skipped)
```

이번에 만든 것은 backend 작업 하나다. 만들지 않은 것은 아래와 같고, 그래서 FR-11은 `partial`로 끝난다.

| 안 만든 것 | 이유 |
| --- | --- |
| frontend 작업 (타입 검사, 빌드, 단위 테스트) | 대시보드(FR-09)가 아직 없다 |
| data-plane 작업 (커널 모듈, storage agent, 통합·데이터 플레인 E2E) | 볼륨부터 생긴다. GitHub 호스트 러너에서 btrfs·nfsd 모듈을 로드하고 privileged 컨테이너로 마운트할 수 있는지를 스파이크 S3로 먼저 확인해야 한다 (ADR §10) |
| 브랜치 보호 (main merge 전에 CI 통과 필수) | 저장소 설정이라 사용자가 정할 일이다. 아직 켜지 않았다 |

### 3.2 코드 따라가기 (`.github/workflows/ci.yml`)

**트리거와 권한 (`ci.yml:5-15`)**
- `on.push`에 필터가 없어서 모든 브랜치의 push에 돈다 (`ci.yml:6`). `pull_request`는 `branches: [main]`이라 main을 향한 PR에만 돈다 (`ci.yml:7-8`). push만 해도 결과를 볼 수 있어야 PR 전에 고칠 수 있다.
- `permissions: contents: read` (`ci.yml:10-11`)는 최소 권한이다. 성공 run 로그에 `Contents: read, Metadata: read`만 찍혔다 (보고서 AC-01a).
- `concurrency`로 같은 ref의 이전 실행은 취소한다 (`ci.yml:13-15`). 연속 push에서 낡은 커밋의 결과를 기다리지 않으려는 것이다. 이 동작은 수락 기준이 아니라서 실제로 취소되는지 시험하지 않았다.

**러너와 제한 시간 (`ci.yml:19-20`)**
- `ubuntu-24.04`로 고정했다. 개발 환경이 WSL Ubuntu 24.04라서 `ubuntu-latest`처럼 바뀔 수 있는 값을 피했다. 성공 run 로그의 OS는 `Ubuntu 24.04.5 LTS`였다.
- `timeout-minutes: 15`. e2e가 멈추면(서버가 안 뜨는 등) 기본값 6시간을 기다리지 않게 한다. 성공 run은 2분 16초에 끝났다. 이 제한이 실제로 작동하는지도 시험하지 않았다.

**Install (`ci.yml:28-33`)**
- `python -m venv ~/.venvs/anf-clone`, `pip install -e ".[dev]"`는 `CLAUDE.md`의 WSL 설정 명령과 같다. CI가 문서의 설정 절차를 매번 따라 해 보는 효과가 있다. TDD 훅도 Linux에서 이 경로의 venv를 찾기 때문에, 훅 테스트 단계(아래)가 같은 환경에서 돈다.
- 마지막 줄 `echo "$HOME/.venvs/anf-clone/bin" >> "$GITHUB_PATH"` (`ci.yml:33`)는 다음 단계부터 `python`, `pytest`가 venv의 것이 되게 한다. 단계마다 새 셸이 뜨므로 PATH를 `GITHUB_PATH`로 넘겨야 한다.

**Lint (`ci.yml:35-39`)**
- `pip install ruff==0.14.0`, `ruff check backend .claude/hooks`. 설정 파일 없이 ruff 기본 규칙만 쓴다. 린트는 테스트보다 빠르고 싸서(성공 run에서 1초) 먼저 돌린다. 문법 수준의 실수가 있으면 2분 걸리는 테스트를 기다리지 않고 바로 실패한다. 실제로 AC-06(b)에서 Lint가 실패하자 Test 이후 단계는 실행되지 않았다.
- **ruff를 `pyproject.toml`의 dev 의존성에 넣지 않은 이유.** `pyproject.toml`은 "제품 코드 내용 해시"에 들어간다 (아래 3.4). 이 파일을 바꾸면 이미 검증을 마친 계정·풀 기능의 검증 대상 코드가 달라져서 판정이 무효가 된다(무효화 규칙). ruff 추가는 실행 동작을 바꾸지 않는데도 재검증을 부르는 것은 낭비라서, CI 단계 안에서만 버전을 고정해 설치했다. 트레이드오프는 개발자가 로컬에서 린트를 돌리려면 ruff를 따로 설치해야 한다는 점이다. 린트 규칙도 기본값에 두었다. 규칙을 넓히면 제품 코드를 고치게 되어 같은 문제가 생긴다.
- 기본 규칙으로 걸린 것은 제품 코드가 아니라 테스트 파일의 F841(쓰지 않는 변수) 1건이었다. `backend/tests/e2e/test_netapp_account_lro_faults_live.py:37`에서 `srv = start_server(faults=DELAYS)`를 `start_server(faults=DELAYS)`로 고쳤다. 테스트 파일은 해시 대상이 아니다.

**Test (`ci.yml:41-45`)**
- `ANF_E2E_API_URL: http://127.0.0.1:8080`을 켜고 `python -m pytest --junitxml=pytest-results.xml`을 돌린다. 인자 없이 `python -m pytest`인 것은 `testpaths`, 마커, `addopts`가 루트 `pyproject.toml`에 있어서 훅·수동 실행·CI가 같은 설정을 쓰기 때문이다.
- 단위·계약 테스트 279개와 라이브 API e2e 63개가 함께 돈다 (합계 342). 이 환경 변수가 있어야 e2e가 skip되지 않는다 (`backend/tests/e2e/live_api.py:31-36`: `ANF_E2E_API_URL`이 비어 있으면 `SKIP_UNLESS_LIVE`가 모든 e2e를 skip으로 표시한다).
- `--junitxml`은 바로 다음 단계가 읽을 결과 파일이다.

**Fail on skipped tests (`ci.yml:47-60`)**
- 이 단계가 이 워크플로의 핵심 설계다. 아래 3.3에서 자세히 설명한다. 코드는 JUnit XML의 루트에서 `tests`와 `skipped` 속성을 읽어 (`ci.yml:54-56`), 수집된 테스트가 0개이거나 skip이 하나라도 있으면 `sys.exit(메시지)`로 종료 코드 1을 낸다 (`ci.yml:58-59`). `tests == 0` 검사는 "테스트가 하나도 안 돌았는데 초록색"이라는 또 다른 조용한 실패를 막는다.
- `ci.yml:55`는 XML의 두 가지 모양을 받는다. 지금 pytest(로컬 9.2.0으로 확인)는 루트를 `<testsuites>`로 쓰고 그 안에 `<testsuite>`를 두므로, 평소에는 `root.find("testsuite")`로 내려간다. 루트가 바로 `<testsuite>`인 옛 모양도 받도록 둔 것은 방어다.

**Hook tests (`ci.yml:62-63`)**
- `python -m pytest .claude/hooks/tests`. TDD 훅(`tdd_guard.py`)은 이 프로젝트의 개발 도구이고 자체 테스트가 25개 있다. 기본 `testpaths`에는 들어 있지 않으므로(약 25초 걸리는 Windows 기준) 따로 돌려야 한다. CI의 Linux에서는 약 7초에 끝났다. 마지막 단계라서 앞 단계(린트, 테스트, skip 검사) 중 하나가 실패하면 실행되지 않는다. AC-06의 세 run에서 실제로 `skipped`였다.

### 3.3 왜 skip을 실패로 보는가

pytest는 skip이 있어도 종료 코드 0으로 끝난다. 이 프로젝트의 e2e 63개는 `ANF_E2E_API_URL`이 없으면 조건부 skip이다. 누군가 워크플로에서 그 환경 변수 두 줄을 지우면(또는 오타를 내면) 테스트 63개가 조용히 건너뛰어지고, CI는 초록색으로 남는다. 가장 중요한 "실제 서버에 붙어 계약을 확인하는" 테스트가 빠졌는데도 아무도 모른다.

검증 run 42445712865가 이를 그대로 보여 준다. 같은 커밋에서 환경 변수만 뺐더니:
- Test 단계는 `279 passed, 63 skipped`로 **성공**했다.
- 다음 단계 Fail on skipped tests가 `collected 342, skipped 63`을 찍고 종료 코드 1로 **실패**시켰다.

이 규칙은 ADR §9.1의 "건너뛴 테스트를 통과로 보고하지 않는다"(TDD 훅의 SKIPPED도 같은 원칙)를 CI에까지 확장한 것이다.

미래에 대한 효과도 있다. 앞으로 root, 커널 모듈, Docker가 필요한 통합·E2E 테스트가 생기면, GitHub 러너에서는 그 테스트가 skip되므로 이 검사가 실패한다. 그러면 사람이 "이 테스트를 어디서 돌릴 것인가"를 명시적으로 정해야 한다. 마커로 골라내서 data-plane 작업(S3 통과 뒤)으로 옮기거나, 러너에서 돌아가게 만들거나, 둘 중 하나다. skip이 조용히 쌓이는 길이 막힌다.

### 3.4 CI의 AC-07과 해시: 앞 커밋과의 연결

CI 작업의 수락 기준 AC-07은 "CI를 추가한 뒤에도 제품 코드가 그대로다"였다. 제품 코드 판정은 계정·풀의 검증에 쓰인 코드와 같은 코드인지로 정한다. 이 비교에는 내용 해시를 쓰는데, 같은 브랜치의 앞 커밋 `e4acc7a`에서 이 절차를 줄 끝(CRLF/LF)에 무관하게 바꿨다 (`.claude/skills/anf-feature-cycle/SKILL.md` 3단계 4번). 명령에 `tr -d '\r'`이 들어 있어서 Windows 작업 트리와 Linux 커밋이 같은 값을 낸다. 해시 대상은 `pyproject.toml`과 `backend/`에서 `backend/tests/`를 뺀 파일이다. 그래서 위의 ruff 결정(dev 의존성에 넣지 않음)과 F841 수정(테스트 파일만 변경)이 모두 이 해시를 건드리지 않는다. 검증에서 커밋 `41f863d`와 `3fd6511`의 해시가 모두 `f2b70558…`로 같았다.

### 3.5 라이브 API e2e를 CI에서 돌릴 수 있는 이유, 데이터 플레인은 왜 아직 안 되는가

- 라이브 e2e가 CI에서 도는 것은 테스트가 anf-api를 직접 `subprocess.Popen`으로 uvicorn 프로세스로 띄우기 때문이다 (`backend/tests/e2e/live_api.py:246-250`). 이 컨트롤 플레인 테스트에는 root, 커널 모듈, Docker가 필요 없다. `ANF_E2E_API_URL`은 서버를 어디에 띄울지 알려 주는 주소일 뿐이다.
- 이 테스트들은 상태 전이, LRO 폴링, 재시작 복구(서버를 SIGKILL하고 같은 DB로 다시 띄움)를 실제 HTTP로 확인한다. 단위·계약 테스트가 가짜로 대체하는 부분을 PR마다 실제 서버로 한 번 더 확인하는 층이다 (ADR §9.1 "E2E (컨트롤 플레인)").
- 반면 데이터 플레인(btrfs 서브볼륨, knfsd export, 컨테이너 마운트)은 호스트 러너에서 커널 모듈을 로드하고 privileged 마운트를 할 수 있어야 한다. 이는 S3가 확인하기 전까지 모른다. 실패하면 데이터 플레인 테스트는 로컬이나 self-hosted 러너에서만 돌리고 그 사실을 문서에 적는다 (ADR §10).

### 3.6 설계 결정

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 라이브 API e2e까지 CI에서 돌린다 | 단위·계약만 (ADR §9.3의 원래 표) | e2e 63개가 root·커널·Docker 없이 돈다. 검증자가 WSL에서 확인한 계약을 PR마다 실제 서버로 다시 확인한다 |
| ruff 0.14.0, 기본 규칙, CI 단계에서만 설치 | `pyproject.toml` dev 의존성, 규칙 확장 | `pyproject.toml`이 제품 코드 해시에 들어가 완료된 기능의 검증을 무효로 만든다. 규칙을 넓히면 제품 코드 수정이 생긴다. 대가는 로컬 ruff를 따로 설치해야 하는 것 |
| `ubuntu-24.04`만 | ubuntu + windows, `ubuntu-latest` | 실행 환경이 WSL Ubuntu 24.04다. Windows 쪽은 편집마다 TDD 훅이 로컬에서 테스트를 돌린다. `latest`는 바뀐다 |
| 설치는 문서의 WSL 설정 명령 그대로 | 시스템 Python에 직접 `pip install` | 문서의 절차를 CI가 매번 확인하고, TDD 훅이 찾는 venv 경로와 같다 |
| skip이 있거나 수집 0개면 실패 | skip 허용 | pytest는 skip에도 종료 코드 0이라 환경 변수 하나가 빠져도 초록색이 된다 |
| 모든 브랜치 push와 main 대상 PR, `concurrency` 취소, `contents: read` | push는 main만 | PRD FR-11이 "푸시와 PR마다"다. 낡은 실행은 취소하고 권한은 최소로 한다 |
| 작업 제한 15분 | 기본 360분 | e2e가 멈출 때 6시간을 기다리지 않는다. 실제 소요는 약 2분 반이다 |
| 계획보다 앞당겨 지금 만든다 | PRD 순서대로 핵심 기능 뒤 | PR #4, #5가 검사 없이 merge됐고 다음 기능(볼륨)이 공통 코드를 크게 바꾼다 |

## 4. ADR §9.3의 원래 계획과 달라진 점

"실제 ANF와 다른 점"은 해당 없음이다. 대신 ADR §9.3이 처음 계획한 CI와 실제 구현이 다른 부분을 적는다. 이 변경은 설계 단계에서 사용자가 골랐고 ADR §9.1·§9.3에 이미 반영했다.

| 항목 | 원래 계획 | 실제 | 이유 |
| --- | --- | --- | --- |
| 라이브 API e2e | backend 작업은 단위·계약 테스트까지 | CI에서 라이브 API e2e 63개도 실행 | 테스트가 uvicorn을 직접 띄우고 root가 필요 없어서 가능했다 |
| 린트 | 도구 미정 | ruff 0.14.0 기본 규칙 | 규칙 확장 없이 제품 코드를 건드리지 않는다 |
| skip 처리 | 명시 없음 | skip이 있으면 실패 (JUnit XML 검사) | pytest의 skip은 종료 코드 0이다 |
| 훅 테스트 | 목록에 없음 | `.claude/hooks/tests` 25개를 CI에서 실행 | 훅이 Linux에서 같은 venv를 찾으므로 CI에서 확인할 수 있다 |
| 실행 시점 | PRD 계획상 핵심 기능 뒤 | 계정·풀 직후 | 위 설계 결정 표 마지막 줄 |

## 5. 검증

**판정 근거는 GitHub Actions의 실제 실행 기록만이다.** 로컬(WSL)에서 CI 단계를 재현했지만(린트 통과, 342 passed, 훅 25 passed) 그것은 구현 중 확인이고 PASS가 아니다. 검증은 real-env-verifier가 `gh` CLI로 run 기록을 조회해서 했다. 1회차는 PASS 7 / FAIL 0 / UNVERIFIED 1이었다. PR #6을 연 뒤 2회차에서 남은 AC-01b가 PASS가 되어, 모든 기준이 PASS다 (검증 대상 커밋 `3fd6511`).

| 기준 | 결과 | 근거 (따로 적지 않으면 push run 42445326221) |
| --- | --- | --- |
| AC-01a push 트리거 | PASS | `event: push`, `head_branch: feature/ci`, 결론 success |
| AC-01b PR 트리거 | PASS (2회차) | PR #6의 run 42446223916: `event: pull_request`, 체크아웃 ref `refs/pull/6/merge`, `342 passed`, `collected 342, skipped 0`, 훅 `25 passed`. `gh pr checks 6`에 push·PR 두 체크가 통과로 표시 |
| AC-02 환경 | PASS | `Ubuntu 24.04.5 LTS`, `CPython (3.12.16)`, venv에 `pip install -e ".[dev]"` 기록 |
| AC-03 린트 | PASS | `ruff-0.14.0`, `All checks passed!` |
| AC-04 테스트 | PASS | `collected 342 items`, `342 passed in 112.05s`, skip 검사 `collected 342, skipped 0`. e2e 63 + 그 밖 279 |
| AC-05 훅 테스트 | PASS | `25 passed in 6.87s` |
| AC-06 실패 감지 | PASS (a, b, c) | 아래 표 |
| AC-07 제품 코드 불변 | PASS | 내용 해시가 `41f863d`, `3fd6511`, 작업 트리 모두 `f2b70558…`. `41f863d`와 `3fd6511` 사이 `backend/`의 변경은 테스트 파일 한 줄뿐 |

**PR run이 검사하는 것은 PR head가 아니다.** `pull_request` run은 PR을 main에 merge한 결과(`refs/pull/6/merge`)를 체크아웃한다. 로그에 `HEAD is now at 86b20aa Merge 3fd6511… into 41f863d…`가 찍혔다. 이번에는 main이 PR head의 조상이라 merge 커밋 `86b20aa`의 트리가 `3fd6511`과 같았고, 그래서 push run과 같은 내용을 검사했다. main이 앞서 나간 뒤 PR run이 다시 돌면 새 merge 결과를 검사하므로, 그때는 그 merge 커밋이 검증 대상이다.

### 5.1 CI가 실패를 잡는지 어떻게 확인했나 (AC-06)

"CI가 초록색"은 CI가 아무것도 검사하지 않아도 나올 수 있다. 워크플로가 비어 있거나, 단계가 실제로는 아무것도 안 해도(예: skip) 초록색이다. 그래서 `origin/feature/ci`에서 임시 브랜치 세 개를 만들어 한 가지씩 일부러 깨뜨리고, 각각 의도한 단계에서 빨간색이 되는지 봤다. 주 브랜치와 `main`에는 push하지 않았고 PR도 만들지 않았다.

| 경우 | 브랜치 | 바꾼 것 | run | 실패한 단계 |
| --- | --- | --- | --- | --- |
| (a) 테스트 실패 | `ci-verify/test-fail` | `test_arm_rules.py:27`을 `assert API_VERSION == "1999-01-01"`로 | 42445665196 | Test (`1 failed, 341 passed`) |
| (b) 린트 위반 | `ci-verify/lint-fail` | `test_arm_rules.py:3`에 쓰지 않는 `import os` | 42445687864 | Lint (`F401 ... Found 1 error`) |
| (c) skip | `ci-verify/skip-fail` | Test 단계의 `ANF_E2E_API_URL` 두 줄 삭제 | 42445712865 | Fail on skipped tests (Test는 `279 passed, 63 skipped`로 통과) |

세 run 모두 실패한 단계는 하나뿐이었고 그 뒤 단계는 `skipped`였다. 확인 뒤 임시 브랜치는 원격과 로컬에서 모두 지웠다 (Actions run 기록은 남아 있다).

### 5.2 증명하지 못하는 것

- **`concurrency`와 `timeout-minutes: 15`.** 수락 기준이 아니라서 시험하지 않았다. 성공 run이 2분 16초에 끝나 제한 안이라는 것만 확인했다.
- **브랜치 보호.** CI가 빨간색이어도 merge를 막는 설정은 아직 없다. 지금의 CI는 "알려 주는" 장치이지 "막는" 장치가 아니다. 사용자가 정할 GitHub 설정이다.
- **데이터 플레인.** NFS 마운트, 스냅샷, 처리량 제한 같은 데이터 효과는 CI가 확인하지 못한다 (S3 뒤).
- **flaky 여부.** 성공 run은 같은 내용으로 2번(push, PR)이다. 이 테스트들이 여러 번 돌려도 안정적인지는 측정하지 않았다 [미확인].
- 검증 보고서의 관찰 3건(판정 밖): 실패 직후 몇 분간 GitHub API가 단계 결과·로그를 비워 돌려줌, skip 검사의 오류 문구가 `collected …` 줄보다 먼저 찍힘 (stdout 버퍼링, 고치려면 `ci.yml:57`에 `flush=True`), 실패 annotation이 `exit code 1`뿐이라 원인은 로그에서만 보임 (`ruff --output-format=github`로 개선 가능). 뒤의 둘은 설계 밖이라 그대로 뒀다.

## 6. 개발 과정

1. **조사: 생략.** PRD §8에 따라 FR-11은 조사를 거치지 않는다.
2. **설계.** 사용자가 범위(단위·계약 + 라이브 API e2e), 린트(ruff 기본 규칙), 러너(ubuntu만)를 골랐다. 설계 기록에 결정 8개와 수락 기준 AC-01~AC-07을 적었다. 계획상 FR-11은 핵심 기능 뒤였지만, PR #4, #5가 검사 없이 merge된 것을 보고 앞당기기로 했다. 같은 브랜치 앞 커밋 `e4acc7a`에서는 검증 해시 절차를 줄 끝에 무관하게 고쳐 두었다.
3. **구현.** `.github/workflows/ci.yml`, F841 수정 1건, `CLAUDE.md` 명령 절, ADR §9.1·§9.3을 바꿨다. WSL의 새 venv에서 CI 단계를 먼저 재현했다: 린트 통과, 342 passed / skip 0, 훅 25 passed. `ANF_E2E_API_URL` 없이 돌리면 skip 검사가 종료 코드 1로 실패하는 것도 로컬에서 먼저 봤다.
4. **push에서 막힘.** `feature/ci`를 push하자 gh 토큰에 `workflow` 권한이 없어 거절됐다 (`refusing to allow an OAuth App to create or update workflow`). 워크플로 파일을 만들거나 고치는 push는 그 권한이 필요하다. 사용자가 기기 인증으로 권한을 추가해서 해결했다. 이 권한은 AC-06(c)에서 임시 브랜치의 워크플로를 바꿔 push할 때도 필요했다.
5. **실환경 검증 1회차.** 첫 run 42445326221이 success였고, real-env-verifier가 AC-01~AC-07을 판정했다. 결과는 PASS 7 / UNVERIFIED 1이고, 수정 사항은 없었다. 로컬 재현을 PASS로 세지 않고 Actions 실행만 근거로 삼는 원칙을 지켰다.
6. **2회차.** 사용자 요청으로 main 대상 PR #6을 열자 `pull_request` run 42446223916이 돌았다. 같은 검증자가 실행 기록으로 AC-01b를 PASS로 판정해 모든 기준이 PASS가 됐다.
7. **사람이 내린 결정.** 범위, 린트 도구, 러너 OS, 앞당기기 여부, 토큰 권한 추가, PR을 열 시점.

---

## 7. Interview Q&A

### Q1. Why does your CI treat skipped tests as failures?

**A.** Because pytest exits with code zero even when tests are skipped, so a skip can hide a real gap behind a green check. In my project, the live API end-to-end tests are skipped unless one environment variable is set. When I removed it on a temporary branch, the test step passed with 279 passed and 63 skipped, and the pipeline would have been green. So I added a step that reads the JUnit XML and fails if any test was skipped or none were collected. It also forces a decision later: when a test needs root or Docker, I must choose where it runs, instead of letting it quietly disappear.

### Q2. What does your CI run, and what can it not run?

**A.** It runs lint with ruff, the unit and API contract tests, and sixty-three live end-to-end tests where the tests start the API server themselves with uvicorn. It also runs the tests of my TDD hook. All of that needs no root and no Docker. What it cannot run yet is the data plane: btrfs volumes, NFS exports, and container mounts. Those need kernel modules and privileged mounts on a GitHub runner, and I have a spike, S3, to check whether that is possible. Until then, the CI status is marked partial, and I say so in the docs.

### Q3. How do you know your CI actually catches failures, and not just passes?

**A.** A green run proves very little, since an empty workflow is also green. So I made three temporary branches from the same commit and broke one thing in each: a failing assertion, an unused import, and the removal of the environment variable that enables the live tests. Each run failed at the step I expected: Test, Lint, and the skipped-test check, and later steps were skipped. I recorded the run IDs and deleted the branches. That gave me evidence for each failure path, not only the success path.

### Q4. Why did you keep ruff out of pyproject.toml?

**A.** In this project, a hash of the product code decides whether an earlier feature verification is still valid, and pyproject.toml is part of that hash. Adding ruff there would change the hash and invalidate the account and pool verification, even though runtime behavior is the same. So I install a pinned ruff version, 0.14.0, inside the CI lint step only. The trade-off is that developers must install ruff themselves to lint locally. If the verification process did not depend on that file, I would put ruff in the dev extras, which is the normal choice.

### Q5. Why do you install with the same commands as the setup docs instead of a plain pip install?

**A.** I wanted the CI to follow the documented setup exactly: create the virtual environment at the same path and run an editable install with the dev extras. If the documentation drifts from what really works, the CI breaks first. The TDD hook also looks for that virtual environment on Linux, so the hook tests run in the same environment as developers use. I pinned the runner to Ubuntu 24.04 and Python 3.12, matching my WSL setup, so a failure in CI should be reproducible locally.

### Q6. How would you handle flaky or environment-dependent tests in this pipeline?

**A.** For environment dependence, I make the dependency explicit rather than silent: a test that needs a condition is marked, and the skipped-test check forces me to run it somewhere or deselect it by marker on purpose. For flakiness, I have not measured it yet, since I have only two successful runs of the same commit, and I would say so honestly. My live tests wait for operations by polling the status URL with a timeout, which is the same client behavior the API contract describes. The next step would be repeating the suite many times and tracking failures before trusting it as a merge gate.

### Q7. Which limitations remain, and what would you do next?

**A.** Three things. First, branch protection is not enabled, so a red build does not block a merge yet. Second, concurrency cancellation and the job timeout were not tested. Third, I have only two successful runs, so flakiness is not measured. Next I would enable required checks on main and add the data-plane job once the runner spike passes. I would also switch ruff to GitHub-style output so failures show on the changed lines.

### Q8. Tell me about a problem you hit while setting this up.

**A.** My first push of the workflow was rejected because the GitHub token lacked the workflow scope, and GitHub refuses OAuth tokens that create or update workflow files without it. I did not work around it with another credential. I asked the owner to add the scope through device authentication, and then the push worked. Another smaller finding came during verification: the GitHub API returned empty step results for a few minutes after a failed run, so I re-fetched the full job logs later instead of trusting the first, incomplete response.

### Q9. Why did you build CI before the volume feature, if the plan put it later?

**A.** Two earlier pull requests had been merged without any automated check, and the next feature, volumes, changes shared code heavily. Catching a regression in the account and pool contracts at that point would have been expensive. The control-plane tests were already runnable on a plain runner, so the cost was low and the value was immediate. It is a reasoned change of order, and I recorded it in the progress notes. If I did it again, I would add CI right after the first feature.
