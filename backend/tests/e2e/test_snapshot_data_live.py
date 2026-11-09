"""스냅샷 e2e (2/3): 클라이언트에서 관찰한 데이터 효과 (스냅샷 설계 §8).

- AC-02 NFSv3 / AC-03 NFSv4.1: 지우고 덮어쓴 파일을 `.snapshot/<이름>/`에서 스냅샷 시점 내용으로 읽는다
- AC-04 스냅샷 안과 `.snapshot` 자체는 root 클라이언트도 바꿀 수 없다. 새 볼륨에도 빈 `.snapshot`이 있다
- AC-05 스냅샷마다 자기 시점이다. 계속 쓰는 동안 만든 스냅샷의 파일시스템이 깨끗하다
- AC-06 클라이언트가 안에 있는 스냅샷의 DELETE, 그 뒤 클라이언트·호스트 관찰, 같은 이름으로 다시 만들기
- AC-10 스냅샷이 남은 볼륨의 DELETE가 스냅샷도 지운다

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_snapshot_data_live.py -v -s'
"""

import os
import subprocess
import time
import uuid

import pytest

import live_api
from live_api import call, poll
from dataplane_live import (
    ACCT, create_volume, db_rows, delete_volume, error_of, fsid_of, instance_name, instances, lv_name,
    lvs_volumes, mount_ip, note, NS, one_shot, out, POOL, setup_pool, sh, SKIP_UNLESS_ROOT, token, vol_url,
)
from snapshot_live import (
    create_snapshot, EXPORTS, exported_paths, exports_file, host_files, instance_etab, lsattr_d, NOT_FOUND,
    op_seconds, SNAPDIR_WRITES, snap_list_url, snap_lv_name, snap_lvs, snap_mounts, snap_url, SNAPSHOT_TYPE,
    SNAPSHOT_WRITES, thin_used_bytes, vol_snap_lvs,
)

# 데이터를 쓰므로 Manual 풀과 DATA_MIBPS 한도로 볼륨을 만든다 (처리량 설계 결정 17)
pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT,
              pytest.mark.usefixtures("manual_data")]

PROTOCOLS = [("NFSv3", "3"), ("NFSv4.1", "4.1")]
MIB = 1 << 20


def used_bytes(df_line: str) -> int:
    return int(df_line.split()[2])


# --- AC-02, AC-03 ---


