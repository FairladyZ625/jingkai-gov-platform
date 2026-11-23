"""冻结夹具通过真实平台装载；平台变动后夹具不跟着改。"""
import json
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from conftest import ROOT
from test_platform import login

BASE = '/api/apps/sdk1-app'


def test_frozen_sdk1_app(make_client, tmp_path):
    apps = tmp_path / 'apps'
    shutil.copytree(ROOT / 'tests/compat/sdk1_app', apps / 'sdk1-app')
    c = make_client(apps)
    assert c.get(BASE + '/context').status_code == 401
    login(c, 'sampleobserver')
    assert c.post(BASE + '/legacy').status_code == 403
    login(c, 'sampleoperator')
    ctx = c.get(BASE + '/context').json()
    assert ctx['user'] == 'sampleoperator' and ctx['approve'] is False
    old = c.post(BASE + '/legacy').json()
    assert old['content'] == 'sdk1' and old['missing'] == 'default'
    assert old['kv']['sdk1-file'] == old['value'] == old['files'][0]['id']
    assert old['available'] is False and old['answer'].startswith('[模拟模型]')
    ai = c.post(BASE + '/ai').json()
    assert ai == {name: {'kind': 'not_configured', 'retryable': False}
                  for name in ['chat', 'image', 'transcribe', 'speech', 'embedding']}
    f = c.post(BASE + '/upload').json()
    rec = c.post(BASE + '/save', json={'project': 'sample-project', 'type': 'sample', 'data': {'value': 1}, 'files': [f['fileId']]}).json()
    assert rec['version'] == 1
    r = c.post(BASE + '/submit', json={'record_id': rec['id'], 'version': 1, 'assignee': 'samplereviewer'})
    assert r.status_code == 200, r.text
    review = r.json()
    login(c, 'samplereviewer')
    assert c.get(BASE + '/context').json()['approve'] is True
    assert c.get(BASE + '/reviews').json()['items'][0]['id'] == review['id']
    result = c.post(BASE + '/decision/' + review['id'], json={'version': 1, 'decision': 'confirm'})
    assert result.status_code == 200, result.text
    assert c.get(BASE + '/artifacts').json()['items'][0]['recordId'] == rec['id']
    login(c, 'sampleoperator')
    target = c.post(BASE + '/save', json={'project': 'sample-project', 'type': 'target', 'data': {},
                    'refs': [{'appId': 'sdk1-app', 'recordId': rec['id'], 'version': 1}]}).json()
    result = c.post(BASE + '/save', json={'id': rec['id'], 'baseVersion': 1, 'data': {'value': 2}})
    assert result.status_code == 200 and result.json()['version'] == 2
    assert c.get(BASE + f"/record/{rec['id']}?version=1").json()['data'] == {'value': 1}
    assert c.get(BASE + f"/record/{rec['id']}").json()['data'] == {'value': 2}
    assert len(c.get(BASE + '/records').json()['items']) == 2
    assert c.get(BASE + f"/record/{target['id']}").json()['status'] == 'recheck'
    note = c.get(BASE + '/notifications').json()['items'][0]
    assert c.post(BASE + '/read/' + note['id']).json()['read'] is True
    conflict = c.post(BASE + '/save', json={'id': rec['id'], 'baseVersion': 1, 'data': {}})
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'VERSION_CONFLICT'
    login(c, 'sampleadmin')
    assert 'sdk1.save' in {x['action'] for x in c.get('/api/audit?app_id=sdk1-app').json()['items']}


def test_template_browser_sdk_conflict_recovery_over_http(make_client, tmp_path):
    node = shutil.which('node')
    if node is None:
        pytest.skip('浏览器 SDK 执行验证需要 node')

    template = ROOT / 'apps/_template'
    manifest = json.loads((template / 'app.json').read_text())
    apps = tmp_path / 'apps'
    for app_id, sdk in [('legacy-explicit', '1'), ('legacy-default', None), ('current-sdk', '2')]:
        app = apps / app_id
        shutil.copytree(template / 'api', app / 'api')
        app_manifest = {**manifest, 'id': app_id}
        app_manifest.pop('sdk')
        if sdk is not None:
            app_manifest['sdk'] = sdk
        (app / 'app.json').write_text(json.dumps(app_manifest), encoding='utf-8')

    sdk_path = tmp_path / 'sdk'
    shutil.copytree(ROOT / 'core/sdk/js', sdk_path)
    (sdk_path / 'package.json').write_text('{"type":"module"}')
    script = r"""
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { createContext, http } = await import(pathToFileURL(process.argv[1]));
const base = process.argv[2];
const fetchOnNetwork = globalThis.fetch;
const login = await fetchOnNetwork(base + '/api/auth/login', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_id: 'sampleoperator' }),
});
assert.equal(login.status, 200);
const cookie = login.headers.get('set-cookie').split(';', 1)[0];
globalThis.fetch = (path, opts) => fetchOnNetwork(base + path, {
  ...opts, headers: { ...opts?.headers, cookie },
});
const catalog = (await http('/api/apps')).apps;
for (const [id, expected] of [
  ['legacy-explicit', 'version_conflict'],
  ['legacy-default', 'version_conflict'],
  ['current-sdk', 'VERSION_CONFLICT'],
]) {
  const app = catalog.find(item => item.id === id);
  const ctx = createContext(app, {}, () => {});
  const created = await ctx.api('/records', { json: { project: 'sample-project', title: '例稿' } });
  const path = '/records/' + created.id;
  const args = (version, title) => ({ method: 'PUT', json: { baseVersion: version, title } });
  const concurrent = await ctx.api(path, args(1, '并发更新'));
  assert.equal(concurrent.version, 2);
  const raw = await fetch('/api/apps/' + id + path, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ baseVersion: 1, title: '旧稿' }),
  });
  assert.equal(raw.status, 409);
  assert.equal((await raw.json()).error.code, 'VERSION_CONFLICT');
  const editing = { version: 1 };
  const saveLegacy = async () => {
    try {
      return await ctx.api(path, args(editing.version, '重试后保存'));
    } catch (error) {
      // 复刻 SDK 1 原模板 97224a6 的严格比较与重新读取。
      if (error.code === 'version_conflict') editing.version = (await ctx.api(path)).version;
      throw error;
    }
  };
  await assert.rejects(saveLegacy(), error => {
    assert.equal(error.code, expected, id);
    return error.status === 409 && error.currentVersion === 2 && error.retryable === false;
  });
  assert.equal(app.sdk, id === 'current-sdk' ? '2' : '1');
  assert.equal(editing.version, id === 'current-sdk' ? 1 : 2);
  await assert.rejects(
    ctx.records.save({ baseVersion: 1, data: {} }, created.id),
    error => error.status === 409 && error.code === expected && error.currentVersion === 2,
  );
  if (id !== 'current-sdk') {
    assert.equal((await saveLegacy()).version, 3);
    assert.equal((await ctx.api(path)).data.title, '重试后保存');
  }
}
"""
    server = uvicorn.Server(uvicorn.Config(make_client(apps).app, log_level='warning'))
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
                [node, '--input-type=module', '-e', script, str(sdk_path / 'haiknow.js'), base],
                capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        finally:
            server.should_exit = True
            thread.join(timeout=5)
