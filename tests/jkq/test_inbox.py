import json
import sqlite3
from pathlib import Path

import pytest

from jkq.admin.usage import usage_page
from jkq.feed import feed_page, publish
from jkq.inbox import add_todo


def test_gateway_attempts():
    db = sqlite3.connect(':memory:')
    db.execute('create table audit(app_id, user_id, action, detail)')
    assert usage_page(db, 'app') == {'items': [], 'total': 0}
    for app, user, model, inputs, outputs, action in [
        ('a', 'u', 'm1', 8, 5, 'ai.chat'), ('b', 'u', 'm2', 3, 4, 'ai.chat'),
        ('a', 'v', 'm2', None, None, 'ai.chat'), ('a', 'v', 'm1', 9, 9, 'other'),
    ]:
        db.execute('insert into audit values (?,?,?,?)', (app, user, action, json.dumps({
            'model': model, 'usage': {'input': inputs, 'output': outputs}})))
    for dim, expected in [
        ('app', [('a', 2, 8, 5), ('b', 1, 3, 4)]),
        ('model', [('m1', 1, 8, 5), ('m2', 2, 3, 4)]),
        ('user', [('u', 2, 11, 9), ('v', 1, 0, 0)]),
    ]:
        assert usage_page(db, dim) == {'total': 2, 'items': [
            {dim: key, 'calls': calls, 'input': i, 'output': o} for key, calls, i, o in expected]}


def test_feed_visibility_and_paging():
    db = sqlite3.connect(':memory:')
    db.execute('create table jkq_feed(id, project, title, at)')
    db.executemany('insert into jkq_feed values (?,?,?,?)', [
        ('a', 'p', '旧', 1), ('c', 'p', '新', 2), ('b', 'p', '同秒', 2), ('d', 'q', '别组', 3)])
    assert feed_page(db, [], 50, 0) == {'total': 0, 'items': []}
    assert feed_page(db, ['p'], 2, 3) == {'total': 3, 'items': []}
    assert [r['id'] for r in feed_page(db, ['p'], 2, 1)['items']] == ['b', 'a']
    assert feed_page(db, ['*'], 1, 0)['items'][0]['id'] == 'd'


@pytest.fixture
def client(request, monkeypatch):
    pytest.importorskip('fastapi')
    from fastapi.testclient import TestClient
    from jkq import routers
    from jkq.app import create_app
    from jkq.inbox import router
    config, _ = request.getfixturevalue('isolated_platform')
    seed = Path(__file__).resolve().parents[2] / 'config/projects.yaml'
    (config / 'projects.yaml').write_bytes(seed.read_bytes())
    users = config / 'users.yaml'
    users.write_text(users.read_text().replace('sample-project', 'jkq'))
    roles = config / 'roles.yaml'
    spec = json.loads(roles.read_text())
    for ident, role in spec['roles'].items():
        role.setdefault('name', ident)
    roles.write_text(json.dumps(spec))
    request.getfixturevalue('cheap_password_hash')
    monkeypatch.setenv('HAIKNOW_SECRET', 'test-session-signing')
    # #12 之后实例禁止卫华演示登录：先用 core 把隔离账号写进身份库，再关掉演示登录启动实例，
    # 用请求头切换会话，账号、项目与权限仍来自身份库。
    from haiknow_core.main import create_app as core_app
    with TestClient(core_app()):
        pass
    monkeypatch.setenv('HAIKNOW_DEMO_LOGIN', '0')
    if router not in routers.ROUTERS:
        monkeypatch.setattr(routers, 'ROUTERS', (*routers.ROUTERS, router))
    from fastapi import HTTPException, Request
    from haiknow_core.main import current_user

    def header_user(request: Request):
        user = request.app.state.platform.directory.user(request.headers.get('x-test-user', ''))
        if user is None:
            raise HTTPException(401, '未登录')
        return user

    app = create_app()
    app.dependency_overrides[current_user] = header_user
    with TestClient(app) as client:
        yield client


def login(client, user):
    client.headers['x-test-user'] = user