@pytest.mark.parametrize("ac,protocol,vers", [("AC-02", "NFSv3", "3"), ("AC-03", "NFSv4.1", "4.1")])
def test_ac02_ac03_snapshot_keeps_point_in_time_content(agent, api, clients, ac, protocol, vers):
    api()
    setup_pool()
    tok = token("s" + ac.lower().replace("-", ""))
    v = create_volume("vs2", tok, protocols=[protocol])
    ip, fsid = mount_ip(v), fsid_of(v)
    a = clients()
    a.mount(ip, tok, vers)
    content_a, content_b = f"A-{uuid.uuid4().hex}", f"B-{uuid.uuid4().hex}"
    w = a.run(f"echo {content_a} > /m/A && mkdir /m/d && echo {content_b} > /m/d/B && "
              "dd if=/dev/urandom of=/m/big bs=1M count=64 conv=fsync 2>/dev/null && sync && "
              "sha256sum /m/big | cut -d' ' -f1 && df -B1 /m | tail -1")
    assert w.returncode == 0, out(w)
    big_sha, df_before = w.stdout.splitlines()
    thin0 = thin_used_bytes()

    s, final = create_snapshot("vs2", "S")
    thin1 = thin_used_bytes()
    ch = a.run("rm /m/A && echo changed > /m/d/B && dd if=/dev/urandom of=/m/big bs=1M count=64 conv=fsync,notrunc "
               "2>/dev/null && sync && df -B1 /m | tail -1")
    assert ch.returncode == 0, out(ch)
    thin2 = thin_used_bytes()
    df_after = ch.stdout.strip()

    rd_a = a.run("cat /m/.snapshot/S/A")
    rd_b = a.run("cat /m/.snapshot/S/d/B")
    big = a.run("sha256sum /m/.snapshot/S/big | cut -d' ' -f1; sha256sum /m/big | cut -d' ' -f1")
    ls = a.run("ls -a /m")
    dev = a.run("stat -c %d /m /m/.snapshot/S")
    active = a.run("test ! -e /m/A && cat /m/d/B")
    host = {"A": (NS / tok / ".snapshot" / "S" / "A").read_text(), "d/B": (NS / tok / ".snapshot" / "S" / "d" / "B").read_text()}
    b = clients()
    b.mount(ip, tok, vers)
    rd_other = b.run("cat /m/.snapshot/S/A /m/.snapshot/S/d/B && grep ' /m' /proc/mounts")
    note(f"{ac} {protocol}", snapshot_seconds=op_seconds(final), client_a={"A": out(rd_a), "d/B": out(rd_b)},
         big_sha={"before": big_sha, "snapshot_and_active": big.stdout.split()}, ls_a=ls.stdout.split(),
         st_dev=dev.stdout.split(), active=out(active), host_snapshot_mount=host, client_b=out(rd_other),
         space={"thin_used_before_snapshot": thin0, "after_snapshot": thin1, "after_overwrite_64MiB": thin2,
                "snapshot_added_bytes": thin1 - thin0, "overwrite_added_bytes": thin2 - thin1,
                "client_df_used_before": used_bytes(df_before), "client_df_used_after": used_bytes(df_after)})
    assert rd_a.returncode == 0 and rd_a.stdout == content_a + "\n", out(rd_a)
    assert rd_b.returncode == 0 and rd_b.stdout == content_b + "\n", out(rd_b)
    assert big.stdout.split()[0] == big_sha != big.stdout.split()[1]
    assert ".snapshot" in ls.stdout.split()
    devs = dev.stdout.split()
    assert dev.returncode == 0 and len(devs) == 2 and devs[0] != devs[1]
    assert active.returncode == 0 and active.stdout == "changed\n"
    assert host == {"A": content_a + "\n", "d/B": content_b + "\n"}
    assert rd_other.returncode == 0 and rd_other.stdout.splitlines()[:2] == [content_a, content_b]
    assert f"vers={vers}" in rd_other.stdout
    # 클론 차이 (결정 16 (4)): 덮어쓴 64 MiB는 씬 풀에서 새로 나가고, 볼륨 df의 사용량에는 잡히지 않는다
    assert vol_snap_lvs(fsid) == [snap_lv_name(s["properties"]["snapshotId"])]
    assert thin2 - thin1 >= 60 * MIB
    assert abs(used_bytes(df_after) - used_bytes(df_before)) < 8 * MIB

    for c in (a, b):
        c.remove()
    delete_volume("vs2")


# --- AC-04 ---


@pytest.mark.parametrize("protocol,vers", PROTOCOLS)
def test_ac04_snapshot_and_snapshot_dir_are_immutable(agent, api, clients, protocol, vers):
    api()
    setup_pool()
    tok = token(f"sac04{vers.replace('.', '')}")
    v = create_volume("vs4", tok, protocols=[protocol])
    c = clients()
    c.mount(mount_ip(v), tok, vers)
    fresh = c.run("ls -a /m; echo ---; ls -A /m/.snapshot")
    note(f"AC-04 {protocol} new volume", **out(fresh))
    assert fresh.returncode == 0
    root_list, snapdir_list = fresh.stdout.split("---\n")
    assert ".snapshot" in root_list.split() and snapdir_list == ""

    assert c.run("echo a > /m/a && mkdir /m/d && echo b > /m/d/b && sync && whoami").stdout == "root\n"
    create_snapshot("vs4", "S")
    snapdir = NS / tok / ".snapshot"

    def host_view():
        st = os.stat(snapdir)
        return {"files": host_files(snapdir / "S"), "dirs": sorted(os.listdir(snapdir / "S")),
                "snapdir": sorted(os.listdir(snapdir)), "snapdir_mode": oct(st.st_mode), "snapdir_ino": st.st_ino,
                "lsattr": lsattr_d(snapdir), "root": sorted(os.listdir(NS / tok))}

    before = host_view()
    results = []
    for label, cmd in SNAPSHOT_WRITES + SNAPDIR_WRITES:
        r = c.run(cmd.format(s="S"))
        results.append({"op": label.format(s="S"), "rc": r.returncode, "stderr": r.stderr.strip()})
    after = host_view()
    view = {"root": c.run("ls -a /m"), "snapdir": c.run("ls -A /m/.snapshot"),
            "content": c.run("cat /m/.snapshot/S/a /m/.snapshot/S/d/b")}
    for row in results:
        note(f"AC-04 {protocol} attempt", **row)
    note(f"AC-04 {protocol} host", before=before, after=after, client_after={k: out(r) for k, r in view.items()})
    assert [row for row in results if row["rc"] == 0] == []
    assert after == before
    assert "i" in before["lsattr"]
    assert ".snapshot" in view["root"].stdout.split()
    assert view["snapdir"].stdout == "S\n" and view["content"].stdout == "a\nb\n"

    c.remove()
    delete_volume("vs4")


