"""처리량 한도 e2e (1/2): ARM 계약과 상태 전이, agent API, 인스턴스 netns의 tc (처리량 설계 §8).

- AC-01 (a) Auto 볼륨의 actualThroughputMibps, 풀 utilizedThroughputMibps, netns HTB rate
- AC-02 Manual 풀 볼륨 생성: 201·Creating → Succeeded, 값, 풀 합, HTB rate (소수 값 포함)
- AC-07 (f) 볼륨 삭제: 호스트에 IFB가 새로 생기지 않고 인스턴스 netns가 사라진다
- AC-08 거절: 코드·문구, 볼륨 행·작업 없음, 기존 값·풀 값·HTB rate 그대로. 정확히 남은 예산은 받는다
- AC-10 실패·재시작 안전: 지연 중 anf-api SIGKILL, 실패 주입 뒤 같은 PATCH
- AC-11 storage agent API의 qos

데이터 처리량 측정은 test_throughput_limit_data_live.py에 있다 (AC-10 (a)의 잰 값만 여기서 잰다).

실행 (WSL, root, 저장소 루트):
    wsl -d Ubuntu -u root -e bash -c 'cd /mnt/c/<repo> && PYTHONDONTWRITEBYTECODE=1 \
        ANF_E2E_API_URL=http://127.0.0.1:8080 /home/<user>/.venvs/anf-clone/bin/python -m pytest \
        -p no:cacheprovider backend/tests/e2e/test_throughput_limit_contract_live.py -v -s'
"""

import os
import signal
import time
import uuid
from pathlib import Path

import pytest

import live_api
from live_api import TIB, call, create_account, create_pool, poll, pool_path, pool_url
from dataplane_live import (
    ACCT, agent_call, agent_job, db_ops, db_rows, delete_volume, error_of, fsid_of, GIB, instances,
    instance_name, lv_name, lvs_volumes, mount_ip, note, ops_for, POLL, sh, SKIP_UNLESS_ROOT, token, vol_body,
    vol_path, vol_url,
)
from restore_live import put_restore
from revert_live import instance_pid
from snapshot_live import create_snapshot
from throughput_live import (
    bare, get_volume, host_ifbs, limits, make, matches, measure, patch_volume, pool_props, tc_state, within,
)

pytestmark = [pytest.mark.e2e, pytest.mark.dataplane, live_api.SKIP_UNLESS_LIVE, SKIP_UNLESS_ROOT]

RANGE = "The 'properties.throughputMibps' property must be a number from 1 to 4500."
REQUIRED = "The 'properties.throughputMibps' property is required for a volume in a Manual QoS capacity pool."
AUTO_ONLY = "The 'properties.throughputMibps' property can be set only for a volume in a Manual QoS capacity pool."


# --- AC-01 (a) ---


def test_ac01a_auto_volume_values_and_rates(agent, api):
    api()
    create_account(ACCT)
    create_pool(ACCT, "auto-p", 4 * TIB, "Premium")
    create_pool(ACCT, "auto-s", TIB, "Standard")
    # 1 GiB Premium = 0.0625, 3 GiB Premium = 0.1875 → half-even 0.062·0.188 (결정 2), 1 GiB Standard = 0.015625
    cases = [("p1", "auto-p", GIB, 0.062), ("p3", "auto-p", 3 * GIB, 0.188), ("s1", "auto-s", GIB, 0.016)]
    for name, pool, size, want in cases:
        r, final, seen, v = make(name, token(f"t1{name}"), pool, size)
        p = v["properties"]
        tc = tc_state(fsid_of(v))
        note("AC-01a volume", name=name, pool=pool, size=size, put=r.json()["properties"], seen=seen,
             actual=p["actualThroughputMibps"], throughput=p.get("throughputMibps"), tc=tc)
        assert "throughputMibps" not in r.json()["properties"] and "throughputMibps" not in p
        assert p["actualThroughputMibps"] == want
        assert matches(tc, want), tc
    pools = {n: pool_props(n) for n in ("auto-p", "auto-s")}
    note("AC-01a pools", pools=pools)
    assert pools["auto-p"]["utilizedThroughputMibps"] == 0.25  # 0.062 + 0.188
    assert pools["auto-s"]["utilizedThroughputMibps"] == 0.016
    for name, pool, *_ in cases:
        delete_volume(name, pool=pool)


# --- AC-02 ---


