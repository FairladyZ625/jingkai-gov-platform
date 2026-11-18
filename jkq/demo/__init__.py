"""经开区演示模式接线，宿主快照恢复独立于 app 生命周期。"""

import json
import os
import secrets
from contextvars import ContextVar
from copy import copy
from pathlib import Path
from typing import Literal

import httpx
import yaml
from fastapi import Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from haiknow_core.aihub.errors import AIError
from jkq.auth import AuthError, require_action
from jkq.settings import web_directory


class ResetReceipt(BaseModel):
    ok: Literal[True] = True
    status: Literal["accepted"] = "accepted"


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_quotes: dict[str, str] = {}
    rule_intent_first: StrictBool = True
    preset_on_failure: StrictBool = True
    mock_modules: frozenset[Literal["kb", "policy", "enterprise", "meeting", "document", "skills", "computer"]] = frozenset()


def request_reset(socket_path):
    if not socket_path:
        raise AuthError(503, "RESET_UNAVAILABLE", "演示宿主尚未接入重置服务")
    try:
        transport = httpx.HTTPTransport(uds=socket_path)
        with httpx.Client(transport=transport, timeout=5) as client:
            response = client.post("http://localhost/reset")
        receipt = response.json() if response.status_code == 202 else None
        if isinstance(receipt, dict) and receipt.get("ok") is True:
            return {"ok": True}
    except (ValueError, httpx.HTTPError):
        pass
    raise AuthError(503, "RESET_UNAVAILABLE", "未能确认宿主受理重置请求")


def match_intent(platform, user, messages):
    last = messages[-1]
    if last.get("role") != "user" or not isinstance(last.get("content"), str):
        return None
    text = last["content"].strip()
    for app_id, entry in platform.apps.copy().items():
        if entry.unavailable_reason() or "view" not in platform.rbac.actions(user, app_id):
            continue
        for intent in entry.manifest.get("intents", []):
            if text in intent.get("examples", []) and intent.get("plan"):
                return "建议步骤：" + " → ".join(intent["plan"])
    return None


def kb_preset(messages, quotes):
    """只返回当前账号检索结果中与演示预置原句完全相符的摘录。"""
    try:
        query = json.loads(messages[-1]["content"])
        quote = quotes.get(query["question"])
        for passage in query["passages"]:
            if quote and quote in passage["sentences"]:
                return json.dumps([{"passage": passage["passage"], "quote": quote}], ensure_ascii=False)
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return "[]"


# 同一个请求的模型调用在线程池中执行，独立标记随请求上下文传递。
_kb_source = ContextVar("demo_kb_source", default=None)


class KnowledgeSource:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/kb/ask":
            return await self.app(scope, receive, send)
        marker = {}
        token = _kb_source.set(marker)
        start = None
        body = bytearray()

        async def label(message):
            nonlocal start
            if message["type"] == "http.response.start" and marker and message["status"] == 200:
                start = message
            elif start is None:
                await send(message)
            else:
                body.extend(message["body"])
                if not message.get("more_body"):
                    answer = json.loads(body)
                    answer["source"] = "preset"
                    answer["routeNote"] = "预置结果"
                    for field in ("answer", "message"):
                        if answer.get(field):
                            answer[field] = "【预置结果】" + answer[field]
                    output = JSONResponse(answer)
                    headers = [(k, v) for k, v in start["headers"] if k != b"content-length"]
                    await send({**start, "headers": headers + [(b"content-length", str(len(output.body)).encode())]})
                    await send({**message, "body": output.body})

        try:
            await self.app(scope, receive, label)
        finally:
            _kb_source.reset(token)


