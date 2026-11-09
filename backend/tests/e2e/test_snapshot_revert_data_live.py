"""되돌리기 e2e (1/2): 클라이언트에서 관찰한 데이터 효과 (되돌리기 설계 §8).

- AC-02 NFSv3 / AC-03 NFSv4.1: S2로 되돌린 볼륨이 S2 트리와 같고, 더 새 S3는 어디에도 없으며 S1·S2는 그대로다.
  같은 볼륨을 더 오래된 S1로 다시 되돌린다 (AC-08 (d))
- AC-04 되돌리기 전에 마운트한 클라이언트: 탐침, fd, cwd, 쓰기를 계속하는 클라이언트
- AC-10 위임 꺼짐: 준비 스크립트, 인스턴스의 NFSv4 상태, 켜진 값에서 agent가 뜨지 않음

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_snapshot_revert_data_live.py -v -s'
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

import live_api
from live_api import call
from dataplane_live import (
    agent_port_open, create_volume, delete_volume, error_of, fsid_of, instance_name, mount_ip, note, NS, one_shot,
    out, REPO, setup_pool, sh, SKIP_UNLESS_ROOT, token,
)
from snapshot_live import (
    create_snapshot, exported_paths, exports_file, instance_etab, NOT_FOUND, op_seconds, snap_lv_name, snap_lvs,
    snap_mounts, snap_url, vol_snap_lvs,
)
from revert_live import (
    build_history, client_tree, drop_rule, fast_poll, HOLDER, identity, listing, post_revert, probe_stats, PROBE,
    revert, rv_tags, RuleWatch, snapshot_trees, start_script, tree, volume_lvs, wait_file, WRITER, writer_stats,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]


@pytest.fixture(autouse=True)
def leases_back_to_zero():
    """AC-10이 중간에 실패해도 위임 꺼짐(fs.leases-enable = 0)으로 돌려놓는다."""
    yield
    sh("sysctl", "-qw", "fs.leases-enable=0")


# --- AC-02, AC-03, AC-08 (d) ---


@pytest.mark.parametrize("ac,protocol,vers", [("AC-02", "NFSv3", "3"), ("AC-03", "NFSv4.1", "4.1")])
def test_ac02_ac03_revert_restores_snapshot_and_deletes_newer(agent, api, clients, ac, protocol, vers):
    api()
    setup_pool()
    tok = token("r" + ac.lower().replace("-", ""))
    v = create_volume("vr2", tok, protocols=[protocol])
    ip, fsid = mount_ip(v), fsid_of(v)
    c = clients()
    c.mount(ip, tok, vers)
    snaps = build_history(c, "vr2")
    mp = NS / tok
    before = snapshot_trees(tok, ("S1", "S2", "S3"))
    before_vol = tree(mp)
    before_list = listing("vr2")
    s3_lv = snap_lv_name(snaps["S3"]["properties"]["snapshotId"])
    assert before["S2"] != before_vol and before["S2"] != before["S3"]  # 되돌리기가 바꿀 것이 있다
    assert s3_lv in vol_snap_lvs(fsid)

    r, final, seen = revert("vr2", snaps["S2"]["id"])
    after_vol = tree(mp)
    after_snaps = snapshot_trees(tok, ("S1", "S2"))
    after_list = listing("vr2")
    g3 = call("GET", snap_url("vr2", "S3"))
    read = c.run("cat /m/A /m/K /m/d2/Z && ls /m /m/d1 && ls -A /m/.snapshot")
    gone = c.run("cat /m/N; cat /m/d1/X; ls /m/d3; ls /m/.snapshot/S3")
    b = clients()
    b.mount(ip, tok, vers)
    fresh = client_tree(b, "/m")
    fresh_s2 = client_tree(b, "/m/.snapshot/S2")
    host = {"snap_lvs": vol_snap_lvs(fsid), "s3_lv_exists": s3_lv in snap_lvs(),
            "snap_mounts": snap_mounts(tok), "exports": exported_paths(exports_file(fsid)),
            "etab": exported_paths(instance_etab(fsid)), "snapshot_dir": sorted(p.name for p in (mp / ".snapshot").iterdir()),
            "volume_lvs": volume_lvs(fsid), "drop_rule": drop_rule(fsid)}
    note(f"{ac} {protocol} revert to S2", status=r.status, seen=seen, final=final, seconds=op_seconds(final),
         tree_equal_s2=after_vol == before["S2"], s1_same=after_snaps["S1"] == before["S1"],
         s2_same=after_snaps["S2"] == before["S2"], client_tree_equal_s2=fresh == before["S2"],
         client_s2_equal=fresh_s2 == before["S2"], list_before=sorted(before_list), list_after=sorted(after_list),
         s3_get=error_of(g3), read=out(read), gone=out(gone), host=host)
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "POST"
    assert after_vol == before["S2"]
    assert fresh == before["S2"] and fresh_s2 == before["S2"]
    assert after_snaps == {"S1": before["S1"], "S2": before["S2"]}
    assert read.returncode == 0
    assert read.stdout.split() == ["a2", "k1", "k2", "z2", "/m:", "A", "K", "big", "d1", "d2",
                                   "/m/d1:", "sub", "S1", "S2"]
    assert gone.stderr.count("No such file or directory") == 4 and gone.stdout == "", out(gone)
    assert sorted(after_list) == ["S1", "S2"]
    assert all(identity(after_list[n]) == identity(before_list[n]) for n in ("S1", "S2"))
    assert error_of(g3)[:2] == (404, "ResourceNotFound")
    assert error_of(g3)[2] == NOT_FOUND.format(snap="S3", a="e2e-vol-acct", p="e2e-vol-pool", v="vr2")
    assert host["snap_lvs"] == sorted(snap_lv_name(snaps[n]["properties"]["snapshotId"]) for n in ("S1", "S2"))
    assert not host["s3_lv_exists"]
    assert host["snap_mounts"] == [str(mp / ".snapshot" / n) for n in ("S1", "S2")]
    assert host["exports"] == [f"/{tok}", f"/{tok}/.snapshot/S1", f"/{tok}/.snapshot/S2"]
    assert host["etab"] == host["exports"]
    assert host["snapshot_dir"] == ["S1", "S2"]
    assert list(host["volume_lvs"]) == [f"vol_{fsid.replace('-', '')}"]
    assert rv_tags(fsid) == [f"anf_rv_done={final['name']}"]
    assert host["drop_rule"] is False

    # 되돌린 볼륨에 새로 쓰고 새 스냅샷을 만들 수 있다
    w = c.run("echo after > /m/after && sync")
    s4, _ = create_snapshot("vr2", "S4")
    s4_read = b.run("cat /m/after /m/.snapshot/S4/after && ls -A /m/.snapshot")
    note(f"{ac} {protocol} write + new snapshot after revert", write=out(w), read=out(s4_read))
    assert w.returncode == 0 and s4_read.returncode == 0
    assert s4_read.stdout.split() == ["after", "after", "S1", "S2", "S4"]

    # AC-08 (d): 한 번 되돌린 볼륨을 더 오래된 S1로 다시 되돌린다. S2와 S4가 더 새 스냅샷이다
    r1, final1, seen1 = revert("vr2", snaps["S1"]["id"])
    after1 = tree(mp)
    list1 = listing("vr2")
    read1 = c.run("cat /m/A /m/K /m/d1/X && ls -A /m/.snapshot; cat /m/after; cat /m/.snapshot/S2/A")
    note(f"AC-08d {protocol} second revert to older S1", seen=seen1, final=final1, seconds=op_seconds(final1),
         tree_equal_s1=after1 == before["S1"], list_after=sorted(list1), read=out(read1),
         s1_same=tree(mp / ".snapshot" / "S1") == before["S1"], snap_lvs=vol_snap_lvs(fsid),
         volume_lvs=volume_lvs(fsid), get_s2=error_of(call("GET", snap_url("vr2", "S2")))[:2],
         get_s4=error_of(call("GET", snap_url("vr2", "S4")))[:2], rv_tags=rv_tags(fsid), drop_rule=drop_rule(fsid))
    assert final1["status"] == "Succeeded"
    assert after1 == before["S1"]
    assert tree(mp / ".snapshot" / "S1") == before["S1"]
    assert sorted(list1) == ["S1"] and identity(list1["S1"]) == identity(before_list["S1"])
    assert read1.stdout.split() == ["a1", "k1", "x1", "S1"]
    assert read1.stderr.count("No such file or directory") == 2
    assert vol_snap_lvs(fsid) == [snap_lv_name(snaps["S1"]["properties"]["snapshotId"])]
    assert list(volume_lvs(fsid)) == [f"vol_{fsid.replace('-', '')}"]
    assert rv_tags(fsid) == [f"anf_rv_done={final1['name']}"]
    for cl in (c, b):
        cl.remove()
    delete_volume("vr2")


# --- AC-04 ---


@pytest.mark.parametrize("protocol,vers", [("NFSv3", "3"), ("NFSv4.1", "4.1")])
def test_ac04_mounted_client_follows_revert_without_remount(agent, api, clients, protocol, vers):
    api()
    setup_pool()
    tok = token(f"rac04{vers.replace('.', '')}")
    v = create_volume("vr4", tok, protocols=[protocol])
    ip, fsid = mount_ip(v), fsid_of(v)
    a = clients()
    a.mount(ip, tok, vers)
    w = clients()
    w.mount(ip, tok, vers)
    prep = a.run("echo p1 > /m/P && echo b1 > /m/B && mkdir /m/olddir && echo e1 > /m/olddir/E && "
                 "echo base > /m/W && sync")
    assert prep.returncode == 0, out(prep)
    s2, _ = create_snapshot("vr4", "S2")
    later = a.run("echo b2 > /m/B && echo d1 > /m/D && mkdir /m/n && echo f1 > /m/n/F && echo e2 > /m/olddir/E2 "
                  "&& sync && cat /m/B /m/D /m/n/F")  # 캐시에 올린다
    assert later.returncode == 0, out(later)
    mount_before = a.run("grep ' /m ' /proc/mounts").stdout.strip()
    start_script(a, "/tmp/hold.sh", HOLDER)
    assert wait_file(a, "/tmp/held")
    start_script(a, "/tmp/probe.sh", PROBE, "/m/P")
    start_script(w, "/tmp/writer.sh", WRITER, "/m/W")
    watch = RuleWatch(fsid)
    watch.start()
    time.sleep(2)

    t_post = time.time()
    r = post_revert("vr4", s2["id"])
    assert r.status == 202, r.raw
    t_done, final, seen = fast_poll(r.headers["azure-asyncoperation"])
    # 다시 마운트하지 않은 같은 클라이언트에서, 끝난 것을 본 직후에
    chk = a.run("date +%s.%N; ls /m; cat /m/B /m/P /m/olddir/E; date +%s.%N")
    paths = a.run("cat /m/D; ls /m/n; date +%s.%N")
    a.run("touch /tmp/go")
    assert wait_file(a, "/tmp/done", 30)
    held = {k: a.run(f"cat /tmp/{k}.out").stdout for k in ("fd_old", "fd_new", "cwd_old", "cwd_new")}
    write = a.run("echo new > /m/X && cat /m/X")
    time.sleep(2)
    for cl in (a, w):
        cl.run("touch /tmp/stop")
    time.sleep(1)
    windows = watch.stop()
    probe = probe_stats(a.run("cat /tmp/probe.log").stdout)
    wlog = w.run("cat /tmp/w.log").stdout
    writer = writer_stats(wlog)
    w_client = w.run("cat /m/W | head -5; echo ...; tail -3 /m/W; echo lines=$(wc -l < /m/W); "
                     "echo nul_bytes=$(tr -cd '\\000' < /m/W | wc -c)")
    w_host = (NS / tok / "W").read_bytes()
    mount_after = a.run("grep ' /m ' /proc/mounts").stdout.strip()
    chk_lines = chk.stdout.splitlines()
    t_chk = (float(chk_lines[0]), float(chk_lines[-1]))
    # 창 동안의 쓰기: 창이 열리기 전에 시작해 창 안에서 멈춘 쓰기
    in_window = []
    if windows:
        w0, w1 = windows[0]
        in_window = [x for x in (line.split() for line in wlog.splitlines()) if float(x[1]) <= w1 and float(x[2]) >= w0]
    note(f"AC-04 {protocol}", seen=seen, final=final, op_seconds=op_seconds(final),
         window_s=[round(b - a_, 3) for a_, b in windows],
         window_open_after_post_s=round(windows[0][0] - t_post, 3) if windows else None,
         done_seen_after_window_close_s=round(t_done - windows[0][1], 3) if windows else None,
         check_started_after_done_s=round(t_chk[0] - t_done, 3), check_finished_after_done_s=round(t_chk[1] - t_done, 3),
         check=out(chk), paths=out(paths), held=held, write=out(write), probe=probe,
         probe_longest_read_relative_to_window_open_s=(round(probe["longest_read_started"] - windows[0][0], 3)
                                                      if windows and probe["longest_read_started"] else None),
         writer=writer, writes_spanning_window=in_window, writer_file_client=out(w_client),
         writer_file_host_head=w_host[:200].decode(errors="replace"), writer_file_host_len=len(w_host),
         mount_before=mount_before, mount_after=mount_after)
    assert final["status"] == "Succeeded"
    assert mount_after == mount_before
    assert probe["reads"] > 10 and probe["failures"] == [] and probe["contents"] == ["p1"]
    assert chk.returncode == 0, out(chk)
    assert chk_lines[1:-1] == ["B", "P", "W", "olddir", "b1", "p1", "e1"]
    assert t_chk[1] - t_done < 1.0
    assert paths.stderr.count("No such file or directory") == 2, out(paths)
    assert held["fd_old"] == "b1\nrc=0\n"
    assert "Stale file handle" in held["fd_new"] and "rc=0" not in held["fd_new"]
    assert held["cwd_old"] == "E\nrc=0\ne1\nrc=0\n"
    assert "Stale file handle" in held["cwd_new"] and "rc=0" not in held["cwd_new"]
    assert write.returncode == 0 and write.stdout == "new\n"
    assert writer["failures"] == []
    for cl in (a, w):
        cl.remove()
    delete_volume("vr4")


# --- AC-10 ---


def leases() -> str:
    return sh("sysctl", "-n", "fs.leases-enable").stdout.strip()


def nfsd_states(fsid: str) -> str:
    r = sh("docker", "exec", instance_name(fsid), "sh", "-c",
           "for d in /proc/fs/nfsd/clients/*/; do echo \"== $d\"; cat \"$d/info\" \"$d/states\"; done")
    return r.stdout + r.stderr


def test_ac10_delegations_are_off(agent, api, clients):
    # 준비 스크립트가 값을 0으로 만들고 파일로 고정한다 (먼저 1로 바꿔 두고 다시 실행한다)
    sh("sysctl", "-qw", "fs.leases-enable=1")
    setup = sh("bash", str(REPO / "scripts" / "setup-wsl-dataplane.sh"), timeout=600)
    conf = Path("/etc/sysctl.d/90-anf-clone.conf")
    note("AC-10 setup script", setup=out(setup), leases=leases(), conf=conf.read_text() if conf.exists() else None)
    assert setup.returncode == 0 and leases() == "0"
    assert conf.read_text() == "fs.leases-enable = 0\n"

    api()
    setup_pool()
    tok = token("rac10")
    v = create_volume("vr10", tok, protocols=["NFSv4.1"])
    ip, fsid = mount_ip(v), fsid_of(v)
    c = clients()
    c.mount(ip, tok, "4.1")
    assert c.run("echo x > /m/held && echo y > /m/ro && sync").returncode == 0
    r = sh("docker", "exec", "-d", c.name, "sh", "-c", "exec 3<>/m/held 4</m/ro; echo z >&3; cat <&4; sleep 600")
    assert r.returncode == 0
    time.sleep(2)
    off = nfsd_states(fsid)
    held_fds = c.run("ls -l /proc/*/fd 2>/dev/null | grep /m/").stdout
    # 대조 (기준 밖): 값이 1이면 같은 검사가 위임을 찾는다. 새 클라이언트가 새 파일을 연다
    contrast = None
    d = None
    try:
        sh("sysctl", "-qw", "fs.leases-enable=1")
        d = clients()
        d.mount(ip, tok, "4.1")
        assert d.run("echo q > /m/other && sync").returncode == 0
        sh("docker", "exec", "-d", d.name, "sh", "-c", "exec 3<>/m/other; echo r >&3; sleep 600")
        time.sleep(2)
        contrast = nfsd_states(fsid)
    finally:
        sh("sysctl", "-qw", "fs.leases-enable=0")
    note("AC-10 nfsd states", leases_during_check="0", states=off, held_fds=held_fds, contrast_leases_1=contrast)
    assert "type: open" in off and "/held" in off and "deleg" not in off
    assert held_fds.count("/m/") >= 2

    # 값을 1로 바꾸고 agent를 띄우면 고칠 방법을 담은 메시지와 함께 뜨지 않는다
    agent.stop()
    refused = None
    try:
        assert not agent_port_open()
        sh("sysctl", "-qw", "fs.leases-enable=1")
        cmd = [live_api.PYTHON, "-m", "uvicorn", "--factory", "storage_agent.agent_app:create_app",
               "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8090"]
        t0 = time.monotonic()
        try:
            refused = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=90,
                                     env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        except subprocess.TimeoutExpired as e:
            refused = e
        elapsed = round(time.monotonic() - t0, 1)
    finally:
        sh("sysctl", "-qw", "fs.leases-enable=0")
        agent.start()
    text = (refused.stdout or "") + (refused.stderr or "") if not isinstance(refused, subprocess.TimeoutExpired) else ""
    note("AC-10 agent with fs.leases-enable=1", returncode=getattr(refused, "returncode", "timeout"),
         elapsed_s=elapsed, output_tail=text[-2500:], leases_after=leases())
    assert isinstance(refused, subprocess.CompletedProcess) and refused.returncode != 0
    assert "NFSv4 delegations must be off" in text and "setup-wsl-dataplane.sh" in text
    assert leases() == "0"
    # agent가 다시 떴고 볼륨이 그대로 돈다
    rd = one_shot(ip, tok, "4.1", "cat /m/held")
    note("AC-10 after agent restart", read=out(rd))
    assert rd.returncode == 0
    # 클라이언트를 볼륨보다 먼저 지운다: 서버가 사라진 뒤의 hard 마운트는 docker rm -f로 지워지지 않았다
    for cl in (c, d):
        cl.remove()
        assert cl.name not in sh("docker", "ps", "-a", "--format", "{{.Names}}").stdout
    delete_volume("vr10")
