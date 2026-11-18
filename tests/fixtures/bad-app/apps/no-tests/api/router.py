from fastapi import APIRouter, Depends

from haiknow_sdk import AppContext, app_context

router = APIRouter()


@router.get("/hello")
def hello(ctx: AppContext = Depends(app_context)):
    return {"app": ctx.app_id}