"""长任务真实 HTTP：受理、防重复、权限、取消、进度与并发。"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import ROOT
from test_platform import login


ROUTER = '''
import time
from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, app_context
from haiknow_sdk.preview.jobs import operation

router = APIRouter()

@operation('demo', version='1')
def demo(job, body):
    def calculate(key):
        for i in range(body.get('ticks', 1)):
            job.check_cancelled()
            job.progress(i, body.get('ticks', 1))
            time.sleep(body.get('delay', 0))
        return {'value': body.get('value', 7), 'key': key}
    return job.step('calculate', calculate)

@operation('failure', version='1')
def failure(job, body):
    job.step('saved', lambda key: job.context.kv.put('once', job.context.kv.get('once', 0) + 1))
    if job.attempt == 1:
        raise RuntimeError('不应回显的输入')
    return job.step('finish', lambda key: {'ok': True})

@operation('ai-image', version='1')
def ai_image(job, body):
    return job.step('image', lambda key: job.context.ai.image('虚构演示'))

@router.post('/submit')
def submit(body: dict, ctx: AppContext = Depends(app_context)):
    return ctx.preview.jobs.submit(**body)

@router.get('/job/{jid}')
def get(jid: str, ctx: AppContext = Depends(app_context)):
    return ctx.preview.jobs.get(jid)

@router.get('/preview')
def preview(ctx: AppContext = Depends(app_context)):
    return ctx.preview.jobs.list()
'''


@pytest.fixture
def jobs_client(make_client, tmp_path):
    apps = tmp_path / 'apps'
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    for app_id in ('job-a', 'job-b'):
        p = apps / app_id
        (p / 'api').mkdir(parents=True)
        (p / 'app.json').write_text(json.dumps({**manifest, 'id': app_id}))
        (p / 'api/router.py').write_text(ROUTER)
    return make_client(apps)


def body(**kw):
    return {'appId': 'job-a', 'operation': 'demo', 'project': 'sample-project',
            'idempotencyKey': 'demo-1', 'input': {'value': 7}, **kw}


def wait_job(c, jid, states=('done', 'failed', 'cancelled'), timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = c.get('/api/v1/jobs/' + jid)
        assert r.status_code == 200, r.text
        if r.json()['status'] in states:
            return r.json()
        time.sleep(.01)
    pytest.fail(f'任务未在 {timeout} 秒内进入 {states}: {r.text}')


def test_accepts_202_and_deduplicates_changed_input_conflicts(jobs_client):
    c = jobs_client
    login(c, 'sampleoperator')
    first = c.post('/api/v1/jobs', json=body(submitter='sampleadmin', status='done'))
    assert first.status_code == 202, first.text
    job = first.json()
    assert job['status'] == 'queued' and job['submitter'] == 'sampleoperator'
    assert job['version'] == '1' and job['attempt'] == 1
    assert c.post('/api/v1/jobs', json=body()).json()['id'] == job['id']
    conflict = c.post('/api/v1/jobs', json=body(input={'value': 8}))
    assert conflict.status_code == 409
    assert conflict.json()['error']['code'] == 'INVALID_STATE'
    assert conflict.json()['error']['retryable'] is False
    assert conflict.json()['error']['jobId'] == job['id']
    assert len(c.get('/api/v1/jobs?app=job-a').json()['items']) == 1


def test_python_preview_jobs_uses_context(jobs_client):
    c = jobs_client
    login(c, 'sampleoperator')
    r = c.post('/api/apps/job-a/submit', json={
        'operation': 'demo', 'project': 'sample-project', 'input': {}, 'idempotency_key': 'preview',
    })
    assert r.status_code == 200, r.text
    response = c.get('/api/apps/job-a/preview')
    assert response.status_code == 200, response.text
    assert [j['id'] for j in response.json()['items']] == [r.json()['id']]


def test_auth_scope_validation_and_sdk_app_binding(jobs_client):
    c = jobs_client
    assert c.post('/api/v1/jobs', json=body()).status_code == 401
    login(c, 'sampleobserver')
    assert c.post('/api/v1/jobs', json=body()).status_code == 403
    login(c, 'sampleoperator')
    for invalid in ({'project': 'private-project'}, {'appId': 'missing'}):
        assert c.post('/api/v1/jobs', json=body(**invalid)).status_code == 404
    for invalid in ({'operation': 'missing'}, {'input': []}, {'idempotencyKey': ''}):
        r = c.post('/api/v1/jobs', json=body(**invalid))
        assert r.status_code == 422, r.text
        assert r.json()['error']['code'] == 'INVALID_REQUEST'
    job = c.post('/api/apps/job-a/submit', json={
        'operation': 'demo', 'project': 'sample-project', 'input': {}, 'idempotency_key': 'sdk',
    }).json()
    assert c.get('/api/apps/job-a/job/' + job['id']).status_code == 200
    assert c.get('/api/apps/job-b/job/' + job['id']).status_code == 404
    login(c, 'samplereviewer')
    assert c.get('/api/v1/jobs/' + job['id']).status_code == 404
    assert c.post('/api/v1/jobs/' + job['id'] + '/cancel').status_code == 404


def test_cancel_queued_is_durable_and_terminal(jobs_client):
    c = jobs_client
    login(c, 'sampleoperator')
    jid = c.post('/api/v1/jobs', json=body()).json()['id']
    r = c.post('/api/v1/jobs/' + jid + '/cancel')
    assert r.json()['status'] == 'cancelled'
    assert c.post('/api/v1/jobs/' + jid + '/cancel').json()['status'] == 'cancelled'
    assert c.post('/api/v1/jobs/' + jid + '/retry').status_code == 409
    with c:
        assert c.get('/api/v1/jobs/' + jid).json()['status'] == 'cancelled'


def test_admin_cancel_audit_records_actual_actor(jobs_client):
    c = jobs_client
    login(c, 'sampleoperator')
    jid = c.post('/api/v1/jobs', json=body()).json()['id']
    login(c, 'sampleadmin')
    assert c.post('/api/v1/jobs/' + jid + '/cancel').json()['status'] == 'cancelled'
    entries = c.get('/api/audit?app_id=job-a').json()['items']
    cancelled = next(e for e in entries if e['action'] == 'job.cancelled')
    assert cancelled['user'] == 'sampleadmin' and cancelled['detail']['jobId'] == jid


def test_three_concurrent_jobs_progress_result_notifications_and_audit(jobs_client):
    with jobs_client as c:
        login(c, 'sampleoperator')
        ids = [c.post('/api/v1/jobs', json=body(idempotencyKey=f'parallel-{i}',
               input={'ticks': 30, 'delay': .02, 'value': i})).json()['id'] for i in range(3)]
        for jid in ids:
            running = wait_job(c, jid, ('running',))
            assert running['status'] == 'running'
        assert all(c.get('/api/v1/jobs/' + jid).json()['status'] == 'running' for jid in ids)
        for i, jid in enumerate(ids):
            done = wait_job(c, jid)
            assert done['status'] == 'done'
            assert done['result']['value'] == i
            assert done['steps'][0]['status'] == 'done'
            assert done['steps'][0]['progress']['total'] == 30
        notes = c.get('/api/v1/jobs/notifications?app=job-a').json()['items']
        assert {n['jobId'] for n in notes} == set(ids)
        assert c.post('/api/v1/jobs/notifications/' + notes[0]['id'] + '/read').json()['read']
        assert len(c.get('/api/v1/jobs/notifications?app=job-a').json()['items']) == 2
        login(c, 'sampleadmin')
        actions = {x['action'] for x in c.get('/api/audit?app_id=job-a').json()['items']}
        assert {'job.submit', 'job.running', 'job.done', 'job.step.running', 'job.step.done'} <= actions


def test_real_thirty_second_tasks_return_202_and_run_in_parallel(jobs_client):
    """Issue 的真实三十秒验收；不缩短 sleep、不改时钟。"""
    with jobs_client as c:
        login(c, 'sampleoperator')
        before = time.monotonic()
        ids = []
        for i in range(3):
            r = c.post('/api/v1/jobs', json=body(idempotencyKey=f'thirty-{i}',
                       input={'ticks': 30, 'delay': 1, 'value': i}))
            assert r.status_code == 202
            ids.append(r.json()['id'])
        # 若任务错误地在请求中同步执行，这里会耗时至少三十秒。
        assert time.monotonic() - before < 5
        for jid in ids:
            assert wait_job(c, jid, ('running',))['status'] == 'running'
        assert all(c.get('/api/v1/jobs/' + jid).json()['status'] == 'running' for jid in ids)
        for i, jid in enumerate(ids):
            done = wait_job(c, jid, timeout=40)
            assert done['status'] == 'done' and done['result']['value'] == i
            assert done['finishedAt'] - done['startedAt'] >= 30
        # 时间区间重叠直接证明并行，避免依赖机器负载上限。
        docs = [c.get('/api/v1/jobs/' + jid).json() for jid in ids]
        assert max(d['startedAt'] for d in docs) < min(d['finishedAt'] for d in docs)


def test_concurrent_duplicates_have_one_task_and_one_submit_audit(jobs_client):
    c = jobs_client
    login(c, 'sampleoperator')
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: c.post('/api/v1/jobs', json=body()), range(12)))
    assert {r.status_code for r in responses} == {202}
    assert len({r.json()['id'] for r in responses}) == 1
    reordered = body(input={'b': 2, 'a': 1}, idempotencyKey='order')
    first = c.post('/api/v1/jobs', json=reordered).json()
    assert c.post('/api/v1/jobs', json=body(input={'a': 1, 'b': 2}, idempotencyKey='order')).json()['id'] == first['id']
    login(c, 'sampleadmin')
    assert len([x for x in c.get('/api/audit?app_id=job-a').json()['items'] if x['action'] == 'job.submit']) == 2


def test_ai_queue_preserves_quota_error_and_can_be_retried_after_admin_change(jobs_client):
    with jobs_client as c:
        login(c, 'sampleadmin')
        assert c.put('/api/v1/admin/ai/providers/p', json={'kind': 'mock', 'models': ['m']}).status_code == 200
        assert c.put('/api/v1/admin/ai/routes/image', json={'provider': 'p', 'model': 'm'}).status_code == 200
        assert c.put('/api/v1/admin/ai/quotas/job-a', json={'max_calls': 0}).status_code == 200
        login(c, 'sampleoperator')
        jid = c.post('/api/v1/jobs', json=body(operation='ai-image')).json()['id']
        failed = wait_job(c, jid)
        assert failed['status'] == 'failed'
        assert failed['error']['code'] == 'QUOTA_EXCEEDED' and not failed['error']['retryable']
        assert failed['error']['jobId'] == jid
        assert failed['steps'][0]['status'] == 'failed'
        login(c, 'sampleadmin')
        c.put('/api/v1/admin/ai/quotas/job-a', json={'max_calls': 1})
        login(c, 'sampleoperator')
        assert c.post('/api/v1/jobs/' + jid + '/retry').status_code == 202
        done = wait_job(c, jid)
        assert done['status'] == 'done' and done['result']['result'][0]['url'] == 'mock://p'


def test_queued_task_rechecks_operation_version_and_permissions(jobs_client):
    c = jobs_client
    login(c, 'sampleoperator')
    first = c.post('/api/v1/jobs', json=body()).json()['id']
    second = c.post('/api/v1/jobs', json=body(appId='job-b')).json()['id']
    service = c.app.state.platform.jobs
    old = service.operations[('job-a', 'demo')]
    service.operations[('job-a', 'demo')] = ('2', old[1])
    # 走真实授权接口撤销 operate；提交时已有权限，执行时按数据库重查。
    login(c, 'sampleadmin')
    assert c.put('/api/admin/grants/sampleoperator/job-b', json={'actions': ['view']}).status_code == 200
    login(c, 'sampleoperator')
    with c:
        a, b = wait_job(c, first), wait_job(c, second)
        assert a['status'] == b['status'] == 'failed'
        assert a['error']['code'] == 'INVALID_STATE'
        assert b['error']['code'] == 'FORBIDDEN'
        assert a['steps'] == b['steps'] == []
        assert c.post('/api/v1/jobs/' + first + '/retry').status_code == 409


def test_running_cancel_waits_for_cooperation(jobs_client):
    with jobs_client as c:
        login(c, 'sampleoperator')
        jid = c.post('/api/v1/jobs', json=body(input={'ticks': 100, 'delay': .02})).json()['id']
        wait_job(c, jid, ('running',))
        assert c.post('/api/v1/jobs/' + jid + '/cancel').json()['status'] == 'cancelling'
        assert wait_job(c, jid)['status'] == 'cancelled'


def test_failure_retry_skips_completed_steps_and_hides_internal_text(jobs_client):
    with jobs_client as c:
        login(c, 'sampleoperator')
        jid = c.post('/api/v1/jobs', json=body(operation='failure')).json()['id']
        failed = wait_job(c, jid)
        assert failed['status'] == 'failed' and failed['error']['code'] == 'INTERNAL_ERROR'
        assert '不应回显' not in json.dumps(failed, ensure_ascii=False)
        retry = c.post('/api/v1/jobs/' + jid + '/retry')
        assert retry.status_code == 202 and retry.json()['attempt'] == 2
        done = wait_job(c, jid)
        assert done['status'] == 'done' and done['result'] == {'ok': True}
        assert c.app.state.platform.store.kv_get('job-a', 'once') == 1
