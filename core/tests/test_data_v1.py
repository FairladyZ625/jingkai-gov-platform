"""数据底座真实 HTTP 与 SDK 验收；样例全部虚构。"""
import hashlib

from test_platform import login

BASE = '/api/v1/apps/sample-app/records'


def record(c, **kw):
    return c.post(BASE, json={'project': 'sample-project', 'type': 'inspection', 'data': {'ok': True}, **kw})


def test_v1_identity_and_unauthenticated(make_client):
    c = make_client()
    r = c.get('/api/v1/me')
    assert r.status_code == 401
    assert r.json()['error']['code'] == 'UNAUTHENTICATED'
    login(c, 'sampleoperator')
    assert c.get('/api/v1/me').json()['projects'] == ['sample-project']
    assert len(c.get('/api/v1/projects').json()['companies'][0]['projects']) == 1


def test_versions_conflict_and_server_identity(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    r = record(c, submitter='sampleadmin', company='client-company').json()
    assert r['version'] == 1 and r['status'] == 'draft'
    assert r['submitter'] == 'sampleoperator' and r['company'] == 'sample-company'
    changed = c.put(f"{BASE}/{r['id']}", json={'baseVersion': 1, 'data': {'ok': False}})
    assert changed.status_code == 200 and changed.json()['version'] == 2
    conflict = c.put(f"{BASE}/{r['id']}", json={'baseVersion': 1, 'data': {}})
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'VERSION_CONFLICT'
    assert conflict.json()['error']['currentVersion'] == 2
    assert c.get(f"{BASE}/{r['id']}/versions/1").json()['data'] == {'ok': True}
    assert c.put(f"{BASE}/{r['id']}", json={'data': {}}).status_code == 422


def test_scope_hides_records_and_files(make_client):
    c = make_client()
    login(c, 'sampleadmin')
    r = record(c, project='limited-project').json()
    f = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'limited-project', 'purpose': '凭证'}, files={'file': ('演示.txt', b'demo')}).json()
    login(c, 'sampleoperator')
    for url in [f"{BASE}/{r['id']}", f"{BASE}/{r['id']}/versions/1", f"/api/v1/files/{f['fileId']}", f"/api/v1/files/{f['fileId']}/content"]:
        result = c.get(url)
        assert result.status_code == 404 and result.json()['error']['code'] == 'NOT_FOUND'
    assert c.get(BASE, params={'project': 'limited-project'}).status_code == 404
    assert record(c, project='limited-project').status_code == 404


def test_file_hash_immutable_and_references(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    def upload():
        return c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '凭证'}, files={'file': ('演示.txt', b'demo')}).json()
    a, b = upload(), upload()
    assert a['sha256'] == b['sha256'] == hashlib.sha256(b'demo').hexdigest()
    assert a['fileId'] != b['fileId'] and a['size'] == 4
    r = record(c, files=[a['fileId']]).json()
    assert c.get(f"/api/v1/files/{a['fileId']}/content").content == b'demo'
    meta = c.get(f"/api/v1/files/{a['fileId']}").json()
    assert meta['references'] == [{'appId': 'sample-app', 'recordId': r['id'], 'version': 1}]
    assert c.put(f"/api/v1/files/{a['fileId']}", json={}).status_code == 405
    login(c, 'sampleobserver')
    assert record(c).status_code == 403


def test_invalid_product_files_and_server_errors(make_client, monkeypatch):
    from fastapi.testclient import TestClient
    c = make_client()
    login(c, 'sampleoperator')
    assert record(c, product='research-product').status_code == 422
    assert record(c, files=['missing-file']).status_code == 404
    assert c.post('/api/v1/files', data={}).json()['error']['code'] == 'INVALID_REQUEST'
    assert c.get('/api/v1/missing').json()['error']['code'] == 'NOT_FOUND'
    assert c.post(BASE, content='{', headers={'Content-Type': 'application/json'}).status_code == 422
    def fail(*args, **kw):
        raise RuntimeError('内部数据库细节')
    monkeypatch.setattr(c.app.state.platform.data, 'list_records', fail)
    with TestClient(c.app, raise_server_exceptions=False) as client:
        login(client, 'sampleoperator')
        r = client.get(BASE)
        assert r.status_code == 500 and r.json()['error']['code'] == 'INTERNAL_ERROR'
        assert '内部数据库细节' not in r.text
