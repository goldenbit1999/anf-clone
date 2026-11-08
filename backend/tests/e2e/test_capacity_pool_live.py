"""capacity-pool 실환경 검증: 계약과 상태 전이 (풀 설계 §8 AC-01~AC-09).

WSL에서 anf-api를 uvicorn 프로세스로 띄우고 HTTP로 확인한다. 결함 주입 없는 서버 하나를 이 모듈 전체가 쓴다.
AC-07의 "계정이 Deleting인 동안" 부분은 지연 주입이 필요해서 test_capacity_pool_lro_faults_live.py에 있다.
AC-13(데이터 플레인 불변)은 root 권한의 exportfs가 필요해서, 이 모듈 실행 전후에 셸에서 비교한다.

실행 (WSL, 저장소 루트):
    ANF_E2E_API_URL=http://127.0.0.1:8080 ~/.venvs/anf-clone/bin/python -m pytest \
        backend/tests/e2e/test_capacity_pool_live.py -m e2e -v
"""

import re

import pytest

import live_api
from live_api import (
    BASE_URL, LOC, POOL_TYPE, SUB, TIB, UUID_RE, V,
    account_path, account_url, call, create_account, create_pool, db_operations, db_resources,
    location_url, poll, pool_list_url, pool_path, pool_url,
)

pytestmark = [pytest.mark.e2e, live_api.SKIP_UNLESS_LIVE]

ACCT = "e2e-pool-acct"
OTHER_ACCT = "e2e-pool-acct2"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    live_api.RESPONSES.clear()
    srv = live_api.Server(tmp_path_factory.mktemp("pool-live") / "anf.db")
    srv.start()
    create_account(ACCT)
    create_account(OTHER_ACCT)
    yield srv
    srv.stop()


def no_tracking_headers(r) -> bool:
    return "azure-asyncoperation" not in r.headers and "location" not in r.headers


def ops_for(db, rid):
    return [o for o in db_operations(db) if o["resource_id"].lower() == rid.lower()]


def op_url_re() -> str:
    return (re.escape(f"{BASE_URL}/subscriptions/{SUB}/providers/Microsoft.NetApp/locations/{LOC}"
                      "/operationResults/") + f"({UUID_RE})" + re.escape(f"?{V}"))


def test_ac01_create_returns_201_creating_then_succeeded_with_pool_fields(server):
    name = "e2e-p01"
    body = {"location": LOC, "properties": {"size": 4398046511104, "serviceLevel": "Premium"}}
    r = call("PUT", pool_url(ACCT, name), body)
    assert r.status == 201, r.raw
    assert r.json()["properties"]["provisioningState"] == "Creating"
    aao = r.headers.get("azure-asyncoperation")
    assert aao, r.headers
    assert "location" not in r.headers  # Azure-AsyncOperation만 (녹화 N1, 설계 결정 1)
    assert "retry-after" not in r.headers
    m = re.fullmatch(op_url_re(), aao)
    assert m, aao
    op_id = m.group(1)

    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["percentComplete"] == 100.0
    assert final["properties"] == {"resourceName": pool_path(ACCT, name), "action": "CREATE"}
    assert final["name"] == op_id

    g = call("GET", pool_url(ACCT, name))
    assert g.status == 200
    p = g.json()
    assert p["id"] == pool_path(ACCT, name)
    assert p["name"] == f"{ACCT}/{name}"
    assert p["type"] == POOL_TYPE
    assert p["location"] == LOC
    assert p["tags"] == {}
    props = p["properties"]
    assert props["provisioningState"] == "Succeeded"
    assert re.fullmatch(UUID_RE, props["poolId"]), props["poolId"]
    assert props["size"] == 4398046511104
    assert props["serviceLevel"] == "Premium"
    assert props["qosType"] == "Auto"
    assert props["encryptionType"] == "Single"
    assert props["coolAccess"] is False
    assert props["totalThroughputMibps"] == 256.0
    assert props["utilizedThroughputMibps"] == 0.0
    # 설계 §4.2: 201 본문도 GET과 같은 필드를 준다 (poolId는 생성 때 정해져 바뀌지 않는다)
    created = r.json()
    assert set(created["properties"]) == set(props)
    assert created["properties"]["poolId"] == props["poolId"]


