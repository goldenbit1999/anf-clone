# 테스트 자동화 (FR-10, 데이터 플레인 실행기와 skip 판정)

> 테스트는 기능마다 이미 있었고 각 사이클의 검증에서 통과했다. FR-10이 더한 것은 "자동화"다. (1) root 명령 하나 `scripts/run-dataplane-tests.sh`가 `dataplane` 마커 테스트 113개(13개 파일)를 파일마다 따로 돌리고, 통과·실패·skip·남은 것을 종료 코드 하나로 알린다. (2) "skip은 PASS가 아니다"라는 판정을 `backend/tests/junit_gate.py` 하나로 모아 CI와 실행기가 같은 코드로 지킨다. (3) `docs/testing.md`가 PRD 수락 기준 문장마다 그것을 확인하는 pytest node ID를 적고, 단위 테스트가 그 node ID가 실제로 수집되는지 지킨다. 검증은 2회차에서 PASS 8 / FAIL 0 / UNVERIFIED 0으로 닫혔다. 1회차(PASS 6 / UNVERIFIED 2)에 남은 AC-01은 인자 없는 전체 실행 한 번(13개 파일·113개 통과, skip 0, 5,279 s)으로, AC-07은 PR #19의 Actions run으로 PASS가 됐다.

코드 인용 기준: 커밋 `961e316` (제품 코드 내용 해시 `f99bc5cfbcf1429d3040a72b4c30205fe983c8e806f375b57c30c15c9dc1a6d3`). FR-10은 제품 코드를 바꾸지 않았다. 검증 1회차의 대상 코드는 `6993c17`(HEAD `db3468c`, 같은 경로)이고, 그 뒤 `961e316`은 커밋 메시지대로 검증 1회차 기록과 `docs/testing.md`의 문구 하나만 바꿨다. 2회차의 대상 HEAD `ace0d39`도 `scripts`·`backend`·`pyproject.toml`·`.github`가 `6993c17`과 같다(2회차 보고서).

FR-10은 ANF 기능이 아니라 엔지니어링 장치다. PRD §8에서 FR-10은 조사(1단계)를 생략하는 FR이라 조사 브리프가 없고, 아래 1, 2절은 "해당 없음"이다. 사실의 근거는 설계(`_workspace/test-automation/02_main_design.md`, 결정 1~13과 §8 구현 중 변경), 진행 기록(`_workspace/test-automation/00_progress.md`), 검증 보고서(`_workspace/test-automation/04_verifier_report.md` 1회차, `04_verifier_report_r2.md` 2회차), `docs/testing.md`, ADR §9, 그리고 실제 코드다. 같은 종류의 앞 문서는 `docs/concepts/ci.md`다.

---

## 1. ANF에서는

해당 없음. 테스트 자동화는 ANF의 기능이 아니다. 다만 지원하는 직무(ANF 데이터 플레인)가 Python 테스트 자동화를 강조하므로, 이 결과물은 "실제 커널 위에서 마운트, 스냅샷, 처리량 효과를 클라이언트에서 확인하는 테스트를 명령 하나로 돌리고, 결과를 숨김 없이 판정한다"는 것을 보여 준다. PRD의 FR-10 수락 기준도 바로 그 문장이다("실제 커널 위에서 마운트, 스냅샷, 처리량 효과를 확인하는 테스트가 있고 통과한다").

## 2. ONTAP에서는

해당 없음.

## 3. 이 프로젝트에서는

### 3.1 왜 필요했나: 비어 있던 것과 앞서 겪은 일

FR-10을 시작할 때 테스트 층은 이미 있었다(단위 13개 파일, 계약 6개, 통합 1개, e2e 16개). 비어 있던 것은 네 가지다 (설계 §2).

1. **데이터 플레인 묶음 전체를 한 번에 돌리는 명령이 없었다.** implementer와 verifier가 파일을 골라 손으로 돌렸고, 그때마다 환경 변수, `drop_caches`, VG 붙이기를 직접 챙겼다. 그 지식이 기록에만 있었다.
2. **skip을 실패로 보는 검사가 CI 워크플로 안의 인라인 Python에만 있었다.** 데이터 플레인 실행에는 없었다.
3. **PRD 수락 기준과 테스트의 대응이 한곳에 없었다.** "FR-05는 어떤 테스트가 증명하나"를 찾으려면 사이클별 보고서를 봐야 했다.
4. **일부 수락 기준은 verifier의 일회성 드라이버로만 확인했을 수 있었다** (예: `_workspace/throughput-limit/verify/fr08_verify.py`).

실행기의 모양은 FR-08(처리량 제한) 사이클에서 겪은 일 세 가지가 정했다 (`_workspace/throughput-limit/00_progress.md` 이력, `_workspace/throughput-limit/04_verifier_report.md`).

| FR-08 때 일어난 일 | 내용 | 이번 설계 |
| --- | --- | --- |
| 한 프로세스로 회귀를 돌리다 죽음 | 14개 파일을 pytest 한 번으로 이어 돌리다 5개 파일 뒤에 호스트 메모리 부족으로 실행기가 강제 종료됐다(WSL page cache 6.8 GB). 파일 사이에 `drop_caches`를 넣어 남은 11개 파일을 다시 돌리자 모두 통과했다 | 결정 3: 파일마다 pytest 프로세스 하나, 사이에 `sync` + `drop_caches` |
| WSL 재부팅 뒤 VG가 없음 | 첫 실행이 모든 파일에서 setup 오류였다. WSL이 다시 뜨면 loop 장치가 사라져 VG `anf`가 보이지 않는다. agent를 한 번 띄워 풀었다. e2e `agent` 픽스처는 시작하자마자 `lvs … anf`로 기준선을 남기는데(`backend/tests/e2e/dataplane_live.py:277` `agent`, `:310-312` `lvs_volumes`), 이 명령이 실패하면 단언이 깨진다 | 결정 8: 실행기가 VG를 스스로 붙인다 |
| 로그를 `/mnt/c`에 바로 씀 | e2e 도우미는 HTTP 요청마다 로그 파일에 한 줄을 붙인다. 그 파일이 9P(`/mnt/c`)에 있으면 요청이 많은 시험이 3~4배 느려졌다(풀 계약 2.48 s → 10.48 s) | 결정 9: 출력은 WSL 디스크 `/var/tmp` |

### 3.2 구조

pytest 테스트 1,101개는 세 경로로 나뉘어 돈다. 두 경로가 같은 판정 스크립트를 쓴다.

```
                           ┌─ Windows TDD 훅 ─ 짝 테스트(Write·Edit 뒤), 전체(종료 때)
                           │     e2e·통합은 skip된다. 모두 skip된 실행은 GREEN이 아니라 SKIPPED로 알린다
pytest 1,101개 ────────────┼─ WSL 일반 사용자 / CI backend 작업 ─ -m "not dataplane" (988개)
(pyproject.toml의 마커)    │     └─> junit_gate.py (CI의 "Fail on skipped tests" 단계)
                           └─ WSL root ─ scripts/run-dataplane-tests.sh ─ dataplane (113개, 13개 파일)
                                 └─> junit_gate.py + pytest 종료 코드 + 남은 것 검사
```

실행기 한 번의 흐름은 이렇다.

```
run-dataplane-tests.sh [경로·pytest 옵션...]
 1 사전 점검 ───── 하나라도 빠지면 stderr에 원인 한 줄, 종료 코드 2 (출력 폴더도 만들지 않는다)
 2 VG anf 확인 ─── 없으면 agent의 FlexVolManager.ensure_aggregate()를 그대로 불러 붙인다
 3 출력 폴더, 기준선(LV·컨테이너) → baseline.txt
   수집: pytest --collect-only -q -m dataplane → node ID → 파일 목록 (스크립트에 목록을 적지 않는다)
 4 파일마다: sync; drop_caches → pytest -v -m dataplane --junitxml=<파일>.xml (ANF_E2E_LOG=<파일>.jsonl) | tee <파일>.log
 5 남은 것: 기준선과 비교 (LV, 컨테이너, 8080·8090 리스너). 출력만 하고 지우지 않는다
 6 판정: junit_gate.py 합산 + 0이 아닌 pytest 종료 코드 + 남은 것 → summary.txt, 종료 코드 0 또는 1
```

