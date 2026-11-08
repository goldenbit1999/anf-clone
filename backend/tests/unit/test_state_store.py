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


def test_delete_resource(store):
    with store.transaction() as tx:
        tx.put_resource(make_account())
    with store.transaction() as tx:
        tx.delete_resource(ACC)
    assert store.get_resource(ACC) is None


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
