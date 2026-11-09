"""처리량 한도 실환경 검증 도구 (처리량 설계 §8). test_throughput_limit_*_live.py가 쓰는 도우미 모듈이다.

볼륨·되돌리기 e2e 도우미(dataplane_live.py, revert_live.py)를 그대로 쓰고, 여기에는 한도 값을 다루는 ARM 호출,
인스턴스 netns의 tc 관찰(HTB rate·카운터, redirect 필터), 호스트 IFB 목록, 클라이언트 컨테이너 안의 fio 측정만 더한다.

측정 (결정 15·19): fio 직접 I/O, bs 1 MiB, iodepth 16, libaio, 게스트 단조 시계. 크기는 한도 × 15 s다.
첫 회는 버리고(파일을 늘리는 쓰기가 섞인다, S7 Q2) 그 뒤 ANF_E2E_FIO_RUNS회(기본 5)의 중앙값을 본다.
바뀐 한도와 멈춤은 netns ifb0의 송신 바이트(HTB를 지난 양방향 바이트)를 0.5초마다 읽어 1초 창으로 본다 (Sampler).
"""

import json
import os
import re
import statistics
import threading
import time
from pathlib import Path

from live_api import call, poll, pool_url
from dataplane_live import ACCT, GIB, POLL, out, sh, vol_body, vol_url
from revert_live import instance_pid
from storage_agent.nfs_instance import htb_rate_bits

MIB = 1 << 20
LOW, HIGH = 0.90, 1.01  # 허용 오차: 데이터 처리량이 한도의 90~101% (결정 15)
RUNS = int(os.environ.get("ANF_E2E_FIO_RUNS", "5"))
SECONDS = 15  # 한 회의 길이: 한도 × 15 s 크기
FIO = "fio --direct=1 --ioengine=libaio --clocksource=clock_gettime --output-format=json"


# --- ARM ---


def make(name: str, tok: str, pool: str, size: int = GIB, protocols=None, **extra) -> tuple:
    """PUT → 201 → Succeeded. 반환: (PUT 응답, 종결 본문, 관찰한 status 순서, GET 본문)."""
    r = call("PUT", vol_url(ACCT, pool, name), vol_body(tok, size, protocols, **extra))
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    assert final["status"] == "Succeeded", (final, seen)
    return r, final, seen, get_volume(name, pool)


def get_volume(name: str, pool: str) -> dict:
    g = call("GET", vol_url(ACCT, pool, name))
    assert g.status == 200, g.raw
    return g.json()


def pool_props(pool: str) -> dict:
    g = call("GET", pool_url(ACCT, pool))
    assert g.status == 200, g.raw
    return g.json()["properties"]


def patch_volume(name: str, pool: str, props: dict):
    return call("PATCH", vol_url(ACCT, pool, name), {"properties": props})


def limits(name: str, pool: str) -> dict:
    p = get_volume(name, pool)["properties"]
    return {"throughputMibps": p.get("throughputMibps"), "actualThroughputMibps": p["actualThroughputMibps"],
            "provisioningState": p["provisioningState"]}


# --- 인스턴스 netns의 tc ---


def in_netns(fsid: str, *argv):
    pid = instance_pid(fsid)
    assert pid is not None, f"instance of {fsid} is not running"
    return sh("nsenter", "-t", pid, "-n", *argv)


def htb_rate(fsid: str) -> int | None:
    """netns ifb0의 HTB 클래스 1:1 rate (bit/s). tc는 `87710Kbit`처럼 단위를 붙여 보인다. 없으면 None."""
    text = in_netns(fsid, "tc", "class", "show", "dev", "ifb0").stdout
    match = re.search(r"class htb 1:1 .*?rate (\d+)([KMG]?)bit", text)
    if match is None:
        return None
    return int(match[1]) * {"": 1, "K": 10**3, "M": 10**6, "G": 10**9}[match[2]]


def htb_sent(fsid: str) -> int:
    """HTB 클래스 1:1이 내보낸 바이트(양방향, L2)."""
    text = in_netns(fsid, "tc", "-s", "class", "show", "dev", "ifb0").stdout
    match = re.search(r"class htb 1:1 .*?Sent (\d+) bytes", text, re.S)
    assert match is not None, text
    return int(match[1])


