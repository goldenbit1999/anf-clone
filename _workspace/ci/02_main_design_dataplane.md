# ci 설계 2부 (FR-11 CI, data-plane 작업)

- 확정일: 2026-11-10 (`anf-roadmap` 총괄. 사용자에게 묻는 결정 없음, 아래 결정은 모두 `자동 채택`)
- 1부(backend 작업)는 `02_main_design.md`, frontend 작업은 `_workspace/dashboard/02_main_design.md` §6이다. 이 문서로 FR-11의 남은 범위가 끝난다.
- 조사 브리프: 없음 (PRD §8)

## 1. 관련 ID

| 종류 | ID |
| --- | --- |
| PRD | FR-11("실제 커널을 쓰는 통합 테스트는 GitHub 러너에서 가능한지 확인한 뒤 넣는다"), FR-10, NFR-03(재현성), §9("main 브랜치의 CI가 통과 상태") |
| ADR | §9.1, §9.3(data-plane 행), §10 S3, D-12(볼륨 인스턴스, ns를 rshared로), R-08 |
| 스파이크 | **S3 조건부 통과** (`_workspace/spikes/S3.md`, 2026-11-10): `ubuntu-24.04` 호스트 러너(커널 7.0.0-azure, 4 vCPU, 16 GB)에서 모듈·패키지·준비 스크립트·실행기가 그대로 돌고, ns 전파를 private으로 바꾼 작업은 113개 전부 통과(4,378 s). 그대로 둔 작업은 8개 실패(전부 스냅샷 마운트가 두 번 보이는 것) |

## 2. 스파이크가 찾은 제품 결함

`NfsInstances.ensure_shared_ns()`(`backend/storage_agent/nfs_instance.py`)는 ns를 자기 자신에 바인드한 뒤 "shared가 아니면" `--make-rshared`를 한다. WSL의 `/`는 private이라 바인드도 private이고, rshared가 새 peer group을 만든다. systemd가 `/`를 shared로 두는 보통의 Linux 호스트에서는 바인드가 `/`의 peer group을 물려받아 이미 shared로 보이므로 rshared를 건너뛴다. 그 결과 ns 아래의 모든 마운트(볼륨, 스냅샷)가 바인드 밑에 깔린 원래 디렉터리에도 복제돼 호스트 마운트 표에 두 번 나온다. 러너의 tmpfs 탐침으로 확인했다(as-is는 `/`와 같은 `shared:1`, private 처리 뒤에는 자기 `shared:328`).

NFS 클라이언트가 보는 것은 같지만(S3의 as-is 작업에서 클라이언트 쪽 단언은 통과), 마운트가 두 벌이면 호스트 마운트 표가 볼륨·스냅샷 수의 두 배가 되고 "한 번 언마운트"의 뜻이 peer group 전파에 기대게 된다. 클론이 WSL에서만 맞게 도는 것은 NFR-03과 어긋난다.

## 3. 범위

### 이번에 만든다

1. **제품 수정**: `ensure_shared_ns()`가 바인드를 새로 만들었을 때 `--make-private` 뒤 `--make-rshared`를 해서 ns가 호스트 `/`와 다른 자기 peer group을 갖게 한다. 단위 테스트 먼저.
2. **`ci.yml`에 `data-plane` 작업**: 호스트 러너에서 준비 스크립트 → 실행기. 2개 조각(matrix)으로 나눠 병렬로 돈다.
3. **문서**: ADR §9.3·§10 S3·§9.1, `CLAUDE.md`(CI, 저장소가 public이라는 사실), `docs/testing.md` §5의 "CI에서 돌지 않는다" 한계 삭제와 CI 절, `docs/concepts/ci.md` 갱신.

### 이번에 만들지 않는다

