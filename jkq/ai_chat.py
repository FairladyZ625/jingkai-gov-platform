"""经开区 §3.2 网关直连。模型路由、密级和配额沿用 #15。"""

import asyncio
import json
import re
from concurrent.futures import TimeoutError as PublishTimeout
from threading import Event
from typing import Annotated
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field, StrictBool, StringConstraints
from starlette.concurrency import run_in_threadpool

from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.streaming import Channel, ChatRequest
from haiknow_core.main import current_user
from haiknow_sdk import PermissionDenied

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
    if "|" in kind:
        return {"type": "string", "enum": kind.split("|")}
    return {}


def _matches_parameter(value, schema):
    types = {"string": (str,), "number": (int, float), "integer": (int,),
             "boolean": (bool,), "object": (dict,), "array": (list,)}
    kind = schema.get("type")
    if kind and type(value) not in types[kind]:
        return False
    if "items" in schema:
        return all(_matches_parameter(item, schema["items"]) for item in value)
    return "enum" not in schema or value in schema["enum"]


def _tool_validator(tools):
    schemas = {tool["function"]["name"]: tool["function"]["parameters"] for tool in tools}

    def validate(call):
        schema = schemas.get(call["name"])
        if schema is None:
            raise AIError("provider_error", "模型返回了未请求的工具。")
        arguments = call["arguments"]
        properties = schema["properties"]
        missing = set(schema["required"]) - arguments.keys()
        unexpected = arguments.keys() - properties.keys()
        if missing or unexpected or any(not _matches_parameter(v, properties[k]) for k, v in arguments.items()):
            raise AIError("provider_error", "模型返回的工具参数与登记清单不符。")

    return validate


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
    requested = dict.fromkeys(names)
    if requested.keys() - definitions.keys():
        raise AIError("tool_not_found", "请求包含未注册的工具。")
    for name in requested:
        app_id, tool = definitions[name]
        if "operate" not in platform.rbac.actions(user, app_id):
            platform.store.audit(app_id, user.id, "ai.tool_forbidden", {"need": "operate"})
            raise PermissionDenied(app_id, "operate")
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
        required = [key for key in properties if not params[key].endswith("?")]
        tools.append({"type": "function", "function": {
            "name": alias,
            "description": tool.get("description", tool.get("desc", "")),
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False},
        }})
    return tools, aliases


def chat_message(service, user, payload, *, model=None, app_id=models.PLATFORM_APP, timeout=50):
    """服务端工具调用入口。接受 OpenAI 工具声明，继续走实例模型路由。"""
    request = ChatRequest({**payload, "classification": models._classification(payload)})
    result, _ = service.call(user, request, model=model, app_id=app_id, timeout=timeout)
    return {key: result["result"][key] for key in ("content", "tool_calls")}


def _chat(service, user, body, payload, aliases):
    if "tools" in payload:
        payload = ChatRequest(payload, validate_tool_call=_tool_validator(payload["tools"]))
    result, note = service.call(user, payload, model=body.model)
    reply = result["result"]
    response = {"model": result["model"], "routeNote": note,
                **{key: reply[key] for key in ("content", "usage", "mock")}}
    if aliases:
        response["tool_calls"] = [{"name": aliases[call["name"]], "arguments": call["arguments"]}
                                  for call in reply["tool_calls"]]
    return response


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
            data = {"tool": aliases[data["name"]], "args": data["arguments"]}
        publish((event, data))

    def run():
        channel = Channel(emit, cancelled)
        try:
            request = ChatRequest(payload, channel, validate_tool_call=_tool_validator(payload.get("tools", [])))
            result, _ = service.call(user, request, model=body.model, timeout=25)
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
    status = {"tool_not_found": 404, "internal_error": 500}.get(error.kind)
    if status is not None:
        return models._response_error(status, error.kind.upper(), str(error))
    return models._gateway_error(error)


@router.post("/ai/chat")
async def chat(body: ChatBody, request: Request, service=Depends(models._service), user=Depends(current_user)):
    try:
        tools, aliases = await run_in_threadpool(_registered_tools, request.app.state.platform, user, body.tools)
        payload = body.model_dump(exclude={"model", "stream", "tools"}, exclude_none=True)
        if tools:
            payload["tools"] = tools
        if body.stream:
            return await _stream(service, user, body, payload, aliases)
        return await run_in_threadpool(_chat, service, user, body, payload, aliases)
    except PermissionDenied as error:
        return JSONResponse({"error": {"code": "FORBIDDEN", "message": "没有使用所请求工具的权限。",
                                      "details": {"app": error.app_id, "need": error.action}}}, status_code=403)
    except AIError as error:
        return _chat_error(error)
