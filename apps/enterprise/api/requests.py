"""企业诉求。自由文本保存在台账同一私库，core 版本只保存可公开的摘要。"""
import json
from contextlib import nullcontext
from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, Body, Depends
from haiknow_sdk import DataError, app_context

from .ledger import LedgerRoute, denied, error, forbidden
from .ledger_store import BEIJING, PROJECT, document, documents, original, snapshots

router = APIRouter(route_class=LedgerRoute)
TYPE = "enterprise.issue"
STATUSES = ("待分派", "办理中", "待补材料", "已办结")


def today():
    return datetime.now(BEIJING).date()


def issue_docs(ctx):
    return ctx.records.list(project=PROJECT, type=TYPE)["items"]


def validate(body, allowed):
    if not isinstance(body, dict) or not body or body.keys() - allowed:
        return "请提供支持的诉求字段"
    if any(not isinstance(v, str) for v in body.values()):
        return "诉求字段须为文本"
    if "status" in body and body["status"] not in STATUSES:
        return "诉求状态无效"
    if "from" in body and body["from"] not in ("走访", "电话", "会议", "座谈"):
        return "诉求来源无效"
    if body.get("due"):
        try:
            if date.fromisoformat(body["due"]).isoformat() == body["due"]:
                return
        except ValueError:
            pass
        return "截止日期须为 YYYY-MM-DD"


def save(ctx, db, row, previous=None):
    ref = uuid4().hex
    with db:
        db.execute("INSERT INTO snapshots VALUES (?, ?)", (ref, json.dumps(row, ensure_ascii=False)))
    public = {k: row[k] for k in ("entId", "created", "status", "from")}
    if row.get("due"):
        public["due"] = row["due"]
    public.update(title="企业诉求", owner="", next="", steps=[])
    revision = {"id": previous["id"], "baseVersion": previous["version"]} if previous else {}
    doc = ctx.records.save(project=PROJECT, type=TYPE,
                           data={"item": public, "snapshot": ref}, **revision)
    return {"item": {**row, "id": doc["id"]}}


@router.post("/issues")
def create(body: dict = Body(default=None), ctx=Depends(app_context)):
    if denied(ctx):
        return forbidden(ctx)
    reason = validate(body, {"entId", "title", "owner", "from", "due", "next"})
    if reason or not all(body.get(k, "").strip() for k in ("entId", "title")):
        return error(400, "INVALID_REQUEST", reason or "企业 ID 和诉求标题必填")
    document(ctx, body["entId"])
    day = today().isoformat()
    row = {"owner": ctx.user.id, "from": "走访", "next": "", **body,
           "created": day, "status": "办理中", "steps": [[day, "登记诉求"]]}
    with snapshots(writing=True) as db:
        return save(ctx, db, row)


@router.patch("/issues/{issue_id}")
def update(issue_id: str, body: dict = Body(default=None), ctx=Depends(app_context)):
    if denied(ctx):
        return forbidden(ctx)
    reason = validate(body, {"status", "owner", "due", "note", "next"})
    if reason:
        return error(400, "INVALID_REQUEST", reason)
    with snapshots(writing=True) as db:
        doc = ctx.records.get(issue_id)
        if doc["type"] != TYPE or doc["project"] != PROJECT:
            raise DataError("not_found", "诉求不存在")
        row = original(db, doc) if "snapshot" in doc["data"] else dict(doc["data"]["item"])
        changed = "status" in body and body["status"] != row["status"]
        note = body.get("note", "").strip()
        row.update({k: v for k, v in body.items() if k != "note"})
        if changed or note:
            text = " · ".join(filter(None, [row["status"] if changed else "", note]))
            row.setdefault("steps", []).append([today().isoformat(), text])
        return save(ctx, db, row, doc)


@router.get("/issues")
def listing(status: str = "", entId: str = "", owner: str = "", ctx=Depends(app_context)):
    names = {d["id"]: d["data"]["item"]["name"] for d in documents(ctx)}
    rows = []
    docs = issue_docs(ctx)
    private = not denied(ctx) and any("snapshot" in doc["data"] for doc in docs)
    with snapshots(writing=False) if private else nullcontext() as db:
        for doc in docs:
            row = doc["data"]["item"]
            if private and "snapshot" in doc["data"]:
                row = original(db, doc)
            if ((not status or row["status"] == status) and (not entId or row["entId"] == entId)
                    and (not owner or row.get("owner") == owner)):
                rows.append({**row, "id": doc["id"], "entName": names.get(row["entId"], "")})
    return {"items": rows, "statuses": STATUSES}
