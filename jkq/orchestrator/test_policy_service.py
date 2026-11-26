"""政策岗位通过真实会话、工具桥、政策目录和企业授权路由验收。"""
import json
import sys

import pytest

pytest.importorskip("fastapi", reason="政策岗位接口由安装 requirements-dev.txt 的 core CI 验证")

from apps.policy.tests.test_notice_tools_http import policy_client  # noqa: F401


BASE = '/api/v1/conversations'


def conversation(client):
    response = client.post(BASE, json={})
    assert response.status_code == 200
    return BASE + '/' + response.json()['item']['id']


def send(client, path, text, **fields):
    response = client.post(path + '/messages', json={'text': text, 'mode': 'policy_service', **fields})
    assert response.status_code == 200, response.text
    return response.json()['reply']


def spy_tools(client, monkeypatch):
    bridge = client.app.state.apps_bridge
    original = bridge.call_from_chat
    calls = []

    async def call(request, app_id, tool, args):
        calls.append((app_id, tool, args.copy()))
        return await original(request, app_id, tool, args)

    monkeypatch.setattr(bridge, 'call_from_chat', call)
    return calls


@pytest.mark.parametrize('fields', [
    {'mode': 'administrator'}, {'mode': None}, {'enterpriseId': ''},
    {'enterpriseId': '  '}, {'enterpriseId': 1}, {'app': 'document'},
])
def test_policy_mode_validates_context_without_appending_messages(policy_client, fields):
    client = policy_client()
    path = conversation(client)
    response = client.post(path + '/messages', json={'text': '数据券', 'mode': 'policy_service', **fields})
    assert response.status_code == 422
    assert client.get(path).json()['messages'] == []


def test_policy_mode_queries_real_policy_tool_before_answer_and_does_not_use_model(policy_client, monkeypatch):
    client = policy_client()
    calls = spy_tools(client, monkeypatch)

    async def forbidden_model(*args, **kwargs):
        pytest.fail('政策事实不能交给自由生成的模型回答')

    client.app.state.chat_gateway = forbidden_model
    path = conversation(client)
    reply = send(client, path, '数据券需要准备什么材料？')
    assert calls == [('policy', 'policy.search', {'q': '数据券需要准备什么材料？', 'queryMode': 'question'})]
    assert reply['toolCalls'][0]['status'] == 'ok'
    assert reply['citations']
    assert '申报材料' in reply['content'] and '原文' in reply['content']
    assert '申请条件' in reply['content'] and '申报期限' in reply['content']
    assert '不代表符合申请条件或获批' in reply['content']
    catalog = client.get('/api/apps/policy/items').json()['items']
    items = {item['id']: item for item in catalog}
    for citation in reply['citations']:
        item = items[citation['itemId']]
        assert citation['snippet'] == item['original']
        assert citation['url'] == item['source']['url']
        assert item['original'] in reply['content']
    assert client.get(path).json()['messages'][-1] == reply
    assert reply['mode'] == 'policy_service' and reply['enterpriseId'] is None


def test_question_search_is_optional_and_preserves_legacy_substring_search(policy_client):
    client = policy_client()
    old = client.get('/api/apps/policy/items', params={'q': '数据券需要什么材料？'}).json()
    assert old['items'] == []
    response = client.get('/api/apps/policy/items', params={'q': '数据券需要什么材料？', 'queryMode': 'question'})
    assert response.status_code == 200
    assert 'RP-001' in [item['id'] for item in response.json()['items']]
    assert response.json()['queryState'] == 'searched'
    assert client.get('/api/apps/policy/items', params={'queryMode': 'invent'}).status_code == 400


def test_policy_followup_uses_only_contiguous_same_enterprise_and_mode(policy_client, monkeypatch):
    client = policy_client()
    calls = spy_tools(client, monkeypatch)
    path = conversation(client)
    send(client, path, 'RP-001 的申请条件是什么？', enterpriseId='enterprise-a')
    followup = send(client, path, '那期限呢？', enterpriseId='enterprise-a')
    assert 'RP-001' in calls[-1][2]['q']
    assert followup['citations']
    changed = send(client, path, '那期限呢？', enterpriseId='enterprise-b')
    assert calls[-1][2]['q'] == '那期限呢？'
    assert changed['citations'] == []
    assert '政策名称' in changed['content']
    reset = send(client, path, '那材料呢？', enterpriseId='enterprise-a')
    assert calls[-1][2]['q'] == '那材料呢？'
    assert reset['citations'] == []
    other = send(client, conversation(client), '那期限呢？', enterpriseId='enterprise-a')
    assert calls[-1][2]['q'] == '那期限呢？'
    assert other['citations'] == []


def test_policy_context_does_not_return_after_general_turn(policy_client, monkeypatch):
    client = policy_client()
    calls = spy_tools(client, monkeypatch)
    path = conversation(client)
    send(client, path, 'RP-001 申请条件')
    response = client.post(path + '/messages', json={'text': '你好'})
    assert response.status_code == 200
    reply = send(client, path, '那材料呢？')
    assert calls[-1][2]['q'] == '那材料呢？'
    assert reply['citations'] == []


