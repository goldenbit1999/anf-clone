#!/bin/bash
# 데이터 플레인 테스트 실행기 (테스트 자동화 설계 §5, FR-10). WSL Ubuntu에서 root로, 명령 하나로 돌린다:
#   MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash /mnt/c/<repo>/scripts/run-dataplane-tests.sh [경로·pytest 옵션...]
# 인자에 경로가 없으면 backend/tests/integration과 backend/tests/e2e에서 dataplane 마커 테스트가 있는 파일 전부를 돈다.
# 대상 파일은 수집 결과에서 얻는다(새 테스트 파일이 빠지지 않게). -k 같은 pytest 옵션은 그대로 넘긴다.
#
# 파일마다 pytest를 따로 띄우고, 그 전에 page cache를 비운다. 한 프로세스로 이어 돌리면 page cache가 차서
# 호스트가 실행기를 죽인 적이 있다 (FR-08, 결정 3). 실패해도 끝까지 돈다 (결정 4).
# 출력(파일별 .log, .xml, .jsonl, summary.txt)은 WSL 디스크 ANF_TEST_OUT에 쓴다. 기본 /var/tmp/anf-clone-tests/<UTC 시각>.
# e2e는 .jsonl 옆 <파일>-logs/에 storage agent(agent.log)와 anf-api(anf-api-<n>.log)의 출력을 쓴다 (live_api.log_file).
# /mnt/c(9P)는 e2e를 3~4배 느리게 하고 /tmp는 WSL이 꺼지면 사라진다 (결정 9).
#
# 종료 코드 (§5.3): 0 수집 1개 이상·전부 통과·skip 0·남은 것 없음
#                   1 실패·오류·skip·수집 0개·남은 것·XML 없는 파일(pytest가 죽음)이 있다
#                   2 사전 점검 실패. 테스트를 돌리지 않았다
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 2
export LVM_SUPPRESS_FD_WARNINGS=1 PYTHONDONTWRITEBYTECODE=1
SETUP_HINT="run scripts/setup-wsl-dataplane.sh as root"

precheck_failed() { echo "precheck failed: $*" >&2; exit 2; }
uptime_s() { cut -d' ' -f1 /proc/uptime; }  # 단조 시계. WSL 벽시계는 뒤로 건너뛴다 (ADR §7.3)
listeners() { ss -Hltnp '( sport = :8080 or sport = :8090 )' | awk '{print $4, $6}'; }
lv_names() { lvs --noheadings -o lv_name anf 2>/dev/null | awk '$1 != "aggr0" {print $1}' | LC_ALL=C sort; }
containers() { docker ps -a --format '{{.Names}}' | LC_ALL=C sort; }

# --- 1. 사전 점검 (결정 7) ---
[ "$(uname -s)" = Linux ] || precheck_failed "not Linux: run it in WSL Ubuntu (wsl -d Ubuntu -u root ...)"
[ "$(id -u)" = 0 ] || precheck_failed "not root: run it with wsl -d Ubuntu -u root"
# root의 ~는 /root다. ANF_CLONE_VENV가 없으면 저장소 주인의 ~/.venvs/anf-clone을 쓴다 (CLAUDE.md Setup (WSL))
if [ -z "${ANF_CLONE_VENV:-}" ]; then
  ANF_CLONE_VENV="$(getent passwd "$(stat -c %u "$REPO")" | cut -d: -f6)/.venvs/anf-clone"
fi
PY="$ANF_CLONE_VENV/bin/python"
[ -x "$PY" ] || precheck_failed "no Python at $PY: set ANF_CLONE_VENV or create the venv (CLAUDE.md Setup (WSL))"
"$PY" -c "import pytest" 2>/dev/null || precheck_failed "pytest is missing in $ANF_CLONE_VENV: pip install -e \".[dev]\""
docker info >/dev/null 2>&1 || precheck_failed "Docker Engine is not available: systemctl start docker"
for image in anf-nfs-server anf-nfs-client; do
  docker image inspect "$image" >/dev/null 2>&1 || precheck_failed "image $image is missing: $SETUP_HINT"
done
net="$(docker network inspect anf-vnet -f '{{range .IPAM.Config}}{{.Subnet}} {{.IPRange}}{{end}}' 2>/dev/null)" ||
  precheck_failed "network anf-vnet is missing: $SETUP_HINT"
[ "$net" = "172.30.0.0/24 172.30.0.0/25" ] ||
  precheck_failed "network anf-vnet has '$net', expected '172.30.0.0/24 172.30.0.0/25': $SETUP_HINT"
grep -q '^nfsd ' /proc/modules || precheck_failed "kernel module nfsd is not loaded: $SETUP_HINT"
[ "$(sysctl -n fs.leases-enable)" = 0 ] ||
  precheck_failed "fs.leases-enable is not 0 (NFSv4 delegations are on): $SETUP_HINT"
busy="$(listeners)"
[ -z "$busy" ] || precheck_failed "port 8080 or 8090 is in use, maybe by another session's data plane:" $busy

# --- 2. VG 붙이기 (결정 8) ---
# WSL이 다시 뜨면 loop 장치가 사라져 VG anf가 보이지 않는다. agent가 시작할 때 부르는 같은 함수로 붙인다
if vgs anf >/dev/null 2>&1; then
  echo "VG anf: attached"
else
  echo "VG anf: not attached (WSL restarted?); attaching it the way the storage agent does at start"
  "$PY" -c "import sys; sys.path.insert(0, 'backend')
