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
  const states = page.locator('#chatcol .pstate');
  const before = await states.count();
  await input.fill(text);
  await input.press('Enter');
  await expect(states).toHaveCount(before + 1);
  await expect(states.last()).toHaveText('已完成', { timeout: 12000 });
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
  await say(page, '帮我查一下纸鹿二号智驾能申报哪些政策');
  await expect(policy.locator('#ps .q')).toContainText('纸鹿二号智驾');
  await op(page, 'nav.chat').click();
  await say(page, '查一下书香里文化');
  await expect(op(enterprise, 'enterprise.profile')).toContainText('书香里文化');

  const history = page.locator('[data-conv]');
  const chatA = history.filter({ hasText: '帮我查一下纸鹿二号智驾' });
  const chatB = history.filter({ hasText: '查一下书香里文化' });
  const showA = async () => {
    await chatA.click();
    await expect(policy.locator('#ps .q')).toContainText('纸鹿二号智驾');
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

test('切换对话时取消等待中的政策任务，企业对话保持原样', async ({ page }) => {
  await login(page);
  await say(page, '查一下书香里文化');
  const chatB = page.locator('[data-conv].on');
  const idB = await chatB.getAttribute('data-conv');
  const snapshot = () => page.evaluate((id) => {
    const { convs, me } = JKShell.S;
    const persisted = JSON.parse(localStorage.getItem('jk4-convs:' + me.id));
    return {
      live: convs.find((conv) => conv.id === id),
      saved: persisted.find((conv) => conv.id === id),
      messages: document.querySelector('#chatcol .msgs-in').textContent,
    };
  }, idB);
  const before = await snapshot();
  await op(page, 'nav.chat').click();

  await page.evaluate((id) => {
    window.firstPolicyRun = JKShell.send('帮我查一下纸鹿二号智驾能申报哪些政策');
    window.switchWhenQueued = () => {
      const run = JKOp.running;
      const stop = run.stop;
      run.stop = (silent) => {
        run.stop = stop;
        stop(silent);
        // 第二条请求已进入 Op.start，等待结束前切换会话。
        document.querySelector(`[data-conv="${id}"]`).click();
      };
    };
  }, idB);
  await expect.poll(() => page.evaluate(() => !!JKOp.running)).toBe(true);
  await page.evaluate(async () => {
    window.switchWhenQueued();
    await JKShell.send('帮我查一下书香里文化能申报哪些政策');
    await window.firstPolicyRun;
  });

  await expect(op(activePanel(page, 'enterprise'), 'enterprise.profile')).toContainText('书香里文化');
  await expectRoute(page, 'enterprise', 'profile', { entId: 'E001' });
  expect(await snapshot()).toEqual(before);
  await page.locator('[data-conv]').filter({ hasText: '帮我查一下纸鹿二号智驾' }).click();
  await expect(page.locator('#chatcol .pstate')).toHaveText(['已停下']);
});

test('手动选标签、关闭活动标签和关闭面板后恢复对应状态', async ({ page }) => {
  test.setTimeout(50000);
  await login(page);
  await say(page, '查一下书香里文化');
  const chatB = page.locator('[data-conv]').filter({ hasText: '查一下书香里文化' });
  await op(page, 'nav.chat').click();
  await say(page, '帮我查一下纸鹿二号智驾能申报哪些政策');
  const chatA = page.locator('[data-conv]').filter({ hasText: '帮我查一下纸鹿二号智驾' });
  const policyTab = page.locator('#ptabs [data-id="policy"]');
  const enterpriseTab = page.locator('#ptabs [data-id="enterprise"]');
  const policy = activePanel(page, 'policy');

  await say(page, '查一下纸鹿二号智驾');
  await expect(enterpriseTab).toHaveClass(/\bon\b/);
  await policyTab.click();
  await expect(policy.locator('#ps .q')).toContainText('纸鹿二号智驾');
  await chatB.click();
  await chatA.click();
  await expect(policy.locator('#ps .q')).toContainText('纸鹿二号智驾');
  await expectRoute(page, 'policy', 'match', { entId: 'E002' });

  await say(page, '查一下纸鹿二号智驾');
  await expect(enterpriseTab).toHaveClass(/\bon\b/);
  await enterpriseTab.locator('.x').click();
  await expect(policy.locator('#ps .q')).toContainText('纸鹿二号智驾');
  await chatB.click();
  await chatA.click();
  await expectRoute(page, 'policy', 'match', { entId: 'E002' });

  await page.locator('#btn-pclose').click();
  await chatB.click();
  await chatA.click();
  await expect(page.locator('#pbody .pview')).toHaveCount(0);
  expect(await page.evaluate(() => JKShell.S.convs.find((chat) => chat.id === JKShell.S.cur).panel)).toBeUndefined();
});

test('通过对话打开的会议纪要和公文详情按记录 ID 恢复', async ({ page }) => {
  test.setTimeout(45000);
  await login(page);
  await say(page, '整理一下文化企业座谈会的纪要');
  const chatMeeting = page.locator('[data-conv]').filter({ hasText: '整理一下文化企业座谈会' });
  const minutes = op(activePanel(page, 'meeting'), 'meeting.minutes');
  await expect(minutes).toContainText('文化企业座谈会');

  await op(page, 'nav.chat').click();
  await say(page, '打开书香里的答复意见');
  const chatDocument = page.locator('[data-conv]').filter({ hasText: '打开书香里的答复意见' });
  const paper = op(activePanel(page, 'document'), 'document.paper');
  await expect(paper).toContainText('关于对北京书香里文化发展有限公司诉求的答复意见');

  for (const reload of [false, true]) {
    if (reload) await login(page);
    await chatMeeting.click();
    await expect(minutes).toContainText('文化企业座谈会');
    await expectRoute(page, 'meeting', 'detail', { id: 'MT-1112' });
    await chatDocument.click();
    await expect(paper).toContainText('关于对北京书香里文化发展有限公司诉求的答复意见');
    await expectRoute(page, 'document', 'detail', { id: 'DOC-1112' });
  }
});

test('告知单转公文后手填要素按对话保留', async ({ page }) => {
  test.setTimeout(65000);
  await login(page);
  const issue = op(activePanel(page, 'document'), 'document.in-issue');
  const openDraft = async (helpText, draftText) => {
    await say(page, helpText);
    await say(page, '把告知单转成公文答复');
    await expect(issue).toHaveValue(/咨询.+申报/);
    await issue.fill(draftText);
  };

  await openDraft('给书香里生成政策告知单', '书香里补充的诉求说明');
  const chatA = page.locator('[data-conv]').filter({ hasText: '给书香里生成政策告知单' });
  await op(page, 'nav.chat').click();
  await openDraft('给纸鹿二号智驾生成政策告知单', '纸鹿二号智驾补充的诉求说明');
  const chatB = page.locator('[data-conv]').filter({ hasText: '给纸鹿二号智驾生成政策告知单' });

  await chatA.click();
  await expect(issue).toHaveValue('书香里补充的诉求说明');
  await chatB.click();
  await expect(issue).toHaveValue('纸鹿二号智驾补充的诉求说明');
  await expect(op(activePanel(page, 'document'), 'document.in-ent')).toHaveValue('E002');
  await login(page);
  await chatA.click();
  await expect(issue).toHaveValue('书香里补充的诉求说明');
});

test('侧栏一键演示从 file:// 完成 12 段', async ({ page }) => {
  test.setTimeout(300000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (['warning', 'error'].includes(message.type())) errors.push(message.text());
  });
  await login(page);
  await page.evaluate(() => {
    window.demoResults = [];
    JK.bus.on('op:done', (result) => window.demoResults.push(result));
  });
  await op(page, 'shell.demo').click();
  await expect(page.locator('.demobar')).toBeVisible();
  await expect(page.locator('.demobar')).toHaveCount(0, { timeout: 280000 });
  expect(await page.evaluate(() => {
    const { demoResults } = window;
    return {
      user: JKShell.S.me.username,
      segments: JKDemo.state.i,
      completed: demoResults.length,
      failures: demoResults.filter(({ fail, stopped }) => fail || stopped),
    };
  })).toEqual({ user: 'wangmin', segments: 12, completed: 20, failures: [] });
  expect(errors).toEqual([]);
  console.log('一键演示：12/12 段，20 次操作员执行完成，0 次失败或停止，0 条页面错误或控制台警告。');
});

