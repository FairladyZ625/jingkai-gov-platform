"""按 §4.2 调用同一实例的企业诉求接口。"""

import json

from haiknow_sdk import DataError
from starlette.exceptions import HTTPException


async def create_issue(request, payload):
    # 只调用预定的业务地址。沿用本次会话，由企业应用独立判断权限和企业存在性。
    body = json.dumps(payload, ensure_ascii=False).encode()
    path = '/api/apps/enterprise/issues'
    scope = {
        **request.scope, 'method': 'POST', 'path': path, 'raw_path': path.encode(),
        'root_path': '', 'query_string': b'', 'headers': [
            (name, value) for name, value in request.scope['headers']
            if name in (b'cookie', b'authorization', b'host')
        ] + [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())],
    }
    for key in ('route', 'endpoint', 'path_params', 'app_root_path', 'session'):
        scope.pop(key, None)

    received = False
    status = 500
    chunks = []

    async def receive():
        nonlocal received
        if received:
            return {'type': 'http.disconnect'}
        received = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(event):
        nonlocal status
        if event['type'] == 'http.response.start':
            status = event['status']
        elif event['type'] == 'http.response.body':
            chunks.append(event.get('body', b''))

    await request.app(scope, receive, send)
    try:
        response = json.loads(b''.join(chunks))
    except ValueError:
        response = {}

    if not isinstance(response, dict):
        response = {}
    item = response.get('item')
    if 200 <= status < 300 and isinstance(item, dict) and isinstance(item.get('id'), str):
        return item
    error = response.get('error')
    if not isinstance(error, dict):
        error = {}
    if status == 404:
        raise DataError('not_found', error.get('message') or '企业诉求接口或企业不存在')
    if status in (401, 403):
        raise HTTPException(status, '无权登记企业诉求')
    if status in (400, 409, 422):
        raise HTTPException(status, error.get('message') or '企业诉求未通过校验')
    raise HTTPException(503, '企业诉求接口暂不可用')
