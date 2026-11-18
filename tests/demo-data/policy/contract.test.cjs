const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const root = path.resolve(__dirname, '../../..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const json = (file) => JSON.parse(read(file));
const plain = (x) => JSON.parse(JSON.stringify(x));
const route = '/api/apps/policy';
const documentRoute = '/api/apps/document';
const exampleLabel = '示例（无对应原文）';

function boot({ stored = null, prepare } = {}) {
  const localStorage = {
    getItem: () => stored,
    setItem: (_, value) => { stored = value; },
    removeItem: () => { stored = null; },
  };
  const ctx = vm.createContext({ window: {}, localStorage, URLSearchParams, setTimeout: (fn) => fn() });
  const run = (file) => {
    let source = read('prototype/v4/' + file);
    if (file === 'mock/mock-api.js' && process.env.JK_POLICY_MUTATION === 'fixed-count') {
      assert.ok(source.includes('核对了 ${total} 项事项'));
      source = source.replace('核对了 ${total} 项事项', '核对了 18 项事项');
    }
    vm.runInContext(source, ctx, { filename: file });
  };
  run('config/mock-data.js');
  run('config/accounts.js');
  if (prepare) prepare(ctx.window.JK_DATA);
  run('mock/mock-api.js');
  run('mock/policy.js');
  run('api/http.js');
  run('api/policy.js');
  return {
    api: ctx.window.JKAPI,
    policy: ctx.window.JKApi.policy,
    seed: ctx.window.JK_DATA,
    stored: () => stored,
  };
}

const directChat = (api, text) => api.post('/api/v1/ai/chat', { messages: [{ content: text }] });
const conversationChat = async (api, text) => {
  const { item } = await api.post('/api/v1/conversations', {});
  return (await api.post(`/api/v1/conversations/${item.id}/messages`, { text })).reply;
};
const tool = async (api, name, args) => (await api.post('/api/v1/apps/policy/tools/' + name, { args })).result;
const latest = (draft) => draft.versions.at(-1).content;

test('事项库、匹配工具和两条对话入口使用同一事项与动态计数', async () => {
  const { api, policy, seed } = boot({ prepare: (data) => {
    data.enterprises.find(({ id }) => id === 'E001').short = '青石样例书屋';
    const e = data.enterprises.find(({ id }) => id === 'E002');
    e.short = '青石样例车研';
    e.name = '北京青石样例车研有限公司';
    e.example = true;
  } });
  const e = seed.enterprises.find(({ id }) => id === 'E002');
  const list = await policy.items();
  const match = await policy.match({ entId: e.id });
  const text = `帮我查一下${e.short}能申报哪些政策`;
  const fallback = await directChat(api, text);
  const reply = await conversationChat(api, text);
  assert.equal(list.total, list.items.length);
  assert.equal(match.total, list.total);
  assert.ok(fallback.content.includes(`核对了 ${list.total} 项事项`), `事项库 ${list.total} 项，兜底回复为 ${fallback.content}`);
  assert.equal(fallback.content, reply.content);
  assert.ok(reply.content.includes(e.short));
  assert.ok(reply.content.includes(`默认选中 ${match.defaultItemIds.length} 项，本批已结束 ${match.summary.ended} 项`));
  assert.deepEqual(plain(reply.cards[0].results), plain(match.results.slice(0, 5)));
  assert.deepEqual(plain(await tool(api, 'match', { entId: e.id })), plain(match));
  assert.deepEqual(plain(match.defaultItemIds), Array.from(match.results.filter((r) => r.level === 'ok' && !r.ended), (r) => r.id));
  assert.equal(match.summary.ended, match.results.filter((r) => r.level !== 'no' && r.ended).length);
  assert.equal(await api.get('/api/apps/enterprise/companies/E002').then(({ item }) => item.example), true);
  assert.ok((await directChat(api, '查一下企业')).content.includes(e.short));
  assert.ok((await directChat(api, '怎么用')).content.includes(`匹配 ${list.total} 项事项`));
});

test('E002 保留原始算力券与独立推理算力，转载依据不重复匹配', async () => {
  const { api, policy } = boot();
  const m = await policy.match({ entId: 'E002' });
  const matches = m.results.filter((p) => p.level !== 'no');
  assert.equal(matches.length, 12);
  assert.equal(m.defaultItemIds.length, 9);
  assert.equal(m.summary.ended, 3);
  assert.equal(matches.filter((p) => /算力券/.test(p.title + p.rule)).length, 1);
  console.log('E002 匹配 12 项，默认选中 9 项，本批已结束 3 项，算力券 1 项。');
  assert.deepEqual(Array.from(m.results.filter((p) => /算力|推理效能/.test(p.title)), (p) => p.id), ['RP-006', 'RP-014']);
  assert.ok(!m.results.some((p) => p.id === 'PI-08'));
  assert.ok((await policy.item('RP-008')).item.source.url);
  const input = { itemId: 'RP-006', amount: 80000000 };
  const calc = await policy.calc(input);
  assert.equal(calc.result.amount, 20000000);
  assert.equal(calc.result.capped, true);
  assert.deepEqual(plain(await tool(api, 'calc', input)), plain(calc));
  assert.equal((await policy.calc({ ...input, amount: -1 })).result, null);
  const checkOnly = await policy.match({ profile: { subjectType: '企业', tags: ['实体书店'], yearsInZone: 1 } });
  assert.ok(checkOnly.defaultItemIds.length);
  assert.ok(checkOnly.defaultItemIds.every((id) => checkOnly.results.some((r) => r.id === id && !r.ended)));
});

test('种子中的真实条款保留官网链接，同文号同条款唯一', async () => {
  const { policy } = boot({ prepare(data) {
    if (process.env.JK_POLICY_MUTATION === 'duplicate-clause') {
      const item = data.policies.find((p) => p.id === 'RP-006');
      data.policies.push({ ...item, id: 'TEST-DUPLICATE' });
    }
  } });
  const { items, docs } = await policy.items();
  const examples = json('data/seed/policy-examples.json');
  assert.deepEqual(Object.keys(examples).sort(), ['policies', 'policyDocs']);
  const exampleDocs = new Set();
  for (const d of examples.policyDocs) {
    assert.equal(d.example, true);
    assert.equal(d.no, exampleLabel);
    assert.ok(!d.url && !d.realNo);
    exampleDocs.add(d.id);
  }
  for (const p of examples.policies) {
    assert.equal(p.example, true);
    assert.equal(p.clause, exampleLabel);
    assert.ok(!p.source?.url && !p.source?.docNo && !p.url);
    assert.ok(!p.doc || exampleDocs.has(p.doc));
  }
  const docById = new Map(docs.map((d) => [d.id, d]));
  const keySet = new Set();
  for (const p of items.filter((p) => p.real)) {
    assert.match(p.source.url, /^https:\/\/kfqgw\.beijing\.gov\.cn\//, p.id);
    assert.equal(p.source.url, docById.get(p.doc).url, p.id);
    const no = !p.docNo || p.docNo === '（无文号）' ? p.source.url : p.docNo;
    const key = no + '|' + p.clause.replace(/\s/g, '');
    assert.ok(!keySet.has(key), p.id + ' 重复依据 ' + key);
    keySet.add(key);
  }
  assert.equal(items.filter((p) => p.id.startsWith('RP-')).length, 83);
  assert.equal((await policy.item('PI-03')).item.times.open, false);
  assert.equal((await policy.item('PI-02')).item.rule.fixed, 2000000);
  assert.equal((await policy.item('PI-09')).item.rule.fixed, 1000000);
  for (const id of ['PI-08', 'PI-16']) await assert.rejects(policy.item(id), { code: 'NOT_FOUND' });
});

test('混合口径保留完整金额及主体，试算不返回单一错误金额', async () => {
  const { policy } = boot();
  const amounts = {
    'RP-010': ['发放5000万元', '合同金额20%', '不超过200万元', '最高不超过500万元'],
    'RP-045': ['最高200万元', '最高500万元', '最高3000万元的1:1'],
    'RP-074': ['80万元', '60万元', '120万元', '90万元', '10项及以上专利'],
    'RP-013': ['再给予800万元', '不超过3000万元'],
    'RP-029': ['4%给予最高不超过500万元'],
  };
  const snapshot = json('data/public/kb_docs.json');
  const normalize = (text) => text.normalize('NFKC').replace(/\s/g, '');
  for (const [id, terms] of Object.entries(amounts)) {
    const { item } = await policy.item(id);
    if (['RP-010', 'RP-045', 'RP-074'].includes(id)) {
      const published = snapshot.find((doc) => doc.url === item.source.url);
      assert.ok(published && normalize(published.text).includes(normalize(item.original)), id + ' 缺少公开快照原句');
    }
    for (const s of terms) assert.ok(item.original.includes(s), id + ' 缺少 ' + s);
    assert.ok(item.rule.manual);
    assert.equal((await policy.calc({ itemId: id, amount: 10000000 })).result, null);
  }
});

test('无出处示例与无文号真实事项兼容列表、详情、对话和公文', async () => {
  const { api, policy } = boot({ prepare: (data) => {
    const p = data.policies.find((x) => x.id === 'RP-006');
    // 模拟旧来源字段残留，规则和文字本身使用明确的虚构测试夹具。
    data.policies.push({
      ...p, id: 'TEST-EXAMPLE', title: '虚构木纹指标', real: false, example: true,
      url: p.source.url, original: '虚构规则供演示', keywords: ['木纹指标'],
      rule: { manual: true, text: '模拟金额，人工核对' },
    });
    data.policies.push({
      ...p, id: 'TEST-NO-REF', title: '无文号测试事项', doc: null, clause: '',
      source: { docNo: '', url: '', deptResp: '' }, keywords: ['无文号测试事项'],
    });
  } });
  const list = await policy.items();
  const ex = list.items.find((x) => x.id === 'TEST-EXAMPLE');
  assert.equal(ex.docNo, exampleLabel);
  assert.equal(ex.clause, exampleLabel);
  assert.ok(!ex.source.url && !ex.url);
  assert.deepEqual(plain((await policy.item(ex.id)).item), plain(ex));
  assert.equal((await policy.item('TEST-NO-REF')).item.docNo, '');
  const reply = await conversationChat(api, '木纹指标的政策条件');
  assert.ok(reply.content.includes(exampleLabel));
  assert.equal(reply.citations[0].name, exampleLabel);
  assert.equal(reply.citations[0].url, '');
  const citation = (await api.get('/api/v1/kb/files/POL:TEST-EXAMPLE')).item;
  assert.equal(citation.no, exampleLabel);
  assert.equal(citation.url, '');
  const missing = await conversationChat(api, '无文号测试事项的政策条件');
  assert.equal(missing.citations[0].name, '无文号测试事项');
  for (const templateId of ['T03', 'T10']) {
    const { item: sample } = await api.post(documentRoute + '/drafts', { templateId, inputs: { policy: ex.id } });
    const { item: noRef } = await api.post(documentRoute + '/drafts', { templateId, inputs: { policy: 'TEST-NO-REF' } });
    assert.ok(latest(sample).paragraphs.join('').includes(exampleLabel));
    assert.doesNotMatch(latest(sample).paragraphs.join(''), /京技管发|https:\/\//);
    assert.doesNotMatch(latest(noRef).paragraphs.join(''), /undefined|（无文号）|《》/);
    const exported = await api.get(documentRoute + '/drafts/' + sample.id + '/export');
    assert.ok(exported.html.includes(exampleLabel));
  }
  const notice = await policy.notice({ itemIds: [ex.id] });
  assert.ok(notice.text.includes(exampleLabel));
  assert.doesNotMatch(notice.text, /京技管发|https:\/\//);
});

test('告知单共用工具路由，按实际选择去重落款并留空电话', async () => {
  const { api, policy, seed } = boot();
  const { item } = await policy.item('RP-006');
  const args = { entId: 'E002', itemIds: [item.id, item.id], amounts: { [item.id]: 6800000 } };
  const notice = await policy.notice(args);
  assert.deepEqual(plain(await tool(api, 'notice', args)), plain(notice));
  assert.ok(notice.text.startsWith(seed.enterprises.find((e) => e.id === 'E002').name));
  assert.ok(notice.text.includes('落款：' + item.source.deptResp + '　'));
  assert.match(notice.text, /试算参考：680 万元 × 30% = 204 万元/);
  assert.match(notice.text, /^咨询电话（请填写）：$/m);
  assert.equal(notice.text.split('\n').filter((line) => /^\d+\. /.test(line)).length, 1);
  const multi = await policy.notice({ entId: 'E002', itemIds: ['RP-006', 'RP-007', 'RP-016', 'RP-074'] });
  assert.match(multi.text, /落款：信息技术产业局、营商环境建设局、市自动驾驶办公室、请填写（责任部门）　/);
  const missing = await policy.notice({ itemIds: ['RP-074'] });
  assert.ok(missing.text.startsWith('申请人：'));
  assert.match(missing.text, /落款：请填写（责任部门）　/);
  assert.doesNotMatch(missing.text, /商务金融局　/);
  const noDocNo = await policy.notice({ itemIds: ['PI-06'] });
  assert.doesNotMatch(noDocNo.text, /undefined|（无文号）/);
  const ended = await policy.notice({ entId: 'E002', itemIds: ['RP-003'] });
  assert.match(ended.text, /^   申报时间：本批已结束。最近一批已于 2026\.11\.06 截止/m);
  await assert.rejects(policy.notice({ entId: 'E002', itemIds: ['PI-08'] }), { code: 'NOT_FOUND' });
});

test('公文新建、核查、修正、审签和导出不会生成发文字号', async () => {
  const { api } = boot();
  const templates = await api.get(documentRoute + '/templates');
  assert.equal(templates.items.find((t) => t.id === 'T10').inputs.find(([key]) => key === 'policy')[2], 'RP-024');
  const create = await api.post(documentRoute + '/drafts', {
    templateId: 'T10', inputs: { ent: 'E002', policy: 'RP-006', issue: '咨询算力券' },
  });
  const draft = documentRoute + '/drafts/' + create.item.id;
  assert.equal(latest(create.item).docNo, '');
  const check = await api.post(draft + '/check', {});
  const numberIssue = check.issues.find((i) => i.target === 'docNo');
  assert.equal(numberIssue.text, '请填写发文字号');
  assert.ok(!numberIssue.fix);
  const fix = await api.post(draft + '/fix', { ids: [numberIssue.id] });
  assert.equal(latest(fix.item).docNo, '');
  const { review } = await api.post(draft + '/submit', {});
  api.state().me = api.state().users.find((u) => u.username === 'liyang').id;
  await api.post('/api/v1/reviews/' + review.id + '/decisions', { decision: 'approve' });
  const { item } = await api.get(draft);
  assert.equal(item.status, '已定稿');
  assert.equal(latest(item).docNo, '');
  const exp = await api.get(draft + '/export');
  assert.ok(exp.html.includes('发文字号（请填写）'));
  assert.doesNotMatch(exp.html, /京技产促/);
});

test('旧公文经一次性升级，只清理有生成记录的演示文号', async () => {
  const fresh = boot();
  const old = fresh.api.state();
  delete old.demoSeedVersion;
  old.myTodos = [{ id: '测试待办' }];
  old.policies.push({ id: 'PI-08' });
  const versions = old.drafts['DOC-1112'].versions;
  const manualNumber = '京技产促〔2026〕58号';
  versions[0].content.docNo = '京技产促〔2026〕【待补】号';
  versions[1] = { ...versions[1], by: '王敏（一键修正）', content: { ...versions[1].content, docNo: manualNumber } };
  versions.push({ ...versions[1], v: 3, by: '王敏', content: { ...versions[1].content, docNo: manualNumber } });
  const { api, policy, stored } = boot({ stored: JSON.stringify(old) });
  assert.ok(!(await policy.items()).items.some((p) => p.id === 'PI-08'));
  assert.equal(api.state().myTodos[0].id, '测试待办');
  assert.equal(api.state().drafts['DOC-1112'].versions[0].content.docNo, '');
  assert.equal(api.state().drafts['DOC-1112'].versions[1].content.docNo, '');
  const migrated = JSON.parse(stored());
  assert.equal(migrated.demoSeedVersion, 3);
  assert.equal(latest(migrated.drafts['DOC-1112']).docNo, manualNumber);

  // 已使用 v2 的缓存里，即便文号碰巧与旧自动值相同，也已属于用户内容。
  migrated.demoSeedVersion = 2;
  migrated.drafts['DOC-1112'].versions[0].content.docNo = '京技产促〔2026〕51号';
  const reopened = boot({ stored: JSON.stringify(migrated) });
  assert.equal(reopened.api.state().drafts['DOC-1112'].versions[0].content.docNo, '京技产促〔2026〕51号');
  const resource = documentRoute + '/drafts/DOC-1112';
  const content = { ...latest(reopened.api.state().drafts['DOC-1112']), docNo: manualNumber };
  await reopened.api.put(resource, { content });
  let snapshot = reopened.stored();
  for (let refresh = 0; refresh < 2; refresh++) {
    const page = boot({ stored: snapshot });
    assert.equal(latest((await page.api.get(resource)).item).docNo, manualNumber);
    snapshot = page.stored();
  }
});

test('历史政策草稿仍须按可信映射核对金额和依据，无替代时阻止送审', async () => {
  const baseline = boot();
  const inputs = { policy: 'RP-006', start: '2026-11-18', end: '2026-12-01', contact: '请填写' };
  const { item: current } = await baseline.api.post(documentRoute + '/drafts', { templateId: 'T03', inputs });
  const stale = plain(latest(current));
  stale.paragraphs[0] = '根据旧发文，现就算力券申报有关事项说明如下。';
  stale.paragraphs[2] = '二、支持标准。按照投入的30%，最高123万元。';
  const state = baseline.api.state();
  state.drafts[current.id].policyId = 'PI-08';
  state.drafts[current.id].versions[0].content = stale;
  state.drafts['DOC-REMOVED'] = { ...state.drafts[current.id], id: 'DOC-REMOVED', policyId: 'PI-18' };

  const { api } = boot({ stored: JSON.stringify(state) });
  const resource = documentRoute + '/drafts/' + current.id;
  const { issues } = await api.post(resource + '/check', {});
  assert.ok(issues.some((i) => i.kind === '数字一致' && i.text.includes('2000 万元')));
  assert.ok(issues.some((i) => i.kind === '政策依据' && i.text.includes('RP-006')));
  await assert.rejects(api.post(resource + '/submit', {}), { status: 422, code: 'CHECK_FAILED' });
  assert.equal((await api.get(resource)).item.status, '草稿');
  const removed = documentRoute + '/drafts/DOC-REMOVED';
  assert.ok((await api.post(removed + '/check', {})).issues.some((i) => i.text.includes('重新选择')));
  await assert.rejects(api.post(removed + '/submit', {}), { status: 422, code: 'CHECK_FAILED' });

  await api.put(resource, { content: latest(current) });
  assert.equal((await api.post(resource + '/submit', {})).item.status, '审签中');
  assert.deepEqual(plain((await api.get(resource)).item.versions[0].content), stale);
});
