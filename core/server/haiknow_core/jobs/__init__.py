"""长任务 HTTP 与 FastAPI 生命周期接入。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends

from ..error_codes import public_error_code
from .service import JobService, SubmitBody


def _job_response(job):
    # 旧任务的快照在 HTTP 读出时规范平台码，持久化文档保留原值。
    error = job.get('error')
    if error:
        return {**job, 'error': {**error, 'code': public_error_code(error['code'])}}
    return job


def install(app, platform, current_user):
    service = platform.jobs = JobService(platform, app)
    platform.data.jobs = service
    router = APIRouter(prefix='/api/v1/jobs')

    @router.post('', status_code=202)
    def submit(body: SubmitBody, user=Depends(current_user)):
        return _job_response(service.submit(user, body.model_dump()))

    @router.get('')
    def jobs(app: str | None = None, project: str | None = None, status: str | None = None, user=Depends(current_user)):
        result = service.list(user, app_id=app, project=project, status=status)
        return {**result, 'items': [_job_response(job) for job in result['items']]}

    @router.get('/notifications')
    def notifications(app: str | None = None, user=Depends(current_user)):
        return service.notifications(user, app_id=app)

    @router.post('/notifications/{nid}/read')
    def read_notification(nid: str, app: str | None = None, user=Depends(current_user)):
        return service.read_notification(user, nid, app_id=app)

    @router.get('/{jid}')
    def get(jid: str, app: str | None = None, user=Depends(current_user)):
        return _job_response(service.get(user, jid, app_id=app))

    @router.post('/{jid}/cancel')
    def cancel(jid: str, app: str | None = None, user=Depends(current_user)):
        return _job_response(service.cancel(user, jid, app_id=app))

    @router.post('/{jid}/retry', status_code=202)
    def retry(jid: str, app: str | None = None, user=Depends(current_user)):
        return _job_response(service.retry(user, jid, app_id=app))

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with previous(instance) as state:
            service.start()
            try:
                yield state
            finally:
                await asyncio.to_thread(service.stop)

    app.router.lifespan_context = lifespan
    app.include_router(router)
