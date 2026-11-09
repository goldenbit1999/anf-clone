# throughput-limit 진행 기록

- 상태: done
- FR: FR-08 (처리량 제한)
- 마지막 완료 단계: 6
- 재개할 단계: 없음 (출하: push, PR, CI, merge)
- 검증 대상 코드: `0b44a8f` 제품 코드 (`feature/throughput-limit`, 내용 해시 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`), e2e 시험 코드 `3328486`
- implementer 에이전트 ID: acadc68bbbccab96e (스파이크 S7부터, 구현도 같은 ID)
- researcher 에이전트 ID: ae21e308facd1f3ae
- verifier 에이전트 ID: a211d76699a7a9b57
- 미해결: 없음

## 선행 확인 (0단계)

- 상위 리소스: 계정·용량 풀·볼륨·스냅샷·되돌리기·새 볼륨 복원 모두 `done` (`docs/feature-status.md`, FR-07 merge `8e42911`).
- 결정: D-12 = T1n (볼륨마다 knfsd 인스턴스와 IP, 인스턴스 호스트 쪽 veth에 clsact → 양방향을 IFB 하나로 → HTB 클래스 하나, 읽기·쓰기 합산). 인스턴스와 IP는 볼륨 사이클에서 만들었고 tc는 이 FR에서 더한다 (ADR §7.3, CLAUDE.md "Decided").
- 스파이크: S2(`_workspace/spikes/S2.md`)는 2026-11-07, 볼륨 구현 전의 실험용 인스턴스(`s2-srv-*`, 네트워크 `s2-net`)에서 쟀다: v3·v4.1 모두 설정값의 약 95%(헤더 바이트 포함), 읽기+쓰기 합산, `tc class change`로 실시간 변경, 같은 클라이언트의 다른 볼륨은 영향 없음. 지금 agent의 인스턴스(`anf-nfs-<uuid>`, `anf-vnet`, 재시작·되돌리기 창·복구)에서 tc를 건 적은 없다. 또 검증은 `ANF_MIN_VOLUME_SIZE_GIB=1`의 작은 볼륨을 쓰는데, Auto QoS 공식이면 1 GiB Premium이 0.0625 MiB/s다. 이런 낮은 한도에서 NFS 동작(마운트, v4.1 lease 갱신)을 잰 적이 없다. 그래서 설계 확정 전에 스파이크 S7로 확인한다 (사이클 0단계 5번).
- 위험: ADR R-08 (클라이언트와 서버가 같은 커널, LOCALIO 꺼짐 확인됨), R-01 (해소됨).
- 이미 아는 사실: 풀은 `qosType` Auto/Manual을 받고 Auto → Manual은 한 방향이다 (`capacity_pools.py`). 볼륨은 Manual QoS 풀을 거절하고 `throughputMibps`를 미룬 기능으로 거절한다 (`volumes.py` `_NOT_YET`). `actualThroughputMibps` = 할당량(TiB) × 서비스 수준 단가를 응답에 이미 보인다.
- 2단계에서 정할 것 (후보):
  - Manual QoS 범위: 볼륨 `throughputMibps`(생성·PATCH), 풀의 처리량 예산 검사, Auto → Manual 전환 때 기존 볼륨 값
  - Auto QoS 한도를 바꾸는 방법: 할당량 변경은 FR-16이다. FR-08 수락 기준 "제한을 바꾸면 잰 값도 바뀐다"를 무엇으로 보일지
  - 작은 검증 볼륨의 낮은 한도를 어떻게 다룰지
  - tc 적용 시점(인스턴스 시작, 재시작, 복구)과 헤더 바이트 보정, 허용 오차
  - agent API: ONTAP QoS policy(`/api/storage/qos/policies`, 볼륨 `qos.policy`)와의 대응

## 수락 기준별 최신 결과

| 기준 ID | 기준 | 최신 결과 | 근거 보고서 | 검증 대상 코드 |
| --- | --- | --- | --- | --- |
| AC-01 | Auto 값과 데이터 | PASS | `04_verifier_report.md` (1회차) — 6.312·0.062·0.016, Ultra 80 GiB v3 10 MiB/s 쓰기 98.1%·읽기 97.2%, Ultra 40 GiB v4.1 99.1% | `0b44a8f` |
| AC-02 | Manual 생성 | PASS | `04_verifier_report.md` (1회차) — 10·20·12.5 각 201 → Succeeded, utilized 30.0 → 42.5, 95.6~97.8% | `0b44a8f` |
| AC-03 | 읽기+쓰기 합산 | PASS | `04_verifier_report.md` (1회차) — 97.8%(v4.1), 96.1%(v3) | `0b44a8f` |
| AC-04 | 한도 변경(PRD) | PASS | `04_verifier_report.md` (1회차) — PATCH 10→30→5 Succeeded 2.1~4.5 s, 뒤 1초 창 97.5~100.8%, 재PUT 15 → 97.5~98.5%, fio 오류 0 | `0b44a8f` |
| AC-05 | 제한 없는 볼륨과 차이·독립성 | PASS(읽기) | `04_verifier_report.md` (1회차) — B가 A의 205.7배, A 단독 97.1% / 함께 99.25%. 쓰기 표본(참고)은 A가 71~86%로 디스크 경합 | `0b44a8f` |
| AC-06 | 작은 Auto 한도 | PASS | `04_verifier_report.md` (1회차) — 0.062 MiB/s, 큰 쓰기 0.0598/0.0597, timeouts 0, dmesg 0 | `0b44a8f` |
| AC-07 | 수명 주기 | PASS | `04_verifier_report.md` (1회차) — (a)~(e) 98.2~98.8%, (d) 2.5 s 멈춤 뒤 복귀, (f) netns·IFB 없음 | `0b44a8f` |
| AC-08 | 거절 | PASS | `04_verifier_report.md` (1회차) — §4.2 행마다 코드·문구, 남은 예산 28 정확히 받음, 바쁜 풀 Manual 전환 409 | `0b44a8f` |
| AC-09 | Auto → Manual | PASS | `04_verifier_report.md` (1회차) — 5.0·0.062 채움, utilized 5.062 그대로, 99.1% 전후 같음, 0.062 재PUT 200 | `0b44a8f` |
| AC-10 | 실패·재시작 | PASS | `04_verifier_report.md` (1회차) — SIGKILL 뒤 Succeeded 17 → 97.2%, 주입 실패 Failed 17 유지, 재시도 9 → 98.2% | `0b44a8f` |
| AC-11 | agent API | PASS | `04_verifier_report.md` (1회차) — qos 레코드, qos 없으면 tc 없음, 모양 오류 10가지 400, 통합 30 passed | `0b44a8f` |
| AC-12 | 회귀 | PASS | `04_verifier_report_r2.md` (2회차) — 1회차 FAIL은 처리량 데이터 e2e의 벽시계 표본 시각. `3328486`(`time.monotonic()`) 뒤 그 파일 7 passed(2,248 s), 실행 중 벽시계 건너뜀 70번(AC-07 구간 12번)에도 한도 넘은 창 0. 나머지 회귀는 1회차 통과(기존 14개 2,385 s 대 FR-07 2,326 s) | `0b44a8f` / e2e `3328486` |

## 이력
- 2026-11-09 단계 0 완료 — 브랜치 `feature/throughput-limit`. 조사와 스파이크 S7을 함께 시작
- 2026-11-09 단계 1 완료 — 브리프 `01_researcher_brief.md`(조사 상태 "한도 도달": 30턴 상한, 받은 원문으로 SendMessage 이어 쓰기). 미확인(Manual 풀 볼륨의 `throughputMibps` 생략 시 기본값, Auto 풀 볼륨에 보낸 값, 예산 초과 오류 코드, Auto→Manual 전환 뒤 기존 볼륨 값, Manual 풀 축소)은 설계를 막지 않고 클론 규칙으로 정한다. ONTAP 대응(fixed QoS policy, 볼륨 `qos.policy`)은 [추론]으로 채워졌다
- 2026-11-09 스파이크 S7 조건부 통과 (`_workspace/spikes/S7.md`): 실제 인스턴스에서 T1n 동작, 인스턴스가 다시 뜰 때마다 tc를 다시 걸어야 함, 0.0625 MiB/s에서도 오류 없지만 같은 연결 메타데이터 1분 넘음, netns 안 `ifb0` 변형도 같은 결과
- 2026-11-09 단계 2 완료 — 설계 `02_main_design.md`. 묻는 결정 없음, 결정 1~19 자동 채택(Auto+Manual 범위, 공식 그대로·하한 없음·셋째 자리 반올림, Manual `throughputMibps` 필수·1~4,500·예산 동기 400, Auto 풀 값 400, Auto→Manual 값 채우기, agent POST `qos.policy.max_throughput_mbps`, tc는 인스턴스 netns 안, `start`→걸기→`wait_ready`, 태그 `anf_qos`, rate ÷ 0.9564, fq_codel, 허용 오차 90~101%, 기존 데이터 e2e는 Manual 풀로). ADR §2.3·§7.3·§8·§10 S7·D-12 상태 갱신
- 2026-11-09 단계 3 1차 보고 — 커밋 `9c0b84d`(agent), `540957d`(API), `b6d2711`(e2e), `38689e4`(§9). Windows 911 passed / 175 skipped, ruff 통과, WSL 통합 30 passed, FR-08 계약 e2e 7 passed, 데이터 e2e 7 passed. AC-12 회귀는 14개 파일 중 5개(계정·계정 결함·풀·풀 결함·볼륨 계약, 시간 FR-07과 같음)만 돌고 호스트 메모리 부족으로 실행기가 강제 종료됨(WSL page cache 6.8 GB). 리더 자동 채택: §9-5 갱신에서 같은 값이면 범위 검사 안 함, §9-4 그대로, AC-05 읽기. 카운터 문장(§6.3, ADR §8)을 고침. implementer에게 §9-5 구현과 남은 10개 파일 회귀(파일 사이 `drop_caches`)를 맡김
- 2026-11-09 단계 3 완료 — `0b44a8f` §9-5(갱신에서 같은 값이면 범위 검사 안 함), `a3ad172` §9-13(오류 순서: 없는 볼륨에 PATCH 0.5가 400 → 404). Windows 914 passed / 176 skipped, ruff 통과. AC-12 회귀 11개 파일(파일 사이 `drop_caches`) 모두 통과, skip 0, 시간은 FR-07과 비슷(볼륨 데이터 214 s 대 192 s, 복원 데이터 223 s 대 179 s). 첫 실행은 WSL 재부팅 뒤 VG가 붙지 않아 모든 파일이 setup 오류였다. agent를 한 번 띄워 풀었다(e2e `agent` 픽스처의 기준선이 VG를 전제함, FR-08 밖). 내용 해시 `f99bc5cf…`
- 2026-11-09 단계 4 1회차 — 11 PASS, 1 FAIL(AC-12: 처리량 데이터 e2e의 1초 창 표본 시각이 `time.time()`이라 WSL 벽시계 뒤로 건너뜀이 한도 초과로 읽힘. 시험 코드 결함, 제품 해시 그대로). 리더 결정(자동 채택): AC-05는 "함께 읽는 동안"으로 판정, 쓰기 경합은 개념 문서에 "한도는 상한일 뿐 디스크 경합을 막지 않는다"로 적음. 판정 시계는 게스트 단조 시계 그대로(ADR §7.3에 FR-08 관찰 추가). 검증 드라이버는 `verify/fr08_verify.py`로 옮겨 남김. implementer에게 `time.monotonic()` 수정을 맡김
- 2026-11-09 단계 4 2회차 — AC-12 PASS(처리량 데이터 e2e 7 passed, 벽시계 건너뜀 속에서 한도 넘은 창 0). 누적 12/12 PASS
- 2026-11-09 단계 5 완료 — 개념 문서 `docs/concepts/throughput-limit.md`(Q&A 13개, `3f877f3`). ADR §7.3 "스토리지 계층" 근거 표시를 [추론]으로 고침
- 2026-11-09 단계 6 완료 — feature-status `done`, CLAUDE.md "Decided"에 FR-08 항목. 사용자 요청: 이 PR까지만 하고 로드맵 멈춤
