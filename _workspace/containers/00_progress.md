# containers 진행 기록

- 상태: done (PR의 CI 통과 뒤 merge)
- FR: FR-13 (컨테이너) + PRD §9 데모 대본 스크립트
- 마지막 완료 단계: 6
- 재개할 단계: 없음 (출하: PR → CI → merge)
- 브랜치: `feature/containers` (`main` `e7d87d5`에서)
- 검증 대상 코드: `4887031`(2회차. 참고 해시 `64530317…`). 그 뒤 `814afb1`이 `scripts/demo.py`의 `follows_limit`을 바꿈(실환경 재실행 없음). 1회차는 `01ab88e` (`feature/containers`). 제품 코드 내용 해시 `7c38d8c7…` 그대로(`backend/`·`pyproject.toml` 불변). FR-13의 변경은 `deploy/`·`scripts/`에 있어, 그것까지 넣은 참고 해시는 `c32b76d8db5425bbd661f42406b7dcf52bd932a17240c27fad194dd726508f0f`(implementer 계산: pyproject, backend(테스트 제외), deploy, scripts, .dockerignore, .gitattributes)
- implementer 에이전트 ID: ab65b077705ac7d85 (스파이크 S9부터)
- verifier 에이전트 ID: a6d70a2527a4ad809 (1회차)
- concept-explainer 에이전트 ID: aa115f9d36091e196
- 미해결: 없음

## 선행 확인 (0단계)

- PRD §8: 조사 생략. 개념 문서는 엔지니어링 관점, ANF·ONTAP 절 "해당 없음".
- 의존: FR-01~FR-12. FR-11은 `partial`(사용자 결정으로 merge), 나머지 done.
- 스파이크 S9 조건부 통과: 전부 컨테이너로 떠서 데모 1~6단계 62 s. 조건 — 이 기기에 compose가 없었다, agent 컨테이너에 다섯 설정이 필요하다.
- 사용자 결정(AskUserQuestion, 2026-11-10): compose를 apt로 설치 → 메인이 설치함(`docker-compose-v2` 2.40.3, `docker-buildx` 0.30.1).

## 수락 기준별 최신 결과

2회차 10/10 PASS(AC-09는 PR의 CI). 기준별 표는 `docs/concepts/containers.md` 5절과 `04_verifier_report.md`, `04_verifier_report_r2.md`. AC-03만 1회차 FAIL → 2회차 PASS.

## 이력

- 2026-11-10 스파이크 S9 (FR-12의 CI 대기 중에 실행, `_workspace/spikes/S9.md`)
- 2026-11-10 단계 0 — FR-12 merge(`e7d87d5`) 뒤 브랜치 생성
- 2026-11-10 단계 2 완료 — 묻는 결정 1개(compose 설치: 설치), 결정 1~12 자동 채택
- 2026-11-10 단계 3 시작 — 같은 implementer에 구현을 맡김
- 2026-11-10 단계 3 완료 — 커밋 `27b8696`(compose 스택), `ab03418`(agent LVM이 호스트 udev를 기다림: `/run/udev:ro` + `ipc: host`, S9 L4), `53f7c8b`·`c99a400`(`scripts/demo.py`), `d2388b1`(compose e2e, 실행기 8081, README), `01ab88e`. 새 e2e 5 passed·252 s(`/var/tmp/anf-clone-tests/fr13-compose-222653`), 데모 85 s, 메모리 최대 used 1,095 MiB, 일반 사용자 첫 빌드 62 s·이후 약 10 s
- 2026-11-10 자동 채택(결정 13): `--build`를 두고 AC-02를 "리소스·데이터·인스턴스가 바뀌지 않는다"로 고침
- 2026-11-10 단계 4 1회차(real-env-verifier), 단계 5(concept-explainer) 시작
- 2026-11-10 단계 5 완료 — 개념 문서 `docs/concepts/containers.md`(Q&A 13개). 결정 14(LVM 백업은 바인드하지 않음) 추가
- 2026-11-10 단계 4 1회차 완료 — PASS 9, FAIL 1(AC-03, 간헐 3/10), AC-09는 PR 뒤 (`04_verifier_report.md`). AC-01: WSL 재시작 직후 일반 사용자로 README 명령 그대로 3번, 8.8~10.4 s에 healthy. AC-05는 headless Chrome. AC-03: 데모 6단계가 한도 10 MiB/s에서 중앙값 72~82%(스토리지 흔들림, 한도 초과 없음). 판정 밖: `/var/lib/anf-clone`이 없는 새 기기에서는 바인드 원본이 없어 실패(같은 모양으로 재현). 자동 채택: 데모 6단계 판정을 상한 + "한도를 바꾸면 따라 바뀜"으로(90% 하한은 FR-08 시험의 몫), `create_host_path`. implementer에 수정과 10회 반복을 맡김
- 2026-11-10 수정 `dcf18d7`·`8c02910`·`9120af6`: 데모 6단계를 천장 + "따라 바뀜"으로(한도 20 → 5), `create_host_path`. 확인 10회 중 07회가 5 MiB/s의 5.12(102.4%)로 옛 천장 101%에 걸림
- 2026-11-10 자동 채택: 천장에 I/O 하나(1 MiB ÷ 6 s)의 여유(`85428ec`, `4887031`). 10회 측정값 재판정 10/10, compose e2e 5 passed(`/var/tmp/anf-clone-tests/fr13-compose-235101`)
- 2026-11-10 단계 4 2회차 — 기록 판정으로 PASS 9·AC-03 UNVERIFIED(HEAD 실제 실행 2회뿐) → 메인이 HEAD로 데모 8회(`/var/tmp/fr13-demo-repeat-head`, 8/8) → AC-03 PASS, 10/10 (`04_verifier_report_r2.md`)
- 2026-11-10 자동 채택(verifier 2회차 제안): `follows_limit`의 내리기 전 쪽을 가장 빠른 회 > 새 한도의 천장으로(`814afb1`, `8732c9b`). 8회차 중앙값 7.25(문턱 5.05), 한 회 최저 3.68. 실측 20회 재판정 20/20(`rejudge-max.txt`). 실환경 재실행은 하지 않고 PR의 CI에 맡김
- 2026-11-10 단계 5 갱신(concept-explainer), 단계 6 완료 — feature-status `done`, 개념 문서 검증 결과, `docs/testing.md` 테스트 수 1,051. push·PR
