# CI (GitHub Actions: backend 작업과 data-plane 작업)

> CI는 "push와 PR마다 같은 절차로 설치, 린트, 테스트를 돌려 결과를 한 곳에 남기는 장치"다. 이 문서의 핵심은 네 가지다. (1) pytest는 skip이 있어도 종료 코드 0이라서, skip을 실패로 바꾸는 단계를 따로 둔다. (2) CI가 초록색이라는 사실만으로는 CI가 실패를 잡는다는 증거가 못 되므로, 일부러 깨뜨린 임시 브랜치 세 개로 확인했다. (3) 2부에서 data-plane 작업을 더했다. GitHub 호스트 러너에서 root로 실제 LVM, 볼륨마다의 knfsd 인스턴스, 클라이언트 컨테이너의 NFS 마운트, tc 한도를 쓰는 `dataplane` 테스트 113개를 두 조각으로 나눠 돌린다. (4) 그 작업을 준비하던 스파이크 S3가 개발 기기(WSL)에서는 보이지 않던 제품 결함을 찾았다. `/`가 shared인 보통의 Linux 호스트에서 storage agent가 볼륨·스냅샷 마운트를 두 벌씩 만들고 있었다(3.8). FR-11의 상태는 2부 검증(5.3)으로 정한다.

코드 인용 기준: 1부 절의 인용은 커밋 `3fd6511` (제품 코드 내용 해시 `f2b70558…`). 2부에서 더한 절(3.7~3.9, 4.1, 5.3)의 인용은 커밋 `5cb8b17` (제품 코드 내용 해시 `9a023d13…`)이고, 1부 절 안에서 고친 인용에는 `@5cb8b17`을 붙였다. `ci.yml`은 그 사이 대시보드(frontend 작업), 테스트 자동화(FR-10), 2부가 고쳐서 1부 인용의 줄 번호는 지금 파일과 어긋난다.

FR-11(CI)을 다룬다. 1부는 backend 작업(2026-11-07), 2부는 data-plane 작업(2026-11-10)이다. frontend 작업은 대시보드(FR-09) 사이클에서 더했고 `docs/concepts/dashboard.md` §3 (7)에 있다. 이 기능은 ANF 기능이 아니라 엔지니어링 장치다. PRD §8에서 FR-11은 조사(1단계)를 생략하는 FR이라 조사 브리프가 없고, 아래 1, 2절은 "해당 없음"이다. 사실의 근거는 설계 기록(1부 `_workspace/ci/02_main_design.md`, 2부 `_workspace/ci/02_main_design_dataplane.md`), 스파이크 S3(`_workspace/spikes/S3.md`), 진행 기록(`_workspace/ci/00_progress.md`), 검증 보고서(1부 `_workspace/ci/04_verifier_report.md`·`04_verifier_report_r2.md`, 2부 `04_verifier_report_dp.md`), 그리고 실제 워크플로 파일과 코드다. 브리프의 근거 표시([스펙], [녹화] 등)는 쓰지 않는다. 대신 GitHub Actions 실행 기록에서 직접 확인한 값에는 run ID를 붙였다. S3가 관찰이 아니라 추론으로 적은 것은 [추론]으로 남겼다.

---

## 1. ANF에서는

해당 없음. CI는 ANF의 기능이 아니다. 다만 이 공고(ANF 데이터 플레인 엔지니어)가 "Python 테스트 자동화, CI/CD"를 강조하므로, 이 프로젝트가 그 기술을 어떻게 쓰는지를 보여 주는 결과물이다 (PRD G4).

## 2. ONTAP에서는

해당 없음.

## 3. 이 프로젝트에서는

### 3.1 구조

```
push (모든 브랜치) ─────────┐
PR (main 대상) ─────────────┼─> GitHub Actions: 워크플로 ci (작업 셋이 나란히 돈다)
workflow_dispatch (손으로) ─┘
  backend    (모든 트리거) ubuntu-24.04, Python 3.12                    ← 1부, 3.2
    1. checkout, setup-python
    2. Install   : 문서의 WSL 설정 명령 그대로 (venv + pip install -e ".[dev]")
    3. Lint      : ruff 0.14.0 기본 규칙
    4. Test      : pytest (단위 + 계약 + 라이브 API e2e), JUnit XML 저장. dataplane 마커는 선택에서 뺀다
    5. Fail on skipped tests : 수집 0개, skip, 실패, 오류가 있으면 실패 (junit_gate.py)
    6. Hook tests: TDD 훅 자체의 테스트
    앞 단계가 실패하면 뒤 단계는 실행되지 않는다 (skipped)
  frontend   (모든 트리거) npm ci → 타입 검사 → Vitest → 빌드              ← FR-09, dashboard.md §3 (7)
  data-plane (main 대상 PR, main push, 손으로) matrix 두 조각이 각자의 VM에서  ← 2부, 3.7
    throughput : 처리량 데이터 파일 하나
    rest       : 그 파일을 뺀 나머지 dataplane 테스트 전부
    조각마다: checkout → setup-python → Install → Runner info → 준비 스크립트(sudo)
              → 실행기(sudo, 이 단계의 종료 코드가 판정) → ns 전파 기록 → 로그 수집 → artifact
              (뒤의 셋은 실패해도 돈다)
```

1부에서 만든 것은 backend 작업 하나였고, FR-11은 `partial`로 끝났다. 그때 만들지 않은 것과 지금 상태는 아래와 같다.

| 1부에서 안 만든 것 | 그때 이유 | 지금 |
| --- | --- | --- |
| frontend 작업 (타입 검사, 빌드, 단위 테스트) | 대시보드(FR-09)가 아직 없었다 | FR-09 사이클에서 더했다 (`docs/concepts/dashboard.md` §3 (7)) |
| data-plane 작업 (커널 모듈, storage agent, 통합·데이터 플레인 E2E) | 볼륨부터 생긴다. GitHub 호스트 러너에서 커널 모듈을 로드하고 privileged 컨테이너로 마운트할 수 있는지를 스파이크 S3로 먼저 확인해야 했다 (ADR §10) | 2부에서 더했다. S3가 호스트 러너에서 된다는 것을 확인했다 (3.7) |
| 브랜치 보호 (main merge 전에 CI 통과 필수) | 저장소 설정이라 사용자가 정할 일이다 | 아직 켜지 않았다. 2부 설계도 범위 밖으로 두고 제안만 한다 |

### 3.2 코드 따라가기: backend 작업 (`.github/workflows/ci.yml`, `3fd6511`)

**트리거와 권한 (`ci.yml:5-15`)**
- `on.push`에 필터가 없어서 모든 브랜치의 push에 돈다 (`ci.yml:6`). `pull_request`는 `branches: [main]`이라 main을 향한 PR에만 돈다 (`ci.yml:7-8`). push만 해도 결과를 볼 수 있어야 PR 전에 고칠 수 있다.
- 2부에서 워크플로 수준 트리거 `workflow_dispatch`를 더했다 (`ci.yml:10 @5cb8b17`). 손으로 돌리면 backend·frontend 작업도 함께 돈다 (2부 설계 §6.5).
- `permissions: contents: read` (`ci.yml:10-11`)는 최소 권한이다. 성공 run 로그에 `Contents: read, Metadata: read`만 찍혔다 (보고서 AC-01a).
- `concurrency`로 같은 ref의 이전 실행은 취소한다 (`ci.yml:13-15`). 연속 push에서 낡은 커밋의 결과를 기다리지 않으려는 것이다. 이 동작은 수락 기준이 아니라서 실제로 취소되는지 시험하지 않았다. 2부에서는 이 규칙이 data-plane 작업에도 걸린다 (3.7, 4.1).

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
- 1부 뒤에 바뀐 것: 볼륨 기능부터 root·LVM·knfsd가 필요한 테스트에 `dataplane` 마커를 붙였고, 지금 이 단계는 `python -m pytest -m "not dataplane" --junitxml=pytest-results.xml`이다 (`ci.yml:45-48 @5cb8b17`). 대상은 989개다 (`docs/testing.md` §1). 빠진 113개는 data-plane 작업이 돌린다 (3.7).