def test_inbox_transitions_and_ownership(client):
    login(client, 'samplereviewer')
    base = '/api/v1'
    for box in ('review', 'todo', 'done'):
        assert client.get(f'{base}/inbox?box={box}').json() == {
            'items': [], 'total': 0, 'counts': dict(review=0, todo=0, done=0, pending=0)}
    bad = client.get(base + '/inbox?box=unknown')
    assert (bad.status_code, bad.json()['error']['code']) == (400, 'INVALID_BOX')

    login(client, 'sampleoperator')
    record = client.post(base + '/apps/sample-app/records', json={
        'project': 'jkq', 'type': 'example', 'data': {}})
    assert record.status_code == 201, record.text
    review = client.post(base + '/reviews', json={
        'appId': 'sample-app', 'recordId': record.json()['id'], 'version': 1, 'assignee': 'samplereviewer'})
    assert review.status_code == 201, review.text
    login(client, 'samplereviewer')
    store = client.app.state.platform.store
    with store._db as db:
        add_todo(db, 'samplereviewer', 'meeting', '核对纪要', 'u', at=5, ident='mine', ref={'meetingId': 'M1'})
        add_todo(db, 'sampleoperator', 'meeting', '确认记录', 'u', at=5, ident='other')
    assert [r['id'] for r in client.get(base + '/todos').json()['items']] == ['mine']
    boxes = [client.get(f'{base}/inbox?box={box}').json() for box in ('review', 'todo')]
    assert boxes[0]['counts']['pending'] == sum(len(b['items']) for b in boxes) == 2
    for ident in ('other', 'missing'):
        err = client.patch(f'{base}/todos/{ident}', json={'done': True})
        assert (err.status_code, err.json()['error']['code']) == (404, 'NOT_FOUND')
    assert client.patch(base + '/todos/mine', json={'done': 'true'}).status_code == 422
    for _ in range(2):
        assert client.patch(base + '/todos/mine', json={'done': True}).json()['item']['done']
    done = client.get(base + '/inbox?box=done').json()
    assert done['counts'] == dict(review=1, todo=0, done=1, pending=1)
    assert done['items'][0]['id'] == 'mine'
    assert len([r for r in store.audit_list() if r['action'] == 'todo.patch']) == 1
    # 审签路由在 #18 内自行解析会话，这里直接走同一业务函数完成确认。
    from jkq import reviews_api
    platform = client.app.state.platform
    reviews_api.decide(platform.data, platform.directory.user('samplereviewer'), review.json()['id'],
                       {'version': 1, 'decision': 'approve'})
    assert client.get(base + '/inbox?box=done').json()['counts'] == dict(review=0, todo=0, done=2, pending=0)


def test_message_moves_to_done_only_after_acknowledgement(client):
    login(client, 'sampleoperator')
    record = client.post('/api/v1/apps/sample-app/records', json={
        'project': 'jkq', 'type': 'example', 'data': {}}).json()
    sent = client.post('/api/v1/apps/sample-app/messages', json={
        'idempotencyKey': 'sample-message', 'recipientIds': ['samplereviewer'],
        'recordId': record['id'], 'version': 1, 'title': '请确认', 'body': '示例',
        'requiresAcknowledgement': True})
    assert sent.status_code == 201, sent.text
    mid = sent.json()['items'][0]['id']
    assert client.get('/api/v1/inbox?box=todo').json()['items'] == []
    login(client, 'samplereviewer')
    assert client.post(f'/api/v1/messages/{mid}/read').status_code == 200
    assert client.get('/api/v1/inbox?box=todo').json()['items'][0]['id'] == mid
    assert client.post(f'/api/v1/messages/{mid}/acknowledge').status_code == 200
    done = client.get('/api/v1/inbox?box=done').json()
    assert done['items'][0]['id'] == mid
    assert done['counts']['pending'] == 0


