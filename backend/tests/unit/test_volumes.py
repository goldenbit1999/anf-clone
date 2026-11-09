"""볼륨 (FR-04): 본문 규칙, 응답 본문, 작업 흐름, 부모·용량·경로 규칙, 처리기 (볼륨 설계 §3, §4, 결정 11).

처리기는 가짜 agent 클라이언트로 확인한다. 실제 agent 호출은 test_storage_client.py가 확인한다.
"""

import asyncio
import uuid

import pytest

import anf_api.accounts as accounts
import anf_api.capacity_pools as pools
import anf_api.snapshots as snapshots
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
    {"deleteBaseSnapshot": False},
    {"exportPolicy": {"rules": [default_rule()]}},
    {"provisioningState": "Succeeded", "actualThroughputMibps": 1.0, "mountTargets": [],
     "originatingResourceId": "x"},
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
    {"snapshotDirectoryVisible": False},
    {"deleteBaseSnapshot": True},
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


def test_volume_with_a_snapshot_operation_in_progress_cannot_be_deleted(store):
    # 볼륨 DELETE는 스냅샷도 지운다. 진행 중인 스냅샷 작업과 겹치지 않게 거절한다 (스냅샷 설계 결정 2)
    create(store)
    _, snap, _ = snapshots.put_snapshot(store, "s1", "rg1", "acc1", "pool1", "vol1", "snap1",
                                        {"location": "westus2"}, None)
    e = arm_error(delete, store)
    assert (e.status, e.code, e.message) == (
        409, "Conflict", f"Cannot delete volume '{VOL}' because an operation is in progress on its snapshot "
                         f"'{snap.id}'. Wait until it is finished, and then retry.")
    assert store.get_resource(VOL).provisioning_state == "Succeeded"


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


# --- 처리량 한도 (FR-08, 처리량 설계 결정 2~7, §4.2) ---

MANUAL = ACC + "/capacityPools/manual"
REQUIRED = "The 'properties.throughputMibps' property is required for a volume in a Manual QoS capacity pool."
RANGE = "The 'properties.throughputMibps' property must be a number from 1 to 4500."
AUTO_ONLY = "The 'properties.throughputMibps' property can be set only for a volume in a Manual QoS capacity pool."


def manual_pool(store, size_tib=1, level="Ultra"):
    """Manual QoS 풀 'manual'. 기본 Ultra 1 TiB = 총 128 MiB/s."""
    make_pool(store, "manual", size_tib=size_tib, level=level, qos="Manual")


def mcreate(store, name, mibps, status="Succeeded", **kw):
    _, res, op = put(store, body(token=name, throughputMibps=mibps, **kw), name, "manual")
    finish(store, op, status)
    return store.get_resource(res.id)


def mpatch(store, b, name):
    return volumes.patch_volume(store, "s1", "rg1", "acc1", "manual", name, b, None)


def no_budget(total, free):
    return ("Requested throughput not available. Capacity pool 'manual' has "
            f"{total} MiB/s in total and {free} MiB/s left for this volume.")


@pytest.mark.parametrize("size, level, mibps", [
    (101 * GIB, "Premium", 6.312),  # 6.3125 → half-even (결정 2) [녹화 R3]
    (GIB, "Premium", 0.062),
    (GIB, "Standard", 0.016),
    (100 * GIB, "Premium", 6.25),
])
def test_auto_volume_limit_is_the_rounded_formula_without_throughput_mibps(store, size, level, mibps):
    make_pool(store, "pool2", level=level)
    _, res, _ = put(store, body(token="v", size=size), "v", "pool2", min_size=GIB)
    props = volumes.volume_body(res)["properties"]
    assert props["actualThroughputMibps"] == mibps
    assert "throughputMibps" not in props  # Auto 볼륨 응답에는 없다 (결정 4) [녹화 R4·R6]


def test_manual_pool_volume_keeps_the_requested_throughput(store):
    manual_pool(store)
    _, res, op = put(store, body(throughputMibps=10), "vol1", "manual")
    assert (res.provisioning_state, op.action) == ("Creating", "CREATE")
    props = volumes.volume_body(res)["properties"]
    assert props["throughputMibps"] == props["actualThroughputMibps"] == 10.0  # (결정 5) [녹화 R1]
    assert isinstance(props["throughputMibps"], float)
    _, res, _ = put(store, body(token="v2", throughputMibps=12.5), "v2", "manual")
    assert volumes.volume_body(res)["properties"]["actualThroughputMibps"] == 12.5


@pytest.mark.parametrize("props", [{}, {"throughputMibps": None}])
def test_manual_pool_volume_requires_throughput_mibps(store, props):
    manual_pool(store)
    e = arm_error(put, store, body(**props), "vol1", "manual")
    assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", REQUIRED)
    assert store.get_resource(MANUAL + "/volumes/vol1") is None
    assert store.active_operations() == []