**Fail on skipped tests (`ci.yml:47-60`)**
- 이 단계가 이 워크플로의 핵심 설계다. 아래 3.3에서 자세히 설명한다. 코드는 JUnit XML의 루트에서 `tests`와 `skipped` 속성을 읽어 (`ci.yml:54-56`), 수집된 테스트가 0개이거나 skip이 하나라도 있으면 `sys.exit(메시지)`로 종료 코드 1을 낸다 (`ci.yml:58-59`). `tests == 0` 검사는 "테스트가 하나도 안 돌았는데 초록색"이라는 또 다른 조용한 실패를 막는다.
- `ci.yml:55`는 XML의 두 가지 모양을 받는다. 지금 pytest(로컬 9.2.0으로 확인)는 루트를 `<testsuites>`로 쓰고 그 안에 `<testsuite>`를 두므로, 평소에는 `root.find("testsuite")`로 내려간다. 루트가 바로 `<testsuite>`인 옛 모양도 받도록 둔 것은 방어다.
- 이 인라인 검사는 FR-10에서 데이터 플레인 실행기와 함께 쓰는 `python backend/tests/junit_gate.py pytest-results.xml` 한 줄로 바뀌었다 (`ci.yml:52-53 @5cb8b17`). 새 스크립트는 실패·오류와 읽을 수 없는 XML도 본다. 바뀐 점은 `docs/concepts/test-automation.md` 3.3에 있다.

**Hook tests (`ci.yml:62-63`)**
- `python -m pytest .claude/hooks/tests`. TDD 훅(`tdd_guard.py`)은 이 프로젝트의 개발 도구이고 자체 테스트가 25개 있다. 기본 `testpaths`에는 들어 있지 않으므로(약 25초 걸리는 Windows 기준) 따로 돌려야 한다. CI의 Linux에서는 약 7초에 끝났다. 마지막 단계라서 앞 단계(린트, 테스트, skip 검사) 중 하나가 실패하면 실행되지 않는다. AC-06의 세 run에서 실제로 `skipped`였다.

### 3.3 왜 skip을 실패로 보는가

pytest는 skip이 있어도 종료 코드 0으로 끝난다. 이 프로젝트의 e2e 63개는 `ANF_E2E_API_URL`이 없으면 조건부 skip이다. 누군가 워크플로에서 그 환경 변수 두 줄을 지우면(또는 오타를 내면) 테스트 63개가 조용히 건너뛰어지고, CI는 초록색으로 남는다. 가장 중요한 "실제 서버에 붙어 계약을 확인하는" 테스트가 빠졌는데도 아무도 모른다.

검증 run 42445712865가 이를 그대로 보여 준다. 같은 커밋에서 환경 변수만 뺐더니:
- Test 단계는 `279 passed, 63 skipped`로 **성공**했다.
- 다음 단계 Fail on skipped tests가 `collected 342, skipped 63`을 찍고 종료 코드 1로 **실패**시켰다.

이 규칙은 ADR §9.1의 "건너뛴 테스트를 통과로 보고하지 않는다"(TDD 훅의 SKIPPED도 같은 원칙)를 CI에까지 확장한 것이다.

미래에 대한 효과도 있었다. 1부를 쓸 때 "root, 커널 모듈, Docker가 필요한 통합·E2E 테스트가 생기면 GitHub 러너에서는 그 테스트가 skip되므로 이 검사가 실패하고, 사람이 '이 테스트를 어디서 돌릴 것인가'를 명시적으로 정해야 한다"고 예상했다. 실제로 그렇게 됐고, 결국 두 길을 다 썼다. backend 작업은 그 테스트를 `dataplane` 마커로 **선택에서 뺀다**(`-m "not dataplane"`). 이것은 skip이 아니다. deselect된 테스트는 XML의 `tests`에 들어가지 않으므로 게이트가 실패로 보지 않는다(`docs/concepts/test-automation.md` 3.3). 그리고 2부의 data-plane 작업이 그 테스트를 러너에서 실제로 돌린다. skip이 조용히 쌓이는 길이 막혔다.

### 3.4 CI의 AC-07과 해시: 앞 커밋과의 연결

CI 작업의 수락 기준 AC-07은 "CI를 추가한 뒤에도 제품 코드가 그대로다"였다. 제품 코드 판정은 계정·풀의 검증에 쓰인 코드와 같은 코드인지로 정한다. 이 비교에는 내용 해시를 쓰는데, 같은 브랜치의 앞 커밋 `e4acc7a`에서 이 절차를 줄 끝(CRLF/LF)에 무관하게 바꿨다 (`.claude/skills/anf-feature-cycle/SKILL.md` 3단계 4번). 명령에 `tr -d '\r'`이 들어 있어서 Windows 작업 트리와 Linux 커밋이 같은 값을 낸다. 해시 대상은 `pyproject.toml`과 `backend/`에서 `backend/tests/`를 뺀 파일이다. 그래서 위의 ruff 결정(dev 의존성에 넣지 않음)과 F841 수정(테스트 파일만 변경)이 모두 이 해시를 건드리지 않는다. 검증에서 커밋 `41f863d`와 `3fd6511`의 해시가 모두 `f2b70558…`로 같았다.

### 3.5 라이브 API e2e를 backend 작업에서 돌릴 수 있는 이유

- 라이브 e2e가 CI에서 도는 것은 테스트가 anf-api를 직접 `subprocess.Popen`으로 uvicorn 프로세스로 띄우기 때문이다 (`backend/tests/e2e/live_api.py:246-250`). 이 컨트롤 플레인 테스트에는 root, 커널 모듈, Docker가 필요 없다. `ANF_E2E_API_URL`은 서버를 어디에 띄울지 알려 주는 주소일 뿐이다.
- 이 테스트들은 상태 전이, LRO 폴링, 재시작 복구(서버를 SIGKILL하고 같은 DB로 다시 띄움)를 실제 HTTP로 확인한다. 단위·계약 테스트가 가짜로 대체하는 부분을 PR마다 실제 서버로 한 번 더 확인하는 층이다 (ADR §9.1 "E2E (컨트롤 플레인)").
- 반면 데이터 플레인(씬 LV와 ext4, 볼륨마다의 knfsd 인스턴스, 클라이언트 컨테이너의 마운트, tc 한도)은 root, 커널 모듈, privileged 컨테이너가 필요하다. 1부 때는 호스트 러너에서 이것이 되는지 몰랐고, S3가 실패하면 데이터 플레인 테스트는 로컬이나 self-hosted 러너에서만 돌리고 그 사실을 문서에 적기로 했었다 (ADR §10). S3가 조건부 통과해서 data-plane 작업이 호스트 러너에서 돈다 (3.7).

### 3.6 설계 결정 (1부, backend 작업)

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

### 3.7 data-plane 작업 (2부)

data-plane 작업은 FR-10의 실행기 `scripts/run-dataplane-tests.sh`를 러너에서 sudo로 부르는 얇은 작업이다. 실행기가 하는 일(사전 점검, VG 붙이기, 파일마다 pytest와 그 사이의 `drop_caches`, 남은 것 검사, `junit_gate.py` 판정)은 `docs/concepts/test-automation.md` 3.2~3.3에 있으므로 여기서 되풀이하지 않는다. 여기서는 워크플로가 더한 것과 그 이유만 설명한다.

#### 왜 GitHub 호스트 러너에서 커널 수준 테스트가 되는가 (S3)

- **job마다 새로 뜨는 VM이다.** S3에서 하이퍼바이저는 Microsoft였고, 2회차의 두 job은 서로 다른 VM에서 동시에 돌았다. 테스트가 그 VM의 커널을 직접 쓰므로 `modprobe`, loop 장치 위의 VG와 씬 풀, privileged 컨테이너 안의 knfsd가 모두 동작했다.
- **sudo가 있다.** job 사용자 `runner`는 `(ALL) NOPASSWD: ALL`이다. 묻지 않는 sudo로 준비 스크립트와 실행기를 root로 부를 수 있다.
- **필요한 것이 이미지에 이미 있다.** 커널 `7.0.0-1017-azure`의 기본 `linux-modules`에 `nfsd`, `dm_thin_pool`, `ifb`, `sch_htb`, `act_mirred`, `cls_matchall`, `sch_fq_codel`, `sch_ingress`, `nfs`, `nfsv3`, `nfsv4`가 있다(`linux-modules-extra`는 필요 없다). `lvm2`, `thin-provisioning-tools`, `e2fsprogs`, `iptables`, `util-linux`, `iproute2`, `python3-venv`, Docker Engine 28.0.4도 설치돼 있다. `nfs-kernel-server`는 없지만 필요 없었다(knfsd는 인스턴스 이미지 안에서 띄운다). NFS LOCALIO가 커널에 없어서 같은 VM의 클라이언트 컨테이너도 네트워크 RPC로 읽고 쓰고, 그래서 tc 한도가 데이터 I/O에 걸린다 (R-08의 우려 없음).
- **자원이 넉넉하다.** 4 vCPU, 메모리 약 16 GB(WSL의 두 배), 디스크 여유 86 GB. 전체 묶음 동안 메모리 used는 최대 1,360 MiB였다.
- 그래서 **self-hosted 러너가 필요 없었다.** S3가 실패했다면 ADR §10의 대안은 "데이터 플레인 테스트는 로컬(또는 self-hosted 러너)에서만"이었다.
- 덤이 하나 있다. 조각마다 VM이 따로라 데이터 플레인(VG `anf`, `anf-vnet`, 포트 8080·8090)도 조각마다 따로다. WSL에서는 데이터 플레인이 기기에 하나라 한 번에 한 실행만 돌릴 수 있지만, 러너에서는 두 조각이 서로 영향 없이 동시에 돈다(S3 2회차의 두 job이 같은 시간에 끝났다).

