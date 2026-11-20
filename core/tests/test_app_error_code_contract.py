"""应用登记、SDK 1 严格比较和 jobs 快照使用同一份合成错误契约。"""

import json
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from conftest import ROOT
from haiknow_core.main import mount_app
from test_check_rules import check, run
from test_jobs import body, wait_job
from test_platform import login


APP = 'job-a'
OTHER = 'job-b'
CUSTOM = 'bad_response'
MESSAGE = '样例响应格式异常'
JOBS = '/api/v1/jobs'
ROUTER = '''
from fastapi import APIRouter, Depends
from haiknow_sdk import DataError, ModelError, app_context
from haiknow_sdk.ai import AIError
from haiknow_sdk.preview.jobs import operation

router = APIRouter()

@router.get('/failure')
def failure(ctx=Depends(app_context)):
    raise DataError('bad_response', '样例响应格式异常', retryable=True, fields=['format'])

@router.get('/missing')
def missing(ctx=Depends(app_context)):
    return ctx.records.get('missing')

@operation('failure', version='1')
def fail(job, body):
    if body['kind'] == 'ai':
        raise AIError('bad_response', '样例响应格式异常')
    if body['kind'] == 'model' or (body['kind'] == 'retry' and job.attempt == 1):
        raise ModelError('bad_response', '样例响应格式异常')
    return failure(job.context)

@router.get('/jobs/{jid}')
def python_job(jid: str, ctx=Depends(app_context)):
    return ctx.preview.jobs.get(jid)

@router.get('/jobs')
def python_list(ctx=Depends(app_context)):
    return ctx.preview.jobs.list()

@router.post('/jobs')
def python_submit(body: dict, ctx=Depends(app_context)):
    return ctx.preview.jobs.submit(**body)
'''


@pytest.fixture
def contract_apps(tmp_path):
    apps = tmp_path / 'contract' / 'apps'
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    for app_id, code in [(APP, CUSTOM), (OTHER, CUSTOM.upper())]:
        app = apps / app_id
        (app / 'api').mkdir(parents=True)
        (app / 'web').mkdir()
        (app / 'app.json').write_text(json.dumps({**manifest, 'id': app_id}))
        (app / 'api/router.py').write_text(ROUTER, encoding='utf-8')
        (app / 'web/errors.json').write_text(json.dumps({code: MESSAGE}), encoding='utf-8')
        (app / 'web/index.js').write_text("export const matches = error => error.code === 'bad_response';")
    return apps


def test_chk_err_03_requires_exact_registration(contract_apps, monkeypatch):
    root = contract_apps.parent
    target = root / check.PLATFORM_ERRORS_JS
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / check.PLATFORM_ERRORS_JS, target)
    monkeypatch.setattr(check, 'ROOT', root)
    assert run('errors', APP).errors == []
    errors = run('errors', OTHER).errors
    assert len(errors) == 2
    assert all('[CHK-ERR-03]' in error and CUSTOM in error for error in errors)
    assert any('/api/router.py:' in error for error in errors)
    assert any('/web/index.js:' in error for error in errors)


def failure_error(code, *, jid=None, data_error=True):
    error = {'code': code, 'message': MESSAGE, 'retryable': data_error}
    if data_error:
        error['fields'] = ['format']
    if jid is not None:
        error['jobId'] = jid
    return error


def test_http_uses_registered_app_directory_and_preserves_platform_errors(make_client, contract_apps):
    client = make_client()
    platform = client.app.state.platform
    # 使用真实挂载器把应用放在平台默认发现目录之外。
    for app_id in (APP, OTHER):
        source = contract_apps / app_id
        mount_app(client.app, platform, source, json.loads((source / 'app.json').read_text()))
    auth = client.get(f'{JOBS}/missing?app={APP}')
    assert (auth.status_code, auth.json()['error']['code']) == (401, 'UNAUTHENTICATED')
    login(client, 'sampleadmin')
    response = client.get(f'/api/apps/{APP}/failure?app={OTHER}')
    missing = client.get(f'/api/apps/{APP}/missing')
    platform_missing = client.get(f'/api/v1/apps/{APP}/records/missing')
    for control in [missing, platform_missing]:
        assert (control.status_code, control.json()['error']['code']) == (404, 'NOT_FOUND')
    other = client.get(f'/api/apps/{OTHER}/failure?app={APP}')
    assert (other.status_code, other.json()['error']['code']) == (400, 'BAD_RESPONSE')
    assert (response.status_code, response.json()) == (400, {'error': failure_error(CUSTOM)})


