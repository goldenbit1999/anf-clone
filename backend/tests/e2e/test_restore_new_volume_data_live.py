"""스냅샷에서 새 볼륨 e2e (1/2): 클라이언트에서 관찰한 데이터 효과 (복원 설계 §8).

- AC-02 NFSv3 / AC-04 (a) NFSv4.1: 원본 V의 기록(S1 → S2 → S3 → 또 바꿈)에서 S2로 만든 N이 S2 트리와 같고,
  `.snapshot`에는 base 스냅샷 S2만 있으며, 루트 모드가 N의 unixPermissions이고, 서버의 `.snapshot`이 immutable이다
- AC-03 (같은 테스트): N에 쓰면 V·S2·base가 그대로, V에 쓰면 N이 그대로, base 안 쓰기는 거절
- AC-04 (b) v3 원본 → 같은 계정 다른 풀(Standard)의 v4.1 N
- AC-05 더 큰 N: df, V 크기를 넘는 쓰기, ENOSPC, base로 되돌린 뒤 크기 유지
- AC-06 N 클라이언트가 읽고 쓰는 동안 원본 되돌리기 → 원본 스냅샷 삭제 → 원본 삭제 → agent 재시작(두 가지)

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_restore_new_volume_data_live.py -v -s'
"""

import os
import time

import pytest

import live_api
from live_api import TIB, create_pool
from dataplane_live import (
    ACCT, agent_call, create_volume, delete_volume, fsid_of, GIB, instance_name, instances, lv_name, mount_ip, note,
    NS, one_shot, out, setup_pool, sh, SKIP_UNLESS_ROOT, token,
)
from snapshot_live import (
    create_snapshot, delete_snapshot, exported_paths, exports_file, instance_etab, lsattr_d, snap_mounts,
    umount_retry, vol_snap_lvs,
)
from revert_live import (
    build_history, client_tree, identity, listing, mount_targets, probe_stats, PROBE, revert, start_script, tree,
    WRITER, writer_stats,
)
from restore_live import (
    cl_tags, df_bytes, ext4_uuid, listing_in, lv_attr, lv_origin, restore_volume, SNAPDIR_WRITES, try_writes,
    WRITE_REFUSALS,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]

POOL2 = "e2e-vol-pool2"


def mode_of(path) -> str:
    return oct(os.stat(path).st_mode & 0o7777)[2:]


# --- AC-02, AC-03, AC-04 (a) ---


@pytest.mark.parametrize("ac,protocol,vers,perms", [("AC-02", "NFSv3", "3", None),
                                                    ("AC-04a", "NFSv4.1", "4.1", "0755")])
