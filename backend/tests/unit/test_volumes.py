"""볼륨 (FR-04): 본문 규칙, 응답 본문, 작업 흐름, 부모·용량·경로 규칙, 처리기 (볼륨 설계 §3, §4, 결정 11).

처리기는 가짜 agent 클라이언트로 확인한다. 실제 agent 호출은 test_storage_client.py가 확인한다.
"""

import asyncio
import uuid

import pytest

import anf_api.accounts as accounts
import anf_api.capacity_pools as pools
import anf_api.volumes as volumes
from anf_api.arm_rules import VOLUME_TYPE, ArmError

GIB = 1 << 30
TIB = 1 << 40
ACC = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
POOL = ACC + "/capacityPools/pool1"
VOL = POOL + "/volumes/vol1"
SUBNET = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/anf"
V6 = ("Cannot modify resource with id '{}' because the resource entity provisioning state is not "
      "terminal. Please wait for the provisioning state to become terminal and then retry the request.")


def finish(store, op, status="Succeeded"):
    """워커가 작업을 끝낸 것처럼 만든다 (생성·갱신·PATCH)."""
    with store.transaction() as tx:
        res = tx.get_resource(op.resource_id)
        res.provisioning_state = status
        tx.put_resource(res)
        tx.finish_operation(op.id, status)


def make_pool(store, name="pool1", size_tib=4, level="Premium", qos="Auto", state="Succeeded"):
    _, _, op = pools.put_pool(store, "s1", "rg1", "acc1", name, {
        "location": "westus2",
        "properties": {"size": size_tib * TIB, "serviceLevel": level, "qosType": qos}}, None)
    if state in ("Succeeded", "Failed"):
        finish(store, op, state)
    else:  # 진행 중: 작업은 열어 두고 풀 상태만 바꾼다
        with store.transaction() as tx:
            res = tx.get_resource(op.resource_id)
            res.provisioning_state = state
            tx.put_resource(res)


@pytest.fixture
def store(tmp_path):
    from anf_api.state_store import StateStore

    s = StateStore(tmp_path / "anf.db")
    _, _, op = accounts.put_account(s, "s1", "rg1", "acc1", {"location": "westus2"}, None)
    finish(s, op)
    make_pool(s)
    return s


def body(token="vol1", size=100 * GIB, subnet=SUBNET, tags=None, **props):
    b = {"location": "westus2",
         "properties": {"creationToken": token, "usageThreshold": size, "subnetId": subnet, **props}}
    if tags is not None:
        b["tags"] = tags
    return b


def put(store, b, name="vol1", pool="pool1", min_size=None):
    kw = {} if min_size is None else {"min_size": min_size}
    return volumes.put_volume(store, "s1", "rg1", "acc1", pool, name, b, "corr-1", **kw)


def patch(store, b, name="vol1"):
    return volumes.patch_volume(store, "s1", "rg1", "acc1", "pool1", name, b, None)


def delete(store, name="vol1"):
    return volumes.delete_volume(store, "s1", "rg1", "acc1", "pool1", name, None)


def create(store, name="vol1", pool="pool1", status="Succeeded", **kw):
    _, res, op = put(store, body(**kw), name, pool)
    finish(store, op, status)
    return store.get_resource(res.id)


def arm_error(fn, *args, **kw):
    with pytest.raises(ArmError) as e:
        fn(*args, **kw)
    return e.value


def default_rule(nfsv3=True, nfsv41=False):
    return {
        "ruleIndex": 1, "unixReadOnly": False, "unixReadWrite": True, "cifs": False,
        "nfsv3": nfsv3, "nfsv41": nfsv41, "allowedClients": "0.0.0.0/0",
        "kerberos5ReadOnly": False, "kerberos5ReadWrite": False, "kerberos5iReadOnly": False,
        "kerberos5iReadWrite": False, "kerberos5pReadOnly": False, "kerberos5pReadWrite": False,
        "hasRootAccess": True, "chownMode": "Restricted",
    }


# --- 생성과 본문 ---


def test_create_is_creating_with_create_operation(store):
    created, res, op = put(store, body())
    assert created is True
    assert res.id == VOL and res.type == VOLUME_TYPE and res.parent_id == POOL
    assert res.provisioning_state == "Creating"
    assert (op.action, op.status, op.correlation_id) == ("CREATE", "Creating", "corr-1")


