"""坏应用、熔断与管理员停用均不影响健康应用。"""
import json
import shutil

import pytest

from conftest import ROOT
from test_platform import login


@pytest.fixture
def unstable(make_client, tmp_path):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    for name, code in [('bad-app', '''
from fastapi import APIRouter, HTTPException
router = APIRouter()
@router.get('/boom')
def boom():
    raise RuntimeError('private-stack-input')
@router.get('/async-boom')
async def async_boom():
    raise ValueError('private-stack-input')
@router.get('/ok')
def ok():
    return {'ok': True}
@router.get('/denied')
def denied():
    raise HTTPException(403, '禁止')
@router.get('/failure')
def failure():
    raise HTTPException(500, '测试失败')
'''), ('import-failure', "raise ImportError('private-import-input')")]:
        p = apps / name
        (p / 'api').mkdir(parents=True)
        m = json.loads((apps / 'sample-app/app.json').read_text())
        (p / 'app.json').write_text(json.dumps({**m, 'id': name, 'sdk': '1'}))
        (p / 'api/router.py').write_text(code)
    return make_client(apps), apps


def test_request_error_envelope_and_cooldown(unstable, monkeypatch):
    from haiknow_core import stability
    c, apps = unstable
    now = [100.0]
    monkeypatch.setattr(stability.time, 'monotonic', lambda: now[0])
    login(c, 'sampleoperator')
    ids = []
    for path in ['/boom', '/async-boom', '/boom']:
        response = c.get('/api/apps/bad-app' + path)
        assert response.status_code == 500
        error = response.json()['error']
        assert error['code'] == 'APP_ERROR' and error['app'] == 'bad-app'
        assert error['requestId'] and 'private' not in response.text and 'Traceback' not in response.text
        ids.append(error['requestId'])
    assert len(set(ids)) == 3
    response = c.get('/api/apps/bad-app/ok')
    assert response.status_code == 503 and response.json()['error']['code'] == 'APP_UNAVAILABLE'
    assert 'Retry-After' in response.headers
    assert 'bad-app' in c.get('/api/health').json()['unavailable']
    assert c.get('/api/apps/sample-app/records').status_code == 200
    now[0] += stability.COOLDOWN_SECONDS + 1
    assert c.get('/api/apps/bad-app/ok').status_code == 200
    assert 'bad-app' not in c.get('/api/health').json()['unavailable']


def test_success_resets_and_permission_errors_do_not_trip(unstable):
    c, _ = unstable
    for _ in range(4):
        assert c.get('/api/apps/bad-app/denied').status_code == 403
    for _ in range(4):
        assert c.get('/api/apps/bad-app/boom').status_code == 500
        assert c.get('/api/apps/bad-app/ok').status_code == 200


def test_explicit_5xx_counts_as_failure(unstable):
    c, _ = unstable
    for _ in range(3):
        assert c.get('/api/apps/bad-app/failure').status_code == 500
    assert c.get('/api/apps/bad-app/ok').status_code == 503


def test_disabled_persists_and_admin_is_required(unstable, make_client):
    c, apps = unstable
    url = '/api/v1/admin/apps/sample-app'
    assert c.put(url, json={'enabled': False}).status_code == 401
    login(c, 'sampleoperator')
    assert c.put(url, json={'enabled': False}).status_code == 403
    login(c, 'sampleadmin')
    assert c.put(url, json={'enabled': 'false'}).status_code == 422
    assert c.put(url, json={'enabled': False}).status_code == 200
    assert c.get('/api/apps/sample-app/records').status_code == 503
    assert c.get('/api/v1/apps/sample-app/records').status_code == 503
    assert c.get('/api/health').json()['ok'] is True
    restarted = make_client(apps)
    login(restarted, 'sampleadmin')
    assert restarted.get('/api/apps/sample-app/records').status_code == 503
    assert restarted.put(url, json={'enabled': True}).status_code == 200
    assert restarted.get('/api/apps/sample-app/records').status_code == 200
    assert restarted.get('/api/apps/bad-app/ok').status_code == 200
    events = restarted.get('/api/audit?app_id=sample-app').json()['items']
    assert {'app.disable', 'app.enable'} <= {e['action'] for e in events}
    assert restarted.put('/api/v1/admin/apps/missing', json={'enabled': False}).status_code == 404


def test_import_failure_returns_503_and_safe_reason(unstable):
    c, _ = unstable
    login(c, 'sampleadmin')
    app = next(a for a in c.get('/api/apps').json()['apps'] if a['id'] == 'import-failure')
    assert app['available'] is False and 'ImportError' in app['error']
    assert 'private-import' not in app['error']
    assert c.get('/api/apps/import-failure/anything').status_code == 503


def test_unavailable_app_is_filtered_from_shared_lists(unstable):
    c, _ = unstable
    login(c, 'sampleoperator')
    created = {}
    for app_id in ['bad-app', 'sample-app']:
        base = '/api/v1/apps/' + app_id + '/records'
        file = c.post('/api/v1/files', data={'app': app_id, 'project': 'sample-project', 'purpose': '隔离测试'},
                      files={'file': ('sample.txt', b'sample')}).json()
        records = [c.post(base, json={'project': 'sample-project', 'type': 'sample', 'data': {}, 'files': [file['fileId']]}).json() for _ in range(2)]
        reviews = [c.post('/api/v1/reviews', json={'appId': app_id, 'recordId': r['id'], 'version': 1, 'assignee': 'samplereviewer'}).json() for r in records]
        created[app_id] = (file, records, reviews)
    login(c, 'samplereviewer')
    for _, _, reviews in created.values():
        assert c.post('/api/v1/reviews/' + reviews[0]['id'] + '/decisions', json={'version': 1, 'decision': 'confirm'}).status_code == 200
    login(c, 'sampleadmin')
    assert c.put('/api/v1/admin/apps/bad-app', json={'enabled': False}).status_code == 200
    login(c, 'samplereviewer')
    for path in ['/api/v1/reviews', '/api/v1/artifacts', '/api/v1/notifications']:
        response = c.get(path)
        assert response.status_code == 200, response.text
        assert all(item['appId'] != 'bad-app' for item in response.json()['items'])
        if path != '/api/v1/notifications':
            assert len(response.json()['items']) == 1
    bad_file = created['bad-app'][0]['fileId']
    assert c.get('/api/v1/files/' + bad_file).status_code == 503
    assert c.get('/api/apps/sample-app/records').status_code == 200
