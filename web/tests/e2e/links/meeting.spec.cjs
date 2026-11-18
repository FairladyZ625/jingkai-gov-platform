const { randomUUID } = require('node:crypto');
const path = require('node:path');
const { expect, test } = require('@playwright/test');

const meetings = '/api/apps/meeting/meetings';
const enterprise = '/api/apps/enterprise';
const jobs = '/api/v1/jobs';

test.use({ baseURL: process.env.T41_BASE_URL });
test.use({ trace: 'off', video: 'off', screenshot: 'off' });

async function signIn(page) {
  const { T41_BASE_URL, T41_USERNAME, T41_PASSWORD } = process.env;
  expect(Boolean(T41_BASE_URL && T41_USERNAME && T41_PASSWORD), '需要隔离实例和测试账号').toBe(true);
  await page.goto('/');
  await page.evaluate(() => Object.assign(JK_CONFIG.api.modules, { meeting: 'http', enterprise: 'http' }));
  await page.getByLabel('账号', { exact: true }).fill(T41_USERNAME);
  await page.getByLabel('密码', { exact: true }).fill(T41_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('.hello')).toBeVisible();
}

function watch(page, method, pathname) {
  return page.waitForResponse((response) => response.request().method() === method
    && new URL(response.url()).pathname === pathname);
}

