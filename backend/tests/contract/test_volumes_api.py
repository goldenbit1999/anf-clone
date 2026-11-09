"""API 계약: 볼륨의 ARM 경로, 응답 코드, 헤더, LRO 흐름, agent 호출 (볼륨 설계 §4, 결정 3·11·12, §8의 AC ID).

storage agent는 가짜 클라이언트다. 실제 agent와 데이터 효과는 real-env-verifier가 같은 기준으로 확인한다.
"""

import logging
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
VOLS = f"{POOL_PATH}/volumes?{V}"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/anf"


class FakeStorage:
    def __init__(self):
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def ensure_volume(self, *args, correlation_id=None, clone=None):
        self.calls.append(("ensure", *args, correlation_id))
        if self.error:
            raise self.error
        return "172.30.0.129"

    async def delete_volume(self, uuid, correlation_id=None):
        self.calls.append(("delete", uuid, correlation_id))


@pytest.fixture
def storage():
    return FakeStorage()


@pytest.fixture
def make_client(tmp_path, storage):
    clients = []

    def make(fault_injection="", min_volume_size_gib=""):
        client = TestClient(create_app(db_path=tmp_path / "anf.db", fault_injection=fault_injection,
                                       storage=storage, min_volume_size_gib=min_volume_size_gib))
        client.__enter__()
        clients.append(client)
        for url, b in ((f"{ACC_PATH}?{V}", {"location": "westus2"}),
                       (f"{POOL_PATH}?{V}", {"location": "westus2",
                                             "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}})):
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


def wait_terminal(client, url, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(url).json()
        if body["status"] in ("Succeeded", "Failed", "Canceled"):
            return body
        assert time.monotonic() < deadline, f"operation did not finish: {body}"
        time.sleep(0.05)


def vol_body(size=100 * GIB, tags=None, **props):
    b = {"location": "westus2",
         "properties": {"creationToken": "vol1", "usageThreshold": size, "subnetId": SUBNET, **props}}
    if tags is not None:
        b["tags"] = tags
    return b


def create(client, **kw):
    r = client.put(VOL, json=vol_body(**kw))
    assert r.status_code == 201, r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    return client.get(VOL).json()


def test_create_volume(client, storage):
    """AC-01 (계약·상태)."""
    r = client.put(VOL, json=vol_body(), headers={"x-ms-correlation-request-id": "corr-ac01"})

    assert r.status_code == 201
    assert "Azure-AsyncOperation" in r.headers and "Location" not in r.headers
    created = r.json()["properties"]
    assert created["provisioningState"] == "Creating"
    assert "mountTargets" not in created  # 생성 작업이 성공한 뒤에 나온다 (결정 12)
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "CREATE")

    v = client.get(VOL).json()
    props = v["properties"]
    fsid = props["fileSystemId"]
    assert str(uuid.UUID(fsid)) == fsid
    assert props["mountTargets"] == [{"mountTargetId": fsid, "fileSystemId": fsid, "ipAddress": "172.30.0.129"}]
    assert props["protocolTypes"] == ["NFSv3"]
    assert props["exportPolicy"]["rules"][0]["nfsv3"] is True
    assert (props["unixPermissions"], props["serviceLevel"], props["actualThroughputMibps"]) == ("0770", "Premium", 6.25)
    assert [x["name"] for x in client.get(VOLS).json()["value"]] == ["acc1/pool1/vol1"]
    assert storage.calls == [("ensure", fsid, "/vol1", 100 * GIB, 770, "nfs3", "corr-ac01")]


def test_patch_tags(client, storage):
    """AC-08 (계약·상태): 202, Patching 본문, 두 헤더. Location 방식으로 끝난 결과는 볼륨 본문이다."""
    create(client)
    r = client.patch(VOL, json={"tags": {"a": "b"}})

    assert r.status_code == 202
    assert r.json()["properties"]["provisioningState"] == "Patching"
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "PATCH")
    result = client.get(r.headers["Location"])
    assert (result.status_code, result.json()["tags"]) == (200, {"a": "b"})
    assert client.get(VOL).json()["tags"] == {"a": "b"}
    assert [c[0] for c in storage.calls] == ["ensure", "ensure"]


def test_delete_volume(client, storage):
    """AC-09 (계약·상태)."""
    fsid = create(client)["properties"]["fileSystemId"]
    r = client.delete(VOL)

    assert (r.status_code, r.content) == (202, b"")
    assert "Location" in r.headers and "Azure-AsyncOperation" in r.headers
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "DELETE")
    assert client.get(VOL).status_code == 404
    assert client.delete(VOL).status_code == 204
    assert storage.calls[-1][:2] == ("delete", fsid)


def test_storage_failure_then_put_again(client, storage):
    """AC-11 (계약 부분): agent 작업이 실패하면 Failed, 같은 본문으로 다시 PUT하면 200 → Succeeded."""
    storage.error = RuntimeError("agent job failed")
    r = client.put(VOL, json=vol_body())
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert status["status"] == "Failed" and status["error"]["code"] == "InternalServerError"
    assert client.get(VOL).json()["properties"]["provisioningState"] == "Failed"

    storage.error = None
    r = client.put(VOL, json=vol_body())
    assert (r.status_code, r.json()["properties"]["provisioningState"]) == (200, "Updating")
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(VOL).json()["properties"]["mountTargets"][0]["ipAddress"] == "172.30.0.129"


def test_volume_fault_injection(make_client):
    client = make_client(fault_injection='{"volumes/create": {"fail": true}}')
    r = client.put(VOL, json=vol_body())
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert status["status"] == "Failed"
    assert "volumes/create" in status["error"]["message"]


def test_pool_with_volume_cannot_be_deleted(client):
    """CV-1."""
    create(client)
    r = client.delete(f"{POOL_PATH}?{V}")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "CannotDeleteResource")


# --- 최소 볼륨 크기 (결정 3) ---


def test_default_minimum_is_50_gib(client):
    """AC-06의 일부: 최소 크기를 낮추지 않은 서버."""
    r = client.put(VOL, json=vol_body(size=49 * GIB))
    assert (r.status_code, r.json()["error"]["code"]) == (400, "InvalidRequestContent")
    assert client.put(VOL, json=vol_body(size=50 * GIB)).status_code == 201


def test_lowered_minimum_for_verification(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="anf_api.arm_app"):
        client = make_client(min_volume_size_gib="1")
    assert any("ANF_MIN_VOLUME_SIZE_GIB" in m for m in caplog.messages)
    create(client, size=GIB)


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_invalid_minimum_prevents_startup(tmp_path, storage, value):
    with pytest.raises(ValueError, match="ANF_MIN_VOLUME_SIZE_GIB"):
        create_app(db_path=tmp_path / "anf.db", fault_injection="", storage=storage, min_volume_size_gib=value)