def test_volume_body_has_service_filled_defaults(store):
    _, res, _ = put(store, body(tags={"k": "v"}))
    b = volumes.volume_body(res)
    props = b["properties"]
    assert b["id"] == VOL
    assert b["name"] == "acc1/pool1/vol1"
    assert b["type"] == "Microsoft.NetApp/netAppAccounts/capacityPools/volumes"
    assert (b["location"], b["tags"]) == ("westus2", {"k": "v"})
    assert str(uuid.UUID(props["fileSystemId"])) == props["fileSystemId"]
    assert props == {
        "provisioningState": "Creating",
        "fileSystemId": props["fileSystemId"],
        "creationToken": "vol1",
        "usageThreshold": 100 * GIB,
        "subnetId": SUBNET,
        "serviceLevel": "Premium",  # 풀 값을 물려받는다 (녹화 V1)
        "protocolTypes": ["NFSv3"],
        "networkFeatures": "Basic",
        "exportPolicy": {"rules": [default_rule()]},
        "unixPermissions": "0770",
        "snapshotDirectoryVisible": True,
        "securityStyle": "unix",
        "actualThroughputMibps": 6.25,  # 100 GiB × Premium 64 MiB/s/TiB (녹화 V1)
    }
    assert "mountTargets" not in props  # 생성 작업이 성공한 뒤에 나온다 (결정 12)


def test_nfsv41_volume_default_rule_follows_protocol(store):
    _, res, _ = put(store, body(protocolTypes=["NFSv4.1"]))
    props = volumes.volume_body(res)["properties"]
    assert props["protocolTypes"] == ["NFSv4.1"]
    assert props["exportPolicy"] == {"rules": [default_rule(nfsv3=False, nfsv41=True)]}


def test_mount_targets_are_shown_once_recorded(store):
    res = create(store)
    target = {"mountTargetId": res.properties["fileSystemId"],
              "fileSystemId": res.properties["fileSystemId"], "ipAddress": "172.30.0.1"}
    res.properties["mountTargets"] = [target]
    assert volumes.volume_body(res)["properties"]["mountTargets"] == [target]


@pytest.mark.parametrize("props", [
    {"protocolTypes": ["NFSv3"]},
    {"unixPermissions": "0755"},
    {"networkFeatures": "Standard"},
    {"serviceLevel": "Premium"},
    {"snapshotDirectoryVisible": True},
    {"securityStyle": "Unix"},
    {"kerberosEnabled": False, "ldapEnabled": False, "isLargeVolume": False, "coolAccess": False},
    {"throughputMibps": None, "snapshotId": None, "backupId": None},
    {"exportPolicy": {"rules": [default_rule()]}},
    {"provisioningState": "Succeeded", "actualThroughputMibps": 1.0, "mountTargets": []},
])
def test_create_accepts_values_the_clone_supports(store, props):
    created, res, _ = put(store, body(**props))
    assert created


def test_unix_permissions_given_at_create_are_kept(store):
    _, res, _ = put(store, body(unixPermissions="0755"))
    assert volumes.volume_body(res)["properties"]["unixPermissions"] == "0755"


@pytest.mark.parametrize("name", ["1vol", "-v", "v" * 65, "a.b"])
def test_invalid_volume_name(store, name):
    e = arm_error(put, store, body(), name)
    assert (e.status, e.code) == (400, "InvalidResourceName")


@pytest.mark.parametrize("b", [
    {"location": "westus2", "properties": {"usageThreshold": 100 * GIB, "subnetId": SUBNET}},
    {"location": "westus2", "properties": {"creationToken": "vol1", "subnetId": SUBNET}},
    {"location": "westus2", "properties": {"creationToken": "vol1", "usageThreshold": 100 * GIB}},
    {"properties": {"creationToken": "vol1", "usageThreshold": 100 * GIB, "subnetId": SUBNET}},
    body(token="-a"), body(token="1a"), body(token="a.b"), body(token=""), body(token="a" * 81),
    body(token=5),
    body(size=100 * GIB + 1), body(size=49 * GIB), body(size=100 * TIB + GIB), body(size="100"),
    body(size=True),
    body(protocolTypes=["NFSv3", "NFSv4.1"]), body(protocolTypes=[]), body(protocolTypes="NFSv3"),
    body(protocolTypes=["NFSv4"]),
    body(subnet="subnet1"),
    body(subnet="/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/v1"),
    body(unixPermissions="777"), body(unixPermissions="0778"), body(unixPermissions=770),
    body(networkFeatures="Fancy"),
    body(foo=1),
    {**body(), "sku": "x"},
], ids=lambda b: str(b)[:80])
def test_malformed_body_is_invalid_request_content(store, b):
    e = arm_error(put, store, b)
    assert (e.status, e.code) == (400, "InvalidRequestContent")
    assert store.get_resource(VOL) is None


