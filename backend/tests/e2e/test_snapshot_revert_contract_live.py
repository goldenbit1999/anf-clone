"""되돌리기 e2e (2/2): API 계약, 거절, 충돌, 실패와 회복, 재시작 안전, agent API (되돌리기 설계 §8).

- AC-01 POST revert의 응답·헤더·작업 상태·Location 조회 (지연 주입)
- AC-05 거절은 작업을 만들지 않고 데이터·스냅샷을 바꾸지 않는다
- AC-06 Reverting인 동안의 다른 요청, 스냅샷 생성 중의 revert
- AC-07 주입한 실패 / agent 중단 → Failed → 볼륨 PUT → revert
- AC-08 (a) 지연 중 anf-api SIGKILL, agent job 중 anf-api SIGKILL (b) 같은 키 agent PATCH
  (c) 창 안에서 agent를 멈추고 죽인 뒤: 곧 다시 띄움 / 재시도 시간(60 s)을 넘겨 띄우고 볼륨 PUT
- AC-09 agent `PATCH /api/storage/volumes/{uuid}?restore_to...`

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_snapshot_revert_contract_live.py -v -s'
"""

import os
import signal
import time
import uuid

import pytest

import live_api
from live_api import LOC, call, location_url, poll
from dataplane_live import (
    ACCT, agent_call, agent_job, create_volume, db_ops, delete_volume, error_of, fsid_of, instance_name, instances,
    lv_name, mount_ip, note, NS, one_shot, ops_for, out, POLL, POOL, setup_pool, sh, SKIP_UNLESS_ROOT, token,
    vol_body, vol_path, vol_url,
)
from snapshot_live import (
    create_snapshot, delete_snapshot, lv_attrs, NOT_FOUND, op_seconds, snap_lv_name, snap_url, umount_retry,
    vol_snap_lvs,
)
from revert_live import (
    build_history, drop_rule, identity, listing, mount_targets, op_id, post_revert, probe_stats, PROBE, revert,
    revert_url, RuleWatch, rv_tags, snapshot_trees, start_script, tree, volume_lvs,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]

CONFLICT = ("Cannot modify resource with id '{rid}' because the resource entity provisioning state is not terminal. "
            "Please wait for the provisioning state to become terminal and then retry the request.")


def history_volume(clients, name: str, tag: str, protocol="NFSv3", vers="3"):
    """볼륨을 만들고 클라이언트로 S1 → S2 → S3 기록을 만든다 (AC-02의 기록). 반환: (볼륨, 토큰, 클라이언트, 스냅샷)."""
    tok = token(tag)
    v = create_volume(name, tok, protocols=[protocol])
    c = clients()
    c.mount(mount_ip(v), tok, vers)
    return v, tok, c, build_history(c, name)


def state_of(name: str) -> str:
    return call("GET", vol_url(ACCT, POOL, name)).json()["properties"]["provisioningState"]


def put_again(name: str, tok: str, protocol="NFSv3", timeout=POLL) -> tuple:
    u = call("PUT", vol_url(ACCT, POOL, name), vol_body(tok, protocols=[protocol]))
    assert u.status == 200, u.raw
    final, seen = poll(u.headers["azure-asyncoperation"], timeout)
    return u, final, seen


def assert_reverted_to_s2(name: str, tok: str, before: dict, before_list: dict) -> None:
    """AC-02와 같은 결과: 볼륨 트리 = 되돌리기 전 S2 트리, S1·S2는 그대로, S3는 없다."""
    assert tree(NS / tok) == before["S2"]
    assert snapshot_trees(tok, ("S1", "S2")) == {"S1": before["S1"], "S2": before["S2"]}
    after = listing(name)
    assert sorted(after) == ["S1", "S2"]
    assert all(identity(after[n]) == identity(before_list[n]) for n in ("S1", "S2"))
    assert error_of(call("GET", snap_url(name, "S3")))[:2] == (404, "ResourceNotFound")
    assert sorted(p.name for p in (NS / tok / ".snapshot").iterdir()) == ["S1", "S2"]


# --- AC-01 ---


