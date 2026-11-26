const assert = require('node:assert/strict');
const test = require('node:test');
const { createContext, loadScript } = require('./mock.cjs');
const plain = value => JSON.parse(JSON.stringify(value));

async function login(context, username = 'wangmin') {
  const account = context.JK_CONFIG.demoAccounts.find(row => row.username === username);
  assert.ok(account);
  return context.JKApi.auth.login({ username, password: account.password });
}
async function setup(globals = {}) {
  const context = createContext(globals);
  loadScript(context, 'api/platform.js');
  loadScript(context, 'api/policy.js');
  await login(context);
  const { item } = await context.JKApi.chat.create({});
  return { context, api: context.JKApi, id: item.id };
}
const send = (api, id, text, fields = {}) => api.chat.send(id, { text, mode: 'policy_service', ...fields });
const detail = (context, id) => context.JKHttp.get('/api/v1/conversations/' + id);


test('政策岗位通过真实政策 handler 检索并返回原文引用、材料、条件与期限', async () => {
  const { context, api, id } = await setup();
  const guard = context.JKAPI.guard;
  const requests = [];
  context.JKAPI.guard = (method, path, body) => { requests.push([method, path]); return guard(method, path, body); };
  const { user, reply } = await send(api, id, '数据券需要准备什么材料？', { enterpriseId: 'E001' });
  assert.deepEqual(plain(reply.toolCalls), [{ tool: 'policy.search', args: {
    q: '数据券需要准备什么材料？', queryMode: 'question', enterpriseId: 'E001',
  }, status: 'ok' }]);
  assert.ok(requests.some(([method, path]) => method === 'GET' && path === '/api/apps/policy/items'));
  assert.ok(requests.some(([method, path]) => method === 'GET' && path === '/api/apps/enterprise/companies/E001'));
  assert.equal(reply.mode, 'policy_service');
  assert.equal(user.enterpriseId, 'E001');
  assert.equal(reply.intent, 'policy');
  assert.match(reply.content, /申请条件.*待确认/s);
  assert.match(reply.content, /申报材料/);
  assert.match(reply.content, /申报期限/);
  assert.match(reply.content, /不代表符合申请条件或获批/);
  assert.ok(reply.citations.length);
  for (const citation of reply.citations) {
    const { item } = await api.policy.item(citation.itemId);
    assert.equal(citation.snippet, item.original);
    assert.equal(citation.url, item.source.url);
    assert.equal(citation.fileId, item.doc);
    assert.deepEqual(plain(citation.source), { app: 'policy', itemId: item.id });
    assert.ok(reply.content.includes(item.original));
  }
  assert.deepEqual(plain((await detail(context, id)).messages.at(-1)), plain(reply));
});

test('question 检索保留旧子串接口，无命中与缺主题均不泛推荐', async () => {
  const { api, id } = await setup();
  assert.equal((await api.policy.items({ q: '数据券需要什么材料？' })).items.length, 0);
  const result = await api.policy.items({ q: '数据券需要什么材料？', queryMode: 'question' });
  assert.ok(result.items.some(item => item.id === 'RP-001'));
  assert.equal(result.queryState, 'searched');
  const noMatch = (await send(api, id, '火星采矿许可补贴')).reply;
  assert.deepEqual(plain(noMatch.citations), []);
  assert.deepEqual(plain(noMatch.cards), []);
  assert.match(noMatch.content, /没有找到.*无法判断适用或获批/s);
  const fresh = (await api.chat.create({})).item.id;
  const clarify = (await send(api, fresh, '那期限呢？')).reply;
  assert.deepEqual(plain(clarify.citations), []);
  assert.match(clarify.content, /政策名称/);
  await assert.rejects(api.policy.items({ q: '数据券', queryMode: 'invent' }), error => error.status === 400);
});

