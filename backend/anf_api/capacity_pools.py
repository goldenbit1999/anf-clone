"""용량 풀 (FR-03): 요청 본문 검사, 응답 본문, PUT·PATCH·DELETE·GET·목록 흐름, 작업 처리기.

풀은 볼륨이 쓸 용량과 처리량을 사는 예산이자 과금 단위다 [풀 브리프 문서 11]. 풀 자체는
마운트 대상이 아니고, 대응하는 ONTAP 객체도 공개 자료에 없다. 그래서 계정처럼 storage agent에
아무것도 만들지 않고, 비동기 작업은 상태 전이만 한다 (풀 설계 결정 2).

풀이 볼륨에 주는 효과는 두 가지 규칙이다.
- 용량: 볼륨 할당량(`usageThreshold`) 합 ≤ 풀 `size`. 풀 쪽 검사(축소 하한)는 여기에 있고,
  볼륨 생성 쪽 검사는 볼륨 사이클에서 같은 규칙으로 만든다 (설계 §6).
- 처리량: 풀 총 처리량 = 풀 TiB × 서비스 수준 단가. 실제 I/O 제한은 FR-08에서 한다.

규칙 위반은 검사와 쓰기를 같은 트랜잭션에서 하고 동기 400으로 거절한다 (설계 결정 4).
"""

import uuid

from anf_api.arm_rules import (
    POOL_TYPE,
    ArmError,
    account_id,
    check_account_name,
    check_pool_name,
    check_resource_group_name,
    check_tags,
    invalid_content,
    location_conflict,
    not_found,
    pool_id,
    unknown_property,
    unsupported_property,
)
from anf_api.state_store import Operation, Resource, StateStore, Tx

TIB = 1 << 40
_MAX_SIZE = 2048 * TIB  # 2,048 TiB, 지원 요청으로도 늘릴 수 없다 [풀 브리프 문서 7]
_VOLUME_TYPE = f"{POOL_TYPE}/volumes"

# 서비스 수준별 처리량 단가 (MiB/s per TiB) [풀 브리프 문서 4]
_MIBPS_PER_TIB = {"Standard": 16, "Premium": 64, "Ultra": 128}
# 실제 ANF에는 있지만 이 클론이 미룬 서비스 수준 (설계 §2)
_UNSUPPORTED_LEVELS = {"Flexible", "StandardZRS"}
_QOS_TYPES = {"Auto", "Manual"}

_READ_ONLY = {"id", "name", "type", "etag", "systemData"}
_READ_ONLY_PROPERTIES = {"provisioningState", "poolId", "totalThroughputMibps", "utilizedThroughputMibps"}
# PATCH 모델(PoolPatchProperties)에는 size, qosType, coolAccess, customThroughputMibps만 있다 [스펙]
_PATCH_PROPERTIES = {"size", "qosType", "coolAccess", "customThroughputMibps"}
_PUT_PROPERTIES = _PATCH_PROPERTIES | {"serviceLevel", "encryptionType"}


def _check_size(value) -> int:
    if (isinstance(value, bool) or not isinstance(value, int) or value % TIB
            or not TIB <= value <= _MAX_SIZE):
        raise invalid_content(
            "The 'properties.size' property must be a whole number of bytes in 1 TiB "
            f"({TIB}) chunks, from 1 TiB to 2048 TiB.")
    return value


def _check_service_level(value) -> str:
    if value in _UNSUPPORTED_LEVELS:
        raise invalid_content(
            f"The value '{value}' of 'properties.serviceLevel' is not supported by this ANF clone.")
    if value not in _MIBPS_PER_TIB:
        raise invalid_content(
            "The 'properties.serviceLevel' property must be one of 'Standard', 'Premium', 'Ultra'.")
    return value


def _check_properties(props, allowed: set[str]) -> dict:
    """쓸 수 있는 속성 중 요청에 있는 것만 돌려준다. 미룬 기능의 값은 거절한다."""
    if not isinstance(props, dict):
        raise invalid_content("The 'properties' property must be an object.")
    changes = {}
    for key, value in props.items():
        if key in _READ_ONLY_PROPERTIES:
            continue
        if key not in allowed:
            raise unknown_property(f"properties.{key}")
        if key == "size":
            changes[key] = _check_size(value)
        elif key == "serviceLevel":
            changes[key] = _check_service_level(value)
        elif key == "qosType":
            if value not in _QOS_TYPES:
                raise invalid_content("The 'properties.qosType' property must be 'Auto' or 'Manual'.")
            changes[key] = value
        elif key == "coolAccess":
            if not isinstance(value, bool):
                raise invalid_content("The 'properties.coolAccess' property must be true or false.")
            if value:
                raise unsupported_property("properties.coolAccess")
            changes[key] = value
        elif key == "encryptionType":
            if value is None:
                continue
            if value != "Single":
                raise invalid_content(
                    f"The value '{value}' of 'properties.encryptionType' is not supported by this ANF clone.")
            changes[key] = value
        elif key == "customThroughputMibps":
            # Flexible 서비스 수준 전용 [스펙]
            if value is not None:
                raise unsupported_property("properties.customThroughputMibps")
    return changes


