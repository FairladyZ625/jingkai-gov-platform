// 使用 Node 内置 fetch/Response 和离线公文路由，不启动网络服务。
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function transport(fetch) {
  const window = {JK_CONFIG: {api: {mode: 'http', baseUrl: ''}}};
  const ctx = vm.createContext({window, fetch, AbortController, setTimeout, clearTimeout});
  for (const file of ['http.js', 'platform.js', 'document.js']) {
    vm.runInContext(readFileSync(path.join(__dirname, '../../prototype/v4/api', file), 'utf8'), ctx);
  }
  return window.JKApi;
}

test('送审保留核查错误正文，HTTP 无原因短语也不显示空提示', async () => {
  const failure = {code: 'CHECK_FAILED', message: '请先处理核查发现的问题'};
  const api = transport(async () => new Response(JSON.stringify({error: failure}), {status: 422}));
  await assert.rejects(api.document.submit('fixture', {}), e =>
    e.status === 422 && e.code === failure.code && e.message === failure.message);
  const empty = transport(async () => new Response(null, {status: 502}));
  await assert.rejects(empty.document.submit('fixture', {}), e => /502/.test(e.message));
});

test('收件箱退回把用户输入的意见和被审版本一起提交', async () => {
  let sent;
  const api = transport(async (url, init) => {
    if (init.method === 'GET') return Response.json({items: [{id: 'R1', version: 2}]});
    sent = JSON.parse(init.body);
    return Response.json({});
  });
  await api.reviews.list();
  await api.reviews.decide('R1', {decision: 'reject', comment: '请明确虚拟材料的范围'});
  assert.equal(sent.version, 2);
  assert.equal(sent.reason, '请明确虚拟材料的范围');
});

test('画面版本优先于列表缓存；服务端拒绝仍按原状态和原因返回', async () => {
  let sent;
  const api = transport(async (url, init) => {
    if (init.method === 'GET') return Response.json({items: [{id: 'S1', app: 'skills', version: 9}]});
    sent = JSON.parse(init.body);
    return Response.json({code: 'FORBIDDEN', message: '没有办理权限'}, {status: 403});
  });
  await api.reviews.list();
  await assert.rejects(api.reviews.decide('S1', {decision: 'reject', reason: '请复核', version: 7}),
    e => e.status === 403 && e.code === 'FORBIDDEN' && e.message === '没有办理权限');
  assert.deepEqual(sent, {decision: 'reject', reason: '请复核', version: 7});
});

test('离线公文也不能自送自审，指定领导之外的账号不能代签', async () => {
  const ctx = vm.createContext({window: {}, localStorage: {getItem() {}, setItem() {}}, setTimeout});
  for (const file of ['config/app.config.js', 'config/mock-data.js', 'config/accounts.js', 'mock/mock-api.js']) {
    vm.runInContext(readFileSync(path.join(__dirname, '../../prototype/v4', file), 'utf8'), ctx);
  }
  const api = ctx.window.JKAPI;
  api.latency = 0;
  const state = api.state();
  state.me = 'u-wangmin';
  const template = (await api.get('/api/apps/document/templates')).items.find(t => t.id === 'T06');
  const inputs = Object.fromEntries(template.inputs.map(([k, , v]) => [k, v]));
  const {item} = await api.post('/api/apps/document/drafts', {templateId: template.id, inputs});
  const draftUrl = '/api/apps/document/drafts/' + item.id;
  state.me = 'u-liyang';
  await assert.rejects(api.post(draftUrl + '/submit', {assignee: '李阳'}), {status: 409, code: 'SELF_REVIEW'});
  assert.equal((await api.get(draftUrl)).item.status, '草稿');
  state.me = 'u-wangmin';
  const {review} = await api.post(draftUrl + '/submit', {assignee: '李阳'});
  const decision = '/api/v1/reviews/' + review.id + '/decisions';
  state.me = state.users.find(u => u.role === 'admin').id;
  await assert.rejects(api.post(decision, {decision: 'reject'}), {status: 403});
  assert.equal((await api.get(draftUrl)).item.status, '审签中');
  state.me = 'u-liyang';
  assert.equal((await api.post(decision, {decision: 'approve'})).item.status, 'done');
});
