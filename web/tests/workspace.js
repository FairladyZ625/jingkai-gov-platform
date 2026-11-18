const { expect, test: base } = require('@playwright/test');

const root = 'http://localhost:8080/';
const subpath = 'http://127.0.0.1:8081/v4/';

const test = base.extend({
  browserErrors: [async ({ page }, use) => {
    const issues = [];
    page.on('console', message => {
      if (message.type() === 'error' ||
          (message.type() === 'warning' && message.text().startsWith('demo '))) {
        issues.push(message.text());
      }
    });
    page.on('pageerror', error => issues.push(error.message));
    page.on('response', response => {
      if (response.status() >= 400) issues.push(response.status() + ' ' + response.url());
    });
    page.on('requestfailed', request => {
      issues.push(request.failure().errorText + ' ' + request.url());
    });
    await use(issues);
    expect(issues, '控制台、页面与资源请求错误').toEqual([]);
  }, { auto: true }],
});

async function openLogin(page, url) {
  await page.goto(url);
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  expect(await page.evaluate(() => JK_CONFIG.api.mode)).toBe('mock');
}

async function login(page) {
  await page.locator('[data-u="wangmin"]').click();
  await expect(page.locator('.hello')).toContainText('王敏');
}

module.exports = { expect, test, root, subpath, openLogin, login };