@pytest.mark.parametrize("value", [0.5, 0, -1, 4500.5, "10", True, [], {}, float("inf"), float("nan")])
def test_throughput_mibps_must_be_a_number_from_1_to_4500(store, value):
    manual_pool(store)
    e = arm_error(put, store, body(throughputMibps=value), "vol1", "nopool")  # 본문 검사가 풀 검사보다 먼저다
    assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", RANGE)


def test_throughput_mibps_bounds_are_accepted(store):
    manual_pool(store, size_tib=40)  # 5,120 MiB/s
    mcreate(store, "v1", 1)
    mcreate(store, "v2", 4500)


def test_auto_pool_volume_rejects_throughput_mibps(store):
    e = arm_error(put, store, body(throughputMibps=10))
    assert (e.status, e.code, e.message) == (400, "BadRequest", AUTO_ONLY)
    assert store.get_resource(VOL) is None
    create(store)
    for fn in (put, patch):
        e = arm_error(fn, store, body(throughputMibps=10))
        assert (e.status, e.code, e.message) == (400, "BadRequest", AUTO_ONLY)
    assert "throughputMibps" not in store.get_resource(VOL).properties


def test_create_beyond_the_manual_pool_budget_is_400(store):
    manual_pool(store)  # 128 MiB/s
    mcreate(store, "v1", 100, status="Failed")  # 실패한 볼륨 행도 예산을 차지한다 (결정 5·7)
    e = arm_error(put, store, body(token="v2", throughputMibps=28.5), "v2", "manual")
    assert (e.status, e.code, e.message) == (400, "BadRequest", no_budget(128.0, 28.0))
    assert store.get_resource(MANUAL + "/volumes/v2") is None
    mcreate(store, "v2", 28)  # 정확히 남은 예산은 받는다


def test_throughput_change_beyond_the_budget_is_400_and_keeps_the_old_value(store):
    manual_pool(store)
    mcreate(store, "v1", 100)
    mcreate(store, "v2", 20)
    e = arm_error(mpatch, store, {"properties": {"throughputMibps": 108.5}}, "v1")
    assert (e.status, e.code, e.message) == (400, "BadRequest", no_budget(128.0, 108.0))
    assert store.get_resource(MANUAL + "/volumes/v1").properties["throughputMibps"] == 100
    assert store.active_operations() == []
    res, op = mpatch(store, {"properties": {"throughputMibps": 108}}, "v1")
    assert (res.provisioning_state, op.action) == ("Patching", "PATCH")
    assert res.properties["throughputMibps"] == 108.0
    assert op.previous["properties"]["throughputMibps"] == 100


def test_put_can_change_throughput_and_keeps_it_when_missing(store):
    manual_pool(store)
    mcreate(store, "v1", 10)
    created, res, _ = put(store, body(token="v1", throughputMibps=30), "v1", "manual")
    assert (created, res.properties["throughputMibps"]) == (False, 30.0)
    finish(store, store.active_operations()[0])
    _, res, op = put(store, {"location": "westus2"}, "v1", "manual")
    assert res.properties["throughputMibps"] == 30.0
    finish(store, op)
    res, _ = mpatch(store, {"properties": {"throughputMibps": None}}, "v1")  # null은 값을 바꾸지 않는다
    assert res.properties["throughputMibps"] == 30.0


def test_lowering_or_resending_a_limit_skips_the_budget(store):
    # 반올림한 Auto 값을 옮겨 받은 풀은 합이 총 처리량을 조금 넘을 수 있다. 한도를 올릴 때만 예산을 본다
    manual_pool(store)
    mcreate(store, "v1", 100)
    mcreate(store, "v2", 28)
    with store.transaction() as tx:
        v1 = tx.get_resource(MANUAL + "/volumes/v1")
        v1.properties = {**v1.properties, "throughputMibps": 100.5}
        tx.put_resource(v1)
    _, op = mpatch(store, {"properties": {"throughputMibps": 28}}, "v2")
    finish(store, op)
    mpatch(store, {"properties": {"throughputMibps": 20}}, "v2")


def set_throughput(store, name, mibps):
    """Auto → Manual 전환이 채운 값처럼 행에 직접 쓴다 (결정 6). 반올림한 Auto 값은 1 미만일 수 있다."""
    with store.transaction() as tx:
        v = tx.get_resource(MANUAL + "/volumes/" + name)
        v.properties = {**v.properties, "throughputMibps": mibps}
        tx.put_resource(v)


