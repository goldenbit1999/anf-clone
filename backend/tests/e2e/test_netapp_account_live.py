"""netapp-account 실환경 검증: 계약과 상태 전이 (계정 설계 §7 AC-01~AC-07, AC-13).

WSL에서 anf-api를 uvicorn 프로세스로 띄우고 HTTP로 확인한다. 결함 주입 없는 서버 하나를 이 모듈 전체가 쓴다.
AC-12(데이터 플레인 불변)는 root 권한의 exportfs가 필요해서, 이 모듈 실행 전후에 셸에서 비교한다.

실행 (WSL, 저장소 루트):
    ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest \
        backend/tests/e2e/test_netapp_account_live.py -m e2e -v
"""

import re
import uuid

import pytest

import live_api
from live_api import (
    ACCOUNT_TYPE, BASE_URL, LOC, OTHER_RG, OTHER_SUB, RG, SUB, UUID_RE, V,
    account_path, account_url, call, create_account, db_operations, location_url, poll,
    rg_list_url, sub_list_url,
)

pytestmark = [pytest.mark.e2e, live_api.SKIP_UNLESS_LIVE]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    live_api.RESPONSES.clear()
    srv = live_api.Server(tmp_path_factory.mktemp("account-live") / "anf.db")
    srv.start()
    yield srv
    srv.stop()


def no_tracking_headers(r) -> bool:
    return "azure-asyncoperation" not in r.headers and "location" not in r.headers


def test_ac01_create_returns_201_creating_and_operation_succeeds(server):
    path = account_path("e2e-ac01")
    r = call("PUT", account_url("e2e-ac01"), {"location": LOC, "tags": {"k": "v"}})
    assert r.status == 201
    assert r.json()["properties"]["provisioningState"] == "Creating"
    aao = r.headers.get("azure-asyncoperation")
    assert aao, r.headers
    assert "location" not in r.headers  # Azure-AsyncOperation만 (녹화 R1)
    assert "retry-after" not in r.headers  # 설계 결정 5
    m = re.fullmatch(
        re.escape(f"{BASE_URL}/subscriptions/{SUB}/providers/Microsoft.NetApp/locations/{LOC}"
                  "/operationResults/") + f"({UUID_RE})" + re.escape(f"?{V}"), aao)
    assert m, aao
    op_id = m.group(1)

    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["percentComplete"] == 100.0
    assert final["properties"] == {"resourceName": path, "action": "CREATE"}
    assert final["id"] == f"/subscriptions/{SUB}/providers/Microsoft.NetApp/locations/{LOC}/operationResults/{op_id}"
    assert final["name"] == op_id
    assert final["startTime"] and final["endTime"]

    g = call("GET", account_url("e2e-ac01"))
    assert g.status == 200
    assert g.json()["properties"]["provisioningState"] == "Succeeded"


def test_ac02_put_existing_returns_200_updating_and_replaces_tags(server):
    create_account("e2e-ac02", tags={"old": "1", "keep": "no"})
    new_tags = {"new": "2", "x": "y"}
    r = call("PUT", account_url("e2e-ac02"), {"location": LOC, "tags": new_tags})
    assert r.status == 200
    assert r.json()["properties"]["provisioningState"] == "Updating"
    aao = r.headers.get("azure-asyncoperation")
    assert aao and aao.startswith(f"{BASE_URL}/subscriptions/{SUB}/providers/Microsoft.NetApp/locations/{LOC}/operationResults/")
    assert "location" not in r.headers

    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["properties"]["action"] == "UPDATE"
    g = call("GET", account_url("e2e-ac02"))
    assert g.status == 200
    assert g.json()["tags"] == new_tags
    assert g.json()["properties"]["provisioningState"] == "Succeeded"


