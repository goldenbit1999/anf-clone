# test-automation (FR-10) 검증 보고서 — 1회차

- 진행 상태: 완료
- 검증일: 2026-11-09~10 (PST. WSL 게스트 UTC로는 2026-11-10)
- 검증 대상 코드: HEAD `db3468c` (`6993c17` 다음 커밋. `_workspace/test-automation/00_progress.md`만 바꿨고 `git diff --stat 6993c17 HEAD -- scripts backend pyproject.toml .github`는 비어 있다). 제품 코드 내용 해시 시작·끝 모두 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`. 미커밋 변경: 이 보고서, `docs/ai-readiness-map.html`, `docs/ai-readiness-score.json`(검증 대상 밖)
- 보관: 이번 회차의 로그와 판정에 쓴 실행 결과의 사본은 `C:\Users\mkimh\AppData\Local\Temp\claude\10ea37fea4129b23\781e2b00-7c2f-4ac4-8d3a-50b50705a3a8\scratchpad\fr10-verify-r1\` (`mine\root`: AC-04·05 실행 출력과 통과 ID 목록, `mine\var`: AC-08 JUnit XML·로그, `runs`: 실행 A·C·`20261110T045258Z`와 콘솔 3개). 파일별 sha256 목록의 해시가 원본과 같음을 확인한 뒤 WSL의 이번 회차 사본(`/root/fr10-verify-r1`, `/var/tmp/fr10-verify-r1`)을 지웠다. `/var/tmp/anf-clone-tests/`의 원본은 리더의 실행 기록이라 그대로 두었다. 판독 스크립트는 같은 scratchpad의 `tests\evidence_dump.py`, `tests\ac03_check.py`.
- 이번 회차 범위: 전체(AC-01~AC-08). 사용자 결정에 따라 데이터 플레인 전체 묶음은 다시 돌리지 않고, 끝난 실행 A(`20261110T050559Z`, 앞 9개 파일)와 실행 C(`20261110T065647Z`, 남은 4개 파일)의 결과 파일로 AC-01·AC-02·AC-03(통과 부분)·AC-05(전체 실행 뒤)·AC-06을 판정한다. AC-04, AC-05(일부러 남기기), AC-03(node ID 수집), AC-08은 직접 실행한다. AC-07은 PR 전이라 `ci.yml` 확인만 한다.

## 환경 사전 점검
| 항목 | 결과 |
| --- | --- |
| WSL 배포판 | `wsl -l -v`: Ubuntu `Stopped`(유휴 종료)였다. 첫 명령으로 다시 뜸. 커널 `6.18.58.1-microsoft-standard-WSL2`, 게스트 `/proc/uptime` 2,870 s(부팅 0 = 22:56:40 PST, 실행 C 직전 부팅과 같은 부팅) |
| 커널 모듈 | `nfsd`, `dm_thin_pool`, `ifb`, `sch_htb` 로드됨. `fs.leases-enable = 0` |
| Docker | Engine `29.1.3 linux`, `systemctl is-active docker` = active, `readlink /usr/bin/docker` 비어 있음(Desktop 연동 아님) |
| 데이터 플레인 준비 | 이미지 `anf-nfs-server`·`anf-nfs-client`, `anf-vnet` = `172.30.0.0/24 172.30.0.0/25`, VG `anf` 붙어 있음(`/dev/loop0` → `aggr0.img`) |
| 데이터 플레인 비어 있음 | LV `aggr0`뿐, 컨테이너 0, `ns/`·`exports/` 비어 있음, 8080·8090 리스너 없음 |
| venv | `/home/mkimhome1/.venvs/anf-clone`, Python 3.12.3, pytest 9.2.0. 저장소 주인 uid 1000 |
| 메모리 | WSL `free -m`: total 7,778 MiB, available 7,003 MiB |
| 결과 파일 | `/var/tmp/anf-clone-tests/`에 실행 A `20261110T050559Z`, 실행 B `20261110T061156Z`(근거로 쓰지 않음), 실행 C `20261110T065647Z`, 구현 때의 재부팅 시험 `20261110T045258Z`, 콘솔 `console-full.log`·`console-rest.log`·`console-rest2.log`·`console-ac06.log`가 남아 있다 |

## 결과 요약
PASS 6 / FAIL 0 / UNVERIFIED 2 (AC-01, AC-07)

- AC-01: 13개 파일·113개가 모두 통과·skip 0인 것은 확인했지만, 명령 하나가 끝까지 돌아 종료 코드 0으로 끝난 실행은 없다(실행 A가 끊겨 두 실행으로 나눔).
- AC-07: `ci.yml`이 `junit_gate.py`를 부르는 것은 확인했다. PR이 없어 Actions 실행은 보지 못했다.

## 수락 기준별 최신 결과
| 기준 ID | 결과 | 확인한 회차 |
| --- | --- | --- |
| AC-01 | UNVERIFIED | 1회차 |
| AC-02 | PASS | 1회차 |
| AC-03 | PASS | 1회차 |
| AC-04 | PASS | 1회차 |
| AC-05 | PASS | 1회차 |
| AC-06 | PASS | 1회차 |
| AC-07 | UNVERIFIED | 1회차 |
| AC-08 | PASS | 1회차 |

## 항목별 결과

### 실행 A·C가 검증 대상 코드와 같은지 (AC-01·02·03·05·06의 전제)
- 커밋 시각(-0800): `9227be6`(실행기) 20:51:36, `744b17d` 21:00:16, `6993c17` 21:01:31. 실행 A 기준선 21:05:59, 실행 C 기준선 22:56:47, 실행 C 끝 23:43:25.
- `git log -1 -- scripts backend/tests` = `744b17d`(21:00:16). 그 뒤 `scripts`·`backend/tests`를 바꾼 커밋이 없다. `git diff --stat 6993c17 HEAD -- scripts backend pyproject.toml .github`는 비어 있고 `git status`에 해당 경로의 변경이 없다.
- 파일 수정 시각: `scripts`·`backend/tests`·`pyproject.toml`·`ci.yml`에서 가장 새 파일은 `backend/tests/unit/test_testing_doc.py` 20:53:14(실행기가 돌리지 않는 단위 테스트), `scripts/run-dataplane-tests.sh` 20:50:00. 제품 코드에서 가장 새 파일은 10:34:27. WSL에서 `find backend scripts pyproject.toml -newermt "2026-11-09 21:05:00" -type f`(캐시 제외) 결과 없음.
- 결론: 실행 A와 C는 커밋 `6993c17`(= HEAD `db3468c`의 같은 경로)의 실행기·테스트·제품 코드로 돌았다. 구현 때의 재부팅 시험 `20261110T045258Z`(기준선 20:52:59)도 실행기 수정 시각 20:50:00 뒤, `backend/tests/e2e`·`integration` 마지막 수정(11:10:38) 뒤라 같은 실행기·테스트다(그 뒤 `744b17d`·`6993c17`은 문서와 단위 테스트만 더했다: `git diff --stat 9227be6 6993c17`).

### [UNVERIFIED] AC-01 명령 하나로 전체, 종료 코드 0, skip 0 (API 계약 — 실행기)
- 기준: 문서의 명령 하나를 root로 실행하면 데이터 플레인 묶음 전체가 돌고 종료 코드 0. 요약의 수집 수 = `pytest --collect-only -m dataplane`의 수, 실패·오류·skip 0. 제한 시간 3시간.
- 확인한 것:
  - 인자 없는 실행(실행 A)이 대상을 13개 파일·113개로 잡았다: `collect.log` 끝 `113/176 tests collected (63 deselected)`, 콘솔 `collected 113 dataplane tests in 13 files`. 지금 코드의 `python -m pytest --collect-only -q -m dataplane`도 `113/1101 tests collected (988 deselected)`, 실행기 기본 경로로는 `113/176`이다.
  - 실행 A의 끝난 9개 파일(`files.tsv` 모두 pytest 종료 코드 0)과 실행 C의 4개 파일(콘솔 끝 `exit 0`, `rc=0`)의 XML 13개를 `junit_gate.py`로 합치면 `total 113 113 0 0 0`, `collected 113, skipped 0`, 게이트 종료 코드 0.
  - 게이트와 별개로 XML의 `testcase` 요소를 직접 세도 113개 모두 통과(failure·error·skipped 자식 없음), 이름 집합이 실행 A 수집 목록 113개와 정확히 같다(빠진 것·남는 것 없음).
  - 시간: 실행 A 9개 파일 2,632 s + 실행 C 2,767 s = 5,399 s(약 90분, `/proc/uptime` 기준). 3시간 안이다.
- 확인하지 못한 것: **한 번의 실행이 13개 파일을 끝까지 돌고 종료 코드 0으로 끝난 적이 없다.** 실행 A(인자 없음)는 10번째 파일 `test_throughput_limit_data_live.py`의 3번째 테스트(`test_ac04_limit_changes_during_io`) 도중 에이전트 중지로 끊겨 `summary.txt`가 없다. 남은 4개는 실행 C에서 경로 인자로 돌렸다. 그래서 13개 XML을 한 요약으로 합친 종료 코드, 전체 실행 뒤의 남은 것 검사, 1~9번 뒤에 10~13번을 같은 실행에서 이어 도는 경우(파일 사이 간섭, 약 90분 동안의 메모리)는 관찰되지 않았다. 실행 B(남은 4개)가 호스트 메모리 부족으로 끊긴 기록이 있어 마지막 항목은 이 기기에서 실제 위험이다.
- 판정 근거: 끊긴 원인은 실행기나 테스트가 아니라 실행 환경(에이전트 중지, 호스트 메모리)이다. 기준의 핵심 문장("명령 하나 … 종료 코드 0")을 보인 출력이 없으므로 PASS로 세지 않는다. 구성 요소(수집 대상, 113개 전부 통과·skip 0, 시간)는 모두 확인됐다.
- 남은 일: WSL 안에서 분리해(`setsid nohup`) 인자 없는 실행을 한 번 끝까지 돌리고 `summary.txt`의 `exit 0`을 확인하면 PASS로 닫힌다(약 90분).

### [PASS] AC-02 실제 효과를 클라이언트에서 관찰하는 테스트가 통과 목록에 있다 (데이터 효과)
- 기준: 통과 목록에 다음 테스트가 있고, 로그에 클라이언트 쪽 근거가 있다. 통과 목록은 AC-01과 같은 이유로 실행 A·C를 합친 것이다(같은 코드, 위 전제).
- 실행한 명령: 결과 XML에서 통과한 node ID를 뽑고(`/root/fr10-verify-r1/passed_AC.txt`, 113개), `.jsonl`의 `kind: evidence` 기록을 테스트별로 출력했다(scratchpad `tests/evidence_dump.py`).
- 항목별 테스트와 클라이언트 쪽 근거(핵심):

| 항목 | 테스트(실행) | 클라이언트 쪽 근거 (`.jsonl`) |
| --- | --- | --- |
| NFSv3 마운트·읽기·쓰기 | `test_volume_data_live.py::test_ac02_nfsv3_mount_two_clients` (C) | 클라이언트 A 쓰기 rc 0, `/proc/mounts`에 `172.30.0.131:/e2ev1cb1-ac02 … vers=3`. 클라이언트 B 읽기 `from-a-69a2ef…`. 같은 볼륨 `vers=4.1`은 rc 32 `Protocol not supported` |
| NFSv4.1 마운트·읽기·쓰기 | `test_volume_data_live.py::test_ac03_nfsv41_volume` (C) | `v41-data`, `/proc/mounts`에 `vers=4.1`, 0.32 s. `vers=3`·`vers=4.0`은 rc 32 `Protocol not supported` |
| 할당량 초과 쓰기 실패 | `test_ac04_quota_full_write_fails[NFSv3-3]`, `[NFSv4.1-4.1]` (C) | `df` 크기 1,021,313,024 B. `dd` 1,229 MiB가 rc 1 `dd: fsync failed for '/m/big': No space left on device` |
| 삭제 뒤 마운트 거절 | `test_ac09_delete_volume` (C) | DELETE 202 → `Succeeded`. 새 클라이언트 마운트 rc 32 `Host is unreachable`, 인스턴스 inspect rc 1, LV 없음, `ns` 항목 없음. 미리 마운트한 클라이언트는 `Stale file handle` |
| 지운 파일을 `.snapshot/<이름>/`에서 읽기 | `test_snapshot_data_live.py::test_ac02_ac03_snapshot_keeps_point_in_time_content[AC-02-NFSv3-3]`, `[AC-03-NFSv4.1-4.1]` (A) | 활성 트리 `ls -a`에 `A`가 없고(`[., .., .snapshot, big, d]`), 클라이언트가 `.snapshot/S/A`에서 `A-0d4d9a76…`, `d/B`에서 `B-0d4cefc3…`를 읽음. 새로 마운트한 클라이언트 B도 같음(`/m/.snapshot/S` 서브마운트) |
| 스냅샷 쓰기 거절 | `test_ac04_snapshot_and_snapshot_dir_are_immutable[NFSv3-3]`, `[NFSv4.1-4.1]` (A) | 스냅샷 안의 덧붙이기·덮어쓰기·새 파일·rm·mv·mkdir·chmod가 모두 rc 1 `Read-only file system`, `.snapshot` 자체의 생성·mv·chmod는 `Operation not permitted`. 서버 쪽 sha256·모드·inode 전후 같음, `lsattr` `----i---` |
| 되돌리기 뒤 내용 | `test_snapshot_revert_data_live.py::test_ac02_ac03_revert_restores_snapshot_and_deletes_newer[AC-02-NFSv3-3]`, `[AC-03-NFSv4.1-4.1]` (A) | POST 202 → `Reverting` → `Succeeded`(5.2 s, 6.1 s). `client_tree_equal_s2: true`, `client_s2_equal: true`, 목록 `S1,S2,S3` → `S3` 삭제. 다시 `S1`로 되돌림 `tree_equal_s1: true`, `/m/after`는 `No such file` |
| 새 볼륨 내용과 원본 독립 | `test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_content_and_independence[AC-02-NFSv3-3-None]`, `[AC-04a-NFSv4.1-4.1-0755]` (A) | `client_tree_equal_s2: true`, `originatingResourceId` = `…/vn2/snapshots/S2`. 새 볼륨에 쓴 뒤 `v_tree_same`·`v_client_s2_same`·`base_client_same` 모두 true, 원본 클라이언트에서 `n_only`는 `No such file`. 반대 방향도 같음. base 스냅샷 쓰기 거절 |
| 처리량이 한도 이하 | `test_throughput_limit_data_live.py::test_ac01b_auto_volume_data`, `test_ac02_ac03_manual_volume_data_and_shared_read_write` (C) | 아래 "측정값" |
| 한도 변경을 따라감 | `test_ac04_limit_changes_during_io` (C) | 아래 "측정값" |
| 제한 없는 볼륨과의 차이 | `test_ac05_unlimited_volume_next_to_a_limited_one` (C) | 아래 "측정값" |

- 통합 테스트(`test_flexvol_linux.py`, 실행 A, 30개 통과)도 같은 효과를 agent 층에서 클라이언트 컨테이너로 본다(대응표에 적힌 7개 매개변수 모두 통과 목록에 있다).

### [PASS] AC-03 대응표 (API 계약 — 문서와 수집)
- 기준: 대응표가 PRD §6.1 FR-01~FR-08의 수락 기준 문장을 빠짐없이 담고, node ID가 모두 수집되며, 데이터 플레인 node ID는 AC-01 실행에서 통과했다.
- 실행한 명령: scratchpad `tests/ac03_check.py`로 `docs/PRD.md` §6.1의 FR-01~FR-08 수락 기준 칸을 문장으로 나눠(`[S2]`와 `(`_workspace/…`)` 참조는 뗌) `docs/testing.md` §4의 같은 FR 행에 그대로 있는지 보고, 표의 node ID를 뽑았다. 그 41개를 WSL 일반 사용자로 `python -m pytest -p no:cacheprovider --collect-only -q <41개>`.
- 출력(핵심): 문장 25개 모두 `OK`(`missing in testing.md 0`), 표 행 23개(FR-02·FR-03의 "실환경 검증은 … 사이클에서 한다"와 "검사 로직은 … 계약 테스트로 확인한다"를 각각 한 행에 둠). `41 tests collected`, 수집 rc 0, `not collected 0`. 데이터 플레인 파일의 node ID 29개가 모두 실행 A·C의 통과 목록에 있다(`not in passed set of runs A+C: []`). 나머지 12개(계정·풀 e2e, 계약)는 AC-08의 `-m "not dataplane"` 실행이 돌린다.
- 단서: "AC-01 실행에서 통과"는 AC-01과 같이 실행 A·C를 합친 통과 목록으로 확인했다.

### [PASS] AC-04 skip·실패는 실패, 준비가 빠지면 2 (API 계약 — 실행기 종료 코드)
- 기준: (a) root가 아니거나 준비가 빠지면 테스트를 돌리지 않고 종료 코드 2와 원인 한 줄. (b) skip이 있는 실행은 종료 코드 1, 요약에 skip 수. (c) 실패하는 임시 파일을 넣으면 종료 코드 1, 나머지 파일은 끝까지 돈다.
- (a) 실행한 명령과 출력:
  - 일반 사용자 `mkimhome1`: `wsl -d Ubuntu -e bash -c 'bash /mnt/c/…/scripts/run-dataplane-tests.sh; echo "exit=$?"'` → `precheck failed: not root: run it with wsl -d Ubuntu -u root`, `exit=2`.
  - root, 다른 프로세스가 8090을 잡음(`setsid nohup python3 -m http.server 8090 --bind 127.0.0.1`, `ss`에 `127.0.0.1:8090 users:(("python3",pid=833,fd=3))`) → `precheck failed: port 8080 or 8090 is in use, maybe by another session's data plane: 127.0.0.1:8090 users:(("python3",pid=833,fd=3))`, `exit=2`.
  - 두 경우 모두 `/var/tmp/anf-clone-tests/`에 새 출력 폴더가 생기지 않았다(실행 전 목록과 `diff` 같음). 수집과 pytest를 시작하지 않았다는 뜻이다(사전 점검이 출력 폴더 만들기 앞에 있다, `scripts/run-dataplane-tests.sh:29-50`, `:65-66`). 8090 서버는 끝낸 뒤 리스너가 없음을 확인했다.
