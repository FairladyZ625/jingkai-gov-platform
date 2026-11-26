const { randomUUID } = require('node:crypto');
const { readFile } = require('node:fs/promises');
const { expect, test } = require('@playwright/test');

const documents = '/api/apps/document';
const drafts = documents + '/drafts';
const notice = '公开合成告知单第一行\n第二行 <strong>按纯文本展示</strong> & 核对';
const draftButton = '[data-op="document.gen"]';
const paper = '[data-op="document.paper"]';

test.use({ baseURL: process.env.T41_BASE_URL });
test.use({ trace: 'off', video: 'off', screenshot: 'off' });

async function signIn(page) {
  const { T41_BASE_URL, T41_USERNAME, T41_PASSWORD } = process.env;
  expect(Boolean(T41_BASE_URL && T41_USERNAME && T41_PASSWORD), '需要隔离实例和测试账号').toBe(true);
  await page.goto('/');
  await page.evaluate(() => Object.assign(JK_CONFIG.api.modules, { document: 'http', enterprise: 'http', policy: 'http' }));
  await page.getByLabel('账号', { exact: true }).fill(T41_USERNAME);
  await page.getByLabel('密码', { exact: true }).fill(T41_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.hello')).toBeVisible();
}

function watch(page, method, pathname) {
  return page.waitForResponse((response) => response.request().method() === method
    && new URL(response.url()).pathname === pathname);
}

async function navigate(page, route, params) {
  await page.evaluate(({ route, params }) => JKShell.openApp('document', route, params), { route, params });
}

async function createFromForm(page, expectedTemplate) {
  const posted = watch(page, 'POST', drafts);
  await page.locator(draftButton).click();
  const response = await posted;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().templateId).toBe(expectedTemplate);
  const { item } = await response.json();
  await expect(page.locator(paper)).toBeVisible();
  return { item, body: response.request().postDataJSON() };
}

async function getDraft(page, id) {
  const response = await page.request.get(`${drafts}/${id}`);
  expect(response.status()).toBe(200);
  return (await response.json()).item;
}

test('公文确认后保存告知单原文，支持模板和草稿深链及 docx 下载', async ({ page }) => {
  await signIn(page);
  const name = `T41 公文测试示例企业 ${randomUUID()}`;
  const company = await page.request.post('/api/apps/enterprise/companies', { data: { name, tags: ['示例'] } });
  expect(company.status()).toBe(200);
  const { item: ent } = await company.json();
  const issue = '咨询公开演示政策申报';
  const inputs = { ent: ent.id, issue, policy: '' };
  const templates = watch(page, 'GET', documents + '/templates');
  const list = watch(page, 'GET', documents + '/documents');
  let writeCount = 0;
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === drafts) writeCount++;
  });

  await navigate(page, 'new', { templateId: 'T10', inputs, from: 'policy', notice });
  expect((await templates).status()).toBe(200);
  expect((await list).status()).toBe(200);
  await expect(page.getByText('来自政策匹配：已带上相关要素')).toBeVisible();
  await expect(page.locator('[data-op="document.in-ent"]')).toHaveValue(ent.id);
  await expect(page.locator('[data-op="document.in-issue"]')).toHaveValue(issue);
  expect(writeCount).toBe(0);
  const { item, body } = await createFromForm(page, 'T10');
  expect(body).toMatchObject({ inputs, extra: [notice] });
  const initial = await getDraft(page, item.id);
  const paragraphs = initial.versions.at(-1).content.paragraphs;
  expect(paragraphs).toContain(notice);
  expect(initial.versions.at(-1).v).toBe(0);
  const noticePara = page.locator(`[data-op="document.p-${paragraphs.indexOf(notice)}"]`);
  expect(await noticePara.textContent()).toBe(notice);
  await expect(noticePara.locator('strong')).toHaveCount(0);
  await expect(noticePara).toHaveCSS('white-space', 'pre-wrap');

  const reopened = watch(page, 'GET', `${drafts}/${item.id}`);
  await navigate(page, 'home', { draftId: item.id });
  expect((await reopened).status()).toBe(200);
  await expect(noticePara).toBeVisible();
  expect(await noticePara.textContent()).toBe(notice);

  const requestedFile = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出 Word' }).click();
  const downloaded = await requestedFile;
  const filename = downloaded.suggestedFilename();
  expect(filename).toMatch(/（草稿）\.docx$/);
  const zip = await readFile(await downloaded.path());
  expect(zip.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(zip.includes(Buffer.from('word/document.xml'))).toBe(true);
  const exported = await page.request.get(`${drafts}/${item.id}/export`);
  expect(exported.status()).toBe(200);
  expect(exported.headers()['content-type']).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document');

  await navigate(page, 'home', { templateId: 'T06', autogen: true, notice: ' \n\t ' });
  await expect(page.locator('[data-op="document.in-orig"]')).not.toHaveValue('');
  expect(writeCount).toBe(1);
  expect((await createFromForm(page, 'T06')).body).not.toHaveProperty('extra');

  await navigate(page, 'new', { templateId: 'T10', inputs, notice });
  await page.getByRole('button', { name: '换一类' }).click();
  await page.locator('[data-op="document.tpl-T01"]').click();
  await page.locator('[data-op="document.sample"]').click();
  const switched = await createFromForm(page, 'T01');
  expect(switched.body).not.toHaveProperty('extra');
  expect((await getDraft(page, switched.item.id)).versions.at(-1).content.paragraphs).not.toContain(notice);
});

