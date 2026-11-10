# ci 진행 기록

- 상태: partial (UNVERIFIED 없음. 이번 범위인 backend 작업은 8/8 PASS이고 개념 문서도 끝났다. FR-11의 frontend·data-plane 작업이 남아 있다)
- FR: FR-11 (CI). 이번 범위는 backend 작업이다. frontend 작업(FR-09 뒤)과 data-plane 작업(S3 뒤)은 남는다
- 마지막 완료 단계: 6
- 재개할 단계: 2 — frontend 작업은 대시보드(FR-09) 사이클 뒤, data-plane 작업은 스파이크 S3 통과 뒤에 설계부터 한다
- 검증 대상 코드: 커밋 `3fd6511` (PR #6의 head. PR run은 merge 커밋 `86b20aa`를 검사했고 트리가 `3fd6511`과 같다). 제품 코드 내용 해시 `f2b70558…` 유지 (AC-07)
- verifier 에이전트 ID: a3e582af3fd57d42c (1·2회차, 2026-11-07)
- 미해결: 없음

## 선행 확인 (0단계)

- PRD §8: FR-11은 1단계(조사)를 생략하고 2~6단계를 거친다. 개념 문서는 엔지니어링 관점이고 ANF·ONTAP 절은 "해당 없음"이다.
- ADR §9.3: backend 작업은 선행 조건이 없다. data-plane 작업은 S3 통과 뒤다.
- 계획상 FR-11은 2단계(핵심 기능 뒤)지만, 사용자가 지금 만들기로 했다. 이유: PR #4, #5가 검사 없이 merge됐고, 다음 기능(볼륨)이 공통 코드를 크게 바꾼다.
- 미리 확인한 것: ruff 0.14.0 기본 규칙 위반은 `backend/tests/e2e/test_netapp_account_lro_faults_live.py:37`의 F841 1건뿐이다. 훅 테스트는 WSL(Linux)에서 25 passed(약 10초)다. 라이브 e2e는 root가 필요 없고 테스트가 uvicorn을 직접 띄운다.

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01a | push 이벤트로 실행 | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |
| AC-01b | main 대상 PR의 `pull_request` 이벤트로 실행 | PASS (run 42446223916, PR #6) | `04_verifier_report_r2.md` (2회차) | `3fd6511` (merge 커밋 `86b20aa`, 같은 트리) |
| AC-02 | ubuntu-24.04, Python 3.12, 문서의 WSL 설정 명령으로 설치 | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |
| AC-03 | ruff 위반 0건 | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |
| AC-04 | 342 passed, 실패·오류·skip 0 | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |
| AC-05 | 훅 테스트 25 passed | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |
| AC-06 | 테스트 실패·린트 위반·skip이 각각 해당 단계에서 실패 | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |
| AC-07 | 제품 코드 내용 해시 `f2b70558…` 유지 | PASS | `04_verifier_report.md` (1회차) | `3fd6511` |

## 이력

- 2026-11-07 단계 0 완료 — 문서 확인. 조사 생략(PRD §8).
- 2026-11-07 단계 2 완료 — 사용자가 범위(단위·계약 + 라이브 API e2e), 린트(ruff 기본 규칙), 러너(ubuntu만)를 골랐다. `02_main_design.md`에 결정 1~8과 AC-01~AC-07을 적었다. 같은 브랜치의 앞 커밋(`e4acc7a`)에서 해시 절차와 계정·풀 기록을 따로 정리했다.
- 2026-11-07 단계 3 완료 — `.github/workflows/ci.yml`(backend 작업: 설치, 린트, 테스트, skip 검사, 훅 테스트), F841 수정(`test_netapp_account_lro_faults_live.py:37`, 쓰지 않는 변수), `CLAUDE.md` 명령 절, ADR §9.1·§9.3. WSL의 새 venv에서 CI 단계를 재현했다: 린트 통과, 342 passed / skip 0(테스트 단계 약 2분 반), 훅 테스트 25 passed. `ANF_E2E_API_URL` 없이 e2e를 돌리면 skip 검사가 종료 코드 1로 실패하는 것도 확인했다. 제품 코드 내용 해시는 `f2b70558…` 그대로다. 로컬 재현은 PASS가 아니다(판정은 Actions 실행으로 한다).
- 2026-11-07 단계 4 시작 — `feature/ci` push(`3fd6511`). push 전에 gh 토큰에 `workflow` 권한이 없어 거절됐고(`refusing to allow an OAuth App to create or update workflow`), 사용자가 기기 인증으로 권한을 추가했다. 첫 Actions run `42445326221`(push)이 success였다. real-env-verifier에 AC-01~AC-07 판정을 맡겼다 (AC-06은 scratchpad worktree의 임시 브랜치 세 개로, PR 이벤트는 PR을 열 때 확인).
- 2026-11-07 단계 4 1회차 완료 — PASS 7 / FAIL 0 / UNVERIFIED 1 (`04_verifier_report.md`, AC-01을 push·PR 둘로 셈). 실패 감지 run: 테스트 실패 42445665196(Test 단계), 린트 위반 42445687864(Lint 단계), `ANF_E2E_API_URL` 제거 42445712865(Fail on skipped tests 단계, Test는 279 passed 63 skipped로 통과). 임시 브랜치와 worktree는 정리됐다. 판정 밖 관찰: (1) 실패 직후 몇 분간 GitHub API가 단계 결과·로그를 비워 돌려줌, (2) skip 검사의 오류 문구가 `collected …` 줄보다 먼저 찍힘(출력 순서, `ci.yml:57`), (3) 실패 annotation이 "exit code 1"뿐이라 원인은 로그에서만 보임(`ruff --output-format=github`이면 PR에 줄 단위 표시). (2)(3)은 설계 밖이라 그대로 둔다.
- 2026-11-07 단계 5 완료 — concept-explainer가 `docs/concepts/ci.md`를 썼다 (면접 Q&A 9개, ANF·ONTAP 절은 해당 없음). 메인이 인용을 대조해 고쳤다: `live_api.py` 줄 번호 두 곳, `ci.yml:55` 설명(지금 pytest 9.2.0은 루트가 `<testsuites>`라 `find`가 평소 경로), 근거 없는 추정 한 곳(훅 테스트를 마지막에 둔 이유 → 앞 단계 실패 시 실행되지 않는다는 사실로 바꿈).
- 2026-11-07 단계 4 2회차 시작 — 사용자 요청으로 main 대상 PR #6을 열었다(head `3fd6511`). `pull_request` run 42446223916이 success로 끝났다. 같은 verifier(a3e582af3fd57d42c)에 AC-01b만 재판정을 맡겼다.
- 2026-11-07 단계 4 2회차 완료 — PASS 1 / FAIL 0 / UNVERIFIED 0 (`04_verifier_report_r2.md`). 체크아웃 ref `refs/pull/6/merge`(merge 커밋 `86b20aa`, 트리 `c26d3131…`가 `3fd6511`과 같음), 342 passed / skip 0, 훅 25 passed, `gh pr checks 6`에 push·PR 두 체크가 모두 통과로 표시. 1·2회차 합계 8/8 PASS. 개념 문서의 AC-01b 서술을 갱신했다. 관찰: main이 앞서 나간 뒤 PR이 다시 돌면 새 merge 커밋이 검증 대상이 된다.
- 2026-11-07 단계 6 완료 — 상태 `partial`(위 상태 줄의 이유). `docs/feature-status.md` 갱신.

## 2부: data-plane 작업 (2026-11-10~)

- 상태: in_progress
- 마지막 완료 단계: 3 (구현)
- 재개할 단계: 4 (검증, `real-env-verifier`. PR의 Actions 실행으로 판정)
- 브랜치: `feature/ci-dataplane` (`main` `7255e3e`에서)
- 검증 대상 코드: `5cb8b17` (`feature/ci-dataplane`), 제품 코드 내용 해시 `9a023d13b647ba1f0363bfa75a22c66ea362991e5baca42796bef74e6cab92f1` (이전 `f99bc5cf…`. 메인 계산)
- implementer 에이전트 ID: a187fce0d89195620 (구현, 주 체크아웃). 스파이크 S3는 aee96ed1b59426045(worktree)
- verifier 에이전트 ID: afd57e3f7005fa470 (1회차)
- concept-explainer 에이전트 ID: a117973a9a96d5635
- 미해결: 없음

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | PR에서 두 조각 success, 합 113 통과·skip 0 | | | |
| AC-02 | ns 우회 단계 없이 `/`가 shared인 러너에서 통과 | | | |
| AC-03 | 실패하면 조각 failure, artifact는 올라옴 | | | |
| AC-04 | artifact | | | |
| AC-05 | WSL에서 마운트 한 번, 클라이언트에서 보임 | | | |
| AC-06 | WSL 전체 회귀 113 통과 | | | |
| AC-07 | backend·frontend 통과 | | | |
| AC-08 | 조각마다 50분 안 | | | |

- 2026-11-10 스파이크 S3 조건부 통과 (`_workspace/spikes/S3.md`): Actions run 42783919456(부분 묶음 43 통과·2 실패), 42785777318(전체: private 113/0/0 4,378 s, as-is 105/8/0). 실패 8개는 전부 스냅샷 마운트 중복. 원격 브랜치 `spike/s3-runner`는 남아 있다(출하 때 지운다)
- 2026-11-10 단계 2 완료 — 묻는 결정 없음, 결정 1~10 자동 채택 (ns 전파는 제품 수정, 회귀는 전체 묶음, 2개 조각 matrix, PR·main push 트리거)
- 2026-11-10 단계 3 시작 — 새 feature-implementer(주 체크아웃)에 구현을 맡김: ns 전파 수정(TDD), ci.yml data-plane 작업, WSL 전체 회귀 1회(분리 실행)
- 2026-11-10 단계 3 완료 — 커밋 `691d93f`(`ensure_shared_ns`: 새 바인드에 `--make-private` 뒤 `--make-rshared`, 단위 테스트 2개), `02f6d7f`(ci.yml `data-plane` 작업, 준비 스크립트 주석, `docs/testing.md` CI 절, 설계 §6), `5cb8b17`(testing.md 테스트 수 989). 제품 코드 내용 해시 `9a023d13…`(메인 계산, HEAD `5cb8b17`). WSL 전체 회귀 `/var/tmp/anf-clone-tests/20261110T102847Z`: 113 통과, skip 0, exit 0, 5,198 s, 남은 것 없음(메인이 summary.txt와 콘솔 `rc=0` 확인). AC-05 손 확인 출력 `/var/tmp/anf-clone-tests/fr11-ac05`. implementer가 push하지 않음
- 2026-11-10 PR #20 열림(pull_request run 42811747210에서 data-plane 두 조각 실행). 단계 4 1회차 시작 — real-env-verifier. 메인이 ADR §9.1·§9.3·§10 S3, CLAUDE.md 갱신(`932cdc8`, 러너 실행을 취소하지 않으려고 push는 판정 뒤). 개념 문서 갱신을 concept-explainer에 맡김
- 2026-11-10 단계 4 1회차 완료 — PASS 7, FAIL 1(AC-01) (`04_verifier_report_dp.md`). run 42811747210: `rest` success(106), `throughput` failure(7 중 2 실패: `test_ac04_limit_changes_during_io` w41 한도를 올린 직후 첫 1초 창 0.880, `test_ac09_auto_to_manual_keeps_the_limit` 바꾼 뒤 quick 쓰기 0.8675). 한도 초과는 없음, tc 값은 맞음 — 공유 러너에서 한도를 올린 직후의 하한 판정이 흔들린다. AC-03은 draft PR #21(닫음)로 PASS. 자동 채택: 시험의 하한 판정을 고친다(상한은 모든 창 그대로, 하한은 안정된 뒤 창/중앙값). implementer에 수정 맡김
- 2026-11-10 AC-01 수정 `c66e51a`(시험만): AC-04 하한은 `Succeeded` 뒤 1~5 s 창의 중앙값, AC-09·AC-07(e)의 한 번 쓰기는 `measure`(6회 중앙값), 상한·범위 그대로. 워크플로에 `journalctl -k -b` 추가. WSL 처리량 파일 7/7 통과(`/var/tmp/anf-clone-tests/fr11-tp-floor`, 2,424 s). 제품 해시 `9a023d13…` 그대로(메인 계산). push, 단계 4 2회차 시작
- 2026-11-10 단계 4 2회차 완료 — PASS 7, FAIL 1(AC-01, 간헐) (`04_verifier_report_dp_r2.md`). PR #20 run 42824999459는 네 작업 모두 success(113 통과, skip 0; throughput 38m42s, rest 36m32s). 1회차의 하한 문제는 러너 10회에서 0건. 그러나 처리량 파일 9회 반복(draft PR #22, 닫음) 중 tp8이 `test_ac07_limit_survives_lifecycle` 단계 (c)(`docker rm -f` 직후 볼륨 재PUT)에서 실패: 작업이 1 s 만에 `InternalServerError`로 Failed, 시험이 상태를 보지 않아 450 s 뒤 timeout. 커널 로그에 rpcbind unregister 지연(약 2분 20초). 원인은 추론(agent·anf-api 로그가 artifact에 없음). implementer에 맡김: 로그 수집 + 시험이 작업 실패를 바로 드러냄 → 러너에서 좁힌 반복으로 원인 확인 → 수정