test('退出一键演示恢复主题，旧一轮收尾不干扰紧接启动的新一轮', async ({ page }) => {
  await page.context().setOffline(true);
  await login(page);
  await page.evaluate(() => {
    JKShell.setTheme('dark');
    JK_DEMO_SCRIPT = [{ title: '浅色主题', steps: [{ theme: 'light' }, { open: 'inbox' }, { theme: 'dark' }] }];
    window.finishDemoSteps = [];
    JKShell.openBuiltin = () => new Promise(resolve => finishDemoSteps.push(resolve));
    window.firstDemo = JKDemo.start();
  });
  const readTheme = () => page.evaluate(() => [
    document.documentElement.dataset.theme, localStorage.getItem('jk4-theme2'),
  ]);
  const bar = page.locator('.demobar');
  await expect.poll(() => page.evaluate(() => finishDemoSteps.length)).toBe(1);
  const beforeExit = await readTheme();
  expect(beforeExit).toEqual(['light', 'light']);
  await bar.getByRole('button', { name: '退出' }).click();
  await expect(bar).toHaveCount(0);
  const afterExit = await readTheme();
  expect(afterExit).toEqual(['dark', 'dark']);
  console.log(`一键演示退出：展示 ${beforeExit.join('/')} → 恢复 ${afterExit.join('/')}（DOM/偏好）`);

  await page.evaluate(() => { window.secondDemo = JKDemo.start(); });
  await expect.poll(() => page.evaluate(() => finishDemoSteps.length)).toBe(2);
  await page.evaluate(async () => {
    finishDemoSteps[0]();
    await firstDemo;
  });
  await expect(bar).toBeVisible();
  expect(await readTheme()).toEqual(['light', 'light']);
  await page.evaluate(async () => {
    finishDemoSteps[1]();
    await secondDemo;
  });
  await expect(bar).toHaveCount(0);
  expect(await readTheme()).toEqual(['dark', 'dark']);
});