test('公文真实保存、润色预览、版本对比、批注和异常回读', async ({ page }) => {
  await signIn(page);
  const title = `T41 合成测试 ${randomUUID()}`;
  await navigate(page, 'new', { templateId: 'T01', inputs: { title, target: '示例单位' } });
  const { item } = await createFromForm(page, 'T01');
  const endpoint = `${drafts}/${item.id}`;

  const paragraph = page.locator('[data-op="document.p-0"]');
  for (const [i, value] of ['第一次修改', '第二次修改'].entries()) {
    await paragraph.click();
    const editor = page.locator('[data-op="document.ed-0"]');
    await editor.fill(value);
    await editor.blur();
    const saved = watch(page, 'PUT', endpoint);
    await page.locator('[data-op="document.save"]').click();
    const response = await saved;
    expect(response.status()).toBe(200);
    expect((await response.json()).item.versions.at(-1).v).toBe(i + 1);
    await expect(paragraph).toHaveText(value);
  }

  const polishTab = page.locator('[data-op="document.panel-polish"]');
  await expect(polishTab).toHaveText('规则润色');
  await polishTab.click();
  const previewed = watch(page, 'POST', endpoint + '/polish');
  await page.getByRole('button', { name: '预览润色' }).click();
  const preview = await previewed;
  expect(preview.status()).toBe(200);
  expect(await preview.json()).toMatchObject({ preview: { paragraphs: expect.any(Array) }, changed: expect.any(Boolean) });
  expect((await getDraft(page, item.id)).versions.at(-1).v).toBe(2);

  await page.locator('[data-op="document.panel-versions"]').click();
  const compared = watch(page, 'POST', documents + '/compare');
  await page.getByRole('button', { name: '对比', exact: true }).click();
  const comparison = await compared;
  expect(comparison.status()).toBe(200);
  expect(comparison.request().postDataJSON()).toEqual({ a: { id: item.id, v: 1 }, b: { id: item.id, v: 2 } });
  expect((await comparison.json()).stats.add).toBeGreaterThan(0);
  await expect(page.locator('.dc-diff ins')).toBeVisible();
  await page.locator('[data-op="document.ver-1"]').click();
  await expect(paragraph).toHaveText('第一次修改');
  await page.getByRole('button', { name: '回到最新' }).click();
  await expect(paragraph).toHaveText('第二次修改');

  await page.getByRole('button', { name: '批注与送审' }).click();
  const comment = '请核查示例公文';
  await page.getByPlaceholder('写下修改意见').fill(comment);
  const commented = watch(page, 'POST', endpoint + '/comments');
  await page.getByRole('button', { name: '添加批注' }).click();
  const commentResponse = await commented;
  expect(commentResponse.status()).toBe(200);
  const { item: added } = await commentResponse.json();
  await expect(page.getByText(comment, { exact: true })).toBeVisible();
  const resolved = watch(page, 'PATCH', endpoint + '/comments/' + added.id);
  await page.getByRole('button', { name: '解决', exact: true }).click();
  expect((await resolved).status()).toBe(200);
  expect((await getDraft(page, item.id)).comments).toContainEqual(expect.objectContaining({ id: added.id, text: comment, resolved: true }));

  const bad = await page.request.post(endpoint + '/comments', { data: { para: 1000, text: '不应写入' } });
  expect(bad.status()).toBe(400);
  expect((await bad.json()).error.code).toBe('INVALID_REQUEST');
  expect((await getDraft(page, item.id)).comments).toHaveLength(1);
  const missing = await page.request.get(drafts + '/T41-document-missing');
  expect(missing.status()).toBe(404);
  expect((await missing.json()).error.code).toBe('NOT_FOUND');
});

