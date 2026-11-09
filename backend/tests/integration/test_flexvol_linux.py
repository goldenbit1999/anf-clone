"""볼륨 관리자를 실제 LVM·ext4와 볼륨 NFS 인스턴스(Docker, knfsd)로 확인한다 (볼륨 설계 §6.3 통합 층,
스냅샷 설계 §6.2, 결정 1).

WSL Ubuntu에서 root로 실행한다. 먼저 `scripts/setup-wsl-dataplane.sh`로 이미지(anf-nfs-server, anf-nfs-client)와
네트워크(anf-vnet)를 준비한다. 실제 스토리지 루트(/var/lib/anf-clone)와 aggregate(VG anf)를 쓴다. agent도 같은
aggregate를 쓴다. 테스트는 자기가 만든 볼륨(경로 `it-<임의>`)만 지우고 aggregate는 남긴다.
클라이언트는 anf-vnet의 새 컨테이너이고 볼륨 IP로 마운트한다 (결정 17·18).

실행:
    wsl -d Ubuntu -u root -e bash -c 'cd <repo> && /home/<user>/.venvs/anf-clone/bin/python -m pytest backend/tests/integration'
"""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from storage_agent.flexvol import FlexVolManager, VolumeError
from storage_agent.nfs_instance import NETWORK, VOLUME_IPS, container_name
from storage_agent.runner import CommandError, Result, Runner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.dataplane,
    pytest.mark.skipif(sys.platform != "linux" or os.geteuid() != 0, reason="needs root on Linux (WSL Ubuntu)"),
]

ROOT = Path("/var/lib/anf-clone")
GIB = 1 << 30
VERSION = {"nfs3": "3", "nfs4.1": "4.1"}
REFUSED = {"nfs3": ["4.1"], "nfs4.1": ["3", "4.0"]}  # 볼륨마다 자기 버전만 켠다 (결정 16)


def sh(*argv, timeout=120):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def mount_options(vers):
    """retry=0·soft·짧은 timeo: 거절을 2분 재시도하지 않고 바로 실패로 본다."""
    return f"vers={vers},retry=0,soft,timeo=20,retrans=1" + (",nolock" if vers == "3" else "")


def client(ip, token, vers, script):
    """anf-vnet의 새 클라이언트 컨테이너에서 볼륨을 마운트하고 script를 실행한다."""
    return sh("docker", "run", "--rm", "--privileged", "--network", NETWORK, "anf-nfs-client", "sh", "-c",
              f"mkdir /m && mount -t nfs -o {mount_options(vers)} {ip}:/{token} /m && {{ {script}; }}; "
              "rc=$?; umount /m; exit $rc")


@pytest.fixture
def long_client():
    """마운트를 유지하는 클라이언트 컨테이너. 이름을 돌려주고 끝나면 지운다."""
    names = []

    def start(ip, token, vers, options=None):
        name = f"it-client-{uuid.uuid4().hex[:8]}"
        names.append(name)
        assert sh("docker", "run", "-d", "--name", name, "--privileged", "--network", NETWORK,
                  "anf-nfs-client", "sleep", "infinity").returncode == 0
        mounted = sh("docker", "exec", name, "sh", "-c",
                     f"mkdir /m && mount -t nfs -o {options or mount_options(vers)} {ip}:/{token} /m")
        assert mounted.returncode == 0, mounted.stderr
        return name

    yield start
    for name in names:
        sh("docker", "rm", "-f", name)


def container_ip(vid):
    fmt = f'{{{{(index .NetworkSettings.Networks "{NETWORK}").IPAddress}}}}'
    return sh("docker", "inspect", "-f", fmt, container_name(vid)).stdout.strip()


@pytest.fixture(scope="module")
def mgr():
    m = FlexVolManager(Runner())
    m.instances.check_host()
    m.recover()
    return m


