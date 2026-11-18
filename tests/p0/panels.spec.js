const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { expect, test } = require('@playwright/test');

const prototypeUrl = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const op = (page, name) => page.locator(`[data-op="${name}"]`);
const activePanel = (page, app) => page.locator(`#pbody [data-view="${app}"].on`);

async function login(page) {
  await page.goto(prototypeUrl);
  const demoAccount = page.locator('.ql[data-u="wangmin"]');
  await expect(demoAccount.or(op(page, 'nav.chat'))).toBeVisible();
  if (await demoAccount.isVisible()) await demoAccount.click();
  await expect(op(page, 'nav.chat')).toBeVisible();
}

async function restartDemo(page) {
  await page.evaluate(() => localStorage.clear());
  await login(page);
}

async function say(page, text) {
  const input = page.locator('#chatcol textarea');
  await input.fill(text);
  await input.press('Enter');
  await expect(page.locator('#chatcol .pstate').last()).toHaveText('已完成', { timeout: 12000 });
}

test('历史对话恢复自己的应用和企业，新对话清空旧面板', async ({ page }) => {
  test.setTimeout(60000);
  const policy = activePanel(page, 'policy');
  const enterprise = activePanel(page, 'enterprise');
  await login(page);
  await say(page, '帮我查一下星河智驾能申报哪些政策');
  await expect(policy.locator('#ps .q')).toContainText('星河智驾');
  await op(page, 'nav.chat').click();
  await say(page, '查一下书香里文化');
  await expect(op(enterprise, 'enterprise.profile')).toContainText('书香里文化');

  const history = page.locator('[data-conv]');
  await history.filter({ hasText: '帮我查一下星河智驾' }).click();
  await expect(policy.locator('#ps .q')).toContainText('星河智驾');
  await history.filter({ hasText: '查一下书香里文化' }).click();
  await expect(op(enterprise, 'enterprise.profile')).toContainText('书香里文化');

  await op(page, 'nav.chat').click();
  await expect(enterprise).toBeHidden();
  await say(page, '书香里文化能申请哪些支持？');
  await expect(policy.locator('#ps .q')).toContainText('书香里文化');
  await history.filter({ hasText: '帮我查一下星河智驾' }).click();
  await expect(policy.locator('#ps .q')).toContainText('星河智驾');

  await page.reload();
  await login(page);
  await history.filter({ hasText: '查一下书香里文化' }).click();
  await expect(op(enterprise, 'enterprise.profile')).toContainText('书香里文化');

  await page.evaluate(() => {
    const { convs, me } = JKShell.S;
    const oldest = convs.at(-1);
    delete oldest.panel;
    localStorage.setItem('jk4-convs:' + me.id, JSON.stringify(convs));
  });
  await login(page);
  await history.filter({ hasText: '查一下书香里文化' }).click();
  await expect(enterprise).toBeVisible();
  await history.filter({ hasText: '帮我查一下星河智驾' }).click();
  await expect(page.locator('#pbody .pview.on')).toHaveCount(0);
});

test('四条跨应用链接在目标首次挂载时进入正确页面并带参数', async ({ page }) => {
  test.setTimeout(65000);
  await test.step('政策事项 → 公文申报通知', async () => {
    await login(page);
    await op(page, 'nav.policy').click();
    await op(page, 'policy.tab-items').click();
    const item = activePanel(page, 'policy').locator('[data-detail]').first();
    const policyId = await item.getAttribute('data-detail');
    await item.click();
    await page.getByRole('button', { name: '起草申报通知' }).click();
    const document = activePanel(page, 'document');
    await expect(document.locator('.callout')).toContainText('来自政策匹配');
    await expect(op(document, 'document.in-policy')).toHaveValue(policyId);
  });

  await test.step('会议纪要 → 指定企业的诉求', async () => {
    await restartDemo(page);
    await op(page, 'nav.meeting').click();
    await op(page, 'meeting.src-nas').click();
    await op(page, 'meeting.m-MT-1112').click();
    await op(page, 'meeting.link').click();
    const name = await page.locator('#le option:checked').textContent();
    const topic = await page.locator('#lt option:checked').textContent();
    await page.getByRole('button', { name: '登记到企业台账' }).click();
    await page.getByRole('button', { name: '去看看' }).click();
    const issues = activePanel(page, 'enterprise');
    await expect(issues.locator('#es .q')).toHaveText(`${name} 的诉求`);
    await expect(issues.locator('.ent-iss-l')).toContainText(topic);
  });

  await test.step('政策提示「查看」→ 指定企业的诉求', async () => {
    await restartDemo(page);
    await say(page, '给书香里生成政策告知单');
    await op(page, 'policy.issue').click();
    await page.locator('.toast').getByRole('button', { name: '查看', exact: true }).click();
    const issues = activePanel(page, 'enterprise');
    await expect(issues.locator('#es .q')).toHaveText('书香里文化 的诉求');
    await expect(issues.locator('.ent-iss-l')).toContainText('政策咨询：');
  });

  await test.step('政策告知单 → 公文答复要素', async () => {
    await restartDemo(page);
    await say(page, '给书香里生成政策告知单');
    await expect(op(page, 'policy.notice-text')).toHaveValue(/书香里/);
    await say(page, '把告知单转成公文答复');
    const document = activePanel(page, 'document');
    await expect(document.locator('#ds .q')).toContainText('答复意见');
    await expect(op(document, 'document.in-ent')).toHaveValue('E001');
    await expect(op(document, 'document.in-policy')).toHaveValue(/\S/);
    await expect(op(document, 'document.in-issue')).toHaveValue(/咨询.+申报/);
    await expect.poll(() => page.evaluate(() => JKShell.S.mounted.document.ctx.params.notice)).toContain('书香里');
  });
});
