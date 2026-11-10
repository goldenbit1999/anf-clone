"""compose 스택 실환경 시험 (FR-13, 설계 _workspace/containers/02_main_design.md §3·§5, 스파이크 S9).

README의 명령 하나로 스택을 띄우고(일반 사용자, sudo 없음), scripts/demo.py로 PRD §5 대본을 돌리고, 스택을 내렸다
올리고 agent를 죽였다 살리는 동안 클라이언트 I/O와 리소스가 그대로인지 본다. 끝에 스택을 내리고 남은 것이 없게 한다.

- AC-01 명령 하나로 네 서비스가 healthy가 된다(걸린 시간 기록). 모든 포트가 127.0.0.1에만 열린다
- AC-03 데모 1~7단계가 0으로 끝나고 단계마다 근거 줄이 있고 3분 안이며 스스로 치운다. AC-07 그동안의 메모리
- AC-02 같은 명령을 다시 실행, down → 클라이언트 I/O 계속 → up → agent가 복구하고 API가 같은 리소스를 보인다
- AC-06 쓰는 중에 agent를 docker kill → 쓰기 오류 0, 다시 뜬 뒤 볼륨·스냅샷·한도 그대로, 되돌리기·삭제 성공
- AC-08 일부: 끝나면 compose 컨테이너·볼륨, 볼륨 인스턴스, 클라이언트, 포트가 남지 않는다

compose 프로젝트 이름을 따로 둔다(anf-clone-e2e). 사용자 스택(anf-clone)의 이름 있는 볼륨(anf-api 상태)을 `down -v`가
지우지 않게 한다. 이미지(anf-clone-agent 등)는 같은 것을 쓴다. 이 파일은 이미지가 있으면 약 5분 걸린다(CI rest 조각).

실행 (WSL, root, 스택을 내린 뒤):
    MSYS_NO_PATHCONV=1 wsl -d Ubuntu -u root -e bash /mnt/c/<repo>/scripts/run-dataplane-tests.sh \
        backend/tests/e2e/test_compose_stack_live.py
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import live_api
from live_api import call, poll
from dataplane_live import SKIP_UNLESS_ROOT, e2e_user, note, out, sh
from throughput_live import matches, tc_state

sys.path.insert(0, str(live_api.REPO_ROOT / "scripts"))
import demo  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]

REPO = live_api.REPO_ROOT
PROJECT = "anf-clone-e2e"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", "deploy/compose.yaml"]
UP = [*COMPOSE, "up", "-d", "--build", "--wait"]  # README의 명령 + 프로젝트 이름
SERVICES = ("storage-agent", "anf-api", "prometheus", "dashboard")
PORTS = (8080, 8081, 8090, 9090)
AGENT = f"{PROJECT}-storage-agent-1"
MEMORY_LIMIT_MIB = 7 * 1024  # NFR-06: 데모 전체가 WSL 메모리 약 7 GB 안
_state: dict = {}  # 시험 사이에 넘기는 값(시작 때의 LV, 3번 시험이 본 리소스)


# --- 도우미 ---


def as_user(*argv: str, timeout: float = 900) -> tuple[subprocess.CompletedProcess, float]:
    """docker 그룹의 일반 사용자로 저장소 루트에서 돌린다(sudo 없이 쓰는 경로). 반환: (결과, 걸린 초)."""
    u = e2e_user()
    env = {"PATH": os.environ["PATH"], "HOME": u.pw_dir, "USER": u.pw_name, "LOGNAME": u.pw_name,
           "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = ["setpriv", f"--reuid={u.pw_uid}", f"--regid={u.pw_gid}", "--init-groups", "--", *argv]
    start = uptime()
    r = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout)
    return r, round(uptime() - start, 2)


def uptime() -> float:
    """단조 시계(초). 클라이언트 컨테이너도 같은 커널의 값을 읽는다. WSL 벽시계는 뒤로 건너뛴다 (ADR §7.3)."""
    return float(Path("/proc/uptime").read_text().split()[0])


def listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def local_addresses(port: int) -> list[str]:
    return [line.split()[3] for line in sh("ss", "-Hltn", f"( sport = :{port} )").stdout.splitlines()]


def service_states() -> dict:
    """compose 서비스 → (State, Health, ExitCode)."""
    text = sh(*COMPOSE, "ps", "-a", "--format", "json").stdout.strip()
    rows = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line]
    return {r["Service"]: (r["State"], r.get("Health", ""), r.get("ExitCode")) for r in rows}


def instances() -> dict:
    """볼륨 인스턴스 컨테이너 → (ID, 시작 시각). compose 밖에서 agent가 띄운다."""
    names = sh("docker", "ps", "-a", "--filter", "name=^anf-nfs-", "--format", "{{.Names}}").stdout.split()
    result = {}
    for name in names:
        r = sh("docker", "inspect", "-f", "{{.Id}} {{.State.Status}} {{.State.StartedAt}}", name)
        result[name] = tuple(r.stdout.split())
    return result


def lv_names() -> set[str]:
    r = sh("lvs", "--noheadings", "-o", "lv_name", "anf")
    return {n for n in r.stdout.split() if n != "aggr0"}


def arm_view() -> dict:
    """데모 리소스를 API로 본 것: 볼륨마다 (상태, 마운트 IP, 한도, fileSystemId)와 vol-v3의 스냅샷 이름."""
    r = call("GET", f"{demo.arm_path(demo.POOL)}/volumes?{demo.V}")
    assert r.status == 200, r.raw
    view = {}
    for v in r.json()["value"]:
        p = v["properties"]
        view[v["name"].rsplit("/", 1)[-1]] = (p["provisioningState"], p["mountTargets"][0]["ipAddress"],
                                               p.get("throughputMibps"), p["fileSystemId"])
    s = call("GET", f"{demo.arm_path(demo.POOL, demo.V3[0])}/snapshots?{demo.V}")
    assert s.status == 200, s.raw
    view["snapshots"] = sorted(x["name"].rsplit("/", 1)[-1] for x in s.json()["value"])
    return view


class Writer:
    """클라이언트 컨테이너 안에서 1 MiB 직접 쓰기를 멈출 때까지 되풀이한다. 줄마다 (단조 시각, dd 종료 코드)."""

    def __init__(self, client: str, path: str, tag: str):
        self.client, self.stop_file = client, f"/tmp/stop-{tag}"
        script = (f"rm -f {self.stop_file}; i=0; while [ ! -e {self.stop_file} ]; do "
                  f"dd if=/dev/zero of={path} bs=1M count=1 seek=$((i % 32)) conv=notrunc oflag=direct status=none; "
                  'rc=$?; read up rest < /proc/uptime; echo "$up $rc"; i=$((i + 1)); done')
        self.proc = subprocess.Popen(["docker", "exec", client, "sh", "-c", script],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def stop(self, timeout: float = 120) -> list[tuple[float, int]]:
        sh("docker", "exec", self.client, "touch", self.stop_file)
        stdout, stderr = self.proc.communicate(timeout=timeout)
        assert self.proc.returncode == 0, stderr
        return [(float(a), int(b)) for a, b in (line.split() for line in stdout.splitlines())]


def summarize(samples: list[tuple[float, int]], start: float, end: float) -> dict:
    times = [t for t, _ in samples]
    gaps = [b - a for a, b in zip(times, times[1:])]
    return {"writes": len(samples), "errors": sum(1 for _, rc in samples if rc != 0),
            "max_gap_s": round(max(gaps), 2) if gaps else None,
            "writes_in_window": sum(1 for t in times if start <= t <= end), "window_s": round(end - start, 2)}


class Memory(threading.Thread):
    """WSL 메모리(free -m의 used·available)와 컨테이너별 메모리(docker stats)를 3초마다 적는다 (AC-07)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self._done = [], threading.Event()  # Thread._stop과 겹치지 않는 이름

    def run(self) -> None:
        while not self._done.is_set():
            mem = next(line.split() for line in sh("free", "-m").stdout.splitlines() if line.startswith("Mem:"))
            stats = sh("docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}").stdout.splitlines()
            self.samples.append({"t": uptime(), "total": int(mem[1]), "used": int(mem[2]),
                                 "available": int(mem[6]), "docker_stats": stats})
            self._done.wait(3)

    def stop(self) -> dict:
        self._done.set()
        self.join(30)
        peak = max(self.samples, key=lambda s: s["used"])
        return {"samples": len(self.samples), "peak": peak}