@pytest.fixture
def vol(mgr):
    vid = str(uuid.uuid4())
    yield vid, f"it-{vid[:8]}"
    mgr.delete(vid)


def test_aggregate_is_a_thin_pool_and_idempotent(mgr):
    mgr.ensure_aggregate()
    seg = sh("lvs", "--noheadings", "-o", "segtype", "anf/aggr0")
    assert seg.returncode == 0, seg.stderr
    assert seg.stdout.strip() == "thin-pool"


@pytest.mark.parametrize("protocol", ["nfs3", "nfs4.1"])
def test_create_mount_delete(mgr, vol, protocol):
    vid, token = vol
    mp = ROOT / "ns" / token
    name = "vol_" + vid.replace("-", "")

    mgr.create(vid, f"/{token}", GIB, 770, protocol)

    record = mgr.record(vid)
    ip = record["data_lif"]["ip"]["address"]
    assert ip in VOLUME_IPS
    assert record == {"uuid": vid, "name": name, "size": GIB,
                      "nas": {"path": f"/{token}", "protocols": [protocol]},
                      "state": "online", "data_lif": {"ip": {"address": ip}}}
    assert oct(mp.stat().st_mode & 0o7777) == "0o770"
    assert os.listdir(mp) == [".snapshot"]  # lost+found를 지웠고, 스냅샷이 없어도 .snapshot이 있다
    fs = sh("findmnt", "-n", "-o", "FSTYPE,OPTIONS", "--mountpoint", str(mp)).stdout
    assert fs.startswith("ext4") and "nodelalloc" in fs
    assert sh("blkid", "-o", "value", "-s", "UUID", f"/dev/anf/{name}").stdout.strip() == vid
    assert container_ip(vid) == ip

    wrote = client(ip, token, VERSION[protocol], "echo hello > /m/f && stat -c %a /m")
    assert wrote.returncode == 0, wrote.stdout + wrote.stderr
    assert wrote.stdout.strip() == "770"
    assert (mp / "f").read_text() == "hello\n"
    for vers in REFUSED[protocol]:
        assert client(ip, token, vers, "true").returncode != 0, f"vers={vers} mounted a {protocol} volume"

    mgr.create(vid, f"/{token}", GIB, 770, protocol)  # 같은 요청은 멱등
    assert len(mgr.records(name=name)) == 1
    with pytest.raises(VolumeError):
        mgr.create(vid, f"/{token}", 2 * GIB, 770, protocol)

    mgr.delete(vid)

    assert mgr.record(vid) is None
    assert not mp.exists()
    assert sh("docker", "inspect", container_name(vid)).returncode != 0
    assert sh("lvs", f"anf/{name}").returncode != 0
    assert client(ip, token, VERSION[protocol], "true").returncode != 0


def test_recover_after_wsl_restart(mgr, vol):
    vid, token = vol
    mp = ROOT / "ns" / token
    mgr.create(vid, f"/{token}", GIB, 770, "nfs4.1")
    ip = mgr.record(vid)["data_lif"]["ip"]["address"]
    (mp / "f").write_text("hello")

    # agent가 없는 동안의 WSL 재시작을 흉내 낸다: 인스턴스는 멈춘 채 남고(재시작 정책 없음) 볼륨 마운트가 사라진다
    assert sh("docker", "stop", container_name(vid)).returncode == 0
    for _ in range(120):  # 인스턴스가 내려간 뒤에도 knfsd가 잠시 파일시스템을 잡는다
        if sh("umount", str(mp)).returncode == 0:
            break
        time.sleep(0.5)
    assert mgr.record(vid)["state"] == "offline"

    mgr.recover()

    assert mgr.record(vid)["state"] == "online"
    assert container_ip(vid) == ip  # 같은 IP로 다시 뜬다
    read = client(ip, token, "4.1", "cat /m/f")
    assert read.returncode == 0, read.stdout + read.stderr
    assert read.stdout == "hello"