### 3.3 코드 따라가기

#### 실행기 `scripts/run-dataplane-tests.sh`

**셸 설정 (`scripts/run-dataplane-tests.sh:15-26`)**
- `set -uo pipefail` (`:15`)에 `-e`가 없는 것은 일부러다. `-e`를 켜면 첫 파일의 pytest가 1로 끝나는 순간 스크립트 전체가 멈춘다. 결정 4는 "실패해도 끝까지 돌고 마지막에 1"이다. `-u`는 변수 이름 오타를, `pipefail`은 파이프 안의 실패를 잡는다.
- `PYTHONDONTWRITEBYTECODE=1` (`:19`)과 뒤의 `-p no:cacheprovider` (`:85`)는 root가 Windows 체크아웃(`/mnt/c`)에 `__pycache__`·`.pytest_cache`를 남기지 않게 한다 (설계 §8-7).
- 작은 함수 다섯 개: `precheck_failed` (`:22`, stderr에 한 줄 쓰고 `exit 2`), `uptime_s` (`:23`, `/proc/uptime`의 단조 시계), `listeners` (`:24`, `ss`로 8080·8090 리스너), `lv_names` (`:25`, VG `anf`의 LV 중 `aggr0` 아닌 것), `containers` (`:26`, `docker ps -a` 이름 전체).
- 시간을 `/proc/uptime`으로 재는 이유: WSL 벽시계는 건너뛴다(`docs/testing.md` §5). bash의 `SECONDS`·`EPOCHREALTIME`은 벽시계라 쓰지 않았다 (설계 §8-4).

**1. 사전 점검 (`:28-50`, 결정 7)**
- Linux (`:29`), root (`:30`), venv (`:32-36`), 그 venv의 pytest (`:37`), Docker Engine (`:38`), 이미지 `anf-nfs-server`·`anf-nfs-client` (`:39-41`), 네트워크 `anf-vnet`의 서브넷과 IP 범위가 정확히 `172.30.0.0/24 172.30.0.0/25` (`:42-45`), `nfsd` 모듈 (`:46`), `fs.leases-enable = 0` (`:47-48`), 8080·8090이 비어 있음 (`:49-50`) 순서로 본다.
- 실행기는 준비를 "하지" 않고 "확인"만 한다. 준비는 `scripts/setup-wsl-dataplane.sh`의 일이라, 메시지마다 그 스크립트를 가리킨다(`SETUP_HINT`, `:20`).
- **venv 찾기 (`:32-34`).** root로 돌면 `~`가 `/root`라서 `~/.venvs/anf-clone`을 그대로 쓸 수 없다. `ANF_CLONE_VENV`가 없으면 저장소 폴더의 주인 uid(`stat -c %u`)를 `getent passwd`로 집 폴더로 바꿔 그 사람의 `~/.venvs/anf-clone`을 쓴다. e2e 도우미가 anf-api를 띄울 일반 사용자로 venv의 주인을 고르는 것(`backend/tests/e2e/dataplane_live.py:96-102` `e2e_user`)과 같은 사람을 가리킨다 (설계 §8-2).
- **포트 점검의 뜻.** 데이터 플레인은 기기에 하나다(VG, IP 대역, 포트 8080·8090). 포트가 차 있으면 다른 세션이 데이터 플레인을 쓰고 있을 수 있으므로, 테스트를 시작하지 않고 끝낸다. 실패 메시지에 리스너를 잡은 프로세스까지 찍힌다(보고서 AC-04 (a)).
- 왜 pytest의 skip·setup 오류에 맡기지 않는가: 조건 하나가 빠지면 70개가 넘는 테스트가 같은 이유로 skip되거나 setup 오류가 난다. 원인을 한 줄로 먼저 말하는 편이 낫다 (결정 7).

**2. VG 붙이기 (`:52-63`, 결정 8, 설계 §8-1)**
- `vgs anf`가 실패하면 venv Python으로 `FlexVolManager(Runner()).ensure_aggregate()`를 부른다 (`:58-61`). 이 함수(`backend/storage_agent/flexvol.py:148-162` `ensure_aggregate`)는 aggregate 이미지에 붙은 loop 장치를 `losetup -j`로 찾고, 없으면 `losetup --find --show`로 새로 붙이고(주석 "첫 실행이거나 WSL이 재시작돼 루프 장치가 사라졌다", `flexvol.py:156`), VG와 thin pool이 없으면 만들고, `vgchange -ay`로 활성화한다. agent가 시작할 때 `recover`의 첫 줄에서 부르는 바로 그 함수다(`flexvol.py:170` `recover`).
- 버린 방법 둘: agent를 잠깐 띄우는 것은 `recover`가 남아 있는 볼륨의 인스턴스까지 띄워(`flexvol.py:177-189`) 3단계의 기준선이 흔들린다. `losetup`·`vgchange`를 스크립트에 다시 쓰는 것은 같은 절차가 두 곳에 생긴다. 함수를 부르기만 하므로 제품 코드는 그대로다.
- 붙인 뒤 `vgs anf`를 한 번 더 확인하고, 그래도 없으면 사전 점검 실패(종료 코드 2)로 끝낸다 (`:62`).

**3. 출력 폴더와 기준선 (`:65-72`, 결정 9·10)**
- 출력 폴더는 `ANF_TEST_OUT`, 없으면 `/var/tmp/anf-clone-tests/<UTC 시각>` (`:65`). `/mnt/c`(9P)는 위 3.1의 이유로, `/tmp`는 WSL이 꺼지면 사라져서 피했다. 폴더 이름의 시각은 이름일 뿐이고 시간 측정에는 쓰지 않는다.
- 출력 폴더를 사전 점검 **뒤에** 만든다. 그래서 사전 점검이 실패하면 출력 폴더도 `summary.txt`도 생기지 않는다(보고서 AC-04 (a), 판정 밖 관찰 6).
- 실행 전의 LV 이름과 컨테이너 이름을 변수와 `baseline.txt`에 남긴다 (`:69-72`).

**대상 고르기와 수집 (`:74-97`)**
- 인자를 경로와 pytest 옵션으로 나눈다 (`:75-83`). `-`로 시작하지 않고 `::` 앞부분(`${a%%::*}`)이 실제로 있는 인자는 경로(파일, 폴더, node ID)다. 경로는 저장소 기준 상대 경로로 바꾸고 `::` 뒤를 다시 붙여 수집 결과의 node ID와 같은 꼴로 맞춘다 (`:79`). 그래서 값이 경로인 옵션은 `--deselect=<node ID>`처럼 `=`로 붙여 써야 한다 (설계 §8-8, `docs/testing.md` §3).
- 경로가 없으면 `backend/tests/integration`과 `backend/tests/e2e` 전체 (`:84`).
- 대상 파일 목록은 스크립트에 적지 않고 `pytest --collect-only -q -m dataplane`의 출력에서 얻는다 (`:87-90`). node ID 줄을 고르고(`:89`), `::` 앞을 잘라 처음 나온 순서대로 중복을 뺀다(`:90`). 새 테스트 파일을 만들면 저절로 들어간다. `-k` 같은 옵션도 수집에 그대로 넘기므로 대상 파일이 같이 줄어든다.
- 수집이 실패하거나 0개면 `collect.log`의 끝을 보여 주고 종료 코드 1 (`:91-95`).
- `API_URL="${ANF_E2E_API_URL-http://127.0.0.1:8080}"` (`:96`)에서 `:-`가 아니라 `-`를 쓴 것은 일부러다. 변수가 **없을 때만** 기본값을 채우고, **빈 값**은 그대로 둔다. 빈 값을 주면 e2e가 skip하고 6단계 판정이 그것을 실패로 센다. AC-04 (b)를 이 방법으로 재현했다 (설계 §8-6).

