"""平台入口：登录、应用注册与挂载、权限、留痕、外壳静态资源。

启动命令见 core/README.md。
"""
from __future__ import annotations

import importlib.util
import logging
import os
import secrets
import sys
import types
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool

import haiknow_sdk
from haiknow_sdk import AppContext, ModelError, PermissionDenied, User

from . import manifest as mf
from . import admin_apps
from . import scenes
from .model import ModelGateway
from .data import DataService
from .projects import Projects
from .aihub.api import install as install_aihub
from .api_v1 import install as install_v1
from .jobs import install as install_jobs
from haiknow_sdk.resources import Records, DataFiles, Reviews, Artifacts, Notifications
from .rbac import Rbac
from .identity import Directory
from .auth import PlatformSessions, install as install_auth
from .admin_identity import install as install_admin_identity
from .store import AppFiles, AppKV, Store
from .knowledge.api import install as install_knowledge
from .schedules import install as install_schedules
from .stability import AppIsolation, AppUnavailable, Circuit, unavailable_response

log = logging.getLogger("haiknow")
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class AppEntry:
    dir: Path
    manifest: dict
    status: str = "ok"  # ok | unavailable
    error: str = ""
    has_api: bool = False
    has_web: bool = False
    enabled: bool = True
    circuit: Circuit = field(default_factory=Circuit)

    def unavailable_reason(self) -> str:
        if self.status != 'ok':
            return self.error
        if not self.enabled:
            return '管理员已停用此应用'
        if self.circuit.retry_after():
            return '应用连续失败，正在冷却，请稍后重试'
        return ''


@dataclass
class Platform:
    root: Path
    apps_dir: Path
    store: Store
    model: ModelGateway
    rbac: Rbac
    directory: Directory
    scenes: scenes.SceneTable = field(default_factory=scenes.SceneTable)
    data: DataService | None = None
    apps: dict[str, AppEntry] = field(default_factory=dict)
    broken: list[dict] = field(default_factory=list)
    config_dir: Path | None = None

    # SDK 运行时：把请求解析成应用上下文
    def resolve(self, request: Request) -> AppContext:
        user = current_user(request)
        parts = request.url.path.split("/")
        # /api/apps/<id>/...
        if len(parts) < 4 or parts[1] != "api" or parts[2] != "apps":
            raise HTTPException(400, "不在应用路由下")
        app_id = parts[3]
        if app_id not in self.apps:
            raise HTTPException(404, f"应用 {app_id} 不存在")
        acts = self.rbac.actions(user, app_id)
        if "view" not in acts:
            raise PermissionDenied(app_id, "view")
        files = AppFiles(self.store.data_dir, app_id)
        return AppContext(
            app_id=app_id,
            user=user,
            actions=acts,
            files=files,
            kv=AppKV(self.store, app_id),
            model=self.model.for_app(app_id, files, user),
            records=Records(self.data, user, app_id),
            reviews=Reviews(self.data, user, app_id),
            artifacts=Artifacts(self.data, user),
            notifications=Notifications(self.data, user, app_id),
            data_files=DataFiles(self.data, user, app_id),
            _audit=lambda action, detail: self.store.audit(app_id, user.id, action, detail),
        )


def current_user(request: Request) -> User:
    p: Platform = request.app.state.platform
    uid = request.session.get("uid")
    # 会话携带签发时的代数；登出、改密、重置口令或强制下线把它抬高，旧 cookie 立即失效。
    # 上线前签发的会话没有 gen，按 0 与库中默认值相等，不强制重登。
    user = p.directory.session_user(uid, request.session.get("gen", 0)) if uid else None
    if user is None:
        raise HTTPException(401, "未登录")
    return user


