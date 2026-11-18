const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { test, expect } = require('@playwright/test');

test.setTimeout(50000);

const op = (page, name) => page.locator(`[data-op="${name}"]`);

async function openPolicyConversation(page) {
  const url = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
  await page.goto(url);
  await page.locator('.ql[data-u="wangmin"]').click();

  async function ask(question) {
    const input = page.locator('#chatcol textarea');
    await input.fill(question);
    await input.press('Enter');
    await expect(page.locator('#chatcol .pstate').last()).toHaveText('已完成', { timeout: 12000 });
    const id = await page.locator('[data-conv].on').getAttribute('data-conv');
    return page.locator(`[data-conv="${id}"]`);
  }

  const other = await ask('查一下纸鹿二号智驾');
  await page.locator('[data-op="nav.chat"]').click();
  const saved = await ask('帮我查一下书香里文化能申报哪些政策');
  return { other, saved };
}

async function editRent(page) {
  // #64 后 PI-03 为历史事项，默认不勾选；手动勾上后再试算。
  await page.locator('[data-pick="PI-03"]').check();
  await page.locator('[data-op="policy.next"]').click();
  const rent = page.locator('[data-camt="PI-03"]');
  const total = page.locator('[data-op="policy.total"]');
  await rent.fill('1');
  await rent.press('Tab');
  await expect(total).toHaveText(/5000\s*元/);
  return { rent, total };
}

test('对话往返后按 PI-03 手填年房租直接生成告知单', async ({ page }) => {
  const { other, saved } = await openPolicyConversation(page);
  const { rent, total } = await editRent(page);
  await other.click();
  await expect(rent).toHaveCount(0);
  await saved.click();
  await expect(rent).toHaveValue('1');
  await expect(total).toHaveText(/5000\s*元/);
  await page.locator('[data-op="policy.to-notice"]').click();
  await expect(page.locator('#pn')).toHaveValue(/1\s*万元\s*×\s*50%\s*=\s*5000\s*元/);
});

test('手动画像往返后仍是原画像，返回选对象可继续修改', async ({ page }) => {
  const { other, saved } = await openPolicyConversation(page);
  await op(page, 'policy.step-0').click();
  await op(page, 'policy.mode-manual').click();
  await op(page, 'policy.mtag-实体书店').click();
  const license = page.locator('[data-mlic="出版物经营许可证"]');
  await license.click();
  await op(page, 'policy.m-years').fill('3.5');
  await page.locator('[data-mamt="rent"]').fill('42');
  await op(page, 'policy.go').click();
  await expect(page.locator('#ps .q')).toContainText('企业（实体书店）');

  await other.click();
  await saved.click();
  await expect(page.locator('#ps .q')).toContainText('企业（实体书店）');
  await expect(page.locator('[data-pick="PI-03"]')).toBeVisible();
  await op(page, 'policy.step-0').click();
  await expect(op(page, 'policy.mode-manual')).toHaveClass(/\bon\b/);
  await expect(op(page, 'policy.mtag-实体书店')).toHaveClass(/\bon\b/);
  await expect(license).toHaveClass(/\bon\b/);
  await expect(op(page, 'policy.m-years')).toHaveValue('3.5');
  await expect(page.locator('[data-mamt="rent"]')).toHaveValue('42');
});

test('恢复试算期间提示等待，完成后才可生成含算式的告知单', async ({ page }) => {
  const { other, saved } = await openPolicyConversation(page);
  const { total } = await editRent(page);
  await other.click();
  await page.evaluate(() => {
    const calc = JKApi.policy.calc;
    JKApi.policy.calc = async (params) => {
      if (params.itemId === 'PI-03') await new Promise((resolve) => { window.finishPolicyCalc = resolve; });
      return calc(params);
    };
  });
  await saved.click();
  await expect.poll(() => page.evaluate(() => !!window.finishPolicyCalc)).toBe(true);
  const next = op(page, 'policy.next');
  // 旧实现会露出核对页，可以提前进入试算。
  if (await next.isVisible()) await next.click();
  const notice = op(page, 'policy.to-notice');
  await expect(notice).toBeDisabled();
  await expect(page.getByRole('status').filter({ hasText: '正在恢复试算' })).toBeVisible();
  await expect(page.locator('#pn')).toHaveCount(0);

  // 回退到核对页也无法越过正在恢复的试算。
  await op(page, 'policy.step-1').click();
  await expect(next).toBeDisabled();
  await page.evaluate(() => window.finishPolicyCalc());
  await next.click();
  await expect(total).toHaveText(/5000\s*元/);
  await notice.click();
  await expect(page.locator('#pn')).toHaveValue(/1\s*万元\s*×\s*50%\s*=\s*5000\s*元/);
});

for (const [tab, label] of [['items', '事项库'], ['docs', '政策文件']]) {
  test(`从${label}往返后保留试算步骤和手填金额`, async ({ page }) => {
    const { other, saved } = await openPolicyConversation(page);
    const { rent, total } = await editRent(page);
    const tabButton = op(page, `policy.tab-${tab}`);
    await tabButton.click();
    await other.click();
    await saved.click();
    await expect(tabButton).toHaveClass(/\bon\b/);
    await op(page, 'policy.tab-flow').click();
    await expect(op(page, 'policy.step-2')).toHaveClass(/\bon\b/);
    await expect(rent).toHaveValue('1');
    await expect(total).toHaveText(/5000\s*元/);
  });
}