def redirect_filters(fsid: str) -> dict:
    """eth0의 방향별 matchall redirect 필터 수 (`tc -j filter`는 필터마다 머리 줄과 본문 줄을 낸다)."""
    counts = {}
    for direction in ("ingress", "egress"):
        rows = json.loads(in_netns(fsid, "tc", "-j", "filter", "show", "dev", "eth0", direction).stdout or "[]")
        counts[direction] = sum(1 for r in rows if r.get("kind") == "matchall" and "options" in r)
    return counts


def tc_state(fsid: str) -> dict:
    """판정과 기록에 쓰는 netns tc 요약. 한도가 없으면 rate가 None이고 필터가 0이다."""
    return {"rate_bits": htb_rate(fsid), "filters": redirect_filters(fsid),
            "ifb0": in_netns(fsid, "ip", "link", "show", "ifb0").returncode == 0}


def matches(st: dict, mibps: float) -> bool:
    """tc_state가 그 한도의 HTB 클래스와 방향마다 필터 하나인가. tc는 rate를 반올림해 보인다(`87710Kbit`)."""
    want = htb_rate_bits(mibps)
    return (st["rate_bits"] is not None and abs(st["rate_bits"] - want) <= want * 1e-3
            and st["filters"] == {"ingress": 1, "egress": 1})


def limited(fsid: str, mibps: float) -> bool:
    return matches(tc_state(fsid), mibps)


def bare(st: dict) -> bool:
    """tc_state에 한도가 없는가: HTB·필터·ifb0가 모두 없다."""
    return st["rate_bits"] is None and st["filters"] == {"ingress": 0, "egress": 0} and not st["ifb0"]


def host_ifbs() -> list[str]:
    return sorted(line.split(":")[1].strip().split("@")[0]
                  for line in sh("ip", "-o", "link", "show", "type", "ifb").stdout.splitlines())


def ifb_tx_bytes(pid: str) -> int | None:
    """netns ifb0의 송신 바이트: HTB를 지난 양방향 skb 바이트 (설계 §6.3, Sampler 설명). 호스트에서 파일 하나만 읽는다."""
    try:
        text = Path(f"/proc/{pid}/net/dev").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name.strip() == "ifb0":
            return int(rest.split()[8])
    return None


class Sampler(threading.Thread):
    """ifb0 송신 바이트를 0.5초마다 읽는다. 인스턴스가 다시 뜨면(pid가 바뀌면) 새 netns를 따라간다.
    windows()는 같은 netns의 표본 사이 1초 창: (창 시작 time.monotonic(), MiB/s). 벽시계는 쓰지 않는다. WSL 벽시계는
    약 32 s마다 0.85 s씩 뒤로 건너뛸 때가 있어, 건너뜀이 든 창이 한도의 1.7배로 읽혔다(검증 1회차 AC-07).

    ifb0 카운터는 GSO 묶음(skb)마다 헤더를 한 번만 센다. 그래서 값이 데이터 처리량에 가깝다(같은 시험의 fio 값보다
    0.5% 안팎 크다). HTB Sent 바이트는 묶음을 세그먼트로 나눈 실제 wire 바이트라 약 4.5% 더 크다(AC-02 기록)."""

    def __init__(self, fsid: str):
        super().__init__(daemon=True)
        self.fsid = fsid
        self.samples: list[tuple[float, str, int]] = []
        self._done = threading.Event()

    def run(self) -> None:
        pid = None
        while not self._done.is_set():
            sent = ifb_tx_bytes(pid) if pid else None
            if sent is None:
                pid = instance_pid(self.fsid)
                sent = ifb_tx_bytes(pid) if pid else None
            if sent is not None:
                self.samples.append((time.monotonic(), pid, sent))
            self._done.wait(0.5)

    def stop(self) -> list[tuple[float, float]]:
        self._done.set()
        self.join(10)
        return self.windows()

    def windows(self) -> list[tuple[float, float]]:
        rows = []
        for i, (t0, pid0, b0) in enumerate(self.samples):
            later = [(t, b) for t, p, b in self.samples[i + 1:] if p == pid0 and t - t0 >= 1.0]
            if later:
                t1, b1 = later[0]
                rows.append((round(t0, 3), round((b1 - b0) / (t1 - t0) / MIB, 3)))
        return rows

    def gaps(self) -> list[tuple[float, float]]:
        """표본이 없던 구간(인스턴스가 없었다): (시작, 끝)."""
        times = [t for t, _, _ in self.samples]
        return [(round(a, 3), round(b, 3)) for a, b in zip(times, times[1:]) if b - a > 1.5]