- (b) 실행한 명령: root, `ANF_E2E_API_URL= ANF_TEST_OUT=/root/fr10-verify-r1/ac04b scripts/run-dataplane-tests.sh backend/tests/e2e/test_snapshot_contract_live.py`.
  - 출력: 5개 모두 `SKIPPED … ANF_E2E_API_URL is not set`, pytest 자체는 `[1/1] …: pytest exit 0`. 요약 `test_snapshot_contract_live 5 0 0 0 5`, `collected 5, skipped 5`, `Skipped tests are not passes. Run them here or deselect them by marker on purpose.`, `exit 1`. pytest가 0으로 끝나도 실행기는 1로 끝난다.
- (c) 실행한 명령: 임시 파일 `backend/tests/e2e/test_zz_fr10tmp_fail.py`(`dataplane` 마커, `assert 1 == 2`)를 만들고 root로 `ANF_TEST_OUT=/root/fr10-verify-r1/ac04c scripts/run-dataplane-tests.sh backend/tests/e2e/test_zz_fr10tmp_fail.py backend/tests/e2e/test_snapshot_contract_live.py`.
  - 출력: `[1/2] …test_zz_fr10tmp_fail.py: pytest exit 1, 1 s`, 이어서 `[2/2] backend/tests/e2e/test_snapshot_contract_live.py`가 실제 agent·anf-api로 `5 passed in 104.59s`, `pytest exit 0, 105 s`. 요약 `total 6 5 1 0 0`, `1 failed, 0 errors.`, `nonzero exit: backend/tests/e2e/test_zz_fr10tmp_fail.py (pytest exit 1)`, `exit 1`. 실행 뒤 LV `aggr0`뿐, 컨테이너 0, 리스너 0.
