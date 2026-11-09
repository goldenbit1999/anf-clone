"""스냅샷에서 새 볼륨 e2e (2/2): API 계약, 거절, 충돌·원본 보호, 실패와 회복, 재시작 안전, agent API (복원 설계 §8).

- AC-01 snapshotId PUT의 응답·헤더·작업 상태·Location 조회, 끝난 뒤 GET, base 스냅샷 (지연 주입)
- AC-07 거절은 볼륨 행·작업을 만들지 않고 원본을 바꾸지 않는다. 재PUT·PATCH의 snapshotId
- AC-08 생성 중 원본 보호, 원본에 진행 중 작업이 있을 때의 N PUT
- AC-09 (a) 주입한 실패 → 같은 PUT (b) agent 중단 → 같은 PUT (c) 지연 중 anf-api SIGKILL
  (기준 밖) agent job 중 agent SIGKILL → 진행 표시가 남은 볼륨을 같은 요청이 끝낸다
- AC-10 agent `POST /api/storage/volumes` + `clone`

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_restore_new_volume_contract_live.py -v -s'
"""

import signal
import time
import uuid

import pytest

import live_api
from live_api import LOC, OTHER_RG, OTHER_SUB, RG, SUB, TIB, call, create_account, create_pool, location_url, poll
from dataplane_live import (
    ACCT, agent_call, agent_job, create_volume, db_ops, db_rows, delete_volume, error_of, fsid_of, GIB, lv_name,
    lvs_volumes, mount_ip, note, NS, one_shot, ops_for, out, POLL, POOL, setup_pool, sh, SKIP_UNLESS_ROOT, token,
    vol_body, vol_path, vol_url,
)
from snapshot_live import NOT_FOUND, create_snapshot, delete_snapshot, op_seconds, snap_lvs, snap_url, vol_snap_lvs
from revert_live import (
    build_history, client_tree, identity, listing, mount_targets, post_revert, revert, tree,
)
from restore_live import cl_tags, put_restore, restore_body, restore_volume, state_in

# 기록(16 MiB)을 쓰므로 Manual 풀과 DATA_MIBPS 한도로 볼륨을 만든다 (처리량 설계 결정 17)
pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT,
              pytest.mark.usefixtures("manual_data")]

ACCT2 = "e2e-vol-acct2"
SNAPSHOT_ID_MSG = ("The 'properties.snapshotId' property must be a snapshot resource ID: /subscriptions/{id}"
                   "/resourceGroups/{group}/providers/Microsoft.NetApp/netAppAccounts/{account}/capacityPools/{pool}"
                   "/volumes/{volume}/snapshots/{snapshot}.")
PROTECT = ("Cannot {verb} '{rid}' because volume '{nid}' is being created from snapshot '{sid}'. Wait until it is "
           "created, or delete it, and then retry.")
BUSY = ("Cannot create volume '{nid}' from snapshot '{sid}' because an operation is in progress on '{rid}'. "
        "Wait until it is finished, and then retry.")


def source_volume(clients, name: str, tag: str, size=GIB, protocol="NFSv3", vers="3"):
    """원본 볼륨 V와 기록(S1 → S2 → S3 → 또 바꿈). 반환: (V, 토큰, 클라이언트, 스냅샷)."""
    tok = token(tag)
    v = create_volume(name, tok, size=size, protocols=[protocol])
    c = clients()
    c.mount(mount_ip(v), tok, vers)
    return v, tok, c, build_history(c, name)


def small_source(name: str, tag: str, size=GIB, snaps=("S",), acct=ACCT):
    """파일 하나(a=one)와 스냅샷들을 가진 원본 볼륨. 반환: (V, 토큰, 이름 → 스냅샷 GET)."""
    tok = token(tag)
    v = create_volume(name, tok, size=size, acct=acct)
    w = one_shot(mount_ip(v), tok, "3", "echo one > /m/a && sync")
    assert w.returncode == 0, out(w)
    return v, tok, {s: create_snapshot(name, s, acct=acct)[0] for s in snaps}


def assert_from_s2(c, name: str, ntok: str, n: dict, s_tree: dict) -> dict:
    """AC-02와 같은 결과: N 트리 = S2, `.snapshot`에 base S2만, ARM 목록도 S2 하나, 진행 표시 없음."""
    c.mount(mount_ip(n), ntok, "3")
    seen = {"tree_equal_s2": client_tree(c, "/m") == s_tree,
            "base_equal_s2": client_tree(c, "/m/.snapshot/S2") == s_tree,
            "snapshot_dir": c.run("ls -A /m/.snapshot").stdout.split(), "list": sorted(listing(name)),
            "agent_snapshots": [x["name"] for x in agent_call(
                "GET", f"/api/storage/volumes/{fsid_of(n)}/snapshots")[1]["records"]],
            "cl_tags": cl_tags(fsid_of(n)),
            "originatingResourceId": n["properties"].get("originatingResourceId")}
    assert seen["tree_equal_s2"] and seen["base_equal_s2"], seen
    assert seen["snapshot_dir"] == ["S2"] and seen["list"] == ["S2"] and seen["agent_snapshots"] == ["S2"], seen
    assert seen["cl_tags"] == []
    return seen