test('会议录音经真实 HTTP 整理、登记企业诉求并回读', async ({ page }) => {
  await signIn(page);
  const name = `T41 会议测试示例企业 ${randomUUID()}`;
  const company = await page.request.post(enterprise + '/companies', {
    data: { name, short: name, tags: ['示例'] },
  });
  expect(company.status()).toBe(200);
  const { item: ent } = await company.json();
  const title = `T41 公开演示会议 ${randomUUID()}`;

  const listed = watch(page, 'GET', meetings);
  await page.evaluate(() => JKShell.openApp('meeting', 'all'));
  expect((await listed).status()).toBe(200);
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '上传录音', exact: true }).click();
  await (await chooser).setFiles(path.resolve(__dirname, '../../../../apps/meeting/samples/demo.webm'));
  const upload = page.getByRole('dialog').filter({ hasText: '登记这份录音' });
  await upload.locator('#ut').fill(title);
  await upload.locator('#up').fill(name);
  const created = watch(page, 'POST', meetings);
  const started = page.waitForResponse((response) => response.request().method() === 'POST'
    && new URL(response.url()).pathname.startsWith(meetings + '/')
    && new URL(response.url()).pathname.endsWith('/transcribe'));
  const polled = page.waitForResponse((response) => new URL(response.url()).pathname.startsWith(jobs + '/')
    && response.status() === 200);
  await upload.getByRole('button', { name: '上传并整理' }).click();

  const creation = await created;
  expect(creation.status()).toBe(201);
  expect(creation.request().headers()['content-type']).toMatch(/^multipart\/form-data; boundary=/);
  const { item: meeting } = await creation.json();
  expect(meeting).toMatchObject({ title, source: 'upload', participants: name.split(' '), file: 'demo.webm' });
  expect(meeting.size).toBeGreaterThan(0);

  const start = await started;
  expect(new URL(start.url()).pathname).toBe(`${meetings}/${meeting.id}/transcribe`);
  expect(start.status()).toBe(202);
  const { job } = await start.json();
  const poll = await polled;
  expect(new URL(poll.url()).pathname).toBe(`${jobs}/${job.id}`);
  expect((await poll.json()).job).toMatchObject({ id: job.id, ref: meeting.id });

  await page.getByRole('button', { name: '看纪要与待办' }).click();
  await expect(page.locator('[data-op="meeting.minutes"] h3')).toHaveText(title + '纪要');
  const detail = await page.request.get(`${meetings}/${meeting.id}`);
  expect(detail.status()).toBe(200);
  const { item, minutes } = await detail.json();
  expect(item).toMatchObject({ status: 'done', transcriptMode: 'demo' });
  expect(item.transcript.length).toBeGreaterThan(0);
  expect(minutes.body[0].refs.length).toBeGreaterThan(0);

  const edited = { ...minutes, body: minutes.body.map((p, i) => i === 0 ? { ...p, p: '核对公开演示纪要原话。' } : p) };
  const edit = await page.request.patch(`${meetings}/${meeting.id}`, { data: { minutes: edited } });
  expect(edit.status()).toBe(200);
  expect((await edit.json()).minutes.body[0].p).toBe(edited.body[0].p);

  const todos = item.todos;
  expect(todos.length).toBeGreaterThan(1);
  const [todo, unassigned] = todos;
  const { user } = await (await page.request.get('/api/v1/me')).json();
  const assign = await page.request.patch(`${meetings}/${meeting.id}`, {
    data: { todo: { id: todo.id, owner: user.id, due: '2026-12-01' } },
  });
  expect(assign.status()).toBe(200);
  const commit = await page.request.post(`${meetings}/${meeting.id}/todos/commit`, {
    data: { ids: [todo.id, unassigned.id] },
  });
  expect(commit.status()).toBe(200);
  expect(await commit.json()).toEqual({
    committed: [todo.id],
    skipped: [{ id: unassigned.id, reason: '缺少负责人、期限' }],
  });
  const afterEdits = await page.request.get(`${meetings}/${meeting.id}`);
  expect(afterEdits.status()).toBe(200);
  const persisted = await afterEdits.json();
  expect(persisted.minutes.body[0].p).toBe(edited.body[0].p);
  expect(persisted.item.todos[0]).toMatchObject({ id: todo.id, status: '已派发' });

  const before = await page.request.get(enterprise + '/issues', { params: { entId: ent.id } });
  expect(before.status()).toBe(200);
  expect((await before.json()).items).toEqual([]);

  await page.getByRole('button', { name: '关联企业诉求' }).click();
  const link = page.getByRole('dialog').filter({ hasText: '关联企业诉求' });
  const companies = link.getByLabel('企业', { exact: true });
  await expect(companies.locator('option').filter({ hasText: name })).toHaveCount(1);
  const missingEnt = 'T41-enterprise-missing';
  const missingMeeting = 'T41-meeting-missing';
  const endpoint = `${meetings}/${meeting.id}/link`;

  const missing = await page.request.post(`${meetings}/${missingMeeting}/link`, {
    data: { entId: ent.id, title: '会议不存在，禁止落库' },
  });
  expect(missing.status()).toBe(404);
  expect((await missing.json()).error.code).toBe('NOT_FOUND');

  // 模拟打开弹窗后企业失效，浏览器提交和企业回读仍走真实接口。
  await companies.evaluate((select, id) => select.add(new Option('已失效的企业', id)), missingEnt);
  await companies.selectOption(missingEnt);
  const failed = watch(page, 'POST', endpoint);
  await link.getByRole('button', { name: '登记到企业台账' }).click();
  const failure = await failed;
  expect(failure.status()).toBe(404);
  const { error } = await failure.json();
  expect(error.code).toBe('NOT_FOUND');
  await expect(page.locator('.toast.err')).toContainText(error.message);
  await expect(link).toBeVisible();
  await expect(page.getByText('已登记到企业台账', { exact: true })).toHaveCount(0);
  for (const entId of [ent.id, missingEnt]) {
    const read = await page.request.get(enterprise + '/issues', { params: { entId } });
    expect(read.status()).toBe(200);
    expect((await read.json()).items).toEqual([]);
  }

  await companies.selectOption(ent.id);
  const topic = await link.getByLabel('诉求', { exact: true }).inputValue();
  const linked = watch(page, 'POST', endpoint);
  await link.getByRole('button', { name: '登记到企业台账' }).click();
  const response = await linked;
  expect(response.status()).toBe(200);
  const expected = { entId: ent.id, title: `${topic}（${title}）` };
  expect(response.request().postDataJSON()).toEqual(expected);
  const { issue } = await response.json();
  expect(issue).toMatchObject({ ...expected, from: '会议' });

  const success = page.locator('.toast.ok').filter({ hasText: '已登记到企业台账' });
  await expect(success).toBeVisible();
  await success.getByRole('button', { name: '去看看' }).click();
  const issueRow = page.locator(`[data-view="enterprise"] [data-op="enterprise.issue-${issue.id}"]`);
  await expect(issueRow).toContainText(expected.title);
  const read = await page.request.get(enterprise + '/issues', { params: { entId: ent.id } });
  expect(read.status()).toBe(200);
  expect((await read.json()).items).toEqual([expect.objectContaining({ id: issue.id, ...expected, from: '会议' })]);
});
