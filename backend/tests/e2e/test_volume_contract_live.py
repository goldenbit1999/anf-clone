"""볼륨 e2e (1/3): ARM 계약과 상태 전이, agent API (볼륨 설계 §8).

- AC-01 NFSv3 볼륨 생성: 201·Creating·헤더 → Succeeded, GET 본문, 풀 목록, 데이터 플레인 객체
- AC-05 용량·부모 규칙과 풀 쪽 CV-1~CV-3
- AC-06 잘못된 본문 거절과 최소 크기 50 GiB
- AC-07 경로 중복, 바꿀 수 없는 속성, 같은 값 PUT
- AC-08 tags PATCH 중에도 클라이언트 I/O가 이어진다
- AC-10 생성 중 PUT·PATCH·DELETE는 409
- AC-13 storage agent의 ONTAP REST 부분집합

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_volume_contract_live.py -v -s'
볼륨 e2e 세 파일을 한 번에: 파일 대신 `-m dataplane backend/tests/e2e`.
"""

import ipaddress
import re
import subprocess
import time
import uuid

import pytest

import live_api
from live_api import LOC, TIB, UUID_RE, call, create_pool, poll, pool_url
from dataplane_live import (
    ACCT, agent_call, agent_job, create_volume, dataplane, db_ops, db_rows, default_rule, delete_volume,
    e2e_user, error_of, fsid_of, GIB, instance_ip, lv_name, lvs_volumes, mount_ip, note, one_shot, ops_for,
    out, POLL, POOL, proc_uid, setup_pool, SKIP_UNLESS_ROOT, SUBNET_ID, token, vol_body, vol_list_url,
    vol_path, vol_url, VOLUME_NET, VOLUME_TYPE,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]


# --- AC-01 ---


def test_ac01_create_nfsv3_volume_contract_and_state(agent, api):
    srv = api()
    assert proc_uid(srv.proc.pid) == e2e_user().pw_uid  # anf-api는 일반 사용자 권한 (§8 공통 조건)
    assert "ANF_MIN_VOLUME_SIZE_GIB=1" in srv.output()  # 결정 3의 경고 로그
    setup_pool()
    tok, cid = token("ac01"), str(uuid.uuid4())
    before = dataplane()

    r = call("PUT", vol_url(ACCT, POOL, "vol1"), vol_body(tok, 100 * GIB),
             headers={"x-ms-correlation-request-id": cid})
    assert r.status == 201, r.raw
    created = r.json()
    lro_headers = sorted(h for h in r.headers if h in ("azure-asyncoperation", "location", "retry-after"))
    note("AC-01 PUT", status=r.status, lro_headers=lro_headers, body=created)
    assert created["properties"]["provisioningState"] == "Creating"
    assert "mountTargets" not in created["properties"]
    assert lro_headers == ["azure-asyncoperation"]

    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    note("AC-01 operation", seen=seen, final=final)
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "CREATE"

    g = call("GET", vol_url(ACCT, POOL, "vol1"))
    assert g.status == 200, g.raw
    v = g.json()
    p = v["properties"]
    note("AC-01 GET", body=v)
    assert v["id"] == vol_path(ACCT, POOL, "vol1")
    assert v["name"] == f"{ACCT}/{POOL}/vol1" and v["type"] == VOLUME_TYPE
    assert p["provisioningState"] == "Succeeded"
    assert re.fullmatch(UUID_RE, p["fileSystemId"])
    assert len(p["mountTargets"]) == 1
    mt = p["mountTargets"][0]
    assert mt["mountTargetId"] == mt["fileSystemId"] == p["fileSystemId"]
    assert ipaddress.ip_address(mt["ipAddress"]) in VOLUME_NET
    assert p["protocolTypes"] == ["NFSv3"]
    assert p["exportPolicy"] == {"rules": [default_rule(True, False)]}
    assert p["unixPermissions"] == "0770"
    assert p["serviceLevel"] == "Premium"
    assert p["actualThroughputMibps"] == 6.25
    assert p["usageThreshold"] == 100 * GIB and p["creationToken"] == tok

    listing = call("GET", vol_list_url(ACCT, POOL))
    assert listing.status == 200
    assert [x["id"] for x in listing.json()["value"]] == [v["id"]]

    # 보조 증거: 데이터 플레인 객체가 생겼고 IP가 일치한다. 상관 ID가 agent 로그에 있다 (NFR-08)
    fsid = p["fileSystemId"]
    after = dataplane()
    lvs = lvs_volumes()
    note("AC-01 dataplane", before=before, after=after, lv=lvs.get(lv_name(fsid)),
         instance_ip=instance_ip(fsid), correlation_in_agent_log=cid in agent.text())
    assert lvs[lv_name(fsid)]["size"] == 100 * GIB
    assert instance_ip(fsid) == mt["ipAddress"]
    assert cid in agent.text()

    delete_volume("vol1")