def test_resending_a_stored_limit_below_1_skips_the_range(store):
    # 갱신에서 저장된 값과 같은 값(소수 셋째 자리)은 1~4,500을 보지 않고 그대로 둔다. 바꾸는 값만 본다 (§9-5)
    manual_pool(store)
    mcreate(store, "v1", 10)
    set_throughput(store, "v1", 0.125)
    b = volumes.volume_body(store.get_resource(MANUAL + "/volumes/v1"))
    created, res, op = put(store, b, "v1", "manual")
    assert (created, op.action, res.properties["throughputMibps"]) == (False, "UPDATE", 0.125)
    finish(store, op)
    res, op = mpatch(store, {"properties": {"throughputMibps": 0.1254}}, "v1")  # 셋째 자리까지 같다
    assert (op.action, res.properties["throughputMibps"]) == ("PATCH", 0.125)
    finish(store, op)
    for fn, b in ((mpatch, {"properties": {"throughputMibps": 0.5}}),
                  (mpatch, {"properties": {"throughputMibps": 0.126}}),
                  (lambda s, b, n: put(s, b, n, "manual"), body(token="v1", throughputMibps=0.5))):
        e = arm_error(fn, store, b, "v1")
        assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", RANGE)
    assert store.get_resource(MANUAL + "/volumes/v1").properties["throughputMibps"] == 0.125
    e = arm_error(put, store, body(token="v2", throughputMibps=0.125), "v2", "manual")  # 새 볼륨은 늘 1~4,500
    assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", RANGE)


def test_resending_a_stored_limit_passes_an_overcommitted_budget(store):
    # 옮겨 받은 합이 총 처리량을 넘는 풀에서도 같은 값 재PUT은 예산을 보지 않는다 (§9-1)
    manual_pool(store)  # 128 MiB/s
    mcreate(store, "v1", 100)
    mcreate(store, "v2", 28)
    set_throughput(store, "v1", 100.5)
    created, res, op = put(store, body(token="v2", throughputMibps=28), "v2", "manual")
    assert (created, op.action, res.properties["throughputMibps"]) == (False, "UPDATE", 28.0)


def test_put_back_the_get_body_of_a_manual_volume(store):
    manual_pool(store)
    b = volumes.volume_body(mcreate(store, "v1", 12.5))
    for key in ("id", "name", "type"):
        b.pop(key)
    created, _, _ = put(store, b, "v1", "manual")
    assert created is False


def test_restore_to_a_manual_pool_needs_its_own_throughput(store):
    _, s = source(store)  # Auto pool1의 vol1과 스냅샷 s1
    manual_pool(store)
    e = arm_error(put_from, store, s.id, pool="manual")
    assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", REQUIRED)
    e = arm_error(put_from, store, s.id, pool="manual", throughputMibps=128.5)
    assert (e.status, e.code, e.message) == (400, "BadRequest", no_budget(128.0, 128.0))
    _, res, _ = put_from(store, s.id, pool="manual", throughputMibps=12.5)
    assert volumes.volume_body(res)["properties"]["actualThroughputMibps"] == 12.5
    e = arm_error(put_from, store, s.id, name="vol3", throughputMibps=10)  # Auto pool1
    assert (e.status, e.code, e.message) == (400, "BadRequest", AUTO_ONLY)


# --- 처리기 (결정 11·12) ---


class FakeStorage:
    """agent 클라이언트 흉내. 실패를 정하면 StorageError처럼 예외를 던진다."""

    def __init__(self, ip="172.30.0.129"):
        self.ip = ip
        self.calls: list[tuple] = []
        self.error: Exception | None = None
        self.remaining: set[str] = set()  # agent에 있는 스냅샷 uuid (되돌린 뒤 남은 것)
        self.records: list[dict] = []  # agent에 있는 스냅샷 레코드 (스냅샷에서 만든 볼륨의 base 스냅샷)
        self.limits: list = []  # ensure_volume마다 보낸 처리량 한도 (처리량 결정 8)

    async def snapshot_records(self, uuid, correlation_id=None):
        self.calls.append(("snapshot_records", uuid, correlation_id))
        return self.records

    async def revert_volume(self, uuid, snapshot_uuid, request_uuid, correlation_id=None):
        self.calls.append(("revert", uuid, snapshot_uuid, request_uuid, correlation_id))
        if self.error:
            raise self.error
        return self.remaining

    async def snapshot_uuids(self, uuid, correlation_id=None):
        self.calls.append(("snapshots", uuid, correlation_id))
        return self.remaining

    async def ensure_volume(self, *args, correlation_id=None, clone=None, qos=None):
        self.calls.append(("ensure", *args, correlation_id, clone))
        self.limits.append(qos)
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
        (VOLUME_TYPE, a) for a in ("CREATE", "UPDATE", "PATCH", "DELETE", "POST")}


def test_create_ensures_the_volume_and_records_the_mount_target(store):
    storage = FakeStorage()
    _, res, op = put(store, body(protocolTypes=["NFSv4.1"], unixPermissions="1777", size=2 * GIB), min_size=GIB)
    fsid = res.properties["fileSystemId"]

    assert run_operation(store, storage, op).status == "Succeeded"

    assert storage.calls == [("ensure", fsid, "/vol1", 2 * GIB, 1777, "nfs4.1", "corr-1", None)]
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


