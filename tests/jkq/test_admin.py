"""§3.9 真实 HTTP 验收。每个场景使用独立 SQLite、签名会话和已注册的临时应用。"""
import csv
import io
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip('fastapi')
from fastapi.testclient import TestClient
from haiknow_core.main import create_app

from jkq.auth import install as install_auth


ROOT = Path(__file__).resolve().parents[2]
ADMIN = '/api/v1/admin/'
USERS = ADMIN + 'users'
DEPTS = ADMIN + 'departments'
AUDIT = '/api/v1/audit'
APP = 'sample-app'
GRANT = ADMIN + 'grants/member/' + APP


def ok(result):
    assert result.is_success, result.text
    assert 'password' not in result.text.casefold()
    assert 'scrypt$' not in result.text
    return result.json()


def denied(result, status, code):
    assert result.status_code == status, result.text
    assert result.json()['error']['code'] == code


def login(client, username, password):
    return client.post('/api/v1/auth/login', json=dict(username=username, password=password))


@pytest.fixture
def build(tmp_path, monkeypatch, cheap_password_hash):
    from jkq.admin import install

    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / APP)
    # 临时应用通过 #12 的真实授权依赖写入 SDK KV，和下游经开区应用用同一权限边界。
    (apps / APP / 'api/router.py').write_text(
        "from fastapi import APIRouter, Depends\n"
        "from haiknow_sdk import app_context\n"
        "from jkq.auth import require_action\n"
        "router = APIRouter()\n"
        "@router.post('/records')\n"
        "def save(body: dict, user=Depends(require_action('sample-app','operate')), ctx=Depends(app_context)):\n"
        "    ctx.kv.put(body['id'], body)\n"
        "    return ctx.kv.get(body['id'])\n"
    )
    monkeypatch.setenv('HAIKNOW_CONFIG_DIR', str(ROOT / 'config'))
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path / 'db'))
    monkeypatch.setenv('HAIKNOW_APPS_DIR', str(apps))
    monkeypatch.setenv('HAIKNOW_SECRET', 'isolated-admin-test-signing-value')
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN', raising=False)
    for role in ('admin', 'leader', 'member', 'partner'):
        monkeypatch.setenv('JKQ_DEMO_' + role.upper() + '_PASSWORD', 'test-' + role)

    def start():
        app = create_app(ROOT)
        install_auth(app, demo=True)
        install(app)
        client = TestClient(app)
        ok(login(client, 'admin', 'test-admin'))
        return client

    return start


@pytest.fixture
def client(build):
    return build()


def items(client, path, **params):
    return ok(client.get(path, params=params))['items']


def user(client, uid):
    return next(x for x in items(client, USERS) if x['id'] == uid)


def detail(client, action):
    row, = items(client, AUDIT, action=action)
    assert row['action'] == action
    return row['detail']


@pytest.mark.parametrize(('query', 'expected'), [
    ({'q': 'WANG'}, 'wangmin'), ({'dept': 'd-ai'}, 'admin'),
    ({'role': 'leader'}, 'liyang'), ({'status': 'disabled'}, 'hejun'),
])
def test_user_filter(client, query, expected):
    if 'status' in query:
        ok(client.patch(USERS + '/u-hejun', json={'status': 'disabled'}))
    assert [x['username'] for x in items(client, USERS, **query)] == [expected]


def test_duplicate_username(client):
    denied(client.post(USERS, json=dict(username='admin', name='重名')), 409, 'DUPLICATE')
    assert items(client, AUDIT, action='identity.user.create') == []


@pytest.mark.parametrize('change', [{'status': 'disabled'}, {'role': 'leader'}])
def test_last_admin_rollback(client, change):
    before = user(client, 'u-zhanglei')
    assert (before['role'], before['status']) == ('admin', 'active')
    denied(client.patch(USERS + '/u-zhanglei', json=change), 400, 'LAST_ADMIN')
    assert user(client, 'u-zhanglei') == before
    assert items(client, AUDIT, action='identity.user.update') == []