def _check_top_level(body) -> dict:
    if not isinstance(body, dict):
        raise invalid_content("The request content must be a JSON object.")
    for key in body:
        if key not in {"location", "tags", "properties"} and key not in _READ_ONLY:
            raise unknown_property(key)
    return body


def parse_put_body(body) -> tuple[str, dict, dict]:
    """PUT 본문에서 (location, tags, 요청에 있는 쓸 수 있는 properties)를 꺼낸다."""
    body = _check_top_level(body)
    location = body.get("location")
    if not isinstance(location, str) or not location:
        raise invalid_content("The 'location' property is required.")
    changes = _check_properties(body.get("properties", {}), _PUT_PROPERTIES)
    return location, check_tags(body.get("tags", {})), changes


def parse_patch_body(body) -> tuple[str | None, dict | None, dict]:
    """PATCH 본문에서 (location, tags, properties)를 꺼낸다. 없는 것은 None이나 빈 dict다."""
    body = _check_top_level(body)
    location = body.get("location")
    if location is not None and (not isinstance(location, str) or not location):
        raise invalid_content("The 'location' property must be a string.")
    tags = check_tags(body["tags"]) if "tags" in body else None
    return location, tags, _check_properties(body.get("properties", {}), _PATCH_PROPERTIES)


def total_throughput_mibps(props: dict) -> float:
    """풀 총 처리량 = 풀 크기(2진 TiB) × 서비스 수준 단가 (설계 결정 10). 4 TiB Premium = 256.0."""
    return props["size"] / TIB * _MIBPS_PER_TIB[props["serviceLevel"]]


def pool_body(res: Resource) -> dict:
    props = res.properties
    account = res.id.split("/")[-3]  # .../netAppAccounts/{account}/capacityPools/{pool}
    return {
        "id": res.id,
        "name": f"{account}/{res.name}",
        "type": POOL_TYPE,
        "location": res.location,
        "tags": res.tags,
        "properties": {
            "provisioningState": res.provisioning_state,
            "poolId": props["poolId"],
            "serviceLevel": props["serviceLevel"],
            "size": props["size"],
            "qosType": props["qosType"],
            "totalThroughputMibps": total_throughput_mibps(props),
            # 볼륨 처리량 한도의 합 (녹화 N5). 볼륨 사이클 전에는 볼륨이 없으므로 0이다.
            "utilizedThroughputMibps": 0.0,
            "encryptionType": props["encryptionType"],
            "coolAccess": props["coolAccess"],
        },
    }


def _id(subscription_id: str, resource_group: str, account: str, name: str) -> str:
    check_resource_group_name(resource_group)
    check_account_name(account)
    check_pool_name(name)
    return pool_id(subscription_id, resource_group, account, name)


def _apply_changes(tx: Tx, pool: Resource, changes: dict) -> dict:
    """갱신(PUT·PATCH)의 규칙을 검사하고 새 properties를 돌려준다. 실서비스 코드가 [미확인]인
    규칙 위반은 400 BadRequest와 ANF 문서의 문구다 (설계 결정 7)."""
    props = pool.properties
    if props["qosType"] == "Manual" and changes.get("qosType") == "Auto":
        # Auto → Manual은 영구 변경이다 [풀 브리프 문서 15, 5]
        raise ArmError(400, "BadRequest",
                       "The QoS type of a capacity pool can't be changed from Manual to Auto.")
    if changes.get("serviceLevel", props["serviceLevel"]) != props["serviceLevel"] and tx.child_ids(pool.id):
        # 볼륨이 있는 풀만 거절한다 [풀 브리프 문서 8에서 추론] (설계 결정 5)
        raise ArmError(400, "BadRequest", "ServiceLevel cannot be changed.")
    if "size" in changes:
        # 하한은 사용량이 아니라 볼륨 할당량의 합이다. 상태와 무관하게 모든 볼륨 행이 예약이다 (설계 §6).
        allocated = sum(v.properties["usageThreshold"] for v in tx.list_children(pool.id, _VOLUME_TYPE))
        if changes["size"] < allocated:
            # NetApp KB의 메시지 [풀 브리프 문서 13]
            raise ArmError(
                400, "BadRequest",
                f"The capacity pool size of {changes['size']} bytes is too small for the combined "
                f"volume size of {allocated} bytes of the capacity pool. Make sure that the total "
                "size of all the volumes in the capacity pool does not exceed the size of the "
                "capacity pool.")
    return {**props, **changes}