def test_every_ensure_sends_the_volume_limit(store):
    # agent POST 보장이 태그와 tc를 그 값에 맞춘다 (처리량 결정 8). Auto는 응답과 같은 반올림 값이다
    storage = FakeStorage()
    _, _, op = put(store, body(size=101 * GIB))
    run_operation(store, storage, op)
    manual_pool(store)
    _, _, op = put(store, body(token="m1", throughputMibps=10), "m1", "manual")
    run_operation(store, storage, op)
    _, op = mpatch(store, {"properties": {"throughputMibps": 30}}, "m1")
    run_operation(store, storage, op)
    _, _, op = put(store, body(token="m1"), "m1", "manual")
    run_operation(store, storage, op)
    assert storage.limits == [6.312, 10.0, 30.0, 30.0]


def test_failed_throughput_change_keeps_the_previous_value(store):
    manual_pool(store)
    mcreate(store, "m1", 10)
    storage = FakeStorage()
    storage.error = RuntimeError("agent job failed")
    _, op = mpatch(store, {"properties": {"throughputMibps": 30}}, "m1")
    assert run_operation(store, storage, op).status == "Failed"
    v = store.get_resource(MANUAL + "/volumes/m1")
    assert (v.provisioning_state, v.properties["throughputMibps"]) == ("Failed", 10)


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


# --- 되돌리기 (FR-06, 되돌리기 설계 §4) ---

SNAP = VOL + "/snapshots/{}"


def make_snapshot(store, name, volume="vol1", status="Succeeded"):
    _, res, op = snapshots.put_snapshot(store, "s1", "rg1", "acc1", "pool1", volume, name,
                                        {"location": "westus2"}, None)
    if status is not None:  # None이면 작업을 열어 둔다
        finish(store, op, status)
    return store.get_resource(res.id)


def revert(store, b, name="vol1"):
    return volumes.revert_volume(store, "s1", "rg1", "acc1", "pool1", name, b, "corr-7")


def test_revert_is_reverting_with_post_operation_and_the_chosen_snapshot(store):
    v = create(store)
    s = make_snapshot(store, "s1")

    op = revert(store, {"snapshotId": s.id})

    # 작업 상태와 볼륨 상태 모두 Reverting (녹화 R3, 결정 2). 작업 입력에 고른 스냅샷 (결정 11)
    assert (op.action, op.status, op.resource_id, op.correlation_id) == ("POST", "Reverting", v.id, "corr-7")
    assert op.params == {"snapshotId": s.id}
    assert store.get_resource(v.id).provisioning_state == "Reverting"
    assert [o.id for o in store.active_operations()] == [op.id]


def test_revert_accepts_ids_in_another_case(store):
    # ARM ID는 대소문자를 구분하지 않는다. 작업에는 저장된 스냅샷 ID를 남긴다
    create(store)
    s = make_snapshot(store, "s1")
    op = revert(store, {"snapshotId": s.id.upper().replace("SNAPSHOTS/S1", "snapshots/S1")})
    assert op.params == {"snapshotId": s.id}


@pytest.mark.parametrize("b, message", [
    ([], "The request content must be a JSON object."),
    ({"snapshotId": SNAP.format("s1"), "force": True}, "Value received for an unknown property 'force'."),
    ({}, "The 'snapshotId' property is required and must be a snapshot resource ID."),
    ({"snapshotId": 5}, "The 'snapshotId' property is required and must be a snapshot resource ID."),
    ({"snapshotId": VOL}, "The 'snapshotId' property must be a snapshot resource ID: /subscriptions/{id}"
     "/resourceGroups/{group}/providers/Microsoft.NetApp/netAppAccounts/{account}/capacityPools/{pool}"
     "/volumes/{volume}/snapshots/{snapshot}."),
    ({"snapshotId": SNAP.format("s1") + "/x"}, "The 'snapshotId' property must be a snapshot resource ID: "
     "/subscriptions/{id}/resourceGroups/{group}/providers/Microsoft.NetApp/netAppAccounts/{account}"
     "/capacityPools/{pool}/volumes/{volume}/snapshots/{snapshot}."),
])
def test_revert_body_errors_are_invalid_request_content(store, b, message):
    v = create(store)
    make_snapshot(store, "s1")
    e = arm_error(revert, store, b)
    assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", message)
    assert store.active_operations() == []
    assert store.get_resource(v.id).provisioning_state == "Succeeded"


def test_revert_to_a_snapshot_of_another_volume_is_400(store):
    create(store)
    create(store, name="vol2", token="vol2")
    other = make_snapshot(store, "s1", volume="vol2")
    e = arm_error(revert, store, {"snapshotId": other.id})
    assert (e.status, e.code) == (400, "BadRequest")
    assert e.message == f"The snapshot '{other.id}' does not belong to the volume '{VOL}'."
    assert store.active_operations() == []


