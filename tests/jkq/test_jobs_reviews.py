"""实例兼容路由、审签事务与跨进程任务恢复的 HTTP 回归。"""

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip('fastapi', reason='仓库通用 CI 仅安装 pytest，实例测试由 core CI 安装依赖后运行')

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from haiknow_core.main import create_app
from jkq import jobs_api, reviews_api


ROOT = Path(__file__).resolve().parents[2]
RECORDS = '/api/v1/apps/sample-app/records'
REVIEWS = '/api/v1/reviews'
JOBS = '/api/v1/jobs'
OPERATION = '''
import time
from fastapi import APIRouter
from haiknow_sdk.preview.jobs import operation

router = APIRouter()

@operation('transcribe', version='1')
def transcribe(job, body):
    def receive(key):
        job.context.kv.put('received', job.context.kv.get('received', 0) + 1)
        return body['ref']

    ref = job.step('收件', receive)

    def transcribe_audio(key):
        previous = job.context.kv.get('transcribe_key', None)
        if previous is None:
            job.context.kv.put('transcribe_key', key)
            job.progress(1, 2)
            while True:
                job.check_cancelled()
                time.sleep(.02)
        assert previous == key
        return ref

    transcript = job.step('转写', transcribe_audio)
    return job.step('生成纪要', lambda _: {'ref': transcript})
'''


def fake_current_user(request: Request):
    user = request.app.state.platform.rbac.users.get(request.headers.get('x-test-user'))
    if user is None:
        raise HTTPException(401, '未登录')
    return user


def install(app):
    for module in (jobs_api, reviews_api):
        module.install(app, fake_current_user)
    return app


def as_user(uid):
    return {'x-test-user': uid}


@pytest.fixture
def client(make_client):
    client = make_client()
    install(client.app)
    return client


def submit_review(client, assignee=None, *, app='sample-app', uid='sampleoperator',
                  project='sample-project'):
    # 原有 core 写入端点用演示会话准备测试数据。
    assert client.post('/api/auth/login', json={'user_id': uid}).status_code == 200
    record = client.post(f'/api/v1/apps/{app}/records', json={
        'project': project, 'type': 'report', 'data': {'title': '样例记录'},
    })
    assert record.status_code == 201, record.text
    response = client.post(REVIEWS, json={
        'appId': app, 'recordId': record.json()['id'], 'version': 1, 'assignee': assignee,
    })
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, review, *, uid='samplereviewer', **overrides):
    return client.post(f"{REVIEWS}/{review['id']}/decisions", headers=as_user(uid),
                       json={'decision': 'approve', 'version': 1, **overrides})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    error = response.json()['error']
    assert error['code'] == code
    assert error['message'] and isinstance(error['details'], dict)
    return error


def test_review_visibility_is_assigned_or_approvable_in_visible_project(client):
    raised = submit_review(client, 'samplereviewer')
    open_review = submit_review(client)
    outside_app = submit_review(client, app='sample-library')
    submit_review(client, uid='sampleadmin', project='limited-project')

    platform = client.app.state.platform
    original = platform.rbac.actions

    def actions(user, app):
        if user.id == 'samplereviewer' and app == 'sample-app':
            return original(user, app) - {'approve'}
        return original(user, app)

    platform.rbac.actions = actions

    def visible(uid):
        response = client.get(REVIEWS, headers=as_user(uid))
        assert response.status_code == 200, response.text
        return {item['id'] for item in response.json()['items']}

    assert visible('samplereviewer') == {raised['id'], outside_app['id']}
    assert visible('sampleextra') == {raised['id'], open_review['id']}
    assert visible('sampleobserver') == set()
    assert client.get(REVIEWS).status_code == 401
    assert_error(decide(client, raised), 403, 'FORBIDDEN')


