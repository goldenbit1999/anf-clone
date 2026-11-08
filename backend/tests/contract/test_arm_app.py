"""API 계약: ARM 경로, 응답 코드, 헤더, LRO 흐름 (계정 설계 §4, §7의 AC ID).

실제 HTTP 서버 대신 TestClient로 앱을 프로세스 안에서 띄운다. lifespan이 작업 워커를 돌린다.
실환경(WSL에서 uvicorn) 검증은 real-env-verifier가 같은 기준으로 따로 한다.
"""

import time

import pytest
from fastapi.testclient import TestClient

from anf_api.arm_app import create_app
from anf_api.state_store import Resource

V = "api-version=2026-08-01"
SUB = "11111111-2222-3333-4444-555555555555"
ACC_PATH = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
ACC = f"{ACC_PATH}?{V}"
OP_PREFIX = f"http://testserver/subscriptions/{SUB}/providers/Microsoft.NetApp/locations/westus2/operationResults/"


@pytest.fixture
def make_client(tmp_path):
    clients = []

    def make(fault_injection=""):
        client = TestClient(create_app(db_path=tmp_path / "anf.db", fault_injection=fault_injection))
        client.__enter__()
        clients.append(client)
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


def create(client, tags=None):
    body = {"location": "westus2"}
    if tags is not None:
        body["tags"] = tags
    r = client.put(ACC, json=body)
    assert r.status_code == 201, r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    return r


# --- AC-01 PUT 생성 ---

def test_ac01_put_new_account_is_201_creating_with_async_operation(client):
    r = client.put(ACC, json={"location": "westus2", "tags": {"a": "1"}})
    assert r.status_code == 201
    assert r.json()["properties"]["provisioningState"] == "Creating"
    assert "Location" not in r.headers
    url = r.headers["Azure-AsyncOperation"]
    assert url.startswith(OP_PREFIX) and url.endswith(f"?{V}")
    op = wait_terminal(client, url)
    assert op["status"] == "Succeeded"
    assert op["percentComplete"] == 100.0
    assert op["properties"] == {"resourceName": ACC_PATH, "action": "CREATE"}
    assert op["name"] == url[len(OP_PREFIX):].split("?")[0]
    g = client.get(ACC)
    assert g.status_code == 200
    assert g.json()["properties"]["provisioningState"] == "Succeeded"


# --- AC-02 PUT 갱신 ---

def test_ac02_put_existing_account_is_200_updating_then_succeeded(client):
    create(client, tags={"a": "1"})
    r = client.put(ACC, json={"location": "westus2", "tags": {"b": "2"}})
    assert r.status_code == 200
    assert r.json()["properties"]["provisioningState"] == "Updating"
    op = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (op["status"], op["properties"]["action"]) == ("Succeeded", "UPDATE")
    g = client.get(ACC).json()
    assert g["tags"] == {"b": "2"}
    assert g["properties"]["provisioningState"] == "Succeeded"


# --- AC-03 GET ---

def test_ac03_get_returns_account_body(client):
    create(client, tags={"k": "v"})
    assert client.get(ACC).json() == {
        "id": ACC_PATH,
        "name": "acc1",
        "type": "Microsoft.NetApp/netAppAccounts",
        "location": "westus2",
        "tags": {"k": "v"},
        "properties": {"provisioningState": "Succeeded",
                       "encryption": {"keySource": "Microsoft.NetApp"}},
    }


def test_ac03_get_missing_is_404_resource_not_found(client):
    r = client.get(ACC)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ResourceNotFound"


def test_ac03_get_ignores_name_case(client):
    create(client)
    r = client.get(ACC.replace("acc1", "ACC1"))
    assert r.status_code == 200
    assert r.json()["name"] == "acc1"


# --- AC-04 목록 ---