from storage_agent.flexvol import FlexVolManager
from storage_agent.runner import Runner
FlexVolManager(Runner()).ensure_aggregate()" || precheck_failed "could not attach VG anf"
  vgs anf >/dev/null 2>&1 || precheck_failed "VG anf is still missing after attaching"
fi

OUT="${ANF_TEST_OUT:-/var/tmp/anf-clone-tests/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT" || precheck_failed "cannot create $OUT"

# --- 3. 기준선 (결정 10): 실행 전에 있던 LV와 컨테이너는 남은 것으로 세지 않는다 ---
base_lvs="$(lv_names)"
base_containers="$(containers)"
{ echo "# LVs in VG anf before the run"; echo "$base_lvs"; echo "# containers before the run"; echo "$base_containers"; } \
  > "$OUT/baseline.txt"

# --- 대상: 경로 인자(파일, 폴더, node ID)와 나머지 pytest 옵션을 나누고, dataplane 테스트를 수집한다 ---
paths=()
opts=()
for a in "$@"; do
  if [[ $a != -* && -e ${a%%::*} ]]; then
    paths+=("$(realpath --relative-to="$REPO" "${a%%::*}")${a#"${a%%::*}"}")  # node ID 꼴로 맞춘다
  else
    opts+=("$a")
  fi
done
[ ${#paths[@]} -gt 0 ] || paths=(backend/tests/integration backend/tests/e2e)
PYTEST=("$PY" -m pytest -p no:cacheprovider)

"${PYTEST[@]}" --collect-only -q -m dataplane "${opts[@]}" "${paths[@]}" > "$OUT/collect.log" 2>&1
collect_rc=$?
mapfile -t ids < <(grep -E '^[^ ]+\.py::' "$OUT/collect.log")
mapfile -t files < <(printf '%s\n' "${ids[@]}" | sed 's/::.*//' | awk 'NF && !seen[$0]++')
if [ "$collect_rc" != 0 ] || [ ${#ids[@]} = 0 ]; then
  tail -20 "$OUT/collect.log"
  echo "collection failed or collected nothing (pytest exit $collect_rc): $OUT/collect.log"
  exit 1
fi
API_URL="${ANF_E2E_API_URL-http://127.0.0.1:8080}"  # 일부러 비우면 e2e가 skip하고, 아래 판정이 실패로 센다
echo "collected ${#ids[@]} dataplane tests in ${#files[@]} files; venv $ANF_CLONE_VENV; output $OUT"

# --- 4. 파일마다 pytest (결정 3·4) ---
xmls=()
bad_exit=()
run_start=$(uptime_s)
i=0
for f in "${files[@]}"; do
  i=$((i + 1))
  stem="$(basename "$f" .py)"
  targets=()
  for p in "${paths[@]}"; do [ "${p%%::*}" = "$f" ] && targets+=("$p"); done
  [ ${#targets[@]} -gt 0 ] || targets=("$f")  # 폴더로 고른 파일은 파일 전체
  sync
  echo 3 > /proc/sys/vm/drop_caches
  echo "[$i/${#files[@]}] $f"
  t0=$(uptime_s)
  ANF_E2E_API_URL="$API_URL" ANF_E2E_LOG="$OUT/$stem.jsonl" \
    "${PYTEST[@]}" -v -m dataplane --junitxml="$OUT/$stem.xml" "${opts[@]}" "${targets[@]}" 2>&1 | tee "$OUT/$stem.log"
  rc=${PIPESTATUS[0]}
  secs=$(awk -v a="$t0" -v b="$(uptime_s)" 'BEGIN {printf "%.0f", b - a}')
  echo "[$i/${#files[@]}] $f: pytest exit $rc, $secs s"
  printf '%s\t%s\t%s\n' "$f" "$rc" "$secs" >> "$OUT/files.tsv"
  xmls+=("$OUT/$stem.xml")
  [ "$rc" = 0 ] || bad_exit+=("$f (pytest exit $rc)")
done
total_secs=$(awk -v a="$run_start" -v b="$(uptime_s)" 'BEGIN {printf "%.0f", b - a}')

# --- 5. 남은 것 (결정 10): 지우지 않고 보여 준다. 정리 결함의 단서다 ---
left=()
while read -r lv; do
  [ -n "$lv" ] && left+=("LV anf/$lv")
done < <(LC_ALL=C comm -13 <(echo "$base_lvs") <(lv_names))
while read -r c; do
  [ -n "$c" ] || continue
  # 실행 전에 있던 볼륨의 인스턴스는 agent와 통합 테스트의 시작 복구(recover)가 다시 띄운 것이다
  [[ $c == anf-nfs-* ]] && grep -qx "vol_${c#anf-nfs-}" <<< "$base_lvs" && continue
  left+=("container $c")
done < <(LC_ALL=C comm -13 <(echo "$base_containers") <(containers))
while read -r l; do
  [ -n "$l" ] && left+=("listener $l")
done < <(listeners)

# --- 6. 판정과 요약 ---
{
  "$PY" backend/tests/junit_gate.py "${xmls[@]}"
  gate_rc=$?
  echo "time: $total_secs s for ${#files[@]} files (monotonic clock)"
  for b in "${bad_exit[@]}"; do echo "nonzero exit: $b"; done
  for l in "${left[@]}"; do echo "left behind (not removed): $l"; done
  rc=0
  [ "$gate_rc" = 0 ] && [ ${#bad_exit[@]} = 0 ] && [ ${#left[@]} = 0 ] || rc=1
  echo "output: $OUT"
  echo "exit $rc"
  exit "$rc"
} 2>&1 | tee "$OUT/summary.txt"
exit "${PIPESTATUS[0]}"
