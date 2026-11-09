"""스냅샷 e2e (3/3): 실패와 재시작 복구, NFSv4.1 인스턴스 재시작 (스냅샷 설계 §8).

- AC-11 생성 실패(주입, agent 정지)는 Failed가 되고, 같은 PUT이 Updating으로 회복한다
- AC-12 (a) 생성 지연 중 anf-api SIGKILL (b) WSL 재시작 흉내 뒤 agent 시작 복구 (NFSv3·NFSv4.1 스냅샷)
- AC-15 NFSv4.1 인스턴스 재시작: (a) 살아 있는 클라이언트 (b) 기록만 남은 클라이언트 (c) lease·grace 30·45 (결정 1)

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_snapshot_recovery_live.py -v -s'
"""

import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

import live_api
from live_api import LOC, call, poll
from dataplane_live import (
    create_volume, delete_volume, fsid_of, instance_name, instance_status, instances, lv_name, mount_ip, note, NS,
    one_shot, ops_for, out, POLL, setup_pool, sh, SKIP_UNLESS_ROOT, token,
)
from snapshot_live import (
    create_snapshot, exported_paths, exports_file, instance_etab, instance_log_lines, lv_attrs, snap_lv_name,
    snap_mounts, snap_url, umount_retry, vol_snap_lvs, wait_instance_ready,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]


# --- AC-11 ---


def test_ac11_injected_failure_then_put_recovers(agent, api, clients):
    srv = api(faults={"snapshots/create": {"fail": True}})
    db = srv.db_path
    setup_pool()
    tok = token("sac11a")
    v = create_volume("vs11", tok)
    fsid = fsid_of(v)
    assert one_shot(mount_ip(v), tok, "3", "echo kept > /m/f && sync").returncode == 0
    before = vol_snap_lvs(fsid)
    r = call("PUT", snap_url("vs11", "s11"), {"location": LOC})
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    g = call("GET", snap_url("vs11", "s11")).json()
    note("AC-11 injected failure", seen=seen, final=final, get=g, lvs_before=before,
         lvs_after=vol_snap_lvs(fsid), exports=exports_file(fsid), mounts=snap_mounts(tok))
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError" and final["error"]["message"]
    assert g["properties"] == {"provisioningState": "Failed"}
    assert before == vol_snap_lvs(fsid) == [] and snap_mounts(tok) == []
    assert exported_paths(exports_file(fsid)) == [f"/{tok}"]

    srv.stop()
    api(db=db)
    u = call("PUT", snap_url("vs11", "s11"), {"location": LOC})
    assert u.status == 200, u.raw
    state = u.json()["properties"]["provisioningState"]
    final, seen = poll(u.headers["azure-asyncoperation"], POLL)
    g = call("GET", snap_url("vs11", "s11")).json()
    rd = one_shot(mount_ip(v), tok, "3", "ls -A /m/.snapshot && cat /m/.snapshot/s11/f")
    note("AC-11 recovery PUT", status=u.status, state=state, seen=seen, final=final, get=g, client=out(rd),
         operations=[(o["action"], o["status"]) for o in ops_for(db, g["id"])])
    assert state == "Updating"
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "UPDATE"
    assert g["properties"]["provisioningState"] == "Succeeded" and "snapshotId" in g["properties"]
    assert vol_snap_lvs(fsid) == [snap_lv_name(g["properties"]["snapshotId"])]
    assert rd.returncode == 0 and rd.stdout == "s11\nkept\n"
    delete_volume("vs11")


