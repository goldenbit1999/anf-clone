"""볼륨 실환경 검증 도구: storage agent, anf-api, 클라이언트 컨테이너를 다룬다 (볼륨 설계 §8).

테스트가 아니라 test_volume_*_live.py가 쓰는 도우미 모듈이다 (live_api.py와 같은 자리).
픽스처 agent·api·clients는 e2e conftest.py가 가져와 등록한다.

WSL Ubuntu에서 root로 실행한다.
- storage agent(root, 127.0.0.1:8090)는 agent 픽스처가 시험 파일마다 직접 띄우고 멈춘다.
  AC-11·AC-12가 agent를 멈추고 다시 띄워야 하기 때문이다.
- anf-api는 setpriv로 일반 사용자 권한으로 띄운다 (§8 공통 조건). 사용자는 ANF_E2E_USER, 없으면 venv 소유자다.
  agent 주소는 anf-api의 기본값(http://127.0.0.1:8090)을 그대로 쓴다.
- 상태 DB는 그 사용자가 만든 /tmp 디렉터리에 두고, 테스트가 DB를 읽을 때도 그 사용자 권한으로 읽는다.
  root가 WAL 파일(-wal, -shm)을 만들면 anf-api가 같은 DB를 다시 열지 못하기 때문이다.
- 클라이언트는 anf-vnet의 anf-nfs-client privileged 컨테이너다. 마운트 IP는 GET의 mountTargets[0].ipAddress다.
- 이번 실행이 만든 볼륨의 경로는 모두 `e2ev<임의 4자리>-`로 시작한다. 시험 파일이 끝나면 agent API로 남은 것을 지운다.
"""

import http.client
import ipaddress
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

import live_api
from live_api import (
    LOC, RG, SUB, TIB, V, Server, call, create_account, create_pool, db_operations, db_resources, poll,
    pool_path,
)

SKIP_UNLESS_ROOT = pytest.mark.skipif(sys.platform != "linux" or os.geteuid() != 0,
                                      reason="needs root on Linux (WSL Ubuntu)")

REPO = live_api.REPO_ROOT
NS = Path("/var/lib/anf-clone/ns")
NETWORK = "anf-vnet"
AGENT_HOST, AGENT_PORT = "127.0.0.1", 8090
GIB = 1 << 30
POLL = 60.0  # §8 공통 조건: 제한 시간 60초 (지연을 주입했으면 지연 + 60초)
VOLUME_NET = ipaddress.ip_network("172.30.0.128/25")
VOLUME_IPS = [f"172.30.0.{i}" for i in range(129, 255)]
SUBNET_ID = (f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Network"
             "/virtualNetworks/e2e-vnet/subnets/anf")
VOLUME_TYPE = "Microsoft.NetApp/netAppAccounts/capacityPools/volumes"
RUN = uuid.uuid4().hex[:4]
TOKEN_PREFIX = f"e2ev{RUN}"
CLIENT_PREFIX = "anfe2e-cli-"
REJECT_OPTS = "retry=0,soft,timeo=20,retrans=1"  # 거절은 2분 재시도하지 않고 바로 실패로 본다
ACCT, POOL = "e2e-vol-acct", "e2e-vol-pool"
# 데이터를 쓰는 e2e 파일의 볼륨 한도 (처리량 설계 결정 17). 1 GiB Premium Auto 볼륨은 0.062 MiB/s라 기존 데이터 시험
# (채우기 1,229 MiB, 기록 16 MiB 등)이 몇 시간 걸린다. 4 TiB Premium Manual 풀(256 MiB/s)에 볼륨 4개가 들어간다
DATA_MIBPS = 64.0
_manual = {"on": False}


@pytest.fixture(scope="module")
def manual_data():
    """이 픽스처를 쓰는 시험 파일에서는 setup_pool이 Manual 풀을 만들고, vol_body가 throughputMibps(DATA_MIBPS)를
    넣는다. 그래서 회귀 데이터도 tc 한도를 지난다. Auto 풀에 만들 때는 throughputMibps=None(null은 무시된다)을 준다."""
    _manual["on"] = True
    yield
    _manual["on"] = False


def note(tag: str, **data) -> None:
    """판정 근거를 출력과 ANF_E2E_LOG에 남긴다."""
    print(f"\n[{tag}] " + json.dumps(data, ensure_ascii=False, default=str))
    live_api.log_event("evidence", tag=tag, **data)