- 임시 파일은 검증 뒤 지웠다(Windows TDD 훅이 만든 `__pycache__`의 `.pyc` 둘 포함). `git status`에 남지 않았다.

### [PASS] AC-05 남기지 않음 (데이터 플레인 정리)
- 기준: AC-01 실행 뒤 실행 전에 없던 LV, `anf-nfs-*`·`anfe2e-cli-*` 컨테이너, 8080·8090 리스너가 없다. 일부러 컨테이너 하나를 남기는 임시 테스트로 실행하면 실행기가 그것을 출력하고 종료 코드 1이다.
- 전체 실행 뒤(실행 C로 봄, 사용자 결정 5): `summary.txt`에 `left behind` 줄이 없고 `exit 0`이다. 기준선(`baseline.txt`)은 LV `vol_091f84da…`·`vol_4ef00169…`(실행 B가 남긴 볼륨), 컨테이너 없음이었다. 이 두 볼륨의 인스턴스 `anf-nfs-091f84da…`·`anf-nfs-4ef00169…`는 실행 중 agent의 시작 복구가 다시 띄워(`test_volume_data_live.jsonl`의 `baseline` 근거에 `running`) 실행 뒤에도 있었다. 실행기는 설계 §8의 3대로 "실행 전에 있던 볼륨의 인스턴스"를 세지 않는다(`scripts/run-dataplane-tests.sh:133`). 기준 문장을 글자 그대로 읽으면 실행 전에 없던 컨테이너지만, 테스트가 만든 것이 아니라 기준선 볼륨의 복구라 정리 결함이 아니다. 리더가 실행 뒤 두 볼륨과 인스턴스를 지웠다(진행 기록).
- 실행 A는 끊겨 남은 것 검사까지 가지 않았다. 끊긴 10번째 파일이 남긴 컨테이너 3개·LV 2개는 리더가 지웠다(진행 기록 40행). 끊긴 테스트의 잔여물이라 정리 결함의 근거로 쓰지 않는다.
- 일부러 남기기: 임시 파일 `backend/tests/e2e/test_zz_fr10tmp_leak.py`(`dataplane` 마커, `docker run -d --name anfe2e-cli-fr10leak --entrypoint sleep anf-nfs-client 3600` 후 통과). root로 `ANF_TEST_OUT=/root/fr10-verify-r1/ac05 scripts/run-dataplane-tests.sh backend/tests/e2e/test_zz_fr10tmp_leak.py`.
  - 출력: `1 passed`, 요약 `total 1 1 0 0 0`, `collected 1, skipped 0`, `left behind (not removed): container anfe2e-cli-fr10leak`, `exit 1`. 실행 뒤 `docker ps -a`에 `anfe2e-cli-fr10leak Up`이 그대로 있다(지우지 않음, 결정 10).
  - 검증 뒤 `docker rm -f anfe2e-cli-fr10leak`, 컨테이너 0으로 되돌렸다.

