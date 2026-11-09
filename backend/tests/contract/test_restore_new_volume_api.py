"""API 계약: 스냅샷에서 새 볼륨 만들기의 ARM 경로, 응답 코드, 헤더, LRO 흐름, agent 호출 (복원 설계 §4, §8의 AC ID).

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
POOL2_PATH = f"{ACC_PATH}/capacityPools/pool2"
VOL_PATH = f"{POOL_PATH}/volumes/vol1"
VOL = f"{VOL_PATH}?{V}"
NEW_PATH = f"{POOL_PATH}/volumes/new1"
NEW = f"{NEW_PATH}?{V}"
SUBNET = f"/subscriptions/{SUB}/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/anf"


def snap_path(name, volume=VOL_PATH):
    return f"{volume}/snapshots/{name}"


def snap_url(name, volume=VOL_PATH):
    return f"{snap_path(name, volume)}?{V}"


class FakeStorage:
    """agent 흉내. 볼륨마다 스냅샷 레코드를 들고, 스냅샷에서 볼륨을 만들면 원본 스냅샷의 이름·시각으로 base 스냅샷을
    찍는다 (복원 설계 결정 7)."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.ips: dict[str, str] = {}
        self.snapshots: dict[str, dict[str, dict]] = {}  # 볼륨 uuid → 스냅샷 uuid → 레코드

    async def ensure_volume(self, uuid_, path, size, perms, protocol, correlation_id=None, clone=None):
        self.calls.append(("ensure_volume", uuid_, path, size, perms, protocol, clone))
        records = self.snapshots.setdefault(uuid_, {})
        if clone is not None and not records:
            source = self.snapshots[clone[0]][clone[1]]
            base = str(uuid.uuid4())
            records[base] = {"uuid": base, "name": source["name"], "create_time": source["create_time"],
                             "volume": {"uuid": uuid_}}
        return self.ips.setdefault(uuid_, f"172.30.0.{129 + len(self.ips)}")

    async def delete_volume(self, uuid_, correlation_id=None):
        self.calls.append(("delete_volume", uuid_))
        self.snapshots.pop(uuid_, None)

    async def ensure_snapshot(self, volume_uuid, uuid_, name, correlation_id=None):
        self.calls.append(("ensure_snapshot", volume_uuid, uuid_, name))
        records = self.snapshots.setdefault(volume_uuid, {})
        created = f"2026-11-08T23:07:{len(records):02d}Z"
        records.setdefault(uuid_, {"uuid": uuid_, "name": name, "create_time": created,
                                   "volume": {"uuid": volume_uuid}})
        return records[uuid_]["create_time"]

    async def delete_snapshot(self, volume_uuid, uuid_, correlation_id=None):
        self.calls.append(("delete_snapshot", volume_uuid, uuid_))
        self.snapshots[volume_uuid].pop(uuid_, None)

    async def revert_volume(self, volume_uuid, snapshot_uuid, request_uuid, correlation_id=None):
        self.calls.append(("revert_volume", volume_uuid, snapshot_uuid))
        return await self.snapshot_uuids(volume_uuid)

    async def snapshot_uuids(self, volume_uuid, correlation_id=None):
        return set(self.snapshots.get(volume_uuid, {}))

    async def snapshot_records(self, volume_uuid, correlation_id=None):
        return list(self.snapshots.get(volume_uuid, {}).values())


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


def put_and_wait(client, url, b, status="Succeeded"):
    r = client.put(url, json=b)
    assert r.status_code in (200, 201), r.text
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == status
    return r


def new_body(snapshot="s2", size=100 * GIB, **props):
    return {"location": "westus2", "properties": {
        "creationToken": "new1", "usageThreshold": size, "subnetId": SUBNET,
        "snapshotId": snap_path(snapshot), **props}}


@pytest.fixture
def make_client(tmp_path, storage):
    """원본: pool1(Premium)의 vol1 (NFSv4.1, 0755, 100 GiB)과 스냅샷 s1, s2. pool2(Standard)는 비어 있다.
    원본은 결함 주입 없이 만들고, 시험할 앱만 주입한 값으로 띄운다."""
    clients = []

    def make(fault_injection=""):
        db = tmp_path / "anf.db"
        if not db.exists():
            with TestClient(create_app(db_path=db, fault_injection="", storage=storage)) as setup:
                put_and_wait(setup, f"{ACC_PATH}?{V}", {"location": "westus2"})
                for path, level in ((POOL_PATH, "Premium"), (POOL2_PATH, "Standard")):
                    put_and_wait(setup, f"{path}?{V}", {
                        "location": "westus2", "properties": {"size": 4 * TIB, "serviceLevel": level}})
                put_and_wait(setup, VOL, {"location": "westus2", "properties": {
                    "creationToken": "vol1", "usageThreshold": 100 * GIB, "subnetId": SUBNET,
                    "protocolTypes": ["NFSv4.1"], "unixPermissions": "0755"}})
                for name in ("s1", "s2"):
                    put_and_wait(setup, snap_url(name), {"location": "westus2"})
        client = TestClient(create_app(db_path=db, fault_injection=fault_injection, storage=storage))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def snapshot_names(client, volume):
    return [s["name"].rsplit("/", 1)[-1] for s in client.get(f"{volume}/snapshots?{V}").json()["value"]]