test('模式和企业参数在写入前校验，缺省仍是 general', async () => {
  const { context, api, id } = await setup();
  for (const fields of [{ mode: 'administrator' }, { mode: null }, { enterpriseId: '' },
    { enterpriseId: '  ' }, { enterpriseId: 1 }, { app: 'document' }]) {
    await assert.rejects(send(api, id, '数据券', fields), error => error.status === 422);
    assert.equal((await detail(context, id)).messages.length, 0);
  }
  const result = await api.chat.send(id, { text: '你好' });
  assert.equal(result.reply.mode, 'general');
  assert.equal(result.reply.enterpriseId, null);
  assert.match(result.reply.content, /你好/);
  assert.deepEqual(plain(result.reply.toolCalls), []);
});

test('企业、模式和会话切换均截断追问上下文', async () => {
  const { api, id } = await setup();
  await send(api, id, 'RP-001 的申请条件', { enterpriseId: 'E001' });
  const follow = (await send(api, id, '那期限呢？', { enterpriseId: 'E001' })).reply;
  assert.equal(follow.toolCalls[0].args.q, '那期限呢？');
  assert.match(follow.toolCalls[1].args.q, /RP-001/);
  const switched = (await send(api, id, '那期限呢？', { enterpriseId: 'E002' })).reply;
  assert.equal(switched.toolCalls[0].args.q, '那期限呢？');
  assert.deepEqual(plain(switched.citations), []);
  const returned = (await send(api, id, '那材料呢？', { enterpriseId: 'E001' })).reply;
  assert.equal(returned.toolCalls[0].args.q, '那材料呢？');
  await send(api, id, 'RP-001 条件');
  await api.chat.send(id, { text: '你好' });
  assert.equal((await send(api, id, '那材料呢？')).reply.toolCalls[0].args.q, '那材料呢？');
  const fresh = (await api.chat.create({})).item.id;
  assert.equal((await send(api, fresh, '那材料呢？')).reply.toolCalls[0].args.q, '那材料呢？');
});

test('账号不能读、写、删除或列出其他身份新建的会话', async () => {
  const { context, api, id } = await setup();
  const owner = (await api.auth.session()).user.id;
  assert.equal((await detail(context, id)).item.ownerId, owner);
  await send(api, id, 'RP-001 条件');
  await login(context, 'hejun');
  assert.ok(!(await api.chat.list()).items.some(item => item.id === id));
  for (const request of [() => detail(context, id), () => send(api, id, '那材料呢？'),
    () => api.chat.send(id, { text: '你好' }), () => api.chat.remove(id)]) {
    await assert.rejects(request(), error => error.status === 404);
  }
  await login(context);
  assert.equal((await detail(context, id)).messages.length, 2);
});

test('无归属的旧演示会话在政策岗位提示新建，不认领历史', async () => {
  const { context, api } = await setup();
  const legacy = (await api.chat.list()).items.find(item => !item.ownerId);
  assert.ok(legacy);
  const before = plain(await detail(context, legacy.id));
  await assert.rejects(send(api, legacy.id, 'RP-001 条件'), error => error.status === 409 && /新建/.test(error.message));
  assert.deepEqual(plain(await detail(context, legacy.id)), before);
  await assert.rejects(send(api, 'missing-policy-session', '数据券'), error => error.status === 404);
});

test('政策权限提前校验，企业无权只返回 unavailable 且保留公开依据', async () => {
  const { context, api } = await setup();
  await login(context, 'admin');
  await api.admin.setGrant('partner', 'enterprise', []);
  await login(context, 'hejun');
  const id = (await api.chat.create({})).item.id;
  const result = await api.policy.items({ q: 'RP-001', queryMode: 'question', enterpriseId: 'E001' });
  assert.deepEqual(plain(result.enterprise), { id: 'E001', status: 'unavailable' });
  const reply = (await send(api, id, 'RP-001 帮我提交申请并保证获批', { enterpriseId: 'E001' })).reply;
  assert.match(reply.content, /未能读取所选企业资料/);
  assert.match(reply.content, /不代表符合申请条件或获批/);
  assert.ok(reply.citations.length);
  assert.ok(!reply.content.includes('书香里'));
  assert.deepEqual(plain(reply.toolCalls.map(call => call.tool)), ['policy.search']);
  await login(context, 'admin');
  await api.admin.setGrant('partner', 'policy', []);
  await login(context, 'hejun');
  await assert.rejects(send(api, id, '数据券'), error => error.status === 403);
  assert.equal((await detail(context, id)).messages.length, 2);
});

