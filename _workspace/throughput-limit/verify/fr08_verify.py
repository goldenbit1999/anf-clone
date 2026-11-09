"""FR-08 처리량 한도 실환경 검증 드라이버 (real-env-verifier 1회차, 처리량 설계 §8).

pytest 시험이 아니다. WSL Ubuntu에서 root로, 저장소 루트에서 단계 이름을 주고 직접 실행한다:
    FR08V_LOG=<로그.jsonl> python backend/tests/e2e/fr08_verify.py <단계>
agent(root)와 anf-api(일반 사용자, ANF_MIN_VOLUME_SIZE_GIB=1)는 이 도구 밖에서 띄운다(검증 scratchpad의 svc.sh).
판정은 이 도구가 하지 않는다. 클라이언트 컨테이너에서 직접 돌린 fio, 인스턴스 netns의 tc 상태와 카운터, API 응답을
그대로 로그에 남기고, 보고서가 그 값으로 판정한다. implementer의 e2e 도우미(throughput_live.py)는 쓰지 않는다.
"""

import http.client
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid as uuidlib
from pathlib import Path

LOG = Path(os.environ.get("FR08V_LOG", "/tmp/fr08v.jsonl"))
SUB = "0f080000-1111-4222-8333-444455556666"
RG = "rg-fr08v"
ACCT = "fr08v"
LOC = "westus2"
V = "api-version=2026-08-01"
GIB, TIB, MIB = 1 << 30, 1 << 40, 1 << 20
SUBNET = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network/virtualNetworks/v/subnets/anf"
NET = "anf-vnet"
CLI = "fr08v-"
DATA_PER_WIRE = 0.9564  # 설계 결정 12
SECONDS = 15  # 한 회의 크기 = 한도 × 15 s (설계 §8)
RUNS = 5  # 첫 회를 버린 뒤의 회 수
SVC = os.environ.get("FR08V_SVC", "")  # svc.sh 경로 (agent·anf-api 재시작 단계)


def now() -> float:
    # 단조 시계: 이 WSL에서는 time.time()이 약 32 s마다 0.6 s씩 뒤로 맞춰져 1초 창을 부풀린다 (1회차 AC-04에서 관찰)
    return time.monotonic()


def log(tag: str, **data) -> dict:
    rec = {"t": round(now(), 3), "wall": round(time.time(), 3), "tag": tag, **data}
    line = json.dumps(rec, ensure_ascii=False, default=str)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return rec


def sh(*argv, timeout=900) -> subprocess.CompletedProcess:
    env = {**os.environ, "LVM_SUPPRESS_FD_WARNINGS": "1"}
    return subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout, env=env)


def svc(*args) -> str:
    r = sh("bash", SVC, *args, timeout=400)
    log("svc", args=args, rc=r.returncode, out=r.stdout.strip()[-600:], err=r.stderr.strip()[-300:])
    return r.stdout


# --- HTTP ---


def request(port: int, method: str, target: str, body=None, timeout=30):
    if target.startswith("http"):
        target = "/" + target.split("/", 3)[3]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, target, body=data, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        hdrs = {k.lower(): v for k, v in r.getheaders()}
    finally:
        conn.close()
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode(errors="replace")
    return r.status, hdrs, parsed


def arm(method: str, path: str, body=None, quiet=False):
    sep = "&" if "?" in path else "?"
    status, hdrs, parsed = request(8080, method, f"{path}{sep}{V}", body)
    if not quiet:
        log("arm", method=method, path=path.split("netAppAccounts/")[-1], req=body, status=status,
            async_op=hdrs.get("azure-asyncoperation"), location=hdrs.get("location"), body=parsed)
    return status, hdrs, parsed


def agent(method: str, path: str, body=None):
    status, _, parsed = request(8090, method, path, body)
    log("agent", method=method, path=path, req=body, status=status, body=parsed)
    return status, parsed


def agent_job(href: str, timeout=300) -> dict:
    deadline = now() + timeout
    while True:
        _, _, job = request(8090, "GET", href)
        if job["state"] in ("success", "failure"):
            log("agent-job", job=job)
            return job
        assert now() < deadline, job
        time.sleep(0.2)


def poll(url: str, timeout=300, interval=0.25) -> tuple[dict, list[str], float]:
    """반환: (종결 본문, 관찰한 status 순서(연속 중복 제거), 종결을 처음 본 시각)."""
    deadline = now() + timeout
    seen = []
    while True:
        status, _, body = request(8080, "GET", url)
        assert status == 200, (status, body)
        if not seen or seen[-1] != body["status"]:
            seen.append(body["status"])
        if body["status"] in ("Succeeded", "Failed", "Canceled"):
            t = now()
            log("poll", url=url.split("operations/")[-1][:60], final=body, seen=seen)
            return body, seen, t
        assert now() < deadline, seen
        time.sleep(interval)


ACCT_PATH = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.NetApp/netAppAccounts/{ACCT}"


def pool_path(pool: str) -> str:
    return f"{ACCT_PATH}/capacityPools/{pool}"


def vol_path(pool: str, vol: str) -> str:
    return f"{pool_path(pool)}/volumes/{vol}"


def snap_path(pool: str, vol: str, snap: str) -> str:
    return f"{vol_path(pool, vol)}/snapshots/{snap}"


def ensure_account() -> None:
    status, _, _ = arm("GET", ACCT_PATH, quiet=True)
    if status == 200:
        return
    s, h, _ = arm("PUT", ACCT_PATH, {"location": LOC})
    assert s == 201
    assert poll(h["azure-asyncoperation"])[0]["status"] == "Succeeded"


def ensure_pool(pool: str, size_tib: int, level: str, qos: str | None = None) -> dict:
    status, _, body = arm("GET", pool_path(pool), quiet=True)
    if status == 200:
        return body
    props = {"size": size_tib * TIB, "serviceLevel": level}
    if qos:
        props["qosType"] = qos
    s, h, _ = arm("PUT", pool_path(pool), {"location": LOC, "properties": props})
    assert s == 201
    assert poll(h["azure-asyncoperation"])[0]["status"] == "Succeeded"
    return arm("GET", pool_path(pool))[2]


def vol_body(token: str, size_gib: int, proto: str, mibps=None, **extra) -> dict:
    props = {"creationToken": token, "usageThreshold": size_gib * GIB, "subnetId": SUBNET,
             "protocolTypes": [proto]}
    if mibps is not None:
        props["throughputMibps"] = mibps
    props.update(extra)
    return {"location": LOC, "properties": props}


def put_volume(pool: str, vol: str, body: dict, timeout=300) -> dict:
    """PUT → 종결. 반환: 응답 코드, 즉시 본문의 상태, 관찰한 작업 status, GET 본문."""
    t0 = now()
    s, h, b = arm("PUT", vol_path(pool, vol), body)
    out = {"status": s, "immediate_state": (b or {}).get("properties", {}).get("provisioningState")
           if isinstance(b, dict) else None, "body": b}
    if s in (200, 201):
        final, seen, t1 = poll(h["azure-asyncoperation"], timeout)
        out.update(final=final["status"], seen=seen, op_seconds=round(t1 - t0, 2), t_done=t1,
                   location_header=h.get("location"))
        out["get"] = arm("GET", vol_path(pool, vol))[2]
    return out


def patch_volume(pool: str, vol: str, props: dict, timeout=300, wait=True) -> dict:
    t0 = now()
    s, h, b = arm("PATCH", vol_path(pool, vol), {"properties": props})
    out = {"status": s, "t_sent": t0, "body": b,
           "immediate_state": b.get("properties", {}).get("provisioningState") if isinstance(b, dict) and
           "properties" in b else None, "async": h.get("azure-asyncoperation")}
    if s == 202 and wait:
        final, seen, t1 = poll(h["azure-asyncoperation"], timeout)
        out.update(final=final["status"], seen=seen, op_seconds=round(t1 - t0, 2), t_done=t1)
    return out


def get_volume(pool: str, vol: str) -> dict:
    return arm("GET", vol_path(pool, vol), quiet=True)[2]


def vol_limits(pool: str, vol: str) -> dict:
    p = get_volume(pool, vol)["properties"]
    return {k: p.get(k) for k in ("provisioningState", "throughputMibps", "actualThroughputMibps",
                                  "usageThreshold", "serviceLevel")} | {"has_throughputMibps": "throughputMibps" in p}


def pool_tp(pool: str) -> dict:
    p = arm("GET", pool_path(pool), quiet=True)[2]["properties"]
    return {k: p[k] for k in ("qosType", "size", "totalThroughputMibps", "utilizedThroughputMibps",
                              "provisioningState")}


def fsid(pool: str, vol: str) -> str:
    return get_volume(pool, vol)["properties"]["fileSystemId"]


