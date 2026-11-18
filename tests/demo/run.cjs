const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');
const { labels, installChecks, checkMasking } = require('./checks.cjs');

const entry = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const report = path.join(__dirname, 'REPORT.md');

// PR #59 合入后移除对应标记。只有已知故障的具体症状属于预期失败。
const expectedFailures = new Set(['p0-conversation', 'p0-document']);
class KnownP0 extends Error {}

function result(name, width, theme) {
  return { name, width, theme, errors: [], file: '', evidence: '', expected: false };
}

async function newPage(browser, width, theme, onError) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, offline: true });
  try {
    const page = await context.newPage();
    page.setDefaultTimeout(12000);
    page.on('pageerror', e => onError(e.message));
    page.on('console', m => {
      if (m.type() === 'error' || (m.type() === 'warning' && m.text().startsWith('demo '))) onError(m.text());
    });
    await page.addInitScript(t => localStorage.setItem('jk4-theme2', t), theme);
    return page;
  } catch (error) {
    await context.close();
    throw error;
  }
}

async function login(page, theme) {
  await page.goto(entry);
  assert.equal(await page.evaluate(() => JK_CONFIG.api.mode), 'mock');
  await page.click('[data-u="wangmin"]');
  await page.locator('#btn-demo').waitFor();
  assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
}

async function capture(row, page, name) {
  const file = 'screenshots/' + name + '.png';
  try {
    await page.screenshot({ path: path.join(__dirname, file), timeout: 4000 });
    row.file = file;
  } catch (error) {
    row.errors.push('截图失败：' + error.message);
  }
}

function markInterrupted(rows, index, message) {
  rows[index].errors.push(message);
  for (const row of rows.slice(index + 1)) row.errors.push('前序中断，未执行');
}

async function walkthrough(browser, rows) {
  const { width, theme } = rows[0];
  let page;
  let current = 0;
  let started = false;
  try {
    page = await newPage(browser, width, theme, message => rows[current].errors.push(message));
    await login(page, theme);
    assert.deepEqual(await page.evaluate(() => JK_DEMO_SCRIPT.map(s => s.title)), labels.map(([title]) => title));
    await page.evaluate(installChecks);
    await page.click('#btn-demo');
    started = true;

    for (const [i, row] of rows.entries()) {
      current = i;
      const name = [width, theme, String(i + 1).padStart(2, '0')].join('-');
      // 段落未满足断言时，也尽量保存该段入口的现场。
      const active = await page.waitForFunction(i => {
        const state = JKDemo.state;
        if (!state.on || state.i >= i) return state.on && state.i === i ? '本段' : '已离开';
      }, i, { timeout: 90000 });
      if (await active.jsonValue() === '本段') await capture(row, page, name);

      const outcome = await page.waitForFunction(i => demoRegression.inspect(i), i, { timeout: 90000 });
      const { missing, active: stillActive } = await outcome.jsonValue();
      if (missing.length) row.errors.push('缺少「' + missing.join('」「') + '」');
      else if (stillActive) await capture(row, page, name);
      if (i === 4 || i === 8) {
        const draft = await page.evaluate(() => demoRegression.submittedDraft());
        if (draft) row.evidence = '文稿 ' + draft.docId + ' / 审签单 ' + draft.reviewId;
      }
      await page.waitForFunction(i => !JKDemo.state.on || JKDemo.state.i > i, i, { timeout: 90000 });
    }
    assert.equal(await page.evaluate(() => JKDemo.state.i), labels.length, '一键演示提前退出');

    current = 9;
    try {
      await checkMasking(page);
      rows[current].evidence = '何军档案与王敏同企业档案对照';
    } catch (error) {
      rows[current].errors.push(error.message);
      await capture(rows[current], page, width + '-' + theme + '-10-mask-failure');
    }
  } catch (error) {
    markInterrupted(rows, current, (started ? '' : '初始化失败：') + error.message);
    if (page && !rows[current].file) await capture(rows[current], page, width + '-' + theme + '-interrupted');
  } finally {
    await page?.context().close();
  }
}