def test_ac04_lists_by_resource_group_and_subscription(client):
    create(client)
    rg1 = client.get(f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts?{V}")
    rg2 = client.get(f"/subscriptions/{SUB}/resourceGroups/rg2/providers/Microsoft.NetApp/netAppAccounts?{V}")
    sub = client.get(f"/subscriptions/{SUB}/providers/Microsoft.NetApp/netAppAccounts?{V}")
    assert [a["name"] for a in rg1.json()["value"]] == ["acc1"]
    assert rg2.json() == {"value": []}
    assert [a["id"] for a in sub.json()["value"]] == [ACC_PATH]


# --- AC-05 PATCH ---

def test_ac05_patch_tags_is_synchronous_200(client):
    create(client, tags={"a": "1"})
    r = client.patch(ACC, json={"tags": {"b": "2"}})
    assert r.status_code == 200
    assert "Azure-AsyncOperation" not in r.headers and "Location" not in r.headers
    assert r.json()["tags"] == {"b": "2"}
    assert r.json()["properties"]["provisioningState"] == "Succeeded"
    assert client.get(ACC).json()["tags"] == {"b": "2"}


def test_ac05_patch_missing_is_404(client):
    assert client.patch(ACC, json={"tags": {}}).status_code == 404


# --- AC-06 검증 ---

@pytest.mark.parametrize("name", ["-abc", "a" * 129, "a.b"])
def test_ac06_invalid_account_name_is_400(client, name):
    r = client.put(ACC.replace("acc1", name), json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "InvalidResourceName")


def test_ac06_missing_api_version_is_400(client):
    r = client.put(ACC_PATH, json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "MissingApiVersionParameter")


def test_ac06_unsupported_api_version_is_400(client):
    r = client.get(f"{ACC_PATH}?api-version=2026-08-15-preview")
    assert (r.status_code, r.json()["error"]["code"]) == (400, "NoRegisteredProviderFound")


@pytest.mark.parametrize("content", [
    b"{not json", b"", b'{"tags": {}}', b'{"location": "westus2", "foo": 1}',
    b'{"location": "westus2", "identity": {"type": "SystemAssigned"}}',
])
def test_ac06_invalid_body_is_400_and_creates_nothing(client, content):
    r = client.put(ACC, content=content, headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "InvalidRequestContent")
    assert client.get(ACC).status_code == 404


def test_ac06_put_with_different_location_is_409_and_keeps_account(client):
    create(client)
    r = client.put(ACC, json={"location": "eastus"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "InvalidResourceLocation")
    g = client.get(ACC).json()
    assert (g["location"], g["properties"]["provisioningState"]) == ("westus2", "Succeeded")


# --- AC-07 DELETE ---

def test_ac07_delete_is_202_then_gone_and_second_delete_is_204(client):
    create(client)
    r = client.delete(ACC)
    assert r.status_code == 202
    assert r.content == b""
    async_url = r.headers["Azure-AsyncOperation"]
    assert r.headers["Location"] == async_url + "&operationResultResponseType=Location"
    op = wait_terminal(client, async_url)
    assert (op["status"], op["properties"]["action"]) == ("Succeeded", "DELETE")
    loc = client.get(r.headers["Location"])
    assert (loc.status_code, loc.content) == (204, b"")
    assert client.get(ACC).status_code == 404
    again = client.delete(ACC)
    assert (again.status_code, again.content) == (204, b"")


def test_location_after_successful_update_returns_resource_body(client):
    create(client)
    r = client.put(ACC, json={"location": "westus2", "tags": {"x": "y"}})
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    loc = client.get(r.headers["Azure-AsyncOperation"] + "&operationResultResponseType=Location")
    assert loc.status_code == 200
    assert loc.json()["tags"] == {"x": "y"}


def test_delete_with_child_resource_is_409_cannot_delete_resource(client):
    create(client)
    with client.app.state.store.transaction() as tx:
        tx.put_resource(Resource(
            id=ACC_PATH + "/capacityPools/pool1", type="Microsoft.NetApp/netAppAccounts/capacityPools",
            subscription_id=SUB, resource_group="rg1", name="pool1", location="westus2",
            tags={}, properties={}, provisioning_state="Succeeded", parent_id=ACC_PATH,
        ))
    r = client.delete(ACC)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "CannotDeleteResource")
    assert client.get(ACC).json()["properties"]["provisioningState"] == "Succeeded"


# --- AC-08 진행 중 상태 (결함 주입: 지연) ---

def test_ac08_create_responds_before_delayed_operation_finishes(make_client):
    client = make_client('{"netAppAccounts/create": {"delaySeconds": 1.0}}')
    began = time.monotonic()
    r = client.put(ACC, json={"location": "westus2"})
    assert time.monotonic() - began < 0.5
    assert r.status_code == 201
    op = client.get(r.headers["Azure-AsyncOperation"])
    assert op.status_code == 200
    assert (op.json()["status"], op.json()["percentComplete"]) == ("Creating", 0.0)
    assert client.get(ACC).json()["properties"]["provisioningState"] == "Creating"
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


def test_ac08_location_is_202_while_delete_in_progress(make_client):
    client = make_client('{"netAppAccounts/delete": {"delaySeconds": 1.0}}')
    create(client)
    r = client.delete(ACC)
    loc = client.get(r.headers["Location"])
    assert (loc.status_code, loc.content) == (202, b"")
    assert loc.headers["Location"] == r.headers["Location"]
    assert "Retry-After" not in loc.headers
    assert client.get(ACC).json()["properties"]["provisioningState"] == "Deleting"
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert client.get(r.headers["Location"]).status_code == 204


# --- AC-09 실패 (결함 주입: 실패) ---

def test_ac09_failed_create_marks_account_failed_and_put_recovers(make_client):
    failing = make_client('{"netAppAccounts/create": {"fail": true}}')
    r = failing.put(ACC, json={"location": "westus2"})
    op = wait_terminal(failing, r.headers["Azure-AsyncOperation"])
    assert op["status"] == "Failed"
    assert op["error"]["code"] == "InternalServerError" and op["error"]["message"]
    loc = failing.get(r.headers["Azure-AsyncOperation"] + "&operationResultResponseType=Location")
    assert (loc.status_code, loc.json()["error"]["code"]) == (500, "InternalServerError")
    assert failing.get(ACC).json()["properties"]["provisioningState"] == "Failed"

    healthy = make_client()  # 같은 DB, 결함 주입 없음
    r2 = healthy.put(ACC, json={"location": "westus2"})
    assert (r2.status_code, r2.json()["properties"]["provisioningState"]) == (200, "Updating")
    assert wait_terminal(healthy, r2.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert healthy.get(ACC).json()["properties"]["provisioningState"] == "Succeeded"


def test_ac09_failed_delete_keeps_account_as_failed(make_client):
    client = make_client('{"netAppAccounts/delete": {"fail": true}}')
    create(client)
    r = client.delete(ACC)
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Failed"
    assert client.get(ACC).json()["properties"]["provisioningState"] == "Failed"


# --- AC-10 진행 중 충돌 ---

def test_ac10_changes_during_operation_are_409(make_client):
    client = make_client('{"netAppAccounts/create": {"delaySeconds": 1.0}}')
    r = client.put(ACC, json={"location": "westus2", "tags": {"a": "1"}})
    for resp in (client.put(ACC, json={"location": "westus2", "tags": {"b": "2"}}),
                 client.patch(ACC, json={"tags": {"c": "3"}}),
                 client.delete(ACC)):
        assert (resp.status_code, resp.json()["error"]["code"]) == (409, "AnotherOperationInProgress")
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(ACC).json()["tags"] == {"a": "1"}


# --- AC-11 재시작 복구 ---

def test_ac11_operation_left_in_progress_finishes_after_restart(tmp_path):
    db = tmp_path / "anf.db"
    with TestClient(create_app(db_path=db, fault_injection='{"netAppAccounts/create": {"delaySeconds": 30}}')) as first:
        r = first.put(ACC, json={"location": "westus2"})
        url = r.headers["Azure-AsyncOperation"]
    # 첫 프로세스는 작업을 끝내지 못하고 멈췄다. 새 프로세스가 이어서 끝낸다.
    with TestClient(create_app(db_path=db, fault_injection="")) as second:
        assert wait_terminal(second, url)["status"] == "Succeeded"
        assert second.get(ACC).json()["properties"]["provisioningState"] == "Succeeded"


# --- AC-13 상관 ID ---

def test_ac13_request_and_correlation_ids(client):
    r1 = client.get(ACC, headers={"x-ms-correlation-request-id": "corr-123"})
    assert r1.headers["x-ms-correlation-request-id"] == "corr-123"
    r2 = client.get(ACC)
    assert r2.headers["x-ms-correlation-request-id"]
    assert r1.headers["x-ms-request-id"] != r2.headers["x-ms-request-id"]


# --- 작업 상태 URL ---

def test_unknown_operation_is_404(client):
    r = client.get(f"{OP_PREFIX}00000000-0000-0000-0000-000000000000?{V}")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "ResourceNotFound")


def test_operation_from_other_subscription_or_location_is_404(client):
    url = create(client).headers["Azure-AsyncOperation"]
    assert client.get(url.replace(SUB, "99999999-2222-3333-4444-555555555555")).status_code == 404
    assert client.get(url.replace("/locations/westus2/", "/locations/eastus/")).status_code == 404


def test_operation_status_requires_api_version(client):
    url = create(client).headers["Azure-AsyncOperation"]
    r = client.get(url.split("?")[0])
    assert (r.status_code, r.json()["error"]["code"]) == (400, "MissingApiVersionParameter")


def test_invalid_fault_injection_prevents_startup(tmp_path):
    with pytest.raises(ValueError):
        create_app(db_path=tmp_path / "anf.db", fault_injection='{"netAppAccounts/patch": {}}')