def test_policy_reply_uses_real_authorized_company_and_never_demo_profile(policy_client, monkeypatch):
    client = policy_client()
    response = client.post('/api/apps/enterprise/companies', json={'name': '政策模式测试公司', 'industry': '软件服务'})
    assert response.status_code == 200, response.text
    company = response.json()['item']
    reply = send(client, conversation(client), 'RP-001 申请条件', enterpriseId=company['id'])
    assert '政策模式测试公司' in reply['content']
    assert '软件服务' in reply['content']
    assert '待确认' in reply['content']
    assert reply['toolCalls'][0]['args']['enterpriseId'] == company['id']
    # 测试实例会 seed E001 到真实台账；明确让旧演示画像入口失效，岗位仍可从台账读取。
    def no_demo(*args, **kwargs):
        pytest.fail('岗位不能读取固定演示画像')
    monkeypatch.setattr(sys.modules['haiknow_apps.policy.policy_routes'], 'enterprise_profile', no_demo)
    seeded = send(client, conversation(client), 'RP-001 申请条件', enterpriseId='E001')
    assert client.get('/api/apps/enterprise/companies/E001').json()['item']['name'] in seeded['content']
    missing = send(client, conversation(client), 'RP-001 申请条件', enterpriseId='nonexistent-company')
    assert '未能读取所选企业资料' in missing['content']
    assert '书香里' not in missing['content']


def test_no_policy_basis_and_query_failure_do_not_fall_back_to_kb(policy_client, monkeypatch):
    client = policy_client()
    calls = spy_tools(client, monkeypatch)
    reply = send(client, conversation(client), '火星采矿许可补贴')
    assert reply['citations'] == [] and reply['cards'] == []
    assert '没有找到' in reply['content']
    assert '无法判断适用或获批' in reply['content']
    assert [call[1] for call in calls] == ['policy.search']

    async def broken(*args, **kwargs):
        raise TimeoutError('private infrastructure detail')

    monkeypatch.setattr(client.app.state.apps_bridge, 'call_from_chat', broken)
    failed = send(client, conversation(client), '数据券的条件')
    assert failed['toolCalls'][0]['status'] == 'error'
    assert failed['citations'] == [] and failed['cards'] == []
    assert '无法判断适用或获批' in failed['content']
    assert 'private infrastructure' not in failed['content']


def test_policy_mode_uses_view_permission_and_never_performs_write(policy_client, monkeypatch):
    client = policy_client('partner')
    calls = spy_tools(client, monkeypatch)
    path = conversation(client)
    reply = send(client, path, 'RP-001 帮我提交申请并保证获批', enterpriseId='E001')
    assert reply['citations']
    assert '不代表符合申请条件或获批' in reply['content']
    assert [call[1] for call in calls] == ['policy.search']
    assert not any(entry.get('status') == 'pending' for entry in reply['toolCalls'])
    original = client.app.state.platform.rbac.actions
    monkeypatch.setattr(client.app.state.platform.rbac, 'actions',
                        lambda user, app: frozenset() if app == 'policy' else original(user, app))
    before = client.get(path).json()['messages']
    denied = client.post(path + '/messages', json={'text': '数据券', 'mode': 'policy_service'})
    assert denied.status_code == 403
    assert client.get(path).json()['messages'] == before


def test_policy_conversation_cannot_be_reused_by_another_account(policy_client):
    owner = policy_client()
    path = conversation(owner)
    send(owner, path, 'RP-001 材料')
    other = policy_client('partner')
    response = other.post(path + '/messages', json={'text': '那期限呢', 'mode': 'policy_service'})
    assert response.status_code == 404
    assert other.get(path).status_code == 404


def test_policy_stream_persists_same_mode_sources_and_tool_result(policy_client):
    client = policy_client()
    path = conversation(client)
    response = client.post(path + '/messages', json={'text': 'RP-001 条件', 'mode': 'policy_service', 'stream': True})
    assert response.status_code == 200
    events = [json.loads(block.split('\ndata: ', 1)[1]) for block in response.text.strip().split('\n\n')]
    reply = events[-1]['reply']
    assert reply['mode'] == 'policy_service'
    assert reply['citations']
    assert reply == client.get(path).json()['messages'][-1]


def test_policy_search_respects_enterprise_permission_and_projects_only_needed_fields(policy_client, monkeypatch):
    client = policy_client('partner')
    result = client.get('/api/apps/policy/items', params={
        'q': 'RP-001', 'queryMode': 'question', 'enterpriseId': 'E001',
    }).json()
    assert result['enterprise']['status'] == 'available'
    assert set(result['enterprise']['item']) == {'id', 'name', 'industry', 'scale'}
    original = client.app.state.platform.rbac.actions
    monkeypatch.setattr(client.app.state.platform.rbac, 'actions',
                        lambda user, app: frozenset() if app == 'enterprise' else original(user, app))
    blocked = client.get('/api/apps/policy/items', params={
        'q': 'RP-001', 'queryMode': 'question', 'enterpriseId': 'E001',
    }).json()
    assert blocked['enterprise'] == {'id': 'E001', 'status': 'unavailable'}
    assert [item['id'] for item in blocked['items']] == ['RP-001']


