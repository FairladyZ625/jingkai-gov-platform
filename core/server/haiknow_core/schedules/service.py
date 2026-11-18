"""按应用声明触发持久长任务的单进程调度器。"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from haiknow_sdk import DataError
from ..stability import AppUnavailable


class ScheduleService:
    def __init__(self, platform, app):
        self.platform, self.app, self.store = platform, app, platform.store
        self.definitions = {}
        for app_id, entry in platform.apps.items():
            if entry.status != "ok":
                continue
            module = sys.modules.get("haiknow_apps." + app_id.replace("-", "_") + ".router")
            for name, definition in getattr(module, "__haiknow_schedules__", {}).items():
                self.definitions[(app_id, name)] = definition
        self.stopping = threading.Event()
        self._lock = threading.RLock()

    def _definition(self, app_id, name):
        definition = self.definitions.get((app_id, name))
        if definition is None:
            raise DataError("not_found", "调度不存在")
        return definition

    def _require(self, user, app_id, action):
        self.platform.data.app(user, app_id, action)

    def _binding(self, app_id, name, project):
        row = self.store._db.execute(
            "select enabled,submitter,enabled_at from v1_schedule_bindings where app=? and name=? and project=?",
            (app_id, name, project),
        ).fetchone()
        return row

    def list(self, user, *, app_id=None):
        global_admin = "admin" in self.platform.rbac.actions(user, "*")
        if app_id is not None and not global_admin:
            self._require(user, app_id, "operate")
        result = []
        with self.store._lock:
            for (aid, name), definition in self.definitions.items():
                if app_id is not None and aid != app_id:
                    continue
                if not global_admin and "operate" not in self.platform.rbac.actions(user, aid):
                    continue
                bindings = []
                for project in definition["projects"]:
                    if not global_admin and not self.platform.data.projects.visible(user, project):
                        continue
                    row = self._binding(aid, name, project)
                    runs = self.store._db.execute(
                        "select document from v1_schedule_runs where app=? and name=? and project=? order by rowid desc limit 10",
                        (aid, name, project),
                    ).fetchall()
                    recent = []
                    for (raw,) in runs:
                        item = json.loads(raw)
                        if item.get("jobId"):
                            try:
                                item["jobStatus"] = self.platform.jobs._load(item["jobId"])["status"]
                            except DataError:
                                pass
                        recent.append(item)
                    bindings.append({"project": project, "enabled": bool(row[0]) if row else False,
                                     "submitter": row[1] if row else None, "enabledAt": row[2] if row else None,
                                     "recentRuns": recent})
                result.append({**definition, "appId": aid, "bindings": bindings})
        return {"items": result}

    def _set_enabled(self, user, app_id, name, project, enabled, *, admin=False):
        definition = self._definition(app_id, name)
        if project not in definition["projects"]:
            raise DataError("not_found", "调度项目不存在")
        self._require(user, app_id, "admin" if admin or not enabled else "operate")
        # 启用人必须同时拥有 operate 和项目范围，避免创建永远无法执行的绑定。
        self.platform.data.projects.require(user, project)
        self.platform.data.app(user, app_id, "operate")
        with self.store._lock, self.store._db:
            if enabled:
                self.store._db.execute(
                    "insert into v1_schedule_bindings(app,name,project,enabled,submitter,enabled_at) values (?,?,?,?,?,?) "
                    "on conflict(app,name,project) do update set enabled=1,submitter=excluded.submitter,enabled_at=excluded.enabled_at",
                    (app_id, name, project, 1, user.id, time.time()),
                )
            else:
                self.store._db.execute(
                    "update v1_schedule_bindings set enabled=0 where app=? and name=? and project=?",
                    (app_id, name, project),
                )
            self.store.audit(app_id, user.id, "schedule.enable" if enabled else "schedule.pause",
                             {"name": name, "project": project}, connection=self.store._db)
        return self.list(user, app_id=app_id)

    def enable(self, user, app_id, name, project):
        return self._set_enabled(user, app_id, name, project, True)

    def pause(self, user, app_id, name, project):
        return self._set_enabled(user, app_id, name, project, False)

    def resume(self, user, app_id, name, project):
        return self._set_enabled(user, app_id, name, project, True, admin=True)

    def _submit(self, app_id, name, project, slot, submitter):
        definition = self._definition(app_id, name)
        key = f"schedule:{app_id}:{name}:{project}:{slot.isoformat()}"
        try:
            entry = self.platform.apps.get(app_id)
            if entry is None or entry.status != "ok" or not entry.enabled:
                raise DataError("app_unavailable", "应用未启用或不可用")
            if submitter is None:
                raise DataError("submitter_unavailable", "调度启用人已不可用")
            job = self.platform.jobs.submit(submitter, {
                "appId": app_id, "operation": definition["operation"], "project": project,
                "input": {}, "idempotencyKey": key,
            })
            status, reason = "submitted", None
            job_id = job["id"]
        except (DataError, AppUnavailable) as exc:
            status, job_id = "skipped", None
            reason = getattr(exc, "code", "app_unavailable" if isinstance(exc, AppUnavailable) else type(exc).__name__)
        document = {"appId": app_id, "name": name, "project": project, "slot": slot.isoformat(),
                    "jobId": job_id, "status": status, "reason": reason,
                    "createdAt": time.time(), "updatedAt": time.time()}
        with self.store._lock, self.store._db:
            self.store._db.execute(
                "insert or ignore into v1_schedule_runs(app,name,project,slot,document) values (?,?,?,?,?)",
                (app_id, name, project, slot.isoformat(), json.dumps(document, ensure_ascii=False, sort_keys=True)),
            )
        return document

    @staticmethod
    def _latest_slot(definition, now):
        try:
            zone = ZoneInfo(definition.get("timezone") or "Asia/Shanghai")
        except ZoneInfoNotFoundError as exc:
            raise DataError("invalid_request", "调度时区无效") from exc
        local = now.astimezone(zone)
        candidates = []
        for day in (local.date(), local.date() - timedelta(days=1)):
            for value in definition["at"]:
                hour, minute = map(int, value.split(":"))
                naive = datetime(day.year, day.month, day.day, hour, minute)
                slot = naive.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
                if slot.astimezone(zone).replace(tzinfo=None) == naive:
                    candidates.append(slot)
        due = [slot for slot in candidates if slot <= now]
        return max(due) if due else None

    def tick(self, now=None, *, startup=False):
        """推进一次调度；startup 只检查每个绑定最近的错过时点。"""
        now = now or datetime.now(timezone.utc)
        with self.store._lock:
            bindings = self.store._db.execute(
                "select app,name,project,submitter,enabled_at from v1_schedule_bindings where enabled=1"
            ).fetchall()
        submitted = []
        for app_id, name, project, submitter, enabled_at in bindings:
            definition = self.definitions.get((app_id, name))
            if not definition:
                continue
            slot = self._latest_slot(definition, now)
            if slot is None or slot.timestamp() < enabled_at:
                continue
            with self.store._lock:
                exists = self.store._db.execute(
                    "select 1 from v1_schedule_runs where app=? and name=? and project=? and slot=?",
                    (app_id, name, project, slot.isoformat()),
                ).fetchone()
            if exists:
                continue
            submitted.append(self._submit(app_id, name, project, slot, self.platform.directory.user(submitter)))
        return submitted

    def run_now(self, user, app_id, name, project):
        definition = self._definition(app_id, name)
        self._require(user, app_id, "admin")
        binding = self._binding(app_id, name, project)
        if not binding or not binding[0]:
            raise DataError("invalid_state", "调度尚未启用")
        self.platform.data.projects.require(user, project)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        return {"items": [self._submit(app_id, name, project, now, self.platform.directory.user(binding[1]))]}

    def start(self):
        self.stopping.clear()
        self.tick(startup=True)
        self.thread = threading.Thread(target=self._loop, name="haiknow-schedules", daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stopping.wait(30):
            self.tick()

    def stop(self):
        self.stopping.set()
        if hasattr(self, "thread"):
            self.thread.join()
