"""实例入口：复用卫华工厂并由经开区决定路由及前端入口。"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match, Mount, get_route_path

from .compat import Compatibility, install_error_handlers
from .projects import load_project_seed, restore_empty_projects
from .settings import REPO_ROOT, core_environment, required_environment, web_directory


class WebMount(Mount):
    """保留 API 的 404 与 405，兼容原型在 /api/ 下的客户端脚本。"""

    def matches(self, scope):
        path = get_route_path(scope)
        script = path.removeprefix("/api/")
        frontend_script = "/" not in script and script.endswith(".js")
        if path == "/api" or (path.startswith("/api/") and not frontend_script):
            return Match.NONE, {}
        return super().matches(scope)


def create_app() -> FastAPI:
    required_environment()
    root = Path(os.environ.get("HAIKNOW_ROOT") or REPO_ROOT).resolve()
    web_dir = web_directory(root)
    with core_environment(root):
        seed = load_project_seed(Path(os.environ["HAIKNOW_CONFIG_DIR"]))
        from haiknow_core.main import create_app as create_core_app

        from .routers import register_routes

        app = create_core_app(root)
        restore_empty_projects(app.state.platform.store, seed)
        register_routes(app)

    app.title = "北京经开区共享智能体工作站"
    install_error_handlers(app)
    app.add_middleware(Compatibility, router=app.router)

    if not (web_dir / "favicon.ico").is_file():
        @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
        async def empty_favicon():
            return Response(status_code=204)

    # core 如自带外壳，保留专用挂载，首页由经开区托管。
    routes = app.router.routes
    routes[:] = [route for route in routes if getattr(route, "path", None) != "/"]
    routes.append(WebMount("/", app=StaticFiles(directory=web_dir, html=True), name="jkq-web"))
    return app
