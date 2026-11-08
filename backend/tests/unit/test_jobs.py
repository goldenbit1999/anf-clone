"""storage agent의 job 표: ONTAP job 모델(queued·running·success·failure)과 멱등 키 (볼륨 설계 결정 9, §6.2)."""

import threading
import time

import pytest

from storage_agent.jobs import JobTable

UUID_LEN = 36


def wait_terminal(table, job_uuid, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        job = table.get(job_uuid)
        if job["state"] in ("success", "failure"):
            return job
        assert time.monotonic() < deadline, f"job did not finish: {job}"
        time.sleep(0.01)


@pytest.fixture
def table():
    t = JobTable()
    yield t
    t.close()


def test_successful_job(table):
    ran = []
    job = table.submit("vol-a", lambda: ran.append(1), "create volume a")
    assert len(job["uuid"]) == UUID_LEN
    assert job["state"] in ("queued", "running", "success")
    done = wait_terminal(table, job["uuid"])
    assert ran == [1]
    assert done["state"] == "success"
    assert done["code"] == 0
    assert done["description"] == "create volume a"
    assert done["start_time"] and done["end_time"]


def test_failed_job_keeps_message(table):
    def boom():
        raise RuntimeError("lvcreate failed: no space")

    done = wait_terminal(table, table.submit("vol-a", boom, "create")["uuid"])
    assert done["state"] == "failure"
    assert done["code"] != 0
    assert done["message"] == "lvcreate failed: no space"


def test_same_key_while_unfinished_returns_same_job(table):
    gate = threading.Event()
    first = table.submit("vol-a", gate.wait, "create")
    second = table.submit("vol-a", lambda: None, "create")
    assert second["uuid"] == first["uuid"]
    gate.set()
    assert wait_terminal(table, first["uuid"])["state"] == "success"


def test_same_key_after_finish_starts_new_job(table):
    first = wait_terminal(table, table.submit("vol-a", lambda: None, "create")["uuid"])
    second = table.submit("vol-a", lambda: None, "create")
    assert second["uuid"] != first["uuid"]


def test_jobs_run_one_at_a_time(table):
    # LVM과 export 파일을 같은 순간에 두 job이 바꾸지 않게 한다
    active, peak = [0], [0]
    lock = threading.Lock()

    def work():
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1

    jobs = [table.submit(f"vol-{i}", work, "create") for i in range(3)]
    for job in jobs:
        wait_terminal(table, job["uuid"])
    assert peak[0] == 1


def test_unknown_job_is_none(table):
    assert table.get("00000000-0000-0000-0000-000000000000") is None


def test_finished_jobs_expire_after_retention():
    # ONTAP은 끝난 job을 300초 뒤 지운다 [볼륨 브리프 문서 15]
    now = [1000.0]
    t = JobTable(retention_seconds=300, clock=lambda: now[0])
    try:
        job = wait_terminal(t, t.submit("vol-a", lambda: None, "create")["uuid"])
        now[0] += 299
        assert t.get(job["uuid"]) is not None
        now[0] += 2
        assert t.get(job["uuid"]) is None
    finally:
        t.close()
