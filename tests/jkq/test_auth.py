"""接口规范 §3.1 验收，使用真实卫华应用及独立的临时 SQLite 库。"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip('fastapi')  # 仓库轻量 CI 只装 pytest；core 门运行本套验收。
from fastapi.testclient import TestClient
from haiknow_core.main import create_app

from jkq.auth import install


ROOT = Path(__file__).resolve().parents[2]
LOGIN = '/api/v1/auth/login'
LOGOUT = '/api/v1/auth/logout'
SESSION = '/api/v1/auth/session'
ME = '/api/v1/me'
PASSWORD = '/api/v1/me/password'
PREFS = '/api/v1/me/prefs'
ROLE = '/api/v1/me/role'
ADMIN = '/api/v1/admin/users'
TEST_PASSWORD = 'test-demo-2026'
ACCOUNTS = {
    'admin': ('admin', '张磊'),
    'leader': ('liyang', '李阳'),
    'member': ('wangmin', '王敏'),
    'partner': ('hejun', '何军'),
}
APPS = ('policy', 'enterprise', 'meeting', 'document', 'kb', 'skills', 'computer')


@pytest.fixture
def instance(tmp_path, monkeypatch, cheap_password_hash):
    now = [1_800_000_000]
    monkeypatch.setenv('HAIKNOW_CONFIG_DIR', str(ROOT / 'config'))
    monkeypatch.setenv('HAIKNOW_DATA_DIR', str(tmp_path / 'db'))
    monkeypatch.setenv('HAIKNOW_APPS_DIR', str(tmp_path / 'apps'))
    monkeypatch.setenv('HAIKNOW_SECRET', 'isolated-test-signing-value')
    monkeypatch.setenv('HAIKNOW_SESSION_COOKIE', 'jkq_test_session')
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN', raising=False)
    monkeypatch.delenv('JKQ_DEMO_MODE', raising=False)
    for role in ACCOUNTS:
        monkeypatch.setenv(f'JKQ_DEMO_{role.upper()}_PASSWORD', TEST_PASSWORD)

    def build(demo=True):
        app = create_app(ROOT)
        platform = app.state.platform
        install(app, demo=demo, clock=lambda: now[0])
        return TestClient(app), platform.store

    return build, now


def assert_public(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert 'password' not in key.casefold()
            assert 'hash' not in key.casefold()
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)
    elif isinstance(value, str):
        assert TEST_PASSWORD not in value
        assert 'scrypt$' not in value


def response(result, status):
    assert result.status_code == status, result.text
    body = result.json()
    assert_public(body)
    return body


def error(result, status, code, details=None):
    data = response(result, status)['error']
    assert data['code'] == code
    assert data['message']
    assert isinstance(data['details'], dict)
    if details is not None:
        assert data['details'] == details
    return data['details']


def login(client, role='member', password=TEST_PASSWORD, path=LOGIN):
    return client.post(path, json={'username': ACCOUNTS[role][0], 'password': password})


@pytest.mark.parametrize(('role', 'wildcard', 'grants'), [
    ('admin', ['view', 'operate', 'approve', 'admin'],
     dict.fromkeys(APPS, ['view', 'operate', 'approve', 'admin'])),
    ('leader', ['view', 'operate', 'approve'], dict.fromkeys(APPS, ['view', 'operate', 'approve'])),
    ('member', [], dict.fromkeys(APPS, ['view', 'operate'])),
    ('partner', [], {
        'policy': ['view'], 'enterprise': ['view'], 'meeting': [], 'document': [],
        'kb': ['view'], 'skills': ['view', 'operate'], 'computer': [],
    }),
])
def test_demo_login_and_matrix(instance, role, wildcard, grants):
    build, _ = instance
    client, _ = build()
    result = login(client, role)
    data = response(result, 200)
    assert set(data) == {'user', 'role', 'grants'}
    assert 'jkq_test_session=' in result.headers['set-cookie']
    assert 'httponly' in result.headers['set-cookie'].lower()
    assert (data['user']['username'], data['user']['name']) == ACCOUNTS[role]
    assert data['user']['role'] == data['role']['id'] == role
    assert data['role']['mask'] is (role == 'partner')
    assert data['grants'] == {'*': wildcard, **grants}
    me = response(client.get(ME), 200)
    assert me['grants'] == data['grants']
    assert me['org']['used'] == 4
    assert response(client.get(SESSION), 200) == {'user': me['user']}


def test_wrong_unknown_and_disabled(instance):
    build, _ = instance
    client, store = build()
    error(login(client, password='test-wrong'), 401, 'BAD_CREDENTIALS')
    error(client.post(LOGIN, json={'username': 'unknown', 'password': TEST_PASSWORD}), 401, 'BAD_CREDENTIALS')
    with store._lock, store._db as db:
        db.execute("update users set status='disabled' where username='wangmin'")
    error(login(client), 403, 'ACCOUNT_DISABLED')
    assert response(client.get(SESSION), 200) == {'user': None}


def test_login_lock_survives_restart_and_clears_at_ten_minutes(instance):
    build, now = instance
    client, _ = build()
    for _ in range(5):
        error(login(client, password='test-wrong'), 401, 'BAD_CREDENTIALS')
    expected = now[0] + 600
    client, _ = build()
    details = error(login(client, path='/api/auth/login'), 409, 'LOCKED')
    assert datetime.fromisoformat(details['retryAt']).timestamp() == expected
    now[0] += 599
    error(login(client), 409, 'LOCKED')
    now[0] += 1
    response(login(client), 200)


def test_success_clears_four_failures(instance):
    build, _ = instance
    client, _ = build()
    for _ in range(2):
        for _ in range(4):
            error(login(client, password='test-wrong'), 401, 'BAD_CREDENTIALS')
        response(login(client), 200)


def test_anonymous_session_and_private_endpoints(instance):
    build, _ = instance
    client, store = build()
    assert response(client.get(SESSION), 200) == {'user': None}
    error(client.get(ME), 401, 'UNAUTHENTICATED')
    error(client.get(ADMIN), 401, 'UNAUTHENTICATED')
    error(client.put(PASSWORD, json={'old': TEST_PASSWORD, 'new': 'sample'}), 401, 'UNAUTHENTICATED')
    error(client.patch(PREFS, json={'theme': 'dark'}), 401, 'UNAUTHENTICATED')
    error(client.put(ROLE, json={'role': 'leader'}), 401, 'UNAUTHENTICATED')
    assert response(client.post(LOGOUT), 200) == {'ok': True}
    assert not store.audit_list()


def test_change_password_revokes_other_sessions_and_old_password(instance):
    build, _ = instance
    client, _ = build()
    other = TestClient(client.app)
    response(login(client), 200)
    response(login(other), 200)
    error(client.put(PASSWORD, json={'old': 'wrong', 'new': '123456'}), 400, 'BAD_PASSWORD')
    error(client.put(PASSWORD, json={'old': TEST_PASSWORD, 'new': '12345'}), 400, 'WEAK_PASSWORD')
    assert response(client.put(PASSWORD, json={'old': TEST_PASSWORD, 'new': '123456'}), 200) == {'ok': True}
    response(client.get(ME), 200)
    error(other.get(ME), 401, 'UNAUTHENTICATED')
    error(login(other), 401, 'BAD_CREDENTIALS')
    response(login(other, password='123456'), 200)


def test_prefs_patch_merge_per_user_and_persistence(instance):
    build, _ = instance
    client, _ = build()
    response(login(client), 200)
    assert response(client.patch(PREFS, json={'theme': 'dark'}), 200) == {'prefs': {'theme': 'dark'}}
    prefs = {'theme': 'dark', 'defaultModel': 'local-model', 'operatorEnabled': False}
    response(client.patch(PREFS, json={'defaultModel': 'local-model', 'operatorEnabled': False}), 200)
    response(login(client, 'partner'), 200)
    assert response(client.get(ME), 200)['prefs'] == {}
    client, _ = build()
    response(login(client), 200)
    assert response(client.get(ME), 200)['prefs'] == prefs


@pytest.mark.parametrize(('method', 'path', 'body'), [
    ('post', LOGIN, {'username': 'wangmin', 'password': [TEST_PASSWORD]}),
    ('post', LOGIN, {'user_id': 'u-wangmin'}),
    ('put', PASSWORD, {'old': TEST_PASSWORD, 'new': [TEST_PASSWORD]}),
    ('patch', PREFS, {'operatorEnabled': TEST_PASSWORD}),
    ('patch', PREFS, {'theme': None}),
    ('put', ROLE, {'role': [TEST_PASSWORD]}),
])
def test_validation_never_echoes_input(instance, method, path, body):
    build, _ = instance
    client, _ = build()
    response(login(client), 200)
    error(getattr(client, method)(path, json=body), 400, 'INVALID_REQUEST', {})


def test_demo_role_switch_changes_server_permissions_and_preserves_identity(instance):
    build, _ = instance
    client, _ = build()
    original = response(login(client, 'partner'), 200)['user']
    changed = response(client.put(ROLE, json={'role': 'leader'}), 200)
    assert changed['user']['id'] == original['id']
    assert changed['role']['id'] == 'leader'
    assert changed['grants']['document'] == ['view', 'operate', 'approve']
    assert response(client.get(ME), 200)['role']['id'] == 'leader'
    response(client.put(ROLE, json={'role': 'admin'}), 200)
    response(client.get(ADMIN), 200)


def test_production_role_always_404_and_demo_sessions_are_rejected(instance):
    build, _ = instance
    demo, _ = build()
    response(login(demo), 200)
    prod, _ = build(demo=False)
    prod.cookies.update(demo.cookies)
    error(prod.put(ROLE, content='malformed-json'), 404, 'NOT_FOUND', {})
    assert response(prod.get(SESSION), 200) == {'user': None}
    error(login(prod), 401, 'BAD_CREDENTIALS')
    response(prod.post('/api/auth/bootstrap', json={
        'username': 'operator', 'name': '测试管理员', 'password': TEST_PASSWORD,
    }), 200)
    response(prod.get(ME), 200)
    error(prod.put(ROLE, json={'role': 'leader'}), 404, 'NOT_FOUND', {})
    response(prod.post(LOGOUT), 200)
    response(prod.post(LOGIN, json={'username': 'operator', 'password': TEST_PASSWORD}), 200)
    response(prod.get(ADMIN), 200)


@pytest.mark.parametrize('path', [ADMIN, '/api/admin/users'])
def test_login_admin_denial_logout_are_audited_once(instance, path):
    build, _ = instance
    client, store = build()
    response(login(client, 'partner'), 200)
    clone = TestClient(client.app, cookies=dict(client.cookies))
    error(client.get(path), 403, 'FORBIDDEN', {'app': '*', 'need': 'admin'})
    result = client.post(LOGOUT)
    assert response(result, 200) == {'ok': True}
    assert 'jkq_test_session=null' in result.headers['set-cookie']
    assert response(client.get(SESSION), 200) == {'user': None}
    assert response(clone.get(SESSION), 200) == {'user': None}
    response(client.post(LOGOUT), 200)
    rows = store.audit_list()
    assert [(row['action'], row['user']) for row in rows] == [
        ('logout', 'u-hejun'), ('permission.denied', 'u-hejun'), ('login', 'u-hejun'),
    ]
    assert rows[1]['detail'] == {'app': '*', 'need': 'admin'}
    assert_public(rows)


def test_generated_password_once_then_environment_does_not_overwrite(instance, monkeypatch, capsys):
    build, _ = instance
    monkeypatch.delenv('JKQ_DEMO_MEMBER_PASSWORD')
    monkeypatch.setattr(sys.stderr, 'isatty', lambda: True)
    client, store = build()
    captured = capsys.readouterr()
    assert not captured.out
    line, = captured.err.splitlines()
    generated = line.removeprefix('经开区演示账号 wangmin 的首次口令：')
    assert line != generated and len(generated) >= 18
    assert generated.encode() not in (store.data_dir / 'platform.db').read_bytes()
    response(login(client, password=generated), 200)
    response(login(client, 'admin'), 200)
    client, _ = build()
    assert capsys.readouterr().err == ''
    monkeypatch.setenv('JKQ_DEMO_MEMBER_PASSWORD', TEST_PASSWORD)
    client, _ = build()
    assert capsys.readouterr().err == ''
    response(login(client, password=generated), 200)


def test_unavailable_terminal_rolls_back_seed(instance, monkeypatch, tmp_path):
    build, _ = instance
    monkeypatch.delenv('JKQ_DEMO_MEMBER_PASSWORD')
    monkeypatch.setattr(sys.stderr, 'isatty', lambda: False)
    with pytest.raises(RuntimeError, match='JKQ_DEMO_MEMBER_PASSWORD'):
        build()
    with sqlite3.connect(tmp_path / 'db/platform.db') as db:
        assert db.execute('select count(*) from users').fetchone() == (0,)
