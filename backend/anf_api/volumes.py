"""볼륨 (FR-04): 요청 본문 검사, 응답 본문, PUT·PATCH·DELETE·GET·목록 흐름 (볼륨 설계 §3, §4).

볼륨은 풀 아래의 ARM 리소스이고, 데이터 플레인에서는 storage agent의 ONTAP 볼륨(thin LV + ext4, NFS export)이다.
이 모듈은 컨트롤 플레인 규칙과, agent를 부르는 작업 처리기(`make_handlers`)를 맡는다.
규칙 위반은 검사와 쓰기를 같은 트랜잭션에서 하고 동기로 거절한다
(결정 13·14). 검사 순서: 이름 → 본문 형식 → 부모 존재·상태 → 진행 중 작업 → 불변 속성 → 경로 중복 → 용량.
스냅샷에서 만드는 볼륨(`snapshotId`, FR-07)은 부모 검사 뒤에 원본 스냅샷을 검사한다 (복원 설계 결정 13).
처리량 한도(FR-08): Auto 풀 볼륨은 할당량 공식, Manual 풀 볼륨은 `throughputMibps`(필수, 1~4,500)다. 풀 QoS 유형에
기대는 검사는 부모 상태 검사 뒤에, Manual 풀 예산은 용량 검사 뒤에 한다 (처리량 설계 결정 3·4·7, §4.2).

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
from anf_api.capacity_pools import (
    MIBPS_PER_TIB,
    TIB,
    total_throughput_mibps,
    utilized_throughput_mibps,
    volume_throughput_mibps,
)
from anf_api.snapshots import ensure_not_cloning, snapshot_not_found
from anf_api.state_store import Operation, Resource, StateStore, Tx

GIB = 1 << 30
DEFAULT_MIN_SIZE = 50 * GIB  # [스펙 2]. 검증할 때만 ANF_MIN_VOLUME_SIZE_GIB로 낮춘다 (결정 3)
_MAX_SIZE = 100 * TIB  # 일반 볼륨 상한 [스펙 2 설명]. large volume은 범위 밖
_MAX_THROUGHPUT = 4500  # 일반 볼륨의 Manual QoS 한도 상한 MiB/s [처리량 브리프 스펙 S1, 문서 D4]

_TOKEN_CHARS = re.compile(r"[a-zA-Z0-9\-_]*")
_SUBNET_ID = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.Network"
    r"/virtualNetworks/[^/]+/subnets/[^/]+", re.IGNORECASE)
_SNAPSHOT_ID = re.compile(
    r"/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.NetApp/netAppAccounts/[^/]+"
    r"/capacityPools/[^/]+/volumes/[^/]+/snapshots/[^/]+", re.IGNORECASE)
_UNIX_PERMISSIONS = re.compile(r"[0-7]{4}")
_PROTOCOLS = ("NFSv3", "NFSv4.1")
_NETWORK_FEATURES = ("Basic", "Standard")

_READ_ONLY = {"id", "name", "type", "etag", "systemData"}
_READ_ONLY_PROPERTIES = {"provisioningState", "actualThroughputMibps", "mountTargets", "originatingResourceId"}
# 클론이 한 가지 값만 지원하고 응답에는 넣지 않는 속성. 그 값이면 받는다.
# deleteBaseSnapshot: 스펙과 문서가 지우는 대상을 다르게 읽혀 false만 받는다 (복원 설계 결정 7)
_FIXED = {"kerberosEnabled": False, "ldapEnabled": False, "isLargeVolume": False, "coolAccess": False,
          "deleteBaseSnapshot": False}
# 값이 있으면 미룬 기능이다: 백업 복원, 데이터 보호(복제)
_NOT_YET = {"backupId", "dataProtection"}
# 생성 때 요청 값을 쓰는 속성. throughputMibps는 Manual 풀 볼륨에만 있다 (처리량 결정 3·4)
_SETTABLE = ("creationToken", "usageThreshold", "subnetId", "protocolTypes", "networkFeatures", "unixPermissions",
             "throughputMibps")
# 서비스가 정하는 값. 요청 값이 그와 다르면 미룬 기능이다
_SERVICE_HELD = ("serviceLevel", "snapshotDirectoryVisible", "securityStyle", "exportPolicy")
_PROPERTIES = {*_SETTABLE, *_SERVICE_HELD, "fileSystemId", "snapshotId", *_FIXED, *_NOT_YET}
# 생성 뒤 바꿀 수 없는 속성과 ANF 오류 문서의 문구 [볼륨 브리프 문서 7]. subnetId·snapshotId 문구는 같은 모양으로 지었다.
# snapshotId는 생성 때만 쓴다 (x-ms-mutability read, create). 원래 없던 볼륨에 넣는 것도 바꾸는 것이다 (복원 결정 12)
_IMMUTABLE = {
    "creationToken": "CreationToken cannot be changed.",
    "subnetId": "SubnetId cannot be changed.",
    "fileSystemId": "FileSystemId cannot be changed.",
    "snapshotId": "SnapshotId cannot be changed.",
}
_ARM_IDS = ("subnetId", "snapshotId")  # ARM ID는 대소문자를 구분하지 않는다
# 생성 뒤에도 바꿀 수 있는 속성. networkFeatures는 Azure 네트워크 개념이라 데이터 효과가 없고 저장만 한다.
# throughputMibps는 Manual 볼륨의 한도이고, 처리기가 agent에 새 값을 건다 (처리량 결정 1·8)
_CHANGEABLE = {"networkFeatures", "throughputMibps"}


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
    if key == "throughputMibps":  # 소수를 받고 받은 값을 그대로 저장한다 (처리량 결정 3). 범위는 _check_throughput_range
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _throughput_range()
        return float(value)
    if key == "snapshotId":  # 스냅샷의 ARM 리소스 ID (format: arm-id) [복원 브리프 스펙 1·2]
        if not isinstance(value, str) or not _SNAPSHOT_ID.fullmatch(value):
            raise invalid_content(
                "The 'properties.snapshotId' property must be a snapshot resource ID: /subscriptions/{id}"
                "/resourceGroups/{group}/providers/Microsoft.NetApp/netAppAccounts/{account}/capacityPools/{pool}"
                "/volumes/{volume}/snapshots/{snapshot}.")
        return value
    # fileSystemId: 읽기 전용이지만 같은 값을 다시 보내는 것은 허용된다 [볼륨 브리프 문서 7]
    if not isinstance(value, str):
        raise invalid_content("The 'properties.fileSystemId' property must be a string.")
    return value


def _throughput_range() -> ArmError:
    return invalid_content("The 'properties.throughputMibps' property must be a number from 1 to 4500.")


def _check_throughput_range(changes: dict) -> None:
    """새 값의 범위 1~4,500 (처리량 결정 3). 생성은 늘 보고, 갱신은 값을 바꿀 때만 본다 (_settle_throughput)."""
    mibps = changes.get("throughputMibps")
    if mibps is not None and not 1 <= mibps <= _MAX_THROUGHPUT:  # nan도 여기서 거절된다
        raise _throughput_range()


def _settle_throughput(props: dict, changes: dict) -> dict:
    """갱신: 저장된 값과 소수 셋째 자리까지 같으면 바꾸지 않는 것으로 보고 저장된 값을 둔다. 그때는 범위를 보지
    않는다. Auto → Manual 전환이 채운 값은 1 미만일 수 있어(Standard 50 GiB = 0.781) GET 본문 재PUT이 되게
    하려는 것이다 (처리량 설계 §9-5)."""
    mibps, old = changes.get("throughputMibps"), props.get("throughputMibps")
    if mibps is not None and old is not None and round(mibps, 3) == round(old, 3):
        return {**changes, "throughputMibps": old}
    _check_throughput_range(changes)
    return changes


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
        elif not (key in ("unixPermissions", "snapshotId", "throughputMibps") and value is None):  # nullable [스펙 2]
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


def parse_revert_body(body) -> str:
    """revert 본문 `{"snapshotId": <스냅샷 ARM ID>}`의 스냅샷 ID. 스펙상 선택이지만 클론은 필수다 (되돌리기 설계 결정 6)."""
    if not isinstance(body, dict):
        raise invalid_content("The request content must be a JSON object.")
    for key in body:
        if key != "snapshotId":
            raise unknown_property(key)
    value = body.get("snapshotId")
    if not isinstance(value, str):
        raise invalid_content("The 'snapshotId' property is required and must be a snapshot resource ID.")
    if not _SNAPSHOT_ID.fullmatch(value):
        raise invalid_content(
            "The 'snapshotId' property must be a snapshot resource ID: /subscriptions/{id}/resourceGroups/{group}"
            "/providers/Microsoft.NetApp/netAppAccounts/{account}/capacityPools/{pool}/volumes/{volume}"
            "/snapshots/{snapshot}.")
    return value


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
            # Auto는 할당량 공식(Premium 100 GiB = 6.25 [녹화 V1]), Manual은 throughputMibps (처리량 결정 2·5)
            "actualThroughputMibps": volume_throughput_mibps(res.properties),
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


def _check_qos_type(pool: Resource, changes: dict, creating: bool) -> None:
    """풀 QoS 유형에 기대는 throughputMibps 규칙. 실서비스 기본값과 거절 코드는 [미확인]이라 클론 규칙이다
    (처리량 결정 3·4). Auto 볼륨 한도는 할당량이 정한다."""
    if pool.properties["qosType"] == "Auto":
        if "throughputMibps" in changes:
            raise ArmError(400, "BadRequest", "The 'properties.throughputMibps' property can be set only for a "
                                              "volume in a Manual QoS capacity pool.")
    elif creating and "throughputMibps" not in changes:
        raise invalid_content(
            "The 'properties.throughputMibps' property is required for a volume in a Manual QoS capacity pool.")


def _check_budget(tx: Tx, pool: Resource, volume_id: str, mibps: float) -> None:
    """Manual 풀: 다른 모든 볼륨 행(상태와 무관)의 한도 합 + 새 값 ≤ 풀 총 처리량, 소수 셋째 자리에서 비교한다
    (처리량 결정 7) [문서 D5·D7]. Auto 풀은 보지 않는다: 할당량 규칙이 같은 것을 보장하고, 반올림한 Auto 한도의
    합은 총 처리량을 조금 넘을 수 있다 (Premium 3 GiB × 341 = 64.108 > 64)."""
    total = round(total_throughput_mibps(pool.properties), 3)
    used = utilized_throughput_mibps([v for v in tx.list_children(pool.id, VOLUME_TYPE) if v.id != volume_id])
    if round(used + mibps, 3) > total:
        free = max(round(total - used, 3), 0.0)
        raise ArmError(400, "BadRequest", f"Requested throughput not available. Capacity pool '{pool.name}' has "
                                          f"{total} MiB/s in total and {free} MiB/s left for this volume.")


def _check_throughput_change(tx: Tx, res: Resource, changes: dict) -> None:
    """갱신(PUT·PATCH)의 한도 규칙. 예산은 한도를 올릴 때만 본다: 줄이거나 같은 값이면 예산을 더 쓰지 않는다.
    Auto → Manual 전환으로 옮겨 받은 반올림 값의 합이 총 처리량을 조금 넘는 풀에서도 줄이기는 된다."""
    pool = tx.get_resource(res.parent_id)
    _check_qos_type(pool, changes, creating=False)
    mibps = changes.get("throughputMibps")
    if mibps is not None and mibps > res.properties["throughputMibps"]:
        _check_budget(tx, pool, res.id, mibps)


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
    _check_qos_type(pool, changes, creating=True)
    for key in ("creationToken", "usageThreshold", "subnetId"):
        if key not in changes:
            raise invalid_content(f"The 'properties.{key}' property is required.")

    props = {
        "fileSystemId": str(uuid.uuid4()),  # agent의 볼륨 UUID이자 멱등 키 (결정 9)
        "serviceLevel": pool.properties["serviceLevel"],  # 풀 값을 물려받는다 [녹화 V1]
        "protocolTypes": ["NFSv3"], "networkFeatures": "Basic", "unixPermissions": "0770",
        "snapshotDirectoryVisible": True, "securityStyle": "unix",
    }
    if "snapshotId" in changes:
        snap, origin = _restore_source(tx, rid, changes)
        # 저장된 스냅샷 ID를 남긴다. 주지 않은 프로토콜과 권한은 원본 볼륨 값이다 (복원 결정 3)
        props.update(snapshotId=snap.id, protocolTypes=origin.properties["protocolTypes"],
                     unixPermissions=origin.properties["unixPermissions"])
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
    if "throughputMibps" in props:  # Manual 풀 (_check_qos_type)
        _check_budget(tx, pool, rid, props["throughputMibps"])
    return Resource(
        id=rid, type=VOLUME_TYPE, subscription_id=subscription_id, resource_group=resource_group,
        name=name, location=location, tags=tags, properties=props, provisioning_state="Creating",
        parent_id=parent_id,
    )


def _restore_source(tx: Tx, rid: str, changes: dict) -> tuple[Resource, Resource]:
    """snapshotId의 (스냅샷, 그 볼륨). 검사 순서: 계정 → 스냅샷 존재 → 진행 중 작업 → 스냅샷 상태 → 볼륨 상태 →
    크기 하한 (복원 설계 결정 2·4·13, §4.2). ANF의 거절 코드는 [미확인]이라 문구는 클론 규칙이다."""
    snapshot_rid = changes["snapshotId"]
    account = rid.split("/capacityPools/", 1)[0]
    if not snapshot_rid.lower().startswith(account.lower() + "/capacitypools/"):
        raise ArmError(400, "BadRequest", f"The snapshot '{snapshot_rid}' must be in the same NetApp account as the "
                                          f"new volume '{rid}'.")
    snap = tx.get_resource(snapshot_rid)
    if snap is None:
        parts = snapshot_rid.split("/")  # .../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}/snapshots/{s}
        raise snapshot_not_found(parts[-1], parts[-7], parts[-5], parts[-3])
    origin = tx.get_resource(snap.parent_id)
    for busy in (snap, origin):
        if tx.active_operation(busy.id) is not None:
            raise ArmError(409, "Conflict", f"Cannot create volume '{rid}' from snapshot '{snap.id}' because an "
                                            f"operation is in progress on '{busy.id}'. Wait until it is finished, "
                                            "and then retry.")
    if snap.provisioning_state != "Succeeded":
        raise ArmError(400, "BadRequest", f"Volume cannot be created from snapshot '{snap.id}' because the snapshot "
                                          "isn't in state succeeded.")
    if origin.provisioning_state != "Succeeded":
        raise ArmError(400, "BadRequest", f"Volume cannot be created from snapshot '{snap.id}' because its volume "
                                          "isn't in state succeeded.")
    floor = origin.properties["usageThreshold"]
    if changes["usageThreshold"] < floor:  # ext4 축소는 오프라인뿐이다 (결정 4)
        raise ArmError(400, "BadRequest", "The 'properties.usageThreshold' of a volume created from a snapshot must "
                                          f"be at least the source volume's {floor // GIB} GiB.")
    return snap, origin


def _apply_update(props: dict, changes: dict) -> dict:
    """갱신(PUT·PATCH)의 새 properties. 같은 값을 다시 보내는 것은 허용한다 (결정 4)."""
    def same(key):
        old = props.get(key)  # snapshotId는 스냅샷에서 만든 볼륨에만 있다
        if key in _ARM_IDS:
            return old is not None and changes[key].lower() == old.lower()
        return changes[key] == old

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
            _check_throughput_range(changes)  # 본문 검사라 풀 검사보다 먼저다
            res = _new_volume(tx, rid, parent_id, subscription_id, resource_group, name, location,
                              tags, changes)
            op = tx.create_operation(res, "CREATE", "Creating", correlation_id=correlation_id)
            tx.put_resource(res)
            return True, res, op
        _ensure_terminal(tx, existing)
        if existing.location.lower() != location.lower():
            raise location_conflict(existing.name, existing.resource_group, existing.location, location)
        # 빠진 속성은 기존 값을 유지한다 (풀 결정 8과 같음)
        changes = _settle_throughput(existing.properties, changes)
        properties = _apply_update(existing.properties, changes)
        _check_throughput_change(tx, existing, changes)
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
        changes = _settle_throughput(res.properties, changes)
        properties = _apply_update(res.properties, changes)
        _check_throughput_change(tx, res, changes)
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
    (스냅샷 설계 결정 2). 이 볼륨의 스냅샷에서 새 볼륨을 만드는 중이어도 409다 (복원 설계 결정 9)."""
    rid = _id(subscription_id, resource_group, account, pool, name)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            return None
        _ensure_terminal(tx, res)
        ensure_not_cloning(tx, res.id, "delete")
        for snap in tx.list_children(rid, SNAPSHOT_TYPE):
            if tx.active_operation(snap.id) is not None:
                raise ArmError(409, "Conflict",
                               f"Cannot delete volume '{rid}' because an operation is in progress on its snapshot "
                               f"'{snap.id}'. Wait until it is finished, and then retry.")
        op = tx.create_operation(res, "DELETE", "Deleting", correlation_id=correlation_id)
        res.provisioning_state = "Deleting"
        tx.put_resource(res)
        return op


