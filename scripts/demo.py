#!/usr/bin/env python3
"""PRD §5의 데모 대본(1~7단계)을 떠 있는 compose 스택에 대고 처음부터 끝까지 재현한다 (FR-13, PRD §9).

    python3 scripts/demo.py            1~7단계를 하고 만든 것을 지운다
    python3 scripts/demo.py --keep     지우지 않는다(대시보드로 볼 수 있게). 다음 실행이 시작할 때 지운다
    python3 scripts/demo.py --clean    이전 --keep 실행이 남긴 것만 지운다

요청은 ARM API(127.0.0.1:8080)로 보내고, 효과는 NFS 클라이언트 컨테이너(anf-nfs-client)에서 본다. 단계마다 한 일과
클라이언트에서 관찰한 근거(읽은 파일 내용, 잰 MiB/s, Prometheus 값)를 한 줄씩 출력한다.
Python 표준 라이브러리만 쓰고 root가 필요 없다(docker 그룹이면 된다).
종료 코드: 0 모든 단계 통과, 1 어떤 단계의 기대가 어긋남(그 단계를 보인다), 2 스택이 떠 있지 않음.
설계: _workspace/containers/02_main_design.md §2.
"""

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API = "http://127.0.0.1:8080"
DASHBOARD = "http://127.0.0.1:8081"  # nginx: 페이지, /subscriptions → anf-api, /prometheus/ → Prometheus
UP = "docker compose -f deploy/compose.yaml up -d --build --wait"
V = "api-version=2026-08-01"
SUB = "de300000-0000-4000-8000-000000000013"  # 데모 전용 구독. 다른 리소스와 섞이지 않는다
RG, LOC = "demo-rg", "westus2"
ACCT, POOL = "demo-acct", "demo-pool"
MIB, GIB, TIB = 1 << 20, 1 << 30, 1 << 40
SIZE = 50 * GIB  # ANF의 볼륨 최소 크기. 스택은 낮추지 않는다(thin LV라 실제 디스크는 쓴 만큼만)
SUBNET = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network/virtualNetworks/demo-vnet/subnets/anf"
# (볼륨 이름, creationToken, 프로토콜). Premium 4 TiB Manual 풀의 예산은 256 MiB/s다
V3 = ("vol-v3", "demo-v3", "NFSv3")
V41 = ("vol-v41", "demo-v41", "NFSv4.1")
RESTORED = ("vol-restored", "demo-restored", "NFSv3")  # 프로토콜은 원본(vol-v3)을 따른다
SNAP = "snap1"
# MiB/s. 30 MiB/s 이상 NFS 쓰기는 서버 쪽 쓰기 경로가 몇 초씩 막혀 가끔 한도의 60~70%로 떨어진다(S7 Q2, 제한기 원인
# 아님). FR-08의 아래쪽 판정처럼 10 MiB/s 쓰기로 잰다
LIMIT, NEW_LIMIT = 10.0, 5.0
LOW, HIGH = 0.90, 1.01  # 잰 쓰기 처리량이 한도의 90~101% (FR-08 결정 15와 같은 허용 오차)
CLIENTS = ("anf-demo-client-1", "anf-demo-client-2")
CLIENT_IMAGE, NETWORK = "anf-nfs-client", "anf-vnet"
TEXT = "hello from the ANF clone demo"
# 한도마다 6 s 쓰기를 3회 재고 중앙값으로 본다. 10 MiB/s에서도 한 회가 몇 초 멈춰 38%가 된 적이 있다(FR-13 구현 중)
FIO_RUNS = 3
FIO = ("fio --direct=1 --ioengine=libaio --clocksource=clock_gettime --output-format=json --bs=1M --iodepth=16"
       " --time_based --ramp_time=1 --runtime=6 --name=write --rw=write --size=256M --filename=")


class StepFailed(Exception):
    pass


class StackDown(Exception):
    pass


@dataclass
class Reply:
    status: int
    headers: dict  # 이름은 소문자
    body: bytes

    def json(self):
        return json.loads(self.body)


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # http_proxy 환경 변수를 따르지 않는다


