// 用发布入口实际加载生成文件，并在断网的 Chromium 中验证演示界面。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');
const legacy = require('./legacy-cache.json');

const root = path.resolve(__dirname, '../../..');
const entry = pathToFileURL(path.join(root, 'web/index.html')).href;
const realSeed = JSON.parse(fs.readFileSync(path.join(root, 'data/seed/real-kb.json'), 'utf8')).docs;
const countOf = async (locator) => Number((await locator.innerText()).match(/\d+/)?.[0]);
const op = (page, name) => page.locator('[data-op="' + name + '"]');

async function checkHome(page) {
  const badge = op(page, 'nav.inbox').locator('.count');
  const pending = await countOf(badge);
  await op(page, 'nav.inbox').click();
  const panel = page.locator('.pview.on');
  await panel.locator('.inb-i').first().waitFor();
  assert.equal(await panel.locator('.inb-i').count(), pending);
  assert.equal(await countOf(panel.locator('[data-t="mine"] .count')), pending);
  console.log('首页收件箱角标、收件箱列表和待处理页签各 ' + pending + ' 项');
}

async function checkEnterprise(page, width) {
  await page.waitForFunction(() => {
    const say = JK.registry.enterprise.manifest.demo[0].say;
    return JKOp.understand(say).slots.ent?.id === 'E002';
  });
  const command = await page.evaluate(() => JK.registry.enterprise.manifest.demo[0].say);
  await page.evaluate((say) => JKShell.send(say), command);
  const profile = op(page, 'enterprise.profile');
  await profile.getByText('示例企业', { exact: true }).waitFor();
  assert.match(await profile.innerText(), /DEMO-E002/);
  await page.locator('#chatcol').getByText('示例企业', { exact: true }).waitFor();

  await op(page, 'enterprise.back').click();
  await op(page, 'enterprise.q').fill('DEMO-E002');
  const card = op(page, 'enterprise.ent-E002');
  await card.getByText('示例企业', { exact: true }).waitFor();
  await card.click();
  await profile.getByText('示例企业', { exact: true }).waitFor();
  assert.match(await profile.innerText(), /DEMO-E002/);
  await op(page, 'enterprise.brief').getByText('项可核对').waitFor();
  if (process.env.JK_SCREENSHOTS) {
    await page.screenshot({ path: path.join(process.env.JK_SCREENSHOTS, 'demo-' + width + '.png') });
  }
  await op(page, 'enterprise.tab-list').click();
  const badges = page.locator('.pview.on tr').getByText('示例企业', { exact: true });
  await badges.first().waitFor();
  assert.equal(await badges.count(), 24);

  console.log('企业卡片、详情和对话卡片显示示例标记，企业台账 24 个角标');
}

async function checkKb(page) {
  await page.evaluate(() => JKShell.openApp('kb'));
  const summary = page.locator('.pview.on .kb-summary');
  const counts = await page.evaluate(async () => {
    const { hits } = await JKAPI.get('/api/v1/kb/docs?limit=2000');
    return {
      total: hits.length,
      real: hits.filter((d) => d.real).length,
      example: hits.filter((d) => d.example).length,
    };
  });
  assert.equal(counts.real, realSeed.filter((d) => d.real === true).length);
  const label = '真实公开资料 ' + counts.real + ' 份 + 示例资料 ' + counts.example + ' 份';
  await summary.filter({ hasText: label }).waitFor();
  assert.equal(await countOf(summary), counts.total);

  await op(page, 'kb.tab-library').click();
  const panel = page.locator('.pview.on');
  const rows = panel.locator('.kb-hit');
  await rows.first().waitFor();
  assert.equal(await countOf(op(page, 'kb.st-all').locator('.v')), counts.total);
  assert.match(await panel.locator('.kb-more').innerText(),
    new RegExp('共 ' + counts.total + ' 份，已显示 ' + await rows.count() + ' 份'));
  console.log('知识库总计 ' + counts.total + '；' + label);
  for (const [id, name] of [['template', '申报通知'], ['rules', '机构职责'], ['minutes', '会议纪要']]) {
    const chip = panel.locator('[data-ls="' + id + '"]');
    assert.match(await chip.innerText(), new RegExp(name));
    await chip.click();
    await rows.first().waitFor();
    const count = await rows.count();
    assert.equal(await countOf(chip), count);
    if (id === 'minutes') {
      assert.equal(await rows.getByText('示例', { exact: true }).count(), count);
    }
    console.log('知识库 ' + name + ' ' + count + ' 行');
  }
  await op(page, 'kb.tab-home').click();
  await page.evaluate(() => JK.services.kb.import(
    { text: '独立的页面统计核验文字', title: '核验导入' }, { space: 'rules', from: '对话' },
  ));
  await summary.filter({ hasText: '对话 1 份' }).waitFor();
  assert.equal(await countOf(summary), counts.total + 1);
}