### [PASS] AC-06 재부팅 뒤 첫 실행 (상태 전이 — 실행기 준비)
- 기준: WSL을 다시 띄운 뒤(VG가 붙지 않은 상태) 첫 실행에서 사람 손 없이 실행기가 묶음을 돌린다(일부 파일로 확인해도 된다).
- 이번에 `wsl --terminate`를 다시 하지 않았다(사용자 결정 2). 근거는 남은 로그 두 개다.
- 실행한 명령: `journalctl --list-boots`, `cat /var/tmp/anf-clone-tests/console-rest2.log`, `console-ac06.log`, 두 실행의 `baseline.txt`·`summary.txt`.
- 출력(핵심):
  - 부팅 기록: 부팅 -1 시작 `20:52:43 PST`, 부팅 0 시작 `22:56:40 PST`.
  - 실행 C(`20261110T065647Z`): 기준선 22:56:47(부팅 0의 7초 뒤). 콘솔 첫 줄 `VG anf: not attached (WSL restarted?); attaching it the way the storage agent does at start`, 이어서 `collected 28 dataplane tests in 4 files`, 4개 파일 모두 `pytest exit 0`, 끝 `exit 0`. 대상은 e2e 4개(처리량 데이터, 볼륨 계약·데이터·복구)이고 통합 파일은 없다.
  - 구현 때의 시험(`20261110T045258Z`): 기준선 20:52:59(부팅 -1의 16초 뒤). 콘솔 첫 줄이 같은 `VG anf: not attached …`, `collected 37 dataplane tests in 2 files`(통합 `test_flexvol_linux.py` 30 + e2e 데이터 `test_volume_data_live.py` 7), `total 37 37 0 0 0`, `exit 0`. 기준이 예로 든 "통합 1개 + e2e 데이터 1개"와 같다.
