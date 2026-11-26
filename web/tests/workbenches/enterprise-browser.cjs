const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chromium, expect } = require('@playwright/test');
const { join } = require('node:path');
const { mkdir } = require('node:fs/promises');
const { pathToFileURL } = require('node:url');
const entry = pathToFileURL(join(__dirname, '../../index.html')).href;

async function setup(t, width = 1280, user = 'wangmin') {
  const browser = await chromium.launch(process.env.PLAYWRIGHT_CHROME_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROME_PATH } : {});
  t.after(() => browser.close());
  const context = await browser.newContext({ viewport: { width, height: 900 }, offline: true });
  const page = await context.newPage(); page.setDefaultTimeout(10000);
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  t.after(() => assert.deepEqual(errors, []));
  await page.goto(entry);
  await page.locator(`[data-u="${user}"]`).click();
  await page.locator('#rail [data-workbench="enterprise"]').click();
  await expect(page.locator('.wb-enterprise [data-view="overview"]')).toBeVisible();
  return page;
}

test('企业档案、走访和诉求形成同一条可持续办理的记录', { timeout: 90000 }, async t => {
  const page = await setup(t), wb = page.locator('.wb-enterprise');
  await page.evaluate(() => JKShell.openApp('enterprise', 'board'));
  await page.locator('#rail [data-workbench="enterprise"]').click();
  await wb.getByRole('button', { name: '企业档案', exact: true }).click();
  await wb.getByRole('button', { name: '新增企业', exact: true }).click();
  await wb.getByLabel('企业全称').fill('工作台流程演示企业');
  await wb.getByLabel('企业简称').fill('流程演示');
  await wb.getByLabel('所属行业').fill('软件服务');
  await wb.getByRole('button', { name: '保存企业档案', exact: true }).click();
  await expect(wb.getByRole('heading', { name: '工作台流程演示企业', exact: true })).toBeVisible();
  const company = await page.evaluate(async () => (await JKApi.enterprise.list({ q: '工作台流程演示企业' })).items[0]);
  assert.ok(company.id);
  await wb.getByRole('button', { name: '记录联系或走访', exact: true }).click();
  await wb.getByLabel('联系类型').selectOption('电话联系');
  await wb.getByLabel('记录内容').fill('企业咨询办公空间需求，需要下周沟通可用房源。');
  await wb.getByRole('button', { name: '保存联系记录', exact: true }).click();
  await expect(wb.getByText('企业咨询办公空间需求，需要下周沟通可用房源。', { exact: true })).toBeVisible();
  const detail = await page.evaluate(id => JKApi.enterprise.get(id), company.id);
  assert.ok(detail.visits.some(v => v.notes.includes('办公空间需求') && v.type === '电话联系'));
  await wb.getByRole('button', { name: '登记诉求', exact: true }).click();
  await wb.getByLabel('诉求内容').fill('协助寻找办公空间');
  await wb.getByLabel('诉求来源').selectOption('电话');
  await wb.getByRole('button', { name: '保存诉求', exact: true }).click();
  await expect(wb.getByRole('heading', { name: '协助寻找办公空间', exact: true })).toBeVisible();
  await expect(wb.locator('[data-issue-status]')).toHaveText('待分派');
  await wb.getByLabel('负责人').fill('演示经办人');
  await wb.getByLabel('办理期限').fill('2030-12-01');
  await wb.getByLabel('办理状态').selectOption('办理中');
  await wb.getByLabel('下一步安排').fill('核对可用房源清单');
  await wb.getByLabel('本次进展与依据').fill('已电话确认面积和交通需求');
  await wb.getByRole('button', { name: '保存办理进展', exact: true }).click();
  await expect(wb.locator('.ew-notice')).toContainText('已保存');
  await page.reload();
  await expect(page.locator('.wb-enterprise').getByLabel('负责人')).toHaveValue('演示经办人');
  const result = await page.evaluate(async id => ({ list: await JKApi.enterprise.issues({ entId: id }), detail: await JKApi.enterprise.get(id) }), company.id);
  const issue = result.list.items.find(i => i.title === '协助寻找办公空间');
  assert.equal(issue.due, '2030-12-01'); assert.equal(issue.status, '办理中');
  assert.equal(result.detail.issues.find(i => i.id === issue.id).next, '核对可用房源清单');
  assert.ok(issue.steps.some(s => s[1].includes('已电话确认面积和交通需求')));
  await page.locator('.wb-enterprise').getByRole('button', { name: '诉求看板', exact: true }).click();
  await expect(page.locator('[data-column="办理中"]').getByText('协助寻找办公空间', { exact: true })).toBeVisible();
  await page.evaluate(() => JKShell.openApp('enterprise', 'board'));
  await expect(page.locator('.pview.on')).toContainText('协助寻找办公空间');
});