def test_revert_of_a_missing_volume_is_404(store):
    e = arm_error(revert, store, {"snapshotId": SNAP.format("s1")})
    assert (e.status, e.code, e.message) == (404, "ResourceNotFound",
                                             f"The resource with identifier '{VOL}' is not found.")


def test_revert_while_the_volume_has_an_operation_is_409_request_conflict(store):
    create(store)
    s = make_snapshot(store, "s1")
    patch(store, {"tags": {"a": "b"}})  # Patching 작업이 열려 있다
    e = arm_error(revert, store, {"snapshotId": s.id})
    assert (e.status, e.code, e.message) == (409, "RequestConflict", V6.format(VOL))


def test_revert_of_a_failed_volume_is_400(store):
    v = create(store)
    s = make_snapshot(store, "s1")
    with store.transaction() as tx:
        res = tx.get_resource(v.id)
        res.provisioning_state = "Failed"
        tx.put_resource(res)
    e = arm_error(revert, store, {"snapshotId": s.id})
    assert (e.status, e.code, e.message) == (400, "BadRequest",
                                             "Volume cannot be reverted when it isn't in state succeeded.")


def test_revert_to_a_missing_snapshot_is_404_with_the_snapshot_wording(store):
    create(store)
    e = arm_error(revert, store, {"snapshotId": SNAP.format("nosuch")})
    # 스냅샷 GET과 같은 문구 (녹화 R1)
    assert (e.status, e.code) == (404, "ResourceNotFound")
    assert e.message == (
        "The requested snapshot 'nosuch' was not found on the volume 'acc1/pool1/vol1'. Please check the "
        "requested snapshot. Please note: The snapshot may no longer be available based on configured "
        "snapshot policies.")


def test_revert_while_a_snapshot_of_the_volume_has_an_operation_is_409_conflict(store):
    create(store)
    s = make_snapshot(store, "s1")
    busy = make_snapshot(store, "s2", status=None)  # 생성 작업이 열려 있다
    e = arm_error(revert, store, {"snapshotId": s.id})
    assert (e.status, e.code) == (409, "Conflict")
    assert e.message == (f"Cannot revert volume '{VOL}' because an operation is in progress on its snapshot "
                         f"'{busy.id}'. Wait until it is finished, and then retry.")


def test_revert_to_a_failed_snapshot_is_400(store):
    create(store)
    s = make_snapshot(store, "s1", status="Failed")
    e = arm_error(revert, store, {"snapshotId": s.id})
    assert (e.status, e.code) == (400, "BadRequest")
    assert e.message == (f"Volume cannot be reverted to snapshot '{s.id}' because the snapshot isn't in "
                         "state succeeded.")


def test_revert_handler_reverts_and_drops_the_snapshots_the_agent_no_longer_has(store):
    v = create(store)
    older, chosen, newer = (make_snapshot(store, n) for n in ("s1", "s2", "s3"))
    storage = FakeStorage()
    storage.remaining = {older.properties["snapshotId"], chosen.properties["snapshotId"]}
    op = revert(store, {"snapshotId": chosen.id})

    assert run_operation(store, storage, op).status == "Succeeded"

    # 작업 ID가 agent의 멱등 키다 (결정 4)
    assert storage.calls == [("revert", v.properties["fileSystemId"], chosen.properties["snapshotId"], op.id,
                              "corr-7")]
    assert store.get_resource(v.id).provisioning_state == "Succeeded"
    # 더 새 스냅샷은 agent가 지웠고 ARM 목록에서도 사라진다 (결정 8)
    assert [s.name for s in store.list_children(v.id, snapshots.SNAPSHOT_TYPE)] == ["s1", "s2"]
    assert store.get_resource(newer.id) is None
    assert store.get_resource(chosen.id).properties == chosen.properties


def test_failed_revert_fails_the_volume_and_keeps_the_snapshots(store):
    v = create(store)
    s1 = make_snapshot(store, "s1")
    make_snapshot(store, "s2")
    storage = FakeStorage()
    storage.error = RuntimeError("lvconvert failed")
    op = revert(store, {"snapshotId": s1.id})

    done = run_operation(store, storage, op)

    assert (done.status, done.error["code"]) == ("Failed", "InternalServerError")
    assert store.get_resource(v.id).provisioning_state == "Failed"
    assert [s.name for s in store.list_children(v.id, snapshots.SNAPSHOT_TYPE)] == ["s1", "s2"]


def test_failed_volume_after_a_revert_recovers_with_put(store):
    # 실패한 되돌리기 뒤 같은 볼륨 PUT이 agent 볼륨을 다시 보장한다 (결정 2)
    v = create(store)
    s = make_snapshot(store, "s1")
    storage = FakeStorage()
    storage.remaining = {s.properties["snapshotId"]}
    storage.error = RuntimeError("agent down")
    run_operation(store, storage, revert(store, {"snapshotId": s.id}))
    storage.error = None
    _, _, op = put(store, body())
    assert run_operation(store, storage, op).status == "Succeeded"
    assert store.get_resource(v.id).provisioning_state == "Succeeded"
    assert revert(store, {"snapshotId": s.id}).status == "Reverting"


