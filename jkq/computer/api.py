"""电脑操作 HTTP 入口，复用实例会话、RBAC 和审计。"""

from contextlib import asynccontextmanager
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from starlette.exceptions import HTTPException

from .browser import PlaywrightRunner
from .runs import ComputerError, PREFIX, Runs, TASKS


APP_ID = "computer"
HTTP_STATUS = {
    "UNAUTHENTICATED": 401, "FORBIDDEN": 403, "NOT_FOUND": 404, "LOCKED": 409,
    "CHECK_FAILED": 422, "OUTBOUND_DENIED": 403, "QUOTA_EXCEEDED": 429,
}
KIND_ALIASES = {"captcha": "otp", "验证码": "otp", "签章": "sign", "付款": "pay", "提交": "submit", "入库": "import"}


class ComputerRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await handler(request)
            except ComputerError as exc:
                error = exc
            except RequestValidationError:
                error = ComputerError("CHECK_FAILED", "请求内容未通过校验")
            except HTTPException as exc:
                if exc.status_code != 401:
                    raise
                error = ComputerError("UNAUTHENTICATED", "请先登录")
            return JSONResponse({"error": error.error}, status_code=HTTP_STATUS[error.error["code"]])

        return handle


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SystemBody(Body):
    allowed: StrictBool


class MatchBody(Body):
    text: str = Field(min_length=1, max_length=1000)


class StartBody(Body):
    task: str = Field(min_length=1, max_length=32)
    ent: str | None = Field(default=None, pattern=r"^E[0-9]{3,12}$")
    month: str | None = Field(default=None, max_length=24)
    source: Literal["", "ui", "operator", "chat", "api"] = Field(default="", alias="from")

    @field_validator("ent", mode="before")
    @classmethod
    def normalize_ent(cls, value):
        # 现有前端在未选择企业时仍会传空字符串。
        return None if value == "" else value


class ConfirmBody(Body):
    decision: Literal["approve", "decline"]
    kind: str | None = Field(default=None, max_length=16)


class ReportBody(BaseModel):
    # 接收规范中的字段，以便明确拒绝由用户修改服务端证据。
    model_config = ConfigDict(extra="allow")
    status: Literal["stopped"] | None = None


def create_router(runs: Runs, current_user, current_actions) -> APIRouter:
    router = APIRouter(prefix=PREFIX, route_class=ComputerRoute)

    def require(action: str):
        def authorize(request: Request, user=Depends(current_user)):
            if "partner" in user.roles or action not in current_actions(request, user):
                need = action
                reason = "partner" if "partner" in getattr(user, "roles", ()) else "missing_action"
                runs.audit(user.id, "computer.denied",
                           {"app": APP_ID, "need": need, "reason": reason})
                raise ComputerError("FORBIDDEN", "当前角色没有电脑操作权限",
                                    details={"app": APP_ID, "need": need})
            return user

        return Depends(authorize)

    view = require("view")
    operate = require("operate")
    admin = require("admin")

    @router.get("/tasks")
    async def tasks(user=view):
        return {"items": list(TASKS.values()), "systems": runs.systems()}

    @router.patch("/systems/{system_id}")
    async def update_system(system_id: str, body: SystemBody, user=admin):
        return {"item": runs.set_allowed(user.id, system_id, body.allowed)}

    @router.post("/match")
    async def match(body: MatchBody, user=view):
        # 先匹配通知，避免「申报通知」被申报填表抢走。
        task = next((item for item in (TASKS["notice"], TASKS["apply"])
                     if any(word in body.text for word in item["keywords"])), None)
        ent = re.search(r"(?<![A-Za-z0-9])E[0-9]{3,12}(?![A-Za-z0-9])", body.text)
        return {"task": task, "entId": ent[0] if ent else None}

    @router.get("/runs")
    async def list_runs(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        user=view,
    ):
        return runs.list(user.id, limit, offset)

    @router.post("/runs", status_code=202)
    async def start_run(
        request: Request,
        body: StartBody,
        key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=200)] = None,
        user=operate,
    ):
        def can_operate() -> bool:
            # 每次在浏览器动作前重新验证原会话及当前角色授权。
            try:
                actor = current_user(request)
            except HTTPException:
                return False
            return (actor.id == user.id and "partner" not in actor.roles
                    and "operate" in current_actions(request, actor))

        run = runs.start(user.id, user.name, body.model_dump(by_alias=True), key, can_operate)
        return {"item": run.snapshot()}

    @router.get("/runs/{run_id}")
    async def get_run(run_id: str, user=view):
        return {"item": runs.get(user.id, run_id).snapshot()}

    @router.patch("/runs/{run_id}")
    async def report(run_id: str, body: ReportBody, user=operate):
        run = runs.get(user.id, run_id)
        if body.model_extra or body.status != "stopped":
            raise ComputerError("FORBIDDEN", "步骤状态、截图和日志由服务端运行器写入")
        run.stop("经办人停止电脑操作")
        return {"item": run.snapshot(detail=False)}

    @router.post("/runs/{run_id}/confirm")
    async def confirm(run_id: str, body: ConfirmBody, user=operate):
        run = runs.get(user.id, run_id)
        run.confirm(body.decision, KIND_ALIASES.get(body.kind, body.kind))
        return {"item": run.snapshot(detail=False)}

    return router


def install(app, current_user, *, url: str, channel: str | None = None) -> None:
    """在经开区实例配置了本地模拟站时挂载，需在应用启动前调用。"""
    platform = app.state.platform
    runner = PlaywrightRunner(url, channel=channel)
    runs = Runs(runner.url, runner, lambda uid, action, detail: platform.store.audit(
        APP_ID, uid, action, {**detail, "via": "computer"},
    ))
    app.include_router(create_router(runs, current_user, lambda _, user: platform.rbac.actions(user, APP_ID)))
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with previous(instance) as state:
            try:
                yield state
            finally:
                await runs.close()

    app.router.lifespan_context = lifespan
