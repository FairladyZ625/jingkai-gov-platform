"""用 SDK 持久记录与真实会话验证会议接口，企业诉求使用 §4.2 契约夹具。"""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
from threading import Barrier

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

APP = Path(__file__).resolve().parents[1]
MEETING = '/api/apps/meeting'
ENTERPRISE = '/api/apps/enterprise'
RECORDS = '/api/v1/apps/meeting/records'


@pytest.fixture
def instance(make_client, isolated_platform):
    config, apps = isolated_platform
    roles_file = config / 'roles.yaml'
    roles = json.loads(roles_file.read_text())
    roles['roles']['sampleobserver'] = {'grants': {'meeting': ['view']}}
    roles['roles']['sampleoutsider'] = {'grants': {'meeting': ['view']}}
    roles_file.write_text(json.dumps(roles))
    shutil.copytree(APP, apps / 'meeting', ignore=shutil.ignore_patterns('__pycache__', 'tests'))
    client = make_client()
    platform = client.app.state.platform
    issues = []
    companies = {'E-DEMO': {'id': 'E-DEMO', 'name': '公开演示企业'}}

    @client.app.post(ENTERPRISE + '/issues')
    def create_issue(body: dict, request: Request):
        # 在嵌套调用里重新读取会话。企业仍拥有对创建动作和资源的判定。
        if request.session.get('uid') != 'sampleadmin':
            return JSONResponse({'error': {'code': 'FORBIDDEN', 'message': '无权登记'}}, 403)
        if body['entId'] not in companies:
            return JSONResponse({'error': {'code': 'NOT_FOUND', 'message': '企业不存在'}}, 404)
        issue = {**body, 'id': f'ISS-{len(issues) + 1}', 'status': '待分派'}
        issues.append(issue)
        return {'item': issue}

    @client.app.get(ENTERPRISE + '/companies/{ent_id}')
    def company(ent_id: str):
        return {'item': companies[ent_id], 'issues': [issue for issue in issues if issue['entId'] == ent_id]}

    def agent(user_id='sampleadmin'):
        browser = TestClient(client.app)
        login = browser.post('/api/auth/login', json={'user_id': user_id})
        assert login.status_code == 200, login.text
        return browser

    assert platform.apps['meeting'].has_api, platform.apps['meeting'].error
    return agent


