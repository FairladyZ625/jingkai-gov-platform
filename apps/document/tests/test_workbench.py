"""公文工作台复用同一文稿和审签状态；身份、版本由服务端核验。"""
from apps.document.tests.test_drafting import APP, create, content, item, login, assert_error, document_client
from apps.document.tests.test_review_export import flow


def test_workspace_uses_real_identities_and_members(document_client):
    client = document_client
    draft = item(create(client))
    response = client.get(APP + '/workbench')
    assert response.status_code == 200, response.text
    result = response.json()
    row = next(row for row in result['items'] if row['id'] == draft['id'])
    assert row['authorId'] == 'sampleoperator'
    assert row['project'] == 'jkq'
    assert {member['id'] for member in result['reviewers']} == {'samplereviewer', 'sampleadmin'}
    login(client, 'sampleoutsider')
    assert_error(client.get(APP + '/workbench'), 404, 'NOT_FOUND')


def test_explicit_edit_version_rejects_stale_content(document_client):
    client = document_client
    draft = item(create(client)); url = APP + '/drafts/' + draft['id']
    version = draft['versions'][-1]['v']
    original = content(draft)
    updated = item(client.put(url, json={'content': {**original, 'title': '经办人最新标题'}, 'baseVersion': version}))
    assert updated['versions'][-1]['v'] == version + 1
    assert_error(client.put(url, json={'content': {**original, 'title': '过期页面标题'}, 'baseVersion': version}), 409, 'STALE_VERSION')
    assert content(item(client.get(url)))['title'] == '经办人最新标题'


def test_workbench_review_is_same_version_and_inbox_record(flow):
    client, url, fields, _ = flow
    latest = item(client.get(url))['versions'][-1]['v']
    assert_error(client.post(url + '/submit', json={'assignee': 'samplereviewer', 'version': latest - 1}), 409, 'STALE_VERSION')
    submitted = client.post(url + '/submit', json={'assignee': 'samplereviewer', 'version': latest}).json()
    review = submitted['review']
    login(client, 'samplereviewer')
    workspace = client.get(APP + '/workbench').json()
    assert any(row['id'] == review['id'] for row in workspace['reviews'])
    assert_error(client.post(APP + '/workbench/reviews/' + review['id'], json={'version': review['version'] - 1, 'decision': 'approve', 'comment': '核对'}), 409, 'STALE_VERSION')
    done = client.post(APP + '/workbench/reviews/' + review['id'], json={'version': review['version'], 'decision': 'approve', 'comment': '同意定稿'})
    assert done.status_code == 200, done.text
    assert item(client.get(url))['status'] == '已定稿'
    login(client, 'sampleoperator')
    assert_error(client.put(url, json={'content': fields}), 409, 'LOCKED')


def test_meeting_source_is_fixed_authorized_server_content(document_client):
    client = document_client
    platform = client.app.state.platform
    admin = platform.rbac.users['sampleadmin']
    minutes = {'title': '核定会议纪要', 'body': [{'h': '一、议定事项', 'p': '完成公开资料核验。'}]}
    record = platform.data.save_record(admin, 'meeting', {'project': 'jkq', 'type': 'meeting', 'data': {
        'minutesStatus': '已定稿', 'finalizedVersion': 1, 'minutesEdit': minutes}})
    source = {'app': 'meeting', 'id': record['id'], 'version': 1, 'title': '伪造标题'}
    # 公文操作权不能代替会议读取权。
    assert_error(create(client, templateId='T02', inputs={}, source=source), 404, 'NOT_FOUND')
    login(client, 'sampleadmin')
    draft = item(create(client, templateId='T02', inputs={}, source=source, extra=['伪造正文']))
    assert draft['source'] == {**source, 'title': minutes['title']}
    assert content(draft)['title'] == minutes['title']
    assert content(draft)['paragraphs'] == ['一、议定事项', '完成公开资料核验。']
    assert item(client.get(APP + '/drafts/' + draft['id']))['source'] == draft['source']
    changed = platform.data.save_record(admin, 'meeting', {'baseVersion': 1, 'data': {
        'minutesStatus': '待核对', 'minutesEdit': {'title': '未核定', 'body': []}}}, record['id'])
    assert_error(create(client, templateId='T02', inputs={}, source={**source, 'version': changed['version']}), 422, 'INVALID_REFERENCE')
    repeat = item(create(client, templateId='T02', inputs={}, source=source))
    assert content(repeat)['paragraphs'] == content(draft)['paragraphs']


def test_original_author_identity_survives_another_editor(document_client):
    client = document_client
    draft = item(create(client))
    login(client, 'sampleadmin')
    item(client.put(APP + '/drafts/' + draft['id'], json={'content': content(draft)}))
    row = next(r for r in client.get(APP + '/workbench').json()['items'] if r['id'] == draft['id'])
    assert row['authorId'] == 'sampleoperator'
    assert row['author'] == draft['author']


def test_replaced_review_does_not_duplicate_pending_work(flow):
    client, url, fields, _ = flow
    first = client.post(url + '/submit', json={'assignee': 'samplereviewer'}).json()['review']
    item(client.put(url, json={'content': {**fields, 'title': fields['title'] + '（修订）'}}))
    latest = client.post(url + '/submit', json={'assignee': 'samplereviewer'}).json()['review']
    login(client, 'samplereviewer')
    rows = client.get(APP + '/workbench').json()['reviews']
    assert [r['id'] for r in rows if r['status'] == 'pending'] == [latest['id']]
    assert not any(r['id'] == first['id'] for r in rows)
    login(client, 'sampleoperator')
    history = client.get(APP + '/workbench').json()['reviews']
    assert next(r for r in history if r['id'] == first['id'])['status'] == 'recheck'


def test_rule_fix_rejects_version_changed_since_check(document_client):
    client = document_client
    draft = item(create(client))
    url = APP + '/drafts/' + draft['id']
    old_version = draft['versions'][-1]['v']
    saved = item(client.put(url, json={'content': {**content(draft), 'title': '核查后别人已修改'}, 'baseVersion': old_version}))
    assert_error(client.post(url + '/fix', json={'ids': [], 'baseVersion': old_version}), 409, 'STALE_VERSION')
    assert item(client.get(url))['versions'][-1]['v'] == saved['versions'][-1]['v']
