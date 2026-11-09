"""스냅샷 (FR-05): 본문 규칙, 응답 본문, 작업 흐름, 부모·개수 규칙, 처리기 (스냅샷 설계 §3 결정 3·9~12, §4).

처리기는 가짜 agent 클라이언트로 확인한다. 실제 agent 호출은 test_storage_client.py가 확인한다.
"""

import asyncio
import uuid

import pytest

import anf_api.accounts as accounts
import anf_api.capacity_pools as pools
import anf_api.snapshots as snapshots
import anf_api.volumes as volumes
from anf_api.arm_rules import SNAPSHOT_TYPE, ArmError
from anf_api.lro import LroWorker

GIB = 1 << 30
TIB = 1 << 40
ACC = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
VOL = ACC + "/capacityPools/pool1/volumes/vol1"
SNAP = VOL + "/snapshots/snap1"
SUBNET = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.Network/virtualNetworks/vnet1/subnets/anf"


def finish(store, op, status="Succeeded"):
    """워커가 작업을 끝낸 것처럼 만든다 (생성·갱신)."""
    with store.transaction() as tx:
        res = tx.get_resource(op.resource_id)
        res.provisioning_state = status
        tx.put_resource(res)
        tx.finish_operation(op.id, status)


def make_volume(store, name="vol1", state="Succeeded"):
    _, _, op = volumes.put_volume(store, "s1", "rg1", "acc1", "pool1", name, {
        "location": "westus2",
        "properties": {"creationToken": name, "usageThreshold": 100 * GIB, "subnetId": SUBNET}}, None)
    if state in ("Succeeded", "Failed"):
        finish(store, op, state)
    else:  # 진행 중: 작업은 열어 두고 볼륨 상태만 바꾼다
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
    _, _, op = pools.put_pool(s, "s1", "rg1", "acc1", "pool1", {
        "location": "westus2", "properties": {"size": 4 * TIB, "serviceLevel": "Premium"}}, None)
    finish(s, op)
    make_volume(s)
    return s


def put(store, body=None, name="snap1", volume="vol1"):
    return snapshots.put_snapshot(store, "s1", "rg1", "acc1", "pool1", volume, name,
                                  {"location": "westus2"} if body is None else body, "corr-1")


def delete(store, name="snap1", volume="vol1"):
    return snapshots.delete_snapshot(store, "s1", "rg1", "acc1", "pool1", volume, name, "corr-2")


def create(store, name="snap1", status="Succeeded", volume="vol1"):
    _, res, op = put(store, name=name, volume=volume)
    finish(store, op, status)
    return store.get_resource(res.id)


def arm_error(fn, *args, **kw):
    with pytest.raises(ArmError) as e:
        fn(*args, **kw)
    return e.value


# --- 생성과 본문 ---


def test_create_is_creating_with_create_operation(store):
    created, res, op = put(store)
    assert created is True
    assert (res.id, res.type, res.parent_id) == (SNAP, SNAPSHOT_TYPE, VOL)
    assert res.provisioning_state == "Creating"
    assert (op.action, op.status, op.correlation_id) == ("CREATE", "Creating", "corr-1")
    # snapshotId는 anf-api가 만든 UUID다. agent에 멱등 키로 넘긴다 (결정 9)
    assert str(uuid.UUID(res.properties["snapshotId"])) == res.properties["snapshotId"]


def test_snapshot_body_before_and_after_success(store):
    # snapshotId·created는 생성 작업이 성공한 뒤에 나온다 (녹화 R1). tags는 없다
    _, res, _ = put(store)
    assert snapshots.snapshot_body(res) == {
        "id": SNAP, "name": "acc1/pool1/vol1/snap1",
        "type": "Microsoft.NetApp/netAppAccounts/capacityPools/volumes/snapshots",
        "location": "westus2", "properties": {"provisioningState": "Creating"},
    }
    res.properties = {**res.properties, "created": "2026-11-08T23:07:12Z"}
    res.provisioning_state = "Succeeded"
    assert snapshots.snapshot_body(res)["properties"] == {
        "provisioningState": "Succeeded", "snapshotId": res.properties["snapshotId"], "created": "2026-11-08T23:07:12Z"}