def put_same(name: str, ntok: str, snapshot_id: str, timeout=POLL) -> tuple:
    u = put_restore(name, ntok, snapshot_id)
    assert u.status == 200, u.raw
    final, seen = poll(u.headers["azure-asyncoperation"], timeout)
    g = call("GET", vol_url(ACCT, POOL, name))
    return u, final, seen, g.json()


# --- AC-01 ---


def test_ac01_contract_and_states(agent, api, clients):
    delay = 5
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("nac01")
    # V는 기본값이 아닌 NFSv4.1·0755로 만든다: N이 주지 않은 값을 V에서 받는지 볼 수 있다 (결정 3)
    rv = call("PUT", vol_url(ACCT, POOL, "vn1"), vol_body(tok, protocols=["NFSv4.1"], unixPermissions="0755"))
    assert rv.status == 201, rv.raw
    vfinal, _ = poll(rv.headers["azure-asyncoperation"], POLL)
    assert vfinal["status"] == "Succeeded"
    v = call("GET", vol_url(ACCT, POOL, "vn1")).json()
    w = one_shot(mount_ip(v), tok, "4.1", "echo snap > /m/f && sync")
    assert w.returncode == 0, out(w)
    s, _ = create_snapshot("vn1", "S")
    assert one_shot(mount_ip(v), tok, "4.1", "echo later > /m/f && sync").returncode == 0
    srv.stop()
    api(faults={"volumes/create": {"delaySeconds": delay}}, db=db)
    ntok = token("nac01n")
    nid = vol_path(ACCT, POOL, "vn1n")
    r = put_restore("vn1n", ntok, s["id"])
    body = r.json()
    during_vol = call("GET", vol_url(ACCT, POOL, "vn1n")).json()
    during_op = call("GET", r.headers["azure-asyncoperation"]).json()
    final, seen = poll(r.headers["azure-asyncoperation"], POLL + delay)
    loc = call("GET", r.headers["location"])
    g = call("GET", vol_url(ACCT, POOL, "vn1n")).json()
    gp, vp = g["properties"], v["properties"]
    nlist = listing("vn1n")
    rd = one_shot(mount_ip(g), ntok, "4.1", "cat /m/f && ls -A /m/.snapshot && stat -c %a /m && cat /m/.snapshot/S/f")
    note("AC-01", plain_create_headers=sorted(rv.headers), status=r.status, headers=r.headers, body=body,
         during_volume_state=during_vol["properties"]["provisioningState"], during_op=during_op, seen=seen,
         final=final, op_seconds=op_seconds(final), location_status=loc.status, location_body=loc.json(),
         get=gp, v={k: vp[k] for k in ("fileSystemId", "mountTargets", "protocolTypes", "unixPermissions")},
         list=nlist, source_snapshot=s["properties"], read=out(rd),
         ops=[(o["action"], o["status"]) for o in ops_for(db, nid)])
    # 일반 생성 201은 Azure-AsyncOperation 하나 (녹화 V1), 스냅샷에서 만드는 생성 201은 둘 (녹화 R4, §9 1번)
    assert "azure-asyncoperation" in rv.headers and "location" not in rv.headers
    assert r.status == 201
    assert "/operationResults/" in r.headers["azure-asyncoperation"]
    assert r.headers["location"] == location_url(r.headers["azure-asyncoperation"])
    assert body["id"] == nid and body["properties"]["provisioningState"] == "Creating"
    assert body["properties"]["snapshotId"] == s["id"]
    assert "originatingResourceId" not in body["properties"] and "mountTargets" not in body["properties"]
    assert during_vol["properties"]["provisioningState"] == "Creating"
    assert during_op["status"] == "Creating" and during_op["properties"] == {"resourceName": nid, "action": "CREATE"}
    assert seen[0] == "Creating" and seen[-1] == "Succeeded" and set(seen) == {"Creating", "Succeeded"}
    assert final["properties"] == {"resourceName": nid, "action": "CREATE"} and op_seconds(final) >= delay
    assert loc.status == 200 and loc.json()["id"] == nid
    assert loc.json()["properties"]["provisioningState"] == "Succeeded"
    assert gp["provisioningState"] == "Succeeded"
    assert gp["snapshotId"] == s["id"] and gp["originatingResourceId"] == s["id"]
    assert gp["fileSystemId"] != vp["fileSystemId"]
    assert gp["mountTargets"][0]["ipAddress"] != vp["mountTargets"][0]["ipAddress"]
    assert "cloneProgress" not in gp
    assert gp["protocolTypes"] == ["NFSv4.1"] and gp["unixPermissions"] == "0755"
    assert sorted(nlist) == ["S"]
    base = nlist["S"]["properties"]
    assert base["provisioningState"] == "Succeeded"
    assert base["snapshotId"] != s["properties"]["snapshotId"] and base["created"] == s["properties"]["created"]
    assert rd.returncode == 0 and rd.stdout.split() == ["snap", "S", "755", "snap"], out(rd)
    assert [(o["action"], o["status"]) for o in ops_for(db, nid)] == [("CREATE", "Succeeded")]
    delete_volume("vn1n")
    delete_volume("vn1")


# --- AC-07 ---