def get_pool(store: StateStore, subscription_id: str, resource_group: str, account: str,
             name: str) -> Resource:
    rid = _id(subscription_id, resource_group, account, name)
    res = store.get_resource(rid)
    if res is None:
        raise not_found(rid)
    return res


def list_pools(store: StateStore, subscription_id: str, resource_group: str,
               account: str) -> list[Resource]:
    check_resource_group_name(resource_group)
    check_account_name(account)
    parent = account_id(subscription_id, resource_group, account)
    if store.get_resource(parent) is None:
        raise not_found(parent)
    return store.list_children(parent, POOL_TYPE)


def put_pool(store: StateStore, subscription_id: str, resource_group: str, account: str, name: str,
             body, correlation_id: str | None) -> tuple[bool, Resource, Operation]:
    """새 풀이면 Creating + CREATE 작업(201), 있으면 Updating + UPDATE 작업(200).
    반환: (새로 만들었는지, 리소스, 작업)."""
    rid = _id(subscription_id, resource_group, account, name)
    location, tags, changes = parse_put_body(body)
    parent_id = account_id(subscription_id, resource_group, account)
    with store.transaction() as tx:
        existing = tx.get_resource(rid)
        if existing is None:
            # 부모 검사를 생성과 같은 트랜잭션에서 해 고아 풀을 막는다 (설계 결정 6, §6)
            parent = tx.get_resource(parent_id)
            if parent is None:
                # 녹화 N6의 게이트웨이 문구
                raise ArmError(
                    404, "ParentResourceNotFound",
                    "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools', "
                    f"because the parent resource '{parent_id}' could not be found.")
            if parent.provisioning_state == "Deleting":
                raise ArmError(
                    409, "Conflict",
                    f"Cannot create capacity pool '{rid}' because its parent NetApp account "
                    f"'{parent.id}' is being deleted.")
            for key in ("size", "serviceLevel"):
                if key not in changes:
                    raise invalid_content(f"The 'properties.{key}' property is required.")
            res = Resource(
                id=rid, type=POOL_TYPE, subscription_id=subscription_id,
                resource_group=resource_group, name=name, location=location, tags=tags,
                properties={
                    "poolId": str(uuid.uuid4()), "qosType": "Auto", "encryptionType": "Single",
                    "coolAccess": False, **changes,
                },
                provisioning_state="Creating", parent_id=parent_id,
            )
            op = tx.create_operation(res, "CREATE", "Creating", correlation_id=correlation_id)
            tx.put_resource(res)
            return True, res, op
        if existing.location.lower() != location.lower():
            raise location_conflict(existing.name, existing.resource_group, existing.location, location)
        # 빠진 속성은 기존 값을 유지한다 (설계 결정 8)
        properties = _apply_changes(tx, existing, changes)
        previous = {"tags": existing.tags, "properties": existing.properties}
        op = tx.create_operation(existing, "UPDATE", "Updating",
                                 previous=previous, correlation_id=correlation_id)
        existing.tags = tags
        existing.properties = properties
        existing.provisioning_state = "Updating"
        tx.put_resource(existing)
        return False, existing, op


def patch_pool(store: StateStore, subscription_id: str, resource_group: str, account: str,
               name: str, body, correlation_id: str | None) -> tuple[Resource, Operation]:
    """tags만 바꿔도 비동기다: Patching + PATCH 작업(202) (녹화 N2, P1, 설계 결정 1).
    새 값을 바로 쓰고, 실패하면 워커가 이전 값으로 되돌린다 (설계 결정 9)."""
    rid = _id(subscription_id, resource_group, account, name)
    location, tags, changes = parse_patch_body(body)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            raise not_found(rid)
        if location is not None and res.location.lower() != location.lower():
            raise location_conflict(res.name, res.resource_group, res.location, location)
        properties = _apply_changes(tx, res, changes)
        previous = {"tags": res.tags, "properties": res.properties}
        op = tx.create_operation(res, "PATCH", "Patching",
                                 previous=previous, correlation_id=correlation_id)
        if tags is not None:
            res.tags = tags
        res.properties = properties
        res.provisioning_state = "Patching"
        tx.put_resource(res)
        return res, op


def delete_pool(store: StateStore, subscription_id: str, resource_group: str, account: str,
                name: str, correlation_id: str | None) -> Operation | None:
    """있으면 Deleting + DELETE 작업(202), 없으면 None(204).
    볼륨이 남아 있으면 409 CannotDeleteResource (녹화 N5, `Tx.ensure_no_children`)."""
    rid = _id(subscription_id, resource_group, account, name)
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
    """풀 작업은 storage agent에 할 일이 없다 (설계 결정 2). 멱등이다."""


HANDLERS = {(POOL_TYPE, action): _no_storage_work
            for action in ("CREATE", "UPDATE", "PATCH", "DELETE")}