# --- 스냅샷 (스냅샷 설계 §6.2) ---


def sha256(path):
    return sh("sha256sum", str(path)).stdout.split()[0]


SNAPSHOT_WRITES = [  # 스냅샷 안에서는 모두 실패해야 한다 (AC-04)
    "echo x >> /m/.snapshot/s1/a", "dd if=/dev/zero of=/m/.snapshot/s1/a bs=1 count=1 conv=notrunc",
    "touch /m/.snapshot/s1/new", "rm /m/.snapshot/s1/a", "mv /m/.snapshot/s1/a /m/.snapshot/s1/b",
    "mkdir /m/.snapshot/s1/x", "chmod 777 /m/.snapshot/s1/a",
    # .snapshot 자체도 바꿀 수 없다 (chattr +i)
    "touch /m/.snapshot/f", "mkdir /m/.snapshot/x", "mv /m/.snapshot /m/x", "chmod 700 /m/.snapshot",
    "rmdir /m/.snapshot/s1",
]


@pytest.mark.parametrize("protocol", ["nfs3", "nfs4.1"])
def test_snapshot_is_a_read_only_point_in_time_copy(mgr, vol, protocol, long_client):
    vid, token = vol
    mp = ROOT / "ns" / token
    vers = VERSION[protocol]
    mgr.create(vid, f"/{token}", GIB, 770, protocol)
    ip = mgr.record(vid)["data_lif"]["ip"]["address"]
    assert client(ip, token, vers, "echo one > /m/a && mkdir /m/d && echo two > /m/d/b").returncode == 0
    sid = str(uuid.uuid4())

    mgr.create_snapshot(vid, sid, "s1")

    lv = "snap_" + sid.replace("-", "")
    assert sh("lvs", "--noheadings", "-o", "lv_attr", f"anf/{lv}").stdout.strip().startswith("Vri")  # 읽기 전용 thin
    assert mgr.snapshot_record(vid, sid)["name"] == "s1"
    changed = client(ip, token, vers, "rm /m/a && echo changed > /m/d/b")
    assert changed.returncode == 0, changed.stderr
    read = client(ip, token, vers, "cat /m/.snapshot/s1/a /m/.snapshot/s1/d/b && ls -a /m && stat -c %d /m /m/.snapshot/s1")
    assert read.returncode == 0, read.stdout + read.stderr
    lines = read.stdout.split()
    assert lines[:2] == ["one", "two"]
    assert ".snapshot" in lines  # 클론 차이: v4.1 목록에도 보인다 (결정 16)
    assert lines[-1] != lines[-2]  # 스냅샷은 다른 파일시스템이다

    before = sha256(mp / ".snapshot" / "s1" / "a")
    tried = client(ip, token, vers, "; ".join(f'{c} 2>/dev/null && echo "ALLOWED: {c}"' for c in SNAPSHOT_WRITES) + "; true")
    assert "ALLOWED" not in tried.stdout, tried.stdout
    assert sha256(mp / ".snapshot" / "s1" / "a") == before
    assert sorted(os.listdir(mp / ".snapshot")) == ["s1"]

    # 클라이언트가 스냅샷 안에 cwd와 열린 파일을 둔 채로 지운다 (AC-06, S4 E4)
    holder = long_client(ip, token, vers)
    assert sh("docker", "exec", "-d", holder, "sh", "-c",
              "cd /m/.snapshot/s1 && exec 3< /m/.snapshot/s1/d/b && sleep 600").returncode == 0
    time.sleep(1)
    mgr.delete_snapshot(vid, sid)

    assert mgr.snapshot_record(vid, sid) is None
    assert sh("lvs", f"anf/{lv}").returncode != 0
    assert str(mp / ".snapshot" / "s1") not in sh("findmnt", "-rn", "-o", "TARGET").stdout.split()
    exports = (ROOT / "exports" / vid.replace("-", "") / "volume.exports").read_text()
    assert ".snapshot" not in exports
    gone = sh("docker", "exec", holder, "ls", "/m/.snapshot/s1")
    assert gone.returncode != 0 and "No such file or directory" in gone.stderr, gone.stderr
    mgr.delete_snapshot(vid, sid)  # 없는 스냅샷은 성공