**4. 파일마다 pytest (`:99-123`, 결정 3·4)**
- 파일마다(`:104`) 먼저 `sync`와 `echo 3 > /proc/sys/vm/drop_caches`로 page cache를 비운다 (`:110-111`).
- 그 파일에 대해 인자로 준 node ID가 있으면 그것만, 없으면 파일 전체를 돈다 (`:107-109`).
- `ANF_E2E_API_URL`과 `ANF_E2E_LOG=<출력>/<파일>.jsonl`을 주고 `pytest -v -m dataplane --junitxml=<출력>/<파일>.xml`을 돌린 뒤 `tee`로 `<파일>.log`에도 남긴다 (`:114-115`). `.jsonl`은 e2e 도우미가 남기는 HTTP 요청·응답, 서버 이벤트, 판정 근거(`evidence`)다. 검증에서 "클라이언트 쪽 근거"는 이 파일에서 읽었다(AC-02).
- `rc=${PIPESTATUS[0]}` (`:116`)는 `tee`가 아니라 pytest의 종료 코드를 얻는다. 0이 아니면 `bad_exit`에 넣는다 (`:121`). XML이 깨끗해도 pytest가 0이 아니면 실패로 센다. XML만으로는 pytest 내부 오류(종료 코드 3)를 놓칠 수 있기 때문이다 (설계 §8-5).
- 파일별 초는 `/proc/uptime` 두 값의 차이다 (`:113`, `:117`). 파일 이름, pytest 종료 코드, 초를 `files.tsv`에 한 줄씩 붙인다 (`:119`). 실행이 중간에 끊겨도 끝난 파일까지의 기록이 이 파일에 남는다. 검증 1회차는 끊긴 실행 A의 앞 9개 파일을 이 기록과 XML로 판정했다.
- 왜 프로세스를 나누는가: FR-08에서 한 프로세스로 14개 파일을 돌리다 호스트가 실행기를 죽였다(3.1). 파일별로 나누면 한 파일이 죽어도 나머지 파일의 XML과 로그가 남는다. e2e `agent` 픽스처도 이미 `scope="module"`, 즉 파일 단위로 agent를 띄우고 치우므로(`dataplane_live.py:275-296`) 구조와도 맞는다.

**5. 남은 것 검사 (`:125-138`, 결정 10, 설계 §8-3)**
- LV는 기준선과 지금의 이름 목록을 `comm -13`으로 비교해 새로 생긴 것만 고른다 (`:127-129`). 컨테이너도 같다 (`:130-135`). 8080·8090 리스너는 사전 점검에서 비어 있었으므로 있으면 모두 남은 것이다 (`:136-138`).
- 이름 접두사(`e2ev*`, `anfe2e-cli-*`)가 아니라 기준선과의 **차이**로 본다. 통합 테스트는 볼륨 경로 `it-*`과 컨테이너 `it-client-*`를 써서 접두사만 보면 놓친다.
- 예외 하나 (`:133`): 실행 전에 있던 볼륨(`vol_<uuid32>`)의 인스턴스 `anf-nfs-<uuid32>`는 세지 않는다. agent와 통합 테스트의 시작 복구(`recover`)가 그 인스턴스를 다시 띄우기 때문이다.
- 지우지 않는다. 남는 것은 테스트의 정리 결함이고, 무엇이 남았는지가 고칠 단서다. e2e 픽스처에도 안전망이 있지만(`dataplane_live.py:286-293`, 이번 실행의 볼륨을 teardown에서 agent로 지운다), 그것은 픽스처의 teardown이 돌 때만 동작하고 클라이언트 컨테이너는 보지 않는다. 실행기의 검사는 그 바깥의 두 번째 층이다.

**6. 판정과 요약 (`:140-153`)**
- `junit_gate.py`에 모든 XML을 넘기고 (`:142`), 전체 시간, 0이 아닌 종료 코드의 파일, 남은 것을 출력한다 (`:144-146`). 셋 중 하나라도 걸리면 종료 코드 1 (`:147-148`).
- 이 블록은 `{ … } | tee summary.txt`라서 subshell에서 돈다 (`:141-152`). 블록 안의 `exit "$rc"` (`:151`)는 subshell만 끝내므로, 스크립트의 종료 코드는 마지막 줄 `exit "${PIPESTATUS[0]}"` (`:153`)가 넘긴다.

#### 판정 `backend/tests/junit_gate.py`

- **`read` (`junit_gate.py:21-32`)**: XML을 파싱하고 `root.iter("testsuite")`로 testsuite를 모두 모은다 (`:27`). `iter`는 루트 자신도 포함하므로, pytest의 기본 모양(`<testsuites>` 아래 `<testsuite>`)과 루트가 바로 `<testsuite>`인 모양을 한 줄로 다 받는다. `tests`, `failures`, `errors`, `skipped`, `time`을 합친다 (`:30-31`). 파일이 없거나(`OSError`) 깨졌거나(`ParseError`) testsuite가 없으면 `None` (`:23-29`).
- **`main` (`:40-71`)**: XML마다 한 행(파일, 수집, 통과, 실패, 오류, skip, 초)을 찍고, 합계 행과 `collected N, skipped M` 줄을 찍는다 (`:47-58`). 통과 수는 `tests - failures - errors - skipped`로 계산한다(`line`, `:35-37`). 그다음 문제를 모은다: 읽을 수 없는 XML(`:61-62`, "pytest did not finish"), 수집 0개(`:63-64`), 실패·오류(`:65-66`), skip(`:67-68`, "Skipped tests are not passes. Run them here or deselect them by marker on purpose."). 하나라도 있으면 1 (`:71`).
- 초는 XML의 `time`, 즉 pytest가 `perf_counter`로 잰 세션 시간이다(단조 시계, 설계 §8-4).
- **CI의 옛 인라인 검사와 다른 점.** 옛 검사는 수집 0개와 skip만 봤다(`docs/concepts/ci.md` 3.2). 새 스크립트는 실패·오류와 읽을 수 없는 XML도 본다. CI에서는 Test 단계가 실패하면 다음 단계가 돌지 않으므로 이 추가 검사가 하는 일이 거의 없다. 필요한 곳은 실행기다. 실행기는 실패한 파일 뒤에도 계속 돌고, pytest가 죽은 파일은 XML이 없거나 중간에 끊긴다. 여러 XML을 합치는 것도 실행기 때문이다.
- 출력이 모두 `print`로 표준 출력 한 곳에 가므로, 줄의 순서가 코드의 순서 그대로다. `ci.md` 5.2에는 옛 검사의 "오류 문구가 `collected …` 줄보다 먼저 찍힘"이 적혀 있다(원인은 표준 출력 버퍼링으로 적었다. 옛 검사는 `collected` 줄을 표준 출력에, 오류 문구를 `sys.exit(메시지)`로 표준 오류에 썼다). 코드로 보면 이 스크립트에서는 그 뒤바뀜이 생기지 않는다. PR #19의 Actions run 42782709293에서는 이 단계가 표와 `collected 988, skipped 0`을 찍고 통과했다(AC-07). 오류 문구가 나오는 실패 경우는 Actions에서 보지 않았다.
- **위치.** `backend/tests/` 아래에 두었다 (결정 6). TDD 훅의 면제 위치이고, 제품 코드 내용 해시(`backend/tests/` 제외)를 건드리지 않는다. `scripts/` 아래 `.py`로 두면 훅이 짝 테스트를 요구하는데 `scripts/`는 pytest 경로 밖이다. 이름이 `test_`로 시작하지 않으므로 pytest가 테스트로 모으지도 않는다.

#### CI `.github/workflows/ci.yml`

- Test 단계는 그대로다: `ANF_E2E_API_URL`을 켜고 `python -m pytest -m "not dataplane" --junitxml=pytest-results.xml` (`ci.yml:43-46`).
- "Fail on skipped tests" 단계가 인라인 Python 대신 `python backend/tests/junit_gate.py pytest-results.xml` 한 줄이 됐다 (`ci.yml:50-51`). 출력 `collected …, skipped …`와 skip 오류 문구는 옛 검사와 같다(보고서 AC-07).
- CI가 데이터 플레인 테스트를 돌리지 않는 것은 skip이 아니라 마커로 **선택에서 뺀** 것이다(`-m "not dataplane"`, 마커 정의는 `pyproject.toml:27-31`). 빠진 테스트는 deselected로 세어지고 XML의 `tests`에 들어가지 않으므로 게이트가 실패로 보지 않는다. 이 둘의 구별이 skip 규칙의 핵심이다: 조건이 없어 조용히 빠진 것(skip)은 실패, 사람이 일부러 마커로 뺀 것(deselect)은 실패가 아니다.