def test_volume_put_drops_the_snapshots_the_agent_no_longer_has(store):
    # 볼륨 PUT이 agent에서 실패한 되돌리기를 끝내면 더 새 스냅샷이 지워진다. ARM 목록도 맞춘다 (결정 2·8)
    v = create(store)
    kept, gone = make_snapshot(store, "s1"), make_snapshot(store, "s2")
    make_snapshot(store, "s3", status="Failed")  # 데이터가 없는 실패 행은 사용자가 지운다
    make_snapshot(store, "s4", status=None)  # 작업 중인 행은 그 작업이 끝낸다
    storage = FakeStorage()
    storage.remaining = {kept.properties["snapshotId"]}
    _, _, op = put(store, body())

    assert run_operation(store, storage, op).status == "Succeeded"

    assert ("snapshots", v.properties["fileSystemId"], "corr-1") in storage.calls
    assert [s.name for s in store.list_children(v.id, snapshots.SNAPSHOT_TYPE)] == ["s1", "s3", "s4"]
    assert store.get_resource(gone.id) is None


# --- 스냅샷에서 새 볼륨 (FR-07, 복원 설계 §4) ---

VOL2 = POOL + "/volumes/vol2"
SNAPSHOT_ID_FORMAT = (
    "The 'properties.snapshotId' property must be a snapshot resource ID: /subscriptions/{id}/resourceGroups/{group}"
    "/providers/Microsoft.NetApp/netAppAccounts/{account}/capacityPools/{pool}/volumes/{volume}/snapshots/{snapshot}.")


def source(store, **kw):
    """원본 볼륨 vol1(기본 100 GiB, NFSv3, 0770)과 스냅샷 s1."""
    v = create(store, **kw)
    return v, make_snapshot(store, "s1")


def put_from(store, snapshot_id, name="vol2", pool="pool1", **props):
    return put(store, body(token=name, snapshotId=snapshot_id, **props), name, pool)


def set_state(store, rid, state):
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        res.provisioning_state = state
        tx.put_resource(res)


def test_create_from_snapshot_is_creating_with_the_snapshot_id(store):
    v, s = source(store, protocolTypes=["NFSv4.1"], unixPermissions="0755")

    created, res, op = put_from(store, s.id)

    assert created and (op.action, op.status) == ("CREATE", "Creating")  # 일반 볼륨 생성과 같다 (결정 1)
    props = volumes.volume_body(res)["properties"]
    assert props["provisioningState"] == "Creating"
    assert props["snapshotId"] == s.id
    assert "originatingResourceId" not in props and "cloneProgress" not in props
    assert props["fileSystemId"] != v.properties["fileSystemId"]
    # 주지 않은 protocolTypes·unixPermissions는 원본 볼륨 값이다 (결정 3)
    assert (props["protocolTypes"], props["unixPermissions"]) == (["NFSv4.1"], "0755")
    assert props["exportPolicy"] == {"rules": [default_rule(nfsv3=False, nfsv41=True)]}


def test_create_from_snapshot_in_another_pool_with_another_protocol(store):
    # 같은 계정이면 어느 풀이든 된다. 서비스 수준은 자기 풀을 따른다 (결정 2·3)
    _, s = source(store)
    make_pool(store, "pool2", level="Standard")
    _, res, _ = put_from(store, s.id.upper(), pool="pool2", protocolTypes=["NFSv4.1"], unixPermissions="0700")
    props = res.properties
    assert props["serviceLevel"] == "Standard"
    assert (props["protocolTypes"], props["unixPermissions"]) == (["NFSv4.1"], "0700")
    assert props["snapshotId"] == s.id  # 대소문자가 달라도 저장된 스냅샷 ID를 남긴다


@pytest.mark.parametrize("value", [5, "s1", VOL, VOL + "/snapshots/s1/x", SUBNET])
def test_snapshot_id_must_be_a_snapshot_resource_id(store, value):
    source(store)
    e = arm_error(put_from, store, value, pool="nopool")  # 본문 검사가 풀 검사보다 먼저다 (결정 13)
    assert (e.status, e.code, e.message) == (400, "InvalidRequestContent", SNAPSHOT_ID_FORMAT)
    assert store.get_resource(POOL + "/volumes/vol2") is None


def test_delete_base_snapshot_must_be_a_boolean(store):
    _, s = source(store)
    e = arm_error(put_from, store, s.id, deleteBaseSnapshot="yes")
    assert (e.status, e.code) == (400, "InvalidRequestContent")


