"""공통 LRO 계층: 작업 워커, 결함 주입, 작업 상태 본문 (계정 설계 §4.2, §6.2, §6.3, 풀 설계 §3·§7의 PATCH)."""

import asyncio
import time

import pytest

from anf_api.lro import Fault, LroWorker, operation_status_body, parse_faults
from anf_api.state_store import Resource, StateStore

TYPE = "Microsoft.NetApp/netAppAccounts"
POOL_TYPE = "Microsoft.NetApp/netAppAccounts/capacityPools"
ACC = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
# 등록된 처리기의 (리소스 종류, 작업). 결함 주입 키는 이 목록에서 만든다.
ACCOUNT_KEYS = [(TYPE, a) for a in ("CREATE", "UPDATE", "DELETE")]
POOL_KEYS = [(POOL_TYPE, a) for a in ("CREATE", "UPDATE", "PATCH", "DELETE")]


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "anf.db")


def account(state="Creating", tags=None):
    return Resource(
        id=ACC, type=TYPE, subscription_id="s1", resource_group="rg1", name="acc1",
        location="westus2", tags=tags if tags is not None else {"a": "1"}, properties={},
        provisioning_state=state,
    )


def start(store, action, status, *, state=None, previous=None, tags=None):
    """리소스와 진행 중 작업을 저장한다 (API가 응답하기 전에 하는 일)."""
    with store.transaction() as tx:
        res = account(state or status, tags)
        tx.put_resource(res)
        return tx.create_operation(res, action, status, previous=previous)


class Recorder:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def __call__(self, op):
        self.calls.append(op.id)
        if self.error:
            raise self.error


def handlers(rec):
    return {(TYPE, a): rec for a in ("CREATE", "UPDATE", "DELETE")}


def drain(worker):
    async def go():
        await asyncio.gather(*worker.start_pending())
    asyncio.run(go())


# --- 결함 주입 설정 ---

@pytest.mark.parametrize("text", [None, ""])
def test_no_fault_injection_by_default(text):
    assert parse_faults(text, ACCOUNT_KEYS) == {}


def test_parse_faults_reads_delay_and_fail():
    faults = parse_faults(
        '{"netAppAccounts/create": {"delaySeconds": 2.5}, "netAppAccounts/delete": {"fail": true}}',
        ACCOUNT_KEYS,
    )
    assert faults == {
        "netAppAccounts/create": Fault(delay_seconds=2.5),
        "netAppAccounts/delete": Fault(fail=True),
    }


@pytest.mark.parametrize("text", [
    "not json",
    "[]",
    '{"capacityPools/create": {"fail": true}}',
    '{"netAppAccounts/patch": {"fail": true}}',
    '{"netAppAccounts": {"fail": true}}',
    '{"netAppAccounts/create": {"delay": 1}}',
    '{"netAppAccounts/create": {"delaySeconds": -1}}',
    '{"netAppAccounts/create": {"fail": "yes"}}',
])
def test_invalid_fault_injection_is_rejected(text):
    """계정에는 PATCH 작업이 없어서(계정 PATCH는 동기) `netAppAccounts/patch`는 받지 않는다."""
    with pytest.raises(ValueError):
        parse_faults(text, ACCOUNT_KEYS)


def test_patch_fault_key_is_accepted_for_resource_with_patch_operation():
    faults = parse_faults('{"capacityPools/patch": {"delaySeconds": 3}}', ACCOUNT_KEYS + POOL_KEYS)
    assert faults == {"capacityPools/patch": Fault(delay_seconds=3.0)}


# --- 워커 ---

def test_create_succeeds_and_resource_becomes_succeeded(store):
    op = start(store, "CREATE", "Creating")
    rec = Recorder()
    drain(LroWorker(store, handlers(rec)))
    assert rec.calls == [op.id]
    done = store.get_operation(op.id)
    assert done.status == "Succeeded"
    assert done.end_time is not None
    assert store.get_resource(ACC).provisioning_state == "Succeeded"


def test_delete_success_removes_resource(store):
    op = start(store, "DELETE", "Deleting")
    drain(LroWorker(store, handlers(Recorder())))
    assert store.get_operation(op.id).status == "Succeeded"
    assert store.get_resource(ACC) is None


def test_injected_failure_marks_operation_and_resource_failed(store):
    op = start(store, "CREATE", "Creating")
    rec = Recorder()
    faults = {"netAppAccounts/create": Fault(fail=True)}
    drain(LroWorker(store, handlers(rec), faults))
    assert rec.calls == []
    done = store.get_operation(op.id)
    assert done.status == "Failed"
    assert done.error["httpStatus"] == 500
    assert done.error["code"] == "InternalServerError"
    assert "Injected fault" in done.error["message"]
    assert store.get_resource(ACC).provisioning_state == "Failed"