def _load_router(entry: AppEntry) -> APIRouter | None:
    """按应用逐个加载后端；失败只影响这个应用。"""
    router_py = entry.dir / "api" / "router.py"
    if not router_py.is_file():
        return None
    pkg_name = "haiknow_apps." + entry.manifest["id"].replace("-", "_")
    sys.modules.setdefault("haiknow_apps", types.ModuleType("haiknow_apps")).__path__ = []
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(router_py.parent)]
    sys.modules[pkg_name] = pkg
    spec = importlib.util.spec_from_file_location(f"{pkg_name}.router", router_py)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    router = getattr(mod, "router", None)
    if not isinstance(router, APIRouter):
        raise TypeError("api/router.py 必须导出 router = APIRouter()")
    return router


READY_STATUSES = ("usable", "demo-ready")


def _coverage_state(apps: list[AppEntry]) -> str:
    """场景状态：有可用应用=usable，只有原型应用=prototype，没有应用=todo。"""
    if not apps:
        return "todo"
    return "usable" if any(a.manifest["status"] in READY_STATUSES for a in apps) else "prototype"


def _rate(covered: int, total: int) -> float:
    return round(covered / total, 4) if total else 0


class AppControlBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool


def mount_app(app: FastAPI, plat: Platform, d: Path, m: dict) -> AppEntry:
    """登记并挂载一个已通过清单校验的应用；加载失败只标记该应用。启动与造应用热加载共用。"""
    e = AppEntry(dir=d, manifest=m, has_web=(d / "web" / "index.js").is_file())
    admin_apps.register(plat, d, m)
    e.enabled = plat.store.app_enabled(m["id"])
    try:
        e.error = mf.sdk_error(m)
        if e.error:
            e.status = "unavailable"
        r = _load_router(e) if not e.error else None
        if r is not None:
            app.include_router(r, prefix=f"/api/apps/{m['id']}", tags=[m["id"]])
            e.has_api = True
    except Exception as ex:  # noqa: BLE001 —— 隔离：任何加载错误都只标记该应用
        e.status, e.error = "unavailable", f"后端加载失败（{type(ex).__name__}），请联系应用负责人"
        log.exception("应用 %s 后端加载失败", m["id"])
    plat.apps[m["id"]] = e
    if (d / "web").is_dir():
        app.mount(f"/apps/{m['id']}/web", admin_apps.VersionedStaticFiles(plat, m["id"], d / "web"), name=f"web-{m['id']}")
    if (d / "prototype").is_dir():
        app.mount(
            f"/apps/{m['id']}/prototype",
            StaticFiles(directory=d / "prototype", html=True),
            name=f"proto-{m['id']}",
        )
    return e