@pytest.mark.parametrize("body", [
    {"location": "westus2", "properties": {}},
    {"location": "westus2", "properties": {"provisioningState": "x", "snapshotId": "x", "created": "x"}},
    {"location": "westus2", "id": "x", "name": "x", "type": "x", "systemData": {}},
])
def test_read_only_keys_are_ignored(store, body):
    created, res, _ = put(store, body)
    assert created and res.properties.keys() == {"snapshotId"}


@pytest.mark.parametrize("body", [
    [], {}, {"location": 1}, {"location": ""},
    {"location": "westus2", "tags": {}},  # 스냅샷 모델에는 tags가 없다 (결정 12)
    {"location": "westus2", "properties": []},
    {"location": "westus2", "properties": None},
    {"location": "westus2", "properties": {"fileSystemId": "x"}},
    {"location": "westus2", "other": 1},
])
def test_malformed_body_is_invalid_request_content(store, body):
    e = arm_error(put, store, body)
    assert (e.status, e.code) == (400, "InvalidRequestContent")
    assert store.get_resource(SNAP) is None


@pytest.mark.parametrize("name", [".a", "-a", "a b", "a" * 256])
def test_invalid_snapshot_name(store, name):
    e = arm_error(put, store, name=name)
    assert (e.status, e.code) == (400, "InvalidResourceName")


def test_name_is_checked_before_the_body(store):
    e = arm_error(put, store, [], name=".a")
    assert e.code == "InvalidResourceName"


# --- 부모 볼륨 규칙 (결정 11) ---


def test_missing_volume_is_parent_resource_not_found(store):
    e = arm_error(put, store, volume="nope")
    assert (e.status, e.code) == (404, "ParentResourceNotFound")
    assert e.message == (
        "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools/volumes/snapshots', "
        f"because the parent resource '{ACC}/capacityPools/pool1/volumes/nope' could not be found.")


def test_volume_being_deleted_is_conflict(store):
    create(store, "old")
    volumes.delete_volume(store, "s1", "rg1", "acc1", "pool1", "vol1", None)
    for fn, name in ((put, "snap1"), (put, "old"), (delete, "old")):
        e = arm_error(fn, store, name=name)
        assert (e.status, e.code) == (409, "Conflict")
        assert e.message == (f"Cannot create or delete snapshot '{VOL}/snapshots/{name}' because its parent "
                             f"volume '{VOL}' is being deleted.")


def test_existing_snapshot_of_a_reverting_volume_is_conflict(store):
    # 되돌리기가 더 새 스냅샷을 지우는 동안 기존 스냅샷을 다시 만들거나 지우지 못한다 (되돌리기 설계 결정 7)
    old = create(store, "old")
    with store.transaction() as tx:
        vol = tx.get_resource(VOL)
        vol.provisioning_state = "Reverting"
        tx.put_resource(vol)
    for fn in (put, delete):
        e = arm_error(fn, store, name="old")
        assert (e.status, e.code) == (409, "Conflict")
        assert e.message == (f"Cannot change snapshot '{old.id}' because its parent volume '{VOL}' "
                             "is being reverted.")
    # 새 스냅샷은 기존 규칙대로 400 (ONTAP 1638532의 자리)
    e = arm_error(put, store, name="new")
    assert (e.status, e.code) == (400, "BadRequest")
    assert delete(store, name="new") is None
    assert store.active_operations() == []


@pytest.mark.parametrize("state", ["Creating", "Updating", "Patching", "Failed", "Reverting"])
def test_volume_not_succeeded_is_bad_request(store, state):
    make_volume(store, "vol2", state)
    e = arm_error(put, store, volume="vol2")
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", "Snapshot cannot be created on a volume that isn't in state succeeded.")


def test_at_most_255_snapshots_per_volume(store):
    for i in range(snapshots.MAX_SNAPSHOTS):
        create(store, f"s{i}")
    e = arm_error(put, store, name="one-more")
    assert (e.status, e.code, e.message) == (
        400, "BadRequest", "Cannot exceed maximum number of snapshots (255) for the volume.")
    make_volume(store, "vol2")
    put(store, name="one-more", volume="vol2")  # 한도는 볼륨마다다


# --- 다시 PUT (결정 3) ---


def test_put_again_is_an_update(store):
    snap = create(store)
    created, res, op = put(store)
    assert created is False
    assert res.provisioning_state == "Updating"
    assert (op.action, op.status) == ("UPDATE", "Updating")
    assert res.properties["snapshotId"] == snap.properties["snapshotId"]