def demo_run(*args: str) -> tuple[subprocess.CompletedProcess, float]:
    return as_user("python3", "scripts/demo.py", *args, timeout=600)


def cleanup() -> None:
    """실패해도 데이터 플레인을 비운다: 데모 리소스는 API로(스택이 내려가 있으면 띄워서), 그다음 스택과 클라이언트."""
    if (lv_names() - _state.get("base_lvs", set())) and not listening(8080):
        as_user(*UP)
    if listening(8080):
        r, _ = demo_run("--clean")
        note("cleanup-demo", rc=r.returncode, stdout=r.stdout[-2000:], stderr=r.stderr[-2000:])
    r, _ = as_user(*COMPOSE, "down", "-v", timeout=300)
    note("cleanup-down", rc=r.returncode, stderr=r.stderr[-2000:])
    for c in demo.CLIENTS:
        sh("docker", "rm", "-f", c)


@pytest.fixture(scope="module", autouse=True)
def stack():
    busy = [p for p in PORTS if listening(p)]
    assert not busy, f"ports {busy} are in use: stop the compose stack (docker compose -f deploy/compose.yaml down)"
    _state["base_lvs"] = lv_names()
    _state["base_instances"] = instances()
    yield
    cleanup()


# --- 시험 (파일 순서대로 돈다) ---


