# metrics 진행 기록

- 상태: in_progress
- FR: FR-12 (메트릭)
- 마지막 완료 단계: 3 (구현)
- 재개할 단계: 4 (검증 1회차 진행 중) → 5·6 → PR
- 브랜치: `feature/metrics` (`main` `a21541f`에서)
- 검증 대상 코드: `e80c8e7` (`feature/metrics`), 제품 코드 내용 해시 `7c38d8c7fdf750e4a4c32b06802475b0a5e3e2632ea1f60da9e7ac89ac2df4ed` (메인 계산. 시작 시 `73dee8f9…`)
- researcher 에이전트 ID: abb206742a6b464de
- implementer 에이전트 ID: a7d790b1fb5b7e3f8 (스파이크 S8부터)
- verifier 에이전트 ID: a2a21e0e8411ece06 (1회차)
- concept-explainer 에이전트 ID: adc11daeedd5414b3
- 미해결: 없음

## 선행 확인 (0단계)

- PRD §8: 조사는 Azure Monitor 메트릭 대응으로 한정. 의존: FR-08 done, FR-09 done.
- FR-11은 `partial`로 merge됨(사용자 결정). FR-12는 그 위에서 시작한다.
- 스파이크 S8: knfsd 통계의 netns 범위, 처리량 출처 비교, IOPS, 한도 도달 신호, 사용량, 수집 비용, Prometheus 컨테이너.

## 수락 기준별 최신 결과

(설계 뒤 채움)

## 이력

- 2026-11-10 단계 0 완료 — 브랜치 생성
- 2026-11-10 단계 1 완료 — 조사 브리프 `01_researcher_brief.md`(한도 도달, 미확인 목록 있음). ANF 볼륨 메트릭은 차원 없는 5분 평균, read/write/other/total × throughput·IOPS·latency. 커널 소스로는 `io`·`rpc`·`proc4ops`가 netns별, `proc3`는 전역(실측 필요)
- 2026-11-10 스파이크 S8 시작 — feature-implementer
- 2026-11-10 스파이크 S8 조건부 통과(`aa0a313`): `io`·`rpc`·`proc4ops`는 netns별, `proc3`는 전역. `io`는 fio 바이트와 같음. HTB `overlimits`는 신호로 못 씀. Prometheus v3.15.1 컨테이너(host 네트워크) 동작
- 2026-11-10 단계 2 완료 — 묻는 결정 없음, 결정 1~14 자동 채택. 수락 기준 AC-01~13
- 2026-11-10 단계 3 시작 — 같은 implementer에 구현을 맡김
- 2026-11-10 단계 3 완료 — 커밋 `e2581cd`(agent `/metrics`), `37a341c`(anf-api `/metrics`), `3c403b1`(Prometheus 컨테이너·데이터 e2e·실행기 9090), `290f726`(대시보드 차트), `e80c8e7`(testing.md, 설계 §7). 새 e2e 5 passed·skip 0·359 s(`/var/tmp/anf-clone-tests/fr12-e2e-1`), WSL not-dataplane 1016 passed·skip 0, 프런트엔드 48 tests·build 통과. 기존 데이터 플레인 파일은 다시 돌리지 않음(결정 14: PR CI가 회귀)
- 2026-11-10 implementer가 올린 두 질문을 메인이 자동 채택으로 정함: (15) 요청 수 출처는 `rpc` 줄 그대로(고부하에서 0.01~0.02% 덜 셈을 문서에 적는다. `rc` 합은 v3·v4.1에서 뜻이 달라 설명이 어렵다), (16) CI의 Prometheus 이미지는 Docker Hub 그대로(pull 한도에 걸리면 그때 quay.io로)
- 2026-11-10 단계 4 1회차 시작(real-env-verifier), 단계 5 개념 문서(concept-explainer) 병행. 메인이 `CLAUDE.md`·ADR §8·§9.3·§10 S8 갱신
- 2026-11-10 단계 5 완료 — 개념 문서 `docs/concepts/metrics.md`(Q&A 13개). 검증 결과 자리는 메인이 채움
- 2026-11-10 단계 4 1회차 완료 — PASS 11, FAIL 1(AC-06, 간헐), AC-12의 CI 부분은 PR 뒤 (`04_verifier_report.md`). AC-06: PATCH 뒤 20 MiB/s 구간에서 Prometheus 값이 한도의 76.7%(3번 중 1번). fio가 실제로 덜 썼다(WSL 스토리지 흔들림) — 메트릭 결함이 아님. AC-08은 headless Chrome으로 PASS(확장 프로그램은 연결돼 있지 않았다). 자동 채택: AC-06 시험을 "Prometheus 대 fio ±5%" + "한도의 101% 이하, PATCH 뒤 중앙값 > PATCH 전 최댓값"으로 나눔. implementer에 수정과 9회 반복(약 23분), `run-prometheus.sh`의 `-v`를 맡김
