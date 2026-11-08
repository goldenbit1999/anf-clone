"""anf-api FastAPI 앱: ARM 경로, 응답 코드와 헤더, 작업 상태 URL (계정 설계 §4).

실행 (WSL):
    python -m uvicorn --factory anf_api.arm_app:create_app --app-dir backend --host 127.0.0.1 --port 8080

환경 변수:
    ANF_API_DB           상태 저장소 파일. 기본값 ~/.local/state/anf-clone/anf-api.db (설계 결정 10)
    ANF_FAULT_INJECTION  결함 주입 JSON. 기본은 꺼짐 (설계 §6.3)
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
from anf_api.arm_rules import ACCOUNT_TYPE, API_VERSION, ArmError, check_api_version, operation_path
from anf_api.lro import LroWorker, operation_status_body, parse_faults
from anf_api.state_store import Operation, StateStore

log = logging.getLogger(__name__)

ApiVersion = Annotated[str | None, Query(alias="api-version")]

_PROVIDER = "/providers/Microsoft.NetApp"
_ACCOUNTS_IN_RG = "/subscriptions/{subscription_id}/resourceGroups/{resource_group}" + _PROVIDER + "/netAppAccounts"
_ACCOUNT = _ACCOUNTS_IN_RG + "/{account_name}"
_ACCOUNTS_IN_SUB = "/subscriptions/{subscription_id}" + _PROVIDER + "/netAppAccounts"
_OPERATION = "/subscriptions/{subscription_id}" + _PROVIDER + "/locations/{location}/operationResults/{operation_id}"


def _default_db_path() -> Path:
    return Path(os.environ.get("ANF_API_DB") or Path.home() / ".local/state/anf-clone/anf-api.db")


async def _json_body(request: Request):
    try:
        return json.loads(await request.body())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ArmError(400, "InvalidRequestContent", "The request content is not valid JSON.") from None


def _operation_url(request: Request, op: Operation) -> str:
    """`Azure-AsyncOperation`에 넣을 절대 URL. 실서비스의 서명 파라미터(t, c, s, h)는 ARM이 붙이므로 뺀다."""
    path = operation_path(quote(op.subscription_id, safe=""), quote(op.location, safe=""), op.id)
    return f"{str(request.base_url).rstrip('/')}{path}?api-version={API_VERSION}"


def create_app(db_path: str | Path | None = None, fault_injection: str | None = None) -> FastAPI:
    """앱 팩토리. 인자가 None이면 환경 변수를 읽는다. 결함 주입 값이 잘못되면 ValueError로 시작을 막는다."""
    store = StateStore(db_path or _default_db_path())
    if fault_injection is None:
        fault_injection = os.environ.get("ANF_FAULT_INJECTION")
    handlers = dict(accounts.HANDLERS)
    faults = parse_faults(fault_injection, {resource_type for resource_type, _ in handlers})
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
        url = _operation_url(request, op)
        # ANF는 202에 두 헤더를 다 붙인다 (녹화). 본문은 없다.
        return Response(status_code=202, headers={
            "Location": f"{url}&operationResultResponseType=Location",
            "Azure-AsyncOperation": url,
        })

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
        assert res.type == ACCOUNT_TYPE  # 리소스 종류가 늘면 종류별 본문 함수를 고른다
        return accounts.account_body(res)

    return app