def error_of(r):
    return r.status_code, r.json()["error"]["code"]


# --- 성공 (AC-01, AC-04 b) ---


def test_create_from_snapshot_is_201_and_finishes_with_a_base_snapshot(client, storage):
    """AC-01 (계약·상태)."""
    source = client.get(VOL).json()["properties"]
    s2 = client.get(snap_url("s2")).json()

    r = client.put(NEW, json=new_body(), headers={"x-ms-correlation-request-id": "corr-n"})

    # 녹화 R4: 201, 두 헤더, Creating 본문에 snapshotId. originatingResourceId·mountTargets는 아직 없다
    assert r.status_code == 201, r.text
    assert "Azure-AsyncOperation" in r.headers and "Location" in r.headers
    created = r.json()["properties"]
    assert (created["provisioningState"], created["snapshotId"]) == ("Creating", snap_path("s2"))
    assert "originatingResourceId" not in created and "mountTargets" not in created
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["properties"]) == ("Succeeded", {"resourceName": NEW_PATH, "action": "CREATE"})

    props = client.get(NEW).json()["properties"]
    assert props["provisioningState"] == "Succeeded"
    assert props["snapshotId"] == props["originatingResourceId"] == snap_path("s2")
    assert props["fileSystemId"] != source["fileSystemId"]
    assert props["mountTargets"][0]["ipAddress"] != source["mountTargets"][0]["ipAddress"]
    assert "cloneProgress" not in props
    # 주지 않은 프로토콜과 권한은 원본 볼륨 값이다 (결정 3)
    assert (props["protocolTypes"], props["unixPermissions"]) == (["NFSv4.1"], "0755")
    assert props["exportPolicy"]["rules"][0]["nfsv41"] is True

    # agent에는 원본 볼륨과 스냅샷의 uuid를 넘긴다 (결정 14)
    clone = (source["fileSystemId"], s2["properties"]["snapshotId"])
    assert storage.calls[-1] == ("ensure_volume", props["fileSystemId"], "/new1", 100 * GIB, 755, "nfs4.1", clone)

    # base 스냅샷: 이름과 created는 원본 스냅샷의 것, snapshotId는 새 것 (결정 7)
    assert snapshot_names(client, NEW_PATH) == ["s2"]
    base = client.get(snap_url("s2", NEW_PATH))
    assert base.status_code == 200
    base = base.json()
    assert base["name"] == "acc1/pool1/new1/s2"
    assert base["properties"]["provisioningState"] == "Succeeded"
    assert base["properties"]["created"] == s2["properties"]["created"]
    assert base["properties"]["snapshotId"] != s2["properties"]["snapshotId"]
    # 원본은 그대로다
    assert snapshot_names(client, VOL_PATH) == ["s1", "s2"]


def test_new_volume_is_creating_while_the_injected_delay_runs(make_client):
    """AC-01: 지연을 주입하면 그동안 GET이 Creating이다 (결정 15: 키는 volumes/create)."""
    client = make_client('{"volumes/create": {"delaySeconds": 1}}')
    r = client.put(NEW, json=new_body())
    assert r.status_code == 201
    status = client.get(r.headers["Azure-AsyncOperation"]).json()
    assert (status["status"], status["properties"]["action"]) == ("Creating", "CREATE")
    assert client.get(NEW).json()["properties"]["provisioningState"] == "Creating"
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"


def test_new_volume_in_another_pool_follows_its_own_pool(client, storage):
    """AC-04 (b) 계약: 같은 계정의 다른 풀, 다른 NFS 버전 (결정 2·3)."""
    url = f"{POOL2_PATH}/volumes/new2?{V}"
    put_and_wait(client, url, new_body(protocolTypes=["NFSv3"], unixPermissions="0700"))

    props = client.get(url).json()["properties"]
    assert (props["serviceLevel"], props["actualThroughputMibps"]) == ("Standard", 1.5625)
    assert (props["protocolTypes"], props["unixPermissions"]) == (["NFSv3"], "0700")
    assert props["originatingResourceId"] == snap_path("s2")
    assert storage.calls[-1][5:] == ("nfs3", (client.get(VOL).json()["properties"]["fileSystemId"],
                                              client.get(snap_url("s2")).json()["properties"]["snapshotId"]))
    assert snapshot_names(client, f"{POOL2_PATH}/volumes/new2") == ["s2"]


