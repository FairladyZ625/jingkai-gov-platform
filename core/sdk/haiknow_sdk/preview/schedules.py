"""定时调度声明与应用管理句柄（preview）。"""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def schedule(name: str, *, operation: str, projects, at, timezone: str = "Asia/Shanghai"):
    """在应用 api/router.py 顶层登记每日时点；装饰器本身不执行任务。"""
    if not isinstance(name, str) or not name or len(name) > 100:
        raise ValueError("调度名称不能为空或超过 100 字")
    if not isinstance(operation, str) or not operation:
        raise ValueError("调度操作不能为空")
    projects = tuple(projects)
    at = tuple(at)
    if not projects or not at or any(not isinstance(p, str) or not p for p in projects):
        raise ValueError("调度必须声明项目")
    try:
        for value in at:
            datetime.strptime(value, "%H:%M")
        ZoneInfo(timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("时点须为有效 HH:MM，时区须为 IANA 名称") from exc

    return _register(name, operation, projects, at, timezone)


def _register(name, operation, projects, at, timezone):
    """返回可修饰任意函数的登记器；调度声明不要求额外函数。"""
    def decorate(fn):
        definitions = fn.__globals__.setdefault("__haiknow_schedules__", {})
        if name in definitions:
            raise ValueError("调度名称不能重复")
        definitions[name] = {
            "name": name, "operation": operation, "projects": tuple(projects),
            "at": tuple(at), "timezone": timezone,
        }
        return fn
    return decorate


class Schedules:
    def __init__(self, service, user, app_id):
        self._service, self._user, self._app_id = service, user, app_id

    def list(self):
        return self._service.list(self._user, app_id=self._app_id)

    def enable(self, name, *, project):
        return self._service.enable(self._user, self._app_id, name, project)

    def pause(self, name, *, project):
        return self._service.pause(self._user, self._app_id, name, project)

    def resume(self, name, *, project):
        return self._service.resume(self._user, self._app_id, name, project)

    def run(self, name, *, project):
        return self._service.run_now(self._user, self._app_id, name, project)