@pytest.mark.parametrize(('verb', 'projected', 'stored', 'audit_verb'), [
    ('approve', 'done', 'confirmed', 'confirm'),
    ('reject', 'rejected', 'needs_info', 'return'),
])
def test_review_decision_updates_record_and_audits_exactly_once(client, verb, projected, stored, audit_verb):
    review = submit_review(client, 'samplereviewer')
    response = decide(client, review, decision=verb, reason='核查意见')
    assert response.status_code == 200, response.text
    item = response.json()['item']
    assert item['id'] == review['id'] and item['status'] == projected
    assert item['decision']['decision'] == verb
    assert item['decision']['comment'] == '核查意见'
    assert client.get(f"{RECORDS}/{review['recordId']}").json()['status'] == stored
    assert client.get(REVIEWS, headers=as_user('samplereviewer')).json() == {'items': []}
    assert_error(decide(client, review, decision=verb), 409, 'ALREADY_DECIDED')
    audit = client.app.state.platform.store.audit_list('sample-app')
    decisions = [event for event in audit if event['action'] == f'v1.review.{audit_verb}']
    assert len(decisions) == 1
    assert decisions[0]['user'] == 'samplereviewer'
    assert decisions[0]['detail']['reviewId'] == review['id']


def test_review_rejects_self_stale_unauthorized_and_invalid_decisions(client):
    own = submit_review(client, uid='samplereviewer')
    assert_error(decide(client, own), 409, 'SELF_REVIEW')
    review = submit_review(client, 'samplereviewer')
    assert_error(decide(client, review, uid='sampleobserver'), 403, 'FORBIDDEN')
    assert_error(decide(client, review, uid='sampleextra'), 403, 'FORBIDDEN')
    assert_error(decide(client, review, decision='confirm'), 422, 'INVALID_REQUEST')
    assert_error(decide(client, review, version=True), 422, 'INVALID_REQUEST')
    assert_error(decide(client, {'id': 'missing'}), 404, 'NOT_FOUND')
    assert_error(decide(client, review, version=2), 409, 'STALE_VERSION')
    target = f"{RECORDS}/{review['recordId']}"
    assert client.put(target, json={'baseVersion': 1, 'data': {}}).json()['version'] == 2
    error = assert_error(decide(client, review), 409, 'STALE_VERSION')
    assert error['details']['currentVersion'] == 2
    private = submit_review(client, uid='sampleadmin', project='limited-project')
    assert_error(decide(client, private, uid='sampleobserver'), 404, 'NOT_FOUND')
    no_app = submit_review(client, app='sample-library')
    assert_error(decide(client, no_app, uid='sampleextra'), 403, 'FORBIDDEN')
    assert not any(event['action'] in {'v1.review.confirm', 'v1.review.return'}
                   for event in client.app.state.platform.store.audit_list())


def test_simultaneous_decisions_have_one_winner(client):
    review = submit_review(client)
    with ThreadPoolExecutor(max_workers=2) as workers:
        decisions = list(workers.map(lambda verb: decide(client, review, decision=verb), ('approve', 'reject')))
    assert sorted(response.status_code for response in decisions) == [200, 409]
    assert_error(next(response for response in decisions if response.status_code == 409), 409, 'ALREADY_DECIDED')
    audit = client.app.state.platform.store.audit_list('sample-app')
    assert sum(event['action'] in {'v1.review.confirm', 'v1.review.return'} for event in audit) == 1