def test_ac02_manual_volume_create_values_and_rates(agent, api):
    api()
    create_account(ACCT)
    create_pool(ACCT, "man", 40 * TIB, "Ultra", qos_type="Manual")  # 총 5,120 MiB/s
    cases = [("m10", ["NFSv4.1"], 10), ("m20", None, 20), ("m125", None, 12.5)]
    for name, protocols, mibps in cases:
        r = call("PUT", vol_url(ACCT, "man", name), vol_body(token(f"t2{name}"), GIB, protocols, throughputMibps=mibps))
        assert r.status == 201, r.raw
        created = r.json()["properties"]
        final, seen = poll(r.headers["azure-asyncoperation"], POLL)
        v = get_volume(name, "man")
        p = v["properties"]
        tc = tc_state(fsid_of(v))
        note("AC-02 volume", name=name, protocols=p["protocolTypes"], put=created, seen=seen, final=final,
             throughput=p["throughputMibps"], actual=p["actualThroughputMibps"], tc=tc)
        assert created["provisioningState"] == "Creating"
        assert created["throughputMibps"] == created["actualThroughputMibps"] == mibps
        assert seen[0] == "Creating" and final["status"] == "Succeeded" and final["properties"]["action"] == "CREATE"
        assert p["provisioningState"] == "Succeeded"
        assert p["throughputMibps"] == p["actualThroughputMibps"] == mibps
        assert matches(tc, mibps), tc
    pool = pool_props("man")
    note("AC-02 pool", pool=pool)
    assert pool["qosType"] == "Manual" and pool["totalThroughputMibps"] == 5120
    assert pool["utilizedThroughputMibps"] == 42.5
    for name, *_ in cases:
        delete_volume(name, pool="man")


# --- AC-07 (f) ---


def netns_users(ns: str) -> dict:
    """그 netns(`net:[inode]`)를 쓰는 프로세스와 nsfs 바인드 마운트."""
    pids = []
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if os.readlink(p / "ns" / "net") == ns:
                    pids.append(int(p.name))
            except OSError:
                pass
    mounts = [line for line in sh("findmnt", "-rn", "-t", "nsfs", "-o", "TARGET,SOURCE").stdout.splitlines()
              if ns in line]
    return {"pids": pids, "nsfs_mounts": mounts}


def test_ac07f_delete_leaves_no_ifb_and_the_netns_goes(agent, api):
    api()
    create_account(ACCT)
    create_pool(ACCT, "del", 2 * TIB, "Ultra", qos_type="Manual")
    ifbs_before = host_ifbs()
    *_, v = make("d1", token("t7f"), "del", throughputMibps=10)
    fsid = fsid_of(v)
    pid = instance_pid(fsid)
    ns = os.readlink(f"/proc/{pid}/ns/net")
    with_limit = {"tc": tc_state(fsid), "ifbs": host_ifbs(), "users": netns_users(ns)}
    delete_volume("d1", pool="del")
    after = {"ifbs": host_ifbs(), "users": netns_users(ns), "instance": instances().get(instance_name(fsid))}
    note("AC-07f delete", ifbs_before=ifbs_before, with_limit=with_limit, netns=ns, after=after)
    assert with_limit["tc"]["ifb0"] and with_limit["tc"]["rate_bits"] is not None and with_limit["users"]["pids"]
    assert with_limit["ifbs"] == ifbs_before  # IFB는 netns 안에만 있다
    assert after["ifbs"] == ifbs_before
    assert after["users"] == {"pids": [], "nsfs_mounts": []} and after["instance"] is None


# --- AC-08 ---


def budget(free: float, total: float = 256.0, pool: str = "rm") -> str:
    return (f"Requested throughput not available. Capacity pool '{pool}' has {total} MiB/s in total and "
            f"{free} MiB/s left for this volume.")


