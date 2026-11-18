"""经开区 v1 管理后台。"""

from fastapi import APIRouter

from jkq.auth import AuthRoute, require_action


def install(app):
    """在 auth 和实例路由之后安装，使正式接口优先于同名占位。"""
    from . import audit, identity, platform

    instance = app.state.platform
    admin = require_action('*', 'admin')
    router = APIRouter(route_class=AuthRoute)
    identity.register(router, instance, admin)
    platform.register(router, instance, admin)
    audit.register(router, instance, admin)
    app.add_middleware(platform.RefreshAppState, platform=instance)

    routes = app.router.routes
    offset = len(routes)
    app.include_router(router)
    routes[:] = routes[offset:] + routes[:offset]