def test_delete_volume_deletes_its_snapshots(mgr, vol):
    vid, token = vol
    mgr.create(vid, f"/{token}", GIB, 770, "nfs3")
    sids = [str(uuid.uuid4()) for _ in range(2)]
    for i, sid in enumerate(sids):
        mgr.create_snapshot(vid, sid, f"s{i}")

    mgr.delete(vid)

    for sid in sids:
        assert sh("lvs", "anf/snap_" + sid.replace("-", "")).returncode != 0
    assert not (ROOT / "ns" / token).exists()
    assert not (ROOT / "exports" / vid.replace("-", "")).exists()
    assert mgr.snapshot_records(vid) is None


@pytest.mark.parametrize("protocol", ["nfs3", "nfs4.1"])
def test_recover_snapshots_after_wsl_restart(mgr, vol, protocol):
    vid, token = vol
    mp = ROOT / "ns" / token
    mgr.create(vid, f"/{token}", GIB, 770, protocol)
    ip = mgr.record(vid)["data_lif"]["ip"]["address"]
    (mp / "f").write_text("before")
    mgr.create_snapshot(vid, str(uuid.uuid4()), "s1")
    (mp / "f").write_text("after")

    # WSL 재시작 흉내: 인스턴스가 멈추고 스냅샷과 볼륨 마운트가 사라진다
    assert sh("docker", "stop", container_name(vid)).returncode == 0
    for target in (mp / ".snapshot" / "s1", mp):
        for _ in range(120):
            if sh("umount", str(target)).returncode == 0:
                break
            time.sleep(0.5)

    mgr.recover()

    read = client(ip, token, VERSION[protocol], "cat /m/f /m/.snapshot/s1/f")
    assert read.returncode == 0, read.stdout + read.stderr
    assert read.stdout == "afterbefore"


# --- 되돌리기 (되돌리기 설계 §6.2, 결정 3·4·8·9) ---


def hard_options(vers):
    """되돌리는 동안의 멈춤을 재전송으로 기다리는 hard 마운트 (ANF가 권하는 마운트, S5)."""
    return f"vers={vers},hard" + (",nolock" if vers == "3" else "")


def volume_tags(vid):
    out = sh("lvs", "--noheadings", "-o", "lv_tags", "anf/vol_" + vid.replace("-", "")).stdout
    return out.strip().split(",")


def volume_lvs(vid):
    """그 볼륨의 LV 이름들 (되돌리는 동안에는 옛 LV와 새 LV `_new`가 함께 있다)."""
    out = sh("lvs", "--noheadings", "-o", "lv_name", "anf").stdout.split()
    return sorted(n for n in out if n.startswith("vol_" + vid.replace("-", "")))


def blocked(vid):
    """인스턴스 netns에 되돌리기 창의 입력 차단 규칙이 남아 있는가."""
    pid = sh("docker", "inspect", "-f", "{{.State.Pid}}", container_name(vid)).stdout.strip()
    return sh("nsenter", "-t", pid, "-n", "iptables", "-C", "INPUT", "-i", "eth0", "-j", "DROP").returncode == 0


def three_snapshots(mgr, vid, write):
    """a=one → s1 → a=two, b → s2 → a=three, c → s3 → a=four. write(script)는 클라이언트나 호스트에서 쓴다."""
    sids = [str(uuid.uuid4()) for _ in range(3)]
    write("echo one > a")
    mgr.create_snapshot(vid, sids[0], "s1")
    write("echo two > a && echo b > b")
    mgr.create_snapshot(vid, sids[1], "s2")
    write("echo three > a && echo c > c")
    mgr.create_snapshot(vid, sids[2], "s3")
    write("echo four > a && cat a")  # 클라이언트 캐시에 올린다
    return sids