def test_ac08_rejections_change_nothing(agent, api):
    delay = 10
    srv = api(faults={"volumes/patch": {"delaySeconds": delay}})  # 진행 중 작업 409에 쓴다 (마지막 사례)
    db = srv.db_path
    create_account(ACCT)
    create_pool(ACCT, "rm", 2 * TIB, "Ultra", qos_type="Manual")  # 총 256 MiB/s
    create_pool(ACCT, "ra", 4 * TIB, "Premium")  # Auto
    *_, a = make("ra1", token("t8a"), "rm", throughputMibps=200)
    *_, auto = make("auto1", token("t8auto"), "ra")
    tx, tb, tc_ = token("t8x"), token("t8b"), token("t8c")
    results = {}

    def check(case, r, status, code, message):
        results[case] = error_of(r)
        assert results[case] == (status, code, message), (case, results[case])

    # 본문 형식과 Manual 풀 필수 (InvalidRequestContent)
    check("missing", call("PUT", vol_url(ACCT, "rm", "rx"), vol_body(tx)), 400, "InvalidRequestContent", REQUIRED)
    check("null", call("PUT", vol_url(ACCT, "rm", "rx"), vol_body(tx, throughputMibps=None)),
          400, "InvalidRequestContent", REQUIRED)
    for value in (0.5, 4500.5, "10", True):
        check(f"value {value!r}", call("PUT", vol_url(ACCT, "rm", "rx"), vol_body(tx, throughputMibps=value)),
              400, "InvalidRequestContent", RANGE)
    # Auto 풀 볼륨에 값 (생성과 갱신)
    check("auto create", call("PUT", vol_url(ACCT, "ra", "rax"), vol_body(token("t8ax"), throughputMibps=10)),
          400, "BadRequest", AUTO_ONLY)
    check("auto patch", patch_volume("auto1", "ra", {"throughputMibps": 10}), 400, "BadRequest", AUTO_ONLY)
    # 예산: 다른 볼륨 200 + 새 값 > 256
    check("budget create", call("PUT", vol_url(ACCT, "rm", "rx"), vol_body(tx, throughputMibps=57)),
          400, "BadRequest", budget(56.0))
    # 정확히 남은 예산은 받는다
    *_, b = make("rb", tb, "rm", throughputMibps=56)
    check("budget patch", patch_volume("rb", "rm", {"throughputMibps": 57}), 400, "BadRequest", budget(56.0))
    check("budget re-PUT", call("PUT", vol_url(ACCT, "rm", "rb"), vol_body(tb, throughputMibps=57)),
          400, "BadRequest", budget(56.0))
    snap, _ = create_snapshot("ra1", "s1", pool="rm")
    check("budget restore", put_restore("rc", tc_, snap["id"], pool="rm", throughputMibps=1),
          400, "BadRequest", budget(0.0))
    # Manual 풀 크기 축소, Manual → Auto
    check("pool shrink", call("PATCH", pool_url(ACCT, "rm"), {"properties": {"size": TIB}}), 400, "BadRequest",
          "The capacity pool throughput of 128.0 MiB/s is too small for the combined volume throughput of "
          "256.0 MiB/s of the capacity pool.")
    check("manual to auto", call("PATCH", pool_url(ACCT, "rm"), {"properties": {"qosType": "Auto"}}), 400,
          "BadRequest", "The QoS type of a capacity pool can't be changed from Manual to Auto.")

    ops_before = {n: len(ops_for(db, vol_path(ACCT, p, n))) for n, p in (("ra1", "rm"), ("rb", "rm"), ("auto1", "ra"))}
    # 진행 중 볼륨 작업이 있을 때 Auto → Manual (지연을 준 tags PATCH)
    busy = call("PATCH", vol_url(ACCT, "ra", "auto1"), {"tags": {"k": "v"}})
    assert busy.status == 202, busy.raw
    check("auto to manual while busy", call("PATCH", pool_url(ACCT, "ra"), {"properties": {"qosType": "Manual"}}),
          409, "Conflict",
          f"Cannot change the QoS type of capacity pool '{pool_path(ACCT, 'ra')}' because an operation is in "
          f"progress on volume '{vol_path(ACCT, 'ra', 'auto1')}'. Wait until it is finished, and then retry.")
    busy_final, _ = poll(busy.headers["azure-asyncoperation"], delay + POLL)

    rows = [r["id"] for r in db_rows(db)]
    rejected_ids = [vol_path(ACCT, "rm", "rx"), vol_path(ACCT, "ra", "rax"), vol_path(ACCT, "rm", "rc")]
    after = {"ra1": limits("ra1", "rm"), "rb": limits("rb", "rm"), "auto1": limits("auto1", "ra"),
             "rm": pool_props("rm"), "ra": pool_props("ra"),
             "tc": {"ra1": tc_state(fsid_of(a)), "rb": tc_state(fsid_of(b)), "auto1": tc_state(fsid_of(auto))}}
    ops_after = {n: len(ops_for(db, vol_path(ACCT, p, n))) for n, p in (("ra1", "rm"), ("rb", "rm"), ("auto1", "ra"))}
    note("AC-08 rejections", results=results, busy_final=busy_final, after=after, ops_before=ops_before,
         ops_after=ops_after, rejected_rows=[i for i in rows if i in rejected_ids],
         rejected_ops=[o for o in db_ops(db) if o["resource_id"] in rejected_ids])
    assert busy_final["status"] == "Succeeded"
    assert not [i for i in rows if i in rejected_ids]
    assert not [o for o in db_ops(db) if o["resource_id"] in rejected_ids]
    assert ops_after == {**ops_before, "auto1": ops_before["auto1"] + 1}  # tags PATCH 하나만 더해졌다
    assert after["ra1"] == {"throughputMibps": 200, "actualThroughputMibps": 200, "provisioningState": "Succeeded"}
    assert after["rb"] == {"throughputMibps": 56, "actualThroughputMibps": 56, "provisioningState": "Succeeded"}
    assert after["auto1"] == {"throughputMibps": None, "actualThroughputMibps": 0.062,
                              "provisioningState": "Succeeded"}
    assert after["rm"]["size"] == 2 * TIB and after["rm"]["qosType"] == "Manual"
    assert after["rm"]["utilizedThroughputMibps"] == 256.0 == after["rm"]["totalThroughputMibps"]
    assert after["ra"]["qosType"] == "Auto" and after["ra"]["utilizedThroughputMibps"] == 0.062
    assert matches(after["tc"]["ra1"], 200) and matches(after["tc"]["rb"], 56)
    assert matches(after["tc"]["auto1"], 0.062)
    for name, pool in (("rb", "rm"), ("ra1", "rm"), ("auto1", "ra")):
        delete_volume(name, pool=pool)


