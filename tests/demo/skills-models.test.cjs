const assert = require('node:assert/strict');
const path = require('node:path');
const { test } = require('node:test');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const entry = pathToFileURL(path.resolve(__dirname, '../../prototype/v4/index.html')).href;
const approvalHint = '本地端点尚未获准，请先配置机密数据审批地址';
const models = [
  { id: 'auto', name: '自动选择', local: false },
  { id: 'local', name: '局内模型', local: false, disabled: true, disabledReason: approvalHint },
  { id: 'acceptance-local', name: '局内模型（按模型名称）', local: false, disabled: true, disabledReason: approvalHint },
  { id: 'cloud', name: '云端模型', local: false },
];

async function withEditor(width, run) {
  const browser = await chromium.launch({ args: ['--allow-file-access-from-files'] });
  try {
    const page = await browser.newPage({ viewport: { width, height: 900 }, offline: true });
    page.setDefaultTimeout(6000);
    await page.addInitScript(() => localStorage.setItem('jk4-theme2', 'light'));
    await page.goto(entry);
    await page.click('[data-u="wangmin"]');
    await page.locator('#btn-demo').waitFor();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
    await run(page);
  } finally {
    await browser.close();
  }
}

async function setup(page, { draftModel = 'auto', approved = false } = {}) {
  const catalog = approved ? [...models, { id: 'approved-local', name: '已审批内网模型', local: true }] : models;
  await page.evaluate(({ catalog, draftModel }) => {
    const options = JKApi.skills.options;
    JKApi.skills.options = async () => ({ ...await options(), models: catalog });
    const draft = JKApi.skills.draft;
    JKApi.skills.draft = async (text) => {
      const response = await draft(text);
      response.draft.spec.model = draftModel;
      response.draft.questions = ['只用本地模型'];
      return response;
    };
  }, { catalog, draftModel });
}

async function openEditor(page) {
  await page.evaluate(() => JKShell.openApp('skills'));
  return page.locator('.pview.on[data-view="skills"]');
}

async function startDraft(panel) {
  await panel.locator('[data-act="new"]').click();
  await panel.locator('[data-desc]').fill('核对数据券申请材料');
  await panel.locator('[data-draft]').click();
  await panel.locator('[data-k="model"]').waitFor({ state: 'attached' });
}

test('新建技能无法选未审批的本地 ID 或别名，草稿须显式换用可用模型', async () => {
  await withEditor(1440, async (page) => {
    await setup(page, { draftModel: 'acceptance-local' });
    const panel = await openEditor(page);
    await startDraft(panel);
    assert.equal(await panel.getByRole('button', { name: '只用本地模型' }).isDisabled(), true);
    await panel.getByText('请在更多设置中选择可用模型。', { exact: false }).waitFor();
    const before = await page.evaluate(async () => (await JKApi.skills.list({ mine: 1 })).items.length);
    await panel.locator('[data-next]').click();
    assert.equal(await page.evaluate(async () => (await JKApi.skills.list({ mine: 1 })).items.length), before);

    const select = panel.getByRole('combobox', { name: '用哪个模型' });
    assert.equal(await select.inputValue(), 'acceptance-local');
    assert.deepEqual(await select.locator('option:disabled').evaluateAll(options => options.map(o => o.value)), ['local', 'acceptance-local']);
    await select.selectOption('cloud');
    assert.equal(await select.inputValue(), 'cloud');
    await panel.locator('[data-next]').click();
    await panel.locator('[data-trial]').waitFor();
    const created = await page.evaluate(async () => (await JKApi.skills.list({ mine: 1 })).items[0]);
    assert.equal(created.spec.model, 'cloud');
  });
});

test('起草快捷项使用当前已获准内网模型', async () => {
  await withEditor(1440, async (page) => {
    await setup(page, { approved: true });
    const panel = await openEditor(page);
    await startDraft(panel);
    await panel.getByRole('button', { name: '只用本地模型' }).click();
    await panel.locator('[data-adv] > summary').click();
    const select = panel.getByRole('combobox', { name: '用哪个模型' });
    assert.equal(await select.inputValue(), 'approved-local');
    assert.match(await select.locator('option:checked').textContent(), /数据不出局/);
    await panel.locator('[data-next]').click();
    await panel.locator('[data-trial]').waitFor();
    const created = await page.evaluate(async () => (await JKApi.skills.list({ mine: 1 })).items[0]);
    assert.equal(created.spec.model, 'approved-local');
  });
});

for (const { width, legacy, published } of [
  { width: 1440, legacy: 'local', published: true },
  { width: 1280, legacy: 'acceptance-local', published: true },
  { width: 1280, legacy: '历版模型 "内网" & 审核', published: false },
]) {
  test(`编辑${published ? '已发布技能' : '草稿'}保留原模型值 ${legacy}`, async () => {
    await withEditor(width, async (page) => {
      await setup(page);
      const id = await page.evaluate(async ({ legacy, published }) => {
        const { draft } = await JKApi.skills.draft('核对数据券申请材料');
        const { item } = await JKApi.skills.create({ ...draft, name: '申请材料核对', spec: { ...draft.spec, model: legacy } });
        if (published) await JKApi.skills.publish(item.id, { scope: 'private' });
        return item.id;
      }, { legacy, published });
      const panel = await openEditor(page);
      await panel.getByRole('button', { name: /^我的/ }).click();
      await panel.locator(`[data-edit="${id}"]`).click();
      const hint = panel.getByText('保存其他修改时会保留原模型。', { exact: false });
      await hint.waitFor();
      assert.match(await hint.textContent(), published ? /机密数据审批地址/ : /检查模型配置/);
      await panel.locator('[data-k="summary"]').fill('核对材料及缺项');
      await panel.locator('[data-fmt="表格"]').click();
      await panel.locator('[data-adv] > summary').click();
      const select = panel.getByRole('combobox', { name: '用哪个模型' });
      assert.equal(await select.inputValue(), legacy);
      assert.equal(await select.locator('option:checked').isDisabled(), true);
      if (published && process.env.SKILLS_MODEL_SCREENSHOTS) {
        await select.scrollIntoViewIfNeeded();
        await page.screenshot({ path: path.join(process.env.SKILLS_MODEL_SCREENSHOTS, `skills-model-${width}-light.png`) });
      }

      await panel.locator('[data-next]').click();
      await panel.locator('[data-trial]').waitFor();
      if (published) {
        await panel.locator('[data-next]').click();
        await panel.locator('[data-save]').click();
        await panel.locator('[data-dtab="ver"].on').waitFor();
      }
      const { item } = await page.evaluate(id => JKApi.skills.get(id), id);
      if (published) {
        assert.equal(item.versions.length, 3);
        assert.equal(item.versions.at(-1).spec.model, legacy);
      }
      assert.equal(item.spec.model, legacy);
      assert.equal(item.summary, '核对材料及缺项');
      assert.equal(item.spec.output.format, '表格');
    });
  });
}