def test_ac02_ac03_ac04a_content_and_independence(agent, api, clients, ac, protocol, vers, perms):
    api()
    setup_pool()
    tag = ac.lower().replace("-", "")
    tok = token("n" + tag)
    v = create_volume("vn2", tok, protocols=[protocol])
    vip, vfsid = mount_ip(v), fsid_of(v)
    c = clients()
    c.mount(vip, tok, vers)
    # 원본 루트 모드를 바꿔 둔다: 스냅샷이 이 모드를 갖고, N은 자기 unixPermissions로 맞춰야 한다 (결정 11)
    chm = c.run("chmod 0711 /m && stat -c %a /m")
    assert chm.returncode == 0 and chm.stdout.strip() == "711", out(chm)
    snaps = build_history(c, "vn2")
    mp = NS / tok
    s_tree = tree(mp / ".snapshot" / "S2")
    v_tree0 = tree(mp)
    assert s_tree != v_tree0 and s_tree != tree(mp / ".snapshot" / "S3")  # 만든 뒤 바뀐 것이 있다

    ntok = token("n" + tag + "n")
    extra = {} if perms is None else {"unixPermissions": perms}
    r, final, seen, n = restore_volume("vn2n", ntok, snaps["S2"]["id"], **extra)
    np_ = n["properties"]
    nip, nfsid = mount_ip(n), fsid_of(n)
    nmp = NS / ntok
    d = clients()
    d.mount(nip, ntok, vers)
    client_n = client_tree(d, "/m")
    client_base = client_tree(d, "/m/.snapshot/S2")
    read = d.run("cat /m/A /m/K && ls -A /m /m/.snapshot && stat -c %a /m && grep ' /m ' /proc/mounts")
    gone = d.run("cat /m/N; ls /m/d3; ls /m/.snapshot/S1; ls /m/.snapshot/S3")
    nlist = listing("vn2n")
    host = {"tree_equal_s2": tree(nmp) == s_tree, "snapshot_dir": sorted(os.listdir(nmp / ".snapshot")),
            "lsattr_snapshot_dir": lsattr_d(nmp / ".snapshot"), "root_mode": mode_of(nmp),
            "v_root_mode": mode_of(mp), "s2_root_mode": mode_of(mp / ".snapshot" / "S2"),
            "lv_attr": lv_attr(nfsid), "origin": lv_origin(nfsid), "cl_tags": cl_tags(nfsid),
            "snap_lvs": vol_snap_lvs(nfsid), "snap_mounts": snap_mounts(ntok),
            "exports": exported_paths(exports_file(nfsid)), "etab": exported_paths(instance_etab(nfsid)),
            "ext4_uuid_n": ext4_uuid(lv_name(nfsid)), "ext4_uuid_v": ext4_uuid(lv_name(vfsid))}
    expected_mode = (perms or "0770").lstrip("0")
    note(f"{ac} {protocol} new volume from S2", seen=seen, final_status=final["status"],
         props={k: np_.get(k) for k in ("protocolTypes", "unixPermissions", "snapshotId", "originatingResourceId",
                                        "fileSystemId", "mountTargets")},
         client_tree_equal_s2=client_n == s_tree, client_base_equal_s2=client_base == s_tree,
         read=out(read), gone=out(gone), list=sorted(nlist), host=host)
    assert np_["protocolTypes"] == [protocol]
    assert np_["unixPermissions"] == (perms or "0770")
    assert client_n == s_tree and client_base == s_tree and host["tree_equal_s2"]
    assert read.returncode == 0, out(read)
    lines = read.stdout.split()
    assert lines[:3] == ["a2", "k1", "k2"]  # 지운 A가 있고, 덮어쓴 K는 S2 내용이다
    assert lines[3:-6] == ["/m:", ".snapshot", "A", "K", "big", "d1", "d2", "/m/.snapshot:", "S2", expected_mode]
    assert f"vers={vers}" in read.stdout and f"addr={nip}" in read.stdout
    assert gone.stdout == "" and gone.stderr.count("No such file or directory") == 4, out(gone)  # S2 뒤에 만든 것 없음
    assert host["snapshot_dir"] == ["S2"] and host["snap_mounts"] == [str(nmp / ".snapshot" / "S2")]
    assert "i" in host["lsattr_snapshot_dir"]
    assert host["root_mode"] == expected_mode and host["s2_root_mode"] == "711"
    assert host["cl_tags"] == [] and host["lv_attr"].startswith("Vwi")
    assert host["exports"] == [f"/{ntok}", f"/{ntok}/.snapshot/S2"] and host["etab"] == host["exports"]
    assert sorted(nlist) == ["S2"]

    # AC-03: N에 쓰고, 덮어쓰고, 지운다 → V, V에서 본 S2, N의 base가 그대로다
    v_tree1 = tree(mp)
    v_s2_client = client_tree(c, "/m/.snapshot/S2")
    base_host0 = tree(nmp / ".snapshot" / "S2")
    wn = d.run("echo nn > /m/n_only && echo over2 > /m/K && rm /m/A && rm -r /m/d1/sub && "
               "dd if=/dev/urandom of=/m/nbig bs=1M count=4 2>/dev/null && sync")
    v_sees = c.run("cat /m/K; ls /m/n_only /m/nbig")
    after_n = {"v_tree_same": tree(mp) == v_tree1, "v_client_s2_same": client_tree(c, "/m/.snapshot/S2") == v_s2_client,
               "base_host_same": tree(nmp / ".snapshot" / "S2") == base_host0,
               "base_client_same": client_tree(d, "/m/.snapshot/S2") == client_base,
               "v_s2_equal_s_tree": v_s2_client == s_tree, "v_sees": out(v_sees)}
    # V에 쓰고 지운다 → N이 그대로다
    n_tree1, n_client1 = tree(nmp), client_tree(d, "/m")
    wv = c.run("echo vv > /m/v_only && rm /m/K && rm -r /m/d1 && sync")
    n_sees = d.run("cat /m/K; ls /m/v_only")
    after_v = {"n_tree_same": tree(nmp) == n_tree1, "n_client_same": client_tree(d, "/m") == n_client1,
               "n_sees": out(n_sees)}
    attempts = try_writes(d, "S2")
    extras = try_writes(d, "S2", SNAPDIR_WRITES)
    base_after = tree(nmp / ".snapshot" / "S2")
    note(f"AC-03 {protocol} independence", write_n=out(wn), after_n=after_n, write_v=out(wv), after_v=after_v,
         base_writes=attempts, snapdir_writes_extra=extras, base_same_after_attempts=base_after == base_host0)
    assert wn.returncode == 0 and wv.returncode == 0
    assert all(after_n[k] for k in ("v_tree_same", "v_client_s2_same", "base_host_same", "base_client_same",
                                    "v_s2_equal_s_tree"))
    assert v_sees.stdout == "over\n" and v_sees.stderr.count("No such file or directory") == 2
    assert after_v["n_tree_same"] and after_v["n_client_same"]
    assert n_sees.stdout == "over2\n" and "No such file or directory" in n_sees.stderr
    for row in attempts:
        assert row["rc"] != 0 and any(x in row["stderr"] for x in WRITE_REFUSALS), row
    assert all(row["rc"] != 0 for row in extras)
    assert base_after == base_host0
    for cl in (c, d):
        cl.remove()
    delete_volume("vn2n")
    delete_volume("vn2")


