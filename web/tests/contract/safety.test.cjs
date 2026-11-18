// HA 评审 review-dispatch_58a7e858 的回归：写入保护、明文凭据、知识库恢复、混合会话、必需字段。
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { execFile } = require('node:child_process');
const { join } = require('node:path');
const { promisify } = require('node:util');
const test = require('node:test');
const { main } = require('./run.cjs');
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

function mockBackend() {
  const mock = createMock();
  return {
    mock,
    handler: async (req, body) => {
      const response = req.url === '/api/v1/me' && !req.headers.cookie
        ? { status: 401, body: { error: { code: 'UNAUTHENTICATED', message: '需要登录', details: {} } } }
        : await mock.request(req.method, req.url, body);
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
  assert.ok(lines.some(line => /^platform: \d+\/\d+，错误样例 1\/1（只读模式跳过 \d+ 条写入或依赖用例）$/.test(line)), lines.join('\n'));
  assert.deepEqual(requests.filter(({ method, url }) => method !== 'GET' && url !== '/api/v1/auth/login'), []);
  assert.ok(requests.every(({ url }) => !url.split('?')[0].endsWith('/export')));
  assert.ok(requests.some(({ url }) => url === '/api/apps/policy/items'));
});

test('登录返回 401 时立即中止，含 --allow-writes 也不发业务写请求', async t => {
  for (const args of [[], ['--allow-writes']]) {
    const { base, requests } = await stubServer(t, async () => ({
      status: 401, body: { error: { code: 'BAD_CREDENTIALS', message: '账号或密码不正确', details: {} } },
    }));
    const env = { CONTRACT_USERNAME: 'sample', CONTRACT_PASSWORD: 'example', CONTRACT_RESETTABLE_TARGET: base };
    await assert.rejects(main(['--base', base, ...args], env, () => {}, () => {}), /登录失败（HTTP 401），已中止/);
    assert.deepEqual(requests, [{ method: 'POST', url: '/api/v1/auth/login' }]);
  }
});

test('--allow-writes 必须先确认目标可重置，否则不发任何请求', async t => {
  const { base, requests } = await stubServer(t, async () => ({ status: 200, body: {} }));
  const env = { CONTRACT_USERNAME: 'sample', CONTRACT_PASSWORD: 'example' };
  await assert.rejects(main(['--base', base, '--allow-writes'], env, () => {}, () => {}), /CONTRACT_RESETTABLE_TARGET=/);
  await assert.rejects(main(['--base', base + '/another-instance', '--allow-writes'], { ...env, CONTRACT_RESETTABLE_TARGET: base }, () => {}, () => {}), /CONTRACT_RESETTABLE_TARGET=/);
  await assert.rejects(main(['--allow-writes'], env, () => {}, () => {}), /只用于 HTTP 模式/);
  assert.deepEqual(requests, []);
});

test('Cookie 会话缺失或重置预检未确认时中止业务写入', async t => {
  const { mock, handler } = mockBackend();
  for (const validSession of [false, true]) {
    const { base, requests } = await stubServer(t, async (req, body) => {
      if (!validSession && req.url === '/api/v1/auth/session') return { status: 200, body: { user: null } };
      if (req.url === '/api/v1/demo/reset') return { status: 200, body: { ok: false } };
      return handler(req, body);
    });
    const env = {
      CONTRACT_USERNAME: mock.credentials.username, CONTRACT_PASSWORD: mock.credentials.password, CONTRACT_RESETTABLE_TARGET: base,
    };
    await assert.rejects(main(['--base', base, '--module', 'platform', '--allow-writes'], env, () => {}, () => {}),
      validSession ? /重置预检失败/ : /user 应为对象/);
    assert.deepEqual(requests.map(({ url }) => url), [
      '/api/v1/auth/login', '/api/v1/auth/session', ...(validSession ? ['/api/v1/demo/reset'] : []),
    ]);
  }
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

test('登录重定向不会转发凭据或会话 Cookie', async t => {
  const receiver = await stubServer(t, async () => ({ status: 200, body: {} }));
  const redirect = createServer((req, res) => {
    req.resume();
    res.writeHead(307, { Location: receiver.base + '/login', 'Content-Type': 'application/json' }).end('{}');
  });
  await new Promise(resolve => redirect.listen(0, '127.0.0.1', resolve));
  t.after(() => redirect.close());
  const base = 'http://127.0.0.1:' + redirect.address().port;
  const env = { CONTRACT_USERNAME: 'sample', CONTRACT_PASSWORD: 'synthetic-value' };
  await assert.rejects(main(['--base', base, '--module', 'platform'], env, () => {}, () => {}), /登录失败（HTTP 307）/);
  assert.deepEqual(receiver.requests, []);
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

test('知识库 HTTP 模式按新资料 ID 验证删除和恢复，回读失败后仍清理', async t => {
  for (const wrongReadback of [false, true]) {
    const { mock, handler } = mockBackend();
    let importedId;
    let restored = false;
    const { base, requests } = await stubServer(t, async (req, body) => {
      const result = await handler(req, body);
      if (req.method === 'POST' && req.url === '/api/v1/kb/import') {
        importedId = result.body.docs[0].id;
      }
      if (req.url === '/api/v1/kb/docs/' + importedId + '/restore') restored = true;
      if (wrongReadback && restored && req.method === 'GET' && req.url === '/api/v1/kb/docs/' + importedId) {
        result.body.item.id = 'mismatched-doc';
      }
      return result;
    });
    const env = {
      CONTRACT_USERNAME: mock.credentials.username, CONTRACT_PASSWORD: mock.credentials.password,
      CONTRACT_RESETTABLE_TARGET: base, CONTRACT_KB_DOC_ID: 'existing-readonly-fixture',
    };
    const errors = [];
    const code = await main(['--base', base, '--module', 'kb', '--allow-writes'], env, () => {}, error => errors.push(error));
    assert.equal(code, wrongReadback ? 1 : 0, errors.join('\n'));
    if (wrongReadback) assert.ok(errors.some(error => error.includes('回读到的资料 ID')));
    assert.ok(importedId && importedId !== env.CONTRACT_KB_DOC_ID);
    const path = '/api/v1/kb/docs/' + importedId;
    const actions = requests.filter(({ url }) => url === path || url === path + '/restore');
    assert.deepEqual(actions.map(({ method, url }) => [method, url]), [
      ['GET', path], ['PATCH', path], ['DELETE', path], ['GET', path], ['POST', path + '/restore'], ['GET', path],
    ]);
    assert.equal(requests.at(-1).url, '/api/v1/demo/reset');
    assert.equal((await mock.request('GET', path)).status, 401);
    await mock.request('POST', '/api/v1/auth/login', mock.credentials);
    assert.equal((await mock.request('GET', path)).status, 404);
  }
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

test('混合模式登录期间发出的过期 401 不清除刚建立的演示会话', async () => {
  let finishLogin;
  let finishRead;
  const context = createContext({
    fetch: url => new Promise(resolve => {
      if (url.endsWith('/auth/login')) finishLogin = resolve;
      else finishRead = resolve;
    }),
    Response, AbortController,
  }, ctx => {
    ctx.JK_CONFIG.api = { mode: 'mock', baseUrl: 'https://demo.example.com', modules: { platform: 'http' } };
  });
  const login = context.JKHttp.post('/api/v1/auth/login', { username: 'remote.leader', password: 'synthetic-value' });
  const stale = context.JKHttp.get('/api/v1/models');
  finishLogin(Response.json({ user: { username: 'remote.leader', role: 'leader' } }));
  await login;
  finishRead(Response.json({}, { status: 401 }));
  await assert.rejects(stale, error => error.status === 401);
  assert.equal(context.JKAuth.user().role, 'leader');
});

function requiredPaths(schema, prefix = []) {
  // 列出 schema 中每个必需字段的路径（数组取第 0 项），供逐项删除。
  if (typeof schema === 'string') {
    if (schema.startsWith('@')) return requiredPaths(models[schema.slice(1)], prefix);
    return [];
  }
  if (Array.isArray(schema)) return schema.length === 1 ? requiredPaths(schema[0], [...prefix, 0]) : [];
  return Object.entries(schema).filter(([key]) => !key.endsWith('?') && key !== '$values')
    .flatMap(([key, field]) => [[...prefix, key], ...requiredPaths(field, [...prefix, key])]);
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
      const retyped = mutate(actual.body, field, (parent, key) => {
        parent[key] = parent[key] !== null && typeof parent[key] === 'object' ? 17 : { wrong: 'type' };
      });
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

test('CLI 对政策与登录的逐项删字段和改类型返回非零', async t => {
  const { mock, handler } = mockBackend();
  let mutation;
  const { base } = await stubServer(t, async (req, body) => {
    const response = await handler(req, body);
    if (req.url === mutation.path && response.status === 200) {
      response.body = mutate(response.body, mutation.field, (parent, key) => {
        if (mutation.remove) delete parent[key];
        else parent[key] = parent[key] !== null && typeof parent[key] === 'object' ? 7 : { invalid: true };
      });
    }
    return response;
  });
  const env = { ...process.env, CONTRACT_USERNAME: mock.credentials.username, CONTRACT_PASSWORD: mock.credentials.password };
  const run = promisify(execFile);
  const cases = [
    { module: 'platform', path: '/api/v1/auth/login', fields: [['role'], ['grants']] },
    { module: 'policy', path: '/api/apps/policy/items', fields: [
      ['items', 0, 'docNo'], ['items', 0, 'docTitle'], ['items', 0, 'docState'], ['items', 0, 'conditions', 0, 'v'],
    ] },
  ];
  for (const { module, path, fields } of cases) {
    for (const field of fields) {
      for (const remove of [true, false]) {
        mutation = { path, field, remove };
        await assert.rejects(run(process.execPath, [join(__dirname, 'run.cjs'), '--base', base, '--module', module], { env }),
          error => error.code === 1 && error.stderr.includes('.' + field.at(-1)), field.join('.'));
      }
    }
  }
});