#### 판정 스크립트의 테스트 `backend/tests/unit/test_junit_gate.py`

- 게이트를 import해서 부르지 않고 **별도 프로세스로 실행**한다 (`gate`, `test_junit_gate.py:32-34`). 실행기와 CI가 둘 다 명령으로 부르므로, 종료 코드와 출력을 명령 그대로 확인한다(모듈 docstring `:4-5`).
- 가짜 XML은 `suite`와 `xml`로 만든다 (`:18-29`). `wrapped=False`면 루트가 `<testsuite>`인 모양이다.
- 시험하는 경우: 모두 통과면 0과 수 (`test_all_passed_exits_0_with_counts`, `:42`), 루트가 `<testsuite>`인 모양 (`test_testsuite_root_is_read_too`, `:50`), skip 하나면 1과 문구 (`test_a_skip_fails`, `:56`), 수집 0개면 1 (`test_nothing_collected_fails`, `:64`), 실패·오류면 1 (`test_failures_and_errors_fail`, `:71-79`, 매개변수 `failure`·`error`), 여러 파일의 수가 합쳐짐 (`test_counts_add_up_across_files`, `:82`), 여러 파일이 모두 통과하면 0 (`test_files_that_all_pass_together_exit_0`, `:93`), 깨진 XML과 없는 XML은 나머지가 통과해도 1이고 이름이 찍힘 (`test_missing_or_unreadable_xml_fails_and_is_named`, `:99-110`).
- 이 파일은 훅 면제 위치의 파일이라 훅이 테스트 우선을 강제하지 않는다. 짝 단위 테스트를 먼저 쓰는 것은 설계 결정 6이 정했다.

#### 대응표와 그 검사 `docs/testing.md`, `backend/tests/unit/test_testing_doc.py`

- `docs/testing.md`는 테스트 층(§1), 어디서 무엇이 도는지(§2), 실행기 사용법·출력·종료 코드(§3), 대응표(§4), 알려진 한계(§5)를 담는다. 대응표는 PRD §6.1 FR-01~FR-08의 수락 기준 문장마다 pytest node ID(파일::함수[매개변수 ID])와 "클라이언트에서 관찰하는 것" 한 줄을 적는다. FR-09는 프론트엔드 테스트와 브라우저 검증을 가리키는 한 줄이다.
- 표는 손으로 쓴다 (결정 11). 표가 썩는 가장 흔한 방식은 테스트 이름이 바뀌는 것이라, 그것만 테스트로 막는다.
  - `test_every_node_id_in_the_doc_is_collected` (`test_testing_doc.py:22-30`): 정규식 `NODE_ID` (`:15`)로 문서의 node ID를 뽑고, 그 파일들을 `pytest --collect-only -q`로 수집해 node ID가 한 글자도 다르지 않게 있는지 본다. 매개변수 ID까지 맞는다 (설계 §8-9).
  - `test_each_of_fr01_to_fr08_has_a_row_with_a_test` (`:33-37`): FR-01~FR-08마다 node ID가 있는 행이 하나 이상인지 본다.
- 이 테스트는 데이터 플레인 파일도 수집하는데, Windows TDD 훅에서도 돈다. 수집은 root가 필요 없고, 테스트 모듈이 import할 때 Linux 전용 모듈을 쓰지 않기 때문이다(ADR §9.2, 예: `dataplane_live.py:97`에서 `pwd`를 함수 안에서 import한다).
- 표가 PRD 문장을 **빠짐없이** 담는지는 이 테스트가 보지 않는다(모듈 docstring `:4-5`). 리뷰와 검증 AC-03이 본다. 검증에서는 verifier가 PRD 문장을 잘라 표와 맞춰 보는 일회성 스크립트를 썼다.
- 표를 쓰다 확인된 것 (설계 §8-10): PRD §6.1 FR-01~FR-08의 수락 기준이 모두 묶음의 자동 테스트에 대응해, 빈 곳을 채울 e2e를 더하지 않았다. 남긴 단서 둘: 클론에는 `Canceled`로 끝나는 경로가 없다(FR-01, 종결 상태 집합에만 있다). ARM 볼륨에는 한도가 없는 경우가 없어서 FR-08의 "제한이 없는 볼륨"은 4,500 MiB/s 볼륨과, 한도 없이 만든 agent 볼륨(통합 테스트)이다.

### 3.4 설계 결정

결정은 모두 로드맵 총괄의 `자동 채택`이다(사용자에게 묻는 결정 없음).

| 결정 | 버린 대안 | 이유 |
| --- | --- | --- |
| 1. 범위는 "묶음을 명령 하나로, skip 없이, 근거가 남게". 새 프레임워크·층을 만들지 않는다 | 테스트 구조 재편(폴더·픽스처 통합), smoke 묶음, 데모 시나리오 테스트 | 테스트는 이미 있고 통과했다. 고장 나지 않은 구조를 바꾸면 완료된 기능의 회귀 근거가 흔들린다 |
| 2. 실행기는 bash, 집계만 Python | 전부 Python, Makefile, pytest 플러그인 | 하는 일이 사전 점검, 환경 변수, 파일별 pytest 호출, `drop_caches`라 셸로 그대로 읽힌다. `scripts/setup-wsl-dataplane.sh`와 같은 자리·같은 방식. WSL에 make가 있다는 보장이 없다 |
| 3. 파일마다 pytest 프로세스, 사이에 `sync` + `drop_caches` | pytest 한 번으로 전체 | FR-08에서 page cache 6.8 GB로 호스트가 실행기를 죽였다. 한 파일이 죽어도 나머지 결과가 남는다. 픽스처도 파일 단위다 |
| 4. 실패해도 끝까지, 마지막에 1. `-x`류는 인자로 넘길 수 있다 | 첫 실패에서 멈춤 | 전체가 1시간이 넘는다. 한 번에 실패 목록을 다 보는 편이 싸다 |
| 5. skip·수집 0개·오류는 실패. 파일별 XML을 합쳐 판정하고, 같은 스크립트를 CI도 쓴다 | 데이터 플레인만 따로 검사, pytest 종료 코드만 믿기 | 두 실행 경로가 "skip은 PASS가 아니다"(PRD §8, ADR §9.1)를 같은 코드로 지킨다. pytest는 skip만 있어도 0이다 |
| 6. 판정 스크립트는 `backend/tests/junit_gate.py`, 짝 테스트를 먼저 쓴다 | `scripts/` 아래 `.py`, 인라인 heredoc 유지 | 훅 규칙과 맞고 판정 로직(여러 XML, 두 루트 모양, 빈 묶음)이 테스트로 고정된다. 제품 코드 해시 밖이다 |
| 7. 사전 점검을 못 채우면 테스트를 돌리지 않고 2 | 점검 없이 pytest의 skip·setup 오류에 맡김 | 70개 넘는 테스트가 같은 이유로 skip·오류가 난다. 원인을 한 줄로 먼저 말한다. 포트가 차 있으면 다른 세션의 데이터 플레인을 건드리지 않는다 |
| 8. VG가 없으면 실행기가 붙인다(제품 코드 불변) | 사람이 agent를 한 번 띄움, e2e 픽스처 수정 | WSL은 쉬면 꺼지고 재부팅 뒤 loop 장치가 사라진다. NFR-03(문서대로 따라 하면 된다) |
| 9. 출력은 WSL 디스크 `/var/tmp/anf-clone-tests/<UTC 시각>`, 끝에 경로와 요약. 저장소로 복사하지 않는다 | 저장소(`/mnt/c`) 아래, `/tmp` | 9P는 3~4배 느리고 시간 판정이 흔들린다. `/tmp`는 WSL이 꺼지면 사라진다. 보관은 부르는 쪽이 한다 |
| 10. 남은 것은 출력하고 실패로 센다. 지우지 않는다. 실행 전에 있던 것은 기준선으로 뺀다 | 실행기가 강제로 치움 | 정리 결함을 숨기지 않는다. 사용자가 띄워 둔 볼륨은 실패로 세지 않는다 |
| 11. 대응표는 손으로 쓰는 문서 하나, node ID 수집은 단위 테스트가 확인 | 마커(`@pytest.mark.fr("FR-05")`)로 자동 생성, 검사 없음 | 60개 넘는 통과한 테스트 파일을 모두 고쳐야 한다. 표는 리뷰어가 읽는 문서다 |
| 12. 대응표의 대상은 PRD §6.1 FR-01~FR-08의 수락 기준 문장 | 설계별 AC 전부(약 100개) | FR-10의 수락 기준이 "마운트, 스냅샷, 처리량 효과를 확인하는 테스트"다. 설계별 AC는 각 사이클의 진행 기록에 표가 있다 |
| 13. 기존 테스트의 판정·이름·구조는 바꾸지 않는다. 실패가 제품 결함이면 멈추고 보고한다 | 이번에 e2e 도우미 정리 | 제품 코드가 바뀌면 FR-04~FR-08의 검증이 무효가 된다(무효화 규칙) |