def revert_volume(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                  name: str, body, correlation_id: str | None) -> Operation:
    """볼륨을 스냅샷으로 되돌린다: Reverting + POST 작업(202) [녹화 R3]. 작업 입력에 고른 스냅샷을 남긴다.
    검사 순서: 이름 → 본문 → 볼륨 존재 → 볼륨 진행 중 작업 → 볼륨 상태 → 스냅샷 존재 → 그 볼륨 스냅샷의
    진행 중 작업 → 스냅샷 상태 (되돌리기 설계 결정 6, §4.2). 이 볼륨의 스냅샷에서 새 볼륨을 만드는 중이면 볼륨 진행 중
    작업처럼 409다: 되돌리기가 더 새 스냅샷을 지운다 (복원 설계 결정 9)."""
    rid = _id(subscription_id, resource_group, account, pool, name)
    snapshot_rid = parse_revert_body(body)
    if not snapshot_rid.lower().startswith(rid.lower() + "/snapshots/"):
        raise ArmError(400, "BadRequest", f"The snapshot '{snapshot_rid}' does not belong to the volume '{rid}'.")
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            raise not_found(rid)
        _ensure_terminal(tx, res)
        ensure_not_cloning(tx, res.id, "revert")
        if res.provisioning_state != "Succeeded":
            raise ArmError(400, "BadRequest", "Volume cannot be reverted when it isn't in state succeeded.")
        snap = tx.get_resource(snapshot_rid)
        if snap is None:
            raise snapshot_not_found(snapshot_rid.rsplit("/", 1)[-1], account, pool, name)
        for other in tx.list_children(rid, SNAPSHOT_TYPE):
            if tx.active_operation(other.id) is not None:
                raise ArmError(409, "Conflict",
                               f"Cannot revert volume '{rid}' because an operation is in progress on its snapshot "
                               f"'{other.id}'. Wait until it is finished, and then retry.")
        if snap.provisioning_state != "Succeeded":
            raise ArmError(400, "BadRequest", f"Volume cannot be reverted to snapshot '{snap.id}' because the "
                                              "snapshot isn't in state succeeded.")
        op = tx.create_operation(res, "POST", "Reverting", params={"snapshotId": snap.id},
                                 correlation_id=correlation_id)
        res.provisioning_state = "Reverting"
        tx.put_resource(res)
        return op


