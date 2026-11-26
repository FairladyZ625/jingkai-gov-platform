"""公文协作 §4.4 API。"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import AppContext, DataError, PermissionDenied, app_context, require
from pydantic import BaseModel, Field, StringConstraints

from . import comments, drafts, policy_draft, templates

ERROR_STATUSES = {"invalid_request": 400, "locked": 409, "app_unavailable": 503}


def error(status, code, message, **details):
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


class DocumentRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def checked(request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                fields = [list(item["loc"]) for item in exc.errors()]
                return error(400, "INVALID_REQUEST", "请求字段缺失或类型不正确", fields=fields)
            except PermissionDenied as exc:
                platform = request.app.state.platform
                platform.store.audit(exc.app_id, request.session.get("uid"), "document.denied", {"need": exc.action})
                message = "无权查看此应用" if exc.action == "view" else "没有公文操作权限"
                return error(403, "FORBIDDEN", message, app=exc.app_id, need=exc.action)
            except DataError as exc:
                details = {k: v for k, v in exc.error.items() if k not in ("code", "message", "retryable")}
                return error(ERROR_STATUSES.get(exc.code, exc.status), exc.code.upper(), str(exc), **details)
            except HTTPException as exc:
                if exc.status_code != 401:
                    raise
                return error(401, "UNAUTHENTICATED", "未登录")

        return checked


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Viewer = Annotated[AppContext, Depends(app_context)]
Operator = Annotated[AppContext, Depends(require("operate"))]


class Reference(BaseModel):
    id: Text


class MeetingSource(BaseModel):
    app: Literal["meeting"]
    id: Text
    version: Annotated[int, Field(strict=True, ge=1)]


class DraftIn(BaseModel):
    templateId: Text
    inputs: dict[str, str | None]
    refs: list[Reference] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)
    source: MeetingSource | None = None


class Content(BaseModel):
    title: Text
    docNo: str
    to: str
    paragraphs: list[str]
    sign: str
    date: str


class SaveIn(BaseModel):
    content: Content
    note: str = ""
    baseVersion: Annotated[int, Field(strict=True, ge=0)] | None = None


router = APIRouter(route_class=DocumentRoute)


@router.get("/templates")
def list_templates(ctx: Viewer):
    return templates.catalogue()


@router.get("/documents")
def list_documents(ctx: Viewer):
    items = drafts.summaries(ctx)
    groups = comments.by_draft(ctx)
    for entry in items:
        entry["comments"] = sum(not c["resolved"] for c in groups.get(entry["id"], []))
    return {"items": items}


def _with_comments(ctx, draft):
    return {**draft, "comments": comments.by_draft(ctx).get(draft["id"], [])}


@router.post("/drafts")
def create_draft(body: DraftIn, ctx: Operator, request: Request):
    platform = request.app.state.platform
    platform.data.projects.require(ctx.user, drafts.PROJECT)
    source = None
    reward_notice = body.templateId == "T03"
    if body.source:
        from .workbench import meeting_content
        if body.templateId != "T02":
            raise DataError("invalid_request", "会议转公文使用工作方案模板")
        content, source = meeting_content(platform, ctx.user, body.source)
    else:
        spec = templates.draft_template(body.templateId, body.inputs)
        lookup = getattr(request.app.state, "public_policy_lookup", None)
        content = (policy_draft.reward_notice(spec, body.inputs, body.extra, lookup=lookup)
                   if reward_notice else templates.mock_draft(spec, body.inputs, body.extra))
    citations = drafts.resolve_citations(getattr(platform, "kb", None), ctx.user, body.refs, content)
    policy_id = (body.inputs.get("policy") or "").strip() or None
    return {"item": drafts.create(ctx, body.templateId, policy_id, content, citations,
                                  provider="policy-template" if reward_notice else "mock", source=source)}


@router.get("/drafts/{identity}")
def get_draft(identity: str, ctx: Viewer, version: Annotated[int | None, Query(ge=0)] = None):
    item = _with_comments(ctx, drafts.get(ctx, identity, version))
    if version is None and item["status"] == "已退回":
        # 只向提交人回显这一版本的实际退回意见，不从批注或旧审签单猜测。
        core_version = item["versions"][-1]["v"] + 1
        reviews = ctx.reviews.list(mine="submitted")["items"]
        review = next((r for r in reviews if r["recordId"] == identity and
                       r["version"] == core_version and r["status"] == "needs_info"), None)
        if review and review["decisions"]:
            item["returnReason"] = review["decisions"][-1]["comment"]
    return {"item": item}


@router.put("/drafts/{identity}")
def save_draft(identity: str, body: SaveIn, ctx: Operator):
    return {"item": _with_comments(ctx, drafts.save(ctx, identity, body.content.model_dump(), body.note, body.baseVersion))}
