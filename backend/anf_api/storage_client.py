"""anf-api → storage agent 호출 (볼륨 설계 결정 9·11, §6.2).

ARM의 ANF 리소스 공급자가 ONTAP REST API로 볼륨을 만들 듯, anf-api의 볼륨 처리기는 agent의 ONTAP REST 부분집합을 부른다.
표준 라이브러리 urllib을 스레드에서 부른다(이벤트 루프를 막지 않게). 연결이 안 되면 60초 동안 다시 시도한다.
job은 agent 메모리에만 있으므로, job이 사라졌으면(agent 재시작) 같은 요청을 다시 보낸다. agent 요청은 멱등이다.
"""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class StorageError(Exception):
    """agent가 작업을 끝내지 못했다: job 실패, 거절, 연결 안 됨."""


def urllib_transport(method: str, url: str, body: dict | None, headers: dict, timeout: float = 30) -> tuple:
    """HTTP 요청 하나. (상태 코드, JSON 본문)을 돌려준다. 연결이 안 되면 OSError다."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={**headers, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, _json(response.read())
    except urllib.error.HTTPError as e:  # 4xx·5xx도 응답이다
        return e.code, _json(e.read())


def _json(raw: bytes):
    return json.loads(raw) if raw else None


def _message(reply) -> str:
    return (reply or {}).get("error", {}).get("message", "") if isinstance(reply, dict) else ""


class StorageClient:
    def __init__(self, base_url: str, transport=urllib_transport, retry_seconds: float = 60.0,
                 poll_seconds: float = 1.0, sleep=asyncio.sleep, clock=time.monotonic):
        self._base = base_url.rstrip("/")
        self._transport = transport
        self._retry = retry_seconds
        self._poll = poll_seconds
        self._sleep = sleep
        self._clock = clock

    async def ensure_volume(self, uuid: str, junction_path: str, size: int, unix_permissions: int,
                            protocol: str, correlation_id: str | None = None,
                            clone: tuple[str, str] | None = None, qos: float | None = None) -> str:
        """볼륨이 있게 하고(없으면 만들고) data LIF IP를 돌려준다. clone = (부모 볼륨 uuid, 부모 스냅샷 uuid)면
        그 스냅샷에서 만든다 (ONTAP FlexClone 필드, 복원 설계 결정 14). qos는 처리량 한도(MiB/s)이고 ONTAP 볼륨의
        인라인 QoS 필드로 보낸다 (처리량 설계 결정 8)."""
        body = {"uuid": uuid, "name": "vol_" + uuid.replace("-", ""), "size": size,
                "nas": {"path": junction_path, "unix_permissions": unix_permissions, "protocols": [protocol]}}
        if clone is not None:
            body["clone"] = {"is_flexclone": True, "parent_volume": {"uuid": clone[0]},
                             "parent_snapshot": {"uuid": clone[1]}}
        if qos is not None:
            body["qos"] = {"policy": {"max_throughput_mbps": qos}}
        await self._run_job("POST", "/api/storage/volumes", body, correlation_id)
        path = f"/api/storage/volumes/{uuid}"
        status, record = await self._call("GET", path, None, correlation_id)
        if status != 200:
            raise StorageError(f"GET {path}: agent answered {status}: {_message(record)}")
        return record["data_lif"]["ip"]["address"]

    async def delete_volume(self, uuid: str, correlation_id: str | None = None) -> None:
        await self._run_job("DELETE", f"/api/storage/volumes/{uuid}", None, correlation_id)

    async def ensure_snapshot(self, volume_uuid: str, uuid: str, name: str,
                              correlation_id: str | None = None) -> str:
        """스냅샷이 있게 하고(없으면 만들고) 만든 시각(agent의 create_time, UTC ISO 8601)을 돌려준다.
        uuid는 anf-api가 정한 멱등 키다 (스냅샷 설계 결정 9)."""
        snapshots = f"/api/storage/volumes/{volume_uuid}/snapshots"
        await self._run_job("POST", snapshots, {"name": name, "uuid": uuid}, correlation_id)
        path = f"{snapshots}/{uuid}"
        status, record = await self._call("GET", path, None, correlation_id)
        if status != 200:
            raise StorageError(f"GET {path}: agent answered {status}: {_message(record)}")
        return record["create_time"]

    async def delete_snapshot(self, volume_uuid: str, uuid: str, correlation_id: str | None = None) -> None:
        await self._run_job("DELETE", f"/api/storage/volumes/{volume_uuid}/snapshots/{uuid}", None, correlation_id)

    async def revert_volume(self, volume_uuid: str, snapshot_uuid: str, request_uuid: str,
                            correlation_id: str | None = None) -> set[str]:
        """볼륨을 스냅샷으로 되돌리고(ONTAP SnapRestore) 남은 스냅샷 uuid를 돌려준다.
        request_uuid는 anf-api 작업 ID다: agent가 끝낸 되돌리기를 다시 하지 않게 하는 멱등 키 (되돌리기 설계 결정 4)."""
        volume = f"/api/storage/volumes/{volume_uuid}"
        query = f"?restore_to.snapshot.uuid={snapshot_uuid}&restore_to.request_uuid={request_uuid}"
        await self._run_job("PATCH", volume + query, None, correlation_id)
        return await self.snapshot_uuids(volume_uuid, correlation_id)

    async def snapshot_uuids(self, volume_uuid: str, correlation_id: str | None = None) -> set[str]:
        """agent에 있는 그 볼륨의 스냅샷 uuid."""
        return {record["uuid"] for record in await self.snapshot_records(volume_uuid, correlation_id)}

    async def snapshot_records(self, volume_uuid: str, correlation_id: str | None = None) -> list[dict]:
        """agent에 있는 그 볼륨의 스냅샷 레코드 (uuid, name, create_time, volume.uuid)."""
        path = f"/api/storage/volumes/{volume_uuid}/snapshots"
        status, reply = await self._call("GET", path, None, correlation_id)
        if status != 200:
            raise StorageError(f"GET {path}: agent answered {status}: {_message(reply)}")
        return reply["records"]

    async def _run_job(self, method: str, path: str, body: dict | None, correlation_id: str | None) -> None:
        while True:
            status, reply = await self._call(method, path, body, correlation_id)
            if status != 202:
                raise StorageError(f"{method} {path}: agent answered {status}: {_message(reply)}")
            href = reply["job"]["_links"]["self"]["href"]
            while True:
                status, job = await self._call("GET", href, None, correlation_id)
                if status == 404:
                    log.warning("job %s is gone (storage agent restarted?); sending %s %s again", href, method, path)
                    break
                if status != 200:
                    raise StorageError(f"GET {href}: agent answered {status}: {_message(job)}")
                if job["state"] == "success":
                    return
                if job["state"] == "failure":
                    raise StorageError(f"{method} {path} failed: {job['message']}")
                await self._sleep(self._poll)

    async def _call(self, method: str, path: str, body: dict | None, correlation_id: str | None) -> tuple:
        headers = {"x-ms-correlation-request-id": correlation_id} if correlation_id else {}
        deadline = None
        while True:
            try:
                return await asyncio.to_thread(self._transport, method, self._base + path, body, headers)
            except OSError as e:
                now = self._clock()
                if deadline is None:
                    deadline = now + self._retry
                if now >= deadline:
                    raise StorageError(f"storage agent at {self._base} is unreachable: {e}") from e
                log.warning("storage agent at %s is unreachable (%s); retrying", self._base, e)
                await self._sleep(1.0)
