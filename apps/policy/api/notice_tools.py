"""告知单与政策对话工具的应用路由。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, PermissionDenied, app_context
from pydantic import BaseModel, Field, StringConstraints

from .policy_cards import items_card, match_card
from .policy_catalog import catalog, enterprise_profile, item_with_doc, list_items
from .policy_notice import build_notice
from .policy_routes import PolicyRequestError, PolicyRoute, match


router = APIRouter(route_class=PolicyRoute)
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TrialAmount = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class NoticeProfile(BaseModel):
    subjectType: Literal["企业", "个人", "其他组织"]


class NoticeRequest(BaseModel):
    entId: Identifier | None = None
    profile: NoticeProfile | None = None
    itemIds: list[Identifier] = Field(min_length=1)
    amounts: dict[Identifier, TrialAmount | None] = Field(default_factory=dict)


def notice_operator(ctx: AppContext = Depends(app_context)) -> AppContext:
    if not ctx.can("operate"):
        ctx.audit("notice.denied", {"need": "operate"})
        raise PermissionDenied(ctx.app_id, "operate")
    return ctx


@router.post("/notice")
def notice(body: NoticeRequest, ctx: AppContext = Depends(notice_operator)):
    if (body.entId is None) == (body.profile is None):
        raise PolicyRequestError(400, "INVALID_REQUEST", "请提供企业编号或手动画像，不能同时提供")
    if body.entId is not None and enterprise_profile(body.entId) is None:
        raise PolicyRequestError(404, "NOT_FOUND", "企业不存在")
    items, docs = catalog()
    selected = []
    for item_id in dict.fromkeys(body.itemIds):
        if item_id not in items:
            raise PolicyRequestError(404, "NOT_FOUND", "事项不存在")
        item = items[item_id]
        selected.append(item_with_doc(item, docs[item["doc"]]))
    result = build_notice(body.entId, selected, subject_type=body.profile.subjectType if body.profile else None,
                          amounts=body.amounts)
    ctx.audit("notice.preview", {"entId": body.entId, "itemIds": [item["id"] for item in selected]})
    return result


@router.post("/tools/match")
def match_tool(body: dict, ctx: AppContext = Depends(app_context)):
    result = match(body, ctx)
    if "entId" in body:
        result["cards"] = [match_card(body["entId"], result["results"])]
    return result


@router.get("/tools/search", dependencies=[Depends(app_context)])
def search_tool(q: str = ""):
    result = list_items(q, "", "")
    return {**result, "cards": [items_card(result["items"])]}
