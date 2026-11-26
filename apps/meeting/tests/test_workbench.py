"""工作台真实 HTTP 状态、版本、授权和 Word 回归。"""
from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient

from apps.meeting.tests.isolated_instance import create_instance, fixture_environment, login

BASE = '/api/apps/meeting/workbench/meetings'


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key, value in fixture_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    with TestClient(create_instance()) as client:
        login(client)
        yield client


def create(client):
    response = client.post(BASE, json={'title': '虚构企业服务协调会', 'date': '2026-11-26',
                                     'text': '主持人：建议讨论服务清单。\n经办人：会议决定先核对企业问题。'})
    assert response.status_code == 201, response.text
    return response.json()


def patch(client, item, **body):
    response = client.patch(f"{BASE}/{item['id']}", json={'baseVersion': item['version'], **body})
    assert response.status_code == 200, response.text
    return response.json()


def finalize(client, item):
    response = client.post(f"{BASE}/{item['id']}/finalize", json={'baseVersion': item['version'], 'checked': True})
    assert response.status_code == 200, response.text
    return response.json()


def test_text_sources_revision_and_real_word(client):
    detail = create(client)
    item = detail['item']
    old = client.get(f"/api/apps/meeting/meetings/{item['id']}").json()
    assert old['item']['transcript'][0][2] == '主持人：建议讨论服务清单。'
    assert item['minutesStatus'] != '已定稿'
    detail = finalize(client, item)
    frozen = detail['item']['finalizedVersion']
    assert frozen == detail['item']['version']
    original = detail['minutes']['body'][0]['p']
    revised = patch(client, detail['item'], text='主持人：更正服务清单名称。')['item']
    assert revised['minutesStatus'] == '待核对'
    snapshot = client.get(f"{BASE}/{item['id']}?version={frozen}").json()
    assert snapshot['minutes']['body'][0]['p'] == original
    assert snapshot['item']['minutesStatus'] == '已定稿'
    conflict = client.patch(f"{BASE}/{item['id']}", json={'baseVersion': item['version'], 'title': '覆盖'})
    assert conflict.status_code == 409
    exported = client.get(f"{BASE}/{item['id']}/export?version={frozen}")
    assert exported.status_code == 200
    assert exported.content[:2] == b'PK'
    assert original in '\n'.join(p.text for p in Document(BytesIO(exported.content)).paragraphs)


def test_dispatch_validation_idempotency_and_inbox_completion(client):
    detail = create(client)
    detail = patch(client, detail['item'], todos=[{'id': 'a1', 'task': '核对问题清单',
                   'ownerId': 'meeting-reader', 'due': '周五', 'ref': 'P1'}])
    detail = finalize(client, detail['item'])
    url = f"{BASE}/{detail['item']['id']}"
    invalid = client.post(url + '/dispatch', json={'ids': ['a1']})
    assert invalid.status_code == 422
    detail = patch(client, detail['item'], todos=[{'id': 'a1', 'task': '核对问题清单',
                   'ownerId': 'meeting-reader', 'due': '2026-11-30', 'ref': 'P1'}])
    assert client.post(url + '/dispatch', json={'ids': ['a1']}).status_code == 409
    detail = finalize(client, detail['item'])
    first = client.post(url + '/dispatch', json={'ids': ['a1']})
    assert first.status_code == 200, first.text
    second = client.post(url + '/dispatch', json={'ids': ['a1']})
    assert second.status_code == 200
    assignment = first.json()['item']['todos'][0]['assignment']['id']
    login(client, 'meeting-reader')
    assert client.post(url + '/finalize', json={'baseVersion': 1, 'checked': True}).status_code == 403
    tasks = client.get('/api/v1/todos').json()['items']
    assert len([x for x in tasks if x['id'] == assignment]) == 1
    assert client.patch('/api/v1/todos/' + assignment, json={'done': True}).status_code == 200
    assert client.get(url).json()['item']['todos'][0]['progressStatus'] == '已完成'
    login(client, 'meeting-outsider')
    assert client.get(url).status_code == 404


def test_source_references_cannot_be_forged(client):
    detail = create(client)
    item = detail['item']
    body = {'baseVersion': item['version'], 'minutes': {'title': item['title'], 'body': [
        {'h': '会议决定', 'p': '伪造结论', 'refs': ['不存在']}]}}
    assert client.patch(f"{BASE}/{item['id']}", json=body).status_code == 422