def sh(*argv, timeout=180) -> subprocess.CompletedProcess:
    env = {**os.environ, "LVM_SUPPRESS_FD_WARNINGS": "1"}
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, env=env)


def out(r: subprocess.CompletedProcess) -> dict:
    return {"rc": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def token(tag: str) -> str:
    return f"{TOKEN_PREFIX}-{tag}"


# --- 사용자 권한 ---


def e2e_user():
    import pwd  # Linux 전용. CI(Windows 수집 포함)에서 import가 깨지지 않게 여기서 부른다

    name = os.environ.get("ANF_E2E_USER")
    entry = pwd.getpwnam(name) if name else pwd.getpwuid(Path(sys.prefix).stat().st_uid)
    assert entry.pw_uid != 0, "anf-api must run as a regular user: set ANF_E2E_USER"
    return entry


@contextmanager
def as_user():
    u = e2e_user()
    os.setegid(u.pw_gid)
    os.seteuid(u.pw_uid)
    try:
        yield
    finally:
        os.seteuid(0)
        os.setegid(0)


def proc_uid(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])
    raise AssertionError("no Uid line")


def db_ops(db) -> list[dict]:
    with as_user():
        return db_operations(db)


def db_rows(db) -> list[dict]:
    with as_user():
        return db_resources(db)


def ops_for(db, rid: str) -> list[dict]:
    return [o for o in db_ops(db) if o["resource_id"].lower() == rid.lower()]


class ApiServer(Server):
    """anf-api를 일반 사용자 권한으로 띄운다. min_gib가 None이면 ANF_MIN_VOLUME_SIZE_GIB를 넣지 않는다."""

    def __init__(self, db_path, faults=None, min_gib=1):
        super().__init__(db_path, faults=faults)
        self.min_gib = min_gib

    def launch(self) -> None:
        deadline = time.monotonic() + 10
        while live_api.port_open():
            assert time.monotonic() < deadline, f"{live_api.HOST}:{live_api.PORT} is already in use"
            time.sleep(0.2)
        u = e2e_user()
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANF_")}
        env.update(HOME=u.pw_dir, USER=u.pw_name, LOGNAME=u.pw_name, PYTHONDONTWRITEBYTECODE="1",
                   ANF_API_DB=str(self.db_path))
        if self.fault_injection is not None:
            env["ANF_FAULT_INJECTION"] = self.fault_injection
        if self.min_gib is not None:
            env["ANF_MIN_VOLUME_SIZE_GIB"] = str(self.min_gib)
        cmd = ["setpriv", f"--reuid={u.pw_uid}", f"--regid={u.pw_gid}", "--init-groups", "--",
               live_api.PYTHON, "-m", "uvicorn", "--factory", "anf_api.arm_app:create_app",
               "--app-dir", "backend", "--host", live_api.HOST, "--port", str(live_api.PORT)]
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=self._log, stderr=subprocess.STDOUT)
        live_api.log_event("server-launch", pid=self.proc.pid, cmd=cmd, db=str(self.db_path),
                           fault_injection=self.fault_injection, min_gib=self.min_gib)


@pytest.fixture
def api():
    """anf-api를 띄우는 팩토리. 같은 테스트 안의 서버는 db를 넘기지 않으면 같은 DB를 쓴다."""
    servers = []
    dbdir = None

    def start(faults=None, min_gib=1, db=None):
        nonlocal dbdir
        if db is None:
            if dbdir is None:
                with as_user():
                    dbdir = Path(tempfile.mkdtemp(prefix="anf-vol-e2e-"))
            db = dbdir / "anf.db"
        srv = ApiServer(db, faults=faults, min_gib=min_gib)
        servers.append(srv)
        srv.start()
        return srv

    yield start
    for srv in reversed(servers):
        srv.stop()


# --- storage agent ---


def agent_call(method: str, path: str, body=None, timeout=60) -> tuple[int, object]:
    conn = http.client.HTTPConnection(AGENT_HOST, AGENT_PORT, timeout=timeout)
    try:
        data = None if body is None else json.dumps(body).encode()
        headers = {"content-type": "application/json"} if body is not None else {}
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)
    finally:
        conn.close()


def agent_job(href: str, timeout=120) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status, job = agent_call("GET", href)
        assert status == 200, (status, job)
        if job["state"] in ("success", "failure"):
            return job
        assert time.monotonic() < deadline, job
        time.sleep(0.2)