test('一键演示发生运行错误后恢复启动主题', async ({ page }) => {
  await page.context().setOffline(true);
  await login(page);
  const warning = page.waitForEvent('console', {
    predicate: message => message.type() === 'warning' && message.text().includes('演示收尾测试错误'),
  });
  const themes = await page.evaluate(async () => {
    JKShell.setTheme('light');
    JK_DEMO_SCRIPT = [{ title: '深色主题', steps: [{ theme: 'dark' }, { open: 'inbox' }] }];
    let beforeError;
    JKShell.openBuiltin = () => {
      beforeError = JKShell.theme();
      throw new Error('演示收尾测试错误');
    };
    await JKDemo.start();
    return { beforeError, dom: JKShell.theme(), saved: localStorage.getItem('jk4-theme2') };
  });
  await warning;
  await expect(page.locator('.demobar')).toHaveCount(0);
  expect(themes).toEqual({ beforeError: 'dark', dom: 'light', saved: 'light' });
  console.log(`一键演示异常：展示 ${themes.beforeError} → 恢复 ${themes.dom}/${themes.saved}（DOM/偏好）`);
});

test('告知单往返后按原勾选和正文首次转公文', async ({ page }) => {
  test.setTimeout(50000);
  await login(page);
  await say(page, '查一下纸鹿二号智驾');
  const other = page.locator('[data-conv]').filter({ hasText: '查一下纸鹿二号智驾' });
  await op(page, 'nav.chat').click();
  await say(page, '帮我查一下书香里文化能申报哪些政策');
  const savedChat = page.locator('[data-conv]').filter({ hasText: '帮我查一下书香里文化' });
  await op(page, 'policy.pick-PI-03').uncheck();
  await expect(op(page, 'policy.pick-RP-024')).toBeChecked();
  await say(page, '给书香里生成政策告知单');
  const notice = op(page, 'policy.notice-text');
  const edited = (await notice.inputValue()) + '\n演示备注：已和企业确认补充材料。';
  await notice.fill(edited);
  await other.click();
  await savedChat.click();
  await expect(notice).toHaveValue(edited);
  await login(page);
  await savedChat.click();
  await expect(notice).toHaveValue(edited);
  await say(page, '把告知单转成公文答复');
  await expect(op(page, 'document.in-policy')).toHaveValue('RP-024');
  const params = await page.evaluate(() => JKShell.S.mounted.document.ctx.params);
  expect(params.notice).toBe(edited);
});

