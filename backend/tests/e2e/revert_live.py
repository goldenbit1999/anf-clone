"""되돌리기 실환경 검증 도구 (되돌리기 설계 §8). test_snapshot_revert_*_live.py가 쓰는 도우미 모듈이다.

볼륨·스냅샷 e2e 도우미(dataplane_live.py, snapshot_live.py)를 그대로 쓰고, 여기에는 revert 경로, 트리 체크섬,
AC-02의 기록(S1 → S2 → S3) 만들기, 인스턴스 netns의 차단 규칙 관찰, 클라이언트 안에서 돌리는 탐침·쓰기·fd 스크립트만 더한다.
"""

import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path

from live_api import V, call, poll
from dataplane_live import ACCT, NS, POLL, POOL, instance_name, lv_name, lvs_volumes, out, sh, vol_path
from snapshot_live import create_snapshot, snap_list_url

# --- ARM revert ---


def listing(vol: str) -> dict:
    """ARM 스냅샷 목록: 이름 → 본문."""
    r = call("GET", snap_list_url(vol))
    assert r.status == 200, r.raw
    return {s["name"].split("/")[-1]: s for s in r.json()["value"]}


def identity(s: dict) -> tuple:
    """되돌린 뒤에도 그대로여야 하는 스냅샷 속성."""
    return s["id"], s["properties"]["snapshotId"], s["properties"]["created"], s["properties"]["provisioningState"]


def op_id(azure_async_operation: str) -> str:
    return azure_async_operation.split("/operationResults/")[1].split("?")[0]


def revert_url(vol: str, acct=ACCT, pool=POOL) -> str:
    return f"{vol_path(acct, pool, vol)}/revert?{V}"


def post_revert(vol: str, snapshot_id, acct=ACCT, pool=POOL):
    return call("POST", revert_url(vol, acct, pool), {"snapshotId": snapshot_id})


def revert(vol: str, snapshot_id: str, timeout=POLL):
    """POST revert → 202 → 종결까지 폴링. 반환: (POST 응답, 종결 본문, 관찰한 status 순서)."""
    r = post_revert(vol, snapshot_id)
    assert r.status == 202, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], timeout)
    return r, final, seen


def fast_poll(url: str, timeout=POLL, interval=0.1) -> tuple[float, dict, list[str]]:
    """작업 상태를 0.1초마다 본다 (AC-04: 끝난 뒤 1초 안의 관찰). 반환: (Succeeded를 본 time.time(), 본문, 순서)."""
    deadline = time.monotonic() + timeout
    seen = []
    while True:
        body = call("GET", url).json()
        if not seen or seen[-1] != body["status"]:
            seen.append(body["status"])
        if body["status"] in ("Succeeded", "Failed", "Canceled"):
            return time.time(), body, seen
        assert time.monotonic() < deadline, seen
        time.sleep(interval)


# --- 트리 체크섬 (설계 §8 공통 조건: 파일별 sha256, `.snapshot` 제외) ---