- self-hosted 러너, 브랜치 보호 규칙(저장소 설정이라 사용자가 정한다. 제안만 한다), nightly 일정 실행, 러너 이미지 고정.
- 이미 `ns`가 `/`와 같은 peer group으로 바인드돼 있는 호스트의 자동 교정: WSL은 해당이 없고 러너는 매번 새 VM이다. 그런 호스트는 재부팅하거나 바인드를 풀면 된다(개념 문서에 적는다).

## 4. 결정

| # | 결정 | 버린 대안 | 이유 |
| --- | --- | --- | --- |
| 1 | `자동 채택` **ns 전파는 제품에서 고친다**(`--make-private` → `--make-rshared`) | (b) CI 워크플로 단계에서만 private 처리, (c) 테스트의 `snap_mounts()`가 중복을 지움 | 결함은 러너가 아니라 "`/`가 shared인 Linux"에서 생긴다. (b)는 CI만 다르게 돌아 CI가 제품을 검증하지 못하고, (c)는 두 벌 마운트를 남긴다. S3의 private 작업이 정확히 이 상태에서 113개를 통과했다. ADR D-12("ns를 rshared 마운트로")는 그대로다: rshared이되 자기 peer group이다 |
| 2 | `자동 채택` **제품 코드가 바뀌므로 회귀는 전체 묶음으로 본다**: WSL에서 실행기 전체 1회 + 러너의 data-plane 작업. FR-04~FR-08의 `done`은 유지하고 `docs/feature-status.md`에 회귀 근거를 더한다 | 기능별 재검증 5회, `done` 해제 | 바뀌는 것은 ns 바인드 직후의 전파 설정이고 WSL에서는 결과 상태가 같다(private → rshared는 지금도 일어나는 전이). 전체 묶음 113개가 FR-04~FR-08의 수락 기준을 모두 덮는다(`docs/testing.md` 대응표). 앞 사이클들도 공용 코드 변경을 회귀 AC로 다뤘다(스냅샷 AC-14, 처리량 AC-12) |
| 3 | `자동 채택` **2개 조각 matrix**: `throughput`(처리량 데이터 파일 하나, 약 36분)과 `rest`(나머지 12개 파일, 약 37분). 각 조각은 자기 VM에서 준비부터 한다 | 한 작업으로 전체(약 75분), 파일마다 조각(13개), PR에는 처리량을 빼고 main에서만 전체 | 처리량 데이터 파일이 전체의 49%라 둘로 나누면 거의 같은 길이가 되고 대기 시간이 반이 된다. 조각이 13개면 준비와 로그가 13번이고 얻는 것이 없다(가장 긴 조각이 여전히 36분). PR에서 처리량을 빼면 FR-08의 효과가 merge 전에 확인되지 않는다. 저장소가 public이라 러너 시간은 무료다 |
| 4 | `자동 채택` **`rest` 조각은 파일 목록을 적지 않고 "처리량 데이터 파일을 뺀 전부"로 고른다**(실행기에 pytest의 `--ignore=`를 넘긴다) | 12개 파일을 나열 | 새 데이터 플레인 테스트 파일이 생기면 자동으로 `rest`에 들어간다. 나열하면 빠뜨린 파일이 조용히 CI 밖에 남는다 |
| 5 | `자동 채택` **트리거는 main 대상 PR과 main push, `workflow_dispatch`**. backend·frontend 작업의 "모든 브랜치 push"는 그대로 둔다 | 모든 브랜치 push | 기능 브랜치는 push와 PR이 겹쳐 같은 37분 작업이 두 번 돈다. merge 전 확인은 PR 실행이, merge 뒤 상태는 main push 실행이 맡는다(PRD §9) |
| 6 | `자동 채택` **작업 구성은 S3에서 그대로 통과한 단계**: checkout → setup-python 3.12 → `~/.venvs/anf-clone`에 설치(1부 결정 5와 같음) → 러너 정보 기록(이미지 버전, `uname -r`, `findmnt -o PROPAGATION /`) → `sudo bash scripts/setup-wsl-dataplane.sh` → `sudo env ANF_TEST_OUT=… bash scripts/run-dataplane-tests.sh <조각 인자>` → `if: always()`로 권한을 풀고 dmesg를 더해 artifact 업로드. 모듈·패키지 설치 단계는 두지 않는다 | `apt-get install` 단계를 미리 둠, ns private 처리 단계 | S3에서 필요한 것이 모두 이미지에 있었다. 이미지가 바뀌어 빠지면 준비 스크립트나 실행기의 사전 점검이 원인을 말하며 실패한다. ns 단계는 결정 1로 필요 없어진다(있으면 제품 수정을 가린다) |
| 7 | `자동 채택` **`timeout-minutes: 75`**(조각마다), `fail-fast: false` | 기본 360분, fail-fast | 가장 긴 조각이 약 37분이다. 두 배를 넘기면 멈춘 것으로 본다. 한 조각이 실패해도 다른 조각의 결과를 본다 |
| 8 | `자동 채택` **판정은 실행기의 종료 코드 하나**(FR-10: 실패·오류·skip·수집 0·남은 것 = 1, 사전 점검 = 2). 워크플로에 따로 skip 검사를 두지 않는다 | `junit_gate.py`를 한 번 더 부름 | 실행기가 이미 같은 게이트를 부른다. 두 번 부르면 판정 경로가 둘이 된다 |
| 9 | `자동 채택` **러너 커널(7.0)과 WSL 커널(6.18)이 다른 것은 그대로 둔다.** 차이로 실패가 나오면 그때 원인을 가른다 | 커널 고정, 컨테이너 안에서 실행 | 호스트 러너의 커널은 고를 수 없다. S3에서 두 커널 모두 113개가 통과했고 처리량 비율도 범위 안이었다(러너 0.9946~1.0016, WSL 0.990~0.997). 다른 커널에서도 도는 것은 약점이 아니라 근거다 |
| 10 | `자동 채택` **준비 스크립트 이름(`setup-wsl-dataplane.sh`)은 바꾸지 않는다** | `setup-dataplane.sh`로 개명 | WSL 밖에서도 그대로 돈다는 것이 확인됐지만, 개명은 문서·스킬·기록 수십 곳을 건드린다. 스크립트 머리 주석과 문서에 "Ubuntu 24.04 호스트(러너 포함)에서도 쓴다"만 더한다 |