def test_ac07_rejections_create_nothing(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    create_account(ACCT2)
    create_pool(ACCT2, POOL, 4 * TIB, "Premium", qos_type="Manual")  # vol_body가 throughputMibps를 넣는다 (결정 17)
    v, tok, snaps = small_source("vn7", "nac07", size=2 * GIB, snaps=("S", "S9"))
    s, s9 = snaps["S"], snaps["S9"]
    vb, _, snaps_b = small_source("vn7b", "nac07b", snaps=("SB",), acct=ACCT2)
    sb = snaps_b["SB"]
    ntok = token("nac07n")
    nid = vol_path(ACCT, POOL, "vn7n")

    def state():
        return {"ops": len(db_ops(db)), "rows": sorted(x["id"] for x in db_rows(db)), "tree": tree(NS / tok),
                "list": {k: identity(x) for k, x in listing("vn7").items()}, "lvs": sorted(lvs_volumes()),
                "snap_lvs": sorted(snap_lvs())}

    st0 = state()
    other_rg = s["id"].replace(f"/resourceGroups/{RG}/", f"/resourceGroups/{OTHER_RG}/")
    other_sub = s["id"].replace(f"/subscriptions/{SUB}/", f"/subscriptions/{OTHER_SUB}/")
    same_acct = "The snapshot '{sid}' must be in the same NetApp account as the new volume '" + nid + "'."
    cases = [
        ("snapshotId is a number", restore_body(ntok, 5, 2 * GIB), 400, "InvalidRequestContent", SNAPSHOT_ID_MSG),
        ("snapshotId is not an ID", restore_body(ntok, "S", 2 * GIB), 400, "InvalidRequestContent",
         SNAPSHOT_ID_MSG),
        ("snapshotId is a volume ID", restore_body(ntok, v["id"], 2 * GIB), 400, "InvalidRequestContent",
         SNAPSHOT_ID_MSG),
        ("other account's snapshot", restore_body(ntok, sb["id"], 2 * GIB), 400, "BadRequest",
         same_acct.format(sid=sb["id"])),
        ("(extra) other resource group", restore_body(ntok, other_rg, 2 * GIB), 400, "BadRequest",
         same_acct.format(sid=other_rg)),
        ("(extra) other subscription", restore_body(ntok, other_sub, 2 * GIB), 400, "BadRequest",
         same_acct.format(sid=other_sub)),
        ("missing snapshot under the volume", restore_body(ntok, f"{v['id']}/snapshots/nope", 2 * GIB), 404,
         "ResourceNotFound", NOT_FOUND.format(snap="nope", a=ACCT, p=POOL, v="vn7")),
        ("smaller than the source volume", restore_body(ntok, s["id"], GIB), 400, "BadRequest",
         "The 'properties.usageThreshold' of a volume created from a snapshot must be at least the source "
         "volume's 2 GiB."),
        ("deleteBaseSnapshot true", restore_body(ntok, s["id"], 2 * GIB, deleteBaseSnapshot=True), 400,
         "InvalidRequestContent", "The property 'properties.deleteBaseSnapshot' is not supported by this ANF clone."),
        ("(extra) deleteBaseSnapshot not a boolean", restore_body(ntok, s["id"], 2 * GIB, deleteBaseSnapshot="no"),
         400, "InvalidRequestContent", None),
        ("bigger than the pool's free space", restore_body(ntok, s["id"], 4 * TIB), 400, "BadRequest",
         "Pool size too small for total volume size."),
    ]
    results = {label: error_of(call("PUT", vol_url(ACCT, POOL, "vn7n"), body)) for label, body, *_ in cases}
    get_n = error_of(call("GET", vol_url(ACCT, POOL, "vn7n")))
    st1 = state()
    note("AC-07 body and source rejections", results=results, get_new_volume=get_n,
         ops=(st0["ops"], st1["ops"]), unchanged=st1 == st0)
    for label, _, status, code, message in cases:
        assert results[label][:2] == (status, code), (label, results[label])
        if message is not None:
            assert results[label][2] == message, (label, results[label])
    assert get_n[:2] == (404, "ResourceNotFound")
    assert st1 == st0

    # Failed 스냅샷, Failed 원본 볼륨 (같은 DB, 결함을 주입한 서버)
    srv.stop()
    srv = api(faults={"snapshots/create": {"fail": True}, "volumes/patch": {"fail": True}}, db=db)
    p = call("PUT", snap_url("vn7", "SF"), {"location": LOC})
    sf_final, _ = poll(p.headers["azure-asyncoperation"], POLL)
    sf = call("GET", snap_url("vn7", "SF")).json()
    n_ops = len(db_ops(db))
    from_failed_snap = error_of(put_restore("vn7n", ntok, sf["id"], 2 * GIB))
    ops_after_snap = len(db_ops(db))
    patch = call("PATCH", vol_url(ACCT, POOL, "vn7"), {"tags": {"k": "v"}})
    patch_final, _ = poll(patch.headers["azure-asyncoperation"], POLL)
    v_state = state_in("vn7")
    n_ops2 = len(db_ops(db))
    from_failed_vol = error_of(put_restore("vn7n", ntok, s["id"], 2 * GIB))
    n_ops3 = len(db_ops(db))
    note("AC-07 failed snapshot / (extra) failed source volume", sf_final=sf_final, sf=sf,
         from_failed_snapshot=from_failed_snap, ops=(n_ops, ops_after_snap), patch_final=patch_final,
         v_state=v_state, from_failed_volume=from_failed_vol, ops2=(n_ops2, n_ops3),
         tree_same=tree(NS / tok) == st0["tree"])
    assert sf_final["status"] == "Failed" and sf["properties"]["provisioningState"] == "Failed"
    assert from_failed_snap == (400, "BadRequest", f"Volume cannot be created from snapshot '{sf['id']}' because "
                                                   "the snapshot isn't in state succeeded.")
    assert ops_after_snap == n_ops
    assert patch_final["status"] == "Failed" and v_state == "Failed"
    assert from_failed_vol == (400, "BadRequest", f"Volume cannot be created from snapshot '{s['id']}' because its "
                                                  "volume isn't in state succeeded.")
    assert n_ops3 == n_ops2
    assert tree(NS / tok) == st0["tree"]

    # V를 회복하고 N을 만든다. deleteBaseSnapshot: false는 받는다 (기준 밖)
    srv.stop()
    api(db=db)
    u = call("PUT", vol_url(ACCT, POOL, "vn7"), vol_body(tok, 2 * GIB, ["NFSv3"]))
    assert u.status == 200 and poll(u.headers["azure-asyncoperation"], POLL)[0]["status"] == "Succeeded"
    _, final, _, n = restore_volume("vn7n", ntok, s["id"], size=2 * GIB, deleteBaseSnapshot=False)
    n_ops = len(db_ops(db))
    later = {
        "re-PUT other snapshotId": call("PUT", vol_url(ACCT, POOL, "vn7n"), restore_body(ntok, s9["id"], 2 * GIB)),
        "PATCH other snapshotId": call("PATCH", vol_url(ACCT, POOL, "vn7n"), {"properties": {"snapshotId": s9["id"]}}),
        "plain volume re-PUT adds snapshotId": call("PUT", vol_url(ACCT, POOL, "vn7"),
                                                    restore_body(tok, s["id"], 2 * GIB)),
        "(extra) plain volume PATCH adds snapshotId": call("PATCH", vol_url(ACCT, POOL, "vn7"),
                                                           {"properties": {"snapshotId": s["id"]}}),
    }
    later_results = {k: error_of(x) for k, x in later.items()}
    n_ops_after = len(db_ops(db))
    same = put_restore("vn7n", ntok, s["id"], 2 * GIB)
    same_final, _ = poll(same.headers["azure-asyncoperation"], POLL)
    upper = put_restore("vn7n", ntok, s["id"].upper(), 2 * GIB)
    upper_final, _ = poll(upper.headers["azure-asyncoperation"], POLL)
    g = call("GET", vol_url(ACCT, POOL, "vn7n")).json()
    note("AC-07 snapshotId on update", later=later_results, ops=(n_ops, n_ops_after),
         same=(same.status, same.json()["properties"]["provisioningState"], sorted(same.headers), same_final["status"]),
         upper=(upper.status, upper_final["status"]), get=g["properties"], list=sorted(listing("vn7n")),
         cl_tags=cl_tags(fsid_of(n)), base_lvs=vol_snap_lvs(fsid_of(n)))
    for k in later:
        assert later_results[k] == (400, "BadRequest", "SnapshotId cannot be changed."), (k, later_results[k])
    assert n_ops_after == n_ops
    assert same.status == 200 and same.json()["properties"]["provisioningState"] == "Updating"
    assert same_final["status"] == "Succeeded"
    assert upper.status == 200 and upper_final["status"] == "Succeeded"
    assert g["properties"]["snapshotId"] == s["id"] and g["properties"]["originatingResourceId"] == s["id"]
    assert sorted(listing("vn7n")) == ["S"] and len(vol_snap_lvs(fsid_of(n))) == 1 and cl_tags(fsid_of(n)) == []
    delete_volume("vn7n")
    delete_volume("vn7")
    delete_volume("vn7b", acct=ACCT2)


# --- AC-08 ---


def test_ac08_conflicts_and_source_protection(agent, api, clients):
    delay = 20
    srv = api()
    db = srv.db_path
    setup_pool()
    v, tok, snaps = small_source("vn8", "nac08", snaps=("S0", "S", "S9"))
    vid, s0, s = v["id"], snaps["S0"], snaps["S"]
    srv.stop()
    srv = api(faults={"volumes/create": {"delaySeconds": delay}}, db=db)
    ntok = token("nac08n")
    nid = vol_path(ACCT, POOL, "vn8n")
    t0 = time.monotonic()
    r = put_restore("vn8n", ntok, s["id"])
    assert r.status == 201, r.raw
    n_ops = len(db_ops(db))
    attempts = {
        "S DELETE": call("DELETE", snap_url("vn8", "S")),
        "V DELETE": call("DELETE", vol_url(ACCT, POOL, "vn8")),
        "V revert to S0": post_revert("vn8", s0["id"]),
        "V revert to S": post_revert("vn8", s["id"]),
    }
    elapsed = round(time.monotonic() - t0, 2)
    still = state_in("vn8n")
    results = {k: error_of(x) for k, x in attempts.items()}
    n_ops_after = len(db_ops(db))
    v_state, s_state = state_in("vn8"), call("GET", snap_url("vn8", "S")).json()["properties"]["provisioningState"]
    # (기준 밖, §9 8번) 원본 볼륨의 다른 스냅샷 DELETE는 막지 않는다
    other = call("DELETE", snap_url("vn8", "S9"))
    other_final, _ = poll(other.headers["azure-asyncoperation"], POLL)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL + delay)
    note("AC-08 during Creating", attempts_elapsed_s=elapsed, new_volume_state=still, results=results,
         ops=(n_ops, n_ops_after), v_state=v_state, s_state=s_state, other_snapshot_delete=(other.status,
                                                                                            other_final["status"]),
         final=final["status"], seen=sorted(set(seen)))
    assert elapsed < delay and still == "Creating"
    assert results["S DELETE"] == (409, "Conflict", PROTECT.format(verb="delete", rid=s["id"], nid=nid, sid=s["id"]))
    assert results["V DELETE"] == (409, "Conflict", PROTECT.format(verb="delete", rid=vid, nid=nid, sid=s["id"]))
    for k in ("V revert to S0", "V revert to S"):
        assert results[k] == (409, "Conflict", PROTECT.format(verb="revert", rid=vid, nid=nid, sid=s["id"])), k
    assert n_ops_after == n_ops and v_state == "Succeeded" and s_state == "Succeeded"
    assert other.status == 202 and other_final["status"] == "Succeeded"
    assert final["status"] == "Succeeded"

    # N이 Succeeded가 된 뒤에는 받아진다: S DELETE → V revert → V DELETE
    after = {"S DELETE": delete_snapshot("vn8", "S")["status"]}
    _, rfinal, _ = revert("vn8", s0["id"])
    after["V revert to S0"] = rfinal["status"]
    after["V DELETE"] = delete_volume("vn8")["status"]
    n = call("GET", vol_url(ACCT, POOL, "vn8n")).json()
    rd = one_shot(mount_ip(n), ntok, "3", "cat /m/a /m/.snapshot/S/a && ls -A /m/.snapshot")
    note("AC-08 after Succeeded", after=after, read=out(rd), list=sorted(listing("vn8n")))
    assert after == {"S DELETE": "Succeeded", "V revert to S0": "Succeeded", "V DELETE": "Succeeded"}
    assert rd.returncode == 0 and rd.stdout.split() == ["one", "one", "S"]

    # 원본에 진행 중 작업이 있을 때 N PUT → 409
    srv.stop()
    srv = api(db=db)
    v2, tok2, snaps2 = small_source("vn8b", "nac08b", snaps=("T0",))
    srv.stop()
    api(faults={"snapshots/create": {"delaySeconds": 15}, "volumes/patch": {"delaySeconds": 15}}, db=db)
    p = call("PUT", snap_url("vn8b", "T1"), {"location": LOC})
    assert p.status == 201, p.raw
    t1_id = p.json()["id"]
    n_ops = len(db_ops(db))
    nc, nd = vol_path(ACCT, POOL, "vn8c"), vol_path(ACCT, POOL, "vn8d")
    during_snapshot = error_of(put_restore("vn8c", token("nac08c"), t1_id))
    p_final, _ = poll(p.headers["azure-asyncoperation"], POLL + 15)
    pa = call("PATCH", vol_url(ACCT, POOL, "vn8b"), {"tags": {"k": "v"}})
    assert pa.status == 202, pa.raw
    during_patch = error_of(put_restore("vn8d", token("nac08d"), snaps2["T0"]["id"]))
    pa_final, _ = poll(pa.headers["azure-asyncoperation"], POLL + 15)
    n_ops_after = len(db_ops(db))
    gets = {x: error_of(call("GET", vol_url(ACCT, POOL, x)))[:2] for x in ("vn8c", "vn8d")}
    note("AC-08 source busy", during_snapshot_create=during_snapshot, during_volume_patch=during_patch,
         snapshot_final=p_final["status"], patch_final=pa_final["status"], ops=(n_ops, n_ops_after), gets=gets)
    assert during_snapshot == (409, "Conflict", BUSY.format(nid=nc, sid=t1_id, rid=t1_id))
    assert during_patch == (409, "Conflict", BUSY.format(nid=nd, sid=snaps2["T0"]["id"], rid=v2["id"]))
    # 사이에 끝난 PATCH 작업 하나만 늘었다 (T1 생성 작업은 PUT 전에 생겼다)
    assert n_ops_after == n_ops + 1
    assert p_final["status"] == "Succeeded" and pa_final["status"] == "Succeeded"
    assert gets == {"vn8c": (404, "ResourceNotFound"), "vn8d": (404, "ResourceNotFound")}
    delete_volume("vn8n")
    delete_volume("vn8b")