async function checkPolicy(page, legacy) {
  await page.evaluate(() => JKShell.openApp('policy'));
  const tab = op(page, 'policy.tab-items');
  await tab.click();
  const panel = page.locator('.pview.on');
  const rows = panel.locator('[data-detail]');
  await rows.first().waitFor();
  const all = await rows.count();
  assert.equal(await countOf(tab.locator('.count')), all);
  assert.equal(await countOf(panel.locator('#pb > .meta')), all);
  await op(page, 'policy.obj-个人').click();
  await rows.first().waitFor();
  const filtered = await rows.count();
  assert.equal(await countOf(panel.locator('#pb > .meta')), filtered);
  const expected = await page.evaluate(async () =>
    (await JKApi.policy.items()).items.filter((item) => item.object === '个人').length,
  );
  assert.equal(filtered, expected);
  console.log('政策库全部 ' + all + ' 行，个人筛选 ' + filtered + ' 行');

  await page.evaluate((legacy) => {
    const request = JKAPI.request.bind(JKAPI);
    window.pendingPolicyCalculations = {};
    JKAPI.request = async (method, route, body) => {
      const result = await request(method, route, body);
      if (route === '/api/apps/policy/match' && legacy) {
        const { profile, results, summary: { ok, check, no } } = result;
        // 模拟规范 4.1 的精简响应，同时验证目录可补上未返回的窗口状态。
        return { profile, results: results.map(({ ended, open, ...item }) => item), summary: { ok, check, no } };
      }
      if (route === '/api/apps/policy/calc' && body.itemId === 'RP-006') {
        await new Promise((resolve) => { window.pendingPolicyCalculations[body.amount] = resolve; });
      }
      return result;
    };
  }, legacy);
  await page.evaluate(() => JKShell.newChat());
  await page.evaluate(() => JKShell.send(JK_CONFIG.homeSuggestions[0].text));
  const selection = op(page, 'policy.selection');
  await selection.filter({ hasText: '已选 9 项 · 默认选中 9 项 · 本批已结束 3 项' }).waitFor();
  await op(page, 'policy.show-all').click();
  assert.equal(await panel.locator('input[data-pick]').count(), 12);
  assert.equal(await panel.locator('input[data-pick]:checked').count(), 9);
  console.log((legacy ? '旧匹配响应' : '当前匹配响应') + '：12 行，勾选 9 行，本批已结束 3 项');

  await op(page, 'policy.next').click();
  const amount = op(page, 'policy.calc-RP-006');
  const row = panel.locator('.pol-calc').filter({ has: amount });
  await amount.fill('222');
  await amount.press('Tab');
  await page.waitForFunction(() => pendingPolicyCalculations[2220000]);
  await amount.fill('123');
  await amount.press('Tab');
  await page.waitForFunction(() => pendingPolicyCalculations[1230000]);
  await page.evaluate(() => pendingPolicyCalculations[1230000]());
  await row.getByText(/123 万元 × 30% = 36\.9 万元/).waitFor();
  await page.evaluate(() => pendingPolicyCalculations[2220000]());
  assert.equal(await amount.inputValue(), '123');
  assert.match(await row.innerText(), /123 万元 × 30% = 36\.9 万元/);

  await amount.fill('130');
  await op(page, 'policy.to-notice').click();
  const preview = op(page, 'policy.notice-text');
  await preview.waitFor();
  const content = await preview.inputValue();
  assert.match(content, /试算参考：130 万元 × 30% = 39 万元/);
  assert.doesNotMatch(content, /试算参考：123 万元 × 30%/);
  await page.waitForFunction(() => pendingPolicyCalculations[1300000]);
  await page.evaluate(() => pendingPolicyCalculations[1300000]());
  const downloadEvent = page.waitForEvent('download');
  await op(page, 'policy.download').click();
  const download = await downloadEvent;
  assert.equal(fs.readFileSync(await download.path(), 'utf8'), content);
  console.log('告知单在试算回包前生成，预览和下载都用当前 130 万元');

  const dataCompany = await page.evaluate(() => JKAPI.state().enterprises.find(({ id }) => id === 'E003').short);
  await page.evaluate((name) => {
    JKShell.newChat();
    return JKShell.send(`帮我查一下${name}能申报哪些政策`);
  }, dataCompany);
  await panel.locator('#ps > .q').filter({ hasText: dataCompany }).waitFor();
  if (await op(page, 'policy.show-all').count()) await op(page, 'policy.show-all').click();
  const closed = panel.locator('[data-res="RP-003"]');
  assert.match(await closed.innerText(), /本批已结束/);
  await op(page, 'policy.more-RP-003').click();
  assert.match(await closed.innerText(), /2026\.11\.06 截止/);
  await op(page, 'policy.pick-RP-003').check();
  await op(page, 'policy.next').click();
  await op(page, 'policy.to-notice').click();
  await preview.waitFor();
  assert.match(await preview.inputValue(), /申报时间：本批已结束。最近一批已于 2026\.11\.06 截止/);
  console.log('RP-003 匹配详情和告知单均显示 2026.11.06 截止与本批已结束');
}