# --- AC-10 ---


def test_ac10a_anf_api_sigkill_during_patch_then_new_limit(agent, api, clients):
    delay = 8
    srv = api(faults={"volumes/patch": {"delaySeconds": delay}})
    db = srv.db_path
    create_account(ACCT)
    create_pool(ACCT, "kp", 2 * TIB, "Ultra", qos_type="Manual")
    tok = token("t10a")
    *_, v = make("k1", tok, "kp", throughputMibps=10)
    fsid = fsid_of(v)
    r = patch_volume("k1", "kp", {"throughputMibps": 20})
    assert r.status == 202, r.raw
    time.sleep(2)
    during = limits("k1", "kp")
    tc_at_kill = tc_state(fsid)
    rc = srv.sigkill()
    ops_at_kill = [(o["action"], o["status"]) for o in ops_for(db, v["id"])]
    api(db=db)
    final, seen = poll(r.headers["azure-asyncoperation"], POLL)
    after = limits("k1", "kp")
    tc_after = tc_state(fsid)
    c = clients()
    c.mount(mount_ip(v), tok, "3")
    m = measure(c, "write", "/m/f", 20)
    note("AC-10a SIGKILL during Patching", patch=r.json()["properties"], during=during, tc_at_kill=tc_at_kill,
         returncode=rc, ops_at_kill=ops_at_kill, seen=seen, final=final, after=after, tc_after=tc_after, write=m)
    assert r.json()["properties"]["provisioningState"] == "Patching" and r.json()["properties"]["throughputMibps"] == 20
    assert during["provisioningState"] == "Patching" and rc == -signal.SIGKILL
    assert ops_at_kill[-1] == ("PATCH", "Patching")
    assert matches(tc_at_kill, 10), tc_at_kill  # 지연 중이라 agent는 아직 옛 값이다
    assert final["status"] == "Succeeded" and final["properties"]["action"] == "PATCH"
    assert after == {"throughputMibps": 20, "actualThroughputMibps": 20, "provisioningState": "Succeeded"}
    assert matches(tc_after, 20), tc_after
    assert within(m["ratio"]), m
    c.remove()
    delete_volume("k1", pool="kp")


def test_ac10b_injected_failure_keeps_old_limit_then_same_patch_succeeds(agent, api):
    srv = api(faults={"volumes/patch": {"fail": True}})
    db = srv.db_path
    create_account(ACCT)
    create_pool(ACCT, "fp", 2 * TIB, "Ultra", qos_type="Manual")
    *_, v = make("f1", token("t10b"), "fp", throughputMibps=10)
    fsid = fsid_of(v)
    r = patch_volume("f1", "fp", {"throughputMibps": 20})
    assert r.status == 202, r.raw
    failed, seen = poll(r.headers["azure-asyncoperation"], POLL)
    after_fail = {**limits("f1", "fp"), "utilized": pool_props("fp")["utilizedThroughputMibps"]}
    tc_fail = tc_state(fsid)
    srv.stop()
    api(db=db)  # 주입을 끈다
    r2 = patch_volume("f1", "fp", {"throughputMibps": 20})
    assert r2.status == 202, r2.raw
    final, seen2 = poll(r2.headers["azure-asyncoperation"], POLL)
    after = {**limits("f1", "fp"), "utilized": pool_props("fp")["utilizedThroughputMibps"]}
    tc_after = tc_state(fsid)
    note("AC-10b injected failure", seen=seen, failed=failed, after_fail=after_fail, tc_fail=tc_fail,
         seen_retry=seen2, final=final, after=after, tc_after=tc_after)
    assert failed["status"] == "Failed"
    assert after_fail == {"throughputMibps": 10, "actualThroughputMibps": 10, "provisioningState": "Failed",
                          "utilized": 10}
    assert matches(tc_fail, 10), tc_fail
    assert final["status"] == "Succeeded"
    assert after == {"throughputMibps": 20, "actualThroughputMibps": 20, "provisioningState": "Succeeded",
                     "utilized": 20}
    assert matches(tc_after, 20), tc_after
    delete_volume("f1", pool="fp")


