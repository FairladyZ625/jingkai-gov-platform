const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');
const {inspectRole, checkRole} = require('./role-surface.cjs');

const entry = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
let browser;
before(async () => {
  browser = await chromium.launch({ executablePath: process.env.JKQ_TEST_CHROMIUM });
});
after(async () => { await browser?.close(); });
async function login(t, user, width = 1440) {
  const page = await browser.newPage({ viewport: { width, height: 900 }, offline: true });
  t.after(() => page.close());
  await page.goto(entry);
  assert.equal(await page.evaluate(() => JK_CONFIG.api.mode), 'mock');
  await page.locator('[data-u="' + user + '"]').click();
  await page.locator('[data-op="rail.demo"]').waitFor();
  return page;
}
async function capture(page, name) {
  if (process.env.JKQ_UX_EVIDENCE) await page.screenshot({
    path: path.join(process.env.JKQ_UX_EVIDENCE, name + '-' + page.viewportSize().width + '.png'),
  });
}
for (const mode of ['http', 'mock']) for (const username of ['hejun','wangmin','liyang','admin']) {
  test(`#174 首屏/菜单/命令授权矩阵：${mode} / ${username}`, async t => {
    const p = await browser.newPage({offline:true});
    t.after(() => p.close());
    await p.goto(entry); await p.locator('#lf').waitFor();
    checkRole(assert, await p.evaluate(inspectRole, {mode, username}), mode);
  });
}
for (const width of [1440, 1280, 375]) {
  test('#213 点击关闭、快捷键 Esc 返回原焦点与页面 / ' + width, async t => {
    const p = await login(t, 'wangmin', width);
    const trigger = p.locator(width === 375 ? '[data-op="rail.cmdk"]' : '[data-op="nav.cmdk"]');
    await trigger.click();
    const close = p.locator('.cmdk').getByRole('button', { name: /关闭/ });
    assert.ok(await close.isVisible(), '命令弹层缺少可见的关闭按钮');
    const bounds = await close.boundingBox();
    assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.height >= 32);
    await p.locator('.cmdk input').press('Tab');
    assert.equal(await close.evaluate(el => el === document.activeElement), true);
    await capture(p, '213-search');
    await close.click();
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
    const input = p.locator('#chatcol textarea');
    await input.fill('还没发出的草稿');
    await input.press('Control+k');
    await p.locator('.cmdk input').press('Escape');
    assert.equal(await input.evaluate(el => el === document.activeElement), true);
    assert.equal(await input.inputValue(), '还没发出的草稿');
    assert.equal(await p.locator('.cmdk,.mask-bg').count(), 0);
  });
}
test('#174 已授权经办人仍按选中企业匹配', async t => {
  const p = await login(t, 'wangmin');
  await p.locator('#side-sc [data-app="enterprise"]').click();
  const enterprise = p.locator('.pview.on [data-ent]').first();
  const id = await enterprise.getAttribute('data-ent');
  await enterprise.click();
  await p.getByRole('button', { name: '能申请哪些政策' }).click();
  await p.locator('.pview.on [data-op="policy.kpi-ok"]').waitFor();
  assert.equal(await p.evaluate(() => JKShell.S.mounted.policy.ctx.params.entId), id);
});
test('#174 无查看权时不提供政策入口', async t => {
  const p = await login(t, 'hejun');
  // 只移除夹具授权，不新增权限。
  await p.evaluate(() => { delete JKShell.S.grants.policy; });
  await p.locator('#side-sc [data-app="enterprise"]').click();
  await p.locator('.pview.on [data-ent]').first().click();
  await p.locator('[data-op="enterprise.profile"]').waitFor();
  assert.match(await p.locator('#ebpol').innerText(), /没有.*查看权限/);
  assert.equal(await p.locator('[data-act="toPolicy"]').count(), 0);
});
test('#174 外部身份不推荐企业走访、企业匹配，也无部署重置入口', async t => {
  const p = await login(t, 'hejun');
  await p.locator('[data-op="nav.cmdk"]').click();
  for (const id of ['enterprise.visit', 'policy.match', 'policy.fill', 'policy.notice', 'policy.toDocument']) {
    const example = await p.evaluate(id => JKOp.allIntents().find(it => it.id === id).examples[0], id);
    await p.locator('.cmdk input').fill(example);
    assert.equal(await p.locator('.cmdk-list').getByText(example, { exact: true }).count(), 0);
  }
  const allowed = await p.evaluate(() => JKOp.allIntents().find(it => it.id === 'policy.items').examples[0]);
  await p.locator('.cmdk input').fill(allowed);
  assert.equal(await p.locator('.cmdk-list').getByText(allowed, { exact: true }).count(), 1);
  await p.locator('.cmdk input').press('Escape');
  await p.evaluate(() => { JKHttp.mode = () => 'http'; });
  await p.locator('#btn-me .nm').click();
  assert.equal(await p.locator('[data-v="reset"]').count(), 0);
  assert.equal(await p.locator('[data-v="logout"]').isVisible(), true);
});
for (const width of [1440, 1280]) {
  test('#174 企业档案只读入口不发匹配请求 / ' + width, async t => {
    const p = await login(t, 'hejun', width);
    await p.evaluate(() => {
      window.matches = 0;
      const match = JKApi.policy.match;
      JKApi.policy.match = (...args) => { matches++; return match(...args); };
    });
    await p.locator('#side-sc [data-app="enterprise"]').click();
    await p.locator('.pview.on [data-ent]').first().click();
    await p.locator('[data-op="enterprise.profile"]').waitFor();
    assert.match(await p.locator('#ebpol').innerText(), /只读|仅可查看/);
    assert.equal(await p.locator('[data-act="toVisit"]').count(), 0);
    await capture(p, '174-partner-profile');
    await p.locator('#ef').getByRole('button', { name: /事项库/ }).click();
    await p.locator('.pview.on[data-view="policy"] [data-detail]').first().waitFor();
    assert.equal(await p.evaluate(() => matches), 0);
  });
}
for (const method of ['关闭', '取消', 'Escape', '遮罩']) {
  test('#177 等待身份时' + method + '取消整次启动', async t => {
    const p = await login(t, 'liyang', method === '取消' ? 1280 : 1440);
    // 仅选择 HTTP 口令弹窗分支；全部数据仍在隔离 mock 页，监测是否误发登录或对话。
    await p.evaluate(() => {
      JKHttp.mode = () => 'http';
      window.calls = [];
      JKApi.auth.login = () => { calls.push('login'); throw Error('不应提交空口令'); };
      JKShell.send = () => { calls.push('send'); };
      JK_DEMO_SCRIPT = [{ title: '需切号', steps: [{ login: 'wangmin' }, { say: '测试' }] }];
    });
    await p.locator('#btn-demo').click();
    const dialog = p.getByRole('dialog');
    await dialog.locator('input').waitFor();
    if (method === '取消') {
      await dialog.getByRole('button', { name: '登录并切换' }).click();
      assert.match(await dialog.getByRole('alert').innerText(), /请输入口令/);
    }
    await p.clock.install();
    await p.clock.runFor(15000);
    assert.equal(await dialog.locator('input').inputValue(), '');
    assert.equal(await p.evaluate(() => JKDemo.state.on), false);
    if (method === '关闭' || method === '取消') await capture(p, '177-await-identity');
    if (method === 'Escape') await dialog.locator('input').press('Escape');
    else if (method === '遮罩') await p.locator('.mask-bg').click({ position: { x: 3, y: 95 } });
    else await dialog.getByRole('button', { name: method, exact: true }).click();
    await p.clock.runFor(15000);
    assert.deepEqual(await p.evaluate(() => [calls, JKDemo.state.i, JKDemo.state.on, JKOp.demo, JKShell.S.me.username]),
      [[], 0, false, false, 'liyang']);
    assert.equal(await p.locator('.demobar,.mask-bg,[role="dialog"]').count(), 0);
  });
}
for (const width of [1440, 1280]) {
  test('#216 一键演示开场可暂停、继续及单段播放 / ' + width, async t => {
    const p = await login(t, 'wangmin', width);
    await p.clock.install();
    // 保留真实开场；接两段仅切主题的虚拟画面，无模型或业务写入。
    await p.evaluate(() => {
      JK_DEMO_SCRIPT = [JK_DEMO_SCRIPT[0],
        { title: '第二段', steps: [{ theme: 'dark' }] }, { title: '第三段', steps: [{ theme: 'light' }] }];
    });
    await p.locator('#btn-demo').click();
    const bar = p.locator('.demobar');
    await bar.getByText(/这是经办人员/).waitFor();
    await bar.getByRole('button', { name: '暂停阅读' }).click();
    await p.clock.runFor(60000);
    assert.equal(await p.evaluate(() => JKDemo.state.i), 0);
    await capture(p, '216-paused');
    await bar.getByRole('button', { name: '继续播放' }).click();
    await bar.getByRole('button', { name: '下一段' }).click();
    await p.clock.runFor(60000);
    assert.deepEqual(await p.evaluate(() => [JKDemo.state.i, JKDemo.state.paused, JKShell.theme()]), [1, true, 'dark']);
    await bar.getByRole('button', { name: '退出' }).click();
    assert.equal(await bar.count(), 0);
  });
}