# --- AC-04 (b) ---


def test_ac04b_nfsv41_volume_in_another_pool_from_nfsv3_snapshot(agent, api, clients):
    api()
    setup_pool()
    create_pool(ACCT, POOL2, 4 * TIB, "Standard")
    tok = token("nac04b")
    v = create_volume("vn4", tok, protocols=["NFSv3"])
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    w = c.run("mkdir -p /m/d && echo one > /m/a && echo b > /m/d/b && "
              "dd if=/dev/urandom of=/m/r bs=1M count=2 2>/dev/null && sync")
    assert w.returncode == 0, out(w)
    s, _ = create_snapshot("vn4", "S")
    assert c.run("echo two > /m/a && rm /m/d/b && sync").returncode == 0
    s_tree = tree(NS / tok / ".snapshot" / "S")
    ntok = token("nac04bn")
    r, final, seen, n = restore_volume("vn4n", ntok, s["id"], protocols=["NFSv4.1"], pool=POOL2)
    np_ = n["properties"]
    nip = mount_ip(n)
    d = clients()
    d.mount(nip, ntok, "4.1")
    ct, cbase = client_tree(d, "/m"), client_tree(d, "/m/.snapshot/S")
    mnt = d.run("grep ' /m ' /proc/mounts")
    rd = d.run("cat /m/a /m/d/b && echo w > /m/new && cat /m/new")
    v3 = one_shot(nip, ntok, "3")
    nlist = listing_in("vn4n", pool=POOL2)
    vprops = v["properties"]
    note("AC-04b other pool, NFSv4.1 from NFSv3", seen=seen,
         n={k: np_.get(k) for k in ("serviceLevel", "actualThroughputMibps", "protocolTypes", "exportPolicy",
                                    "snapshotId", "originatingResourceId")},
         v={k: vprops.get(k) for k in ("serviceLevel", "actualThroughputMibps", "protocolTypes")},
         client_tree_equal_s=ct == s_tree, client_base_equal_s=cbase == s_tree, mount=mnt.stdout.strip(),
         read=out(rd), v3_mount=out(v3), list=sorted(nlist))
    assert n["id"].split("/capacityPools/")[1].startswith(POOL2 + "/")
    assert np_["serviceLevel"] == "Standard" and vprops["serviceLevel"] == "Premium"
    assert np_["actualThroughputMibps"] == GIB / TIB * 16 and vprops["actualThroughputMibps"] == GIB / TIB * 64
    assert np_["protocolTypes"] == ["NFSv4.1"] and vprops["protocolTypes"] == ["NFSv3"]
    assert np_["exportPolicy"]["rules"][0]["nfsv41"] is True and np_["exportPolicy"]["rules"][0]["nfsv3"] is False
    assert ct == s_tree and cbase == s_tree
    assert "nfs4 " in mnt.stdout and "vers=4.1" in mnt.stdout
    assert rd.returncode == 0 and rd.stdout.split() == ["one", "b", "w"]
    # v3 마운트는 버전 거절로 실패한다 (거절 이유까지 본다)
    assert v3.returncode != 0
    assert ("Protocol not supported" in v3.stderr
            or "requested NFS version or transport protocol is not supported" in v3.stderr), out(v3)
    assert sorted(nlist) == ["S"]
    for cl in (c, d):
        cl.remove()
    delete_volume("vn4n", pool=POOL2)
    delete_volume("vn4")