test('企业上下文只返回当前授权摘要，不携带联系人和诉求历史', async () => {
  const { context, api } = await setup();
  await login(context, 'hejun');
  const result = await api.policy.items({ q: 'RP-001', queryMode: 'question', enterpriseId: 'E001' });
  assert.equal(result.enterprise.status, 'available');
  assert.deepEqual(Object.keys(result.enterprise.item).sort(), ['id', 'industry', 'name', 'scale']);
  const missing = await api.policy.items({ q: 'RP-001', queryMode: 'question', enterpriseId: 'missing' });
  assert.deepEqual(plain(missing.enterprise), { id: 'missing', status: 'unavailable' });
  assert.equal(missing.items.length, 1);
});

test('工具返回被替换时，岗位只展示该真实 handler 的来源结果', async () => {
  const { context, api, id } = await setup();
  const base = (await api.policy.items({ q: '数据券', queryMode: 'question' })).items[0];
  const source = { ...base, id: 'TEST-SOURCE', title: '确定性工具来源', original: '这是工具本轮实际提供的公开条款。' };
  const seen = [];
  context.JKAPI.ext.first('GET', '/api/apps/policy/items', (body, params, query) => {
    seen.push(plain(query));
    return { items: [source], total: 1, docs: [], queryState: 'searched', enterprise: null };
  });
  const reply = (await send(api, id, '测试具体支持条件')).reply;
  assert.deepEqual(seen, [{ q: '测试具体支持条件', queryMode: 'question' }]);
  assert.equal(reply.citations[0].snippet, source.original);
  assert.match(reply.content, /这是工具本轮实际提供的公开条款/);
  assert.deepEqual(plain(reply.cards[0].ids), ['TEST-SOURCE']);
});

test('查询失败与非法来源均不回退到知识库或泛推荐', async () => {
  for (const malformed of [false, true]) {
    const { context, api, id } = await setup();
    const item = (await api.policy.items({ q: '数据券', queryMode: 'question' })).items[0];
    context.JKAPI.ext.first('GET', '/api/apps/policy/items', () => {
      if (!malformed) throw new Error('private internal server');
      return { items: [{ ...item, source: { url: 'javascript:unsafe()' } }], queryState: 'searched' };
    });
    const reply = (await send(api, id, '数据券条件')).reply;
    assert.equal(reply.toolCalls[0].status, 'error');
    assert.deepEqual(plain(reply.citations), []);
    assert.deepEqual(plain(reply.cards), []);
    assert.match(reply.content, /无法判断适用或获批/);
    assert.doesNotMatch(reply.content, /private internal/);
  }
});

test('重新载入后保留模式和企业，账号边界继续生效', async () => {
  const { context, api, id } = await setup();
  await send(api, id, 'RP-001 条件', { enterpriseId: 'E001' });
  const reloaded = createContext({ localStorage: context.localStorage });
  loadScript(reloaded, 'api/platform.js');
  loadScript(reloaded, 'api/policy.js');
  const messages = (await detail(reloaded, id)).messages;
  assert.equal(messages.at(-1).mode, 'policy_service');
  assert.equal(messages.at(-1).enterpriseId, 'E001');
  const reply = (await send(reloaded.JKApi, id, '那材料呢？', { enterpriseId: 'E001' })).reply;
  assert.equal(reply.toolCalls[0].args.q, '那材料呢？');
  assert.match(reply.toolCalls[1].args.q, /RP-001/);
  await login(reloaded, 'hejun');
  await assert.rejects(detail(reloaded, id), error => error.status === 404);
});


test('政策岗位按北京时间刷新已确认批次期限，不沿用过时申报中快照', async () => {
  const time = Date.parse('2026-11-30T16:30:00Z');
  class BeijingBoundaryDate extends Date {
    constructor(...args) { super(...(args.length ? args : [time])); }
    static now() { return time; }
  }
  const { api, id } = await setup({ Date: BeijingBoundaryDate });
  const result = await api.policy.items({ q: 'RP-023', queryMode: 'question' });
  assert.equal(result.items[0].times.open, false);
  assert.match(result.items[0].times.deadlineText, /已于 2026-11-30 截止/);
  const reply = (await send(api, id, 'RP-023 什么时候截止')).reply;
  assert.match(reply.content, /已于 2026-11-30 截止/);
  assert.doesNotMatch(reply.content, /当前批次申报至/);
});


