"""SQLite 상태 저장소: ARM 리소스와 비동기 작업 (ADR D-07, 계정 설계 §6.1).

- 쓰기는 `transaction()` 하나로 묶는다. 리소스 변경과 작업 생성을 같은 트랜잭션에 넣어,
  응답하기 전에 둘 다 저장되거나 둘 다 저장되지 않게 한다 (ADR §6.4).
- 리소스 ID는 대소문자를 구분하지 않고 찾는다 (ARM 이름 규칙, 설계 결정 9).
- 리소스 하나에 진행 중 작업 하나: 부분 유니크 인덱스가 DB 수준에서 보장한다 (설계 결정 6).
"""

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from anf_api.arm_rules import ArmError

TERMINAL_STATES = ("Succeeded", "Failed", "Canceled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id                 TEXT PRIMARY KEY COLLATE NOCASE,
    type               TEXT NOT NULL COLLATE NOCASE,
    parent_id          TEXT COLLATE NOCASE,
    subscription_id    TEXT NOT NULL COLLATE NOCASE,
    resource_group     TEXT NOT NULL COLLATE NOCASE,
    name               TEXT NOT NULL,
    location           TEXT NOT NULL,
    tags               TEXT NOT NULL,
    properties         TEXT NOT NULL,
    provisioning_state TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS resources_by_parent ON resources(parent_id);
CREATE TABLE IF NOT EXISTS operations (
    id              TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL COLLATE NOCASE,
    location        TEXT NOT NULL COLLATE NOCASE,
    resource_id     TEXT NOT NULL COLLATE NOCASE,
    resource_type   TEXT NOT NULL,
    action          TEXT NOT NULL,
    status          TEXT NOT NULL,
    previous        TEXT,
    error           TEXT,
    correlation_id  TEXT,
    start_time      TEXT NOT NULL,
    end_time        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS operations_one_active_per_resource
    ON operations(resource_id) WHERE status NOT IN ('Succeeded', 'Failed', 'Canceled');
"""


def utc_now() -> str:
    """ARM 형식의 UTC 시각 (예: 2026-11-07T12:00:00.123456Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class Resource:
    id: str
    type: str
    subscription_id: str
    resource_group: str
    name: str
    location: str
    tags: dict
    properties: dict
    provisioning_state: str
    parent_id: str | None = None


@dataclass
class Operation:
    id: str
    subscription_id: str
    location: str
    resource_id: str
    resource_type: str
    action: str  # CREATE | UPDATE | DELETE
    status: str  # 진행 중: Creating | Updating | Deleting, 종결: TERMINAL_STATES
    start_time: str
    end_time: str | None = None
    previous: dict | None = None  # UPDATE가 실패하면 되돌릴 tags·properties
    error: dict | None = None  # {httpStatus, code, message}
    correlation_id: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES


def _load(text: str | None):
    return None if text is None else json.loads(text)


def _resource(row: sqlite3.Row) -> Resource:
    return Resource(
        id=row["id"], type=row["type"], subscription_id=row["subscription_id"],
        resource_group=row["resource_group"], name=row["name"], location=row["location"],
        tags=json.loads(row["tags"]), properties=json.loads(row["properties"]),
        provisioning_state=row["provisioning_state"], parent_id=row["parent_id"],
    )


def _operation(row: sqlite3.Row) -> Operation:
    return Operation(
        id=row["id"], subscription_id=row["subscription_id"], location=row["location"],
        resource_id=row["resource_id"], resource_type=row["resource_type"],
        action=row["action"], status=row["status"], start_time=row["start_time"],
        end_time=row["end_time"], previous=_load(row["previous"]), error=_load(row["error"]),
        correlation_id=row["correlation_id"],
    )


class Tx:
    """연결 하나 위의 읽기·쓰기. `StateStore.transaction()` 안에서 쓴다."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def get_resource(self, resource_id: str) -> Resource | None:
        row = self._conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        return None if row is None else _resource(row)

    def list_resources(self, type: str, subscription_id: str,
                       resource_group: str | None = None) -> list[Resource]:
        sql = "SELECT * FROM resources WHERE type = ? AND subscription_id = ?"
        args: list = [type, subscription_id]
        if resource_group is not None:
            sql += " AND resource_group = ?"
            args.append(resource_group)
        rows = self._conn.execute(sql + " ORDER BY name COLLATE NOCASE", args).fetchall()
        return [_resource(r) for r in rows]

    def all_of_type(self, type: str) -> list[Resource]:
        """모든 구독에서 한 종류의 리소스. 클론 전체에서 유일해야 하는 값을 검사할 때 쓴다."""
        rows = self._conn.execute(
            "SELECT * FROM resources WHERE type = ? ORDER BY id COLLATE NOCASE", (type,)
        ).fetchall()
        return [_resource(r) for r in rows]

    def child_ids(self, parent_id: str, limit: int = 5) -> list[str]:
        rows = self._conn.execute(
            "SELECT id FROM resources WHERE parent_id = ? ORDER BY id LIMIT ?", (parent_id, limit)
        ).fetchall()
        return [r["id"] for r in rows]

    def list_children(self, parent_id: str, type: str) -> list[Resource]:
        rows = self._conn.execute(
            "SELECT * FROM resources WHERE parent_id = ? AND type = ? ORDER BY name COLLATE NOCASE",
            (parent_id, type),
        ).fetchall()
        return [_resource(r) for r in rows]

    def ensure_no_children(self, resource_id: str) -> None:
        """자식이 남은 리소스의 DELETE를 409로 거절한다 (계정 녹화 R4, 풀 녹화 N5).
        실서비스에서는 ARM 게이트웨이가 하는 검사다. 클론은 DELETE 트랜잭션 안에서 해서,
        검사와 삭제 사이에 자식이 생기는 경합을 막는다 (ADR §6.4). 자식의 상태와는 무관하다."""
        children = self.child_ids(resource_id)
        if children:
            nested = ", ".join(f"'{c.split('/providers/', 1)[1]}'" for c in children)
            raise ArmError(
                409, "CannotDeleteResource",
                "Cannot delete resource while nested resources exist. Some existing nested "
                f"resource IDs include: {nested}. Please delete all nested resources before "
                "deleting this resource.",
            )

    def put_resource(self, res: Resource) -> None:
        now = utc_now()
        self._conn.execute(
            """INSERT INTO resources (id, type, parent_id, subscription_id, resource_group, name,
                   location, tags, properties, provisioning_state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   location = excluded.location, tags = excluded.tags,
                   properties = excluded.properties,
                   provisioning_state = excluded.provisioning_state,
                   updated_at = excluded.updated_at""",
            (res.id, res.type, res.parent_id, res.subscription_id, res.resource_group, res.name,
             res.location, json.dumps(res.tags), json.dumps(res.properties),
             res.provisioning_state, now, now),
        )

    def delete_resource(self, resource_id: str) -> None:
        self._conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))

    def get_operation(self, operation_id: str) -> Operation | None:
        row = self._conn.execute(
            "SELECT * FROM operations WHERE id = ?", (operation_id,)
        ).fetchone()
        return None if row is None else _operation(row)

    def active_operations(self) -> list[Operation]:
        rows = self._conn.execute(
            "SELECT * FROM operations WHERE status NOT IN (?, ?, ?) ORDER BY start_time",
            TERMINAL_STATES,
        ).fetchall()
        return [_operation(r) for r in rows]

    def active_operation(self, resource_id: str) -> Operation | None:
        row = self._conn.execute(
            "SELECT * FROM operations WHERE resource_id = ? AND status NOT IN (?, ?, ?)",
            (resource_id, *TERMINAL_STATES),
        ).fetchone()
        return None if row is None else _operation(row)

    def ensure_no_active_operation(self, resource_id: str) -> None:
        """리소스 하나에 진행 중 작업 하나 (설계 결정 6). 있으면 대기열에 넣지 않고 즉시 409로 거절한다."""
        if self.active_operation(resource_id) is not None:
            raise ArmError(
                409, "AnotherOperationInProgress",
                f"Another operation is in progress on resource '{resource_id}'. "
                "Wait until it is finished, and then retry.",
            )

    def create_operation(self, res: Resource, action: str, status: str, *,
                         previous: dict | None = None,
                         correlation_id: str | None = None) -> Operation:
        """진행 중 작업을 만든다. 이미 진행 중인 작업이 있으면 409로 거절한다."""
        self.ensure_no_active_operation(res.id)
        op = Operation(
            id=str(uuid.uuid4()), subscription_id=res.subscription_id, location=res.location,
            resource_id=res.id, resource_type=res.type, action=action, status=status,
            start_time=utc_now(), previous=previous, correlation_id=correlation_id,
        )
        self._conn.execute(
            """INSERT INTO operations (id, subscription_id, location, resource_id, resource_type,
                   action, status, previous, error, correlation_id, start_time, end_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)""",
            (op.id, op.subscription_id, op.location, op.resource_id, op.resource_type,
             op.action, op.status, None if previous is None else json.dumps(previous),
             op.correlation_id, op.start_time),
        )
        return op

    def finish_operation(self, operation_id: str, status: str, error: dict | None = None) -> None:
        assert status in TERMINAL_STATES, status
        self._conn.execute(
            "UPDATE operations SET status = ?, error = ?, end_time = ? WHERE id = ?",
            (status, None if error is None else json.dumps(error), utc_now(), operation_id),
        )


class StateStore:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None: 트랜잭션은 transaction()이 BEGIN IMMEDIATE로 직접 연다.
        conn = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        """쓰기 트랜잭션. 시작할 때 쓰기 잠금을 잡아(BEGIN IMMEDIATE) 확인과 쓰기 사이에 끼어들 틈을 없앤다."""
        with closing(self._connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield Tx(conn)
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def _read(self):
        return closing(self._connect())

    def get_resource(self, resource_id: str) -> Resource | None:
        with self._read() as conn:
            return Tx(conn).get_resource(resource_id)

    def list_resources(self, type: str, subscription_id: str,
                       resource_group: str | None = None) -> list[Resource]:
        with self._read() as conn:
            return Tx(conn).list_resources(type, subscription_id, resource_group)

    def list_children(self, parent_id: str, type: str) -> list[Resource]:
        with self._read() as conn:
            return Tx(conn).list_children(parent_id, type)

    def get_operation(self, operation_id: str) -> Operation | None:
        with self._read() as conn:
            return Tx(conn).get_operation(operation_id)

    def active_operations(self) -> list[Operation]:
        with self._read() as conn:
            return Tx(conn).active_operations()