def test_enterprise_transport_failure_does_not_discard_public_policy_sources(policy_client, monkeypatch):
    import httpx
    client = policy_client()

    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError('private internal host')

    monkeypatch.setattr(httpx.AsyncClient, 'get', unavailable)
    reply = send(client, conversation(client), 'RP-001 条件', enterpriseId='E001')
    assert reply['citations'] and reply['toolCalls'][0]['status'] == 'ok'
    assert '未能读取所选企业资料' in reply['content']
    assert 'private internal host' not in reply['content']


def test_policy_invalid_source_never_publishes_card_or_unverified_claim(policy_client, monkeypatch):
    client = policy_client()
    bridge = client.app.state.apps_bridge
    original = bridge.call_from_chat

    async def corrupted(*args, **kwargs):
        response = await original(*args, **kwargs)
        response['result']['items'][0]['source']['url'] = 'javascript:unsafe()'
        response['result']['items'][0]['original'] = '本企业保证获得补贴'
        return response

    monkeypatch.setattr(bridge, 'call_from_chat', corrupted)
    reply = send(client, conversation(client), 'RP-001 条件')
    assert reply['toolCalls'][0]['status'] == 'error'
    assert reply['cards'] == [] and reply['citations'] == []
    assert '本企业保证获得补贴' not in reply['content']
    assert '无法判断适用或获批' in reply['content']


def test_compound_bookshop_rent_question_uses_same_source_keywords_and_marks_history(policy_client):
    client = policy_client()
    question = '实体书店房租有哪些申请条件？'
    reply = send(client, conversation(client), question, enterpriseId='E001')
    assert [citation['itemId'] for citation in reply['citations']] == ['PI-03']
    assert '申请条件' in reply['content'] and '房租' in reply['content']
    assert '历史' in reply['content']
    assert '不代表符合申请条件或获批' in reply['content']


def test_current_topic_and_unknown_topic_never_reuse_previous_policy(policy_client, monkeypatch):
    client = policy_client()
    calls = spy_tools(client, monkeypatch)
    path = conversation(client)
    send(client, path, 'RP-001 条件', enterpriseId='E001')
    changed = send(client, path, '那 RP-023 材料', enterpriseId='E001')
    assert [citation['itemId'] for citation in changed['citations']] == ['RP-023']
    assert [call['args']['q'] for call in changed['toolCalls']] == ['那 RP-023 材料']
    unknown = send(client, path, '那火星采矿许可补贴呢？', enterpriseId='E001')
    assert unknown['citations'] == [] and unknown['cards'] == []
    assert [call['args']['q'] for call in unknown['toolCalls']] == ['那火星采矿许可补贴呢？']
    assert calls[-1][2]['q'] == '那火星采矿许可补贴呢？'
    follow = send(client, path, '那需要什么材料？', enterpriseId='E001')
    assert follow['citations'] == []
    assert len(follow['toolCalls']) == 1


def test_referential_followup_records_current_query_then_context_query_in_stream(policy_client, monkeypatch):
    client = policy_client()
    calls = spy_tools(client, monkeypatch)
    path = conversation(client)
    send(client, path, 'RP-001 条件', enterpriseId='E001')
    response = client.post(path + '/messages', json={
        'text': '那需要什么材料？', 'mode': 'policy_service', 'enterpriseId': 'E001', 'stream': True,
    })
    events = [(block.split('\n', 1)[0], json.loads(block.split('\ndata: ', 1)[1]))
              for block in response.text.strip().split('\n\n')]
    reply = events[-1][1]['reply']
    queries = ['那需要什么材料？', 'RP-001 条件\n那需要什么材料？']
    assert [call[2]['q'] for call in calls[-2:]] == queries
    assert [call['args']['q'] for call in reply['toolCalls']] == queries
    assert [data['args']['q'] for kind, data in events if kind == 'event: tool'] == queries
    assert [citation['itemId'] for citation in reply['citations']] == ['RP-001']
    # 后续追问必须承接上轮最后一次有依据的查询，而不是第一次 clarify。
    again = send(client, path, '那期限呢？', enterpriseId='E001')
    assert [call['args']['q'] for call in again['toolCalls']] == [
        '那期限呢？', 'RP-001 条件\n那需要什么材料？\n那期限呢？',
    ]
    assert [citation['itemId'] for citation in again['citations']] == ['RP-001']


@pytest.mark.parametrize(('question', 'expected'), [
    ('RP-001', ['RP-001']), ('RP-001需要什么材料？', ['RP-001']),
    ('请问RP-001的申请条件是什么？', ['RP-001']), ('RP-0010需要什么材料？', []),
    ('请问XRP-001的申请条件是什么？', []),
])
def test_policy_identifier_has_ascii_boundary_not_chinese_boundary(policy_client, question, expected):
    client = policy_client()
    result = client.get('/api/apps/policy/items', params={'q': question, 'queryMode': 'question'})
    assert result.status_code == 200
    assert [item['id'] for item in result.json()['items']] == expected