def test_department_dependencies_and_snapshots(client):
    created = ok(client.post(DEPTS, json=dict(name='验收处', parent='d-ai')))['item']
    path = DEPTS + '/' + created['id']
    renamed = ok(client.patch(path, json=dict(name='新名称')))['item']
    assert renamed == dict(created, name='新名称')
    created_user = ok(client.post(USERS, json=dict(username='new.user', name='验收员', role='member',
                                                    deptId=created['id'], title='专员')))['item']
    assert created_user['dept'] == '新名称'
    denied(client.delete(path), 409, 'NOT_EMPTY')  # 只有成员
    updated = ok(client.patch(USERS + '/' + created_user['id'], json={'deptId': None}))['item']
    assert updated == dict(created_user, deptId=None, dept='')
    denied(client.delete(DEPTS + '/d-ext'), 409, 'NOT_EMPTY')  # 只有下级
    ok(client.delete(path))
    assert renamed not in items(client, DEPTS)
    for action, before, after in (
        ('identity.department.create', None, created), ('identity.department.update', created, renamed),
        ('identity.user.create', None, created_user), ('identity.user.update', created_user, updated),
        ('identity.department.delete', renamed, None),
    ):
        change = detail(client, action)
        assert (change['before'], change['after']) == (before, after)
        assert change['target'] == (before or after)['id']


def test_department_with_core_position(client):
    did = ok(client.post(DEPTS, json={'name': '保留岗位的部门'}))['item']['id']
    store = client.app.state.platform.store
    with store._lock, store._db as db:
        db.execute('insert into positions values (?,?,?)', ('existing-position', '主任', did))
    denied(client.delete(DEPTS + '/' + did), 409, 'NOT_EMPTY')
    assert did in {row['id'] for row in items(client, DEPTS)}


def test_demo_org_survives_restart(client, build):
    ok(client.patch(USERS + '/u-wangmin', json=dict(deptId='d-ai', title='协调员')))
    restarted = user(build(), 'u-wangmin')
    assert (restarted['deptId'], restarted['title']) == ('d-ai', '协调员')


def test_reset_invalidates_cookie_and_hides_credentials(client):
    peer = TestClient(client.app)
    ok(login(peer, 'wangmin', 'test-member'))
    result = client.patch(USERS + '/u-wangmin', json={'resetPassword': 'new-test-value'})
    assert 'new-test-value' not in result.text
    after = ok(result)['item']
    denied(peer.get('/api/v1/me'), 401, 'UNAUTHENTICATED')
    denied(login(peer, 'wangmin', 'test-member'), 401, 'BAD_CREDENTIALS')
    ok(login(peer, 'wangmin', 'new-test-value'))
    entry = detail(client, 'identity.user.update')
    assert entry['after'] == after
    assert 'new-test-value' not in json.dumps(entry)


def test_admin_self_lock(client):
    path = ADMIN + 'grants/admin/*'
    denied(client.put(path, json={'actions': ['view']}), 400, 'SELF_LOCK')
    assert 'admin' in ok(client.get(ADMIN + 'grants'))['grants']['admin']['*']


def test_revoke_operate_same_cookie(client):
    peer = TestClient(client.app)
    ok(login(peer, 'wangmin', 'test-member'))
    # 按同一份已签名 Cookie 发两次请求，禁止客户端接收响应中可能刷新的 Cookie。
    headers = {'Cookie': '; '.join(f'{k}={v}' for k, v in peer.cookies.items())}
    path = '/api/apps/' + APP + '/records'
    for actions in (['view', 'operate'], ['view']):
        ok(client.put(GRANT, json={'actions': actions}))
        response = peer.post(path, headers=headers, json={'id': 'note'})
        if 'operate' in actions:
            assert ok(response)['id']
        else:
            denied(response, 403, 'FORBIDDEN')
    row = items(client, AUDIT, action='identity.grant.update')[0]['detail']
    for snapshot, actions in ((row['before'], ['view', 'operate']), (row['after'], ['view'])):
        assert (snapshot['actions'] if isinstance(snapshot, dict) else snapshot) == actions


