"""API 계약: 볼륨 revert 액션의 ARM 경로, 응답 코드, 헤더, LRO 흐름, agent 호출 (되돌리기 설계 §4, §8의 AC ID).

storage agent는 가짜 클라이언트다. 실제 agent와 데이터 효과는 real-env-verifier가 같은 기준으로 확인한다.
"""

import time

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
REVERT = f"{VOL_PATH}/revert?{V}"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/anf"


def snap_path(name):
    return f"{VOL_PATH}/snapshots/{name}"


def snap_url(name):
    return f"{snap_path(name)}?{V}"


class FakeStorage:
    def __init__(self):
        self.calls: list[tuple] = []
        self.keep: set[str] | None = None  # 되돌린 뒤 남길 스냅샷 이름. None이면 모두 남긴다
        self.uuids: dict[str, str] = {}  # 스냅샷 uuid → 이름

    async def ensure_volume(self, *args, correlation_id=None):
        self.calls.append(("ensure_volume", *args))
        return "172.30.0.129"

    async def delete_volume(self, uuid, correlation_id=None):
        self.calls.append(("delete_volume", uuid))

    async def ensure_snapshot(self, volume_uuid, uuid, name, correlation_id=None):
        self.calls.append(("ensure_snapshot", volume_uuid, uuid, name))
        self.uuids[uuid] = name
        return "2026-11-08T23:07:12Z"

    async def delete_snapshot(self, *args, correlation_id=None):
        self.calls.append(("delete_snapshot", *args))

    async def revert_volume(self, volume_uuid, snapshot_uuid, request_uuid, correlation_id=None):
        self.calls.append(("revert_volume", volume_uuid, snapshot_uuid, request_uuid, correlation_id))
        return {u for u, n in self.uuids.items() if self.keep is None or n in self.keep}


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


def put_and_wait(client, url, b):
    r = client.put(url, json=b)
    assert r.status_code in (200, 201), r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    return r


@pytest.fixture
def make_client(tmp_path, storage):
    clients = []

    def make(fault_injection="", snapshots=("s1", "s2", "s3")):
        client = TestClient(create_app(db_path=tmp_path / "anf.db", fault_injection=fault_injection,
                                       storage=storage))
        client.__enter__()
        clients.append(client)
        if client.get(VOL).status_code == 404:
            put_and_wait(client, f"{ACC_PATH}?{V}", {"location": "westus2"})
            put_and_wait(client, f"{POOL_PATH}?{V}", {
                "location": "westus2", "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}})
            put_and_wait(client, VOL, {"location": "westus2", "properties": {
                "creationToken": "vol1", "usageThreshold": 100 * GIB, "subnetId": SUBNET}})
            for name in snapshots:
                put_and_wait(client, snap_url(name), {"location": "westus2"})
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def snapshot_names(client):
    return [s["name"].rsplit("/", 1)[-1] for s in client.get(f"{VOL_PATH}/snapshots?{V}").json()["value"]]


# --- 성공 (AC-01) ---


def test_revert_is_202_with_both_headers_and_finishes_as_post(client, storage):
    """AC-01 (계약·상태)."""
    s2 = client.get(snap_url("s2")).json()
    storage.keep = {"s1", "s2"}

    r = client.post(REVERT, json={"snapshotId": snap_path("s2")}, headers={"x-ms-correlation-request-id": "corr-r"})

    # 녹화 R3: 본문 없는 202, 두 헤더, Retry-After 없음
    assert (r.status_code, r.content) == (202, b"")
    assert "Azure-AsyncOperation" in r.headers and "Location" in r.headers
    assert "Retry-After" not in r.headers
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]) == ("Succeeded", {"resourceName": VOL_PATH, "action": "POST"})

    # 끝난 뒤 Location 조회는 볼륨 본문 (녹화 R3 #46. 스펙은 void)
    final = client.get(r.headers["Location"])
    assert final.status_code == 200
    assert (final.json()["id"], final.json()["properties"]["provisioningState"]) == (VOL_PATH, "Succeeded")
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Succeeded"

    # 작업 ID가 agent의 멱등 키, 상관 ID도 넘긴다
    fsid = client.get(VOL).json()["properties"]["fileSystemId"]
    assert storage.calls[-1] == ("revert_volume", fsid, s2["properties"]["snapshotId"], status["name"], "corr-r")
    # 더 새 스냅샷(s3)은 사라지고, 고른 스냅샷과 오래된 스냅샷은 그대로다 (결정 8·9)
    assert snapshot_names(client) == ["s1", "s2"]
    assert client.get(snap_url("s3")).status_code == 404
    assert client.get(snap_url("s2")).json() == s2


def test_volume_and_operation_are_reverting_while_it_runs(make_client):
    """AC-01: 지연을 주입하면 그동안 볼륨 GET이 Reverting이다 (결정 2)."""
    client = make_client('{"volumes/post": {"delaySeconds": 1}}')
    r = client.post(REVERT, json={"snapshotId": snap_path("s1")})
    assert r.status_code == 202
    status = client.get(r.headers["Azure-AsyncOperation"]).json()
    assert (status["status"], status["properties"]["action"]) == ("Reverting", "POST")
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Reverting"
    location = client.get(r.headers["Location"])
    assert (location.status_code, location.content) == (202, b"")
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


