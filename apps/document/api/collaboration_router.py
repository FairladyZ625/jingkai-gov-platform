"""公文协作 §4.4 的润色、比对和批注路由。"""

from typing import Annotated, Literal

from fastapi import APIRouter
from haiknow_sdk import DataError
from pydantic import BaseModel, Field, StrictBool

from . import comments, diff, drafts, polish
from .drafting_router import DocumentRoute, Operator, Text, Viewer

router = APIRouter(route_class=DocumentRoute)
Index = Annotated[int, Field(strict=True, ge=0)]


class PolishIn(BaseModel):
    style: Literal["formal", "concise"]
    para: Index | None = None


class VersionRef(BaseModel):
    id: Text
    v: Index


class CompareIn(BaseModel):
    a: VersionRef | str
    b: VersionRef | str


class CommentIn(BaseModel):
    para: Index
    text: Text


class CommentUpdate(BaseModel):
    reply: Text | None = None
    resolved: StrictBool | None = None


def _check_paragraph(content: dict, para: int) -> None:
    if para >= len(content["paragraphs"]):
        raise DataError("invalid_request", "段落编号超出正文范围", para=para)


def _current_draft(ctx: Viewer, identity: str) -> dict:
    record = ctx.records.get(identity)
    if record["type"] != drafts.RECORD_TYPE:
        raise DataError("not_found", "文稿不存在")
    return record


def _text(ctx: Viewer, source: VersionRef | str) -> str:
    if isinstance(source, str):
        return source
    draft = drafts.get(ctx, source.id, source.v)
    content = draft["versions"][0]["content"]
    fields = (content["title"], content["docNo"], content["to"], *content["paragraphs"],
              content["sign"], content["date"])
    return "\n".join(text for text in fields if text)


@router.post("/drafts/{identity}/polish")
def preview_polish(identity: str, body: PolishIn, ctx: Operator):
    current = _current_draft(ctx, identity)
    content = current["data"]["content"]
    if body.para is not None:
        _check_paragraph(content, body.para)
    result = polish.preview(content, body.style, body.para)
    ctx.audit("document.polish.mock", {"recordId": identity, "provider": "mock", "style": body.style})
    return result


@router.post("/compare")
def compare(body: CompareIn, ctx: Viewer):
    return diff.compare(_text(ctx, body.a), _text(ctx, body.b))


@router.post("/drafts/{identity}/comments")
def add_comment(identity: str, body: CommentIn, ctx: Operator):
    draft = _current_draft(ctx, identity)
    _check_paragraph(draft["data"]["content"], body.para)
    return {"item": comments.add(ctx, draft, body.para, body.text)}


@router.patch("/drafts/{identity}/comments/{cid}")
def patch_comment(identity: str, cid: str, body: CommentUpdate, ctx: Operator):
    if body.reply is None and body.resolved is None:
        raise DataError("invalid_request", "需要填写回复或指定解决状态")
    _current_draft(ctx, identity)
    return {"item": comments.update(ctx, identity, cid, body.reply, body.resolved)}
