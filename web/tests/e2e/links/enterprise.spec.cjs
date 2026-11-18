const { randomUUID } = require('node:crypto');
const { expect, test } = require('@playwright/test');

test('企业没有诉求时，跟进页保持为空，非法来源返回 400', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => { JK_CONFIG.api.modules.enterprise = 'http'; });
  await page.getByLabel('账号', { exact: true }).fill(process.env.T41_USERNAME);
  await page.getByLabel('密码', { exact: true }).fill(process.env.T41_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.hello')).toBeVisible();
  const endpoint = '/api/apps/enterprise';
  async function company(short) {
    const response = await page.request.post(endpoint + '/companies', {
      data: { name: short + randomUUID(), short },
    });
    expect(response.status()).toBe(200);
    return (await response.json()).item.id;
  }
  const other = await company('有诉求示例');
  const target = await company('无诉求示例');
  const issues = endpoint + '/issues';
  const valid = await page.request.post(issues, { data: { entId: other, title: '其他企业诉求', from: '政策咨询' } });
  expect(valid.status()).toBe(200);
  const invalid = await page.request.post(issues, { data: { entId: target, title: '不应保存', from: '未定义' } });
  expect(invalid.status()).toBe(400);
  expect((await invalid.json()).error.code).toBe('INVALID_REQUEST');
  await page.evaluate(entId => JKShell.openApp('enterprise', 'issues', { entId }), target);
  await expect(page.getByText('无诉求示例 的诉求', { exact: true })).toBeVisible();
  await expect(page.locator('.ent-iss-l')).toHaveText('暂无诉求');
  await expect(page.locator('[data-op="enterprise.save-issue"]')).toHaveCount(0);
});