# --- AC-05 ---


def test_ac05_larger_volume_from_snapshot(agent, api, clients):
    api()
    setup_pool()
    tok = token("nac05")
    v = create_volume("vn5", tok)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    assert c.run("echo one > /m/a && sync").returncode == 0
    s, _ = create_snapshot("vn5", "S")
    ntok = token("nac05n")
    r, final, seen, n = restore_volume("vn5n", ntok, s["id"], size=2 * GIB)
    nip, nfsid = mount_ip(n), fsid_of(n)
    d = clients()
    d.mount(nip, ntok, "3")
    v_df, n_df = df_bytes(c), df_bytes(d)
    rec = agent_call("GET", f"/api/storage/volumes/{nfsid}")[1]
    t0 = time.monotonic()
    big = d.run("dd if=/dev/zero of=/m/big bs=1M count=1200 conv=fsync 2>&1; echo rc=$?", timeout=600)
    big_s = round(time.monotonic() - t0, 1)
    df_big = df_bytes(d)
    t0 = time.monotonic()
    fill = d.run("dd if=/dev/zero of=/m/fill bs=1M conv=fsync 2>&1; echo rc=$?", timeout=600)
    fill_s = round(time.monotonic() - t0, 1)
    df_full = df_bytes(d)
    rm = d.run("rm /m/big /m/fill && sync && cat /m/a")
    base = listing("vn5n")["S"]
    rr, rfinal, _ = revert("vn5n", base["id"])
    df_after = df_bytes(d)
    rec_after = agent_call("GET", f"/api/storage/volumes/{nfsid}")[1]
    after_read = d.run("cat /m/a && ls -A /m")
    note("AC-05 larger volume", v_df=v_df, n_df=n_df, agent_size=rec["size"], big=out(big), big_s=big_s,
         df_big=df_big, fill=out(fill), fill_s=fill_s, df_full=df_full, rm=out(rm), revert=rfinal["status"],
         df_after_revert=df_after, agent_size_after_revert=rec_after["size"], after_read=out(after_read),
         lv_size=sh("lvs", "--noheadings", "--units", "b", "--nosuffix", "-o", "lv_size", f"anf/{lv_name(nfsid)}"
                    ).stdout.strip())
    assert n["properties"]["usageThreshold"] == 2 * GIB and rec["size"] == 2 * GIB
    assert 1.9 * GIB <= n_df[0] <= 2 * GIB and v_df[0] <= GIB  # df가 N의 크기를 보인다 (V는 1 GiB)
    assert big.stdout.strip().endswith("rc=0") and df_big[1] > GIB  # V의 크기를 넘는 쓰기가 된다
    assert "No space left on device" in fill.stdout and not fill.stdout.strip().endswith("rc=0")
    assert df_full[2] < 16 << 20  # 다 찼다
    assert rm.returncode == 0 and rm.stdout == "one\n"
    assert rfinal["status"] == "Succeeded"
    assert df_after[0] == n_df[0] and rec_after["size"] == 2 * GIB  # base로 되돌려도 크기가 줄지 않는다 (S6 B2)
    assert after_read.stdout.split() == ["one", ".snapshot", "a"]
    for cl in (c, d):
        cl.remove()
    delete_volume("vn5n")
    delete_volume("vn5")


