"""长任务 HTTP 与 FastAPI 生命周期接入。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends

from .service import JobService, SubmitBody


def install(app, platform, current_user):
    service = platform.jobs = JobService(platform, app)
    platform.data.jobs = service
    router = APIRouter(prefix='/api/v1/jobs')

    @router.post('', status_code=202)
    def submit(body: SubmitBody, user=Depends(current_user)):
        return service.submit(user, body.model_dump(), public=True)

    @router.get('')
    def jobs(app: str | None = None, project: str | None = None, status: str | None = None, user=Depends(current_user)):
        return service.list(user, app_id=app, project=project, status=status, public=True)

    @router.get('/notifications')
    def notifications(app: str | None = None, user=Depends(current_user)):
        return service.notifications(user, app_id=app)

    @router.post('/notifications/{nid}/read')
    def read_notification(nid: str, app: str | None = None, user=Depends(current_user)):
        return service.read_notification(user, nid, app_id=app)

    @router.get('/{jid}')
    def get(jid: str, app: str | None = None, user=Depends(current_user)):
        return service.get(user, jid, app_id=app, public=True)

    @router.post('/{jid}/cancel')
    def cancel(jid: str, app: str | None = None, user=Depends(current_user)):
        return service.cancel(user, jid, app_id=app)

    @router.post('/{jid}/retry', status_code=202)
    def retry(jid: str, app: str | None = None, user=Depends(current_user)):
        return service.retry(user, jid, app_id=app)

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