## 5. 검증 기준

판정은 GitHub Actions 실행과 WSL 실행기 출력으로 한다.

| ID | 종류 | 기준 |
| --- | --- | --- |
| AC-01 | data-plane 작업 (PRD FR-11) | main 대상 PR에서 `data-plane` 작업의 두 조각이 모두 success다. 두 조각의 실행기 요약을 합치면 수집 113(= `pytest --collect-only -m dataplane`의 수), 통과 113, 실패·오류·skip 0이고, 두 조각에 겹치거나 빠진 파일이 없다(13개 파일) |
| AC-02 | 그대로의 러너 | 그 실행의 워크플로에 ns 전파를 손대는 단계가 없고, 러너 정보 기록에 `/`의 전파가 `shared`로 찍혀 있다. 즉 S3의 as-is 조건에서 통과한 것이다. S3에서 실패했던 8개 테스트가 통과 목록에 있다 |
| AC-03 | 실패를 알림 | 데이터 플레인 테스트가 실패하면 그 조각이 failure다(임시 브랜치에서 실패하는 테스트로 확인. 시간을 줄이려고 그 브랜치에서만 대상을 좁혀도 된다). 실패해도 artifact는 올라온다 |
| AC-04 | artifact | 조각마다 실행기 출력 폴더(JUnit XML, `.log`, `.jsonl`, `summary.txt`)와 dmesg가 artifact로 남고 내려받아 읽을 수 있다 |
| AC-05 | 제품 수정의 효과 (WSL) | 수정한 코드로 WSL에서 볼륨과 스냅샷을 만들면 호스트 마운트 표에 각 마운트가 한 번만 있고, 클라이언트 컨테이너에서 볼륨과 `.snapshot/<이름>`이 보인다(인스턴스의 rslave 바인드가 여전히 동작). `/`가 shared인 호스트에서 ns의 peer group이 `/`와 다른 것은 러너 실행의 기록으로 본다 |
| AC-06 | 회귀 (WSL) | 수정한 코드로 `scripts/run-dataplane-tests.sh` 전체 1회: 113 통과, skip 0, exit 0, 남은 것 없음 |
| AC-07 | 기존 작업 | 같은 PR 실행에서 backend·frontend 작업이 통과한다(단위 테스트에 `ensure_shared_ns`의 새 경우 포함, skip 0, ruff) |
| AC-08 | 시간 | 각 조각이 50분 안에 끝난다 |