def mount_ip(pool: str, vol: str) -> str:
    return get_volume(pool, vol)["properties"]["mountTargets"][0]["ipAddress"]


def delete_volume(pool: str, vol: str, timeout=300) -> dict:
    s, h, b = arm("DELETE", vol_path(pool, vol))
    out = {"status": s}
    if s == 202:
        final, seen, _ = poll(h["azure-asyncoperation"], timeout)
        out.update(final=final["status"], seen=seen)
    return out


# --- 인스턴스 netns ---


def inst(fs: str) -> str:
    return "anf-nfs-" + fs.replace("-", "")


def pid_of(fs: str) -> str | None:
    r = sh("docker", "inspect", "-f", "{{.State.Pid}}", inst(fs))
    p = r.stdout.strip()
    return p if r.returncode == 0 and p not in ("", "0") else None


def nsx(pid: str, *argv) -> subprocess.CompletedProcess:
    return sh("nsenter", "-t", pid, "-n", *argv)


def parse_rate(word: str) -> int:
    for unit, mult in (("Gbit", 10**9), ("Mbit", 10**6), ("Kbit", 10**3), ("bit", 1)):
        if word.endswith(unit):
            return int(float(word[: -len(unit)]) * mult)
    raise ValueError(word)


def tc_state(fs: str) -> dict:
    """netns의 tc 원문과 요약: ifb0, HTB 루트·클래스 rate/ceil, leaf, eth0 clsact, 방향별 redirect 필터 수."""
    pid = pid_of(fs)
    if pid is None:
        return {"pid": None}
    link = nsx(pid, "ip", "-o", "link", "show").stdout
    qd_ifb = nsx(pid, "tc", "qdisc", "show", "dev", "ifb0")
    cls = nsx(pid, "tc", "class", "show", "dev", "ifb0").stdout
    qd_eth = nsx(pid, "tc", "qdisc", "show", "dev", "eth0").stdout
    filt = {d: nsx(pid, "tc", "filter", "show", "dev", "eth0", d).stdout for d in ("ingress", "egress")}
    rate = ceil = None
    for line in cls.splitlines():
        words = line.split()
        if words[:3] == ["class", "htb", "1:1"]:
            rate = parse_rate(words[words.index("rate") + 1])
            ceil = parse_rate(words[words.index("ceil") + 1])
    return {
        "pid": pid, "ifb0": " ifb0:" in link or ": ifb0:" in link,
        "htb_root": "qdisc htb 1: root" in qd_ifb.stdout, "rate_bits": rate, "ceil_bits": ceil,
        "fq_codel_leaf": "qdisc fq_codel 10: parent 1:1" in qd_ifb.stdout,
        "clsact": "qdisc clsact" in qd_eth,
        # tc는 필터마다 머리 줄과 `handle 0x..` 줄을 낸다. 필터 수 = handle 줄 수
        "filters": {d: t.count("matchall chain 0 handle 0x") for d, t in filt.items()},
        "redirect_ifb0": {d: t.count("Egress Redirect to device ifb0") for d, t in filt.items()},
        "raw": {"links": link, "qdisc_ifb0": qd_ifb.stdout + qd_ifb.stderr, "class_ifb0": cls, "qdisc_eth0": qd_eth,
                "filters": filt},
    }


def want_bits(mibps: float) -> int:
    return round(mibps * 1048576 * 8 / DATA_PER_WIRE)


def tc_summary(fs: str, mibps: float | None) -> dict:
    st = tc_state(fs)
    st.pop("raw", None)
    if mibps is not None and st.get("rate_bits") is not None:
        w = want_bits(mibps)
        st["want_bits"] = w
        st["rate_err"] = round((st["rate_bits"] - w) / w, 6)  # tc는 Kbit로 잘라 보인다
    return st


def host_ifbs() -> list[str]:
    return [line.split(":")[1].strip() for line in sh("ip", "-o", "link", "show", "type", "ifb").stdout.splitlines()]


def netdev(pid: str) -> dict | None:
    try:
        text = Path(f"/proc/{pid}/net/dev").read_text()
    except OSError:
        return None
    out = {}
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        f = rest.split()
        out[name.strip()] = (int(f[0]), int(f[8]))  # (rx bytes, tx bytes)
    return out


def htb_sent(pid: str) -> int | None:
    text = nsx(pid, "tc", "-s", "class", "show", "dev", "ifb0").stdout
    words = text.split()
    if "Sent" not in words:
        return None
    return int(words[words.index("Sent") + 1])


class Sampler(threading.Thread):
    """/proc/<pid>/net/dev의 eth0(rx+tx)와 ifb0(tx)를 0.25 s마다 읽는다. 인스턴스가 다시 뜨면 새 pid를 따라간다.
    eth0는 tc가 없을 때도 있으므로 제한 없는 흐름을 잡는다. ifb0 송신은 데이터에 가깝다(설계 §6.3)."""

    def __init__(self, fs: str, period=0.25, htb=True):
        super().__init__(daemon=True)
        self.fs, self.period, self.with_htb = fs, period, htb
        self.samples: list[tuple[float, str, int, int | None]] = []  # (t, pid, eth0 rx+tx, ifb0 tx)
        self.htb: list[tuple[float, str, int]] = []  # 약 1 s마다 HTB 클래스 Sent (wire 바이트)
        self._done = threading.Event()

    def run(self):
        pid = None
        last_lookup = last_htb = 0.0
        while not self._done.is_set():
            d = netdev(pid) if pid else None
            if d is None and now() - last_lookup > 0.2:
                pid, last_lookup = pid_of(self.fs), now()
                d = netdev(pid) if pid else None
            if d is not None and "eth0" in d:
                eth = d["eth0"][0] + d["eth0"][1]
                ifb = d["ifb0"][1] if "ifb0" in d else None
                self.samples.append((now(), pid, eth, ifb))
                if self.with_htb and ifb is not None and now() - last_htb >= 0.95:
                    t = now()
                    sent = htb_sent(pid)
                    if sent is not None:
                        self.htb.append(((t + now()) / 2, pid, sent))
                    last_htb = t
            self._done.wait(self.period)

    def htb_windows(self) -> list[tuple[float, float]]:
        """HTB Sent의 이웃 표본 창 × 0.9564 (데이터로 환산한 상한)."""
        rows = []
        for a, b in zip(self.htb, self.htb[1:]):
            if a[1] == b[1] and b[0] > a[0]:
                rows.append((round(a[0], 3), round((b[2] - a[2]) / (b[0] - a[0]) / MIB * DATA_PER_WIRE, 4)))
        return rows

    def stop(self):
        self._done.set()
        self.join(10)

    def windows(self, which="ifb", t_from=None, t_to=None) -> list[tuple[float, float]]:
        """1초 창 (창 시작 시각, MiB/s). which = 'ifb' | 'eth'."""
        idx = 3 if which == "ifb" else 2
        rows = []
        s = self.samples
        for i, a in enumerate(s):
            if (t_from is not None and a[0] < t_from) or (t_to is not None and a[0] > t_to) or a[idx] is None:
                continue
            for b in s[i + 1:]:
                if b[1] != a[1]:
                    break
                if b[0] - a[0] >= 1.0 and b[idx] is not None:
                    rows.append((round(a[0], 3), round((b[idx] - a[idx]) / (b[0] - a[0]) / MIB, 4)))
                    break
        return rows

    def pids(self) -> list[tuple[str, float, float]]:
        out = []
        for t, pid, _, _ in self.samples:
            if not out or out[-1][0] != pid:
                out.append([pid, t, t])
            out[-1][2] = t
        return [tuple(x) for x in out]

    def gaps(self, more_than=1.0) -> list[tuple[float, float]]:
        ts = [x[0] for x in self.samples]
        return [(round(a, 3), round(b, 3)) for a, b in zip(ts, ts[1:]) if b - a > more_than]

    def first_ifb(self, pid: str) -> float | None:
        return next((t for t, p, _, i in self.samples if p == pid and i is not None), None)


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": round(statistics.median(values), 4), "min": round(min(values), 4),
            "max": round(max(values), 4)}


# --- 클라이언트 ---


def client(name: str) -> str:
    full = CLI + name
    r = sh("docker", "inspect", "-f", "{{.State.Running}}", full)
    if r.stdout.strip() != "true":
        sh("docker", "rm", "-f", full)
        r = sh("docker", "run", "-d", "--privileged", "--network", NET, "--name", full, "anf-nfs-client",
               "sleep", "infinity")
        assert r.returncode == 0, r.stderr
    return full


def cx(cli: str, script: str, timeout=900) -> subprocess.CompletedProcess:
    return sh("docker", "exec", cli, "sh", "-c", script, timeout=timeout)


