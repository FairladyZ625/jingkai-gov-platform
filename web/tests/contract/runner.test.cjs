const assert = require('node:assert/strict');
const { readFileSync, existsSync } = require('node:fs');
const { createServer } = require('node:http');
const { join } = require('node:path');
const test = require('node:test');
const { spawn } = require('node:child_process');
const { main, modules } = require('./run.cjs');
const { createMock } = require('./mock.cjs');
const { verify } = require('./assertions.cjs');

test('八个模块的清单与接口规范 §7 的 117 个方法和路径逐项相等', () => {
  const root = join(__dirname, '../../..');
  const published = join(root, 'docs/接口规范.md');
  const file = existsSync(published) ? published : join(root, 'prototype/v4/接口规范.md');
  const text = readFileSync(file, 'utf8').split('## 7. 适配层路径全量清单')[1];
  const sections = [...text.matchAll(/### [^\n]*\x60api\/(\w+)\.js\x60[^\n]*\n([\s\S]*?)(?=\n### |$)/g)];
  assert.deepEqual(sections.map(section => section[1]).sort(), [...modules].sort());
  let total = 0;
  for (const [, module, section] of sections) {
    const { routes } = require('./cases/' + module + '.json');
    const expected = [...section.matchAll(/^\| (GET|POST|PUT|PATCH|DELETE) \| \x60([^\n]+)\x60 \|$/gm)]
      .map(([, method, path]) => method + ' ' + path);
    assert.deepEqual(routes.map(({ method, path }) => method + ' ' + path).sort(), expected.sort(), module);
    total += routes.length;
  }
  assert.equal(total, 117);
});

test('响应断言拒绝缺失字段、错误类型和扁平错误响应', () => {
  const example = { response: { items: [{ id: 'string' }], total: 'number' } };
  assert.throws(() => verify({ status: 200, body: { items: [{}], total: 1 } }, example, {}), /缺少必需字段/);
  assert.throws(() => verify({ status: 200, body: { items: [{ id: 1 }], total: 1 } }, example, {}), /应为 string/);
  const contract = { status: 404, error: 'NOT_FOUND' };
  const error = { code: 'NOT_FOUND', message: '不存在', details: {} };
  verify({ status: 404, body: { error } }, contract, {});
  assert.throws(() => verify({ status: 404, body: error }, contract, {}), /缺少必需字段/);
  assert.throws(() => verify({ status: 404, body: { error: { ...error, details: [] } } }, contract, {}), /应为 object/);
});

async function listen(server) {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return 'http://127.0.0.1:' + server.address().port;
}

test('真实 HTTP 传输只执行所选 platform 用例，并转发会话 Cookie', async t => {
  const mock = createMock();
  const requests = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : undefined;
    requests.push([req.method, req.url, req.headers.cookie]);
    const response = await mock.request(req.method, req.url, body);
    if (req.url === '/api/v1/auth/login' && response.status === 200) res.setHeader('Set-Cookie', 'contract-session=example; Path=/; HttpOnly');
    res.writeHead(response.status, { 'Content-Type': 'application/json' }).end(JSON.stringify(response.body));
  });
  const base = await listen(server);
  t.after(() => server.close());

  const lines = [];
  const errors = [];
  const status = await main(['--base', base, '--module', 'platform'], {
    CONTRACT_USERNAME: mock.credentials.username,
    CONTRACT_PASSWORD: mock.credentials.password,
  }, line => lines.push(line), line => errors.push(line));
  assert.equal(status, 0, errors.join('\n'));
  assert.deepEqual(lines, ['契约模式：HTTP；模块：platform', 'platform: 37/37，错误样例 1/1', '合计 37/37，错误样例 1/1']);
  assert.equal(requests.length, 38);
  assert.equal(requests.find(([, url]) => url === '/api/v1/me')[2], 'contract-session=example');
  assert.ok(requests.every(([, url]) => url.startsWith('/api/v1/')));
});

test('连接挂起时 CLI 在 30 秒内失败并提示后端地址', { timeout: 29_000 }, async t => {
  const server = createServer(() => {});
  const base = await listen(server);
  t.after(() => {
    server.closeAllConnections();
    server.close();
  });

  const child = spawn(process.execPath, [join(__dirname, 'run.cjs'), '--base', base, '--module', 'platform'], {
    env: { ...process.env, CONTRACT_USERNAME: '', CONTRACT_PASSWORD: '' },
  });
  t.after(() => child.kill());
  let stderr = '';
  child.stderr.setEncoding('utf8').on('data', chunk => { stderr += chunk; });
  const started = Date.now();
  const code = await new Promise((resolve, reject) => child.once('error', reject).once('close', resolve));
  assert.notEqual(code, 0);
  assert.ok(Date.now() - started < 30_000);
  assert.ok(stderr.includes('无法访问后端 ' + base));
});

test('CLI 拒绝未知模块和含凭据的 base URL', async () => {
  await assert.rejects(main(['--module', 'invalid']), /未知模块/);
  await assert.rejects(main(['--module', '']), /未知模块/);
  await assert.rejects(main(['--base', 'https://sample:example@example.com']), /不含凭据/);
});
