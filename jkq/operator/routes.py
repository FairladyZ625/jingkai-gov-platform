"""§3.8 操作员 HTTP 接口，由经开区实例安装。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from jkq.conversations.routes import Utf8Text

from .planning import build_plan, catalog, missing_permission
from .receipts import ReceiptError, Receipts

Identifier = Annotated[Utf8Text, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class PlanContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: Identifier | None = None
    app: Identifier | None = None
    entId: Identifier | None = None
    meetingId: Identifier | None = None
    draftId: Identifier | None = None
    templateId: Identifier | None = None


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[Utf8Text, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    context: PlanContext = Field(default_factory=PlanContext)
    model: Identifier | None = None


class StepReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Identifier
    status: Literal["done", "failed", "skipped"]
    at: AwareDatetime


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planId: Identifier
    steps: list[StepReceipt] = Field(max_length=100)
    confirmed: list[Identifier] = Field(default_factory=list, max_length=100)


def error(status, code, message, details=None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}},
                        status_code=status)


class OperatorRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def endpoint(request):
            try:
                return await handle(request)
            except ReceiptError as exc:
                return error(exc.status, exc.code, str(exc), exc.details)
            except RequestValidationError:
                return error(422, "CHECK_FAILED", "操作员请求字段缺失或格式不正确")
            except HTTPException as exc:
                if exc.status_code == 401:
                    return error(401, "UNAUTHENTICATED", "请先登录")
                raise

        return endpoint


def install(app, current_user):
    platform = app.state.platform
    receipts = Receipts(platform)
    router = APIRouter(prefix="/api/v1/operator", route_class=OperatorRoute)

    def intents_for(user):
        bridge = getattr(app.state, "apps_bridge", None)
        tools = bridge.tools(user)["items"] if bridge is not None else None
        return catalog(platform, tools)

    @router.get("/intents")
    def intents(user=Depends(current_user)):
        return {"items": [intent.summary() for intent in intents_for(user)
                          if not missing_permission(platform, user, intent.app, intent.need)]}

    @router.post("/plan")
    def plan(body: PlanBody, user=Depends(current_user)):
        result, intent = build_plan(platform, user, intents_for(user), body.text,
                                    body.context.model_dump(exclude_none=True), body.model)
        if intent is not None:
            result["planId"] = receipts.prepare(user, intent, result["steps"])
        return result

    @router.post("/runs")
    def run(body: RunBody, user=Depends(current_user)):
        return receipts.record(user, body.planId, [step.model_dump(mode="json") for step in body.steps],
                               body.confirmed)

    @router.post("/runs/{identity}/stop")
    def stop(identity: Identifier, user=Depends(current_user)):
        return receipts.stop(user, identity)

    app.include_router(router)