def test_one_command_starts_the_stack_as_a_regular_user():
    """AC-01: sudo 없이 docker 그룹 사용자로 명령 하나. --wait가 healthy까지 기다린다."""
    r, secs = as_user(*UP)
    note("up", user=e2e_user().pw_name, rc=r.returncode, seconds=secs, stderr=r.stderr[-3000:])
    assert r.returncode == 0, r.stderr[-3000:]
    states = service_states()
    note("services", states=states, ports={p: local_addresses(p) for p in PORTS})
    assert {s: states[s][:2] for s in SERVICES} == {s: ("running", "healthy") for s in SERVICES}
    assert states["init"][0] == "exited" and states["init"][2] == 0
    for p in PORTS:
        assert local_addresses(p) == [f"127.0.0.1:{p}"], p


def test_demo_replays_steps_1_to_7_cleans_up_and_fits_in_memory():
    """AC-03(1~7단계, 근거 줄, 3분 안, 스스로 치움), AC-07(그동안의 메모리)."""
    mem = Memory()
    mem.start()
    r, secs = demo_run()
    memory = mem.stop()
    note("demo", rc=r.returncode, seconds=secs, stdout=r.stdout, stderr=r.stderr)
    note("memory", limit_mib=MEMORY_LIMIT_MIB, **memory)
    assert r.returncode == 0, r.stderr
    for step in "1234567":
        assert f"\n[{step}] " in "\n" + r.stdout, step
    assert "[done] steps 1-7 passed" in r.stdout
    assert secs < 180
    # 근거: 클라이언트가 읽은 내용, 잰 MiB/s, Prometheus 값
    assert "/.snapshot/snap1/hello.txt still reads" in r.stdout
    assert re.search(r"fio write on vol-v41 with the limit 5 MiB/s: [\d., ]+ MiB/s \(median ", r.stdout)
    assert "write rate peaked at" in r.stdout
    # 스스로 치웠다
    accounts = call("GET", f"/subscriptions/{demo.SUB}/providers/Microsoft.NetApp/netAppAccounts?{demo.V}")
    assert accounts.json()["value"] == []
    assert instances() == _state["base_instances"]
    assert lv_names() == _state["base_lvs"]
    assert not [c for c in demo.CLIENTS if sh("docker", "inspect", c).returncode == 0]
    assert memory["peak"]["used"] < MEMORY_LIMIT_MIB


def test_rerun_and_down_up_keep_volumes_and_client_io():
    """AC-02: 같은 명령 다시 → down(인스턴스는 남아 I/O 계속) → up(agent 복구, API 같은 리소스)."""
    r, secs = demo_run("--keep")
    note("demo-keep", rc=r.returncode, seconds=secs, stdout=r.stdout[-1500:], stderr=r.stderr)
    assert r.returncode == 0, r.stderr
    before, inst = arm_view(), instances()
    note("before", view=before, instances=inst)
    assert len(inst) == len(_state["base_instances"]) + 3
    _state["view"] = before
    writer = Writer(demo.CLIENTS[0], "/v41/continuity", "a")
    time.sleep(3)

    rerun, rerun_s = as_user(*UP)
    recreated = sorted(set(re.findall(r"Container (\S+)\s+Recreate\b", rerun.stderr)))
    note("rerun", rc=rerun.returncode, seconds=rerun_s, recreated=recreated, stderr=rerun.stderr[-2000:])
    assert rerun.returncode == 0, rerun.stderr
    assert instances() == inst

    down, down_s = as_user(*COMPOSE, "down")
    t_down = uptime()
    states_down = {p: listening(p) for p in PORTS}
    note("down", rc=down.returncode, seconds=down_s, listening=states_down, instances=instances())
    assert down.returncode == 0, down.stderr
    assert not any(states_down.values())
    assert instances() == inst  # compose 밖이라 남는다 (결정 4)
    time.sleep(10)
    t_up = uptime()

    up, up_s = as_user(*UP)
    after = arm_view()
    samples = writer.stop()
    s = summarize(samples, t_down, t_up)
    note("up-again", rc=up.returncode, seconds=up_s, view=after, instances=instances(), writes=s)
    assert up.returncode == 0, up.stderr
    assert after == before
    assert instances() == inst
    assert s["errors"] == 0 and s["writes_in_window"] > 0


