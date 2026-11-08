"""NetApp 계정 (FR-02): 본문 검사, 응답 본문, 작업 흐름 (계정 설계 §4.1, §4.3, §4.4, §5)."""

import asyncio

import pytest

import anf_api.accounts as accounts
from anf_api.arm_rules import ACCOUNT_TYPE, ArmError
from anf_api.state_store import Resource, StateStore

ACC = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "anf.db")


def arm_error(fn, *args):
    with pytest.raises(ArmError) as e:
        fn(*args)
    return e.value


def finish(store, op, status="Succeeded"):
    """워커가 작업을 끝낸 것처럼 만든다."""
    with store.transaction() as tx:
        res = tx.get_resource(op.resource_id)
        res.provisioning_state = status
        tx.put_resource(res)
        tx.finish_operation(op.id, status)


def create(store, tags=None, location="westus2"):
    body = {"location": location}
    if tags is not None:
        body["tags"] = tags
    _, _, op = accounts.put_account(store, "s1", "rg1", "acc1", body, None)
    finish(store, op)


# --- 본문 검사 ---

def test_minimal_put_body():
    assert accounts.parse_put_body({"location": "westus2"}) == ("westus2", {})


def test_put_body_with_tags_default_encryption_and_read_only_fields():
    body = {
        "location": "eastus", "tags": {"k": "v"}, "id": "x", "name": "x", "type": "x",
        "etag": "x", "systemData": {},
        "properties": {"encryption": {"keySource": "Microsoft.NetApp"},
                       "provisioningState": "Succeeded", "disableShowmount": None,
                       "multiAdStatus": "Enabled", "multiADStatus": "Enabled"},
    }
    assert accounts.parse_put_body(body) == ("eastus", {"k": "v"})


@pytest.mark.parametrize("body", [
    [],
    "text",
    {},
    {"location": ""},
    {"location": 1},
    {"location": "westus2", "tags": {"k": 1}},
    {"location": "westus2", "tags": []},
    {"location": "westus2", "foo": 1},
    {"location": "westus2", "identity": {"type": "SystemAssigned"}},
    {"location": "westus2", "properties": []},
    {"location": "westus2", "properties": {"activeDirectories": []}},
    {"location": "westus2", "properties": {"nfsV4IDDomain": "x"}},
    {"location": "westus2", "properties": {"ldapConfiguration": {}}},
    {"location": "westus2", "properties": {"bar": 1}},
    {"location": "westus2", "properties": {"encryption": {"keySource": "Microsoft.KeyVault"}}},
    {"location": "westus2", "properties": {"encryption": {"keyVaultProperties": {}}}},
])
def test_invalid_put_body_is_400_invalid_request_content(body):
    err = arm_error(accounts.parse_put_body, body)
    assert (err.status, err.code) == (400, "InvalidRequestContent")


def test_unknown_property_message_names_the_property():
    err = arm_error(accounts.parse_put_body, {"location": "westus2", "foo": 1})
    assert err.message == "Value received for an unknown property 'foo'."


def test_patch_body():
    assert accounts.parse_patch_body({"tags": {"b": "2"}}) == {"b": "2"}
    assert accounts.parse_patch_body({}) is None
    assert accounts.parse_patch_body({"properties": {}}) is None


@pytest.mark.parametrize("body", [{"location": "westus2"}, {"identity": {}}, {"tags": {"a": 1}}, []])
def test_invalid_patch_body_is_400(body):
    err = arm_error(accounts.parse_patch_body, body)
    assert (err.status, err.code) == (400, "InvalidRequestContent")


# --- 응답 본문 ---

def test_account_body_shape(store):
    create(store, tags={"k": "v"})
    body = accounts.account_body(store.get_resource(ACC))
    assert body == {
        "id": ACC,
        "name": "acc1",
        "type": "Microsoft.NetApp/netAppAccounts",
        "location": "westus2",
        "tags": {"k": "v"},
        "properties": {"provisioningState": "Succeeded",
                       "encryption": {"keySource": "Microsoft.NetApp"}},
    }


# --- PUT ---

def test_put_new_account_creates_resource_and_create_operation(store):
    created, res, op = accounts.put_account(
        store, "s1", "rg1", "acc1", {"location": "westus2", "tags": {"a": "1"}}, "corr-1")
    assert created is True
    assert res.provisioning_state == "Creating"
    assert (op.action, op.status, op.correlation_id) == ("CREATE", "Creating", "corr-1")
    stored = store.get_resource(ACC)
    assert stored.provisioning_state == "Creating"
    assert stored.tags == {"a": "1"}
    assert stored.parent_id is None


def test_put_existing_account_starts_update_and_replaces_tags(store):
    create(store, tags={"a": "1"})
    created, res, op = accounts.put_account(
        store, "s1", "rg1", "ACC1", {"location": "WestUS2", "tags": {"b": "2"}}, None)
    assert created is False
    assert res.id == ACC  # 처음 받은 이름을 보존한다
    assert (op.action, op.status) == ("UPDATE", "Updating")
    assert op.previous == {"tags": {"a": "1"},
                           "properties": {"encryption": {"keySource": "Microsoft.NetApp"}}}
    stored = store.get_resource(ACC)
    assert (stored.provisioning_state, stored.tags, stored.location) == ("Updating", {"b": "2"}, "westus2")


def test_put_failed_account_starts_update(store):
    _, _, op = accounts.put_account(store, "s1", "rg1", "acc1", {"location": "westus2"}, None)
    finish(store, op, "Failed")
    created, res, op2 = accounts.put_account(store, "s1", "rg1", "acc1", {"location": "westus2"}, None)
    assert (created, res.provisioning_state, op2.action) == (False, "Updating", "UPDATE")


