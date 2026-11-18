"""公文协作 §4.4 API。"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import AppContext, DataError, PermissionDenied, app_context, require
from pydantic import BaseModel, Field, StringConstraints

from . import drafts, templates

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


class DraftIn(BaseModel):
    templateId: Text
    inputs: dict[str, str | None]
    refs: list[Reference] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)


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


router = APIRouter(route_class=DocumentRoute)


@router.get("/templates")
def list_templates(ctx: Viewer):
    return templates.catalogue()


@router.get("/documents")
def list_documents(ctx: Viewer):
    return {"items": drafts.summaries(ctx)}


@router.post("/drafts")
def create_draft(body: DraftIn, ctx: Operator, request: Request):
    spec = templates.draft_template(body.templateId, body.inputs)
    platform = request.app.state.platform
    platform.data.projects.require(ctx.user, drafts.PROJECT)
    content = templates.mock_draft(spec, body.inputs, body.extra)
    citations = drafts.resolve_citations(getattr(platform, "kb", None), ctx.user, body.refs, content)
    policy_id = (body.inputs.get("policy") or "").strip() or None
    drafts.install_lock(platform)
    return {"item": drafts.create(ctx, body.templateId, policy_id, content, citations)}


@router.get("/drafts/{identity}")
def get_draft(identity: str, ctx: Viewer, version: Annotated[int | None, Query(ge=0)] = None):
    return {"item": drafts.get(ctx, identity, version)}


@router.put("/drafts/{identity}")
def save_draft(identity: str, body: SaveIn, ctx: Operator, request: Request):
    drafts.install_lock(request.app.state.platform)
    return {"item": drafts.save(ctx, identity, body.content.model_dump(), body.note)}


# #11 的实例路由应优先登记此路由，防止 core 通用记录写入口绕过公文校验和定稿锁。
records_guard = APIRouter(prefix="/api/v1/apps/document")


@records_guard.post("/records", include_in_schema=False)
@records_guard.put("/records/{identity}", include_in_schema=False)
def use_document_routes():
    return error(405, "METHOD_NOT_ALLOWED", "请使用公文草稿接口写入文稿")