- 판정: 두 실행 모두 부팅 직후 VG가 없는 상태에서 실행기가 스스로 VG를 붙이고(`vgs anf` 재확인 통과, 사전 점검 실패 없음) 묶음을 끝까지 돌렸다. 사이에 사람이 한 일의 흔적이 없다(부팅에서 기준선까지 7초·16초).
- 보조 근거(이번 회차, HEAD 코드): 이번 검증 중에도 WSL VM이 제 명령 사이에 쉬면서 여러 번 내려갔다 다시 떴다(부팅 23:48:44, 23:52:52, 23:54:28 PST, 부팅 직후 `/proc/uptime` 39 s). 그래서 AC-04 (b)와 (c)의 실행이 모두 첫 줄 `VG anf: not attached (WSL restarted?); attaching …`로 시작했고, (c)는 빈 VG에서 실제 e2e 파일(`test_snapshot_contract_live.py`, agent·anf-api·LV·스냅샷)을 `5 passed`로 끝냈다.
- 단서: 실행 C 때 VG 안에는 실행 B가 남긴 볼륨 2개(`vol_091f84da…`, `vol_4ef00169…`, 경로 `e2evbf9e-d9`·`-d9s`)가 있어 기준선에 잡혔다. 테스트의 `baseline` 근거 기록에 그 인스턴스 둘이 `running`으로 보인다(agent 시작 복구가 다시 띄움). 빈 VG에서의 재부팅 뒤 첫 실행은 `20261110T045258Z`가 보인다. 두 볼륨은 실행 C 뒤 리더가 지웠다.

