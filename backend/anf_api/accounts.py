"""NetApp 계정 (FR-02): 요청 본문 검사, 응답 본문, PUT·PATCH·DELETE·GET 흐름, 작업 처리기.

계정은 컨트롤 플레인 전용 리소스다 (설계 결정 1). 실제 ANF에서도 계정을 만들거나 지워도
데이터 플레인에 보이는 변화가 없고, 1:1로 대응하는 ONTAP 객체는 공개 자료에서 확인되지 않았다.
그래서 storage agent에 아무것도 만들지 않고, 비동기 작업은 상태 전이만 한다.
"""

from anf_api.arm_rules import (
    ACCOUNT_TYPE,
    account_id,
    check_account_name,
    check_resource_group_name,
    location_conflict,
    not_found,
)
from anf_api.arm_rules import check_tags as _check_tags
from anf_api.arm_rules import invalid_content as _invalid
from anf_api.arm_rules import unknown_property as _unknown
from anf_api.arm_rules import unsupported_property as _unsupported
from anf_api.state_store import Operation, Resource, StateStore

# 기본 암호화 설정. 요청에 없어도 실서비스 GET 응답에 채워져 나온다 (녹화 R1).
_DEFAULT_PROPERTIES = {"encryption": {"keySource": "Microsoft.NetApp"}}

_READ_ONLY = {"id", "name", "type", "etag", "systemData"}
_READ_ONLY_PROPERTIES = {"provisioningState", "disableShowmount", "multiAdStatus", "multiADStatus"}
# 실제 계정에는 있지만 이 클론이 미룬 속성 (설계 §2). 받으면 무시하지 않고 거절한다.
_UNSUPPORTED = {"identity"}
_UNSUPPORTED_PROPERTIES = {"activeDirectories", "nfsV4IDDomain", "ldapConfiguration"}


def _check_properties(props) -> None:
    if not isinstance(props, dict):
        raise _invalid("The 'properties' property must be an object.")
    for key, value in props.items():
        if key in _READ_ONLY_PROPERTIES:
            continue
        if key in _UNSUPPORTED_PROPERTIES:
            raise _unsupported(f"properties.{key}")
        if key != "encryption":
            raise _unknown(f"properties.{key}")
        if not isinstance(value, dict):
            raise _invalid("The 'properties.encryption' property must be an object.")
        for enc_key, enc_value in value.items():
            if enc_key != "keySource" or enc_value != "Microsoft.NetApp":
                # 고객 관리 키(Microsoft.KeyVault)와 그 설정은 미룬다
                raise _unsupported(f"properties.encryption.{enc_key}")


def _check_top_level(body, allowed: set[str]) -> dict:
    if not isinstance(body, dict):
        raise _invalid("The request content must be a JSON object.")
    for key in body:
        if key in _UNSUPPORTED:
            raise _unsupported(key)
        if key not in allowed and key not in _READ_ONLY:
            raise _unknown(key)
    if "properties" in body:
        _check_properties(body["properties"])
    return body


def parse_put_body(body) -> tuple[str, dict]:
    """PUT 본문에서 (location, tags)를 꺼낸다. tags는 맵 전체를 바꾼다."""
    body = _check_top_level(body, {"location", "tags", "properties"})
    location = body.get("location")
    if not isinstance(location, str) or not location:
        raise _invalid("The 'location' property is required.")
    return location, _check_tags(body.get("tags", {}))


def parse_patch_body(body) -> dict | None:
    """PATCH 본문에서 tags를 꺼낸다. 없으면 None (tags를 그대로 둔다).
    2026-08-01 PATCH 모델에는 location이 없다 [스펙 3]."""
    body = _check_top_level(body, {"tags", "properties"})
    return _check_tags(body["tags"]) if "tags" in body else None


def account_body(res: Resource) -> dict:
    return {
        "id": res.id,
        "name": res.name,
        "type": ACCOUNT_TYPE,
        "location": res.location,
        "tags": res.tags,
        "properties": {"provisioningState": res.provisioning_state, **res.properties},
    }


def _id(subscription_id: str, resource_group: str, name: str) -> str:
    check_resource_group_name(resource_group)
    check_account_name(name)
    return account_id(subscription_id, resource_group, name)


def get_account(store: StateStore, subscription_id: str, resource_group: str, name: str) -> Resource:
    rid = _id(subscription_id, resource_group, name)
    res = store.get_resource(rid)
    if res is None:
        raise not_found(rid)
    return res


def list_accounts(store: StateStore, subscription_id: str,
                  resource_group: str | None = None) -> list[Resource]:
    if resource_group is not None:
        check_resource_group_name(resource_group)
    return store.list_resources(ACCOUNT_TYPE, subscription_id, resource_group)


def put_account(store: StateStore, subscription_id: str, resource_group: str, name: str,
                body, correlation_id: str | None) -> tuple[bool, Resource, Operation]:
    """새 계정이면 Creating + CREATE 작업(201), 있으면 Updating + UPDATE 작업(200, 녹화 R3).
    반환: (새로 만들었는지, 리소스, 작업)."""
    rid = _id(subscription_id, resource_group, name)
    location, tags = parse_put_body(body)
    with store.transaction() as tx:
        existing = tx.get_resource(rid)
        if existing is None:
            res = Resource(
                id=rid, type=ACCOUNT_TYPE, subscription_id=subscription_id,
                resource_group=resource_group, name=name, location=location, tags=tags,
                properties=dict(_DEFAULT_PROPERTIES), provisioning_state="Creating",
            )
            op = tx.create_operation(res, "CREATE", "Creating", correlation_id=correlation_id)
            tx.put_resource(res)
            return True, res, op
        if existing.location.lower() != location.lower():
            raise location_conflict(existing.name, existing.resource_group, existing.location, location)
        previous = {"tags": existing.tags, "properties": existing.properties}
        op = tx.create_operation(existing, "UPDATE", "Updating",
                                 previous=previous, correlation_id=correlation_id)
        existing.tags = tags
        existing.provisioning_state = "Updating"
        tx.put_resource(existing)
        return False, existing, op


def patch_account(store: StateStore, subscription_id: str, resource_group: str, name: str,
                  body) -> Resource:
    """tags만 바꾸는 동기 PATCH (녹화 R2). provisioningState는 바꾸지 않는다 (설계 결정 3)."""
    rid = _id(subscription_id, resource_group, name)
    tags = parse_patch_body(body)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            raise not_found(rid)
        tx.ensure_no_active_operation(res.id)
        if tags is not None:
            res.tags = tags
            tx.put_resource(res)
        return res


def delete_account(store: StateStore, subscription_id: str, resource_group: str, name: str,
                   correlation_id: str | None) -> Operation | None:
    """있으면 Deleting + DELETE 작업(202), 없으면 None(204).
    자식(용량 풀)이 남아 있으면 409 CannotDeleteResource (녹화 R4, `Tx.ensure_no_children`)."""
    rid = _id(subscription_id, resource_group, name)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            return None
        tx.ensure_no_children(rid)
        op = tx.create_operation(res, "DELETE", "Deleting", correlation_id=correlation_id)
        res.provisioning_state = "Deleting"
        tx.put_resource(res)
        return op


async def _no_storage_work(op: Operation) -> None:
    """계정 작업은 storage agent에 할 일이 없다 (설계 결정 1). 멱등이다."""


HANDLERS = {(ACCOUNT_TYPE, action): _no_storage_work for action in ("CREATE", "UPDATE", "DELETE")}
