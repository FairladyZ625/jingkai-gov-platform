"""服务端保存计划步骤与执行回执，状态更新和卫华审计在同一事务提交。"""

import json
from contextlib import contextmanager
from uuid import uuid4

from jkq.conversations.store import now

from .planning import missing_permission


class ReceiptError(Exception):
    def __init__(self, status, code, message, **details):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


class Receipts:
    def __init__(self, platform):
        self.platform = platform
        self.store = platform.store
        self.db = self.store._db
        with self.transaction():
            self.db.execute(
                """create table if not exists jkq_operator_runs (
                    id text primary key, owner text not null, app text not null,
                    need text not null, receipt text not null, status text not null
                )"""
            )

    @contextmanager
    def transaction(self):
        with self.store._lock, self.db:
            self.store.begin_write()
            yield

    def prepare(self, user, intent, steps):
        identity = f"OP-{uuid4().hex}"
        # 仅保存回执校验所需信息，原始话术和槽位不会入库。
        pending = [{"id": step["id"], "write": step["write"], "status": "pending"} for step in steps]
        with self.transaction():
            self.db.execute("insert into jkq_operator_runs values(?,?,?,?,?,?)",
                            (identity, user.id, intent.app, intent.need, json.dumps(pending), "planned"))
        return identity

    def _owned(self, user, identity):
        row = self.db.execute(
            "select app, need, receipt, status from jkq_operator_runs where id=? and owner=?",
            (identity, user.id),
        ).fetchone()
        if row is None:
            raise ReceiptError(404, "NOT_FOUND", "操作员计划或运行不存在")
        app, need, raw, status = row
        return app, need, json.loads(raw), status

    def _audit(self, user, app_id, action, identity, **detail):
        self.store.audit(app_id, user.id, action, {"via": "operator", "runId": identity, **detail},
                         connection=self.db)

    def _save(self, identity, steps, status):
        self.db.execute("update jkq_operator_runs set receipt=?, status=? where id=?",
                        (json.dumps(steps), status, identity))

    def record(self, user, identity, incoming, confirmed):
        with self.transaction():
            app, needed, steps, status = self._owned(user, identity)
            try:
                if need := missing_permission(self.platform, user, app, needed):
                    raise ReceiptError(403, "FORBIDDEN", "当前账号已无权执行此计划", app=app, need=need)
                changed = _apply(steps, status, incoming, set(confirmed))
            except ReceiptError as error:
                self._audit(user, app, "operator.run.rejected", identity,
                            outcome=error.code, **error.details)
                rejected = error
            else:
                if changed or status == "planned":
                    status = _status(steps)
                    self._save(identity, steps, status)
                    self._audit(user, app, "operator.run", identity, status=status,
                                steps=changed, confirmed=[step["id"] for step in changed
                                                         if step["write"] and step["status"] == "done"])
                return _response(identity, status, steps)
        # 先提交拒绝审计，再返回 HTTP 错误。
        raise rejected

    def stop(self, user, identity):
        with self.transaction():
            app, _, steps, status = self._owned(user, identity)
            if status in {"planned", "running"}:
                at = now()
                skipped = []
                for step in steps:
                    if step["status"] == "pending":
                        step.update(status="skipped", at=at)
                        skipped.append(step["id"])
                status = "stopped"
                self._save(identity, steps, status)
                self._audit(user, app, "operator.stop", identity, status=status, skipped=skipped)
            return _response(identity, status, steps)


def _apply(steps, status, incoming, confirmed):
    planned = {step["id"]: step for step in steps}
    by_id = {step["id"]: step for step in incoming}
    if (len(by_id) != len(incoming) or by_id.keys() - planned.keys()
            or confirmed - {step["id"] for step in steps if step["write"]}):
        raise ReceiptError(422, "CHECK_FAILED", "回执包含未知、重复或不可确认的步骤")
    for step in incoming:
        sid = step["id"]
        if step["status"] == "done" and planned[sid]["write"] and sid not in confirmed:
            raise ReceiptError(409, "WRITE_CONFIRMATION_REQUIRED", "写步骤需要用户确认", stepId=sid)

    changed = []
    for step in steps:
        report = by_id.get(step["id"])
        if report is None or step["status"] == report["status"]:
            continue
        if status == "stopped" or step["status"] != "pending":
            raise ReceiptError(409, "INVALID_STATE", "已结束的步骤无法改写", stepId=step["id"])
        step.update(report)
        changed.append(step)
    return changed


def _status(steps):
    if any(step["status"] == "pending" for step in steps):
        return "running"
    return "failed" if any(step["status"] == "failed" for step in steps) else "done"


def _response(identity, status, steps):
    return {"id": identity, "planId": identity, "status": status, "steps": steps}