#### 코드 따라가기 (`.github/workflows/ci.yml:86-155`)

**트리거 (`ci.yml:89-90`)**
- `if: github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch' || github.ref == 'refs/heads/main'`. `pull_request`는 워크플로 수준에서 `branches: [main]`이므로(`ci.yml:8-9`) main 대상 PR만이다. push는 ref가 main일 때만 남는다.
- **기능 브랜치 push에서 돌지 않는 이유 (결정 5).** 기능 브랜치에 PR이 열려 있으면 push 한 번에 push 실행과 PR 실행이 함께 생겨, 같은 약 37분 작업이 두 번 돈다. merge 전 확인은 PR 실행(merge 결과를 체크아웃한다, 5절)이, merge 뒤 상태는 main push 실행이 맡는다. PRD §9의 성공 기준이 "`main` 브랜치의 CI가 통과 상태"다.
- backend·frontend 작업은 그대로 모든 push에서 돈다 (결정 5). `workflow_dispatch`는 워크플로 수준 트리거라, 손으로 돌리면 그 두 작업도 함께 돈다 (설계 §6.5).

**러너, 제한 시간, matrix (`ci.yml:91-104`)**
- `runs-on: ubuntu-24.04`, `timeout-minutes: 75` (`:91-92`). 가장 긴 조각이 약 37분이라 두 배를 넘기면 멈춘 것으로 본다 (결정 7). 스파이크 때는 180분이었다.
- `fail-fast: false` (`:94`). 한 조각이 실패해도 다른 조각을 끝까지 돌려 그 결과를 본다 (결정 7).
- `include` 두 항목 (`:98-102`). `throughput`의 `args`는 `backend/tests/e2e/test_throughput_limit_data_live.py`, `rest`의 `args`는 `--ignore=backend/tests/e2e/test_throughput_limit_data_live.py`다.
  - **왜 둘로 나누나 (결정 3).** S3에서 처리량 데이터 파일 하나가 2,141 s(35.7분)로 전체의 49%였고, 나머지 12개 파일이 2,227 s(37.1분)였다. 그래서 둘로 나누면 길이가 거의 같아지고 기다리는 시간이 반이 된다. 처리량 시험은 한도가 걸린 채로 실제 데이터를 흘려 재므로 줄일 수 없다 (`docs/testing.md` §3). 파일마다 조각(13개)을 만들면 준비와 로그가 13번이고, 가장 긴 조각은 여전히 그 파일이라 얻는 것이 없다. PR에서 처리량을 빼고 main에서만 전체를 돌리면 FR-08의 효과가 merge 전에 확인되지 않는다. 저장소가 public이라 러너 시간은 무료다.
  - **왜 `rest`를 `--ignore=`로 고르나 (결정 4).** 12개 파일을 나열하면, 새 데이터 플레인 테스트 파일이 생겼을 때 목록에 넣는 것을 잊은 파일이 조용히 CI 밖에 남는다. "처리량 데이터 파일을 뺀 전부"로 고르면 새 파일이 저절로 `rest`에 들어간다.
  - **실행기는 고치지 않았다 (설계 §6.1).** 실행기는 `-`로 시작하는 인자를 pytest 옵션으로 본다 (`scripts/run-dataplane-tests.sh:77-83`). `rest`에는 경로 인자가 없으므로 기본 대상(통합 + e2e 폴더, `:84`)에서 수집할 때(`:87`)와 파일마다 돌 때(`:115`) 그 옵션을 그대로 넘긴다. 값이 경로인 옵션은 `=`로 붙여 써야 한다. 따로 쓰면 실행기가 값을 경로로 읽는다 (`docs/testing.md` §3). implementer가 WSL에서 실행기의 수집 부분을 그대로 돌려 확인한 결과는 `rest` 12개 파일 106개, `throughput` 1개 파일 7개, 합 13개 파일 113개로, 인자 없는 수집과 같았다.
- `env: OUT: /var/tmp/anf-clone-tests/${{ matrix.shard }}` (`:103-104`)는 실행기의 출력 폴더(`ANF_TEST_OUT`)다.

**단계 (`ci.yml:106-155`).** S3에서 그대로 통과한 단계만 둔다 (결정 6).
1. **checkout, setup-python 3.12** (`:106-110`).
2. **Install** (`:113-116`). backend와 같은 `~/.venvs/anf-clone`이다. backend와 달리 `GITHUB_PATH`에 넣지 않는다. 뒤의 단계가 venv의 `python`을 직접 부르지 않고, 실행기가 저장소 주인(`runner`)의 집 폴더에서 venv를 찾기 때문이다 (`scripts/run-dataplane-tests.sh:32-34`). S3에서 `ANF_CLONE_VENV`, `ANF_E2E_USER`를 줄 필요가 없었다. sudo는 환경을 초기화하지만(`HOME=/root`, setup-python이 내보낸 `LD_LIBRARY_PATH` 없음) `sudo ~/.venvs/anf-clone/bin/python`은 돌았다 (S3 Q3).
3. **Runner info** (`:119-123`). 이미지(`$ImageOS $ImageVersion`), `uname -r`, `/`의 전파(`findmnt -no PROPAGATION /`)를 남긴다. 러너 이미지가 바뀌면 커널도 바뀌므로 회귀 원인을 가르려는 기록이다. `/`가 `shared`로 찍히는 것이 "ns를 손대지 않은 그대로의 러너에서 통과했다"(AC-02)의 근거다.
4. **Set up the data plane** (`:126-127`). `sudo bash scripts/setup-wsl-dataplane.sh`. WSL과 같은 스크립트이고, S3에서 고치지 않고 6~8 s에 끝났다(모듈 로드, 이미지 두 개 빌드, `anf-vnet`, `fs.leases-enable = 0`). 이름은 WSL이지만 바꾸지 않았다 (결정 10). 개명은 문서·스킬·기록 수십 곳을 건드리므로, 머리 주석에 "Ubuntu 24.04 호스트(GitHub 호스트 러너 포함)에서도 그대로 쓴다"만 더했다 (`scripts/setup-wsl-dataplane.sh:4`).
   - 모듈·패키지를 설치하는 단계는 없다. 이미지가 바뀌어 무언가 빠지면 준비 스크립트(`:17-22`, 없는 명령과 설치할 패키지를 말한다)나 실행기의 사전 점검(종료 코드 2)이 원인을 말하며 실패한다.
   - ns를 private로 만드는 단계도 없다. S3의 `private` job에는 있었지만, 지금은 agent가 스스로 한다 (3.8). 워크플로에 남겨 두면 제품 수정이 동작하는지를 가린다.