def seed(agent, *, transcript=True):
    response = agent.post(RECORDS, json={
        'type': 'meeting', 'project': 'sample-project',
        'data': {
            'title': '公开演示例会', 'date': '2026-11-17', 'type': '专题推进会',
            'host': '发言人 1', 'participants': ['发言人 1', '发言人 2'],
            'transcript': [
                ['00:00', '发言人 1', '会议决定：公开材料。待办：起草工作方案。'],
                ['00:05.716', '发言人 2', '待办：准备窗口答复。'],
                ['00:09', '发言人 1', '会议议定：窗口公开答复。待办：起草征集通知。'],
            ] if transcript else [],
            'topics': [], 'todos': [],
        },
    })
    assert response.status_code == 201, response.text
    return f"{MEETING}/meetings/{response.json()['id']}"


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def fails(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()['error']['code'] == code, response.text


def test_minutes_citations_and_all_four_edits(instance):
    agent = instance()
    path = seed(agent)
    detail = ok(agent.get(path))
    assert [section['refs'] for section in detail['minutes']['body']] == [['00:00'], ['00:09']]
    for section in detail['minutes']['body']:
        for source in section['sources']:
            assert [source['ts'], source['speaker'], source['quote']] == detail['item']['transcript'][source['index']]
    assert detail['minutes']['todos'] == detail['item']['todos']

    edited = detail['minutes']
    edited['body'][0]['p'] = '发言人 1：同意公开材料，经核对。'
    edited['body'][0]['sources'][0]['quote'] = '伪造的来源'
    saved = ok(agent.patch(path, json={'minutes': edited}))
    assert saved['minutes']['body'][0]['p'] == edited['body'][0]['p']
    assert saved['minutes']['body'][0]['sources'][0]['quote'] == detail['item']['transcript'][0][2]

    renamed = ok(agent.patch(path, json={'renameSpeaker': {'from': '发言人 1', 'to': '会议主持人'}}))
    assert [line[1] for line in renamed['item']['transcript']] == ['会议主持人', '发言人 2', '会议主持人']
    assert '发言人 1' not in json.dumps(renamed['minutes'], ensure_ascii=False)
    assert '会议主持人' in renamed['minutes']['attendees']
    assert all(section['sources'][0]['speaker'] == '会议主持人' for section in renamed['minutes']['body'])

    revised = ok(agent.patch(path, json={'line': {'index': 0, 'text': '会上修正为先核对再公开。'}}))
    assert revised['item']['transcript'][0] == ['00:00', '会议主持人', '会上修正为先核对再公开。']
    affected = revised['minutes']['body'][0]
    assert affected['needsReview'] and affected['sources'][0]['quote'] == revised['item']['transcript'][0][2]
    assert not revised['minutes']['body'][1].get('needsReview')

    todo_id = revised['item']['todos'][0]['id']
    todo_patch = {'id': todo_id, 'owner': '样例观察员', 'due': '2026-12-25'}
    updated = ok(agent.patch(path, json={'todo': todo_patch}))
    assert updated['item']['todos'][0]['certain']
    assert updated['minutes']['todos'][0]['owner'] == '样例观察员'
    assert updated['minutes']['todos'][0]['due'] == '2026-12-25'
    assert ok(agent.get(path)) == updated


def test_invalid_edits_and_transcript_visibility(instance):
    admin = instance()
    path = seed(admin)
    detail = ok(admin.get(path))
    missing_ref = detail['minutes']
    missing_ref['body'][0]['refs'] = ['99:00']
    for body in ({}, {'minutes': missing_ref}, {'line': {'index': -1, 'text': '错误'}},
                 {'todo': {'id': 'TD-1'}}, {'line': {'index': 0, 'text': '  '}}):
        fails(admin.patch(path, json=body), 422, 'INVALID_REQUEST')
    for body in ({'line': {'index': 50, 'text': '找不到这行'}},
                 {'renameSpeaker': {'from': '未知', 'to': '主持人'}},
                 {'todo': {'id': '未知', 'due': '2026-12-25'}}):
        fails(admin.patch(path, json=body), 404, 'NOT_FOUND')
    draft = seed(admin, transcript=False)
    assert ok(admin.get(draft))['minutes'] is None
    fails(admin.post(draft + '/todos/commit', json={'ids': []}), 409, 'INVALID_STATE')
    fails(instance('sampleobserver').patch(path, json={'line': {'index': 0, 'text': '无权限'}}), 403, 'FORBIDDEN')
    fails(instance('sampleoutsider').get(path), 404, 'NOT_FOUND')
    fails(TestClient(admin.app).get(path), 401, 'UNAUTHENTICATED')
    fails(admin.get(MEETING + '/meetings/不存在'), 404, 'NOT_FOUND')


def test_commit_skips_and_persists_once_in_recipient_list(instance):
    admin = instance()
    path = seed(admin)
    first, second, third = [todo['id'] for todo in ok(admin.get(path))['item']['todos']]
    commit = path + '/todos/commit'
    mine = MEETING + '/my-todos'
    for values in (
        {'id': first, 'owner': '样例观察员', 'due': '2001-01-01'},
        {'id': second, 'owner': '  ', 'due': '2026-12-25'},
        {'id': third, 'owner': 'sampleobserver', 'due': None},
    ):
        ok(admin.patch(path, json={'todo': values}))
    response = ok(admin.post(commit, json={'ids': [first, second, third, first, 'unknown']}))
    assert response == {'committed': [first], 'skipped': [
        {'id': second, 'reason': '缺少负责人'},
        {'id': third, 'reason': '缺少期限'},
        {'id': 'unknown', 'reason': '待办不存在'},
    ]}
    assert ok(admin.post(commit, json={'ids': [first]})) == {
        'committed': [], 'skipped': [{'id': first, 'reason': '待办已派发'}],
    }
    assert ok(admin.get(mine))['items'] == []
    assert ok(instance('sampleoutsider').get(mine))['items'] == []
    receiver = instance('sampleobserver')
    [assignment] = ok(receiver.get(mine))['items']
    assert assignment['ref'] == {'meetingId': path.rsplit('/', 1)[1], 'tab': 'todos', 'todoId': first}
    assert assignment['task'] == '起草工作方案'
    assert assignment['dueStatus'] == '逾期'
    assert assignment['reminder']['target'] == 'sampleobserver'
    assert 'assignment' not in ok(admin.get(path))['item']['todos'][0]
    fails(admin.patch(path, json={'todo': {'id': first, 'owner': 'sampleoperator'}}), 409, 'INVALID_STATE')


def test_parallel_commit_has_one_winner(instance):
    admin = instance()
    path = seed(admin)
    todo_id = ok(admin.get(path))['item']['todos'][0]['id']
    ok(admin.patch(path, json={'todo': {'id': todo_id, 'owner': 'sampleobserver', 'due': '周五'}}))
    clients = (instance(), instance())
    start = Barrier(2)

    def commit(client):
        start.wait(timeout=5)
        return ok(client.post(path + '/todos/commit', json={'ids': [todo_id]}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, clients))
    assert sum(len(result['committed']) for result in results) == 1
    assert sum(len(result['skipped']) for result in results) == 1
    [item] = ok(instance('sampleobserver').get(MEETING + '/my-todos'))['items']
    assert item['due'] == '周五' and item['dueStatus'] is None


def test_link_enters_company_detail_and_document_navigation(instance):
    admin = instance()
    path = seed(admin)
    issue = ok(admin.post(path + '/link', json={'entId': 'E-DEMO'}))['issue']
    assert issue['from'] == '会议' and issue['title'] == '公开演示例会中提出的诉求'
    assert ok(admin.get(ENTERPRISE + '/companies/E-DEMO'))['issues'] == [issue]
    fails(admin.post(path + '/link', json={'entId': 'UNKNOWN'}), 404, 'NOT_FOUND')
    fails(admin.post(path + '/link', json={}), 422, 'INVALID_REQUEST')
    fails(instance('sampleobserver').post(path + '/link', json={'entId': 'E-DEMO'}), 403, 'FORBIDDEN')

    todos = ok(admin.get(path))['item']['todos']
    for todo, template, key in zip(todos, ['T02', 'T10', 'T04'], ['title', 'issue', 'title'], strict=True):
        deep_link = ok(admin.get(f"{path}/todos/{todo['id']}/document-link"))
        meeting_id = path.rsplit('/', 1)[1]
        assert deep_link == {'app': 'document', 'route': 'new', 'params': {
            'templateId': template, 'autogen': True, 'fromMeeting': meeting_id,
            'inputs': {key: todo['task'].removeprefix('起草')},
            'from': {'app': 'meeting', 'id': meeting_id, 'title': '公开演示例会'},
        }}
    fails(admin.get(path + '/todos/unknown/document-link'), 404, 'NOT_FOUND')