검증 대상 코드: 제품 코드 해시가 `f99bc5cf…`에서 바뀐다. 구현 뒤 새 해시를 `00_progress.md`에 적고, AC-05·AC-06과 Actions 실행이 그 해시의 코드인지 대조한다.

## 6. 구현 중 변경

설계를 바꾼 것은 없다. 설계가 정하지 않은 세부를 이렇게 정했다 (2026-11-10, feature-implementer).

1. **실행기는 고치지 않았다(결정 4).** `--ignore=<파일>`은 `-`로 시작해 실행기가 pytest 옵션으로 보고, 수집(`--collect-only -m dataplane`)과 파일마다의 실행에 그대로 넘긴다. WSL에서 실행기의 인자 분리·수집 줄(75~90행)을 그대로 돌려 확인했다: `rest`는 12개 파일 106개, 처리량 데이터 파일 0개. `throughput`(경로 인자)은 1개 파일 7개. 합 13개 파일 113개로 인자 없는 수집과 같다.
2. **`ensure_shared_ns()`는 바인드를 새로 만들었을 때만 `--make-private`를 한다.** 이미 마운트 지점이면 전과 같다(private면 rshared, shared면 아무것도 안 함). 그래서 이미 `/`와 같은 peer group인 바인드는 고치지 않는다(§3 범위 밖). 단위 테스트는 바인드 직후 전파가 shared로 보이는 경우(러너)도 순서가 bind → private → rshared인지 본다.
3. **ns 전파 기록은 테스트 뒤에 한다.** "Mount propagation of ns" 단계(`if: always()`)가 `findmnt --mountpoint ns`와 `/proc/self/mountinfo`의 `/`·ns 줄(peer group 번호)을 남긴다. 테스트 전에 남기려면 워크플로가 agent보다 먼저 제품 함수를 불러 바인드를 만들어야 해서, agent가 바인드를 만드는 그대로의 조건(AC-02)이 흐려진다. agent는 끝날 때 ns 바인드를 풀지 않으므로 테스트 뒤에도 보인다. `/`의 전파는 테스트 전 "Runner info" 단계에 있다.
4. **artifact**: 이름 `dataplane-<조각>-<run_attempt>`(다시 돌린 시도와 이름이 겹치지 않게, S3와 같음), `retention-days: 14`(S3와 같음), `if-no-files-found: warn`. 실행기 출력 폴더와 `dmesg.txt`만 올린다(결정 6). S3가 올린 pytest tmp의 agent 로그는 올리지 않는다.
5. **`workflow_dispatch`는 워크플로 수준 트리거라 손으로 돌리면 backend·frontend도 돈다.** 두 작업에는 조건을 더하지 않았다(결정 5의 "그대로").
6. **`concurrency`는 그대로다**(`ci-${{ github.ref }}`, `cancel-in-progress`). main에 연달아 merge하면 앞 main push 실행의 data-plane 작업이 취소되고 마지막 것만 끝까지 돈다.