async function say(page, text, reply) {
  const input = page.locator('#chatcol textarea');
  await input.fill(text);
  await input.press('Enter');
  await page.locator('#chatcol .msg.ai .txt').getByText(reply).first().waitFor();
}

async function company(page, id) {
  const e = await page.evaluate(id => JK_DATA.enterprises.find(e => e.id === id), id);
  assert.ok(e?.short && e.name, '模拟企业缺少名称：' + id);
  return { id, short: e.short, name: e.name };
}

function matchReply(e) {
  const short = e.short.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(short + '：\\d+ 项可进一步核对');
}

async function matchCompany(page, e) {
  await say(page, e.short + '能申报哪些政策', matchReply(e));
}

async function switchConversation(page, row) {
  const first = await company(page, 'E002');
  const second = await company(page, 'E010');
  row.evidence = first.short + ' → ' + second.short + ' → ' + first.short;
  const heading = page.locator('.pview.on[data-view="policy"] #ps .q');

  await matchCompany(page, first);
  const expected = await heading.innerText();
  assert.ok(expected.includes(first.short), '首个会话面板未显示 ' + first.short);
  await page.click('[data-op="chat.new"]');
  await matchCompany(page, second);
  const other = await heading.innerText();
  assert.ok(other.includes(second.short), '第二个会话面板未显示 ' + second.short);
  await page.locator('[data-conv]').filter({ hasText: first.short }).click();
  await page.locator('#chatcol .msg.ai .txt').getByText(matchReply(first)).waitFor();

  await page.waitForFunction(text => document.querySelector('.pview.on[data-view="policy"] #ps .q')?.innerText === text,
    expected, { timeout: 5000 }).catch(async error => {
    if (error.name !== 'TimeoutError') throw error;
    const actual = await heading.textContent({ timeout: 1000 });
    const message = '返回 ' + first.short + ' 后，期望「' + expected + '」，面板显示「' + actual + '」';
    if (actual === other) throw new KnownP0(message);
    assert.equal(actual, expected, message);
  });
}

async function firstDocument(page, row) {
  const e = await company(page, 'E002');
  await matchCompany(page, e);
  await say(page, '给' + e.short + '生成政策告知单', /告知单已生成（/);
  const notice = await page.locator('.pview.on [data-op="policy.notice-text"]').inputValue();
  assert.ok(notice.startsWith(e.name + '：'), '告知单所用企业与 ' + e.id + ' 不符');
  const firstLine = notice.split('\n').find(line => line.startsWith('1. '));
  assert.ok(firstLine, '告知单缺少第一项政策');

  const candidateIds = await page.evaluate(async line => {
    const { items } = await JKApi.policy.items();
    return items.filter(p => line.startsWith('1. ' + p.title + '（' + p.docNo + ' ')).map(p => p.id);
  }, firstLine);
  assert.equal(candidateIds.length, 1, '无法从告知单首项唯一确定政策 ID：' + firstLine);
  const [policyId] = candidateIds;
  row.evidence = e.short + ' / 告知单首项 ' + policyId;

  assert.equal(await page.locator('[data-view="document"]').count(), 0, '公文应用此前已打开');
  await say(page, '把告知单转成公文答复', /已带上企业和政策依据/);
  const panel = page.locator('.pview.on[data-view="document"]');
  await panel.waitFor();
  const heading = panel.locator('#ds .q');
  await panel.locator('[data-in="ent"]').waitFor({ timeout: 5000 }).catch(async error => {
    if (error.name !== 'TimeoutError') throw error;
    const actual = await heading.innerText();
    const message = '首次打开应进入答复意见填要素页，当前显示「' + actual + '」';
    if (actual.trim() === '要办什么事？') throw new KnownP0(message);
    throw Error(message);
  });
  assert.match(await heading.innerText(), /答复意见/);
  assert.equal(await panel.locator('[data-in="ent"]').inputValue(), e.id, '公文企业 ID 与告知单不一致');
  const actualId = await panel.locator('[data-in="policy"]').inputValue();
  row.evidence += ' / 公文实际 ' + (actualId || '空');
  assert.equal(actualId, policyId, '公文政策 ID 与告知单首项不一致');
}

