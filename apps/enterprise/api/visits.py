"""§4.2 走访和逐条决定。路由由企业应用注册点挂载。"""

import json
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Request
from haiknow_sdk import DataError, app_context

from . import ledger, requests
from .company import Duplicate, public
from .ledger_store import BEIJING, TYPE, document, item, names_by_id, original, snapshots, write
from .visit_extraction import CURRENCY, FIELDS, MOCK_EXTRACTOR, candidates, normalize, visible_text

router = APIRouter(route_class=ledger.LedgerRoute)


def init_tables(db):
    with db:
        db.execute("BEGIN")
        db.execute("CREATE TABLE IF NOT EXISTS visit_notes (id TEXT PRIMARY KEY, company TEXT, body TEXT)")
        db.execute("""CREATE TABLE IF NOT EXISTS visit_proposals (
            id TEXT PRIMARY KEY, company TEXT, body TEXT, status TEXT NOT NULL,
            accepted_version INTEGER, accepted_snapshot TEXT
        )""")
        if not has_proposal_state(db):
            # 老建议无法区分真实决定与通用 history 写入。保留记录，重新提取后再确认。
            db.execute("ALTER TABLE visit_proposals ADD COLUMN status TEXT NOT NULL DEFAULT 'legacy'")
            db.execute("ALTER TABLE visit_proposals ADD COLUMN accepted_version INTEGER")
            db.execute("ALTER TABLE visit_proposals ADD COLUMN accepted_snapshot TEXT")


def has_proposal_state(db):
    return any(col[1] == "status" for col in db.execute("PRAGMA table_info(visit_proposals)"))