test('实体书店房租连写问句命中同一原文的组合关键词，并明确历史政策边界', async () => {
  const { api, id } = await setup();
  const text = '实体书店房租有哪些申请条件？';
  const result = await api.policy.items({ q: text, queryMode: 'question' });
  assert.deepEqual(plain(result.items.map(item => item.id)), ['PI-03']);
  const { reply } = await send(api, id, text, { enterpriseId: 'E001' });
  assert.equal(reply.toolCalls[0].args.q, text);
  assert.match(reply.content, /申请条件/);
  assert.match(reply.content, /房租/);
  assert.match(reply.content, /历史/);
  assert.match(reply.content, /不代表符合申请条件或获批/);
  assert.deepEqual(plain(reply.citations.map(citation => citation.itemId)), ['PI-03']);
});


test('新编号与陌生新主题只查当前问题，不借旧政策兜底', async () => {
  const { api, id } = await setup();
  await send(api, id, 'RP-001 条件', { enterpriseId: 'E001' });
  const changed = (await send(api, id, '那 RP-023 材料', { enterpriseId: 'E001' })).reply;
  assert.deepEqual(plain(changed.citations.map(citation => citation.itemId)), ['RP-023']);
  assert.deepEqual(plain(changed.toolCalls.map(call => call.args.q)), ['那 RP-023 材料']);
  const unknown = (await send(api, id, '那火星采矿许可补贴呢？', { enterpriseId: 'E001' })).reply;
  assert.deepEqual(plain(unknown.citations), []);
  assert.deepEqual(plain(unknown.cards), []);
  assert.deepEqual(plain(unknown.toolCalls.map(call => call.args.q)), ['那火星采矿许可补贴呢？']);
  const again = (await send(api, id, '那需要什么材料？', { enterpriseId: 'E001' })).reply;
  assert.deepEqual(plain(again.citations), []);
  assert.equal(again.toolCalls.length, 1);
});

test('明确指代先查本轮，clarify 后才二次查询且完整记录调用顺序', async () => {
  const { context, api, id } = await setup();
  await send(api, id, 'RP-001 条件', { enterpriseId: 'E001' });
  const guard = context.JKAPI.guard;
  const paths = [];
  context.JKAPI.guard = (method, path, body) => { paths.push(path); return guard(method, path, body); };
  const reply = (await send(api, id, '那需要什么材料？', { enterpriseId: 'E001' })).reply;
  assert.deepEqual(plain(reply.toolCalls.map(call => call.args.q)), ['那需要什么材料？', 'RP-001 条件\n那需要什么材料？']);
  assert.equal(paths.filter(path => path === '/api/apps/policy/items').length, 2);
  assert.deepEqual(plain(reply.citations.map(citation => citation.itemId)), ['RP-001']);
  const again = (await send(api, id, '那期限呢？', { enterpriseId: 'E001' })).reply;
  assert.deepEqual(plain(again.toolCalls.map(call => call.args.q)), ['那期限呢？', 'RP-001 条件\n那需要什么材料？\n那期限呢？']);
  assert.deepEqual(plain(again.citations.map(citation => citation.itemId)), ['RP-001']);
});

test('政策编号可与中文连写，同时排除较长编号和英文前缀', async () => {
  const { api } = await setup();
  for (const [q, expected] of [
    ['RP-001', ['RP-001']], ['RP-001需要什么材料？', ['RP-001']],
    ['请问RP-001的申请条件是什么？', ['RP-001']], ['RP-0010需要什么材料？', []],
    ['请问XRP-001的申请条件是什么？', []],
  ]) {
    const result = await api.policy.items({ q, queryMode: 'question' });
    assert.deepEqual(plain(result.items.map(item => item.id)), expected, q);
  }
});
