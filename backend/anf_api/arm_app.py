"""anf-api FastAPI 앱: ARM 경로, 응답 코드와 헤더, 작업 상태 URL (계정 설계 §4).

실행 (WSL):
    python -m uvicorn --factory anf_api.arm_app:create_app --app-dir backend --host 127.0.0.1 --port 8080

환경 변수:
    ANF_API_DB               상태 저장소 파일. 기본값 ~/.local/state/anf-clone/anf-api.db (설계 결정 10)
    ANF_FAULT_INJECTION      결함 주입 JSON. 기본은 꺼짐 (설계 §6.3)
    ANF_STORAGE_AGENT_URL    storage agent 주소. 기본값 http://127.0.0.1:8090 (볼륨 설계 §6.1)
    ANF_MIN_VOLUME_SIZE_GIB  최소 볼륨 크기(GiB). 기본은 ANF의 50 GiB. 검증할 때만 낮춘다 (볼륨 설계 결정 3)
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

import anf_api.accounts as accounts
import anf_api.capacity_pools as pools
import anf_api.snapshots as snapshots
import anf_api.volumes as volumes
from anf_api.arm_rules import (
    ACCOUNT_TYPE,
    API_VERSION,
    POOL_TYPE,
    SNAPSHOT_TYPE,
    VOLUME_TYPE,
    ArmError,
    check_api_version,
    operation_path,
)
from anf_api.lro import LroWorker, operation_status_body, parse_faults
from anf_api.state_store import Operation, StateStore
from anf_api.storage_client import StorageClient

log = logging.getLogger(__name__)

ApiVersion = Annotated[str | None, Query(alias="api-version")]

_PROVIDER = "/providers/Microsoft.NetApp"
_ACCOUNTS_IN_RG = "/subscriptions/{subscription_id}/resourceGroups/{resource_group}" + _PROVIDER + "/netAppAccounts"
_ACCOUNT = _ACCOUNTS_IN_RG + "/{account_name}"
_ACCOUNTS_IN_SUB = "/subscriptions/{subscription_id}" + _PROVIDER + "/netAppAccounts"
_POOLS = _ACCOUNT + "/capacityPools"
_POOL = _POOLS + "/{pool_name}"
_VOLUMES = _POOL + "/volumes"
_VOLUME = _VOLUMES + "/{volume_name}"
_SNAPSHOTS = _VOLUME + "/snapshots"
_SNAPSHOT = _SNAPSHOTS + "/{snapshot_name}"
_OPERATION = "/subscriptions/{subscription_id}" + _PROVIDER + "/locations/{location}/operationResults/{operation_id}"

# Location 방식으로 끝난 작업이 돌려줄 리소스 본문 (리소스 종류별)
_BODIES = {ACCOUNT_TYPE: accounts.account_body, POOL_TYPE: pools.pool_body, VOLUME_TYPE: volumes.volume_body,
           SNAPSHOT_TYPE: snapshots.snapshot_body}


def _default_db_path() -> Path:
    return Path(os.environ.get("ANF_API_DB") or Path.home() / ".local/state/anf-clone/anf-api.db")


def _min_volume_size(text: str) -> int:
    """`ANF_MIN_VOLUME_SIZE_GIB` 값을 바이트로. 비어 있으면 ANF 기본값. 잘못된 값은 ValueError로 시작을 막는다."""
    if not text:
        return volumes.DEFAULT_MIN_SIZE
    if not text.isdigit() or int(text) < 1:
        raise ValueError(f"ANF_MIN_VOLUME_SIZE_GIB must be a whole number of GiB >= 1, got '{text}'")
    log.warning("ANF_MIN_VOLUME_SIZE_GIB=%s: volumes may be smaller than the ANF minimum of 50 GiB "
                "(for verification only)", text)
    return int(text) * volumes.GIB


async def _json_body(request: Request):
    try:
        return json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ArmError(400, "InvalidRequestContent", "The request content is not valid JSON.") from None


def _operation_url(request: Request, op: Operation) -> str:
    """`Azure-AsyncOperation`에 넣을 절대 URL. 실서비스의 서명 파라미터(t, c, s, h)는 ARM이 붙이므로 뺀다."""
    path = operation_path(quote(op.subscription_id, safe=""), quote(op.location, safe=""), op.id)
    return f"{str(request.base_url).rstrip('/')}{path}?api-version={API_VERSION}"


def _tracking_headers(request: Request, op: Operation) -> dict:
    """PATCH·DELETE의 202에 붙이는 두 헤더. ANF는 둘 다 붙인다 (녹화)."""
    url = _operation_url(request, op)
    return {"Location": f"{url}&operationResultResponseType=Location", "Azure-AsyncOperation": url}


def create_app(db_path: str | Path | None = None, fault_injection: str | None = None, storage=None,
               min_volume_size_gib: str | None = None) -> FastAPI:
    """앱 팩토리. 인자가 None이면 환경 변수를 읽는다. 결함 주입·최소 크기 값이 잘못되면 ValueError로 시작을 막는다.
    storage는 agent 클라이언트다. 테스트는 가짜를 넣는다."""
    store = StateStore(db_path or _default_db_path())
    if fault_injection is None:
        fault_injection = os.environ.get("ANF_FAULT_INJECTION")
    if min_volume_size_gib is None:
        min_volume_size_gib = os.environ.get("ANF_MIN_VOLUME_SIZE_GIB", "")
    min_size = _min_volume_size(min_volume_size_gib)
    if storage is None:
        storage = StorageClient(os.environ.get("ANF_STORAGE_AGENT_URL") or "http://127.0.0.1:8090")
    handlers = {**accounts.HANDLERS, **pools.HANDLERS, **volumes.make_handlers(store, storage),
                **snapshots.make_handlers(store, storage)}
    faults = parse_faults(fault_injection, handlers)
    if faults:
        log.warning("Fault injection is enabled (ANF_FAULT_INJECTION): %s", faults)
    worker = LroWorker(store, handlers, faults)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(worker.run())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="anf-api", lifespan=lifespan)
    app.state.store = store
    app.state.worker = worker

    @app.middleware("http")
    async def arm_request_ids(request: Request, call_next):
        # ARM 관례 헤더 (ADR §8). 상관 ID는 받은 값을 이어 쓰고, 작업 기록에도 남긴다 (NFR-08).
        correlation_id = request.headers.get("x-ms-correlation-request-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["x-ms-request-id"] = str(uuid.uuid4())
        response.headers["x-ms-correlation-request-id"] = correlation_id
        return response

    @app.exception_handler(ArmError)
    async def arm_error(request: Request, exc: ArmError):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.put(_ACCOUNT)
    async def put_account(subscription_id: str, resource_group: str, account_name: str,
                          request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        created, res, op = accounts.put_account(
            store, subscription_id, resource_group, account_name, body, request.state.correlation_id)
        worker.notify()
        # 생성은 201, 갱신은 200. 둘 다 Azure-AsyncOperation으로 폴링한다 (녹화 R1, R3)
        return JSONResponse(accounts.account_body(res), status_code=201 if created else 200,
                            headers={"Azure-AsyncOperation": _operation_url(request, op)})

    @app.get(_ACCOUNT)
    async def get_account(subscription_id: str, resource_group: str, account_name: str,
                          api_version: ApiVersion = None):
        check_api_version(api_version)
        res = accounts.get_account(store, subscription_id, resource_group, account_name)
        return accounts.account_body(res)

    @app.patch(_ACCOUNT)
    async def patch_account(subscription_id: str, resource_group: str, account_name: str,
                            request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        res = accounts.patch_account(store, subscription_id, resource_group, account_name, body)
        return accounts.account_body(res)  # 동기 200, 추적 헤더 없음 (녹화 R2)

    @app.delete(_ACCOUNT)
    async def delete_account(subscription_id: str, resource_group: str, account_name: str,
                             request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        op = accounts.delete_account(
            store, subscription_id, resource_group, account_name, request.state.correlation_id)
        if op is None:
            return Response(status_code=204)  # 없는 리소스 [스펙 3, 8]
        worker.notify()
        # ANF는 202에 두 헤더를 다 붙인다 (녹화). 본문은 없다.
        return Response(status_code=202, headers=_tracking_headers(request, op))

    @app.get(_ACCOUNTS_IN_RG)
    async def list_accounts_in_resource_group(subscription_id: str, resource_group: str,
                                              api_version: ApiVersion = None):
        check_api_version(api_version)
        return {"value": [accounts.account_body(r)
                          for r in accounts.list_accounts(store, subscription_id, resource_group)]}

    @app.get(_ACCOUNTS_IN_SUB)
    async def list_accounts_in_subscription(subscription_id: str, api_version: ApiVersion = None):
        check_api_version(api_version)
        return {"value": [accounts.account_body(r)
                          for r in accounts.list_accounts(store, subscription_id)]}

    @app.put(_POOL)
    async def put_pool(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                       request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        created, res, op = pools.put_pool(store, subscription_id, resource_group, account_name,
                                          pool_name, body, request.state.correlation_id)
        worker.notify()
        # 계정과 같다: 생성 201, 갱신 200, 둘 다 Azure-AsyncOperation만 (녹화 N1, N3, 풀 설계 결정 1)
        return JSONResponse(pools.pool_body(res), status_code=201 if created else 200,
                            headers={"Azure-AsyncOperation": _operation_url(request, op)})

    @app.get(_POOL)
    async def get_pool(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                       api_version: ApiVersion = None):
        check_api_version(api_version)
        return pools.pool_body(
            pools.get_pool(store, subscription_id, resource_group, account_name, pool_name))

    @app.patch(_POOL)
    async def patch_pool(subscription_id: str, resource_group: str, account_name: str,
                         pool_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        res, op = pools.patch_pool(store, subscription_id, resource_group, account_name, pool_name,
                                   body, request.state.correlation_id)
        worker.notify()
        # 계정 PATCH(동기 200)와 달리 풀 PATCH는 202 + Patching 본문 + 두 헤더다 (녹화 N2, P1)
        return JSONResponse(pools.pool_body(res), status_code=202,
                            headers=_tracking_headers(request, op))

    @app.delete(_POOL)
    async def delete_pool(subscription_id: str, resource_group: str, account_name: str,
                          pool_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        op = pools.delete_pool(store, subscription_id, resource_group, account_name, pool_name,
                               request.state.correlation_id)
        if op is None:
            return Response(status_code=204)
        worker.notify()
        return Response(status_code=202, headers=_tracking_headers(request, op))

    @app.get(_POOLS)
    async def list_pools(subscription_id: str, resource_group: str, account_name: str,
                         api_version: ApiVersion = None):
        check_api_version(api_version)
        return {"value": [pools.pool_body(r) for r in
                          pools.list_pools(store, subscription_id, resource_group, account_name)]}

    @app.put(_VOLUME)
    async def put_volume(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                         volume_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        created, res, op = volumes.put_volume(store, subscription_id, resource_group, account_name, pool_name,
                                              volume_name, body, request.state.correlation_id, min_size)
        worker.notify()
        # 풀과 같다: 생성 201, 갱신 200, 둘 다 Azure-AsyncOperation만 (녹화 V1, V2).
        # 스냅샷에서 만드는 생성 201은 두 헤더다 (녹화 R4, 복원 설계 §4.1)
        if created and "snapshotId" in res.properties:
            headers = _tracking_headers(request, op)
        else:
            headers = {"Azure-AsyncOperation": _operation_url(request, op)}
        return JSONResponse(volumes.volume_body(res), status_code=201 if created else 200, headers=headers)

    @app.get(_VOLUME)
    async def get_volume(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                         volume_name: str, api_version: ApiVersion = None):
        check_api_version(api_version)
        return volumes.volume_body(volumes.get_volume(
            store, subscription_id, resource_group, account_name, pool_name, volume_name))

    @app.patch(_VOLUME)
    async def patch_volume(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                           volume_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        res, op = volumes.patch_volume(store, subscription_id, resource_group, account_name, pool_name,
                                       volume_name, body, request.state.correlation_id, min_size)
        worker.notify()
        # tags만 바꿔도 202 + Patching 본문 + 두 헤더 (녹화 V3)
        return JSONResponse(volumes.volume_body(res), status_code=202, headers=_tracking_headers(request, op))

    @app.delete(_VOLUME)
    async def delete_volume(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                            volume_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        op = volumes.delete_volume(store, subscription_id, resource_group, account_name, pool_name,
                                   volume_name, request.state.correlation_id)
        if op is None:
            return Response(status_code=204)
        worker.notify()
        return Response(status_code=202, headers=_tracking_headers(request, op))

    @app.post(_VOLUME + "/revert")
    async def revert_volume(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                            volume_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        op = volumes.revert_volume(store, subscription_id, resource_group, account_name, pool_name,
                                   volume_name, body, request.state.correlation_id)
        worker.notify()
        # 본문 없는 202 + 두 헤더 (녹화 R3, 되돌리기 설계 결정 5)
        return Response(status_code=202, headers=_tracking_headers(request, op))

    @app.get(_VOLUMES)
    async def list_volumes(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                           api_version: ApiVersion = None):
        check_api_version(api_version)
        return {"value": [volumes.volume_body(r) for r in volumes.list_volumes(
            store, subscription_id, resource_group, account_name, pool_name)]}

    @app.put(_SNAPSHOT)
    async def put_snapshot(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                           volume_name: str, snapshot_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        body = await _json_body(request)
        created, res, op = snapshots.put_snapshot(store, subscription_id, resource_group, account_name, pool_name,
                                                  volume_name, snapshot_name, body, request.state.correlation_id)
        worker.notify()
        # 생성 201에는 두 헤더 (녹화 R1). 다시 PUT은 200 + Azure-AsyncOperation만 (스냅샷 설계 결정 3)
        headers = _tracking_headers(request, op) if created else {"Azure-AsyncOperation": _operation_url(request, op)}
        return JSONResponse(snapshots.snapshot_body(res), status_code=201 if created else 200, headers=headers)

    @app.get(_SNAPSHOT)
    async def get_snapshot(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                           volume_name: str, snapshot_name: str, api_version: ApiVersion = None):
        check_api_version(api_version)
        return snapshots.snapshot_body(snapshots.get_snapshot(
            store, subscription_id, resource_group, account_name, pool_name, volume_name, snapshot_name))

    @app.delete(_SNAPSHOT)
    async def delete_snapshot(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                              volume_name: str, snapshot_name: str, request: Request, api_version: ApiVersion = None):
        check_api_version(api_version)
        op = snapshots.delete_snapshot(store, subscription_id, resource_group, account_name, pool_name,
                                       volume_name, snapshot_name, request.state.correlation_id)
        if op is None:
            return Response(status_code=204)
        worker.notify()
        return Response(status_code=202, headers=_tracking_headers(request, op))

    @app.get(_SNAPSHOTS)
    async def list_snapshots(subscription_id: str, resource_group: str, account_name: str, pool_name: str,
                             volume_name: str, api_version: ApiVersion = None):
        check_api_version(api_version)
        return {"value": [snapshots.snapshot_body(r) for r in snapshots.list_snapshots(
            store, subscription_id, resource_group, account_name, pool_name, volume_name)]}

    @app.get(_OPERATION)
    async def operation_result(
        subscription_id: str, location: str, operation_id: str, request: Request,
        api_version: ApiVersion = None,
        response_type: Annotated[str | None, Query(alias="operationResultResponseType")] = None,
    ):
        check_api_version(api_version)
        op = store.get_operation(operation_id)
        if (op is None or op.subscription_id.lower() != subscription_id.lower()
                or op.location.lower() != location.lower()):
            raise ArmError(404, "ResourceNotFound", f"The operation '{operation_id}' is not found.")
        if response_type != "Location":
            # Azure-AsyncOperation 방식: 진행 중이든 끝났든 200, 상태는 본문의 status [문서 24]
            return operation_status_body(op)
        # Location 방식: 진행 중이면 본문 없는 202, 끝나면 동기로 실행했을 때와 같은 응답 [문서 24]
        if not op.is_terminal:
            return Response(status_code=202, headers={"Location": str(request.url)})
        if op.status == "Failed":
            error = op.error
            return JSONResponse({"error": {"code": error["code"], "message": error["message"]}},
                                status_code=error["httpStatus"])
        if op.action == "DELETE":
            return Response(status_code=204)
        res = store.get_resource(op.resource_id)
        if res is None:
            raise ArmError(404, "ResourceNotFound",
                           f"The resource with identifier '{op.resource_id}' is not found.")
        return _BODIES[res.type](res)

    return app