def test_ac11_agent_down_fails_after_retry_then_put_recovers(agent, api):
    srv = api()
    setup_pool()
    tok = token("sac11b")
    v = create_volume("vs11b", tok)
    fsid = fsid_of(v)
    assert one_shot(mount_ip(v), tok, "3", "echo kept > /m/f && sync").returncode == 0
    agent.stop()
    try:
        t0 = time.monotonic()
        r = call("PUT", snap_url("vs11b", "s11"), {"location": LOC})
        assert r.status == 201
        final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
        elapsed = round(time.monotonic() - t0, 1)
        state = call("GET", snap_url("vs11b", "s11")).json()["properties"]["provisioningState"]
        retries = srv.output().count("is unreachable")
        note("AC-11 agent down", elapsed_seconds=elapsed, seen=sorted(set(seen)), final=final, snapshot_state=state,
             unreachable_log_lines=retries, lvs=vol_snap_lvs(fsid))
        assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError"
        assert state == "Failed"
        assert 55 <= elapsed <= 90
        assert retries > 0
        assert vol_snap_lvs(fsid) == []
    finally:
        agent.start()
    u = call("PUT", snap_url("vs11b", "s11"), {"location": LOC})
    assert u.status == 200 and u.json()["properties"]["provisioningState"] == "Updating", u.raw
    final, seen = poll(u.headers["azure-asyncoperation"], POLL)
    rd = one_shot(mount_ip(v), tok, "3", "cat /m/.snapshot/s11/f")
    note("AC-11 agent back, PUT", seen=seen, final=final, client=out(rd))
    assert final["status"] == "Succeeded"
    assert rd.returncode == 0 and rd.stdout == "kept\n"
    delete_volume("vs11b")


# --- AC-12 ---