@pytest.mark.parametrize("level, tib, expected", [
    ("Standard", 2, 32.0), ("Ultra", 1, 128.0), ("Premium", 1, 64.0),
])
def test_ac02_total_throughput_is_size_tib_times_level_rate(server, level, tib, expected):
    name = f"e2e-p02-{level.lower()}-{tib}t"
    p = create_pool(ACCT, name, size=tib * TIB, service_level=level)
    assert p["properties"]["serviceLevel"] == level
    assert p["properties"]["size"] == tib * TIB
    assert p["properties"]["totalThroughputMibps"] == expected
    assert p["properties"]["utilizedThroughputMibps"] == 0.0


def test_ac03_put_update_returns_200_updating_and_keeps_missing_properties(server):
    name = "e2e-p03"
    created = create_pool(ACCT, name, tags={"old": "1", "keep": "no"})

    # tags 교체 + size 8 TiB
    r = call("PUT", pool_url(ACCT, name),
             {"location": LOC, "tags": {"new": "2"}, "properties": {"size": 8 * TIB}})
    assert r.status == 200, r.raw
    assert r.json()["properties"]["provisioningState"] == "Updating"
    aao = r.headers.get("azure-asyncoperation")
    assert aao and re.fullmatch(op_url_re(), aao), r.headers
    assert "location" not in r.headers
    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["properties"]["action"] == "UPDATE"
    g = call("GET", pool_url(ACCT, name)).json()
    assert g["tags"] == {"new": "2"}
    assert g["properties"]["size"] == 8 * TIB
    assert g["properties"]["totalThroughputMibps"] == 512.0
    assert g["properties"]["provisioningState"] == "Succeeded"
    assert g["properties"]["poolId"] == created["properties"]["poolId"]

    # size·serviceLevel을 뺀 PUT은 두 값을 유지한다 (설계 결정 8)
    r2 = call("PUT", pool_url(ACCT, name), {"location": LOC, "tags": {"t": "3"}})
    assert r2.status == 200, r2.raw
    assert poll(r2.headers["azure-asyncoperation"])[0]["status"] == "Succeeded"
    g2 = call("GET", pool_url(ACCT, name)).json()
    assert g2["tags"] == {"t": "3"}
    assert g2["properties"]["size"] == 8 * TIB
    assert g2["properties"]["serviceLevel"] == "Premium"
    assert g2["properties"]["totalThroughputMibps"] == 512.0

    # 볼륨이 없는 풀의 serviceLevel 변경: Premium → Ultra (설계 결정 5)
    r3 = call("PUT", pool_url(ACCT, name),
              {"location": LOC, "tags": {"t": "3"}, "properties": {"serviceLevel": "Ultra"}})
    assert r3.status == 200, r3.raw
    final3, _ = poll(r3.headers["azure-asyncoperation"])
    assert final3["status"] == "Succeeded", final3
    g3 = call("GET", pool_url(ACCT, name)).json()
    assert g3["properties"]["serviceLevel"] == "Ultra"
    assert g3["properties"]["size"] == 8 * TIB
    assert g3["properties"]["totalThroughputMibps"] == 1024.0
    assert g3["properties"]["provisioningState"] == "Succeeded"


