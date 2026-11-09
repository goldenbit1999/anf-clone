"""스냅샷 (FR-05): 요청 본문 검사, 응답 본문, PUT·GET·목록·DELETE 흐름, 처리기 (스냅샷 설계 §3, §4).

스냅샷은 볼륨 아래의 ARM 리소스(ProxyResource)이고, 데이터 플레인에서는 storage agent의 ONTAP 스냅샷
(읽기 전용 thin 스냅샷 LV, 볼륨 인스턴스가 `.snapshot/<이름>`으로 export)이다.
규칙 위반은 검사와 쓰기를 같은 트랜잭션에서 하고 동기로 거절한다.
검사 순서: 이름 → 본문 → 부모 존재·상태 → 진행 중 작업 → 개수 (결정 11).
"""

import uuid

from anf_api.arm_rules import (
    SNAPSHOT_TYPE,
    VOLUME_TYPE,
    ArmError,
    check_account_name,
    check_pool_name,
    check_resource_group_name,
    check_snapshot_name,
    check_volume_name,
    invalid_content,
    location_conflict,
    not_found,
    snapshot_id,
    unknown_property,
    volume_id,
)
from anf_api.state_store import Operation, Resource, StateStore, Tx

MAX_SNAPSHOTS = 255  # 볼륨마다 [브리프 문서]. ONTAP은 1023

_READ_ONLY = {"id", "name", "type", "systemData"}
_READ_ONLY_PROPERTIES = {"provisioningState", "snapshotId", "created"}


# --- 본문 ---


def parse_put_body(body) -> str:
    """PUT 본문의 location. 스냅샷 모델에 쓸 수 있는 속성은 없고 tags도 없다 (결정 12)."""
    if not isinstance(body, dict):
        raise invalid_content("The request content must be a JSON object.")
    for key in body:
        if key not in {"location", "properties"} and key not in _READ_ONLY:
            raise unknown_property(key)
    location = body.get("location")
    if not isinstance(location, str) or not location:
        raise invalid_content("The 'location' property is required.")
    props = body.get("properties", {})
    if not isinstance(props, dict):
        raise invalid_content("The 'properties' property must be an object.")
    for key in props:
        if key not in _READ_ONLY_PROPERTIES:
            raise unknown_property(f"properties.{key}")
    return location


def snapshot_body(res: Resource) -> dict:
    """snapshotId·created는 생성 작업이 한 번 성공한 뒤부터 보인다 (녹화 R1, 결정 9)."""
    parts = res.id.split("/")  # .../netAppAccounts/{a}/capacityPools/{p}/volumes/{v}/snapshots/{s}
    props = {"provisioningState": res.provisioning_state}
    if "created" in res.properties:
        props.update(snapshotId=res.properties["snapshotId"], created=res.properties["created"])
    return {
        "id": res.id,
        "name": f"{parts[-7]}/{parts[-5]}/{parts[-3]}/{res.name}",
        "type": SNAPSHOT_TYPE,
        "location": res.location,
        "properties": props,
    }


# --- 흐름 ---


def _volume_id(subscription_id: str, resource_group: str, account: str, pool: str, volume: str) -> str:
    check_resource_group_name(resource_group)
    check_account_name(account)
    check_pool_name(pool)
    check_volume_name(volume)
    return volume_id(subscription_id, resource_group, account, pool, volume)


def _ids(subscription_id: str, resource_group: str, account: str, pool: str, volume: str,
         name: str) -> tuple[str, str]:
    parent_id = _volume_id(subscription_id, resource_group, account, pool, volume)
    check_snapshot_name(name)
    return snapshot_id(subscription_id, resource_group, account, pool, volume, name), parent_id


def _ensure_volume_not_deleting(vol: Resource, rid: str) -> None:
    if vol.provisioning_state == "Deleting":
        raise ArmError(409, "Conflict", f"Cannot create or delete snapshot '{rid}' because its parent volume "
                                        f"'{vol.id}' is being deleted.")


def _ensure_volume_not_reverting(vol: Resource, snap: Resource) -> None:
    """되돌리기가 더 새 스냅샷을 지우는 동안 기존 스냅샷을 바꾸지 못한다 (되돌리기 설계 결정 7)."""
    if vol.provisioning_state == "Reverting":
        raise ArmError(409, "Conflict", f"Cannot change snapshot '{snap.id}' because its parent volume "
                                        f"'{vol.id}' is being reverted.")


def ensure_not_cloning(tx: Tx, rid: str, verb: str) -> None:
    """rid(스냅샷, 또는 그 스냅샷들의 볼륨)에서 만드는 중인 새 볼륨이 있으면 409다 (복원 설계 결정 9).
    새 볼륨이 처음 Succeeded가 되면(처리기가 originatingResourceId를 쓰면) 풀린다. 그 전에 원본 스냅샷이 사라지면
    agent가 생성을 끝낼 수 없고 같은 PUT으로도 회복하지 못한다."""
    for vol in tx.all_of_type(VOLUME_TYPE):
        source = vol.properties.get("snapshotId")
        if source is None or "originatingResourceId" in vol.properties:
            continue
        if source.lower() == rid.lower() or source.lower().startswith(rid.lower() + "/snapshots/"):
            raise ArmError(409, "Conflict", f"Cannot {verb} '{rid}' because volume '{vol.id}' is being created from "
                                            f"snapshot '{source}'. Wait until it is created, or delete it, and then "
                                            "retry.")


def snapshot_not_found(name: str, account: str, pool: str, volume: str) -> ArmError:
    return ArmError(  # 녹화 R1의 문구
        404, "ResourceNotFound",
        f"The requested snapshot '{name}' was not found on the volume '{account}/{pool}/{volume}'. "
        "Please check the requested snapshot. Please note: The snapshot may no longer be available "
        "based on configured snapshot policies.")


