"""管理契约逐项验收；全用虚构组织与临时数据库。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from haiknow_core.identity_models import GRANT_ACTIONS
from test_identity_auth import bootstrap
from test_platform import login

ROOT = Path(__file__).resolve().parents[2]


def test_anonymous_admin_apps(make_client):
    response = make_client().get('/api/admin/apps')
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'UNAUTHENTICATED'


@pytest.fixture
def owner(make_client, monkeypatch):
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN')
    client = make_client()
    assert bootstrap(client).status_code == 200
    return client


def created(response):
    assert response.status_code == 201, response.text
    return response.json()


def test_bootstrap_org_grants_employee_apps_and_audit(owner):
    c = owner
    dept = created(c.post('/api/admin/org/departments', json={'id': 'quality', 'name': '质量部'}))
    position = created(c.post('/api/admin/org/positions', json={'name': '检验岗', 'departmentId': dept['id']}))
    role = created(c.post('/api/admin/roles', json={'id': 'quality', 'name': '质量角色'}))
    grant = c.put('/api/admin/grants/quality/sample-app', json={'actions': ['view', 'operate']})
    assert grant.status_code == 200, grant.text
    user = created(c.post('/api/admin/users', json={'username': 'worker', 'name': '虚构员工', 'password': 'worker-pass-123',
                   'departments': [dept['id']], 'positions': [position['id']], 'roles': [role['id']]}))
    assert user['status'] == 'active' and user['lastLoginAt'] is None
    assert 'password' not in str(user)
    project = created(c.post('/api/admin/projects', json={'name': '虚构装配项目'}))
    assert c.put(f"/api/admin/projects/{project['id']}/members", json={'members': [user['id']]}).status_code == 200
    assert c.get('/api/admin/users', params={'q': 'worker', 'dept': dept['id'], 'status': 'active'}).json()['users'] == [
        {**user, 'projects': [project['id']]}]
    assert c.get('/api/admin/users?q=不存在').json() == {'users': []}
    org = c.get('/api/admin/org').json()
    assert org['company']['name'] == '虚构测试机构'
    assert org['departments'] == [dept] and org['positions'] == [position]
    role_info = next(r for r in c.get('/api/admin/roles').json()['roles'] if r['id'] == 'quality')
    assert role_info == {'id': 'quality', 'name': '质量角色', 'builtin': False, 'userCount': 1}
    matrix = c.get('/api/admin/grants').json()
    assert matrix['actions'] == ['view', 'operate', 'approve', 'admin']
    assert matrix['grants']['quality']['sample-app'] == ['view', 'operate']
    employee = TestClient(c.app)
    assert employee.post('/api/auth/login', json={'username': 'worker', 'password': 'worker-pass-123'}).status_code == 200
    me = employee.get('/api/me').json()
    assert me['departments'] == [{'id': 'quality', 'name': '质量部'}]
    assert me['positions'] == [{'id': position['id'], 'name': '检验岗'}]
    assert me['projects'] == [{'id': project['id'], 'name': '虚构装配项目'}]
    apps = employee.get('/api/apps').json()['apps']
    assert [a['id'] for a in apps] == ['sample-app']
    assert 'operate' in apps[0]['actions'] and 'edit' not in apps[0]['actions']
    record_url = '/api/v1/apps/sample-app/records'
    assert employee.post(record_url, json={'project': project['id'], 'type': 'sample', 'data': {}}).status_code == 201
    assert c.put('/api/admin/grants/quality/sample-app', json={'actions': ['view']}).status_code == 200
    assert employee.post(record_url, json={'project': project['id'], 'type': 'sample', 'data': {}}).status_code == 403
    assert c.put('/api/admin/grants/quality/sample-app', json={'actions': []}).status_code == 200
    assert employee.get('/api/apps').json()['apps'] == []
    assert c.app.state.platform.directory.departments_of(user['id']) == frozenset({'quality'})
    assert c.app.state.platform.directory.roles_of(user['id']) == frozenset({'quality'})
    assert c.patch(f"/api/admin/users/{user['id']}", json={'status': 'disabled'}).status_code == 200
    assert employee.get('/api/me').status_code == 401
    audit = c.get('/api/audit').json()['items']
    expected = {'identity.department.create', 'identity.position.create', 'identity.role.create', 'identity.grant.update',
                'identity.user.create', 'identity.project.create', 'identity.project.members', 'identity.user.update'}
    assert expected <= {a['action'] for a in audit if a['app'] == 'platform'}
    assert 'worker-pass-123' not in str(audit)


def test_grant_actions_unify_on_operate(owner):
    """授权矩阵只认 operate；旧词 edit 不再有兼容层，拒绝后原授权不变。"""
    c = owner
    created(c.post('/api/admin/roles', json={'id': 'buyer', 'name': '采购员'}))
    actions = ['view', 'operate', 'approve', 'admin']
    assert c.put('/api/admin/grants/buyer/sample-library', json={'actions': actions}).status_code == 200
    matrix = c.get('/api/admin/grants').json()
    assert matrix['actions'] == actions
    assert matrix['grants']['buyer']['sample-library'] == actions
    # 内置办理员的清单默认授权也用 operate，矩阵应原样回传而不是换成 edit。
    assert matrix['grants']['sampleoperator']['sample-library'] == ['view', 'operate']
    stored = {row[0] for row in c.app.state.platform.store._db.execute(
        "select action from role_grants where role_id='buyer' and app_id='sample-library'")}
    assert stored == set(actions)
    assert c.put('/api/admin/grants/buyer/sample-library', json={'actions': ['view', 'edit']}).status_code == 400
    assert c.get('/api/admin/grants').json()['grants']['buyer']['sample-library'] == actions
    assert not c.app.state.platform.store._db.execute("select 1 from role_grants where action='edit'").fetchone()


def test_organization_updates_deletes_and_references(owner):
    c = owner
    parent = created(c.post('/api/admin/org/departments', json={'id': 'parent', 'name': '装配车间'}))
    child = created(c.post('/api/admin/org/departments', json={'id': 'child', 'name': '一班', 'parentId': parent['id']}))
    assert c.patch('/api/admin/org/departments/parent', json={'parentId': child['id']}).status_code == 409
    assert c.patch('/api/admin/org/departments/child', json={'name': '二班', 'parentId': None}).json()['name'] == '二班'
    assert c.delete('/api/admin/org/departments/parent').status_code == 200
    position = created(c.post('/api/admin/org/positions', json={'id': 'job', 'name': '检验岗', 'departmentId': child['id']}))
    assert c.patch('/api/admin/org/positions/job', json={'name': '复核岗'}).json()['name'] == '复核岗'
    user = created(c.post('/api/admin/users', json={'username': 'one', 'name': '虚构甲', 'password': 'sample-pass',
                   'departments': [child['id']], 'positions': [position['id']]}))
    assert c.delete('/api/admin/org/departments/child').status_code == 409
    assert c.delete('/api/admin/org/positions/job').status_code == 409
    assert c.patch(f"/api/admin/users/{user['id']}", json={'departments': [], 'positions': [], 'name': '虚构乙'}).status_code == 200
    assert c.delete('/api/admin/org/positions/job').status_code == 200
    assert c.delete('/api/admin/org/departments/child').status_code == 200
    assert c.patch('/api/admin/org/departments/missing', json={'name': '无'}).status_code == 404
    assert c.post('/api/admin/org/positions', json={'name': '未知部门岗位', 'departmentId': 'missing'}).status_code == 400


def test_role_changes_reset_password_and_member_replacement(owner):
    c = owner
    created(c.post('/api/admin/roles', json={'id': 'reader', 'name': '只读角色'}))
    assert c.patch('/api/admin/roles/reader', json={'name': '查看角色'}).json()['name'] == '查看角色'
    user = created(c.post('/api/admin/users', json={'username': 'reader', 'name': '虚构读者', 'password': 'first-pass', 'roles': ['reader']}))
    assert c.post(f"/api/admin/users/{user['id']}/reset-password", json={'password': 'second-pass'}).status_code == 200
    employee = TestClient(c.app)
    assert employee.post('/api/auth/login', json={'username': 'reader', 'password': 'first-pass'}).status_code == 401
    assert employee.post('/api/auth/login', json={'username': 'reader', 'password': 'second-pass'}).status_code == 200
    assert c.put('/api/admin/grants/reader/*', json={'actions': ['view']}).status_code == 200
    assert employee.get('/api/apps').json()['apps']
    assert c.delete('/api/admin/roles/reader').status_code == 200
    assert employee.get('/api/apps').json()['apps'] == []
    assert c.delete('/api/admin/roles/admin').status_code == 409
    # 替换项目成员必须准确，旧种子的 * 范围在管理员排除该成员时展开为显式范围。
    assert c.put('/api/admin/projects/sample-project/members', json={'members': [user['id']]}).status_code == 200
    projects = c.get('/api/admin/projects').json()['projects']
    assert next(p for p in projects if p['id'] == 'sample-project')['members'] == [user['id']]
    assert employee.get('/api/v1/me').json()['projects'] == ['sample-project']
    assert c.put('/api/admin/projects/sample-project/members', json={'members': []}).status_code == 200
    assert employee.get('/api/v1/me').json()['projects'] == []
    assert c.put('/api/admin/projects/sample-project/members', json={'members': ['missing']}).status_code == 400


def test_last_administrator_and_invalid_input(owner):
    c = owner
    uid = c.get('/api/me').json()['id']
    for patch in ({'roles': []}, {'status': 'disabled'}):
        assert c.patch(f'/api/admin/users/{uid}', json=patch).status_code == 409
    assert c.put('/api/admin/grants/admin/*', json={'actions': ['view']}).status_code == 409
    assert c.get('/api/me').json()['isAdmin'] is True
    assert c.post('/api/admin/users', json={'username': 'owner', 'name': '重名', 'password': 'sample-pass'}).status_code == 409
    assert c.post('/api/admin/users', json={'username': 'short', 'name': '短口令', 'password': 'short'}).status_code == 400
    assert c.patch(f'/api/admin/users/{uid}', json={'roles': ['missing']}).status_code == 400
    assert c.patch(f'/api/admin/users/{uid}', json={'name': None}).status_code == 400
    assert c.put('/api/admin/grants/admin/missing', json={'actions': ['view']}).status_code == 404
    assert c.put('/api/admin/grants/admin/*', json={'actions': ['unknown']}).status_code == 400
    assert c.get('/api/admin/users?status=unknown').status_code == 400


def test_settings_persist_and_expire_session(owner, make_client, monkeypatch):
    from haiknow_core import auth
    now = auth.time.time()
    # SessionMiddleware 只对非空 session 下发 cookie；登录/引导是会话写入边界。
    # 冻结签名与验签共用的时钟，避免慢请求或时钟回拨把 1 分钟会话提前判过期。
    monkeypatch.setattr(auth.time, 'time', lambda: now)
    c = owner
    assert c.post('/api/auth/login', json={'username': 'owner', 'password': 'fixture111111111111'}).status_code == 200
    settings = {'platformName': '虚构平台', 'defaultHome': '#/apps', 'sessionMinutes': 1}
    assert c.put('/api/admin/settings', json=settings).status_code == 200
    assert c.get('/api/admin/settings').json() == settings
    assert c.put('/api/admin/settings', json={'sessionMinutes': 0}).status_code == 400
    restarted = make_client()
    login = restarted.post('/api/auth/login', json={'username': 'owner', 'password': 'fixture111111111111'})
    assert login.status_code == 200
    # 新时长直接作用于登录时下发的会话 cookie；GET /api/me 只读取会话，不承担签发。
    assert 'Max-Age=60' in login.headers['set-cookie']
    assert restarted.get('/api/me').status_code == 200
    assert restarted.get('/api/admin/settings').json() == settings
    monkeypatch.setattr(auth.time, 'time', lambda: now + 62)
    assert restarted.get('/api/me').status_code == 401


def test_audit_failure_rolls_back_identity_mutation(owner, monkeypatch):
    store = owner.app.state.platform.store
    def fail(*args, **kwargs):
        raise RuntimeError('模拟审计失败')
    monkeypatch.setattr(store, 'audit', fail)
    client = TestClient(owner.app, raise_server_exceptions=False)
    client.cookies.update(owner.cookies)
    r = client.post('/api/admin/users', json={'username': 'rollback', 'name': '回滚用户', 'password': 'sample-pass'})
    assert r.status_code == 500
    assert store._db.execute("select id from users where username='rollback'").fetchone() is None


def test_every_admin_route_denies_non_admin(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    for method, path, body in [
        ('GET', 'users', None), ('POST', 'users', {'username': 'x', 'name': '甲', 'password': 'sample-pass'}),
        ('PATCH', 'users/admin', {'name': '甲'}), ('POST', 'users/admin/reset-password', {'password': 'sample-pass'}),
        ('GET', 'org', None), ('POST', 'org/departments', {'name': '甲'}), ('PATCH', 'org/departments/x', {'name': '甲'}),
        ('DELETE', 'org/departments/x', None), ('POST', 'org/positions', {'name': '甲'}),
        ('PATCH', 'org/positions/x', {'name': '甲'}), ('DELETE', 'org/positions/x', None),
        ('GET', 'roles', None), ('POST', 'roles', {'id': 'x', 'name': '甲'}), ('PATCH', 'roles/x', {'name': '甲'}),
        ('DELETE', 'roles/x', None), ('GET', 'grants', None), ('PUT', 'grants/sampleoperator/*', {'actions': []}),
        ('GET', 'projects', None), ('POST', 'projects', {'name': '甲'}), ('PUT', 'projects/sample-project/members', {'members': []}),
        ('GET', 'settings', None), ('PUT', 'settings', {'platformName': '甲'}),
    ]:
        r = c.request(method, '/api/admin/' + path, **({'json': body} if body is not None else {}))
        assert r.status_code == 403, (method, path, r.text)
        assert r.json()['error']['code'] == 'FORBIDDEN'
