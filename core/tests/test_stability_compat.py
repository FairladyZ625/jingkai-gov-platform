"""冻结夹具通过真实平台装载；平台变动后夹具不跟着改。"""
import shutil

from conftest import ROOT
from test_platform import login

BASE = '/api/apps/sdk1-app'


def test_frozen_sdk1_app(make_client, tmp_path):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/compat/sdk1_app', apps / 'sdk1-app')
    c = make_client(apps)
    assert c.get(BASE + '/context').status_code == 401
    login(c, 'sampleobserver')
    assert c.post(BASE + '/legacy').status_code == 403
    login(c, 'sampleoperator')
    ctx = c.get(BASE + '/context').json()
    assert ctx['user'] == 'sampleoperator' and ctx['approve'] is False
    old = c.post(BASE + '/legacy').json()
    assert old['content'] == 'sdk1' and old['missing'] == 'default'
    assert old['kv']['sdk1-file'] == old['value'] == old['files'][0]['id']
    assert old['available'] is False and old['answer'].startswith('[模拟模型]')
    ai = c.post(BASE + '/ai').json()
    assert ai == {name: {'kind': 'not_configured', 'retryable': False}
                  for name in ['chat', 'image', 'transcribe', 'speech', 'embedding']}
    f = c.post(BASE + '/upload').json()
    rec = c.post(BASE + '/save', json={'project': 'sample-project', 'type': 'sample', 'data': {'value': 1}, 'files': [f['fileId']]}).json()
    assert rec['version'] == 1
    r = c.post(BASE + '/submit', json={'record_id': rec['id'], 'version': 1, 'assignee': 'samplereviewer'})
    assert r.status_code == 200, r.text
    review = r.json()
    login(c, 'samplereviewer')
    assert c.get(BASE + '/context').json()['approve'] is True
    assert c.get(BASE + '/reviews').json()['items'][0]['id'] == review['id']
    result = c.post(BASE + '/decision/' + review['id'], json={'version': 1, 'decision': 'confirm'})
    assert result.status_code == 200, result.text
    assert c.get(BASE + '/artifacts').json()['items'][0]['recordId'] == rec['id']
    login(c, 'sampleoperator')
    target = c.post(BASE + '/save', json={'project': 'sample-project', 'type': 'target', 'data': {},
                    'refs': [{'appId': 'sdk1-app', 'recordId': rec['id'], 'version': 1}]}).json()
    result = c.post(BASE + '/save', json={'id': rec['id'], 'baseVersion': 1, 'data': {'value': 2}})
    assert result.status_code == 200 and result.json()['version'] == 2
    assert c.get(BASE + f"/record/{rec['id']}?version=1").json()['data'] == {'value': 1}
    assert c.get(BASE + f"/record/{rec['id']}").json()['data'] == {'value': 2}
    assert len(c.get(BASE + '/records').json()['items']) == 2
    assert c.get(BASE + f"/record/{target['id']}").json()['status'] == 'recheck'
    note = c.get(BASE + '/notifications').json()['items'][0]
    assert c.post(BASE + '/read/' + note['id']).json()['read'] is True
    conflict = c.post(BASE + '/save', json={'id': rec['id'], 'baseVersion': 1, 'data': {}})
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'version_conflict'
    login(c, 'sampleadmin')
    assert 'sdk1.save' in {x['action'] for x in c.get('/api/audit?app_id=sdk1-app').json()['items']}