def test_ac04_patch_is_async_202_patching_and_manual_to_auto_is_rejected(server):
    name = "e2e-p04"
    rid = pool_path(ACCT, name)
    create_pool(ACCT, name, tags={"a": "1"})

    # tags만 바꾼 PATCH도 202 + Patching + 두 헤더 (녹화 N2, P1)
    r = call("PATCH", pool_url(ACCT, name), {"tags": {"b": "2"}})
    assert r.status == 202, r.raw
    assert r.json()["properties"]["provisioningState"] == "Patching"
    aao, loc = r.headers.get("azure-asyncoperation"), r.headers.get("location")
    assert aao and loc, r.headers
    assert re.fullmatch(op_url_re(), aao), aao
    assert loc == location_url(aao)
    assert "operationResultResponseType=Location" in loc
    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["properties"]["action"] == "PATCH"
    g = call("GET", pool_url(ACCT, name))
    assert g.json()["tags"] == {"b": "2"}
    assert g.json()["properties"]["provisioningState"] == "Succeeded"
    # 설계 §4.1: Location 방식으로 끝난 PATCH를 조회하면 200과 풀 본문
    lr = call("GET", loc)
    assert lr.status == 200
    assert lr.json() == g.json()

    # size PATCH (tags 없음: tags 유지)
    r2 = call("PATCH", pool_url(ACCT, name), {"properties": {"size": 8 * TIB}})
    assert r2.status == 202, r2.raw
    assert poll(r2.headers["azure-asyncoperation"])[0]["status"] == "Succeeded"
    g2 = call("GET", pool_url(ACCT, name)).json()
    assert g2["properties"]["size"] == 8 * TIB
    assert g2["properties"]["totalThroughputMibps"] == 512.0
    assert g2["tags"] == {"b": "2"}

    # qosType Manual PATCH
    r3 = call("PATCH", pool_url(ACCT, name), {"properties": {"qosType": "Manual"}})
    assert r3.status == 202, r3.raw
    assert poll(r3.headers["azure-asyncoperation"])[0]["status"] == "Succeeded"
    g3 = call("GET", pool_url(ACCT, name)).json()
    assert g3["properties"]["qosType"] == "Manual"

    # Manual → Auto는 PATCH·PUT 모두 400 BadRequest, 작업 없음, Manual 유지
    ops_before = ops_for(server.db_path, rid)
    for method, body in (("PATCH", {"properties": {"qosType": "Auto"}}),
                         ("PUT", {"location": LOC, "tags": {"b": "2"}, "properties": {"qosType": "Auto"}})):
        rej = call(method, pool_url(ACCT, name), body)
        assert rej.status == 400, (method, rej.raw)
        assert rej.json()["error"]["code"] == "BadRequest", method
        assert "Manual to Auto" in rej.json()["error"]["message"], method
        assert no_tracking_headers(rej), rej.headers
        after = call("GET", pool_url(ACCT, name)).json()
        assert after == g3, method
        assert ops_for(server.db_path, rid) == ops_before, method


def test_ac05_list_in_account_other_account_missing_and_case_insensitive(server):
    name = "E2e-P05-Mixed"
    body = create_pool(ACCT, name)
    create_pool(OTHER_ACCT, "e2e-p05-other")

    def names(account):
        r = call("GET", pool_list_url(account))
        assert r.status == 200, r.raw
        assert set(r.json()) == {"value"}
        return {p["name"] for p in r.json()["value"]}

    in_acct, in_other = names(ACCT), names(OTHER_ACCT)
    assert f"{ACCT}/{name}" in in_acct
    assert f"{OTHER_ACCT}/e2e-p05-other" not in in_acct
    assert f"{OTHER_ACCT}/e2e-p05-other" in in_other
    assert f"{ACCT}/{name}" not in in_other

    missing_list = call("GET", pool_list_url("e2e-pool-no-such-acct"))
    assert missing_list.status == 404
    assert missing_list.json()["error"]["code"] == "ResourceNotFound"

    missing = call("GET", pool_url(ACCT, "e2e-p05-missing"))
    assert missing.status == 404
    assert missing.json()["error"]["code"] == "ResourceNotFound"
    assert missing.json()["error"]["message"]

    for variant in ("E2E-P05-MIXED", "e2e-p05-mixed"):
        g = call("GET", pool_url(ACCT, variant))
        assert g.status == 200, variant
        assert g.json() == body, variant  # 이름은 처음 받은 그대로
    # 추가 확인: 계정 이름의 대소문자만 바꿔도 같은 풀
    g = call("GET", pool_url(ACCT.upper(), name))
    assert g.status == 200 and g.json() == body


@pytest.fixture(scope="module")
def ac06_pool(server):
    return create_pool(ACCT, "e2e-p06", tags={"keep": "1"})


def pools_snapshot(account):
    r = call("GET", pool_list_url(account))
    assert r.status == 200
    return sorted((p["id"], p["location"], tuple(sorted(p["tags"].items())),
                   tuple(sorted(p["properties"].items()))) for p in r.json()["value"])


def _props(**kw):
    return {"location": LOC, "properties": {"size": 4 * TIB, "serviceLevel": "Premium", **kw}}


_CLONE = "is not supported by this ANF clone."
UNSUPPORTED_MESSAGES = {
    "serviceLevel-Flexible": f"The value 'Flexible' of 'properties.serviceLevel' {_CLONE}",
    "serviceLevel-StandardZRS": f"The value 'StandardZRS' of 'properties.serviceLevel' {_CLONE}",
    "encryptionType-Double": f"The value 'Double' of 'properties.encryptionType' {_CLONE}",
    "coolAccess-true": f"The property 'properties.coolAccess' {_CLONE}",
    "customThroughputMibps": f"The property 'properties.customThroughputMibps' {_CLONE}",
}


