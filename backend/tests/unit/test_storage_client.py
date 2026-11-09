"""anf-api의 storage agent 호출: 요청 모양, job 폴링, 연결 재시도, agent 재시작 뒤 재요청 (볼륨 설계 결정 9·11, §6.2)."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from anf_api.storage_client import StorageClient, StorageError, urllib_transport

BASE = "http://agent.test"
U1 = "11111111-2222-3333-4444-555555555555"
GIB = 1 << 30


def job(uuid):
    return 202, {"job": {"uuid": uuid, "_links": {"self": {"href": f"/api/cluster/jobs/{uuid}"}}}}


def state(value, message=""):
    return 200, {"uuid": "j", "state": value, "message": message, "code": 0 if value != "failure" else 1}


VOLUME = 200, {"uuid": U1, "data_lif": {"ip": {"address": "172.30.0.129"}}}


class FakeAgent:
    """(메서드, 경로)마다 정한 응답을 차례로 준다. 마지막 응답은 계속 준다. down이 남아 있으면 연결이 거절된다."""

    def __init__(self):
        self.requests: list[tuple] = []
        self.replies: dict[tuple[str, str], list] = {}
        self.down = 0

    def reply(self, method, path, *responses):
        self.replies[(method, path)] = list(responses)

    def __call__(self, method, url, body, headers):
        self.requests.append((method, url.removeprefix(BASE), body, headers))
        if self.down:
            self.down -= 1
            raise ConnectionRefusedError(111, "Connection refused")
        queue = self.replies[(method, url.removeprefix(BASE))]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def paths(self):
        return [(m, p) for m, p, _, _ in self.requests]


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def agent():
    return FakeAgent()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def client(agent, clock):
    return StorageClient(BASE, transport=agent, sleep=clock.sleep, clock=clock)


def ensure(client, protocol="nfs3"):
    return asyncio.run(client.ensure_volume(U1, "/vol1", GIB, 770, protocol, correlation_id="corr-1"))


# --- 볼륨 보장 ---


def test_ensure_volume_posts_polls_and_returns_the_ip(agent, client, clock):
    agent.reply("POST", "/api/storage/volumes", job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("queued"), state("running"), state("success"))
    agent.reply("GET", f"/api/storage/volumes/{U1}", VOLUME)

    assert ensure(client, "nfs4.1") == "172.30.0.129"

    method, path, body, headers = agent.requests[0]
    assert (method, path) == ("POST", "/api/storage/volumes")
    assert body == {"uuid": U1, "name": "vol_11111111222233334444555555555555", "size": GIB,
                    "nas": {"path": "/vol1", "unix_permissions": 770, "protocols": ["nfs4.1"]}}
    # 상관 ID를 모든 요청에 넘긴다 (NFR-08)
    assert all(h == {"x-ms-correlation-request-id": "corr-1"} for _, _, _, h in agent.requests)
    assert agent.paths()[1:] == [("GET", "/api/cluster/jobs/j1")] * 3 + [("GET", f"/api/storage/volumes/{U1}")]
    assert clock.sleeps == [1.0, 1.0]


def test_failed_job_raises_with_the_agent_message(agent, client):
    agent.reply("POST", "/api/storage/volumes", job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("failure", "junction path /vol1 is already used"))
    with pytest.raises(StorageError, match="already used"):
        ensure(client)


def test_rejected_request_raises(agent, client):
    agent.reply("POST", "/api/storage/volumes", (400, {"error": {"message": "size must be a multiple of 1 GiB"}}))
    with pytest.raises(StorageError, match="multiple of 1 GiB"):
        ensure(client)


def test_lost_job_is_requested_again(agent, client):
    # agent가 재시작하면 메모리 job 표가 비어 404다. 같은 요청을 다시 보낸다 (결정 9)
    agent.reply("POST", "/api/storage/volumes", job("j1"), job("j2"))
    agent.reply("GET", "/api/cluster/jobs/j1", (404, {"error": {"message": "job j1 not found"}}))
    agent.reply("GET", "/api/cluster/jobs/j2", state("success"))
    agent.reply("GET", f"/api/storage/volumes/{U1}", VOLUME)

    assert ensure(client) == "172.30.0.129"
    assert [p for p in agent.paths() if p[0] == "POST"] == [("POST", "/api/storage/volumes")] * 2


def test_unreachable_agent_is_retried(agent, client, clock):
    agent.down = 5
    agent.reply("POST", "/api/storage/volumes", job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("success"))
    agent.reply("GET", f"/api/storage/volumes/{U1}", VOLUME)

    assert ensure(client) == "172.30.0.129"
    assert clock.sleeps == [1.0] * 5


def test_agent_down_for_60_seconds_fails(agent, client, clock):
    agent.down = 10**6
    with pytest.raises(StorageError, match="unreachable"):
        ensure(client)
    assert 60 <= clock.now <= 61


# --- 볼륨 삭제 ---


def test_delete_volume(agent, client):
    agent.reply("DELETE", f"/api/storage/volumes/{U1}", job("j1"), job("j2"))
    agent.reply("GET", "/api/cluster/jobs/j1", (404, {}))
    agent.reply("GET", "/api/cluster/jobs/j2", state("running"), state("success"))

    asyncio.run(client.delete_volume(U1, correlation_id="corr-2"))

    assert [p for p in agent.paths() if p[0] == "DELETE"] == [("DELETE", f"/api/storage/volumes/{U1}")] * 2


def test_failed_delete_raises(agent, client):
    agent.reply("DELETE", f"/api/storage/volumes/{U1}", job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("failure", "umount: target is busy"))
    with pytest.raises(StorageError, match="busy"):
        asyncio.run(client.delete_volume(U1))


# --- 스냅샷 (스냅샷 설계 결정 9, §6.1) ---

S1 = "5a000000-0000-4000-8000-000000000001"
SNAPSHOTS = f"/api/storage/volumes/{U1}/snapshots"


def test_ensure_snapshot_posts_polls_and_returns_the_create_time(agent, client):
    agent.reply("POST", SNAPSHOTS, job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("running"), state("success"))
    agent.reply("GET", f"{SNAPSHOTS}/{S1}", (200, {"uuid": S1, "name": "daily.1",
                                                   "create_time": "2026-11-08T23:07:12Z", "volume": {"uuid": U1}}))

    created = asyncio.run(client.ensure_snapshot(U1, S1, "daily.1", correlation_id="corr-3"))

    assert created == "2026-11-08T23:07:12Z"
    assert agent.requests[0][:3] == ("POST", SNAPSHOTS, {"name": "daily.1", "uuid": S1})
    assert all(h == {"x-ms-correlation-request-id": "corr-3"} for _, _, _, h in agent.requests)


def test_failed_snapshot_job_raises(agent, client):
    agent.reply("POST", SNAPSHOTS, job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("failure", "A snapshot with the specified name already exists."))
    with pytest.raises(StorageError, match="already exists"):
        asyncio.run(client.ensure_snapshot(U1, S1, "daily.1"))


def test_snapshot_gone_after_its_job_raises(agent, client):
    agent.reply("POST", SNAPSHOTS, job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("success"))
    agent.reply("GET", f"{SNAPSHOTS}/{S1}", (404, {"error": {"message": f"snapshot {S1} not found"}}))
    with pytest.raises(StorageError, match="404"):
        asyncio.run(client.ensure_snapshot(U1, S1, "daily.1"))


def test_delete_snapshot(agent, client):
    agent.reply("DELETE", f"{SNAPSHOTS}/{S1}", job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("success"))
    asyncio.run(client.delete_snapshot(U1, S1, correlation_id="corr-4"))
    assert agent.paths() == [("DELETE", f"{SNAPSHOTS}/{S1}"), ("GET", "/api/cluster/jobs/j1")]


# --- 되돌리기 (되돌리기 설계 결정 4·12, §6.1) ---

S2 = "5a000000-0000-4000-8000-000000000002"
REQ = "0c000000-0000-4000-8000-0000000000aa"
RESTORE = f"/api/storage/volumes/{U1}?restore_to.snapshot.uuid={S2}&restore_to.request_uuid={REQ}"


def revert(client, **kw):
    return asyncio.run(client.revert_volume(U1, S2, REQ, **kw))


def test_revert_volume_patches_polls_and_returns_the_remaining_snapshots(agent, client):
    agent.reply("PATCH", RESTORE, job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("running"), state("success"))
    agent.reply("GET", SNAPSHOTS, (200, {"records": [{"uuid": S1, "name": "a"}, {"uuid": S2, "name": "b"}],
                                         "num_records": 2}))

    assert revert(client, correlation_id="corr-5") == {S1, S2}

    # ONTAP SnapRestore: 볼륨 PATCH + 쿼리, 본문 없음. request_uuid는 클론 확장 멱등 키다
    assert agent.requests[0][:3] == ("PATCH", RESTORE, None)
    assert agent.paths()[1:] == [("GET", "/api/cluster/jobs/j1")] * 2 + [("GET", SNAPSHOTS)]
    assert all(h == {"x-ms-correlation-request-id": "corr-5"} for _, _, _, h in agent.requests)


def test_failed_revert_job_raises(agent, client):
    agent.reply("PATCH", RESTORE, job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("failure", f"snapshot {S2} not found"))
    with pytest.raises(StorageError, match="not found"):
        revert(client)


def test_lost_revert_job_is_requested_again_with_the_same_key(agent, client):
    # agent가 재시작하면 같은 request_uuid로 다시 보낸다. agent가 끝난 되돌리기를 다시 하지 않는다 (결정 4)
    agent.reply("PATCH", RESTORE, job("j1"), job("j2"))
    agent.reply("GET", "/api/cluster/jobs/j1", (404, {}))
    agent.reply("GET", "/api/cluster/jobs/j2", state("success"))
    agent.reply("GET", SNAPSHOTS, (200, {"records": [], "num_records": 0}))

    assert revert(client) == set()
    assert [p for p in agent.paths() if p[0] == "PATCH"] == [("PATCH", RESTORE)] * 2


def test_snapshot_list_failure_after_revert_raises(agent, client):
    agent.reply("PATCH", RESTORE, job("j1"))
    agent.reply("GET", "/api/cluster/jobs/j1", state("success"))
    agent.reply("GET", SNAPSHOTS, (404, {"error": {"message": f"volume {U1} not found"}}))
    with pytest.raises(StorageError, match="404"):
        revert(client)


# --- 기본 전송 (urllib) ---


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        body = json.loads(self.rfile.read(length))
        status = 400 if body.get("bad") else 202
        self._send(status, {"got": body, "correlation": self.headers.get("x-ms-correlation-request-id")})

    def do_DELETE(self):
        self._send(202, {"method": "DELETE"})

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_urllib_transport_sends_json_and_headers(http_server):
    status, reply = urllib_transport("POST", http_server + "/x", {"a": 1}, {"x-ms-correlation-request-id": "c"})
    assert (status, reply) == (202, {"got": {"a": 1}, "correlation": "c"})
    assert urllib_transport("DELETE", http_server + "/x", None, {}) == (202, {"method": "DELETE"})


def test_urllib_transport_returns_error_statuses(http_server):
    status, reply = urllib_transport("POST", http_server + "/x", {"bad": True}, {})
    assert status == 400
    assert reply["got"] == {"bad": True}


def test_urllib_transport_raises_oserror_when_refused():
    probe = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    closed = f"http://127.0.0.1:{probe.server_address[1]}"
    probe.server_close()  # 이 포트에는 이제 아무도 듣지 않는다
    with pytest.raises(OSError):
        urllib_transport("GET", closed + "/x", None, {})
