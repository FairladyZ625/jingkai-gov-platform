"""应用上架管理：权限、可见性与日志。"""
from test_platform import login


def test_catalog_state_and_audience(make_client):
    c = make_client()
    login(c, 'sampleadmin')
    url = '/api/admin/apps/sample-app'
    assert c.patch(url, json={'state': 'gray', 'audience': [{'type': 'user', 'id': 'sampleoperator'}]}).status_code == 200
    login(c, 'sampleobserver')
    assert 'sample-app' not in [a['id'] for a in c.get('/api/apps').json()['apps']]
    login(c, 'sampleoperator')
    assert 'sample-app' in [a['id'] for a in c.get('/api/apps').json()['apps']]
    assert c.patch(url, json={'state': 'live'}).status_code == 403


def test_states_audience_roles_departments_and_legacy(make_client):
    c = make_client()
    url = '/api/admin/apps/sample-app'
    catalog = lambda: {a['id']: a for a in c.get('/api/apps').json()['apps']}
    login(c, 'sampleadmin')
    assert c.patch(url, json={'state': 'draft'}).status_code == 200
    assert 'sample-app' in catalog()
    login(c, 'sampleoperator')
    assert 'sample-app' not in catalog()
    login(c, 'sampleadmin')
    # 用真实 Directory 验灰度：sampleoperator 的种子角色即 sampleoperator，质量部通过管理接口建立并关联。
    assert c.post('/api/admin/org/departments', json={'id': 'quality', 'name': '质量部'}).status_code == 201
    assert c.patch('/api/admin/users/sampleoperator', json={'departments': ['quality']}).status_code == 200
    for audience in ([{'type': 'role', 'id': 'sampleoperator'}], [{'type': 'dept', 'id': 'quality'}]):
        assert c.patch(url, json={'state': 'gray', 'audience': audience}).status_code == 200
        login(c, 'sampleoperator')
        assert 'sample-app' in catalog()
        login(c, 'sampleobserver')
        assert 'sample-app' not in catalog()
        login(c, 'sampleadmin')
    assert c.patch(url, json={'state': 'disabled', 'disabledReason': '维护'}).status_code == 200
    login(c, 'sampleoperator')
    assert catalog()['sample-app']['available'] is False
    assert c.get('/api/apps/sample-app/records').status_code == 503
    login(c, 'sampleadmin')
    assert c.put('/api/v1/admin/apps/sample-app', json={'enabled': True}).status_code == 200
    assert next(a for a in c.get('/api/admin/apps').json()['apps'] if a['id'] == 'sample-app')['state'] == 'live'
    assert c.put('/api/v1/admin/apps/sample-app', json={'enabled': False}).status_code == 200
    assert next(a for a in c.get('/api/admin/apps').json()['apps'] if a['id'] == 'sample-app')['state'] == 'disabled'
    assert c.patch(url, json={'state': 'live'}).status_code == 200
    login(c, 'sampleobserver')
    assert catalog()['sample-app']['available'] is True
    assert c.get('/api/admin/apps').status_code == 403


def test_rollback_snapshot_survives_restart(make_client, tmp_path):
    import json
    import shutil
    from conftest import ROOT
    apps = tmp_path / 'apps'
    app = apps / 'sample-app'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', app)
    manifest = app / 'app.json'
    data = json.loads(manifest.read_text())
    data['version'] = '1'
    manifest.write_text(json.dumps(data))
    (app / 'web/index.js').write_text('old version')
    c = make_client(apps)
    login(c, 'sampleadmin')
    rollback = '/api/admin/apps/sample-app/rollback'
    assert c.post(rollback).status_code == 409
    (app / 'web/index.js').write_text('new version')
    data['version'] = '2'
    manifest.write_text(json.dumps(data))
    c = make_client(apps)
    login(c, 'sampleadmin')
    assert c.get('/apps/sample-app/web/index.js').text == 'new version'
    assert c.post(rollback).json()['version'] == '1'
    assert c.get('/apps/sample-app/web/index.js').text == 'old version'
    c = make_client(apps)
    login(c, 'sampleadmin')
    assert c.get('/apps/sample-app/web/index.js').text == 'old version'
    assert c.post(rollback).json()['version'] == '2'
    assert c.get('/apps/sample-app/web/index.js').text == 'new version'
    assert any(e['action'] == 'app.rollback' for e in c.get('/api/audit?app_id=platform').json()['items'])


