"""会话代数吊销：登出、改密、管理员重置口令与强制下线后，旧 cookie 立即 401。"""
import json
from base64 import b64encode

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

SESSION_COOKIE = 'haiknow_session'


def cookie_of(client):
    return client.cookies.get(SESSION_COOKIE)


def with_cookie(app, value):
    """模拟被复制的 cookie：另一个客户端只带这枚 cookie。"""
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, value)
    return client


def demo_login(app, user):
    client = TestClient(app)
    assert client.post('/api/auth/login', json={'user_id': user}).status_code == 200
    return client


def test_copied_cookie_is_dead_after_logout(make_client):
    client = make_client()
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    copied = cookie_of(client)
    assert client.get('/api/v1/me').status_code == 200

    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/v1/me').status_code == 401
    assert with_cookie(client.app, copied).get('/api/v1/me').status_code == 401
    # 阴性：同一账号重新登录后的新会话仍然可用。
    again = demo_login(client.app, 'sampleoperator')
    assert again.get('/api/v1/me').status_code == 200


def test_password_change_revokes_sessions_on_other_devices(make_client):
    phone = make_client()
    assert phone.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    laptop = demo_login(phone.app, 'sampleoperator')
    laptop_cookie = cookie_of(laptop)
    assert laptop.get('/api/me').status_code == 200

    assert phone.post('/api/auth/password', json={'old': 'demo1234', 'new': 'changed-pass-123'}).status_code == 200
    # 改密的这台设备继续可用；其他设备与会话副本立即失效。
    assert phone.get('/api/me').status_code == 200
    assert laptop.get('/api/me').status_code == 401
    assert with_cookie(phone.app, laptop_cookie).get('/api/v1/me').status_code == 401
    # 阴性：新口令可以重新登录，旧口令不行。
    assert laptop.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'demo1234'}).status_code == 401
    assert laptop.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'changed-pass-123'}).status_code == 200
    assert laptop.get('/api/me').status_code == 200


def test_admin_password_reset_revokes_target_sessions_only(make_client):
    admin = demo_login(make_client().app, 'sampleadmin')
    employee = demo_login(admin.app, 'sampleoperator')
    bystander = demo_login(admin.app, 'sampleobserver')
    assert employee.get('/api/me').status_code == 200

    body = {'password': 'reset-pass-123'}
    assert admin.post('/api/admin/users/sampleoperator/reset-password', json=body).status_code == 200
    assert employee.get('/api/me').status_code == 401
    # 阴性：其他用户与管理员自己不受影响，目标用户可用新口令重新登录。
    assert bystander.get('/api/me').status_code == 200
    assert admin.get('/api/me').status_code == 200
    assert employee.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'reset-pass-123'}).status_code == 200
    assert employee.get('/api/me').status_code == 200


def test_admin_force_sign_out_revokes_all_sessions_and_records_audit(make_client):
    admin = demo_login(make_client().app, 'sampleadmin')
    employee = demo_login(admin.app, 'sampleoperator')
    bystander = demo_login(admin.app, 'sampleobserver')

    response = admin.post('/api/admin/users/sampleoperator/sign-out')
    assert response.status_code == 200, response.text
    assert response.json() == {'ok': True}
    assert employee.get('/api/me').status_code == 401
    assert employee.get('/api/v1/me').status_code == 401
    # 阴性：其他账号与管理员自己不受影响；被下线账号可再次登录。
    assert bystander.get('/api/me').status_code == 200
    assert admin.get('/api/me').status_code == 200
    assert employee.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    assert employee.get('/api/me').status_code == 200

    audit = admin.get('/api/audit').json()['items']
    assert any(item['action'] == 'identity.user.sign-out' and item['detail']['userId'] == 'sampleoperator' for item in audit)
    # 非管理员 403，账号不存在 404。
    assert employee.post('/api/admin/users/sampleadmin/sign-out').status_code == 403
    assert admin.post('/api/admin/users/missing/sign-out').status_code == 404


def test_session_without_generation_stays_valid_until_revoked(make_client, monkeypatch):
    """上线前签发的会话没有 gen：按 0 处理，不强制全员重登；碰上一次吊销才失效。"""
    monkeypatch.setenv('HAIKNOW_SECRET', 'test-secret')
    client = make_client()
    legacy = TimestampSigner('test-secret').sign(
        b64encode(json.dumps({'uid': 'sampleoperator'}).encode())).decode()
    old = with_cookie(client.app, legacy)
    assert old.get('/api/me').status_code == 200

    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert old.get('/api/me').status_code == 401
    assert old.get('/api/v1/me').status_code == 401