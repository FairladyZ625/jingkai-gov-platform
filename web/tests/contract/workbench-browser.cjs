const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chromium, expect } = require('@playwright/test');
const { join } = require('node:path');
const { mkdir } = require('node:fs/promises');
const { pathToFileURL } = require('node:url');
const entry = pathToFileURL(join(__dirname, '../../index.html')).href;
async function setup(t, width = 1280) {
  const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : {});
  t.after(() => browser.close());
  const context = await browser.newContext({ viewport: { width, height: 900 }, offline: true });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.goto(entry);
  await page.locator('[data-u="wangmin"]').click();
  await page.locator('[data-op="shell.me"]').waitFor({ state: 'attached' });
  return page;
}

test('工作台记录、返回、刷新、退出及历史访问按身份隔离', { timeout: 60000 }, async t => {
  const page = await setup(t);
  assert.deepEqual(await page.locator('#side-sc [data-app]').evaluateAll(nodes => nodes.map(n => n.dataset.app).filter(id => ['policy', 'enterprise', 'meeting', 'document'].includes(id))), ['policy', 'enterprise', 'meeting', 'document']);
  await page.locator('#side-sc [data-workbench="meeting"]').click();
  await page.evaluate(() => JKWorkbench.open('meeting', { recordId: 'M-TEST' }));
  await expect(page).toHaveURL(/record=M-TEST/);
  await page.goBack();
  await expect(page.locator('#workbench')).toHaveAttribute('data-record', '');
  await page.evaluate(() => JKWorkbench.open('meeting', { recordId: 'M-TEST' }));
  await page.locator('[data-nav="chat"]').first().click();
  assert.equal(new URL(page.url()).hash, '');
  await page.locator('#side-sc [data-workbench="meeting"]').click();
  await expect(page.locator('#workbench')).toHaveAttribute('data-record', 'M-TEST');
  await page.reload();
  await expect(page.locator('#workbench')).toHaveAttribute('data-record', 'M-TEST');
  await page.locator('[data-op="shell.me"]').click();
  await page.getByText('退出登录', { exact: true }).click();
  await page.locator('[data-u="hejun"]').click();
  await expect(page.locator('[data-workbench="meeting"]')).toHaveCount(0);
  await page.goBack();
  await expect(page.locator('#workbench')).toBeHidden();
  await expect(page.locator('#workbench')).toHaveAttribute('data-record', '');
});

test('工作台隐藏背景控件，原应用深链、收件箱与历史对话可切回', { timeout: 60000 }, async t => {
  const page = await setup(t);
  await page.evaluate(() => JKShell.send('你好'));
  await page.locator('.hist [data-conv]').first().waitFor();
  await page.locator('#side-sc [data-workbench="document"]').click();
  await expect(page.locator('#chatcol')).toBeHidden();
  await expect(page.locator('#side-sc [data-workbench="document"]')).toHaveAttribute('aria-current', 'page');
  await page.locator('.hist [data-conv]').first().click();
  await expect(page.locator('#workbench')).toBeHidden();
  await page.locator('#side-sc [data-workbench="document"]').click();
  await page.evaluate(() => JKShell.openApp('enterprise', 'list'));
  await expect(page.locator('#workbench')).toBeHidden();
  await expect(page.locator('.pview.on')).toHaveAttribute('data-view', 'enterprise');
  await page.locator('#side-sc [data-workbench="document"]').click();
  await page.locator('[data-op="nav.inbox"]').click();
  await expect(page.locator('#workbench')).toBeHidden();
  await expect(page.locator('.pview.on')).toHaveAttribute('data-view', 'inbox');
  await page.locator('#side-sc [data-workbench="document"]').click();
  await expect(page.locator('[data-op="rail.inbox"]')).not.toHaveClass(/\bon\b/);
  await expect(page.locator('[data-op="nav.inbox"]')).not.toHaveClass(/\bon\b/);
});

for (const width of [1440, 1280, 390]) {
  test(`工作台布局 ${width}px：导航可达、原应用可打开`, { timeout: 60000 }, async t => {
    const page = await setup(t, width);
    if (width < 1180) await page.locator('.rail-logo').click();
    await page.locator('#side-sc [data-workbench="meeting"]').click();
    await expect(page.locator('.side-drawer-open')).toHaveCount(0);
    await expect(page.locator('#workbench h1')).toHaveText('会议纪要工作台');
    await expect(page.locator('#workbench [data-wb-chat]')).toBeVisible();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    const bounds = await page.locator('#workbench').boundingBox();
    assert.ok(bounds.width > width * .5 && bounds.x + bounds.width <= width);
    if (process.env.WORKBENCH_SCREENSHOTS) {
      await mkdir(process.env.WORKBENCH_SCREENSHOTS, { recursive: true });
      await page.screenshot({ path: join(process.env.WORKBENCH_SCREENSHOTS, `workbench-${width}.png`) });
    }
    await page.locator('[data-wb-app]').click();
    await expect(page.locator('#workbench')).toBeHidden();
    await expect(page.locator('.pview.on')).toHaveAttribute('data-view', 'meeting');
  });
}

for (const width of [1280, 390]) {
  test(`返回对话保留原会话与消息 ${width}px`, { timeout: 60000 }, async t => {
    const page = await setup(t, width);
    await page.evaluate(() => JKShell.send('你好'));
    const before = await page.evaluate(() => ({ cur: JKShell.S.cur, messages: JKShell.S.convs.find(c => c.id === JKShell.S.cur)?.msgs }));
    assert.ok(before.cur);
    assert.ok(before.messages.length >= 2);
    await page.evaluate(() => JKShell.openApp('meeting'));
    if (width < 1180) await page.locator('.rail-logo').click();
    await page.locator('#side-sc [data-workbench="meeting"]').click();
    await expect(page.locator('#workbench h1')).toBeFocused();
    await page.locator('[data-wb-chat]').click();
    await expect(page.locator('#chatcol')).toBeVisible();
    const after = await page.evaluate(() => ({ cur: JKShell.S.cur, messages: JKShell.S.convs.find(c => c.id === JKShell.S.cur)?.msgs }));
    assert.deepEqual(after, before);
  });
}
