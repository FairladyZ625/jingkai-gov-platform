const http = require('node:http');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { expect, test } = require('@playwright/test');

const web = path.resolve(__dirname, '..');
const username = 't27-browser-test';
const password = 'local-test-password';
const user = { id: 'TEST-T27', name: '测试用户', username };
const profile = { user, role: { name: '经办人员' }, grants: { '*': ['view', 'operate'] } };
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png' };
const error = (code, message, details = {}) => ({ error: { code, message, details } });
const forbidden = error('FORBIDDEN', '无权访问', { app: 'kb', need: 'view' });

let server;
let origin;

function json(response, status, data, headers = {}) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...headers });
  response.end(JSON.stringify(data));
}

async function handle(request, response) {
  const { pathname } = new URL(request.url, 'http://127.0.0.1');
  const authenticated = request.headers.cookie?.includes('t27_test_session=active');
  if (pathname === '/api/v1/auth/session') return json(response, 200, { user: authenticated ? user : null });
  if (pathname === '/api/v1/auth/login') {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const credentials = JSON.parse(Buffer.concat(chunks));
    if (credentials.username !== username || credentials.password !== password) {
      return json(response, 401, error('BAD_CREDENTIALS', '账号或密码不正确'));
    }
    return json(response, 200, profile, { 'Set-Cookie': 't27_test_session=active; Path=/; HttpOnly; SameSite=Lax' });
  }
  if (pathname.startsWith('/api/v1/')) {
    if (!authenticated) return json(response, 401, error('UNAUTHENTICATED', '请登录'));
    if (pathname === '/api/v1/me') return json(response, 200, profile);
    if (pathname === '/api/v1/models') return json(response, 200, { items: [], current: 'auto' });
    if (pathname === '/api/v1/conversations') return json(response, 200, { item: { id: 'C-T27' } });
    if (pathname === '/api/v1/conversations/C-T27/messages') {
      if (request.headers.accept?.includes('text/event-stream') !== true) return json(response, 422, {});
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const data = JSON.parse(Buffer.concat(chunks));
      if (data.text === '兼容 JSON') {
        return json(response, 200, { reply: { content: '兼容响应成功', model: '测试模型' } });
      }
      response.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8' });
      response.flushHeaders();
      response.write(': keepalive\r\n\r\nevent: meta\r\ndata: {"model":"测试模型"}\r\n\r\n');
      const first = Buffer.from('event: delta\r\ndata: {"text":"第一段"}\r\n\r\n');
      const split = first.indexOf(Buffer.from('第')) + 1;
      response.write(first.subarray(0, split));
      setTimeout(() => response.write(first.subarray(split)), 60);
      if (data.text === '中途断流') return setTimeout(() => response.end(), 175);
      setTimeout(() => response.write('event: card\ndata: {"type":"kb-hits",\ndata: "hits":[{"title":"演示政策原文"}]}\n\n'), 350);
      return setTimeout(() => response.end('event: delta\ndata: {"text":"第二段"}\n\nevent: done\ndata: {"messageId":"M-T27"}\n\n'), 1000);
    }
    if (pathname === '/api/v1/kb/search') return json(response, 200, { hits: [], total: 0, terms: [], facets: {} });
    if (pathname === '/api/v1/kb/ask') return json(response, 200, { answer: '没找到能够作答的原文。', confidence: 'none', citations: [], notFound: true });
    if (pathname === '/api/v1/kb/stats') return json(response, 200, { docs: 0, chunks: 0, recent: [], status: {} });
    return json(response, 200, { items: [] });
  }
  const file = path.resolve(web, '.' + (pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(web + path.sep)) return json(response, 404, {});
  try {
    const data = await fs.readFile(file);
    response.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' });
    response.end(data);
  } catch {
    json(response, 404, {});
  }
}

test.beforeAll(async () => {
  server = http.createServer((request, response) => {
    handle(request, response).catch(() => {
      if (!response.headersSent) json(response, 500, {});
      else response.destroy();
    });
  });
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
});
test.afterAll(async () => {
  server.closeAllConnections();
  await new Promise((resolve) => server.close(resolve));
});

async function signIn(page, name = username, pass = password) {
  await page.getByLabel('账号', { exact: true }).fill(name);
  await page.getByLabel('密码', { exact: true }).fill(pass);
  await page.getByRole('button', { name: '登录', exact: true }).click();
}

async function openWorkspace(page) {
  await page.goto(origin);
  await signIn(page);
  await expect(page.locator('.hello')).toContainText(user.name);
}

async function send(page, message) {
  const input = page.locator('#chatcol textarea');
  await input.fill(message);
  await input.press('Enter');
}

test('HTTP 正式配置提交凭证，错误密码显示原位提示', async ({ page }) => {
  await page.goto(origin);
  await expect(page.getByText('一键选账号', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => JK_CONFIG.api.modules)).toEqual({
    platform: 'http', kb: 'http', policy: 'http', enterprise: 'http', meeting: 'http', document: 'http',
  });
  await signIn(page, username, 'incorrect');
  await expect(page.getByRole('alert')).toHaveText('用户名或密码错误');
  await expect(page.getByLabel('账号', { exact: true })).toHaveValue(username);
  await signIn(page);
  await expect(page.locator('.hello')).toContainText(user.name);
  await page.reload();
  await expect(page.locator('.hello')).toContainText(user.name);
});

test('显式 HTTP 演示配置保留一键选账号', async ({ page }) => {
  await page.route('**/config/app.config.js', async (route) => {
    const response = await route.fetch();
    const account = { username, password, name: user.name, role: '经办人员' };
    const override = `\nJK_CONFIG.demoMode = true; JK_CONFIG.demoAccounts = ${JSON.stringify([account])};`;
    await route.fulfill({ response, body: (await response.text()) + override });
  });
  await page.goto(origin);
  await expect(page.getByText('一键选账号', { exact: true })).toBeVisible();
  await page.locator('[data-u="' + username + '"]').click();
  await expect(page.locator('.hello')).toContainText(user.name);
});

test('file:// 断网可一键选择演示账号', async ({ page, context }) => {
  await context.setOffline(true);
  await page.goto(pathToFileURL(path.join(web, 'index.html')).href);
  await expect(page.getByText('一键选账号', { exact: true })).toBeVisible();
  await page.locator('[data-u="wangmin"]').click();
  await expect(page.locator('.hello')).toContainText('王敏');
});

test('401 返回登录，重新认证后恢复原对话与知识库面板', async ({ page }) => {
  await openWorkspace(page);
  await send(page, '兼容 JSON');
  await expect(page.locator('.msg.ai .txt')).toHaveText('兼容响应成功');
  await page.locator('#side-sc [data-app="kb"]').click();
  await expect(page.locator('.pview.on[data-view="kb"]')).toBeVisible();
  await page.route('**/api/v1/kb/search', (route) => route.fulfill({
    status: 401, json: error('UNAUTHENTICATED', '会话过期'),
  }), { times: 1 });
  await page.evaluate(() => JKApi.kb.search({ q: '政策' }).catch(() => null));
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveText('登录已失效，请重新登录');
  await signIn(page);
  await expect(page.locator('.pview.on[data-view="kb"]')).toBeVisible();
  await expect(page.locator('.msg.ai .txt')).toHaveText('兼容响应成功');
});

test('403 提示后端给出的应用与权限且保持当前工作台', async ({ page }) => {
  await openWorkspace(page);
  await page.route('**/api/v1/kb/search', (route) => route.fulfill({ status: 403, json: forbidden }));
  await page.evaluate(() => JKApi.kb.search({ q: '政策' }).catch(() => null));
  await expect(page.locator('.toast').last()).toHaveText('缺少应用「kb」的查看权限');
  await expect(page.locator('#chatcol textarea')).toBeVisible();
});

for (const failure of ['断网', '503']) {
  test(failure + ' 自动重试三次，耗尽后保留页面与可读提示', async ({ page }) => {
    await openWorkspace(page);
    let attempts = 0;
    await page.route('**/api/v1/kb/search', (route) => {
      attempts++;
      return failure === '断网' ? route.abort('internetdisconnected') : route.fulfill({ status: 503, json: {} });
    });
    const request = page.evaluate(() => JKApi.kb.search({ q: '政策' }).catch(({ message }) => message));
    await expect(page.locator('.toast').filter({ hasText: '正在重试（1/3）' })).toBeVisible();
    const message = failure === '断网' ? '网络不可用，请检查连接' : '服务暂时不可用，请稍后重试';
    expect(await request).toBe(message);
    expect(attempts).toBe(4);
    await expect(page.locator('.toast').last()).toHaveText(message);
    await expect(page.locator('#chatcol textarea')).toBeVisible();
  });
}

test('知识库读请求在重试后成功，写操作遇 503 不会被重放', async ({ page }) => {
  await openWorkspace(page);
  let reads = 0;
  let writes = 0;
  await page.route('**/api/v1/kb/ask', (route) => ++reads < 3 ?
    route.fulfill({ status: 503, json: {} }) : route.continue());
  await page.route('**/api/v1/kb/import', (route) => {
    writes++;
    return route.fulfill({ status: 503, json: {} });
  });
  const result = await page.evaluate(() => JKApi.kb.ask({ q: '未收录的政策' }));
  expect(result).toMatchObject({ notFound: true, citations: [], answer: '没找到能够作答的原文。' });
  expect(reads).toBe(3);
  await page.evaluate(() => JKApi.kb.importNow({ text: '测试' }).catch(() => null));
  expect(writes).toBe(1);
});

test('SSE 文本与卡片在 done 前出现', async ({ page }) => {
  await openWorkspace(page);
  await send(page, '查询政策');
  const text = page.locator('.msg.ai .txt');
  await expect(text).toHaveText('第一段');
  await expect(page.locator('[data-reply-card="kb-hits"]')).toContainText('演示政策原文');
  await expect(text).toHaveText('第一段');
  await expect(text).toHaveText('第一段第二段');
});

test('SSE 提前结束保留已收到的文本和错误提示', async ({ page }) => {
  await openWorkspace(page);
  await send(page, '中途断流');
  await expect(page.locator('.msg.ai .txt')).toContainText('第一段');
  await expect(page.locator('.msg.ai .txt')).toContainText('对话连接中断');
});

if (process.env.T27_SCREENSHOT_DIR) {
  for (const width of [1440, 1280]) {
    test('浅色 HTTP 页面截图 ' + width, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(origin);
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
      await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: path.join(process.env.T27_SCREENSHOT_DIR, 't27-' + width + '.png') });
    });
  }
}

if (process.env.T27_REAL_BASE) {
  test('真实本地实例登录和知识库检索', async ({ page }) => {
    await page.goto(process.env.T27_REAL_BASE);
    await signIn(page, process.env.CONTRACT_USERNAME, process.env.CONTRACT_PASSWORD);
    await expect(page.locator('.hello')).not.toBeEmpty();
    const result = await page.evaluate(() => JKApi.kb.search({ q: '数据券', limit: 3 }));
    expect(Array.isArray(result.hits)).toBe(true);
  });
}
