"""经开区直连对话。工具名称按会话授权校验，工具调用只作为事件透出。"""

import hashlib
import json
from threading import Event
from uuid import uuid4

import anyio
from anyio.from_thread import BlockingPortal
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field, StrictBool

from haiknow_core.aihub.chat_gateway import ConversationGateway
from haiknow_core.aihub.errors import AIError
from haiknow_core.aihub.gateway import allowed_outbound
from haiknow_core.aihub.providers.jkq_chat import ProviderRejected
from haiknow_core.main import current_user
from jkq import models


class ChatRequest(models.ChatBody):
    stream: StrictBool = False
    tools: list[models.ModelId] = Field(default_factory=list)


router = APIRouter(lifespan=models.router.lifespan_context)
router.routes.extend(route for route in models.router.routes if route.endpoint is not models.chat)


def _gateway(service, user, body):
    items = service.items()
    selected = body.model or service.current(user.id, items)
    if selected != "auto":
        service._require_enabled(items, selected)
    preferred = service.primary if selected == "auto" else selected
    candidates = [
        (service.providers[key], items[key]["name"])
        for key in sorted(service.models, key=lambda key: key != preferred)
        if items[key]["enabled"]
    ]
    if not candidates and body.classification != "confidential":
        raise AIError("not_configured", "没有已启用的模型。")
    allowed = [p for p, _ in candidates if allowed_outbound(p, body.classification)]

    def record(provider, model, status, usage):
        service.store.audit(models.PLATFORM_APP, user.id, "ai.chat", {
            "provider": provider, "model": model, "status": status, "usage": usage,
        })

    def meta(provider, model):
        notes = []
        if candidates[0][0]["id"] != allowed[0]["id"]:
            notes.append("按密级切换到白名单模型")
        if provider != allowed[0]["id"]:
            notes.append("主模型调用失败，已回退")
        if service.providers[provider]["kind"] == "mock":
            notes.append("使用模拟模型")
        return {"model": model, "routeNote": "，".join(notes)}

    return ConversationGateway(
        service.settings, service.store.audit, candidates, record, transport=service.transport,
    ), meta


def _encode(event, data):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()


class ChatStream(Response):
    """等首个上游结果再发响应头，让前置拒绝保留 HTTP 状态码。"""

    media_type = "text/event-stream"

    def __init__(self, gateway, payload, user, meta):
        super().__init__(headers={"Cache-Control": "no-cache"})
        del self.headers["content-length"]
        self.gateway = gateway
        self.payload = payload
        self.user = user
        self.meta = meta

    async def __call__(self, scope, receive, send):
        cancelled = Event()
        output, incoming = anyio.create_memory_object_stream(1)

        async with output, BlockingPortal() as portal, anyio.create_task_group() as group:
            async def watch_disconnect():
                while (await receive())["type"] != "http.disconnect":
                    pass
                group.cancel_scope.cancel()

            def produce():
                def publish(provider, model, kind, data):
                    if not cancelled.is_set():
                        try:
                            portal.call(output.send, (provider, model, kind, data))
                        except anyio.BrokenResourceError:
                            if not cancelled.is_set():
                                raise

                try:
                    result = self.gateway.stream_message(
                        models.PLATFORM_APP, self.payload, principal=self.user,
                        on_event=publish, cancelled=cancelled, timeout=25,
                    )
                    detail = result["result"]
                    if detail["mock"]:
                        digest = hashlib.sha256(json.dumps(self.payload, sort_keys=True).encode())
                        message_id = "M-" + digest.hexdigest()[:24]
                    else:
                        message_id = "M-" + uuid4().hex
                    publish(result["provider"], result["model"], "done",
                            {"messageId": message_id, "usage": detail["usage"]})
                except (ProviderRejected, AIError) as error:
                    if isinstance(error, ProviderRejected):
                        error = AIError("provider_error", "模型服务商拒绝了请求。")
                    publish(None, None, "error", error)

            group.start_soon(watch_disconnect)
            group.start_soon(anyio.to_thread.run_sync, produce)
            started = False
            try:
                async with incoming:
                    async for provider, model, kind, data in incoming:
                        if not started:
                            if kind == "error":
                                await models._gateway_error(data)(scope, receive, send)
                                break
                            await send({"type": "http.response.start", "status": 200,
                                        "headers": self.raw_headers})
                            await send({"type": "http.response.body", "more_body": True,
                                        "body": _encode("meta", self.meta(provider, model))})
                            started = True
                        if kind == "error":
                            data = {"code": data.kind.upper(), "message": str(data)}
                        terminal = kind in ("done", "error")
                        await send({"type": "http.response.body", "more_body": not terminal,
                                    "body": _encode(kind, data)})
                        if terminal:
                            break
            finally:
                cancelled.set()
                incoming.close()
                group.cancel_scope.cancel()


@router.post("/api/v1/ai/chat", responses={200: {"content": {"text/event-stream": {}}}})
def chat(body: ChatRequest, request: Request, service=Depends(models._service),
         user=Depends(current_user)):
    payload = body.model_dump(exclude={"model", "stream", "tools"}, exclude_none=True)
    if body.tools:
        bridge = getattr(request.app.state, "apps_bridge", None)
        visible = {item["name"] for item in bridge.tools(user)["items"]} if bridge else set()
        if any(name not in visible for name in body.tools):
            return models._response_error(404, "TOOL_NOT_FOUND", "工具不存在或当前用户不可用。")
        payload["tools"] = [
            {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}
            for name in dict.fromkeys(body.tools)
        ]
    try:
        gateway, meta = _gateway(service, user, body)
        if body.stream:
            return ChatStream(gateway, payload, user, meta)
        result = gateway.call_message(models.PLATFORM_APP, payload, principal=user)
        return {**meta(result["provider"], result["model"]), "content": result["result"]["content"]}
    except ProviderRejected:
        return models._gateway_error(AIError("provider_error", "模型服务商拒绝了请求。"))
    except AIError as error:
        return models._gateway_error(error)
