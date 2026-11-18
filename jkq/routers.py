"""实例路由注册。各业务模块导出带完整路径前缀的 APIRouter。"""

from fastapi import APIRouter, FastAPI, HTTPException

from .inbox import router as inbox_router
from .kb import install as install_kb

# 在这里显式登记业务模块的 router。经开区路由优先于同方法、同路径的 core 路由。
ROUTERS: tuple[APIRouter, ...] = (inbox_router,)

health = APIRouter()
stubs = APIRouter(prefix="/api/v1", include_in_schema=False)


@health.get("/api/health")
def health_check():
    return {"ok": True}


@stubs.get("/auth/session")
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
    for router in ROUTERS:
        app.include_router(router)
    routes[:] = routes[core_route_count:] + routes[:core_route_count]
    app.include_router(stubs)