def test_ac03_get_body_fields_not_found_and_case_insensitive_name(server):
    name = "E2e-Ac03-Mixed"
    body = create_account(name, tags={"k": "v"})
    assert body["id"] == account_path(name)
    assert body["name"] == name
    assert body["type"] == ACCOUNT_TYPE
    assert body["location"] == LOC
    assert body["tags"] == {"k": "v"}
    assert body["properties"]["provisioningState"] == "Succeeded"
    assert body["properties"]["encryption"] == {"keySource": "Microsoft.NetApp"}

    missing = call("GET", account_url("e2e-ac03-missing"))
    assert missing.status == 404
    assert missing.json()["error"]["code"] == "ResourceNotFound"
    assert missing.json()["error"]["message"]

    for variant in ("E2E-AC03-MIXED", "e2e-ac03-mixed"):
        g = call("GET", account_url(variant))
        assert g.status == 200, variant
        assert g.json() == body, variant  # 이름은 처음 받은 그대로 보존 (설계 결정 9)


def test_ac04_resource_group_and_subscription_lists(server):
    create_account("e2e-ac04")
    create_account("e2e-ac04-other", rg=OTHER_RG)

    def names(url):
        r = call("GET", url)
        assert r.status == 200
        assert set(r.json()) == {"value"}
        return {a["name"] for a in r.json()["value"]}

    in_rg = names(rg_list_url(RG))
    in_other_rg = names(rg_list_url(OTHER_RG))
    in_sub = names(sub_list_url(SUB))
    in_other_sub = names(sub_list_url(OTHER_SUB))
    assert "e2e-ac04" in in_rg and "e2e-ac04-other" not in in_rg
    assert "e2e-ac04-other" in in_other_rg and "e2e-ac04" not in in_other_rg
    assert {"e2e-ac04", "e2e-ac04-other"} <= in_sub
    assert not in_other_sub


def test_ac05_patch_tags_is_synchronous_and_replaces_map(server):
    create_account("e2e-ac05", tags={"a": "1"})
    r = call("PATCH", account_url("e2e-ac05"), {"tags": {"b": "2"}})
    assert r.status == 200
    assert no_tracking_headers(r), r.headers
    assert r.json()["tags"] == {"b": "2"}
    assert r.json()["properties"]["provisioningState"] == "Succeeded"
    g = call("GET", account_url("e2e-ac05"))
    assert g.json()["tags"] == {"b": "2"}
    assert g.json()["properties"]["provisioningState"] == "Succeeded"

    missing = call("PATCH", account_url("e2e-ac05-missing"), {"tags": {"b": "2"}})
    assert missing.status == 404
    assert missing.json()["error"]["code"] == "ResourceNotFound"


@pytest.fixture(scope="module")
def ac06_account(server):
    return create_account("e2e-ac06", tags={"keep": "1"})


def sub_snapshot():
    r = call("GET", sub_list_url())
    assert r.status == 200
    return sorted((a["id"], a["location"], tuple(sorted(a["tags"].items())),
                   a["properties"]["provisioningState"]) for a in r.json()["value"])


@pytest.mark.parametrize("name, query, body, status, code", [
    pytest.param("-abc", V, {"location": LOC}, 400, "InvalidResourceName", id="name-leading-hyphen"),
    pytest.param("a" * 129, V, {"location": LOC}, 400, "InvalidResourceName", id="name-129-chars"),
    pytest.param("a.b", V, {"location": LOC}, 400, "InvalidResourceName", id="name-with-dot"),
    pytest.param("e2e-ac06-nover", None, {"location": LOC}, 400, "MissingApiVersionParameter",
                 id="api-version-missing"),
    pytest.param("e2e-ac06-oldver", "api-version=2025-01-01", {"location": LOC}, 400,
                 "NoRegisteredProviderFound", id="api-version-unsupported"),
    pytest.param("e2e-ac06-noloc", V, {"tags": {"a": "1"}}, 400, "InvalidRequestContent",
                 id="body-without-location"),
    pytest.param("e2e-ac06-unknown", V, {"location": LOC, "unknownProp": 1}, 400,
                 "InvalidRequestContent", id="body-unknown-property"),
    pytest.param("e2e-ac06-identity", V, {"location": LOC, "identity": {"type": "SystemAssigned"}}, 400,
                 "InvalidRequestContent", id="body-identity"),
    pytest.param("e2e-ac06", V, {"location": "eastus", "tags": {"changed": "1"}}, 409,
                 "InvalidResourceLocation", id="existing-account-other-location"),
])
def test_ac06_rejected_put_creates_no_operation_and_changes_nothing(
        server, ac06_account, name, query, body, status, code):
    before = sub_snapshot()
    ops_before = db_operations(server.db_path)

    target = account_path(name) + (f"?{query}" if query else "")
    r = call("PUT", target, body)
    assert r.status == status, r.raw
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]
    assert no_tracking_headers(r), r.headers

    assert sub_snapshot() == before
    assert db_operations(server.db_path) == ops_before  # 보조 증거: 작업 기록이 늘지 않았다
    g = call("GET", account_url("e2e-ac06"))
    assert g.status == 200 and g.json() == ac06_account
    if name.startswith("e2e-ac06-"):  # 이름이 올바른 경우: 리소스가 생기지 않았다
        assert call("GET", account_url(name)).status == 404


