// 使用本机 Playwright 与 Chrome；在临时原型副本中预置待合并的种子。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

async function check() {
  const root = path.resolve(__dirname, '../../..');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'jk-demo-'));
  let browser;
  try {
    fs.cpSync(path.join(root, 'prototype/v4'), tmp, { recursive: true });
    const json = f => fs.readFileSync(path.join(root, 'data/seed', f + '.json'), 'utf8');
    fs.appendFileSync(path.join(tmp, 'config/mock-data.js'), '\nObject.assign(window.JK_DATA, ' + json('demo') + ');\n');
    for (const [f, key] of [['real-kb','JK_REAL_KB'], ['kb-examples','JK_KB_EXAMPLES']]) {
      fs.writeFileSync(path.join(tmp, 'data', f + '.js'), 'window.' + key + ' = ' + json(f));
    }
    browser = await chromium.launch({ channel: 'chrome' });
    for (const width of [1440, 1280]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.goto(pathToFileURL(path.join(tmp, 'index.html')).href);
      await page.locator('[data-u="wangmin"]').click();
      await page.locator('#chatcol').waitFor();
      const first = await page.evaluate(() => {
        const command = JK.registry.enterprise.manifest.demo[0].say;
        const intent = JKOp.understand(command);
        return { app: intent.best.intent.app, ent: intent.slots.ent.id, command };
      });
      assert.equal(first.app, 'enterprise');
      assert.equal(first.ent, 'E002');
      await page.evaluate(command => JKShell.send(command), first.command);
      const opened = page.locator('[data-op="enterprise.profile"]');
      await opened.getByText('示例企业', { exact: true }).waitFor();
      assert.match(await opened.innerText(), /DEMO-E002/);
      await page.locator('[data-op="enterprise.back"]').click();
      await page.locator('[data-op="enterprise.q"]').fill('DEMO-E002');
      const target = page.locator('[data-op="enterprise.ent-E002"]');
      await target.getByText('示例企业', { exact: true }).waitFor();
      await target.click();
      const profile = page.locator('[data-op="enterprise.profile"]');
      await profile.getByText('示例企业', { exact: true }).waitFor();
      assert.match(await profile.innerText(), /DEMO-E002/);
      await screenshot(page, width, 'enterprise');
      await page.locator('[data-op="enterprise.tab-list"]').click();
      const badges = page.locator('tr').getByText('示例企业', { exact: true });
      await badges.first().waitFor();
      assert.equal(await badges.count(), 24);
      await page.evaluate(() => JKShell.openApp('kb'));
      const summaryRow = page.locator('.kb-summary');
      const counts = await page.evaluate(async () => {
        const { hits } = await JKAPI.get('/api/v1/kb/docs?limit=2000');
        const count = key => hits.filter(d => d[key]).length;
        return { total: hits.length, real: count('real'), example: count('example'),
          template: hits.filter(d => d.space === 'template').length,
          rules: hits.filter(d => d.space === 'rules').length };
      });
      const summary = `真实公开资料 ${counts.real} 份 + 示例资料 ${counts.example} 份`;
      await summaryRow.filter({ hasText: summary }).waitFor();
      assert.ok((await summaryRow.innerText()).includes(counts.total + ' 份资料'));
      await screenshot(page, width, 'kb');
      for (const [id, name] of [['template', '申报通知'], ['rules', '机构职责']]) {
        const chip = page.locator(`[data-op="kb.space-${id}"]`);
        assert.equal((await chip.innerText()).replace(/\s/g, ''), name + counts[id]);
      }
      await page.evaluate(() => JK.services.kb.import({ text: '独立的页面统计核验文字', title: '核验导入' }, { space: 'rules', from: '对话' }));
      await summaryRow.filter({ hasText: '对话 1 份' }).waitFor();
      assert.ok((await summaryRow.innerText()).includes((counts.total + 1) + ' 份资料'));
      assert.equal((await page.locator('[data-op="kb.space-rules"]').innerText()).replace(/\s/g, ''), '机构职责' + (counts.rules + 1));
      await page.evaluate(() => JKShell.openApp('meeting'));
      await page.locator('[data-op^="meeting.m-"]').first().getByText(/示例/).waitFor();
      console.log(width, 'px：企业卡片、详情、24 行台账、知识库空间和统计、示例会议均通过');
      await page.close();
    }
  } finally {
    if (browser) await browser.close();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}
async function screenshot(page, width, name) {
  if (process.env.JK_SCREENSHOTS) await page.screenshot({ path: path.join(process.env.JK_SCREENSHOTS, name + '-' + width + '.png') });
}
check().catch(err => { console.error(err); process.exitCode = 1; });
