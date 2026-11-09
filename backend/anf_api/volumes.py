"""볼륨 (FR-04): 요청 본문 검사, 응답 본문, PUT·PATCH·DELETE·GET·목록 흐름 (볼륨 설계 §3, §4).

볼륨은 풀 아래의 ARM 리소스이고, 데이터 플레인에서는 storage agent의 ONTAP 볼륨(thin LV + ext4, NFS export)이다.
이 모듈은 컨트롤 플레인 규칙과, agent를 부르는 작업 처리기(`make_handlers`)를 맡는다.
규칙 위반은 검사와 쓰기를 같은 트랜잭션에서 하고 동기로 거절한다
(결정 13·14). 검사 순서: 이름 → 본문 형식 → 부모 존재·상태 → 진행 중 작업 → 불변 속성 → 경로 중복 → 용량.

데이터 효과를 아직 만들지 않은 속성은 저장만 하지 않고 거절한다. 클론이 지금 하는 값과 같으면 받는다 (결정 4).
"""

import re
import uuid

from anf_api.arm_rules import (
    SNAPSHOT_TYPE,
    VOLUME_TYPE,
    ArmError,
    check_account_name,
    check_pool_name,
    check_resource_group_name,
    check_tags,
    check_volume_name,
    invalid_content,
    location_conflict,
    not_found,
    pool_id,
    unknown_property,
    unsupported_property,
    volume_id,
)
from anf_api.capacity_pools import MIBPS_PER_TIB, TIB
from anf_api.state_store import Operation, Resource, StateStore, Tx

GIB = 1 << 30
DEFAULT_MIN_SIZE = 50 * GIB  # [스펙 2]. 검증할 때만 ANF_MIN_VOLUME_SIZE_GIB로 낮춘다 (결정 3)
_MAX_SIZE = 100 * TIB  # 일반 볼륨 상한 [스펙 2 설명]. large volume은 범위 밖

_TOKEN_CHARS = re.compile(r"[a-zA-Z0-9\-_]*")
_SUBNET_ID = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Network"
    r"/virtualNetworks/[^/]+/subnets/[^/]+", re.IGNORECASE)
_UNIX_PERMISSIONS = re.compile(r"[0-7]{4}")
_PROTOCOLS = ("NFSv3", "NFSv4.1")
_NETWORK_FEATURES = ("Basic", "Standard")

_READ_ONLY = {"id", "name", "type", "etag", "systemData"}
_READ_ONLY_PROPERTIES = {"provisioningState", "actualThroughputMibps", "mountTargets"}
# 클론이 한 가지 값만 지원하고 응답에는 넣지 않는 속성. 그 값이면 받는다
_FIXED = {"kerberosEnabled": False, "ldapEnabled": False, "isLargeVolume": False, "coolAccess": False}
# 값이 있으면 미룬 기능이다: Manual QoS 처리량(FR-08), 스냅샷·백업 복원, 데이터 보호(복제)
_NOT_YET = {"throughputMibps", "snapshotId", "backupId", "dataProtection"}
# 생성 때 요청 값을 쓰는 속성
_SETTABLE = ("creationToken", "usageThreshold", "subnetId", "protocolTypes", "networkFeatures", "unixPermissions")
# 서비스가 정하는 값. 요청 값이 그와 다르면 미룬 기능이다
_SERVICE_HELD = ("serviceLevel", "snapshotDirectoryVisible", "securityStyle", "exportPolicy")
_PROPERTIES = {*_SETTABLE, *_SERVICE_HELD, "fileSystemId", *_FIXED, *_NOT_YET}
# 생성 뒤 바꿀 수 없는 속성과 ANF 오류 문서의 문구 [볼륨 브리프 문서 7]. subnetId 문구는 같은 모양으로 지었다
_IMMUTABLE = {
    "creationToken": "CreationToken cannot be changed.",
    "subnetId": "SubnetId cannot be changed.",
    "fileSystemId": "FileSystemId cannot be changed.",
}
# 생성 뒤에도 바꿀 수 있는 속성. Azure 네트워크 개념이라 데이터 효과가 없고 저장만 한다
_CHANGEABLE = {"networkFeatures"}


# --- 본문 검사 ---


def _check_token(value) -> str:
    # 문구는 ANF RP 오류 문서 [볼륨 브리프 문서 7]
    if not isinstance(value, str):
        raise invalid_content("The 'properties.creationToken' property must be a string.")
    if not value:
        raise invalid_content("File path too short.")
    if len(value) > 80:
        raise invalid_content("File path too long.")
    if not _TOKEN_CHARS.fullmatch(value):
        raise invalid_content(
            'The file path name can contain letters, numbers, underscores ("_"), and hyphens ("-") only.')
    if not value[0].isalpha():
        raise invalid_content("The file path must start with a letter.")
    return value