# --- 거절 (AC-05) ---


def test_rejections_create_no_operation(client, storage):
    """AC-05 (계약)."""
    before = len(storage.calls)
    cases = [
        (client.post(REVERT, content=b""), 400, "InvalidRequestContent"),
        (client.post(REVERT, json=[]), 400, "InvalidRequestContent"),
        (client.post(REVERT, json={"snapshotId": snap_path("s1"), "x": 1}), 400, "InvalidRequestContent"),
        (client.post(REVERT, json={}), 400, "InvalidRequestContent"),
        (client.post(REVERT, json={"snapshotId": 7}), 400, "InvalidRequestContent"),
        (client.post(REVERT, json={"snapshotId": VOL_PATH}), 400, "InvalidRequestContent"),
        (client.post(REVERT, json={"snapshotId": f"{POOL_PATH}/volumes/vol2/snapshots/s1"}), 400, "BadRequest"),
        (client.post(REVERT, json={"snapshotId": snap_path("nosuch")}), 404, "ResourceNotFound"),
        (client.post(f"{POOL_PATH}/volumes/vol2/revert?{V}", json={"snapshotId": f"{POOL_PATH}/volumes/vol2/snapshots/s1"}),
         404, "ResourceNotFound"),
        (client.post(f"{POOL_PATH}/volumes/-bad/revert?{V}", json={"snapshotId": snap_path("s1")}),
         400, "InvalidResourceName"),
        (client.post(f"{VOL_PATH}/revert", json={"snapshotId": snap_path("s1")}), 400, "MissingApiVersionParameter"),
    ]
    for r, status, code in cases:
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), r.text
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Succeeded"
    assert snapshot_names(client) == ["s1", "s2", "s3"]
    assert len(storage.calls) == before


# --- 진행 중 충돌 (AC-06) ---


def test_changes_during_a_revert_are_rejected(make_client):
    """AC-06 (계약)."""
    client = make_client('{"volumes/post": {"delaySeconds": 1}}')
    r = client.post(REVERT, json={"snapshotId": snap_path("s2")})
    assert r.status_code == 202

    conflicts = [
        (client.post(REVERT, json={"snapshotId": snap_path("s1")}), 409, "RequestConflict"),
        (client.patch(VOL, json={"tags": {"a": "b"}}), 409, "RequestConflict"),
        (client.delete(VOL), 409, "RequestConflict"),
        (client.put(snap_url("new"), json={"location": "westus2"}), 400, "BadRequest"),
        (client.put(snap_url("s3"), json={"location": "westus2"}), 409, "Conflict"),
        (client.delete(snap_url("s3")), 409, "Conflict"),
    ]
    for res, status, code in conflicts:
        assert (res.status_code, res.json()["error"]["code"]) == (status, code), res.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


def test_revert_while_a_snapshot_is_being_created_is_409(make_client):
    """AC-06: 스냅샷 생성에 지연을 주입하고 그동안 revert하면 409 Conflict."""
    client = make_client('{"snapshots/create": {"delaySeconds": 1}}', snapshots=())
    put_and_wait(client, snap_url("s1"), {"location": "westus2"})
    r = client.put(snap_url("s2"), json={"location": "westus2"})
    res = client.post(REVERT, json={"snapshotId": snap_path("s1")})
    assert (res.status_code, res.json()["error"]["code"]) == (409, "Conflict")
    wait_terminal(client, r.headers["Azure-AsyncOperation"])


# --- 실패와 재시작 (AC-07, AC-08) ---


def test_injected_failure_fails_the_volume_and_put_recovers(make_client, storage):
    """AC-07 (상태)."""
    client = make_client('{"volumes/post": {"fail": true}}')
    r = client.post(REVERT, json={"snapshotId": snap_path("s1")})
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["error"]["code"]) == ("Failed", "InternalServerError")
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Failed"
    assert client.get(r.headers["Location"]).status_code == 500
    assert snapshot_names(client) == ["s1", "s2", "s3"]
    assert not any(c[0] == "revert_volume" for c in storage.calls)

    failed = client.post(REVERT, json={"snapshotId": snap_path("s1")})
    assert (failed.status_code, failed.json()["error"]["code"]) == (400, "BadRequest")
    put_and_wait(client, VOL, {"location": "westus2", "properties": {
        "creationToken": "vol1", "usageThreshold": 100 * GIB, "subnetId": SUBNET}})
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Succeeded"


def test_revert_left_in_progress_finishes_after_restart_with_the_same_key(make_client, storage):
    """AC-08 (a): 재시작한 워커가 같은 작업 ID(멱등 키)로 agent를 다시 부른다 (결정 4)."""
    client = make_client('{"volumes/post": {"delaySeconds": 30}}')
    r = client.post(REVERT, json={"snapshotId": snap_path("s1")})
    op_id = client.get(r.headers["Azure-AsyncOperation"]).json()["name"]
    client.__exit__(None, None, None)  # 워커가 작업을 끝내기 전에 멈춘다

    storage.keep = {"s1"}
    client = make_client()
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert status["status"] == "Succeeded"
    assert [c[3] for c in storage.calls if c[0] == "revert_volume"] == [op_id]
    assert snapshot_names(client) == ["s1"]