def test_put_with_different_location_is_409_and_changes_nothing(store):
    create(store, tags={"a": "1"})
    err = arm_error(accounts.put_account, store, "s1", "rg1", "acc1",
                    {"location": "eastus", "tags": {"b": "2"}}, None)
    assert (err.status, err.code) == (409, "InvalidResourceLocation")
    stored = store.get_resource(ACC)
    assert (stored.tags, stored.provisioning_state) == ({"a": "1"}, "Succeeded")
    assert store.active_operations() == []


def test_put_while_operation_in_progress_is_409_and_changes_nothing(store):
    accounts.put_account(store, "s1", "rg1", "acc1", {"location": "westus2", "tags": {"a": "1"}}, None)
    err = arm_error(accounts.put_account, store, "s1", "rg1", "acc1",
                    {"location": "westus2", "tags": {"b": "2"}}, None)
    assert (err.status, err.code) == (409, "AnotherOperationInProgress")
    assert store.get_resource(ACC).tags == {"a": "1"}
    assert len(store.active_operations()) == 1


@pytest.mark.parametrize("rg,name", [("rg1", "-bad"), ("rg1", "a.b"), ("bad rg", "acc1")])
def test_put_with_invalid_names_is_400(store, rg, name):
    err = arm_error(accounts.put_account, store, "s1", rg, name, {"location": "westus2"}, None)
    assert (err.status, err.code) == (400, "InvalidResourceName")


# --- GET, 목록 ---

def test_get_account_ignores_case(store):
    create(store)
    assert accounts.get_account(store, "S1", "RG1", "ACC1").id == ACC


def test_get_missing_account_is_404(store):
    err = arm_error(accounts.get_account, store, "s1", "rg1", "nope")
    assert (err.status, err.code) == (404, "ResourceNotFound")
    assert "/netAppAccounts/nope" in err.message


def test_list_accounts_by_resource_group_and_subscription(store):
    create(store)
    accounts.put_account(store, "s1", "rg2", "acc2", {"location": "westus2"}, None)
    assert [r.name for r in accounts.list_accounts(store, "s1", "rg1")] == ["acc1"]
    assert [r.name for r in accounts.list_accounts(store, "s1")] == ["acc1", "acc2"]
    assert accounts.list_accounts(store, "s1", "rg3") == []


# --- PATCH ---

def test_patch_replaces_tags_without_changing_state(store):
    create(store, tags={"a": "1"})
    res = accounts.patch_account(store, "s1", "rg1", "acc1", {"tags": {"b": "2"}})
    assert (res.tags, res.provisioning_state) == ({"b": "2"}, "Succeeded")
    assert store.get_resource(ACC).tags == {"b": "2"}
    assert store.active_operations() == []


def test_patch_without_tags_keeps_tags(store):
    create(store, tags={"a": "1"})
    assert accounts.patch_account(store, "s1", "rg1", "acc1", {}).tags == {"a": "1"}


def test_patch_missing_account_is_404(store):
    err = arm_error(accounts.patch_account, store, "s1", "rg1", "nope", {"tags": {}})
    assert (err.status, err.code) == (404, "ResourceNotFound")


def test_patch_while_operation_in_progress_is_409(store):
    accounts.put_account(store, "s1", "rg1", "acc1", {"location": "westus2"}, None)
    err = arm_error(accounts.patch_account, store, "s1", "rg1", "acc1", {"tags": {"b": "2"}})
    assert (err.status, err.code) == (409, "AnotherOperationInProgress")


# --- DELETE ---

def test_delete_starts_delete_operation(store):
    create(store)
    op = accounts.delete_account(store, "s1", "rg1", "acc1", "corr-9")
    assert (op.action, op.status, op.correlation_id) == ("DELETE", "Deleting", "corr-9")
    assert store.get_resource(ACC).provisioning_state == "Deleting"


def test_delete_missing_account_returns_none(store):
    assert accounts.delete_account(store, "s1", "rg1", "nope", None) is None
    assert store.active_operations() == []


def test_delete_with_child_resource_is_409_cannot_delete_resource(store):
    """자식이 남은 계정의 삭제 거절 (설계 결정 8). 실환경 검증은 용량 풀 사이클에서 한다."""
    create(store)
    with store.transaction() as tx:
        tx.put_resource(Resource(
            id=ACC + "/capacityPools/pool1", type=ACCOUNT_TYPE + "/capacityPools",
            subscription_id="s1", resource_group="rg1", name="pool1", location="westus2",
            tags={}, properties={}, provisioning_state="Succeeded", parent_id=ACC,
        ))
    err = arm_error(accounts.delete_account, store, "s1", "rg1", "acc1", None)
    assert (err.status, err.code) == (409, "CannotDeleteResource")
    assert "'Microsoft.NetApp/netAppAccounts/acc1/capacityPools/pool1'" in err.message
    assert store.get_resource(ACC).provisioning_state == "Succeeded"
    assert store.active_operations() == []


def test_delete_while_operation_in_progress_is_409(store):
    accounts.put_account(store, "s1", "rg1", "acc1", {"location": "westus2"}, None)
    err = arm_error(accounts.delete_account, store, "s1", "rg1", "acc1", None)
    assert (err.status, err.code) == (409, "AnotherOperationInProgress")
    assert store.get_resource(ACC).provisioning_state == "Creating"


# --- 작업 처리기 ---

def test_handlers_cover_all_actions_and_touch_no_storage(store):
    assert set(accounts.HANDLERS) == {(ACCOUNT_TYPE, a) for a in ("CREATE", "UPDATE", "DELETE")}
    _, _, op = accounts.put_account(store, "s1", "rg1", "acc1", {"location": "westus2"}, None)
    assert asyncio.run(accounts.HANDLERS[(ACCOUNT_TYPE, "CREATE")](op)) is None
