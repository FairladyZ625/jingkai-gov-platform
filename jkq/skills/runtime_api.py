"""§3.7 运行、起草、匹配接口。实例入口在 CRUD 安装后调用 install。"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi import APIRouter, Depends, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from haiknow_core.jobs.service import JobService
from haiknow_sdk import DataError

from .api import SkillRoute
from .drafting import draft, match, request_text
from .runtime import execute, prepare_skill, step_label
from .runtime_provider import SkillProvider
from .spec import SkillError, invalid

APP = "skills"
PROJECT = "jkq"
OPERATION = "skill.execute"
OPERATION_VERSION = "2"


def require_utf8_json(value):
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        invalid("技能请求须可编码为 UTF-8 JSON，数字须为有限值")


class RuntimeRoute(SkillRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def dispatch(request):
            try:
                return await handle(request)
            except RequestValidationError:
                return JSONResponse(
                    {"error": {"code": "INVALID_REQUEST", "message": "请求格式无效", "details": {}}},
                    status_code=400,
                )

        return dispatch


class JobPlatform:
    """把 core 队列绑定到技能工作区，沿用当前用户和技能中心授权。"""

    def __init__(self, skills):
        self.skills = skills
        self.store = skills.store
        self.rbac = skills.platform.rbac
        self.data = SimpleNamespace(app=self.authorize, projects=skills.records.projects)
        self.apps = {}

    def authorize(self, user, app_id, action="view"):
        try:
            self.skills.records.app(user, app_id, action)
        except SkillError as exc:
            raise DataError(exc.error["code"].lower(), str(exc), **exc.error["details"]) from exc

    def resolve(self, request):
        directory = self.skills.platform.directory
        uid = request.session["uid"]
        user = directory.session_user(uid, directory.session_gen(uid))
        if user is None:
            raise DataError("unauthenticated", "任务提交人已不可用")
        return SimpleNamespace(user=user)


class SkillJobService(JobService):
    def _save(self, doc, action, *, actor=None):
        super()._save(doc, action, actor=actor)
        # SkillStore 已附接平台库。队列状态和元数据审计在同一事务提交。
        self.store._db.execute(
            "INSERT INTO platform.audit(ts, app_id, user_id, action, detail) "
            "SELECT ts, app_id, user_id, action, detail FROM main.audit WHERE id=last_insert_rowid()"
        )


def runnable_skill(skills, user, sid):
    item = skills.load(user, sid)["data"]
    actions = skills.platform.rbac.actions(user, APP)
    if item["authorId"] != user.id and "admin" not in actions and (
        item["status"] != "published" or item["share"]["perm"] not in ("use", "edit")
    ):
        raise SkillError(403, "FORBIDDEN", "没有该技能的运行权限")
    return item


def job_view(job):
    payload = job["input"]
    checkpoints = {step["name"]: step for step in job["steps"]}
    steps = []
    for index, step in enumerate(payload["skill"]["spec"]["steps"]):
        checkpoint = checkpoints.get(f"{index + 1}:{step['type']}", {})
        state = checkpoint.get("status", "pending")
        if state == "done" and (checkpoint.get("result") or {}).get("skipped"):
            state = "skipped"
        steps.append({"label": step_label(step), "type": step["type"],
                      "status": "run" if state == "running" else state})
    status = {"queued": "running", "cancelling": "running", "cancelled": "failed"}.get(
        job["status"], job["status"]
    )
    message = job["error"]["message"] if job["error"] else None
    if job["status"] == "cancelled":
        message = "任务已取消"
    return {"id": job["id"], "status": status, "steps": steps, "result": job["result"],
            "trial": payload["ref"] is None, "error": message,
            "errorCode": job["error"]["code"].upper() if job["error"] else None}


def install(app, current_user, *, provider=None):
    skills = app.state.skills
    if provider is None:
        provider = SkillProvider(app)
    jobs = SkillJobService(JobPlatform(skills), app)
    router = APIRouter(prefix="/api/v1/skills", route_class=RuntimeRoute)

    def operation(execution, payload):
        user = execution.context.user

        def authorize():
            current = skills.platform.directory.user(user.id)
            if current is None:
                raise SkillError(401, "UNAUTHENTICATED", "任务提交人已不可用")
            skills.records.app(current, APP, "operate")
            if payload["ref"] is not None:
                runnable_skill(skills, current, payload["ref"])
            return current

        try:
            return execute(execution, payload["skill"], payload["inputs"], user, provider, authorize)
        except SkillError as exc:
            raise DataError(exc.error["code"].lower(), str(exc), **exc.error["details"]) from exc

    jobs.operations[(APP, OPERATION)] = (OPERATION_VERSION, operation)
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with previous(instance) as state:
            jobs.start()
            try:
                yield state
            finally:
                await asyncio.to_thread(jobs.stop)

    def visible_job(user, job):
        if job["result"] is not None:
            if job["version"] != OPERATION_VERSION:
                raise SkillError(409, "INVALID_STATE", "该任务结果由旧版运行时生成，请重新运行")
            tools = [checkpoint["result"]["access"] for checkpoint in job["steps"]
                     if (checkpoint.get("result") or {}).get("access")]
            provider.require_sources(user, job["result"]["citations"], tools)
        return {"job": job_view(job)}

    def submit(user, key, ref, skill, body):
        inputs = body.get("inputs", {})
        if not isinstance(inputs, dict):
            invalid("技能输入应为对象")
        if key is not None and (not key.strip() or len(key) > 200):
            invalid("防重复编号应为 1 到 200 字符")
        request = {
            "appId": APP, "project": PROJECT, "operation": OPERATION, "idempotencyKey": key or uuid4().hex,
            "input": {"ref": ref, "skill": prepare_skill(skill), "inputs": inputs},
        }
        require_utf8_json(request)
        return visible_job(user, jobs.submit(user, request))

    @router.post("/{sid}/run", status_code=202)
    def run(sid: str, body: dict, user=Depends(current_user), idempotency_key: str | None = Header(None)):
        skills.records.app(user, APP, "operate")
        return submit(user, idempotency_key, sid, runnable_skill(skills, user, sid), body)

    @router.post("/trial", status_code=202)
    def trial(body: dict, user=Depends(current_user), idempotency_key: str | None = Header(None)):
        skills.records.app(user, APP, "operate")
        return submit(user, idempotency_key, None, body.get("skill"), body)

    @router.get("/jobs/{jid}")
    def job_status(jid: str, user=Depends(current_user)):
        try:
            job = jobs.get(user, jid, app_id=APP)
        except DataError as exc:
            if exc.code != "forbidden":
                raise
            job = None
        if job is None or job["submitter"] != user.id:
            raise SkillError(404, "NOT_FOUND", "任务不存在")
        if job["input"]["ref"] is not None:
            runnable_skill(skills, user, job["input"]["ref"])
        return visible_job(user, job)

    @router.post("/draft")
    def create_draft(body: dict, user=Depends(current_user)):
        skills.records.app(user, APP, "operate")
        text = request_text(body)
        require_utf8_json(text)
        result = draft(provider, user, text)
        skills.platform.store.audit(APP, user.id, "skill.draft.generate",
                                    {"provider": type(provider).__name__})
        return {"draft": result}

    @router.post("/match")
    def find_match(body: dict, user=Depends(current_user)):
        text = body.get("text")
        if not isinstance(text, str):
            invalid("触发语查询应为文本")
        docs = skills.records.list_records(user, APP, type="skill")["items"]
        items = [skills.view(user, doc, history=False) for doc in docs
                 if not doc["data"]["deleted"] and doc["data"]["status"] == "published"
                 and skills.access(user, doc["data"])[0]]
        return match(text, items)

    @router.get("/{sid}/manifest")
    @router.post("/{sid}/promote")
    def unavailable(sid: str, user=Depends(current_user)):
        skills.records.app(user, APP)
        raise SkillError(501, "NOT_IMPLEMENTED", "本期暂不支持将技能升级为小应用")

    app.include_router(router)
    app.router.lifespan_context = lifespan
