"""应用只使用 SDK 的真实服务流程，以及浏览器封装的路由与错误契约。"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from conftest import ROOT
from test_platform import login


SDK_ROUTER = '''
from fastapi import APIRouter, Depends
from haiknow_sdk import AppContext, app_context
router = APIRouter()

@router.post('/save')
def save(body: dict, ctx: AppContext = Depends(app_context)):
    return ctx.records.save(**body)

@router.get('/record/{rid}')
def record(rid: str, ctx: AppContext = Depends(app_context)):
    return ctx.records.get(rid)

@router.get('/records')
def records(ctx: AppContext = Depends(app_context)):
    return ctx.records.list()

@router.post('/file')
def file(ctx: AppContext = Depends(app_context)):
    f = ctx.data_files.save('演示.txt', b'demo', project='sample-project', purpose='演示')
    assert ctx.data_files.read(f['fileId']) == b'demo'
    return ctx.data_files.get(f['fileId'])

@router.post('/submit')
def submit(body: dict, ctx: AppContext = Depends(app_context)):
    return ctx.reviews.submit(**body)

@router.post('/decision/{rid}')
def decide(rid: str, body: dict, ctx: AppContext = Depends(app_context)):
    return ctx.reviews.decide(rid, **body)

@router.post('/preview-decision/{rid}')
def preview_decide(rid: str, body: dict, ctx: AppContext = Depends(app_context)):
    return ctx.preview.reviews.decide(rid, **body)

@router.get('/reviews')
def reviews(ctx: AppContext = Depends(app_context)):
    return ctx.reviews.list(assignee='me')

@router.get('/artifacts')
def artifacts(ctx: AppContext = Depends(app_context)):
    return ctx.artifacts.find()

@router.get('/notifications')
def notifications(ctx: AppContext = Depends(app_context)):
    return ctx.notifications.list()

@router.post('/read/{nid}')
def read(nid: str, ctx: AppContext = Depends(app_context)):
    return ctx.notifications.read(nid)
'''


def test_python_sdk_scopes_and_cross_app_flow(make_client, tmp_path):
    apps = tmp_path / 'apps'
    m = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    for app_id in ['sdk-a', 'sdk-b']:
        p = apps / app_id
        (p / 'api').mkdir(parents=True)
        (p / 'app.json').write_text(json.dumps({**m, 'id': app_id}))
        (p / 'api/router.py').write_text(SDK_ROUTER)
    c = make_client(apps)
    a, b = '/api/apps/sdk-a', '/api/apps/sdk-b'
    login(c, 'sampleoperator')
    file = c.post(a + '/file').json()
    source = c.post(a + '/save', json={'project': 'sample-project', 'type': 'source', 'data': {}, 'files': [file['fileId']]}).json()
    assert source['submitter'] == 'sampleoperator'
    review = c.post(a + '/submit', json={'record_id': source['id'], 'version': 1, 'assignee': 'samplereviewer'}).json()
    login(c, 'samplereviewer')
    assert len(c.get(a + '/reviews').json()['items']) == 1
    assert c.get(b + '/reviews').json()['items'] == []
    assert c.post(b + '/decision/' + review['id'], json={'version': 1, 'decision': 'confirm'}).status_code == 404
    assert c.post(a + '/decision/' + review['id'], json={'version': 1, 'decision': 'confirm'}).status_code == 200
    assert c.get(b + '/artifacts').json()['items'][0]['recordId'] == source['id']
    login(c, 'sampleoperator')
    target = c.post(b + '/save', json={'project': 'sample-project', 'type': 'report', 'data': {}, 'refs': [{'appId': 'sdk-a', 'recordId': source['id'], 'version': 1, 'fileId': file['fileId']}]}).json()
    assert c.post(a + '/save', json={'id': source['id'], 'baseVersion': 1, 'data': {}}).status_code == 200
    assert c.get(b + '/record/' + target['id']).json()['status'] == 'recheck'
    note = c.get(b + '/notifications').json()['items'][0]
    assert c.get(a + '/notifications').json()['items'] == []
    assert c.post(a + '/read/' + note['id']).status_code == 404
    assert c.post(b + '/read/' + note['id']).json()['read'] is True
    assert c.post(a + '/save', json={'id': source['id'], 'baseVersion': 1, 'data': {}}).json()['error']['code'] == 'VERSION_CONFLICT'
    assert len(c.get(b + '/records').json()['items']) == 1
    login(c, 'sampleobserver')
    assert c.post(b + '/save', json={'project': 'sample-project', 'type': 'report', 'data': {}}).status_code == 403


def test_browser_sdk_routes_and_error_codes():
    node = shutil.which('node')
    if node is None:
        import pytest
        pytest.skip('浏览器 SDK 执行验证需要 node')
    script = r'''
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const sdk = await import(pathToFileURL(process.argv[1]));
const calls = [];
globalThis.fetch = async (path, init) => {
  calls.push({ path, init });
  return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ ok: true }) };
};
const ctx = sdk.createContext({ id: 'app-b', sdk: '2', actions: ['view'] }, { id: 'sampleoperator' }, () => {});
await ctx.records.save({ project: 'sample-project', data: {} });
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/records');
await ctx.records.save({ baseVersion: 1 }, 'record/a');
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/records/record%2Fa');
assert.equal(calls.at(-1).init.method, 'PUT');
await ctx.records.get('r', 2);
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/records/r/versions/2');
await ctx.records.list({ status: 'draft' });
assert.match(calls.at(-1).path, /status=draft/);
await ctx.dataFiles.save(new Blob(['demo']), 'sample-project', '演示');
assert.equal(calls.at(-1).init.body.get('app'), 'app-b');
assert.equal(ctx.dataFiles.url('f/a'), '/api/v1/files/f%2Fa/content');
await ctx.dataFiles.get('f');
await ctx.reviews.submit('r', 1, 'samplereviewer');
assert.deepEqual(JSON.parse(calls.at(-1).init.body), { appId: 'app-b', recordId: 'r', version: 1, assignee: 'samplereviewer' });
await ctx.reviews.decide('review/a', { version: 1, decision: 'confirm' });
assert.equal(calls.at(-1).path, '/api/v1/reviews/review%2Fa/decisions');
await ctx.reviews.list();
await ctx.artifacts.find({ project: 'sample-project' });
await ctx.notifications.list();
assert.match(calls.at(-1).path, /app=app-b/);
await ctx.notifications.read('n');
const messageBody = { idempotencyKey: 'k1', recipientIds: ['samplereviewer'], recordId: 'r', version: 2, title: '变更', body: '请查看' };
await ctx.preview.messages.send(messageBody);
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/messages');
assert.deepEqual(JSON.parse(calls.at(-1).init.body), messageBody);
await ctx.preview.messages.inbox();
assert.equal(calls.at(-1).path, '/api/v1/messages');
await ctx.preview.messages.get('m/1');
assert.equal(calls.at(-1).path, '/api/v1/messages/m%2F1');
await ctx.preview.messages.read('m/1');
assert.equal(calls.at(-1).path, '/api/v1/messages/m%2F1/read');
await ctx.preview.messages.acknowledge('m/1');
assert.equal(calls.at(-1).path, '/api/v1/messages/m%2F1/acknowledge');
await ctx.preview.messages.sent();
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/messages/sent');
await ctx.preview.crossProject.records('SUP-SAMPLE-01', { type: 'quote' });
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/cross-project/records?subject=SUP-SAMPLE-01&type=quote');
await ctx.preview.crossProject.get('record/a', 2);
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/cross-project/records/record%2Fa?version=2');
globalThis.fetch = async (path, init) => {
  calls.push({ path, init });
  return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ ok: true }), arrayBuffer: async () => Uint8Array.from([65, 66]).buffer };
};
assert.deepEqual([...await ctx.preview.crossProject.readFile('file/a')], [65, 66]);
assert.equal(calls.at(-1).path, '/api/v1/apps/app-b/cross-project/files/file%2Fa/content');
await sdk.v1.me();
assert.equal(calls.at(-1).path, '/api/v1/me');
await sdk.v1.projects();
await sdk.v1.reviews();
await sdk.v1.notifications();
// 原应用 API 和 v1 方法共存。
await ctx.api('/records');
assert.equal(calls.at(-1).path, '/api/apps/app-b/records');
globalThis.fetch = async () => ({ ok: false, status: 409, headers: { get: () => 'application/json' }, json: async () => ({ error: { code: 'VERSION_CONFLICT', message: '记录已有新版本', retryable: false, currentVersion: 2 } }) });
await assert.rejects(() => ctx.records.save({}), e => e.status === 409 && e.code === 'VERSION_CONFLICT' && e.currentVersion === 2 && e.message === '记录已有新版本' && e.retryable === false);
const legacy = sdk.createContext({ id: 'app-b', sdk: '1', actions: ['view'] }, {}, () => {});
await assert.rejects(legacy.upload('/upload', new Blob(['演示'])), { code: 'version_conflict' });
await assert.rejects(legacy.preview.messages.get('m/1'), { code: 'version_conflict' });
await assert.rejects(sdk.v1.reviews(), { code: 'VERSION_CONFLICT' });
for (const code of ['loan_period_invalid', 'LOAN_PERIOD_INVALID']) {
  globalThis.fetch = async () => Response.json({ error: { code, message: '借期无效' } }, { status: 400 });
  await assert.rejects(legacy.api('/loan'), { code, status: 400 });
  await assert.rejects(ctx.api('/loan'), { code, status: 400 });
}
console.log('浏览器 SDK 路由、应用绑定、兼容调用与错误字段通过');
'''
    with tempfile.TemporaryDirectory(prefix='haiknow-sdk-') as temporary:
        sdk_root = Path(temporary) / 'sdk'
        shutil.copytree(ROOT / 'core/sdk/js', sdk_root)
        (sdk_root / 'package.json').write_text('{"type":"module"}')
        p = subprocess.run([node, '--input-type=module', '-e', script, str(sdk_root / 'haiknow.js')], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
