"""实例入口：复用卫华工厂并由经开区决定路由及前端入口。"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.routing import Match, Mount, get_route_path

from .app_catalogs import install as install_app_catalogs
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


def install_platform(app: FastAPI) -> None:
    """安装需要包住 core 路由或挂平台存储的模块，每个模块一行。"""
    from haiknow_core.main import current_user  # 登录依赖只在这里指定

    from . import admin, apps_bridge, demo, jobs_api, reviews_api
    from .skills.storage import Skills
    from .conversations import routes as conversations
    from .kb import ask as kb_ask
    from .operator import routes as operator
    from .orchestrator import routes as orchestrator

    app.state.conversations = conversations.install(app, app.state.platform, current_user)
    orchestrator.install(app, current_user)
    jobs_api.install(app, current_user)
    reviews_api.install(app, current_user)
    operator.install(app, current_user)
    kb_ask.install(app, app.state.platform, current_user)
    skills = Skills(app.state.platform)

    def list_skills(user):
        if "view" not in app.state.platform.rbac.actions(user, "skills"):
            return []
        return [
            skills.view(user, doc, history=False)
            for doc in skills.records.list_records(user, "skills")["items"]
            if not doc["data"]["deleted"] and skills.access(user, doc["data"])[0]
        ]

    apps_bridge.install(app, current_user, list_skills=list_skills, register_catalog=False)
    demo.install(app)
    admin.install(app)
    if "document" in app.state.platform.data.apps:
        # 公文协作：定稿锁定的存储约束，以及禁止绕过核查的通用送审入口（#38、#41）。
        from apps.document.instance import install as install_document

        install_document(app)


def create_app() -> FastAPI:
    required_environment()
    root = Path(os.environ.get("HAIKNOW_ROOT") or REPO_ROOT).resolve()
    web_dir = web_directory(root)
    with core_environment(root):
        seed = load_project_seed(Path(os.environ["HAIKNOW_CONFIG_DIR"]))
        from haiknow_core.main import create_app as create_core_app

        from .auth import install as install_auth
        from .routers import register_routes

        app = create_core_app(root)
        install_app_catalogs(app)
        restore_empty_projects(app.state.platform.store, seed)
        register_routes(app)
        install_auth(app)
        install_platform(app)

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
