"""§3.10 的运行状态与人工确认，全部由服务端更新。"""

import asyncio
from base64 import b64encode
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Protocol
from uuid import uuid4

from .tasks.gov_notice import SITE_SYSTEM, TASK as NOTICE_TASK, run_notice


PREFIX = "/api/apps/computer"
SYSTEM_ID = "zcdx"
GATES = {"otp": "验证码核验", "sign": "签章", "pay": "付款", "submit": "提交"}
CONFIRM_LABELS = {**GATES, "import": "入库"}
TERMINAL = {"done", "stopped", "failed"}
TIMEOUT_SECONDS = 600
TIMEOUT_MESSAGE = "运行超时，单次运行上限为 10 分钟"
TASK = {
    "id": "apply", "title": "政策申报填表", "icon": "policy", "system": SYSTEM_ID,
    "needsEnt": False, "desc": "在本地模拟政务站填写演示申报",
    "stop": "验证码、签章、付款和提交前停下确认", "keywords": ["申报", "备案", "填表"],
}
TASKS = {"apply": TASK, "notice": NOTICE_TASK}


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


class ComputerError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.error = {"code": code, "message": message, "details": details or {}}


class Runner(Protocol):
    def __call__(self, run: "Run") -> Awaitable[dict]: ...


Audit = Callable[[str, str, dict], None]
CanOperate = Callable[[], bool]


class Run:
    def __init__(self, owner: str, data: dict, deadline: float, audit: Audit, can_operate: CanOperate):
        self.owner = owner
        self.data = data
        self.deadline = deadline
        self.audit = audit
        self.can_operate = can_operate
        self.approval: asyncio.Future | None = None
        self.job: asyncio.Task | None = None

    def event(self, action: str, text: str, who: str = "AI", *, actor: str | None = None) -> None:
        self.audit(actor or self.owner, action, {"runId": self.data["id"], "text": text})
        self.data["log"].append({"at": now(), "text": text, "who": who})

    def check(self) -> None:
        if asyncio.get_running_loop().time() >= self.deadline:
            raise TimeoutError
        if not self.can_operate():
            raise ComputerError("FORBIDDEN", "系统已停用或经办人已失去操作权限")
        if self.data["status"] != "running":
            raise ComputerError("LOCKED", "任务未在执行中")

    def snapshot(self, *, detail: bool = True) -> dict:
        fields = self.data if detail else {k: v for k, v in self.data.items() if k != "shots"}
        return deepcopy(fields)

    async def capture(self, title: str, png: bytes, *, kind: str | None = None) -> None:
        self.check()
        step = {"title": title, "status": "blocked" if kind else "done", "ops": []}
        message = f"{title}，等待人工确认{GATES[kind]}" if kind else title
        self.event("computer.step.waiting" if kind else "computer.step.done", message)
        # 原型用 HTML 重放历史截图。标签固定生成，输入只有浏览器返回的 PNG 字节。
        payload = b64encode(png).decode("ascii")
        self.data["shots"].append(f'<img alt="步骤截图" src="data:image/png;base64,{payload}">')
        self.data["steps"].append(step)
        self.data["step"] = len(self.data["steps"]) - 1
        self.data["shotCount"] = len(self.data["shots"])
        if not kind:
            return
        self.approval = asyncio.get_running_loop().create_future()
        step["human"] = "otp" if kind == "otp" else "gate"
        self.data.update(status="waiting", pending={"kind": kind, "step": self.data["step"]})
        try:
            await self.approval
            self.check()
            step["status"] = "done"
        finally:
            self.approval = None

    def record_result(self, result: dict) -> None:
        """站点已受理后立刻留下回执，后续截图或清理不得把它清掉。"""
        if self.data.get("result"):
            return
        self.data["result"] = result
        self.event("computer.receipt", f"模拟申报已受理，编号 {result.get('no')}")

    def confirm(self, decision: str, kind: str | None) -> None:
        pending = self.data["pending"]
        if (self.data["status"] != "waiting" or self.approval is None or self.approval.done()
                or asyncio.get_running_loop().time() >= self.deadline):
            raise ComputerError("LOCKED", "当前没有可以确认的步骤")
        if kind != pending["kind"] and (decision == "approve" or kind is not None):
            raise ComputerError("LOCKED", "确认类型与当前步骤不一致")
        if decision == "decline":
            self.stop(f"人工拒绝{CONFIRM_LABELS[pending['kind']]}，任务已停止")
            return
        if not self.can_operate():
            raise ComputerError("FORBIDDEN", "系统已停用或经办人已失去操作权限")
        self.event("computer.confirm.approve", f"人工确认{CONFIRM_LABELS[kind]}", self.data["by"])
        self.data.update(status="running", pending=None)
        # 将消费掉的批准同步交给同一个等待点，重复请求无法继续。
        self.approval.set_result(None)

    def stop(self, message: str, *, actor: str | None = None) -> None:
        if self.data["status"] in TERMINAL:
            raise ComputerError("LOCKED", "任务已经结束")
        who = "系统" if actor else self.data["by"]
        self.event("computer.stop", message, who, actor=actor)
        # 受理回执一旦写下就保留；清理阶段被停止时仍可追查。
        self.data.update(status="done" if self.data.get("result") else "stopped", pending=None)
        self.job.cancel()

    def reject_pending(self, error: ComputerError) -> None:
        if self.approval is not None and not self.approval.done():
            self.approval.set_exception(error)

    def expire(self) -> None:
        if self.data["status"] not in TERMINAL:
            # 先公布超时，再取消浏览器会话。浏览器关闭耗时不延长确认期限。
            try:
                self.fail(ComputerError("CHECK_FAILED", TIMEOUT_MESSAGE))
            finally:
                self.job.cancel()

    async def execute(self, runner: Runner) -> None:
        timeout = asyncio.get_running_loop().call_at(self.deadline, self.expire)
        try:
            self.check()
            result = await runner(self)
            if self.data["status"] in TERMINAL:
                return
            if self.data["task"] == "apply":
                if not self.data.get("result") and result:
                    self.record_result(result)
                self.event("computer.done", "模拟申报已完成")
            else:
                if result is not None and not self.data.get("result"):
                    self.data["result"] = result
                self.event("computer.done", "通知已入库" if self.data.get("result") else "任务已完成")
            self.check()
            self.data.update(status="done", result=self.data.get("result") or result)
        except TimeoutError:
            self.fail(ComputerError("CHECK_FAILED", TIMEOUT_MESSAGE))
        except ComputerError as exc:
            self.fail(exc)
        except Exception:
            self.fail(ComputerError("CHECK_FAILED", "模拟站运行失败，请检查浏览器与站点是否可用"))
        finally:
            timeout.cancel()

    def fail(self, exc: ComputerError) -> None:
        if self.data["status"] in TERMINAL:
            return
        if self.data.get("result"):
            self.data.update(status="done", pending=None)
            self.event("computer.cleanup", f"受理回执已保留：{str(exc)}")
            return
        self.data.update(status="failed", pending=None, error=exc.error)
        self.event("computer.failed", str(exc))


