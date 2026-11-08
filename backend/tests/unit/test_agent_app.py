"""storage agent HTTP 앱: ONTAP REST 부분집합의 경로, 입력 검사, job, 시작 검사 (볼륨 설계 §6.1·§6.2, AC-13).

볼륨 관리자는 가짜다. 실제 볼륨 동작은 test_flexvol.py(명령 순서)와 통합 테스트가 확인한다.
"""

import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from storage_agent.agent_app import create_app
from storage_agent.flexvol import VolumeError
from storage_agent.jobs import JobTable
from storage_agent.nfs_instance import StartupError

GIB = 1 << 30
U1 = "11111111-2222-3333-4444-555555555555"
NAME1 = "vol_11111111222233334444555555555555"
RECORD1 = {"uuid": U1, "name": NAME1, "size": GIB, "nas": {"path": "/vol1", "protocols": ["nfs3"]},
           "state": "online", "data_lif": {"ip": {"address": "172.30.0.129"}}}


class FakeInstances:
    def __init__(self, calls):
        self.calls = calls
        self.broken = None  # StartupError 메시지

    def check_host(self):
        self.calls.append("check_host")
        if self.broken:
            raise StartupError(self.broken)


class FakeManager:
    def __init__(self):
        self.calls: list = []
        self.instances = FakeInstances(self.calls)
        self.volumes = {U1: RECORD1}
        self.error = None  # create·delete가 던질 예외
        self.gate = threading.Event()  # 지우면 create가 기다린다
        self.gate.set()

    def recover(self):
        self.calls.append("recover")

    def create(self, *args):
        self.gate.wait(5)
        self.calls.append(("create", *args))
        if self.error:
            raise self.error

    def delete(self, uuid):
        self.calls.append(("delete", uuid))
        if self.error:
            raise self.error

    def records(self, name=None):
        return [r for r in self.volumes.values() if name is None or r["name"] == name]

    def record(self, uuid):
        return self.volumes.get(uuid)


@pytest.fixture
def manager():
    return FakeManager()


@pytest.fixture
def client(manager):
    jobs = JobTable()
    with TestClient(create_app(manager=manager, jobs=jobs)) as c:
        yield c


def body(**changes):
    b = {"uuid": U1, "name": NAME1, "size": GIB,
         "nas": {"path": "/vol1", "unix_permissions": 770, "protocols": ["nfs3"]}}
    nas = {k: changes.pop(k) for k in list(changes) if k in ("path", "unix_permissions", "protocols")}
    b["nas"].update(nas)
    b.update(changes)
    return b


def wait_job(client, href):
    for _ in range(200):
        job = client.get(href).json()
        if job["state"] in ("success", "failure"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"job did not finish: {job}")


# --- 시작 ---


def test_startup_checks_the_host_then_recovers(manager, client):
    assert manager.calls == ["check_host", "recover"]


def test_startup_fails_when_the_host_is_not_ready(manager):
    manager.instances.broken = "Image 'anf-nfs-server' is missing. Run scripts/setup-wsl-dataplane.sh as root first."
    with pytest.raises(StartupError):
        with TestClient(create_app(manager=manager, jobs=JobTable())):
            pass
    assert "recover" not in manager.calls


# --- 생성 ---


def test_post_volume_returns_a_job_that_succeeds(manager, client):
    r = client.post("/api/storage/volumes", json=body(protocols=["nfs4.1"], unix_permissions=1777))
    assert r.status_code == 202
    href = r.json()["job"]["_links"]["self"]["href"]
    assert href == f"/api/cluster/jobs/{r.json()['job']['uuid']}"
    job = wait_job(client, href)
    assert (job["state"], job["code"], job["message"]) == ("success", 0, "")
    assert ("create", U1, "/vol1", GIB, 1777, "nfs4.1") in manager.calls


def test_failed_create_is_a_failed_job(manager, client):
    manager.error = VolumeError("junction path /vol1 is already used by volume x")
    r = client.post("/api/storage/volumes", json=body())
    job = wait_job(client, r.json()["job"]["_links"]["self"]["href"])
    assert job["state"] == "failure"
    assert job["code"] != 0
    assert "already used" in job["message"]


