const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const { loadScript } = require('./mock.cjs');

function setup(api, globals = {}) {
  const http = [];
  const mock = [];
  const warnings = [];
  const context = vm.createContext({
    JK_CONFIG: { api }, FormData, URL, AbortController, setTimeout, clearTimeout,
    console: { warn: value => warnings.push(value) },
    JKAPI: {
      request: async (method, path, body) => { mock.push({ method, path, body }); return {}; },
      reset: () => mock.push({ reset: true }),
    },
    fetch: async (url, options) => {
      http.push({ url, ...options });
      return { ok: true, json: async () => ({}) };
    },
    ...globals,
  });
  context.window = context;
  loadScript(context, 'api/http.js');
  return { context, http, mock, warnings };
}

const baseUrl = 'http://127.0.0.1:8000/';

test('只切 policy 时，实际 policy adapter 请求 HTTP，其余七个模块默认 mock', async () => {
  const { context, http, mock } = setup({ mode: 'mock', baseUrl, modules: { policy: 'http' } });
  for (const id of ['platform', 'policy', 'enterprise', 'meeting', 'document', 'kb', 'skills', 'computer']) {
    loadScript(context, 'api/' + id + '.js');
  }
  const api = context.JKApi;
  await api.policy.items({ q: '数据券' });
  await api.policy.match({ entId: 'E001' });
  await api.me.get();
  await api.kb.spaces();
  await api.enterprise.list();
  await api.meeting.job('JOB-1');
  await api.document.list();
  await api.skills.get('SK-1');
  await api.computer.tasks();

  assert.deepEqual(http.map(({ method, url }) => [method, url]), [
    ['GET', 'http://127.0.0.1:8000/api/apps/policy/items?q=%E6%95%B0%E6%8D%AE%E5%88%B8'],
    ['POST', 'http://127.0.0.1:8000/api/apps/policy/match'],
  ]);
  assert.equal(http[1].body, '{"entId":"E001"}');
  assert.equal(http[1].credentials, 'include');
  assert.deepEqual(mock.map(call => call.path), [
    '/api/v1/me', '/api/v1/kb/spaces', '/api/apps/enterprise/companies', '/api/v1/jobs/JOB-1',
    '/api/apps/document/documents', '/api/v1/skills/SK-1', '/api/apps/computer/tasks',
  ]);
});

test('缺省 modules 时分别保留原全局 mock / HTTP 传输', async () => {
  for (const mode of ['mock', 'http']) {
    const { context, http, mock, warnings } = setup({ mode, baseUrl });
    await context.JKHttp.get('/api/apps/policy/items');
    assert.equal(context.JKHttp.mode(), mode);
    assert.equal(http.length, Number(mode === 'http'));
    assert.equal(mock.length, Number(mode === 'mock'));
    assert.deepEqual(warnings, []);
  }
});

test('未知模块只警告一次，继承属性和无效覆盖沿用全局 mode', async () => {
  const modules = Object.assign(Object.create({ policy: 'http' }), {
    unknown: 'http', constructor: 'http', enterprise: 'other',
  });
  const { context, http, mock, warnings } = setup({ mode: 'mock', baseUrl, modules });
  await context.JKHttp.get('/api/apps/unknown/items');
  await context.JKHttp.get('/api/apps/policy/items');
  await context.JKHttp.get('/api/apps/enterprise/companies');
  assert.equal(mock.length, 3);
  assert.equal(http.length, 0);
  assert.deepEqual(warnings, ['已忽略未知的 API 模块：unknown', '已忽略未知的 API 模块：constructor']);
});

test('全局 http 下只补载显式 mock 的应用脚本，并按覆盖分流', async () => {
  const scripts = [];
  const { context, mock, http } = setup({ mode: 'http', baseUrl, modules: { kb: 'mock' } }, {
    document: {
      readyState: 'loading',
      currentScript: { src: 'file:///tmp/web/api/http.js' },
      write: value => scripts.push(value),
    },
    JK_APP_LIST: [{ id: 'kb', mock: true }, { id: 'policy', mock: true }],
  });
  await context.JKHttp.get('/api/v1/kb/spaces');
  await context.JKHttp.get('/api/apps/policy/items');
  assert.equal(mock[0].path, '/api/v1/kb/spaces');
  assert.equal(http[0].url, baseUrl + 'api/apps/policy/items');
  assert.deepEqual(scripts, ['<script src="file:///tmp/web/mock/kb.js"></script>']);
});

test('平台覆盖也用于演示重置，HTTP 错误保留规范字段', async () => {
  const { context, mock, http } = setup({ mode: 'mock', baseUrl, modules: { platform: 'http' } });
  loadScript(context, 'api/platform.js');
  await context.JKApi.demo.reset();
  assert.equal(http[0].url, baseUrl + 'api/v1/demo/reset');
  assert.equal(mock.length, 0);

  context.fetch = async () => new Response(JSON.stringify({
    error: { code: 'FORBIDDEN', message: '没有权限', details: { app: 'platform' } },
  }), { status: 403 });
  await assert.rejects(context.JKApi.me.get(), error =>
    error.status === 403 && error.code === 'FORBIDDEN' && error.message === '没有权限' && error.details.app === 'platform');
});
