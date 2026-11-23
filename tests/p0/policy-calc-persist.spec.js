const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { test, expect } = require('@playwright/test');

test.setTimeout(50000);

const op = (page, name) => page.locator(`[data-op="${name}"]`);

async function openPolicyConversation(page) {
  const url = pathToFileURL(path.resolve(__dirname, '../../web/index.html')).href;
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

async function holdNextPolicyResponse(page, method, targetId) {
  await page.evaluate(({ method, targetId }) => {
    const original = JKApi.policy[method];
    JKApi.policy[method] = async (params) => {
      const id = method === 'match' ? params.entId : params.itemId;
      if (id !== targetId) return original(params);
      JKApi.policy[method] = original;
      const response = await original(params);
      await new Promise((resolve) => { window.releasePolicyResponse = resolve; });
      return response;
    };
  }, { method, targetId });
}

test('旧匹配晚于个人画像核对完成时保留新办理', async ({ page }) => {
  const { other, saved } = await openPolicyConversation(page);
  await editRent(page);
  await op(page, 'policy.tab-items').click();
  await other.click();
  await holdNextPolicyResponse(page, 'match', 'E001');
  await saved.click();
  await expect.poll(() => page.evaluate(() => !!window.releasePolicyResponse)).toBe(true);
  await op(page, 'policy.tab-flow').click();
  await op(page, 'policy.step-0').click();
  await op(page, 'policy.mode-manual').click();
  await page.locator('[data-mobj="个人"]').click();
  await op(page, 'policy.go').click();
  const heading = page.locator('#ps .q');
  await expect(heading).toContainText('个人');
  const selection = await op(page, 'policy.selection').innerText();
  await page.evaluate(() => window.releasePolicyResponse());
  await expect(heading).toContainText('个人');
  await expect(op(page, 'policy.selection')).toHaveText(selection);
  await expect(page.locator('[data-camt="PI-03"]')).toHaveCount(0);
});

test('慢重算中编辑告知单后立即切对话仍保留备注', async ({ page }) => {
  const { other, saved } = await openPolicyConversation(page);
  await editRent(page);
  await op(page, 'policy.to-notice').click();
  const notice = page.locator('#pn');
  await expect(notice).toHaveValue(/5000\s*元/);
  const edited = (await notice.inputValue()) + '\n备注：已核对房租';
  await other.click();
  await holdNextPolicyResponse(page, 'calc', 'PI-03');
  await saved.click();
  await expect.poll(() => page.evaluate(() => !!window.releasePolicyResponse)).toBe(true);
  await notice.fill(edited);
  await other.click();
  await page.evaluate(() => window.releasePolicyResponse());
  await saved.click();
  await expect(notice).toHaveValue(edited);
});

test('首次恢复匹配失败后再次返回仍保留告知单和手填房租', async ({ page }) => {
  const { other, saved } = await openPolicyConversation(page);
  const { rent, total } = await editRent(page);
  await op(page, 'policy.to-notice').click();
  const notice = page.locator('#pn');
  await expect(notice).toHaveValue(/1\s*万元\s*×\s*50%\s*=\s*5000\s*元/);
  const edited = (await notice.inputValue()) + '\n备注：首次返回前已核对房租';
  await notice.fill(edited);
  const items = op(page, 'policy.tab-items');
  await items.click();
  await other.click();

  const failure = '首次恢复匹配暂时失败';
  await page.evaluate(({ message, entId }) => {
    const match = JKApi.policy.match;
    JKApi.policy.match = (params) => {
      // 切出的企业档案也会调用匹配接口生成政策速览。
      if (params.entId !== entId) return match(params);
      JKApi.policy.match = match;
      return new Promise((_, reject) => {
        window.rejectPolicyRestore = () => reject(new Error(message));
      });
    };
  }, { message: failure, entId: 'E001' });
  await saved.click();
  await expect.poll(() => page.evaluate(() => !!window.rejectPolicyRestore)).toBe(true);
  const errors = await page.evaluate(async () => {
    const restoring = JKShell.S.mounted.policy.restoring;
    window.rejectPolicyRestore();
    await restoring;
    return [...document.querySelectorAll('.toasts .toast.err')].map((toast) => toast.textContent);
  });
  expect(errors).toContain(failure);
  await other.click();
  await saved.click();
  await expect(items).toHaveClass(/\bon\b/);
  await op(page, 'policy.tab-flow').click();
  await expect(op(page, 'policy.step-3'), '再次返回办理应恢复到告知单步骤').toHaveClass(/\bon\b/);
  await expect(notice).toHaveValue(edited);
  await op(page, 'policy.step-1').click();
  await expect(page.locator('[data-pick="PI-03"]')).toBeChecked();
  await op(page, 'policy.next').click();
  await expect(rent).toHaveValue('1');
  await expect(total).toHaveText(/5000\s*元/);
});

async function failNextPolicyEnterpriseList(page) {
  await page.evaluate(() => {
    const list = JKApi.enterprise.list;
    JKApi.enterprise.list = async (params) => {
      if (params?.sort !== 'name') return list(params);
      JKApi.enterprise.list = list;
      throw new Error('企业台账暂不可用');
    };
  });
}

test('首次恢复时台账列表失败，仍能将绑定企业交给公文', async ({ page, context }) => {
  await context.setOffline(true);
  const { other, saved } = await openPolicyConversation(page);
  await editRent(page);
  await op(page, 'policy.to-notice').click();
  await expect(page.locator('#pn')).toHaveValue(/5000\s*元/);
  await other.click();
  await failNextPolicyEnterpriseList(page);
  await saved.click();
  await expect(page.locator('#pn')).toHaveValue(/5000\s*元/);
  await op(page, 'policy.step-1').click();
  // 仍在第一次恢复：台账名未能载入，但已选企业不能退为泛称。
  await expect(page.locator('#ps .q')).toContainText('E001');
  await op(page, 'policy.next').click();
  await op(page, 'policy.to-notice').click();
  await op(page, 'policy.to-doc').click();
  await expect(op(page, 'document.in-ent')).toHaveValue('E001');
});

test('从台账切为手动画像后转公文，企业字段保持未选择', async ({ page, context }) => {
  await context.setOffline(true);
  await openPolicyConversation(page);
  await op(page, 'policy.step-0').click();
  await op(page, 'policy.mode-manual').click();
  await op(page, 'policy.mtag-实体书店').click();
  await op(page, 'policy.go').click();
  await editRent(page);
  await op(page, 'policy.to-notice').click();
  await op(page, 'policy.to-doc').click();
  const enterprise = op(page, 'document.in-ent');
  await expect(enterprise.locator('option[value="E001"]')).toHaveCount(1);
  await expect(enterprise).toHaveValue('');
});

test('台账列表短暂失败后再次往返仍保留企业、草稿和房租', async ({ page, context }) => {
  await context.setOffline(true);
  const { other, saved } = await openPolicyConversation(page);
  const { rent, total } = await editRent(page);
  await op(page, 'policy.to-notice').click();
  const notice = page.locator('#pn');
  await expect(notice).toHaveValue(/5000\s*元/);
  const draft = (await notice.inputValue()) + '\n备注：房租已复核';
  await other.click();
  await failNextPolicyEnterpriseList(page);
  await holdNextPolicyResponse(page, 'calc', 'PI-03');
  await saved.click();
  await expect.poll(() => page.evaluate(() => !!window.releasePolicyResponse)).toBe(true);
  await notice.fill(draft);
  await other.click();
  await page.evaluate(() => window.releasePolicyResponse());
  await saved.click();

  await expect(notice).toHaveValue(draft);
  await op(page, 'policy.step-1').click();
  await expect(page.locator('#ps .q')).toContainText('书香里文化');
  await expect(page.locator('[data-pick="PI-03"]')).toBeChecked();
  await op(page, 'policy.next').click();
  await expect(rent).toHaveValue('1');
  await expect(total).toHaveText(/5000\s*元/);
});
