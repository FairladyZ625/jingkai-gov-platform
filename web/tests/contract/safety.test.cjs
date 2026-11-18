// HA 评审 review-dispatch_58a7e858 的回归：写入保护、明文凭据、知识库恢复、混合会话、必需字段。
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const test = require('node:test');
const { main, isWrite } = require('./run.cjs');
const { createContext, createMock, loadScript } = require('./mock.cjs');
const { verify } = require('./assertions.cjs');
const models = require('./models.json');

async function stubServer(t, handler) {
  const requests = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : undefined;
    requests.push({ method: req.method, url: req.url });
    const { status, body: out, cookie } = await handler(req, body);
    if (cookie) res.setHeader('Set-Cookie', cookie);
    res.writeHead(status, { 'Content-Type': 'application/json' }).end(JSON.stringify(out));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  return { base: 'http://127.0.0.1:' + server.address().port, requests };
}

const businessWrites = requests => requests.filter(({ method, url }) =>
  method !== 'GET' && !['/api/v1/auth/login', '/api/v1/auth/logout'].includes(url) && isWrite({ method, path: url }));

function mockBackend() {
  const mock = createMock();
  return {
    mock,
    handler: async (req, body) => {
      const response = await mock.request(req.method, req.url, body);
      return { ...response, cookie: req.url === '/api/v1/auth/login' && response.status === 200 ? 'sid=example; Path=/' : '' };
    },
  };
}

test('普通 HTTP 目标默认只读：全模块不发任何业务写请求，也不重置', async t => {
  const { mock, handler } = mockBackend();
  const { base, requests } = await stubServer(t, handler);
  const lines = [];
  const errors = [];
  const status = await main(['--base', base], {
    CONTRACT_USERNAME: mock.credentials.username, CONTRACT_PASSWORD: mock.credentials.password,
  }, line => lines.push(line), line => errors.push(line));
  assert.equal(status, 0, errors.join('\n'));
  assert.equal(lines[0], '契约模式：HTTP（只读）；模块：platform、kb、policy、enterprise、meeting、document、skills、computer');
  assert.ok(lines.some(line => /^platform: \d+\/\d+，错误样例 1\/1（只读模式跳过 \d+ 条写入）$/.test(line)), lines.join('\n'));
  assert.deepEqual(businessWrites(requests), []);
  assert.ok(!requests.some(({ url }) => url === '/api/v1/demo/reset'));
  assert.ok(requests.some(({ url }) => url === '/api/apps/policy/items'));
});

test('登录返回 401 时立即中止，含 --allow-writes 也不发业务写请求', async t => {
  for (const args of [[], ['--allow-writes']]) {
    const { base, requests } = await stubServer(t, async () => ({
      status: 401, body: { error: { code: 'BAD_CREDENTIALS', message: '账号或密码不正确', details: {} } },
    }));
    const env = { CONTRACT_USERNAME: 'sample', CONTRACT_PASSWORD: 'example', CONTRACT_RESETTABLE_TARGET: new URL(base).host };
    await assert.rejects(main(['--base', base, ...args], env, () => {}, () => {}), /登录失败（HTTP 401），已中止/);
    assert.deepEqual(requests, [{ method: 'POST', url: '/api/v1/auth/login' }]);
  }
});

test('--allow-writes 必须先确认目标可重置，否则不发任何请求', async t => {
  const { base, requests } = await stubServer(t, async () => ({ status: 200, body: {} }));
  const env = { CONTRACT_USERNAME: 'sample', CONTRACT_PASSWORD: 'example' };
  await assert.rejects(main(['--base', base, '--allow-writes'], env, () => {}, () => {}), /CONTRACT_RESETTABLE_TARGET=/);
  await assert.rejects(main(['--base', base, '--allow-writes'], { ...env, CONTRACT_RESETTABLE_TARGET: 'other.example:443' }, () => {}, () => {}), /CONTRACT_RESETTABLE_TARGET=/);
  await assert.rejects(main(['--allow-writes'], env, () => {}, () => {}), /只用于 HTTP 模式/);
  assert.deepEqual(requests, []);
});