# --- AC-06 ---


def test_ac06_new_volume_survives_source_revert_delete_and_agent_restart(agent, api, clients):
    api()
    setup_pool()
    tok = token("nac06")
    v = create_volume("vn6", tok)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    snaps = build_history(c, "vn6")
    s_tree = tree(NS / tok / ".snapshot" / "S2")
    ntok = token("nac06n")
    r, final, seen, n = restore_volume("vn6n", ntok, snaps["S2"]["id"])
    nip, nfsid = mount_ip(n), fsid_of(n)
    nmp = NS / ntok
    base0 = listing("vn6n")["S2"]
    d = clients()
    d.mount(nip, ntok, "3")
    start_script(d, "/tmp/probe.sh", PROBE, "/m/A")  # 0.2초마다 읽는다 (S2의 A = a2)
    start_script(d, "/tmp/writer.sh", WRITER, "/m/W")  # 0.1초마다 덧붙인다
    time.sleep(2)
    results = {}

    def check(step: str, settle: float = 1.0) -> dict:
        time.sleep(settle)
        probe = probe_stats(d.run("cat /tmp/probe.log").stdout)
        writer = writer_stats(d.run("cat /tmp/w.log").stdout)
        t = tree(nmp)
        t.pop("W", None)
        lst = listing("vn6n")
        snapdir = d.run("ls -A /m/.snapshot")
        row = {"probe": {k: probe[k] for k in ("reads", "failures", "longest_read_s", "contents")},
               "writer": writer, "tree_equal_s2": t == s_tree,
               "base_host_equal_s2": tree(nmp / ".snapshot" / "S2") == s_tree,
               "base_client_equal_s2": client_tree(d, "/m/.snapshot/S2") == s_tree,
               "list": sorted(lst), "base_identity_same": "S2" in lst and identity(lst["S2"]) == identity(base0),
               "client_snapshot_dir": snapdir.stdout.split(), "origin": lv_origin(nfsid),
               "snap_mounts": snap_mounts(ntok)}
        results[step] = row
        note(f"AC-06 after {step}", **row)
        assert probe["failures"] == [] and writer["failures"] == [], (step, row)
        assert probe["contents"] == ["a2"]
        assert row["tree_equal_s2"] and row["base_host_equal_s2"] and row["base_client_equal_s2"], (step, row)
        assert row["list"] == ["S2"] and row["base_identity_same"] and row["client_snapshot_dir"] == ["S2"]
        assert row["snap_mounts"] == [str(nmp / ".snapshot" / "S2")]
        return row

    check("start")
    _, rfinal, _ = revert("vn6", snaps["S1"]["id"])  # S2(N의 원본)와 S3가 지워진다
    assert rfinal["status"] == "Succeeded"
    assert sorted(listing("vn6")) == ["S1"]
    check("source revert to S1")
    delete_snapshot("vn6", "S1")
    assert listing("vn6") == {}
    check("source snapshot S1 delete")
    c.remove()  # 서버가 사라진 뒤의 hard 마운트는 docker rm -f로 지워지지 않는다 (되돌리기 검증)
    delete_volume("vn6")
    v_gone = {"lvs": sorted(x for x in os.listdir("/dev/anf") if x.startswith(lv_name(fsid_of(v)))),
              "mounted": str(NS / tok) in mount_targets()}
    note("AC-06 source volume gone", **v_gone)
    assert v_gone == {"lvs": [], "mounted": False}
    check("source volume delete")

    # agent 재시작 (1): 프로세스만
    agent.stop()
    agent.start()
    check("agent restart", settle=3)

    # agent 재시작 (2): WSL 재시작 흉내. 인스턴스를 멈추고, 마운트를 내리고, LV를 비활성화한 뒤 agent를 띄운다
    lvs = [lv_name(nfsid)] + vol_snap_lvs(nfsid)
    agent.stop()
    t_down = time.time()
    try:
        stop = sh("docker", "stop", instance_name(nfsid))
        tries = {"base": umount_retry(nmp / ".snapshot" / "S2"), "volume": umount_retry(nmp)}
        deact = sh("lvchange", "-an", *[f"anf/{x}" for x in lvs])
        down = {"stop": stop.returncode, "umount_tries": tries, "lvchange": out(deact),
                "attrs": sh("lvs", "--noheadings", "-o", "lv_name,lv_attr", *[f"anf/{x}" for x in lvs]).stdout,
                "instance": instances().get(instance_name(nfsid))}
    finally:
        agent.start(timeout=200)
    t_up = time.time()
    # 같은 마운트의 쓰기가 이어지는지: agent가 뜬 뒤에 시작한 쓰기가 성공할 때까지 기다린다 (최대 240초)
    deadline = time.monotonic() + 240
    resumed = None
    while time.monotonic() < deadline:
        rows = [x.split() for x in d.run("cat /tmp/w.log").stdout.splitlines() if x.strip()]
        later = [x for x in rows if float(x[1]) > t_up and x[3] == "ok"]
        if later:
            resumed = float(later[0][2])
            break
        time.sleep(1)
    fresh = clients()
    fresh.mount(nip, ntok, "3")
    fresh_tree = client_tree(fresh, "/m")
    fresh_tree.pop("W", None)
    fresh_base = client_tree(fresh, "/m/.snapshot/S2")
    note("AC-06 simulated WSL restart", down=down, agent_down_s=round(t_up - t_down, 1),
         write_resumed_after_agent_up_s=round(resumed - t_up, 1) if resumed else None,
         fresh_tree_equal_s2=fresh_tree == s_tree, fresh_base_equal_s2=fresh_base == s_tree,
         exports=exported_paths(exports_file(nfsid)), instance=instances().get(instance_name(nfsid)))
    assert 0 not in tries.values() and deact.returncode == 0
    assert resumed is not None
    assert fresh_tree == s_tree and fresh_base == s_tree
    check("simulated WSL restart")

    d.run("touch /tmp/stop")
    time.sleep(1)
    wlog = d.run("cat /tmp/w.log").stdout
    oks = sum(1 for x in wlog.splitlines() if x.split()[3] == "ok")
    w_host = (nmp / "W").read_text().split()
    note("AC-06 writer file", ok_writes=oks, host_lines=len(w_host), first=w_host[:2], last=w_host[-2:])
    assert w_host == [f"w{i}" for i in range(1, len(w_host) + 1)] and len(w_host) == oks
    for cl in (d, fresh):
        cl.remove()
    delete_volume("vn6n")
