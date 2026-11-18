"""应用自管审核隔离通用 HTTP 写入，应用后端 SDK 保持原权限规则。"""
import json
import sqlite3

import pytest

from conftest import ROOT
from haiknow_core import manifest
from test_platform import login
from test_v1_sdk import SDK_ROUTER


@pytest.fixture
def review_apps(make_client, tmp_path):
    apps = tmp_path / 'apps'
    base = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    for app_id, mode in [('managed-app', 'app'), ('plain-app', 'platform')]:
        p = apps / app_id
        (p / 'api').mkdir(parents=True)
        m = {**base, 'id': app_id}
        if mode == 'app':
            m['review'] = mode
        (p / 'app.json').write_text(json.dumps(m))
        (p / 'api/router.py').write_text(SDK_ROUTER)
    return make_client(apps)


def save(c, app_id='managed-app', project='sample-project', **body):
    r = c.post(f'/api/apps/{app_id}/save', json={'project': project, 'type': 'example', 'data': {}, **body})
    assert r.status_code == 200, r.text
    return r.json()


def preview_decide(c, review, *, app_id='managed-app', decision='confirm', **body):
    return c.post(f'/api/apps/{app_id}/preview-decision/{review["id"]}', json={
        'version': review['version'], 'decision': decision, **body})


def sdk_submit(c, record, **kw):
    return c.post(f"/api/apps/{record['appId']}/submit", json={
        'record_id': record['id'], 'version': record['version'], 'assignee': 'samplereviewer', **kw})


def generic_submit(c, record, **kw):
    return c.post('/api/v1/reviews', json={
        'appId': record['appId'], 'recordId': record['id'], 'version': record['version'], **kw})


def assert_app_required(response):
    assert response.status_code == 409, response.text
    error = response.json()['error']
    assert error['code'] == 'invalid_state'
    assert '请在应用内处理' in error['message']
    assert error['appId'] == 'managed-app' and error['appUrl'] == '#/app/managed-app'


def test_managed_submit_rejected_without_side_effects(review_apps):
    c = review_apps
    login(c, 'sampleoperator')
    record = save(c)
    before = c.app.state.platform.store.audit_list()
    assert_app_required(generic_submit(c, record, generic_http=False, review='platform'))
    assert c.get(f"/api/v1/apps/managed-app/records/{record['id']}").json()['status'] == 'draft'
    assert c.get('/api/v1/reviews?mine=submitted').json()['items'] == []
    assert c.app.state.platform.store.audit_list() == before
    assert sdk_submit(c, record).status_code == 200


@pytest.mark.parametrize('decision', ['confirm', 'return', 'reassign'])
def test_managed_existing_todo_cannot_be_decided_over_http(review_apps, decision):
    c = review_apps
    login(c, 'sampleoperator')
    record = save(c)
    # 包括启用清单声明前已经产生的待办；按当前清单判定，不存储模式快照。
    entry = c.app.state.platform.apps['managed-app']
    entry.manifest.pop('review')
    review = generic_submit(c, record, assignee='samplereviewer').json()
    entry.manifest['review'] = 'app'
    login(c, 'samplereviewer')
    todo = c.get('/api/v1/reviews?assignee=me').json()['items'][0]
    assert todo['review'] == 'app' and todo['project'] == 'sample-project'
    before = c.app.state.platform.store.audit_list()
    body = {'version': 1, 'decision': decision, 'assignee': 'sampleadmin',
            'appId': 'plain-app', 'generic_http': False}
    assert_app_required(c.post(f"/api/v1/reviews/{review['id']}/decisions", json=body))
    assert c.get('/api/v1/reviews').json()['items'][0]['decisions'] == []
    assert c.app.state.platform.store.audit_list() == before
    result = c.post(f"/api/apps/managed-app/decision/{review['id']}", json={
        'version': 1, 'decision': decision, 'assignee': 'sampleadmin'})
    assert result.status_code == 200, result.text


