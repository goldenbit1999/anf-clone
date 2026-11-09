"""스냅샷 e2e (1/3): ARM 계약과 상태 전이, agent API (스냅샷 설계 §8).

- AC-01 생성: 201·Creating·두 헤더 → Succeeded, GET 본문, 목록, 데이터 플레인 객체
- AC-07 거절: 이름, 본문, 없는 볼륨, Deleting·Creating 볼륨, PATCH. 작업·LV가 생기지 않는다
- AC-08 같은 PUT: 200·Updating → Succeeded(UPDATE), snapshotId·created·LV·내용 그대로. 다른 location은 409
- AC-09 진행 중인 스냅샷에 PUT·DELETE, 그 볼륨의 DELETE는 409
- AC-13 storage agent의 ONTAP REST 스냅샷 부분집합

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_snapshot_contract_live.py -v -s'
스냅샷 e2e 세 파일을 한 번에: 파일 대신 `backend/tests/e2e/test_snapshot_*_live.py`.
"""

import re
import uuid

import pytest

import live_api
from live_api import LOC, UUID_RE, call, poll
from dataplane_live import (
    ACCT, agent_call, agent_job, create_volume, dataplane, db_ops, db_rows, delete_volume, error_of, fsid_of, GIB,
    lv_name, mount_ip, note, NS, one_shot, ops_for, out, POLL, POOL, setup_pool, SKIP_UNLESS_ROOT, token, vol_body,
    vol_path, vol_url,
)
from snapshot_live import (
    create_snapshot, exported_paths, exports_file, instance_etab, ISO_UTC, op_seconds, snap_list_url, snap_lv_name,
    snap_lvs, snap_mounts, snap_path, snap_url, SNAPSHOT_TYPE, vol_snap_lvs,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]


# --- AC-01 ---


def test_ac01_create_snapshot_contract_and_state(agent, api):
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("sac01")
    v = create_volume("vs1", tok)
    fsid = fsid_of(v)

    empty = call("GET", snap_list_url("vs1"))
    note("AC-01 empty list", status=empty.status, body=empty.json())
    assert empty.status == 200 and empty.json() == {"value": []}

    cid = str(uuid.uuid4())
    before = snap_lvs()
    r = call("PUT", snap_url("vs1", "s1"), {"location": LOC}, headers={"x-ms-correlation-request-id": cid})
    assert r.status == 201, r.raw
    created = r.json()
    lro_headers = sorted(h for h in r.headers if h in ("azure-asyncoperation", "location", "retry-after"))
    early_location = call("GET", r.headers["location"])
    note("AC-01 PUT", status=r.status, lro_headers=lro_headers, body=created,
         location_poll_right_after_put=early_location.status)
    assert created["properties"] == {"provisioningState": "Creating"}  # snapshotId·created 없음 (녹화 R1)
    assert lro_headers == ["azure-asyncoperation", "location"]

    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    note("AC-01 operation", seen=seen, final=final, seconds=op_seconds(final))
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "CREATE"
    assert final["properties"]["resourceName"].lower() == snap_path("vs1", "s1").lower()

    g = call("GET", snap_url("vs1", "s1"))
    assert g.status == 200, g.raw
    s = g.json()
    p = s["properties"]
    note("AC-01 GET", body=s)
    assert s["id"] == snap_path("vs1", "s1")
    assert s["name"] == f"{ACCT}/{POOL}/vs1/s1" and s["type"] == SNAPSHOT_TYPE and s["location"] == LOC
    assert "tags" not in s
    assert p["provisioningState"] == "Succeeded"
    assert re.fullmatch(UUID_RE, p["snapshotId"]) and uuid.UUID(p["snapshotId"]).version == 4
    assert re.fullmatch(ISO_UTC, p["created"])
    assert sorted(p) == ["created", "provisioningState", "snapshotId"]

    loc = call("GET", r.headers["location"])
    listing = call("GET", snap_list_url("vs1"))
    note("AC-01 Location poll and list", location_status=loc.status, location_body=loc.json(),
         list_body=listing.json())
    assert loc.status == 200 and loc.json() == s
    assert listing.status == 200 and listing.json() == {"value": [s]}

    # 보조 증거: 스냅샷 LV(읽기 전용 thin 스냅샷, 태그), 호스트 마운트, export 줄, 상관 ID (NFR-08)
    lvs = snap_lvs()
    lv = snap_lv_name(p["snapshotId"])
    mounts = snap_mounts(tok)
    xf, etab = exports_file(fsid), instance_etab(fsid)
    ops = [(o["action"], o["status"]) for o in ops_for(db, s["id"])]
    note("AC-01 dataplane", before=sorted(before), lv=lvs.get(lv), mounts=mounts, exports_file=xf, etab=etab,
         operations=ops, correlation_in_agent_log=cid in agent.text())
    assert set(lvs) - set(before) == {lv}
    assert lvs[lv]["attr"].startswith("Vri") and lvs[lv]["origin"] == lv_name(fsid)
    assert lvs[lv]["tags"]["anf_snap_name"] == "s1" and lvs[lv]["tags"]["anf_snap_vol"] == fsid
    assert lvs[lv]["tags"]["anf_snap_time"] == p["created"]
    assert mounts == [str(NS / tok / ".snapshot" / "s1")]
    assert exported_paths(xf) == [f"/{tok}", f"/{tok}/.snapshot/s1"]
    assert f"fsid={p['snapshotId']}" in xf
    assert exported_paths(etab) == exported_paths(xf)  # 인스턴스 etab도 rootdir(/export) 기준 경로다
    assert ops == [("CREATE", "Succeeded")]
    assert cid in agent.text()

    rd = one_shot(mount_ip(v), tok, "3", "ls -A /m/.snapshot")
    note("AC-01 client sees .snapshot/s1", **out(rd))
    assert rd.returncode == 0 and rd.stdout == "s1\n"
    delete_volume("vs1")


