"""API 계약: 용량 풀의 ARM 경로, 응답 코드, 헤더, LRO 흐름 (풀 설계 §4, §8의 AC ID).

계정 계약 테스트(test_arm_app.py)처럼 TestClient로 앱을 프로세스 안에서 띄운다.
실환경(WSL에서 uvicorn) 검증은 real-env-verifier가 같은 기준으로 따로 한다.
"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from anf_api.arm_app import create_app
from anf_api.state_store import Resource

V = "api-version=2026-08-01"
SUB = "11111111-2222-3333-4444-555555555555"
TIB = 1 << 40
ACC_PATH = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
ACC = f"{ACC_PATH}?{V}"
POOL_PATH = f"{ACC_PATH}/capacityPools/pool1"
POOL = f"{POOL_PATH}?{V}"
POOLS = f"{ACC_PATH}/capacityPools?{V}"
OP_PREFIX = f"http://testserver/subscriptions/{SUB}/providers/Microsoft.NetApp/locations/westus2/operationResults/"


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def make(fault_injection="", account=True):
        client = TestClient(create_app(db_path=tmp_path / "anf.db", fault_injection=fault_injection))
        client.__enter__()
        clients.append(client)
        if account:
            r = client.put(ACC, json={"location": "westus2"})
            wait_terminal(client, r.headers["Azure-AsyncOperation"])
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def wait_terminal(client, url, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(url).json()
        if body["status"] in ("Succeeded", "Failed", "Canceled"):
            return body
        assert time.monotonic() < deadline, f"operation did not finish: {body}"
        time.sleep(0.05)


def pool_body(size_tib=4, level="Premium", tags=None, **props):
    b = {"location": "westus2", "properties": {"size": size_tib * TIB, "serviceLevel": level, **props}}
    if tags is not None:
        b["tags"] = tags
    return b


def create(client, url=POOL, **kw):
    r = client.put(url, json=pool_body(**kw))
    assert r.status_code == 201, r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    return r


def add_volume(client, quota_tib):
    """볼륨 사이클 전이라 볼륨 행을 저장소에 직접 넣는다 (풀 설계 결정 3, CV-1~CV-3)."""
    with client.app.state.store.transaction() as tx:
        tx.put_resource(Resource(
            id=f"{POOL_PATH}/volumes/v1", type="Microsoft.NetApp/netAppAccounts/capacityPools/volumes",
            subscription_id=SUB, resource_group="rg1", name="v1", location="westus2", tags={},
            properties={"usageThreshold": quota_tib * TIB}, provisioning_state="Succeeded",
            parent_id=POOL_PATH,
        ))


def error_code(r):
    return r.status_code, r.json()["error"]["code"]


# --- AC-01 PUT 생성 ---

def test_ac01_put_new_pool_is_201_creating_then_succeeded(client):
    r = client.put(POOL, json=pool_body())
    assert r.status_code == 201
    assert r.json()["properties"]["provisioningState"] == "Creating"
    assert "Location" not in r.headers  # 녹화를 따른다 (설계 결정 1)
    url = r.headers["Azure-AsyncOperation"]
    assert url.startswith(OP_PREFIX) and url.endswith(f"?{V}")
    op = wait_terminal(client, url)
    assert (op["status"], op["percentComplete"]) == ("Succeeded", 100.0)
    assert op["properties"] == {"resourceName": POOL_PATH, "action": "CREATE"}
    g = client.get(POOL).json()
    props = g["properties"]
    uuid.UUID(props.pop("poolId"))
    assert g["name"] == "acc1/pool1"
    assert g["type"] == "Microsoft.NetApp/netAppAccounts/capacityPools"
    assert props == {
        "provisioningState": "Succeeded", "serviceLevel": "Premium", "size": 4 * TIB,
        "qosType": "Auto", "totalThroughputMibps": 256.0, "utilizedThroughputMibps": 0.0,
        "encryptionType": "Single", "coolAccess": False,
    }


# --- AC-02 처리량 계산 ---

@pytest.mark.parametrize("level, size_tib, mibps", [("Standard", 2, 32.0), ("Ultra", 1, 128.0), ("Premium", 1, 64.0)])
def test_ac02_total_throughput_follows_service_level(client, level, size_tib, mibps):
    create(client, level=level, size_tib=size_tib)
    assert client.get(POOL).json()["properties"]["totalThroughputMibps"] == mibps


# --- AC-03 PUT 갱신 ---

def test_ac03_put_existing_pool_is_200_updating_then_succeeded(client):
    create(client, tags={"a": "1"})
    r = client.put(POOL, json=pool_body(size_tib=8, tags={"b": "2"}))
    assert r.status_code == 200
    assert r.json()["properties"]["provisioningState"] == "Updating"
    op = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (op["status"], op["properties"]["action"]) == ("Succeeded", "UPDATE")
    g = client.get(POOL).json()
    assert g["tags"] == {"b": "2"}
    assert (g["properties"]["size"], g["properties"]["totalThroughputMibps"]) == (8 * TIB, 512.0)


def test_ac03_put_without_size_and_service_level_keeps_them(client):
    create(client, level="Ultra", size_tib=2)
    r = client.put(POOL, json={"location": "westus2", "properties": {"qosType": "Manual"}})
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    props = client.get(POOL).json()["properties"]
    assert (props["serviceLevel"], props["size"], props["qosType"]) == ("Ultra", 2 * TIB, "Manual")


def test_ac03_service_level_changes_on_empty_pool(client):
    create(client, level="Premium")
    r = client.put(POOL, json=pool_body(level="Ultra"))
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    props = client.get(POOL).json()["properties"]
    assert (props["serviceLevel"], props["totalThroughputMibps"]) == ("Ultra", 512.0)


# --- AC-04 PATCH ---

def test_ac04_patch_is_202_patching_with_both_headers(client):
    create(client, tags={"a": "1"})
    r = client.patch(POOL, json={"tags": {"b": "2"}})
    assert r.status_code == 202
    assert r.json()["properties"]["provisioningState"] == "Patching"
    async_url = r.headers["Azure-AsyncOperation"]
    assert r.headers["Location"] == async_url + "&operationResultResponseType=Location"
    op = wait_terminal(client, async_url)
    assert (op["status"], op["properties"]["action"]) == ("Succeeded", "PATCH")
    assert client.get(POOL).json()["tags"] == {"b": "2"}
    loc = client.get(r.headers["Location"])
    assert (loc.status_code, loc.json()["tags"]) == (200, {"b": "2"})


def test_ac04_patch_size_and_qos_type(client):
    create(client)
    r = client.patch(POOL, json={"properties": {"size": 8 * TIB, "qosType": "Manual"}})
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    props = client.get(POOL).json()["properties"]
    assert (props["size"], props["qosType"]) == (8 * TIB, "Manual")


@pytest.mark.parametrize("method", ["patch", "put"])
def test_ac04_manual_to_auto_is_400_and_keeps_manual(client, method):
    create(client, qosType="Manual")
    if method == "patch":
        r = client.patch(POOL, json={"properties": {"qosType": "Auto"}})
    else:
        r = client.put(POOL, json=pool_body(qosType="Auto"))
    assert error_code(r) == (400, "BadRequest")
    g = client.get(POOL).json()["properties"]
    assert (g["qosType"], g["provisioningState"]) == ("Manual", "Succeeded")


def test_ac04_patch_missing_pool_is_404(client):
    assert error_code(client.patch(POOL, json={"tags": {}})) == (404, "ResourceNotFound")


# --- AC-05 조회 ---

def test_ac05_list_pools_in_account(client):
    create(client)
    r = client.put(ACC.replace("acc1", "acc2"), json={"location": "westus2"})
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert [p["name"] for p in client.get(POOLS).json()["value"]] == ["acc1/pool1"]
    assert client.get(POOLS.replace("acc1", "acc2")).json() == {"value": []}
    assert error_code(client.get(POOLS.replace("acc1", "nope"))) == (404, "ResourceNotFound")


def test_ac05_get_missing_pool_is_404_and_get_ignores_case(client):
    assert error_code(client.get(POOL)) == (404, "ResourceNotFound")
    create(client)
    r = client.get(POOL.replace("pool1", "POOL1").replace("acc1", "ACC1"))
    assert (r.status_code, r.json()["id"]) == (200, POOL_PATH)


# --- AC-06 거절 ---

@pytest.mark.parametrize("name", ["-p", "p" * 65, "a.b"])
def test_ac06_invalid_pool_name_is_400(client, name):
    r = client.put(POOL.replace("pool1", name), json=pool_body())
    assert error_code(r) == (400, "InvalidResourceName")


@pytest.mark.parametrize("body", [
    {"location": "westus2", "properties": {"size": TIB // 2, "serviceLevel": "Premium"}},
    {"location": "westus2", "properties": {"size": 0, "serviceLevel": "Premium"}},
    {"location": "westus2", "properties": {"size": 2049 * TIB, "serviceLevel": "Premium"}},
    {"location": "westus2", "properties": {"serviceLevel": "Premium"}},
    {"location": "westus2", "properties": {"size": 4 * TIB}},
    pool_body(level="Gold"),
    pool_body(level="Flexible"),
    pool_body(coolAccess=True),
    pool_body(encryptionType="Double"),
    pool_body(customThroughputMibps=128),
    pool_body(foo=1),
])
def test_ac06_invalid_body_is_400_and_creates_nothing(client, body):
    assert error_code(client.put(POOL, json=body)) == (400, "InvalidRequestContent")
    assert client.get(POOL).status_code == 404


def test_ac06_patch_service_level_is_400(client):
    create(client)
    r = client.patch(POOL, json={"properties": {"serviceLevel": "Ultra"}})
    assert error_code(r) == (400, "InvalidRequestContent")


def test_ac06_put_with_different_location_is_409(client):
    create(client)
    r = client.put(POOL, json={**pool_body(), "location": "eastus"})
    assert error_code(r) == (409, "InvalidResourceLocation")


# --- AC-07 부모 규칙 ---

def test_ac07_create_under_missing_account_is_404_parent_resource_not_found(make_client):
    client = make_client(account=False)
    assert error_code(client.put(POOL, json=pool_body())) == (404, "ParentResourceNotFound")
    assert client.get(POOL).status_code == 404


def test_ac07_create_under_deleting_account_is_409_conflict(make_client):
    client = make_client('{"netAppAccounts/delete": {"delaySeconds": 1.0}}')
    d = client.delete(ACC)
    assert d.status_code == 202
    assert error_code(client.put(POOL, json=pool_body())) == (409, "Conflict")
    assert wait_terminal(client, d.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(POOL).status_code == 404


# --- AC-08 DELETE ---

def test_ac08_delete_is_202_then_gone_and_second_delete_is_204(client):
    create(client)
    r = client.delete(POOL)
    assert (r.status_code, r.content) == (202, b"")
    async_url = r.headers["Azure-AsyncOperation"]
    assert r.headers["Location"] == async_url + "&operationResultResponseType=Location"
    op = wait_terminal(client, async_url)
    assert (op["status"], op["properties"]["action"]) == ("Succeeded", "DELETE")
    assert client.get(r.headers["Location"]).status_code == 204
    assert client.get(POOL).status_code == 404
    assert client.delete(POOL).status_code == 204


# --- AC-09 계정 사이클에서 넘어온 기준 ---

def test_ac09_account_with_pool_cannot_be_deleted_until_pool_is_gone(client):
    create(client)
    r = client.delete(ACC)
    assert error_code(r) == (409, "CannotDeleteResource")
    assert "'Microsoft.NetApp/netAppAccounts/acc1/capacityPools/pool1'" in r.json()["error"]["message"]
    assert client.get(POOL).json()["properties"]["provisioningState"] == "Succeeded"
    assert client.get(ACC).json()["properties"]["provisioningState"] == "Succeeded"
    wait_terminal(client, client.delete(POOL).headers["Azure-AsyncOperation"])
    d = client.delete(ACC)
    assert d.status_code == 202
    assert wait_terminal(client, d.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


# --- CV-1~CV-3 (볼륨 사이클로 옮긴 기준. 여기서는 볼륨 행을 직접 넣어 로직만 확인한다) ---

def test_cv1_pool_with_volume_cannot_be_deleted(client):
    create(client)
    add_volume(client, 1)
    r = client.delete(POOL)
    assert error_code(r) == (409, "CannotDeleteResource")
    assert "capacityPools/pool1/volumes/v1'" in r.json()["error"]["message"]


@pytest.mark.parametrize("method", ["patch", "put"])
def test_cv2_shrinking_below_volume_quota_sum_is_400(client, method):
    create(client, size_tib=4)
    add_volume(client, 3)
    if method == "patch":
        r = client.patch(POOL, json={"properties": {"size": 2 * TIB}})
    else:
        r = client.put(POOL, json=pool_body(size_tib=2))
    assert error_code(r) == (400, "BadRequest")
    assert client.get(POOL).json()["properties"]["size"] == 4 * TIB


def test_cv3_service_level_change_with_volume_is_400(client):
    create(client)
    add_volume(client, 1)
    r = client.put(POOL, json=pool_body(level="Ultra"))
    assert error_code(r) == (400, "BadRequest")
    assert r.json()["error"]["message"] == "ServiceLevel cannot be changed."


# --- AC-10 진행 중·실패 (결함 주입) ---

def test_ac10_in_progress_states_for_create_patch_and_delete(make_client):
    client = make_client('{"capacityPools/create": {"delaySeconds": 1.0}, '
                         '"capacityPools/patch": {"delaySeconds": 1.0}, '
                         '"capacityPools/delete": {"delaySeconds": 1.0}}')
    r = client.put(POOL, json=pool_body())
    assert client.get(r.headers["Azure-AsyncOperation"]).json()["status"] == "Creating"
    assert client.get(POOL).json()["properties"]["provisioningState"] == "Creating"
    wait_terminal(client, r.headers["Azure-AsyncOperation"])

    p = client.patch(POOL, json={"tags": {"x": "y"}})
    op = client.get(p.headers["Azure-AsyncOperation"]).json()
    assert (op["status"], op["percentComplete"]) == ("Patching", 0.0)
    assert client.get(p.headers["Location"]).status_code == 202
    assert client.get(POOL).json()["properties"]["provisioningState"] == "Patching"
    wait_terminal(client, p.headers["Azure-AsyncOperation"])

    d = client.delete(POOL)
    assert client.get(d.headers["Azure-AsyncOperation"]).json()["status"] == "Deleting"
    assert client.get(POOL).json()["properties"]["provisioningState"] == "Deleting"
    assert wait_terminal(client, d.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


def test_ac10_failed_create_then_put_recovers(make_client):
    failing = make_client('{"capacityPools/create": {"fail": true}}')
    r = failing.put(POOL, json=pool_body())
    op = wait_terminal(failing, r.headers["Azure-AsyncOperation"])
    assert op["status"] == "Failed" and op["error"]["code"]
    assert failing.get(POOL).json()["properties"]["provisioningState"] == "Failed"

    healthy = make_client(account=False)  # 같은 DB, 결함 주입 없음
    r2 = healthy.put(POOL, json=pool_body())
    assert r2.status_code == 200
    assert wait_terminal(healthy, r2.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert healthy.get(POOL).json()["properties"]["provisioningState"] == "Succeeded"


def test_ac10_failed_patch_restores_previous_values(make_client):
    client = make_client('{"capacityPools/patch": {"fail": true}}')
    create(client, tags={"a": "1"})
    r = client.patch(POOL, json={"tags": {"b": "2"}, "properties": {"size": 8 * TIB}})
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Failed"
    g = client.get(POOL).json()
    assert (g["tags"], g["properties"]["size"]) == ({"a": "1"}, 4 * TIB)
    assert g["properties"]["provisioningState"] == "Failed"


# --- AC-11 진행 중 충돌 ---

def test_ac11_changes_during_pool_operation_are_409(make_client):
    client = make_client('{"capacityPools/create": {"delaySeconds": 1.0}}')
    r = client.put(POOL, json=pool_body(tags={"a": "1"}))
    for resp in (client.put(POOL, json=pool_body(tags={"b": "2"})),
                 client.patch(POOL, json={"tags": {"c": "3"}}),
                 client.delete(POOL)):
        assert error_code(resp) == (409, "AnotherOperationInProgress")
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(POOL).json()["tags"] == {"a": "1"}


# --- AC-12 재시작 복구 ---

def test_ac12_pool_operation_left_in_progress_finishes_after_restart(tmp_path):
    db = tmp_path / "anf.db"
    faults = '{"capacityPools/create": {"delaySeconds": 30}}'
    with TestClient(create_app(db_path=db, fault_injection=faults)) as first:
        r = first.put(ACC, json={"location": "westus2"})
        wait_terminal(first, r.headers["Azure-AsyncOperation"])
        url = first.put(POOL, json=pool_body()).headers["Azure-AsyncOperation"]
    with TestClient(create_app(db_path=db, fault_injection="")) as second:
        assert wait_terminal(second, url)["status"] == "Succeeded"
        assert second.get(POOL).json()["properties"]["provisioningState"] == "Succeeded"