def test_ac01_revert_contract_and_states(agent, api, clients):
    delay = 5
    api(faults={"volumes/post": {"delaySeconds": delay}})
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr1", "rac01")
    vid = v["id"]
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing("vr1")
    r = post_revert("vr1", snaps["S2"]["id"])
    during_vol = call("GET", vol_url(ACCT, POOL, "vr1")).json()
    during_op = call("GET", r.headers["azure-asyncoperation"]).json()
    final, seen = poll(r.headers["azure-asyncoperation"], POLL + delay)
    loc = call("GET", r.headers["location"])
    g = call("GET", vol_url(ACCT, POOL, "vr1")).json()
    note("AC-01", status=r.status, headers=r.headers, body=r.raw.decode(), during_volume_state=during_vol["properties"][
        "provisioningState"], during_op=during_op, seen=seen, final=final, op_seconds=op_seconds(final),
        location_status=loc.status, location_body=loc.json(), volume_after=g["properties"]["provisioningState"])
    assert r.status == 202 and r.raw == b"" and r.headers.get("content-length") == "0"
    assert "retry-after" not in r.headers
    assert "/operationResults/" in r.headers["azure-asyncoperation"]
    assert r.headers["location"] == location_url(r.headers["azure-asyncoperation"])
    assert during_vol["properties"]["provisioningState"] == "Reverting"
    assert during_op["status"] == "Reverting" and during_op["properties"] == {"resourceName": vid, "action": "POST"}
    assert seen[0] == "Reverting" and seen[-1] == "Succeeded" and set(seen) == {"Reverting", "Succeeded"}
    assert final["properties"] == {"resourceName": vid, "action": "POST"} and final["percentComplete"] == 100.0
    assert op_seconds(final) >= delay
    assert loc.status == 200 and loc.json()["id"] == vid and loc.json()["properties"]["provisioningState"] == "Succeeded"
    assert g["properties"]["provisioningState"] == "Succeeded"
    assert_reverted_to_s2("vr1", tok, before, before_list)
    c.remove()
    delete_volume("vr1")


# --- AC-05 ---


