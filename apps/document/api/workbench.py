"""工作台投影；文稿、审签仍由既有记录服务保管。"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, DataError, require
from pydantic import BaseModel, Field

from . import comments, drafts
from .drafting_router import DocumentRoute, Viewer

router = APIRouter(route_class=DocumentRoute)
Approver = Annotated[AppContext, Depends(require("approve"))]


@router.get("/workbench")
def workspace(ctx: Viewer):
    reviewers = ctx.preview.members.list(drafts.PROJECT)["items"]
    records = ctx.records.list(type=drafts.RECORD_TYPE)["items"]
    groups = comments.by_draft(ctx)
    items = [{**drafts._summary(r),
              "authorId": r["data"].get("authorId") or ctx.records.get(r["id"], 1)["submitter"],
              "project": r["project"],
              "source": r["data"].get("source"),
              "comments": sum(not c["resolved"] for c in groups.get(r["id"], []))}
             for r in sorted(records, key=lambda r: r["createdAt"], reverse=True)]
    reviews = {r["id"]: r for r in [*ctx.reviews.list()["items"],
                                      *ctx.reviews.list(mine="submitted")["items"]]}
    return {"items": items, "reviewers": reviewers, "reviews": list(reviews.values())}


class Decision(BaseModel):
    version: int = Field(strict=True, ge=1)
    decision: Literal["approve", "reject"]
    comment: str = ""


@router.post("/workbench/reviews/{identity}")
def decide(identity: str, body: Decision, ctx: Approver):
    if body.decision == "reject" and not body.comment.strip():
        raise DataError("invalid_request", "请说明退回原因")
    result = ctx.reviews.decide(identity, version=body.version,
                               decision="confirm" if body.decision == "approve" else "return",
                               comment=body.comment)
    return {"item": result}


def meeting_content(platform, user, source):
    """只接受当前用户可读取的会议定稿快照，不采信客户端正文和标题。"""
    record = platform.data.get_record(user, "meeting", source.id, source.version)
    data = record["data"]
    if (record["type"] != "meeting" or data.get("minutesStatus") != "已定稿"
            or data.get("finalizedVersion") != source.version):
        raise DataError("invalid_reference", "只能从已定稿会议的固定版本转入公文")
    minutes = data.get("minutesEdit") or {}
    if not minutes.get("title") or not isinstance(minutes.get("body"), list):
        raise DataError("invalid_reference", "会议定稿内容不完整")
    paragraphs = []
    for part in minutes["body"]:
        if part.get("h"):
            paragraphs.append(str(part["h"]))
        if part.get("p"):
            paragraphs.append(str(part["p"]))
    if not paragraphs:
        raise DataError("invalid_reference", "会议定稿正文为空")
    content = {"title": minutes["title"], "docNo": "【待补：发文字号】",
               "to": "【待补：主送机关】", "paragraphs": paragraphs,
               "sign": "【待补：发文机关】", "date": "【待补：成文日期】"}
    return content, {"app": "meeting", "id": source.id, "version": source.version,
                     "title": minutes["title"]}