# --- 처리기: 데이터 플레인 작업 (결정 11·12) ---

_AGENT_PROTOCOL = {"NFSv3": "nfs3", "NFSv4.1": "nfs4.1"}


def make_handlers(store: StateStore, storage) -> dict:
    """볼륨 작업 처리기. storage는 agent 클라이언트(`StorageClient`)다.

    CREATE·UPDATE·PATCH는 모두 agent에 볼륨을 보장하고 data LIF IP로 mountTargets를 기록한다.
    agent 요청은 멱등이라 재시작 뒤 다시 실행해도 같다. DELETE는 agent 볼륨을 지운다.
    실패하면 예외가 그대로 나가고 공통 워커가 작업을 Failed로 끝낸다.
    스냅샷에서 만드는 볼륨은 끝날 때까지 agent에 원본(FlexClone 필드)을 넘긴다 (복원 설계 결정 10·14).
    """
    def clone_source(props: dict) -> tuple[str, str] | None:
        """(원본 볼륨 uuid, 원본 스냅샷 uuid). 한 번 끝난 볼륨(originatingResourceId)은 일반 볼륨이다.
        끝나기 전에는 원본 보호(결정 9)가 있어 원본 행이 남아 있다."""
        if "snapshotId" not in props or "originatingResourceId" in props:
            return None
        snap = store.get_resource(props["snapshotId"])
        return store.get_resource(snap.parent_id).properties["fileSystemId"], snap.properties["snapshotId"]

    async def ensure(op: Operation) -> None:
        props = store.get_resource(op.resource_id).properties
        fsid = props["fileSystemId"]
        clone = clone_source(props)
        ip = await storage.ensure_volume(
            fsid, "/" + props["creationToken"], props["usageThreshold"], int(props["unixPermissions"]),
            _AGENT_PROTOCOL[props["protocolTypes"][0]], correlation_id=op.correlation_id, clone=clone,
            qos=volume_throughput_mibps(props))  # 응답의 actualThroughputMibps와 같은 값 (처리량 결정 2·8)
        with store.transaction() as tx:
            res = tx.get_resource(op.resource_id)
            # 워커가 끝낼 때 리소스를 다시 읽으므로 여기서 쓴 값이 남는다
            res.properties = {**res.properties, "mountTargets": [
                {"mountTargetId": fsid, "fileSystemId": fsid, "ipAddress": ip}]}
            tx.put_resource(res)
        # agent가 실패한 되돌리기를 끝냈으면 더 새 스냅샷이 지워졌다 (되돌리기 결정 2·8). 작업 중이 아닌 Succeeded 행만
        # 맞춘다: 실패 행은 사용자가 지우고, 작업 중인 행은 그 작업이 끝낸다
        with store.transaction() as tx:
            settled = [s for s in tx.list_children(op.resource_id, SNAPSHOT_TYPE)
                       if s.provisioning_state == "Succeeded" and tx.active_operation(s.id) is None]
        if settled:
            remaining = await storage.snapshot_uuids(fsid, correlation_id=op.correlation_id)
            with store.transaction() as tx:
                for snap in settled:
                    if snap.properties["snapshotId"] not in remaining and tx.active_operation(snap.id) is None:
                        tx.delete_resource(snap.id)
        if clone is not None:
            # 다 만들었다: agent가 찍은 base 스냅샷을 Creating 없이 Succeeded 행으로 더하고, originatingResourceId로
            # 원본 보호를 푼다. 한 트랜잭션이라 재시작 뒤 다시 실행해도 행이 겹치지 않는다 (복원 결정 7·9)
            records = await storage.snapshot_records(fsid, correlation_id=op.correlation_id)
            with store.transaction() as tx:
                res = tx.get_resource(op.resource_id)
                for record in records:
                    tx.put_resource(Resource(
                        id=f"{res.id}/snapshots/{record['name']}", type=SNAPSHOT_TYPE,
                        subscription_id=res.subscription_id, resource_group=res.resource_group,
                        name=record["name"], location=res.location, tags={},
                        properties={"snapshotId": record["uuid"], "created": record["create_time"]},
                        provisioning_state="Succeeded", parent_id=res.id))
                res.properties = {**res.properties, "originatingResourceId": res.properties["snapshotId"]}
                tx.put_resource(res)

    async def delete(op: Operation) -> None:
        props = store.get_resource(op.resource_id).properties
        await storage.delete_volume(props["fileSystemId"], correlation_id=op.correlation_id)

    async def revert(op: Operation) -> None:
        """agent가 되돌리고 더 새 스냅샷을 지운다. 작업 ID가 멱등 키라 재시작 뒤 다시 실행해도 한 번만
        되돌린다 (되돌리기 설계 결정 4). agent에 남지 않은 스냅샷의 행을 지운다 (결정 8)."""
        props = store.get_resource(op.resource_id).properties
        snap = store.get_resource(op.params["snapshotId"])
        remaining = await storage.revert_volume(props["fileSystemId"], snap.properties["snapshotId"], op.id,
                                                correlation_id=op.correlation_id)
        with store.transaction() as tx:
            for other in tx.list_children(op.resource_id, SNAPSHOT_TYPE):
                if other.properties["snapshotId"] not in remaining:
                    tx.delete_resource(other.id)

    return {(VOLUME_TYPE, "CREATE"): ensure, (VOLUME_TYPE, "UPDATE"): ensure,
            (VOLUME_TYPE, "PATCH"): ensure, (VOLUME_TYPE, "DELETE"): delete, (VOLUME_TYPE, "POST"): revert}
