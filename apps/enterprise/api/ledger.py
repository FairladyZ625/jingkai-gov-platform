"""供 #29 企业 router.include_router 使用的 §4.2 台账接口。"""
import csv
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import DataError, PermissionDenied, app_context

from . import ledger_csv
from .company import Duplicate, InvalidRow, has_alert
from .ledger_store import (BEIJING, PROJECT, document, documents, item, names_by_id,
                           original, snapshots, write)

class LedgerRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route(request):
            try:
                return await handler(request)
            except DataError as exc:
                return error(exc.status, exc.code.upper(), str(exc))
            except PermissionDenied as exc:
                return error(403, "FORBIDDEN", str(exc), {"app": exc.app_id, "need": exc.action})
            except HTTPException as exc:
                if exc.status_code == 401:
                    return error(401, "UNAUTHENTICATED", "请先登录")
                raise
        return route


router = APIRouter(route_class=LedgerRoute)


def error(status, code, message, details=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)


def denied(ctx):
    return "partner" in ctx.user.roles or not ctx.can("operate")


def forbidden(ctx):
    ctx.audit("enterprise.denied", {"need": "operate"})
    return error(403, "FORBIDDEN", "无权修改企业台账", {"app": "enterprise", "need": "operate"})


RELATED_FIELDS = ("id", "entId", "status", "title", "due", "type")


def related(ctx, kind, company_id=None):
    # #33/#34 按项目提供可对外展示的关联记录；此处只透出约定字段，自由文本由其模块投影。
    docs = ctx.records.list(project=PROJECT, type="enterprise." + kind)["items"]
    rows = []
    for doc in docs:
        payload = doc.get("data", {}).get("item") or {}
        if company_id is not None and payload.get("entId") != company_id:
            continue
        rows.append({key: payload[key] for key in RELATED_FIELDS if key in payload} | {"id": doc["id"]})
    return rows


@router.get("/companies")
def companies(request: Request, ctx=Depends(app_context)):
    query = request.query_params
    docs = documents(ctx)
    sort = query.get("sort", "lastVisit")
    if sort not in {"name", "lastVisit", "revenue"}:
        return error(400, "INVALID_REQUEST", "不支持该排序字段")
    rows = [item(doc) for doc in docs]
    if sort == "revenue" and docs and not denied(ctx):
        def revenue(pair):
            try:
                return float(original(db, pair[0]).get("revenue", {}).get("value", 0) or 0)
            except (TypeError, ValueError):
                return 0
        with snapshots(writing=False) as db:
            rows = [row for _, row in sorted(zip(docs, rows), key=revenue, reverse=True)]
    elif sort == "name" or (sort == "revenue" and denied(ctx)):
        # partner / 只读角色只能按已公开字段排，避免用私库原值暴露营收高低。
        rows.sort(key=lambda row: (str(row.get("revenue", {}).get("value", "")), row["name"]))
        if sort == "name":
            rows.sort(key=lambda row: row["name"])
    elif sort == "lastVisit":
        rows.sort(key=lambda row: row.get("lastVisitDays", 0), reverse=True)
    today = datetime.now(BEIJING).date()
    alerts = set()
    if query.get("alert") == "1":
        cutoff = (today + timedelta(days=5)).isoformat()
        alerts = {issue["entId"] for issue in related(ctx, "issue") if
                  issue.get("status") != "已办结" and "due" in issue and issue["due"] < cutoff}

    def matches(row):
        terms = [row.get(k, "") for k in ("name", "short", "creditCode", "industry")]
        terms.extend(row.get("formerNames", []))
        terms.extend(row.get("tags", []))
        return (any(query.get("q", "").casefold() in term.casefold() for term in terms)
                and query.get("industry", "") in row.get("industry", "")
                and (not query.get("tag") or query["tag"] in row.get("tags", []))
                and all(not query.get(k) or query[k] == row.get(k) for k in ("scale", "servicer"))
                and (query.get("alert") != "1" or row["id"] in alerts or has_alert(row, today)))

    rows = list(filter(matches, rows))
    facets = {
        "industries": sorted({r["industry"].split(" · ")[0] for r in rows if r.get("industry")}),
        "tags": sorted({t for r in rows for t in r.get("tags", [])}),
        "servicers": sorted({r["servicer"] for r in rows if r.get("servicer")}),
    }
    return {"items": rows, "total": len(rows), "facets": facets}


@router.get("/companies/{company_id}")
def detail(company_id: str, ctx=Depends(app_context)):
    doc = document(ctx, company_id)
    history = [document(ctx, company_id, v)["data"].get("change") for v in range(doc["version"], 1, -1)]
    return {"item": item(doc), "history": [change for change in history if change],
            "visits": related(ctx, "visit", company_id), "issues": related(ctx, "issue", company_id),
            "files": related(ctx, "file", company_id),
            "proposals": [p for p in related(ctx, "proposal", company_id) if p.get("status") == "pending"]}


def save(ctx, changes, company_id=None):
    if denied(ctx):
        return forbidden(ctx)
    if not isinstance(changes, dict) or not changes:
        return error(400, "INVALID_REQUEST", "企业字段不能为空")
    with snapshots(writing=True) as db:
        previous = document(ctx, company_id) if company_id else None
        try:
            return {"item": write(ctx, db, changes, names_by_id(ctx), previous)}
        except Duplicate as exc:
            return error(409, "DUPLICATE", str(exc))
        except InvalidRow as exc:
            return error(400, "INVALID_REQUEST", str(exc))


@router.post("/companies")
def create(changes: dict = Body(default=None), ctx=Depends(app_context)):
    return save(ctx, changes)


@router.patch("/companies/{company_id}")
def update(company_id: str, changes: dict = Body(default=None), ctx=Depends(app_context)):
    return save(ctx, changes, company_id)


@router.post("/import")
def import_companies(body: dict, ctx=Depends(app_context)):
    if denied(ctx):
        return forbidden(ctx)
    if isinstance(body.get("csv"), str):
        try:
            rows = list(ledger_csv.rows(body["csv"]))
        except ledger_csv.UnrecoverableCsv as exc:
            return error(400, "INVALID_REQUEST", str(exc))
        except (InvalidRow, csv.Error):
            return error(400, "INVALID_REQUEST", "CSV 表头无效")
    elif isinstance(body.get("rows"), list):
        rows = [(n, row, None) for n, row in enumerate(body["rows"], 1)]
    else:
        return error(400, "INVALID_REQUEST", "请提供 csv 文本或 rows 数组")
    items, errors = [], []
    with snapshots(writing=True) as db:
        names = names_by_id(ctx)
        for number, row, reason in rows:
            try:
                if reason or not isinstance(row, dict):
                    raise InvalidRow(reason or "行必须为对象")
                items.append(write(ctx, db, row, names))
            except InvalidRow as exc:
                errors.append({"row": number, "reason": str(exc)})
    return {"added": len(items), "items": items, "errors": errors}


@router.get("/export")
def export(ids: str | None = None, ctx=Depends(app_context)):
    selected = set(ids.split(",")) if ids is not None else None
    items = [item(doc) for doc in documents(ctx) if selected is None or doc["id"] in selected]
    ctx.audit("enterprise.export", {"count": len(items)})
    return ledger_csv.render(items)