def test_plain_generic_flow_and_independent_reviewer_rules(review_apps):
    c = review_apps
    login(c, 'samplereviewer')
    own = save(c, 'plain-app')
    assert generic_submit(c, own, assignee='samplereviewer').json()['error']['code'] == 'self_review'
    review = generic_submit(c, own).json()
    response = c.post(f"/api/v1/reviews/{review['id']}/decisions", json={'version': 1, 'decision': 'confirm'})
    assert response.status_code == 403 and response.json()['error']['code'] == 'self_review'
    login(c, 'sampleoperator')
    record = save(c, 'plain-app')
    sent = generic_submit(c, record, assignee='samplereviewer')
    assert sent.status_code == 201, sent.text
    path = f"/api/v1/reviews/{sent.json()['id']}/decisions"
    assert c.post(path, json={'version': 1, 'decision': 'confirm'}).status_code == 403
    login(c, 'samplereviewer')
    assert c.get('/api/v1/reviews').json()['items'][0]['review'] == 'platform'
    assert c.post(path, json={'version': 1, 'decision': 'confirm'}).json()['status'] == 'confirmed'


def test_managed_sdk_keeps_scope_assignee_and_self_review_rules(review_apps):
    c = review_apps
    login(c, 'samplereviewer')
    own = save(c)
    assert sdk_submit(c, own).json()['error']['code'] == 'self_review'
    review = sdk_submit(c, own, assignee=None).json()
    path = f"/api/apps/managed-app/decision/{review['id']}"
    self_result = c.post(path, json={'version': 1, 'decision': 'confirm'})
    assert self_result.status_code == 403 and self_result.json()['error']['code'] == 'self_review'
    login(c, 'sampleadmin')
    hidden = save(c, project='limited-project')
    login(c, 'sampleoperator')
    assert generic_submit(c, hidden).status_code == 404
    assert sdk_submit(c, hidden).status_code == 404
    r = save(c)
    review = sdk_submit(c, r).json()
    login(c, 'sampleadmin')
    assert c.post(f"/api/apps/managed-app/decision/{review['id']}", json={'version': 1, 'decision': 'confirm'}).status_code == 403
    login(c, 'samplereviewer')
    assert c.post(f"/api/apps/plain-app/decision/{review['id']}", json={'version': 1, 'decision': 'confirm'}).status_code == 404
    assert c.post(f"/api/apps/managed-app/decision/{review['id']}", json={'version': 1, 'decision': 'confirm'}).status_code == 200


@pytest.mark.parametrize('decision,status', [('confirm', 'confirmed'), ('return', 'needs_info')])
def test_preview_decide_requires_current_source_version_without_side_effects(review_apps, decision, status):
    """应用读旧来源 → 另一请求改版 → 决定带前置条件：同事务拒绝，不写决定/状态/待办/审计。"""
    c = review_apps
    login(c, 'sampleoperator')
    source = save(c, type='source')
    quote = save(c, type='quote')
    review = sdk_submit(c, quote).json()
    # 应用在决定接口里读到的来源版本。
    assert c.get(f'/api/apps/managed-app/record/{source["id"]}').json()['version'] == 1
    # 两次调用之间，另一请求把来源改成 v2。
    assert save(c, id=source['id'], baseVersion=1, data={'changed': True})['version'] == 2

    login(c, 'samplereviewer')
    before = c.app.state.platform.store.audit_list()
    stale = preview_decide(c, review, decision=decision, require=[
        {'recordId': source['id'], 'version': 1, 'status': 'draft'},
    ])
    assert stale.status_code == 409, stale.text
    error = stale.json()['error']
    assert error['code'] == 'stale_version'
    assert error['recordId'] == source['id'] and error['currentVersion'] == 2
    # 无副作用：决定、记录状态、审计都不写。
    assert c.get('/api/v1/reviews?assignee=me').json()['items'][0]['decisions'] == []
    assert c.get(f'/api/v1/apps/managed-app/records/{quote["id"]}').json()['status'] == 'pending'
    assert c.app.state.platform.store.audit_list() == before

    # 带当前来源版本重试才生效。
    accepted = preview_decide(c, review, decision=decision, require=[
        {'recordId': source['id'], 'version': 2, 'status': 'draft'},
    ])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['status'] == status


