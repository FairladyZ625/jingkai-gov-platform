"""经开区长任务读接口，复用卫华的身份校验和任务快照。"""

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from haiknow_core.stability import AppUnavailable
from haiknow_sdk import DataError


HTTP_ERROR_CODES = {
    401: 'unauthenticated',
    403: 'forbidden',
    404: 'not_found',
}
DATA_ERROR_STATUSES = {'self_review': 409, 'already_decided': 409}


def api_error(error, *, status=None, headers=None):
    details = {key: value for key, value in error.error.items()
               if key not in ('code', 'message', 'retryable')}
    return JSONResponse(
        {'error': {'code': error.code.upper(), 'message': str(error), 'details': details}},
        status_code=status if status is not None else DATA_ERROR_STATUSES.get(error.code, error.status),
        headers=headers,
    )


class JingkaiRoute(APIRoute):
    def __init__(self, core_route, endpoint, use_core, app):
        self.core_handler = core_route.get_route_handler()
        self.use_core = use_core
        super().__init__(core_route.path, endpoint, methods=core_route.methods,
                         dependency_overrides_provider=app)

    def get_route_handler(self):
        handle = super().get_route_handler()

        async def dispatch(request: Request):
            if await self.use_core(request):
                return await self.core_handler(request)
            try:
                return await handle(request)
            except DataError as error:
                return api_error(error)
            except RequestValidationError as error:
                fields = [list(item['loc']) for item in error.errors()]
                return api_error(DataError('invalid_request', '请求字段缺失或类型不正确', fields=fields))
            except HTTPException as error:
                code = HTTP_ERROR_CODES.get(error.status_code, 'invalid_request')
                message = error.detail if isinstance(error.detail, str) else '请求未通过'
                return api_error(DataError(code, message), status=error.status_code, headers=error.headers)
            except AppUnavailable as error:
                headers = {'Retry-After': str(error.retry_after)} if error.retry_after else None
                return api_error(DataError('app_unavailable', error.reason, app=error.app_id),
                                 status=503, headers=headers)

        return dispatch


def replace_core_route(app, path, method, endpoint, use_core):
    """为经开区路由保留同路径的 core 请求处理器。"""
    routers = [app.router]
    while routers:
        current = routers.pop()
        for index, route in enumerate(current.routes):
            # FastAPI 新版保留被包含的路由器，旧版将 APIRoute 展开到父路由器。
            included = getattr(route, 'original_router', None)
            if included is not None:
                routers.append(included)
            if isinstance(route, APIRoute) and route.path == path and route.methods == {method}:
                current.routes[index] = JingkaiRoute(route, endpoint, use_core, app)
                return
    raise RuntimeError(f'缺少待适配的 core 路由 {method} {path}')


def job_view(job):
    checkpoints = job['steps']
    names = [step['name'] for step in checkpoints]
    status = {'queued': 'running', 'cancelling': 'running', 'cancelled': 'failed'}.get(
        job['status'], job['status']
    )
    completed = sum(step['status'] == 'done' for step in checkpoints)
    # 总步骤数事先未知。按已持久完成的步骤递增，重启时未完成步骤重新进入也不会回退。
    progress = 100 if status == 'done' else 100 * completed // (completed + 1)
    return {
        'id': job['id'], 'kind': job['operation'], 'ref': job['input'].get('ref'),
        'status': status, 'progress': progress, 'step': max(0, len(names) - 1),
        'steps': names, 'stepName': names[-1] if names else None,
    }


async def sdk_job_view(request):
    return 'app' in request.query_params


def install(app, current_user):
    service = app.state.platform.jobs

    def get_job(jid: str, user=Depends(current_user)):
        return {'job': job_view(service.get(user, jid))}

    replace_core_route(app, '/api/v1/jobs/{jid}', 'GET', get_job, sdk_job_view)