def http_call(method: str, url: str, body=None) -> Reply:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with _opener.open(req, timeout=30) as r:
            return Reply(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        return Reply(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())


def run_cmd(argv: list[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


# --- 순수 부분 ---


def fio_mibps(stdout: str) -> tuple[int, float]:
    """fio JSON 출력(앞에 경고 줄이 올 수 있다)의 첫 job. 반환: (오류 수, 쓰기 MiB/s = io_bytes ÷ runtime)."""
    job = json.loads(stdout[stdout.index("{"):])["jobs"][0]
    w = job["write"]
    return job["error"], round(w["io_bytes"] / MIB / (w["runtime"] / 1000), 2)


def within(measured: float, limit: float) -> bool:
    return LOW <= round(measured / limit, 4) <= HIGH


def throughput_ok(runs: list[float], limit: float) -> bool:
    """중앙값이 한도의 90~101%이고, 한도는 천장이라 어느 회도 101%를 넘지 않는다."""
    return within(statistics.median(runs), limit) and max(runs) / limit <= HIGH


def prom_value(body: dict) -> float | None:
    result = body["data"]["result"]
    return float(result[0]["value"][1]) if result else None


def operation_error(final: dict) -> str | None:
    if final["status"] == "Succeeded":
        return None
    err = final.get("error") or {}
    return f"{final['status']}: {err.get('code')}: {err.get('message')}"


def arm_path(*parts: str) -> str:
    path = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.NetApp/netAppAccounts/{ACCT}"
    for kind, name in zip(("capacityPools", "volumes", "snapshots"), parts):
        path += f"/{kind}/{name}"
    return path


# --- 대본 ---


class Demo:
    def __init__(self, http, run):
        self.http, self.run = http, run
        self.step = "0"
        self.vols: dict[str, dict] = {}

    def say(self, text: str) -> None:
        print(f"[{self.step}] {text}", flush=True)

    # API

    def api(self, method: str, path: str, body=None) -> Reply:
        sep = "&" if "?" in path else "?"
        return self.http(method, f"{API}{path}{sep}{V}", body)

    def wait(self, r: Reply, expect: int, what: str, timeout: float = 300) -> float:
        """즉시 응답의 코드를 확인하고 Azure-AsyncOperation을 종결까지 폴링한다. 반환: 걸린 초."""
        if r.status != expect:
            raise StepFailed(f"{what}: expected {expect}, got {r.status}: {r.body[:300]!r}")
        start, deadline = time.monotonic(), time.monotonic() + timeout
        while True:
            s = self.http("GET", r.headers["azure-asyncoperation"])
            if s.status != 200:
                raise StepFailed(f"{what}: operation status returned {s.status}: {s.body[:300]!r}")
            final = s.json()
            if final["status"] in ("Succeeded", "Failed", "Canceled"):
                break
            if time.monotonic() > deadline:
                raise StepFailed(f"{what}: operation still {final['status']} after {timeout:.0f} s")
            time.sleep(0.5)
        error = operation_error(final)
        if error:
            raise StepFailed(f"{what}: {error}")
        return time.monotonic() - start

    def put(self, path: str, body: dict, what: str) -> dict:
        t = time.monotonic()
        r = self.api("PUT", path, body)
        answered = (time.monotonic() - t) * 1000
        took = self.wait(r, 201, f"PUT {what}")
        g = self.api("GET", path)
        state = g.json()["properties"]["provisioningState"] if g.status == 200 else g.status
        if state != "Succeeded":
            raise StepFailed(f"PUT {what}: provisioningState is {state}")
        self.say(f"PUT {what} -> {r.status} in {answered:.0f} ms; Succeeded after {took:.1f} s")
        return g.json()

    def volume(self, spec: tuple, extra: dict) -> dict:
        name, token, protocol = spec
        props = {"creationToken": token, "usageThreshold": SIZE, "subnetId": SUBNET, "throughputMibps": LIMIT, **extra}
        if "snapshotId" not in extra:
            props["protocolTypes"] = [protocol]
        v = self.put(arm_path(POOL, name), {"location": LOC, "properties": props},
                     f"volume {name} ({protocol}, 50 GiB, {LIMIT:g} MiB/s)")
        p = v["properties"]
        info = {"name": name, "token": token, "ip": p["mountTargets"][0]["ipAddress"],
                "vers": "3" if p["protocolTypes"] == ["NFSv3"] else "4.1", "props": p}
        self.say(f"  mount target {info['ip']}:/{token} ({p['protocolTypes'][0]})")
        return info

    # 클라이언트

    def docker(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        return self.run(["docker", *args], timeout=timeout)

    def sh(self, client: str, script: str, timeout: float = 120) -> str:
        r = self.docker("exec", client, "sh", "-c", script, timeout=timeout)
        if r.returncode != 0:
            raise StepFailed(f"{client}: {script!r} exited {r.returncode}: {r.stderr.strip()[-300:]}")
        return r.stdout.strip()

    def client(self, name: str) -> None:
        self.docker("rm", "-f", name)
        r = self.docker("run", "-d", "--privileged", "--network", NETWORK, "--name", name, CLIENT_IMAGE,
                        "sleep", "3600")
        if r.returncode != 0:
            raise StepFailed(f"docker run {name}: {r.stderr.strip()[-300:]}")

    def mount(self, client: str, vol: dict, mp: str) -> str:
        opts = "vers=3,nolock" if vol["vers"] == "3" else "vers=4.1"
        self.sh(client, f"mkdir -p {mp} && mount -t nfs -o {opts} {vol['ip']}:/{vol['token']} {mp}")
        line = self.sh(client, f"grep ' {mp} ' /proc/mounts").split()
        vers = [o for o in line[3].split(",") if o.startswith("vers=")]
        if vers != [f"vers={vol['vers']}"]:
            raise StepFailed(f"{client}: {mp} mounted with {vers}, expected vers={vol['vers']}")
        return f"{line[0]} on {mp} ({line[2]}, {vers[0]})"

    def read_until(self, client: str, path: str, timeout: float = 60) -> float:
        """path의 내용이 TEXT가 될 때까지 다시 읽는다. 반환: 걸린 초."""
        start = time.monotonic()
        while True:
            r = self.docker("exec", client, "cat", path)
            if r.returncode == 0 and r.stdout.strip() == TEXT:
                return time.monotonic() - start
            if time.monotonic() - start > timeout:
                raise StepFailed(f"{client}: {path} not readable as {TEXT!r} after {timeout:.0f} s: "
                                 f"{(r.stdout + r.stderr).strip()[-200:]}")
            time.sleep(1)

    def fio_write(self, client: str, path: str, limit: float) -> str:
        """FIO_RUNS회 재서 판정한다. 반환: 출력할 값들(회마다 MiB/s와 중앙값의 비율)."""
        runs = []
        for _ in range(FIO_RUNS):
            error, mibps = fio_mibps(self.sh(client, FIO + path, timeout=180))
            if error:
                raise StepFailed(f"fio write {path}: {error} errors")
            runs.append(mibps)
        median = statistics.median(runs)
        text = f"{', '.join(f'{r:g}' for r in runs)} MiB/s (median {median:g} = {median / limit:.0%})"
        if not throughput_ok(runs, limit):
            raise StepFailed(f"fio write {path} with the limit {limit:g} MiB/s: {text}; expected the median in "
                             f"{LOW:.0%}-{HIGH:.0%} and no run above {HIGH:.0%}")
        return text

    # 단계

    def step1(self) -> None:
        self.step = "1"
        self.put(arm_path(), {"location": LOC}, f"account {ACCT}")
        self.put(arm_path(POOL), {"location": LOC, "properties": {"size": 4 * TIB, "serviceLevel": "Premium",
                                                                   "qosType": "Manual"}},
                 f"pool {POOL} (Premium, Manual QoS, 4 TiB)")
        self.vols["v3"] = self.volume(V3, {})
        self.vols["v41"] = self.volume(V41, {})

    def step2(self) -> None:
        self.step = "2"
        c = CLIENTS[0]
        self.client(c)
        for key, mp in (("v3", "/v3"), ("v41", "/v41")):
            self.say(f"{c} mounted {self.mount(c, self.vols[key], mp)}")
            self.sh(c, f"echo '{TEXT}' > {mp}/hello.txt && sync")
            got = self.sh(c, f"cat {mp}/hello.txt")
            if got != TEXT:
                raise StepFailed(f"{mp}/hello.txt reads {got!r}")
            self.say(f"{c} wrote {mp}/hello.txt and read it back: {got!r}")

    def step3(self) -> None:
        self.step = "3"
        c = CLIENTS[0]
        snap = self.put(arm_path(POOL, V3[0], SNAP), {"location": LOC}, f"snapshot {V3[0]}/{SNAP}")
        self.snapshot_id = snap["id"]
        self.sh(c, "rm /v3/hello.txt")
        listing = self.sh(c, "ls /v3").split()
        if "hello.txt" in listing:
            raise StepFailed(f"/v3/hello.txt still listed after rm: {listing}")
        got = self.sh(c, f"cat /v3/.snapshot/{SNAP}/hello.txt")
        if got != TEXT:
            raise StepFailed(f"/v3/.snapshot/{SNAP}/hello.txt reads {got!r}")
        self.say(f"{c} deleted /v3/hello.txt (ls /v3: {' '.join(listing) or 'empty'}); "
                 f"/v3/.snapshot/{SNAP}/hello.txt still reads {got!r}")

    def step4(self) -> None:
        self.step = "4"
        r = self.api("POST", arm_path(POOL, V3[0]) + "/revert", {"snapshotId": self.snapshot_id})
        took = self.wait(r, 202, f"POST revert {V3[0]} to {SNAP}")
        self.say(f"POST revert {V3[0]} to {SNAP} -> {r.status}; Succeeded after {took:.1f} s")
        seen = self.read_until(CLIENTS[0], "/v3/hello.txt")
        self.say(f"{CLIENTS[0]} reads /v3/hello.txt again without remounting ({seen:.1f} s after the revert): "
                 f"{TEXT!r}")

    def step5(self) -> None:
        self.step = "5"
        vol = self.vols["restored"] = self.volume(RESTORED, {"snapshotId": self.snapshot_id})
        origin = vol["props"].get("originatingResourceId")
        if origin != self.snapshot_id:
            raise StepFailed(f"originatingResourceId is {origin}, expected {self.snapshot_id}")
        self.say(f"originatingResourceId = .../{V3[0]}/snapshots/{SNAP}")
        c2 = CLIENTS[1]
        self.client(c2)
        self.say(f"{c2} mounted {self.mount(c2, vol, '/r')}")
        got = self.sh(c2, "cat /r/hello.txt")
        if got != TEXT:
            raise StepFailed(f"/r/hello.txt reads {got!r}")
        self.sh(c2, "echo new > /r/only-in-restored.txt && sync")
        restored = self.sh(c2, "ls /r").split()
        source = self.sh(CLIENTS[0], "ls /v3").split()
        if "only-in-restored.txt" not in restored or "only-in-restored.txt" in source:
            raise StepFailed(f"ls /r: {restored}; ls /v3: {source}")
        self.say(f"{c2} reads /r/hello.txt {got!r} and wrote /r/only-in-restored.txt; "
                 f"source unchanged (ls /v3 on {CLIENTS[0]}: {' '.join(source)})")

    def step6(self) -> None:
        self.step = "6"
        c, name = CLIENTS[0], V41[0]
        first = self.fio_write(c, "/v41/fio", LIMIT)
        self.say(f"fio write on {name} with the limit {LIMIT:g} MiB/s: {first}")
        r = self.api("PATCH", arm_path(POOL, name), {"properties": {"throughputMibps": NEW_LIMIT}})
        took = self.wait(r, 202, f"PATCH {name} throughputMibps={NEW_LIMIT:g}")
        self.say(f"PATCH {name} throughputMibps {LIMIT:g} -> {NEW_LIMIT:g} -> {r.status}; Succeeded after {took:.1f} s")
        second = self.fio_write(c, "/v41/fio", NEW_LIMIT)
        self.say(f"fio write on {name} with the limit {NEW_LIMIT:g} MiB/s: {second}")

    def prom(self, query: str) -> float | None:
        r = self.http("GET", f"{DASHBOARD}/prometheus/api/v1/query?" + urllib.parse.urlencode({"query": query}))
        if r.status != 200:
            raise StepFailed(f"Prometheus via {DASHBOARD}/prometheus/: {r.status}: {r.body[:200]!r}")
        return prom_value(r.json())

    def step7(self) -> None:
        self.step = "7"
        # 이번 실행의 볼륨만 본다. creation_token은 이전 실행의 같은 이름 볼륨과 겹친다
        sel = f'{{volume_uuid="{self.vols["v41"]["props"]["fileSystemId"]}"}}'
        peak_q = f"max_over_time(sum(rate(anf_volume_write_bytes_total{sel}[20s]))[3m:5s])"
        limit_q = f"sum(anf_volume_throughput_limit_bytes_per_second{sel})"
        deadline = time.monotonic() + 30  # Prometheus는 5초마다 긁는다
        while True:
            peak, limit = self.prom(peak_q), self.prom(limit_q)
            if peak and peak >= NEW_LIMIT / 2 * MIB and limit and abs(limit - NEW_LIMIT * MIB) < 1:
                break
            if time.monotonic() > deadline:
                raise StepFailed(f"Prometheus: peak write rate {peak} B/s, limit {limit} B/s for {V41[1]}")
            time.sleep(1)
        self.say(f"Prometheus (via {DASHBOARD}/prometheus/): {V41[1]} write rate peaked at {peak / MIB:.1f} MiB/s "
                 f"during the fio runs; its limit series is {limit / MIB:g} MiB/s")
        page = self.http("GET", f"{DASHBOARD}/?subscription={SUB}")
        if page.status != 200 or b'<div id="root">' not in page.body:
            raise StepFailed(f"dashboard page: {page.status}: {page.body[:200]!r}")
        r = self.http("GET", f"{DASHBOARD}{arm_path(POOL)}/volumes?{V}")
        # 목록의 name은 ARM 중첩 이름(계정/풀/볼륨)이다
        names = sorted(v["name"].rsplit("/", 1)[-1] for v in r.json()["value"]) if r.status == 200 else r.status
        if names != sorted(v[0] for v in (V3, V41, RESTORED)):
            raise StepFailed(f"dashboard /subscriptions proxy: volumes {names}")
        up = self.http("GET", f"{DASHBOARD}/prometheus/api/v1/query?query=up")
        targets = {s["metric"]["job"]: s["value"][1] for s in up.json()["data"]["result"]}
        self.say(f"dashboard {DASHBOARD}/ -> {page.status} (index.html); /subscriptions proxy -> volumes "
                 f"{', '.join(names)}; /prometheus proxy -> up {targets}")
        self.say(f"open http://127.0.0.1:8081/?subscription={SUB} in a browser")

    # 정리

    def delete(self, path: str, what: str) -> bool:
        r = self.api("DELETE", path)
        if r.status == 204:
            return False
        self.wait(r, 202, f"DELETE {what}")
        return True

    def cleanup(self) -> list[str]:
        for c in CLIENTS:
            self.docker("rm", "-f", c)
        removed = []
        for name in (RESTORED[0], V41[0], V3[0]):
            if self.delete(arm_path(POOL, name), f"volume {name}"):
                removed.append(name)
        if self.delete(arm_path(POOL), f"pool {POOL}"):
            removed.append(POOL)
        if self.delete(arm_path(), f"account {ACCT}"):
            removed.append(ACCT)
        return removed

    def check_stack(self) -> None:
        for url in (f"{API}/subscriptions/{SUB}/providers/Microsoft.NetApp/netAppAccounts?{V}",
                    f"{DASHBOARD}/", f"{DASHBOARD}/prometheus/-/ready"):
            try:
                r = self.http("GET", url)
            except OSError as e:
                raise StackDown(f"{url}: {e}") from None
            if r.status != 200:
                raise StackDown(f"{url} returned {r.status}")
        try:
            r = self.docker("image", "inspect", CLIENT_IMAGE)
        except OSError as e:
            raise StackDown(f"docker: {e}") from None
        if r.returncode != 0:
            raise StackDown(f"image {CLIENT_IMAGE} is missing (the init service builds it)")


def main(argv=None, http=http_call, run=run_cmd) -> int:
    p = argparse.ArgumentParser(description="Replay the PRD §5 demo against the running compose stack.")
    p.add_argument("--keep", action="store_true", help="leave the resources and clients for the dashboard")
    p.add_argument("--clean", action="store_true", help="only remove what an earlier --keep run left")
    args = p.parse_args(argv)
    demo = Demo(http, run)
    try:
        demo.check_stack()
    except StackDown as e:
        print(f"The stack is not running ({e}). Start it from the repository root:\n  {UP}", file=sys.stderr)
        return 2
    start, code = time.monotonic(), 0
    try:
        demo.step = "cleanup"
        left = demo.cleanup()  # 이전 --keep 실행이 남긴 것
        if left or args.clean:
            demo.say(f"removed what an earlier run left: {', '.join(left) or 'nothing'}")
        if args.clean:
            return 0
        for step in (demo.step1, demo.step2, demo.step3, demo.step4, demo.step5, demo.step6, demo.step7):
            step()
    except Exception as e:  # noqa: BLE001 - 어느 단계에서 무엇이 어긋났는지 보이고 0이 아닌 코드로 끝난다
        kind = "" if isinstance(e, StepFailed) else f"{type(e).__name__}: "
        print(f"[{demo.step}] FAILED: {kind}{e}", file=sys.stderr)
        code = 1
    finally:
        if not args.keep and not args.clean:
            demo.step = "cleanup"
            try:
                removed = demo.cleanup()
                demo.say(f"removed {', '.join(removed) or 'nothing'} and the clients {', '.join(CLIENTS)}")
            except Exception as e:  # noqa: BLE001
                print(f"[cleanup] FAILED: {e}. Run python3 scripts/demo.py --clean", file=sys.stderr)
                code = 1
    if code == 0:
        kept = " (kept the resources: run python3 scripts/demo.py --clean to remove them)" if args.keep else ""
        print(f"[done] steps 1-7 passed in {time.monotonic() - start:.0f} s{kept}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