def test_failed_update_restores_previous_values(store):
    op = start(store, "UPDATE", "Updating", tags={"new": "1"},
               previous={"tags": {"old": "1"}, "properties": {}})
    drain(LroWorker(store, handlers(Recorder()), {"netAppAccounts/update": Fault(fail=True)}))
    res = store.get_resource(ACC)
    assert res.provisioning_state == "Failed"
    assert res.tags == {"old": "1"}
    assert store.get_operation(op.id).status == "Failed"


def test_patch_succeeds_and_resource_becomes_succeeded(store):
    op = start(store, "PATCH", "Patching")
    rec = Recorder()
    drain(LroWorker(store, {(TYPE, "PATCH"): rec}))
    assert rec.calls == [op.id]
    assert store.get_operation(op.id).status == "Succeeded"
    assert store.get_resource(ACC).provisioning_state == "Succeeded"


def test_failed_patch_restores_previous_values(store):
    """PATCH는 PUT 갱신처럼 새 값을 바로 쓰고, 실패하면 되돌린다 (풀 설계 결정 9)."""
    op = start(store, "PATCH", "Patching", tags={"new": "1"},
               previous={"tags": {"old": "1"}, "properties": {"size": 1}})
    drain(LroWorker(store, {(TYPE, "PATCH"): Recorder()}, {"netAppAccounts/patch": Fault(fail=True)}))
    res = store.get_resource(ACC)
    assert res.provisioning_state == "Failed"
    assert res.tags == {"old": "1"}
    assert res.properties == {"size": 1}
    assert store.get_operation(op.id).status == "Failed"


def test_failed_delete_keeps_resource_as_failed(store):
    start(store, "DELETE", "Deleting")
    drain(LroWorker(store, handlers(Recorder()), {"netAppAccounts/delete": Fault(fail=True)}))
    assert store.get_resource(ACC).provisioning_state == "Failed"


def test_handler_exception_fails_operation_with_internal_error(store):
    op = start(store, "CREATE", "Creating")
    drain(LroWorker(store, handlers(Recorder(error=RuntimeError("boom")))))
    done = store.get_operation(op.id)
    assert done.status == "Failed"
    assert (done.error["httpStatus"], done.error["code"]) == (500, "InternalServerError")
    assert store.get_resource(ACC).provisioning_state == "Failed"


def test_injected_delay_keeps_operation_in_progress_until_it_ends(store):
    op = start(store, "CREATE", "Creating")
    worker = LroWorker(store, handlers(Recorder()), {"netAppAccounts/create": Fault(delay_seconds=0.3)})

    async def go():
        began = time.monotonic()
        tasks = worker.start_pending()
        await asyncio.sleep(0.1)
        mid = store.get_operation(op.id).status
        await asyncio.gather(*tasks)
        return mid, time.monotonic() - began

    mid, elapsed = asyncio.run(go())
    assert mid == "Creating"
    assert elapsed >= 0.3
    assert store.get_operation(op.id).status == "Succeeded"


def test_running_operation_is_not_scheduled_twice(store):
    start(store, "CREATE", "Creating")
    worker = LroWorker(store, handlers(Recorder()), {"netAppAccounts/create": Fault(delay_seconds=0.1)})

    async def go():
        first = worker.start_pending()
        second = worker.start_pending()
        await asyncio.gather(*first)
        return len(first), len(second)

    assert asyncio.run(go()) == (1, 0)


def test_run_loop_picks_up_new_operation_when_notified(store):
    worker = LroWorker(store, handlers(Recorder()), scan_interval=30)

    async def go():
        loop_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        op = start(store, "CREATE", "Creating")
        worker.notify()
        for _ in range(50):
            if store.get_operation(op.id).is_terminal:
                break
            await asyncio.sleep(0.01)
        loop_task.cancel()
        return store.get_operation(op.id).status

    assert asyncio.run(go()) == "Succeeded"


def test_new_worker_resumes_operations_left_in_progress(store):
    """재시작 복구 (AR-04): 이전 프로세스가 끝내지 못한 작업을 새 워커가 처리한다."""
    op = start(store, "CREATE", "Creating")
    drain(LroWorker(store, handlers(Recorder())))
    assert store.get_operation(op.id).status == "Succeeded"


# --- 작업 상태 본문 ---

def test_status_body_while_in_progress(store):
    op = start(store, "CREATE", "Creating")
    body = operation_status_body(store.get_operation(op.id))
    assert body == {
        "id": f"/subscriptions/s1/providers/Microsoft.NetApp/locations/westus2/operationResults/{op.id}",
        "name": op.id,
        "status": "Creating",
        "startTime": op.start_time,
        "percentComplete": 0.0,
        "properties": {"resourceName": ACC, "action": "CREATE"},
    }


def test_status_body_when_failed_has_error_without_http_status(store):
    op = start(store, "CREATE", "Creating")
    drain(LroWorker(store, handlers(Recorder()), {"netAppAccounts/create": Fault(fail=True)}))
    body = operation_status_body(store.get_operation(op.id))
    assert body["status"] == "Failed"
    assert body["percentComplete"] == 100.0
    assert "endTime" in body
    assert set(body["error"]) == {"code", "message"}
    assert body["error"]["code"] == "InternalServerError"
