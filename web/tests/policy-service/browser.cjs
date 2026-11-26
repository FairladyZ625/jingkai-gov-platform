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
  const page = await browser.newPage({ viewport: { width, height: 900 }, offline: true });
  page.setDefaultTimeout(8000);
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.goto(entry); await page.locator('[data-u="wangmin"]').click();
  await expect(page.getByLabel('助手模式', { exact: true })).toHaveValue('general');
  return page;
}

test('政策参考清单和旧告知单问法都路由到转公文动作', async t => {
  const page = await setup(t);
  const routed = await page.evaluate(() => ['把政策参考清单转成公文答复', '把告知单转成公文答复']
    .map(text => ({ text, intent: JKOp.understand(text).best?.intent.id })));
  assert.deepEqual(routed, [
    { text: '把政策参考清单转成公文答复', intent: 'policy.toDocument' },
    { text: '把告知单转成公文答复', intent: 'policy.toDocument' },
  ]);
});

test('政策岗位在当前会话持续使用真实查询，原文可打开，模式不抢走旧应用位置', { timeout: 60000 }, async t => {
  const page = await setup(t);
  const apps = await page.locator('#shell-side [data-app]').evaluateAll(es => es.map(e => e.dataset.app));
  await page.getByLabel('助手模式', { exact: true }).selectOption('policy_service');
  await page.getByLabel('服务企业', { exact: true }).selectOption('E001');
  await page.locator('[data-op="chat.input"]').fill('实体书店房租有哪些申请条件？');
  await page.locator('[data-op="chat.send"]').click();
  await expect(page.locator('.msg.ai').last()).toContainText('申请条件');
  const context = await page.evaluate(() => JKShell.S.convs.find(c => c.id === JKShell.S.cur).context);
  assert.deepEqual(context, { mode: 'policy_service', enterpriseId: 'E001' });
  await expect(page.locator('.msg.ai .src').first()).toBeVisible();
  await page.locator('.msg.ai .src').first().click();
  await expect(page.locator('.drawer')).toContainText('原文');
  await page.keyboard.press('Escape');
  assert.deepEqual(await page.locator('#shell-side [data-app]').evaluateAll(es => es.map(e => e.dataset.app)), apps);
  await page.locator('[data-op="chat.input"]').fill('那需要什么材料？');
  await page.locator('[data-op="chat.send"]').click();
  await expect(page.locator('.msg.ai').last()).toContainText('申报材料');
});

test('岗位与企业按会话保存，新会话和切换账号不继承，切回通用清除企业', { timeout: 60000 }, async t => {
  const page = await setup(t);
  await page.getByLabel('助手模式', { exact: true }).selectOption('policy_service');
  await page.getByLabel('服务企业', { exact: true }).selectOption('E002');
  await page.locator('[data-op="chat.input"]').fill('数据券需要什么材料？');
  await page.locator('[data-op="chat.send"]').click();
  await expect(page.locator('.msg.ai').last()).toContainText('申报材料');
  const cid = await page.evaluate(() => JKShell.S.cur);
  await page.evaluate(() => JKShell.newChat());
  await expect(page.getByLabel('助手模式', { exact: true })).toHaveValue('general');
  await page.locator(`[data-conv="${cid}"]`).click();
  await expect(page.getByLabel('助手模式', { exact: true })).toHaveValue('policy_service');
  await expect(page.getByLabel('服务企业', { exact: true })).toHaveValue('E002');
  await page.reload();
  await page.locator(`[data-conv="${cid}"]`).click();
  await expect(page.getByLabel('服务企业', { exact: true })).toHaveValue('E002');
  await page.getByLabel('助手模式', { exact: true }).selectOption('general');
  await page.getByLabel('助手模式', { exact: true }).selectOption('policy_service');
  await expect(page.getByLabel('服务企业', { exact: true })).toHaveValue('');
  await page.evaluate(() => JKShell.switchUser('hejun'));
  await expect(page.getByLabel('助手模式', { exact: true })).toHaveValue('general');
  assert.equal(await page.locator(`[data-conv="${cid}"]`).count(), 0);
});

test('HTTP消息契约传递岗位与企业，等待中切换企业不会改写已发出的消息上下文', { timeout: 45000 }, async t => {
  const page = await setup(t);
  await page.getByLabel('助手模式', { exact: true }).selectOption('policy_service');
  await page.getByLabel('服务企业', { exact: true }).selectOption('E001');
  await page.evaluate(() => {
    window.policyRequests = [];
    JKHttp.mode = () => 'http';
    JKApi.chat.create = () => new Promise(resolve => { window.releaseConversation = () => resolve({ item: { id: 'http-protocol-test' } }); });
    JKApi.chat.send = async (id, body) => { policyRequests.push({ id, body }); return { reply: { content: '协议桩：已接收当前岗位', intent: 'policy' } }; };
  });
  await page.locator('[data-op="chat.input"]').fill('先核对房租政策');
  await page.locator('[data-op="chat.send"]').click();
  await page.getByLabel('服务企业', { exact: true }).selectOption('E002');
  await page.evaluate(() => releaseConversation());
  await expect.poll(() => page.evaluate(() => policyRequests.length)).toBe(1);
  const request = await page.evaluate(() => policyRequests[0]);
  assert.equal(request.body.mode, 'policy_service');
  assert.equal(request.body.enterpriseId, 'E001');
  assert.equal(request.body.stream, true);
});

for (const width of [1440, 1280, 390]) test(`政策岗位 ${width}px 模式与企业控件可见`, { timeout: 45000 }, async t => {
  const page = await setup(t, width);
  await page.getByLabel('助手模式', { exact: true }).selectOption('policy_service');
  await page.getByLabel('服务企业', { exact: true }).selectOption('E001');
  await page.locator('[data-op="chat.input"]').fill('实体书店房租有哪些申请条件？');
  await page.locator('[data-op="chat.send"]').click();
  await expect(page.locator('.msg.ai').last()).toContainText('申请条件');
  await expect(page.getByLabel('助手模式', { exact: true })).toBeVisible();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  if (process.env.POLICY_SCREENSHOTS) {
    await mkdir(process.env.POLICY_SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: join(process.env.POLICY_SCREENSHOTS, `policy-mode-${width}.png`) });
  }
});
test('升级前的旧会话不继承首页尚未发送的岗位和企业', { timeout: 45000 }, async t => {
  const page = await setup(t);
  await page.evaluate(() => { JKShell.S.convs.unshift({ id: 'legacy-without-context', title: '升级前旧会话', at: '10:00', msgs: [] }); JKShell.rerenderSide(); });
  await page.getByLabel('助手模式', { exact: true }).selectOption('policy_service');
  await page.getByLabel('服务企业', { exact: true }).selectOption('E001');
  await page.locator('[data-conv="legacy-without-context"]').click();
  await expect(page.getByLabel('助手模式', { exact: true })).toHaveValue('general');
  await expect(page.getByLabel('服务企业', { exact: true })).toHaveCount(0);
});
