"""preview 知识库句柄：Python 上下文身份绑定与浏览器路径契约。"""
import json
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_platform import login

BASE = '/api/v1/knowledge'


def test_python_preview_uses_context_identity(make_client, tmp_path):
    apps = tmp_path / 'apps'
    app = apps / 'kb-preview'
    (app / 'api').mkdir(parents=True)
    manifest = json.loads((ROOT / 'tests/fixtures/platform-app/app.json').read_text())
    (app / 'app.json').write_text(json.dumps({**manifest, 'id': 'kb-preview'}))
    (app / 'api/router.py').write_text('''
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from haiknow_sdk import app_context

router = APIRouter()

@router.post('/upload')
def upload(ctx=Depends(app_context)):
    return ctx.preview.knowledge.upload('依据.txt', '预览上传正文'.encode(), title='预览上传',
                                        category='01-制度标准通知', tags=['预览'], project='sample-project')

@router.get('/entry/{entry_id}')
def entry(entry_id: str, ctx=Depends(app_context)):
    return ctx.preview.knowledge.get(entry_id)

@router.get('/list')
def listing(ctx=Depends(app_context)):
    return ctx.preview.knowledge.list(q='预览')

@router.post('/publish/{entry_id}')
def publish(entry_id: str, ctx=Depends(app_context)):
    return ctx.preview.knowledge.publish(entry_id, 1)

@router.post('/shared')
def shared(ctx=Depends(app_context)):
    return ctx.preview.knowledge.upload('共享依据.txt', '公司共享正文'.encode(), title='共享依据',
                                        category='01-制度标准通知', project='sample-project', scope='company')

@router.get('/read/{entry_id}')
def read(entry_id: str, ctx=Depends(app_context)):
    return Response(ctx.preview.knowledge.read(entry_id), media_type='text/plain')
''')
    c = make_client(apps)
    login(c, 'sampleoperator')
    entry = c.post('/api/apps/kb-preview/upload').json()
    assert entry['sourceApp'] == 'kb-preview' and entry['latest']['name'] == '依据.txt'
    assert entry['visibility'] == 'internal' and entry['publishedVersion'] is None
    assert entry['scope'] == 'project'
    assert c.get(f'{BASE}/entries/{entry["id"]}').status_code == 200
    assert c.post('/api/apps/kb-preview/publish/' + entry['id']).status_code == 403
    assert c.post('/api/apps/kb-preview/shared').status_code == 403

    login(c, 'samplereviewer')
    published = c.post('/api/apps/kb-preview/publish/' + entry['id']).json()
    assert published['publishedVersion'] == 1
    shared = c.post('/api/apps/kb-preview/shared').json()
    assert shared['scope'] == 'company' and shared['project'] == 'sample-project'
    assert c.get('/api/apps/kb-preview/list').json()['items'][0]['id'] == entry['id']
    assert c.get('/api/apps/kb-preview/read/' + entry['id']).content == '预览上传正文'.encode()
    login(c, 'sampleoutsider')
    assert c.get(f'{BASE}/entries/{entry["id"]}').status_code == 403


def test_js_preview_binds_app_and_uses_knowledge_paths():
    node = shutil.which('node')
    if not node:
        pytest.skip('浏览器 SDK 执行验证需要 node')
    script = r'''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const data = text => 'data:text/javascript;base64,' + Buffer.from(text).toString('base64');
const preview = data(readFileSync(process.argv[2], 'utf8'));
const withErrors = (text) => text.replaceAll('./preview/errors.js', 'data:text/javascript;base64,' + readFileSync(process.argv[1].replace('haiknow.js', 'preview/errors.js')).toString('base64'));
const source = withErrors(readFileSync(process.argv[1], 'utf8')).replaceAll('./preview/knowledge.js', preview);
const sdk = await import(data(source));
const calls = [];
globalThis.fetch = async (path, init = {}) => {
  calls.push({ path, init });
  return { ok: true, headers: { get: () => 'application/json' }, json: async () => ({ items: [] }) };
};
const ctx = sdk.createContext({ id: 'app-a', actions: ['view', 'operate'] }, {}, () => {});
const last = () => calls.at(-1);
await ctx.preview.knowledge.list({ q: '制度', includeUnpublished: true, limit: 5 });
assert.equal(last().path, '/api/v1/knowledge/entries?' + new URLSearchParams({ q: '制度', includeUnpublished: 'true', limit: '5' }));
await ctx.preview.knowledge.get('a/b');
assert.equal(last().path, '/api/v1/knowledge/entries/a%2Fb');
await ctx.preview.knowledge.submit('e1', 2);
assert.equal(last().path, '/api/v1/knowledge/entries/e1/submit');
assert.deepEqual(JSON.parse(last().init.body), { version: 2 });
await ctx.preview.knowledge.publish('e1', 3);
assert.equal(last().path, '/api/v1/knowledge/entries/e1/publish');
await ctx.preview.knowledge.update('e1', { tags: ['甲', '乙'] });
assert.equal(last().init.method, 'PATCH');
assert.deepEqual(JSON.parse(last().init.body), { tags: ['甲', '乙'] });
await ctx.preview.knowledge.references('e1');
assert.equal(last().path, '/api/v1/knowledge/entries/e1/references');
await ctx.preview.knowledge.recordFiles('app-a', 'r1', 3);
assert.equal(last().path, '/api/v1/knowledge/records/app-a/r1/versions/3/files');
await ctx.preview.knowledge.categories();
assert.equal(last().path, '/api/v1/knowledge/categories');
await ctx.preview.knowledge.upload(new File(['正文'], '依据.txt'), {
  title: '单据', category: '01-制度标准通知', tags: ['甲', '乙'], visibility: 'restricted',
  roles: ['samplereviewer'], project: 'sample-project', scope: 'company', note: '登记', text: '解析文本',
});
assert.equal(last().path, '/api/v1/knowledge/entries');
assert.equal(last().init.method, 'POST');
const body = last().init.body;
assert.equal(body.get('file').name, '依据.txt');
assert.equal(body.get('sourceApp'), 'app-a');
assert.equal(body.get('tags'), '甲,乙');
assert.equal(body.get('roles'), 'samplereviewer');
assert.equal(body.get('visibility'), 'restricted');
assert.equal(body.get('scope'), 'company');
assert.equal(body.get('text'), '解析文本');
assert.equal(body.get('note'), '登记');
await ctx.preview.knowledge.addVersion('e1', new File(['v2'], '依据-v2.txt'), { note: '换版' });
assert.equal(last().path, '/api/v1/knowledge/entries/e1/versions');
assert.equal(last().init.body.get('file').name, '依据-v2.txt');
assert.equal(last().init.body.get('sourceApp'), null);
assert.equal(ctx.preview.knowledge.url('e/1', 2), '/api/v1/knowledge/entries/e%2F1/versions/2/content');
console.log('preview JS 知识库路径与应用绑定通过');
'''
    result = subprocess.run(
        [node, '--input-type=module', '-e', script, str(ROOT / 'core/sdk/js/haiknow.js'),
         str(ROOT / 'core/sdk/js/preview/knowledge.js')],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'preview JS 知识库路径与应用绑定通过' in result.stdout