def test_usage_and_feed_http(client):
    for path in ('inbox', 'todos', 'admin/usage', 'feed'):
        assert client.get('/api/v1/' + path).status_code == 401
    login(client, 'sampleoperator')
    err = client.get('/api/v1/admin/usage')
    assert (err.status_code, err.json()['error']['code']) == (403, 'FORBIDDEN')
    assert client.get('/api/v1/feed').json() == {'items': [], 'total': 0}
    with client.app.state.platform.store._db as db:
        for n in range(54):
            publish(db, 'jkq', '团队动态', at=n, ident=str(n))
        publish(db, 'other-project', '别组动态', at=99)
    page = client.get('/api/v1/feed').json()
    assert page['total'] == 54 and len(page['items']) == 50
    assert client.get('/api/v1/feed?limit=1&offset=1').json()['items'][0]['id'] == '52'
    assert client.get('/api/v1/feed?offset=-1').status_code == 422
    assert client.get('/api/v1/feed?limit=0').status_code == 422
    assert client.get('/api/v1/feed?limit=200').json()['total'] == 54
    for query in ('limit=201', 'offset=2147483648', 'offset=9223372036854775808'):
        err = client.get('/api/v1/feed?' + query)
        assert (err.status_code, err.json()['error']['code']) == (422, 'INVALID_REQUEST')
    assert client.get('/api/v1/feed?offset=2147483647').json() == {'items': [], 'total': 54}
    login(client, 'sampleadmin')
    assert client.get('/api/v1/admin/usage').json() == {'items': [], 'total': 0}
    store = client.app.state.platform.store
    store.audit('app1', 'user1', 'ai.chat', {'model': 'model1', 'usage': {'input': 8, 'output': 5}})
    for dim, key in [('app', 'app1'), ('model', 'model1'), ('user', 'user1')]:
        assert client.get('/api/v1/admin/usage', params={'groupBy': dim}).json() == {
            'items': [{dim: key, 'calls': 1, 'input': 8, 'output': 5}], 'total': 1}


def review_counts(client, uid):
    login(client, uid)
    return client.get('/api/v1/inbox?box=review').json()['counts']


def test_review_box_only_counts_actionable_reviews(client):
    login(client, 'sampleoperator')
    ids = []
    for assignee in ('samplereviewer', None):
        record = client.post('/api/v1/apps/sample-app/records', json={
            'project': 'jkq', 'type': 'example', 'data': {}}).json()
        body = {'appId': 'sample-app', 'recordId': record['id'], 'version': 1}
        if assignee:
            body['assignee'] = assignee
        review = client.post('/api/v1/reviews', json=body)
        assert review.status_code == 201, review.text
        ids.append(review.json()['id'])
    assigned, open_review = ids
    # 提交人不能审自己的记录，角标不计。
    assert review_counts(client, 'sampleoperator')['review'] == 0
    login(client, 'samplereviewer')
    assert {i['id'] for i in client.get('/api/v1/inbox?box=review').json()['items']} == {assigned, open_review}
    # 指派给别人的审签不进第二位审核员的待审和角标。
    login(client, 'sampleextra')
    page = client.get('/api/v1/inbox?box=review').json()
    assert assigned not in {i['id'] for i in page['items']}
    assert page['counts']['pending'] == page['counts']['review'] + page['counts']['todo']
    assert page['counts']['review'] == len(page['items'])


class BadgeMismatch(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=BadgeMismatch, reason='shell.js:116、132 漏计第 834 行的我的待办')
def test_sidebar_badge_counts_inbox_rows():
    playwright = pytest.importorskip('playwright.sync_api')
    entry = Path(__file__).resolve().parents[2] / 'prototype/v4/index.html'
    with playwright.sync_playwright() as pw:
        with pw.chromium.launch() as browser:
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.goto(entry.as_uri())
            page.locator('[data-u="wangmin"]').click()
            page.locator('#btn-demo').wait_for()
            result = page.evaluate("""() => JKHttp.post('/api/apps/meeting/meetings/MT-1112/todos/commit',
                                                  {ids:['TD-2']})""")
            assert result['committed'] == ['TD-2']
            nav = page.locator('[data-nav="inbox"]:visible').first
            nav.click()
            page.locator('[data-t="todo"]').click()
            page.locator('[data-todo="TD-2"]').wait_for()
            todos = page.locator('.inb-i:visible').count()
            page.locator('[data-t="mine"]').click()
            reviews = page.locator('.inb-i:visible').count()
            badge = nav.locator('.count,.rb').all_text_contents()
            count = int(badge[0]) if badge else 0
            if count != reviews + todos:
                raise BadgeMismatch(f'角标 {count}，审签 {reviews}，待办 {todos}')