@pytest.mark.parametrize("props", [
    {"protocolTypes": ["CIFS"]},
    {"exportPolicy": {"rules": [{**default_rule(), "allowedClients": "10.0.0.0/24"}]}},
    {"throughputMibps": 10.0},
    {"snapshotDirectoryVisible": False},
    {"snapshotId": "snap1"},
    {"backupId": "b1"},
    {"dataProtection": {}},
    {"kerberosEnabled": True},
    {"ldapEnabled": True},
    {"isLargeVolume": True},
    {"coolAccess": True},
    {"securityStyle": "ntfs"},
])
def test_deferred_features_are_rejected(store, props):
    # 데이터 효과를 아직 만들지 않은 속성은 저장만 하지 않고 거절한다 (결정 4)
    e = arm_error(put, store, body(**props))
    assert (e.status, e.code) == (400, "InvalidRequestContent")
    assert "not supported by this ANF clone" in e.message
    assert store.get_resource(VOL) is None


def test_service_level_must_match_pool(store):
    e = arm_error(put, store, body(serviceLevel="Standard"))
    assert (e.status, e.code) == (400, "InvalidRequestContent")


def test_minimum_size_is_50_gib_unless_lowered(store):
    assert arm_error(put, store, body(size=49 * GIB)).status == 400
    put(store, body(size=50 * GIB))
    put(store, body(token="small", size=GIB), "small", min_size=GIB)  # 검증용 하한 (결정 3)


# --- 부모 ---


def test_missing_pool_is_parent_resource_not_found(store):
    e = arm_error(put, store, body(), "vol1", "nopool")
    assert (e.status, e.code) == (404, "ParentResourceNotFound")
    assert ACC + "/capacityPools/nopool" in e.message


def test_pool_being_deleted_is_conflict(store):
    with store.transaction() as tx:
        pool = tx.get_resource(POOL)
        pool.provisioning_state = "Deleting"
        tx.put_resource(pool)
    e = arm_error(put, store, body())
    assert (e.status, e.code) == (409, "Conflict")


@pytest.mark.parametrize("state", ["Creating", "Updating", "Failed"])
def test_pool_not_succeeded_is_bad_request(store, state):
    make_pool(store, "pool2", state=state)
    e = arm_error(put, store, body(), "vol1", "pool2")
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", "Volume cannot be created in a pool that isn't in state succeeded.")


def test_manual_qos_pool_is_deferred(store):
    make_pool(store, "manual", qos="Manual")
    e = arm_error(put, store, body(), "vol1", "manual")
    assert (e.status, e.code) == (400, "InvalidRequestContent")


# --- 경로와 용량 ---


@pytest.mark.parametrize("token, pool", [("vol1", "pool1"), ("VOL1", "pool1"), ("vol1", "pool2")])
def test_file_path_must_be_unique_in_the_clone(store, token, pool):
    make_pool(store, "pool2")
    create(store)
    e = arm_error(put, store, body(token=token), "vol2", pool)
    assert (e.status, e.code, e.message) == (400, "BadRequest", "File path already in use.")


def test_volumes_cannot_exceed_pool_size(store):
    create(store, size=3 * TIB)
    e = arm_error(put, store, body(token="vol2", size=2 * TIB), "vol2")
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", "Pool size too small for total volume size.")
    create(store, "vol2", token="vol2", size=TIB)  # 합이 풀 크기와 같으면 된다


def test_failed_volume_still_reserves_its_quota(store):
    create(store, size=3 * TIB, status="Failed")
    assert arm_error(put, store, body(token="vol2", size=2 * TIB), "vol2").status == 400


# --- PUT 갱신 ---


def test_put_again_is_update(store):
    create(store)
    created, res, op = put(store, body(tags={"a": "b"}))
    assert created is False
    assert (res.provisioning_state, res.tags) == ("Updating", {"a": "b"})
    assert (op.action, op.status) == ("UPDATE", "Updating")


def test_put_back_the_get_body_is_accepted(store):
    # SDK가 GET 본문을 고쳐 다시 PUT하는 흐름 (AC-07). 읽기 전용 값과 같은 값은 통과한다
    res = create(store)
    res.properties["mountTargets"] = [{"mountTargetId": "x", "fileSystemId": "x", "ipAddress": "1.2.3.4"}]
    b = volumes.volume_body(res)
    for key in ("id", "name", "type"):
        b.pop(key)
    created, _, _ = put(store, b)
    assert created is False


