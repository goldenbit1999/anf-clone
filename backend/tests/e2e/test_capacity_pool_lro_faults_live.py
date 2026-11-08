"""capacity-pool 실환경 검증: 진행 중·실패·충돌·재시작, 부모 삭제 중 생성 (풀 설계 §8 AC-07, AC-10~AC-12).

ANF_FAULT_INJECTION을 켜고 anf-api를 uvicorn 프로세스로 다시 띄워 확인한다 (계정 설계 §6.3, 풀 설계 §7).
결함 키는 `capacityPools/{create|update|patch|delete}`다. 회복은 같은 DB로 주입 없이 다시 띄운 서버에서,
AC-12는 SIGKILL 뒤 같은 DB로 다시 띄운 서버에서 한다.

실행 (WSL, 저장소 루트):
    ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest \
        backend/tests/e2e/test_capacity_pool_lro_faults_live.py -m e2e -v
"""

import time
import uuid

import pytest

import live_api
from live_api import (
    LOC, POLL_TIMEOUT, TIB, account_url, call, create_account, create_pool, db_operations,
    db_resources, location_url, poll, pool_path, pool_url, port_open,
)

pytestmark = [pytest.mark.e2e, live_api.SKIP_UNLESS_LIVE]

DELAY = 5.0
POOL_DELAYS = {f"capacityPools/{a}": {"delaySeconds": DELAY} for a in ("create", "update", "patch", "delete")}
ACCT = "e2e-poolf-acct"


@pytest.fixture(scope="module", autouse=True)
def fresh_responses():
    live_api.RESPONSES.clear()


def ops_for(db, account, name):
    rid = pool_path(account, name).lower()
    return [o for o in db_operations(db) if o["resource_id"].lower() == rid]


def pool_state(account, name):
    r = call("GET", pool_url(account, name))
    assert r.status == 200, r.raw
    return r.json()["properties"]["provisioningState"]