def tree(root: Path) -> dict:
    """호스트에서 root 아래의 파일(sha256)과 디렉터리("dir"). 최상위 `.snapshot`은 뺀다."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if rel == Path("."):
            dirnames[:] = [d for d in dirnames if d != ".snapshot"]
        for d in dirnames:
            found[(rel / d).as_posix()] = "dir"
        for f in filenames:
            found[(rel / f).as_posix()] = hashlib.sha256((Path(dirpath) / f).read_bytes()).hexdigest()
    return found


def client_tree(c, path: str) -> dict:
    """클라이언트에서 본 같은 목록 (tree와 같은 모양)."""
    r = c.run(f"cd {path} && find . -type d | grep -v -e '^\\.$' -e '^\\./\\.snapshot' | sed 's/^/dir /'; "
              "find . -type f | grep -v '^\\./\\.snapshot' | xargs -r sha256sum")
    assert r.returncode == 0, out(r)
    found = {}
    for line in r.stdout.splitlines():
        if line.startswith("dir "):
            found[line[6:]] = "dir"
        else:
            digest, name = line.split(None, 1)
            found[name[2:]] = digest
    return found


# --- AC-02의 기록: 파일·디렉터리 → S1 → 바꿈 → S2 → 지우기·덮어쓰기·새로 만들기 → S3 → 또 바꿈 ---

STEPS = {
    "S1": "mkdir -p /m/d1/sub && echo a1 > /m/A && echo k1 > /m/K && echo x1 > /m/d1/X && echo y1 > /m/d1/sub/Y "
          "&& dd if=/dev/urandom of=/m/big bs=1M count=8 2>/dev/null",
    "S2": "echo a2 > /m/A && echo k2 >> /m/K && mkdir /m/d2 && echo z2 > /m/d2/Z && rm /m/d1/X",
    # 지우기(A), 덮어쓰기(K: 같은 inode에 자르고 쓰기, big: 같은 자리에 덮어쓰기), 새 파일(N)·디렉터리(d3)
    "S3": "rm /m/A && echo over > /m/K && dd if=/dev/urandom of=/m/big bs=1M count=8 conv=notrunc 2>/dev/null "
          "&& echo n3 > /m/N && mkdir /m/d3 && echo q3 > /m/d3/Q",
}
AFTER_S3 = "echo n4 > /m/N && echo m4 > /m/M && rm -r /m/d2 && echo y4 > /m/d1/sub/Y"


def build_history(c, vol: str) -> dict:
    """클라이언트 c(/m에 마운트)로 기록을 만든다. 반환: 이름 → 스냅샷 GET 본문."""
    snaps = {}
    for name, script in STEPS.items():
        w = c.run(script + " && sync")
        assert w.returncode == 0, out(w)
        snaps[name], _ = create_snapshot(vol, name)
    w = c.run(AFTER_S3 + " && sync && cat /m/K /m/N")  # 클라이언트 캐시에도 올린다
    assert w.returncode == 0, out(w)
    return snaps


def snapshot_trees(token_: str, names) -> dict:
    return {n: tree(NS / token_ / ".snapshot" / n) for n in names}


# --- 데이터 플레인 관찰 (root) ---


def instance_pid(fsid: str) -> str | None:
    r = sh("docker", "inspect", "-f", "{{.State.Pid}}", instance_name(fsid))
    pid = r.stdout.strip()
    return pid if r.returncode == 0 and pid not in ("", "0") else None


def drop_rule(fsid: str, pid: str | None = None) -> bool | None:
    """인스턴스 netns에 되돌리기 창의 입력 차단 규칙이 있는가. 인스턴스가 돌지 않으면 None."""
    pid = pid or instance_pid(fsid)
    if pid is None:
        return None
    return sh("nsenter", "-t", pid, "-n", "iptables", "-C", "INPUT", "-i", "eth0", "-j", "DROP").returncode == 0


def volume_lvs(fsid: str) -> dict:
    """그 볼륨의 볼륨 LV(옛 LV와 되돌리는 동안의 `_new`) → 태그 목록."""
    prefix = lv_name(fsid)
    return {n: sorted(x["tags"].split(",")) for n, x in lvs_volumes().items() if n.startswith(prefix)}


def rv_tags(fsid: str) -> list[str]:
    return sorted(t for tags in volume_lvs(fsid).values() for t in tags if t.startswith("anf_rv_"))


def mount_targets() -> set[str]:
    with open("/proc/self/mountinfo") as f:
        return {line.split()[4] for line in f}


class RuleWatch(threading.Thread):
    """차단 규칙이 생기고 사라진 시각(time.time())을 0.02초 간격으로 기록한다. 창의 서버 쪽 길이다."""

    def __init__(self, fsid: str):
        super().__init__(daemon=True)
        self.pid = instance_pid(fsid)
        self.events: list[tuple[float, bool]] = []
        self._done = threading.Event()

    def run(self) -> None:
        last = None
        while not self._done.is_set():
            present = drop_rule("", self.pid)
            if present != last:
                self.events.append((time.time(), present))
                last = present
            self._done.wait(0.02)

    def stop(self) -> list[tuple[float, float]]:
        """창 목록 [(열린 시각, 닫힌 시각)]."""
        self._done.set()
        self.join(10)
        windows, opened = [], None
        for t, present in self.events:
            if present:
                opened = t
            elif opened is not None:
                windows.append((opened, t))
                opened = None
        return windows


# --- 클라이언트 안의 스크립트 ---

# 0.2초마다 기존 파일을 읽는다. 줄: 시작 끝 결과 내용 (설계 AC-04)
PROBE = r"""
: > /tmp/probe.log
while [ ! -e /tmp/stop ]; do
  s=$(date +%s.%N)
  if v=$(cat "$1" 2>/tmp/probe.err); then r=ok; else r="fail:$(tr ' ' _ < /tmp/probe.err)"; fi
  e=$(date +%s.%N)
  echo "$s $e $r $v" >> /tmp/probe.log
  sleep 0.2