def test_arbitrary_audio_never_uses_demonstration_text(client):
    from apps.meeting.tests.isolated_instance import wait_job
    result = client.post('/api/apps/meeting/meetings', data={'title': '非示例录音'},
                         files={'file': ('actual.webm', b'\x1a\x45\xdf\xa3' + b'actual-audio' * 20, 'audio/webm')})
    assert result.status_code == 201
    item = result.json()['item']
    response = client.post(f"/api/apps/meeting/meetings/{item['id']}/transcribe")
    assert response.status_code == 202
    job = wait_job(client, response.json()['job']['id'], lambda job: job['status'] in ('done', 'failed'))[-1]
    assert job['status'] == 'failed'
    detail = client.get(f"/api/apps/meeting/meetings/{item['id']}").json()['item']
    assert not detail['transcript'] and detail['fileId'] == item['fileId']


def test_assignee_only_progress_and_source_correction_requires_review(client):
    detail = create(client)
    detail = patch(client, detail['item'], todos=[{'id': 'task', 'task': '材料核对', 'ownerId': 'meeting-reader', 'due': '2026-12-01', 'ref': 'P1'}])
    detail = finalize(client, detail['item'])
    url = f"{BASE}/{detail['item']['id']}"
    assert client.post(url + '/dispatch', json={'ids': ['task']}).status_code == 200

    assert client.patch(url + '/todos/task/progress', json={'status': '已完成', 'note': '代办完成'}).status_code == 403
    login(client, 'meeting-reader')
    assert client.patch(url + '/todos/task/progress', json={'status': '办理中', 'note': '已开始核对'}).status_code == 200
    assert client.patch(url + '/todos/task/progress', json={'status': '已取消', 'note': '不办理'}).status_code == 403
    login(client)
    detail = client.get(url).json()
    detail = patch(client, detail['item'], text='主持人：纠正记录。')
    assert detail['minutes']['body'][0]['needsReview'] is True
    response = client.post(url + '/finalize', json={'baseVersion': detail['item']['version'], 'checked': True})
    assert response.status_code == 409


def test_real_adapter_receives_original_audio_and_publishes_its_result(client, monkeypatch):
    from apps.meeting.tests.isolated_instance import wait_job
    from jkq import transcribe
    actual = b'\x1a\x45\xdf\xa3' + b'own-audio-content' * 20
    seen = []

    class Adapter:
        provider = object()

        async def transcribe(self, audio):
            seen.append(audio)
            return {'sentences': [{'startMs': 1275, 'endMs': 1900, 'speaker': '发言人甲', 'text': '这是该录音自身的识别结果。'}]}

    monkeypatch.setattr(transcribe, 'transcriber_from_environment', lambda: Adapter())
    result = client.post('/api/apps/meeting/meetings', data={'title': '适配器验证'}, files={'file': ('actual.webm', actual, 'audio/webm')})
    item = result.json()['item']
    response = client.post(f"/api/apps/meeting/meetings/{item['id']}/transcribe")
    job = wait_job(client, response.json()['job']['id'], lambda j: j['status'] in ('done', 'failed'))[-1]
    assert job['status'] == 'done' and seen == [actual]
    result = client.get(f"/api/apps/meeting/meetings/{item['id']}").json()['item']
    assert result['transcript'] == [['00:01.275', '发言人甲', '这是该录音自身的识别结果。']]
    assert result['transcriptMode'] == 'provider'


def test_repeated_timestamps_have_distinct_source_ids(client):
    platform = client.app.state.platform
    record = platform.data.save_record(platform.rbac.users['meeting-writer'], 'meeting', {'project': 'jkq', 'type': 'meeting', 'data': {
        'title': '同时间戳', 'date': '2026-11-26', 'type': '专题推进会', 'participants': [],
        'transcript': [['00:01', '甲', '建议一'], ['00:01', '乙', '建议二']], 'todos': []}})
    result = client.get(f"{BASE}/{record['id']}")
    assert result.status_code == 200, result.text
    detail = result.json()
    assert [s['id'] for s in detail['item']['sources']] == ['L1', 'L2']
    saved = patch(client, detail['item'], minutes={'title': '同时间戳', 'body': [{'h': '讨论要点', 'p': '只引用第二人', 'refs': ['L2']}]})
    assert [s['quote'] for s in saved['minutes']['body'][0]['sources']] == ['建议二']


