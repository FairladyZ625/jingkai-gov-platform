"""CAP-07 应用消息的幂等、收件人隔离与来源授权。"""
import json
import shutil
import time

from conftest import ROOT
from test_data_v1 import record
from test_platform import login


def request(source, *, recipients=None, key='change-17-v1'):
    return {
        'idempotencyKey': key,
        'recipientIds': recipients or ['samplereviewer', 'sampleobserver'],
        'recordId': source['id'],
        'version': source['version'],
        'title': '图纸版本已更新',
        'body': '请查看已批准的版本变更。',
        'priority': 'high',
        'expiresAt': time.time() + 3600,
        'requiresAcknowledgement': True,
    }


def test_message_recipients_have_independent_state_and_idempotent_send(make_client):
    c = make_client()
    login(c, 'sampleoperator')
    source = record(c).json()
    payload = request(source)
    sent = c.post('/api/v1/apps/sample-app/messages', json=payload)
    assert sent.status_code == 201
    items = sent.json()['items']
    assert len(items) == 2
    assert {item['recipientId'] for item in items} == {'samplereviewer', 'sampleobserver'}
    assert all(item['status'] == 'written' for item in items)

    replay = c.post('/api/v1/apps/sample-app/messages', json=payload)
    assert replay.status_code == 200 and replay.json()['replayed'] is True
    assert {item['id'] for item in replay.json()['items']} == {item['id'] for item in items}
    changed = c.post('/api/v1/apps/sample-app/messages', json={**payload, 'title': '另一个事件'})
    assert changed.status_code == 409 and changed.json()['error']['code'] == 'INVALID_STATE'

    lead_id = next(item['id'] for item in items if item['recipientId'] == 'samplereviewer')
    sampleobserver_id = next(item['id'] for item in items if item['recipientId'] == 'sampleobserver')
    login(c, 'samplereviewer')
    assert c.get('/api/v1/messages').json()['items'][0]['read'] is False
    assert c.post(f'/api/v1/messages/{lead_id}/acknowledge').json()['status'] == 'acknowledged'
    login(c, 'sampleobserver')
    sampleobserver_note = c.get(f'/api/v1/messages/{sampleobserver_id}')
    assert sampleobserver_note.status_code == 200 and sampleobserver_note.json()['read'] is False
    assert c.get(f'/api/v1/messages/{lead_id}').status_code == 404

    login(c, 'sampleoperator')
    states = c.get('/api/v1/apps/sample-app/messages/sent').json()['items']
    by_recipient = {item['recipientId']: item for item in states}
    assert by_recipient['samplereviewer']['status'] == 'acknowledged'
    assert by_recipient['sampleobserver']['status'] == 'written'


def test_message_send_rejects_unknown_and_out_of_scope_recipients(make_client):
    c = make_client()
    login(c, 'sampleadmin')
    source = record(c, project='limited-project').json()
    payload = request(source, recipients=['sampleoperator'], key='restricted-record')
    denied = c.post('/api/v1/apps/sample-app/messages', json=payload)
    assert denied.status_code == 422
    assert denied.json()['error']['recipients'] == [
        {'recipientId': 'sampleoperator', 'reason': '来源记录不可见'}
    ]

    source = record(c).json()
    no_app = c.post('/api/v1/apps/sample-app/messages', json=request(source, recipients=['sampleoutsider'], key='no-app-access'))
    assert no_app.status_code == 422
    assert no_app.json()['error']['recipients'] == [
        {'recipientId': 'sampleoutsider', 'reason': '来源记录不可见'}
    ]
    missing = c.post('/api/v1/apps/sample-app/messages', json=request(source, recipients=['missing-user'], key='missing-user'))
    assert missing.status_code == 422
    assert missing.json()['error']['recipients'] == [
        {'recipientId': 'missing-user', 'reason': '收件人不存在或已停用'}
    ]
    disabled_id = c.app.state.platform.directory.users()['samplereviewer'].id
    assert c.patch(f'/api/admin/users/{disabled_id}', json={'status': 'disabled'}).status_code == 200
    disabled = c.post('/api/v1/apps/sample-app/messages', json=request(source, recipients=[disabled_id], key='disabled-user'))
    assert disabled.status_code == 422
    assert disabled.json()['error']['recipients'] == [
        {'recipientId': disabled_id, 'reason': '收件人不存在或已停用'}
    ]
    invalid_link = c.post('/api/v1/apps/sample-app/messages', json={
        **request(source, recipients=['samplereviewer'], key='external-link'), 'deepLink': 'https://example.invalid/',
    })
    assert invalid_link.status_code == 422 and invalid_link.json()['error']['code'] == 'INVALID_REQUEST'
    expired = c.post('/api/v1/apps/sample-app/messages', json={
        **request(source, recipients=['samplereviewer'], key='expired'), 'expiresAt': time.time() - 1,
    })
    assert expired.status_code == 422 and expired.json()['error']['code'] == 'INVALID_REQUEST'
    assert c.get('/api/v1/messages').json()['items'] == []
    audit = c.get('/api/audit', params={'app_id': 'sample-app'}).json()['items']
    assert any(item['action'] == 'v1.message.send_failed' for item in audit)


def test_python_preview_messages_bind_sender_app_and_current_user(make_client, tmp_path):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/fixtures/platform-app', apps / 'sample-app')
    app = apps / 'message-client'
    shutil.copytree(ROOT / 'apps/_template', app)
    manifest = json.loads((app / 'app.json').read_text(encoding='utf-8'))
    manifest.update(id='message-client', name='消息 SDK 示例',
                    defaultRoles={'sampleoperator': ['view', 'operate'], 'samplereviewer': ['view']})
    (app / 'app.json').write_text(json.dumps(manifest), encoding='utf-8')
    (app / 'api/router.py').write_text('''
from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, app_context
router = APIRouter()

@router.post('/send')
def send(body: dict, ctx: AppContext = Depends(app_context)):
    return ctx.preview.messages.send(**body)

@router.get('/sent')
def sent(ctx: AppContext = Depends(app_context)):
    return ctx.preview.messages.sent()
''', encoding='utf-8')
    c = make_client(apps)
    login(c, 'sampleoperator')
    source = c.post('/api/v1/apps/message-client/records', json={
        'project': 'sample-project', 'type': 'change', 'data': {'version': 1},
    }).json()
    sent = c.post('/api/apps/message-client/send', json={
        'idempotency_key': 'sdk-example-1', 'recipient_ids': ['samplereviewer'],
        'record_id': source['id'], 'version': source['version'],
        'title': '请核对变更', 'body': '此内容为虚构测试消息。',
        'priority': 'normal', 'requires_acknowledgement': True,
    })
    assert sent.status_code == 200, sent.text
    assert sent.json()['items'][0]['appId'] == 'message-client'
    assert c.get('/api/apps/message-client/sent').json()['items'][0]['recipientId'] == 'samplereviewer'