5. **Data-plane tests** (`:130-131`). `sudo env ANF_TEST_OUT="$OUT" bash scripts/run-dataplane-tests.sh ${{ matrix.args }}`. sudo가 환경을 지우므로 출력 폴더는 `env`로 넘긴다. **판정은 이 단계의 종료 코드 하나다 (결정 8).** 0은 수집 1개 이상·전부 통과·skip 0·남은 것 없음, 1은 실패·오류·skip·수집 0개·남은 것, 2는 사전 점검 실패다. 실행기가 이미 `junit_gate.py`를 부르므로(`scripts/run-dataplane-tests.sh:142`) 워크플로에서 한 번 더 부르지 않았다. 두 번 부르면 판정 경로가 둘이 된다.
6. **Mount propagation of ns** (`:134-138`, `if: always()`). `findmnt --mountpoint /var/lib/anf-clone/ns`와 `/proc/self/mountinfo`의 `/`·ns 줄(peer group 번호 `shared:N`)을 남긴다. ns의 번호가 `/`의 번호와 다르면 3.8의 수정이 러너에서 동작한 것이다. 이 단계를 테스트 **뒤**에 둔 이유(설계 §6.3): 테스트 전에 남기려면 워크플로가 agent보다 먼저 제품 함수를 불러 바인드를 만들어야 하는데, 그러면 "agent가 바인드를 만드는 그대로의 조건"(AC-02)이 흐려진다. agent는 끝날 때 ns 바인드를 풀지 않으므로 테스트 뒤에도 보인다.
7. **Collect logs** (`:141-146`, `if: always()`). `sudo dmesg -T`를 `dmesg.txt`로 더하고(러너는 `kernel.dmesg_restrict = 1`이라 sudo가 필요하다), `chmod -R a+rX`로 읽기 권한을 연다. 실행기 출력은 root 소유라 열지 않으면 올리지 못한다 (S3 Q8). `mkdir -p "$OUT"`가 있어서, 사전 점검이 실패해 실행기가 출력 폴더를 만들지 않았을 때도 dmesg는 남는다.
8. **Upload logs** (`:148-155`, `if: always()`). artifact 이름은 `dataplane-<조각>-<run_attempt>`이다. 시도 번호를 넣어 다시 돌린 시도와 이름이 겹치지 않게 했다(S3와 같음). `retention-days: 14`, `if-no-files-found: warn`. 올리는 것은 실행기 출력 폴더(파일별 `.log`·`.xml`·`.jsonl`, `collect.log`, `baseline.txt`, `files.tsv`, `summary.txt`)와 `dmesg.txt`뿐이다. S3가 올린 pytest tmp의 agent 로그는 올리지 않는다 (설계 §6.4). S3에서 전체 묶음의 압축본은 약 0.5 MB, 업로드는 2 s였다.

**`concurrency`는 그대로다 (`ci.yml:15-17`).** `ci-${{ github.ref }}`, `cancel-in-progress: true`. main에 연달아 merge하면 앞 main push 실행의 data-plane 작업이 취소되고 마지막 것만 끝까지 돈다 (설계 §6.6). 열린 PR에 문서만 고친 커밋을 push해도 두 조각이 처음부터 다시 돈다 (`CLAUDE.md` CI). 그래서 2부 검증 중에는 메인 세션이 ADR·`CLAUDE.md` 커밋(`932cdc8`)의 push를 판정 뒤로 미뤘다. 러너 실행을 취소하지 않으려는 것이다 (진행 기록).

### 3.8 CI가 찾은 제품 결함: ns의 마운트 전파

S3 2회차가 찾은 것이고, 이 문서에서 면접에 가장 쓸 만한 이야기다. "CI를 붙이다가, 개발 기기에서는 생기지 않는 제품 결함을 찾았다."

#### 배경: agent는 왜 ns를 공유 마운트로 만드나

- 볼륨은 호스트의 `/var/lib/anf-clone/ns/<creationToken>`에 마운트되고, 스냅샷은 그 아래 `.snapshot/<이름>`에 마운트된다. 볼륨마다의 NFS 인스턴스(컨테이너)는 ns를 `/export`로 바인드하는데, `bind-propagation=rslave`다 (`backend/storage_agent/nfs_instance.py:163` `start`). 그래야 인스턴스가 뜬 뒤 호스트에서 하는 마운트(새 스냅샷 등)가 인스턴스 안에도 보인다.
- docstring대로 WSL의 `/`는 private 마운트라 이 rslave 바인드가 그대로는 거절된다. 그래서 agent는 시작할 때(`backend/storage_agent/flexvol.py:171` `recover`) `ensure_shared_ns()`로 ns를 자기 자신에 바인드하고 rshared로 만든다 (`nfs_instance.py:101-112`, docstring `:102-106`). ADR D-12의 "ns를 rshared 마운트로"가 이것이다.

#### 개념: private, shared, peer group, slave

리눅스 마운트에는 전파 유형(propagation type)이 있다. 이 결함을 설명하는 데 필요한 것만 적는다. 아래 S3 탐침의 mountinfo가 이 동작을 그대로 보여 준다.
- **private**: 이 마운트 아래에서 일어난 마운트·언마운트가 다른 곳으로 퍼지지 않고, 다른 곳의 것도 받지 않는다.
- **shared**: 같은 **peer group**에 든 마운트들이 그 아래에서 일어난 마운트·언마운트를 서로 복제한다. peer group 번호는 `/proc/self/mountinfo`의 `shared:N`이다. `findmnt -o PROPAGATION`은 `shared`, `private`처럼 유형만 보여 주고 어느 group인지는 보여 주지 않는다.
- **slave**: 한쪽(master)에서 일어난 것을 받기만 하고 되돌려 보내지 않는다. 인스턴스의 `/export`(rslave)가 이것이다. 앞의 r(recursive)은 그 아래 마운트 전체에 같은 유형을 준다는 뜻이다.
- shared 마운트 안의 디렉터리를 바인드하면 새 바인드는 원본과 같은 peer group에 들어간다.

#### 무엇이 일어났나 (S3 2회차, run 42785777318)

- 러너의 `/`는 systemd 기본값대로 shared다 (`/ shared`). 옛 `ensure_shared_ns()`는 ns를 자기 자신에 바인드한 뒤 "shared가 아니면" `--make-rshared`를 했다 (설계 §2). 러너에서는 새 바인드가 `/`의 peer group을 물려받아 이미 `shared`로 보였으므로 rshared를 건너뛰었다.
- S3는 테스트 전에 ns 아래에 tmpfs 하나(`probe`)를 마운트하고 호스트 마운트 표를 봤다. ns를 그대로 둔 `as-is` job(job 129726474089)의 출력이다. mountinfo의 첫 두 칸은 마운트 ID와 부모 마운트 ID다.

```
28 1 259:1 / / rw,relatime shared:1 - ext4 /dev/root ...
265 28 259:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns rw,relatime shared:1 - ext4 /dev/root ...
probe entries in host mount table: 2
277 265 0:50 / /var/lib/anf-clone/ns/probe rw,relatime shared:328 - tmpfs probe rw,inode64
278 28 0:50 / /var/lib/anf-clone/ns/probe rw,relatime shared:328 - tmpfs probe rw,inode64
probe entries after one umount: 0
```

  agent 방식의 자기 바인드(265)가 `/`(28)와 같은 `shared:1`에 들어갔다. 그래서 ns 아래에 마운트를 하나 하면 커널이 peer인 `/`에도 같은 마운트를 복제한다. 277은 ns 바인드 아래(보이는 쪽)에, 278은 `/` 아래의 같은 경로, 즉 ns 바인드에 가려진 원래 디렉터리 위에 생겼다. 둘은 서로 peer(`shared:328`)라 한 번의 umount로 둘 다 사라진다.
- agent보다 먼저 워크플로 단계로 `mount --bind ns ns && mount --make-private ns && mount --make-rshared ns`를 한 `private` job(job 129726473812)에서는 ns 바인드가 자기 group을 받았고 탐침이 한 줄이었다.

```
28 1 8:1 / / rw,relatime shared:1 - ext4 /dev/root ...
62 28 8:1 /var/lib/anf-clone/ns /var/lib/anf-clone/ns rw,relatime shared:328 - ext4 /dev/root ...
probe entries in host mount table: 1
```

