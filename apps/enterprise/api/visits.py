"""§4.2 走访和逐条决定。路由由企业应用注册点挂载。"""

import json
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body, Depends
from haiknow_sdk import DataError, app_context

from . import ledger
from .company import Duplicate, public
from .ledger_store import BEIJING, document, names_by_id, original, snapshots, write
from .visit_extraction import FIELDS, MOCK_EXTRACTOR, candidates, normalize, visible_text

router = APIRouter(route_class=ledger.LedgerRoute)


def init_tables(db):
    with db:
        db.execute("CREATE TABLE IF NOT EXISTS visit_notes (id TEXT PRIMARY KEY, company TEXT, body TEXT)")
        db.execute("""CREATE TABLE IF NOT EXISTS visit_proposals (
            id TEXT PRIMARY KEY, company TEXT, body TEXT, rejected INTEGER NOT NULL DEFAULT 0
        )""")


def available(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'visit_notes'").fetchone()


def visit_view(visit):
    return {**visit, "notes": visible_text(visit["notes"]), "type": visible_text(visit["type"])}


def field_value(row, field):
    key, dot, part = field.partition(".")
    return row.get(key, {}).get(part) if dot else row.get(key)


def field_change(row, field, value):
    key, dot, part = field.partition(".")
    if dot:
        return {key: {**row.get(key, {}), part: value}}
    return {key: value}


def apply_candidate(field, previous, value):
    if field not in ("contacts", "license"):
        return value
    items = previous or []
    return items if value in items else [*items, value]


def public_value(field, value):
    return None if value is None else field_value(public(field_change({}, field, value)), field)


def proposal_view(proposal, status="pending"):
    fields = {key: value for key, value in proposal.items() if key != "quote"}
    return {**fields, "old": public_value(proposal["field"], proposal["old"]),
            "new": public_value(proposal["field"], proposal["new"]), "status": status}


def applied(history):
    return {change["proposalId"] for change in history if "proposalId" in change}


def pending(db, company_id, accepted):
    rows = db.execute("SELECT id, body FROM visit_proposals WHERE company = ? AND rejected = 0 ORDER BY rowid",
                      (company_id,))
    return [proposal_view(json.loads(body)) for pid, body in rows if pid not in accepted]


def add_visit(ctx, company_id, body, extractor=MOCK_EXTRACTOR):
    if ledger.denied(ctx):
        return ledger.forbidden(ctx)
    notes = body.get("notes")
    visit_type = body.get("type", "上门走访")
    if not isinstance(notes, str) or not notes.strip():
        return ledger.error(400, "INVALID_REQUEST", "走访随记不能为空")
    if not isinstance(visit_type, str) or not visit_type.strip():
        return ledger.error(400, "INVALID_REQUEST", "走访类型必须为非空文本")
    visit = {"id": uuid4().hex, "entId": company_id, "date": datetime.now(BEIJING).date().isoformat(),
             "staff": ctx.user.name, "type": visit_type, "notes": notes, "followups": []}
    with snapshots(writing=True) as db:
        company = document(ctx, company_id)
        raw = original(db, company)
        init_tables(db)
        with db:
            db.execute("INSERT INTO visit_notes VALUES (?, ?, ?)",
                       (visit["id"], company_id, json.dumps(visit, ensure_ascii=False)))

    # 走访先提交。模型响应或超时期间释放 #32 的台账写锁。
    found, issues, warning = candidates(extractor, company["data"]["item"], notes)
    proposals = []
    for field, value, source, quote in found:
        old = field_value(raw, field)
        new = apply_candidate(field, old, value)
        if old != new:
            proposals.append({"id": uuid4().hex, "entId": company_id, "visitId": visit["id"],
                              "field": field, "label": FIELDS.by_key[field].label,
                              "old": old, "new": new, "source": source, "quote": quote})
    with snapshots(writing=True) as db, db:
        if warning:
            visit["warning"] = warning
            db.execute("UPDATE visit_notes SET body = ? WHERE id = ?",
                       (json.dumps(visit, ensure_ascii=False), visit["id"]))
        db.executemany("INSERT INTO visit_proposals (id, company, body) VALUES (?, ?, ?)",
                       [(p["id"], company_id, json.dumps(p, ensure_ascii=False)) for p in proposals])

    ctx.audit("enterprise.visit", {"visitId": visit["id"], "companyId": company_id,
                                  "provider": extractor.destination.id, "proposalCount": len(proposals)})
    return {"visit": visit_view(visit), "proposals": [proposal_view(p) for p in proposals], "issues": issues}


def visit_detail(company_id, ctx):
    document(ctx, company_id)
    with snapshots(writing=False) as db, db:
        # 固定私库读取快照，随后读取 core。这样不会把后写入的建议与旧台账历史拼接。
        db.execute("BEGIN")
        has_visits = available(db)
        result = ledger.detail(company_id, ctx)
        if has_visits:
            rows = db.execute("SELECT body FROM visit_notes WHERE company = ? ORDER BY rowid DESC", (company_id,))
            result["visits"] = [visit_view(json.loads(row[0])) for row in rows] + result["visits"]
            result["proposals"].extend(pending(db, company_id, applied(result["history"])))
    return result


class VisitDecisionWrite:
    """让 #32 的台账 writer 在同一个 core 版本中留下应用决定。"""

    def __init__(self, records, proposal):
        self.records = records
        self.proposal = proposal

    def save(self, **body):
        change = body["data"]["change"]
        field = self.proposal["field"]
        change.update(field=field, old=public_value(field, self.proposal["old"]),
                      new=public_value(field, self.proposal["new"]), source="走访记录",
                      proposalId=self.proposal["id"], visitId=self.proposal["visitId"])
        return self.records.save(**body)


def decide(ctx, proposal_id, body):
    if ledger.denied(ctx):
        return ledger.forbidden(ctx)
    decision = body.get("decision")
    if decision not in ("accept", "reject"):
        return ledger.error(400, "INVALID_REQUEST", "决定必须为 accept 或 reject")

    with snapshots(writing=True) as db:
        row = None
        if available(db):
            row = db.execute("SELECT body, rejected FROM visit_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise DataError("not_found", "更新建议不存在")
        proposal, rejected = json.loads(row[0]), row[1]
        company_id = proposal["entId"]
        company = document(ctx, company_id)
        accepted = applied(ledger.detail(company_id, ctx)["history"])
        if rejected or proposal_id in accepted:
            return ledger.error(409, "LOCKED", "更新建议已经处理")

        if decision == "reject":
            with db:
                db.execute("UPDATE visit_proposals SET rejected = 1 WHERE id = ?", (proposal_id,))
            status = "rejected"
        else:
            field = proposal["field"]
            raw = original(db, company)
            if field_value(raw, field) != proposal["old"]:
                return ledger.error(409, "STALE_VERSION", "台账字段已修改，请重新核对建议")
            try:
                if "value" in body:
                    value = normalize(field, body["value"])
                    proposal["new"] = apply_candidate(field, proposal["old"], value)
                # 用 #32 的快照和版本写入。接受状态来自同一个已提交的 history 条目。
                writer_ctx = replace(ctx, records=VisitDecisionWrite(ctx.records, proposal))
                write(writer_ctx, db, field_change(raw, field, proposal["new"]), names_by_id(ctx), company)
            except Duplicate as exc:
                return ledger.error(409, "DUPLICATE", str(exc))
            except ValueError as exc:
                return ledger.error(400, "INVALID_REQUEST", str(exc))
            accepted.add(proposal_id)
            status = "accepted"

        remaining = len(pending(db, company_id, accepted))

    ctx.audit("enterprise.proposal." + decision, {"proposalId": proposal_id, "companyId": company_id})
    return {"item": proposal_view(proposal, status), "pending": remaining}


def visit_extractor():
    """由实例提供受控提取器，默认使用进程内模拟。"""
    return MOCK_EXTRACTOR


@router.get("/companies/{company_id}")
def get_company(company_id: str, ctx=Depends(app_context)):
    return visit_detail(company_id, ctx)


@router.post("/companies/{company_id}/visits")
def post_visit(company_id: str, body: dict = Body(default=None), ctx=Depends(app_context),
               extractor=Depends(visit_extractor)):
    return add_visit(ctx, company_id, body or {}, extractor)


@router.post("/proposals/{proposal_id}/decision")
def post_decision(proposal_id: str, body: dict = Body(default=None), ctx=Depends(app_context)):
    return decide(ctx, proposal_id, body or {})
