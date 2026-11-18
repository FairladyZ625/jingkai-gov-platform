"""经开区应用目录及界面、对话共用的工具调用入口。"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.routing import Match

from haiknow_core.manifest_ext import endpoint_parts, safe_segment, validate_extensions
from haiknow_core.stability import AppIsolation, AppUnavailable
from haiknow_sdk import DataError, User

if TYPE_CHECKING:
    from haiknow_core.main import AppEntry, Platform


class ReviewSink(Protocol):
    def create_tool_review(self, app: str, tool: str, args: dict[str, Any], requester: User) -> str:
        """持久化一条 pending Review，返回其 ID。"""
        ...

    def get_review(self, id: str) -> dict[str, Any] | None:
        """按 ID 读回 Review，包括当前状态。"""
        ...


class _BridgeError(DataError):
    def __init__(self, status: int, code: str, message: str, **details: Any):
        super().__init__(code, message, details=details)
        self.status = status


class _CallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    args: dict[str, Any]


_HTTP_ERRORS = {
    401: ("UNAUTHENTICATED", "请先登录"),
    403: ("FORBIDDEN", "没有执行此操作的权限"),
    404: ("NOT_FOUND", "应用工具的目标资源不存在"),
}
_PUBLIC_FIELDS = (
    "contract", "sdk", "id", "name", "summary", "sector", "kind", "owner", "status", "version",
    "scenes", "starters", "chatCards", "dataClass", "routes",
)
_PUBLIC_LIST_FIELDS = {
    "tools": ("name", "description", "write", "input", "endpoint"),
    "accepts": ("kind", "ext", "match"),
    "intents": ("id", "action", "plan"),
}


class _BridgeIsolation(AppIsolation):
    def __init__(self, app, platform, routes):
        super().__init__(app, platform)
        self.routes = routes

    async def __call__(self, scope, receive, send):
        # 桥的路由依赖先验证登录，随后桥自身按权限、可用性的顺序处理。
        if scope["type"] == "http" and scope["path"].startswith("/api/v1/apps/"):
            path = scope["path"].rstrip("/")
            canonical = dict(scope, path=path)
            if any(route.matches(canonical)[0] is Match.FULL for route in self.routes):
                if "raw_path" in canonical:
                    canonical["raw_path"] = canonical["raw_path"].rstrip(b"/")
                return await self.app(canonical, receive, send)
        return await super().__call__(scope, receive, send)


def _require_available(entry: AppEntry) -> None:
    if reason := entry.unavailable_reason():
        raise AppUnavailable(entry.manifest["id"], reason, entry.circuit.retry_after())


def _public_manifest(entry: AppEntry, actions: frozenset[str], is_admin: bool) -> dict:
    manifest = entry.manifest
    result = {key: manifest[key] for key in _PUBLIC_FIELDS if key in manifest}
    for key, fields in _PUBLIC_LIST_FIELDS.items():
        if key in manifest:
            result[key] = [{field: item[field] for field in fields} for item in manifest[key]]
    if "deepLink" in manifest:
        result["deepLink"] = {"params": manifest["deepLink"]["params"]}
    reason = entry.unavailable_reason()
    result.update(
        actions=sorted(actions), url=manifest.get("url") if is_admin else None,
        available=not bool(reason), hasWeb=entry.has_web,
        hasPrototype=(entry.dir / "prototype" / "index.html").is_file(),
    )
    if is_admin and reason:
        result["error"] = reason
    return result


def _preflight_method(app: FastAPI, method: str, path: str) -> str:
    """同一业务路由显式提供只读检查方法，沿用其全部依赖、入参和业务授权。"""
    check = f"CHECK-{method}"
    for route in app.routes:
        expand = getattr(route, "effective_route_contexts", None)
        for candidate in expand() if expand else (route,):
            pattern = getattr(candidate, "path_regex", None)
            if not pattern or not pattern.match(path):
                continue
            methods = getattr(candidate, "methods", None)
            if methods and methods.isdisjoint({method, check}):
                continue
            if methods and {method, check} <= methods:
                return check
            raise DataError("internal_error", "工具业务路由尚未接入共用预检")
    raise DataError("internal_error", "找不到工具业务路由")


def _tool_target(tool: dict, app_id: str, args: dict) -> tuple[str, str, dict]:
    method, segments = endpoint_parts(tool["endpoint"], app_id)
    remaining = args.copy()
    for index, segment in enumerate(segments):
        if segment.startswith("{"):
            key = segment[1:-1]
            value = args.get(key)
            if type(value) is int:
                value = str(value)
            if not isinstance(value, str) or not safe_segment(value):
                raise DataError("invalid_request", f"工具路径参数 {key} 缺失或格式不正确")
            remaining.pop(key, None)
            segments[index] = value
    return method, f"/api/apps/{app_id}/" + "/".join(segments), remaining


async def _dispatch(request: Request, method: str, path: str, args: dict) -> Any:
    """进程内调用原有应用路由，沿用请求的登录态、SDK 权限和应用错误处理。"""
    headers = [(name, value) for name, value in request.headers.raw if name in {b"cookie", b"authorization"}]
    transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://jkq.internal", headers=headers) as client:
        options = {"params": args} if method == "GET" else {"json": args}
        response = await client.request(method, path, **options)
    try:
        result = response.json() if response.content else None
    except ValueError:
        raise DataError("internal_error", "应用工具未返回 JSON 结果") from None
    if method.startswith("CHECK-") and response.is_success and response.status_code != 204:
        raise DataError("internal_error", "工具业务预检未确认授权")
    if response.is_success:
        return result
    if response.status_code in _HTTP_ERRORS:
        code, message = _HTTP_ERRORS[response.status_code]
        raise _BridgeError(response.status_code, code, message)
    error = result.get("error") if isinstance(result, dict) else None
    if isinstance(error, dict) and isinstance(error.get("code"), str) and isinstance(error.get("message"), str):
        forwarded = DataError(error["code"], error["message"])
        forwarded.status, forwarded.error = response.status_code, error
        raise forwarded
    if response.status_code == 422:
        raise DataError("invalid_request", "工具参数缺失或类型不正确")
    raise DataError("internal_error", "应用工具执行失败")


class AppsBridge:
    def __init__(
        self,
        platform: Platform,
        current_user: Callable[[Request], User],
        review_sink: ReviewSink | None,
        list_skills: Callable[[User], list[dict]] | None,
    ):
        self.platform = platform
        self.current_user = current_user
        self.review_sink = review_sink
        self.list_skills = list_skills

    def user(self, request: Request) -> User:
        try:
            return self.current_user(request)
        except HTTPException as error:
            if error.status_code == 401:
                raise _BridgeError(401, "UNAUTHENTICATED", "请先登录") from error
            raise

    def _entry(self, app_id: str) -> AppEntry:
        entry = self.platform.apps.get(app_id)
        if entry is None or validate_extensions(entry.manifest):
            raise _BridgeError(404, "NOT_FOUND", "应用不存在")
        return entry

    def _visible(self, user: User) -> Iterator[tuple[AppEntry, frozenset[str]]]:
        for app_id, entry in self.platform.apps.copy().items():
            actions = self.platform.rbac.actions(user, app_id)
            if "view" in actions and not validate_extensions(entry.manifest):
                yield entry, actions

    def apps(self, user: User) -> dict:
        is_admin = "admin" in self.platform.rbac.actions(user, "*")
        return {
            "items": [_public_manifest(entry, actions, is_admin) for entry, actions in self._visible(user)],
            "skills": self.list_skills(user) if self.list_skills is not None else [],
        }

    def app(self, user: User, app_id: str) -> dict:
        entry = self._entry(app_id)
        actions = self.platform.rbac.actions(user, app_id)
        if "view" not in actions:
            self.platform.store.audit(app_id, user.id, "app.view", {"need": "view", "outcome": "FORBIDDEN"})
            raise _BridgeError(403, "FORBIDDEN", "没有查看此应用的权限", app=app_id, need="view")
        _require_available(entry)
        return _public_manifest(entry, actions, "admin" in self.platform.rbac.actions(user, "*"))

    def tools(self, user: User) -> dict:
        return {
            "items": [
                {"name": tool["name"], "app": entry.manifest["id"], "write": tool["write"]}
                for entry, _ in self._visible(user) if not entry.unavailable_reason()
                for tool in entry.manifest.get("tools", [])
            ]
        }

    async def call_from_chat(self, request: Request, app_id: str, tool: str, args: dict) -> dict:
        """供对话编排在已登录请求内调用。"""
        user = await run_in_threadpool(self.user, request)
        return await self._call(request, user, app_id, tool, args, via="chat")

    async def _call(self, request: Request, user: User, app_id: str, name: str, args: dict, *, via: str) -> dict:
        name = name if "." in name else f"{app_id}.{name}"
        entry = self._entry(app_id)
        detail = {"tool": name, "via": via, "need": "view", "outcome": "internal_error"}
        try:
            actions = await run_in_threadpool(self.platform.rbac.actions, user, app_id)
            if "view" not in actions:
                raise _BridgeError(403, "FORBIDDEN", "没有查看此应用的权限", app=app_id, need="view")
            tool = next((item for item in entry.manifest.get("tools", []) if item["name"] == name), None)
            if tool is None:
                raise _BridgeError(404, "TOOL_NOT_FOUND", "工具不存在")
            if tool["write"]:
                detail["need"] = "operate"
                if "operate" not in actions:
                    raise _BridgeError(403, "FORBIDDEN", "没有执行此工具的权限", app=app_id, need="operate")
            _require_available(entry)
            method, path, body = _tool_target(tool, app_id, args)
            if via == "chat" and tool["write"]:
                if self.review_sink is None:
                    raise DataError("internal_error", "工具审签服务尚未接入")
                check = _preflight_method(request.app, method, path)
                await _dispatch(request, check, path, body)
                review_id = await run_in_threadpool(self.review_sink.create_tool_review, app_id, name, args, user)
                result = {"status": "pending", "reviewId": review_id, "message": "待确认"}
                detail.update(outcome="pending", reviewId=review_id)
            else:
                result = await _dispatch(request, method, path, body)
                detail["outcome"] = "ok"
            return {"tool": name, "result": result}
        except AppUnavailable:
            detail["outcome"] = "app_unavailable"
            raise
        except DataError as error:
            http_error = _HTTP_ERRORS.get(error.status)
            if http_error and error.code == http_error[0].lower():
                error = _BridgeError(error.status, *http_error)
            detail["outcome"] = error.code
            if error.status == 403:
                error.error.setdefault("details", {"app": app_id, "need": detail["need"]})
            raise error
        finally:
            await run_in_threadpool(self.platform.store.audit, app_id, user.id, "tool.call", detail)


def install(
    app: FastAPI,
    current_user: Callable[[Request], User],
    *,
    review_sink: ReviewSink | None = None,
    list_skills: Callable[[User], list[dict]] | None = None,
) -> AppsBridge:
    """启动前注册。业务写工具的预检负责同一请求人的入参和资源授权，全程只读。"""
    if app.middleware_stack is not None:
        raise RuntimeError("应用工具桥须在实例启动前注册")
    bridge = AppsBridge(app.state.platform, current_user, review_sink, list_skills)
    app.state.apps_bridge = bridge
    router = APIRouter(prefix="/api/v1")

    @router.get("/apps")
    def apps(user: User = Depends(bridge.user)):
        return bridge.apps(user)

    @router.get("/apps/{app_id}")
    def app_detail(app_id: str, user: User = Depends(bridge.user)):
        return bridge.app(user, app_id)

    @router.get("/tools")
    def tools(user: User = Depends(bridge.user)):
        return bridge.tools(user)

    @router.post("/apps/{app_id}/tools/{tool}")
    async def call_tool(request: Request, app_id: str, tool: str, body: _CallBody, user: User = Depends(bridge.user)):
        return await bridge._call(request, user, app_id, tool, body.args, via="ui")

    app.include_router(router)
    for index, middleware in enumerate(app.user_middleware):
        if middleware.cls is AppIsolation:
            app.user_middleware[index] = Middleware(
                _BridgeIsolation, *middleware.args, **middleware.kwargs, routes=tuple(router.routes),
            )
    return bridge
