"""§4.1 政策业务路由，交由 #29 的 apps/policy/api/router.py 挂载。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from haiknow_sdk import PermissionDenied, app_context

from .policy_calc import estimate, positive_amount
from .policy_catalog import WINDOWS, catalog, enterprise_profile, item_with_doc, list_items
from .policy_match import match_items


class PolicyRequestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _error(status: int, code: str, message: str, **details):
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


class PolicyRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def policy_handler(request: Request):
            try:
                return await handle(request)
            except PolicyRequestError as exc:
                return _error(exc.status, exc.code, exc.message)
            except RequestValidationError:
                return _error(400, "INVALID_REQUEST", "请提供有效的 JSON 请求对象")
            except PermissionDenied as exc:
                return _error(403, "FORBIDDEN", "无权查看此应用", app=exc.app_id, need=exc.action)
            except HTTPException as exc:
                if exc.status_code == 401:
                    return _error(401, "UNAUTHENTICATED", "未登录")
                raise

        return policy_handler


router = APIRouter(route_class=PolicyRoute, dependencies=[Depends(app_context)])


def _item(item_id: object) -> dict:
    items, docs = catalog()
    if not isinstance(item_id, str) or not item_id:
        raise PolicyRequestError(400, "INVALID_REQUEST", "请提供事项编号")
    item = items.get(item_id)
    if item is None:
        raise PolicyRequestError(404, "NOT_FOUND", "事项不存在")
    return item_with_doc(item, docs[item["doc"]])


@router.get("/items")
def items(q: str = "", object: str = "", window: str = ""):
    if window and window not in WINDOWS:
        raise PolicyRequestError(400, "INVALID_REQUEST", "申报窗口须为 open、ended 或 unknown")
    return list_items(q, object, window)


@router.get("/items/{item_id}")
def detail(item_id: str):
    return {"item": _item(item_id)}


@router.post("/match")
def match(body: dict):
    if "entId" in body and "profile" not in body:
        ent_id = body["entId"]
        overrides = body.get("overrides", {})
        if not isinstance(ent_id, str) or not ent_id or not isinstance(overrides, dict):
            raise PolicyRequestError(400, "INVALID_REQUEST", "请提供企业编号和有效的覆盖字段")
        profile = enterprise_profile(ent_id)
        if profile is None:
            raise PolicyRequestError(404, "NOT_FOUND", "企业不存在")
        profile.update(overrides)
    elif isinstance(body.get("profile"), dict) and "entId" not in body and "overrides" not in body:
        profile = body["profile"]
    else:
        raise PolicyRequestError(400, "INVALID_REQUEST", "请提供企业编号或手动画像")
    try:
        json.dumps(profile, allow_nan=False)
    except ValueError as exc:
        raise PolicyRequestError(400, "INVALID_REQUEST", "画像字段须使用有限数字") from exc
    data, docs = catalog()
    items = (item_with_doc(item, docs[item["doc"]]) for item in data.values())
    return match_items(profile, items, estimate_item=estimate)


@router.post("/calc")
def calc(body: dict):
    item = _item(body.get("itemId"))
    amount = body.get("amount")
    if not positive_amount(amount):
        raise PolicyRequestError(400, "INVALID_REQUEST", "金额须为大于零的有限数字")
    rule = item["rule"]
    result = estimate(rule, amount)
    if result is None and not rule.get("manual") and rule.get("base") and "ratio" in rule:
        raise PolicyRequestError(400, "INVALID_REQUEST", "该金额无法按事项规则试算")
    note = (
        "历史规则试算，仅用于回顾，当前申报以现行政策为准"
        if item.get("historical") or item["times"]["valid"].startswith("已替代")
        else "实际金额以评审结果为准" if result is not None else "请按条款与申报指南人工核算"
    )
    return {"item": item["id"], "rule": rule["text"], "result": result, "note": note}