def test_put_without_properties_keeps_existing_values(store):
    before = create(store).properties
    _, res, _ = put(store, {"location": "westus2"})
    assert res.properties == before


def test_network_features_can_change(store):
    create(store)
    _, res, _ = put(store, body(networkFeatures="Standard"))
    assert res.properties["networkFeatures"] == "Standard"


def test_subnet_id_compare_ignores_case(store):
    create(store)
    put(store, body(subnet=SUBNET.upper()))


@pytest.mark.parametrize("props, message", [
    ({"creationToken": "other"}, "CreationToken cannot be changed."),
    ({"subnetId": SUBNET.replace("anf", "other")}, "SubnetId cannot be changed."),
    ({"fileSystemId": "00000000-0000-0000-0000-000000000000"}, "FileSystemId cannot be changed."),
])
def test_immutable_properties(store, props, message):
    create(store)
    b = body()
    b["properties"].update(props)
    for fn in (put, patch):
        e = arm_error(fn, store, b)
        assert (e.status, e.code, e.message) == (400, "BadRequest", message)


@pytest.mark.parametrize("props", [
    {"usageThreshold": 200 * GIB},  # FR-16
    {"unixPermissions": "0755"},
    {"protocolTypes": ["NFSv4.1"]},
    {"serviceLevel": "Ultra"},
    {"snapshotDirectoryVisible": False},  # FR-05
    {"exportPolicy": {"rules": [default_rule(nfsv41=True)]}},  # FR-15
])
def test_changing_deferred_properties_is_rejected(store, props):
    before = create(store)
    for fn in (put, patch):
        e = arm_error(fn, store, {"location": "westus2", "properties": props})
        assert (e.status, e.code) == (400, "InvalidRequestContent")
    assert store.get_resource(VOL).properties == before.properties


def test_update_with_other_location_is_conflict(store):
    create(store)
    b = body()
    b["location"] = "eastus"
    e = arm_error(put, store, b)
    assert (e.status, e.code) == (409, "InvalidResourceLocation")


# --- 진행 중 충돌 ---


def test_volume_with_operation_in_progress_is_request_conflict(store):
    put(store, body())  # Creating
    for fn, args in ((put, (body(),)), (patch, ({"tags": {}},)), (delete, ())):
        e = arm_error(fn, store, *args)
        assert (e.status, e.code, e.message) == (409, "RequestConflict", V6.format(VOL))


# --- PATCH ---


def test_patch_tags(store):
    create(store)
    res, op = patch(store, {"tags": {"x": "1"}})
    assert (res.provisioning_state, res.tags) == ("Patching", {"x": "1"})
    assert (op.action, op.status) == ("PATCH", "Patching")
    assert op.previous["tags"] == {}


def test_patch_with_same_values_is_accepted(store):
    create(store)
    patch(store, {"properties": {"usageThreshold": 100 * GIB, "protocolTypes": ["NFSv3"]}})


def test_patch_missing_volume_is_not_found(store):
    e = arm_error(patch, store, {"tags": {}})
    assert (e.status, e.code) == (404, "ResourceNotFound")


# --- DELETE, GET, 목록 ---


def test_delete(store):
    create(store)
    op = delete(store)
    assert (op.action, op.status) == ("DELETE", "Deleting")
    assert store.get_resource(VOL).provisioning_state == "Deleting"


def test_delete_missing_volume_is_none(store):
    assert delete(store) is None


def test_get_and_list(store):
    create(store)
    create(store, "vol2", token="vol2")
    assert volumes.get_volume(store, "s1", "rg1", "acc1", "pool1", "VOL1").id == VOL
    assert [r.name for r in volumes.list_volumes(store, "s1", "rg1", "acc1", "pool1")] == ["vol1", "vol2"]
    e = arm_error(volumes.get_volume, store, "s1", "rg1", "acc1", "pool1", "nope")
    assert (e.status, e.code) == (404, "ResourceNotFound")
    e = arm_error(volumes.list_volumes, store, "s1", "rg1", "acc1", "nopool")
    assert (e.status, e.code) == (404, "ResourceNotFound")


# --- 풀 쪽 규칙이 실제 볼륨 행으로 동작한다 (풀 설계 §6, CV-1~CV-3) ---


def test_pool_with_volume_cannot_be_deleted(store):
    create(store)
    e = arm_error(pools.delete_pool, store, "s1", "rg1", "acc1", "pool1", None)
    assert (e.status, e.code) == (409, "CannotDeleteResource")
    assert "volumes/vol1" in e.message