### 3.5 구현 중 정한 것 (설계 §8)

결정 1~13의 뜻은 바뀌지 않았다. 구현이 정하거나 좁힌 것은 위 3.3에 위치와 함께 설명했다. 목록만 모으면 이렇다.

1. VG 붙이기는 `FlexVolManager(Runner()).ensure_aggregate()`를 그대로 부른다(agent 잠깐 띄우기, `losetup` 복사는 버림).
2. venv는 저장소 주인의 `~/.venvs/anf-clone`.
3. 남은 것 검사는 이름 접두사가 아니라 기준선과의 차이, 기준선 볼륨의 인스턴스는 예외.
4. 요약 표의 초는 XML `time`, 실행기 자체의 시간은 `/proc/uptime`.
5. pytest 종료 코드도 본다.
6. `ANF_E2E_API_URL`은 없을 때만 기본값, 빈 값은 그대로.
7. `-v`, `-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`.
8. 경로 인자 구분 규칙(`--deselect=` 꼴).
9. 대응표 검사는 `pytest --collect-only`로.
10. 빈 곳 채우기는 할 것이 없었다.

### 3.6 이번에 만들지 않은 것

| 안 만든 것 | 이유 |
| --- | --- |
| CI의 data-plane 작업과 스파이크 S3 | FR-11이다. 이번 실행기는 그 작업이 부를 명령이 된다 |
| PRD §5 데모 대본 스크립트 | 전체를 명령 하나로 띄우는 FR-13에서 만든다 |
| 빠른 부분 묶음(smoke 마커) | 필요한 곳이 아직 없다. FR-11이 러너 시간 때문에 필요하면 그때 정한다 |
| 병렬 실행(pytest-xdist) | 데이터 플레인은 기기에 하나고(VG, IP 대역, 포트 8080·8090), 처리량 시험은 다른 I/O와 겹치면 판정이 흔들린다 |
| 메트릭 테스트, 프론트엔드 테스트 변경 | FR-12, FR-09의 일이다 |

## 4. 실제 ANF와 다른 점

해당 없음(ANF 기능이 아니다). 대신 면접에서 물을 만한 것, 즉 **이 테스트 환경이 재는 값이 실제 서비스와 달라질 수 있는 곳**을 `docs/testing.md` §5에서 옮긴다.

| 항목 | 이 프로젝트의 테스트 환경 | 결과에 주는 영향 | 대응 |
| --- | --- | --- | --- |
| 같은 커널 | 클라이언트 컨테이너와 knfsd가 같은 WSL 커널·메모리를 쓴다 (ADR R-08) | 처리량 측정과 page cache 효과가 실제 ANF(별도 VM, 네트워크)와 다를 수 있다 | NFS LOCALIO는 꺼져 있다(S0). 측정은 `fio --direct=1`, 읽기 전에 캐시를 비운다(`throughput_live.py:236-251`) |
| 시계 | WSL 벽시계가 건너뛴다 | 벽시계로 재면 처리량과 소요 시간이 틀어진다 | 처리량은 게스트 단조 시계로 판정한다. 실행기 시간도 `/proc/uptime` |
| CI | 데이터 플레인 묶음은 아직 CI에서 돌지 않는다 | PR마다 데이터 효과를 확인하지는 않는다 | 러너에서 커널 모듈과 privileged 마운트가 되는지는 FR-11의 S3가 정한다. 그때까지 근거는 WSL에서 실행기를 돌린 기록이다 |
| 기기에 하나 | VG, IP 대역, 포트 8080·8090을 같이 쓴다 | 병렬로 못 돌린다. 전체가 약 90분(아래 5절) | 파일을 차례로 돌리고, 포트가 차 있으면 시작하지 않는다 |
| 처리량 판정 방식 | 6회 재고 첫 회를 버린 5회의 중앙값이 한도의 90~101% (`throughput_live.py:240-251` `measure`) | 개별 회가 범위 안이라는 것은 단언하지 않는다. 실행 C에서 `m3` 20 MiB/s 쓰기의 첫 회는 11.659(58%)였고 버려졌다 | `docs/testing.md` FR-08 행의 문구를 이 방식에 맞게 고쳤다(`961e316`) |

## 5. 검증

**판정은 real-env-verifier가 WSL 실환경에서 했다.** implementer의 실행은 참고 기록이다. 사용자 결정으로 verifier는 약 90분짜리 전체 묶음을 다시 돌리지 않고, 이미 끝난 실행 A(앞 9개 파일)와 실행 C(남은 4개 파일)의 결과 파일로 AC-01·02·03·05·06을 판정했다. 짧은 항목(AC-04, AC-05의 일부러 남기기, AC-03의 수집, AC-08)은 직접 돌렸다. 실행 A·C가 검증 대상 코드와 같은 코드로 돌았다는 것은 커밋 시각, 파일 수정 시각, `git diff --stat`으로 먼저 확인했다(보고서 "실행 A·C가 검증 대상 코드와 같은지"). 2회차는 1회차에 UNVERIFIED였던 AC-01·AC-07만 다시 판정했다. AC-01은 인자 없는 전체 실행 D의 결과 파일로(다시 돌리지 않음), AC-07은 PR #19의 Actions run으로 봤다. 1회차 뒤 코드가 바뀌지 않아 1회차 PASS는 다시 돌리지 않았다.

**결과: PASS 8 / FAIL 0 / UNVERIFIED 0** (1회차 PASS 6 / UNVERIFIED 2, 대상 `6993c17`·HEAD `db3468c`. 2회차 대상 HEAD `ace0d39`, 같은 코드)

