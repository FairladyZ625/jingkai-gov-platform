"""经开区 §3.2 网关直连。模型路由、密级和配额沿用 #15。"""

import asyncio
import json
import re
from concurrent.futures import TimeoutError as PublishTimeout
from threading import Event
from typing import Annotated
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import Field, StrictBool, StringConstraints
from starlette.concurrency import run_in_threadpool

from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.streaming import Channel, ChatRequest
from haiknow_core.main import current_user

from . import models


class ChatBody(models.ChatBody):
    stream: StrictBool = False
    tools: list[Annotated[str, StringConstraints(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=64,
    )


router = APIRouter(prefix="/api/v1")


def install(app):
    """用扩展路由替换旧文本端点，保留模型目录和原有服务绑定。"""
    models._bind(app)
    model_routes = APIRouter(
        routes=[route for route in models.router.routes if route.endpoint is not models.chat],
        lifespan=models.router.lifespan_context,
    )
    app.include_router(model_routes)
    app.include_router(router)


def _parameter_schema(kind):
    if kind in ("string", "number", "integer", "boolean", "object", "array"):
        return {"type": kind}
    if kind.endswith("[]"):
        return {"type": "array", "items": _parameter_schema(kind[:-2])}
    return {}


def _registered_tools(platform, user, names):
    if not names:
        return [], {}
    definitions = {}
    for app_id, entry in platform.apps.items():
        declarations = entry.manifest.get("tools")
        if not isinstance(declarations, list):
            continue
        for tool in declarations:
            if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                definitions[tool["name"]] = (app_id, tool)

    tools, aliases = [], {}
    for name in dict.fromkeys(names):
        definition = definitions.get(name)
        if definition is None:
            raise AIError("tool_not_found", "请求包含未注册的工具。")
        app_id, tool = definition
        if "operate" not in platform.rbac.actions(user, app_id):
            raise AIError("forbidden", "没有使用所请求工具的权限。")
        # OpenAI 函数名只接受字母、数字、下划线和连字符。
        base = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:64]
        alias, suffix = base, 0
        while alias in aliases:
            suffix += 1
            alias = f"{base[:61]}_{suffix}"
        aliases[alias] = name
        params = tool.get("params", tool.get("input", {}))
        if not isinstance(params, dict):
            params = {}
        properties = {key: _parameter_schema(value.rstrip("?")) for key, value in params.items()
                      if isinstance(value, str)}
        tools.append({"type": "function", "function": {
            "name": alias,
            "description": tool.get("description", tool.get("desc", "")),
            "parameters": {"type": "object", "properties": properties},
        }})
    return tools, aliases


def chat_message(service, user, payload, *, model=None, app_id=models.PLATFORM_APP, timeout=50):
    """服务端工具调用入口。接受 OpenAI 工具声明，继续走实例模型路由。"""
    request = ChatRequest({**payload, "classification": models._classification(payload)})
    result, _ = service.call(user, request, model=model, app_id=app_id, timeout=timeout)
    return {key: result["result"][key] for key in ("content", "tool_calls")}


def _chat(service, user, body, payload):
    if "tools" in payload:
        payload = ChatRequest(payload)
    result, note = service.call(user, payload, model=body.model)
    reply = result["result"]
    return {"model": result["model"], "routeNote": note,
            **{key: reply[key] for key in ("content", "usage", "mock")}}


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, allow_nan=False)}\n\n"


async def _stream(service, user, body, payload, aliases):
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=32)
    cancelled = Event()

    def publish(event):
        if cancelled.is_set():
            raise AIError("timeout", "本轮已中断。")
        future = asyncio.run_coroutine_threadsafe(queue.put(event), loop)
        while not cancelled.is_set():
            try:
                future.result(timeout=0.1)
                return
            except PublishTimeout:
                continue
        future.cancel()
        raise AIError("timeout", "本轮已中断。")

    def emit(chunk):
        event, data = chunk
        if event == "tool":
            name = aliases.get(data["name"])
            if name is None:
                raise AIError("provider_error", "模型返回了未请求的工具。")
            data = {"tool": name, "args": data["arguments"]}
        publish((event, data))

    def run():
        channel = Channel(emit, cancelled)
        try:
            result, _ = service.call(user, ChatRequest(payload, channel), model=body.model, timeout=25)
            reply = result["result"]
            message_id = uuid4()
            if reply["mock"]:
                signature = json.dumps([result["model"], reply], ensure_ascii=False, sort_keys=True)
                message_id = uuid5(NAMESPACE_URL, signature)
            publish(("done", {"messageId": f"M-{message_id}", "usage": reply["usage"]}))
        except AIError as error:
            if not cancelled.is_set():
                publish(("error", error))
        except Exception:
            if not cancelled.is_set():
                publish(("error", AIError("internal_error", "对话暂时无法完成。")))

    worker = asyncio.create_task(asyncio.to_thread(run))
    try:
        first = await queue.get()
    except BaseException:
        cancelled.set()
        raise
    if first[0] == "error":
        await worker
        return _chat_error(first[1])

    async def events():
        event, data = first
        try:
            while True:
                if event == "error":
                    yield _sse(event, {"code": data.kind.upper(), "message": str(data)})
                    break
                yield _sse(event, data)
                if event == "done":
                    break
                event, data = await queue.get()
        finally:
            cancelled.set()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _chat_error(error):
    status = {"tool_not_found": 404, "forbidden": 403, "internal_error": 500}.get(error.kind)
    if status is not None:
        return models._response_error(status, error.kind.upper(), str(error))
    return models._gateway_error(error)


@router.post("/ai/chat")
async def chat(body: ChatBody, request: Request, service=Depends(models._service), user=Depends(current_user)):
    try:
        tools, aliases = _registered_tools(request.app.state.platform, user, body.tools)
        payload = body.model_dump(exclude={"model", "stream", "tools"}, exclude_none=True)
        if tools:
            payload["tools"] = tools
        if body.stream:
            return await _stream(service, user, body, payload, aliases)
        return await run_in_threadpool(_chat, service, user, body, payload)
    except AIError as error:
        return _chat_error(error)
