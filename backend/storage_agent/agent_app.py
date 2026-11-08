"""storage agent FastAPI 앱: ONTAP REST API의 부분집합 (ADR D-06, 볼륨 설계 §6).

실행 (WSL, root):
    sudo ~/.venvs/anf-clone/bin/python -m uvicorn --factory storage_agent.agent_app:create_app \\
        --app-dir backend --host 127.0.0.1 --port 8090

시작할 때 호스트 준비(Docker, 이미지, anf-vnet)를 확인하고 볼륨을 복구한다(마운트, 인스턴스). 준비가 안 됐으면 뜨지 않는다.
anf-api만 부르는 내부 API라 인증은 없다 (D-13). 커널 명령에 들어갈 값은 여기서 다시 검사한다 (R-07).
"""

import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from storage_agent.flexvol import FlexVolManager, lv_name
from storage_agent.jobs import JobTable
from storage_agent.runner import Runner

log = logging.getLogger(__name__)

GIB = 1 << 30
MAX_SIZE = 100 << 40  # ANF 일반 볼륨 상한
PROTOCOLS = ("nfs3", "nfs4.1")  # 볼륨 인스턴스가 켤 수 있는 버전 (결정 16)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PATH = re.compile(r"/[a-zA-Z][a-zA-Z0-9_-]{0,79}")  # "/" + creationToken 규칙 (anf_api.volumes)
_PERMISSIONS = re.compile(r"[0-7]{1,4}")  # ONTAP처럼 8진수 숫자를 그대로 쓴 정수 (770 = 0770)


class BadRequest(Exception):
    pass


def _check_uuid(value) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise BadRequest(f"uuid must be a lowercase UUID, got {value!r}")
    return value


def parse_volume(body) -> tuple[str, str, int, int, str]:
    """POST 본문 → (uuid, junction path, size, unix_permissions, protocol)."""
    if not isinstance(body, dict) or set(body) != {"uuid", "name", "size", "nas"}:
        raise BadRequest("body must have exactly the fields uuid, name, size, nas")
    nas = body["nas"]
    if not isinstance(nas, dict) or set(nas) != {"path", "unix_permissions", "protocols"}:
        raise BadRequest("nas must have exactly the fields path, unix_permissions, protocols")
    uuid = _check_uuid(body["uuid"])
    if body["name"] != lv_name(uuid):
        raise BadRequest(f"name must be {lv_name(uuid)}")
    size = body["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size % GIB or not GIB <= size <= MAX_SIZE:
        raise BadRequest("size must be a multiple of 1 GiB from 1 GiB to 100 TiB")
    path = nas["path"]
    if not isinstance(path, str) or not _PATH.fullmatch(path):
        raise BadRequest("nas.path must be / and a creation token: a letter, then up to 79 letters, digits, - or _")
    perms = nas["unix_permissions"]
    if isinstance(perms, bool) or not isinstance(perms, int) or not _PERMISSIONS.fullmatch(str(perms)):
        raise BadRequest("nas.unix_permissions must be up to four octal digits, such as 770")
    protocols = nas["protocols"]
    if not isinstance(protocols, list) or len(protocols) != 1 or protocols[0] not in PROTOCOLS:
        raise BadRequest(f"nas.protocols must be one of {[[p] for p in PROTOCOLS]}")
    return uuid, path, size, perms, protocols[0]


def _not_found(message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message}}, status_code=404)


def create_app(manager=None, jobs: JobTable | None = None) -> FastAPI:
    """앱 팩토리. 인자가 None이면 실제 볼륨 관리자(root 필요)와 job 표를 만든다."""
    if manager is None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        manager = FlexVolManager(Runner())
    if jobs is None:
        jobs = JobTable()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager.instances.check_host()  # StartupError면 뜨지 않는다 (§6.1)
        manager.recover()
        yield
        jobs.close()

    app = FastAPI(title="anf-clone storage agent", lifespan=lifespan)

    @app.exception_handler(BadRequest)
    async def bad_request(request: Request, exc: BadRequest):
        return JSONResponse({"error": {"message": str(exc)}}, status_code=400)

    def accepted(action: str, uuid: str, work, request: Request) -> JSONResponse:
        # 키는 작업 종류 + 볼륨 UUID: 같은 요청을 다시 보내면 진행 중인 그 job을 받는다 (결정 9)
        job = jobs.submit(f"{action} {uuid}", work, f"{action} /api/storage/volumes/{uuid}")
        log.info("%s volume %s: job %s (x-ms-correlation-request-id %s)", action, uuid, job["uuid"],
                 request.headers.get("x-ms-correlation-request-id"))
        href = f"/api/cluster/jobs/{job['uuid']}"
        return JSONResponse({"job": {"uuid": job["uuid"], "_links": {"self": {"href": href}}}}, status_code=202)

    @app.post("/api/storage/volumes")
    async def post_volume(request: Request):
        try:
            body = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BadRequest("body is not valid JSON") from None
        uuid, path, size, perms, protocol = parse_volume(body)
        return accepted("POST", uuid, lambda: manager.create(uuid, path, size, perms, protocol), request)

    # 볼륨 관리자를 부르는 경로는 def로 둔다: 커널 명령을 기다리는 동안 이벤트 루프를 막지 않게 스레드에서 돈다
    @app.get("/api/storage/volumes")
    def list_volumes(name: str | None = None):
        records = manager.records(name=name)
        return {"records": records, "num_records": len(records)}

    @app.get("/api/storage/volumes/{uuid}")
    def get_volume(uuid: str):
        record = manager.record(_check_uuid(uuid))
        return record if record is not None else _not_found(f"volume {uuid} not found")

    @app.delete("/api/storage/volumes/{uuid}")
    def delete_volume(uuid: str, request: Request):
        _check_uuid(uuid)
        return accepted("DELETE", uuid, lambda: manager.delete(uuid), request)

    @app.get("/api/cluster/jobs/{uuid}")
    def get_job(uuid: str):
        job = jobs.get(uuid)
        return job if job is not None else _not_found(f"job {uuid} not found")

    return app