# --- AC-09 ---


def test_ac09a_injected_failure_then_same_put_recovers(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = source_volume(clients, "vn9a", "nac09a")
    vid, s2 = v["id"], snaps["S2"]
    s_tree = tree(NS / tok / ".snapshot" / "S2")
    before = {"tree": tree(NS / tok), "list": {k: identity(x) for k, x in listing("vn9a").items()},
              "lvs": sorted(lvs_volumes()), "snap_lvs": sorted(snap_lvs())}
    srv.stop()
    srv = api(faults={"volumes/create": {"fail": True}}, db=db)
    ntok = token("nac09an")
    nid = vol_path(ACCT, POOL, "vn9an")
    r = put_restore("vn9an", ntok, s2["id"])
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    n_state = state_in("vn9an")
    protect = {"S2 DELETE": error_of(call("DELETE", snap_url("vn9a", "S2"))),
               "V DELETE": error_of(call("DELETE", vol_url(ACCT, POOL, "vn9a"))),
               "V revert": error_of(post_revert("vn9a", snaps["S1"]["id"]))}
    after = {"tree": tree(NS / tok), "list": {k: identity(x) for k, x in listing("vn9a").items()},
             "lvs": sorted(lvs_volumes()), "snap_lvs": sorted(snap_lvs())}
    note("AC-09a injected failure", seen=seen, final=final, new_volume_state=n_state, protection=protect,
         source_unchanged=after == before)
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError"
    assert "Injected fault" in final["error"]["message"]
    assert n_state == "Failed"
    assert after == before
    assert protect["S2 DELETE"] == (409, "Conflict", PROTECT.format(verb="delete", rid=s2["id"], nid=nid,
                                                                    sid=s2["id"]))
    assert protect["V DELETE"] == (409, "Conflict", PROTECT.format(verb="delete", rid=vid, nid=nid, sid=s2["id"]))
    assert protect["V revert"] == (409, "Conflict", PROTECT.format(verb="revert", rid=vid, nid=nid, sid=s2["id"]))

    srv.stop()
    api(db=db)
    u, ufinal, useen, n = put_same("vn9an", ntok, s2["id"])
    d = clients()
    seen_n = assert_from_s2(d, "vn9an", ntok, n, s_tree)
    ops = [(o["action"], o["status"]) for o in ops_for(db, nid)]
    released = delete_snapshot("vn9a", "S2")["status"]  # 처음 Succeeded가 되면 원본 보호가 풀린다
    note("AC-09a same PUT", put_state=u.json()["properties"]["provisioningState"], final=ufinal["status"],
         seen=useen, new_volume=seen_n, ops=ops, source_snapshot_delete_after=released)
    assert u.json()["properties"]["provisioningState"] == "Updating" and ufinal["status"] == "Succeeded"
    assert seen_n["originatingResourceId"] == s2["id"]
    assert ops == [("CREATE", "Failed"), ("UPDATE", "Succeeded")]
    assert released == "Succeeded"
    for cl in (c, d):
        cl.remove()
    delete_volume("vn9an")
    delete_volume("vn9a")


def test_ac09b_agent_down_then_same_put_recovers(agent, api, clients):
    srv = api()
    setup_pool()
    v, tok, c, snaps = source_volume(clients, "vn9b", "nac09b")
    s2 = snaps["S2"]
    s_tree = tree(NS / tok / ".snapshot" / "S2")
    ntok = token("nac09bn")
    agent.stop()
    try:
        t0 = time.monotonic()
        r = put_restore("vn9bn", ntok, s2["id"])
        assert r.status == 201, r.raw
        final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
        elapsed = round(time.monotonic() - t0, 1)
        n_state = state_in("vn9bn")
        retries = srv.output().count("is unreachable")
    finally:
        agent.start()
    note("AC-09b agent down", elapsed_s=elapsed, seen=sorted(set(seen)), final=final, new_volume_state=n_state,
         unreachable_log_lines=retries, protection=error_of(call("DELETE", snap_url("vn9b", "S2")))[:2])
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError"
    assert n_state == "Failed" and 55 <= elapsed <= 90 and retries > 0
    u, ufinal, _, n = put_same("vn9bn", ntok, s2["id"])
    d = clients()
    seen_n = assert_from_s2(d, "vn9bn", ntok, n, s_tree)
    note("AC-09b agent back", final=ufinal["status"], new_volume=seen_n)
    assert ufinal["status"] == "Succeeded"
    for cl in (c, d):
        cl.remove()
    delete_volume("vn9bn")
    delete_volume("vn9b")


def test_ac09c_anf_api_sigkill_during_injected_delay(agent, api, clients):
    delay = 8
    srv = api()
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = source_volume(clients, "vn9c", "nac09c")
    s2 = snaps["S2"]
    s_tree = tree(NS / tok / ".snapshot" / "S2")
    srv.stop()
    srv = api(faults={"volumes/create": {"delaySeconds": delay}}, db=db)
    ntok = token("nac09cn")
    nid = vol_path(ACCT, POOL, "vn9cn")
    r = put_restore("vn9cn", ntok, s2["id"])
    assert r.status == 201
    time.sleep(2)
    during = state_in("vn9cn")
    rc = srv.sigkill()
    ops_at_kill = [(o["action"], o["status"]) for o in ops_for(db, nid)]
    api(db=db)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    n = call("GET", vol_url(ACCT, POOL, "vn9cn")).json()
    d = clients()
    seen_n = assert_from_s2(d, "vn9cn", ntok, n, s_tree)
    note("AC-09c SIGKILL during delay", state_before_kill=during, returncode=rc, ops_at_kill=ops_at_kill, seen=seen,
         final=final, ops_after=[(o["action"], o["status"]) for o in ops_for(db, nid)], new_volume=seen_n)
    assert during == "Creating" and rc == -signal.SIGKILL and ops_at_kill == [("CREATE", "Creating")]
    assert final["status"] == "Succeeded"
    assert [(o["action"], o["status"]) for o in ops_for(db, nid)] == [("CREATE", "Succeeded")]
    for cl in (c, d):
        cl.remove()
    delete_volume("vn9cn")
    delete_volume("vn9c")


def test_ac09_extra_agent_sigkill_during_clone_job(agent, api, clients):
    """(기준 밖, 결정 10의 e2e) 새 볼륨이 호스트에 마운트된 순간(LV를 만든 뒤, 진행 표시를 지우기 전) agent를
    SIGKILL하고 다시 띄운다. 시작 복구는 그 볼륨을 건너뛰고, anf-api가 다시 보낸 같은 POST가 끝낸다."""
    srv = api()
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = source_volume(clients, "vn9e", "nac09e")
    s2 = snaps["S2"]
    s_tree = tree(NS / tok / ".snapshot" / "S2")
    ntok = token("nac09en")
    nid = vol_path(ACCT, POOL, "vn9en")
    nmp = str(NS / ntok)
    r = put_restore("vn9en", ntok, s2["id"])
    assert r.status == 201, r.raw
    nfsid = r.json()["properties"]["fileSystemId"]
    deadline = time.monotonic() + 30
    while nmp not in mount_targets():
        assert time.monotonic() < deadline, "new volume was never mounted"
        time.sleep(0.002)
    agent.kill()
    at_kill = {"cl_tags": cl_tags(nfsid), "base_lvs": vol_snap_lvs(nfsid),
               "mounts": sorted(m for m in mount_targets() if m.startswith(nmp)),
               "instance": sh("docker", "ps", "-a", "--filter", f"name=anf-nfs-{nfsid.replace('-', '')}",
                              "--format", "{{.State}}").stdout.strip()}
    time.sleep(2)
    t_up0 = time.monotonic()
    agent.start()
    up_s = round(time.monotonic() - t_up0, 1)
    final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
    n = call("GET", vol_url(ACCT, POOL, "vn9en")).json()
    d = clients()
    seen_n = assert_from_s2(d, "vn9en", ntok, n, s_tree)
    recover_log = [x for x in agent.text().splitlines() if nfsid in x or "POST" in x][-12:]
    note("AC-09 extra agent SIGKILL during clone job", at_kill=at_kill, agent_start_s=up_s, seen=sorted(set(seen)),
         final=final, new_volume=seen_n, base_lvs=vol_snap_lvs(nfsid), cl_tags_after=cl_tags(nfsid),
         ops=[(o["action"], o["status"]) for o in ops_for(db, nid)], agent_log=recover_log)
    assert at_kill["cl_tags"] != []  # 진행 표시가 남은 채로 멈췄다
    assert final["status"] == "Succeeded"
    assert len(vol_snap_lvs(nfsid)) == 1 and cl_tags(nfsid) == []
    for cl in (c, d):
        cl.remove()
    delete_volume("vn9en")
    delete_volume("vn9e")


# --- AC-10 ---


def test_ac10_agent_clone_api(agent, api, clients):
    api()
    setup_pool()
    v, tok, snaps = small_source("vn10", "nac10", size=2 * GIB)
    w, _, snaps_w = small_source("vn10w", "nac10w", snaps=("T",))
    vfs, sid, tid = fsid_of(v), snaps["S"]["properties"]["snapshotId"], snaps_w["T"]["properties"]["snapshotId"]

    def body(u: str, path: str, size=2 * GIB, clone=None, drop_clone=False):
        b = {"uuid": u, "name": lv_name(u), "size": size,
             "nas": {"path": path, "unix_permissions": 755, "protocols": ["nfs3"]}}
        if not drop_clone:
            b["clone"] = clone
        return b

    def flex(parent: str, snapshot: str) -> dict:
        return {"is_flexclone": True, "parent_volume": {"uuid": parent}, "parent_snapshot": {"uuid": snapshot}}

    def post(b):
        status, reply = agent_call("POST", "/api/storage/volumes", b)
        job = agent_job(reply["job"]["_links"]["self"]["href"], 180) if status == 202 else reply
        return status, job

    ok_uuid, ok_tok = str(uuid.uuid4()), token("nac10ok")
    ok = post(body(ok_uuid, "/" + ok_tok, clone=flex(vfs, sid)))
    rec = agent_call("GET", f"/api/storage/volumes/{ok_uuid}")
    bases = agent_call("GET", f"/api/storage/volumes/{ok_uuid}/snapshots")[1]["records"]
    rd = one_shot(rec[1]["data_lif"]["ip"]["address"], ok_tok, "3", "cat /m/a && ls -A /m/.snapshot && stat -c %a /m")
    note("AC-10 clone POST", status=ok[0], job=ok[1], record=rec, bases=bases, read=out(rd))
    assert ok[0] == 202 and ok[1]["state"] == "success"
    assert rec[0] == 200 and rec[1]["state"] == "online" and rec[1]["size"] == 2 * GIB
    assert [b["name"] for b in bases] == ["S"] and bases[0]["uuid"] != sid
    assert rd.returncode == 0 and rd.stdout.split() == ["one", "S", "755"]

    missing_vol, missing_snap = str(uuid.uuid4()), str(uuid.uuid4())
    failures = {
        "missing parent volume": (body(str(uuid.uuid4()), "/" + token("nac10f1"), clone=flex(missing_vol, sid)),
                                  f"volume {missing_vol} not found"),
        "missing snapshot": (body(str(uuid.uuid4()), "/" + token("nac10f2"), clone=flex(vfs, missing_snap)),
                             f"snapshot {missing_snap} not found"),
        "another volume's snapshot": (body(str(uuid.uuid4()), "/" + token("nac10f3"), clone=flex(vfs, tid)),
                                      f"snapshot {tid} is not a snapshot of volume {vfs}"),
        "size smaller than the snapshot": (body(str(uuid.uuid4()), "/" + token("nac10f4"), size=GIB,
                                                clone=flex(vfs, sid)), "is smaller than snapshot"),
    }
    lvs_before = sorted(lvs_volumes())
    failed = {}
    for label, (b, _) in failures.items():
        failed[label] = post(b) + (agent_call("GET", f"/api/storage/volumes/{b['uuid']}")[0],)
    lvs_after = sorted(lvs_volumes())
    good = flex(vfs, sid)
    bad = {
        "clone missing parent_snapshot": {"is_flexclone": True, "parent_volume": {"uuid": vfs}},
        "clone extra field": {**good, "split_initiated": False},
        "is_flexclone false": {**good, "is_flexclone": False},
        "is_flexclone missing": {"parent_volume": {"uuid": vfs}, "parent_snapshot": {"uuid": sid}},
        "is_flexclone string (extra)": {**good, "is_flexclone": "true"},
        "parent volume uuid not a uuid": flex("nope", sid),
        "parent snapshot uuid not a uuid": flex(vfs, "nope"),
        "parent volume uuid upper case (extra)": flex(vfs.upper(), sid),
        "parent snapshot by name (extra)": {**good, "parent_snapshot": {"name": "S"}},
        "parent snapshot uuid and name (extra)": {**good, "parent_snapshot": {"uuid": sid, "name": "S"}},
        "clone is a list (extra)": [],
        "clone is null (extra)": None,
    }
    bad_results = {}
    for label, clone in bad.items():
        bad_results[label] = agent_call("POST", "/api/storage/volumes",
                                        body(str(uuid.uuid4()), "/" + token("nac10b"), clone=clone))
    note("AC-10 failure jobs and 400s", failed=failed, lvs_unchanged=lvs_after == lvs_before, bad=bad_results)
    for label, (b, needle) in failures.items():
        status, job, get_status = failed[label]
        assert status == 202 and job["state"] == "failure" and needle in job["message"], (label, job)
        assert get_status == 404, label
    assert lvs_after == lvs_before
    for label, (status, reply) in bad_results.items():
        assert status == 400, (label, status, reply)

    # 진행 표시가 있는 볼륨: 마지막 단계(진행 표시 지우기) 전에 멈춘 상태를 태그로 만든다 (통합 테스트의 lvchange 지점)
    ok_lv = lv_name(ok_uuid)
    s_time = snaps["S"]["properties"]["created"]
    tag = sh("lvchange", "--addtag", f"anf_cl_snap={sid}", "--addtag", "anf_cl_name=S", "--addtag",
             f"anf_cl_time={s_time}", f"anf/{ok_lv}")
    assert tag.returncode == 0, out(tag)
    pending = cl_tags(ok_uuid)
    snap_post = agent_call("POST", f"/api/storage/volumes/{ok_uuid}/snapshots", {"uuid": str(uuid.uuid4()), "name": "s9"})
    snap_post_job = agent_job(snap_post[1]["job"]["_links"]["self"]["href"])
    snap_del = agent_call("DELETE", f"/api/storage/volumes/{ok_uuid}/snapshots/{bases[0]['uuid']}")
    snap_del_job = agent_job(snap_del[1]["job"]["_links"]["self"]["href"])
    restore = agent_call("PATCH", f"/api/storage/volumes/{ok_uuid}?restore_to.snapshot.uuid={bases[0]['uuid']}"
                                  f"&restore_to.request_uuid={uuid.uuid4()}")
    restore_job = agent_job(restore[1]["job"]["_links"]["self"]["href"])
    still = agent_call("GET", f"/api/storage/volumes/{ok_uuid}/snapshots")[1]["records"]
    again = post(body(ok_uuid, "/" + ok_tok, clone=flex(vfs, sid)))
    after_tags = cl_tags(ok_uuid)
    snap_post2 = agent_call("POST", f"/api/storage/volumes/{ok_uuid}/snapshots", {"uuid": str(uuid.uuid4()), "name": "s9"})
    snap_post2_job = agent_job(snap_post2[1]["job"]["_links"]["self"]["href"])
    final_snaps = sorted(x["name"] for x in agent_call("GET", f"/api/storage/volumes/{ok_uuid}/snapshots")[1]["records"])
    note("AC-10 volume with progress tags", pending_tags=pending, snapshot_post=snap_post_job,
         snapshot_delete=snap_del_job, restore=restore_job, snapshots_while_pending=[x["name"] for x in still],
         post_again=again, tags_after=after_tags, snapshot_post_after=snap_post2_job, snapshots_after=final_snaps)
    assert len(pending) == 3
    for job in (snap_post_job, snap_del_job, restore_job):
        assert job["state"] == "failure" and "still being created from snapshot" in job["message"], job
    assert [x["name"] for x in still] == ["S"]
    assert again[0] == 202 and again[1]["state"] == "success" and after_tags == []
    assert snap_post2_job["state"] == "success" and final_snaps == ["S", "s9"]

    st, reply = agent_call("DELETE", f"/api/storage/volumes/{ok_uuid}")
    assert agent_job(reply["job"]["_links"]["self"]["href"], 180)["state"] == "success"
    delete_volume("vn10w")
    delete_volume("vn10")