# --- 거절 (AC-07) ---


def test_rejections_create_no_volume_and_no_operation(client, storage):
    """AC-07 (계약)."""
    before = len(storage.calls)
    other_account = snap_path("s2").replace("/netAppAccounts/acc1/", "/netAppAccounts/acc2/")
    other_group = snap_path("s2").replace("/resourceGroups/rg1/", "/resourceGroups/rg2/")
    cases = [
        (new_body(snapshotId=7), 400, "InvalidRequestContent"),
        (new_body(snapshotId=VOL_PATH), 400, "InvalidRequestContent"),
        (new_body(snapshotId=other_account), 400, "BadRequest"),
        (new_body(snapshotId=other_group), 400, "BadRequest"),
        (new_body("nosuch"), 404, "ResourceNotFound"),
        (new_body(snapshotId=snap_path("s2", f"{POOL_PATH}/volumes/novol")), 404, "ResourceNotFound"),
        (new_body(size=50 * GIB), 400, "BadRequest"),
        (new_body(deleteBaseSnapshot=True), 400, "InvalidRequestContent"),
        (new_body(deleteBaseSnapshot="no"), 400, "InvalidRequestContent"),
        (new_body(size=4 * TIB), 400, "BadRequest"),
    ]
    for b, status, code in cases:
        r = client.put(NEW, json=b)
        assert error_of(r) == (status, code), r.text
    assert client.put(NEW, json=new_body(size=50 * GIB)).json()["error"]["message"] == (
        "The 'properties.usageThreshold' of a volume created from a snapshot must be at least the source "
        "volume's 100 GiB.")
    assert client.put(NEW, json=new_body(size=4 * TIB)).json()["error"]["message"] == (
        "Pool size too small for total volume size.")
    assert client.get(NEW).status_code == 404
    assert len(storage.calls) == before
    assert snapshot_names(client, VOL_PATH) == ["s1", "s2"]


def test_failed_snapshot_cannot_be_a_source(make_client):
    """AC-07: 실패를 주입해 Failed가 된 스냅샷 → 400 BadRequest."""
    client = make_client('{"snapshots/create": {"fail": true}}')
    put_and_wait(client, snap_url("bad"), {"location": "westus2"}, status="Failed")
    r = client.put(NEW, json=new_body("bad"))
    assert error_of(r) == (400, "BadRequest")
    assert client.get(NEW).status_code == 404