# --- AC-05 ---


def test_ac05_capacity_and_parent_rules(agent, api):
    delay = 8
    srv = api(faults={"capacityPools/delete": {"delaySeconds": delay}, "capacityPools/patch": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool(4 * TIB)
    v1 = create_volume("v1", token("ac05a"), GIB)
    before = dataplane()

    # 풀 할당량 합 초과: 1 GiB + 4 TiB > 4 TiB
    r = call("PUT", vol_url(ACCT, POOL, "v2"), vol_body(token("ac05b"), 4 * TIB))
    note("AC-05 over pool size", error=error_of(r))
    assert error_of(r) == (400, "BadRequest", "Pool size too small for total volume size.")
    assert ops_for(db, vol_path(ACCT, POOL, "v2")) == []

    # 없는 풀
    r = call("PUT", vol_url(ACCT, "nopool", "v3"), vol_body(token("ac05c")))
    note("AC-05 missing pool", error=error_of(r), headers=r.headers)
    assert r.status == 404 and r.json()["error"]["code"] == "ParentResourceNotFound"

    # Deleting 풀 아래
    create_pool(ACCT, "p-del", 4 * TIB, "Premium")
    d = call("DELETE", pool_url(ACCT, "p-del"))
    assert d.status == 202
    assert call("GET", pool_url(ACCT, "p-del")).json()["properties"]["provisioningState"] == "Deleting"
    r = call("PUT", vol_url(ACCT, "p-del", "v4"), vol_body(token("ac05d")))
    note("AC-05 pool deleting", error=error_of(r))
    assert r.status == 409 and r.json()["error"]["code"] == "Conflict"
    final, _ = poll(d.headers["azure-asyncoperation"], delay + POLL)
    assert final["status"] == "Succeeded"
    assert ops_for(db, vol_path(ACCT, "p-del", "v4")) == []

    # (§4.3 보조) Succeeded가 아닌 풀(Patching) 아래
    pt = call("PATCH", pool_url(ACCT, POOL), {"tags": {"k": "v"}})
    assert pt.status == 202
    r = call("PUT", vol_url(ACCT, POOL, "v5"), vol_body(token("ac05e")))
    note("AC-05 pool patching", error=error_of(r))
    assert error_of(r) == (400, "BadRequest", "Volume cannot be created in a pool that isn't in state succeeded.")
    assert poll(pt.headers["azure-asyncoperation"], delay + POLL)[0]["status"] == "Succeeded"

    # CV-1
    r = call("DELETE", pool_url(ACCT, POOL))
    note("CV-1", error=error_of(r))
    assert r.status == 409 and r.json()["error"]["code"] == "CannotDeleteResource"
    assert f"Microsoft.NetApp/netAppAccounts/{ACCT}/capacityPools/{POOL}/volumes/v1" in r.json()["error"]["message"]
    assert call("GET", pool_url(ACCT, POOL)).json()["properties"]["provisioningState"] == "Succeeded"

    # CV-3. serviceLevel은 PUT으로만 바꾼다. PATCH 모델에는 없어 모르는 속성이다 (풀 설계 결정 5, §4.3)
    r1 = call("PATCH", pool_url(ACCT, POOL), {"properties": {"serviceLevel": "Standard"}})
    r2 = call("PUT", pool_url(ACCT, POOL), {"location": LOC, "properties": {"size": 4 * TIB, "serviceLevel": "Ultra"}})
    note("CV-3", patch=error_of(r1), put=error_of(r2))
    assert error_of(r1)[:2] == (400, "InvalidRequestContent")
    assert error_of(r2) == (400, "BadRequest", "ServiceLevel cannot be changed.")
    assert call("GET", pool_url(ACCT, POOL)).json()["properties"]["serviceLevel"] == "Premium"

    # CV-2: 실제 볼륨 합은 aggregate(약 1 TiB)를 넘을 수 없어 1 TiB 하한의 풀을 줄일 수 없다.
    # 그래서 agent가 aggregate 부족으로 실패시킨 Failed 볼륨의 예약(1025 GiB)으로 확인한다
    create_pool(ACCT, "p-cv2", 2 * TIB, "Premium")
    r = call("PUT", vol_url(ACCT, "p-cv2", "v6"), vol_body(token("ac05f"), 1025 * GIB))
    assert r.status == 201, r.raw
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    v6 = call("GET", vol_url(ACCT, "p-cv2", "v6")).json()
    agent_reason = [line for line in agent.text().splitlines() if "aggregate aggr0 has" in line][-1:]
    note("CV-2 reservation volume", final=final, seen=seen, state=v6["properties"]["provisioningState"],
         agent_reason=agent_reason)
    assert final["status"] == "Failed" and final["error"]["code"] == "InternalServerError"
    assert v6["properties"]["provisioningState"] == "Failed"
    r1 = call("PATCH", pool_url(ACCT, "p-cv2"), {"properties": {"size": TIB}})
    r2 = call("PUT", pool_url(ACCT, "p-cv2"), {"location": LOC, "properties": {"size": TIB, "serviceLevel": "Premium"}})
    note("CV-2", patch=error_of(r1), put=error_of(r2))
    assert r1.status == 400 and r1.json()["error"]["code"] == "BadRequest"
    assert r2.status == 400 and r2.json()["error"]["code"] == "BadRequest"
    assert call("GET", pool_url(ACCT, "p-cv2")).json()["properties"]["size"] == 2 * TIB

    after = dataplane()
    note("AC-05 dataplane", before=before, after=after)
    assert after == before  # 거절된 요청은 LV·인스턴스를 만들지 않았다 (v1만 있다)
    assert [x["id"] for x in db_rows(db) if x["type"] == VOLUME_TYPE] == sorted(
        [v1["id"], vol_path(ACCT, "p-cv2", "v6")])

    delete_volume("v6", pool="p-cv2")
    delete_volume("v1")


# --- AC-06 ---


def test_ac06_invalid_bodies_rejected(agent, api):
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("ac06")
    custom_rule = {**default_rule(True, False), "allowedClients": "10.0.0.0/8"}
    cases = [
        ("name 1vol", "1vol", vol_body(tok)),
        ("name 65 chars", "v" * 65, vol_body(tok)),
        ("creationToken missing", "v06", vol_body(None)),
        ("creationToken -a", "v06", vol_body("-a")),
        ("creationToken 81 chars", "v06", vol_body("t" * 81)),
        ("usageThreshold not GiB multiple", "v06", vol_body(tok, GIB + 1)),
        ("usageThreshold below minimum (0, min 1 GiB)", "v06", vol_body(tok, 0)),
        ("usageThreshold over 100 TiB", "v06", vol_body(tok, 100 * TIB + GIB)),
        ("protocolTypes CIFS", "v06", vol_body(tok, protocols=["CIFS"])),
        ("protocolTypes NFSv3+NFSv4.1", "v06", vol_body(tok, protocols=["NFSv3", "NFSv4.1"])),
        ("protocolTypes []", "v06", vol_body(tok, protocols=[])),
        ("subnetId not an ID", "v06", vol_body(tok, subnet="not-a-subnet")),
        ("subnetId VNet without subnet", "v06", vol_body(tok, subnet=SUBNET_ID.rsplit("/subnets/", 1)[0])),
        ("subnetId missing", "v06", vol_body(tok, subnet=None)),
        ("exportPolicy custom rule", "v06", vol_body(tok, exportPolicy={"rules": [custom_rule]})),
        # FR-08 전에는 미룬 속성이었다. 이제 범위(1~4,500) 밖의 값이 본문 단계에서 거절된다 (처리량 §4.2)
        ("throughputMibps below 1", "v06", vol_body(tok, throughputMibps=0.5)),
        ("snapshotDirectoryVisible false", "v06", vol_body(tok, snapshotDirectoryVisible=False)),
        ("snapshotId", "v06", vol_body(tok, snapshotId=str(uuid.uuid4()))),
        ("kerberosEnabled true", "v06", vol_body(tok, kerberosEnabled=True)),
        ("unknown property", "v06", vol_body(tok, fooBar=1)),
        ("unknown top-level property", "v06", {**vol_body(tok), "fooBar": 1}),
        ("serviceLevel differs from pool", "v06", vol_body(tok, serviceLevel="Standard")),
    ]
    ops_before, before = len(db_ops(db)), dataplane()
    results = []
    for label, name, body in cases:
        r = call("PUT", vol_url(ACCT, POOL, name), body)
        results.append((label, *error_of(r)))
    for row in results:
        note("AC-06", case=row[0], status=row[1], code=row[2], message=row[3])
    assert [row for row in results if row[1] != 400] == []
    assert {row[2] for row in results[:2]} == {"InvalidResourceName"}
    assert {row[2] for row in results[2:]} == {"InvalidRequestContent"}
    assert len(db_ops(db)) == ops_before
    assert [x for x in db_rows(db) if x["type"] == VOLUME_TYPE] == []
    assert dataplane() == before

    # 대조: 미룬 속성도 클론이 지금 하는 값과 같으면 받는다 (구현 중 변경)
    ok = call("PUT", vol_url(ACCT, POOL, "v06ok"),
              vol_body(tok, snapshotDirectoryVisible=True, kerberosEnabled=False,
                       exportPolicy={"rules": [default_rule(True, False)]}))
    note("AC-06 control (default values)", status=ok.status)
    assert ok.status == 201, ok.raw
    assert poll(ok.headers["azure-asyncoperation"], POLL)[0]["status"] == "Succeeded"
    delete_volume("v06ok")

    # 최소 크기 주입을 끈 서버: 49 GiB는 400, 50 GiB는 통과
    srv.stop()
    srv2 = api(min_gib=None, db=db)
    assert "ANF_MIN_VOLUME_SIZE_GIB" not in srv2.output()
    r49 = call("PUT", vol_url(ACCT, POOL, "v49"), vol_body(token("ac06m49"), 49 * GIB))
    r50 = call("PUT", vol_url(ACCT, POOL, "v50"), vol_body(token("ac06m50"), 50 * GIB))
    note("AC-06 default minimum", r49=error_of(r49), r50_status=r50.status)
    assert error_of(r49)[:2] == (400, "InvalidRequestContent")
    assert r50.status == 201, r50.raw
    final, _ = poll(r50.headers["azure-asyncoperation"], POLL)
    assert final["status"] == "Succeeded"
    v50 = call("GET", vol_url(ACCT, POOL, "v50")).json()
    assert lvs_volumes()[lv_name(fsid_of(v50))]["size"] == 50 * GIB
    delete_volume("v50")


# --- AC-07 ---


def test_ac07_path_uniqueness_and_immutable_properties(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("ac07")
    v = create_volume("v07", tok)
    ip, fsid = mount_ip(v), fsid_of(v)
    c = clients()
    c.mount(ip, tok, "3")
    assert c.run("echo first > /m/f && sync").returncode == 0
    before = dataplane()

    dup = call("PUT", vol_url(ACCT, POOL, "v07b"), vol_body(tok))
    dup_case = call("PUT", vol_url(ACCT, POOL, "v07c"), vol_body(tok.upper()))
    note("AC-07 duplicate path", same=error_of(dup), case_only=error_of(dup_case))
    for r in (dup, dup_case):
        assert error_of(r) == (400, "BadRequest", "File path already in use.")
    assert ops_for(db, vol_path(ACCT, POOL, "v07b")) == ops_for(db, vol_path(ACCT, POOL, "v07c")) == []
    assert dataplane() == before
    still = one_shot(ip, tok, "3", "cat /m/f")
    assert still.returncode == 0 and still.stdout == "first\n", out(still)

    changes = {
        "creationToken": call("PUT", vol_url(ACCT, POOL, "v07"), vol_body(tok + "x")),
        "subnetId": call("PUT", vol_url(ACCT, POOL, "v07"),
                         vol_body(tok, subnet=SUBNET_ID.replace("/subnets/anf", "/subnets/other"))),
        "usageThreshold": call("PUT", vol_url(ACCT, POOL, "v07"), vol_body(tok, 2 * GIB)),
    }
    for key, r in changes.items():
        note("AC-07 change", property=key, error=error_of(r))
    assert error_of(changes["creationToken"]) == (400, "BadRequest", "CreationToken cannot be changed.")
    assert error_of(changes["subnetId"])[:2] == (400, "BadRequest")
    assert error_of(changes["usageThreshold"])[:2] == (400, "InvalidRequestContent")
    g = call("GET", vol_url(ACCT, POOL, "v07")).json()["properties"]
    assert (g["creationToken"], g["usageThreshold"], g["subnetId"], g["provisioningState"]) == (
        tok, GIB, SUBNET_ID, "Succeeded")
    assert [o["action"] for o in ops_for(db, vol_path(ACCT, POOL, "v07"))] == ["CREATE"]
    df = c.run("df -B1 /m | tail -1; cat /m/f")
    assert lvs_volumes()[lv_name(fsid)]["size"] == GIB
    note("AC-07 after rejected changes", client=out(df), lv_size=lvs_volumes()[lv_name(fsid)]["size"])
    assert df.returncode == 0 and df.stdout.splitlines()[-1] == "first"
    assert int(df.stdout.split()[1]) <= GIB
    assert one_shot(ip, tok + "x", "3").returncode != 0  # 바뀌지 않은 경로만 마운트된다

    same = call("PUT", vol_url(ACCT, POOL, "v07"), vol_body(tok))
    lro_headers = sorted(h for h in same.headers if h in ("azure-asyncoperation", "location"))
    assert same.status == 200, same.raw
    assert same.json()["properties"]["provisioningState"] == "Updating"
    final, seen = poll(same.headers["azure-asyncoperation"], POLL)
    note("AC-07 same-value PUT", status=same.status, lro_headers=lro_headers, seen=seen, final=final)
    assert lro_headers == ["azure-asyncoperation"]
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "UPDATE"
    rd = c.run("cat /m/f")
    assert rd.returncode == 0 and rd.stdout == "first\n"

    c.run("umount /m")
    delete_volume("v07")


# --- AC-08 ---


IO_LOOP = ('end=$(( $(date +%s) + {secs} )); n=0; '
           'while [ "$(date +%s)" -lt "$end" ]; do i=$((n % 20)); '
           'echo "$n" > /m/io.$i || exit 11; [ "$(cat /m/io.$i)" = "$n" ] || exit 12; n=$((n + 1)); done; '
           'echo "$n"')


def test_ac08_patch_tags_while_client_reads_and_writes(agent, api, clients):
    srv = api()
    db = srv.db_path
    setup_pool()
    tok = token("ac08")
    v = create_volume("v08", tok)
    c = clients()
    c.mount(mount_ip(v), tok, "3")

    loop = subprocess.Popen(["docker", "exec", c.name, "sh", "-c", IO_LOOP.format(secs=10)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    tags = {"env": "e2e", "ac": "08"}
    p = call("PATCH", vol_url(ACCT, POOL, "v08"), {"tags": tags})
    lro_headers = sorted(h for h in p.headers if h in ("azure-asyncoperation", "location"))
    assert p.status == 202, p.raw
    patching = p.json()
    final, seen = poll(p.headers["azure-asyncoperation"], POLL)
    loc = call("GET", p.headers["location"])
    g = call("GET", vol_url(ACCT, POOL, "v08")).json()
    stdout, stderr = loop.communicate(timeout=120)
    note("AC-08 PATCH", status=p.status, lro_headers=lro_headers,
         body_state=patching["properties"]["provisioningState"], seen=seen, final=final,
         location_status=loc.status, tags=g["tags"], io_loop={"rc": loop.returncode, "iterations": stdout.strip(),
                                                                "stderr": stderr})
    assert patching["properties"]["provisioningState"] == "Patching"
    assert lro_headers == ["azure-asyncoperation", "location"]
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "PATCH"
    assert loc.status == 200 and loc.json()["tags"] == tags
    assert g["tags"] == tags and g["properties"]["provisioningState"] == "Succeeded"
    assert loop.returncode == 0 and int(stdout.strip()) > 0

    r = call("PATCH", vol_url(ACCT, POOL, "v08"), {"properties": {"usageThreshold": 2 * GIB}})
    note("AC-08 PATCH usageThreshold", error=error_of(r))
    assert r.status == 400
    g = call("GET", vol_url(ACCT, POOL, "v08")).json()
    assert g["properties"]["usageThreshold"] == GIB and g["tags"] == tags
    assert [o["action"] for o in ops_for(db, vol_path(ACCT, POOL, "v08"))] == ["CREATE", "PATCH"]

    c.run("umount /m")
    delete_volume("v08")


# --- AC-10 ---


CONFLICT = ("Cannot modify resource with id '{}' because the resource entity provisioning state is not terminal. "
            "Please wait for the provisioning state to become terminal and then retry the request.")


def test_ac10_requests_during_create_conflict(agent, api):
    delay = 8
    srv = api(faults={"volumes/create": {"delaySeconds": delay}})
    db = srv.db_path
    setup_pool()
    tok = token("ac10")
    r = call("PUT", vol_url(ACCT, POOL, "v10"), vol_body(tok))
    assert r.status == 201
    rid = r.json()["id"]
    put = call("PUT", vol_url(ACCT, POOL, "v10"), vol_body(tok))
    patch = call("PATCH", vol_url(ACCT, POOL, "v10"), {"tags": {"a": "b"}})
    delete = call("DELETE", vol_url(ACCT, POOL, "v10"))
    status_now = call("GET", r.headers["azure-asyncoperation"]).json()["status"]
    ops = ops_for(db, rid)
    note("AC-10 conflicts", put=error_of(put), patch=error_of(patch), delete=error_of(delete),
         operation_status_after=status_now, operations=[(o["action"], o["status"]) for o in ops])
    for x in (put, patch, delete):
        assert error_of(x) == (409, "RequestConflict", CONFLICT.format(rid))
        assert "azure-asyncoperation" not in x.headers and "location" not in x.headers
    assert status_now == "Creating"
    assert [o["action"] for o in ops] == ["CREATE"]

    final, seen = poll(r.headers["azure-asyncoperation"], delay + POLL)
    note("AC-10 original operation", seen=seen, final=final)
    assert final["status"] == "Succeeded"
    v = call("GET", vol_url(ACCT, POOL, "v10")).json()
    assert v["tags"] == {}
    m = one_shot(mount_ip(v), tok, "3", "echo ok > /m/f && cat /m/f")
    assert m.returncode == 0, out(m)
    delete_volume("v10")


# --- AC-13 ---


def test_ac13_agent_api(agent):
    vid = str(uuid.uuid4())
    name = lv_name(vid)
    tok = token("ac13")
    body = {"uuid": vid, "name": name, "size": GIB,
            "nas": {"path": f"/{tok}", "unix_permissions": 770, "protocols": ["nfs3"]}}

    st, reply = agent_call("POST", "/api/storage/volumes", body)
    href = reply["job"]["_links"]["self"]["href"]
    job = agent_job(href)
    note("AC-13 POST", status=st, reply=reply, job=job)
    assert st == 202 and href == f"/api/cluster/jobs/{reply['job']['uuid']}"
    assert job["state"] == "success"

    st2, reply2 = agent_call("POST", "/api/storage/volumes", body)
    job2 = agent_job(reply2["job"]["_links"]["self"]["href"])
    count = [n for n in lvs_volumes() if n == name]
    note("AC-13 POST again", status=st2, job=job2, lvs=count)
    assert st2 == 202 and job2["state"] == "success" and len(count) == 1

    other = {**body, "nas": {**body["nas"], "path": f"/{tok}x"}}
    st3, reply3 = agent_call("POST", "/api/storage/volumes", other)
    job3 = agent_job(reply3["job"]["_links"]["self"]["href"])
    note("AC-13 POST other path", status=st3, job=job3)
    assert st3 == 202 and job3["state"] == "failure"

    st4, listing = agent_call("GET", f"/api/storage/volumes?name={name}")
    note("AC-13 GET ?name=", status=st4, listing=listing)
    assert st4 == 200 and listing["num_records"] == 1 and listing["records"][0]["uuid"] == vid
    st4b, record = agent_call("GET", f"/api/storage/volumes/{vid}")
    assert st4b == 200 and ipaddress.ip_address(record["data_lif"]["ip"]["address"]) in VOLUME_NET

    missing = str(uuid.uuid4())
    st5, reply5 = agent_call("DELETE", f"/api/storage/volumes/{missing}")
    job5 = agent_job(reply5["job"]["_links"]["self"]["href"])
    note("AC-13 DELETE missing", status=st5, job=job5)
    assert st5 == 202 and job5["state"] == "success"

    bad = {}
    for path in ("../x", "/../x", "/a/b", "/", f"/{tok}/.."):
        b = {**body, "uuid": str(uuid.uuid4())}
        b["name"] = lv_name(b["uuid"])
        b["nas"] = {**body["nas"], "path": path}
        bad[path] = agent_call("POST", "/api/storage/volumes", b)
    note("AC-13 bad paths", results=bad)
    assert {path: st for path, (st, _) in bad.items()} == {path: 400 for path in bad}

    st6, reply6 = agent_call("DELETE", f"/api/storage/volumes/{vid}")
    assert agent_job(reply6["job"]["_links"]["self"]["href"])["state"] == "success"
    assert name not in lvs_volumes()
