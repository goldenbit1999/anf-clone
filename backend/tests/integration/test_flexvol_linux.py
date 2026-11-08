"""볼륨 관리자를 실제 LVM·ext4와 볼륨 NFS 인스턴스(Docker, knfsd)로 확인한다 (볼륨 설계 §6.3 통합 층).

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
from storage_agent.runner import Runner

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


def client(ip, token, vers, script):
    """anf-vnet의 새 클라이언트 컨테이너에서 볼륨을 마운트하고 script를 실행한다.
    retry=0·soft·짧은 timeo: 거절을 2분 재시도하지 않고 바로 실패로 본다."""
    opts = f"vers={vers},retry=0,soft,timeo=20,retrans=1" + (",nolock" if vers == "3" else "")
    return sh("docker", "run", "--rm", "--privileged", "--network", NETWORK, "anf-nfs-client", "sh", "-c",
              f"mkdir /m && mount -t nfs -o {opts} {ip}:/{token} /m && {{ {script}; }}; rc=$?; umount /m; exit $rc")


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
    assert os.listdir(mp) == []  # lost+found를 지웠다
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
