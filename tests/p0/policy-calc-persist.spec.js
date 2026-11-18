const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { test, expect } = require('@playwright/test');

test('对话往返后按 PI-03 手填年房租直接生成告知单', async ({ page }) => {
  test.setTimeout(50000);
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

  const other = await ask('查一下星河智驾');
  await page.locator('[data-op="nav.chat"]').click();
  const saved = await ask('帮我查一下书香里文化能申报哪些政策');
  await page.locator('[data-op="policy.next"]').click();
  const rent = page.locator('[data-camt="PI-03"]');
  const total = page.locator('[data-op="policy.total"]');
  await rent.fill('1');
  await rent.press('Tab');
  await expect(total).toHaveText(/5000\s*元/);

  await other.click();
  await expect(rent).toHaveCount(0);
  await saved.click();
  await expect(rent).toHaveValue('1');
  await expect(total).toHaveText(/5000\s*元/);
  await page.locator('[data-op="policy.to-notice"]').click();
  await expect(page.locator('#pn')).toHaveValue(/1\s*万元\s*×\s*50%\s*=\s*5000\s*元/);
});