def test_preview_decide_checks_status_and_read_scope(review_apps):
    c = review_apps
    login(c, 'sampleoperator')
    source = save(c, type='source')
    quote = save(c, type='quote')
    review = sdk_submit(c, quote).json()

    login(c, 'samplereviewer')
    wrong_status = preview_decide(c, review, require=[
        {'recordId': source['id'], 'version': 1, 'status': 'confirmed'},
    ])
    assert wrong_status.status_code == 409, wrong_status.text
    error = wrong_status.json()['error']
    assert error['code'] == 'invalid_state'
    assert error['recordId'] == source['id'] and error['status'] == 'draft'

    # 不存在与越权引用都按不存在处理，不泄露来源是否存在。
    login(c, 'sampleadmin')
    hidden = save(c, project='limited-project')
    login(c, 'samplereviewer')
    for record_id in ['no-such-record', hidden['id']]:
        missing = preview_decide(c, review, require=[{'recordId': record_id, 'version': 1}])
        assert missing.status_code == 404, missing.text
        assert missing.json()['error']['code'] == 'not_found'

    # 同项目内的其他应用记录可以显式 appId 引用；省略 appId 默认取待办所属应用。
    login(c, 'sampleoperator')
    peer = save(c, 'plain-app')
    login(c, 'samplereviewer')
    accepted = preview_decide(c, review, require=[
        {'appId': 'plain-app', 'recordId': peer['id'], 'version': 1, 'status': 'draft'},
    ])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['status'] == 'confirmed'


def test_decide_holds_write_transaction_between_source_check_and_commit(review_apps, monkeypatch):
    """检查通过后用独立连接改来源：写事务提交前，另一个连接的写入被 SQLite 阻塞。"""
    c = review_apps
    login(c, 'sampleoperator')
    source = save(c, type='source')
    quote = save(c)
    review = sdk_submit(c, quote).json()
    login(c, 'samplereviewer')
    data = c.app.state.platform.data
    db_path = data.store.data_dir / 'platform.db'
    real = data._require_sources

    def bump_source_after_check(*args, **kwargs):
        real(*args, **kwargs)
        assert args[0].in_transaction, '前置条件读取必须在写事务内'
        other = sqlite3.connect(db_path, timeout=0.1)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('update v1_records set latest=2 where id=?', (source['id'],))
                other.commit()
        finally:
            other.close()

    monkeypatch.setattr(data, '_require_sources', bump_source_after_check)
    response = preview_decide(c, review, require=[
        {'recordId': source['id'], 'version': 1, 'status': 'draft'},
    ])
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'confirmed'
    # 竞争写入没有落地，决定基于检查时看到的 v1。
    assert c.get(f'/api/v1/apps/managed-app/records/{source["id"]}').json()['version'] == 1


def test_submit_holds_write_transaction_between_record_read_and_todo(review_apps, monkeypatch):
    """送审读到记录后用独立连接改版：写事务提交前，另一个连接的写入被阻塞。"""
    c = review_apps
    login(c, 'sampleoperator')
    source = save(c, type='source')
    quote = save(c)
    data = c.app.state.platform.data
    db_path = data.store.data_dir / 'platform.db'
    real = data._assignee

    def bump_source_after_read(*args, **kwargs):
        real(*args, **kwargs)
        other = sqlite3.connect(db_path, timeout=0.1)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('update v1_records set latest=2 where id=?', (source['id'],))
                other.commit()
        finally:
            other.close()

    monkeypatch.setattr(data, '_assignee', bump_source_after_read)
    response = sdk_submit(c, quote)
    assert response.status_code == 200, response.text
    assert c.get('/api/v1/reviews?mine=submitted').json()['items'][0]['recordId'] == quote['id']


def test_save_holds_write_transaction_between_version_read_and_update(review_apps, monkeypatch):
    """改版读到旧版本后用独立连接写同一记录：写事务提交前，另一个连接的写入被阻塞。"""
    c = review_apps
    login(c, 'sampleoperator')
    source = save(c, type='source')
    data = c.app.state.platform.data
    db_path = data.store.data_dir / 'platform.db'
    real = data._validate_links

    def bump_source_after_read(*args, **kwargs):
        real(*args, **kwargs)
        other = sqlite3.connect(db_path, timeout=0.1)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('update v1_records set latest=99 where id=?', (source['id'],))
                other.commit()
        finally:
            other.close()

    monkeypatch.setattr(data, '_validate_links', bump_source_after_read)
    updated = save(c, id=source['id'], baseVersion=1, data={'changed': True})
    assert updated['version'] == 2
    assert c.get(f'/api/v1/apps/managed-app/records/{source["id"]}').json()['version'] == 2


@pytest.mark.parametrize('mode', [None, True, 1, [], {}, '', 'APP', 'other'])
def test_manifest_rejects_unknown_review_modes(mode):
    m = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    assert any('review' in error for error in manifest.validate({**m, 'review': mode}))


def test_manifest_accepts_review_modes_and_legacy_default():
    m = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    for value in [m, {**m, 'review': 'app'}, {**m, 'review': 'platform'}]:
        assert manifest.validate(value) == []