| 기준 | 결과 | 근거 |
| --- | --- | --- |
| AC-01 명령 하나로 전체, 종료 코드 0, skip 0 | PASS (2회차. 1회차 UNVERIFIED) | 2회차: 인자 없는 실행 D 한 번이 13개 파일·113개를 돌고 `total 113 113 0 0 0`, `collected 113, skipped 0`, `left behind` 없음, `exit 0`, 5,279 s(약 88분, 단조 시계)로 끝났다. 수집 수는 `pytest --collect-only -m dataplane`과 같고, XML 13개의 testcase 이름 집합이 `collect.log`의 113개와 같다. 1회차: 실행 A가 끊겨 실행 A의 9개 파일과 실행 C의 4개 파일을 합친 결과(113개 통과, skip 0, 5,399 s)만 있었고, 한 번의 실행이 끝까지 돌고 0으로 끝난 출력이 없어 PASS로 세지 않았다 |
| AC-02 실제 효과를 클라이언트에서 관찰하는 테스트가 통과 목록에 있다 | PASS | 항목마다 `.jsonl`에 클라이언트 쪽 근거가 있다. 아래 표 |
| AC-03 대응표 | PASS | PRD 문장 25개가 대응표 23행에 모두 있다(FR-02·FR-03의 두 문장짜리 기준을 각각 한 행에 둠). node ID 41개 모두 수집(`not collected 0`). 데이터 플레인 node ID 29개가 실행 A·C의 통과 목록에 있고, 나머지 12개는 AC-08 실행에서 통과 |
| AC-04 skip·실패는 1, 준비가 빠지면 2 | PASS | (a) 일반 사용자: `precheck failed: not root…`, exit 2. 8090을 다른 프로세스가 잡음: 원인과 그 프로세스가 찍히고 exit 2. 두 경우 모두 출력 폴더가 생기지 않았다. (b) `ANF_E2E_API_URL=`(빈 값)으로 계약 파일 하나: 5개 모두 SKIPPED, pytest는 exit 0, 실행기는 `collected 5, skipped 5`와 skip 문구를 찍고 exit 1. (c) 실패하는 임시 파일 + 계약 파일: 첫 파일 pytest exit 1, 이어서 둘째 파일이 실제 agent·anf-api로 `5 passed`, 요약 `total 6 5 1 0 0`, exit 1 |
| AC-05 남기지 않음 | PASS | 실행 C의 `summary.txt`에 `left behind`가 없고 exit 0. 2회차 보충: 실행 D는 빈 기준선(LV·컨테이너 없음)에서 끝까지 돌았고 `left behind` 줄이 없다. 기준선 예외도 걸리지 않은 경우다. 컨테이너 하나를 일부러 남기는 임시 테스트: `1 passed`인데 `left behind (not removed): container anfe2e-cli-fr10leak`, exit 1, 컨테이너는 그대로 있었다(지우지 않음) |
| AC-06 재부팅 뒤 첫 실행 | PASS | 실행 C: 부팅 7초 뒤 기준선, 첫 줄 `VG anf: not attached (WSL restarted?); attaching it the way the storage agent does at start`, 4개 파일 28개 통과, exit 0. 구현 때의 시험 `20261110T045258Z`: 부팅 16초 뒤, 통합 30 + e2e 데이터 7 = 37개 통과, exit 0. 검증 중에도 WSL VM이 여러 번 다시 떠서 AC-04 (b)·(c)가 같은 첫 줄로 시작했다 |
| AC-07 CI가 같은 판정 코드를 쓰고 Actions가 통과 | PASS (2회차. 1회차 UNVERIFIED) | PR #19의 run 42782709293: `event: pull_request`, head `ace0d39`, 결론 success. backend 작업(Lint, Test, Fail on skipped tests, Hook tests)과 frontend 작업(Install, Type check, Test, Build) 모두 success. Test 단계 `988 passed, 113 deselected in 143.39s`. Fail on skipped tests 단계가 `python backend/tests/junit_gate.py pytest-results.xml`을 돌려 `total 988 988 0 0 0`, `collected 988, skipped 0`을 찍었다. 1회차 WSL 실행(AC-08)과 같은 스크립트·같은 수. 1회차에는 `ci.yml:43-51`의 호출만 확인했다 |
| AC-08 제품 코드 불변, 비데이터 플레인 skip 0, ruff | PASS | 해시가 시작·끝 모두 `f99bc5cf…`. WSL `-m "not dataplane"`이 `988 passed, 113 deselected in 190.09s`, 게이트 `collected 988, skipped 0`. ruff `All checks passed!` |

**2회차 (2026-11-10): AC-01과 AC-07을 닫다**

- **실행 D (AC-01).** `/var/tmp/anf-clone-tests/20261110T080605Z`, 콘솔 `console-full2.log`. 인자 없이 WSL 안에서 분리해 띄웠다. 시작 때 기준선은 LV·컨테이너 모두 비어 있었고, 콘솔 첫 줄이 `VG anf: not attached (WSL restarted?); attaching …`이라 VG도 실행기가 스스로 붙였다. 13개 파일의 `pytest exit`가 모두 0(`files.tsv`), `summary.txt`는 `total 113 113 0 0 0`, `collected 113, skipped 0`, `time: 5279 s for 13 files (monotonic clock)`, `left behind` 없음, `exit 0`. 가장 긴 파일은 처리량 데이터 2,251 s. 1회차에서 관찰하지 못한 것(한 요약으로 합친 종료 코드, 전체 실행 뒤의 남은 것 검사, 앞 9개 뒤에 4개를 같은 실행에서 이어 도는 경우)이 이 한 번에 모두 나왔다. 실행 중과 그 뒤의 커밋 `961e316`·`ace0d39`는 문서와 `_workspace/`만 바꿨고, 13개 로그 모두 같은 저장소 루트에서 돌았다(코드 대조, 2회차 보고서).
- **PR #19 (AC-07).** 위 표의 AC-07 행. CI의 skip 검사와 데이터 플레인 실행기가 같은 `junit_gate.py`로 판정한다는 것을 Actions 로그로 봤다.
- **문서.** `docs/testing.md` §3 "소요 시간"을 리더가 실행 D의 파일별 실측 표로 채웠다. 표의 파일별 초는 XML `time`(pytest 세션 시간)을 반올림한 값이고, 머리말의 5,279초는 실행기의 단조 시계 값이라 `files.tsv`와 1 s씩 다른 행이 있다(뜻은 같다). `CLAUDE.md` Commands 절에 실행기 줄이 들어갔다(`ace0d39`).
- **판정 밖 관찰.** 실행 D 도중 저장소 안에 다른 에이전트의 워크트리(`.claude/worktrees/…`, 브랜치 `spike/s3-runner`)가 생겼다. 실행기의 수집 경로 밖이라 대상은 변하지 않았다(수집 113, 이름 집합 같음). 그 에이전트가 WSL 데이터 플레인을 같이 썼는지는 보지 않았지만, 실행 D의 기준선은 비었고 남은 것도 없어 겹친 흔적은 보이지 않는다. `CLAUDE.md`는 워크트리를 형제 폴더에 두라고 한다.

**AC-02: 클라이언트 쪽 근거 (보고서 표의 요약)**

| 항목 | 테스트 | 클라이언트 쪽 근거 |
| --- | --- | --- |
| NFSv3·NFSv4.1 마운트와 읽기·쓰기 | `test_volume_data_live.py::test_ac02_nfsv3_mount_two_clients`, `::test_ac03_nfsv41_volume` | 클라이언트 A가 쓰고 B가 읽음, `/proc/mounts`에 `vers=3`·`vers=4.1`. 볼륨이 허용하지 않는 버전은 rc 32 `Protocol not supported` |
| 할당량 초과 쓰기 실패 | `test_ac04_quota_full_write_fails[NFSv3-3]`, `[NFSv4.1-4.1]` | `df` 크기 1,021,313,024 B, 1,229 MiB `dd`가 `No space left on device` |
| 삭제 뒤 마운트 거절 | `test_ac09_delete_volume` | 새 클라이언트 마운트 rc 32 `Host is unreachable`, 미리 마운트한 클라이언트는 `Stale file handle` |
| 지운 파일을 `.snapshot/<이름>/`에서 읽기 | `test_snapshot_data_live.py::test_ac02_ac03_…[AC-02-NFSv3-3]`, `[AC-03-NFSv4.1-4.1]` | 활성 트리에 없는 `A`를 `.snapshot/S/A`에서 읽음. 새로 마운트한 클라이언트도 같음 |
| 스냅샷 쓰기 거절 | `test_ac04_snapshot_and_snapshot_dir_are_immutable[…]` | 스냅샷 안의 쓰기 7종이 `Read-only file system`, `.snapshot` 자체는 `Operation not permitted` (이 테스트의 root 클라이언트, 이 순서에서 관찰) |
| 되돌리기 뒤 내용 | `test_snapshot_revert_data_live.py::test_ac02_ac03_…[…]` | `S2`와 트리가 같고 `S3`가 지워짐, 다시 `S1`로 되돌림 |
| 새 볼륨 내용과 원본 독립 | `test_restore_new_volume_data_live.py::test_ac02_ac03_ac04a_…[…]` | `S2`와 트리가 같고, 새 볼륨에 써도 원본과 base 스냅샷이 그대로, 반대 방향도 같음 |
| 처리량 한도 이하, 한도 변경, 제한 없는 볼륨과의 차이 | `test_throughput_limit_data_live.py`의 `test_ac01b_…`, `test_ac02_ac03_…`, `test_ac04_limit_changes_during_io`, `test_ac05_unlimited_volume_next_to_a_limited_one` | 아래 측정값 |

**측정값 (실행 C, 클라이언트 컨테이너 `fio --direct=1`, MiB/s, 게스트 단조 시계)**

