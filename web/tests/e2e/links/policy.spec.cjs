const { expect, test } = require('@playwright/test');

const entId = 'E001'; // 隔离企业台账与政策公开示例画像使用同一编号。
const policy = '/api/apps/policy';
const issues = '/api/apps/enterprise/issues';
const drafts = '/api/apps/document/drafts';
const op = (page, name) => page.locator(`[data-op="${name}"]`);

function responseTo(page, method, path) {
  return page.waitForResponse(r => r.request().method() === method && new URL(r.url()).pathname === path);
}

async function selectItems(page) {
  await page.goto('/');
  await page.evaluate(() => Object.assign(JK_CONFIG.api.modules, { policy: 'http', enterprise: 'http', document: 'http' }));
  await page.getByLabel('账号', { exact: true }).fill(process.env.T41_USERNAME);
  await page.getByLabel('密码', { exact: true }).fill(process.env.T41_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.hello')).toBeVisible();

  const catalog = responseTo(page, 'GET', policy + '/items');
  await op(page, 'nav.policy').click();
  expect((await catalog).status()).toBe(200);
  await op(page, 'policy.sample-' + entId).click();
  const matching = responseTo(page, 'POST', policy + '/match');
  await op(page, 'policy.go').click();
  const matched = await matching;
  expect(matched.status()).toBe(200);
  expect(matched.request().postDataJSON().entId).toBe(entId);

  const first = page.locator('[data-pick]').first();
  const id = await first.getAttribute('data-pick');
  await first.uncheck();
  await first.check();
  await op(page, 'policy.next').click();
  return id;
}

async function generateNotice(page, allowStub) {
  const id = await selectItems(page);
  const path = policy + '/notice';
  if (allowStub) {
    await page.route('**' + path, async route => {
      const upstream = await route.fetch();
      if (upstream.status() === 404 && (await upstream.json()).detail === 'Not Found') {
        await route.fulfill({ json: { text: '公开演示告知单\n请核对申报材料。' } });
      } else {
        await route.fulfill({ response: upstream });
      }
    });
  }
  const generated = responseTo(page, 'POST', path);
  await op(page, 'policy.to-notice').click();
  const response = await generated;
  expect(response.request().postDataJSON()).toMatchObject({ entId, itemIds: expect.arrayContaining([id]) });
  const body = await response.json();
  test.skip(!allowStub && response.status() === 404 && body.detail === 'Not Found', '等待 #127 挂载 POST /api/apps/policy/notice');
  expect(response.status()).toBe(200);
  expect(body.text.trim()).toBeTruthy();
  await expect(op(page, 'policy.notice-text')).toHaveValue(body.text);
  return body.text;
}

for (const allowStub of [false, true]) {
  test(`政策告知单转 T10，编辑正文持久化（${allowStub ? '#127 路由缺失时仅桩告知单' : '完整真实 HTTP'}）`, async ({ page }) => {
    const text = await generateNotice(page, allowStub);
    const edited = text + '\n经办人补充：保留换行及 <材料> 原文。';
    await op(page, 'policy.notice-text').fill(edited);
    await op(page, 'policy.to-doc').click();
    await expect(op(page, 'document.in-ent')).toHaveValue(entId);
    const saving = responseTo(page, 'POST', drafts);
    await op(page, 'document.gen').click();
    const saved = await saving;
    expect(saved.status()).toBe(200);
    expect(saved.request().postDataJSON()).toMatchObject({ templateId: 'T10', extra: [edited] });
    const { item } = await saved.json();
    const read = await page.request.get(drafts + '/' + item.id);
    expect(read.status()).toBe(200);
    expect((await read.json()).item.versions.at(-1).content.paragraphs).toContain(edited);
  });
}

test('政策提示的查看定位本次真实诉求（#127 路由缺失时仅桩告知单）', async ({ page }) => {
  await generateNotice(page, true);
  // 已打开的企业标签页会复用上次加载的列表。
  await page.evaluate(entId => JKShell.openApp('enterprise', 'issues', { entId }), entId);
  await page.evaluate(() => JKShell.openApp('policy'));
  const saving = responseTo(page, 'POST', issues);
  await op(page, 'policy.issue').click();
  const saved = await saving;
  expect(saved.status()).toBe(200);
  const { item } = await saved.json();
  expect(item).toMatchObject({ entId, from: '政策咨询' });
  const reading = page.waitForResponse(r => {
    const url = new URL(r.url());
    return r.request().method() === 'GET' && url.pathname === issues && url.searchParams.get('entId') === entId;
  });
  await page.locator('.toast').getByText('查看', { exact: true }).click();
  const response = await reading;
  expect(response.status()).toBe(200);
  expect((await response.json()).items).toContainEqual(expect.objectContaining(item));
  const selected = op(page, 'enterprise.issue-' + item.id);
  await expect(selected).toHaveClass(/\bon\b/);
  await expect(selected).toContainText(item.title);
});