test('概览数字对应筛选结果，错误可重试，只读身份不提供写入口', { timeout: 60000 }, async t => {
  const page = await setup(t);
  const expected = await page.evaluate(async () => (await JKApi.enterprise.issues()).items.filter(i => i.status === '待分派').length);
  await expect(page.locator('[data-metric="pending"] strong')).toHaveText(String(expected));
  await page.locator('[data-metric="pending"]').click();
  await expect(page.locator('.wb-enterprise [data-issue-card]')).toHaveCount(expected);
  await page.evaluate(() => {
    window.restoreEnterpriseList = JKApi.enterprise.list;
    JKApi.enterprise.list = async () => { throw { message: '企业服务暂不可用' }; };
    JKWorkbench.open('enterprise', { recordId: 'companies' });
  });
  await expect(page.locator('.wb-enterprise [role="alert"]')).toContainText('企业服务暂不可用');
  await page.evaluate(() => { JKApi.enterprise.list = window.restoreEnterpriseList; });
  await page.locator('.wb-enterprise').getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('.wb-enterprise [data-company-row]').first()).toBeVisible();
  await page.evaluate(() => JKShell.switchUser('hejun'));
  await page.locator('#rail [data-workbench="enterprise"]').click();
  await expect(page.locator('.wb-enterprise [data-view="overview"]')).toBeVisible();
  await expect(page.locator('.wb-enterprise [data-write]')).toHaveCount(0);
  await page.locator('.wb-enterprise').getByRole('button', { name: '企业档案', exact: true }).click();
  await page.locator('.wb-enterprise [data-company-row]').first().click();
  await expect(page.locator('.wb-enterprise [data-write]')).toHaveCount(0);
});

for (const width of [1440, 1280, 390]) {
  test(`企业工作台 ${width}px 导航、看板和布局`, { timeout: 45000 }, async t => {
    const page = await setup(t, width);
    await page.locator('.wb-enterprise').getByRole('button', { name: '诉求看板', exact: true }).click();
    await expect(page.locator('.wb-enterprise [data-column]')).toHaveCount(4);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (process.env.WORKBENCH_SCREENSHOTS) {
      await mkdir(process.env.WORKBENCH_SCREENSHOTS, { recursive: true });
      await page.screenshot({ path: join(process.env.WORKBENCH_SCREENSHOTS, `enterprise-${width}.png`) });
    }
    await page.locator('.wb-enterprise').getByRole('button', { name: '联系与走访', exact: true }).click();
    await expect(page.locator('.wb-enterprise').getByLabel('选择企业')).toBeVisible();
  });
}

test('工作台保存后原已打开应用重新读取诉求，不保留旧看板缓存', { timeout: 60000 }, async t => {
  const page = await setup(t);
  const issue = await page.evaluate(async () => (await JKApi.enterprise.createIssue({ entId: 'E001', title: '跨入口跟进示例', owner: '原办理员' })).item);
  await page.evaluate(() => JKShell.openApp('enterprise', 'board'));
  await expect(page.locator('.pview.on')).toContainText('跨入口跟进示例');
  await page.evaluate(id => JKWorkbench.open('enterprise', { recordId: 'issue?id=' + id }), issue.id);
  await page.locator('.wb-enterprise').getByLabel('办理状态').selectOption('已办结');
  await page.locator('.wb-enterprise').getByLabel('本次进展与依据').fill('已核实完成服务');
  await page.locator('.wb-enterprise').getByRole('button', { name: '保存办理进展' }).click();
  await expect(page.locator('.wb-enterprise .ew-notice')).toContainText('已保存');
  await page.evaluate(() => JKShell.openApp('enterprise', 'board'));
  const card = page.locator('.pview.on [data-bissue="' + issue.id + '"]');
  await expect(card).toBeVisible();
  await expect(card.locator('..')).toContainText('已办结');
});

test('空数据不造统计，重复联系记录与编辑档案在当前页面更新', { timeout: 60000 }, async t => {
  const page = await setup(t);
  const company = await page.evaluate(async () => (await JKApi.enterprise.create({ name: '连续联系演示企业', opAddr: '演示路1号' })).item);
  await page.evaluate(id => JKWorkbench.open('enterprise', { recordId: 'visits?company=' + id }), company.id);
  for (const notes of ['第一次电话沟通', '第二次现场补充']) {
    const wb = page.locator('.wb-enterprise');
    await wb.getByRole('button', { name: '记录联系或走访', exact: true }).click();
    await wb.getByLabel('记录内容').fill(notes);
    await wb.getByRole('button', { name: '保存联系记录', exact: true }).click();
    await expect(wb.getByText(notes, { exact: true })).toBeVisible();
  }
  await page.evaluate(id => JKWorkbench.open('enterprise', { recordId: 'company?id=' + id }), company.id);
  const wb = page.locator('.wb-enterprise');
  await wb.getByRole('button', { name: '编辑企业资料', exact: true }).click();
  await wb.getByLabel('经营地址').fill('演示路2号');
  await wb.getByRole('button', { name: '保存企业档案', exact: true }).click();
  await expect(wb.getByText('演示路2号', { exact: true })).toBeVisible();
  await page.evaluate(() => {
    JKApi.enterprise.list = async () => ({ items: [] });
    JKApi.enterprise.issues = async () => ({ items: [] });
    JKWorkbench.open('enterprise', { recordId: 'overview' });
  });
  await expect(wb.locator('[data-metric] strong')).toHaveText(['0', '0', '0', '0']);
  await expect(wb.locator('[data-issue-card]')).toHaveCount(0);
});