def test_snapshot_id_cannot_be_changed_after_creation(client):
    """AC-07: 끝난 새 볼륨에 다른 snapshotId는 400, 같은 값(대소문자 무시)은 200. 일반 볼륨에 넣어도 400 (결정 12)."""
    put_and_wait(client, NEW, new_body())
    message = "SnapshotId cannot be changed."
    for r in (client.put(NEW, json=new_body("s1")),
              client.patch(NEW, json={"properties": {"snapshotId": snap_path("s1")}}),
              client.put(VOL, json={"location": "westus2", "properties": {
                  "creationToken": "vol1", "usageThreshold": 100 * GIB, "subnetId": SUBNET,
                  "snapshotId": snap_path("s1")}})):
        assert (error_of(r), r.json()["error"]["message"]) == ((400, "BadRequest"), message), r.text

    again = client.put(NEW, json=new_body(snapshotId=snap_path("s2").upper().replace("SNAPSHOTS/S2", "snapshots/s2")))
    assert again.status_code == 200, again.text
    assert "Location" not in again.headers  # 갱신은 일반 볼륨 갱신과 같다
    assert wait_terminal(client, again.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    props = client.get(NEW).json()["properties"]
    assert props["snapshotId"] == props["originatingResourceId"] == snap_path("s2")
    assert snapshot_names(client, NEW_PATH) == ["s2"]


# --- 진행 중 충돌과 원본 보호 (AC-08) ---


def test_source_is_protected_until_the_new_volume_is_created(make_client):
    """AC-08 (계약): 생성 중에는 원본 스냅샷 DELETE, 원본 볼륨 DELETE·revert가 409 Conflict다 (결정 9)."""
    client = make_client('{"volumes/create": {"delaySeconds": 1}}')
    r = client.put(NEW, json=new_body())
    assert r.status_code == 201

    for res in (client.delete(snap_url("s2")), client.delete(VOL),
                client.post(f"{VOL_PATH}/revert?{V}", json={"snapshotId": snap_path("s1")})):
        assert error_of(res) == (409, "Conflict"), res.text
        assert f"because volume '{NEW_PATH}' is being created from snapshot" in res.json()["error"]["message"]
    # 원본 볼륨의 다른 스냅샷은 지울 수 있다
    d = client.delete(snap_url("s1"))
    assert d.status_code == 202
    assert wait_terminal(client, d.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"

    # 만든 뒤에는 독립이다: 원본을 되돌리고, 지우고, 원본 볼륨을 지워도 새 볼륨과 base 스냅샷이 남는다
    for res in (client.post(f"{VOL_PATH}/revert?{V}", json={"snapshotId": snap_path("s2")}),
                client.delete(snap_url("s2")), client.delete(VOL)):
        assert res.status_code == 202, res.text
        assert wait_terminal(client, res.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(VOL).status_code == 404
    assert client.get(NEW).json()["properties"]["provisioningState"] == "Succeeded"
    assert snapshot_names(client, NEW_PATH) == ["s2"]


def test_new_volume_from_a_busy_source_is_409(make_client):
    """AC-08: 원본 스냅샷이나 원본 볼륨에 진행 중 작업이 있으면 409 Conflict."""
    client = make_client('{"snapshots/create": {"delaySeconds": 1}, "volumes/patch": {"delaySeconds": 1}}')
    r = client.put(snap_url("s3"), json={"location": "westus2"})
    res = client.put(NEW, json=new_body("s3"))
    assert error_of(res) == (409, "Conflict"), res.text
    assert f"because an operation is in progress on '{snap_path('s3')}'" in res.json()["error"]["message"]
    wait_terminal(client, r.headers["Azure-AsyncOperation"])

    r = client.patch(VOL, json={"tags": {"a": "b"}})
    res = client.put(NEW, json=new_body())
    assert error_of(res) == (409, "Conflict"), res.text
    assert f"because an operation is in progress on '{VOL_PATH}'" in res.json()["error"]["message"]
    wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert client.get(NEW).status_code == 404


# --- 실패, 회복, 재시작 (AC-09) ---


def test_injected_failure_keeps_the_source_protected_and_the_same_put_recovers(make_client, storage):
    """AC-09 (a) 계약: 실패하면 새 볼륨 Failed, 원본 보호가 이어지고, 같은 PUT(200 Updating)이 끝낸다."""
    client = make_client('{"volumes/create": {"fail": true}}')
    r = client.put(NEW, json=new_body())
    status = wait_terminal(client, r.headers["Azure-AsyncOperation"])
    assert (status["status"], status["error"]["code"]) == ("Failed", "InternalServerError")
    assert client.get(NEW).json()["properties"]["provisioningState"] == "Failed"
    assert "originatingResourceId" not in client.get(NEW).json()["properties"]
    assert snapshot_names(client, NEW_PATH) == []
    assert error_of(client.delete(snap_url("s2"))) == (409, "Conflict")
    client.__exit__(None, None, None)

    client = make_client()
    again = client.put(NEW, json=new_body())
    assert again.status_code == 200, again.text
    assert wait_terminal(client, again.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    props = client.get(NEW).json()["properties"]
    assert props["originatingResourceId"] == snap_path("s2")
    assert storage.calls[-1][-1] is not None  # 끝나기 전 갱신도 agent에 원본을 넘긴다 (결정 10)
    assert snapshot_names(client, NEW_PATH) == ["s2"]
    assert client.delete(snap_url("s2")).status_code == 202


def test_deleting_an_unfinished_new_volume_releases_the_source(make_client):
    """결정 9: 새 볼륨을 지우면 원본 보호가 풀린다."""
    client = make_client('{"volumes/create": {"fail": true}}')
    r = client.put(NEW, json=new_body())
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Failed"
    d = client.delete(NEW)
    assert d.status_code == 202
    assert wait_terminal(client, d.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.delete(snap_url("s2")).status_code == 202


def test_creation_left_in_progress_finishes_after_restart(make_client, storage):
    """AC-09 (c) 계약: 재시작한 워커가 같은 작업을 다시 실행하고, 원본을 다시 넘긴다."""
    client = make_client('{"volumes/create": {"delaySeconds": 30}}')
    r = client.put(NEW, json=new_body())
    assert r.status_code == 201
    client.__exit__(None, None, None)  # 워커가 작업을 끝내기 전에 멈춘다

    client = make_client()
    assert wait_terminal(client, r.headers["Azure-AsyncOperation"])["status"] == "Succeeded"
    assert client.get(NEW).json()["properties"]["originatingResourceId"] == snap_path("s2")
    assert snapshot_names(client, NEW_PATH) == ["s2"]