def mount(cli: str, ip: str, token: str, proto: str, mp: str) -> None:
    opts = "vers=3,nolock" if proto == "NFSv3" else "vers=4.1"
    r = cx(cli, f"mountpoint -q {mp} || {{ mkdir -p {mp} && mount -t nfs -o {opts} {ip}:/{token} {mp}; }}; "
                f"grep ' {mp} ' /proc/mounts")
    log("mount", cli=cli, mp=mp, ip=ip, token=token, rc=r.returncode, out=r.stdout.strip(), err=r.stderr.strip())
    assert r.returncode == 0, r.stderr


def drop_caches(cli: str) -> None:
    cx(cli, "sync; echo 3 > /proc/sys/vm/drop_caches")


def mountstats(cli: str, mp: str) -> str:
    """그 마운트의 mountstats 중 age, xprt(연결 횟수 등), READ/WRITE 줄."""
    r = cx(cli, f"awk '/ mounted on {mp.replace('/', chr(92) + '/')} /{{f=1;print;next}} /^device /{{f=0}} f' "
                "/proc/self/mountstats | grep -E 'mounted on|age:|xprt:|READ:|WRITE:'")
    return r.stdout


DB = "/home/mkimhome1/.local/state/anf-clone/fr08-verify.db"


def db_counts() -> dict:
    """anf-api DB의 작업·리소스 행 수. DB 사용자 권한으로 읽기 전용으로 연다."""
    code = ("import sqlite3,json;c=sqlite3.connect('file:%s?mode=ro',uri=True);"
            "print(json.dumps({'operations':c.execute('select count(*) from operations').fetchone()[0],"
            "'resources':c.execute('select count(*) from resources').fetchone()[0]}))" % DB)
    r = sh("setpriv", "--reuid=1000", "--regid=1000", "--init-groups", "python3", "-c", code)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr}


FIO = "fio --direct=1 --ioengine=libaio --clocksource=clock_gettime --output-format=json"


def fio(cli: str, jobs: list[dict], bs="1M", iodepth=16, runtime=None, timeout=1200, extra="") -> dict:
    """jobs: [{"rw": "write", "path": "/m/f", "size": "150M"}]. 반환: job별 오류와 방향별 MiB/s(io_bytes ÷ runtime)."""
    cmd = f"{FIO} --bs={bs} --iodepth={iodepth} {extra}"
    if runtime is not None:
        cmd += f" --time_based --runtime={runtime}"
    for j in jobs:
        cmd += f" --name={j['rw']}-{j['path'].replace('/', '_')} --rw={j['rw']} --filename={j['path']} --size={j['size']}"
    t0 = now()
    r = cx(cli, cmd, timeout=timeout)
    t1 = now()
    res = {"cmd": cmd, "rc": r.returncode, "t0": round(t0, 3), "t1": round(t1, 3), "jobs": []}
    try:
        data = json.loads(r.stdout[r.stdout.index("{"):])
        for job in data["jobs"]:
            jr = {"name": job["jobname"], "error": job["error"]}
            for d in ("read", "write"):
                if job[d]["io_bytes"]:
                    jr[d] = round(job[d]["io_bytes"] / MIB / (job[d]["runtime"] / 1000), 4)
                    jr[d + "_bytes"] = job[d]["io_bytes"]
                    jr[d + "_runtime_ms"] = job[d]["runtime"]
                    jr[d + "_clat_max_s"] = round(job[d]["clat_ns"]["max"] / 1e9, 3)
            res["jobs"].append(jr)
    except (ValueError, KeyError) as e:
        res["parse_error"] = repr(e)
        res["stdout"] = r.stdout[-2000:]
        res["stderr"] = r.stderr[-2000:]
    return res


def measure(cli: str, fs: str, rw: str, path: str, limit: float, runs=RUNS, label="") -> dict:
    """크기 한도 × 15 s, 첫 회 버림, runs회 중앙값. 회마다 HTB Sent와 ifb0 송신 바이트로 데이터/wire를 함께 낸다."""
    size = max(1, round(limit * SECONDS))
    vals, per = [], []
    for k in range(runs + 1):
        if rw == "read":
            drop_caches(cli)
        pid = pid_of(fs)
        h0, d0 = htb_sent(pid), netdev(pid)
        r = fio(cli, [{"rw": rw, "path": path, "size": f"{size}M"}])
        h1, d1 = htb_sent(pid), netdev(pid)
        j = r["jobs"][0] if r["jobs"] else {}
        v = j.get(rw)
        row = {"run": k, "mibps": v, "error": j.get("error"), "rc": r["rc"], "clat_max_s": j.get(rw + "_clat_max_s"),
               "data_bytes": j.get(rw + "_bytes"), "htb_bytes": (h1 - h0) if h0 is not None and h1 is not None else None,
               "ifb_tx_bytes": d1["ifb0"][1] - d0["ifb0"][1] if d0 and d1 and "ifb0" in d0 else None}
        if row["data_bytes"] and row["htb_bytes"]:
            row["data_per_htb"] = round(row["data_bytes"] / row["htb_bytes"], 4)
            row["data_per_ifbtx"] = round(row["data_bytes"] / row["ifb_tx_bytes"], 4)
        per.append(row)
        vals.append(v)
        if "parse_error" in r:
            log("fio-parse-error", fio=r)
    kept = [v for v in vals[1:] if v is not None]
    med = statistics.median(kept) if kept else None
    out = {"label": label, "rw": rw, "limit": limit, "size_mib": size, "runs": vals,
           "median": round(med, 4) if med else None, "ratio": round(med / limit, 4) if med else None,
           "max_ratio_kept": round(max(kept) / limit, 4) if kept else None,
           "min_ratio_kept": round(min(kept) / limit, 4) if kept else None,
           "errors": [p["error"] for p in per], "per_run": per}
    log("measure", **out)
    return out


def mem(tag: str) -> None:
    r = sh("free", "-m")
    log("mem", where=tag, free=r.stdout.splitlines()[1])


def drop_host_caches(tag: str) -> None:
    sh("sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches")
    mem(tag)


def lazyinit() -> bool:
    return "ext4lazyinit" in sh("ps", "-eo", "comm").stdout


# --- 단계 ---

TOK = "fr08v"


