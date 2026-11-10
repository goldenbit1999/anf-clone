"""[verify, do not merge] FR-11 2부 AC-05 (_workspace/ci/02_main_design_dataplane.md §5).

ns 바인드 전파 수정(`NfsInstances.ensure_shared_ns`, 새 바인드에 --make-private 뒤 --make-rshared) 뒤에도
- 볼륨과 스냅샷 마운트가 호스트 마운트 표에 한 번씩만 있고,
- 인스턴스 컨테이너(rslave 바인드) 안에도 스냅샷 마운트가 보이고,
- 클라이언트에서 볼륨과 .snapshot/<이름>의 스냅샷 시점 내용이 읽히는지 본다.
호스트의 / 와 ns 바인드의 peer group(mountinfo의 shared:N)도 남긴다. / 가 shared인 호스트(러너)에서는 둘이 달라야 한다.
임시 브랜치 verify/fr11-ac03-fail에만 있다.
"""

from pathlib import Path

import pytest

import live_api
from dataplane_live import (create_volume, delete_volume, fsid_of, instance_name, mount_ip, note, NS, out, setup_pool, sh,
                            SKIP_UNLESS_ROOT, token)
from snapshot_live import create_snapshot

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT,
              pytest.mark.usefixtures("manual_data")]


def _mountinfo(path: str, *mount_points: str) -> list[str]:
    """mountinfo에서 마운트 지점(5번째 필드)이 주어진 것인 줄."""
    lines = Path(path).read_text().splitlines() if path.startswith("/") else sh("docker", "exec", path, "cat",
                                                                                "/proc/self/mountinfo").stdout.splitlines()
    return [ln for ln in lines if ln.split()[4] in mount_points]


def _peer(line: str) -> str | None:
    tags = [f for f in line.split(" - ")[0].split()[6:] if f.startswith("shared:")]
    return tags[0] if tags else None


def test_verify_fr11_ac05_single_mounts_and_client_view(agent, api, clients):
    api()
    setup_pool()
    tok = token("f11")
    v = create_volume("vf11", tok)
    ip = mount_ip(v)
    inst = instance_name(fsid_of(v))
    c = clients()
    c.mount(ip, tok, "3")
    w = c.run("echo before > /m/a.txt && sync")
    assert w.returncode == 0, out(w)
    create_snapshot("vf11", "s1")
    rd = c.run("echo after > /m/a.txt && sync && cat /m/a.txt && ls /m/.snapshot && cat /m/.snapshot/s1/a.txt")
    note("verify AC-05 client view", **out(rd))

    vol_mp, snap_mp = str(NS / tok), str(NS / tok / ".snapshot" / "s1")
    targets = sh("findmnt", "-rn", "-o", "TARGET").stdout.splitlines()
    host = _mountinfo("/proc/self/mountinfo", "/", str(NS), vol_mp, snap_mp)
    in_instance = _mountinfo(inst, "/export", f"/export/{tok}", f"/export/{tok}/.snapshot/s1")
    prop = sh("findmnt", "-no", "PROPAGATION", "--mountpoint", str(NS)).stdout.strip()
    root_prop = sh("findmnt", "-no", "PROPAGATION", "/").stdout.strip()
    counts = {"volume": targets.count(vol_mp), "snapshot": targets.count(snap_mp)}
    note("verify AC-05 host mounts", counts=counts, ns_propagation=prop, root_propagation=root_prop,
         host_mountinfo=host, instance_mountinfo=in_instance)

    c.run("umount /m")
    delete_volume("vf11")

    assert rd.returncode == 0, out(rd)
    assert rd.stdout.splitlines() == ["after", "s1", "before"]
    assert counts == {"volume": 1, "snapshot": 1}, (counts, host)
    assert "shared" in prop.split(",")
    root_line = next(ln for ln in host if ln.split()[4] == "/")
    ns_line = next(ln for ln in host if ln.split()[4] == str(NS))
    if "shared" in root_prop.split(","):
        assert _peer(ns_line) != _peer(root_line), host
    assert len([ln for ln in in_instance if ln.split()[4] == f"/export/{tok}/.snapshot/s1"]) == 1, in_instance