- 결과: `as-is`는 105 통과 / 8 실패 / skip 0(4,372 s, 실행기 exit 1), `private`는 113 / 0 / 0(4,378 s, exit 0)이었다. 실패 8개는 모두 같은 종류다. 스냅샷 마운트 경로가 호스트 마운트 표(`findmnt -rn -o TARGET`)에 두 번 나와, 그것을 한 벌짜리 목록과 비교하는 단언이 깨졌다 (`backend/tests/e2e/snapshot_live.py:143` `snap_mounts`). 파일별로는 새 볼륨 데이터 3개, 스냅샷 데이터 2개, 되돌리기 데이터 2개, 스냅샷 계약 1개다.
- 클라이언트가 보는 것은 같았다. 실패한 테스트에서도 실패한 줄 앞의 단언(내용, 읽기 전용, 클라이언트 보기, LV, export, 작업 상태)은 통과했고, 두 벌을 세지 않는 테스트(스냅샷 복구, 되돌리기 계약, 볼륨 삭제)는 `as-is`에서도 통과했다. 그래도 결함인 이유는 셋이다 (설계 §2). 호스트 마운트 표가 볼륨·스냅샷 수의 두 배가 되고, "한 번 언마운트하면 사라진다"가 peer group 전파에 기대게 되고, 클론이 WSL에서만 맞게 도는 것은 NFR-03(재현성)과 어긋난다.
- 이것은 러너만의 문제가 아니다. systemd를 쓰는 보통의 Linux 호스트는 `/`가 shared이므로, WSL 밖에서는 agent가 볼륨·스냅샷 마운트를 호스트 마운트 네임스페이스에 두 벌씩 만들었을 것이다 [추론, S3].

#### 왜 WSL에서는 안 보였나

WSL의 `/`는 private이다 (`ensure_shared_ns` docstring). private 마운트 안의 바인드는 peer group이 없고, 뒤의 `--make-rshared`가 새 peer group을 만든다. 그래서 WSL에서는 처음부터 S3의 `private` job과 같은 상태였다 [추론: S3는 이것을 docstring과 WSL에서 실패가 없던 것으로 판단했다]. 같은 코드와 같은 테스트가 개발 기기에서는 매번 통과했고, `/`가 shared인 호스트에서 처음 돌린 CI가 차이를 드러냈다. 그리고 위 두 job 모두 `findmnt -o TARGET,PROPAGATION`은 ns를 `shared`로만 보여 줬다. 전파 유형만 보는 옛 검사로는 "자기 group"과 "`/`의 group"을 구별할 수 없었다.

#### 고친 방법 (`backend/storage_agent/nfs_instance.py:101-112` `ensure_shared_ns`, 커밋 `691d93f`)

```python
result = self._run(["findmnt", "-no", "PROPAGATION", "--mountpoint", str(self._ns)], check=False)
if result.returncode != 0:
    self._run(["mount", "--bind", str(self._ns), str(self._ns)])
    self._run(["mount", "--make-private", str(self._ns)])
if "shared" not in result.stdout.strip().split(","):
    self._run(["mount", "--make-rshared", str(self._ns)])
```

- `:107`: ns가 이미 마운트 지점인지, 전파 유형이 무엇인지 본다. 마운트 지점이 아니면 `findmnt`가 0이 아닌 코드로 끝난다.
- `:108-110`: 바인드를 **새로 만들었을 때만** `--make-private`로 `/`의 peer group에서 떼어 낸다.
- `:111-112`: 판정은 바인드 **전**에 본 `result`로 한다. 새 바인드는 그때 stdout이 비어 있었으므로 반드시 `--make-rshared`를 거치고, 이 rshared가 자기 peer group을 새로 준다. 순서는 bind → private → rshared이고, S3의 `private` job이 정확히 이 상태로 113개를 통과했다.
- 이미 마운트 지점이면 전과 같다. private면 rshared, shared면 아무것도 하지 않는다 (설계 §6.2). WSL에서는 결과 상태가 같다. 원래 일어나던 private → rshared 전이 앞에 private 단계 하나가 붙었을 뿐이다 (결정 2).
- ADR D-12("ns를 rshared 마운트로")는 그대로다. rshared이되 자기 peer group이다 (결정 1).

**단위 테스트 (`backend/tests/unit/test_nfs_instance.py:396-427`).** 가짜 실행기로 명령 순서를 본다.
- `test_shared_ns_from_plain_directory` (`:399-405`): WSL 경우. 마운트 지점이 아니면 bind → private → rshared.
- `test_shared_ns_new_bind_leaves_the_peer_group_of_a_shared_root` (`:408-415`): 러너 경우. 가짜 `findmnt`가 첫 호출에는 "마운트 지점 아님"을, 그 뒤 호출에는 `shared`를 답한다 (`runner.sequence`, `:411`). 바인드 직후 다시 검사해 "이미 shared"로 보고 건너뛰는 옛 동작이 돌아오면 이 테스트가 깨진다. 기대하는 마운트 명령은 위와 같은 세 개다.
- `test_shared_ns_private_mount_is_made_shared` (`:418-421`), `test_shared_ns_already_shared` (`:424-427`): 이미 마운트 지점인 두 경우. 동작이 바뀌지 않았다.

#### 버린 대안 (결정 1)

| 대안 | 버린 이유 |
| --- | --- |
| CI 워크플로 단계에서만 ns를 private로 만든다 (S3 `private` job 그대로, 한 줄) | CI만 다르게 돈다. CI가 WSL을 흉내 내는 셈이라 제품을 검증하지 못하고, 다른 Linux 호스트에서는 두 벌 마운트가 그대로 남는다 |
| 테스트 도우미 `snap_mounts()`가 중복을 지운다 | 함수 하나만 바꾸면 되지만, 테스트가 결함을 덮고 제품의 두 벌 마운트는 남는다 |
| **채택: 제품의 `ensure_shared_ns()`를 고친다** | 결함은 러너가 아니라 "`/`가 shared인 Linux"에서 생긴다. 바꿀 곳이 storage agent 함수 하나다 |

대가는 제품 코드가 바뀐 것이다. 제품 코드 내용 해시가 `f99bc5cf…`에서 `9a023d13…`로 바뀌었다. 그래서 FR-04~FR-08을 기능별로 다시 검증하는 대신 데이터 플레인 묶음 전체를 회귀로 본다 (결정 2). WSL에서 실행기 전체 1회, 그리고 러너의 data-plane 작업이다. 묶음 113개가 FR-04~FR-08의 수락 기준을 모두 덮는다 (`docs/testing.md` §4 대응표).

#### 범위 밖: 이미 `/`와 같은 peer group으로 바인드된 호스트

고친 코드는 바인드를 새로 만들 때만 private로 떼어 낸다. 옛 agent가 이미 `/`의 peer group으로 바인드해 둔 호스트는 자동으로 고치지 않는다 (설계 §3, §6.2). WSL은 해당이 없고 러너는 매번 새 VM이기 때문이다. 그런 호스트는 재부팅하거나 바인드를 풀면 된다.

### 3.9 설계 결정 (2부, data-plane 작업)

2부의 결정은 모두 `anf-roadmap` 총괄의 자동 채택이다 (설계 §4).

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 1. ns 전파는 제품에서 고친다 (새 바인드에 `--make-private` 뒤 `--make-rshared`) | 워크플로 단계에서만 private, 테스트가 중복을 지움 | 3.8 |
| 2. 회귀는 전체 묶음으로 본다: WSL 실행기 전체 1회 + 러너의 data-plane 작업. FR-04~FR-08의 `done`은 유지하고 회귀 근거를 더한다 | 기능별 재검증 5회, `done` 해제 | 바뀌는 것은 ns 바인드 직후의 전파 설정이고 WSL에서는 결과 상태가 같다. 113개가 FR-04~FR-08의 수락 기준을 모두 덮는다. 앞 사이클들도 공용 코드 변경을 회귀 AC로 다뤘다(스냅샷 AC-14, 처리량 AC-12) |
| 3. matrix 두 조각 `throughput`·`rest`, 조각마다 자기 VM에서 준비부터 | 한 작업으로 전체(약 75분), 파일마다 조각(13개), PR에서는 처리량을 빼고 main에서만 전체 | 처리량 데이터 파일이 전체의 49%라 둘로 나누면 길이가 비슷하다. 13조각은 준비·로그만 늘고 가장 긴 조각은 그대로다. PR에서 빼면 FR-08의 효과가 merge 전에 확인되지 않는다 |
| 4. `rest`는 `--ignore=`로 "처리량 데이터 파일을 뺀 전부" | 12개 파일 나열 | 새 파일이 저절로 들어간다. 나열하면 빠뜨린 파일이 조용히 CI 밖에 남는다 |
| 5. 트리거는 main 대상 PR, main push, `workflow_dispatch` | 모든 브랜치 push | 기능 브랜치는 push와 PR이 겹쳐 같은 작업이 두 번 돈다 |
| 6. 단계는 S3에서 그대로 통과한 것만. 모듈·패키지 설치, ns private 단계 없음 | `apt-get install` 단계, ns private 단계 | 필요한 것이 이미지에 있었다. 빠지면 준비 스크립트나 사전 점검이 원인을 말한다. ns 단계는 제품 수정을 가린다 |
| 7. 조각마다 `timeout-minutes: 75`, `fail-fast: false` | 기본 360분, fail-fast | 가장 긴 조각이 약 37분이라 두 배를 넘기면 멈춘 것이다. 한 조각이 실패해도 다른 조각의 결과를 본다 |
| 8. 판정은 실행기의 종료 코드 하나 | 워크플로에서 `junit_gate.py`를 한 번 더 부름 | 실행기가 이미 같은 게이트를 부른다. 두 번 부르면 판정 경로가 둘이 된다 |
| 9. 러너 커널(7.0)과 WSL 커널(6.18)의 차이는 그대로 둔다 | 커널 고정, 컨테이너 안에서 실행 | 호스트 러너의 커널은 고를 수 없다. S3에서 두 커널 모두 113개가 통과했고(러너는 `private` 조건), 처리량 비율도 범위 안이었다(러너 0.9946~1.0016, WSL 0.990~0.997). 다른 커널에서도 도는 것은 약점이 아니라 근거다 |
| 10. 준비 스크립트 이름 `setup-wsl-dataplane.sh`는 그대로 | `setup-dataplane.sh`로 개명 | 개명은 문서·스킬·기록 수십 곳을 건드린다. 머리 주석만 더했다 |