# --- fio (클라이언트 컨테이너 안) ---


def run_fio(c, jobs: list[tuple[str, str, int]], runtime: int | None = None, bs: str = "1M", iodepth: int = 16,
            timeout: int = 600) -> list[dict]:
    """fio 한 번에 job 여럿 (rw, 경로, 크기 MiB). 공통 옵션은 첫 --name 앞에 둔다.
    반환: job마다 오류 수와 방향별 데이터 MiB/s(io_bytes ÷ 그 방향의 runtime)."""
    cmd = f"{FIO} --bs={bs} --iodepth={iodepth}"
    if runtime is not None:
        cmd += f" --time_based --runtime={runtime}"
    for rw, path, size_mib in jobs:
        cmd += f" --name={rw} --rw={rw} --filename={path} --size={size_mib}M"
    r = c.run(cmd, timeout=timeout)
    assert r.returncode == 0, out(r)
    results = []
    for job in json.loads(r.stdout[r.stdout.index("{"):])["jobs"]:
        result = {"error": job["error"]}
        for d in ("read", "write"):
            if job[d]["io_bytes"]:
                result[d] = round(job[d]["io_bytes"] / MIB / (job[d]["runtime"] / 1000), 4)
        results.append(result)
    return results


def fio(c, rw: str, path: str, size_mib: int, runtime: int | None = None, **kw) -> dict:
    return run_fio(c, [(rw, path, size_mib)], runtime, **kw)[0]


def in_background(fn, *args, **kwargs):
    """fn을 스레드에서 돌린다. 반환: 끝나기를 기다려 값을 돌려주는(예외면 다시 던지는) 함수."""
    box = {}

    def target():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - 기다리는 쪽에서 다시 던진다
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()

    def wait(timeout: float = 900):
        t.join(timeout)
        assert not t.is_alive(), f"{fn.__name__} still running after {timeout}s"
        if "error" in box:
            raise box["error"]
        return box["value"]

    return wait


def drop_caches(c) -> None:
    c.run("sync; echo 3 > /proc/sys/vm/drop_caches")


def measure(c, rw: str, path: str, mibps: float) -> dict:
    """한도 × 15 s 크기를 RUNS + 1회 재고 첫 회를 버린다. 반환: 회별 값, 중앙값, 한도 대비 비율."""
    size = max(1, round(mibps * SECONDS))
    values = []
    for _ in range(RUNS + 1):
        if rw == "read":
            drop_caches(c)
        r = fio(c, rw, path, size)
        assert r["error"] == 0, r
        values.append(round(r[rw], 3))
    median = statistics.median(values[1:])
    return {"rw": rw, "limit": mibps, "runs": values, "median": round(median, 3), "ratio": round(median / mibps, 4)}


def measure_mixed(c, read_path: str, write_path: str, mibps: float) -> dict:
    """AC-03: 읽기 job 하나와 쓰기 job 하나를 15 s 동안 함께. RUNS + 1회 재고 첫 회를 버린다. 값은 둘의 합."""
    size = max(1, round(mibps * SECONDS))
    runs = []
    for _ in range(RUNS + 1):
        drop_caches(c)
        r, w = run_fio(c, [("read", read_path, size), ("write", write_path, size)], runtime=SECONDS)
        assert r["error"] == 0 and w["error"] == 0, (r, w)
        runs.append({"read": r["read"], "write": w["write"], "sum": round(r["read"] + w["write"], 3)})
    median = statistics.median(x["sum"] for x in runs[1:])
    return {"limit": mibps, "runs": runs, "median": round(median, 3), "ratio": round(median / mibps, 4)}


def quick(c, path: str, mibps: float, size_mib: int, seconds: int = SECONDS) -> dict:
    """측정 한 번: 이미 있는 파일(size_mib)에 시간 기반 쓰기. 파일을 늘리지 않는다."""
    r = fio(c, "write", path, size_mib, runtime=seconds)
    assert r["error"] == 0, r
    return {"limit": mibps, "write": r["write"], "ratio": round(r["write"] / mibps, 4)}


def within(ratio: float) -> bool:
    return LOW <= ratio <= HIGH
