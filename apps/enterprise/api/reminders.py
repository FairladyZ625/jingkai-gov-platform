"""企业到期提醒。查询只计算当前提醒，每日任务负责投递。"""
from datetime import date
from hashlib import sha256

from fastapi import Depends
from haiknow_sdk import DataError, app_context
from haiknow_sdk.preview.components import c04
from haiknow_sdk.preview.jobs import operation
from haiknow_sdk.preview.schedules import schedule

from . import requests
from .ledger_store import PROJECT, documents, original, snapshots

router = requests.router


def candidates(ctx, day):
    companies = {doc["id"]: doc for doc in documents(ctx)}
    for doc in requests.issue_docs(ctx):
        row = doc["data"]["item"]
        company = companies.get(row["entId"])
        if not company or not row.get("due") or row["status"] == "已办结":
            continue
        node = c04.Node(doc["id"], owner=doc["submitter"], planned=row["due"])
        if c04.plan([node], now=day).reminders:
            yield doc, doc["id"], {"entId": row["entId"], "issueId": doc["id"],
                                   "name": company["data"]["item"]["name"], "kind": "诉求临期",
                                   "level": "high", "text": f"诉求已超过截止日期 {row['due']}"}
    for ent_id, doc in companies.items():
        row = doc["data"]["item"]
        for qualification in row.get("qualifications", []):
            try:
                expires = date.fromisoformat(qualification.get("validTo", ""))
            except ValueError:
                continue
            if 0 <= (expires - day).days <= 30:
                name = qualification.get("name") or "企业资质"
                key = sha256(name.encode()).hexdigest()
                yield doc, f"{ent_id}/{key}", {"entId": ent_id, "name": row["name"], "kind": "资质到期",
                                               "level": "mid", "text": f"{name} 将于 {expires} 到期"}


@router.get("/alerts")
def alerts(ctx=Depends(app_context)):
    return {"items": [alert for _, _, alert in candidates(ctx, requests.today())]}


@operation("enterprise.reminders", version="1")
@schedule("enterprise.daily", operation="enterprise.reminders", projects=(PROJECT,), at=("09:00",))
def scan(job, body):
    ctx = job.context
    if job.project != PROJECT or requests.denied(ctx):
        raise DataError("forbidden", "无权扫描企业提醒")
    day = requests.today()
    members = ctx.preview.members.list(PROJECT, action="view")["items"]
    ids = {m["id"] for m in members}
    sent = 0
    # 与诉求改期/结案共用台账写锁，重跑或多个任务同时扫描时复用当天回执。
    with snapshots(writing=True) as db:
        db.execute("CREATE TABLE IF NOT EXISTS reminder_receipts "
                   "(day TEXT, subject TEXT, PRIMARY KEY(day, subject))")
        for doc, subject, alert in candidates(ctx, day):
            key = (day.isoformat(), subject)
            if db.execute("SELECT 1 FROM reminder_receipts WHERE day=? AND subject=?", key).fetchone():
                continue
            is_issue = "issueId" in alert
            row = doc["data"]["item"]
            if is_issue and "snapshot" in doc["data"]:
                row = original(db, doc)
            owner = row.get("owner" if is_issue else "servicer", "")
            matches = [m["id"] for m in members if m["name"] == owner]
            recipient = doc["submitter"]
            if owner in ids:
                recipient = owner
            elif len(matches) == 1:
                recipient = matches[0]
            if recipient not in ids:
                recipient = ctx.user.id
            ctx.preview.messages.send(idempotency_key="/".join(key), recipient_ids=[recipient],
                                      record_id=doc["id"], version=doc["version"],
                                      title=alert["kind"], body=alert["text"])
            with db:
                db.execute("INSERT INTO reminder_receipts VALUES (?, ?)", key)
            sent += 1
    return {"sent": sent}


def register(parent, namespace):
    """由企业应用入口调用，保留同一入口已有的任务与调度声明。"""
    parent.include_router(router)
    for key in ("__haiknow_jobs__", "__haiknow_schedules__"):
        namespace.setdefault(key, {}).update(globals()[key])