def _check_size(value, min_size: int) -> int:
    if (isinstance(value, bool) or not isinstance(value, int) or value % GIB
            or not min_size <= value <= _MAX_SIZE):
        raise invalid_content(
            "The 'properties.usageThreshold' property must be a whole number of bytes in 1 GiB "
            f"({GIB}) chunks, from {min_size // GIB} GiB to 100 TiB.")
    return value


def _check_protocols(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise invalid_content("The 'properties.protocolTypes' property must be an array of strings.")
    if "CIFS" in value:
        raise invalid_content("The value 'CIFS' of 'properties.protocolTypes' is not supported by this ANF clone.")
    if len(value) != 1 or value[0] not in _PROTOCOLS:
        raise invalid_content("The 'properties.protocolTypes' property must be [\"NFSv3\"] or [\"NFSv4.1\"].")
    return list(value)


def _check_property(key: str, value, min_size: int):
    if key == "creationToken":
        return _check_token(value)
    if key == "usageThreshold":
        return _check_size(value, min_size)
    if key == "protocolTypes":
        return _check_protocols(value)
    if key == "subnetId":
        if not isinstance(value, str) or not _SUBNET_ID.fullmatch(value):
            raise invalid_content(
                "The 'properties.subnetId' property must be a subnet resource ID: /subscriptions/{id}"
                "/resourceGroups/{group}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}.")
        return value
    if key == "serviceLevel":
        if value not in MIBPS_PER_TIB:
            raise invalid_content(
                "The 'properties.serviceLevel' property must be one of 'Standard', 'Premium', 'Ultra'.")
        return value
    if key == "networkFeatures":
        if value not in _NETWORK_FEATURES:
            raise invalid_content("The 'properties.networkFeatures' property must be 'Basic' or 'Standard'.")
        return value
    if key == "unixPermissions":
        if not isinstance(value, str) or not _UNIX_PERMISSIONS.fullmatch(value):
            raise invalid_content(
                "The 'properties.unixPermissions' property must be four octal digits, for example '0770'.")
        return value
    if key == "snapshotDirectoryVisible":
        if not isinstance(value, bool):
            raise invalid_content("The 'properties.snapshotDirectoryVisible' property must be true or false.")
        return value
    if key == "securityStyle":
        if not isinstance(value, str) or value.lower() not in ("unix", "ntfs"):
            raise invalid_content("The 'properties.securityStyle' property must be 'unix' or 'ntfs'.")
        return value.lower()
    if key == "exportPolicy":
        if not isinstance(value, dict):
            raise invalid_content("The 'properties.exportPolicy' property must be an object.")
        return value
    # fileSystemId: 읽기 전용이지만 같은 값을 다시 보내는 것은 허용된다 [볼륨 브리프 문서 7]
    if not isinstance(value, str):
        raise invalid_content("The 'properties.fileSystemId' property must be a string.")
    return value


def _check_properties(props, min_size: int) -> dict:
    """요청에 있는 쓸 수 있는 속성을 검사해 돌려준다. 미룬 기능의 값은 여기서 거절한다."""
    if not isinstance(props, dict):
        raise invalid_content("The 'properties' property must be an object.")
    changes = {}
    for key, value in props.items():
        if key in _READ_ONLY_PROPERTIES:
            continue
        if key not in _PROPERTIES:
            raise unknown_property(f"properties.{key}")
        if key in _NOT_YET:
            if value is not None:
                raise unsupported_property(f"properties.{key}")
        elif key in _FIXED:
            if not isinstance(value, bool):
                raise invalid_content(f"The 'properties.{key}' property must be true or false.")
            if value != _FIXED[key]:
                raise unsupported_property(f"properties.{key}")
        elif not (key == "unixPermissions" and value is None):  # nullable [스펙 2]
            changes[key] = _check_property(key, value, min_size)
    return changes


def _check_top_level(body) -> dict:
    if not isinstance(body, dict):
        raise invalid_content("The request content must be a JSON object.")
    for key in body:
        if key not in {"location", "tags", "properties"} and key not in _READ_ONLY:
            raise unknown_property(key)
    return body


def parse_put_body(body, min_size: int = DEFAULT_MIN_SIZE) -> tuple[str, dict, dict]:
    """PUT 본문에서 (location, tags, 요청에 있는 쓸 수 있는 properties)를 꺼낸다."""
    body = _check_top_level(body)
    location = body.get("location")
    if not isinstance(location, str) or not location:
        raise invalid_content("The 'location' property is required.")
    changes = _check_properties(body.get("properties", {}), min_size)
    return location, check_tags(body.get("tags", {})), changes


def parse_patch_body(body, min_size: int = DEFAULT_MIN_SIZE) -> tuple[str | None, dict | None, dict]:
    """PATCH 본문에서 (location, tags, properties)를 꺼낸다. 없는 것은 None이나 빈 dict다."""
    body = _check_top_level(body)
    location = body.get("location")
    if location is not None and (not isinstance(location, str) or not location):
        raise invalid_content("The 'location' property must be a string.")
    tags = check_tags(body["tags"]) if "tags" in body else None
    return location, tags, _check_properties(body.get("properties", {}), min_size)


# --- 응답 본문 ---


def default_export_rule(protocol_types: list[str]) -> dict:
    """요청에 exportPolicy가 없을 때 서비스가 채우는 규칙 [녹화 V1]. nfsv41 플래그가 protocolTypes를
    따르는 것은 [추론]이다 (결정 16)."""
    return {
        "ruleIndex": 1, "unixReadOnly": False, "unixReadWrite": True, "cifs": False,
        "nfsv3": "NFSv3" in protocol_types, "nfsv41": "NFSv4.1" in protocol_types,
        "allowedClients": "0.0.0.0/0",
        "kerberos5ReadOnly": False, "kerberos5ReadWrite": False, "kerberos5iReadOnly": False,
        "kerberos5iReadWrite": False, "kerberos5pReadOnly": False, "kerberos5pReadWrite": False,
        "hasRootAccess": True, "chownMode": "Restricted",
    }


def actual_throughput_mibps(props: dict) -> float:
    """Auto QoS 볼륨의 처리량 한도 = 할당량(2진 TiB) × 서비스 수준 단가. Premium 100 GiB = 6.25 [녹화 V1]."""
    return props["usageThreshold"] / TIB * MIBPS_PER_TIB[props["serviceLevel"]]


def volume_body(res: Resource) -> dict:
    parts = res.id.split("/")  # .../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}
    return {
        "id": res.id,
        "name": f"{parts[-5]}/{parts[-3]}/{res.name}",
        "type": VOLUME_TYPE,
        "location": res.location,
        "tags": res.tags,
        "properties": {
            "provisioningState": res.provisioning_state,
            **res.properties,  # mountTargets는 생성 작업이 성공한 뒤 처리기가 넣는다 (결정 12)
            "actualThroughputMibps": actual_throughput_mibps(res.properties),
        },
    }


# --- 흐름 ---


def _id(subscription_id: str, resource_group: str, account: str, pool: str, name: str) -> str:
    check_resource_group_name(resource_group)
    check_account_name(account)
    check_pool_name(pool)
    check_volume_name(name)
    return volume_id(subscription_id, resource_group, account, pool, name)


def _ensure_terminal(tx: Tx, res: Resource) -> None:
    """진행 중인 볼륨에 PUT·PATCH·DELETE는 대기열에 넣지 않고 409다 [녹화 V6] (결정 14)."""
    if tx.active_operation(res.id) is not None:
        raise ArmError(
            409, "RequestConflict",
            f"Cannot modify resource with id '{res.id}' because the resource entity provisioning state "
            "is not terminal. Please wait for the provisioning state to become terminal and then retry "
            "the request.")


def _service_level_mismatch(requested: str, pool_level: str) -> ArmError:
    return invalid_content(
        f"The 'properties.serviceLevel' value '{requested}' differs from the capacity pool's "
        f"'{pool_level}'. Moving a volume to another service level is not supported by this ANF clone.")


def _new_volume(tx: Tx, rid: str, parent_id: str, subscription_id: str, resource_group: str,
                name: str, location: str, tags: dict, changes: dict) -> Resource:
    pool = tx.get_resource(parent_id)
    if pool is None:
        # 녹화 N6의 게이트웨이 문구
        raise ArmError(
            404, "ParentResourceNotFound",
            "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools/volumes', "
            f"because the parent resource '{parent_id}' could not be found.")
    if pool.provisioning_state == "Deleting":
        raise ArmError(409, "Conflict",
                       f"Cannot create volume '{rid}' because its parent capacity pool "
                       f"'{pool.id}' is being deleted.")
    if pool.provisioning_state != "Succeeded":
        raise ArmError(400, "BadRequest", "Volume cannot be created in a pool that isn't in state succeeded.")
    if pool.properties["qosType"] == "Manual":
        raise invalid_content("Volumes in a Manual QoS capacity pool are not supported by this ANF clone.")
    for key in ("creationToken", "usageThreshold", "subnetId"):
        if key not in changes:
            raise invalid_content(f"The 'properties.{key}' property is required.")

    props = {
        "fileSystemId": str(uuid.uuid4()),  # agent의 볼륨 UUID이자 멱등 키 (결정 9)
        "serviceLevel": pool.properties["serviceLevel"],  # 풀 값을 물려받는다 [녹화 V1]
        "protocolTypes": ["NFSv3"], "networkFeatures": "Basic", "unixPermissions": "0770",
        "snapshotDirectoryVisible": True, "securityStyle": "unix",
    }
    props.update({key: changes[key] for key in _SETTABLE if key in changes})
    props["exportPolicy"] = {"rules": [default_export_rule(props["protocolTypes"])]}
    for key in _SERVICE_HELD:
        if key in changes and changes[key] != props[key]:
            if key == "serviceLevel":
                raise _service_level_mismatch(changes[key], props[key])
            raise invalid_content(f"The value of 'properties.{key}' is not supported by this ANF clone.")

    token = props["creationToken"].lower()
    if any(v.properties["creationToken"].lower() == token for v in tx.all_of_type(VOLUME_TYPE)):
        # 클론에는 마운트 대상이 하나뿐이라 클론 전체에서 유일하다 (결정 15)
        raise ArmError(400, "BadRequest", "File path already in use.")
    # 상태와 무관하게 모든 볼륨 행이 할당량을 예약한다 (풀 설계 §6)
    allocated = sum(v.properties["usageThreshold"] for v in tx.list_children(parent_id, VOLUME_TYPE))
    if allocated + props["usageThreshold"] > pool.properties["size"]:
        raise ArmError(400, "BadRequest", "Pool size too small for total volume size.")
    return Resource(
        id=rid, type=VOLUME_TYPE, subscription_id=subscription_id, resource_group=resource_group,
        name=name, location=location, tags=tags, properties=props, provisioning_state="Creating",
        parent_id=parent_id,
    )


def _apply_update(props: dict, changes: dict) -> dict:
    """갱신(PUT·PATCH)의 새 properties. 같은 값을 다시 보내는 것은 허용한다 (결정 4)."""
    def same(key):
        if key == "subnetId":  # ARM ID는 대소문자를 구분하지 않는다
            return changes[key].lower() == props[key].lower()
        return changes[key] == props[key]

    for key in changes:
        if key in _IMMUTABLE and not same(key):
            raise ArmError(400, "BadRequest", _IMMUTABLE[key])
    for key in changes:
        if key in _IMMUTABLE or key in _CHANGEABLE or same(key):
            continue
        if key == "serviceLevel":
            raise _service_level_mismatch(changes[key], props[key])
        raise invalid_content(f"Changing 'properties.{key}' is not supported by this ANF clone.")
    return {**props, **{key: changes[key] for key in _CHANGEABLE if key in changes}}


def get_volume(store: StateStore, subscription_id: str, resource_group: str, account: str,
               pool: str, name: str) -> Resource:
    rid = _id(subscription_id, resource_group, account, pool, name)
    res = store.get_resource(rid)
    if res is None:
        raise not_found(rid)
    return res


def list_volumes(store: StateStore, subscription_id: str, resource_group: str, account: str,
                 pool: str) -> list[Resource]:
    check_resource_group_name(resource_group)
    check_account_name(account)
    check_pool_name(pool)
    parent = pool_id(subscription_id, resource_group, account, pool)
    if store.get_resource(parent) is None:
        raise not_found(parent)
    return store.list_children(parent, VOLUME_TYPE)


def put_volume(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
               name: str, body, correlation_id: str | None,
               min_size: int = DEFAULT_MIN_SIZE) -> tuple[bool, Resource, Operation]:
    """새 볼륨이면 Creating + CREATE 작업(201), 있으면 Updating + UPDATE 작업(200).
    반환: (새로 만들었는지, 리소스, 작업)."""
    rid = _id(subscription_id, resource_group, account, pool, name)
    location, tags, changes = parse_put_body(body, min_size)
    parent_id = pool_id(subscription_id, resource_group, account, pool)
    with store.transaction() as tx:
        existing = tx.get_resource(rid)
        if existing is None:
            res = _new_volume(tx, rid, parent_id, subscription_id, resource_group, name, location,
                              tags, changes)
            op = tx.create_operation(res, "CREATE", "Creating", correlation_id=correlation_id)
            tx.put_resource(res)
            return True, res, op
        _ensure_terminal(tx, existing)
        if existing.location.lower() != location.lower():
            raise location_conflict(existing.name, existing.resource_group, existing.location, location)
        # 빠진 속성은 기존 값을 유지한다 (풀 결정 8과 같음)
        properties = _apply_update(existing.properties, changes)
        previous = {"tags": existing.tags, "properties": existing.properties}
        op = tx.create_operation(existing, "UPDATE", "Updating",
                                 previous=previous, correlation_id=correlation_id)
        existing.tags = tags
        existing.properties = properties
        existing.provisioning_state = "Updating"
        tx.put_resource(existing)
        return False, existing, op


def patch_volume(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                 name: str, body, correlation_id: str | None,
                 min_size: int = DEFAULT_MIN_SIZE) -> tuple[Resource, Operation]:
    """tags만 바꿔도 비동기다: Patching + PATCH 작업(202) [녹화 V3]. 실패하면 워커가 이전 값으로 되돌린다."""
    rid = _id(subscription_id, resource_group, account, pool, name)
    location, tags, changes = parse_patch_body(body, min_size)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            raise not_found(rid)
        _ensure_terminal(tx, res)
        if location is not None and res.location.lower() != location.lower():
            raise location_conflict(res.name, res.resource_group, res.location, location)
        properties = _apply_update(res.properties, changes)
        previous = {"tags": res.tags, "properties": res.properties}
        op = tx.create_operation(res, "PATCH", "Patching", previous=previous, correlation_id=correlation_id)
        if tags is not None:
            res.tags = tags
        res.properties = properties
        res.provisioning_state = "Patching"
        tx.put_resource(res)
        return res, op


def delete_volume(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                  name: str, correlation_id: str | None) -> Operation | None:
    """있으면 Deleting + DELETE 작업(202), 없으면 None(204). 스냅샷도 함께 지워진다: agent가 스냅샷부터 지우고,
    작업이 끝나면 볼륨 행과 스냅샷 행이 한 트랜잭션에서 지워진다. 그래서 진행 중인 스냅샷 작업이 있으면 409다
    (스냅샷 설계 결정 2)."""
    rid = _id(subscription_id, resource_group, account, pool, name)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            return None
        _ensure_terminal(tx, res)
        for snap in tx.list_children(rid, SNAPSHOT_TYPE):
            if tx.active_operation(snap.id) is not None:
                raise ArmError(409, "Conflict",
                               f"Cannot delete volume '{rid}' because an operation is in progress on its snapshot "
                               f"'{snap.id}'. Wait until it is finished, and then retry.")
        op = tx.create_operation(res, "DELETE", "Deleting", correlation_id=correlation_id)
        res.provisioning_state = "Deleting"
        tx.put_resource(res)
        return op


# --- 처리기: 데이터 플레인 작업 (결정 11·12) ---

_AGENT_PROTOCOL = {"NFSv3": "nfs3", "NFSv4.1": "nfs4.1"}


def make_handlers(store: StateStore, storage) -> dict:
    """볼륨 작업 처리기. storage는 agent 클라이언트(`StorageClient`)다.

    CREATE·UPDATE·PATCH는 모두 agent에 볼륨을 보장하고 data LIF IP로 mountTargets를 기록한다.
    agent 요청은 멱등이라 재시작 뒤 다시 실행해도 같다. DELETE는 agent 볼륨을 지운다.
    실패하면 예외가 그대로 나가고 공통 워커가 작업을 Failed로 끝낸다.
    """
    async def ensure(op: Operation) -> None:
        props = store.get_resource(op.resource_id).properties
        fsid = props["fileSystemId"]
        ip = await storage.ensure_volume(
            fsid, "/" + props["creationToken"], props["usageThreshold"], int(props["unixPermissions"]),
            _AGENT_PROTOCOL[props["protocolTypes"][0]], correlation_id=op.correlation_id)
        with store.transaction() as tx:
            res = tx.get_resource(op.resource_id)
            # 워커가 끝낼 때 리소스를 다시 읽으므로 여기서 쓴 값이 남는다
            res.properties = {**res.properties, "mountTargets": [
                {"mountTargetId": fsid, "fileSystemId": fsid, "ipAddress": ip}]}
            tx.put_resource(res)

    async def delete(op: Operation) -> None:
        props = store.get_resource(op.resource_id).properties
        await storage.delete_volume(props["fileSystemId"], correlation_id=op.correlation_id)

    return {(VOLUME_TYPE, "CREATE"): ensure, (VOLUME_TYPE, "UPDATE"): ensure,
            (VOLUME_TYPE, "PATCH"): ensure, (VOLUME_TYPE, "DELETE"): delete}
