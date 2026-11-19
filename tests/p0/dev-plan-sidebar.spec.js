const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { test, expect } = require('@playwright/test');

const entry = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const accounts = { wangmin: '王敏', liyang: '李阳', admin: '张磊', hejun: '何军' };

for (const [account, name] of Object.entries(accounts)) {
  for (const enabled of [false, true]) {
    test(`${name}的侧栏：${enabled ? '显式开启开发计划' : '默认隐藏开发计划'}`, async ({ page, context }) => {
      await context.setOffline(true);
      await page.goto(entry);
      const login = page.locator(`.ql[data-u="${account}"]`);
      await expect(login).toBeVisible();
      // 默认场景不覆写任何配置；开启场景在真实外壳首次渲染前切换。
      if (enabled) await page.evaluate(() => { window.JK_CONFIG.showDevPlan = true; });
      await login.click();

      const sidebar = page.locator('.side-foot');
      await expect(sidebar.getByRole('button', { name: /一键演示/ })).toBeVisible();
      const profile = sidebar.locator('#btn-me .nm');
      await expect(profile).toHaveText(name);
      const plan = sidebar.getByRole('link', { name: /开发计划/ });
      if (enabled) {
        await expect(plan).toBeVisible();
        const [popup] = await Promise.all([page.waitForEvent('popup'), plan.click()]);
        await expect(popup).toHaveURL(new URL('plan.html', entry).href);
        await expect(popup).toHaveTitle(/开发计划/);
        await popup.close();
      } else {
        await expect(plan).toHaveCount(0);
      }
      await profile.click();
      await expect(page.getByText('个人设置', { exact: true })).toBeVisible();
    });
  }
}
