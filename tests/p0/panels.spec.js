const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { expect, test } = require('@playwright/test');

const prototypeUrl = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const op = (page, name) => page.locator(`[data-op="${name}"]`);
const activePanel = (page, app) => page.locator(`#pbody [data-view="${app}"].on`);

async function expectRoute(page, app, route, params) {
  await expect.poll(() => page.evaluate(() => {
    const { active, mounted, convs, cur } = JKShell.S;
    return {
      panel: convs.find((conv) => conv.id === cur)?.panel,
      active,
      params: mounted[active]?.ctx?.params,
    };
  })).toEqual({ panel: { app, route, params }, active: app, params });
}

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
  test.setTimeout(90000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  const policy = activePanel(page, 'policy');
  const enterprise = activePanel(page, 'enterprise');
  await login(page);
  await say(page, '帮我查一下星河智驾能申报哪些政策');
  await expect(policy.locator('#ps .q')).toContainText('星河智驾');
  await op(page, 'nav.chat').click();
  await say(page, '查一下书香里文化');
  await expect(op(enterprise, 'enterprise.profile')).toContainText('书香里文化');

  const history = page.locator('[data-conv]');
  const chatA = history.filter({ hasText: '帮我查一下星河智驾' });
  const chatB = history.filter({ hasText: '查一下书香里文化' });
  const showA = async () => {
    await chatA.click();
    await expect(policy.locator('#ps .q')).toContainText('星河智驾');
    await expectRoute(page, 'policy', 'match', { entId: 'E002' });
  };
  const showB = async () => {
    await chatB.click();
    await expect(op(enterprise, 'enterprise.profile')).toContainText('书香里文化');
    await expectRoute(page, 'enterprise', 'profile', { entId: 'E001' });
  };

  await test.step('A → B → A 三轮，核对 app、route、params', async () => {
    await showA();
    for (let round = 0; round < 3; round++) {
      await showB();
      await showA();
    }
  });

  await test.step('新对话清空所有旧挂载，重新打开四个应用均回到首页', async () => {
    const panels = [
      { app: 'policy', route: 'match', params: { entId: 'E002' }, detail: '#ps .pol-r1' },
      { app: 'enterprise', route: 'profile', params: { entId: 'E001' }, detail: '.ent-head' },
      { app: 'meeting', route: 'detail', params: { id: 'MT-1112' }, detail: '[data-op="meeting.link"]' },
      { app: 'document', route: 'new', params: { templateId: 'T10', inputs: { ent: 'E001' } }, detail: '[data-op="document.in-ent"]' },
    ];
    for (const { app, route, params, detail } of panels) {
      await page.evaluate(({ app, route, params }) => JKShell.openApp(app, route, params).then(() => {}), { app, route, params });
      await expect(activePanel(page, app).locator(detail).first()).toBeVisible();
    }
    await op(page, 'nav.chat').click();
    await expect(page.locator('#pbody .pview')).toHaveCount(0);
    for (const { app, detail } of panels) {
      await op(page, `nav.${app}`).click();
      const panel = activePanel(page, app);
      await expect(op(panel, `${app}.step-0`)).toHaveClass(/\bon\b/);
      await expect(panel.locator(detail)).toHaveCount(0);
      expect(await page.evaluate((id) => JKShell.S.mounted[id].ctx.params, app)).toEqual({});
      if (app === 'policy') await expect(op(panel, 'policy.go')).toBeDisabled();
    }
  });

  await test.step('重载后仍能恢复新记录，旧记录安全复位', async () => {
    await login(page);
    await showB();
    const legacyId = await chatA.getAttribute('data-conv');
    await page.evaluate((id) => {
      const { convs, me } = JKShell.S;
      const legacy = convs.find((conv) => conv.id === id);
      delete legacy.panel;
      localStorage.setItem('jk4-convs:' + me.id, JSON.stringify(convs));
    }, legacyId);
    await login(page);
    await showB();
    await chatA.click();
    await expect(page.locator('#pbody .pview')).toHaveCount(0);
    await expect(page.locator('#main')).not.toHaveClass(/\bsplit\b|\bmax\b/);
    expect(errors).toEqual([]);
  });
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
    expect(await page.evaluate(() => JKShell.S.mounted.document.ctx.params)).toEqual({
      from: 'policy', templateId: 'T03', inputs: { policy: policyId },
    });
  });

  await test.step('会议纪要 → 指定企业的诉求', async () => {
    await restartDemo(page);
    await op(page, 'nav.meeting').click();
    await op(page, 'meeting.src-nas').click();
    await op(page, 'meeting.m-MT-1112').click();
    await op(page, 'meeting.link').click();
    const entId = await page.locator('#le').inputValue();
    const name = await page.locator('#le option:checked').textContent();
    const topic = await page.locator('#lt option:checked').textContent();
    await page.getByRole('button', { name: '登记到企业台账' }).click();
    await page.getByRole('button', { name: '去看看' }).click();
    const issues = activePanel(page, 'enterprise');
    await expect(issues.locator('#es .q')).toHaveText(`${name} 的诉求`);
    await expect(issues.locator('.ent-iss-l')).toContainText(topic);
    expect(await page.evaluate(() => JKShell.S.mounted.enterprise.ctx.params)).toEqual({ entId });
  });

  await test.step('政策提示「查看」→ 指定企业的诉求', async () => {
    await restartDemo(page);
    await say(page, '给书香里生成政策告知单');
    await op(page, 'policy.issue').click();
    await page.locator('.toast').getByRole('button', { name: '查看', exact: true }).click();
    const issues = activePanel(page, 'enterprise');
    await expect(issues.locator('#es .q')).toHaveText('书香里文化 的诉求');
    await expect(issues.locator('.ent-iss-l')).toContainText('政策咨询：');
    await expectRoute(page, 'enterprise', 'issues', { entId: 'E001' });
  });

  await test.step('政策告知单 → 公文答复要素', async () => {
    await restartDemo(page);
    await say(page, '帮我查一下书香里文化能申报哪些政策');
    const policy = activePanel(page, 'policy');
    const [policyId, ...otherIds] = await policy.locator('[data-pick]:checked')
      .evaluateAll((items) => items.map((item) => item.dataset.pick));
    expect(policyId).toBeTruthy();
    for (const id of otherIds) await op(policy, `policy.pick-${id}`).uncheck();
    await say(page, '给书香里生成政策告知单');
    const notice = await op(page, 'policy.notice-text').inputValue();
    expect(notice).toContain('书香里');
    await say(page, '把告知单转成公文答复');
    const document = activePanel(page, 'document');
    await expect(document.locator('#ds .q')).toContainText('答复意见');
    await expect(op(document, 'document.in-ent')).toHaveValue('E001');
    await expect(op(document, 'document.in-policy')).toHaveValue(policyId);
    await expect(op(document, 'document.in-issue')).toHaveValue(/咨询.+申报/);
    const issue = await op(document, 'document.in-issue').inputValue();
    await expectRoute(page, 'document', 'new', {
      from: 'policy', templateId: 'T10', inputs: { ent: 'E001', policy: policyId, issue }, notice,
    });
  });

  await test.step('ready() 超时后保留首页，迟到的结果不会执行跳转', async () => {
    await restartDemo(page);
    const warnings = [];
    page.on('console', (message) => {
      if (message.type() === 'warning') warnings.push(message.text());
    });
    await page.evaluate(() => {
      const app = JK.registry.document;
      const mount = app.mount;
      app.mount = (el, ctx) => {
        const ctl = mount(el, ctx);
        ctl.ready = () => new Promise((resolve) => { window.finishDocumentReady = resolve; });
        return ctl;
      };
      window.documentNavigation = JKShell.openApp('document', 'new', { templateId: 'T10' });
    });
    const document = activePanel(page, 'document');
    await expect(op(document, 'document.step-0')).toHaveClass(/\bon\b/);
    expect(warnings).toEqual([]);
    await expect.poll(() => warnings, { timeout: 5000 }).toEqual(['「公文协作」等待就绪超过 3 秒，已显示首页']);
    await page.evaluate(() => window.documentNavigation.then(() => {}));
    await page.evaluate(() => window.finishDocumentReady());
    await expect(op(document, 'document.step-0')).toHaveClass(/\bon\b/);
    await expect(op(document, 'document.in-ent')).toHaveCount(0);
    expect(await page.evaluate(() => JKShell.S.mounted.document.ctx.params)).toEqual({});
    expect(warnings).toHaveLength(1);
  });
});