def test_sdk1_strict_comparison_over_real_http(make_client, contract_apps):
    node = shutil.which('node')
    if node is None:
        pytest.skip('SDK 1 HTTP 回归需要 node')
    sdk = contract_apps.parent / 'sdk'
    shutil.copytree(ROOT / 'core/sdk/js', sdk)
    (sdk / 'package.json').write_text('{"type":"module"}')
    shutil.copyfile(contract_apps / APP / 'web/index.js', sdk / 'app.js')
    script = """
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const sdk = pathToFileURL(process.argv[1]);
const { createContext, http } = await import(sdk);
const { matches } = await import(new URL('./app.js', sdk));
const base = process.argv[2];
const request = globalThis.fetch;
const login = await request(base + '/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_id: 'sampleoperator' }),
});
assert.equal(login.status, 200);
const cookie = login.headers.get('set-cookie').split(';', 1)[0];
globalThis.fetch = (path, opts) => request(base + path, {
  ...opts, headers: { ...opts?.headers, cookie },
});
const { apps } = await http('/api/apps');
const app = apps.find(app => app.id === process.argv[3]);
assert.equal(app.sdk, '1');
await assert.rejects(createContext(app, {}, () => {}).api('/failure'), error => {
  assert.equal(error.status, 400);
  assert.equal(matches(error), true, error.code);
  return true;
});
"""
    server = uvicorn.Server(uvicorn.Config(make_client(contract_apps).app, log_level='warning'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        base = f'http://127.0.0.1:{listener.getsockname()[1]}'
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while thread.is_alive() and not server.started and time.monotonic() < deadline:
                time.sleep(.01)
            assert server.started, 'SDK HTTP 测试服务启动失败'
            result = subprocess.run(
                [node, '--input-type=module', '-e', script, str(sdk / 'haiknow.js'), base, APP],
                capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=5)


@pytest.mark.parametrize(('kind', 'code'), [('data', CUSTOM), ('model', 'BAD_RESPONSE'), ('ai', 'BAD_RESPONSE')])
def test_new_job_uses_error_source(make_client, contract_apps, kind, code):
    request = body(operation='failure', input={'kind': kind})
    with make_client(contract_apps) as client:
        login(client, 'sampleoperator')
        queued = client.post(JOBS, json=request)
        assert queued.status_code == 202
        jid = queued.json()['id']
        public = wait_job(client, jid)
        assert public['status'] == 'failed'
        assert set(public) == set(queued.json())
        expected = failure_error(code, jid=jid, data_error=kind == 'data')
        assert public['error'] == expected
        assert client.get(f'{JOBS}?app={APP}').json() == {'items': [public]}
        replay = client.post(JOBS, json=request)
        assert replay.status_code == 202 and replay.json() == public

        raw = {**public, 'error': {**expected, 'code': CUSTOM}}
        python_api = f'/api/apps/{APP}/jobs'
        assert client.get(f'{python_api}/{jid}').json() == raw
        assert client.get(python_api).json() == {'items': [raw]}
        assert client.post(python_api, json={
            'operation': 'failure', 'project': request['project'], 'input': request['input'],
            'idempotency_key': request['idempotencyKey'],
        }).json() == raw
    # 重启读到创建失败时的 HTTP 码，即使之后应用移除了登记。
    (contract_apps / APP / 'web/errors.json').unlink()
    reopened = make_client(contract_apps)
    login(reopened, 'sampleoperator')
    assert reopened.get(f'{JOBS}/{jid}').json() == public


def test_retry_replaces_first_failure_projection(make_client, contract_apps):
    with make_client(contract_apps) as client:
        login(client, 'sampleoperator')
        request = body(operation='failure', input={'kind': 'retry'})
        jid = client.post(JOBS, json=request).json()['id']
        first = wait_job(client, jid)
        assert (first['attempt'], first['error']['code']) == (1, 'BAD_RESPONSE')
        retry = client.post(f'{JOBS}/{jid}/retry')
        assert retry.status_code == 202
        assert set(retry.json()) == set(first) and retry.json()['error'] is None
        second = wait_job(client, jid)
        assert (second['attempt'], second['error']['code']) == (2, CUSTOM)
        assert client.post(JOBS, json=request).json() == second


@pytest.mark.parametrize(('app_id', 'code'), [(APP, CUSTOM), (OTHER, 'BAD_RESPONSE')])
def test_historical_job_uses_exact_app_registration_without_rewriting(make_client, contract_apps, app_id, code):
    client = make_client(contract_apps)
    login(client, 'sampleoperator')
    request = body(appId=app_id, operation='failure', input={'kind': 'data'})
    job = client.post(JOBS, json=request).json()
    jid = job['id']
    snapshot = json.dumps({**job, 'status': 'failed', 'error': failure_error(CUSTOM, jid=jid)})
    store = client.app.state.platform.store
    with store._lock, store._db as db:
        db.execute("update v1_jobs set status='failed', document=? where id=?", (snapshot, jid))

    response = client.get(f'{JOBS}/{jid}')
    assert (response.status_code, response.json()['error']['code']) == (200, code)
    assert client.get(f'{JOBS}?app={app_id}').json() == {'items': [response.json()]}
    assert client.post(JOBS, json=request).json() == response.json()
    with store._lock:
        assert store._db.execute('select document from v1_jobs where id=?', (jid,)).fetchone()[0] == snapshot
