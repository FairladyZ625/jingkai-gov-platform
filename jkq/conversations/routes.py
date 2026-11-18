from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel

from .store import ConversationNotFound, ConversationStore


class Panel(BaseModel):
    app: str
    route: str
    params: dict[str, Any]


class NewConversation(BaseModel):
    title: str = "新对话"
    app: str | None = None
    panel: Panel | None = None


class PanelUpdate(BaseModel):
    panel: Panel | None


def error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message, "details": {}}},
                        status_code=status)


class ConversationRoute(APIRoute):
    """仅在本路由组适配 §1 的错误格式。"""
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def endpoint(request):
            try:
                return await handle(request)
            except ConversationNotFound:
                return error(404, "NOT_FOUND", "会话不存在")
            except RequestValidationError:
                return error(422, "CHECK_FAILED", "请求字段缺失或格式不正确")
            except HTTPException as exc:
                if exc.status_code == 401:
                    return error(401, "UNAUTHENTICATED", "请先登录")
                raise

        return endpoint


def install(app, plat, current_user):
    store = ConversationStore(plat.store)
    router = APIRouter(prefix="/api/v1/conversations", route_class=ConversationRoute)

    @router.post("")
    def create(body: NewConversation, user=Depends(current_user)):
        return {"item": store.create(user.id, **body.model_dump())}

    @router.get("")
    def history(limit: int = Query(50, ge=0, le=2**63-1),
                offset: int = Query(0, ge=0, le=2**63-1), user=Depends(current_user)):
        return store.history(user.id, limit, offset)

    @router.get("/{cid}")
    def detail(cid: str, user=Depends(current_user)):
        return store.detail(user.id, cid)

    @router.patch("/{cid}")
    def panel(cid: str, body: PanelUpdate, user=Depends(current_user)):
        return {"item": store.set_panel(user.id, cid, body.model_dump()["panel"])}

    @router.delete("/{cid}", status_code=204)
    def remove(cid: str, user=Depends(current_user)):
        store.set_deleted(user.id, cid, deleted=True)
        return Response(status_code=204)

    @router.post("/{cid}/restore")
    def restore(cid: str, user=Depends(current_user)):
        return {"item": store.set_deleted(user.id, cid, deleted=False)}

    app.include_router(router)
    return store