# --- AC-05 ---


STREAM_MIB = 900


def test_ac05_each_snapshot_is_its_own_point_in_time(agent, api, clients):
    api()
    setup_pool()
    tok = token("sac05")
    v = create_volume("vs5", tok)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    assert c.run("echo one > /m/f && sync").returncode == 0
    create_snapshot("vs5", "S1")
    assert c.run("echo two > /m/f && sync").returncode == 0
    create_snapshot("vs5", "S2")
    assert c.run("echo three > /m/f && sync").returncode == 0
    rd = c.run("cat /m/.snapshot/S1/f /m/.snapshot/S2/f /m/f")
    other = one_shot(mount_ip(v), tok, "3", "cat /m/.snapshot/S1/f /m/.snapshot/S2/f /m/f")
    note("AC-05 points in time", client=out(rd), new_client=out(other))
    assert rd.returncode == 0 and rd.stdout == "one\ntwo\nthree\n"
    assert other.returncode == 0 and other.stdout == "one\ntwo\nthree\n"

    # 클라이언트가 dd로 계속 쓰는 동안 S3를 만든다 (설계 §3 "아직 확정하지 않은 것" 둘째 항목)
    t0 = time.monotonic()
    dd = subprocess.Popen(["docker", "exec", c.name, "sh", "-c",
                           f"dd if=/dev/urandom of=/m/stream bs=1M count={STREAM_MIB} oflag=direct 2>&1"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    running_at_put = dd.poll() is None
    put_at = round(time.monotonic() - t0, 2)
    s3, final3 = create_snapshot("vs5", "S3")
    running_at_done = dd.poll() is None
    done_at = round(time.monotonic() - t0, 2)
    stdout, stderr = dd.communicate(timeout=600)
    dd_seconds = round(time.monotonic() - t0, 2)
    dev = f"/dev/anf/{snap_lv_name(s3['properties']['snapshotId'])}"
    fsck = sh("e2fsck", "-fn", dev)
    s3_size = os.stat(NS / tok / ".snapshot" / "S3" / "stream").st_size
    active_size = os.stat(NS / tok / "stream").st_size
    rd2 = c.run("cat /m/.snapshot/S1/f /m/.snapshot/S2/f /m/.snapshot/S3/f /m/f")
    note("AC-05 snapshot during writes", dd_rc=dd.returncode, dd_out=stdout.strip(), dd_err=stderr.strip(),
         timeline_s={"put": put_at, "succeeded": done_at, "dd_end": dd_seconds},
         dd_running_at_put=running_at_put, dd_running_at_succeeded=running_at_done,
         snapshot_seconds=op_seconds(final3), e2fsck=out(fsck), s3_stream_bytes=s3_size,
         active_stream_bytes=active_size, read_all=out(rd2))
    assert running_at_put and running_at_done, "dd finished before the snapshot: no overlap"
    assert dd.returncode == 0 and f"{STREAM_MIB * MIB} bytes" in stdout
    assert fsck.returncode == 0, out(fsck)
    assert 0 < s3_size < STREAM_MIB * MIB and active_size == STREAM_MIB * MIB
    assert rd2.returncode == 0 and rd2.stdout == "one\ntwo\nthree\nthree\n"

    c.remove()
    delete_volume("vs5")


# --- AC-06 ---


@pytest.mark.parametrize("protocol,vers", PROTOCOLS)
def test_ac06_delete_snapshot_with_client_inside(agent, api, clients, protocol, vers):
    api()
    setup_pool()
    tok = token(f"sac06{vers.replace('.', '')}")
    v = create_volume("vs6", tok, protocols=[protocol])
    ip, fsid = mount_ip(v), fsid_of(v)
    c = clients()
    c.mount(ip, tok, vers)
    assert c.run("echo one > /m/f && mkdir /m/d && echo inside > /m/d/b && sync").returncode == 0
    s1, _ = create_snapshot("vs6", "S1")
    assert c.run("echo two > /m/f && sync").returncode == 0
    s2, _ = create_snapshot("vs6", "S2")
    assert c.run("echo three > /m/f && sync").returncode == 0
    sid1, sid2 = s1["properties"]["snapshotId"], s2["properties"]["snapshotId"]

    holder = clients()
    holder.mount(ip, tok, vers)
    started = sh("docker", "exec", "-d", holder.name, "sh", "-c",
                 "cd /m/.snapshot/S1/d && exec 3< /m/.snapshot/S1/d/b && sleep 600")
    assert started.returncode == 0, out(started)
    time.sleep(1)
    held = holder.run("for p in /proc/[0-9]*; do readlink $p/cwd $p/fd/3 2>/dev/null; done | grep snapshot | sort -u")
    seen_before = c.run("cat /m/.snapshot/S1/f")
    assert seen_before.stdout == "one\n"

    t0 = time.monotonic()
    d = call("DELETE", snap_url("vs6", "S1"))
    lro_headers = sorted(h for h in d.headers if h in ("azure-asyncoperation", "location"))
    assert d.status == 202 and d.raw == b"", (d.status, d.raw)
    final, seen = poll(d.headers["azure-asyncoperation"], 120)
    seconds = round(time.monotonic() - t0, 1)
    g = call("GET", snap_url("vs6", "S1"))
    d2 = call("DELETE", snap_url("vs6", "S1"))
    d2_headers = sorted(h for h in d2.headers if h in ("azure-asyncoperation", "location"))
    note(f"AC-06 {protocol} DELETE", held=held.stdout.split(), status=d.status, lro_headers=lro_headers, seen=seen,
         final=final, seconds=seconds, get_after=error_of(g), second_delete=d2.status, second_headers=d2_headers)
    assert lro_headers == ["azure-asyncoperation", "location"]
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "DELETE"
    assert error_of(g) == (404, "ResourceNotFound", NOT_FOUND.format(snap="S1", a=ACCT, p=POOL, v="vs6"))
    assert d2.status == 204 and d2.raw == b"" and d2_headers == []

    views = {
        "observer (mounted, had read S1)": c.run("timeout 30 ls /m/.snapshot/S1"),
        "holder (cwd and fd inside S1)": holder.run("timeout 30 ls /m/.snapshot/S1"),
        "new client": one_shot(ip, tok, vers, "ls /m/.snapshot/S1"),
    }
    s2_read = c.run("timeout 30 cat /m/.snapshot/S2/f; ls -A /m/.snapshot")
    lvs = snap_lvs()
    xf, etab = exports_file(fsid), instance_etab(fsid)
    host = {"lvs": sorted(lvs), "mounts": snap_mounts(tok), "S1_dir": (NS / tok / ".snapshot" / "S1").exists(),
            "exports_file": exported_paths(xf), "etab": etab}
    for label, r in views.items():
        note(f"AC-06 {protocol} {label}", **out(r))
    note(f"AC-06 {protocol} after", s2=out(s2_read), host=host)
    for label, r in views.items():
        assert r.returncode != 0 and "No such file or directory" in r.stderr, (label, out(r))
    assert s2_read.returncode == 0 and s2_read.stdout == "two\nS2\n"
    assert snap_lv_name(sid1) not in lvs and snap_lv_name(sid2) in lvs
    assert host["mounts"] == [str(NS / tok / ".snapshot" / "S2")] and not host["S1_dir"]
    assert host["exports_file"] == [f"/{tok}", f"/{tok}/.snapshot/S2"]
    assert exported_paths(etab) == [f"/{tok}", f"/{tok}/.snapshot/S2"]

    s1b, _ = create_snapshot("vs6", "S1")
    fresh = one_shot(ip, tok, vers, "cat /m/.snapshot/S1/f /m/.snapshot/S2/f")
    old_view = c.run("timeout 30 cat /m/.snapshot/S1/f")
    note(f"AC-06 {protocol} recreate S1", old_id=sid1, new_id=s1b["properties"]["snapshotId"], new_client=out(fresh),
         observer_client=out(old_view))
    assert s1b["properties"]["snapshotId"] != sid1
    assert fresh.returncode == 0 and fresh.stdout == "three\ntwo\n"

    holder.remove()
    c.remove()
    delete_volume("vs6")


# --- AC-10 ---


def test_ac10_volume_delete_deletes_its_snapshots(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("sac10")
    v = create_volume("vs10", tok)
    ip, fsid = mount_ip(v), fsid_of(v)
    c = clients()
    c.mount(ip, tok, "3", opts="soft,timeo=20,retrans=1")
    assert c.run("echo one > /m/f && sync").returncode == 0
    s1, _ = create_snapshot("vs10", "S1")
    assert c.run("echo two > /m/f && sync").returncode == 0
    s2, _ = create_snapshot("vs10", "S2")
    ids = [s1["properties"]["snapshotId"], s2["properties"]["snapshotId"]]
    rd = c.run("cat /m/.snapshot/S1/f")
    assert rd.stdout == "one\n"
    # 클라이언트가 스냅샷 S1 안에 cwd를 둔 채로 있다
    assert sh("docker", "exec", "-d", c.name, "sh", "-c", "cd /m/.snapshot/S1 && sleep 600").returncode == 0
    time.sleep(1)
    before = {"lvs": sorted(snap_lvs()), "mounts": snap_mounts(tok), "exports_dir": (EXPORTS / fsid.replace("-", "")).exists()}

    d = call("DELETE", vol_url(ACCT, POOL, "vs10"))
    assert d.status == 202, d.raw
    final, seen = poll(d.headers["azure-asyncoperation"], 150)
    gets = {"volume": call("GET", vol_url(ACCT, POOL, "vs10")), "S1": call("GET", snap_url("vs10", "S1")),
            "S2": call("GET", snap_url("vs10", "S2")), "list": call("GET", snap_list_url("vs10"))}
    lvs = snap_lvs()
    after = {"snapshot_lvs_left": sorted(n for n in lvs if n in {snap_lv_name(i) for i in ids}),
             "volume_lv": lv_name(fsid) in lvs_volumes(), "mounts": snap_mounts(tok), "ns_entry": (NS / tok).exists(),
             "exports_dir": (EXPORTS / fsid.replace("-", "")).exists(), "instance": instances().get(instance_name(fsid)),
             "snapshot_rows": [x["id"] for x in db_rows(db) if x["type"] == SNAPSHOT_TYPE]}
    note("AC-10 volume DELETE", before=before, seen=seen, final=final,
         gets={k: error_of(r) for k, r in gets.items()}, after=after)
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "DELETE"
    assert {k: r.status for k, r in gets.items()} == {"volume": 404, "S1": 404, "S2": 404, "list": 404}
    assert after == {"snapshot_lvs_left": [], "volume_lv": False, "mounts": [], "ns_entry": False,
                     "exports_dir": False, "instance": None, "snapshot_rows": []}

    c.remove()
    v2 = create_volume("vs10", tok)
    again = one_shot(mount_ip(v2), tok, "3", "ls -a /m; echo ---; ls -A /m/.snapshot")
    listing = call("GET", snap_list_url("vs10"))
    note("AC-10 recreate same creationToken", client=out(again), list=listing.json())
    assert again.returncode == 0
    root_list, snapdir_list = again.stdout.split("---\n")
    assert ".snapshot" in root_list.split() and snapdir_list == ""
    assert listing.json() == {"value": []}
    delete_volume("vs10")
