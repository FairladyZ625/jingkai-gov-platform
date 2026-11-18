const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const entry = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const checks = [
  ['开场', '.hello', '王敏'],
  ['政策兑现', '.pview.on #ps', '告知单已生成'],
  ['企业走访', '#chatcol .msgs', '高新技术企业共'],
  ['会议纪要', '#chatcol .msgs', '已派发 '],
  ['公文协作', '#chatcol .msgs', '第 1 版 → 第 2 版：新增'],
  ['知识库', '.pview.on', '未找到依据'],
  ['技能中心', '#chatcol .msgs', '已运行'],
  ['电脑操作', '#chatcol .msgs', '存进知识库'],
  ['审签', '.toast', '已通过'],
  ['外部协作者', '.pview.on', '外部协作者视图：联系人电话、营收已打码'],
  ['管理后台', '.pview.on [data-csv]', '导出'],
  ['浅色主题', 'html[data-theme="light"] .demo-caption', '深色、浅色'],
];

async function login(browser, width, theme, onError) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, offline: true });
  page.setDefaultTimeout(20000);
  page.on('pageerror', e => onError(e.message));
  page.on('console', m => {
    if (m.type() === 'error' || (m.type() === 'warning' && m.text().startsWith('demo '))) onError(m.text());
  });
  await page.addInitScript(t => localStorage.setItem('jk4-theme2', t), theme);
  await page.goto(entry);
  assert.equal(await page.evaluate(() => JK_CONFIG.api.mode), 'mock');
  await page.click('[data-u="wangmin"]');
  await page.locator('#btn-demo').waitFor();
  assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
  return page;
}

async function shot(page, name) {
  const file = 'screenshots/' + name + '.png';
  await page.screenshot({ path: path.join(__dirname, file) });
  return file;
}

async function walkthrough(browser, width, theme) {
  const rows = checks.map(([title], i) => ({
    name: (i + 1) + '. ' + title, width, theme, errors: [], file: '',
  }));
  let current = 0;
  const page = await login(browser, width, theme, message => rows[current].errors.push(message));
  try {
    assert.deepEqual(await page.evaluate(() => JK_DEMO_SCRIPT.map(s => s.title)), checks.map(c => c[0]));
    await page.click('#btn-demo');
    for (const [i, [, selector, key]] of checks.entries()) {
      current = i;
      const row = rows[i];
      const name = [width, theme, String(i + 1).padStart(2, '0')].join('-');
      // 若关键文字没有出现，保留本段入口截图，避免误用下一段画面。
      if (await page.evaluate(i => JKDemo.state.on && JKDemo.state.i === i, i)) {
        row.file = await shot(page, name);
      }
      // 同时等待业务结果和段落结束。跳段、异常退出都不能替代业务结果。
      const match = await page.waitForFunction(({ i, selector, key }) => {
        const { on, i: active } = JKDemo.state;
        if (!on || active > i) return '已离开本段';
        if (active === i && [...document.querySelectorAll(selector)].some(el =>
          el.getClientRects().length && el.innerText.includes(key))) return '匹配';
      }, { i, selector, key }, { timeout: 90000 });
      if (await match.jsonValue() !== '匹配') row.errors.push('本段未出现「' + key + '」');
      else row.file = await shot(page, name);
      await page.waitForFunction(i => !JKDemo.state.on || JKDemo.state.i > i, i, { timeout: 90000 });
    }
    assert.equal(await page.evaluate(() => JKDemo.state.i), checks.length, '一键演示提前退出');
  } catch (error) {
    rows[current].errors.push(error.message);
    for (const row of rows.slice(current + 1)) row.errors.push('前序中断，未执行');
  } finally {
    await page.close();
  }
  return rows;
}

async function say(page, text, reply) {
  const input = page.locator('#chatcol textarea');
  await input.fill(text);
  await input.press('Enter');
  await page.locator('#chatcol .msgs').getByText(reply).first().waitFor();
}