def test_logs_and_statistics(make_client, tmp_path):
    import json
    import shutil
    from conftest import ROOT
    apps = tmp_path / 'apps'
    app = apps / 'bad-app'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', app)
    manifest = app / 'app.json'
    data = json.loads(manifest.read_text())
    data['id'] = 'bad-app'
    manifest.write_text(json.dumps(data))
    (app / 'api/router.py').write_text("from fastapi import APIRouter\nrouter=APIRouter()\n@router.get('/ok')\ndef ok(): return {}\n@router.get('/boom')\ndef boom(): raise RuntimeError('private-stack-input')\n")
    c = make_client(apps)
    login(c, 'sampleoperator')
    assert c.get('/api/apps/bad-app/ok?secret=not-logged').status_code == 200
    assert c.get('/api/apps/bad-app/boom').status_code == 500
    assert c.get('/api/admin/apps/bad-app/stats').status_code == 403
    login(c, 'sampleadmin')
    base = '/api/admin/apps/bad-app'
    logs = c.get(base + '/logs').json()['logs']
    assert [r['status'] for r in logs] == [500, 200]
    assert logs[0]['error'] == 'RuntimeError' and logs[0]['userId'] == 'sampleoperator'
    assert 'secret' not in str(logs) and 'private-stack-input' not in str(logs)
    assert len(c.get(base + '/logs?level=error').json()['logs']) == 1
    assert len(c.get(base + '/logs?level=info&limit=1').json()['logs']) == 1
    assert not c.get(base + '/logs?since=2999-01-01T00:00:00Z').json()['logs']
    stats = c.get(base + '/stats?hours=24').json()
    assert stats['requests'] == 2 and stats['errors'] == 1 and stats['p95ms'] >= 0


def test_demo_gray_disable_rollback_and_logs(make_client, tmp_path):
    import json
    import shutil
    from conftest import ROOT
    apps = tmp_path / 'apps'
    directory = apps / 'sample-app'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', directory)
    manifest = directory / 'app.json'
    doc = json.loads(manifest.read_text())
    doc['version'] = '1'
    manifest.write_text(json.dumps(doc))
    make_client(apps)
    doc['version'] = '2'
    manifest.write_text(json.dumps(doc))
    c = make_client(apps)
    login(c, 'sampleadmin')
    base = '/api/admin/apps/sample-app'
    assert c.patch(base, json={'state': 'gray', 'audience': [{'type': 'user', 'id': 'sampleoperator'}]}).status_code == 200
    login(c, 'sampleobserver')
    assert 'sample-app' not in [a['id'] for a in c.get('/api/apps').json()['apps']]
    login(c, 'sampleadmin')
    assert c.patch(base, json={'state': 'disabled'}).status_code == 200
    login(c, 'sampleoperator')
    assert c.get('/api/apps/sample-app/records').status_code == 503
    login(c, 'sampleadmin')
    assert c.post(base + '/rollback').json()['version'] == '1'
    log = c.get(base + '/logs').json()['logs'][0]
    assert log['status'] == 503 and log['userId'] == 'sampleoperator'
    assert c.patch(base, json={'state': 'invalid'}).status_code == 400


def test_invalid_manifest_version_only_breaks_that_app(make_client, tmp_path):
    """version 非法只让该应用不可用，登录和其它应用不受影响。"""
    import json
    import shutil
    from conftest import ROOT

    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    base = json.loads((apps / 'sample-app/app.json').read_text())
    bad_versions = ['', ' ', 'v1 正式版', '1/2', '-1', 1]
    for i, version in enumerate(bad_versions):
        directory = apps / f'bad-version-{i}'
        directory.mkdir()
        (directory / 'app.json').write_text(
            json.dumps(dict(base, id=f'bad-version-{i}', version=version), ensure_ascii=False))

    c = make_client(apps)
    login(c, 'sampleadmin')
    body = c.get('/api/apps').json()
    assert [a['id'] for a in body['apps']] == ['sample-app']
    assert {b['dir'] for b in body['broken']} == {f'bad-version-{i}' for i in range(len(bad_versions))}
    assert all('version' in b['error'] for b in body['broken'])
    assert c.get('/api/health').json()['broken'] == len(bad_versions)
    # 缺省 version 的存量应用仍登记为上线，版本为 0。
    assert c.get('/api/admin/apps').json()['apps'][0]['version'] == '0'