def test_pool_cannot_shrink_below_volume_quotas(store):
    create(store, size=2 * TIB)
    e = arm_error(pools.put_pool, store, "s1", "rg1", "acc1", "pool1", {
        "location": "westus2", "properties": {"size": TIB, "serviceLevel": "Premium"}}, None)
    assert (e.status, e.code) == (400, "BadRequest")


def test_pool_service_level_is_fixed_while_it_has_volumes(store):
    create(store)
    e = arm_error(pools.put_pool, store, "s1", "rg1", "acc1", "pool1", {
        "location": "westus2", "properties": {"size": 4 * TIB, "serviceLevel": "Ultra"}}, None)
    assert (e.status, e.code, e.message) == (400, "BadRequest", "ServiceLevel cannot be changed.")


# --- 처리기 (결정 11·12) ---


class FakeStorage:
    """agent 클라이언트 흉내. 실패를 정하면 StorageError처럼 예외를 던진다."""

    def __init__(self, ip="172.30.0.129"):
        self.ip = ip
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def ensure_volume(self, *args, correlation_id=None):
        self.calls.append(("ensure", *args, correlation_id))
        if self.error:
            raise self.error
        return self.ip

    async def delete_volume(self, uuid, correlation_id=None):
        self.calls.append(("delete", uuid, correlation_id))
        if self.error:
            raise self.error


def run_operation(store, storage, op):
    """공통 LRO 워커가 작업 하나를 처리한다 (처리기 실행 → 리소스·작업 반영)."""
    from anf_api.lro import LroWorker

    asyncio.run(LroWorker(store, volumes.make_handlers(store, storage))._process(op))
    return store.get_operation(op.id)


def test_handlers_cover_all_volume_operations(store):
    assert set(volumes.make_handlers(store, FakeStorage())) == {
        (VOLUME_TYPE, a) for a in ("CREATE", "UPDATE", "PATCH", "DELETE")}


def test_create_ensures_the_volume_and_records_the_mount_target(store):
    storage = FakeStorage()
    _, res, op = put(store, body(protocolTypes=["NFSv4.1"], unixPermissions="1777", size=2 * GIB), min_size=GIB)
    fsid = res.properties["fileSystemId"]

    assert run_operation(store, storage, op).status == "Succeeded"

    assert storage.calls == [("ensure", fsid, "/vol1", 2 * GIB, 1777, "nfs4.1", "corr-1")]
    props = volumes.volume_body(store.get_resource(res.id))["properties"]
    assert props["provisioningState"] == "Succeeded"
    assert props["mountTargets"] == [{"mountTargetId": fsid, "fileSystemId": fsid, "ipAddress": "172.30.0.129"}]


@pytest.mark.parametrize("action", ["UPDATE", "PATCH"])
def test_update_and_patch_ensure_the_volume_again(store, action):
    # 생성이 실패한 볼륨도 다시 PUT하면 데이터 플레인까지 완성된다 (결정 11)
    v = create(store, status="Failed")
    storage = FakeStorage()
    if action == "UPDATE":
        _, _, op = put(store, body())
    else:
        _, op = patch(store, {"tags": {"a": "b"}})
    assert run_operation(store, storage, op).status == "Succeeded"
    assert [c[0] for c in storage.calls] == ["ensure"]
    assert store.get_resource(v.id).properties["mountTargets"][0]["ipAddress"] == "172.30.0.129"


def test_failed_storage_work_fails_the_operation(store):
    storage = FakeStorage()
    storage.error = RuntimeError("agent job failed")
    _, res, op = put(store, body())

    done = run_operation(store, storage, op)

    assert (done.status, done.error["code"]) == ("Failed", "InternalServerError")
    v = store.get_resource(res.id)
    assert v.provisioning_state == "Failed"
    assert "mountTargets" not in v.properties


def test_delete_removes_the_agent_volume(store):
    v = create(store)
    storage = FakeStorage()
    op = volumes.delete_volume(store, "s1", "rg1", "acc1", "pool1", "vol1", "corr-9")

    assert run_operation(store, storage, op).status == "Succeeded"

    assert storage.calls == [("delete", v.properties["fileSystemId"], "corr-9")]
    assert store.get_resource(v.id) is None


def test_failed_delete_keeps_the_volume(store):
    v = create(store)
    storage = FakeStorage()
    storage.error = RuntimeError("umount: target is busy")
    op = delete(store)
    assert run_operation(store, storage, op).status == "Failed"
    assert store.get_resource(v.id).provisioning_state == "Failed"