## 4. ADR §9.3의 원래 계획과 달라진 점

"실제 ANF와 다른 점"은 해당 없음이다. 대신 ADR §9.3이 처음 계획한 CI와 실제 구현이 다른 부분을 적는다. 1부의 변경은 설계 단계에서 사용자가 골랐고 ADR §9.1·§9.3에 이미 반영했다. 2부의 변경은 자동 채택이고, 메인 세션이 ADR §9.1·§9.3·§10 S3에 반영했다 (`932cdc8`).

| 항목 | 원래 계획 | 실제 | 이유 |
| --- | --- | --- | --- |
| 라이브 API e2e | backend 작업은 단위·계약 테스트까지 | CI에서 라이브 API e2e 63개도 실행 | 테스트가 uvicorn을 직접 띄우고 root가 필요 없어서 가능했다 |
| 린트 | 도구 미정 | ruff 0.14.0 기본 규칙 | 규칙 확장 없이 제품 코드를 건드리지 않는다 |
| skip 처리 | 명시 없음 | skip이 있으면 실패 (JUnit XML 검사) | pytest의 skip은 종료 코드 0이다 |
| 훅 테스트 | 목록에 없음 | `.claude/hooks/tests` 25개를 CI에서 실행 | 훅이 Linux에서 같은 venv를 찾으므로 CI에서 확인할 수 있다 |
| 실행 시점 | PRD 계획상 핵심 기능 뒤 | 계정·풀 직후 | 위 설계 결정 표 마지막 줄 |
| data-plane 작업의 러너 | S3 결과에 따른다. 실패하면 데이터 플레인 테스트는 로컬(또는 self-hosted 러너)에서만 (ADR §10 S3) | GitHub 호스트 러너 `ubuntu-24.04`. 모듈·패키지 설치 단계 없음 | S3 조건부 통과 (3.7) |
| S3가 확인할 모듈 | btrfs·nfsd (ADR §10 S3의 질문) | nfsd, dm-thin, ifb와 tc 모듈 | 볼륨은 btrfs가 아니라 dm-thin 씬 LV + ext4다 (D-11). 처리량 한도가 IFB·HTB를 쓴다 (FR-08) |
| data-plane 작업의 트리거 | 정하지 않음 (PRD FR-11은 "GitHub 러너에서 가능한지 확인한 뒤 넣는다"만 적었다) | main 대상 PR, main push, 수동 | 결정 5 |
| 제품 코드 | 1부: CI 추가는 제품 코드를 바꾸지 않는다 (AC-07) | 2부: storage agent의 `ensure_shared_ns()`를 고쳤다 (해시 `f99bc5cf…` → `9a023d13…`) | S3가 찾은 결함 (3.8) |

### 4.1 data-plane 작업의 한계

| 항목 | 한계 | 이유와 대응 |
| --- | --- | --- |
| 커널 | 러너는 `7.0.0-1017-azure`, 개발 기기(WSL)는 6.18이다. 러너 이미지가 갱신되면 커널도 바뀐다 | 호스트 러너의 커널은 고를 수 없다 (결정 9). 차이로 실패가 나오면 그때 원인을 가른다. 그래서 Runner info 단계가 이미지, 커널, `/`의 전파를 실행마다 남긴다 |
| 시간 | 조각마다 약 40분이다. S3의 파일별 시간으로 나누면 `throughput` 약 36분, `rest` 약 37분, 준비 30 s 안팎이다. PR의 피드백이 그만큼 늦다 | 처리량 시험은 실제 데이터를 흘려 재므로 줄일 수 없다. 기능 브랜치 push에서는 돌리지 않는다. 브랜치 작업 중에는 같은 실행기를 WSL에서 돌릴 수 있다 |
| 처리량 판정 | 측정 대상이 공유 러너 VM 위의 실제 대역폭이다. S3에서는 중앙값이 한도의 0.9946~1.0016, 2 s·1 s 창의 최댓값이 1.0084로 판정 범위(0.90~1.01) 안이었고, 같은 조건의 5회 흔들림도 0.1% 안쪽이었다. 그러나 근거는 S3의 job 몇 개뿐이고, 창 기준으로 상한까지 남은 폭은 0.16%p다 | 러너 쪽 잡음이 커지면 결함 없이 빨간색이 될 수 있다 [추론]. 여러 번 돌려도 안정적인지는 측정하지 않았다 [미확인]. 판정 범위를 바꿀 근거도 아직 없다 (S3). 실패하면 `.jsonl`의 측정값과 Runner info부터 본다 |
| `concurrency` | 같은 ref의 앞선 실행이 취소된다. main에 연달아 merge하면 마지막 main push 실행만 끝까지 돌고, 열린 PR에 문서만 고쳐 push해도 두 조각이 처음부터 다시 돈다 | 낡은 커밋의 결과를 기다리지 않는다는 1부의 규칙을 그대로 뒀다 (설계 §6.6). 긴 실행 중에는 PR 브랜치 push를 미룬다 |
| 막는 장치가 아님 | 브랜치 보호가 없어 data-plane 작업이 빨간색이어도 merge를 막지 않는다 | 저장소 설정이라 사용자가 정한다 (2부 설계 §3) |
| 디스크 | 전체 묶음 한 번에 `aggr0.img`가 21~22 GB로 커지고 줄지 않는다. 씬 풀은 비었는데 지운 블록이 희소 파일로 돌아가지 않는다 | 러너 여유 86 GB에서는 문제가 없다. 한 VM에서 묶음을 반복하면 쌓인다 (S3) |

## 5. 검증

5.1~5.2는 1부(backend 작업)의 검증이다. 2부(data-plane 작업)는 5.3에 있다.

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
- **데이터 플레인.** 1부의 backend 작업은 NFS 마운트, 스냅샷, 처리량 제한 같은 데이터 효과를 확인하지 않는다. 그 일은 2부의 data-plane 작업이 맡는다 (5.3). 2부의 한계는 4.1에 있다.
- **flaky 여부.** 성공 run은 같은 내용으로 2번(push, PR)이다. 이 테스트들이 여러 번 돌려도 안정적인지는 측정하지 않았다 [미확인].
- 검증 보고서의 관찰 3건(판정 밖): 실패 직후 몇 분간 GitHub API가 단계 결과·로그를 비워 돌려줌, skip 검사의 오류 문구가 `collected …` 줄보다 먼저 찍힘 (stdout 버퍼링, 고치려면 `ci.yml:57`에 `flush=True`), 실패 annotation이 `exit code 1`뿐이라 원인은 로그에서만 보임 (`ruff --output-format=github`로 개선 가능). 뒤의 둘은 설계 밖이라 그대로 뒀다. 그중 skip 검사는 FR-10에서 `junit_gate.py`로 바뀌었다 (`docs/concepts/test-automation.md` 3.3).

### 5.3 2부: data-plane 작업