### [UNVERIFIED] AC-07 CI와 같은 판정 (API 계약 — CI)
- 기준: `ci.yml`의 skip 검사가 `junit_gate.py`를 부르고, PR의 Actions 실행에서 backend·frontend 작업이 통과하며, 그 단계 로그에 수집·skip 수가 보인다.
- 확인한 것: `.github/workflows/ci.yml:43-51`에서 `Test` 단계가 `python -m pytest -m "not dataplane" --junitxml=pytest-results.xml`, `Fail on skipped tests` 단계가 `python backend/tests/junit_gate.py pytest-results.xml`이다. `git diff main -- .github/workflows/ci.yml`은 인라인 Python 검사(`collected {tests}, skipped {skipped}`, 같은 오류 문구)를 이 한 줄로 바꾼 것뿐이다. 같은 두 명령을 WSL에서 그대로 돌린 결과가 AC-08이다(게이트 출력 `collected 988, skipped 0`, 종료 코드 0). 데이터 플레인 실행기도 같은 파일을 부른다(`scripts/run-dataplane-tests.sh:142`).
- 확인하지 못한 것: PR이 아직 없어 GitHub Actions 실행(backend·frontend 통과, 단계 로그의 수)을 보지 않았다(리더 지시). PR 뒤 리더가 확인한다.

