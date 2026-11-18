"""对话工具注册表与应用内工具桥。对话网关调用时须传入服务端实际选定的模型。"""

from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, Request
from haiknow_sdk import DataError, app_context
from starlette.responses import Response

from . import ledger
from .visit_extraction import Destination
from .visits import add_visit, company_summary, visit_detail, visit_extractor, visit_listing

router = APIRouter(route_class=ledger.LedgerRoute)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict

    def metadata(self):
        return {"name": self.name, "app": "enterprise", "write": False,
                "description": self.description, "parameters": self.parameters}


def parameters(properties, required=()):
    return {"type": "object", "properties": {key: {"type": "string"} for key in properties},
            "required": list(required)}


TOOLS = {
    tool.name: tool for tool in (
        Tool("enterprise.search", "按关键词查企业", parameters(("q",))),
        Tool("enterprise.get", "查看企业台账", parameters(("id",), ("id",))),
        Tool("enterprise.propose_update", "根据走访随记生成待确认建议",
             parameters(("id", "notes", "type"), ("id", "notes"))),
    )
}


def tool_metadata():
    return [tool.metadata() for tool in TOOLS.values()]


def run_tool(ctx, name, args, *, destination: Destination, allowlist, extractor):
    """网关在执行前传入实际目的地，此调用不允许更换模型或回退。"""
    destination.require_allowed(allowlist)
    return execute(ctx, name, args, extractor)


def execute(ctx, name, args, extractor):
    if name not in TOOLS:
        return ledger.error(404, "TOOL_NOT_FOUND", "企业工具不存在")
    if ctx.app_id != "enterprise" or not ctx.can("view"):
        raise DataError("forbidden", "无权查看企业台账")
    if not isinstance(args, dict):
        return ledger.error(400, "INVALID_REQUEST", "工具参数必须为对象")
    if name == "enterprise.search":
        q = args.get("q", "")
        if not isinstance(q, str):
            return ledger.error(400, "INVALID_REQUEST", "搜索词必须为文本")
        request = Request({"type": "http", "query_string": urlencode({"q": q}).encode()})
        result = visit_listing(request, ctx)
        if isinstance(result, dict):
            result = {"items": [company_summary(row) for row in result["items"]], "total": result["total"]}
    else:
        company_id = args.get("id")
        if not isinstance(company_id, str) or not company_id.strip():
            return ledger.error(400, "INVALID_REQUEST", "请提供企业编号")
        result = visit_detail(company_id, ctx, summary=True) if name == "enterprise.get" else add_visit(
            ctx, company_id, args, extractor, summary=True,
        )
    if isinstance(result, Response):
        return result
    ctx.audit("enterprise.tool", {"tool": name})
    return {"tool": name, "result": result}


@router.get("/tools")
def list_tools(ctx=Depends(app_context)):
    return {"items": tool_metadata()}


@router.post("/tools/{name}")
def call_tool(name: str, body: dict = Body(default=None), ctx=Depends(app_context),
              extractor=Depends(visit_extractor)):
    # 应用内请求的接收端是登录用户。模型调用走需要目的地授权的 run_tool。
    return execute(ctx, name, (body or {}).get("args"), extractor)