def test_ac12a_anf_api_sigkill_during_snapshot_create(agent, api):
    delay = 10
    srv = api(faults={"snapshots/create": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    tok = token("sac12a")
    v = create_volume("vs12a", tok)
    fsid = fsid_of(v)
    assert one_shot(mount_ip(v), tok, "3", "echo before > /m/f && sync").returncode == 0
    r = call("PUT", snap_url("vs12a", "s12"), {"location": LOC})
    assert r.status == 201
    rid = r.json()["id"]
    time.sleep(2)
    rc = srv.sigkill()
    at_kill = [(o["action"], o["status"]) for o in ops_for(db, rid)]
    lvs_at_kill = vol_snap_lvs(fsid)
    api(db=db)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    g = call("GET", snap_url("vs12a", "s12")).json()
    rd = one_shot(mount_ip(v), tok, "3", "cat /m/.snapshot/s12/f")
    note("AC-12a", sigkill_rc=rc, operations_at_kill=at_kill, lvs_at_kill=lvs_at_kill, seen=seen, final=final,
         get=g, client=out(rd), lvs=vol_snap_lvs(fsid))
    assert at_kill == [("CREATE", "Creating")] and lvs_at_kill == []
    assert final["status"] == "Succeeded"
    assert g["properties"]["provisioningState"] == "Succeeded"
    assert vol_snap_lvs(fsid) == [snap_lv_name(g["properties"]["snapshotId"])]
    assert rd.returncode == 0 and rd.stdout == "before\n"
    delete_volume("vs12a")


def test_ac12b_agent_restart_recovers_snapshots_after_simulated_wsl_restart(agent, api):
    api()
    setup_pool()
    vols = {"NFSv3": ("vs12v3", token("sac12b3"), "3"), "NFSv4.1": ("vs12v4", token("sac12b4"), "4.1")}
    made = {}
    for protocol, (name, tok, vers) in vols.items():
        v = create_volume(name, tok, protocols=[protocol])
        ip = mount_ip(v)
        assert one_shot(ip, tok, vers, "echo one > /m/f && sync").returncode == 0
        s1, _ = create_snapshot(name, "S1")
        assert one_shot(ip, tok, vers, "echo two > /m/f && sync").returncode == 0
        s2, _ = create_snapshot(name, "S2")
        assert one_shot(ip, tok, vers, "echo three > /m/f && sync").returncode == 0
        made[protocol] = {"name": name, "tok": tok, "vers": vers, "ip": ip, "fsid": fsid_of(v),
                          "lvs": [lv_name(fsid_of(v)), snap_lv_name(s1["properties"]["snapshotId"]),
                                  snap_lv_name(s2["properties"]["snapshotId"])]}

    agent.stop()
    try:
        # WSL 재시작 흉내: 인스턴스 정지 → 스냅샷·볼륨 언마운트 → LV 비활성화 (실제 재시작 뒤에는 LV가 모두 꺼져 있다)
        down = {}
        for protocol, m in made.items():
            stop = sh("docker", "stop", instance_name(m["fsid"]))
            tries = {name: umount_retry(NS / m["tok"] / ".snapshot" / name) for name in ("S1", "S2")}
            tries["volume"] = umount_retry(NS / m["tok"])
            deact = sh("lvchange", "-an", *[f"anf/{lv}" for lv in m["lvs"]])
            refused = one_shot(m["ip"], m["tok"], m["vers"])
            down[protocol] = {"docker_stop_rc": stop.returncode, "umount_tries": tries, "lvchange": out(deact),
                              "attrs": lv_attrs(*m["lvs"]), "mounts": snap_mounts(m["tok"]),
                              "instance": instances().get(instance_name(m["fsid"])), "mount_while_down": refused.returncode}
        note("AC-12b simulated restart", down=down)
        for protocol, d in down.items():
            assert 0 not in d["umount_tries"].values() and d["lvchange"]["rc"] == 0, (protocol, d)
            assert all(a[4] != "a" for a in d["attrs"].values()), (protocol, d["attrs"])  # 비활성
            assert d["mounts"] == [] and d["instance"] == "exited" and d["mount_while_down"] != 0
    finally:
        t0 = time.monotonic()
        agent.start(timeout=200)
        start_seconds = round(time.monotonic() - t0, 1)
    up = {}
    for protocol, m in made.items():
        rd = one_shot(m["ip"], m["tok"], m["vers"], "cat /m/f /m/.snapshot/S1/f /m/.snapshot/S2/f")
        up[protocol] = {"read": out(rd), "attrs": lv_attrs(*m["lvs"]), "mounts": snap_mounts(m["tok"]),
                        "etab": exported_paths(instance_etab(m["fsid"])), "instance": instance_status(m["fsid"])}
    note("AC-12b after agent start", agent_start_seconds=start_seconds, up=up)
    for protocol, m in made.items():
        u = up[protocol]
        assert u["read"]["rc"] == 0 and u["read"]["stdout"] == "three\none\ntwo\n", (protocol, u)
        assert all(a[4] == "a" for a in u["attrs"].values()), (protocol, u["attrs"])  # 스냅샷 LV도 다시 켜졌다 (-kn)
        assert u["etab"] == [f"/{m['tok']}", f"/{m['tok']}/.snapshot/S1", f"/{m['tok']}/.snapshot/S2"]
    for m in made.values():
        delete_volume(m["name"])


# --- AC-15 ---


def reclaimable_records(fsid: str) -> dict:
    """멈춘 인스턴스의 nfsdcld DB를 꺼내 되찾을 클라이언트 기록 수를 센다 (진입점 reclaimable()과 같은 질의)."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "main.sqlite"
        cp = sh("docker", "cp", f"{instance_name(fsid)}:/var/lib/nfs/nfsdcld/main.sqlite", str(dst))
        if cp.returncode != 0:
            return {"error": cp.stderr.strip()}
        conn = sqlite3.connect(dst)
        try:
            grace = conn.execute("select current, recovery from grace").fetchone()
            tables = [r[0] for r in conn.execute("select name from sqlite_master where name like 'rec-%'")]
            counts = {t: conn.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables}
        finally:
            conn.close()
    return {"grace_current_recovery": grace, "records": counts}


def test_ac15_nfsv41_instance_restart_with_client_records(agent, api, clients):
    api()
    setup_pool()
    tok = token("sac15")
    v = create_volume("vs15", tok, protocols=["NFSv4.1"])
    ip, fsid = mount_ip(v), fsid_of(v)
    name = instance_name(fsid)

    # (c) ONTAP 기본값 lease 30초, grace 45초
    lg = sh("docker", "exec", name, "cat", "/proc/fs/nfsd/nfsv4leasetime", "/proc/fs/nfsd/nfsv4gracetime")
    serving = instance_log_lines(fsid, "anf-nfs: serving")
    note("AC-15c lease/grace", proc=out(lg), serving=serving)
    assert lg.stdout.split() == ["30", "45"]
    assert serving and "lease=30 grace=45" in serving[-1]

    live = clients()
    live.mount(ip, tok, "4.1")
    assert live.run("echo one > /m/f && sync").returncode == 0
    create_snapshot("vs15", "S")
    w = live.run("echo two >> /m/f && sync && cat /m/.snapshot/S/f && grep ' /m ' /proc/mounts")
    assert w.returncode == 0 and w.stdout.splitlines()[0] == "one", out(w)
    mounts_before = live.run("grep -c ' nfs4 ' /proc/mounts").stdout.strip()

    # (a) 살아 있는 클라이언트가 마운트를 유지한 채 인스턴스를 docker stop·start
    stop = sh("docker", "stop", "-t", "30", name)
    t0 = time.monotonic()
    start = sh("docker", "start", name)
    ready = wait_instance_ready(fsid)
    t1 = time.monotonic()
    io = live.run("cat /m/f && echo three >> /m/f && sync && cat /m/.snapshot/S/f", timeout=200)
    io_seconds = round(time.monotonic() - t1, 2)
    mounts_after = live.run("grep -c ' nfs4 ' /proc/mounts").stdout.strip()
    st = instance_status(fsid)
    note("AC-15a live client", stop=out(stop), start=out(start), ready_seconds=ready, io_seconds=io_seconds,
         io=out(io), nfs4_mounts_before_after=[mounts_before, mounts_after], instance=st,
         grace_lines=instance_log_lines(fsid, "grace period"))
    assert stop.returncode == 0 and start.returncode == 0
    assert 0 <= ready < 150 and st["v4_end_grace"] == "Y"
    assert io.returncode == 0 and io.stdout == "one\ntwo\none\n", out(io)
    assert mounts_before == mounts_after
    # 서버가 살아 있을 때 깔끔히 내리면 기록이 지워진다 (DESTROY_CLIENTID). 스냅샷 하위 마운트부터 내린다
    clean = live.run("for x in $(grep ' /m/' /proc/mounts | cut -d' ' -f2 | sort -r); do umount $x; done; umount /m")
    assert clean.returncode == 0, out(clean)
    live.remove()

    # (b) 기록만 남은 클라이언트: agent를 멈추고 인스턴스를 멈춘 동안 클라이언트를 지운 뒤 agent 시작 복구가 인스턴스를 띄운다.
    # 클라이언트는 soft 마운트다: hard 마운트는 서버가 없는 동안 커널의 마운트 정리가 끝나지 않아 컨테이너가 지워지지 않고,
    # 서버가 돌아오면 그 클라이언트가 상태를 되찾아 버린다 (1회차 첫 실행에서 관찰, 통합 테스트도 soft를 쓴다)
    dead = clients()
    dead.mount(ip, tok, "4.1", opts="soft,timeo=20,retrans=1")
    assert dead.run("echo four >> /m/f && sync").returncode == 0
    agent.stop()
    try:
        assert sh("docker", "stop", "-t", "30", name).returncode == 0
        t_rm = time.monotonic()
        rm = sh("docker", "rm", "-f", dead.name)
        rm_seconds = round(time.monotonic() - t_rm, 1)
        gone = sh("docker", "inspect", dead.name).returncode != 0
        records = reclaimable_records(fsid)
    finally:
        t0 = time.monotonic()
        agent.start(timeout=200)
        agent_seconds = round(time.monotonic() - t0, 1)
    st = instance_status(fsid)
    grace = instance_log_lines(fsid, "grace period")
    t1 = time.monotonic()
    new = one_shot(ip, tok, "4.1", "echo five >> /m/f && cat /m/f /m/.snapshot/S/f")
    new_seconds = round(time.monotonic() - t1, 2)
    note("AC-15b dead client record via agent recovery", client_rm=out(rm), client_rm_seconds=rm_seconds,
         client_gone=gone, nfsdcld=records, agent_start_seconds=agent_seconds, instance=st, grace_lines=grace,
         new_client=out(new), new_client_seconds=new_seconds)
    # 전제: 기록만 남고 되찾는 클라이언트가 없다. 서버가 없는 동안에는 soft 마운트여도 `docker rm -f`가
    # "did not receive an exit event"로 실패할 수 있어(커널의 NFS 마운트 정리가 끝나지 않는다) 컨테이너 제거 여부가 아니라
    # 서버에서 관찰한 것으로 판정한다: nfsdcld 기록이 있고, 유예 기간이 grace(45초)에 가깝게 끝까지 돌았다
    assert sum(records["records"].values()) >= 1, records
    waited = int(grace[-1].rsplit(" after ", 1)[1].split()[0])
    assert grace[-2].startswith("anf-nfs: grace period: waiting for") and waited >= 30, grace  # 되찾는 클라이언트 없음
    assert agent_seconds < 150 and st["ready"] and st["v4_end_grace"] == "Y"
    assert new.returncode == 0 and new.stdout == "one\ntwo\nthree\nfour\nfive\none\n", out(new)
    delete_volume("vs15")
