"""告知单与政策对话工具的应用路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, PermissionDenied, app_context
from pydantic import BaseModel, Field, StringConstraints

from .policy_cards import items_card, match_card
from .policy_catalog import catalog, enterprise_profile, item_with_doc, list_items
from .policy_notice import build_notice
from .policy_routes import PolicyRequestError, PolicyRoute, match


router = APIRouter(route_class=PolicyRoute)
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class NoticeRequest(BaseModel):
    entId: Identifier
    itemIds: list[Identifier] = Field(min_length=1)


def notice_operator(ctx: AppContext = Depends(app_context)) -> AppContext:
    if not ctx.can("operate"):
        ctx.audit("notice.denied", {"need": "operate"})
        raise PermissionDenied(ctx.app_id, "operate")
    return ctx


@router.post("/notice")
def notice(body: NoticeRequest, ctx: AppContext = Depends(notice_operator)):
    if enterprise_profile(body.entId) is None:
        raise PolicyRequestError(404, "NOT_FOUND", "企业不存在")
    items, docs = catalog()
    selected = []
    for item_id in dict.fromkeys(body.itemIds):
        if item_id not in items:
            raise PolicyRequestError(404, "NOT_FOUND", "事项不存在")
        item = items[item_id]
        selected.append(item_with_doc(item, docs[item["doc"]]))
    result = build_notice(body.entId, selected)
    ctx.audit("notice.preview", {"entId": body.entId, "itemIds": [item["id"] for item in selected]})
    return result


@router.post("/tools/match", dependencies=[Depends(app_context)])
def match_tool(body: dict):
    result = match(body)
    if "entId" in body:
        result["cards"] = [match_card(body["entId"], result["results"])]
    return result


@router.get("/tools/search", dependencies=[Depends(app_context)])
def search_tool(q: str = ""):
    result = list_items(q, "", "")
    return {**result, "cards": [items_card(result["items"])]}