def test_ac07_pool_put_while_parent_account_is_deleting_returns_409_conflict(start_server, tmp_path):
    db = tmp_path / "anf.db"
    start_server(db_path=db, faults={"netAppAccounts/delete": {"delaySeconds": DELAY}})
    acct, name = "e2e-poolf-acct7", "e2e-pf07"
    create_account(acct)

    d = call("DELETE", account_url(acct))
    assert d.status == 202
    assert call("GET", d.headers["azure-asyncoperation"]).json()["status"] == "Deleting"
    assert call("GET", account_url(acct)).json()["properties"]["provisioningState"] == "Deleting"

    r = call("PUT", pool_url(acct, name),
             {"location": LOC, "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}})
    assert r.status == 409, r.raw
    assert r.json()["error"]["code"] == "Conflict"
    assert r.json()["error"]["message"]
    assert "azure-asyncoperation" not in r.headers and "location" not in r.headers
    assert ops_for(db, acct, name) == []  # 보조 증거: 풀 작업이 생기지 않았다
    assert not [x for x in db_resources(db) if x["id"].lower() == pool_path(acct, name).lower()]
    # 계정은 아직 Deleting (거절 시점에 삭제가 끝나지 않았음)
    assert call("GET", account_url(acct)).json()["properties"]["provisioningState"] == "Deleting"

    final, seen = poll(d.headers["azure-asyncoperation"], DELAY + POLL_TIMEOUT)
    assert final["status"] == "Succeeded", (final, seen)
    assert call("GET", account_url(acct)).status == 404
    g = call("GET", pool_url(acct, name))
    assert g.status == 404
    assert g.json()["error"]["code"] == "ResourceNotFound"
    assert db_resources(db) == []  # 고아 풀이 없다


def test_ac10_in_progress_states_create_patch_delete(start_server):
    start_server(faults=POOL_DELAYS)
    create_account(ACCT)
    name = "e2e-pf10"

    # 생성
    put = call("PUT", pool_url(ACCT, name),
               {"location": LOC, "tags": {"a": "1"}, "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}})
    assert put.status == 201
    assert put.elapsed < DELAY / 5, put.elapsed
    aao = put.headers["azure-asyncoperation"]
    st = call("GET", aao).json()
    assert (st["status"], st["percentComplete"], st["properties"]["action"]) == ("Creating", 0.0, "CREATE")
    assert "endTime" not in st
    assert pool_state(ACCT, name) == "Creating"
    final, seen = poll(aao, DELAY + POLL_TIMEOUT)
    assert final["status"] == "Succeeded", (final, seen)
    assert seen[0] == "Creating"
    assert pool_state(ACCT, name) == "Succeeded"

    # PATCH
    patch = call("PATCH", pool_url(ACCT, name), {"tags": {"b": "2"}})
    assert patch.status == 202
    assert patch.elapsed < DELAY / 5, patch.elapsed
    assert patch.json()["properties"]["provisioningState"] == "Patching"
    aao_p, loc_p = patch.headers["azure-asyncoperation"], patch.headers["location"]
    st = call("GET", aao_p).json()
    assert (st["status"], st["percentComplete"], st["properties"]["action"]) == ("Patching", 0.0, "PATCH")
    assert pool_state(ACCT, name) == "Patching"
    lr = call("GET", loc_p)
    assert lr.status == 202, lr.raw
    assert lr.raw == b""
    assert lr.headers.get("location") == loc_p
    final_p, seen_p = poll(aao_p, DELAY + POLL_TIMEOUT)
    assert final_p["status"] == "Succeeded", (final_p, seen_p)
    assert seen_p[0] == "Patching"
    done = call("GET", loc_p)
    assert done.status == 200 and done.json()["tags"] == {"b": "2"}
    assert done.json()["properties"]["provisioningState"] == "Succeeded"

    # 삭제
    delete = call("DELETE", pool_url(ACCT, name))
    assert delete.status == 202
    aao_d, loc_d = delete.headers["azure-asyncoperation"], delete.headers["location"]
    st = call("GET", aao_d).json()
    assert (st["status"], st["percentComplete"], st["properties"]["action"]) == ("Deleting", 0.0, "DELETE")
    assert pool_state(ACCT, name) == "Deleting"
    assert call("GET", loc_d).status == 202
    final_d, seen_d = poll(aao_d, DELAY + POLL_TIMEOUT)
    assert final_d["status"] == "Succeeded", (final_d, seen_d)
    assert seen_d[0] == "Deleting"
    assert call("GET", loc_d).status == 204
    assert call("GET", pool_url(ACCT, name)).status == 404


def test_ac10_injected_create_failure_then_recovery_by_put(start_server, tmp_path):
    db = tmp_path / "anf.db"
    name = "e2e-pf10-cfail"
    body = {"location": LOC, "tags": {"v": "1"}, "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}}
    failing = start_server(db_path=db, faults={"capacityPools/create": {"fail": True}})
    create_account(ACCT)
    put = call("PUT", pool_url(ACCT, name), body)
    assert put.status == 201
    aao = put.headers["azure-asyncoperation"]
    final, seen = poll(aao)
    assert final["status"] == "Failed", (final, seen)
    assert final["error"]["code"] and final["error"]["message"], final
    assert final["properties"]["action"] == "CREATE"
    assert pool_state(ACCT, name) == "Failed"
    lr = call("GET", location_url(aao))
    assert lr.status == 500 and set(lr.json()) == {"error"}
    failing.stop()

    start_server(db_path=db)  # 주입 없음, 같은 DB
    assert pool_state(ACCT, name) == "Failed"
    retry = call("PUT", pool_url(ACCT, name), {**body, "tags": {"v": "2"}})
    assert retry.status == 200
    assert retry.json()["properties"]["provisioningState"] == "Updating"
    final2, seen2 = poll(retry.headers["azure-asyncoperation"])
    assert final2["status"] == "Succeeded", (final2, seen2)
    assert final2["properties"]["action"] == "UPDATE"
    g = call("GET", pool_url(ACCT, name)).json()
    assert g["properties"]["provisioningState"] == "Succeeded"
    assert g["tags"] == {"v": "2"}


def test_ac10_injected_patch_failure_rolls_back_tags_and_size(start_server, tmp_path):
    db = tmp_path / "anf.db"
    name = "e2e-pf10-pfail"
    failing = start_server(db_path=db, faults={"capacityPools/patch": {"fail": True}})
    create_account(ACCT)
    before = create_pool(ACCT, name, tags={"a": "1"})
    assert before["properties"]["size"] == 4 * TIB

    patch = call("PATCH", pool_url(ACCT, name),
                 {"tags": {"b": "2"}, "properties": {"size": 8 * TIB, "qosType": "Manual"}})
    assert patch.status == 202
    pb = patch.json()  # 설계 결정 9: 202 본문은 새 값
    assert pb["properties"]["provisioningState"] == "Patching"
    assert pb["tags"] == {"b": "2"} and pb["properties"]["size"] == 8 * TIB
    final, seen = poll(patch.headers["azure-asyncoperation"])
    assert final["status"] == "Failed", (final, seen)
    assert final["properties"]["action"] == "PATCH"
    assert final["error"]["code"] and final["error"]["message"]

    g = call("GET", pool_url(ACCT, name)).json()
    assert g["properties"]["provisioningState"] == "Failed"
    assert g["tags"] == {"a": "1"}
    assert g["properties"]["size"] == 4 * TIB
    assert g["properties"]["qosType"] == "Auto"
    assert g["properties"]["totalThroughputMibps"] == 256.0
    assert g["properties"]["poolId"] == before["properties"]["poolId"]
    assert call("GET", patch.headers["location"]).status == 500
    failing.stop()

    # 추가 확인 (설계 §5 Failed → Patching → Succeeded): 주입 없는 서버에서 PATCH로 회복
    start_server(db_path=db)
    rec = call("PATCH", pool_url(ACCT, name), {"tags": {"c": "3"}})
    assert rec.status == 202
    assert poll(rec.headers["azure-asyncoperation"])[0]["status"] == "Succeeded"
    g2 = call("GET", pool_url(ACCT, name)).json()
    assert g2["properties"]["provisioningState"] == "Succeeded"
    assert g2["tags"] == {"c": "3"} and g2["properties"]["size"] == 4 * TIB


def test_ac11_conflicting_requests_while_each_operation_is_in_progress(start_server, tmp_path):
    db = tmp_path / "anf.db"
    start_server(db_path=db, faults=POOL_DELAYS)
    create_account(ACCT)
    name = "e2e-pf11"

    def assert_conflicts(state):
        for method, body in (("PUT", {"location": LOC, "tags": {"other": "x"},
                                      "properties": {"size": 16 * TIB}}),
                             ("PATCH", {"tags": {"patched": "x"}, "properties": {"size": 16 * TIB}}),
                             ("DELETE", None)):
            r = call(method, pool_url(ACCT, name), body)
            assert r.status == 409, (state, method, r.raw)
            assert r.json()["error"]["code"] == "AnotherOperationInProgress", (state, method)
            assert "azure-asyncoperation" not in r.headers and "location" not in r.headers

    steps = [
        ("PUT", {"location": LOC, "tags": {"orig": "1"},
                 "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}}, 201, "Creating", {"orig": "1"}),
        ("PUT", {"location": LOC, "tags": {"upd": "1"}}, 200, "Updating", {"upd": "1"}),
        ("PATCH", {"tags": {"pat": "1"}}, 202, "Patching", {"pat": "1"}),
    ]
    for i, (method, body, code, state, tags_after) in enumerate(steps, start=1):
        r = call(method, pool_url(ACCT, name), body)
        assert r.status == code, (method, r.raw)
        aao = r.headers["azure-asyncoperation"]
        assert call("GET", aao).json()["status"] == state
        assert_conflicts(state)
        assert len(ops_for(db, ACCT, name)) == i  # 거절된 요청은 작업을 만들지 않았다 (보조 증거)
        final, seen = poll(aao, DELAY + POLL_TIMEOUT)
        assert final["status"] == "Succeeded", (state, final, seen)
        g = call("GET", pool_url(ACCT, name)).json()
        assert g["tags"] == tags_after, state  # 거절된 PUT·PATCH의 값이 반영되지 않았다
        assert g["properties"]["size"] == 4 * TIB, state
        assert g["properties"]["provisioningState"] == "Succeeded"

    delete = call("DELETE", pool_url(ACCT, name))
    assert delete.status == 202
    assert call("GET", delete.headers["azure-asyncoperation"]).json()["status"] == "Deleting"
    assert_conflicts("Deleting")
    assert len(ops_for(db, ACCT, name)) == 4
    final, _ = poll(delete.headers["azure-asyncoperation"], DELAY + POLL_TIMEOUT)
    assert final["status"] == "Succeeded"
    assert call("GET", pool_url(ACCT, name)).status == 404
    assert [o["action"] for o in ops_for(db, ACCT, name)] == ["CREATE", "UPDATE", "PATCH", "DELETE"]
    assert all(o["status"] == "Succeeded" for o in ops_for(db, ACCT, name))


@pytest.mark.parametrize("restart_faults", [POOL_DELAYS, None],
                         ids=["restart-with-same-delay", "restart-without-faults"])
def test_ac12_create_and_patch_resume_after_sigkill_restart(start_server, tmp_path, restart_faults):
    db = tmp_path / "anf.db"
    first = start_server(db_path=db, faults=POOL_DELAYS)
    create_account(ACCT)
    a, b = "e2e-pf12-a", "e2e-pf12-b"
    create_pool(ACCT, b, tags={"before": "patch"}, timeout=DELAY + POLL_TIMEOUT)

    patch = call("PATCH", pool_url(ACCT, b), {"tags": {"after": "patch"}, "properties": {"size": 8 * TIB}})
    assert patch.status == 202
    put = call("PUT", pool_url(ACCT, a), {"location": LOC, "properties": {"size": 4 * TIB, "serviceLevel": "Ultra"}})
    assert put.status == 201
    aao_a, aao_b = put.headers["azure-asyncoperation"], patch.headers["azure-asyncoperation"]
    assert call("GET", aao_a).json()["status"] == "Creating"
    assert call("GET", aao_b).json()["status"] == "Patching"

    rc = first.sigkill()
    assert rc == -9
    assert not port_open()
    assert [o["status"] for o in ops_for(db, ACCT, a)] == ["Creating"]
    assert [o["status"] for o in ops_for(db, ACCT, b)] == ["Succeeded", "Patching"]

    restarted_at = time.monotonic()
    start_server(db_path=db, faults=restart_faults)
    for aao, label in ((aao_a, "create"), (aao_b, "patch")):
        final, seen = poll(aao, DELAY + POLL_TIMEOUT)
        assert final["status"] == "Succeeded", (label, final, seen)
    assert time.monotonic() - restarted_at <= DELAY + POLL_TIMEOUT
    ga = call("GET", pool_url(ACCT, a)).json()
    gb = call("GET", pool_url(ACCT, b)).json()
    assert ga["properties"]["provisioningState"] == "Succeeded"
    assert gb["properties"]["provisioningState"] == "Succeeded"
    assert gb["tags"] == {"after": "patch"} and gb["properties"]["size"] == 8 * TIB
    assert len(ops_for(db, ACCT, a)) == 1 and len(ops_for(db, ACCT, b)) == 2  # 새 작업이 생기지 않았다


def test_extra_fault_keys_follow_registered_handlers(start_server, tmp_path):
    """수락 기준 밖 (풀 설계 "구현 중 변경"): 받는 결함 키는 등록된 처리기에서 만든다."""
    for raw, needle in (('{"capacityPools/resize": {"fail": true}}', "Unknown fault key 'capacityPools/resize'"),
                        ('{"netAppAccounts/patch": {"fail": true}}', "Unknown fault key 'netAppAccounts/patch'")):
        srv = start_server(db_path=tmp_path / f"bad-{uuid.uuid4().hex[:6]}.db", raw_faults=raw, wait=False)
        rc = srv.proc.wait(30)
        assert rc != 0, srv.output()
        assert needle in srv.output(), srv.output()
        assert not port_open()

    every_key = {**POOL_DELAYS, **{f"netAppAccounts/{a}": {"delaySeconds": 0} for a in ("create", "update", "delete")}}
    ok = start_server(db_path=tmp_path / "ok.db", faults=every_key)
    assert "Fault injection is enabled" in ok.output()
    for key in every_key:
        assert key in ok.output(), key


def test_extra_every_fault_scenario_response_has_request_id():
    responses = list(live_api.RESPONSES)
    assert len(responses) > 30
    missing = [(r.method, r.target, r.status) for r in responses if "x-ms-request-id" not in r.headers]
    assert not missing
    ids = [r.headers["x-ms-request-id"] for r in responses]
    assert len(set(ids)) == len(ids)
    assert {r.status for r in responses} >= {200, 201, 202, 204, 404, 409, 500}