def create_app(root: Path | None = None) -> FastAPI:
    root = Path(root or os.environ.get("HAIKNOW_ROOT") or REPO_ROOT)
    apps_dir = Path(os.environ.get("HAIKNOW_APPS_DIR") or root / "apps")
    data_dir = Path(os.environ.get("HAIKNOW_DATA_DIR") or root / "data")
    config_dir = Path(os.environ.get("HAIKNOW_CONFIG_DIR") or root / "config")

    found = mf.discover(apps_dir)
    good = [(d, m) for d, m, errs in found if m is not None and not errs]
    store = Store(data_dir)
    directory = Directory(store, demo_login=os.environ.get('HAIKNOW_DEMO_LOGIN') == '1')
    directory.seed(config_dir, [m for _, m in good], demo=directory.demo_login)
    try:
        scene_table = scenes.load(config_dir)
    except scenes.SceneTableError as exc:
        # 场景表是展示数据：坏了只影响覆盖页并显式报错，不拖垮平台启动。
        log.error("场景表不可用：%s；需求覆盖页按空表展示", exc)
        scene_table = scenes.SceneTable(error=str(exc))
    plat = Platform(
        root=root,
        apps_dir=apps_dir,
        store=store,
        model=ModelGateway(),
        rbac=Rbac(directory),
        directory=directory,
        scenes=scene_table,
        config_dir=config_dir,
    )
    for d, m, errs in found:
        if m is None or errs:
            plat.broken.append({"dir": d.name, "error": "；".join(errs)})
            log.warning("应用 %s 清单无效：%s", d.name, errs)

    app = FastAPI(title="HAiKnow 小应用接入平台", version="0.1.0")
    app.state.platform = plat
    secret = os.environ.get("HAIKNOW_SECRET") or secrets.token_hex(16)
    app.add_middleware(AppIsolation, platform=plat)
    app.add_middleware(PlatformSessions, directory=directory, secret_key=secret)
    haiknow_sdk._install_runtime(plat)
    # 灰度/草稿应用只对受众可见：授权判断集中在 Rbac.actions，所有接口一视同仁。
    plat.rbac.audience = lambda user, app_id: app_id not in plat.apps or admin_apps.visible(plat, app_id, user, False)
    install_aihub(app, plat)

    @app.exception_handler(PermissionDenied)
    async def _denied(_: Request, e: PermissionDenied):
        return JSONResponse({"detail": str(e), "app": e.app_id, "action": e.action}, status_code=403)

    @app.exception_handler(ModelError)
    async def _model_error(_: Request, e: ModelError):
        status = {"not_configured": 503, "timeout": 504, "bad_input": 400, "outbound_denied": 403}.get(e.kind, 502)
        return JSONResponse({"detail": str(e), "kind": e.kind}, status_code=status)

    @app.exception_handler(AppUnavailable)
    async def _unavailable(_: Request, e: AppUnavailable):
        return unavailable_response(e)

    # 只挂载 apps/ 中通过清单校验的应用。
    for d, m in good:
        mount_app(app, plat, d, m)

    plat.data = DataService(plat.store, plat.rbac, Projects(directory), plat.apps)
    install_v1(app, plat, current_user)
    install_auth(app, plat, current_user)
    install_admin_identity(app, plat, current_user)
    install_knowledge(app, plat, current_user)
    admin_apps.install(app, plat, current_user)
    install_jobs(app, plat, current_user)
    install_schedules(app, plat, current_user)

    if not plat.scenes.error:
        unknown = scenes.unknown_codes(
            plat.scenes, [s for e in plat.apps.values() for s in e.manifest.get("scenes", [])]
        )
        if unknown:
            log.warning(
                "场景编号 %s 不在 %s 中；需求覆盖页不展示这些编号，请核对 app.json 的 scenes 或补场景表",
                "、".join(unknown),
                config_dir / scenes.FILE_NAME,
            )

    # 平台接口
    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "apps": len(plat.apps),
            "unavailable": [k for k, v in plat.apps.items() if v.unavailable_reason()],
            "broken": len(plat.broken),
            "model": "configured" if plat.model.configured else "mock",
        }

    def _app_view(e: AppEntry, acts: frozenset[str], admin: bool) -> dict:
        m = e.manifest
        v = {
            "id": m["id"],
            "name": m["name"],
            "sector": m["sector"],
            "kind": m["kind"],
            "status": m["status"],
            "scenes": m.get("scenes", []),
            "summary": m.get("summary", ""),
            "owner": m["owner"],
            "url": m.get("url") if admin else None,
            "available": not bool(e.unavailable_reason()),
            "hasWeb": e.has_web,
            "hasPrototype": (e.dir / "prototype" / "index.html").is_file(),
            "actions": sorted(acts),
        }
        if admin and e.unavailable_reason():
            v["error"] = e.unavailable_reason()
        return v

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        is_admin = "admin" in plat.rbac.actions(user, "*")
        return {
            "id": user.id,
            "name": user.name,
            "roles": [plat.rbac.role_names.get(r, r) for r in user.roles],
            "isAdmin": is_admin,
            **plat.directory.profile(user),
        }

    @app.get("/api/apps")
    def list_apps(user: User = Depends(current_user)):
        is_admin = "admin" in plat.rbac.actions(user, "*")
        out = []
        for e in plat.apps.values():
            acts = plat.rbac.actions(user, e.manifest["id"])
            if "view" in acts and admin_apps.visible(plat, e.manifest["id"], user, is_admin):
                out.append(_app_view(e, acts, is_admin))
        return {"apps": out, "broken": plat.broken if is_admin else []}

    @app.put('/api/v1/admin/apps/{app_id}')
    def app_control(app_id: str, body: AppControlBody, user: User = Depends(current_user)):
        if 'admin' not in plat.rbac.actions(user, '*'):
            raise PermissionDenied('*', 'admin')
        if app_id not in plat.apps:
            raise HTTPException(404, '应用不存在')
        # 复用数据库锁串行化持久状态与内存状态，避免并发开关更新顺序相反。
        with plat.store._lock:
            admin_apps.update(plat, app_id, user, state="live" if body.enabled else "disabled", legacy=True)
            return {'id': app_id, 'enabled': body.enabled,
                    'available': not bool(plat.apps[app_id].unavailable_reason())}

    @app.get("/api/coverage")
    def coverage(_: User = Depends(current_user)):
        by_scene: dict[str, list[str]] = {}
        by_scene_apps: dict[str, list[AppEntry]] = {}
        sectors: Counter[str] = Counter()
        for e in plat.apps.values():
            sectors[e.manifest["sector"]] += 1
            for s in e.manifest.get("scenes", []):
                by_scene.setdefault(s, []).append(e.manifest["name"])
                by_scene_apps.setdefault(s, []).append(e)
        groups = []
        covered = first_covered = 0
        for group in plat.scenes.groups:
            rows = []
            group_covered = 0
            for scene in group.scenes:
                apps = by_scene_apps.get(scene.id, [])
                if apps:
                    group_covered += 1
                    covered += 1
                    first_covered += int(scene.first)
                rows.append({
                    "id": scene.id,
                    "name": scene.name,
                    "first": scene.first,
                    "state": _coverage_state(apps),
                    "apps": [
                        {"id": a.manifest["id"], "name": a.manifest["name"], "status": a.manifest["status"]}
                        for a in apps
                    ],
                })
            groups.append({
                "id": group.id,
                "name": group.name,
                "covered": group_covered,
                "total": len(group.scenes),
                "scenes": rows,
            })
        total = sum(len(g.scenes) for g in plat.scenes.groups)
        first_total = sum(1 for scene in plat.scenes if scene.first)
        return {
            "scenes": by_scene,
            "sectors": dict(sectors),
            "apps": len(plat.apps),
            "groups": groups,
            "coverage": {"covered": covered, "total": total, "rate": _rate(covered, total)},
            "firstBatch": {"covered": first_covered, "total": first_total, "rate": _rate(first_covered, first_total)},
            "unknown": scenes.unknown_codes(plat.scenes, set(by_scene)),
            "tableError": plat.scenes.error,
        }

    @app.get("/api/audit")
    def audit(app_id: str | None = None, user: User = Depends(current_user)):
        if "admin" not in plat.rbac.actions(user, app_id or "*"):
            raise PermissionDenied(app_id or "*", "admin")
        return {"items": plat.store.audit_list(app_id)}

    @app.get("/api/model/usage")
    def model_usage(user: User = Depends(current_user)):
        if "admin" not in plat.rbac.actions(user, "*"):
            raise PermissionDenied("*", "admin")
        usage = plat.model.usage()
        return {
            "mode": "configured" if plat.model.configured else "mock",
            "calls": {app_id: counts["total"] for app_id, counts in usage.items()},
            "usage": usage,
            "scope": "process",
        }

    # 外壳
    web_dir = root / "core" / "web"
    sdk_js = root / "core" / "sdk" / "js"
    if sdk_js.is_dir():
        app.mount("/sdk", StaticFiles(directory=sdk_js), name="sdk")
    if web_dir.is_dir():
        app.mount("/web", StaticFiles(directory=web_dir), name="web")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(web_dir / "index.html")

    return app


app = create_app() if os.environ.get("HAIKNOW_NO_AUTOAPP") != "1" else None
