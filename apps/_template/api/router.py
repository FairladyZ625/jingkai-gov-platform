"""__APP_NAME__ 后端：保存 → 提交确认 → 导出。

只 import haiknow_sdk、fastapi、pydantic、标准库和本目录文件。
记录版本、项目范围、确认权限都由平台执行；这里只写业务动作和留痕。
"""
from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from haiknow_sdk import AppContext, DataError, app_context, require

router = APIRouter()
RECORD_TYPE = "note"


def to_csv(record: dict) -> str:
    """把一条已确认记录拼成 CSV；纯函数，测试用手工样本断言。"""
    data = record.get("data") or {}
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["字段", "内容"])
    writer.writerow(["标题", data.get("title", "")])
    writer.writerow(["内容", data.get("content", "")])
    writer.writerow(["状态", record.get("status", "")])
    writer.writerow(["提交人", record.get("submitter", "")])
    writer.writerow(["确认人", record.get("confirmedBy") or ""])
    return buf.getvalue()


class RecordIn(BaseModel):
    project: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(default="", max_length=2000)


class RecordPatch(BaseModel):
    baseVersion: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(default="", max_length=2000)


class SubmitIn(BaseModel):
    assignee: str | None = None


class DecisionIn(BaseModel):
    version: int = Field(gt=0)
    decision: Literal["confirm", "return", "reassign"]
    comment: str = ""
    assignee: str | None = None


@router.get("/records")
def list_records(project: str | None = None, ctx: AppContext = Depends(app_context)):
    return ctx.records.list(project=project)


@router.post("/records", status_code=201)
def create_record(body: RecordIn, ctx: AppContext = Depends(require("operate"))):
    record = ctx.records.save(
        project=body.project,
        type=RECORD_TYPE,
        data={"title": body.title, "content": body.content},
    )
    ctx.audit("create", {"record": record["id"], "version": record["version"]})
    return record


@router.get("/records/{rid}")
def get_record(rid: str, ctx: AppContext = Depends(app_context)):
    return ctx.records.get(rid)


@router.put("/records/{rid}")
def update_record(rid: str, body: RecordPatch, ctx: AppContext = Depends(require("operate"))):
    record = ctx.records.save(
        id=rid,
        baseVersion=body.baseVersion,
        data={"title": body.title, "content": body.content},
    )
    ctx.audit("update", {"record": rid, "version": record["version"]})
    return record


@router.post("/records/{rid}/submit", status_code=201)
def submit_record(rid: str, body: SubmitIn, ctx: AppContext = Depends(require("operate"))):
    record = ctx.records.get(rid)
    review = ctx.reviews.submit(rid, record["version"], assignee=body.assignee)
    ctx.audit("submit", {"record": rid, "version": record["version"], "review": review["id"]})
    return review


@router.get("/reviews")
def list_reviews(ctx: AppContext = Depends(app_context)):
    """待我确认 + 我提交的；没有 approve 的账号 todo 为空。"""
    return {"todo": ctx.reviews.list(assignee="me")["items"], "submitted": ctx.reviews.list(mine="submitted")["items"]}


@router.post("/reviews/{review_id}/decisions")
def decide_review(review_id: str, body: DecisionIn, ctx: AppContext = Depends(require("approve"))):
    review = ctx.reviews.decide(
        review_id,
        version=body.version,
        decision=body.decision,
        comment=body.comment,
        assignee=body.assignee,
    )
    ctx.audit(body.decision, {"review": review_id, "record": review["recordId"], "version": review["version"]})
    return review


@router.get("/artifacts")
def list_artifacts(project: str | None = None, ctx: AppContext = Depends(app_context)):
    return ctx.artifacts.find(project=project, app=ctx.app_id)


@router.get("/records/{rid}/export")
def export_record(rid: str, version: int | None = None, ctx: AppContext = Depends(app_context)):
    record = ctx.records.get(rid, version)
    if record["status"] != "confirmed":
        raise DataError("invalid_state", "记录确认后才能导出")
    ctx.audit("export", {"record": rid, "version": record["version"]})
    return Response(
        "\ufeff" + to_csv(record),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=record-{rid}.csv"},
    )