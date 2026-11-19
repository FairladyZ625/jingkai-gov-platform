"""浏览器 SDK 的任务路径、应用绑定、错误信封，以及操作定义的加载隔离。"""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_jobs import ROUTER, body
from test_platform import login


def test_browser_job_handle_routes_and_error_fields():
    node = shutil.which('node')
    if node is None:
        pytest.skip('浏览器 SDK 执行验证需要 node')
    script = r'''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const withErrors = (text) => text.replaceAll('./preview/errors.js', 'data:text/javascript;base64,' + readFileSync(process.argv[1].replace('haiknow.js', 'preview/errors.js')).toString('base64'));
const sdk = await import('data:text/javascript;base64,' + Buffer.from(withErrors(readFileSync(process.argv[1], 'utf8'))).toString('base64'));
const jobs = await import('data:text/javascript;base64,' + Buffer.from(readFileSync(process.argv[2])).toString('base64'));
const calls = [];
globalThis.fetch = async (path, init) => {
  calls.push({ path, init });
  return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ id: 'job' }) };
};
const ctx = sdk.createContext({ id: 'job-a', actions: ['view', 'operate'] }, { id: 'sampleoperator' }, () => {});
await jobs.submit(sdk.http, ctx.app.id, { operation: 'demo', project: 'sample-project', input: {}, idempotencyKey: 'one', appId: 'job-b' });
assert.equal(calls.at(-1).path, '/api/v1/jobs');
assert.equal(calls.at(-1).init.method, 'POST');
assert.equal(JSON.parse(calls.at(-1).init.body).appId, 'job-a');
await jobs.get(sdk.http, ctx.app.id, 'job/1');
assert.equal(calls.at(-1).path, '/api/v1/jobs/job%2F1?app=job-a');
await jobs.list(sdk.http, ctx.app.id, { status: 'running', app: 'job-b' });
assert.equal(new URL(calls.at(-1).path, 'http://example.test').searchParams.get('app'), 'job-a');
await jobs.cancel(sdk.http, ctx.app.id, 'job/1');
assert.equal(calls.at(-1).path, '/api/v1/jobs/job%2F1/cancel?app=job-a');
assert.equal(calls.at(-1).init.method, 'POST');
await jobs.retry(sdk.http, ctx.app.id, 'job/1');
assert.equal(calls.at(-1).path, '/api/v1/jobs/job%2F1/retry?app=job-a');
await jobs.notifications(sdk.http, ctx.app.id);
assert.equal(calls.at(-1).path, '/api/v1/jobs/notifications?app=job-a');
await jobs.readNotification(sdk.http, ctx.app.id, 'note/1');
assert.equal(calls.at(-1).path, '/api/v1/jobs/notifications/note%2F1/read?app=job-a');
globalThis.fetch = async () => ({ ok: false, status: 409, headers: { get: () => 'application/json' },
  json: async () => ({ error: { code: 'INVALID_STATE', message: '防重复编号冲突', retryable: false, jobId: 'old' } }) });
await assert.rejects(() => jobs.submit(sdk.http, ctx.app.id, {}), e => e.status === 409 && e.code === 'INVALID_STATE' && e.retryable === false && e.jobId === 'old');
console.log('任务 SDK：七类路由、应用绑定、URL 编码与错误字段通过');
'''
    result = subprocess.run([node, '--input-type=module', '-e', script, str(ROOT / 'core/sdk/js/haiknow.js'),
                             str(ROOT / 'core/sdk/js/preview/jobs.js')],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_operation_only_disables_its_app(make_client, tmp_path):
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    apps = tmp_path / 'apps'
    for app_id, source in [('good', ROUTER), ('bad', ROUTER + "\n@operation('demo', version='2')\ndef duplicate(job, body): return {}\n")]:
        p = apps / app_id
        (p / 'api').mkdir(parents=True)
        (p / 'app.json').write_text(json.dumps({**manifest, 'id': app_id}))
        (p / 'api/router.py').write_text(source)
    c = make_client(apps)
    assert c.get('/api/health').json()['unavailable'] == ['bad']
    login(c, 'sampleoperator')
    assert c.post('/api/v1/jobs', json=body(appId='good')).status_code == 202
    assert c.post('/api/v1/jobs', json=body(appId='bad')).status_code == 503
