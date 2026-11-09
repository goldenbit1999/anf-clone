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
        self.limits: list = []  # ensure_volume마다 보낸 처리량 한도 (처리량 결정 8)

    async def ensure_volume(self, *args, correlation_id=None, clone=None, qos=None):
        self.calls.append(("ensure", *args, correlation_id))
        self.limits.append(qos)
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


# --- 처리량 한도 (FR-08, 처리량 설계 §4, AC-01·02·04·08·09 계약) ---

MANUAL_PATH = f"{ACC_PATH}/capacityPools/manual"
MVOL_PATH = f"{MANUAL_PATH}/volumes/m1"
MVOL = f"{MVOL_PATH}?{V}"


def manual_pool(client, size_tib=1, level="Ultra"):
    r = client.put(f"{MANUAL_PATH}?{V}", json={"location": "westus2", "properties": {
        "size": size_tib * TIB, "serviceLevel": level, "qosType": "Manual"}})
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


def put_wait(client, url, b, expected=201):
    r = client.put(url, json=b)
    assert r.status_code == expected, r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    return client.get(url).json()["properties"]


def test_auto_volume_shows_the_rounded_limit_and_the_pool_sums_it(client, storage):
    """AC-01 (a) 계약: round(할당량 TiB × 64, 3), Auto 볼륨에는 throughputMibps가 없다."""
    props = put_wait(client, VOL, vol_body(size=101 * GIB))
    assert props["actualThroughputMibps"] == 6.312 and "throughputMibps" not in props
    assert client.get(f"{POOL_PATH}?{V}").json()["properties"]["utilizedThroughputMibps"] == 6.312
    assert storage.limits == [6.312]


def test_manual_volume_is_created_and_changed_with_throughput_mibps(client, storage):
    """AC-02·AC-04 계약: 201 → Succeeded, PATCH 202 → Succeeded, 재PUT 200 → Succeeded. 매번 agent에 한도를 보낸다."""
    manual_pool(client)
    props = put_wait(client, MVOL, vol_body(creationToken="m1", throughputMibps=10))
    assert props["throughputMibps"] == props["actualThroughputMibps"] == 10.0
    pool = f"{MANUAL_PATH}?{V}"
    assert client.get(pool).json()["properties"]["utilizedThroughputMibps"] == 10.0

    r = client.patch(MVOL, json={"properties": {"throughputMibps": 30}})
    assert (r.status_code, r.json()["properties"]["provisioningState"]) == (202, "Patching")
    assert r.json()["properties"]["throughputMibps"] == 30.0
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]["action"]) == ("Succeeded", "PATCH")
    props = put_wait(client, MVOL, vol_body(creationToken="m1", throughputMibps=12.5), expected=200)
    assert props["actualThroughputMibps"] == 12.5
    assert client.get(pool).json()["properties"]["utilizedThroughputMibps"] == 12.5
    assert storage.limits == [10.0, 30.0, 12.5]


@pytest.mark.parametrize("props, code, message", [
    ({}, "InvalidRequestContent",
     "The 'properties.throughputMibps' property is required for a volume in a Manual QoS capacity pool."),
    ({"throughputMibps": None}, "InvalidRequestContent",
     "The 'properties.throughputMibps' property is required for a volume in a Manual QoS capacity pool."),
    ({"throughputMibps": 0.5}, "InvalidRequestContent",
     "The 'properties.throughputMibps' property must be a number from 1 to 4500."),
    ({"throughputMibps": "10"}, "InvalidRequestContent",
     "The 'properties.throughputMibps' property must be a number from 1 to 4500."),
    ({"throughputMibps": 128.5}, "BadRequest",
     "Requested throughput not available. Capacity pool 'manual' has 128.0 MiB/s in total and 128.0 MiB/s left "
     "for this volume."),
])
def test_manual_volume_rejects_create_bodies(client, props, code, message):
    """AC-08 계약: 거절이면 볼륨 행과 작업이 생기지 않는다."""
    manual_pool(client)
    r = client.put(MVOL, json=vol_body(creationToken="m1", **props))
    assert (r.status_code, r.json()["error"]) == (400, {"code": code, "message": message})
    assert client.get(MVOL).status_code == 404


def test_auto_volume_rejects_throughput_mibps_and_budget_patch_keeps_the_old_value(client, storage):
    """AC-08 계약: Auto 풀 볼륨에 값, 예산 초과 PATCH."""
    r = client.put(VOL, json=vol_body(throughputMibps=10))
    assert (r.status_code, r.json()["error"]["code"]) == (400, "BadRequest")
    manual_pool(client)
    put_wait(client, MVOL, vol_body(creationToken="m1", throughputMibps=100))
    r = client.patch(MVOL, json={"properties": {"throughputMibps": 128.5}})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "BadRequest")
    props = client.get(MVOL).json()["properties"]
    assert (props["throughputMibps"], props["provisioningState"]) == (100.0, "Succeeded")
    assert storage.limits == [100.0]


def test_auto_to_manual_moves_limits_and_then_patch_changes_them(client, storage):
    """AC-09 계약: 전환 뒤 throughputMibps = 전환 전 actualThroughputMibps, 풀 사용량은 그대로."""
    before = put_wait(client, VOL, vol_body(size=101 * GIB))["actualThroughputMibps"]
    r = client.patch(f"{POOL_PATH}?{V}", json={"properties": {"qosType": "Manual"}})
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    props = client.get(VOL).json()["properties"]
    assert props["throughputMibps"] == props["actualThroughputMibps"] == before == 6.312
    assert client.get(f"{POOL_PATH}?{V}").json()["properties"]["utilizedThroughputMibps"] == 6.312
    r = client.patch(VOL, json={"properties": {"throughputMibps": 20}})
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert storage.limits == [6.312, 20.0]


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
