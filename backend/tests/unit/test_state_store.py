"""SQLite 상태 저장소: 리소스·작업 저장, 트랜잭션, 리소스당 진행 중 작업 하나 (계정 설계 §6.1)."""

import pytest

from anf_api.arm_rules import ArmError
from anf_api.state_store import Resource, StateStore

ACC = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
TYPE = "Microsoft.NetApp/netAppAccounts"


def make_account(id=ACC, rg="rg1", name="acc1", state="Creating", **kw):
    return Resource(
        id=id, type=TYPE, subscription_id="s1", resource_group=rg, name=name,
        location="westus2", tags={"a": "1"}, properties={}, provisioning_state=state, **kw,
    )


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "nested" / "anf.db")


def test_put_and_get_resource_round_trips(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
    got = store.get_resource(ACC)
    assert got.name == "acc1"
    assert got.tags == {"a": "1"}
    assert got.provisioning_state == "Creating"
    assert got.parent_id is None


def test_resource_lookup_ignores_case_but_keeps_original_id(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
    got = store.get_resource(ACC.upper())
    assert got is not None
    assert got.id == ACC


def test_put_resource_replaces_existing(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
    with store.transaction() as tx:
        tx.put_resource(make_account(state="Succeeded"))
    assert store.get_resource(ACC).provisioning_state == "Succeeded"


def test_list_filters_by_type_subscription_and_resource_group(store):
    other = ACC.replace("rg1", "rg2").replace("acc1", "acc2")
    with store.transaction() as tx:
        tx.put_resource(make_account())
        tx.put_resource(make_account(id=other, rg="rg2", name="acc2"))
    assert [r.name for r in store.list_resources(TYPE, "s1")] == ["acc1", "acc2"]
    assert [r.name for r in store.list_resources(TYPE, "S1", "RG1")] == ["acc1"]
    assert store.list_resources(TYPE, "s2") == []


def test_all_of_type_spans_subscriptions(store):
    # 볼륨 경로(creationToken)는 클론 전체에서 유일하다 (볼륨 설계 결정 15)
    other = ACC.replace("s1", "s2").replace("acc1", "acc2")
    with store.transaction() as tx:
        tx.put_resource(make_account())
        tx.put_resource(Resource(
            id=other, type=TYPE, subscription_id="s2", resource_group="rg1", name="acc2",
            location="westus2", tags={}, properties={}, provisioning_state="Succeeded"))
        assert [r.id for r in tx.all_of_type(TYPE)] == [ACC, other]
        assert tx.all_of_type(TYPE + "/capacityPools") == []


def test_child_ids_returns_resources_with_parent(store):
    pool = ACC + "/capacityPools/p1"
    with store.transaction() as tx:
        tx.put_resource(make_account())
        tx.put_resource(Resource(
            id=pool, type=TYPE + "/capacityPools", subscription_id="s1", resource_group="rg1",
            name="p1", location="westus2", tags={}, properties={},
            provisioning_state="Succeeded", parent_id=ACC,
        ))
    with store.transaction() as tx:
        assert tx.child_ids(ACC.upper()) == [pool]


def make_pool(name, state="Succeeded", type=TYPE + "/capacityPools"):
    return Resource(
        id=f"{ACC}/capacityPools/{name}", type=type, subscription_id="s1", resource_group="rg1",
        name=name, location="westus2", tags={}, properties={}, provisioning_state=state,
        parent_id=ACC,
    )


def test_list_children_filters_by_parent_and_type(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
        tx.put_resource(make_pool("p2"))
        tx.put_resource(make_pool("p1", state="Creating"))
        tx.put_resource(make_pool("x", type="Other/type"))
    assert [r.name for r in store.list_children(ACC.upper(), TYPE + "/capacityPools")] == ["p1", "p2"]
    with store.transaction() as tx:
        assert [r.name for r in tx.list_children(ACC, "Other/type")] == ["x"]
    assert store.list_children(ACC + "x", TYPE + "/capacityPools") == []


def test_ensure_no_children_passes_without_children(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
        tx.ensure_no_children(ACC)


def test_ensure_no_children_is_409_cannot_delete_resource_with_nested_ids(store):
    """녹화 R4·N5의 메시지 형식: 경로의 `/providers/` 뒤만 따옴표로 묶어 나열한다. 상태와 무관하다."""
    with store.transaction() as tx:
        tx.put_resource(make_account())
        tx.put_resource(make_pool("p1", state="Deleting"))
    with pytest.raises(ArmError) as e, store.transaction() as tx:
        tx.ensure_no_children(ACC)
    assert (e.value.status, e.value.code) == (409, "CannotDeleteResource")
    assert e.value.message == (
        "Cannot delete resource while nested resources exist. Some existing nested resource IDs "
        "include: 'Microsoft.NetApp/netAppAccounts/acc1/capacityPools/p1'. Please delete all "
        "nested resources before deleting this resource."
    )


def test_delete_resource(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
    with store.transaction() as tx:
        tx.delete_resource(ACC)
    assert store.get_resource(ACC) is None


def test_delete_resource_deletes_nested_resources(store):
    # 볼륨을 지우면 스냅샷도 지워진다 (스냅샷 설계 결정 2). 계정·풀은 DELETE 전에 자식을 409로 막는다
    nested = make_pool("p1")
    nested_child = Resource(
        id=nested.id + "/volumes/v1", type=nested.type + "/volumes", subscription_id="s1", resource_group="rg1",
        name="v1", location="westus2", tags={}, properties={}, provisioning_state="Succeeded",
        parent_id=nested.id.upper(),
    )
    other = make_pool("p2")
    with store.transaction() as tx:
        for res in (make_account(), nested, nested_child, other):
            tx.put_resource(res)
    with store.transaction() as tx:
        tx.delete_resource(nested.id)
    assert store.get_resource(nested.id) is None
    assert store.get_resource(nested_child.id) is None
    assert store.get_resource(other.id) is not None
    assert store.get_resource(ACC) is not None


def test_transaction_rolls_back_on_error(store):
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.put_resource(make_account())
            raise RuntimeError("boom")
    assert store.get_resource(ACC) is None


def test_create_operation_records_in_progress_operation(store):
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        op = tx.create_operation(res, "CREATE", "Creating", correlation_id="corr-1")
    got = store.get_operation(op.id)
    assert got.status == "Creating"
    assert got.action == "CREATE"
    assert got.resource_id == ACC
    assert got.resource_type == TYPE
    assert (got.subscription_id, got.location) == ("s1", "westus2")
    assert got.correlation_id == "corr-1"
    assert got.start_time.endswith("Z")
    assert got.end_time is None
    assert not got.is_terminal
    assert [o.id for o in store.active_operations()] == [op.id]


def test_second_active_operation_on_same_resource_is_409(store):
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        tx.create_operation(res, "CREATE", "Creating")
    with pytest.raises(ArmError) as e:
        with store.transaction() as tx:
            tx.create_operation(make_account(id=ACC.upper()), "DELETE", "Deleting")
    assert (e.value.status, e.value.code) == (409, "AnotherOperationInProgress")
    assert len(store.active_operations()) == 1


def test_finished_operation_allows_next_operation(store):
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        op = tx.create_operation(res, "CREATE", "Creating")
    with store.transaction() as tx:
        tx.finish_operation(op.id, "Failed", {"httpStatus": 500, "code": "X", "message": "m"})
    done = store.get_operation(op.id)
    assert done.is_terminal
    assert done.end_time.endswith("Z")
    assert done.error == {"httpStatus": 500, "code": "X", "message": "m"}
    with store.transaction() as tx:
        tx.create_operation(res, "UPDATE", "Updating", previous={"tags": {}, "properties": {}})
    assert store.active_operations()[0].previous == {"tags": {}, "properties": {}}


def test_operation_params_round_trip(store):
    # 작업 입력: revert는 고른 스냅샷을 작업 행에 남기고 처리기가 읽는다 (되돌리기 설계 결정 11)
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        op = tx.create_operation(res, "POST", "Reverting", params={"snapshotId": "/x/snapshots/s1"})
        assert tx.active_operation(ACC).params == {"snapshotId": "/x/snapshots/s1"}
    assert store.get_operation(op.id).params == {"snapshotId": "/x/snapshots/s1"}


def test_operation_without_params_has_none(store):
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        op = tx.create_operation(res, "CREATE", "Creating")
    assert store.get_operation(op.id).params is None


def test_existing_database_gains_params_column(tmp_path):
    # 앞 사이클이 만든 DB 파일에는 params 열이 없다. 시작할 때 더하고 기존 작업은 그대로 읽힌다
    import sqlite3

    path = tmp_path / "old.db"
    old_schema = """
    CREATE TABLE operations (
        id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL, location TEXT NOT NULL,
        resource_id TEXT NOT NULL, resource_type TEXT NOT NULL, action TEXT NOT NULL,
        status TEXT NOT NULL, previous TEXT, error TEXT, correlation_id TEXT,
        start_time TEXT NOT NULL, end_time TEXT);
    INSERT INTO operations VALUES ('op1', 's1', 'westus2', '/r', 't', 'CREATE', 'Succeeded',
        NULL, NULL, NULL, '2026-11-07T00:00:00.000000Z', '2026-11-07T00:00:01.000000Z');
    """
    conn = sqlite3.connect(path)
    conn.executescript(old_schema)
    conn.close()
    store = StateStore(path)
    assert store.get_operation("op1").params is None
    StateStore(path)  # 두 번째 시작은 열을 다시 더하지 않는다
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        op = tx.create_operation(res, "POST", "Reverting", params={"k": 1})
    assert store.get_operation(op.id).params == {"k": 1}


def test_active_operation_for_resource(store):
    with store.transaction() as tx:
        res = make_account()
        tx.put_resource(res)
        assert tx.active_operation(ACC) is None
        op = tx.create_operation(res, "CREATE", "Creating")
        assert tx.active_operation(ACC.upper()).id == op.id


def test_data_survives_reopening_the_store(tmp_path):
    path = tmp_path / "anf.db"
    with StateStore(path).transaction() as tx:
        tx.put_resource(make_account())
    assert StateStore(path).get_resource(ACC).name == "acc1"
