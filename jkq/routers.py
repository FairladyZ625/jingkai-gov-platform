"""实例路由注册。各业务模块导出带完整路径前缀的 APIRouter。"""

import os

from fastapi import APIRouter, FastAPI, HTTPException

from .inbox import router as inbox_router
from .kb import install as install_kb
from .models import install as install_models
from .transcribe import router as transcribe_router

# 在这里显式登记业务模块的 router。经开区路由优先于同方法、同路径的 core 路由。
ROUTERS: tuple[APIRouter, ...] = (transcribe_router, inbox_router)

health = APIRouter()
stubs = APIRouter(prefix="/api/v1", include_in_schema=False)


@health.get("/api/health")
def health_check():
    return {"ok": True}


@stubs.api_route("/admin/departments", methods=["GET", "POST"])
@stubs.api_route("/admin/departments/{department_id}", methods=["PATCH", "DELETE"])
def unavailable_contract_route():
    raise HTTPException(404, "接口待接入")


def register_routes(app: FastAPI) -> None:
    from haiknow_core.main import current_user

    routes = app.router.routes
    # core 健康检查还用于卫华自身，实例替换它的 HTTP 契约。
    routes[:] = [route for route in routes if getattr(route, "path", None) != "/api/health"]
    core_route_count = len(routes)
    app.include_router(health)
    install_kb(app, app.state.platform, current_user)
    install_models(app)
    for router in ROUTERS:
        app.include_router(router)
    routes[:] = routes[core_route_count:] + routes[:core_route_count]
    # #48：配置了本地模拟站时挂载电脑操作运行器。见 Issue #48 评论。
    mock_url = os.environ.get("JKQ_MOCK_GOV_URL", "").strip()
    if mock_url:
        from haiknow_core.main import current_user
        from .computer.api import install as install_computer

        install_computer(app, current_user, url=mock_url,
                         channel=os.environ.get("JKQ_BROWSER_CHANNEL") or None)
    app.include_router(stubs)