@pytest.mark.parametrize("protocol", ["nfs3", "nfs4.1"])
def test_restore_reverts_under_a_mounted_client(mgr, vol, protocol, long_client):
    vid, token = vol
    vers = VERSION[protocol]
    mgr.create(vid, f"/{token}", GIB, 770, protocol)
    ip = mgr.record(vid)["data_lif"]["ip"]["address"]
    holder = long_client(ip, token, vers, hard_options(vers))

    def run(script):
        result = sh("docker", "exec", holder, "sh", "-c", f"cd /m && {script}")
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    s1, s2, s3 = three_snapshots(mgr, vid, run)
    before = mgr.snapshot_record(vid, s2)
    key = str(uuid.uuid4())

    mgr.restore(vid, s2, key)

    # 다시 마운트하지 않은 클라이언트가 s2 시점을 본다. 더 새 스냅샷 s3는 지워지고 s1·s2는 남는다
    assert run("cat a b && ls && ls .snapshot && cat .snapshot/s2/a").split() == [
        "two", "b", "a", "b", "s1", "s2", "two"]
    assert mgr.snapshot_record(vid, s2) == before  # 같은 uuid·이름·시각으로 다시 만들었다
    assert mgr.snapshot_record(vid, s3) is None
    assert sh("lvs", "anf/snap_" + s3.replace("-", "")).returncode != 0
    tags = volume_tags(vid)
    assert f"anf_rv_done={key}" in tags and not any(t.startswith("anf_rv_req=") for t in tags)
    assert not blocked(vid)

    # 같은 키는 아무것도 하지 않는다: 그 뒤에 쓴 파일이 남는다 (AC-08b)
    run("echo after > after")
    mgr.restore(vid, s2, key)
    assert run("cat after") == "after\n"
    # 앞선 되돌리기보다 오래된 s1로도 되돌릴 수 있다 (merge 방식은 여기서 "is not a mergeable logical volume").
    # 이제 s2가 s1보다 새 스냅샷이라 지워진다
    mgr.restore(vid, s1, str(uuid.uuid4()))
    assert run("cat a && ls && ls .snapshot").split() == ["one", "a", "s1"]
    # 볼륨 LV의 원본이 된 s1도 지울 수 있다. 볼륨은 그대로다
    mgr.delete_snapshot(vid, s1)
    assert run("cat a && ls -A .snapshot").split() == ["one"]


class FailAt(Runner):
    """program의 (skip + 1)번째 실행이 한 번 실패한다. 되돌리기가 그 단계에서 멈춘 상태를 만든다."""

    def __init__(self, program, skip=0):
        super().__init__()
        self.program, self.skip = program, skip

    def run(self, argv, check=True, input=None):
        if argv[0] == self.program:
            if self.skip == 0:
                self.program = None
                raise CommandError(argv, Result(5, "", "injected failure"))
            self.skip -= 1
        return super().run(argv, check=check, input=input)