class Runs:
    """#18 合并前的单进程执行适配。重启时丢弃会话，绝不重放写动作。"""

    def __init__(self, url: str, runner: Runner, audit: Audit, *, timeout: float = TIMEOUT_SECONDS,
                 fetch=None, import_items=None, site_requests=None):
        self.name = "本地模拟政务站"
        self.url = url
        self.runner = runner
        self.audit = audit
        self.timeout = min(timeout, TIMEOUT_SECONDS)
        self.allowed = True
        self.runs: dict[str, Run] = {}
        self.keys: dict[tuple[str, str], str] = {}
        self.notice_get = fetch
        self.site_requests = site_requests
        self._imported: dict[tuple[str, str], dict] = {}
        self.import_items = import_items or self._stub_import

    def system(self) -> dict:
        return {
            "id": SYSTEM_ID, "name": self.name, "url": self.url, "kind": "申报",
            "account": "演示身份", "allowed": self.allowed, "confirmOn": list(GATES),
        }

    def systems(self) -> list[dict]:
        return [self.system(), dict(SITE_SYSTEM)]

    async def _stub_import(self, payload: dict) -> dict:
        """#25 导入流水线尚未合并，按约定返回 docs/skipped。"""
        docs, skipped = [], []
        for item in payload.get("items") or []:
            source = item.get("source") or {}
            key = (str(source.get("url") or ""), str(item.get("name") or ""))
            if key in self._imported:
                skipped.append({"name": item.get("name"), "reason": "已在库中"})
            else:
                self._imported[key] = item
                docs.append({"name": item.get("name"), "source": source})
        return {"docs": docs, "skipped": skipped}

    async def run_notice_task(self, run: "Run") -> dict:
        async def confirm(items):
            titles = [item.get("name") or "通知" for item in items]
            run.data["notice"] = {
                "title": titles[0] if titles else "通知",
                "count": len(items),
                "items": [{"name": item.get("name"), "source": item.get("source")} for item in items],
            }
            step = {"title": "确认入库", "status": "blocked", "ops": [], "human": "import"}
            run.data["steps"].append(step)
            run.data["step"] = len(run.data["steps"]) - 1
            run.event("computer.step.waiting", f"已下载 {len(items)} 条通知，等待确认入库")
            run.approval = asyncio.get_running_loop().create_future()
            run.data.update(status="waiting", pending={"kind": "import", "step": run.data["step"]})
            try:
                await run.approval
                run.check()
                step["status"] = "done"
                return True
            finally:
                run.approval = None

        kwargs = {}
        if self.notice_get is not None:
            kwargs["get"] = self.notice_get
        if self.site_requests is not None:
            kwargs["requests"] = self.site_requests
        result = await run_notice(confirm, self.import_items, **kwargs)
        run.data["requests"] = result.get("log") or []
        for entry in run.data["requests"]:
            run.data["log"].append({
                "at": now(), "who": "系统",
                "text": f"GET {entry.get('url')} → {entry.get('result')} (#{entry.get('attempt')})",
            })
        if result.get("status") == "failed":
            run.data["skipped"] = True
            raise ComputerError("CHECK_FAILED", result.get("error") or "官网通知任务失败",
                                details={"skipped": True})
        if result.get("status") == "stopped":
            if run.data["status"] not in TERMINAL:
                run.stop("人工拒绝入库，任务已停止")
            return result
        return result.get("result") or result

    def set_allowed(self, owner: str, system_id: str, allowed: bool) -> dict:
        if system_id != SYSTEM_ID:
            raise ComputerError("NOT_FOUND", "系统不存在")
        self.audit(owner, "computer.system.update", {"systemId": system_id, "allowed": allowed})
        self.allowed = allowed
        if not allowed:
            for run in self.runs.values():
                if run.data["status"] not in TERMINAL:
                    run.stop("系统授权已停用，任务已停止", actor=owner)
        return self.system()

    def start(self, owner: str, name: str, args: dict, key: str | None, can_operate: CanOperate) -> Run:
        task = TASKS.get(args["task"])
        if task is None:
            raise ComputerError("NOT_FOUND", "任务模板不存在")
        dedup = (owner, key) if key else None
        if dedup in self.keys:
            existing = self.runs[self.keys[dedup]]
            ent = existing.data["ent"]
            current = (existing.data["task"], ent["id"] if ent else None, existing.data["from"])
            if current != (args["task"], args["ent"], args["from"]):
                raise ComputerError("LOCKED", "幂等键已用于其他任务")
            return existing
        if task["id"] == "apply" and not self.allowed:
            raise ComputerError("FORBIDDEN", "模拟政务站的操作授权已停用")
        active = [run for run in self.runs.values() if not run.job.done()]
        if len(active) >= 3 or any(run.owner == owner for run in active):
            raise ComputerError("QUOTA_EXCEEDED", "执行席位已满或你已有进行中的电脑操作")
        # 运行记录、回执和幂等键按经办人保留；超限只丢掉已结束任务的截图热缓存。
        if len(self.runs) >= 30:
            for run in self.runs.values():
                if run.job.done() and run.data.get("shots"):
                    run.data["shots"] = []
                    break
        run_id = uuid4().hex
        ent = args["ent"]
        official = task["id"] == "notice"
        data = {
            "id": run_id, "task": task["id"], "title": task["title"],
            "ent": {"id": ent, "short": ent} if ent else None,
            "system": (
                {"name": SITE_SYSTEM["name"], "url": SITE_SYSTEM["url"]} if official
                else {"name": self.name, "url": self.url}
            ),
            "from": args["from"],
            "by": name, "status": "running", "step": 0, "created": now(),
            "steps": [], "log": [], "shots": [], "shotCount": 0, "fields": [],
            "pending": None, "result": None,
        }
        deadline = asyncio.get_running_loop().time() + self.timeout
        # 官网只读任务不依赖模拟站授权；经办人权限仍每次复核。
        authorized = (lambda: can_operate()) if official else (lambda: self.allowed and can_operate())
        run = Run(owner, data, deadline, self.audit, authorized)
        run.event("computer.start", "开始下载官网通知" if official else "开始本地模拟申报")
        worker = self.run_notice_task if official else self.runner
        run.job = asyncio.create_task(run.execute(worker))
        self.runs[run_id] = run
        if dedup:
            self.keys[dedup] = run_id
        return run

    def get(self, owner: str, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None or run.owner != owner:
            raise ComputerError("NOT_FOUND", "运行记录不存在")
        return run

    def list(self, owner: str, limit: int, offset: int) -> dict:
        owned = [run for run in reversed(self.runs.values()) if run.owner == owner]
        return {"items": [run.snapshot(detail=False) for run in owned[offset:offset + limit]], "total": len(owned)}

    async def close(self) -> None:
        for run in self.runs.values():
            if not run.job.done():
                if run.data["status"] not in TERMINAL:
                    run.fail(ComputerError("LOCKED", "运行服务已停止"))
                run.job.cancel()
        await asyncio.gather(*(run.job for run in self.runs.values()), return_exceptions=True)
