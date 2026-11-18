"""应用边界：请求异常不外溢，连续失败短暂熔断；不伪造可强杀的超时。"""
from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass, field

from fastapi.responses import JSONResponse

from .admin_apps import record_run

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 30
log = logging.getLogger('haiknow')


@dataclass
class Circuit:
    failures: int = 0
    until: float = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def retry_after(self) -> int:
        with self._lock:
            remaining = self.until - time.monotonic()
            if self.until and remaining <= 0:
                self.failures, self.until = 0, 0
            return max(0, math.ceil(remaining))

    def record(self, failed: bool) -> None:
        with self._lock:
            if not failed:
                self.failures = 0
            else:
                self.failures += 1
                if self.failures >= FAILURE_THRESHOLD:
                    self.until = time.monotonic() + COOLDOWN_SECONDS


class AppUnavailable(Exception):
    def __init__(self, app_id: str, reason: str, retry_after: int = 0):
        self.app_id, self.reason, self.retry_after = app_id, reason, retry_after


def unavailable_response(error: AppUnavailable, request_id: str | None = None):
    return JSONResponse({'error': {'code': 'APP_UNAVAILABLE', 'app': error.app_id,
                                  'message': error.reason, 'requestId': request_id or uuid.uuid4().hex,
                                  'retryable': bool(error.retry_after)}}, status_code=503,
                        headers={'Retry-After': str(error.retry_after)} if error.retry_after else None)


class AppIsolation:
    """原生 ASGI 边界保留 SDK 已定义的 4xx/模型错误响应，只截获未处理异常。"""
    def __init__(self, app, platform):
        self.app, self.platform = app, platform

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        prefix = next((p for p in ('/api/apps/', '/api/v1/apps/') if path.startswith(p)), None)
        app_id = path[len(prefix):].split('/')[0] if prefix else ''
        entry = self.platform.apps.get(app_id)
        if scope['type'] != 'http' or entry is None:
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        began = time.perf_counter()

        def record(status, error=None):
            user_id = scope.get('session', {}).get('uid')
            record_run(self.platform, app_id, user_id, scope.get('method', ''), path,
                       status, round((time.perf_counter() - began) * 1000, 3), error)

        reason = entry.unavailable_reason()
        if reason:
            response = unavailable_response(AppUnavailable(app_id, reason, entry.circuit.retry_after()), request_id)
            result = await response(scope, receive, send)
            if prefix == '/api/apps/':
                record(503)
            return result
        if prefix == '/api/v1/apps/':
            # v1 由平台服务执行，保留其 internal_error 契约，不计作应用代码失败。
            return await self.app(scope, receive, send)
        started, completed, status = False, False, 500

        async def track(message):
            nonlocal started, completed, status
            if message['type'] == 'http.response.start':
                started, status = True, message['status']
                message['headers'] = [*message.get('headers', []), (b'x-request-id', request_id.encode())]
            elif message['type'] == 'http.response.body' and not message.get('more_body', False):
                completed = True
            await send(message)

        try:
            await self.app(scope, receive, track)
        except Exception as error:
            entry.circuit.record(True)
            log.exception('应用 %s 请求失败 requestId=%s', app_id, request_id)
            if not started:
                response = JSONResponse({'error': {'code': 'APP_ERROR', 'app': app_id,
                    'requestId': request_id, 'message': '应用处理失败，请重试或联系负责人', 'retryable': True}}, status_code=500)
                await response(scope, receive, track)
            elif not completed:
                # 流已经发出时不能改写 HTTP 状态；结束本次流，避免请求一直悬挂。
                await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
            record(status, type(error).__name__)
            return
        entry.circuit.record(status >= 500)
        record(status)