def test_failed_snapshot_can_be_put_again(store):
    create(store, status="Failed")
    assert put(store)[0] is False


def test_put_again_ignores_name_case(store):
    create(store)
    _, res, _ = put(store, name="SNAP1")
    assert res.name == "snap1"


def test_put_again_with_other_location_is_conflict(store):
    create(store)
    e = arm_error(put, store, {"location": "eastus"})
    assert (e.status, e.code) == (409, "InvalidResourceLocation")


def test_snapshot_with_operation_in_progress_is_409(store):
    put(store)  # Creating
    for fn in (put, delete):
        e = arm_error(fn, store)
        assert (e.status, e.code) == (409, "AnotherOperationInProgress")


# --- DELETE, GET, 목록 ---


def test_delete(store):
    create(store)
    op = delete(store)
    assert (op.action, op.status, op.correlation_id) == ("DELETE", "Deleting", "corr-2")
    assert store.get_resource(SNAP).provisioning_state == "Deleting"


def test_delete_missing_snapshot_is_none(store):
    assert delete(store) is None
    assert delete(store, volume="nope") is None


def test_get(store):
    create(store)
    assert snapshots.get_snapshot(store, "s1", "rg1", "acc1", "pool1", "vol1", "SNAP1").id == SNAP


def test_get_missing_snapshot_uses_the_anf_message(store):
    e = arm_error(snapshots.get_snapshot, store, "s1", "rg1", "acc1", "pool1", "vol1", "nope")
    assert (e.status, e.code) == (404, "ResourceNotFound")
    assert e.message == (  # 녹화 R1
        "The requested snapshot 'nope' was not found on the volume 'acc1/pool1/vol1'. Please check the "
        "requested snapshot. Please note: The snapshot may no longer be available based on configured "
        "snapshot policies.")


def test_list_is_sorted_by_name(store):
    create(store, "b")
    create(store, "A")
    make_volume(store, "vol2")
    create(store, "c", volume="vol2")
    assert [r.name for r in snapshots.list_snapshots(store, "s1", "rg1", "acc1", "pool1", "vol1")] == ["A", "b"]


def test_list_of_a_missing_volume_is_not_found(store):
    e = arm_error(snapshots.list_snapshots, store, "s1", "rg1", "acc1", "pool1", "nope")
    assert (e.status, e.code) == (404, "ResourceNotFound")


# --- 스냅샷에서 새 볼륨을 만드는 동안 원본 보호 (복원 설계 결정 9) ---

NEW = ACC + "/capacityPools/pool1/volumes/vol2"


def put_new_volume(store, snapshot_id):
    _, res, op = volumes.put_volume(store, "s1", "rg1", "acc1", "pool1", "vol2", {
        "location": "westus2", "properties": {"creationToken": "vol2", "usageThreshold": 100 * GIB,
                                              "subnetId": SUBNET, "snapshotId": snapshot_id}}, None)
    return res, op


@pytest.mark.parametrize("state", ["Creating", "Failed"])
def test_source_snapshot_cannot_be_deleted_until_the_new_volume_is_created(store, state):
    # 새 볼륨이 한 번도 Succeeded가 되지 않은 동안(originatingResourceId가 없는 동안)이다
    s = create(store)
    other = create(store, "snap2")
    _, op = put_new_volume(store, s.id)
    if state == "Failed":
        finish(store, op, "Failed")
    e = arm_error(delete, store)
    assert (e.status, e.code, e.message) == (
        409, "Conflict", f"Cannot delete '{s.id}' because volume '{NEW}' is being created from snapshot '{s.id}'. "
                         "Wait until it is created, or delete it, and then retry.")
    assert store.get_resource(s.id).provisioning_state == "Succeeded"
    assert delete(store, "snap2").status == "Deleting"  # 다른 스냅샷은 지울 수 있다
    assert store.get_resource(other.id).provisioning_state == "Deleting"