def test_ac07_delete_returns_202_with_both_headers_then_resource_is_gone(server):
    create_account("e2e-ac07")
    r = call("DELETE", account_url("e2e-ac07"))
    assert r.status == 202
    assert r.raw == b""
    aao = r.headers.get("azure-asyncoperation")
    loc = r.headers.get("location")
    assert aao and loc, r.headers
    assert loc == location_url(aao)

    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["properties"]["action"] == "DELETE"

    lr = call("GET", loc)
    assert lr.status == 204
    assert lr.raw == b""
    g = call("GET", account_url("e2e-ac07"))
    assert g.status == 404
    assert g.json()["error"]["code"] == "ResourceNotFound"
    again = call("DELETE", account_url("e2e-ac07"))
    assert again.status == 204
    assert again.raw == b""


def test_ac13_request_and_correlation_ids(server):
    # 이 모듈에서 받은 모든 응답(준비 확인 GET 포함)에 x-ms-request-id가 있고, 요청마다 다르다
    responses = list(live_api.RESPONSES)
    assert len(responses) > 50
    missing = [(r.method, r.target, r.status) for r in responses if "x-ms-request-id" not in r.headers]
    assert not missing
    request_ids = [r.headers["x-ms-request-id"] for r in responses]
    assert len(set(request_ids)) == len(request_ids)
    for rid in request_ids:
        uuid.UUID(rid)

    # 보낸 상관 ID는 그대로 돌아온다 (성공·오류·본문 없는 응답 모두)
    create_account("e2e-ac13")
    cases = [
        ("GET", account_url("e2e-ac13"), None, 200),
        ("GET", account_url("e2e-ac13-missing"), None, 404),
        ("PUT", account_url("-bad"), {"location": LOC}, 400),
        ("PATCH", account_url("e2e-ac13"), {"tags": {"t": "1"}}, 200),
        ("DELETE", account_url("e2e-ac13-missing"), None, 204),
        ("GET", sub_list_url(), None, 200),
    ]
    for method, target, body, status in cases:
        cid = f"e2e-corr-{uuid.uuid4()}"
        r = call(method, target, body, headers={"x-ms-correlation-request-id": cid})
        assert r.status == status, (method, target, r.raw)
        assert r.headers.get("x-ms-correlation-request-id") == cid, (method, target, r.headers)
        assert "x-ms-request-id" in r.headers

    # 보내지 않으면 새 값을 만든다
    r1 = call("GET", account_url("e2e-ac13"))
    r2 = call("GET", account_url("e2e-ac13"))
    c1, c2 = r1.headers["x-ms-correlation-request-id"], r2.headers["x-ms-correlation-request-id"]
    uuid.UUID(c1)
    uuid.UUID(c2)
    assert c1 != c2

    # 보조 증거: 상관 ID가 작업 기록에 저장된다 (설계 §4.5)
    cid = f"e2e-corr-{uuid.uuid4()}"
    put = call("PUT", account_url("e2e-ac13"), {"location": LOC}, headers={"x-ms-correlation-request-id": cid})
    assert put.status == 200
    assert put.headers["x-ms-correlation-request-id"] == cid
    poll(put.headers["azure-asyncoperation"])
    op_id = put.headers["azure-asyncoperation"].split("/operationResults/")[1].split("?")[0]
    stored = {o["id"]: o["correlation_id"] for o in db_operations(server.db_path)}
    assert stored[op_id] == cid