def bind_demo_models(service, platform, options):
    normal_call = service.call
    # 沿用配置里的模拟 provider、启用状态、密级校验、配额与审计。
    mock_service = copy(service)
    mock_service.providers = {key: value if value and value["kind"] == "mock" else None
                              for key, value in service.providers.items()}

    def call(user, payload, *, model=None, app_id="platform", timeout=50):
        args = dict(model=model, app_id=app_id, timeout=timeout)
        if payload["classification"] == "confidential" or model not in (None, "auto"):
            return normal_call(user, payload, **args)
        plan = None
        if options.rule_intent_first and app_id == "platform" and user and payload.get("messages"):
            plan = match_intent(platform, user, payload["messages"])
        if plan or app_id in options.mock_modules:
            result, note = mock_service.call(user, payload, **args)
        else:
            try:
                result, note = normal_call(user, payload, **args)
            except AIError as exc:
                if not options.preset_on_failure or exc.kind not in {"provider_error", "timeout", "not_configured"}:
                    raise
                result, note = mock_service.call(user, payload, **args)
        if result["result"]["mock"] and (options.preset_on_failure or plan or app_id in options.mock_modules):
            content = plan or "模型当前使用演示数据，请按应用内的示例步骤继续办理。"
            if app_id == "kb":
                marker = _kb_source.get()
                excerpt = kb_preset(payload["messages"], options.kb_quotes)
                if marker is not None and excerpt != "[]":
                    marker["preset"] = True
                result["result"]["content"] = excerpt
            else:
                result["result"]["content"] = f"【预置结果】{content}"
            note = "规则意图优先，预置结果" if plan else "预置结果"
        return result, note

    service.call = call


def install_module_config(app, directory, modules):
    """通过 #108 的模块配置切换浏览器传输，只覆盖已启用 HTTP 的演示站。"""
    config_file = directory / "config/app.config.js"
    overrides = json.dumps(dict.fromkeys(sorted(modules), "mock"))
    overlay = (
        "\nif (window.JK_CONFIG.api.mode === 'http') {"
        f"window.JK_CONFIG.api.modules = Object.assign({{}}, window.JK_CONFIG.api.modules, {overrides});"
        "}\n"
    )

    @app.get("/config/app.config.js", include_in_schema=False)
    def module_config():
        return Response(config_file.read_text(encoding="utf-8") + overlay,
                        media_type="text/javascript", headers={"Cache-Control": "no-store"})


def install(app):
    if os.environ.get("JKQ_DEMO_MODE") != "1":
        return
    platform = app.state.platform
    path = Path(platform.config_dir) / "demo.yaml"
    options = Options.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {})
    bind_demo_models(app.state.jkq_models, platform, options)
    if options.mock_modules:
        install_module_config(app, web_directory(platform.root), options.mock_modules)
    socket_path = os.environ.get("JKQ_DEMO_RESET_SOCKET")

    app.add_middleware(KnowledgeSource)
    reset_key = os.environ.get("JKQ_DEMO_RESET_KEY", "").encode()

    @app.post("/api/v1/demo/reset", status_code=202, response_model=ResetReceipt,
              summary="请求宿主受理演示快照恢复",
              description="限演示配置、管理员会话及独立 X-JKQ-Reset-Key 请求头。202 仅表明受理。"
                          "宿主完成恢复、健康检查和快照哈希核验后才能提示已重置。",
              responses={202: {"description": "已受理，status 为 accepted"},
                         401: {"description": "UNAUTHENTICATED：尚未登录"},
                         403: {"description": "FORBIDDEN：缺少管理员或宿主重置授权"},
                         503: {"description": "RESET_UNAVAILABLE：尚未接入或未收到宿主回执"}})
    def reset(request: Request, admin=Depends(require_action("*", "admin"))):
        proof = request.headers.get("X-JKQ-Reset-Key", "").encode()
        if not reset_key or not secrets.compare_digest(proof, reset_key):
            platform.store.audit("platform", admin.id, "demo.reset.denied", {})
            raise AuthError(403, "FORBIDDEN", "缺少独立的宿主重置授权")
        request_reset(socket_path)
        platform.store.audit("platform", admin.id, "demo.reset.accepted", {})
        return ResetReceipt()