async function regression(browser, row, id, run) {
  let page;
  let started = false;
  try {
    page = await newPage(browser, row.width, row.theme, message => row.errors.push(message));
    await login(page, row.theme);
    started = true;
    await run(page, row);
    if (expectedFailures.has(id)) row.errors.push('预期失败的用例已通过，请核对 PR #59 并移除该标记');
  } catch (error) {
    row.expected = started && error instanceof KnownP0 && expectedFailures.has(id) && !row.errors.length;
    row.errors.push((started ? '' : '初始化失败：') + error.message);
  } finally {
    if (page) await capture(row, page, id);
    await page?.context().close();
  }
  if (row.errors.length > 1) row.expected = false;
}

async function writeReport(rows) {
  const failed = rows.filter(row => row.errors.length && !row.expected);
  const expected = rows.filter(row => row.expected).length;
  const summary = '通过 ' + (rows.length - failed.length - expected) + '，预期失败 ' + expected +
    '，失败 ' + failed.length + '，共 ' + rows.length + ' 项';
  const cell = value => value.replaceAll('\n', ' ').replaceAll('|', '\\|');
  const table = rows.map(row => {
    const status = row.expected ? '预期失败' : row.errors.length ? '失败' : '通过';
    return '| ' + [row.name, row.width, row.theme, status, cell(row.errors.join('；')) || '—',
      cell(row.evidence) || '—', row.file ? '[截图](' + row.file + ')' : '未截取'].join(' | ') + ' |';
  });
  await fs.writeFile(report, ['# 离线 mock 演示回归', '', summary, '',
    '| 段落 / 用例 | 宽度 | 起始主题 | 结果 | 失败原因 | 业务证据 | 现场 |',
    '|---|---:|---|---|---|---|---|', ...table, ''].join('\n'));
  console.log(summary);
  for (const row of rows.filter(row => row.errors.length)) {
    console.log(row.width, row.theme, row.name, row.expected ? '预期失败' : '失败', row.errors.join('；'));
  }
  if (failed.length) process.exitCode = 1;
}

async function main() {
  const groups = [1440, 1280].flatMap(width => ['dark', 'light'].map(theme =>
    labels.map(([title, evidence], i) => ({ ...result((i + 1) + '. ' + title, width, theme), evidence }))));
  const p0 = [
    [result('P0 会话切换面板', 1440, 'dark'), 'p0-conversation', switchConversation],
    [result('P0 政策转公文首次打开', 1440, 'dark'), 'p0-document', firstDocument],
  ];
  const rows = [...groups.flat(), ...p0.map(([row]) => row)];
  await fs.writeFile(report, '# 离线 mock 演示回归\n\n本次运行尚未结束。\n');

  let browser;
  try {
    await fs.mkdir(path.join(__dirname, 'screenshots'), { recursive: true });
    browser = await chromium.launch();
  } catch (error) {
    for (const group of groups) markInterrupted(group, 0, '浏览器初始化失败：' + error.message);
    for (const [row] of p0) row.errors.push('浏览器初始化失败：' + error.message);
    await writeReport(rows);
    return;
  }

  try {
    const jobs = [
      ...groups.map(group => [group, walkthrough(browser, group)]),
      ...p0.map(([row, id, run]) => [[row], regression(browser, row, id, run)]),
    ];
    const outcomes = await Promise.allSettled(jobs.map(([, job]) => job));
    outcomes.forEach((outcome, i) => {
      if (outcome.status === 'rejected') {
        const row = jobs[i][0][0];
        row.expected = false;
        row.errors.push('用例运行异常：' + outcome.reason.message);
      }
    });
  } finally {
    await writeReport(rows);
    await browser.close();
  }
}

if (require.main === module) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}

module.exports = { main, walkthrough, regression, result, switchConversation, firstDocument };
