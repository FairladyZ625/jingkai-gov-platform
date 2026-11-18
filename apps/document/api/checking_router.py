"""公文核查与修正的 §4.4 路由。由公文应用路由统一挂载。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from . import checks, templates
from .drafting_router import DocumentRoute, Operator, Viewer
from .drafts import _locked as locked, _present as present, _record as get_record

router = APIRouter(route_class=DocumentRoute)


class FixIn(BaseModel):
    ids: list[str]


def inspect(ctx, request, record):
    knowledge = getattr(request.app.state.platform, "kb", None)

    def lookup(identity, version):
        if knowledge is None:
            return None
        try:
            return knowledge.detail(ctx.user, identity, version)
        except Exception as exc:
            if getattr(exc, "status", None) not in (403, 404):
                raise
            return None

    kind = templates.TEMPLATES.get(record["data"]["templateId"], {}).get("kind")
    result = checks.inspect(record, kind, lookup, ctx.ai.chat)
    ctx.audit("document.check", {"recordId": record["id"], "version": record["version"],
                                 "languageStatus": result.language_check["status"]})
    return result


@router.post("/drafts/{identity}/check")
def check_draft(identity: str, ctx: Viewer, request: Request):
    return inspect(ctx, request, get_record(ctx, identity)).response()


@router.post("/drafts/{identity}/fix")
def fix_draft(identity: str, body: FixIn, ctx: Operator, request: Request):
    current = get_record(ctx, identity)
    if current["status"] == "confirmed":
        raise locked()
    findings = inspect(ctx, request, current)
    data = current["data"]
    content, citations, ignored, unfixable = checks.apply(data, findings, body.ids)
    if content != data["content"] or citations != data["citations"]:
        # 用产生问题的版本做写入前置条件，避免覆盖并发编辑。
        current = ctx.records.save(id=identity, baseVersion=current["version"], data={
            **data, "by": f"{ctx.user.name}（一键修正）", "content": content, "citations": citations,
        })
        findings = inspect(ctx, request, current)
    return {"item": present(ctx, current), **findings.response(),
            "ignoredIds": ignored, "unfixableIds": unfixable}