@pytest.mark.parametrize("method, name, body, status, code", [
    pytest.param("PUT", "-p", _props(), 400, "InvalidResourceName", id="name-leading-hyphen"),
    pytest.param("PUT", "a" * 65, _props(), 400, "InvalidResourceName", id="name-65-chars"),
    pytest.param("PUT", "a.b", _props(), 400, "InvalidResourceName", id="name-with-dot"),
    pytest.param("PUT", "e2e-p06-half", _props(size=549755813888), 400, "InvalidRequestContent",
                 id="size-512GiB-not-1TiB-multiple"),
    pytest.param("PUT", "e2e-p06-zero", _props(size=0), 400, "InvalidRequestContent", id="size-0"),
    pytest.param("PUT", "e2e-p06-big", _props(size=2049 * TIB), 400, "InvalidRequestContent",
                 id="size-2049TiB"),
    pytest.param("PUT", "e2e-p06-nosize", {"location": LOC, "properties": {"serviceLevel": "Premium"}},
                 400, "InvalidRequestContent", id="create-without-size"),
    pytest.param("PUT", "e2e-p06-nolevel", {"location": LOC, "properties": {"size": 4 * TIB}},
                 400, "InvalidRequestContent", id="create-without-serviceLevel"),
    pytest.param("PUT", "e2e-p06-gold", _props(serviceLevel="Gold"), 400, "InvalidRequestContent",
                 id="serviceLevel-Gold"),
    pytest.param("PUT", "e2e-p06-flex", _props(serviceLevel="Flexible"), 400, "InvalidRequestContent",
                 id="serviceLevel-Flexible"),
    pytest.param("PUT", "e2e-p06-zrs", _props(serviceLevel="StandardZRS"), 400, "InvalidRequestContent",
                 id="serviceLevel-StandardZRS"),
    pytest.param("PUT", "e2e-p06-cool", _props(coolAccess=True), 400, "InvalidRequestContent",
                 id="coolAccess-true"),
    pytest.param("PUT", "e2e-p06-dbl", _props(encryptionType="Double"), 400, "InvalidRequestContent",
                 id="encryptionType-Double"),
    pytest.param("PUT", "e2e-p06-ctp", _props(customThroughputMibps=100), 400, "InvalidRequestContent",
                 id="customThroughputMibps"),
    pytest.param("PUT", "e2e-p06-unk", {**_props(), "unknownProp": 1}, 400, "InvalidRequestContent",
                 id="unknown-top-level-property"),
    pytest.param("PUT", "e2e-p06-unkp", _props(unknownProp=1), 400, "InvalidRequestContent",
                 id="unknown-properties-property"),
    pytest.param("PATCH", "e2e-p06", {"properties": {"serviceLevel": "Ultra"}}, 400, "InvalidRequestContent",
                 id="patch-serviceLevel"),
    pytest.param("PUT", "e2e-p06", {"location": "eastus", "tags": {"changed": "1"}}, 409,
                 "InvalidResourceLocation", id="existing-pool-other-location"),
])
def test_ac06_rejected_requests_create_no_operation_and_change_nothing(
        server, ac06_pool, method, name, body, status, code, request):
    before, other_before = pools_snapshot(ACCT), pools_snapshot(OTHER_ACCT)
    ops_before, res_before = db_operations(server.db_path), db_resources(server.db_path)

    r = call(method, pool_url(ACCT, name), body)
    assert r.status == status, r.raw
    assert r.json()["error"]["code"] == code
    assert r.json()["error"]["message"]
    assert no_tracking_headers(r), r.headers
    expected = UNSUPPORTED_MESSAGES.get(request.node.callspec.id)
    if expected is not None:  # 미룬 기능: 메시지 전체를 비교한다 (풀 설계 "구현 중 변경")
        assert r.json()["error"]["message"] == expected

    assert pools_snapshot(ACCT) == before
    assert pools_snapshot(OTHER_ACCT) == other_before
    assert db_operations(server.db_path) == ops_before  # 보조 증거: 작업 기록이 늘지 않았다
    assert db_resources(server.db_path) == res_before   # 보조 증거: 리소스 행이 그대로다
    g = call("GET", pool_url(ACCT, "e2e-p06"))
    assert g.status == 200 and g.json() == ac06_pool
    if name.startswith("e2e-p06-"):  # 이름이 올바른 새 풀: 생기지 않았다
        assert call("GET", pool_url(ACCT, name)).status == 404