def agent_port_open() -> bool:
    try:
        with socket.create_connection((AGENT_HOST, AGENT_PORT), timeout=0.5):
            return True
    except OSError:
        return False


class Agent:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.proc: subprocess.Popen | None = None
        self._log = None

    def start(self, timeout=120) -> None:
        assert not agent_port_open(), f"{AGENT_HOST}:{AGENT_PORT} is already in use"
        self._log = open(self.log_path, "ab")
        cmd = [live_api.PYTHON, "-m", "uvicorn", "--factory", "storage_agent.agent_app:create_app",
               "--app-dir", "backend", "--host", AGENT_HOST, "--port", str(AGENT_PORT)]
        self.proc = subprocess.Popen(cmd, cwd=REPO, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                     stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + timeout
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"agent exited with {self.proc.returncode}:\n{self.text()[-4000:]}")
            if agent_port_open() and agent_call("GET", "/api/storage/volumes")[0] == 200:
                live_api.log_event("agent-ready", pid=self.proc.pid)
                return
            assert time.monotonic() < deadline, f"agent not ready:\n{self.text()[-4000:]}"
            time.sleep(0.2)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        self.proc.send_signal(signal.SIGKILL)
        self.proc.wait(10)
        self._close()

    def stop(self) -> None:
        if self.running():
            self.proc.terminate()
            try:
                self.proc.wait(30)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        self._close()

    def text(self) -> str:
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def _close(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None


@pytest.fixture(scope="module")
def agent(tmp_path_factory):
    note("baseline", dataplane=dataplane(), thin_data_percent=thin_data_percent())
    watcher = InstanceLogs()
    watcher.start()
    a = Agent(live_api.log_file("agent.log") or tmp_path_factory.mktemp("agent") / "agent.log")
    a.start()
    note("agent", log=str(a.log_path), pid=a.proc.pid)
    yield a
    if not a.running():
        a.start()
    # 안전망: 실패한 테스트가 남긴, 이번 실행의 볼륨을 agent로 지운다
    leftovers = []
    status, listing = agent_call("GET", "/api/storage/volumes")
    for rec in listing["records"]:
        if rec["nas"]["path"].startswith("/" + TOKEN_PREFIX):
            leftovers.append(rec["nas"]["path"])
            st, reply = agent_call("DELETE", f"/api/storage/volumes/{rec['uuid']}")
            agent_job(reply["job"]["_links"]["self"]["href"], 180)
    a.stop()
    note("teardown", leftovers_deleted=leftovers, dataplane=dataplane(), thin_data_percent=thin_data_percent())
    note("instance logs", **watcher.finish())


# --- 데이터 플레인 관찰 (root) ---


def lv_name(fsid: str) -> str:
    return "vol_" + fsid.replace("-", "")


def instance_name(fsid: str) -> str:
    return "anf-nfs-" + fsid.replace("-", "")


def lvs_volumes() -> dict:
    r = sh("lvs", "--reportformat", "json", "--units", "b", "--nosuffix", "-o", "lv_name,lv_size,lv_tags", "anf")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)["report"][0]["lv"]
    return {row["lv_name"]: {"size": int(row["lv_size"]), "tags": row["lv_tags"]}
            for row in rows if row["lv_name"] != "aggr0"}


def thin_data_percent() -> str:
    return sh("lvs", "--noheadings", "-o", "data_percent", "anf/aggr0").stdout.strip()


def instances() -> dict:
    r = sh("docker", "ps", "-a", "--filter", "name=^anf-nfs-", "--format", "{{.Names}} {{.State}}")
    return dict(line.split(" ", 1) for line in r.stdout.splitlines() if line)


def instance_ip(fsid: str) -> str:
    fmt = f'{{{{(index .NetworkSettings.Networks "{NETWORK}").IPAddress}}}}'
    return sh("docker", "inspect", "-f", fmt, instance_name(fsid)).stdout.strip()


def host_mounted(token_: str) -> bool:
    return sh("findmnt", "--mountpoint", str(NS / token_)).returncode == 0


def dataplane() -> dict:
    return {"lvs": sorted(lvs_volumes()), "instances": instances(),
            "ns": sorted(os.listdir(NS)) if NS.exists() else None}