수락 기준은 2부 설계 §5의 AC-01~AC-08이다.
- AC-01: main 대상 PR에서 두 조각이 모두 success이고, 두 조각의 실행기 요약을 합치면 수집 113, 통과 113, 실패·오류·skip 0이며, 13개 파일이 겹치거나 빠지지 않는다.
- AC-02: 그 실행의 워크플로에 ns 전파를 손대는 단계가 없고, Runner info에 `/`가 `shared`로 찍혀 있으며, S3에서 실패했던 8개가 통과 목록에 있다.
- AC-03: 데이터 플레인 테스트가 실패하면 그 조각이 failure이고, 그래도 artifact는 올라온다 (임시 브랜치에서 확인).
- AC-04: 조각마다 실행기 출력 폴더와 dmesg가 artifact로 남고 내려받아 읽을 수 있다.
- AC-05: 고친 코드로 WSL에서 볼륨과 스냅샷을 만들면 호스트 마운트 표에 각 마운트가 한 번만 있고, 클라이언트 컨테이너에서 볼륨과 `.snapshot/<이름>`이 보인다.
- AC-06: 고친 코드로 WSL에서 실행기 전체 1회: 113 통과, skip 0, exit 0, 남은 것 없음.
- AC-07: 같은 PR 실행에서 backend·frontend 작업이 통과한다 (`ensure_shared_ns`의 새 단위 테스트 포함, skip 0, ruff).
- AC-08: 각 조각이 50분 안에 끝난다.

판정 방법(2부 검증 보고서): AC-01·02·04·07·08은 PR #20의 Actions 실행(`pull_request` run 42811747210), AC-03은 임시 브랜치의 draft PR, AC-05는 WSL에서 직접, AC-06은 implementer의 WSL 실행 결과 파일로 본다. 검증 대상 코드는 커밋 `5cb8b17`, 제품 코드 내용 해시 `9a023d13…`이다.

**검증 회차 전에 이미 확인된 것.** 아래는 판정이 아니라 판정의 재료다.
- **S3 (run 42785777318).** `private` job 113 통과 / 0 실패 / 0 skip, 4,378 s, 실행기 exit 0. `as-is` job 105 / 8 / 0, 4,372 s, exit 1. 단, `private` job의 ns 처리는 워크플로 단계의 우회였다. 이 결과가 보여 주는 것은 "bind → private → rshared 상태면 러너에서 전부 통과한다"이다. 고친 제품 코드가 러너에서 그 상태를 만드는지는 PR #20의 실행(AC-02)이 보여야 한다.
- **WSL 전체 회귀 (AC-06의 재료).** 고친 코드(해시 `9a023d13…`)로 `scripts/run-dataplane-tests.sh`를 인자 없이 1회 돌렸다. 113 통과, skip 0, exit 0, 5,198 s(단조 시계), 남은 것 없음. 출력은 `/var/tmp/anf-clone-tests/20261110T102847Z`이고, 메인 세션이 `summary.txt`와 콘솔의 종료 코드 0을 확인했다. `/`가 private인 WSL에서 private 단계 하나를 더한 것이 묶음의 어느 테스트도 깨뜨리지 않았다는 뜻이다.
- **단위 테스트.** `test_nfs_instance.py:399-427`의 네 경우 (3.8). backend 작업이 이 테스트를 skip 0으로 돌리는지는 AC-07이 본다.

<!-- 검증 결과: 메인이 채움 -->

## 6. 개발 과정

**1부 (backend 작업, 2026-11-07)**

1. **조사: 생략.** PRD §8에 따라 FR-11은 조사를 거치지 않는다.
2. **설계.** 사용자가 범위(단위·계약 + 라이브 API e2e), 린트(ruff 기본 규칙), 러너(ubuntu만)를 골랐다. 설계 기록에 결정 8개와 수락 기준 AC-01~AC-07을 적었다. 계획상 FR-11은 핵심 기능 뒤였지만, PR #4, #5가 검사 없이 merge된 것을 보고 앞당기기로 했다. 같은 브랜치 앞 커밋 `e4acc7a`에서는 검증 해시 절차를 줄 끝에 무관하게 고쳐 두었다.
3. **구현.** `.github/workflows/ci.yml`, F841 수정 1건, `CLAUDE.md` 명령 절, ADR §9.1·§9.3을 바꿨다. WSL의 새 venv에서 CI 단계를 먼저 재현했다: 린트 통과, 342 passed / skip 0, 훅 25 passed. `ANF_E2E_API_URL` 없이 돌리면 skip 검사가 종료 코드 1로 실패하는 것도 로컬에서 먼저 봤다.
4. **push에서 막힘.** `feature/ci`를 push하자 gh 토큰에 `workflow` 권한이 없어 거절됐다 (`refusing to allow an OAuth App to create or update workflow`). 워크플로 파일을 만들거나 고치는 push는 그 권한이 필요하다. 사용자가 기기 인증으로 권한을 추가해서 해결했다. 이 권한은 AC-06(c)에서 임시 브랜치의 워크플로를 바꿔 push할 때도 필요했다.
5. **실환경 검증 1회차.** 첫 run 42445326221이 success였고, real-env-verifier가 AC-01~AC-07을 판정했다. 결과는 PASS 7 / UNVERIFIED 1이고, 수정 사항은 없었다. 로컬 재현을 PASS로 세지 않고 Actions 실행만 근거로 삼는 원칙을 지켰다.
6. **2회차.** 사용자 요청으로 main 대상 PR #6을 열자 `pull_request` run 42446223916이 돌았다. 같은 검증자가 실행 기록으로 AC-01b를 PASS로 판정해 모든 기준이 PASS가 됐다.
7. **사람이 내린 결정.** 범위, 린트 도구, 러너 OS, 앞당기기 여부, 토큰 권한 추가, PR을 열 시점.

**2부 (data-plane 작업, 2026-11-10)**

1. **조사: 생략.** 1부와 같다.
2. **스파이크 S3.** feature-implementer가 격리된 worktree에서 브랜치 `spike/s3-runner`에 임시 워크플로 `.github/workflows/spike-s3.yml`을 넣고 push해 Actions에서 돌렸다. 로컬 WSL 데이터 플레인은 쓰지 않았고 제품 코드와 기존 테스트도 바꾸지 않았다. 1회차 run 42783919456(부분 묶음)에서는 테스트 2개가 실패했다. 2회차 run 42785777318은 전체 묶음을 ns를 그대로 둔 `as-is` job과 private로 떼어 낸 `private` job으로 나란히 돌리고 tmpfs 탐침을 더했다. 그 결과 `as-is`의 실패 8개가 모두 ns 마운트 전파 하나 때문임을 확인했다. 러너 사양, 시간 분포, 처리량 비율도 이때 쟀다.
3. **설계.** 결정 1~10을 `anf-roadmap` 총괄이 자동 채택했다. S3가 사용자에게 물을 것으로 남긴 두 질문(ns 전파를 어디서 고칠지, PR마다 무엇을 돌릴지)도 설계에서 자동 채택으로 정했다(제품 수정, 두 조각으로 전체).
4. **구현.** 새 feature-implementer가 주 체크아웃에서 했다. 커밋 `691d93f`(`ensure_shared_ns` 수정과 단위 테스트, TDD), `02f6d7f`(`ci.yml`의 data-plane 작업, 준비 스크립트 머리 주석, `docs/testing.md` CI 절, 설계 §6), `5cb8b17`(`docs/testing.md`의 테스트 수 989)이다. 실행기는 고치지 않았다(`--ignore=`가 그대로 넘어가는 것을 WSL에서 수집으로 확인). 설계를 바꾼 것은 없고, 설계가 정하지 않은 세부(ns 전파 기록을 테스트 뒤에 둠, artifact 이름과 보관, `workflow_dispatch`의 범위, `concurrency`)를 설계 §6에 적었다. WSL 전체 회귀는 분리 실행으로 1회 돌렸다 (5.3).
5. **PR #20.** main 대상 PR을 열자 `pull_request` run 42811747210에서 두 조각이 돌기 시작했다. 메인 세션이 ADR §9.1·§9.3·§10 S3와 `CLAUDE.md`를 갱신했고(`932cdc8`), 러너 실행을 취소하지 않으려고 그 push는 판정 뒤로 미뤘다.
6. **실환경 검증.** real-env-verifier가 AC-01~AC-08을 판정한다. 결과는 5.3에 있다.
7. **사람이 내린 결정.** 2부에는 사용자에게 물은 결정이 없다. 브랜치 보호를 켤지는 여전히 사용자 몫이다.