def test_agent_kill_during_writes_keeps_volumes_and_revert_and_delete_work():
    """AC-06: 쓰는 중에 agent kill → 오류 0, 다시 뜬 뒤 볼륨·스냅샷·한도 그대로, 되돌리기·삭제 성공(S9 P3 회귀)."""
    before = _state.get("view")
    assert before, "the previous test did not leave the demo resources (demo.py --keep)"
    c = demo.CLIENTS[0]
    writers = {"v3": Writer(c, "/v3/during-kill", "b"), "v41": Writer(c, "/v41/during-kill", "c")}
    time.sleep(3)
    k = sh("docker", "kill", AGENT)
    t_kill = uptime()
    assert k.returncode == 0, out(k)
    time.sleep(5)
    assert not listening(8090)
    up, up_s = as_user(*UP)
    t_up = uptime()
    writes = {name: summarize(w.stop(), t_kill, t_up) for name, w in writers.items()}
    view = arm_view()
    vols = {n: v for n, v in view.items() if n != "snapshots"}
    limits = {n: tc_state(fsid) for n, (_, _, _, fsid) in vols.items()}  # 인스턴스 netns의 HTB와 필터
    note("after-kill", rc=up.returncode, seconds=up_s, writes=writes, view=view, tc=limits)
    assert up.returncode == 0, up.stderr
    assert all(w["errors"] == 0 and w["writes_in_window"] > 0 for w in writes.values()), writes
    assert view == before
    for n, (_, _, mibps, _) in vols.items():
        assert matches(limits[n], mibps), (n, limits[n])

    # 되돌리기: 재시작 뒤에도 성공하고, 클라이언트가 스냅샷 시점의 파일을 본다
    snap_id = call("GET", f"{demo.arm_path(demo.POOL, demo.V3[0], demo.SNAP)}?{demo.V}").json()["id"]
    r = call("POST", f"{demo.arm_path(demo.POOL, demo.V3[0])}/revert?{demo.V}", {"snapshotId": snap_id})
    assert r.status == 202, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], 120)
    listing = sh("docker", "exec", c, "ls", "/v3").stdout.split()
    text = sh("docker", "exec", c, "cat", "/v3/hello.txt").stdout.strip()
    note("revert-after-restart", final=final, seen=seen, ls=listing, hello=text)
    assert final["status"] == "Succeeded", final
    assert text == demo.TEXT and "during-kill" not in listing

    # 삭제: 데모의 정리(볼륨 셋, 풀, 계정)가 모두 성공한다
    clean, clean_s = demo_run("--clean")
    note("delete-after-restart", rc=clean.returncode, seconds=clean_s, stdout=clean.stdout, stderr=clean.stderr)
    assert clean.returncode == 0, clean.stderr
    assert "vol-restored, vol-v41, vol-v3, demo-pool, demo-acct" in clean.stdout
    assert instances() == _state["base_instances"]
    assert lv_names() == _state["base_lvs"]


def test_down_leaves_nothing_behind():
    """AC-08 일부: 스택을 내리면 compose 컨테이너·볼륨, 인스턴스, 클라이언트, 포트가 남지 않는다."""
    # down -v는 anf-api 상태도 지운다. 앞 시험이 실패해 리소스가 남았으면 먼저 API로 지운다(상태 없는 LV가 남지 않게)
    clean, _ = demo_run("--clean")
    assert clean.returncode == 0, clean.stderr
    r, secs = as_user(*COMPOSE, "down", "-v")
    project = f"label=com.docker.compose.project={PROJECT}"
    left = {
        "containers": sh("docker", "ps", "-a", "--filter", project, "--format", "{{.Names}}").stdout.split(),
        "volumes": sh("docker", "volume", "ls", "--filter", project, "--format", "{{.Name}}").stdout.split(),
        "clients": [c for c in demo.CLIENTS if sh("docker", "inspect", c).returncode == 0],
        "listening": [p for p in PORTS if listening(p)],
    }
    note("down-v", rc=r.returncode, seconds=secs, left=left, instances=instances(), lvs=sorted(lv_names()))
    assert r.returncode == 0, r.stderr
    assert left == {"containers": [], "volumes": [], "clients": [], "listening": []}
    assert instances() == _state["base_instances"]
    assert lv_names() == _state["base_lvs"]