# --- AC-07 ---


def test_ac07_rejections_create_no_operation_or_lv(agent, api, clients):
    delay = 8
    srv = api(faults={"volumes/create": {"delaySeconds": delay}, "volumes/delete": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    tok = token("sac07")
    v = create_volume("vs7", tok)
    vid = v["id"]

    cases = [
        ("name .a", ".a", {"location": LOC}),
        ("name -a", "-a", {"location": LOC}),
        ("name a/b (path differs)", "a/b", {"location": LOC}),
        ("name a%2Fb (encoded slash)", "a%2Fb", {"location": LOC}),
        ("name 'a b'", "a%20b", {"location": LOC}),
        ("name 256 chars", "a" * 256, {"location": LOC}),
        ("location missing", "s7", {}),
        ("location not a string", "s7", {"location": 1}),
        ("tags", "s7", {"location": LOC, "tags": {"k": "v"}}),
        ("unknown properties key", "s7", {"location": LOC, "properties": {"fooBar": 1}}),
        ("properties not an object", "s7", {"location": LOC, "properties": []}),
    ]
    ops_before, before = len(db_ops(db)), dataplane()
    results = []
    for label, name, body in cases:
        r = call("PUT", snap_url("vs7", name), body)
        results.append((label, *error_of(r)))
    missing = call("PUT", snap_url("novol", "s7"), {"location": LOC})
    patch = call("PATCH", snap_url("vs7", "s7"), {"properties": {}})
    for row in results:
        note("AC-07 rejected", case=row[0], status=row[1], code=row[2], message=row[3])
    note("AC-07 missing volume", error=error_of(missing))
    note("AC-07 PATCH", status=patch.status, body=patch.raw.decode(errors="replace"))
    by_label = {row[0]: row[1:] for row in results}
    for label in ("name .a", "name -a", "name 'a b'", "name 256 chars"):
        assert by_label[label][:2] == (400, "InvalidResourceName"), (label, by_label[label])
    for label in ("name a/b (path differs)", "name a%2Fb (encoded slash)"):
        assert by_label[label][0] in (400, 404), (label, by_label[label])  # 경로가 달라져 라우트가 없을 수 있다
    for label in ("location missing", "location not a string", "tags", "unknown properties key",
                  "properties not an object"):
        assert by_label[label][:2] == (400, "InvalidRequestContent"), (label, by_label[label])
    assert error_of(missing) == (
        404, "ParentResourceNotFound",
        "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools/volumes/snapshots', "
        f"because the parent resource '{vol_path(ACCT, POOL, 'novol')}' could not be found.")
    assert patch.status == 405
    assert len(db_ops(db)) == ops_before
    assert [x for x in db_rows(db) if x["type"] == SNAPSHOT_TYPE] == []
    assert dataplane() == before

    # Creating인 볼륨 아래 (volumes/create 지연)
    c = call("PUT", vol_url(ACCT, POOL, "vs7c"), vol_body(token("sac07c")))
    assert c.status == 201, c.raw
    snaps_before = snap_lvs()
    r = call("PUT", snap_url("vs7c", "s7"), {"location": LOC})
    note("AC-07 volume Creating", error=error_of(r))
    assert error_of(r) == (400, "BadRequest", "Snapshot cannot be created on a volume that isn't in state succeeded.")
    assert ops_for(db, snap_path("vs7c", "s7")) == []
    assert poll(c.headers["azure-asyncoperation"], delay + POLL)[0]["status"] == "Succeeded"
    assert snap_lvs() == snaps_before

    # Deleting인 볼륨 아래 (volumes/delete 지연). 남은 스냅샷 keep의 DELETE도 409다 (설계 §4.1)
    keep, _ = create_snapshot("vs7c", "keep")
    d = call("DELETE", vol_url(ACCT, POOL, "vs7c"))
    assert d.status == 202, d.raw
    vstate = call("GET", vol_url(ACCT, POOL, "vs7c")).json()["properties"]["provisioningState"]
    r = call("PUT", snap_url("vs7c", "s7"), {"location": LOC})
    rd = call("DELETE", snap_url("vs7c", "keep"))
    note("AC-07 volume Deleting", volume_state=vstate, put=error_of(r), delete_keep=error_of(rd))
    assert vstate == "Deleting"
    vc_id = vol_path(ACCT, POOL, "vs7c")
    assert error_of(r) == (409, "Conflict", f"Cannot create or delete snapshot '{snap_path('vs7c', 's7')}' because "
                                            f"its parent volume '{vc_id}' is being deleted.")
    assert error_of(rd)[:2] == (409, "Conflict")
    assert ops_for(db, snap_path("vs7c", "s7")) == []
    assert [o["action"] for o in ops_for(db, keep["id"])] == ["CREATE"]
    final, _ = poll(d.headers["azure-asyncoperation"], delay + 2 * POLL)
    gone = call("GET", snap_url("vs7c", "keep"))
    note("AC-07 volume deleted", final=final, keep_after=error_of(gone))
    assert final["status"] == "Succeeded"
    assert gone.status == 404

    # 보조 (결정 10의 경계): 정책 스냅샷 이름처럼 `.`이 든 이름과 255자 이름은 받고, 클라이언트가 읽는다
    edge = {"dotted": "daily.2026-11-08_0013", "255 chars": "b" * 255}
    cl = clients()
    cl.mount(mount_ip(v), tok, "3")
    assert cl.run("echo edge > /m/f && sync").returncode == 0
    for label, name in edge.items():
        r = call("PUT", snap_url("vs7", name), {"location": LOC})
        final, seen = (poll(r.headers["azure-asyncoperation"], POLL) if r.status == 201 else ({}, []))
        rd = cl.run(f"cat /m/.snapshot/{name}/f")
        note(f"AC-07 edge name {label}", put=r.status, final=final, read=out(rd))
        assert r.status == 201 and final["status"] == "Succeeded"
        assert rd.returncode == 0 and rd.stdout == "edge\n"
    assert call("GET", snap_url("vs7", "s7")).status == 404
    assert len([x for x in db_rows(db) if x["type"] == SNAPSHOT_TYPE and x["parent_id"] == vid]) == 2
    cl.remove()
    delete_volume("vs7")


# --- AC-08 ---


def test_ac08_put_again_is_async_update_and_keeps_snapshot(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("sac08")
    v = create_volume("vs8", tok)
    fsid = fsid_of(v)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    assert c.run("echo first > /m/f && sync").returncode == 0
    s, _ = create_snapshot("vs8", "s8")
    sid, created_at = s["properties"]["snapshotId"], s["properties"]["created"]
    assert c.run("echo second > /m/f && sync").returncode == 0
    lvs_before = snap_lvs()

    u = call("PUT", snap_url("vs8", "s8"), {"location": LOC})
    lro_headers = sorted(h for h in u.headers if h in ("azure-asyncoperation", "location"))
    assert u.status == 200, u.raw
    body = u.json()
    final, seen = poll(u.headers["azure-asyncoperation"], POLL)
    g = call("GET", snap_url("vs8", "s8")).json()
    lvs_after = snap_lvs()
    rd = c.run("cat /m/.snapshot/s8/f /m/f")
    note("AC-08 PUT again", status=u.status, lro_headers=lro_headers, body=body, seen=seen, final=final, get=g,
         lvs_before=lvs_before, lvs_after=lvs_after, read=out(rd))
    assert body["properties"]["provisioningState"] == "Updating"
    assert lro_headers == ["azure-asyncoperation"]
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "UPDATE"
    assert g["properties"] == {"provisioningState": "Succeeded", "snapshotId": sid, "created": created_at}
    assert vol_snap_lvs(fsid) == [snap_lv_name(sid)] and lvs_after == lvs_before
    assert rd.returncode == 0 and rd.stdout == "first\nsecond\n"

    other = call("PUT", snap_url("vs8", "s8"), {"location": "eastus"})
    note("AC-08 other location", error=error_of(other))
    assert error_of(other)[:2] == (409, "InvalidResourceLocation")
    assert [o["action"] for o in ops_for(db, s["id"])] == ["CREATE", "UPDATE"]
    c.remove()
    delete_volume("vs8")


# --- AC-09 ---


def test_ac09_requests_during_snapshot_create_conflict(agent, api):
    delay = 8
    srv = api(faults={"snapshots/create": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    tok = token("sac09")
    v = create_volume("vs9", tok)
    r = call("PUT", snap_url("vs9", "s9"), {"location": LOC})
    assert r.status == 201, r.raw
    rid = r.json()["id"]
    put = call("PUT", snap_url("vs9", "s9"), {"location": LOC})
    delete = call("DELETE", snap_url("vs9", "s9"))
    vdelete = call("DELETE", vol_url(ACCT, POOL, "vs9"))
    status_now = call("GET", r.headers["azure-asyncoperation"]).json()["status"]
    snap_ops, vol_ops = ops_for(db, rid), ops_for(db, v["id"])
    note("AC-09 conflicts", put=error_of(put), delete=error_of(delete), volume_delete=error_of(vdelete),
         operation_status_after=status_now, snapshot_operations=[(o["action"], o["status"]) for o in snap_ops],
         volume_operations=[(o["action"], o["status"]) for o in vol_ops])
    in_progress = (f"Another operation is in progress on resource '{rid}'. Wait until it is finished, and then retry.")
    for x in (put, delete):
        assert error_of(x) == (409, "AnotherOperationInProgress", in_progress)
    assert error_of(vdelete) == (409, "Conflict", f"Cannot delete volume '{v['id']}' because an operation is in "
                                                  f"progress on its snapshot '{rid}'. Wait until it is finished, "
                                                  "and then retry.")
    for x in (put, delete, vdelete):
        assert "azure-asyncoperation" not in x.headers and "location" not in x.headers
    assert status_now == "Creating"
    assert [o["action"] for o in snap_ops] == ["CREATE"]
    assert [o["action"] for o in vol_ops] == ["CREATE"]
    assert call("GET", vol_url(ACCT, POOL, "vs9")).json()["properties"]["provisioningState"] == "Succeeded"

    final, seen = poll(r.headers["azure-asyncoperation"], delay + POLL)
    rd = one_shot(mount_ip(v), tok, "3", "ls -A /m/.snapshot")
    note("AC-09 original operation", seen=seen, final=final, client=out(rd))
    assert final["status"] == "Succeeded"
    assert rd.returncode == 0 and rd.stdout == "s9\n"
    delete_volume("vs9")


# --- AC-13 ---


def test_ac13_agent_snapshot_api(agent):
    vid = str(uuid.uuid4())
    tok = token("sac13")
    st, reply = agent_call("POST", "/api/storage/volumes", {
        "uuid": vid, "name": lv_name(vid), "size": GIB,
        "nas": {"path": f"/{tok}", "unix_permissions": 770, "protocols": ["nfs3"]}})
    assert st == 202 and agent_job(reply["job"]["_links"]["self"]["href"])["state"] == "success"
    base = f"/api/storage/volumes/{vid}/snapshots"
    sid = str(uuid.uuid4())

    st1, reply1 = agent_call("POST", base, {"name": "a1", "uuid": sid})
    href = reply1["job"]["_links"]["self"]["href"]
    job1 = agent_job(href)
    note("AC-13 POST", status=st1, reply=reply1, job=job1)
    assert st1 == 202 and href == f"/api/cluster/jobs/{reply1['job']['uuid']}"
    assert job1["state"] == "success"

    st2, reply2 = agent_call("POST", base, {"name": "a1", "uuid": sid})
    job2 = agent_job(reply2["job"]["_links"]["self"]["href"])
    mine = [n for n, x in snap_lvs().items() if x["tags"]["anf_snap_vol"] == vid]
    note("AC-13 POST again", status=st2, job=job2, lvs=mine)
    assert st2 == 202 and job2["state"] == "success" and mine == [snap_lv_name(sid)]

    st3, reply3 = agent_call("POST", base, {"name": "a1", "uuid": str(uuid.uuid4())})
    job3 = agent_job(reply3["job"]["_links"]["self"]["href"])
    note("AC-13 POST same name, other uuid", status=st3, job=job3)
    assert st3 == 202 and job3["state"] == "failure" and "already exists" in job3["message"]

    st4, listing = agent_call("GET", f"{base}?name=a1")
    st5, record = agent_call("GET", f"{base}/{sid}")
    st6, missing = agent_call("GET", f"{base}/{uuid.uuid4()}")
    st6b, nolist = agent_call("GET", f"/api/storage/volumes/{uuid.uuid4()}/snapshots")
    note("AC-13 GET", list_status=st4, listing=listing, record_status=st5, record=record, missing_status=st6,
         missing_volume_list_status=st6b, missing_volume_list=nolist)
    assert st4 == 200 and listing["num_records"] == 1 and listing["records"][0]["uuid"] == sid
    assert st5 == 200 and record["name"] == "a1" and record["volume"] == {"uuid": vid}
    assert re.fullmatch(ISO_UTC, record["create_time"])
    assert st6 == 404 and st6b == 404

    st7, reply7 = agent_call("DELETE", f"{base}/{uuid.uuid4()}")
    job7 = agent_job(reply7["job"]["_links"]["self"]["href"])
    note("AC-13 DELETE missing", status=st7, job=job7)
    assert st7 == 202 and job7["state"] == "success"

    bad = {}
    for label, path, body in [
        ("name ../x", base, {"name": "../x", "uuid": str(uuid.uuid4())}),
        ("name a/b", base, {"name": "a/b", "uuid": str(uuid.uuid4())}),
        ("name .a", base, {"name": ".a", "uuid": str(uuid.uuid4())}),
        ("name 256 chars", base, {"name": "a" * 256, "uuid": str(uuid.uuid4())}),
        ("uuid uppercase", base, {"name": "a2", "uuid": str(uuid.uuid4()).upper()}),
        ("uuid not a uuid", base, {"name": "a2", "uuid": "not-a-uuid"}),
        ("unknown field", base, {"name": "a2", "uuid": str(uuid.uuid4()), "comment": "x"}),
        ("volume uuid in path", "/api/storage/volumes/not-a-uuid/snapshots", {"name": "a2", "uuid": str(uuid.uuid4())}),
    ]:
        bad[label] = agent_call("POST", path, body)
    bad["GET bad snapshot uuid"] = agent_call("GET", f"{base}/NOT-A-UUID")
    bad["DELETE bad snapshot uuid"] = agent_call("DELETE", f"{base}/x")
    note("AC-13 bad input", results=bad)
    assert {k: st for k, (st, _) in bad.items()} == {k: 400 for k in bad}

    st8, reply8 = agent_call("POST", f"/api/storage/volumes/{uuid.uuid4()}/snapshots",
                             {"name": "a3", "uuid": str(uuid.uuid4())})
    job8 = agent_job(reply8["job"]["_links"]["self"]["href"])
    note("AC-13 POST to missing volume", status=st8, job=job8)
    assert st8 == 202 and job8["state"] == "failure"
    assert [n for n, x in snap_lvs().items() if x["tags"]["anf_snap_vol"] == vid] == [snap_lv_name(sid)]

    st9, reply9 = agent_call("DELETE", f"{base}/{sid}")
    job9 = agent_job(reply9["job"]["_links"]["self"]["href"])
    after = agent_call("GET", base)[1]
    note("AC-13 DELETE", status=st9, job=job9, list_after=after, mounts=snap_mounts(tok))
    assert job9["state"] == "success" and after["num_records"] == 0
    assert snap_mounts(tok) == []
    st10, reply10 = agent_call("DELETE", f"/api/storage/volumes/{vid}")
    assert agent_job(reply10["job"]["_links"]["self"]["href"], 180)["state"] == "success"