def test_ac05_rejections_create_no_operation(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr5", "rac05")
    vid, s1 = v["id"], snaps["S1"]["id"]
    create_volume("vr5o", token("rac05o"))
    t1, _ = create_snapshot("vr5o", "T1")
    state0 = (tree(NS / tok), {n: identity(s) for n, s in listing("vr5").items()}, len(db_ops(db)))
    missing_snap = f"{vid}/snapshots/nope"
    cases = [
        ("body is an array", [], 400, "InvalidRequestContent", "The request content must be a JSON object."),
        ("unknown key", {"snapshotId": s1, "extra": 1}, 400, "InvalidRequestContent", None),
        ("snapshotId missing", {}, 400, "InvalidRequestContent",
         "The 'snapshotId' property is required and must be a snapshot resource ID."),
        ("snapshotId is a number", {"snapshotId": 5}, 400, "InvalidRequestContent",
         "The 'snapshotId' property is required and must be a snapshot resource ID."),
        ("snapshotId is a volume id", {"snapshotId": vid}, 400, "InvalidRequestContent", None),
        ("snapshotId is a bare name", {"snapshotId": "S1"}, 400, "InvalidRequestContent", None),
        ("other volume's snapshot", {"snapshotId": t1["id"]}, 400, "BadRequest",
         f"The snapshot '{t1['id']}' does not belong to the volume '{vid}'."),
        ("missing snapshot", {"snapshotId": missing_snap}, 404, "ResourceNotFound",
         NOT_FOUND.format(snap="nope", a=ACCT, p=POOL, v="vr5")),
    ]
    results = {}
    for label, body, status, code, message in cases:
        r = call("POST", revert_url("vr5"), body)
        results[label] = error_of(r)
    nv = vol_path(ACCT, POOL, "nope")
    results["missing volume"] = error_of(call("POST", revert_url("nope"), {"snapshotId": f"{nv}/snapshots/S1"}))
    state1 = (tree(NS / tok), {n: identity(s) for n, s in listing("vr5").items()}, len(db_ops(db)))
    note("AC-05 body and lookup rejections", results=results, ops_before=state0[2], ops_after=state1[2],
         tree_same=state0[0] == state1[0], snapshots_same=state0[1] == state1[1])
    for label, body, status, code, message in cases:
        assert results[label][:2] == (status, code), (label, results[label])
        if message is not None:
            assert results[label][2] == message, (label, results[label])
    assert "snapshot resource ID: /subscriptions/{id}/resourceGroups" in results["snapshotId is a volume id"][2]
    assert "extra" in results["unknown key"][2]
    assert results["missing volume"][:2] == (404, "ResourceNotFound")
    assert state1 == state0

    # Failed 스냅샷과 Failed 볼륨 (같은 DB, 결함을 주입한 서버)
    srv.stop()
    srv = api(faults={"snapshots/create": {"fail": True}, "volumes/patch": {"fail": True}}, db=db)
    p = call("PUT", snap_url("vr5", "SF"), {"location": LOC})
    sf_final, _ = poll(p.headers["azure-asyncoperation"], POLL)
    sf = call("GET", snap_url("vr5", "SF")).json()
    n_ops = len(db_ops(db))
    to_failed_snap = error_of(post_revert("vr5", sf["id"]))
    ops_after_snap = len(db_ops(db))
    patch = call("PATCH", vol_url(ACCT, POOL, "vr5"), {"tags": {"k": "v"}})
    patch_final, _ = poll(patch.headers["azure-asyncoperation"], POLL)
    vol_state = state_of("vr5")
    n_ops2 = len(db_ops(db))
    failed_vol = error_of(post_revert("vr5", s1))
    state2 = (tree(NS / tok), {n: identity(s) for n, s in listing("vr5").items() if n != "SF"}, len(db_ops(db)))
    note("AC-05 failed snapshot and failed volume", sf_final=sf_final, sf=sf, to_failed_snap=to_failed_snap,
         ops=(n_ops, ops_after_snap), patch_status=patch.status, patch_final=patch_final, vol_state=vol_state,
         failed_vol=failed_vol, ops2=(n_ops2, state2[2]), tree_same=state2[0] == state0[0],
         snapshots_same=state2[1] == state0[1])
    assert sf_final["status"] == "Failed" and sf["properties"]["provisioningState"] == "Failed"
    assert to_failed_snap == (400, "BadRequest", f"Volume cannot be reverted to snapshot '{sf['id']}' because the "
                                                 "snapshot isn't in state succeeded.")
    assert ops_after_snap == n_ops
    assert patch_final["status"] == "Failed" and vol_state == "Failed"
    assert failed_vol == (400, "BadRequest", "Volume cannot be reverted when it isn't in state succeeded.")
    assert state2[2] == n_ops2
    assert state2[0] == state0[0] and state2[1] == state0[1]
    srv.stop()
    api(db=db)
    c.remove()
    delete_volume("vr5")
    delete_volume("vr5o")


# --- AC-06 ---


def test_ac06_conflicts_while_reverting(agent, api, clients):
    delay = 15
    srv = api(faults={"volumes/post": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr6", "rac06")
    vid = v["id"]
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing("vr6")
    t0 = time.monotonic()
    r = post_revert("vr6", snaps["S2"]["id"])
    assert r.status == 202, r.raw
    n_ops = len(db_ops(db))
    attempts = {
        "revert again": call("POST", revert_url("vr6"), {"snapshotId": snaps["S1"]["id"]}),
        "volume PUT": call("PUT", vol_url(ACCT, POOL, "vr6"), vol_body(tok, protocols=["NFSv3"])),
        "volume PATCH": call("PATCH", vol_url(ACCT, POOL, "vr6"), {"tags": {"k": "v"}}),
        "volume DELETE": call("DELETE", vol_url(ACCT, POOL, "vr6")),
        "new snapshot PUT": call("PUT", snap_url("vr6", "S9"), {"location": LOC}),
        "existing snapshot re-PUT": call("PUT", snap_url("vr6", "S1"), {"location": LOC}),
        "existing snapshot DELETE": call("DELETE", snap_url("vr6", "S3")),
    }
    elapsed = round(time.monotonic() - t0, 2)
    still = state_of("vr6")
    results = {k: error_of(x) for k, x in attempts.items()}
    n_ops_after = len(db_ops(db))
    final, seen = poll(r.headers["azure-asyncoperation"], POLL + delay)
    note("AC-06 during Reverting", attempts_elapsed_s=elapsed, volume_state=still, results=results,
         ops=(n_ops, n_ops_after), final=final, seen=sorted(set(seen)))
    conflict = (409, "RequestConflict", CONFLICT.format(rid=vid))
    for k in ("revert again", "volume PUT", "volume PATCH", "volume DELETE"):
        assert results[k] == conflict, (k, results[k])
    assert results["new snapshot PUT"] == (400, "BadRequest",
                                           "Snapshot cannot be created on a volume that isn't in state succeeded.")
    for k, s in (("existing snapshot re-PUT", "S1"), ("existing snapshot DELETE", "S3")):
        sid = snaps[s]["id"]
        assert results[k] == (409, "Conflict", f"Cannot change snapshot '{sid}' because its parent volume '{vid}' "
                                               "is being reverted."), (k, results[k])
    assert elapsed < delay and still == "Reverting"
    assert n_ops_after == n_ops
    assert final["status"] == "Succeeded"
    assert_reverted_to_s2("vr6", tok, before, before_list)
    assert error_of(call("GET", snap_url("vr6", "S9")))[:2] == (404, "ResourceNotFound")

    # 스냅샷 생성 중의 revert → 409 Conflict
    srv.stop()
    api(faults={"snapshots/create": {"delaySeconds": delay}}, db=db)
    p = call("PUT", snap_url("vr6", "S4"), {"location": LOC})
    assert p.status == 201, p.raw
    s4_id = p.json()["id"]
    n_ops = len(db_ops(db))
    during = error_of(post_revert("vr6", snaps["S1"]["id"]))
    n_ops_after = len(db_ops(db))
    s4_final, _ = poll(p.headers["azure-asyncoperation"], POLL + delay)
    note("AC-06 revert while a snapshot is being created", result=during, ops=(n_ops, n_ops_after), s4=s4_final["status"],
         volume_state=state_of("vr6"))
    assert during == (409, "Conflict", f"Cannot revert volume '{vid}' because an operation is in progress on its "
                                       f"snapshot '{s4_id}'. Wait until it is finished, and then retry.")
    assert n_ops_after == n_ops and s4_final["status"] == "Succeeded" and state_of("vr6") == "Succeeded"
    c.remove()
    delete_volume("vr6")


# --- AC-07 ---


def test_ac07_injected_failure_then_put_recovers(agent, api, clients):
    srv = api(faults={"volumes/post": {"fail": True}})
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr7", "rac07")
    fsid = fsid_of(v)
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing("vr7")
    before_vol, lvs0 = tree(NS / tok), vol_snap_lvs(fsid)
    r, final, seen = revert("vr7", snaps["S2"]["id"])
    vstate = state_of("vr7")
    read = c.run("cat /m/N /m/M")
    note("AC-07 injected failure", seen=seen, final=final, volume_state=vstate, read=out(read),
         tree_same=tree(NS / tok) == before_vol, list_same={n: identity(s) for n, s in listing("vr7").items()} == {
             n: identity(s) for n, s in before_list.items()}, lvs_same=vol_snap_lvs(fsid) == lvs0, rv_tags=rv_tags(fsid))
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError" and final["error"]["message"]
    assert vstate == "Failed"
    assert tree(NS / tok) == before_vol and vol_snap_lvs(fsid) == lvs0
    assert {n: identity(s) for n, s in listing("vr7").items()} == {n: identity(s) for n, s in before_list.items()}
    assert read.returncode == 0 and read.stdout == "n4\nm4\n"
    assert rv_tags(fsid) == []

    srv.stop()
    api(db=db)
    u, ufinal, useen = put_again("vr7", tok)
    r2, final2, seen2 = revert("vr7", snaps["S2"]["id"])
    note("AC-07 recovery", put_state=u.json()["properties"]["provisioningState"], put_final=ufinal["status"],
         revert=final2["status"], operations=[(o["action"], o["status"]) for o in ops_for(db, v["id"])])
    assert u.json()["properties"]["provisioningState"] == "Updating" and ufinal["status"] == "Succeeded"
    assert final2["status"] == "Succeeded"
    assert_reverted_to_s2("vr7", tok, before, before_list)
    c.remove()
    delete_volume("vr7")


def test_ac07_agent_down_fails_after_retry_then_put_recovers(agent, api, clients):
    srv = api()
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr7b", "rac07b")
    fsid = fsid_of(v)
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing("vr7b")
    before_vol, lvs0 = tree(NS / tok), vol_snap_lvs(fsid)
    agent.stop()
    try:
        t0 = time.monotonic()
        r = post_revert("vr7b", snaps["S2"]["id"])
        assert r.status == 202, r.raw
        final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
        elapsed = round(time.monotonic() - t0, 1)
        vstate = state_of("vr7b")
        retries = srv.output().count("is unreachable")
    finally:
        agent.start()
    note("AC-07 agent down", elapsed_s=elapsed, seen=sorted(set(seen)), final=final, volume_state=vstate,
         unreachable_log_lines=retries, tree_same=tree(NS / tok) == before_vol, lvs_same=vol_snap_lvs(fsid) == lvs0)
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError"
    assert vstate == "Failed" and 55 <= elapsed <= 90 and retries > 0
    assert tree(NS / tok) == before_vol and vol_snap_lvs(fsid) == lvs0
    u, ufinal, _ = put_again("vr7b", tok)
    r2, final2, _ = revert("vr7b", snaps["S2"]["id"])
    note("AC-07 agent back", put=ufinal["status"], revert=final2["status"])
    assert ufinal["status"] == "Succeeded" and final2["status"] == "Succeeded"
    assert_reverted_to_s2("vr7b", tok, before, before_list)
    c.remove()
    delete_volume("vr7b")


# --- AC-08 ---


def test_ac08a_anf_api_sigkill_during_injected_delay(agent, api, clients):
    delay = 8
    srv = api(faults={"volumes/post": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr8a", "rac08a")
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing("vr8a")
    before_vol = tree(NS / tok)
    r = post_revert("vr8a", snaps["S2"]["id"])
    assert r.status == 202
    time.sleep(2)
    during = state_of("vr8a")
    rc = srv.sigkill()
    untouched = tree(NS / tok) == before_vol
    ops_at_kill = [(o["action"], o["status"]) for o in ops_for(db, v["id"])]
    api(db=db)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    note("AC-08a SIGKILL during delay", state_before_kill=during, returncode=rc, data_untouched_at_kill=untouched,
         ops_at_kill=ops_at_kill, seen=seen, final=final,
         ops_after=[(o["action"], o["status"]) for o in ops_for(db, v["id"])])
    assert during == "Reverting" and rc == -signal.SIGKILL and untouched
    assert ops_at_kill[-1] == ("POST", "Reverting")
    assert final["status"] == "Succeeded" and final["name"] == op_id(r.headers["azure-asyncoperation"])
    assert [o for o in ops_for(db, v["id"]) if o["action"] == "POST"][0]["status"] == "Succeeded"
    assert_reverted_to_s2("vr8a", tok, before, before_list)
    c.remove()
    delete_volume("vr8a")


def test_ac08ab_anf_api_sigkill_during_agent_job_then_same_key_is_a_noop(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vr8b", "rac08b")
    fsid = fsid_of(v)
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing("vr8b")
    s3_mp = str(NS / tok / ".snapshot" / "S3")
    r = post_revert("vr8b", snaps["S2"]["id"])
    key = op_id(r.headers["azure-asyncoperation"])
    deadline = time.monotonic() + 30
    while s3_mp in mount_targets():  # agent가 되돌리기를 시작했다 (더 새 S3를 내린다)
        assert time.monotonic() < deadline
        time.sleep(0.005)
    rc = srv.sigkill()
    at_kill = {"volume_lvs": volume_lvs(fsid), "rv_tags": rv_tags(fsid), "drop_rule": drop_rule(fsid)}
    api(db=db)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    note("AC-08a SIGKILL during agent job", returncode=rc, at_kill=at_kill, seen=seen, final=final,
         ops=[(o["action"], o["status"]) for o in ops_for(db, v["id"])], rv_tags=rv_tags(fsid))
    assert rc == -signal.SIGKILL
    assert final["status"] == "Succeeded"
    assert_reverted_to_s2("vr8b", tok, before, before_list)
    assert rv_tags(fsid) == [f"anf_rv_done={key}"]

    # (b) 같은 키로 agent PATCH를 다시 보낸다: 성공 job이고 첫 되돌리기 뒤에 쓴 파일이 남는다
    w = c.run("echo after > /m/after && sync")
    assert w.returncode == 0, out(w)
    lvs0, snaps0, tree0 = volume_lvs(fsid), vol_snap_lvs(fsid), tree(NS / tok)
    s2_uuid = snaps["S2"]["properties"]["snapshotId"]
    path = f"/api/storage/volumes/{fsid}?restore_to.snapshot.uuid={s2_uuid}&restore_to.request_uuid={key}"
    results = []
    for when in ("same agent", "after agent restart"):
        if when == "after agent restart":
            agent.stop()
            agent.start()
        status, reply = agent_call("PATCH", path)
        job = agent_job(reply["job"]["_links"]["self"]["href"])
        rd = c.run("cat /m/after")
        results.append({"when": when, "status": status, "job": job, "read": out(rd),
                        "tree_same": tree(NS / tok) == tree0, "lvs_same": volume_lvs(fsid) == lvs0,
                        "snaps_same": vol_snap_lvs(fsid) == snaps0, "drop_rule": drop_rule(fsid)})
    note("AC-08b same key again", results=results)
    for x in results:
        assert x["status"] == 202 and x["job"]["state"] == "success"
        assert x["read"]["rc"] == 0 and x["read"]["stdout"] == "after\n"
        assert x["tree_same"] and x["lvs_same"] and x["snaps_same"] and x["drop_rule"] is False
    c.remove()
    delete_volume("vr8b")


@pytest.mark.parametrize("variant,protocol,vers", [("restart", "NFSv4.1", "4.1"), ("past-retry", "NFSv3", "3")])
def test_ac08c_agent_killed_inside_the_window(agent, api, clients, variant, protocol, vers):
    """창이 열린 채(차단 규칙, S2 언마운트, 새 LV 있음) agent를 멈추고 죽인다.
    restart: 곧 다시 띄운다 → 시작 복구가 끝내고 anf-api 작업이 Succeeded.
    past-retry: 60초 재시도를 넘겨 띄운다 → 작업 Failed → 시작 복구가 끝냄 → 볼륨 PUT이 S3 행을 지운다 (§9-5)."""
    srv = api()
    db = srv.db_path
    setup_pool()
    name = "vr8c" + variant[0]
    v, tok, c, snaps = history_volume(clients, name, f"rac08c{variant[0]}", protocol, vers)
    fsid = fsid_of(v)
    before, before_list = snapshot_trees(tok, ("S1", "S2")), listing(name)
    s2_rec = [x for x in agent_call("GET", f"/api/storage/volumes/{fsid}/snapshots")[1]["records"]
              if x["name"] == "S2"]
    start_script(c, "/tmp/probe.sh", PROBE, "/m/d1/sub/Y")
    watch = RuleWatch(fsid)
    watch.start()
    time.sleep(1)
    s2_mp = str(NS / tok / ".snapshot" / "S2")
    r = post_revert(name, snaps["S2"]["id"])
    key = op_id(r.headers["azure-asyncoperation"])
    deadline = time.monotonic() + 30
    while s2_mp in mount_targets():
        assert time.monotonic() < deadline
        time.sleep(0.002)
    os.kill(agent.proc.pid, signal.SIGSTOP)
    t_stop = time.time()
    time.sleep(0.5)  # 돌던 명령 하나는 끝까지 간다
    prefix = str(NS / tok)
    at_stop = {"volume_lvs": sorted(volume_lvs(fsid)), "rv_tags": rv_tags(fsid), "drop_rule": drop_rule(fsid),
               "mounts": sorted(m for m in mount_targets() if m.startswith(prefix))}
    agent.kill()
    if variant == "restart":
        time.sleep(3)
        agent.start()
        t_up = time.time()
        final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
        put = None
    else:
        final, seen = poll(r.headers["azure-asyncoperation"], 2 * POLL)
        t_failed = time.time()
        failed_state = {"volume": state_of(name), "list": sorted(listing(name)), "drop_rule": drop_rule(fsid),
                        "probe_tail": c.run("tail -2 /tmp/probe.log").stdout}
        agent.start()
        t_up = time.time()
        after_recover = {"list": sorted(listing(name)), "volume": state_of(name)}
        u, ufinal, _ = put_again(name, tok, protocol)
        put = {"failed_after_kill_s": round(t_failed - t_stop, 1), "at_failure": failed_state,
               "after_agent_recover": after_recover, "put_final": ufinal["status"]}
    t_read = time.time()
    read = c.run("cat /m/A /m/K /m/d1/sub/Y && ls -A /m/.snapshot")
    read_s = round(time.time() - t_read, 2)
    # 막혀 있던 탐침이 이어 가는지: 되돌린 내용(y1)을 읽을 때까지 기다린다 (기준 밖의 관찰, 최대 240초)
    deadline = time.monotonic() + 240
    while "ok y1" not in c.run("cat /tmp/probe.log").stdout and time.monotonic() < deadline:
        time.sleep(1)
    c.run("touch /tmp/stop")
    time.sleep(1)
    windows = watch.stop()
    log = c.run("cat /tmp/probe.log").stdout
    probe = probe_stats(log)
    first_y1 = next((float(x.split()[1]) for x in log.splitlines() if x.endswith(" ok y1")), None)
    stalled = [x for x in log.splitlines() if float(x.split()[1]) - float(x.split()[0]) > 1]
    kernel = sh("dmesg", "--time-format", "iso").stdout.splitlines()[-400:]
    s2_after = [x for x in agent_call("GET", f"/api/storage/volumes/{fsid}/snapshots")[1]["records"]
                if x["name"] == "S2"]
    note(f"AC-08c agent killed in window ({variant}, {protocol})", at_stop=at_stop,
         agent_down_s=round(t_up - t_stop, 1), seen=sorted(set(seen)), final=final, put=put, probe=probe,
         window_s=[round(b - a, 2) for a, b in windows],
         probe_resumed_after_window_close_s=round(first_y1 - windows[-1][1], 2) if first_y1 and windows else None,
         stalled_probe_reads=stalled, read=out(read), read_s=read_s, read_after_window_close_s=round(
             t_read - windows[-1][1], 2) if windows else None,
         kernel_nfs=[x for x in kernel if "nfs: server" in x][-6:], s2_record_before=s2_rec, s2_record_after=s2_after,
         volume_lvs=volume_lvs(fsid), rv_tags=rv_tags(fsid), drop_rule=drop_rule(fsid),
         mount=c.run("grep ' /m ' /proc/mounts").stdout.strip(),
         ops=[(o["action"], o["status"]) for o in ops_for(db, v["id"])])
    lv = f"vol_{fsid.replace('-', '')}"
    assert at_stop["drop_rule"] is True and at_stop["volume_lvs"] == [lv, lv + "_new"]
    assert prefix + "/.snapshot/S2" not in at_stop["mounts"]
    if variant == "restart":
        assert final["status"] == "Succeeded"
    else:
        assert final["status"] == "Failed" and put["at_failure"]["volume"] == "Failed"
        assert put["at_failure"]["list"] == ["S1", "S2", "S3"]  # agent는 S3를 지웠지만 행은 남았다
        assert put["put_final"] == "Succeeded"
    assert_reverted_to_s2(name, tok, before, before_list)
    assert read.returncode == 0 and read.stdout.split() == ["a2", "k1", "k2", "y1", "S1", "S2"]
    assert s2_rec and s2_after == s2_rec
    assert list(volume_lvs(fsid)) == [lv] and rv_tags(fsid) == [f"anf_rv_done={key}"]
    assert drop_rule(fsid) is False
    assert probe["failures"] == [] and set(probe["contents"]) == {"y1", "y4"}
    c.remove()
    delete_volume(name)


# --- 기준 밖 (LV 교체의 남은 위험): 원본 스냅샷 삭제와 WSL 재시작 흉내 ---


def test_extra_reverted_volume_survives_origin_delete_and_simulated_wsl_restart(agent, api, clients):
    api()
    setup_pool()
    v, tok, c, snaps = history_volume(clients, "vrx", "racx")
    fsid, ip = fsid_of(v), mount_ip(v)
    before = snapshot_trees(tok, ("S1", "S2"))
    _, final, _ = revert("vrx", snaps["S2"]["id"])
    assert final["status"] == "Succeeded"
    vol_lv = lv_name(fsid)
    origin = sh("lvs", "--noheadings", "-o", "origin", f"anf/{vol_lv}").stdout.strip()
    assert c.run("echo s4 > /m/s4file && sync").returncode == 0
    create_snapshot("vrx", "S4")
    s4_tree, vol_tree = tree(NS / tok / ".snapshot" / "S4"), tree(NS / tok)
    delete_snapshot("vrx", "S2")  # 볼륨 LV의 원본
    after_delete = {"tree_same": tree(NS / tok) == vol_tree, "read": out(c.run("cat /m/A && ls -A /m/.snapshot")),
                    "origin": sh("lvs", "--noheadings", "-o", "origin", f"anf/{vol_lv}").stdout.strip()}
    c.remove()
    lvs = [vol_lv] + vol_snap_lvs(fsid)
    agent.stop()
    try:
        stop = sh("docker", "stop", instance_name(fsid))
        tries = {n: umount_retry(NS / tok / ".snapshot" / n) for n in ("S1", "S4")}
        tries["volume"] = umount_retry(NS / tok)
        deact = sh("lvchange", "-an", *[f"anf/{lv}" for lv in lvs])
        down = {"stop": stop.returncode, "umount_tries": tries, "lvchange": out(deact), "attrs": lv_attrs(*lvs),
                "instance": instances().get(instance_name(fsid))}
    finally:
        agent.start(timeout=200)
    rd = one_shot(ip, tok, "3", "cat /m/A /m/K /m/s4file /m/.snapshot/S4/s4file /m/.snapshot/S1/A && ls -A /m/.snapshot")
    note("extra: origin delete + simulated WSL restart after revert", origin_after_revert=origin,
         after_delete=after_delete, down=down, attrs_up=lv_attrs(*lvs), read=out(rd),
         tree_same=tree(NS / tok) == vol_tree, s1_same=tree(NS / tok / ".snapshot" / "S1") == before["S1"],
         s4_same=tree(NS / tok / ".snapshot" / "S4") == s4_tree)
    assert origin == snap_lv_name(snaps["S2"]["properties"]["snapshotId"])
    assert after_delete["tree_same"] and after_delete["read"]["stdout"].split() == ["a2", "S1", "S4"]
    assert 0 not in tries.values() and deact.returncode == 0
    assert rd.returncode == 0, out(rd)
    assert rd.stdout.split() == ["a2", "k1", "k2", "s4", "s4", "a1", "S1", "S4"]
    assert tree(NS / tok) == vol_tree
    assert tree(NS / tok / ".snapshot" / "S1") == before["S1"]
    assert tree(NS / tok / ".snapshot" / "S4") == s4_tree
    delete_volume("vrx")


# --- AC-09 ---


def test_ac09_agent_restore_api(agent, api, clients):
    api()
    setup_pool()
    tok = token("rac09")
    v = create_volume("vr9", tok)
    fsid, ip = fsid_of(v), mount_ip(v)
    assert one_shot(ip, tok, "3", "echo one > /m/f && sync").returncode == 0
    s1, _ = create_snapshot("vr9", "S1")
    assert one_shot(ip, tok, "3", "echo two > /m/f && sync").returncode == 0
    s1_uuid = s1["properties"]["snapshotId"]
    base = f"/api/storage/volumes/{fsid}"

    def q(snap, key):
        return f"?restore_to.snapshot.uuid={snap}&restore_to.request_uuid={key}"

    def job_of(status, reply):
        return agent_job(reply["job"]["_links"]["self"]["href"]) if status == 202 else None

    ok_status, ok_reply = agent_call("PATCH", base + q(s1_uuid, uuid.uuid4()))
    ok_job = job_of(ok_status, ok_reply)
    ok_read = one_shot(ip, tok, "3", "cat /m/f")
    assert one_shot(ip, tok, "3", "echo three > /m/f && sync").returncode == 0
    empty_status, empty_reply = agent_call("PATCH", base + q(s1_uuid, uuid.uuid4()), body={})
    empty_job = job_of(empty_status, empty_reply)
    no_vol = str(uuid.uuid4())
    nv_status, nv_reply = agent_call("PATCH", f"/api/storage/volumes/{no_vol}" + q(s1_uuid, uuid.uuid4()))
    nv_job = job_of(nv_status, nv_reply)
    no_snap = str(uuid.uuid4())
    ns_status, ns_reply = agent_call("PATCH", base + q(no_snap, uuid.uuid4()))
    ns_job = job_of(ns_status, ns_reply)
    tree0 = tree(NS / tok)
    k = uuid.uuid4()
    bad = {
        "volume uuid not a uuid": agent_call("PATCH", "/api/storage/volumes/not-a-uuid" + q(s1_uuid, k)),
        "snapshot uuid not a uuid": agent_call("PATCH", base + q("not-a-uuid", k)),
        "snapshot uuid upper case (extra)": agent_call("PATCH", base + q(s1_uuid.upper(), k)),
        "request_uuid not a uuid": agent_call("PATCH", base + q(s1_uuid, "nope")),
        "request_uuid missing": agent_call("PATCH", base + f"?restore_to.snapshot.uuid={s1_uuid}"),
        "unknown query": agent_call("PATCH", base + q(s1_uuid, k) + "&foo=1"),
        "snapshot by name (extra)": agent_call("PATCH", base + f"?restore_to.snapshot.name=S1&restore_to.request_uuid={k}"),
        "body field size": agent_call("PATCH", base + q(s1_uuid, k), body={"size": 1}),
        "no query (extra)": agent_call("PATCH", base, body={}),
    }
    note("AC-09 agent PATCH", ok=(ok_status, ok_job, out(ok_read)), empty_body=(empty_status, empty_job),
         no_volume=(nv_status, nv_job), no_snapshot=(ns_status, ns_job, no_snap), bad=bad,
         tree_same_after_bad=tree(NS / tok) == tree0)
    assert ok_status == 202 and ok_job["state"] == "success" and ok_read.stdout == "one\n"
    assert empty_status == 202 and empty_job["state"] == "success"
    assert nv_status == 202 and nv_job["state"] == "failure" and no_vol in nv_job["message"]
    assert ns_status == 202 and ns_job["state"] == "failure" and no_snap in ns_job["message"]
    for label, (status, _) in bad.items():
        assert status == 400, (label, status)
    assert tree(NS / tok) == tree0
    delete_volume("vr9")