def test_nonadmin_routes(client):
    ok(login(client, 'wangmin', 'test-member'))
    for method, path, payload in (
        ('GET', USERS, None), ('POST', USERS, dict(username='test', name='测试')),
        ('PATCH', USERS + '/u-wangmin', dict(title='专员')), ('GET', DEPTS, None),
        ('POST', DEPTS, dict(name='处室')), ('PATCH', DEPTS + '/d-ai', dict(name='处室')),
        ('DELETE', DEPTS + '/d-ai', None), ('GET', ADMIN + 'roles', None),
        ('PATCH', ADMIN + 'roles/member', dict(mask=True)), ('GET', ADMIN + 'grants', None),
        ('PUT', GRANT, dict(actions=[])), ('PATCH', ADMIN + 'apps/' + APP, dict(status='maintenance')),
        ('GET', ADMIN + 'settings', None), ('PUT', ADMIN + 'settings', dict(settings=dict(platformName='平台'))),
        ('GET', AUDIT, None), ('GET', AUDIT + '/export', None),
    ):
        denied(client.request(method, path, json=payload), 403, 'FORBIDDEN')


def test_role_settings_and_app_snapshots(client, build):
    role = next(x for x in items(client, ADMIN + 'roles') if x['id'] == 'member')
    changed = ok(client.patch(ADMIN + 'roles/member', json=dict(mask=not role['mask'], desc='验收说明')))['item']
    assert changed == dict(role, mask=not role['mask'], desc='验收说明')
    audit = detail(client, 'identity.role.update')
    assert (audit['before'], audit['after']) == (role, changed)

    settings = ADMIN + 'settings'
    before = ok(client.get(settings))
    ok(client.put(settings, json={'settings': {'platformName': '验收平台'}}))
    after = ok(client.get(settings))
    assert after['settings']['platformName'] == '验收平台'
    audit = detail(client, 'identity.settings.update')
    for value, snapshot in ((before, audit['before']), (after, audit['after'])):
        assert snapshot.get('settings', snapshot)['platformName'] == value['settings']['platformName']

    def app_item(reader):
        return next(x for x in items(reader, '/api/v1/apps') if x['id'] == APP)

    initial = app_item(client)
    changed = ok(client.patch(ADMIN + 'apps/' + APP, json=dict(status='maintenance', statusNote='例行维护')))['item']
    assert changed['status'] == app_item(client)['status'] == app_item(build())['status'] == 'maintenance'
    audit = detail(client, 'app.update')
    assert audit['before']['status'] == initial['status']
    assert audit['after']['status'] == changed['status']
    assert audit['after']['statusNote'] == '例行维护'


def test_audit_filters_and_csv(client):
    # 写入两条时间确定的旧格式审计记录，让每一种筛选都有应保留及应排除的对象。
    store = client.app.state.platform.store
    with store._lock, store._db as db:
        db.executemany('insert into audit(ts,app_id,user_id,action,detail) values (?,?,?,?,?)', [
            (946684800, 'policy', 'reader-A', 'example.read', '{}'),
            (978307200, 'meeting', 'reader-B', 'example.write', '{}'),
        ])
    for field, value, expected in (
        ('user', 'reader-A', ['example.read']), ('app', 'meeting', ['example.write']),
        ('action', 'example.read', ['example.read']), ('from', '2000-06-01T00:00:00Z', ['example.write']),
        ('to', '2000-06-01T00:00:00Z', ['example.read']),
    ):
        rows = items(client, AUDIT, **{field: value})
        matches = [r['action'] for r in rows if r['action'].startswith('example.')]
        assert matches == expected
    result = client.get(AUDIT + '/export', params={'user': 'reader-A'})
    assert result.status_code == 200 and 'text/csv' in result.headers['content-type']
    reader = csv.DictReader(io.StringIO(result.content.decode('utf-8-sig')))
    assert reader.fieldnames == ['id', 'at', 'userId', 'user', 'role', 'app', 'action', 'target', 'model', 'via', 'detail']
    assert [row['action'] for row in reader] == ['example.read']
    export = detail(client, 'audit.export')
    assert (export['before'], export['after']) == (None, {'count': 1})