const matchQuestion = '帮我查一下星河智驾能申报哪些政策';
async function switchConversation(page) {
  await say(page, matchQuestion, /星河智驾：\d+ 项可进一步核对/);
  const heading = page.locator('.pview.on #ps .q');
  const expected = await heading.innerText();
  assert.match(expected, /星河智驾/);
  await page.click('[data-op="chat.new"]');
  await say(page, '芯视界半导体能申报哪些政策', /芯视界半导体：\d+ 项可进一步核对/);
  assert.match(await heading.innerText(), /芯视界半导体/);
  await page.locator('[data-conv]').filter({ hasText: '星河智驾' }).click();
  await page.locator('#chatcol .msgs').getByText(/星河智驾：\d+ 项可进一步核对/).waitFor();
  try {
    await page.waitForFunction(text => document.querySelector('.pview.on #ps .q')?.innerText === text, expected, {timeout: 5000});
  } catch {
    throw Error('返回星河智驾对话后，期望「' + expected + '」，面板显示「' + await heading.innerText() + '」');
  }
}

async function firstDocument(page) {
  await say(page, matchQuestion, /星河智驾：\d+ 项可进一步核对/);
  await say(page, '给星河智驾生成政策告知单', /告知单已生成（/);
  assert.equal(await page.locator('[data-view="document"]').count(), 0);
  await say(page, '把告知单转成公文答复', /已带上企业和政策依据/);
  const panel = page.locator('.pview.on[data-view="document"]');
  await panel.waitFor();
  try {
    await panel.locator('[data-in="ent"]').waitFor({ timeout: 5000 });
  } catch {
    throw Error('首次打开公文协作应进入答复意见填要素页，当前显示「' + await panel.locator('#ds .q').innerText() + '」');
  }
  assert.match(await panel.locator('#ds .q').innerText(), /答复意见/);
  assert.match(await panel.locator('[data-in="ent"] option:checked').innerText(), /星河智驾/);
  assert.ok(await panel.locator('[data-in="policy"]').inputValue(), '缺少政策依据');
}

async function regression(browser, name, id, run) {
  const row = { name, width: 1440, theme: 'dark', errors: [] };
  const page = await login(browser, row.width, row.theme, message => row.errors.push(message));
  try { await run(page); } catch (error) { row.errors.push(error.message); }
  row.file = await shot(page, id);
  await page.close();
  return row;
}

async function main() {
  await fs.mkdir(path.join(__dirname, 'screenshots'), { recursive: true });
  const browser = await chromium.launch();
  try {
    const results = await Promise.all([
      ...[1440, 1280].flatMap(width => ['dark', 'light'].map(theme => walkthrough(browser, width, theme))),
      regression(browser, 'P0 会话切换面板', 'p0-conversation', switchConversation),
      regression(browser, 'P0 政策转公文首次打开', 'p0-document', firstDocument),
    ]);
    const rows = results.flat();
    const failed = rows.filter(row => row.errors.length);
    const summary = '通过 ' + (rows.length - failed.length) + '，失败 ' + failed.length + '，共 ' + rows.length + ' 项';
    const table = rows.map(row => {
      const reason = row.errors.join('；').replaceAll('\n', ' ').replaceAll('|', '\\|');
      return '| ' + [row.name, row.width, row.theme, reason ? '失败' : '通过', reason || '—',
        row.file ? '[截图](' + row.file + ')' : '未截取'].join(' | ') + ' |';
    });
    await fs.writeFile(path.join(__dirname, 'REPORT.md'), ['# 离线 mock 演示回归', '', summary, '',
      '| 段落 / 用例 | 宽度 | 起始主题 | 结果 | 失败原因 | 现场 |', '|---|---:|---|---|---|---|', ...table, ''].join('\n'));
    console.log(summary);
    for (const row of failed) console.log(row.width, row.theme, row.name, row.errors.join('；'));
    if (failed.length) process.exitCode = 1;
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