test('HTTP兼容联系人字段按服务端脱敏值展示', { timeout: 45000 }, async t => {
  const page = await setup(t);
  await page.evaluate(() => {
    const get = JKApi.enterprise.get;
    JKApi.enterprise.get = async id => {
      const r = await get(id);
      return { ...r, item: { ...r.item, contacts: [], contact: 'HTTP联系人', phone: '138****1234' } };
    };
    JKWorkbench.open('enterprise', { recordId: 'company?id=E001' });
  });
  await expect(page.locator('.wb-enterprise .ew-contacts')).toContainText('HTTP联系人');
  await expect(page.locator('.wb-enterprise .ew-contacts')).toContainText('138****1234');
});

test('返回对话时原已打开应用显示已更新的诉求状态', { timeout: 60000 }, async t => {
  const page = await setup(t);
  const issue = await page.evaluate(async () => (await JKApi.enterprise.createIssue({ entId: 'E001', title: '跨入口跟进示例', owner: '原办理员' })).item);
  await page.evaluate(() => JKShell.openApp('enterprise', 'board'));
  await expect(page.locator('.pview.on')).toContainText('跨入口跟进示例');
  await page.evaluate(id => JKWorkbench.open('enterprise', { recordId: 'issue?id=' + id }), issue.id);
  await page.locator('.wb-enterprise').getByLabel('办理状态').selectOption('已办结');
  await page.locator('.wb-enterprise').getByLabel('本次进展与依据').fill('已核实完成服务');
  await page.locator('.wb-enterprise').getByRole('button', { name: '保存办理进展' }).click();
  await expect(page.locator('.wb-enterprise .ew-notice')).toContainText('已保存');
  await page.locator('[data-wb-chat]').click();
  const card = page.locator('.pview.on [data-bissue="' + issue.id + '"]');
  await expect(card).toBeVisible();
  await expect(card.locator('..')).toContainText('已办结');
});
test('补充进展和编辑档案仅提交实际改动，保留其他经办人已保存的字段', { timeout: 45000 }, async t => {
  const page = await setup(t);
  const issueId = await page.evaluate(async () => {
    const item = (await JKApi.enterprise.createIssue({ entId: 'E001', title: '并发办理验证', owner: '原负责人' })).item;
    JKWorkbench.open('enterprise', { recordId: 'issue?id=' + item.id }); return item.id;
  });
  await expect(page.getByLabel('负责人', { exact: true })).toHaveValue('原负责人');
  await page.evaluate(id => JKApi.enterprise.patchIssue(id, { owner: '新负责人', status: '已办结', next: '办结归档', due: '2030-12-12' }), issueId);
  await page.getByLabel('本次进展与依据').fill('补记之前的电话沟通');
  await page.getByRole('button', { name: '保存办理进展', exact: true }).click();
  await expect(page.locator('.ew-notice')).toContainText('已保存');
  await expect(page.getByLabel('负责人', { exact: true })).toHaveValue('新负责人');
  await expect(page.getByLabel('办理状态')).toHaveValue('已办结');
  await expect(page.getByLabel('下一步安排')).toHaveValue('办结归档');
  await expect(page.getByLabel('办理期限')).toHaveValue('2030-12-12');
  await page.evaluate(() => JKWorkbench.open('enterprise', { recordId: 'company?id=E001' }));
  await page.getByRole('button', { name: '编辑企业资料', exact: true }).click();
  await page.getByLabel('企业简称').fill('更新简称');
  await page.evaluate(() => JKApi.enterprise.patch('E001', { industry: '他人更新的行业', employees: 123 }));
  await page.getByRole('button', { name: '保存企业档案', exact: true }).click();
  await expect(page.locator('.ew-profile')).toContainText('123');
  const company = await page.evaluate(async () => (await JKApi.enterprise.get('E001')).item);
  assert.equal(company.industry, '他人更新的行业'); assert.equal(company.short, '更新简称');
});