### [PASS] AC-08 제품 코드 불변, 비데이터 플레인 묶음 skip 0, ruff (API 계약 — 회귀)
- 해시: 검증 시작과 끝에 Git Bash에서 `git ls-files -co --exclude-standard -- pyproject.toml backend ':!backend/tests' | LC_ALL=C sort | while IFS= read -r f; do cat "$f"; done | tr -d '\r' | sha256sum` → 두 번 모두 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`. 기대값과 같다.
- 실행한 명령(WSL 일반 사용자, 저장소 루트): `PYTHONDONTWRITEBYTECODE=1 ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest -p no:cacheprovider -m "not dataplane" --junitxml=/var/tmp/fr10-verify-r1/not_dataplane.xml`, 이어서 `python backend/tests/junit_gate.py <그 XML>`. (`-p no:cacheprovider`와 `PYTHONDONTWRITEBYTECODE`는 Windows 체크아웃에 캐시를 남기지 않으려고 더했다. 선택과 판정은 바꾸지 않는다.)
- 출력: `988 passed, 113 deselected in 190.09s`, pytest rc 0. 게이트 `not_dataplane 988 988 0 0 0`, `collected 988, skipped 0`, rc 0. 컨트롤 플레인 e2e 4개 파일(`test_netapp_account_live.py`, `test_netapp_account_lro_faults_live.py`, `test_capacity_pool_live.py`, `test_capacity_pool_lro_faults_live.py`)의 테스트가 skip 없이 통과했다. 대응표의 비데이터 플레인 node ID 12개가 모두 이 실행의 통과 목록에 있다. 새 단위 테스트 `test_junit_gate.py`·`test_testing_doc.py`도 이 실행에 들어 있다.
- ruff(Windows): `uvx ruff@0.14.0 check backend .claude/hooks` → `All checks passed!`, rc 0.

## 측정값

실행 C(`20261110T065647Z/test_throughput_limit_data_live.jsonl`)의 클라이언트 컨테이너 `fio --direct=1` 값(MiB/s). 테스트는 회마다 한도×15 s 크기를 6회 재고 첫 회를 버린 5회의 중앙값을 한도의 90~101%로 판정한다(`backend/tests/e2e/throughput_live.py:240-251`, `LOW, HIGH = 0.90, 1.01`). 한도 변경(AC-04)은 2 s 창마다 판정한다.

| 시험 | 볼륨·한도 | 6회 값(첫 회는 버림) | 중앙값 / 비율 |
| --- | --- | --- | --- |
| AC-01b Auto 쓰기 | `a3`(NFSv3), Ultra 40 GiB = 5 | 4.965, 4.966, 4.97, 4.964, 4.969, 4.967 | 4.967 / 0.9934 |
| AC-01b Auto 읽기 | `a3` 5 | 4.94, 4.97, 4.971, 4.973, 4.97, 4.972 | 4.971 / 0.9942 |
| AC-01b Auto 쓰기·읽기 | `a41`(NFSv4.1) 5 | 쓰기 4.969~4.973, 읽기 4.971~4.973 | 4.971 / 0.9942, 4.973 / 0.9946 |
| AC-02 Manual 쓰기 | `m41` 10 | 9.945, 9.948, 9.942, 9.953, 9.95, 9.951 | 9.95 / 0.995 |
| AC-02 Manual 읽기 | `m41` 10 | 9.948, 9.954, 9.956, 9.925, 9.939, 9.942 | 9.942 / 0.9942 |
| AC-03 읽기+쓰기 합 | `m41` 10 | 9.968, 9.97, 9.966, 9.973, 9.972, 9.965 | 9.97 / 0.997 |
| AC-02 Manual 쓰기 | `m3` 20 | **11.659**, 19.886, 19.864, 19.867, 19.864, 19.889 | 19.867 / 0.9934 |
| AC-02 Manual 읽기 | `m3` 20 | 19.846, 19.826, 19.853, 19.784, 19.801, 19.786 | 19.801 / 0.99 |
| AC-03 읽기+쓰기 합 | `m3` 20 | 19.906, 19.867, 19.891, 19.876, 19.865, 19.864 | 19.867 / 0.9934 |

| AC-04 한도 변경(I/O 중) | 바꾼 방법·한도 | 2 s 창 값 |
| --- | --- | --- |
| `w41` 쓰기 | PATCH 202 → 30 | 29.839, 29.814, 29.836, 29.915 |
| `w41` 쓰기 | PATCH 202 → 5 | 5.021, 5.041, 5.031, 5.012 |
| `w41` 쓰기 | PUT 200 → 10 | 10.023, 10.025, 10.036, 9.991 |
| `r3` 읽기 | PATCH 202 → 30 | 29.65, 29.693, 29.74, 29.942 |
| `r3` 읽기 | PATCH 202 → 5 | 5.022, 5.017, 5.038, 5.036 |
| `r3` 읽기 | PUT 200 → 10 | 10.019, 10.005, 9.973, 9.995 |

AC-05(제한 없는 볼륨 옆): A(10 MiB/s) 혼자 읽기 중앙값 9.955, 함께 읽을 때 A 9.9226~9.9621(중앙값 9.9575), B(4,500 MiB/s) 1,863.9~2,051.1(중앙값 2,033.4). B가 A의 약 204배. tc `rate_bits` A 87,710,000, B 39,469,000,000.

## 판정 밖 관찰

1. **`docs/testing.md` §3 "소요 시간"이 비어 있다.** 본문이 `(전체 실행의 실측을 여기에 적는다.)` 그대로다. 설계 §6은 "전체 소요 시간(이번 실행의 실측)"을 적으라고 한다. 지금 있는 실측은 두 실행의 합 5,399 s(실행 A 9개 파일 2,632 s + 실행 C 4개 파일 2,767 s, 단조 시계)이고, 파일별로는 처리량 데이터 2,256 s가 가장 길다. 한 번에 끝까지 돈 값은 아직 없다(AC-01).
2. **`docs/testing.md` FR-08 첫 행의 "회마다 한도의 90~101%다"는 테스트가 단언하는 것과 다르다.** 테스트는 6회를 재고 첫 회를 버린 5회의 중앙값을 판정한다(`backend/tests/e2e/throughput_live.py:240-251`, `test_throughput_limit_data_live.py:73`, `:102`). 실행 C에서 `m3` 20 MiB/s 쓰기의 첫 회는 11.659(58%)였고 버려졌다. 셈에 든 5회는 이번에 모두 범위 안이었지만 그것을 단언하지는 않는다. "첫 회를 버린 5회의 중앙값이 한도의 90~101%" 같은 문구가 맞다. 테스트는 바꿀 필요가 없다.
3. **이 기기의 WSL VM은 쉬면 몇십 초 만에 내려간다.** 이번 검증 중에도 제 명령 사이에 세 번 다시 떴다(23:48:44, 23:52:52, 23:54:28 PST). 다시 뜰 때마다 VG가 떨어지고 `/tmp`가 비워진다. 실행기의 VG 붙이기(결정 8)와 `/var/tmp` 출력(결정 9)이 바로 이 경우를 덮는다는 것을 이번에 거듭 보았다. AC-01을 닫는 한 번의 전체 실행(약 90분)은 VM이 그동안 떠 있어야 하고, 실행 B는 호스트 메모리 부족으로 끊겼다. 실행 C처럼 WSL 안에서 분리해 띄우고 짧게 나눠 기다리는 방법이 이 기기에서 통한 유일한 방법이다.
4. **실행 C는 깨끗한 VG에서 돌지 않았다.** 실행 B가 남긴 볼륨 2개와 그 knfsd 인스턴스 2개가 처리량 시험 내내 떠 있었다. 처리량 값은 모두 범위 안이었으므로 판정에는 영향이 없었지만, 빈 데이터 플레인에서의 처리량 데이터 파일 실행은 실행 B(끊김)뿐이다.
5. **실행기의 남은 것 검사 예외(설계 §8의 3)는 AC-05 문구보다 넓다.** "실행 전에 있던 볼륨의 인스턴스는 세지 않는다"는 규칙 때문에, 실행 전에 없던 `anf-nfs-<uuid>` 컨테이너가 실행 뒤에 있어도 그 볼륨이 기준선에 있으면 출력하지 않는다. 실행 C가 그 경우였다. 복구가 띄운 것이라 맞는 판단이지만, 테스트가 기준선 볼륨의 인스턴스를 멈춘 채 두거나 지우지 않고 남긴 경우를 구별하지는 못한다(이번에는 해당 없음).
6. 사전 점검 실패(AC-04 a)는 출력 폴더를 만들기 전에 끝나므로 `summary.txt`가 남지 않는다. 원인은 표준 오류의 한 줄뿐이다. CI나 다른 호출자가 원인을 남기려면 표준 오류를 따로 받아야 한다. 설계와 어긋나지는 않는다.
