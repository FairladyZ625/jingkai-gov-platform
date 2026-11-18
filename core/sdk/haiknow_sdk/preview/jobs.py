"""持久任务句柄。操作函数随应用代码加载，队列只保存操作名、版本和 JSON。"""
from inspect import iscoroutinefunction


def operation(name: str, *, version: str):
    """在 api/router.py 声明同步后台操作；函数签名为 (job, input)。"""
    if not isinstance(name, str) or not 1 <= len(name) <= 100 or not isinstance(version, str) or not version:
        raise ValueError('任务操作名须为 1–100 字，版本须为非空字符串')

    def decorate(fn):
        if iscoroutinefunction(fn):
            raise ValueError('任务操作必须是普通 def 函数')
        definitions = fn.__globals__.setdefault('__haiknow_jobs__', {})
        if name in definitions:
            raise ValueError('任务操作名不能重复')
        definitions[name] = (version, fn)
        return fn
    return decorate


class Jobs:
    def __init__(self, service, user, app_id):
        self._s, self._u, self._a = service, user, app_id

    def submit(self, operation: str, *, project: str, input: dict, idempotency_key: str) -> dict:
        return self._s.submit(self._u, {'appId': self._a, 'operation': operation,
                                     'project': project, 'input': input, 'idempotencyKey': idempotency_key})

    def get(self, id: str) -> dict:
        return self._s.get(self._u, id, app_id=self._a)

    def list(self, *, project=None, status=None) -> dict:
        return self._s.list(self._u, app_id=self._a, project=project, status=status)

    def cancel(self, id: str) -> dict:
        return self._s.cancel(self._u, id, app_id=self._a)

    def retry(self, id: str) -> dict:
        return self._s.retry(self._u, id, app_id=self._a)

    def notifications(self) -> dict:
        return self._s.notifications(self._u, app_id=self._a)

    def read_notification(self, id: str) -> dict:
        return self._s.read_notification(self._u, id, app_id=self._a)
