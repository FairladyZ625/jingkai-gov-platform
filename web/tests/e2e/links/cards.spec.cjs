const { join } = require('node:path');
const { expect, test } = require('@playwright/test');

test('对话 SSE 卡片打开四个业务应用的具体对象', async ({ page }) => {
  await page.goto('/');
  const apps = ['policy', 'enterprise', 'meeting', 'document'];
  expect(await page.evaluate(ids => ids.map(id => JK_CONFIG.api.modules[id]), apps)).toEqual(apps.map(() => 'http'));
  await page.getByLabel('账号', { exact: true }).fill(process.env.T41_USERNAME);
  await page.getByLabel('密码', { exact: true }).fill(process.env.T41_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.hello')).toBeVisible();

  const policyList = await page.request.get('/api/apps/policy/items');
  expect(policyList.ok()).toBeTruthy();
  const [policy] = (await policyList.json()).items;
  const companyList = await page.request.get('/api/apps/enterprise/companies');
  expect(companyList.ok()).toBeTruthy();
  const company = (await companyList.json()).items.find(item => item.id === 'E001');
  expect(company).toBeDefined();
  const created = await page.request.post('/api/apps/meeting/meetings', {
    multipart: { title: '对话卡片测试会议', source: 'demo' },
  });
  expect(created.status()).toBe(201);
  const { item: meeting } = await created.json();

  // 固定对话模型输出。登录、会话创建及卡片打开后的业务请求均使用隔离实例。
  const cards = [
    { type: 'policy-items', deepLink: { app: 'policy', params: { tab: 'library', itemId: policy.id } } },
    { type: 'enterprise-brief', deepLink: { app: 'enterprise', params: { entId: company.id } } },
    { type: 'meeting-list', deepLink: { app: 'meeting', params: { meetingId: meeting.id, process: false } } },
    { type: 'doc-start', deepLink: { app: 'document', params: { templateId: 'T10', autogen: true } } },
    { type: 'app-suggest', deepLink: { app: '未注册应用', params: {} } },
  ];
  await page.route('**/api/v1/conversations/*/messages', route => {
    expect(route.request().postDataJSON()).toMatchObject({ stream: true });
    const event = (type, value) => `event: ${type}\ndata: ${JSON.stringify(value)}\n\n`;
    return route.fulfill({
      contentType: 'text/event-stream',
      body: event('delta', { text: '公开示例卡片' }) + cards.map(card => event('card', card)).join('') + event('done', {}),
    });
  });
  const composer = page.locator('#chatcol textarea');
  await composer.fill('请列出示例业务对象');
  await composer.press('Enter');

  const button = type => page.locator(`[data-reply-card="${type}"]`).getByRole('button', { name: '打开应用' });
  const panel = app => page.locator(`.pview.on[data-view="${app}"]`);
  await expect(page.locator('[data-reply-card]')).toHaveCount(cards.length);
  await expect(button('app-suggest')).toHaveCount(0);

  await button('enterprise-brief').click();
  await expect(panel('enterprise').locator('[data-op="enterprise.profile"]')).toContainText(company.name);
  if (process.env.T41_SCREENSHOT_DIR) {
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    for (const width of [1440, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      await page.screenshot({ path: join(process.env.T41_SCREENSHOT_DIR, `cards-${width}.png`) });
    }
  }
  await button('meeting-list').click();
  await expect(panel('meeting').getByText(meeting.title, { exact: true })).toBeVisible();
  await button('doc-start').click();
  await expect(panel('document').locator('#ds .q')).toContainText('企业诉求答复意见');
  await expect(panel('document').locator('[data-op="document.gen"]')).toBeVisible();
  await button('policy-items').click();
  await expect(page.locator('.drawer').getByText(policy.title, { exact: true })).toBeVisible();
});
