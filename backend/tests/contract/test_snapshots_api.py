"""API 계약: 스냅샷의 ARM 경로, 응답 코드, 헤더, LRO 흐름, agent 호출 (스냅샷 설계 §4, §8의 AC ID).

storage agent는 가짜 클라이언트다. 실제 agent와 데이터 효과는 real-env-verifier가 같은 기준으로 확인한다.
"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from anf_api.arm_app import create_app

V = "api-version=2026-08-01"
SUB = "11111111-2222-3333-4444-555555555555"
GIB = 1 << 30
TIB = 1 << 40
ACC_PATH = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
POOL_PATH = f"{ACC_PATH}/capacityPools/pool1"
VOL_PATH = f"{POOL_PATH}/volumes/vol1"
VOL = f"{VOL_PATH}?{V}"
SNAP_PATH = f"{VOL_PATH}/snapshots/snap1"
SNAP = f"{SNAP_PATH}?{V}"
SNAPS = f"{VOL_PATH}/snapshots?{V}"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/anf"
CREATED = "2026-11-08T23:07:12Z"
NOT_FOUND = ("The requested snapshot 'snap1' was not found on the volume 'acc1/pool1/vol1'. Please check the "
             "requested snapshot. Please note: The snapshot may no longer be available based on configured "
             "snapshot policies.")


class FakeStorage:
    def __init__(self):
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def ensure_volume(self, *args, correlation_id=None, clone=None, qos=None):
        self.calls.append(("ensure_volume", *args))
        return "172.30.0.129"

    async def delete_volume(self, uuid, correlation_id=None):
        self.calls.append(("delete_volume", uuid))

    async def ensure_snapshot(self, *args, correlation_id=None):
        self.calls.append(("ensure_snapshot", *args, correlation_id))
        if self.error:
            raise self.error
        return CREATED

    async def delete_snapshot(self, *args, correlation_id=None):
        self.calls.append(("delete_snapshot", *args, correlation_id))


@pytest.fixture
def storage():
    return FakeStorage()


def wait_terminal(client, url, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(url).json()
        if body["status"] in ("Succeeded", "Failed", "Canceled"):
            return body
        assert time.monotonic() < deadline, f"operation did not finish: {body}"
        time.sleep(0.05)


def vol_body():
    return {"location": "westus2",
            "properties": {"creationToken": "vol1", "usageThreshold": 100 * GIB, "subnetId": SUBNET}}


@pytest.fixture
def make_client(tmp_path, storage):
    clients = []

    def make(fault_injection="", volume=True):
        client = TestClient(create_app(db_path=tmp_path / "anf.db", fault_injection=fault_injection,
                                       storage=storage))
        client.__enter__()
        clients.append(client)
        parents = [(f"{ACC_PATH}?{V}", {"location": "westus2"}),
                   (f"{POOL_PATH}?{V}", {"location": "westus2",
                                         "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}})]
        for url, b in parents + ([(VOL, vol_body())] if volume else []):
            r = client.put(url, json=b)
            if r.status_code == 201:
                assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def create(client, url=SNAP):
    r = client.put(url, json={"location": "westus2"})
    assert r.status_code == 201, r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    return client.get(url).json()


def file_system_id(client):
    return client.get(VOL).json()["properties"]["fileSystemId"]


# --- 생성 ---


def test_create_snapshot(client, storage):
    """AC-01 (계약·상태)."""
    assert client.get(SNAPS).json() == {"value": []}
    r = client.put(SNAP, json={"location": "westus2"}, headers={"x-ms-correlation-request-id": "corr-ac01"})

    assert r.status_code == 201
    # ANF는 스냅샷 생성 201에 두 헤더를 다 붙인다 (녹화 R1)
    assert "Azure-AsyncOperation" in r.headers and "Location" in r.headers
    assert r.json() == {"id": SNAP_PATH, "name": "acc1/pool1/vol1/snap1",
                        "type": "Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots",
                        "location": "westus2", "properties": {"provisioningState": "Creating"}}
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "CREATE")

    snap = client.get(SNAP).json()
    props = snap["properties"]
    assert str(uuid.UUID(props["snapshotId"])) == props["snapshotId"]
    assert props == {"provisioningState": "Succeeded", "snapshotId": props["snapshotId"], "created": CREATED}
    assert "tags" not in snap
    assert client.get(SNAPS).json() == {"value": [snap]}
    assert storage.calls[-1] == ("ensure_snapshot", file_system_id(client), props["snapshotId"], "snap1", "corr-ac01")


def test_location_style_polling_returns_the_snapshot(client):
    r = client.put(SNAP, json={"location": "westus2"})
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    result = client.get(r.headers["Location"])
    assert (result.status_code, result.json()["properties"]["provisioningState"]) == (200, "Succeeded")


def test_list_is_sorted_by_name(client):
    for name in ("weekly", "daily"):
        create(client, f"{VOL_PATH}/snapshots/{name}?{V}")
    assert [s["name"] for s in client.get(SNAPS).json()["value"]] == ["acc1/pool1/vol1/daily", "acc1/pool1/vol1/weekly"]


# --- 다시 PUT (결정 3) ---


def test_put_again_is_an_async_update(client, storage):
    """AC-08 (계약·상태)."""
    first = create(client)["properties"]
    r = client.put(SNAP, json={"location": "westus2"})

    assert r.status_code == 200
    assert "Azure-AsyncOperation" in r.headers and "Location" not in r.headers
    assert r.json()["properties"]["provisioningState"] == "Updating"
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "UPDATE")
    assert client.get(SNAP).json()["properties"] == first
    assert [c[0] for c in storage.calls].count("ensure_snapshot") == 2  # 같은 uuid로 다시 보장한다

    r = client.put(SNAP, json={"location": "eastus"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "InvalidResourceLocation")


# --- 삭제 ---


def test_delete_snapshot(client, storage):
    """AC-06 (계약·상태)."""
    snap_id = create(client)["properties"]["snapshotId"]
    r = client.delete(SNAP)

    assert (r.status_code, r.content) == (202, b"")
    assert "Location" in r.headers and "Azure-AsyncOperation" in r.headers
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "DELETE")
    gone = client.get(SNAP)
    assert (gone.status_code, gone.json()["error"]) == (404, {"code": "ResourceNotFound", "message": NOT_FOUND})
    assert client.delete(SNAP).status_code == 204
    assert storage.calls[-1][:3] == ("delete_snapshot", file_system_id(client), snap_id)
    assert client.get(r.headers["Location"]).status_code == 204


# --- 거절 (AC-07) ---


@pytest.mark.parametrize("name", [".a", "-a", "a%20b", "a" * 256])
def test_invalid_snapshot_name(client, name):
    r = client.put(f"{VOL_PATH}/snapshots/{name}?{V}", json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "InvalidResourceName")


@pytest.mark.parametrize("body", [
    {}, {"location": "westus2", "tags": {"a": "b"}}, {"location": "westus2", "properties": {"x": 1}},
])
def test_invalid_body(client, body):
    r = client.put(SNAP, json=body)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "InvalidRequestContent")
    assert client.get(SNAPS).json() == {"value": []}


def test_missing_volume(client):
    r = client.put(f"{POOL_PATH}/volumes/nope/snapshots/snap1?{V}", json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]["code"]) == (404, "ParentResourceNotFound")
    assert client.get(f"{POOL_PATH}/volumes/nope/snapshots?{V}").status_code == 404


def test_patch_is_not_allowed(client):
    create(client)
    assert client.patch(SNAP, json={}).status_code == 405


def test_api_version_is_required(client):
    r = client.put(SNAP_PATH, json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "MissingApiVersionParameter")


def test_at_most_255_snapshots(client):
    for i in range(255):
        assert client.put(f"{VOL_PATH}/snapshots/s{i}?{V}", json={"location": "westus2"}).status_code == 201
    r = client.put(SNAP, json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]) == (400, {
        "code": "BadRequest", "message": "Cannot exceed maximum number of snapshots (255) for the volume."})


def test_volume_not_succeeded(make_client):
    client = make_client(fault_injection='{"volumes/create": {"delaySeconds": 5}}', volume=False)
    assert client.put(VOL, json=vol_body()).status_code == 201  # Creating
    r = client.put(SNAP, json={"location": "westus2"})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "BadRequest")


def test_volume_being_deleted(make_client):
    client = make_client(fault_injection='{"volumes/delete": {"delaySeconds": 5}}')
    create(client)
    assert client.delete(VOL).status_code == 202  # Deleting
    for r in (client.put(f"{VOL_PATH}/snapshots/new?{V}", json={"location": "westus2"}), client.delete(SNAP)):
        assert (r.status_code, r.json()["error"]["code"]) == (409, "Conflict")


# --- 진행 중 충돌 (AC-09) ---


def test_operation_in_progress(make_client):
    client = make_client(fault_injection='{"snapshots/create": {"delaySeconds": 1}}')
    r = client.put(SNAP, json={"location": "westus2"})
    for again in (client.put(SNAP, json={"location": "westus2"}), client.delete(SNAP)):
        assert (again.status_code, again.json()["error"]["code"]) == (409, "AnotherOperationInProgress")
    volume_delete = client.delete(VOL)
    assert (volume_delete.status_code, volume_delete.json()["error"]["code"]) == (409, "Conflict")
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Succeeded"


# --- 볼륨 연쇄 삭제 (AC-10) ---


def test_volume_delete_deletes_its_snapshots(client, storage):
    create(client)
    create(client, f"{VOL_PATH}/snapshots/snap2?{V}")
    r = client.delete(VOL)
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(SNAP).status_code == 404
    assert client.get(SNAPS).status_code == 404
    assert storage.calls[-1][0] == "delete_volume"  # agent의 볼륨 삭제가 스냅샷도 지운다


# --- 실패와 회복 (AC-11) ---


def test_storage_failure_then_put_again(client, storage):
    storage.error = RuntimeError("A snapshot with the specified name already exists.")
    r = client.put(SNAP, json={"location": "westus2"})
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["error"]["code"]) == ("Failed", "InternalServerError")
    assert client.get(SNAP).json()["properties"] == {"provisioningState": "Failed"}

    storage.error = None
    r = client.put(SNAP, json={"location": "westus2"})
    assert (r.status_code, r.json()["properties"]["provisioningState"]) == (200, "Updating")
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(SNAP).json()["properties"]["created"] == CREATED


@pytest.mark.parametrize("key", ["snapshots/create", "snapshots/update", "snapshots/delete"])
def test_snapshot_fault_keys(tmp_path, storage, key):
    create_app(db_path=tmp_path / "anf.db", fault_injection=f'{{"{key}": {{"fail": true}}}}', storage=storage)


def test_injected_failure(make_client):
    client = make_client(fault_injection='{"snapshots/create": {"fail": true}}')
    r = client.put(SNAP, json={"location": "westus2"})
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert status["status"] == "Failed" and "snapshots/create" in status["error"]["message"]


# --- 재시작 복구 (AC-12 a의 계약 부분) ---


def test_unfinished_create_finishes_after_restart(tmp_path, storage):
    db = tmp_path / "anf.db"
    with TestClient(create_app(db_path=db, fault_injection='{"snapshots/create": {"delaySeconds": 30}}',
                               storage=storage)) as first:
        for url, b in ((f"{ACC_PATH}?{V}", {"location": "westus2"}),
                       (f"{POOL_PATH}?{V}", {"location": "westus2",
                                             "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}}),
                       (VOL, vol_body())):
            assert wait_terminal(first, first.put(url, json=b).headers["Azure-AsyncOperation"])["status"] == "Succeeded"
        url = first.put(SNAP, json={"location": "westus2"}).headers["Azure-AsyncOperation"]
    with TestClient(create_app(db_path=db, fault_injection="", storage=storage)) as second:
        assert wait_terminal(second, url)["status"] == "Succeeded"
        assert second.get(SNAP).json()["properties"]["created"] == CREATED