def _new_snapshot(tx: Tx, rid: str, vol: Resource, name: str, location: str) -> Resource:
    if vol.provisioning_state != "Succeeded":
        raise ArmError(400, "BadRequest", "Snapshot cannot be created on a volume that isn't in state succeeded.")
    if len(tx.list_children(vol.id, SNAPSHOT_TYPE)) >= MAX_SNAPSHOTS:
        # 문구는 ONTAP 525062에서 빌렸다. ANF의 코드는 [미확인]
        raise ArmError(400, "BadRequest", f"Cannot exceed maximum number of snapshots ({MAX_SNAPSHOTS}) for the volume.")
    return Resource(
        id=rid, type=SNAPSHOT_TYPE, subscription_id=vol.subscription_id, resource_group=vol.resource_group,
        name=name, location=location, tags={},
        properties={"snapshotId": str(uuid.uuid4())},  # agent의 스냅샷 uuid이자 멱등 키 (결정 9)
        provisioning_state="Creating", parent_id=vol.id,
    )


def get_snapshot(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                 volume: str, name: str) -> Resource:
    rid, _ = _ids(subscription_id, resource_group, account, pool, volume, name)
    res = store.get_resource(rid)
    if res is None:
        raise snapshot_not_found(name, account, pool, volume)
    return res


def list_snapshots(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                   volume: str) -> list[Resource]:
    parent_id = _volume_id(subscription_id, resource_group, account, pool, volume)
    if store.get_resource(parent_id) is None:
        raise not_found(parent_id)
    return store.list_children(parent_id, SNAPSHOT_TYPE)


def put_snapshot(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                 volume: str, name: str, body, correlation_id: str | None) -> tuple[bool, Resource, Operation]:
    """새 스냅샷이면 Creating + CREATE 작업(201). 있으면 Updating + UPDATE 작업(200): 바꿀 속성이 없으므로
    처리기는 데이터 플레인 보장만 다시 한다. 그래서 Failed 스냅샷도 다시 PUT하면 고쳐진다 (결정 3).
    반환: (새로 만들었는지, 리소스, 작업)."""
    rid, parent_id = _ids(subscription_id, resource_group, account, pool, volume, name)
    location = parse_put_body(body)
    with store.transaction() as tx:
        vol = tx.get_resource(parent_id)
        if vol is None:
            # 볼륨 녹화 N6과 같은 게이트웨이 문구
            raise ArmError(
                404, "ParentResourceNotFound",
                "Failed to perform 'write' on resource(s) of type 'netAppAccounts/capacityPools/volumes/snapshots', "
                f"because the parent resource '{parent_id}' could not be found.")
        _ensure_volume_not_deleting(vol, rid)
        existing = tx.get_resource(rid)
        if existing is None:
            res = _new_snapshot(tx, rid, vol, name, location)
            op = tx.create_operation(res, "CREATE", "Creating", correlation_id=correlation_id)
            tx.put_resource(res)
            return True, res, op
        _ensure_volume_not_reverting(vol, existing)
        tx.ensure_no_active_operation(rid)
        if existing.location.lower() != location.lower():
            raise location_conflict(existing.name, existing.resource_group, existing.location, location)
        op = tx.create_operation(existing, "UPDATE", "Updating", correlation_id=correlation_id)
        existing.provisioning_state = "Updating"
        tx.put_resource(existing)
        return False, existing, op


def delete_snapshot(store: StateStore, subscription_id: str, resource_group: str, account: str, pool: str,
                    volume: str, name: str, correlation_id: str | None) -> Operation | None:
    """있으면 Deleting + DELETE 작업(202), 없으면 None(204)."""
    rid, parent_id = _ids(subscription_id, resource_group, account, pool, volume, name)
    with store.transaction() as tx:
        res = tx.get_resource(rid)
        if res is None:
            return None
        vol = tx.get_resource(parent_id)
        _ensure_volume_not_deleting(vol, rid)
        _ensure_volume_not_reverting(vol, res)
        ensure_not_cloning(tx, res.id, "delete")
        op = tx.create_operation(res, "DELETE", "Deleting", correlation_id=correlation_id)
        res.provisioning_state = "Deleting"
        tx.put_resource(res)
        return op


# --- 처리기: 데이터 플레인 작업 ---


def make_handlers(store: StateStore, storage) -> dict:
    """스냅샷 작업 처리기. storage는 agent 클라이언트(`StorageClient`)다.

    CREATE·UPDATE는 agent에 스냅샷을 보장하고(멱등, uuid가 키) 만든 시각을 created로 기록한다.
    DELETE는 agent 스냅샷을 지운다. 실패하면 예외가 그대로 나가고 공통 워커가 작업을 Failed로 끝낸다.
    """
    async def ensure(op: Operation) -> None:
        res = store.get_resource(op.resource_id)
        fsid = store.get_resource(res.parent_id).properties["fileSystemId"]
        created = await storage.ensure_snapshot(fsid, res.properties["snapshotId"], res.name,
                                                correlation_id=op.correlation_id)
        with store.transaction() as tx:
            res = tx.get_resource(op.resource_id)
            res.properties = {**res.properties, "created": created}
            tx.put_resource(res)

    async def delete(op: Operation) -> None:
        res = store.get_resource(op.resource_id)
        fsid = store.get_resource(res.parent_id).properties["fileSystemId"]
        await storage.delete_snapshot(fsid, res.properties["snapshotId"], correlation_id=op.correlation_id)

    return {(SNAPSHOT_TYPE, "CREATE"): ensure, (SNAPSHOT_TYPE, "UPDATE"): ensure, (SNAPSHOT_TYPE, "DELETE"): delete}