test('远程明文 HTTP 在发请求前拒绝，回环 HTTP 与远程 HTTPS 放行', async t => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async url => { calls.push(String(url)); throw new TypeError('blocked in test'); };
  t.after(() => { globalThis.fetch = original; });
  const env = { CONTRACT_USERNAME: 'sample', CONTRACT_PASSWORD: 'synthetic-value' };
  for (const base of ['http://example.com', 'http://10.0.0.8:8000', 'http://127.0.0.1.example.com']) {
    await assert.rejects(main(['--base', base, '--module', 'platform'], env, () => {}, () => {}), /远程目标必须使用 HTTPS/);
  }
  assert.deepEqual(calls, []);
  for (const base of ['http://127.0.0.1:9', 'http://localhost:9', 'http://[::1]:9', 'https://demo.example.com']) {
    await assert.rejects(main(['--base', base, '--module', 'platform'], env, () => {}, () => {}), /无法访问后端/);
  }
  assert.deepEqual(calls.map(url => new URL(url).origin), [
    'http://127.0.0.1:9', 'http://localhost:9', 'http://[::1]:9', 'https://demo.example.com',
  ]);
});

test('知识库只删除本轮导入的资料，恢复走 /restore 并回读到原资料', async () => {
  const { routes } = require('./cases/kb.json');
  const docRoutes = routes.filter(route => route.path.startsWith('/api/v1/kb/docs/{id}') && route.method !== 'GET');
  assert.deepEqual(docRoutes.map(route => route.method + ' ' + route.path), [
    'PATCH /api/v1/kb/docs/{id}', 'DELETE /api/v1/kb/docs/{id}', 'POST /api/v1/kb/docs/{id}/restore',
  ]);
  assert.ok(docRoutes.every(route => route.params.id === '{{imported.docs.0.id}}'));
  assert.ok(routes.findIndex(route => route.save === 'imported') < routes.indexOf(docRoutes[0]));

  const mock = createMock();
  await mock.request('POST', '/api/v1/auth/login', mock.credentials);
  const imported = await mock.request('POST', '/api/v1/kb/import', { text: '仅用于契约测试的虚构资料，验证删除后可以撤销。', space: 'policy' });
  const id = imported.body.docs[0].id;
  assert.equal((await mock.request('DELETE', '/api/v1/kb/docs/' + id)).status, 200);
  assert.equal((await mock.request('GET', '/api/v1/kb/docs/' + id)).status, 404);
  assert.equal((await mock.request('POST', '/api/v1/kb/docs/' + id + '/restore', {})).status, 200);
  const back = await mock.request('GET', '/api/v1/kb/docs/' + id);
  assert.equal(back.status, 200);
  assert.equal(back.body.item.id, id);
  assert.equal((await mock.request('POST', '/api/v1/kb/docs/' + id, {})).status, 404, '简写恢复路径不再被改写');
});

test('混合模式：platform=http 登录后 kb=mock 可访问，JKAuth 有用户，HTTP 退出后清除', async () => {
  const fetches = [];
  const context = createContext({
    fetch: async (url, options) => {
      fetches.push({ url, body: options.body });
      const path = new URL(url).pathname;
      const out = path === '/api/v1/auth/logout' ? { ok: true }
        : { user: { id: 'remote-1', username: 'remote.leader', name: '远端账号', role: 'leader', status: 'active', deptId: 'd-x' } };
      return new Response(JSON.stringify(out), { status: 200 });
    },
    Response, AbortController, FormData,
  }, ctx => {
    ctx.JK_CONFIG.api = { mode: 'mock', baseUrl: 'https://demo.example.com', modules: { platform: 'http', kb: 'mock' } };
  });
  for (const id of ['platform', 'kb']) loadScript(context, 'api/' + id + '.js');
  const api = context.JKApi;
  assert.equal(context.JKAuth.user(), null);
  await assert.rejects(api.kb.spaces(), error => error.status === 401);

  await api.auth.login({ username: 'remote.leader', password: 'synthetic-value' });
  assert.equal(fetches.length, 1);
  assert.equal(new URL(fetches[0].url).pathname, '/api/v1/auth/login');
  const spaces = await api.kb.spaces();
  assert.ok(spaces.items.length > 0);
  assert.equal(context.JKAuth.user().role, 'leader');
  const session = context.JKAPI.state().session;
  assert.equal(session.bridged, true);
  assert.ok(!JSON.stringify(context.JKAPI.state()).includes('synthetic-value'), '本地状态不保存远端口令');

  await api.auth.logout();
  assert.equal(context.JKAuth.user(), null);
  await assert.rejects(api.kb.spaces(), error => error.status === 401);
});

