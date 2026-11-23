"""真实口令、首管引导、锁定、开发入口与禁用身份。"""
import hashlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient


def bootstrap(client, username='owner'):
    return client.post('/api/auth/bootstrap', json={'username': username, 'name': '虚构管理员', 'password': 'fixture111111111111'})


def test_password_hash_salt_and_verification():
    from haiknow_core.passwords import hash_password, verify_password
    first, second = hash_password('sample-pass'), hash_password('sample-pass')
    assert first != second and 'sample-pass' not in first
    assert verify_password('sample-pass', first)
    assert not verify_password('wrong-pass', first)


def test_production_scrypt_cost_is_unchanged_in_clean_process():
    """测试夹具把 scrypt 成本降到最低；这里在没有夹具的干净进程里确认生产参数仍是 n=16384,r=8,p=1，
    且生产散列与标准库 scrypt 的同参数结果逐位一致。"""
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; sys.path[:0] = [sys.argv[1]]\n"
        "from haiknow_core import passwords as p\n"
        "print(p.SCRYPT_N, p.SCRYPT_R, p.SCRYPT_P)\n"
        "print(p.hash_password('sample-pass'))\n"
    )
    out = subprocess.run([sys.executable, '-I', '-c', code, str(root / 'core' / 'server')],
                         check=True, capture_output=True, text=True).stdout.splitlines()
    assert out[0] == '16384 8 1'
    _, salt, digest = out[1].split('$')
    assert digest == hashlib.scrypt(b'sample-pass', salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def test_production_bootstrap_once_and_password(make_client, monkeypatch):
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN')
    client = make_client()
    assert client.get('/api/auth/state').json() == {'needsBootstrap': True, 'demoLogin': False}
    assert client.get('/api/auth/users').status_code == 404
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 401
    assert bootstrap(client).status_code == 200
    me = client.get('/api/me').json()
    assert me['isAdmin'] and me['username'] == 'owner'
    assert me['departments'] == [] and me['positions'] == []
    assert me['projects'][0]['id'] == 'sample-project'
    assert client.get('/api/auth/state').json()['needsBootstrap'] is False
    assert bootstrap(client, 'second').status_code == 409
    assert client.post('/api/auth/password', json={'old': 'wrong', 'new': 'changed-123'}).status_code == 401
    assert client.post('/api/auth/password', json={'old': 'fixture111111111111', 'new': 'short'}).status_code == 400
    assert client.post('/api/auth/password', json={'old': 'fixture111111111111', 'new': 'changed-123'}).status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/me').status_code == 401
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': 'fixture111111111111'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': 'changed-123'}).status_code == 200
    raw = client.app.state.platform.store._db.execute('select password_hash,last_login from users').fetchone()
    assert 'changed-123' not in raw[0] and 'T' in raw[1]
    audit = client.app.state.platform.store.audit_list()
    assert {'auth.bootstrap', 'auth.password', 'login', 'logout'} <= {a['action'] for a in audit}
    assert 'changed-123' not in str(audit) and 'fixture111111111111' not in str(audit)


def test_lock_persists_across_restart_and_expires(make_client, monkeypatch):
    from haiknow_core import auth
    client = make_client()
    now = auth.time.time()
    monkeypatch.setattr(auth.time, 'time', lambda: now)
    for attempt in range(5):
        r = client.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'wrong'})
        assert r.status_code == (423 if attempt == 4 else 401)
    restarted = make_client()
    locked = restarted.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'demo1234'})
    assert locked.status_code == 423 and locked.json()['error']['code'] == 'LOCKED'
    assert restarted.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 423
    monkeypatch.setattr(auth.time, 'time', lambda: now + 301)
    assert restarted.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'demo1234'}).status_code == 200
    with restarted.app.state.platform.store._db as db:
        db.execute("update users set status='disabled' where id='sampleoperator'")
    assert restarted.get('/api/me').status_code == 401
    assert restarted.get('/api/v1/me').status_code == 401
    assert restarted.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'demo1234'}).status_code == 401


def test_concurrent_bootstrap_has_one_winner(make_client, monkeypatch):
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN')
    app = make_client().app
    def create(index):
        with TestClient(app) as client:
            return bootstrap(client, f'owner{index}').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == [200, 409]


def test_demo_list_and_strict_login_body(make_client, monkeypatch):
    client = make_client()
    assert client.get('/api/auth/state').json() == {'needsBootstrap': False, 'demoLogin': True}
    demo_users = client.get('/api/auth/users').json()
    assert len(demo_users) == 6
    reviewer = next(user for user in demo_users if user['id'] == 'samplereviewer')
    assert reviewer['position'] == '样例审核员'
    assert {app['id'] for app in reviewer['approveApps']} == {'sample-app', 'sample-library'}
    assert client.post('/api/auth/login', json={'username': 'sampleoperator'}).status_code == 400
    assert client.post('/api/auth/login', json={'user_id': 'sampleadmin', 'username': 'sampleoperator', 'password': 'demo1234'}).status_code == 400
    assert client.post('/api/auth/login', json={'username': 'missing', 'password': 'unknown'}).json()['error']['code'] == 'INVALID_CREDENTIALS'
    assert client.post('/api/auth/login', json={'username': 'sampleoperator', 'password': 'demo1234'}).status_code == 200
    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN')
    restarted = make_client()
    assert restarted.get('/api/auth/users').status_code == 404
    assert restarted.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 401


def test_demo_identities_cannot_authenticate_after_restart(make_client, monkeypatch):
    monkeypatch.setenv('HAIKNOW_SECRET', 'test-session-signing')
    demo_admin = make_client()
    assert demo_admin.post('/api/auth/login', json={'user_id': 'sampleadmin'}).status_code == 200
    assert demo_admin.get('/api/v1/me').status_code == 200
    regular = {'username': 'worker', 'password': 'worker-pass-123'}
    assert demo_admin.post('/api/admin/users', json={**regular, 'name': '虚构办理员'}).status_code == 201
    regular_client = TestClient(demo_admin.app)
    assert regular_client.post('/api/auth/login', json=regular).status_code == 200

    monkeypatch.delenv('HAIKNOW_DEMO_LOGIN')
    restarted = make_client()
    restarted.cookies.update(demo_admin.cookies)
    assert restarted.get('/api/auth/state').json() == {'needsBootstrap': True, 'demoLogin': False}
    for url in ('/api/me', '/api/v1/me'):
        assert restarted.get(url).status_code == 401
    for login in ({'user_id': 'sampleadmin'}, {'username': 'sampleadmin', 'password': 'demo1234'}):
        response = restarted.post('/api/auth/login', json=login)
        assert response.status_code == 401
        assert response.json()['error']['code'] == 'INVALID_CREDENTIALS'

    worker = TestClient(restarted.app)
    worker.cookies.update(regular_client.cookies)
    assert worker.get('/api/v1/me').status_code == 200
    assert worker.post('/api/auth/login', json=regular).status_code == 200
    assert bootstrap(restarted).status_code == 200
    uid = restarted.get('/api/me').json()['id']
    disabled = restarted.patch(f'/api/admin/users/{uid}', json={'status': 'disabled'})
    assert disabled.status_code == 409
    assert disabled.json()['error']['code'] == 'LAST_ADMIN'