async function checkUpgrade(page) {
  const oldShort = legacy.company.short;
  const newShort = '纸鹿二号智驾';
  const imported = '用户原文中保留' + oldShort + '的历史称谓。';
  const [conversation] = legacy.conversations;
  const quote = legacy.messages[conversation.id][1].content;
  const fileId = await page.evaluate(async ({ imported, quote, legacy }) => {
    const { docs } = await JKAPI.post('/api/v1/kb/import', { text: imported, title: '历史原文核验' });
    const state = JSON.parse(JSON.stringify(JKAPI.state()));
    delete state.demoSeedVersion;
    const company = state.enterprises.find((item) => item.id === legacy.company.id);
    Object.assign(company, legacy.company);
    delete company.example;
    company.creditCode = '旧演示格式';
    state.drafts['DOC-1112'].versions[0].content.paragraphs[0] = imported;
    localStorage.setItem(JK_STATE_KEY, JSON.stringify(state));
    localStorage.setItem('jk4-convs:' + state.me, JSON.stringify([
      legacy.shellConversation,
      { id: 'legacy-quote', title: legacy.conversations[0].title, msgs: [
        { role: 'user', text: imported, file: { text: imported } },
        { role: 'ai', text: quote },
        { role: 'ai', text: imported, cites: [{ snippet: imported }] },
      ] },
    ]));
    return docs[0].id;
  }, { imported, quote, legacy });
  const card = legacy.shellConversation;
  const previousAnswer = card.msgs.at(-1);
  const newSummary = previousAnswer.text.replace(oldShort, newShort);
  const shellConversation = page.locator('[data-conv="' + card.id + '"]');
  for (let i = 0; i < 2; i++) {
    await page.reload();
    await op(page, 'nav.inbox').waitFor();
    await shellConversation.getByText(card.title, { exact: true }).waitFor();
    await page.locator('[data-conv="legacy-quote"]').getByText(conversation.title, { exact: true }).waitFor();
    await shellConversation.click();
    await page.locator('#chatcol').getByText(newSummary, { exact: true }).waitFor();
  }
  const result = await page.evaluate(async ({ fileId, shellId, companyId }) => {
    const { name, creditCode, example } = JKAPI.state().enterprises.find((item) => item.id === companyId);
    const state = JSON.parse(localStorage.getItem(JK_STATE_KEY));
    const conversations = JSON.parse(localStorage.getItem('jk4-convs:' + state.me));
    const history = conversations.find(({ id }) => id === 'legacy-quote');
    const card = conversations.find(({ id }) => id === shellId);
    const { item } = await JKAPI.get('/api/v1/kb/docs/' + fileId);
    return { name, creditCode, example, version: state.demoSeedVersion, card, history,
      imported: item.text, draft: state.drafts['DOC-1112'].versions[0].content.paragraphs[0] };
  }, { fileId, shellId: card.id, companyId: legacy.company.id });
  assert.deepEqual(result, {
    name: '北京纸鹿二号智驾科技有限公司', creditCode: 'DEMO-E002', example: true, version: 3,
    imported, draft: imported,
    card: { ...card, msgs: [...card.msgs.slice(0, -1), { ...previousAnswer, text: newSummary,
      next: previousAnswer.next.map((action) => ({ ...action, say: action.say.replace(oldShort, newShort) })) }] },
    history: { id: 'legacy-quote', title: conversation.title, msgs: [
      { role: 'user', text: imported, file: { text: imported } },
      { role: 'ai', text: quote },
      { role: 'ai', text: imported, cites: [{ snippet: imported }] },
    ] },
  });
  console.log('旧缓存重载两次，企业速览和固定动作更新；历史标题、无引用标记的引述、附件、知识库与草稿原文逐字保留');
}

