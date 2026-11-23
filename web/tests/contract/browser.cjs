const assert = require('node:assert/strict');
const { test } = require('node:test');
const { chromium } = require('playwright');
const { join } = require('node:path');
const { pathToFileURL } = require('node:url');

test('Chromium 空存储：HTTP 登录、mock 知识库、刷新、HTTP 退出', { timeout: 60_000 }, async t => {
  const browser = await chromium.launch(
    process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : undefined,
  );
  t.after(() => browser.close());
  const context = await browser.newContext({ colorScheme: 'light' });
  const page = await context.newPage();
  const remote = 'https://contract.invalid';
  const credentials = { username: 'contract.leader', password: 'sample-pw' };
  const user = { id: 'remote-leader', username: credentials.username, name: '契约测试领导', role: 'leader' };
  const me = { user, role: { id: 'leader', name: '审签领导' }, grants: { kb: ['view'] } };
  const requests = [];
  let signedIn = false;
  await context.route(remote + '/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push([request.method(), path]);
    let json = {};
    let status = 200;
    if (path === '/api/v1/auth/login') {
      signedIn = JSON.stringify(request.postDataJSON()) === JSON.stringify(credentials);
      json = signedIn ? me : { error: { code: 'BAD_CREDENTIALS', message: '登录失败', details: {} } };
      status = signedIn ? 200 : 401;
    } else if (path === '/api/v1/auth/session') {
      json = { user: signedIn ? user : null };
    } else if (path === '/api/v1/me') {
      json = me;
    } else if (path === '/api/v1/auth/logout') {
      signedIn = false;
      json = { ok: true };
    } else {
      json = { items: [] };
    }
    await route.fulfill({ status, json });
  });
  await context.addInitScript(({ remote }) => {
    Object.defineProperty(window, 'JK_CONFIG', {
      set(config) {
        config.api = { ...config.api, mode: 'mock', baseUrl: remote, modules: { platform: 'http', kb: 'mock' } };
        Object.defineProperty(window, 'JK_CONFIG', { value: config, writable: true, configurable: true });
      },
      configurable: true,
    });
  }, { remote });
  await page.goto(pathToFileURL(join(__dirname, '../../index.html')).href);
  const login = page.getByRole('heading', { name: '登录', exact: true });
  await login.waitFor();
  const kbState = () => page.evaluate(async () => ({
    username: JKAuth.user()?.username ?? null,
    result: await JKApi.kb.spaces().then(({ items }) => items.length, error => error.code),
  }));
  assert.deepEqual(await kbState(), { username: null, result: 'UNAUTHENTICATED' });
  await page.locator('[data-op="login.user"]').fill(credentials.username);
  await page.locator('[data-op="login.pass"]').fill(credentials.password);
  await page.locator('[data-op="login.go"]').click();
  await page.locator('[data-op="shell.me"]').waitFor();
  const afterLogin = await kbState();
  assert.notEqual(afterLogin.username, credentials.username);
  assert.ok(afterLogin.username && afterLogin.result > 0);
  assert.equal(await page.evaluate(value => JSON.stringify(JKAPI.state()).includes(value)
    || Object.values(localStorage).some(item => item.includes(value)), credentials.password), false);

  await page.reload();
  await page.locator('[data-op="shell.me"]').waitFor();
  assert.deepEqual(await kbState(), afterLogin);
  await page.locator('[data-op="shell.me"]').click();
  await page.getByText('退出登录', { exact: true }).click();
  await login.waitFor();
  assert.deepEqual(await kbState(), { username: null, result: 'UNAUTHENTICATED' });
  assert.equal(signedIn, false);
  assert.equal(requests.filter(([, path]) => path === '/api/v1/auth/login').length, 1);
  assert.equal(requests.filter(([, path]) => path === '/api/v1/auth/logout').length, 1);
  assert.ok(requests.every(([, path]) => !path.startsWith('/api/v1/kb/')));
});