def volume_state(fsid: str, token_: str) -> dict:
    """한 볼륨의 데이터 플레인 단계별 상태 (결정 10의 순서)."""
    lv = lv_name(fsid)
    blkid = sh("blkid", "-o", "value", "-s", "TYPE", f"/dev/anf/{lv}")
    return {"lv": lv in lvs_volumes(), "fs": blkid.stdout.strip() or f"rc={blkid.returncode}",
            "mounted": host_mounted(token_), "instance": instances().get(instance_name(fsid))}


# 진입점은 NFSv4 유예 기간이 끝난(v4_end_grace = Y) 뒤에만 준비 표시를 만들고 serving 줄을 남긴다.
# 추적이 늦게 붙으면 knfsd를 다시 띄우고 재시작 줄을 남긴다 (1회차 AC-03 FAIL의 수정)
READY_FILE = "/run/anf-ready"
SERVING_LINE = "anf-nfs: serving /"
RESTART_LINE = "client tracking did not start (attempt"


def instance_status(fsid: str) -> dict:
    """인스턴스가 준비됐는가: 준비 표시, 유예 기간 종료, serving 줄, knfsd 재시작 횟수."""
    name = instance_name(fsid)
    logs = sh("docker", "logs", name)
    lines = (logs.stdout + logs.stderr).splitlines()
    return {"ready": sh("docker", "exec", name, "test", "-e", READY_FILE).returncode == 0,
            "v4_end_grace": sh("docker", "exec", name, "cat", "/proc/fs/nfsd/v4_end_grace").stdout.strip(),
            "serving": next((x for x in reversed(lines) if SERVING_LINE in x), ""),
            "restarts": sum(RESTART_LINE in x for x in lines)}


def instance_ok(st: dict) -> bool:
    return st["ready"] and st["v4_end_grace"] == "Y" and st["serving"] != ""


