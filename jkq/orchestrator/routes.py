"""会话消息 POST 接线及流式回复的持久化边界。"""

import logging
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from haiknow_sdk import User
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from starlette.types import Send

from jkq.compat import error_content
from jkq.conversations.routes import ConversationRoute, Utf8Text
from jkq.conversations.store import ConversationNotFound, ConversationStore, encode

from .classification import Classification, strictest
from .persistence import finish_turn, start_turn
from .ports import ModelGateway, ToolBridge
from .service import ModelStreamError, respond

LOGGER = logging.getLogger(__name__)


class MessageBody(BaseModel):
    text: Utf8Text = Field(min_length=1)
    app: Utf8Text | None = Field(default=None, min_length=1, max_length=100)
    model: Utf8Text | None = Field(default=None, min_length=1)
    files: list[dict] = Field(default_factory=list)
    classification: Utf8Text | None = None
    stream: bool = False
    mode: Literal["general", "policy_service"] = "general"
    enterpriseId: Utf8Text | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def valid_context(self):
        if self.enterpriseId is not None:
            self.enterpriseId = self.enterpriseId.strip()
            if not self.enterpriseId:
                raise ValueError("企业编号不能为空")
        if self.mode == "policy_service" and self.app not in (None, "policy"):
            raise ValueError("政策岗位只能使用政策应用上下文")
        return self

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
    """流式发送正文，数据库提交完成后才发送 done。"""

    def __init__(self, message_id, generate, complete):
        super().__init__((), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })
        self.message_id, self.generate, self.complete = message_id, generate, complete

    async def stream_response(self, send: Send) -> None:
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        last_meta = None
        sent_deltas = 0

        async def emit(kind, payload, *, more=True):
            try:
                await send({"type": "http.response.body", "body": _event(kind, payload).encode(),
                            "more_body": more})
            except OSError as exc:
                raise ClientDisconnect() from exc

        async def meta(model=None, route_note=None):
            nonlocal last_meta
            if last_meta != (model, route_note):
                await emit("meta", {"messageId": self.message_id, "model": model, "routeNote": route_note})
                last_meta = (model, route_note)

        async def event(kind, payload):
            nonlocal sent_deltas
            if last_meta is None:
                await meta()
            await emit(kind, payload)
            if kind == "delta":
                sent_deltas += 1

        async def persistence_error(status, message):
            error = error_content(status, {"detail": message})["error"]
            await emit("error", {"code": error["code"], "message": error["message"]}, more=False)

        try:
            reply = await self.generate(event, meta)
        except ModelStreamError:
            await emit("error", {"code": "PROVIDER_ERROR", "message": "模型回复中断，请重试。"}, more=False)
            return
        if last_meta is None:
            await meta(reply.model, reply.route_note)
        for text in reply.deltas[sent_deltas:]:
            await emit("delta", {"text": text})
        for card in reply.cards:
            await emit("card", card)
        try:
            payload = await self.complete(reply)
        except ConversationNotFound:
            await persistence_error(404, "会话或待完成的消息已不存在。")
            return
        except Exception as exc:
            LOGGER.error("会话消息提交失败 (%s)", type(exc).__name__)
            await persistence_error(500, "回复保存失败，请稍后重试。")
            return
        await emit("done", {"messageId": self.message_id, **payload}, more=False)


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
        if body.mode == "policy_service" and "view" not in app.state.platform.rbac.actions(user, "policy"):
            return JSONResponse({"error": {"code": "FORBIDDEN", "message": "无权使用政策服务岗位",
                                           "details": {"app": "policy", "need": "view"}}}, status_code=403)
        app_classes = {app_id: entry.manifest.get("dataClass") for app_id, entry in app.state.platform.apps.copy().items()}
        input_class = classification if body.classification is None else strictest(classification, body.classification)
        pending = await run_in_threadpool(
            start_turn, store, user.id, cid, body.text, body.files,
            app=body.app, app_classes=app_classes, classification=input_class,
            mode=body.mode, enterprise_id=body.enterpriseId,
        )

        async def generate_reply(on_event=None, on_meta=None):
            return await respond(
                request, user, text=body.text, app=body.app, model=body.model, history=pending.history,
                gateway=gateway if gateway is not None else getattr(app.state, "chat_gateway", None),
                bridge=bridge if bridge is not None else getattr(app.state, "apps_bridge", None),
                classification=pending.user["classification"], on_event=on_event, on_meta=on_meta,
                mode=body.mode, enterprise_id=body.enterpriseId,
            )

        async def complete(reply):
            return await run_in_threadpool(finish_turn, store, user.id, cid, pending, reply.fields())

        if not body.stream:
            return await complete(await generate_reply())

        return MessageStream(pending.assistant["id"], generate_reply, complete)

    app.include_router(router)
