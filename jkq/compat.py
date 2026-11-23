"""经开区 v1 路径和错误信封，复用 core 的会话与请求处理。"""

import json
from http.client import responses
from urllib.parse import urlsplit, urlunsplit

from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.routing import Match, get_route_path

from haiknow_core.error_codes import public_error_code

ALIASES = {
    "/api/v1/auth": "/api/auth",
    "/api/v1/admin": "/api/admin",
    "/api/v1/kb": "/api/v1/knowledge",
}
ERROR_ALIASES = {
    "INVALID_CREDENTIALS": "BAD_CREDENTIALS",
    "UNAUTHORIZED": "UNAUTHENTICATED",
}
HTTP_ERRORS = {
    401: ("UNAUTHENTICATED", "请先登录"),
    403: ("FORBIDDEN", "没有执行此操作的权限"),
    404: ("NOT_FOUND", "资源不存在"),
    405: ("METHOD_NOT_ALLOWED", "此资源不支持该操作"),
    422: ("INVALID_REQUEST", "请求字段缺失或类型不正确"),
    500: ("INTERNAL_ERROR", "平台处理失败，请联系管理员"),
}


def error_content(status: int, payload: dict) -> dict:
    fallback = "INTERNAL_ERROR" if status >= 500 else "INVALID_REQUEST"
    default_code, default_message = HTTP_ERRORS.get(status, (fallback, "请求处理失败"))
    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        raw_code = str(error.get("code") or default_code)
        legacy_code = raw_code.upper()
        if legacy_code == "ERROR":
            code = default_code
        else:
            code = ERROR_ALIASES.get(legacy_code) or public_error_code(raw_code)
        message = error.get("message") or default_message
        details = {
            key: value for key, value in error.items()
            if key not in {"code", "message", "details", "retryable"}
        }
        if isinstance(error.get("details"), dict):
            details.update(error["details"])
        if error.get("retryable") is True:
            details["retryable"] = True
    else:
        code = default_code
        detail = payload.get("detail")
        message = detail if isinstance(detail, str) else default_message
        details = {key: value for key, value in payload.items() if key != "detail"}

    if "action" in details and code == "FORBIDDEN":
        details.setdefault("need", details.pop("action"))
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app) -> None:
    previous_http = app.exception_handlers[HTTPException]

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if not get_route_path(request.scope).startswith("/api/v1/"):
            return await previous_http(request, exc)
        if exc.status_code < 400:
            return await http_exception_handler(request, exc)

        # core 以 DataError 重新推导 HTTP 状态。这里用原状态和公开的客户端提示。
        message = exc.detail
        if exc.status_code >= 500 or message == responses.get(exc.status_code):
            message = None
        return JSONResponse(error_content(exc.status_code, {"detail": message}),
                            status_code=exc.status_code, headers=exc.headers)

    # Starlette 的 500 处理器位于用户 middleware 外层。
    previous = app.exception_handlers[Exception]

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        response = await previous(request, exc)
        if get_route_path(request.scope).startswith("/api/v1/"):
            return JSONResponse(error_content(500, {}), status_code=500)
        return response


class Compatibility:
    def __init__(self, app, router):
        self.app = app
        self.router = router

    def _match(self, scope):
        match = Match.NONE
        for route in self.router.routes:
            candidate, _ = route.matches(scope)
            if candidate is Match.FULL:
                return candidate
            if candidate is Match.PARTIAL:
                match = candidate
        return match

    def _prefer_alias(self, original, rewritten):
        native = self._match(original)
        if native is Match.FULL:
            return False
        if self._match(rewritten) is Match.FULL:
            return True
        if native is Match.PARTIAL:
            return False

        if self.router.redirect_slashes:
            path = original["path"]
            slash_path = path.rstrip("/") if path.endswith("/") else path + "/"
            if self._match({**original, "path": slash_path}) is not Match.NONE:
                return False
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not get_route_path(scope).startswith("/api/v1/"):
            await self.app(scope, receive, send)
            return

        original = scope
        path = get_route_path(scope)
        alias = next(((source, target) for source, target in ALIASES.items()
                      if path.startswith(source + "/")), None)
        if alias:
            source, target = alias
            prefix = scope["path"][:-len(path)]
            rewritten = {**scope, "path": prefix + target + path[len(source):]}
            rewritten.pop("raw_path", None)
            if self._prefer_alias(original, rewritten):
                scope = rewritten

        start = None
        body = bytearray()

        async def send_compat(message):
            nonlocal start
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if scope is not original and message["status"] in (307, 308) and "location" in headers:
                    location = urlsplit(headers["location"])
                    if location.path.startswith(prefix + target + "/"):
                        alias_path = prefix + source + location.path[len(prefix + target):]
                        headers["location"] = urlunsplit(location._replace(path=alias_path))
                if message["status"] >= 400 and scope["method"] != "HEAD":
                    start = message
                    return
            elif message["type"] == "http.response.body" and start is not None:
                body.extend(message.get("body", b""))
                if message.get("more_body"):
                    return
                try:
                    payload = json.loads(body)
                except ValueError:
                    payload = {}
                response = JSONResponse(error_content(start["status"], payload if isinstance(payload, dict) else {}))
                headers = MutableHeaders(scope=start)
                headers["content-type"] = response.headers["content-type"]
                headers["content-length"] = response.headers["content-length"]
                await send(start)
                message = {"type": "http.response.body", "body": response.body}
            await send(message)

        await self.app(scope, receive, send_compat)
