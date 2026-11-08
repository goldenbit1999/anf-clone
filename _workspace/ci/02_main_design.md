# ci 설계 (FR-11 CI, 백엔드 작업)

- 확정일: 2026-11-07 (사용자 확인: 범위, 린트, 러너 OS)
- 조사 브리프: 없음. PRD §8에서 FR-11은 조사를 생략한다 (ANF 기능이 아니다)

## 1. 관련 ID

| 종류 | ID |
| --- | --- |
| PRD | FR-11(CI), FR-10(테스트 자동화), G4(공고 기술을 결과물로), §9 성공 기준("main 브랜치의 CI가 통과 상태") |
| ADR | §9.1 테스트 층, §9.2 TDD 훅에 맞추기(Python 3.12), §9.3 CI 표, D-01(Python 3.12, CI 포함), D-14(Python 설정) |
| 스파이크 | S3(GitHub 러너에서 커널 모듈·privileged 마운트)는 데이터 플레인 작업의 선행 조건이다. 이번 백엔드 작업에는 필요 없다 |

## 2. 범위

### 이번에 만든다

GitHub Actions 워크플로 `.github/workflows/ci.yml`에 `backend` 작업 하나를 만든다. push와 main 대상 PR마다 다음을 돌린다.

1. 린트: `ruff check backend .claude/hooks` (ruff 0.14.0, 기본 규칙)
2. 테스트: `ANF_E2E_API_URL`을 켜고 `python -m pytest`를 돌린다. 단위·계약 테스트와 라이브 API e2e(테스트가 uvicorn을 직접 띄우는 컨트롤 플레인 검증)가 함께 돈다. skip이 하나라도 있으면 실패한다
3. TDD 훅 테스트: `python -m pytest .claude/hooks/tests`

### 이번에 만들지 않는다 (FR-11이 `partial`로 남는 이유)

- **frontend 작업** (타입 검사, 빌드, 단위 테스트): 대시보드(FR-09)가 아직 없다.
- **data-plane 작업** (커널 모듈, storage agent, 통합·데이터 플레인 E2E): 볼륨부터 생기고, GitHub 호스트 러너에서 가능한지 스파이크 S3로 먼저 확인한다.
- **브랜치 보호 규칙** (main merge 전에 CI 통과 필수): GitHub 저장소 설정이라 사용자가 정한다. 이번에는 제안만 한다.

## 3. 결정

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | **라이브 API e2e까지 CI에서 돌린다** (사용자 선택) | 단위·계약만 (ADR §9.3의 원래 표) | 지금 e2e 63개는 root·커널·Docker가 필요 없다. 테스트가 uvicorn을 직접 띄운다. 그래서 검증자가 WSL에서 확인한 계약을 PR마다 실제 서버로 다시 확인할 수 있다 |
| 2 | **ruff 기본 규칙** (사용자 선택), 버전 0.14.0 고정 | 린트 없음, 규칙 확장 | 기본 규칙으로 걸린 것은 테스트 파일의 F841 1건이라 제품 코드를 고치지 않는다. 규칙을 넓히면 제품 코드 수정이 생겨 완료된 기능의 검증이 무효가 된다 |
| 3 | **ubuntu만** (사용자 선택), `ubuntu-24.04`로 고정 | ubuntu + windows, `ubuntu-latest` | 실행 환경이 WSL Ubuntu 24.04다. Windows 쪽은 편집할 때마다 로컬 TDD 훅이 테스트를 돌린다. `latest`는 바뀔 수 있어 WSL과 같은 24.04로 고정한다 |
| 4 | ruff를 `pyproject.toml`의 dev 의존성에 넣지 않고, CI에서 버전을 고정해 설치한다. 설정 파일도 두지 않는다(기본 규칙) | dev 의존성에 추가 | `pyproject.toml`은 제품 코드 해시에 들어간다. 바꾸면 계정·풀의 검증 대상 코드가 달라진다. 린트 도구 추가는 실행 동작을 바꾸지 않으므로 해시를 건드리지 않는 쪽을 택했다 |
| 5 | 설치는 `CLAUDE.md`의 WSL 설정 명령을 그대로 쓴다 (`python -m venv ~/.venvs/anf-clone`, `pip install -e ".[dev]"`) | `pip install`을 시스템 Python에 바로 | 문서의 설정 절차를 CI가 매번 확인한다. TDD 훅도 Linux에서 이 venv를 찾는다 |
| 6 | **skip이 있으면 실패한다.** pytest의 JUnit XML에서 `skipped`가 0이 아니거나 수집된 테스트가 0개면 작업을 실패시킨다 | skip을 허용 | pytest는 skip이 있어도 성공(종료 코드 0)으로 끝난다. `ANF_E2E_API_URL`이 빠지면 e2e 63개가 조용히 skip되고 CI는 초록색이 된다. "skip은 PASS가 아니다"(ADR §9.1)를 CI에서도 지킨다. 나중에 root나 Docker가 필요한 테스트가 생기면 이 검사가 실패해서, 그 테스트를 어디서 돌릴지(마커로 빼고 data-plane 작업으로) 명시적으로 정하게 된다 |
| 7 | 트리거는 모든 브랜치의 push와 main 대상 PR. 같은 ref의 이전 실행은 취소한다(`concurrency`). 권한은 `contents: read` | push는 main만 | PRD FR-11이 "푸시와 PR마다"다. 브랜치에 push만 해도 결과를 볼 수 있다 |
| 8 | 작업 제한 시간 15분 | 기본값 360분 | e2e가 멈추면(서버가 안 뜨는 등) 6시간을 기다리지 않는다. 로컬 전체 실행은 약 3분이다 |

## 4. 검증 기준

검증은 GitHub Actions의 실제 실행 결과로 한다. 로컬 실행은 구현 중 확인일 뿐 PASS가 아니다.

| ID | 종류 | 기준 |
| --- | --- | --- |
| AC-01 | 트리거 | `feature/ci` 브랜치에 push하면 워크플로 `ci`가 자동으로 돈다. main 대상 PR을 열면 `pull_request` 이벤트로도 돈다 |
| AC-02 | 환경 | 실행 로그에 러너 `ubuntu-24.04`, Python 3.12.x, `~/.venvs/anf-clone`에 `pip install -e ".[dev]"`로 설치한 기록이 있다 |
| AC-03 | 린트 | `ruff check backend .claude/hooks` 단계가 위반 0건으로 통과한다 |
| AC-04 | 테스트 | 테스트 단계가 실패 0, 오류 0, skip 0으로 통과한다. 수집 수는 로컬 Windows 실행의 passed + skipped와 같다(지금 342 = 279 + 63) |
| AC-05 | 훅 테스트 | `.claude/hooks/tests`가 통과한다 (지금 25개) |
| AC-06 | 실패 감지 | 임시 브랜치에서 다음 세 경우가 각각 작업 실패(빨간색)로 끝나고, 실패한 단계가 그 원인을 가리킨다. (a) 단위 테스트 하나를 일부러 깨뜨림 → 테스트 단계 실패, (b) 린트 위반 추가 → 린트 단계 실패, (c) 워크플로에서 `ANF_E2E_API_URL`을 뺌 → skip 검사 실패. 확인 뒤 임시 브랜치를 지운다 |
| AC-07 | 제품 코드 불변 | 이번 변경 뒤에도 제품 코드 내용 해시가 `f2b70558…`(커밋 `41f863d`)와 같다. 그래서 계정·풀의 판정이 유지된다 |

## 5. 구현 중 변경

(없음)
