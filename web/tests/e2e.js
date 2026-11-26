const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { expect, test, openLogin, login } = require('./workspace');

const fileEntry = pathToFileURL(path.resolve(__dirname, '../index.html')).href;

const panel = (page, id) => page.locator('.pview.on[data-view="' + id + '"]');
const reply = (page, text) => page.locator('#chatcol .msg.ai .txt').filter({ hasText: text }).first();
const caption = page => page.locator('.demo-caption');

const segments = [
  ['开场', async page => {
    await expect(page.locator('.hello')).toContainText('王敏');
    await expect(caption(page)).toContainText('王敏的工作台');
  }],
  ['政策兑现', async page => {
    await expect(reply(page, /项可进一步核对/)).toBeVisible({ timeout: 25_000 });
    await expect(reply(page, /政策参考清单已生成/)).toBeVisible({ timeout: 25_000 });
    await expect(panel(page, 'policy').locator('[data-op="policy.notice-text"]')).toHaveValue(/^1\. .+/m);
  }],
  ['企业走访', async page => {
    await expect(panel(page, 'enterprise').locator('[data-op="enterprise.profile"]')).toBeVisible();
    await expect(reply(page, /已写入 \d+ 条，变更已留痕/)).toBeVisible({ timeout: 25_000 });
  }],
  ['会议纪要', async page => {
    await expect(reply(page, /已整理：\d+ 段转写/)).toBeVisible({ timeout: 20_000 });
    await expect(reply(page, /已派发 \d+ 条/)).toBeVisible({ timeout: 25_000 });
  }],
  ['公文协作', async page => {
    await expect(reply(page, /第 1 版 → 第 2 版：新增/)).toBeVisible({ timeout: 35_000 });
    expect(await submittedDraft(page)).toMatchObject({ status: 'pending', assignee: '李阳' });
  }],
  ['知识库', async page => {
    await expect(page.locator('#chatcol .msg.ai .src a[title="官网原文"]').first())
      .toHaveAttribute('href', /^https:\/\//, { timeout: 20_000 });
    await expect(panel(page, 'kb').locator('[data-op="kb.answer"]')).toContainText('未找到依据', { timeout: 25_000 });
  }],
  ['技能中心', async page => {
    await expect(reply(page, /技能「.*」已发布/)).toBeVisible({ timeout: 25_000 });
    await expect(reply(page, /「.*」已运行/)).toBeVisible({ timeout: 25_000 });
  }],
  ['电脑操作', async page => {
    const wait = panel(page, 'computer').locator('[data-op="computer.wait"]');
    await expect(wait).toContainText('需要你输入验证码', { timeout: 25_000 });
    await expect(wait).toContainText(/停在「提交」前/, { timeout: 50_000 });
    await expect(reply(page, /提交申报，受理编号/)).toBeVisible({ timeout: 20_000 });
    await expect(reply(page, /已把《.*》存进知识库/)).toBeVisible({ timeout: 30_000 });
  }],
  ['审签', async page => {
    await expect(page.locator('.toast').filter({ hasText: '已切换为 李阳' })).toBeVisible({ timeout: 40_000 });
    await expect(page.locator('.toast').filter({ hasText: '已通过' })).toBeVisible();
    expect(await submittedDraft(page)).toMatchObject({ status: 'done', documentStatus: '已定稿' });
  }],
  ['外部协作者', async page => {
    const profile = panel(page, 'enterprise');
    await expect(profile.locator('[data-op="enterprise.profile"]')).toBeVisible({ timeout: 15_000 });
    expect(await page.evaluate(() => JKShell.S.me.username)).toBe('hejun');
    const contacts = profile.locator('#eptab .ent-kv').filter({ hasText: '联系人' });
    await expect(contacts).toContainText(/\d{3}\*{4}\d{4}/);
  }],
  ['管理后台', async page => {
    const admin = panel(page, 'admin');
    await expect(admin.locator('[data-tab="grants"].on')).toBeVisible();
    await expect(admin.locator('[data-tab="models"].on')).toBeVisible();
    await expect(admin.locator('.audit-row').first()).toBeVisible();
  }],
  ['浅色主题', async page => {
    await expect(caption(page)).toContainText('深色、浅色两套主题');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expect(caption(page)).toContainText('演示结束');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('.hello')).toContainText('王敏');
  }],
];

async function submittedDraft(page) {
  return page.evaluate(() => {
    const state = JKAPI.state();
    const draft = Object.values(state.drafts).find(d => !initialDraftIds.includes(d.id) && /数据券.*延期/.test(d.title));
    const review = draft && state.inbox.find(item => item.ref === draft.id);
    return review && { status: review.status, assignee: review.assignee, documentStatus: draft.status };
  });
}

test.describe.configure({ mode: 'parallel' });

for (const [index, [name, check]] of segments.entries()) {
  test(String(index + 1).padStart(2, '0') + ' ' + name, async ({ page }) => {
    if (index === 7) test.setTimeout(95_000);
    if (index === 11) await page.addInitScript(() => localStorage.setItem('jk4-theme2', 'dark'));
    await page.context().setOffline(true);
    await openLogin(page, fileEntry);
    await login(page);
    expect(await page.evaluate(() => JK_DEMO_SCRIPT.map(segment => segment.title))).toEqual(segments.map(([title]) => title));

    // 调用真实演示引擎。审签段先执行公文段，建立同一份待签文稿和审签单。
    await page.evaluate(index => {
      window.initialDraftIds = Object.keys(JKAPI.state().drafts);
      JK_DEMO_SCRIPT.splice(index + 1);
      if (index === 8) {
        for (const segment of JK_DEMO_SCRIPT.slice(5, 8)) segment.steps = [];
      }
      void JKDemo.start(index === 8 ? 4 : index);
    }, index);
    await check(page);
    await expect.poll(() => page.evaluate(() => ({ running: JKDemo.state.on, next: JKDemo.state.i })),
      { timeout: 35_000 }).toEqual({ running: false, next: index + 1 });
  });
}