@pytest.mark.parametrize("other", [
    VOL.replace("acc1", "acc2") + "/snapshots/s1",
    VOL.replace("rg1", "rg2") + "/snapshots/s1",
    VOL.replace("/subscriptions/s1/", "/subscriptions/s2/") + "/snapshots/s1",
])
def test_snapshot_of_another_account_is_bad_request(store, other):
    source(store)
    e = arm_error(put_from, store, other)
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", f"The snapshot '{other}' must be in the same NetApp account as the new volume '{VOL2}'.")
    assert store.active_operations() == []


def test_missing_snapshot_is_404_with_the_snapshot_wording(store):
    source(store)
    e = arm_error(put_from, store, VOL + "/snapshots/nosuch")
    assert (e.status, e.code) == (404, "ResourceNotFound")
    assert e.message.startswith("The requested snapshot 'nosuch' was not found on the volume 'acc1/pool1/vol1'.")


def test_operation_in_progress_on_the_snapshot_or_its_volume_is_409(store):
    v = create(store)
    busy = make_snapshot(store, "s1", status=None)  # 생성 작업이 열려 있다
    e = arm_error(put_from, store, busy.id)
    assert (e.status, e.code, e.message) == (
        409, "Conflict", f"Cannot create volume '{VOL2}' from snapshot '{busy.id}' because an operation is in "
                         f"progress on '{busy.id}'. Wait until it is finished, and then retry.")
    finish(store, store.active_operations()[0])
    patch(store, {"tags": {"a": "b"}})  # 원본 볼륨에 Patching 작업
    e = arm_error(put_from, store, busy.id)
    assert (e.status, e.code) == (409, "Conflict")
    assert f"because an operation is in progress on '{v.id}'." in e.message


def test_snapshot_not_succeeded_is_bad_request(store):
    create(store)
    s = make_snapshot(store, "s1", status="Failed")
    e = arm_error(put_from, store, s.id)
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", f"Volume cannot be created from snapshot '{s.id}' because the snapshot isn't in state "
                           "succeeded.")


def test_source_volume_not_succeeded_is_bad_request(store):
    v, s = source(store)
    set_state(store, v.id, "Failed")
    e = arm_error(put_from, store, s.id)
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", f"Volume cannot be created from snapshot '{s.id}' because its volume isn't in state "
                           "succeeded.")


def test_new_volume_must_be_at_least_the_source_size(store):
    # ext4 축소는 오프라인뿐이다. 같거나 크면 된다 (결정 4)
    _, s = source(store)
    e = arm_error(put_from, store, s.id, size=50 * GIB)
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", "The 'properties.usageThreshold' of a volume created from a snapshot must be at least the "
                           "source volume's 100 GiB.")
    put_from(store, s.id, size=200 * GIB)


def test_new_volume_reserves_its_quota_in_its_pool(store):
    _, s = source(store, size=3 * TIB)
    e = arm_error(put_from, store, s.id, size=3 * TIB)
    assert (e.status, e.code, e.message) == (400, "BadRequest", "Pool size too small for total volume size.")


def restored(store, storage=None, **props):
    """vol1의 s1에서 vol2를 만들고 생성 작업을 처리기로 끝낸다."""
    _, s = source(store)
    _, res, op = put_from(store, s.id, **props)
    run_operation(store, storage or FakeStorage(), op)
    return store.get_resource(res.id), s


def test_snapshot_id_cannot_change(store):
    n, s = restored(store)
    other = make_snapshot(store, "s2")
    for fn in (put, patch):
        e = arm_error(fn, store, body(token="vol2", snapshotId=other.id), "vol2")
        assert (e.status, e.code, e.message) == (400, "BadRequest", "SnapshotId cannot be changed.")
    # 같은 값(대소문자 무시)은 받는다 (결정 12)
    created, _, op = put(store, body(token="vol2", snapshotId=s.id.upper()), "vol2")
    assert (created, op.action) == (False, "UPDATE")


def test_snapshot_id_cannot_be_added_to_an_existing_volume(store):
    _, s = source(store)
    for fn in (put, patch):
        e = arm_error(fn, store, body(snapshotId=s.id))
        assert (e.status, e.code, e.message) == (400, "BadRequest", "SnapshotId cannot be changed.")


def test_put_back_the_get_body_of_a_restored_volume(store):
    # originatingResourceId는 읽기 전용이라 무시하고, snapshotId는 같은 값이다
    n, _ = restored(store)
    b = volumes.volume_body(n)
    for key in ("id", "name", "type"):
        b.pop(key)
    created, _, _ = put(store, b, "vol2")
    assert created is False