function requiredPaths(schema, prefix = []) {
  // 列出 schema 中每个必需字段的路径（数组取第 0 项），供逐项删除。
  if (typeof schema === 'string') {
    if (schema.startsWith('@')) return requiredPaths(models[schema.slice(1)], prefix);
    return [];
  }
  if (Array.isArray(schema)) return schema.length === 1 ? requiredPaths(schema[0], [...prefix, 0]) : [];
  return Object.entries(schema).flatMap(([key, field]) => [[...prefix, key], ...requiredPaths(field, [...prefix, key])]);
}

function mutate(body, path, change) {
  const copy = structuredClone(body);
  let parent = copy;
  for (const key of path.slice(0, -1)) {
    parent = parent?.[key];
    if (parent == null) return null;
  }
  if (!parent || !Object.hasOwn(parent, path.at(-1))) return null;
  change(parent, path.at(-1));
  return copy;
}

test('逐项删除必需字段或替换类型时契约失败（政策清单、详情、登录、me）', async () => {
  const mock = createMock();
  const cases = [
    ['POST', '/api/v1/auth/login', mock.credentials, require('./cases/platform.json').routes[1].response],
    ['GET', '/api/v1/me', undefined, require('./cases/platform.json').routes[2].response],
    ['GET', '/api/apps/policy/items', undefined, require('./cases/policy.json').routes[0].response],
    ['GET', '/api/apps/policy/items/PI-03', undefined, require('./cases/policy.json').routes[1].response],
  ];
  for (const [method, path, body, response] of cases) {
    const actual = await mock.request(method, path, body);
    verify(actual, { response }, models);
    let checked = 0;
    for (const field of requiredPaths(response)) {
      const removed = mutate(actual.body, field, (parent, key) => { delete parent[key]; });
      if (!removed) continue;
      assert.throws(() => verify({ status: 200, body: removed }, { response }, models), undefined, `${path} 删除 ${field.join('.')}`);
      const retyped = mutate(actual.body, field, (parent, key) => { parent[key] = parent[key] !== null && typeof parent[key] === 'object' ? 'wrong-type' : { wrong: 'type' }; });
      assert.throws(() => verify({ status: 200, body: retyped }, { response }, models), undefined, `${path} 改类型 ${field.join('.')}`);
      checked++;
    }
    assert.ok(checked > 3, path);
  }
  const items = (await mock.request('GET', '/api/apps/policy/items')).body;
  for (const key of ['docNo', 'docTitle', 'docState']) {
    const broken = structuredClone(items);
    broken.items.forEach(item => { delete item[key]; });
    assert.throws(() => verify({ status: 200, body: broken }, require('./cases/policy.json').routes[0], models), new RegExp(key));
  }
  const noValue = structuredClone(items);
  noValue.items.forEach(item => item.conditions.forEach(condition => { delete condition.v; }));
  assert.throws(() => verify({ status: 200, body: noValue }, require('./cases/policy.json').routes[0], models), /\.v/);
  const login = (await mock.request('POST', '/api/v1/auth/login', mock.credentials)).body;
  for (const key of ['role', 'grants']) {
    const broken = structuredClone(login);
    delete broken[key];
    assert.throws(() => verify({ status: 200, body: broken }, require('./cases/platform.json').routes[1], models), new RegExp(key));
  }
});
