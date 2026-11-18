"""v1 数据资源句柄；身份和应用作用域由平台注入。"""
from __future__ import annotations

from typing import Any

ERROR_STATUS = {
    'unauthenticated': 401, 'not_found': 404, 'forbidden': 403,
    'self_review': 403, 'stale_version': 409, 'version_conflict': 409,
    'invalid_state': 409, 'invalid_reference': 422, 'invalid_request': 422,
    'method_not_allowed': 405, 'internal_error': 500,
}


class DataError(Exception):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.status = ERROR_STATUS.get(code, 400)
        self.error = {'code': code, 'message': message, 'retryable': False, **details}


class Records:
    def __init__(self, service, user, app_id):
        self._s, self._u, self._a = service, user, app_id

    def save(self, *, id: str | None = None, **body) -> dict:
        return self._s.save_record(self._u, self._a, body, id)

    def get(self, id: str, version: int | None = None) -> dict:
        return self._s.get_record(self._u, self._a, id, version)

    def list(self, **filters) -> dict:
        return self._s.list_records(self._u, self._a, **filters)


class DataFiles:
    def __init__(self, service, user, app_id):
        self._s, self._u, self._a = service, user, app_id

    def save(self, name: str, data: bytes, *, project: str, purpose: str) -> dict:
        return self._s.save_file(self._u, self._a, project, purpose, name, data)

    def get(self, file_id: str) -> dict:
        return self._s.get_file(self._u, file_id)

    def read(self, file_id: str) -> bytes:
        return self._s.read_file(self._u, file_id)


class Reviews:
    def __init__(self, service, user, app_id):
        self._s, self._u, self._a = service, user, app_id

    def submit(self, record_id: str, version: int, assignee: str | None = None) -> dict:
        return self._s.submit_review(self._u, {'appId': self._a, 'recordId': record_id, 'version': version, 'assignee': assignee})

    def decide(self, review_id: str, *, version: int, decision: str, comment: str = '', assignee: str | None = None) -> dict:
        return self._s.decide_review(self._u, review_id,
                                    {'version': version, 'decision': decision, 'comment': comment, 'assignee': assignee}, app_id=self._a)

    def list(self, *, assignee: str | None = None, mine: str | None = None) -> dict:
        return self._s.list_reviews(self._u, assignee=assignee, mine=mine, app_id=self._a)


class Artifacts:
    def __init__(self, service, user):
        self._s, self._u = service, user

    def find(self, **filters) -> dict:
        return self._s.find_artifacts(self._u, **filters)


class Notifications:
    def __init__(self, service, user, app_id):
        self._s, self._u, self._a = service, user, app_id

    def list(self) -> dict:
        return self._s.list_notifications(self._u, app=self._a)

    def read(self, notification_id: str) -> dict:
        return self._s.read_notification(self._u, notification_id, app=self._a)