---

## 7. Interview Q&A

### Q1. Why does your CI treat skipped tests as failures?

**A.** Because pytest exits with code zero even when tests are skipped, so a skip can hide a real gap behind a green check. In my project, the live API end-to-end tests are skipped unless one environment variable is set. When I removed it on a temporary branch, the test step passed with 279 passed and 63 skipped, and the pipeline would have been green. So I added a step that reads the JUnit XML and fails if any test was skipped or none were collected. It also forces a decision later: when a test needs root or Docker, I must choose where it runs, instead of letting it quietly disappear.

### Q2. What does your CI run, and what can it not run?

**A.** It runs three jobs. The backend job runs ruff, the unit and contract tests, the live control-plane end-to-end tests, where the tests start the API server themselves with uvicorn, and the tests of my TDD hook. It deselects the data-plane tests by marker, which is different from skipping them. The frontend job type-checks, tests, and builds the dashboard. The data-plane job runs the 113 data-plane tests as root on a GitHub-hosted runner: real thin volumes, one NFS server instance per volume, client containers that mount over NFSv3 and NFSv4.1, and tc throughput limits. What CI still does not do is block merges, because branch protection is off. The data-plane job also does not run on feature-branch pushes, only on pull requests to main, pushes to main, and manual runs.

### Q3. How do you know your CI actually catches failures, and not just passes?

**A.** A green run proves very little, since an empty workflow is also green. So I made three temporary branches from the same commit and broke one thing in each: a failing assertion, an unused import, and the removal of the environment variable that enables the live tests. Each run failed at the step I expected: Test, Lint, and the skipped-test check, and later steps were skipped. I recorded the run IDs and deleted the branches. That gave me evidence for each failure path, not only the success path.

### Q4. Why did you keep ruff out of pyproject.toml?

**A.** In this project, a hash of the product code decides whether an earlier feature verification is still valid, and pyproject.toml is part of that hash. Adding ruff there would change the hash and invalidate the account and pool verification, even though runtime behavior is the same. So I install a pinned ruff version, 0.14.0, inside the CI lint step only. The trade-off is that developers must install ruff themselves to lint locally. If the verification process did not depend on that file, I would put ruff in the dev extras, which is the normal choice.

### Q5. Why do you install with the same commands as the setup docs instead of a plain pip install?

**A.** I wanted the CI to follow the documented setup exactly: create the virtual environment at the same path and run an editable install with the dev extras. If the documentation drifts from what really works, the CI breaks first. The TDD hook also looks for that virtual environment on Linux, so the hook tests run in the same environment as developers use. I pinned the runner to Ubuntu 24.04 and Python 3.12, matching my WSL setup, so a failure in CI should be reproducible locally.

### Q6. How would you handle flaky or environment-dependent tests in this pipeline?

**A.** For environment dependence, I make the dependency explicit rather than silent: a test that needs a condition is marked, and the skipped-test check forces me to run it somewhere or deselect it by marker on purpose. For flakiness, I have not measured it yet, since I have only two successful runs of the same commit, and I would say so honestly. My live tests wait for operations by polling the status URL with a timeout, which is the same client behavior the API contract describes. The next step would be repeating the suite many times and tracking failures before trusting it as a merge gate.

### Q7. Which limitations remain, and what would you do next?

**A.** A few. First, branch protection is not enabled, so a red build does not block a merge yet. Second, concurrency cancellation and the backend job timeout were not tested, and flakiness is not measured. Third, the data-plane job runs on the runner's kernel, 7.0, not my WSL kernel, 6.18, and its throughput checks measure real bandwidth on a shared VM, so they depend on low noise. Next I would enable required checks on main, track the throughput margins across many runs before making the data-plane job a merge gate, and switch ruff to GitHub-style output so failures show on the changed lines.

### Q8. Tell me about a problem you hit while setting this up.

**A.** My first push of the workflow was rejected because the GitHub token lacked the workflow scope, and GitHub refuses OAuth tokens that create or update workflow files without it. I did not work around it with another credential. I asked the owner to add the scope through device authentication, and then the push worked. Another smaller finding came during verification: the GitHub API returned empty step results for a few minutes after a failed run, so I re-fetched the full job logs later instead of trusting the first, incomplete response.

### Q9. Why did you build CI before the volume feature, if the plan put it later?

**A.** Two earlier pull requests had been merged without any automated check, and the next feature, volumes, changes shared code heavily. Catching a regression in the account and pool contracts at that point would have been expensive. The control-plane tests were already runnable on a plain runner, so the cost was low and the value was immediate. It is a reasoned change of order, and I recorded it in the progress notes. If I did it again, I would add CI right after the first feature.

### Q10. How can a GitHub-hosted runner run tests that load kernel modules and mount file systems? Why no self-hosted runner?

**A.** Because a hosted Ubuntu runner is a fresh virtual machine whose kernel the job uses directly, and the job user has passwordless sudo. Before designing the job, I ran a spike on the real runner. The ubuntu-24.04 image, with kernel 7.0, already had every module the clone needs, such as nfsd, dm-thin, ifb, and the tc modules, plus the LVM tools, iptables, and Docker Engine. My setup script and test runner ran unchanged under sudo, and all 113 data-plane tests passed with no skips once one mount issue was handled. So a self-hosted runner was unnecessary. There is also a bonus: each matrix leg gets its own VM, so each leg has a whole data plane to itself.

### Q11. Tell me about a product bug that CI found but your development machine did not.

**A.** The CI spike showed that my storage agent mounted every volume and snapshot twice on a normal Linux host. The agent bind-mounts its namespace directory onto itself and makes it shared, so each volume's NFS container, which binds it as rslave, sees snapshot mounts made later. On WSL the root mount is private, so that bind got its own peer group. On the runner, systemd makes root shared, so the bind joined root's peer group, and the kernel copied every mount under it onto the hidden directory beneath the bind as well. Clients saw the same data, but eight tests that count host mounts failed. A tmpfs probe confirmed it: two mount-table entries as-is, one when the bind was made private first.

### Q12. Why did you fix it in the storage agent, not in the workflow or the tests?

**A.** Because the defect belongs to the product on any host whose root mount is shared, not to the CI runner. I had three options. A workflow step that makes the directory private before the agent starts would make CI imitate WSL, so CI would stop testing what a real host runs. Removing duplicates in the test helper would hide a real double mount. So the agent now makes a new bind private and then recursively shared, which gives it its own peer group. The spike had already passed all 113 tests in exactly that state. The cost was a product code change, so instead of re-verifying five features one by one, I re-ran the whole data-plane suite on WSL as a regression: 113 passed, no skips.

### Q13. Why is the data-plane job split into two matrix legs, and how does each leg pick its tests?

**A.** Because one file, the throughput data test, takes about half of the total time. It streams real data through each limit, so it cannot be shortened. Putting it in its own leg gives two legs of roughly 36 and 37 minutes instead of one job of about 75. More legs would not help, because the longest leg would still be that one file, and every leg repeats setup and produces its own logs. The throughput leg names that file. The rest leg passes pytest's ignore option for it instead of listing the other twelve files, so a new data-plane test file joins the rest leg automatically and cannot silently fall outside CI.

### Q14. Why doesn't the data-plane job run on every push, like the other jobs?

**A.** To avoid running a forty-minute job twice for the same commit, while still checking what matters. On a feature branch with an open pull request, one push starts both a push run and a pull-request run. So the data-plane job runs on pull requests to main, which test the merge result before merging, on pushes to main, which show the state of main, and on manual dispatch. Backend and frontend still run on every push; they take a few minutes, so a second run costs little. The trade-off is slower feedback while I work on a branch, and there I can run the same runner script on WSL. Also, concurrency cancels older runs of the same ref, so I avoid pushing small fixes during a long PR run.

### Q15. When a data-plane leg fails in CI, how do you find the cause?

**A.** I follow the same evidence the verdict is built on. The verdict is the test runner's exit code: one means failures, errors, skips, or leftover volumes and containers; two means a precheck failed before any test ran, and its cause is one line in the step log. Next I download that leg's artifact, which is uploaded even on failure: per-file pytest logs and JUnit XML, a JSON-lines log of every HTTP request with evidence notes, the baseline and summary, and the kernel log. Then I compare the Runner info step, which records image, kernel, and root mount propagation, with an earlier green run, because a runner image change is a plausible cause. Finally I reproduce it with the same command on WSL.
