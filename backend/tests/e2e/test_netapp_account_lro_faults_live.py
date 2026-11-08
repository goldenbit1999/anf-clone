"""netapp-account 실환경 검증: 진행 중·실패·충돌·재시작 (계정 설계 §7 AC-08~AC-11, AC-13).

ANF_FAULT_INJECTION을 켜고 anf-api를 uvicorn 프로세스로 다시 띄워 확인한다 (설계 §6.3).
AC-09의 회복은 같은 DB로 주입 없이 다시 띄운 서버에서, AC-11은 SIGKILL 뒤 같은 DB로 다시 띄운 서버에서 한다.

실행 (WSL, 저장소 루트):
    ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest \
        backend/tests/e2e/test_netapp_account_lro_faults_live.py -m e2e -v
"""

import time
import uuid

import pytest

import live_api
from live_api import (
    LOC, POLL_TIMEOUT, account_path, account_url, call, db_operations, location_url, poll, port_open,
)

pytestmark = [pytest.mark.e2e, live_api.SKIP_UNLESS_LIVE]

DELAY = 5.0
DELAYS = {"netAppAccounts/create": {"delaySeconds": DELAY}, "netAppAccounts/delete": {"delaySeconds": DELAY}}


@pytest.fixture(scope="module", autouse=True)
def fresh_responses():
    live_api.RESPONSES.clear()


def ops_for(db, name):
    return [o for o in db_operations(db) if o["resource_id"].lower() == account_path(name).lower()]


def test_ac08_in_progress_states_with_injected_delay(start_server):
    start_server(faults=DELAYS)
    name = "e2e-ac08"

    put = call("PUT", account_url(name), {"location": LOC, "tags": {"k": "v"}})
    put_at = time.monotonic()
    assert put.status == 201
    assert put.elapsed < DELAY / 5, f"PUT took {put.elapsed:.3f}s with a {DELAY}s injected delay"
    aao = put.headers["azure-asyncoperation"]

    status = call("GET", aao)
    assert status.status == 200
    assert status.json()["status"] == "Creating"
    assert status.json()["percentComplete"] == 0.0
    assert status.json()["properties"]["action"] == "CREATE"
    assert call("GET", account_url(name)).json()["properties"]["provisioningState"] == "Creating"
    in_progress_loc = call("GET", location_url(aao))  # 생성 중 Location 방식도 202 (설계 §4.2)
    assert in_progress_loc.status == 202 and in_progress_loc.raw == b""

    final, seen = poll(aao, DELAY + POLL_TIMEOUT)
    assert final["status"] == "Succeeded", (final, seen)
    assert seen[0] == "Creating"
    took = time.monotonic() - put_at
    assert DELAY - 1 <= took <= DELAY + POLL_TIMEOUT, took
    assert call("GET", account_url(name)).json()["properties"]["provisioningState"] == "Succeeded"

    delete = call("DELETE", account_url(name))
    assert delete.status == 202
    loc, aao_del = delete.headers["location"], delete.headers["azure-asyncoperation"]
    lr = call("GET", loc)
    assert lr.status == 202
    assert lr.raw == b""
    assert lr.headers.get("location") == loc
    assert call("GET", account_url(name)).json()["properties"]["provisioningState"] == "Deleting"
    del_status = call("GET", aao_del).json()
    assert (del_status["status"], del_status["percentComplete"]) == ("Deleting", 0.0)

    final_del, seen_del = poll(aao_del, DELAY + POLL_TIMEOUT)
    assert final_del["status"] == "Succeeded", (final_del, seen_del)
    assert seen_del[0] == "Deleting"
    assert call("GET", loc).status == 204
    assert call("GET", account_url(name)).status == 404


def test_ac09_injected_create_failure_then_recovery(start_server, tmp_path):
    db = tmp_path / "anf.db"
    name = "e2e-ac09"

    failing = start_server(db_path=db, faults={"netAppAccounts/create": {"fail": True}})
    put = call("PUT", account_url(name), {"location": LOC, "tags": {"v": "1"}})
    assert put.status == 201
    aao = put.headers["azure-asyncoperation"]
    final, seen = poll(aao)
    assert final["status"] == "Failed", (final, seen)
    assert final["error"]["code"] and final["error"]["message"], final
    assert final["properties"]["action"] == "CREATE"

    lr = call("GET", location_url(aao))
    assert lr.status == 500
    assert set(lr.json()) == {"error"}
    assert lr.json()["error"]["code"] and lr.json()["error"]["message"]
    g = call("GET", account_url(name))
    assert g.status == 200
    assert g.json()["properties"]["provisioningState"] == "Failed"
    failing.stop()

    # 주입을 끈 서버, 같은 DB: 같은 계정에 PUT하면 200 Updating → Succeeded
    start_server(db_path=db)
    assert call("GET", account_url(name)).json()["properties"]["provisioningState"] == "Failed"
    retry = call("PUT", account_url(name), {"location": LOC, "tags": {"v": "2"}})
    assert retry.status == 200
    assert retry.json()["properties"]["provisioningState"] == "Updating"
    final2, seen2 = poll(retry.headers["azure-asyncoperation"])
    assert final2["status"] == "Succeeded", (final2, seen2)
    assert final2["properties"]["action"] == "UPDATE"
    g2 = call("GET", account_url(name))
    assert g2.json()["properties"]["provisioningState"] == "Succeeded"
    assert g2.json()["tags"] == {"v": "2"}