- 한도 이하: 첫 회를 버린 5회의 중앙값이 한도의 0.99~0.997이었다. Auto 5 MiB/s(Ultra 40 GiB)에서 쓰기 4.967, 읽기 4.971(NFSv3), Manual 10 MiB/s에서 쓰기 9.95, 읽기 9.942, 읽기+쓰기 합 9.97, Manual 20 MiB/s에서 쓰기 19.867, 읽기 19.801, 합 19.867.
- 한도 변경(I/O 중, 2 s 창): 쓰기 볼륨 PATCH → 30이 29.814~29.915, → 5가 5.012~5.041, PUT → 10이 9.991~10.036. 읽기 볼륨도 같은 꼴(29.65~29.942, 5.017~5.038, 9.973~10.019).
- 제한 없는 볼륨 옆: 10 MiB/s 볼륨 A가 혼자 9.955, 함께 읽을 때 중앙값 9.9575, 4,500 MiB/s 볼륨 B의 중앙값 2,033.4. B가 A의 약 204배.
- 단서: 실행 C는 깨끗한 VG에서 돌지 않았다. 실행 B가 남긴 볼륨 2개와 그 knfsd 인스턴스 2개가 처리량 시험 내내 떠 있었다. 값은 모두 범위 안이라 판정에는 영향이 없었다(보고서 판정 밖 관찰 4). 2회차의 실행 D는 빈 기준선에서 처리량 데이터 파일까지 통과했지만, 2회차 보고서는 그 측정값을 따로 옮기지 않았다. 위 값은 실행 C의 것이다.

**판정 밖 관찰 (1회차 보고서)**

1. `docs/testing.md` §3 "소요 시간"이 비어 있었다. 1회차 때의 실측은 두 실행의 합 5,399 s였고, 파일별로는 처리량 데이터 2,256 s(약 38분)가 가장 길었다. 2회차 뒤 리더가 실행 D(5,279 s)의 파일별 실측 표로 채웠다.
2. `docs/testing.md` FR-08 첫 행의 "회마다 한도의 90~101%"가 테스트의 단언(첫 회를 버린 5회의 중앙값)과 달랐다. `961e316`에서 문구를 고쳤다. 테스트는 바꾸지 않았다.
3. 이 기기의 WSL VM은 쉬면 몇십 초 만에 내려간다. 검증 중에도 세 번 다시 떴고, 그때마다 VG가 떨어지고 `/tmp`가 비워졌다. 실행기의 VG 붙이기와 `/var/tmp` 출력이 바로 이 경우를 덮는다. 약 90분짜리 전체 실행은 VM이 그동안 떠 있어야 하고, 실행 C처럼 WSL 안에서 분리해 띄우는 것이 이 기기에서 통한 방법이었다.
4. 실행 C는 깨끗한 VG에서 돌지 않았다(위 측정값의 단서).
5. 남은 것 검사의 예외(기준선 볼륨의 인스턴스는 세지 않음)는 AC-05 문구보다 넓다. 복구가 띄운 인스턴스라는 판단은 맞지만, 테스트가 기준선 볼륨의 인스턴스를 멈춘 채 두거나 남긴 경우를 구별하지 못한다(이번에는 해당 없음).
6. 사전 점검 실패는 출력 폴더를 만들기 전에 끝나므로 `summary.txt`가 남지 않는다. 원인은 표준 오류의 한 줄뿐이라, CI나 다른 호출자는 표준 오류를 따로 받아야 한다.

**증명하지 못한 것 (2회차 뒤)**

1회차에 남았던 셋(명령 하나로 끝까지 돌고 0으로 끝나기, Actions에서의 판정, 빈 데이터 플레인에서 처리량 데이터 파일을 끝까지 돈 실행)은 실행 D와 PR #19로 닫혔다. 남은 것은 판정 기준 밖의 것이다.

- **반복 안정성.** 한 번에 끝까지 돈 전체 실행은 실행 D 하나다. 여러 번 돌려도 같은 결과인지(flaky 여부)는 재지 않았다.
- **CI의 데이터 플레인.** Actions가 돌리는 것은 `-m "not dataplane"`의 988개다. 데이터 플레인 113개는 여전히 WSL 실행기 기록이 근거다(FR-11, S3).
- **남은 것 검사 예외의 구별.** 판정 밖 관찰 5의 경우(테스트가 기준선 볼륨의 인스턴스를 멈춘 채 두거나 남김)는 실행기가 구별하지 못한다. 실행 D는 기준선이 비어 있어 이 예외를 시험하지 않았다.
- **사전 점검 실패의 기록.** 원인은 표준 오류의 한 줄뿐이다(관찰 6).

## 6. 개발 과정

1. **조사: 생략.** PRD §8에 따라 FR-10은 조사를 거치지 않는다. 새 스파이크도 없다. 새 데이터 플레인 동작에 기대지 않고, 기존 e2e가 기대는 S0·S1·S2·S4~S7은 그대로다.
2. **설계 (2026-11-09).** `anf-roadmap` 총괄이 맡았고 사용자에게 묻는 결정은 없었다. 결정 1~13을 자동 채택했다. 범위는 실행기, 공용 판정 스크립트, 대응표, 빈 수락 기준 채우기다. 수락 기준은 AC-01~AC-08이다.
3. **구현 (feature-implementer, Claude).** 커밋 `d2eff17`(junit_gate와 `ci.yml`), `9227be6`(실행기), `744b17d`(`docs/testing.md`와 대응표 검사), `6993c17`(설계 §8 기록). 제품 코드 해시는 그대로였다. 빈 수락 기준을 채울 e2e는 필요 없었다.
4. **긴 실행이 두 번 끊김.** 아래 표. 사람이 내린 결정이 여기서 나왔다.

| 실행 | 출력 폴더 | 대상 | 결과 |
| --- | --- | --- | --- |
| 구현 때 재부팅 시험 | `20261110T045258Z` | 통합 1 + e2e 데이터 1 (37개) | 부팅 16초 뒤 시작, VG를 스스로 붙임, 37 통과, exit 0 |
| A (implementer의 전체 실행) | `20261110T050559Z` | 인자 없음, 13개 파일 113개 | 앞 9개 파일 pytest exit 0(2,632 s). 10번째 처리량 데이터 파일의 3번째 테스트(`test_ac04_limit_changes_during_io`) 도중 implementer 에이전트가 멈추면서 함께 끊겼다. `summary.txt` 없음, implementer의 최종 보고도 없음. 컨테이너 3개와 LV 2개가 남아 메인 세션이 지웠다 |
| B (남은 4개 파일) | `20261110T061156Z` | 경로 인자 4개 | 처리량 데이터 7번째 테스트 도중 호스트 메모리 부족으로 끊겼다(Claude Code가 백그라운드 명령을 강제 종료). 볼륨 2개(`e2evbf9e-d9`, `-d9s`)를 남김. 근거로 쓰지 않는다 |
| C (남은 4개 파일, 다시) | `20261110T065647Z` | 경로 인자 4개 | WSL 안에서 분리해 띄움. WSL 재부팅 직후라 VG를 스스로 붙였다. B의 볼륨 2개가 기준선에 잡힌 채 돌았고, 그 인스턴스는 agent 시작 복구가 다시 띄웠다. 28 통과, skip 0, exit 0, 2,767 s(처리량 데이터 2,256 · 볼륨 계약 120 · 데이터 215 · 복구 176). 끝난 뒤 메인 세션이 그 볼륨 2개와 인스턴스를 지웠다 |
| D (AC-01을 닫는 전체 실행) | `20261110T080605Z` | 인자 없음, 13개 파일 113개 | WSL 안에서 분리해 띄움(콘솔 `console-full2.log`). 시작 때 기준선 비어 있음, VG를 스스로 붙임. 113 통과, skip 0, exit 0, 5,279 s(약 88분, 처리량 데이터 2,251 s), 남은 것 없음 |

   - **사람이 내린 결정 (사용자).** (1) verifier는 전체 묶음을 다시 돌리지 않는다. 실행 결과 파일로 판정하고 짧은 항목(AC-04·05·06·08)만 직접 돌린다. (2) 끊긴 실행은 남은 4개 파일만 실행기로 돌려 앞 9개의 결과와 합치고, AC-01은 두 번에 나눠 확인한 것으로 기록한다. (3) 실행 B가 끊긴 뒤 다시 진행하라고 지시했다.
   - 이 실행들이 실행기 설계를 실제로 시험했다. 실행 C와 구현 때의 시험은 사람 손 없이 VG를 붙였다(결정 8). 끊긴 실행 B의 잔여물은 다음 실행의 기준선으로 빠져 실패로 세지 않았다(결정 10). 반대로 "깨끗하지 않은 데이터 플레인에서 돈 실행"이라는 단서도 남았다.
