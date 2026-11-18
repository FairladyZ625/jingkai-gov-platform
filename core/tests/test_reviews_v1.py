"""确认、跨应用引用和失效通知的端到端与拒绝场景。"""
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT
from test_data_v1 import BASE, record
from test_platform import login


@pytest.fixture
def two_apps(make_client, tmp_path):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    (apps / 'app-b').mkdir()
    m = json.loads((apps / 'sample-app/app.json').read_text())
    m.update(id='app-b', name='演示引用应用')
    (apps / 'app-b/app.json').write_text(json.dumps(m))
    return make_client(apps)


def submit(c, r, assignee='samplereviewer'):
    body = {'appId': r['appId'], 'recordId': r['id'], 'version': r['version']}
    if assignee is not None:
        body['assignee'] = assignee
    return c.post('/api/v1/reviews', json=body)


def decide(c, review, decision='confirm', **kw):
    return c.post(f"/api/v1/reviews/{review['id']}/decisions", json={'version': review['version'], 'decision': decision, 'comment': '演示意见', **kw})


def test_cross_app_reference_invalidation_end_to_end(two_apps):
    c = two_apps
    login(c, 'sampleoperator')
    f = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '凭证'}, files={'file': ('演示.txt', b'demo')}).json()
    a = record(c, files=[f['fileId']], product='sample-item').json()
    review = submit(c, a).json()
    assert c.get(BASE + '/' + a['id']).json()['status'] == 'pending'
    login(c, 'samplereviewer')
    assert c.get('/api/v1/reviews?assignee=me').json()['items'][0]['id'] == review['id']
    assert decide(c, review).status_code == 200
    login(c, 'sampleoperator')
    refs = [{'appId': a['appId'], 'recordId': a['id'], 'version': 1, 'fileId': f['fileId']}]
    b = c.post('/api/v1/apps/app-b/records', json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': refs}).json()
    a2 = c.put(f"{BASE}/{a['id']}", json={'baseVersion': 1, 'data': {'ok': False}}).json()
    assert a2['version'] == 2 and a2['status'] == 'draft'
    assert c.get(f"/api/v1/apps/app-b/records/{b['id']}").json()['status'] == 'recheck'
    notifications = c.get('/api/v1/notifications').json()['items']
    assert len(notifications) == 1
    n = notifications[0]
    assert n['recordId'] == b['id'] and n['appId'] == 'app-b' and not n['read']
    assert n['source'] == {'appId': a['appId'], 'recordId': a['id'], 'version': 1, 'currentVersion': 2}
    assert c.post(f"/api/v1/notifications/{n['id']}/read").json()['read'] is True
    artifacts = c.get('/api/v1/artifacts?project=sample-project&product=sample-item&type=inspection&app=sample-app').json()['items']
    assert len(artifacts) == 1 and artifacts[0]['version'] == 1
    assert artifacts[0]['confirmedBy'] == 'samplereviewer'
    assert artifacts[0]['files'][0]['sha256'] == f['sha256']
    assert c.get(f"{BASE}/{a['id']}/versions/1").json()['status'] == 'confirmed'
    assert c.get(f"/api/v1/files/{f['fileId']}").json()['references'] == [
        {'appId': 'sample-app', 'recordId': a['id'], 'version': 1},
        {'appId': 'app-b', 'recordId': b['id'], 'version': 1},
        {'appId': 'sample-app', 'recordId': a['id'], 'version': 2},
    ]
    login(c, 'samplereviewer')
    assert c.get('/api/v1/notifications?app=app-b').json()['items'][0]['id'] == n['id']
    assert c.get('/api/v1/notifications?app=app-b').json()['items'][0]['read'] is False


def test_self_review_and_no_approve(make_client):
    c = make_client()
    login(c, 'samplereviewer')
    own = record(c).json()
    assert submit(c, own).status_code == 403
    assert submit(c, own).json()['error']['code'] == 'self_review'
    review = submit(c, own, None).json()
    assert decide(c, review).json()['error']['code'] == 'self_review'
    login(c, 'sampleoperator')
    r = record(c).json()
    review = submit(c, r).json()
    denied = decide(c, review)
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'forbidden'


def test_old_version_and_pending_review_are_not_confirmable(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    r = record(c).json()
    review = submit(c, r).json()
    assert submit(c, r).status_code == 409
    c.put(f"{BASE}/{r['id']}", json={'baseVersion': 1, 'data': {}})
    assert c.get(f"{BASE}/{r['id']}/versions/1").json()['status'] == 'recheck'
    submitted = c.get('/api/v1/reviews?mine=submitted').json()['items']
    assert submitted[0]['status'] == 'recheck'
    login(c, 'samplereviewer')
    result = decide(c, review)
    assert result.status_code == 409 and result.json()['error']['code'] == 'stale_version'
    assert c.get('/api/v1/reviews?assignee=me').json()['items'] == []
    assert c.get('/api/v1/artifacts').json()['items'] == []


def test_unconfirmed_out_of_scope_and_unattached_file_references(two_apps):
    c = two_apps
    login(c, 'sampleoperator')
    source = record(c).json()
    def reference(r, **kw):
        return c.post('/api/v1/apps/app-b/records', json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': [{'appId': r['appId'], 'recordId': r['id'], 'version': r['version'], **kw}]})
    assert reference(source).status_code == 422
    review = submit(c, source).json()
    login(c, 'samplereviewer')
    assert decide(c, review).status_code == 200
    login(c, 'sampleoperator')
    f = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '凭证'}, files={'file': ('演示.txt', b'not-attached')}).json()
    assert reference(source, fileId=f['fileId']).status_code == 422
    assert reference(source).status_code == 201
    login(c, 'sampleadmin')
    secret = record(c, project='limited-project').json()
    secret_review = submit(c, secret, None).json()
    # 同项目可确认且有 approve 的另一个演示身份，仅作用于本测试。
    rb = c.app.state.platform.rbac
    with rb.directory.store._db as db:
        db.execute("update users set all_projects=1 where id='samplereviewer'")
    login(c, 'samplereviewer')
    assert decide(c, secret_review).status_code == 200
    login(c, 'sampleoperator')
    assert reference(secret).status_code == 404
    assert c.get('/api/v1/artifacts?project=limited-project').status_code == 404
    assert c.get('/api/v1/artifacts').json()['items'][0]['recordId'] == source['id']
    assert c.get('/api/v1/reviews?mine=submitted').json()['items'][0]['recordId'] == source['id']


def test_return_reassign_and_refresh(two_apps):
    c = two_apps
    login(c, 'sampleoperator')
    r = record(c).json()
    review = submit(c, r).json()
    login(c, 'samplereviewer')
    returned = decide(c, review, 'return')
    assert returned.status_code == 200
    assert c.get(f"{BASE}/{r['id']}").json()['status'] == 'needs_info'
    login(c, 'sampleoperator')
    next_review = submit(c, r).json()
    login(c, 'samplereviewer')
    assert decide(c, next_review, 'reassign', assignee='sampleoperator').status_code == 403
    assert decide(c, next_review, 'reassign', assignee='sampleadmin').status_code == 200
    assert decide(c, next_review).status_code == 403
    login(c, 'sampleadmin')
    assert decide(c, next_review).status_code == 200
    assert decide(c, next_review).status_code == 409


def test_concurrent_writers_have_one_winner(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    r = record(c).json()
    def update(value):
        with TestClient(c.app) as client:
            login(client, 'sampleoperator')
            return client.put(f"{BASE}/{r['id']}", json={'baseVersion': 1, 'data': {'value': value}}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(update, [1, 2])) == [200, 409]
    assert c.get(f"{BASE}/{r['id']}").json()['version'] == 2


def test_only_current_consumers_invalidate_and_refreshed_refs_reset(two_apps):
    c = two_apps
    login(c, 'sampleoperator')
    a = record(c).json()
    review = submit(c, a).json()
    login(c, 'samplereviewer')
    assert decide(c, review).status_code == 200
    login(c, 'sampleoperator')
    bbase = '/api/v1/apps/app-b/records'
    def ref(version):
        return [{'appId': a['appId'], 'recordId': a['id'], 'version': version}]
    b = c.post(bbase, json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': ref(1)}).json()
    # 第一版引用在历史里，当前第二版已移除引用，不应被源改版失效。
    detached = c.put(f"{bbase}/{b['id']}", json={'baseVersion': 1, 'refs': []}).json()
    assert detached['status'] == 'draft'
    linked = c.post(bbase, json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': ref(1)}).json()
    pending = submit(c, linked).json()
    a2 = c.put(f"{BASE}/{a['id']}", json={'baseVersion': 1, 'data': {'changed': True}}).json()
    assert c.get(f"{bbase}/{b['id']}").json()['status'] == 'draft'
    assert c.get(f"{bbase}/{linked['id']}").json()['status'] == 'recheck'
    login(c, 'samplereviewer')
    assert decide(c, pending).status_code == 409
    login(c, 'sampleoperator')
    review2 = submit(c, a2).json()
    login(c, 'samplereviewer')
    assert decide(c, review2).status_code == 200
    login(c, 'sampleoperator')
    fixed = c.put(f"{bbase}/{linked['id']}", json={'baseVersion': 1, 'refs': ref(2)}).json()
    assert fixed['status'] == 'draft' and submit(c, fixed).status_code == 201
    assert [a['version'] for a in c.get('/api/v1/artifacts').json()['items']] == [2]
    assert [a['version'] for a in c.get('/api/v1/artifacts?history=true').json()['items']] == [2, 1]
    assert c.get('/api/v1/artifacts?version=1').json()['items'][0]['version'] == 1


def test_transaction_rolls_back_version_invalidation_notifications_and_audit(two_apps, monkeypatch):
    from haiknow_sdk import DataError
    c = two_apps
    login(c, 'sampleoperator')
    a = record(c).json()
    review = submit(c, a).json()
    login(c, 'samplereviewer')
    decide(c, review)
    login(c, 'sampleoperator')
    b = c.post('/api/v1/apps/app-b/records', json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': [{'appId': a['appId'], 'recordId': a['id'], 'version': 1}]}).json()
    store = c.app.state.platform.store
    before = store.audit_list()
    real = store.audit
    def fail(app_id, user_id, action, detail, **kw):
        real(app_id, user_id, action, detail, **kw)
        if action == 'v1.record.save':
            raise DataError('internal_error', '演示写入失败')
    monkeypatch.setattr(store, 'audit', fail)
    assert c.put(f"{BASE}/{a['id']}", json={'baseVersion': 1, 'data': {}}).status_code == 500
    assert c.get(f"{BASE}/{a['id']}").json()['version'] == 1
    assert c.get(f"/api/v1/apps/app-b/records/{b['id']}").json()['status'] == 'draft'
    assert c.get('/api/v1/notifications').json()['items'] == []
    assert store.audit_list() == before
    assert c.get(f"{BASE}/{a['id']}/versions/2").status_code == 404


def test_scope_and_permission_apply_to_every_resource(two_apps):
    c = two_apps
    login(c, 'sampleadmin')
    a = record(c, project='limited-project').json()
    review = submit(c, a, None).json()
    login(c, 'sampleoperator')
    assert decide(c, review).status_code == 404
    login(c, 'sampleoutsider')
    assert c.get(BASE).status_code == 404
    assert record(c).status_code == 404
    login(c, 'sampleobserver')
    assert decide(c, review).status_code == 404
    login(c, 'sampleoperator')
    a = record(c).json()
    assert submit(c, a, 'sampleobserver').status_code == 403
    assert submit(c, a, 'missing-user').status_code == 404
    review = submit(c, a).json()
    login(c, 'samplereviewer')
    assert decide(c, review, version=2).json()['error']['code'] == 'stale_version'
    assert decide(c, review).status_code == 200
    login(c, 'sampleoperator')
    b = c.post('/api/v1/apps/app-b/records', json={'project': 'limited-project', 'type': 'report', 'data': {}})
    assert b.status_code == 404
    # 可见项目中的通知，对无应用 view 的账号仍不可见。
    b = c.post('/api/v1/apps/app-b/records', json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': [{'appId': a['appId'], 'recordId': a['id'], 'version': 1}]}).json()
    c.put(f"{BASE}/{a['id']}", json={'baseVersion': 1, 'data': {}})
    nid = c.get('/api/v1/notifications').json()['items'][0]['id']
    login(c, 'sampleoutsider')
    assert c.get('/api/v1/notifications').json()['items'] == []
    assert c.post(f'/api/v1/notifications/{nid}/read').status_code == 404
    assert c.get('/api/v1/notifications?app=app-b').status_code == 404
    login(c, 'sampleobserver')
    rb = c.app.state.platform.rbac
    with rb.directory.store._db as db:
        db.execute("delete from project_members where user_id='sampleobserver'")
        db.execute("insert into project_members values ('limited-project','sampleobserver')")
    assert c.post(f'/api/v1/notifications/{nid}/read').status_code == 404


def test_data_persists_across_restart_and_versions_are_unchanged(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    a = record(c).json()
    store = c.app.state.platform.store
    with store._lock:
        original = store._db.execute('select document from v1_versions where record_id=? and version=1', (a['id'],)).fetchone()[0]
    review = submit(c, a).json()
    login(c, 'samplereviewer')
    decide(c, review)
    login(c, 'sampleoperator')
    c.put(f"{BASE}/{a['id']}", json={'baseVersion': 1, 'data': ['演示', 2]})
    restarted = make_client()
    login(restarted, 'sampleoperator')
    assert restarted.get(f"{BASE}/{a['id']}").json()['data'] == ['演示', 2]
    assert restarted.get(f"{BASE}/{a['id']}/versions/1").json()['confirmedBy'] == 'samplereviewer'
    with store._lock:
        assert store._db.execute('select document from v1_versions where record_id=? and version=1', (a['id'],)).fetchone()[0] == original
    actions = {item['action'] for item in store.audit_list()}
    assert {'v1.record.save', 'v1.review.submit', 'v1.review.confirm'} <= actions


def test_invalidated_confirmation_is_not_a_new_shared_artifact(two_apps):
    c = two_apps
    login(c, 'sampleoperator')
    a = record(c).json()
    ra = submit(c, a).json()
    login(c, 'samplereviewer')
    decide(c, ra)
    login(c, 'sampleoperator')
    body = {'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': [{'appId': a['appId'], 'recordId': a['id'], 'version': 1}]}
    b = c.post('/api/v1/apps/app-b/records', json=body).json()
    rb = submit(c, b).json()
    login(c, 'samplereviewer')
    decide(c, rb)
    assert c.get('/api/v1/artifacts?app=app-b').json()['items'][0]['status'] == 'confirmed'
    login(c, 'sampleoperator')
    c.put(f"{BASE}/{a['id']}", json={'baseVersion': 1, 'data': {}})
    assert c.get('/api/v1/artifacts?app=app-b').json()['items'] == []
    historical = c.get(f"/api/v1/apps/app-b/records/{b['id']}/versions/1").json()
    assert historical['status'] == 'recheck' and historical['confirmedBy'] == 'samplereviewer'
    attempt = record(c, refs=[{'appId': 'app-b', 'recordId': b['id'], 'version': 1}])
    assert attempt.status_code == 422 and attempt.json()['error']['code'] == 'invalid_reference'


@pytest.mark.parametrize('hidden_by', ['app', 'project'])
def test_artifact_files_filter_independent_visibility(two_apps, hidden_by):
    from haiknow_sdk.resources import Artifacts

    c = two_apps
    platform = c.app.state.platform
    rb = platform.rbac
    with rb.directory.store._db as db:
        db.execute("insert into project_members values ('sample-project','sampleoutsider')")
    with rb.directory.store._db as db:
        db.execute("update users set all_projects=1 where id='samplereviewer'")
    with rb.directory.store._db as db:
        db.execute("insert into role_grants values ('sampleoutsider','app-b','view')")
    if hidden_by == 'project':
        with rb.directory.store._db as db:
            db.execute("insert into role_grants values ('sampleoutsider','sample-app','view')")
    source_project = 'limited-project' if hidden_by == 'project' else 'sample-project'
    bbase = '/api/v1/apps/app-b/records'
    login(c, 'sampleadmin')
    def upload(app, project, content):
        response = c.post('/api/v1/files', data={'app': app, 'project': project, 'purpose': '演示凭证'},
                          files={'file': ('演示.txt', content)})
        assert response.status_code == 201, response.text
        return response.json()
    hidden = upload('sample-app', source_project, b'source-file')
    source = record(c, project=source_project, files=[hidden['fileId']]).json()
    review = submit(c, source).json()
    login(c, 'samplereviewer')
    assert decide(c, review).status_code == 200
    login(c, 'sampleadmin')
    visible = upload('app-b', 'sample-project', b'target-file')
    target = c.post(bbase, json={'project': 'sample-project', 'type': 'report', 'data': {},
                               'files': [visible['fileId']], 'refs': [
                                   {'appId': source['appId'], 'recordId': source['id'],
                                    'version': 1, 'fileId': hidden['fileId']}]}).json()
    independent = c.post(bbase, json={'project': 'sample-project', 'type': 'report', 'data': {}}).json()
    reviews = [submit(c, r).json() for r in [target, independent]]
    login(c, 'samplereviewer')
    for review in reviews:
        assert decide(c, review).status_code == 200
    authorized = c.get('/api/v1/artifacts?recordId=' + target['id']).json()['items'][0]
    assert {f['fileId'] for f in authorized['files']} == {hidden['fileId'], visible['fileId']}

    login(c, 'sampleoutsider')
    assert c.get(f"{bbase}/{target['id']}").status_code == 200
    for suffix in ['', '/content']:
        denied = c.get(f"/api/v1/files/{hidden['fileId']}" + suffix)
        assert denied.status_code == 404 and denied.json()['error']['code'] == 'not_found'
    assert c.get(f"/api/v1/files/{visible['fileId']}").status_code == 200
    for query in ['', '?app=app-b', '?app=app-b&history=true']:
        result = c.get('/api/v1/artifacts' + query)
        assert result.status_code == 200, result.text
        items = {r['recordId']: r for r in result.json()['items']}
        assert set(items) == {target['id'], independent['id']}
        assert [f['fileId'] for f in items[target['id']]['files']] == [visible['fileId']]
        assert hidden['sha256'] not in result.text
    sdk = Artifacts(platform.data, rb.users['sampleoutsider'])
    assert sdk.find(app='app-b') == c.get('/api/v1/artifacts?app=app-b').json()
    # 过滤只影响本次响应，未移除引用登记或其他用户能看到的文件。
    login(c, 'sampleadmin')
    authorized = c.get('/api/v1/artifacts?recordId=' + target['id']).json()['items'][0]
    assert {f['fileId'] for f in authorized['files']} == {hidden['fileId'], visible['fileId']}


@pytest.mark.parametrize('code,status', [('forbidden', 403), ('internal_error', 500)])
def test_artifact_file_errors_other_than_not_found_surface(make_client, monkeypatch, code, status):
    from haiknow_sdk import DataError

    c = make_client()
    login(c, 'sampleoperator')
    file = c.post('/api/v1/files', data={'app': 'sample-app', 'project': 'sample-project', 'purpose': '演示凭证'},
                  files={'file': ('演示.txt', b'demo')}).json()
    source = record(c, files=[file['fileId']]).json()
    review = submit(c, source).json()
    login(c, 'samplereviewer')
    assert decide(c, review).status_code == 200
    def fail(*args):
        raise DataError(code, '演示文件读取失败')
    monkeypatch.setattr(c.app.state.platform.data, '_file', fail)
    response = c.get('/api/v1/artifacts')
    assert response.status_code == status and response.json()['error']['code'] == code