@pytest.mark.parametrize("fail, skip, finish", [
    ("lvcreate", 0, "restore"),  # 새 볼륨 LV를 만들기 전 (창은 열지 않았다)
    ("mount", 0, "recover"),  # 창이 열린 채 새 LV를 마운트하기 전: agent 재시작 (AC-08c)
    ("mount", 0, "create"),  # 같은 상태를 볼륨 POST(보장)가 끝낸다
    ("lvremove", 1, "restore"),  # 창을 닫은 뒤 옛 볼륨 LV를 지우기 전 (첫 lvremove는 더 새 스냅샷 s3)
    ("lvrename", 0, "recover"),  # 옛 LV를 지운 뒤 이름을 넘겨받기 전
])
def test_restore_resumes_after_stopping_midway(mgr, vol, fail, skip, finish):
    vid, token = vol
    mp = ROOT / "ns" / token
    mgr.create(vid, f"/{token}", GIB, 770, "nfs3")
    ip = mgr.record(vid)["data_lif"]["ip"]["address"]
    _, s2, _ = three_snapshots(mgr, vid, lambda script: sh("sh", "-c", f"cd {mp} && {script}"))
    before = mgr.snapshot_record(vid, s2)
    key = str(uuid.uuid4())
    with pytest.raises(CommandError):
        FlexVolManager(FailAt(fail, skip)).restore(vid, s2, key)
    with pytest.raises(VolumeError, match="unfinished restore"):
        mgr.create_snapshot(vid, str(uuid.uuid4()), "s9")

    if finish == "restore":
        mgr.restore(vid, s2, key)
    elif finish == "recover":
        mgr.recover()
    else:
        mgr.create(vid, f"/{token}", GIB, 770, "nfs3")

    read = client(ip, token, "3", "cat /m/a && ls /m/.snapshot && cat /m/.snapshot/s2/a")
    assert read.returncode == 0, read.stdout + read.stderr
    assert read.stdout.split() == ["two", "s1", "s2", "two"]
    assert mgr.snapshot_record(vid, s2) == before
    assert volume_lvs(vid) == ["vol_" + vid.replace("-", "")]
    assert f"anf_rv_done={key}" in volume_tags(vid)
    assert not blocked(vid)


# --- NFSv4.1 인스턴스 재시작 (스냅샷 설계 결정 1, AC-15) ---


def restart_instance(mgr, vid, between=None):
    """인스턴스를 멈췄다 다시 띄우고 준비될 때까지 걸린 초를 돌려준다. between은 멈춘 동안 할 일이다."""
    assert sh("docker", "stop", "-t", "30", container_name(vid)).returncode == 0
    if between:
        between()
    t0 = time.monotonic()
    assert sh("docker", "start", container_name(vid)).returncode == 0
    mgr.instances.wait_ready(vid)
    return time.monotonic() - t0


def test_nfs41_instance_restarts_with_client_records(mgr, vol, long_client):
    vid, token = vol
    mgr.create(vid, f"/{token}", GIB, 770, "nfs4.1")
    ip = mgr.record(vid)["data_lif"]["ip"]["address"]
    lease_grace = sh("docker", "exec", container_name(vid), "cat", "/proc/fs/nfsd/nfsv4leasetime",
                     "/proc/fs/nfsd/nfsv4gracetime")
    assert lease_grace.stdout.split() == ["30", "45"]  # ONTAP 기본값

    # (a) 살아 있는 클라이언트: 마운트를 유지한 채 재시작해도 다시 마운트하지 않고 이어서 쓴다
    live = long_client(ip, token, "4.1")
    assert sh("docker", "exec", live, "sh", "-c", "echo one > /m/f").returncode == 0
    seconds = restart_instance(mgr, vid)
    print(f"live client: ready after {seconds:.1f} s")
    wrote = sh("docker", "exec", live, "sh", "-c", "echo two >> /m/f && cat /m/f")
    assert wrote.returncode == 0, wrote.stderr
    assert wrote.stdout.split() == ["one", "two"]

    # (b) 기록만 남은 클라이언트: 서버가 멈춘 동안 클라이언트가 사라지면 유예 기간(grace 45초)을 기다린다
    seconds = restart_instance(mgr, vid, between=lambda: sh("docker", "rm", "-f", live))
    print(f"dead client record: ready after {seconds:.1f} s")
    assert seconds < 150
    logs = sh("docker", "logs", container_name(vid))
    assert "grace period: waiting for" in logs.stdout + logs.stderr
    wrote = client(ip, token, "4.1", "echo three >> /m/f && cat /m/f")
    assert wrote.returncode == 0, wrote.stderr
    assert wrote.stdout.split() == ["one", "two", "three"]