5. **실환경 검증 1회차 (real-env-verifier, 2026-11-09~10).** PASS 6, UNVERIFIED 2(AC-01, AC-07), FAIL 0. 실패를 일부러 만드는 임시 테스트 파일 둘(실패, 컨테이너 남기기)과 임시 조건 둘(빈 `ANF_E2E_API_URL`, 8090 점유)로 실행기의 실패 경로를 확인한 뒤 모두 치웠다. 판정 밖 관찰 중 문서 둘은 메인이 고친다: FR-08 행의 문구(`961e316`에서 고침), §3 소요 시간(실행 D 뒤 채움).
6. **실환경 검증 2회차 (real-env-verifier, 2026-11-10).** 남은 둘을 닫아 누적 PASS 8 / FAIL 0 / UNVERIFIED 0. AC-01은 실행 D의 결과 파일로(다시 돌리지 않음), AC-07은 PR #19의 run 42782709293으로 판정했다. 리더가 `docs/testing.md` §3 "소요 시간"을 실행 D의 파일별 실측 표로 채웠고, 설계 §6이 마지막 단계에 둔 `CLAUDE.md` Commands 절의 실행기 줄을 넣었다(`ace0d39`).
7. **AI를 쓴 방식.** 설계 기록, 구현, 검증, 이 문서를 Claude 에이전트(로드맵 총괄, implementer, verifier, 문서 작성)가 나눠 맡았다. 사람은 긴 실행을 어떻게 나누고 무엇으로 판정할지를 정했다. verifier는 implementer의 실행을 그대로 믿지 않고, 실행 결과가 검증 대상 코드와 같은 코드에서 나왔는지부터 확인했다.

---

## 7. Interview Q&A

### Q1. Your tests already existed. What did "test automation" add?

**A.** It added the automation around the tests, not new tests. Each feature cycle had its own data-plane tests, and they had passed, but running them meant remembering a list of steps: set environment variables, drop the page cache between files, re-attach the LVM volume group after a WSL restart, and check that nothing was left behind. I turned that into one root command, `run-dataplane-tests.sh`. It discovers every test with the `dataplane` marker, runs them, and exits zero only if everything passed with no skips and no leftovers. I also wrote `docs/testing.md`, which maps each PRD acceptance sentence to a pytest node ID, and a unit test fails if any node ID in that table stops existing.

### Q2. Why is a skipped test a failure, and how do you enforce that in two places?

**A.** Because pytest exits with code zero when tests are skipped, so a missing precondition can look like a green run. My end-to-end tests skip when one environment variable is empty, so one typo could hide all of them. I enforce the rule with one small script, `junit_gate.py`. It reads JUnit XML files, sums tests, failures, errors, and skips, and exits one if anything failed or was skipped, if nothing was collected, or if an XML file is missing or truncated. The CI job and the data-plane runner both call it, so the rule cannot drift. I checked the runner path on purpose: with the variable set to empty, five tests skipped, pytest exited zero, and the runner exited one. Deselecting by marker is different: that is a visible, deliberate choice.

### Q3. Why one pytest process per file, with the page cache dropped in between?

**A.** Because one long pytest process got killed. During the throughput feature, I ran fourteen files in a single process. After five files, the WSL page cache had grown to about 6.8 gigabytes, and the host killed the run for lack of memory. My NFS clients and servers share one kernel and about seven gigabytes of RAM. The fix was to call `sync` and `drop_caches` before each file and start a fresh pytest; with that, the remaining eleven files passed. Per-file runs also keep results safe: if one file crashes, every other file still has its own XML, log, and evidence file. And my e2e fixtures already start and stop the storage agent per module, so this matches the existing structure.

### Q4. The runner reports leftovers but does not delete them. Why?

**A.** Because a leftover is a cleanup bug in a test, and deleting it would destroy the clue. Before the run, the runner records every logical volume in the volume group and every container as a baseline. Afterwards it compares by difference, not by name prefix, because integration tests use different prefixes than e2e tests. Anything new is printed as "left behind" and the run exits one. I verified it with a temporary test that started a container and then passed: the runner named that container and failed, and the container was still there. One exception: if a volume existed before the run, its NFS server container can come back through the agent's startup recovery, so the runner does not count it.

### Q5. How does the runner survive a WSL restart without changing product code?

**A.** It calls the storage agent's own function. When WSL restarts, the loop device behind my LVM volume group disappears, and every e2e test then errors at setup, because the fixture lists volumes first. In the throughput cycle, a whole regression run was setup errors for that reason, and the agent had to be started once by hand. Now the runner checks with `vgs`, and if the group is missing, it imports `FlexVolManager` and calls `ensure_aggregate`, the first step the agent runs at startup. I rejected starting the agent, because its recovery also restarts NFS instances of existing volumes and would change the baseline. I also rejected copying the `losetup` steps into bash, which duplicates logic. A content hash confirms the product code did not change.

### Q6. What can this suite not prove?

**A.** Three things. First, clients and NFS servers run on the same WSL kernel and memory, so throughput and page-cache effects can differ from a real service where client and server are separate machines on a network. Second, the data-plane suite does not run in GitHub Actions yet. Whether a hosted runner can load the kernel modules and do privileged mounts is spike S3, part of the CI feature, so for now the evidence is runner output from one machine. Third, the data plane exists once per machine, so files run one at a time, and the full suite takes about ninety minutes, about thirty-eight of them in the throughput file. That is too slow for every commit, so a smaller smoke set may be needed later.

### Q7. Tell me about a test run that failed for reasons outside your code.

**A.** My first full run was interrupted twice, and neither failure came from the tests. Run A stopped in the tenth of thirteen files when the agent session running it ended; it left containers and volumes behind, which were cleaned up by hand. Run B, with the remaining four files, was killed because the host ran out of memory. Run C worked because I launched it detached inside WSL, so it no longer depended on the calling session. It started seven seconds after a WSL reboot, attached the volume group by itself, and passed 28 of 28. But run B's two leftover volumes were still there, so run C took them as baseline. The results were valid, yet not from a clean data plane, and the verifier recorded that limitation.

### Q8. If you built this again, what would you change?

**A.** I would plan for a ninety-minute run on a machine that sleeps. During verification, the WSL VM shut down after tens of seconds of idle time, which detached the volume group and emptied `/tmp`. Writing output to `/var/tmp` and re-attaching the group already handle that, but I would launch long runs detached from the start, instead of learning it from two interrupted runs. I would also fix two gaps the verifier noted. A precheck failure leaves only one line on stderr and no summary file, so I would write that reason to a file for CI callers. And the baseline exception for restarted instances cannot tell a recovered instance from one a test stopped and left, so I would check its state too.

### Q9. How do you know the runner itself works?

**A.** I tested its failure paths, not only the green path. Running as a normal user, or with port 8090 taken, gave exit code two, a one-line reason, and no output folder. An empty API URL made five tests skip while pytest exited zero; the runner exited one. A deliberately failing file returned one, and the next file still ran and passed. A test that leaked a container made the runner name it and fail. For the full suite, the first round found all 113 tests passing, but only across two runs, so "one command, exit zero" was marked unverified, not passed. The second round closed it with one uninterrupted run: 113 passed, zero skips, nothing left behind, about 88 minutes. The pull request's Actions run showed the same gate script printing 988 collected, zero skipped.

### Q10. How do you keep the acceptance-criteria table from going stale?

**A.** A unit test parses the table and asks pytest to collect every node ID in it. The table in `docs/testing.md` is handwritten: each PRD acceptance sentence for FR-01 to FR-08 points to pytest node IDs and one line on what the client observes. Renamed tests are the usual way such tables rot, so `test_testing_doc.py` extracts the node IDs with a regex, runs `pytest --collect-only` on those files, and fails if any ID is missing, including parameter IDs. It also checks that every FR from 01 to 08 has a row with a test. I chose this over adding markers to more than sixty passing tests, which would have meant editing every verified test file. Whether the table covers every PRD sentence is still checked in review.