def test_ac07_parent_account_missing_returns_404_parent_resource_not_found(server):
    missing_acct = "e2e-pool-no-such-acct7"
    ops_before, res_before = db_operations(server.db_path), db_resources(server.db_path)
    r = call("PUT", pool_url(missing_acct, "e2e-p07"),
             {"location": LOC, "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}})
    assert r.status == 404, r.raw
    assert r.json()["error"]["code"] == "ParentResourceNotFound"
    assert account_path(missing_acct) in r.json()["error"]["message"]
    assert no_tracking_headers(r), r.headers
    assert db_operations(server.db_path) == ops_before
    assert db_resources(server.db_path) == res_before
    assert call("GET", pool_url(missing_acct, "e2e-p07")).status == 404
    assert call("GET", account_url(missing_acct)).status == 404


def test_ac08_delete_returns_202_both_headers_then_pool_is_gone(server):
    name = "e2e-p08"
    create_pool(ACCT, name)
    r = call("DELETE", pool_url(ACCT, name))
    assert r.status == 202, r.raw
    assert r.raw == b""
    aao, loc = r.headers.get("azure-asyncoperation"), r.headers.get("location")
    assert aao and loc, r.headers
    assert re.fullmatch(op_url_re(), aao), aao
    assert loc == location_url(aao)

    final, seen = poll(aao)
    assert final["status"] == "Succeeded", (final, seen)
    assert final["properties"] == {"resourceName": pool_path(ACCT, name), "action": "DELETE"}
    lr = call("GET", loc)
    assert lr.status == 204
    assert lr.raw == b""
    g = call("GET", pool_url(ACCT, name))
    assert g.status == 404
    assert g.json()["error"]["code"] == "ResourceNotFound"
    again = call("DELETE", pool_url(ACCT, name))
    assert again.status == 204
    assert again.raw == b""


def test_ac09_account_with_pool_cannot_be_deleted_until_pool_is_gone(server):
    acct, name = "e2e-pool-acct9", "e2e-p09"
    create_account(acct)
    create_pool(acct, name)
    acct_ops_before = ops_for(server.db_path, account_path(acct))

    r = call("DELETE", account_url(acct))
    assert r.status == 409, r.raw
    assert r.json()["error"]["code"] == "CannotDeleteResource"
    assert f"Microsoft.NetApp/netAppAccounts/{acct}/capacityPools/{name}" in r.json()["error"]["message"]
    assert no_tracking_headers(r), r.headers
    assert ops_for(server.db_path, account_path(acct)) == acct_ops_before
    assert call("GET", account_url(acct)).json()["properties"]["provisioningState"] == "Succeeded"
    assert call("GET", pool_url(acct, name)).json()["properties"]["provisioningState"] == "Succeeded"

    dp = call("DELETE", pool_url(acct, name))
    assert dp.status == 202
    assert poll(dp.headers["azure-asyncoperation"])[0]["status"] == "Succeeded"
    da = call("DELETE", account_url(acct))
    assert da.status == 202, da.raw
    final, seen = poll(da.headers["azure-asyncoperation"])
    assert final["status"] == "Succeeded", (final, seen)
    assert final["properties"]["action"] == "DELETE"
    assert call("GET", account_url(acct)).status == 404


def test_extra_patch_other_location_and_missing_pool(server):
    """수락 기준 밖 (설계 §4.1, §4.3): PATCH의 다른 location은 409, 없는 풀 PATCH는 404."""
    name = "e2e-px-patch"
    before = create_pool(ACCT, name)
    r = call("PATCH", pool_url(ACCT, name), {"location": "eastus", "tags": {"x": "1"}})
    assert r.status == 409, r.raw
    assert r.json()["error"]["code"] == "InvalidResourceLocation"
    assert call("GET", pool_url(ACCT, name)).json() == before
    missing = call("PATCH", pool_url(ACCT, "e2e-px-missing"), {"tags": {"x": "1"}})
    assert missing.status == 404
    assert missing.json()["error"]["code"] == "ResourceNotFound"


def test_extra_every_response_has_request_id(server):
    responses = list(live_api.RESPONSES)
    assert len(responses) > 50
    missing = [(r.method, r.target, r.status) for r in responses if "x-ms-request-id" not in r.headers]
    assert not missing
    ids = [r.headers["x-ms-request-id"] for r in responses]
    assert len(set(ids)) == len(ids)