async function checkLegacyApproval(page) {
  const draft = legacy.drafts['PI-18'];
  const [review] = legacy.reviews;
  await page.evaluate(async ({ draft, review }) => {
    JKAPI.state().drafts[draft.id] = draft;
    JKAPI.state().inbox.unshift(review);
    await JKShell.switchUser('liyang');
    await JKShell.openApp('document');
  }, { draft, review });
  await op(page, 'document.tab-list').click();
  await op(page, 'document.row-' + draft.id).click();
  await op(page, 'document.approve').click();
  await page.locator('[role="dialog"] [data-ok]').click();
  await page.locator('.toast').getByText(/请退回修订.*PI-18.*已下线/).waitFor();
  await op(page, 'document.reject').waitFor();
  assert.equal(await page.evaluate(async (draftId) => (await JKApi.document.exportWord(draftId)).final, draft.id), false);

  await page.evaluate(() => { void JKShell.send('审签通过'); });
  await page.getByRole('button', { name: '确认通过', exact: true }).first().click();
  await page.locator('#chatcol .msg').getByText(/请退回修订.*PI-18.*已下线/).waitFor();
  assert.equal(await page.locator('#chatcol .msg').getByText(/^已定稿/).count(), 0);
  assert.equal(await page.evaluate((id) => JKAPI.state().inbox.find(item => item.id === id).status, review.id), 'pending');
  console.log('旧 PI-18 在公文按钮和对话审签均提示退回修订，保留待审状态及未定稿导出');
}

async function checkPolishedApproval(page) {
  await page.evaluate(() => JKShell.openApp('document'));
  const panel = page.locator('.pview.on[data-view="document"]');
  const submitted = [];
  for (const [templateId, policy] of [['T03', 'RP-006'], ['T10', 'RP-024']]) {
    const currentIds = await page.evaluate(() => Object.keys(JKAPI.state().drafts));
    await op(panel, 'document.tpl-' + templateId).click();
    await op(panel, 'document.sample').click();
    await op(panel, 'document.in-policy').selectOption(policy);
    if (templateId === 'T03') await op(panel, 'document.in-contact').fill('请填写');
    await op(panel, 'document.gen').click();
    await op(panel, 'document.paper').waitFor();
    await op(panel, 'document.panel-polish').click();
    assert.match(await op(panel, 'document.pstyle-formal').getAttribute('class'), /\bon\b/);
    await op(panel, 'document.polish').click();
    await op(panel, 'document.polish-yes').click();
    await panel.locator('#ds .q').getByText('第 2 版', { exact: true }).waitFor();
    const draftId = await page.evaluate((previous) => Object.keys(JKAPI.state().drafts)
      .find((id) => !previous.includes(id)), currentIds);
    assert.ok(draftId, templateId + ' ' + policy);
    await op(panel, 'document.to-review').click();
    await op(panel, 'document.submit').click();
    await page.getByRole('button', { name: '确认送审', exact: true }).click();
    await panel.locator('.dc-status .tag').filter({ hasText: /^审签中$/ }).waitFor();
    assert.equal(await page.evaluate((id) => JKAPI.state().drafts[id].status, draftId), '审签中');
    submitted.push([draftId, templateId, policy]);
    await op(panel, 'document.step-0').click();
  }
  await page.evaluate(async () => {
    await JKShell.switchUser('liyang');
    await JKShell.openApp('document');
  });
  for (const [id, templateId, policy] of submitted) {
    await op(panel, 'document.tab-list').click();
    await op(panel, 'document.row-' + id).click();
    await op(panel, 'document.approve').click();
    await page.locator('[role="dialog"] [data-ok]').click();
    await panel.getByText(/内容已锁定，需要改请另存新稿/).waitFor();
    assert.equal(await page.evaluate(async (id) => (await JKApi.document.exportWord(id)).final, id), true);
    console.log(templateId + ' ' + policy + ' 采用「更正式」第 2 版，送审、批准、定稿导出通过');
  }
}

async function main() {
  const browser = await chromium.launch();
  try {
    for (const width of [1440, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: 900 }, offline: true });
      page.setDefaultTimeout(12000);
      const errors = [];
      page.on('pageerror', (error) => errors.push(error.message));
      try {
        await page.goto(entry);
        await page.locator('[data-u="wangmin"]').click();
        await page.locator('.home').waitFor();
        assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
        console.log(width + 'px 浅色 / file:// / 离线');
        await checkHome(page);
        await checkEnterprise(page, width);
        await checkKb(page);
        await checkPolicy(page, width === 1280);
        await checkUpgrade(page);
        await checkPolishedApproval(page);
        await checkLegacyApproval(page);
        assert.deepEqual(errors, []);
      } finally {
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
