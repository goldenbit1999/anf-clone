# test-automation 진행 기록

- 상태: in_progress
- FR: FR-10 (테스트 자동화)
- 마지막 완료 단계: 3
- 재개할 단계: 4 (검증 1회차 진행 중. 전체 실행은 다시 돌리지 않고 실행 A·C의 결과 파일로 판정)
- 검증 대상 코드: 커밋 `6993c17` (`feature/test-automation`), 제품 코드 내용 해시 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3` (그대로)
- implementer 에이전트 ID: ac5a9f5d4f40d0e32 (구현, 2026-11-09)
- verifier 에이전트 ID: af5e52bae07225091 (1회차, 2026-11-09)
- 미해결: 없음

## 선행 확인 (0단계)

- PRD §8: FR-10은 1단계(조사)를 생략한다. 개념 문서는 엔지니어링 관점, ANF·ONTAP 절은 "해당 없음".
- 의존: FR-08 done (`6aab1d1`). FR-01~FR-09 모두 done.
- 스파이크: 새로 필요한 것 없음(새 데이터 플레인 동작에 기대지 않는다).
- 브랜치: `feature/test-automation` (`main` `cd82054`에서).
- 묻는 결정: 없음. 결정 1~13 자동 채택 (`02_main_design.md` §4).

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | 명령 하나로 전체, 종료 코드 0, skip 0 | UNVERIFIED (명령 하나로 13개 파일을 끝까지 돈 실행이 없다. 실행 A 9개 + 실행 C 4개를 합치면 113개 통과·skip 0. 2회차에서 한 번의 전체 실행으로 닫는다) | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-02 | 마운트·스냅샷·처리량의 클라이언트 관찰 테스트 포함 | PASS — 항목마다 클라이언트 쪽 근거가 `.jsonl`에 있음(ENOSPC, `Read-only file system`, 한도 대비 0.99~0.997, 제한 없는 볼륨 약 204배) | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-03 | 대응표와 node ID | PASS — PRD 문장 25개가 대응표 23행에, node ID 41개 모두 수집, 데이터 플레인 29개 통과 | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-04 | 사전 점검 2, skip·실패 1 | PASS — (a) 일반 사용자·포트 점유 exit 2, (b) skip 5 → exit 1, (c) 실패 뒤 나머지 끝까지 돌고 exit 1 | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-05 | 남기지 않음 | PASS — 실행 C 남은 것 없음, 일부러 남긴 컨테이너를 출력하고 exit 1 | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-06 | 재부팅 뒤 첫 실행 | PASS — 실행 C가 부팅 7초 뒤 VG를 스스로 붙이고 28 통과(기준선에 실행 B의 볼륨 2개), `045258Z`도 같은 방식 37 통과 | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-07 | CI가 같은 판정 코드 사용, Actions 통과 | UNVERIFIED (`ci.yml`이 `junit_gate.py`를 부르는 것은 확인. Actions 실행은 PR 뒤) | `04_verifier_report.md` (1회차) | `6993c17` |
| AC-08 | 제품 코드 해시 불변, 비데이터 플레인 묶음 skip 0 | PASS — 해시 그대로, WSL `-m "not dataplane"` 988 passed·skip 0, ruff 통과 | `04_verifier_report.md` (1회차) | `6993c17` |

## 이력

- 2026-11-09 단계 0 완료 — 로드맵 재개. 브랜치 생성, 문서 확인. 조사 생략(PRD §8)
- 2026-11-09 단계 2 완료 — 설계 `02_main_design.md`. 범위: 실행기 `scripts/run-dataplane-tests.sh`, `junit_gate.py`(CI와 공용), `docs/testing.md` 대응표, 빈 수락 기준 채우기. 결정 1~13 자동 채택
- 2026-11-09 단계 3 시작 — feature-implementer에 구현을 맡김
- 2026-11-09 단계 3 구현 커밋 — `d2eff17`(junit_gate + ci.yml), `9227be6`(실행기), `744b17d`(docs/testing.md + 대응표 검사), `6993c17`(설계 §8). 제품 코드 내용 해시 `f99bc5cf…` 그대로(메인 계산, HEAD `6993c17`). implementer의 전체 실행(`/var/tmp/anf-clone-tests/20261110T050559Z`, 113개·13개 파일 수집)은 9개 파일이 pytest 종료 코드 0으로 끝난 뒤 10번째(처리량 데이터, 3번째 테스트 중)에서 에이전트 중지와 함께 끊겼다. implementer의 최종 보고는 없다
- 2026-11-09 사용자 결정 — (1) 전체 실행을 verifier가 다시 돌리지 않는다: 실행 결과 파일로 판정하고 verifier는 짧은 항목(AC-04·05·06·08)만 직접 돌린다. (2) 끊긴 실행은 남은 4개 파일만 실행기로 돌려 앞 9개의 결과와 합친다. AC-01은 두 번에 나눠 확인한 것으로 기록한다
- 2026-11-09 메인이 끊긴 실행의 잔여물을 치움(기준선은 비어 있었다): 컨테이너 `anf-nfs-149527ef…`·`anf-nfs-a0eeb816…`·`anfe2e-cli-e042aafc`, LV `vol_149527ef…`·`vol_a0eeb816…`(경로 `e2ev3831-d4r3`·`e2ev3831-d4w41`), `ns/`·`exports/`의 해당 폴더. 남은 4개 파일 실행 시작(`/var/tmp/anf-clone-tests/console-rest.log`)
- 2026-11-09 남은 4개 파일 실행 B(`20261110T061156Z`)가 처리량 데이터 7번째 테스트 중 호스트 메모리 부족으로 끊김(Claude Code가 백그라운드 명령을 강제 종료). 사용자 지시로 다시 진행
- 2026-11-09 실행 C(`/var/tmp/anf-clone-tests/20261110T065647Z`, 콘솔 `console-rest2.log`): WSL 안에서 분리해 띄움. WSL 재부팅 직후라 실행기가 VG를 스스로 붙였다. 실행 B가 남긴 볼륨 2개(`e2evbf9e-d9`, `-d9s`)는 기준선에 잡힌 채 돌았다. 4개 파일 28 passed, skip 0, 종료 코드 0, 2,767초(처리량 데이터 2,256 · 볼륨 계약 120 · 데이터 215 · 복구 176). 실행 A의 9개 파일과 합쳐 13개 파일. 실행 뒤 메인이 그 볼륨 2개와 인스턴스를 지움(LV `aggr0`만, 컨테이너 0)
- 2026-11-09 단계 4 1회차 시작 — real-env-verifier에 맡김
- 2026-11-10 단계 4 1회차 완료 — PASS 6, UNVERIFIED 2(AC-01, AC-07), FAIL 0 (`04_verifier_report.md`). 판정 밖 관찰 중 문서 둘을 메인이 고친다: `docs/testing.md` FR-08 행의 "회마다" → 첫 회를 버린 5회의 중앙값, §3 소요 시간(전체 실행 실측 뒤 채움)
- 2026-11-10 AC-01을 닫는 전체 실행 D 시작 — 인자 없이 WSL 안에서 분리(`/var/tmp/anf-clone-tests/20261110T080605Z`, 콘솔 `console-full2.log`). 시작 때 데이터 플레인 비어 있음, VG는 실행기가 붙임