def test_repeated_post_while_running_returns_the_same_job(manager, client):
    manager.gate.clear()
    first = client.post("/api/storage/volumes", json=body()).json()["job"]["uuid"]
    second = client.post("/api/storage/volumes", json=body()).json()["job"]["uuid"]
    # 같은 UUID라도 다른 작업(삭제)은 생성 job을 돌려받지 않는다
    deleting = client.delete(f"/api/storage/volumes/{U1}").json()["job"]["uuid"]
    manager.gate.set()
    assert first == second != deleting
    wait_job(client, f"/api/cluster/jobs/{deleting}")
    assert [c[0] for c in manager.calls if isinstance(c, tuple)] == ["create", "delete"]


@pytest.mark.parametrize("bad", [
    {"uuid": "not-a-uuid"},
    {"uuid": U1.upper(), "name": NAME1.upper()},
    {"name": "vol_other"},
    {"size": GIB + 1},
    {"size": 0},
    {"size": (100 << 40) + GIB},
    {"size": True},
    {"size": "1073741824"},
    {"path": "../x"},
    {"path": "/a/b"},
    {"path": "/1vol"},
    {"path": "vol1"},
    {"path": "/" + "a" * 81},
    {"path": "/vol;rm"},
    {"unix_permissions": 778},
    {"unix_permissions": 17777},
    {"unix_permissions": -1},
    {"unix_permissions": "0770"},
    {"protocols": ["nfs4"]},
    {"protocols": ["nfs3", "nfs4.1"]},
    {"protocols": []},
    {"protocols": "nfs3"},
    {"extra": 1},
    {"nas": {"path": "/vol1", "unix_permissions": 770, "protocols": ["nfs3"], "security_style": "unix"}},
    {"nas": None},
])
def test_invalid_post_is_rejected_without_a_job(manager, client, bad):
    r = client.post("/api/storage/volumes", json=body(**bad))
    assert r.status_code == 400
    assert r.json()["error"]["message"]
    assert not any(isinstance(c, tuple) for c in manager.calls)


@pytest.mark.parametrize("raw", [b"{", b"[]", b"null"])
def test_post_body_must_be_a_json_object(manager, client, raw):
    r = client.post("/api/storage/volumes", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_missing_field_is_rejected(manager, client):
    b = body()
    del b["nas"]["protocols"]
    assert client.post("/api/storage/volumes", json=b).status_code == 400


# --- 삭제 ---


def test_delete_volume_returns_a_job(manager, client):
    r = client.delete(f"/api/storage/volumes/{U1}")
    assert r.status_code == 202
    job = wait_job(client, r.json()["job"]["_links"]["self"]["href"])
    assert job["state"] == "success"
    assert ("delete", U1) in manager.calls


def test_delete_with_a_bad_uuid_is_rejected(manager, client):
    assert client.delete("/api/storage/volumes/x").status_code == 400
    assert not any(isinstance(c, tuple) for c in manager.calls)


# --- 조회 ---


def test_list_volumes(client):
    assert client.get("/api/storage/volumes").json() == {"records": [RECORD1], "num_records": 1}
    assert client.get("/api/storage/volumes", params={"name": NAME1}).json()["num_records"] == 1
    assert client.get("/api/storage/volumes", params={"name": "vol_x"}).json() == {"records": [], "num_records": 0}


def test_get_volume(client):
    assert client.get(f"/api/storage/volumes/{U1}").json() == RECORD1
    r = client.get("/api/storage/volumes/99999999-2222-3333-4444-555555555555")
    assert r.status_code == 404
    assert r.json()["error"]["message"]


def test_unknown_job_is_404(client):
    assert client.get("/api/cluster/jobs/99999999-2222-3333-4444-555555555555").status_code == 404


# --- 상관 ID ---


def test_correlation_id_is_logged_with_the_job(client, caplog):
    caplog.set_level(logging.INFO, logger="storage_agent.agent_app")
    r = client.post("/api/storage/volumes", json=body(), headers={"x-ms-correlation-request-id": "corr-123"})
    job = r.json()["job"]["uuid"]
    assert any("corr-123" in m and job in m for m in caplog.messages)