class InstanceLogs(threading.Thread):
    """시험 파일 동안 뜬 모든 인스턴스의 진입점 로그를 지워지기 전에 모은다(0.3초마다).

    knfsd 재시작 횟수는 dmesg가 아니라 이 로그로 센다. dmesg의 추적 실패 줄은 rate limit으로 빠질 수 있다.
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.logs: dict[str, str] = {}
        self._done = threading.Event()

    def run(self) -> None:
        while not self._done.is_set():
            self.collect()
            self._done.wait(0.3)

    def collect(self) -> None:
        ps = sh("docker", "ps", "-a", "--filter", "name=^anf-nfs-", "--format", "{{.ID}} {{.Names}}")
        for line in ps.stdout.splitlines():
            cid, name = line.split()
            logs = sh("docker", "logs", cid)
            if logs.returncode == 0:
                self.logs[f"{name}@{cid}"] = logs.stdout + logs.stderr

    def finish(self) -> dict:
        self._done.set()
        self.join(30)
        self.collect()
        per = {}
        for key, text in sorted(self.logs.items()):
            lines = text.splitlines()
            per[key] = {"serving": sum(SERVING_LINE in x for x in lines),
                        "restarts": sum(RESTART_LINE in x for x in lines),
                        "gave_up": any("giving up" in x for x in lines)}
        return {"instances": len(per), "starts": sum(x["serving"] for x in per.values()),
                "restarts": sum(x["restarts"] for x in per.values()),
                "with_restart": sorted(k for k, x in per.items() if x["restarts"]),
                "gave_up": sorted(k for k, x in per.items() if x["gave_up"]),
                "never_served": sorted(k for k, x in per.items() if not x["serving"]), "per_instance": per}


# --- 클라이언트 컨테이너 ---


def mount_opts(vers: str, opts: str) -> str:
    return ",".join(x for x in (f"vers={vers}", opts, "nolock" if vers == "3" else "") if x)


def one_shot(ip: str, token_: str, vers: str, script: str = "true", opts: str = REJECT_OPTS):
    """anf-vnet의 새 클라이언트 컨테이너에서 마운트하고 script를 실행한다."""
    o = mount_opts(vers, opts)
    return sh("docker", "run", "--rm", "--privileged", "--network", NETWORK, "anf-nfs-client", "sh", "-c",
              f"mkdir /m && mount -t nfs -o {o} {ip}:/{token_} /m && {{ {script}; }}; rc=$?; "
              "umount /m 2>/dev/null; exit $rc")


class Client:
    """오래 사는 클라이언트 컨테이너. 마운트를 유지한 채 여러 명령을 실행한다."""

    def __init__(self):
        self.name = CLIENT_PREFIX + uuid.uuid4().hex[:8]
        r = sh("docker", "run", "-d", "--privileged", "--network", NETWORK, "--name", self.name,
               "anf-nfs-client", "sleep", "3600")
        assert r.returncode == 0, r.stderr

    def run(self, script: str, timeout=180):
        return sh("docker", "exec", self.name, "sh", "-c", script, timeout=timeout)

    def mount(self, ip: str, token_: str, vers: str, mp: str = "/m", opts: str = "") -> None:
        o = mount_opts(vers, opts)
        r = self.run(f"mkdir -p {mp} && mount -t nfs -o {o} {ip}:/{token_} {mp}")
        assert r.returncode == 0, out(r)

    def pid(self) -> str:
        return sh("docker", "inspect", "-f", "{{.State.Pid}}", self.name).stdout.strip()

    def remove(self) -> None:
        sh("docker", "rm", "-f", self.name, timeout=180)


@pytest.fixture
def clients():
    made = []

    def make() -> Client:
        c = Client()
        made.append(c)
        return c

    yield make
    for c in made:
        c.remove()


# --- ARM 볼륨 ---


def vol_path(acct: str, pool: str, name: str) -> str:
    return f"{pool_path(acct, pool)}/volumes/{name}"


def vol_url(acct: str, pool: str, name: str) -> str:
    return f"{vol_path(acct, pool, name)}?{V}"


def vol_list_url(acct: str, pool: str) -> str:
    return f"{pool_path(acct, pool)}/volumes?{V}"


def vol_body(token_: str | None, size: int | None = GIB, protocols=None, subnet=SUBNET_ID, **extra) -> dict:
    props = {}
    if token_ is not None:
        props["creationToken"] = token_
    if size is not None:
        props["usageThreshold"] = size
    if subnet is not None:
        props["subnetId"] = subnet
    if protocols is not None:
        props["protocolTypes"] = protocols
    if _manual["on"]:
        props["throughputMibps"] = DATA_MIBPS
    props.update(extra)
    return {"location": LOC, "properties": props}


def create_volume(name: str, token_: str, size: int = GIB, protocols=None, acct=ACCT, pool=POOL) -> dict:
    r = call("PUT", vol_url(acct, pool, name), vol_body(token_, size, protocols))
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    assert final["status"] == "Succeeded", (final, seen)
    g = call("GET", vol_url(acct, pool, name))
    assert g.status == 200, g.raw
    return g.json()


def delete_volume(name: str, acct=ACCT, pool=POOL, timeout=150) -> dict:
    d = call("DELETE", vol_url(acct, pool, name))
    assert d.status in (202, 204), d.raw
    if d.status == 204:
        return {}
    final, seen = poll(d.headers["azure-asyncoperation"], timeout)
    assert final["status"] == "Succeeded", (final, seen)
    return final


def mount_ip(v: dict) -> str:
    return v["properties"]["mountTargets"][0]["ipAddress"]


def fsid_of(v: dict) -> str:
    return v["properties"]["fileSystemId"]


def error_of(r) -> tuple:
    """(상태 코드, error.code, error.message). 오류 본문이 아니면 code 자리에 None을 둔다."""
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or "error" not in body:
        return r.status, None, r.raw.decode(errors="replace")[:300]
    return r.status, body["error"]["code"], body["error"]["message"]


def default_rule(nfsv3: bool, nfsv41: bool) -> dict:
    # 녹화 V1의 기본 export 규칙. nfsv41 쪽은 결정 16 [추론]
    return {"ruleIndex": 1, "unixReadOnly": False, "unixReadWrite": True, "cifs": False,
            "nfsv3": nfsv3, "nfsv41": nfsv41, "allowedClients": "0.0.0.0/0",
            "kerberos5ReadOnly": False, "kerberos5ReadWrite": False, "kerberos5iReadOnly": False,
            "kerberos5iReadWrite": False, "kerberos5pReadOnly": False, "kerberos5pReadWrite": False,
            "hasRootAccess": True, "chownMode": "Restricted"}


def setup_pool(size=4 * TIB, acct=ACCT, pool=POOL) -> None:
    create_account(acct)
    create_pool(acct, pool, size, "Premium", qos_type="Manual" if _manual["on"] else None)