def available(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'visit_notes'").fetchone()


@contextmanager
def visit_read():
    with snapshots(writing=False) as db, db:
        db.execute("BEGIN")
        yield db if available(db) else None


SUMMARY_FIELDS = ("id", "name", "short", "industry", "scale", "employees", "lastVisit", "lastVisitDays")
SUMMARY_PROPOSAL_FIELDS = ("id", "entId", "visitId", "field", "label", "unit")


def company_summary(row):
    return {key: row[key] for key in SUMMARY_FIELDS if key in row}


def visit_view(visit, summary=False):
    if summary:
        view = {key: visit[key] for key in ("id", "entId", "date") if key in visit}
        if "warning" in visit:
            view["warning"] = visit["warning"]
        return {**view, "type": "走访", "notes": "", "followups": []}
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


def proposal_view(proposal, status="pending", summary=False):
    field = proposal["field"]
    if summary:
        fields = {key: proposal[key] for key in SUMMARY_PROPOSAL_FIELDS if key in proposal}
        fields["source"] = ""
        if field not in ("employees", "yearsInZone") and not field.startswith(("amounts.", "revenue.")):
            return {**fields, "old": None, "new": None, "status": status}
    else:
        fields = {key: value for key, value in proposal.items() if key != "quote"}
    return {**fields, "old": public_value(field, proposal["old"]),
            "new": public_value(field, proposal["new"]), "status": status}


def was_accepted(ctx, company, target_version, snapshot):
    if target_version is None or target_version > company["version"]:
        return False
    target = company if target_version == company["version"] else document(ctx, company["id"], target_version)
    return target["data"].get("snapshot") == snapshot


def pending(db, ctx, company):
    if not has_proposal_state(db):
        return []
    rows = db.execute("""SELECT body, accepted_version, accepted_snapshot FROM visit_proposals
                         WHERE company = ? AND status = 'pending' ORDER BY rowid""", (company["id"],))
    return [json.loads(body) for body, version, snapshot in rows if not was_accepted(ctx, company, version, snapshot)]


def add_visit(ctx, company_id, body, extractor=MOCK_EXTRACTOR, *, summary=False):
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
        metadata = {}
        if field == "revenue.value":
            unit = raw.get("revenue", {}).get("unit")
            if unit not in CURRENCY:
                warning = "台账营收单位缺失或无法识别，请人工核对"
                continue
            value = float(Decimal(str(value)) / CURRENCY[unit])
            metadata["unit"] = unit
        old = field_value(raw, field)
        new = apply_candidate(field, old, value)
        if old != new:
            proposals.append({"id": uuid4().hex, "entId": company_id, "visitId": visit["id"],
                              "field": field, "label": FIELDS.by_key[field].label,
                              "old": old, "new": new, "source": source, "quote": quote, **metadata})
    with snapshots(writing=True) as db, db:
        if warning:
            visit["warning"] = warning
            db.execute("UPDATE visit_notes SET body = ? WHERE id = ?",
                       (json.dumps(visit, ensure_ascii=False), visit["id"]))
        db.executemany("INSERT INTO visit_proposals (id, company, body, status) VALUES (?, ?, ?, 'pending')",
                       [(p["id"], company_id, json.dumps(p, ensure_ascii=False)) for p in proposals])

    ctx.audit("enterprise.visit", {"visitId": visit["id"], "companyId": company_id,
                                  "provider": extractor.destination.id, "proposalCount": len(proposals)})
    return {"visit": visit_view(visit, summary), "proposals": [proposal_view(p, summary=summary) for p in proposals],
            "issues": ["走访记录中有待核对诉求"] * len(issues) if summary else [visible_text(text) for text in issues]}


def with_last_visit(item, saved_date, today):
    if saved_date is None:
        return item
    try:
        previous = date.fromisoformat(item.get("lastVisit") or "")
    except (TypeError, ValueError):
        previous = saved_date
    latest = max(previous, saved_date)
    return {**item, "lastVisit": latest.isoformat(), "lastVisitDays": max(0, (today - latest).days)}


class VisitListing:
    """在台账排序、筛选和计算分面前补上最近走访。"""

    def __init__(self, records):
        self.records = records

    def list(self, **filters):
        result = self.records.list(**filters)
        # 空台账不打开尚未创建的原值库。旧版无快照记录继续走台账默认投影。
        if filters.get("type") != TYPE or not any("snapshot" in d["data"] for d in result["items"]):
            return result
        with visit_read() as db:
            if db is None:
                return result
            latest = {cid: date.fromisoformat(visited) for cid, visited in db.execute(
                "SELECT company, MAX(json_extract(body, '$.date')) FROM visit_notes GROUP BY company"
            )}
        today = datetime.now(BEIJING).date()
        items = []
        for doc in result["items"]:
            row = with_last_visit(doc["data"]["item"], latest.get(doc["id"]), today)
            items.append({**doc, "data": {**doc["data"], "item": row}})
        return {**result, "items": items}


def visit_listing(request, ctx):
    return ledger.companies(request, replace(ctx, records=VisitListing(ctx.records)))


def visit_detail(company_id, ctx, *, summary=False):
    summary = summary or ledger.denied(ctx)
    company = document(ctx, company_id)
    private = visit_read() if "snapshot" in company["data"] else nullcontext()
    with private as db:
        if db is not None:
            rows = db.execute("SELECT body FROM visit_notes WHERE company = ? ORDER BY rowid DESC", (company_id,))
            visits = [json.loads(row[0]) for row in rows]
            proposals = pending(db, ctx, company)
        else:
            visits, proposals = [], []

    row = item(company)
    if visits:
        latest = max(date.fromisoformat(v["date"]) for v in visits)
        row = with_last_visit(row, latest, datetime.now(BEIJING).date())
    result = {"item": row, "visits": [visit_view(v, summary) for v in visits],
              "proposals": [proposal_view(p, summary=summary) for p in proposals],
              "issues": [], "files": [], "history": []}
    if summary:
        result["item"] = company_summary(row)
        return result
    result["visits"].extend(ledger.related(ctx, "visit", company_id))
    result["proposals"].extend(p for p in ledger.related(ctx, "proposal", company_id) if p.get("status") == "pending")
    result["issues"] = requests.listing(entId=company_id, ctx=ctx)["items"]
    result["files"] = ledger.related(ctx, "file", company_id)
    for version in range(company["version"], 1, -1):
        change = document(ctx, company_id, version)["data"].get("change")
        if change:
            result["history"].append(change)
    return result


class VisitDecisionWrite:
    """先登记私库中将要发布的快照，core 的条件写入是决定的提交点。"""

    def __init__(self, records, db, proposal):
        self.records = records
        self.db = db
        self.proposal = proposal

    def save(self, **body):
        data = body["data"]
        field = self.proposal["field"]
        data["change"].update(field=field, old=public_value(field, self.proposal["old"]),
                              new=public_value(field, self.proposal["new"]), source="走访记录",
                              proposalId=self.proposal["id"], visitId=self.proposal["visitId"])
        # #32 已持久化新快照但尚未发布快照 ID。若 core 写入失败，预登记不生效；
        # 若 core 已提交但进程中断，读端仍能从目标版本的快照引用恢复已接受状态。
        with self.db:
            self.db.execute("""UPDATE visit_proposals SET accepted_version = ?, accepted_snapshot = ?
                               WHERE id = ?""",
                            (body["baseVersion"] + 1, data["snapshot"], self.proposal["id"]))
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
            if not has_proposal_state(db):
                init_tables(db)
            row = db.execute("""SELECT body, status, accepted_version, accepted_snapshot
                                FROM visit_proposals WHERE id = ?""", (proposal_id,)).fetchone()
        if row is None:
            raise DataError("not_found", "更新建议不存在")
        raw_body, status, accepted_version, accepted_snapshot = row
        proposal = json.loads(raw_body)
        company_id = proposal["entId"]
        company = document(ctx, company_id)
        if status == "legacy":
            return ledger.error(409, "LOCKED", "旧格式的更新建议需重新提取后确认")
        if status == "rejected" or was_accepted(ctx, company, accepted_version, accepted_snapshot):
            return ledger.error(409, "LOCKED", "更新建议已经处理")

        if decision == "reject":
            with db:
                db.execute("UPDATE visit_proposals SET status = 'rejected' WHERE id = ?", (proposal_id,))
            status = "rejected"
        else:
            field = proposal["field"]
            raw = original(db, company)
            if (field_value(raw, field) != proposal["old"]
                    or (field == "revenue.value" and raw["revenue"].get("unit") != proposal["unit"])):
                return ledger.error(409, "STALE_VERSION", "台账字段已修改，请重新核对建议")
            try:
                if "value" in body:
                    value = normalize(field, body["value"])
                    proposal["new"] = apply_candidate(field, proposal["old"], value)
                writer_ctx = replace(ctx, records=VisitDecisionWrite(ctx.records, db, proposal))
                write(writer_ctx, db, field_change(raw, field, proposal["new"]), names_by_id(ctx), company)
                company = document(ctx, company_id)
            except Duplicate as exc:
                return ledger.error(409, "DUPLICATE", str(exc))
            except ValueError as exc:
                return ledger.error(400, "INVALID_REQUEST", str(exc))
            status = "accepted"

        remaining = len(pending(db, ctx, company))

    ctx.audit("enterprise.proposal." + decision, {"proposalId": proposal_id, "companyId": company_id})
    return {"item": proposal_view(proposal, status), "pending": remaining}


def visit_extractor():
    """由实例提供受控提取器，默认使用进程内模拟。"""
    return MOCK_EXTRACTOR


@router.get("/companies")
def get_companies(request: Request, ctx=Depends(app_context)):
    return visit_listing(request, ctx)


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