def step_ac11():
    """AC-11: agent API 직접. 볼륨 POST의 qos, GET 레코드, netns tc, 같은 uuid 다른 값, qos 없음, 모양 오류."""
    u1, u2 = str(uuidlib.uuid4()), str(uuidlib.uuid4())

    def body(u, path, proto="nfs4.1", qos=None):
        b = {"uuid": u, "name": "vol_" + u.replace("-", ""), "size": GIB,
             "nas": {"path": path, "unix_permissions": 777, "protocols": [proto]}}
        if qos is not None:
            b["qos"] = qos
        return b

    def post(b):
        s, reply = agent("POST", "/api/storage/volumes", b)
        job = agent_job(reply["job"]["_links"]["self"]["href"]) if s == 202 else None
        return s, reply, job

    def lvtags(u):
        r = sh("lvs", "--noheadings", "-o", "lv_tags", "anf/vol_" + u.replace("-", ""))
        return sorted(t for t in r.stdout.strip().split(",") if t)

    log("ac11-start", host_ifbs=host_ifbs())
    s, reply, job = post(body(u1, f"/{TOK}-a11a", qos={"policy": {"max_throughput_mbps": 10}}))
    log("ac11-post-qos10", status=s, job_state=job["state"], record=agent("GET", f"/api/storage/volumes/{u1}")[1],
        tags=lvtags(u1), tc=tc_summary(u1, 10), tc_raw=tc_state(u1)["raw"])
    s, reply, job = post(body(u1, f"/{TOK}-a11a", qos={"policy": {"max_throughput_mbps": 20}}))
    log("ac11-post-qos20", status=s, job_state=job["state"], record=agent("GET", f"/api/storage/volumes/{u1}")[1],
        tags=lvtags(u1), tc=tc_summary(u1, 20))
    s, reply, job = post(body(u1, f"/{TOK}-a11a", qos={"policy": {"max_throughput_mbps": 20}}))
    log("ac11-post-qos20-again", status=s, job_state=job["state"], tags=lvtags(u1), tc=tc_summary(u1, 20))
    s, reply, job = post(body(u1, f"/{TOK}-a11a"))
    log("ac11-post-noqos-existing", status=s, job_state=job["state"], tags=lvtags(u1), tc=tc_summary(u1, 20),
        record=agent("GET", f"/api/storage/volumes/{u1}")[1])
    s, reply, job = post(body(u2, f"/{TOK}-a11b", proto="nfs3"))
    st = tc_state(u2)
    log("ac11-post-noqos-new", status=s, job_state=job["state"], record=agent("GET", f"/api/storage/volumes/{u2}")[1],
        tags=lvtags(u2), tc={k: v for k, v in st.items() if k != "raw"}, tc_raw=st.get("raw"))
    # 데이터: 20 MiB/s 볼륨과 제한 없는 볼륨에 짧은 쓰기 (보조 근거)
    c = client("a11")
    ip1 = agent("GET", f"/api/storage/volumes/{u1}")[1]["data_lif"]["ip"]["address"]
    ip2 = agent("GET", f"/api/storage/volumes/{u2}")[1]["data_lif"]["ip"]["address"]
    mount(c, ip1, f"{TOK}-a11a", "NFSv4.1", "/m1")
    mount(c, ip2, f"{TOK}-a11b", "NFSv3", "/m2")
    log("ac11-fio", limited=fio(c, [{"rw": "write", "path": "/m1/f", "size": "200M"}], runtime=10),
        unlimited=fio(c, [{"rw": "write", "path": "/m2/f", "size": "200M"}], runtime=10))
    cx(c, "umount /m1; umount /m2")
    before = sorted(r["uuid"] for r in agent("GET", "/api/storage/volumes")[1]["records"])
    bad = {
        "extra_qos_field": {"policy": {"max_throughput_mbps": 10}, "name": "x"},
        "extra_policy_field": {"policy": {"max_throughput_mbps": 10, "min_throughput_mbps": 1}},
        "empty_policy": {"policy": {}},
        "zero": {"policy": {"max_throughput_mbps": 0}},
        "negative": {"policy": {"max_throughput_mbps": -5}},
        "string": {"policy": {"max_throughput_mbps": "10"}},
        "bool": {"policy": {"max_throughput_mbps": True}},
        "null": {"policy": {"max_throughput_mbps": None}},
        "qos_not_object": 10,
    }
    u3 = str(uuidlib.uuid4())
    for label, q in bad.items():
        s, reply = agent("POST", "/api/storage/volumes", body(u3, f"/{TOK}-a11c", qos=q))
        log("ac11-bad", label=label, status=s, reply=reply)
    # 문자열 NaN은 JSON 표준 밖이라 원문으로 보낸다
    conn = http.client.HTTPConnection("127.0.0.1", 8090, timeout=30)
    raw = json.dumps(body(u3, f"/{TOK}-a11c", qos={"policy": {"max_throughput_mbps": 1.0}})).replace("1.0", "NaN")
    conn.request("POST", "/api/storage/volumes", body=raw, headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    log("ac11-bad", label="nan", status=r.status, reply=r.read().decode())
    conn.close()
    after = sorted(r["uuid"] for r in agent("GET", "/api/storage/volumes")[1]["records"])
    log("ac11-bad-no-volume", before=before, after=after, same=before == after, u3_lv=lvtags(u3))
    for u in (u1, u2):
        p1 = pid_of(u)
        s, reply = agent("DELETE", f"/api/storage/volumes/{u}")
        job = agent_job(reply["job"]["_links"]["self"]["href"])
        log("ac11-delete", uuid=u, job_state=job["state"], old_pid=p1, pid_alive=Path(f"/proc/{p1}").exists(),
            host_ifbs=host_ifbs())


def step_setup():
    ensure_account()
    pools = {"auto-prem": (4, "Premium", None), "auto-std": (1, "Standard", None), "auto-ultra": (1, "Ultra", None),
             "man-ultra": (40, "Ultra", "Manual"), "man-small": (2, "Premium", "Manual"),
             "sw-prem": (1, "Premium", None), "sw-busy": (1, "Premium", None)}
    for name, (size, level, qos) in pools.items():
        ensure_pool(name, size, level, qos)
        log("pool", name=name, props=pool_tp(name))


def step_ac01a():
    out = {}
    for pool, vol, gib, proto, expect in (("auto-prem", "p101", 101, "NFSv3", 6.312),
                                          ("auto-prem", "p1", 1, "NFSv3", 0.062),
                                          ("auto-std", "s1", 1, "NFSv4.1", 0.016)):
        r = put_volume(pool, vol, vol_body(f"{TOK}-{vol}", gib, proto))
        lim = vol_limits(pool, vol)
        fs = fsid(pool, vol)
        out[vol] = {"put": r["status"], "seen": r.get("seen"), "limits": lim, "expect": expect,
                    "tc": tc_summary(fs, expect), "agent_qos": agent("GET", f"/api/storage/volumes/{fs}")[1].get("qos")}
        log("ac01a-volume", vol=vol, **out[vol])
    log("ac01a-pools", auto_prem=pool_tp("auto-prem"), auto_std=pool_tp("auto-std"))
    log("ac01a-p101-delete", result=delete_volume("auto-prem", "p101"), auto_prem=pool_tp("auto-prem"))


def step_ac01b():
    c = client("c1")
    for vol, gib, proto in (("u80", 80, "NFSv3"), ("u40", 40, "NFSv4.1")):
        r = put_volume("auto-ultra", vol, vol_body(f"{TOK}-{vol}", gib, proto))
        lim = vol_limits("auto-ultra", vol)
        log("ac01b-volume", vol=vol, put=r["status"], seen=r.get("seen"), limits=lim,
            tc=tc_summary(fsid("auto-ultra", vol), lim["actualThroughputMibps"]))
        mount(c, mount_ip("auto-ultra", vol), f"{TOK}-{vol}", proto, f"/{vol}")
    log("ac01b-pool", pool=pool_tp("auto-ultra"), lazyinit=lazyinit())
    for vol in ("u80", "u40"):
        lim = vol_limits("auto-ultra", vol)["actualThroughputMibps"]
        fs = fsid("auto-ultra", vol)
        for rw in ("write", "read"):
            drop_host_caches(f"before {vol} {rw}")
            measure(c, fs, rw, f"/{vol}/f", lim, label=f"ac01b {vol} {rw}")
        log("ac01b-lazyinit", running=lazyinit())


def step_ac02():
    c = client("c1")
    for vol, mibps, proto in (("m10", 10, "NFSv4.1"), ("m20", 20, "NFSv3"), ("m125", 12.5, "NFSv4.1")):
        r = put_volume("man-ultra", vol, vol_body(f"{TOK}-{vol}", 1, proto, mibps))
        log("ac02-volume", vol=vol, put=r["status"], immediate=r.get("immediate_state"), seen=r.get("seen"),
            limits=vol_limits("man-ultra", vol), tc=tc_summary(fsid("man-ultra", vol), mibps), pool=pool_tp("man-ultra"))
        mount(c, mount_ip("man-ultra", vol), f"{TOK}-{vol}", proto, f"/{vol}")
    for vol, mibps, dirs in (("m10", 10, ("write", "read")), ("m20", 20, ("write", "read")), ("m125", 12.5, ("write",))):
        fs = fsid("man-ultra", vol)
        for rw in dirs:
            drop_host_caches(f"before {vol} {rw}")
            measure(c, fs, rw, f"/{vol}/f", mibps, label=f"ac02 {vol} {rw}")


def step_ac03():
    c = client("c1")
    for vol, mibps in (("m10", 10.0), ("m20", 20.0)):
        fs = fsid("man-ultra", vol)
        size = round(mibps * SECONDS)
        runs = []
        for k in range(RUNS + 1):
            drop_caches(c)
            r = fio(c, [{"rw": "read", "path": f"/{vol}/f", "size": f"{size}M"},
                        {"rw": "write", "path": f"/{vol}/g", "size": f"{size}M"}], runtime=SECONDS)
            rd, wr = r["jobs"][0], r["jobs"][1]
            runs.append({"run": k, "read": rd.get("read"), "write": wr.get("write"),
                         "sum": round((rd.get("read") or 0) + (wr.get("write") or 0), 4),
                         "errors": [rd["error"], wr["error"]], "rc": r["rc"]})
        med = statistics.median(x["sum"] for x in runs[1:])
        log("ac03", vol=vol, limit=mibps, runs=runs, median=round(med, 4), ratio=round(med / mibps, 4),
            tc=tc_summary(fs, mibps))
        drop_host_caches(f"after ac03 {vol}")


def step_ac04():
    c = client("c1")
    w_fs, r_fs = fsid("man-ultra", "m10"), fsid("man-ultra", "m20")
    pre = patch_volume("man-ultra", "m20", {"throughputMibps": 10})
    log("ac04-pre", m20_to_10=pre, m10=vol_limits("man-ultra", "m10"), m20=vol_limits("man-ultra", "m20"),
        tc_w=tc_summary(w_fs, 10), tc_r=tc_summary(r_fs, 10))
    stats0 = {v: mountstats(c, f"/{v}") for v in ("m10", "m20")}
    sw, sr = Sampler(w_fs), Sampler(r_fs)
    sw.start()
    sr.start()
    drop_caches(c)
    box = {}

    def run(key, jobs):
        box[key] = fio(c, jobs, runtime=60)

    tw = threading.Thread(target=run, args=("w", [{"rw": "write", "path": "/m10/f", "size": "150M"}]))
    tr = threading.Thread(target=run, args=("r", [{"rw": "read", "path": "/m20/f", "size": "300M"}]))
    t0 = now()
    tw.start()
    tr.start()
    events = []
    time.sleep(15)
    for target in (30, 5):
        for vol in ("m10", "m20"):
            p = patch_volume("man-ultra", vol, {"throughputMibps": target}, wait=False)
            events.append({"vol": vol, "target": target, "t_sent": p["t_sent"], "status": p["status"],
                           "immediate": p["immediate_state"], "async": p["async"]})
        for e in events[-2:]:
            final, seen, t1 = poll(e["async"], interval=0.1)
            e.update(final=final["status"], seen=seen, t_done=t1, op_seconds=round(t1 - e["t_sent"], 2))
        time.sleep(18)
    tw.join(200)
    tr.join(200)
    sw.stop()
    sr.stop()
    stats1 = {v: mountstats(c, f"/{v}") for v in ("m10", "m20")}
    result = {"t0": t0, "events": events, "fio_w": box.get("w"), "fio_r": box.get("r"),
              "mountstats_before": stats0, "mountstats_after": stats1,
              "tc_w": tc_summary(w_fs, 5), "tc_r": tc_summary(r_fs, 5)}
    for key, s in (("m10", sw), ("m20", sr)):
        wins = s.windows("ifb")
        hw = s.htb_windows()
        result[f"windows_{key}"] = [(round(t - t0, 2), v) for t, v in wins]
        result[f"htb_windows_{key}"] = [(round(t - t0, 2), v) for t, v in hw]
        mine = [e for e in events if e["vol"] == key]
        checks = []
        for e in mine:
            after = [v for t, v in wins if e["t_done"] <= t <= e["t_done"] + 2]
            checks.append({"target": e["target"], "op_seconds": e["op_seconds"], "t_done_rel": round(e["t_done"] - t0, 2),
                           "windows_2s": after, "ratios": [round(v / e["target"], 4) for v in after],
                           "htb_2s": [v for t, v in hw if e["t_done"] <= t <= e["t_done"] + 2]})
        result[f"checks_{key}"] = checks
        active = [v for t, v in wins if t0 + 3 <= t <= t0 + 58]
        result[f"min_window_{key}"] = min(active) if active else None
        result[f"gaps_{key}"] = s.gaps()
    log("ac04", **result)
    # 재PUT(Updating)으로 바꾸기: m10 15 MiB/s, 쓰는 중
    sw = Sampler(w_fs)
    sw.start()
    t0 = now()
    tw = threading.Thread(target=run, args=("w2", [{"rw": "write", "path": "/m10/f", "size": "150M"}]))
    tw.start()
    time.sleep(10)
    body = get_volume("man-ultra", "m10")
    props = {k: v for k, v in body["properties"].items()}
    props["throughputMibps"] = 15
    r = put_volume("man-ultra", "m10", {"location": body["location"], "tags": body.get("tags", {}),
                                        "properties": props})
    tw.join(200)
    sw.stop()
    wins = sw.windows("ifb")
    log("ac04-reput", put=r["status"], immediate=r.get("immediate_state"), seen=r.get("seen"),
        op_seconds=r.get("op_seconds"), limits=vol_limits("man-ultra", "m10"), tc=tc_summary(w_fs, 15),
        windows=[(round(t - t0, 2), v) for t, v in wins],
        after_2s=[v for t, v in wins if r["t_done"] <= t <= r["t_done"] + 2], fio=box.get("w2"))
    drop_host_caches("after ac04")


def step_ac05():
    c = client("c5")
    for vol, mibps, gib in (("a10", 10, 1), ("b4500", 4500, 4)):
        r = put_volume("man-ultra", vol, vol_body(f"{TOK}-{vol}", gib, "NFSv4.1", mibps))
        log("ac05-volume", vol=vol, put=r["status"], seen=r.get("seen"), limits=vol_limits("man-ultra", vol),
            tc=tc_summary(fsid("man-ultra", vol), mibps))
        mount(c, mount_ip("man-ultra", vol), f"{TOK}-{vol}", "NFSv4.1", f"/{vol}")
    fa, fb = fsid("man-ultra", "a10"), fsid("man-ultra", "b4500")
    # 파일 준비: A 150 MiB, B 1 GiB
    log("ac05-prep", a=fio(c, [{"rw": "write", "path": "/a10/f", "size": "150M"}]),
        b=fio(c, [{"rw": "write", "path": "/b4500/f", "size": "1024M"}]))
    drop_host_caches("ac05 after prep")
    alone = measure(c, fa, "read", "/a10/f", 10, label="ac05 A alone read")
    # B만: 서버 캐시에서 읽기 (첫 회는 캐시를 채운다)
    b_alone = [fio(c, [{"rw": "read", "path": "/b4500/f", "size": "1024M"}], runtime=SECONDS) for _ in range(3)]
    log("ac05-b-alone", runs=[x["jobs"][0].get("read") for x in b_alone])
    together = []
    for k in range(RUNS + 1):
        drop_caches(c)  # A만 잴 때(measure)와 같은 조건
        r = fio(c, [{"rw": "read", "path": "/a10/f", "size": "150M"},
                    {"rw": "read", "path": "/b4500/f", "size": "1024M"}], runtime=SECONDS)
        together.append({"run": k, "a": r["jobs"][0].get("read"), "b": r["jobs"][1].get("read"),
                         "errors": [j["error"] for j in r["jobs"]]})
    a_med = statistics.median(x["a"] for x in together[1:])
    b_med = statistics.median(x["b"] for x in together[1:])
    log("ac05-together-read", runs=together, a_median=round(a_med, 4), b_median=round(b_med, 2),
        a_ratio=round(a_med / 10, 4), b_over_a=round(b_med / a_med, 1),
        a_alone_median=alone["median"], diff=round(abs(a_med - alone["median"]), 4),
        tc_a=tc_summary(fa, 10), tc_b=tc_summary(fb, 4500))
    drop_host_caches("ac05 before write sample")
    w = fio(c, [{"rw": "write", "path": "/a10/f", "size": "150M", }], runtime=SECONDS)
    log("ac05-a-write-alone", fio=w)
    # 함께 쓰기 한 번: A는 15 s 시간 기반, B는 2 GiB 크기 고정 (수 GiB 이하)
    box = {}
    ta = threading.Thread(target=lambda: box.update(a=fio(c, [{"rw": "write", "path": "/a10/f", "size": "150M"}],
                                                          runtime=SECONDS)))
    tb = threading.Thread(target=lambda: box.update(b=fio(c, [{"rw": "write", "path": "/b4500/w", "size": "2048M"}])))
    ta.start()
    tb.start()
    ta.join(300)
    tb.join(300)
    log("ac05-together-write", a=box.get("a"), b=box.get("b"))
    drop_host_caches("after ac05")


def step_ac05w():
    """AC-05 쓰기 표본을 두 번 더: A 15 s 시간 기반 쓰기 + B 2 GiB 쓰기를 함께. 그동안 A의 ifb0 HTB 대기열(backlog)과
    A의 1초 창을 본다. 대기열이 비어 있으면 A가 늦은 원인은 A의 제한기가 아니다."""
    c = client("c5")
    fa = fsid("man-ultra", "a10")
    for k in range(2):
        drop_host_caches(f"ac05w {k}")
        pid = pid_of(fa)
        s = Sampler(fa)
        s.start()
        box, backlog = {}, []
        ta = threading.Thread(target=lambda: box.update(a=fio(c, [{"rw": "write", "path": "/a10/f", "size": "150M"}],
                                                              runtime=SECONDS)))
        tb = threading.Thread(target=lambda: box.update(b=fio(c, [{"rw": "write", "path": "/b4500/w",
                                                                    "size": "2048M"}])))
        t0 = now()
        ta.start()
        tb.start()
        while ta.is_alive() or tb.is_alive():
            q = nsx(pid, "tc", "-s", "qdisc", "show", "dev", "ifb0").stdout
            words = q.split()
            backlog.append((round(now() - t0, 1), [words[i + 1] for i, w in enumerate(words) if w == "backlog"]))
            time.sleep(1)
        s.stop()
        log("ac05w", k=k, a=box.get("a", {}).get("jobs"), b=box.get("b", {}).get("jobs"), backlog=backlog,
            a_windows=[(round(t - t0, 1), v) for t, v in s.windows("ifb")][::4])
    drop_host_caches("after ac05w")


def step_ac06():
    c1, c2 = client("c6a"), client("c6b")
    r = put_volume("auto-prem", "p1b", vol_body(f"{TOK}-p1b", 1, "NFSv4.1"))
    log("ac06-volume", put=r["status"], limits=vol_limits("auto-prem", "p1b"),
        tc=tc_summary(fsid("auto-prem", "p1b"), 0.062), tc_p1=tc_summary(fsid("auto-prem", "p1"), 0.062))
    vols = (("p1", "NFSv3"), ("p1b", "NFSv4.1"))
    dmesg0 = sh("dmesg").stdout.count("\n")
    for vol, proto in vols:
        ip = mount_ip("auto-prem", vol)
        for cli in (c1, c2):
            mount(cli, ip, f"{TOK}-{vol}", proto, f"/{vol}")
    small = {}
    for vol, _ in vols:
        r = cx(c1, f"cat /proc/uptime; echo hello-{vol} > /{vol}/small && cat /{vol}/small && ls -la /{vol} && "
                   "cat /proc/uptime")
        r2 = cx(c2, f"cat /{vol}/small; ls /{vol}")
        small[vol] = {"rc": r.returncode, "out": r.stdout, "err": r.stderr, "other_rc": r2.returncode,
                      "other_out": r2.stdout}
    log("ac06-small", **small)
    box = {}
    threads = [threading.Thread(target=lambda v=v: box.update({v: fio(
        c1, [{"rw": "write", "path": f"/{v}/big", "size": "4M"}], bs="64k", iodepth=1, runtime=30,
        extra="--fallocate=none")})) for v, _ in vols]
    for t in threads:
        t.start()
    probes = []
    time.sleep(3)
    for k in range(3):
        for vol, _ in vols:
            for cli, kind in ((c1, "same"), (c2, "other")):
                r = cx(cli, f"a=$(cat /proc/uptime | cut -d' ' -f1); ls /{vol} >/dev/null; b=$(cat /proc/uptime | "
                            f"cut -d' ' -f1); dd if=/dev/zero of=/{vol}/probe-{kind} bs=4k count=1 conv=fsync "
                            f"2>/dev/null; c=$(cat /proc/uptime | cut -d' ' -f1); echo $a $b $c", timeout=300)
                a, b, cc = (float(x) for x in r.stdout.split())
                probes.append({"k": k, "vol": vol, "conn": kind, "ls_s": round(b - a, 2), "dd4k_s": round(cc - b, 2),
                               "rc": r.returncode})
        time.sleep(7)
    for t in threads:
        t.join(600)
    ms = {}
    for vol, _ in vols:
        r = cx(c1, f"awk '/mounted on \\/{vol} /,/^device /' /proc/self/mountstats | grep -E 'WRITE:|xprt:'")
        ms[vol] = r.stdout
    dm = sh("dmesg").stdout.splitlines()[dmesg0:]
    nfsmsg = [x for x in dm if "nfs" in x.lower() or "rpc" in x.lower()]
    log("ac06-big", fio=box, probes=probes, mountstats=ms, dmesg_nfs=nfsmsg[-40:], dmesg_nfs_count=len(nfsmsg),
        limit=0.062, upper=round(0.062 * 1.01, 5))
    for vol, _ in vols:
        r = cx(c1, f"cat /{vol}/small && ls -la /{vol}")
        log("ac06-after", vol=vol, rc=r.returncode, out=r.stdout)


def step_ac08():
    out = []

    def check(label, s, b, extra=None):
        err = b.get("error", {}) if isinstance(b, dict) else {}
        out.append({"label": label, "status": s, "code": err.get("code"), "message": err.get("message"),
                    "db_after": db_counts(), **(extra or {})})
        log("ac08", **out[-1])

    def exists(pool, vol):
        return arm("GET", vol_path(pool, vol), quiet=True)[0]

    log("ac08-pool-before", pool=pool_tp("man-small"), db=db_counts())
    for label, extra in (("manual-missing", {}), ("manual-null", {"throughputMibps": None}),
                         ("manual-0.5", {"throughputMibps": 0.5}), ("manual-4500.5", {"throughputMibps": 4500.5}),
                         ("manual-string", {"throughputMibps": "10"}), ("manual-true", {"throughputMibps": True}),
                         ("manual-0", {"throughputMibps": 0}), ("manual-4501", {"throughputMibps": 4501})):
        s, h, b = arm("PUT", vol_path("man-small", "rej"), vol_body(f"{TOK}-rej", 1, "NFSv3", **extra))
        check(label, s, b, {"row_after": exists("man-small", "rej"), "async": h.get("azure-asyncoperation")})
    s, h, b = arm("PUT", vol_path("auto-prem", "rej"), vol_body(f"{TOK}-rej", 1, "NFSv3", throughputMibps=10))
    check("auto-create-with-value", s, b, {"row_after": exists("auto-prem", "rej"), "db": db_counts()})
    s, h, b = arm("PUT", vol_path("auto-prem", "rejn"), vol_body(f"{TOK}-rejn", 1, "NFSv3", throughputMibps=None))
    check("auto-create-with-null-accepted", s, b, {"row_after": exists("auto-prem", "rejn")})
    if s == 201:
        poll(h["azure-asyncoperation"])
        log("ac08-auto-null", limits=vol_limits("auto-prem", "rejn"), del_=delete_volume("auto-prem", "rejn"))
    fs_p1 = fsid("auto-prem", "p1")
    before = {"limits": vol_limits("auto-prem", "p1"), "tc": tc_summary(fs_p1, 0.062)}
    s, h, b = arm("PATCH", vol_path("auto-prem", "p1"), {"properties": {"throughputMibps": 10}})
    check("auto-patch-with-value", s, b, {"before": before, "after": {"limits": vol_limits("auto-prem", "p1"),
                                                                        "tc": tc_summary(fs_p1, 0.062)}})
    # 예산: man-small = Premium 2 TiB Manual = 128 MiB/s
    r1 = put_volume("man-small", "bud1", vol_body(f"{TOK}-bud1", 1, "NFSv3", 100))
    log("ac08-bud1", put=r1["status"], final=r1.get("final"), pool=pool_tp("man-small"))
    s, h, b = arm("PUT", vol_path("man-small", "bud2"), vol_body(f"{TOK}-bud2", 1, "NFSv3", 30))
    check("budget-create-over", s, b, {"row_after": exists("man-small", "bud2"), "pool": pool_tp("man-small")})
    s, h, b = arm("PUT", vol_path("man-small", "bud2"), vol_body(f"{TOK}-bud2", 1, "NFSv3", 28.0005))
    check("budget-create-over-by-0.0005-rounds-equal", s, b, {"row_after": exists("man-small", "bud2")})
    if s == 201:
        poll(h["azure-asyncoperation"])
        delete_volume("man-small", "bud2")
    s, h, b = arm("PUT", vol_path("man-small", "bud2"), vol_body(f"{TOK}-bud2", 1, "NFSv3", 28.001))
    check("budget-create-over-by-0.001", s, b, {"row_after": exists("man-small", "bud2")})
    r2 = put_volume("man-small", "bud2", vol_body(f"{TOK}-bud2", 1, "NFSv3", 28))
    log("ac08-budget-exact", put=r2["status"], final=r2.get("final"), limits=vol_limits("man-small", "bud2"),
        pool=pool_tp("man-small"), tc=tc_summary(fsid("man-small", "bud2"), 28))
    f1, f2 = fsid("man-small", "bud1"), fsid("man-small", "bud2")
    snap_before = {"bud1": vol_limits("man-small", "bud1"), "bud2": vol_limits("man-small", "bud2"),
                   "pool": pool_tp("man-small"), "tc1": tc_summary(f1, 100), "tc2": tc_summary(f2, 28)}
    s, h, b = arm("PATCH", vol_path("man-small", "bud2"), {"properties": {"throughputMibps": 29}})
    check("budget-patch-over", s, b)
    s, h, b = arm("PATCH", vol_path("man-small", "bud1"), {"properties": {"throughputMibps": 101}})
    check("budget-patch-over-2", s, b)
    body = get_volume("man-small", "bud2")
    props = dict(body["properties"])
    props["throughputMibps"] = 40
    s, h, b = arm("PUT", vol_path("man-small", "bud2"), {"location": LOC, "properties": props})
    check("budget-reput-over", s, b)
    s, h, b = arm("PATCH", pool_path("man-small"), {"properties": {"size": 1 * TIB}})
    check("pool-shrink", s, b, {"pool_after": pool_tp("man-small")})
    for label, val in (("patch-0.5", 0.5), ("patch-4500.5", 4500.5), ("patch-string", "10"), ("patch-true", True)):
        s, h, b = arm("PATCH", vol_path("man-small", "bud2"), {"properties": {"throughputMibps": val}})
        check(label, s, b)
    s, h, b = arm("PATCH", vol_path("man-small", "nope"), {"properties": {"throughputMibps": 0.5}})
    check("patch-missing-volume-0.5", s, b)
    snap_after = {"bud1": vol_limits("man-small", "bud1"), "bud2": vol_limits("man-small", "bud2"),
                  "pool": pool_tp("man-small"), "tc1": tc_summary(f1, 100), "tc2": tc_summary(f2, 28)}
    log("ac08-unchanged", before=snap_before, after=snap_after,
        same=json.dumps(snap_before, sort_keys=True, default=str) == json.dumps(snap_after, sort_keys=True, default=str))
    s, h, b = arm("PATCH", pool_path("man-small"), {"properties": {"qosType": "Auto"}})
    check("manual-to-auto", s, b, {"pool_after": pool_tp("man-small")})
    # 진행 중 볼륨 작업이 있을 때 Auto → Manual: 볼륨 생성(인스턴스 시작, 수 초) 중에 보낸다
    s0, h0, _ = arm("PUT", vol_path("sw-busy", "busy1"), vol_body(f"{TOK}-busy1", 1, "NFSv3"))
    s, h, b = arm("PATCH", pool_path("sw-busy"), {"properties": {"qosType": "Manual"}})
    check("auto-to-manual-busy", s, b, {"volume_put": s0, "pool_after": pool_tp("sw-busy")})
    if s0 == 201:
        poll(h0["azure-asyncoperation"])
    log("ac08-busy-after", pool=pool_tp("sw-busy"), vol=vol_limits("sw-busy", "busy1"))
    log("ac08-summary", results=out)


def step_ac09():
    c = client("c9")
    for vol, gib, proto in (("w80", 80, "NFSv3"), ("w1", 1, "NFSv4.1")):
        r = put_volume("sw-prem", vol, vol_body(f"{TOK}-{vol}", gib, proto))
        log("ac09-volume", vol=vol, put=r["status"], limits=vol_limits("sw-prem", vol))
    mount(c, mount_ip("sw-prem", "w80"), f"{TOK}-w80", "NFSv3", "/w80")
    fs80, fs1 = fsid("sw-prem", "w80"), fsid("sw-prem", "w1")
    before = {"w80": vol_limits("sw-prem", "w80"), "w1": vol_limits("sw-prem", "w1"), "pool": pool_tp("sw-prem"),
              "tc80": tc_summary(fs80, 5.0), "tc1": tc_summary(fs1, 0.062)}
    log("ac09-before", **before, lazyinit=lazyinit())
    mb = {rw: measure(c, fs80, rw, "/w80/f", 5.0, label=f"ac09 before {rw}") for rw in ("write", "read")}
    t0 = now()
    s, h, b = arm("PATCH", pool_path("sw-prem"), {"properties": {"qosType": "Manual"}})
    final, seen, t1 = poll(h["azure-asyncoperation"]) if s == 202 else (None, None, None)
    after = {"w80": vol_limits("sw-prem", "w80"), "w1": vol_limits("sw-prem", "w1"), "pool": pool_tp("sw-prem"),
             "tc80": tc_summary(fs80, 5.0), "tc1": tc_summary(fs1, 0.062)}
    log("ac09-switch", status=s, immediate=(b or {}).get("properties", {}).get("provisioningState"),
        final=(final or {}).get("status"), seen=seen, seconds=round((t1 or t0) - t0, 2), **after)
    ma = {rw: measure(c, fs80, rw, "/w80/f", 5.0, label=f"ac09 after {rw}") for rw in ("write", "read")}
    log("ac09-compare", before={k: v["median"] for k, v in mb.items()}, after={k: v["median"] for k, v in ma.items()})
    p = patch_volume("sw-prem", "w80", {"throughputMibps": 8})
    log("ac09-patch", patch=p, limits=vol_limits("sw-prem", "w80"), tc=tc_summary(fs80, 8), pool=pool_tp("sw-prem"))
    measure(c, fs80, "write", "/w80/f", 8.0, label="ac09 after patch 8 write")
    # 0.062 볼륨: GET 본문 그대로 재PUT (§9-5)
    body = get_volume("sw-prem", "w1")
    r = put_volume("sw-prem", "w1", {"location": body["location"], "tags": body.get("tags", {}),
                                     "properties": body["properties"]})
    log("ac09-reput-w1", put=r["status"], final=r.get("final"), limits=vol_limits("sw-prem", "w1"),
        tc=tc_summary(fs1, 0.062))
    drop_host_caches("after ac09")


def step_ac10a():
    """volumes/patch 지연 주입 중 Patching에서 anf-api SIGKILL → 다시 띄우면 Succeeded, 새 한도."""
    c = client("c1")
    fs = fsid("man-ultra", "m10")
    old = vol_limits("man-ultra", "m10")["throughputMibps"]
    svc("api-stop")
    svc("api-start", json.dumps({"volumes/patch": {"delaySeconds": 30}}))
    p = patch_volume("man-ultra", "m10", {"throughputMibps": 17}, wait=False)
    time.sleep(4)
    mid = {"limits": vol_limits("man-ultra", "m10"), "op": request(8080, "GET", p["async"])[2],
           "tc": tc_summary(fs, old)}
    svc("api-kill")
    time.sleep(1)
    svc("api-start")
    final, seen, t1 = poll(p["async"], timeout=200)
    log("ac10a", patch=p, old=old, mid=mid, final=final, seen=seen, seconds=round(t1 - p["t_sent"], 2),
        limits=vol_limits("man-ultra", "m10"), tc=tc_summary(fs, 17))
    measure(c, fs, "write", "/m10/f", 17, label="ac10a after restart write")


def step_ac10b():
    c = client("c1")
    fs = fsid("man-ultra", "m10")
    old = vol_limits("man-ultra", "m10")["throughputMibps"]
    svc("api-stop")
    svc("api-start", json.dumps({"volumes/patch": {"fail": True}}))
    p = patch_volume("man-ultra", "m10", {"throughputMibps": 9})
    log("ac10b-failed", patch=p, old=old, limits=vol_limits("man-ultra", "m10"), tc=tc_summary(fs, old))
    svc("api-stop")
    svc("api-start")
    p2 = patch_volume("man-ultra", "m10", {"throughputMibps": 9})
    log("ac10b-retry", patch=p2, limits=vol_limits("man-ultra", "m10"), tc=tc_summary(fs, 9))
    measure(c, fs, "write", "/m10/f", 9, label="ac10b after retry write")


# --- AC-07 수명 주기 ---


def ac07_window_report(s: Sampler, t_event: float, limit: float, label: str, t_mark=None) -> dict:
    """t_event(단계를 끝낸 시각) 뒤 I/O가 다시 흐른 때부터 15 s의 1초 창. eth0 창으로 제한 없는 흐름을 찾는다."""
    ifb = s.windows("ifb")
    eth = s.windows("eth")
    flowing = [t for t, v in ifb if t >= t_event and v > 0.3 * limit]
    resume = flowing[0] if flowing else None
    after = [v for t, v in ifb if resume is not None and resume <= t <= resume + SECONDS]
    over_eth = [(round(t - t_event, 2), v) for t, v in eth if t >= (t_mark or t_event) - 30 and v > 1.5 * limit]
    over_ifb = [(round(t - t_event, 2), v) for t, v in ifb if t >= t_event - 30 and v > limit * 1.01]
    hw = [v for t, v in s.htb_windows() if resume is not None and resume <= t <= resume + SECONDS]
    out = {"label": label, "limit": limit, "resume_after_s": round(resume - t_event, 2) if resume else None,
           "windows_15s": stats(after), "ratio_median": round(statistics.median(after) / limit, 4) if after else None,
           "htb_windows_15s": stats(hw),
           "series_rel": [(round(t - t_event, 2), v) for t, v in ifb if t_event - 20 <= t <= t_event + 40][::2],
           "over_1.5x_eth0": over_eth, "over_1.01_ifb0": over_ifb, "pids": s.pids(), "gaps": s.gaps()}
    log("ac07-window", **out)
    return out


def ac07_writer(c, seconds: int, box: dict, key: str) -> threading.Thread:
    t = threading.Thread(target=lambda: box.update({key: fio(c, [{"rw": "write", "path": "/lc/w", "size": "200M"}],
                                                             runtime=seconds, timeout=seconds + 600)}))
    t.start()
    return t


def step_ac07_setup():
    c = client("c7")
    r = put_volume("man-ultra", "lc", vol_body(f"{TOK}-lc", 2, "NFSv4.1", 10))
    log("ac07-volume", put=r["status"], limits=vol_limits("man-ultra", "lc"), tc=tc_summary(fsid("man-ultra", "lc"), 10))
    mount(c, mount_ip("man-ultra", "lc"), f"{TOK}-lc", "NFSv4.1", "/lc")
    log("ac07-prep", fio=fio(c, [{"rw": "write", "path": "/lc/w", "size": "200M"}]))
    s, h, b = arm("PUT", snap_path("man-ultra", "lc", "s1"), {"location": LOC})
    log("ac07-snapshot", status=s, final=poll(h["azure-asyncoperation"])[0] if s == 201 else None)


def step_ac07a():
    c = client("c7")
    fs = fsid("man-ultra", "lc")
    s = Sampler(fs)
    s.start()
    box = {}
    t = ac07_writer(c, 60, box, "w")
    time.sleep(15)
    t_mark = now()
    svc("agent-stop")
    svc("agent-start")
    t_ev = now()
    st = tc_summary(fs, 10)
    t.join(700)
    s.stop()
    log("ac07a", tc=st, fio=box.get("w"), agent_restart_s=round(t_ev - t_mark, 2))
    ac07_window_report(s, t_ev, 10, "a agent restart", t_mark)


def step_ac07b():
    c = client("c7")
    fs = fsid("man-ultra", "lc")
    old_pid = pid_of(fs)
    s = Sampler(fs)
    s.start()
    box = {}
    t = ac07_writer(c, 150, box, "w")
    time.sleep(12)
    t_mark = now()
    r = sh("docker", "stop", "-t", "30", inst(fs))
    t_stopped = now()
    svc("agent-stop")
    svc("agent-start")
    t_ev = now()
    st = tc_summary(fs, 10)
    t.join(900)
    s.stop()
    new_pid = pid_of(fs)
    log("ac07b", docker_stop_rc=r.returncode, stop_s=round(t_stopped - t_mark, 2), agent_ready_after_s=round(t_ev - t_mark, 2),
        old_pid=old_pid, new_pid=new_pid, tc=st, fio=box.get("w"),
        first_ifb_sample_new_pid=s.first_ifb(new_pid), first_sample_new_pid=next(
            (x[0] for x in s.samples if x[1] == new_pid), None))
    ac07_window_report(s, t_ev, 10, "b docker stop + agent restart (recover docker start)", t_mark)


def step_ac07c():
    c = client("c7")
    fs = fsid("man-ultra", "lc")
    old_pid = pid_of(fs)
    s = Sampler(fs)
    s.start()
    box = {}
    t = ac07_writer(c, 150, box, "w")
    time.sleep(12)
    t_mark = now()
    r = sh("docker", "rm", "-f", inst(fs))
    body = get_volume("man-ultra", "lc")
    pr = put_volume("man-ultra", "lc", {"location": body["location"], "tags": body.get("tags", {}),
                                        "properties": body["properties"]})
    t_ev = now()
    st = tc_summary(fs, 10)
    t.join(900)
    s.stop()
    new_pid = pid_of(fs)
    log("ac07c", rm_rc=r.returncode, reput=pr["status"], seen=pr.get("seen"), op_seconds=pr.get("op_seconds"),
        old_pid=old_pid, new_pid=new_pid, tc=st, fio=box.get("w"),
        first_sample_new_pid=next((x[0] for x in s.samples if x[1] == new_pid), None),
        first_ifb_sample_new_pid=s.first_ifb(new_pid))
    ac07_window_report(s, t_ev, 10, "c docker rm + re-PUT (docker run)", t_mark)


def step_ac07d():
    c = client("c7")
    fs = fsid("man-ultra", "lc")
    pid0 = pid_of(fs)
    s = Sampler(fs)
    s.start()
    box = {}
    t = ac07_writer(c, 75, box, "w")
    time.sleep(15)
    t_mark = now()
    sid = snap_path("man-ultra", "lc", "s1")
    st0, h, b = arm("POST", f"{vol_path('man-ultra', 'lc')}/revert", {"snapshotId": sid})
    final, seen, t_ev = poll(h["azure-asyncoperation"], interval=0.1) if st0 == 202 else (None, None, now())
    st = tc_summary(fs, 10)
    t.join(700)
    s.stop()
    ifb = s.windows("ifb")
    log("ac07d", revert=st0, final=(final or {}).get("status"), seen=seen, seconds=round(t_ev - t_mark, 2),
        pid_before=pid0, pid_after=pid_of(fs), tc=st, fio=box.get("w"),
        windows_around=[(round(x - t_mark, 2), v) for x, v in ifb if t_mark - 3 <= x <= t_ev + 6])
    ac07_window_report(s, t_ev, 10, "d revert while writing", t_mark)


def step_ac07e():
    c = client("c7")
    sid = snap_path("man-ultra", "lc", "s1")
    r = put_volume("man-ultra", "rm7", vol_body(f"{TOK}-rm7", 2, "NFSv4.1", 7, snapshotId=sid))
    fs = fsid("man-ultra", "rm7")
    log("ac07e-manual", put=r["status"], seen=r.get("seen"), location=r.get("location_header"),
        limits=vol_limits("man-ultra", "rm7"), tc=tc_summary(fs, 7),
        origin=get_volume("man-ultra", "rm7")["properties"].get("originatingResourceId"))
    mount(c, mount_ip("man-ultra", "rm7"), f"{TOK}-rm7", "NFSv4.1", "/rm7")
    measure(c, fs, "write", "/rm7/x", 7, label="ac07e restored manual 7 write")
    r = put_volume("auto-prem", "ra", vol_body(f"{TOK}-ra", 2, "NFSv3", snapshotId=sid))
    fa = fsid("auto-prem", "ra")
    log("ac07e-auto", put=r["status"], seen=r.get("seen"), limits=vol_limits("auto-prem", "ra"),
        tc=tc_summary(fa, 0.125), agent_qos=agent("GET", f"/api/storage/volumes/{fa}")[1].get("qos"))
    cx(c, "umount /rm7")
    for pool, vol in (("man-ultra", "rm7"), ("auto-prem", "ra")):
        log("ac07e-delete", vol=vol, result=delete_volume(pool, vol))


def step_ac07f():
    c = client("c7")
    cx(c, "umount -f /lc")
    fs = fsid("man-ultra", "lc")
    pid = pid_of(fs)
    ns_inode = os.readlink(f"/proc/{pid}/ns/net")
    ifb0 = host_ifbs()
    links0 = sh("ip", "-o", "link", "show").stdout.count("\n")
    r = delete_volume("man-ultra", "lc")
    lsns = sh("lsns", "-t", "net", "-o", "NS", "-n").stdout.split()
    log("ac07f", delete=r, pid=pid, pid_alive=Path(f"/proc/{pid}").exists(), netns=ns_inode,
        netns_still_listed=ns_inode.split("[")[1].rstrip("]") in lsns, host_ifbs_before=ifb0, host_ifbs_after=host_ifbs(),
        host_links_before=links0, host_links_after=sh("ip", "-o", "link", "show").stdout.count("\n"),
        instance=sh("docker", "ps", "-a", "--filter", f"name={inst(fs)}", "--format", "{{.Names}}").stdout.strip())


def step_cleanup():
    """이 검증이 만든 볼륨과 풀·계정, 클라이언트 컨테이너를 지운다."""
    for cli in sh("docker", "ps", "-a", "--format", "{{.Names}}").stdout.split():
        if cli.startswith(CLI):
            sh("docker", "rm", "-f", cli)
    s, _, body = arm("GET", f"{ACCT_PATH}/capacityPools", quiet=True)
    for pool in (body or {}).get("value", []) if s == 200 else []:
        pname = pool["name"].split("/")[-1]
        _, _, vb = arm("GET", f"{pool_path(pname)}/volumes", quiet=True)
        for v in vb.get("value", []):
            vname = v["name"].split("/")[-1]
            log("cleanup-volume", pool=pname, vol=vname, result=delete_volume(pname, vname))
        st, h, _ = arm("DELETE", pool_path(pname))
        if st == 202:
            poll(h["azure-asyncoperation"])
    st, h, _ = arm("DELETE", ACCT_PATH)
    if st == 202:
        poll(h["azure-asyncoperation"])
    log("cleanup-agent-volumes", records=agent("GET", "/api/storage/volumes")[1])


STEPS = {name[5:]: fn for name, fn in globals().items() if name.startswith("step_")}

if __name__ == "__main__":
    for name in sys.argv[1:]:
        log("step-start", step=name)
        t_start = now()
        try:
            STEPS[name]()
        except Exception as e:  # noqa: BLE001 - 단계 실패를 기록하고 멈춘다
            log("step-error", step=name, error=repr(e))
            raise
        finally:
            log("step-end", step=name, seconds=round(now() - t_start, 1))
