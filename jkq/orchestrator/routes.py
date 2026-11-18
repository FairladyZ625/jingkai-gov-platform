"""会话消息 POST 接线及流式回复的持久化边界。"""

from collections.abc import Callable

from anyio import CancelScope
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from haiknow_sdk import User
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.types import Send

from jkq.conversations.routes import ConversationRoute, Utf8Text
from jkq.conversations.store import ConversationStore, encode

from .classification import Classification, strictest
from .persistence import completed_reply, finish_turn, start_turn
from .ports import ModelGateway, ToolBridge
from .service import ModelStreamError, respond


class MessageBody(BaseModel):
    text: Utf8Text = Field(min_length=1)
    app: Utf8Text | None = Field(default=None, min_length=1, max_length=100)
    model: Utf8Text | None = Field(default=None, min_length=1)
    files: list[dict] = Field(default_factory=list)
    classification: Utf8Text | None = None
    stream: bool = False

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value

    @field_validator("files")
    @classmethod
    def json_files(cls, value: list[dict]) -> list[dict]:
        encode(value).encode("utf-8")
        return value


def _event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {encode(data)}\n\n"


class MessageStream(StreamingResponse):
    """在网关回调中发送 SSE，收到终止帧的 ASGI send 回执后才完成消息。"""

    def __init__(self, message_id, generate, complete, commit):
        super().__init__((), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })
        self.message_id, self.generate, self.complete, self.commit = message_id, generate, complete, commit

    async def stream_response(self, send: Send) -> None:
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        meta_sent = False
        sent_deltas = 0

        async def emit(kind, payload, *, more=True):
            try:
                await send({"type": "http.response.body", "body": _event(kind, payload).encode(),
                            "more_body": more})
            except OSError as exc:
                raise ClientDisconnect() from exc

        async def meta(model=None, route_note=None):
            nonlocal meta_sent
            if not meta_sent:
                await emit("meta", {"messageId": self.message_id, "model": model, "routeNote": route_note})
                meta_sent = True

        async def event(kind, payload):
            nonlocal sent_deltas
            await meta()
            await emit(kind, payload)
            if kind == "delta":
                sent_deltas += 1

        try:
            reply = await self.generate(event)
        except ModelStreamError:
            await emit("error", {"code": "PROVIDER_ERROR", "message": "模型回复中断，请重试。"}, more=False)
            return
        await meta(reply.model, reply.route_note)
        for text in reply.deltas[sent_deltas:]:
            await emit("delta", {"text": text})
        for card in reply.cards:
            await emit("card", card)
        payload = await self.complete(reply)
        await emit("done", {"messageId": self.message_id, **payload}, more=False)
        with CancelScope(shield=True):
            await self.commit(payload)


def install(
    app: FastAPI, current_user: Callable[[Request], User], *,
    conversations: ConversationStore | None = None, gateway: ModelGateway | None = None,
    bridge: ToolBridge | None = None, classification: Classification | None = None,
) -> None:
    """在实例启动前调用。会话存储默认取 app.state.conversations。"""
    store = conversations if conversations is not None else app.state.conversations
    router = APIRouter(prefix="/api/v1/conversations", route_class=ConversationRoute)

    @router.post("/{cid}/messages")
    async def messages(cid: str, body: MessageBody, request: Request, user=Depends(current_user)):
        app_classes = {app_id: entry.manifest.get("dataClass") for app_id, entry in app.state.platform.apps.copy().items()}
        input_class = classification if body.classification is None else strictest(classification, body.classification)
        pending = await run_in_threadpool(
            start_turn, store, user.id, cid, body.text, body.files,
            app=body.app, app_classes=app_classes, classification=input_class,
        )

        async def generate_reply(on_event=None):
            return await respond(
                request, user, text=body.text, app=body.app, model=body.model, history=pending.history,
                gateway=gateway if gateway is not None else getattr(app.state, "chat_gateway", None),
                bridge=bridge if bridge is not None else getattr(app.state, "apps_bridge", None),
                classification=pending.user["classification"], on_event=on_event,
            )

        async def complete(reply):
            return await run_in_threadpool(completed_reply, store, user.id, cid, pending, reply.fields())

        async def commit(payload):
            await run_in_threadpool(finish_turn, store, user.id, cid, pending, payload)

        if not body.stream:
            payload = await complete(await generate_reply())
            await commit(payload)
            return payload

        return MessageStream(pending.assistant["id"], generate_reply, complete, commit)

    app.include_router(router)
