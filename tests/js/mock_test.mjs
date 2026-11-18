// 浏览器假数据服务的场景测试；由 js-tests 作业直接调起，本机 node tests/js/mock_test.mjs。
import assert from 'node:assert/strict';
import { installMock, toCsv } from '../../core/sdk/js/mock/index.js';

const BASE = 'http://mock.local';
const USERS = {
  sampleoperator: { id: 'sampleoperator', name: '办理员', roles: ['sampleoperator'], isAdmin: false },
  'samplereviewer': { id: 'samplereviewer', name: '审核员', roles: ['samplereviewer'], isAdmin: false },
};
let loggedIn = USERS.sampleoperator;

async function passthrough(input) {
  const path = new URL(String(input), BASE).pathname;
  if (path === '/api/me') return Response.json(loggedIn);
  return new Response('not found', { status: 404 });
}

function install(scenario = 'normal', delay = 10) {
  loggedIn = USERS.sampleoperator;
  return installMock({ scenario, fetch: passthrough, base: BASE, delay });
}

const app = (path) => `${BASE}/api/apps/demo-flow${path}`;
const call = (path, init) => fetch(app(path), init);
const post = (path, body = {}) => call(path, { method: 'POST', body: JSON.stringify(body) });
const put = (path, body = {}) => call(path, { method: 'PUT', body: JSON.stringify(body) });

async function create(mock, title = '示例记录') {
  const response = await post('/records', { project: 'sample-project', title, content: '示例内容' });
  assert.equal(response.status, 201);
  return response.json();
}

async function withMock(scenario, run, delay = 10) {
  const mock = install(scenario, delay);
  try {
    await run(mock);
  } finally {
    mock.restore();
  }
}

await withMock('normal', async (mock) => {
  const record = await create(mock);
  assert.equal(record.status, 'draft');
  assert.equal(record.version, 1);
  assert.equal(record.data.title, '示例记录');

  const review = await (await post(`/records/${record.id}/submit`)).json();
  assert.equal(review.status, 'pending');

  mock.user('samplereviewer');
  const todo = await (await call('/reviews')).json();
  assert.equal(todo.todo.length, 1);
  assert.equal(todo.todo[0].id, review.id);

  const decided = await post(`/reviews/${review.id}/decisions`, { version: 1, decision: 'confirm' });
  assert.equal(decided.status, 200);
  assert.equal((await decided.json()).status, 'confirmed');

  const exported = await call(`/records/${record.id}/export`);
  assert.equal(exported.status, 200);
  const csv = await exported.text();
  assert.match(csv, /示例记录/);
  assert.match(csv, /samplereviewer/);

  const artifacts = await (await call('/artifacts?project=sample-project')).json();
  assert.deepEqual(artifacts.items.map((item) => item.recordId), [record.id]);
});

await withMock('normal', async (mock) => {
  // 自定义字段不再被模板 schema 拦住：保存、改版、提交确认、导出都原样带字段。
  const created = await post('/records', {
    project: 'sample-project', workpiece: 'W-001', seam: 'S-3', undercut: 1.2,
  });
  assert.equal(created.status, 201);
  const custom = await created.json();
  assert.deepEqual(custom.data, { workpiece: 'W-001', seam: 'S-3', undercut: 1.2 });

  const v1 = await post('/records', {
    project: 'sample-project', type: 'inspection', data: { result: '演示' },
  });
  assert.deepEqual((await v1.json()).data, { result: '演示' });

  const updated = await put(`/records/${custom.id}`, {
    baseVersion: 1, workpiece: 'W-002', porosity: 0.4,
  });
  assert.equal(updated.status, 200);
  assert.deepEqual((await updated.json()).data, {
    workpiece: 'W-002', seam: 'S-3', undercut: 1.2, porosity: 0.4,
  });

  const review = await (await post(`/records/${custom.id}/submit`)).json();
  mock.user('samplereviewer');
  const decided = await post(`/reviews/${review.id}/decisions`, { version: 2, decision: 'confirm' });
  assert.equal(decided.status, 200);

  const exported = await call(`/records/${custom.id}/export`);
  assert.equal(exported.status, 200);
  const csv = await exported.text();
  assert.match(csv, /^workpiece,W-002$/m);
  assert.match(csv, /^porosity,0\.4$/m);

  const missingProject = await post('/records', { workpiece: 'W-003' });
  assert.equal(missingProject.status, 422);
});

await withMock('forbidden', async () => {
  const denied = await post('/records', { project: 'sample-project', title: '观察员不能写' });
  assert.equal(denied.status, 403);
  assert.equal((await denied.json()).action, 'operate');
  assert.equal((await call('/records')).status, 200);
});

await withMock('failure', async () => {
  const failed = await post('/records', { project: 'sample-project', title: '会失败' });
  assert.equal(failed.status, 500);
  assert.equal((await failed.json()).error.code, 'internal_error');
});

await withMock('conflict', async () => {
  const record = await create();
  const conflict = await put(`/records/${record.id}`, { baseVersion: 1, title: '并发修改' });
  assert.equal(conflict.status, 409);
  const body = await conflict.json();
  assert.equal(body.error.code, 'version_conflict');
  assert.equal(body.error.currentVersion, 2);

  const latest = await (await call(`/records/${record.id}`)).json();
  assert.equal(latest.version, 2);
  const retry = await put(`/records/${record.id}`, { baseVersion: 2, title: '重新保存' });
  assert.equal(retry.status, 200);
  assert.equal((await retry.json()).version, 3);
});

await withMock('slow', async () => {
  const started = Date.now();
  assert.equal((await call('/records')).status, 200);
  assert.ok(Date.now() - started >= 30, 'slow 场景应等待配置的延迟');
}, 40);

await withMock('normal', async () => {
  const record = await create();
  const review = await (await post(`/records/${record.id}/submit`)).json();
  const self = await post(`/reviews/${review.id}/decisions`, { version: 1, decision: 'confirm' });
  assert.equal(self.status, 403);
  assert.equal((await self.json()).error.code, 'self_review');
});

// 新外壳把应用放在 iframe 里；切换账号会重建 iframe，父窗口状态要保留。
globalThis.parent = {};
try {
  const first = installMock({ scenario: 'normal', fetch: passthrough, base: BASE, delay: 10 });
  const record = await create(first);
  assert.equal(first.state.records.size, 1);
  first.restore();

  const second = installMock({ scenario: 'normal', fetch: passthrough, base: BASE, delay: 10 });
  assert.equal(second.state.records.size, 1);
  assert.equal((await (await call(`/records/${record.id}`)).json()).status, 'draft');
  second.restore();
} finally {
  delete globalThis.parent;
}

assert.equal(
  toCsv({
    data: { title: '含,逗号', content: '第一行\n第二行' },
    status: 'confirmed',
    submitter: 'sampleoperator',
    confirmedBy: 'samplereviewer',
  }),
  '\ufeff字段,内容\n标题,"含,逗号"\n内容,"第一行\n第二行"\n状态,confirmed\n提交人,sampleoperator\n确认人,samplereviewer\n',
);

assert.equal(
  toCsv({
    data: { workpiece: 'W-1', undercut: 0.2 },
    status: 'confirmed',
    submitter: 'sampleoperator',
    confirmedBy: 'samplereviewer',
  }),
  '\ufeff字段,内容\nworkpiece,W-1\nundercut,0.2\n状态,confirmed\n提交人,sampleoperator\n确认人,samplereviewer\n',
);

console.log('mock ok: normal / custom fields / forbidden / failure / conflict / slow / self_review / shared-state / csv');