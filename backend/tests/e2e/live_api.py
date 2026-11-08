"""실환경 검증 도구: anf-api를 실제 uvicorn 프로세스로 띄우고 HTTP로 부른다 (real-env-verify).

TestClient를 쓰지 않는다. 서버는 별도 프로세스이고, 요청은 표준 라이브러리 http.client로 보낸다.
서버를 이 도구가 직접 띄우고 죽이는 이유: 결함 주입(ANF_FAULT_INJECTION)과 SIGKILL 재시작을
확인하려면 같은 DB로 서버를 여러 번 다시 띄워야 하기 때문이다 (계정 설계 §7 AC-08~AC-11).

환경 변수:
    ANF_E2E_API_URL   anf-api를 띄울 주소 (예: http://127.0.0.1:8080). 없으면 e2e 테스트는 모두 skip.
    ANF_E2E_PYTHON    uvicorn을 실행할 Python. 기본은 pytest를 돌리는 Python.
    ANF_E2E_LOG       요청·응답·서버 이벤트를 JSON Lines로 남길 파일. 없으면 남기지 않는다.
"""

import http.client
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
API_URL = os.environ.get("ANF_E2E_API_URL", "")
PYTHON = os.environ.get("ANF_E2E_PYTHON") or sys.executable
LOG_PATH = os.environ.get("ANF_E2E_LOG")

SKIP_UNLESS_LIVE = pytest.mark.skipif(
    not API_URL, reason="ANF_E2E_API_URL is not set (live anf-api e2e runs in WSL)")

_url = urlsplit(API_URL or "http://127.0.0.1:8080")
HOST = _url.hostname
PORT = _url.port or 80
BASE_URL = f"http://{HOST}:{PORT}"

API_VERSION = "2026-08-01"
V = f"api-version={API_VERSION}"
SUB = "0e2e0000-1111-4222-8333-444455556666"
OTHER_SUB = "0e2e0000-9999-4999-8999-999999999999"
RG = "rg-e2e"
OTHER_RG = "rg-e2e-other"
LOC = "westus2"
ACCOUNT_TYPE = "Microsoft.NetApp/netAppAccounts"
POOL_TYPE = f"{ACCOUNT_TYPE}/capacityPools"
TIB = 1 << 40
TERMINAL = ("Succeeded", "Failed", "Canceled")
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# 설계 §7: 1초 간격으로 폴링, 제한 시간 30초 (지연을 주입했으면 지연 + 30초)
POLL_INTERVAL = 1.0
POLL_TIMEOUT = 30.0

# 이번 실행에서 받은 모든 응답. AC-13(모든 응답에 x-ms-request-id)을 확인할 때 쓴다.
RESPONSES: list["Resp"] = []


def log_event(kind: str, **data) -> None:
    if not LOG_PATH:
        return
    record = {"t": datetime.now(timezone.utc).isoformat(), "kind": kind,
              "test": os.environ.get("PYTEST_CURRENT_TEST", ""), **data}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass
class Resp:
    method: str
    target: str
    status: int
    headers: dict  # 이름은 소문자
    raw: bytes
    elapsed: float

    def json(self):
        return json.loads(self.raw)


def call(method: str, target: str, body=None, headers: dict | None = None) -> Resp:
    """target은 경로+쿼리 또는 절대 URL(작업 상태 URL)이다."""
    if target.startswith("http"):
        parts = urlsplit(target)
        assert (parts.hostname, parts.port) == (HOST, PORT), f"URL points elsewhere: {target}"
        target = parts.path + (f"?{parts.query}" if parts.query else "")
    send_headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        send_headers["Content-Type"] = "application/json"
    conn = http.client.HTTPConnection(HOST, PORT, timeout=15)
    try:
        start = time.monotonic()
        conn.request(method, target, body=data, headers=send_headers)
        r = conn.getresponse()
        raw = r.read()
        elapsed = time.monotonic() - start
        resp_headers = {}
        for name, value in r.getheaders():
            key = name.lower()
            resp_headers[key] = f"{resp_headers[key]}, {value}" if key in resp_headers else value
    finally:
        conn.close()
    resp = Resp(method, target, r.status, resp_headers, raw, elapsed)
    RESPONSES.append(resp)
    log_event("http", method=method, target=target, request_headers=send_headers, request_body=body,
              status=r.status, response_headers=resp_headers,
              response_body=raw.decode(errors="replace")[:4000], elapsed_ms=round(elapsed * 1000, 1))
    return resp


def account_path(name: str, rg: str = RG, sub: str = SUB) -> str:
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.NetApp/netAppAccounts/{name}"


def account_url(name: str, rg: str = RG, sub: str = SUB) -> str:
    return f"{account_path(name, rg, sub)}?{V}"


def rg_list_url(rg: str = RG, sub: str = SUB) -> str:
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.NetApp/netAppAccounts?{V}"


def sub_list_url(sub: str = SUB) -> str:
    return f"/subscriptions/{sub}/providers/Microsoft.NetApp/netAppAccounts?{V}"


def location_url(azure_async_operation: str) -> str:
    return f"{azure_async_operation}&operationResultResponseType=Location"