done
"""

# 되돌리는 동안 쓰기를 계속한다: 경로로 열어 한 줄 덧붙이고 닫는다 (닫을 때 서버로 간다). 줄: 번호 시작 끝 결과
WRITER = r"""
: > /tmp/w.log
i=0
while [ ! -e /tmp/stop ]; do
  i=$((i+1)); s=$(date +%s.%N)
  if echo "w$i" >> "$1" 2>/tmp/w.err; then r=ok; else r="fail:$(tr ' ' _ < /tmp/w.err)"; fi
  e=$(date +%s.%N)
  echo "$i $s $e $r" >> /tmp/w.log
  sleep 0.1
done
"""

# 되돌리기 전에 연 fd와 cwd. /tmp/go가 생기면 읽고 결과를 남긴다 (설계 AC-04)
HOLDER = r"""
exec 3</m/B
exec 4</m/D
( cd /m/olddir || exit 9; while [ ! -e /tmp/go ]; do sleep 0.05; done
  { ls; echo "rc=$?"; cat E; echo "rc=$?"; } > /tmp/cwd_old.out 2>&1 ) &
( cd /m/n || exit 9; while [ ! -e /tmp/go ]; do sleep 0.05; done
  { ls; echo "rc=$?"; cat F; echo "rc=$?"; } > /tmp/cwd_new.out 2>&1 ) &
touch /tmp/held
while [ ! -e /tmp/go ]; do sleep 0.05; done
{ cat <&3; echo "rc=$?"; } > /tmp/fd_old.out 2>&1
{ cat <&4; echo "rc=$?"; } > /tmp/fd_new.out 2>&1
wait
touch /tmp/done
"""


def put_script(c, path: str, text: str) -> None:
    r = subprocess.run(["docker", "exec", "-i", c.name, "sh", "-c", f"cat > {path}"], input=text, text=True,
                       capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr


def start_script(c, path: str, text: str, *args: str) -> None:
    put_script(c, path, text)
    r = sh("docker", "exec", "-d", c.name, "sh", path, *args)
    assert r.returncode == 0, out(r)


def wait_file(c, path: str, timeout=60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if c.run(f"test -e {path}").returncode == 0:
            return True
        time.sleep(0.2)
    return False


def probe_stats(log: str) -> dict:
    """탐침 기록: 횟수, 실패, 가장 긴 한 번(초), 연속 시작 사이의 가장 긴 간격(초), 내용 종류."""
    rows = [line.split(" ", 3) for line in log.splitlines() if line.strip()]
    durations = [float(e) - float(s) for s, e, *_ in rows]
    starts = [float(s) for s, *_ in rows]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    longest = max(range(len(durations)), key=durations.__getitem__) if durations else None
    return {"reads": len(rows), "failures": [r for r in rows if not r[2].startswith("ok")],
            "longest_read_s": round(durations[longest], 3) if durations else None,
            "longest_read_started": float(rows[longest][0]) if durations else None,
            "longest_gap_s": round(max(gaps), 3) if gaps else None,
            "contents": sorted({r[3] if len(r) > 3 else "" for r in rows})}


def writer_stats(log: str) -> dict:
    rows = [line.split() for line in log.splitlines() if line.strip()]
    durations = [float(e) - float(s) for _, s, e, _ in rows]
    return {"writes": len(rows), "failures": [r for r in rows if not r[3].startswith("ok")],
            "longest_write_s": round(max(durations), 3) if durations else None}
