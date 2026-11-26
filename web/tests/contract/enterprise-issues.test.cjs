const assert = require('node:assert/strict');
const test = require('node:test');
const { createContext, loadScript } = require('./mock.cjs');

async function setup(username = 'wangmin', globals = {}) {
  const context = createContext(globals);
  loadScript(context, 'api/enterprise.js');
  const account = context.JK_CONFIG.demoAccounts.find(u => u.username === username);
  await context.JKHttp.post('/api/v1/auth/login', { username, password: account.password });
  return { context, api: context.JKApi.enterprise };
}
const plain = value => JSON.parse(JSON.stringify(value));

test('明确空负责人创建待分派，旧调用仍默认当前办理人', async () => {
  const { api } = await setup();
  const empty = (await api.createIssue({ entId: 'E001', title: '新诉求', owner: '', due: '', next: '' })).item;
  assert.equal(empty.status, '待分派');
  assert.equal(empty.owner, '');
  assert.equal(empty.due, '');
  const legacy = (await api.createIssue({ entId: 'E001', title: '旧调用' })).item;
  assert.equal(legacy.status, '办理中');
  assert.equal(legacy.owner, '王敏');
});

test('诉求负责人、期限与下一步更新和清空均保留修改依据，同记录在企业详情可读', async () => {
  const { api } = await setup();
  const item = (await api.createIssue({ entId: 'E001', title: '跟进诉求', owner: '', due: '', next: '' })).item;
  const change = { owner: '办理员甲', due: '2026-12-01', next: '联系企业', note: '企业来电确认', status: '办理中' };
  const row = (await api.patchIssue(item.id, change)).item;
  assert.equal(row.due, '2026-12-01');
  assert.equal(row.steps.at(-1)[1], '状态：待分派 → 办理中 · 负责人：未分派 → 办理员甲 · 截止日期：未设置 → 2026-12-01 · 下一步：未填写 → 联系企业 · 备注：企业来电确认 · 操作人：王敏');
  const { note, ...sameChange } = change;
  const same = (await api.patchIssue(item.id, sameChange)).item;
  assert.deepEqual(plain(same.steps), plain(row.steps));
  const cleared = (await api.patchIssue(item.id, { owner: '', due: '', next: '' })).item;
  assert.deepEqual([cleared.owner, cleared.due, cleared.next], ['', '', '']);
  assert.equal(cleared.steps.at(-1)[1], '负责人：办理员甲 → 未分派 · 截止日期：2026-12-01 → 未设置 · 下一步：联系企业 → 未填写 · 操作人：王敏');
  const detail = (await api.get('E001')).issues.find(i => i.id === item.id);
  const listed = (await api.issues({ entId: 'E001' })).items.find(i => i.id === item.id);
  assert.deepEqual(plain(detail), plain(cleared));
  assert.equal(listed.title, cleared.title);
  assert.deepEqual(plain(listed.steps), plain(cleared.steps));
});

test('非法诉求输入被拒绝且不更改原记录', async () => {
  const { api } = await setup();
  const item = (await api.createIssue({ entId: 'E001', title: '校验诉求' })).item;
  for (const change of [{ due: '2026-02-30' }, { due: '2026-2-01' }, { status: '未知' }, { owner: 3 }, { entId: 'E002' }, {}]) {
    await assert.rejects(api.patchIssue(item.id, change), error => error.status === 400 && error.code === 'INVALID_REQUEST');
  }
  await assert.rejects(api.patchIssue('missing', { note: '不存在' }), error => error.status === 404);
  await assert.rejects(api.createIssue({ entId: 'missing', title: '不存在企业' }), error => error.status === 404);
  await assert.rejects(api.createIssue({ entId: 'E001', title: '空来源', from: '' }), error => error.status === 400);
  const actual = (await api.issues()).items.find(i => i.id === item.id);
  assert.equal(actual.status, item.status);
  assert.deepEqual(plain(actual.steps), plain(item.steps));
});

test('只读协作者读取企业详情与诉求列表均不拿到自由文本，写入仍拒绝', async () => {
  const { api, context } = await setup();
  const item = (await api.createIssue({ entId: 'E001', title: '需要保护的诉求正文', owner: '测试负责人', next: '保密下一步' })).item;
  await api.visit('E001', { notes: '需要保护的走访正文', type: '电话' });
  const partner = context.JK_CONFIG.demoAccounts.find(u => u.username === 'hejun');
  await context.JKHttp.post('/api/v1/auth/login', { username: partner.username, password: partner.password });
  for (const payload of [await api.get('E001'), await api.issues()]) {
    const serialized = JSON.stringify(payload);
    for (const text of ['需要保护的诉求正文', '测试负责人', '保密下一步', '需要保护的走访正文']) assert.ok(!serialized.includes(text));
  }
  assert.equal((await api.issues({ owner: '测试负责人' })).items.length, 0);
  await assert.rejects(api.patchIssue(item.id, { owner: '协作者' }), error => error.status === 403);
  await assert.rejects(api.createIssue({ entId: 'E001', title: '禁止创建', owner: '' }), error => error.status === 403);
});


test('新诉求和进展的日期按北京时间保存', async () => {
  const instant = '2026-11-18T18:30:00Z';
  class TestDate extends Date {
    constructor(...args) { super(...(args.length ? args : [instant])); }
    static now() { return Date.parse(instant); }
  }
  const { api } = await setup('wangmin', { Date: TestDate });
  const item = (await api.createIssue({ entId: 'E001', title: '跨日诉求' })).item;
  assert.equal(item.created, '2026-11-19');
  const changed = (await api.patchIssue(item.id, { note: '记录当日进展' })).item;
  assert.equal(changed.steps.at(-1)[0], '2026-11-19');
});

test('新建企业保留显式经营地址，兼容旧 addr 调用并从详情读取同一地址', async () => {
  const { api } = await setup();
  const current = (await api.create({ name: '地址验证企业甲', opAddr: '演示路 18 号', addr: '旧地址参数' })).item;
  assert.equal(current.opAddr, '演示路 18 号');
  assert.equal((await api.get(current.id)).item.opAddr, '演示路 18 号');
  const legacy = (await api.create({ name: '地址验证企业乙', addr: '旧调用经营地址' })).item;
  assert.equal((await api.get(legacy.id)).item.opAddr, '旧调用经营地址');
  const empty = (await api.create({ name: '地址验证企业丙', opAddr: '', addr: '不应代填' })).item;
  assert.equal((await api.get(empty.id)).item.opAddr, '');
});
