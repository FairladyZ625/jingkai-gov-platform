const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { expect, test, root, subpath, openLogin, login } = require('./workspace');

const applications = ['policy', 'enterprise', 'meeting', 'document'];

async function openAppsAndChat(page) {
  for (const id of applications) {
    await page.locator('[data-op="nav.' + id + '"]').click();
    await expect(page.locator('.pview.on[data-view="' + id + '"] .app-root')).not.toBeEmpty();
  }
  const composer = page.locator('#chatcol textarea');
  const prompt = '你好，请跟我打个招呼并介绍一下自己';
  await composer.fill(prompt);
  await composer.press('Enter');
  await expect(page.locator('#chatcol .msg.user .bubble')).toHaveText(prompt);
  await expect(page.locator('#chatcol .msg.ai .txt')).toContainText('我是经开区共享智能体工作站的助手');
}

for (const [name, url] of [['站点根路径', root], ['部署子路径 /v4/', subpath]]) {
  test(name + '登录、打开四个业务应用并取得模拟回复', async ({ page }) => {
    const requests = [];
    page.on('request', request => requests.push(request.url()));
    await openLogin(page, url);
    await login(page);
    const icon = page.locator('link[rel="icon"]');
    const iconUrl = await icon.evaluate(link => link.href);
    expect(iconUrl).toBe(new URL('assets/favicon.png', url).href);
    expect((await page.request.get(iconUrl)).ok()).toBe(true);

    const width = page.viewportSize().width;
    if (process.env.V4_SCREENSHOT_DIR && url === root) {
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
      await page.screenshot({ path: path.join(process.env.V4_SCREENSHOT_DIR, width + '.png') });
    }

    await openAppsAndChat(page);
    const plan = page.locator('#btn-plan');
    if (await plan.count()) expect(await plan.evaluate(link => link.href)).toBe(new URL('plan.html', url).href);
    expect((await page.request.get(new URL('plan.html', url).href)).ok()).toBe(true);
    expect(requests).toEqual(expect.arrayContaining([
      new URL('assets/theme.css', url).href,
      new URL('assets/fonts/Inter-var.woff2', url).href,
      new URL('data/index.js', url).href,
      ...applications.map(id => new URL('apps/' + id + '/app.js', url).href),
    ]));
    expect(requests.filter(request => !request.startsWith(url))).toEqual([]);
  });
}

test('无效口令显示错误，仍可用演示账号继续', async ({ page }) => {
  await openLogin(page, root);
  await page.locator('#lf [name=u]').fill('wangmin');
  await page.locator('#lf [name=p]').fill('invalid-demo-password');
  await page.locator('[data-op="login.go"]').click();
  await expect(page.locator('.login-box .callout')).toContainText(/错误|不正确/);
  await expect(page.locator('#btn-demo')).toHaveCount(0);
  await login(page);
});

test('断网直开文件仍可打开首页和四个应用并取得回复', async ({ page }) => {
  await page.context().setOffline(true);
  const file = pathToFileURL(path.resolve(__dirname, '../index.html')).href;
  await openLogin(page, file);
  await login(page);
  await openAppsAndChat(page);
});

if (process.env.V4_SCREENSHOT_DIR) {
  test.describe('窄屏截图', () => {
    test.use({ viewport: { width: 1280, height: 900 } });
    test('登录后的浅色 1280px 工作台', async ({ page }) => {
      await openLogin(page, root);
      await login(page);
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
      await page.screenshot({ path: path.join(process.env.V4_SCREENSHOT_DIR, '1280.png') });
    });
  });
}