def test_job_missing_and_queued(client):
    client.app.state.platform.jobs.operations[('sample-app', 'transcribe')] = ('1', None)
    assert client.post('/api/auth/login', json={'user_id': 'sampleoperator'}).status_code == 200
    response = client.post(JOBS, json={
        'appId': 'sample-app', 'project': 'sample-project', 'operation': 'transcribe',
        'input': {}, 'idempotencyKey': 'queued-test',
    })
    assert response.status_code == 202, response.text
    uid = as_user('sampleoperator')
    job_id = response.json()['id']
    assert client.get(f'{JOBS}/{job_id}', headers=uid).json() == {
        'job': {'id': job_id, 'kind': 'transcribe', 'ref': None, 'status': 'running',
                'progress': 0, 'step': 0, 'steps': [], 'stepName': None},
    }
    assert_error(client.get(f'{JOBS}/missing', headers=uid), 404, 'NOT_FOUND')
    assert_error(client.get(f'{JOBS}/{job_id}', headers=as_user('samplereviewer')), 404, 'NOT_FOUND')
    schema = client.get('/openapi.json').json()['paths']
    assert schema[f'{JOBS}/{{jid}}']['get']['operationId'].startswith('get_job_')
    assert 'post' in schema[REVIEWS] and 'get' in schema[REVIEWS]


def run_job_process(mode, checkpoint):
    app = install(create_app(ROOT))
    with TestClient(app) as client:
        user = 'sampleoperator'
        headers = as_user(user)
        if mode == 'first':
            assert client.post('/api/auth/login', json={'user_id': user}).status_code == 200
            response = client.post(JOBS, json={
                'appId': 'sample-app', 'project': 'sample-project', 'operation': 'transcribe',
                'input': {'ref': 'meeting-example'}, 'idempotencyKey': 'restart-test',
            })
            assert response.status_code == 202, response.text
            job_id = response.json()['id']
        else:
            job_id = json.loads(checkpoint.read_text())['id']

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = client.get(f'{JOBS}/{job_id}', headers=headers)
            assert response.status_code == 200, response.text
            job = response.json()['job']
            if mode == 'first' and job['step'] == 1 and job['progress'] == 50:
                pending = checkpoint.with_suffix('.pending')
                pending.write_text(json.dumps(job))
                pending.replace(checkpoint)
                time.sleep(20)  # 等待父进程发送 SIGKILL。
                raise AssertionError('父进程未在第二步终止子进程')
            if mode == 'resume' and job['status'] == 'done':
                store = app.state.platform.store
                assert store.kv_get('sample-app', 'received') == 1
                assert store.kv_get('sample-app', 'transcribe_key') == f'{job_id}:转写'
                assert sum(event['action'] == 'job.recover' for event in store.audit_list()) == 1
                raw = app.state.platform.jobs.get(app.state.platform.rbac.users[user], job_id)
                assert raw['attempt'] == 1 and raw['result'] == {'ref': 'meeting-example'}
                print(json.dumps(job))
                return
            time.sleep(.02)
        raise AssertionError(f'未到达预期检查点：{job}')


def test_three_step_job_resumes_after_killing_step_two(isolated_platform, tmp_path):
    apps = isolated_platform[1]
    (apps / 'sample-app/api/router.py').write_text(OPERATION)
    checkpoint = tmp_path / 'checkpoint.json'
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(map(str, (ROOT, ROOT / 'core/server', ROOT / 'core/sdk')))}
    launch = [sys.executable, str(Path(__file__).resolve())]
    proc = subprocess.Popen([*launch, 'first', str(checkpoint)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 12
        while not checkpoint.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
    finally:
        if proc.poll() is None:
            proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
    assert checkpoint.exists() and proc.returncode == -signal.SIGKILL, stdout + stderr
    before = json.loads(checkpoint.read_text())
    assert before == {
        'id': before['id'], 'kind': 'transcribe', 'ref': 'meeting-example', 'status': 'running',
        'progress': 50, 'step': 1, 'steps': ['收件', '转写'], 'stepName': '转写',
    }
    resumed = subprocess.run([*launch, 'resume', str(checkpoint)], env=env,
                             capture_output=True, text=True, timeout=15)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert json.loads(resumed.stdout) == {
        **before, 'status': 'done', 'progress': 100, 'step': 2,
        'steps': ['收件', '转写', '生成纪要'], 'stepName': '生成纪要',
    }


if __name__ == '__main__':
    run_job_process(sys.argv[1], Path(sys.argv[2]))