def test_unavailable_model_keeps_manual_minutes(client):
    detail = create(client)
    before = detail['minutes']
    response = client.post(f"{BASE}/{detail['item']['id']}/candidate")
    assert response.status_code == 503, response.text
    after = client.get(f"{BASE}/{detail['item']['id']}").json()
    assert after['minutes'] == before and after['item']['version'] == detail['item']['version']


@pytest.fixture
def cross_client(tmp_path, monkeypatch):
    import json
    import shutil
    from apps.meeting.tests.isolated_instance import ROOT
    for key, value in fixture_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    for app in ('enterprise', 'document'):
        shutil.copytree(ROOT / 'apps' / app, tmp_path / 'apps' / app,
                        ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    path = tmp_path / 'config/roles.yaml'
    roles = json.loads(path.read_text())
    roles['apps'].extend(['enterprise', 'document'])
    roles['roles']['operator']['grants'].update(enterprise=['view', 'operate'], document=['view', 'operate'])
    path.write_text(json.dumps(roles))
    with TestClient(create_instance()) as client:
        login(client)
        yield client


def test_links_are_authorized_idempotent_and_discoverable(cross_client):
    client = cross_client
    detail = finalize(client, create(client)['item'])
    meeting = detail['item']
    url = f"{BASE}/{meeting['id']}"
    issue = client.post('/api/v1/apps/enterprise/records', json={
        'project': 'jkq', 'type': 'enterprise.issue', 'data': {'item': {'title': '虚构诉求', 'status': '办理中'}}}).json()
    first = client.post(url + '/links', json={'app': 'enterprise', 'id': issue['id'], 'sourceRef': 'P1'})
    assert first.status_code == 200, first.text
    repeated = client.post(url + '/links', json={'app': 'enterprise', 'id': issue['id'], 'sourceRef': 'P1'})
    assert repeated.json()['item']['version'] == first.json()['item']['version']
    assert len(repeated.json()['item']['links']) == 1
    reverse = client.get('/api/apps/meeting/workbench/links', params={'app': 'enterprise', 'id': issue['id']})
    assert reverse.json()['items'][0]['meetingId'] == meeting['id']
    login(client, 'meeting-reader')
    denied = client.get('/api/apps/meeting/workbench/links', params={'app': 'enterprise', 'id': issue['id']})
    assert denied.status_code in (403, 404)
    login(client)
    platform = client.app.state.platform
    # 公文创建已在 #228 验证，此处用受信 SDK 夹具提供其落库契约，不能绕过HTTP草稿写保护。
    document = platform.data.save_record(platform.rbac.users['meeting-writer'], 'document', {
        'project': 'jkq', 'type': 'document-draft', 'data': {'source': {
            'app': 'meeting', 'id': meeting['id'], 'version': meeting['finalizedVersion']}}})
    assert client.post(url + '/links', json={'app': 'document', 'id': document['id'], 'version': meeting['finalizedVersion']}).status_code == 200
    assert client.post(url + '/links', json={'app': 'document', 'id': document['id'], 'version': 99}).status_code == 422


def test_generic_and_legacy_writes_cannot_bypass_workbench_checks(client):
    detail = create(client)
    item = detail['item']
    forged = {'project': 'jkq', 'type': 'meeting', 'data': {'minutesStatus': '已定稿', 'finalizedVersion': 1}}
    assert client.post('/api/v1/apps/meeting/records', json=forged).status_code == 405
    assert client.put('/api/v1/apps/meeting/records/' + item['id'], json={**forged, 'baseVersion': item['version']}).status_code == 405
    assert client.patch('/api/apps/meeting/meetings/' + item['id'], json={'line': {'index': 0, 'text': '跳过来源版本'}}).status_code == 409
    assert client.get(f"{BASE}/{item['id']}").json()['item']['version'] == item['version']


def test_reassignment_moves_inbox_and_atomically_keeps_audit_and_notifications(client):
    detail = create(client)
    detail = patch(client, detail['item'], todos=[{'id': 'a1', 'task': '核对材料', 'ownerId': 'meeting-reader', 'due': '2026-12-01', 'ref': 'P1'}])
    detail = finalize(client, detail['item'])
    url = f"{BASE}/{detail['item']['id']}"
    detail = client.post(url + '/dispatch', json={'ids': ['a1']}).json()
    assignment = detail['item']['todos'][0]['assignment']
    payload = {'baseVersion': detail['item']['version'], 'previousOwnerId': 'meeting-reader',
               'ownerId': 'meeting-writer', 'due': '2026-12-03', 'note': '经核对由整理人继续办理'}
    result = client.post(url + '/todos/a1/reassign', json=payload)
    assert result.status_code == 200, result.text
    changed = result.json()['item']
    assert changed['todos'][0]['assignment']['id'] == assignment['id']
    assert changed['todos'][0]['assignment']['finalizedVersion'] == assignment['finalizedVersion']
    assert changed['todos'][0]['due'] == '2026-12-03'
    assert any(t['id'] == assignment['id'] for t in client.get('/api/v1/todos').json()['items'])
    assert client.post(url + '/todos/a1/reassign', json=payload).status_code == 409
    login(client, 'meeting-reader')
    assert not any(t['id'] == assignment['id'] for t in client.get('/api/v1/todos').json()['items'])
    assert client.patch('/api/v1/todos/' + assignment['id'], json={'done': True}).status_code == 404
    notices = client.get('/api/v1/inbox?box=todo').json()['items']
    assert any('调整' in n['title'] and n.get('kind') == 'notice' for n in notices)
    login(client)
    assert client.patch('/api/v1/todos/' + assignment['id'], json={'done': True}).status_code == 200
    assert client.patch('/api/v1/todos/' + assignment['id'], json={'done': False}).status_code == 409
    payload.update(baseVersion=changed['version'], previousOwnerId='meeting-writer', ownerId='meeting-reader')
    assert client.post(url + '/todos/a1/reassign', json=payload).status_code == 409
    assert client.patch(url + '/todos/a1/progress', json={'status': '待处理', 'note': '补充核对，说明原因后重新办理'}).status_code == 200
    result = client.post(url + '/todos/a1/reassign', json=payload)
    assert result.status_code == 200, result.text
    store = client.app.state.platform.store
    rows = store._db.execute("select detail from audit where action='meeting.todo.reassign'").fetchall()
    assert len(rows) == 2


def test_restore_and_supplement_keep_original_versions_and_label_provenance(client):
    detail = create(client)
    detail = finalize(client, detail['item'])
    item = detail['item']
    frozen = item['finalizedVersion']
    url = f"{BASE}/{item['id']}"
    response = client.post(url + '/supplements', json={'baseVersion': item['version'], 'text': '会后核实资料无需重复提交', 'source': '经办人会后电话核对记录'})
    assert response.status_code == 200, response.text
    detail = response.json()
    added = detail['item']['sources'][-1]
    assert added['id'].startswith('S') and '会议办理员' in added['quote'] and '电话核对记录' in added['quote']
    assert detail['minutes']['body'][0]['needsReview']
    result = client.post(url + '/restore', json={'baseVersion': detail['item']['version'], 'fromVersion': frozen})
    assert result.status_code == 200, result.text
    restored = result.json()
    assert restored['item']['minutesStatus'] == '待核对'
    assert len(restored['item']['sources']) == 2
    assert restored['minutes']['body'][0]['p'] == '主持人：建议讨论服务清单。'
    assert client.get(url + '?version=' + str(frozen)).json()['item']['minutesStatus'] == '已定稿'


def test_reassignment_notification_failure_rolls_back_version_and_receiver(client):
    import sqlite3
    detail = create(client)
    detail = patch(client, detail['item'], todos=[{'id': 'a1', 'task': '核对材料', 'ownerId': 'meeting-reader', 'due': '2026-12-01', 'ref': 'P1'}])
    detail = finalize(client, detail['item'])
    url = f"{BASE}/{detail['item']['id']}"
    detail = client.post(url + '/dispatch', json={'ids': ['a1']}).json()
    store = client.app.state.platform.store
    with store._lock, store._db as db:
        db.execute("CREATE TRIGGER test_notification_failure BEFORE INSERT ON v1_notifications BEGIN SELECT RAISE(ABORT,'test notification failure'); END")
    failed = client.post(url + '/todos/a1/reassign', json={'baseVersion': detail['item']['version'],
                    'previousOwnerId': 'meeting-reader', 'ownerId': 'meeting-writer', 'due': '2026-12-02', 'note': '故障回滚验收'})
    assert failed.status_code >= 500
    after = client.get(url).json()['item']
    assert after['version'] == detail['item']['version']
    assert after['todos'][0]['assignment']['recipientId'] == 'meeting-reader'
    assert not store._db.execute("select 1 from audit where action='meeting.todo.reassign'").fetchall()
    assert not store._db.execute('select 1 from jkq_meeting_todo_done').fetchall()


def test_empty_meeting_can_receive_original_audio_without_changing_id(client):
    detail = client.post(BASE, json={'title': '后补资料的会议', 'date': '2026-11-26'}).json()
    item = detail['item']
    audio = b'\x1a\x45\xdf\xa3' + b'own-recording' * 10
    response = client.post(f"{BASE}/{item['id']}/audio", data={'baseVersion': item['version']},
                           files={'file': ('record.webm', audio, 'audio/webm')})
    assert response.status_code == 200, response.text
    saved = response.json()['item']
    assert saved['id'] == item['id'] and saved['version'] == item['version'] + 1
    assert client.get('/api/v1/files/' + saved['fileId'] + '/content').content == audio
    assert saved['minutesStatus'] == '草稿'


def test_unfinalized_link_source_snapshot_is_immutable(client):
    detail = create(client)
    item = detail['item']
    patch(client, item, text='后续更正了原文。')
    url = f"{BASE}/{item['id']}?version={item['version']}"
    assert client.get(url).status_code == 404
    snapshot = client.get(url + '&snapshot=1')
    assert snapshot.status_code == 200
    assert snapshot.json()['item']['sources'][0]['quote'] == '主持人：建议讨论服务清单。'


def test_negated_or_questioned_decision_remains_discussion(client):
    text = '\n'.join(['主持人：尚未形成会议决定，建议下周再讨论。', '记录人：会议决定尚未明确，继续征求意见。',
                      '主持人：是否会议明确了办理期限？', '主持人：会议决定：先核对材料。'])
    result = client.post(BASE, json={'title': '虚构否定表述', 'date': '2026-11-26', 'text': text}).json()
    assert [s['h'] for s in result['minutes']['body']] == ['讨论要点', '讨论要点', '讨论要点', '已明确的决定']


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    import json
    from apps.meeting.tests.isolated_instance import PASSWORD_ENV
    for key, value in fixture_environment(tmp_path).items():
        monkeypatch.setenv(key, value)
    path = tmp_path / 'config/users.yaml'
    config = json.loads(path.read_text())
    config['demoUsers'].append({'id': 'meeting-other', 'username': 'meeting-other', 'name': '另一经办人', 'role': 'operator', 'passwordEnv': PASSWORD_ENV})
    path.write_text(json.dumps(config))
    with TestClient(create_instance()) as client:
        login(client)
        yield client


def test_original_and_generic_job_paths_check_original_owner(owner_client):
    from apps.meeting.tests.isolated_instance import MEETING, wait_job
    client = owner_client
    result = client.post('/api/apps/meeting/meetings', data={'title': '原入口所有权'},
                         files={'file': ('demo.webm', (MEETING / 'samples/demo.webm').read_bytes(), 'audio/webm')})
    item = result.json()['item']
    url = '/api/apps/meeting/meetings/' + item['id']
    login(client, 'meeting-other')
    assert client.post(url + '/transcribe').status_code == 403
    assert client.post(url + '/todos/commit', json={'ids': ['missing']}).status_code == 403
    assert client.patch(url, json={'line': {'index': 0, 'text': '越权'}}).status_code == 403
    job = client.post('/api/v1/jobs', json={'appId': 'meeting', 'project': 'jkq', 'operation': 'transcribe',
                      'input': {'ref': item['id'], 'title': '越权修改'}, 'idempotencyKey': 'other-owner-attempt'})
    assert job.status_code == 202, job.text
    job_id = job.json().get('id') or job.json()['job']['id']
    result = wait_job(client, job_id, lambda j: j['status'] in ('done', 'failed'))[-1]
    assert result['status'] == 'failed'
    detail = client.get(url).json()['item']
    assert detail['title'] == '原入口所有权' and not detail['transcript'] and not detail.get('jobId')
