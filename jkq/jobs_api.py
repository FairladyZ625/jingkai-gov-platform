"""经开区长任务读接口，复用卫华的身份校验和任务快照。"""

from fastapi import Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from haiknow_sdk import DataError


def replace_core_route(router, path, method, endpoint):
    """替换实例上的同名路由，其他 core 端点和生命周期继续由 core 管理。"""
    routers = [router]
    while routers:
        current = routers.pop()
        for index, route in enumerate(current.routes):
            # FastAPI 新版保留被包含的路由器，旧版将 APIRoute 展开到父路由器。
            included = getattr(route, 'original_router', None)
            if included is not None:
                routers.append(included)
            if isinstance(route, APIRoute) and route.path == path and route.methods == {method}:
                current.routes[index] = APIRoute(path, endpoint, methods=[method])
                return
    raise RuntimeError(f'缺少待适配的 core 路由 {method} {path}')


def api_error(error, *, code=None, status=None):
    details = {key: value for key, value in error.error.items()
               if key not in ('code', 'message', 'retryable')}
    return JSONResponse(
        {'error': {'code': code or error.code.upper(), 'message': str(error), 'details': details}},
        status_code=status or error.status,
    )


def job_view(job):
    checkpoints = job['steps']
    names = [step['name'] for step in checkpoints]
    status = {'queued': 'running', 'cancelling': 'running', 'cancelled': 'failed'}.get(
        job['status'], job['status']
    )
    completed = sum(step['status'] == 'done' for step in checkpoints)
    last = checkpoints[-1] if checkpoints else None
    fraction = last.get('progress') if last and last['status'] != 'done' else None
    partial = fraction['current'] / fraction['total'] if fraction else 0
    # core 逐步登记检查点。未成功时预留一个单位，避免尚有后续步骤却显示 100%。
    progress = 100 if status == 'done' else int(100 * (completed + partial) / (len(names) + 1))
    return {
        'id': job['id'], 'kind': job['operation'], 'ref': job['input'].get('ref'),
        'status': status, 'progress': progress, 'step': max(0, len(names) - 1),
        'steps': names, 'stepName': names[-1] if names else None,
    }


def install(app, current_user):
    service = app.state.platform.jobs

    def get_job(jid: str, app: str | None = None, user=Depends(current_user)):
        try:
            return {'job': job_view(service.get(user, jid, app_id=app))}
        except DataError as error:
            return api_error(error)

    replace_core_route(app.router, '/api/v1/jobs/{jid}', 'GET', get_job)