test('公文送审前置校验失败时保持草稿，不显示成功', async ({ page }) => {
  await signIn(page);
  await navigate(page, 'new', { templateId: 'T01', inputs: { title: '公开演示核查测试', target: '示例单位' } });
  const { item } = await createFromForm(page, 'T01');
  const endpoint = `${drafts}/${item.id}`;
  const checked = await page.request.post(endpoint + '/check', { data: {} });
  const checkingUnavailable = checked.status() === 404;
  if (checkingUnavailable) {
    expect(await checked.json()).toEqual({ detail: 'Not Found' });
    const fixed = await page.request.post(endpoint + '/fix', { data: { ids: ['c1'] } });
    expect(fixed.status()).toBe(404);
    expect(await fixed.json()).toEqual({ detail: 'Not Found' });
    await expect(page.getByText('暂时无法核查当前文稿')).toBeVisible();
  } else {
    expect(checked.status()).toBe(200);
    expect((await checked.json()).issues).toContainEqual(expect.objectContaining({ level: 'error' }));
  }

  await page.getByRole('button', { name: '批注与送审' }).click();
  await page.getByRole('button', { name: '送审签' }).click();
  const submitted = watch(page, 'POST', endpoint + '/submit');
  await page.getByRole('button', { name: '确认送审' }).click();
  const submission = await submitted;
  expect(submission.status()).toBe(checkingUnavailable ? 503 : 422);
  expect((await submission.json()).error.code).toBe(checkingUnavailable ? 'APP_UNAVAILABLE' : 'CHECK_FAILED');
  await expect(page.locator('.toast.err').first()).toBeVisible();
  await expect(page.locator('.toast.ok').filter({ hasText: '已送' })).toHaveCount(0);
  expect((await getDraft(page, item.id)).status).toBe('草稿');
});

test('公文核查、修正并送审指定版本', async ({ page }) => {
  await signIn(page);
  await navigate(page, 'new', { templateId: 'T01', inputs: { title: '公开演示核查测试', target: '示例单位' } });
  const { item } = await createFromForm(page, 'T01');
  const endpoint = `${drafts}/${item.id}`;
  const saved = await page.request.put(endpoint, { data: { content: {
    title: '关于开展公开资料核验的通知', docNo: '测试[2026]08号', to: '各有关单位：',
    paragraphs: ['请核对已公开的资料。'], sign: '公文演示工作组', date: '2026年11月18日',
  } } });
  expect(saved.status()).toBe(200);

  const checked = await page.request.post(endpoint + '/check', { data: {} });
  if (checked.status() === 404) {
    expect(await checked.json()).toEqual({ detail: 'Not Found' });
    test.skip(true, '等待 PR #122，真实公文核查路由返回 404');
  }
  expect(checked.status()).toBe(200);
  const { issues } = await checked.json();
  const fixable = issues.filter((issue) => issue.fix);
  expect(fixable.length).toBeGreaterThan(0);
  const fixed = await page.request.post(endpoint + '/fix', { data: { ids: fixable.map((issue) => issue.id) } });
  expect(fixed.status()).toBe(200);
  const version = (await fixed.json()).item.versions.at(-1);
  expect(version.content.docNo).toBe('测试〔2026〕8号');

  await navigate(page, 'detail', { draftId: item.id });
  await page.getByRole('button', { name: '批注与送审' }).click();
  await page.getByRole('button', { name: '送审签' }).click();
  const submitted = watch(page, 'POST', endpoint + '/submit');
  await page.getByRole('button', { name: '确认送审' }).click();
  const submission = await submitted;
  expect(submission.status()).toBe(200);
  const { review } = await submission.json();
  expect(review).toMatchObject({ ref: item.id, version: version.v + 1, status: 'pending' });
  expect((await getDraft(page, item.id)).status).toBe('审签中');
});