def poll(azure_async_operation: str, timeout: float = POLL_TIMEOUT) -> tuple[dict, list[str]]:
    """작업 상태 URL을 1초 간격으로 폴링한다. 반환: (종결 본문, 관찰한 status 순서)."""
    deadline = time.monotonic() + timeout
    seen = []
    while True:
        r = call("GET", azure_async_operation)
        assert r.status == 200, f"operation status GET returned {r.status}: {r.raw!r}"
        body = r.json()
        seen.append(body["status"])
        if body["status"] in TERMINAL:
            return body, seen
        assert time.monotonic() < deadline, f"operation not terminal after {timeout}s: {seen}"
        time.sleep(POLL_INTERVAL)


def create_account(name: str, tags: dict | None = None, rg: str = RG) -> dict:
    """새 계정을 PUT하고 작업이 Succeeded가 될 때까지 기다린다. 반환: GET 본문."""
    body = {"location": LOC}
    if tags is not None:
        body["tags"] = tags
    r = call("PUT", account_url(name, rg), body)
    assert r.status == 201, r.raw
    final, _ = poll(r.headers["azure-asyncoperation"])
    assert final["status"] == "Succeeded", final
    g = call("GET", account_url(name, rg))
    assert g.status == 200, g.raw
    return g.json()


def pool_path(account: str, name: str, rg: str = RG, sub: str = SUB) -> str:
    return f"{account_path(account, rg, sub)}/capacityPools/{name}"


def pool_url(account: str, name: str, rg: str = RG, sub: str = SUB) -> str:
    return f"{pool_path(account, name, rg, sub)}?{V}"


def pool_list_url(account: str, rg: str = RG, sub: str = SUB) -> str:
    return f"{account_path(account, rg, sub)}/capacityPools?{V}"


def create_pool(account: str, name: str, size: int = 4 * TIB, service_level: str = "Premium",
                tags: dict | None = None, timeout: float = POLL_TIMEOUT) -> dict:
    """새 풀을 PUT하고 작업이 Succeeded가 될 때까지 기다린다. 반환: GET 본문."""
    body = {"location": LOC, "properties": {"size": size, "serviceLevel": service_level}}
    if tags is not None:
        body["tags"] = tags
    r = call("PUT", pool_url(account, name), body)
    assert r.status == 201, r.raw
    final, _ = poll(r.headers["azure-asyncoperation"], timeout)
    assert final["status"] == "Succeeded", final
    g = call("GET", pool_url(account, name))
    assert g.status == 200, g.raw
    return g.json()


def db_resources(db_path: Path) -> list[dict]:
    """상태 저장소의 리소스 행 (보조 증거: 리소스가 생기거나 지워졌는지 확인할 때 쓴다)."""
    with closing(sqlite3.connect(db_path, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, type, parent_id, provisioning_state FROM resources ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def db_operations(db_path: Path) -> list[dict]:
    """상태 저장소의 작업 기록 (보조 증거: 작업이 새로 생기지 않았는지 확인할 때 쓴다)."""
    with closing(sqlite3.connect(db_path, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, resource_id, action, status, correlation_id, error, start_time, end_time "
            "FROM operations ORDER BY start_time").fetchall()
    return [dict(r) for r in rows]


def port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


_server_numbers = count(1)


class Server:
    """anf-api uvicorn 프로세스 하나. 설계 §6.5의 실행 명령을 그대로 쓴다."""

    def __init__(self, db_path: Path, faults: dict | None = None, raw_faults: str | None = None):
        self.db_path = Path(db_path)
        self.fault_injection = raw_faults if raw_faults is not None else (
            json.dumps(faults) if faults else None)
        self.log_path = self.db_path.parent / f"server-{next(_server_numbers)}.log"
        self.proc: subprocess.Popen | None = None
        self._log = None

    def launch(self) -> None:
        deadline = time.monotonic() + 10
        while port_open():
            assert time.monotonic() < deadline, f"{HOST}:{PORT} is already in use"
            time.sleep(0.2)
        env = os.environ.copy()
        env["ANF_API_DB"] = str(self.db_path)
        env.pop("ANF_FAULT_INJECTION", None)
        if self.fault_injection is not None:
            env["ANF_FAULT_INJECTION"] = self.fault_injection
        cmd = [PYTHON, "-m", "uvicorn", "--factory", "anf_api.arm_app:create_app",
               "--app-dir", "backend", "--host", HOST, "--port", str(PORT)]
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(cmd, cwd=REPO_ROOT, env=env,
                                     stdout=self._log, stderr=subprocess.STDOUT)
        log_event("server-launch", pid=self.proc.pid, cmd=cmd, db=str(self.db_path),
                  fault_injection=self.fault_injection)

    def start(self, timeout: float = 30) -> "Server":
        self.launch()
        deadline = time.monotonic() + timeout
        while True:
            if self.proc.poll() is not None:
                raise RuntimeError(f"anf-api exited with {self.proc.returncode}:\n{self.output()}")
            if port_open():
                r = call("GET", sub_list_url())
                if r.status == 200:
                    log_event("server-ready", pid=self.proc.pid)
                    return self
            assert time.monotonic() < deadline, f"anf-api not ready:\n{self.output()}"
            time.sleep(0.2)

    def output(self) -> str:
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def sigkill(self) -> int:
        self.proc.send_signal(signal.SIGKILL)
        rc = self.proc.wait(10)
        log_event("server-sigkill", pid=self.proc.pid, returncode=rc)
        self._close_log()
        return rc

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
            log_event("server-stop", pid=self.proc.pid, returncode=self.proc.returncode)
        self._close_log()

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None