def test_source_snapshot_can_be_deleted_once_the_new_volume_is_created(store):
    s = create(store)
    res, op = put_new_volume(store, s.id)
    with store.transaction() as tx:  # 처리기가 생성을 끝내면 originatingResourceId를 쓴다
        new = tx.get_resource(res.id)
        new.properties = {**new.properties, "originatingResourceId": s.id}
        new.provisioning_state = "Succeeded"
        tx.put_resource(new)
        tx.finish_operation(op.id, "Succeeded")
    assert delete(store).status == "Deleting"


# --- 볼륨 DELETE와 스냅샷 (결정 2) ---


def test_volume_delete_removes_its_snapshot_rows(store):
    # 진행 중인 스냅샷 작업이 있으면 볼륨 DELETE가 409다: test_volumes.py
    create(store, "a")
    create(store, "b")
    op = volumes.delete_volume(store, "s1", "rg1", "acc1", "pool1", "vol1", None)
    asyncio.run(LroWorker(store, volumes.make_handlers(store, FakeStorage()))._process(op))
    assert store.get_resource(VOL) is None
    assert store.get_resource(VOL + "/snapshots/a") is None
    assert store.get_resource(VOL + "/snapshots/b") is None


# --- 처리기 ---


class FakeStorage:
    """agent 클라이언트 흉내. 실패를 정하면 StorageError처럼 예외를 던진다."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    async def ensure_snapshot(self, *args, correlation_id=None):
        self.calls.append(("ensure", *args, correlation_id))
        if self.error:
            raise self.error
        return "2026-11-08T23:07:12Z"

    async def delete_snapshot(self, *args, correlation_id=None):
        self.calls.append(("delete", *args, correlation_id))
        if self.error:
            raise self.error

    async def delete_volume(self, *args, correlation_id=None):
        self.calls.append(("delete_volume", *args, correlation_id))


def run_operation(store, storage, op):
    asyncio.run(LroWorker(store, snapshots.make_handlers(store, storage))._process(op))
    return store.get_operation(op.id)


def file_system_id(store):
    return store.get_resource(VOL).properties["fileSystemId"]


def test_handlers_cover_all_snapshot_operations(store):
    assert set(snapshots.make_handlers(store, FakeStorage())) == {
        (SNAPSHOT_TYPE, a) for a in ("CREATE", "UPDATE", "DELETE")}


def test_create_ensures_the_snapshot_and_records_created(store):
    storage = FakeStorage()
    _, res, op = put(store)
    assert run_operation(store, storage, op).status == "Succeeded"
    snap_id = res.properties["snapshotId"]
    assert storage.calls == [("ensure", file_system_id(store), snap_id, "snap1", "corr-1")]
    assert snapshots.snapshot_body(store.get_resource(SNAP))["properties"] == {
        "provisioningState": "Succeeded", "snapshotId": snap_id, "created": "2026-11-08T23:07:12Z"}


def test_update_ensures_the_snapshot_again(store):
    # 생성이 실패한 스냅샷도 다시 PUT하면 데이터 플레인까지 완성된다 (결정 3)
    create(store, status="Failed")
    storage = FakeStorage()
    _, _, op = put(store)
    assert run_operation(store, storage, op).status == "Succeeded"
    assert [c[0] for c in storage.calls] == ["ensure"]
    assert store.get_resource(SNAP).properties["created"] == "2026-11-08T23:07:12Z"


def test_failed_storage_work_fails_the_snapshot(store):
    storage = FakeStorage()
    storage.error = RuntimeError("A snapshot with the specified name already exists.")
    _, _, op = put(store)
    done = run_operation(store, storage, op)
    assert (done.status, done.error["code"]) == ("Failed", "InternalServerError")
    snap = store.get_resource(SNAP)
    assert snap.provisioning_state == "Failed"
    assert "snapshotId" not in snapshots.snapshot_body(snap)["properties"]


def test_delete_removes_the_agent_snapshot(store):
    snap = create(store)
    storage = FakeStorage()
    op = delete(store)
    assert run_operation(store, storage, op).status == "Succeeded"
    assert storage.calls == [("delete", file_system_id(store), snap.properties["snapshotId"], "corr-2")]
    assert store.get_resource(SNAP) is None


def test_failed_delete_keeps_the_snapshot(store):
    create(store)
    storage = FakeStorage()
    storage.error = RuntimeError("umount: target is busy")
    op = delete(store)
    assert run_operation(store, storage, op).status == "Failed"
    assert store.get_resource(SNAP).provisioning_state == "Failed"
