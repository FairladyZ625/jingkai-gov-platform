"""定时调度 preview HTTP 与生命周期接线。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends

from .service import ScheduleService


def install(app, platform, current_user):
    service = platform.schedules = ScheduleService(platform, app)
    router = APIRouter(prefix="/api/v1/schedules")

    @router.get("")
    def schedules(app: str | None = None, user=Depends(current_user)):
        return service.list(user, app_id=app)

    @router.post("/{app_id}/{name}/enable")
    def enable(app_id: str, name: str, project: str, user=Depends(current_user)):
        return service.enable(user, app_id, name, project)

    @router.post("/{app_id}/{name}/pause")
    def pause(app_id: str, name: str, project: str, user=Depends(current_user)):
        return service.pause(user, app_id, name, project)

    @router.post("/{app_id}/{name}/resume")
    def resume(app_id: str, name: str, project: str, user=Depends(current_user)):
        return service.resume(user, app_id, name, project)

    @router.post("/{app_id}/{name}/run")
    def run(app_id: str, name: str, project: str, user=Depends(current_user)):
        return service.run_now(user, app_id, name, project)

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
