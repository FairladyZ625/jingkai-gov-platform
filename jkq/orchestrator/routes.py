"""会话消息 POST 接线及流式回复的持久化边界。"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from haiknow_sdk import User
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from jkq.conversations.routes import ConversationRoute, Utf8Text
from jkq.conversations.store import ConversationStore, encode

from .persistence import finish_turn, start_turn
from .ports import ModelGateway, ToolBridge
from .service import Classification, Reply, respond


class MessageBody(BaseModel):
    text: Utf8Text = Field(min_length=1)
    app: Utf8Text | None = Field(default=None, min_length=1, max_length=100)
    model: Utf8Text | None = Field(default=None, min_length=1)
    files: list[dict] = Field(default_factory=list)
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


def install(
    app: FastAPI, current_user: Callable[[Request], User], *,
    conversations: ConversationStore | None = None, gateway: ModelGateway | None = None,
    bridge: ToolBridge | None = None, classification: Classification = "internal",
) -> None:
    """在实例启动前调用。会话存储默认取 app.state.conversations。"""
    store = conversations if conversations is not None else app.state.conversations
    router = APIRouter(prefix="/api/v1/conversations", route_class=ConversationRoute)

    @router.post("/{cid}/messages")
    async def messages(cid: str, body: MessageBody, request: Request, user=Depends(current_user)):
        pending = await run_in_threadpool(start_turn, store, user.id, cid, body.text, body.files)
        message_id = pending.assistant["id"]

        async def generate_reply():
            return await respond(
                request, user, text=body.text, app=body.app, model=body.model, history=pending.history,
                gateway=gateway, bridge=bridge if bridge is not None else getattr(app.state, "apps_bridge", None),
                classification=classification,
            )

        async def finish(reply):
            return await run_in_threadpool(finish_turn, store, user.id, cid, pending, reply.fields())

        if not body.stream:
            return await finish(await generate_reply())

        async def stream():
            reply = await generate_reply()
            yield _event("meta", {"messageId": message_id, "model": reply.model,
                                  "routeNote": reply.route_note})
            for tool in reply.tool_calls:
                yield _event("tool", tool)
            for text in reply.deltas:
                yield _event("delta", {"text": text})
            for card in reply.cards:
                yield _event("card", card)
            # 在完整正文和卡片都发送之后才提交回复；中途断开时保留预存的标记。
            yield _event("done", {"messageId": message_id, **await finish(reply)})

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(router)
