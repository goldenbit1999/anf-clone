"""공통 LRO 계층: 작업 워커, 결함 주입, 작업 상태 본문 (FR-01, 계정 설계 §4.2, §6.2, §6.3).

흐름: API가 리소스(진행 중 상태)와 작업을 한 트랜잭션으로 저장하고 바로 응답한다.
워커는 같은 프로세스의 asyncio 태스크로 돌며(ADR D-09), 종결되지 않은 작업을 찾아
처리기를 실행하고, 결과를 리소스와 작업에 한 트랜잭션으로 반영한다.
재시작하면 종결되지 않은 작업을 처음부터 다시 실행한다. 그래서 처리기는 멱등이어야 한다 (AR-04, AR-05).
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

from anf_api.arm_rules import operation_path
from anf_api.state_store import Operation, StateStore

log = logging.getLogger(__name__)

Handler = Callable[[Operation], Awaitable[None]]

_FAULT_ACTIONS = ("create", "update", "delete")


@dataclass(frozen=True)
class Fault:
    delay_seconds: float = 0.0
    fail: bool = False


def parse_faults(text: str | None, resource_types: Iterable[str]) -> dict[str, Fault]:
    """`ANF_FAULT_INJECTION` 값을 읽는다. 잘못된 값은 ValueError로 거절해 서버가 뜨지 않게 한다.

    형식: {"netAppAccounts/create": {"delaySeconds": 5}, "netAppAccounts/delete": {"fail": true}}
    """
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"ANF_FAULT_INJECTION is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise ValueError("ANF_FAULT_INJECTION must be a JSON object")
    short_types = {t.rsplit("/", 1)[-1] for t in resource_types}
    faults = {}
    for key, spec in raw.items():
        type_name, _, action = key.partition("/")
        if type_name not in short_types or action not in _FAULT_ACTIONS:
            raise ValueError(
                f"Unknown fault key '{key}'. Use '{{type}}/{{{'|'.join(_FAULT_ACTIONS)}}}' "
                f"with type in {sorted(short_types)}"
            )
        if not isinstance(spec, dict) or set(spec) - {"delaySeconds", "fail"}:
            raise ValueError(f"Fault '{key}' may only have 'delaySeconds' and 'fail'")
        delay = spec.get("delaySeconds", 0)
        fail = spec.get("fail", False)
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
            raise ValueError(f"Fault '{key}': delaySeconds must be a number >= 0")
        if not isinstance(fail, bool):
            raise ValueError(f"Fault '{key}': fail must be true or false")
        faults[key] = Fault(delay_seconds=float(delay), fail=fail)
    return faults


def _fault_key(op: Operation) -> str:
    return f"{op.resource_type.rsplit('/', 1)[-1]}/{op.action.lower()}"


class LroWorker:
    def __init__(self, store: StateStore, handlers: dict[tuple[str, str], Handler],
                 faults: dict[str, Fault] | None = None, scan_interval: float = 1.0):
        self._store = store
        self._handlers = handlers
        self._faults = faults or {}
        self._scan_interval = scan_interval
        self._wake = asyncio.Event()
        self._running: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    def notify(self) -> None:
        """새 작업이 생겼다고 알린다. API 라우트와 워커는 같은 이벤트 루프에서 돈다."""
        self._wake.set()

    def start_pending(self) -> list[asyncio.Task]:
        """종결되지 않은 작업 중 아직 실행 중이 아닌 것을 태스크로 띄운다."""
        started = []
        for op in self._store.active_operations():
            if op.id in self._running:
                continue
            self._running.add(op.id)
            task = asyncio.create_task(self._process(op))
            self._tasks.add(task)
            task.add_done_callback(lambda t, op_id=op.id: self._done(t, op_id))
            started.append(task)
        return started

    def _done(self, task: asyncio.Task, op_id: str) -> None:
        self._tasks.discard(task)
        self._running.discard(op_id)

    async def run(self) -> None:
        """새 작업 알림이나 scan_interval마다 깨어나 작업을 띄운다. 취소되면 실행 중인 작업도 멈춘다.
        멈춘 작업은 종결되지 않은 채 남고, 다음 시작 때 다시 실행된다."""
        try:
            while True:
                self._wake.clear()
                self.start_pending()
                try:
                    await asyncio.wait_for(self._wake.wait(), self._scan_interval)
                except TimeoutError:
                    pass
        finally:
            for task in list(self._tasks):
                task.cancel()

    async def _process(self, op: Operation) -> None:
        fault = self._faults.get(_fault_key(op), Fault())
        if fault.delay_seconds:
            await asyncio.sleep(fault.delay_seconds)
        if fault.fail:
            self._finish(op, {
                "httpStatus": 500, "code": "InternalServerError",
                "message": f"Injected fault: {_fault_key(op)} (ANF_FAULT_INJECTION).",
            })
            return
        try:
            await self._handlers[(op.resource_type, op.action)](op)
        except Exception:
            log.exception("operation %s (%s %s) failed", op.id, op.action, op.resource_id)
            self._finish(op, {
                "httpStatus": 500, "code": "InternalServerError",
                "message": "Something unexpected occurred when performing this action. "
                           f"Please try again, and provide the operation id '{op.id}'.",
            })
            return
        self._finish(op, None)

    def _finish(self, op: Operation, error: dict | None) -> None:
        """작업 결과를 리소스와 작업에 한 트랜잭션으로 반영한다 (설계 §5 상태 전이)."""
        with self._store.transaction() as tx:
            res = tx.get_resource(op.resource_id)
            if error is None and op.action == "DELETE":
                tx.delete_resource(op.resource_id)
            elif res is not None:
                if error is not None and op.action == "UPDATE" and op.previous is not None:
                    res.tags = op.previous["tags"]
                    res.properties = op.previous["properties"]
                res.provisioning_state = "Succeeded" if error is None else "Failed"
                tx.put_resource(res)
            tx.finish_operation(op.id, "Succeeded" if error is None else "Failed", error)


def operation_status_body(op: Operation) -> dict:
    """`Azure-AsyncOperation` URL의 응답 본문. ANF 녹화처럼 진행 중에도 properties를 넣는다."""
    body = {
        "id": operation_path(op.subscription_id, op.location, op.id),
        "name": op.id,
        "status": op.status,
        "startTime": op.start_time,
        "percentComplete": 100.0 if op.is_terminal else 0.0,
        "properties": {"resourceName": op.resource_id, "action": op.action},
    }
    if op.end_time is not None:
        body["endTime"] = op.end_time
    if op.status == "Failed" and op.error is not None:
        body["error"] = {"code": op.error["code"], "message": op.error["message"]}
    return body