def test_create_handler_clones_and_records_the_base_snapshot(store):
    storage = FakeStorage()
    storage.records = [{"uuid": "5b000000-0000-4000-8000-000000000001", "name": "s1",
                        "create_time": "2026-11-08T23:07:12Z", "volume": {"uuid": "x"}}]
    v, s = source(store, unixPermissions="0755")
    _, res, op = put_from(store, s.id)
    fsid = res.properties["fileSystemId"]

    assert run_operation(store, storage, op).status == "Succeeded"

    # agent에 원본 볼륨 uuid와 원본 스냅샷 uuid를 넘긴다 (결정 14)
    clone = (v.properties["fileSystemId"], s.properties["snapshotId"])
    assert storage.calls == [("ensure", fsid, "/vol2", 100 * GIB, 755, "nfs3", "corr-1", clone),
                             ("snapshot_records", fsid, "corr-1")]
    props = volumes.volume_body(store.get_resource(res.id))["properties"]
    assert props["provisioningState"] == "Succeeded"
    assert props["originatingResourceId"] == s.id  # 끝나면 같은 ARM ID (결정 1)
    assert props["mountTargets"] == [{"mountTargetId": fsid, "fileSystemId": fsid, "ipAddress": "172.30.0.129"}]
    # base 스냅샷 행: Creating을 거치지 않고 Succeeded로 생긴다 (결정 7)
    base = store.list_children(res.id, snapshots.SNAPSHOT_TYPE)
    assert [b.id for b in base] == [VOL2 + "/snapshots/s1"]
    assert base[0].provisioning_state == "Succeeded"
    assert snapshots.snapshot_body(base[0])["properties"] == {
        "provisioningState": "Succeeded", "snapshotId": "5b000000-0000-4000-8000-000000000001",
        "created": "2026-11-08T23:07:12Z"}
    assert (base[0].location, base[0].tags) == ("westus2", {})


def test_failed_clone_keeps_protecting_the_source_and_put_finishes_it(store):
    storage = FakeStorage()
    storage.error = RuntimeError("agent job failed")
    n, s = restored(store, storage)
    assert n.provisioning_state == "Failed"
    assert "originatingResourceId" not in n.properties
    assert store.list_children(n.id, snapshots.SNAPSHOT_TYPE) == []
    # 같은 PUT이 agent에서 남은 단계를 끝낸다 (결정 10). 그때도 클론 필드를 넘긴다
    storage.error = None
    _, _, op = put(store, body(token="vol2"), "vol2")
    assert run_operation(store, storage, op).status == "Succeeded"
    assert storage.calls[-2][-1] == (store.get_resource(VOL).properties["fileSystemId"], s.properties["snapshotId"])
    assert store.get_resource(n.id).properties["originatingResourceId"] == s.id


def test_finished_restored_volume_is_ensured_as_an_ordinary_volume(store):
    # originatingResourceId가 있으면 원본을 찾지 않는다. 원본이 지워졌어도 다시 PUT할 수 있다
    storage = FakeStorage()
    n, s = restored(store, storage)
    store_delete(store, s)
    storage.calls.clear()
    _, _, op = put(store, body(token="vol2"), "vol2")
    assert run_operation(store, storage, op).status == "Succeeded"
    assert storage.calls[0][-1] is None
    assert "snapshot_records" not in [c[0] for c in storage.calls]


def store_delete(store, res):
    with store.transaction() as tx:
        tx.delete_resource(res.id)


PROTECTED = ("Cannot {} '{}' because volume '" + VOL2 + "' is being created from snapshot '{}'. Wait until it is "
             "created, or delete it, and then retry.")


@pytest.mark.parametrize("state", ["Creating", "Failed"])
def test_source_volume_cannot_be_deleted_or_reverted_until_the_new_volume_is_created(store, state):
    # 원본 보호 (결정 9): 새 볼륨이 한 번도 Succeeded가 되지 않은 동안
    v, s = source(store)
    _, _, op = put_from(store, s.id)
    if state == "Failed":
        finish(store, op, "Failed")
    e = arm_error(delete, store)
    assert (e.status, e.code, e.message) == (409, "Conflict", PROTECTED.format("delete", v.id, s.id))
    e = arm_error(revert, store, {"snapshotId": s.id})
    assert (e.status, e.code, e.message) == (409, "Conflict", PROTECTED.format("revert", v.id, s.id))
    assert store.get_resource(v.id).provisioning_state == "Succeeded"


def test_source_is_free_once_the_new_volume_is_created_or_deleted(store):
    restored(store)  # vol1의 s1에서 만든 vol2가 끝났다
    assert revert(store, {"snapshotId": VOL + "/snapshots/s1"}).status == "Reverting"
    # 끝나지 않은 새 볼륨을 지우면 보호가 풀린다
    create(store, "vol3", token="vol3")
    t1 = make_snapshot(store, "t1", volume="vol3")
    _, res, op = put_from(store, t1.id, name="vol4")
    finish(store, op, "Failed")
    store_delete(store, res)
    assert volumes.delete_volume(store, "s1", "rg1", "acc1", "pool1", "vol3", None).status == "Deleting"