def test_ac09_injected_delete_failure_leaves_account_failed(start_server, tmp_path):
    db = tmp_path / "anf.db"
    name = "e2e-ac09-del"
    normal = start_server(db_path=db)
    put = call("PUT", account_url(name), {"location": LOC})
    assert put.status == 201
    assert poll(put.headers["azure-asyncoperation"])[0]["status"] == "Succeeded"
    normal.stop()

    start_server(db_path=db, faults={"netAppAccounts/delete": {"fail": True}})
    delete = call("DELETE", account_url(name))
    assert delete.status == 202
    final, seen = poll(delete.headers["azure-asyncoperation"])
    assert final["status"] == "Failed", (final, seen)
    assert final["error"]["code"] and final["error"]["message"]
    assert final["properties"]["action"] == "DELETE"
    g = call("GET", account_url(name))
    assert g.status == 200
    assert g.json()["properties"]["provisioningState"] == "Failed"
    assert call("GET", delete.headers["location"]).status == 500


def test_ac10_conflicting_requests_while_in_progress(start_server, tmp_path):
    db = tmp_path / "anf.db"
    start_server(db_path=db, faults=DELAYS)
    name = "e2e-ac10"

    put = call("PUT", account_url(name), {"location": LOC, "tags": {"orig": "1"}})
    assert put.status == 201
    aao = put.headers["azure-asyncoperation"]

    def assert_conflicts(state):
        for method, body in (("PUT", {"location": LOC, "tags": {"other": "x"}}),
                             ("PATCH", {"tags": {"patched": "1"}}),
                             ("DELETE", None)):
            r = call(method, account_url(name), body)
            assert r.status == 409, (state, method, r.raw)
            assert r.json()["error"]["code"] == "AnotherOperationInProgress", (state, method)
            assert "azure-asyncoperation" not in r.headers and "location" not in r.headers

    assert call("GET", aao).json()["status"] == "Creating"
    assert_conflicts("Creating")
    assert len(ops_for(db, name)) == 1  # 새 작업이 생기지 않았다 (보조 증거)

    final, seen = poll(aao, DELAY + POLL_TIMEOUT)
    assert final["status"] == "Succeeded", (final, seen)
    g = call("GET", account_url(name)).json()
    assert g["tags"] == {"orig": "1"}  # 거절된 PUT·PATCH의 tags가 반영되지 않았다
    assert g["properties"]["provisioningState"] == "Succeeded"

    # 삭제 진행 중에도 같다
    delete = call("DELETE", account_url(name))
    assert delete.status == 202
    assert call("GET", delete.headers["azure-asyncoperation"]).json()["status"] == "Deleting"
    assert_conflicts("Deleting")
    assert len(ops_for(db, name)) == 2
    final_del, _ = poll(delete.headers["azure-asyncoperation"], DELAY + POLL_TIMEOUT)
    assert final_del["status"] == "Succeeded"
    assert call("GET", account_url(name)).status == 404
    assert [o["action"] for o in ops_for(db, name)] == ["CREATE", "DELETE"]


@pytest.mark.parametrize("restart_faults", [DELAYS, None], ids=["restart-with-same-delay", "restart-without-faults"])
def test_ac11_operation_resumes_after_sigkill_restart(start_server, tmp_path, restart_faults):
    db = tmp_path / "anf.db"
    name = "e2e-ac11"
    first = start_server(db_path=db, faults=DELAYS)
    put = call("PUT", account_url(name), {"location": LOC})
    assert put.status == 201
    aao = put.headers["azure-asyncoperation"]
    assert call("GET", aao).json()["status"] == "Creating"

    rc = first.sigkill()
    assert rc == -9
    assert not port_open()
    assert [o["status"] for o in ops_for(db, name)] == ["Creating"]  # 죽을 때 작업은 진행 중이었다

    restarted_at = time.monotonic()
    start_server(db_path=db, faults=restart_faults)
    final, seen = poll(aao, DELAY + POLL_TIMEOUT)
    assert final["status"] == "Succeeded", (final, seen)
    assert time.monotonic() - restarted_at <= DELAY + POLL_TIMEOUT
    g = call("GET", account_url(name))
    assert g.status == 200
    assert g.json()["properties"]["provisioningState"] == "Succeeded"
    assert len(ops_for(db, name)) == 1


def test_s63_fault_injection_startup_guard_and_warning(start_server, tmp_path):
    """설계 §6.3 (수락 기준 밖, 추가 관찰): 잘못된 값이면 서버가 뜨지 않고, 켜면 경고 로그를 남긴다."""
    for raw in ('{"netAppAccounts/create": {"delaySeconds": 5}',  # JSON 아님
                '{"netAppAccounts/resize": {"fail": true}}',      # 모르는 키
                '{"netAppAccounts/patch": {"fail": true}}'):      # 계정 PATCH는 동기라 처리기가 없다 (풀 설계 "구현 중 변경")
        srv = start_server(db_path=tmp_path / f"bad-{uuid.uuid4().hex[:6]}.db", raw_faults=raw, wait=False)
        rc = srv.proc.wait(30)
        assert rc != 0, srv.output()
        assert "ANF_FAULT_INJECTION" in srv.output() or "fault key" in srv.output()
        assert not port_open()
        if "netAppAccounts/patch" in raw:
            assert "Unknown fault key 'netAppAccounts/patch'" in srv.output(), srv.output()

    ok = start_server(faults=DELAYS)
    assert "Fault injection is enabled" in ok.output()


def test_ac13_request_id_on_every_fault_scenario_response():
    responses = list(live_api.RESPONSES)
    assert len(responses) > 30
    missing = [(r.method, r.target, r.status) for r in responses if "x-ms-request-id" not in r.headers]
    assert not missing
    ids = [r.headers["x-ms-request-id"] for r in responses]
    assert len(set(ids)) == len(ids)
    assert {r.status for r in responses} >= {200, 201, 202, 204, 404, 409, 500}