# --- AC-11 ---


def agent_post(body: dict) -> tuple[int, dict]:
    st, reply = agent_call("POST", "/api/storage/volumes", body)
    if st != 202:
        return st, reply
    return st, agent_job(reply["job"]["_links"]["self"]["href"], 180)


def qos_tags(lv: str) -> list[str]:
    return sorted(t for t in lvs_volumes()[lv]["tags"].split(",") if t.startswith("anf_qos="))


def test_ac11_agent_api_qos(agent):
    def body(vid, tag, qos=None):
        b = {"uuid": vid, "name": lv_name(vid), "size": GIB,
             "nas": {"path": f"/{token(tag)}", "unix_permissions": 770, "protocols": ["nfs3"]}}
        return b if qos is None else {**b, "qos": qos}

    vid, plain = str(uuid.uuid4()), str(uuid.uuid4())
    st, job = agent_post(body(vid, "t11", {"policy": {"max_throughput_mbps": 12.5}}))
    rec = agent_call("GET", f"/api/storage/volumes/{vid}")[1]
    first = {"status": st, "job": job, "qos": rec.get("qos"), "tags": qos_tags(lv_name(vid)), "tc": tc_state(vid)}

    st2, job2 = agent_post(body(vid, "t11", {"policy": {"max_throughput_mbps": 30}}))
    rec2 = agent_call("GET", f"/api/storage/volumes/{vid}")[1]
    second = {"status": st2, "job": job2, "qos": rec2.get("qos"), "tags": qos_tags(lv_name(vid)),
              "tc": tc_state(vid)}

    st3, job3 = agent_post(body(plain, "t11p"))
    rec3 = agent_call("GET", f"/api/storage/volumes/{plain}")[1]
    without = {"status": st3, "job": job3, "qos": rec3.get("qos"), "tags": qos_tags(lv_name(plain)),
               "tc": tc_state(plain)}

    bad = {"extra field": {"policy": {"max_throughput_mbps": 10}, "x": 1},
           "policy extra field": {"policy": {"max_throughput_mbps": 10, "min_throughput_mbps": 1}},
           "no policy": {}, "not an object": 10, "zero": {"policy": {"max_throughput_mbps": 0}},
           "negative": {"policy": {"max_throughput_mbps": -1}}, "string": {"policy": {"max_throughput_mbps": "10"}},
           "boolean": {"policy": {"max_throughput_mbps": True}}}
    rejected = {}
    lvs_before = sorted(lvs_volumes())
    for case, qos in bad.items():
        bid = str(uuid.uuid4())
        rejected[case] = agent_call("POST", "/api/storage/volumes", body(bid, "t11bad", qos))
    lvs_after = sorted(lvs_volumes())
    note("AC-11 agent qos", first=first, second=second, without=without, rejected=rejected,
         lvs_unchanged=lvs_before == lvs_after)
    assert st == 202 and job["state"] == "success", job
    assert first["qos"] == {"policy": {"max_throughput_mbps": 12.5}} and first["tags"] == ["anf_qos=12.5"]
    assert matches(first["tc"], 12.5), first["tc"]
    assert st2 == 202 and job2["state"] == "success", job2
    assert second["qos"] == {"policy": {"max_throughput_mbps": 30}} and second["tags"] == ["anf_qos=30.0"]
    assert matches(second["tc"], 30), second["tc"]
    assert st3 == 202 and job3["state"] == "success", job3
    assert without["qos"] is None and without["tags"] == [] and bare(without["tc"]), without["tc"]
    assert {case: s for case, (s, _) in rejected.items()} == {case: 400 for case in bad}
    assert lvs_before == lvs_after
    for x in (vid, plain):
        st_d, reply = agent_call("DELETE", f"/api/storage/volumes/{x}")
        assert agent_job(reply["job"]["_links"]["self"]["href"], 180)["state"] == "success"