test('公文初稿的未保存标题和段落在往返后可以保存', async ({ page }) => {
  test.setTimeout(55000);
  await login(page);
  await say(page, '查一下纸鹿二号智驾');
  const other = page.locator('[data-conv]').filter({ hasText: '查一下纸鹿二号智驾' });
  await op(page, 'nav.chat').click();
  await say(page, '写一份企业诉求答复意见');
  const draftChat = page.locator('[data-conv]').filter({ hasText: '写一份企业诉求答复意见' });
  const title = page.locator('[data-pe="title"]');
  const body = page.locator('[data-pe="0"]');
  await title.click();
  await page.locator('[data-ed="title"]').fill('企业诉求答复意见演示稿');
  await body.click();
  await body.click();
  await page.locator('[data-ed="0"]').fill('第一段保留的手填说明。');
  await op(page, 'document.panel-check').click();
  await expect(page.getByText('有未保存的修改', { exact: true })).toBeVisible();

  await other.click();
  await draftChat.click();
  await expect(title).toHaveText('企业诉求答复意见演示稿');
  await expect(body).toHaveText('第一段保留的手填说明。');
  await expect(op(page, 'document.save')).toBeVisible();
  await op(page, 'document.save').click();
  await expect(op(page, 'document.save')).toHaveCount(0);

  await other.click();
  await draftChat.click();
  await expect(title).toHaveText('企业诉求答复意见演示稿');
  await expect(body).toHaveText('第一段保留的手填说明。');
  await expect(op(page, 'document.save')).toHaveCount(0);
});

test('往返恢复实际政策步骤、企业筛选和公文页签', async ({ page }) => {
  test.setTimeout(65000);
  await login(page);
  await say(page, '查一下书香里文化');
  const other = page.locator('[data-conv] .t').getByText('查一下书香里文化', { exact: true });
  await op(page, 'nav.chat').click();

  await test.step('政策核对已手动退回选对象', async () => {
    await say(page, '帮我查一下纸鹿二号智驾能申报哪些政策');
    const target = page.locator('[data-conv]').filter({ hasText: '帮我查一下纸鹿二号智驾' });
    await op(page, 'policy.step-0').click();
    await other.click();
    await target.click();
    await expect(op(page, 'policy.step-0')).toHaveClass(/\bon\b/);
    await expect(op(page, 'policy.ent')).toHaveValue('纸鹿二号智驾');
    await expectRoute(page, 'policy', 'home', { entId: 'E002' });
  });

  await test.step('企业列表沿用问句生效的标签和手动筛选', async () => {
    await op(page, 'nav.chat').click();
    await say(page, '打开企业台账筛选高新企业');
    const target = page.locator('[data-conv]').filter({ hasText: '打开企业台账筛选高新企业' });
    await expect(op(page, 'enterprise.list-tag')).toHaveValue('高新技术');
    await op(page, 'enterprise.list-q').fill('纸鹿二号');
    await op(page, 'enterprise.list-alert').check();
    await page.locator('#lsort').selectOption('name');
    await expect(op(page, 'enterprise.list-count')).toBeVisible();
    await other.click();
    await target.click();
    await expect(op(page, 'enterprise.list-tag')).toHaveValue('高新技术');
    await expect(op(page, 'enterprise.list-q')).toHaveValue('纸鹿二号');
    await expect(op(page, 'enterprise.list-alert')).toBeChecked();
    await expect(page.locator('#lsort')).toHaveValue('name');
    await expectRoute(page, 'enterprise', 'list', { tag: '高新技术', q: '纸鹿二号', alert: 1, sort: 'name' });
  });

  await test.step('公文从起草改看我的文稿', async () => {
    await op(page, 'nav.chat').click();
    await say(page, '帮我查一下书香里文化能申报哪些政策');
    const target = page.locator('[data-conv]').filter({ hasText: '帮我查一下书香里文化' });
    await op(page, 'nav.document').click();
    await op(page, 'document.tpl-T10').click();
    await expect(op(page, 'document.in-issue')).toBeVisible();
    await op(page, 'document.tab-list').click();
    await other.click();
    await target.click();
    await expect(op(page, 'document.tab-list')).toHaveClass(/\bon\b/);
    await expect(op(page, 'document.row-DOC-1112')).toBeVisible();
    await expectRoute(page, 'document', 'list', {});
  });
});

test('通过对话切换视角后发起账号的任务卡已完成', async ({ page }) => {
  await login(page);
  const result = await page.evaluate(async () => {
    const events = [];
    JK.bus.on('op:done', (e) => events.push(e));
    const key = 'jk4-convs:' + JKShell.S.me.id;
    await JKShell.send('切换到领导视角');
    const plan = JSON.parse(localStorage.getItem(key))[0].msgs.find((m) => m.role === 'plan');
    return { username: JKShell.S.me.username, state: plan.state, steps: plan.steps.map(({ s }) => s), events };
  });
  expect(result).toEqual({ username: 'liyang', state: 'done', steps: ['done', 'done'], events: [{ appId: 'shell' }] });
});
