// 用发布入口实际加载生成文件，并在断网的 Chromium 中验证演示界面。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '../../..');
const entry = pathToFileURL(path.join(root, 'prototype/v4/index.html')).href;
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

async function checkPolicy(page) {
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

  await page.evaluate(() => JKShell.newChat());
  await page.evaluate(() => JKShell.send(JK_CONFIG.homeSuggestions[0].text));
  const selection = op(page, 'policy.selection');
  await selection.filter({ hasText: '已选 9 项 · 默认选中 9 项 · 本批已结束 3 项' }).waitFor();
  await op(page, 'policy.show-all').click();
  assert.equal(await panel.locator('input[data-pick]').count(), 12);
  assert.equal(await panel.locator('input[data-pick]:checked').count(), 9);
  console.log('政策匹配 12 行，勾选 9 行，本批已结束 3 项');
}

async function checkUpgrade(page) {
  const oldShort = '星河智驾';
  const newShort = '纸鹿二号智驾';
  await page.evaluate(({ oldShort, newShort }) => {
    const state = JSON.parse(JSON.stringify(JKAPI.state()), (_, value) =>
      typeof value === 'string' ? value.replaceAll(newShort, oldShort) : value,
    );
    delete state.demoSeedVersion;
    const company = state.enterprises.find((item) => item.id === 'E002');
    delete company.example;
    company.creditCode = '旧演示格式';
    localStorage.setItem(JK_STATE_KEY, JSON.stringify(state));
    localStorage.setItem('jk4-convs:' + state.me, JSON.stringify([
      { id: 'legacy', title: oldShort + '走访', msgs: [] },
      { id: 'other', title: '保留的草稿', msgs: [] },
    ]));
  }, { oldShort, newShort });
  await page.reload();
  await op(page, 'nav.inbox').waitFor();
  await page.locator('[data-conv="legacy"]').getByText(newShort + '走访').waitFor();
  await page.getByText('保留的草稿', { exact: true }).waitFor();
  await page.reload();
  await op(page, 'nav.inbox').waitFor();
  await page.locator('[data-conv="legacy"]').getByText(newShort + '走访').waitFor();
  const result = await page.evaluate((oldShort) => {
    const stored = Object.keys(localStorage).filter((key) =>
      key === JK_STATE_KEY || key.startsWith('jk4-convs:'),
    ).map((key) => localStorage.getItem(key));
    const { name, creditCode, example } = JKAPI.state().enterprises.find((item) => item.id === 'E002');
    return { name, creditCode, example, oldName: stored.some((value) => value.includes(oldShort)) };
  }, oldShort);
  assert.deepEqual(result, { name: '北京纸鹿二号智驾科技有限公司', creditCode: 'DEMO-E002', example: true, oldName: false });
  console.log('旧 localStorage 升级并重载两次，企业及对话使用新名，其他历史保留');
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
        await checkPolicy(page);
        await checkUpgrade(page);
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
